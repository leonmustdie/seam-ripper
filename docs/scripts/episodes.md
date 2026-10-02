---
title: Episodes and challenges
parent: Naughty Bear
grand_parent: Game reference
nav_order: 6
---

# Episodes and challenges

*Naughty Bear* has ten episodes. Each has a **story** and four **challenges**,
and each of those is one script that says what you have to do, in what order,
and what makes you fail. They are readable, and their numbers (score gates,
time limits) are easy to change.

## Where they live

One container per script, named after the episode:

* `ep1story.lu` → `ep1_story_rules` (one for each of episodes 1 to 10)
* `ep1challenge1.lu` → `ep1_cha1_rules`, and `ep1challenge2` to `ep1challenge4`

(In the container names the word is `challenge`; in the script names it is
`cha`.) The tutorial is `ep0_tutorial_rules`.

## How a rule script reads

The script makes a chain of **objectives**. Finishing one runs a function and
moves on to the next. Episode 1's story, the start of it:

```lua
_G.challengeType = CHALLENGETYPE_STORY
gMonitoringUtil:SetInitialZone(ZONE_NAUGHTY_HUT)
gMonitoringUtil:SetFinalZone(ZONE_DISCO)
gGameEvents:SetGatePointRequired(GATE_FACTORY, 2500)
gGameEvents:SetBridgePointRequired(BRIDGE_DISCO_FACTORY, 100000)
local objective = Objective(--[[HASH:"ep1_story_objectives_obj1" TEXT:"Points to go:"]]0x122c1a77)
```

and how the first objective opens the gate once you have the points:

```lua
local greaterOrEqualThan = GreaterOrEqualThan(gMonitoringUtil.fTotalScore, gGameEvents:GetGatePointRequired(GATE_FACTORY))
function Obj1CB()
  print("Open Gate to Factory")
  gGameEvents:OpenGate(GATE_FACTORY)
  ...
objective:AddProgressiveBranchObjective(greaterOrEqualThan, objective2, "Obj1CB")
```

The words you can use:

* `Objective(text)`: a step, with the text shown on screen.
* `AddBranchObjective(condition, next, "Function")`: when the condition is
  true, run the function and go to the next step.
* `AddSubObjective` / `AddFailSubObjective`: an optional goal, or one that ends
  the attempt if it comes true.
* `Rule(name, condition, "Function")`: a check that runs the whole time. The
  story's "you died" and "the boss escaped" are rules.

## Gates and bridges: the score you need

Each story sets how many points open a gate or a bridge:

| Episode | Gate | Bridge |
|---|---|---|
| 1 | Factory 2,500 | Disco to Factory 100,000 |
| 2 | | Cabin to Disco 150,000 |
| 3 | Factory 2,500 | Factory to Cabin 250,000 |
| 4 | Disco 20,000 | Cabin to Disco 250,000 |
| 5 | Disco 200,000; Factory 25,000 | |
| 6 | Disco 200,000; Cabin 25,000 | Factory to Cabin 200,000 (see below) |
| 7 | Disco 250,000; Cabin 25,000 | Disco to Factory 300,000 |
| 8 | Disco 20,000 | Disco to Factory 300,000; Factory to Cabin 350,000 |
| 9 | | Factory to Cabin 300,000; Disco to Factory 400,000 |
| 10 | | Cabin to Disco 200,000; Factory to Cabin 300,000 |

Episode 6 sets its Factory to Cabin bridge with `SetGatePointRequired`, the
gate call, where every other bridge uses `SetBridgePointRequired`. *Interpretation:*
a slip by the developers, which may mean that bridge uses a different value;
this page did not test it.

## The four challenges

Each challenge sets a type at the top. From the scripts:

| Episode | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| 1 | Killer | Peaceful | Insanity | Top Hat |
| 2 | Untouchable | Speed Run | Killer | Top Hat |
| 3 | Killer | Invisible | Insanity | Top Hat |
| 4 | Untouchable | Speed Run | Killer | Top Hat |
| 5 | Invisible | Peaceful | Killer | Top Hat |
| 6 | Speed Run | Killer | Insanity | Top Hat |
| 7 | Speed Run | Peaceful | Killer | Story |
| 8 | Speed Run | Peaceful | Killer | Story |
| 9 | Killer | Speed Run | Insanity | Top Hat |
| 10 | Speed Run | Killer | Untouchable | Top Hat |

The Peaceful challenges are called "Friendly" in some of the scripts' own
titles. Episodes 7 and 8's fourth challenge is typed *Story* in the script, not *Top
Hat*. *Interpretation:* those two are not a hat challenge, or the type was
copied from the story script.

What the names mean comes from the script. **Untouchable** fails if you get hurt
(`"Challenge: Don't Get Hurt!"`). **Speed Run** fails when a timer runs out:

```lua
local timerCondition = gMonitoringUtil:CreateTimerCondition(180.0)
```

The time limits (in seconds) are 180 for episode 2, 240 for 4, 360 for 6, 7 and
9, 300 for 8 and 420 for 10.

## How to change it

* **A gate or bridge score:** change the number in `SetGatePointRequired` or
  `SetBridgePointRequired`, in the story script. This is the simplest edit here.
* **A speed-run time:** change the number in `CreateTimerCondition`.
* Use whole or decimal numbers as the game does: `180.0` is a decimal, `2500`
  a whole number (see [Numbers](../technical.md#numbers)).

## Confirmed and not

* Confirmed in the scripts: the structure, every number in the tables, and the
  challenge types.
* *Interpretation:* the typing of episodes 7 and 8, and the episode 6 bridge.
* Checked in Seam Ripper: changing Episode 1's `SetGatePointRequired(GATE_FACTORY, 2500)` to `100` ships, and the file reads back with only that line changed. Not tested in the game.
