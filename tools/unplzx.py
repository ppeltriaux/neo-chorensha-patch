"""Unpack SZ2.X (Human68k .X packed with PLZX 1.04) and list its relocations.

  .venv/bin/python -I tools/unplzx.py --x build/orig/disk/GAME/SZ2.X --out build/orig

Writes <out>/sz2.bin (text+data relocated to base 0) and <out>/sz2.json
{text, data, bss, entry, relocs}. Each reloc is the offset of a 32-bit word holding a
base-0 address. The depacker runs under Unicorn (M68000) at two bases; the words that
differ by exactly the base delta are the relocations.
"""
import argparse
import json
import os
import struct
import sys

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_INTR
from unicorn.m68k_const import (UC_CPU_M68K_M68000, UC_M68K_REG_A0, UC_M68K_REG_A1,
                                UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4,
                                UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC)

HDR = 0x40          # Human68k .X header size; the PLZX stub starts here
MEM = 0x1000000
STACK = 0xC00000
ENV = 0x8000
TRAP15 = 0x4E4F
B_BPEEK = 0x82      # the stub reads the MPU type byte at $CBC with it (0 = 68000)
SYS_STAT = 0xAC
MAX_STEPS = 200
# PLZX stub header (offsets from the stub start): entry $0E, total size $12 (text+data+bss, the
# initial sp), data size $16, bss size $1A, size of the original .X relocation table $1E.
# The stub sets PSP+$30 (bss start) = base + total - bss, so text = total - data - bss.
STUB_ENTRY = 0x0E
STUB_TOTAL = 0x12


def _stub_info(x):
    s = x[HDR:]
    if s[3:12] != b"PLZX 1.04":
        raise ValueError("not a PLZX 1.04 packed .X")
    entry, total, data, bss = struct.unpack(">IIII", s[STUB_ENTRY:STUB_TOTAL + 12])
    return {"text": total - data - bss, "data": data, "bss": bss, "entry": entry}


def unpack(x_file, base):
    """Return the memory image at `base` when the depacked program makes its first DOS call."""
    ptext, pdata, pbss = struct.unpack(">III", x_file[0x0C:0x18])
    (pexec,) = struct.unpack(">I", x_file[8:12])
    psp = base - 0x100
    mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    mu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
    mu.mem_map(0, MEM)
    mu.mem_write(base, x_file[HDR:HDR + ptext + pdata])
    mu.mem_write(psp + 8, struct.pack(">I", STACK))  # end of the memory block
    mu.reg_write(UC_M68K_REG_A0, psp)
    mu.reg_write(UC_M68K_REG_A1, base + ptext + pdata + pbss)
    mu.reg_write(UC_M68K_REG_A2, psp + 0x80)
    mu.reg_write(UC_M68K_REG_A3, ENV)
    mu.reg_write(UC_M68K_REG_A4, base + pexec)
    mu.reg_write(UC_M68K_REG_A7, STACK)
    stop = {}

    def on_intr(uc, intno, _):
        stop["pc"] = uc.reg_read(UC_M68K_REG_PC)
        uc.emu_stop()

    mu.hook_add(UC_HOOK_INTR, on_intr)
    pc = base
    for _ in range(MAX_STEPS):
        stop.clear()
        mu.emu_start(pc, 0xFFFFFF, count=50_000_000)
        if "pc" not in stop:
            raise RuntimeError("depacker ran out of steps without a DOS call")
        pc = stop["pc"]
        (op,) = struct.unpack(">H", mu.mem_read(pc, 2))
        if op & 0xF000 == 0xF000:
            return bytes(mu.mem_read(base, 0x40000))  # F-line: first DOS call
        if op != TRAP15:
            raise RuntimeError("depacker stopped on $%04X at $%X (not trap #15 or a DOS call)" % (op, pc))
        func = mu.reg_read(UC_M68K_REG_D0) & 0xFF
        if func == B_BPEEK:
            mu.reg_write(UC_M68K_REG_D0, 0)
            mu.reg_write(UC_M68K_REG_A1, mu.reg_read(UC_M68K_REG_A1) + 1)
        elif func == SYS_STAT:
            mu.reg_write(UC_M68K_REG_D0, 0)
        else:
            raise RuntimeError("unhandled IOCS call $%02X at $%X" % (func, pc))
        pc += 2
    raise RuntimeError("depacker did not finish")


def convert(x_file, base_a=0x20000, base_b=0x80000):
    """Return (meta, base0_image) for a packed .X."""
    meta = _stub_info(x_file)
    n = meta["text"] + meta["data"]
    a = unpack(x_file, base_a)[:n]
    b = unpack(x_file, base_b)[:n]
    delta = base_b - base_a
    relocs = []
    covered = set()
    for d in range(n):
        if a[d] == b[d] or d in covered:
            continue
        # The first differing byte is byte 1 of the word (addresses are < $1000000),
        # or byte 0..3 on a carry; take the lowest start whose words differ by delta.
        for s in range(max(0, d - 3), min(d, n - 4) + 1):
            if covered.intersection(range(s, s + 4)):
                continue
            wa = struct.unpack(">I", a[s:s + 4])[0]
            wb = struct.unpack(">I", b[s:s + 4])[0]
            if wb - wa == delta:
                relocs.append(s)
                covered.update(range(s, s + 4))
                break
        else:
            raise RuntimeError("unexplained difference at offset $%X" % d)
    img = bytearray(a)
    for r in relocs:
        (w,) = struct.unpack(">I", img[r:r + 4])
        img[r:r + 4] = struct.pack(">I", w - base_a)
    meta["relocs"] = relocs
    return meta, bytes(img)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.x, "rb") as f:
        meta, img = convert(f.read())
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "sz2.bin"), "wb") as f:
        f.write(img)
    with open(os.path.join(a.out, "sz2.json"), "w") as f:
        json.dump(meta, f)
    print("sz2.bin %d bytes, %d relocs, entry $%X" % (len(img), len(meta["relocs"]), meta["entry"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
