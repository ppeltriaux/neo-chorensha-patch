"""Assemble a MAME rompath for the x68000 driver from the user's X68000 ROMs (read at build time only).

  tools/x68k_roms.py --bios SRC --out build/x68k/roms/x68000

SRC is a folder (searched with its subfolders) or a zip (MAME's x68000.zip, say). Two files are
taken, nothing else: iplrom.dat, found by its SHA1 among the files of 131,072 bytes whatever their
name (MAME 0.289's x68000 -bios ipl10), and cgrom.dat, found by name in any case, then checked by
its size. MAME 0.289 boots x68000 -bios ipl10 with those two alone (it warns about the others).
The music is recorded against that ROM, so tools/record_sound.py names the same SHA1.
"""
import argparse
import hashlib
import os
import shutil
import sys
import zipfile

IPLROM_SHA1 = "0ed038ed2133b9f78c6e37256807424e0d927560"
IPLROM_SIZE = 131072
CGROM_SIZE = 786432


class RomError(Exception):
    pass


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _members(src):
    """(name, size, read) for every file in the folder SRC (and its subfolders) or the zip SRC."""
    if os.path.isdir(src):
        for top, dirs, names in os.walk(src):
            dirs.sort()
            for n in sorted(names):
                p = os.path.join(top, n)
                yield n, os.path.getsize(p), (lambda p=p: _read(p))
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            for i in z.infolist():
                if not i.is_dir():
                    yield os.path.basename(i.filename), i.file_size, (lambda i=i: z.read(i))
    elif not os.path.exists(src):
        raise RomError("%s: not found (the X68000 ROMs: iplrom.dat and cgrom.dat)" % src)
    else:
        raise RomError("%s: neither a folder nor a zip (the X68000 ROMs: iplrom.dat and cgrom.dat)" % src)


def find_roms(src):
    """{"iplrom.dat": bytes, "cgrom.dat": bytes} from SRC; RomError names each file missing or wrong."""
    found, ipl_named, cg_sizes = {}, False, []
    for name, size, read in _members(src):
        low = name.lower()
        if "iplrom.dat" not in found and size == IPLROM_SIZE:
            data = read()
            if hashlib.sha1(data).hexdigest() == IPLROM_SHA1:
                found["iplrom.dat"] = data
        ipl_named = ipl_named or low == "iplrom.dat"
        if low == "cgrom.dat" and "cgrom.dat" not in found:
            if size == CGROM_SIZE:
                found["cgrom.dat"] = read()
            else:
                cg_sizes.append(size)
    errors = []
    if "iplrom.dat" not in found:
        errors.append("iplrom.dat: %s in %s; it must be MAME 0.289's x68000 ipl10 (%d bytes, SHA1 %s)"
                      % ("no file with its SHA1" if ipl_named else "not found", src, IPLROM_SIZE, IPLROM_SHA1))
    if "cgrom.dat" not in found:
        errors.append("cgrom.dat: %s in %s; it must be %d bytes"
                      % ("%s bytes" % ", ".join(map(str, cg_sizes)) if cg_sizes else "not found", src, CGROM_SIZE))
    if errors:
        raise RomError("\n".join(errors))
    return found


def _within(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def build(src, out):
    """Clear OUT and write iplrom.dat and cgrom.dat there (found in SRC first: a wrong SRC leaves OUT).
    OUT may not be SRC, lie inside it or hold it: clearing it would delete the user's ROMs."""
    if _within(out, src) or _within(src, out):
        raise RomError("%s: the ROMs' folder %s is %s; it is emptied first, choose another"
                       % (src, out, "inside or the same as it" if _within(out, src) else "holding it"))
    roms = find_roms(src)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for n, data in roms.items():
        with open(os.path.join(out, n), "wb") as f:
            f.write(data)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bios", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        build(a.bios, a.out)
    except RomError as e:
        raise SystemExit("x68k_roms: %s" % e)


if __name__ == "__main__":
    main()
