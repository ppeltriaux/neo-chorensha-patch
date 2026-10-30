"""Merge RAM-census scenarios (tests/x68k/ramcensus.lua output) and judge the 64 KB gate.

  .venv/bin/python -I tools/census_report.py --game-dir build/orig/disk/GAME --orig-dir build/orig \\
      --out data/census.json --md docs/notes/ram-census.md build/census/scen_*.json

Each scenario JSON has regions (game-relative start, size, kind) with four bitmaps, base64,
bit j of byte k = byte start+8k+j: written / read during init, written / read after init
(init ends at the first title frame), plus per-writer-class bitmaps of the live bytes. The
merge ORs them. Per region: live = written after init; ROM candidate = read after init and
never written after it (tables loaded or set up at init); init only = touched only during init;
untouched = the rest.

Footprint: the memory is split into objects at every relocation target (the addresses the code
and data refer to; sz2.bin + sz2.json from --orig-dir), heap blocks into their 12-byte malloc
header and their data. An object counts whole when any byte of it is written after init. Each
live object has an owner: "xsp" (XSP's text variables and bss, the PCG_ALT work table: replaced
by the shim, inside the port reserve), "rom" (all its live bytes are reloaded file data), "drop"
(the XC stdio buffer and malloc headers: file I/O and malloc go) or "counted" (the game's state).
Two totals: "XSP bss kept" (every live object) and "XSP bss replaced by the shim" (the counted
objects only: the spec's model). The stack is left out of both (its need is the measured depth,
judged against the stack's own reserve). Verdict: INCOMPLETE if any of REQUIRED_EVENTS was not
seen in any scenario; else STOP when the spec-model total exceeds BUDGET or the stack depth
exceeds STACK_RESERVE; else WARN when the stack depth is within STACK_WARN_MARGIN of the
reserve; else GO.

The census is written frozen (freeze: every bitmap as runs of set bits, no base64; data/census.json,
tracked, read by tools/layout.py through load); heap block dumps are named relative to the
scenarios' folder (build/census), wherever --out is.

With --orig-dir and the end-of-run memory dumps, text and data objects that the program wrote
(after init, or during init: the dump differs from sz2.bin once relocation is undone) are listed.
"""
import argparse
import base64
import bisect
import glob
import json
import os
import re
import sys

# 64 KB work RAM ($100000-$10FFFF) - BIOS work area ($10F300-$10FFFF, 3,328 B) - port reserve
# 12 KB (sprite list shadow, sound queue, view state, shim scratch) - stack 2 KB.
BUDGET = 65536 - 3328 - 12 * 1024 - 2048
STACK_RESERVE = 2048
STACK_WARN_MARGIN = 256      # WARN once the measured depth is within this of the reserve
STACK_PAIRS = {"min_written_after_init": "min_written_any_pc",
               "min_written_by_program": "min_written_by_program_pc"}
REQUIRED_EVENTS = ["boss_killed", "bomb_used", "player_died", "continue_taken", "bonus_stage",
                   "game_over"]
FRAME_EVENTS = {"past_bonus", "finished", "loop2_stage1_boss", "loop2_stage2"}  # frames: earliest
MAX_EVENTS = {"loop2_stage1_frames"}                     # durations: the longest
BITMAPS = ["written_during_init", "read_during_init", "written_after_init", "read_after_init"]
WRITER_CLASSES = ["xsp", "game", "lib", "other"]
HEAP_HEADER = 12             # XC malloc block header: prev, end, next
# XSP's own memory (game-relative): its text with its work variables, and its bss (see NOTES).
# XSP_TEXT_END: the end of XSP's code and text variables ($0-$1575, inventory: link order), the
# one source for tools/preinit.py's XSP_TEXT and tools/layout.py's XSP_TEXT_END.
XSP_TEXT_END = 0x1576
XSP_RANGES = [(0x0, XSP_TEXT_END), (0x17D98, 0x1DB0E)]
XSP_HEAP_LABEL = "PCG_ALT"   # heap block content labels (size_label) of XSP's work table
STDIO_HEAP_LABEL = "stdio buffer"
CODE_CLASSES = [(0x0, XSP_TEXT_END, "xsp"), (XSP_TEXT_END, 0x144D8, "game"), (0x144D8, 0x1750A, "lib")]
OWNERS = ["counted", "xsp", "rom", "drop"]
# Variables written only on paths the autoplay does not take (docs/notes/game-globals.md).
PATH_VARS = [(0x221F8, "muteki"), (0x221FA, "stage"), (0x221F6, "acchoh"), (0x221F0, "debug")]

# Known arrays (game-relative), to label the biggest live runs. Sources: docs/notes/game-globals.md,
# docs/notes/inventory.md, the XC startup ($14B04) and this census.
KNOWN = [
    (0x278A6, 0x4000, "char_table: object array, 128 x $80 (game)"),
    (0x27896, 0x10, "char_table free bitmap (game)"),
    (0x2B8B6, 0x370, "XC stdio FILE table (cleared by the startup)"),
    (0x14B6, XSP_TEXT_END - 0x14B6, "XSP work variables inside its text"),
    (0x2650, 0x27E0 - 0x2650, "game tables inside text: cleared by $2636; $25E0 tests 32 x 8-byte "
                              "player-shot boxes from $27D8 down"),
    (0x1FF52, 0x100, "sam.bg0 buffer: fread by $6512 at every play-loop entry"),
    (0x20052, 0x100, "sam.bg1 buffer: fread by $6512 at every play-loop entry"),
    (0x20152, 0x2000, "sam.par buffer: fread by $6512 at every play-loop entry"),
    (0x17D98, 0x1DB0E - 0x17D98, "XSP bss (modified XSP 1.99; layout differs from the 1.99 source)"),
    (0x1606, 8, "MCDRV wrapper variables (game text)"),
    (0x193A, 0xC, "text renderer state (game text, stored by $160E)"),
    (0x179B8, 4, "MCDRV detect result (data)"),
    (0x26992, 0xE80, "game array, 29 x $80 (writes at the same offsets in each entry)"),
]

# Facts from the binary behind the region layout (relocations and disassembly; see the notes).
NOTES = [
    "Layout: text $0-$17509 (XSP $0-$1575, game $1576-$144D7, XC library $144D8-$17509), data "
    "$1750A-$17D8F, bss $17D90-$2C097. Every relocated XSP-text reference into bss lands in "
    "$17D98-$1D80E (13 targets) and every game/library reference in $1DB0E-$2C098, so XSP's bss is "
    "$17D98-$1DB0D (23,926 B; the last XSP target $1D80E opens a buffer that ends where the game's "
    "first variable starts). XSP 1.99's own bss is $63F8 (25,592 B): this build's layout differs. "
    "$17D90-$17D97 is referenced by nothing. Game bss $1DB0E-$2B8AD, XC library bss $2B8AE-$2C097.",
    "The C stack is not in bss: the XC startup ($14B04) runs on sp = bss end only until it moves "
    "sp ($14C12) to its own area above the program (bss end + $400 + stack size, the size from "
    "$14F06 = $10000), then puts the malloc arena after it (head at [$2BC4C]).",
    "Heap: the game grows its Human68k block to all of RAM (`_SETBLOCK` at $14F80) and every "
    "file buffer is an XC malloc block (12-byte headers: prev, end with $FE in the high byte when "
    "free, next); there is no DOS `_MALLOC` in the image, so the Human68k memory chain holds one "
    "block for the whole program.",
    "File loads after init: the play-loop entry calls $6512 at every game start and continue: it "
    "reads XSP_DAT\\BG_PCG.SP into PCG RAM through a 1 KB stack buffer and sam.bg0, sam.bg1, "
    "sam.par into $1FF52 (256), $20052 (256), $20152 ($2000) with fread; $3510/$34EA only store "
    "pointers to them. The 1,036-byte heap block written by DOS (writer class other) is the "
    "stdio buffer of those freads. None of this exists on the Neo Geo (data read from ROM).",
    "The stack depth includes IOCS/DOS frames (the game runs in supervisor mode, so trap #15, "
    "F-line DOS calls and interrupts push on the C stack). The program-only depth counts pushes "
    "by code in the image (XSP, game, XC library, and CPU exception frames taken while it runs); "
    "it still sits on top of whatever IOCS frames were below it.",
    "One sample per scenario: runs with the same seed are not frame-identical (the game "
    "itself varies between runs), so each scenario is one play-through, not a fixed trace; a path "
    "the autoplay did not take leaves its bytes untouched or read-only here.",
]


def decode_bitmap(b64, size):
    """Bitmap string -> int, bit i = byte offset i."""
    raw = base64.b64decode(b64) if b64 else b""
    v = int.from_bytes(raw, "little")
    return v & ((1 << size) - 1)


def encode_bitmap(bits, size):
    return base64.b64encode(bits.to_bytes((size + 7) // 8, "little")).decode()


def bit_runs(bits):
    """Set bits -> [[start, length], ...] in offset order (bit i = byte offset i)."""
    runs = []
    i = 0
    while bits >> i:
        rest = bits >> i
        i += (rest & -rest).bit_length() - 1         # the next set bit
        x = bits >> i
        n = (x ^ (x + 1)).bit_length() - 1         # the ones from there
        runs.append([i, n])
        i += n
    return runs


def _region_bitmaps(r):
    """The keys of region `r` that hold a bitmap: (dict, key) pairs."""
    keys = [(r, k) for k in BITMAPS + ["file_data"] if k in r]
    return keys + [(r["writers"], c) for c in r.get("writers", {})]


def freeze(census):
    """The census as data/census.json holds it: every region bitmap (the four BITMAPS, file_data,
    writers.<class>) as runs [[start, length], ...] of set bits, offsets within the region: the
    base64 bitmaps' bytes hold runs of the original program's, the runs are numbers."""
    out = json.loads(json.dumps(census))
    for r in out.get("regions", []):
        for d, k in _region_bitmaps(r):
            if isinstance(d[k], str):
                d[k] = bit_runs(decode_bitmap(d[k], r["size"]))
    return out


def thaw(frozen):
    """freeze's inverse: runs back to base64 bitmaps (a census already in base64 passes as is)."""
    out = json.loads(json.dumps(frozen))
    for r in out.get("regions", []):
        for d, k in _region_bitmaps(r):
            if isinstance(d[k], list):
                d[k] = encode_bitmap(sum(((1 << n) - 1) << i for i, n in d[k]), r["size"])
    return out


def load(path):
    """A census file (data/census.json, frozen, or a base64 one) as the readers take it."""
    with open(path) as f:
        return thaw(json.load(f))


def write(path, census):
    """The census frozen to `path` (data/census.json: make census)."""
    with open(path, "w") as f:
        json.dump(freeze(census), f, indent=1)


def popcount(v):
    return bin(v).count("1")


def live_runs(bits, size, gap=16):
    """Runs of set bits, merging runs separated by fewer than `gap` clear bytes:
    [(offset, span, set_bytes)] in offset order."""
    runs = []
    i = 0
    cur = None
    while bits >> i:
        if bits >> i & 1:
            # find the end of this run of ones
            j = i
            while bits >> j & 1:
                j += 1
            if cur and i - cur[1] < gap:
                cur[1] = j
                cur[2] += j - i
            else:
                if cur:
                    runs.append((cur[0], cur[1] - cur[0], cur[2]))
                cur = [i, j, j - i]
            i = j
        else:
            # skip clear bits fast
            rest = bits >> i
            i += (rest & -rest).bit_length() - 1
    if cur:
        runs.append((cur[0], cur[1] - cur[0], cur[2]))
    return runs


def _region_bits(r):
    size = r["size"]
    out = {k: decode_bitmap(r.get(k, ""), size) for k in BITMAPS}
    out["writers"] = {c: decode_bitmap(b, size) for c, b in r.get("writers", {}).items()}
    return out


def merge(scens):
    """OR the scenarios' bitmaps region by region; sum their event counts."""
    if not scens:
        raise ValueError("no scenarios")
    regions = {}
    order = []
    for s in scens:
        for r in s["regions"]:
            key = r["name"]
            if key in regions:
                m = regions[key]
                if {m["kind"], r["kind"]} == {"heap", "heap_free"}:
                    m["kind"] = "heap"        # a block used in one scenario, free in another
                if (m["start"], m["size"], m["kind"]) != (r["start"], r["size"], r["kind"]) and \
                        not (m["kind"] == "heap" and r["kind"] == "heap_free"):
                    raise ValueError("region %s differs between scenarios: %s/%s vs %s/%s" % (
                        key, hex(m["start"]), m["size"], hex(r["start"]), r["size"]))
                b = _region_bits(r)
                for k in BITMAPS:
                    m["_bits"][k] |= b[k]
                for c, v in b["writers"].items():
                    m["_bits"]["writers"][c] = m["_bits"]["writers"].get(c, 0) | v
                for k in ("content",):
                    if r.get(k) and not m.get(k):
                        m[k] = r[k]
            else:
                m = {k: v for k, v in r.items() if k not in BITMAPS and k != "writers"}
                m["_bits"] = _region_bits(r)
                regions[key] = m
                order.append(key)
    out_regions = []
    for key in sorted(order, key=lambda k: (regions[k]["start"], k)):
        m = regions[key]
        b = m.pop("_bits")
        for k in BITMAPS:
            m[k] = encode_bitmap(b[k], m["size"])
        m["writers"] = {c: encode_bitmap(v, m["size"]) for c, v in sorted(b["writers"].items()) if v}
        out_regions.append(m)

    events = {}
    for s in scens:
        for k, v in s.get("events_seen", {}).items():
            if isinstance(v, bool) or v is None:
                continue
            if k in FRAME_EVENTS and isinstance(v, (int, float)):
                events[k] = min(events.get(k, v), v)
            elif k in MAX_EVENTS and isinstance(v, (int, float)):
                events[k] = max(events.get(k, v), v)
            elif isinstance(v, (int, float)):
                events[k] = events.get(k, 0) + v
            elif isinstance(v, dict):
                d = events.setdefault(k, {})
                for kk, vv in v.items():
                    d[kk] = min(d.get(kk, vv), vv)
    blocks = {}
    for s in scens:
        for hb in s.get("heap_blocks", []):
            k = (hb["start"], hb["size"])
            e = blocks.setdefault(k, dict(hb, scenarios=[]))
            e["scenarios"].append(s.get("scenario", "?"))
            e["used"] = bool(e.get("used")) or bool(hb.get("used"))
            for f in ("content", "dump"):
                if hb.get(f) and not e.get(f):
                    e[f] = hb[f]
    stack = {}
    paired = set(STACK_PAIRS.values())
    for s in scens:
        st = s.get("stack") or {}
        for k, v in st.items():
            if v is None or k in paired:
                continue
            if k.startswith("min"):
                if k not in stack or v < stack[k]:
                    stack[k] = v
                    if k in STACK_PAIRS:      # the pc that wrote this minimum comes with it
                        stack[STACK_PAIRS[k]] = st.get(STACK_PAIRS[k])
            else:
                stack.setdefault(k, v)
    bases = sorted({s.get("program_base") for s in scens})
    return {
        "program_base": bases[0] if len(bases) == 1 else bases,
        "scenarios": [s.get("scenario", "?") for s in scens],
        "scenario_info": [{k: s.get(k) for k in ("scenario", "status", "frames", "init_end_frame",
                                                   "options", "events_seen", "stack", "stray",
                                                   "config_writes")} for s in scens],
        "regions": out_regions,
        "heap_blocks": [blocks[k] for k in sorted(blocks)],
        "events_seen": events,
        "stack": stack,
    }


def _label(start, span):
    names = [n for a, size, n in KNOWN if a < start + span and start < a + size]
    return "; ".join(names)


def reloc_targets(image, relocs):
    """The addresses (base-0) held by the relocated longwords: where objects start."""
    return sorted({int.from_bytes(image[o:o + 4], "big") for o in relocs})


def segment(start, size, targets):
    """Split [start, start + size) at every target strictly inside it: [(start, size)]."""
    i = bisect.bisect_right(targets, start)
    j = bisect.bisect_left(targets, start + size)
    cuts = [start] + list(targets[i:j]) + [start + size]
    return [(a, b - a) for a, b in zip(cuts, cuts[1:]) if b > a]


def region_objects(r, targets):
    """Objects of a region: heap blocks = malloc header + data; others split at the targets
    (no targets known: the whole region is one object)."""
    start, size = r["start"], r["size"]
    if r["kind"] in ("heap", "heap_free") and size > HEAP_HEADER:
        return [(start, HEAP_HEADER), (start + HEAP_HEADER, size - HEAP_HEADER)]
    if targets is None:
        return [(start, size)]
    return segment(start, size, targets)


def _code_class(start):
    for a, b, name in CODE_CLASSES:
        if a <= start < b:
            return name
    return None


def _owner(r, start, live, fd):
    """Who keeps a live object on the Neo Geo (see OWNERS and the module doc)."""
    content = r.get("content") or ""
    if r["kind"] in ("heap", "heap_free"):
        if start == r["start"]:
            return "drop"                      # malloc header
        if XSP_HEAP_LABEL in content:
            return "xsp"
        if STDIO_HEAP_LABEL in content:
            return "drop"
    if any(a <= start < b for a, b in XSP_RANGES):
        return "xsp"
    if fd and not live & ~fd:
        return "rom"
    return "counted"


def _is_rom_candidate(census, addr):
    """Byte `addr` read after init and never written after it (any non-stack region)."""
    for r in census["regions"]:
        if r["kind"] != "stack" and r["start"] <= addr < r["start"] + r["size"]:
            o = addr - r["start"]
            wa = decode_bitmap(r.get("written_after_init", ""), r["size"])
            ra = decode_bitmap(r.get("read_after_init", ""), r["size"])
            return bool(ra >> o & 1) and not wa >> o & 1
    return False


def footprint(census):
    """Live objects (any byte written after init) and the totals per owner."""
    targets = census.get("reloc_targets")
    objects = []
    by_region = []
    for r in census["regions"]:
        if r["kind"] == "stack":
            continue
        size = r["size"]
        b = _region_bits(r)
        wa = b["written_after_init"]
        fd = decode_bitmap(r["file_data"], size) if r.get("file_data") else 0
        row = {"name": r["name"], "kind": r["kind"], "start": r["start"], "live": popcount(wa),
               "objects": 0, "bytes": 0}
        row.update({o: 0 for o in OWNERS})
        if wa:
            for start, n in region_objects(r, targets):
                m = ((1 << n) - 1) << (start - r["start"])
                live = wa & m
                if not live:
                    continue
                owner = _owner(r, start, live, fd & m)
                ws = {c: popcount(v & m) for c, v in b["writers"].items()}
                header = r["kind"] in ("heap", "heap_free") and start == r["start"]
                objects.append({"region": r["name"], "start": start, "size": n, "live": popcount(live),
                                "owner": owner, "writers": {c: k for c, k in ws.items() if k},
                                "label": "XC malloc header" if header else
                                         (_label(start, n) or (r.get("content") or ""))})
                row["objects"] += 1
                row["bytes"] += n
                row[owner] += n
        by_region.append(row)
    tot = {o: sum(x["size"] for x in objects if x["owner"] == o) for o in OWNERS}
    return dict(tot, kept=sum(tot.values()), objects=objects, by_region=by_region,
                targets=targets is not None)


def changed_since_load(mem, image, relocs, base):
    """Bitmap over the image of the bytes of `mem` (the image's memory, loaded at `base`) that
    differ from the base-0 `image` once the relocated longwords are moved back to base 0."""
    m = bytearray(mem[:len(image)])
    for o in relocs:
        v = (int.from_bytes(m[o:o + 4], "big") - base) & 0xFFFFFFFF
        m[o:o + 4] = v.to_bytes(4, "big")
    out = 0
    for i, (x, y) in enumerate(zip(m, image)):
        if x != y:
            out |= 1 << i
    return out


def text_data_writes(census, changed):
    """Text and data objects the program writes: written after init ("live") or changed by init
    and never written after it ("init_changed", from `changed`, a bitmap over the image)."""
    targets = census.get("reloc_targets")
    rows = []
    for r in census["regions"]:
        if r["kind"] not in ("text", "data"):
            continue
        wa = decode_bitmap(r.get("written_after_init", ""), r["size"])
        ch = (changed >> r["start"]) & ((1 << r["size"]) - 1)
        for start, n in region_objects(r, targets):
            m = ((1 << n) - 1) << (start - r["start"])
            live, init = popcount(wa & m), popcount(ch & ~wa & m)
            if live or init:
                rows.append({"region": r["name"], "start": start, "size": n, "live": live,
                             "init_changed": init,
                             "owner": (_code_class(start) if r["kind"] == "text" else None) or r["kind"],
                             "label": _label(start, n)})
    return rows


def analyze(census, budget=BUDGET):
    regions = []
    live_total = 0
    stack_depth = None
    runs = []
    rom_runs = []
    for r in census["regions"]:
        size = r["size"]
        b = _region_bits(r)
        wa, ra = b["written_after_init"], b["read_after_init"]
        early = b["written_during_init"] | b["read_during_init"]
        live = popcount(wa)
        rom = popcount(ra & ~wa)
        init_only = popcount(early & ~wa & ~ra)
        fd = decode_bitmap(r["file_data"], size) if r.get("file_data") else 0
        row = {"name": r["name"], "kind": r["kind"], "start": r["start"], "size": size,
               "live": live, "file_data_live": popcount(wa & fd), "rom_candidate": rom,
               "init_only": init_only,
               "untouched": size - live - rom - init_only,
               "writers": {c: popcount(v) for c, v in b["writers"].items() if popcount(v)},
               "content": r.get("content")}
        regions.append(row)
        if r["kind"] == "stack":
            low = (wa & -wa).bit_length() - 1 if wa else size
            stack_depth = size - low
            continue
        live_total += live
        for off, span, n in live_runs(wa, size, gap=64):
            ws = {c: popcount(v >> off & ((1 << span) - 1)) for c, v in b["writers"].items()}
            runs.append({"region": r["name"], "start": r["start"] + off, "span": span, "live": n,
                         "writers": {c: k for c, k in ws.items() if k},
                         "label": _label(r["start"] + off, span) or (r.get("content") or "")})
        if r["kind"] != "text":   # text is ROM anyway
            for off, span, n in live_runs(ra & ~wa, size):
                rom_runs.append({"region": r["name"], "start": r["start"] + off, "span": span,
                                 "bytes": n, "label": _label(r["start"] + off, span) or (r.get("content") or "")})
    runs.sort(key=lambda x: (-x["live"], x["start"]))
    rom_runs.sort(key=lambda x: (-x["bytes"], x["start"]))
    ev = census.get("events_seen", {})
    missing = [k for k in REQUIRED_EVENTS if not (isinstance(ev.get(k), (int, float)) and ev.get(k) > 0)]
    depth = stack_depth or 0
    fp = footprint(census)
    if missing:
        verdict = "INCOMPLETE"
    elif fp["counted"] > budget or depth > STACK_RESERVE:
        verdict = "STOP"
    elif depth > STACK_RESERVE - STACK_WARN_MARGIN:
        verdict = "WARN"
    else:
        verdict = "GO"
    file_live = sum(r["file_data_live"] for r in regions if r["kind"] != "stack")
    return {"regions": regions, "live_total": live_total, "budget": budget, "verdict": verdict,
            "file_data_live_total": file_live, "footprint": fp,
            "missing_events": missing, "stack_depth": stack_depth, "runs": runs,
            "rom_runs": rom_runs}


def identify(data, files, min_len=32):
    """Name the files whose contents make up `data` (greedy, biggest file first)."""
    cover = bytearray(len(data))
    hits = []
    for name, content in sorted(files.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(content) < min_len or len(content) > len(data) or not content.strip(b"\0"):
            continue
        i = data.find(content)
        while i >= 0:
            if not any(cover[i:i + len(content)]):
                cover[i:i + len(content)] = b"\1" * len(content)
                hits.append((i, name))
            i = data.find(content, i + 1)
    if not hits:
        return "?"
    hits.sort()
    covered = sum(cover)
    names = [n for _, n in hits]
    shown = " + ".join(names[:6]) + (" + %d more" % (len(names) - 6) if len(names) > 6 else "")
    if len(names) == 1 and len(data) - covered <= 1:
        return shown                       # malloc rounds sizes up to even
    if covered == len(data):
        return shown
    return "%s (%d of %d B)" % (shown, covered, len(data))


def file_data_mask(mem, live, files, chunk=32, step=4):
    """Live bytes of `mem` (a region's content at the end of a run) that equal a contiguous piece
    of one of `files`: seeds of `chunk` live bytes (tried every `step` bytes) with at least 4
    distinct values found verbatim in a file, extended byte by byte while live and equal.
    Returns (mask, hits), hits = [(region offset, length, file name, file offset)]."""
    mask = 0
    hits = []
    n = len(mem)
    named = sorted(files.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    i = 0
    while i + chunk <= n:
        seed = mem[i:i + chunk]
        full = (1 << chunk) - 1
        if (live >> i) & full != full or (mask >> i) & full or len(set(seed)) < 4:
            i += step
            continue
        for name, content in named:
            j = content.find(seed)
            if j < 0:
                continue
            a, b = i, i + chunk                    # extend [a, b) <-> content[j - (i - a) ...]
            while a > 0 and j - (i - a) > 0 and live >> (a - 1) & 1 and not mask >> (a - 1) & 1 \
                    and mem[a - 1] == content[j - (i - a) - 1]:
                a -= 1
            while b < n and j + (b - i) < len(content) and live >> b & 1 and mem[b] == content[j + (b - i)]:
                b += 1
            mask |= ((1 << (b - a)) - 1) << a
            hits.append((a, b - a, name, j - (i - a)))
            i = b
            break
        else:
            i += step
    # adjacent hits from the same file stay separate entries; callers merge for display
    return mask, hits


def mark_file_data(census, scens, files):
    """region["file_data"] = live bytes that hold a verbatim piece of a GAME file at the end of
    every scenario in which they are live (memory dumps of the image, [0, bss end))."""
    out = []
    for r in census["regions"]:
        if r["kind"] not in ("text", "data", "bss", "gap"):
            continue
        size = r["size"]
        got, bad = 0, 0
        hits = {}
        for s in scens:
            path = s.get("memory_dump")
            sr = next((x for x in s["regions"] if x["name"] == r["name"]), None)
            if not path or not os.path.exists(path) or sr is None:
                continue
            with open(path, "rb") as f:
                f.seek(r["start"])
                mem = f.read(size)
            if len(mem) < size:
                continue
            live = decode_bitmap(sr["written_after_init"], size)
            mask, h = file_data_mask(mem, live, files)
            got |= mask
            bad |= live & ~mask
            for off, n, name, foff in h:
                hits.setdefault(name, []).append((off, n, foff))
        fd = got & ~bad
        if not fd:
            continue
        r["file_data"] = encode_bitmap(fd, size)
        for off, span, n in live_runs(fd, size, gap=1):
            names = sorted({name for name, hs in hits.items()
                            for o, k, _ in hs if o < off + span and off < o + k})
            out.append({"region": r["name"], "start": r["start"] + off, "size": n, "files": names})
    census["file_data"] = out


def xsp_mem_sizes(cnf):
    """PCG_MAX / REF_MAX / FRM_MAX from XSP_MEM.cnf (Shift-JIS comments, `NAME = 0x..` lines)."""
    out = {}
    for line in cnf.splitlines():
        line = line.split(b"*")[0]
        m = re.match(rb"\s*(PCG_MAX|REF_MAX|FRM_MAX)\s*=\s*(?:0x|0X|\$)?([0-9A-Fa-f]+)", line)
        if m:
            out[m.group(1).decode()] = int(m.group(2), 16)
    return out


def size_label(block_size, sizes):
    """Name a malloc block (size with its 12-byte header) by the size the game asked for."""
    data = block_size - 12
    def even(n):
        return n + (n & 1)
    labels = []
    if "PCG_MAX" in sizes and data == even(sizes["PCG_MAX"] * 128):
        labels.append("PCG_DAT: PCG_MAX x 128 (XSP_MEM.cnf), xsp_pcgdat_set")
    if "PCG_MAX" in sizes and data == even(sizes["PCG_MAX"] + 1):
        labels.append("PCG_ALT: PCG_MAX + 1 bytes (XSP_MEM.cnf), xsp_pcgdat_set work table")
    if "REF_MAX" in sizes and data == even(sizes["REF_MAX"] * 8):
        labels.append("REF_DAT: REF_MAX x 8 (XSP_MEM.cnf), xsp_objdat_set")
    if "FRM_MAX" in sizes and data == even(sizes["FRM_MAX"] * 8):
        labels.append("FRM_DAT: FRM_MAX x 8 (XSP_MEM.cnf), xsp_objdat_set")
    if data == 0x400:
        labels.append("1 KB: an XC stdio buffer (the startup and fopen malloc $400)")
    return "; ".join(labels)


def load_game_files(game_dir):
    files = {}
    for path in glob.glob(os.path.join(game_dir, "**", "*"), recursive=True):
        if os.path.isfile(path):
            with open(path, "rb") as f:
                files[os.path.relpath(path, game_dir)] = f.read()
    return files


def _h(v):
    return "$%X" % v


def _pc(v, base):
    """Game-relative pc; outside the image as an absolute address."""
    if v is None:
        return "?"
    if 0 <= v < 0x2C098 or not isinstance(base, int):
        return _h(v)
    return "abs $%06X" % ((v + base) & 0xFFFFFF)


def _writers(ws):
    return ", ".join("%s %d" % (c, ws[c]) for c in WRITER_CLASSES if ws.get(c)) or "-"


def render_md(a, census):
    ev = census.get("events_seen", {})
    L = []
    L.append("# RAM census of the original (SZ2 v0.10) and the 64 KB gate")
    L.append("")
    L.append("Generated by `make census` (`tests/x68k/ramcensus.lua` in MAME x68000 while "
             "`tests/x68k/autoplay.lua` plays, merged by `tools/census_report.py`). Offsets are "
             "game-relative (base-0 image offsets; the program loaded at $050F40). Sizes in bytes.")
    L.append("")
    fp = a["footprint"]
    budget = a["budget"]
    L.append("## Verdict")
    L.append("")
    L.append("**%s**: %d bytes of live objects in the spec's model (XSP's bss replaced by the shim, "
             "reloaded file data in ROM, stdio dropped; see Footprint) against a budget of %d, margin "
             "%+d (stack excluded; measured stack depth %s of a %d-byte reserve)." % (
                 a["verdict"], fp["counted"], budget, budget - fp["counted"],
                 a["stack_depth"] if a["stack_depth"] is not None else "?", STACK_RESERVE))
    L.append("")
    L.append("Keeping XSP's bss, the file buffers and stdio in RAM would need %d bytes (margin %+d%s)." % (
        fp["kept"], budget - fp["kept"], ": over the budget" if fp["kept"] > budget else ""))
    if not fp["targets"]:
        L.append("")
        L.append("No relocation targets were given (--orig-dir): each region counts as one object.")
    if a["missing_events"]:
        L.append("")
        L.append("Events never seen: %s." % ", ".join(a["missing_events"]))
    depth = a["stack_depth"] or 0
    if depth > STACK_RESERVE - STACK_WARN_MARGIN:
        L.append("")
        L.append("> **%s** stack depth %d is %s the %d-byte stack reserve (warning above %d): size "
                 "the port's stack with headroom and measure it on the port." % (
                     "STOP:" if depth > STACK_RESERVE else "WARN:", depth,
                     "over" if depth > STACK_RESERVE else "within %d bytes of" % (STACK_RESERVE - depth),
                     STACK_RESERVE, STACK_RESERVE - STACK_WARN_MARGIN))
    L.append("")
    L.append("Budget: 65,536 (work RAM $100000-$10FFFF) - 3,328 (BIOS work area $10F300-$10FFFF) - "
             "12,288 (port reserve: sprite list shadow, sound queue, view state, shim scratch; it "
             "also holds what replaces XSP's buffers) - 2,048 (stack) = %d; the spec-model "
             "footprint leaves %+d." % (BUDGET, budget - fp["counted"]))
    L.append("")
    L.append("Definitions: **live** = written after init (init ends at the first title frame); "
             "**ROM candidate** = read after init but never written after it; **init only** = "
             "touched only during init; **untouched** = never accessed while the census ran "
             "(the image's own load is not seen). Writers = class of the code that first wrote "
             "each live word (XSP text $0-$1575, game $1576-$144D7, XC library $144D8-$17509, "
             "other = outside the program: IOCS/DOS/interrupt code or DMA).")
    L.append("")
    L.append("## Footprint")
    L.append("")
    L.append("Objects: the program's memory split at every relocation target (the addresses its code "
             "and data refer to), each heap block into its %d-byte malloc header and its data. An "
             "object counts whole when any byte of it is written after init, so an array of "
             "structures counts its full span however few entries the census saw written. Written "
             "bytes alone (%d, the Regions table) undercount arrays and are not the gate figure." % (
                 HEAP_HEADER, a["live_total"]))
    L.append("")
    roms = sorted({f for x in census.get("file_data") or [] for f in x["files"]})
    L.append("| Live objects | Bytes | XSP bss kept | XSP bss replaced by the shim (verdict) |")
    L.append("|---|---|---|---|")
    L.append("| game state (game, XC library, data) | %d | RAM | RAM |" % fp["counted"])
    L.append("| XSP's own: text variables $0-$1575, bss $17D98-$1DB0D, PCG_ALT heap block | %d | RAM | "
             "replaced by the shim (port reserve) |" % fp["xsp"])
    L.append("| reloaded file buffers%s | %d | RAM | ROM |" % (
        " (%s)" % ", ".join(roms) if roms else "", fp["rom"]))
    L.append("| XC stdio buffer and malloc headers | %d | RAM | dropped (file I/O and malloc go) |" % fp["drop"])
    L.append("| **total** | | **%d** (margin %+d) | **%d** (margin %+d) |" % (
        fp["kept"], budget - fp["kept"], fp["counted"], budget - fp["counted"]))
    L.append("")
    L.append("The verdict uses the spec's model (XSP's buffers go with XSP, loaded files go to ROM, "
             "the C library's file I/O and malloc go), judged against %d with the stack rules "
             "(WARN above %d, STOP above %d)." % (budget, STACK_RESERVE - STACK_WARN_MARGIN, STACK_RESERVE))
    L.append("")
    L.append("| Region | Written bytes | Live objects | Object bytes | Game state | XSP | ROM | Dropped |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in fp["by_region"]:
        if r["objects"]:
            L.append("| %s | %d | %d | %d | %d | %d | %d | %d |" % (
                r["name"], r["live"], r["objects"], r["bytes"], r["counted"], r["xsp"], r["rom"], r["drop"]))
    L.append("")
    bss = sum(r["size"] for r in a["regions"] if r["kind"] == "bss")
    if bss > budget:
        L.append("Relocation: the spec's two-segment relocation (text to a ROM base, data and bss to "
                 "one RAM base) cannot fit, because the bss alone is %d bytes. Plan 2 must remap the "
                 "bss object by object (the same relocation-target objects as here): live game-state "
                 "objects to RAM, ROM candidates to ROM, XSP's bss to the shim." % bss)
        L.append("")
    L.append("## Regions")
    L.append("")
    L.append("| Region | Kind | Start | Size | Live | of which file data | ROM cand. | Init only | Untouched | Live writers |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    groups = {}
    for r in a["regions"]:
        if r["kind"] in ("heap", "heap_free") and r["live"] == 0 and r["rom_candidate"] == 0:
            key = r["kind"]
        else:
            key = None
        if key:
            g = groups.setdefault(key, {"n": 0, "size": 0, "init_only": 0, "untouched": 0})
            g["n"] += 1
            g["size"] += r["size"]
            g["init_only"] += r["init_only"]
            g["untouched"] += r["untouched"]
            continue
        L.append("| %s | %s | %s | %d | %d | %d | %d | %d | %d | %s |" % (
            r["name"], r["kind"], _h(r["start"]), r["size"], r["live"], r.get("file_data_live", 0),
            r["rom_candidate"], r["init_only"], r["untouched"], _writers(r["writers"])))
    for key, g in groups.items():
        L.append("| %d other %s blocks | %s | - | %d | 0 | 0 | 0 | %d | %d | - |" % (
            g["n"], "heap" if key == "heap" else "free heap", key, g["size"], g["init_only"], g["untouched"]))
    L.append("| **total written bytes (stack excluded)** | | | | **%d** | %d | %d | | | |" % (
        a["live_total"], a.get("file_data_live_total", 0),
        sum(r["rom_candidate"] for r in a["regions"] if r["kind"] != "stack")))
    L.append("")
    by_kind = {}
    for r in a["regions"]:
        if r["kind"] != "stack":
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["live"]
    L.append("Live by kind: " + ", ".join("%s %d" % (k, v) for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])) + ".")
    wt = {}
    for r in a["regions"]:
        if r["kind"] != "stack":
            for c, n in r["writers"].items():
                wt[c] = wt.get(c, 0) + n
    L.append("Live by first writer (a byte first written by different classes in different "
             "scenarios counts once per class): " + _writers(wt) + ".")
    L.append("")
    L.append("## Biggest live objects")
    L.append("")
    L.append("Live objects (see Footprint), largest first. Owner: RAM = game state; xsp = replaced by "
             "the shim; rom = reloaded file data; drop = stdio or malloc.")
    L.append("")
    L.append("| Region | Start | End | Size | Live | Writers | Owner | Known as |")
    L.append("|---|---|---|---|---|---|---|---|")
    names = {"counted": "RAM", "xsp": "xsp", "rom": "rom", "drop": "drop"}
    for x in sorted(fp["objects"], key=lambda o: (-o["size"], o["start"]))[:30]:
        L.append("| %s | %s | %s | %d | %d | %s | %s | %s |" % (
            x["region"], _h(x["start"]), _h(x["start"] + x["size"] - 1), x["size"], x["live"],
            _writers(x["writers"]), names[x["owner"]], x["label"]))
    L.append("")
    fdl = census.get("file_data") or []
    if fdl:
        L.append("## Live bytes that are file data")
        L.append("")
        L.append("| Region | Start | Bytes | Files |")
        L.append("|---|---|---|---|")
        for x in fdl:
            L.append("| %s | %s | %d | %s |" % (x["region"], _h(x["start"]), x["size"], ", ".join(x["files"])))
        L.append("")
    tdw = census.get("text_data_writes")
    if tdw is not None:
        L.append("## Text and data written by the program")
        L.append("")
        L.append("Text and data objects (split at relocation targets) that the program writes: "
                 "written after init (live: RAM), or changed by init and never written after it (the "
                 "end-of-run memory of a scenario differs from `sz2.bin` once relocation is undone). "
                 "The census cannot see which code wrote during init: its during-init map also holds "
                 "the PLZX depacker's copy of the whole image. A byte init writes with the value it "
                 "already had does not show here.")
        L.append("")
        L.append("| Region | Start | Size | Code | Written after init | Changed by init only | Known as |")
        L.append("|---|---|---|---|---|---|---|")
        for x in tdw:
            L.append("| %s | %s | %d | %s | %d | %d | %s |" % (
                x["region"], _h(x["start"]), x["size"], x["owner"], x["live"], x["init_changed"], x["label"]))
        L.append("")
    L.append("## ROM candidates")
    L.append("")
    L.append("Read after init, never written after it (text is ROM anyway and not listed).")
    L.append("")
    L.append("- A ROM candidate (and an init-only object in text or data above) takes its value from "
             "the post-init snapshot, not from `sz2.bin`: init writes some of them (detection results, "
             "renderer state, XSP's variables). The end-of-run memory dumps serve as that snapshot for "
             "bytes never written after init.")
    path_only = [(n, v) for v, n in PATH_VARS if _is_rom_candidate(census, v)]
    L.append("- \"ROM candidate\" depends on the paths the census ran: each one needs static "
             "confirmation (no write instruction targets it) before it moves to ROM. %sCode that runs "
             "only in ACCHOH mode or with the debug flag set never ran, so variables only it writes "
             "look read-only or untouched here. The KAKUSI variables (muteki $221F8, stage $221FA, "
             "acchoh $221F6) become RAM if KAKUSI stays reachable in the port." % (
                 "ROM candidates here only because no scenario took the KAKUSI or debug paths (the "
                 "census's own muteki poke is not counted): %s. " % ", ".join(
                     "%s %s" % (n, _h(v)) for n, v in path_only) if path_only else ""))
    L.append("")
    L.append("Per region:")
    L.append("")
    for r in a["regions"]:
        if r["rom_candidate"] and r["kind"] != "text":
            L.append("- %s (%s, %s): %d" % (r["name"], _h(r["start"]), r["kind"], r["rom_candidate"]))
    L.append("")
    L.append("Largest runs (gaps under 16 bytes merged):")
    L.append("")
    L.append("| Region | Start | Span | Bytes | Known as |")
    L.append("|---|---|---|---|---|")
    for x in a["rom_runs"][:20]:
        L.append("| %s | %s | %d | %d | %s |" % (x["region"], _h(x["start"]), x["span"], x["bytes"], x["label"]))
    L.append("")
    L.append("## Heap blocks")
    L.append("")
    L.append("XC malloc chain inside the program's own Human68k block (12-byte headers: prev, end, "
             "next; the arena head is 16 bytes). Size includes the header. Content = files of "
             "`GAME/` found in the block's data at the first title frame.")
    L.append("")
    L.append("| Start | Size | Used | Live | Live writers | ROM cand. | Content |")
    L.append("|---|---|---|---|---|---|---|")
    rmap = {r["start"]: r for r in a["regions"] if r["kind"] in ("heap", "heap_free")}
    for hb in census.get("heap_blocks", []):
        r = rmap.get(hb["start"], {})
        L.append("| %s | %d | %s | %d | %s | %d | %s |" % (
            _h(hb["start"]), hb["size"], "yes" if hb.get("used") else "free", r.get("live", 0),
            _writers(r.get("writers", {})), r.get("rom_candidate", 0), hb.get("content") or "-"))
    L.append("")
    L.append("## Stack")
    L.append("")
    st = census.get("stack", {})
    if st:
        hi = st.get("hi")
        def depth(k):
            return (hi - st[k]) if st.get(k) is not None and hi is not None else "?"
        L.append("- C stack (moved there by the XC startup): %s-%s (%d bytes reserved by the "
                 "original)." % (_h(st.get("lo", 0)), _h(hi or 0), (hi or 0) - st.get("lo", 0)))
        L.append("- Deepest byte written after init: %s bytes below the top; during init: %s; "
                 "lowest sp sampled at frame ends: %s." % (
                     depth("min_written_after_init"), depth("min_written_during_init"),
                     depth("min_sp_sampled")))
        if st.get("min_written_by_program") is not None:
            L.append("- Deepest byte written after init by code in the image (game, XSP, XC library): "
                     "%s bytes below the top." % depth("min_written_by_program"))
        pcs = [(s.get("scenario"), (s.get("stack") or {})) for s in census.get("scenario_info", [])]
        rows = ["%s: %s (pc %s) / program %s (pc %s)" % (
                    n, (hi - x["min_written_after_init"]) if x.get("min_written_after_init") is not None else "?",
                    _pc(x.get("min_written_any_pc"), census.get("program_base")),
                    (hi - x["min_written_by_program"]) if x.get("min_written_by_program") is not None else "?",
                    _pc(x.get("min_written_by_program_pc"), census.get("program_base")))
                for n, x in pcs if x]
        if rows:
            L.append("- Per scenario, deepest after init (pc of the write, game-relative; outside "
                     "the image = IOCS/DOS ROM or RAM code): " + "; ".join(rows) + ".")
    L.append("")
    L.append("## Events seen")
    L.append("")
    L.append("Counts, summed over the scenarios:")
    L.append("")
    L.append("| Event | Count |")
    L.append("|---|---|")
    timed = []
    for k in REQUIRED_EVENTS + sorted(k for k in ev if k not in REQUIRED_EVENTS):
        v = ev.get(k, 0)
        if isinstance(v, dict) or k in FRAME_EVENTS or k in MAX_EVENTS:
            timed.append(k)
            continue
        L.append("| %s | %s |" % (k, v))
    if timed:
        L.append("")
        L.append("Frames: the earliest over the scenarios (loop2_stage1_frames: the longest time spent "
                 "in the second loop's stage 1):")
        L.append("")
        L.append("| Event | Frame or frames |")
        L.append("|---|---|")
        for k in timed:
            v = ev[k]
            if isinstance(v, dict):
                v = ", ".join("stage %s: frame %s" % kv for kv in sorted(v.items()))
            elif k in MAX_EVENTS:
                v = "%s frames" % v
            else:
                v = "frame %s" % v
            L.append("| %s | %s |" % (k, v))
    L.append("")
    L.append("## Notes")
    L.append("")
    for n in NOTES:
        L.append("- " + n)
    deaths = []
    for s in census.get("scenario_info", []):
        e = s.get("events_seen") or {}
        if isinstance(e.get("player_died"), (int, float)) and e["player_died"] > 0:
            st = e.get("stage_reached") or {}
            deaths.append("%s (stages reached: %s)" % (s.get("scenario"), ", ".join(sorted(st)) or "?"))
    if deaths:
        L.append("- Deaths: player_died only in %s; the death, respawn, continue and game-over paths "
                 "ran only in those stages." % "; ".join(deaths))
    L.append("")
    info = census.get("scenario_info", [])
    if info:
        L.append("## Scenarios")
        L.append("")
        L.append("| Scenario | Options | Status | Frames | Init end | Stray marks |")
        L.append("|---|---|---|---|---|---|")
        for s in info:
            o = s.get("options") or {}
            L.append("| %s | %s | %s | %s | %s | %s |" % (
                s.get("scenario"), ", ".join("%s=%s" % kv for kv in sorted(o.items())), s.get("status"),
                s.get("frames"), s.get("init_end_frame"), (s.get("stray") or {}).get("count", "-")))
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md")
    ap.add_argument("--game-dir")
    ap.add_argument("--orig-dir", help="build/orig: sz2.bin + sz2.json (relocation targets = objects)")
    ap.add_argument("--budget", type=int, default=BUDGET)
    a = ap.parse_args(argv)
    scens = []
    for p in a.scenarios:
        with open(p) as f:
            s = json.load(f)
        for hb in s.get("heap_blocks", []):
            if hb.get("dump"):
                hb["dump"] = os.path.join(os.path.dirname(os.path.abspath(p)), hb["dump"])
        if s.get("memory_dump"):
            s["memory_dump"] = os.path.join(os.path.dirname(os.path.abspath(p)), s["memory_dump"])
        scens.append(s)
    files = load_game_files(a.game_dir) if a.game_dir else None
    census = merge(scens)
    if files is not None:
        sizes = xsp_mem_sizes(files.get(os.path.join("XSP_DAT", "XSP_MEM.cnf"), b""))
        names = {}
        for hb in census["heap_blocks"]:
            if hb.get("used") and hb.get("dump") and os.path.exists(hb["dump"]):
                with open(hb["dump"], "rb") as f:
                    hb["content"] = identify(f.read(), files)
            elif not hb.get("content"):
                hb["content"] = "?" if hb.get("used") else "free"
            lab = size_label(hb["size"], sizes)
            if lab and hb.get("used"):
                hb["content"] = lab if hb["content"] == "?" else "%s; %s" % (lab, hb["content"])
            names[hb["start"]] = hb["content"]
        for r in census["regions"]:
            if r["start"] in names and r["kind"].startswith("heap"):
                r["content"] = names[r["start"]]
    if files is not None:
        mark_file_data(census, scens, files)
    if a.orig_dir:
        with open(os.path.join(a.orig_dir, "sz2.bin"), "rb") as f:
            image = f.read()
        with open(os.path.join(a.orig_dir, "sz2.json")) as f:
            relocs = json.load(f)["relocs"]
        census["reloc_targets"] = reloc_targets(image, relocs)
        changed, seen = 0, 0
        for s in scens:
            path = s.get("memory_dump")
            if path and os.path.exists(path) and isinstance(s.get("program_base"), int):
                with open(path, "rb") as f:
                    mem = f.read(len(image))
                if len(mem) == len(image):
                    changed |= changed_since_load(mem, image, relocs, s["program_base"])
                    seen += 1
        if seen:
            census["text_data_writes"] = text_data_writes(census, changed)
    scen_dir = os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in a.scenarios])
    for hb in census["heap_blocks"]:
        if hb.get("dump"):
            hb["dump"] = os.path.relpath(hb["dump"], scen_dir)
    res = analyze(census, a.budget)
    census["verdict"] = {k: res[k] for k in ("verdict", "live_total", "budget", "missing_events", "stack_depth")}
    census["footprint"] = res["footprint"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    write(a.out, census)
    if a.md:
        with open(a.md, "w") as f:
            f.write(render_md(res, census))
    fp = res["footprint"]
    print("census: %d scenarios, written %d B, objects: XSP bss kept %d / replaced %d (verdict) of "
          "budget %d, stack depth %s -> verdict %s%s" % (
        len(scens), res["live_total"], fp["kept"], fp["counted"], res["budget"], res["stack_depth"],
        res["verdict"],
        (" (missing: %s)" % ", ".join(res["missing_events"])) if res["missing_events"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
