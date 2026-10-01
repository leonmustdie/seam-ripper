---
title: Script reference
nav_order: 2
has_children: true
permalink: /scripts/
---

# Script reference

What the games' Lua scripts actually do, one page per system. The rest of the
docs cover the tool (how to read, edit and ship a script); these pages cover
the game.

### Naughty Bear

| Page | System | Main scripts |
|---|---|---|
| [npc-fear.md](npc-fear.md) | How bears get scared, including seeing Naughty attack another bear | `global.lu` → `npc`, `globaldictionnary`; `naughtyisland.lu` → `naughtyisland_npcbase`, `naughtyisland_npcs` |
| [hats.md](hats.md) | Naughty's hats: health and damage | `naughtybear.lu` → `naughtybearhatbonus` |
| [bear-stats.md](bear-stats.md) | Each bear's health, fear, weapon and colour | `naughtyisland.lu` → `naughtyisland_npcs`; episode `*_npcs` |
| [scoring.md](scoring.md) | Points and the combo multiplier | `global.lu` → `scoremanager`; `naughtyisland.lu` → `naughtyisland_npcbase`, `librarygameevents` |

### Panic in Paradise

| Page | System | Main scripts |
|---|---|---|
| [pip-weapons-and-outfits.md](pip-weapons-and-outfits.md) | Weapon and outfit stats, prices | `levelcommon.lu` → `weapons`, `accessoriesattribute` |
| [pip-grades.md](pip-grades.md) | Scores for bronze to platinum | `global.lu` → `gamemodes` |

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
to the table above, and follow the same shape: where it lives, the exact code,
what it does, what is confirmed, and how to change it.
