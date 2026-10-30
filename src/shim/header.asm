; ==============================================================================
; 68000 EXCEPTION VECTORS ($000000-$0000FF) AND CARTRIDGE HEADER ($000100)
; The shim's entry points are named here and defined in boot.asm, resume.asm (VBlank,
; timer), dos.asm (F-line), iocs.asm (trap #15) and mcdrv.asm (trap #4).
; ==============================================================================
    org     $000000
    dc.l    STACK_TOP               ; initial SSP
    dc.l    BIOS_INIT_HARDWARE      ; initial PC
    dc.l    Shim_FaultBus           ; 2 bus error
    dc.l    Shim_FaultAddr          ; 3 address error
    dc.l    Shim_FaultIllegal       ; 4 illegal instruction
    dc.l    Shim_FaultDiv0          ; 5 divide by zero
    dc.l    Shim_FaultChk           ; 6 CHK
    dc.l    Shim_FaultTrapv         ; 7 TRAPV
    dc.l    Shim_FaultPriv          ; 8 privilege violation
    dc.l    BIOS_EXC_TRACE   ; 9 trace
    dc.l    Shim_FaultLineA         ; 10 line 1010
    dc.l    Shim_FLine              ; 11 line 1111 (the original's DOS calls)
    dcb.l   4, $FFFFFFFF            ; 12-15 reserved
    dcb.l   8, $FFFFFFFF            ; 16-23 reserved
    dc.l    BIOS_SPURIOUS_INT       ; $000060
    dc.l    Shim_VBlank             ; $000064 level 1: VBlank
    dc.l    Shim_Level2             ; $000068 level 2: timer
    dc.l    $00000000               ; $00006C level 3: cold reset
    dcb.l   4, $00000000            ; levels 4-7
    dc.l    Shim_FaultTrap0, Shim_FaultTrap1, Shim_FaultTrap2, Shim_FaultTrap3 ; TRAP #0-3
    dc.l    Shim_MCDRV              ; TRAP #4 (MCDRV)
    dc.l    Shim_FaultTrap5, Shim_FaultTrap6, Shim_FaultTrap7, Shim_FaultTrap8
    dc.l    Shim_FaultTrap9, Shim_FaultTrap10, Shim_FaultTrap11, Shim_FaultTrap12
    dc.l    Shim_FaultTrap13, Shim_FaultTrap14 ; TRAP #5-14: vector reported
    dc.l    Shim_IOCS               ; TRAP #15 (IOCS)
    dcb.l   16, $FFFFFFFF           ; reserved

    org     $000100
    dc.b    "NEO-GEO", $00
    dc.w    NGH_NUMBER              ; $108 NGH number
    dc.l    $00100000               ; $10A program size
    dc.l    RAM_BACKUP              ; $10E MVS backup RAM start
    dc.w    RAM_BACKUP_SIZE         ; $112 MVS backup RAM size
    dc.b    $02                     ; $114 eye catcher: 2 = none
    dc.b    $00                     ; $115 eye catcher logo tile bank
    dc.l    Soft_DIPs               ; $116 JP
    dc.l    Soft_DIPs               ; $11A US
    dc.l    Soft_DIPs               ; $11E EU
    jmp     USER                    ; $122
    jmp     PLAYER_START            ; $128
    jmp     DEMO_END                ; $12E
    jmp     COIN_SOUND              ; $134
    dcb.b   70, $FF                 ; $13A unused
    dc.w    $0000                   ; $180
    dc.l    Security_Code           ; $182

    ; Fixed 61-word sequence the BIOS checks before it will boot the cart
Security_Code:                      ; $186
    dc.w    $7600, $4A6D, $0A14, $6600, $003C, $206D, $0A04, $3E2D
    dc.w    $0A08, $13C0, $0030, $0001, $3210, $0C01, $00FF, $671A
    dc.w    $3028, $0002, $B02D, $0ACE, $6610, $3028, $0004, $B02D
    dc.w    $0ACF, $6606, $B22D, $0AD0, $6708, $5088, $51CF, $FFD4
    dc.w    $3607, $4E75, $206D, $0A04, $3E2D, $0A08, $3210, $E049
    dc.w    $0C01, $00FF, $671A, $3010, $B02D, $0ACE, $6612, $3028
    dc.w    $0002, $E048, $B02D, $0ACF, $6606, $B22D, $0AD0, $6708
    dc.w    $5888, $51CF, $FFD8, $3607, $4E75

; Soft DIP block: 16-char name, 2 time settings, 2 count settings, 10 options (high nibble the
; default choice, low nibble the number of choices; 0 unused), then for each option used its
; 12-char name and a 12-char name per choice. The BIOS keeps the values at BIOS_GAME_DIP (MVS:
; the operator's, in backup RAM; set in the BIOS's soft-DIP menu).
SOFT_DIP_AUTOFIRE EQU BIOS_GAME_DIP+6 ; option 1: auto-fire's power-on default (0 OFF, 1 ON)
Soft_DIPs:
    dc.b    "CHOURENSHA      "
    dc.w    $FFFF, $FFFF            ; no time settings
    dc.b    $FF, $FF                ; no count settings
    dc.b    $02                     ; option 1: AUTO FIRE, 2 choices, default 0 (OFF)
    dcb.b   9, $00                  ; options 2-10 unused
    dc.b    "AUTO FIRE   "
    dc.b    "OFF         "
    dc.b    "ON          "
    even
