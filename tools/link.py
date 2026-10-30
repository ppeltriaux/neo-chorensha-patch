"""Linker: the game's code and start-up snapshot placed in P-ROM and RAM for the Neo Geo.

  .venv/bin/python -I tools/link.py --orig build/orig --preinit build/preinit \\
      --layout build/link/layout.json --out build/link                         (make link)
  .venv/bin/python -I tools/link.py --digests --orig build/orig     (TABLE_SHA1, after a table edit)

Inputs: sz2.bin/sz2.json (text, relocations), inventory.json (I/O operands, XSP entries), the
start-up snapshot (build/preinit: memory.bin, below_base.bin, snapshot.json) and the object
layout (build/link/layout.json, tools/layout.py). layout.json decides every address; this tool
only carries the bytes there and rewrites the words that hold addresses.

Bytes. Every object takes its snapshot value (memory.bin; below_base.bin for the command line,
environment and PSP). The text sits in place at GAME_ROM; the other ROM objects at their layout
address (those the game reloads from a file after the resume point hold the file's bytes
instead: FILE_RELOADS); then SHIM_DEAD (64 bytes of $FF). RAM objects go into the RAM image
(copied by the shim to RAM_LO at boot). The stack's live part (sp .. the original's top) is the
stack image, put at the same distance below the Neo Geo stack top. Shim and drop objects have no
copy.

Words (patches.json lists each, with its old and new value and what it means):
  reloc / pointer  every relocation word and every snapshot pointer (memory.bin, below the base)
                   is rewritten where its holder object's bytes go (ROM, RAM image, stack image;
                   none for shim/drop holders). The target maps through the object that contains
                   it; an address not inside any object but at one's end maps to that object's
                   end; layout's end_pointers use their map_to. Targets in shim/drop objects map
                   into SHIM_DEAD (offset kept for objects of at most 64 bytes, else its start:
                   flagged "dead"). Tagged pointers (pointer_tags) keep their top byte.
  xsp_entry        the 16 XSP C entries (snapshot.json xsp_entries, each confirmed against
                   inventory.json's xsp / xsp_unmatched) become `jmp XSPJT_<name>` (abs long,
                   6 bytes; the XSP code behind is dead). XSPJT_<name> is a 6-byte slot of the
                   jump table at XSP_JT in the shim's low P-ROM: game.asm pins each slot (its own
                   org) and fills it with `jmp (Shim_<name>).l`, resolved by the cart's
                   assembler. A missing Shim_<name> fails the assembly unless the shim opts out
                   explicitly with XSP_STUB_<name> (then the slot is `illegal`: a tripwire the
                   fault handler reports).
                   Relocation words under a jmp are superseded (listed).
  shim_entry       the game routines the shim replaces (SHIM_ENTRIES: the text routines $1618,
                   $173C, $1888, Plan 3 Task 3) the same way: `jmp SHIMJT_<name>`, a slot after
                   the XSP slots filled with `jmp (Shim_<name>).l` (a missing Shim_<name> fails
                   the assembly). The game variables those replacements use (SHIM_VARS) get
                   GV_<name> equates: their Neo Geo address (the ones they write must be RAM); an
                   entry with a size covers that many bytes, which must lie in one object.
  io               absolute I/O operands ($E00000-$EFFFFF, inventory.json io, game and library
                   code: XSP's code is dead) fold into the 4 KB shadow at IO_SHADOW: the
                   addresses are grouped in clusters (gaps under IO_CLUSTER_GAP), each cluster
                   placed whole (relative offsets and parity kept) one after the other; the fold
                   map is patches.json's io_fold. More than 4 KB of clusters, or an operand that
                   cannot be found uniquely in its instruction, fails the build. IO_REDIRECT
                   sends chosen operands elsewhere instead (a constant byte: see its note).
  io_ptr           register-based I/O whose READS the game depends on after the resume point
                   (IO_PTR_SHADOW, the Task 5 decisions in docs/notes/shim.md): the base
                   immediate becomes the shadow address of the same register (its cluster must
                   be folded). Every other register-based site stays (patches.json io_unfolded).
  io_code          game code reaching X68000 I/O through a register that runs after the resume
                   point (IO_CODE, Plan 3 Task 5: the game-start background builder): each
                   instruction becomes one of the same size that touches no I/O (the site's
                   bytes are checked: see "The tables" below; no relocation word may lie under
                   it).
  title_code       the title's own edits (TITLE_CODE): the call that draws its placeholder
                   text (presentation plan Task 1) and, Plan 5 Task 3, the menu's "exit"
                   and its cursor limit, the copyright and version rows; Plan 5 Task 5, its
                   menus': KAKUSI's gate (the debug-flag test), CONFIG's item 1 (SCREEN's prints and
                   handler) and every CONFIG row two up (CONFIG_ROWS); 2026-10-28, CONFIG's item 0
                   (XSP MODE) gone, its prints nops and the items' numbering one down, the other
                   lines four up. The same checks as io_code; a table of its own because it is not
                   I/O.
  title_hook       the title's hooks (TITLE_HOOKS, Plan 5 Tasks 3 and 5: Title_Hook, CONFIG's
                   Config_Hook): a 4-byte instruction with no
                   relocation word becomes `jsr HOOKJT_<label>.w`, a jump-table slot after the
                   shim entries' (one per label, whatever its sites) that game.asm fills with
                   `jmp (<label>).l` (a missing label fails the assembly); the shim's <label>
                   does the instruction's work too.
  game_hook        the game's own hooks (GAME_HOOKS, two-player plan Task 1: the co-op's, src/shim/
                   coop.asm; the labels lie above game.asm, coop.asm's COOP_CODE after DEMO_DATA,
                   so no ifd: a missing one is an undefined symbol). A 4-byte site (no relocation
                   or pointer word under it) becomes `jsr GHOOKJT_<label>.w`, returning to at + 4:
                   a jump table of its own at GHOOK_JT ($7F00, GHOOK_MAX 6-byte slots, one per
                   label with a 4-byte site, in label order) that game.asm fills with
                   `jmp (<label>).l`. A 6-byte site (jsr abs.l or a move whose source is abs.l, its
                   one relocation word at at + 2 and no other word under it) becomes `jsr
                   (<label>).l` itself, returning to at + 6 (no slot: game.bin holds `jsr $0.l`
                   there and game.asm assembles the instruction between two pieces of game.bin);
                   its relocation word is superseded (listed) as under an XSP jmp. The site's
                   bytes are checked and must be one instruction; <label> does its work, CCR
                   included.
  game_code        the game's own code edits around them (GAME_CODE, two-player plan R5: the play
                   loop's second and third calls -> a bra.s over them, Coop_Pass making all three):
                   as title_code, but relocation words wholly inside the edit are superseded
                   (listed); the site's bytes and the new ones must each decode to whole
                   instructions.
  pcrel            PC-relative reads of text variables now in RAM (layout's pcrel_fixups): the
                   site becomes `jsr <stub>.w` (+ nop padding) to a stub in PCREL_STUBS doing
                   the same access with an absolute long address, then rts (CCR kept). Forms the
                   stub cannot express (indexed, stack-relative, pea, flow control) fail.
DOS F-line words, trap #15 and trap #4 are left as they are (the shim's vectors catch them).

The tables (IO_CODE, TITLE_CODE, TITLE_HOOKS, GAME_HOOKS, GAME_CODE) carry no byte of the original
program. A site is its address and size; the bytes there are the user's, checked by one SHA1 per
table (TABLE_SHA1) over its sites' (address, size, bytes) in sz2.bin (site_digest: a per-site hash
of 2-6 bytes would give the bytes away). The new bytes are ours, as hex, except where they hold 3
bytes or more in a row that the original has: that run is an Orig(at, n) piece, n bytes copied
from the user's text at link time (split_ours), its source in the table's digest too. A table
changed (a site, a size, an Orig piece) gets its digest printed by `link.py --digests`.

Low P-ROM region reserved for the link (the shim must place nothing there; vasm refuses
overlapping sections): XSP_JT $7C00 (128 B; its last two bytes are IO_CONST_SET/CLR),
PCREL_STUBS $7C80-$7EFF, GHOOK_JT $7F00-$7FFF (all abs.w reachable).

Writes to --out:
  game.bin      GAME_ROM .. rom_end: text, ROM objects, SHIM_DEAD (the 6-byte game-hook sites hold
                `jsr $0.l` here: game.asm assembles the real jsr, p1.bin has the real bytes)
  stubs.bin     the PC-relative stubs (at PCREL_STUBS)
  ramimage.bin  RAM_LO .. RAM_LO + ram_used (RAMIMAGE_SIZE bytes, copied to RAMIMAGE_DEST)
  stack.bin     the stack image (copied to GAME_SP)
  iosh.bin      the I/O shadow's starting bytes (the folded registers' values at the resume
                point, snapshot io_final; 0 where never written), copied to IO_SHADOW at boot
  romfiles.bin  the ROM file table the shim's DOS _OPEN/_READ serve: the files the game opens
                after the resume point (name strings referenced by code reachable from it)
  bgtext.bin    preinit's bgtext.bin (BG text page 1 as the game-start loader reads it back
                through IOCS _BGTEXTGT), at BGTEXT for the shim
  game.inc      equates: GAME_ROM, GAME_RESUME, GAME_SP, GAME_SR, GAME_REGS (15 longs d0-d7/a0-a6
                in ROM, for movem.l), GAME_STACK_IMAGE/SIZE, RAMIMAGE_*, GAME_PSP, XSP_<name>
                (entry in game ROM), XSPJT_<name>, XSPI_<call>_<arg> (XSP state the start-up
                set, pointers mapped), GAME_<name>/SHIMJT_<name> and GV_<name> (SHIM_ENTRIES,
                SHIM_VARS), HOOK_<label>_<n>/HOOKJT_<label> (TITLE_HOOKS),
                GHOOK_<label>_<n>/GHOOKJT_<label> (GAME_HOOKS), IO_SHADOW (+ IOSH_<addr> per
                folded address, IOSH_IMAGE/_SIZE), ROMFILES/_COUNT, the reserved regions, and the
                sound values that need the layout (Plan 4): SND_CUE_TABLE (the cue table in
                P-ROM) and SND_TUNE_PTR_<t> (the tune table's relocated data pointer of tune index
                t, the a0 MCDRV fn $01 receives); the tables' original addresses and the tunes are
                tools/mksound.py's (the rest of the sound numbers: build/snd/sound68k.inc)
  game.asm      the cart include placing all of it: org/incbin per piece, the XSP jump table,
                GAME_REGS. Include it after the shim's code (with -Ibuild/link).
  patches.json  every patched word, the fold map, the stubs, the RAM image table, counts
After game.bin the link data follows (LINKDATA = rom_end): GAME_REGS, the stack image, the RAM
image, the I/O shadow image, the ROM file table, the BG text page; all of it must end at or below
$100000.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
from bisect import bisect_right
from collections import namedtuple

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402
import mksound  # noqa: E402

GAME_ROM = layout.GAME_ROM
P1_END = 0x100000
RAM_LO = layout.RAM_LO
STACK_TOP = layout.STACK_TOP
IO_LO, IO_HI = 0xE00000, 0xF00000
IO_SHADOW = 0x10B800
IO_SHADOW_SIZE = 0x1000
IO_CLUSTER_GAP = 0x100
XSP_JT = 0x7C00
XSP_JT_SIZE = 0x80
PCREL_STUBS = 0x7C80
GHOOK_JT = 0x7F00            # the game hooks' jump table (GAME_HOOKS), to $7FFF
GHOOK_MAX = (0x8000 - GHOOK_JT) // 6
PCREL_STUBS_SIZE = GHOOK_JT - PCREL_STUBS
XSP_TEXT_END = layout.XSP_TEXT_END   # XSP's code and text variables: dead on the Neo Geo
JMP_L, JSR_W, JSR_L, NOP, RTS, ILLEGAL = 0x4EF9, 0x4EB8, 0x4EB9, 0x4E71, 0x4E75, 0x4AFC
# Two constant bytes link.py places at the end of the XSP jump table's reserved area (low
# P-ROM): I/O polls whose wait means nothing on the Neo Geo read one of them and end at once.
IO_CONST_SET = 0x7C7E       # $FF: every bit set
IO_CONST_CLR = 0x7C7F       # $00: every bit clear

# Register-based I/O reads the game depends on after the resume point (Task 5, docs/notes/
# shim.md): the io_ptr immediate at the site becomes the shadow address of the same register.
IO_PTR_SHADOW = {
    0x1958: "CRTC set-up $1944: lea $E80000,a1; R20 is read back at $1962 (cmp.b $29(a1),d0) "
            "to pick the order of the CRTC writes; with the base in the shadow the read sees "
            "what _CRTMOD and the game wrote (the writes through a1 land there too)",
}
# Absolute I/O operands sent to a constant byte in low P-ROM instead of the shadow.
IO_REDIRECT = {
    0x19A6: IO_CONST_SET,   # btst #7,GPIP; beq: wait for H-sync high -> bit 7 set: no wait
    0x19B0: IO_CONST_CLR,   # btst #7,GPIP; bne: wait for H-sync low  -> bit 7 clear: no wait
}
IO_REDIRECT_WHY = ("MFP GPIP bit 7 (H-sync) polled 7 times with interrupts masked at level 7 "
                   "($19A0) in the CRTC set-up $1944, so the X68000 CRTC registers change during "
                   "an H-blank: no interrupt can drive a RAM shadow there and the Neo Geo has no "
                   "readable H-sync bit (LSPC's line counter low byte is not mapped for byte "
                   "reads); the waits time hardware the Neo Geo does not have: each reads a "
                   "constant that ends it at once")
# A piece of a table's new bytes copied from the user's program: the `n` bytes of the text at
# base-0 `at` (split_ours makes them: runs of 3 bytes or more the original has).
Orig = namedtuple("Orig", "at n")
# Game code that reaches X68000 I/O through a register after the resume point (Plan 3 Task 5): the
# game-start background builder $6512 and the BG page writer $3536 it calls -- every site
# tests/neo/tripwire.lua finds over a whole game (docs/notes/shim.md "Background"). The Neo Geo
# draws the two graphic pages from C-ROM (build/gfx), so what the builder drew is not needed; the
# game's RAM after it is the original's (the lock-step). at -> (new, why): new a hex string, or a
# tuple of hex strings and Orig pieces (the runs the original has, copied from the user's text);
# the site's size is the new bytes' length, the bytes there checked by TABLE_SHA1["io_code"].
IO_CODE = {
    0x36C2: ((Orig(0x751A, 4), "4e71"),
             "$3536 BG page write move.w (a0,d1.l),(a1,d0.l) (a1: $EBC000/$EBE000, BG data RAM; "
             "the row-major path, not taken by the builder's calls) -> move.w (a0,d1.l),d2; nop: "
             "the cell is read, nothing is written (d2 is dead there: set again before any read)"),
    0x37E4: ((Orig(0x751A, 4), "4e71"),
             "$3536 BG page write move.w (a0,d1.l),(a1,d0.l) (a1: BG data RAM $EBE000, page 1 "
             "the builder reads back through _BGTEXTGT -- the shim serves that from bgtext.bin) "
             "-> move.w (a0,d1.l),d2; nop (d2 dead: move.w a5,d2 follows)"),
    0x6578: ("5488",
             "$6512 BG_PCG.SP upload move.w (a0)+,(a1)+ (a1: PCG RAM $EB8000, 8 x 1 KB; only the "
             "pixel loop read it back) -> addq.l #2,a0 (a1 is reloaded per piece and dead after)"),
    0x6764: ((Orig(0x40C2, 3), "3e"),
             "$6512 pixel loop $6764-$6AA0 (4,096 _BGTEXTGT reads, the PCG reads $6808/$68B2/"
             "$695A/$6A04, 262,144 graphic VRAM writes from $C00000: BIOS ROM on the Neo Geo) "
             "-> bra.w $6AA4, the builder's tail (_SUPER back, registers restored, rts): the "
             "loop's other effects are its stack frame's locals and scratch registers"),
}
# Game code that draws the original's placeholder text on the title (presentation
# plan Task 1): the call at $2A94 (`jsr (a3)`, a3 = the string printer $33E8, called with the three
# pushed arguments x 9, y 10, the string at $29C0) becomes a nop. Same checks as IO_CODE, but a
# table of its own: these are not I/O (test_builder_off_io pins IO_CODE to the I/O sites). The
# pushes stay and $2AB2 still pops all 36 bytes of the three calls, so the stack is balanced; the
# printer saves and restores d3-d5/a3 and only clobbers d0-d2/a0-a1, which the code after the call
# sets again before reading them; its other effect, GV_TEXT_SUPER ($193A), is stored again by the
# next print (START). Lock-step: no game state changes (docs/notes/presentation-recon.md 3.2).
# at -> (new, why), as IO_CODE.
# Plan 5 Task 3 (the cabinet's title, docs/notes/plan5-recon.md section 3) adds, in the same way:
# the menu's 4th item "exit" (the user's request) is not printed and the cursor stops at CONFIG,
# so the exit case ($2C56 -> main's $3F5C, _EXIT2) is never reached; the copyright line and
# the version row move up from field rows 27 / 29 (fix rows 27 / 29 with the title lift: the
# bombs' row and the screen's last 8 lines, which a CRT may crop) to rows 23 / 24 (fix rows 25 /
# 26 at the title's view 0; row 29 then holds no text, so the lift stays off), their order kept.
# The title's code is not compared by the lock-step (it compares from the play loop's entry), but
# the menu it returns from is: make lockstep proves it again.
TITLE_CODE = {
    0x2A94: ("4e71",
             "title: jsr (a3) -> nop; the $33E8 call printing the placeholder text at (9, 10); its "
             "three pushed arguments are still popped at $2AB2, the stack stays balanced"),
    0x2AD0: ("4e71",
             "title: jsr (a3) -> nop; the $33E8 call printing \"exit\" at (12, 23), the menu's 4th "
             "item (Plan 5 Task 3: the user removed it); its pushes are still popped at $2AE0"),
    0x2AD8: ("0017",
             "title: pea $1B.w -> pea $17.w, the copyright line's row: field (4, 23), fix row 25 "
             "(was 27, lifted: the bombs' row), above the version, where exit was"),
    0x2AEA: ("0018",
             "title: pea $1D.w -> pea $18.w, the version's row: field (9, 24), fix row 26 "
             "(was 29: the screen's last 8 lines); no title text is left on row 29 (no lift)"),
    0x2B80: ("0001",
             "title: cmp.w #2,d4 -> #1 (the cursor's down limit): Down moves it only from items 0 "
             "and 1, so it stops at CONFIG (2); item 3, exit ($2C56; main's _EXIT2 at $3F62), "
             "is never chosen"),
    # Plan 5 Task 5 (docs/notes/plan5-recon.md sections 4-5): the title's menus. KAKUSI's gate on
    # the CONFIG item ($2C2A-$2C52) tests _BITSNS group $A bit 3 (the X68000's key $53), then the
    # debug flag $221F0; only the second test goes, so the shim's _BITSNS (iocs.asm: bit 3 while
    # A+B+C+D are held) alone opens KAKUSI, and $221F0 (ROM, 0) keeps every other debug gate shut.
    0x2C46: ("4e71",
             "title, CONFIG item: beq.b $2C50 -> nop: the KAKUSI gate's debug-flag test ($221F0, "
             "ROM 0: tst.w at $2C40 still reads it) no longer sends to CONFIG; the code's key bit "
             "($2C3E: _BITSNS group $A bit 3, A+B+C+D held) alone chooses KAKUSI"),
    # CONFIG's SCREEN item (the original's 1; 0 since the 2026-10-28 renumbering below) is AUTO
    # FIRE (the shim's Config_Hook: TITLE_HOOKS below): its "0x" and its value print nothing (the
    # hook draws ON / OFF), and its handler ends after the hook.
    0x2D6E: ("4e71",
             "CONFIG: jsr (a4) -> nop: item 1's \"0x\" (18, 19), SCREEN's, not printed (AUTO FIRE's "
             "value is ON / OFF: Config_Hook); the pushes are still popped at $2D7E"),
    0x2DBA: ("4e71",
             "CONFIG: jsr (a3) -> nop: item 1's value (SCREEN's $17510 in hex) not printed; the "
             "pushes ($2DA6's now Config_Hook's) are still popped at $2DBC"),
    0x2F56: ((Orig(0x2FA2, 3), "fc"),
             "CONFIG: item 1's handler (SCREEN's, $2F52 now Config_Hook's jsr): bne.b and the next "
             "opcode -> bra.w $2D54, the loop; the rest ($2F5A-$2FA5: SCREEN 0-2 and its CRTC "
             "set-up $4A9C) is dead, so $17510 is never written"),
    # CONFIG without XSP MODE (the 2026-10-28 request; the port stays in MODE 2, the start-up's,
    # which every lock-step, timing, demo and framecheck baseline runs in): item 0's three prints
    # are nops (its pushes are still popped, at $2D06, $2D7E and $2DBC), and the items are numbered
    # one down so that the loop's d5 = 0 at the start ($2CC8, now $2CC4) and Up's stop at 0 ($2E78
    # tst.w d5; ble.b) are AUTO FIRE's: the dispatch reads its table ($2EF8, offsets from $2EF8)
    # one word on, Down stops at item 4 (exit) and the range check at 4. The XSP MODE handler
    # ($2F04-$2F4E: $221F4 1-3 and the xsp_mode2 call) is never reached, so $221F4 stays the
    # start-up's 2 (the cursor's rows: CONFIG_ROWS below, 17 + 2 n -> 15 + 2 n for the new n).
    0x2CC4: (("7a00", Orig(0x6764, 3), "01"),
             "CONFIG: clr.w d6; movea.w d6,a5; move.w a5,d5 -> moveq #0,d5; movea.w #1,a5: the "
             "cursor on item 0 as before, the triggers' last value (a5, d7 at the first pass) "
             "held, so the A that chose CONFIG, still held at the loop's first pass, is not a "
             "press there (the original's first pass gave it to XSP MODE, whose handler, with d4 "
             "1, fell through to xsp_mode2($221F4) at $2F3E-$2F46, the mode applied again "
             "unchanged; it would toggle AUTO FIRE, now item 0). d6 (the stick's last) is the "
             "title's: at most the first pass's stick goes unread"),
    0x2CF6: ("4e71",
             "CONFIG: jsr (a3) -> nop: XSP MODE's label (9, 17) not printed (the 2026-10-28 "
             "request: no XSP MODE item); its pushes are still popped at $2D06"),
    0x2D60: ("4e71",
             "CONFIG loop: jsr (a4) -> nop: XSP MODE's \"0x\" (18, 17) not printed; the pushes are "
             "still popped at $2D7E"),
    0x2DA4: ("4e71",
             "CONFIG loop: jsr (a3) -> nop: XSP MODE's value ($221F4 in hex, (20, 17)) not printed; "
             "the pushes are still popped at $2DBC"),
    0x2E90: ((Orig(0x2E90, 3), "03"),
             "CONFIG: cmp.w #4,d5 -> #3 (the cursor's down limit; bgt.b over the move follows): "
             "Down moves it from items 0-3 only, so it stops at exit, now item 4"),
    0x2EE6: ("7204",
             "CONFIG: moveq #5,d1 -> #4: the dispatch's range check (cmp.l d1,d0; bhi.w $2D54) "
             "ends at exit, now item 4 (d5 never passes it: the down limit)"),
    0x2EF0: ((Orig(0x2BD6, 3), "08"),
             "CONFIG: move.w $2EF8(pc,d0.l),d1 -> $2EFA(pc,d0.l): item n takes the table's entry "
             "n + 1 (jmp $2EF8(pc,d1.w) follows, the offsets still from $2EF8): 0 AUTO FIRE "
             "($2F52), 1 PCM PLAY, 2 BGM PLAY, 3 SHOT/BOMB, 4 exit; entry 0, XSP MODE's ($2F04: "
             "$221F4 and xsp_mode2), is never read"),
}
# CONFIG's rows (Plan 5 Task 5, plan5-recon.md section 4 option (a), the user's "move CONFIG's
# exit up"; the 2026-10-28 request): CONFIG prints at the title's fixed view 0 with no lift (no
# text on row 29), field row y on fix row y + 2, so the original's "exit" on row 27 sat on fix row
# 29, the screen's last 8 lines. Plan 5 moved every row two up (exit on fix row 27, the bombs' top
# row); without XSP MODE (row 17) the header stays two up (row 8) and the lines below it close the
# gap, four up: AUTO FIRE 15, PCM PLAY 17, BGM PLAY 19, SHOT/BOMB 21, exit 23 (fix row 25, off the
# bombs' rows 27-28 and the last 8 lines), every line's order kept, nothing on field rows 24-29.
# The row word of each print's `pea $yy.w` (of the cursor's `pea $11(a1)`: row 17 + 2 n, the
# original's item 0 on 17; now item 0 is AUTO FIRE, on 15) -> (the original's row, the port's,
# what it places). The prints of XSP MODE's label, "0x" and value and of SCREEN's "0x" and value
# are nops (above): their rows stay.
CONFIG_ROWS = {
    0x2CDC: (10, 8, "CONFIG's header (x 6)"),
    0x2CFE: (19, 15, "AUTO FIRE's label (x 9; SCREEN's in the original)"),
    0x2D10: (21, 17, "PCM PLAY's label (x 9)"),
    0x2D1E: (23, 19, "BGM PLAY's label (x 9)"),
    0x2D2C: (27, 23, "\"exit\" (x 9)"),
    0x2D3E: (17, 15, "the cursor's first draw (x 8, item 0: XSP MODE's row, now AUTO FIRE's)"),
    0x2D76: (21, 17, "PCM PLAY's \"0x\" (x 18)"),
    0x2D88: (23, 19, "BGM PLAY's \"0x\" (x 18)"),
    0x2DCE: (21, 17, "PCM PLAY's value (x 20)"),
    0x2DE4: (23, 19, "BGM PLAY's value (x 20)"),
    0x2DFE: (25, 21, "the shot/bomb keys' line (x 9)"),
    0x2E0E: (25, 21, "the shot/bomb keys' line (x 9, the swap on)"),
    0x2E62: (17, 15, "the cursor's erase (x 8, row 17 + 2 n -> 15 + 2 n: pea $11(a1))"),
    0x2EB2: (17, 15, "the cursor's draw (x 8, row 17 + 2 n -> 15 + 2 n: pea $11(a1))"),
}
for _at, (_y, _to, _what) in CONFIG_ROWS.items():
    TITLE_CODE[_at] = ("%04x" % _to,
                       "CONFIG: %s on row %d -> %d (fix row %d -> %d): %d up, out of the screen's "
                       "last 8 lines and off the bombs' rows" % (_what, _y, _to, _y + 2, _to + 2,
                                                                 _y - _to))
del _at, _y, _to, _what
# The title's hook (Plan 5 Task 3, src/shim/title.asm), one label at several sites (one jump-table
# slot; Title_Hook tells the sites apart by its return address and does the replaced instruction's
# work itself):
#   * the loop's pass ($2B10-$2BB8) after its V-blank wait and its two joystick reads, at `lea
#     $C(a7),a7` (their three arguments popped): Title_Hook pops the 12 bytes itself and may set
#     the loop's registers (d3-d7: the stick's and the triggers' last and new values, d4 the
#     cursor);
#   * the drawing ($2A82-$2B0A, at the title's opening and back from CONFIG): the x argument
#     pushes of the START, CONTINUE and CONFIG prints (`pea $C.w`) and the cursor's character push
#     (`pea $5.w`): Title_Hook pushes the same long and, where credits are counted (the MVS without
#     Free Play), has CONFIG's item printed as AUTO FIRE OFF / ON (the 2026-10-28 request: no CONFIG
#     there) and, with no credit in, every item printed empty and the cursor as a blank cell -- so
#     no menu is on the screen at 0 credits, not even for the frames before the loop's first pass.
# at -> (size, label, why). Only 4-byte instructions with no relocation word under them.
TITLE_HOOKS = {
    0x2A9E: (4, "Title_Hook",
             "title: pea $C.w (START's print, x 12) -> jsr HOOKJT_Title_Hook.w: pushes 12; with no "
             "credit in, the string pushed before it (START, $29D0) replaced by an empty one"),
    0x2AAC: (4, "Title_Hook",
             "title: pea $C.w (CONTINUE's print, x 12) -> jsr HOOKJT_Title_Hook.w: pushes 12; with "
             "no credit in, the string ($29D6) replaced by an empty one"),
    0x2ABE: (4, "Title_Hook",
             "title: pea $C.w (CONFIG's print, x 12, y 21) -> jsr HOOKJT_Title_Hook.w: pushes 12; "
             "where credits are counted, the string ($29E0) replaced by AUTO FIRE OFF / ON (the "
             "preserved block's), with no credit in by an empty one"),
    0x2AF2: (4, "Title_Hook",
             "title: pea $5.w (the cursor's character) -> jsr HOOKJT_Title_Hook.w: pushes 5; with "
             "no credit in, 0 (a blank cell): no cursor"),
    0x2B36: (4, "Title_Hook",
             "title loop: lea $C(a7),a7 -> jsr HOOKJT_Title_Hook.w (Title_Hook pops the 12 bytes "
             "of stick(1) / strig(1)'s pushes and $1F92(0)'s): once a pass, after the wait and the "
             "reads, before the cursor and the choice"),
    # Plan 5 Task 5 (src/shim/config.asm): CONFIG's item 1, SCREEN, becomes AUTO FIRE (the jump
    # table's last slot: Config_Hook tells its three sites apart by the return address). The table
    # is now full (21 of 21 up to IO_CONST_SET): a later title hook must share a label (its sites
    # told apart by the return address); the game's hooks have their own table (GAME_HOOKS)
    0x2CF8: (4, "Config_Hook",
             "CONFIG: pea $2C80(pc) (\"SCREEN\", item 1's label) -> jsr HOOKJT_Config_Hook.w: "
             "pushes the string \"AUTO FIRE\" instead"),
    0x2DA6: (4, "Config_Hook",
             "CONFIG loop: pea $4.w (item 1's value: 4 digits) -> jsr HOOKJT_Config_Hook.w: pushes "
             "4 and draws AUTO FIRE's value, ON or OFF (its hex print at $2DBA is a nop)"),
    0x2F52: (4, "Config_Hook",
             "CONFIG: cmp.w #6,d4 (item 1's handler, the table $2EF8's $5A) -> jsr "
             "HOOKJT_Config_Hook.w: Right, Left or A (d4 6, 4, 1) toggle AUTO FIRE; bra.w $2D54 "
             "follows ($2F56)"),
}
# The game's hooks (two-player plan Task 1, src/shim/coop.asm; docs/superpowers/specs/
# 2026-10-28-two-player-design.md): at -> (size, label, why). The 4-byte sites' slots
# are a table of their own (GHOOK_JT: TITLE_HOOKS's slots end at IO_CONST_SET, full); a 6-byte
# site calls its label directly. Each label's first instruction tests SHIM_COOP_2P; at 0 (until
# P2 first joins a game) it does the replaced work alone and writes no game RAM (Coop_Over, once a
# game, also closes the joins: the shim's own RAM; Task 6).
GAME_HOOKS = {
    0x426A: (6, "Coop_Pass",
             "play loop: jsr $6CEC.l (the ship: its move, its death and the game over), the first "
             "of its three calls -> jsr (Coop_Pass).l; 1P: jsr $6CEC, jsr $70A0, jmp $45AE (the "
             "three calls; $45AE's rts returns to $4270: GAME_CODE's bra.s to $427C)"),
    0x7470: (6, "Coop_Tail",
             "$70A0's tail: move.w $2B8AC.l,d0 (the bomb timer; beq.w $757C follows) -> jsr "
             "(Coop_Tail).l; 1P: move.w GV_BOMB,d0, rts (N, Z for the beq)"),
    0x6EFA: (4, "Coop_ShipSlot",
             "$6CEC: pea $1F.w (the ship's sprite call's first argument) -> jsr "
             "GHOOKJT_Coop_ShipSlot.w; 1P: the same long pushed under the return address (CCR "
             "dead: move.l a1,-(a7) at $6F0C sets it before a test)"),
    0x765E: (4, "Coop_Hit",
             "hit test: cmp.w #$1F,d3 (bne.b $76B8 follows) -> jsr GHOOKJT_Coop_Hit.w; 1P: the "
             "cmp, rts (its CCR for the bne)"),
    0x441E: (6, "Coop_Over",
             "the play loop's game over ($4414 found the flag set; once a game): move.l $22200.l,d0 "
             "(the score) -> jsr (Coop_Over).l; 1P: the last look at the join requests (a P2 START "
             "accepted in the last step joins P2, the loop goes on at $40C6; none: the joins "
             "closed), then the move, rts"),
}
# The game's code edits that go with them (two-player plan ruling R5): at -> (new, why), as
# IO_CODE.
# The play loop's other two calls ($70A0, $45AE) are Coop_Pass's now (one hook, one test a step):
# their 12 bytes become a bra.s over them, the rest dead (nops); their relocation words ($4272,
# $4278) are superseded.
GAME_CODE = {
    0x4270: (("600a", Orig(0x1555C, 4), Orig(0x1555C, 4), "4e71"),
             "play loop: jsr $70A0.l; jsr $45AE.l -> bra.s $427C (+ 5 nops, never run): Coop_Pass "
             "(the hook at $426A) makes the three calls, $45AE's rts returns here"),
}
# Each table's SHA1 over its sites' (address, size, bytes) in the tested program (site_digest; the
# sites: digest_sites). `link.py --digests` prints them for the tables as written.
TABLE_SHA1 = {
    "io_code": "cac933e40acb918a2d25e2fa5699353dd9dc6453",
    "title_code": "10ff63255b6f824f1ae1efcc8efee90dff416273",
    "title_hook": "d435b624fc6e171b00d33614c696bee2327889ab",
    "game_hook": "ed5f7b89760343b60f966aa12f04aa0e82acba0d",
    "game_code": "324becac206bbb504aa29cf28040fff3533b764f",
}
# Game routines the shim replaces (Plan 3 Task 3, src/shim/text.asm): name -> entry (base-0).
# Each entry becomes `jmp SHIMJT_<name>` as the XSP C entries do; Shim_<name> keeps the routine's
# stack arguments and register effects (tests/tools/test_text_regs.py) and draws on the Neo Geo.
SHIM_ENTRIES = {
    "Text8": 0x1618,        # (x, y, ch): an 8x8 character into text VRAM (14 callers)
    "Text16": 0x173C,       # (x, y, g): a 16x16 glyph (the bomb icons)
    "TextClear": 0x1888,    # (): clears all of text VRAM
}
# Game variables the shim's replacements use: name -> (base-0 offset, written by the shim[,
# size]): with a size, GV_<name> covers that many bytes, which must lie in one layout object.
SHIM_VARS = {
    "TEXT_SUPER": (0x193A, True),    # the text routines' _B_SUPER(0) return, stored then tested
    "TEXT_FONT": (0x193E, False),    # the font pointer ($160E stores it at the font load)
    "TEXT_R21": (0x1942, True),      # $1888's copy of CRTC R21 (text simultaneous access)
    # the view (Plan 3 Task 7, src/shim/view.asm) reads, never writes:
    "PLAYER_Y": (0x27892, True, 4),  # the ship's y (1/64 px), then its x; the co-op writes both
    "DEATH_TIMER": (0x221A8, False), # 0 while the ship lives; counts up from a hit
    "LIVES": (0x221AC, False),       # spare ships (0: the next death ends the game)
    # the settings' homes the preserved block keeps (Plan 5 Task 2, src/shim/resume.asm Keep_*):
    # read at every save, written back at a title-mode resume
    "XSP_MODE": (0x221F4, True),     # XSP MODE (the start-up's 2; CONFIG no longer sets it)
    "SWAP": (0x221F2, True),         # CONFIG's SHOT/BOMB swap
    "PCM_PLAY": (0x17512, True),     # CONFIG's PCM PLAY number
    "BGM_PLAY": (0x17514, True),     # CONFIG's BGM PLAY number
    "MUTEKI": (0x221F8, True),       # KAKUSI's muteki
    "ACCHOH": (0x221F6, True),       # KAKUSI's acchoh
    "STAGE": (0x221FA, True),        # KAKUSI's stage, CONTINUE's stage
    # the attract demo (Plan 5 Task 4, src/shim/demo.asm) reads, never writes:
    "FRAME": (0x22210, False),       # the game step (cleared at the play loop's entry, +1 a step):
                                     # the demo's stream is keyed to it
    # the co-op (two-player plan, src/shim/coop.asm): the runs it saves, swaps and reads
    "PLAYER_BLK": (0x22196, True, 28),     # the player block
    "PAD": (0x17C8E, True, 4),             # the stored pad bytes ($70A0's strig now, before)
    "SCORE_ADD": (0x221FC, True, 4),
    "SCORE": (0x22200, True, 4),
    "GAMEOVER": (0x2220A, True, 2),
    "BOMB": (0x2B8AC, True, 2),            # the bomb timer
    "SHOT_FREE": (0x22152, True, 60),      # the free-shot stack
    "SHOT_NFREE": (0x2218E, True, 2),      # its count
    "SHOTS": (0x26992, True, 0xF00),       # 30 shots x $80
    "OBJECTS": (0x278A6, False, 0x4000),   # 128 objects x $80 (read only)
}
REGS = ["d%d" % i for i in range(8)] + ["a%d" % i for i in range(7)]
# ROM objects the game reloads from a file after the resume point (layout rule 5, "reloaded file
# data"): object start -> (file under GAME, file offset, how the game reads it). link.py fills
# each with the bytes the game's fread stores there, min(object size, file size - offset) from the
# offset; the rest keeps its snapshot value. On the Neo Geo the bytes are then already in place:
# the shim's _READ into them only compares, and fread's own copies from its stdio buffer write
# the same values (tests/neo/tripwire.lua lets equal writes into these objects through).
FILE_RELOADS = {
    0x1FF52: ("XSP_DAT\\SAM.BG0", 16, "$6512: fopen, four fread(4) header longs, "
              "fread($1FF52, 1, $100) at $6604 (64 bytes: the file's rest)"),
    0x20052: ("XSP_DAT\\SAM.BG1", 16, "$6512: fopen, four fread(4) header longs, "
              "fread($20052, 1, $100) at $6672"),
    0x20152: ("XSP_DAT\\SAM.PAR", 8, "$6512: fopen, two fread(4) header longs, "
              "fread($20152, 1, $2000) at $66B8"),
}

# Sound (Plan 4): the cue table and the tune table (original addresses) and the tunes by tune
# index, from tools/mksound.py (one source); game.inc gets their P-ROM values (sound_equates).
SOUND = {"cue_table": mksound.CUE_TABLE, "tune_table": mksound.TUNE_TABLE,
         "tune_size": mksound.TUNE_SIZE, "tunes": [e for e, _ in mksound.TUNES]}

_md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_000)
_md.detail = True


class LinkError(Exception):
    pass


def _h(v):
    return ("-$%X" % -v) if v < 0 else "$%X" % v


# ------------------------------------------------------------------------- the tables' bytes

HOOK_KINDS = ("title_hook", "game_hook")       # at -> (size, label, why); the others (new, why)


def _pieces(new):
    return (new,) if isinstance(new, str) else tuple(new)


def new_bytes(new, text):
    """A code table's new bytes: its hex pieces, its Orig pieces copied from `text` (the user's
    program, base 0)."""
    out = b""
    for p in _pieces(new):
        if isinstance(p, Orig):
            if p.at < 0 or p.n <= 0 or p.at + p.n > len(text):
                raise LinkError("Orig($%X, %d) is not inside the text" % (p.at, p.n))
            out += bytes(text[p.at:p.at + p.n])
        else:
            out += bytes.fromhex(p)
    return out


def digest_sites(table, kind):
    """{at: size} a table's digest covers: its edit sites and its Orig pieces' sources (one entry
    per address: a source at a site's own address is covered by the larger of the two)."""
    sites = {}

    def add(at, n):
        sites[at] = max(sites.get(at, 0), n)
    for at, v in table.items():
        if kind in HOOK_KINDS:
            add(at, v[0])
            continue
        n = 0
        for p in _pieces(v[0]):
            if isinstance(p, Orig):
                add(p.at, p.n)
                n += p.n
            else:
                n += len(p) // 2
        add(at, n)
    return sites


def site_digest(sites, text):
    """SHA1 of each site's (address, size, bytes) in `text`, in address order."""
    h = hashlib.sha1()
    for at in sorted(sites):
        n = sites[at]
        h.update(struct.pack(">IH", at, n) + bytes(text[at:at + n]))
    return h.hexdigest()


def split_ours(new, text, minimum=3):
    """One literal as pieces: the runs of `minimum` bytes or more found anywhere in `text` (the
    longest at each point) become Orig pieces, the rest stays hex; no hex piece then holds
    `minimum` bytes in a row that `text` has (R-Type Plus's mkpatch.program_ops, one literal)."""
    index = {}
    for k in range(len(text) - minimum + 1):
        index.setdefault(bytes(text[k:k + minimum]), []).append(k)
    out, lit, i, j = [], 0, 0, len(new)
    while i < j:
        best = (0, 0)
        if j - i >= minimum:
            for p in index.get(bytes(new[i:i + minimum]), [])[:256]:
                n = minimum
                while i + n < j and p + n < len(text) and text[p + n] == new[i + n]:
                    n += 1
                if n > best[0]:
                    best = (n, p)
        if best[0]:
            if lit < i:
                out.append(bytes(new[lit:i]).hex())
            out.append(Orig(best[1], best[0]))
            i += best[0]
            lit = i
        else:
            i += 1
    if lit < j:
        out.append(bytes(new[lit:j]).hex())
    return tuple(out)


def table_digests(img, tables):
    """{kind: site_digest} of `tables` ({kind: table}) over the program `img`."""
    return {kind: site_digest(digest_sites(t, kind), img) for kind, t in tables.items()}


class Mapper:
    """Original (base-0) address -> Neo Geo address, through layout.json's objects."""

    def __init__(self, lay):
        self.objs = sorted(lay["objects"], key=lambda o: o["start"])
        self.starts = [o["start"] for o in self.objs]
        self.ends = {o["start"] + o["size"]: o for o in self.objs if o["size"]}
        self.dead = lay["shim_dead"]
        self.dead_size = lay["shim_dead_size"]
        self.end_ptrs = {e["pointer"]: e for e in lay.get("end_pointers", ())}

    def object_at(self, t):
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and t < self.objs[i]["start"] + self.objs[i]["size"]:
            return self.objs[i]
        return None

    def _addr(self, o, off):
        if o["home"] in ("rom", "ram", "stack"):
            return o["addr"] + off, False
        if o["home"] in ("shim", "drop"):
            return self.dead + (off if o["size"] <= self.dead_size else 0), True
        raise LinkError("object %s has home %r" % (_h(o["start"]), o["home"]))

    def map(self, t, ptr=None):
        """(Neo Geo address, info) for target `t`; `ptr` is the pointer word's own offset (for
        layout's end_pointers)."""
        if ptr is not None and ptr in self.end_ptrs:
            e = self.end_ptrs[ptr]
            return e["map_to"], {"how": "end pointer (%s)" % "/".join(e.get("tag", [])),
                                 "dead": False, "object": None, "home": None}
        o = self.object_at(t)
        how = "in"
        if o is None:
            o = self.ends.get(t)
            how = "end of"
            if o is None:
                raise LinkError("address %s is in no object" % _h(t))
        a, dead = self._addr(o, t - o["start"])
        return a, {"how": how, "dead": dead, "object": o["start"], "home": o["home"]}


def fold_io(addrs):
    """{I/O address: access size} -> ({address: shadow address}, clusters). Addresses closer
    than IO_CLUSTER_GAP form a cluster placed whole (from an even start: parity kept)."""
    clusters = []
    for a in sorted(addrs):
        if not IO_LO <= a < IO_HI:
            raise LinkError("$%X is not an I/O address" % a)
        end = a + addrs[a]
        if clusters and a - clusters[-1][1] < IO_CLUSTER_GAP:
            clusters[-1][1] = max(clusters[-1][1], end)
            clusters[-1][2].append(a)
        else:
            clusters.append([a & ~1, end, [a]])
    fold, out, cur = {}, [], 0
    for lo, hi, members in clusters:
        hi += hi & 1
        for a in members:
            fold[a] = IO_SHADOW + cur + (a - lo)
        out.append({"lo": lo, "hi": hi, "shadow": IO_SHADOW + cur, "addrs": members})
        cur += hi - lo
    if cur > IO_SHADOW_SIZE:
        raise LinkError("I/O operands need %d bytes of shadow, %d available: %s" % (
            cur, IO_SHADOW_SIZE, ", ".join("$%X-$%X" % (c["lo"], c["hi"]) for c in out)))
    return fold, out


def _dis(b, at=0):
    try:
        return list(_md.disasm(bytes(b), at))
    except capstone.CsError:
        return []


def _sizes(b, at=0):
    """The sizes of the instructions `b` holds from its start, decoded with room past its end (a
    truncated instruction shows its whole size, capstone's own count stops at the bytes given)."""
    out, pos = [], 0
    while pos < len(b):
        ins = _dis(bytes(b[pos:]) + bytes(10), at + pos)
        if not ins:
            break
        out.append(ins[0].size)
        pos += ins[0].size
    return out


def pcrel_stub(insn, new):
    """The stub for PC-relative instruction bytes `insn` (d16(PC) source operand) reading the
    absolute long `new` instead: the instruction with mode 7/2 turned into 7/1, then rts."""
    ins = _dis(insn[:10])
    if not ins or ins[0].size != len(insn):
        raise LinkError("cannot decode %s" % insn.hex())
    i = ins[0]
    text = ("%s %s" % (i.mnemonic, i.op_str)).strip()
    op = struct.unpack_from(">H", insn)[0]
    if op & 0x3F != 0x3A:
        raise LinkError("%s: not a d16(pc) source operand" % text)
    if re.search(r"\b(a7|sp)\b", i.op_str) or i.mnemonic.split(".")[0] in (
            "pea", "jmp", "jsr", "bsr", "bra", "rtd", "rts", "rte", "link", "unlk"):
        raise LinkError("%s: stack-relative or flow control (jsr to a stub would change it)" % text)
    stub = struct.pack(">HI", (op & ~0x3F) | 0x39, new) + bytes(insn[4:]) + struct.pack(">H", RTS)
    want = re.sub(r"\$[0-9a-f]+\(pc\)", "$%x.l" % new, text)
    got = _dis(stub)
    if len(got) != 2 or got[0].size != len(stub) - 2 or got[1].mnemonic != "rts" or \
            ("%s %s" % (got[0].mnemonic, got[0].op_str)).strip() != want:
        raise LinkError("%s: the absolute form does not decode the same (%s)" % (
            text, ", ".join("%s %s" % (g.mnemonic, g.op_str) for g in got)))
    return stub


def io_operands(code, at):
    """The absolute long I/O operands of the instruction `code` (bytes from `at`):
    ([(offset from the instruction start, address)], text, size); none for register forms."""
    ins = _dis(code[:10], at)
    if not ins:
        raise LinkError("cannot decode the I/O instruction at $%X" % at)
    i = ins[0]
    vals = []
    for o in i.operands:
        if o.type == capstone.m68k.M68K_OP_MEM and \
                o.address_mode == capstone.m68k.M68K_AM_ABSOLUTE_DATA_LONG:
            v = o.imm & 0xFFFFFFFF
            if IO_LO <= v < IO_HI:
                vals.append(v)
    found = [(k, struct.unpack_from(">I", code, k)[0]) for k in range(2, i.size - 3, 2)
             if IO_LO <= struct.unpack_from(">I", code, k)[0] < IO_HI]
    if sorted(v for _, v in found) != sorted(vals):
        raise LinkError("I/O operands at $%X (%s %s): not found uniquely" % (
            at, i.mnemonic, i.op_str))
    return found, ("%s %s" % (i.mnemonic, i.op_str)).strip(), i.size


def _even(v):
    return v + (v & 1)


def imm_operand(code, at, value):
    """Offset (from the instruction start) of the long immediate/absolute `value` in the
    instruction `code` at `at`; LinkError unless found exactly once."""
    ins = _dis(code[:10], at)
    if not ins:
        raise LinkError("cannot decode the instruction at $%X" % at)
    i = ins[0]
    found = [k for k in range(2, i.size - 3, 2) if struct.unpack_from(">I", code, k)[0] == value]
    if len(found) != 1:
        raise LinkError("$%X (%s %s): $%X not found once" % (at, i.mnemonic, i.op_str, value))
    return found[0], ("%s %s" % (i.mnemonic, i.op_str)).strip()


def shadow_of(clusters, a):
    """The shadow address of I/O address `a` inside a folded cluster, else None."""
    for c in clusters:
        if c["lo"] <= a < c["hi"]:
            return c["shadow"] + (a - c["lo"])
    return None


def iosh_image(clusters, io_final):
    """The shadow's starting bytes: each folded register's value at the resume point."""
    size = sum(c["hi"] - c["lo"] for c in clusters)
    img = bytearray(_even(size))
    for w in io_final or ():
        for k in range(w["size"]):
            sh = shadow_of(clusters, w["addr"] + k)
            if sh is not None:
                img[sh - IO_SHADOW] = (w["value"] >> (8 * (w["size"] - 1 - k))) & 0xFF
    return bytes(img)


# Instructions that can run once main resumes: the same set tools/layout.py places by.
reachable = layout._reachable_after_resume


def files_after_resume(img, meta, snap, mem, inv, game_dir):
    """[(NAME, bytes)]: the files named by strings that code reachable after the resume point
    references (lea/pea/move.l # operands), resolved on the disk as Human68k would (relative to
    A:\\GAME). NAME is the path relative to GAME, upper case, backslashes."""
    import x68k_hle
    out = {}
    text = meta["text"]
    for pc in sorted(reachable(img, meta, snap, mem, inv)):
        ins = _dis(img[pc:pc + 10], pc)
        if not ins or ins[0].mnemonic.split(".")[0] not in ("lea", "pea", "move", "movea"):
            continue
        for h in re.findall(r"\$([0-9a-f]+)", ins[0].op_str):
            t = int(h, 16)
            if not 0 <= t < text + meta["data"]:
                continue
            raw = bytes(img[t:t + 128]).split(b"\0")[0]
            if not 4 <= len(raw) < 128 or b"." not in raw or not all(32 < c < 127 for c in raw):
                continue
            path = x68k_hle.resolve(game_dir, raw)
            if path is None:
                continue
            name = os.path.relpath(path, game_dir).replace(os.sep, "\\").upper()
            with open(path, "rb") as f:
                out[name] = f.read()
    return sorted(out.items())


def game_file(game_dir, name):
    """The bytes of GAME file `name` (a Human68k path relative to A:\\GAME, any case)."""
    import x68k_hle
    path = x68k_hle.resolve(game_dir, name.encode("ascii"))
    if path is None:
        raise LinkError("no file %s under %s" % (name, game_dir))
    with open(path, "rb") as f:
        return f.read()


def romfiles_bin(files, at):
    """The ROM file table placed at `at`: count.w, then per file name.l, data.l, size.l (Neo
    Geo addresses), then the names (C strings), then the data (each from an even address)."""
    head = 2 + 12 * len(files)
    names = b"".join(n.encode("ascii") + b"\0" for n, _ in files)
    pos_names = at + head
    pos_data = _even(pos_names + len(names))
    table, blob = bytearray(struct.pack(">H", len(files))), bytearray()
    na = pos_names
    for n, data in files:
        table += struct.pack(">III", na, pos_data + len(blob), len(data))
        na += len(n) + 1
        blob += data + b"\0" * (len(data) & 1)
    out = table + names
    out += b"\0" * (pos_data - at - len(out))
    return bytes(out + blob)


def link(img, meta, snap, mem, below, lay, inv, xsp_text_end=XSP_TEXT_END, game_dir=None,
         io_ptr_shadow=None, io_redirect=None, bgtext=None, shim_entries=None, shim_vars=None,
         io_code=None, sound=None, title_code=None, title_hooks=None, game_hooks=None,
         game_code=None, digests=TABLE_SHA1):
    """Everything link.py produces, in memory (see the module docstring). The bytes come from
    the snapshot (memory.bin holds the text as the start-up left it); `img` (sz2.bin) is the
    program the tables' sites are checked in (`digests`: {kind: SHA1}, TABLE_SHA1's) and their
    Orig pieces copied from."""
    text = meta["text"]
    if len(img) < text:
        raise LinkError("sz2.bin is shorter than its text")
    relocs = set(meta["relocs"])
    io_ptr_shadow = IO_PTR_SHADOW if io_ptr_shadow is None else io_ptr_shadow
    io_redirect = IO_REDIRECT if io_redirect is None else io_redirect
    shim_entries = SHIM_ENTRIES if shim_entries is None else shim_entries
    shim_vars = SHIM_VARS if shim_vars is None else shim_vars
    io_code = IO_CODE if io_code is None else io_code
    title_code = TITLE_CODE if title_code is None else title_code
    title_hooks = TITLE_HOOKS if title_hooks is None else title_hooks
    game_hooks = GAME_HOOKS if game_hooks is None else game_hooks
    game_code = GAME_CODE if game_code is None else game_code
    sound = SOUND if sound is None else sound
    # the tables' sites hold the tested bytes (one SHA1 a table: see the module docstring)
    tables = {"io_code": io_code, "title_code": title_code, "title_hook": title_hooks,
              "game_hook": game_hooks, "game_code": game_code}
    for kind, table in tables.items():
        sites = digest_sites(table, kind)
        got, want = site_digest(sites, img), digests.get(kind)
        if got != want:
            raise LinkError("%s: the bytes at its %d sites are not the tested ones (SHA1 %s, "
                            "expected %s): a site or size changed, or not this disk" % (
                                kind, len(sites), got, want))
    prog = bytes(img[:text])
    mp = Mapper(lay)
    if lay["game_rom"] != GAME_ROM:
        raise LinkError("layout's game_rom is $%X" % lay["game_rom"])
    rom_end = lay["rom_end"]
    game = bytearray(b"\xFF" * (rom_end - GAME_ROM))
    game[0:text] = mem[0:text]
    ram_used = lay["ram_used"]
    ramimage = bytearray(ram_used + (ram_used & 1))
    blo = snap["layout"]["below_base_bin"][0]

    def src(start, n):
        if start >= 0:
            if start + n > len(mem):
                raise LinkError("object %s past memory.bin" % _h(start))
            return mem[start:start + n]
        if start + n > 0 or start < blo:
            raise LinkError("object %s crosses the base" % _h(start))
        return below[start - blo:start - blo + n]

    ram_table = []
    for o in mp.objs:
        if o["region"] == "text" and o["home"] == "rom" and o["addr"] != GAME_ROM + o["start"]:
            raise LinkError("text ROM object %s at $%X, not in place at $%X" % (
                _h(o["start"]), o["addr"], GAME_ROM + o["start"]))
        if o["home"] == "rom" and o["region"] != "text":
            a = o["addr"] - GAME_ROM
            if a < text or a + o["size"] > lay["shim_dead"] - GAME_ROM:
                raise LinkError("ROM object %s at $%X outside the ROM objects' area" % (
                    _h(o["start"]), o["addr"]))
            game[a:a + o["size"]] = src(o["start"], o["size"])
        elif o["home"] == "ram":
            a = o["addr"] - RAM_LO
            if a < 0 or a + o["size"] > ram_used:
                raise LinkError("RAM object %s at $%X outside the RAM used" % (
                    _h(o["start"]), o["addr"]))
            ramimage[a:a + o["size"]] = src(o["start"], o["size"])
            ram_table.append({"start": o["start"], "size": o["size"], "addr": o["addr"],
                              "area": o.get("area")})
    sd = lay["shim_dead"] - GAME_ROM
    game[sd:sd + lay["shim_dead_size"]] = b"\xFF" * lay["shim_dead_size"]

    # ROM objects the game reloads from files: the bytes its freads store (FILE_RELOADS)
    reloads = []
    for o in mp.objs:
        if o["home"] != "rom" or not o.get("why", "").startswith("rule 5: reloaded file"):
            continue
        if o["start"] not in FILE_RELOADS:
            raise LinkError("ROM object %s holds reloaded file data: no FILE_RELOADS entry" %
                            _h(o["start"]))
        if game_dir is None:
            continue
        name, off, _ = FILE_RELOADS[o["start"]]
        data = game_file(game_dir, name)[off:off + o["size"]]
        if not data:
            raise LinkError("%s has no bytes at offset %d" % (name, off))
        a = o["addr"] - GAME_ROM
        game[a:a + len(data)] = data
        reloads.append({"object": o["start"], "addr": o["addr"], "file": name, "offset": off,
                        "size": len(data)})

    # the stack: sp .. the original's top, at the same distance below the Neo Geo stack top
    st = lay["stack"]
    sp, otop = snap["sp"], st["orig"][1]
    sobj = mp.object_at(sp)
    if sobj is None or sobj["home"] != "stack" or sobj["start"] + sobj["size"] != otop:
        raise LinkError("sp %s is not in the stack object" % _h(sp))
    new_sp = st["top"] - (otop - sp)
    if mp.map(sp)[0] != new_sp:
        raise LinkError("the stack object does not end at the stack top")
    stack = bytearray(mem[sp:otop])

    patches = []
    touched = {}          # (where, offset) -> patch kind: no byte is patched twice

    def where_of(w, n):
        """Where the bytes [w, w + n) are emitted: (where, buffer, offset, Neo Geo address)."""
        o = mp.object_at(w)
        if o is None or w + n > o["start"] + o["size"]:
            raise LinkError("word %s is not inside one object" % _h(w))
        off = w - o["start"]
        h = o["home"]
        if h == "rom":
            return "game", game, o["addr"] - GAME_ROM + off, o["addr"] + off
        if h == "ram":
            return "ram", ramimage, o["addr"] - RAM_LO + off, o["addr"] + off
        if h == "stack":
            if sp <= w < otop:
                return "stack", stack, w - sp, new_sp + (w - sp)
            return None
        return None

    def touch(wh, off, n, kind):
        for k in range(off, off + n):
            if (wh, k) in touched:
                raise LinkError("%s patch at %s offset $%X overlaps a %s patch" % (
                    kind, wh, k, touched[(wh, k)]))
            touched[(wh, k)] = kind

    def site_old(kind, at, n, buf, off):
        """The user's bytes at a table's site (the digest checked them in sz2.bin): the snapshot
        must hold the same (the start-up changes no code)."""
        old = bytes(buf[off:off + n])
        if old != prog[at:at + n]:
            raise LinkError("%s $%X: the snapshot holds %s, the program %s" % (
                kind, at, old.hex(), prog[at:at + n].hex()))
        return old

    # --- XSP C entries (first: relocation words under them are superseded)
    xsp_entries = snap["xsp_entries"]
    xsp_bytes = set()
    for name, a in xsp_entries.items():
        ok = inv.get("xsp", {}).get(name) == a or \
            inv.get("xsp_unmatched", {}).get(name, {}).get("best", {}).get("at") == a
        if not ok:
            raise LinkError("XSP entry %s at $%X: no inventory xsp/xsp_unmatched entry" % (name, a))
        xsp_bytes |= set(range(a, a + 6))
    order = sorted(xsp_entries, key=lambda n: xsp_entries[n])
    sorder = sorted(shim_entries, key=lambda n: shim_entries[n])
    hooks = sorted(title_hooks.items())
    labels = sorted({v[1] for v in title_hooks.values()})      # one slot per label
    if XSP_JT + 6 * (len(order) + len(sorder) + len(labels)) > min(IO_CONST_SET, IO_CONST_CLR):
        raise LinkError("%d XSP entries, %d shim entries and %d hooks do not fit the jump table" % (
            len(order), len(sorder), len(labels)))
    for name in sorder:
        a = shim_entries[name]
        if not xsp_text_end <= a < text:
            raise LinkError("shim entry %s at $%X is not in the game's text" % (name, a))
        if xsp_bytes & set(range(a, a + 6)):
            raise LinkError("shim entry %s at $%X overlaps an XSP entry" % (name, a))
        xsp_bytes |= set(range(a, a + 6))
    xsp_jt, xsp_addr, shim_jt, shim_addr = {}, {}, {}, {}
    for k, (kind, name) in enumerate([("xsp_entry", n) for n in order] +
                                     [("shim_entry", n) for n in sorder]):
        a = xsp_entries[name] if kind == "xsp_entry" else shim_entries[name]
        slot = XSP_JT + 6 * k
        loc = where_of(a, 6)
        if loc is None or loc[0] != "game" or a >= text:
            raise LinkError("%s %s at $%X is not in the text in ROM" % (kind, name, a))
        wh, buf, off, addr = loc
        old = bytes(buf[off:off + 6])
        buf[off:off + 6] = struct.pack(">HI", JMP_L, slot)
        touch(wh, off, 6, kind)
        if kind == "xsp_entry":
            xsp_jt[name], xsp_addr[name] = slot, addr
            new, meaning = "jmp $%X (XSPJT_%s)" % (slot, name), \
                "XSP C entry %s -> the shim's jump table" % name
        else:
            shim_jt[name], shim_addr[name] = slot, addr
            new, meaning = "jmp $%X (SHIMJT_%s)" % (slot, name), \
                "game routine $%X -> the shim's Shim_%s (jump table)" % (a, name)
        patches.append({"kind": kind, "where": wh, "orig": a, "addr": addr, "words": 3,
                        "old": old.hex(), "new": new, "meaning": meaning})
    hook_jt, hook_addr = {}, {}
    hook_words = sorted(relocs | set(snap["pointers"]) | set(snap.get("pointers_below_base", ())))
    for at, (n, label, why) in hooks:
        slot = XSP_JT + 6 * (len(order) + len(sorder) + labels.index(label))
        if n != 4:
            raise LinkError("title_hook $%X: %d bytes, not 4 (jsr abs.w)" % (at, n))
        if not xsp_text_end <= at or at + 4 > text:
            raise LinkError("title_hook $%X is not in the game's text" % at)
        if any(w < at + 4 and w + 4 > at for w in hook_words):
            raise LinkError("title_hook $%X: a relocation or pointer word lies under it" % at)
        loc = where_of(at, 4)
        if loc is None or loc[0] != "game":
            raise LinkError("title_hook $%X is not in ROM" % at)
        wh, buf, off, addr = loc
        old = site_old("title_hook", at, 4, buf, off)
        buf[off:off + 4] = struct.pack(">HH", JSR_W, slot)
        touch(wh, off, 4, "title_hook")
        hook_jt[label] = slot
        hook_addr.setdefault(label, []).append(addr)
        patches.append({"kind": "title_hook", "where": wh, "at": at, "orig": at, "addr": addr,
                        "words": 2, "old": old.hex(),
                        "new": "jsr $%X.w (HOOKJT_%s: jmp %s)" % (slot, label, label),
                        "meaning": why})
    # --- the game's hooks (GAME_HOOKS): 4-byte sites through their own jump table at GHOOK_JT,
    # 6-byte sites calling their label directly (game.asm assembles the jsr)
    ghooks = sorted(game_hooks.items())
    glabels = sorted({v[1] for v in game_hooks.values() if v[0] == 4})        # a slot per label
    if len(glabels) > GHOOK_MAX:
        raise LinkError("%d game hook labels do not fit the game hooks' jump table (%d slots)" % (
            len(glabels), GHOOK_MAX))
    ghook_jt, ghook_addr, ghook_calls = {}, {}, []
    for at, (n, label, why) in ghooks:
        if n not in (4, 6):
            raise LinkError("game_hook $%X: %d bytes, not 4 (jsr abs.w) or 6 (jsr abs.l)" % (at, n))
        if not xsp_text_end <= at or at + n > text:
            raise LinkError("game_hook $%X is not in the game's text" % at)
        under = [w for w in hook_words if w < at + n and w + 4 > at]
        if n == 4 and under:
            raise LinkError("game_hook $%X: a relocation or pointer word lies under it" % at)
        if n == 6 and set(under) - {at + 2}:
            raise LinkError("game_hook $%X: words under it at %s, not only at + 2" % (
                at, ", ".join("$%X" % w for w in under)))
        if n == 6 and at + 2 not in relocs:
            raise LinkError("game_hook $%X: no relocation word at + 2" % at)
        loc = where_of(at, n)
        if loc is None or loc[0] != "game":
            raise LinkError("game_hook $%X is not in ROM" % at)
        wh, buf, off, addr = loc
        old = site_old("game_hook", at, n, buf, off)
        ins = _dis(old, at)
        if _sizes(old, at) != [n]:
            raise LinkError("game_hook $%X: %s is not one instruction" % (at, old.hex()))
        op = struct.unpack_from(">H", old)[0]
        if n == 6 and not (op == JSR_L or (op >> 12 in (1, 2, 3) and op & 0x3F == 0x39)):
            raise LinkError("game_hook $%X: %s %s is not jsr abs.l or a move from abs.l" % (
                at, ins[0].mnemonic, ins[0].op_str))
        if n == 4:
            slot = GHOOK_JT + 6 * glabels.index(label)
            buf[off:off + 4] = struct.pack(">HH", JSR_W, slot)
            new = "jsr $%X.w (GHOOKJT_%s: jmp %s)" % (slot, label, label)
            ghook_jt[label] = slot
        else:
            buf[off:off + 6] = struct.pack(">HI", JSR_L, 0)    # game.asm: jsr (<label>).l
            new = "jsr (%s).l (game.asm)" % label
            ghook_calls.append((addr, label))
            xsp_bytes |= set(range(at, at + 6))      # its relocation word: superseded
        touch(wh, off, n, "game_hook")
        ghook_addr.setdefault(label, []).append(addr)
        patches.append({"kind": "game_hook", "where": wh, "at": at, "orig": at, "addr": addr,
                        "words": n // 2, "old": old.hex(), "new": new, "meaning": why})
    for at, (new, why) in sorted(game_code.items()):
        new = new_bytes(new, prog)
        n = len(new)
        if not n or n & 1:
            raise LinkError("game_code $%X: %d bytes, not whole words" % (at, n))
        if not xsp_text_end <= at or at + n > text:
            raise LinkError("game_code $%X is not in the game's text" % at)
        under = [w for w in hook_words if w < at + n and w + 4 > at]
        if any(w < at or w + 4 > at + n or w not in relocs for w in under):
            raise LinkError("game_code $%X: a word under it is not a relocation word inside it" %
                            at)
        loc = where_of(at, n)
        if loc is None or loc[0] != "game":
            raise LinkError("game_code $%X is not in ROM" % at)
        wh, buf, off, addr = loc
        old = site_old("game_code", at, n, buf, off)
        for b in (old, new):
            if sum(_sizes(b, at)) != n:
                raise LinkError("game_code $%X: %s is not whole instructions" % (at, b.hex()))
        buf[off:off + n] = new
        xsp_bytes |= set(range(at, at + n))          # its relocation words: superseded
        touch(wh, off, n, "game_code")
        text_new = "; ".join("%s %s" % (i.mnemonic, i.op_str) if i.op_str else i.mnemonic
                             for i in _md.disasm(new, at))
        patches.append({"kind": "game_code", "where": wh, "at": at, "orig": at, "addr": addr,
                        "words": n // 2, "old": old.hex(), "new": text_new, "meaning": why})

    gvars = {}
    for name, v in sorted(shim_vars.items()):
        off, writes = v[:2]
        size = v[2] if len(v) > 2 else 1
        try:
            new, info = mp.map(off)
        except LinkError as e:
            raise LinkError("shim variable %s ($%X): %s" % (name, off, e))
        if info["home"] not in ("rom", "ram") or (writes and info["home"] != "ram"):
            raise LinkError("shim variable %s ($%X) is %s, the shim %s it" % (
                name, off, info["home"], "writes" if writes else "reads"))
        o = mp.object_at(off)
        if size > 1 and (o is None or off + size > o["start"] + o["size"]):
            raise LinkError("shim variable %s ($%X, %d bytes) crosses its object's end" % (
                name, off, size))
        gvars[name] = new

    # --- game code reaching I/O through a register: the instruction replaced (IO_CODE)
    words = sorted(relocs | set(snap["pointers"]) | set(snap.get("pointers_below_base", ())))
    for kind, table in (("io_code", io_code), ("title_code", title_code)):
        for at in sorted(table):
            new, why = table[at]
            new = new_bytes(new, prog)
            n = len(new)
            if not n or n & 1:
                raise LinkError("%s $%X: %d bytes, not whole words" % (kind, at, n))
            if not xsp_text_end <= at or at + n > text:
                raise LinkError("%s $%X is not in the game's text" % (kind, at))
            if any(w < at + n and w + 4 > at for w in words):
                raise LinkError("%s $%X: a relocation or pointer word lies under it" % (kind, at))
            loc = where_of(at, n)
            if loc is None or loc[0] != "game":
                raise LinkError("%s $%X is not in ROM" % (kind, at))
            wh, buf, off, addr = loc
            old = site_old(kind, at, n, buf, off)
            buf[off:off + n] = new
            touch(wh, off, n, kind)
            text_new = "; ".join("%s %s" % (i.mnemonic, i.op_str) if i.op_str else i.mnemonic
                                 for i in _md.disasm(new, at))
            patches.append({"kind": kind, "where": wh, "at": at, "orig": at, "addr": addr,
                            "words": n // 2, "old": old.hex(), "new": text_new, "meaning": why})

    # --- relocation words and snapshot pointers
    tags = {int(k): v for k, v in snap.get("pointer_tags", {}).items()}
    superseded, not_emitted, dead = [], [], []
    for w in words:
        if xsp_bytes & set(range(w, w + 4)):
            superseded.append(w)
            continue
        loc = where_of(w, 4)
        if loc is None:
            not_emitted.append(w)
            continue
        wh, buf, off, addr = loc
        raw = struct.unpack_from(">I", buf, off)[0]
        t = raw & 0xFFFFFF
        t = t - 0x1000000 if t & 0x800000 else t
        if w not in tags and raw != t & 0xFFFFFFFF:
            raise LinkError("pointer word %s holds $%08X (top byte not a sign)" % (_h(w), raw))
        try:
            new, info = mp.map(t, w)
        except LinkError as e:
            raise LinkError("pointer word %s: %s" % (_h(w), e))
        if w in tags:
            new = (tags[w] << 24) | (new & 0xFFFFFF)
        struct.pack_into(">I", buf, off, new)
        touch(wh, off, 4, "pointer")
        kind = "reloc" if w in relocs else "pointer"
        meaning = "%s %s" % (info["how"], _h(info["object"])) if info["object"] is not None \
            else info["how"]
        if info["home"]:
            meaning += " (%s)" % info["home"]
        p = {"kind": kind, "where": wh, "orig": w, "addr": addr, "words": 2,
             "old": t, "new": new, "meaning": meaning}
        if info["dead"]:
            p["dead"] = True
            dead.append({"word": w, "target": t, "object": info["object"], "home": info["home"],
                         "map": new})
        if w in tags:
            p["tag"] = tags[w]
        patches.append(p)

    # --- I/O operands (game and library code): absolute long operands only. Sites that reach
    # I/O through a register (inventory's register tracking) have nothing to fold here: listed.
    sites, io_sizes, io_register = [], {}, []
    for at in sorted({e["at"] for e in inv.get("io", ()) if e["at"] >= xsp_text_end}):
        if at >= text:
            raise LinkError("I/O site $%X outside the text" % at)
        found, itext, n = io_operands(game[at:at + 10], at)
        if not found:
            io_register.append({"at": at, "insn": itext,
                                "addrs": sorted({e["addr"] for e in inv["io"] if e["at"] == at})})
            continue
        size = {"b": 1, "w": 2, "l": 4}.get(itext.split(" ")[0].partition(".")[2], 2)
        for _, v in found:
            io_sizes[v] = max(io_sizes.get(v, 0), size)
        sites.append((at, found, itext))
    fold, clusters = fold_io(io_sizes) if io_sizes else ({}, [])
    unknown = set(io_redirect) - {at for at, _, _ in sites}
    if unknown:
        raise LinkError("I/O redirect sites %s: no absolute I/O operand there" % ", ".join(
            "$%X" % a for a in sorted(unknown)))
    for at, found, itext in sites:
        for k, v in found:
            loc = where_of(at + k, 4)
            if loc is None or loc[0] != "game":
                raise LinkError("I/O site $%X is not in ROM" % at)
            wh, buf, off, addr = loc
            new, meaning = fold[v], "%s: $%X -> I/O shadow" % (itext, v)
            if at in io_redirect:
                new = io_redirect[at]
                meaning = "%s: $%X -> redirected to $%X (%s)" % (itext, v, new, IO_REDIRECT_WHY)
            struct.pack_into(">I", buf, off, new)
            touch(wh, off, 4, "io")
            patches.append({"kind": "io", "where": wh, "at": at, "orig": at + k, "addr": addr,
                            "words": 2, "old": v, "new": new, "meaning": meaning})
    io_ptr = [e for e in inv.get("io_ptr", ()) if e["at"] >= xsp_text_end]
    by_site = {e["at"]: e for e in io_ptr}
    for at in sorted(io_ptr_shadow):
        e = by_site.get(at)
        if e is None:
            raise LinkError("io_ptr site $%X is not in inventory's io_ptr" % at)
        sh = shadow_of(clusters, e["addr"])
        if sh is None:
            raise LinkError("io_ptr site $%X: $%X is in no folded cluster" % (at, e["addr"]))
        k, itext = imm_operand(game[at:at + 10], at, e["addr"])
        loc = where_of(at + k, 4)
        if loc is None or loc[0] != "game":
            raise LinkError("io_ptr site $%X is not in ROM" % at)
        wh, buf, off, addr = loc
        struct.pack_into(">I", buf, off, sh)
        touch(wh, off, 4, "io_ptr")
        patches.append({"kind": "io_ptr", "where": wh, "at": at, "orig": at + k, "addr": addr,
                        "words": 2, "old": e["addr"], "new": sh,
                        "meaning": "%s: base -> I/O shadow (%s)" % (itext, io_ptr_shadow[at])})
    iosh = iosh_image(clusters, snap.get("io_final"))

    # --- PC-relative reads of text variables now outside the text
    stubs = bytearray()
    stub_at = {}
    for f in lay.get("pcrel_fixups", ()):
        at, n = f["at"], f["size"]
        if n < 4 or n & 1:
            raise LinkError("PC-relative site $%X is %d bytes" % (at, n))
        new, info = mp.map(f["target"])
        if f.get("addr") is not None and new != f["addr"] + (f["target"] - f["object"]):
            raise LinkError("PC-relative site $%X: layout and link disagree" % at)
        insn = bytes(mem[at:at + n])
        stub = pcrel_stub(insn, new)
        if stub not in stub_at:
            stub_at[stub] = PCREL_STUBS + len(stubs)
            stubs += stub
        s = stub_at[stub]
        loc = where_of(at, n)
        if loc is None or loc[0] != "game":
            raise LinkError("PC-relative site $%X is not in ROM" % at)
        wh, buf, off, addr = loc
        buf[off:off + n] = struct.pack(">HH", JSR_W, s) + struct.pack(">H", NOP) * ((n - 4) // 2)
        touch(wh, off, n, "pcrel")
        patches.append({"kind": "pcrel", "where": wh, "at": at, "orig": at, "addr": addr,
                        "words": n // 2, "old": f.get("insn", insn.hex()),
                        "new": "jsr $%X.w" % s + " + nop" * ((n - 4) // 2),
                        "meaning": "stub at $%X reads $%X (%s %s)" % (
                            s, new, info["home"], _h(info["object"]))})
    if len(stubs) > PCREL_STUBS_SIZE:
        raise LinkError("PC-relative stubs: %d bytes, %d reserved" % (len(stubs), PCREL_STUBS_SIZE))

    # --- registers and the resume point
    regs = {}
    for r in REGS:
        v = snap["regs"][r]
        if r in snap.get("pointer_regs", ()):
            regs[r] = mp.map(v)[0]
        else:
            regs[r] = v & 0xFFFFFFFF
    io_regs = {r: regs[r] for r in REGS
               if r not in snap.get("pointer_regs", ()) and IO_LO <= regs[r] < IO_HI}
    resume, rinfo = mp.map(snap["resume_pc"])
    if rinfo["home"] != "rom" or not snap["resume_pc"] < text:
        raise LinkError("the resume pc is not in the text in ROM")

    # the PSP (a5 = PSP + $10; DOS _GETPDB) and the XSP state the start-up set
    psp = next((o for o in mp.objs if o.get("area") == "psp"), None)
    psp_addr = mp.map(psp["start"])[0] if psp else 0
    xsp_init = {}
    try:
        import x68k_hle
        xsp_args = x68k_hle.XSP_ARGS
    except ImportError:                 # no unicorn: argument kinds unknown, pointers unmapped
        xsp_args = {}
    for c in sorted(snap.get("xsp_calls", ()), key=lambda c: c["seq"]):
        kinds = dict(xsp_args.get(c["name"], ()))
        if c["name"] in ("xsp_on", "xsp_off"):
            xsp_init["xsp_on"] = 1 if c["name"] == "xsp_on" else 0
        for an, v in (c.get("args") or {}).items():
            if kinds.get(an) == "ptr":
                v = mp.map(v)[0]
            xsp_init["%s_%s" % (c["name"], an)] = v & 0xFFFFFFFF

    files = files_after_resume(img, meta, snap, mem, inv, game_dir) if game_dir else []

    linkdata = _even(rom_end)
    regs_at = linkdata
    stack_at = regs_at + 4 * len(REGS)
    ram_at = _even(stack_at + len(stack))
    iosh_at = _even(ram_at + len(ramimage))
    files_at = _even(iosh_at + len(iosh))
    romfiles = romfiles_bin(files, files_at)
    # BG text page as the game-start loader reads it back (preinit's bgtext.bin): _BGTEXTGT
    bgtext = bgtext or b""
    bgtext_page = snap.get("game_start", {}).get("page", 0xFFFF) if bgtext else 0xFFFF
    bgtext_at = _even(files_at + len(romfiles))
    end = bgtext_at + len(bgtext)
    if end > P1_END:
        raise LinkError("the link data ends at $%X, past P1" % end)
    snd = sound_equates(mp, game, ramimage, sound)
    return {
        "sound": snd, "sound_tunes": list(sound["tunes"]) if sound else [],
        "game": bytes(game), "ramimage": bytes(ramimage), "stack": bytes(stack),
        "stubs": bytes(stubs), "regs": regs, "sp": new_sp, "sr": snap.get("sr", 0),
        "resume": resume, "xsp_jt": xsp_jt, "xsp_addr": xsp_addr, "shim_jt": shim_jt,
        "shim_addr": shim_addr, "hook_jt": hook_jt, "hook_addr": hook_addr,
        "title_hooks": {at: title_hooks[at][2] for at in sorted(title_hooks)},
        "ghook_jt": ghook_jt, "ghook_addr": ghook_addr, "ghook_calls": sorted(ghook_calls),
        "game_hooks": {at: game_hooks[at][2] for at in sorted(game_hooks)},
        "game_code": {at: game_code[at][1] for at in sorted(game_code)},
        "shim_vars": gvars, "io_fold": fold,
        "io_clusters": clusters, "io_register": io_register, "io_ptr": io_ptr,
        "io_regs": io_regs, "iosh_image": iosh, "iosh_at": iosh_at,
        "io_code": {at: io_code[at][1] for at in sorted(io_code)},
        "title_code": {at: title_code[at][1] for at in sorted(title_code)},
        "rom_files": files, "romfiles": romfiles, "romfiles_at": files_at,
        "file_reloads": reloads, "psp": psp_addr,
        "bgtext": bgtext, "bgtext_at": bgtext_at, "bgtext_page": bgtext_page, "xsp_init": xsp_init,
        "patches": patches, "superseded": superseded,
        "not_emitted": not_emitted, "dead": dead, "ram_table": ram_table,
        "linkdata": linkdata, "regs_at": regs_at, "stack_at": stack_at, "ram_at": ram_at,
        "linkdata_end": end, "ram_used": ram_used, "rom_end": rom_end,
        "shim_dead": lay["shim_dead"], "shim_dead_size": lay["shim_dead_size"],
        "ram_end_addr": lay.get("ram_end_addr", RAM_LO + ram_used),
    }


def emitted_long(mp, game, ramimage, t):
    """The long at original address `t` as the cart holds it (game.bin or the RAM image), patched."""
    o = mp.object_at(t)
    if o is None or t + 4 > o["start"] + o["size"]:
        raise LinkError("long %s is not inside one object" % _h(t))
    a = mp.map(t)[0]
    if o["home"] == "rom":
        return struct.unpack_from(">I", game, a - GAME_ROM)[0]
    if o["home"] == "ram":
        return struct.unpack_from(">I", ramimage, a - RAM_LO)[0]
    raise LinkError("long %s is in a %s object" % (_h(t), o["home"]))


def sound_equates(mp, game, ramimage, sound):
    """SND_CUE_TABLE and SND_TUNE_PTR_<t> (module doc); {} when `sound` is empty."""
    if not sound:
        return {}
    o = mp.object_at(sound["cue_table"])
    if o is None or o["home"] != "rom":
        raise LinkError("the cue table %s is not in ROM" % _h(sound["cue_table"]))
    eq = {"SND_CUE_TABLE": mp.map(sound["cue_table"])[0]}
    for i, entry in enumerate(sound["tunes"]):
        ptr = emitted_long(mp, game, ramimage, sound["tune_table"] + sound["tune_size"] * entry)
        if not ptr:
            raise LinkError("tune $%02X has no data pointer" % entry)
        eq["SND_TUNE_PTR_%d" % i] = ptr
    return eq


def load(orig_dir, preinit_dir, layout_path):
    def rj(p):
        with open(p) as f:
            return json.load(f)

    def rb(p):
        with open(p, "rb") as f:
            return f.read()
    return {"img": rb(os.path.join(orig_dir, "sz2.bin")),
            "meta": rj(os.path.join(orig_dir, "sz2.json")),
            "inv": rj(os.path.join(orig_dir, "inventory.json")),
            "snap": rj(os.path.join(preinit_dir, "snapshot.json")),
            "mem": rb(os.path.join(preinit_dir, "memory.bin")),
            "below": rb(os.path.join(preinit_dir, "below_base.bin")),
            "bgtext": rb(os.path.join(preinit_dir, "bgtext.bin")),
            "lay": rj(layout_path),
            "game_dir": os.path.join(orig_dir, "disk", "GAME")}


# ------------------------------------------------------------------------------------ output

def _equ(name, v, note=""):
    return "%-24s EQU $%08X%s" % (name, v, ("   ; " + note) if note else "")


def render_inc(r):
    L = ["; generated by tools/link.py - do not edit (make link)",
         "; The game's pieces on the Neo Geo: where they are, what the shim copies at boot.", "",
         "; --- P-ROM", _equ("GAME_ROM", GAME_ROM, "relocated text, then the ROM objects"),
         _equ("GAME_ROM_END", r["rom_end"], "end of game.bin"),
         _equ("SHIM_DEAD", r["shim_dead"], "every reference to shim/drop objects lands here"),
         _equ("SHIM_DEAD_SIZE", r["shim_dead_size"]),
         _equ("LINKDATA", r["linkdata"], "GAME_REGS, stack image, RAM image"),
         _equ("LINKDATA_END", r["linkdata_end"]),
         "", "; --- resume state (main's first title-menu call)",
         _equ("GAME_RESUME", r["resume"], "jump here with the registers and SP below"),
         _equ("GAME_SP", r["sp"], "the stack image goes here (up to STACK_TOP)"),
         _equ("GAME_SR", r["sr"], "the original's SR at the resume point (user mode)"),
         _equ("GAME_REGS", r["regs_at"], "15 longs: movem.l GAME_REGS, d0-d7/a0-a6"),
         _equ("GAME_REGS_COUNT", len(REGS)),
         _equ("GAME_STACK_IMAGE", r["stack_at"], "ROM copy of the live stack"),
         _equ("GAME_STACK_SIZE", len(r["stack"])),
         _equ("RAMIMAGE_ROM", r["ram_at"], "ROM copy of the RAM objects"),
         _equ("RAMIMAGE_DEST", RAM_LO),
         _equ("RAMIMAGE_SIZE", len(r["ramimage"])),
         _equ("GAME_RAM_END", r["ram_end_addr"], "end of the game RAM used (malloc arena)"),
         _equ("GAME_PSP", r["psp"], "the PSP object (a5 = PSP + $10; DOS _GETPDB)"),
         "", "; --- ROM file table (romfiles.bin): count.w, then name.l, data.l, size.l per file",
         _equ("ROMFILES", r["romfiles_at"]),
         _equ("ROMFILES_COUNT", len(r["rom_files"]), ", ".join(n for n, _ in r["rom_files"])),
         "", "; --- BG text page as the game-start loader reads it back (_BGTEXTGT; bgtext.bin):",
         ";     64 x 64 words, row-major; BGTEXT_PAGE $FFFF = none",
         _equ("BGTEXT", r["bgtext_at"]), _equ("BGTEXT_PAGE", r["bgtext_page"]),
         _equ("BGTEXT_SIZE", len(r["bgtext"])),
         "", "; --- low P-ROM reserved for the link (the shim places nothing here)",
         _equ("XSP_JT", XSP_JT, "6-byte jmp slots, filled by game.asm"),
         _equ("XSP_JT_SIZE", XSP_JT_SIZE),
         _equ("PCREL_STUBS", PCREL_STUBS, "stubs.bin"),
         _equ("PCREL_STUBS_SIZE", PCREL_STUBS_SIZE),
         _equ("PCREL_STUBS_USED", len(r["stubs"])),
         _equ("GHOOK_JT", GHOOK_JT, "6-byte jmp slots of the game hooks, filled by game.asm"),
         _equ("GHOOK_JT_SIZE", 0x8000 - GHOOK_JT),
         "", "; --- XSP C entries: XSP_<name> = the entry in game ROM (now jmp XSPJT_<name>)"]
    for name in sorted(r["xsp_jt"], key=lambda n: r["xsp_jt"][n]):
        L.append(_equ("XSP_" + name, r["xsp_addr"][name]))
        L.append(_equ("XSPJT_" + name, r["xsp_jt"][name], "jmp Shim_%s" % name))
    L += ["", "; --- game routines the shim replaces: GAME_<name> = the entry in game ROM (now",
          ";     jmp SHIMJT_<name>), SHIMJT_<name> = its jump-table slot (jmp Shim_<name>)"]
    for name in sorted(r["shim_jt"], key=lambda n: r["shim_jt"][n]):
        L.append(_equ("GAME_" + name, r["shim_addr"][name]))
        L.append(_equ("SHIMJT_" + name, r["shim_jt"][name], "jmp Shim_%s" % name))
    L += ["", "; --- the title's hooks (link.py TITLE_HOOKS): HOOK_<label>_<n> = its sites in game ROM",
          ";     (now jsr HOOKJT_<label>.w), HOOKJT_<label> = its jump-table slot (jmp <label>)"]
    for name in sorted(r["hook_jt"], key=lambda n: r["hook_jt"][n]):
        for n, a in enumerate(r["hook_addr"][name]):
            L.append(_equ("HOOK_%s_%d" % (name, n), a))
        L.append(_equ("HOOKJT_" + name, r["hook_jt"][name], "jmp %s" % name))
    L += ["", "; --- the game's hooks (link.py GAME_HOOKS): GHOOK_<label>_<n> = its sites in game",
          ";     ROM (jsr (<label>).l, or jsr GHOOKJT_<label>.w), GHOOKJT_<label> = its GHOOK_JT",
          ";     slot (jmp <label>) where it has a 4-byte site"]
    for name in sorted(r["ghook_addr"]):
        for n, a in enumerate(r["ghook_addr"][name]):
            L.append(_equ("GHOOK_%s_%d" % (name, n), a))
        if name in r["ghook_jt"]:
            L.append(_equ("GHOOKJT_" + name, r["ghook_jt"][name], "jmp %s" % name))
    L += ["", "; --- game variables the shim's replacements use (Neo Geo addresses)"]
    for name in sorted(r["shim_vars"]):
        L.append(_equ("GV_" + name, r["shim_vars"][name]))
    L += ["", "; --- XSP state the start-up set (snapshot xsp_calls; pointers mapped)"]
    for k in sorted(r["xsp_init"]):
        L.append(_equ("XSPI_" + k, r["xsp_init"][k]))
    L += ["", "; --- I/O shadow: the game's absolute I/O operands, folded (patches.json io_fold)",
          _equ("IO_SHADOW", IO_SHADOW), _equ("IO_SHADOW_SIZE", IO_SHADOW_SIZE),
          _equ("IOSH_IMAGE", r["iosh_at"], "iosh.bin: the shadow's bytes at the resume point"),
          _equ("IOSH_IMAGE_SIZE", len(r["iosh_image"]))]
    for a in sorted(r["io_fold"]):
        L.append(_equ("IOSH_%06X" % a, r["io_fold"][a]))
    if r["sound"]:
        L += ["", "; --- sound (Plan 4): the cue table in P-ROM; by tune index, the data pointer MCDRV",
              ";     fn $01 receives in a0 (the relocated tune table's)",
              _equ("SND_CUE_TABLE", r["sound"]["SND_CUE_TABLE"],
                   "16 B per cue: +0 STAT, +2 length, +6 sample pointer, +A PR")]
        for k in sorted(n for n in r["sound"] if n.startswith("SND_TUNE_PTR_")):
            L.append(_equ(k, r["sound"][k], "tune $%02X" % r["sound_tunes"][int(k[13:])]))
    return "\n".join(L) + "\n"


def render_asm(r):
    L = ["; generated by tools/link.py - do not edit (make link)",
         "; Places the game in P-ROM. Include it after the shim's own code and labels, with",
         "; game.inc included first and -Ibuild/link (incbin paths). vasm refuses overlapping",
         "; sections: the shim must keep out of XSP_JT..$7FFF and GAME_ROM..LINKDATA_END.", "",
         "; XSP jump table: one pinned 6-byte slot per C entry, jmp (Shim_<name>).l. A missing",
         "; Shim_<name> fails the assembly unless the shim defines XSP_STUB_<name> (explicit",
         "; opt-out: the slot is then `illegal`, reported by the fault handler)."]
    for name in sorted(r["xsp_jt"], key=lambda n: r["xsp_jt"][n]):
        L += ["    org     XSPJT_%s" % name,
              "    ifd     Shim_%s" % name, "    jmp     (Shim_%s).l" % name, "    else",
              "    ifd     XSP_STUB_%s" % name,
              "    dc.w    $%04X,$%04X,$%04X     ; illegal: XSP_STUB_%s" % (
                  ILLEGAL, ILLEGAL, ILLEGAL, name),
              "    else",
              '    fail    "Shim_%s missing: define it before including game.asm, or XSP_STUB_%s"'
              % (name, name),
              "    endif", "    endif"]
    L += ["", "; game routines the shim replaces (link.py SHIM_ENTRIES): jmp (Shim_<name>).l"]
    for name in sorted(r["shim_jt"], key=lambda n: r["shim_jt"][n]):
        L += ["    org     SHIMJT_%s" % name,
              "    ifd     Shim_%s" % name, "    jmp     (Shim_%s).l" % name, "    else",
              '    fail    "Shim_%s missing: define it before including game.asm"' % name,
              "    endif"]
    L += ["", "; the title's hooks (link.py TITLE_HOOKS): jmp (<label>).l"]
    for name in sorted(r["hook_jt"], key=lambda n: r["hook_jt"][n]):
        L += ["    org     HOOKJT_%s" % name,
              "    ifd     %s" % name, "    jmp     (%s).l" % name, "    else",
              '    fail    "%s missing: define it before including game.asm"' % name,
              "    endif"]
    L += ["", "; the game's hooks' 4-byte sites (link.py GAME_HOOKS): jmp (<label>).l. The labels",
          "; lie above this file (coop.asm's COOP_CODE): no ifd, a missing one is undefined"]
    for name in sorted(r["ghook_jt"], key=lambda n: r["ghook_jt"][n]):
        L += ["    org     GHOOKJT_%s" % name, "    jmp     (%s).l" % name]
    L += ["", "; constant bytes for I/O polls that end at once (link.py IO_REDIRECT)",
          "    org     $%X" % IO_CONST_SET, "    dc.b    $FF", "    org     $%X" % IO_CONST_CLR,
          "    dc.b    $00"]
    L += ["", "    org     PCREL_STUBS"]
    if r["stubs"]:
        L.append('    incbin  "stubs.bin"')
    # game.bin, with the game hooks' 6-byte sites (jsr (<label>).l) assembled between its pieces
    L += ["", "    org     GAME_ROM"]
    pos = 0
    for addr, label in r["ghook_calls"]:
        L += ['    incbin  "game.bin",$%X,$%X' % (pos, addr - GAME_ROM - pos),
              "    jsr     (%s).l               ; GAME_HOOKS: $%X" % (label, addr - GAME_ROM)]
        pos = addr - GAME_ROM + 6
    L += ['    incbin  "game.bin",$%X' % pos if pos else '    incbin  "game.bin"', "",
          "    org     GAME_REGS              ; d0-d7/a0-a6"]
    for k in range(0, len(REGS), 4):
        L.append("    dc.l    " + ",".join("$%08X" % r["regs"][x] for x in REGS[k:k + 4]))
    L += ["", "    org     GAME_STACK_IMAGE"]
    if r["stack"]:
        L.append('    incbin  "stack.bin"')
    L += ["", "    org     RAMIMAGE_ROM", '    incbin  "ramimage.bin"', "",
          "    org     IOSH_IMAGE", '    incbin  "iosh.bin"', "",
          "    org     ROMFILES", '    incbin  "romfiles.bin"', ""]
    if r["bgtext"]:
        L += ["    org     BGTEXT", '    incbin  "bgtext.bin"', ""]
    return "\n".join(L) + "\n"


def summary(r):
    c = {}
    for p in r["patches"]:
        c[p["kind"]] = c.get(p["kind"], 0) + 1
    return {"sites": c, "words": sum(p["words"] for p in r["patches"]),
            "dead_pointers": len(r["dead"]), "superseded": r["superseded"],
            "pointer_words_not_emitted": len(r["not_emitted"]),
            "io_register_sites": len(r["io_register"]), "io_ptr_sites": len(r["io_ptr"]),
            "stubs_bytes": len(r["stubs"]), "game_bin": len(r["game"]),
            "ramimage": len(r["ramimage"]), "stack_image": len(r["stack"]),
            "linkdata_end": r["linkdata_end"]}


def write(r, out):
    os.makedirs(out, exist_ok=True)
    for name, key in (("game.bin", "game"), ("stubs.bin", "stubs"), ("ramimage.bin", "ramimage"),
                      ("stack.bin", "stack"), ("iosh.bin", "iosh_image"),
                      ("romfiles.bin", "romfiles"), ("bgtext.bin", "bgtext")):
        with open(os.path.join(out, name), "wb") as f:
            f.write(r[key])
    with open(os.path.join(out, "game.inc"), "w") as f:
        f.write(render_inc(r))
    with open(os.path.join(out, "game.asm"), "w") as f:
        f.write(render_asm(r))
    stubs = []
    for p in r["patches"]:
        if p["kind"] == "pcrel":
            stubs.append({"site": p["at"], "stub": p["new"], "does": p["meaning"]})
    doc = {
        "legend": {
            "orig": "base-0 offset of the patched word in the original's memory (negative: below "
                    "the base); at: the instruction",
            "where": "game (game.bin, at addr) | ram (RAM image) | stack (stack image)",
            "addr": "Neo Geo address of the patched word",
            "old/new": "reloc/pointer/io: the original address and the Neo Geo value written; "
                       "xsp_entry/pcrel/io_code/title_code/title_hook/game_hook/game_code: the "
                       "instruction bytes "
                       "before and after",
            "dead": "the target is a shim/drop object: SHIM_DEAD",
        },
        "summary": summary(r),
        "io_fold": [{"lo": c["lo"], "hi": c["hi"], "shadow": c["shadow"],
                     "addrs": {"$%X" % a: r["io_fold"][a] for a in c["addrs"]}}
                    for c in r["io_clusters"]],
        "xsp_jt": {n: {"entry": r["xsp_addr"][n], "slot": s} for n, s in r["xsp_jt"].items()},
        "shim_jt": {n: {"entry": r["shim_addr"][n], "slot": s} for n, s in r["shim_jt"].items()},
        "hook_jt": {n: {"sites": r["hook_addr"][n], "slot": s} for n, s in r["hook_jt"].items()},
        "ghook_jt": {n: {"sites": r["ghook_addr"][n], "slot": r["ghook_jt"].get(n)}
                     for n in r["ghook_addr"]},
        "shim_vars": r["shim_vars"],
        "io_unfolded": {
            "note": "I/O reached through a register: not folded (no operand to rewrite); the "
                    "base comes from an immediate (io_ptr). Plan 2 Task 5's decisions "
                    "(docs/notes/shim.md): the io_ptr sites in io_ptr_shadow point at the shadow "
                    "(kind io_ptr patches). Plan 3: the text routines' sites ($1618, $173C, "
                    "$1888) are no longer reached (the routines jump to the shim: shim_entry); "
                    "the game-start background builder's ($6512, $3536: the PCG, BG page and "
                    "graphic VRAM accesses, some not in sites) are replaced (io_code, kind "
                    "io_code patches); the palette pair runs only at start-up, before the "
                    "resume point. tests/neo/tripwire.lua fails on any game access to "
                    "$C00000-$CFFFFF or $E00000-$EFFFFF.",
            "io_code": {"$%X" % k: v for k, v in r["io_code"].items()},
            "title_code": {"$%X" % k: v for k, v in r["title_code"].items()},
            "io_ptr_shadow": {"$%X" % k: v for k, v in IO_PTR_SHADOW.items()},
            "io_redirect": {"$%X" % k: "$%X" % v for k, v in IO_REDIRECT.items()},
            "io_redirect_why": IO_REDIRECT_WHY,
            "sites": r["io_register"], "io_ptr": r["io_ptr"],
            "resume_regs": {k: "$%X" % v for k, v in r["io_regs"].items()},
            "resume_regs_note": "resume registers (not pointer registers) holding I/O "
                                "addresses, kept as they are"},
        "pointer_words_not_emitted": {
            "note": "pointer/reloc words inside shim or drop objects (no copy), or in the stack "
                    "below sp: base-0 offsets",
            "words": r["not_emitted"]},
        "stubs": stubs,
        "rom_files": [{"name": n, "size": len(d)} for n, d in r["rom_files"]],
        "file_reloads": r["file_reloads"],
        "xsp_init": r["xsp_init"],
        "ram_table": r["ram_table"],
        "dead": r["dead"],
        "patches": r["patches"],
    }
    with open(os.path.join(out, "patches.json"), "w") as f:
        json.dump(doc, f, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--orig", default="build/orig")
    ap.add_argument("--preinit", default="build/preinit")
    ap.add_argument("--layout", default="build/link/layout.json")
    ap.add_argument("--out", default="build/link")
    ap.add_argument("--digests", action="store_true",
                    help="print each table's SHA1 over --orig's sz2.bin (TABLE_SHA1) and stop")
    a = ap.parse_args(argv)
    if a.digests:
        with open(os.path.join(a.orig, "sz2.bin"), "rb") as f:
            img = f.read()
        for kind, d in table_digests(img, {
                "io_code": IO_CODE, "title_code": TITLE_CODE, "title_hook": TITLE_HOOKS,
                "game_hook": GAME_HOOKS, "game_code": GAME_CODE}).items():
            print('    "%s": "%s",' % (kind, d))
        return
    try:
        r = link(**load(a.orig, a.preinit, a.layout))
    except LinkError as e:
        sys.exit("link: %s" % e)
    write(r, a.out)
    s = summary(r)
    print("link: game.bin $%X-$%X, link data to $%X; RAM image %d B, stack %d B, stubs %d B" % (
        GAME_ROM, r["rom_end"], r["linkdata_end"], len(r["ramimage"]), len(r["stack"]),
        len(r["stubs"])))
    print("link: patches %s, %d words; %d dead pointers, %d superseded, %d not emitted" % (
        ", ".join("%s %d" % kv for kv in sorted(s["sites"].items())), s["words"],
        s["dead_pointers"], len(s["superseded"]), s["pointer_words_not_emitted"]))


if __name__ == "__main__":
    main()
