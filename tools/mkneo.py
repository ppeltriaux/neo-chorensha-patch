#!/usr/bin/env python3
"""Pack the built cart into a .neo for the MiSTer Neo Geo core (TerraOnion NeoSD v1, as Main_MiSTer's
support/neogeo/neogeo_loader.cpp load_neo reads it).

A 4,096-byte little-endian header, then the regions in the order P S M V1 V2 C:
  "NEO" 1, u32 sizes P S M V1 V2 C, u32 year, genre, screenshot, NGH, name (33 bytes),
  manufacturer (17 bytes), zero fill to 4,096.
P is the cart's .p1 as MAME loads it (word-swapped, so a little-endian word at P+$108 is the NGH
number); S and M as files; V1 the 4 MB V-ROM and V2 empty (the core then lets ADPCM-B read V1);
C the C1/C2 pair interleaved byte by byte, C1 on the even bytes. The NGH (0x0C68) is in none of the
loader's quirk entries: no special chip, the plain cart.
Input: the cart files tools/mkcart.py wrote in --build (build/neo).
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkcart  # noqa: E402
import mkstandin  # noqa: E402

HEADER_SIZE = 4096
HEADER_FMT = "<4s6I4I33s17s"   # magic+version, six sizes, year genre screenshot NGH, name, maker
REGIONS = ("P", "S", "M", "V1", "V2", "C")
NAME_LEN = 33
MAKER_LEN = 17


def text(s, n, what):
    b = s.encode("ascii")
    if len(b) >= n:       # the loader prints it as a C string: keep the terminating zero
        raise ValueError("%s %r is longer than %d bytes" % (what, s, n - 1))
    return b


def build_neo(cart, name="Neo-Chorensha", manufacturer="homebrew", year=2026, genre=7):
    """The .neo bytes of `cart` ({p1 s1 m1 v1 c1 c2: the files as mkcart wrote them})."""
    p, s, m, v1 = cart["p1"], cart["s1"], cart["m1"], cart["v1"]
    c1, c2 = cart["c1"], cart["c2"]
    if len(c1) != len(c2):
        raise ValueError("c1 and c2 differ in size")
    c = bytearray(len(c1) * 2)
    c[0::2], c[1::2] = c1, c2
    ngh = mkcart.ngh(mkcart.word_swap(p))   # mkcart reads the unswapped image
    head = struct.pack(HEADER_FMT, b"NEO\x01", len(p), len(s), len(m), len(v1), 0, len(c),
                       year, genre, 0, ngh, text(name, NAME_LEN, "name"),
                       text(manufacturer, MAKER_LEN, "manufacturer"))
    return head.ljust(HEADER_SIZE, b"\0") + p + s + m + v1 + bytes(c)


def read_neo(data):
    """The header's fields and the regions of .neo bytes `data`."""
    (magic, p, s, m, v1, v2, c, year, genre, shot, ngh, name, maker) = struct.unpack_from(
        HEADER_FMT, data, 0)
    sizes = (p, s, m, v1, v2, c)
    if len(data) != HEADER_SIZE + sum(sizes):
        raise ValueError("size %d is not the header plus the regions (%d)" % (
            len(data), HEADER_SIZE + sum(sizes)))
    regions, at = {}, HEADER_SIZE
    for key, n in zip(REGIONS, sizes):
        regions[key] = data[at:at + n]
        at += n
    return {"magic": magic[:3], "version": magic[3], "sizes": sizes, "year": year, "genre": genre,
            "screenshot": shot, "ngh": ngh, "name": name.split(b"\0")[0].decode("ascii"),
            "manufacturer": maker.split(b"\0")[0].decode("ascii"), "regions": regions}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", default="build/neo", help="the cart's folder (tools/mkcart.py)")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)
    cart = {}
    for ext in ("p1", "s1", "m1", "v1", "c1", "c2"):
        cart[ext] = mkcart.read(mkstandin.cart_file(args.build, ext))
    data = build_neo(cart)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(data)
    print("%s: %d bytes, NGH %#06x" % (args.output, len(data), read_neo(data)["ngh"]))


if __name__ == "__main__":
    main()
