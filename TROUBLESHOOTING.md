# Troubleshooting / contingency playbook

Symptom-first. Find what you're seeing, do what it says. Written after
the `tools/` reorg shipped a real bug in v1.0.0 (`load_settings()`
expected a `tools/` subfolder inside the frozen bundle that the spec
never puts there), so several entries below are that incident
generalized, not hypothetical.

## "could not run luac at '...'" / same for unluac / same for luadec

**Means:** `SeamRipper.py` (or whoever's calling `nblua.py`) handed a
path that doesn't resolve on this machine.

**Check, in order:**
1. Is the file actually where the error says? Open the folder, look.
2. Frozen build → should be flat next to `SeamRipper.exe`
   (`_internal\luac51.exe`), never `_internal\tools\...`. If you see
   `tools` in a frozen-build error path, that's this exact bug back
   again, something reintroduced an unguarded `BUNDLE / "tools"` outside
   `_bundled()`. Grep `SeamRipper.py` for `BUNDLE /` and check every hit
   goes through `_bundled()` or is inside `tool_argv`'s existing
   `if FROZEN` branch.
3. Source-run → should be inside `tools/`, next to `nblua.py`.
4. **`seamripper_settings.json` can mask a code fix.** If a bad path was
   saved before the fix landed, and that bad path happens to exist on
   disk (points at *some* file, just the wrong one), the self-heal
   fallback in `load_settings()` won't trigger, it only fires when the
   saved path doesn't exist at all. Delete the settings file to force
   regeneration if a fix doesn't seem to take.

**General principle, not just this bug:** tool-to-tool references
*within* `tools/` (e.g. `nblua.py` finding `luadec.exe` as a sibling via
its own `HERE = Path(__file__).resolve().parent`) are safe in both
layouts, the whole folder always moves as one unit. The fragile spot is
`SeamRipper.py` itself reaching *into* `tools/` from outside it, since
that's the one place source-run and frozen-build genuinely disagree
about what's flat and what isn't. Any new cross-boundary reference needs
the same `FROZEN` branch `tool_argv`/`_bundled()` already have, don't
add a new one without it.

## "REFUSED: container verification failed, output deleted."

Two different causes, same message shape, check which:

- **"independent decoder binary not found"** — `lzxverify`/`lzxverify.exe`
  missing or wrong-platform. Not a container bug, a packaging one. Same
  checklist as above: is it actually in the build folder, is the spec's
  `BINARIES` list resolving it from `tools/` correctly.
- **A real structural failure** (misaligned records, bad padding, missing
  terminator) — this is the gate doing exactly what it's for. Don't add
  a bypass flag. Investigate: what edit produced this file, did it
  resize a chunk, is `lu_chunk_replace.py`'s 16-byte rounding actually
  running. `tests/test_verify_lzx.py` has the synthetic repro of the
  original version of this bug; a new instance likely wants a new test
  alongside it, not just a manual fix.

## A function shows DIVERGENT and Ship refuses to touch it

Not a bug. The decompiler didn't reproduce that function byte-faithfully
on recompile, this is expected for some bytecode shapes, not all of
them. The GUI's "use luadec (cleaner)" checkbox is **ticked by default**,
meaning luadec is already the active backend, if a function is DIVERGENT
under it, try *unticking* to fall back to unluac for a second opinion,
not the reverse. Still divergent under both backends means that function
isn't safely editable with current tooling, don't force an injection
past the gate.

## Batch editor matches 0 calls, or way more than expected

Re-read `tests/test_lua_batchedit.py`'s
`test_target_slots_implicitly_anchor_to_example_value` before debugging
by hand, this exact confusion (42 matches instead of 26) already
happened once this project. A target slot gates on its own example value
by default; if you meant "touch this argument regardless of its current
value," that slot's `match_value` needs to be explicitly cleared, it
doesn't happen automatically just because the slot is tagged target.

If it's 0 matches and the pattern looks right: check whether the actual
call spans multiple lines in the decompiled source. `lua_callsplit.py`
has never been tested against a multi-line call, only single-line ones,
real ones from `npc.lua` and synthetic adversarial ones. If the
decompiler ever produces a wrapped call, this is the first place to
look, not a bug in the matching logic necessarily.

## Textures extract fine but conversion/embedding finds nothing, no error

Real incident, not hypothetical: `is_texture_chunk()` (`lu_convert.py`)
only checked for PiP's texture type tag (`0x34200007`). NB1's texture
type (`0x14200007`) was never in the check at all, for the entire
lifetime of that function, across every tool that imports it
(`lu_convert.py`'s own bulk convert, `lu_rig.py`'s texture embedding,
`pip_dump.py`). Every NB1 texture chunk silently fell through as "not a
texture," no error, no warning, just absent output. It went unnoticed
because nobody had run NB1 texture conversion against real data until
live testing surfaced it as: raw `.bin` chunks genuinely present in the
extracted `texture\` folder, but the converted-textures output folder
never gets created at all.

If a texture-consuming step produces no output and no error even though
the raw extracted chunks are confirmed present: check `is_texture_chunk`
recognizes the type tag for the game you're actually working with, don't
assume "no error" means "nothing to convert." `tests/test_lu_convert.py`
has the permanent regression for this specific incident; if a similar
silent-gap bug turns up elsewhere, that's the pattern to replicate, not
just a manual fix.

## A rig export has a real embedded texture but still looks completely untextured

The hardest one of these to diagnose, because every individual check
passes: the GLB has a valid `baseColorTexture`, a real embedded PNG with
a correct signature, sane non-degenerate UVs, and the material is bound
to the right primitive. Everything *structural* is correct. The actual
problem: the submesh referenced more than one texture (a real diffuse
plus something like a lightmap, AO map, or shadow mask), and the wrong
one got embedded, a real image, just not a color one. A greyscale
gradient applied as `baseColorTexture` renders almost identically to no
texture at all in every viewport mode, which is exactly why this looks
indistinguishable from "the embedding failed" without actually decoding
the pixels.

Confirmed by checking the R/G/B channel correlation of the extracted
image: 1.000 correlation (R≈G≈B at every pixel) means it's greyscale
regardless of what the file extension says.

`lu_rig.py` now scores every resolvable candidate for a submesh, not
just the first one, and picks whichever looks most like a real color
image (`tests/test_lu_rig.py`'s
`test_prefers_color_texture_over_greyscale_candidate` is the permanent
regression). This is a heuristic, not a format-guaranteed answer, it
could still pick wrong for a submesh whose real diffuse is itself mostly
monochrome. If a rig comes out looking flat again after this fix: check
the log's per-submesh line, it now prints every candidate hash and its
color-score, so which one got picked and why is visible directly instead
of needing this whole investigation again.

## The built EXE behaves differently than source-run testing

This is what shipped in v1.0.0. The two run through genuinely different
code paths (`tool_argv`'s `if FROZEN` branch, PyInstaller's flat
bundling vs. the real `tools/` folder), so "works from source" is not
evidence the built EXE works. **Always rebuild, actually launch the new
`dist\SeamRipper\SeamRipper.exe`, and retry the specific thing that was
fixed, before re-zipping.** Source testing and build testing are two
separate steps, neither substitutes for the other.

## A published release doesn't match current source

Happened once already: `v1.0.0`'s attached zip predates this fix. Git
history and release assets are not the same thing and don't update
together, pushing a fix to `main` does nothing to an already-published
release's attached binary. After any fix that touches build output:
rebuild, retest the actual EXE, then either edit the existing release to
swap the asset or cut a new tagged version, don't consider a fix
"shipped" until the release page itself has the new binary.

Worth eventually adding some visible build identifier (a version string
in the window title, a `--version` flag, anything) so "which build is
this" is answerable by looking at the running app, not by guessing from
when you think you last downloaded it.

## Claimed test coverage vs. actual test coverage

Keep these honest separately, they're not the same thing:

- **Structurally tested** (unit tests, synthetic fixtures): container
  verification, the splitter, the batch engine. Solid, repeatable,
  `tests/run_all.py`.
- **Boot-tested in-game**: NB1 — one function (`InitFears`), two edit
  shapes (scale, set), one file (`global.lu`). PiP — the pre-existing
  tooling, not yet re-run through the new mandatory verify gate
  specifically.
- Don't let the first category's thoroughness imply the second one's
  scope. "25/25 tests pass" says the mechanisms work correctly on what
  they've been asked to check, not that every function in every file
  mods safely. Widening the second category (more functions, more
  files, an actual PiP edit through the current gate) is still open
  work, independent of how solid the first category is.
