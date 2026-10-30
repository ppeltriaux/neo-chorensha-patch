"""Run a Lua script inside MAME x68000 (headless) playing the original game.

usage: run.py SCRIPT.lua [--frames N] [--timeout S] [--env K=V ...] [--wav FILE]
--wav records MAME's sound output (-wavwrite: 48 kHz, 16-bit, one channel per speaker).
MAME is $MAME, else mame on PATH; its cfg/nv/snap folders (and its home path) are under $X68K_STATE
(default build/x68k). MAME runs on its built-in defaults, nothing of its user's setup: no ini file
(mame.ini, x68000.ini: -noreadconfig), no plugin, the sample rate given;
$X68K_RTC (YYYYMMDDhhmmss) sets the X68000's clock at the start (MAME -rtc) instead of the host's.
Exit 0 only if the script printed 'RESULT PASS'; 3 on timeout (process group killed); 2 without MAME;
1 otherwise.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build")
ROMS = os.path.join(BUILD, "x68k", "roms")
DIM = os.path.join(BUILD, "orig", "disk.dim")
SZ2 = os.path.join(BUILD, "orig", "sz2.bin")
SZ2_JSON = os.path.join(BUILD, "orig", "sz2.json")
MAME = os.environ.get("MAME") or shutil.which("mame")
# MAME's cfg, nvram and snapshot folders (X68K_STATE: tools/record_sound.py gives each recording a
# fresh one)
STATE = os.environ.get("X68K_STATE", os.path.join(BUILD, "x68k"))


def signature():
    """Hex of the first 64 bytes of the text; bytes of relocated longwords are '??'."""
    with open(SZ2, "rb") as f:
        head = bytearray(f.read(64))
    with open(SZ2_JSON) as f:
        relocs = json.load(f)["relocs"]
    masked = set()
    for r in relocs:
        for i in range(r, r + 4):
            if i < 64:
                masked.add(i)
    return "".join("??" if i in masked else "%02x" % b for i, b in enumerate(head))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--frames", type=int, default=4000)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--env", action="append", default=[])
    ap.add_argument("--wav")
    a = ap.parse_args(argv)
    if not MAME:
        print("run.py: MAME not found (set MAME or put mame on PATH)", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.update({
        "SDL_JOYSTICK_HIDAPI": "0", "SDL_JOYSTICK_MFI": "0", "SDL_JOYSTICK_IOKIT": "0",
        "SDL_VIDEO_DRIVER": "dummy", "SDL_VIDEODRIVER": "dummy",
        "SZ2_SIG": signature(), "X68K_DIR": HERE, "X68K_FRAMES": str(a.frames),
        "X68K_SNAP_DIR": os.path.join(STATE, "snap"),
    })
    for kv in a.env:
        k, _, v = kv.partition("=")
        env[k] = v
    dirs = {n: os.path.join(STATE, n) for n in ("cfg", "nv", "snap")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    backstop = max(60, a.frames // 20 + 60, a.timeout)
    cmd = [MAME, "x68000", "-bios", "ipl10", "-rompath", ROMS, "-flop1", DIM,
           "-video", "none", "-sound", "none", "-seconds_to_run", str(backstop),
           "-joystickprovider", "none", "-lightgunprovider", "none",
           "-mouseprovider", "none", "-keyboardprovider", "none",
           "-skip_gameinfo", "-nothrottle",
           "-noreadconfig", "-noplugins", "-samplerate", "48000", "-homepath", STATE,
           "-cfg_directory", dirs["cfg"], "-nvram_directory", dirs["nv"],
           "-snapshot_directory", dirs["snap"],
           "-autoboot_script", os.path.abspath(a.script)]
    if os.environ.get("X68K_RTC"):
        cmd += ["-rtc", os.environ["X68K_RTC"]]
    if a.wav:
        cmd += ["-wavwrite", os.path.abspath(a.wav)]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, start_new_session=True, cwd=ROOT)
    try:
        out, _ = p.communicate(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        sys.stdout.write(out or "")
        print("run.py: TIMEOUT after %ds" % a.timeout, file=sys.stderr)
        return 3
    sys.stdout.write(out)
    return 0 if "RESULT PASS" in out.splitlines() or any(l.strip() == "RESULT PASS" for l in out.splitlines()) else 1


if __name__ == "__main__":
    sys.exit(main())
