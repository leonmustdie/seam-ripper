---
title: Game text
parent: Naughty Bear
grand_parent: Game reference
nav_order: 9
---

# Game text

*Naughty Bear.* Every word you read in the game, from the menus to the
objectives ("Kill a Bear!"), is stored apart from the scripts, in text files you
can edit as plain lines. This is the easiest way to change how the game feels,
and it works on every language.

## Where it lives

Text is in per-language containers named `<container>.<language>.lu`, next to the
container whose scripts use it. Retail has 71 of them for each of five
languages (`en_us`, `fr_fr`, `de_de`, `es_es`, `it_it`):

* `global.en_us.lu` (1,027 strings) and `startmenu.en_us.lu` (521): the game's
  general text and the menus.
* `naughtyisland.en_us.lu`: the bears' names.
* `ep1story.en_us.lu` (76), `ep1challenge1.en_us.lu` (16) and so on: each
  episode's story and challenge text, objectives, tutorial prompts and
  cutscene subtitles.

## How scripts find their text

A script never holds the words. It holds a number, and the container with the
same name holds the text for that number. In Episode 1's first challenge:

```lua
local objective = Objective(--[[HASH:"ep1_cha1_objectives_obj1" TEXT:"Kill a Bear!"]]0x19896ed5)
```

The number `0x19896ed5` is the text's ID. Seam Ripper shows the English words in
the `TEXT:` note beside it. The same ID is the first thing on a line of the
text file:

```
19896ed5	Kill a Bear!
```

So to change what the objective says, change the words in the text file. You do
not touch the script.

## How to edit it

Extract, edit, and apply back:

```
SeamRipper.exe --tool lu_strings.py extract ep1challenge1.en_us.lu -o text.txt
SeamRipper.exe --tool lu_strings.py apply ep1challenge1.en_us.lu text_edited.txt -o new.lu --verify
```

Each line is an ID, a tab, and the text. Edit only the text after the tab. A
`\n` in the text is a line break. Making the text longer is fine.

We checked this round trip on `ep1challenge1.en_us.lu`: we changed "Kill a
Bear!" to "Kill a Bear! (edited)", and the rebuilt file reported `VERIFY OK: all
edits present and readable` and read back with the new text. We did not run the
edited file in the game.

## Things to know

* Change the same line in all five languages to change it for everyone;
  otherwise players in other languages still see the original.
* The text file uses the ID as a name. Do not change an ID, and do not add
  one the scripts do not use.
* Bear names use the same system. Chubby's `NPCDef` in [Bear stats](bear-stats.md)
  holds the ID `0xf676deae`, and in `naughtyisland.en_us.lu` the line
  `f676deae	Chubby` is where the name is kept.

## Confirmed and not

* Confirmed: the container names and string counts above, how a script points
  at text, and the extract and apply round trip.
* Not tested in the game: an edited text file.
* For Panic in Paradise's text and menus, see [PiP: text and menus](pip-text-and-menus.md).
