---
title: Patches and backups
parent: Seam Ripper reference
nav_order: 1
---

# Patches and backups

A `.srpatch` is how a mod is shared. It holds only the lines you changed, so
it contains none of the game. Finished ones to try are on the
[Examples](examples/index.md) page.

## Using a patch

In the app, open the patch on the **Patches** page. Seam Ripper checks your
files first and says whether it fits, then you can apply it to your game or to
a copy. To make one, use **Save as patch…** on the **Changes** page.

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

## How a patch is stored

A `.srpatch` is a zip with a `manifest.json`. Each script edit is stored as
the changed lines plus fingerprints of the lines around them, so it can still
be placed if the recipient's copy has other edits. Text edits store only the
changed strings. Patches are always made against the retail file, even after
you've shipped into it. When applying, Seam Ripper rebuilds the file from the
recipient's own copy, verifies it, backs up the original and writes the
result. Each patch records the Seam Ripper version that made it.

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

