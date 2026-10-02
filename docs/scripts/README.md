---
title: Script reference
nav_exclude: true
permalink: /scripts/
---

# Script reference

What the games' Lua scripts actually do, one page per system, in two groups:
[Naughty Bear](../game-nb1.md) and [Panic in Paradise](../game-pip.md). They
are kept apart because the two games' scripts differ: NB1's are compiled
bytecode that Seam Ripper decompiles, PiP's are plain source. The rest of the
docs cover the tool; these pages cover the game.

## How to read these pages

* **Code blocks are exact.** Every excerpt is copied from Seam Ripper's own
  output (Files page, or `lu_lua.py read`) on the retail containers, with
  nothing added inside the block. Where lines are left out, the text above the
  block says which. In NB1 the `--[[HASH:"..." TEXT:"..."]]` annotations are
  Seam Ripper's: the original scripts are compiled bytecode and carry no
  comments. PiP scripts are the developers' own source, comments included.
* **Confirmed vs. interpretation.** "Confirmed" means the script says so
  directly. Anything read from a function name or a pattern of values, and
  not tested in-game, is marked *interpretation*.
* **Where to find it.** Each page names the container and the script, so you
  can open the same code: pick the `.lu` on the **Files** page and open the
  script.

## Adding a page

Name the page after the system (`stealth-kills.md`, `scares.md`, ...), add it
to its game's page ([Naughty Bear](../game-nb1.md) or [Panic in Paradise](../game-pip.md)), and follow the same shape: where it lives, the exact code,
what it does, what is confirmed, and how to change it.
