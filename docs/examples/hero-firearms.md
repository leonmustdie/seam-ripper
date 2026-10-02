---
title: Hero firearms
parent: Examples
nav_order: 1
---

# Hero firearms

In Panic in Paradise Naughty can only smash guns. This patch lets him pick one
up and fire it, with a six-round clip that reloads after a short pause, and
lets him swing it with the attack buttons. It is four small edits in four
scripts, and nothing in it is a new system: the game already has the gun code,
and Naughty already has an input called Shoot.

[Download hero-firearms.srpatch](hero-firearms.srpatch){: .btn .btn-primary }

## What you get

* Walk up to a gun and the prompt is **Pick up**, not *Destroy item*.
* Fire it in whatever direction Naughty is facing. There is no crosshair.
* Single-shot guns (revolver, pistol, magnum) hold six rounds. The game's own
  clip is 36, which is why the patch sets it.
* After the last round there is a 1.5 second pause, then the gun is full again.
  There is no reload animation.
* The light and heavy attack buttons swing the gun with the Chef's knife
  moves.
* An ultra-kill with a gun in hand plays one of that gun's executions.
* Shotguns and automatic rifles work too, but Naughty holds every gun
  one-handed, like a pistol.

## How the game decides

Guns are scripts like everything else. A gun on the ground uses
`pickupsmallhandobject`. Two lines show how it treats Naughty and everyone
else:

```lua
    if  isObjectLongRange then
        pickupSmallHandObjDef:AddInteractionAlias("Pickup_AI")
        pickupSmallHandObjDef:AddInteractionAlias("Destroy_NB")
```

A gun is "long range". Bears get the pickup prompt; Naughty gets *Destroy*.
Later, when the interaction runs, a second check sends Naughty down a smash
branch instead of a pickup:

```lua
    if  isObjectLongRange and isInteractorHero then
        pExecutorPointer:SkipToInteractionEnd()
        if  GetBreakableComponent(__this__)~= nil then
            GetBreakableComponent(__this__):Break()
```

## The four edits

**1. Pick it up** (`levelcommon` → `pickupsmallhandobject`). The prompt becomes
*Pickup*, and the two "smash it" branches are switched off with `if false`.
After the normal pickup, the clip is set:

```diff
+GUN_CLIP_SIZE = 6   -- rounds in a revolver-type gun (the game's own number is 36)
 ...
-        pickupSmallHandObjDef:AddInteractionAlias("Destroy_NB")
+        pickupSmallHandObjDef:AddInteractionAlias("Pickup")
 ...
-    if  isObjectLongRange and isInteractorHero then
+    if false then
 ...
     OnPickup(pSourceObj)
+    if isObjectLongRange and isInteractorHero then
+        local c = GetLongRangeCombatComponent(__this__)
+        if c:GetFirearmType() == engine.LongRangeCombatComponent_eSINGLE_SHOT then
+            c:SetAmmoCapacity(GUN_CLIP_SIZE)
+            if c:GetNumberOfBullet() > GUN_CLIP_SIZE then c:SetNumberOfBullet(GUN_CLIP_SIZE) end
+        end
+    end
```

(`false` appears twice in the real patch, once in each branch.) *Interpretation:*
the game gives a gun its ammo from its own data when it is made, so the patch
trims it after the pickup instead of editing every gun.

**2. Reload** (`skinnaughty` → `naughtybearadditivestatemachine`). This is the
state that plays the shoot animation. After each shot, if the gun is empty,
wait and call the gun's own reload:

```diff
+GUN_RELOAD_SECONDS = 1.5   -- pause after the last round; 0 = never reload
 ...
     bodyAnimMgr:PlayAdditiveAnimState(GetFirearmShootAnim(), shootAnimationSpeed)
+    if GUN_RELOAD_SECONDS > 0 then
+        local ok, bullets = pcall(function() return currentLongRangeCombatComponent:GetNumberOfBullet() end)
+        if ok and bullets <= 0 then
+            threads.WaitForTime(__this__, GUN_RELOAD_SECONDS)
+            CallFunctionOnGameObject(GetCharacterComponent(__this__):GetRightHandModeledObject(), 'OnReload')
+        end
+    end
```

`OnReload` is the gun script's own function (`longrangemethods`). It refills
the gun to its capacity. Waiting inside the shoot state is what produces the
pause: Naughty can't fire until it ends. `pcall` runs the bullet check so a
missing value can't stop the script.

**3. Swing it** (`skinnaughty` → `basecharacterbodystatemachine`).
`GetAttackAnimation` picks the attack by the weapon in hand, and skips guns,
so Naughty punches. A second case sends a gun to a chosen set of attacks:

```diff
+GUN_SWING_TYPE = --[[HASH:"Pointy":0xc76f6737]]3345966903   -- attack set for swinging a gun: Pointy (knife), Slash, Smash or Bash
 ...
+    if pCharacterComponent:IsRightHandHoldingObject() and IsLongRangeWeapon(pCharacterComponent:GetRightHandModeledObject()) then
+        local set = attackAnimList[GUN_SWING_TYPE]
+        if set and set[combatMove] then return set[combatMove] end
+    end
     return attackAnimList[--[[HASH:"NoWpn":0x57ee9218]]1475252760][combatMove]
```

`attackAnimList` holds the attack animations for each kind of weapon. The
Chef's knife uses the *Pointy* set. The other sets are *Slash*, *Smash* and
*Bash*. Their numbers are in the script, next to `Pointy`'s: Slash `130959345`,
Smash `3211927700`, Bash `3188032220`.

**4. Execute with it** (`levelcommon` → `libraryweapon`). When Naughty makes an
ultra-kill, this script picks the animation from the weapon he is holding.
*Interpretation:* a gun held by a *bear* is flagged with a resource number
`0`, and a gun held by Naughty is not. One line makes them the same:

```diff
         rightHandObjectHashedName = rightHandObject:GetGODHashedName()
         animationResourceName = nil
+        if IsLongRangeWeapon(rightHandObject) then animationResourceName = 0 end   -- same as a gun held by a bear
```

## Change it

* `GUN_CLIP_SIZE`: rounds in a revolver-type gun. It does not apply to shotguns
  or automatic rifles.
* `GUN_RELOAD_SECONDS`: the reload pause. `0` means never reload: the gun stays
  empty until you put it down and pick it up again.
* `GUN_SWING_TYPE`: swap the number for another attack set.
* To bring the smash back for one kind of gun, give that gun its own check in
  the `if false then` branches.

## Limits

* No crosshair. The game has reticle functions, but no script calls them.
* No reload animation. It is a pause.
* One-handed. Shotguns and rifles are held like pistols.
* Ultra-kills with a gun in hand play the gun's execution, but the victim does
  not always finish the second half of the animation. On our test bears in the
  beta's Collision Zoo the victim hung in the air; on story bears it was fine.

## Checked

The patch is made from the retail files and was played on retail Panic in
Paradise in Xenia: Cuddles and Goober load and play, and the
guns work as described above. It was first developed on the June 26th, 2012
beta, where the ultra-kill limit above was seen. Of the five scripts the two
examples edit, four are word for word the same in the beta; `libraryweapon`
differs by one line (for a weapon Naughty holds, retail passes `nil` where the
beta passes the weapon's hash).

It is very strong. *Interpretation:* a gun that kills from across the room is
a likely reason the developers took the feature out. Treat it as a toy to build on, and lower
`GUN_CLIP_SIZE` or raise `GUN_RELOAD_SECONDS` if you want it fair.

## More

* [Rage glow](rage-glow.md): another small mod on the same scripts.
* [PiP: June 26th Beta Discoveries](../pip-june26-beta.md): where the testing
  was done, and what else is in the beta.
