---
title: Examples
nav_order: 3
has_children: true
permalink: /examples/
---

# Examples

Finished mods and previews, each with a page that shows exactly what it
changes and why. They are here to show what Seam Ripper can do, and to be
worked from: read the edit, change a number, make your own.

The two games are listed separately, because they are at different stages:
*Panic in Paradise* has finished `.srpatch` files you can apply, and *Naughty
Bear* has its first example, a preview.

## Naughty Bear

| Example | What it does | What it touches |
|---|---|---|
| [HUD score feed](hud-score-feed.md) (preview) | Score lines stack up to six at a time, newest on top, with the score on the same line, and fade out quickly, instead of replacing each other one at a time | The HUD's Flash movie in `levelcommon` |

There is no patch file for this one yet. A patch holds only changed lines of
script, and this edit is to a Flash movie. Support for that is planned for
version 2.5; the page says what it took by hand.

## Panic in Paradise

Each of these is a small `.srpatch` you can apply. A patch holds only the
lines that were changed, never any of the game, so these files are safe to
share. How patches work is on [Patches and backups](../patches.md).

| Example | What it does | Scripts touched |
|---|---|---|
| [Hero firearms](hero-firearms.md) | Naughty picks up guns and fires them, with a six-round clip, a reload pause and knife-style swings | `levelcommon` (2 scripts), `skinnaughty` (2 scripts) |
| [Rage glow](rage-glow.md) | Every ultra-kill makes Naughty's fists glow and hit harder, with no unlock needed | `skinnaughty` (1 script) |

## Apply one

1. Get your Panic in Paradise files ([Getting your game files](../getting-game-files.md)).
2. In Seam Ripper, open the patch on the **Patches** page. It checks that it
   fits your files.
3. Apply it to a copy first, then to the game. Seam Ripper backs up what it
   replaces.

The two patches change different scripts, so you can apply both.

## What they are made from

Both are edits to the game's own scripts, made on the retail files and read
back with Seam Ripper. The scripts are plain Lua. Every excerpt on these pages
is copied from the game, with only the changed lines marked.

* A `+` line was added, a `-` line was removed.
* Anything marked *interpretation* is a reading of the code, not something
  tested.
* "Constants" are the numbers at the top of an edited script. Change them,
  reapply and the mod changes. They are the easiest place to start.

To see where the scripts come from and how they fit together, the
[Game reference](../game-reference.md) covers them system by system.
