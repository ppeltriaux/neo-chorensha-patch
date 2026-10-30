"""The user's own bytes, named by (size, SHA1) instead of by value.

The tools carry no byte of the original program or of the disk's other files: where they need a
run of them (a string they look for, an ID they copy), they name it by its length and SHA1 and
take it from the user's copy -- found by a window search (find) or read at a known offset and
checked (take).
"""
import hashlib


def find(data, n, sha1):
    """The lowest offset in `data` whose `n` bytes hash to `sha1`; ValueError if none."""
    data = bytes(data)
    for k in range(len(data) - n + 1):
        if hashlib.sha1(data[k:k + n]).hexdigest() == sha1:
            return k
    raise ValueError("no %d bytes with SHA1 %s" % (n, sha1))


def take(data, at, n, sha1, what):
    """The `n` bytes of `data` at `at`, checked against `sha1`; ValueError naming `what` (the
    file) otherwise."""
    b = bytes(data[at:at + n])
    got = hashlib.sha1(b).hexdigest()
    if len(b) != n or got != sha1:
        raise ValueError("%s: the %d bytes at offset %d have SHA1 %s, expected %s (not the "
                         "tested file)" % (what, n, at, got, sha1))
    return b
