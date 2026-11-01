; ==============================================================================
; THE SHIM'S STATE: everything in the port reserve $10B000-$10DFFF (Plan 2 global
; constraints). IO_SHADOW ($10B800-$10C7FF, 4 KB) is link.py's (game.inc). The reserve's whole
; map, every block and every free range in address order, is at the end of this file (with the
; asserts that keep it exact); docs/notes/shim.md "The port reserve" has the same table.
; ==============================================================================

; --- fault record and counters (tests/neo/lib.lua reads these) ------------------
; SHIM_FAULT / SHIM_HEARTBEAT are in neogeo.inc ($10B000, $10B008)
SHIM_MAGIC        EQU $0010B00C  ; long "SHIM" once the shim owns the machine
SHIM_MAGIC_VALUE  EQU $5348494D
SHIM_FAULT_PC     EQU $0010B010  ; call faults: the F-line word / the trap #15 / a wait's caller
SHIM_FAULT_ARG    EQU $0010B014  ; call faults: d1 at the call, or the argument at fault
SHIM_RESTARTS     EQU $0010B018  ; word: times the game exited and was resumed again
; --- cleared at every resume from here (SHIM_STATE_LO) ---
SHIM_SUPER        EQU $0010B01A  ; word: the game's virtual supervisor flag (_B_SUPER/_SUPER)
SHIM_IOCS_COUNT   EQU $0010B01C  ; long: IOCS calls served
SHIM_DOS_COUNT    EQU $0010B020  ; long: DOS/FLOAT calls served
SHIM_VSYNC        EQU $0010B024  ; word: XSP's vsync_count (VBlanks since the last xsp_vsync)
SHIM_JOY_COUNT    EQU $0010B028  ; long: _JOYGET calls served (the game polling its controls)

; --- XSP replacement state (xsp.asm) ------------------------------------------------
SHIM_XSP_ON       EQU $0010B030  ; word: 1 after xsp_on, 0 after xsp_off
SHIM_XSP_W        EQU $0010B032  ; word: XSP's write buffer (0-2)
SHIM_XSP_D        EQU $0010B034  ; word: XSP's display buffer (0-2)
SHIM_XSP_MODE     EQU $0010B036  ; word: xsp_mode2(mode)
SHIM_XSP_VERT     EQU $0010B038  ; word: xsp_vertical(flag)
SHIM_XSP_DIVY     EQU $0010B03A  ; 3 words: xsp_divy_set2(y1, y2, y3)
SHIM_XSP_FRM      EQU $0010B040  ; long: xsp_objdat_set(frm, ...)
SHIM_XSP_REF      EQU $0010B044  ; long: xsp_objdat_set(..., ref)
SHIM_XSP_PCG      EQU $0010B048  ; long: xsp_pcgdat_set(pcg, ...)
SHIM_XSP_ALT      EQU $0010B04C  ; long: xsp_pcgdat_set(..., alt, ...)
SHIM_XSP_ALTSZ    EQU $0010B050  ; long: xsp_pcgdat_set(..., size)
SHIM_XSP_MASK     EQU $0010B054  ; long: xsp_mask_set(mask)
SHIM_XSP_CHAIN    EQU $0010B058  ; long: xsp_wtrans(chain)
SHIM_XSP_OUTS     EQU $0010B05C  ; long: xsp_out calls (frames closed)

; --- the view (Plan 3 Task 7, view.asm) ------------------------------------------------------
; The Neo Geo screen (224 lines) shows field lines view .. view + 223 of the original's 256-line
; field, at screen x = field x + 32. The view belongs to each sprite list: xsp_out's build
; computes it (view.asm View_Build: from the ship's y, PB_VIEW) and lays the list's objects, its
; guard's bands and its text reservation out for it; the VBlank that puts the list into VRAM
; takes it for the background (SHIM_BG_VIEW) and the text (SHIM_VIEW): one view per displayed
; frame for everything on the screen.
SHIM_VIEW         EQU $0010B0B0  ; word, 0..32: the view on the screen (the PB_VIEW of the list in
                                 ; VRAM: Bg_Take sets it); Text_Flush draws the text for it

; --- the sprite drawing's state (sprites.asm) --------------------------------------------
SHIM_SPR_KEY      EQU $0010B0B2  ; 12 bytes: the published list's seq.l and the image (8 bytes)
                                 ; the last upload drew (an unchanged one is not drawn again)
SHIM_SPR_LOW      EQU $0010B0BE  ; word: the lowest object sprite number shown (SPR_OBJ_END: none)
SHIM_SPR_SHOWN    EQU $0010B0C0  ; long: seq of the list the last upload drew (tests)
SHIM_SPR_HB       EQU $0010B0C4  ; long: SHIM_HEARTBEAT at that upload (its image phase: & 3)
SHIM_SPR_LINES    EQU $0010B0C8  ; word: the most raster lines one VBlank's sprite upload took
                                 ; (this and the next two: test builds only, COST_START below)
SHIM_VBL_LINES    EQU $0010B0CA  ; word: the most raster lines one whole VBlank took (to the end of
                                 ; Text_Flush)
SHIM_SPR_BLINES   EQU $0010B0CC  ; word: the most raster lines one list's build took (xsp_out, in
                                 ; the game's time)
SHIM_SPR_DROPS    EQU $0010B0CE  ; long: sprites the guard dropped, all lists since the resume
SHIM_SPR_RUN      EQU $0010B0D2  ; word: the open list's last priority run: INFO & $3F, x 4
                                 ; (-4: none yet)
SHIM_SPR_END      EQU $0010B0D4  ; (sprites.asm's build variables follow, SPR_VARS_BYTES of them;
                                 ; sprites.asm asserts its SPR_VARS_END is SHIM_SPR_AVAIL)
SPR_VARS_BYTES    EQU 34
SHIM_SPR_AVAIL    EQU SHIM_SPR_END+SPR_VARS_BYTES  ; word ($10B0F6): PB_AVAIL of the list in VRAM
                                 ; (Spr_Upload copies it when it draws a list: the text gate's)

; --- DOS file handles (dos.asm): handles 5-14, 8 bytes each ---------------------------
DOS_FIRST_FH      EQU 5
DOS_HANDLES       EQU 10
SHIM_FILES        EQU $0010B060  ; per handle: table entry.l (0 = free), position.l
SHIM_FILES_END    EQU SHIM_FILES+8*DOS_HANDLES

; --- sound command ring (MCDRV trap #4, IOCS ADPCM): sound.asm's Snd_Drain plays them ----
SND_ENTRIES       EQU 32         ; a power of two
SND_SIZE          EQU 16         ; +0 source.b (1 MCDRV, 2 IOCS), +1 fn.b, +2 pad.w,
                                 ; +4 d1.l, +8 d2.l, +12 a0.l (MCDRV) / a1.l (ADPCM)
SND_SRC_MCDRV     EQU 1
SND_SRC_IOCS      EQU 2
; SHIM_SND_HEAD and SHIM_SND_TAIL are instrumentation, written in every build and read by nothing in
; the shim (as SHIM_PROF is reserved in every build): the Lua tests' write taps see each recorded
; entry by the head's write (replay_neo.lua ls_snd, sound.lua snd_head) and each drain by the
; tail's (sound.lua snd_tail). The drain itself reads SHIM_SND_COUNT and SHIM_SND_DONE.
SHIM_SND_HEAD     EQU $0010B100  ; word: SHIM_SND_COUNT & 31 after each recorded entry (test tap)
SHIM_SND_TAIL     EQU $0010B102  ; word: SHIM_SND_DONE & 31 after each drain (test tap)
SHIM_SND_COUNT    EQU $0010B104  ; long: commands recorded (an entry is in once this counts it)
SHIM_SND          EQU $0010B110  ; SND_ENTRIES * SND_SIZE = 512 bytes
SHIM_SND_END      EQU SHIM_SND+SND_ENTRIES*SND_SIZE

; SND_PUT source, fn, addr, dN, aN: one call into the ring (source.b, fn.b, pad, d1, d2, addr) at
; entry SHIM_SND_COUNT & 31, then SHIM_SND_COUNT + 1, which puts it in for the drain in one
; instruction, then SHIM_SND_HEAD. No interrupt mask: the VBlank's drain reads only counted
; entries, and at most SND_ENTRIES - 1 of them, so never the slot being written (with 32 or more
; pending that slot is the oldest's: sound.asm counts it lost). dN and aN are used.
; The entry layout (SND_SIZE above) is written here and, hand-inlined, in iocs.asm Iocs_Snd (whose
; -11(a0) reads the fn byte back from the last field's address): change both, and
; tests/tools/test_shim_map.py TestSoundRing holds them to the same writes.
SND_PUT macro
    move.l  SHIM_SND_COUNT, \4
    andi.w  #SND_ENTRIES-1, \4
    lsl.w   #4, \4
    lea     SHIM_SND, \5
    adda.w  \4, \5
    move.b  \1, (\5)+
    move.b  \2, (\5)+
    clr.w   (\5)+
    move.l  d1, (\5)+
    move.l  d2, (\5)+
    move.l  \3, (\5)
    addq.l  #1, SHIM_SND_COUNT
    lsr.w   #4, \4
    addq.w  #1, \4
    andi.w  #SND_ENTRIES-1, \4
    move.w  \4, SHIM_SND_HEAD
    endm

; --- the sound drain (sound.asm, Plan 4 Task 5): the ring sent to the Z80 once a frame ---------
SHIM_SND_DONE     EQU $0010B32C  ; long: SHIM_SND_COUNT at the last drain (later entries are new)
SHIM_SND_ERR      EQU $0010B330  ; word: commands whose echo did not come in SND_ECHO_POLLS polls,
                                 ; and _ADPCMOUT samples that are no cue's (none is sent for them)
SHIM_SND_LOST     EQU $0010B332  ; word: entries not taken: more than 31 pending
SHIM_SND_TUNE     EQU $0010B334  ; word: the tune MCDRV fn $01 set last (its index: SND_CMD_PLAY +
                                 ; index plays it), SND_NO_TUNE before any
SHIM_SND_LAST     EQU $0010B336  ; word: the echo of the last command sent, not yet seen (the next
                                 ; drain waits for it before it sends), 0: none
SHIM_SND_MUSIC    EQU $0010B338  ; word: nonzero after an MCDRV call (Shim_MCDRV), until a drain walks
                                 ; the ring (Snd_Walk); while 0, a drain may take its newest entry alone
SHIM_SND_FXC      EQU $0010B33A  ; 2 x (sample.l, command.w): the samples mapped last, the latest
                                 ; first (a cache in front of SHIM_SND_FXPTR's search)
SHIM_SND_FXPTR    EQU $0010B346  ; SND_FX_MAX longs: effect i's sample (the cue table's +6 pointer
                                 ; of the cue SND_FX_INDEX gives i), set at every resume (Snd_Init)
SND_FX_MAX        EQU 32         ; effects the table holds (sound68k.inc SND_FX_COUNT: 25)
SHIM_SND_STATE_END EQU SHIM_SND_FXPTR+4*SND_FX_MAX                  ; $10B3C6
; --- _ADPCMSNS's busy model (Plan 4 Task 6, iocs.asm, sound.asm Snd_Tick): game steps left ------
SHIM_SE_BUSY      EQU $0010B3C6  ; word: game steps the effect channel still reads busy: _ADPCMOUT
                                 ; sets SND_FX_FRAMES[its effect], _ADPCMMOD(0) clears it, every
                                 ; game step takes 1 (Snd_Tick); _ADPCMSNS: 0 idle, 2 busy
SHIM_SE_SMP       EQU $0010B3C8  ; long: the sample of the last _ADPCMOUT (a cache: -1 none)
SHIM_SE_SMPF      EQU $0010B3CC  ; word: its SND_FX_FRAMES
SHIM_SE_END       EQU $0010B3CE

; --- the BIOS layer (Plan 5 Task 1, bios.asm): cleared at every resume, set by it -------------
SHIM_BIOS_MODE    EQU $0010B3CE  ; word: the USER request the resume serves (USER_REQ_DEMO /
                                 ; USER_REQ_TITLE); 0 from Shim_Boot until the resume sets it
SHIM_START_REQ    EQU $0010B3D0  ; word: nonzero once PLAYER_START accepted a start (the demo:
                                 ; Bios_Frame resumes the title; the title: its hook, Task 3)
SHIM_TITLE_ON     EQU $0010B3D2  ; word: nonzero while the title loop waits for a start (the
                                 ; title's hook sets it, Plan 5 Task 3): PLAYER_START accepts
SHIM_DEMO_LEFT    EQU $0010B3D4  ; word: frames the demo has left at most (BIOS_DEMO_FRAMES at its
                                 ; resume): its backstop (demo.asm; it ends with its stream first)
SHIM_BIOS_END     EQU $0010B3D6
BIOS_DEMO_FRAMES  EQU 2760       ; the demo's backstop (46.6 s): its title (DEMO_TITLE_PASSES), the
                                 ; game's start and its stream's steps take about 2,470 frames

; --- the title's hook (Plan 5 Task 3, title.asm): cleared at every resume ---------------------
SHIM_TITLE_STATE  EQU $0010B3D6  ; word: TITLE_FRESH (the title opens: from the resume or after a
                                 ; game), TITLE_LOOP (its loop runs), TITLE_MENU (CONFIG chosen:
                                 ; the loop comes back from it)
SHIM_TITLE_PASS   EQU $0010B3D8  ; word: the hook's passes (the blink's clock)
SHIM_TITLE_IDLE   EQU $0010B3DA  ; word: passes without input while no countdown runs
SHIM_TITLE_COIN   EQU $0010B3DC  ; word: the menu's rows as the hook left them: 0 the menu (START,
                                 ; CONTINUE, item 2), 1 INSERT COIN (no credit: no menu)
SHIM_TITLE_END    EQU $0010B3DE
TITLE_FRESH       EQU 0
TITLE_LOOP        EQU 1
TITLE_MENU        EQU 2
TITLE_IDLE_FRAMES EQU 1800       ; an idle title with no countdown (no credit counted, or none in)
                                 ; hands back to the BIOS (its demo) after this many passes (30.4 s)

; --- the attract demo (Plan 5 Task 4, demo.asm): cleared at every resume ----------------------
SHIM_DEMO_STATE   EQU $0010B3DE  ; word: DEMO_TITLE (the demo's title shows), DEMO_PLAY (its game
                                 ; started: the stream feeds the pad)
SHIM_DEMO_RUN     EQU $0010B3E0  ; long: the stream's run the last read found (its first: Demo_Resume)
SHIM_DEMO_FROM    EQU $0010B3E4  ; word: the step that run begins at
SHIM_DEMO_END     EQU $0010B3E6
DEMO_TITLE        EQU 0
DEMO_PLAY         EQU 1
DEMO_TITLE_PASSES EQU 600        ; the demo's title: this many passes (10.1 s), then its START
DEMO_STEPS        EQU 1776       ; the stream's steps (30.0 s at 59.19 Hz): what the recording
                                 ; build's stream lasts (demo.asm DEMO_DATA, tests/neo/demo_record.lua)

; --- the KAKUSI code's window (Plan 5 Task 5 fix round 1, title.asm): cleared at every resume --
SHIM_TITLE_KWAIT  EQU $0010B3E6  ; word: the passes the title has held its CONFIG choice back for
                                 ; the code's other trigger (0: none held back)
SHIM_KWAIT_END    EQU $0010B3E8

; --- the test builds' words (reserved in every build, read only by a test build's code; in the
; resume's clear: 0 until a test writes them after the resume). Not $10F000-$10F2FF: the BIOS's
; stack (SYSTEM_RETURN sets SP = $10F300; plan5-recon.md 2.3) -------------------------------
SHIM_TEST_UNTIL   EQU $0010B4FE  ; word (make cart SHIM_TEST_LATE=1): a VBlank waits until the
                                 ; LSPC line counter reaches it (0: none)
SHIM_TEST_RET     EQU $0010B500  ; word (make cart SHIM_TEST_RETURN=1): nonzero, the next _JOYGET
                                 ; calls Bios_Return from the game's code just before a VBlank,
                                 ; this many polls late (bios.asm Test_Return)
SHIM_TEST_CO      EQU $0010B502  ; word (make cart SHIM_TEST_COOP=1, coop.asm Coop_Test): its high
                                 ; byte nonzero, Coop_Pass acts on it at its step's start (2: P2
                                 ; joins, 1: P1 buys in, 3: P2 out), then clears it; 4: the game
                                 ; over's last look waits a VBlank first (Coop_TestLate); its low
                                 ; byte: who ran first in the last two-player step (1 P1, 2 P2)
SHIM_TEST_END     EQU $0010B504

; --- the preserved block (Plan 5 Task 2, resume.asm Keep_*): the settings that survive a return --
; Outside the resume's clears (SHIM_HIGH_HI stops below it), at the top of the reserve. The
; settings live in the game's own RAM (their homes, GV_<name>: link.py SHIM_VARS), which every
; resume reloads from the snapshot; the block keeps a copy that a title-mode resume puts back
; (Keep_Restore), never a demo's. Written at every screen change in title mode (the text clear
; the title, CONFIG, KAKUSI and the game over make: Keep_Screen) and on the game's own way back
; to the BIOS (Bios_Return), so it always holds the settings as the last menu left them. Valid
; when KEEP_MAGIC holds KEEP_MAGIC_VALUE and KEEP_SUM the sum of the words KEEP_XSP ..
; KEEP_KENTRY (Keep_Sum); else (power-on: the BIOS's RAM test) the snapshot's values apply.
SHIM_KEEP         EQU $0010DFE0
KEEP_MAGIC        EQU 0          ; long: KEEP_MAGIC_VALUE
KEEP_XSP          EQU 4          ; word: XSP MODE (GV_XSP_MODE, $221F4; 2 always since CONFIG
                                 ; lost its XSP MODE item, 2026-10-28: kept, harmless)
KEEP_SWAP         EQU 6          ; word: the SHOT/BOMB swap (GV_SWAP, $221F2)
KEEP_PCM          EQU 8          ; word: PCM PLAY (GV_PCM_PLAY, $17512)
KEEP_BGM          EQU 10         ; word: BGM PLAY (GV_BGM_PLAY, $17514)
KEEP_MUTEKI       EQU 12         ; word: KAKUSI's muteki (GV_MUTEKI, $221F8)
KEEP_ACCHOH       EQU 14         ; word: KAKUSI's acchoh (GV_ACCHOH, $221F6)
KEEP_STAGE        EQU 16         ; word: the stage (GV_STAGE, $221FA: KAKUSI's and CONTINUE's)
KEEP_KSTAGE       EQU 18         ; byte: nonzero while KAKUSI set the stage last (the stage is put
                                 ; back only then: the controller's ruling, plan5-recon.md 2.2)
KEEP_AUTOFIRE     EQU 19         ; byte: AUTO FIRE, 0 OFF / 1 ON (Task 5: the block is its only
                                 ; home: config.asm toggles it and seals the block again, Keep_Seal;
                                 ; iocs.asm reads it; power-on: the soft DIP's default)
KEEP_KENTRY       EQU 20         ; word: the stage when KAKUSI last opened
KEEP_SUM          EQU 22         ; word: the sum of the words KEEP_XSP .. KEEP_KENTRY
KEEP_WAVES_BEST   EQU 24         ; long: the best WAVES score since power-on (the WAVES plan Task 5:
                                 ; waves.asm Waves_End; not in the sum: an invalid block clears it)
KEEP_SIZE         EQU 32         ; (28-31 spare)
SHIM_KEEP_END     EQU SHIM_KEEP+KEEP_SIZE
KEEP_MAGIC_VALUE  EQU $4B454550  ; "KEEP"

; SE_TICK: a game step has passed (the game's frame waits: xsp_vsync's return, the start of $1F92;
; one per step of play and one per pass of the title's loops): SHIM_SE_BUSY - 1, down to 0
SE_TICK macro
    tst.w   SHIM_SE_BUSY
    beq.s   .tick\@
    subq.w  #1, SHIM_SE_BUSY
.tick\@:
    endm
SND_NO_TUNE       EQU $FF
SND_ECHO_POLLS    EQU 1000       ; latch reads a command's echo is waited for (about 1.5 ms)
SND_STALE_POLLS   EQU 60         ; latch reads waited instead when the latch already holds the
                                 ; command's echo and another command follows (about 90 us: the
                                 ; Z80's NMI takes about 30)

; --- the background (sprites.asm, Plan 3 Task 5): the two graphic pages as sprite chains -------
; The X68000's registers the chains are drawn from, as the original's hardware holds them: the
; graphic scroll (CRTC R13 page 0, R17 page 1: the xsp_wpoke words of the list in VRAM, kept
; until a list sets them again; Spr_Upload takes them with the list) and the pages shown
; (_VPAGE: bit 0 page 0, bit 1 page 1; 0 at the title and while the game-start builder runs).
SHIM_BG_SCROLL0   EQU $0010B310  ; word: CRTC R13 (page 0's Y scroll)
SHIM_BG_SCROLL1   EQU $0010B312  ; word: CRTC R17 (page 1's Y scroll)
SHIM_BG_VIEW      EQU $0010B314  ; word: the view of the list in VRAM (its PB_VIEW)
SHIM_VPAGE        EQU $0010B316  ; word: _VPAGE(pages): the graphic pages shown
; the view's state (view.asm, Plan 3 Task 7)
SHIM_VIEW_LAST    EQU $0010B318  ; word: the view of the list being built (View_Build sets it at the
                                 ; build's start; the next list's view moves on from it)
SHIM_VIEW_FORCE   EQU $0010B31A  ; word (make cart SHIM_TEST_VIEW=1 only): the tests' override:
                                 ; $8000 | v sets every list's view to v (0: the view follows the ship)
SHIM_VIEW_PLAY    EQU $0010B31C  ; word: nonzero when the last list built (not forced) was a play
                                 ; list (0: the next play list starts at its target)
SHIM_BG_END       EQU SHIM_VIEW_PLAY+2  ; $10B31E (the reserve's map, below: what follows)

; --- the time profile (make cart SHIM_TEST_PROFILE=1 only; tests/lockstep/replay_neo.lua
; LS_PROFILE=1, docs/notes/graphics.md "Timing") -------------------------------------------
; One byte per kind of shim code, $FF while it runs (st) and 0 when it returns (sf: neither
; changes the condition codes, so a marker sits anywhere, the exits included). The script times
; the writes (MAME's clock is the CPU's own inside a tap): while VBL or L2 is set the time is the
; interrupts', else while WAIT is set idle (a shim wait for the VBlank), else while CALL or TRAP is
; set the shim's (an XSP or text entry; a DOS, IOCS or MCDRV trap: a trap made inside a call sets
; TRAP, so the call stays set), else the game's own.
SHIM_PROF         EQU $0010B320  ; 6 bytes, reserved in every build (written by the profile's only)
PROF_CALL         EQU 0          ; the XSP and text entries (link.py's jump table)
PROF_TRAP         EQU 1          ; F-line (DOS, FLOAT), trap #15 (IOCS), trap #4 (MCDRV)
PROF_VBL          EQU 2          ; the VBlank interrupt
PROF_L2           EQU 3          ; the LSPC timer interrupt
PROF_WAIT         EQU 4          ; Shim_WaitVBlank (xsp_out's and xsp_vsync's waits)
PROF_PHASE        EQU 5          ; xsp_out's part running (PROF_MARK; 0 outside xsp_out)
SHIM_PROF_END     EQU SHIM_PROF+6
SHIM_SPR_PTR      EQU $0010B328  ; long (every build: live): where xsp_set / xobj_set put the open
                                 ; list's next entry (xsp.asm PUT)

PROF_ON macro
    ifd     SHIM_TEST_PROFILE
    st      SHIM_PROF+\1
    endif
    endm

PROF_OFF macro
    ifd     SHIM_TEST_PROFILE
    sf      SHIM_PROF+\1
    endif
    endm

; PROF_MARK n: xsp_out's part n from here (a move: only where the condition codes are not live)
PROF_MARK macro
    ifd     SHIM_TEST_PROFILE
    move.b  #\1, SHIM_PROF+PROF_PHASE
    endif
    endm

; --- xsp_wpoke buffer: count.w then 42 x (dest.l, data.w); the open frame's ---------------
; (xsp_out copies it into the published list, PB_WPK: Plan 3 applies it with that list)
WPK_MAX           EQU 42
WPK_SIZE          EQU 6
WPK_BYTES         EQU 2+WPK_MAX*WPK_SIZE
SHIM_WPK_WORK     EQU $0010B400
SHIM_WPK_END      EQU SHIM_WPK_WORK+WPK_BYTES

; ==============================================================================
; THE SHIM EXTENSION $107000-$10AFFF (16 KB, Plan 3 RAM map: the game's objects end below
; $107000, which link/layout assert): the sprite lists.
; ==============================================================================
SHIM_EXT_LO       EQU $00107000
SHIM_EXT_HI       EQU $0010B000

; --- the open sprite list: count.w, lost.w, then SPR_MAX x SPR_SIZE bytes ------------------
; entry: x.w, y.w (in pixels: what the game passed >> 6, as XSP stores them), pt.w, info.w,
; next.w; pt bit 15 set = xobj (a composite sprite: pt is the object number, sprites.asm expands
; it through frm/ref). The entries are chained by priority (INFO & $3F) as they are set, in
; runs: next = 0: the entry after it (same priority); -1: the last of its priority; else the
; byte offset (from the first entry) of the next run of its priority. SHIM_SPR_HEADS holds each
; priority's first entry. Priorities below $10 (not shown) are not chained.
SPR_MAX           EQU 512
SPR_SIZE          EQU 10
SPR_NEXT          EQU 8
SPR_XOBJ          EQU $8000
SPR_LIST_BYTES    EQU 4+SPR_MAX*SPR_SIZE

; --- the published lists (XSP's three buffers; xsp_out builds one, the VBlank draws one) -----
; Each is ready for the VBlank (sprites.asm): the shown sprites' SCB words in four arrays of
; SPR_CAP words (tile, attribute, SCB3, SCB4), filled from the top down in drawing order: the
; front-most sprite (highest XSP priority, earliest set) at index SPR_CAP - 1, which the upload
; puts on the highest object sprite number. PB_IMG gives, per VBlank phase (the VBlank count
; & 3), the one or two runs of the arrays the upload draws, the first on the lower numbers:
; XSP MODE 1 shows 128 at a time and alternates (XSP's SP_TRANS); modes 2 and 3 one run always.
SPR_CAP           EQU 384            ; sprites one list holds (MODE 1 shows up to 384 in turns)
PB_SEQ            EQU 0              ; long: SHIM_XSP_OUTS of the xsp_out that built it
PB_VIEW           EQU 4              ; word: the view its Y were computed for
PB_N              EQU 6              ; word: sprites in the arrays
PB_REQ            EQU 8              ; word: sprites XSP's caps let through (shown on the X68000
                                     ; by priority, before the Neo Geo guard; off-screen ones too)
PB_DROP           EQU 10             ; word: of those, on the Neo Geo's lines and dropped by the
                                     ; guard (one band full, or the total)
PB_MODE           EQU 12             ; word: the XSP MODE it was built in (1, 2, 3)
PB_TEXT           EQU 14             ; word: text sprites reserved: row 14's << 8 | row 16's
PB_IMG            EQU 16             ; 4 phases x (start.w, count.w, start2.w, count2.w)
PB_WPK            EQU 48             ; the list's xsp_wpoke words (WPK_BYTES)
PB_LINES          EQU 302            ; word: raster lines its build took (xsp_out; test and
                                     ; profile builds only: COST_START)
PB_AVAIL          EQU 304            ; 2 bytes: places left for text sprites on text row 14's
                                     ; bands, row 16's (64 less the most objects on one of them):
                                     ; Text_Flush shows no more text sprites on a row than this
PB_BG             EQU 306            ; word: the graphic scroll words the list's xsp_wpoke set
                                     ; (bit 0: R13, bit 1: R17; Spr_Build), then R13.w, R17.w:
PB_BG_R13         EQU 308            ; the background's registers once the list is in VRAM
PB_BG_R17         EQU 310
PB_PAL            EQU 312            ; the colours its xsp_wpoke palette words set (palette.asm
                                     ; Pal_Build): count.w, then PAL_MAX x (palette RAM offset.w,
                                     ; Neo Geo colour.w); Pal_Take writes them with the list
PAL_MAX           EQU 32             ; Neo entries one list sets at most (the game's 13 ramp
                                     ; words feed 14; the rest of a longer list is not applied)
PB_TILE           EQU PB_PAL+2+4*PAL_MAX  ; SPR_CAP words each: SCB1 tile, SCB1 attribute, SCB3, SCB4
PB_ATTR           EQU PB_TILE+2*SPR_CAP
PB_SCB3           EQU PB_TILE+4*SPR_CAP
PB_SCB4           EQU PB_TILE+6*SPR_CAP
PB_SIZE           EQU PB_TILE+8*SPR_CAP
SHIM_PUB          EQU SHIM_EXT_LO    ; 3 x PB_SIZE: buffer n at SHIM_PUB + n * PB_SIZE
SHIM_SPR_WORK     EQU SHIM_PUB+3*PB_SIZE              ; the open list (SPR_LIST_BYTES)
SHIM_SPR_EXT_END  EQU SHIM_SPR_WORK+SPR_LIST_BYTES
    if SHIM_SPR_EXT_END>SHIM_EXT_HI
    fail "the sprite lists overrun the shim extension"
    endif

; --- the build's work areas, in the port reserve ($10C800 on: free since Task 4) ----------
SHIM_SPR_HEADS    EQU $0010C800      ; 64 x (first.w (-1: none), pad.w): per priority (INFO & $3F)
                                     ; its first entry's byte offset
SHIM_SPR_TAILS    EQU SHIM_SPR_HEADS+4*64             ; 64 longs: per priority the address of
                                     ; its last closed run's end (that entry's next word), 0: none
SPR_BANDS         EQU 34             ; 2 above the screen, 28 on it (224 lines), 4 below
SHIM_SPR_ROOM     EQU SHIM_SPR_TAILS+4*64             ; per 8-line band: places left (words)
SHIM_SPR_ROOM0    EQU SHIM_SPR_ROOM+2*SPR_BANDS       ; ... before the list's first sprite
; A priority the guard cuts is walked again (sprites.asm Spr_Cut): its candidates (on the
; screen's lines, within XSP's cap) by number c in set order; those it dropped in the list
; before go first. SPR_PREV keeps, per priority $30-$3F (the game's: graphics-recon 1.1), the
; bitmap of the candidates dropped last time (bit c; c < SPR_CAND_MAX).
SPR_CAND_MAX      EQU 1024
SHIM_SPR_GWORK    EQU SHIM_SPR_ROOM0+2*SPR_BANDS      ; 256 bytes: kept (bit c) | 128: dropped
                                     ; before (bit c), the priority being cut
SHIM_SPR_PREV     EQU SHIM_SPR_GWORK+256              ; 16 x 128 bytes, priority $30 + n
SHIM_SPR_PREVSEQ  EQU SHIM_SPR_PREV+16*128            ; 16 longs: the list (PB_SEQ) whose drops
                                     ; the bitmap holds (used only by the list after it)
SHIM_SPR_CIDX     EQU SHIM_SPR_PREVSEQ+4*16           ; SPR_CAND_MAX bytes: per candidate
                                     ; its SPR_YTAB index / 4 (Spr_Cut's walk 1)
SHIM_SPR_WAREA_END EQU SHIM_SPR_CIDX+SPR_CAND_MAX    ; $10D7C8

; --- sprite numbers ---------------------------------------------------------------------
; 1-32 the background chains (Task 5), SPR_OBJ_FIRST .. SPR_OBJ_END - 1 the objects,
; TEXT_SPR_FIRST .. 380 the text (text.asm). The hardware draws at most 96 on a line, the
; higher numbers in front.
SPR_BG_FIRST      EQU 1
SPR_BG_COUNT      EQU 32
SPR_OBJ_FIRST     EQU 33
SPR_OBJ_END       EQU 354            ; = TEXT_SPR_FIRST
SPR_OBJ_MAX       EQU SPR_OBJ_END-SPR_OBJ_FIRST       ; 321
SPR_LINE_MAX      EQU 96             ; the hardware's sprites per line
SPR_LINE_OBJ      EQU SPR_LINE_MAX-SPR_BG_COUNT       ; 64 for objects and text on a line

; --- text (text.asm): the original's text plane as a cell model --------------------------
; The X68000 text plane shows 32 x 32 cells of 8x8 over the 256 x 256 field. The game draws on
; it only through $1618 (8x8 character), $173C (16x16 glyph: 4 cells) and $1888 (clear); link.py
; sends those to Shim_Text8 / Shim_Text16 / Shim_TextClear, which write this model. The VBlank
; (Text_Flush) draws each changed cell where TEXT_PLACE (text.asm) puts it:
;   HUD cells          -> fixed places on the fix layer over the field, whatever the view
;                         (Presentation Task 2): score and lives (field rows 1-2) at (col + 4,
;                         row + 2), the original's own place; the bombs' 16x16 row (field rows
;                         30-31, cols 0-15) at (col + 4, row - 3), the screen's lines 200-215.
;                         The text font (palette PAL_TEXT, colour 0 transparent). A bomb place
;                         that field text shares: SHIM_BOMB_BITS. The side strips' columns 0-3
;                         and 36-39 hold only the strips (Presentation Task 5: gfx.inc STRIP_MAP,
;                         palettes 10/11 entries 2-15, opaque), drawn once by Text_Init
;   field cells        -> the fix layer at (col + 4, row + 2 - view/8) (fixed-view screens; the
;                         title lift: while row TEXT_LIFT_ROW holds text, rows TEXT_LIFT_FROM
;                         and down draw TEXT_LIFT_ROWS higher)
;   stage card / GAME OVER cells (field row 14 cols 8-24, row 16 cols 11-20) -> text sprites
;                         at (32 + 8 col, 8 row - view): they follow the view without drift
TEXT_COLS         EQU 32
TEXT_ROWS         EQU 32
SHIM_TEXT         EQU $0010D820  ; 1024 bytes: cell (x, y) at x * 32 + y = its character (0 blank)
SHIM_TEXT_DIRTY   EQU $0010DC20  ; 32 longs: column x's long, bit y = the cell changed and is not
                                 ; drawn yet (set by the game's calls, cleared by the VBlank)
SHIM_TEXT_USED    EQU $0010DCA0  ; 32 longs: bit y = the cell holds a nonzero character
SHIM_TEXT_ON      EQU $0010DD20  ; long: TEXT_ON_MAGIC once Text_Init has run (the VBlank draws)
SHIM_TEXT_VROW    EQU $0010DD24  ; word: the view / 8 the fix layer's field cells are drawn for,
                                 ; + TEXT_LIFT_KEY while the title lift is on
SHIM_TEXT_SVIEW   EQU $0010DD26  ; word: the view the text sprites' Y was last set for
SHIM_TEXT_SPRDIRTY EQU $0010DD28 ; word: nonzero when a text sprite's cell changed
SHIM_TEXT_SPR_N   EQU $0010DD2A  ; word: text sprites shown now (see the contract below)
SHIM_TEXT_LINES   EQU $0010DD2C  ; word: the most raster lines one Text_Flush has taken (test
                                 ; builds only: COST_START)
SHIM_TEXT_SPR_MASK EQU $0010DD30 ; long: bit k = text sprite k shown
SHIM_TEXT_SPRSEQ  EQU $0010DD34 ; long: SHIM_SPR_SHOWN when the text sprites were last placed
                                 ; (a new list on display: placed again against its PB_AVAIL)
SHIM_TEXT_LIFT    EQU $0010DD38  ; word: cells of field row TEXT_LIFT_ROW holding a character (the
                                 ; title's version row): while nonzero, the title lift (text.asm)
SHIM_TEXT_FIXON   EQU $0010DD3A  ; word: nonzero once a field cell with a character is drawn on the
                                 ; fix map (cleared by Text_NewRow's blank): a view row change
                                 ; then blanks the field's fix map
SHIM_BOMB_BITS    EQU $0010DD3C  ; long: bit 2 x + r - 27 = bomb place (fix column 4 + x, row r:
                                 ; 27-28; x 0-15, player 1's bombs) holds its bomb's glyph (the last
                                 ; cell drawn there was a bomb cell with a character >=
                                 ; TEXT_BOMB_BLANK); a blank bomb is drawn only over that, so field
                                 ; text sharing the place stays. Bits 32-63 (x 16-31, player 2's:
                                 ; two-player plan Task 7) are SHIM_BOMB_BITS2's 0-31
SHIM_TEXT_END     EQU $0010DD40
SHIM_TEXT_BLANK   EQU $0010DD40  ; word: nonzero after a text clear found a glyph on the field's fix
                                 ; map: the next VBlank with the lines blanks it whole (Text_Flush;
                                 ; Plan 5 Task 3)
SHIM_TEXT_BLANK_END EQU $0010DD42
TEXT_ON_MAGIC     EQU $54455854  ; "TEXT"
TEXT_BUDGET       EQU 48         ; cells one VBlank draws at most (the rest stay dirty)
TEXT_BLANK_COST   EQU 48         ; ... less this many when it blanks the field's fix map
TEXT_BOMB_CAP     EQU 28         ; ... of them bomb cells at most (the dearest cells, about 455
                                 ; cycles: 28 of them and 20 others keep a flush within the 24
                                 ; lines its budget allows; the rest wait for the next VBlank)
; TEXT_PLACE words: TP_FIELD, TP_SPRITE + k, or the fix map address of the cell's fixed place
; (the HUD)
TP_FIELD          EQU $0000
TP_SPRITE         EQU $8000

; Text sprites -- the contract with the sprite drawing (Task 4):
; * sprites TEXT_SPR_FIRST .. TEXT_SPR_FIRST + TEXT_SPR_COUNT - 1 belong to the text: the highest
;   numbers, so they are in front of every object sprite (text in front of sprites, VC R1).
;   Object and background sprites use numbers below TEXT_SPR_FIRST and never touch these.
; * each covers 16 lines from its row's top: all of them lie on field lines TEXT_SPR_LINE_TOP ..
;   TEXT_SPR_LINE_END - 1 (screen lines minus SHIM_VIEW). SHIM_TEXT_SPR_N of them are shown now
;   (height 1; the others height 0); at most TEXT_SPR_ROW_MAX on one line. The per-line guard
;   must count SHIM_TEXT_SPR_N on every line of that span, so the hardware's 96-per-line limit
;   (which drops the highest numbers first) never reaches a text sprite.
TEXT_SPR_COUNT    EQU 27         ; row 14 cols 8-24 (k 0-16), row 16 cols 11-20 (k 17-26)
TEXT_SPR_FIRST    EQU 354        ; 354..380 (text.asm checks: the last one is sprite 380)
TEXT_SPR_LINE_TOP EQU 112        ; field row 14's top line
TEXT_SPR_LINE_END EQU 144        ; field row 16's sprites end 16 lines below line 128
TEXT_SPR_ROW_MAX  EQU 17

; --- the two-player co-op (two-player plan, coop.asm): cleared at every resume (in SHIM_HIGH_LO ..
; SHIM_HIGH_HI) and, SHIM_COOP_PAD and SHIM_COOP_START2 aside, at every game's setup (Coop_Setup:
; the first step after a title pass, Coop_Pass) --------------------------------------------------
SHIM_COOP         EQU $0010DD42
SHIM_COOP_2P      EQU SHIM_COOP+0    ; byte: 0 until P2 first joins a game (every game's setup clears
                                     ; it: ruling R1); every hook tests it first (0: the replaced
                                     ; instruction alone, no game RAM written)
SHIM_COOP_NEW     EQU SHIM_COOP+1    ; byte: COOP_NEW_SETUP from a title pass (Title_Hook) to the next
                                     ; game's first step, whose Coop_Pass sets the block up;
                                     ; COOP_NEW_REQ while a request waits (Coop_Start, Task 6): Coop_Pass
                                     ; tests this byte and SHIM_COOP_2P as one word (one test a step)
SHIM_COOP_PAD     EQU SHIM_COOP+2    ; byte: where _JOYGET's port 0 reads (iocs.asm): 0 REG_P1CNT,
                                     ; else COOP_PAD_DEMO (the demo's stream: Bios_Resume) or
                                     ; COOP_PAD_P2 (P2's context in: REG_P2CNT; Coop_Exchange)
SHIM_COOP_START2  EQU SHIM_COOP+3    ; byte: the title chose a two-player start (P2's START, Title_Hook;
                                     ; the game's first step joins P2: Coop_Starts, Task 6)
SHIM_COOP_LIVE    EQU SHIM_COOP+4    ; byte: bit 0 the block is set up for this game (Title_Hook clears
                                     ; it every pass), bit 1 joins closed (the game over's last
                                     ; look, Coop_End, one player Coop_Over: no request after it)
SHIM_COOP_IN      EQU SHIM_COOP+5    ; byte: bit 0 P1, bit 1 P2 in play (alive or dying, not out)
SHIM_COOP_CTX     EQU SHIM_COOP+6    ; byte: 1 while P2's context is in the game's globals
SHIM_COOP_REQ     EQU SHIM_COOP+7    ; byte: join requests, bit 0 P1, bit 1 P2 (PLAYER_START accepted
                                     ; them, their credits taken: Coop_Start; the next Coop_Pass, or
                                     ; the game over's last look, joins them)
SHIM_COOP_BOMB    EQU SHIM_COOP+8    ; byte: the bomb's owner, 1 P1, 2 P2 (Coop_PassOne)
SHIM_COOP_TAIL    EQU SHIM_COOP+9    ; byte: nonzero while the step's last pass runs ($70A0's tail
                                     ; runs in it alone: Coop_Tail)
SHIM_COOP_NFREE   EQU SHIM_COOP+10   ; word: the free-shot stack's count as each pass's $70A0 began
SHIM_COOP_SCORE2  EQU SHIM_COOP+12   ; long: P2's score (Coop_Pass adds P2's score_add)
SHIM_COOP_OWN     EQU SHIM_COOP+16   ; long: bit n, shot n is P2's (Coop_Tail: Coop_Own)
SHIM_COOP_P2      EQU SHIM_COOP+20   ; COOP_P2_SIZE bytes: P2's context while P1's is in the globals
                                     ; (Coop_Exchange swaps them), the runs in this order:
COOP_P2_BLK       EQU 0              ;   the player block (GV_PLAYER_BLK, 28 bytes)
COOP_P2_Y         EQU 28             ;   the ship's y, then x (GV_PLAYER_Y)
COOP_P2_X         EQU 30
COOP_P2_PAD       EQU 32             ;   the stored pad bytes (GV_PAD)
COOP_P2_SCORE_ADD EQU 36             ;   score_add (GV_SCORE_ADD)
COOP_P2_SIZE      EQU 40
SHIM_COOP_TGT     EQU SHIM_COOP_P2+COOP_P2_SIZE   ; 128 words, one per object (Coop_Objects): the
                                     ; handler's low word when its target was chosen, bit 15 set
                                     ; when it is P2 (0: none chosen, or a bullet's, an item's)
SHIM_COOP_SWAP    EQU SHIM_COOP_TGT+2*128   ; byte: the object loop's swap in the globals around
                                     ; the handler it runs (0 none: P1 the target; COOP_SWAP_PART
                                     ; the ships' y/x and death/invulnerability longs; COOP_SWAP_ALL
                                     ; Coop_Exchange); bit 7 while a hit (Coop_Hit) has it undone
SHIM_COOP_PROMPT  EQU SHIM_COOP_SWAP+1   ; byte: what the join prompt's cells hold (Task 7,
                                     ; Coop_Prompt): bit COOP_PR_P1 / COOP_PR_P2 that player's
                                     ; corner is the prompt's (its HUD cells blank, PRESS START or
                                     ; INSERT COIN on row 1), COOP_PR_OFF the blink's off half (no
                                     ; text), COOP_PR_COIN INSERT COIN's text; 0: no prompt cell
SHIM_COOP_END     EQU SHIM_COOP_PROMPT+1
SHIM_BOMB_BITS2   EQU SHIM_COOP_END  ; long: SHIM_BOMB_BITS's bits 32-63 (player 2's bomb places,
                                     ; field columns 16-31: Task 7, text.asm); not the co-op's block
                                     ; (the fix map's, as SHIM_BOMB_BITS: cleared by the resume,
                                     ; Text_Init and Text_NewRow alone)
SHIM_COOP_CREDITS EQU SHIM_BOMB_BITS2+4  ; byte: BIOS_CREDITS as Coop_Prompt last read it (Task 7:
                                     ; Coop_Blink asks again when it changes)
SHIM_COOP_P2KEY   EQU SHIM_COOP_CREDITS+1  ; byte: P2's START as the VBlank reads it (Coop_Blink):
                                     ; COOP_KEY_UP up last frame (0 after a resume), COOP_KEY_SEEN
                                     ; a press the BIOS dropped, the US BIOS fallback's (Coop_P2Key;
                                     ; Title_Hook and Coop_Take take it, masked)
; --- WAVES, the endless wave mode (the WAVES plan; title.asm, waves.asm): RES_FREE8's start, WAVES_SIZE
; bytes; cleared at every resume (in SHIM_HIGH_LO .. SHIM_HIGH_HI: a resume is never inside a run)
SHIM_WAVES        EQU SHIM_COOP_P2KEY+1
SHIM_WAVES_ON     EQU SHIM_WAVES     ; byte: a WAVES run is on: set by the title's WAVES choice
                                     ; (Title_Hook), cleared by any other choice and as the title
                                     ; opens
WV_STARTED        EQU SHIM_WAVES+1   ; byte: the run's first step done (Waves_Start)
WV_SECTIONS       EQU SHIM_WAVES+2   ; word: sections started in the run (tests)
WV_MUTEKI         EQU SHIM_WAVES+4   ; byte: KAKUSI's muteki was on in the run (no best score)
WV_FORCED         EQU SHIM_WAVES+5   ; byte: PLAYER_START at the title was the BIOS's forced start
                                     ; (the countdown's: P1's START up, bios.asm; Title_Hook reads it)
WV_LANES          EQU SHIM_WAVES+8   ; WAVES_LANES lanes of WVL_SIZE bytes: the original's stage
WAVES_LANES       EQU 3              ; sections run side by side, each with its own phase and timer
WVL_SCRIPT        EQU 0              ; word: 0 idle, 1-3 the stage script (stage 1, 2, the bonus)
WVL_PHASE         EQU 2              ; word: its phase ($2B8A6) ...
WVL_TIMER         EQU 4              ; word: ... and phase timer ($2B8A8), exchanged with the game's
WVL_START         EQU 6              ; word: the section's phase (a change: the section ended)
WVL_GAP           EQU 8              ; word: steps idle since its last section (Waves_Fill)
WVL_WEIGHT        EQU 10             ; word: its section's weight (measured p99 sprites: Waves_Pick)
WVL_SIZE          EQU 12
WV_LANES_END      EQU WV_LANES+WAVES_LANES*WVL_SIZE
WV_STATE          EQU WV_LANES_END   ; word: the cycle's part: WV_ST_CARD, WV_ST_WAVES, WV_ST_BOSS
WV_ST_CARD        EQU 0              ; "WAVE n" (the stage card's timings), the waves tune
WV_ST_WAVES       EQU 1              ; the waves, WAVES_CYCLE_STEPS of them
WV_ST_BOSS        EQU 2              ; the boss: lane 0 runs a boss section to its end (in turn
                                     ; stage 1's, stage 2's, the bonus stage's finale: WAVES_BOSSES)
WV_ST_CLEAR       EQU 3              ; between the waves and the boss: no section, until the last
                                     ; waves' enemies are destroyed or gone (the user, 2026-11-01)
WV_CYCLE          EQU WV_LANES_END+2 ; word: the cycle, 1 at the run's start
WV_CLOCK          EQU WV_LANES_END+4 ; word: steps into the card or the waves
WV_BOSSES         EQU WV_LANES_END+6 ; word: bosses launched in the run
WV_CARD           EQU WV_LANES_END+8 ; 10 bytes: the card's text ("WAVE n", 0)
WV_CARD_END       EQU WV_CARD+10
WV_BPREV          EQU WV_CARD_END    ; WV_BPREV_N x (object address.l, flag.w): each boss object
WV_BPREV_N        EQU 4              ; seen above its base since last below it (Waves_BossHP; the
                                     ; bonus stage's finale: $FF42's one and $F7C0's two, one spare)
WV_BPREV_END      EQU WV_BPREV+6*WV_BPREV_N  ; (cleared as a boss section starts)
WAVES_CYCLE_STEPS EQU 3552           ; a cycle's waves: about a minute (60 x 59.19 steps)
WAVES_SIZE        EQU $60            ; (the run's state: the WAVES plan's Tasks 2-5)
    if WV_BPREV_END>SHIM_WAVES+WAVES_SIZE
    fail "shim.inc: WAVES' state past WAVES_SIZE"
    endif
SHIM_WAVES_END    EQU SHIM_WAVES+WAVES_SIZE
SHIM_COOP_CLR     EQU SHIM_COOP_LIVE ; the setup clears SHIM_COOP_2P, SHIM_COOP_NEW and from here on
COOP_SWAP_PART    EQU 1              ; SHIM_COOP_SWAP's kinds
COOP_SWAP_ALL_BIT EQU 1
COOP_SWAP_ALL     EQU 1<<COOP_SWAP_ALL_BIT
COOP_SWAP_UNDONE  EQU 7              ; (its bit: a hit has the swap undone)
COOP_NEW_SETUP    EQU 0              ; SHIM_COOP_NEW's bits (Title_Hook's st sets them all)
COOP_NEW_REQ      EQU 7
COOP_NEW_PROMPT   EQU 6              ; (the VBlank, Coop_Blink: the join prompt's cells are due)
COOP_PR_P1        EQU 0              ; SHIM_COOP_PROMPT's bits (the corners: SHIM_COOP_IN's bits)
COOP_PR_P2        EQU 1
COOP_PR_OFF       EQU 5              ; (= GV_FRAME's blink bit, TITLE_BLINK)
COOP_PR_COIN      EQU 6
COOP_KEY_UP       EQU 2              ; SHIM_COOP_P2KEY's bits (REG_STATUS_B's P2 START bit)
COOP_KEY_SEEN     EQU 7
COOP_PAD_DEMO     EQU 1              ; SHIM_COOP_PAD's bits
COOP_PAD_P2_BIT   EQU 1
COOP_PAD_P2       EQU 1<<COOP_PAD_P2_BIT

; --- areas the boot clears -------------------------------------------------------------
SHIM_STATE_LO     EQU $0010B01A  ; after the fault record, heartbeat, magic and restarts
SHIM_STATE_HI     EQU $0010B600  ; up to the boot stack
SHIM_BOOT_SP      EQU $0010B800  ; the shim's own stack while it sets up ($10B600-$10B7FF): the
                                 ; game's stack area is rewritten then
SHIM_HIGH_LO      EQU $0010C800  ; after IO_SHADOW (the sprite build's work areas, the text model)
SHIM_HIGH_HI      EQU $0010DFE0  ; the preserved block (SHIM_KEEP) follows, then the stack
STACK_FILL        EQU $A5C3      ; the stack below main's live frames at every resume: the
                                 ; deepest word that no longer holds it is the high-water mark
GAME_RAM_LO       EQU $00100000
GAME_RAM_HI       EQU $0010B000  ; (the resume clears this far: the game's objects to $106FFF
                                 ; and the shim extension SHIM_EXT_LO .. SHIM_EXT_HI)

; --- timing --------------------------------------------------------------------------
; The original polls MFP GPIP bit 4 (V-DISP: 0 in vertical blank) at $1F92. The shadow
; byte IOSH_E88001 follows the Neo Geo: the VBlank IRQ clears bit 4, the LSPC timer
; (IRQ2, reloaded at every VBlank) sets it again GPIP_BLANK_LINES lines later.
GPIP_BLANK_LINES  EQU 24
GPIP_VDISP        EQU 4          ; bit
GPIP_IDLE         EQU $90        ; bits 7 (H-sync) and 4 (display) set
LSPC_TIMER_ON     EQU $0050      ; REG_LSPCMODE: timer IRQ enabled, reloaded at VBlank

; --- cost instrumentation (Plan 3 final fix wave, review M6) ----------------------------
; The most raster lines the VBlank, the sprite upload, Text_Flush and xsp_out's build took
; (SHIM_VBL_LINES, SHIM_SPR_LINES, SHIM_TEXT_LINES, SHIM_SPR_BLINES, each list's PB_LINES) are
; measured only in the test and profile builds (SHIM_TEST_VIEW, SHIM_TEST_LATE: tests/neo/
; sprites.lua and text.lua print them; SHIM_TEST_PROFILE: make timing). The cart as it ships
; leaves them 0 (tests/neo/view.lua checks it). COST_START pushes the line counter (d0 the
; line), COST_END \1 pops it and keeps the lines since in the word \1 if more (d0 the lines).
    ifd     SHIM_TEST_VIEW
SHIM_COST set 1
    endif
    ifd     SHIM_TEST_LATE
SHIM_COST set 1
    endif
    ifd     SHIM_TEST_PROFILE
SHIM_COST set 1
    endif

COST_START macro
    ifd     SHIM_COST
    bsr     Spr_Line
    move.w  d0, -(sp)
    endif
    endm

COST_END macro
    ifd     SHIM_COST
    move.w  (sp)+, d0
    bsr     Spr_Lines
    cmp.w   \1, d0
    bls.s   .\@
    move.w  d0, \1
.\@:
    endif
    endm

; --- the original's environment ----------------------------------------------------------
SSP_VALUE         EQU $00008364  ; Human68k's SSP: what _B_SUPER/_SUPER(0) return (x68k_hle)

; --- call faults: numbers stored at SHIM_FAULT+4 (vector 0) ----------------------------
FAULT_IOCS        EQU $0F00      ; + IOCS fn
FAULT_MCDRV       EQU $0400      ; + trap #4 fn: a function other than $01/$02/$05/$14, or fn $01
                                 ; with data that is none of the three tunes (arg: a0)
FAULT_WAIT_MASKED EQU $5741      ; "WA": a shim wait with VBlank masked by the caller

; ==============================================================================
; THE PORT RESERVE'S MAP ($10B000-$10DFFF), in address order: every block the shim uses and
; every free range (RES_FREE<n> .. RES_FREE<n>_END - 1). Each block's end is asserted to be the
; next one's start (RES_MEETS, below; IO_SHADOW's two ends in resume.asm, after game.inc), so a
; block that grows into the next fails the build, and so does a free range that is not exactly
; what lies between two blocks; tests/tools/test_shim_map.py fails on an equate of the shim's that
; lies inside a free range (an allocation not entered here) and checks docs/notes/shim.md's free
; list against these. A later plan allocates from the free ranges: it moves their bounds here.
;   $10B000-$10B02B  the fault record, heartbeat, magic, restarts (not cleared at a resume), the
;                    virtual supervisor flag and the call counters (neogeo.inc, above)
;   $10B02C-$10B02F  free (RES_FREE0)
;   $10B030-$10B05F  XSP's state (xsp.asm)
;   $10B060-$10B0AF  DOS file handles (dos.asm)
;   $10B0B0-$10B0F7  the view on the screen, the sprite drawing's state (sprites.asm's build
;                    variables at SHIM_SPR_END), SHIM_SPR_AVAIL
;   $10B0F8-$10B0FF  free (RES_FREE1)
;   $10B100-$10B107  the sound ring's head, tail and count
;   $10B108-$10B10F  free (RES_FREE2)
;   $10B110-$10B30F  the sound ring (SND_ENTRIES x SND_SIZE: Plan 4 plays it)
;   $10B310-$10B31D  the background's scroll, view and pages; the view's build state
;   $10B31E-$10B31F  free (RES_FREE3)
;   $10B320-$10B325  SHIM_PROF (written by the profile build only; reserved in every build)
;   $10B326-$10B327  free (RES_FREE4)
;   $10B328-$10B32B  SHIM_SPR_PTR (live in every build: the open list's append pointer)
;   $10B32C-$10B3C5  the sound drain's state (SHIM_SND_DONE .. SHIM_SND_FXPTR: sound.asm)
;   $10B3C6-$10B3CD  _ADPCMSNS's busy model (SHIM_SE_BUSY .. SHIM_SE_SMPF: iocs.asm, sound.asm)
;   $10B3CE-$10B3D5  the BIOS layer's state (SHIM_BIOS_MODE .. SHIM_DEMO_LEFT: bios.asm)
;   $10B3D6-$10B3DD  the title hook's state (SHIM_TITLE_STATE .. SHIM_TITLE_COIN: title.asm)
;   $10B3DE-$10B3E5  the attract demo's state (SHIM_DEMO_STATE .. SHIM_DEMO_FROM: demo.asm)
;   $10B3E6-$10B3E7  the KAKUSI code's window (SHIM_TITLE_KWAIT: title.asm)
;   $10B3E8-$10B3FF  free (RES_FREE5)
;   $10B400-$10B4FD  the xsp_wpoke buffer (WPK_BYTES)
;   $10B4FE-$10B503  the test builds' words (SHIM_TEST_UNTIL, SHIM_TEST_RET, SHIM_TEST_CO)
;   $10B504-$10B5FF  free (RES_FREE6)
;   $10B600-$10B7FF  the boot stack (SHIM_STATE_HI .. SHIM_BOOT_SP)
;   $10B800-$10C7FF  IO_SHADOW (link.py, game.inc)
;   $10C800-$10D7C7  the sprite build's work areas (SHIM_SPR_HEADS .. SHIM_SPR_WAREA_END)
;   $10D7C8-$10D81F  free (RES_FREE7)
;   $10D820-$10DD3F  the text model (SHIM_TEXT .. SHIM_TEXT_END; SHIM_BOMB_BITS last)
;   $10DD40-$10DD41  the text clear's blank request (SHIM_TEXT_BLANK: text.asm)
;   $10DD42-$10DE7F  the co-op's state (SHIM_COOP .. SHIM_COOP_END: coop.asm)
;   $10DE80-$10DE83  player 2's bomb places' bits (SHIM_BOMB_BITS2: text.asm)
;   $10DE84-$10DE85  the credits the join prompt was written for (SHIM_COOP_CREDITS), P2's START
;                    (SHIM_COOP_P2KEY: coop.asm)
;   $10DE86-$10DEE5  WAVES' state (SHIM_WAVES .. SHIM_WAVES_END: title.asm, waves.asm)
;   $10DEE6-$10DFDF  free (RES_FREE8)
;   $10DFE0-$10DFFF  the preserved block (SHIM_KEEP: not cleared at a resume)
; Cleared at every resume: SHIM_STATE_LO .. SHIM_STATE_HI and SHIM_HIGH_LO .. SHIM_HIGH_HI (the
; free ranges in them too); the stack follows at $10E000.
RES_FREE0         EQU $0010B02C
RES_FREE0_END     EQU $0010B030
RES_FREE1         EQU $0010B0F8
RES_FREE1_END     EQU $0010B100
RES_FREE2         EQU $0010B108
RES_FREE2_END     EQU $0010B110
RES_FREE3         EQU $0010B31E
RES_FREE3_END     EQU $0010B320
RES_FREE4         EQU $0010B326
RES_FREE4_END     EQU $0010B328
RES_FREE5         EQU $0010B3E8
RES_FREE5_END     EQU $0010B400
RES_FREE6         EQU $0010B504
RES_FREE6_END     EQU $0010B600
RES_FREE7         EQU $0010D7C8
RES_FREE7_END     EQU $0010D820
RES_FREE8         EQU $0010DEE6
RES_FREE8_END     EQU $0010DFE0

; RES_MEETS end, start: a block's (or free range's) end must be the next one's start
RES_MEETS macro
    if (\1)!=(\2)
    fail "the port reserve's map (shim.inc): \1 is not \2"
    endif
    endm

    RES_MEETS SHIM_FAULT, $0010B000
    RES_MEETS SHIM_RESTARTS+2, SHIM_STATE_LO
    RES_MEETS SHIM_STATE_LO, SHIM_SUPER
    RES_MEETS SHIM_JOY_COUNT+4, RES_FREE0
    RES_MEETS RES_FREE0_END, SHIM_XSP_ON
    RES_MEETS SHIM_XSP_OUTS+4, SHIM_FILES
    RES_MEETS SHIM_FILES_END, SHIM_VIEW
    RES_MEETS SHIM_VIEW+2, SHIM_SPR_KEY
    RES_MEETS SHIM_SPR_KEY+12, SHIM_SPR_LOW
    RES_MEETS SHIM_SPR_RUN+2, SHIM_SPR_END
    RES_MEETS SHIM_SPR_AVAIL+2, RES_FREE1
    RES_MEETS RES_FREE1_END, SHIM_SND_HEAD
    RES_MEETS SHIM_SND_COUNT+4, RES_FREE2
    RES_MEETS RES_FREE2_END, SHIM_SND
    RES_MEETS SHIM_SND_END, SHIM_BG_SCROLL0
    RES_MEETS SHIM_BG_END, RES_FREE3
    RES_MEETS RES_FREE3_END, SHIM_PROF
    RES_MEETS SHIM_PROF_END, RES_FREE4
    RES_MEETS RES_FREE4_END, SHIM_SPR_PTR
    RES_MEETS SHIM_SPR_PTR+4, SHIM_SND_DONE
    RES_MEETS SHIM_SND_TUNE+2, SHIM_SND_LAST
    RES_MEETS SHIM_SND_LAST+2, SHIM_SND_MUSIC
    RES_MEETS SHIM_SND_MUSIC+2, SHIM_SND_FXC
    RES_MEETS SHIM_SND_FXC+12, SHIM_SND_FXPTR
    RES_MEETS SHIM_SND_STATE_END, SHIM_SE_BUSY
    RES_MEETS SHIM_SE_BUSY+2, SHIM_SE_SMP
    RES_MEETS SHIM_SE_SMP+4, SHIM_SE_SMPF
    RES_MEETS SHIM_SE_SMPF+2, SHIM_SE_END
    RES_MEETS SHIM_SE_END, SHIM_BIOS_MODE
    RES_MEETS SHIM_DEMO_LEFT+2, SHIM_BIOS_END
    RES_MEETS SHIM_BIOS_END, SHIM_TITLE_STATE
    RES_MEETS SHIM_TITLE_COIN+2, SHIM_TITLE_END
    RES_MEETS SHIM_TITLE_END, SHIM_DEMO_STATE
    RES_MEETS SHIM_DEMO_FROM+2, SHIM_DEMO_END
    RES_MEETS SHIM_DEMO_END, SHIM_TITLE_KWAIT
    RES_MEETS SHIM_TITLE_KWAIT+2, SHIM_KWAIT_END
    RES_MEETS SHIM_KWAIT_END, RES_FREE5
    RES_MEETS RES_FREE5_END, SHIM_WPK_WORK
    RES_MEETS SHIM_WPK_END, SHIM_TEST_UNTIL
    RES_MEETS SHIM_TEST_UNTIL+2, SHIM_TEST_RET
    RES_MEETS SHIM_TEST_RET+2, SHIM_TEST_CO
    RES_MEETS SHIM_TEST_CO+2, SHIM_TEST_END
    RES_MEETS SHIM_TEST_END, RES_FREE6
    RES_MEETS RES_FREE6_END, SHIM_STATE_HI
    RES_MEETS SHIM_STATE_HI+$200, SHIM_BOOT_SP
    RES_MEETS SHIM_HIGH_LO, SHIM_SPR_HEADS
    RES_MEETS SHIM_SPR_WAREA_END, RES_FREE7
    RES_MEETS RES_FREE7_END, SHIM_TEXT
    RES_MEETS SHIM_TEXT+TEXT_COLS*TEXT_ROWS, SHIM_TEXT_DIRTY
    RES_MEETS SHIM_TEXT_DIRTY+4*TEXT_COLS, SHIM_TEXT_USED
    RES_MEETS SHIM_TEXT_USED+4*TEXT_COLS, SHIM_TEXT_ON
    RES_MEETS SHIM_TEXT_FIXON+2, SHIM_BOMB_BITS
    RES_MEETS SHIM_BOMB_BITS+4, SHIM_TEXT_END
    RES_MEETS SHIM_TEXT_END, SHIM_TEXT_BLANK
    RES_MEETS SHIM_TEXT_BLANK+2, SHIM_TEXT_BLANK_END
    RES_MEETS SHIM_TEXT_BLANK_END, SHIM_COOP
    RES_MEETS SHIM_COOP_2P+1, SHIM_COOP_NEW
    RES_MEETS SHIM_COOP_NEW+1, SHIM_COOP_PAD
    RES_MEETS SHIM_COOP_PAD+1, SHIM_COOP_START2
    RES_MEETS SHIM_COOP_START2+1, SHIM_COOP_LIVE
    RES_MEETS SHIM_COOP_LIVE+1, SHIM_COOP_IN
    RES_MEETS SHIM_COOP_IN+1, SHIM_COOP_CTX
    RES_MEETS SHIM_COOP_CTX+1, SHIM_COOP_REQ
    RES_MEETS SHIM_COOP_REQ+1, SHIM_COOP_BOMB
    RES_MEETS SHIM_COOP_BOMB+1, SHIM_COOP_TAIL
    RES_MEETS SHIM_COOP_TAIL+1, SHIM_COOP_NFREE
    RES_MEETS SHIM_COOP_NFREE+2, SHIM_COOP_SCORE2
    RES_MEETS SHIM_COOP_SCORE2+4, SHIM_COOP_OWN
    RES_MEETS SHIM_COOP_OWN+4, SHIM_COOP_P2
    RES_MEETS SHIM_COOP_P2+COOP_P2_SIZE, SHIM_COOP_TGT
    RES_MEETS SHIM_COOP_TGT+2*128, SHIM_COOP_SWAP
    RES_MEETS SHIM_COOP_SWAP+1, SHIM_COOP_PROMPT
    RES_MEETS SHIM_COOP_PROMPT+1, SHIM_COOP_END
    RES_MEETS SHIM_COOP_END, SHIM_BOMB_BITS2
    RES_MEETS SHIM_BOMB_BITS2+4, SHIM_COOP_CREDITS
    RES_MEETS SHIM_COOP_CREDITS+1, SHIM_COOP_P2KEY
    RES_MEETS SHIM_COOP_P2KEY+1, SHIM_WAVES
    RES_MEETS SHIM_WAVES_END, RES_FREE8
    RES_MEETS RES_FREE8_END, SHIM_HIGH_HI
    RES_MEETS SHIM_HIGH_HI, SHIM_KEEP
    if KEEP_SUM+2>KEEP_SIZE
    fail "the preserved block's fields (shim.inc KEEP_*) are past KEEP_SIZE"
    endif
    RES_MEETS SHIM_KEEP_END, $0010E000
