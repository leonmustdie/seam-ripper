# Technical notes

The details behind Seam Ripper, for anyone who wants to know how it works or
hit something the main README doesn't cover.

## Requirements (running from source)

| What | Needed for | Notes |
|---|---|---|
| PySide6 | the GUI | the command-line tools only need the standard library |
| Pillow | PNG textures, textures inside GLB | without it you still get DDS |
| numpy | rigged character GLB export (`lu_rig.py`) | only that tool needs it |
| Java 8+ | the `unluac.jar` fallback decompiler | only if you pick unluac by hand |

The release EXE bundles Python, PySide6 and Pillow.

## Editing NB1 scripts

Ship compares your edit with the original, recompiles only the functions you
changed, and puts them back into the container. Every other function keeps the
game's original bytes. If you edited a function the decompiler can't reproduce
exactly, Ship refuses and names it, rather than risk breaking the script.

### The decompiler

Leave the decompiler on **auto**. It uses nbdec (`tools/nbdec.py`), written
for this game's scripts. On the six retail NB1 containers tested, every
function (2220 of 2220) recompiles to the original bytes. If nbdec declines a
chunk, auto falls back to luadec and unluac, runs both, and keeps whichever
recompiles closer to the original.

The first line of a decompiled script records which decompiler made it, and
Ship reads it back so it compares against the same baseline. Keep that line.

### Hashed names

Names the game stores as hashes show like this:
`if message.mSoundName == --[[HASH:"DetectThreat"]]0x4342e44f then`.
Hashes without a known name stay as plain hex.

To use a different hashed name, write `HASH("CSmoke02")`. Ship turns it into
the hash before compiling and lists each one in the log. This works in both
games. Editing the name inside a `--[[HASH:"..."]]` comment does nothing.

Local variable and parameter names are made up by the decompiler from how they
are used, and you can rename them freely. Global names, field names and strings
are real, and changing them changes behaviour.

### Numbers

`20` is NB1's integer type and `20.0` is a decimal. Ship follows the same rule
for numbers you add. One catch: a function stores each number once, so if it
already uses `0` and you add `0.0` (or the other way round), both get the same
type. Ship prints a `note: line N` when that happens. Use `nil` where the game
has a default, or pick a value the function doesn't already use.

### Scripts in several containers

Many scripts are compiled into several `.lu` files, and the game runs only one
copy, in practice the one in the first container it loads. The bear state
machine `basenpcbodystatemachine` is in 13 containers: an edit shipped only to
`normalbear.lu` did nothing in-game, and the same edit shipped to all 13
worked. Ship lists the other containers and ships to the identical copies
(`--all-in <folder>` on the command line).

## Patches

A `.srpatch` is a zip with a `manifest.json`. Each script edit is stored as
the changed lines plus fingerprints of the lines around them, so it can still
be placed if the recipient's copy has other edits. Text edits store only the
changed strings. Patches are always made against the retail file, even after
you've shipped into it. When applying, Seam Ripper rebuilds the file from the
recipient's own copy, verifies it, backs up the original and writes the
result. Each patch records the Seam Ripper version that made it.

## Backups

Before overwriting a game file, Seam Ripper keeps the original and the last
10 versions in a `.seamripper\backups` folder next to it. Read-only files are
never overwritten.

## Panic in Paradise

PiP uses a new container format (`LUH`, magic `05 4C 55 48`) alongside reused
NB1 containers. `naughty_lu.py` detects both, so every tool reads PiP files.
The LUH image is XMemCompress LZX in 1 MB segments. The 360's XMemCompress
differs from CAB LZX in one place (no pad byte after odd-length uncompressed
blocks), and the decoder handles it.

`pip_dump.py` dumps a unit's raw chunks with a manifest, textures as PNG,
skeleton reports, rigged character GLBs and prop models, the Lua source with
its original folder tree, `.cu` audio manifests, and the Scaleform UI movies
as `.gfx` (open them in JPEXS).

**Text** lives in per-language units (`global.en_us.lu`, ...) as type
`04d00013` string tables (UTF-16BE, keyed by CRC32). `lu_strings.py extract`
writes one `HASH<TAB>text` line per string, and `apply` rebuilds the container
from your edited file, including length changes. Rebuilt containers store
segments uncompressed (compressed size equal to uncompressed size), which the
engine accepts; files get bigger but load the same.

**UI**: `pip_gfx.py` pulls the Scaleform movies out of `04d00001` chunks as
`.gfx`, plus every texture they embed as PNG. The art is in the PNGs; the
`.gfx` files are mostly layout and ActionScript.

**Scripts** are plain Lua 5.1 source in `04b00000` chunks. Two rules decide
whether an edited script boots or hangs:

1. **It has to fit the original slot.** Each chunk has a fixed span in the
   image. Units like `global.lu` hang if a chunk grows past it and moves, even
   if its content is unchanged. The injector squeezes out whitespace to make an
   edit fit and refuses with a byte count if it still doesn't. It also checks
   for unbalanced brackets and unterminated strings or comments first. Don't
   shrink a file by stripping comments or reindenting: a reflowed data table
   can hang the game even though it parses.
2. **Stay inside the game's own data.** Data tables have a fixed set of keys
   and an expected range. Adding a key the game doesn't use (like
   `Bonus = {rr=...}`) hangs the loader, and so does a value far out of range:
   costume `hp` works at 400, the game's highest, but hangs at 30000. Check
   what the real data uses and stay inside it.

## Output formats

Extracting is two steps: `naughty_lu.py extract` dumps each record as a raw
`.bin`, and `lu_convert.py` turns those into usable files. If you only ran the
first step, you only have `.bin` files.

* **Textures** (`14200007`): always `.dds` (DXT1/3/5, untiled, base mip), plus
  `.png` if Pillow is installed.
* **Meshes** (`04000007`): `.obj` + `.mtl`, and `.glb` with the textures
  embedded (needs Pillow for textures). `--no-glb` or *OBJ only* skips the GLB.
  Up-axis varies by asset, so rotate as needed. OBJ UVs are flipped to OBJ's
  bottom-left origin; GLB keeps the top-left origin glTF expects.
* **Sounds**: banks and XMA streams via `lu_sound.py`.

## File formats

**`.lu` containers** are not Lua bytecode. They are big-endian resource
containers: a header, a record table, and a data image stored raw or as
XMemCompress LZX pools. Script records hold Lua 5.1 bytecode compiled
big-endian for the 360.

**Record layout.** Each record starts at the first multiple of its own
alignment after the previous one ends, and the gap is filled with `0xBF`. The
alignment is in the top byte of the record's flags as a power of two (`0x4` =
16 for scripts and most records, `0xb` = 2048, `0xc` = 4096 for textures and
mesh buffers). The engine relies on this, so a container with any other gap
opens fine in every tool but crashes the game at level setup. Seam Ripper
re-lays out every record after an edited one by this rule, and doing that to
unchanged records reproduces the retail files exactly.

**Textures** carry size, mip count and a Xenos format dword (low 6 bits:
`0x12` DXT1, `0x13` DXT3, `0x14` DXT5). Pixel data is 16-bit byteswapped and
2D-tiled, with surfaces padded to 32x32 blocks.

**Meshes** have per-submesh descriptors pointing at 4 KB-aligned vertex and
index buffers. Vertices are big-endian with float3 positions and half-float
UVs; stride and UV offset are detected per submesh. Indices are 16-bit
triangle strips with `0xFFFF` restart, or lists where the trailer says so.
Submeshes reference their textures by CRC32 hash pairs, which is how materials
get bound.

## More troubleshooting

**Ship refused a function.** The decompiler couldn't reproduce it exactly.
Leave it unedited, or try another decompiler in *Settings → Advanced*.

**DDS but no PNG.** Pillow isn't installed in the Python running the tools.
The EXE has it.

**`unsupported Xenos format`.** The converter doesn't decode that texture
format yet; the raw data is saved as `.texdata.bin`. Open an issue with the
format dword from the message.

**`layout detection failed; skipping submesh`.** That submesh's vertex layout
couldn't be worked out. The rest of the mesh still converts. Issues with the
`.bin` attached are welcome.
