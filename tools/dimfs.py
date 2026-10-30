"""Read a Human68k FAT12 disk image in X68000 DIM format (256-byte header + sectors)."""
import struct
from collections import namedtuple

DimEntry = namedtuple("DimEntry", "path is_dir data")

HEADER = 256


def _name(e):
    base = (e[0:8] + e[0x0C:0x16]).rstrip(b" \0").decode("shift_jis", "replace")
    ext = e[8:11].rstrip(b" ").decode("shift_jis", "replace")
    return base + ("." + ext if ext else "")


def read_dim(data):
    d = data[HEADER:]
    bps, spc, res, nfat, nroot = struct.unpack_from("<HBHBH", d, 0x0B)
    spf = struct.unpack_from("<H", d, 0x16)[0]
    if not (bps and spc and nfat and spf):
        raise ValueError("bad BPB")
    fat = d[res * bps:(res + spf) * bps]
    root_off = (res + nfat * spf) * bps
    data_off = root_off + nroot * 32
    csize = spc * bps

    def fat12(n):
        o = n * 3 // 2
        v = fat[o] | (fat[o + 1] << 8)
        return (v >> 4) if n & 1 else (v & 0xFFF)

    def chain(c):
        seen = set()
        while 2 <= c < 0xFF8 and c not in seen:
            seen.add(c)
            yield c
            c = fat12(c)

    def read_chain(c):
        return b"".join(d[data_off + (x - 2) * csize:data_off + (x - 1) * csize] for x in chain(c))

    out = []

    def walk(buf, prefix):
        for i in range(0, len(buf), 32):
            e = buf[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                continue
            attr = e[11]
            if attr & 0x08:
                continue
            name = _name(e)
            if name in (".", ".."):
                continue
            c = struct.unpack_from("<H", e, 26)[0]
            size = struct.unpack_from("<I", e, 28)[0]
            path = prefix + name
            if attr & 0x10:
                out.append(DimEntry(path, True, b""))
                walk(read_chain(c), path + "/")
            else:
                out.append(DimEntry(path, False, read_chain(c)[:size]))

    walk(d[root_off:data_off], "")
    return out
