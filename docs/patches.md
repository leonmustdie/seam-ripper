---
title: Patches and backups
parent: Seam Ripper reference
nav_order: 1
---

# Patches and backups

A `.srpatch` is how a mod is shared. It holds only what you changed: the
lines of a script, the strings, and for animations, textures and models your
own clip, picture or vertices. Nothing you left alone is in it, and the
recipient's own game files are rebuilt with your changes. A picture or model
made by editing the game's own (a recoloured texture, a sculpted body) is
still derived from the game's art, so the patch carries that. Finished ones
to try are on the [Examples](examples/index.md) page.

## Using a patch

In the app, open the patch on the **Patches** page. It lists each file the
patch changes and what it does there: script changes, strings, and each
animation, texture or model it replaces. Seam Ripper checks your files first
and says whether it fits, then you can apply it to your game or to a copy. To
make one, use **Save as patch…** on the **Changes** page.

From the command line (`sr_patch.py`, see [Command-line tools](cli.md)):

```
SeamRipper.exe --tool sr_patch.py info  hero-firearms.srpatch
SeamRipper.exe --tool sr_patch.py apply hero-firearms.srpatch "PiP files\lu" --check
SeamRipper.exe --tool sr_patch.py apply hero-firearms.srpatch "PiP files\lu" -o "patched"
```

`--check` only reports which of your files the patch fits. `-o` writes the
patched files to another folder instead of replacing the game's.

To make one, give `make` the *original* container, the index of the script and
your edited copy of it:

```
SeamRipper.exe --tool sr_patch.py make -o my-mod.srpatch --name "My mod" ^
    --script levelcommon.lu 75 my_edited_script.lua
```

For an animation swap, **Replace an animation** saves the patch for you (see
[Assets](assets.md#replacing-an-animation)); so do **Replace a texture** and
**Replace a model** ([Assets](assets.md#replacing-a-texture)). `make` also
takes them directly:

```
SeamRipper.exe --tool sr_patch.py make -o fur.srpatch --name "Blue fur" ^
    --texture characters_shared_resources.lu 26ca1642 fur_blue.png
SeamRipper.exe --tool sr_patch.py make -o head.srpatch --name "Big head" ^
    --mesh naughtybear.lu 743299d0 head_edit.json
```

The `--mesh` file is a neutral vertex edit (the format `lu_mesh.py` writes);
**Replace a model** makes it from your GLB for you.

## How a patch is stored

A `.srpatch` is a zip with a `manifest.json`. Each script edit is stored as
the changed lines plus fingerprints of the lines around them, so it can still
be placed if the recipient's copy has other edits. Text edits store only the
changed strings. A replacement animation is stored as the clip's motion only (a
`.json` clip file, no game bytes) and rebuilt into the recipient's own clip;
it is refused if their clip is not the one the patch was made for. A Panic
in Paradise clip stored in another clip's record (see
[Assets](assets.md#replacing-an-animation)) needs Seam Ripper with patch
format 4. A replaced texture is stored as the picture you gave (PNG, or the
DDS as you made it), re-encoded into the recipient's own texture; a model
edit as the ids and new positions, normals and texture coordinates of the
vertices you moved, written into the recipient's own model. Both are refused
when the recipient's texture or model is not the one the patch was made for,
and need Seam Ripper with patch format 5. A new model (Import a new model) is
stored as your model: its vertices, triangles, texture coordinates and
weights by skeleton bone, and the parts it hides; it is built into the
recipient's own model record, also format 5. The picture is yours, but if you
made it by recolouring the game's texture, the patch carries that recoloured
art. A patch
can also *add* strings the game's text file doesn't
have: in the strings file, write `+HASH`, a tab and the text. A line without
the `+` still only edits an existing string, so a mistyped ID can't add one
by accident. Builds of Seam Ripper from before this was added can't add
strings, so a patch that does is marked as needing a newer Seam Ripper and
those builds refuse it, instead of applying without the text. If you get that
message, download Seam Ripper again. Patches are always made against the retail file,
even after you've shipped into it. When applying, Seam Ripper rebuilds the file from the
recipient's own copy, verifies it, backs up the original and writes the
result. Each patch records the Seam Ripper version that made it. From 2.5 on,
the parts of a Naughty Bear file that an edit doesn't touch keep their original
compressed bytes, and the parts it changes are stored uncompressed, the way
Panic in Paradise patches already were. Applying even a new model takes a
few seconds, and the patched file is larger than the original (a new model
for Naughty grew `naughtybear.lu` from 6.6 MB to 9.8 MB). A patch made with an older
version may therefore report "applied, but not byte-identical to the author's
result". The file was still verified; only its compression differs.

**Size.** A Panic in Paradise script has to stay the size it was: the game
lays a container out by the size of each script, so one that comes out smaller
moves everything after it and the level fails to load. When your edit is
bigger than the slot, Seam Ripper squeezes out whitespace to fit; when it ends
up smaller, it pads the end with spaces back to the original length. You don't
need to do anything, but it is why a patched script can look reindented next to
the original.

## Backups

Before overwriting a game file, Seam Ripper keeps the original and the last
10 versions in a `.seamripper\backups` folder next to it. Read-only files are
never overwritten.

