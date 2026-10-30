; ==============================================================================
; TEXT: the original's text plane on the Neo Geo (Plan 3 Task 3).
;
; The game draws text only through three routines, which link.py sends here (SHIM_ENTRIES):
;   $1618 (x, y, ch)  8x8 character ch at cell (x & $7F, y & $7F)    -> Shim_Text8
;   $173C (x, y, g)   16x16 glyph g at (x & $3F, y & $3F) x 16 px:     -> Shim_Text16
;                     cells (2x, 2y) = 4g, (2x, 2y+1) = 4g+1, (2x+1, 2y) = 4g+2, (2x+1, 2y+1) = 4g+3
;   $1888 ()          clears all of text VRAM                         -> Shim_TextClear
; Each keeps the original's stack arguments and register effects: the same _B_SUPER calls (IOCS
; $81) and the same saved values ($193A, $1942: GV_TEXT_SUPER, GV_TEXT_R21; R21 in the I/O
; shadow), and every register as the original leaves it -- d0-d2/a0-a1 computed as the original
; computes them, the text VRAM addresses included (nothing is written there) -- and the condition
; codes from the same last instructions (each routine ends on the original's own tail).
; tests/tools/test_text_regs.py runs both side by side and compares the registers.
;
; Instead of text VRAM they write the cell model SHIM_TEXT (shim.inc): one byte per 8x8 cell of
; the 32 x 32 field, a dirty bit per cell and a "used" bit per nonzero cell. The VBlank's
; Text_Flush draws at most TEXT_BUDGET dirty cells a frame (the rest wait for the next VBlank)
; where TEXT_PLACE puts them:
;   * HUD cells (score label and digits, lives, bombs) -> fixed places on the fix layer over the
;     field (Presentation Task 2), whatever the view: the score and lives at the original's own
;     place (fix rows 3-4: screen y = field y), the bombs' 16x16 row pinned near the screen's
;     bottom (fix rows 27-28: lines 200-215, 8 lines up from the bottom so a CRT that crops the
;     last 8 shows it: the user's choice, 2026-10-23); player 2's (two-player plan Task 7: its
;     score and lives on field rows 1-2 x + 18, its bombs on the bombs' rows x 16-31; the join
;     prompt in a corner, coop.asm) at the same rule, in the text font (palette 0, colour 0
;     transparent: the original's look, in front of every sprite) -- player 2's corner (rows 1-2
;     from TEXT_P2_COL, the bombs' from 16) in the font's P2 copy (tile + TEXT_P2_FONT: its
;     pixels in palette 0's entries 1 and 5, P2's colours; Task 8), a blank as the font's blank
;     (character 0, a bomb's blank glyph 0-3), so a one-player game's blanks there are as before.
;     The join prompt takes the corner's font: P1's in P1's, P2's in P2's. They never set
;     SHIM_TEXT_FIXON (the moving view never blanks them) and Text_NewRow draws them again after
;     its blank (TEXT_FIXMASK). A bomb place may also take a field cell (once the title's
;     copyright line on fix row 27, then CONFIG's "SHOT=A" and "exit"; no screen puts one there
;     since the 2026-10-28 CONFIG, the precedence stays): SHIM_BOMB_BITS (and SHIM_BOMB_BITS2,
;     player 2's half) keeps which places hold a bomb glyph, and a blank bomb is drawn only
;     over its own glyph, so the field's text there stays whatever order the cells come in. The
;     side strips' fix columns 0-3 and 36-39 hold only the strips (Presentation Task 5: gfx.inc's
;     STRIP_MAP, palettes 10/11 entries 2-15, opaque; Text_Init draws them, nothing else writes
;     those columns), so the fix layer covers the strips whole: no sprite shows there;
;   * stage-card and GAME OVER cells -> the text sprites (TEXT_SPR_FIRST + k), which take the
;     view into account every frame: they stay on their field line, never drifting;
;   * every other cell -> the fix layer at (x + 4, y + 2 - view/8): screens with a fixed view
;     (title, CONFIG: view.asm keeps their view at 0). The title lift (Task 7): the title's
;     content runs to field row 29 (the version row, fix row 31 at view 0: off the 224 lines,
;     while the logo at the top keeps the view at 0), so while field row TEXT_LIFT_ROW holds text
;     (only the title's does) rows TEXT_LIFT_FROM and down draw TEXT_LIFT_ROWS rows higher: the
;     credit lines 27 and 29 on 25 and 27 (fix rows 27 and 29), the order kept, rows 24-26 and 28
;     empty on the title. When view/8 or the lift changes and the field's fix map holds a glyph
;     (SHIM_TEXT_FIXON), that part of the fix map is blanked and the set cells are drawn again
;     (Text_NewRow); with nothing on it only the row the cells are drawn for moves (play: the
;     view moves all the time, the field's fix map is empty).
; Text_Init (the resume) blanks the fix map, draws the side strips and sets up the text sprites
; (hidden).
;
; VBlank cost (SHIM_TEXT_LINES keeps the most raster lines one Text_Flush took, in the test
; builds; measured in MAME, tests/neo/text.lua): about 270 cycles a cell, so TEXT_BUDGET (48)
; cells take about 17 lines; a bomb cell that draws (its bit set or cleared: .bomb) about 400,
; past the 384 of TEXT_CELLS_LINE's 2 a line (about 455 since two-player Task 7: two bit longs),
; but at most TEXT_BOMB_CAP (28) of a flush's 48 cells are bomb cells -- both players' 64 can be
; dirty at once: the rest wait for the next VBlank --, so a flush's cells take at most about 23.6
; lines (28 x 455 + 20 x 270 cycles) of the 24 the cap allows: the 16-bomb wipe on the way to the
; title, 30-31 lines with the setup and the text sprites' pass (tests/neo/text.lua "wipe_16_bombs";
; with a cap of 32, 32 lines; 16: 23; the 8-bomb wipe before Task 7, 29 bomb cells, took 28).
; With nothing on the field's fix map (play) the cells stop TEXT_PLAY_SPARE lines early, so a heavy
; list's VBlank stays within play's 31 (the MODE 3 guard replay: 30), TEXT_PLAY_FLOOR cells at
; least: a HUD cell waits 2 frames at most in the MODE 2 and 3 replays (sprites.lua "hud wait"). A
; view row change with fix text set or
; pending blanks 1,024 fix words instead (about 23 lines; that VBlank draws fewer cells:
; TEXT_BLANK_COST). A score update is 7 cells (3 lines).
; Worst case, a screen change: the clear marks every cell that was set, the new screen prints
; its own -- at most 1,024 cells, drawn over 22 VBlanks at 17 lines each; the real ones are
; smaller: the title after a game over, about 140 cells (the play screen's 62 blanked, the
; title's 74 printed), 3 VBlanks; the first title, 2.
; ==============================================================================

    ifnd    IOSH_E8002A
    fail    "IOSH_E8002A (CRTC R21) not in the I/O shadow: Shim_TextClear keeps it as $1888 does"
    endif
    if TEXT_SPR_FIRST+TEXT_SPR_COUNT-1!=380
    fail    "the text sprites must end at sprite 380"
    endif

TEXT_FIX_WORD   EQU (PAL_TEXT<<12)+FONT_FIX_BASE   ; fix map word of character 0 (+ ch)
TEXT_BOMB_ROW   EQU 30                             ; the bombs' cells: field rows 30-31, cols 0-31
TEXT_BOMB_FIX   EQU 27                             ; (P1's 0-15, P2's 16-31), on fix rows 27-28
TEXT_BOMB_BLANK EQU 4                              ; (TP_OF); characters 0-3: the blank glyph 0
TEXT_P2_COL     EQU 19                             ; player 2's corner: rows 1-2 from this column,
TEXT_P2_FONT    EQU P2_FONT_BASE-FONT_FIX_BASE     ; the bombs' from 16, drawn in P2's font copy
                                                   ; (tile + this: gfx.inc; two-player Task 8)
TEXT_P2_HUD     EQU 1                              ; player 2's HUD cells (field rows 1-2 cols 19-30
                                                   ; and 19-28, the bombs' rows cols 16-31) have
                                                   ; places of their own (two-player Task 7: TP_OF,
                                                   ; checked at TEXT_PLACE): coop.asm's Coop_Text8 /
                                                   ; Coop_Text16 write them (0: none of them)
    if (TEXT_BOMB_ROW&$18)!=((TEXT_BOMB_ROW+1)&$18)
    fail    "the bombs' two rows must share one byte of a dirty long (Text_Flush's .bomb)"
    endif
    if (((62-TEXT_BOMB_FIX)&31)<1)||(((62-TEXT_BOMB_FIX)&31)>8)
    fail    "TEXT_BOMB_FIX: .onbomb's bit offset must fit an addq (1-8)"
    endif
TEXT_LIFT_ROW   EQU 29                             ; the title lift: while this row holds text,
TEXT_LIFT_FROM  EQU 26                             ; rows from this one down draw
TEXT_LIFT_ROWS  EQU 2                              ; this many rows higher
TEXT_LIFT_KEY   EQU $100                           ; (SHIM_TEXT_VROW: the lift's flag)
TEXT_SPR_ATTR   EQU PAL_TEXT<<8                    ; SCB1 attribute: palette, no flip
TVRAM           EQU $E00000                        ; the X68000's text VRAM (4 planes)
TVRAM_PLANE     EQU $20000

; ------------------------------------------------------------------------------
; Shim_Text8(x, y, ch): $1618
; ------------------------------------------------------------------------------
Shim_Text8:
    PROF_ON PROF_CALL
    suba.l  a1, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15                     ; _B_SUPER(0), as $1618
    move.l  d0, GV_TEXT_SUPER
    movem.l d1-d2, -(sp)            ; (d1's high word is the caller's at the end, as in $1618)
    move.w  8+6(sp), d0
    andi.w  #$7F, d0
    move.w  8+10(sp), d1
    andi.w  #$7F, d1
    move.b  8+15(sp), d2
    tst.b   SHIM_COOP_CTX           ; player 2's pass: its HUD's cells (coop.asm Coop_Text8)
    bne     .p2
    bsr     Text_Put
.put:
    movem.l (sp)+, d1-d2
    ; the registers as $1618 leaves them: the font address of the glyph's last plane in a0, the
    ; text VRAM address of its last plane in a1
    move.l  12(sp), d0
    move.w  d0, d1
    lsr.l   #2, d0
    lsl.l   #7, d0                  ; font cell ch >> 2
    andi.w  #3, d1
    lsl.w   #4, d1
    cmpi.w  #$20, d1
    blt.s   .quadrant
    subi.w  #$1F, d1                ; quadrant offset: 0, $10, 1, $11 (TL BL TR BR)
.quadrant:
    movea.l GV_TEXT_FONT, a0
    adda.l  d0, a0
    adda.w  d1, a0
    lea     3*$20(a0), a0           ; planes 1-3 follow at $20 steps
    movea.l #TVRAM+3*TVRAM_PLANE, a1
    move.w  6(sp), d0
    andi.w  #$7F, d0
    adda.w  d0, a1
    move.w  10(sp), d0
    andi.l  #$7F, d0
    swap    d0
    lsr.l   #6, d0                  ; y * 8 lines * 128 bytes
    adda.l  d0, a1
    move.l  GV_TEXT_SUPER, d0       ; back to user mode if _B_SUPER switched (as $172E)
    bmi.s   .done
    movea.l d0, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15
.done:
    PROF_OFF PROF_CALL
    rts
.p2:
    jsr     Coop_Text8
    bra     .put

; ------------------------------------------------------------------------------
; Shim_Text16(x, y, g): $173C
; ------------------------------------------------------------------------------
Shim_Text16:
    PROF_ON PROF_CALL
    suba.l  a1, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15
    move.l  d0, GV_TEXT_SUPER
    movem.l d1-d2, -(sp)
    move.w  8+6(sp), d0
    andi.w  #$3F, d0
    add.w   d0, d0
    move.w  8+10(sp), d1
    andi.w  #$3F, d1
    add.w   d1, d1
    move.b  8+15(sp), d2
    lsl.b   #2, d2                  ; 4g: the top-left quarter
    lea     Text_Put, a1            ; (a1 is set again below)
    tst.b   SHIM_COOP_CTX
    beq.s   .cells
    lea     Coop_Text16, a1         ; player 2's pass: its HUD's cells (coop.asm)
.cells:
    jsr     (a1)
    addq.w  #1, d1
    addq.b  #1, d2
    jsr     (a1)                    ; bottom-left
    addq.w  #1, d0
    subq.w  #1, d1
    addq.b  #1, d2
    jsr     (a1)                    ; top-right
    addq.w  #1, d1
    addq.b  #1, d2
    jsr     (a1)                    ; bottom-right
    movem.l (sp)+, d1-d2
    ; the registers as $173C leaves them (d1 untouched)
    move.l  12(sp), d0
    lsl.l   #7, d0
    movea.l GV_TEXT_FONT, a0
    adda.l  d0, a0
    lea     4*16*2(a0), a0          ; past the cell's 4 planes x 16 words
    movea.l #TVRAM+3*TVRAM_PLANE, a1
    move.w  6(sp), d0
    andi.w  #$3F, d0
    add.w   d0, d0
    adda.w  d0, a1
    move.w  10(sp), d0
    andi.l  #$3F, d0
    swap    d0
    lsr.l   #5, d0                  ; y * 16 lines * 128 bytes
    adda.l  d0, a1
    move.l  GV_TEXT_SUPER, d0
    bmi.s   .done
    movea.l d0, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15
.done:
    PROF_OFF PROF_CALL
    rts

; ------------------------------------------------------------------------------
; Shim_TextClear(): $1888. The original saves CRTC R21, sets simultaneous access to all four
; planes ($1F0), clears with d1-d7/a0-a5 = 0 and restores R21; d3-d7/a3-a6 are restored.
; ------------------------------------------------------------------------------
Shim_TextClear:
    PROF_ON PROF_CALL
    bsr     Keep_Screen             ; a screen change: the preserved block saved (resume.asm)
    tst.b   SHIM_COOP_PROMPT        ; a join prompt showing (coop.asm): none left, and drawn
    beq.s   .noprompt               ; again at the next step's Coop_Pass if still due (its
    clr.b   SHIM_COOP_PROMPT        ; request: Coop_Blink sees none without the cells)
    bset    #COOP_NEW_PROMPT, SHIM_COOP_NEW
.noprompt:
    movem.l d3-d7/a3-a6, -(sp)
    suba.l  a1, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15
    move.l  d0, GV_TEXT_SUPER
    move.w  IOSH_E8002A, GV_TEXT_R21
    move.w  #$01F0, IOSH_E8002A
    move.w  sr, -(sp)               ; the original changes no X flag: keep the caller's
    bsr     Text_Wipe
    move.w  (sp)+, ccr
    moveq   #0, d1
    moveq   #0, d2
    suba.l  a0, a0
    suba.l  a1, a1
    suba.l  a2, a2
    move.w  GV_TEXT_R21, IOSH_E8002A
    move.l  GV_TEXT_SUPER, d0
    bmi.s   .done
    movea.l d0, a1
    moveq   #$81-$100, d0           ; _B_SUPER ($81)
    trap    #15
.done:
    movem.l (sp)+, d3-d7/a3-a6
    PROF_OFF PROF_CALL
    rts

; ------------------------------------------------------------------------------
; Text_Put: cell (d0.w x, d1.w y) = d2.b. Cells past the field's 32 x 32 are not shown and are
; ignored; an unchanged cell is left alone. Keeps every register. The model byte is written
; before the dirty bit (a single bset, as the VBlank sees it), so a VBlank in between only
; draws the cell one frame later. SHIM_TEXT_LIFT counts the cells of row TEXT_LIFT_ROW with a
; character (the used bit's change).
; ------------------------------------------------------------------------------
Text_Put:
    cmpi.w  #TEXT_COLS, d0
    bhs.s   .out
    cmpi.w  #TEXT_ROWS, d1
    bhs.s   .out
    movem.l d0/d3/a0, -(sp)
    move.w  d0, d3
    lsl.w   #5, d3
    add.w   d1, d3                  ; x * 32 + y
    lea     SHIM_TEXT, a0
    cmp.b   (a0,d3.w), d2
    beq.s   .same
    move.b  d2, (a0,d3.w)
    move.w  d1, d3                  ; column x's long, bit y: byte x * 4 + 3 - y / 8, bit y & 7
    lsr.w   #3, d3
    neg.w   d3
    addq.w  #3, d3
    add.w   d0, d0
    add.w   d0, d0
    add.w   d0, d3
    lea     SHIM_TEXT_USED, a0
    tst.b   d2
    beq.s   .unused
    bset    d1, (a0,d3.w)
    bne.s   .dirty                  ; (it held a character already)
    cmpi.w  #TEXT_LIFT_ROW, d1
    bne.s   .dirty
    addq.w  #1, SHIM_TEXT_LIFT      ; the title lift's row: one more cell with text
    bra.s   .dirty
.unused:
    bclr    d1, (a0,d3.w)
    beq.s   .dirty                  ; (it held none)
    cmpi.w  #TEXT_LIFT_ROW, d1
    bne.s   .dirty
    subq.w  #1, SHIM_TEXT_LIFT
.dirty:
    lea     SHIM_TEXT_DIRTY, a0
    bset    d1, (a0,d3.w)
.same:
    movem.l (sp)+, d0/d3/a0
.out:
    rts

; ------------------------------------------------------------------------------
; Text_Wipe: every cell 0. Only the columns with set cells change: their cells become dirty
; (the VBlank blanks what was drawn) after the model is cleared. With a glyph on the field's fix
; map (SHIM_TEXT_FIXON) it also asks the VBlank to blank that whole (SHIM_TEXT_BLANK: Text_Flush).
; Uses d3-d5/a3-a5.
; ------------------------------------------------------------------------------
Text_Wipe:
    tst.w   SHIM_TEXT_FIXON
    beq.s   .model
    move.w  #1, SHIM_TEXT_BLANK     ; glyphs on the field's fix map: the next VBlank blanks it whole
.model:
    lea     SHIM_TEXT, a3
    lea     SHIM_TEXT_USED, a4
    lea     SHIM_TEXT_DIRTY, a5
    clr.w   SHIM_TEXT_LIFT          ; no cell holds a character from here
    moveq   #TEXT_COLS-1, d5
.col:
    move.l  (a4), d3
    beq.s   .next
    moveq   #0, d4
    move.l  d4, (a3)
    move.l  d4, 4(a3)
    move.l  d4, 8(a3)
    move.l  d4, 12(a3)
    move.l  d4, 16(a3)
    move.l  d4, 20(a3)
    move.l  d4, 24(a3)
    move.l  d4, 28(a3)
    or.l    d3, (a5)                ; one instruction: the VBlank sees all of it or none
    clr.l   (a4)
.next:
    lea     TEXT_ROWS(a3), a3
    addq.l  #4, a4
    addq.l  #4, a5
    dbra    d5, .col
    rts

; ------------------------------------------------------------------------------
; Text_Init (the resume, interrupts masked, the text state zeroed): the fix map blank but for the
; side strips (Presentation Task 5), drawn here once -- columns 0-3 and 36-39, rows 2-29 (the 224
; lines) from STRIP_MAP (gfx.inc, mkgfx: the art's tiles in palettes 10/11), those columns' rows
; 0-1 and 30-31 blank; no bomb glyph on it; the text sprites full size, at their cells' X,
; hidden. Nothing else writes the strips' columns (TP_OF: every fixed place in columns 4-35;
; Text_NewRow blanks columns 4-35 only). Once a resume, outside the VBlank: the fix map's 1,280 words.
; Uses d0-d2/a0.
; ------------------------------------------------------------------------------
    if VRAM_FIX_SIZE!=40*32
    fail "the fix map is 40 columns of 32 rows"
    endif
Text_Init:
    move.w  #1, REG_VRAMMOD
    move.w  #VRAM_FIX, REG_VRAMADDR
    lea     STRIP_MAP, a0
    bsr     .strip                  ; columns 0-3: the left strip
    move.w  #32*32-1, d0            ; columns 4-35: the field
    move.w  #TEXT_FIX_WORD, d1
.fix:
    move.w  d1, REG_VRAMRW
    dbra    d0, .fix
    bsr     .strip                  ; columns 36-39: the right strip (a0 at its words)
    move.w  #VRAM_SCB2+TEXT_SPR_FIRST, REG_VRAMADDR
    moveq   #TEXT_SPR_COUNT-1, d0
.scb2:
    move.w  #$0FFF, REG_VRAMRW
    dbra    d0, .scb2
    move.w  #VRAM_SCB3+TEXT_SPR_FIRST, REG_VRAMADDR
    moveq   #TEXT_SPR_COUNT-1, d0
.scb3:
    move.w  #0, REG_VRAMRW
    dbra    d0, .scb3
    move.w  #VRAM_SCB4+TEXT_SPR_FIRST, REG_VRAMADDR
    lea     TEXT_SPR_CELLS+4, a0
    moveq   #TEXT_SPR_COUNT-1, d0
.scb4:
    move.w  (a0), REG_VRAMRW
    lea     TSC_SIZE(a0), a0
    dbra    d0, .scb4
    clr.w   SHIM_TEXT_VROW          ; the view (0 at the resume) / 8, no lift
    clr.w   SHIM_TEXT_SVIEW
    clr.w   SHIM_TEXT_LIFT
    clr.w   SHIM_TEXT_FIXON         ; the field's fix map blank
    clr.l   SHIM_BOMB_BITS          ; no bomb glyph on it
    clr.l   SHIM_BOMB_BITS2
    move.l  #TEXT_ON_MAGIC, SHIM_TEXT_ON
    rts

; the next STRIP_COLS (4) columns from the fix map address set: rows 0-1 blank, rows 2-29 the
; words at a0 (a0 past them), rows 30-31 blank (boot.asm checks gfx.inc's STRIP_* against this)
.strip:
    moveq   #4-1, d2
    move.w  #TEXT_FIX_WORD, d1
.col:
    move.w  d1, REG_VRAMRW          ; rows 0-1: off the screen
    move.w  d1, REG_VRAMRW
    moveq   #28-1, d0
.row:
    move.w  (a0)+, REG_VRAMRW       ; rows 2-29
    dbra    d0, .row
    move.w  d1, REG_VRAMRW          ; rows 30-31: off the screen
    move.w  d1, REG_VRAMRW
    dbra    d2, .col
    rts

; ------------------------------------------------------------------------------
; Text_Flush (VBlank, after the sprite upload): the view's row, at most TEXT_BUDGET dirty cells,
; the text sprites' Y -- all before the display begins (the controller's ruling: the sprites
; first, then the text, done by LSPC_LINE_SHOWN). The view is the one on the screen (SHIM_VIEW:
; the list in VRAM's, view.asm). The lines left then (Text_Left) set what it does: a view row
; or lift change with a glyph on the field's fix map (Text_NewRow's blank, about 23 lines)
; waits for a VBlank with TEXT_NEWROW_LINES left -- until then the field's cells are drawn for
; the row the fix map holds (SHIM_TEXT_VROW), so the other cells (the HUD's fixed places, the
; text sprites') never wait for it; with nothing on the field's fix map (play) only that row
; moves. The cells drawn are at most TEXT_CELLS_LINE a line left (with nothing on the field's
; fix map, less TEXT_PLAY_SPARE: play's VBlank budget, TEXT_PLAY_FLOOR at least), less
; TEXT_PASS_LINES for the text sprites' pass, which is skipped once the display has begun (it
; runs at the next VBlank),
; and of them at most TEXT_BOMB_CAP bomb cells (.bomb).
; Cells not drawn stay dirty. Keeps every register. Runs once Text_Init has (SHIM_TEXT_ON).
; ------------------------------------------------------------------------------
TEXT_NEWROW_LINES EQU 28            ; Text_NewRow's blank (about 23 lines) and some cells
TEXT_CELLS_LINE   EQU 2             ; a cell takes about 270 cycles: 2.8 a line (a drawing
                                    ; bomb cell about 455: 1.7; at most TEXT_BOMB_CAP (28) of
                                    ; 48, so the mix stays within 2 a line: the cost note at
                                    ; the top)
TEXT_PASS_LINES   EQU 3             ; the text sprites' pass (27 sprites)
TEXT_PLAY_SPARE   EQU 40-31         ; whenever nothing is on the field's fix map
                                    ; (SHIM_TEXT_FIXON 0: play, the game over and its wipe, a
                                    ; fresh title until its first glyph is drawn) the cells stop
                                    ; this many lines earlier, so a heavy list's VBlank with the
                                    ; score and the join prompt's blink (10 cells, coop.asm)
                                    ; stays within play's 31 lines of 40; the rest wait --
TEXT_PLAY_FLOOR   EQU 2             ; -- but this many cells are drawn every VBlank at least
                                    ; (within the lines to the display), so a fixed place's wait
                                    ; is bounded: the cost note at the top

; Text_Left: d0.w = lines from now to the display's first line (negative: it has begun)
Text_Left:
    bsr     Spr_Line
    cmpi.w  #LSPC_LINE_VBL, d0
    blo.s   .before
    subi.w  #$200+LSPC_LINE_SHOWN-$0F8, d0      ; to the counter's top ($1FF), then $0F8 up
    neg.w   d0                                  ; to the first line shown
    rts
.before:
    subi.w  #LSPC_LINE_SHOWN, d0
    neg.w   d0
    rts

Text_Flush:
    cmpi.l  #TEXT_ON_MAGIC, SHIM_TEXT_ON
    bne     .off
    movem.l d0-d7/a0-a5, -(sp)
    COST_START                      ; the raster line now (the cost: test builds)
    lea     REG_VRAMADDR, a5
    move.w  #1, 4(a5)               ; REG_VRAMMOD
    move.w  #TEXT_BUDGET, d6
    move.w  SHIM_VIEW, d7
    lsr.w   #3, d7                  ; the view's row of 8 lines
    tst.w   SHIM_TEXT_LIFT
    beq.s   .key
    addi.w  #TEXT_LIFT_KEY, d7      ; the title lift on
.key:
    tst.w   SHIM_TEXT_BLANK
    bne.s   .blank
.vrow:
    cmp.w   SHIM_TEXT_VROW, d7
    beq.s   .rows
    tst.w   SHIM_TEXT_FIXON
    beq.s   .moved                  ; nothing on the field's fix map: only the row moves
    bsr     Text_Left
    cmpi.w  #TEXT_NEWROW_LINES, d0
    blt.s   .stay                   ; not this VBlank: the row change waits
    bsr     Text_NewRow             ; (a blank of the field's fix map costs TEXT_BLANK_COST)
    bra.s   .rows
.stay:
    move.w  SHIM_TEXT_VROW, d7      ; the field's cells drawn for the row the fix map holds
    bra.s   .rows
.blank:
    ; a text clear with a glyph on the field's fix map (Text_Wipe, SHIM_TEXT_BLANK): the field's
    ; fix map blanked at once, as a view row change blanks it (Text_NewRow, for the row now due),
    ; rather than cell by cell -- so the screen after it (a game's first play list moves the view)
    ; finds it blank, its HUD not waiting for a second blank (Plan 5 Task 3: the title lift's
    ; change did this at the title's closing clear while the title used the lift)
    tst.w   SHIM_TEXT_FIXON
    beq.s   .blanked                ; (blank already: a row change came first)
    bsr     Text_Left
    cmpi.w  #TEXT_NEWROW_LINES, d0
    blt.s   .vrow                   ; not this VBlank: the cells as they come meanwhile
    bsr     Text_NewRow
    clr.w   SHIM_TEXT_BLANK
    bra.s   .rows
.blanked:
    clr.w   SHIM_TEXT_BLANK
    bra.s   .vrow
.moved:
    move.w  d7, SHIM_TEXT_VROW
.rows:
    bsr     Text_Left               ; the cells the lines left allow (to the display)
    subq.w  #TEXT_PASS_LINES, d0
    bgt.s   .some
    moveq   #0, d0
    bra.s   .cap
.some:
    mulu    #TEXT_CELLS_LINE, d0
    tst.w   SHIM_TEXT_FIXON
    bne.s   .cap                    ; a glyph on the field's fix map: the blank's 40 lines
    subi.w  #TEXT_PLAY_SPARE*TEXT_CELLS_LINE, d0    ; none: play's 31 (two-player Task 7) ...
    cmpi.w  #TEXT_PLAY_FLOOR, d0
    bge.s   .cap
    addi.w  #TEXT_PLAY_SPARE*TEXT_CELLS_LINE, d0    ; ... but TEXT_PLAY_FLOOR cells at least,
    cmpi.w  #TEXT_PLAY_FLOOR, d0                    ; within the lines to the display
    ble.s   .cap
    moveq   #TEXT_PLAY_FLOOR, d0
.cap:
    cmp.w   d0, d6
    ble.s   .budget
    move.w  d0, d6
.budget:
    tst.w   d6
    ble     .sprites                ; no cells left this time
    movea.w #TEXT_ROWS, a2          ; the first row the lift moves (none) ...
    btst    #8, d7
    beq.s   .nolift
    movea.w #TEXT_LIFT_FROM, a2     ; ... with the title lift on
.nolift:
    ext.w   d7                      ; (the view row: 0-4)
    neg.w   d7
    addq.w  #2, d7                  ; fix row of a field cell = y + 2 - view/8 (- the lift)
    ; dirty cells, column by column; in a column a byte of the dirty long (8 rows) at a time,
    ; its lowest set bit from TEXT_LOWBIT. A column with none costs its long's test and the cells'
    ; pointer alone (the walk runs every VBlank: two-player Task 7 paid the join prompt's blink
    ; with it); a column with some sets its other pointers from that one
    lea     SHIM_TEXT_DIRTY, a0
    lea     TEXT_LOWBIT, a1
    lea     SHIM_TEXT-TEXT_ROWS, a3
    moveq   #TEXT_COLS-1, d5
.col:
    lea     TEXT_ROWS(a3), a3       ; column x's cells
    move.l  (a0)+, d1               ; (a0 past column x's long from here)
    bne.s   .cells
.nextcol:
    dbra    d5, .col
    bra     .sprites
.cells:
    clr.l   -4(a0)
    move.w  a3, d4
    subi.w  #SHIM_TEXT&$FFFF, d4    ; x * 32
    lea     TEXT_PLACE, a4
    adda.w  d4, a4
    adda.w  d4, a4                  ; its TEXT_PLACE words
    addi.w  #VRAM_FIX+4*32, d4      ; the fix column of field column x
    moveq   #0, d2                  ; the row of the byte's bit 0
.byte:
    tst.b   d1
    beq     .nextbyte
    moveq   #0, d3
    move.b  d1, d3
    move.b  (a1,d3.w), d3           ; its lowest set bit
    bclr    d3, d1
    add.w   d2, d3                  ; y
    move.w  d3, d0
    add.w   d0, d0
    move.w  (a4,d0.w), d0           ; the cell's TEXT_PLACE word
    bmi     .sprite
    bne.s   .fixed                  ; a fixed place (the HUD)
    move.w  d3, d0                  ; a field cell: its fix row, if on the fix map
    cmp.w   a2, d0
    blo.s   .row
    subq.w  #TEXT_LIFT_ROWS, d0     ; the title lift
.row:
    add.w   d7, d0
    cmpi.w  #31, d0
    bhi.s   .drawn
    cmpi.w  #TEXT_BOMB_FIX, d0
    bhs     .onbomb                 ; fix rows 27-31: maybe a bomb's place
.field:
    add.w   d4, d0
    move.w  d0, (a5)
    moveq   #0, d0
    move.b  (a3,d3.w), d0           ; the character
    beq.s   .fixw
    move.w  d0, SHIM_TEXT_FIXON     ; a glyph on the field's fix map
.fixw:
    addi.w  #TEXT_FIX_WORD, d0
    move.w  d0, 2(a5)
.drawn:
    subq.w  #1, d6
    bne.s   .byte
    bra     .spent
.fixed:
    move.w  d0, (a5)                ; its place
    cmpi.w  #TEXT_BOMB_ROW, d3
    bhs.s   .bomb
    moveq   #0, d0
    move.b  (a3,d3.w), d0           ; the character, in the text font (as a field cell's)
    beq.s   .fixw                   ; (a blank: the font's, either corner)
    cmpi.w  #31-TEXT_P2_COL, d5     ; (x = 31 - d5)
    bhi.s   .fixw                   ; the score and lives (never SHIM_TEXT_FIXON)
.p2font:
    addi.w  #TEXT_P2_FONT, d0       ; player 2's corner: the font's P2 copy
    bra.s   .fixw
.bomb:
    ; a bomb cell, TEXT_BOMB_CAP a flush at most (d5's high word counts them: 0 from the walk's
    ; moveq, dbra leaves it; at the cap the walk ends, as at the budget's end). Its place's bit,
    ; 2 x + fix row - TEXT_BOMB_FIX (x = 31 - d5, fix row y - TEXT_BOMB_ROW + TEXT_BOMB_FIX:
    ; 2 x + y - 30 = y - 2 d5, as bset / bclr take it, mod 32, whatever TEXT_BOMB_FIX), in
    ; SHIM_BOMB_BITS for x 0-15, SHIM_BOMB_BITS2 for x 16-31 (d5 0-15: the same bit number mod
    ; 32), is set by a bomb glyph; the blank glyph is
    ; drawn only while it is set (over this bomb's own glyph), else left out: the place keeps the
    ; field cell drawn there, or nothing. (d2, the row of d1's byte -- rows 24-31's for both
    ; bomb rows -- is free until it is set again.)
    swap    d5
    cmpi.w  #TEXT_BOMB_CAP, d5
    bhs.s   .bcap                   ; the cap reached
    addq.w  #1, d5
    swap    d5
    move.w  d3, d0
    sub.w   d5, d0
    sub.w   d5, d0
    cmpi.w  #16, d5
    blo.s   .bomb2
    move.l  SHIM_BOMB_BITS, d2
    cmpi.b  #TEXT_BOMB_BLANK, (a3,d3.w)
    bhs.s   .bglyph
    bclr    d0, d2
    beq.s   .bleave                 ; no bomb glyph there: leave the place as it is
    move.l  d2, SHIM_BOMB_BITS
    bra.s   .bput
.bglyph:
    bset    d0, d2
    move.l  d2, SHIM_BOMB_BITS
.bput:
    moveq   #TEXT_BOMB_ROW&$18, d2
    moveq   #0, d0
    move.b  (a3,d3.w), d0
    bra     .fixw
.bomb2:                             ; (player 2's half, as above: a glyph in P2's font)
    move.l  SHIM_BOMB_BITS2, d2
    cmpi.b  #TEXT_BOMB_BLANK, (a3,d3.w)
    bhs.s   .bglyph2
    bclr    d0, d2
    beq.s   .bleave
    move.l  d2, SHIM_BOMB_BITS2
    bra.s   .bput
.bglyph2:
    bset    d0, d2
    move.l  d2, SHIM_BOMB_BITS2
    moveq   #TEXT_BOMB_ROW&$18, d2
    moveq   #0, d0
    move.b  (a3,d3.w), d0
    bra.s   .p2font
.bleave:
    ; (the place's address went to REG_VRAMADDR in .fixed, before the bit was known; no data
    ; follows it, so VRAM is untouched -- moving the write past the test would cost more than it
    ; saves. The cell still counts against the budget.)
    moveq   #TEXT_BOMB_ROW&$18, d2
    bra     .drawn
.bcap:
    swap    d5                      ; the cap reached: the walk ends here, as a spent budget's (the
    move.w  d3, d0                  ; cells left wait for the next VBlank: a capped cell's own
    sub.w   d2, d0                  ; walk would cost the lines the cap saves): this cell's bit back
    bset    d0, d1                  ; in d1's byte (d2 its row: 24), the column's rest with it
    bra     .spent
.onbomb:
    ; a field cell on fix row 27 or 28 (columns 4-35: x 0-31, each a bomb's place) takes a
    ; bomb's place: its bit cleared (2 x + row - TEXT_BOMB_FIX: row + 62 - TEXT_BOMB_FIX - 2 d5,
    ; mod 32, in x's long), no bomb glyph there from now.
    ; (d2, the row of d1's byte, is d3 & $18: free until it is set again.)
    cmpi.w  #TEXT_BOMB_FIX+1, d0
    bhi     .field
    move.w  d0, -(sp)
    sub.w   d5, d0
    sub.w   d5, d0
    addq.w  #(62-TEXT_BOMB_FIX)&31, d0
    cmpi.w  #16, d5
    blo.s   .onbomb2
    move.l  SHIM_BOMB_BITS, d2
    bclr    d0, d2
    move.l  d2, SHIM_BOMB_BITS
    bra.s   .onbombed
.onbomb2:
    move.l  SHIM_BOMB_BITS2, d2
    bclr    d0, d2
    move.l  d2, SHIM_BOMB_BITS2
.onbombed:
    move.w  d3, d2
    andi.w  #$18, d2
    move.w  (sp)+, d0
    bra     .field
.sprite:
    andi.w  #$7FFF, d0              ; k
    addi.w  #TEXT_SPR_FIRST, d0
    lsl.w   #6, d0                  ; its SCB1: tile, then attribute
    move.w  d0, (a5)
    moveq   #0, d0
    move.b  (a3,d3.w), d0
    addi.w  #FONT_SPR_BASE, d0
    move.w  d0, 2(a5)
    move.w  #TEXT_SPR_ATTR, 2(a5)
    move.w  #1, SHIM_TEXT_SPRDIRTY  ; its height may change: the pass below
    bra     .drawn
.nextbyte:
    addq.w  #8, d2
    lsr.l   #8, d1
    bne     .byte
    bra     .nextcol
.spent:
    lsl.l   d2, d1                  ; the rest of this column waits for the next VBlank
    or.l    d1, -4(a0)
.sprites:
    ; the text sprites' SCB3 (height, Y for the view), again when a cell changed, a sprite was
    ; held back, the view moved or another list is on display while one is shown (not once the
    ; display has begun: then at the next VBlank -- but when another list went into VRAM, at
    ; once). A row shows no more text sprites than the list in VRAM left places on its bands
    ; (SHIM_SPR_AVAIL, its PB_AVAIL: the 96 per line hold whenever the text came after that list
    ; was built); the others are held back (hidden, retried at every VBlank), in k order.
    move.w  SHIM_VIEW, d0
    bsr     Spr_Late
    beq.s   .ontime
    ; the display has begun: only when another list went into VRAM this VBlank while text is
    ; shown (its places, not the last list's, must hold: the pass writes 27 words, the text
    ; rows lie at least 80 lines down)
    tst.l   SHIM_TEXT_SPR_MASK
    beq     .sprdone
    move.l  SHIM_SPR_SHOWN, d1
    cmp.l   SHIM_TEXT_SPRSEQ, d1
    beq     .sprdone
    bra.s   .sprall
.ontime:
    tst.w   SHIM_TEXT_SPRDIRTY
    bne.s   .sprall
    tst.l   SHIM_TEXT_SPR_MASK
    beq.s   .noshown
    move.l  SHIM_SPR_SHOWN, d1
    cmp.l   SHIM_TEXT_SPRSEQ, d1
    bne.s   .sprall                 ; another list on display
    cmp.w   SHIM_TEXT_SVIEW, d0
    bne.s   .sprall
    bra     .sprdone
.noshown:
    move.w  d0, SHIM_TEXT_SVIEW     ; the view moved, but no text sprite is shown: nothing to move
    bra     .sprdone
.sprall:
    clr.w   SHIM_TEXT_SPRDIRTY
    move.w  d0, SHIM_TEXT_SVIEW
    move.l  SHIM_SPR_SHOWN, SHIM_TEXT_SPRSEQ
    moveq   #0, d1                  ; the places the list in VRAM left (sprites.asm Spr_Upload)
    move.b  SHIM_SPR_AVAIL+1, d1
    movea.w d1, a4                  ; row 16's
    move.b  SHIM_SPR_AVAIL, d1
    movea.w d1, a2                  ; row 14's
    move.w  #VRAM_SCB3+TEXT_SPR_FIRST, (a5)
    lea     TEXT_SPR_CELLS, a1
    lea     SHIM_TEXT, a3
    lea     SHIM_TEXT_DIRTY, a0
    move.l  SHIM_TEXT_SPR_MASK, d6  ; shown until now (bit k)
    moveq   #0, d7                  ; shown from now
    moveq   #0, d5                  ; how many
    moveq   #0, d2                  ; k
.spr:
    moveq   #0, d4                  ; height 0: hidden
    move.w  6(a1), d3
    move.b  (a0,d3.w), d3
    move.w  8(a1), d1
    btst    d1, d3
    beq.s   .clean
    btst    d2, d6                  ; a pending cell: its sprite still holds the old glyph,
    beq.s   .hide                   ; shown or hidden as it was (only its Y follows the view)
    bra.s   .show
.clean:
    move.w  (a1), d3                ; drawn: shown when the character has a glyph (not 0,
    move.b  (a3,d3.w), d3           ; not a space, below $80)
    ble.s   .hide
    cmpi.b  #' ', d3
    beq.s   .hide
.show:
    cmpi.w  #17, d2                 ; k 0-16: row 14, 17-26: row 16
    bhs.s   .r16
    move.w  a2, d1
    beq.s   .held
    subq.w  #1, a2
    bra.s   .room
.r16:
    move.w  a4, d1
    beq.s   .held
    subq.w  #1, a4
.room:
    move.w  2(a1), d1               ; SPR_Y_BASE - its field line
    add.w   d0, d1                  ; screen line = field line - view
    lsl.w   #7, d1
    addq.w  #1, d1                  ; one tile high
    move.w  d1, d4
    addq.w  #1, d5
    bset    d2, d7
    bra.s   .hide
.held:
    move.w  #1, SHIM_TEXT_SPRDIRTY  ; no place on the list on display: again at the next VBlank
.hide:
    move.w  d4, 2(a5)
    lea     TSC_SIZE(a1), a1
    addq.w  #1, d2
    cmpi.w  #TEXT_SPR_COUNT, d2
    blo.s   .spr
    move.l  d7, SHIM_TEXT_SPR_MASK
    move.w  d5, SHIM_TEXT_SPR_N
.sprdone:
    COST_END SHIM_TEXT_LINES        ; lines taken (Spr_Lines: the counter runs $0F8-$1FF)
    movem.l (sp)+, d0-d7/a0-a5
.off:
    rts

; ------------------------------------------------------------------------------
; Text_NewRow: the view moved to another row of 8 lines, or the title lift came or went (d7 = the
; new SHIM_TEXT_VROW, a5 = REG_VRAMADDR) while the field's fix map holds a glyph: field cells on
; the fix layer move to other rows. The field's part of the fix map (columns 4-35, the HUD's
; places with it) is blanked and the set cells on it, the HUD's too, are drawn again (marked
; dirty: TEXT_FIXMASK); no bomb glyph is on it until they are. Uses d0-d2/a0-a2; d6 (the cells
; left) drops by TEXT_BLANK_COST.
; ------------------------------------------------------------------------------
Text_NewRow:
    move.w  d7, SHIM_TEXT_VROW
    clr.w   SHIM_TEXT_FIXON         ; blank from here: the cells drawn again set it
    clr.l   SHIM_BOMB_BITS          ; (and the bombs' glyphs drawn again set theirs)
    clr.l   SHIM_BOMB_BITS2
    subi.w  #TEXT_BLANK_COST, d6    ; the blank's time comes out of this VBlank's cells
    move.w  #VRAM_FIX+4*32, (a5)
    move.w  #TEXT_FIX_WORD, d1
    move.w  #TEXT_COLS*32/8-1, d0
.blank:
    rept    8
    move.w  d1, 2(a5)
    endr
    dbra    d0, .blank
    lea     SHIM_TEXT_USED, a0
    lea     SHIM_TEXT_DIRTY, a1
    lea     TEXT_FIXMASK, a2
    moveq   #TEXT_COLS-1, d0
.mark:
    move.l  (a0)+, d2
    and.l   (a2)+, d2
    or.l    d2, (a1)+
    dbra    d0, .mark
    rts

; ------------------------------------------------------------------------------
; TEXT_PLACE: one word per cell, column-major (cell (x, y) at word x * 32 + y):
;   TP_FIELD        the fix layer at (x + 4, y + 2 - view/8)
;   TP_SPRITE + k   text sprite k (TEXT_SPR_CELLS[k])
;   else            the fix map address of its fixed place (the HUD), in the field's columns 4-35
; The HUD (graphics-recon section 3) over the field at the original's places, fixed on the
; screen (Presentation Task 2):
;   "SC 0x" + 7 hex digits, field row 1 cols 1-12  -> fix (x + 4, y + 2): row 3, cols 5-16
;   lives (char 4 / 0), field row 2 cols 1-10      -> fix (x + 4, y + 2): row 4, cols 5-14
;   bombs (16x16 glyph 2 / 0), i = 0-7 at field (2i..2i+1, 30..31)
;                                                  -> fix (x + 4, y - 3): rows 27-28, cols 4-19
;                                                     (screen lines 200-215, x 32-159, in order)
; and player 2's, the same shifted right (two-player plan Task 7; coop.asm Coop_Text8 / _Text16):
;   its score, field row 1 cols 19-30               -> fix row 3, cols 23-34
;   its lives, field row 2 cols 19-28               -> fix row 4, cols 23-32
;   its bombs, i = 8-15 at field (2i..2i+1, 30..31) -> fix rows 27-28, cols 20-35 (x 160-287)
; (field col 30 is screen x 272-279: inside the field, off the strips and the CRT crop; the join
; prompt, coop.asm Coop_Prompt, is a corner's row-1 cells)
; Stage cards ("STAGE n" at (12, 14), the bonus stage's card at (8, 14)) and the game over's at
; (11, 16): row 14 cols 8-24 = sprites 0-16, row 16 cols 11-20 = sprites 17-26.
; ------------------------------------------------------------------------------
TP_OF   macro                       ; TPV = the TEXT_PLACE word of cell (TX, TY)
TPV     set     TP_FIELD
    if ((TY=1)&&(TX>=1)&&(TX<=12))||((TY=2)&&(TX>=1)&&(TX<=10))
TPV     set     VRAM_FIX+(TX+4)*32+TY+2
    endif
    if TEXT_P2_HUD
    if ((TY=1)&&(TX>=19)&&(TX<=30))||((TY=2)&&(TX>=19)&&(TX<=28))
TPV     set     VRAM_FIX+(TX+4)*32+TY+2
    endif
    endif
    if (TY>=TEXT_BOMB_ROW)&&((TX<=15)||TEXT_P2_HUD)
TPV     set     VRAM_FIX+(TX+4)*32+TY-TEXT_BOMB_ROW+TEXT_BOMB_FIX
    endif
    if (TY=14)&&(TX>=8)&&(TX<=24)
TPV     set     TP_SPRITE+TX-8
    endif
    if (TY=16)&&(TX>=11)&&(TX<=20)
TPV     set     TP_SPRITE+17+TX-11
    endif
    if (TPV!=TP_FIELD)&&(TPV<TP_SPRITE)&&((TPV<VRAM_FIX+4*32)||(TPV>=VRAM_FIX+36*32))
    fail    "TEXT_PLACE: a fixed place outside the field's fix columns 4-35"
    endif
    endm

    even
TEXT_PLACE:
TX      set     0
    rept    TEXT_COLS
TY      set     0
    rept    TEXT_ROWS
    TP_OF
    dc.w    TPV
TY      set     TY+1
    endr
TX      set     TX+1
    endr

; Player 2's HUD (two-player plan; coop.asm Coop_Text8 / Coop_Text16) is written only when every
; one of its cells has a fixed place: on the field's fix map it would move with the view
    if TEXT_P2_HUD
TY      set     1
    rept    2
TX      set     1+COOP_HUD8_DX
    rept    12-2*(TY-1)             ; (row 1: the score's 12, row 2: the lives' 10)
    TP_OF
    if TPV==TP_FIELD
    fail    "TEXT_P2_HUD: a cell of player 2's score or lives has no place (TP_OF)"
    endif
TX      set     TX+1
    endr
TY      set     TY+1
    endr
TY      set     TEXT_BOMB_ROW
    rept    2
TX      set     2*COOP_HUD16_DX
    rept    16
    TP_OF
    if TPV==TP_FIELD
    fail    "TEXT_P2_HUD: a cell of player 2's bombs has no place (TP_OF)"
    endif
TX      set     TX+1
    endr
TY      set     TY+1
    endr
    endif

; TEXT_FIXMASK: per column x, bit y set when cell (x, y) is on the fix map (TP_FIELD or a fixed
; place: Text_NewRow draws it again after its blank), not on a text sprite
TEXT_FIXMASK:
TX      set     0
    rept    TEXT_COLS
TM      set     0
TY      set     0
    rept    TEXT_ROWS
    TP_OF
    if TPV<TP_SPRITE
TM      set     TM|(1<<TY)
    endif
TY      set     TY+1
    endr
    dc.l    TM
TX      set     TX+1
    endr

; TEXT_LOWBIT: the number of the lowest set bit of a nonzero byte
TEXT_LOWBIT:
TB      set     0
    rept    256
TL      set     0
    if (TB&$0F)=0
TL      set     TL+4
    endif
    if ((TB>>TL)&3)=0
TL      set     TL+2
    endif
    if ((TB>>TL)&1)=0
TL      set     TL+1
    endif
    dc.b    TL&7
TB      set     TB+1
    endr

; TEXT_SPR_CELLS: per text sprite k: its cell (x * 32 + y), SPR_Y_BASE - its field line, SCB4,
; its dirty bit (byte offset in SHIM_TEXT_DIRTY: x * 4 + 3 - y / 8, bit y & 7)
TSC_SIZE EQU    10
TEXT_SPR_CELLS:
TX      set     8
    rept    17
    dc.w    TX*32+14, SPR_Y_BASE-14*8, (32+8*TX)<<7, TX*4+3-14/8, 14&7
TX      set     TX+1
    endr
TX      set     11
    rept    10
    dc.w    TX*32+16, SPR_Y_BASE-16*8, (32+8*TX)<<7, TX*4+3-16/8, 16&7
TX      set     TX+1
    endr
    if (*-TEXT_SPR_CELLS)!=TEXT_SPR_COUNT*TSC_SIZE
    fail    "TEXT_SPR_CELLS: one entry per text sprite"
    endif
