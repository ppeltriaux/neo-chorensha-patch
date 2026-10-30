"""Read HAS object files (.o: Sharp and Hudson's X68000 format), as linked by HLK.

  .venv/bin/python -I tools/hunks.py build/orig/xsp/XSPlibC.o     # prints sections and symbols

The format is a stream of big-endian records, each led by a 16-bit tag whose high byte is the
record type and low byte its argument. Only the tags met in the XSP 1.99 objects are accepted;
anything else raises ValueError so a new tag is looked at before it is trusted:

  $0000                       end of object
  $D000 size.l name\\0[pad]    file header: total file size, source name (even-padded)
  $C0ss size.l name\\0[pad]    section definition: ss = 1 text, 2 data, 3 bss, 4 stack
  $B2ss value.l name\\0[pad]   symbol definition (xdef): value is an offset in section ss
  $20ss 0.l                   switch the output to section ss
  $10nn bytes[nn+1] [pad]     raw bytes (nn+1 of them, padded to an even length)
  $42ss value.l               32-bit absolute address of section ss + value (linker relocates)
  $3000 size.l                reserve size bytes (.ds) in the current section

The relocation tags listed in the XC manual for other cases ($40/$41/$43 byte/word forms, $46
external refs, $65/$6A PC-relative cross-section words) do not occur in XSPlibC.o/XSPlibA.o.
"""
import struct
import sys

SECTIONS = {1: "text", 2: "data", 3: "bss", 4: "stack"}


class ObjFile:
    """One object: `sections` name -> size, `symbols` name -> (section, offset), `text` bytes,
    `mask` (one byte per text byte: 1 = literal, 0 = filled in by the linker) and `fixups`
    [(text offset, size, target section, addend)]."""

    def __init__(self):
        self.name = ""
        self.sections = {}
        self.symbols = {}
        self.text = b""
        self.mask = b""
        self.fixups = []


def _cstr(d, p):
    e = d.index(b"\0", p)
    s = d[p:e].decode("latin-1")
    e += 1
    return s, e + (e & 1)


def read_object(data):
    o = ObjFile()
    text, mask = bytearray(), bytearray()
    sect, p = None, 0
    while True:
        if p + 2 > len(data):
            raise ValueError("object ends without an end record")
        (tag,) = struct.unpack_from(">H", data, p)
        hi, lo = tag >> 8, tag & 0xFF
        if tag == 0x0000:
            break
        if hi == 0xD0 and lo == 0:
            o.name, p = _cstr(data, p + 6)
        elif hi == 0xC0:
            (size,) = struct.unpack_from(">I", data, p + 2)
            name, p = _cstr(data, p + 6)
            if SECTIONS.get(lo) != name:
                raise ValueError(f"section {lo} named {name!r}")
            o.sections[name] = size
        elif hi == 0xB2:
            (val,) = struct.unpack_from(">I", data, p + 2)
            name, p = _cstr(data, p + 6)
            if lo not in SECTIONS:
                raise ValueError(f"symbol {name!r} in section {lo:#x}")
            o.symbols[name] = (SECTIONS[lo], val)
        elif hi == 0x20:
            if lo not in SECTIONS:
                raise ValueError(f"switch to section {lo:#x}")
            sect, p = lo, p + 6
        elif hi == 0x10:
            n = lo + 1
            if sect == 1:
                text += data[p + 2:p + 2 + n]
                mask += b"\1" * n
            elif sect != 2:
                raise ValueError(f"raw bytes in section {sect}")
            p += 2 + n + (n & 1)
        elif hi == 0x42:
            (val,) = struct.unpack_from(">I", data, p + 2)
            if lo not in SECTIONS:
                raise ValueError(f"reloc to section {lo:#x}")
            if sect == 1:
                o.fixups.append((len(text), 4, SECTIONS[lo], val))
                text += struct.pack(">I", val)
                mask += b"\0" * 4
            p += 6
        elif hi == 0x30 and lo == 0:
            (size,) = struct.unpack_from(">I", data, p + 2)
            if sect == 1:
                text += bytes(size)
                mask += b"\1" * size
            p += 6
        else:
            raise ValueError(f"unknown HAS record tag {tag:#06x} at {p:#x}")
    o.text, o.mask = bytes(text), bytes(mask)
    if "text" in o.sections and len(o.text) != o.sections["text"]:
        raise ValueError(f"text is {len(o.text):#x} bytes, header says {o.sections['text']:#x}")
    return o


def main(argv):
    for path in argv[1:]:
        with open(path, "rb") as f:
            o = read_object(f.read())
        print(path, o.name, {k: hex(v) for k, v in o.sections.items()}, f"{len(o.fixups)} fixups")
        for name, (sec, off) in sorted(o.symbols.items(), key=lambda kv: kv[1][1]):
            print(f"  {sec:5s} {off:6x} {name}")


if __name__ == "__main__":
    main(sys.argv)
