---
title: Naughty's hats
parent: Script reference
grand_parent: Game reference
nav_order: 1
---

# Naughty's hats: health and damage

Each hat changes Naughty's health and how hard he hits. All of it is in one
short script, so this is one of the easiest things to mod.

## Where it lives

`naughtybear.lu` → `naughtybearhatbonus`. The same script is also in
`cutscene_tophat_endings.lu` and `ep6endingcutscene.lu`; Ship offers to change
all three copies, so leave them ticked.

## What it does

When a level starts, the script checks which hat Naughty is wearing and sets
four values for it. One hat, as it appears in the script:

```lua
  elseif hashName == --[[TEXT:"Hat: Adept Naughty"]]0x64b5d953 then
    characterComponent:SetBaseHitPoints(250)
    characterComponent:SetRemainingHitPoints(250)
    characterComponent:SetCloseRangeDamageModifier(150)
    characterComponent:SetLongRangeDamageModifier(100)
```

* **SetBaseHitPoints**: Naughty's maximum health.
* **SetRemainingHitPoints**: the health he starts the level with. Keep it the
  same as the maximum.
* **SetCloseRangeDamageModifier**: melee damage. *Interpretation:* a
  percentage, so 100 is normal and 150 is half as much again.
* **SetLongRangeDamageModifier**: the same for guns.

## The values

| Hat | Health | Melee | Guns |
|---|---|---|---|
| Naughty the Party Animal | 300 | 125 | 100 |
| Mayor Naughty | 300 | 110 | 110 |
| Peacekeeper Naughty | 325 | 100 | 110 |
| Cordon Bleu Naughty | 350 | 100 | 100 |
| Prospector Naughty | 300 | 100 | 125 |
| Doc Naughty | 300 | 100 | 125 |
| Conspiracy Naughty | 325 | 110 | 100 |
| Cop Naughty | 325 | 100 | 125 |
| Adept Naughty | 250 | 150 | 100 |
| General Naughty | 325 | 110 | 110 |
| Zombie hat (`costume_hat_zombiehat`) | 350 | 110 | 100 |
| Tactical Naughty | 325 | 110 | 125 |
| Tech-Naughty | 300 | 125 | 110 |
| Astro-Naughty | 250 | 100 | 150 |
| Epic Naughty | 400 | 125 | 125 |

The Party Animal hat appears in the script as the plain number `139358`
rather than a hex hash; it is the same kind of value. Hats not in this list
don't change anything here. With no hat, the script only prints
`PLAYER IS NOT WEARING ANY ACCESSORIES` to the log.

## How to change it

Change the numbers for the hat you want and Ship. Write them as whole
numbers, without a decimal point. For example, to give the Adept hat 400
health, change both `250`s under Adept Naughty to `400`.

Keep values in the same range as the game's own. Panic in Paradise hangs when
a costume's health is set far above its real ceiling (see
[PiP weapons and outfits](pip-weapons-and-outfits.md)), and NB1 hasn't been tested with extreme values.
