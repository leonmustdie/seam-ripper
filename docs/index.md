---
title: Home
nav_order: 1
permalink: /
---

# Seam Ripper

Modding tools for the Xbox 360 Naughty Bear games: **Naughty Bear** and
**Naughty Bear: Panic in Paradise**.

Seam Ripper opens the games' `.lu` files so you can read and edit the gameplay
scripts, change the text, pull out textures, models and sounds, and put it all
back. Mods can be shared as small patch files that don't contain any of the
game.

[Download Seam Ripper](https://github.com/leonmustdie/seam-ripper/releases){: .btn .btn-primary }

The GitHub page is the only official place to get Seam Ripper. How to use the
app is in the [README](https://github.com/leonmustdie/seam-ripper#readme).

## What's here

**Start**

* [Getting your game files](getting-game-files.md): from your NB1 disc image
  or PiP Arcade package to a folder you can mod.

**Examples**

* [Examples](examples/index.md): finished PiP mods as `.srpatch` files, with
  the exact edits explained. [Hero firearms](examples/hero-firearms.md) lets
  Naughty pick up and fire guns; [Rage glow](examples/rage-glow.md) makes
  ultra-kills power him up.

**Seam Ripper reference** (the tool)

* [Patches and backups](patches.md): the `.srpatch` format, making and
  applying patches.
* [How Seam Ripper works](technical.md): Ship, the decompiler, hashed names,
  output formats.
* [Command-line tools](cli.md): every tool, and building the EXE.

**Game reference** (the games)

* [Script reference](scripts/README.md): what the game's scripts do and how to
  change them. Easy places to start: [Naughty's hats](scripts/hats.md) (NB1)
  and [weapons and outfits](scripts/pip-weapons-and-outfits.md) (PiP).
* [File formats and PiP internals](game-files.md): containers, textures,
  meshes, PiP's script rules.
* [PiP: June 26th Beta Discoveries](pip-june26-beta.md): getting the beta's debug
  "zoo" levels to run, and why they hang.
