---
title: How Seam Ripper works
parent: Seam Ripper reference
nav_order: 1
---

# How Seam Ripper works

The tool's own behaviour: how Ship rewrites a script, what the decompiler does,
what the output files are. For what is *inside* the game files, see
[File formats and PiP internals](game-files.md).

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
