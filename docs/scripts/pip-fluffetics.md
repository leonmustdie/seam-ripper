---
title: "PiP: Fluffetics"
parent: Panic in Paradise
grand_parent: Game reference
nav_order: 3
---

# PiP: Fluffetics (the profile upgrades)

*Fluffetics* is the developers' name for a set of upgrades kept on the
player's profile. The scripts ask the profile whether Naughty owns one, and
change what happens if he does. There are five, and each is one `if` line, so
each is a one-line mod.

## Where they live

The check is the same everywhere:

```lua
engine.HazingPlayerProfileManagerRef():GetFluffeticsCannotBeTrapped()
```

It answers true or false. The scripts below are copies in several containers
(`area01`, `area02`, and so on); the table says which script holds each check.

## The five

| Fluffetic | Script | What it changes |
|---|---|---|
| Rage effect after ultra-kill | `finishingmove` | An ultra-kill starts the glowing fists and the damage bonus. This is what the [Rage glow](../examples/rage-glow.md) example switches on for everyone |
| Contextual scare deals damage | `receivescareinteraction`, `receivetrapscareattack` | A scare also damages the bear |
| Cannot be trapped | `traptrigger` | Naughty doesn't get caught by traps |
| Traps cannot be escaped | `stuckintrap` | A bear stuck in a trap gets no release timer, so it stays stuck |
| Staggering effect when dodging | `basecharacterbodystatemachine` | Switches on a dodge-staggering mechanic during a dodge. *Interpretation:* from the name, a dodge staggers what it hits |

## What each one does in the script

**Rage effect.** After the ultra-kill has played:

```lua
        if engine.HazingPlayerProfileManagerRef():GetFluffeticsRageEffectAfterUltraKill() then
            DamageUpgradeActivated()
        end
```

`DamageUpgradeActivated` is in `naughtybearupgrades`. With no length given, it
uses `sFluffeticsRageEffectDuration`, a number the engine holds, not the
scripts.

**Contextual scare.** The damage is the bear's remaining health times a
coefficient:

```lua
	if engine.HazingPlayerProfileManagerRef():GetFluffeticsContextualScareDealsDamage() then
		local hero = engine.HazingPlayerManager_GetPlayerMainCharacterObject(0)
		local data = engine.HazingDamageData(GetCharacterDamageableComponent(npcMO):GetRemainingHitPoints() * engine.HazingPlayerProfileManager_sFluffeticsContextualScareDamageCoefficient)
```

The comment above it reads "If the player has purchased the upgrade", so these
are bought. *Interpretation:* the coefficient is a fraction, so the scare takes
that share of what the bear has left. Its value is in the engine.

**Cannot be trapped.**

```lua
    --If player own the Fluffetic Cannot Be Trapped don't trap him
    local heroCanBeTrapped = not engine.HazingPlayerProfileManagerRef():GetFluffeticsCannotBeTrapped()
```

**Traps cannot be escaped.** The release timer is only made when Naughty does
*not* own it:

```lua
    	if engine.HazingPlayerProfileManagerRef():GetFluffeticsTrapsCannotBeEscaped() == false then
        	StuckInTrap_ReleaseTimer = CreateTimer(StuckInTrap_ReleaseTimerDelay, __this__, "StuckInTrap_ReleaseTimer_End")
```

**Staggering dodge.** Turns the dodge-staggering mechanic on at the start of
the dodge, and the same check turns it off again at the end:

```lua
    if engine.HazingPlayerProfileManagerRef():GetFluffeticsStaggeringEffectWhenDodging() then
        GetMechanics():ActivateMechanic(engine.eMECHANIC_DODGESTAGGERING, true)
```

## How to change it

To give Naughty one without owning it, replace the check with `true`. For
cannot-be-trapped:

```lua
    local heroCanBeTrapped = not true
```

Do this in every copy of the script, as Ship offers when you edit one (see
[Scripts in several containers](../technical.md#scripts-in-several-containers)).
The Rage one is the same edit as in the example. For *traps cannot be
escaped*, which is tested the other way round (`== false`), use `true == false`
so the timer is never made.

## Confirmed and not

* Confirmed in the scripts: the five names, where each check is, and what each
  branch does.
* Tested in the game: only the rage effect (see the example).
* Not found: where the game sells or unlocks them, and their prices.
* The two numbers (rage duration and the scare coefficient) are set in the
  engine, so they cannot be changed from the scripts.
