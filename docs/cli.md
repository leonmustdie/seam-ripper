---
title: Command-line tools
parent: Seam Ripper reference
nav_order: 3
---

# Command-line tools

Everything the GUI does runs through these scripts, and the GUI's Log tab
shows the exact command for every action. Each tool prints its usage with
`--help`.

From source, the scripts are in `tools/`: `python tools/lu_lua.py --help`.
With the release build, run them through the EXE:
`SeamRipper.exe --tool lu_lua.py --help`.

## Main tools

| Tool | What it does |
|---|---|
| `lu_lua.py` | Scripts in either game: `list`, `read`, `ship`, `export`, `where`. `export` writes every script to a folder plus an `INDEX.txt` of which containers have each one |
| `sr_patch.py` | `make`, `info` and `apply` `.srpatch` patches |
| `nblua.py` | The NB1 side of `lu_lua.py`, with `--backend` to pick a decompiler |
| `nbdec.py` | The NB1 decompiler. `nbdec_bench.py` measures it |
| `nb_reconstruct.py` | Recovers hashed names from the patterns they follow; only exact hash matches are kept |
| `lua_repair.py` | Makes luadec output parse as Lua 5.1 again |
| `naughty_lu.py` | Containers: `info`, `decompress`, `extract` |
| `lu_convert.py` | Extracted chunks to DDS/PNG and OBJ/GLB |
| `lu_strings.py` | `extract` and `apply` game text. A `+HASH` line in the strings file adds a new string |
| `lu_autofix.py` | Spelling and spacing `report` and `fix` |
| `lu_grep.py` | Search game text across files |
| `lu_sound.py` | `bank` and `streams` sound extraction |
| `lu_repack.py` | Repack a raw image, with verification |
| `pip_dump.py` | Dump everything from PiP units |
| `pip_gfx.py` | PiP UI movies and their textures |
| `pip_scripts.py` | `extract` and `inject` PiP Lua source |
| `xiso_extract.py` | `list` and `extract` the files on an Xbox 360 disc image |

## Building blocks

Used by the tools above; handy for debugging.

| Tool | What it does |
|---|---|
| `lua_decompile.py`, `lua_recompile.py` | 360 Lua 5.1 bytecode to source and back |
| `lua_chunk_swap.py`, `lu_chunk_replace.py` | Put recompiled chunks into containers |
| `lua_clean.py`, `lua_annotate.py`, `lua_readable.py`, `lua_readall.py` | Readability passes and bulk decompiling |
| `nb_read.py`, `nb_decompile.py`, `nb_inject.py`, `nb_ship.py`, `nb_apply.py` | The stages behind `nblua.py` |
| `proto360.py`, `bccmp.py`, `rename_luadec.py`, `widen_sizet.py` | Bytecode helpers |
| `verify_lzx.py` | Checks every rebuilt container before it's written |

## Bundled third-party tools

* `luac51.exe`: Lua 5.1 compiler (MIT, from the Lua project).
* `unluac.jar`: Lua 5.1 decompiler by tehtmi.
* `luadec.exe`: decompiler from the luadec project.
* `lzxverify.exe`: independent LZX decoder used to check every rebuilt
  container, built from [libmspack](https://github.com/kyz/libmspack)
  (LGPL 2.1) by Stuart Caie and contributors. Source, license and build steps
  are in `tools/lzxverify_src/`, with the full notice in
  `tools/lzxverify_src/NOTICE.md`.

## Building the EXE

On Windows, from the repo folder:

```
build_exe.bat
```

This installs PyInstaller, PySide6 and Pillow and builds
`dist\SeamRipper\SeamRipper.exe`. Zip the `dist\SeamRipper` folder to release
it. The EXE icon is `seamripper.ico` and the window icon is
`seamripper_256.png`.

It's a one-folder build on purpose: the GUI runs every tool as
`SeamRipper.exe --tool <script>`, and a one-file build would unpack itself
again on every run. For a build with a console window, set `console=True` in
`seamripper.spec`.
