; ==============================================================================
; NEO-CHORENSHA SHIM: BIOS ENTRY POINTS, FAULT CATCHER; THE SERVICES THE ORIGINAL'S CODE CALLS
; ==============================================================================
    include "neogeo.inc"
    include "shim.inc"              ; the shim's state in the port reserve
    include "game.inc"              ; build/link (make link): the game's addresses
    include "header.asm"

; USER: the BIOS calls this with a request (BIOS_USER_REQUEST) and expects SYSTEM_RETURN back.
; 0 = first boot init (no backup RAM to set up), 1 = eye catcher (none: the header's $114):
; straight back. 2 = demo, 3 = title: the game resumes in that mode (bios.asm) and never
; returns here; it goes back to the BIOS through SYSTEM_RETURN (Bios_Return, or the BIOS's own
; from inside SYSTEM_IO). PLAYER_START and DEMO_END are bios.asm's.
USER:
    move.b  d0, REG_WATCHDOG
    moveq   #0, d7
    move.b  BIOS_USER_REQUEST, d7
    cmpi.w  #USER_REQ_DEMO, d7
    beq.s   Shim_Boot
    cmpi.w  #USER_REQ_TITLE, d7
    beq.s   Shim_Boot
    jmp     SYSTEM_RETURN

COIN_SOUND:                         ; the BIOS calls this on a coin: the original has no coin
    rts                             ; sound (Plan 5 design, non-goals)

; ------------------------------------------------------------------------------
; Shim_Boot: take over from the BIOS (interrupts off), then resume the original's code at
; its title menu (resume.asm) in the mode d7.w (USER_REQ_DEMO / USER_REQ_TITLE). The magic tells
; tests/neo/lib.lua the fault record is live. SHIM_BIOS_MODE 0 until the resume sets it: the
; settle frames' VBlanks only count the frame and call SYSTEM_IO (resume.asm Shim_VBlank, settling),
; nothing on what the last run left; the title's flag, the start request and the sound ring are
; cleared too, so nothing acts on any of it.
; ------------------------------------------------------------------------------
Shim_Boot:
    move.w  #$2700, sr
    move.b  d0, REG_WATCHDOG
    lea     STACK_TOP, sp
    clr.w   SHIM_BIOS_MODE
    clr.w   SHIM_TITLE_ON           ; (the last run's: PLAYER_START reads it in the settle frames)
    clr.w   SHIM_START_REQ
    clr.l   SHIM_SND_COUNT          ; the sound ring empty: the settle frames' drains send nothing
    clr.l   SHIM_SND_DONE           ; of the last run's (calls a return left in it) or of RAM's
    clr.w   SHIM_SND_MUSIC          ; power-on contents
    clr.l   SHIM_FAULT
    clr.l   SHIM_FAULT+4
    clr.l   SHIM_HEARTBEAT
    clr.l   SHIM_FAULT_PC
    clr.l   SHIM_FAULT_ARG
    clr.w   SHIM_RESTARTS
    move.l  #SHIM_MAGIC_VALUE, SHIM_MAGIC
    move.b  d0, REG_SWPROM          ; the cart's vectors from now on
    move.w  #IRQACK_ALL, REG_IRQACK
    move.b  d0, REG_CRTFIX          ; fix layer from the cart S-ROM
    ifd SHIM_TEST_FAULT
    illegal                         ; make cart SHIM_TEST_FAULT=1: vector 4 must be reported
    endif
    ; two VBlanks before the game runs: a debugger or test script sees the cart's vectors in
    ; place and the magic set, and arms its P-ROM taps (tests/neo/lib.lua)
    move.w  #$2000, sr
    move.l  SHIM_HEARTBEAT, d1
    addq.l  #2, d1
.settle:
    move.b  d0, REG_WATCHDOG
    cmp.l   SHIM_HEARTBEAT, d1
    bhi.s   .settle
    jmp     Shim_Resume

; ------------------------------------------------------------------------------
; Shim_Fault: store the vector number and the stacked PC at SHIM_FAULT and halt
; (kicking the watchdog so the machine stays put). Bus and address errors stack
; 8 extra bytes below SR/PC.
; ------------------------------------------------------------------------------
FAULT_ENTRY macro
Shim_Fault\1:
    move.w  #$2700, sr
    move.l  #\2, d7
    move.l  \3(sp), d6              ; stacked PC
    bra     Shim_Fault
    endm

    FAULT_ENTRY Bus,2,10
    FAULT_ENTRY Addr,3,10
    FAULT_ENTRY Illegal,4,2
    FAULT_ENTRY Div0,5,2
    FAULT_ENTRY Chk,6,2
    FAULT_ENTRY Trapv,7,2
    FAULT_ENTRY Priv,8,2
    FAULT_ENTRY LineA,10,2
    FAULT_ENTRY Trap0,32,2
    FAULT_ENTRY Trap1,33,2
    FAULT_ENTRY Trap2,34,2
    FAULT_ENTRY Trap3,35,2
    FAULT_ENTRY Trap5,37,2
    FAULT_ENTRY Trap6,38,2
    FAULT_ENTRY Trap7,39,2
    FAULT_ENTRY Trap8,40,2
    FAULT_ENTRY Trap9,41,2
    FAULT_ENTRY Trap10,42,2
    FAULT_ENTRY Trap11,43,2
    FAULT_ENTRY Trap12,44,2
    FAULT_ENTRY Trap13,45,2
    FAULT_ENTRY Trap14,46,2

Shim_Fault:
    move.l  d7, SHIM_FAULT
    move.l  d6, SHIM_FAULT+4
.halt:
    move.b  d0, REG_WATCHDOG
    bra.s   .halt

; ------------------------------------------------------------------------------
; The services. Their labels (Shim_<xsp name> among them) must come before game.asm.
; ------------------------------------------------------------------------------
    include "resume.asm"
    include "bios.asm"
    include "title.asm"
    include "config.asm"
    include "demo.asm"
    include "coop.asm"
    include "dos.asm"
    include "iocs.asm"
    include "mcdrv.asm"
    include "xsp.asm"
    include "sprites.asm"
    include "view.asm"
    include "text.asm"
    include "palette.asm"
    include "sound.asm"

; The art's equates and the background tile maps (build/gfx/gfx.inc, make gfx: tools/mkgfx.py).
    include "gfx.inc"
    if (SPR_TILE_BASE<1)|(SPR_TILE_BASE>8)|(PAL_SPR_BASE!=0)
    fail "sprites.asm STORE: addq #SPR_TILE_BASE (1-8); palette = colour block (PAL_SPR_BASE 0)"
    endif
    if PAL_P2_BASE!=$20
    fail "sprites.asm ATTR: player 2's palettes are INFO bit 13's $20 + block (PAL_P2_BASE $20)"
    endif
    if (BG_COLS!=16)|(BG_ROWS!=32)
    fail "sprites.asm Bg_Init: the background tile maps are 16 sprites of 32 tiles"
    endif
    if (STRIP_COLS!=4)|(STRIP_ROW!=2)|(STRIP_ROWS!=28)
    fail "text.asm Text_Init: the side strips are fix columns 0-3 and 36-39, rows 2-29"
    endif

; ==============================================================================
; The game's pieces in P-ROM (build/link/game.asm, generated): the XSP jump table and the
; PC-relative stubs at $7C00-$7FFF, the game at GAME_ROM, then its registers, stack and RAM
; images. Keep this last: its XSP slots use the Shim_<name> labels defined above.
; ==============================================================================
    include "game.asm"

; palettes.bin (build/gfx, make gfx) above the game's pieces (palette.asm), then the attract demo's
; stream (data/demo.bin, frozen: demo.asm), then the co-op's code (coop.asm: its labels fill the
; game hooks' slots in game.asm above).
    PAL_DATA
    DEMO_DATA
    COOP_CODE
