; ==============================================================================
; THE TITLE AS A CABINET'S (Plan 5 Task 3; docs/notes/plan5-recon.md section 3). The original's
; title menu runs as it is; link.py's TITLE_CODE drops its "exit" item and moves the copyright and
; version lines up out of the CRT crop, and TITLE_HOOKS calls Title_Hook once a pass of its loop
; ($2B10-$2BB8), after the pass's V-blank wait ($1F92) and its stick and trigger reads, before the
; loop acts on them. The hook may change the loop's registers:
;   d3 / d6  the stick's last and new values (a press edge: d3 0, d6 not), d4 the cursor's item
;            (0 START, 1 CONTINUE, 2 CONFIG, or AUTO FIRE where credits are counted), d5 / d7 the
;            triggers' last and new values (the loop chooses item d4 on a press edge: d5 0, d7 not).
; Credits are counted on the MVS without Free Play (Bios_Credits); there:
;   * no credit: no menu at all. INSERT COIN blinks between START's and CONTINUE's rows; START,
;     CONTINUE and item 2 are printed empty and the cursor drawn as a blank cell (the drawing's
;     sites, Title_Draw), and the loop sees no stick edge and no trigger edge (d3 = d5 = 1 every
;     pass): A, B and the stick choose nothing, move nothing (no CONFIG, no KAKUSI, no toggle);
;   * credits: START, CONTINUE and, on item 2's row (CONFIG's place), AUTO FIRE OFF / ON (the
;     preserved block's KEEP_AUTOFIRE, as config.asm's item shows it), the cursor to START when the
;     first credit comes. A trigger press edge on item 2 toggles AUTO FIRE (the block's byte,
;     sealed again: resume.asm Keep_Seal) and redraws it, and chooses nothing (d5 = 1: the loop
;     sees no edge; d7 kept, so a trigger held on is no edge in the next pass either: one toggle a
;     press); CONFIG and KAKUSI are not reached there (the user's request, 2026-10-28: on the MVS
;     the other settings keep their defaults). The BIOS's countdown (BIOS_COMPULSION_TIMER, TIME
;     nn) runs: USER_MODE 1 while the loop waits (a toggle's pass too), so the BIOS counts it and,
;     at 0, starts a game through PLAYER_START (its forced start). It is reloaded as the title
;     opens (BIOS_COMPULSION_RELOAD, as the BIOS does after a game; TITLE_COUNTDOWN where that
;     word reads 0). In CONFIG and KAKUSI (reached only where no credit is counted) and in play,
;     USER_MODE is 2: no countdown, no forced start. Where the SNK BIOS's "game start compulsion"
;     is off (BIOS_COMPULSION_OFF: the US BIOS's default) it never counts: no TIME is shown, and
;     the title waits for START (final review I2);
;   * CREDIT nn on the title's bottom line (the version's, right of it), at 0 too;
;   * A on START or CONTINUE takes a credit (CREDIT_CHECK, then CREDIT_DOWN; none: no choice).
; Everywhere (the AES, the MVS on Free Play too): START (PLAYER_START accepted it while the loop
; waited: SHIM_START_REQ) starts a new game whatever the cursor is on: the loop chooses START, so
; the game leaves the title as A on START does ($2BE6 -> $2C16, the clear with d4 = 0: the preserved
; block's START rule). The BIOS took its credit. P2's START (two-player plan Task 6: PLAYER_START,
; SHIM_START_REQ 2; two credits where counted, the BIOS took both, and with one in it does nothing)
; does the same and sets SHIM_COOP_START2: the game's first step joins P2 (coop.asm Coop_Starts).
; Where the BIOS drops P2's START (an SNK BIOS with its game start compulsion off, the US BIOS's
; default: coop.asm Coop_P2Key) the hook takes the two credits itself in its masked pass (Title_P2:
; CREDIT_CHECK / CREDIT_DOWN, as CONTINUE's), and the same two-player game follows.
; A on START or CONTINUE, and the countdown's forced start (P1's START), are one-player. With no
; credit counted, no text is added and no countdown runs: there, and on the MVS with no credit in,
; the title waiting TITLE_IDLE_FRAMES with no input hands back to the BIOS (Bios_Return: its demo
; follows) -- the way back after a game over: the game over shows the title, as the original's,
; for a CONTINUE.
; A pass that chooses also kills its stick edge (d3 = 1): the loop moves its cursor before it
; chooses, so the item the hook judged (took a credit for, or not) is the item the loop takes. A
; toggle's pass kills it too: the cursor stays on the item toggled.
; The menu comes back in the first pass that sees a credit after one with none (SHIM_TITLE_COIN:
; set by that pass, Title_NoCoin, and by a drawing at 0 credits, Title_Draw, so a coin counted
; between the drawing and the loop's first pass brings it too: fix round 1, I1). That pass chooses
; nothing (d5 = 1: no trigger edge), and a trigger still held after it is no edge either: A or B
; down as the coin lands (first seen in that pass, or held from before, when there was nothing to
; choose) never becomes START spending the new credit (Plan 5 Task 6, Task 5 re-review N1;
; tests/neo/cabinet.lua kakusi_coin).
; The KAKUSI code (C+D held, A+B pressed on CONFIG, where no credit is counted: iocs.asm
; Iocs_BITSNS, the gate at $2C2A) asks for both triggers in the pass that chooses, but a player's
; "together" is often a frame or two apart (review I1, Plan 5 Task 5 fix round 1). So with C and D
; held and only one of A and B down, the hook holds CONFIG's choice back (d7 = 0, the next pass's d5
; then 0 too: the choice judged again, SHIM_TITLE_KWAIT counting) for up to TITLE_KWAIT_PASSES
; passes: the other trigger in that time opens KAKUSI (up to 4 frames after the first: the last held
; pass's read sees it; 5 frames after, CONFIG: tests/neo/bios.lua kakusi_window); otherwise, or with
; the trigger let go, CONFIG opens. Without C and D held, no delay.
; SHIM_TITLE_ON (PLAYER_START accepts while it is set) and USER_MODE 1 hold from the end of a pass
; that chose nothing to the next pass: the VBlank in its wait. A pass that chooses clears both
; (USER_MODE first: never 1 with the title not waiting, or the BIOS's forced start would be refused
; and the BIOS would end the game: DEMO_END, SYSTEM_RETURN).
; The demo's title (demo.asm) shows the same text and holds the same cursor; its pad is not the
; player's, and after DEMO_TITLE_PASSES passes it chooses START itself (Demo_Title). The rest (the
; countdown, the START button, the choices, the idle return) is the title mode's.
; All text goes through the text model (Text_Put), on the title's fixed view: field (x, y) on fix
; (x + 4, y + 2), inside the CRT-safe area (fix rows 19-26, columns 15-35: not the strips, not the
; bombs' rows 27-28, not the HUD's rows 3-4).
; ==============================================================================
TITLE_CURSOR    EQU 5               ; the cursor's character ($2AF2: $1618(11, 17 + 2 d4, 5))
TITLE_CUR_X     EQU 11
TITLE_MENU_X    EQU 12              ; the items' column, their rows 17 + 2 n
TITLE_MENU_Y    EQU 17
TITLE_CONFIG    EQU 2               ; CONFIG's item (AUTO FIRE's where credits are counted)
TITLE_KWAIT_PASSES EQU 4            ; the KAKUSI code's window: passes CONFIG's choice is held back
                                    ; (C+D held, one of A and B down) for the other (67.6 ms)
TITLE_COIN_X    EQU 12              ; INSERT COIN: between START's and CONTINUE's rows
TITLE_COIN_Y    EQU 18
TITLE_BLINK     EQU 5               ; on and off for 2^5 = 32 passes each
TITLE_COUNTDOWN EQU $303B           ; 30 s (BCD seconds, frames): the countdown when the BIOS's
                                    ; setting word reads 0
TITLE_TIME_X    EQU 25              ; "TIME nn": right of START, to field column 31 (fix 35)
TITLE_TIME_Y    EQU 17
TITLE_CREDIT_X  EQU 23              ; "CREDIT nn": right of the version row (field 9-21, row 24)
TITLE_CREDIT_Y  EQU 24
    if (TITLE_TIME_X+7>32)||(TITLE_CREDIT_X+9>32)||(TITLE_CREDIT_Y+2>26)||(TITLE_MENU_X+13>32)
    fail "title.asm: the cabinet's text must stay in field columns 0-31, fix rows up to 26"
    endif
GAME_STR_START  EQU GAME_ROM+$29D0  ; the title's own strings ("START", "CONTINUE")
GAME_STR_CONT   EQU GAME_ROM+$29D6
TITLE_AT_LOOP   EQU GAME_ROM+$2B3A  ; Title_Hook's return addresses (link.py TITLE_HOOKS): the loop
TITLE_AT_CONFIG EQU GAME_ROM+$2AC2  ; CONFIG's print
TITLE_AT_CURSOR EQU GAME_ROM+$2AF6  ; the cursor's draw (the START / CONTINUE prints: $2AA2, $2AB0)

; ------------------------------------------------------------------------------
; Title_Hook (link.py TITLE_HOOKS: jsr from the title loop's $2B36, `lea $C(a7),a7` replaced).
; d3-d7 the loop's (above); every other register kept.
; ------------------------------------------------------------------------------
Title_Hook:
    cmpi.l  #TITLE_AT_LOOP, (sp)
    bne     Title_Draw              ; one of the drawing sites
    move.l  (sp), 12(sp)            ; the replaced instruction: the three reads' arguments popped
    lea     12(sp), sp
    movem.l d0-d2/a0-a1, -(sp)
    addq.w  #1, SHIM_TITLE_PASS
    st      SHIM_COOP_NEW           ; the next game's first step sets the co-op's block up, and
    clr.b   SHIM_COOP_LIVE          ; until then it is no game's (coop.asm Coop_Setup)
    bsr     Bios_Credits            ; -1 none counted, else the credits (BCD): kept in a1
    movea.w d0, a1
    tst.w   SHIM_TITLE_STATE
    bne.s   .open
    clr.w   SHIM_TITLE_IDLE         ; the title opens: from the resume, or after a game
    lea     BIOS_PLAYER_MOD1, a0    ; after a game: P1's and P2's game over (the BIOS's
    moveq   #1, d1                  ; convention, recon 10; the BIOS clears them at every USER;
.mod:                               ; coop.asm Coop_Out sets a player out's already)
    cmpi.b  #PLAYER_MOD_PLAYING, (a0)
    bne.s   .over
    move.b  #PLAYER_MOD_OVER, (a0)
.over:
    addq.l  #1, a0
    dbra    d1, .mod
    tst.w   d0
    ble.s   .open
    move.w  BIOS_COMPULSION_RELOAD, d1  ; its countdown whole: the SNK BIOS's setting (seconds,
    bne.s   .reload                 ; frames), or TITLE_COUNTDOWN where a BIOS keeps its own
    move.w  #TITLE_COUNTDOWN, d1    ; elsewhere and that word is 0 (0 would start a game at once)
.reload:
    move.w  d1, BIOS_COMPULSION_TIMER
.open:
    move.w  #TITLE_LOOP, SHIM_TITLE_STATE
    tst.w   d0
    bne.s   .menu
    bsr     Title_NoCoin            ; no credit: INSERT COIN, no menu, no edge
    bra.s   .text
.menu:
    tst.w   SHIM_TITLE_COIN
    beq.s   .text
    bsr     Title_Menu              ; the first credit: the menu back (the cursor on START)
    moveq   #1, d5                  ; and no choice in this pass: a trigger down now (first seen,
                                    ; or held from before, when there was no menu) was meant for
                                    ; nothing: never START with the new credit (N1)
.text:
    move.w  a1, d0
    bsr     Title_Counts            ; CREDIT nn, TIME nn
    cmpi.w  #USER_REQ_TITLE, SHIM_BIOS_MODE
    beq.s   .mode
    bclr    #COOP_NEW_PROMPT, SHIM_COOP_NEW ; (the demo's game shows no join prompt: coop.asm)
    bsr     Demo_Title              ; the demo's title: the text, then its START (demo.asm)
    bra     .out
.mode:
    move.w  sr, -(sp)
    ori.w   #$0700, sr              ; no VBlank (PLAYER_START, the BIOS's count) until it is set
    moveq   #0, d2                  ; 1: AUTO FIRE toggled, its item redrawn once unmasked (.done)
    bclr    #COOP_KEY_SEEN, SHIM_COOP_P2KEY ; P2's START the BIOS dropped (the US BIOS: coop.asm
    beq.s   .req                    ; Coop_P2Key)
    tst.w   SHIM_START_REQ
    bne.s   .req                    ; (a START the BIOS passed: that one)
    bsr     Title_P2
    bne.s   .req                    ; (one credit: nothing, as the BIOS's handshake)
    move.w  #2, SHIM_START_REQ      ; two taken: a two-player game, as PLAYER_START's
.req:
    tst.w   SHIM_START_REQ
    bne.s   .start
    tst.w   SHIM_TITLE_KWAIT
    beq.s   .edge
    cmpi.w  #TITLE_CONFIG, d4
    bne.s   .kdrop
    moveq   #1, d3                  ; CONFIG's choice held back last pass (the KAKUSI code's window,
    moveq   #0, d5                  ; .config): judged again in this one (no stick edge, a trigger
    moveq   #1, d7                  ; edge), whatever the triggers are now (let go: CONFIG)
    bra.s   .config
.kdrop:
    clr.w   SHIM_TITLE_KWAIT        ; (the cursor left CONFIG: a guard. Nothing moves it in the
                                    ; window: its passes kill the stick edge, and it opens only
                                    ; where no credit is counted, so no Title_Menu)
.edge:
    tst.w   d5
    bne     .stay
    tst.w   d7
    beq     .stay
    move.w  a1, d0
    cmpi.w  #TITLE_CONFIG, d4       ; a choice: item 2 (CONFIG, or AUTO FIRE), or START / CONTINUE
    bne.s   .item
    tst.w   d0
    bmi.s   .config                 ; no credit counted: CONFIG
    bra     .toggle                 ; counted (credits in: none has no edge, Title_NoCoin)
.item:
    clr.b   SHIM_COOP_START2        ; A on START or CONTINUE: one player
    tst.w   d0
    bmi.s   .game                   ; no credit counted
    bsr     Title_Spend             ; (none in: no edge comes here, but the check holds)
    beq.s   .game
    moveq   #0, d7                  ; no credit taken: no choice
    bra     .stay
.start:
    cmpi.w  #2, SHIM_START_REQ      ; START: a new game, whatever the cursor is on; P2's START
    seq     SHIM_COOP_START2        ; (PLAYER_START: 2) a two-player one (coop.asm Coop_Starts
    clr.w   SHIM_START_REQ          ; joins P2 at its first step)
    moveq   #0, d4
    moveq   #1, d3                  ; (no stick edge)
    moveq   #0, d5
    moveq   #1, d7                  ; the loop chooses START
.game:
    move.w  #TITLE_FRESH, SHIM_TITLE_STATE  ; after the game, the title opens again
    move.b  #PLAYER_MOD_PLAYING, BIOS_PLAYER_MOD1   ; P1 plays (the BIOS's convention: its play
    bra.s   .leave                  ; time's count, $C12BF8; final review M3)
.config:
    move.b  REG_P1CNT, d0           ; the KAKUSI code's window: C and D held and one trigger of A
    andi.b  #$F0, d0                ; and B (active low: bits 4-7 D C B A ... A bit 4, B bit 5)
    cmpi.b  #$10, d0                ; C, D, B held, A not yet
    beq.s   .kwait
    cmpi.b  #$20, d0                ; C, D, A held, B not yet
    bne.s   .chosen
.kwait:
    cmpi.w  #TITLE_KWAIT_PASSES, SHIM_TITLE_KWAIT
    bhs.s   .chosen                 ; the window over: CONFIG (the gate sees three of the four)
    addq.w  #1, SHIM_TITLE_KWAIT
    moveq   #0, d7                  ; no choice in this pass (and the next pass's d5 is 0: the
    moveq   #1, d3                  ; choice is judged again then); no cursor move either
    clr.w   SHIM_TITLE_IDLE
    bra.s   .wait
.chosen:
    move.w  #TITLE_MENU, SHIM_TITLE_STATE   ; CONFIG (KAKUSI), then back to this loop
.leave:
    clr.w   SHIM_TITLE_KWAIT
    moveq   #1, d3                  ; no stick edge in this pass: the loop chooses the item judged
                                    ; here (its cursor move comes before its choice: $2B3A-$2BAC)
    move.b  #USER_MODE_GAME, BIOS_USER_MODE ; the countdown paused, no forced start
    clr.w   SHIM_TITLE_ON
    clr.w   SHIM_TITLE_IDLE
    bra.s   .done
.toggle:
    lea     SHIM_KEEP, a0           ; AUTO FIRE's toggle: the block's byte, the block sealed again
    eori.b  #1, KEEP_AUTOFIRE(a0)
    bsr     Keep_Seal               ; (resume.asm; uses d0-d1)
    moveq   #1, d2                  ; the item's text redrawn after the mask (.done)
    moveq   #1, d5                  ; no choice: no trigger edge for the loop (d7 kept: held on, the
    moveq   #1, d3                  ; next pass sees none either); no stick edge: the cursor stays
    clr.w   SHIM_TITLE_IDLE         ; (an input; the countdown runs on: .wait, USER_MODE 1)
    bra.s   .wait
.stay:
    move.w  d6, d1                  ; any stick or trigger held: not idle
    or.w    d7, d1
    beq.s   .idle
    clr.w   SHIM_TITLE_IDLE
    bra.s   .wait
.idle:
    move.w  a1, d0
    bgt.s   .wait                   ; credits in: the countdown starts a game instead
    addq.w  #1, SHIM_TITLE_IDLE
    cmpi.w  #TITLE_IDLE_FRAMES, SHIM_TITLE_IDLE
    bhs     Bios_Return             ; idle: back to the BIOS (its demo); never returns
.wait:
    move.w  #1, SHIM_TITLE_ON       ; waiting: the next VBlank's START is the title's
    move.w  a1, d0
    ble.s   .done                   ; no countdown: USER_MODE stays 2
    move.b  #1, BIOS_DEMO_COIN      ; credits seen (else, in USER_MODE 1 with credits, the BIOS
                                    ; would end this title as a demo: a power-on with credits)
    move.b  #USER_MODE_TITLE, BIOS_USER_MODE    ; the BIOS counts the countdown
.done:
    move.w  (sp)+, sr
    tst.w   d2
    beq.s   .out
    bsr     Title_AutoFire          ; a toggle's: its 13 cells drawn with the VBlank free to come
.out:
    movem.l (sp)+, d0-d2/a0-a1
    rts

; ------------------------------------------------------------------------------
; Title_Draw (Title_Hook from the title's drawing, $2A82-$2B0A: the title's opening and its redraw
; back from CONFIG): the replaced `pea $C.w` / `pea $5.w` pushed. Where credits are counted,
; CONFIG's print gets AUTO FIRE's string for the block's byte instead (the one pushed before the
; x); with no credit in (Bios_Credits 0), the START, CONTINUE and item 2 prints get an empty one
; and the cursor's character is 0 (Text8's blank cell). So the menu and the cursor are never on
; the screen at 0 credits, not even before the loop's first pass; and SHIM_TITLE_COIN is set, so
; a credit counted before that pass brings the menu (Title_Menu: fix round 1, I1). Every register
; kept.
; ------------------------------------------------------------------------------
Title_Draw:
    move.l  (sp), -(sp)             ; the return address, the replaced push's long below it
    move.l  d0, -(sp)
    bsr     Bios_Credits
    cmpi.l  #TITLE_AT_CURSOR, 4(sp)
    beq.s   .cursor
    move.l  #TITLE_MENU_X, 8(sp)    ; pea $C.w: the item's x
    cmpi.l  #TITLE_AT_CONFIG, 4(sp)
    beq.s   .config
    tst.w   d0
    bne.s   .out
.empty:
    move.l  #TITLE_STR_EMPTY, 16(sp)    ; (above: the y, then the string)
.blank:
    move.w  #1, SHIM_TITLE_COIN     ; the menu not drawn: the first pass with a credit draws it
    bra.s   .out
.config:
    tst.w   d0
    bmi.s   .out                    ; none counted: CONFIG
    beq.s   .empty
    move.l  #TITLE_STR_AF_OFF, 16(sp)   ; credits: AUTO FIRE, the block's
    tst.b   SHIM_KEEP+KEEP_AUTOFIRE
    beq.s   .out
    move.l  #TITLE_STR_AF_ON, 16(sp)
    bra.s   .out
.cursor:
    move.l  #TITLE_CURSOR, 8(sp)    ; pea $5.w: the cursor's character
    tst.w   d0
    bne.s   .out
    clr.l   8(sp)                   ; no credit: a blank cell, no cursor
    bra.s   .blank
.out:
    move.l  (sp)+, d0
    rts

; Title_NoCoin: INSERT COIN blinking on its row; no stick edge (d3) and no trigger edge (d5): with
; no credit in, nothing is chosen or moved. START, CONTINUE and item 2 were printed empty and the
; cursor blank (the drawing's sites: Title_Draw). Uses d0-d2/a0.
Title_NoCoin:
    move.w  #1, SHIM_TITLE_COIN
    moveq   #1, d3
    moveq   #1, d5
    lea     TITLE_STR_COIN, a0
    moveq   #TITLE_COIN_X, d0
    moveq   #TITLE_COIN_Y, d1
    btst    #TITLE_BLINK, SHIM_TITLE_PASS+1
    beq     Title_Puts              ; on
    bra     Title_Wipe              ; off

; Title_Menu: the first credit in: START, CONTINUE and AUTO FIRE drawn, INSERT COIN off, the
; cursor drawn on START (as the title opens; its cell on item d4's row, blank till now, cleared).
; Uses d0-d2/a0.
Title_Menu:
    clr.w   SHIM_TITLE_COIN
    lea     TITLE_STR_COIN, a0
    moveq   #TITLE_COIN_X, d0
    moveq   #TITLE_COIN_Y, d1
    bsr     Title_Wipe
    lea     GAME_STR_START, a0
    moveq   #TITLE_MENU_X, d0
    moveq   #TITLE_MENU_Y, d1
    bsr     Title_Puts
    lea     GAME_STR_CONT, a0
    moveq   #TITLE_MENU_X, d0
    moveq   #TITLE_MENU_Y+2, d1
    bsr     Title_Puts
    bsr     Title_AutoFire
    moveq   #TITLE_CUR_X, d0
    move.w  d4, d1
    add.w   d1, d1
    addi.w  #TITLE_MENU_Y, d1
    moveq   #0, d2
    bsr     Text_Put
    moveq   #0, d4
    moveq   #TITLE_MENU_Y, d1
    moveq   #TITLE_CURSOR, d2
    bra     Text_Put

; Title_AutoFire: item 2's text where credits are counted, AUTO FIRE OFF / ON as the preserved
; block's byte is. Uses d0-d2/a0.
Title_AutoFire:
    lea     TITLE_STR_AF_OFF, a0
    tst.b   SHIM_KEEP+KEEP_AUTOFIRE
    beq.s   .put
    lea     TITLE_STR_AF_ON, a0
.put:
    moveq   #TITLE_MENU_X, d0
    moveq   #TITLE_MENU_Y+2*TITLE_CONFIG, d1
    bra     Title_Puts

; Title_Counts: d0 = Bios_Credits' answer (kept). Counted: CREDIT nn; with credits, TIME nn (the
; BIOS's countdown, BCD seconds), else its cells blank. Uses d1-d2/a0.
Title_Counts:
    tst.w   d0
    bmi.s   .out
    move.w  d0, -(sp)
    lea     TITLE_STR_CREDIT, a0
    moveq   #TITLE_CREDIT_X, d0
    moveq   #TITLE_CREDIT_Y, d1
    bsr     Title_Puts
    move.w  (sp), d2
    bsr     Title_Bcd
    lea     TITLE_STR_TIME, a0
    moveq   #TITLE_TIME_X, d0
    moveq   #TITLE_TIME_Y, d1
    tst.w   (sp)
    beq.s   .notime
    tst.b   BIOS_COMPULSION_OFF
    bne.s   .notime                 ; the BIOS does not count it (final review I2): no TIME
    bsr     Title_Puts
    move.b  BIOS_COMPULSION_TIMER, d2
    bsr     Title_Bcd
    bra.s   .done
.notime:
    bsr     Title_Wipe              ; "TIME " and the two digits' cells
    moveq   #0, d2
    bsr     Text_Put
    addq.w  #1, d0
    bsr     Text_Put
.done:
    move.w  (sp)+, d0
.out:
    rts

; Title_Spend: A on START or CONTINUE takes P1's credit (and the US BIOS fallback's join: coop.asm
; Coop_Spend): CREDIT_CHECK, then CREDIT_DOWN if it left the request (interrupts masked by the
; caller: SYSTEM_IO's coin count does not run in between). Title_SpendDec: as many as
; BIOS_CREDIT_DEC's P1 byte (Title_P2's two). Z set: taken. Every register kept but the condition
; codes.
Title_Spend:
    move.b  #$01, BIOS_CREDIT_DEC   ; P1: one credit
Title_SpendDec:
    movem.l d0-d7/a0-a6, -(sp)
    clr.b   BIOS_CREDIT_DEC+1
    jsr     CREDIT_CHECK            ; clears the byte if the credits are short
    tst.b   BIOS_CREDIT_DEC
    beq.s   .short
    jsr     CREDIT_DOWN
    movem.l (sp)+, d0-d7/a0-a6
    move.w  #4, ccr                 ; Z: taken
    rts
.short:
    movem.l (sp)+, d0-d7/a0-a6
    move.w  #0, ccr
    rts

; Title_P2 (the masked pass, a1 Bios_Credits' answer): P2's START that the BIOS dropped (the US
; BIOS fallback, coop.asm Coop_P2Key: only where credits are counted) is a two-player game for two of
; P1's credits, taken here (Title_SpendDec), as PLAYER_START's handshake takes them elsewhere; with
; one in, nothing. Z set: taken. Uses d0.
Title_P2:
    move.w  a1, d0
    cmpi.w  #2, d0                  ; (BCD: 2 or more)
    blt.s   .short
    move.b  #$02, BIOS_CREDIT_DEC
    bra.s   Title_SpendDec
.short:
    moveq   #1, d0                  ; (not Z)
    rts

; Title_Puts: the string at a0 (0 ends it) from field cell (d0, d1) on; Title_Wipe: as many cells
; blank. d0 past the last cell, a0 past the 0; d2 used.
Title_Puts:
    move.b  (a0)+, d2
    beq.s   .out
    bsr     Text_Put
    addq.w  #1, d0
    bra.s   Title_Puts
.out:
    rts
Title_Wipe:
    moveq   #0, d2
.cell:
    tst.b   (a0)+
    beq.s   .out
    bsr     Text_Put
    addq.w  #1, d0
    bra.s   .cell
.out:
    rts

; Title_Bcd: the BCD byte d2 as two digits from (d0, d1); d0 past them. d2 used.
Title_Bcd:
    move.w  d2, -(sp)
    lsr.b   #4, d2
    addi.b  #'0', d2
    bsr     Text_Put
    addq.w  #1, d0
    move.w  (sp)+, d2
    andi.b  #$0F, d2
    addi.b  #'0', d2
    bsr     Text_Put
    addq.w  #1, d0
    rts

TITLE_STR_COIN:
    dc.b    "INSERT COIN", 0
TITLE_STR_CREDIT:
    dc.b    "CREDIT ", 0
TITLE_STR_TIME:
    dc.b    "TIME ", 0
TITLE_STR_EMPTY:
    dc.b    0
TITLE_STR_AF_OFF:                   ; (the same length: ON's redraw covers OFF's last cell)
    dc.b    "AUTO FIRE OFF", 0
TITLE_STR_AF_ON:
    dc.b    "AUTO FIRE ON ", 0
    even
