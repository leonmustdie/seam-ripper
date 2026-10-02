---
title: File formats and PiP internals
parent: Game reference
nav_order: 3
---

# File formats and PiP internals

How the games' files are put together. This is about the files, not the tool:
for how Seam Ripper edits them see [How Seam Ripper works](technical.md).

## Container formats

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
