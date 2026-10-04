---
title: Examples
nav_order: 3
has_children: true
permalink: /examples/
---

# Examples

Finished mods, each with a page that shows exactly what it changes and why.
They are here to show what Seam Ripper can do, and to be worked from: read the
edit, change a number, make your own.

Pick a game:

* **[Naughty Bear](naughty-bear.md)**: the HUD score feed, and the restored
  pre-order costumes.
* **[Panic in Paradise](panic-in-paradise.md)**: Hero firearms and Rage glow,
  each a small `.srpatch` you can apply.

## How to read the pages

Most are edits to the game's own scripts, made on the retail files and read
back with Seam Ripper. The scripts are plain Lua. Every excerpt on these pages
is copied from the game, with only the changed lines marked.

* A `+` line was added, a `-` line was removed.
* Anything marked *interpretation* is a reading of the code, not something
  tested.
* "Constants" are the numbers at the top of an edited script. Change them,
  reapply and the mod changes. They are the easiest place to start.

To see where the scripts come from and how they fit together, the
[Game reference](../game-reference.md) covers them system by system.
