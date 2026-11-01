# Neo-Chorensha 2026-11-01 (5de0e05)

Neo-Chorensha is Chorensha v0.10, the 1995 X68000 shooter by Famibe No Yosshin, on the Neo Geo:
the original's own program runs on the Neo Geo's 68000, with its graphics, music and sound, two
players at once, WAVES (an endless one-player mode made of the original's own enemies and
bosses), and the ways of a coin-op cabinet (coins and credits, the attract demo). The
project page, with videos and screenshots:
https://continuearcade.com/neo-chorensha/

This repository is a patch: one command builds the game on your machine from your own copy of
the original. It holds none of the game (see "What is in the patch").

## What you need

- **Your own copy of the game:** the Chorensha v0.10 disk image, the X68000 `.dim` (SHA1
  `9eae93138254a277f87039ade791f35301dced93`), as it is or in a zip, whatever its name.
- **The X68000 system ROMs:** `iplrom.dat` (SHA1 `0ed038ed2133b9f78c6e37256807424e0d927560`, the
  IPL ROM MAME 0.289's `x68000` boots) and `cgrom.dat` (786,432 bytes), in a folder or a zip.
  `iplrom.dat` is found by its contents whatever its name, `cgrom.dat` by its name in any case;
  nothing else there is read.
- **MAME 0.289, exactly:** the build plays the original in MAME's X68000 to record its music, and
  checks the recording against the tested build's. Another version stops the build with a message.
  The build was tested on macOS on Apple silicon with Homebrew's MAME 0.289, and on Linux (Debian
  13, arm64) with MAME 0.289 built from its source with gcc 14: both recorded the music the same.
  MAME builds for other systems (x86-64 ones among them, not yet tried) may record it slightly
  differently; the build then cannot guarantee the tested game and stops with a message: please
  open an issue on this repository with it.
- **Python 3.12 or later**, with internet on the first run: `build.py` installs the Python
  packages `requirements.txt` pins into `.venv` beside it.
- **vasm** (`vasmm68k_mot`, its 68000 assembler, Motorola syntax) and **z80asm** (Bas
  Wijnen's), on PATH. The tested build used vasm 2.0f with its Motorola syntax module 3.19f
  (`vasmm68k_mot -v` shows yours) and z80asm 1.8 (`z80asm --version`). MAME, vasm and z80asm
  come from their authors' sites or your package manager.
- macOS or Linux (on Windows: in WSL2).
- **To play the game** (not to build it): a Neo Geo BIOS. In MAME, its `neogeo` set; on a MiSTer,
  the BIOS files the Neo Geo core's documentation lists.

None of the game, the X68000 ROMs or the Neo Geo BIOS is included here, linked to, or sent on
request.

## How to use it

```
python3 build.py --disk PATH --x68k-roms PATH [--mame PATH] [-o FOLDER]
```

`--disk` is the disk image or its zip, `--x68k-roms` the folder or zip holding the two ROMs,
`--mame` MAME (default: `$MAME`, else `mame` on PATH), `-o` the folder written (default
`neo-chorensha`). It takes a few minutes and writes:

- `neo-chorensha/marukodq.zip`: the game as a Neo Geo ROM set, under the name of MAME's
  `marukodq` (an existing Neo Geo set whose files fit the port's). Put it where MAME looks for
  ROMs, beside the Neo Geo BIOS set, in place of any `marukodq` you have (keep that one
  elsewhere), and run `marukodq`. MAME warns that the ROMs' checksums are wrong: they are the
  port's, that is expected.
- `neo-chorensha/neo-chorensha.neo`: the same game for the MiSTer Neo Geo core. Copy it into the
  core's games folder on the MiSTer's SD card (`games/NeoGeo/`, where its BIOS files go too) and
  load it from the core's menu.

Your files are only read. Every input is checked first, and a wrong or missing one is named (all
of them at once). The build replaces no file of yours: if the `-o` folder already holds a
`marukodq.zip` or a `neo-chorensha.neo` that is not this patch's own output (MAME's real
`marukodq` set, say), it stops before writing anything; choose another folder or move that file.
Every file written is checked against the SHA1 of the tested build's, so what you get is byte for
byte the game that was tested; a file that differs is renamed `NAME.mismatch` (not for play) and
the message says what made it (the assembler, say), to check.

The build needs MAME 0.289 exactly, and the ROM set it writes was played in MAME 0.289. The
`.neo` is built to the format the MiSTer core's loader reads, but it has not yet been run on a
MiSTer.

## What is in the patch

- the port's 68000 code and its Z80 sound driver, as source (`src/`);
- the build tools (`tools/`, Python) and the MAME scripts that record the music (`tests/x68k/`);
- facts about the program: addresses, the memory layout, sizes, SHA1s;
- the RAM census (`data/census.json`): which addresses the game uses;
- the attract demo's input stream (`data/demo.bin`): the pad bytes the port recorded playing
  itself;
- the side strips' art (`art/strips/strip.png`), ours.

None of the game. Where the build checks the original's instructions it checks SHA1s, and the
37 bytes that 9 of our edits to the program share with the original are copied from
your disk at build time; the edits' other 71 bytes are ours. The patch's data holds no 3 bytes
in a row of the original program, and its files quote none of the game's text.

## Legal

This is an unofficial, free, non-commercial fan project, not affiliated with or endorsed by
Famibe No Yosshin or any rights holder. Chorensha and its program, graphics, music and sound are
©1995 FAMIBE NO YOSSHIN, named here only to say which game the patch is for; the X68000 system
ROMs are Sharp's, the Neo Geo and its BIOS SNK's, MAME its developers'. The patch is not the game
and cannot run without it: it holds none of the game's program, graphics, music or sound and
none of the system ROMs (see above), and you need your own lawfully obtained copy of the
original. None are included here, none are linked to, and none are sent on request: please do
not ask. The patch's own code is under the MIT licence (LICENSE), which grants nothing for anyone
else's work. If you hold rights in Chorensha and object to this patch, write to
dev@continuearcade.com and it will be taken down.

## Contact

dev@continuearcade.com, or an issue on this repository. More about how the port was made, with
videos and screenshots: https://continuearcade.com/neo-chorensha/
