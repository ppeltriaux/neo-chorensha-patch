"""Build-time start-up: run the original's init once in the X68000 stand-in and snapshot it.

  .venv/bin/python -I tools/preinit.py --orig build/orig --out build/preinit      (make preinit)

The program (build/orig/sz2.bin) runs from its entry in tools/x68k_hle.py until main ($3E78)
reaches its first call of the title menu (`jsr $2A14` at $3F54), at two load bases. Everything
the stand-in sets up (PSP, environment, stack, heap, RAM end) moves with the base, so the two
memories differ exactly at the words that hold addresses: those are the snapshot's pointers.

Writes build/preinit/:
  snapshot.json  resume point (pc, registers, sp, stack), layout, heap blocks, pointers, and every
                 call and I/O write the start-up made; all addresses base-0 (program at 0).
  memory.bin     base-0 memory [0, end of the last heap block): text, data, bss, the gap, the
                 C stack (live frames from sp up; the dead part below sp zeroed), the
                 environment copy and the malloc arena, pointers made base-0.
  below_base.bin [base-$12D64, base): the command line, environment and PSP the stand-in made
                 (pointers base-0; some snapshot pointers target them: pointer_targets_outside).
  bgtext.bin     BG text page 1 (64 x 64 words) as the game-start loader $6512 reads it back
                 through IOCS _BGTEXTGT: that loader run once in the stand-in after the snapshot
                 (game_start_bg; snapshot.json "game_start"). The shim serves _BGTEXTGT from it.

snapshot.json keys beyond the plan's: pointer_regs (registers holding addresses: their value in
regs is base-0), pointers_below_base, pointer_tags (tagged addresses: top byte kept, low 24 bits
moved), pointer_targets_outside (pointers to the PSP, environment, command line or RAM end),
relocs_not_pointers (relocated words init overwrote with a non-address: none), supervisor, sr,
xsp_entries, mcdrv_calls, float_calls, io_reads / io_reads_unwritten / system_reads (what was
read and from where), console (what the start-up printed), system (FLOAT2 and its __RND state,
clock, MCDRV, SSP), pointer_regs_outside (pointer registers whose target is outside memory.bin),
io_final / io_final_text_vram (I/O state at the resume point: every register written with its
last value; text VRAM as runs of equal bytes), after_resume (static reachability from the resume
point: whether the __RND table builder can run again, and every FLOAT/DOS F-line reachable).
Every logged event carries "seq" (one counter over the run): merge by seq for the true order.
io_writes entries carry the writing instruction's pc (Unicorn reports it exactly except, at
times, for the first access after control enters a block of code, where it gives the block's
start) and "via" for the palette writes the stand-in makes on behalf of an IOCS call.
"""
import argparse
import json
import os
import re
import struct
import sys

from capstone import Cs, CS_ARCH_M68K, CS_MODE_BIG_ENDIAN, CS_MODE_M68K_000

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import census_report  # noqa: E402
import x68k_hle  # noqa: E402
import x68k_names  # noqa: E402

BASE_A = 0x50F40            # the base MAME loaded the program at in every census run
BASE_B = BASE_A + 0x41230   # 16-byte aligned; low 16 bits non-zero: an address kept in a word shows
RESUME = 0x3F54             # main ($3E78): jsr $2A14 (title menu)
TITLE = 0x2A14
XSP_TEXT = (0, census_report.XSP_TEXT_END)   # XSP's code (inventory: link order)

# XC library variables (startup $14B04, ram-census.md)
XC_STACK_LO, XC_STACK_HI = 0x2BC44, 0x2BC48     # C stack bottom / top
XC_HEAP_HEAD = 0x2BC4C                          # malloc arena head

_md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000)


def insn_text(image, at):
    """(text, size) of the instruction at `at` as capstone prints it ("jsr $2a14.l"), or
    (None, 0). Code is checked by its decoded form: no original bytes in the repository."""
    for i in _md.disasm(bytes(image[at:at + 10]), at):
        return ("%s %s" % (i.mnemonic, i.op_str)).strip(), i.size
    return None, 0


def is_jsr_abs_long(image, at):
    """True if `jsr <absolute long>` starts at `at`."""
    text, size = insn_text(image, at)
    return size == 6 and text is not None and text.startswith("jsr $") and text.endswith(".l")
PLAY_LOOP = 0x4020
# The play-loop entry's background loader (BG_PCG.SP and sam.* through stdio, BG text page 1
# through $3536): it then reads all of page 1 back cell by cell through IOCS _BGTEXTGT ($679C)
# to draw the background into graphic VRAM. Run once after the snapshot (game_start_bg).
GAME_START_BG = 0x6512
RND_TABLE = 0x4AE2          # the only caller of FLOAT's __RND ($1539E), from $62BA (init)
# FLOAT2's __RND state (its code at $FE40: index word, then 55 longs; offsets from its load
# address, read from the depacked driver): carried in the snapshot in case a port needs it.
FLOAT2_RND_INDEX, FLOAT2_RND_TABLE, FLOAT2_RND_LONGS = 0x5176, 0x51FE, 55
MAX_HEAP_BLOCKS = 4096

# ROM-candidate bytes (census) whose value at the snapshot is expected to differ from the MAME
# dumps, with the reason. Empty: the stand-in reproduces every one (see x68k_hle's docstring for
# the choices that make it so: MCDRV resident, FLOAT2's clock, the CPU-power clock).
EXPECTED_ROM_MISMATCHES = {}


def find_pointers(a, b, delta):
    """Offsets of the 32-bit words (even offsets) where `b` - `a` = `delta`, covering every byte
    that differs; ValueError on a difference no such word explains."""
    out = []
    covered = -1
    n = len(a)
    for d in range(n):
        if a[d] == b[d] or d <= covered:
            continue
        for s in range(max(0, (d - 3) & ~1), d + 1, 2):
            if s <= covered or s + 4 > n:
                continue
            wa, = struct.unpack_from(">I", a, s)
            wb, = struct.unpack_from(">I", b, s)
            if (wb - wa) & 0xFFFFFFFF == delta:
                out.append(s)
                covered = s + 3
                break
        else:
            raise ValueError("unexplained difference at $%X" % d)
    return out


def xsp_entries(inv, image, meta):
    """XSP C entries: the matched ones, and the four modified ones at their candidate offsets,
    each confirmed by a `jsr` from the game's code."""
    ent = dict(inv["xsp"])
    for name, info in inv["xsp_unmatched"].items():
        ent[name] = info["best"]["at"]
    called = set()
    for r in meta["relocs"]:
        if r >= XSP_TEXT[1] and is_jsr_abs_long(image, r - 2):
            t, = struct.unpack_from(">I", image, r)
            if t < XSP_TEXT[1]:
                called.add(t)
    for name in inv["xsp_unmatched"]:
        if ent[name] not in called:
            raise ValueError("XSP candidate %s $%X: no jsr from the game" % (name, ent[name]))
    unknown = called - set(ent.values())
    if unknown:
        raise ValueError("jsr into XSP at %s: not a known entry" %
                         ", ".join("$%X" % t for t in sorted(unknown)))
    return ent


def walk_heap(m):
    """The XC malloc chain: [(start, size, used)] in base-0 offsets (12-byte headers: prev, end
    with $FE in the top byte when free, next; size = up to the next block)."""
    b = m.base
    head = m.r32(b + XC_HEAP_HEAD)
    out = []
    blk = m.r32(head + 8)
    prev = head
    while blk:
        if not prev < blk < m.ram_end or len(out) >= MAX_HEAP_BLOCKS:
            raise RuntimeError("XC heap chain broken at $%X (after $%X)" % (blk - b, prev - b))
        prev = blk
        end, nxt = m.r32(blk + 4), m.r32(blk + 8)
        used = end >> 24 != 0xFE
        stop = nxt if nxt else ((end & 0xFFFFFF) + 1) & ~1
        out.append((blk - b, stop - blk, used))
        blk = nxt
    return head - b, out


def find_ci(root, *parts):
    """Path under `root` with each part matched case-insensitively (the disk is Human68k's)."""
    cur = root
    for p in parts:
        hit = [n for n in os.listdir(cur) if n.upper() == p.upper()]
        if not hit:
            raise FileNotFoundError(os.path.join(cur, p))
        cur = os.path.join(cur, hit[0])
    return cur


def reachable_after_resume(image, meta, inv, roots):
    """Code reachable once main resumes: a recursive descent over the game and XC library text
    from `roots`, following branches, calls, the switch tables (inventory) and every reference
    to a known function start in reachable code (`lea`/`pea`/`move.l #f`: handlers stored at run
    time). XSP's code is not entered (the shim replaces it). Returns (instruction addresses,
    {F-line word: [sites]})."""
    text = meta["text"]
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000)
    funcs = set(inv["functions"]) | {int(k) for k in inv["pointers"]}
    tables = {t["at"]: t for t in inv["tables"]}
    no_return = {0xFF00, 0xFF31, 0xFF4C}               # _EXIT, _KEEPPR, _EXIT2
    seen, fline = set(), {}
    work = list(roots)
    while work:
        pc = work.pop()
        while XSP_TEXT[1] <= pc < text and pc not in seen:
            w, = struct.unpack_from(">H", image, pc)
            seen.add(pc)
            if w & 0xF000 == 0xF000:
                fline.setdefault(w, []).append(pc)
                if w in no_return:
                    break
                pc += 2
                continue
            ins = next(md.disasm(image[pc:pc + 10], pc), None)
            if ins is None:
                break
            m, ops = ins.mnemonic, ins.op_str
            if pc in tables:
                t = tables[pc]
                work += [t["base"] + struct.unpack_from(">h", image, t["base"] + 2 * i)[0]
                         for i in range(t["cases"])]
            for h in re.findall(r"\$([0-9a-f]+)", ops):
                v = int(h, 16)
                if v in funcs:
                    work.append(v)
            flow = m.startswith(("b", "db", "jmp", "jsr")) and \
                not m.startswith(("btst", "bset", "bclr", "bchg"))
            tgt = re.match(r"^\$([0-9a-f]+)(\.[lw])?$", ops)
            if flow and tgt:
                work.append(int(tgt.group(1), 16))
            if m.startswith(("bra", "jmp")) or m in ("rts", "rte", "rtr"):
                break
            pc += ins.size
    return seen, fline


def _where(layout, t):
    """The layout range a base-0 address falls in (memory_bin aside), or "ram_end"."""
    return next((k for k, v in layout.items() if isinstance(v, list) and k != "memory_bin"
                 and v[0] <= t < v[0] + v[1]), "ram_end" if t == layout["ram_end"] else None)


def _run(image, meta, base, game_dir, ent, float2):
    m = x68k_hle.X68k(image, meta, base, game_dir, ent, RESUME, xsp_text=XSP_TEXT, float2=float2)
    m.run()
    return m


def _logs(m):
    return {"dos_calls": m.dos_calls, "iocs_calls": m.iocs_calls, "xsp_calls": m.xsp_calls,
            "mcdrv_calls": m.mcdrv_calls, "float_calls": m.float_calls, "io_writes": m.io_writes,
            "interrupts": m.interrupts, "system_calls": m.system_calls,
            "console": b"".join(m.console).hex(),
            "io_reads": m.io_reads, "io_reads_unwritten": m.io_reads_unwritten,
            "low_reads": m.low_reads}


def _files_in(data, contents):
    hits = []
    for name, c in contents.items():
        if len(c) >= 32:
            i = data.find(c)
            if i >= 0:
                hits.append((i, name))
    return [n for _, n in sorted(hits)]


def game_start_bg(m):
    """Run the game-start background loader (GAME_START_BG) once in the stand-in, from the state
    the start-up left (after the snapshot was taken: its logs are set aside first), and return
    (BG text page as its _BGTEXTGT reads saw it: 64 x 64 big-endian words, row-major; a summary).
    What the loader reads back depends only on the files and its own code, so it is the same at
    every game start (and equals what the IOCS gave the original: tests/x68k/bgtext.lua)."""
    for k in ("dos_calls", "iocs_calls", "xsp_calls", "mcdrv_calls", "float_calls", "io_writes",
              "interrupts", "console", "system_calls"):
        setattr(m, k, [])
    for k in ("io_reads", "io_reads_unwritten", "low_reads"):
        setattr(m, k, {})
    m.call(GAME_START_BG, gvram=True)
    reads = [c for c in m.iocs_calls if c["name"] == "_BGTEXTGT"]
    pages = sorted({c["d1"] for c in reads})
    if len(pages) != 1:
        raise RuntimeError("game start: _BGTEXTGT reads pages %s" % pages)
    cells = {}
    for c in reads:
        if cells.setdefault((c["d2"], c["d3"]), c["ret"]) != c["ret"]:
            raise RuntimeError("game start: _BGTEXTGT cell (%d, %d) read twice, differently" %
                               (c["d2"], c["d3"]))
    if len(cells) != 64 * 64:
        raise RuntimeError("game start: %d BG cells read, not the whole page" % len(cells))
    out = bytearray(x68k_hle.BG_PAGE_SIZE)
    for (x, y), v in cells.items():
        struct.pack_into(">H", out, (y * 64 + x) * 2, v & 0xFFFF)
    lo = x68k_hle.BG_DATA + pages[0] * x68k_hle.BG_PAGE_SIZE
    return bytes(out), {
        "call": GAME_START_BG, "page": pages[0], "cells": len(cells), "reads": len(reads),
        "bg_writes": sum(1 for w in m.io_writes if lo <= w["addr"] < lo + x68k_hle.BG_PAGE_SIZE),
        "dos_files": [c["file"] for c in m.dos_calls if c["call"] == "_OPEN"],
        "xsp_calls": [c["name"] for c in m.xsp_calls],
        "iocs": sorted({c["name"] for c in m.iocs_calls}),
        "note": "build/preinit/bgtext.bin: BG text page %d as the loader's _BGTEXTGT reads ($679C) "
                "see it; the shim serves _BGTEXTGT from it" % pages[0]}


def run(orig_dir, game_dir, float2=None):
    with open(os.path.join(orig_dir, "sz2.bin"), "rb") as f:
        image = f.read()
    with open(os.path.join(orig_dir, "sz2.json")) as f:
        meta = json.load(f)
    with open(os.path.join(orig_dir, "inventory.json")) as f:
        inv = json.load(f)
    if float2 is None:
        float2 = find_ci(os.path.dirname(os.path.abspath(game_dir)), "SYS", "FLOAT2.X")
    if insn_text(image, RESUME) != ("jsr $%x.l" % TITLE, 6):
        raise ValueError("$%X is not main's jsr $%X" % (RESUME, TITLE))
    ent = xsp_entries(inv, image, meta)
    ma = _run(image, meta, BASE_A, game_dir, ent, float2)
    mb = _run(image, meta, BASE_B, game_dir, ent, float2)
    delta = BASE_B - BASE_A

    head, heap = walk_heap(ma)
    head_b, heap_b = walk_heap(mb)
    if (head, heap) != (head_b, heap_b):
        raise RuntimeError("the heap differs between the two bases")
    top = max(s + n for s, n, _ in heap) if heap else ma.prog_end
    lo = x68k_hle.BELOW_BASE
    sp_a, sp_b = ma.reg(x68k_hle.UC_M68K_REG_A7), mb.reg(x68k_hle.UC_M68K_REG_A7)
    if sp_b - sp_a != delta:
        raise RuntimeError("sp does not move with the base")
    sp = sp_a - BASE_A
    stack_lo = ma.r32(BASE_A + XC_STACK_LO) - BASE_A
    stack_hi = ma.r32(BASE_A + XC_STACK_HI) - BASE_A
    # The C stack below sp is dead (whatever the start-up's calls left there): zero in the
    # snapshot, at both bases, so it holds no stale pointers. The live frames (sp up) stay.
    mem_a = bytearray(ma.mu.mem_read(BASE_A + lo, top - lo))
    mem_b = bytearray(mb.mu.mem_read(BASE_B + lo, top - lo))
    for m_ in (mem_a, mem_b):
        m_[stack_lo - lo:sp - lo] = bytes(sp - stack_lo)
    mem_a, mem_b = bytes(mem_a), bytes(mem_b)
    words = [w + lo for w in find_pointers(mem_a, mem_b, delta)]
    # Everything outside the snapshot window (vectors, the fake MCDRV, FLOAT2, the free RAM up to
    # the RAM end) must be the same at both bases: nothing the program keeps lies outside it.
    ram = []
    for m, base in ((ma, BASE_A), (mb, BASE_B)):
        r = bytearray(m.mu.mem_read(0, x68k_hle.MEM_TOP))
        r[base + lo:base + top] = bytes(top - lo)
        ram.append(r)
    if ram[0] != ram[1]:
        at = next(i for i in range(len(ram[0])) if ram[0][i] != ram[1][i])
        raise RuntimeError("memory outside the snapshot window differs between the bases at $%X" % at)
    del ram

    # registers and sp at the resume point
    ra, rb = ma.regs(), mb.regs()
    pointer_regs, regs = [], {}
    for n in x68k_hle.REG_NAMES:
        d = (rb[n] - ra[n]) & 0xFFFFFFFF
        if d == delta:
            pointer_regs.append(n)
            regs[n] = x68k_hle.s32(ra[n] - BASE_A)
        elif d == 0:
            regs[n] = ra[n]
        else:
            raise RuntimeError("register %s differs between the bases by $%X" % (n, d))

    # memory.bin: base-0 [0, top), every pointer word made base-0. A word with a non-zero top
    # byte is a tagged address (XC malloc marks a free block's end with $FE): the 68000 uses
    # the low 24 bits, so those move and the tag stays (listed in pointer_tags).
    mem = bytearray(mem_a[-lo:])
    below = bytearray(mem_a[:-lo])
    tags = {}
    targets = {}
    for w in words:
        buf, at = (mem, w) if w >= 0 else (below, w - lo)
        v, = struct.unpack_from(">I", buf, at)
        tag, t = v >> 24, (v & 0xFFFFFF) - BASE_A
        if tag:
            tags[w] = tag
            struct.pack_into(">I", buf, at, tag << 24 | t & 0xFFFFFF)
        else:
            struct.pack_into(">I", buf, at, t & 0xFFFFFFFF)
        targets[w] = t

    layout = {
        "program": [0, ma.prog_end],
        "text": [0, meta["text"]], "data": [meta["text"], meta["data"]],
        "bss": [meta["text"] + meta["data"], meta["bss"]],
        "post_bss": [ma.prog_end, stack_lo - ma.prog_end],
        "stack_area": [stack_lo, stack_hi - stack_lo],
        "pre_heap": [stack_hi, head - stack_hi],
        "heap_head": [head, 16],
        "heap": [head + 16, top - head - 16],
        "psp": [x68k_hle.PSP_OFF, 0x100],
        "env": [x68k_hle.ENV_OFF, 4 + x68k_hle.ENV_SIZE],
        "cmdline": [x68k_hle.CMDLINE_OFF, 2],
        "memory_bin": [0, top],
        "below_base_bin": [lo, -lo],
        "ram_end": x68k_hle.RAM_END_OFF,
    }
    reg_outside = {}
    for n in pointer_regs:
        t = regs[n]
        if not 0 <= t <= top:
            reg_outside[n] = {"target": t, "in": _where(layout, t)}
    outside = []
    for w in words:
        t = targets[w]
        if not 0 <= t <= top:
            outside.append({"addr": w, "target": t, "in": _where(layout, t)})

    contents = {}
    for c in ma.dos_calls:
        if c["call"] == "_OPEN" and c.get("file") and c["file"] not in contents:
            with open(os.path.join(game_dir, c["file"]), "rb") as f:
                contents[c["file"]] = f.read()
    heap_out = []
    for s, n, used in heap:
        files = _files_in(bytes(mem[s + 12:s + n]), contents) if used else []
        heap_out.append({"start": s, "size": n, "used": used,
                         "file": files[0] if len(files) == 1 else None, "files": files})

    # what runs after the resume point: main's continuation, the title menu, the play loop, the
    # handlers the game has installed, and every code address held in data, bss, heap or stack
    roots = {RESUME + 6, TITLE, PLAY_LOOP}
    roots |= {i["handler"] for i in ma.interrupts if XSP_TEXT[1] <= i["handler"] < meta["text"]}
    for w in words:
        if w >= meta["text"] or (w >= 0 and w not in set(meta["relocs"])):
            t = targets[w]
            if XSP_TEXT[1] <= t < meta["text"]:
                roots.add(t)
    code, fline = reachable_after_resume(image, meta, inv, sorted(roots))
    after = {
        "roots": len(roots), "instructions": len(code),
        "rnd_table_reachable": RND_TABLE in code,
        "float_calls": [{"fn": "$%04X" % f, "name": x68k_names.FEFUNC.get(f, "?"), "sites": sites}
                        for f, sites in sorted(fline.items()) if 0xFE00 <= f < 0xFF00],
        "dos_calls": [{"fn": "$%04X" % f, "name": x68k_names.DOS.get(f, "?"), "sites": sites}
                      for f, sites in sorted(fline.items()) if f >= 0xFF00],
    }
    rnd = {"index_at": "FLOAT2+$%X" % FLOAT2_RND_INDEX, "table_at": "FLOAT2+$%X" % FLOAT2_RND_TABLE,
           "index": ma.r16(x68k_hle.FLOAT2_AT + FLOAT2_RND_INDEX),
           "table": [ma.r32(x68k_hle.FLOAT2_AT + FLOAT2_RND_TABLE + 4 * i)
                     for i in range(FLOAT2_RND_LONGS)]}

    # the I/O state at the resume point: every register written, and text VRAM as runs
    io_final, seen_regs = [], set()
    for w in ma.io_writes:
        a = w["addr"]
        if not 0xE00000 <= a < 0xE80000 and (a, w["size"]) not in seen_regs:
            seen_regs.add((a, w["size"]))
    for a, n in sorted(seen_regs):
        off = a - x68k_hle.IO_LO
        io_final.append({"addr": a, "size": n, "value": int.from_bytes(ma.io[off:off + n], "big")})
    tvram, run_ = [], None
    for off in range(0, 0x80000):
        if ma.io_written[off]:
            v = ma.io[off]
            if run_ and run_["start"] + run_["size"] == 0xE00000 + off and run_["value"] == v:
                run_["size"] += 1
            else:
                run_ = {"start": 0xE00000 + off, "size": 1, "value": v}
                tvram.append(run_)

    la, lb = _logs(ma), _logs(mb)
    diff = [k for k in la if json.dumps(la[k], sort_keys=True) != json.dumps(lb[k], sort_keys=True)]

    snap = {
        "resume_pc": RESUME,
        "regs": regs, "pointer_regs": pointer_regs,
        "sp": sp,
        # the stand-in's CPU runs in supervisor mode throughout; the original's mode at the
        # resume point is the virtual one (_SUPER/_B_SUPER): sr as the original has it
        "sr": ma.reg(x68k_hle.UC_M68K_REG_SR) & (0xFFFF if ma.super else 0xDFFF),
        "supervisor": ma.super,
        "stack": [sp, stack_hi - sp],
        "layout": layout,
        "heap": heap_out,
        "pointers": [w for w in words if w >= 0],
        "pointers_below_base": [w for w in words if w < 0],
        "pointer_regs_outside": reg_outside,
        "pointer_tags": {str(w): t for w, t in sorted(tags.items())},
        "pointer_targets_outside": outside,
        "relocs_not_pointers": sorted(set(meta["relocs"]) - set(words)),
        "xsp_entries": {k: v for k, v in sorted(ent.items(), key=lambda kv: kv[1])},
        "xsp_calls": ma.xsp_calls, "iocs_calls": ma.iocs_calls, "dos_calls": ma.dos_calls,
        "mcdrv_calls": ma.mcdrv_calls, "float_calls": ma.float_calls,
        "io_writes": ma.io_writes, "interrupts": ma.interrupts,
        "io_final": io_final, "io_final_text_vram": tvram,
        "after_resume": after,
        "io_reads": ma.io_reads, "io_reads_unwritten": ma.io_reads_unwritten,
        "system_reads": ma.low_reads,
        "console": b"".join(ma.console).decode("cp932", "replace"),
        "system": {"float2": ma.float2, "float2_init_calls": ma.system_calls,
                   "clock": {"date": x68k_hle.CLOCK_DATE, "time": x68k_hle.CLOCK_TIME},
                   "float2_rnd": rnd,
                   "mcdrv": {"vector": x68k_hle.MCDRV_ENTRY, "long": x68k_hle.MCDRV_LONG},
                   "ssp": x68k_hle.SSP_VALUE},
        "bases": [BASE_A, BASE_B],
    }
    # last (it changes ma's memory and logs): the game-start loader's BG page read-back
    bgtext, snap["game_start"] = game_start_bg(ma)
    return {"snapshot": snap, "bgtext": bgtext, "memory": bytes(mem), "below_base": bytes(below),
            "mem_a": mem_a, "mem_b": mem_b, "mem_lo": lo, "delta": delta,
            "base_a": BASE_A, "base_b": BASE_B, "regs_a": ra, "regs_b": rb,
            "sp_a": sp_a, "sp_b": sp_b, "logs_equal": not diff, "logs_diff": diff,
            "expected_rom_mismatches": EXPECTED_ROM_MISMATCHES}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    game = os.path.join(a.orig, "disk", "GAME")
    res = run(a.orig, game)
    if not res["logs_equal"]:
        raise SystemExit("preinit: call logs differ between the two bases: %s" % res["logs_diff"])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "snapshot.json"), "w") as f:
        json.dump(res["snapshot"], f, indent=1)
    with open(os.path.join(a.out, "memory.bin"), "wb") as f:
        f.write(res["memory"])
    with open(os.path.join(a.out, "below_base.bin"), "wb") as f:
        f.write(res["below_base"])
    with open(os.path.join(a.out, "bgtext.bin"), "wb") as f:
        f.write(res["bgtext"])
    s = res["snapshot"]
    print("preinit: resume $%X sp $%X (stack %d B), %d pointers (+%d below the base), %d heap blocks, "
          "%d DOS / %d IOCS / %d XSP / %d MCDRV calls, %d I/O writes; memory.bin %d B" % (
              s["resume_pc"], s["sp"], s["stack"][1], len(s["pointers"]), len(s["pointers_below_base"]),
              len(s["heap"]), len(s["dos_calls"]), len(s["iocs_calls"]), len(s["xsp_calls"]),
              len(s["mcdrv_calls"]), len(s["io_writes"]), len(res["memory"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
