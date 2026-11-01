; ==============================================================================
; WAVES, the endless wave mode (docs/superpowers/specs/2026-11-01-waves-mode-design.md; the WAVES
; plan). The title's item 1 (title.asm: SHIM_WAVES_ON) starts a one-player game that runs, instead
; of a stage script, the original's own stage sections (docs/notes/waves.md): the stage
; dispatcher's switch on the stage (`$4A1A`, link.py GAME_HOOKS: Waves_Dispatch) runs Waves_Step
; and returns past the dispatch. Each section runs in a lane: the lane's phase and phase timer are
; exchanged with the game's ($2B8A6, GV_PHASE) around a call of its stage's script, ACCHOH 0 for
; the call (the scripts' heads add KAKUSI ACCHOH's extras: not in WAVES, and the value is the
; normal game's, kept for its CONTINUE). A section ends when its script writes the next phase:
; the lane goes idle (the next phase's code never runs). The stage is never read nor written, so
; CONTINUE after a run plays the stage the last normal game left. The original's rank ($2220E:
; docs/notes/waves.md) counts on as in any game.
; Without a run (SHIM_WAVES_ON 0) the hook does the replaced instruction alone.
; WAVES_CODE (boot.asm, after COOP_CODE) places it in high P-ROM.
; ==============================================================================
WAVES_TUNE      EQU $11             ; the stage tune ($3D92(11): stage 1's and the bonus stage's)
WV_BOSS_T0      EQU $1B0            ; a boss lane's first timer: the boss tune at $1C0, the boss at
                                    ; $240 (the section's own timings; its warning at $40 skipped)
WV_BOSS_AT      EQU $241            ; the lane's timer after the step that made the boss
WV_HP_MAX       EQU $7FFF           ; hit points are a signed word ($1129E)
WV_GAP0         EQU 120             ; the ramp (Waves_Fill): an idle lane's wait before its next
WV_GAP_STEP     EQU 16              ; section, WV_GAP0 less WV_GAP_STEP a cycle, at least
WV_GAP_MIN      EQU 16              ; WV_GAP_MIN; lanes allowed 1 + (cycle - 1) / 2, at most
                                    ; WAVES_LANES
WV_BUDGET       EQU 360             ; the sprite ceiling's governor (Waves_Pick): the running
                                    ; sections' weights (their measured p99 requested sprites,
                                    ; WAVES_POOL) with the new one's at most this (tuned against
                                    ; tests/neo/waves.lua ceiling: p99 381, max 497 a cycle)
WV_CLEAR_MAX    EQU 1776            ; the clearing's limit: 30 s (a stuck object never holds a run)
WV_OBJ_HIGH     EQU 36              ; the governor's feedback: with more objects live than this
                                    ; (enemies, their bullets: the rank raises their fire as a run
                                    ; goes on, which the weights measured early do not see) the
                                    ; running sections pause (their timers held: their next spawns
                                    ; wait) and none starts (tuned: tests/neo/waves.lua ceiling)
WV_CARD_X       EQU 12              ; the card where "STAGE n" prints ($79AE: $33E8(12, 14, ...))
WV_CARD_Y       EQU 14

WAVES_CODE macro
    cnop    0, 2
WAVES_IMAGE:

; Waves_Dispatch (link.py GAME_HOOKS $4A1A: move.w $221FA.l,d0 -> jsr (Waves_Dispatch).l)
Waves_Dispatch:
    tst.b   SHIM_WAVES_ON
    bne.s   .run
    move.w  GV_STAGE, d0
    rts
.run:
    bsr.s   Waves_Step
    move.l  #GAME_ROM+$4A58, (sp)   ; past the dispatch: its epilogue (movem.l (a7)+,a3-a4; rts)
    rts

; Waves_Step: one step of the run: its cycle's part (WV_STATE). Every register kept.
;   * the card: at clock 0 the waves tune and the card's text ("WAVE n"), printed at $30 and
;     blanked at $C0 as a stage's card is ($79A4-$79DA), the waves at $E0;
;   * the waves: WAVES_CYCLE_STEPS of them (the lanes filled: Waves_Fill); then every lane cut (made
;     idle: a section's tail is not waited for);
;   * the clearing: no section, until the last waves' enemies are destroyed or gone (the object
;     table empty: the user's request, 2026-11-01), at most WV_CLEAR_MAX steps; then lane 0 is
;     given the next boss's section from WV_BOSS_T0 (odd bosses stage 1's, $160, even ones stage
;     2's, $190);
;   * the boss: lane 0 alone; the step that made the boss raises its hit points (Waves_BossHP);
;     the section's own end (its boss dead: it writes phase $200, which never runs) starts the
;     next cycle's card.
Waves_Step:
    movem.l d0-d7/a0-a6, -(sp)
    tst.w   GV_MUTEKI
    beq.s   .mortal
    st      WV_MUTEKI               ; (KAKUSI's invincibility: the run's score not the best)
.mortal:
    tst.b   WV_STARTED
    bne.s   .go
    st      WV_STARTED
    move.w  #1, WV_CYCLE            ; (the block cleared by Waves_Begin: the card, clock 0)
.go:
    lea     WV_LANES, a2
    move.w  WV_STATE, d0
    cmpi.w  #WV_ST_WAVES, d0
    beq.s   .waves
    cmpi.w  #WV_ST_CLEAR, d0
    beq     .clear
    cmpi.w  #WV_ST_BOSS, d0
    beq     .boss
; the card
    move.w  WV_CLOCK, d0
    bne.s   .c30
    pea     (WAVES_TUNE).w          ; the waves tune, as a stage's card starts it ($7998)
    jsr     (GAME_ROM+$3D92).l
    addq.l  #4, sp
    bsr     Waves_CardText
    bra.s   .ctick
.c30:
    cmpi.w  #$30, d0
    bne.s   .cC0
    pea     WV_CARD
    bra.s   .print
.cC0:
    cmpi.w  #$C0, d0
    bne.s   .ctick
    pea     WAVES_BLANK(pc)
.print:
    pea     (WV_CARD_Y).w
    pea     (WV_CARD_X).w
    jsr     (GAME_ROM+$33E8).l      ; the game's string printer, as the stages' cards
    lea     12(sp), sp
.ctick:
    addq.w  #1, WV_CLOCK
    cmpi.w  #$E0, WV_CLOCK
    blo     .out
    move.w  #WV_ST_WAVES, WV_STATE
    clr.w   WV_CLOCK
    bra     .out
; the waves
.waves:
    cmpi.w  #WAVES_CYCLE_STEPS, WV_CLOCK
    bhs.s   .cut
    addq.w  #1, WV_CLOCK
    bsr     Waves_Live
    cmpi.w  #WV_OBJ_HIGH, d2
    bhi     .out                    ; busy: the sections paused, none started (the governor)
    bsr     Waves_Fill
    bsr     Waves_RunLanes
    bra     .out
.cut:
    moveq   #WAVES_LANES-1, d0      ; the cycle's end: every lane idle, the clearing
    movea.l a2, a0
.idle:
    clr.w   WVL_SCRIPT(a0)
    lea     WVL_SIZE(a0), a0
    dbra    d0, .idle
    move.w  #WV_ST_CLEAR, WV_STATE
    clr.w   WV_CLOCK
    bra     .out
; the clearing: the boss once no object is left (or WV_CLEAR_MAX steps on)
.clear:
    bsr     Waves_Live
    tst.w   d2
    beq.s   .toboss
    addq.w  #1, WV_CLOCK
    cmpi.w  #WV_CLEAR_MAX, WV_CLOCK
    blo     .out
.toboss:
    addq.w  #1, WV_BOSSES
    lea     WV_BPREV, a0            ; no boss object seen yet (Waves_BossHP)
    moveq   #WV_BPREV_N*6/2-1, d0
.bprev:
    clr.w   (a0)+
    dbra    d0, .bprev
    moveq   #1, d0                  ; odd: stage 1's boss section
    move.w  #$160, d1
    btst    #0, WV_BOSSES+1
    bne.s   .which
    moveq   #2, d0                  ; even: stage 2's
    move.w  #$190, d1
.which:
    move.w  d0, WVL_SCRIPT(a2)
    move.w  d1, WVL_PHASE(a2)
    move.w  d1, WVL_START(a2)
    move.w  #WV_BOSS_T0, WVL_TIMER(a2)
    move.w  #WV_ST_BOSS, WV_STATE
    bra.s   .out
; the boss
.boss:
    bsr     Waves_RunLane
    cmpi.w  #WV_BOSS_AT, WVL_TIMER(a2)
    blo.s   .alive                  ; (no boss yet)
    bsr     Waves_BossHP            ; every step: $FF42's handler sets $2C00 again in its first
.alive:                             ; state ($10042), so the raise is made until it leaves it
    tst.w   WVL_SCRIPT(a2)
    bne.s   .out
    addq.w  #1, WV_CYCLE            ; the boss down: the next cycle's card
    move.w  #WV_ST_CARD, WV_STATE
    clr.w   WV_CLOCK
.out:
    movem.l (sp)+, d0-d7/a0-a6
    rts

; Waves_Live: d2.w = the objects live (the object table's free bitmap's clear bits). d0-d1/a0 used.
Waves_Live:
    lea     GV_OBJ_FREE, a0
    moveq   #0, d2
    moveq   #8-1, d1
.word:
    move.w  (a0)+, d0
    not.w   d0
.bit:
    beq.s   .done
    lsr.w   #1, d0
    bcc.s   .bit
    addq.w  #1, d2
    bra.s   .bit
.done:
    dbra    d1, .word
    rts

; Waves_RunLanes: every lane not idle, one step. a2 kept; d0-d2/a0-a1 used.
Waves_RunLanes:
    move.l  a2, -(sp)
    moveq   #WAVES_LANES-1, d2
.lane:
    tst.w   WVL_SCRIPT(a2)
    beq.s   .next
    move.w  d2, -(sp)
    bsr     Waves_RunLane
    move.w  (sp)+, d2
.next:
    lea     WVL_SIZE(a2), a2
    dbra    d2, .lane
    movea.l (sp)+, a2
    rts

; Waves_BossHP (each boss step from the one that made the boss): each boss object (type $204 or
; $205) whose hit points are the base the game gives it ($2000, $2C00) gets base x (4 + k) / 4,
; k = bosses before it (WV_BOSSES - 1), at most WV_HP_MAX -- unless it was seen above its base at
; a step's start since it was last seen below it (WV_BPREV's flag, per object): a hit landing
; exactly on the base on its way down is left there (final review C1: else the fight heals). The
; raises it needs still come: a new object; $FF42's first state, which gives it its base again
; before every step (so it is never seen above it there); its second form, which restarts that
; state from below 0. d0-d4/a0-a1 used (a2 kept: the caller's lane).
Waves_BossHP:
    lea     GV_OBJECTS, a0
    move.w  #128-1, d2
.obj:
    move.w  $16(a0), d0
    move.w  #$2000, d1
    cmpi.w  #$204, d0
    beq.s   .type
    move.w  #$2C00, d1
    cmpi.w  #$205, d0
    bne     .next
.type:
    lea     WV_BPREV, a1            ; its entry: found, or the first free one (0), or none
    moveq   #WV_BPREV_N-1, d3
    moveq   #0, d4
.find:
    cmpa.l  (a1), a0
    beq.s   .found
    tst.l   (a1)
    bne.s   .f1
    tst.l   d4
    bne.s   .f1
    move.l  a1, d4                  ; (the first free entry)
.f1:
    addq.l  #6, a1
    dbra    d3, .find
    moveq   #0, d3                  ; not seen before: never above its base
    tst.l   d4
    beq.s   .test                   ; (no room: judged as new each step)
    movea.l d4, a1
    move.l  a0, (a1)
    clr.w   4(a1)
    bra.s   .seen
.found:
    move.w  4(a1), d3               ; seen above its base since last below it
.seen:
    move.w  $3E(a0), d0             ; the flag from this step's hit points
    cmp.w   d1, d0
    beq.s   .test
    sgt     d0                      ; above: set; below: cleared
    ext.w   d0
    move.w  d0, 4(a1)
.test:
    cmp.w   $3E(a0), d1
    bne.s   .next                   ; (not at its base)
    tst.w   d3
    bne.s   .next                   ; came down onto it: left there
    move.w  WV_BOSSES, d0
    addq.w  #3, d0                  ; 4 + k
    mulu    d0, d1
    lsr.l   #2, d1
    cmpi.l  #WV_HP_MAX, d1
    bls.s   .hp
    move.l  #WV_HP_MAX, d1
.hp:
    move.w  d1, $3E(a0)
.next:
    lea     $80(a0), a0
    dbra    d2, .obj
    rts

; Waves_CardText: WV_CARD = "WAVE " and WV_CYCLE in decimal (1-9999), 0. d0-d2/a0-a1 used.
Waves_CardText:
    lea     WV_CARD, a0
    lea     WAVES_WORD(pc), a1
.w:
    move.b  (a1)+, (a0)+
    bne.s   .w
    subq.l  #1, a0                  ; (on the 0)
    moveq   #0, d0
    move.w  WV_CYCLE, d0
    moveq   #0, d2                  ; digits pushed
.div:
    divu    #10, d0
    swap    d0
    addi.w  #'0', d0
    move.w  d0, -(sp)
    addq.w  #1, d2
    clr.w   d0
    swap    d0
    tst.w   d0
    bne.s   .div
.pop:
    move.w  (sp)+, d0
    move.b  d0, (a0)+
    subq.w  #1, d2
    bne.s   .pop
    clr.b   (a0)
    rts

; Waves_Fill (a2 = WV_LANES; the waves): the ramp. Lanes 0 .. allowed - 1 (allowed = 1 + (cycle
; - 1) / 2, at most WAVES_LANES) that are idle wait the cycle's gap (WV_GAP0 less WV_GAP_STEP a
; cycle, at least WV_GAP_MIN), then take a section that fits the budget (Waves_Pick; none: the
; lane waits on). a2 kept; d0-d4/a0-a1 used.
Waves_Fill:
    move.w  WV_CYCLE, d3
    subq.w  #1, d3                  ; cycle - 1
    move.w  d3, d4
    lsr.w   #1, d4                  ; allowed - 1
    cmpi.w  #WAVES_LANES-1, d4
    bls.s   .lanes
    moveq   #WAVES_LANES-1, d4
.lanes:
    mulu    #WV_GAP_STEP, d3
    move.w  #WV_GAP0, d0
    sub.w   d3, d0
    cmpi.w  #WV_GAP_MIN, d0
    bge.s   .gap
    moveq   #WV_GAP_MIN, d0
.gap:
    move.w  d0, d3                  ; the gap
    movea.l a2, a1
.lane:
    tst.w   WVL_SCRIPT(a1)
    bne.s   .next
    cmp.w   WVL_GAP(a1), d3
    bls.s   .ready
    addq.w  #1, WVL_GAP(a1)
    bra.s   .next
.ready:
    movem.l d3-d4/a1-a2, -(sp)
    movea.l a1, a2
    bsr.s   Waves_Pick
    movem.l (sp)+, d3-d4/a1-a2
    tst.w   WVL_SCRIPT(a1)
    beq.s   .next                   ; (nothing fits: it waits, ready)
    clr.w   WVL_GAP(a1)
.next:
    lea     WVL_SIZE(a1), a1
    dbra    d4, .lane
    rts

; Waves_Pick (a2 = an idle lane): a section drawn with the game's own random numbers ($4ABE) from
; WAVES_POOL's first WAVES_POOL1 (stage 1's and the bonus stage's) in cycle 1, from all of it
; after: the draw, or the next after it, that no other lane runs and whose weight with the
; running sections' keeps within WV_BUDGET; none: the lane stays idle. d0-d5/a0-a1 used.
Waves_Pick:
    lea     WV_LANES, a1            ; the running sections' weight
    moveq   #0, d5
    moveq   #WAVES_LANES-1, d2
.sum:
    tst.w   WVL_SCRIPT(a1)
    beq.s   .s1
    add.w   WVL_WEIGHT(a1), d5
.s1:
    lea     WVL_SIZE(a1), a1
    dbra    d2, .sum
    moveq   #WAVES_POOL1, d3
    cmpi.w  #1, WV_CYCLE
    beq.s   .n
    moveq   #WAVES_POOL_N, d3
.n:
    jsr     (GAME_ROM+$4ABE).l      ; (C: d0-d1/a0-a1 its own)
    andi.l  #$FF, d0
    divu    d3, d0
    swap    d0                      ; d0.w = the draw, 0 .. n - 1
    move.w  d3, d4
    subq.w  #1, d4                  ; tries
.try:
    lea     WAVES_POOL(pc), a0
    move.w  d0, d1
    mulu    #6, d1
    adda.w  d1, a0
    move.w  4(a0), d1               ; its weight: within the budget?
    add.w   d5, d1
    cmpi.w  #WV_BUDGET, d1
    bhi.s   .no
    move.l  (a0), d1                ; script.w, phase.w
    lea     WV_LANES, a1
    moveq   #WAVES_LANES-1, d2
.other:
    cmpa.l  a1, a2
    beq.s   .skip
    tst.w   WVL_SCRIPT(a1)
    beq.s   .skip
    cmp.l   WVL_SCRIPT(a1), d1      ; (script and phase: one long)
    beq.s   .no
.skip:
    lea     WVL_SIZE(a1), a1
    dbra    d2, .other
    move.l  d1, WVL_SCRIPT(a2)      ; script, phase
    move.w  d1, WVL_START(a2)       ; (the phase: the low word)
    move.w  4(a0), WVL_WEIGHT(a2)
    clr.w   WVL_TIMER(a2)
    addq.w  #1, WV_SECTIONS
    rts
.no:
    addq.w  #1, d0
    cmp.w   d3, d0
    blo.s   .again
    moveq   #0, d0
.again:
    dbra    d4, .try
    rts                             ; (none fits now)

; Waves_RunLane (a2 = a lane, not idle): its section one step. a2 kept (the scripts, compiled C,
; keep only what they use of d3-d7/a3-a6: d0-d2/a0-a2 are theirs to use); d0-d2/a0-a1 used.
Waves_RunLane:
    move.l  GV_PHASE, -(sp)         ; the game's phase and timer
    move.w  GV_ACCHOH, -(sp)
    clr.w   GV_ACCHOH
    move.w  WVL_PHASE(a2), GV_PHASE
    move.w  WVL_TIMER(a2), GV_PHASE+2
    move.w  WVL_SCRIPT(a2), d0
    add.w   d0, d0
    add.w   d0, d0
    lea     WAVES_SCRIPTS-4(pc), a0
    movea.l (a0,d0.w), a0
    move.l  a2, -(sp)
    jsr     (a0)
    movea.l (sp)+, a2
    move.w  GV_PHASE+2, WVL_TIMER(a2)
    move.w  GV_PHASE, d0
    move.w  d0, WVL_PHASE(a2)
    move.w  (sp)+, GV_ACCHOH
    move.l  (sp)+, GV_PHASE
    cmp.w   WVL_START(a2), d0
    beq.s   .out
    clr.w   WVL_SCRIPT(a2)          ; the section wrote its next phase: done, the lane idle
.out:
    rts

; Waves_Begin (Title_Hook, WAVES chosen): the run's state cleared, the run on. Every register kept.
Waves_Begin:
    movem.l d0/a0, -(sp)
    lea     SHIM_WAVES, a0
    moveq   #WAVES_SIZE/2-1, d0
.clr:
    clr.w   (a0)+
    dbra    d0, .clr
    move.b  #1, SHIM_WAVES_ON
    movem.l (sp)+, d0/a0
    rts

; Waves_End (Title_Hook as the title opens, a run on: its game over): the run off; its score
; (GV_SCORE: the game over added the last score_add) the best since power-on if higher and no
; step of the run had KAKUSI's muteki on (SHIM_KEEP+KEEP_WAVES_BEST, the block sealed again).
; Every register kept.
Waves_End:
    clr.b   SHIM_WAVES_ON
    tst.b   WV_MUTEKI
    bne.s   .out
    movem.l d0-d1/a0, -(sp)
    lea     SHIM_KEEP, a0
    move.l  GV_SCORE, d0
    cmp.l   KEEP_WAVES_BEST(a0), d0
    bls.s   .kept
    move.l  d0, KEEP_WAVES_BEST(a0)
    jsr     Keep_Seal               ; (resume.asm: uses d0-d1)
.kept:
    movem.l (sp)+, d0-d1/a0
.out:
    rts

WAVES_WORD:
    dc.b    "WAVE ", 0
WAVES_BLANK:                        ; (the card's cells: "WAVE " and up to 3 digits)
    dc.b    "        ", 0
    even
WAVES_SCRIPTS:                      ; WVL_SCRIPT 1-3
    dc.l    GAME_ROM+$78C2, GAME_ROM+$8152, GAME_ROM+$8E2C
WAVES_POOL:                         ; (script, phase, weight: its p99 requested sprites run alone,
                                    ; docs/notes/waves.md "Measures")
    dc.w    1, $108, 106, 1, $110, 178, 1, $120, 107, 1, $130, 88, 1, $140, 131, 1, $150, 196
    dc.w    3, $108, 190, 3, $110, 224, 3, $120, 207, 3, $130, 88, 3, $140, 259, 3, $150, 359
WAVES_POOL1     EQU (*-WAVES_POOL)/6    ; stage 1's and the bonus stage's: from cycle 1
    dc.w    2, $110, 166, 2, $128, 193, 2, $130, 250, 2, $140, 227, 2, $150, 100, 2, $160, 232
    dc.w    2, $170, 94, 2, $180, 197
WAVES_POOL_N    EQU (*-WAVES_POOL)/6    ; stage 2's too (not its $120: it launches nothing)

WAVES_IMAGE_END:
    if WAVES_IMAGE_END>$100000
    fail "WAVES' code does not fit in the 1 MB P-ROM"
    endif
    endm
