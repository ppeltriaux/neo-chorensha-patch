; ==============================================================================
; XSP: the 16 C entries of the game's (modified) XSP 1.99, reached through link.py's jump
; table. Arguments are on the stack as XC pushes them (one long each: shorts in the low
; word). Each returns what XSP returns (XSP199.MAN, XSPsys.s, the game's own xsp_set at $0);
; only d0 changes, and d1-d2/a0-a2 where XSP itself changes them (XC's scratch registers).
; Here the calls are recorded (shim.inc); sprites.asm draws the sprites:
;   xsp_set, xsp_set_st, xobj_set, xobj_set_st  append to the open sprite list SHIM_SPR_WORK
;     (x >> 6, y >> 6, pt, info, next; xobj entries have pt | SPR_XOBJ), chained by priority.
;     xsp_set(_st) drop an off-screen sprite (x or y >= $4400, 1/64 px) and return 0, else
;     x >> 6 as XSP does. A full list (SPR_MAX, 512) drops the entry, counts it in the list's
;     lost word and leaves d0. d1/d2/a2 are left as Plan 2's shim left them: the game reads one
;     of them after the call (the lock-step differs at step 1759 otherwise).
;   xsp_wpoke         appends (dest, data) to SHIM_WPK_WORK (42 entries, -1 when full)
;   xsp_out           closes the frame: sprites.asm's Spr_Build turns the open list (and the
;                     xsp_wpoke words) into XSP's write buffer SHIM_XSP_W, one of the three
;                     published buffers (shim.inc PB_*); returns the number of entries (XSP
;                     counts the sprites after expanding xobj). As XSP: the buffer being
;                     written is never on display, and moving on to the next one waits while
;                     that one still is (the VBlank moves the display on, sprites.asm draws it).
;   xsp_vsync(n)      waits until n VBlanks have passed since the last call, returns how many
;                     did and restarts the count (XSP's vsync_count, VBlank-driven)
;   xsp_pcgdat_set    records; waits 3 VBlanks as XSP does before it changes PCG tables
;   xsp_on/off, xsp_objdat_set, xsp_mask_set, xsp_mode2, xsp_vertical, xsp_divy_set2,
;   xsp_wtrans        record their arguments (void)
; Xsp_Init sets the state the start-up left (link.py's XSPI_* equates).
; ==============================================================================

Xsp_Init:
    ifd     XSPI_xsp_on
    move.w  #XSPI_xsp_on, SHIM_XSP_ON
    endif
    ifd     XSPI_xsp_mode2_mode
    move.w  #XSPI_xsp_mode2_mode, SHIM_XSP_MODE
    endif
    ifd     XSPI_xsp_vertical_flag
    move.w  #XSPI_xsp_vertical_flag, SHIM_XSP_VERT
    endif
    ifd     XSPI_xsp_objdat_set_frm
    move.l  #XSPI_xsp_objdat_set_frm, SHIM_XSP_FRM
    move.l  #XSPI_xsp_objdat_set_ref, SHIM_XSP_REF
    endif
    ifd     XSPI_xsp_pcgdat_set_pcg
    move.l  #XSPI_xsp_pcgdat_set_pcg, SHIM_XSP_PCG
    move.l  #XSPI_xsp_pcgdat_set_alt, SHIM_XSP_ALT
    move.l  #XSPI_xsp_pcgdat_set_size, SHIM_XSP_ALTSZ
    endif
    ifd     XSPI_xsp_mask_set_mask
    move.l  #XSPI_xsp_mask_set_mask, SHIM_XSP_MASK
    endif
    clr.w   SHIM_XSP_W              ; XSP's write buffer 0; its V-DISP interrupt has moved
    move.w  #2, SHIM_XSP_D          ; the display on as far as it goes (W - 1) since xsp_on
    bra     Spr_ListInit

Shim_xsp_on:
    PROF_ON PROF_CALL
    move.w  #1, SHIM_XSP_ON
    PROF_OFF PROF_CALL
    rts

Shim_xsp_off:
    PROF_ON PROF_CALL
    clr.w   SHIM_XSP_ON
    PROF_OFF PROF_CALL
    rts

Shim_xsp_objdat_set:                ; (frm, ref)
    PROF_ON PROF_CALL
    move.l  4(sp), SHIM_XSP_FRM
    move.l  8(sp), SHIM_XSP_REF
    PROF_OFF PROF_CALL
    rts

Shim_xsp_mask_set:                  ; (mask)
    PROF_ON PROF_CALL
    move.l  4(sp), SHIM_XSP_MASK
    PROF_OFF PROF_CALL
    rts

Shim_xsp_mode2:                     ; (mode)
    PROF_ON PROF_CALL
    move.w  6(sp), SHIM_XSP_MODE
    PROF_OFF PROF_CALL
    rts

Shim_xsp_vertical:                  ; (flag)
    PROF_ON PROF_CALL
    move.w  6(sp), SHIM_XSP_VERT
    PROF_OFF PROF_CALL
    rts

Shim_xsp_divy_set2:                 ; (y1, y2, y3)
    PROF_ON PROF_CALL
    move.w  6(sp), SHIM_XSP_DIVY
    move.w  10(sp), SHIM_XSP_DIVY+2
    move.w  14(sp), SHIM_XSP_DIVY+4
    PROF_OFF PROF_CALL
    rts

Shim_xsp_wtrans:                    ; (chain)
    PROF_ON PROF_CALL
    move.l  4(sp), SHIM_XSP_CHAIN
    PROF_OFF PROF_CALL
    rts

; xsp_vsync(n): d0.w = VBlanks since the last call (at least n), -1 if XSP is off
Shim_xsp_vsync:
    PROF_ON PROF_CALL
    tst.w   SHIM_XSP_ON
    bne.s   .on
    move.w  #-1, d0
    PROF_OFF PROF_CALL
    rts
.on:
    move.w  6(sp), d0
.wait:
    cmp.w   SHIM_VSYNC, d0
    ble.s   .done                   ; n <= vsync_count (signed; the VBlank stops it at $7FFF)
    bsr     Shim_WaitVBlank
    bra.s   .wait
.done:
    SE_TICK                         ; a game step for _ADPCMSNS's busy model (shim.inc)
    move.w  sr, -(sp)
    ori.w   #$0700, sr
    moveq   #0, d0
    move.w  SHIM_VSYNC, d0
    clr.w   SHIM_VSYNC
    move.w  (sp)+, sr
    PROF_OFF PROF_CALL
    rts

; xsp_pcgdat_set(pcg, alt, size)
Shim_xsp_pcgdat_set:
    PROF_ON PROF_CALL
    move.l  4(sp), SHIM_XSP_PCG
    move.l  8(sp), SHIM_XSP_ALT
    move.l  12(sp), SHIM_XSP_ALTSZ
    tst.w   SHIM_XSP_ON
    beq.s   .done
    clr.w   SHIM_VSYNC              ; XSP: wait until its VBlank PCG work has run (3 VBlanks)
.wait:
    cmpi.w  #3, SHIM_VSYNC
    bge.s   .over
    bsr     Shim_WaitVBlank
    bra.s   .wait
.over:
    clr.w   SHIM_VSYNC
.done:
    PROF_OFF PROF_CALL
    rts

; xsp_wpoke(dest, data): d0 = dest, or -1 when the frame's 42 entries are used
Shim_xsp_wpoke:
    PROF_ON PROF_CALL
    lea     SHIM_WPK_WORK, a0
    move.w  (a0), d1
    cmpi.w  #WPK_MAX, d1
    bhs.s   .full
    addq.w  #1, (a0)
    move.w  d1, d0                  ; x WPK_SIZE (6)
    add.w   d1, d1
    add.w   d0, d1
    add.w   d1, d1
    lea     2(a0,d1.w), a0
    move.l  4(sp), d0
    move.l  d0, (a0)+
    move.w  10(sp), (a0)
    PROF_OFF PROF_CALL
    rts
.full:
    moveq   #-1, d0
    PROF_OFF PROF_CALL
    rts

; PUT: the entry d0.w x, d1.w y (1/64 px), d2.w pt (| SPR_XOBJ), a2.w INFO appended to the open
; list (a0 = SHIM_SPR_WORK, not full) as (x >> 6, y >> 6, pt, INFO, next) (shim.inc) at
; SHIM_SPR_PTR, chained by priority (Spr_NewRun when its priority differs from the entry
; before's). Out: d0.w = x >> 6, d1/d2/a2 kept, a0 = SHIM_SPR_WORK, a1 = the entry's INFO word
; (the registers Plan 2's append left: the lock-step's; tests/tools/test_xsp_regs.py pins them).
; The condition codes it returns differ from Plan 2's append; no caller reads them: every call
; of xsp_set/xobj_set(_st) sets the flags again before it tests them (test_xsp_regs
; test_callers_ignore_flags, on the original's code).
PUT macro
    movea.l SHIM_SPR_PTR, a1
    addq.w  #1, (a0)
    move.w  d1, -(sp)
    asr.w   #6, d0
    move.w  d0, (a1)+
    asr.w   #6, d1
    move.w  d1, (a1)+
    move.w  d2, (a1)+
    move.w  a2, (a1)+
    clr.w   (a1)                    ; next: the entry after it (a run goes on)
    move.w  a2, d1
    andi.w  #$3F, d1
    add.w   d1, d1
    add.w   d1, d1
    cmp.w   SHIM_SPR_RUN, d1
    beq.s   .\@same
    movem.l d0/d2/a2, -(sp)
    bsr     Spr_NewRun
    movem.l (sp)+, d0/d2/a2
    lea     SHIM_SPR_WORK, a0
.\@same:
    addq.l  #2, a1
    move.l  a1, SHIM_SPR_PTR
    subq.l  #4, a1                  ; the INFO word
    move.w  (sp)+, d1
    endm

; Spr_NewRun: the entry whose next word is at a1 begins a run of priority d1 (x 4): the run
; before it ends (its last entry: next = -1 until a later run of its priority links there), and
; this one is linked after the last run of its priority, or is its first. Uses d0/d2/a0/a2.
Spr_NewRun:
    move.w  SHIM_SPR_RUN, d0        ; the run that ends with the entry before
    move.w  d1, SHIM_SPR_RUN
    cmpi.w  #$10*4, d0
    blt.s   .open                   ; none, or not shown
    lea     -SPR_SIZE(a1), a2       ; its last entry's next word
    move.w  #-1, (a2)
    lea     SHIM_SPR_TAILS, a0
    move.l  a2, (a0,d0.w)
.open:
    cmpi.w  #$10*4, d1
    blt.s   .done                   ; not shown: not chained
    move.l  a1, d2
    subi.l  #SHIM_SPR_WORK+4+SPR_NEXT, d2   ; this entry's offset
    lea     SHIM_SPR_TAILS, a0
    move.l  (a0,d1.w), d0
    beq.s   .first
    movea.l d0, a0
    move.w  d2, (a0)                ; after the last run of its priority
    rts
.first:
    lea     SHIM_SPR_HEADS, a0
    move.w  d2, (a0,d1.w)
.done:
    rts

; Spr_ListInit: the open list empty (Xsp_Init, and xsp_out once it is built). Uses d0-d1/a0.
Spr_ListInit:
    clr.l   SHIM_SPR_WORK
    move.l  #SHIM_SPR_WORK+4, SHIM_SPR_PTR
    move.w  #-4, SHIM_SPR_RUN
    lea     SHIM_SPR_HEADS, a0
    moveq   #-1, d0
    moveq   #64-1, d1
.heads:
    move.l  d0, (a0)+
    dbra    d1, .heads
    moveq   #0, d0
    moveq   #64-1, d1
.tails:
    move.l  d0, (a0)+
    dbra    d1, .tails
    rts

; (xsp_set, xsp_set_st) a sprite off the screen: not set, d0 = 0; the list full: XSP's end mark
Xsp_Off:
    moveq   #0, d0
    PROF_OFF PROF_CALL
    rts
Xsp_Full:
    addq.w  #1, SHIM_SPR_WORK+2     ; XSP's end mark: nothing pushed, d0 left as it was
    PROF_OFF PROF_CALL
    rts

Shim_xsp_set_st:                    ; (st): +0 x, +2 y, +4 pt, +6 info
    PROF_ON PROF_CALL
    cmpi.w  #SPR_MAX, SHIM_SPR_WORK
    bhs.s   Xsp_Full
    movea.l 4(sp), a1
    move.w  (a1), d0
    move.w  2(a1), d1
    cmpi.w  #$4400, d0
    bhs.s   Xsp_Off
    cmpi.w  #$4400, d1
    bhs.s   Xsp_Off
    move.w  4(a1), d2
    andi.w  #$7FFF, d2
    movea.w 6(a1), a2
    bra.s   Xsp_Set

Shim_xsp_set:                       ; (x, y, pt, info)
    PROF_ON PROF_CALL
    cmpi.w  #SPR_MAX, SHIM_SPR_WORK
    bhs.s   Xsp_Full
    move.w  6(sp), d0
    move.w  10(sp), d1
    cmpi.w  #$4400, d0
    bhs.s   Xsp_Off
    cmpi.w  #$4400, d1
    bhs.s   Xsp_Off
    move.w  14(sp), d2
    andi.w  #$7FFF, d2
    movea.w 18(sp), a2
Xsp_Set:
    lea     SHIM_SPR_WORK, a0
    PUT                             ; d0: XSP's return, x in pixels (low word)
    PROF_OFF PROF_CALL
    rts
Shim_xobj_set:                      ; (x, y, pt, info)
    PROF_ON PROF_CALL
    move.w  6(sp), d0
    move.w  10(sp), d1
    move.w  14(sp), d2
    ori.w   #SPR_XOBJ, d2
    movea.w 18(sp), a2
    bra.s   Xobj_Set

Shim_xobj_set_st:                   ; (st)
    PROF_ON PROF_CALL
    movea.l 4(sp), a1
    move.w  (a1), d0
    move.w  2(a1), d1
    move.w  4(a1), d2
    ori.w   #SPR_XOBJ, d2
    movea.w 6(a1), a2
Xobj_Set:                           ; d0 the raw x again (xobj_set's d0)
    lea     SHIM_SPR_WORK, a0
    cmpi.w  #SPR_MAX, (a0)
    bhs.s   .full
    move.w  d0, -(sp)
    PUT
    move.w  (sp)+, d0
    PROF_OFF PROF_CALL
    rts
.full:
    addq.w  #1, 2(a0)               ; lost
    PROF_OFF PROF_CALL
    rts

; xsp_out(): closes the frame's lists; d0.l = entries in it (-1 if XSP is off)
Shim_xsp_out:
    PROF_ON PROF_CALL
    tst.w   SHIM_XSP_ON
    bne.s   .on
    moveq   #-1, d0
    PROF_OFF PROF_CALL
    rts
.on:
    movem.l d1-d7/a0-a6, -(sp)
    PROF_MARK 1
    move.w  SHIM_XSP_W, d0          ; the write buffer: not on display (the VBlank never moves
    mulu    #PB_SIZE, d0            ; the display onto it)
    lea     SHIM_PUB, a6
    adda.l  d0, a6
    bsr     Spr_Build
    PROF_MARK 7
    move.w  SHIM_XSP_W, d1          ; the next buffer to write
    addq.w  #1, d1
    cmpi.w  #3, d1
    blo.s   .ring
    moveq   #0, d1
.ring:
    move.w  sr, -(sp)
    ori.w   #$0700, sr
    cmp.w   SHIM_XSP_D, d1
    bne.s   .free
    move.w  (sp)+, sr               ; still on screen: wait for the VBlank to move on
    bsr     Shim_WaitVBlank
    bra.s   .ring
.free:
    move.w  d1, SHIM_XSP_W          ; the one just built may be shown from the next VBlank
    move.w  (sp)+, sr
    moveq   #0, d0
    move.w  SHIM_SPR_WORK, d0       ; the return value
    move.l  d0, -(sp)
    bsr     Spr_ListInit
    move.l  (sp)+, d0
    clr.w   SHIM_WPK_WORK
    addq.l  #1, SHIM_XSP_OUTS
    PROF_MARK 0
    movem.l (sp)+, d1-d7/a0-a6
    PROF_OFF PROF_CALL
    rts
