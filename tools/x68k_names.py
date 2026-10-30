"""Names of the X68000's system calls and hardware registers, used by tools/inventory.py.

Human68k DOS calls (F-line $FFxx), IOCS calls (trap #15, d0 = n), FLOAT driver calls (F-line
$FExx) and the I/O registers the game touches. Lists follow the standard Human68k/IOCS call
tables (doscall.mac / iocscall.mac numbering); entries marked "?" are recalled with less
certainty and should be checked against a reference before relying on them.
"""

DOS = {
    0xFF00: "_EXIT", 0xFF01: "_GETCHAR", 0xFF02: "_PUTCHAR", 0xFF03: "_COMINP", 0xFF04: "_COMOUT",
    0xFF05: "_PRNOUT", 0xFF06: "_INPOUT", 0xFF07: "_INKEY", 0xFF08: "_GETC", 0xFF09: "_PRINT",
    0xFF0A: "_GETS", 0xFF0B: "_KEYSNS", 0xFF0C: "_KFLUSH", 0xFF0D: "_FFLUSH", 0xFF0E: "_CHGDRV",
    0xFF0F: "_DRVCTRL", 0xFF10: "_CONSNS", 0xFF11: "_PRNSNS", 0xFF12: "_CINSNS", 0xFF13: "_COUTSNS",
    0xFF17: "_FATCHK", 0xFF18: "_HENDSP", 0xFF19: "_CURDRV", 0xFF1A: "_GETSS", 0xFF1B: "_FGETC",
    0xFF1C: "_FGETS", 0xFF1D: "_FPUTC", 0xFF1E: "_FPUTS", 0xFF1F: "_ALLCLOSE", 0xFF20: "_SUPER",
    0xFF21: "_FNCKEY", 0xFF22: "_KNJCTRL", 0xFF23: "_CONCTRL", 0xFF24: "_KEYCTRL", 0xFF25: "_INTVCS",
    0xFF26: "_PSPSET", 0xFF27: "_GETTIM2", 0xFF28: "_SETTIM2", 0xFF29: "_NAMESTS", 0xFF2A: "_GETDATE",
    0xFF2B: "_SETDATE", 0xFF2C: "_GETTIME", 0xFF2D: "_SETTIME", 0xFF2E: "_VERIFY", 0xFF2F: "_DUP0",
    0xFF30: "_VERNUM", 0xFF31: "_KEEPPR", 0xFF32: "_GETDPB", 0xFF33: "_BREAKCK", 0xFF34: "_DRVXCHG",
    0xFF35: "_INTVCG", 0xFF36: "_DSKFRE", 0xFF37: "_NAMECK", 0xFF39: "_MKDIR", 0xFF3A: "_RMDIR",
    0xFF3B: "_CHDIR", 0xFF3C: "_CREATE", 0xFF3D: "_OPEN", 0xFF3E: "_CLOSE", 0xFF3F: "_READ",
    0xFF40: "_WRITE", 0xFF41: "_DELETE", 0xFF42: "_SEEK", 0xFF43: "_CHMOD", 0xFF44: "_IOCTRL",
    0xFF45: "_DUP", 0xFF46: "_DUP2", 0xFF47: "_CURDIR", 0xFF48: "_MALLOC", 0xFF49: "_MFREE",
    0xFF4A: "_SETBLOCK", 0xFF4B: "_EXEC", 0xFF4C: "_EXIT2", 0xFF4D: "_WAIT", 0xFF4E: "_FILES",
    0xFF4F: "_NFILES",
    # Human68k v1 numbering of the calls v2+ moved to $FF80-: same functions
    0xFF50: "_SETPDB (v1 no.)", 0xFF51: "_GETPDB (v1 no.)", 0xFF52: "_SETENV (v1 no.)",
    0xFF53: "_GETENV (v1 no.)", 0xFF54: "_VERIFYG (v1 no.)", 0xFF55: "_COMMON (v1 no.)",
    0xFF56: "_RENAME (v1 no.)", 0xFF57: "_FILEDATE (v1 no.)", 0xFF58: "_MALLOC2 (v1 no.)",
    0xFF80: "_SETPDB", 0xFF81: "_GETPDB", 0xFF82: "_SETENV", 0xFF83: "_GETENV", 0xFF84: "_VERIFYG",
    0xFF85: "_COMMON", 0xFF86: "_RENAME", 0xFF87: "_FILEDATE", 0xFF88: "_MALLOC2",
    0xFFF0: "_EXITVC", 0xFFF1: "_CTRLVC", 0xFFF2: "_ERRJVC", 0xFFF3: "_DISKRED", 0xFFF4: "_DISKWRT",
    0xFFF5: "_INDOSFLG", 0xFFF6: "_SUPER_JSR", 0xFFF7: "_BUS_ERR", 0xFFF8: "_OPEN_PR",
    0xFFF9: "_KILL_PR", 0xFFFA: "_GET_PR", 0xFFFB: "_SUSPEND_PR", 0xFFFC: "_SLEEP_PR",
    0xFFFD: "_SEND_PR", 0xFFFE: "_TIME_PR", 0xFFFF: "_CHANGE_PR",
}

IOCS = {
    0x00: "_B_KEYINP", 0x01: "_B_KEYSNS", 0x02: "_B_SFTSNS", 0x03: "_KEY_INIT", 0x04: "_BITSNS",
    0x05: "_SKEYSET", 0x06: "_LEDCTRL", 0x07: "_LEDSET", 0x08: "_KEYDLY", 0x09: "_KEYREP",
    0x0C: "_TVCTRL", 0x0D: "_LEDMOD", 0x0E: "_TGUSEMD", 0x0F: "_DEFCHR", 0x10: "_CRTMOD",
    0x11: "_CONTRAST", 0x12: "_HSVTORGB", 0x13: "_TPALET", 0x14: "_TPALET2", 0x15: "_TCOLOR",
    0x16: "_FNTADR", 0x17: "_VRAMGET", 0x18: "_VRAMPUT", 0x19: "_FNTGET", 0x1A: "_TEXTGET",
    0x1B: "_TEXTPUT", 0x1C: "_CLIPPUT", 0x1D: "_SCROLL", 0x1E: "_B_CURON", 0x1F: "_B_CUROFF",
    0x20: "_B_PUTC", 0x21: "_B_PRINT", 0x22: "_B_COLOR", 0x23: "_B_LOCATE", 0x24: "_B_DOWN_S",
    0x25: "_B_UP_S", 0x26: "_B_UP", 0x27: "_B_DOWN", 0x28: "_B_RIGHT", 0x29: "_B_LEFT",
    0x2A: "_B_CLR_ST", 0x2B: "_B_ERA_ST", 0x2C: "_B_INS", 0x2D: "_B_DEL", 0x2E: "_B_CONSOL",
    0x2F: "_B_PUTMES", 0x3B: "_JOYGET",
    0x60: "_ADPCMOUT", 0x61: "_ADPCMINP", 0x62: "_ADPCMAOT", 0x63: "_ADPCMAIN", 0x64: "_ADPCMLOT",
    0x65: "_ADPCMLIN", 0x66: "_ADPCMSNS", 0x67: "_ADPCMMOD", 0x68: "_OPMSET", 0x69: "_OPMSNS",
    0x6A: "_OPMINTST", 0x6B: "_TIMERDST", 0x6C: "_VDISPST", 0x6D: "_CRTCRAS", 0x6E: "_HSYNCST",
    0x6F: "_PRNINTST", 0x7D: "_SKEY_MOD", 0x7E: "_DENSNS", 0x7F: "_ONTIME",
    0x80: "_B_INTVCS", 0x81: "_B_SUPER", 0x82: "_B_BPEEK", 0x83: "_B_WPEEK", 0x84: "_B_LPEEK",
    0x85: "_B_MEMSTR", 0x86: "_B_BPOKE", 0x87: "_B_WPOKE", 0x88: "_B_LPOKE", 0x89: "_B_MEMSET",
    0x8A: "_DMAMOVE", 0x8B: "_DMAMOV_A", 0x8C: "_DMAMOV_L", 0x8D: "_DMAMODE", 0x8E: "_BOOTINF",
    0x8F: "_ROMVER", 0x90: "_G_CLR_ON", 0x91: "_G_MOD ?", 0x92: "_PRIORITY ?", 0x93: "_CRTMOD2 ?",
    0x94: "_GPALET", 0xAC: "_SYS_STAT", 0xAD: "_B_CONMOD", 0xAE: "_OS_CURON", 0xAF: "_OS_CUROF",
    0xB0: "_DRAWMODE", 0xB1: "_APAGE", 0xB2: "_VPAGE", 0xB3: "_HOME", 0xB4: "_WINDOW", 0xB5: "_WIPE",
    0xB6: "_PSET", 0xB7: "_POINT", 0xB8: "_LINE", 0xB9: "_BOX", 0xBA: "_FILL", 0xBB: "_CIRCLE",
    0xBC: "_PAINT", 0xBD: "_SYMBOL", 0xBE: "_GETGRM", 0xBF: "_PUTGRM", 0xC0: "_SP_INIT",
    0xC1: "_SP_ON", 0xC2: "_SP_OFF", 0xC3: "_SP_CGCLR", 0xC4: "_SP_DEFCG", 0xC5: "_SP_GTPCG",
    0xC6: "_SP_REGST", 0xC7: "_SP_REGGT", 0xC8: "_BGSCRLST", 0xC9: "_BGSCRLGT", 0xCA: "_BGCTRLST",
    0xCB: "_BGCTRLGT", 0xCC: "_BGTEXTCL", 0xCD: "_BGTEXTST", 0xCE: "_BGTEXTGT", 0xCF: "_SPALET",
    0xFD: "_ABORTRST", 0xFE: "_IPLERR", 0xFF: "_ABORTJOB",
}

FEFUNC = {
    0xFE00: "__LMUL", 0xFE01: "__LDIV", 0xFE02: "__LMOD", 0xFE04: "__UMUL", 0xFE05: "__UDIV",
    0xFE06: "__UMOD", 0xFE08: "__IMUL", 0xFE09: "__IDIV", 0xFE0C: "__RANDOMIZE", 0xFE0D: "__SRAND",
    0xFE0E: "__RAND", 0xFE1A: "__LTOD", 0xFE1B: "__DTOL", 0xFE1C: "__LTOF", 0xFE1D: "__FTOL",
    0xFE1E: "__FTOD", 0xFE1F: "__DTOF", 0xFE20: "__VAL", 0xFE21: "__USING", 0xFE22: "__STOD",
    0xFE23: "__DTOS", 0xFE24: "__ECVT", 0xFE25: "__FCVT", 0xFE26: "__GCVT", 0xFE28: "__DTST",
    0xFE29: "__DCMP", 0xFE2A: "__DNEG", 0xFE2B: "__DADD", 0xFE2C: "__DSUB", 0xFE2D: "__DMUL",
    0xFE2E: "__DDIV", 0xFE2F: "__DMOD", 0xFE30: "__DABS", 0xFE36: "__SIN", 0xFE37: "__COS",
    0xFE38: "__TAN", 0xFE39: "__ATAN", 0xFE3A: "__LOG", 0xFE3B: "__EXP", 0xFE3C: "__SQR",
    0xFE3D: "__PI", 0xFE40: "__RND ?", 0xFEE0: "__CLMUL ?", 0xFEE1: "__CLDIV ?",
    0xFEEC: "__CDCMP ?", 0xFEED: "__CDADD ?", 0xFEEE: "__CDSUB ?", 0xFEEF: "__CDMUL ?",
    0xFEF0: "__CDDIV ?", 0xFEF1: "__CDMOD ?",
}

# (start, end inclusive, device) for grouping I/O addresses
DEVICES = [
    (0xC00000, 0xDFFFFF, "Graphic VRAM"),
    (0xE00000, 0xE7FFFF, "Text VRAM (4 planes x $20000)"),
    (0xE80000, 0xE81FFF, "CRTC"),
    (0xE82000, 0xE83FFF, "Video controller"),
    (0xE84000, 0xE85FFF, "DMAC"),
    (0xE86000, 0xE87FFF, "Area set"),
    (0xE88000, 0xE89FFF, "MFP MC68901"),
    (0xE8A000, 0xE8BFFF, "RTC"),
    (0xE8E000, 0xE8FFFF, "System port"),
    (0xE90000, 0xE91FFF, "OPM YM2151"),
    (0xE92000, 0xE93FFF, "ADPCM MSM6258"),
    (0xE94000, 0xE95FFF, "FDC"),
    (0xE96000, 0xE97FFF, "HDD"),
    (0xE9A000, 0xE9BFFF, "PPI i8255 (joystick, ADPCM rate/pan)"),
    (0xEB0000, 0xEB07FF, "Sprite registers (128 x 8 bytes)"),
    (0xEB0800, 0xEB7FFF, "BG/sprite control"),
    (0xEB8000, 0xEBBFFF, "PCG (sprite/BG patterns)"),
    (0xEBC000, 0xEBFFFF, "BG data pages 0/1"),
    (0xF00000, 0xFBFFFF, "CG ROM"),
    (0x000000, 0x0003FF, "68000 exception vectors"),
    (0x000400, 0x001FFF, "IOCS work area"),
]

_MFP = {1: "GPIP", 3: "AER", 5: "DDR", 7: "IERA", 9: "IERB", 0xB: "IPRA", 0xD: "IPRB", 0xF: "ISRA",
        0x11: "ISRB", 0x13: "IMRA", 0x15: "IMRB", 0x17: "VR", 0x19: "TACR", 0x1B: "TBCR",
        0x1D: "TCDCR", 0x1F: "TADR", 0x21: "TBDR", 0x23: "TCDR", 0x25: "TDDR", 0x27: "SCR",
        0x29: "UCR", 0x2B: "RSR", 0x2D: "TSR", 0x2F: "UDR"}
_CRTC = {0x00: "R00 H total", 0x02: "R01 H sync end", 0x04: "R02 H disp start",
         0x06: "R03 H disp end", 0x08: "R04 V total", 0x0A: "R05 V sync end",
         0x0C: "R06 V disp start", 0x0E: "R07 V disp end", 0x10: "R08 ext H adjust",
         0x12: "R09 raster IRQ line", 0x14: "R10 text X scroll", 0x16: "R11 text Y scroll",
         0x18: "R12 GR0 X", 0x1A: "R13 GR0 Y", 0x1C: "R14 GR1 X", 0x1E: "R15 GR1 Y",
         0x20: "R16 GR2 X", 0x22: "R17 GR2 Y", 0x24: "R18 GR3 X", 0x26: "R19 GR3 Y",
         0x28: "R20 memory/display mode", 0x29: "R20 low byte (status bits)",
         0x2A: "R21 text access control", 0x2C: "R22 raster copy", 0x2E: "R23 text mask"}
_BG = {0x800: "BG0 X scroll", 0x802: "BG0 Y scroll", 0x804: "BG1 X scroll", 0x806: "BG1 Y scroll",
       0x808: "BG control", 0x80A: "H total", 0x80C: "H disp", 0x80E: "V disp",
       0x810: "resolution"}
_VECTORS = {0x90: "trap #4 vector", 0xBC: "trap #15 vector", 0x118: "MFP V-DISP vector ($46)",
            0x138: "MFP CRTC raster vector ($4E)", 0x13C: "MFP H-SYNC vector ($4F)",
            0x110: "MFP Timer D vector ($44)", 0x134: "MFP Timer A vector ($4D)"}


def device(addr):
    for lo, hi, name in DEVICES:
        if lo <= addr <= hi:
            return name
    return "unknown"


TRAPS = {4: "MCDRV"}


def register(addr):
    """Register or area name for a hardware address, or '' if none applies."""
    if 0xC00000 <= addr <= 0xDFFFFF:
        return "GVRAM"
    if 0xE00000 <= addr <= 0xE7FFFF:
        return "text plane %d" % ((addr - 0xE00000) // 0x20000)
    if 0xEB8000 <= addr <= 0xEBBFFF:
        return "PCG patterns"
    if 0xEBC000 <= addr <= 0xEBDFFF:
        return "BG page 0"
    if 0xEBE000 <= addr <= 0xEBFFFF:
        return "BG page 1"
    if 0xE80000 <= addr <= 0xE8002F:
        return "CRTC " + _CRTC.get(addr - 0xE80000, "?")
    if addr == 0xE88000:
        return "MFP base (registers at odd addresses)"
    if 0xE88000 <= addr <= 0xE8802F:
        return "MFP " + _MFP.get(addr - 0xE88000, "?")
    if 0xE82000 <= addr <= 0xE821FF:
        return "graphic palette"
    if 0xE82200 <= addr <= 0xE8221F:
        return "text palette"
    if 0xE82220 <= addr <= 0xE823FF:
        return "sprite/BG palette %d, colour %d" % ((addr - 0xE82200) // 0x20, (addr & 0x1F) // 2)
    if addr == 0xE82400:
        return "VC R0 screen mode"
    if addr == 0xE82500:
        return "VC R1 priority"
    if addr == 0xE82600:
        return "VC R2 on/off"
    if addr == 0xE8E007:
        return "system port 4"
    if 0xEB0000 <= addr <= 0xEB03FF:
        n, r = divmod(addr - 0xEB0000, 8)
        return "sprite %d %s" % (n, ("X", "Y", "pattern/colour", "priority")[r // 2])
    if 0xEB0800 <= addr <= 0xEB0810:
        return _BG.get(addr - 0xEB0000, "?")
    if addr in _VECTORS:
        return _VECTORS[addr]
    return ""
