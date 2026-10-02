---
title: Your first mod
nav_order: 4
---

# Your first mod

A small change you can make in a few minutes, check, and undo: give one hat in
*Naughty Bear* more health. It uses the same steps as any other script mod.

You need your game files first ([Getting your game files](getting-game-files.md)).
The button names below are from the app's README.

## 1. Open the game folder

Start Seam Ripper and pick your game folder, the one with `lu` inside it, at the
top left.

## 2. Find the script

Open the **Files** page, pick the container `naughtybear.lu`, and open the
script `naughtybearhatbonus`. This is the script that sets each hat's health and
damage. [Naughty's hats](scripts/hats.md) explains what is in it.

## 3. Change a number

Find the Adept hat:

```lua
  elseif hashName == --[[TEXT:"Hat: Adept Naughty"]]0x64b5d953 then
    characterComponent:SetBaseHitPoints(250)
    characterComponent:SetRemainingHitPoints(250)
```

Change both `250`s to `400`. Keep them the same, and write whole numbers without
a decimal point.

Press **Check**. It tells you whether the script still compiles.

## 4. Ship it

Open the **Changes** page. Your edit is listed there. Press **Ship**. Seam
Ripper lists the other containers that hold the same script. Leave them ticked,
or the game may use another copy and your change will do nothing.

Seam Ripper backs up each file before it writes it.

## 5. Try it

Play with the Adept hat on. How you play depends on the game: see
[Playing modded games](playing-modded-games.md).

## 6. Undo it

Open the **History** page. Every file Seam Ripper changed is listed. Undo this
one, or put everything back to retail.

## What to try next

* A script with more to read: [Bear stats](scripts/bear-stats.md).
* Share your change as a patch: [Patches and backups](patches.md).
* Ready-made mods to read and change: [Examples](examples/index.md).
