---
title: Naughty Bear examples
parent: Examples
has_children: true
nav_order: 1
---

# Naughty Bear examples

| Example | What it does | What it touches |
|---|---|---|
| [HUD score feed](hud-score-feed.md) | Score lines stack up to six at a time, newest on top, with the score on the same line, and fade out quickly, instead of replacing each other one at a time | The HUD's Flash movie in `levelcommon` |
| [Pre-order costumes](preorder-costumes.md) | Restores Naughty Kruebear and Naughty Slasher, the original pre-order costumes, from the DLC packages | `init_unlockable` in `global`, plus text in `global` and `levelcommon` (a zip with the costume files and a patch) |

The HUD score feed is a Flash edit, which a patch cannot carry yet, so it comes
as a script that builds the modified file from your own copy. The pre-order
costumes come as a zip with a `.srpatch` and the two costume files. Each page
says how to use it.

How patches work is on [Patches and backups](../patches.md).
