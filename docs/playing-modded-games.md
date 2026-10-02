---
title: Playing modded games
nav_order: 5
---

# Playing modded games

Seam Ripper edits the game's files. To see the change you have to run the game
from the edited files. Keep a clean copy of the originals first (see
[Getting your game files](getting-game-files.md#keep-a-clean-copy)).

## Naughty Bear (NB1)

The author tests NB1 through *restuff*, a native PC build made for this. In
Seam Ripper, set its folder in **Settings → Play**. **Ship & launch** then ships
your changes, copies them into the build and starts the game. This is the only
way to run NB1 that Seam Ripper has built-in support for.

## Panic in Paradise (PiP)

PiP is tested in the Xenia Canary emulator. Run the game from the folder you
extracted, with the game's `default.xex` next to the `lu` folder, then use
Seam Ripper to change the files in that folder and start the game again. We used
Xenia Canary with `--license_mask=1`.

On a real console: not tested. Do not replace files on a console without a
backup.

## Tips

* If a change does nothing, the script is probably in more than one `.lu` file.
  Ship to all of them (see [Scripts in several containers](technical.md#scripts-in-several-containers)).
* If the game hangs or stops at a black screen after a change, undo that change
  on the **History** page first. Edited PiP scripts must stay the size they were
  (see [Patches and backups](patches.md)), and Seam Ripper handles that for you.
* A patch you did not make is safest applied to a copy first.
