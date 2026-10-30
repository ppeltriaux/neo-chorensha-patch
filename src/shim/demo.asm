; ==============================================================================
; THE ATTRACT DEMO (Plan 5 Task 4; docs/notes/plan5-recon.md section 7). The BIOS's USER request 2
; resumes the game in demo mode (bios.asm), from the start-up's snapshot: a demo never restores the
; preserved block (resume.asm), so its settings are the snapshot's (XSP MODE 2, no swap, no muteki),
; its pad is the stream's and never goes through the player's read (iocs.asm Iocs_JOYGET: no
; auto-fire), and the random index ($1F62A) and the fire words ($17C8E-$17C93) are the snapshot's
; (only play writes them; the title never draws a random number).
;   * Its title shows (the title hook draws the cabinet text, title.asm) for DEMO_TITLE_PASSES
;     passes of the title loop; then Demo_Title has the loop choose START as the START button does
;     (title.asm .start: item 0, no stick edge, a trigger edge), so the game leaves the title
;     through $2BE6 -> $2C16 and starts stage 1 as any START does (main $3F42).
;   * From then on (DEMO_PLAY) every _JOYGET read of P1 returns the stream's byte for the game step
;     (GV_FRAME, $22210: cleared at the play loop's entry, +1 at each step's end). The step keys
;     it, not the frame: every read of a step gets the same byte however many frames the step
;     takes, so the game plays the recorded run step for step, as the lock-step replays the
;     original's (docs/notes/lockstep.md). Before the stream's first step and after its last, the
;     pad reads nothing pressed.
;   * The stream past its last step (Demo_Frame, in the VBlank) -> Bios_Return: the sound stopped,
;     the BIOS's next USER (its title, or this demo again). Also back to the BIOS: the title loop
;     running again once the demo's game started (a game over in it), and the backstop (bios.asm
;     SHIM_DEMO_LEFT, BIOS_DEMO_FRAMES after the resume).
;   * A coin: the BIOS ends it (DEMO_END, then SYSTEM_RETURN); START: the title (bios.asm).
; The stream (DEMO_IMAGE) is data/demo.bin, the record frozen (tracked; make records it into
; build/demo: tests/neo/demo_record.lua records the port playing stage 1 with play.lua's weave, in a
; build of this demo with SHIM_DEMO_RECORD defined, where the stream's reads take the pad itself;
; tools/mkdemo.py codes it; make standin fails when the two differ): the steps (word), then runs of
; (count byte 1-255, the REG_P1CNT byte its steps' reads return), a count 0 last (even length).
; ==============================================================================
DEMO_RUNS       EQU DEMO_IMAGE+2    ; the stream's runs, after its steps

; ------------------------------------------------------------------------------
; Demo_Resume (Bios_Resume, either mode): the stream from its first run. The resume's clear left
; SHIM_DEMO_STATE at DEMO_TITLE and SHIM_DEMO_FROM at 0.
; ------------------------------------------------------------------------------
Demo_Resume:
    move.l  #DEMO_RUNS, SHIM_DEMO_RUN
    rts

; ------------------------------------------------------------------------------
; Demo_Title (Title_Hook, a pass of the demo's title loop; d3-d7 the loop's: title.asm): the
; DEMO_TITLE_PASSES-th pass chooses START; the title loop running again after that (the demo's game
; over) ends the demo. Every other register kept.
; ------------------------------------------------------------------------------
Demo_Title:
    tst.w   SHIM_DEMO_STATE
    bne     Bios_Return             ; the title again after its game: the demo is over
    cmpi.w  #DEMO_TITLE_PASSES, SHIM_TITLE_PASS
    blo.s   .out
    move.w  #DEMO_PLAY, SHIM_DEMO_STATE ; the stream feeds the pad from here
    moveq   #0, d4                  ; START (whatever the cursor's item; none drawn at 0 credits)
    moveq   #1, d3                  ; no stick edge: the loop moves no cursor
    moveq   #0, d5
    moveq   #1, d7                  ; a trigger's press edge: the loop chooses item d4
.out:
    rts

; ------------------------------------------------------------------------------
; Demo_Pad (Iocs_JOYGET, P1 in the demo): d2.b = the REG_P1CNT byte this read returns: the stream's
; for the game step while the demo's game runs and the stream lasts, else nothing pressed ($FF).
; The run found is kept (SHIM_DEMO_RUN, SHIM_DEMO_FROM) and the next read walks on from it: a demo
; plays one play loop, whose step only goes up (it is cleared at the loop's entry alone, and the
; title back after a game over ends the demo: Demo_Title). d3-d4/a0 used.
; ------------------------------------------------------------------------------
Demo_Pad:
    moveq   #-1, d2
    cmpi.w  #DEMO_PLAY, SHIM_DEMO_STATE
    bne.s   .out
    move.w  GV_FRAME, d3            ; the game step
    cmp.w   DEMO_IMAGE, d3
    bhs.s   .out                    ; past the stream's last step
    ifd     SHIM_DEMO_RECORD
    move.b  REG_P1CNT, d2           ; the recording build: the pad itself (demo_record.lua)
    else
    movea.l SHIM_DEMO_RUN, a0
    move.w  SHIM_DEMO_FROM, d4      ; the step the run begins at
.find:
    moveq   #0, d2
    move.b  (a0), d2                ; the run's steps
    beq.s   .idle                   ; (the stream's end: its steps word is past every run's)
    add.w   d4, d2                  ; the step after the run
    cmp.w   d2, d3
    blo.s   .found
    move.w  d2, d4
    addq.l  #2, a0
    bra.s   .find
.found:
    move.l  a0, SHIM_DEMO_RUN
    move.w  d4, SHIM_DEMO_FROM
    move.b  1(a0), d2
    rts
.idle:
    moveq   #-1, d2
    endif
.out:
    rts

; ------------------------------------------------------------------------------
; Demo_Frame (Bios_Frame, the demo's VBlank, after SYSTEM_IO): its game past the stream's last step
; -> Bios_Return. d0 used (the VBlank's own).
; ------------------------------------------------------------------------------
Demo_Frame:
    cmpi.w  #DEMO_PLAY, SHIM_DEMO_STATE
    bne.s   .out
    move.w  GV_FRAME, d0
    cmp.w   DEMO_IMAGE, d0
    bhs     Bios_Return             ; the stream played out
.out:
    rts

; ------------------------------------------------------------------------------
; DEMO_DATA (boot.asm, right after PAL_DATA): the stream in P-ROM above the palettes. The recording
; build (SHIM_DEMO_RECORD) has no stream yet: DEMO_STEPS steps whose reads take the pad, no run.
; ------------------------------------------------------------------------------
DEMO_DATA macro
DEMO_IMAGE:
    ifd     SHIM_DEMO_RECORD
    dc.w    DEMO_STEPS
    dc.b    0, 0
    else
    incbin  "demo.bin"
    endif
DEMO_IMAGE_END:
    if (DEMO_IMAGE&1)|((DEMO_IMAGE_END-DEMO_IMAGE)&1)
    fail "demo.bin: the stream must start and end on a word"
    endif
    if DEMO_IMAGE_END>$100000
    fail "demo.bin does not fit in the 1 MB P-ROM"
    endif
    endm
