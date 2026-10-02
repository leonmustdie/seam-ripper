---
title: "PiP: levels and game modes"
parent: Panic in Paradise
grand_parent: Game reference
nav_order: 4
---

# PiP: levels and game modes

*Panic in Paradise.* A story level is set up by two scripts: a **loader** that
says what the level is and what to load, and an entry in **gamemodes** that
says how it is scored. Both are plain, commented source.

## Where they live

* `levelloaders.lu`: one script per level, named `area1_loaderscript`,
  `area15_loaderscript` and so on. Retail also has loaders for zoo levels and
  an older `level1_loaderscript` to `level10_loaderscript` set.
* `global.lu` → `gamemodes`: see [PiP: grades](pip-grades.md) for the scores in
  it. This page is about how the pieces connect.

## One level, three missions

Each story level (an *area*) holds three or four missions, the zones
`AREA_1`, `AREA_2` and `AREA_3`, each with its own target bear. The loader
registers the level once, then every zone. Area 1, as in the script (the
second and third zones left out):

```lua
local myLevelID = --[[HASH:"level_names_Area01":0x70a75517]]1890014487
local levelName = myLevelID
RegisterLevel( { name=myLevelID, globalIndex = 2, levelLoader = __this__:GetName(), locationID = 1, 
                 menuData={descTxtID=myLevelID, IconLU="", IconSWF=""}})
```

```lua
RegisterZone( { zoneID = AREA_1, levelName = myLevelID, targetImage = "Polaroid_Trembles", targetID = targetID1,
                objectiveID = objectiveID1, status = 2, briefingID = briefingID1, miniMap=--[[HASH:"Area01":0x3a0d5e1c]]973954588, 
                token=--[[HASH:"num_level_completed_03":0x6d024ea6]]1828867750, menuPos = 5, leaderboardID = engine.LEADERBOARD_TEMBLES,
                iconID = 1 } )
```

A comment above them lists the `status` values: `1-new 2-LOCKED 3-DEFFLUFED
4-Secret`. *Interpretation* of the rest: `targetImage` is the polaroid of the
bear to kill, `objectiveID` and `briefingID` point at text, `menuPos` is the
slot on the menu, and `globalIndex` is the order the levels are played. Cuddles'
level, Area 15, is `globalIndex = 1`, and that is Stage 1 in the game.

## Which areas are which

Worked out from each loader's `globalIndex`, its targets, and the area names in
the comments of `gamemodes`:

| Order | Area | Name | Target bears |
|---|---|---|---|
| 1 | 15 | Paradise Resort | Cuddles, Giggles, Comfy |
| 2 | 1 | Grease Garage | Trembles, Greasy, Buddy |
| 3 | 9 | Glasshouse Garden | Pudding, Flopsey, Ghoulplant |
| 4 | 3 | Jungle Spa | Cozy, Ketchup, Treacle |
| 7 | 2 | Silky Mansion | Goober, Silky, Miyagi |
| 8 | 7 | Fiesta Docks | Twinkles, Gordon, Peluso, Nibbles |
| 13 | 12 | Prof Workshop | Fluffy, Robo, Professor B |
| 15 | 5 | Duegard Temple | Normal, Tickler, Rubbert |
| 16 | 11 | Wellness Center | Chubby, Juggles, Dr Docteur, Daddles |
| 17 | 13 | Paradise Beach | Bubble, Danger Bear, DJ Fuzz, Oodoo |
| 19 | 6 | Fiesta Cantina | Sunbeam, Stardust, Xoctopus |

The numbers skip (5, 6, 9 to 12, 14, 18). *Interpretation:* levels that were
cut or never made. The area numbers skip too (4, 8, 10, 14).

## What a level loads

`InitializeLoadUnits` lists the containers the level needs. Things the whole
game needs are loaded once; the three missions each add their own copy of the
level's containers:

```lua
    LibraryLoading.AddZonesLU(LOAD_INIT, "SkinNaughty")
    LibraryLoading.AddZonesLU(LOAD_INIT, "BearaBearaIsland")
    LibraryLoading.AddZonesLU(LOAD_INIT, "StoryMode")
    ...
    LibraryLoading.AddZonesLU(AREA_1, "Area01")
    LibraryLoading.AddZonesLU(AREA_2, "Area01")
    LibraryLoading.AddZonesLU(AREA_3, "Area01")
    LibraryLoading.AddZonesLU(AREA_1, "Area01_NPC")
    ...
    LibraryLoading.LoadZone(LOAD_INIT, levelLoadUnitRequester)
    -- Load everything in AREA_1 and ENVR_1
    LoadInitialZone()
```

`LOAD_INIT` containers load once and are never reloaded. The `Area01_NPC` files
are the bears: `_NPC_1`, `_NPC_2` and `_NPC_3` are one per mission.

## The level name

The level's name is a hash, and it must match in two places: the loader (as
`name` and `descTxtID`) and the `AddGameModeToLevel` line in `gamemodes`. The
number is the CRC32 of the name in lowercase: `level_names_area01` gives
`0x70a75517`. The beta page used the same rule to give its zoo levels IDs.

## How to change it

Changes that are safe to try:

* The objective, briefing and polaroid names, to point a mission at other
  text or art.
* Which containers a level loads, to swap the bears or the level around.

Two things to know from [the beta page](../pip-june26-beta.md): a loader has to
keep its **exact size** (Seam Ripper pads it back), and anything you put in
`LOAD_INIT` is loaded once, so a level restart will not rebuild it. Load a
level's own content as `AREA_1` and call `LoadInitialZone()`, as the story
levels do.

## Confirmed and not

* Confirmed: the structure above, and that Area 15 is Stage 1.
* *Interpretation:* what each `RegisterZone` field is for, apart from the
  `status` comment, and the gaps in `globalIndex`.
* Retail has loader scripts for zoo levels, but I found no zoo containers in the
  retail files, so those loaders have nothing to load.
