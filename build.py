#!/usr/bin/env python3
"""Neo-Chorensha: build the Neo Geo port from your own copy of the game, in one command.

  python3 build.py --disk DISK --x68k-roms ROMS [--mame MAME] [-o OUT]

DISK   the Chourensha 68K v0.10 disk image: a zip holding the .dim, or the .dim
       (SHA1 of the .dim 9eae93138254a277f87039ade791f35301dced93)
ROMS   a folder or zip holding the X68000's iplrom.dat (MAME 0.289's x68000 ipl10, found by its
       SHA1 whatever its name) and cgrom.dat (786,432 bytes); nothing else is read
MAME   MAME 0.289 (default: $MAME, else mame on PATH): it plays the original to record its music,
       checked by SHA1 against the tested build's recordings
OUT    the folder written (default ./neo-chorensha): marukodq.zip, the ROM set for MAME (with
       neogeo.zip beside it), and neo-chorensha.neo for the MiSTer Neo Geo core

Also needed: Python 3.12 or later, and on PATH vasmm68k_mot and z80asm (the tested build's: vasm
2.0f with its Motorola syntax module 3.19f, z80asm 1.8). The Python packages requirements.txt pins
(exact versions) are installed into .venv here when missing. Every input is checked first and every
problem listed at once; build/ is then cleared (no file of an earlier run reaches the outputs) and
the steps of the tested build run in order; each output's SHA1 is checked against
data/outputs.json, and an output that differs is renamed NAME.mismatch (not the tested game). The
inputs are only read: an output path that is an input is refused, and so is an input inside build/.
No file in OUT is replaced but this patch's own earlier outputs: an OUT/marukodq.zip (marukodq is a
real MAME set: it may be yours) or OUT/neo-chorensha.neo that is not byte for byte the tested
build's is refused.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.dont_write_bytecode = True          # the release folder stays as written (the tools imported too)

OUTPUTS = ("marukodq.zip", "neo-chorensha.neo")
MISMATCH = ".mismatch"                 # an output that differs from the tested build's: NAME.mismatch
# what makes each file of the outputs (by the ROM set's member extension, c1 to c4 as "c"; the
# .neo's "neo"), for a mismatch's message: what to check
MADE_BY = {
    "p": "the 68000 program, assembled by vasmm68k_mot (tested: vasm 2.0f, Motorola syntax module "
         "3.19f; vasmm68k_mot -v shows yours), with the link of your program and the sound commands",
    "m": "the Z80 sound driver, assembled by z80asm (tested: 1.8; z80asm --version shows yours), "
         "with the sound tables made from the music recording",
    "v": "the music and effects, made from the music recording (checked) by the Python packages of "
         "requirements.txt",
    "s": "the text layer's graphics, made from your disk by the Python packages of requirements.txt",
    "c": "the sprites' graphics, made from your disk by the Python packages of requirements.txt",
    "neo": "the .neo, made of the ROM set's files: see those",
}
PACKAGES = {"capstone": "capstone", "unicorn": "unicorn", "numpy": "numpy", "pillow": "PIL"}
# the oldest Python the pinned packages install on (numpy 2.5.4's floor) and the build was run on
# end to end, its outputs byte for byte the tested build's
MIN_PYTHON = (3, 12)
VENV_GUARD = "NEO_CHORENSHA_VENV"
TAIL = 20                          # a failing step's last output lines shown


class InputError(Exception):
    """The inputs' problems, one per line."""


# --- the Python packages ------------------------------------------------------------------------

def _version(v):
    parts = []
    for p in v.split("."):
        digits = ""
        for c in p:
            if not c.isdigit():
                break
            digits += c
        parts.append(int(digits or 0))
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def meets(version, spec):
    """Does VERSION meet SPEC, requirements.txt's exact pin (==x)? Anything else is refused: the
    outputs are checked byte for byte, so the packages are the tested build's, no other."""
    spec = spec.strip()
    if not spec.startswith("==") or spec.startswith("==="):
        raise ValueError("requirements.txt: %r is not an exact pin (name==version)" % spec)
    return _version(version) == _version(spec[2:].strip())


def unmet():
    """requirements.txt's lines this Python does not meet, each with what it has."""
    from importlib import metadata
    bad = []
    with open(os.path.join(ROOT, "requirements.txt")) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            i = next((i for i, c in enumerate(line) if c in "=<>!~;"), len(line))
            name, spec = line[:i].strip(), line[i:]
            try:
                have = metadata.version(name)
            except metadata.PackageNotFoundError:
                bad.append("%s (not installed)" % line)
                continue
            if not meets(have, spec):
                bad.append("%s (found %s)" % (line, have))
    return bad


def _has_pip(py):
    try:
        return subprocess.run([py, "-m", "pip", "--version"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:                    # absent, or a link to a Python gone
        return False


def _run_or_stop(what, cmd):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        code, text = r.returncode, r.stdout
    except OSError as e:
        code, text = None, str(e)
    if code != 0:
        hint = ("\n(Debian, Ubuntu, WSL2: sudo apt install python3-venv)" if what.endswith("venv") else "")
        raise SystemExit("build.py: %s failed:\n%s%s" % (what, "\n".join(text.splitlines()[-TAIL:]), hint))


def ensure_packages():
    """Run under the pinned packages: when this Python lacks them, make .venv here, install
    requirements.txt into it and start again with its Python (same arguments)."""
    bad = unmet()
    if not bad:
        return
    if os.environ.get(VENV_GUARD):
        raise SystemExit("build.py: the Python packages are still not as requirements.txt pins them "
                         "after installing them into .venv: %s" % "; ".join(bad))
    venv = os.path.join(ROOT, ".venv")
    py = os.path.join(venv, "bin", "python")
    print("Python packages needed (%s): installing requirements.txt into %s" % ("; ".join(bad), venv))
    if not _has_pip(py):
        # none yet, or half made (python3-venv missing: a python without pip), or its python gone
        # (a Python upgrade): made again from this Python
        cmd = [sys.executable, "-m", "venv"] + (["--clear"] if os.path.lexists(venv) else []) + [venv]
        _run_or_stop("python3 -m venv", cmd)
        if not _has_pip(py):
            raise SystemExit("build.py: %s has no pip after python3 -m venv: install your system's venv "
                             "support (Debian, Ubuntu, WSL2: sudo apt install python3-venv) and run "
                             "build.py again" % venv)
    _run_or_stop("pip install", [py, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements.txt")])
    os.environ[VENV_GUARD] = "1"
    sys.stdout.flush()                  # execv drops what is still buffered
    os.execv(py, [py, "-I", os.path.abspath(__file__)] + sys.argv[1:])


# --- the inputs ---------------------------------------------------------------------------------

def _check_disk(disk):
    import import_disk
    try:
        dim = import_disk.read_dim(disk)
    except FileNotFoundError:
        return ["disk image %s: not found" % disk]
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        return ["disk image %s: %s" % (disk, e)]
    got = hashlib.sha1(dim).hexdigest()
    if got != import_disk.DIM_SHA1:
        return ["disk image %s: its .dim has SHA1 %s; Chourensha 68K v0.10's is %s"
                % (disk, got, import_disk.DIM_SHA1)]
    return []


def _find_mame(mame):
    """(MAME's absolute path or None, the name asked for): --mame, else $MAME, else mame on PATH."""
    mame = mame or os.environ.get("MAME") or "mame"
    if os.sep in mame:
        return os.path.abspath(mame), mame
    found = shutil.which(mame)
    return (os.path.abspath(found) if found else None), mame


def _writable(folder):
    """Can FOLDER be made (if absent) and written in? (the nearest folder that exists decides)"""
    while not os.path.exists(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            return False
        folder = parent
    return os.path.isdir(folder) and os.access(folder, os.W_OK | os.X_OK)


def _inside(path, folder):
    for p in {os.path.abspath(path), os.path.realpath(path)}:
        if p == folder or p.startswith(folder + os.sep):
            return True
    return False


def earlier_outputs(out, expected):
    """The files in OUT under the outputs' names that the build would replace and may not: anything
    but this patch's own earlier outputs (byte for byte the tested build's, EXPECTED: data/outputs.json).
    marukodq is a real MAME set: an OUT/marukodq.zip may be the user's own."""
    problems = []
    for name in OUTPUTS:
        path = os.path.join(out, name)
        if not os.path.lexists(path):
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            ours = False
        elif name == OUTPUTS[0]:
            try:
                with zipfile.ZipFile(path) as z:
                    ours = {n: _sha1(z.read(n)) for n in z.namelist()} == expected["marukodq"]
            except (OSError, zipfile.BadZipFile):
                ours = False
        else:
            with open(path, "rb") as f:
                ours = _sha1(f.read()) == expected["neo"]
        if not ours:
            problems.append("%s exists and is not this patch's output (byte for byte the tested build's)%s: "
                            "the build would replace it, and never replaces a file of yours: choose another "
                            "-o/--out or move that file" % (path, ", maybe your own MAME marukodq set"
                                                            if name == OUTPUTS[0] else ""))
    return problems


def check_inputs(disk, x68k_roms, mame, out, expected=None):
    """Check every input in one pass; the paths made absolute ({disk, x68k_roms, mame, mame_version,
    vasm, z80asm, out}); with EXPECTED (data/outputs.json), the files in OUT the build would replace
    too (earlier_outputs). InputError lists every problem."""
    import record_sound
    import x68k_roms as roms_tool
    disk, x68k_roms, out = (os.path.abspath(p) for p in (disk, x68k_roms, out))
    problems = _check_disk(disk)
    try:
        roms_tool.find_roms(x68k_roms)
    except roms_tool.RomError as e:
        problems += str(e).splitlines()
    found, mame_name = _find_mame(mame)
    inp = {"disk": disk, "x68k_roms": x68k_roms, "mame": found, "mame_version": None, "out": out}
    req = record_sound.REQUIRED_MAME
    if not inp["mame"]:
        problems.append("MAME: %s not found on PATH (--mame, $MAME or mame on PATH); MAME %s is required"
                        % (mame_name, req))
    else:
        try:
            inp["mame_version"] = record_sound.mame_version(inp["mame"])
            if inp["mame_version"] != req:
                problems.append("MAME %s is required (found %s, %s): the music is recorded against its "
                                "X68000 and checked against the tested build's"
                                % (req, inp["mame_version"], inp["mame"]))
        except record_sound.RecordError as e:
            problems.append("%s; MAME %s is required" % (e, req))
    for key, tool, what in (("vasm", "vasmm68k_mot", "vasm's 68000 assembler, Motorola syntax"),
                            ("z80asm", "z80asm", "z80asm 1.8")):
        inp[key] = shutil.which(tool)
        if not inp[key]:
            problems.append("%s: not found on PATH (%s)" % (tool, what))
    root = os.path.realpath(ROOT)
    build = os.path.join(root, "build")
    if os.path.exists(out) and not os.path.isdir(out):
        problems.append("output folder %s: a file, not a folder" % out)
    elif not _writable(out):
        problems.append("output folder %s: cannot be written" % out)
    if _inside(out, build):
        problems.append("output folder %s is inside %s, which the build clears first: choose another"
                        % (out, build))
    if os.path.islink(build) or (os.path.lexists(build) and not os.path.isdir(build)):
        problems.append("%s is %s: the build clears and remakes it; remove it"
                        % (build, "a link" if os.path.islink(build) else "not a folder"))
    if os.path.isdir(x68k_roms) and _inside(build, os.path.realpath(x68k_roms)):
        problems.append("the X68000 ROMs' folder %s holds this folder's build/, which the build clears "
                        "and writes: put iplrom.dat and cgrom.dat in a folder of their own (or a zip)"
                        % x68k_roms)
    inputs = [p for p in (disk, x68k_roms, inp["mame"]) if p and os.path.exists(p)]
    for name in OUTPUTS:
        o = os.path.join(out, name)
        for i in inputs:
            if os.path.exists(o) and os.path.samefile(o, i):
                problems.append("output %s is the input %s: choose another -o/--out or move the input"
                                % (o, i))
    for i in inputs:
        if _inside(i, build):
            problems.append("input %s is inside %s, which the build clears first: move it" % (i, build))
    if expected is not None and os.path.isdir(out):
        problems += earlier_outputs(out, expected)
    if problems:
        raise InputError("\n".join(problems))
    return inp


# --- the steps ----------------------------------------------------------------------------------

def _py(tool, *args):
    return [sys.executable, "-I", "-B", "tools/%s.py" % tool] + list(args)


def steps(inp):
    """The tested build's commands (the Makefile's), in order, to run from ROOT."""
    out = inp["out"]
    return [
        _py("import_disk", "--disk", inp["disk"], "--out", "build/orig"),
        _py("unplzx", "--x", "build/orig/disk/GAME/SZ2.X", "--out", "build/orig"),
        _py("inventory", "--orig", "build/orig", "--out", "build/orig/inventory.json",
            "--md", "build/orig/inventory.md"),
        _py("preinit", "--orig", "build/orig", "--out", "build/preinit"),
        _py("layout", "--orig", "build/orig", "--census", "data/census.json", "--preinit", "build/preinit",
            "--out", "build/link/layout.json", "--md", "build/link/layout.md"),
        _py("link", "--orig", "build/orig", "--preinit", "build/preinit", "--layout", "build/link/layout.json",
            "--out", "build/link"),
        _py("x68k_roms", "--bios", inp["x68k_roms"], "--out", "build/x68k/roms/x68000"),
        _py("record_sound", "--orig", "build/orig", "--out", "build/snd/rec", "--mame", inp["mame"],
            "--expect", "data/recordings.json"),
        _py("mksound", "--rec", "build/snd/rec", "--orig", "build/orig", "--preinit", "build/preinit",
            "--out", "build/snd"),
        _py("mkgfx", "--orig", "build/orig", "--preinit", "build/preinit", "--strip", "art/strips/strip.png",
            "--out", "build/gfx"),
        [inp["vasm"], "-Fbin", "-m68000", "-spaces", "-no-opt", "-quiet", "-Isrc/shim", "-Ibuild/link",
         "-Ibuild/gfx", "-Ibuild/snd", "-Idata", "-L", "build/neo/p1.lst", "-o", "build/neo/p1.bin",
         "src/shim/boot.asm"],
        [inp["z80asm"], "--includepath=build/snd", "--includepath=src/z80", "-o", "build/neo/m1.bin",
         "src/z80/sound.asm"],
        _py("mkcart", "--build", "build/neo", "--gfx", "build/gfx", "--vrom", "build/snd/vrom.bin"),
        _py("mkstandin", "--build", "build/neo", "-o", os.path.join(out, OUTPUTS[0])),
        _py("mkneo", "--build", "build/neo", "-o", os.path.join(out, OUTPUTS[1])),
    ]


def step_name(cmd):
    """A step's name: its tool (_py's tools/NAME.py), else its program's."""
    if cmd[0] == sys.executable:
        script = next((c for c in cmd[1:] if not c.startswith("-")), None)
        if script:
            return os.path.splitext(os.path.basename(script))[0]
    return os.path.basename(cmd[0])


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


# --- the outputs --------------------------------------------------------------------------------

def check_outputs(out, expected):
    """The members of OUT/marukodq.zip and the files of OUT that differ from EXPECTED
    (data/outputs.json), missing or extra ones included."""
    bad = []
    try:
        with zipfile.ZipFile(os.path.join(out, OUTPUTS[0])) as z:
            got = {n: _sha1(z.read(n)) for n in z.namelist()}
    except (OSError, zipfile.BadZipFile):
        bad.append(OUTPUTS[0])
    else:
        want = expected["marukodq"]
        bad += [n for n in sorted(set(want) | set(got)) if want.get(n) != got.get(n)]
    try:
        with open(os.path.join(out, OUTPUTS[1]), "rb") as f:
            if _sha1(f.read()) != expected["neo"]:
                bad.append(OUTPUTS[1])
    except OSError:
        bad.append(OUTPUTS[1])
    return bad


def made_by(name):
    """What makes the output file NAME (a member of the ROM set, or the .neo): MADE_BY's line."""
    if name == OUTPUTS[1]:
        return MADE_BY["neo"]
    ext = os.path.splitext(name)[1].lstrip(".").rstrip("0123456789")
    return MADE_BY.get(ext, "the ROM set (%s)" % OUTPUTS[0])


def set_aside(out, bad):
    """Rename the outputs BAD (check_outputs) holds a file of to NAME.mismatch, any earlier one
    replaced: no file that is not the tested game stays under an output's name. The new paths."""
    moved = []
    for name in OUTPUTS:
        hit = name in bad if name == OUTPUTS[1] else any(b != OUTPUTS[1] for b in bad)
        path = os.path.join(out, name)
        if hit and os.path.isfile(path):
            os.replace(path, path + MISMATCH)
            moved.append(path + MISMATCH)
    return moved


# --- the command --------------------------------------------------------------------------------

def run_steps(cmds):
    """Run CMDS from ROOT; on a failure, its name and last output lines on stderr: False."""
    for n, cmd in enumerate(cmds, 1):
        name = step_name(cmd)
        print("[%d/%d] %s" % (n, len(cmds), name), flush=True)
        try:
            r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors="replace")
            code, text = r.returncode, r.stdout
        except OSError as e:
            code, text = None, str(e)
        if code != 0:
            print("build.py: step %d/%d, %s, failed (exit %s):" % (n, len(cmds), name, code), file=sys.stderr)
            print("\n".join(text.splitlines()[-TAIL:]), file=sys.stderr)
            return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build.py", description=__doc__.splitlines()[0])
    ap.add_argument("--disk", required=True, help="Chourensha 68K v0.10's disk image: a zip holding the .dim, or the .dim")
    ap.add_argument("--x68k-roms", required=True, help="a folder or zip holding iplrom.dat and cgrom.dat")
    ap.add_argument("--mame", help="MAME 0.289 (default: $MAME, else mame on PATH)")
    ap.add_argument("-o", "--out", default="neo-chorensha", help="the folder written (default: %(default)s)")
    a = ap.parse_args(argv)
    if sys.version_info[:2] < MIN_PYTHON:
        raise SystemExit("build.py: Python %d.%d or later is needed (this is %s, %s): run it with a newer "
                         "python3" % (MIN_PYTHON + (sys.version.split()[0], sys.executable)))
    ensure_packages()
    problems = []
    try:
        with open(os.path.join(ROOT, "data", "outputs.json")) as f:
            expected = json.load(f)
    except (OSError, ValueError) as e:
        problems.append("data/outputs.json (the tested build's SHA1s): %s; this release is incomplete" % e)
    try:
        inp = check_inputs(a.disk, a.x68k_roms, a.mame, a.out, expected if not problems else None)
    except InputError as e:
        problems += str(e).splitlines()
    if problems:
        print("build.py: the inputs have problems:", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        return 2
    build = os.path.join(ROOT, "build")
    try:
        if os.path.lexists(build):
            shutil.rmtree(build)
        os.makedirs(os.path.join(build, "neo"))
        for name in OUTPUTS:            # an earlier run's set-aside outputs
            if os.path.isfile(os.path.join(inp["out"], name + MISMATCH)):
                os.remove(os.path.join(inp["out"], name + MISMATCH))
    except OSError as e:
        print("build.py: cannot clear %s (no file of an earlier run may reach the outputs): %s"
              % (build, e), file=sys.stderr)
        return 1
    if not run_steps(steps(inp)):
        moved = set_aside(inp["out"], check_outputs(inp["out"], expected))
        if moved:
            print("Set aside, not the tested game: %s" % ", ".join(moved), file=sys.stderr)
        return 1
    bad = check_outputs(inp["out"], expected)
    if bad:
        print("build.py: the outputs differ from the tested build's (data/outputs.json), so they are not "
              "the tested game:", file=sys.stderr)
        for name in bad:
            print("  %s: %s" % (name, made_by(name)), file=sys.stderr)
        moved = set_aside(inp["out"], bad)
        if moved:
            print("Set aside, not for play: %s" % ", ".join(moved), file=sys.stderr)
        print("With the tested tools (above), please open an issue on the repository with this message.",
              file=sys.stderr)
        return 1
    print("Done, both checked against the tested build:")
    for name in OUTPUTS:
        print("  " + os.path.join(inp["out"], name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
