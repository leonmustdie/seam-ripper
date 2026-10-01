# PiP: weapons and outfits

*Panic in Paradise.* Every weapon and outfit piece Naughty can buy has one
line in a table: its stats, its price and how much use it takes to level up.
PiP's scripts are plain text, so these are some of the easiest edits in
either game.

## Where it lives

| Container | Script | What's in it |
|---|---|---|
| `levelcommon.lu` | `weapons` | Every weapon (94 entries) |
| `levelcommon.lu` | `accessoriesattribute` | Every outfit piece: `_Top`, `_Mid` and `_Bottom` |
| `global.lu` | `libraryattributes` | What each stat code means |

## One entry

A weapon, exactly as it appears in `weapons`:

```lua
        [--[[HASH:"Machete":0xac32dc3b]]2889014331]           	= {Hidden = false, 	LUName = "Machete",      	Bonus = {md=80},   	ExpLimit = 1500, 	ExpSlot = 357, MenuID = "Machete",     	costNP=18125,  	menuPos = 14,    unlockToken=0},
```

And an outfit piece from `accessoriesattribute`:

```lua
        [--[[HASH:"TribalPaint_Mid":0xa69d342c]]2795320364]         = {Hidden = false, LUName = "TribalPaint_Mid",        		Bonus = {hp=400,hr=50,sd=200},	ExpLimit = 3000,	ExpSlot = 88, MenuID = "TribalPaint_Mid",         costNP=47000,      	menuPos = 500,  unlockToken=--[[HASH:"TribalPaint_Mid":0xa69d342c]]2795320364, UsableOnlyByHero=false },
```

| Field | Meaning |
|---|---|
| `Bonus` | The stats it gives (codes below) |
| `costNP` | Price in naughty points |
| `ExpLimit` | Use needed to fully level it up |
| `Hidden` | `true` keeps it out of the shop |
| `menuPos` | Its place in the shop list |
| `ExpSlot`, `LUName`, `MenuID`, `unlockToken` | Save-game and menu IDs. **Don't change these.** |

## Stat codes

From `libraryattributes` (the game's own names):

| Code | Stat | Used by the game |
|---|---|---|
| `hp` | life | yes |
| `md` | melee damage | yes |
| `sd` | sanity damage | yes |
| `mr` | melee resistance | yes |
| `st` | stamina multiplier | yes |
| `hr` | health regen multiplier | yes |
| `np` | cash multiplier | yes (3 weapons) |
| `rd` | ranged damage | no item uses it |
| `rr` | ranged resistance | no item uses it |
| `xp` | exp multiplier | no item uses it |

## How to change it

Change a number inside `Bonus` or `costNP` and Ship. For example,
`Bonus = {md=80}` → `Bonus = {md=120}` makes the Machete hit harder. Weapon damage
and outfit stat mods have both been tested in-game.

Two rules, both found the hard way:

* **Only use codes the game already uses.** Adding `rr` to an outfit hung the
  game at load, even though `rr` is listed in `libraryattributes`. Stick to
  the "yes" rows above.
* **Stay inside the game's own range.** Outfit `hp` works at 400, the highest
  value the game uses (Tribal Paint), but the game hangs at 30000. The
  highest weapon `md` in the game is 180.

An edit must also fit in the space the original script took up. Changing
numbers never runs into this; Ship squeezes out spare whitespace if needed and
tells you if an edit is too big.
