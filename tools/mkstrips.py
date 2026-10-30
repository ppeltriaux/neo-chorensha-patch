#!/usr/bin/env python3
"""Strip tool: an image -> the two 32x224 side strips of the presentation, as Neo Geo fix tiles.

  reduce(src)      any PIL image -> a 32x224 mode-P image the fix layer can show exactly
  build(png)       that image -> (tiles_left, tiles_right, pal10, pal11, fixmap)
  preview(png, f)  a 320x224 game frame with the strips pasted in (1:1 and x3, CRT crop marked)

Fit (reduce): the image is composited on black if it has alpha, scaled to 32 px wide (box filter,
aspect kept: height h = round(H * 32 / W)), then made 224 tall. h > 224: a 224-line window is cut
out, its top at scaled row `offset` (default centred, (h - 224) // 2). h < 224: the image is put
on a canvas of `pad` colour (default black) with its top at canvas row `offset` (default centred).
`offset` is clamped so the window / image stays inside / on the canvas.

Quantising: every colour is one a Neo Geo palette word can show, as MAME displays it: the
candidates are all 65536 words through x68k_gfx.neo_rgb, each colour by the lowest word that
shows it but never $0000: black is $8000 (the dark bit), which shows the same. No strip colour
is the word $0000, which a display may take as transparent (Presentation Task 4's carry; MAME
0.289's neogeo, measured, shows a fix pixel of word $0000 opaque black). Two palettes of 14
colours (entries 2-15: entry 0 would make the strip transparent, entry 1 is the game's $6AB8
ramp). The tiles are split
between the two palettes by alternating k-means (palette fit on its tiles' pixels, then every tile
to the palette that gives it the lowest error); error is squared RGB, weighted 2:4:3. Flat by
default: `dither=True` diffuses the error (Floyd-Steinberg, inside the tile's palette).

The reduced image: mode P, indices 0-15 = palette 10 (0 and 1 unused, black), 16-31 = palette 11
(16 and 17 unused). A tile's pixels all use indices of one palette; build() relies on that.

fixmap: 224 words, the left strip's 112 cells then the right's (row-major, row * 4 + column; the
column is the screen column, left to right): tile number | palette << 12, tile numbers from $180.
The tiles are one block from $180: tiles_left then tiles_right (32 bytes each, mkgfx's fix format).
The right strip is the left one mirrored. Identical tiles (same pixels, whatever the palette) are
stored once across both strips. pal10 / pal11: 16 Neo Geo words; entries 0 and 1 are 0 and are
not to be written (entry 1 stays the ramp's); an entry the image does not use is 0, every one it
uses nonzero (the strips opaque: checked, ValueError otherwise).
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkgfx  # noqa: E402
import x68k_gfx  # noqa: E402

W, H = 32, 224
TILE_BASE = 0x180
MAX_TILES = 224
PALS = (10, 11)
WEIGHT = np.array([2.0, 4.0, 3.0])

_LATTICE = None


def _lattice():
    """(words, rgb): one word per displayable colour (the lowest, but never $0000: the module
    doc), rgb as float (n, 3)."""
    global _LATTICE
    if _LATTICE is None:
        seen = {}
        for n in range(0x10000):
            seen.setdefault(x68k_gfx.neo_rgb(n), n)
        black = x68k_gfx.neo_rgb(0)              # (its place in the order kept: reduce's ties)
        seen[black] = min(n for n in range(1, 0x10000) if x68k_gfx.neo_rgb(n) == black)
        _LATTICE = (np.array(list(seen.values())), np.array(list(seen.keys()), dtype=float))
    return _LATTICE


def _dist(a, b):
    """Weighted squared RGB distance, a (n, 3) x b (m, 3) -> (n, m)."""
    d = a[:, None, :] - b[None, :, :]
    return (d * d * WEIGHT).sum(axis=2)


def _snap(rgb):
    """The nearest displayable colour of each row: (words, rgb)."""
    words, lat = _lattice()
    i = _dist(rgb, lat).argmin(axis=1)
    return words[i], lat[i]


def fit(src, offset=None, pad=(0, 0, 0)):
    """Scale to 32 wide, then crop or pad to 224 tall (see the module doc): an RGB image."""
    if src.mode in ("RGBA", "LA", "PA") or "transparency" in src.info:
        rgba = src.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        src = Image.alpha_composite(bg, rgba)
    src = src.convert("RGB")
    h = max(1, round(src.height * W / src.width))
    img = src.resize((W, h), Image.BOX if src.width >= W else Image.BICUBIC)
    if h >= H:
        top = (h - H) // 2 if offset is None else min(max(offset, 0), h - H)
        return img.crop((0, top, W, top + H))
    top = (H - h) // 2 if offset is None else min(max(offset, 0), H - h)
    out = Image.new("RGB", (W, H), tuple(pad))
    out.paste(img, (0, top))
    return out


def _kmeans(cols, w, k):
    """Weighted k-means of colours cols (n, 3): k centres (m <= k, 3)."""
    if len(cols) <= k:
        return cols.copy()
    c = [cols[w.argmax()]]
    for _ in range(k - 1):
        d = _dist(cols, np.array(c)).min(axis=1) * w
        c.append(cols[d.argmax()])
    c = np.array(c)
    for _ in range(12):
        a = _dist(cols, c).argmin(axis=1)
        for j in range(len(c)):
            m = a == j
            if m.any():
                c[j] = (cols[m] * w[m, None]).sum(axis=0) / w[m].sum()
    return c


def _fit_palette(pix):
    """pix (n, 3) pixels -> up to 14 displayable (words, rgb), nearest-snapped, distinct."""
    cols, cnt = np.unique(pix, axis=0, return_counts=True)
    c = _kmeans(cols.astype(float), cnt.astype(float), 14)
    words, rgb = _snap(c)
    _, first = np.unique(words, return_index=True)
    first.sort()
    return words[first], rgb[first]


def _tile_costs(tiles, pal_rgb):
    """tiles (t, 64, 3) -> (t,) error of each tile in a palette of colours pal_rgb."""
    d = _dist(tiles.reshape(-1, 3), pal_rgb).min(axis=1)
    return d.reshape(len(tiles), -1).sum(axis=1)


def _tiles_of(rgb):
    """(112, 64, 3) float: the image's 8x8 tiles, row-major (row * 4 + column)."""
    a = np.asarray(rgb, dtype=float).reshape(H // 8, 8, W // 8, 8, 3)
    return a.transpose(0, 2, 1, 3, 4).reshape(-1, 64, 3)


def _assign(tiles):
    """Choose two palettes and each tile's palette: ([(words, rgb)] * 2, group (112,))."""
    mean = tiles.mean(axis=1)
    cen = _kmeans(mean, np.ones(len(mean)), 2)
    group = _dist(mean, cen).argmin(axis=1)
    pals = [None, None]
    for _ in range(10):
        for g in (0, 1):
            m = group == g
            pals[g] = _fit_palette(tiles[m].reshape(-1, 3)) if m.any() else None
        if pals[1] is None:
            pals[1] = pals[0]
        if pals[0] is None:
            pals[0] = pals[1]
        cost = np.stack([_tile_costs(tiles, p[1]) for p in pals], axis=1)
        new = cost.argmin(axis=1)
        if (new == group).all():
            break
        group = new
    return pals, group


def reduce(src, offset=None, pad=(0, 0, 0), dither=False):
    """Any image -> the 32x224 mode-P strip image (see the module doc)."""
    rgb = fit(src, offset, pad)
    tiles = _tiles_of(rgb)
    pals, group = _assign(tiles)
    idx = np.zeros((H, W), np.uint8)
    pix = np.asarray(rgb, dtype=float)
    err = np.zeros((H + 1, W + 2, 3))
    for y in range(H):
        for x in range(W):
            g = group[(y // 8) * 4 + x // 8]
            prs = pals[g][1]
            p = pix[y, x] + (err[y, x + 1] if dither else 0)
            k = int(_dist(p[None, :], prs).argmin())
            idx[y, x] = g * 16 + 2 + k
            if dither:
                e = p - prs[k]
                err[y, x + 2] += e * 7 / 16
                err[y + 1, x] += e * 3 / 16
                err[y + 1, x + 1] += e * 5 / 16
                err[y + 1, x + 2] += e * 1 / 16
    out = Image.fromarray(idx, "P")
    pal = [0] * 768
    for g in (0, 1):
        for k, c in enumerate(pals[g][1]):
            pal[(g * 16 + 2 + k) * 3:(g * 16 + 2 + k) * 3 + 3] = [int(v) for v in c]
    out.putpalette(pal)
    return out


def _word_of(rgb):
    """The Neo Geo word that shows rgb (the lowest); ValueError if none does."""
    words, lat = _lattice()
    i = np.flatnonzero((lat == np.array(rgb, dtype=float)).all(axis=1))
    if not len(i):
        raise ValueError("colour %s is not one a Neo Geo palette word can show" % (tuple(rgb),))
    return int(words[i[0]])


def _load(png):
    img = Image.open(png) if isinstance(png, (str, os.PathLike)) else png
    if img.mode != "P" or img.size != (W, H):
        raise ValueError("a reduced strip image is 32x224 mode P (run reduce first)")
    return img


def build(png, max_tiles=MAX_TILES):
    """A reduced strip image (path or Image) -> (tiles_left, tiles_right, pal10, pal11, fixmap)."""
    img = _load(png)
    idx = np.asarray(img)
    rgb = img.getpalette()
    rgb += [0] * (768 - len(rgb))
    if (idx & 15 < 2).any() or (idx > 31).any():
        raise ValueError("strip image uses palette entry 0 or 1 (or an index above 31)")
    pal = []
    for g in (0, 1):
        words = [0, 0]
        for e in range(2, 16):
            o = (g * 16 + e) * 3
            words.append(_word_of(rgb[o:o + 3]) if (idx == g * 16 + e).any() else 0)
            if (idx == g * 16 + e).any() and words[-1] == 0:
                raise ValueError("palette %d entry %d: word $0000 (kept out of the strips)"
                                 % (PALS[g], e))
        pal.append(words)
    tiles = idx.reshape(H // 8, 8, W // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 8, 8)
    pgroup = tiles // 16
    if (pgroup != pgroup[:, :1, :1]).any():
        raise ValueError("a tile mixes the two palettes")
    store, order = {}, []                # tile bytes -> number; bytes by number

    def put(g):
        key = mkgfx.encode_fix_tile((g & 15).tolist())
        if key not in store:
            store[key] = len(order)
            order.append(key)
        return store[key]

    left = [(put(t), PALS[int(t[0, 0] >> 4)]) for t in tiles]
    n_left = len(order)
    right = []
    for r in range(H // 8):
        for c in range(4):
            t = tiles[r * 4 + 3 - c]
            right.append((put(t[:, ::-1]), PALS[int(t[0, 0] >> 4)]))
    if len(order) > max_tiles:
        raise ValueError("%d distinct tiles, the budget is %d" % (len(order), max_tiles))
    fixmap = [(TILE_BASE + n) | p << 12 for n, p in left + right]
    return (b"".join(order[:n_left]), b"".join(order[n_left:]), pal[0], pal[1], fixmap)


def decode(tiles_left, tiles_right, pal10, pal11, fixmap):
    """The two strips as RGB images (left, right) from build()'s output: the check of build."""
    blob = tiles_left + tiles_right
    pals = {10: pal10, 11: pal11}
    out = []
    for side in (0, 1):
        im = np.zeros((H, W, 3), np.uint8)
        for cell in range(112):
            v = fixmap[side * 112 + cell]
            n = (v & 0xFFF) - TILE_BASE
            g = mkgfx.decode_fix_tile(blob[n * 32:(n + 1) * 32])
            r, c = divmod(cell, 4)
            for y in range(8):
                for x in range(8):
                    im[r * 8 + y, c * 8 + x] = x68k_gfx.neo_rgb(pals[v >> 12][g[y][x]])
        out.append(Image.fromarray(im, "RGB"))
    return tuple(out)


def preview(png, frame_png):
    """The strips pasted onto a 320x224 game frame: 1:1 on top, x3 below, the outer 8 px marked."""
    left = _load(png).convert("RGB")
    right = left.transpose(Image.FLIP_LEFT_RIGHT)
    frame = Image.open(frame_png).convert("RGB")
    if frame.size != (320, 224):
        raise ValueError("the frame is 320x224")
    frame.paste(left, (0, 0))
    frame.paste(right, (288, 0))
    big = frame.resize((960, 672), Image.NEAREST)
    out = Image.new("RGB", (960, 224 + 4 + 672), (32, 32, 32))
    out.paste(frame, (0, 0))
    out.paste(big, (0, 228))
    mark = (255, 0, 255)
    for x in (7, 312):                      # the outer 8 px a CRT hides: lines on their inner edge pixels
        for y in range(224):
            out.putpixel((x, y), mark)
    for x in (23, 936):
        for y in range(228, 900):
            out.putpixel((x, y), mark)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reduce", help="SRC -> OUT.png, the 32x224 strip image")
    r.add_argument("src")
    r.add_argument("out")
    r.add_argument("--offset", type=int, default=None, help="crop/pad top row (default centred)")
    r.add_argument("--dither", action="store_true")
    p = sub.add_parser("preview", help="STRIP.png FRAME.png -> OUT.png")
    p.add_argument("strip")
    p.add_argument("frame")
    p.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "reduce":
        reduce(Image.open(a.src), a.offset, dither=a.dither).save(a.out)
    else:
        preview(a.strip, a.frame).save(a.out)


if __name__ == "__main__":
    main()
