#!/usr/bin/env python3
"""Convert Chourensha 68K's art for the Neo Geo (docs/notes/graphics-recon.md §1-2, §7).

Inputs (the user's dump; nothing derived is committed; and the side strips' art, which is ours):
  <preinit>/snapshot.json, memory.bin  the start-up snapshot: the XSP pattern heap block (813 PCG
                                       patterns, xsp_pcgdat_set's pcg) and palette RAM as the
                                       start-up left it (io_final $E82000-$E823FF)
  <preinit>/bgtext.bin                 BG text page 1 as the background builder reads it
  <orig>/disk/GAME/XSP_DAT/BG_PCG.SP   the builder's 8x8 tiles; SZ_TEXT.PCG: the text font
  --strip art/strips/strip.png         the side strips (Presentation Task 5: generated art, not the
                                       original's), through tools/mkstrips.py build()
Outputs in <out> (make gfx: build/gfx):
  c1.bin, c2.bin     the C-ROM pair (whole 1 MB chips); layout in gfx.inc
  s1.bin             the S-ROM (128 KB): the text font's 128 8x8 characters at tile = code, player
                     2's HUD copies of codes 0-$7E at P2_FONT_BASE + code (two-player Task 8), and
                     from STRIP_TILE_BASE the side strips' tiles (both strips: the right one is the
                     left mirrored, and the fix layer has no flip)
  gfx.inc            equates (tile bases, palette numbers), the two background tile maps and
                     STRIP_MAP, the strips' fix words (text.asm Text_Init writes them once)
  palettes.bin       Neo Geo palette RAM image (256 palettes x 16 words, big-endian), static colours
  palette_map.json   X68000 colour index -> [[Neo palette, entry], ...] it feeds ("graphic": GVRAM
                     indices, "sprite": text/sprite indices block*16+colour), for the colour ramps
                     (gfx.inc carries the same map for the shim: PAL_XMAP, PAL_XLIST)

C-ROM tiles (16x16): 0 blank; SPR_TILE_BASE + pt = XSP pattern pt (0-812, palette = sprite block,
identity); BG_TILE_BASE.. the background pages' distinct tiles (flips folded); FONT_SPR_BASE + ch
the text font as sprite tiles (character ch's 8x8 glyph in the tile's top-left quadrant, the rest
transparent; palette PAL_TEXT: the field text that follows the view, Task 3); FREE_TILE_BASE ..
FREE_TILE_END unused. The background pages are 16 x 32 tiles each
(256 x 512), BGn_TILEMAP: per column 0-15, per row 0-31, the SCB1 pair (tile low word, attribute
word = palette << 8 | tile bits 16-19 << 4 | V flip << 1 | H flip).
Palettes: 0 = the text palette (fix palette 0: the fix layer's palette field has 4 bits, so it
must be 0-15; sprite block 0 is never used by sprites), 1-15 = sprite blocks 1-15 -- but entries
2-15 of palettes 10 and 11 (STRIP_PALS) hold the side strips' colours: sprites never use blocks
A and B (graphics-recon), and colour 1 there stays block A's / B's, the game's $6AB8 ramp writes
it (the strips use entries 2-15 only, no word $0000: opaque); PAL_BG1 = page 1
(block A, opaque), PAL_BG0_BASE.. = page 0's merged palettes (its 16x16 tiles mix blocks 9/A/B: a
greedy merge into 15-colour palettes; the opaque nibble-0 colours $90/$A0/$B0 get real entries,
page 0's index 0 is entry 0, transparent), PAL_P2_BASE + 2, 5, 9 = player 2's sprites (two-player
Task 8: p2_palette of blocks 2, 5, 9; palette 0's entries 1 and 5, which the font never uses, its
HUD's colours P2_HUD). Palette 255 entry 15 is the backdrop colour (black).
No X68000 colour feeds an entry 0 (refused): a colour the game changes at run time (the ramps, which
reach $0000) stays opaque on the Neo Geo.
The colour ramps (Plan 3 Task 6, src/shim/palette.asm): PAL_XMAP, per X68000 colour (graphic 0-255,
then text/sprite 256-511) the byte offset in PAL_XLIST of its list: count, then the palette RAM byte
offset (palette * 32 + entry * 2) of each Neo entry it feeds (PAL_XLIST starts with the empty list;
at most PAL_XMAX entries a colour). NEO_CHI / NEO_CLO: neo_colour(w) = NEO_CHI[w >> 8] |
NEO_CLO[w & $FF] (each output bit comes from one input bit: x68k_gfx.neo_colour split by bytes).
"""
import argparse
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x68k_gfx  # noqa: E402

C_TILE = 64                    # bytes per 16x16 tile per C-ROM chip
TILE_BLANK = 0
SPR_TILE_BASE = 0x0001
SPR_TILE_COUNT = 813
BG_TILE_BASE = 0x0340
FONT_SPR_BASE = 0x0400         # the font as sprite tiles: tile = FONT_SPR_BASE + character
FONT_SPR_COUNT = 128
FREE_TILE_BASE = FONT_SPR_BASE + FONT_SPR_COUNT
FREE_TILE_END = 0x3FFF         # 1 MB per chip
S1_SIZE = 0x20000
FIX_TILE = 32
FONT_FIX_BASE = 0x0000         # the font is ASCII-ordered: code = tile, space and 0 blank
FONT_FIX_COUNT = 128
STRIP_TILE_BASE = 0x0180       # the side strips' tiles ($80-$17F stay blank: $FF the BIOS's border)
STRIP_PALS = (10, 11)          # their palettes, entries 2-15 (tools/mkstrips.py)
STRIP_COLS = 4                 # fix columns 0-3 and 36-39 (screen x 0-31, 288-319) ...
STRIP_ROW, STRIP_ROWS = 2, 28  # ... rows 2-29: the 224 lines
FIX_FREE_END = S1_SIZE // FIX_TILE - 1
PAL_TEXT = 0
PAL_SPR_BASE = 0               # Neo palette = PAL_SPR_BASE + X68000 sprite block
PAL_BG1 = 16
PAL_BG0_BASE = 17
PAL_BACKDROP = 255             # entry 15: the backdrop colour
# Player 2's colours (two-player plan Task 8). Its sprites take Neo palette PAL_P2_BASE + block
# (the attribute's bit 13, which no attribute of the game's sets and the X68000 ignores:
# sprites.asm ATTR): its ship's block 9 ($93A) and its shots' 2 and 5 (priority $36), each
# p2_palette of P1's. Its HUD: every block is some sprite's (the lock-step's attribute log), so
# P2's HUD characters are the font's copies at S-ROM tile P2_FONT_BASE + code (codes 0-$7E: $FF
# is the BIOS's border tile) in fix palette 0's entries 1 and 5, which the font never uses
# (P2_FONT_MAP: its bright colours on 1, its dark ones on 5), set to P2_HUD (fed by no X68000
# colour: the text palette's 1 and 5 are never shown).
PAL_P2_BASE = 0x20
P2_BLOCKS = (2, 5, 9)
P2_FONT_BASE = 0x80
P2_FONT_COUNT = 0x7F
P2_FONT_ENTRIES = (1, 5)       # P2's main colour, its shade
P2_FONT_MAP = (0, 1, 1, 5, 5, 5, 5, 5, 1, 1, 1, 5, 5, 1, 1, 1)   # font colour index -> entry


def rgb5(r, g, b):
    """5-bit channels (the X68000's) -> a Neo Geo palette word (bright: dark bit 0)."""
    return (r & 1) << 14 | (g & 1) << 13 | (b & 1) << 12 | (r >> 1) << 8 | (g >> 1) << 4 | (b >> 1)


P2_HUD = (rgb5(31, 26, 8), rgb5(26, 10, 0))   # gold, its orange shade (P1's: white, azure)
BG_COLS, BG_ROWS = 16, 32
PAL_RAM = 0xE82000             # X68000 palette: graphic 256 words, then text/sprite 256


# --- Neo Geo tile formats ----------------------------------------------------------------------

def encode_c_tile(g):
    """16x16 grid -> (C1 64 B, C2 64 B). Blocks TR, BR, TL, BL; per 8-px row the bytes of planes
    0, 1 (C1) and 2, 3 (C2), leftmost pixel = bit 0 (neo-r-type tools/png2crom.py)."""
    c1, c2 = bytearray(), bytearray()
    for bx, by in ((8, 0), (8, 8), (0, 0), (0, 8)):
        for y in range(8):
            planes = [0, 0, 0, 0]
            for x in range(8):
                v = g[by + y][bx + x]
                for p in range(4):
                    planes[p] |= ((v >> p) & 1) << x
            c1 += bytes(planes[0:2])
            c2 += bytes(planes[2:4])
    return bytes(c1), bytes(c2)


def decode_c_tile(c1, c2):
    g = [[0] * 16 for _ in range(16)]
    i = 0
    for bx, by in ((8, 0), (8, 8), (0, 0), (0, 8)):
        for y in range(8):
            planes = (c1[i], c1[i + 1], c2[i], c2[i + 1])
            i += 2
            for x in range(8):
                g[by + y][bx + x] = sum(((planes[p] >> x) & 1) << p for p in range(4))
    return g


FIX_PAIRS = (0x10, 0x18, 0x00, 0x08)   # row y: pixel pairs (0,1) (2,3) (4,5) (6,7); left = low nibble


def encode_fix_tile(g):
    out = bytearray(FIX_TILE)
    for y in range(8):
        for pair, base in enumerate(FIX_PAIRS):
            out[base + y] = (g[y][2 * pair] & 15) | (g[y][2 * pair + 1] & 15) << 4
    return bytes(out)


def decode_fix_tile(t):
    g = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for pair, base in enumerate(FIX_PAIRS):
            g[y][2 * pair] = t[base + y] & 15
            g[y][2 * pair + 1] = t[base + y] >> 4
    return g


# --- palettes ----------------------------------------------------------------------------------

def merge_palettes(tile_sets, transparent=None):
    """Colour sets of tiles -> (palettes, assignment). Each palette is 16 entries: entry 0 None
    (transparent), then the X68000 indices it holds in ascending order, None for unused entries.
    `transparent` is the index that stays entry 0 (page 0: 0); every other colour, including
    the opaque nibble-0 ones, gets an entry 1-15. Greedy: the largest sets first, each into the
    palette it adds fewest colours to (that still fits 15), else a new one."""
    sets = [frozenset(s) - ({transparent} if transparent is not None else set()) for s in tile_sets]
    for s in sets:
        if len(s) > 15:
            raise ValueError("a tile has %d opaque colours (max 15)" % len(s))
    order = sorted(range(len(sets)), key=lambda i: (-len(sets[i]), sorted(sets[i])))
    pal_sets, assign = [], [None] * len(sets)
    for i in order:
        best = None
        for k, ps in enumerate(pal_sets):
            add = len(sets[i] - ps)
            if len(ps) + add <= 15 and (best is None or (add, k) < best):
                best = (add, k)
        if best is None:
            pal_sets.append(set(sets[i]))
            assign[i] = len(pal_sets) - 1
        else:
            pal_sets[best[1]] |= sets[i]
            assign[i] = best[1]
    pals = [[None] + sorted(ps) + [None] * (15 - len(ps)) for ps in pal_sets]
    return pals, assign


def neo_colour_tables():
    """(NEO_CHI, NEO_CLO): 256 words each, neo_colour(w) = NEO_CHI[w >> 8] | NEO_CLO[w & $FF]
    (the high byte's colour without the dark bit, which the low byte's I decides)."""
    return ([x68k_gfx.neo_colour(h << 8) & 0x7FFF for h in range(256)],
            [x68k_gfx.neo_colour(lo) for lo in range(256)])


def colour_lists(gmap, smap):
    """(PAL_XMAP, PAL_XLIST, most entries one colour feeds) from the maps X68000 colour index ->
    [[Neo palette, entry], ...] (graphic, text/sprite)."""
    xmap, xlist, most = [], [0], 0
    for i in range(512):
        entries = gmap[i] if i < 256 else smap[i - 256]
        if any(e == 0 for _, e in entries):
            raise SystemExit("error: X68000 colour $%03X feeds a Neo entry 0 (transparent)" % i)
        if not entries:
            xmap.append(0)
            continue
        xmap.append(2 * len(xlist))
        xlist += [len(entries)] + [(p * 16 + e) * 2 for p, e in entries]
        most = max(most, len(entries))
    return xmap, xlist, most


# --- gfx.inc ---------------------------------------------------------------------------------

def write_inc(path, equates, data, header):
    """equates: name -> value or (value, comment); data: label -> words (dc.w)."""
    lines = ["; " + h if h else ";" for h in header.splitlines()]
    lines.append("")
    for name, v in equates.items():
        v, note = v if isinstance(v, tuple) else (v, "")
        lines.append(("%-16s EQU $%04X" % (name, v)) + ("    ; " + note if note else ""))
    for label, words in data.items():
        lines += ["", "    even", label + ":"]
        for i in range(0, len(words), 8):
            lines.append("    dc.w    " + ",".join("$%04X" % w for w in words[i:i + 8]))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def read_inc(path):
    """gfx.inc -> (equates {name: int}, data {label: [words]})."""
    eq, data, cur = {}, {}, None
    with open(path) as f:
        text = f.read()
    for line in text.splitlines():
        line = line.split(";")[0].rstrip()
        m = re.match(r"^(\w+)\s+EQU\s+\$([0-9A-Fa-f]+)$", line)
        if m:
            eq[m.group(1)] = int(m.group(2), 16)
            continue
        m = re.match(r"^(\w+):$", line)
        if m:
            cur = data.setdefault(m.group(1), [])
            continue
        m = re.match(r"^\s+dc\.w\s+(.*)$", line)
        if m and cur is not None:
            cur += [int(w.strip().lstrip("$"), 16) for w in m.group(1).split(",")]
    return eq, data


# --- sources ---------------------------------------------------------------------------------

def load_sources(orig, preinit):
    """The art as the original holds it after its start-up: pcg (813 x 128 B), bg_pcg, bgtext,
    font, gfx_pal (256 graphic palette words), spr_pal (256 text/sprite words; block 0 = the text
    palette, colours 1-15 copied from block 2 by $6494)."""
    with open(os.path.join(preinit, "snapshot.json")) as f:
        snap = json.load(f)
    with open(os.path.join(preinit, "memory.bin"), "rb") as f:
        mem = f.read()
    xsp_dat = os.path.join(orig, "disk", "GAME", "XSP_DAT")
    game = os.path.join(orig, "disk", "GAME")
    (call,) = [c for c in snap["xsp_calls"] if c["name"] == "xsp_pcgdat_set"]
    pcg_at = call["args"]["pcg"]
    lo = snap["layout"]["memory_bin"][0]            # base-0 offset of memory.bin[0]
    (blk,) = [h for h in snap["heap"] if h["start"] <= pcg_at < h["start"] + h["size"]]
    size = sum(os.path.getsize(os.path.join(game, f)) for f in blk["files"])
    if size % 128 or size // 128 != SPR_TILE_COUNT:
        raise SystemExit("error: the PCG heap block's files hold %d bytes, not %d patterns" % (size, SPR_TILE_COUNT))
    pcg = mem[pcg_at - lo:pcg_at - lo + size]
    pal = {e["addr"]: e["value"] for e in snap["io_final"] if PAL_RAM <= e["addr"] < PAL_RAM + 0x400}
    if len(pal) != 512:
        raise SystemExit("error: the snapshot's io_final holds %d palette words, not 512" % len(pal))
    words = [pal[PAL_RAM + 2 * i] for i in range(512)]
    def rd(name):
        with open(os.path.join(xsp_dat, name), "rb") as f:
            return f.read()
    with open(os.path.join(preinit, "bgtext.bin"), "rb") as f:
        bgtext = f.read()
    return {"pcg": pcg, "bg_pcg": rd("BG_PCG.SP"), "bgtext": bgtext, "font": rd("SZ_TEXT.PCG"),
            "gfx_pal": words[:256], "spr_pal": words[256:]}


# --- conversion ------------------------------------------------------------------------------

def _flips(g):
    """(h, v) -> grid flipped that way."""
    return {(h, v): [(r[::-1] if h else list(r)) for r in (g[::-1] if v else g)]
            for h in (0, 1) for v in (0, 1)}


def convert_pages(pages):
    """Both pages -> (tiles [16x16 Neo-index grids], tile maps [page][col][row] = (tile, palette
    offset, h, v), palettes {page: [palette entries]})."""
    tiles, index = [], {}
    maps, pals = [], {}
    for n, page in enumerate(pages):
        grids = [[[[page[(row * 16 + y) * 256 + col * 16 + x] for x in range(16)] for y in range(16)]
                  for row in range(BG_ROWS)] for col in range(BG_COLS)]
        flat = [grids[c][r] for c in range(BG_COLS) for r in range(BG_ROWS)]
        sets = [frozenset(v for row in g for v in row) for g in flat]
        p, assign = merge_palettes(sets, transparent=0 if n == 0 else None)
        pals[n] = p
        m = [[None] * BG_ROWS for _ in range(BG_COLS)]
        for i, g in enumerate(flat):
            col, row = divmod(i, BG_ROWS)
            entries = p[assign[i]]
            neo = [[0 if (n == 0 and v == 0) else entries.index(v) for v in r] for r in g]
            hit = None
            for (h, v), f in _flips(neo).items():
                key = tuple(map(tuple, f))
                if key in index:
                    hit = (index[key], h, v)
                    break
            if hit is None:
                index[tuple(map(tuple, neo))] = len(tiles)
                tiles.append(neo)
                hit = (len(tiles) - 1, 0, 0)
            m[col][row] = (hit[0], assign[i], hit[1], hit[2])
        maps.append(m)
    return tiles, maps, pals


def p2_palette(words):
    """Player 2's copy of a sprite palette (16 Neo Geo words): entries 2-15 a third of a turn
    round in hue -- red to blue, green to red, blue to green: each channel's five bits moved to
    the next, the shared dark bit kept, so exact -- entry 0 (transparent) and 1 as they are: colour
    1 is the one the game's ramps change ($6AB8: blocks 1-11); P2's keeps its static colour, so
    Pal_Build feeds none of P2's palettes and costs one player nothing."""
    def turn(w):
        r = (w >> 8) & 15, (w >> 14) & 1
        g = (w >> 4) & 15, (w >> 13) & 1
        b = w & 15, (w >> 12) & 1
        return (w & 0x8000) | g[1] << 14 | b[1] << 13 | r[1] << 12 | g[0] << 8 | b[0] << 4 | r[0]
    return list(words[:2]) + [turn(w) for w in words[2:16]]


def p2_glyph(g):
    """A font glyph (8 x 8 colour indices) in player 2's HUD colours: P2_FONT_MAP's entries."""
    return [[P2_FONT_MAP[v] for v in row] for row in g]


def strips(strip):
    """The side strips (tools/mkstrips.py build() of the image or path `strip`): (tiles from
    STRIP_TILE_BASE, {palette: 16 words}, STRIP_MAP: the fix words of columns 0-3 then 36-39,
    each its rows STRIP_ROW..), as Text_Init writes them."""
    import mkstrips                                # (it imports this module)
    tl, tr, p10, p11, fixmap = mkstrips.build(strip)
    if mkstrips.TILE_BASE != STRIP_TILE_BASE or mkstrips.PALS != STRIP_PALS or \
            (mkstrips.W, mkstrips.H) != (8 * STRIP_COLS, 8 * STRIP_ROWS):
        raise SystemExit("error: tools/mkstrips.py's layout is not mkgfx's")
    words = [fixmap[side * 112 + r * STRIP_COLS + c] for side in (0, 1) for c in range(STRIP_COLS)
             for r in range(STRIP_ROWS)]
    return tl + tr, dict(zip(STRIP_PALS, (p10, p11))), words


def convert(src, strip):
    pats = x68k_gfx.decode_pcg(src["pcg"])
    pages = x68k_gfx.build_pages(src["bg_pcg"], src["bgtext"])
    bg_tiles, maps, bg_pals = convert_pages(pages)
    if len(bg_pals[1]) != 1:
        raise SystemExit("error: page 1 needs %d palettes, not 1" % len(bg_pals[1]))
    if BG_TILE_BASE + len(bg_tiles) > FONT_SPR_BASE:
        raise SystemExit("error: %d background tiles overflow tile $%04X" % (len(bg_tiles), FONT_SPR_BASE))
    n0 = len(bg_pals[0])
    pal_no = {0: [PAL_BG0_BASE + k for k in range(n0)], 1: [PAL_BG1]}
    if PAL_BG0_BASE + n0 > PAL_BACKDROP:
        raise SystemExit("error: %d page 0 palettes" % n0)

    # C-ROM
    c1, c2 = bytearray((FREE_TILE_END + 1) * C_TILE), bytearray((FREE_TILE_END + 1) * C_TILE)
    glyphs = x68k_gfx.decode_text_font(src["font"])
    font_spr = [[[g[y][x] if x < 8 and y < 8 else 0 for x in range(16)] for y in range(16)]
                for g in glyphs]
    for t, g in [(SPR_TILE_BASE + i, p) for i, p in enumerate(pats)] + \
                [(BG_TILE_BASE + i, g) for i, g in enumerate(bg_tiles)] + \
                [(FONT_SPR_BASE + ch, g) for ch, g in enumerate(font_spr)]:
        a, b = encode_c_tile(g)
        c1[t * C_TILE:(t + 1) * C_TILE] = a
        c2[t * C_TILE:(t + 1) * C_TILE] = b

    # S-ROM
    s1 = bytearray(S1_SIZE)
    for ch, g in enumerate(glyphs):
        t = FONT_FIX_BASE + ch
        s1[t * FIX_TILE:(t + 1) * FIX_TILE] = encode_fix_tile(g)
    if any(v in P2_FONT_ENTRIES for g in glyphs for r in g for v in r):
        raise SystemExit("error: the font uses palette 0's entry 1 or 5 (player 2's HUD colours)")
    if FONT_FIX_BASE + len(glyphs) > P2_FONT_BASE or P2_FONT_BASE + P2_FONT_COUNT > 0xFF:
        raise SystemExit("error: player 2's font copies overlap the font or tile $FF")
    for ch in range(P2_FONT_COUNT):
        t = P2_FONT_BASE + ch
        s1[t * FIX_TILE:(t + 1) * FIX_TILE] = encode_fix_tile(p2_glyph(glyphs[ch]))
    # the side strips (Presentation Task 5)
    strip_tiles, strip_pal, strip_map = strips(strip)
    n_strip = len(strip_tiles) // FIX_TILE
    fix_free = STRIP_TILE_BASE + n_strip
    if fix_free > FIX_FREE_END + 1:
        raise SystemExit("error: %d strip tiles overflow the S-ROM" % n_strip)
    s1[STRIP_TILE_BASE * FIX_TILE:fix_free * FIX_TILE] = strip_tiles

    # palette RAM: text, sprite blocks, background
    black = x68k_gfx.neo_colour(0)
    ram = [black] * (256 * 16)
    gmap = {i: [] for i in range(256)}
    smap = {i: [] for i in range(256)}
    for blk in range(16):
        for c in range(1, 16):
            if PAL_SPR_BASE + blk in STRIP_PALS and c >= 2:
                continue                                # (the strips' colours, below)
            if PAL_SPR_BASE + blk == PAL_TEXT and c in P2_FONT_ENTRIES:
                continue                                # (player 2's HUD colours, below)
            ram[(PAL_SPR_BASE + blk) * 16 + c] = x68k_gfx.neo_colour(src["spr_pal"][blk * 16 + c])
            smap[blk * 16 + c].append([PAL_SPR_BASE + blk, c])
    # the strips' colours: entries 2-15 (one the art does not use black, never $0000); every
    # pixel of the strips an entry 2-15 whose word is not $0000 (a word a display may take as
    # transparent: tools/mkstrips.py): the strips opaque
    for p, words in strip_pal.items():
        for e in range(2, 16):
            ram[p * 16 + e] = words[e] or black
    for w in strip_map:
        t = (w & 0xFFF) * FIX_TILE
        for row in decode_fix_tile(s1[t:t + FIX_TILE]):
            for i in row:
                if i < 2 or (w >> 12) not in STRIP_PALS or ram[(w >> 12) * 16 + i] == 0:
                    raise SystemExit("error: a strip pixel of fix word $%04X is not opaque (entry %d)"
                                     % (w, i))
    for n in (0, 1):
        for k, entries in enumerate(bg_pals[n]):
            for e, i in enumerate(entries):
                if i is not None:
                    ram[pal_no[n][k] * 16 + e] = x68k_gfx.neo_colour(src["gfx_pal"][i])
                    gmap[i].append([pal_no[n][k], e])
    ram[PAL_BACKDROP * 16 + 15] = black
    # player 2's: its sprite palettes, its HUD colours (fed by no X68000 colour)
    taken = {PAL_BG1, PAL_BACKDROP} | set(pal_no[0]) | {PAL_SPR_BASE + b for b in range(16)}
    for blk in P2_BLOCKS:
        n = PAL_P2_BASE + blk
        if n in taken:
            raise SystemExit("error: player 2's palette %d is taken" % n)
        ram[n * 16:n * 16 + 16] = p2_palette(ram[(PAL_SPR_BASE + blk) * 16:(PAL_SPR_BASE + blk) * 16 + 16])
    for e, w in zip(P2_FONT_ENTRIES, P2_HUD):
        ram[PAL_TEXT * 16 + e] = w

    # tile maps; the colour ramps' map and the colour conversion (src/shim/palette.asm)
    xmap, xlist, xmax = colour_lists(gmap, smap)
    chi, clo = neo_colour_tables()
    data = {"PAL_XMAP": xmap, "PAL_XLIST": xlist, "NEO_CHI": chi, "NEO_CLO": clo,
            "STRIP_MAP": strip_map}
    for n, name in ((0, "BG0_TILEMAP"), (1, "BG1_TILEMAP")):
        words = []
        for col in range(BG_COLS):
            for row in range(BG_ROWS):
                t, k, h, v = maps[n][col][row]
                tno = BG_TILE_BASE + t
                words += [tno & 0xFFFF, pal_no[n][k] << 8 | (tno >> 16) << 4 | v << 1 | h]
        data[name] = words

    equates = {
        "TILE_BLANK": (TILE_BLANK, "C-ROM tile 0: blank (transparent)"),
        "SPR_TILE_BASE": (SPR_TILE_BASE, "C-ROM tile of XSP pattern 0 (tile = SPR_TILE_BASE + pt)"),
        "SPR_TILE_COUNT": (len(pats), "XSP patterns 0-812"),
        "BG_TILE_BASE": (BG_TILE_BASE, "the background pages' distinct tiles (flips folded)"),
        "BG_TILE_COUNT": (len(bg_tiles), ""),
        "FONT_SPR_BASE": (FONT_SPR_BASE, "the font as sprite tiles: character ch at FONT_SPR_BASE + ch,"),
        "FONT_SPR_COUNT": (FONT_SPR_COUNT, "its glyph top-left, the rest transparent (palette PAL_TEXT)"),
        "FREE_TILE_BASE": (FREE_TILE_BASE, "free C-ROM tiles ..."),
        "FREE_TILE_END": (FREE_TILE_END, "... to here, inclusive (1 MB chips)"),
        "BG_COLS": (BG_COLS, "tile map: BG_COLS sprites of BG_ROWS tiles, column-major"),
        "BG_ROWS": (BG_ROWS, "each entry: tile word, attribute word (SCB1)"),
        "FONT_FIX_BASE": (FONT_FIX_BASE, "fix tile of text character 0 (tile = base + code, ASCII order)"),
        "FONT_FIX_COUNT": (FONT_FIX_COUNT, "characters 0-127; 16x16 glyph g = chars 4g..4g+3 (TL BL TR BR)"),
        "STRIP_TILE_BASE": (STRIP_TILE_BASE, "the side strips' fix tiles, palettes 10/11 entries 2-15"),
        "STRIP_TILE_COUNT": (n_strip, "this many ($80-$17F below them blank; $FF the BIOS border tile)"),
        "STRIP_COLS": (STRIP_COLS, "STRIP_MAP: fix columns 0 .. STRIP_COLS - 1, then 40 - STRIP_COLS .. 39,"),
        "STRIP_ROW": (STRIP_ROW, "each its rows STRIP_ROW .. STRIP_ROW + STRIP_ROWS - 1 (the 224"),
        "STRIP_ROWS": (STRIP_ROWS, "lines), one fix word each"),
        "FIX_FREE_BASE": (fix_free, "free fix tiles ..."),
        "FIX_FREE_END": (FIX_FREE_END, "... to here, inclusive"),
        "PAL_TEXT": (PAL_TEXT, "fix palette of the text plane (X68000 text palette)"),
        "PAL_SPR_BASE": (PAL_SPR_BASE, "sprite palette = PAL_SPR_BASE + X68000 colour block (1-15)"),
        "PAL_BG1": (PAL_BG1, "graphic page 1 (block A, opaque)"),
        "PAL_BG0_BASE": (PAL_BG0_BASE, "graphic page 0: merged palettes ..."),
        "PAL_BG0_COUNT": (n0, "... this many"),
        "PAL_BACKDROP": (PAL_BACKDROP, "entry 15 = the backdrop colour"),
        "PAL_XMAX": (xmax, "the most Neo entries one X68000 colour feeds (PAL_XMAP)"),
        "PAL_P2_BASE": (PAL_P2_BASE, "player 2's sprite palettes: + block (2, 5, 9: attribute bit 13)"),
        "P2_FONT_BASE": (P2_FONT_BASE, "player 2's HUD font: fix tile P2_FONT_BASE + code, palette 0"),
        "P2_FONT_COUNT": (P2_FONT_COUNT, "codes 0 .. this - 1 (entries 1 and 5: P2's colours)"),
    }
    pmap = {
        "graphic": {"0x%02x" % i: v for i, v in gmap.items()},
        "sprite": {"0x%02x" % i: v for i, v in smap.items()},
        "neo": {"text": PAL_TEXT, "sprite_base": PAL_SPR_BASE, "bg1": PAL_BG1, "bg0": pal_no[0],
                "p2_base": PAL_P2_BASE},
    }
    stats = {"sprites": len(pats), "bg_tiles": len(bg_tiles), "strip_tiles": n_strip,
             "bg_tiles_page": [len({maps[n][c][r][0] for c in range(BG_COLS) for r in range(BG_ROWS)}) for n in (0, 1)],
             "bg0_palettes": n0,
             "bg0_colours": [sum(e is not None for e in p[1:]) for p in bg_pals[0]]}
    return {"c1": bytes(c1), "c2": bytes(c2), "s1": bytes(s1), "equates": equates, "data": data,
            "palettes": struct.pack(">%dH" % len(ram), *ram), "palette_map": pmap, "stats": stats}


HEADER = """generated by tools/mkgfx.py from the original's art (build/preinit, XSP_DAT) and the side
strips' generated art (art/strips/strip.png) - do not edit
Chourensha 68K graphics on the Neo Geo: C-ROM/S-ROM layout, palette numbers, background tile maps.
C-ROM (c1/c2.bin): 0 blank | SPR_TILE_BASE.. XSP patterns | BG_TILE_BASE.. background tiles |
  FONT_SPR_BASE.. the font as sprite tiles | FREE_TILE_BASE..FREE_TILE_END free.
S-ROM (s1.bin): FONT_FIX_BASE.. the text font (code = tile) | P2_FONT_BASE.. player 2's HUD font
  (codes 0-$7E) | $FF-$17F blank | STRIP_TILE_BASE.. the side strips' tiles (art/strips/strip.png,
  tools/mkstrips.py) | FIX_FREE_BASE.. free.
Palettes (palettes.bin): 0 text (fix; entries 1 and 5 player 2's HUD colours) | 1-15 sprite blocks
  (10 and 11: entries 2-15 the strips' colours) | PAL_BG1 | PAL_BG0_BASE.. | PAL_P2_BASE + 2, 5, 9
  player 2's sprites | 255/15 backdrop.
STRIP_MAP: the strips' fix words, column by column (0-3, then 36-39), rows STRIP_ROW.. (Text_Init).
PAL_XMAP / PAL_XLIST: X68000 colour -> the palette RAM offsets it feeds; NEO_CHI / NEO_CLO: the colour
conversion by bytes (tools/mkgfx.py's docstring)."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--orig", default="build/orig")
    ap.add_argument("--preinit", default="build/preinit")
    ap.add_argument("--out", default="build/gfx")
    ap.add_argument("--strip", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                                    "art", "strips", "strip.png"),
                    help="the side strips' art (32x224 mode P: tools/mkstrips.py reduce)")
    a = ap.parse_args()
    r = convert(load_sources(a.orig, a.preinit), a.strip)
    os.makedirs(a.out, exist_ok=True)
    for name in ("c1", "c2", "s1"):
        with open(os.path.join(a.out, name + ".bin"), "wb") as f:
            f.write(r[name])
    with open(os.path.join(a.out, "palettes.bin"), "wb") as f:
        f.write(r["palettes"])
    with open(os.path.join(a.out, "palette_map.json"), "w") as f:
        json.dump(r["palette_map"], f, indent=1)
    write_inc(os.path.join(a.out, "gfx.inc"), r["equates"], r["data"], HEADER)   # last: stands for all
    s = r["stats"]
    print("gfx: %d sprite tiles, %d background tiles (page 0 %d, page 1 %d), page 0 palettes %d "
          "(colours %s), %d font tiles, %d strip tiles -> %s" % (
              s["sprites"], s["bg_tiles"], s["bg_tiles_page"][0], s["bg_tiles_page"][1],
              s["bg0_palettes"], s["bg0_colours"], FONT_FIX_COUNT, s["strip_tiles"], a.out))


if __name__ == "__main__":
    main()
