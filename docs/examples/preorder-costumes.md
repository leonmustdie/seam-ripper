---
title: Pre-order costumes
parent: Examples
nav_order: 3
---

# Pre-order costumes

A restoration of the original *Naughty Bear* pre-order bonuses, for the Gold
Edition: **Naughty Kruebear** and **Naughty Slasher**. They show up on the
Select Costume screen, are unlocked from the start, and have their stats,
perks and execution text.

[Download NB-Pre-order-Costumes.zip](NB-Pre-order-Costumes.zip){: .btn .btn-primary }

This one is different from the other examples. A normal patch holds none of
the game. This zip holds the two costume files exactly as they were in the
pre-order DLC, and its patch holds the DLC's own registration script and text.
That is on purpose: the DLC can no longer be bought, and this is the closest
thing left to the original pre-orders.

## Install

You need the Seam Ripper version that can add new text (older ones refuse the
patch) and your own Gold Edition files.

1. Copy `naughtyfreddy.lu` and `naughtyslasher.lu` from the zip's `lu` folder
   into your game's `lu` folder.
2. In Seam Ripper, open `preorder_costumes.srpatch` on the **Patches** page.
   It checks that it fits your files.
3. Apply it to a copy first, then to the game. Seam Ripper backs up every
   file it replaces, and **History** can put them back.

## Where each part comes from

The pre-order DLC survives as three packages: Kruebear "A" and "B", and
Slasher "A". They are prototypes. Slasher "B" is lost.

| Part | Taken from |
|---|---|
| Naughty Kruebear costume | prototype B |
| Naughty Slasher costume | prototype A (the only one) |
| Kruebear's top-left line, "Claws Ultra Kill!" | prototype B |
| Kruebear's big execution pop-up, `NIGHTMARISH/DISFIGURIFICATION` | prototype A |
| Slasher's top-left line and pop-up, `INCREDI-BELLY/KNIFAGE` | prototype A, left exactly as it is |

Prototype A put the same flavor text on both lines. B split them, with a short
"Ultra Kill" line at the top left and a separate pop-up, but B's pop-up is one
long line and the game draws nothing for it. A's short, slash-split version
draws. Slasher has no B, so its top-left line shows the pop-up text, slash and
all. It is left as found, not reconstructed.

## How it works

A DLC package is three kinds of file: the costume (`naughtyfreddy.lu`), a small
script that registers it, and text. The Gold Edition already had the hats, the
finishing-move scoring and the pop-up definitions for both costumes. What was
missing was the costume itself, so the patch adds:

* **The registration**, 26 lines in `global` → `init_unlockable`. This is the
  DLC's own script, with its `downloadable = true` left out, so the game loads
  the costumes from the normal `lu` folder:

  ```lua
  CreateUnlockable({
    name = --[[HASH:"naughtyfreddy_costume_name"]]0xa5dbb167,
    category = engine.eSPCOSTUME,
    conditions = nil,
    statistics = {life = 5, strength = 4, accuracy = 2, speed = 3},
    loadUnit = "NaughtyFreddy"
  })
  ```

* **Fourteen text lines**, in `global.<language>.lu` for the names, perks and
  top-left lines.
* **Two pop-up lines**, in `levelcommon.<language>.lu`. The big execution
  pop-ups read their text from `levelcommon`, like every other pop-up in the
  game. Putting them only in `global` made the Narrator speak with no text
  on screen.

## Checked

* Both costumes appear on Select Costume and play through levels (Naughty Bear
  on the PC port, in English).
* Both executions show their top-left line and big pop-up.
* The patch applies to unmodified files and produces exactly the files it was
  made from, and every rebuilt file passes Seam Ripper's layout check.
* Not played: German, Spanish, French and Italian. Their text is in, taken from
  the same prototypes. Kruebear B's top-left line is empty in those four
  languages, as the prototype has it.

## Make your own

The patch needed a new feature: a text line starting with `+` adds a string the
file does not have yet. In a strings file from `lu_strings.py extract`, write
`+HASH`, a tab and the text, then apply it (or put it in a patch) as usual.
A line without the `+` still only edits existing strings, so a mistyped ID
cannot add one by accident.
