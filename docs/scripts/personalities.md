---
title: Bear personalities
parent: Naughty Bear
grand_parent: Game reference
nav_order: 5
---

# Bear personalities

Every bear in *Naughty Bear* has a personality, one of **Jock**, **Cheerleader**,
**Threat** or **Smart**. It is a short list of numbers, and it is one of the
smallest scripts in the game.

## Where it lives

`global.lu` → `characterclasses`. There is one copy. Which personality a bear
has is set in its `NPCDef` line (third value; see [Bear stats](bear-stats.md)).

## What it does

Each personality is a function that fills in a small table. Jock, in full:

```lua
function ClassBuilder.InitJock(p1)
  local t = {}
  t[CHARACTER_CLASS] = JOCK
  t[STATE_COURAGE] = HIGH
  t[STATE_USEFIREARM] = true
  t[STATE_MORAL] = LOW
  t[STATE_ATTACK_CHARGED] = true
  t[STATE_WANT_TO_FIGHT] = true
  t[ATTRIBUTE_INTELLIGENCE] = LOW
  return t
end
```

The levels are plain numbers, set at the top of the script:

```lua
VERY_HIGH = 5
HIGH = 4
NORMAL = 3
LOW = 2
VERY_LOW = 1
```

## The values

Read from each `Init...` function:

| Personality | Courage | Moral | Intelligence | Bears in the base game |
|---|---|---|---|---|
| Jock | HIGH | LOW | LOW | 36 |
| Cheerleader | LOW | LOW | LOW | 19 |
| Threat | VERY_HIGH | VERY_LOW | NORMAL | 50 |
| Smart | LOW | LOW | VERY_HIGH | 11 |
| Fearless | HIGH | HIGH | NORMAL | 0 |

Every personality also sets `UseFirearm`, `AttackCharged` and `WantToFight` to
`true`. The bear counts are the `NPCDef` lines in `naughtyisland_npcs`.
Fearless has a function but no bear in that script uses it.

After the table is built, `InitNPCClass` adds the bear's faction, name,
leadership and threat level to it, then attaches it to the bear:

```lua
    v2[CHARACTER_FACTION] = p1.factionName
    v2[CHARACTER_NAME] = p1.name
    v2[ATTRIBUTE_LEADERSHIP] = p1.leadershipValue
    v2[ATTRIBUTE_THREAT_LEVEL] = p1.threatLevel
    p1:AddAttributes(v2)
```

## What the numbers do

The scripts only *store* these values. `NPC.GenerateAttribute` turns each one
into an attribute on the bear (courage, moral, intelligence and leadership as
whole numbers, the rest as yes/no), and one helper,
`GetSourceIntelligenceAttribute`, reads intelligence back. The behaviour
that uses courage and moral is not in the scripts. *Interpretation:* the engine's
AI reads them, which fits the names (a high-courage bear is slower to flee), but
that is a reading of the names and nothing here shows it.

## How to change it

Change a level in one of the `Init...` functions and Ship. Use the names
(`VERY_LOW` to `VERY_HIGH`) or the numbers 1 to 5. For example, to make Smart
bears as brave as Jocks, change `t[STATE_COURAGE] = LOW` to `HIGH` in
`InitSmart`. It affects every bear of that personality at once.

Keep to 1 to 5; the scripts never use a value outside them.

## Confirmed and not

* Confirmed: the five personalities, their values, how many bears use each, and
  where the table is attached.
* *Interpretation:* what the AI does with courage, moral and intelligence.
* Not tested in the game: any change on this page.
