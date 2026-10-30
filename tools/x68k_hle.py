"""X68000 stand-in for the game's start-up at build time (Plan 2 Task 2; driven by preinit.py).

Runs the unpacked program (build/orig/sz2.bin, relocated to `base`) on Unicorn (M68000) from its
entry to a resume point, servicing what Human68k, the IOCS ROM, MCDRV and XSP would do, and
recording every call and every I/O write. Anything it does not know stops the run (HleError) with
the call number or address.

Memory, relative to the program base (the original's layout in MAME, `ram-census.md`; every part
moves with the base, so two runs at different bases differ only at pointers):

  base-$12D64  command line (LASCIIZ, empty)        COMMAND.X's buffer in the original run
  base-$11E60  environment: size long $600, no strings ("/E:" area of COMMAND.X; the census saw
               the startup copy 1 byte and clear one pointer: an empty environment)
  base-$100    memory block + PSP (block end = RAM end, +$30/+$34 = bss start, +$80 "A:\\GAME\\",
               +$C4 "sz2.x", as the startup read them in the census run)
  base         text, data, bss ($2C098 bytes)
  RAM end      base+$3AF0C0 (MAME's 4 MB machine: $400000 with the program at $50F40)

The XC startup itself puts the C stack at bss end + $400 (64 KB) and the malloc arena after the
environment copy; _SETBLOCK and the RAM end above are what make it land where the census saw it.

System state the program sees (each choice is the one the original makes on a stock 10 MHz
X68000 with this disk, AUTOEXEC.BAT = `sys\\mcdrv -B32`, `cd GAME`, `sz2`):

- User mode at entry; _B_SUPER/_SUPER switch a virtual mode flag (the CPU itself runs in
  supervisor mode throughout: one stack, as on the X68000 where both calls keep the C stack).
  The old SSP they return is $8364 (Human68k's, as MAME's run stored it at $1606/$2002).
- MCDRV is resident: the trap #4 vector points to a handler preceded by its 8-byte ID (copied
  from the user's SYS/MCDRV.X: MCDRV_ID) and the long $00600000 (what the census run's detect
  stored at $179B8; the game only tests its sign). Trap #4 calls are recorded and return d0 = 0.
- MFP GPIP bit 4 (V-DISP) and bit 7 (H-SYNC) follow a read-count clock: 468 reads of vertical
  blank (bit 4 = 0), 4276 reads of display (bit 4 = 1); bit 7 is set on one read in 8. One read
  stands for one pass of the game's polling loop ($1FAE: addq.l/btst.b #4,abs.l/bne = 38 cycles
  = 3.8 us at 10 MHz): 512 display lines and 56 blank lines of 31.75 us (31 kHz, 55.46 Hz), and
  8 reads per H period. The CPU-power test $4A5E counts one display period: 4276 x 0.297 / 10 =
  127 <= 130 (126% printed as the CPU power, integer maths), so main sets $221F4 = 2 and XSP mode 2,
  as the census dumps show for the stock machine. $192C waits for 7 H-sync pulses the same way.
- MPU type byte $CBC = 0 (68000), read by FLOAT2.
- FLOAT2.X is loaded from the disk (SYS) and its own code serves every $FExx call; its clock
  (_GETDATE/_GETTIME) reads the census runs' boot time (see CLOCK_DATE): the random table at
  $1F62C then matches the census dumps word for word.
- _CRTMOD(10) leaves CRTC R20's low byte at $10 (IPL ROM table); the game reads it back.

I/O: every write to $E00000-$EFFFFF goes to a shadow and to io_writes, in order. Reads return:
GPIP from the clock above; text VRAM, palettes, sprite/BG/PCG and the registers in
IO_SHADOW_READ what was written last (palettes: $641A copies the text palette it loaded into the
graphic palette). Two registers are read before the game wrote them. CRTC R21 $E8002A (saved
into $1942 and restored around the text clear $1888) holds what the IPL ROM left there, $0033
(IO_BOOT, measured in MAME x68000: the lock-step found the game's saved copy differing when this
gave 0, docs/notes/lockstep.md). System port 4 $E8E007 ($19DC, bit 1 set then cleared) gives 0
(power-on value not modelled; it only goes back to the port). Any other I/O read stops the run.

IOCS calls (trap #15, d0 = number) and what they do here: _B_SUPER $81 (the virtual mode; old
SSP or -1), _CRTMOD $10 (R20 above), _TPALET2 $14 and _SPALET $CF (palette read/write on the
shadow; writes also go to io_writes with "via"; d0 = the colour before), _B_INTVCS $80 (vector
recorded; old handler returned), _B_BPEEK $82 / _B_LPEEK $84 (memory read, a1 advanced),
_PRIORITY $92 (video controller R1), _SP_ON $C1 / _SP_OFF $C2 / _BGCTRLST $CA (BG control
$EB0808 bits), _G_CLR_ON $90, _SKEY_MOD $7D, _OS_CUROF $AF (d0 = 0), _BGTEXTGT $CE (d1 = BG text
page, d2 = x, d3 = y, each 0-63: d0.w = the word at $EBC000 + page * $2000 + (y * 64 + x) * 2,
what the game wrote there; a cell never written stops the run). The register writes a
call stands for go to io_writes ("via" = the call) and the effects not modelled are named in the
call's "unmodelled" (see BG_CTRL). Every logged event (DOS, IOCS, XSP, MCDRV, FLOAT calls, I/O
writes, vector installs) carries "seq", one counter over the run: merging the lists by seq gives
the order things happened in. DOS calls: file calls on
GAME read-only (_OPEN/_READ/_SEEK/_CLOSE, _IOCTRL mode 0), console output (_WRITE to 1/2,
_PRINT) collected, _SETBLOCK on the program's block against the RAM end ($81 + the largest
size when too big), _SUPER (virtual mode), _INTVCS (recorded in interrupts), _GETPDB,
_GETDATE/_GETTIME (the clock), _CONCTRL (recorded). XSP's C entries are not run: each call is
recorded with its arguments (XSP199.MAN), and returns what XSP would (void, or 0 missed blanks).

After the resume point, call() runs one game function from the state run() left (preinit.py: the
game-start background loader, to learn what its _BGTEXTGT reads give).
"""
import os
import struct
import sys

from unicorn import (Uc, UcError, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_INTR, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED, UC_MEM_WRITE)
from unicorn.m68k_const import (UC_CPU_M68K_M68000, UC_M68K_REG_A0, UC_M68K_REG_A1,
                                UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5,
                                UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_D1,
                                UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5,
                                UC_M68K_REG_D6, UC_M68K_REG_D7, UC_M68K_REG_PC, UC_M68K_REG_SR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orig_bytes  # noqa: E402
import x68k_names  # noqa: E402

DREGS = [UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4,
         UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7]
AREGS = [UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4,
         UC_M68K_REG_A5, UC_M68K_REG_A6, UC_M68K_REG_A7]
REG_NAMES = ["d%d" % i for i in range(8)] + ["a%d" % i for i in range(7)]

# Layout relative to the base (see the module docstring)
CMDLINE_OFF = -0x12D64
ENV_OFF = -0x11E60
ENV_SIZE = 0x600
PSP_OFF = -0x100
RAM_END_OFF = 0x3AF0C0
BELOW_BASE = CMDLINE_OFF                  # lowest base-relative address the stand-in sets up

SSP_VALUE = 0x8364                        # Human68k's SSP, returned by _B_SUPER/_SUPER
MCDRV_ENTRY = 0x10000                     # absolute: the fake MCDRV's trap #4 handler
MCDRV_LONG = 0x00600000                   # the long before it (returned by the game's detect)
# MCDRV's ID, the 8 bytes before that long (what the game's detect compares): copied from the
# user's driver, (file under the disk's root, offset, size, SHA1)
MCDRV_ID = ("SYS/MCDRV.X", 227, 8, "975aca9c8c79cbd65f03cf47648a17535dab40b2")
FAKE_OLD_VECTOR = 0x00FF0000              # "previous handler" returned by DOS _INTVCS

# FLOAT2.X (CONFIG.SYS DEVICE = \SYS\FLOAT2.x): loaded at a fixed address below the program,
# initialised as a device driver, then every $FExx F-line goes to its handler (its own code: the
# random numbers, sin/cos and double arithmetic are then the original's to the bit).
FLOAT2_AT = 0x12000
FLOAT2_REQ = 0x11000                      # device request header + CONFIG line + return stub
HUMAN_FLINE = 0x6E00                      # "Human68k's line-F handler" returned as the old vector
MPU_TYPE_ADDR = 0xCBC                     # IOCS work: MPU type byte, 0 = 68000
# The clock: FLOAT2 seeds __RND with _GETDATE + _GETTIME at load, so the game's random table
# ($1F62C, 1024 words) depends on the boot time. The stand-in's clock reads the time the census
# runs booted in MAME (seed $CD87, recovered from their table; all three runs started together):
# 2026-10-19, a Monday, 14:01:38. Any other time gives another, equally valid table.
CLOCK_DATE = (1 << 16) | (2026 - 1980) << 9 | 10 << 5 | 19     # _GETDATE: weekday, y, m, d
CLOCK_TIME = 14 << 11 | 1 << 5 | 38 // 2                       # _GETTIME: h, m, s/2

MEM_TOP = 0xC00000                        # RAM mapped [0, $C00000)
IO_LO, IO_HI = 0xE00000, 0xF00000         # I/O: recorded shadow
LOW_HOOK = 0x10100                        # [0, here): vectors, IOCS/Human work, the fake MCDRV

EXCP_RTE = 0x100                          # QEMU's m68k "exception" for rte

GPIP = 0xE88001
VBLANK_READS, VDISP_READS = 468, 4276
HSYNC_READS = 8                           # one H period (31.75 us) per 8 reads, bit 7 set on 1

# Human68k IOCTRL(0, handle) device information for the standard handles, as the original run
# stored them at $2BC74 (CON in, CON out, CON err, AUX, PRN: bit 7 = character device).
STD_DEVINFO = {0: 0xC1, 1: 0xC2, 2: 0xC2, 3: 0xC0, 4: 0xC0}
FIRST_FH, LAST_FH = 5, 14                 # CONFIG.SYS FILES = 15

XSP_ARGS = {      # XSP199.MAN signatures; every argument is pushed as a long (XC); (name, kind)
    "xsp_on": [], "xsp_off": [], "xsp_out": [],
    "xsp_pcgdat_set": [("pcg", "ptr"), ("alt", "ptr"), ("size", "int")],
    "xsp_mask_set": [("mask", "ptr")],
    "xsp_mode2": [("mode", "int")],
    "xsp_objdat_set": [("frm", "ptr"), ("ref", "ptr")],
    "xsp_vsync": [("n", "int")],
    "xsp_set": [("x", "short"), ("y", "short"), ("pt", "short"), ("info", "short")],
    "xobj_set": [("x", "short"), ("y", "short"), ("pt", "short"), ("info", "short")],
    "xsp_set_st": [("st", "ptr")],
    "xobj_set_st": [("st", "ptr")],
    "xsp_divy_set2": [("div_y1", "int"), ("div_y2", "int"), ("div_y3", "int")],
    "xsp_wpoke": [("dest", "ptr"), ("data", "short")],
    "xsp_vertical": [("flag", "int")],
    "xsp_wtrans": [("chain", "ptr")],
}
# XSP's own vectors (inventory.md, hardware notes): what xsp_on installs on the original.
XSP_ON_VECTORS = [("xsp_on: MFP V-DISP vector $118", 0xEA8), ("xsp_on: CRTC raster vector $138", 0x1112)]

IO_SHADOW_READ = {   # registers whose read gives back the last value written (power-on 0)
    0xE8E007: "system port 4 (read-modify-write of bit 1 around the CRTC set-up, $19DC/$19E6)",
    0xE8002A: "CRTC R21 text access control (read-modify-write in the text clear $1888)",
    0xE8002B: "CRTC R21 low byte",
    0xE80029: "CRTC R20 low byte (as _CRTMOD left it, then as the game wrote it)",
}


# What the IPL ROM leaves in registers the game reads before writing them (MAME x68000 ipl10: a
# write tap from power-on sees the IPL write $0033 to R21 at $FF63C4/$FF63DC/$FF65D8; the IOCS's
# later byte writes (mask $FF00) go to the high byte and end at $00; R21 reads $0033 when the
# program has loaded, and the game's saved copy $1942 holds $0033 in the lock-step's record).
IO_BOOT = {0xE8002A: 0x00, 0xE8002B: 0x33}


# BG data: text pages 0 and 1, 64 x 64 words each (pattern, palette, flips), what _BGTEXTGT reads.
BG_DATA = 0xEBC000
BG_PAGE_SIZE = 0x2000
# Graphic VRAM: mapped only while call() runs game code that draws there (the game-start
# background builder); the start-up never touches it.
GVRAM_LO, GVRAM_SIZE = 0xC00000, 0x200000
CALL_STOP = FLOAT2_REQ + 0xC0             # call(): the return address it stops at (a nop)

# Hardware the IOCS ROM sets for a call: the register writes the stand-in models go to io_writes
# (with "via" and the call's seq; the call's record lists them under "io"); what is not modelled
# is named in the call's "unmodelled". BG control $EB0808: bit 9 sprite/BG display (XSP's own
# sp_disp is `bset #1,$EB0808`), bit 0 BG0 on, bits 2-1 BG0 text page, bit 3 BG1 on, bits 5-4
# BG1 text page. Video controller R1 $E82500: screen priority.
BG_CTRL = 0xEB0808
VC_R1 = 0xE82500

# _CRTMOD: CRTC R20 low byte the IPL ROM sets per mode (its CRTC table: every 256x256 31 kHz
# entry has R20 = $x310). Only the byte the game reads back is modelled.
CRTMOD_R20 = {0x0A: 0x10}

# DOS calls that only set console state: recorded with the words they take, return 0.
DOS_SIMPLE = {
    0xFF23: ("_CONCTRL", 2, "console control: mode.w and its word argument (mode 14: function-key"
                            " row display, from XC screen())"),
}


# Memory-like I/O ranges whose reads give back what was written (0 if never written: such
# reads are counted in io_reads_unwritten).
IO_SHADOW_RANGES = [
    (0xE00000, 0xE80000, "text VRAM"),
    (0xE82000, 0xE82400, "palettes (graphic, then text/sprite/BG): $641A reads back the text"
                         " palette it loaded to copy it to the graphic palette"),
    (0xEB0000, 0xEC0000, "sprite registers, BG registers, PCG and BG data"),
]


class HleError(RuntimeError):
    pass


def resolve(game_dir, name):
    """Human68k path (bytes) -> file under `game_dir` (= A:\\GAME), case-insensitive; None if it
    does not exist or lies outside GAME."""
    s = name.split(b"\0")[0].decode("cp932", "replace").replace("/", "\\")
    if len(s) >= 2 and s[1] == ":":
        s = s[2:]
    parts = [p for p in s.split("\\") if p not in ("", ".")]
    if s.startswith("\\"):
        if not parts or parts[0].upper() != "GAME":
            return None
        parts = parts[1:]
    cur = game_dir
    for p in parts:
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        hit = [n for n in names if n.upper() == p.upper()]
        if not hit:
            return None
        cur = os.path.join(cur, hit[0])
    return cur if os.path.isfile(cur) else None


def _nop(*_):
    pass


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


class X68k:
    def __init__(self, image, meta, base, game_dir, xsp_entries, resume_off, xsp_text=None,
                 float2=None, timeout_s=300, mcdrv_id=None):
        self.image, self.meta, self.base, self.game_dir = image, meta, base, game_dir
        # MCDRV's ID: given, or read from the disk the game is on (<game_dir>/../SYS/MCDRV.X)
        self.mcdrv_id = self.read_mcdrv_id(game_dir) if mcdrv_id is None else bytes(mcdrv_id)
        self.xsp_by_off = {off: name for name, off in xsp_entries.items()}
        self.xsp_text = xsp_text
        self.resume_off = resume_off
        self.timeout_s = timeout_s
        self.prog_end = meta["text"] + meta["data"] + meta["bss"]
        self.error = None
        self.super = False
        self.files = {}                    # fh -> [rel name, data, pos]
        self.dos_calls, self.iocs_calls, self.xsp_calls = [], [], []
        self.mcdrv_calls, self.float_calls, self.interrupts = [], [], []
        self.io_writes, self.io_reads, self.console = [], {}, []
        self.low_reads = {}
        self.gpip_t = 0
        self.io = bytearray(IO_HI - IO_LO)
        self.io_written = bytearray(IO_HI - IO_LO)
        for a, v in IO_BOOT.items():
            self.io[a - IO_LO] = v
            self.io_written[a - IO_LO] = 1
        self.io_reads_unwritten = {}
        self.phase = "game"
        self.system_calls = []             # what FLOAT2's own initialisation asked for
        self.vectors = {}                  # vector number -> handler installed with _B_INTVCS
        self.float2 = None
        self.seq = 0                       # one counter over every logged event (calls, I/O)

        mu = self.mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        mu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        mu.mem_map(0, MEM_TOP)
        mu.mmio_map(IO_LO, IO_HI - IO_LO, self._io_read, None, self._io_write, None)
        self._load()
        mu.hook_add(UC_HOOK_INTR, self._intr)
        mu.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._low, begin=0, end=LOW_HOOK - 1)
        # a (no-op) memory hook on the I/O range makes Unicorn keep the PC exact for the I/O
        # callbacks, so each recorded I/O access carries the pc of its instruction
        mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, _nop, begin=IO_LO, end=IO_HI - 1)
        if float2:
            self._load_float2(float2)
        if xsp_text:
            mu.hook_add(UC_HOOK_CODE, self._xsp, begin=base + xsp_text[0], end=base + xsp_text[1] - 1)
        else:
            for off in self.xsp_by_off:
                mu.hook_add(UC_HOOK_CODE, self._xsp, begin=base + off, end=base + off)

    # --- set-up ------------------------------------------------------------------------------

    @staticmethod
    def read_mcdrv_id(game_dir):
        """MCDRV's ID from the user's disk: MCDRV_ID's bytes of SYS/MCDRV.X beside `game_dir` (any
        case), checked by SHA1 (ValueError naming the file otherwise)."""
        name, at, n, sha1 = MCDRV_ID
        cur = os.path.dirname(os.path.abspath(game_dir))
        for part in name.split("/"):
            hit = [x for x in os.listdir(cur) if x.upper() == part.upper()]
            if not hit:
                raise ValueError("%s: not on the disk (%s)" % (name, os.path.join(cur, part)))
            cur = os.path.join(cur, hit[0])
        with open(cur, "rb") as f:
            return orig_bytes.take(f.read(), at, n, sha1, name)

    def _load(self):
        b, m, mu = self.base, self.meta, self.mu
        img = bytearray(self.image[:m["text"] + m["data"]])
        for r in m["relocs"]:
            v, = struct.unpack_from(">I", img, r)
            struct.pack_into(">I", img, r, (v + b) & 0xFFFFFFFF)
        mu.mem_write(b, bytes(img))
        psp = b + PSP_OFF
        ram_end = b + RAM_END_OFF
        self.psp, self.ram_end = psp, ram_end
        self.env, self.cmdline = b + ENV_OFF, b + CMDLINE_OFF
        mu.mem_write(self.env, struct.pack(">I", ENV_SIZE))
        mu.mem_write(self.cmdline, b"\0\0")
        mu.mem_write(psp + 0x08, struct.pack(">I", ram_end))          # memory block end
        mu.mem_write(psp + 0x10, struct.pack(">I", self.env))
        mu.mem_write(psp + 0x20, struct.pack(">I", self.cmdline))
        bss = b + m["text"] + m["data"]
        mu.mem_write(psp + 0x30, struct.pack(">II", bss, bss))
        mu.mem_write(psp + 0x80, b"A:\\GAME\\\0")
        mu.mem_write(psp + 0xC4, b"sz2.x\0")
        # the resident MCDRV: trap #4 vector, its ID and the long before the handler
        mu.mem_write(0x90, struct.pack(">I", MCDRV_ENTRY))
        mu.mem_write(MCDRV_ENTRY - 12, self.mcdrv_id + struct.pack(">I", MCDRV_LONG))
        mu.mem_write(MCDRV_ENTRY, b"\x4e\x73")                          # rte (never run)
        mu.reg_write(UC_M68K_REG_SR, 0x2000)
        mu.reg_write(UC_M68K_REG_A0, psp)
        mu.reg_write(UC_M68K_REG_A1, b + self.prog_end)
        mu.reg_write(UC_M68K_REG_A2, self.cmdline)
        mu.reg_write(UC_M68K_REG_A3, self.env)
        mu.reg_write(UC_M68K_REG_A4, b + m["entry"])
        mu.reg_write(UC_M68K_REG_A7, b + self.prog_end)

    def _load_float2(self, path):
        """Load FLOAT2.X (a PLZX-packed .X device driver) at FLOAT2_AT and run its init (strategy,
        then interrupt routine, command 0) as Human68k does for a CONFIG.SYS DEVICE= line."""
        with open(path, "rb") as f:
            x = f.read()
        if x[:2] != b"HU":
            raise HleError("%s: not a Human68k .X file" % path)
        text, data, bss, rsize = struct.unpack(">IIII", x[0x0C:0x1C])
        img = bytearray(x[0x40:0x40 + text + data])
        rt = x[0x40 + text + data:0x40 + text + data + rsize]
        pos, i = 0, 0
        while i < len(rt):
            d, = struct.unpack_from(">H", rt, i)
            i += 2
            if d == 1:
                d, = struct.unpack_from(">I", rt, i)
                i += 4
            pos += d
            v, = struct.unpack_from(">I", img, pos)
            struct.pack_into(">I", img, pos, v + FLOAT2_AT)
        mu = self.mu
        mu.mem_write(FLOAT2_AT, bytes(img))
        req, line, stop = FLOAT2_REQ, FLOAT2_REQ + 0x40, FLOAT2_REQ + 0x80
        mu.mem_write(req, bytes([26, 0, 0]) + bytes(23))
        mu.mem_write(req + 0x12, struct.pack(">I", line))
        mu.mem_write(line, b"\\SYS\\FLOAT2.x\0\0")
        mu.mem_write(stop, b"\x4e\x71")
        regs = {r: self.reg(r) for r in DREGS + AREGS + [UC_M68K_REG_SR]}
        for r in DREGS + AREGS:               # the driver starts with none of the game's registers
            self.setreg(r, 0)
        self.phase = "float2"
        for field in (6, 10):                 # strategy, then interrupt (the stub fixes it)
            entry = self.r32(FLOAT2_AT + field)
            sp = stop - 0x10
            self.w32(sp, stop)
            self.setreg(UC_M68K_REG_A7, sp)
            self.setreg(UC_M68K_REG_A5, req)
            self.mu.emu_start(entry, stop, timeout=10_000_000)
            if self.error or self.reg(UC_M68K_REG_PC) != stop:
                raise HleError("FLOAT2 init: %s" % (self.error or "did not return"))
        self.phase = "game"
        status = self.r16(req + 3)
        handler = self.vectors.get(0x0B)
        if status or handler is None:
            raise HleError("FLOAT2 init failed (status $%04X, line-F handler %r)" % (status, handler))
        self.float2 = {"at": FLOAT2_AT, "end": self.r32(req + 0x0E), "fline": handler,
                       "vectors": {"$%02X" % k: v for k, v in sorted(self.vectors.items())}}
        for r, v in regs.items():
            self.setreg(r, v)

    # --- helpers -----------------------------------------------------------------------------

    def _next(self):
        self.seq += 1
        return self.seq - 1

    def rel(self, v):
        """An address the program holds -> base-0 (values outside the moving layout unchanged)."""
        v &= 0xFFFFFFFF
        if self.base + BELOW_BASE <= v <= self.base + RAM_END_OFF:
            return v - self.base
        return v

    def read(self, off, n):
        return bytes(self.mu.mem_read(self.base + off, n))

    def r8(self, a):
        return self.mu.mem_read(a, 1)[0]

    def r16(self, a):
        return struct.unpack(">H", self.mu.mem_read(a, 2))[0]

    def r32(self, a):
        return struct.unpack(">I", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack(">I", v & 0xFFFFFFFF))

    def reg(self, r):
        return self.mu.reg_read(r)

    def setreg(self, r, v):
        self.mu.reg_write(r, v & 0xFFFFFFFF)

    def cstr(self, a, limit=512):
        raw = bytes(self.mu.mem_read(a, limit))
        return raw.split(b"\0")[0]

    def call_site(self, ret):
        """Base-0 offset of the jsr/bsr that pushed return address `ret`."""
        for n, ops in ((6, (0x4EB9,)), (4, (0x6100,)), (2, None)):
            op = self.r16(ret - n)
            if ops is None or op in ops:
                return ret - n - self.base
        return ret - self.base

    def _pc_rec(self, pc):
        """A call site for the logs: base-0 in the program, "FLOAT2+$x" in FLOAT2's code."""
        if FLOAT2_AT <= pc < FLOAT2_AT + 0x8000:
            return "FLOAT2+$%X" % (pc - FLOAT2_AT)
        return pc - self.base

    def pc_off(self):
        return self.reg(UC_M68K_REG_PC) - self.base

    def fail(self, msg):
        if self.error is None:
            self.error = "%s (pc $%X)" % (msg, self.reg(UC_M68K_REG_PC) - self.base)
        self.mu.emu_stop()

    def regs(self):
        return {n: self.reg(r) for n, r in zip(REG_NAMES, DREGS + AREGS[:7])}

    # --- run ---------------------------------------------------------------------------------

    def run(self):
        start = self.base + self.meta["entry"]
        until = self.base + self.resume_off if self.resume_off is not None else 0xFFFFFFFF
        try:
            self.mu.emu_start(start, until, timeout=int(self.timeout_s * 1e6))
        except UcError as e:
            if self.error is None:
                self.error = "%s at pc $%X" % (e, self.reg(UC_M68K_REG_PC) - self.base)
        if self.error:
            raise HleError(self.error)
        if self.reg(UC_M68K_REG_PC) != until:
            raise HleError("stopped at pc $%X before the resume point $%X (timeout?)" %
                           (self.pc_off(), self.resume_off))
        if not self.reg(UC_M68K_REG_SR) & 0x2000:
            raise HleError("the CPU left supervisor mode")

    def call(self, off, args=(), gvram=False):
        """Run the game's function at base-0 `off` from the current state (after run()): `args`
        pushed as longs (XC), until it returns; d0. With `gvram`, graphic VRAM is mapped (plain
        memory) for code that draws there."""
        if gvram and not getattr(self, "gvram_mapped", False):
            self.mu.mem_map(GVRAM_LO, GVRAM_SIZE)
            self.gvram_mapped = True
        self.mu.mem_write(CALL_STOP, b"\x4e\x71")
        sp = self.reg(UC_M68K_REG_A7)
        for v in reversed(list(args)):
            sp -= 4
            self.w32(sp, v)
        sp -= 4
        self.w32(sp, CALL_STOP)
        self.setreg(UC_M68K_REG_A7, sp)
        try:
            self.mu.emu_start(self.base + off, CALL_STOP, timeout=int(self.timeout_s * 1e6))
        except UcError as e:
            if self.error is None:
                self.error = "%s at pc $%X" % (e, self.reg(UC_M68K_REG_PC) - self.base)
        if self.error:
            raise HleError(self.error)
        if self.reg(UC_M68K_REG_PC) != CALL_STOP:
            raise HleError("call $%X stopped at pc $%X (timeout?)" % (off, self.pc_off()))
        self.setreg(UC_M68K_REG_A7, sp + 4 + 4 * len(args))
        return self.reg(UC_M68K_REG_D0)

    # --- hooks -------------------------------------------------------------------------------

    def _unmapped(self, uc, access, addr, size, value, _):
        self.fail("unmapped access $%X (size %d)" % (addr, size))
        return False

    def _low(self, uc, access, addr, size, value, _):
        if access == UC_MEM_WRITE:
            self.fail("write to system memory $%X" % addr)
            return
        if addr in (0x90, MPU_TYPE_ADDR) or MCDRV_ENTRY - 12 <= addr < MCDRV_ENTRY:
            key = "$%X" % addr
            self.low_reads[key] = self.low_reads.get(key, 0) + 1
            return
        self.fail("read of system memory $%X" % addr)

    def _io_read(self, uc, off, size, _):
        a = IO_LO + off
        if a == GPIP and size == 1:
            t = self.gpip_t % (VBLANK_READS + VDISP_READS)
            self.gpip_t += 1
            v = self.io[off] & ~0x90 | (0x10 if t >= VBLANK_READS else 0) | \
                (0x80 if self.gpip_t % HSYNC_READS == 0 else 0)
            self._count_read(a)
            return v
        if all(a + i in IO_SHADOW_READ or any(lo <= a + i < hi for lo, hi, _ in IO_SHADOW_RANGES)
               for i in range(size)):
            self._count_read(a)
            if not all(self.io_written[off:off + size]):
                k = "$%X" % a
                self.io_reads_unwritten[k] = self.io_reads_unwritten.get(k, 0) + 1
            return int.from_bytes(self.io[off:off + size], "big")
        self.fail("I/O read $%X (size %d) not modelled" % (a, size))
        return 0

    def _count_read(self, a):
        k = next(("%s $%X-$%X" % (n, lo, hi - 1) for lo, hi, n in IO_SHADOW_RANGES if lo <= a < hi),
                 None) or "$%X" % a
        k = k.split(":")[0]
        self.io_reads[k] = self.io_reads.get(k, 0) + 1

    def _io_write(self, uc, off, size, value, _):
        self.io_written[off:off + size] = b"\1" * size
        self.io[off:off + size] = (value & ((1 << 8 * size) - 1)).to_bytes(size, "big")
        self.io_writes.append({"seq": self._next(), "addr": IO_LO + off, "size": size,
                               "value": value & ((1 << 8 * size) - 1), "pc": self.pc_off()})

    def _xsp(self, uc, addr, size, _):
        off = addr - self.base
        name = self.xsp_by_off.get(off)
        if name is None:
            self.fail("XSP code executed at $%X (not a C entry)" % off)
            return
        sp = self.reg(UC_M68K_REG_A7)
        ret = self.r32(sp)
        args = {}
        for i, (an, kind) in enumerate(XSP_ARGS[name]):
            v = self.r32(sp + 4 + 4 * i)
            args[an] = self.rel(v) if kind == "ptr" else s16(v) if kind == "short" else s32(v)
        r = self._xsp_ret(name, args)
        if r is False:
            return
        self.xsp_calls.append({"seq": self._next(), "name": name, "pc": self.call_site(ret),
                               "args": args, "ret": r})
        if name == "xsp_on":
            for kind, h in XSP_ON_VECTORS:
                self.interrupts.append({"seq": self._next(), "kind": kind, "handler": h,
                                        "via": "xsp_on (XSP code, not run)"})
        if r is not None:
            self.setreg(UC_M68K_REG_D0, r)
        self.setreg(UC_M68K_REG_A7, sp + 4)
        self.setreg(UC_M68K_REG_PC, ret)

    def _xsp_ret(self, name, args):
        """What XSP returns (XSP199.MAN): void calls None; xsp_vsync the missed blanks (0)."""
        if name in ("xsp_on", "xsp_off", "xsp_pcgdat_set", "xsp_mask_set", "xsp_mode2",
                    "xsp_objdat_set", "xsp_vertical", "xsp_divy_set2", "xsp_wtrans"):
            return None
        if name == "xsp_vsync":
            return 0
        self.fail("XSP %s during the start-up: return value not modelled" % name)
        return False

    def _intr(self, uc, intno, _):
        pc = self.reg(UC_M68K_REG_PC)
        self.redirected = False
        if intno == 11:
            op = self.r16(pc)
            if op >= 0xFF00:
                self._dos(op, pc)
            elif op >= 0xFE00:
                self._fefunc(op, pc)
            else:
                self.fail("F-line $%04X" % op)
        elif intno == 47:
            self._iocs(pc)
        elif intno == 36:
            self._mcdrv(pc)
        elif intno == EXCP_RTE:              # Unicorn hands rte to the hook: return from FLOAT2
            sp = self.reg(UC_M68K_REG_A7)
            sr, ret = struct.unpack(">HI", self.mu.mem_read(sp, 6))
            if not sr & 0x2000:
                self.fail("rte to user mode")
                return
            self.setreg(UC_M68K_REG_SR, sr)
            self.setreg(UC_M68K_REG_A7, sp + 6)
            self.setreg(UC_M68K_REG_PC, ret)
            self.redirected = True
        else:
            self.fail("CPU exception %d" % intno)
            return
        if self.error is None and not self.redirected:
            self.setreg(UC_M68K_REG_PC, pc + 2)

    # --- MCDRV (trap #4) ---------------------------------------------------------------------

    def _mcdrv(self, pc):
        fn = self.reg(UC_M68K_REG_D0)
        self.mcdrv_calls.append({"seq": self._next(), "fn": fn, "pc": pc - self.base,
                                 "d1": self.reg(UC_M68K_REG_D1),
                                 "a0": self.rel(self.reg(UC_M68K_REG_A0))})
        self.setreg(UC_M68K_REG_D0, 0)

    # --- FLOAT driver (F-line $FExx) -----------------------------------------------------------

    def _fefunc(self, op, pc):
        """A $FExx call goes to FLOAT2's line-F handler as the CPU would take it: a 68000 frame
        (SR, PC of the F-line word) on the stack, PC = handler; FLOAT2 steps over the word and
        returns with rte. Logged with its inputs (d0:d1; for the __CD calls the two doubles on the
        stack)."""
        if not self.float2:
            self.fail("FLOAT call $%04X without FLOAT2" % op)
            return
        sp = self.reg(UC_M68K_REG_A7)
        name = x68k_names.FEFUNC.get(op, "?")
        rec = {"seq": self._next(), "fn": "$%04X" % op, "name": name, "pc": pc - self.base,
               "d0d1": [self.reg(r) for r in DREGS[:2]]}
        if name.startswith("__CD"):
            rec["stack"] = bytes(self.mu.mem_read(sp, 16)).hex()      # its two double operands
        self.float_calls.append(rec)
        sp -= 6
        self.mu.mem_write(sp, struct.pack(">HI", self.reg(UC_M68K_REG_SR) & 0xFFFF, pc))
        self.setreg(UC_M68K_REG_A7, sp)
        self.setreg(UC_M68K_REG_PC, self.float2["fline"])
        self.redirected = True

    # --- Human68k DOS (F-line $FFxx) ------------------------------------------------------------

    def _dos(self, op, pc):
        sp = self.reg(UC_M68K_REG_A7)
        name = x68k_names.DOS.get(op, "?")
        rec = {"seq": self._next(), "call": name, "fn": "$%04X" % op, "pc": self._pc_rec(pc)}
        h = getattr(self, "_dos_%02X" % (op & 0xFF), None)
        if h is None and op in DOS_SIMPLE:
            h = self._dos_simple
            rec["words"] = [self.r16(sp + 2 * i) for i in range(DOS_SIMPLE[op][1])]
        if h is None:
            self.fail("DOS call $%04X %s not handled" % (op, name))
            return
        ret = h(sp, rec)
        if self.error:
            return
        rec["ret"] = ret
        (self.system_calls if self.phase != "game" else self.dos_calls).append(rec)
        self.setreg(UC_M68K_REG_D0, ret)

    def _dos_simple(self, sp, rec):
        return 0

    def _dos_3D(self, sp, rec):            # _OPEN(name.l, mode.w)
        raw = self.cstr(self.r32(sp))
        mode = self.r16(sp + 4)
        rec.update(name=raw.decode("cp932", "replace"), mode=mode)
        if mode & 3:
            self.fail("_OPEN %r for writing (the disk is served read-only)" % raw)
            return 0
        path = resolve(self.game_dir, raw)
        if path is None:
            rec["file"] = None
            return -2                         # file not found
        fh = next((h for h in range(FIRST_FH, LAST_FH + 1) if h not in self.files), None)
        if fh is None:
            return -4                         # too many open files
        with open(path, "rb") as f:
            data = f.read()
        relname = os.path.relpath(path, self.game_dir).replace(os.sep, "/")
        rec["file"] = relname
        self.files[fh] = [relname, data, 0]
        return fh

    def _fh(self, fh):
        f = self.files.get(fh)
        if f is None:
            self.fail("file handle %d not open" % fh)
        return f

    def _dos_3F(self, sp, rec):            # _READ(fh.w, buf.l, len.l)
        fh, buf, n = self.r16(sp), self.r32(sp + 2), s32(self.r32(sp + 6))
        rec.update(fh=fh, buf=self.rel(buf), len=n)
        f = self._fh(fh)
        if f is None:
            return 0
        chunk = f[1][f[2]:f[2] + max(n, 0)]
        self.mu.mem_write(buf, chunk)
        f[2] += len(chunk)
        rec.update(file=f[0], pos=f[2] - len(chunk))
        return len(chunk)

    def _dos_3E(self, sp, rec):            # _CLOSE(fh.w)
        fh = self.r16(sp)
        rec["fh"] = fh
        if fh < FIRST_FH:
            return 0
        if self._fh(fh) is None:
            return 0
        rec["file"] = self.files.pop(fh)[0]
        return 0

    def _dos_42(self, sp, rec):            # _SEEK(fh.w, offset.l, mode.w)
        fh, off, mode = self.r16(sp), s32(self.r32(sp + 2)), self.r16(sp + 6)
        rec.update(fh=fh, offset=off, mode=mode)
        f = self._fh(fh)
        if f is None:
            return 0
        new = {0: 0, 1: f[2], 2: len(f[1])}.get(mode, -1)
        if new < 0:
            self.fail("_SEEK mode %d" % mode)
            return 0
        new += off
        if new < 0 or new > len(f[1]):
            return -25                        # can't seek
        f[2] = new
        rec["file"] = f[0]
        return new

    def _dos_40(self, sp, rec):            # _WRITE(fh.w, buf.l, len.l)
        fh, buf, n = self.r16(sp), self.r32(sp + 2), s32(self.r32(sp + 6))
        data = bytes(self.mu.mem_read(buf, n)) if n > 0 else b""
        rec.update(fh=fh, buf=self.rel(buf), len=n, data=data.hex())
        if fh not in (1, 2):
            self.fail("_WRITE to handle %d" % fh)
            return 0
        self.console.append(data)
        return n

    def _dos_44(self, sp, rec):            # _IOCTRL(mode.w, ...)
        mode = self.r16(sp)
        rec["mode"] = mode
        if mode == 0:                         # device information of a handle
            fh = self.r16(sp + 2)
            rec["fh"] = fh
            if fh in STD_DEVINFO:
                return STD_DEVINFO[fh]
            if fh in self.files:
                return 0                      # a file on drive A:
            return -6                         # invalid handle
        self.fail("_IOCTRL mode %d" % mode)
        return 0

    def _dos_4A(self, sp, rec):            # _SETBLOCK(ptr.l, size.l)
        ptr, size = self.r32(sp), self.r32(sp + 4)
        rec.update(ptr=self.rel(ptr), size=size)
        if ptr != self.psp + 0x10:
            self.fail("_SETBLOCK of a block other than the program's ($%X)" % ptr)
            return 0
        avail = self.ram_end - ptr
        if size > avail:
            return s32(0x81000000 | avail)    # not enough memory: $81 + the largest size
        self.w32(self.psp + 0x08, ptr + size)
        return 0

    def _dos_25(self, sp, rec):            # _INTVCS(vector.w, handler.l)
        vec, addr = self.r16(sp), self.r32(sp + 2)
        kind = "_INTVCS $%04X %s" % (vec, x68k_names.DOS.get(vec, "vector $%X" % vec))
        rec.update(vector=vec, handler=self.rel(addr))
        self.interrupts.append({"seq": rec["seq"], "kind": kind, "handler": self.rel(addr),
                                "via": "DOS _INTVCS"})
        return FAKE_OLD_VECTOR

    def _dos_20(self, sp, rec):            # _SUPER(stack.l)
        st = self.r32(sp)
        rec["stack"] = self.rel(st)
        if st == 0:
            if self.super:
                self.fail("_SUPER(0) in supervisor mode")
                return 0
            self.super = True
            return SSP_VALUE
        self.super = False
        return 0

    def _dos_2A(self, sp, rec):            # _GETDATE (the clock: see CLOCK_DATE)
        return CLOCK_DATE

    def _dos_2C(self, sp, rec):            # _GETTIME
        return CLOCK_TIME

    def _dos_09(self, sp, rec):            # _PRINT(string.l)
        text = self.cstr(self.r32(sp), 4096)
        rec["data"] = text.hex()
        self.console.append(text)
        return 0

    def _dos_51(self, sp, rec):            # _GETPDB
        return self.psp + 0x10

    # --- IOCS (trap #15) -----------------------------------------------------------------------

    def _iocs(self, pc):
        fn = self.reg(UC_M68K_REG_D0) & 0xFF
        name = x68k_names.IOCS.get(fn, "?")
        rec = {"seq": self._next(), "fn": fn, "name": name, "pc": self._pc_rec(pc)}
        h = getattr(self, "_iocs_%02X" % fn, None)
        if h is None:
            self.fail("IOCS call $%02X %s not handled" % (fn, name))
            return
        ret = h(rec)
        if self.error:
            return
        rec["ret"] = ret
        (self.system_calls if self.phase != "game" else self.iocs_calls).append(rec)
        if ret is not None:
            self.setreg(UC_M68K_REG_D0, ret)

    def _iocs_10(self, rec):               # _CRTMOD(d1.w = mode): XC screen() at $15722
        mode = self.reg(UC_M68K_REG_D1) & 0xFFFF
        rec["d1"] = mode
        if mode & 0xFF not in CRTMOD_R20:
            self.fail("_CRTMOD mode $%X not modelled" % mode)
            return 0
        # what the IOCS ROM leaves in the CRTC register the game reads back (R20 low byte,
        # compared at $1962 to pick the order of its own CRTC writes)
        self._hw(rec, 0xE80029, 1, CRTMOD_R20[mode & 0xFF])
        rec["unmodelled"] = ("the rest of the mode: CRTC R0-R8, R20 high byte, video controller,"
                             " text screen (the game sets CRTC R0-R8 and R20 itself at $194A)")
        return 0                              # d0 is not used by the caller

    def _hw(self, rec, a, size, value):
        """A register write the IOCS ROM makes for the call `rec`: shadow + io_writes."""
        off = a - IO_LO
        value &= (1 << 8 * size) - 1
        self.io[off:off + size] = value.to_bytes(size, "big")
        self.io_written[off:off + size] = b"\1" * size
        w = {"seq": self._next(), "addr": a, "size": size, "value": value, "pc": rec["pc"],
             "via": rec["name"]}
        self.io_writes.append(w)
        rec.setdefault("io", []).append({"addr": a, "size": size, "value": value})

    def _shadow16(self, a):
        off = a - IO_LO
        return int.from_bytes(self.io[off:off + 2], "big")

    def _iocs_90(self, rec):               # _G_CLR_ON: graphic screen clear, display on
        rec["unmodelled"] = "graphic VRAM clear and graphic display on (video controller R2)"
        return 0                              # d0 not used

    def _iocs_92(self, rec):               # _PRIORITY(d1) ($6332: d1 = $12E4)
        d1 = self.reg(UC_M68K_REG_D1) & 0xFFFF
        rec["d1"] = d1
        rec["note"] = "IOCS name recalled; d1 $12E4 has the layout of video controller R1"
        self._hw(rec, VC_R1, 2, d1)
        return 0                              # d0 not used

    def _iocs_C1(self, rec):               # _SP_ON: sprite/BG display on (XC sp_on())
        self._hw(rec, BG_CTRL, 2, self._shadow16(BG_CTRL) | 0x0200)
        return 0

    def _iocs_C2(self, rec):               # _SP_OFF
        self._hw(rec, BG_CTRL, 2, self._shadow16(BG_CTRL) & ~0x0200)
        return 0

    def _iocs_CA(self, rec):               # _BGCTRLST(d1 = BG plane, d2 = text page, d3 = display;
        d1, d2, d3 = (s32(self.reg(r)) for r in DREGS[1:4])   # -1 = unchanged); XC bg_set()
        rec.update(d1=d1, d2=d2, d3=d3)
        if d1 not in (0, 1) or d2 not in (-1, 0, 1) or d3 not in (-1, 0, 1):
            self.fail("_BGCTRLST(%d, %d, %d)" % (d1, d2, d3))
            return 0
        v = self._shadow16(BG_CTRL)
        on, page = (0, 1) if d1 == 0 else (3, 4)
        if d2 >= 0:
            v = v & ~(3 << page) | d2 << page
        if d3 >= 0:
            v = v & ~(1 << on) | d3 << on
        self._hw(rec, BG_CTRL, 2, v)
        return 0

    def _iocs_CE(self, rec):               # _BGTEXTGT(d1 = BG text page, d2 = x, d3 = y): the cell
        d1, d2, d3 = (s32(self.reg(r)) for r in DREGS[1:4])   # word (d0.w); $679C, game start
        rec.update(d1=d1, d2=d2, d3=d3)
        if d1 not in (0, 1) or not 0 <= d2 < 64 or not 0 <= d3 < 64:
            self.fail("_BGTEXTGT(%d, %d, %d) not modelled" % (d1, d2, d3))
            return 0
        a = BG_DATA + d1 * BG_PAGE_SIZE + (d3 * 64 + d2) * 2
        if not all(self.io_written[a - IO_LO:a - IO_LO + 2]):
            self.fail("_BGTEXTGT(%d, %d, %d): a cell nothing wrote (power-on content not "
                      "modelled)" % (d1, d2, d3))
            return 0
        return self._shadow16(a)

    def _iocs_81(self, rec):               # _B_SUPER(a1): a1 = 0 -> supervisor, else back to user
        a1 = self.reg(UC_M68K_REG_A1)
        rec["a1"] = self.rel(a1)
        if a1 == 0:
            if self.super:
                return -1                     # already in supervisor mode
            self.super = True
            return SSP_VALUE
        self.super = False
        return 0

    def _regs_rec(self, rec, names):
        for n in names:
            r = (DREGS + AREGS)[REG_NAMES.index(n)] if n in REG_NAMES else None
            rec[n] = self.reg(r)

    def _iocs_7D(self, rec):               # _SKEY_MOD(d1): software keyboard display mode
        self._regs_rec(rec, ["d1"])
        rec["unmodelled"] = "software keyboard window state (console)"
        return 0                              # the previous mode: off

    def _iocs_AF(self, rec):               # _OS_CUROF: text cursor off
        rec["unmodelled"] = "text cursor blink off (console)"
        return 0

    def _iocs_80(self, rec):               # _B_INTVCS(d1 = vector number, a1 = handler): old one
        vec, a1 = self.reg(UC_M68K_REG_D1) & 0xFFFF, self.reg(UC_M68K_REG_A1)
        rec.update(d1=vec, a1=a1)
        old = self.vectors.get(vec, HUMAN_FLINE if vec == 0x0B else FAKE_OLD_VECTOR)
        self.vectors[vec] = a1
        if self.phase == "game":
            self.interrupts.append({"seq": rec["seq"], "kind": "_B_INTVCS vector $%02X" % vec,
                                    "handler": self.rel(a1), "via": "IOCS _B_INTVCS"})
        return old

    def _peek(self, rec, n):               # _B_BPEEK / _B_LPEEK: d0 = (a1), a1 += n
        a1 = self.reg(UC_M68K_REG_A1)
        rec["a1"] = self.rel(a1)
        if not 0 <= a1 < MEM_TOP:
            self.fail("IOCS peek of $%X (not RAM)" % a1)
            return 0
        self.setreg(UC_M68K_REG_A1, a1 + n)
        return int.from_bytes(self.mu.mem_read(a1, n), "big")

    def _iocs_82(self, rec):               # _B_BPEEK ($CBC: MPU type 0 = 68000)
        return self._peek(rec, 1)

    def _iocs_84(self, rec):               # _B_LPEEK (FLOAT2 looks for its ID before the old
        return self._peek(rec, 4)           # line-F handler: zero memory, so not installed yet)

    def _palette(self, rec, a, value):
        """A palette entry the IOCS ROM reads or writes: returns the colour before the call;
        a write (value != -1) goes to the shadow and into io_writes (tagged "via")."""
        off = a - IO_LO
        old = int.from_bytes(self.io[off:off + 2], "big")
        if not all(self.io_written[off:off + 2]):
            k = "$%X" % a
            self.io_reads_unwritten[k] = self.io_reads_unwritten.get(k, 0) + 1
        if value != -1:
            self._hw(rec, a, 2, value)
        return old

    def _iocs_14(self, rec):               # _TPALET2(d1 = text palette code, d2 = colour, -1 = read)
        d1, d2 = self.reg(UC_M68K_REG_D1), s32(self.reg(UC_M68K_REG_D2))
        rec.update(d1=d1 & 0xFFFF, d2=d2)
        if d1 & 0xFFFF > 15:
            self.fail("_TPALET2 code %d" % d1)
            return 0
        return self._palette(rec, 0xE82200 + (d1 & 0xFFFF) * 2, d2)

    def _iocs_CF(self, rec):               # _SPALET(d1 = code (bit 31: in V-blank), d2 = block,
        d1, d2, d3 = (self.reg(r) for r in DREGS[1:4])   # d3 = colour, -1 = read)
        rec.update(d1=d1, d2=d2, d3=s32(d3))
        code, block = d1 & 0xFF, s32(d2)
        if code > 15 or not 0 <= block <= 15:
            self.fail("_SPALET code %d block %d" % (code, block))
            return 0
        return self._palette(rec, 0xE82200 + block * 32 + code * 2, s32(d3))
