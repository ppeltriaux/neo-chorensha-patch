"""Inventory of everything SZ2 asks of the X68000.

  .venv/bin/python -I tools/inventory.py --orig build/orig --out build/orig/inventory.json \\
      --md build/orig/inventory.md

Recursive-descent disassembly (Capstone, M68000) of the base-0 image from the entry point,
following direct branches/calls, C `switch` jump tables, and code pointers (lea/pea operands and
relocated 32-bit words) that decode cleanly as code. From the decoded instructions it lists:

  dos     Human68k DOS calls: F-line words $FF00-$FFFF at instruction positions
  fefunc  FLOAT driver calls: F-line words $FE00-$FEFF
  iocs    trap #15; `fn` is n when the instruction just before is `moveq #n,d0`, else null
          with a note; iocs_via: calls of the C wrapper `iocs(fn, ...)` with their fn
  traps   every other trap #n (`d0`: constant loaded into d0 earlier in the block, if any)
  io      accesses to $E00000-$EFFFFF, absolute or through a register holding a hardware
          address (forward dataflow), with direction, size, and `indexed` when base + unknown
  mem     the same for other non-program addresses (vectors, GVRAM); io_ptr: hardware
          addresses that appear as constants (immediates, lea/pea operands)
  xsp     XSP entry points found by masked byte matching against XSPlibC.o/XSPlibA.o
          (xsp_how, xsp_asm, xsp_unmatched with a structural candidate)
  functions  call targets and accepted code pointers; clib_start: first XC library function;
          kakusi: the KAKUSI menu string, its function and callers; unreached: code nothing
          references
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import defaultdict

import capstone
from capstone import m68k

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hunks  # noqa: E402
import orig_bytes  # noqa: E402
import x68k_names  # noqa: E402

# The KAKUSI menu's header string (the menu's title line): its length and SHA1, found by a window
# search in the program (the tools carry no string of the game's).
KAKUSI_HEADER = (21, "54e35ecdf97b95177a3bb3d0c1d04cfb8798c8a5")

IO_LO, IO_HI = 0xE00000, 0xEFFFFF
NORETURN_DOS = {0xFF00, 0xFF31, 0xFF4C}       # _EXIT, _KEEPPR, _EXIT2
CALLER_SAVED = ("d0", "d1", "d2", "a0", "a1", "a2")

_md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_000)
_md.detail = True

AM = m68k
WRITE_ONLY = {"move", "movea", "clr", "st", "sf", "shi", "sls", "scc", "scs", "sne", "seq", "svc",
              "svs", "spl", "smi", "sge", "slt", "sgt", "sle", "moveq", "lea", "movem", "movep",
              "exg", "swap", "ext"}
READ_ONLY = {"cmp", "cmpa", "cmpi", "cmpm", "tst", "btst", "chk", "pea", "jmp", "jsr"}


class Insn:
    __slots__ = ("addr", "size", "mn", "sz", "ops", "text", "word")

    def __init__(self, addr, size, mn, sz, ops, text, word):
        self.addr, self.size, self.mn, self.sz, self.ops, self.text, self.word = (
            addr, size, mn, sz, ops, text, word)


class Op:
    """A decoded operand: kind in imm/dreg/areg/abs/pcrel/pcidx/ind/postinc/predec/disp/idx/
    regs/other; `reg` (name), `val` (immediate, absolute address, PC-relative target, or disp)."""
    __slots__ = ("kind", "reg", "val")

    def __init__(self, kind, reg=None, val=None):
        self.kind, self.reg, self.val = kind, reg, val

    def __repr__(self):
        return f"Op({self.kind},{self.reg},{self.val})"


def _reg(r):
    return _md.reg_name(r) if r else None


def decode(img, a, limit):
    """Decode the instruction at `a`; None if invalid or running past `limit`."""
    if a + 2 > limit:
        return None
    (w,) = struct.unpack_from(">H", img, a)
    if w >= 0xFE00:
        return Insn(a, 2, "dos" if w >= 0xFF00 else "fefunc", None, [], f"dc.w ${w:04x}", w)
    buf = img[a:min(a + 10, limit)]
    try:
        i = next(_md.disasm(buf, a, 1))
    except StopIteration:
        return None
    if i.id == 0 or a + i.size > limit:
        return None
    try:
        cops = i.operands
    except capstone.CsError:
        return None
    mn, _, sz = i.mnemonic.partition(".")
    ops = []
    for o in cops:
        t, am = o.type, o.address_mode
        if t == AM.M68K_OP_IMM:
            ops.append(Op("imm", val=o.imm))
        elif t == AM.M68K_OP_REG:
            r = _reg(o.reg)
            ops.append(Op("areg" if am == AM.M68K_AM_REG_DIRECT_ADDR else "dreg", r))
        elif t == AM.M68K_OP_BR_DISP:
            ops.append(Op("pcrel", val=a + 2 + o.br_disp.disp))
        elif t == AM.M68K_OP_MEM:
            if am == AM.M68K_AM_ABSOLUTE_DATA_LONG:
                ops.append(Op("abs", val=o.imm & 0xFFFFFFFF))
            elif am == AM.M68K_AM_ABSOLUTE_DATA_SHORT:
                v = o.imm & 0xFFFF
                ops.append(Op("abs", val=(v - 0x10000) & 0xFFFFFF if v & 0x8000 else v))
            elif am == AM.M68K_AM_PCI_DISP:
                # insn+2+disp, as Capstone computes it: exact for lea/pea/jmp/jsr and every form
                # whose extension word follows the opcode; 2 short for `btst #n,d(pc)`.
                ops.append(Op("pcrel", val=a + 2 + o.mem.disp))
            elif am in (AM.M68K_AM_PCI_INDEX_8_BIT_DISP, AM.M68K_AM_PCI_INDEX_BASE_DISP):
                ops.append(Op("pcidx", _reg(o.mem.index_reg), a + 2 + o.mem.disp))
            elif am == AM.M68K_AM_REGI_ADDR:
                ops.append(Op("ind", _reg(o.mem.base_reg) or _reg(o.reg), 0))
            elif am == AM.M68K_AM_REGI_ADDR_POST_INC:
                ops.append(Op("postinc", _reg(o.mem.base_reg) or _reg(o.reg), 0))
            elif am == AM.M68K_AM_REGI_ADDR_PRE_DEC:
                ops.append(Op("predec", _reg(o.mem.base_reg) or _reg(o.reg), 0))
            elif am == AM.M68K_AM_REGI_ADDR_DISP:
                ops.append(Op("disp", _reg(o.mem.base_reg), o.mem.disp))
            elif am in (AM.M68K_AM_AREGI_INDEX_8_BIT_DISP, AM.M68K_AM_AREGI_INDEX_BASE_DISP):
                ops.append(Op("idx", _reg(o.mem.base_reg), o.mem.disp))
            else:
                return None
        elif t == AM.M68K_OP_REG_BITS:
            ops.append(Op("regs", val=o.register_bits))
        else:
            ops.append(Op("other"))
    return Insn(a, i.size, mn, sz, ops, f"{i.mnemonic} {i.op_str}".strip(), None)


class Code:
    """Result of the disassembly: `insns` addr -> size, `ins` addr -> Insn, `functions`,
    `xrefs` target -> [(from, kind)], `pointers` accepted code pointers {target: source}."""

    def __init__(self):
        self.insns, self.ins = {}, {}
        self.owner = {}
        self.functions = set()
        self.labels = set()
        self.xrefs = defaultdict(list)
        self.tables = []            # (jmp address, table base, [case targets])
        self.jumps = {}             # jmp address -> targets, for tables and computed jumps
        self.external = {}          # jsr/jmp targets outside the text section -> [from]
        self.pointers = {}
        self.rejected = {}


class _Walker:
    def __init__(self, img, limit, relocs, code, prog_end=None):
        self.img, self.limit, self.relocs, self.code = img, limit, relocs, code
        self.prog_end = prog_end or limit

    def ok_target(self, t):
        return t is not None and 0 <= t < self.limit and not t & 1

    def _table(self, ins, prev):
        """C switch: [cmp bound] ... add.l d0,d0; move.w T(pc,d0.l),dR; jmp T(pc,dR.w)."""
        tgt = ins.ops[0].val
        p = prev[-1] if prev else None
        if not (p and p.mn == "move" and p.sz == "w" and p.ops[0].kind == "pcidx"
                and p.ops[0].val == tgt):
            return None
        bound = None
        for q in reversed(prev[:-1]):
            if q.mn in ("cmp", "cmpi") and q.ops[0].kind == "imm":
                bound = q.ops[0].val
                break
            if q.mn == "cmp" and q.ops[0].kind == "dreg":
                r = q.ops[0].reg
                for z in reversed(prev[:prev.index(q)]):
                    if z.mn == "moveq" and z.ops[1].reg == r:
                        bound = z.ops[0].val
                        break
                break
        targets = []
        n = 0
        while True:
            if bound is not None and n > bound:
                break
            if bound is None and targets and tgt + 2 * n >= min(targets):
                break
            (d,) = struct.unpack_from(">h", self.img, tgt + 2 * n)
            t = tgt + d
            if not self.ok_target(t):
                break
            targets.append(t)
            n += 1
        return tgt, targets

    def walk(self, seeds, trial=False):
        """Descend from `seeds`. In trial mode nothing is committed unless every path decodes
        cleanly without overlapping known code; returns (ok, new insns)."""
        code = self.code
        new, owner = {}, {}
        calls, labels, xrefs, tables, jumps, external = set(), set(), [], [], {}, []
        work = list(seeds)
        prevs = {}
        while work:
            a = work.pop()
            if a in code.ins or a in new:
                continue
            if a in code.owner or a in owner:
                if trial:
                    return False, None
                code.rejected[a] = "inside another instruction"
                continue
            ins = decode(self.img, a, self.limit)
            if trial and ins is not None and self.img[a:a + 4] == b"\0\0\0\0":
                return False, None          # ori.b #0,d0: a zero-filled variable, not code
            if ins is None:
                if trial:
                    return False, None
                code.rejected[a] = "invalid opcode"
                continue
            span = range(a + 1, a + ins.size)
            if any(b in code.ins or b in new or b in code.owner or b in owner for b in span):
                if trial:
                    return False, None
                code.rejected[a] = "overlaps another instruction"
                continue
            new[a] = ins
            for b in span:
                owner[b] = a
            prev = prevs.get(a, [])
            nxt = a + ins.size
            fall = True
            mn = ins.mn
            if mn == "dos":
                fall = ins.word not in NORETURN_DOS
            elif mn in ("rts", "rte", "rtr", "illegal"):
                fall = False
            elif mn in ("bra", "bsr") or (mn.startswith(("b", "db")) and ins.ops and ins.ops[-1].kind == "pcrel"
                                          and mn not in ("btst", "bset", "bclr", "bchg")):
                t = ins.ops[-1].val
                if not self.ok_target(t):
                    if trial:
                        return False, None
                    code.rejected[t] = f"bad branch target from {a:#x}"
                else:
                    work.append(t)
                    if mn == "bsr":
                        calls.add(t)
                        xrefs.append((t, a, "call"))
                    else:
                        labels.add(t)
                        xrefs.append((t, a, "branch"))
                fall = mn != "bra"
            elif mn in ("jmp", "jsr"):
                op = ins.ops[0]
                t = None
                if op.kind == "abs":
                    t = op.val
                elif op.kind == "pcrel":
                    t = op.val
                elif op.kind == "pcidx" and mn == "jmp":
                    tb = self._table(ins, prev)
                    if tb:
                        tables.append((a, tb[0], tb[1]))
                        jumps[a] = tb[1]
                        for x in tb[1]:
                            work.append(x)
                            labels.add(x)
                            xrefs.append((x, a, "case"))
                    else:   # hand-written computed jump into unrolled code
                        jumps[a] = [x for x in (op.val, nxt) if self.ok_target(x)]
                        for x in (op.val, nxt):
                            if self.ok_target(x):
                                work.append(x)
                                labels.add(x)
                                xrefs.append((x, a, "computed"))
                if t is not None and self.limit <= t < self.prog_end and not t & 1:
                    external.append((t, a))       # into data/bss: not followed
                elif t is not None:
                    if not self.ok_target(t):
                        if trial:
                            return False, None
                        code.rejected[t] = f"bad jump target from {a:#x}"
                    else:
                        work.append(t)
                        if mn == "jsr":
                            calls.add(t)
                        else:
                            labels.add(t)
                        xrefs.append((t, a, "call" if mn == "jsr" else "jump"))
                fall = mn == "jsr"
            if fall:
                if nxt >= self.limit:
                    if trial:
                        return False, None
                else:
                    work.append(nxt)
                    prevs[nxt] = (prev + [ins])[-6:]
        # commit
        code.ins.update(new)
        for a, ins in new.items():
            code.insns[a] = ins.size
        code.owner.update(owner)
        code.functions |= calls
        code.labels |= labels
        for t, f, k in xrefs:
            code.xrefs[t].append((f, k))
        code.tables.extend(tables)
        code.jumps.update(jumps)
        for t, f in external:
            code.external.setdefault(t, []).append(f)
        return True, new


def _is_string(img, t):
    """True if the bytes at t are a NUL-terminated run of at least three text characters
    (ASCII, tab/CR/LF/ESC, or Shift-JIS pairs), or only CR/LF: a string literal, not code.
    (Two printable bytes then NUL is also `move.l 4(sp),d0` = " /\0\4", so two is too few.)"""
    n, i = 0, t
    while i < len(img) and img[i]:
        c = img[i]
        if 0x20 <= c < 0x7F or c in (9, 10, 13, 27) or 0xA1 <= c <= 0xDF:
            i += 1
        elif (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC) and i + 1 < len(img) and 0x40 <= img[i + 1] <= 0xFC:
            i += 2
        else:
            return False
        n += 1
    if i >= len(img) or n == 0:
        return False
    return n >= 3 or all(c in (10, 13) for c in img[t:i])


def _pointer_candidates(img, code, relocs, limit):
    """Code-pointer candidates: lea/pea operands and relocated words that point into the image
    and are not themselves inside decoded instructions."""
    cands = {}
    for a, ins in code.ins.items():
        if ins.mn in ("lea", "pea") and ins.ops[0].kind in ("pcrel", "abs"):
            t = ins.ops[0].val
            if t < limit and not t & 1:
                cands.setdefault(t, f"{ins.mn} at {a:#x}")
        elif ins.mn in ("move", "movea") and ins.ops and ins.ops[0].kind == "imm":
            if any(r in relocs for r in range(a + 2, a + ins.size - 3)):
                t = ins.ops[0].val
                if t < limit and not t & 1:
                    cands.setdefault(t, f"{ins.mn} #imm at {a:#x}")
    for r in sorted(relocs):
        if r in code.owner or r in code.ins:
            continue
        (t,) = struct.unpack_from(">I", img, r)
        if t < limit and not t & 1:
            cands.setdefault(t, f"word at {r:#x}")
    return cands


def disassemble(img, meta, extra=()):
    limit = meta["text"]
    relocs = set(meta["relocs"])
    code = Code()
    w = _Walker(img, limit, relocs, code, meta["text"] + meta["data"] + meta["bss"])
    w.walk([meta["entry"], *extra])
    code.functions.add(meta["entry"])
    code.functions |= set(extra)
    while True:
        cands = {t: s for t, s in _pointer_candidates(img, code, relocs, limit).items()
                 if t not in code.ins and t not in code.pointers and t not in code.rejected}
        progress = False
        for t, src in sorted(cands.items()):
            if t in code.ins or t in code.owner:
                continue
            ok = not _is_string(img, t) and w.walk([t], trial=True)[0]
            if ok:
                w.walk([t])
                code.pointers[t] = src
                code.functions.add(t)
                progress = True
            else:
                code.rejected[t] = f"pointer ({src}) does not decode as code"
        if not progress:
            break
    return code


# ---------------------------------------------------------------- per-instruction analysis

def _access(ins, idx):
    mn = ins.mn
    if mn == "movem":
        return "w" if idx == 1 else "r"
    if mn in ("move", "movea", "movep"):
        return "r" if idx == 0 else "w"
    if mn in READ_ONLY:
        return "r"
    if mn in WRITE_ONLY or _is_scc(mn):
        return "w" if idx == len(ins.ops) - 1 else "r"
    if len(ins.ops) >= 2 and idx == 0:
        return "r"
    return "rw"


def _is_scc(mn):
    return mn in ("st", "sf", "shi", "sls", "scc", "scs", "sne", "seq", "svc", "svs", "spl", "smi",
                  "sge", "slt", "sgt", "sle")


def _size(ins):
    if ins.mn in ("btst", "bset", "bclr", "bchg", "tas", "nbcd") or _is_scc(ins.mn):
        return 1
    return {"b": 1, "w": 2, "l": 4}.get(ins.sz, 2)


def _is_prog_abs(img, ins, relocs, val):
    for r in range(ins.addr + 2, ins.addr + ins.size - 3):
        if r in relocs and struct.unpack_from(">I", img, r)[0] == val:
            return True
    return False


# Register values are tracked only when they point at hardware ($C00000-$FEFFFF): GVRAM, text
# VRAM, I/O, CG ROM. A value is (address, exact); "inexact" means base + an unknown index.
HW_LO, HW_HI = 0xC00000, 0xFEFFFF


def _hw(v):
    return v is not None and HW_LO <= (v & 0xFFFFFFFF) <= HW_HI


def _successors(code, ins):
    a, mn = ins.addr, ins.mn
    nxt = a + ins.size
    if mn == "dos":
        return [nxt] if ins.word not in NORETURN_DOS else []
    if mn in ("rts", "rte", "rtr", "illegal"):
        return []
    if a in code.jumps:
        return list(code.jumps[a])
    if mn in ("jmp",):
        op = ins.ops[0]
        return [op.val] if op.kind in ("abs", "pcrel") and op.val in code.ins else []
    if mn == "bra":
        return [ins.ops[-1].val]
    if mn.startswith(("b", "db")) and mn not in ("bsr", "btst", "bset", "bclr", "bchg") \
            and ins.ops and ins.ops[-1].kind == "pcrel":
        return [ins.ops[-1].val, nxt]
    return [nxt]


def _meet(x, y):
    out = {}
    for r in x.keys() & y.keys():
        (v1, e1), (v2, e2) = x[r], y[r]
        if v1 == v2:
            out[r] = (v1, e1 and e2)
        elif abs(v1 - v2) < 0x10000:
            out[r] = (min(v1, v2), False)
    return out


def _transfer(ins, st):
    """Register state after `ins` (only hardware pointers are kept)."""
    st = dict(st)
    mn, ops = ins.mn, ins.ops
    if mn in ("dos", "trap", "jsr", "bsr"):
        for r in CALLER_SAVED:
            st.pop(r, None)
        return st
    for op in ops:
        if op.kind in ("postinc", "predec") and op.reg in st and mn != "movem":
            v, e = st[op.reg]
            if e:
                st[op.reg] = (v + (_size(ins) if op.kind == "postinc" else -_size(ins)), True)
        elif op.kind in ("postinc", "predec") and op.reg in st:
            v, e = st[op.reg]
            st[op.reg] = (v, False)
    if mn == "movem" and ops and ops[-1].kind == "regs":
        bits = ops[-1].val      # capstone order: bit 0-7 = d0-d7, 8-15 = a0-a7
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
    if mn == "swap" and ops:
        st.pop(ops[0].reg, None)
        return st
    if len(ops) != 2 or ops[1].kind not in ("areg", "dreg"):
        if len(ops) == 1 and ops[0].kind in ("areg", "dreg"):
            st.pop(ops[0].reg, None)    # clr/neg/not/ext...
        return st
    src, dst = ops
    d = dst.reg
    cur = st.get(d)
    new = None
    if mn == "lea":
        if src.kind == "abs" and _hw(src.val):
            new = (src.val, True)
        elif src.kind == "disp" and src.reg in st:
            v, e = st[src.reg]
            new = (v + src.val, e)
        elif src.kind == "ind" and src.reg in st:
            new = st[src.reg]
        elif src.kind == "idx" and src.reg in st:
            new = (st[src.reg][0] + src.val, False)
    elif mn in ("move", "movea") and ins.sz == "l":
        if src.kind == "imm" and _hw(src.val):
            new = ((src.val & 0xFFFFFFFF), True)
        elif src.kind in ("areg", "dreg") and src.reg in st:
            new = st[src.reg]
    elif mn in ("add", "adda", "addi", "addq", "sub", "suba", "subi", "subq"):
        sign = -1 if mn.startswith("sub") else 1
        if src.kind == "imm" and cur is not None and (ins.sz != "w" or dst.kind == "areg"):
            new = (cur[0] + sign * src.val, cur[1])
        elif src.kind == "imm" and cur is None and sign > 0 and _hw(src.val):
            new = ((src.val & 0xFFFFFFFF), False)       # index + hardware base
        elif cur is not None:
            new = (cur[0], False)                        # base + unknown index
        elif src.kind in ("areg", "dreg") and src.reg in st and sign > 0:
            new = (st[src.reg][0], False)
    if new is None or not _hw(new[0]):
        st.pop(d, None)
    else:
        st[d] = new
    return st


def _call_target(code, ins):
    if ins.mn == "bsr" or (ins.mn == "jsr" and ins.ops[0].kind in ("abs", "pcrel")):
        t = ins.ops[-1].val if ins.mn == "bsr" else ins.ops[0].val
        return t if t in code.ins else None
    return None


def regstates(code, entry=None):
    """Forward dataflow: register state at the entry of every decoded instruction. A function
    reached only by direct calls starts with the meet of its callers' states (register-passed
    hardware pointers, as in XSP's internal routines); anything else starts knowing nothing."""
    preds = set()
    called = set()
    for a, ins in code.ins.items():
        preds.update(_successors(code, ins))
        t = _call_target(code, ins)
        if t is not None:
            called.add(t)
    fixed = set(code.pointers) | ({entry} if entry is not None else set())
    for t, refs in code.xrefs.items():
        if any(k not in ("call", "branch") for _, k in refs):
            fixed.add(t)
    for f in code.functions:
        if f not in called:
            fixed.add(f)
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
            m = _meet(states[t], st)
            if m != states[t]:
                states[t] = m
                work.append(t)

    while work:
        a = work.pop()
        ins = code.ins[a]
        st = states[a]
        out = _transfer(ins, st)
        for t in _successors(code, ins):
            push(t, out)
        t = _call_target(code, ins)
        if t is not None:
            push(t, st)
    return states


def scan(img, meta, code):
    relocs = set(meta["relocs"])
    prog_end = meta["text"] + meta["data"] + meta["bss"]
    out = {"dos": [], "fefunc": [], "iocs": [], "traps": [], "io": [], "mem": [], "io_ptr": []}
    states = regstates(code, meta["entry"])
    d0 = None           # (value, at, text) of the last constant load into d0 in this block
    last = None
    for a in sorted(code.ins):
        ins = code.ins[a]
        st = states.get(a, {})
        if a in code.labels or a in code.functions or last is None or last.addr + last.size != a:
            d0 = None
        last = ins
        mn = ins.mn
        if mn == "dos":
            out["dos"].append({"at": a, "call": ins.word})
            d0 = None
            continue
        if mn == "fefunc":
            out["fefunc"].append({"at": a, "call": ins.word})
            continue
        if mn == "trap":
            n = ins.ops[0].val
            if n == 15:
                prev = code.ins.get(a - 2)
                if prev is not None and prev.mn == "moveq" and prev.ops[1].reg == "d0":
                    out["iocs"].append({"at": a, "fn": prev.ops[0].val & 0xFF})
                else:
                    e = {"at": a, "fn": None, "d0": None}
                    if d0 is not None:
                        e["d0"] = d0[0] & 0xFF
                        e["note"] = f"d0 = ${d0[0] & 0xFF:02x} set by `{d0[2]}` at ${d0[1]:x}, not adjacent"
                    else:
                        e["note"] = "d0 not a constant in this block (generic IOCS call wrapper)"
                    out["iocs"].append(e)
            else:
                out["traps"].append({"at": a, "n": n, "d0": d0[0] if d0 else None})
            d0 = None
            continue
        for idx, op in enumerate(ins.ops):
            addr, exact = None, True
            if op.kind == "abs":
                if mn in ("jmp", "jsr"):
                    continue
                if op.val < prog_end and _is_prog_abs(img, ins, relocs, op.val):
                    continue
                if mn in ("lea", "pea"):
                    if _hw(op.val):
                        out["io_ptr"].append({"at": a, "addr": op.val, "how": mn})
                    continue
                addr = op.val
            elif op.kind == "imm" and _hw(op.val) and not _is_prog_abs(img, ins, relocs, op.val):
                out["io_ptr"].append({"at": a, "addr": op.val & 0xFFFFFFFF, "how": mn})
                continue
            elif op.kind in ("ind", "postinc", "predec", "disp", "idx") and op.reg in st and mn not in ("lea", "pea"):
                base, exact = st[op.reg]
                if op.kind == "predec":
                    base -= _size(ins)
                addr = base + (op.val or 0)
                exact = exact and op.kind != "idx"
            if addr is None:
                continue
            e = {"at": a, "addr": addr, "access": _access(ins, idx), "size": _size(ins)}
            if mn == "movem":
                e["count"] = bin(ins.ops[1 - idx].val).count("1")     # registers moved
            if not exact:
                e["indexed"] = True
            out["io" if IO_LO <= addr <= IO_HI else "mem"].append(e)
        d0 = _track_d0(ins, d0)
        if mn in ("jsr", "bsr"):
            d0 = None
    return out


def _track_d0(ins, d0):
    ops = ins.ops
    if len(ops) == 2 and ops[1].kind == "dreg" and ops[1].reg == "d0":
        if ins.mn in ("moveq", "move") and ops[0].kind == "imm":
            return (ops[0].val, ins.addr, ins.text)
        return None
    if ins.mn in ("clr",) and ops and ops[0].kind == "dreg" and ops[0].reg == "d0":
        return (0, ins.addr, ins.text)
    if ins.mn == "movem" and ops and ops[-1].kind == "regs":
        return None
    return d0


# ---------------------------------------------------------------- XSP matching

def load_xsp(xsp_dir):
    objs = {}
    for n in ("XSPlibC.o", "XSPlibA.o"):
        p = os.path.join(xsp_dir, n)
        if os.path.exists(p):
            with open(p, "rb") as f:
                objs[n] = hunks.read_object(f.read())
    return objs


def _groups(obj):
    """Entry points grouped per function: canonical name -> (start, end, {label: offset})."""
    text = [(off, name) for name, (sec, off) in obj.symbols.items() if sec == "text"]
    offs = sorted({o for o, _ in text}) + [len(obj.text)]
    byname = defaultdict(dict)
    for off, name in text:
        byname[name.lstrip("_")][name] = off
    out = {}
    for canon, labels in byname.items():
        start = min(labels.values())
        end = min(o for o in offs if o > max(labels.values()))
        out[canon] = (start, end, labels)
    return out


def _pcrel_mask(obj, start, end):
    """obj.mask with PC-relative fields also cleared: d16(pc)/d8(pc,Xn) extension words, and
    branch displacements that leave [start, end). These depend on where XSP's work area and
    other functions sit, so they differ between XSP builds even when the code is the same."""
    mask = bytearray(obj.mask)
    a = start
    while a < end:
        ins = decode(obj.text, a, end)
        if ins is None:
            a += 2
            continue
        words = [(k, struct.unpack_from(">h", obj.text, a + k)[0]) for k in range(2, ins.size - 1, 2)]
        for op in ins.ops:
            if op.kind in ("pcrel", "pcidx") and ins.mn not in ("bra", "bsr") and not (
                    ins.mn.startswith(("b", "db")) and op is ins.ops[-1] and op.kind == "pcrel"
                    and ins.mn not in ("btst", "bset", "bclr", "bchg")):
                disp = op.val - (a + 2)
                for k, w in words:
                    if w == disp or (op.kind == "pcidx" and (w & 0xFF) == (disp & 0xFF)):
                        mask[a + k:a + k + 2] = b"\0\0"
            elif op.kind == "pcrel" and not start <= op.val < end:     # branch out of the function
                if ins.size == 2:
                    mask[a + 1] = 0
                else:
                    mask[a + 2:a + 4] = b"\0\0"
        a += ins.size
    return bytes(mask)


def _pattern(text, mask, start, end):
    return re.compile(b"".join(re.escape(text[i:i + 1]) if mask[i] else b"." for i in range(start, end)), re.S)


def match_xsp_detail(img, objs):
    """Per object and function, where its text matches the image.

    Tier "exact": relocated fields masked. Tier "pcrel": PC-relative fields masked as well (same
    code, different XSP layout), tried only when "exact" finds nothing. Several hits are narrowed
    by link order: an object's functions appear in the image in object order, so a hit must lie
    between the uniquely matched neighbours ("+ordered")."""
    res = {}
    for oname, obj in objs.items():
        groups = sorted(_groups(obj).items(), key=lambda kv: kv[1][0])
        found = {}
        for c, (s, e, _) in groups:
            h = [m.start() for m in _pattern(obj.text, obj.mask, s, e).finditer(img)]
            how = "exact"
            if not h:
                h = [m.start() for m in _pattern(obj.text, _pcrel_mask(obj, s, e), s, e).finditer(img)]
                how = "pcrel"
            found[c] = (h, how)
        deltas = [(s, found[c][0][0] - s) for c, (s, e, _) in groups if len(found[c][0]) == 1]
        for c, (s, e, labels) in groups:
            h, how = found[c]
            if len(h) > 1:
                lo = max([d for o, d in deltas if o < s], default=None)
                hi = min([d for o, d in deltas if o > s], default=None)
                if lo is not None and hi is not None:
                    h = [x for x in h if lo + s <= x <= hi + s]
                    how += "+ordered"
            res.setdefault(c, []).append({"obj": oname, "hits": h, "how": how, "start": s, "end": e,
                                          "labels": labels})
    return res


def _entry(canon, row, hit):
    labels = row["labels"]
    lab = "_" + canon if "_" + canon in labels else canon
    return hit + labels[lab] - row["start"]


def match_xsp(img, objs, detail=None):
    """name -> sorted distinct positions of its C entry point (asm entry if it has no C one),
    over all objects whose match was unique."""
    out = {}
    for canon, rows in (detail or match_xsp_detail(img, objs)).items():
        out[canon] = sorted({_entry(canon, r, r["hits"][0]) for r in rows if len(r["hits"]) == 1})
    return out


def xsp_tables(img, objs, code):
    """(xsp, xsp_how, xsp_asm, xsp_unmatched) for the inventory."""
    detail = match_xsp_detail(img, objs)
    xsp, how, asm, unmatched = {}, {}, {}, {}
    for canon, pos in sorted(match_xsp(img, objs, detail).items()):
        rows = [r for r in detail[canon] if len(r["hits"]) == 1]
        if len(pos) == 1:
            xsp[canon] = pos[0]
            how[canon] = "/".join(sorted({f"{r['obj']}:{r['how']}" for r in rows}))
            r = rows[0]
            if canon in r["labels"] and "_" + canon in r["labels"]:
                a = r["hits"][0] + r["labels"][canon] - r["start"]
                if a != pos[0]:
                    asm[canon] = a
        else:
            unmatched[canon] = {"hits": pos, "tried": sorted({r["obj"] for r in detail[canon]})}
    # Unmatched functions: the game's call targets lying between the matched neighbours (in the
    # object's order) are scored by how many leading bytes match with PC-relative fields masked.
    # The best one is reported as a structural candidate, not as a match.
    ref = max(objs.values(), key=lambda o: sum(1 for n in o.symbols if n.lstrip("_") in unmatched))
    order = sorted(_groups(ref).items(), key=lambda kv: kv[1][0])
    for i, (canon, (gs, ge, labels)) in enumerate(order):
        if canon not in unmatched:
            continue
        before = [xsp[c] for c, _ in order[:i] if c in xsp]
        lo = max(before) + 1 if before else 0
        hi = min([xsp[c] for c, _ in order[i + 1:] if c in xsp], default=min(len(img), lo + len(ref.text)))
        lab = "_" + canon if "_" + canon in labels else canon
        mask = _pcrel_mask(ref, gs, ge)
        best = None
        for f in sorted(f for f in code.functions if lo <= f < hi):
            base = f - (labels[lab] - gs)
            k = 0
            while gs + k < ge and base + k < len(img) and (not mask[gs + k] or img[base + k] == ref.text[gs + k]):
                k += 1
            if best is None or k > best["prefix"]:
                best = {"at": f, "prefix": k, "of": ge - gs, "obj": [n for n, o in objs.items() if o is ref][0]}
        unmatched[canon]["window"] = [lo, hi]
        unmatched[canon]["best"] = best
    return xsp, how, asm, unmatched


# ---------------------------------------------------------------- assembly

def func_of(code, a):
    """Nearest function start at or below `a` (None if none)."""
    fs = [f for f in code.functions if f <= a]
    return max(fs) if fs else None


def _jsr_an_target(code, ins):
    """For `jsr (aN)`: the address last loaded into aN by `lea addr,aN` earlier in the same
    function (the XC compiler's idiom for repeated calls), else None."""
    if ins.mn != "jsr" or ins.ops[0].kind != "ind":
        return None
    f = func_of(code, ins.addr)
    for b in sorted((x for x in code.ins if f is not None and f <= x < ins.addr), reverse=True):
        q = code.ins[b]
        if len(q.ops) == 2 and q.ops[1].kind == "areg" and q.ops[1].reg == ins.ops[0].reg:
            if q.mn == "lea" and q.ops[0].kind in ("abs", "pcrel") and q.ops[0].val in code.ins:
                return q.ops[0].val
            return None
    return None


def iocs_wrappers(code, iocs):
    """Functions that issue trap #15 with d0 taken from their first stack argument (C wrappers
    like `iocs(fn, d1, ...)`), and their call sites with the fn pushed last before the call."""
    wrappers = set()
    for e in iocs:
        if e["fn"] is not None:
            continue
        f = func_of(code, e["at"])
        for a in sorted(x for x in code.ins if f is not None and f <= x < e["at"]):
            i = code.ins[a]
            if (i.mn == "move" and len(i.ops) == 2 and i.ops[1].kind == "dreg" and i.ops[1].reg == "d0"
                    and i.ops[0].kind == "disp" and i.ops[0].reg in ("a7", "sp")):
                wrappers.add(f)
    sites = []
    for a in sorted(code.ins):
        ins = code.ins[a]
        t = _call_target(code, ins) or _jsr_an_target(code, ins)
        if t not in wrappers:
            continue
        # the argument pushed last is fn: walk back over register setup to the nearest push
        fn, b = None, a
        for _ in range(4):
            prev = next((code.ins[x] for x in (b - 2, b - 4, b - 6) if x in code.ins
                         and x + code.ins[x].size == b), None)
            if prev is None:
                break
            b = prev.addr
            if prev.mn == "lea" or (prev.mn == "movea" and prev.ops[1].reg not in ("a7", "sp")):
                continue
            if prev.mn == "pea" and prev.ops[0].kind == "abs":
                fn = prev.ops[0].val & 0xFF
            elif prev.mn == "move" and prev.ops[0].kind == "imm" and prev.ops[1].kind == "predec":
                fn = prev.ops[0].val & 0xFF
            break
        sites.append({"at": a, "via": t, "fn": fn})
    return sorted(wrappers), sites


def clib_start(code):
    """First function after the last one with a `link a6` frame: the XC C compiler gives every
    game function with locals a frame; the XC library (assembly) after it does not."""
    links = [a for a, i in code.ins.items() if i.mn == "link"]
    if not links:
        return None
    last = func_of(code, max(links))
    later = [f for f in code.functions if f > last]
    return min(later) if later else None


def unreached(img, meta, code):
    """Gaps in the text that decode cleanly as code (same test as code pointers) but that
    nothing found references: dead code, or reached in a way this analysis misses."""
    out = []
    limit = meta["text"]
    a = 0
    probe = Code()
    probe.ins, probe.owner = dict(code.ins), dict(code.owner)
    w = _Walker(img, limit, set(meta["relocs"]), probe, meta["text"] + meta["data"] + meta["bss"])
    while a < limit:
        if a in code.ins:
            a += code.ins[a].size
            continue
        if a in code.owner or a & 1:
            a += 1
            continue
        b = a
        while b < limit and b not in code.ins and b not in code.owner:
            b += 1
        if b - a >= 8 and not _is_string(img, a):
            ok, new = w.walk([a], trial=True)
            if ok and new and max(new) < b:
                out.append({"start": a, "end": max(x + new[x].size for x in new), "first": new[a].text})
        a = b
    return out


def string_refs(img, code, n, sha1):
    """Offset of the `n` bytes with SHA1 `sha1` in the image (the lowest), the instructions
    referencing it, their functions and those functions' callers; None if the image has none."""
    try:
        s = orig_bytes.find(img, n, sha1)
    except ValueError:
        return None
    refs = []
    for a, ins in sorted(code.ins.items()):
        if any(o.kind in ("pcrel", "abs") and o.val == s for o in ins.ops):
            f = func_of(code, a)
            refs.append({"at": a, "func": f, "callers": sorted(x for x, _ in code.xrefs.get(f, []))})
    return {"offset": s, "refs": refs}


def clib_entries(code, inv, start):
    """XC library functions the game calls directly, with the system calls each can reach
    (through direct calls inside the library)."""
    if start is None:
        return []
    funcs = sorted(code.functions)
    import bisect

    def owner(a):
        i = bisect.bisect_right(funcs, a) - 1
        return funcs[i] if i >= 0 else None

    body = defaultdict(set)
    callees = defaultdict(set)
    for e in inv["dos"] + inv["fefunc"]:
        body[owner(e["at"])].add("%04X" % e["call"])
    for e in inv["iocs"]:
        body[owner(e["at"])].add("IOCS %02X" % e["fn"] if e["fn"] is not None else "IOCS ?")
    for e in inv["traps"]:
        body[owner(e["at"])].add("trap #%d" % e["n"])
    callers = defaultdict(int)
    for a, ins in code.ins.items():
        t = _call_target(code, ins) or _jsr_an_target(code, ins)
        if t is not None:
            callees[owner(a)].add(t)
            if a < start:
                callers[t] += 1
    memo = {}

    def reach(f, seen):
        if f in memo:
            return memo[f]
        out = set(body[f])
        for g in callees[f]:
            if g not in seen and g >= start:
                out |= reach(g, seen | {g})
        memo[f] = out
        return out

    rows = []
    for f in funcs:
        if f < start:
            continue
        if callers[f]:
            rows.append({"at": f, "game_calls": callers[f], "sys": sorted(reach(f, {f}))})
    return rows


def analyze(img, meta, objs=None, code=None):
    if code is None:
        code = disassemble(img, meta)
    inv = scan(img, meta, code)
    inv["iocs_wrappers"], inv["iocs_via"] = iocs_wrappers(code, inv["iocs"])
    inv["xsp"], inv["xsp_how"], inv["xsp_asm"], inv["xsp_unmatched"] = (
        xsp_tables(img, objs, code) if objs else ({}, {}, {}, {}))
    inv["functions"] = sorted(code.functions)
    inv["clib_start"] = clib_start(code)
    inv["clib_entries"] = clib_entries(code, inv, inv["clib_start"])
    inv["pointers"] = {str(t): s for t, s in sorted(code.pointers.items())}
    inv["tables"] = [{"at": a, "base": b, "cases": len(t)} for a, b, t in sorted(code.tables)]
    inv["external"] = {str(t): f for t, f in sorted(code.external.items())}
    inv["unreached"] = unreached(img, meta, code)
    inv["coverage"] = {"insns": len(code.insns), "bytes": sum(code.insns.values()), "text": meta["text"]}
    inv["kakusi"] = string_refs(img, code, *KAKUSI_HEADER)
    return inv


# ---------------------------------------------------------------- report

def _h(v, w=0):
    return "$%0*X" % (w, v) if v is not None else "-"


def _sites(xs, n=6):
    xs = sorted(xs)
    out = ", ".join(_h(x) for x in xs[:n])
    return out + (f" (+{len(xs) - n})" if len(xs) > n else "")


def _name(table, k):
    return table.get(k, "unknown")


# What the drivers behind the other traps do with d0 (trap -> {d0: meaning}). MCDRV's, from its
# dispatch table in the unpacked MCDRV.X (docs/notes/sound-recon.md §1, "MCDRV function meanings").
TRAP_FUNCTIONS = {4: {0x01: "set data (a0 = data, d1 = size)", 0x02: "play", 0x05: "stop",
                      0x14: "fade (d1 = speed)"}}


def trap_meaning(n, d0):
    """The "Other traps" table's meaning of trap #n with d0."""
    what = x68k_names.TRAPS.get(n, "unknown driver")
    return f"{what}: function {_h(d0, 2)}, {TRAP_FUNCTIONS.get(n, {}).get(d0, 'meaning unknown')}"


def to_markdown(inv, meta):
    """The generated tables of docs/notes/inventory.md (hand annotations are added there)."""
    from collections import defaultdict as dd
    L = []
    w = L.append
    cov = inv["coverage"]
    w("# SZ2 inventory: what the game asks of the X68000\n")
    w("Generated by `make inventory` (tools/inventory.py) from `build/orig/sz2.bin`. Offsets are "
      "base-0 image offsets (add the load address for a run-time address).\n")
    w(f"- Image: text {_h(meta['text'])}, data {_h(meta['data'])}, bss {_h(meta['bss'])}, "
      f"entry {_h(meta['entry'])}, {len(meta['relocs'])} relocations")
    w(f"- Decoded: {cov['insns']} instructions, {_h(cov['bytes'])} of {_h(cov['text'])} text bytes; "
      f"{len(inv['functions'])} functions ({len(inv['pointers'])} found only as code pointers), "
      f"{len(inv['tables'])} switch tables")
    w(f"- XC library starts at {_h(inv['clib_start'])} (first function after the last `link a6` frame)\n")

    def calltable(title, rows, table, width):
        w(f"## {title}\n")
        w("| Call | Name | Sites | Where |")
        w("|---|---|---|---|")
        by = dd(list)
        for e in rows:
            by[e["call"]].append(e["at"])
        for k in sorted(by):
            w(f"| {_h(k, width)} | {_name(table, k)} | {len(by[k])} | {_sites(by[k])} |")
        w(f"\n{len(rows)} sites, {len(by)} distinct calls.\n")

    calltable("Human68k DOS calls (F-line $FFxx)", inv["dos"], x68k_names.DOS, 4)
    calltable("FLOAT driver calls (F-line $FExx)", inv["fefunc"], x68k_names.FEFUNC, 4)

    w("## XC library entry points called by the game\n")
    w(f"Functions at or after {_h(inv['clib_start'])} called from game code (`jsr`/`bsr`, or "
      "`jsr (aN)` after `lea f,aN`), with the system calls they reach (DOS $FFxx, FLOAT $FExx, "
      "IOCS, traps) through such calls inside the library.\n")
    w("| Function | Game call sites | Reaches |")
    w("|---|---|---|")
    for r in inv["clib_entries"]:
        w(f"| {_h(r['at'])} | {r['game_calls']} | {', '.join(r['sys']) or '-'} |")
    w("")

    w("## IOCS calls (trap #15)\n")
    w("Direct: `moveq #fn,d0` right before `trap #15`. Via wrapper: calls of the C helper "
      + ", ".join(_h(x) for x in inv["iocs_wrappers"]) + " (`iocs(fn, d1, d2, ...)`; fn = the "
      "argument pushed last).\n")
    w("| fn | Name | Direct sites | Where | Via wrapper | Where |")
    w("|---|---|---|---|---|---|")
    d, v = dd(list), dd(list)
    for e in inv["iocs"]:
        d[e["fn"] if e["fn"] is not None else e.get("d0")].append(e["at"])
    for e in inv["iocs_via"]:
        v[e["fn"]].append(e["at"])
    for k in sorted(set(d) | set(v), key=lambda x: -1 if x is None else x):
        name = _name(x68k_names.IOCS, k) if k is not None else "(fn not constant)"
        w(f"| {_h(k, 2)} | {name} | {len(d[k])} | {_sites(d[k])} | {len(v[k])} | {_sites(v[k])} |")
    for e in inv["iocs"]:
        if e["fn"] is None:
            w(f"\n- trap #15 at {_h(e['at'])}: {e['note']}")
    w("")

    w("## Other traps\n")
    w("| trap | d0 | Meaning | Sites | Where |")
    w("|---|---|---|---|---|")
    t = dd(list)
    for e in inv["traps"]:
        t[(e["n"], e["d0"])].append(e["at"])
    for (n, d0), xs in sorted(t.items(), key=lambda kv: (kv[0][0], kv[0][1] if kv[0][1] is not None else -1)):
        w(f"| #{n} | {_h(d0, 2)} | {trap_meaning(n, d0)} | {len(xs)} | {_sites(xs)} |")
    w("")

    w("## Hardware accesses by device\n")
    w("Absolute addresses, or an address register holding a hardware address (forward dataflow "
      "over the control-flow graph, into callees reached only by direct calls). \"indexed\" = "
      "base address plus an index the analysis does not know (loops, tables): the row gives the "
      "base. Size `4x13` = a movem of 13 longs starting there.\n")
    acc = dd(lambda: {"acc": set(), "size": set(), "sites": [], "idx": False})
    for e in inv["io"] + inv["mem"]:
        r = acc[e["addr"]]
        r["acc"].add(e["access"])
        r["size"].add(f"{e['size']}x{e['count']}" if "count" in e else str(e["size"]))
        r["sites"].append(e["at"])
        r["idx"] |= bool(e.get("indexed"))
    bydev = dd(list)
    for a in acc:
        bydev[x68k_names.device(a)].append(a)
    order = {name: i for i, (_, _, name) in enumerate(x68k_names.DEVICES)}
    for dev in sorted(bydev, key=lambda n: order.get(n, 99)):
        w(f"### {dev}\n")
        w("| Address | Register | Access | Size | Indexed | Sites | Where |")
        w("|---|---|---|---|---|---|---|")
        for a in sorted(bydev[dev]):
            r = acc[a]
            a_s = "rw" if "rw" in r["acc"] or {"r", "w"} <= r["acc"] else "".join(sorted(r["acc"]))
            w(f"| {_h(a, 6)} | {x68k_names.register(a) or 'unknown'} | {a_s} | "
              f"{'/'.join(sorted(r['size']))} | {'yes' if r['idx'] else ''} | "
              f"{len(r['sites'])} | {_sites(r['sites'], 4)} |")
        w("")

    w("## Hardware addresses as constants\n")
    w("Every hardware address loaded, pushed or added as a constant (immediate or `lea`/`pea` "
      "operand). Where it then went into a register used in place, the accesses are in the "
      "tables above; otherwise (pushed as an argument, kept in a variable) the access happens "
      "through a pointer the analysis does not follow.\n")
    w("| Address | Device | Register | Sites | Where |")
    w("|---|---|---|---|---|")
    p = dd(list)
    for e in inv["io_ptr"]:
        p[e["addr"]].append(e["at"])
    for a in sorted(p):
        w(f"| {_h(a, 6)} | {x68k_names.device(a)} | {x68k_names.register(a) or 'unknown'} | "
          f"{len(p[a])} | {_sites(p[a], 4)} |")
    w("")

    w("## XSP entry points\n")
    w("Matched against XSP 1.99 `XSPlibC.o`/`XSPlibA.o`: \"exact\" = text equal with relocated "
      "fields masked; \"pcrel\" = equal once PC-relative displacements are masked too (same code, "
      "different XSP layout); \"+ordered\" = several hits narrowed by link order. Offsets are the "
      "C entry (`_name`, arguments on the stack); \"asm entry\" is the register-argument label "
      "where it differs.\n")
    w("| Function | Game offset | asm entry | Found by |")
    w("|---|---|---|---|")
    for n in sorted(set(inv["xsp"]) | set(inv["xsp_unmatched"])):
        if n in inv["xsp"]:
            w(f"| {n} | {_h(inv['xsp'][n])} | {_h(inv['xsp_asm'].get(n))} | {inv['xsp_how'][n]} |")
        else:
            u = inv["xsp_unmatched"][n]
            b = u.get("best")
            cand = (f"not matched; candidate {_h(b['at'])} ({b['prefix']} of {b['of']} bytes match "
                    f"from the start, {b['obj']})") if b else "not matched; no candidate"
            w(f"| {n} | - | - | {cand} |")
    w("")

    w("## Code pointers, switch tables, unreached code\n")
    w("Functions found only through a pointer (lea/pea operand, `move.l #f`, or a relocated word "
      "outside instructions) that decodes cleanly as code:\n")
    srcs = dd(list)
    for t_, src in inv["pointers"].items():
        srcs[src.split(" at ")[0]].append(int(t_))
    for k in sorted(srcs):
        w(f"- {k}: {len(srcs[k])} ({_sites(srcs[k], 8)})")
    w("\nSwitch tables: " + ", ".join(f"{_h(t_['at'])} ({t_['cases']} cases)" for t_ in inv["tables"]))
    w("\nUnreached code candidates (decode cleanly, nothing found references them):\n")
    w("| Start | End | Bytes |")
    w("|---|---|---|")
    for u in inv["unreached"]:
        w(f"| {_h(u['start'])} | {_h(u['end'])} | {u['end'] - u['start']} |")
    if inv["external"]:
        w("\nCalls/jumps into data or bss: " + ", ".join(_h(int(k)) for k in inv["external"]))
    w("")

    k = inv["kakusi"]
    w("## KAKUSI menu (generated facts)\n")
    if k:
        w(f"- Header string ({KAKUSI_HEADER[0]} bytes) at {_h(k['offset'])}")
        for r in k["refs"]:
            w(f"- Referenced at {_h(r['at'])} in function {_h(r['func'])}, called from "
              + (", ".join(_h(c) for c in r["callers"]) or "nowhere found"))
    w("")
    return "\n".join(L) + "\n"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", default="build/orig")
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv[1:])
    with open(os.path.join(a.orig, "sz2.bin"), "rb") as f:
        img = f.read()
    with open(os.path.join(a.orig, "sz2.json")) as f:
        meta = json.load(f)
    inv = analyze(img, meta, load_xsp(os.path.join(a.orig, "xsp")))
    out = a.out or os.path.join(a.orig, "inventory.json")
    with open(out, "w") as f:
        json.dump(inv, f, indent=1)
    if a.md:
        with open(a.md, "w") as f:
            f.write(to_markdown(inv, meta))
    print(out, {k: len(v) if isinstance(v, (list, dict)) else v for k, v in inv.items()})


if __name__ == "__main__":
    main(sys.argv)
