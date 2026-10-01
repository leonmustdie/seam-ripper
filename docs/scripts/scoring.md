---
title: Scoring
parent: Script reference
nav_order: 3
---

# Scoring: points and the combo multiplier

Most of the big point awards and the whole combo multiplier ladder are set in
scripts, so they are easy to change.

## Where it lives

| Container | Script | What's in it |
|---|---|---|
| `global.lu` | `scoremanager` | The combo multiplier ladder and score settings (17 lines) |
| `naughtyisland.lu` | `naughtyisland_npcbase` | Points for driving a bear insane, by bear type |
| `naughtyisland.lu` | `librarygameevents` | Bonuses for clearing a zone or the whole level |
| each bear's container (e.g. `copbear.lu`) | `finishingscare` | Points when an insane bear finishes itself off |
| episode and challenge containers | `*_rules` | Objective, gate and bridge bonuses |

*Interpretation:* the everyday points for hits, kills and scares were not
found in the scripts and look like they come from the game's data instead.

## The combo multiplier

All of `scoremanager`'s ladder:

```lua
engine.HazingScoreMgr_AddCombo(1, 0.0, 2.0)
engine.HazingScoreMgr_AddCombo(2.0, 50.0, 2.0)
engine.HazingScoreMgr_AddCombo(5, 150.0, 6.0)
engine.HazingScoreMgr_AddCombo(10, 350.0, 12.0)
engine.HazingScoreMgr_AddCombo(25, 650.0, 20.0)
engine.HazingScoreMgr_AddCombo(50.0, 1050.0, 50.0)
engine.HazingScoreMgr_AddCombo(75, 1550.0, 80.0)
engine.HazingScoreMgr_AddCombo(100, 2050.0, 100)
engine.HazingScoreMgr_SetMaxComboScore(2550.0)
```

*Interpretation:* each line is one step of the ladder. The first value is the
multiplier (x1 to x100), the second is the combo score needed to reach it, and
`SetMaxComboScore` is the top of the bar. What the third value does is not
known yet.

## Points for driving a bear insane

From `NaughtyIsland_NPCBase:FearStateChangedCB`, one of its twelve cases:

```lua
    elseif self.factionName == FACTION_COP_BEAR_HASH then
      engine.HazingScoreMgr_AddScoreWithComboSettings(SCORE_GROUP_ACTION, SCORE_INSANE_COP, SCORECATEGORY_PLAYER, 2000.0, false, false)
```

The fourth value is the points. All of them:

| Bears | Points |
|---|---|
| Normal bears | 1000 |
| Cops, ninjas, zombears, pirates | 2000 |
| Army, aliens, robots, B.E.A.R., vampires, danger bears | 3000 |
| The Unibear | 25000 |

## Other awards

| What | Points | Script |
|---|---|---|
| An insane bear finishes itself off | 500 | `finishingscare` |
| Every bear in a zone killed / driven insane | 5000 | `librarygameevents` |
| Every bear in the level killed / driven insane | 50000 | `librarygameevents` |
| Every collectible destroyed | 25000 | `librarygameevents` |
| Objective complete, or a zone's collectibles cleared | 10000 | `*_rules` |
| Gate or bridge opened | 1000 | `*_rules` |
| Health pickup, power pill | 100 | the pickup's own script |

## How to change it

Change the number and Ship. Keep the decimal point where the game has one
(`2000.0`), since that is how NB1 tells a decimal number from a whole one
(see [Numbers](../technical.md#numbers)).

* `finishingscare` is a separate copy in every bear's container. Ship lists
  them all; tick every one you want changed.
* The `*_rules` scripts are per level, so a change there only affects that
  level.
