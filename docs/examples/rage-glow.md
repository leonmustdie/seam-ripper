---
title: Rage glow
parent: Examples
nav_order: 2
---

# Rage glow

Every ultra-kill makes Naughty's fists glow and hit harder for a few seconds.
One short edit, which makes it a good first mod to read.

[Download rage-glow.srpatch](rage-glow.srpatch){: .btn .btn-primary }

## Where it comes from

Panic in Paradise had a rage mode, a meter that fills as you fight. The game
still has the code that listens for it, but it was switched off. The comments
say so:

```lua
    -- Pause rage mode  -- NO more rage mode for NB2
    --GetCharacterRageModeComponent(pAttackingCharacter):PauseRageModeTimer()
```

We could not bring the meter back: Naughty has no rage component in his data,
in any build we looked at. But one piece of it survives as a *Fluffetic*, a
perk on the player's profile. In `finishingmove` (the script that plays
ultra-kills), the last lines of an ultra-kill ask the profile whether the perk
is on:

```lua
        if engine.HazingPlayerProfileManagerRef():GetFluffeticsRageEffectAfterUltraKill() then
            DamageUpgradeActivated()
        end
```

`DamageUpgradeActivated` is in `naughtybearupgrades`. It does three things:

```lua
        pCharacterComponent:SetCloseRangeDamageModifier(500)
        pCharacterComponent:SetLongRangeDamageModifier(500)
        ...
        pCharacterComponent:StartEmitter(--[[HASH:"RageFistL":0x3b89ceb6]]998887094)
        pCharacterComponent:StartEmitter(--[[HASH:"RageFistR":0xc186f3d5]]3246846933)
```

*Interpretation:* the two modifiers are percentages, so 500 is five times the
normal damage, for melee and guns. The two emitters are the glow on each fist.
A timer then switches it all off; the length comes from the profile unless the
caller passes one. The line that played a rage sound is commented out.

## The change

`skinnaughty` → `finishingmove`:

```diff
+RAGE_SECONDS = 10   -- how long the glow and the bonus damage last
 local pFinishingMoveExecutorPointer = nil
 ...
-        if engine.HazingPlayerProfileManagerRef():GetFluffeticsRageEffectAfterUltraKill() then
-            DamageUpgradeActivated()
+        if true then   -- was: only with the Fluffetic that unlocks it
+            DamageUpgradeActivated(RAGE_SECONDS)
         end
```

The check is replaced with `true`, so the effect always happens, and the
length is passed in as a number instead of taken from the profile.

## Change it

* `RAGE_SECONDS`: how long the effect lasts.
* The bonus is the `500` in `DamageUpgradeActivated`, in `naughtybearupgrades`.
  Changing it means another edit, in another script.

## Checked

* The glowing fists show after an ultra-kill, in the June 26th beta and in
  retail Panic in Paradise (played in Xenia).
* We did not measure the damage bonus or hear any sound. The sound line is
  commented out in the game.
* The bonus is large, which is a likely reason it was an unlock and not
  always on. Lower `RAGE_SECONDS` to make it a short burst.
