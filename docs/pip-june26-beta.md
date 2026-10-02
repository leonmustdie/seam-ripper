---
title: "PiP: June 26th Beta Discoveries"
parent: Panic in Paradise
grand_parent: Game reference
nav_order: 7
---

# PiP: June 26th Beta Discoveries

Notes from getting the *Naughty Bear: Panic in Paradise* **June 26th, 2012
beta** build to run in Xenia Canary and to play its debug "zoo" levels. Every
script excerpt below is copied from the game's own files (the `.lu` files, read
with Seam Ripper), so you can check each claim yourself. Where something is a
guess, it says *interpretation*.

None of this is in the retail game. The beta has its own zoo levels, and it is
missing some of the data they depend on.

## What was made to work

The beta ships five debug levels that the story never uses. Four of them now
load, play and survive a level restart:

| Zoo | Level name | Notes |
|---|---|---|
| Combat Zoo | `level_names_zooCombat` | Arena with bears and weapons. Arena waves are switched off (see [below](#combat-zoos-missing-bear-definitions)). |
| Vegetation Zoo | `level_names_zoovegetation` | Plays as-is. |
| Lighting Zoo | `level_names_zoolighting` | Plays as-is. The beta has no loader for it, so the level name and loader are our own. |
| Collision Zoo | `level_names_zoocollision` | Has no player spawner of its own, so it borrows Lighting Zoo's (see [below](#collision-zoo-has-no-player)). |

The fifth, Test Zoo, loads its data but black-screens, and was left alone.

Our test setup reached them by redirecting four story levels on the Back-button
cube: Cuddles → Lighting, Pudding → Vegetation, Trembles → Collision, Fluffy →
Combat. Dev-menu entries that pick a zoo for the next load were added too, but
are not yet tested end to end.

## The zoo data is older than the engine

The zoo `.lu` files were exported by an older build, and the June 26 engine reads
some of their records differently. Two things went wrong, and both only show up
as a hang or a garbage allocation, never as a clear error.

**Old element layout.** Some geometry and model records contain small objects
that were 0x38 bytes in the old layout and are 0x3C in the engine's. The engine
then reads the object's pointer and count one word late and sweeps hundreds of
megabytes of heap. An old-layout element looks like this, and the fix is to
insert one `00efefef` word at +0x10 and repoint the references:

```
aabbccdd 00000000 00000000 00000000 00000000 00000000 00000000 <ptr> ... c4ce3eb3 ...
```

**Records are placed by a running cursor.** Resource records flagged `0x200`
(meshes, zone records) are mapped one after another, each rounded up to a 16-byte
boundary (4096 for some rows). If you make one record larger and leave the
offsets alone, every later record lands too early, and texture descriptors point
into filler bytes. The tell is the heap-full message asking for about 3.2 GB.
After any edit that changes a record's size, lay the file out again in row order.

## Loader scripts

Each level has a loader script in `levelloaders.lu`. A story level and a zoo
look similar, but the zoo loader as shipped does less. Story level (Cuddles,
Area 15):

```lua
LibraryLoading.AddZonesLU(AREA_1, "Area15")
...
LibraryLoading.LoadZone(LOAD_INIT, levelLoadUnitRequester)

-- Load everything in AREA_1 and ENVR_1
LoadInitialZone()
```

Combat Zoo, as shipped:

```lua
LibraryLoading.AddZonesLU(LOAD_INIT, "Zoo")
LibraryLoading.AddZonesLU(LOAD_INIT, "CombatZoo", 0, 1)
...
LibraryLoading.LoadZone(LOAD_INIT)
```

Three differences matter:

* `RegisterLevel` needs `locationID = 0`, which the zoo loaders leave out.
* `LoadZone` needs the `levelLoadUnitRequester` argument.
* **Restart.** Anything in `LOAD_INIT` is loaded once and never rebuilt, and a
  level restart clears the player spawner out of the engine's registry. With the
  zoo in `LOAD_INIT` the restart finds no spawner and crashes. Loading the zoo
  as `AREA_1` and calling `LoadInitialZone()`, as the story levels do, fixes it:

```lua
LibraryLoading.AddZonesLU(AREA_1, "CombatZoo")
LibraryLoading.LoadZone(LOAD_INIT, levelLoadUnitRequester)
LoadInitialZone()
```

A loader script must keep its **exact size**, so a modded loader is padded back
to the original length with a trailing comment.

## A "hang" is usually a crash

Most of the hangs in this build were not deadlocks. When a guest thread reads an
address that is not mapped, Xenia Canary pauses the whole emulator, and the game
looks frozen. Sometimes a "The guest has crashed" box appears:

```
==== CRASH DUMP ====
Thread ID (Host: 0x0000A900 / Guest: 0x00000006)
PC: 0x8262B874
Access Violation: read at 0x0000000100000018
```

Xenia prints host addresses, which are the guest address plus `0x100000000`. The
read above is at guest address `0x18`, so the code followed a null pointer. The
PC and the registers tell you where.

Two other kinds of hang look the same from outside:

* **Heap-full spin.** The allocator's out-of-memory handler prints
  `(Use the '--dump-on-heap-full' option on the command line.)` and then loops
  forever. Here the "heap" was not really full: one caller asked for 2.8 GB
  because it was copying a string with a garbage length.
* **A thread at 100% CPU** in one spot is a loop; one at 0% is waiting.

## Combat Zoo's missing bear definitions

Stepping on an arena trigger box in Combat Zoo hung the game. The trigger
script is `combatzoo_bearspawning`. It builds lists of bears from two names:

```lua
local CombatArea1 = {  
                     COMBATAREABEAR
                    }

local CombatArea2 = {  
                     NORMALARENABEAR
                    }
```

and hands them to the threat manager:

```lua
gEscalatingThreatManager:ConfigureAmbushGroup(--[[HASH:"combatzoo_brown_arena2_group":0xf5c187d]]257693821, bearSpawningAnimation, CombatArea1, CombatZooBrownArena2Spawner)
```

When the player steps on a trigger, this runs:

```lua
engine.ThreatSpawningMgr_StartSpawningFromGroupUID(--[[HASH:"combatzoo_brown_arena2_group":0xf5c187d]]257693821)
```

`ConfigureAmbushGroup` (in `escalatingthreatmanager`) adds each entry's `.name`
as a bear the group can spawn:

```lua
function SetSpawnerAndNPCName(aSpawningGroup, aNPCDefinition, aSpawner)
    for i,v in pairs(aNPCDefinition) do
        aSpawningGroup:AddNPCName(v.name)
    end
    ...
```

So `COMBATAREABEAR` and `NORMALARENABEAR` should each be an NPC definition
(`NPCDef`, in `global` → `npc`), a table with a `.name`. They are not defined
anywhere in the scripts of `combatzoo`, `zoo`, `global`, `bearabearaisland`,
`storymode`, `area15` or `area15_npc` (every script of those containers was
searched; other containers were not). In Lua a name that was never set is `nil`,
and a `nil` entry in a table constructor leaves the table **empty**.
*Interpretation:* every group has no bears, and when a trigger fires, the
engine's "pick a random bear name from this group" code takes an entry from an
empty list and reads garbage. The garbage string length is the 2.8 GB request
above. In one hang, a register held the hash of the `combatzoo_brown_arena2_group`
group, and the hangs stopped once the spawn calls were removed.

The story levels have the same gap, so it looks like a hole in the beta. Area 15
builds its tables from names that are also not defined anywhere we searched:

```lua
local area15_T3_temple_enemytable = 	{  
                     		ZOMBEARLOUIS,
                     		ZOMBEARJASON,
                     		ZOMBEARFREDDY,
                     		ZOMBEARVINCENT
                    		}
```

We did not test whether that level hangs the same way.

**What we did:** removed the five spawn calls from `CombatStartZooArena`, so
the trigger boxes do nothing:

```lua
if __this__:GetHashedName() == --[[HASH:"combatzoo_blue_arenatrigger":0xd5c266b9]]3586287289 then
    --waves off (NPC defs missing)
elseif __this__:GetHashedName() == --[[HASH:"combatzoo_orange_arenatrigger":0x9964514d]]2573488461 then
    --waves off (NPC defs missing)
```

To get the waves back, someone needs to write `NPCDef(...)` entries for those two
names. Its parameters are in `global` → `npc`; we have not found the values the
developers used.

## Collision Zoo has no player

Collision Zoo loads, but nothing ever places Naughty. The engine only creates the
world after it finds one entry in a registry of "player/special spawners". The
zones that work each contain one, as an entity (Lighting's is named
`zoo_specialspawner1`, Combat's `combatzoo_specialspawner`). Collision's zone has
none, so the level-start code looks for the world, gets null, and the
read at `+0x84` is the crash.

The fix that works is to load Lighting Zoo alongside it, which registers the
spawner:

```lua
LibraryLoading.AddZonesLU(AREA_1, "LightingZoo")
LibraryLoading.AddZonesLU(AREA_1, "CollisionZoo")
```

The cost is that Lighting Zoo's room appears in the scene, and you spawn in it.
Adding the spawner entity to Collision's own zone, hiding the room, or borrowing
Test Zoo's spawner instead did not work. Test Zoo's registered, but a later
step crashed on a null write.

## Engine patches

Hangs that were really crashes were fixed with small patches to
`default.xex`. All three jump to a few instructions in padding after the code:

| Address | What it does |
|---|---|
| `0x8262B874`, `0x8262B910` | `lwz r11,0x18(r3)` in a function that looks up an entity by handle. If the entity is gone, the handle is empty and the read crashes. Both reads now treat a null result as "nothing found". This was the Combat Zoo **corner crash**. |
| `0x822EC228` | `addi r4,r30,8` in the code that copies the chosen bear name. If the source string's length is above 1 MB, copy an empty string. This stopped the 2.8 GB allocation. |
| `0x825763B0`, `0x822E51A0` | Null-safe versions of the registry lookup. Only needed for Collision without Lighting, which is not shipped. |

The first is the one that mattered. The second is a safety net and the Lua change
above is the real fix for the bear spawns.

## Not done

* The dev-menu "Next load" entries are not tested end to end.
* Lighting Zoo's white room cannot be removed from Collision Zoo.
* Combat Zoo's arena waves need real NPC definitions.
* Test Zoo still black-screens.
* Whether the story levels hit the same empty-bear-list crash.
