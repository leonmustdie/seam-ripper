---
title: Traps and sabotage
parent: Naughty Bear
grand_parent: Game reference
nav_order: 7
---

# Traps and sabotage

*Naughty Bear.* Bear traps, landmines, the barbecue, the radio and the toilet
are all *objects* with scripts. A trap catches a bear and hurts it; sabotage
lets Naughty spoil an object so a bear who finds it gets scared. The scripts are
long, but the numbers that matter are few and easy to find.

## Where they live

Each object has its own container (`beartrap.lu`, `bbq.lu`, `radio.lu`,
`toilet.lu`, `landmine`...) holding one script for the object, and one more for
each thing you can do to it:

* `beartraptrigger`: what happens when something steps on the trap.
* `beartrap_doscareattack`, `beartrap_receivestealthkill` and so on: the scare
  and stealth-kill interactions, from either side.
* `bbq_sabotage`, `bbq_repair`, `bbq_getfood`: the barbecue's own interactions.

## The bear trap

When something steps on a set trap, `OnTrapTriggerEnter` checks that it is
allowed to catch it:

```lua
    if trapSetAttribute:GetValue() == true and value ~= true and not fetchBool2:GetValue() and isInvulnerable == false then
      local modeledObject = GetModeledObject(__this__)
      trapSetAttribute:SetValue(false)
      v2 = --[[HASH:"ST_TrapIn"]]0x085f7575
      PlayAnim(modeledObject, v2, 0.0, 1.0)
      TrapCharacter(p1, modeledObject, hazingObjectDescriptor, objectDescriptor, stateAttributes)
```

*Interpretation:* the four tests are that the trap is set, the victim is not
already stuck in a trap, not knocked down, and not invulnerable. When the jaws
close, the damage is a third of what the victim has left:

```lua
    local hazingDamageData = engine.HazingDamageData(GetComponent(pTrapVictimCharacterMO, "Character Component"):GetRemainingHitPoints() / 3)
```

When the victim is a bear (not Naughty), it also screams and frightens the
others. `TrapCharacter` plays a scream, applies the bear-trap fear, and sends an
AI sound that the other bears hear:

```lua
    GenerateFearEvent(pTrapVictimCharacterMO)
    GenerateAISoundEvent(pTrapVictimCharacterMO)
```

How much fear that gives is not in this script. It is the line
`self:AddFear(FEAR_BEAR_TRAP, FEARTYPE_AGGRESSION, 100.0, 80.0, 60.0, 50.0, 25.0, false)`
in `global.lu` → `npc`, covered on [NPC fear](npc-fear.md).

*Interpretation:* the one who set the trap can't spring it for three seconds.
The trigger test skips the character stored by this function until its timer
ends:

```lua
function StartTrapOwnerDelay(p1)
  local timer = CreateTimer(3, __this__, "EnableTrapEverybody")
  timer:Start()
  v = p1
end
```

## Sabotage

Sabotage is an *interaction*: a set of callbacks that run when Naughty uses the
object. The barbecue's is typical. Only Naughty may do it, and only if the object
is not already destroyed or sabotaged:

```lua
function bbq_Sabotage_ValidateRights(p1)
  return GetComponent(p1, "HazingObjectDescriptor"):GetObjectDescriptor():IsType(TYPE_HERO)
end
```

When the animation reaches its `SABOTAGE` moment, the script marks the object,
scores, makes it scary, and tells the bears:

```lua
    ApplyScoreEvent(SCORE_DISABLE_BBQ)
    local fearGeneratorComponent = GetComponent(__this__, "Fear generator Component")
    fearGeneratorComponent:ActivateFearEvent(FEAR_SEEDISABLED_BBQ)
    Sabotaged = true
    ...
    GetComponent(__this__, "MultiInteraction"):SetDefaultInteraction("Repair")
    engine.ThreatSabotageMsg_SendBroadcastMsg(GetModeledObject(v2))
```

So a sabotaged object gives points ([Scoring](scoring.md)), frightens any bear
that sees it (`FEAR_SEEDISABLED_BBQ`, "discovers a burning barbecue"), and then
offers *Repair* in place of *Sabotage*. The broadcast is how the game's threat
system learns that Naughty has been up to something.

## How to change it

* **Trap damage:** the `/ 3` in `beartraptrigger`. Use a whole number: `/ 2`
  takes half of what the victim has left, `/ 1` all of it.
* **Owner delay:** the `3` in `CreateTimer(3, ...)`.
* **What a sabotage is worth or how scary it is:** not in the object script. The
  score is the `SCORE_...` entry in the score tables, and the fear is the
  matching `FEAR_...` entry in `npc`; see [Scoring](scoring.md) and
  [NPC fear](npc-fear.md).

## Confirmed and not

* Confirmed in the scripts: the trigger test, the `/ 3` damage, the three-second
  delay, the sabotage steps, and where the fear lines are.
* *Interpretation:* the plain-English reading of the trigger test.
* Checked in Seam Ripper: changing `/ 3` to `/ 2` in `beartraptrigger` ships, and the file reads back with only that line changed. Not tested in the game.
