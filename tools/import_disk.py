"""Import the user's Chorensha disk image into build/orig (never committed).

  .venv/bin/python -I tools/import_disk.py --disk PATH --out build/orig
PATH is a zip holding one .dim, or the .dim itself (--zip: the same option, the Makefile's name).
Exit code 2 if the disk image SHA1 is not the expected one.
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dimfs  # noqa: E402
import lzh  # noqa: E402

DIM_SHA1 = "9eae93138254a277f87039ade791f35301dced93"
XSP_ARCHIVE = "TOOL/XSP199.LZH"


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def write_tree(root, entries, files):
    for e in entries:
        dest = os.path.join(root, e.path)
        if e.is_dir:
            os.makedirs(dest, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(e.data)
            files[os.path.relpath(dest, os.path.dirname(root))] = sha1(e.data)


def read_dim(path):
    """The disk image's bytes: the one .dim of the zip PATH, or the file PATH itself (ValueError when
    the zip holds no .dim or several; OSError when PATH cannot be read)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".dim")]
            if len(names) != 1:
                raise ValueError("expected exactly one .dim in the zip, found %r" % names)
            return z.read(names[0])
    with open(path, "rb") as f:
        return f.read()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--disk", "--zip", dest="disk", required=True, help="a zip holding the .dim, or the .dim")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        dim = read_dim(a.disk)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print("%s: %s" % (a.disk, e), file=sys.stderr)
        return 2
    got = sha1(dim)
    if got != DIM_SHA1:
        print("disk image SHA1 mismatch: found %s, expected %s" % (got, DIM_SHA1), file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "disk.dim"), "wb") as f:
        f.write(dim)
    entries = dimfs.read_dim(dim)
    files = {}
    write_tree(os.path.join(a.out, "disk"), entries, files)
    xsp = next(e for e in entries if e.path == XSP_ARCHIVE)
    write_tree(os.path.join(a.out, "xsp"), lzh.read_lzh(xsp.data), files)
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump({"dim_sha1": got, "files": dict(sorted(files.items()))}, f, indent=1, ensure_ascii=False)
    print("imported %d files into %s" % (len(files), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
