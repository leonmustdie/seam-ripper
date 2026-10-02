---
title: NPC fear
parent: Script reference
grand_parent: Game reference
nav_order: 4
---

# NPC fear: how bears react to Naughty

Bears don't watch Naughty directly. Every bear has a **fear component** that
holds its fear level, and a **fear generator** that gives off fear events for
other bears to pick up. Being hit, seeing another bear get hit or hurt, and
seeing a kill all go through this one system.

## Where it lives

| Container | Script | What's in it |
|---|---|---|
| `global.lu` | `globaldictionnary` | The fear event constants (`FEAR_ATTACKED`, `FEAR_WIT_ATTACKED`, ...) |
| `global.lu` | `npc` | `NPC:AddFear`, `NPC:InitFears` (the fear table), `NPC:InitFearEvents`, threshold setters |
| `naughtyisland.lu` | `naughtyisland_npcbase` | What a bear does when it's hit (`HealthChangedCB`) or dies (`DeathCB`); applies each bear's thresholds |
| `naughtyisland.lu` | `naughtyisland_npcs` | Per-bear definitions (`NPCDef`), including max fear and thresholds |

Episode and challenge containers carry their own `*_npcs` definitions (for
example `ep10story.lu` → `ep10story_npcs`) with different values for the same
bears.

## Fear events

Each event is a hashed name. The `TEXT` is the game's own debug description
(`demo_fearevent_*` strings). From `globaldictionnary` (selected lines):

```lua
FEAR_TORMENTOR = --[[HASH:"demo_fearevent_see_tormentor" TEXT:"sees Naughty!"]]0x972502d2
FEAR_WITNESS_KILL = --[[HASH:"demo_fearevent_witness_kill" TEXT:"witnesses a Bear being killed!!!"]]0xfedbeab9
FEAR_ATTACKED = --[[HASH:"demo_fearevent_attacked" TEXT:"is attacked!"]]0x538405ab
FEAR_WIT_ATTACKED = --[[HASH:"demo_fearevent_witness_attacked" TEXT:"witnesses an attacked Bear!"]]0x621aabbb
FEAR_WIT_INJURED = --[[HASH:"demo_fearevent_witness_injured" TEXT:"witnesses an injured Bear!"]]0xadb546f0
```

"Tormentor" is the scripts' word for Naughty.

## What happens when Naughty hits a bear

`naughtyisland_npcbase`, complete function:

```lua
function NaughtyIsland_NPCBase:HealthChangedCB()
  local message = self.healthChangedMsgListener:GetMessage()
  if not message:IsDamaging() then
    return
  end
  local damageData = message:GetDamageData()
  if self.className == CHEERLEADER or self.className == SMART then
    local generateAttribute = self:GenerateAttribute(STATE_ATTACK_CHARGED, false)
    self.objectDescriptor:SetVisibleAttribute(generateAttribute)
  end
  local fearGeneratorComponent = GetComponent(self.gameObjectEnvironment, "Fear generator Component")
  local fearComponent = GetComponent(self.gameObjectEnvironment, "Fear Component")
  if GetCharacterModelAttributes(self.gameObjectEnvironment):IsInjured() and self.isInjured == false then
    local modeledObject = GetModeledObject(self.gameObjectEnvironment)
    self.isInjured = true
    fearGeneratorComponent:ActivateFearEvent(FEAR_WIT_INJURED)
    local fearInjured = engine.FearEvent_Create(FEAR_INJURED, true, 0.0, nil)
    fearComponent:ApplyFearEvent(fearInjured)
    local soundManagerManipulator = engine.SoundManagerManipulator()
    modeledObject:GetSoundManager(soundManagerManipulator)
    GlobalPlayCustomSound("VO_SCARED_SCREAM", soundManagerManipulator, self.soundSuffix)
  end
  if damageData ~= nil and damageData:GetDamageType() ~= DAMAGE_TYPE_TRAP then
    fearGeneratorComponent:ActivateFearEvent(FEAR_WIT_ATTACKED)
    local fearAttacked = engine.FearEvent_Create(FEAR_ATTACKED, true, 0.0, nil)
    fearComponent:ApplyFearEvent(fearAttacked)
    local attacker = damageData:GetAttacker()
    if attacker ~= nil then
      AchievementUsedWeapon(attacker)
    end
  end
end
```

Confirmed, step by step:

1. Only damaging messages count.
2. The first time the bear becomes injured, its generator switches on
   `FEAR_WIT_INJURED`, the bear applies `FEAR_INJURED` to itself, and it plays
   `VO_SCARED_SCREAM`.
3. Any hit that isn't trap damage switches on `FEAR_WIT_ATTACKED` on the
   victim's generator and applies `FEAR_ATTACKED` to the victim.
4. Cheerleader and Smart class bears also lose their "attack charged" state
   when hit.

When the bear dies, `DeathCB` in the same script switches its generator from
`FEAR_WIT_INJURED` to `FEAR_WITNESS_KILL`.

`NPC:InitFearEvents` in `npc` registers these events on every bear's generator,
so every bear can also be the source. The third argument is 3.0 for
`FEAR_WIT_ATTACKED` and 0.0 for `FEAR_WIT_INJURED` (selected lines):

```lua
  fearEvent = engine.FearEvent_Create(FEAR_WIT_ATTACKED, false, 3.0, GetModeledObject(self.gameObjectEnvironment))
  fearGeneratorComponent:AddFearEvent(fearEvent)
  fearEvent = engine.FearEvent_Create(FEAR_WIT_INJURED, false, 0.0, GetModeledObject(self.gameObjectEnvironment))
  fearGeneratorComponent:AddFearEvent(fearEvent)
```

*Interpretation:* the 3.0 is how many seconds the event stays active. Which
bears perceive an event (range, line of sight) is decided by the engine, not
the scripts.

## How much each event scares a bear

`NPC:InitFears` in `npc` is the fear table: one `AddFear` call per event. The
first 13 lines of the function:

```lua
function NPC:InitFears()
  self:AddFear(FEAR_SONAR, FEARTYPE_PLAYER, 0.0, 0.0, 0.0, 0.0, 0.0, false, 0.0, {}, 1.5)
  self:AddFear(FEAR_TORMENTOR, FEARTYPE_PLAYER, 30.0, 20.0, 10.0, 0.0, 0.0, false)
  self:AddFear(FEAR_NBSCREAM, FEARTYPE_PLAYER, 30.0, 20.0, 10.0, 5.0, 5.0, false)
  self:AddFear(FEAR_TERRORIZE, FEARTYPE_PLAYER, 100.0, 75.0, 50.0, 25.0, 10.0, false)
  self:AddFear(FEAR_WITNESS_KILL, FEARTYPE_TORMENT, 100.0, 75.0, 50.0, 25.0, 25.0, true)
  self:AddFear(FEAR_ATTACKED, FEARTYPE_AGGRESSION, 50.0, 25.0, 15.0, 10.0, 5.0, false)
  self:AddFear(FEAR_CORNERED, FEARTYPE_PLAYER, 30.0, 20.0, 10.0, 5.0, 0.0, false)
  self:AddFear(FEAR_INJURED, FEARTYPE_AGGRESSION, 100.0, 0.0, 0.0, 0.0, 0.0, false)
  self:AddFear(FEAR_WIT_ATTACKED, FEARTYPE_AGGRESSION, 40.0, 20.0, 10.0, 5.0, 0.0, false)
  self:AddFear(FEAR_WIT_INJURED, FEARTYPE_TORMENT, 50.0, 40.0, 20.0, 10.0, 5.0, false)
  self:AddFear(FEAR_SCREAM, FEARTYPE_TORMENT, 25.0, 20.0, 10.0, 5.0, 0.0, false)
  self:AddFear(FEAR_HIDDEN_TERRORIZE, FEARTYPE_PLAYER, 200.0, 150.0, 100.0, 50.0, 25.0, false)
  self:AddFear(FEAR_STEALTH_SCARE, FEARTYPE_PLAYER, 200.0, 150.0, 100.0, 50.0, 25.0, false)
```

The rest of the table follows the same pattern: one entry per object for
scares (`FEAR_SCARE_*`), seen kills (`FEAR_SEE_KILL_*`), destroyed
(`FEAR_SEEDESTROY_*`) and disabled (`FEAR_SEEDISABLED_*`) objects, plus
kill types (`FEAR_KILLED_*`).

`AddFear`'s arguments, confirmed from its body (`Fear_Create`,
`SetFearLevels`, `SetShocking`, ...):

| Argument | Meaning |
|---|---|
| 1 | The fear event |
| 2 | Its category: `FEARTYPE_PLAYER`, `_AGGRESSION`, `_TORMENT`, `_STRANGE`, `_TRAP` |
| 3–7 | Five fear values, passed to `SetFearLevels` |
| 8 | "Shocking" |
| 9 | Optional: how many shocks are permitted (default -1) |
| 11 | Optional: immune time |

*Interpretation:* the five values are the amount of fear added at each of the
bear's fear stages, getting smaller as the bear is already more scared.
"Shocking" is set on the kill-type events and probably triggers a stronger
reaction. Neither has been tested in-game yet.

What the table shows either way: seeing a bear get hit (40) scares less than
being hit (50); seeing a kill (100, shocking) scares more; seeing an object
kill (200 or more, shocking) scares most.

## Fear thresholds

Each bear type is defined with a maximum fear level and three thresholds. From
`naughtyisland_npcs`:

```lua
STARDUST = NPCDef("Stardust", --[[HASH:"npc_names_Stardust" TEXT:"Stardust"]]0x4b5fa30b, CHEERLEADER, 0, FACTION_NORMAL_BEAR_HASH, 20, false, {0.79, 1.0, 0.82}, 90, 1500, 1.5, {0.2, 0.5, 1.0}, NORMALBEAR2_SOUNDSUFFIX, "")
```

The arguments follow `NPCDef.__init` in `npc`: ..., `color` `{0.79, 1.0, 0.82}`,
`maxHP` 90, `maxFearLevel` 1500, `shootingSpeed` 1.5, `fearThresholds`
`{0.2, 0.5, 1.0}`, ... . `naughtyisland_npcbase` applies them:

```lua
  v:SetMaxFearLevel(maxFearLevel)
  v:SetScaredThreshold(fearThresholds[1])
  v:SetTerrifiedThreshold(fearThresholds[2])
  v:SetPanicThreshold(fearThresholds[3])
```

*Interpretation:* the thresholds are fractions of the maximum, so Stardust
becomes scared at 20% of 1500 (300), terrified at 50% (750) and panics at 100%.

## Changing it

* **How strongly bears react:** edit the values in `NPC:InitFears`
  (`global.lu` → `npc`) and ship. Keep the `.0` on these values (`40.0`, not
  `40`): Ship treats a number without a decimal point as the game's integer
  type, and these are floating-point.
* **How easily one bear type breaks:** edit its `maxFearLevel` or
  `fearThresholds` in the `*_npcs` script of the level you're changing.
* **What counts as an attack:** `HealthChangedCB` skips trap damage; that's
  the `DAMAGE_TYPE_TRAP` check.

Verified in-game: a `global.lu` with `NPC:InitFears` multiplied by 10, read and
shipped with Seam Ripper, boots and plays correctly in the tutorial and in
gameplay (the 2026-09-24 scare test).
