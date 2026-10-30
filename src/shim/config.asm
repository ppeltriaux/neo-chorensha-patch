; ==============================================================================
; CONFIG'S AUTO FIRE (Plan 5 Task 5; docs/notes/plan5-recon.md section 4). The original's CONFIG runs
; as it is, with its item 1, SCREEN, made AUTO FIRE and (the 2026-10-28 request) its item 0, XSP
; MODE, gone: link.py TITLE_CODE leaves XSP MODE's line unprinted and numbers the items one down,
; so the cursor starts on AUTO FIRE (now item 0, where Up stops) and the port stays in XSP MODE 2,
; the start-up's; the header two rows up, the lines below it four (CONFIG_ROWS: AUTO FIRE on row
; 15, its "exit" on 23, out of the screen's last 8 lines and off the bombs' rows). link.py's
; TITLE_HOOKS call Config_Hook from three sites, told apart by the return address:
;   * the item's label ($2CF8, `pea $2C80(pc)`: "SCREEN"): "AUTO FIRE" is pushed instead;
;   * the loop's print of the item's value ($2DA6, `pea $4.w`: the hex print's digit count; that
;     print, $2DBA, and the "0x" before it are nops): 4 is pushed, and ON or OFF drawn at (CFG_AF_X,
;     CFG_AF_Y) with Text_Put, every pass, as the loop prints the other values;
;   * the item's handler ($2F52, `cmp.w #6,d4`; `bra.w $2D54`, the loop, follows): Right, Left or A
;     (d4 6, 4, 1) toggle it; B (2) and A+B (3) leave it, as the other items' handlers ignore them.
; AUTO FIRE's only home is the preserved block (shim.inc KEEP_AUTOFIRE: 0 OFF, 1 ON), so a toggle
; seals the block again (resume.asm Keep_Seal) and the setting survives a return to the BIOS; its
; power-on default is the soft DIP's (header.asm SOFT_DIP_AUTOFIRE, resume.asm Keep_Save). What it
; does in play: iocs.asm Iocs_JOYGET. CONFIG (and KAKUSI) is reached only where no credit is
; counted (the AES, the MVS on Free Play): on the MVS with credits counted the title's own item 2,
; in CONFIG's place, is AUTO FIRE OFF / ON and toggles the same byte (title.asm; the 2026-10-28
; request), and the other settings keep their defaults. SCREEN's $17510 is never written and its
; CRTC set-up ($4A9C) never reached from CONFIG (the handler's rest is dead); XSP MODE's handler
; ($2F04: $221F4 1-3 and the xsp_mode2 call) is never reached, so $221F4 stays 2.
; ==============================================================================
CFG_AT_LABEL    EQU GAME_ROM+$2CFC  ; Config_Hook's return addresses (link.py TITLE_HOOKS)
CFG_AT_HANDLER  EQU GAME_ROM+$2F56
CFG_AF_X        EQU 20              ; AUTO FIRE's value: the column of the other values' digits
CFG_AF_Y        EQU 15              ; AUTO FIRE's row (SCREEN's 19 in the original: CONFIG_ROWS)
CFG_AF_DIGITS   EQU 4               ; the push the value's site replaces ($2DA6: pea $4.w)

; ------------------------------------------------------------------------------
; Config_Hook (link.py TITLE_HOOKS: jsr HOOKJT_Config_Hook.w from CONFIG's $2CF8, $2DA6, $2F52).
; The pushes' sites leave the long pushed; every register and the stack below it kept. The
; condition codes are not: the code after each site sets them before it tests them.
; ------------------------------------------------------------------------------
Config_Hook:
    cmpi.l  #CFG_AT_HANDLER, (sp)
    beq.s   Config_Toggle           ; (the handler's site replaced no push)
    move.l  (sp), -(sp)             ; a push replaced: the return address, the pushed long below it
    cmpi.l  #CFG_AT_LABEL, (sp)
    bne.s   .value
    move.l  #CFG_STR_AF, 4(sp)      ; the label: "AUTO FIRE"
    rts
.value:
    move.l  #CFG_AF_DIGITS, 4(sp)   ; the value's: the digits pushed (its print is a nop)
    movem.l d0-d2/a0, -(sp)
    lea     CFG_STR_OFF, a0
    tst.b   SHIM_KEEP+KEEP_AUTOFIRE
    beq.s   .show
    lea     CFG_STR_ON, a0
.show:
    moveq   #CFG_AF_X, d0
    moveq   #CFG_AF_Y, d1
    bsr     Title_Puts
    movem.l (sp)+, d0-d2/a0
    rts

; Config_Toggle: d4 = the loop's action (6 Right, 4 Left, 1 A, 2 B, 3 both): Right, Left and A
; toggle AUTO FIRE in the preserved block and seal it. Every register kept.
Config_Toggle:
    cmpi.w  #6, d4
    beq.s   .flip
    cmpi.w  #4, d4
    beq.s   .flip
    cmpi.w  #1, d4
    bne.s   .out
.flip:
    movem.l d0-d1/a0, -(sp)
    lea     SHIM_KEEP, a0
    eori.b  #1, KEEP_AUTOFIRE(a0)
    bsr     Keep_Seal               ; the block valid with it (resume.asm)
    movem.l (sp)+, d0-d1/a0
.out:
    rts

CFG_STR_AF:
    dc.b    "AUTO FIRE", 0
CFG_STR_ON:
    dc.b    "ON ", 0
CFG_STR_OFF:
    dc.b    "OFF", 0
    even
