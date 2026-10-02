---
title: "PiP: unlockables and achievements"
parent: Panic in Paradise
grand_parent: Game reference
nav_order: 5
---

# PiP: unlockables and achievements

*Panic in Paradise.* What you have to do to unlock a weapon, an attack or a
costume, and what earns an achievement, is a list of rules in three scripts.
Each rule is one line: a name, a condition, and a number or an item. That makes
them some of the easiest things in the game to change.

## Where it lives

All in `global.lu`:

* `unlockablerules`: the rules for unlocking things.
* `rules_achievements`: the rules for achievements.
* `libraryunlockable`: the functions both call (`UnlockablesRegisterLevelRules`
  and the like). You rarely edit it, but its comments say what each kind of
  rule expects, for example "minCount = minimum number of levels to be
  completed".

## How a rule reads

The name is a hash, then a table. The same `unlockCondTxtID` is the text
shown for the condition, shared by many rules:

```lua
[--[[HASH:"rank_names_rank02":0x53d83b54]]1406679892]   = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_condition_reach_level":0x974f744b]]2538566731, lvl = 2 },
```

`InitializeAllRules` then runs the groups in this order (the last four only
outside the demo):

| Function | What it unlocks |
|---|---|
| `InitializePlayerLevelRules` | The player ranks, `rank01` to `rank100`, each at `lvl = 1` to `100` |
| `InitializePlayerUpgradeAttack` | Attack moves, by rank |
| `InitializeMultiTokenRules` | An unlock that needs other unlocks first, such as the Baseball bat and Machete masteries together |
| `InitializeObjectOwnershipRules` | Items that unlock when you own two others |
| `InitializeAcquireItemRules` | Weapons from ultra-kills, and costumes stolen from bears |
| `InitializeItemMasteryRules` | Mastery of a weapon |
| `InitializeLevelCompletedRules` | Number of levels finished |
| `InitializeKillCompletedRules` | Killing a particular bear |
| `InitializeLevelTrophyRules`, `InitializeTrophyCountRules` | A grade on one level (`lvl1_story_bronze`), and a total number of one kind of cup (`gold_allcup` needs `minCount=36`) |

## Attacks by rank

The three moves Naughty gains by ranking up are one small table:

```lua
[--[[HASH:"uppercut_attack":0x2f4deb6e]]793635694]   = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_unlock_uppercut_attack":0x727b6376]]1920689014, lvl = 5 }, --this is link to the kick
[--[[HASH:"special_attack":0x46b76293]]1186423443]   = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_unlock_special_attack":0x18247869]]405043305, lvl = 10 },
[--[[HASH:"big_terrorize_attack":0x718468e7]]1904503015]   = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_unlock_big_terrorize":0xd530f849]]3576756297, lvl = 20 },        
```

*Interpretation:* `lvl` is the rank at which the move unlocks. Set the three
numbers to `1` to have them from the start.

## Weapons from ultra-kills

A comment in the script says the token "must absolutely be the name of the item
for ultra kills and stolen costumes". An ultra-kill rule looks like this:

```lua
[--[[HASH:"Animesword":0x68356540]]1748329792] 	= {unlockCondTxtID = --[[HASH:"unlockable_condition_ultrakill_knight":0x2c94dd37]]747953463, itemID = --[[HASH:"Animesword":0x68356540]]1748329792 },
```

*Interpretation:* the condition text name (`..._ultrakill_knight`) says which bear's ultra-kill
earns the Anime sword.

## Achievements

`rules_achievements` has the same shape. Trophies are counted by grade, and the
number of items bought or mastered is counted too. For the first trophy and the
purchase counts:

```lua
[--[[HASH:"achievement_First_Trophy":0x91266097]]2435211415]    = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_condition_missing":0xef3cfe39]]4013751865, minCountBronze = 1, minCountSilver = 1, minCountGold = 1, minCountPlatine = 1},
```

```lua
[--[[HASH:"achievement_PurchasedItems_1":0xd9a91b24]]3651738404]    = {canForceUnlock=false, unlockCondTxtID = --[[HASH:"unlockable_condition_missing":0xef3cfe39]]4013751865, minPurchasedItemsCount = 25},
```

The purchase counts are 25, 50, 100 and 200 items. One gold-count rule needs
`goldCount = 1000000`. The script also prints a line when one is earned:

```lua
	print("Achievement earned : " .. engine.GetAchievementHashName(aAchievementID))
```

`SetAchievementComplete` hands the achievement to the engine. *Interpretation:*
the engine passes it on to the console, which this page cannot test.

## How to change it

Change the number in a rule and Ship. Whole numbers only, no decimal point.
Keep to the kind of value the game already uses: PiP scripts hang when a value
is far outside its normal range (see
[PiP internals](../game-files.md)).

## Confirmed and not

* Confirmed in the scripts: the rule groups, their order, and the shape of each
  rule.
* *Interpretation:* that `lvl` is a rank, what `canForceUnlock` does (every rule
  here sets it to `false`), and which bear each ultra-kill name means.
* Checked in Seam Ripper: setting the uppercut to `lvl = 1` ships, the file
  reads back with only that line changed, and every record keeps its retail
  size. Not tested in the game; try that one first.
