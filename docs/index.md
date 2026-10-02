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
* [Your first mod](first-mod.md): change a hat's health, ship it, undo it.
* [Playing modded games](playing-modded-games.md): running your change.

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
* [Textures, models and sounds](assets.md): pulling the art and sound out.
* [Command-line tools](cli.md): every tool, and building the EXE.

**Game reference** (the games)

* [Naughty Bear](game-nb1.md): the first game's scripts. Easy places to start:
  [Naughty's hats](scripts/hats.md), [Episodes and challenges](scripts/episodes.md)
  and [Game text](scripts/game-text.md).
* [Panic in Paradise](game-pip.md): the second game's scripts. Easy places to
  start: [Fluffetics](scripts/pip-fluffetics.md) and
  [Unlockables and achievements](scripts/pip-unlockables.md). Includes the
  [June 26th beta](pip-june26-beta.md) notes.
* [File formats and PiP internals](game-files.md): containers, textures,
  meshes, PiP's script rules.
