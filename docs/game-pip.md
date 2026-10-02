---
title: Panic in Paradise
parent: Game reference
nav_order: 2
has_children: true
permalink: /game/pip/
---

# Naughty Bear: Panic in Paradise (PiP)

What the second game's scripts do. PiP's scripts are plain Lua source written
by the developers, comments included, so what you read in Seam Ripper is what
they wrote. NB1 is different: see [Naughty Bear](game-nb1.md). The
[File formats](game-files.md) page covers how PiP's containers differ.

| Page | System | Main scripts |
|---|---|---|
| [Weapons and outfits](scripts/pip-weapons-and-outfits.md) | Weapon and outfit stats, prices | `levelcommon.lu` → `weapons`, `accessoriesattribute` |
| [Grades](scripts/pip-grades.md) | Scores for bronze to platinum | `global.lu` → `gamemodes` |
| [Fluffetics](scripts/pip-fluffetics.md) | The five profile upgrades, one `if` each | `finishingmove`, `traptrigger`, `stuckintrap` and others |
| [Levels and game modes](scripts/pip-levels.md) | How a level is registered, loaded and scored; which area is which | `levelloaders.lu`; `global.lu` → `gamemodes` |
| [Unlockables and achievements](scripts/pip-unlockables.md) | The rules for unlocking attacks, weapons and costumes | `global.lu` → `unlockablerules`, `rules_achievements` |
| [Text and menus](scripts/pip-text-and-menus.md) | Editing PiP's text; extracting the menu movies | `<unit>.en_us.lu`; `startmenu.lu` |
| [June 26th Beta Discoveries](pip-june26-beta.md) | Getting the beta's debug "zoo" levels to run | `levelloaders.lu`, the zoo containers |
