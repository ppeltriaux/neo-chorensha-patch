; ==============================================================================
; NEO-CHORENSHA SOUND DRIVER (z80asm, the M1 ROM). Adapted from neo-r-type's
; src/z80/sample_driver.asm. Plays the original's recordings, stored by tools/mksound.py in the
; V-ROM (build/snd/vrom.bin) and described by build/snd/sound.inc (tables, command bytes):
;   music:   ADPCM-B. A tune's intro and loop are contiguous; it starts at the intro with END =
;            the intro's end and repeat on. START = the loop's start is written a short delay
;            after the key-on (written in the same instant, the key-on takes it and the intro is
;            skipped), so the chip restarts at the loop when the intro ends; intro_ticks Timer B
;            ticks after the key-on, END becomes the loop's end
;   fade:    the level falls linearly in dB, FADE_STEPS steps of 1/4 dB, over
;            fade_ticks[tune][speed] ticks (to about -30 dB), then the music stops. A fade during
;            a fade goes on from the level reached at the new speed; a play restores the level;
;            a fade with no music does nothing
;   effect:  ADPCM-A channel 0 only: a play keys it off, then starts the effect (one at a time)
; 68k -> Z80: REG_SOUND write raises the NMI, the command on port $00 (sound.inc CMD_*). Every
; command but the BIOS's $01/$03 is queued and answered at once with command | CMD_ECHO on
; port $0C. The BIOS's $01 (MVS slot switch) silences everything, parks the Z80 in RAM and
; replies $01; $03 resets. $02 (eye-catcher) is never sent (header $114 = 2) and is ignored.
; After $03 the NMI stays enabled (it is no hardware reset: port $08 was written by the first
; init) while init clears the RAM (ZRAM_CLEAR_LEN bytes, the command ring and its head and tail
; among them; the ldir alone is about 2.7 ms): a command sent in that window is echoed, then lost
; with the ring. The game's drain sends nothing then (the BIOS owns the Z80 while it sends $03);
; Plan 5's BIOS work must allow for it (docs/notes/sound.md, "The Z80 driver").
; YM2610 Timer B (TIMER_B_VALUE, Z80_TICK_HZ about 59.9 Hz) paces the intro and the fade.
; RAM: src/z80/zram.inc.
; ==============================================================================

PORT_FROM_68K:      equ $00
PORT_YM_ADDR_A:     equ $04     ; read: status 0, bit 7 = busy
PORT_YM_DATA_A:     equ $05
PORT_YM_ADDR_B:     equ $06     ; read: status 1, ADPCM end flags (A: bits 0-5, B: bit 7)
PORT_YM_DATA_B:     equ $07
PORT_ENABLE_NMI:    equ $08
PORT_TO_68K:        equ $0C

; YM2610 registers, port A. (Names must not start with a register name and "_": this
; z80asm reads A_KEY as the register a.)
YM_TIMER_B:         equ $26
YM_TIMER_CTRL:      equ $27
TIMER_B_RUN:        equ $2A     ; load B, enable B IRQ, reset B flag
TIMER_STOP:         equ $30
PB_CTRL1:           equ $10     ; bit 7 start, 4 repeat, 0 reset
PB_CTRL2:           equ $11     ; bits 7/6: left/right
PB_START:           equ $12     ; and $13
PB_END:             equ $14     ; and $15
PB_DELTA_N:         equ $19     ; and $1A
PB_LEVEL:           equ $1B
FLAG_CTRL:          equ $1C     ; 1 bits reset (and mask) end flags
; port B (ADPCM-A)
PA_KEY:             equ $00     ; channel bits: key on; | $80: key off
PA_TOTAL:           equ $01
PA_CH_LEVEL:        equ $08     ; + channel: bits 7/6 left/right, 4-0 level
PA_START_L:         equ $10     ; + channel
PA_START_H:         equ $18
PA_END_L:           equ $20
PA_END_H:           equ $28

PB_PAN:             equ $C0     ; music on both sides
PB_PLAY_REPEAT:     equ $90     ; start, repeat
FX_CH_BIT:          equ $01     ; effects: ADPCM-A channel 0
ALL_A_OFF:          equ $BF     ; key off the 6 ADPCM-A channels
START_DELAY:        equ 0       ; djnz count (0 = 256): 256 x 13 cycles = 0.83 ms at 4 MHz
FADE_STEPS:         equ 120     ; the fade: 120 steps of 1/4 dB = 30 dB
NONE:               equ $FF
OPCODE_JR_SELF:     equ $FE18   ; $18 $FE little-endian = jr $

    include "zram.inc"

    org $0000
    di
    jp      init

    ds      $0038 - $, $FF
irq:                                ; Timer B (IM 1): the main loop acknowledges it
    push    af
    ld      a, 1
    ld      (tick_pending), a
    pop     af
    reti

    ds      $0066 - $, $FF
nmi:                                ; a command from the 68k on port $00
    push    af
    in      a, (PORT_FROM_68K)
    cp      $01
    jp      z, cmd_01_wait_in_ram
    cp      $03
    jp      z, cmd_03_reset
    push    bc
    push    hl
    ld      b, a
    ld      a, (queue_tail)
    ld      l, a
    inc     a
    and     QUEUE_MASK
    ld      c, a
    ld      a, (queue_head)
    cp      c
    jr      z, nmi_reply            ; queue full: drop the newest command
    ld      h, QUEUE_PAGE
    ld      (hl), b
    ld      a, c
    ld      (queue_tail), a
nmi_reply:
    ld      a, b
    or      CMD_ECHO
    out     (PORT_TO_68K), a
    pop     hl
    pop     bc
    pop     af
    retn

    ds      $0100 - $, $FF
init:
    di
    im      1
    ld      sp, STACK_TOP
    ld      hl, ZRAM_START
    ld      de, ZRAM_START + 1
    ld      bc, ZRAM_CLEAR_LEN - 1
    ld      (hl), 0
    ldir
    call    stop_all
    ld      de, PA_TOTAL * 256 + ADPCMA_TOTAL
    call    ym_write_b
    ld      de, PA_CH_LEVEL * 256 + ADPCMA_LEVEL ; channel 0
    call    ym_write_b
    ld      de, YM_TIMER_CTRL * 256 + TIMER_STOP ; both timers off, both flags reset: the
    call    ym_write_a              ; BIOS's driver runs Timer A with its IRQ on, and an A flag
                                    ; it leaves set would hold the IRQ line (TIMER_B_RUN only
                                    ; turns A's IRQ off): the Z80 would tick at kHz, not at Timer B
    ld      de, YM_TIMER_B * 256 + TIMER_B_VALUE
    call    ym_write_a
    ld      de, YM_TIMER_CTRL * 256 + TIMER_B_RUN
    call    ym_write_a
    xor     a
    out     (PORT_ENABLE_NMI), a
    ei

main_loop:
    call    run_queue
    call    poll_fx
    ld      a, (tick_pending)
    or      a
    jr      z, main_loop
    xor     a
    ld      (tick_pending), a
    ld      de, YM_TIMER_CTRL * 256 + TIMER_B_RUN
    call    ym_write_a
    ei
    call    tick
    jr      main_loop

; run_queue: run every queued command
run_queue:
    ld      a, (queue_head)
    ld      hl, queue_tail
    cp      (hl)
    ret     z
    ld      l, a
    ld      h, QUEUE_PAGE
    ld      b, (hl)
    inc     a
    and     QUEUE_MASK
    ld      (queue_head), a
    ld      a, b
    call    run_cmd
    jr      run_queue

; run_cmd: a = command (sound.inc CMD_*); anything outside the set does nothing
run_cmd:
    cp      CMD_MUSIC_STOP
    jp      z, stop_music
    cp      CMD_FX_STOP
    jp      z, stop_fx
    cp      CMD_FX
    jr      c, rc_below_fx
    sub     CMD_FX
    cp      SFX_COUNT
    ret     nc
    jp      play_fx
rc_below_fx:
    cp      CMD_PLAY
    jr      c, rc_below_play
    sub     CMD_PLAY
    cp      MUSIC_COUNT
    ret     nc
    jp      play_tune
rc_below_play:
    sub     CMD_FADE
    ret     c
    cp      FADE_SPEEDS
    ret     nc
    jp      fade

; stop_all: silence ADPCM-A and ADPCM-B
stop_all:
    ld      de, PA_KEY * 256 + ALL_A_OFF
    call    ym_write_b
    ld      a, NONE
    ld      (fx_cur), a
    ld      de, FLAG_CTRL * 256 + $BF
    call    ym_write_a
    ld      de, FLAG_CTRL * 256 + $00
    call    ym_write_a
    ; fall through
stop_music:                         ; (a reset alone leaves its last level on the output)
    ld      de, PB_LEVEL * 256 + $00
    call    ym_write_a
    ld      de, PB_CTRL2 * 256 + $00
    call    ym_write_a
    ld      de, PB_CTRL1 * 256 + $01 ; reset
    call    ym_write_a
    ld      de, PB_CTRL1 * 256 + $00
    call    ym_write_a
    ld      a, NONE
    ld      (cur_tune), a
    xor     a
    ld      (fading), a
    ld      h, a
    ld      l, a
    ld      (intro_ticks), hl
    ret

; row: hl = table + a * de (a = row index)
row:
    inc     a
row_next:
    dec     a
    ret     z
    add     hl, de
    jr      row_next

; play_tune: a = tune index
play_tune:
    push    af
    call    stop_music
    pop     af
    ld      (cur_tune), a
    ld      hl, music_table
    ld      de, MUSIC_ROW
    call    row
    ld      e, (hl)                 ; intro start
    inc     hl
    ld      d, (hl)
    inc     hl
    ld      a, PB_START
    call    ym_write_word_a
    ld      e, (hl)                 ; intro end
    inc     hl
    ld      d, (hl)
    inc     hl
    ld      a, PB_END
    call    ym_write_word_a
    ld      c, (hl)                 ; loop start
    inc     hl
    ld      b, (hl)
    inc     hl
    ld      e, (hl)                 ; loop end
    inc     hl
    ld      d, (hl)
    inc     hl
    ld      (loop_end), de
    ld      e, (hl)                 ; delta-N
    inc     hl
    ld      d, (hl)
    inc     hl
    ld      a, PB_DELTA_N
    call    ym_write_word_a
    ld      e, (hl)                 ; intro ticks
    inc     hl
    ld      d, (hl)
    ld      (intro_ticks), de
    ld      de, PB_LEVEL * 256 + ADPCMB_LEVEL
    call    ym_write_a
    ld      de, PB_CTRL2 * 256 + PB_PAN
    call    ym_write_a
    ld      de, PB_CTRL1 * 256 + PB_PLAY_REPEAT
    call    ym_write_a
    push    bc                      ; let the key-on take the intro's start first
    ld      b, START_DELAY
pt_delay:
    djnz    pt_delay
    pop     de
    ld      a, PB_START             ; the repeat goes to the loop
    jp      ym_write_word_a

; fade: a = speed index. No music: nothing. Not fading yet: from full level.
fade:
    ld      c, a
    ld      a, (cur_tune)
    cp      NONE
    ret     z
    ld      hl, fade_ticks
    ld      de, FADE_ROW
    call    row
    ld      a, c
    add     a, a
    ld      e, a
    ld      d, 0
    add     hl, de
    ld      e, (hl)
    inc     hl
    ld      d, (hl)
    ld      (fade_len), de
    ld      hl, 0
    ld      (fade_err), hl
    ld      a, (fading)
    or      a
    jr      nz, fade_on
    ld      (fade_step), a
    inc     a
    ld      (fading), a
fade_on:
    ret

; tick: Timer B. Set the loop's end once the intro has played; run the fade.
tick:
    ld      hl, (tick_count)
    inc     hl
    ld      (tick_count), hl
    ld      hl, (intro_ticks)
    ld      a, h
    or      l
    jr      z, tick_fade
    dec     hl
    ld      (intro_ticks), hl
    ld      a, h
    or      l
    jr      nz, tick_fade
    ld      de, (loop_end)
    ld      a, PB_END
    call    ym_write_word_a
tick_fade:
    ld      a, (fading)
    or      a
    ret     z
    ; FADE_STEPS steps over fade_len ticks: err += FADE_STEPS a tick, a step per fade_len
    ld      hl, (fade_err)
    ld      de, FADE_STEPS
    add     hl, de
    ld      de, (fade_len)
    ld      a, (fade_step)
    ld      c, a
tf_steps:
    or      a
    sbc     hl, de
    jr      c, tf_rest
    inc     c
    jr      tf_steps
tf_rest:
    add     hl, de
    ld      (fade_err), hl
    ld      a, c
    cp      FADE_STEPS
    jp      nc, stop_music          ; -30 dB reached: the music stops
    ld      (fade_step), a
    ld      hl, fade_att            ; level = L - L * fade_att[step] / 256
    ld      e, a
    ld      d, 0
    add     hl, de
    ld      e, (hl)
    ld      h, ADPCMB_LEVEL
    call    mul8
    ld      a, ADPCMB_LEVEL
    sub     h
    ld      e, a
    ld      d, PB_LEVEL
    jp      ym_write_a

; mul8: hl = h * e
mul8:
    ld      d, 0
    ld      l, d
    ld      b, 8
mul8_bit:
    add     hl, hl
    jr      nc, mul8_next
    add     hl, de
mul8_next:
    djnz    mul8_bit
    ret

; play_fx: a = effect index; ADPCM-A channel 0, the effect before it keyed off first
play_fx:
    ld      (fx_cur), a
    ld      hl, sfx_table
    ld      de, SFX_ROW
    call    row
    ld      de, PA_KEY * 256 + FX_CH_BIT + $80
    call    ym_write_b
    ld      de, FLAG_CTRL * 256 + FX_CH_BIT ; forget an end flag it may have left
    call    ym_write_a
    ld      de, FLAG_CTRL * 256 + $00
    call    ym_write_a
    ld      e, (hl)                 ; start
    inc     hl
    ld      d, (hl)
    inc     hl
    ld      a, PA_START_L
    ld      c, PA_START_H
    call    fx_write_addr
    ld      e, (hl)                 ; end
    inc     hl
    ld      d, (hl)
    ld      a, PA_END_L
    ld      c, PA_END_H
    call    fx_write_addr
    ld      de, PA_KEY * 256 + FX_CH_BIT
    jp      ym_write_b

; stop_fx: key channel 0 off
stop_fx:
    ld      a, NONE
    ld      (fx_cur), a
    ld      de, PA_KEY * 256 + FX_CH_BIT + $80
    jp      ym_write_b

; poll_fx: the effect ended: channel 0 is free
poll_fx:
    in      a, (PORT_YM_ADDR_B)
    and     FX_CH_BIT
    ret     z
    ld      a, NONE
    ld      (fx_cur), a
    ld      de, FLAG_CTRL * 256 + FX_CH_BIT
    call    ym_write_a
    ld      de, FLAG_CTRL * 256 + $00
    jp      ym_write_a

; fx_write_addr: a = low byte's register, c = high byte's, de = 256-byte address (port B).
; Keeps hl.
fx_write_addr:
    push    de
    ld      d, a
    call    ym_write_b
    pop     de
    ld      e, d
    ld      d, c
    jp      ym_write_b

; ym_write_word_a: a = register of the low byte, de = value (high byte to a + 1). Keeps
; bc, de, hl.
ym_write_word_a:
    push    de
    ld      d, a
    call    ym_write_a
    pop     de
    push    de
    inc     a
    ld      e, d
    ld      d, a
    call    ym_write_a
    pop     de
    ret

; ym_write_a / ym_write_b: d = register, e = data. Preserve bc, de, hl; a = d after
ym_write_a:
    call    ym_wait
    ld      a, d
    out     (PORT_YM_ADDR_A), a
    call    ym_wait
    ld      a, e
    out     (PORT_YM_DATA_A), a
    ld      a, d
    ret
ym_write_b:
    call    ym_wait
    ld      a, d
    out     (PORT_YM_ADDR_B), a
    call    ym_wait
    ld      a, e
    out     (PORT_YM_DATA_B), a
    ld      a, d
    ret
ym_wait:
    in      a, (PORT_YM_ADDR_A)
    rlca
    jr      c, ym_wait
    ret

; BIOS commands (inside the NMI)
cmd_01_wait_in_ram:
    xor     a
    out     (PORT_TO_68K), a
    out     (PORT_FROM_68K), a
    call    stop_all
    ld      de, YM_TIMER_CTRL * 256 + TIMER_STOP
    call    ym_write_a
    di
    ld      bc, OPCODE_JR_SELF
    ld      (RAM_WAIT_PC), bc
    ld      hl, RAM_WAIT_PC
    ld      sp, hl
    push    hl
    ld      a, $01
    out     (PORT_TO_68K), a
    retn

cmd_03_reset:
    ld      sp, STACK_TOP
    ld      hl, init
    push    hl
    retn

; the fade's attenuation: fade_att[i] = round(256 x (1 - 10^(-i / 4 / 20))):
; step i is i/4 dB down (the level is ADPCMB_LEVEL - ADPCMB_LEVEL x fade_att[i] / 256)
fade_att:
    db      0, 7, 14, 21, 28, 34, 41, 47, 53, 58
    db      64, 69, 75, 80, 85, 90, 94, 99, 104, 108
    db      112, 116, 120, 124, 128, 131, 135, 138, 142, 145
    db      148, 151, 154, 157, 160, 163, 165, 168, 170, 173
    db      175, 177, 180, 182, 184, 186, 188, 190, 192, 194
    db      195, 197, 199, 200, 202, 203, 205, 206, 208, 209
    db      210, 212, 213, 214, 215, 217, 218, 219, 220, 221
    db      222, 223, 224, 225, 226, 226, 227, 228, 229, 230
    db      230, 231, 232, 233, 233, 234, 234, 235, 236, 236
    db      237, 237, 238, 238, 239, 239, 240, 240, 241, 241
    db      242, 242, 242, 243, 243, 244, 244, 244, 245, 245
    db      245, 246, 246, 246, 246, 247, 247, 247, 247, 248

    include "sound.inc"
