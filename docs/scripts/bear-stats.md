---
title: Bear stats
parent: Script reference
nav_order: 2
---

# Bear stats: health, fear, weapons

Every named bear on the island is defined by one line. Changing that line
changes the bear's health, how much fear it can take, what it carries and more.

## Where it lives

| Container | Script | What's in it |
|---|---|---|
| `naughtyisland.lu` | `naughtyisland_npcs` | The main list: one `NPCDef(...)` line per bear |
| `global.lu` | `npc` | `NPCDef` itself, which says what each value means |
| episode and challenge containers | `*_npcs` (e.g. `ep1challenge4.lu` → `ep1cha4_npcs`) | Changes to the main list for that level only |

## One bear, value by value

```lua
CHUBBY = NPCDef("Chubby", --[[HASH:"npc_names_Chubby" TEXT:"Chubby"]]0xf676deae, JOCK, 0, FACTION_NORMAL_BEAR_HASH, 50, false, {1.0, 0.52, 0}, 135, 1500, 1.5, {0.4, 0.7, 1.0}, NORMALBEAR1_SOUNDSUFFIX, "")
```

In order (names from `NPCDef` in `global.lu`):

| # | Value | Chubby | Meaning |
|---|---|---|---|
| 1 | name | `"Chubby"` | Internal name |
| 2 | xtxtUID | `0xf676deae` | Name shown in game |
| 3 | class | `JOCK` | Personality: `JOCK`, `SMART`, `CHEERLEADER` or `THREAT` |
| 4 | threatLevel | `0` | How dangerous the bear counts as |
| 5 | faction | `FACTION_NORMAL_BEAR_HASH` | Which group it belongs to |
| 6 | leadership | `50` | *Interpretation:* how much other bears follow it |
| 7 | isaboss | `false` | Boss flag |
| 8 | color | `{1.0, 0.52, 0}` | Fur colour, red/green/blue from 0 to 1 |
| 9 | maxHP | `135` | Health |
| 10 | maxFearLevel | `1500` | How much fear it can take (see [NPC fear](npc-fear.md)) |
| 11 | shootingSpeed | `1.5` | *Interpretation:* time between shots, so lower is faster |
| 12 | fearThresholds | `{0.4, 0.7, 1.0}` | Fear stages (see [NPC fear](npc-fear.md)) |
| 13 | soundSuffix | `NORMALBEAR1_SOUNDSUFFIX` | Which voice it uses |
| 14 | startingWeaponName | `""` | Weapon it starts with (`""` = none) |
| 15 | startingAccessoriesList | *(not given)* | Hats and other items it starts with (see the example below) |

## Typical values

| Bears | Health | Max fear | Weapon |
|---|---|---|---|
| Normal bears: cheerleader / smart / jock | 90 / 112 / 135 | 1500 | none |
| Cops (Cop Gordon) | 180 (270) | 1750 | `revolver` |
| Ninjas (Master Miyagi) | 135 (225) | 1750 (2250) | `ninjato01` |
| Army (Colonel Ketchup) | 270–315 (360) | 2250–2500 (2750) | `revolver`, `uzi01` |
| Zombears (Oodoo) | 270 (1000) | 1750 (3000) | `bone01`, `branch01a` (`machete`) |
| Robots (R0B0-PR1M3) | 315 (405) | 2250 (3000) | `powerfist` |
| Aliens (Emperor Xoon) | 135 (225) | 2250 (3000) | `raygun01` |
| B.E.A.R. (Mahoney) | 270–315 (360) | 2250 | `silentpistol` |
| The Unibear | 10 | 100 | none |

## Per-level changes

Episode and challenge levels change bears with plain assignments after the
main list. From `ep1cha4_npcs`:

{% raw %}
```lua
COPCURLY.startingAccessoriesList = {{"tophat", "joint_Head"}}
COPCURLY.startingWeaponName = "raygun01"
COPCURLY.maxFearLevel = 3500
COPCURLY.maxHP = 360
COPCURLY.shootingSpeed = 1.0
COPCURLY.longRangeDamageModifier = 125
COPCURLY.closeRangeDamageModifier = 125
```
{% endraw %}

`closeRangeDamageModifier` and `longRangeDamageModifier` are the bear's own
melee and gun damage, the same as on [Naughty's hats](hats.md).

## How to change it

* **One bear everywhere:** edit its `NPCDef` line in `naughtyisland_npcs`.
  Values are read by position, so change them in place and don't add or
  remove any.
* **One level only:** edit or add a `BEARNAME.field = value` line in that
  level's `*_npcs` script. A level's own value wins over the main list there.
* Whole numbers (`maxHP`, `maxFearLevel`) stay whole; values written with a
  decimal point (`shootingSpeed`, colours) keep one. See
  [Numbers](../technical.md#numbers).
* Weapon and hat names must be ones the game already uses; they are listed in
  the tables above and in the `*_npcs` scripts.
