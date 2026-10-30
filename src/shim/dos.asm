; ==============================================================================
; DOS and FLOAT (F-line, vector 11): Human68k DOS calls ($FFxx, arguments on the stack after
; the F-line word) and FLOAT2's integer calls ($FExx, d0/d1). The result in d0; every other
; register is kept (FLOAT: the CCR as described). Behaviour matches tools/x68k_hle.py. A call
; not listed below stops the machine: vector 0, number = the F-line word.
;
; Served (the calls reachable after the resume point, snapshot after_resume):
;   _INPOUT $FF06   0 (no key; output dropped)    _PRINT $FF09    0 (console not shown)
;   _FFLUSH $FF0D   0                             _SUPER $FF20    virtual mode, as _B_SUPER
;   _CONCTRL $FF23  0                             _OPEN $FF3D     ROMFILES, read-only
;   _CLOSE $FF3E    0                             _READ $FF3F     from the ROM copy (below)
;   _WRITE $FF40    console handles 1/2: length   _SEEK $FF42     0/1/2, -25 out of range
;   _IOCTRL $FF44   mode 0 (device information)   _GETPDB $FF51   GAME_PSP + $10
;   _EXIT $FF00, _EXIT2 $FF4C: the game quit (title menu "exit"): resumed again from the
;                   snapshot (SHIM_RESTARTS + 1): an arcade machine has nowhere to exit to
;   __LMUL $FE00, __LDIV $FE01 (FLOAT2's conventions)
; Not served (fault if reached): _CREATE $FF3C (the cart has nowhere to write), __ECVT
; $FE24 / __FCVT $FE25 (printf's float formats), and everything else.
;
; Files: _OPEN looks the name up in the ROM file table (link.py: the files the game opens
; after the resume point) as Human68k resolves it from A:\GAME (drive, "\GAME\" prefix,
; case and / vs \ ignored). A name not in the table is a call fault ($FF3D, arg = name).
; _READ into the game's RAM ($100000-$10AFFF) or its stack ($10E000-$10EFFF) copies; into P-ROM
; (a ROM object placed by layout.py; link.py's FILE_RELOADS fills those the game reloads) it is
; a no-op when those bytes already hold the file's, and a call fault ($FF3F, arg = destination)
; when not. Anywhere else (the shim's reserve, the spare RAM, the BIOS area, I/O) is a call fault.
; ==============================================================================

Shim_FLine:
    PROF_ON PROF_TRAP
    movem.l d1-d7/a0-a6, -(sp)      ; 56 bytes; the frame (SR, PC of the F-line word) above
    movea.l 56+2(sp), a0            ; the F-line word
    move.w  (a0), d7
    addq.l  #2, 56+2(sp)            ; return past it
    lea     56+6(sp), a6            ; the caller's stack: DOS arguments
    addq.l  #1, SHIM_DOS_COUNT
    lea     DosList, a5
.find:
    move.w  (a5)+, d6
    beq.s   .unknown
    cmp.w   d7, d6
    beq.s   .found
    addq.l  #4, a5
    bra.s   .find
.found:
    movea.l (a5), a5
    jsr     (a5)                    ; caller's d0-d5/a0 (= the word's address) in place
    movem.l (sp)+, d1-d7/a0-a6
    PROF_OFF PROF_TRAP
    rte
.unknown:
    andi.l  #$FFFF, d7
    bra     Shim_CallFault          ; a0 = the F-line word, d1 = the caller's d1

DOS_FN macro
    dc.w    \1
    dc.l    \2
    endm

DosList:
    DOS_FN  $FF00, Dos_EXIT
    DOS_FN  $FF06, Dos_Zero         ; _INPOUT
    DOS_FN  $FF09, Dos_Zero         ; _PRINT
    DOS_FN  $FF0D, Dos_Zero         ; _FFLUSH
    DOS_FN  $FF20, Dos_SUPER
    DOS_FN  $FF23, Dos_Zero         ; _CONCTRL
    DOS_FN  $FF3D, Dos_OPEN
    DOS_FN  $FF3E, Dos_CLOSE
    DOS_FN  $FF3F, Dos_READ
    DOS_FN  $FF40, Dos_WRITE
    DOS_FN  $FF42, Dos_SEEK
    DOS_FN  $FF44, Dos_IOCTRL
    DOS_FN  $FF4C, Dos_EXIT
    DOS_FN  $FF51, Dos_GETPDB
    DOS_FN  $FE00, Float_LMUL
    DOS_FN  $FE01, Float_LDIV
    dc.w    0

; frame offsets inside a handler (after the dispatcher's jsr)
DOS_SAVED_D1    EQU 4               ; the caller's d1
DOS_SR          EQU 4+56            ; the stacked SR (its low byte: the caller's CCR)

; a handler's own fault: d7 = the call word, d1 = the argument to show
Dos_Fault:
    andi.l  #$FFFF, d7
    movea.l DOS_SR+2(sp), a0
    subq.l  #2, a0                  ; the F-line word
    bra     Shim_CallFault

Dos_Zero:
    moveq   #0, d0
    rts

Dos_EXIT:
    addq.w  #1, SHIM_RESTARTS
    move.w  SHIM_BIOS_MODE, d7      ; the same mode again
    jmp     Shim_Resume

Dos_GETPDB:
    move.l  #GAME_PSP+$10, d0
    rts

; _SUPER(stack.l): 0 enters supervisor mode (old SSP; -1 if already there), else user mode
Dos_SUPER:
    tst.l   (a6)
    bne.s   .user
    tst.w   SHIM_SUPER
    bne.s   .already
    move.w  #1, SHIM_SUPER
    move.l  #SSP_VALUE, d0
    rts
.already:
    moveq   #-1, d0
    rts
.user:
    clr.w   SHIM_SUPER
    moveq   #0, d0
    rts

; _WRITE(fh.w, buf.l, len.l): the console only
Dos_WRITE:
    move.w  (a6), d1
    subq.w  #1, d1
    cmpi.w  #1, d1
    bhi     Dos_Fault               ; not handle 1 or 2
    move.l  6(a6), d0
    rts

; _IOCTRL(mode.w, ...): mode 0 = device information of a handle
Dos_IOCTRL:
    move.w  (a6), d1
    bne     Dos_Fault
    move.w  2(a6), d1
    cmpi.w  #DOS_FIRST_FH, d1
    bhs.s   .file
    moveq   #0, d0
    lea     DosStdInfo, a0
    move.b  (a0,d1.w), d0
    rts
.file:
    bsr     Dos_Handle
    beq.s   .bad
    moveq   #0, d0                  ; a file on drive A:
    rts
.bad:
    moveq   #-6, d0                 ; invalid handle
    rts

DosStdInfo:                         ; CON in, CON out, CON err, AUX, PRN (x68k_hle)
    dc.b    $C1, $C2, $C2, $C0, $C0
    even

; Dos_Handle: d1.w = handle -> a4 = its slot in SHIM_FILES; Z set if not an open file
Dos_Handle:
    move.w  d1, d0
    subi.w  #DOS_FIRST_FH, d0
    cmpi.w  #DOS_HANDLES, d0
    bhs.s   .none
    lsl.w   #3, d0
    lea     SHIM_FILES, a4
    adda.w  d0, a4
    tst.l   (a4)
    rts
.none:
    moveq   #0, d0                  ; Z set
    rts

; _OPEN(name.l, mode.w)
Dos_OPEN:
    move.l  (a6), d1
    move.w  4(a6), d0
    andi.w  #3, d0
    bne     Dos_Fault               ; open for writing: the cart is read-only
    movea.l d1, a0
    bsr     Dos_FindFile            ; a3 = the table entry, or Z
    beq     Dos_Fault               ; not in the ROM file table
    lea     SHIM_FILES, a4
    moveq   #DOS_FIRST_FH, d0
.slot:
    tst.l   (a4)
    beq.s   .take
    addq.l  #8, a4
    addq.w  #1, d0
    cmpi.w  #DOS_FIRST_FH+DOS_HANDLES, d0
    blo.s   .slot
    moveq   #-4, d0                 ; too many open files
    rts
.take:
    move.l  a3, (a4)+
    clr.l   (a4)
    rts

; Dos_FindFile: a0 = Human68k name -> a3 = its ROMFILES entry (name.l, data.l, size.l), Z
; clear; Z set when the table has no such file.
Dos_FindFile:
    cmpi.b  #':', 1(a0)
    bne.s   .nodrive
    addq.l  #2, a0
.nodrive:
    move.b  (a0), d0
    bsr     Dos_Upper
    cmpi.b  #$5C, d0
    bne.s   .relative
    addq.l  #1, a0                  ; absolute: must be \GAME\...
    lea     DosGameDir, a1
.game:
    move.b  (a1)+, d2
    beq.s   .relative
    move.b  (a0)+, d0
    bsr     Dos_Upper
    cmp.b   d2, d0
    beq.s   .game
    bra.s   .none
.relative:
    lea     ROMFILES, a3
    move.w  (a3)+, d3
    bra.s   .next
.entry:
    movea.l (a3), a2
    movea.l a0, a1
.cmp:
    move.b  (a1)+, d0
    bsr     Dos_Upper
    cmp.b   (a2)+, d0
    bne.s   .miss
    tst.b   d0
    bne.s   .cmp
    move.l  a3, d0                  ; found: Z clear (the table is not at 0)
    rts
.miss:
    lea     12(a3), a3
.next:
    dbra    d3, .entry
.none:
    moveq   #0, d0                  ; Z set
    rts

DosGameDir:
    dc.b    "GAME", $5C, 0
    even

; Dos_Upper: d0.b in upper case, / as \
Dos_Upper:
    cmpi.b  #'/', d0
    bne.s   .letter
    moveq   #$5C, d0
    rts
.letter:
    cmpi.b  #'a', d0
    blo.s   .done
    cmpi.b  #'z', d0
    bhi.s   .done
    subi.b  #'a'-'A', d0
.done:
    rts

; _CLOSE(fh.w)
Dos_CLOSE:
    move.w  (a6), d1
    cmpi.w  #DOS_FIRST_FH, d1
    blo.s   .ok                     ; the standard handles
    bsr     Dos_Handle
    beq.s   .bad
    clr.l   (a4)+
    clr.l   (a4)
.ok:
    moveq   #0, d0
    rts
.bad:
    moveq   #-6, d0
    rts

; _SEEK(fh.w, offset.l, mode.w)
Dos_SEEK:
    move.w  (a6), d1
    bsr     Dos_Handle
    beq     Dos_Fault               ; not an open file
    movea.l (a4), a3
    move.w  6(a6), d1
    moveq   #0, d0
    tst.w   d1
    beq.s   .add
    move.l  4(a4), d0
    subq.w  #1, d1
    beq.s   .add
    move.l  8(a3), d0
    subq.w  #1, d1
    bne     Dos_Fault               ; no such mode
.add:
    add.l   2(a6), d0
    bmi.s   .range
    cmp.l   8(a3), d0
    bhi.s   .range
    move.l  d0, 4(a4)
    rts
.range:
    moveq   #-25, d0                ; can't seek
    rts

; _READ(fh.w, buf.l, len.l)
Dos_READ:
    move.w  (a6), d1
    bsr     Dos_Handle
    beq     Dos_Fault               ; not an open file
    movea.l (a4), a3
    move.l  8(a3), d0
    sub.l   4(a4), d0               ; bytes left
    move.l  6(a6), d2
    bpl.s   .len
    moveq   #0, d2
.len:
    cmp.l   d0, d2
    bls.s   .n
    move.l  d0, d2                  ; d2 = bytes to read
.n:
    movea.l 4(a3), a0
    adda.l  4(a4), a0               ; the file's bytes
    movea.l 2(a6), a1               ; the destination
    move.l  a1, d1
    move.l  a1, d0
    add.l   d2, d0                  ; its end
    cmpi.l  #GAME_RAM_LO, d1
    blo.s   .rom
    cmpi.l  #GAME_RAM_HI, d0
    bls.s   .ram                    ; the game's RAM objects
    cmpi.l  #STACK_TOP-$1000, d1
    blo     Dos_Fault               ; the shim's reserve
    cmpi.l  #STACK_TOP, d0
    bhi     Dos_Fault               ; the spare RAM, the BIOS area, beyond
.ram:
    move.l  d2, d0
    bra.s   .ctest
.copy:
    move.b  (a0)+, (a1)+
.ctest:
    subq.l  #1, d0
    bcc.s   .copy
    bra.s   .done
.rom:                               ; a ROM object: it must hold the file already
    cmpi.l  #GAME_RAM_LO, d0
    bhi     Dos_Fault               ; runs on past P-ROM
    move.l  d2, d0
    bra.s   .rtest
.cmp:
    cmpm.b  (a0)+, (a1)+
    bne     Dos_Fault
.rtest:
    subq.l  #1, d0
    bcc.s   .cmp
.done:
    add.l   d2, 4(a4)
    move.l  d2, d0
    rts

; ------------------------------------------------------------------------------
; FLOAT2 integer calls (its own code, run in tools/x68k_hle: d0 op d1 -> d0, every other
; register kept). __LMUL: the low 32 bits of the signed product, N/Z from it (FLOAT2 also
; flags an overflow with V/C and returns something else then; the game's only uses are
; fread/fwrite's size x count, far from it). __LDIV: the signed quotient truncated toward 0,
; N/Z from it; d1 = 0 leaves d0 and sets C; $80000000 / -1 gives $7FFFFFFF with V and C.
; ------------------------------------------------------------------------------
Float_LMUL:
    move.l  d0, d2
    move.l  d1, d3
    move.w  d2, d4
    mulu    d3, d4                  ; al * bl
    move.l  d2, d5
    swap    d5
    mulu    d3, d5                  ; ah * bl
    move.l  d3, d6
    swap    d6
    mulu    d2, d6                  ; bh * al
    add.w   d6, d5
    swap    d5
    clr.w   d5
    add.l   d4, d5
    move.l  d5, d0
    moveq   #0, d5                  ; V = C = 0
    bra.s   Float_CCR

Float_LDIV:
    tst.l   d1
    bne.s   .div
    moveq   #1, d5                  ; C: division by zero, d0 as it was
    bra.s   Float_SetCCR
.div:
    moveq   #0, d4                  ; the result's sign
    move.l  d0, d2
    bpl.s   .a
    neg.l   d2
    not.b   d4
.a:
    move.l  d1, d3
    bpl.s   .b
    neg.l   d3
    not.b   d4
.b:
    moveq   #0, d0                  ; quotient
    moveq   #0, d6                  ; remainder
    moveq   #31, d7
.bit:
    add.l   d2, d2
    addx.l  d6, d6
    add.l   d0, d0
    cmp.l   d3, d6
    blo.s   .zero
    sub.l   d3, d6
    addq.l  #1, d0
.zero:
    dbra    d7, .bit
    moveq   #0, d5
    tst.b   d4
    beq.s   .pos
    neg.l   d0
    bra.s   Float_CCR
.pos:
    tst.l   d0
    bpl.s   Float_CCR
    move.l  #$7FFFFFFF, d0          ; -2^31 / -1
    moveq   #3, d5                  ; V, C
    bra.s   Float_SetCCR

; Float_CCR: N/Z from d0 or'ed into d5 (V/C); Float_SetCCR: the caller's CCR becomes d5
; (X kept)
Float_CCR:
    tst.l   d0
    bpl.s   .nn
    ori.b   #8, d5
.nn:
    bne.s   Float_SetCCR
    ori.b   #4, d5
Float_SetCCR:
    move.b  DOS_SR+1(sp), d6
    andi.b  #$10, d6
    or.b    d5, d6
    move.b  d6, DOS_SR+1(sp)
    rts
