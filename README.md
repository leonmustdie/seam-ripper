# Seam Ripper

![Seam Ripper](seamrpr.png)

A modding toolkit for the Xbox 360 **Naughty Bear** games:

* **Naughty Bear** (Gold Edition data validated)
* **Naughty Bear: Panic in Paradise**

Seam Ripper reads and writes the games' `.lu` resource containers end to end: decompile and edit the embedded Lua 5.1 gameplay scripts and inject them back, extract and edit subtitle/localization text, convert textures to DDS/PNG and meshes to OBJ and GLB, pull sound banks and streams, and bulk-dump Panic in Paradise data.

It ships as a tabbed GUI (`SeamRipper.exe` or `SeamRipper.py`) built on top of a set of standalone command-line tools. The GUI never reimplements anything: every button shells out to the same scripts you can run yourself, so anything that works in the terminal works in the GUI and vice versa.

> These tools operate on files you dump from your own legally owned copies of the games. No game assets, scripts, or code are included in this repository.

An updated version of the tools seen from [my original .lu decompilation and documentation](https://github.com/leonmustdie/lu-documentation), for the usage of modification for the Naughty Bear Games on PC. The [original documentation GitHub repo](https://github.com/leonmustdie/lu-documentation) will no longer have the original tools, as they didn't work as well and their upgraded versions make them obsolete.

---

## Getting it

**Release build (no Python needed):** download the latest release zip, extract it anywhere, run `SeamRipper.exe`. The tool scripts (now in `tools/`), `luac51.exe`, `luadec.exe`, and `unluac.jar` are bundled inside the folder.

**From source:**

```
pip install PySide6 pillow
python SeamRipper.py
```

Every tool also runs standalone from the repo root, e.g. `python tools/nblua.py list game.lu`.

### Requirements

| What | Needed for | Notes |
|---|---|---|
| Java (JRE 8+) | Lua decompilation via `unluac.jar` | must be on PATH; the `luadec` backend does not need it |
| Pillow (`pip install pillow`) | PNG texture output, textures embedded in GLB | without it you still get DDS |
| numpy (`pip install numpy`) | Rigged character GLB export (`lu_rig.py`) | bind-pose matrix math; without it that one tool fails to import |
| PySide6 | the GUI only | CLI tools are stdlib-only |

The release EXE bundles Python, PySide6, and Pillow; you still need Java installed for the unluac backend.

---

## The GUI

Four tabs, one shared log panel at the bottom. Every run prints the exact command line it executed, so you can reproduce anything in a terminal. One task runs at a time.

First run: open **Settings -> Tool paths** if you keep `luac51.exe`/`unluac.jar` somewhere unusual, and optionally point *Build assets\lu* at your build's staging folder. Paths persist in `seamripper_settings.json` next to the EXE.

### Lua Code

The main modding loop.

1. Pick a `.lu` file and click **List chunks**. Every embedded Lua script chunk appears in the list.
2. Double-click a chunk to decompile it into the editor. Each function is tagged `FAITHFUL` or `DIVERGENT` as a hint of how well the decompiler round-trips it.
3. Edit function **bodies** (leave signatures alone) and click **Ship**.

Ship diffs your edit against the original, recompiles **only the functions you actually changed**, splices them into the container, and keeps every other function's original game bytes untouched. If you edited a function the decompiler cannot reproduce faithfully, Ship **refuses and names it**: that is the safety net, not a bug. Leave that function alone or retry with the *use luadec* backend, which decompiles more functions cleanly.

Tick *stage into build* to copy the shipped `.lu` straight into your build's `assets\lu`.

### Text / Localization

* **Extract strings**: dump a `.lu`'s subtitle/localization strings to an editable text file.
* **Apply strings**: write the edited text back (raw, codec 0), with optional round-trip verification.
* **Spelling report / fix**: scan for spelling and spacing candidates across files; report is review-only, fix writes corrected copies.
* **Grep text**: search localization text across many `.lu` files, plain or regex, case-insensitive optional.
* **Repack raw**: low-level reassembly of a container from a raw edited image.

### Assets

* **Container info**: header and record-table details for `.lu` files.
* **Decompress image**: write a container's raw (decompressed) data image out as `.bin`.
* **Extract chunks**: dump every resource record from `.lu` files into an output tree, sorted by type.
* **Convert textures/meshes**: run `lu_convert.py` on extracted chunks (see [Output formats](#output-formats)).
* **Sound: bank / streams**: extract sound banks and XMA streams.

### Panic in Paradise

One-button bulk dump of everything decodable from PiP `.lu`/`.cu` files. PiP ships a new container format (`LUH`, magic `05 4C 55 48`) alongside reused NB1 archives; `naughty_lu.py` auto-detects both, so every tool in the kit reads PiP files natively. The LUH image is XMemCompress LZX in 1 MB segments; note that the 360's XMemCompress deviates from CAB LZX in one place (no pad byte after odd-length uncompressed blocks), which this decoder implements — including for the Scaleform-heavy front-end units that carry large stores of incompressible Flash data.

`pip_dump.py` produces per unit: raw chunks with a manifest, textures as PNG, skeleton reports, rigged character GLBs and rigid prop models (PiP's `34000007` mesh chunk shares NB1's inner container), plaintext Lua source scripts with the original tree rebuilt, `.cu` audio manifests, and the Scaleform UI movies as `.gfx` files (sliced from `04d00001` chunks; open them in JPEXS for UI edits).

**PiP localization** lives in per-language units (`global.en_us.lu`, `global.fr_fr.lu`, ...) as type `04d00013` string tables (UTF-16BE, keyed by CRC32 hash). `lu_strings.py` auto-detects them: `extract` writes one `HASH<TAB>text` line per string (1,841 per language in the retail units) and `apply` rebuilds the whole container from your edited file, handling length changes. Rebuilt containers use raw passthrough segments (compressed size == uncompressed size, the engine's memcpy convention for incompressible data) — **verified in-game on retail hardware**: edited strings display correctly. Files grow since nothing is recompressed, but load and behave identically. Note the engine rejects segments whose stored size exceeds the uncompressed size, so the writer always uses raw mode.

**PiP UI flash**: `pip_gfx.py` extracts the Scaleform movies from `04d00001` chunks as `.gfx` plus every texture they embed as PNG (the images are standard little-endian DDS packed after each movie with a name table; the movie references them by filename via GFx tag 1009). `pip_dump.py` runs this automatically. The `.gfx` shells themselves are mostly vector layout and actionscript — the art is all in the PNGs.

**PiP Lua script injection**: PiP ships its gameplay logic as plaintext Lua 5.1 source inside `04b00000` chunks. `pip_scripts.py extract` pulls the tree out; `pip_scripts.py inject <orig.lu> <edited .lua...> -o out.lu` writes edited source back, matching each file to its chunk by embedded source path, fixing the chunk's offset table, and rebuilding the container. Verified in-game on retail hardware across three independent data types (weapon damage, costume stats, and a hardcoded HP cap constant).

Two rules make the difference between an edit that boots and one that hangs, both learned the hard way:

1. **Edits must fit their original slot.** Each chunk occupies a fixed span in the image (its size plus trailing padding to the next chunk). global.lu and other offset-referencing units hang at boot if a chunk grows past its slot and gets relocated — even a byte-for-byte-identical chunk that merely *moved* will hang. The injector enforces this: it reclaims whitespace to make an edit fit, prints a note when it does, and refuses with a byte count rather than shipping a relocated or heavily-reflowed chunk. It also runs a dependency-free Lua structure check first (unbalanced brackets, unterminated strings/comments — the fat-finger errors that hang the game silently) and refuses unless you pass `--force`; a valid edit passes untouched (zero false positives across the retail script set). Keep edits at or below the original size and this never bites. (Do **not** rely on comment-stripping or reindenting to shrink a file — a heavily-reflowed data table hangs the game at load even though it re-parses fine. Reclaim only whitespace, or trim the edit itself.)

2. **Injected values must respect the data table's implicit schema.** Game data tables have an unwritten contract: a fixed set of valid keys and an expected value range. Inventing a key (e.g. a `Bonus = {rr=...}` when the real resistance keys are `mr`/`hr`) hangs the loader. So does a value far outside the game's own range — costume `hp` works at the game's real ceiling of 400 but hangs at 30000, because something downstream (a UI bar, a fixed-width field) assumed a bound. Survey the real data (`grep` the extracted scripts for the keys and their observed min/max) and stay inside it. "Bigger number" is not free.

---

## Output formats

Extraction is a two-step pipeline: `naughty_lu.py extract` dumps each resource record as a raw `.bin` chunk, and `lu_convert.py` converts those chunks into usable formats. The GUI's *Extract chunks* and *Convert textures/meshes* forms map to those two steps. If you only ran the extract step, you only have `.bin` files; run the convert step on the extract output folder to get images and models.

**Textures** (chunk type `14200007`) convert to:

* `.dds`: always. DXT1/DXT3/DXT5, un-byteswapped and untiled from the console's Xenos 2D tiling, base mip level.
* `.png`: additionally, when Pillow is installed.

**Meshes** (chunk type `04000007`) convert to:

* `.obj` + `.mtl`: UV-mapped submeshes with materials bound to the converted textures via each submesh's texture references.
* `.glb`: binary glTF 2.0, one primitive per submesh, **textures embedded** in the file (PNG, so Pillow is required for textured GLBs; without it the GLB still exports with untextured grey materials). Drops straight into Blender, three.js, or any glTF viewer with no sidecar files. Pass `--no-glb` (or tick *OBJ only* in the GUI) to skip it.

Up-axis varies by asset (characters are Y-up, some props Z-up); rotate in your DCC as needed. UVs in the OBJ are flipped to OBJ's bottom-left origin; the GLB keeps the source's top-left origin, which is what glTF expects.

**Sounds** extract to banks and XMA streams via `lu_sound.py`.

---

## Command-line reference

Every tool prints full usage with `--help`. From source, scripts live in `tools/` (`python tools/nblua.py --help`). In a release build, run tools through the EXE: `SeamRipper.exe --tool <script.py> <args>` — the bundle stays flat internally regardless of the repo's `tools/` layout, so this invocation is unchanged.

### Primary tools

| Tool | Purpose |
|---|---|
| `nblua.py` | one-stop Lua editing: `list` chunks, `read` one to editable Lua, `ship` edits back with per-function faithfulness checking and optional `--stage` |
| `naughty_lu.py` | container level: `info`, `decompress`, `extract` (records to `.bin` tree) |
| `lu_convert.py` | extracted chunks to DDS/PNG textures and OBJ/MTL/GLB meshes |
| `lu_strings.py` | `extract` / `apply` localization strings |
| `lu_autofix.py` | spelling/spacing `report` and `fix` across containers |
| `lu_grep.py` | search localization text across files |
| `lu_sound.py` | `bank` / `streams` sound extraction |
| `lu_repack.py` | raw image repack with verification |
| `pip_dump.py` | bulk Panic in Paradise dumper |
| `pip_gfx.py` | PiP Scaleform UI movie + texture extractor |
| `pip_scripts.py` | `extract` / `inject` PiP plaintext Lua source |

### Pipeline internals

These are the building blocks the primary tools compose; they are useful on their own for debugging the pipeline.

| Tool | Purpose |
|---|---|
| `lua_decompile.py` / `lua_recompile.py` | X360 big-endian Lua 5.1 bytecode to source and back |
| `lua_chunk_swap.py` / `lu_chunk_replace.py` | splice recompiled chunks into containers |
| `lua_clean.py` / `lua_annotate.py` / `lua_readable.py` / `lua_readall.py` | readability passes and bulk decompilation |
| `nb_read.py` / `nb_decompile.py` / `nb_inject.py` / `nb_ship.py` / `nb_apply.py` | the read/ship pipeline stages `nblua.py` wraps |
| `proto360.py`, `bccmp.py`, `rename_luadec.py`, `widen_sizet.py` | bytecode helpers: prototype handling, bytecode comparison, luadec symbol renaming, size_t widening |

### Bundled third-party binaries

* `luac51.exe`: Lua 5.1 compiler (MIT, from the Lua project).
* `unluac.jar`: Lua 5.1 decompiler by tehtmi.
* `luadec.exe`: alternative decompiler backend (luadec project).
* `lzxverify` / `lzxverify.exe`: independent LZX decoder used to verify every
  rebuilt container, built from [libmspack](https://github.com/kyz/libmspack)
  (LGPL 2.1) by Stuart Caie and contributors. Source, license text, and build
  instructions are bundled in `tools/lzxverify_src/`; full notice in
  `tools/lzxverify_src/NOTICE.md`.

---

## Format notes

Short version; the tool docstrings carry the full details.

**`.lu` containers** are not Lua bytecode. They are big-endian A2M engine resource containers: a self-describing header, a resource record table, and a data image stored either raw or as XMemCompress LZX (X360 XCompress) pools. Script chunks inside carry standard Lua 5.1 bytecode compiled big-endian for the Xenon CPU.

**Texture chunks** carry dimensions, mip count, and a Xenos format dword in the header (low 6 bits: `0x12` DXT1, `0x13` DXT3, `0x14` DXT5); pixel data is u16-byteswapped and 2D-tiled (XGAddress2DTiledOffset, surfaces padded to 32x32 blocks).

**Mesh chunks** hold per-submesh descriptor blocks referencing 4 KB-aligned vertex/index buffers. Vertices are big-endian with float3 positions and half-float UV pairs; stride and UV offset vary per submesh and are auto-detected (minimal-edge-length scoring for stride, range analysis for UVs, with X360 vertex declarations used when present). Index buffers are 16-bit big-endian triangle strips with `0xFFFF` primitive restart, or triangle lists where the trailer says so. Descriptors also reference the submesh's textures as CRC32 hash pairs, which is how materials get bound.

---

## Building the EXE

On Windows, from the toolkit folder:

```
build_exe.bat
```

That installs PyInstaller/PySide6/Pillow and builds `dist\SeamRipper\SeamRipper.exe` from `seamripper.spec`. Zip the `dist\SeamRipper` folder for distribution. The build uses `seamripper.ico` (a multi-resolution 16–256 px icon) for the EXE and taskbar; the running window loads `seamripper_256.png` as its title-bar icon. To reskin, replace those files (an `.ico` with the standard sizes and a square PNG) and rebuild.

It is a **one-folder** build on purpose. The GUI launches every tool as a subprocess of its own EXE (`SeamRipper.exe --tool <script> ...`); a one-file build would re-extract the entire bundle on every tool run. The tool `.py` files ship as plain data inside the folder, byte-identical to this repo, and are executed by the shim at the top of `SeamRipper.py`.

For a debug build with a console window, flip `console=True` in the spec.

---

## Troubleshooting

**Ship refused a function.** The decompiler could not reproduce that function byte-faithfully, so injecting your edit of it would risk corrupting behavior elsewhere in the chunk. Retry with *use luadec*, or leave that function unedited; everything else you changed still ships.

**Textures came out as `.bin`, not images.** You ran the extract step but not the convert step. Point *Convert textures/meshes* (or `lu_convert.py`) at the extract output folder.

**DDS but no PNG.** Pillow is not installed in the Python you are running the tools with (`pip install pillow`). The release EXE has it bundled.

**`unsupported Xenos format` on a texture.** That chunk uses a format the converter does not decode yet; the raw pixel data is dumped as `.texdata.bin` so nothing is lost. Open an issue with the format dword from the message.

**`layout detection failed; skipping submesh`.** The vertex layout auto-detection could not find a plausible stride/offset for that submesh. The rest of the mesh still converts. Issues with the source `.bin` attached are welcome.

**Tool output looks garbled or a run hangs.** Check the log panel for the exact command and run it in a terminal; the GUI and CLI are the same code paths.

---

## Legal

Seam Ripper is a fan-made research and modding tool. It contains no assets,
scripts, or code from any Naughty Bear game. Use it only with data dumped
from copies of the games you own. *Naughty Bear* and *Naughty Bear: Panic in
Paradise* were developed by Artificial Mind and Movement / Behaviour
Interactive and published by 505 Games; all rights to the games belong to
their respective owners. This project is not affiliated with or endorsed by
them. 

Icon, description image, and all .SVG assets currently used for the icon are 
created by [Mallorie](https://github.com/unixfunnies).
