"""X68000 graphics formats of Chourensha 68K (docs/notes/graphics-recon.md §1-2).

- decode_pcg(data): XSP/PCG 16x16 patterns, 128 B each: four 8x8 quadrants in the order TL, BL,
  TR, BR; 4 bytes per quadrant row, 4bpp packed, the left pixel in the high nibble.
- build_pages(bg_pcg, bgtext): the game-start background builder $6512 (§1.3): graphic pages 0 and
  1 as 256 x 512 index images (one byte per pixel, row-major), from BG_PCG.SP (256 8x8 tiles, 32 B
  each, packed like PCG quadrants) and BG text page 1 as _BGTEXTGT reads it (64 x 64 big-endian
  cell words, row-major; build/preinit/bgtext.bin). Page p, cell (col, row) = cell[row][col + 32p]:
  tile = cell & $FF, block = (cell >> 8) & $F, bit 15 = V flip, bit 14 = H flip; pixel = block << 4
  | nibble.
- decode_text_font(data): SZ_TEXT.PCG (§1.4), 32 planar 16x16 cells of 128 B (4 planes x 16 rows
  x 2 B; plane p = colour bit p, bit 7 = leftmost pixel) as the 128 8x8 characters of the
  renderer $1618: char ch = cell ch >> 2, quadrant ch & 3 (0 TL, 1 BL, 2 TR, 3 BR).
- neo_colour / x68k_colour: X68000 GGGGG RRRRR BBBBB I <-> Neo Geo D R0 G0 B0 R4-1 G4-1 B4-1,
  dark D = !I. A bijection of the 65,536 words.
- neo_rgb: Neo Geo palette word -> the RGB MAME neogeo shows for it (its resistor-weighted
  levels, NEO_LEVELS, measured on the Neo Geo in MAME: tests/neo/sprites.lua SP_RGB=1). A Neo Geo
  screenshot compares with the reference renderer through render_words -> neo_colour -> neo_rgb.
"""

PAGE_W, PAGE_H = 256, 512
CELLS = 64                    # BG text page: 64 x 64 cells


def _nibbles(row4):
    """4 packed bytes -> 8 pixels, high nibble first."""
    out = []
    for b in row4:
        out.append(b >> 4)
        out.append(b & 15)
    return out


def decode_pcg(data):
    """PCG patterns (128 B each) -> list of 16x16 grids (rows of 16 colour indices)."""
    if len(data) % 128:
        raise ValueError("PCG data is %d bytes, not a multiple of 128" % len(data))
    pats = []
    for at in range(0, len(data), 128):
        g = [[0] * 16 for _ in range(16)]
        for q, (qx, qy) in enumerate(((0, 0), (0, 8), (8, 0), (8, 8))):
            for y in range(8):
                o = at + q * 32 + y * 4
                g[qy + y][qx:qx + 8] = _nibbles(data[o:o + 4])
        pats.append(g)
    return pats


def decode_bg_tiles(bg_pcg):
    """BG_PCG.SP: 8x8 tiles of 32 B -> list of 8x8 grids."""
    return [[_nibbles(bg_pcg[t * 32 + y * 4:t * 32 + y * 4 + 4]) for y in range(8)]
            for t in range(len(bg_pcg) // 32)]


def build_pages(bg_pcg, bgtext):
    """($6512) -> (page0, page1): 256 x 512 bytes each, pixel (x, y) at y * 256 + x."""
    if len(bgtext) != CELLS * CELLS * 2:
        raise ValueError("BG text page is %d bytes, not %d" % (len(bgtext), CELLS * CELLS * 2))
    tiles = decode_bg_tiles(bg_pcg)
    pages = []
    for page in range(2):
        img = bytearray(PAGE_W * PAGE_H)
        for row in range(CELLS):
            for col in range(32):
                i = (row * CELLS + col + 32 * page) * 2
                cell = bgtext[i] << 8 | bgtext[i + 1]
                t = tiles[cell & 0xFF]
                hi = ((cell >> 8) & 0xF) << 4
                vflip, hflip = cell & 0x8000, cell & 0x4000
                for y in range(8):
                    src = t[7 - y if vflip else y]
                    if hflip:
                        src = src[::-1]
                    o = (row * 8 + y) * PAGE_W + col * 8
                    img[o:o + 8] = bytes(hi | v for v in src)
        pages.append(bytes(img))
    return pages[0], pages[1]


def decode_text_font(data):
    """SZ_TEXT.PCG -> 128 8x8 grids, by character code."""
    if len(data) != 32 * 128:
        raise ValueError("text font is %d bytes, want %d" % (len(data), 32 * 128))
    chars = []
    for ch in range(128):
        cell, q = ch >> 2, ch & 3
        off = (0, 16, 1, 17)[q]            # $1618: quadrant -> byte offset in a plane
        g = [[0] * 8 for _ in range(8)]
        for p in range(4):
            for y in range(8):
                b = data[cell * 128 + p * 32 + off + 2 * y]
                for x in range(8):
                    g[y][x] |= ((b >> (7 - x)) & 1) << p
        chars.append(g)
    return chars


def neo_colour(w):
    """X68000 palette word -> Neo Geo palette word (exact)."""
    g, r, b, i = (w >> 11) & 31, (w >> 6) & 31, (w >> 1) & 31, w & 1
    return ((0 if i else 1) << 15 | (r & 1) << 14 | (g & 1) << 13 | (b & 1) << 12 |
            (r >> 1) << 8 | (g >> 1) << 4 | (b >> 1))


def x68k_colour(n):
    """Neo Geo palette word -> X68000 palette word (the inverse of neo_colour)."""
    r = ((n >> 8) & 15) << 1 | (n >> 14) & 1
    g = ((n >> 4) & 15) << 1 | (n >> 13) & 1
    b = (n & 15) << 1 | (n >> 12) & 1
    return g << 11 | r << 6 | b << 1 | (0 if n & 0x8000 else 1)


# MAME neogeo's 8-bit output per 5-bit channel value (R4-R1 R0, ...), without and with the dark
# bit: measured by tests/neo/sprites.lua SP_RGB=1 (every value of each channel as the backdrop
# colour, read back from the screen); tests/tools/test_neo_run.py TestNeoSprites.test_neo_rgb
# measures them again. (MAME computes them from the resistor network: 220-3900 ohm, the dark
# bit an 8.2k pull-down.)
NEO_LEVELS = (
    (0, 8, 14, 22, 30, 38, 44, 52, 65, 73, 79, 86, 95, 103, 109, 117,
     138, 146, 152, 160, 169, 176, 182, 190, 203, 211, 217, 225, 233, 241, 247, 255),
    (0, 8, 14, 21, 30, 38, 44, 51, 64, 71, 77, 85, 94, 101, 107, 115,
     136, 144, 150, 158, 166, 174, 180, 188, 200, 208, 214, 221, 230, 238, 244, 251),
)


def neo_rgb(n):
    """Neo Geo palette word -> (r, g, b) as MAME neogeo displays it."""
    lv = NEO_LEVELS[(n >> 15) & 1]
    r = (n >> 7) & 0x1E | (n >> 14) & 1
    g = (n >> 3) & 0x1E | (n >> 13) & 1
    b = (n << 1) & 0x1E | (n >> 12) & 1
    return (lv[r], lv[g], lv[b])
