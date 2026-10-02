---
title: Naughty Bear
parent: Game reference
nav_order: 1
has_children: true
permalink: /game/nb1/
---

# Naughty Bear (NB1)

What the first game's scripts do. NB1's scripts are compiled Lua bytecode, so
Seam Ripper decompiles them when you open them, and the names you see in them
come from Seam Ripper's own name list. PiP is different: see
[Panic in Paradise](game-pip.md).

| Page | System | Main scripts |
|---|---|---|
| [Naughty's hats](scripts/hats.md) | Health and damage per hat | `naughtybear.lu` → `naughtybearhatbonus` |
| [Bear stats](scripts/bear-stats.md) | Each bear's health, fear, weapon and colour | `naughtyisland.lu` → `naughtyisland_npcs`; episode `*_npcs` |
| [Scoring](scripts/scoring.md) | Points and the combo multiplier | `global.lu` → `scoremanager`; `naughtyisland.lu` → `naughtyisland_npcbase`, `librarygameevents` |
| [NPC fear](scripts/npc-fear.md) | How bears get scared, including seeing Naughty attack another bear | `global.lu` → `npc`, `globaldictionnary`; `naughtyisland.lu` → `naughtyisland_npcbase`, `naughtyisland_npcs` |
| [Bear personalities](scripts/personalities.md) | Jock, Cheerleader, Threat, Smart: courage, moral, intelligence | `global.lu` → `characterclasses` |
| [Episodes and challenges](scripts/episodes.md) | Objectives, gate and bridge scores, challenge types, time limits | `ep1story.lu` → `ep1_story_rules`; `ep1challenge1.lu` → `ep1_cha1_rules` |
| [Traps and sabotage](scripts/traps-and-sabotage.md) | Bear trap damage, sabotage steps | `beartrap.lu` → `beartraptrigger`; `bbq.lu` → `bbq_sabotage` |
| [Weapons and pickups](scripts/weapons-and-pickups.md) | Picking up, dropping and despawning | `weaponmethods` (58 containers) |
| [Game text](scripts/game-text.md) | Where every word is kept and how to edit it | `<container>.en_us.lu` |
