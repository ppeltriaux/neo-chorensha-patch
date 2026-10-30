; ==============================================================================
; MCDRV (trap #4): the resident music driver the game found at start-up (its detect
; stored the ID long; the game only tests its sign). d0.l = function: $01 set data (a0 = data,
; d1 = size), $05 stop, $02 play, $14 fade (d1 = speed) (inventory.md, sound-recon.md §1);
; recorded in the sound ring (shim.inc SND_PUT: source SND_SRC_MCDRV, a0 kept), which
; sound.asm's Snd_Drain sends to the Z80. Another function, or fn $01's data none of the three
; tunes (game.inc SND_TUNE_PTR_*: the drain could not name it), is a call fault (FAULT_MCDRV +
; fn, arg d1 or a0). Returns d0 = 0 as x68k_hle does. Every other register is kept.
; ==============================================================================

Shim_MCDRV:
    PROF_ON PROF_TRAP
    movem.l d1-d7/a0-a6, -(sp)
    cmpi.l  #$01, d0
    beq.s   .set
    cmpi.l  #$02, d0
    beq.s   .record
    cmpi.l  #$05, d0
    beq.s   .record
    cmpi.l  #$14, d0
    beq.s   .record
    bra.s   .fault
.set:
    lea     Snd_TunePtrs, a1
    moveq   #SND_TUNE_COUNT-1, d7
.tune:
    cmpa.l  (a1)+, a0
    dbeq    d7, .tune
    bne.s   .notune
.record:
    SND_PUT #SND_SRC_MCDRV, d0, a0, d3, a4
    move.w  #1, SHIM_SND_MUSIC      ; the next drain walks the ring (sound.asm)
    movem.l (sp)+, d1-d7/a0-a6
    moveq   #0, d0
    PROF_OFF PROF_TRAP
    rte
.notune:
    move.l  a0, d1                  ; the data
.fault:
    move.l  d0, d7
    addi.l  #FAULT_MCDRV, d7
    movea.l 56+2(sp), a0            ; the stacked PC (after the trap), above the saved registers
    subq.l  #2, a0
    bra     Shim_CallFault
