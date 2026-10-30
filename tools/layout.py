"""Object layout for the Neo Geo: where every byte of the original's memory lives.

  .venv/bin/python -I tools/layout.py --orig build/orig --census data/census.json \\
      --preinit build/preinit --out build/link/layout.json --md docs/notes/layout.md   (make layout)

Inputs: sz2.bin/sz2.json (relocations), the census (per-byte live / ROM candidate / init only /
untouched, the relocation-target split of tools/census_report.py), the start-up snapshot
(build/preinit: memory.bin, below_base.bin, snapshot.json; base-0 offsets throughout).

Objects. Text is split into code runs and the data islands between them (bytes no decoded
instruction covers), the islands cut at every reference target (relocation targets, PC-relative
operands, snapshot pointers). Data and bss are cut at the relocation targets (census_report's
segment()). Each heap block is its 12-byte malloc header plus its data; the arena head, the gaps
after bss and before the heap, the C stack (its top STACK_SIZE bytes, the rest dead) and the
command line / environment / PSP below the base are objects of their own. Together they cover
memory.bin [0, end of the last heap block) once, plus the three pieces below the base.

Rules, in order:
  1. Adjacent pieces of one array merge (merge_objects): a known array (KNOWN_ARRAYS: char_table,
     the player-shot tables in text); an access whose bytes cross a boundary; a displacement from
     a register holding an object's address that lands in another object; an indexed access
     (d8(An,Xn), d8(PC,Xn)) from a base, over the first element (the index's scale, found in the
     instructions before it: asl/lsl #k, add Xn,Xn, mulu #n); a census written-after-init run
     crossing a boundary. Merges stay inside one census region and never take in code.
  2. A group any piece of which an instruction of the game or the XC library that can run after
     the resume point writes (static scan below; reachability from tools/preinit.py, the set
     behind snapshot.json's after_resume: stores by the start-up already happened and their
     results are in the snapshot) or that the census counts as game state (written after init by
     game, library or system code; census_report's "counted" owner) goes to RAM. So does the
     part of XC malloc's arena that malloc and free use after the resume point (fopen's 1 KB
     buffer at every game start, arena_after_resume): the arena head, the free block at malloc's
     rover and the next block's header, placed together as in the original (malloc measures
     the distance between headers).
  3. XSP's text variables, its bss and the PCG_ALT heap block (and anything only XSP's code
     wrote) go to the shim: no address in the game's RAM, every reference to SHIM_DEAD.
  4. The other malloc headers and free heap blocks, unreferenced gaps and the dead part of the
     stack are dropped (same treatment).
  5. Everything else (ROM candidates, init only, untouched, loaded files, the reloaded sam.*
     buffers) is ROM, holding its snapshot value. Code is ROM.

Static write scan (static_accesses): every decoded instruction of the game and the XC library
(XSP's code, below XSP_TEXT_END, is replaced by the shim and not scanned), every memory operand,
with the 68000's write forms (move, clr, add/sub/and/or/eor, neg/not/negx, addq/subq, bset/bclr/
bchg, Scc, tas, movem, addx/subx/abcd/sbcd, ...; direction from tools/inventory.py's _access).
A destination counts when it is an absolute (relocated) or PC-relative address, or an address
register whose value a forward dataflow over the function knows to be a program address: loaded
by `lea abs,An` / `lea d(pc),An`, `move.l #abs,An` / `movea.l #abs,An`, copied between
registers, offset by lea d(An)/addq/subq/adda #, and carried into functions reached only by direct
calls (the meet of the callers' states, as inventory.regstates does for hardware pointers). Loops
make a register inexact (the index is unknown): the store counts against the object the register
started in. A register loaded from a pointer variable counts only for pointers to the PSP,
environment or command line (no other way reaches them). Stores through registers the dataflow
does not know (pointer arguments, structure pointers loaded from memory) are not resolved: those
objects stay as the census says, and a ROM object written that way is Task 5's tripwire's to catch.

Placement: text at GAME_ROM + offset (in place, so PC-relative code works), then the ROM objects
in original order (pieces adjacent in the original stay adjacent; an odd start keeps an odd
address), then SHIM_DEAD (SHIM_DEAD_SIZE bytes). RAM objects from RAM_LO in original order the
same way; ram_used is their extent. The stack's top STACK_SIZE bytes sit under STACK_TOP. Text
variables placed in RAM leave their old bytes in the text image; the instructions that reach them
PC-relatively cannot follow and are listed in pcrel_fixups for link.py.
"""
import argparse
import bisect
import json
import os
import struct
import sys
from collections import Counter

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import census_report as cr  # noqa: E402
import inventory as inv  # noqa: E402

GAME_ROM = 0x010000          # P-ROM address of the relocated text
RAM_LO = 0x100000            # game objects placed in RAM: $100000-$106FFF (Plan 3 RAM map:
RAM_LIMIT = 0x7000           # $107000-$10AFFF is the shim extension, the sprite lists)
STACK_TOP = 0x10F000         # stack $10E000-$10EFFF
STACK_SIZE = 4096
ROM_END = 0x100000           # one 1 MB P1
SHIM_DEAD_SIZE = 64
XSP_TEXT_END = cr.XSP_TEXT_END   # XSP's code and text variables: $0-$1575 (inventory: link order)
HEAP_HEADER = cr.HEAP_HEADER
CALLER_SAVED = ("d0", "d1", "d2", "a0", "a1", "a2")
# Arrays known from the census notes and docs/notes/game-globals.md (base-0 start, size, name).
KNOWN_ARRAYS = [
    (0x278A6, 0x4000, "char_table: 128 x $80 object array"),
    (0x2650, 0x27E0 - 0x2650, "game tables in text: cleared by $2636, player-shot boxes to $27DF"),
    (0x26992, 0x27892 - 0x26992, "30 x $80 array: `adda.l #$26992,a5` at $7176, a5 stepped by -$80 "
                                 "at $75D8 (its last entry $27812 is named on its own)"),
    (0x2B8B6, 40 * 0x16, "_iob: XC stdio's 40 FILE structures of $16 bytes; fopen's slot "
                         "search $16534 steps a0 by $16 from $2B8B6 and fopen stores into the "
                         "slot it finds (sam.* at every game start), fclose ($149DC) divides by "
                         "$16"),
]
# XC library malloc (ram-census.md "Heap"): first fit from the rover, 12-byte headers (prev, end
# with $FE in the top byte when free, next), arena head at [XC_HEAP_HEAD].
XC_MALLOC = 0x15560
XC_ROVER = 0x2BC58
XC_HEAP_HEAD = 0x2BC4C
XC_ARENA_HEAD = 16
# Reviewed verdicts on the indexed tables unmerged_indexed lists (base offset: why it may stay).
UNMERGED_NOTES = {
    0x1750A: "3-word table indexed by the value of $17510 (0-2)",
    0x177B6: "256-word table (512 B): the index is a byte",
    0x17C7A: "10-word table indexed by stick() (0-9)",
    0x22152: "indexed by $2218E, a count kept above 0 inside the table's own range",
    0x157D6: "48-byte library table, PC-relative, read only",
    0x26592: "1 KB table the start-up fills (ROM); read after resume mostly as 256 x 4 "
             "(strides 4, 8, 64): 104 of the 117 reads' indexes proven in bounds "
             "(tools/bounds.py), 11 more read in the lock-step (make lockstep), 2 neither: "
             "type $182's handler, never run: no object of type $182 is created "
             "(tools/bounds.py audit_spawn; docs/notes/graphics.md, \"The $26592 table\")",
    0x2B8B6: "_iob, 40 x $16 bytes: the start-up's clear ($14CA0) covers exactly $370 bytes, "
             "fopen's slot search ($1653C) stops after 40 entries",
    0x2BC74: "96 x 4 table (384 B), read only",
}
HOMES = ["ram", "rom", "shim", "drop", "stack"]
STARTUP_NOTE = "; stored only by start-up code (not reachable after the resume point)"

_md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_000)
_md.detail = True


def _insn_text(img, at):
    """(text, size) of the instruction at `at` as capstone prints it, or (None, 0). Code is
    matched by its decoded form: no original bytes in the repository."""
    for i in _md.disasm(bytes(img[at:at + 10]), at):
        return ("%s %s" % (i.mnemonic, i.op_str)).strip(), i.size
    return None, 0


# ------------------------------------------------------------------------- static access scan

def _prog_val(img, relocs, ins, op):
    """The program address an abs or immediate operand holds, if relocated in this instruction."""
    if op.kind not in ("abs", "imm"):
        return None
    v = op.val & 0xFFFFFFFF
    return v if inv._is_prog_abs(img, ins, relocs, v) else None


def _transfer(img, relocs, outside, ins, st):
    """Register state after `ins`: {reg: (program address, exact)} (a7 is never tracked)."""
    st = dict(st)
    mn, ops = ins.mn, ins.ops
    if mn in ("link", "unlk"):
        st.pop(ops[0].reg, None)
        return st
    if mn in ("dos", "fefunc", "trap", "jsr", "bsr"):
        for r in CALLER_SAVED:
            st.pop(r, None)
        return st
    for op in ops:
        if op.kind in ("postinc", "predec") and op.reg in st:
            v, e = st[op.reg]
            if mn == "movem":
                st[op.reg] = (v, False)
            elif e:
                n = inv._size(ins)
                st[op.reg] = (v + (n if op.kind == "postinc" else -n), True)
    if mn == "movem" and ops and ops[-1].kind == "regs":
        bits = ops[-1].val
        for i in range(16):
            if bits >> i & 1:
                st.pop(("d%d" % i) if i < 8 else ("a%d" % (i - 8)), None)
        return st
    if mn == "exg":
        x, y = ops[0].reg, ops[1].reg
        vx, vy = st.pop(x, None), st.pop(y, None)
        if vx:
            st[y] = vx
        if vy:
            st[x] = vy
        return st
    if len(ops) != 2 or ops[1].kind not in ("areg", "dreg"):
        if len(ops) == 1 and ops[0].kind in ("areg", "dreg"):
            st.pop(ops[0].reg, None)
        return st
    src, dst = ops
    d = dst.reg
    cur = st.get(d)
    new = None
    if mn == "lea":
        if src.kind == "abs":
            v = _prog_val(img, relocs, ins, src)
            new = (v, True) if v is not None else None
        elif src.kind == "pcrel":
            new = (src.val, True)
        elif src.kind == "disp" and src.reg in st:
            v, e = st[src.reg]
            new = (v + src.val, True) if e else (v, False)
        elif src.kind == "ind" and src.reg in st:
            new = st[src.reg]
        elif src.kind == "idx" and src.reg in st:
            new = (st[src.reg][0] + src.val, False) if st[src.reg][1] else (st[src.reg][0], False)
        elif src.kind == "pcidx":
            new = (src.val, False)
    elif mn in ("move", "movea") and ins.sz == "l":
        if src.kind == "imm":
            v = _prog_val(img, relocs, ins, src)
            new = (v, True) if v is not None else None
        elif src.kind in ("areg", "dreg") and src.reg in st:
            new = st[src.reg]
        elif src.kind == "abs" and outside:
            v = _prog_val(img, relocs, ins, src)
            if v is not None and v in outside:
                new = (outside[v], True)
    elif mn in ("add", "adda", "addi", "addq", "sub", "suba", "subi", "subq"):
        sign = -1 if mn.startswith("sub") else 1
        if src.kind == "imm" and cur is not None and (ins.sz != "w" or dst.kind == "areg"):
            new = (cur[0] + sign * src.val, True) if cur[1] else cur
        elif src.kind == "imm" and cur is None and sign > 0:
            v = _prog_val(img, relocs, ins, src)
            new = (v, False) if v is not None else None
        elif cur is not None:
            new = (cur[0], False)
        elif src.kind in ("areg", "dreg") and src.reg in st and sign > 0:
            new = (st[src.reg][0], False)
    if new is None or d == "a7":
        st.pop(d, None)
    else:
        st[d] = new
    return st


def regstates(code, img, relocs, entry, outside=None):
    """Forward dataflow over the decoded code (inventory.regstates with program addresses): the
    register state at the entry of every instruction."""
    preds, called = set(), set()
    for a, ins in code.ins.items():
        preds.update(inv._successors(code, ins))
        t = inv._call_target(code, ins)
        if t is not None:
            called.add(t)
    fixed = set(code.pointers) | {entry}
    for t, refs in code.xrefs.items():
        if any(k not in ("call", "branch") for _, k in refs):
            fixed.add(t)
    fixed |= {f for f in code.functions if f not in called}
    fixed |= {a for a in code.ins if a not in preds and a not in called}
    states = {a: {} for a in fixed if a in code.ins}
    work = list(states)

    def push(t, st):
        if t not in code.ins or t in fixed:
            return
        if t not in states:
            states[t] = st
            work.append(t)
        else:
            m = inv._meet(states[t], st)
            if m != states[t]:
                states[t] = m
                work.append(t)

    while work:
        a = work.pop()
        ins = code.ins[a]
        st = states[a]
        out = _transfer(img, relocs, outside, ins, st)
        for t in inv._successors(code, ins):
            push(t, out)
        t = inv._call_target(code, ins)
        if t is not None:
            push(t, st)
    return states


def _index_reg(img, ins, opi):
    """The index register of an (An,Xn) / (PC,Xn) operand."""
    i = next(_md.disasm(img[ins.addr:ins.addr + 10], ins.addr, 1))
    r = i.operands[opi].mem.index_reg
    return _md.reg_name(r) if r else None


def _stride(code, prev_of, a, xreg, limit=10):
    """Scale applied to index register `xreg` in the instructions before `a` (same block):
    asl/lsl #k, add Xn,Xn and mulu/muls #n multiply; ext and and keep; any other write defines
    it and stops. None when neither a scale nor the defining instruction is in the block."""
    f, defined = 1, False
    for _ in range(limit):
        if a in code.labels or a in code.functions or a not in prev_of:
            break
        a = prev_of[a]
        ins = code.ins[a]
        ops = ins.ops
        if not ops or ops[-1].kind not in ("dreg", "areg") or ops[-1].reg != xreg:
            if ins.mn in ("jsr", "bsr", "trap", "dos", "fefunc", "movem", "exg", "swap"):
                break
            continue
        mn = ins.mn
        if mn in ("asl", "lsl") and len(ops) == 2 and ops[0].kind == "imm":
            f <<= ops[0].val
        elif mn in ("add", "adda") and len(ops) == 2 and ops[0].kind in ("dreg", "areg") \
                and ops[0].reg == xreg:
            f *= 2
        elif mn in ("mulu", "muls") and ops[0].kind == "imm":
            f *= ops[0].val
            defined = True
            break
        elif mn in ("ext", "and", "andi"):
            continue
        else:
            defined = True
            break
    return f if defined or f > 1 else None


def static_accesses(img, meta, code=None, lo=XSP_TEXT_END, outside=None):
    """Memory accesses with a known program address by the code at or above `lo`: [{at, target,
    size, write, exact, base, disp, stride, via, text}]. `base`: the register's exact value for
    d(An) and indexed forms (None for absolute, PC-relative and inexact registers)."""
    if code is None:
        code = inv.disassemble(img, meta)
    relocs = set(meta["relocs"])
    states = regstates(code, img, relocs, meta["entry"], outside)
    prev_of = {a + ins.size: a for a, ins in code.ins.items()}
    out = []
    for a in sorted(code.ins):
        if a < lo:
            continue
        ins = code.ins[a]
        mn = ins.mn
        if mn in ("lea", "pea", "jmp", "jsr", "dos", "fefunc") or mn.startswith("db") or \
                (mn.startswith("b") and mn not in ("bset", "bclr", "bchg", "btst")):
            continue
        st = states.get(a, {})
        for i, op in enumerate(ins.ops):
            if op.kind not in ("abs", "pcrel", "pcidx", "ind", "postinc", "predec", "disp", "idx"):
                continue
            size = inv._size(ins)
            if mn == "movem":
                size *= bin(ins.ops[1 - i].val).count("1")
            write = "w" in inv._access(ins, i)
            e = {"at": a, "size": size, "write": write, "base": None, "disp": 0, "stride": None,
                 "text": ins.text}
            if op.kind == "abs":
                t = _prog_val(img, relocs, ins, op)
                if t is None:
                    continue
                e.update(target=t, exact=True, via="abs")
            elif op.kind == "pcrel":
                e.update(target=op.val, exact=True, via="pcrel")
            elif op.kind == "pcidx":
                e.update(target=op.val, exact=False, via="pcidx", base=op.val,
                         stride=_stride(code, prev_of, a, op.reg) if op.reg else None)
            elif op.reg in st:
                v, ex = st[op.reg]
                if op.kind == "idx":
                    xr = _index_reg(img, ins, i)
                    e.update(target=v + op.val, exact=False, via="reg", base=v if ex else None,
                             disp=op.val, stride=_stride(code, prev_of, a, xr) if ex and xr else None)
                elif op.kind == "predec":
                    e.update(target=v - size if ex else v, exact=ex, via="reg")
                else:
                    d = op.val if op.kind == "disp" else 0
                    e.update(target=v + d, exact=ex, via="reg",
                             base=v if ex and op.kind == "disp" else None, disp=d)
            else:
                continue
            out.append(e)
    return out


def write_census(img, meta, code=None, lo=XSP_TEXT_END):
    """How far the scan resolves the stores of the code at or above `lo`: memory-operand stores
    by kind (absolute, PC-relative, register known, register unknown, stack/frame)."""
    if code is None:
        code = inv.disassemble(img, meta)
    relocs = set(meta["relocs"])
    states = regstates(code, img, relocs, meta["entry"])
    c = Counter()
    for a, ins in code.ins.items():
        mn = ins.mn
        if a < lo or mn in ("lea", "pea", "jmp", "jsr", "dos", "fefunc") or mn.startswith("db") or \
                (mn.startswith("b") and mn not in ("bset", "bclr", "bchg", "btst")):
            continue
        for i, op in enumerate(ins.ops):
            if op.kind not in ("abs", "pcrel", "ind", "postinc", "predec", "disp", "idx") or \
                    "w" not in inv._access(ins, i):
                continue
            if op.kind == "abs":
                c["absolute, program" if _prog_val(img, relocs, ins, op) is not None
                  else "absolute, hardware/system"] += 1
            elif op.kind == "pcrel":
                c["pc-relative"] += 1
            elif op.reg in states.get(a, {}):
                c["register, program address known"] += 1
            elif op.reg in ("a7", "a6"):
                c["stack or frame (a7/a6)"] += 1
            else:
                c["register, not resolved"] += 1
    return dict(c)


# ------------------------------------------------------------------------------------ merging

def _find(starts, objs, t):
    i = bisect.bisect_right(starts, t) - 1
    if i >= 0 and t < objs[i]["start"] + objs[i]["size"]:
        return i
    return None


def merge_objects(objs, accesses, known=(), live_runs=()):
    """Rule 1. `objs` sorted by start. Returns the groups, each a run of adjacent objects:
    [{"lo": first index, "hi": last index, "why": [reasons]}]."""
    starts = [o["start"] for o in objs]
    link = [None] * len(objs)            # link[i]: reasons joining objs[i] and objs[i + 1]

    def join(a, b, why):
        """Join every object overlapping [a, b) (b > a)."""
        if b <= a:
            return
        i = _find(starts, objs, a)
        j = _find(starts, objs, b - 1)
        if i is None:
            i = bisect.bisect_left(starts, a)
        if j is None:
            j = bisect.bisect_right(starts, b - 1) - 1
        if i >= len(objs) or j < i or i == j:
            return
        area = objs[i].get("area", objs[i].get("region"))
        rng = range(i, j + 1)
        if any(objs[k].get("area", objs[k].get("region")) != area or objs[k].get("code")
               for k in rng):
            return
        if any(objs[k]["start"] + objs[k]["size"] != objs[k + 1]["start"] for k in range(i, j)):
            return
        for k in range(i, j):
            if link[k] is None:
                link[k] = set()
            link[k].add(why)

    for s, n, label in known:
        join(s, s + n, "known array: " + label)
    for x in accesses:
        t, n, b, d = x["target"], x["size"], x.get("base"), x.get("disp", 0)
        if b is None:
            if x.get("exact", True):
                join(t, t + n, "access crossing at $%X" % x["at"])
            continue
        hi_end = b if d < 0 else b + 1             # a negative displacement: b may be an end
        lo_ = min(t, b if d >= 0 else b - 1)
        if x.get("exact", True):
            join(lo_, max(t + n, hi_end), "displacement from $%X at $%X" % (b, x["at"]))
        else:
            s = x.get("stride") or 0
            join(lo_, max(t + n, b + s, hi_end),
                 "indexed from $%X%s at $%X" % (b, " stride %d" % s if s else "", x["at"]))
    for a, b in live_runs:
        if b - a >= 2:
            join(a, b, "census: written run crosses")
    groups = []
    i = 0
    while i < len(objs):
        j = i
        why = set()
        while j < len(objs) - 1 and link[j]:
            why |= link[j]
            j += 1
        groups.append({"lo": i, "hi": j, "why": sorted(why)})
        i = j + 1
    return groups


# --------------------------------------------------------------------------------------- homes

def count_writes(objs, accesses, reach=None):
    """Mark each object with the static stores into it (o["static_writes"], o["writers"]).
    With `reach` (instructions that can run after the resume point), stores by other code (the
    start-up, whose results are in the snapshot) do not count; they are kept in
    o["startup_pcs"]."""
    objs_s = sorted(range(len(objs)), key=lambda k: objs[k]["start"])
    starts = [objs[k]["start"] for k in objs_s]
    sorted_objs = [objs[k] for k in objs_s]
    for x in accesses:
        if not x["write"]:
            continue
        span = x["size"] if x.get("exact", True) else 1
        hit = set()
        for t in range(x["target"], x["target"] + span):
            i = _find(starts, sorted_objs, t)
            if i is not None:
                hit.add(i)
        for i in hit:
            o = sorted_objs[i]
            if reach is not None and x["at"] not in reach:
                o.setdefault("startup_pcs", set()).add(x["at"])
                continue
            o["static_writes"] = o.get("static_writes", 0) + 1
            o.setdefault("writer_pcs", set()).add(x["at"])
            o.setdefault("writers", [])
            if len(o["writers"]) < 4:
                o["writers"].append(x["at"])


def home_of(objs):
    """Rules 2-5 for one group: (home, why)."""
    fixed = next((o for o in objs if o.get("fixed")), None)
    if fixed:
        return fixed["fixed"], fixed.get("fixed_why", "")
    if any(o.get("code") for o in objs):
        return "rom", "code"
    w = [o for o in objs if o.get("static_writes")]
    if w:
        at = sorted({a for o in w for a in o.get("writers", [])})[:3]
        return "ram", "rule 2: stored by game/library code (static%s)" % (
            ": " + ", ".join("$%X" % a for a in at) if at else "")
    if any(o.get("census_owner") == "counted" for o in objs):
        return "ram", "rule 2: written after init (census)"
    if any(o.get("xsp") or o.get("census_owner") == "xsp" for o in objs):
        return "shim", "rule 3: XSP's own (replaced by the shim)"
    if any(o.get("drop") or o.get("census_owner") == "drop" for o in objs):
        why = next((o.get("drop_why") for o in objs if o.get("drop_why")), "stdio or malloc")
        return "drop", "rule 4: " + why
    if any(o.get("census_owner") == "rom" for o in objs):
        return "rom", "rule 5: reloaded file data (the shim makes the reads no-ops)"
    return "rom", "rule 5: read-only after init, init only or untouched (snapshot value)"


# ------------------------------------------------------------------------------------ placing

def _even(v):
    return v + (v & 1)


def place(objs, rom_base):
    """Give every object an address (o["addr"]): text in place at GAME_ROM + start, other ROM
    objects from `rom_base`, RAM from RAM_LO, both in original order (adjacent stays adjacent,
    parity kept); shim/drop at SHIM_DEAD after the ROM objects. Stack objects keep the address
    the caller gave. Returns {ram_used, rom_end, shim_dead}."""
    cur = {"ram": RAM_LO, "rom": rom_base}
    last_end = {"ram": None, "rom": None}
    for o in sorted(objs, key=lambda o: o["start"]):
        h = o["home"]
        if h == "rom" and o.get("region") == "text":
            o["addr"] = GAME_ROM + o["start"]
            continue
        if h not in cur:
            continue
        c = cur[h]
        if last_end[h] != o["start"] and (c - o["start"]) & 1:
            c += 1
        o["addr"] = c
        cur[h] = c + o["size"]
        last_end[h] = o["start"] + o["size"]
    shim_dead = _even(max(cur["rom"], rom_base))
    for o in objs:
        if o["home"] in ("shim", "drop"):
            o["addr"] = shim_dead
    return {"ram_used": cur["ram"] - RAM_LO, "rom_end": shim_dead + SHIM_DEAD_SIZE,
            "shim_dead": shim_dead}


# ----------------------------------------------------------------------------- the real build

def _unmerged_indexed(objs, groups, ghome, accesses, reach=None):
    """Inexact accesses (indexed, or through a register a loop moves) whose base group borders a
    data group with another home in the same area, with nothing that merged them: the index
    could run on into the neighbour. Listed for review; not merged."""
    starts = [o["start"] for o in objs]
    gi_of = {}
    for n, g in enumerate(groups):
        for k in range(g["lo"], g["hi"] + 1):
            gi_of[k] = n
    seen, out = {}, []
    for x in accesses:
        if x["exact"]:
            continue
        b = x["base"] if x.get("base") is not None else x["target"]
        i = _find(starts, objs, b)
        if i is None:
            continue
        g = gi_of[i]
        if g + 1 >= len(groups):
            continue
        cur, nxt = objs[groups[g]["lo"]:groups[g]["hi"] + 1], objs[groups[g + 1]["lo"]]
        if any(p.get("code") for p in cur) or nxt.get("code") or \
                nxt.get("area") != cur[-1].get("area") or ghome[g][0] == ghome[g + 1][0]:
            continue
        kind = ("after_resume" if reach is None or x["at"] in reach else "startup") + \
            ("_writes" if x["write"] else "_reads")
        if (g, g + 1) not in seen:
            base = objs[groups[g]["lo"]]["start"]
            e = {"at": x["at"], "base": base, "next": nxt["start"],
                 "homes": [ghome[g][0], ghome[g + 1][0]], "stride": x.get("stride"),
                 "after_resume_reads": [], "after_resume_writes": [], "startup_reads": [],
                 "startup_writes": [], "note": UNMERGED_NOTES.get(base, "")}
            seen[(g, g + 1)] = e
            out.append(e)
        seen[(g, g + 1)][kind].append(x["at"])
    return out


def _boundary_tags(lay, t):
    """Names of the snapshot layout boundaries at offset `t` ("bss_end", "stack_area_start"...)."""
    out = []
    for k, v in lay.items():
        if not isinstance(v, list) or k in ("memory_bin", "below_base_bin"):
            continue
        if t == v[0]:
            out.append(k + "_start")
        if t == v[0] + v[1]:
            out.append(k + "_end")
    return sorted(out)


def _reachable_after_resume(img, meta, snap, mem, inventory):
    """Instructions that can run once main resumes (tools/preinit.py's descent, same roots:
    main past its title call, the title menu, the play loop, the interrupt handlers the
    start-up installed and the code pointers the snapshot holds). tools/link.py uses it too."""
    import preinit
    relocs = set(meta["relocs"])
    roots = {preinit.RESUME + 6, preinit.TITLE, preinit.PLAY_LOOP}
    roots |= {i["handler"] for i in snap.get("interrupts", ())
              if preinit.XSP_TEXT[1] <= i["handler"] < meta["text"]}
    for w in snap["pointers"]:
        if w >= meta["text"] or w not in relocs:
            t = struct.unpack_from(">I", mem, w)[0]
            if preinit.XSP_TEXT[1] <= t < meta["text"]:
                roots.add(t)
    seen, _ = preinit.reachable_after_resume(img, meta, inventory, sorted(roots))
    return seen


def _bits(r):
    return cr._region_bits(r)


def _set_bits(v):
    """Offsets of the set bits of int `v`."""
    out = []
    while v:
        low = v & -v
        out.append(low.bit_length() - 1)
        v ^= low
    return out


def _text_objects(meta, code, census, targets, snap_ptr_targets):
    """Text: code runs and data-island pieces cut at reference targets, each flagged with who
    writes it (static stores of the game/library code, census writes by class)."""
    text = meta["text"]
    is_code = bytearray(text)
    for a, ins in code.ins.items():
        is_code[a:a + ins.size] = b"\1" * ins.size
    cuts = set(t for t in targets if 0 < t < text)
    for ins in code.ins.values():
        for op in ins.ops:
            if op.kind in ("pcrel", "pcidx") and 0 <= op.val < text:
                cuts.add(op.val)
    cuts |= {t for t in snap_ptr_targets if 0 < t < text}
    # runs of code / non-code, non-code runs cut further at the targets
    bounds = {0, text}
    for i in range(1, text):
        if is_code[i] != is_code[i - 1]:
            bounds.add(i)
    for t in cuts:
        if not is_code[t]:
            bounds.add(t)
    bounds = sorted(bounds)
    objs = []
    for a, b in zip(bounds, bounds[1:]):
        objs.append({"start": a, "size": b - a, "region": "text", "area": "text",
                     "kind": "text", "code": bool(is_code[a]), "static_writes": 0,
                     "census_owner": None, "xsp": False, "drop": False})
    # census: bytes written after init, by class; XSP's text variables (written in or after init)
    starts = [o["start"] for o in objs]
    r = next(r for r in census["regions"] if r["kind"] == "text")
    b = _bits(r)
    game_w = 0
    for c, v in b["writers"].items():
        if c != "xsp":
            game_w |= v
    xsp_w = b["writers"].get("xsp", 0)
    for off in _set_bits(game_w):
        i = _find(starts, objs, r["start"] + off)
        if not objs[i]["code"]:
            objs[i]["census_owner"] = "counted"
    for off in _set_bits(xsp_w):
        i = _find(starts, objs, r["start"] + off)
        if not objs[i]["code"] and objs[i]["census_owner"] is None:
            objs[i]["census_owner"] = "xsp"
    for row in census.get("text_data_writes", []):
        if row["region"] == "text" and row["owner"] == "xsp":
            for t in range(row["start"], row["start"] + row["size"]):
                i = _find(starts, objs, t)
                if not objs[i]["code"] and objs[i]["census_owner"] is None:
                    objs[i]["census_owner"] = "xsp"
    for o in objs:
        if o["start"] < XSP_TEXT_END and not o["code"] and o["census_owner"] == "xsp":
            o["xsp"] = True
    return objs


def malloc_sizes(img, reach):
    """Request sizes of the XC malloc calls that can run after the resume point: each
    `jsr XC_MALLOC` there must follow `move.l #n,-(sp)` (fopen's buffer: $400)."""
    call = ("jsr $%x.l" % XC_MALLOC, 6)
    sizes = {}
    for pc in sorted(reach):
        if _insn_text(img, pc) != call:
            continue
        push, size = _insn_text(img, pc - 6)
        if size != 6 or not (push.startswith("move.l #$") and push.endswith(", -(a7)")):
            raise ValueError("malloc call at $%X: not after move.l #n,-(sp)" % pc)
        sizes.setdefault(struct.unpack_from(">I", img, pc - 4)[0], []).append(pc)
    return sizes


def arena_after_resume(mem, sizes):
    """[lo, hi): the part of XC malloc's arena that malloc and free use after the resume point,
    for requests of `sizes`. malloc ($15560) takes the first fit from its rover [XC_ROVER]; each
    request must fit the free block the rover points at, the arena's first (the stdio buffer
    fclose freed: fopen takes it again), so malloc reads and writes only the head, that block and
    the next block's header (its prev). Anything else fails: it is not modelled."""
    head = struct.unpack_from(">I", mem, XC_HEAP_HEAD)[0]
    rover = struct.unpack_from(">I", mem, XC_ROVER)[0]
    end, nxt = struct.unpack_from(">II", mem, rover + 4)
    if rover != head + XC_ARENA_HEAD:
        raise ValueError("malloc's rover $%X is not the arena's first block" % rover)
    if end >> 24 != 0xFE:
        raise ValueError("the block at malloc's rover $%X is not free" % rover)
    for n in sizes:
        need = _even(n) + HEAP_HEADER
        if nxt - rover < need:
            raise ValueError("malloc($%X) after the resume point does not fit the block at the "
                             "rover ($%X bytes): not modelled" % (n, nxt - rover))
    return head, nxt + HEAP_HEADER


def _region_objects(census, r, targets, heap_index, referenced):
    """Objects of one census region other than text and the stack, with census flags."""
    kind = r["kind"]
    name = r["name"]
    out = []
    if name == "heap_head":
        return [{"start": r["start"], "size": r["size"], "region": "heap_head", "area": name,
                 "kind": "heap_head", "drop": True, "drop_why": "malloc arena head"}]
    if kind == "gap":
        o = {"start": r["start"], "size": r["size"], "region": "gap", "area": name, "kind": "gap"}
        if not referenced(r["start"], r["start"] + r["size"]):
            o.update(drop=True, drop_why="gap nothing refers to")
        return [o]
    b = _bits(r)
    wa = b["written_after_init"]
    fd = cr.decode_bitmap(r["file_data"], r["size"]) if r.get("file_data") else 0
    xsp_only = b["writers"].get("xsp", 0) & ~sum_others(b["writers"])
    content = r.get("content") or ""
    for s, n in cr.region_objects(r, targets):
        m = ((1 << n) - 1) << (s - r["start"])
        live = wa & m
        o = {"start": s, "size": n, "area": name, "kind": kind, "static_writes": 0,
             "census_owner": None, "xsp": False, "drop": False, "live": cr.popcount(live)}
        if kind in ("heap", "heap_free"):
            i = heap_index[r["start"]]
            o["region"] = "heap:%d" % i
            if s == r["start"]:
                o.update(drop=True, drop_why="malloc header")
            elif kind == "heap_free":
                o.update(drop=True, drop_why="free heap block")
            elif cr.XSP_HEAP_LABEL in content:
                o["xsp"] = True
            elif cr.STDIO_HEAP_LABEL in content:
                o.update(drop=True, drop_why="XC stdio buffer")
        else:
            o["region"] = "data" if kind == "data" else "bss"
            if any(a <= s < z for a, z in cr.XSP_RANGES):
                o["xsp"] = True
        if live:
            own = cr._owner(r, s, live, fd & m)
            if own == "counted" and not (live & ~fd & m & ~xsp_only):
                own = "xsp"                      # only XSP's code wrote it
            o["census_owner"] = own
        out.append(o)
    return out


def sum_others(writers):
    v = 0
    for c, x in writers.items():
        if c != "xsp":
            v |= x
    return v


def build(orig_dir, census_path, preinit_dir):
    with open(os.path.join(orig_dir, "sz2.bin"), "rb") as f:
        img = f.read()
    with open(os.path.join(orig_dir, "sz2.json")) as f:
        meta = json.load(f)
    census = cr.load(census_path)
    with open(os.path.join(preinit_dir, "snapshot.json")) as f:
        snap = json.load(f)
    with open(os.path.join(preinit_dir, "memory.bin"), "rb") as f:
        mem = f.read()
    lay = snap["layout"]
    text, data, bss = meta["text"], meta["data"], meta["bss"]
    if (lay["text"], lay["data"], lay["bss"]) != ([0, text], [text, data], [text + data, bss]):
        raise ValueError("snapshot layout differs from sz2.json")
    # heap blocks: census and snapshot agree on every start and size
    cheap = [(h["start"], h["size"]) for h in census["heap_blocks"]]
    sheap = [(h["start"], h["size"]) for h in snap["heap"]]
    if cheap != sheap:
        raise ValueError("heap blocks differ between the census and the snapshot")
    heap_index = {s: i for i, (s, _) in enumerate(sheap)}
    stack_lo, stack_n = lay["stack_area"]
    stack_hi = stack_lo + stack_n
    regions = sorted(census["regions"], key=lambda r: r["start"])
    st = next(r for r in regions if r["kind"] == "stack")
    if (st["start"], st["size"]) != (stack_lo, stack_n):
        raise ValueError("stack area differs between the census and the snapshot")
    pos = 0
    for r in regions:
        if r["start"] != pos:
            raise ValueError("census regions leave a hole at $%X" % pos)
        pos = r["start"] + r["size"]
    if pos != len(mem):
        raise ValueError("census regions end at $%X, memory.bin at $%X" % (pos, len(mem)))

    targets = cr.reloc_targets(img, meta["relocs"])

    def ptr_target(p):
        v = struct.unpack_from(">I", mem, p)[0] & 0xFFFFFF
        return v - 0x1000000 if v & 0x800000 else v

    ptr_targets = {p: ptr_target(p) for p in snap["pointers"]}
    # pointers below the base (PSP, environment): their words are in below_base.bin
    with open(os.path.join(preinit_dir, "below_base.bin"), "rb") as f:
        below = f.read()
    blo = lay["below_base_bin"][0]
    for p in snap["pointers_below_base"]:
        v = struct.unpack_from(">I", below, p - blo)[0] & 0xFFFFFF
        ptr_targets[p] = v - 0x1000000 if v & 0x800000 else v
    all_targets = sorted(set(targets) | set(ptr_targets.values()))

    def referenced(a, b):
        i = bisect.bisect_left(all_targets, a)
        return i < len(all_targets) and all_targets[i] < b

    outside = {p: t for p, t in ptr_targets.items() if t < 0}
    code = inv.disassemble(img, meta)
    accesses = static_accesses(img, meta, code, XSP_TEXT_END, outside)

    objs = _text_objects(meta, code, census, targets, set(ptr_targets.values()))
    for r in regions:
        if r["kind"] in ("text",):
            continue
        if r["kind"] == "stack":
            objs.append({"start": stack_lo, "size": stack_n - STACK_SIZE, "region": "stack",
                         "area": "stack", "kind": "stack", "fixed": "drop",
                         "fixed_why": "rule 4: C stack below the port's %d bytes (dead)" % STACK_SIZE})
            objs.append({"start": stack_hi - STACK_SIZE, "size": STACK_SIZE, "region": "stack",
                         "area": "stack", "kind": "stack", "fixed": "stack",
                         "fixed_why": "C stack top (live frames from sp $%X)" % snap["sp"]})
            continue
        objs.extend(_region_objects(census, r, targets, heap_index, referenced))
    for name in ("cmdline", "env", "psp"):
        s, n = lay[name]
        objs.append({"start": s, "size": n, "region": "below_base", "area": name,
                     "kind": "below_base", "static_writes": 0, "census_owner": None})
    objs.sort(key=lambda o: o["start"])
    with open(os.path.join(orig_dir, "inventory.json")) as f:
        reach = _reachable_after_resume(img, meta, snap, mem, json.load(f))
    if len(reach) != snap["after_resume"]["instructions"]:
        raise ValueError("reachability after the resume point: %d instructions here, %d in the "
                         "snapshot" % (len(reach), snap["after_resume"]["instructions"]))
    msizes = malloc_sizes(img, reach)
    alo, ahi = arena_after_resume(mem, msizes)
    arena = [o for o in objs if o["start"] < ahi and o["start"] + o["size"] > alo]
    if arena[0]["start"] != alo or arena[-1]["start"] + arena[-1]["size"] != ahi:
        raise ValueError("the malloc arena [$%X, $%X) does not fall on object bounds" % (alo, ahi))
    for o in arena:
        o["fixed"] = "ram"
        o["fixed_why"] = ("rule 2: XC malloc arena used after the resume point (malloc %s at %s, "
                          "free): head, the block at the rover, the next header" % (
                              ", ".join("$%X" % n for n in sorted(msizes)),
                              ", ".join("$%X" % a for v in msizes.values() for a in v)))
    count_writes(objs, accesses, reach)
    bad = [o["start"] for o in objs if o.get("code") and o.get("static_writes")]
    if bad:
        raise ValueError("stores into code at %s" % ", ".join("$%X" % a for a in bad))

    live_runs = []
    for r in regions:
        if r["kind"] == "stack":
            continue
        b = _bits(r)
        # game state only: bytes written by game, library or system code, not file data
        fd = cr.decode_bitmap(r["file_data"], r["size"]) if r.get("file_data") else 0
        wa = b["written_after_init"] & sum_others(b["writers"]) & ~fd
        for off, span, _ in cr.live_runs(wa, r["size"], gap=1):
            live_runs.append((r["start"] + off, r["start"] + off + span))
    groups = merge_objects(objs, accesses, KNOWN_ARRAYS, live_runs)

    ghome = [home_of(objs[g["lo"]:g["hi"] + 1]) for g in groups]
    unmerged = _unmerged_indexed(objs, groups, ghome, accesses, reach)

    out = []
    startup_only = []
    for g, (home, why) in zip(groups, ghome):
        pieces = objs[g["lo"]:g["hi"] + 1]
        first = pieces[0]
        spcs = sorted({a for p in pieces for a in p.get("startup_pcs", ())})
        if spcs and home != "ram":
            why += STARTUP_NOTE
            startup_only.append({"start": first["start"], "size": sum(p["size"] for p in pieces),
                                 "area": first.get("area"), "home": home, "startup_pcs": spcs[:8]})
        o = {"start": first["start"], "size": sum(p["size"] for p in pieces),
             "region": first["region"], "area": first.get("area"), "home": home, "addr": None,
             "why": why, "pieces": len(pieces)}
        if home == "ram":
            o["census_live"] = any(p.get("census_owner") == "counted" for p in pieces)
        if g["why"]:
            o["merged"] = g["why"][:6] + (["+%d more" % (len(g["why"]) - 6)] if len(g["why"]) > 6 else [])
        if first.get("code"):
            o["code"] = True
        out.append(o)
    # text that stays in place: one object per run of in-place pieces
    merged = []
    for o in out:
        p = merged[-1] if merged else None
        if p and o["region"] == "text" and p["region"] == "text" and o["home"] == p["home"] == "rom" \
                and "merged" not in o and "merged" not in p:
            p["size"] += o["size"]
            p["pieces"] += o["pieces"]
            p["why"] = "text in place (code, constants, variables nothing stores to after init)"
            p.pop("code", None)
            continue
        merged.append(dict(o))
    out = merged
    for o in out:
        if o["region"] == "text" and o["home"] == "rom":
            o["why"] = o["why"] if o.get("merged") else \
                "text in place (code, constants, variables nothing stores to after init)"
            o.pop("code", None)
        if o["region"] == "stack" and o["home"] == "stack":
            o["addr"] = STACK_TOP - o["size"]
    res = place(out, _even(GAME_ROM + text))
    ram_used, shim_dead = res["ram_used"], res["shim_dead"]
    if res["rom_end"] > ROM_END:
        raise ValueError("ROM overflows: ends at $%X" % res["rom_end"])

    starts = [o["start"] for o in out]

    def obj_at(t):
        i = _find(starts, out, t)
        return out[i] if i is not None else None

    # PC-relative references (game/library code) into text that moved
    fix = []
    for a in sorted(code.ins):
        ins = code.ins[a]
        if a < XSP_TEXT_END or ins.mn.startswith(("b", "db")) and ins.mn not in ("bset", "bclr", "bchg", "btst"):
            continue
        if ins.mn in ("jmp", "jsr"):
            continue
        for op in ins.ops:
            if op.kind in ("pcrel", "pcidx") and 0 <= op.val < text:
                o = obj_at(op.val)
                if o and o["home"] != "rom":
                    fix.append({"at": a, "size": ins.size, "insn": ins.text, "target": op.val,
                                "object": o["start"], "home": o["home"], "addr": o["addr"]})
    # references of the game/library (relocations at or above XSP_TEXT_END, snapshot pointers
    # outside XSP's own memory) into shim/drop objects: they point at SHIM_DEAD
    dead = []
    for rl in meta["relocs"]:
        if rl < XSP_TEXT_END:
            continue
        t = struct.unpack_from(">I", img, rl)[0]
        o = obj_at(t)
        if o and o["home"] in ("shim", "drop"):
            dead.append({"reloc": rl, "target": t, "home": o["home"], "object": o["start"]})
    ptr_dead = Counter()
    for p, t in ptr_targets.items():
        o, src = obj_at(t), obj_at(p)
        if o and o["home"] in ("shim", "drop") and src and src["home"] in ("ram", "rom", "stack"):
            ptr_dead[o["home"]] += 1
    # Run-time pointers (snapshot pointer words that are not relocations: made by the start-up)
    # to the exact end of an object whose successor is placed elsewhere: by containment they map
    # to the successor's start, which is wrong if they mean "end of" (bss end, stack top, the
    # arena bounds). Malloc results (the data start of a heap block) are starts and left out.
    ends = []
    end_of = {o["start"] + o["size"]: o for o in out}
    relocs = set(meta["relocs"])
    for p, t in sorted(ptr_targets.items()):
        prev, nxt, holder = end_of.get(t), obj_at(t), obj_at(p)
        if t == lay["ram_end"] and holder and holder["home"] not in ("shim", "drop"):
            ends.append({"pointer": p, "target": t, "tag": ["ram_end"], "map_to": RAM_LO + ram_used,
                         "map_why": "RAM end: the end of the game RAM used", "prev": None,
                         "prev_home": None, "prev_end_addr": None, "next": None, "next_home": None})
            continue
        if p in relocs or not prev or not nxt or nxt["region"].startswith("heap:") and \
                prev["region"] == nxt["region"]:
            continue
        if not holder or holder["home"] in ("shim", "drop"):
            continue                          # the pointer itself is not kept (malloc chain)
        if prev["home"] == nxt["home"] and prev["home"] in ("ram", "rom") and \
                prev["addr"] + prev["size"] == nxt["addr"]:
            continue
        prev_end = (prev["addr"] + prev["size"]) if prev["home"] in ("ram", "rom", "stack") else None
        tags = _boundary_tags(lay, t)
        if "stack_area_start" in tags:
            to, how = STACK_TOP - STACK_SIZE, "stack bottom: the Neo Geo stack region's start"
        elif "stack_area_end" in tags:
            to, how = STACK_TOP, "stack top"
        elif ("heap_head_start" in tags or "heap_start" in tags) and nxt["home"] == "ram":
            to, how = nxt["addr"], "malloc arena: its head / first block, in RAM"
        elif "heap_head_start" in tags or "heap_start" in tags:
            to, how = RAM_LO + ram_used, "malloc arena: the end of the game RAM used"
        elif "text_start" in tags:
            to, how = nxt["addr"], "program start: the text at game_rom"
        elif tags:
            to, how = prev_end, "end of the object before it"
        else:                                 # no layout boundary: a start pointer (argv[0])
            to, how = nxt["addr"], "start of the object it points to (no layout boundary here)"
        ends.append({"pointer": p, "target": t, "tag": tags or ["?"], "map_to": to, "map_why": how,
                     "prev": prev["start"], "prev_home": prev["home"], "prev_end_addr": prev_end,
                     "next": nxt["start"], "next_home": nxt["home"]})
    totals = {h: sum(o["size"] for o in out if o["home"] == h) for h in HOMES}
    static_ram = [{"start": o["start"], "size": o["size"], "area": o["area"], "why": o["why"]}
                  for o in out if o["home"] == "ram" and not o["census_live"]]
    return {
        "legend": {
            "region": "text | data | bss | heap:<n> (n = index in snapshot.json's heap) | stack | "
                      "gap (after bss, before the heap) | heap_head (malloc arena head) | "
                      "below_base (area: cmdline, env, psp; negative offsets)",
            "home": "ram (RAM_LO..) | rom (text in place at game_rom + start, others after it) | "
                    "shim / drop (no copy: every reference -> shim_dead) | stack (top of the "
                    "original's C stack under stack.top)",
            "addr": "Neo Geo address of the object's first byte",
        },
        "game_rom": GAME_ROM, "shim_dead": shim_dead, "shim_dead_size": SHIM_DEAD_SIZE,
        "rom_used": res["rom_end"] - GAME_ROM, "rom_end": res["rom_end"],
        "ram": [RAM_LO, RAM_LO + ram_used], "ram_used": ram_used, "ram_limit": RAM_LIMIT,
        "ram_end_addr": RAM_LO + ram_used,
        "stack": {"addr": STACK_TOP - STACK_SIZE, "top": STACK_TOP,
                  "orig": [stack_hi - STACK_SIZE, stack_hi], "sp": snap["sp"]},
        "memory_bin": len(mem), "totals": totals,
        "objects": out,
        "pcrel_fixups": fix,
        "dead_relocs": dead, "dead_pointers": dict(ptr_dead),
        "end_pointers": ends,
        "unmerged_indexed": unmerged,
        "static_ram": static_ram, "startup_only": startup_only,
        "scan": write_census(img, meta, code),
        "scan_accesses": len(accesses),
    }


# ----------------------------------------------------------------------------------- report

def _h(v):
    return ("-$%X" % -v) if v < 0 else "$%X" % v


def render_md(lay):
    L = ["# Object layout on the Neo Geo", "",
         "Generated by `make layout` (`tools/layout.py`; rules in its docstring). Offsets are base-0 "
         "(the original's image offsets, as in `ram-census.md`); addresses are the Neo Geo's. "
         "Sizes in bytes. Full list: `build/link/layout.json`.", ""]
    t = lay["totals"]
    L += ["## Totals", "",
          "| Home | Bytes | Objects | Where |", "|---|---|---|---|"]
    n = Counter(o["home"] for o in lay["objects"])
    where = {"ram": "work RAM $%06X-$%06X (%d of %d B used)" % (
                 lay["ram"][0], lay["ram"][1] - 1, lay["ram_used"], lay["ram_limit"]),
             "rom": "P-ROM from $%06X (text in place, then the ROM objects)" % lay["game_rom"],
             "shim": "nowhere: references go to SHIM_DEAD $%06X" % lay["shim_dead"],
             "drop": "nowhere: references go to SHIM_DEAD $%06X" % lay["shim_dead"],
             "stack": "stack $%06X-$%06X" % (lay["stack"]["addr"], lay["stack"]["top"] - 1)}
    for h in HOMES:
        L.append("| %s | %d | %d | %s |" % (h, t[h], n[h], where[h]))
    L += ["",
          "- **ram_used: %d** of %d (margin %+d); the RAM end pointer of the original maps to "
          "$%06X." % (lay["ram_used"], lay["ram_limit"], lay["ram_limit"] - lay["ram_used"],
                      lay["ram_end_addr"]),
          "- **rom_used: %d** ($%06X-$%06X, SHIM_DEAD = $%06X, %d bytes, last)." % (
              lay["rom_used"], lay["game_rom"], lay["rom_end"] - 1, lay["shim_dead"],
              lay["shim_dead_size"]),
          "- Stack: the original's top %d bytes ($%X-$%X, sp at the resume point $%X) at $%06X." % (
              lay["stack"]["top"] - lay["stack"]["addr"], lay["stack"]["orig"][0],
              lay["stack"]["orig"][1] - 1, lay["stack"]["sp"], lay["stack"]["addr"]),
          ""]
    L += ["## Biggest RAM objects", "",
          "| Start | Size | Area | Neo Geo | Pieces | Why |", "|---|---|---|---|---|---|"]
    for o in sorted([o for o in lay["objects"] if o["home"] == "ram"],
                    key=lambda o: (-o["size"], o["start"]))[:20]:
        L.append("| %s | %d | %s | $%06X | %d | %s |" % (_h(o["start"]), o["size"], o["area"],
                                                       o["addr"], o["pieces"], o["why"]))
    L += ["", "## Merged objects", "",
          "Objects joined from several relocation-target pieces (rule 1).", "",
          "| Start | Size | Area | Home | Pieces | Evidence |", "|---|---|---|---|---|---|"]
    for o in lay["objects"]:
        if o.get("merged"):
            L.append("| %s | %d | %s | %s | %d | %s |" % (_h(o["start"]), o["size"], o["area"],
                                                         o["home"], o["pieces"], "; ".join(o["merged"])))
    L += ["", "## RAM because code stores to them, not because the census saw it", "",
          "Objects the census had as ROM candidate, init only or untouched (no game-state byte "
          "written after init) that the static scan finds a store to from game or library code "
          "that can run after the resume point (tools/preinit.py's reachability). %d objects, "
          "%d bytes." % (len(lay["static_ram"]), sum(o["size"] for o in lay["static_ram"])),
          "", "| Start | Size | Area | Why |", "|---|---|---|---|"]
    for o in lay["static_ram"]:
        L.append("| %s | %d | %s | %s |" % (_h(o["start"]), o["size"], o["area"], o["why"]))
    so = lay["startup_only"]
    L += ["", "## Stored only by the start-up: ROM", "",
          "Objects that only start-up code (not reachable after the resume point) stores to: the "
          "stores already happened when the snapshot was taken, so they keep their snapshot value "
          "in ROM (or their home by rules 3-5). %d objects, %d bytes." % (
              len(so), sum(o["size"] for o in so)), "",
          "| Start | Size | Area | Home | Storing code |", "|---|---|---|---|---|"]
    for o in so:
        L.append("| %s | %d | %s | %s | %s |" % (_h(o["start"]), o["size"], o["area"], o["home"],
                                                ", ".join(_h(a) for a in o["startup_pcs"])))
    L += ["", "## Text variables moved out of the text", "",
          "| Start | Size | Home | Neo Geo |", "|---|---|---|---|"]
    for o in lay["objects"]:
        if o["region"] == "text" and o["home"] != "rom":
            L.append("| %s | %d | %s | $%06X |" % (_h(o["start"]), o["size"], o["home"], o["addr"]))
    fx = lay["pcrel_fixups"]
    L += ["", "PC-relative references to them in game/library code (link.py must redirect "
          "these; the text copy in ROM is stale): %d, at %s." % (
              len(fx), ", ".join(_h(f["at"]) for f in fx) or "none"), ""]
    L += ["## For link.py", "",
          "- Game/library relocations pointing into shim or drop objects (they get SHIM_DEAD): %d; "
          "snapshot pointers from kept objects into them: %s." % (
              len(lay["dead_relocs"]), ", ".join("%s %d" % kv for kv in sorted(lay["dead_pointers"].items())) or "none"),
          "- Snapshot pointers (memory.bin and below the base) to an object's end where the next "
          "object lives elsewhere, or to the RAM end (`end_pointers`, each tagged with the layout boundary and a suggested address): %s." % (
              ", ".join("%s %s -> $%06X" % (_h(e["pointer"]), "/".join(e["tag"]), e["map_to"])
                        for e in lay["end_pointers"] if e["map_to"] is not None) or "none"),
          "- Indexed accesses whose base object borders an object with another home, no merge "
          "evidence (`unmerged_indexed`): %d." % len(lay["unmerged_indexed"]),
          ""]
    if lay["unmerged_indexed"]:
        L += ["Indexed accesses from the base object, by code that can run after the resume "
              "point and by start-up code only (r = reads, w = writes).", "",
              "| Code | Base object | Next object | Homes | Stride | After resume | Start-up | Why it "
              "may stay apart |", "|---|---|---|---|---|---|---|---|"]

        def rw(u, k):
            return " ".join("%s%d" % (c, len(u["%s_%s" % (k, n)]))
                            for c, n in (("r", "reads"), ("w", "writes"))
                            if u["%s_%s" % (k, n)]) or "-"

        for u in lay["unmerged_indexed"]:
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                _h(u["at"]), _h(u["base"]), _h(u["next"]), " / ".join(u["homes"]),
                u["stride"] or "?", rw(u, "after_resume"), rw(u, "startup"),
                u["note"] or "not reviewed"))
        L.append("")
    L += ["## Static scan coverage", "",
          "Stores (memory destinations) in the game and XC library code, by how the scan resolves "
          "them:", "", "| Destination | Instructions |", "|---|---|"]
    for k, v in sorted(lay["scan"].items(), key=lambda kv: -kv[1]):
        L.append("| %s | %d |" % (k, v))
    L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", default="build/orig")
    ap.add_argument("--census", default="data/census.json")
    ap.add_argument("--preinit", default="build/preinit")
    ap.add_argument("--out", default="build/link/layout.json")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    lay = build(a.orig, a.census, a.preinit)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(lay, f, indent=1)
    if a.md:
        with open(a.md, "w") as f:
            f.write(render_md(lay))
    t = lay["totals"]
    print("layout: ram_used %d of %d, rom_used %d (SHIM_DEAD $%X); RAM %d, ROM %d, shim %d, drop %d, "
          "stack %d B; %d objects, %d PC-relative fixups" % (
              lay["ram_used"], RAM_LIMIT, lay["rom_used"], lay["shim_dead"], t["ram"], t["rom"],
              t["shim"], t["drop"], t["stack"], len(lay["objects"]), len(lay["pcrel_fixups"])))
    if lay["ram_used"] > RAM_LIMIT:
        print("layout: RAM over the %d-byte area" % RAM_LIMIT)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
