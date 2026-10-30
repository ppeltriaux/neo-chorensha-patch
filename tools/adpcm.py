"""YM2610 ADPCM-A/ADPCM-B codecs, a windowed-sinc resampler and the V-ROM packer (Plan 4).

Lifted from neo-r-type's tools/rtype_sound.py (bit-exact encoders, resampler, packer, VRom); the
decoders are the chip's, as in ymfm / MAME, so a round trip shows what the YM2610 will play.

  encode_a(pcm) -> bytes           ADPCM-A at 18,518.5 Hz (8 MHz / 432), 12-bit accumulator
  encode_b(pcm, rate_hz) -> (bytes, delta_n)   ADPCM-B at rate_hz, 16-bit accumulator
  decode_a(data) / decode_b(data, delta_n) -> int16 samples
  resample(pcm, src_hz, dst_hz)    Hann-windowed sinc, 32 taps per side at the lower rate
  pack_blocks(data)                pad to whole 256-byte blocks (the chips address in those)
  VRom                             effects (ADPCM-A) first, none crossing 1 MB, then music (B)

Samples are nibbles, high nibble first. Nothing here reads original data; callers keep the
results in build/.
"""
import numpy as np

YM_CLOCK = 8_000_000
RATE_A = YM_CLOCK / 432          # ADPCM-A: fixed 18.5 kHz
RATE_B_BASE = YM_CLOCK / 144     # ADPCM-B: delta-N / 65536 of this
PAD_NIBBLES = 0x08               # odd-length streams end on this nibble (-1 step)
VROM_SIZE = 0x400000

A_STEPS = [16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
           130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
           724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552]
A_INC = [-1, -1, -1, -1, 2, 5, 7, 9]
B_SCALE = [57, 57, 57, 57, 77, 102, 128, 153]
B_STEP_MIN, B_STEP_MAX = 127, 24576


def resample(x, src_hz, dst_hz):
    """Windowed-sinc resampling (Hann, 32 taps per side at the lower rate)."""
    x = np.asarray(x, dtype=np.float64)
    n_out = int(len(x) * dst_hz / src_hz)
    t = np.arange(n_out) * (src_hz / dst_hz)
    cutoff = min(1.0, dst_hz / src_hz) * 0.95
    half = 32 * src_hz / dst_hz
    out = np.zeros(n_out)
    base = np.floor(t).astype(np.int64)
    for k in range(-int(half), int(half) + 1):
        idx = base + k
        ok = (idx >= 0) & (idx < len(x))
        d = t - idx
        w = cutoff * np.sinc(cutoff * d) * (0.5 + 0.5 * np.cos(np.pi * np.clip(d / half, -1, 1)))
        out[ok] += x[idx[ok]] * w[ok]
    return out


def _nibbles_to_bytes(nibbles):
    if len(nibbles) % 2:
        nibbles = nibbles + [PAD_NIBBLES]
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def _bytes_to_nibbles(data):
    b = np.frombuffer(bytes(data), dtype=np.uint8)
    return np.stack([b >> 4, b & 15], axis=1).reshape(-1).tolist()


def encode_a(pcm):
    """16-bit samples -> ADPCM-A bytes (12-bit accumulator, kept from wrapping)."""
    acc, si, out = 0, 0, []
    for v in np.clip(np.round(np.asarray(pcm, dtype=np.float64) / 16), -2048, 2047).astype(int).tolist():
        step = A_STEPS[si]
        diff = v - acc
        m = min(7, max(0, int(round((abs(diff) * 8 / step - 1) / 2))))
        best = None
        for mm in (m - 1, m, m + 1):
            if 0 <= mm <= 7:
                d = (2 * mm + 1) * step // 8
                for n, a in ((mm, acc + d), (mm | 8, acc - d)):
                    if -2048 <= a <= 2047 and (best is None or abs(a - v) < best[0]):
                        best = (abs(a - v), n, a)
        _, n, acc = best
        si = min(48, max(0, si + A_INC[n & 7]))
        out.append(n)
    return _nibbles_to_bytes(out)


def decode_a(data):
    """ADPCM-A bytes -> int16 samples (12-bit accumulator scaled by 16, as ymfm)."""
    acc, si, out = 0, 0, []
    for n in _bytes_to_nibbles(data):
        d = (2 * (n & 7) + 1) * A_STEPS[si] // 8
        acc = ((acc + (-d if n & 8 else d) + 2048) & 0xFFF) - 2048
        si = min(48, max(0, si + A_INC[n & 7]))
        out.append(acc * 16)
    return np.array(out, dtype=np.int16)


def encode_b(pcm, rate_hz):
    """16-bit samples at rate_hz -> (ADPCM-B bytes, delta_n). The caller picks rate_hz (22,000
    nominal) and resamples to it; for a loop, rate_hz is adjusted so the loop is whole 512-sample
    blocks (rate = blocks * 512 / loop seconds), and delta_n follows that rate."""
    acc, step, out = 0, B_STEP_MIN, []
    for v in np.clip(np.round(np.asarray(pcm, dtype=np.float64)), -32768, 32767).astype(int).tolist():
        diff = v - acc
        m = min(7, max(0, int(round((abs(diff) * 8 / step - 1) / 2))))
        best = None
        for mm in (m - 1, m, m + 1):
            if 0 <= mm <= 7:
                d = (2 * mm + 1) * step // 8
                for n, a in ((mm, acc + d), (mm | 8, acc - d)):
                    a = max(-32768, min(32767, a))
                    if best is None or abs(a - v) < best[0]:
                        best = (abs(a - v), n, a)
        _, n, acc = best
        step = max(B_STEP_MIN, min(B_STEP_MAX, step * B_SCALE[n & 7] // 64))
        out.append(n)
    return _nibbles_to_bytes(out), round(rate_hz / RATE_B_BASE * 65536)


def decode_b(data, delta_n):
    """ADPCM-B bytes -> int16 samples at delta_n / 65536 * 55,555 Hz (16-bit saturating
    accumulator). delta_n only sets the playback rate, so it does not change the samples."""
    acc, step, out = 0, B_STEP_MIN, []
    for n in _bytes_to_nibbles(data):
        d = (2 * (n & 7) + 1) * step // 8
        acc = max(-32768, min(32767, acc + (-d if n & 8 else d)))
        step = max(B_STEP_MIN, min(B_STEP_MAX, step * B_SCALE[n & 7] // 64))
        out.append(acc)
    return np.array(out, dtype=np.int16)


def pack_blocks(data):
    """Pad to whole 256-byte blocks with $08 bytes: +1/-1 step pairs, which hold the level
    instead of drifting."""
    return bytes(data) + bytes([0x08]) * (-len(data) % 256)


class VRom:
    """The V-ROM image: ADPCM-A effects first (none may cross a 1 MB boundary), then ADPCM-B.
    Addresses are in 256-byte units, end inclusive."""

    def __init__(self):
        self.data = bytearray()
        self.entries = {}

    def _add(self, name, data, a_sample):
        if name in self.entries:
            raise ValueError(f"V-ROM: {name!r} added twice")
        if not data:
            raise ValueError(f"V-ROM: {name!r} is empty")
        packed = pack_blocks(data)
        if a_sample and len(packed) > 1 << 20:
            raise ValueError(f"V-ROM: ADPCM-A sample {name!r} is {len(packed):#x} bytes, over 1 MB")
        if a_sample and (len(self.data) >> 20) != ((len(self.data) + len(packed) - 1) >> 20):
            self.data += bytes(-len(self.data) % (1 << 20))
        if len(self.data) + len(packed) > VROM_SIZE:
            raise ValueError(f"V-ROM overflow adding {name!r}: {len(self.data) + len(packed):#x} > {VROM_SIZE:#x}")
        start = len(self.data) >> 8
        self.data += packed
        self.entries[name] = (start, (len(self.data) >> 8) - 1)
        return self.entries[name]

    def add_a(self, name, data):
        return self._add(name, data, True)

    def add_b(self, name, data):
        return self._add(name, data, False)

    def image(self, size=VROM_SIZE):
        if len(self.data) > size:
            raise ValueError(f"V-ROM overflow: {len(self.data):#x} > {size:#x}")
        return bytes(self.data) + bytes(size - len(self.data))
