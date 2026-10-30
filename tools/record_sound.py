"""Record the original's three tunes and 25 effects from MAME x68000, with the loop points (Plan 4).

  .venv/bin/python -I tools/record_sound.py --orig build/orig --out build/snd/rec

Two MAME runs side by side (tests/x68k/run.py + rec_sound.lua, MAME's -wavwrite):
  tunes    CONFIG BGM PLAY: $17514 = the tune, A (MCDRV stop + play), one slot per tune
  effects  CONFIG PCM PLAY: $17512 = the cue, A (stop, 2 frames, se_play), one cue every 3 s
The menu sounds of the navigation end long before the first play (t0 is 90 frames after the last
Down), and no effect plays during the tunes (the run's MSM6258 writes are checked).

Writes, all derived from the user's dump (build/ only, never git):
  tune_11.wav, tune_12.wav, tune_21.wav  stereo 48 kHz int16 (channels 0-1 of MAME's 6-channel WAV:
      the stereo speaker; the other four are the floppy drives), from the MCDRV fn $02 (play) call,
      intro + 2 loop passes, the DC removed (see below)
  effects.wav   the 25 cues 3 s apart, the MSM6258's hold level removed
  meta.json     per tune play_s, intro_s, loop_s, tick_s (and how they were measured); per cue
                the sample its _ADPCMOUT call falls on in effects.wav
  tunes.log, effects.log  the runs' event logs (rec_sound.lua)

Loop points (recon §5): MCDRV's music tick is OPM Timer A (registers $10/$11, set at play). Every
key-on (OPM register $08 with a slot bit set) is logged; the loop length is the period at which the
key-ons repeat, searched around the tune's loop in ticks (TUNES, from the MDX files' loop labels:
the MDC the game plays loops at the same tick counts) and refined to the median spacing of the
repeated key-ons; the intro ends at the first key-on of the run that repeats to the end. Times are
emulated seconds from the play call; the WAV's sample n is emulated time n / 48000 (a tune's sound
starts 0.1 ms after its first key-on). In MAME 0.289 the loops come out at exactly their ticks x
the nominal tick (recon §5's loops were 3.3 ms short: loops2.py's matching tolerance).

Checks (the public patch): MAME must be 0.289 (mame -version). The recordings are the same bytes
from run to run only with the X68000's clock fixed (RTC) and an SRAM file present at the boot:
each run gets a fresh MAME state folder (cfg/nvram/snap: <out>/mame-state/<mode>) holding the SRAM a
first short run leaves (REC_MODE=boot). raw.json holds the SHA1 of the raw WAVs and logs;
with --expect (data/recordings.json: the tested build's recordings) they are checked before the
processing ("raw") and the files written after it ("files"), and a difference stops the build (a raw
one with the MAME builds tested, TESTED_MAME: no build the recordings were not checked on goes on).

DC: MAME's MSM6258 output holds its 10-bit floor (-512 x 16 x the 0.5 route = -4096) after the
first sample, and nothing writes the MSM6258 during the tunes, so the level is constant there:
each tune has its own mean taken out. In effects.wav the hold level, measured in the quiet before
the first cue, is taken out (each effect keeps its own drift: it starts from that floor).
"""
import argparse
import bisect
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from x68k_roms import IPLROM_SHA1  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN = os.path.join(ROOT, "tests", "x68k", "run.py")
LUA = os.path.join(ROOT, "tests", "x68k", "rec_sound.lua")
RATE = 48000
REQUIRED_MAME = "0.289"
# the MAME builds the recordings were checked on (data/recordings.json's raw SHA1s): MAME 0.289 built
# for another system may record the music slightly differently (its sound path is floating point)
TESTED_MAME = ("MAME 0.289 from Homebrew on macOS on Apple silicon and MAME 0.289 built with gcc 14 on "
               "Linux (Debian 13, arm64)")
# The X68000's clock at the runs' start (MAME -rtc, local time): MAME otherwise sets it from the
# host's clock, and the boot's timing, so the recordings' samples, follow it. The tested build's
# recordings were made at 2026-10-23 07:34:37 (found by trying each second around the files' dates).
RTC = "20261023073437"
OPM_HZ = 4_000_000

# tune -> (title, loop length in Timer A ticks, recording slot in seconds: intro + 2 loops + margin)
TUNES = {0x11: ("Sample2", 7680, 190), 0x12: ("Sample1", 6912, 150), 0x21: ("Boss1", 5856, 140)}
FX_GAP_S = 3
FIRST_ACTION_S = 1                      # after t0
T0_S = 45                               # boot + title + menu: t0 came at 42.95 s (frame 2529)
FRAME_BUDGET_HZ = 70                    # lib.lua's frame budget: MAME's frames come at up to ~69 Hz

PLAY_CALL = "15DE"                      # MCDRV trap #4 fn $02 in the bgm_play wrapper
ADPCMOUT_CALL = "3B3C"                  # se_play's IOCS _ADPCMOUT


class RecordError(Exception):
    pass


def mame_version(mame):
    """The first token of `mame -version` (0.289 (mame0289), 0.289 (unknown) from Homebrew)."""
    try:
        r = subprocess.run([mame, "-version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise RecordError("cannot run MAME %s: %s" % (mame, e))
    words = r.stdout.split()
    if r.returncode != 0 or not words:
        raise RecordError("cannot run MAME %s: -version gave %r (exit %d)" % (mame, r.stdout[:80], r.returncode))
    return words[0]


def mame_path(mame):
    """MAME as run.py can run it from ROOT: a path (./mame) made absolute; a bare name stays, for PATH."""
    if os.sep in mame or (os.altsep and os.altsep in mame):
        return os.path.abspath(mame)
    return mame


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(out, expect, group):
    """The names in expect[group] whose file in out is missing or has another SHA1."""
    return [n for n, sha in expect[group].items()
            if not os.path.isfile(os.path.join(out, n)) or sha1_file(os.path.join(out, n)) != sha]


def pcm_cues(game_dir):
    """SZ2_PCM.cnf's active lines -> {cue: file name on the disk} (the cnf's case may differ)."""
    pcm_dir = os.path.join(game_dir, "PCM_DAT")
    on_disk = {n.upper(): n for n in os.listdir(pcm_dir)}
    with open(os.path.join(pcm_dir, "SZ2_PCM.cnf"), "rb") as f:
        text = f.read().decode("shift_jis")
    cues = {}
    for line in text.splitlines():
        m = re.match(r"\s*PCM_No\.\$([0-9A-Fa-f]+)\s*:\s*FILE=\s*PCM_DAT[\\¥]([^\s,]+)", line)
        if m:
            cues[int(m.group(1), 16)] = on_disk[m.group(2).upper()]
    return dict(sorted(cues.items()))


def plan_tunes():
    t, items = FIRST_ACTION_S, []
    for num, (_, _, slot) in TUNES.items():
        items.append("%d:t%02X" % (t, num))
        t += slot
    return ",".join(items + ["%d:Q" % t]), t


def plan_effects(cues):
    items = ["%d:p%02X" % (FIRST_ACTION_S + FX_GAP_S * i, c) for i, c in enumerate(cues)]
    end = FIRST_ACTION_S + FX_GAP_S * len(cues)
    return ",".join(items + ["%d:Q" % end]), end


def state_dir(out, mode, nvram=None):
    """<out>/mame-state/<mode>, emptied; with nvram, the boot run's SRAM file copied in."""
    state = os.path.join(out, "mame-state", mode)
    shutil.rmtree(state, ignore_errors=True)
    os.makedirs(state)
    if nvram:
        shutil.copytree(nvram, os.path.join(state, "nv"))
    return state


def start_run(mode, plan, plan_s, out, mame, nvram=None):
    """Start one MAME run (tests/x68k/run.py) with a fresh state folder; returns (process, log, wav,
    console)."""
    log, wav, console = (os.path.join(out, mode + ext) for ext in (".log", ".raw.wav", ".mame.txt"))
    env = dict(os.environ, MAME=mame, X68K_STATE=state_dir(out, mode, nvram), X68K_RTC=RTC)
    frames = int((T0_S + plan_s + 10) * FRAME_BUDGET_HZ)
    cmd = [sys.executable, "-I", RUN, LUA, "--frames", str(frames), "--timeout", "1800",
           "--env", "REC_MODE=" + mode, "--env", "REC_LOG=" + log, "--env", "REC_PLAN=" + plan]
    if mode != "boot":
        cmd += ["--wav", wav]
    with open(console, "w") as f:
        return subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, env=env), log, wav, console


def boot_sram(out, mame):
    """The X68000's SRAM as its IPL leaves it (REC_MODE=boot: a run to the game's start). Without an
    SRAM file the IPL initialises it during the boot, which shifts the recordings' timing; the
    tested build's runs had one: the runs start from this file."""
    p, _, _, console = start_run("boot", "", 0, out, mame)
    nvram = os.path.join(out, "mame-state", "boot", "nv")
    if p.wait() != 0:
        with open(console) as f:
            sys.stderr.write("".join(f.readlines()[-5:]))
        raise RecordError("MAME's boot run failed (see %s)" % console)
    if not any(files for _, _, files in os.walk(nvram)):
        raise RecordError("MAME's boot run left no SRAM file in %s (see %s): the recordings need one"
                          % (nvram, console))
    return nvram


def parse_log(path):
    """rec_sound.lua's log -> {"call": [(t, off)], "opm": [(t, reg, val)], "msm": [t], "action": [(t, a)]}."""
    ev = collections.defaultdict(list)
    with open(path) as f:
        for line in f:
            p = line.split()
            t, kind = float(p[0]), p[1]
            if kind == "call":
                ev["call"].append((t, p[2]))
            elif kind == "opm":
                ev["opm"].append((t, int(p[2], 16), int(p[3], 16)))
            elif kind == "msm":
                ev["msm"].append(t)
            elif kind == "action":
                ev["action"].append((t, p[2]))
    return ev


def first_call(ev, off, after):
    calls = [t for t, o in ev["call"] if o == off and t >= after]
    if not calls:
        raise ValueError("no call at $%s after %.3f s" % (off, after))
    return calls[0]


def read_wav(path):
    """A 16-bit PCM WAV -> (rate, int16 array of shape (samples, channels))."""
    with wave.open(path) as w:
        assert w.getsampwidth() == 2, path
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return w.getframerate(), x.reshape(-1, w.getnchannels())


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.ascontiguousarray(x, dtype="<i2").tobytes())


def timer_a_tick(ev, play, keyons):
    """The OPM Timer A period (s) the tune runs at: NA = reg $10 << 2 | reg $11 & 3, as last written
    before its first key-on (MCDRV sets it at play); none may be written while its key-ons run."""
    first, last = keyons[0][0], keyons[-1][0]
    writes = [(t, r, v) for t, r, v in ev["opm"] if r in (0x10, 0x11) and play <= t <= last]
    hi = [v for t, r, v in writes if r == 0x10 and t < first]
    lo = [v & 3 for t, r, v in writes if r == 0x11 and t < first]
    if not hi or not lo or any(t > first for t, _, _ in writes):
        raise ValueError("Timer A not set once at play (%.3f s): %s" % (play, writes))
    na = hi[-1] << 2 | lo[-1]
    return na, 64 * (1024 - na) / OPM_HZ


def find_loop(keyons, end_s, loop_ticks, tick_s, window=0.05, tol=0.004, tight=0.001):
    """Key-ons [(t, value)] (s from the play call, up to end_s) -> (intro_s, loop_s, run_s).

    The period is searched in loop_ticks x tick_s +- window (0.5 ms steps) for the most key-ons
    that recur one period later (within tol), then refined to the median spacing of those pairs.
    The intro ends at the first key-on of the run that recurs (within tight) up to the last
    key-on that can; run_s is that run's length. Raises ValueError when the run is shorter than
    the period less a second (the key-ons do not repeat at it).
    """
    by = collections.defaultdict(list)
    for t, v in keyons:
        by[v].append(t)
    for times in by.values():
        times.sort()

    def partner(t, v, period, within):
        times = by[v]
        i = bisect.bisect_left(times, t + period - within)
        return times[i] if i < len(times) and abs(times[i] - (t + period)) <= within else None

    def testable(period):
        return [(t, v) for t, v in keyons if t + period < end_s - window]

    def score(period):
        return sum(partner(t, v, period, tol) is not None for t, v in testable(period))

    guess = loop_ticks * tick_s
    cands = [guess + d * 5e-4 for d in range(-round(window / 5e-4), round(window / 5e-4) + 1)]
    scores = [score(p) for p in cands]
    best = max(scores)
    coarse = float(np.mean([p for p, s in zip(cands, scores) if s == best]))
    spacing = [partner(t, v, coarse, tol) - t for t, v in testable(coarse) if partner(t, v, coarse, tol)]
    loop_s = float(np.median(spacing))
    ok = [(t, partner(t, v, loop_s, tight) is not None) for t, v in sorted(testable(loop_s))]
    k = len(ok)
    while k > 0 and ok[k - 1][1]:
        k -= 1
    if k == len(ok):
        raise ValueError("no key-on recurs %.4f s later" % loop_s)
    intro_s, run_s = ok[k][0], ok[-1][0] - ok[k][0]
    if run_s < loop_s - 1:
        raise ValueError("key-ons repeat at %.4f s only from %.3f to %.3f s" % (loop_s, intro_s, ok[-1][0]))
    return intro_s, loop_s, run_s


def quiet_level(x, a, b, what):
    """Per-channel median of x[a:b], which must be quiet (the hold level)."""
    seg = x[a:b].astype(np.float64)
    if np.ptp(seg, axis=0).max() > 64:
        raise ValueError("%s: not quiet (peak-to-peak %s)" % (what, np.ptp(seg, axis=0)))
    return np.median(seg, axis=0)


def to_int16(x):
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


def record_tunes(ev, wav, out):
    rate, raw = read_wav(wav)
    if rate != RATE or raw.shape[1] < 2:
        raise ValueError("%s: %d Hz, %d channels" % (wav, rate, raw.shape[1]))
    raw = raw[:, :2]
    plays = [first_call(ev, PLAY_CALL, t) for t, a in ev["action"] if a[0] == "t"]
    quit_s = [t for t, a in ev["action"] if a == "Q"][0]
    hold = quiet_level(raw, round((plays[0] - 0.5) * RATE), round((plays[0] - 0.05) * RATE),
                       "before the first tune")
    tunes = {}
    for i, num in enumerate(TUNES):
        name, loop_ticks, _ = TUNES[num]
        play, end = plays[i], (plays[i + 1] if i + 1 < len(plays) else quit_s)
        msm = [t for t in ev["msm"] if play <= t < end]
        if msm:
            raise ValueError("tune $%02X: the MSM6258 was written at %.3f s" % (num, msm[0]))
        keyons = [(t - play, v) for t, r, v in ev["opm"] if r == 0x08 and v & 0x78 and play <= t < end]
        na, tick_nominal = timer_a_tick(ev, play, [(t + play, v) for t, v in keyons])
        intro, loop, run = find_loop(keyons, end - play, loop_ticks, tick_nominal)
        tick = loop / loop_ticks
        if abs(tick / tick_nominal - 1) > 1e-3:
            raise ValueError("tune $%02X: tick %.6f s, Timer A says %.6f s" % (num, tick, tick_nominal))
        n = round(intro * RATE) + 2 * round(loop * RATE)     # the intro, then two whole loop passes
        a = round(play * RATE)
        if play + (n + 1) / RATE > end:
            raise ValueError("tune $%02X: intro + 2 loops do not fit its %.1f s slot" % (num, end - play))
        seg = raw[a:a + n].astype(np.float64)
        dc = seg.mean(axis=0)
        write_wav(os.path.join(out, "tune_%02X.wav" % num), to_int16(seg - dc))
        tunes["%02X" % num] = {
            "title": name, "file": "tune_%02X.wav" % num, "samples": n,
            "play_s": round(play, 6),
            "play_how": "emulated time of the MCDRV trap #4 fn $02 (play) at game offset $%s (a read tap "
                        "on its opcode, rec_sound.lua); the WAV starts at sample round(play_s x %d)"
                        % (PLAY_CALL, RATE),
            "intro_s": round(intro, 6), "loop_s": round(loop, 6), "tick_s": round(tick, 9),
            "timer_a": na, "tick_nominal_s": tick_nominal, "loop_ticks": loop_ticks,
            "intro_ticks": round(intro / tick, 2), "first_keyon_s": round(keyons[0][0], 6),
            "repeat_run_s": round(run, 3), "dc": [round(v, 1) for v in dc],
        }
    return tunes, [round(v, 1) for v in hold]


def record_effects(ev, wav, out, cues):
    rate, raw = read_wav(wav)
    if rate != RATE or raw.shape[1] < 2:
        raise ValueError("%s: %d Hz, %d channels" % (wav, rate, raw.shape[1]))
    raw = raw[:, :2]
    actions = [(t, a) for t, a in ev["action"] if a[0] == "p"]
    end = [t for t, a in ev["action"] if a == "Q"][0]
    if [int(a[1:], 16) for _, a in actions] != list(cues):
        raise ValueError("effects run played %s" % [a for _, a in actions])
    first = actions[0][0]
    hold = quiet_level(raw, round((first - 0.5) * RATE), round(first * RATE), "before the first cue")
    a = round((first - 0.5) * RATE)
    seg = raw[a:round(end * RATE)].astype(np.float64) - hold
    write_wav(os.path.join(out, "effects.wav"), to_int16(seg))
    meta = {}
    for i, (t, act) in enumerate(actions):
        nxt = actions[i + 1][0] if i + 1 < len(actions) else end
        calls = [u for u, o in ev["call"] if o == ADPCMOUT_CALL and t <= u < nxt]
        if len(calls) != 1:
            raise ValueError("cue %s: %d _ADPCMOUT calls" % (act, len(calls)))
        cue = int(act[1:], 16)
        meta["%02X" % cue] = {"file": cues[cue], "start": round(calls[0] * RATE) - a}
    return {"file": "effects.wav", "gap_s": FX_GAP_S, "start_s": round(first - 0.5, 6),
            "start_how": "the sample of the cue's IOCS _ADPCMOUT call at game offset $%s; "
                         "its sound follows about 0.4 ms later" % ADPCMOUT_CALL,
            "hold": [round(v, 1) for v in hold], "cues": meta}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--orig", default=os.path.join(ROOT, "build", "orig"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "snd", "rec"))
    ap.add_argument("--mame", default=os.environ.get("MAME") or shutil.which("mame"))
    ap.add_argument("--expect", help="the tested build's SHA1s (data/recordings.json)")
    a = ap.parse_args(argv)
    try:
        record(a)
    except RecordError as e:
        raise SystemExit("record_sound: %s" % e)


def record(a):
    if not a.mame:
        raise RecordError("MAME not found (--mame, $MAME or mame on PATH)")
    a.mame = mame_path(a.mame)
    found = mame_version(a.mame)
    if found != REQUIRED_MAME:
        raise RecordError("MAME %s is required (found %s, %s): the music is recorded against its X68000 "
                          "and checked against the tested build's" % (REQUIRED_MAME, found, a.mame))
    expect = None
    if a.expect:
        with open(a.expect) as f:
            expect = json.load(f)
    os.makedirs(a.out, exist_ok=True)
    cues = pcm_cues(os.path.join(a.orig, "disk", "GAME"))
    plans = {"tunes": plan_tunes(), "effects": plan_effects(cues)}
    nvram = boot_sram(a.out, a.mame)
    runs = {m: start_run(m, plan, plan_s, a.out, a.mame, nvram) for m, (plan, plan_s) in plans.items()}
    failed = []
    for mode, (p, log, wav, console) in runs.items():
        if p.wait() != 0:
            failed.append(mode)
            with open(console) as f:
                sys.stderr.write("".join(f.readlines()[-5:]))
    if failed:
        raise RecordError("MAME run(s) failed: %s (see %s/*.mame.txt)" % (failed, a.out))
    raw = {os.path.basename(p): sha1_file(p) for mode in runs for p in (runs[mode][2], runs[mode][1])}
    with open(os.path.join(a.out, "raw.json"), "w") as f:
        json.dump(raw, f, indent=1, sort_keys=True)
    bad = check(a.out, expect, "raw") if expect else []
    if bad:
        raise RecordError(
            "MAME's x68000 recorded the original's music differently from the tested build (%s). The "
            "build was tested with %s and iplrom.dat SHA1 %s. MAME builds for other systems may record "
            "the music slightly differently; the build then cannot guarantee the tested game, so it "
            "stops here. Please open an issue on the repository with this message."
            % (", ".join("%s SHA1 %s" % (n, raw.get(n, "(none)")) for n in bad), TESTED_MAME, IPLROM_SHA1))
    tunes, hold = record_tunes(parse_log(runs["tunes"][1]), runs["tunes"][2], a.out)
    effects = record_effects(parse_log(runs["effects"][1]), runs["effects"][2], a.out, cues)
    meta = {"rate": RATE, "source": "MAME x68000 -wavwrite, channels 0-1 (tools/record_sound.py)",
            "tunes": tunes, "tunes_hold": hold, "effects": effects}
    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    for mode in runs:
        os.remove(runs[mode][2])          # the 6-channel WAVs: hundreds of MB, all kept above
    if expect:
        bad = check(a.out, expect, "files")
        if bad:
            raise RecordError("the music recorded matches but its processing differs (%s): use the "
                              "Python packages of requirements.txt" % ", ".join(bad))
    for num, t in tunes.items():
        print("tune $%s %-8s play %.3f s  intro %.3f s  loop %.3f s  tick %.4f ms" % (
            num, t["title"], t["play_s"], t["intro_s"], t["loop_s"], t["tick_s"] * 1e3))
    print("effects: %d cues in effects.wav" % len(effects["cues"]))


if __name__ == "__main__":
    main()
