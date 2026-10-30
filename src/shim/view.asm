; ==============================================================================
; THE VIEW (Plan 3 Task 7): which 224 of the original's 256 field lines the Neo Geo shows.
;
; The screen shows field lines view .. view + 223 (view 0..VIEW_MAX), at screen x = field x + 32.
; The view belongs to each sprite list: View_Build runs in xsp_out's build (sprites.asm
; Spr_Build, the game's time) and sets the list's PB_VIEW; the build lays the list's objects
; (their SCB3 Y), the guard's 8-line bands and the text reservation (PB_AVAIL) out for that view,
; and the VBlank that puts the list into VRAM takes the same view for the background chains'
; heads (Bg_Take: SHIM_BG_VIEW) and for the text (SHIM_VIEW: the text sprites' Y, the fix
; layer's rows). So every displayed frame has one view for all of it, whatever the view of the
; lists built since: a list kept (a step overran) or a static screen (the title's logo, the game
; over's frozen field) keeps its view with it, and the text sprites' places come from the list
; that is on the screen (Task 4's 96-per-line guarantee holds while the view moves).
;
; Play lists -- those that set the graphic scroll (CRTC R13 / R17 among their xsp_wpoke words:
; PB_BG, which only the play loop's lists do) -- follow the ship (player_y, 1/64 px; its
; reference line on the field ref = player_y / 64 - 16, its sprites on lines ref - 10 .. ref +
; 21, graphics-recon 1.4), but only as far as it needs (fix round 1: the top of the field, where
; the enemies and bullets come from, stays on the screen as long as it can):
;  * the target: 0 (the top) while the ship's bottom line (ref + 21) is at most screen line 223
;    less VIEW_MARGIN; below that it keeps the ship's bottom VIEW_MARGIN lines above the screen's
;    last line: bottom + VIEW_MARGIN - 223, at most VIEW_MAX. So the view leaves 0 when ref
;    passes 186 (the ship's resting place after it rises in is ref 176: view 0) and is 32 from
;    ref 218 down (the bottom clamp is ref 236);
;  * the smoothing: from the list before's view (SHIM_VIEW_LAST) at most VIEW_STEP lines a list
;    toward the target, down and back up; the first play list after a fixed screen's (a game's
;    start, a CONTINUE: the field comes out of the loading's black) is at its target
;    (SHIM_VIEW_PLAY);
;  * VIEW_MARGIN is the catch-up room for the smoothing: the ship moves at most VIEW_SHIP_SPEED
;    (3) lines a step down (the game's code: $6E92-$6EAC adds speed / 16 x the stick's direction
;    word, the speed $221AE is only ever set to $30 ($6CCA), the direction table $26592's words
;    are at most 64: 3 x 64 = 192 = 3 px; measured 3 px in MAME). Diving from the threshold at
;    full speed from view 0, after k steps the ship's bottom is on field line 223 - VIEW_MARGIN +
;    3k and the screen's last line on 223 + 2k (the target runs ahead, the view moves its 2):
;    whole while 3k - VIEW_MARGIN <= 2k, for every k until the view reaches VIEW_MAX after
;    VIEW_MAX / VIEW_STEP = 16 steps (then the field's last line is on the screen). So
;    VIEW_MARGIN = 16 x (3 - 2) = VIEW_SHIP_SPEED x VIEW_MAX / VIEW_STEP - VIEW_MAX = 16;
;  * the ship whole on the screen, whatever the smoothing: while its top is on the field, the
;    view at most max(ref - 10, 0) and at least min(ref + 21, 255) - 223 -- its lines on the
;    field inside view .. view + 223. The margin keeps the smoothing inside these bounds; the
;    clamp only acts when something else moved the view (a test's override let go). A new ship
;    rises from below the field (y $5000, ref 304: VIEW_MAX the target, no bound while it is
;    below): the view gets there before its top shows (16 lists against 38);
;  * while the ship is dead (the death timer runs: it explodes where it was) the view holds,
;    settling one line a list on a multiple of 8 -- the nearest one inside the ship's bounds
;    (one ship's bounds always hold one: they are [0, x] or [y, 32]; two players' hold bounds
;    are made to, Coop_View) -- so the exploding ship stays
;    whole and a game over (the last death: the game over loop shows the last play list, no new
;    one) freezes on an 8-aligned view: the fix layer's rows line up with the field's sprites
;    there, as on every fixed screen.
; Two players (two-player plan Task 9; SHIM_COOP_2P set -- one test at a play list's start, so one
; player's path is the rule above, unchanged): coop.asm's Coop_View makes the bounds and the target
; from the ships that count -- in play (SHIM_COOP_IN) and alive (death timer 0: an exploding ship,
; or an out one with its timer held at $5C, does not) -- each giving the range above. The higher
; ship whole first (the most view the higher's most), the lower too whenever both fit (the least
; view the lower's least, at most that), the target the lower's own, at most the higher's most;
; ships too far apart for both (some 190 lines) keep the higher whole at the screen's top, the
; lower's bottom off the screen. One ship counted is followed by the rule above exactly (P2 alone
; as P1 in a one-player game); none counted, the dying hold, in the bounds of the dying ships the
; view shows whole as the hold begins (the higher first; the lower too while a multiple of 8 stays
; inside) -- bounds that hold the view and a multiple of 8, so the hold never snaps the view to an
; explosion it had left (P1's far below while P2 lived) and settles 8-aligned (a game over too).
; The smoothing, the margin and the clamp are the ones above; the clamp keeping the higher ship
; whole may move the view more than VIEW_STEP (the higher rising while the lower holds the view at
; its bound). tests/neo/view.lua VW_MODE=two checks every two-player list against this.
; Every other list (the title's logo, CONFIG's and the game over's empty ones) has VIEW_FIXED (0):
; the title, CONFIG and KAKUSI are fixed screens at view 0 (their text on the fix layer lines up
; with the field, and Text_NewRow never blanks it while they show: the view cannot move without a
; new list).
;
; Tests (make cart SHIM_TEST_VIEW=1 only): SHIM_VIEW_FORCE = $8000 | v sets every list's view to
; v (tests/neo/sprites.lua: the replays at view 0, a view moving every frame; text.lua: the stage
; card at view 13; view.lua: the clamp after a release).
;
; Reads the game's player_y, death timer (link.py SHIM_VARS: GV_PLAYER_Y, GV_DEATH_TIMER; two
; players: P2's in SHIM_COOP_P2, SHIM_COOP_IN), never writes game RAM. Cost: about 400 cycles a
; list (the game's time; one player: the 2P test's 26 more, tst.b 16 + the taken beq.s 10). State: SHIM_VIEW_LAST,
; SHIM_VIEW_PLAY, SHIM_VIEW_FORCE (shim.inc).
;
; The text sprites and the display (fix round 1): the text sprites' SCB3 pass (text.asm
; Text_Flush) may finish a few lines into the display when a list goes into VRAM late in the
; VBlank (measured once: line 0, in the MODE 3 replay with the view moving every frame; never in
; play). That cannot tear: every text sprite starts at screen line TEXT_SPR_LINE_TOP - VIEW_MAX
; or lower under any view, far below the lines being shown then. The assert below keeps it so.
; ==============================================================================

VIEW_MAX        EQU 32              ; 256 - 224
VIEW_FIXED      EQU 0               ; lists that do not scroll the graphic pages
VIEW_STEP       EQU 2               ; the most the view moves from one list to the next
VIEW_SHIP_SPEED EQU 3               ; the ship's most lines a step down (the game's code, above)
VIEW_MARGIN     EQU VIEW_SHIP_SPEED*VIEW_MAX/VIEW_STEP-VIEW_MAX     ; 16: the catch-up room
VIEW_SHIP_UP    EQU 10              ; the ship's sprites: lines ref - 10 ..
VIEW_SHIP_DOWN  EQU 21              ; .. ref + 21
VIEW_ALIGN      EQU 8               ; the view a death settles on: a multiple of the fix rows
TEXT_SPR_SAFE   EQU 80              ; the text sprites' first screen line under any view, at least
    if VIEW_MARGIN<0
    fail "the view's catch-up margin"
    endif
    if TEXT_SPR_LINE_TOP-VIEW_MAX<TEXT_SPR_SAFE
    fail "a text sprite could start near the display's top: its SCB3 pass may run into the display"
    endif

; ------------------------------------------------------------------------------
; View_Build (Spr_Build, a6 = the list's buffer, its PB_BG set): the list's view -> PB_VIEW(a6) and
; SHIM_VIEW_LAST (the build's walk and Spr_Rooms lay the list out for it). Uses d0-d4.
; ------------------------------------------------------------------------------
View_Build:
    ifd     SHIM_TEST_VIEW
    move.w  SHIM_VIEW_FORCE, d0
    bmi     .forced
    endif
    tst.w   PB_BG(a6)
    bne.s   .play
    clr.w   SHIM_VIEW_PLAY          ; a fixed screen (the next play list starts at its target)
    moveq   #VIEW_FIXED, d0
    bra     .done
.play:
    tst.b   SHIM_COOP_2P
    beq.s   .one
    jsr     Coop_View               ; two players (coop.asm): d3 / d4 the counted ships' bounds, d2
    beq     .dead                   ; their target, d0 the list before's view; Z: no ship counted
    bra     .step                   ; (the dying hold, in the bounds of the explosions shown whole)
.one:
    move.w  GV_PLAYER_Y, d1
    asr.w   #6, d1
    subi.w  #16, d1                 ; ref: the ship's line on the field
    ; the ship's bounds: d3 the least view, d4 the most (none while it is below the field)
    moveq   #0, d3
    moveq   #VIEW_MAX, d4
    move.w  d1, d2
    subi.w  #VIEW_SHIP_UP, d2       ; its top line
    cmpi.w  #255, d2
    bgt.s   .bounds                 ; below the field (a new ship rising): nothing shows yet
    cmp.w   d4, d2                  ; at most max(top, 0) ...
    bge.s   .least
    move.w  d2, d4
    bpl.s   .least
    moveq   #0, d4
.least:
    move.w  d1, d2                  ; ... at least min(bottom, 255) - 223
    addi.w  #VIEW_SHIP_DOWN-223, d2
    ble.s   .bounds
    cmpi.w  #VIEW_MAX, d2
    ble.s   .lo
    moveq   #VIEW_MAX, d2
.lo:
    move.w  d2, d3
.bounds:
    move.w  SHIM_VIEW_LAST, d0
    tst.w   GV_DEATH_TIMER
    bne.s   .dead
    ; the target: the ship's bottom VIEW_MARGIN lines above the screen's last line, 0..VIEW_MAX
    move.w  d1, d2
    addi.w  #VIEW_SHIP_DOWN+VIEW_MARGIN-223, d2
    bpl.s   .tmax
    moveq   #0, d2
.tmax:
    cmpi.w  #VIEW_MAX, d2
    ble.s   .step
    moveq   #VIEW_MAX, d2
.step:
    tst.w   SHIM_VIEW_PLAY
    bne.s   .smooth
    move.w  #1, SHIM_VIEW_PLAY      ; the first play list after a fixed screen (the field comes
    move.w  d2, d0                  ; out of the loading's black): at the target
    bra.s   .bound
.smooth:
    ; toward the target, VIEW_STEP lines a list at most
    sub.w   d0, d2
    cmpi.w  #VIEW_STEP, d2
    ble.s   .up
    moveq   #VIEW_STEP, d2
.up:
    cmpi.w  #-VIEW_STEP, d2
    bge.s   .move
    moveq   #-VIEW_STEP, d2
.move:
    add.w   d2, d0
    bra.s   .bound
.dead:
    ; the ship dead: the view holds, settling on the nearest multiple of VIEW_ALIGN inside the
    ; ship's bounds, a line a list (two players: d3 / d4 hold the view and a multiple, Coop_View)
    move.w  d0, d2
    addq.w  #VIEW_ALIGN/2, d2
    andi.w  #-VIEW_ALIGN, d2
    cmp.w   d3, d2
    bge.s   .dlo
    move.w  d3, d2                  ; below the least: the multiple of 8 above it
    addq.w  #VIEW_ALIGN-1, d2
    andi.w  #-VIEW_ALIGN, d2
.dlo:
    cmp.w   d4, d2
    ble.s   .dhi
    move.w  d4, d2                  ; above the most: the multiple of 8 below it
    andi.w  #-VIEW_ALIGN, d2
.dhi:
    cmp.w   d0, d2
    beq.s   .bound
    blt.s   .down
    addq.w  #1, d0
    bra.s   .bound
.down:
    subq.w  #1, d0
.bound:
    ; the ship whole: inside its bounds (0..VIEW_MAX)
    cmp.w   d4, d0
    ble.s   .most
    move.w  d4, d0
.most:
    cmp.w   d3, d0
    bge.s   .done
    move.w  d3, d0
    ifd     SHIM_TEST_VIEW
    bra.s   .done
.forced:
    andi.w  #$7FFF, d0
    cmpi.w  #VIEW_MAX, d0
    bls.s   .done
    moveq   #VIEW_MAX, d0
    endif
.done:
    move.w  d0, PB_VIEW(a6)
    move.w  d0, SHIM_VIEW_LAST
    rts
