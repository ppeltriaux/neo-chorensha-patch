; ==============================================================================
; NEO-CHORENSHA SOUND DRIVER: Z80 RAM (z80asm). Hand-written; src/z80/sound.asm includes it and
; tests/neo/sound_driver.lua reads the driver's state by these names (name: equ $addr).
; RAM is $F800-$FFFF; init clears ZRAM_START..+ZRAM_CLEAR_LEN.
; ==============================================================================
ZRAM_START:     equ $F800
ZRAM_CLEAR_LEN: equ $0200
tick_pending:   equ $F800       ; set by the Timer B IRQ, taken by the main loop
queue_head:     equ $F801       ; command ring (QUEUE_PAGE): next to run
queue_tail:     equ $F802       ;   next free
cur_tune:       equ $F803       ; tune index playing on ADPCM-B, $FF = none
fading:         equ $F804       ; 1 while a fade runs
fx_cur:         equ $F805       ; effect index playing on ADPCM-A channel 0, $FF = none
fade_step:      equ $F806       ; the fade's attenuation so far, in 1/4 dB steps
fade_err:       equ $F807       ; word: the fade's step accumulator (+FADE_STEPS a tick)
fade_len:       equ $F809       ; word: the fade's length in ticks (fade_ticks[tune][speed])
intro_ticks:    equ $F80B       ; word: ticks until the loop's end is set, 0 = done
loop_end:       equ $F80D       ; word: the tune's loop end (256-byte units)
tick_count:     equ $F80F       ; word: Timer B ticks since init (wraps); read by the tests only
QUEUE_PAGE:     equ $F9         ; command ring at $F900
QUEUE_MASK:     equ $0F         ; 16 slots: 15 commands (one slot stays free)
STACK_TOP:      equ $FFFC
RAM_WAIT_PC:    equ $FFFE       ; the BIOS's $01: the driver parks here (jr $)
