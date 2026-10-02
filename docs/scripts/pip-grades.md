---
title: "PiP: grades"
parent: Script reference
grand_parent: Game reference
nav_order: 6
---

# PiP: grade scores (bronze to platinum)

*Panic in Paradise.* The scores needed for bronze, silver, gold and platinum
on every level are in one script. Grade mods have been tested in-game.

## Where it lives

`global.lu` → `gamemodes`. The script has the developers' own comments, with
one section per area.

## What it does

Each level has a set of four scores, named after a bear (*interpretation:* the
level's target). Then each area lists its levels in order. Area 1, Grease Garage, exactly as in the
script (its other two sets left out):

```lua
local tremblesScores = engine.GradeScore()
tremblesScores:AddGradeScore(engine.eBRONZE_GRADE,  45000)
tremblesScores:AddGradeScore(engine.eSILVER_GRADE,  70000)
tremblesScores:AddGradeScore(engine.eGOLD_GRADE,    95000)
tremblesScores:AddGradeScore(engine.ePLATINE_GRADE, 130000)
```

```lua
local gameMode = engine.GameMode_Create(1, --[[HASH:"startmenu_story":0xffaefd84]]4289658244, "Area01", engine.eSTORY_MODE, engine.eNAUGHTY_POINT)
gameMode:SetGradeScoreAttribute(tremblesScores, 1)
gameMode:SetGradeScoreAttribute(greasyScores, 2)
gameMode:SetGradeScoreAttribute(buddyScores, 3)
mgr:AddGameModeToLevel(--[[HASH:"level_names_Area01":0x70a75517]]1890014487, gameMode)
```

`PLATINE` is platinum (the French spelling). The number after each set in
`SetGradeScoreAttribute` is the level's place in the area.

## The values

| Area | Target | Bronze | Silver | Gold | Platinum |
|---|---|---|---|---|---|
| Grease Garage | Trembles | 45000 | 70000 | 95000 | 130000 |
| | Greasy | 45000 | 70000 | 95000 | 130000 |
| | Buddy | 55000 | 80000 | 115000 | 155000 |
| Silky Mansion | Goober | 40000 | 60000 | 80000 | 115000 |
| | Silky | 85000 | 135000 | 185000 | 250000 |
| | Miyagi | 60000 | 95000 | 135000 | 185000 |
| Jungle Spa | Cozy | 60000 | 90000 | 120000 | 160000 |
| | Ketchup | 75000 | 110000 | 150000 | 195000 |
| | Treacle | 100000 | 150000 | 200000 | 260000 |
| Duegard Temple | Normal | 30000 | 50000 | 70000 | 100000 |
| | Tickler | 80000 | 120000 | 165000 | 220000 |
| | Rubbert | 85000 | 130000 | 180000 | 240000 |
| Fiesta Cantina | Sunbeam | 90000 | 140000 | 190000 | 260000 |
| | Stardust | 95000 | 140000 | 190000 | 250000 |
| | Xoctopus | 120000 | 180000 | 240000 | 305000 |
| Fiesta Docks | Twinkles | 80000 | 120000 | 165000 | 220000 |
| | Gordon | 85000 | 130000 | 175000 | 235000 |
| | Peluso | 80000 | 120000 | 165000 | 225000 |
| | Nibbles | 75000 | 110000 | 155000 | 205000 |
| Glasshouse Garden | Pudding | 30000 | 45000 | 65000 | 95000 |
| | Flopsey | 35000 | 55000 | 80000 | 110000 |
| | Ghoulplant | 65000 | 100000 | 135000 | 180000 |
| Wellness Center | Chubby | 55000 | 80000 | 110000 | 150000 |
| | Juggles | 60000 | 90000 | 125000 | 170000 |
| | Docteur | 75000 | 115000 | 160000 | 215000 |
| | Daddles | 55000 | 85000 | 120000 | 160000 |
| Prof Workshop | Fluffy | 60000 | 90000 | 125000 | 170000 |
| | Robo | 85000 | 125000 | 175000 | 225000 |
| | Prof | 90000 | 130000 | 175000 | 220000 |
| Paradise Beach | Bubble | 90000 | 140000 | 190000 | 255000 |
| | Danger | 100000 | 150000 | 205000 | 265000 |
| | Fuzz | 95000 | 140000 | 190000 | 255000 |
| | Oodoo | 95000 | 140000 | 190000 | 255000 |
| Paradise Resort | Cuddles | 65000 | 100000 | 140000 | 190000 |
| | Giggles | 95000 | 145000 | 200000 | 265000 |
| | Comfy | 80000 | 125000 | 170000 | 225000 |

Area and target names are the ones in the script's comments and variable
names, which can differ from what the game shows.

## How to change it

Change the four numbers for a level and Ship. Keep them in order, with bronze
lowest and platinum highest. *Interpretation:* out-of-order values may confuse
the results screen; this hasn't been tested.

The "Demo" section at the top of the script is commented out (every line
starts with `--`), so changing it does nothing.
