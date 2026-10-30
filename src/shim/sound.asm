; ==============================================================================
; SOUND (Plan 4 Task 5): the original's MCDRV (trap #4) and IOCS ADPCM calls, recorded in the
; sound ring as the game makes them (mcdrv.asm, iocs.asm Iocs_Snd: shim.inc SND_PUT), are sent to
; the Z80 driver (src/z80/sound.asm) as latch commands (build/snd/sound68k.inc SND_CMD_*) once
; a frame: Snd_Drain, at the end of the VBlank (resume.asm Shim_VBlank, after Text_Flush: it uses
; no VRAM and so no blank lines). The VBlank's game part runs only while BIOS_SYSTEM_MODE bit 7 is
; set (the BIOS's frames go to SYSTEM_INT1), so the drain never talks to the Z80 while the BIOS
; does.
;
; A drain takes the entries recorded since the last one and coalesces them (docs/notes/shim.md,
; "Sound"):
;   music:  the last play (fn $02: the tune fn $01 set last, SHIM_SND_TUNE, a fn $01 being one of
;           the three tunes: Shim_MCDRV faults on any other) -> SND_CMD_PLAY + tune, then a stop
;           (fn $05 -> SND_CMD_MUSIC_STOP) or fade (fn $14 -> SND_CMD_FADE + speed index: the
;           nearest of SND_FADE_SPEED_0..2 to d1) made after it: a stop wins over a fade (the
;           fade of nothing does nothing); a stop or fade before the play is dropped (bgm_play's
;           $01 $05 $02 is one play)
;   effect: the last of _ADPCMOUT (-> SND_CMD_FX + the effect index of the cue whose sample a1
;           is: SHIM_SND_FXPTR) and _ADPCMMOD(0) (-> SND_CMD_FX_STOP): on the X68000 each one
;           stopped the one before within the same frame
; and sends them in that order: at most 3 bytes. Each command's echo (the command | SND_CMD_ECHO
; on the reply latch: the Z80's NMI is not re-entrant before it) is waited for before the next
; command is sent, at most SND_ECHO_POLLS reads; a command not echoed by then is counted in
; SHIM_SND_ERR. The echo of a drain's last command is waited for by the next drain that sends
; (SHIM_SND_LAST): a frame later it is there. When the latch already holds a command's echo (the
; same command ended the drain before) its answer cannot be told from the old one: the drain
; waits SND_STALE_POLLS reads instead when another command follows.
; A drain takes at most SND_ENTRIES - 1 entries, the newest; any more are counted in
; SHIM_SND_LOST. (With SND_ENTRIES or more pending, the oldest slot is the one a recorder the
; VBlank interrupted may be writing: SHIM_SND_COUNT & 31, not counted yet. It is never read.)
; ==============================================================================

    include "sound68k.inc"          ; build/snd (tools/mksound.py): the command bytes, SND_FX_INDEX
    even

    if SND_FX_COUNT>SND_FX_MAX
    fail "sound.asm: more effects than SHIM_SND_FXPTR holds (shim.inc SND_FX_MAX)"
    endif
    if SND_FADE_SPEEDS!=3
    fail "sound.asm: Snd_Drain maps a fade's speed to one of three (SND_FADE_SPEED_0..2)"
    endif
    if SND_TUNE_COUNT!=3
    fail "sound.asm: Snd_TunePtrs lists three tunes (game.inc SND_TUNE_PTR_0..2)"
    endif
    if SND_SIZE!=16
    fail "sound.asm: Snd_Drain indexes the ring by << 4 (SND_SIZE)"
    endif

SND_CUES        EQU 128             ; the cue table's entries (16 bytes each, +6 the sample)
SND_CUE_SAMPLE  EQU 6

; the data MCDRV fn $01 is given for tune t (game.inc: the tune table's pointers in P-ROM)
Snd_TunePtrs:
    dc.l    SND_TUNE_PTR_0, SND_TUNE_PTR_1, SND_TUNE_PTR_2

; ------------------------------------------------------------------------------
; Snd_Init (the resume, after the state is cleared): no tune set, no echo pending, the cache
; empty; SHIM_SND_FXPTR[i] = the sample of the cue SND_FX_INDEX maps to effect i. Uses d0-d1/a0-a2.
; ------------------------------------------------------------------------------
Snd_Init:
    move.w  #SND_NO_TUNE, SHIM_SND_TUNE
    moveq   #-1, d0                 ; (an odd address: no sample)
    move.l  d0, SHIM_SND_FXC
    move.l  d0, SHIM_SND_FXC+6
    move.l  d0, SHIM_SE_SMP         ; (the busy model's cache: none)
    lea     SND_FX_INDEX, a0
    lea     SND_CUE_TABLE+SND_CUE_SAMPLE, a1
    lea     SHIM_SND_FXPTR, a2
    move.w  #SND_CUES-1, d0
.cue:
    moveq   #0, d1
    move.b  (a0)+, d1
    cmpi.b  #SND_FX_COUNT, d1
    bhs.s   .next                   ; $FF: the cue has no sample
    add.w   d1, d1
    add.w   d1, d1
    move.l  (a1), (a2,d1.w)
.next:
    lea     16(a1), a1
    dbra    d0, .cue
    rts

; ------------------------------------------------------------------------------
; Snd_Drain (the VBlank, at its end, when SHIM_SND_COUNT, in d0, is not SHIM_SND_DONE): the
; ring's new entries to the Z80, as above. Every register but d0 is kept. It runs in most frames
; of play and its time is the game's, so the usual drain is short: with no MCDRV call since the
; last walk (SHIM_SND_MUSIC clear) and the newest entry an _ADPCMOUT or _ADPCMMOD(0), that entry
; alone gives the one command (the rules above: the effect is the last of them; nothing else is
; there to send). Anything else (a music call, a pause, a ring that wrapped) is Snd_Walk's.
; ------------------------------------------------------------------------------
Snd_Drain:
    movem.l d1/a0, -(sp)
    move.l  d0, d1
    sub.l   SHIM_SND_DONE, d1       ; entries recorded since the last drain
    move.l  d0, SHIM_SND_DONE       ; all taken now
    tst.w   SHIM_SND_MUSIC
    bne.s   .walk
    cmpi.l  #SND_ENTRIES-1, d1      ; (more: Snd_Walk counts the lost)
    bhi.s   .walk
    subq.w  #1, d0
    andi.w  #SND_ENTRIES-1, d0
    lsl.w   #4, d0
    lea     SHIM_SND, a0
    adda.w  d0, a0                  ; the newest entry
    cmpi.w  #SND_SRC_IOCS<<8|$60, (a0)
    bne.s   .mod
    movea.l 12(a0), a0              ; _ADPCMOUT: its sample's command
    bsr     Snd_Fx
    bra.s   .one
.mod:
    cmpi.w  #SND_SRC_IOCS<<8|$67, (a0)
    bne.s   .walk
    tst.l   4(a0)                   ; _ADPCMMOD(0) (1, 2: Snd_Walk's)
    bne.s   .walk
    moveq   #SND_CMD_FX_STOP, d0
.one:
    tst.b   d0
    beq.s   .end                    ; (no cue's sample)
    lea     REG_SOUND, a0
    move.w  SHIM_SND_LAST, d1       ; the last drain's last command: its echo first
    beq.s   .send
    cmp.b   (a0), d1
    beq.s   .send                   ; (there, as it is a frame later)
    bsr     Snd_Echo
.send:
    move.b  d0, (a0)
    ori.w   #SND_CMD_ECHO, d0
    andi.w  #$00FF, d0
    move.w  d0, SHIM_SND_LAST       ; the next drain waits for its echo
.end:
    move.w  SHIM_SND_DONE+2, d0
    andi.w  #SND_ENTRIES-1, d0
    move.w  d0, SHIM_SND_TAIL       ; (test tap only: the head, SHIM_SND_COUNT & 31)
    movem.l (sp)+, d1/a0
    rts
.walk:
    bsr.s   Snd_Walk                ; d1 = the entries since the last drain
    bra.s   .end

; Snd_Walk: every entry since the last drain (d1 of them; the newest SND_ENTRIES - 1 when more:
; the rest counted in SHIM_SND_LOST), coalesced and sent as above; SHIM_SND_MUSIC cleared. Uses
; d0-d1/a0.
Snd_Walk:
    movem.l d2-d5/a1-a2, -(sp)
    clr.w   SHIM_SND_MUSIC
    move.l  d1, d0
    moveq   #SND_ENTRIES-1, d2
    cmp.l   d2, d0
    bls.s   .held
    sub.l   d2, d0                  ; the ring wrapped (or is about to: the slot after the newest
    add.w   d0, SHIM_SND_LOST       ; may be being written): the oldest are lost
    move.l  d2, d0                  ; the newest SND_ENTRIES - 1
.held:
    move.w  SHIM_SND_DONE+2, d1     ; (the count)
    sub.w   d0, d1
    andi.w  #SND_ENTRIES-1, d1
    lsl.w   #4, d1
    lea     SHIM_SND, a0
    adda.w  d1, a0                  ; the oldest entry taken
    subq.w  #1, d0
    moveq   #0, d3                  ; music: the play's command (0: none)
    moveq   #0, d4                  ; music: the stop's or fade's after it (0: none)
    moveq   #0, d5                  ; effect: 0 none, SND_CMD_FX_STOP, -1 a play (a2 its sample)
.entry:
    move.w  (a0), d2                ; source << 8 | function
    cmpi.w  #SND_SRC_IOCS<<8|$67, d2
    beq.s   .mod
    cmpi.w  #SND_SRC_IOCS<<8|$60, d2
    beq.s   .out
    cmpi.w  #SND_SRC_MCDRV<<8|$02, d2
    beq.s   .play
    cmpi.w  #SND_SRC_MCDRV<<8|$01, d2
    beq.s   .set
    cmpi.w  #SND_SRC_MCDRV<<8|$05, d2
    beq.s   .stop
    cmpi.w  #SND_SRC_MCDRV<<8|$14, d2
    bne.s   .next                   ; (no other is recorded)
    cmpi.b  #SND_CMD_MUSIC_STOP, d4 ; a fade after a stop: nothing
    beq.s   .next
    move.l  4(a0), d2               ; the speed: the nearest of the three
    moveq   #SND_CMD_FADE, d4
    cmpi.l  #(SND_FADE_SPEED_0+SND_FADE_SPEED_1)/2, d2
    ble.s   .next
    addq.b  #1, d4
    cmpi.l  #(SND_FADE_SPEED_1+SND_FADE_SPEED_2)/2, d2
    ble.s   .next
    addq.b  #1, d4
    bra.s   .next
.mod:
    tst.l   4(a0)                   ; _ADPCMMOD(0): stop (1 pause, 2 resume: the game makes neither)
    bne.s   .next
    moveq   #SND_CMD_FX_STOP, d5
    bra.s   .next
.out:
    moveq   #-1, d5                 ; _ADPCMOUT
    movea.l 12(a0), a2
    bra.s   .next
.stop:
    moveq   #SND_CMD_MUSIC_STOP, d4
    bra.s   .next
.play:
    move.w  SHIM_SND_TUNE, d2
    cmpi.w  #SND_NO_TUNE, d2        ; no data set: MCDRV plays nothing
    beq.s   .next
    moveq   #SND_CMD_PLAY, d3
    add.b   d2, d3
    moveq   #0, d4                  ; what came before the play is gone
    bra.s   .next
.set:
    move.l  12(a0), d2              ; the data: one of the three tunes
    lea     Snd_TunePtrs, a1
    moveq   #SND_TUNE_COUNT-1, d1
.tune:
    cmp.l   (a1)+, d2
    dbeq    d1, .tune
    beq.s   .known
    move.w  #SND_NO_TUNE, d2
    bra.s   .settune
.known:
    moveq   #SND_TUNE_COUNT-1, d2
    sub.w   d1, d2
.settune:
    move.w  d2, SHIM_SND_TUNE
.next:
    lea     SND_SIZE(a0), a0
    cmpa.l  #SHIM_SND_END, a0
    bne.s   .more
    lea     SHIM_SND, a0
.more:
    dbra    d0, .entry

    tst.b   d5                      ; the effect's sample -> its command
    bpl.s   .bytes
    movea.l a2, a0
    bsr.s   Snd_Fx
    move.b  d0, d5
.bytes:
    moveq   #0, d2                  ; the commands, the first in the low byte
    move.b  d5, d2
    tst.b   d4
    beq.s   .nofade
    lsl.l   #8, d2
    move.b  d4, d2
.nofade:
    tst.b   d3
    beq.s   .noplay
    lsl.l   #8, d2
    move.b  d3, d2
.noplay:
    bsr.s   Snd_Send
    movem.l (sp)+, d2-d5/a1-a2
    rts

; Snd_Send: the commands in d2.l (the first in the low byte, 0 ends them; none: nothing) to the
; Z80, as the drain sends them: the last drain's last command's echo first (SHIM_SND_LAST), then
; each command's echo before the next (SND_STALE_POLLS reads instead when the latch already holds
; it), the last one's echo left for the next to wait for (SHIM_SND_LAST). a0 = REG_SOUND after.
; Uses d0-d2/a0.
Snd_Send:
    lea     REG_SOUND, a0
    tst.l   d2
    beq.s   .sent
    move.w  SHIM_SND_LAST, d1       ; the last drain's last command: its echo first
    beq.s   .send
    cmp.b   (a0), d1
    beq.s   .send
    bsr     Snd_Echo
.send:
    move.b  d2, d1
    ori.b   #SND_CMD_ECHO, d1       ; the Z80's answer
    move.b  d2, (a0)
    lsr.l   #8, d2
    beq.s   .last
    cmp.b   (a0), d1                ; the latch held it already (the same command ended the
    beq.s   .stale                  ; drain before): its answer can't be seen
    bsr     Snd_Echo
    bra.s   .send
.stale:
    moveq   #SND_STALE_POLLS-1, d0  ; the time the Z80 takes, instead
.wait:
    cmp.b   (a0), d1                ; (a poll's time)
    dbra    d0, .wait
    bra.s   .send
.last:
    andi.w  #$00FF, d1
    move.w  d1, SHIM_SND_LAST       ; the next drain waits for its echo
.sent:
    rts

; Snd_Fx: the command for the sample a0 in d0 (SND_CMD_FX + its effect index; 0, counted in
; SHIM_SND_ERR, for no cue's), through the two-entry cache SHIM_SND_FXC.
Snd_Fx:
    moveq   #0, d0
    cmpa.l  SHIM_SND_FXC, a0        ; the latest
    bne.s   .older
    move.w  SHIM_SND_FXC+4, d0
    rts
.older:
    cmpa.l  SHIM_SND_FXC+6, a0      ; the one before
    bne.s   .search
    move.w  SHIM_SND_FXC+10, d0
    bra.s   .front
.search:
    movem.l d1/a1, -(sp)
    lea     SHIM_SND_FXPTR, a1
    moveq   #SND_FX_COUNT-1, d1
.fx:
    cmpa.l  (a1)+, a0
    dbeq    d1, .fx
    beq.s   .found
    movem.l (sp)+, d1/a1
    addq.w  #1, SHIM_SND_ERR        ; no cue's sample: nothing to play
    rts
.found:
    moveq   #SND_CMD_FX+SND_FX_COUNT-1, d0
    sub.b   d1, d0
    movem.l (sp)+, d1/a1
.front:
    move.l  SHIM_SND_FXC, SHIM_SND_FXC+6
    move.w  SHIM_SND_FXC+4, SHIM_SND_FXC+10
    move.l  a0, SHIM_SND_FXC
    move.w  d0, SHIM_SND_FXC+4
    rts

; Snd_Frames (Iocs_Snd, an _ADPCMOUT whose sample a1 is not SHIM_SE_SMP): d0.w = SND_FX_FRAMES of
; the effect whose sample a1 is (0 for no cue's: nothing plays), kept in SHIM_SE_SMP / SHIM_SE_SMPF.
; Uses d0/a0.
Snd_Frames:
    move.l  d1, -(sp)
    lea     SHIM_SND_FXPTR, a0
    moveq   #SND_FX_COUNT-1, d1
.fx:
    cmpa.l  (a0)+, a1
    dbeq    d1, .fx
    beq.s   .found
    moveq   #0, d0
    bra.s   .keep
.found:
    moveq   #SND_FX_COUNT-1, d0
    sub.w   d1, d0                  ; the effect index
    lea     SND_FX_FRAMES, a0
    move.b  (a0,d0.w), d0
    andi.w  #$00FF, d0
.keep:
    move.l  a1, SHIM_SE_SMP
    move.w  d0, SHIM_SE_SMPF
    move.l  (sp)+, d1
    rts

; Snd_Echo: wait for the echo d1.b on the latch (a0 = REG_SOUND), at most SND_ECHO_POLLS reads; not
; there: counted in SHIM_SND_ERR (the Z80 did not take the command). Every register kept.
Snd_Echo:
    move.w  d0, -(sp)
    move.w  #SND_ECHO_POLLS-1, d0
.poll:
    cmp.b   (a0), d1
    dbeq    d0, .poll
    beq.s   .ok
    addq.w  #1, SHIM_SND_ERR
.ok:
    move.w  (sp)+, d0
    rts

; ------------------------------------------------------------------------------
; Snd_StopAll (Plan 5 Task 1, bios.asm: before the BIOS takes the Z80 or a demo ends): the music
; and the effect stopped now: SND_CMD_MUSIC_STOP and SND_CMD_FX_STOP sent as the drain sends
; (Snd_Send: the last drain's echo first, then the music stop's; the effect stop's is left in
; SHIM_SND_LAST, as a drain leaves its last: the Z80 takes it within microseconds, and the BIOS's
; next byte or the resume's first drain comes milliseconds later). No VBlank wait: DEMO_END runs
; inside the VBlank. The ring is left alone (the resume that follows clears it; Shim_Boot empties
; it). Every register kept.
; ------------------------------------------------------------------------------
Snd_StopAll:
    movem.l d0-d2/a0, -(sp)
    move.l  #SND_CMD_FX_STOP<<8|SND_CMD_MUSIC_STOP, d2
    bsr     Snd_Send                ; the drain's way: the last echo, then both stops
    movem.l (sp)+, d0-d2/a0
    rts
