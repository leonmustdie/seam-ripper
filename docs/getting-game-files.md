---
title: Getting your game files
nav_order: 2
---

# Getting your game files

Seam Ripper works on a folder of game files, the one with `lu` in it. Here's
how to get that folder from your own copy of each game.

## Naughty Bear (disc image)

NB1 came on disc, so you start from a disc image (`.iso`) of your copy.

If your Tools page has no **Extract game disc** button, download Seam Ripper
again from the Releases page; the first 2.0 download didn't have it yet.

1. In Seam Ripper, open **Tools → Extract game disc (.iso)**.
2. Pick your `.iso` and a folder to put the files in.
3. Click **Run**. It takes a minute or so.

You get `Default.xex`, `lu` (the game files Seam Ripper edits) and `streams`
(sound). Tick **Only the lu folder** if that's all you want.

Then pick that folder at the top left of Seam Ripper, and you're ready to
mod.

From the command line, the same thing is:

```
SeamRipper.exe --tool xiso_extract.py extract "Naughty Bear.iso" -o "NB1 files"
```

### Why other ISO tools fail

A full Xbox 360 disc image doesn't start with the game's files. It starts with
a video partition, and the game's file system begins about 250 MB in. Tools
made for original Xbox images look at the very start, find nothing, and give
up. Seam Ripper checks every known layout (full 360 images, trimmed or
rebuilt images, original Xbox).

## Naughty Bear: Panic in Paradise (Arcade package)

PiP was an Xbox Live Arcade game, so there's no disc. It comes as a package
file from your console's storage instead. To unpack it:

1. Open **Horizon** and go to its **Package Manager**.
2. Open your PiP package.
3. Go to **Contents** and click **Extract All**.

That gives you the game's folder with `lu` in it. Pick it in Seam Ripper as
usual.

PiP's title ID is `5841127D`, which helps if you're looking for its package
among other Arcade games.

## Keep a clean copy

Before you start modding, copy your extracted folder somewhere safe. Seam
Ripper backs up every file it changes, but a clean copy of the whole game is
the easiest way to start over or compare against later.
