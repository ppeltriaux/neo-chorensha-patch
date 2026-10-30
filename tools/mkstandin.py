#!/usr/bin/env python3
"""Repackage the built cart as a stand-in for a Neo Geo set that arcade front-ends already know
(adapted from neo-r-type's tools/mkstandin.py, whose stand-in is quizkof).

Arcade front-ends run Neo Geo games from MAME's game list, not from software-list carts, so the
cart goes out under the name of an existing set with that set's file layout. The set is
marukodq (Chibi Maruko-chan: Maruko Deluxe Quiz, Takara 1995; MAME snk/neogeo.cpp): a plain cart
(no protection, no encryption, joystick controls) whose regions take ours as they are:

  206-p1.p1  1 MB     maincpu, load16_word_swap at 0     our P1 as built (1 MB, word-swapped)
  206-s1.s1  128 KB   fixed                              our S1
  206-m1.m1  128 KB   audiocpu                           our M1
  206-v1.v1  2 MB     ymsnd:adpcma 0                     our V-ROM's first 2 MB (the effects first)
  206-v2.v2  2 MB     ymsnd:adpcma 2 MB                  our V-ROM's second 2 MB
  206-c1.c1  4 MB     sprites, even bytes from 0         our C1 (1 MB) padded with zeros
  206-c2.c2  4 MB     sprites, odd bytes from 1          our C2 (1 MB) padded with zeros
  206-c3.c3  1 MB     sprites from 8 MB                  zeros
  206-c4.c4  1 MB     sprites from 8 MB                  zeros

The C1/C2 pair is interleaved byte by byte from offset 0 as on our cart, so our 2 MB of tiles are
the region's first 2 MB, tile numbers unchanged. The set's one ymsnd:adpcma region (4 MB, no
adpcmb region, as our cart's) takes our 4 MB V-ROM whole (tools/mksound.py: the effects and tunes),
so the samples' addresses are the cart's. MAME reports the checksums as wrong and runs it. The Neo
Geo BIOS set (neogeo.zip) must sit in the same folder.

Input: the cart tools/mkcart.py built (<build>/<ngh>-p1.p1 and the rest, make cart). Output:
build/standin/marukodq.zip by default (make standin). The zip holds the port's P-ROM and art,
derived from the user's dump of the original: never committed (build/ is ignored).
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkcart  # noqa: E402

SET = "marukodq"
PREFIX = "206"
# file -> (size, source extension in the cart or None for zeros, offset into that source)
LAYOUT = [
    ("p1", 0x100000, "p1", 0),
    ("s1", 0x020000, "s1", 0),
    ("m1", 0x020000, "m1", 0),
    ("v1", 0x200000, "v1", 0),
    ("v2", 0x200000, "v1", 0x200000),
    ("c1", 0x400000, "c1", 0),
    ("c2", 0x400000, "c2", 0),
    ("c3", 0x100000, None, 0),
    ("c4", 0x100000, None, 0),
]


def cart_file(build, ext):
    """The cart's file of that extension (the prefix is the NGH number mkcart.py read)."""
    found = [p for p in glob.glob(os.path.join(build, "*-%s.%s" % (ext, ext)))
             if os.path.basename(p)[:3] != PREFIX]
    if len(found) != 1:
        sys.exit("%s: %s cart file(s) *-%s.%s: build the cart first (make cart)" % (
            build, len(found) or "no", ext, ext))
    return found[0]


def roms(build):
    """{file name in the set: bytes} (module doc's table)."""
    src = {}
    for _, _, ext, _ in LAYOUT:
        if ext and ext not in src:
            with open(cart_file(build, ext), "rb") as f:
                src[ext] = f.read()
    # every byte of the cart has a place: P/S/M exactly, V and C within the files they fill
    for ext, room in (("p1", 0x100000), ("s1", 0x20000), ("m1", 0x20000), ("v1", 0x400000),
                      ("c1", 0x400000), ("c2", 0x400000)):
        data = src[ext]
        if ext in ("p1", "s1", "m1") and len(data) != room:
            sys.exit("%s is %#x bytes, the set's %s is %#x" % (ext, len(data), ext, room))
        if len(data.rstrip(b"\0")) > room:
            sys.exit("%s: %#x bytes used, more than the set's %#x" % (
                ext, len(data.rstrip(b"\0")), room))
    out = {}
    for name, size, ext, off in LAYOUT:
        data = src[ext][off:off + size] if ext else b""
        out["%s-%s.%s" % (PREFIX, name, name)] = data.ljust(size, b"\0")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default="build/neo", help="the cart (tools/mkcart.py's output)")
    ap.add_argument("-o", "--out", default="build/standin/%s.zip" % SET)
    a = ap.parse_args(argv)
    files = roms(a.build)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    mkcart.write_zip(a.out, files)
    print("%s: %d bytes, set %s (%s)" % (a.out, os.path.getsize(a.out), SET,
                                         ", ".join("%s %#x" % (n, len(d)) for n, d in files.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
