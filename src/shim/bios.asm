; ==============================================================================
; THE BIOS LAYER (Plan 5 Task 1; docs/notes/plan5-recon.md section 1, the protocol as read from
; the euro and unibios40 ROMs). The BIOS calls USER (boot.asm) with a request: 2 (demo) and 3
; (title) resume the game (Shim_Boot, then Shim_Resume with the request in d7; the resume keeps
; it in SHIM_BIOS_MODE through Bios_Resume). From then on:
;   * Bios_Frame, last in the VBlank's game part (resume.asm, after the sound drain), calls
;     SYSTEM_IO once a frame: the controllers, the coins and credits, START. SYSTEM_IO may call
;     PLAYER_START, or DEMO_END and then SYSTEM_RETURN (a coin, Next / Previous Game, a refused
;     forced start, all in USER_MODE 1): it may never return, so nothing of the VBlank's is left
;     to do after it, and every return to the BIOS goes through a fresh resume.
;   * PLAYER_START (the header's $128, inside SYSTEM_IO) acts on P1's START in the demo (where it
;     leaves it for the title), on P1's and P2's while the title loop waits for one (SHIM_TITLE_ON:
;     title.asm's hook sets it; P2's a two-player game, two credits where counted), and in play on
;     a join or a buy-in (coop.asm Coop_Start: two-player plan Task 6). Anywhere else (CONFIG, the
;     game over, the loader) it clears BIOS_START_FLAG: refused, so the BIOS takes no credit.
;     Accepted at the title, it sets SHIM_START_REQ for the title's hook (a new game). The demo
;     starts no game: where the BIOS would take a credit for its START (the MVS without Free Play,
;     a credit in: a coin just before START, in the 10 frames before the BIOS ends a demo for a
;     credit), the start is refused, so the credit stays for the title, and the title follows all
;     the same.
;   * DEMO_END (the header's $12E, inside SYSTEM_IO, before the BIOS's SYSTEM_RETURN) and
;     Bios_Return (the game's own way back: the demo's end; an idle title, title.asm) stop the
;     music and the effect (sound.asm Snd_StopAll): SYSTEM_RETURN sends the Z80 nothing.
; USER_MODE: the BIOS sets 1 (title / demo) before USER. The demo keeps it: a coin ends the demo
; (the BIOS's DEMO_END) and START reaches PLAYER_START. The title mode sets 2 (game), so that
; neither the forced start nor the coin's demo end can fire in CONFIG or play, and a coin there
; only counts; START still reaches PLAYER_START, which refuses it unless the title waits (or a
; player joins or buys in: coop.asm). The title's hook sets 1 only while its loop waits with
; credits in (title.asm: the countdown).
; The demo (demo.asm): its title, then stage 1 played from a recorded stream (the pad never the
; player's: iocs.asm Iocs_JOYGET), then Bios_Return; BIOS_DEMO_FRAMES after its resume at the latest.
; ==============================================================================

; ------------------------------------------------------------------------------
; Bios_Resume (Shim_Resume, once the state is set up): d0.w = the request the resume serves.
; Uses d0.
; ------------------------------------------------------------------------------
Bios_Resume:
    move.w  d0, SHIM_BIOS_MODE
    move.w  #BIOS_DEMO_FRAMES, SHIM_DEMO_LEFT
    bsr     Demo_Resume             ; the demo's stream from its start (demo.asm)
    cmpi.w  #USER_REQ_TITLE, d0
    bne.s   .demo
    move.b  #USER_MODE_GAME, BIOS_USER_MODE ; the title: no forced start, no demo end by a coin
    rts
.demo:
    move.b  #COOP_PAD_DEMO, SHIM_COOP_PAD   ; _JOYGET's port 0: the demo's stream (iocs.asm)
    rts

; ------------------------------------------------------------------------------
; Bios_Frame (the VBlank, last: after the sound drain): SYSTEM_IO, every register kept around it
; (the BIOS uses them all). Then the demo: a start accepted, or a credit counted, -> the title (a
; fresh resume); its stream played out (demo.asm Demo_Frame) or its backstop's frames over ->
; Bios_Return. Not the demo: the join prompt's request last (coop.asm Coop_Blink). d0 used (the
; VBlank's own). In Shim_Boot's settle frames and in Shim_Resume until
; it writes the mode, SHIM_BIOS_MODE is 0 (cleared: what the last run left there, a demo's last
; frame, is not acted on) and the VBlank calls this alone (resume.asm Shim_VBlank, settling):
; SYSTEM_IO runs every frame, so no coin is missed, but its start check and the demo's end wait 10
; frames after every USER.
; ------------------------------------------------------------------------------
Bios_Frame:
    movem.l d0-d7/a0-a6, -(sp)
    jsr     SYSTEM_IO               ; may not return (DEMO_END, SYSTEM_RETURN)
    movem.l (sp)+, d0-d7/a0-a6
    cmpi.w  #USER_REQ_DEMO, SHIM_BIOS_MODE
    bne.s   .done
    tst.w   SHIM_START_REQ
    bne.s   Bios_Title
    bsr     Bios_Credits
    tst.w   d0
    bgt.s   Bios_Title              ; a credit in: the title (below)
    subq.w  #1, SHIM_DEMO_LEFT
    beq.s   Bios_Return
    bra     Demo_Frame              ; (its rts is the VBlank's)
.done:
    jmp     Coop_Blink              ; not the demo: the join prompt's request (coop.asm: a few
                                    ; tests, no VRAM; nothing added to the demo's VBlank)

; Bios_Title: the demo -> the title, through a fresh resume. For START in the demo (the BIOS has
; taken the start: nothing of the demo's goes on), and for a credit counted in the demo: the SNK
; BIOSes end the demo for a coin themselves (DEMO_END, SYSTEM_RETURN, then USER 3) only while their
; "game start compulsion" is on (backup RAM BIOS_COMPULSION_OFF 0) and not in their first 10 frames
; after a USER; the US BIOS's default is off (final review I2), and with it the demo would play on
; with the credit in, and the BIOS ask for the demo again at its end. From the VBlank: its frame and
; the game's are dropped. USER_MODE 2 at once (the title mode's: Bios_Resume), so that the BIOS
; does not end the resume as a demo with credits in.
Bios_Title:
    move.w  #$2700, sr
    move.b  #USER_MODE_GAME, BIOS_USER_MODE
    bsr     Snd_StopAll
    moveq   #USER_REQ_TITLE, d7
    jmp     Shim_Resume

; ------------------------------------------------------------------------------
; Bios_Return: back to the BIOS, the sound stopped first. Never returns: the BIOS's next USER
; resumes the game (SYSTEM_RETURN resets the stack, so any caller's frames go with it). Called at
; the demo's end (Bios_Frame, demo.asm) and by the title's hook when its title idles (title.asm: the
; way back after a game over) or the demo's title comes back after its game (demo.asm), from the
; game's code.
; ------------------------------------------------------------------------------
Bios_Return:
    move.w  #$2700, sr              ; no VBlank from here: its drain would send the ring's newer
                                    ; calls after the stops, its SYSTEM_IO run once more
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .nosave                 ; the demo's settings are the snapshot's: never kept
    suba.l  a1, a1
    bsr     Keep_Save               ; the settings as the game leaves them (resume.asm)
.nosave:
    bsr     Snd_StopAll
    jmp     SYSTEM_RETURN

    ifd     SHIM_TEST_RETURN
; ------------------------------------------------------------------------------
; Test_Return (make cart SHIM_TEST_RETURN=1; Iocs_JOYGET, the game's code, when a test sets
; SHIM_TEST_RET = n): Bios_Return as the game's code calls it (the title's hook, title.asm)
; with a tune just played (bgm_play's fn $01 and $02 in the ring, not yet drained), timed so that
; a VBlank falls inside it: the line before the VBlank, then n polls (tests/neo/bios.lua
; game_return sweeps n).
; ------------------------------------------------------------------------------
Test_Return:
    move.w  SHIM_TEST_RET, d5
    clr.w   SHIM_TEST_RET
.line:
    bsr     Spr_Line
    cmpi.w  #LSPC_LINE_VBL-1, d0
    bne.s   .line
    lea     SND_TUNE_PTR_0, a0
    moveq   #1, d0                  ; MCDRV fn $01: the tune's data
    SND_PUT #SND_SRC_MCDRV, d0, a0, d3, a4
    moveq   #2, d0                  ; fn $02: play
    SND_PUT #SND_SRC_MCDRV, d0, a0, d3, a4
    move.w  #1, SHIM_SND_MUSIC
.delay:
    subq.w  #1, d5
    bne.s   .delay
    bra     Bios_Return
    endif

; ------------------------------------------------------------------------------
; PLAYER_START (BIOS -> game, from SYSTEM_IO: BIOS_START_FLAG holds the STARTs found, bit 0 P1,
; bit 1 P2). What the BIOS passes (two-player plan Task 6's probe, MAME 0.289: the euro and
; unibios40 MVS BIOSes, the AES on unibios40): P2's START reaches it as bit 1 with P2's own credits
; ($D00035) 0, and an accepted bit 1 takes one of P1's; at the MVS's title (USER_MODE 1) P2's START
; comes as bits 0 and 1 together, and only with two credits in (one: no call), the two then taken;
; with no credit in, neither START reaches it. The AES and Free Play: bit 1 alone, no credit. (The
; US BIOS, its game start compulsion off, never passes P2's START while $D00035 is 0: coop.asm
; Coop_P2Key reads it then, the fallback.) So:
;   * the demo: P1's START leaves it for the title, P2's with it or not (P2's alone: refused, the
;     demo goes on; both: P1's taken alone, as before Task 6);
;   * the title waiting (SHIM_TITLE_ON): P1's, a game (SHIM_START_REQ 1); P2's, a two-player game
;     (SHIM_START_REQ 2: title.asm's hook sets SHIM_COOP_START2, coop.asm joins P2 at the game's
;     first step), where credits are counted only with two in, both bits then left (two taken);
;   * anywhere else, the game's: coop.asm Coop_Start (a join or a buy-in in play; refused in CONFIG,
;     KAKUSI, the loader, and the game over after its last look).
; Refused, BIOS_START_FLAG's bits are cleared: the BIOS takes no credit. Every register kept.
; ------------------------------------------------------------------------------
PLAYER_START:
    move.b  d0, REG_WATCHDOG
    cmpi.w  #USER_REQ_DEMO, SHIM_BIOS_MODE
    beq.s   .demo
    tst.w   SHIM_TITLE_ON
    bne.s   .title
    jsr     Coop_Start              ; not at the title: play, CONFIG, the game over (coop.asm; its
    rts                             ; return here: the BIOS's next fetch from the shim's own code)
.title:
    btst    #1, BIOS_START_FLAG
    bne.s   .two
.accept:
    move.b  #1, BIOS_START_FLAG     ; P1's alone: the BIOS takes P1's credit
    move.w  #1, SHIM_START_REQ
    rts
.two:
    move.l  d0, -(sp)               ; P2's START: two players, two credits where counted
    bsr     Bios_Credits
    tst.w   d0
    bmi.s   .free                   ; none counted (the AES, Free Play): the bits as passed
    cmpi.w  #2, d0                  ; (BCD: 2 or more)
    blt.s   .short
    move.b  #3, BIOS_START_FLAG     ; both: the BIOS takes two of P1's credits
.free:
    move.w  #2, SHIM_START_REQ
    move.l  (sp)+, d0
    rts
.short:
    move.l  (sp)+, d0               ; one credit: nothing
    bra.s   .refuse
.demo:
    btst    #0, BIOS_START_FLAG     ; P1's (P2's with it too: P1's alone taken, .accept) leaves
    beq.s   .refuse                 ; for the title; P2's alone: nothing
    move.l  d0, -(sp)
    bsr     Bios_Credits
    tst.w   d0
    movem.l (sp)+, d0               ; (the condition codes kept)
    bmi.s   .accept                 ; no credit counted (the AES, Free Play): none taken
    move.w  #1, SHIM_START_REQ      ; a credit would be: the title without it (it starts the game)
.refuse:
    clr.b   BIOS_START_FLAG         ; no start: no credit taken
    rts

; ------------------------------------------------------------------------------
; Bios_Credits: d0.w = -1 where no credit is counted (the AES: BIOS_MVS_FLAG 0; the MVS with its
; Free Play DIP on: the BIOS takes none), else P1's credits (BIOS_CREDITS, BCD $00-$99). Uses d0.
; ------------------------------------------------------------------------------
Bios_Credits:
    moveq   #-1, d0
    tst.b   BIOS_MVS_FLAG
    beq.s   .out
    btst    #DIP_FREE_PLAY, REG_DIPSW
    beq.s   .out                    ; (active low: Free Play on)
    moveq   #0, d0
    move.b  BIOS_CREDITS, d0
.out:
    rts

; ------------------------------------------------------------------------------
; DEMO_END (BIOS -> game, from SYSTEM_IO, inside the VBlank; SYSTEM_RETURN follows): the sound
; stopped, no VBlank waited for.
; ------------------------------------------------------------------------------
DEMO_END:
    move.b  d0, REG_WATCHDOG
    bsr     Snd_StopAll
    rts
