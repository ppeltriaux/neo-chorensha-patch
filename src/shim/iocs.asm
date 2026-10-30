; ==============================================================================
; IOCS (trap #15, d0.b = function): what the X68000's IOCS ROM gives the game, on the Neo
; Geo. Arguments in registers as on the X68000; the result in d0; every other register is
; kept. Behaviour matches tools/x68k_hle.py where the start-up already used a call. A
; function not listed below stops the machine: vector 0, number FAULT_IOCS + fn.
;
; Pad map (_JOYGET, X68000 joystick byte, active low):
;   bit 0 up, 1 down, 2 left, 3 right  <- Neo Geo stick (REG_P1CNT bits 0-3)
;   bit 5 trigger A                    <- Neo Geo A (bit 4)
;   bit 6 trigger B                    <- Neo Geo B (bit 5)
;   bits 4 and 7 read 1 (no such inputs). C, D and Start are not mapped. Port 0 = P1,
;   port 1 = P2 (REG_P2CNT); XC stick(1)/strig(1) ask for port 0. Auto-fire (Plan 5 Task 5): in
;   play, the shot button held pulses (Iocs_JOYGET).
; Keyboard (_BITSNS): no key is down (the Neo Geo has no keyboard), but the KAKUSI code: group $A's
;   bit 3 (the X68000's key $53) while P1 holds A+B+C+D (Iocs_BITSNS).
; _BGTEXTGT: BG text page 1 as the game-start loader leaves it (link.py BGTEXT, from preinit).
; ==============================================================================

Shim_IOCS:
    PROF_ON PROF_TRAP
    addq.l  #1, SHIM_IOCS_COUNT
    cmpi.b  #$60, d0
    bhs.s   .high                   ; _ADPCMOUT, _ADPCMMOD: recorded at once (Iocs_Snd)
    cmpi.b  #$04, d0
    beq     Iocs_BITSNS             ; _BITSNS: answered at once, every step of play (Plan 5 Task 5)
.call:
    movem.l d1-d7/a0-a6, -(sp)      ; 56 bytes; the frame (SR, PC after the trap) above
    moveq   #0, d6
    move.b  d0, d6                  ; the function
    move.w  d6, d7
    add.w   d7, d7
    add.w   d7, d7
    lea     IocsTable, a6
    movea.l (a6,d7.w), a6           ; its handler (IocsTable; Iocs_Fault for the others)
    jsr     (a6)                    ; caller's d0-d5/a0-a5 in place, d6 = function
    movem.l (sp)+, d1-d7/a0-a6
    PROF_OFF PROF_TRAP
    rte
.high:
    beq.s   Iocs_Snd                ; ($60)
    cmpi.b  #$67, d0
    beq.s   Iocs_Snd
    bra.s   .call

; ADPCM: _ADPCMOUT ($60: d1 = mode/rate, d2 = length, a1 = sample) and _ADPCMMOD ($67: d1 = 0
; stop, 1 pause, 2 resume) are recorded in the sound ring (shim.inc SND_PUT), which sound.asm's
; Snd_Drain sends to the Z80 (the sample a1 named by its cue's effect index), straight from the
; trap: every se_play makes both (the shots: most frames of play), so they skip the dispatcher's
; save of every register (shim.inc SND_PUT's steps and entry layout, inlined: change both; d0 the
; work register). They also drive
; _ADPCMSNS's busy model (shim.inc SHIM_SE_BUSY; docs/notes/shim.md "Sound"): _ADPCMOUT sets the
; game steps its effect reads busy (SND_FX_FRAMES, through the one-sample cache SHIM_SE_SMP), and
; _ADPCMMOD(0) clears them. d0 = 0, every other register kept.
Iocs_Snd:
    move.l  a0, -(sp)
    move.b  d0, -(sp)               ; the function
    move.l  SHIM_SND_COUNT, d0
    andi.w  #SND_ENTRIES-1, d0
    lsl.w   #4, d0
    lea     SHIM_SND, a0
    adda.w  d0, a0
    move.b  #SND_SRC_IOCS, (a0)+
    move.b  (sp)+, (a0)+
    clr.w   (a0)+
    move.l  d1, (a0)+
    move.l  d2, (a0)+
    move.l  a1, (a0)
    addq.l  #1, SHIM_SND_COUNT      ; (in for the drain)
    lsr.w   #4, d0
    addq.w  #1, d0
    andi.w  #SND_ENTRIES-1, d0
    move.w  d0, SHIM_SND_HEAD
    cmpi.b  #$60, -11(a0)           ; (the entry's function)
    beq.s   .out
    tst.l   d1                      ; _ADPCMMOD: 0 stops the sample
    bne.s   .done
    clr.w   SHIM_SE_BUSY
    bra.s   .done
.out:
    cmpa.l  SHIM_SE_SMP, a1         ; _ADPCMOUT: its effect's steps
    bne.s   .find
    move.w  SHIM_SE_SMPF, SHIM_SE_BUSY
    bra.s   .done
.find:
    bsr     Snd_Frames
    move.w  d0, SHIM_SE_BUSY
.done:
    movea.l (sp)+, a0
    moveq   #0, d0
    PROF_OFF PROF_TRAP
    rte

; IocsTable: the functions served, a handler per function number (0-255; Iocs_Fault for the
; others): Shim_IOCS's dispatch (Plan 3 Task 8: it replaced a list searched entry by entry).
IocsTable:
IOCS_N  set     0
    rept    256
IOCS_D  set     0
    if IOCS_N==$04
    dc.l    Iocs_Fault              ; _BITSNS: Shim_IOCS sends it to Iocs_BITSNS first
IOCS_D  set     1
    endif
    if IOCS_N==$10
    dc.l    Iocs_CRTMOD
IOCS_D  set     1
    endif
    if IOCS_N==$20
    dc.l    Iocs_Zero               ; _B_PUTC: console text, not shown
IOCS_D  set     1
    endif
    if IOCS_N==$22
    dc.l    Iocs_Zero               ; _B_COLOR
IOCS_D  set     1
    endif
    if IOCS_N==$23
    dc.l    Iocs_Zero               ; _B_LOCATE
IOCS_D  set     1
    endif
    if IOCS_N==$3B
    dc.l    Iocs_JOYGET
IOCS_D  set     1
    endif
    if (IOCS_N==$60)|(IOCS_N==$67)
    dc.l    Iocs_Fault              ; _ADPCMOUT, _ADPCMMOD: Shim_IOCS sends them to Iocs_Snd first
IOCS_D  set     1
    endif
    if IOCS_N==$66
    dc.l    Iocs_ADPCMSNS
IOCS_D  set     1
    endif
    if IOCS_N==$7D
    dc.l    Iocs_Zero               ; _SKEY_MOD: software keyboard off (previous mode: off)
IOCS_D  set     1
    endif
    if IOCS_N==$81
    dc.l    Iocs_B_SUPER
IOCS_D  set     1
    endif
    if IOCS_N==$90
    dc.l    Iocs_Zero               ; _G_CLR_ON: graphic screen clear -- reached only on the
                                    ; exit path (XC screen()), where the resume rebuilds VRAM
IOCS_D  set     1
    endif
    if IOCS_N==$AE
    dc.l    Iocs_Zero               ; _OS_CURON: text cursor
IOCS_D  set     1
    endif
    if IOCS_N==$AF
    dc.l    Iocs_Zero               ; _OS_CUROF
IOCS_D  set     1
    endif
    if IOCS_N==$B2
    dc.l    Iocs_VPAGE              ; _VPAGE: graphic pages shown (the background chains)
IOCS_D  set     1
    endif
    if IOCS_N==$CE
    dc.l    Iocs_BGTEXTGT
IOCS_D  set     1
    endif
    if IOCS_D==0
    dc.l    Iocs_Fault              ; not served: vector 0, number FAULT_IOCS + fn
    endif
IOCS_N  set     IOCS_N+1
    endr

; a handler's own fault: the call's number (FAULT_IOCS + fn), at its trap, d1 as the caller's
Iocs_Fault:
    move.l  d6, d7
    addi.l  #FAULT_IOCS, d7
    movea.l 4+56+2(sp), a0          ; the stacked PC (after the trap), above the dispatcher's
    subq.l  #2, a0                  ; return address and the 56 bytes of saved registers
    bra     Shim_CallFault

Iocs_Zero:
    moveq   #0, d0
    rts

; _BITSNS(d1 = key group): d0 = the group's keys down. None, but group $A's bit 3 (the X68000's key
; $53) while P1 holds A, B, C and D (REG_P1CNT bits 4-7 all 0): the KAKUSI code (Plan 5 Task 5). The
; game reads group $A in one place, the title's KAKUSI gate on its CONFIG item ($2C2A; link.py
; TITLE_CODE takes the gate's debug-flag test out); every other group stays 0, above all group 0,
; which the play loop reads every step ($4114): its bit 1 (ESC) pauses the game. The demo's pad is
; never the player's: 0 there too. Straight from the trap (Shim_IOCS), as Iocs_Snd: it runs every
; step of play, so it skips the dispatcher's save of every register (d0 alone changes).
KAKUSI_GROUP    EQU $A
KAKUSI_KEY_BIT  EQU 3
Iocs_BITSNS:
    cmpi.l  #KAKUSI_GROUP, d1
    bne.s   .none
    cmpi.w  #USER_REQ_DEMO, SHIM_BIOS_MODE
    beq.s   .none
    move.b  REG_P1CNT, d0
    andi.b  #$F0, d0                ; A, B, C, D: active low
    bne.s   .none
    moveq   #1<<KAKUSI_KEY_BIT, d0
    bra.s   .out
.none:
    moveq   #0, d0
.out:
    PROF_OFF PROF_TRAP
    rte

; _VPAGE(d1.b = the graphic pages shown: bit 0 page 0, bit 1 page 1 in the game's 256-colour
; mode): kept in SHIM_VPAGE, which shows or hides the background chains (sprites.asm Bg_Heads).
; The game calls it with 0 at the title ($2A3C) and before the game-start builder ($405E), with
; 3 after it ($4070). d0 = 0, as Plan 2's stand-in returned (the lock-step's).
Iocs_VPAGE:
    moveq   #3, d0
    and.w   d1, d0
    move.w  d0, SHIM_VPAGE
    moveq   #0, d0
    rts

; _CRTMOD(d1.w = mode): the screen itself is Plan 3's. The game's only _CRTMOD is XC screen()
; ($15780). It asks for mode 10 (256 x 256, 31 kHz) at start-up, before the snapshot, and for
; mode 16 on the way out ($4D20 in $4CD4: the title's "exit", or a missing file), the one call
; reachable after the resume point. Mode 10 is modelled as x68k_hle does: CRTC R20's low byte
; $10, which the game reads back at $1962. Mode 16 is followed only by _EXIT2, and the shim's
; exit resumes the snapshot (the shadow reloaded): R20 is left as it is. Any other mode is a call
; fault.
    ifnd    IOSH_E80029
    fail    "IOSH_E80029 (CRTC R20 low byte) not in the I/O shadow: _CRTMOD needs it"
    endif
Iocs_CRTMOD:
    cmpi.w  #$0A, d1
    bne.s   .not10
    move.b  #$10, IOSH_E80029
    bra.s   .done
.not10:
    cmpi.w  #$10, d1
    bne     Iocs_Fault
.done:
    moveq   #0, d0
    rts

; _BGTEXTGT(d1 = BG text page, d2 = x, d3 = y): d0 = the cell's word (high word 0). The only
; caller is the game-start background builder ($679C), reading back all of BG text page 1 that
; its loader ($6512) wrote just before through $3536 (to X68000 BG RAM: unmapped space here).
; The page it reads depends only on the files and that code: preinit ran the loader once in the
; stand-in and link.py placed the page at BGTEXT (it equals what the original's IOCS returned,
; tests/x68k/bgtext.lua). Another page, or x/y outside 0-63, is a call fault.
Iocs_BGTEXTGT:
    cmpi.l  #BGTEXT_PAGE, d1
    bne     Iocs_Fault
    cmpi.l  #63, d2
    bhi     Iocs_Fault
    cmpi.l  #63, d3
    bhi     Iocs_Fault
    move.w  d3, d0
    lsl.w   #6, d0
    add.w   d2, d0
    add.w   d0, d0                  ; (y * 64 + x) * 2
    lea     BGTEXT, a0
    move.w  (a0,d0.w), d0
    andi.l  #$FFFF, d0
    rts

; _JOYGET(d1 = port): the joystick byte (see the pad map above). In the demo (USER request 2) P1 is
; never the player's pad: it is the demo's stream (demo.asm Demo_Pad). (The game reads P1 alone.)
; While player 2's context is in the game's globals (two-player, coop.asm Coop_Exchange) port 0 is
; REG_P2CNT: P2's pass reads P2's pad through the game's own reads. Both cases are SHIM_COOP_PAD's
; (one byte test: the demo's bit set by Bios_Resume, P2's by Coop_Exchange).
; Auto-fire (Plan 5 Task 5: CONFIG's AUTO FIRE, the preserved block's KEEP_AUTOFIRE, config.asm), on
; the player's read alone (so never in the demo) and only for the play loop's fire read (strig(1) at
; $70B6, which returns to GAME_ROM + $70BC: the title, CONFIG, KAKUSI and the GAME OVER wait read as
; they are): while the shot button is held -- Neo A, or Neo B with the swap on ($221F2: the game
; swaps the triggers after this read, at $70C6) -- it reads released in every step whose number
; (the game's step counter, $22210) is 7 modulo 8, so the game sees a press edge every 8 steps.
; Its fire logic ($70A0-$72DE) starts a burst on a press edge and runs it 12 steps, a press inside
; a burst queued (several collapse into one): any 12 steps in a row hold an edge, so the bursts run
; back to back, one every 12 steps, the fastest rate tapping gives (plan5-recon.md section 6: any
; period of 2-12 steps gives that rate). A power of two (fix round 1, review M1): a mask, not a
; divide (the held fire read cost 251 cycles a step with `divu #12`), and no odd gap where the
; 16-bit counter wraps. Keyed to the step, not the frame or the call: every read of a step gets the
; same, however many frames the step takes.
GAME_FIRE_READ  EQU GAME_ROM+$70BC  ; the fire read's return address (the strig wrapper's caller)
AUTOFIRE_PERIOD EQU 8               ; a press edge every 8 steps (a power of two: the mask below)
    if (AUTOFIRE_PERIOD&(AUTOFIRE_PERIOD-1))|(AUTOFIRE_PERIOD>12)|(AUTOFIRE_PERIOD<2)
    fail "iocs.asm: AUTOFIRE_PERIOD must be a power of two of 2-12 steps (inside the 12-step burst)"
    endif
Iocs_JOYGET:
    ifd     SHIM_TEST_RETURN
    tst.w   SHIM_TEST_RET
    bne     Test_Return             ; (bios.asm: a test's Bios_Return from the game's code)
    endif
    addq.l  #1, SHIM_JOY_COUNT
    tst.l   d1
    bne.s   .p2
    tst.b   SHIM_COOP_PAD           ; the demo's stream, or player 2's pass (a byte: 4 cycles less
    bne.s   .alt                    ; than the demo's mode compare it replaced)
    move.b  REG_P1CNT, d2           ; the player's pad
.fire:
    tst.b   SHIM_KEEP+KEEP_AUTOFIRE
    beq.s   .read                   ; AUTO FIRE off (the demo's stream, .demo, never comes this way)
    cmpi.l  #GAME_FIRE_READ, 4+56+6(sp) ; above the dispatcher's return address, the 56 bytes it
    bne.s   .read                       ; saved and the trap's SR and PC: the wrapper's caller
    moveq   #4, d3                  ; the shot: Neo A (REG_P1CNT bit 4) ...
    tst.w   GV_SWAP
    beq.s   .shot
    moveq   #5, d3                  ; ... or Neo B with the swap on
.shot:
    btst    d3, d2
    bne.s   .read                   ; not held (active low)
    moveq   #AUTOFIRE_PERIOD-1, d0
    and.w   GV_FRAME, d0            ; the step modulo 8
    subq.w  #AUTOFIRE_PERIOD-1, d0
    bne.s   .read
    bset    d3, d2                  ; read released in this step: a press edge in the next
    bra.s   .read
.alt:
    btst    #COOP_PAD_P2_BIT, SHIM_COOP_PAD
    beq.s   .demo
    move.b  REG_P2CNT, d2           ; player 2's pass (coop.asm): its pad, AUTO FIRE as player 1's
    bra.s   .fire
.demo:
    bsr     Demo_Pad                ; the demo's stream (demo.asm)
    bra.s   .read
.p2:
    cmpi.l  #1, d1
    bne.s   .none
    move.b  REG_P2CNT, d2
    bra.s   .read
.none:
    moveq   #-1, d0                 ; no such port
    rts
.read:
    moveq   #0, d0
    move.b  d2, d0
    ori.b   #$F0, d0                ; stick in bits 0-3, nothing else down
    btst    #4, d2
    bne.s   .nob
    bclr    #5, d0                  ; A -> trigger A
.nob:
    btst    #5, d2
    bne.s   .done
    bclr    #6, d0                  ; B -> trigger B
.done:
    rts

; _B_SUPER(a1): a1 = 0 enters supervisor mode (returns the old SSP, or -1 if already there),
; anything else goes back to user mode. The CPU stays in supervisor mode throughout (one
; stack, as on the X68000 where both keep the C stack): the mode is virtual (x68k_hle).
; The game's V-blank wait $1F92 (the title, CONFIG, KAKUSI and GAME OVER loops: one pass a
; frame) begins with _B_SUPER(0): there it is also a game step for the busy model (SE_TICK).
GAME_VWAIT_TRAP EQU GAME_ROM+$1F98  ; $1F92's first trap #15 returns here (the text at GAME_ROM)
Iocs_B_SUPER:
    move.l  a1, d0
    bne.s   .user
    cmpi.l  #GAME_VWAIT_TRAP, 4+56+2(sp)    ; the trap's stacked PC, above the dispatcher's
    bne.s   .enter                          ; return address and the 56 bytes it saved
    SE_TICK
.enter:
    tst.w   SHIM_SUPER
    bne.s   .already
    move.w  #1, SHIM_SUPER
    move.l  #SSP_VALUE, d0
    rts
.already:
    moveq   #-1, d0
    rts
.user:
    clr.w   SHIM_SUPER
    moveq   #0, d0
    rts

; _ADPCMSNS: 2 while the busy model holds game steps (SHIM_SE_BUSY: the effect channel plays, in
; the original's time), else 0 (the original's two answers; se_play tests only for zero).
; (_ADPCMOUT and _ADPCMMOD: Iocs_Snd, above.)
Iocs_ADPCMSNS:
    moveq   #0, d0
    tst.w   SHIM_SE_BUSY
    beq.s   .idle
    moveq   #2, d0
.idle:
    rts
