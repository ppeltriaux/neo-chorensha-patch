"""LZH (LHA) reader: header levels 0 and 1; methods -lh0-, -lh5-, -lhd-."""
import struct
from collections import namedtuple

LzhEntry = namedtuple("LzhEntry", "path is_dir data")


def crc16(data, crc=0):
    """CRC-16/ARC (poly 0xA001 reflected, init 0)."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class _Bits:
    def __init__(self, d):
        self.d, self.p, self.buf, self.n = d, 0, 0, 0

    def _fill(self, k):
        while self.n < k:
            b = self.d[self.p] if self.p < len(self.d) else 0
            self.p += 1
            self.buf = ((self.buf << 8) | b) & 0xFFFFFFFFFF
            self.n += 8

    def get(self, k):
        if k == 0:
            return 0
        self._fill(k)
        self.n -= k
        return (self.buf >> self.n) & ((1 << k) - 1)


def _table(lens):
    codes, code = {}, 0
    maxl = max(lens) if lens else 0
    for L in range(1, maxl + 1):
        for sym, l in enumerate(lens):
            if l == L:
                codes[(L, code)] = sym
                code += 1
        code <<= 1
    return codes, maxl


def _dec(bits, tab):
    codes, maxl = tab
    c = 0
    for L in range(1, maxl + 1):
        c = (c << 1) | bits.get(1)
        if (L, c) in codes:
            return codes[(L, c)]
    raise ValueError("bad huffman code")


def _read_len(b):
    l = b.get(3)
    if l == 7:
        while b.get(1):
            l += 1
    return l


def lh5(data, osize, dicbit=13):
    np_ = dicbit + 1
    pbit = 4
    b = _Bits(data)
    out = bytearray()
    while len(out) < osize:
        blocksize = b.get(16)
        # code-length code table (NT=19, TBIT=5)
        n = b.get(5)
        if n == 0:
            ptc, pt = b.get(5), None
        else:
            ptl, i = [0] * 19, 0
            while i < n:
                ptl[i] = _read_len(b)
                i += 1
                if i == 3:
                    i += b.get(2)
            ptc, pt = None, _table(ptl)
        # literal/length table (NC=510)
        n = b.get(9)
        if n == 0:
            cconst, ct = b.get(9), None
        else:
            cl, i = [0] * 510, 0
            while i < n:
                c = ptc if pt is None else _dec(b, pt)
                if c <= 2:
                    i += 1 if c == 0 else (b.get(4) + 3 if c == 1 else b.get(9) + 20)
                else:
                    cl[i] = c - 2
                    i += 1
            cconst, ct = None, _table(cl)
        # position table
        n = b.get(pbit)
        if n == 0:
            pconst, ptt = b.get(pbit), None
        else:
            pl = [0] * np_
            for i in range(n):
                pl[i] = _read_len(b)
            pconst, ptt = None, _table(pl)
        for _ in range(blocksize):
            c = cconst if ct is None else _dec(b, ct)
            if c < 256:
                out.append(c)
            else:
                ln = c - 256 + 3
                p = pconst if ptt is None else _dec(b, ptt)
                if p > 1:
                    p = (1 << (p - 1)) + b.get(p - 1)
                src = len(out) - p - 1
                for k in range(ln):
                    out.append(out[src + k])
            if len(out) >= osize:
                break
    return bytes(out[:osize])


def read_lzh(data):
    out, p = [], 0
    while p < len(data) and data[p] != 0:
        hs, level = data[p], data[p + 20]
        if level not in (0, 1):
            raise ValueError("unsupported LZH header level %d" % level)
        method = data[p + 2:p + 7].decode("ascii")
        csz, osz = struct.unpack_from("<II", data, p + 7)
        nl = data[p + 21]
        name = data[p + 22:p + 22 + nl]
        crc = struct.unpack_from("<H", data, p + 22 + nl)[0]
        dirn = b""
        if level == 0:
            q = p + 2 + hs
        else:
            q = p + 2 + hs
            nx = struct.unpack_from("<H", data, q - 2)[0]
            ext = 0
            while nx:
                t, body = data[q], data[q + 1:q + nx - 2]
                if t == 1:
                    name = body
                elif t == 2:
                    dirn = body.replace(b"\xff", b"/")
                ext += nx
                q += nx - 2
                nx = struct.unpack_from("<H", data, q)[0]
                q += 2
            csz -= ext
        path = (dirn + name).decode("shift_jis", "replace").rstrip("/")
        cd = data[q:q + csz]
        p = q + csz
        if method == "-lhd-":
            out.append(LzhEntry(path, True, b""))
            continue
        if method == "-lh0-":
            od = cd
        elif method == "-lh5-":
            od = lh5(cd, osz)
        else:
            raise ValueError("unsupported method " + method)
        if len(od) != osz or crc16(od) != crc:
            raise ValueError("CRC mismatch in " + path)
        out.append(LzhEntry(path, False, od))
    return out
