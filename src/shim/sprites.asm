; ==============================================================================
; SPRITES: the XSP list drawn with Neo Geo sprites (Plan 3 Task 4).
;
; The game hands XSP its sprites through xsp_set / xobj_set (xsp.asm records them in the open
; list SHIM_SPR_WORK, an xobj unexpanded) and closes each frame with xsp_out. As XSP does, the
; work is split in two:
;   xsp_out (the game's time): Spr_Build turns the open list into one of XSP's three published
;     buffers (shim.inc, PB_*), ready for the VBlank: every sprite's SCB words, in drawing order.
;   the VBlank: Spr_Upload writes the buffer on display (SHIM_XSP_D) into VRAM, before
;     Text_Flush, and only when it changed (the title's last list stays as it is).
;
; Spr_Build, for one list (graphics-recon section 1.1 and 10):
;  1. Order. The entries come chained by priority (INFO & $3F, the game's XSP buckets; below
;     $10 not shown; xsp.asm chains them as they are set), walked highest first, equal
;     priorities in set order -- the front-most first. An xobj is expanded where it stands (its
;     pieces share its priority and follow each other): REF entry (num.w, index.l) -> num FRM
;     pieces (vx.w, vy.w, rv.w, pt.w) from frm + index; from its x and y (pixels: >> 6 when set)
;     per piece x += vx, y += vy (subtracted under the INFO's H / V flip), a piece at x or y >=
;     $110 (unsigned) culled, INFO = rv XOR the xobj's INFO -- the original's xobj_set
;     ($8C-$110).
;  2. XSP MODE (SHIM_XSP_MODE: the game sets it from $221F4 through xsp_mode2, at start-up
;     ($50D8) only; read at every list): MODE 2 shows the first 256 of that order, MODE 3 all of
;     them, MODE 1 the first 384, 128 at a time in turns (step 5). The port runs in MODE
;     2 only: the start-up sets it and, since CONFIG lost its XSP MODE item (2026-10-28, link.py
;     TITLE_CODE), nothing sets another; MODE 1 and 3 stay, reached by the tests alone (the
;     heavy frames' headroom proofs, tests/neo/sprites.lua SP_XSP_MODE).
;  3. The guard, so the hardware's 96 sprites per line never drop one: on every line 32 go to
;     the background chains (sprites 1-32, Task 5) and up to TEXT_SPR_ROW_MAX to the text
;     sprites (text.asm: field rows 14 and 16, lines 112-127 and 128-143); objects get the rest,
;     SPR_LINE_OBJ (64) less the text sprites a row may show (its cells shown now or to be shown
;     by the text model), counted per 8-line band of the screen: a sprite takes a place in each
;     band it touches (2 or 3). Off the Neo Geo's 224 lines a sprite is not drawn and takes
;     nothing. At most SPR_OBJ_MAX (321) are kept (MODE 1: the bands only, since 128 show at
;     a time). Priorities are walked highest first, so the lowest priority goes first: a sprite
;     is only dropped where its bands are full of higher or equal priorities. In a priority
;     the list before dropped some of (Spr_Cut), those get their places first, so
;     while an overflow lasts the dropped take turns, as XSP's flicker does (only a band that
;     priority needs more than twice the places of can drop one in two lists running); the kept
;     stay in set order. (8-line bands, not 16: a 16-line band counts a sprite on 32 lines and
;     drops 6 boss pieces at the bonus stage's peak -- step 27550, MODE 2 and 3 -- that fit.
;     Priority cannot tell debris from boss parts: the game sets BRAWN and FRAGMENT pieces at
;     $34 like enemies and bosses.)
;     PB_AVAIL: per text row, the places the list leaves for text sprites; Spr_Upload copies
;     it to SHIM_SPR_AVAIL when it draws the list, and Text_Flush shows no more on a row than
;     the list in VRAM leaves (text printed after a list was built waits for a list with room:
;     a frame or two). The turns are exact only for a list unchanged (a sprite is known by its
;     number among its priority's candidates).
;  4. The words: tile SPR_TILE_BASE + pt; attribute = palette PAL_SPR_BASE + colour block
;     (INFO bits 11-8) + bit 13 x $20 (player 2's palettes, PAL_P2_BASE + block: two-player Task 8;
;     no attribute of the game's sets bit 13 or 12, the X68000 ignores them), H flip (bit 14) ->
;     bit 0, V flip (bit 15) -> bit 1 (ATTR); SCB3 =
;     (496 - screen y) << 7 | 1 tile, screen y = y - 16 - view; SCB4 = screen x << 7, screen x =
;     x - 16 + 32. Kept sprites fill the arrays from the top: the front-most gets the highest
;     object sprite number (SPR_OBJ_END - 1), the Neo Geo drawing higher numbers in front --
;     higher priority in front, and in one priority the earlier set (the X68000 order).
;  5. PB_IMG: what each VBlank phase draws. MODE 1 over 128 alternates as XSP's SP_TRANS
;     (graphics-recon section 10) by the VBlank count: n <= 256 kept: odd VBlanks the first 128,
;     even ones the first 256 - n and the 129th .. nth; n > 256: odd VBlanks the first 128,
;     count & 3 = 2 the 129th .. 256th, = 0 the first 384 - n after the 128th and the 257th ..
;     nth. Otherwise all of them, every VBlank.
;
; Spr_Upload (VBlank): SCB1 tiles and attributes (address step 64), SCB3 and SCB4 (step 1) of
; the phase's runs to consecutive sprite numbers ending at SPR_OBJ_END - 1; object sprites shown
; before and not now get SCB3 = 0 (hidden). SCB2 (full size) is set once (Sprites_Init).
;
; The background (Plan 3 Task 5, graphics-recon sections 1.3 and 7.1): the X68000's two graphic
; pages -- each a 256 x 512 image the game-start builder $6512 draws, the same every time -- are
; two chains of BG_COLS (16) sprites of BG_ROWS (32) tiles from C-ROM (build/gfx's BG1_TILEMAP,
; BG0_TILEMAP), written once at the resume (Bg_Init): page 1 on sprites 1-16 (behind), page 0 on
; 17-32, the objects and text in front of both (the lower numbers are behind). Each chain's
; head is at x 32 (field x 0), height 32: 512 lines, so it covers every line and wraps at 512 as
; the X68000's scroll does; the other 15 are sticky to it. Per VBlank only the two heads' SCB3
; change (Bg_Heads, Spr_Upload's first VRAM writes): Y such that screen line 0 shows page line
; (scroll + view) mod 512 -- page 0's scroll CRTC R13, page 1's R17, as the xsp_wpoke words of the
; list in VRAM set them (the play loop: -4 x frame and -frame; Spr_Build notes them in PB_BG,
; Bg_Take keeps them when the list goes into VRAM, as the X68000's registers keep their last
; value), the view of that list (its objects' view) -- height 32, or 0 (hidden) while the game's
; _VPAGE has the page off (SHIM_VPAGE: the title, the game-start builder). 32 sprites on every
; line: the guard gives the objects and text the other 64 (SPR_LINE_OBJ).
;
; Costs, measured in MAME (tests/neo/sprites.lua prints them; SHIM_SPR_LINES, SHIM_VBL_LINES,
; SHIM_SPR_BLINES): docs/notes/shim.md, "Sprites" (upload at most 26 lines: 321 sprites, the
; background heads and a new list's colours); per game step, by part: docs/notes/graphics.md,
; "Timing" (make timing, the profile build's PROF_MARK parts).
; ==============================================================================


SPR_ON_MAGIC    EQU $53505254          ; "SPRT"
SHIM_SPR_ON     EQU SHIM_SPR_END       ; long: SPR_ON_MAGIC once Sprites_Init has run
SPR_B_SP        EQU SHIM_SPR_END+4     ; long: Spr_Build's sp during its walk (a stop returns to it)
SPR_B_CAP       EQU SHIM_SPR_END+8     ; word: XSP's cap of the list being built
SPR_B_DROP      EQU SHIM_SPR_END+10    ; word: its guard drops; bit 15: the total was reached
SPR_B_TOTAL     EQU SHIM_SPR_END+12    ; word: the most it keeps (321; MODE 1: SPR_CAP)
SPR_B_BKT       EQU SHIM_SPR_END+14    ; word: the walk's priority (x 4)
SPR_G_A3        EQU SHIM_SPR_END+16    ; long: the arrays' pointer when that priority began
SPR_G_CAP       EQU SHIM_SPR_END+20    ; word: XSP's cap left then (Spr_Cut3, MODE 3 only)
SPR_G_C         EQU SHIM_SPR_END+22    ; word: Spr_Cut's candidate number
SPR_G_PASS      EQU SHIM_SPR_END+24    ; word: Spr_Cut3's walk (1, 2, 3; MODE 3 only)
SPR_G_DROP      EQU SHIM_SPR_END+26    ; word: its drops
SPR_B_FREE      EQU SHIM_SPR_END+28    ; word: the fewest places a band has (Spr_Rooms)
SPR_B_SLOW      EQU SHIM_SPR_END+30    ; word: nonzero once the fast walk has ended (rooms charged)
SPR_B_ANYREC    EQU SHIM_SPR_END+32    ; word: nonzero when the list before recorded drops in some
                                       ; priority (latched at the build's start: Spr_Recorded's
                                       ; quick test; the build's own records come later)
SPR_VARS_END    EQU SHIM_SPR_END+34
    if SPR_VARS_END!=SHIM_SPR_AVAIL
    fail "the sprite state must end at SHIM_SPR_AVAIL (shim.inc SPR_VARS_BYTES)"
    endif
    if SPR_OBJ_END!=TEXT_SPR_FIRST
    fail "the object sprites must end where the text sprites begin"
    endif
    if SPR_OBJ_FIRST!=SPR_BG_FIRST+SPR_BG_COUNT
    fail "the object sprites must begin where the background chains end"
    endif
    if GAME_RAM_END>SHIM_EXT_LO
    fail "the game's RAM objects run into the shim extension ($107000)"
    endif

; the LSPC's line counter (REG_LSPCMODE >> 7) runs $0F8-$1FF; the VBlank interrupt comes at $1F0
; and the first line shown is $110 (measured in MAME: tests/neo/sprites.lua)
LSPC_LINE_SHOWN EQU $110
LSPC_LINE_VBL   EQU $1F0
LSPC_LINES      EQU 264

; ------------------------------------------------------------------------------
; Sprites_Init (the resume, interrupts masked, the shim's state zeroed): the object sprites full
; size, every sprite of the 512 hidden -- SCB3 0: height 0, not sticky (Bg_Init then sets up the
; background chains, Text_Init the text sprites). Nothing else draws on 0 or 381-511, but VRAM
; holds whatever the BIOS or the game before left there (a real board does not zero it, nor does
; a frontend resuming from another game; MAME does): those numbers are the highest, in front of
; everything (review I1; tests/neo/transitions.lua fills SCB3 with junk at every resume and checks
; them all hidden). No drop record. Uses d0-d1/a0.
; ------------------------------------------------------------------------------
SPR_ALL         EQU 512                    ; the LSPC's sprite numbers (SCB3 entries)

Sprites_Init:
    lea     REG_VRAMADDR, a0
    move.w  #1, 4(a0)
    move.w  #VRAM_SCB2+SPR_OBJ_FIRST, (a0)
    move.w  #SPR_OBJ_MAX-1, d0
.scb2:
    move.w  #$0FFF, 2(a0)
    dbra    d0, .scb2
    move.w  #VRAM_SCB3, (a0)
    move.w  #SPR_ALL-1, d0
.scb3:
    move.w  #0, 2(a0)
    dbra    d0, .scb3
    move.w  #SPR_OBJ_END, SHIM_SPR_LOW
    lea     SHIM_PUB+PB_AVAIL, a0   ; the buffers before their first list: nothing on display,
    move.w  #SPR_LINE_OBJ<<8|SPR_LINE_OBJ, d0   ; every place free for the text
    move.w  d0, (a0)
    move.w  d0, PB_SIZE(a0)
    move.w  d0, 2*PB_SIZE(a0)
    move.w  d0, SHIM_SPR_AVAIL      ; nothing in VRAM yet
    lea     SHIM_SPR_PREVSEQ, a0    ; no list has recorded drops (the first list's OUTS is 0)
    moveq   #-1, d0
    moveq   #16-1, d1
.noprev:
    move.l  d0, (a0)+
    dbra    d1, .noprev
    move.l  #SPR_ON_MAGIC, SHIM_SPR_ON
    rts

; ------------------------------------------------------------------------------
; Bg_Init (the resume, interrupts masked, after Sprites_Init): the background chains' tiles,
; full size, the heads at x 32 and hidden (_VPAGE off), the others sticky. Uses d0-d1/a0-a1.
; ------------------------------------------------------------------------------
BG_PAGE1_SPR    EQU SPR_BG_FIRST           ; page 1's chain (behind page 0's)
BG_PAGE0_SPR    EQU SPR_BG_FIRST+16
BG_X            EQU 32                     ; field x 0
CRTC_R13        EQU $00E8001A              ; xsp_wpoke destinations ($4280-$4308): page 0's Y
CRTC_R17        EQU $00E80022              ; ... page 1's Y
    if SPR_BG_COUNT!=32
    fail "the background is two chains of 16 sprites"
    endif

Bg_Init:
    lea     REG_VRAMADDR, a0
    move.w  #1, 4(a0)
    move.w  #VRAM_SCB1+64*BG_PAGE1_SPR, (a0)     ; SCB1: 64 words a sprite, one after the other
    lea     BG1_TILEMAP, a1
    move.w  #16*64-1, d0
.page1:
    move.w  (a1)+, 2(a0)
    dbra    d0, .page1
    lea     BG0_TILEMAP, a1
    move.w  #16*64-1, d0
.page0:
    move.w  (a1)+, 2(a0)
    dbra    d0, .page0
    move.w  #VRAM_SCB2+SPR_BG_FIRST, (a0)
    moveq   #SPR_BG_COUNT-1, d0
.scb2:
    move.w  #$0FFF, 2(a0)
    dbra    d0, .scb2
    move.w  #VRAM_SCB3+SPR_BG_FIRST, (a0)
    moveq   #SPR_BG_COUNT-1, d0
.scb3:
    moveq   #15, d1
    and.w   d0, d1
    cmpi.w  #15, d1                 ; (d0 counts down: 31 and 15 are sprites 1 and 17)
    beq.s   .head
    move.w  #$0040, 2(a0)           ; sticky
    bra.s   .next3
.head:
    move.w  #0, 2(a0)               ; hidden
.next3:
    dbra    d0, .scb3
    move.w  #VRAM_SCB4+SPR_BG_FIRST, (a0)
    moveq   #SPR_BG_COUNT-1, d0
.scb4:
    move.w  #0, 2(a0)
    dbra    d0, .scb4
    move.w  #16, 4(a0)
    move.w  #VRAM_SCB4+BG_PAGE1_SPR, (a0)
    move.w  #BG_X<<7, 2(a0)
    move.w  #BG_X<<7, 2(a0)
    rts

; Bg_Take (VBlank, a list going into VRAM, a1 = its buffer): the graphic scroll it sets (PB_BG)
; and its view, for the background and the text (SHIM_VIEW: view.asm). Bg_Heads (VBlank): the
; chain heads' SCB3 from them and _VPAGE. Both use d0/a5.
Bg_Take:
    btst    #0, PB_BG+1(a1)
    beq.s   .r17
    move.w  PB_BG_R13(a1), SHIM_BG_SCROLL0
.r17:
    btst    #1, PB_BG+1(a1)
    beq.s   .view
    move.w  PB_BG_R17(a1), SHIM_BG_SCROLL1
.view:
    move.w  PB_VIEW(a1), SHIM_BG_VIEW
    move.w  PB_VIEW(a1), SHIM_VIEW  ; the view on the screen: the text's (Text_Flush), Task 7
    rts

; BG_HEAD: d0 = a head's SCB3: Y field 496 - top with top = -(scroll \1 + view) (screen line 0
; shows page line scroll + view), 9 bits (lsl drops the rest); height 32 if bit \2 of _VPAGE
BG_HEAD macro
    move.w  \1, d0
    add.w   SHIM_BG_VIEW, d0
    addi.w  #SPR_Y_BASE, d0
    lsl.w   #7, d0
    btst    #\2, SHIM_VPAGE+1
    beq.s   .\@off
    ori.w   #BG_ROWS, d0
.\@off:
    endm

Bg_Heads:
    lea     REG_VRAMADDR, a5
    move.w  #BG_PAGE0_SPR-BG_PAGE1_SPR, 4(a5)
    move.w  #VRAM_SCB3+BG_PAGE1_SPR, (a5)
    BG_HEAD SHIM_BG_SCROLL1, 1
    move.w  d0, 2(a5)
    BG_HEAD SHIM_BG_SCROLL0, 0
    move.w  d0, 2(a5)
    rts

; ------------------------------------------------------------------------------
; Spr_Line: d0.w = the LSPC's line counter now. Spr_Lines: d0.w = lines since the counter value
; d0 held (the counter wraps from $1FF to $0F8). Spr_Late: Z clear when the counter is on a line
; shown (the display has begun). All keep the other registers.
; ------------------------------------------------------------------------------
Spr_Line:
    move.w  REG_LSPCMODE, d0
    lsr.w   #7, d0
    rts

Spr_Lines:
    move.w  d1, -(sp)
    move.w  d0, d1
    bsr.s   Spr_Line
    sub.w   d1, d0
    bpl.s   .pos
    addi.w  #LSPC_LINES, d0
.pos:
    move.w  (sp)+, d1
    rts

Spr_Late:
    move.w  d0, -(sp)
    bsr.s   Spr_Line
    cmpi.w  #LSPC_LINE_SHOWN, d0
    blo.s   .early
    cmpi.w  #LSPC_LINE_VBL, d0
    bhs.s   .early
    move.w  (sp)+, d0
    andi.b  #$FB, ccr               ; Z clear: late
    rts
.early:
    move.w  (sp)+, d0
    ori.b   #$04, ccr               ; Z set
    rts

; ------------------------------------------------------------------------------
; Spr_Build (xsp_out): the open list SHIM_SPR_WORK -> the published buffer at a6. Uses every
; register but sp (the caller keeps what it needs).
;
; The walk goes through the priority chains (xsp.asm: $3F first, each in set order), an xobj's
; pieces where it stands. Registers: d1/d2 x/y (pixels), d3 pt or an xobj's pieces left, d4 INFO
; (an xobj: its attribute word), d5 XSP's cap left, d7 the total left, d0/d6 scratch; a0 the
; xobj's FRM pieces, a1 the entry, a2 SPR_XTAB, a3 the arrays (tile words, from the top down), a4
; the guard's rooms, a5 SPR_YTAB, a6 the view. Each priority is walked once in set order, every
; sprite kept that has a place in its bands and the total, the others dropped and recorded for the
; list after (Spr_Drop, Spr_Record: Plan 3 Task 8; the same as walking it again from its beginning
; in set order, which Task 4 did); a priority that dropped some in the list before goes to Spr_Cut
; at once (those dropped then get their places first). Two copies of the walk:
; "fast" keeps sprites without looking at the bands while fewer are kept than any band holds (d7
; counts down from SPR_B_FREE: no band can fill, nothing is dropped); then Spr_Charge gives the
; kept ones their places and the "slow" walk checks every band (d7: the total left).
; ------------------------------------------------------------------------------

; VIS: the sprite at y d2 on the screen's lines? d0 = (its line + 15) x 4 (SPR_YTAB's index), else
; to \1. Counts it against XSP's cap first (d5; none left: to \2).
VIS macro
    subq.w  #1, d5
    bmi     \2
    move.w  d2, d0
    sub.w   \3, d0                  ; screen line + 16 (\3: the view)
    subq.w  #1, d0
    cmpi.w  #239, d0
    bhs     \1                      ; above or below the 224 lines
    add.w   d0, d0
    add.w   d0, d0
    endm

; GUARD: a place in each band of the sprite at SPR_YTAB index d0 (rooms: places left; a band
; with none goes below 0 and is put back), else to \1. Uses d6.
GUARD macro
    move.w  (a5,d0.w), d6           ; its first band's room (word offset); bit 15: three bands
    bmi.s   .\@three
    subq.w  #1, (a4,d6.w)
    bmi.s   .\@full1
    subq.w  #1, 2(a4,d6.w)
    bpl.s   .\@ok
    addq.w  #1, 2(a4,d6.w)
.\@full1:
    addq.w  #1, (a4,d6.w)
    bra     \1
.\@three:
    andi.w  #$7FFF, d6
    subq.w  #1, (a4,d6.w)
    bmi.s   .\@full1
    subq.w  #1, 2(a4,d6.w)
    bmi.s   .\@full2
    subq.w  #1, 4(a4,d6.w)
    bpl.s   .\@ok
    addq.w  #1, 4(a4,d6.w)
.\@full2:
    addq.w  #1, 2(a4,d6.w)
    bra.s   .\@full1
.\@ok:
    endm

; ATTR: d0 = the SCB1 attribute of INFO \1 (changed): palette = colour block (PAL_SPR_BASE 0),
; + $20 with INFO bit 13 (player 2's: PAL_P2_BASE), V/H flip (bits 15/14) -> bits 1/0
ATTR macro
    move.w  \1, d0
    andi.w  #$2F00, d0
    rol.w   #2, \1
    andi.w  #3, \1
    or.w    \1, d0
    endm

; STORE1: a kept single sprite (pt d3, INFO d4; d0 its SPR_YTAB index). Uses d0/d6.
STORE1 macro
    addq.w  #SPR_TILE_BASE, d3
    move.w  d3, -(a3)
    move.w  2(a5,d0.w), 4*SPR_CAP(a3)
    move.w  d4, d6
    ATTR    d6
    move.w  d0, 2*SPR_CAP(a3)
    move.w  d1, d0
    add.w   d0, d0
    move.w  (a2,d0.w), 6*SPR_CAP(a3)
    endm

; STOREP: a kept piece (a0 = its rv, pt; d4 = the xobj's attribute; d0 its SPR_YTAB index): the
; piece's INFO is rv XOR the xobj's, so its attribute is d4 XOR rv's. Uses d0/d6.
STOREP macro
    move.w  (a0)+, d6               ; rv
    move.w  (a0)+, -(a3)            ; pt
    addq.w  #SPR_TILE_BASE, (a3)
    move.w  2(a5,d0.w), 4*SPR_CAP(a3)
    tst.w   d6
    bne.s   .\@rv
    move.w  d4, 2*SPR_CAP(a3)
.\@x:
    move.w  d1, d0
    add.w   d0, d0
    move.w  (a2,d0.w), 6*SPR_CAP(a3)
    bra.s   .\@done
.\@rv:
    ATTR    d6
    eor.w   d4, d0
    move.w  d0, 2*SPR_CAP(a3)
    bra.s   .\@x
.\@done:
    endm

; PIECE_XY: the next piece of an xobj (a0 at its vx): x, y moved (\1 / \2: add or sub, the
; INFO's flips); culled (x or y >= $110, unsigned): to \3 with a0 at its rv
PIECE_XY macro
    \1.w    (a0)+, d1
    \2.w    (a0)+, d2
    move.w  d1, d0                  ; (both below $100: kept)
    or.w    d2, d0
    cmpi.w  #$100, d0
    blo.s   .\@in
    cmpi.w  #$110, d1
    bhs     \3
    cmpi.w  #$110, d2
    bhs     \3
.\@in:
    endm

; XOBJ_F / XOBJ_S: the pieces of an xobj in the fast / slow walk (a0 = its first FRM piece, d3 =
; pieces - 1, d4 its attribute, d1/d2 its x/y): \1 / \2 add or sub for x / y; \3 a name for the
; pair (the fast one hands a piece over to the slow one when the guard takes over)
XOBJ_F macro
.\@piece:
    PIECE_XY \1, \2, .\@cull
    VIS     .\@cull, .stop, a6
    subq.w  #1, d7
    bmi     \3_guard
    STOREP
    dbra    d3, .\@piece
    bra     .f_next
.\@cull:
    addq.l  #4, a0                  ; rv, pt
    dbra    d3, .\@piece
    bra     .f_next
\3_guard:
    bsr     Spr_Guard
    bra     \3_check
    endm

XOBJ_S macro
.\@piece:
    PIECE_XY \1, \2, .\@cull
    VIS     .\@cull, .stop, a6
\3_check:
    tst.w   d7
    beq.s   .\@drop
    GUARD   .\@drop
    subq.w  #1, d7
    STOREP
    dbra    d3, .\@piece
    bra     .s_next
.\@drop:
    bsr     Spr_Drop                ; no place (or the total kept): dropped
.\@cull:
    addq.l  #4, a0
    dbra    d3, .\@piece
    bra     .s_next
    endm

; XOBJ_START: an xobj entry (d3 = its number | SPR_XOBJ, d4 its INFO): a0 = its FRM pieces,
; d3 = their count - 1 (REF entry num.w, index.l at ref + 8 number, as $A6-$C8), d4 its
; attribute, d6 its INFO (for the flips); none: to \1
XOBJ_START macro
    andi.w  #$7FFF, d3
    lsl.w   #3, d3
    movea.w d3, a0
    adda.l  SHIM_XSP_REF, a0
    move.w  (a0)+, d3
    ble     \1
    subq.w  #1, d3
    movea.l (a0), a0
    adda.l  SHIM_XSP_FRM, a0
    move.w  d4, d6
    ATTR    d4
    exg     d0, d4
    endm

Spr_Build:
    PROF_MARK 2
    COST_START                      ; the cost measurement (test and profile builds)
    move.l  a6, -(sp)
    ; the header
    move.l  SHIM_XSP_OUTS, d0
    addq.l  #1, d0
    move.l  d0, PB_SEQ(a6)          ; this xsp_out's number (xsp.asm counts it after)
    move.w  SHIM_XSP_MODE, d0
    move.w  #SPR_CAP, d5            ; MODE 1: the first 384, 128 at a time ...
    move.w  #SPR_CAP, d7            ; ... (no total: the bands only)
    moveq   #1, d1
    cmpi.w  #1, d0
    beq.s   .mode
    move.w  #SPR_OBJ_MAX, d7
    moveq   #3, d1
    move.w  #$7FFF, d5              ; MODE 3 (and 4): all
    cmpi.w  #3, d0
    beq.s   .mode
    cmpi.w  #4, d0
    beq.s   .mode
    moveq   #2, d1
    move.w  #256, d5                ; MODE 2 (the default): the first 256
.mode:
    move.w  d1, PB_MODE(a6)
    move.w  d5, SPR_B_CAP
    move.w  d7, SPR_B_TOTAL
    clr.w   SPR_B_DROP
    clr.w   SPR_B_SLOW
    clr.w   SPR_G_DROP
    ; the list before recorded drops in some priority? (latched now: this list's own records,
    ; written as its priorities are walked, must not hide the lower priorities' -- fix round 1)
    clr.w   SPR_B_ANYREC
    lea     SHIM_SPR_PREVSEQ, a0
    move.l  SHIM_XSP_OUTS, d0       ; (= this list's PB_SEQ - 1: the list before)
    moveq   #16-1, d1
.anyrec:
    cmp.l   (a0)+, d0
    dbeq    d1, .anyrec
    bne.s   .norec
    move.w  #1, SPR_B_ANYREC
.norec:
    ; the list's xsp_wpoke words, and the graphic scroll they set (the background follows it
    ; once the list is in VRAM)
    clr.w   PB_BG(a6)
    lea     SHIM_WPK_WORK, a0
    lea     PB_WPK(a6), a1
    move.w  (a0)+, d0
    move.w  d0, (a1)+
    bra.s   .gtest
.gscan:
    move.l  (a0)+, d1               ; dest
    move.w  (a0)+, d2               ; data
    move.l  d1, (a1)+
    move.w  d2, (a1)+
    cmpi.l  #CRTC_R13, d1
    bne.s   .g17
    move.w  d2, PB_BG_R13(a6)
    bset    #0, PB_BG+1(a6)
    bra.s   .gtest
.g17:
    cmpi.l  #CRTC_R17, d1
    bne.s   .gtest
    move.w  d2, PB_BG_R17(a6)
    bset    #1, PB_BG+1(a6)
.gtest:
    dbra    d0, .gscan
    ; the list's view (view.asm: a play list's from the ship; the walk and the rooms use it)
    bsr     View_Build
    ; the colours they set (palette.asm: shown with the list)
    bsr     Pal_Build
    ; the guard's rooms (PB_TEXT)
    bsr     Spr_Rooms
    ; the open list's last run ends there
    lea     SHIM_SPR_WORK+4, a2
    move.w  SHIM_SPR_WORK, d0
    beq     .walk
    mulu    #SPR_SIZE, d0
    move.w  #-1, SPR_NEXT-SPR_SIZE(a2,d0.l)
.walk:
    PROF_MARK 3
    lea     SPR_XTAB, a2
    movea.l (sp), a3
    lea     PB_TILE+2*SPR_CAP(a3), a3       ; the arrays, from the top down
    lea     SHIM_SPR_ROOM, a4
    lea     SPR_YTAB, a5
    movea.w SHIM_VIEW_LAST, a6      ; the list's view (View_Build)
    move.l  sp, SPR_B_SP
    move.w  #$3F*4, SPR_B_BKT
    move.w  SPR_B_FREE, d7          ; the fast walk's budget
    bra     .f_bucket
.bucket_f:
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    move.l  a3, SPR_G_A3            ; the priority's first slot (its candidates' numbers)
    bsr     Spr_Recorded
    beq     .f_direct
.f_entry:
    movem.w (a1), d1-d4             ; x, y, pt, INFO
    tst.w   d3
    bmi     .f_xobj
    VIS     .f_next, .stop, a6
    subq.w  #1, d7
    bmi     .f_guard1
    STORE1
.f_next:
    move.w  SPR_NEXT(a1), d0
    beq     .f_follow
    bmi     .f_nextbucket
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    bra     .f_entry
.f_follow:
    lea     SPR_SIZE(a1), a1
    bra     .f_entry
.f_nextbucket:
    subq.w  #4, SPR_B_BKT
    cmpi.w  #$10*4, SPR_B_BKT
    blo     .walked
.f_bucket:
    move.w  SPR_B_BKT, d0
    lea     SHIM_SPR_HEADS, a1
    move.w  (a1,d0.w), d0
    bmi     .f_nextbucket
    bra     .bucket_f
.f_guard1:
    bsr     Spr_Guard
    bra     .s_check1
.f_direct:                          ; dropped some in the list before: the slow walk, cut at once
    bsr     Spr_Guard
    bra     .cutnow
.f_xobj:
    XOBJ_START .f_next
    cmpi.w  #$4000, d6              ; the xobj's INFO: its flips
    bhs     .f_x1
    XOBJ_F  add, add, .xaa
.f_x1:
    cmpi.w  #$8000, d6
    bhs     .f_x2
    XOBJ_F  sub, add, .xsa          ; H flip
.f_x2:
    cmpi.w  #$C000, d6
    bhs     .f_x3
    XOBJ_F  add, sub, .xas          ; V flip
.f_x3:
    XOBJ_F  sub, sub, .xss          ; both flips

    ; --- the slow walk: every band checked ---
.s_bucket:
    move.w  SPR_B_BKT, d0
    lea     SHIM_SPR_HEADS, a1
    move.w  (a1,d0.w), d0
    bmi     .s_nextbucket
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    move.l  a3, SPR_G_A3
    bsr     Spr_Recorded
    beq     .cutnow
.s_entry:
    movem.w (a1), d1-d4
    tst.w   d3
    bmi     .s_xobj
    VIS     .s_next, .stop, a6
.s_check1:
    tst.w   d7
    beq     .s_drop1
    GUARD   .s_drop1
    subq.w  #1, d7
    STORE1
.s_next:
    move.w  SPR_NEXT(a1), d0
    beq     .s_follow
    bmi     .s_nextbucket
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    bra     .s_entry
.s_follow:
    lea     SPR_SIZE(a1), a1
    bra     .s_entry
.s_drop1:
    bsr     Spr_Drop                ; no place (or the total kept): dropped
    bra     .s_next
.s_nextbucket:
    tst.w   SPR_G_DROP
    beq.s   .s_more
    bsr     Spr_Record              ; the priority dropped some: their record, for the list after
    clr.w   SPR_G_DROP
    tst.w   d7
    beq     .total                  ; the total is kept: the rest is dropped
.s_more:
    subq.w  #4, SPR_B_BKT
    cmpi.w  #$10*4, SPR_B_BKT
    bhs     .s_bucket
    bra     .walked
.s_xobj:
    XOBJ_START .s_next
    cmpi.w  #$4000, d6
    bhs     .s_x1
    XOBJ_S  add, add, .xaa
.s_x1:
    cmpi.w  #$8000, d6
    bhs     .s_x2
    XOBJ_S  sub, add, .xsa
.s_x2:
    cmpi.w  #$C000, d6
    bhs     .s_x3
    XOBJ_S  add, sub, .xas
.s_x3:
    XOBJ_S  sub, sub, .xss

.cutnow:                            ; the list before dropped some of this priority
    PROF_MARK 5
    bsr     Spr_Cut
    PROF_MARK 4
    clr.w   SPR_G_DROP              ; (recorded by Spr_Cut)
    tst.w   d5
    bmi     .walked                 ; XSP's cap reached in it
    tst.w   d7
    bne     .s_more                 ; on in the slow walk
.total:
    bset    #7, SPR_B_DROP          ; the total is kept: the rest is dropped
    bra     .walked
.stop:                              ; XSP's cap reached: the walk ends here
    movea.l SPR_B_SP, sp
    tst.w   SPR_G_DROP
    beq.s   .walked
    bsr     Spr_Record              ; the priority it ends in dropped some
    clr.w   SPR_G_DROP
.walked:
    PROF_MARK 6
    movea.l (sp)+, a6
    lea     PB_TILE+2*SPR_CAP(a6), a0
    suba.l  a3, a0
    move.l  a0, d0
    lsr.w   #1, d0
    move.w  d0, PB_N(a6)
    move.w  SPR_B_CAP, d1
    tst.w   d5
    bpl.s   .req
    moveq   #0, d5
.req:
    sub.w   d5, d1
    move.w  d1, PB_REQ(a6)          ; sprites XSP's cap let through, as far as the walk went
    move.w  SPR_B_DROP, d1
    move.w  d1, PB_DROP(a6)
    andi.l  #$7FFF, d1
    add.l   d1, SHIM_SPR_DROPS
    bsr     Spr_Avail
    move.w  PB_N(a6), d0
    bsr     Spr_Images
    COST_END SHIM_SPR_BLINES
    ifd     SHIM_COST
    move.w  d0, PB_LINES(a6)
    endif
    rts

; ------------------------------------------------------------------------------
; Spr_Guard: the fast walk ends (it has kept SPR_B_FREE - d7 sprites; d7 below 0: all of them):
; the kept ones take their places in the rooms (none fills: no band holds fewer places than
; SPR_B_FREE), d7 = the total left. Spr_Charge: d1.w kept sprites from a3 take their places.
; Spr_Recorded: Z set when the priority SPR_B_BKT dropped some in the list before (its record in
; SHIM_SPR_PREV is this list's to use). All keep every register but d7 (Spr_Guard).
; ------------------------------------------------------------------------------
Spr_Guard:
    PROF_MARK 4
    move.w  #1, SPR_B_SLOW
    movem.l a0-a1, -(sp)            ; the rooms as before the list's first sprite (Spr_Avail,
    lea     SHIM_SPR_ROOM, a0       ; a cut back to a priority that began fast)
    lea     SHIM_SPR_ROOM0, a1
    rept    SPR_BANDS/2
    move.l  (a0)+, (a1)+
    endr
    movem.l (sp)+, a0-a1
    move.l  d1, -(sp)
    move.w  SPR_B_FREE, d1
    tst.w   d7
    bmi.s   .all
    sub.w   d7, d1
.all:
    bsr.s   Spr_Charge
    move.w  SPR_B_TOTAL, d7
    sub.w   d1, d7
    move.l  (sp)+, d1
    rts

Spr_Charge:
    movem.l d0-d1/d6/a0, -(sp)
    lea     4*SPR_CAP(a3), a0       ; their SCB3 words
    bra.s   .test
.kept:
    move.w  (a0)+, d0               ; (496 - line) << 7 | 1 = -(line + 16) << 7 | 1
    lsr.w   #7, d0
    neg.w   d0
    andi.w  #$1FF, d0               ; line + 16
    subq.w  #1, d0
    add.w   d0, d0
    add.w   d0, d0
    move.w  (a5,d0.w), d6
    bpl.s   .two
    andi.w  #$7FFF, d6
    subq.w  #1, 4(a4,d6.w)
.two:
    subq.w  #1, (a4,d6.w)
    subq.w  #1, 2(a4,d6.w)
.test:
    dbra    d1, .kept
    movem.l (sp)+, d0-d1/d6/a0
    rts

Spr_Recorded:
    tst.w   SPR_B_ANYREC
    bne.s   .some
    andi.b  #$FB, ccr               ; Z clear: none
    rts
.some:
    movem.l d1-d2/a0, -(sp)
    move.w  SPR_B_BKT, d1
    subi.w  #$30*4, d1
    bcs.s   .none
    lea     SHIM_SPR_PREVSEQ, a0
    move.l  SHIM_XSP_OUTS, d2
    cmp.l   (a0,d1.w), d2
    bra.s   .out
.none:
    andi.b  #$FB, ccr               ; Z clear
.out:
    movem.l (sp)+, d1-d2/a0         ; (movem keeps the condition codes)
    rts

;------------------------------------------------------------------------------
; Spr_Drop: the walk drops a candidate of its priority (no place in one of its bands, or the total
; is kept): counted (SPR_G_DROP, SPR_B_DROP) and, in priorities $30-$3F, recorded for the list
; after by its number among the priority's candidates in set order (the kept so far, from
; SPR_G_A3, and the dropped so far) in SHIM_SPR_PREV, which its first drop clears. Spr_Record: the
; priority SPR_B_BKT dropped some: its record is this list's (SHIM_SPR_PREVSEQ). So a
; priority with no record from the list before is walked once in set order, keeping each sprite
; that has a place -- what Spr_Cut's walks give it without a record. Both keep every register.
; ------------------------------------------------------------------------------
Spr_Drop:
    movem.l d0-d1/a0, -(sp)
    move.l  SPR_G_A3, d0
    sub.l   a3, d0
    lsr.w   #1, d0                  ; kept so far in the priority
    add.w   SPR_G_DROP, d0          ; its number
    addq.w  #1, SPR_B_DROP
    addq.w  #1, SPR_G_DROP
    move.w  SPR_B_BKT, d1
    subi.w  #$30*4, d1
    bcs.s   .done                   ; no record below $30
    lsl.w   #5, d1                  ; x 128 / 4
    lea     SHIM_SPR_PREV, a0
    adda.w  d1, a0
    cmpi.w  #1, SPR_G_DROP
    bne.s   .set
    moveq   #32-1, d1               ; the priority's first drop: its record empty
.clear:
    clr.l   (a0)+
    dbra    d1, .clear
    lea     -128(a0), a0
.set:
    cmpi.w  #SPR_CAND_MAX, d0
    bhs.s   .done
    move.w  d0, d1
    lsr.w   #3, d1
    bset    d0, (a0,d1.w)
.done:
    movem.l (sp)+, d0-d1/a0
    rts

Spr_Record:
    movem.l d0-d1/a0, -(sp)
    move.w  SPR_B_BKT, d0
    subi.w  #$30*4, d0
    bcs.s   .done
    lea     SHIM_SPR_PREVSEQ, a0
    move.l  SHIM_XSP_OUTS, d1
    addq.l  #1, d1                  ; this list's PB_SEQ
    move.l  d1, (a0,d0.w)
.done:
    movem.l (sp)+, d0-d1/a0
    rts

; ------------------------------------------------------------------------------
; Spr_Cut: the priority SPR_B_BKT (x 4) the list before dropped some of (its record), as it
; begins (d5 XSP's cap left, d7 the total left, a3 and SPR_G_A3 the arrays, the rooms). Its
; candidates -- sprites on the screen's lines within XSP's cap -- are numbered c in set order.
; Walk 1 (Spr_PWalk) stores every candidate's words in the next slot of the arrays (c's at
; SPR_G_A3 - 2 - 2c: XSP's cap leaves room for all of them, MODE 1 and 2); walk 2 tries those the
; record holds, in set order (a place in every band, the total; each band found again from the
; slot's SCB3 word); walk 3 tries the others in set order and packs the kept in set order (the
; drawing order stays), recording the dropped for the list after. So while an overflow lasts
; the dropped take turns: one dropped now goes first next time (only a band that needs more than
; twice its places can drop one twice in a row). MODE 3 (no cap: the candidates may not fit the
; arrays) walks the priority three times instead (Spr_Cut3, the same result). Out: d5, d7, a3 and
; the rooms as after the priority; SPR_B_DROP counts its drops. Keeps a2 and a4-a6.
; ------------------------------------------------------------------------------
; SCB3_IDX: d0 = a slot's SCB3 word ((496 - line) << 7 | 1) -> its SPR_YTAB index (Spr_Charge's)
SCB3_IDX macro
    lsr.w   #7, d0
    neg.w   d0
    andi.w  #$1FF, d0
    subq.w  #1, d0
    add.w   d0, d0
    add.w   d0, d0
    endm

    if SPR_CAP>SPR_CAND_MAX
    fail "Spr_Cut: a candidate past the bitmaps"
    endif
Spr_Cut:
    cmpi.w  #SPR_CAP, SPR_B_CAP
    bhi     Spr_Cut3                ; MODE 3: the three walks
    move.l  a6, -(sp)
    lea     SHIM_SPR_GWORK+128, a6  ; kept bits at -128, dropped-before bits at 0
    lea     -128(a6), a0
    moveq   #0, d0
    moveq   #64-1, d1
.clear:
    move.l  d0, (a0)+               ; both bitmaps empty
    dbra    d1, .clear
    move.w  SPR_B_BKT, d0
    subi.w  #$30*4, d0
    bcs.s   .walk1                  ; no record below $30: set order alone
    lea     SHIM_SPR_PREVSEQ, a0
    move.l  SHIM_XSP_OUTS, d1       ; (= this list's PB_SEQ - 1: the list before)
    cmp.l   (a0,d0.w), d1
    bne.s   .walk1                  ; not written by the list before: none first
    lsl.w   #5, d0                  ; x 128 / 4
    lea     SHIM_SPR_PREV, a0
    adda.w  d0, a0
    movea.l a6, a1
    moveq   #32-1, d1
.copy:
    move.l  (a0)+, (a1)+
    dbra    d1, .copy
.walk1:
    bsr     Spr_PWalk               ; every candidate's words in its slot (no place taken yet)
    move.w  SPR_G_C, d3
    ; walk 2: those the list before dropped, in set order: a place in each band and the total
    movea.l SPR_G_A3, a1
    lea     4*SPR_CAP(a1), a1       ; the slots' SCB3 words: candidate c's at -2 - 2c
    moveq   #0, d2                  ; c
    bra     .t2
.w2:
    tst.w   d7
    beq.s   .w3                     ; the total is kept
    move.w  d2, d1
    lsr.w   #3, d1
    btst    d2, (a6,d1.w)
    beq.s   .n2
    move.w  d2, d0
    add.w   d0, d0
    neg.w   d0
    move.w  -2(a1,d0.w), d0
    SCB3_IDX
    GUARD   .n2
    subq.w  #1, d7
    bset    d2, -128(a6,d1.w)       ; kept
.n2:
    addq.w  #1, d2
.t2:
    cmp.w   d3, d2
    blo     .w2
.w3:
    ; walk 3, in set order: the others a place in each band and the total; the kept packed (the
    ; drawing order stays), the dropped recorded in place of the record read (each bit read first)
    movea.l SPR_G_A3, a0            ; candidate c's slot (going down)
    movea.l a0, a1                  ; the next kept one's
    moveq   #0, d2                  ; c
    clr.w   SPR_G_DROP
    bra     .t3
.c3:
    subq.l  #2, a0
    move.w  d2, d1
    lsr.w   #3, d1
    btst    d2, (a6,d1.w)
    bne.s   .tried                  ; tried in walk 2
    tst.w   d7
    beq.s   .drop                   ; the total is kept
    move.w  4*SPR_CAP(a0), d0
    SCB3_IDX
    GUARD   .drop
    subq.w  #1, d7
    bra.s   .keep
.tried:
    btst    d2, -128(a6,d1.w)
    beq.s   .drop
.keep:
    bclr    d2, (a6,d1.w)
    subq.l  #2, a1
    cmpa.l  a0, a1
    beq.s   .n3                     ; in its place
    move.w  (a0), (a1)
    move.w  2*SPR_CAP(a0), 2*SPR_CAP(a1)
    move.w  4*SPR_CAP(a0), 4*SPR_CAP(a1)
    move.w  6*SPR_CAP(a0), 6*SPR_CAP(a1)
    bra.s   .n3
.drop:
    bset    d2, (a6,d1.w)           ; dropped: first next time
    addq.w  #1, SPR_G_DROP
.n3:
    addq.w  #1, d2
.t3:
    cmp.w   d3, d2
    blo     .c3
    movea.l a1, a3
    ; the record's bits past the candidates: cleared
    move.w  d3, d1
    lsr.w   #3, d1
    moveq   #7, d0
    and.w   d3, d0
    moveq   #1, d2
    lsl.b   d0, d2
    subq.b  #1, d2
    and.b   d2, (a6,d1.w)
    bra.s   .ct
.cb:
    clr.b   (a6,d1.w)
.ct:
    addq.w  #1, d1
    cmpi.w  #128, d1
    blo.s   .cb
    move.w  SPR_G_DROP, d0
    add.w   d0, SPR_B_DROP
    bra     Cut_Record              ; the record, for the list after (Spr_Cut3's)

; CANDP: candidate SPR_G_C of Spr_PWalk (d0 its SPR_YTAB index): its words in its slot (\1:
; STORE1 or STOREP). Uses d0/d6.
CANDP macro
    addq.w  #1, SPR_G_C
    \1
    endm

; XOBJ_P: an xobj's pieces in Spr_PWalk (as XOBJ_S)
XOBJ_P macro
.\@piece:
    PIECE_XY \1, \2, .\@cull
    VIS     .\@cull, .end, SHIM_VIEW_LAST
    CANDP   STOREP
    dbra    d3, .\@piece
    bra     .next
.\@cull:
    addq.l  #4, a0
    dbra    d3, .\@piece
    bra     .next
    endm

; Spr_PWalk: walk 1 of Spr_Cut: the priority SPR_B_BKT from d5 of XSP's cap (d5 out: what is
; left); SPR_G_C: its candidates, each stored at -(a3) (SPR_G_A3 - 2 - 2c)
Spr_PWalk:
    clr.w   SPR_G_C
    move.w  SPR_B_BKT, d0
    lea     SHIM_SPR_HEADS, a1
    move.w  (a1,d0.w), d0
    bmi     .end
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
.entry:
    movem.w (a1), d1-d4
    tst.w   d3
    bmi     .xobj
    VIS     .next, .end, SHIM_VIEW_LAST
    CANDP   STORE1
.next:
    move.w  SPR_NEXT(a1), d0
    beq.s   .follow
    bmi     .end
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    bra     .entry
.follow:
    lea     SPR_SIZE(a1), a1
    bra     .entry
.xobj:
    XOBJ_START .next
    cmpi.w  #$4000, d6
    bhs     .x1
    XOBJ_P  add, add
.x1:
    cmpi.w  #$8000, d6
    bhs     .x2
    XOBJ_P  sub, add
.x2:
    cmpi.w  #$C000, d6
    bhs     .x3
    XOBJ_P  add, sub
.x3:
    XOBJ_P  sub, sub
.end:
    rts

; ------------------------------------------------------------------------------
; Spr_Cut3: Spr_Cut in MODE 3: the priority SPR_B_BKT (x 4) as it began (d5 XSP's cap left, d7 the total left, a3,
; the rooms), when keeping all of it in set order would drop one. Its candidates -- sprites on
; the screen's lines within XSP's cap -- are numbered c in set order. Walk 1 tries those the
; list before dropped (SHIM_SPR_PREV of priorities $30-$3F, if written by that list), walk 2 the
; others, each in set order, a place in every band and the total, and marks the kept; walk 3
; stores the kept ones in set order (the drawing order stays) and records the dropped, for the
; next list. So while an overflow lasts the sprites dropped take turns: one dropped now goes
; first next time (only a band that needs more than twice its places can drop one twice in a
; row). Out: d5, d7, a3 and the rooms as after the priority; SPR_B_DROP counts its drops. Keeps
; a2 and a4-a6.
; ------------------------------------------------------------------------------
Spr_Cut3:
    move.l  a6, -(sp)
    move.w  d5, SPR_G_CAP
    lea     SHIM_SPR_GWORK+128, a6  ; kept bits at -128, dropped-before bits at 0
    lea     -128(a6), a0
    moveq   #0, d0
    moveq   #64-1, d1
.clear:
    move.l  d0, (a0)+               ; both bitmaps empty
    dbra    d1, .clear
    move.w  SPR_B_BKT, d0
    subi.w  #$30*4, d0
    bcs.s   .walk1                  ; no record below $30: set order alone
    lea     SHIM_SPR_PREVSEQ, a0
    move.l  SHIM_XSP_OUTS, d1       ; (= this list's PB_SEQ - 1: the list before)
    cmp.l   (a0,d0.w), d1
    bne.s   .walk1                  ; not written by the list before: none first
    lsl.w   #5, d0                  ; x 128 / 4
    lea     SHIM_SPR_PREV, a0
    adda.w  d0, a0
    movea.l a6, a1
    moveq   #32-1, d1
.copy:
    move.l  (a0)+, (a1)+
    dbra    d1, .copy
.walk1:
    move.w  #1, SPR_G_PASS          ; numbers the candidates, tries those dropped before
    bsr     Spr_GWalk
    bsr     Spr_GRest               ; tries the others
    movea.l a6, a0                  ; the drops, written by walk 3
    moveq   #0, d0
    moveq   #32-1, d1
.clear2:
    move.l  d0, (a0)+
    dbra    d1, .clear2
    clr.w   SPR_G_DROP
    move.w  #3, SPR_G_PASS
    bsr     Spr_GWalk
    move.w  SPR_G_DROP, d0
    add.w   d0, SPR_B_DROP
; Cut_Record (Spr_Cut, Spr_Cut3; a6 = the drops' bitmap, the caller's a6 on the stack): the
; record, for the list after (none when nothing was dropped)
Cut_Record:
    move.w  SPR_B_BKT, d0
    subi.w  #$30*4, d0
    bcs.s   .done
    lea     SHIM_SPR_PREVSEQ, a0
    moveq   #0, d1
    tst.w   SPR_G_DROP
    beq.s   .stamp
    move.l  SHIM_XSP_OUTS, d1
    addq.l  #1, d1                  ; this list's PB_SEQ
.stamp:
    move.l  d1, (a0,d0.w)
    lsl.w   #5, d0
    lea     SHIM_SPR_PREV, a1
    adda.w  d0, a1
    movea.l a6, a0
    moveq   #32-1, d1
.save:
    move.l  (a0)+, (a1)+
    dbra    d1, .save
.done:
    movea.l (sp)+, a6
    rts

; GVIS: VIS for Spr_GWalk (the list's view, SHIM_VIEW_LAST; XSP's cap: the walk ends)
GVIS macro
    VIS     \1, .end, SHIM_VIEW_LAST
    endm

; XOBJ_G: an xobj's pieces in Spr_GWalk (as XOBJ_S)
XOBJ_G macro
.\@piece:
    PIECE_XY \1, \2, .\@cull
    GVIS    .\@cull
    bsr     Spr_GPiece
    dbra    d3, .\@piece
    bra     .next
.\@cull:
    addq.l  #4, a0
    dbra    d3, .\@piece
    bra     .next
    endm

; Spr_GWalk: one walk of the priority SPR_B_BKT for Spr_Cut (SPR_G_PASS), from SPR_G_CAP of
; XSP's cap (d5 out: what is left). Candidates go to Spr_GSingle / Spr_GPiece.
Spr_GWalk:
    move.w  SPR_G_CAP, d5
    clr.w   SPR_G_C
    move.w  SPR_B_BKT, d0
    lea     SHIM_SPR_HEADS, a1
    move.w  (a1,d0.w), d0
    bmi     .end
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
.entry:
    movem.w (a1), d1-d4
    tst.w   d3
    bmi     .xobj
    GVIS    .next
    bsr     Spr_GSingle
.next:
    move.w  SPR_NEXT(a1), d0
    beq.s   .follow
    bmi     .end
    lea     SHIM_SPR_WORK+4, a1
    adda.w  d0, a1
    bra     .entry
.follow:
    lea     SPR_SIZE(a1), a1
    bra     .entry
.xobj:
    XOBJ_START .next
    cmpi.w  #$4000, d6
    bhs     .x1
    XOBJ_G  add, add
.x1:
    cmpi.w  #$8000, d6
    bhs     .x2
    XOBJ_G  sub, add
.x2:
    cmpi.w  #$C000, d6
    bhs     .x3
    XOBJ_G  add, sub
.x3:
    XOBJ_G  sub, sub
.end:
    rts

; CAND: candidate number SPR_G_C (d0 its SPR_YTAB index) in walk SPR_G_PASS: walks 1 and 2
; try to keep it (walk 1 those dropped before, walk 2 the others: a place in each band, the
; total), walk 3 stores the kept (\1: STORE1 or STOREP) and marks the dropped. Uses d0/d6.
CAND macro
    move.w  SPR_G_C, d6
    addq.w  #1, SPR_G_C
    cmpi.w  #SPR_CAND_MAX, d6
    bhs     .over                   ; past the bitmaps: never kept
    move.w  d0, -(sp)
    cmpi.w  #3, SPR_G_PASS
    beq.s   .w3
    lsr.w   #2, d0                  ; walk 1: its band index, for Spr_GRest
    lea     SHIM_SPR_CIDX, a3
    move.b  d0, (a3,d6.w)
    movea.l SPR_G_A3, a3            ; (walk 1 stores nothing: a3 is the priority's start)
.w3:
    move.w  d6, d0
    lsr.w   #3, d0
    cmpi.w  #2, SPR_G_PASS
    bhi     .walk3
    btst    d6, (a6,d0.w)           ; walk 1: dropped before?
    beq.s   .no
.try:
    move.w  (sp)+, d0
    tst.w   d7
    beq     .done                   ; the total is kept
    GUARD   .done
    subq.w  #1, d7
    move.w  SPR_G_C, d6
    subq.w  #1, d6
    move.w  d6, d0
    lsr.w   #3, d0
    bset    d6, -128(a6,d0.w)       ; kept
    bra     .done
.no:
    addq.l  #2, sp
    bra     .done
.walk3:
    btst    d6, -128(a6,d0.w)
    bne.s   .keep
    bset    d6, (a6,d0.w)           ; dropped: first next time
    addq.l  #2, sp
    addq.w  #1, SPR_G_DROP
    bra     .done
.over:
    cmpi.w  #3, SPR_G_PASS
    bne     .done
    addq.w  #1, SPR_G_DROP
    bra     .done
.keep:
    move.w  (sp)+, d0
    \1
    endm

Spr_GSingle:
    CAND    STORE1
.done:
    rts

Spr_GPiece:
    CAND    STOREP
    rts                             ; (STOREP took rv, pt)
.done:
    addq.l  #4, a0                  ; rv, pt
    rts

; Spr_GRest: walk 2 of Spr_Cut without a walk: the candidates walk 1 numbered (SPR_G_C of them,
; their band indices in SHIM_SPR_CIDX) not dropped before, in set order: a place in each band,
; the total; kept: marked
Spr_GRest:
    move.w  SPR_G_C, d3
    cmpi.w  #SPR_CAND_MAX, d3
    bls.s   .n
    move.w  #SPR_CAND_MAX, d3
.n:
    moveq   #0, d2                  ; c
    lea     SHIM_SPR_CIDX, a1
    bra.s   .test
.c:
    tst.w   d7
    beq.s   .end                    ; the total is kept
    move.w  d2, d1
    lsr.w   #3, d1
    btst    d2, (a6,d1.w)
    bne.s   .next                   ; tried in walk 1
    moveq   #0, d0
    move.b  (a1,d2.w), d0
    add.w   d0, d0
    add.w   d0, d0
    GUARD   .next
    subq.w  #1, d7
    bset    d2, -128(a6,d1.w)       ; kept
.next:
    addq.w  #1, d2
.test:
    cmp.w   d3, d2
    blo.s   .c
.end:
    rts

; ------------------------------------------------------------------------------
; Spr_Avail: PB_AVAIL of the buffer at a6 (as built): per text row (14: field lines 112-127,
; 16: 128-143, at the list's view) the places left for text sprites: SPR_LINE_OBJ less the most
; objects on one of its bands (the rooms before the list less after). Uses d0-d3/a0-a1.
; ------------------------------------------------------------------------------
Spr_Avail:
    tst.w   SPR_B_SLOW              ; the fast walk never ended (the rooms are not charged):
    bne.s   .charged                ; no band holds more than the sprites kept (all of them
    move.w  #SPR_LINE_OBJ, d0       ; fewer than SPR_B_FREE)
    sub.w   PB_N(a6), d0
    move.b  d0, PB_AVAIL(a6)
    move.b  d0, PB_AVAIL+1(a6)
    rts
.charged:
    lea     SHIM_SPR_ROOM0, a0
    lea     SHIM_SPR_ROOM, a1
    move.w  #TEXT_SPR_LINE_TOP+16, d0
    sub.w   PB_VIEW(a6), d0
    bsr.s   .row
    move.b  d3, PB_AVAIL(a6)
    move.w  #TEXT_SPR_LINE_TOP+16+16, d0
    sub.w   PB_VIEW(a6), d0
    bsr.s   .row
    move.b  d3, PB_AVAIL+1(a6)
    rts
; d0 = the row's first screen line + 16 -> d3 = its places
.row:
    move.w  d0, d1
    addi.w  #15, d1
    lsr.w   #3, d0
    lsr.w   #3, d1
    add.w   d0, d0
    add.w   d1, d1
    move.w  #SPR_LINE_OBJ, d3
.band:
    move.w  (a0,d0.w), d2
    sub.w   (a1,d0.w), d2           ; objects on the band
    neg.w   d2
    addi.w  #SPR_LINE_OBJ, d2
    cmp.w   d2, d3
    bls.s   .most
    move.w  d2, d3
.most:
    addq.w  #2, d0
    cmp.w   d1, d0
    bls.s   .band
    rts

; SPR_XTAB: per x (pixels from the X68000's sprite origin, 0-$10F) the SCB4 word: screen x =
; x - 16 + 32
SPR_XTAB:
XP      set     0
    rept    $110
    dc.w    ((XP+32-16)&$1FF)<<7
XP      set     XP+1
    endr

; SPR_YTAB: per screen line + 15 (0-238: lines -15 to 223), the sprite's first 8-line band (the
; word offset of its room: SHIM_SPR_ROOM has 2 bands above the screen) | $8000 when it touches
; three (not on an 8-line boundary), and its SCB3 word
SPR_YTAB:
YL      set     -15
    rept    239
    dc.w    (((YL+16)>>3)*2)|((((YL+16)&7)!=0)<<15), ((-(YL+16))&$1FF)<<7|1
YL      set     YL+1
    endr

; ------------------------------------------------------------------------------
; Spr_Rooms: the guard's rooms for the list being built (a6 = its buffer: PB_TEXT, SPR_B_FREE),
; at its view (SHIM_VIEW_LAST). Every 8-line
; band of the screen: SPR_LINE_OBJ, less the text sprites of the text row it touches (most of
; the two if both); the 2 bands above and 4 below the screen never fill. A row's text sprites:
; those shown now (SHIM_TEXT_SPR_MASK) or whose cell holds a glyph in the text model (shown
; once Text_Flush draws it; the rule is text.asm's); row 16 all ten during the last ship's
; death (GAME OVER follows with no new list: Task 7). Uses d0-d4/a0-a1.
; ------------------------------------------------------------------------------
Spr_Rooms:
    moveq   #0, d2                  ; row 14's
    moveq   #0, d3                  ; row 16's
    move.l  SHIM_TEXT_SPR_MASK, d1
    bne.s   .cells
    ; none shown: a glyph in the text model? Not while no cell of the two rows holds a character
    ; (SHIM_TEXT_USED, row 14's columns 8-24 and row 16's 11-20: the play screen's usual case)
    lea     SHIM_TEXT_USED+4*8, a0
    moveq   #0, d0
    moveq   #24-8, d4
.used:
    or.l    (a0)+, d0
    dbra    d4, .used
    andi.l  #(1<<14)|(1<<16), d0
    beq.s   .counted
.cells:
    lea     TEXT_SPR_CELLS, a0
    lea     SHIM_TEXT, a1
    moveq   #0, d4                  ; k
.k:
    btst    d4, d1
    bne.s   .shown
    move.w  (a0), d0                ; its cell
    move.b  (a1,d0.w), d0
    ble.s   .next                   ; 0 or $80 and up: no glyph
    cmpi.b  #' ', d0
    beq.s   .next
.shown:
    cmpi.w  #17, d4                 ; k 0-16: row 14, 17-26: row 16
    bhs.s   .r16
    addq.w  #1, d2
    bra.s   .next
.r16:
    addq.w  #1, d3
.next:
    lea     TSC_SIZE(a0), a0
    addq.w  #1, d4
    cmpi.w  #TEXT_SPR_COUNT, d4
    blo.s   .k
.counted:
    ; the last ship's death (a play list, no life left, the death timer running): row 16 keeps its
    ; places for GAME OVER, which the game over loop prints with no new list (the list it shows
    ; is the last one built here: Task 7's static screens); two players, only when no player is
    ; left after it (coop.asm Coop_NoneLeft: P1 out keeps lives 0 and its death timer at $5C)
    tst.w   PB_BG(a6)
    beq.s   .text
    tst.w   GV_LIVES
    bne.s   .text
    tst.w   GV_DEATH_TIMER
    beq.s   .text
    jsr     Coop_NoneLeft
    bne.s   .text
    moveq   #TEXT_SPR_COUNT-17, d3
.text:
    move.b  d2, PB_TEXT(a6)
    move.b  d3, PB_TEXT+1(a6)
    move.w  d2, d0                  ; the fewest places a band has: SPR_LINE_OBJ less the
    cmp.w   d3, d0                  ; larger row's text sprites
    bhs.s   .max
    move.w  d3, d0
.max:
    neg.w   d0
    addi.w  #SPR_LINE_OBJ, d0
    move.w  d0, SPR_B_FREE
    lea     SHIM_SPR_ROOM, a0
    move.w  #$7FFF, d0
    move.w  d0, (a0)+
    move.w  d0, (a0)+
    moveq   #SPR_BANDS-6-1, d1
.on:
    move.w  #SPR_LINE_OBJ, (a0)+
    dbra    d1, .on
    move.w  d0, (a0)+
    move.w  d0, (a0)+
    move.w  d0, (a0)+
    move.w  d0, (a0)+
    move.w  SHIM_VIEW_LAST, d4      ; the list's view (View_Build)
    move.w  #TEXT_SPR_LINE_TOP+16, d0       ; row 14's first line + 16 on the screen
    sub.w   d4, d0
    move.w  d2, d1
    bsr.s   .row
    move.w  #TEXT_SPR_LINE_TOP+16+16, d0    ; row 16's
    sub.w   d4, d0
    move.w  d3, d1
    bsr.s   .row
    rts
; .row: d0 = the row's first screen line + 16, d1 = its text sprites: each band of its 16 lines
; gets at most SPR_LINE_OBJ - d1 (rows lie inside the screen: field lines 112-143, view 0-32)
.row:
    tst.w   d1
    beq.s   .rdone
    neg.w   d1
    addi.w  #SPR_LINE_OBJ, d1
    move.w  d0, d2
    addi.w  #15, d2
    lsr.w   #3, d0
    lsr.w   #3, d2
    add.w   d0, d0
    add.w   d2, d2
    lea     SHIM_SPR_ROOM, a1
.rb:
    cmp.w   (a1,d0.w), d1
    bhs.s   .keep
    move.w  d1, (a1,d0.w)
.keep:
    addq.w  #2, d0
    cmp.w   d2, d0
    bls.s   .rb
.rdone:
    rts

; ------------------------------------------------------------------------------
; Spr_Images: PB_IMG of the buffer at a6 for d0.w = n sprites kept. The arrays hold the i-th of
; the drawing order (0 = the front-most) at index SPR_CAP - 1 - i: the order's [a, b) is the run
; (SPR_CAP - b, b - a). Uses d0-d4/a0.
; ------------------------------------------------------------------------------
Spr_Images:
    lea     PB_IMG(a6), a0
    cmpi.w  #1, PB_MODE(a6)
    bne     .all
    cmpi.w  #128, d0
    bls     .all
    move.w  #SPR_CAP-128, d1        ; odd VBlanks: the first 128
    move.w  d1, 8(a0)
    move.w  #128, 10(a0)
    clr.l   12(a0)
    move.w  d1, 24(a0)
    move.w  #128, 26(a0)
    clr.l   28(a0)
    cmpi.w  #256, d0
    bhi.s   .over
    ; even VBlanks: [128, n) then [0, 256 - n)
    move.w  #SPR_CAP, d1
    sub.w   d0, d1
    move.w  d1, (a0)
    move.w  d0, d2
    subi.w  #128, d2
    move.w  d2, 2(a0)
    move.w  #256, d3
    sub.w   d0, d3                  ; 256 - n
    move.w  #SPR_CAP, d4
    sub.w   d3, d4
    move.w  d4, 4(a0)
    move.w  d3, 6(a0)
    move.l  (a0), 16(a0)
    move.l  4(a0), 20(a0)
    rts
.over:
    ; & 3 = 0: [256, n) then [128, 512 - n); & 3 = 2: [128, 256)
    move.w  #SPR_CAP, d1
    sub.w   d0, d1
    move.w  d1, (a0)
    move.w  d0, d2
    subi.w  #256, d2
    move.w  d2, 2(a0)
    move.w  #SPR_CAP-512, d3
    add.w   d0, d3                  ; SPR_CAP - (512 - n)
    move.w  d3, 4(a0)
    move.w  #384, d4
    sub.w   d0, d4                  ; (512 - n) - 128
    move.w  d4, 6(a0)
    move.w  #SPR_CAP-256, 16(a0)
    move.w  #128, 18(a0)
    clr.l   20(a0)
    rts
.all:
    move.w  #SPR_CAP, d1
    sub.w   d0, d1
    moveq   #4-1, d2
.phase:
    move.w  d1, (a0)+
    move.w  d0, (a0)+
    clr.l   (a0)+
    dbra    d2, .phase
    rts

; ------------------------------------------------------------------------------
; Spr_Upload (VBlank, before Text_Flush): the buffer on display (SHIM_XSP_D), the image of this
; VBlank's phase, into VRAM unless that is what the last upload drew; first the background
; chains' heads (Bg_Heads: with that list's scroll when it goes in). Keeps every register.
; ------------------------------------------------------------------------------
Spr_Upload:
    cmpi.l  #SPR_ON_MAGIC, SHIM_SPR_ON
    bne     .off
    movem.l d0-d3/a0-a2/a5-a6, -(sp)
    COST_START
    move.w  SHIM_XSP_D, d0
    mulu    #PB_SIZE, d0
    lea     SHIM_PUB, a1
    adda.l  d0, a1
    move.l  SHIM_HEARTBEAT, d3
    moveq   #3, d0
    and.w   d3, d0
    lsl.w   #3, d0
    lea     PB_IMG(a1,d0.w), a2     ; this VBlank's image
    lea     SHIM_SPR_KEY, a0
    move.l  PB_SEQ(a1), d1
    cmp.l   (a0), d1
    bne.s   .new
    move.l  (a2), d0
    cmp.l   4(a0), d0
    bne.s   .new
    move.l  4(a2), d0
    cmp.l   8(a0), d0
    beq     .keep
.new:
    ; time enough before the display? Measured: 321 sprites take 24 lines (13.4 a line; 25 with
    ; the background heads, Bg_Take + Bg_Heads: half a line, inside the margin; 26 with a new
    ; list's colours, Pal_Take before the sprites: about 40 cycles an entry, the game's 14 under
    ; a line); a hidden one 18 cycles (42 a line). Estimate shown * 5 / 64 + hidden / 32 + 3
    ; lines, + colour entries / 16 rounded up for a new list (321 with the game's colours: 29).
    ; A VBlank entered too late (the game masked it) keeps the picture as it is for a frame
    ; rather than tear it (the key stays: the next VBlank draws it, its colours with it;
    ; SHIM_SPR_AVAIL stays the list in VRAM's)
    move.w  2(a2), d0
    add.w   6(a2), d0               ; shown
    move.w  #SPR_OBJ_END, d2
    sub.w   d0, d2                  ; the first sprite number
    sub.w   SHIM_SPR_LOW, d2        ; hidden from now (if positive)
    bpl.s   .hid
    moveq   #0, d2
.hid:
    lsr.w   #5, d2
    mulu    #5, d0
    lsr.w   #6, d0
    add.w   d2, d0
    addq.w  #3, d0
    cmp.l   (a0), d1                ; a new list: its colours first
    beq.s   .est
    move.w  PB_PAL(a1), d2
    addi.w  #15, d2
    lsr.w   #4, d2
    add.w   d2, d0
.est:
    move.w  d0, d2
    bsr     Text_Left
    cmp.w   d2, d0
    blt     .keep                   ; too late: not this VBlank
    move.w  PB_AVAIL(a1), SHIM_SPR_AVAIL    ; the text gate follows the list in VRAM
    bsr     Bg_Take                 ; ... and the background its scroll and view
    bsr     Bg_Heads
    cmp.l   (a0), d1                ; a new list (not another phase of the one in VRAM): its
    beq.s   .colours                ; colours (palette.asm), before the display as the heads
    bsr     Pal_Take
.colours:
    move.l  d1, (a0)+
    move.l  (a2), (a0)+
    move.l  4(a2), (a0)
    move.l  d1, SHIM_SPR_SHOWN
    move.l  d3, SHIM_SPR_HB
    move.w  2(a2), d1
    add.w   6(a2), d1
    neg.w   d1
    addi.w  #SPR_OBJ_END, d1        ; the first sprite number
    lea     REG_VRAMADDR, a5
    lea     2(a5), a6
    move.w  #64, 4(a5)              ; SCB1: 64 words a sprite
    move.w  d1, d2
    lsl.w   #6, d2
    move.w  d2, (a5)
    lea     PB_TILE(a1), a0
    bsr.s   Spr_Runs
    addq.w  #1, d2
    move.w  d2, (a5)
    lea     PB_ATTR(a1), a0
    bsr.s   Spr_Runs
    move.w  #1, 4(a5)
    move.w  #VRAM_SCB3, d2
    add.w   d1, d2
    move.w  d2, (a5)
    lea     PB_SCB3(a1), a0
    bsr.s   Spr_Runs
    move.w  #VRAM_SCB4, d2
    add.w   d1, d2
    move.w  d2, (a5)
    lea     PB_SCB4(a1), a0
    bsr.s   Spr_Runs
    move.w  SHIM_SPR_LOW, d0        ; shown before and not now: hidden
    move.w  d1, SHIM_SPR_LOW
    sub.w   d0, d1
    ble.s   .shown
    addi.w  #VRAM_SCB3, d0
    move.w  d0, (a5)
    moveq   #0, d0
    subq.w  #1, d1
.hide:
    move.w  d0, (a6)
    dbra    d1, .hide
.shown:
    COST_END SHIM_SPR_LINES
    bra.s   .done
.keep:
    ; the list in VRAM stays: its background (_VPAGE may change), but not once the display has
    ; begun (a VBlank entered late: the heads would change below the beam; they are written at
    ; the next VBlank -- review M9, tests/neo/sprites.lua SP_LATE "heads in display")
    bsr     Spr_Late
    bne.s   .same
    bsr     Bg_Heads
.same:
    ifd     SHIM_COST
    addq.l  #2, sp
    endif
.done:
    movem.l (sp)+, d0-d3/a0-a2/a5-a6
.off:
    rts

; Spr_Runs: the image's two runs (a2: start, count, start, count) of the array at a0 to the VRAM
; port at a6. Spr_Copy: d0.w words from a0 to it. Both use d0/d3/a0.
Spr_Runs:
    move.l  a0, -(sp)
    move.w  (a2), d0
    add.w   d0, d0
    adda.w  d0, a0
    move.w  2(a2), d0
    bsr.s   Spr_Copy
    movea.l (sp)+, a0
    move.w  4(a2), d0
    add.w   d0, d0
    adda.w  d0, a0
    move.w  6(a2), d0
Spr_Copy:
    move.w  d0, d3
    lsr.w   #4, d3
    andi.w  #15, d0
    add.w   d0, d0
    neg.w   d0
    jmp     .end(pc,d0.w)
.loop:
    rept    16
    move.w  (a0)+, (a6)
    endr
.end:
    dbra    d3, .loop
    rts
