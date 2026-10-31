; ==============================================================================
; TWO-PLAYER CO-OP (docs/superpowers/specs/2026-10-28-two-player-design.md). link.py's GAME_HOOKS
; send five of the game's instructions here:
;   $426A jsr $6CEC.l          (6 bytes) -> jsr (Coop_Pass).l       the play loop's three calls
;   $7470 move.w $2B8AC.l,d0   (6 bytes) -> jsr (Coop_Tail).l       $70A0's tail: the bomb timer
;   $6EFA pea $1F.w            (4 bytes) -> jsr GHOOKJT_Coop_ShipSlot.w   $6CEC: the ship sprite's
;                                                                   first push
;   $765E cmp.w #$1F,d3        (4 bytes) -> jsr GHOOKJT_Coop_Hit.w  the hit test (bne.b follows)
;   $441E move.l $22200.l,d0   (6 bytes) -> jsr (Coop_Over).l       the game over (once a game): a
;                                                                   one-player game's last look
; A 6-byte site calls its label directly (game.asm assembles the jsr between pieces of game.bin)
; and returns to site + 6; a 4-byte one goes through its slot of GHOOK_JT ($7F00: game.asm's
; `jmp (<label>).l`) and returns to site + 4. The play loop's other two calls, $70A0 and $45AE
; ($4270-$427B), are a bra.s to $427C now (link.py GAME_CODE): Coop_Pass makes all three, so the
; loop pays one test a step for them (ruling R5).
; Every hook first tests SHIM_COOP_2P (0 until P2 first joins a game; the coop block is cleared at
; every resume and at every game's setup): at 0 it does the replaced work alone and writes no game
; RAM, so one player runs as before (the lock-step, the timing, the demo: G1). Coop_Pass tests it
; together with SHIM_COOP_NEW as one word (the same 16 cycles as the byte): a title pass sets that
; byte (Title_Hook), so a game's first step takes the slow path once, to set the block up
; (Coop_Setup), and every other one-player step passes through. Coop_Pass ends with a jmp to
; $45AE, whose rts returns to $4270 (the bra.s); the others end with the instruction itself, then
; rts, which keeps its CCR (move and cmp set it for the beq / bne after them; pea leaves CCR alone,
; but the hook's test does not: dead there, move.l a1,-(a7) at $6F0C sets it before any test). The
; routines at $6CEC, $70A0 and $45AE set CCR before they read it. While $6CEC and $70A0 run, the
; stack holds Coop_Pass's return address too (4 bytes deeper than the original's; in two-player
; Coop_PassOne's return and frame too, and while $6CEC runs the open list's end: Coop_Ship).
;
; Two players (SHIM_COOP_2P set): the original's ship code runs once per player in play, with
; player 2's context (SHIM_COOP_P2, 40 bytes: the player block, the ship's y and x, the stored pad
; bytes, score_add) swapped into the game's globals around player 2's pass (Coop_Exchange), so
; both ships move, fire, bomb, die and respawn by the original's own code. One step:
;   * the order: P1 then P2 on even steps (GV_FRAME bit 0 clear), P2 then P1 on odd ones, so that
;     neither player takes the whole shot pool when it runs short (the spec's builder check); a
;     player not in SHIM_COOP_IN is skipped;
;   * each pass: $6CEC (the ship: its move, its death and respawn; its sprite on collision slot $1D
;     in P2's context, Coop_ShipSlot: the 29 shots' last slot, Task 3), SHIM_COOP_NFREE = the
;     free-shot stack's count, $70A0 (the fire and the bomb: both pop the one shared stack);
;   * $70A0's tail ($7470-$75DE: the bomb's run and its collision, every shot's move and the free
;     stack rebuilt) runs once a step, in the last pass that runs (SHIM_COOP_TAIL; Coop_Tail
;     returns to the epilogue $75E0 in the others): every shot moves once, and the stack the next
;     pass pops is the one the first left;
;   * then slot $1D taken off the free-shot stack while P2 is in (Coop_Take1D: P2's ship's
;     collision slot, the 29 shots' pool), P2's score_add added to its score every fourth step
;     (the original's $40D4 rule, P1's), and the objects' pass: the shim's own loop in $45AE's
;     place (Coop_Objects, Task 4: each object's target, P2's place swapped in for those whose
;     target is P2; one player keeps $45AE);
;   * the step's end (Coop_End): an out player's score_add zeroed; the game over's closing.
; Lives (Task 5): each player dies and respawns by the original's own code in its pass (P2's
; respawn 32 px right of P1's, a bomb the other set off kept going: Coop_PassOne). A player whose
; last ship's death ends the original's way ($6E30: the game over flag) is out (Coop_Out): its
; passes skipped, its HUD corner the join prompt's (Task 7), and the flag back to 0 while the
; other plays; no player left, the original's GAME OVER (and then its title). A player joins or
; buys in (Coop_Join) with a new game's stock and score 0, rising in as at a respawn.
; Hits (Coop_Hit, Task 3): the objects turn the collision mask's slots into damage and score
; through $75EA(slot) ($46B4: score_add += the sum x 8, $47B2). A shot's slot is its owner's
; (SHIM_COOP_OWN: Coop_Tail marks the slots each pass's fire part popped), the bomb ($1E) its
; setter's (SHIM_COOP_BOMB: Coop_PassOne), $1D P2's ship while P2 is in (its kill: the original's
; $6FE2 in P2's context); for P2's the damage is P2's, its x 8 moved from score_add to P2's. A hit
; while the loop has P2's place swapped in has the swap undone around it (Coop_Hit_Swap, R7).
; Starts (Task 6): P2's START at the title starts both players (PLAYER_START, title.asm:
; SHIM_COOP_START2, joined at the game's first step, Coop_Starts); in play P2's START joins, and
; P1's buys P1 back in, through the BIOS's start handshake (Coop_Start, in the VBlank: the BIOS
; takes one of P1's credits, MVS without Free Play) as a request the next pass serves, or the game
; over's last look (Coop_End; one player, Coop_Over): a credit taken always brings its ship in,
; and after that look nothing is accepted. A player is in from the masked moment its request is
; taken (Coop_Take), so a START during its join is refused (final review I2). Where the BIOS drops
; P2's START (the US BIOS, its game start compulsion off: Coop_P2Key, in the VBlank) the game spends
; P1's credits itself in that same masked moment (Coop_Spend; the title's: title.asm Title_P2).
; P2's pad: _JOYGET's port 0 reads REG_P2CNT while P2's context is in (SHIM_COOP_PAD, iocs.asm),
; AUTO FIRE as P1's.
; Colours (Task 8): P2's sprites take Neo palette PAL_P2_BASE + block (INFO bit 13: sprites.asm
; ATTR; tools/mkgfx.py p2_palette): its ship (Coop_Ship: the INFO $93A that $6CEC's xobj_set
; recorded in P2's pass made $293A in the open list; the dying and invulnerable blinks $E3A / $F3A
; as they are; no hook: one player pays nothing) and its shots (Coop_Own: bit 13 set in the
; attribute word of each it fires, which the fire part has just written: $719E, $7240, $72BC); its
; HUD in the font's P2 copy (text.asm Text_Flush: P2's corner).
; The HUD (Task 7): P2's is P1's shifted right, written by the original's own HUD code in P2's
; context (Coop_Text8 / Coop_Text16: field rows 1-2 x + 18, the bombs' 16x16 row x + 8 glyphs;
; text.asm TEXT_PLACE gives them fixed places as P1's); its score printed by Coop_Pass_2P's flush
; and by Coop_Join (Coop_Score2). The join prompt (Coop_Prompt; the user's choice, 2026-10-28:
; every one-player game too): the corner of a player not in blinks PRESS START or INSERT COIN
; while a title-mode game's play loop runs with the joins open; its cells are written only when
; they change (the blink's half, the text, the corners), in the main code: a one-player game's
; Coop_Pass takes its slow path for it only when the VBlank finds it due (Coop_Blink: no test
; added to the one-player step), two players' at every step; cleared by the game over (Coop_Over)
; and, a corner's, by its player's join.
; Stages (Task 10): nothing of the co-op's. A stage's end is `stage` + 1 ($8132, $8DF8, $9774; the
; bonus stage's end writes 4, which v0.10 plays as stage 1, $4A50): no ship is moved (every write
; to the ship's y / x is $6CC4-$6FE2's, in the passes) and no player block touched, so both ships
; go through the stages as P1's does in the original, each with its own place, stock and score.
; No stage-end award either: the original's one call of $7750 / $771C / $784E outside the passes
; and the objects ($422A-$4236) is the debug keys' ($416C: the debug flag $221F0, ROM 0 here, and
; _BITSNS's group $E, never down), so neither player gets one; the item's ($D996, $DB0E, $DD08)
; goes to its collector (Coop_Objects). tests/neo/coop.lua whole_game_2p watches it all.
; The view (Task 9): view.asm's View_Build, a two-player play list, calls Coop_View for the bounds
; and the target from the ships that count (in play, alive): the higher whole first, the lower too
; whenever both fit; one ship counted is followed by one player's rule; none, the dying hold in
; the bounds of the explosions the view shows whole.
; COOP_CODE (boot.asm, after DEMO_DATA) places it all in high P-ROM, above the demo's stream: the
; labels follow game.asm, which names them without ifd (a missing one: undefined symbol).
; ==============================================================================
GAME_TAIL_SKIP  EQU GAME_ROM+$75E0  ; $70A0's epilogue (movem, unlk, rts): its tail left out
GAME_KILL       EQU GAME_ROM+$6FE2  ; the ship's kill (invulnerability, death timer, muteki
                                    ; tests; sound $E, the explosion at the ship)
GAME_HIT_OUT    EQU GAME_ROM+$76CA  ; $75EA's epilogue (movem, unlk, rts: d0 the damage)
GAME_HIT_SUM    EQU GAME_ROM+$46B4  ; $46B4..$47BD: the caller that scores (score_add += its
GAME_HIT_SUM_END EQU GAME_ROM+$47BE ; damages' sum x 8, $47B2); $47BE's two ($12C2E, $12EE0)
                                    ; drop its sum (no score)
COOP_P2_SHIP    EQU $1D             ; P2's ship's collision slot (P1's: $1F)
COOP_BOMB_SLOT  EQU $1E             ; the bomb's ($75EA: its damage $60)
COOP_BOMB_DAMAGE EQU $60
COOP_SHOT_LOG2  EQU 7               ; a shot's size, $80 (GV_SHOTS: slots 0-$1D)
COOP_SHOT_SIZE  EQU 1<<COOP_SHOT_LOG2
COOP_BLK_DAMAGE EQU $22198-$22196   ; the player block's shot damage ($776A's, by power level)
COOP_ITEM       EQU GAME_ROM+$D440  ; the item's handler (Coop_Objects)
COOP_BULLET0    EQU GAME_ROM+$AE08  ; the four bullets' handlers
COOP_BULLET1    EQU GAME_ROM+$AFB8
COOP_BULLET2    EQU GAME_ROM+$B196
COOP_BULLET3    EQU GAME_ROM+$B354
COOP_BLK_DEATH  EQU $221A8-$22196   ; the player block's death timer, then invulnerability (a long)
COOP_BLK_INVULN EQU $221AA-$22196
COOP_BLK_LIVES  EQU $221AC-$22196   ; the spare ships
COOP_BLK_BURST  EQU $221A2-$22196   ; the burst counter, then $221A4 (the fire part's)
COOP_P2_DX      EQU $800            ; P2's entry and respawn x: 32 px right of P1's ($6CC4's $2200)
COOP_HUD8_DX    EQU 18              ; P2's HUD (Task 7's places): Text8 on field rows 1-2, x + 18
COOP_HUD16_Y    EQU 15              ; Text16's bombs' row (16-px units: cells 30-31) ...
COOP_HUD16_DX   EQU 8               ; ... cells 16-31 (mirrored: Coop_Text16)
COOP_LOOP       EQU GAME_ROM+$40C6  ; the play loop's step ($4414's beq.w: the game over flag 0)
COOP_PASS_GO    EQU 0               ; Coop_PassOne's frame: the game over flag as the pass began,
COOP_PASS_BOMB  EQU 2               ; the bomb timer as it began,
COOP_PASS_WHO   EQU 4               ; the player (a word: 1 | 2)
COOP_PASS_SIZE  EQU 6

COOP_SWAP macro                     ; \1 longs: (a0)+ <-> (a1)+
    rept    \1
    move.l  (a0), d0
    move.l  (a1), (a0)+
    move.l  d0, (a1)+
    endr
    endm


COOP_NEAR macro                     ; \1: 0 |dx| + |dy|, else max(|dx|, |dy|/2) (Coop_NearSum, _Max)
    cmpi.b  #3, d1
    bne.s   .out                    ; one ship, or none: that one
    move.w  (a3), d0                ; P1's: |dx|
    sub.w   d6, d0
    bpl.s   .x1
    neg.w   d0
.x1:
    move.l  d6, d2                  ; |dy|
    swap    d2
    sub.w   2(a3), d2
    bpl.s   .y1
    neg.w   d2
.y1:
    if \1
    lsr.w   #1, d2
    cmp.w   d2, d0
    bhs.s   .j1
    move.w  d2, d0
    else
    add.w   d2, d0
    bcc.s   .j1
    moveq   #-1, d0
    endif
.j1:
    move.w  (a3), d1                ; P2's
    sub.w   d7, d1
    bpl.s   .x2
    neg.w   d1
.x2:
    move.l  d7, d2
    swap    d2
    sub.w   2(a3), d2
    bpl.s   .y2
    neg.w   d2
.y2:
    if \1
    lsr.w   #1, d2
    cmp.w   d2, d1
    bhs.s   .j2
    move.w  d2, d1
    else
    add.w   d2, d1
    bcc.s   .j2
    moveq   #-1, d1
    endif
.j2:
    cmp.w   d0, d1
    blo.s   .p2
    moveq   #1, d1
    rts
.p2:
    moveq   #2, d1
.out:
    rts
    endm


COOP_CODE macro
    cnop    0, 2
COOP_IMAGE:

; ------------------------------------------------------------------------------
; The hooks: one player (SHIM_COOP_2P 0, no setup due) does the replaced work. Coop_Pass's
; two-player path follows it (its bne.s), the other three hooks' theirs.
; ------------------------------------------------------------------------------
Coop_Pass:                          ; the play loop: the ship, the fire input, the objects' pass
    ifd     SHIM_TEST_COOP
    tst.b   SHIM_TEST_CO            ; (the test build: a test's request, Coop_Test)
    bne     Coop_Pass_2P
    tst.w   SHIM_COOP_2P
    bne     Coop_Pass_2P
    else
    tst.w   SHIM_COOP_2P            ; SHIM_COOP_2P and SHIM_COOP_NEW
    bne.s   Coop_Pass_2P
    endif
Coop_Pass_1P:
    jsr     (GAME_ROM+$6CEC).l
    jsr     (GAME_ROM+$70A0).l
    jmp     (GAME_ROM+$45AE).l      ; its rts: to $4270, bra.s $427C

; ------------------------------------------------------------------------------
; Coop_Pass's slow path: a game's first step (SHIM_COOP_NEW's setup bit: the block set up), the
; starts (Coop_Starts: a request in a one-player game is SHIM_COOP_NEW's request bit), a test
; build's request, the join prompt's cells (Coop_Prompt: when due, SHIM_COOP_NEW's prompt bit;
; every two-player step), then the two-player step, or the one-player calls when SHIM_COOP_2P is
; still 0.
; d0-d1/a0-a1 used ($6CEC, $70A0 and $45AE use them too: the play loop keeps nothing there).
; ------------------------------------------------------------------------------
Coop_Pass_2P:
    btst    #COOP_NEW_SETUP, SHIM_COOP_NEW
    beq.s   .set
    bsr     Coop_Setup
.set:
    bsr     Coop_Starts             ; a two-player start, the requests (Task 6)
    ifd     SHIM_TEST_COOP
    bsr     Coop_Test
    endif
    btst    #COOP_NEW_PROMPT, SHIM_COOP_NEW
    bne.s   .prompt                 ; the join prompt due (Coop_Blink, a game's first step: the
    tst.b   SHIM_COOP_2P            ; title's pass asks; Task 7), or two players: every step
    beq     Coop_Pass_1P
.prompt:
    bsr     Coop_Prompt
    tst.b   SHIM_COOP_2P
    beq     Coop_Pass_1P
    moveq   #3, d0                  ; P2's score: its score_add added every fourth step, as
    and.w   GV_FRAME, d0            ; the original adds P1's ($40D4: GV_FRAME & 3 = 0, the
    bne.s   .score                  ; same step's), and printed when it changed (as $40D4's
    move.l  SHIM_COOP_P2+COOP_P2_SCORE_ADD, d0  ; $341E: Coop_Score2)
    beq.s   .score
    add.l   d0, SHIM_COOP_SCORE2
    clr.l   SHIM_COOP_P2+COOP_P2_SCORE_ADD
    btst    #1, SHIM_COOP_IN
    beq.s   .score                  ; (P2 out: its corner the prompt's; Coop_End zeroes its
    bsr     Coop_Score2             ; score_add, so never here)
.score:
    moveq   #1, d0                  ; the first pass: P1 (bit 0 of SHIM_COOP_IN) ...
    moveq   #2, d1                  ; ... then P2 (bit 1)
    btst    #0, GV_FRAME+1
    beq.s   .order
    exg     d0, d1                  ; odd steps: P2 first
.order:
    and.b   SHIM_COOP_IN, d0        ; each 0 when that player is not in
    and.b   SHIM_COOP_IN, d1
    ifd     SHIM_TEST_COOP
    move.b  d0, SHIM_TEST_CO+1      ; (the test build: who runs first)
    bne.s   .trace
    move.b  d1, SHIM_TEST_CO+1
.trace:
    endif
    move.b  d1, -(sp)               ; the second pass's player (0: none)
    tst.b   d0
    beq.s   .second
    tst.b   d1
    seq     SHIM_COOP_TAIL          ; the tail in the first pass when no second one runs
    bsr     Coop_PassOne
.second:
    move.b  (sp)+, d0
    beq.s   .take
    st      SHIM_COOP_TAIL
    bsr     Coop_PassOne
.take:
    btst    #1, SHIM_COOP_IN
    beq.s   .objects
    bsr     Coop_Take1D             ; the tail freed it: P2's ship's slot again
.objects:
    bsr     Coop_Objects            ; the objects' pass, $45AE's
    bra     Coop_End                ; the step's end (its rts: to $4270, bra.s $427C)

; Coop_PassOne: one player's pass, d0.b = its bit in SHIM_COOP_IN (1 P1, 2 P2): P2's context in
; around it. The bomb timer going 0 -> nonzero in its $70A0 ($7324: one bomb at a time, the
; original's test at $72F8) makes this player the bomb's owner (SHIM_COOP_BOMB 1 P1, 2 P2).
; Its $6CEC runs the original's death and respawn ($6D8E-$6E1E): the respawn ($6E06: $6CC4)
; clears the bomb timer too ($6E18), so when the bomb going off is the other player's the timer
; is put back before $70A0 (the tail runs it on: its 64 steps whole); P2's respawn ($6CC4's x
; $2200, invulnerability $100, untouched by the rest of the pass: the dying path leaves at $6E24)
; comes in 32 px right of P1's place (x + $800, as Coop_Join). The game over flag going 0 -> 1 in
; it ($6E30: the death timer at $5C with no ship left) puts this player out (Coop_Out).
; d0-d1/a0-a1 used.
Coop_PassOne:
    ext.w   d0
    move.w  d0, -(sp)               ; COOP_PASS_WHO
    move.w  GV_BOMB, -(sp)          ; COOP_PASS_BOMB
    move.w  GV_GAMEOVER, -(sp)      ; COOP_PASS_GO
    cmpi.b  #2, d0
    bne.s   .in
    bsr     Coop_Exchange           ; P2's context in
.in:
    move.l  SHIM_SPR_PTR, -(sp)     ; the open list's end: $6CEC's ship sprite is set after it
    jsr     (GAME_ROM+$6CEC).l
    movea.l (sp)+, a0
    tst.b   SHIM_COOP_CTX
    beq.s   .p1ship
    bsr     Coop_Ship               ; P2's: its colour (Task 8)
.p1ship:
    tst.w   GV_BOMB
    bne.s   .bombs                  ; (the timer as it was: no respawn, or no bomb)
    move.w  COOP_PASS_BOMB(sp), d0
    beq.s   .bombs
    move.b  SHIM_COOP_BOMB, d1      ; a respawn cut a bomb short: the other player's goes on
    cmp.b   COOP_PASS_WHO+1(sp), d1
    beq.s   .bombs
    move.w  d0, GV_BOMB
.bombs:
    move.w  GV_SHOT_NFREE, SHIM_COOP_NFREE
    tst.w   GV_BOMB
    sne     -(sp)                   ; a bomb going off already
    jsr     (GAME_ROM+$70A0).l
    tst.b   (sp)+
    bne.s   .owner
    tst.w   GV_BOMB
    beq.s   .owner
    move.b  SHIM_COOP_CTX, d0       ; set off in this pass
    addq.b  #1, d0
    move.b  d0, SHIM_COOP_BOMB
.owner:
    tst.b   SHIM_COOP_CTX
    beq.s   .out
    bsr     Coop_Exchange           ; and out again
    cmpi.w  #$100, SHIM_COOP_P2+COOP_BLK_INVULN
    bne.s   .out
    addi.w  #COOP_P2_DX, SHIM_COOP_P2+COOP_P2_X ; P2 respawned in this pass: 32 px right
.out:
    tst.w   COOP_PASS_GO(sp)
    bne.s   .kept
    tst.w   GV_GAMEOVER
    beq.s   .kept
    move.w  COOP_PASS_WHO(sp), d0   ; set in this pass: this player's out
    bsr     Coop_Out
.kept:
    addq.l  #COOP_PASS_SIZE, sp
    rts

; Coop_Ship (Coop_PassOne, P2's pass; Task 8): P2's ship in P2's colour. $6CEC sets the ship's
; sprite through xobj_set ($6FD2: INFO $93A, or a blink's $E3A / $F3A, which stay); xsp.asm recorded
; it in the open list after a0 (SHIM_SPR_PTR before $6CEC; nothing else of $6CEC's is set there):
; an xobj entry with INFO $93A there gets $293A, Neo palette $29 (PAL_P2_BASE + 9; its priority,
; INFO & $3F, the chain's, unchanged). a0-a1 used.
Coop_Ship:
    movea.l SHIM_SPR_PTR, a1
    bra.s   .test
.entry:
    cmpi.w  #$93A, 6(a0)            ; (an entry: x, y, pt, INFO, next: shim.inc SPR_SIZE)
    bne.s   .next
    tst.w   4(a0)
    bpl.s   .next                   ; (not an xobj: SPR_XOBJ, pt's bit 15)
    move.w  #$293A, 6(a0)
.next:
    lea     SPR_SIZE(a0), a0
.test:
    cmpa.l  a1, a0
    blo.s   .entry
    rts

; ------------------------------------------------------------------------------
; Coop_Out (d0.w = 1 | 2; Coop_PassOne, the test build's request 3): that player out of ships.
; Its SHIM_COOP_IN bit cleared (its passes skipped from the next one: no ship, no fire), the
; BIOS's play bookkeeping BIOS_PLAYER_MOD<n> = PLAYER_MOD_OVER, its pending score_add added to
; its score (as $4414 adds P1's at the game over: no print, P1's score is printed at the game
; over or by a buy-in's Coop_Join, P2's by Task 7's HUD); from then on Coop_End zeroes it at
; every step's end (its shots still in flight score nothing). The other player in: the game
; over flag back to 0, the game goes on; none: 1, the original's game over ($4414), and P2's
; score printed again when its corner shows it (a two-player game, not the prompt's: P2 out last,
; or in the step P1 went out last), its last steps' score_add in it. d0-d1/a0-a1 used.
; ------------------------------------------------------------------------------
Coop_Out:
    move.b  d0, d1
    not.b   d1
    and.b   d1, SHIM_COOP_IN
    lea     BIOS_PLAYER_MOD1-1, a0
    move.b  #PLAYER_MOD_OVER, (a0,d0.w)
    lea     GV_SCORE_ADD, a0        ; P1's score_add and score
    cmpi.b  #2, d0
    bne.s   .flush
    lea     SHIM_COOP_P2+COOP_P2_SCORE_ADD, a0  ; P2's (SHIM_COOP_SCORE2)
.flush:
    move.l  (a0), d1
    clr.l   (a0)
    lea     GV_SCORE, a0
    cmpi.b  #2, d0
    bne.s   .add
    lea     SHIM_COOP_SCORE2, a0
.add:
    add.l   d1, (a0)
    moveq   #0, d1                  ; the game over flag: 0 while a player is in
    tst.b   SHIM_COOP_IN
    bne.s   .flag
    moveq   #1, d1
.flag:
    move.w  d1, GV_GAMEOVER
    beq.s   .out                    ; (a player in: the game goes on)
    tst.b   SHIM_COOP_2P
    beq.s   .out                    ; (one player: P2's corner holds nothing)
    btst    #COOP_PR_P2, SHIM_COOP_PROMPT
    bne.s   .out                    ; (P2's corner the prompt's: Coop_Over reprints it)
    bra     Coop_Score2
.out:
    rts

; ------------------------------------------------------------------------------
; Coop_End (Coop_Pass_2P's last part, after the objects' pass; its rts returns to $4270): the
; step's end.
;   * An out player's score_add zeroed (P1: GV_SCORE_ADD; P2: its context's): the hits of its
;     shots still in flight score nothing, and no flush ($40D4, Coop_Pass_2P's) prints over its
;     corner.
;   * The closing: a step that ends with the game over flag set (both out, Coop_Out: the flag's one
;     setter is $6CEC's $6E30; $4200's is unreachable on the Neo Geo, $221F0 is 0 in ROM and
;     _BITSNS's group $E is never down) takes a last look at the requests (Coop_Last: interrupts
;     masked; the BIOS's PLAYER_START sets them from the VBlank, Coop_Start): none, SHIM_COOP_LIVE's
;     "closed" bit (bit 1) is set in that same masked look, so no request is accepted after it and
;     the game over follows; a request for a player out joins that player (Coop_JoinReq, unmasked)
;     and clears the flag: the game goes on.
; Ledger: with SHIM_COOP_2P set, SHIM_COOP_IN 0 never reaches a pass: the step that leaves no
; player in ends with the flag set (Coop_Out), so the play loop leaves for the game over at
; $4414 before another Coop_Pass. d0-d1/a0-a1 used.
; ------------------------------------------------------------------------------
Coop_End:
    move.b  SHIM_COOP_IN, d0
    btst    #0, d0
    bne.s   .p1
    clr.l   GV_SCORE_ADD
.p1:
    btst    #1, d0
    bne.s   .p2
    clr.l   SHIM_COOP_P2+COOP_P2_SCORE_ADD
.p2:
    tst.w   GV_GAMEOVER
    bne.s   .close
    rts
.close:
    ifd     SHIM_TEST_COOP
    bsr     Coop_TestLate           ; (the test build: a VBlank let in first)
    endif
    bsr     Coop_Last
    beq.s   .out                    ; closed: the game over
    bsr     Coop_JoinReq
    clr.w   GV_GAMEOVER
.out:
    rts

; ------------------------------------------------------------------------------
; Coop_Over ($441E, the play loop's game over: $4414 found the flag set; `move.l $22200.l,d0`, the
; score, replaced; once a game). Two players: Coop_End's last look closed the joins (a request
; there would have kept the game on): the instruction alone. One player (P1's last ship, $6E30):
; the game's last look (Coop_Last; Coop_Pass's one test sees a request only at a step's start, and
; the step's VBlank falls after its Coop_Pass: one accepted there in this step, its credit taken,
; must not be lost; tests/neo/coop.lua join_at_last_death): none, the joins closed and the
; original's game over; P2's request (accepted before the look: P1's requests need two players)
; puts P1 out (Coop_Out: lives 0, its death timer at $5C, as a two-player game's out
; player; BIOS_PLAYER_MOD1 game over), P2 in (Coop_Join), the flag back to 0, and the loop goes on
; at $40C6 (as $4414's beq.w would). The game over (both cases): the join prompt's cells cleared
; (Coop_Prompt: the joins closed), in the step it is decided; two players: the corner that was the
; prompt's (the player out first) gets its label and its final score again (Coop_Label: the
; original's $4446 that follows reprints P1's digits alone, final review M1), so both scores stay
; on the game over. d0-d1/a0-a1 used (the loop keeps nothing there across $4414).
; ------------------------------------------------------------------------------
Coop_Over:
    tst.b   SHIM_COOP_2P
    bne.s   .over
    ifd     SHIM_TEST_COOP
    bsr     Coop_TestLate
    endif
    bsr     Coop_Last
    bne.s   .join
.over:
    move.b  SHIM_COOP_PROMPT, -(sp) ; the corners the prompt's
    bsr     Coop_Prompt             ; the joins closed: the join prompt's cells cleared (Task 7)
    move.b  (sp)+, d0
    tst.b   SHIM_COOP_2P
    beq.s   .score                  ; (one player: P2's corner held no score)
    btst    #COOP_PR_P2, d0
    beq.s   .p1
    move.b  d0, -(sp)
    bsr     Coop_Exchange           ; P2's label and final score at its place
    move.l  SHIM_COOP_SCORE2, d0
    bsr     Coop_Label
    bsr     Coop_Exchange
    move.b  (sp)+, d0
.p1:
    btst    #COOP_PR_P1, d0
    beq.s   .score
    move.l  GV_SCORE, d0            ; P1's (out first: its score final since, Coop_Out)
    bsr     Coop_Label
.score:
    move.l  GV_SCORE, d0            ; the replaced instruction
    rts
.join:
    moveq   #1, d0
    bsr     Coop_Out
    moveq   #2, d0
    bsr     Coop_Join
    clr.w   GV_GAMEOVER
    addq.l  #4, sp                  ; (its return to $4424 dropped)
    jmp     COOP_LOOP

; ------------------------------------------------------------------------------
; Coop_Start (bios.asm PLAYER_START, in the VBlank inside SYSTEM_IO: a START anywhere but the demo
; and the waiting title): a join or a buy-in, through the BIOS's start handshake. Accepted, its bit
; is left in BIOS_START_FLAG (the BIOS takes one of P1's credits for it, MVS without Free Play: the
; probe, PLAYER_START's header) and it is a request: its SHIM_COOP_REQ bit, and SHIM_COOP_NEW's
; request bit, which Coop_Pass's one test sees in a one-player game. The next Coop_Pass serves it
; (Coop_Starts), or the game over's last look (Coop_End; one player, Coop_Over), which closes the
; joins: so a credit taken always brings its ship in. Joins are open in the title mode's game once
; it is set up and until its last look (SHIM_BIOS_MODE the title's, SHIM_COOP_LIVE exactly 1): not
; in the loader, CONFIG, KAKUSI, the title's passes, the game over after its look, nor a resume's
; settle frames. Then:
;   * P2's START (bit 1): P2 not in and not asked for already: P2 joins a one-player game, or buys
;     back in;
;   * P1's START (bit 0): a two-player game (SHIM_COOP_2P) with P1 out and not asked for already:
;     P1 buys back in (P2 in; or in the step both went out, before the last look);
;   * where credits are counted, as many as there are credits for, P2's first (with no credit in,
;     the BIOS calls for neither START).
; Anything else is refused (its bit cleared: no credit taken). Every register kept.
; ------------------------------------------------------------------------------
Coop_Start:
    movem.l d0-d2, -(sp)
    moveq   #0, d1                  ; the starts accepted
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .take
    cmpi.b  #1, SHIM_COOP_LIVE
    bne.s   .take                   ; joins not open
    jsr     Bios_Credits
    move.w  d0, d2                  ; the credits (BCD: compared as a binary count up to 2), -1 none
    move.b  SHIM_COOP_IN, d0        ; counted
    or.b    SHIM_COOP_REQ, d0       ; in, or asked for (a request's bit goes into SHIM_COOP_IN
    tst.b   SHIM_COOP_START2        ; under Coop_Take's mask, and Coop_Join's at its entry), or
    beq.s   .asked                  ; joining from the title's two-player start (SHIM_COOP_START2
    bset    #1, d0                  ; set until that join is done: Coop_Starts)
.asked:
    btst    #1, BIOS_START_FLAG
    beq.s   .p1
    btst    #1, d0
    bne.s   .p1
    tst.w   d2
    beq.s   .p1                     ; no credit (counted)
    bmi.s   .p2
    subq.w  #1, d2
.p2:
    bset    #1, d1
.p1:
    btst    #0, BIOS_START_FLAG
    beq.s   .take
    tst.b   SHIM_COOP_2P
    beq.s   .take
    btst    #0, d0
    bne.s   .take
    tst.w   d2
    beq.s   .take
    bset    #0, d1
.take:
    move.b  d1, BIOS_START_FLAG     ; the accepted (0: refused)
    beq.s   .out
    or.b    d1, SHIM_COOP_REQ
    bset    #COOP_NEW_REQ, SHIM_COOP_NEW
.out:
    movem.l (sp)+, d0-d2
    rts

; ------------------------------------------------------------------------------
; Coop_Starts (Coop_Pass_2P, at a step's start, after the setup): a two-player start chosen at the
; title (SHIM_COOP_START2: the game's first step; P1 is in from Coop_Setup) joins P2; then the
; requests Coop_Start accepted (their credits taken), each player's join. d0-d1/a0-a1 used.
; Coop_JoinReq: d0.b's players (bit 0 P1, bit 1 P2) join (Coop_Join). d0-d1/a0-a1 used.
; ------------------------------------------------------------------------------
Coop_Starts:
    tst.b   SHIM_COOP_START2
    beq.s   .req
    ifd     SHIM_TEST_COOP
    moveq   #5, d1                  ; (the test build: a hold, Coop_TestHold)
    bsr     Coop_TestHold
    endif
    moveq   #2, d0
    bsr     Coop_Join
    clr.b   SHIM_COOP_START2        ; (after the join: P2 asked for or in throughout, Coop_Start)
.req:
    tst.b   SHIM_COOP_REQ           ; (one after this: the next step's, or the last look's)
    bne.s   .take
    tst.b   SHIM_COOP_P2KEY         ; (bit 7, COOP_KEY_SEEN: a P2 START the BIOS dropped)
    bpl.s   Coop_JoinOut
.take:
    bsr.s   Coop_Req
    beq.s   Coop_JoinOut
Coop_JoinReq:
    move.b  d0, -(sp)
    btst    #0, d0
    beq.s   .two
    moveq   #1, d0
    bsr     Coop_Join               ; P1 buys in
.two:
    btst    #1, (sp)+
    beq.s   Coop_JoinOut
    moveq   #2, d0
    bra     Coop_Join               ; P2 joins
Coop_JoinOut:
    rts

; Coop_Req / Coop_Last: the requests of players out taken, d0.b (Z: none), SHIM_COOP_REQ and
; SHIM_COOP_NEW's request bit cleared, interrupts masked around it (Coop_Start sets them from the
; VBlank). A P2 START the BIOS dropped (COOP_KEY_SEEN, Coop_Blink: the US BIOS) is taken there too,
; its credit spent then (Coop_Spend). The players taken are in SHIM_COOP_IN from that same masked
; moment (final review I2: a START between it and the join's end, which prints for a tenth of a
; frame, finds them in, so no second credit is taken for a request this look would drop); the
; caller joins them at once. Coop_Last (the game over's last look): with none, SHIM_COOP_LIVE's
; closed bit set in that same masked moment, so Coop_Start accepts nothing after it. d0-d1 used.
Coop_Req:
    moveq   #0, d1
    bra.s   Coop_Take
Coop_Last:
    moveq   #2, d1                  ; (SHIM_COOP_LIVE's bit 1)
Coop_Take:
    move.w  sr, -(sp)
    move.w  #$2700, sr
    move.b  SHIM_COOP_IN, d0
    not.b   d0
    and.b   SHIM_COOP_REQ, d0
    andi.b  #3, d0
    bclr    #COOP_KEY_SEEN, SHIM_COOP_P2KEY
    beq.s   .bios
    bsr.s   Coop_Spend              ; P2's START the BIOS dropped: its credit here
.bios:
    or.b    d0, SHIM_COOP_IN
    clr.b   SHIM_COOP_REQ
    bclr    #COOP_NEW_REQ, SHIM_COOP_NEW
    tst.b   d0
    bne.s   .req
    or.b    d1, SHIM_COOP_LIVE
.req:
    move.w  (sp)+, sr
    tst.b   d0
    rts

; Coop_Spend (Coop_Take, masked: SYSTEM_IO's coin count does not run in between): the US BIOS
; fallback's join (the spec's "Starting and credits": the game reads P2's START itself where the
; BIOS will not let it spend P1's credits, Coop_Blink). P2 not in, not asked for through the BIOS
; (d0's bit 1), the joins open: one of P1's credits taken (title.asm Title_Spend: CREDIT_CHECK, then
; CREDIT_DOWN), and then d0's bit 1 set, so the join follows in this same step (none in: nothing).
; d0's bit 1 set when taken; every other register kept.
Coop_Spend:
    btst    #1, d0
    bne.s   .out                    ; (the BIOS's request too: that credit is the one)
    btst    #1, SHIM_COOP_IN
    bne.s   .out
    cmpi.b  #1, SHIM_COOP_LIVE
    bne.s   .out
    tst.b   BIOS_CREDITS
    beq.s   .out                    ; (none in: no BIOS call)
    jsr     Title_Spend             ; (Z: taken)
    bne.s   .out
    bset    #1, d0
.out:
    rts

; ------------------------------------------------------------------------------
; Coop_Join (d0.w = 1 | 2; the starts, Coop_Starts; the last looks; the test build's requests):
; that player comes in with a new game's stock, in its own context (P2's exchanged in around it),
; through the original's game start [V]:
;   * $6C4A: lives 2, power 0, the shot parameters ($776A), bombs 3;
;   * $6CC4: x $2200, y $5000, invulnerability $100: the ship rises in from below as at a
;     respawn; P2's x + $800 (32 px right of P1's place);
;   * $76E8 and $7818: the HUD's lives and bombs (P2's: Coop_Text8 / Coop_Text16's places);
;   * the label and the score 0 printed as the game's start prints them ($4094-$40B8: $33E8(1,
;     1, "SC 0x"), $341E(6, 1, score, 7 digits); P2's in its context: its places): the corner's
;     row 1 whole again, over the join prompt's cells (its SHIM_COOP_PROMPT bit cleared first:
;     Coop_Prompt leaves the corner to the HUD);
;   * $6C66's other writes: the burst counter $221A2 -1, $221A4 0, the death timer 0; the stored
;     pad bytes $FF (nothing held before);
;   * score_add 0 and the score 0 (P1: GV_SCORE; P2: SHIM_COOP_SCORE2).
; Not $6C66's $703E (the shot reset: the shots in flight are the other player's) nor its bomb
; timer clear (the bomb going off may be the other's). Its SHIM_COOP_IN bit first (final review
; I2), then all that; SHIM_COOP_2P = 1, BIOS_PLAYER_MOD<n> = PLAYER_MOD_PLAYING; P2: Coop_P2Enter
; (slot $1D its ship's). The block set up first if this game's setup has not run (SHIM_COOP_LIVE
; bit 0 clear: a join before the game's first step since a resume or a title pass). d0-d1/a0-a1
; used.
; ------------------------------------------------------------------------------
Coop_Join:
    btst    #0, SHIM_COOP_LIVE
    bne.s   .live
    bsr     Coop_Setup
.live:
    or.b    d0, SHIM_COOP_IN        ; in from here (final review I2: a START while it prints finds
                                    ; this player in, so Coop_Start takes no credit for it; nothing
                                    ; below reads SHIM_COOP_IN)
    ifd     SHIM_TEST_COOP
    moveq   #6, d1                  ; (the test build: a hold, Coop_TestHold)
    bsr     Coop_TestHold
    endif
    move.w  d0, -(sp)               ; the player
    move.b  d0, d1                  ; its corner no longer the join prompt's (the HUD below
    not.b   d1                      ; covers its row-1 cells)
    and.b   d1, SHIM_COOP_PROMPT
    cmpi.w  #2, d0
    bne.s   .in
    bsr     Coop_Exchange           ; P2's context in
.in:
    jsr     (GAME_ROM+$6C4A).l
    jsr     (GAME_ROM+$6CC4).l
    jsr     (GAME_ROM+$76E8).l
    jsr     (GAME_ROM+$7818).l
    moveq   #0, d0
    bsr     Coop_Label              ; "SC 0x", then the score 0
    move.w  #-1, GV_PLAYER_BLK+COOP_BLK_BURST
    clr.w   GV_PLAYER_BLK+COOP_BLK_BURST+2
    clr.w   GV_PLAYER_BLK+COOP_BLK_DEATH
    moveq   #-1, d0
    move.l  d0, GV_PAD
    clr.l   GV_SCORE_ADD
    tst.b   SHIM_COOP_CTX
    beq.s   .p1
    addi.w  #COOP_P2_DX, GV_PLAYER_Y+2
    clr.l   SHIM_COOP_SCORE2
    bsr     Coop_Exchange           ; and out again
    bsr     Coop_P2Enter
    bra.s   .on
.p1:
    clr.l   GV_SCORE
.on:
    move.w  (sp)+, d0
    move.b  #1, SHIM_COOP_2P
    lea     BIOS_PLAYER_MOD1-1, a0
    move.b  #PLAYER_MOD_PLAYING, (a0,d0.w)
    rts

; Coop_Label: the corner's label and score in the context that is in (P2's: Coop_Text8's places),
; as the game's start prints them ($4094-$40B8): $33E8(1, 1, "SC 0x") [V], then $341E(6, 1, d0.l,
; 7 digits). d0-d1/a0-a1 used.
Coop_Label:
    move.l  d0, -(sp)
    pea     (GAME_ROM+$3F72).l
    pea     (1).w
    pea     (1).w
    jsr     (GAME_ROM+$33E8).l
    lea     12(sp), sp
    move.l  (sp)+, d0
    pea     (7).w
    move.l  d0, -(sp)
    pea     (1).w
    pea     (6).w
    jsr     (GAME_ROM+$341E).l
    lea     16(sp), sp
    rts

; ------------------------------------------------------------------------------
; Coop_NoneLeft (sprites.asm Spr_Rooms, during P1's last ship's death: GV_LIVES 0, its death
; timer running): Z set when no player is left after it, so row 16 keeps its places for GAME
; OVER. One player: always. Two (SHIM_COOP_2P): P2 not in, or on its own last ship's death
; (lives 0, death timer running). (P1 out keeps lives 0 and its death timer at $5C: P1 in that
; state while P2 plays is not a game over.) Every register kept.
; ------------------------------------------------------------------------------
Coop_NoneLeft:
    tst.b   SHIM_COOP_2P
    beq.s   .out                    ; (Z)
    btst    #1, SHIM_COOP_IN
    beq.s   .out                    ; (Z)
    tst.w   SHIM_COOP_P2+COOP_BLK_LIVES
    bne.s   .out                    ; (not Z)
    tst.w   SHIM_COOP_P2+COOP_BLK_DEATH
    eori.b  #4, ccr                 ; Z: dying
.out:
    rts

; ------------------------------------------------------------------------------
; Coop_Objects (Coop_Pass_2P's last call, in $45AE's place: its rts returns to $4270): $45AE's
; loop -- objects 0-127 (GV_OBJECTS, $80 apart), each one's handler $18(obj), 0 skipped, called
; with the object pushed -- with each object's target. The handlers read the ship from the globals
; (y/x $27892: ~70 aimed shots through $1A04, the bullets' and the items' proximity tests), so for
; an object whose target is P2 the loop swaps P2's into the globals before its handler runs
; (SHIM_COOP_SWAP the kind, Coop_SwapTo; kept in for the next object if its target is P2 too, out
; again for one whose target is P1 and at the loop's end):
;   * a bullet ($AE08, $AFB8, $B196, $B354: each tests the ship's place, ±$100 x ±$200, and calls
;     the kill $6FE2): the nearer ship in SHIM_COOP_IN every step, by max(|dx|, |dy|/2);
;     COOP_SWAP_PART: the ship's y and x, the death timer and invulnerability (two longs; $6FE2
;     tests and writes those two);
;   * an item ($D440: five proximity tests, then the effect block $D8F2-$DD76: power, bombs, lives,
;     invulnerability, the bonus to score_add at $DA0C / $DB84 / $DD3A, the HUD): the same choice;
;     COOP_SWAP_ALL: Coop_Exchange, so the effect is P2's (and its HUD, SHIM_COOP_CTX) and stays
;     P2's when the exchange back stores it;
;   * anything else aims: its target is chosen when it is first seen (the handler's low word not
;     the one in SHIM_COOP_TGT[index]: a new object, or a new state) and again on steps with
;     (GV_FRAME + index) & 15 = 0, the nearer ship by |dx| + |dy| of those in SHIM_COOP_IN and
;     alive (death timer 0 as the loop began), the last kept when none is; SHIM_COOP_TGT[index] =
;     the low word, bit 15 P2. COOP_SWAP_PART too: no handler reads the player block but through
;     the ship's routines ($6CC4-$78B2 [V]), and a bullet such a handler spawns and runs at once
;     (a spawner calls a new object's handler when its slot is below its parent's) tests and kills
;     the ship its parent aims at.
; Hits inside a swapped handler ($46B4 / $47BE -> $75EA -> Coop_Hit) undo the swap first
; (Coop_Hit_Swap: SHIM_COOP_SWAP bit 7 while undone), so every kill and every score sees the
; globals as outside the loop (ruling R7).
; Outside the loop the globals keep P1's place: the play loop's stage scripts ($4976 at $4248:
; acchoh's spawns above the ship, $78C2 / $8152 / $8E2C, and the spawners they call at once,
; $BE24 / $C072 / $C5BE / $DF7C / $1273E, aim at P1 as their objects appear), the ship code
; ($6CC4-$78B2: each pass its player's), the view (view.asm: P1's from the globals, P2's from its
; context: Coop_View).
; Cost (its own, the handlers' time left out; a 3,000-step MAME run, the record's weave, against
; $45AE's in one player): 9,500 cycles a step at the median, 13,700 at the 90th centile, 18,700
; at the 99th, where $45AE's are 6,200 / 6,400 / 6,500 (a frame: 200,000).
; ------------------------------------------------------------------------------
Coop_Objects:
    movem.l d3-d7/a3-a4, -(sp)      ; (the handlers keep d3-d7/a3-a6: C's, as $45AE's d3/a3)
    lea     GV_OBJECTS, a3
    lea     SHIM_COOP_TGT, a4       ; (a4)+: each object's word
    moveq   #127, d3                ; the objects left - 1: the index is 127 - d3
    move.w  GV_FRAME, d4
    addi.w  #127, d4                ; (frame + index) & 15 = (d4 - d3) & 15
    move.l  GV_PLAYER_Y, d6         ; P1's y:x, P2's: no handler moves a ship (the ship code
    move.l  SHIM_COOP_P2+COOP_P2_Y, d7  ; alone writes them, $6CD2-$6EF2 [V])
    moveq   #0, d5
    move.b  SHIM_COOP_IN, d5        ; bits 0-7: the ships a bullet or an item may reach (bit 0
    move.b  d5, -(sp)               ; P1, 1 P2); bits 8-15: those an aim may choose (alive too)
    move.w  (sp)+, d1
    tst.w   GV_PLAYER_BLK+COOP_BLK_DEATH
    beq.s   .alive1
    bclr    #8, d1
.alive1:
    tst.w   SHIM_COOP_P2+COOP_BLK_DEATH
    beq.s   .alive2
    bclr    #9, d1
.alive2:
    clr.b   d1
    or.w    d1, d5
.next:
    move.l  $18(a3), d0
    beq.s   .none
    movea.l d0, a0                  ; the handler
    cmpa.l  #COOP_BULLET0, a0       ; (the bullets' and the item's lie in $AE08-$D440)
    blo.s   .aims
    cmpa.l  #COOP_ITEM, a0
    bhi.s   .aims
    beq.s   .item
    cmpa.l  #COOP_BULLET0, a0
    beq.s   .bullet
    cmpa.l  #COOP_BULLET1, a0
    beq.s   .bullet
    cmpa.l  #COOP_BULLET2, a0
    beq.s   .bullet
    cmpa.l  #COOP_BULLET3, a0
    beq.s   .bullet
.aims:
    move.w  (a4), d1                ; it aims: first seen (bits 0-14 not its handler's)?
    eor.w   d0, d1
    add.w   d1, d1
    bne.s   .choose
    move.w  d4, d1                  ; its re-choice step?
    sub.w   d3, d1
    andi.w  #15, d1
    bne.s   .chosen
.choose:
    move.w  d5, d1
    lsr.w   #8, d1                  ; the ships alive
    bsr     Coop_NearSum
    move.w  a0, d0
    andi.w  #$7FFF, d0              ; the handler's low word
    subq.b  #1, d1
    beq.s   .store                  ; P1
    bcc.s   .p2t                    ; P2
    move.w  (a4), d1                ; none alive: the last target kept
    andi.w  #$8000, d1
    or.w    d1, d0
    bra.s   .store
.p2t:
    ori.w   #$8000, d0
.store:
    move.w  d0, (a4)
.chosen:
    tst.w   (a4)+
    bpl.s   .p1
    moveq   #COOP_SWAP_PART, d1
    bra.s   .p2
.none:
    clr.w   (a4)+                   ; (a new object here is first seen)
    lea     $80(a3), a3
    dbra    d3, .next
    bra.s   .done
.item:
    movea.w #COOP_SWAP_ALL, a1
    bra.s   .reach
.bullet:
    movea.w #COOP_SWAP_PART, a1
.reach:
    clr.w   (a4)+
    move.b  d5, d1                  ; the ships in
    bsr     Coop_NearMax
    subq.b  #2, d1
    bne.s   .p1
    move.w  a1, d1
    bra.s   .p2
.p1:
    moveq   #0, d1                  ; P1 the target: no swap
.p2:
    cmp.b   SHIM_COOP_SWAP, d1      ; P2's: its part (or all) in (kept in from the last object
    beq.s   .call                   ; whose target was P2 too: one swap a change of target)
    bsr     Coop_SwapTo
.call:
    move.l  a3, -(sp)
    jsr     (a0)
    addq.l  #4, sp
.step:
    lea     $80(a3), a3
    dbra    d3, .next
.done:
    moveq   #0, d1                  ; the globals P1's again
    bsr     Coop_SwapTo
    movem.l (sp)+, d3-d7/a3-a4
    rts

; Coop_NearSum / Coop_NearMax (Coop_Objects: d6 P1's y:x, d7 P2's): of the ships in d1.b (bit 0
; P1, bit 1 P2), the one nearer object a3 (its x, then y), by |dx| + |dy| (the aim) or by
; max(|dx|, |dy|/2) (the bullets' window is twice as tall as wide): d1.b 1 P1 (a tie too), 2 P2,
; 0 none. d0-d2 used.
Coop_NearSum:
    COOP_NEAR 0
Coop_NearMax:
    COOP_NEAR 1

; Coop_SwapTo: the globals from SHIM_COOP_SWAP's swap to d1.b's (0 none): the one in out, the new
; one in. Every register kept.
Coop_SwapTo:
    tst.b   SHIM_COOP_SWAP
    beq.s   .in
    bsr.s   Coop_Swap
.in:
    move.b  d1, SHIM_COOP_SWAP
    beq.s   .out
    bsr.s   Coop_Swap
.out:
    rts

; Coop_Swap: SHIM_COOP_SWAP's swap, run twice the identity: COOP_SWAP_ALL Coop_Exchange (P2's
; whole context, SHIM_COOP_CTX); COOP_SWAP_PART the ship's y/x and its death timer and
; invulnerability, P2's <-> the globals. Every register kept.
Coop_Swap:
    btst    #COOP_SWAP_ALL_BIT, SHIM_COOP_SWAP
    bne     Coop_Exchange
    move.l  d0, -(sp)
    move.l  GV_PLAYER_Y, d0
    move.l  SHIM_COOP_P2+COOP_P2_Y, GV_PLAYER_Y
    move.l  d0, SHIM_COOP_P2+COOP_P2_Y
    move.l  GV_PLAYER_BLK+COOP_BLK_DEATH, d0
    move.l  SHIM_COOP_P2+COOP_BLK_DEATH, GV_PLAYER_BLK+COOP_BLK_DEATH
    move.l  d0, SHIM_COOP_P2+COOP_BLK_DEATH
    move.l  (sp)+, d0
    rts

; ------------------------------------------------------------------------------
; The other three hooks: one player does the replaced work.
; ------------------------------------------------------------------------------
Coop_Tail:                          ; move.w $2B8AC.l,d0 (the bomb timer; beq.w $757C follows)
    tst.b   SHIM_COOP_2P
    bne.s   Coop_Tail_2P
    move.w  GV_BOMB, d0
    rts

Coop_ShipSlot:                      ; pea $1F.w (the ship sprite call's first argument)
    tst.b   SHIM_COOP_2P
    bne.s   Coop_ShipSlot_2P
    move.l  (sp), -(sp)             ; the return address one long down,
    move.l  #$1F, 4(sp)             ; the pea's long where it was
    rts

Coop_Hit:                           ; cmp.w #$1F,d3 (bne.b $76B8 follows)
    tst.b   SHIM_COOP_2P
    bne.s   Coop_Hit_2P
    cmp.w   #$1F, d3
    rts

; ------------------------------------------------------------------------------
; Their two-player paths (SHIM_COOP_2P set).
; ------------------------------------------------------------------------------
; Coop_Tail_2P: the shots' owner first (Coop_Own), then $70A0's tail in the step's last pass
; alone (it rebuilds the free stack); in the others, the epilogue at once (the return address
; dropped: $70A0's frame on a6 restores its registers and returns).
Coop_Tail_2P:
    bsr     Coop_Own
    tst.b   SHIM_COOP_TAIL
    beq.s   .skip
    move.w  GV_BOMB, d0
    rts
.skip:
    addq.l  #4, sp
    jmp     GAME_TAIL_SKIP

; Coop_ShipSlot_2P: the ship's collision slot, P2's ($1D) while its context is in, else P1's ($1F)
Coop_ShipSlot_2P:
    move.l  (sp), -(sp)
    move.l  #$1F, 4(sp)
    tst.b   SHIM_COOP_CTX
    beq.s   .p1
    move.l  #COOP_P2_SHIP, 4(sp)
.p1:
    rts

; Coop_Hit_2P ($765E: d3 the slot $75EA(slot) was given, a6 its frame, the hook's return on the
; stack; $45AE's objects call it, P1's context in): P1's hits (its ship $1F, its shots, its bomb)
; go back to the original's code with the cmp's CCR ($7664: P1's kill; $76B8: the damage, $60 or
; P1's); P2's (Coop_HitP2) leave through $75EA's epilogue (the hook's return dropped) with d0 the
; damage. A hit inside a handler the object loop runs with P2's part or context swapped in
; (SHIM_COOP_SWAP, Coop_Objects) is Coop_Hit_Swap's.
Coop_Hit_2P:
    tst.b   SHIM_COOP_SWAP
    bgt.s   Coop_Hit_Swap           ; (a swap in; bit 7, undone already: a nested hit, as none)
    bsr.s   Coop_HitP2
    beq.s   Coop_HitOut
    cmp.w   #$1F, d3
    rts
Coop_HitOut:
    addq.l  #4, sp
    jmp     GAME_HIT_OUT

; Coop_Hit_Swap (ruling R7): the loop's swap undone first (Coop_Swap; SHIM_COOP_SWAP bit 7 while
; it is), so the globals hold P1's context as Coop_HitP2 expects; P1's hits done here, not by the
; original's code (the swap is done again before $75EA returns): $1F the original's kill ($6FE2:
; $7664's tests and writes, the explosion at P1's ship), d0 $60 for the bomb, else P1's damage
; ($76C2). Leaves through $75EA's epilogue.
Coop_Hit_Swap:
    bsr     Coop_Swap
    bset    #COOP_SWAP_UNDONE, SHIM_COOP_SWAP
    bsr.s   Coop_HitP2
    beq.s   .again                  ; P2's: done
    moveq   #COOP_BOMB_DAMAGE, d0
    cmpi.w  #COOP_BOMB_SLOT, d3
    beq.s   .again
    cmpi.w  #$1F, d3
    bne.s   .damage
    jsr     GAME_KILL               ; P1's ship
.damage:
    move.w  GV_PLAYER_BLK+COOP_BLK_DAMAGE, d0
    ext.l   d0
.again:
    bclr    #COOP_SWAP_UNDONE, SHIM_COOP_SWAP
    bsr     Coop_Swap
    bra.s   Coop_HitOut

; Coop_HitP2 (P1's context in the globals): a hit of P2's, Z set and d0 the damage, or P1's, Z
; clear:
;   * $1D while P2 is in, P2's ship: the original's kill ($6FE2) with P2's context in (its
;     invulnerability and death timer, the explosion at P2's ship), d0 P2's damage (a ship that
;     rams scores as a shot, as P1's);
;   * a shot whose SHIM_COOP_OWN bit is set: d0 P2's damage;
;   * the bomb when SHIM_COOP_BOMB is P2's: d0 $60.
; Then, when $46B4 is the caller (4(a6), its return address, in $46B4-$47BD), the damage x 8 is
; moved from score_add (P1's, in the globals) to P2's: $46B4 adds its sum x 8 at its end ($47B2),
; so P1's score gets none of it. $47BE's callers drop the sum (no score). d1 used ($75EA's
; callers keep nothing there: C's scratch).
Coop_HitP2:
    cmpi.w  #$1F, d3
    beq.s   .p1                     ; P1's ship
    cmpi.w  #COOP_BOMB_SLOT, d3
    beq.s   .bomb
    cmpi.w  #COOP_P2_SHIP, d3
    bne.s   .shot
    btst    #1, SHIM_COOP_IN
    beq.s   .shot                   ; (P2 not in: $1D a shot's)
    bsr     Coop_Exchange           ; P2's ship hit: its kill, P2's context in
    jsr     GAME_KILL
    bsr     Coop_Exchange
    bra.s   .p2
.shot:
    move.l  SHIM_COOP_OWN, d0
    btst    d3, d0
    beq.s   .p1
.p2:
    move.w  SHIM_COOP_P2+COOP_BLK_DAMAGE, d0
    ext.l   d0                      ; (as $76C2)
    bra.s   .score
.bomb:
    cmpi.b  #2, SHIM_COOP_BOMB
    bne.s   .p1
    moveq   #COOP_BOMB_DAMAGE, d0
.score:
    move.l  4(a6), d1               ; $75EA's caller
    cmpi.l  #GAME_HIT_SUM, d1
    blo.s   .out
    cmpi.l  #GAME_HIT_SUM_END, d1
    bhs.s   .out
    move.l  d0, d1
    asl.l   #3, d1
    sub.l   d1, GV_SCORE_ADD
    add.l   d1, SHIM_COOP_P2+COOP_P2_SCORE_ADD
.out:
    moveq   #0, d1                  ; Z: P2's
    rts
.p1:
    moveq   #1, d1
    rts

; Coop_Own ($70A0's tail, Coop_Tail_2P): the shots' owner. The fire part pops the free-shot stack
; from its top ($7156, $71C0, $7244: subq the count, then the entry at it), so the slots this
; pass took are the entries from GV_SHOT_NFREE up to SHIM_COOP_NFREE (the count as $70A0 began):
; each one's SHIM_COOP_OWN bit set in P2's pass, cleared in P1's. P2's new shots also get bit 13
; of their attribute word (+6, the fire part's $536 or table word: bit 13 never set; Task 8): its
; palette PAL_P2_BASE + block from its first list on (the tail draws it after this), kept while it
; flies (nothing writes the word again before the next shot in its slot). d0-d1/a0 used ($70A0's
; tail sets each before it reads it), d2/a1 kept.
Coop_Own:
    move.w  SHIM_COOP_NFREE, d1
    sub.w   GV_SHOT_NFREE, d1       ; the slots popped (the bomb pops none)
    ble.s   .owned                  ; (never fewer: a guard)
    movem.l d2/a1, -(sp)
    move.w  GV_SHOT_NFREE, d0
    add.w   d0, d0
    lea     GV_SHOT_FREE, a0
    adda.w  d0, a0
    lea     GV_SHOTS+6, a1          ; (the shots' attribute words: slot x COOP_SHOT_SIZE on)
    move.l  SHIM_COOP_OWN, d0
    subq.w  #1, d1
.own:
    move.w  (a0)+, d2               ; a slot, 0-$1D
    bclr    d2, d0
    tst.b   SHIM_COOP_CTX
    beq.s   .p1
    bset    d2, d0                  ; P2's
    lsl.w   #COOP_SHOT_LOG2, d2
    bset    #13-8, (a1,d2.w)        ; its attribute word's bit 13: P2's palette
.p1:
    dbra    d1, .own
    move.l  d0, SHIM_COOP_OWN
    movem.l (sp)+, d2/a1
.owned:
    rts

; ------------------------------------------------------------------------------
; Coop_P2Enter (P2's entry, a join): collision slot $1D becomes P2's ship's. A shot live there is
; retired (its y, the shots' active word, cleared: the tail frees it and Coop_Pass takes it), the
; slot taken off the free stack if it is on it. d0/a0 used.
; Coop_Take1D: slot $1D off the free-shot stack. The tail rebuilds the stack from slot $1D down
; ($7588 moveq #$1D,d3; $75CA: each free one pushed), so a free $1D is its entry 0 (the bottom,
; popped last): the entries above it move down one. d0/a0 used.
; ------------------------------------------------------------------------------
Coop_P2Enter:
    clr.w   GV_SHOTS+COOP_P2_SHIP*COOP_SHOT_SIZE+2
Coop_Take1D:
    move.w  GV_SHOT_NFREE, d0
    beq.s   .out
    cmpi.w  #COOP_P2_SHIP, GV_SHOT_FREE
    bne.s   .out
    subq.w  #1, d0
    move.w  d0, GV_SHOT_NFREE
    lea     GV_SHOT_FREE, a0
    bra.s   .next
.down:
    move.w  2(a0), (a0)+
.next:
    dbra    d0, .down
.out:
    rts

; ------------------------------------------------------------------------------
; Coop_Setup (a game's first step, SHIM_COOP_NEW set): the block cleared but SHIM_COOP_PAD and
; SHIM_COOP_START2 -- SHIM_COOP_2P with it (ruling R1: every game starts on the pass-through; a
; two-player start pending, Task 6, joins P2 again), SHIM_COOP_NEW but its join prompt request
; (Task 7), SHIM_COOP_PROMPT (no prompt cell: the title's clear left none) --, P1 in, the block
; set up for this game.
; Every register kept.
; ------------------------------------------------------------------------------
Coop_Setup:
    movem.l d0/a0, -(sp)
    clr.b   SHIM_COOP_2P
    andi.b  #1<<COOP_NEW_PROMPT, SHIM_COOP_NEW  ; (the join prompt's request kept: the title's
                                    ; pass sets it, the game's first step serves it after this)
    lea     SHIM_COOP_CLR, a0
    move.w  #(SHIM_COOP_END-SHIM_COOP_CLR)/2-1, d0
.clr:
    clr.w   (a0)+
    dbra    d0, .clr
    move.b  #1, SHIM_COOP_IN
    move.b  #1, SHIM_COOP_LIVE
    movem.l (sp)+, d0/a0
    rts

; ------------------------------------------------------------------------------
; Coop_Exchange: SHIM_COOP_P2's 40 bytes <-> the game's four runs (the player block, the ship's y
; and x, the stored pad bytes, score_add), SHIM_COOP_CTX and SHIM_COOP_PAD's P2 bit toggled. Run
; twice it is the identity (nested exchanges round-trip). Every register and the CCR kept.
; ------------------------------------------------------------------------------
Coop_Exchange:
    move.w  sr, -(sp)
    movem.l d0/a0-a1, -(sp)
    lea     SHIM_COOP_P2, a0
    lea     GV_PLAYER_BLK, a1
    COOP_SWAP COOP_P2_Y/4
    lea     GV_PLAYER_Y, a1
    COOP_SWAP 1
    lea     GV_PAD, a1
    COOP_SWAP 1
    lea     GV_SCORE_ADD, a1
    COOP_SWAP 1
    eori.b  #1, SHIM_COOP_CTX
    eori.b  #COOP_PAD_P2, SHIM_COOP_PAD
    movem.l (sp)+, d0/a0-a1
    move.w  (sp)+, ccr
    rts

; ------------------------------------------------------------------------------
; Coop_Text8 / Coop_Text16 (text.asm Shim_Text8 / Shim_Text16 while P2's context is in): the cell
; (d0.w x, d1.w y) = d2.b, P2's HUD at its own place: field rows 1-2 (the label, the score, the
; lives) x + 18, the bombs' rows (Text16's row 15: cells 30-31) mirrored into cells 16-31 (glyph i
; at 16-px column 15 - i, its halves kept in order: cell x -> 31 - (x ^ 1); P2's bombs from the
; right edge, the last one spent its leftmost, P1's mirror image: the user's choice, 2026-11-01;
; the original draws i 0-7 only, $7818/$784E/$7882): fixed places of their own (text.asm TEXT_PLACE, TEXT_P2_HUD 1: Task 7; with 0, on the field's fix map, they
; would scroll with the view, so none was written). Other cells as P1's. Keeps every register.
; ------------------------------------------------------------------------------
Coop_Text8:
    cmpi.w  #1, d1
    blo.s   .put
    cmpi.w  #2, d1
    bhi.s   .put
    if TEXT_P2_HUD
    move.w  d0, -(sp)
    addi.w  #COOP_HUD8_DX, d0
    jsr     Text_Put
    move.w  (sp)+, d0
    endif
    rts
.put:
    jmp     Text_Put

Coop_Text16:                        ; (the four cells' bsr Text_Put, each)
    cmpi.w  #2*COOP_HUD16_Y, d1
    blo.s   .put
    cmpi.w  #2*COOP_HUD16_Y+1, d1
    bhi.s   .put
    if TEXT_P2_HUD
    move.w  d0, -(sp)
    eori.w  #1, d0                  ; 31 - (x ^ 1): the glyph's column mirrored, its halves not
    neg.w   d0
    addi.w  #4*COOP_HUD16_DX-1, d0
    jsr     Text_Put
    move.w  (sp)+, d0
    endif
    rts
.put:
    jmp     Text_Put

; ------------------------------------------------------------------------------
; Coop_Score2 (Coop_Pass_2P's flush, P2 in): P2's score printed at its place, $341E(6, 1, score,
; 7 digits) in P2's context (Coop_Text8: x + 18), as $40D4 prints P1's. d0-d1/a0-a1 used ($341E
; keeps d3-d7/a3; the play loop keeps nothing in the rest).
; ------------------------------------------------------------------------------
Coop_Score2:
    bsr     Coop_Exchange
    pea     (7).w
    move.l  SHIM_COOP_SCORE2, -(sp) ; (not one of the exchanged runs)
    pea     (1).w
    pea     (6).w
    jsr     (GAME_ROM+$341E).l
    lea     16(sp), sp
    bra     Coop_Exchange

; ------------------------------------------------------------------------------
; The join prompt (Task 7; the spec's "The HUD"). While a play loop runs outside the demo with the
; joins open (the title mode's game, SHIM_COOP_LIVE 1: from its first step's setup to its last
; look), the corner of each player not in (SHIM_COOP_IN) shows, on field row 1 from column 1 (P1)
; or 19 (P2: x + COOP_HUD8_DX), 11 cells: INSERT COIN on the MVS with credits counted and none in
; (Bios_Credits 0), else PRESS START (credits in, the AES, Free Play) -- on while GV_FRAME's bit
; COOP_PR_OFF (5) is 0, blank while it is 1: 32 steps each, the title's TITLE_BLINK. The corner's
; lives and bombs are blank meanwhile (and its score's last cell). Not in the demo, the title,
; CONFIG, KAKUSI or the game over.
; Coop_Prompt (Coop_Pass_2P, at a step's start after the requests: a one-player step's slow path
; when Coop_Blink asked for it, every two-player step; Coop_Over: the game over): SHIM_COOP_PROMPT
; (what the cells hold) made what is due (Coop_PromptWant), writing only the cells of what
; changed: a corner that becomes the prompt's has its HUD blanked first (Coop_Blank; not in a
; one-player game: P2's corner held nothing since the title's clear), then its 11 cells (the text,
; or blanks in the blink's off half: Coop_Row); a corner no longer the prompt's (the game over;
; a join clears its own bit and prints its HUD over the cells) has its 11 cells blanked.
; Unchanged cells are left alone, so the blink's step writes 10 (the text's gap is a 0 both
; ways). Clears SHIM_COOP_NEW's COOP_NEW_PROMPT first (a later request: the next step), and
; sets it again when the next step changes the blink's half (so the cells change in that very step
; whenever the VBlank falls: Coop_Blink). Every register kept.
; ------------------------------------------------------------------------------
COOP_PROMPT_LEN EQU 11

Coop_Prompt:
    movem.l d0-d5/a0-a2, -(sp)
    bclr    #COOP_NEW_PROMPT, SHIM_COOP_NEW
    bsr.s   Coop_PromptWant
    tst.b   d0
    beq.s   .due
    move.w  GV_FRAME, d1            ; a prompt, and the next step changes the blink's half: that
    move.w  d1, d2                  ; step's slow path asked for now (Coop_Blink's VBlank may
    addq.w  #1, d2                  ; have fallen before this step's Coop_Pass, and none fall
    eor.w   d2, d1                  ; between it and the next's when this step runs long)
    btst    #COOP_PR_OFF, d1
    beq.s   .due
    bset    #COOP_NEW_PROMPT, SHIM_COOP_NEW
.due:
    move.b  SHIM_COOP_PROMPT, d4    ; d4: what the cells hold, d5: what is due
    cmp.b   d0, d4
    beq.s   .out
    move.b  d0, SHIM_COOP_PROMPT
    move.b  d0, d5
    moveq   #0, d3                  ; the corner: its bit (0 P1, 1 P2)
.corner:
    btst    d3, d5
    beq.s   .gone
    btst    d3, d4
    bne.s   .text                   ; the prompt's already: its text only
    tst.b   SHIM_COOP_2P
    beq.s   .text                   ; (one player: P2's corner blank since the title's clear)
    bsr     Coop_Blank
.text:
    lea     COOP_STR_START, a0
    btst    #COOP_PR_COIN, d5
    beq.s   .off
    lea     COOP_STR_COIN, a0
.off:
    btst    #COOP_PR_OFF, d5
    beq.s   .row
.blank:
    lea     COOP_STR_BLANK, a0      ; the off half, or gone: blanks
.row:
    bsr.s   Coop_Row
.next:
    addq.w  #1, d3
    cmpi.w  #2, d3
    blo.s   .corner
.out:
    movem.l (sp)+, d0-d5/a0-a2
    rts
.gone:
    btst    d3, d4
    beq.s   .next                   ; (not the prompt's before either)
    bra.s   .blank

; Coop_PromptWant: d0.b = the cells due, SHIM_COOP_PROMPT's form (0: no prompt cell). Uses d0-d1.
Coop_PromptWant:
    moveq   #0, d1
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .none                   ; (the demo)
    cmpi.b  #1, SHIM_COOP_LIVE
    bne.s   .none                   ; not set up, or the joins closed
    move.b  SHIM_COOP_IN, d1
    not.b   d1
    andi.b  #(1<<COOP_PR_P1)|(1<<COOP_PR_P2), d1
    beq.s   .none                   ; both in
    move.b  BIOS_CREDITS, SHIM_COOP_CREDITS  ; (the byte this text was decided on: Coop_Blink;
    jsr     Bios_Credits                    ; the AES's read, not backup RAM, is never compared)
    tst.w   d0
    bne.s   .start                  ; credits in, or none counted
    bset    #COOP_PR_COIN, d1
.start:
    move.w  GV_FRAME, d0
    andi.w  #1<<COOP_PR_OFF, d0
    or.b    d1, d0
    rts
.none:
    moveq   #0, d0
    rts

; Coop_Row: corner d3 (0 P1, 1 P2)'s 11 prompt cells on field row 1, from the characters at a0,
; written as Text_Put writes a cell (the model's byte, its used bit, then its dirty bit; an
; unchanged cell left alone) but straight, the row's addresses stepped: the blink's 10 cells cost
; the one-player step that changes them about a third of Text_Put's (make timing). Row 1 is bit 1
; of each column's longs' last byte (rows 0-7); no title lift there (row TEXT_LIFT_ROW). Uses
; d0-d2/a0-a2.
    if TEXT_LIFT_ROW=1
    fail "coop.asm Coop_Row: the title lift's row counts its cells (Text_Put)"
    endif
Coop_Row:
    bsr.s   Coop_Col
    move.w  d0, d1
    lsl.w   #5, d1
    lea     SHIM_TEXT+1, a1
    adda.w  d1, a1                  ; cell (x, 1): x * 32 + 1
    add.w   d0, d0
    add.w   d0, d0
    lea     SHIM_TEXT_USED+3, a2
    adda.w  d0, a2                  ; column x's used long, its last byte (rows 0-7)
    moveq   #COOP_PROMPT_LEN-1, d2
.cell:
    move.b  (a0)+, d0
    cmp.b   (a1), d0
    beq.s   .same
    move.b  d0, (a1)
    beq.s   .unused
    bset    #1, (a2)
    bra.s   .dirty
.unused:
    bclr    #1, (a2)
.dirty:
    bset    #1, SHIM_TEXT_DIRTY-SHIM_TEXT_USED(a2)
.same:
    lea     TEXT_ROWS(a1), a1
    addq.l  #4, a2
    dbra    d2, .cell
    rts

; Coop_Cells: d0.w = the first column, d1.w the row, d2.w + 1 cells from a0 (a0 past them),
; through Text_Put. Uses d0-d2/a0.
Coop_Cells:
    swap    d2                      ; (the count in d2's high word: Text_Put takes d2.b)
.cell:
    move.b  (a0)+, d2
    jsr     Text_Put
    addq.w  #1, d0
    swap    d2
    dbra    d2, .more
    rts
.more:
    swap    d2
    bra.s   .cell

; Coop_Col: d0.w = corner d3's first column (1 P1, 1 + COOP_HUD8_DX P2)
Coop_Col:
    moveq   #1, d0
    tst.w   d3
    beq.s   .p1
    moveq   #1+COOP_HUD8_DX, d0
.p1:
    rts

; Coop_Blank: corner d3 (0 P1, 1 P2)'s HUD cells blank: row 1's 12 (the label and the score),
; row 2's 10 (the lives), the bombs' 32 (field rows TEXT_BOMB_ROW and the next, 16 columns from
; 16 x the corner: 2 * COOP_HUD16_DX). Uses d0-d2/a0.
Coop_Blank:
    bsr.s   Coop_Col
    moveq   #1, d1
    moveq   #12-1, d2
    lea     COOP_STR_BLANK, a0
    bsr.s   Coop_Cells
    bsr.s   Coop_Col
    moveq   #2, d1
    moveq   #10-1, d2
    lea     COOP_STR_BLANK, a0
    bsr.s   Coop_Cells
    moveq   #TEXT_BOMB_ROW, d1
.bombs:
    moveq   #0, d0
    tst.w   d3
    beq.s   .p1
    moveq   #2*COOP_HUD16_DX, d0
.p1:
    moveq   #16-1, d2
    lea     COOP_STR_BLANK, a0
    bsr.s   Coop_Cells
    addq.w  #1, d1
    cmpi.w  #TEXT_BOMB_ROW+1, d1
    bls.s   .bombs
    rts

; ------------------------------------------------------------------------------
; Coop_Blink (the VBlank: bios.asm Bios_Frame's last, after SYSTEM_IO, never in the demo's -- its
; frames' cost unchanged): a one-player game's join prompt possibly due to change -- the blink's
; half changing at this step or the next (GV_FRAME & 31 is 31 or 0), or the MVS's credits byte
; not the one Coop_Prompt last read (SHIM_COOP_CREDITS: a coin, a start; the AES and Free Play
; never change it) -- in the title mode's game with the joins open (SHIM_COOP_LIVE 1: 0 in the
; settle frames, the title, CONFIG, KAKUSI; SHIM_COOP_2P 0: two players' Coop_Pass_2P calls
; Coop_Prompt at every step) asks Coop_Pass's one test for its slow path (SHIM_COOP_NEW's
; COOP_NEW_PROMPT), where Coop_Prompt writes the cells if they changed (the main code's: Text_Put
; is not the VBlank's). Each step waits for a VBlank before its Coop_Pass (xsp_vsync, $425C), so
; one falls between two steps' waits at least -- in the step before (GV_FRAME one less) or in the
; step itself, before its Coop_Pass -- and the step whose GV_FRAME changes the half finds the
; request at its Coop_Pass either way (a step before it that was asked takes a slow path that
; changes nothing but asks for the next: Coop_Prompt): the cells change in that very step. A
; coin's or a start's text is served by the next step. A text clear empties SHIM_COOP_PROMPT and
; asks itself (text.asm Shim_TextClear). Most frames of a one-player game's play: the tests
; above .near, about 120 cycles.
; First, every frame but the demo's, P2's START read (REG_STATUS_B, about 60 cycles): its press
; (an edge: SHIM_COOP_P2KEY's COOP_KEY_UP the last frame's, 0 after a resume: a START held then is
; no press) is the US BIOS fallback's when the BIOS drops it (Coop_P2Key). Uses d0 (the VBlank's).
; ------------------------------------------------------------------------------
Coop_Blink:
    btst    #2, REG_STATUS_B        ; P2's START (active low)
    bne.s   .up
    bclr    #COOP_KEY_UP, SHIM_COOP_P2KEY
    beq.s   .blink                  ; (held: no press)
    bsr.s   Coop_P2Key
    bra.s   .blink
.up:
    bset    #COOP_KEY_UP, SHIM_COOP_P2KEY
.blink:
    move.w  GV_FRAME, d0
    addq.w  #1, d0
    andi.w  #$1E, d0                ; GV_FRAME & 31: 31 or 0 (the blink's bit COOP_PR_OFF, 5)
    beq.s   .near
    tst.b   BIOS_MVS_FLAG
    beq.s   .out                    ; (the AES: no credits byte, $D00034 not backup RAM)
    move.b  BIOS_CREDITS, d0
    cmp.b   SHIM_COOP_CREDITS, d0
    bne.s   .near
    rts
.near:
    cmpi.b  #1, SHIM_COOP_LIVE
    bne.s   .out
    tst.b   SHIM_COOP_2P
    bne.s   .out
    bset    #COOP_NEW_PROMPT, SHIM_COOP_NEW
.out:
    rts

; Coop_P2Key (Coop_Blink: P2's START pressed this frame): the US BIOS fallback (the spec's
; "Starting and credits", ruling R19). An SNK BIOS with its "game start compulsion" off
; (BIOS_COMPULSION_OFF: the US BIOS's default) never passes P2's START to PLAYER_START while P2's
; own credits ($D00035) are 0 (two-player plan Task 11's probe, MAME 0.289), so it could not spend
; P1's: there (the MVS, credits counted, that BIOS setting, P2's byte 0) and where PLAYER_START would
; have served it -- the title waiting (SHIM_TITLE_ON: title.asm Title_Hook's next pass, two of P1's
; credits for two players) or the joins open (SHIM_COOP_LIVE 1: Coop_Take at the next step's start,
; or the last look, one credit, SHIM_COOP_NEW's request bit for Coop_Pass's one test) -- the press
; is kept (COOP_KEY_SEEN), and the game spends the credit itself, under the mask, in the moment
; its ship's join is decided (CREDIT_CHECK / CREDIT_DOWN, as CONTINUE: title.asm Title_Spend): no
; credit without its ship. Where the BIOS passes the START (compulsion on: the euro and Universe
; BIOSes; or a P2 credit in, which the BIOS then takes), nothing (and a START it passed in the same
; VBlank, SYSTEM_IO's first, is the one served: Coop_Spend, Title_Hook). Uses d0.
Coop_P2Key:
    tst.b   BIOS_MVS_FLAG
    beq.s   .out                    ; (the AES)
    btst    #DIP_FREE_PLAY, REG_DIPSW
    beq.s   .out                    ; (Free Play: active low)
    tst.b   BIOS_COMPULSION_OFF
    beq.s   .out                    ; the BIOS passes it
    tst.b   BIOS_CREDITS+1
    bne.s   .out                    ; P2's own credit: the BIOS passes it (and takes that one)
    tst.b   BIOS_CREDITS
    beq.s   .out                    ; no credit: no press kept (a coin landing before its take would
                                    ; be spent on it), as the BIOS calls for no START with none in
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    bne.s   .out
    tst.w   SHIM_START_REQ
    bne.s   .out                    ; (a START PLAYER_START took at the title)
    tst.w   SHIM_TITLE_ON
    bne.s   .seen                   ; the title waiting
    cmpi.b  #1, SHIM_COOP_LIVE
    bne.s   .out                    ; joins not open
    move.b  SHIM_COOP_IN, d0        ; P2 in, or asked for (through the BIOS, or the title's
    or.b    SHIM_COOP_REQ, d0       ; start: as Coop_Start counts them)
    or.b    SHIM_COOP_START2, d0
    btst    #1, d0
    bne.s   .out
    bset    #COOP_NEW_REQ, SHIM_COOP_NEW
.seen:
    bset    #COOP_KEY_SEEN, SHIM_COOP_P2KEY
.out:
    rts

COOP_STR_START:
    dc.b    "PRESS", 0, "START"     ; (the gap a 0 both ways: one cell less to write a blink)
COOP_STR_COIN:
    dc.b    "INSERT", 0, "COIN"
COOP_STR_BLANK:
    dcb.b   16, 0
    even
    if (COOP_STR_COIN-COOP_STR_START!=COOP_PROMPT_LEN)|(COOP_STR_BLANK-COOP_STR_COIN!=COOP_PROMPT_LEN)
    fail "coop.asm: the join prompt's strings are COOP_PROMPT_LEN characters"
    endif

; ------------------------------------------------------------------------------
; Coop_View (view.asm View_Build, a two-player game's play list: the game's time, after the step's
; passes and its objects, P1's context in the globals): the view's bounds and target from both
; ships (the spec's "The view": neo-r-type's rule, the top winning when both pull). A ship counts
; while it is in play (SHIM_COOP_IN) with its death timer 0: an out player (its timer held at $5C,
; Coop_Out) and a dying one do not. Each counted ship gives view.asm's one-ship range -- its least
; view and its most (its lines on the field whole; none while it is below the field, rising in)
; and its target (its bottom VIEW_MARGIN lines above the screen's last line, 0..VIEW_MAX):
;   * d4, the most: the least of the mosts (the higher ship's: its top on the screen);
;   * d3, the least: the most of the leasts (the lower ship's), but at most d4: the higher ship
;     whole first, the lower too whenever both fit (the lower's least at most the higher's most:
;     its bottom at most 223 lines below the higher's top, the ships some 190 lines apart);
;   * d2, the target: the most of the targets (the lower's), at most d4 -- inside [d3, d4], as
;     each target lies at or above its ship's least.
; Apart, d3 = d4 = the higher's most: its top on the screen's first line, the lower's bottom off
; the screen. One ship counted: its own range and target, view.asm's one-player rule exactly (P2
; alone is followed as P1 is in a one-player game). View_Build then smooths (VIEW_STEP) and clamps
; to [d3, d4] as for one ship: the clamp keeps the higher ship whole even where that moves the view
; more than VIEW_STEP (the higher rising while the lower holds the view at the higher's most).
; No ship counted: Z set, View_Build's dying hold in d3 / d4: the bounds of the ships in play
; (dying) that the view shows whole now, the higher first, the lower too while a multiple of
; VIEW_ALIGN stays inside (.hold); none: [0, VIEW_MAX]. They always hold the view and a multiple of
; 8, so the hold moves a line a list to one and settles there (no snap to an explosion the view
; had left; a game over freezes 8-aligned). Reads GV_PLAYER_Y, GV_DEATH_TIMER and SHIM_COOP_P2
; (P2's y, its block's death timer); writes nothing. Out: d0 SHIM_VIEW_LAST, d2-d4; Z set: no ship
; counted. Uses d0-d4 (4 bytes of stack in the hold). About 300 cycles a list.
; ------------------------------------------------------------------------------
Coop_View:
    moveq   #-1, d2                 ; the target (-1: no ship counted)
    moveq   #0, d3
    moveq   #VIEW_MAX, d4
    btst    #0, SHIM_COOP_IN
    beq.s   .p2
    tst.w   GV_DEATH_TIMER
    bne.s   .p2
    move.w  GV_PLAYER_Y, d1
    bsr.s   .ship
.p2:
    btst    #1, SHIM_COOP_IN
    beq.s   .counted
    tst.w   SHIM_COOP_P2+COOP_P2_BLK+COOP_BLK_DEATH
    bne.s   .counted
    move.w  SHIM_COOP_P2+COOP_P2_Y, d1
    bsr.s   .ship
.counted:
    tst.w   d2
    bmi.s   .none
    cmp.w   d4, d2                  ; the target at most the most
    ble.s   .live
    move.w  d4, d2
.live:
    moveq   #1, d1
    bra.s   .least
.none:
    ; no ship counted: the hold's bounds (.hold), from the ships in play, the higher first (one not
    ; in play: y $7FFF, below the field: no bound)
    move.w  #$7FFF, d1
    move.w  d1, d2
    btst    #0, SHIM_COOP_IN
    beq.s   .n2
    move.w  GV_PLAYER_Y, d1
.n2:
    btst    #1, SHIM_COOP_IN
    beq.s   .n3
    move.w  SHIM_COOP_P2+COOP_P2_Y, d2
.n3:
    cmp.w   d1, d2
    bge.s   .n4
    exg     d1, d2                  ; d1 the higher
.n4:
    move.w  d2, -(sp)
    bsr.s   .hold
    move.w  (sp)+, d1
    bsr.s   .hold
    moveq   #0, d1
.least:
    cmp.w   d4, d3                  ; the least at most the most: the higher ship whole first
    ble.s   .out
    move.w  d4, d3
.out:
    move.w  SHIM_VIEW_LAST, d0
    tst.w   d1                      ; Z: no ship counted
    rts
; one ship (d1 its y): its target into d2 (the most of them), its least view into d3 (the most of
; them), its most into d4 (the least of them) -- view.asm's one-ship rule. Uses d0-d1.
.ship:
    asr.w   #6, d1
    subi.w  #16, d1                 ; ref: the ship's line on the field
    move.w  d1, d0                  ; its target: its bottom VIEW_MARGIN lines above the screen's
    addi.w  #VIEW_SHIP_DOWN+VIEW_MARGIN-223, d0     ; last line, 0..VIEW_MAX
    bpl.s   .tmax
    moveq   #0, d0
.tmax:
    cmpi.w  #VIEW_MAX, d0
    ble.s   .tgt
    moveq   #VIEW_MAX, d0
.tgt:
    cmp.w   d2, d0
    ble.s   .bounds
    move.w  d0, d2
.bounds:
    move.w  d1, d0
    subi.w  #VIEW_SHIP_UP, d0       ; its top line
    cmpi.w  #255, d0
    bgt.s   .done                   ; below the field (rising in): no bound
    tst.w   d0                      ; its most: max(top, 0)
    bpl.s   .most
    moveq   #0, d0
.most:
    cmp.w   d4, d0
    bge.s   .lst
    move.w  d0, d4
.lst:
    move.w  d1, d0                  ; its least: min(bottom, 255) - 223 (at most VIEW_MAX)
    addi.w  #VIEW_SHIP_DOWN-223, d0
    cmpi.w  #VIEW_MAX, d0
    ble.s   .lmax
    moveq   #VIEW_MAX, d0
.lmax:
    cmp.w   d3, d0
    ble.s   .done
    move.w  d0, d3
.done:
    rts
; one dying ship in the hold (d1 its y): its bounds narrow d3 / d4 only if the view (the list
; before's) shows it whole now -- an explosion the view has left stays off (no snap back to it) --
; and a multiple of VIEW_ALIGN is left inside them (else it is left out: the higher, taken first,
; whole). So the hold's bounds always hold the view, and a multiple of VIEW_ALIGN (one ship's
; bounds always do: [0, x] or [y, VIEW_MAX]): View_Build's hold settles on one a line a list, and
; never moves the view by its clamp. Uses d0-d2; d3 / d4 (the bounds so far) narrowed.
.hold:
    asr.w   #6, d1
    subi.w  #16+VIEW_SHIP_UP, d1    ; its top line
    cmpi.w  #255, d1
    bgt.s   .hdone                  ; below the field: no bound
    move.w  d1, d0                  ; its most: its top, 0..VIEW_MAX
    bpl.s   .hm0
    moveq   #0, d0
.hm0:
    cmpi.w  #VIEW_MAX, d0
    ble.s   .hm1
    moveq   #VIEW_MAX, d0
.hm1:
    addi.w  #VIEW_SHIP_UP+VIEW_SHIP_DOWN-223, d1    ; its least: its bottom - 223, 0..VIEW_MAX
    bpl.s   .hl0
    moveq   #0, d1
.hl0:
    cmpi.w  #VIEW_MAX, d1
    ble.s   .hl1
    moveq   #VIEW_MAX, d1
.hl1:
    cmp.w   SHIM_VIEW_LAST, d1      ; whole at the view now?
    bgt.s   .hdone
    cmp.w   SHIM_VIEW_LAST, d0
    blt.s   .hdone
    cmp.w   d3, d1                  ; with the bounds so far
    bge.s   .hl2
    move.w  d3, d1
.hl2:
    cmp.w   d4, d0
    ble.s   .hm2
    move.w  d4, d0
.hm2:
    move.w  d1, d2                  ; a multiple of VIEW_ALIGN left inside?
    addq.w  #VIEW_ALIGN-1, d2
    andi.w  #-VIEW_ALIGN, d2
    cmp.w   d0, d2
    bgt.s   .hdone
    move.w  d1, d3
    move.w  d0, d4
.hdone:
    rts

    ifd     SHIM_TEST_COOP
; ------------------------------------------------------------------------------
; Coop_Test (make cart SHIM_TEST_COOP=1; Coop_Pass at a step's start): SHIM_TEST_CO's request,
; cleared once done (a test reads the join's state at that write, before the step's passes).
; 1: P1 buys in, 2: P2 joins (Coop_Join, free, no BIOS; nothing for a player in); 3: P2 out
; (Coop_Out, its ship as it is); 4 is the last look's (Coop_TestLate), 5-7 the holds'
; (Coop_TestHold), left. d0-d1/a0-a1 used.
; ------------------------------------------------------------------------------
Coop_Test:
    move.b  SHIM_TEST_CO, d0
    beq.s   .out
    cmpi.b  #4, d0
    bhs.s   .out                    ; (4: the last look's, Coop_TestLate; 5-7: Coop_TestHold)
    tst.b   SHIM_COOP_LIVE
    bne.s   .live
    bsr     Coop_Setup              ; (a request before the game's setup)
.live:
    ext.w   d0
    cmpi.w  #3, d0
    beq.s   .p2out
    move.b  d0, d1
    and.b   SHIM_COOP_IN, d1
    bne.s   .done                   ; (in already)
    bsr     Coop_Join
    bra.s   .done
.p2out:
    btst    #1, SHIM_COOP_IN
    beq.s   .done
    moveq   #2, d0
    bsr     Coop_Out
.done:
    clr.b   SHIM_TEST_CO
.out:
    rts

; Coop_TestLate (the test build: Coop_End's and Coop_Over's last look, first): SHIM_TEST_CO's high
; byte 4 (a test sets it in the step a last ship ends) cleared, then a VBlank waited for, so that a
; START the test pressed in that step reaches PLAYER_START between the passes and the last look
; (Coop_End's: where a VBlank falls when a step runs long; Coop_Over's comes after the step's own
; VBlank, which this one stands for). d0 used.
Coop_TestLate:
    cmpi.b  #4, SHIM_TEST_CO
    bne.s   .out
    clr.b   SHIM_TEST_CO
    move.l  SHIM_HEARTBEAT, d0
.wait:
    cmp.l   SHIM_HEARTBEAT, d0
    beq.s   .wait
.out:
    rts

; Coop_TestHold (the test build; d1.b the place: 5 Coop_Starts' join of the title's two-player
; start, after the game's setup; 6 Coop_Join, after its SHIM_COOP_IN bit): with SHIM_TEST_CO's high
; byte that place's, 7 written there and the main code held until a test writes it back (0), the
; VBlanks running on, so that a START the test presses meanwhile reaches PLAYER_START inside the
; join (final review I2: tests/neo/coop.lua join_hold). Every register kept.
Coop_TestHold:
    cmp.b   SHIM_TEST_CO, d1
    bne.s   .out
    move.b  #7, SHIM_TEST_CO
.hold:
    cmpi.b  #7, SHIM_TEST_CO
    beq.s   .hold
.out:
    rts
    endif

COOP_IMAGE_END:
    if COOP_IMAGE_END>$100000
    fail "the co-op's code does not fit in the 1 MB P-ROM"
    endif
    if (GHOOK_JT!=$7F00)|(PCREL_STUBS+PCREL_STUBS_SIZE!=GHOOK_JT)
    fail "coop.asm: the game hooks' table is GHOOK_JT $7F00, after the PC-relative stubs"
    endif
    endm
