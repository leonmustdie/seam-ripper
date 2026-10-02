---
title: Weapons and pickups
parent: Naughty Bear
grand_parent: Game reference
nav_order: 8
---

# Weapons and pickups

*Naughty Bear.* Every weapon and trap Naughty can hold shares one script, which
handles picking it up, carrying it and dropping it. What it does *not* contain
is how hard a weapon hits: that is not in the scripts.

## Where it lives

`weaponmethods`. It is the same script in 58 containers, one for each weapon,
trap and a few cutscenes (`baseballbat.lu`, `beartrap.lu`, `bone.lu`,
`branch.lu`, `campfire.lu`, `cricketbat.lu`, `crowbar.lu`...). Ship offers to
change all the identical copies when you edit one, so leave them ticked (see
[Scripts in several containers](../technical.md#scripts-in-several-containers)).

It has six functions:

| Function | What it does |
|---|---|
| `AttachWeaponToChar` | Puts the weapon in a character's hand |
| `OnPickup` | Runs when a character picks it up |
| `OnDrop` | Runs when it is dropped or let go |
| `weaponOwner_OnCorpseOnGround` | Drops it when its owner dies |
| `TutorialManagement` | Shows a tutorial prompt the first time you pick one up |
| `UnSpawnWeaponTimerEnded` | Removes an unclaimed weapon (multiplayer) |

## Picking up

`OnPickup` attaches the weapon, plays a sound when the hero picks it up, and
records the character as the owner of the pickup:

```lua
  AttachWeaponToChar(modeledObject, p1, p2)
  ...
  if objectDescriptor:IsType(TYPE_HERO) then
    soundManager = engine.SoundManagerManipulator()
    GetModeledObject(__this__):GetSoundManager(soundManager)
    soundManager:PlayFX(--[[HASH:"FX_Weapon"]]0xbba9f9be)
  end
```

## Dropping

When a weapon is dropped it is put back on the ground, turned upright, and made
glow so you can see it:

```lua
    modeledObject:SetExposedShaderValues1("GlowEnable", 1)
    modeledObject:SetExposedShaderValues1("strength", 2.0)
```

`strength` here is the brightness of that glow, a graphics value. It is not
damage, despite the name. Its damage zone is switched off on drop:

```lua
      local primitiveManipulator = engine.PrimitiveManipulator()
      modeledObject:GetPrimitive(primitiveManipulator, "damage")
      ...
      primitiveManipulator:SetActive(false)
```

*Interpretation:* each weapon's model has a "damage" shape, a hit area that is
switched on while it is swung and off while it lies on the ground. How much it
hurts is stored with the weapon's data, not here.

## Guns run out

A firearm with no bullets left disappears when dropped:

```lua
    if IsLongRangeWeapon(modeledObject) and not IsfirearmHaveBullets(modeledObject) then
      GetComponent(modeledObject, "MultiTrigger"):SetTriggerEnabled(false)
      modeledObject:SetEnabled(false)
    end
```

## Multiplayer

In multiplayer, a weapon that came from a spawner and was dropped is removed
after 15 seconds if nobody has picked it up:

```lua
        v7 = CreateTimer(15, modeledObject, "UnSpawnWeaponTimerEnded")
```

The golden gun is special-cased by name (`goldengun`) in multiplayer, with its
own sound and a "someone has the gun" message.

## How to change it

* **How bright a dropped weapon glows:** the `2.0` after `"strength"`.
* **How long a weapon stays in multiplayer:** the `15` in `CreateTimer(15, ...)`.
* **What a weapon does when you pick it up or drop it:** the six functions
  above. Change them in every copy.

Weapon damage, speed and the list of weapons are not here. For which weapon each
bear carries, see [Bear stats](bear-stats.md).

## Confirmed and not

* Confirmed in the script: the six functions, the glow lines, the empty-gun
  rule and the 15 second timer.
* *Interpretation:* what the `damage` shape is for.
* Not found: where weapon damage is stored.
* Not tested in the game: any change on this page.
