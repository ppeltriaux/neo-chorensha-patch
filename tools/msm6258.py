"""MSM6258 (OKI/Dialogic) ADPCM decoder, as MAME's okim6258 in its x68000 driver (the X68000's ADPCM).

The algorithm is the well-known OKI/Dialogic ADPCM one that MAME's okim6258.cpp uses: the 49-entry
step table, the index shift table -1 -1 -1 -1 2 4 6 8 (indexed by the nibble's low 3 bits), and
per nibble (low nibble first)
    diff = step/8 + (bit2 ? step : 0) + (bit1 ? step/2 : 0) + (bit0 ? step/4 : 0)   (each integer-divided)
    signal += bit3 ? -diff : diff, clamped to the 10-bit range -512..511 (the x68000 driver's
              OUTPUT_10BITS)
    index  += shift[nibble & 7], clamped to 0..48
and the signal is scaled by 16 to int16 (-8192..8176).

The start state is the one the X68000 leaves between samples in MAME: after a sample ends the chip
sits at the 10-bit floor (signal -512, step index 0: MAME's x68000 output holds -4096 =
-512 x 16 x the 0.5 route gain), and a new sample decodes on from there, so every effect starts at
-8192 and climbs to its own level. Checked against MAME x68000's output for all 25 of the game's
effects (tests/tools/test_record_sound.py: correlation >= 0.95; low nibble first, 10 bits and the
floor start each needed, a 12-bit clamp or a -2 start gave 0.47-0.78 on the worst cue). MAME mixes
the chip at 0.5 of this scale next to the OPM music.
"""
import numpy as np

STEPS = [16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
         130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
         724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552]
INDEX_SHIFT = [-1, -1, -1, -1, 2, 4, 6, 8]
SIGNAL_MIN, SIGNAL_MAX = -512, 511       # 10-bit output


def decode(data, low_nibble_first=True, signal=SIGNAL_MIN, index=0):
    """MSM6258 ADPCM bytes -> int16 samples, two per byte (low nibble first by default), from the
    given start state (by default the floor the X68000 leaves between samples)."""
    out = []
    for byte in bytes(data):
        pair = (byte & 15, byte >> 4) if low_nibble_first else (byte >> 4, byte & 15)
        for nib in pair:
            step = STEPS[index]
            diff = (step >> 3) + (step if nib & 4 else 0) + (step >> 1 if nib & 2 else 0) \
                + (step >> 2 if nib & 1 else 0)
            signal = max(SIGNAL_MIN, min(SIGNAL_MAX, signal + (-diff if nib & 8 else diff)))
            index = max(0, min(48, index + INDEX_SHIFT[nib & 7]))
            out.append(signal * 16)
    return np.array(out, dtype=np.int16)
