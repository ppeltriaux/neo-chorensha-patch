; ==============================================================================
; RESUME: the original's start-up ran at build time (tools/preinit.py); its snapshot is in
; P-ROM (build/link). Shim_Resume (SYSTEM_IO served every frame of it) puts the RAM objects, the
; I/O shadow and the live stack
; in place, sets up the shim's state as the start-up left XSP, starts the timer that models
; MFP GPIP's V-DISP bit, loads main's registers and jumps to main's first title-menu call.
; Also here: the VBlank and timer interrupts, the shim's VBlank wait and the call fault.
; ==============================================================================

SHIM_TEST_CALL  EQU $FF7E           ; make cart SHIM_TEST_UNKNOWN=1: a DOS call nobody serves

    ifnd    IOSH_E88001
    fail    "IOSH_E88001 (MFP GPIP) not in the I/O shadow: the V-DISP model needs it"
    endif
    ; IO_SHADOW (game.inc) between the boot stack and the sprite build's work areas (shim.inc's
    ; map of the port reserve)
    RES_MEETS SHIM_BOOT_SP, IO_SHADOW
    RES_MEETS IO_SHADOW+IO_SHADOW_SIZE, SHIM_HIGH_LO

; The BIOS sees a coin only in SYSTEM_IO, so the resume serves it every frame too (final review I1:
; a coin pressed and let go while a resume ran with every interrupt masked, 12 frames then, was
; lost; and the BIOS counts a second coin only after two calls saw the first let go). Until
; Bios_Resume writes the mode, SHIM_BIOS_MODE is 0 and the VBlank does SYSTEM_IO alone
; (Shim_VBlank's settling part, as in Shim_Boot's settle frames): the clears and copies run with
; the VBlank on, on the stack's top (as Shim_Boot's); the VRAM's and the palettes' set-up (which
; the Universe BIOS's menu, opened from SYSTEM_IO, would write too) and the stack's own fill and
; the mode at the end run masked, about 0.8 and 0.1 frame: a VBlank in them is served as they end
; (pending), never lost. PLAYER_START refuses all along (SHIM_BIOS_MODE and SHIM_TITLE_ON 0), and
; a coin's DEMO_END and SYSTEM_RETURN (a demo's resume, USER_MODE 1) only abandon a resume the
; BIOS's next USER makes again. The whole resume takes about 2.2 frames (the clears and copies by
; movem: Shim_Clear).
Shim_Resume:
    move.w  #$2700, sr
    lea     STACK_TOP, sp
    move.w  d7, -(sp)               ; the mode (bios.asm), kept over the clears
    move.b  d0, REG_WATCHDOG
    clr.w   SHIM_BIOS_MODE          ; the VBlank's settling part (SYSTEM_IO alone) from here
    clr.w   SHIM_TITLE_ON           ; (PLAYER_START refuses: the BIOS takes no credit)
    clr.w   SHIM_START_REQ
    move.w  #0, REG_LSPCMODE        ; timer off while the state is set up
    move.w  #IRQACK_ALL, REG_IRQACK
    move.w  #$2000, sr              ; the VBlank on (no timer)

    ; game RAM: zero, then the RAM objects' snapshot values
    lea     GAME_RAM_LO, a0
    move.l  #GAME_RAM_HI-GAME_RAM_LO, d0
    bsr     Shim_Clear
    lea     RAMIMAGE_ROM, a0
    lea     RAMIMAGE_DEST, a1
    move.l  #RAMIMAGE_SIZE, d0
    bsr     Shim_Copy

    ; the shim's state and the I/O shadow
    lea     SHIM_STATE_LO, a0
    move.l  #SHIM_STATE_HI-SHIM_STATE_LO, d0
    bsr     Shim_Clear
    lea     SHIM_HIGH_LO, a0
    move.l  #SHIM_HIGH_HI-SHIM_HIGH_LO, d0
    bsr     Shim_Clear
    lea     IO_SHADOW, a0
    move.l  #IO_SHADOW_SIZE, d0
    bsr     Shim_Clear
    lea     IOSH_IMAGE, a0
    lea     IO_SHADOW, a1
    move.l  #IOSH_IMAGE_SIZE, d0
    bsr     Shim_Copy
    move.b  #GPIP_IDLE, IOSH_E88001 ; MFP GPIP: display period, H-sync high

    bsr     Xsp_Init                ; XSP as the start-up left it (xsp.asm)
    move.w  #$2700, sr              ; (VRAM and palettes: masked)
    bsr     Sprites_Init            ; the object sprites hidden (sprites.asm)
    bsr     Bg_Init                 ; the background chains, hidden (sprites.asm)
    bsr     Text_Init               ; the fix layer blank but the side strips, drawn once, the
                                    ; text sprites hidden (text.asm)
    bsr     Pal_Init                ; the static colours, palettes.bin (palette.asm)
    move.w  #$2000, sr
    bsr     Snd_Init                ; the sound drain's tables (sound.asm)

    ; masked to the end: the stack below the stack top (this one's place: the boot stack's from
    ; here): STACK_FILL (the high-water mark: tests/neo/lib.lua's stack_depth), then main's live
    ; frames at GAME_SP
    move.w  #$2700, sr
    move.w  (sp)+, d7
    lea     SHIM_BOOT_SP, sp
    lea     STACK_TOP-$1000, a0
    move.l  #$1000, d0
    move.w  #STACK_FILL, d2
    bsr     Shim_Fill
    lea     GAME_STACK_IMAGE, a0
    lea     GAME_SP, a1
    move.l  #GAME_STACK_SIZE, d0
    bsr     Shim_Copy

    move.w  d7, d0
    bsr     Bios_Resume             ; the mode: SHIM_BIOS_MODE, the demo's frames, USER_MODE
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .fresh                  ; the demo: always the snapshot's settings
    bsr     Keep_Restore            ; the title: the settings the preserved block keeps
.fresh:

    ; LSPC timer: fires GPIP_BLANK_LINES lines after every VBlank (Shim_Level2)
    move.w  #0, REG_TIMERHIGH
    move.w  #GPIP_BLANK_LINES*384-1, REG_TIMERLOW
    move.w  #LSPC_TIMER_ON, REG_LSPCMODE
    move.w  #IRQACK_ALL-IRQACK_VBLANK, REG_IRQACK  ; (a VBlank in the masked end still pending:
                                    ; its SYSTEM_IO runs as the game starts)
    move.b  d0, REG_WATCHDOG

    ifd     SHIM_TEST_ROMWRITE
    move.w  #$4E71, GAME_ROM        ; a write into P-ROM: the tripwire must report it
    endif

    movem.l GAME_REGS, d0-d7/a0-a6
    lea     GAME_SP, sp
    move.w  #$2000, sr              ; supervisor (the game's own mode is virtual: SHIM_SUPER),
                                    ; VBlank and timer on
    ifd     SHIM_TEST_UNKNOWN
    dc.w    SHIM_TEST_CALL          ; an unimplemented DOS call: the shim must report it
    endif
    jmp     GAME_RESUME

; ------------------------------------------------------------------------------
; Shim_Clear: zero d0.l bytes (even) from a0. Shim_Fill: the same with the word d2.
; Shim_Copy: d0.l bytes (even) a0 -> a1. a0 (and a1) end past the bytes; d0-d1 used, d2 too by
; Shim_Clear and Shim_Fill; every other register kept.
; SHIM_BLOCK bytes a movem (twelve longs), the rest by words: about 2.5 cycles a byte cleared and
; 4.8 copied (a word at a time took 24), so the whole resume takes about 2.2 frames (it took 12,
; all of them masked: final review I1, Shim_Resume above). d0.l < SHIM_BLOCK * 65,536 (divu): the
; largest is game RAM's 44 KB. The watchdog is kicked as each starts: the longest takes ~9 ms, the
; whole resume ~37 ms, well inside its ~0.13 s.
; ------------------------------------------------------------------------------
SHIM_BLOCK      EQU 48              ; d1-d7/a2-a6: 12 longs

Shim_Clear:
    moveq   #0, d2
Shim_Fill:
    move.b  d0, REG_WATCHDOG
    movem.l d3-d7/a2-a6, -(sp)
    move.w  d2, d1                  ; the word twice in each long
    swap    d2
    move.w  d1, d2
    move.l  d2, d1
    move.l  d2, d3
    move.l  d2, d4
    move.l  d2, d5
    move.l  d2, d6
    move.l  d2, d7
    movea.l d2, a2
    movea.l d2, a3
    movea.l d2, a4
    movea.l d2, a5
    movea.l d2, a6
    divu    #SHIM_BLOCK, d0         ; d0.w the blocks, its high word the rest (bytes, even)
    bra.s   .btest
.block:
    movem.l d1-d7/a2-a6, (a0)
    lea     SHIM_BLOCK(a0), a0
.btest:
    dbra    d0, .block
    swap    d0
    lsr.w   #1, d0
    bra.s   .wtest
.word:
    move.w  d2, (a0)+
.wtest:
    dbra    d0, .word
    movem.l (sp)+, d3-d7/a2-a6
    rts

Shim_Copy:
    move.b  d0, REG_WATCHDOG
    movem.l d2-d7/a2-a6, -(sp)
    divu    #SHIM_BLOCK, d0
    bra.s   .btest
.block:
    movem.l (a0)+, d1-d7/a2-a6
    movem.l d1-d7/a2-a6, (a1)
    lea     SHIM_BLOCK(a1), a1
.btest:
    dbra    d0, .block
    swap    d0
    lsr.w   #1, d0
    bra.s   .wtest
.word:
    move.w  (a0)+, (a1)+
.wtest:
    dbra    d0, .word
    movem.l (sp)+, d2-d7/a2-a6
    rts

; ==============================================================================
; THE PRESERVED BLOCK (Plan 5 Task 2; SHIM_KEEP, shim.inc): CONFIG's and KAKUSI's settings survive
; every return from the BIOS or the demo, the CONTINUE stage only if KAKUSI set it.
;   * Restore (Keep_Restore): at every title-mode resume, never a demo's (the demo always runs from
;     the snapshot). A valid block goes back into the settings' homes (the stage only while
;     KEEP_KSTAGE says KAKUSI set it last: else a CONTINUE after a demo starts fresh, the
;     controller's ruling on plan5-recon.md 2.2); an invalid one (power-on) leaves the snapshot's
;     values and is made from them.
;   * Save (Keep_Save): the settings change only in CONFIG and KAKUSI, and the stage in play
;     (START, the stage ends). Rather than a check on every write to the homes or every menu pass
;     (both on paths the game runs every frame), the block is saved when a screen changes: the
;     text clear $1888 (Shim_TextClear: Keep_Screen) that the title, CONFIG and KAKUSI make as they
;     open and close and the game over makes before the title; and on the game's own way back to
;     the BIOS (bios.asm Bios_Return). In title mode only: the demo saves nothing. Nothing of it
;     runs every frame (the game over's clear, $44F4, runs once a game). A return from inside a menu
;     (the BIOS's test menu, a reset) keeps the settings that menu's visit found, not its changes.
;   * The stage's flag (KEEP_KSTAGE), from the clear's caller (its jsr's return address):
;     KAKUSI's opening clear notes the stage (KEEP_KENTRY); its EXIT's clear sets the flag if the
;     stage changed meanwhile (the stage item, $32FE: the only stage write in KAKUSI). The title's
;     closing clear with item 0 in d4 (START: main then writes stage 1 and clears acchoh, $3F42 /
;     $3F4A) clears the flag and keeps those two values; CONTINUE writes no stage. A save that finds
;     the stage changed since the last one clears the flag (play's stage ends $8132 / $8DF8 / $9774,
;     stages 4-5 played as 1 at $4A50). That compares values: no save falls between two stages of a
;     game, so a game that comes round to KAKUSI's own stage again and loses there keeps the flag
;     (the value restored is KAKUSI's anyway). It is not a "play wrote the stage" signal.
; ==============================================================================
KEEP_AT_TITLE   EQU GAME_ROM+$2C1C  ; the title's clear as it returns its item (move.w d4,d0 follows)
KEEP_AT_KAKUSI  EQU GAME_ROM+$310C  ; KAKUSI's clear as it opens ($30FC)
KEEP_AT_EXIT    EQU GAME_ROM+$3376  ; KAKUSI's EXIT clear

; Keep_Restore (Shim_Resume, title mode): see above. Uses d0-d1/a0-a1.
Keep_Restore:
    bsr.s   Keep_Valid              ; a0 = SHIM_KEEP
    suba.l  a1, a1                  ; (no screen change; the condition codes kept)
    bne.s   .power
    bra.s   .valid
.power:
    clr.l   KEEP_WAVES_BEST(a0)     ; power-on: no best WAVES score yet (outside the sum)
    bra     Keep_Save               ; the snapshot's values stay; the block made of them
.valid:
    move.w  KEEP_XSP(a0), GV_XSP_MODE
    move.w  KEEP_XSP(a0), SHIM_XSP_MODE ; the sprite drawing's, as xsp_mode2 sets it (2 always:
                                        ; CONFIG has no XSP MODE item since 2026-10-28)
    move.w  KEEP_SWAP(a0), GV_SWAP
    move.w  KEEP_PCM(a0), GV_PCM_PLAY
    move.w  KEEP_BGM(a0), GV_BGM_PLAY
    move.w  KEEP_MUTEKI(a0), GV_MUTEKI
    move.w  KEEP_ACCHOH(a0), GV_ACCHOH
    tst.b   KEEP_KSTAGE(a0)
    beq.s   .done                   ; KAKUSI did not set it: the CONTINUE stage is forgotten
    move.w  KEEP_STAGE(a0), GV_STAGE
.done:
    rts

; Keep_Valid: Z set if the block is valid: its magic, its sum, and every value in the range the
; game gives it (KEEP_RANGES: a block another layout of these fields wrote -- a later version's,
; say -- most likely reads as invalid rather than putting a wrong value in a home: a reordered
; block can still be in range). a0 = SHIM_KEEP; d0-d1 used.
Keep_Valid:
    lea     SHIM_KEEP, a0
    bsr.s   Keep_Sum
    cmp.w   KEEP_SUM(a0), d0
    bne.s   .no
    cmpi.l  #KEEP_MAGIC_VALUE, KEEP_MAGIC(a0)
    bne.s   .no
    move.l  d2, -(sp)
    moveq   #0, d1
.range:
    moveq   #0, d0
    move.b  KEEP_RANGES(pc,d1.w), d0
    beq.s   .in                     ; (the table's end: Z set, valid)
    moveq   #0, d2
    btst    #0, d0
    beq.s   .word
    move.b  (a0,d0.w), d2           ; an odd offset: a byte (KEEP_AUTOFIRE)
    bra.s   .value
.word:
    move.w  (a0,d0.w), d2
    cmpi.w  #$FF, d2
    bhi.s   .out
.value:
    cmp.b   KEEP_RANGES+1(pc,d1.w), d2
    blo.s   .out
    cmp.b   KEEP_RANGES+2(pc,d1.w), d2
    bhi.s   .out
    addq.w  #3, d1
    bra.s   .range
.out:
    moveq   #1, d0                  ; Z clear: invalid
.in:
    movem.l (sp)+, d2               ; (the condition codes kept)
.no:
    rts

; KEEP_RANGES: (offset, lowest, highest) of each word Keep_Restore puts back, as the game's own
; code bounds it (CONFIG $2F04 / $2FA6 / $300E / $3074, KAKUSI $32E8 / $32FE / $3348), and of AUTO
; FIRE's byte (an odd offset: Keep_Valid reads a byte there; config.asm toggles it 0 / 1); offset 0
; ends.
KEEP_RANGES:
    dc.b    KEEP_XSP, 1, 3
    dc.b    KEEP_SWAP, 0, 1
    dc.b    KEEP_PCM, 0, $3F
    dc.b    KEEP_BGM, 0, $3F
    dc.b    KEEP_MUTEKI, 0, 1
    dc.b    KEEP_ACCHOH, 0, 1
    dc.b    KEEP_STAGE, 1, 5
    dc.b    KEEP_KENTRY, 1, 5
    dc.b    KEEP_AUTOFIRE, 0, 1
    dc.b    0
    even
    if (KEEP_AUTOFIRE&1)==0
    fail "resume.asm: Keep_Valid reads KEEP_AUTOFIRE as a byte at an odd offset"
    endif

; Keep_Sum: d0.w = the sum of the block's words KEEP_XSP .. KEEP_SUM - 2 (a0 = SHIM_KEEP). d1 used.
Keep_Sum:
    moveq   #0, d0
    moveq   #KEEP_SUM-2, d1
.add:
    add.w   (a0,d1.w), d0
    subq.w  #2, d1
    cmpi.w  #KEEP_XSP, d1
    bge.s   .add
    rts

; Keep_Screen (Shim_TextClear, first): a screen change. 4(sp) = the clear's caller (its jsr's
; return address), d4 = its d4. Saves the block in title mode. Every register and the condition
; codes kept (Shim_TextClear's contract: tests/tools/test_text_regs.py).
Keep_Screen:
    move.w  sr, -(sp)
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .out
    movem.l d0-d1/a0-a1, -(sp)
    movea.l 2+16+4(sp), a1          ; (sr, d0-d1/a0-a1, Keep_Screen's return)
    bsr.s   Keep_Save
    movem.l (sp)+, d0-d1/a0-a1
.out:
    move.w  (sp)+, ccr
    rts

; Keep_Save: the settings' homes into the block, the stage's flag updated, the block sealed. a1 =
; the screen change's caller (Keep_Screen; else 0), d4 = its d4. Uses d0-d1/a0. A save cut short
; (the BIOS taking over in the middle: its test menu) leaves a block whose sum is wrong, unless
; the words written so far did not change: either way no wrong settings come back.
Keep_Save:
    bsr     Keep_Valid              ; a0 = SHIM_KEEP
    beq.s   .valid
    sf      KEEP_KSTAGE(a0)         ; power-on: KAKUSI has set nothing,
    sf      KEEP_AUTOFIRE(a0)       ; AUTO FIRE the soft DIP's default: OFF (0) unless the
    cmpi.b  #1, SOFT_DIP_AUTOFIRE   ; operator's option 1 (header.asm) is ON (1)
    bne.s   .dip
    move.b  #1, KEEP_AUTOFIRE(a0)
.dip:
    move.w  GV_STAGE, KEEP_STAGE(a0)
    move.w  GV_STAGE, KEEP_KENTRY(a0)
.valid:
    move.w  GV_STAGE, d0
    cmp.w   KEEP_STAGE(a0), d0
    beq.s   .same
    sf      KEEP_KSTAGE(a0)         ; written since the last save (KAKUSI's own write: below)
.same:
    move.w  d0, KEEP_STAGE(a0)
    move.w  GV_XSP_MODE, KEEP_XSP(a0)
    move.w  GV_SWAP, KEEP_SWAP(a0)
    move.w  GV_PCM_PLAY, KEEP_PCM(a0)
    move.w  GV_BGM_PLAY, KEEP_BGM(a0)
    move.w  GV_MUTEKI, KEEP_MUTEKI(a0)
    move.w  GV_ACCHOH, KEEP_ACCHOH(a0)
    cmpa.l  #KEEP_AT_KAKUSI, a1
    bne.s   .exit
    move.w  d0, KEEP_KENTRY(a0)     ; KAKUSI opens: its stage before
    bra.s   Keep_Seal
.exit:
    cmpa.l  #KEEP_AT_EXIT, a1
    bne.s   .title
    cmp.w   KEEP_KENTRY(a0), d0
    beq.s   Keep_Seal
    st      KEEP_KSTAGE(a0)         ; KAKUSI changed the stage: KAKUSI set it last
    bra.s   Keep_Seal
.title:
    cmpa.l  #KEEP_AT_TITLE, a1
    bne.s   Keep_Seal
    tst.w   d4
    bne.s   Keep_Seal               ; WAVES (1), CONTINUE (2): no stage written (main)
    sf      KEEP_KSTAGE(a0)         ; START: main's next writes ($3F42, $3F4A)
    move.w  #1, KEEP_STAGE(a0)
    clr.w   KEEP_ACCHOH(a0)
    ; (on into Keep_Seal)

; Keep_Seal: the block's sum and magic (a0 = SHIM_KEEP): valid from here. Whatever writes the
; block's own bytes (config.asm: KEEP_AUTOFIRE) seals it again. Uses d0-d1.
Keep_Seal:
    bsr     Keep_Sum
    move.w  d0, KEEP_SUM(a0)
    move.l  #KEEP_MAGIC_VALUE, KEEP_MAGIC(a0)
    rts

; ------------------------------------------------------------------------------
; Level 1: VBlank. While the BIOS is in control it gets the interrupt. Once the game runs:
; the frame counter, MFP GPIP's V-DISP bit (vertical blank starts), and what XSP's V-DISP
; interrupt did that the game can see: vsync_count + 1 and the display buffer moving on to
; the next finished one (xsp_out waits on it). Then the picture, the VRAM ports' only user
; from here on: the background chains' two heads, the colours of a new list on display
; (palette.asm Pal_Take: its xsp_wpoke palette words) and its sprites (sprites.asm
; Spr_Upload: in that order), then the text model's changes (text.asm Text_Flush, which stops
; when the display begins). SHIM_VBL_LINES keeps the most raster lines one VBlank took to there
; (the test and profile builds: shim.inc COST_START). Then the sound ring's new calls go to the
; Z80 (sound.asm Snd_Drain): no VRAM, so it may run on into the display; only here, in the game's
; part (BIOS_SYSTEM_MODE bit 7 set: the BIOS owns the Z80 otherwise). Last, the BIOS's SYSTEM_IO
; (bios.asm Bios_Frame: no VRAM either), which may not return: nothing is left to do after it.
; Settling (SHIM_BIOS_MODE 0: Shim_Boot's settle frames, and Shim_Resume until it writes the mode,
; the state being set up): the frame counter and SYSTEM_IO alone, so the BIOS sees every frame's
; coins (final review I1) and nothing acts on a state half made.
; ------------------------------------------------------------------------------
Shim_VBlank:
    btst    #7, BIOS_SYSTEM_MODE
    bne.s   .game
    jmp     SYSTEM_INT1
.game:
    PROF_ON PROF_VBL
    move.w  #IRQACK_VBLANK, REG_IRQACK
    move.b  d0, REG_WATCHDOG
    move.l  d0, -(sp)
    tst.w   SHIM_BIOS_MODE
    bne.s   .running
    addq.l  #1, SHIM_HEARTBEAT      ; settling
    bra     .quiet                  ; (a word: the test builds put more between)
.running:
    ifd     SHIM_TEST_LATE
    ; test build: a VBlank late on purpose (tests/neo/sprites.lua SP_LATE): its work waits
    ; until the line counter reaches SHIM_TEST_UNTIL, as when the game masked the interrupt
.late:
    tst.w   SHIM_TEST_UNTIL
    beq.s   .ontime
    bsr     Spr_Line
    cmpi.w  #LSPC_LINE_VBL, d0
    bhs.s   .late                   ; still before the counter wraps
    cmp.w   SHIM_TEST_UNTIL, d0
    blo.s   .late
.ontime:
    endif
    COST_START                      ; the line it began on (the cost: test builds)
    addq.l  #1, SHIM_HEARTBEAT
    bclr    #GPIP_VDISP, IOSH_E88001
    tst.w   SHIM_XSP_ON
    beq.s   .done
    ; XSP's vsync_count, a signed word that xsp_vsync compares with cmp.w/ble (as XSP's own
    ; bgt): it stops at $7FFF instead of wrapping negative. XSP wraps after 32,768 VBlanks
    ; (9.2 minutes) of XSP on without an xsp_vsync, and its next xsp_vsync(n) then waits
    ; another 32K frames; stopping at the top keeps every count below that identical.
    cmpi.w  #$7FFF, SHIM_VSYNC
    beq.s   .top
    addq.w  #1, SHIM_VSYNC
.top:
    move.w  SHIM_XSP_D, d0
    addq.w  #1, d0
    cmpi.w  #3, d0
    blo.s   .ring
    moveq   #0, d0
.ring:
    cmp.w   SHIM_XSP_W, d0          ; the buffer being written is not shown
    beq.s   .done
    move.w  d0, SHIM_XSP_D
.done:
    bsr     Spr_Upload
    bsr     Text_Flush
    COST_END SHIM_VBL_LINES
    move.l  SHIM_SND_COUNT, d0      ; sound calls since the last drain: to the Z80 (sound.asm;
    cmp.l   SHIM_SND_DONE, d0       ; no VRAM: after the blank's work, outside its cost)
    beq.s   .quiet
    bsr     Snd_Drain
.quiet:
    bsr     Bios_Frame              ; last: SYSTEM_IO may not return (bios.asm)
    move.l  (sp)+, d0
    PROF_OFF PROF_VBL
    rte

; ------------------------------------------------------------------------------
; Level 2: the LSPC timer, GPIP_BLANK_LINES lines into the frame: the display period starts
; (GPIP bit 4 back to 1: the game's V-DISP poll $1F92 sees the blank end).
; ------------------------------------------------------------------------------
Shim_Level2:
    PROF_ON PROF_L2
    move.w  #IRQACK_TIMER, REG_IRQACK
    bset    #GPIP_VDISP, IOSH_E88001
    PROF_OFF PROF_L2
    rte

; ------------------------------------------------------------------------------
; Shim_WaitVBlank: wait for the next VBlank, kicking the watchdog. All registers kept.
; A caller whose SR masks the VBlank would wait forever: that is a call fault.
; ------------------------------------------------------------------------------
Shim_WaitVBlank:
    move.l  d0, -(sp)
    move.w  sr, d0
    andi.w  #$0700, d0
    bne.s   .masked
    PROF_ON PROF_WAIT
    move.l  SHIM_HEARTBEAT, d0
.wait:
    move.b  d0, REG_WATCHDOG
    cmp.l   SHIM_HEARTBEAT, d0
    beq.s   .wait
    move.l  (sp)+, d0
    PROF_OFF PROF_WAIT
    rts
.masked:
    move.l  (sp)+, d0
    movea.l (sp), a0                ; the caller
    move.l  #FAULT_WAIT_MASKED, d7
    bra     Shim_CallFault

; ------------------------------------------------------------------------------
; Shim_CallFault: a call the shim does not serve. d7.l = its number (the F-line word, or
; FAULT_IOCS + fn, ...), a0 = where it was made, d1 = the caller's d1 (or an argument).
; Stores vector 0 and the number at SHIM_FAULT and halts, kicking the watchdog.
; ------------------------------------------------------------------------------
Shim_CallFault:
    move.w  #$2700, sr
    move.l  a0, SHIM_FAULT_PC
    move.l  d1, SHIM_FAULT_ARG
    clr.l   SHIM_FAULT
    move.l  d7, SHIM_FAULT+4
.halt:
    move.b  d0, REG_WATCHDOG
    bra.s   .halt
