# Seam Ripper

A tabbed GUI front-end for the Naughty Bear modding toolkit. Tools are grouped
by category into tabs; each is a form where you click to pick a file or folder,
set options, and hit Run. A shared log panel at the bottom shows every command
and all output, and can be saved.

## Run

    pip install PySide6
    python SeamRipper.py

First time: open **Settings → Tool paths** and point it at your `luac51.exe`,
`unluac.jar`, and your build's `assets\lu` folder (for staging). They default
to files sitting next to the script. Paths are remembered in
`seamripper_settings.json`.

## Tabs

**Lua Code** — the main loop. Pick a `.lu`, click *List chunks*, double-click a
chunk to read it into the editor, edit the code, click *Ship*. Shipping injects
only the functions you changed and refuses ones the decompiler can't reproduce
(it tells you which). After a successful splice, Ship also runs a mandatory
container-integrity check (see **Verification** below) and refuses to write
the file if that fails too. Tick *use luadec* to try the luadec backend; tick
*stage into build* to copy the result into your `assets\lu` after shipping.

Two ways to edit without hand-writing changes yourself:
- **Find/replace** — plain or regex text substitution across the editor.
- **Batch edit calls…** — highlight one example call (e.g. one `AddFear(...)`
  line), tag each of its arguments anchor / target / ignore, pick a transform
  (scale / set / offset) for the targets, preview how many calls in the whole
  chunk match, apply. Marking a slot as a target also gates matching on its
  own example value by default (so "these five numbers" doesn't accidentally
  catch every other call that merely shares the same function and a
  different-purpose argument) — this is adjustable per slot if you want to
  target a value regardless of what it currently is.

**Text / Localization** — subtitle/string editing: extract strings, apply edits,
spelling report/fix, grep, raw repack.

**Assets** — container info, decompress, extract chunks, texture/mesh convert,
sound bank/stream extraction.

**Panic in Paradise** — the PiP dumper.

## How it works

The GUI never reimplements a tool. Every Run shells out to the existing `.py`
script with the same Python, so the tested command-line logic stays
authoritative and the GUI is just a launcher plus a log. If a command works in
the terminal, it works here, and vice-versa.

## Verification

Every Ship is checked two ways before the file is accepted, both mandatory,
neither skippable:
- **Structural** — record table stays 16-byte aligned, alignment gaps stay
  0xBF-filled, compression frame headers and the stream terminator match
  retail convention. Pure Python, no external dependency.
- **Independent decode** — each rebuilt segment is decoded by a *separate*
  LZX implementation (`lzxverify`/`lzxverify.exe`, built from libmspack, not
  this toolkit's own decoder) and compared byte-for-byte against the
  container's declared image. This exists because a decoder written by the
  same author as the encoder can share its bugs; an independent one can't.

Either failing deletes the just-written output and Ship exits nonzero with
the specific reason. Run the same check on any `.lu` on disk, without
shipping anything, with:

    python tools/nblua.py verify path\to\file.lu

`lzxverify`/`lzxverify.exe` must be built and present next to the scripts —
see `tools/lzxverify_src/build.sh` (source is libmspack, LGPL 2.1; full licensing
notice in `tools/lzxverify_src/NOTICE.md`, license text in
`tools/lzxverify_src/COPYING.LIB`). Without it, Ship refuses everything; there's
no reduced-checking fallback mode.

## Tests

    python tests/run_all.py

Stdlib `unittest`, no extra dependencies. All fixtures are synthetic (hand-
built Lua snippets and hand-built container layouts), nothing decompiled
from the actual game ships with the toolkit or its tests. The independent-
decode tests skip themselves if `lzxverify` isn't built yet for the current
platform, rather than failing the run.

## Notes

- One task runs at a time; the log shows start, output, and exit code.
- The Lua editor writes to a temp `_sr_edit.lua` next to the script; Ship reads
  from the editor pane, so just edit and click Ship.
- "Refused" on Ship is the safety net, not a bug: you edited a function the
  decompiler couldn't reproduce faithfully. Leave it, or retry with *use luadec*.

## Install

`SeamRipper.py` (the GUI entry point) and the branding/build files
(`seamripper.spec`, `build_exe.bat`, icons) sit at the repo root. Every tool
script and bundled third-party binary (`nblua.py`, `naughty_lu.py`,
`luac51.exe`, `unluac.jar`, `lzxverify`, etc.) lives in `tools/` alongside it.
Keep that pairing intact, `SeamRipper.py` resolves everything else relative
to its own location plus `tools/`, both when run from source and in a built
EXE.
