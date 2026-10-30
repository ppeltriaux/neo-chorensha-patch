#!/usr/bin/env python3
"""Build the sound data (Plan 4 Task 3): the 4 MB V-ROM, the Z80 driver's tables and the 68k's
equates, from make sound-rec's recordings and the disk's effects.

  .venv/bin/python -I tools/mksound.py --rec build/snd/rec --orig build/orig \\
      --preinit build/preinit --out build/snd                                   (make cart)

Writes to --out, all derived from the user's dump (build/ only, never git):
  vrom.bin      4 MB: the 25 effects (ADPCM-A, 18,518.5 Hz) from 0, none crossing a 1 MB boundary,
                then the three tunes (ADPCM-B, about 22 kHz), each tune's intro then its loop,
                contiguous; zeros after
  sound.inc     z80asm: the command bytes, TIMER_B_VALUE, the driver's output levels, sfx_table,
                music_table, fade_ticks (written last: it stands for all of them)
  sound68k.inc  vasm: the same command bytes (SND_CMD_*), the fade speeds, SND_FX_INDEX (cue ->
                effect index, $FF = no sample) and SND_FX_FRAMES (effect index -> the game steps
                the original's _ADPCMSNS answers busy after it starts: fx_frames). Holds tables:
                include it where data may sit (as gfx.inc)
  sound.json    what was built and why (rows, rates, gain, levels) for the tests and Plan 4's checks
The values that need the P-ROM layout (SND_TUNE_PTR_0..2, SND_CUE_TABLE) are tools/link.py's, in
build/link/game.inc; it takes TUNES, TUNE_TABLE and CUE_TABLE from here.

Effects. The cue table at $1EBA4 (preinit snapshot: 16 B x $80, +0 STAT, +2 length, +6 pointer,
+A PR) names the 25 cues that have a sample, checked against SZ2_PCM.cnf and the files' sizes.
Effect index i is the i-th of them by cue number. Each file is decoded as the X68000 plays it
(tools/msm6258.py: from the floor the chip idles at, 15,625 Hz) and put at MAME's level beside the
music (x 0.5, the MSM6258's route). Its silence is that floor, so the floor is taken out (the effect
starts at 0, as effects.wav), then the DC high-pass (below), and the last FX_TAPER_S fall to 0 so the
stop leaves no step. Resampled to 18,518.5 Hz between zero pads (the first and last samples are 0).

Tunes. tune_<nn>.wav (48 kHz stereo, from the play call, intro + 2 loops) folded to mono (the chip
plays one channel to both sides), its silence before the first key-on taken as zero, the DC
high-pass. The loop is k whole 512-sample blocks: rate r = k x 512 / loop_s, k = round(loop_s x
22,000 / 512), with loop_s meta.json's measured ticks x tick. The loop is one pass of the recording
from t, y[t:t + loop], all recorded (the passes are not sample-identical: MAME's OPM state runs on,
so a loop pieced from two passes would carry a seam of its own). Its one seam is the repeat, and the
ADPCM-B repeat restarts the decoder (ymfm load_start: accumulator 0, minimum step), so the loop is
encoded from that state and t is the quietest point of the 512 samples after the intro's end
(loop_start): the restart then costs no click, and the intro (whole blocks too) gives up d < 512
samples of the silence before the first key-on to end there. The intro ends where the loop starts
in the music, contiguous in the V-ROM, and its last 1-2 ms (LANDINGS) ease to silence so that its
encoding ends in that same start state (land_intro: the minimum step, |accumulator| <= 15): the chip
may run on from the intro into the loop or restart at the loop's start, and the loop decodes the
same either way (to within 15 of 32,768). intro_ticks = the intro's length in Z80 Timer B ticks.

Levels: one gain for all. In MAME x68000 the effects (0.5 x decode) mix beside the OPM music at the
levels recorded; the Neo Geo must keep that ratio. ymfm's YM2610 outputs, per decoded sample unit,
ADPCM-A at total level T and channel level L: mul / 2^(5 + vol >> 3), vol = (L & $1F ^ $1F) +
(T ^ $3F), mul = 15 - (vol & 7) (adpcm_a_out); ADPCM-B at level V: V / 512 (V >> 8, then the
YM2610's >> 1; adpcm_b_out). At the driver's levels (ADPCMA_TOTAL $3F, ADPCMA_LEVEL $DF,
ADPCMB_LEVEL $EA, as neo-r-type) that is 15/32 and 234/512, so the effects are encoded at FX_SCALE
= (234/512) / (15/32) = 0.975 of the music's gain. The gain puts the loudest of all (the music, and
the effects x FX_SCALE) at PEAK = 30,000. Measured in MAME 0.289 (this V-ROM in the cart, the
YM2610 driven at these levels): ADPCM-A / ADPCM-B = -0.07 dB, against +0.22 dB from the formulas
(ADPCM-A's held samples lose a little treble).

DC: a one-pole high-pass at HP_HZ from a zero state, on signals that start at their silence: they
start at 0 and their DC goes, so the chip's 0 before a start and after a stop meets them without a
step, and the loop (taken long after the start) is periodic.
"""
import argparse
import json
import math
import os
import struct
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adpcm  # noqa: E402
import msm6258  # noqa: E402

# --- the one table of the sound interface (sound.inc and sound68k.inc are written from it) -----
# (name, byte, meaning); the 68k writes them to REG_SOUND, the Z80 echoes cmd | ECHO
COMMANDS = (
    ("MUSIC_STOP", 0x04, "stop the music"),
    ("FX_STOP", 0x05, "stop the effect"),
    ("FADE", 0x08, "+ s: fade the music out at FADE_SPEEDS[s], then stop it"),
    ("PLAY", 0x10, "+ t: play tune t (TUNES[t]) from its intro"),
    ("FX", 0x40, "+ i: play effect i (stops the one playing)"),
    ("ECHO", 0x80, "the Z80's reply: the command | ECHO"),
)
FADE_SPEEDS = (0x0C, 0x10, 0x18)      # MCDRV fn $14 speeds the game uses; others -> the nearest
TUNES = ((0x11, "Sample2"), (0x12, "Sample1"), (0x21, "Boss1"))   # (MCDRV tune entry, title)
CUE_TABLE, CUE_SIZE, CUE_COUNT = 0x1EBA4, 16, 0x80     # original base-0 addresses (recon §2)
TUNE_TABLE, TUNE_SIZE, TUNE_COUNT = 0x1F3A4, 8, 64
STAT_15625 = 0x403                     # IOCS _ADPCMOUT d1: 15,625 Hz, both sides
# The original's game frame (MAME x68000, SCREEN 0: the start-up's CRTC mode 8, the one normal play
# uses): screen frame_period 13.523811 ms = 73.944 Hz; MAME's screen.refresh still reads the driver's
# nominal 55.8625. Checked against the OPM: 1,000 steps of stage 1 took 1,591 Timer A ticks of
# 8.496 ms (docs/notes/shim.md, "Sound": the busy model)
ORIG_FRAME_S = 0.013523811468012
# _ADPCMSNS answers busy until about 4 ms after a sample's length (the original's own answers,
# logged by tests/lockstep/record_x68k.lua over the four lock-step scenarios: 1.5-4.5 ms past it,
# with about 1 ms of jitter); in frames, the best fit per record: 0.22-0.40 on Task 6's calibration
# records, 0.30-0.40 on its final ones (tools/busycal.py; what is asserted is that at this tail
# every disagreement lies at a boundary, within the cap: test_busy_tail_in_range)
BUSY_TAIL_FRAMES = 0.3

# --- the chips -------------------------------------------------------------------------------
TIMER_B_VALUE = 198                    # the driver's Timer B (neo-r-type's), about 59.9 Hz
Z80_TICK_HZ = adpcm.YM_CLOCK / (2304 * (256 - TIMER_B_VALUE))   # Timer B: 16 FM samples x 144
ADPCMA_TOTAL, ADPCMA_LEVEL, ADPCMB_LEVEL = 0x3F, 0xDF, 0xEA     # the driver's output levels
RATE_B_NOMINAL = 22000
BLOCK = 512                            # samples in a 256-byte block
MSM_RATE = 15625                       # the MSM6258 at 8 MHz / 512 (STAT $403)
MSM_FLOOR = msm6258.SIGNAL_MIN * 16    # where the X68000's MSM6258 idles: an effect's silence
MSM_MIX = 0.5                          # MAME x68000 mixes the MSM6258 at 0.5 beside the OPM
REC_RATE = 48000

# --- processing ------------------------------------------------------------------------------
PEAK = 30000
HP_HZ = 10
FX_TAPER_S = 0.003
LOOP_SCORE_SPAN = 4                    # samples at the loop's start the restart must reach
RESAMPLE_EDGE = 33                     # samples at a resampled end the sinc saw only partly
# the intro's landing (samples at the tune's rate), shortest first: (fade, silence after it)
LANDINGS = [(f, h) for h in (8, 12, 16, 24, 32, 48, 64, 96, 128) for f in (16, 24, 32, 48, 64)
            if h <= f]
LAND_SCORE = 32                        # the landing window loop_start keeps quiet


def adpcm_a_out(total, channel):
    """YM2610 ADPCM-A output per decoded unit (adpcm.decode_a's acc x 16) at these levels (ymfm)."""
    vol = ((channel & 0x1F) ^ 0x1F) + (total ^ 0x3F)
    if vol >= 63:
        return 0
    return (15 - (vol & 7)) / 2 ** (5 + (vol >> 3))


def adpcm_b_out(level):
    """YM2610 ADPCM-B output per decoded unit at this level (ymfm: x level >> 8, then >> 1)."""
    return level / 512


FX_SCALE = adpcm_b_out(ADPCMB_LEVEL) / adpcm_a_out(ADPCMA_TOTAL, ADPCMA_LEVEL)


def command_bytes(n_fx, n_tunes):
    """Every byte the 68k may send."""
    c = {n: v for n, v, _ in COMMANDS}
    return ([c["MUSIC_STOP"], c["FX_STOP"]] + [c["FADE"] + s for s in range(len(FADE_SPEEDS))]
            + [c["PLAY"] + t for t in range(n_tunes)] + [c["FX"] + i for i in range(n_fx)])


def fade_ticks(tick_s):
    """MCDRV's fade (64 x speed music ticks) in Timer B ticks, per FADE_SPEEDS."""
    return [round(64 * s * tick_s * Z80_TICK_HZ) for s in FADE_SPEEDS]


def fx_index(fx_cues):
    """Cue (0-$7F) -> effect index, $FF = no sample."""
    t = [0xFF] * CUE_COUNT
    for i, c in enumerate(fx_cues):
        t[c] = i
    return t


def fx_frames(length):
    """Game steps the original's _ADPCMSNS answers busy after an _ADPCMOUT of `length` bytes
    (busy while fewer have passed): ceil(length x 2 / 15625 s, in the original's frames, + the
    tail). The shim's busy model counts them (SND_FX_FRAMES)."""
    return math.ceil(length * 2 / MSM_RATE / ORIG_FRAME_S + BUSY_TAIL_FRAMES)


def loop_rate(loop_s, nominal=RATE_B_NOMINAL):
    """(k, rate): the loop is k whole 512-sample blocks at rate, about nominal."""
    k = max(1, round(loop_s * nominal / BLOCK))
    return k, k * BLOCK / loop_s


def highpass(x, fs, hz=HP_HZ):
    """One-pole DC blocker y[n] = x[n] - x[n-1] + R y[n-1] from a zero state."""
    r = math.exp(-2 * math.pi * hz / fs)
    out, px, py = [], 0.0, 0.0
    for v in np.asarray(x, dtype=np.float64).tolist():
        py = v - px + r * py
        px = v
        out.append(py)
    return np.array(out)


def fx_pcm(data, gain):
    """One MSM6258 file -> PCM at RATE_A for encode_a: decoded from the idle floor, at MAME's level
    beside the music, the floor (its silence) as 0, the DC high-pass, a taper to 0 at the end, the
    gain; resampled between zero pads, so it starts and ends at 0."""
    e = MSM_MIX * (msm6258.decode(data).astype(np.float64) - MSM_FLOOR)
    e = highpass(e, MSM_RATE)
    n = min(len(e), max(1, round(FX_TAPER_S * MSM_RATE)))
    e[len(e) - n:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(1, n + 1) / n)
    pad = np.zeros(math.ceil(32 * MSM_RATE / adpcm.RATE_A) + 1)   # the resampler's half-window
    return adpcm.resample(np.concatenate([pad, e * gain, pad]), MSM_RATE, adpcm.RATE_A)


def fx_level(data):
    """An effect's processed peak at gain 1 (before resampling)."""
    e = MSM_MIX * (msm6258.decode(data).astype(np.float64) - MSM_FLOOR)
    return float(np.abs(highpass(e, MSM_RATE)).max())


def read_wav(path):
    with wave.open(path) as w:
        if w.getframerate() != REC_RATE or w.getsampwidth() != 2 or w.getnchannels() != 2:
            raise ValueError("%s: expected 16-bit stereo %d Hz" % (path, REC_RATE))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return x.reshape(-1, 2).astype(np.float64)


def tune_pcm(stereo, first_keyon_s):
    """A tune's recording -> mono at 48 kHz, the silence before its first key-on as 0, the DC
    high-pass."""
    m = stereo.mean(axis=1)
    quiet = int(first_keyon_s * REC_RATE) - REC_RATE // 1000
    if quiet < REC_RATE // 1000:
        raise ValueError("no silence before the first key-on")
    return highpass(m - np.median(m[:quiet]), REC_RATE)


def loop_start(y, intro, period, dmax, land=LAND_SCORE):
    """(d, t): the loop starts at sample t (y's rate) and the intro is y[d:t], whole blocks.
    The loop is y[t:t + period]. t is searched over the block after the intro's end (intro, in
    samples) for the quietest seams: twice the restart's (the loop's last sample, which the
    restart cuts to 0, and its first LOOP_SCORE_SPAN, which the decoder climbs to from 0: their
    peak; it comes at every repeat) plus the landing's (the intro's last `land` samples: their
    mean; once per play); d = t mod 512 must leave the music (d <= dmax)."""
    t0 = math.ceil(intro)
    best = None
    for t in range(t0, t0 + BLOCK):
        d = t % BLOCK
        if d > dmax:
            continue
        restart = max(abs(y[t + period - 1]), np.abs(y[t:t + LOOP_SCORE_SPAN]).max())
        score = 2 * restart + np.abs(y[t - land:t]).mean()
        if best is None or score < best[0]:
            best = (score, d, t)
    return best[1], best[2]


def b_end_state(data):
    """ADPCM-B decoder state (accumulator, step) after `data`, from the chip's start state."""
    acc, step = 0, adpcm.B_STEP_MIN
    for n in adpcm._bytes_to_nibbles(data):
        d = (2 * (n & 7) + 1) * step // 8
        acc = max(-32768, min(32767, acc + (-d if n & 8 else d)))
        step = max(adpcm.B_STEP_MIN, min(adpcm.B_STEP_MAX, step * adpcm.B_SCALE[n & 7] // 64))
    return acc, step


def land_intro(intro, rate):
    """(bytes, delta_n, (fade, hold)): the intro encoded so that it ends in the decoder's start
    state: its last `fade` samples before `hold` samples of silence ease out, the shortest of
    LANDINGS after which the encoding ends on the minimum step within one smallest step (15) of 0."""
    n = len(intro)
    longest = max(f + h for f, h in LANDINGS)
    for fade, hold in sorted(LANDINGS, key=lambda fh: (fh[0] + fh[1], fh[1])):
        z = np.array(intro, dtype=np.float64)
        z[n - hold - fade:n - hold] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(1, fade + 1) / fade)
        z[n - hold:] = 0
        data, dn = adpcm.encode_b(z, rate)
        acc, step = b_end_state(data)
        if step == adpcm.B_STEP_MIN and abs(acc) <= adpcm.B_STEP_MIN // 8:
            return data, dn, (fade, hold)
    raise ValueError("the intro does not land in %d samples" % longest)


def read_tables(mem):
    """(cues, tunes) from the preinit memory: {cue: (stat, length, pointer, pr)} for the cues with a
    sample, {entry: (pointer, size)} for the tunes."""
    cues = {}
    for c in range(CUE_COUNT):
        stat, length, ptr, pr = struct.unpack_from(">HIIH", mem, CUE_TABLE + CUE_SIZE * c)
        if length:
            cues[c] = (stat, length, ptr, pr)
    tunes = {}
    for e in range(TUNE_COUNT):
        ptr, size = struct.unpack_from(">II", mem, TUNE_TABLE + TUNE_SIZE * e)
        if size:
            tunes[e] = (ptr, size)
    return cues, tunes


def build(rec_dir, game_dir, mem):
    import record_sound
    with open(os.path.join(rec_dir, "meta.json")) as f:
        meta = json.load(f)
    cues, tunes = read_tables(mem)
    if sorted(tunes) != [e for e, _ in TUNES]:
        raise ValueError("tune table entries %s, expected %s" % (
            [hex(e) for e in sorted(tunes)], [hex(e) for e, _ in TUNES]))
    cnf = record_sound.pcm_cues(game_dir)
    if sorted(cnf) != sorted(cues):
        raise ValueError("SZ2_PCM.cnf's cues and the cue table's differ")
    fx = []
    for c in sorted(cues):
        stat, length, _, pr = cues[c]
        with open(os.path.join(game_dir, "PCM_DAT", cnf[c]), "rb") as f:
            data = f.read()
        if stat != STAT_15625 or length != len(data):
            raise ValueError("cue $%02X: STAT $%X, length %d, file %d bytes" % (
                c, stat, length, len(data)))
        fx.append({"cue": c, "file": cnf[c], "pr": pr, "data": data})

    mus = []
    for entry, title in TUNES:
        m = meta["tunes"]["%02X" % entry]
        pcm = tune_pcm(read_wav(os.path.join(rec_dir, m["file"])), m["first_keyon_s"])
        mus.append({"entry": entry, "title": title, "meta": m, "pcm": pcm})

    peak_music = max(float(np.abs(t["pcm"]).max()) for t in mus)
    peak_fx = max(fx_level(e["data"]) for e in fx)
    gain = PEAK / max(peak_music, peak_fx * FX_SCALE)

    vrom = adpcm.VRom()
    peak_enc = 0.0
    for i, e in enumerate(fx):
        y = fx_pcm(e["data"], gain * FX_SCALE)
        peak_enc = max(peak_enc, float(np.abs(y).max()))
        e["start"], e["end"] = vrom.add_a("fx%d" % i, adpcm.encode_a(y))
        e["samples"] = len(y)
    for t in mus:
        m = t["meta"]
        k, r = loop_rate(m["loop_s"])
        y = adpcm.resample(t["pcm"] * gain, REC_RATE, r)
        period = k * BLOCK
        d, at = loop_start(y, m["intro_s"] * r, period, int(m["first_keyon_s"] * r) - 8)
        if at + period + RESAMPLE_EDGE > len(y):
            raise ValueError("%s: the recording ends inside the loop" % t["title"])
        intro, loop = y[d:at], y[at:at + period]
        peak_enc = max(peak_enc, float(np.abs(intro).max()), float(np.abs(loop).max()))
        enc_i, dn, landing = land_intro(intro, r)
        enc_l, _ = adpcm.encode_b(loop, r)
        if len(enc_i) % 256 or len(enc_l) != k * 256:
            raise ValueError("%s: intro/loop not whole blocks" % t["title"])
        t.update(rate=r, blocks=k, delta_n=dn, trim=d, loop_at=at, landing=landing,
                 intro=vrom.add_b("intro%02X" % t["entry"], enc_i),
                 loop=vrom.add_b("loop%02X" % t["entry"], enc_l),
                 intro_ticks=round(len(intro) / r * Z80_TICK_HZ),
                 fade_ticks=fade_ticks(m["tick_s"]))
    if peak_enc >= 32768:
        raise ValueError("encoded peak %.0f: lower PEAK" % peak_enc)
    return {"vrom": vrom.image(), "vrom_used": len(vrom.data), "fx": fx, "tunes": mus,
            "gain": gain, "peak_music": peak_music, "peak_fx": peak_fx, "peak_encoded": peak_enc,
            "fx_index": fx_index([e["cue"] for e in fx]),
            "fx_frames": [fx_frames(len(e["data"])) for e in fx]}


# ------------------------------------------------------------------------------------ output

HEADER = "generated by tools/mksound.py from the original's dump - do not edit or commit (build/ only)"


def render_z80(res):
    L = ["; " + HEADER, "; the Z80 driver's sound data (z80asm); the 68k's side is sound68k.inc", "",
         "; commands (68k -> Z80 on port $00; the reply on port $0C is the command | CMD_ECHO)"]
    for name, v, what in COMMANDS:
        L.append("%-20s equ $%02X        ; %s" % ("CMD_" + name + ":", v, what))
    L += ["", "; Timer B: Z80_TICK_HZ = %d / (2304 x (256 - TIMER_B_VALUE)) = %.9f Hz" % (
        adpcm.YM_CLOCK, Z80_TICK_HZ),
          "%-20s equ %d" % ("TIMER_B_VALUE:", TIMER_B_VALUE),
          "%-20s equ %d        ; Z80_TICK_HZ x 1000, rounded" % (
              "Z80_TICK_MILLIHZ:", round(Z80_TICK_HZ * 1000)),
          "", "; output levels the gain was derived for (tools/mksound.py: keep them)",
          "%-20s equ $%02X        ; ADPCM-A total level" % ("ADPCMA_TOTAL:", ADPCMA_TOTAL),
          "%-20s equ $%02X        ; ADPCM-A channel: both sides, level $1F" % (
              "ADPCMA_LEVEL:", ADPCMA_LEVEL),
          "%-20s equ $%02X        ; ADPCM-B level" % ("ADPCMB_LEVEL:", ADPCMB_LEVEL),
          "", "%-20s equ %d" % ("SFX_COUNT:", len(res["fx"])),
          "%-20s equ %d" % ("MUSIC_COUNT:", len(res["tunes"])),
          "%-20s equ %d" % ("FADE_SPEEDS:", len(FADE_SPEEDS)),
          "%-20s equ 4          ; bytes per sfx_table row" % "SFX_ROW:",
          "%-20s equ 12         ; bytes per music_table row" % "MUSIC_ROW:",
          "%-20s equ %d          ; bytes per fade_ticks row" % ("FADE_ROW:", 2 * len(FADE_SPEEDS)),
          "", "; effects (ADPCM-A, 18,518.5 Hz) by effect index: start, end (256-byte units, end",
          "; inclusive)",
          "sfx_table:"]
    for i, e in enumerate(res["fx"]):
        L.append("    dw      $%04X, $%04X    ; %2d: cue $%02X %s, %.3f s" % (
            e["start"], e["end"], i, e["cue"], e["file"], e["samples"] / adpcm.RATE_A))
    L += ["", "; tunes (ADPCM-B) by tune index: intro start, intro end, loop start, loop end (256-byte",
          "; units, end inclusive; the loop follows the intro), delta-N, intro_ticks (the intro's",
          "; length in Timer B ticks)", "music_table:"]
    for i, t in enumerate(res["tunes"]):
        L.append("    dw      $%04X, $%04X, $%04X, $%04X, $%04X, %d    ; %d: tune $%02X %s, %.2f Hz" % (
            t["intro"][0], t["intro"][1], t["loop"][0], t["loop"][1], t["delta_n"], t["intro_ticks"],
            i, t["entry"], t["title"], t["rate"]))
    L += ["", "; fade lengths in Timer B ticks by tune index, then speed index (speeds %s):" % (
        " ".join("$%02X" % s for s in FADE_SPEEDS)), "; 64 x speed x the tune's music tick",
          "fade_ticks:"]
    for i, t in enumerate(res["tunes"]):
        L.append("    dw      %s    ; %d: %s, tick %.6f s" % (
            ", ".join("%d" % n for n in t["fade_ticks"]), i, t["title"], t["meta"]["tick_s"]))
    return "\n".join(L) + "\n"


def render_68k(res):
    L = ["; " + HEADER,
         "; the 68k's sound numbers (vasm); the Z80's side is sound.inc. SND_FX_INDEX is a table:",
         "; include this file where data may sit. The P-ROM addresses (SND_TUNE_PTR_*,",
         "; SND_CUE_TABLE) are in game.inc (tools/link.py).", "",
         "; commands written to REG_SOUND; the Z80 replies the command | SND_CMD_ECHO"]
    for name, v, what in COMMANDS:
        L.append("%-24s EQU $%02X   ; %s" % ("SND_CMD_" + name, v, what))
    L += ["", "; MCDRV fade speeds by speed index (SND_CMD_FADE + index)"]
    for i, s in enumerate(FADE_SPEEDS):
        L.append("%-24s EQU $%02X" % ("SND_FADE_SPEED_%d" % i, s))
    L += ["%-24s EQU %d" % ("SND_FADE_SPEEDS", len(FADE_SPEEDS)), "",
          "; tunes by tune index (SND_CMD_PLAY + index): MCDRV tune entry"]
    for i, t in enumerate(res["tunes"]):
        L.append("%-24s EQU $%02X   ; %s" % ("SND_TUNE_%d" % i, t["entry"], t["title"]))
    L += ["%-24s EQU %d" % ("SND_TUNE_COUNT", len(res["tunes"])),
          "%-24s EQU %d" % ("SND_FX_COUNT", len(res["fx"])), "",
          "; cue (0-$7F) -> effect index (SND_CMD_FX + index), $FF = the cue has no sample",
          "SND_FX_INDEX:"]
    t = res["fx_index"]
    for k in range(0, len(t), 16):
        L.append("    dc.b    %s   ; cues $%02X-$%02X" % (
            ",".join("$%02X" % v for v in t[k:k + 16]), k, k + 15))
    L += ["", "; effect index -> the game steps _ADPCMSNS answers busy after its _ADPCMOUT (the",
          "; original's frames: tools/mksound.py fx_frames)", "SND_FX_FRAMES:"]
    f = res["fx_frames"]
    for k in range(0, len(f), 16):
        L.append("    dc.b    %s   ; effects %d-%d" % (
            ",".join("%d" % v for v in f[k:k + 16]), k, min(k + 16, len(f)) - 1))
    L.append("    even")
    return "\n".join(L) + "\n"


def summary(res):
    return {
        "note": HEADER,
        "rate_a": adpcm.RATE_A, "z80_tick_hz": Z80_TICK_HZ, "timer_b": TIMER_B_VALUE,
        "levels": {"adpcma_total": ADPCMA_TOTAL, "adpcma_level": ADPCMA_LEVEL,
                   "adpcmb_level": ADPCMB_LEVEL, "a_out": adpcm_a_out(ADPCMA_TOTAL, ADPCMA_LEVEL),
                   "b_out": adpcm_b_out(ADPCMB_LEVEL), "fx_scale": FX_SCALE},
        "gain": res["gain"], "peak_music": res["peak_music"], "peak_fx": res["peak_fx"],
        "peak_encoded": res["peak_encoded"], "msm_mix": MSM_MIX, "hp_hz": HP_HZ,
        "vrom_used": res["vrom_used"], "fx_index": res["fx_index"],
        "orig_frame_s": ORIG_FRAME_S, "busy_tail_frames": BUSY_TAIL_FRAMES,
        "effects": [{"index": i, "cue": e["cue"], "file": e["file"], "pr": e["pr"],
                     "start": e["start"], "end": e["end"], "samples": e["samples"],
                     "length": len(e["data"]), "busy_frames": f}
                    for i, (e, f) in enumerate(zip(res["fx"], res["fx_frames"]))],
        "tunes": [{"index": i, "entry": t["entry"], "title": t["title"], "rate": t["rate"],
                   "blocks": t["blocks"], "delta_n": t["delta_n"], "intro": t["intro"],
                   "loop": t["loop"], "intro_ticks": t["intro_ticks"], "trim": t["trim"],
                   "loop_at": t["loop_at"], "landing": t["landing"],
                   "fade_ticks": t["fade_ticks"]}
                  for i, t in enumerate(res["tunes"])],
    }


def write(res, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "vrom.bin"), "wb") as f:
        f.write(res["vrom"])
    with open(os.path.join(out, "sound68k.inc"), "w") as f:
        f.write(render_68k(res))
    with open(os.path.join(out, "sound.json"), "w") as f:
        json.dump(summary(res), f, indent=1)
    with open(os.path.join(out, "sound.inc"), "w") as f:
        f.write(render_z80(res))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rec", default="build/snd/rec")
    ap.add_argument("--orig", default="build/orig")
    ap.add_argument("--preinit", default="build/preinit")
    ap.add_argument("--out", default="build/snd")
    a = ap.parse_args(argv)
    with open(os.path.join(a.preinit, "memory.bin"), "rb") as f:
        mem = f.read()
    try:
        res = build(a.rec, os.path.join(a.orig, "disk", "GAME"), mem)
    except ValueError as e:
        sys.exit("mksound: %s" % e)
    write(res, a.out)
    fx_bytes = (res["fx"][-1]["end"] + 1) * 256
    print("mksound: V-ROM %d KB used of 4 MB: %d effects %d KB, %d tunes %d KB; gain %.4f "
          "(effects x %.4f)" % (res["vrom_used"] // 1024, len(res["fx"]), fx_bytes // 1024,
                                len(res["tunes"]), (res["vrom_used"] - fx_bytes) // 1024,
                                res["gain"], FX_SCALE))
    for t in res["tunes"]:
        print("mksound: tune $%02X %-7s %.2f Hz (delta-N %d), intro %.3f s (%d ticks, %d samples "
              "of lead-in dropped), loop %d blocks" % (
                  t["entry"], t["title"], t["rate"], t["delta_n"],
                  (t["loop_at"] - t["trim"]) / t["rate"], t["intro_ticks"], t["trim"], t["blocks"]))


if __name__ == "__main__":
    main()
