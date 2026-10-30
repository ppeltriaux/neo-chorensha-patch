; ==============================================================================
; NEO GEO HARDWARE / BIOS EQUATES AND THE SHIM'S WORK RAM MAP
; Hardware addresses as in neo-r-type's neogeo.inc (cross-checked with ngdevkit).
; ==============================================================================

; --- I/O registers -------------------------------------------------------------
REG_P1CNT       EQU $00300000   ; P1 joystick, active low: 0=U 1=D 2=L 3=R 4=A 5=B 6=C 7=D
REG_WATCHDOG    EQU $00300001   ; any byte write kicks the watchdog
REG_P2CNT       EQU $00340000   ; P2 joystick, same layout as REG_P1CNT
REG_STATUS_B    EQU $00380000   ; bit 0 P1 Start, 1 P1 Select, 2 P2 Start, 3 P2 Select (active low)
REG_DIPSW       EQU $00300001   ; R (the MVS): the hard DIP switches, active low (a write is the
                                ; watchdog's kick); DIP_FREE_PLAY clear = Free Play on
DIP_FREE_PLAY   EQU 6           ; (bit: the BIOS's own test, euro $C117E0 / $C1179A)
REG_SOUND       EQU $00320000   ; W: command to the Z80 (raises NMI) / R: Z80 reply
REG_SWPBIOS     EQU $003A0003   ; write: the BIOS's vectors at $000000
REG_SWPROM      EQU $003A0013   ; write: the cartridge's vectors at $000000
REG_CRTFIX      EQU $003A001B   ; write: fix layer from the cartridge S-ROM
REG_PALBANK0    EQU $003A001F   ; write: palette bank 0 (shown and at PALRAM)

; --- palette RAM ---------------------------------------------------------------
PALRAM          EQU $00400000   ; 256 palettes x 16 words (the bank selected); entry 0 of each is
                                ; transparent, palette 255 entry 15 the backdrop colour
PALRAM_SIZE     EQU $2000

; --- LSPC ----------------------------------------------------------------------
REG_LSPCMODE    EQU $003C0006   ; R: raster line in bits 15-7; W: bit 4 timer IRQ on, 5 reload on
                                ; TIMERLOW write, 6 reload at VBlank, 7 reload at 0
REG_TIMERHIGH   EQU $003C0008   ; timer reload value (pixel clocks, 384 per line), high word
REG_TIMERLOW    EQU $003C000A
REG_IRQACK      EQU $003C000C   ; bit 0 = cold reset, 1 = timer, 2 = VBlank
IRQACK_TIMER    EQU $0002
IRQACK_VBLANK   EQU $0004
IRQACK_ALL      EQU $0007

; --- LSPC video RAM (word addresses through the VRAM ports; neo-r-type's neogeo.inc) -------
REG_VRAMADDR    EQU $003C0000   ; VRAM address for the next REG_VRAMRW access
REG_VRAMRW      EQU $003C0002   ; VRAM data; the address then moves on by REG_VRAMMOD
REG_VRAMMOD     EQU $003C0004   ; signed address step after each REG_VRAMRW access
VRAM_SCB1       EQU $0000       ; sprite tile maps: 64 words per sprite (tile, attr) x 32 rows
VRAM_FIX        EQU $7000       ; fix map: 40 columns x 32 rows, column-major (32 words a column)
VRAM_FIX_SIZE   EQU $0500       ; visible rows: 2-29 (224 lines)
VRAM_SCB2       EQU $8000       ; shrink: $0FFF = full size
VRAM_SCB3       EQU $8200       ; (496 - y) << 7 | sticky << 6 | height in tiles (0 = not drawn)
VRAM_SCB4       EQU $8400       ; x << 7
SPR_Y_BASE      EQU 496         ; SCB3 Y field = SPR_Y_BASE - screen line (9 bits)

; --- BIOS RAM and calls (docs/notes/plan5-recon.md section 1: read from the euro and unibios40
; ROMs; the names are the NeoGeo dev wiki's) -------------------------------------------------
BIOS_SYSTEM_MODE  EQU $0010FD80 ; bit 7: 0 = BIOS in control, 1 = game (SYSTEM_RETURN clears it)
BIOS_SYSRET_STATUS EQU $0010FD81 ; what SYSTEM_RETURN does next (the BIOS's own: 3 after a start)
BIOS_MVS_FLAG     EQU $0010FD82 ; nonzero on an MVS (the credit code runs only there)
BIOS_COUNTRY_CODE EQU $0010FD83
BIOS_GAME_DIP     EQU $0010FD84 ; 16 bytes: the soft DIPs' values (+6: option 1, header.asm)
BIOS_P1CURRENT    EQU $0010FD96 ; P1's controller as SYSTEM_IO read it
BIOS_STATCURNT    EQU $0010FDAC ; the START / SELECT bits now
BIOS_STATCHANGE   EQU $0010FDAD ; ... their press edges (SYSTEM_IO's start check reads them)
BIOS_USER_REQUEST EQU $0010FDAE ; 0 = init, 1 = eye catcher, 2 = demo, 3 = title
BIOS_USER_MODE    EQU $0010FDAF ; 0 = boot, 1 = title / demo, 2 = game (USER_MODE_*)
BIOS_CREDIT_DEC   EQU $0010FDB0 ; 2 bytes, P1 / P2: BCD credits CREDIT_CHECK / CREDIT_DOWN take
BIOS_START_FLAG   EQU $0010FDB4 ; the START bits PLAYER_START is called with (bit 0 = P1); it
                                ; clears them to refuse a start (no credit is then taken)
BIOS_PLAYER_MOD1  EQU $0010FDB6 ; 4 bytes, P1-P4: 0 none, 1 playing, 2 continue, 3 game over
BIOS_COMPULSION_TIMER EQU $0010FDDA ; BCD seconds, then frames: the MVS forced start (USER_MODE 1
                                ; with credits)
BIOS_FRAME_COUNTER EQU $0010FE88 ; long: +1 every SYSTEM_IO
BIOS_DEMO_COIN    EQU $0010FEC5 ; byte: the BIOS's "credits seen" latch. In USER_MODE 1 with credits
                                ; and this 0, SYSTEM_IO ends the game (DEMO_END, SYSTEM_RETURN status
                                ; 6: a coin in the demo) and sets it; only SYSTEM_RETURN after a
                                ; game (status 3) clears it (euro $C1186E-$C11886, $C11452)
BIOS_CREDITS      EQU $00D00034 ; backup RAM, 2 bytes BCD: P1's and P2's credits (MVS)
BIOS_COMPULSION_OFF EQU $00D00043 ; backup RAM byte: the SNK BIOS's "game start compulsion" off
                                ; (not 0): no title request and no demo's end for a credit, the
                                ; countdown stopped (euro $C11272, $C11874, $C116FA). The US BIOS's
                                ; default is 1, the euro, japan and asia ones' and unibios40's 0
                                ; (final review I2, MAME 0.289)
BIOS_COMPULSION_RELOAD EQU $00D00044 ; backup RAM word: what the BIOS loads the compulsion timer
                                ; with at a coin and after a game (euro $C127C0, $C1147E)

USER_REQ_INIT     EQU 0         ; BIOS_USER_REQUEST
USER_REQ_EYE      EQU 1
USER_REQ_DEMO     EQU 2
USER_REQ_TITLE    EQU 3
USER_MODE_BOOT    EQU 0         ; BIOS_USER_MODE
USER_MODE_TITLE   EQU 1         ; title or demo: the forced start and the demo's end by a coin run
USER_MODE_GAME    EQU 2         ; a game: neither runs (START still calls PLAYER_START)
PLAYER_MOD_PLAYING EQU 1        ; BIOS_PLAYER_MOD1
PLAYER_MOD_OVER    EQU 3

BIOS_INIT_HARDWARE     EQU $00C00402
BIOS_EXC_BUS_ERROR     EQU $00C00408
BIOS_EXC_TRACE         EQU $00C00420
BIOS_UNINITIALIZED_INT EQU $00C0042C
BIOS_SPURIOUS_INT      EQU $00C00432
SYSTEM_INT1            EQU $00C00438
SYSTEM_RETURN          EQU $00C00444 ; back to the BIOS: never returns (the next USER resumes)
SYSTEM_IO              EQU $00C0044A ; once a frame in the game: controllers, coins, START; it
                                     ; may call PLAYER_START, or DEMO_END then SYSTEM_RETURN
CREDIT_CHECK           EQU $00C00450 ; BIOS_CREDIT_DEC: clears a player's byte if short
CREDIT_DOWN            EQU $00C00456 ; takes BIOS_CREDIT_DEC's credits

; --- Work RAM map (docs: Plan 2 global constraints) ------------------------------
; $100000-$10AFFF game objects placed in RAM
; $10B000-$10DFFF port reserve: shim state, XSP replacement, I/O shadow
; $10E000-$10EFFF stack (top $10F000)
; $10F000-$10F2FF the BIOS's stack (SYSTEM_RETURN sets SP = $10F300): never used
; $10F300-$10FFFF BIOS work area, never touched
SHIM_FAULT      EQU $0010B000   ; 8 bytes: long vector number, long stacked PC
SHIM_HEARTBEAT  EQU $0010B008   ; long, the VBlank handler increments it
STACK_TOP       EQU $0010F000

; --- Cartridge ---------------------------------------------------------------
NGH_NUMBER      EQU $0C68       ; this port's (unofficial) NGH number
RAM_BACKUP      EQU $00D00000   ; header field only: the port does not use backup RAM
RAM_BACKUP_SIZE EQU 0
