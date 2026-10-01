# Seam Ripper

![Seam Ripper](seamrpr.png)

Modding tools for the Xbox 360 Naughty Bear games: **Naughty Bear** and **Naughty Bear: Panic in Paradise**.

Seam Ripper opens the games' `.lu` files so you can read and edit the gameplay scripts, change the text, pull out textures, models and sounds, and put it all back. You can share your mods as small patch files that don't contain any of the game.

You need your own copy of the game files. Nothing from the games is included here.

This replaces the tools from my older [.lu documentation repo](https://github.com/leonmustdie/lu-documentation).

## Download

Grab the latest zip from [Releases](../../releases), extract it anywhere and run `SeamRipper.exe`. No Python needed.

This GitHub page is the only official place to get Seam Ripper.

Need the game files first? See [Getting your game files](docs/getting-game-files.md).

To run from source instead: `pip install PySide6 pillow`, then `python SeamRipper.py`.

## The GUI

Pick your game folder (the one with `lu\` in it) at the top left. Then:

* **Files**: open a container and a script, and edit it. **Check** tells you if it compiles.
* **Search**: find text in every script in the game.
* **Changes**: your edits so far. **Ship** writes them into the game files.
* **Patches**: save your changes as a `.srpatch`, or apply someone else's.
* **History**: every file Seam Ripper changed. Undo one, or put everything back to retail.
* **Tools**: text, textures, models, sound and the rest.

Seam Ripper backs up every game file before changing it, so you can always go back.

### Editing scripts

Both games work. NB1's scripts are compiled, so Seam Ripper decompiles them for you; PiP's are already plain text.

A few things worth knowing:

* Edit what's inside functions and leave the function names and arguments alone.
* Write whole numbers without a decimal point (`20`) and decimals with one (`2.5`). NB1 treats them as different types.
* Many scripts are in several `.lu` files and the game only uses one copy. Ship lists the other files that have the same script; leave them ticked or your edit might do nothing.
* If Ship refuses a function, leave that one unedited. The rest of your changes still go through.

Want to know what to edit? [docs/scripts](docs/scripts/README.md) explains what the game's scripts do. [Naughty's hats](docs/scripts/hats.md) (NB1) and [weapons and outfits](docs/scripts/pip-weapons-and-outfits.md) (PiP) are easy places to start.

### Patches

A patch only holds the lines you changed. Make one with **Save as patch…** on the Changes page.

To use one, open it on the Patches page. Seam Ripper checks your files first and tells you if it fits, then you can apply it to your game or to a copy.

### Playing your changes

If you play NB1 through restuff, set its folder in **Settings → Play**. **Ship & launch** ships your changes, copies them into the build and starts the game.

## Troubleshooting

**My edit does nothing in game.** The script is probably in more than one `.lu` file. Ship to all of the ones listed.

**Apply is greyed out / "read-only".** Your game files are set to read-only in Windows. Use *Apply to a copy…*, or untick read-only in the file's Properties.

**A button did nothing.** Check the **Log** tab at the bottom. It shows what ran and what went wrong.

**Textures came out as `.bin` files.** Run *Convert textures/meshes* on the folder you extracted to.

## More

* [docs/technical.md](docs/technical.md): file formats, how the decompiler works, PiP internals
* [docs/cli.md](docs/cli.md): command-line tools and building the EXE
* [docs/scripts](docs/scripts/README.md): what the game's scripts do

## Legal

Seam Ripper is a fan-made modding tool. It contains no assets, scripts or code from any Naughty Bear game. Use it only with files from copies of the games you own. *Naughty Bear* and *Naughty Bear: Panic in Paradise* were developed by Artificial Mind and Movement / Behaviour Interactive and published by 505 Games; all rights to the games belong to their owners. This project isn't affiliated with or endorsed by them.

Bundled third-party tools (luac, unluac, luadec, and lzxverify from libmspack) are listed with their licenses in [docs/cli.md](docs/cli.md#bundled-third-party-tools).

Icon, description image and the icon's .SVG files were made by [Mallorie](https://github.com/unixfunnies).
