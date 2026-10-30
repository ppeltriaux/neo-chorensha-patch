; ==============================================================================
; PALETTES (Plan 3 Task 6): the static colours at the resume, and the original's per-step
; colour ramps shown with the sprite list they belong to (graphics-recon section 2).
;
; Static: palettes.bin (make gfx: tools/mkgfx.py) is the whole palette RAM image -- palette 0
; the text (fix) palette (the X68000 text palette: sprite block 0, colours 1-15 copied from
; block 2 by $6494), 1-15 the sprite colour blocks, PAL_BG1 and PAL_BG0_BASE.. the background's
; merged palettes, palette 255 entry 15 the backdrop (black), every other word black. Pal_Init
; selects bank 0 and copies it in at every resume (PAL_DATA puts it in P-ROM after the game).
;
; Ramps: every play step the game sets 13 palette words through xsp_wpoke ($6AB8: colour 1 of
; sprite blocks 1-11, graphic colours $A1 and $B1), which XSP writes when it shows that step's
; list. Pal_Build (xsp_out, the game's time) turns the palette words among the list's xsp_wpoke
; words (destinations $E82000-$E823FF) into PB_PAL: for every Neo entry the X68000 colour feeds
; (PAL_XMAP / PAL_XLIST in gfx.inc, palette_map's copy) the palette RAM offset and the colour,
; converted as x68k_gfx.neo_colour (dark = !I) by two byte tables, NEO_CHI[w >> 8] |
; NEO_CLO[w & $FF]. Pal_Take (the VBlank: Spr_Upload, right after the background heads, once the
; list is going into VRAM with time enough before the display) writes them. So colours change in
; the VBlank that shows their list: a list the VBlank keeps (a step overran: no new list) or skips
; (too late) keeps its colours too, another phase of the same list (XSP MODE 1) writes nothing,
; and a list without palette words (the title's) leaves palette RAM as it is -- as the X68000's
; palette keeps its last value.
;
; Entry 0 (transparent on the Neo Geo) is never fed: mkgfx refuses a map that would. A ramp at
; $0000 (green at step & 15 = 15, red at (step + 4) & 31 = 31) is $8000 on an entry 1-15: opaque
; black, as the reference's "full" picture draws it (MAME x68000 shows it see-through).
;
; Cost: Pal_Build about 2,500 cycles a play list (3 lines of the game's time); Pal_Take 14 words
; (about 500 cycles: under a line) in the VBlank before the sprite upload (docs/notes/shim.md).
; ==============================================================================

X68K_PAL        EQU $00E82000       ; the X68000 palette: graphic 256 words, then text/sprite 256
X68K_PAL_SIZE   EQU $400

; ------------------------------------------------------------------------------
; Pal_Init (the resume, interrupts masked): palette bank 0, palettes.bin into it. Uses d0-d2/a0-a1.
; ------------------------------------------------------------------------------
Pal_Init:
    move.b  d0, REG_PALBANK0
    lea     PAL_IMAGE, a0
    lea     PALRAM, a1
    move.l  #PALRAM_SIZE, d0
    bra     Shim_Copy

; ------------------------------------------------------------------------------
; Pal_Build (Spr_Build, a6 = the buffer, its PB_WPK filled): PB_PAL from the list's palette
; words, in their order (a word set twice: the later wins, as on the X68000). Keeps every
; register.
; ------------------------------------------------------------------------------
Pal_Build:
    movem.l d0-d4/a0-a6, -(sp)
    lea     PB_PAL(a6), a1
    move.l  a1, -(sp)               ; (the count's place)
    addq.l  #2, a1
    lea     PB_WPK(a6), a0
    lea     NEO_CLO, a2
    lea     NEO_CHI, a3
    lea     PAL_XMAP, a4
    lea     PAL_XLIST, a5
    moveq   #0, d3                  ; entries stored
    move.w  (a0)+, d0
    bra.s   .test
.word:
    move.l  (a0)+, d1               ; dest
    subi.l  #X68K_PAL, d1
    cmpi.l  #X68K_PAL_SIZE, d1
    bhs.s   .skip                   ; not a palette word
    moveq   #0, d4                  ; the Neo Geo colour: NEO_CLO[low byte] | NEO_CHI[high byte]
    move.b  1(a0), d4
    add.w   d4, d4
    move.w  (a2,d4.w), d4
    moveq   #0, d2
    move.b  (a0), d2
    add.w   d2, d2
    or.w    (a3,d2.w), d4
    andi.w  #X68K_PAL_SIZE-2, d1    ; colour index x 2
    move.w  (a4,d1.w), d1
    lea     (a5,d1.w), a6
    move.w  (a6)+, d1               ; the entries it feeds
    bra.s   .etest
.entry:
    cmpi.w  #PAL_MAX, d3
    bhs.s   .skip                   ; PB_PAL full: the rest is not applied
    move.w  (a6)+, (a1)+            ; palette RAM offset
    move.w  d4, (a1)+               ; colour
    addq.w  #1, d3
.etest:
    dbra    d1, .entry
.skip:
    addq.l  #2, a0                  ; (data)
.test:
    dbra    d0, .word
    movea.l (sp)+, a1
    move.w  d3, (a1)
    movem.l (sp)+, d0-d4/a0-a6
    rts

; ------------------------------------------------------------------------------
; Pal_Take (VBlank, Spr_Upload: a new list going into VRAM, a1 = its buffer): its PB_PAL into
; palette RAM. Uses d0/d2/a5/a6.
; ------------------------------------------------------------------------------
Pal_Take:
    lea     PB_PAL(a1), a6
    move.w  (a6)+, d0
    beq.s   .done
    lea     PALRAM, a5
    subq.w  #1, d0
.entry:
    move.w  (a6)+, d2
    move.w  (a6)+, (a5,d2.w)
    dbra    d0, .entry
.done:
    rts

; ------------------------------------------------------------------------------
; PAL_DATA (boot.asm, after game.asm): palettes.bin in P-ROM above the game's pieces.
; ------------------------------------------------------------------------------
PAL_DATA macro
    org     (LINKDATA_END+15)&$FFFFF0
PAL_IMAGE:
    incbin  "palettes.bin"
PAL_IMAGE_END:
    if PAL_IMAGE_END-PAL_IMAGE!=PALRAM_SIZE
    fail "palettes.bin is not a whole palette bank (8 KB)"
    endif
    if PAL_IMAGE_END>$100000
    fail "palettes.bin does not fit in the 1 MB P-ROM"
    endif
    if PAL_MAX<PAL_XMAX*13
    fail "PB_PAL may hold fewer entries than the game's 13 ramp words feed"
    endif
    endm
