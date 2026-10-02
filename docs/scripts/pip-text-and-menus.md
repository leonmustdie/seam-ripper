---
title: "PiP: text and menus"
parent: Panic in Paradise
grand_parent: Game reference
nav_order: 6
---

# PiP: text and menus

*Panic in Paradise.* The words in the game, and the menu screens they sit on,
are in separate files from the scripts. Text is the easy half: it is a list of
strings you can edit as plain text. Menus are Scaleform UI movies, which you can
pull out and open, but Seam Ripper does not put them back.

## Where the text lives

Text is in per-language units, named `<unit>.<language>.lu`. Retail has five
languages (`en_us`, `fr_fr`, `de_de`, `es_es`, `it_it`) for each of these
eleven units:

`bearabearaisland`, `briefingscreen`, `customizationmenu`, `global`,
`levelcommon`, `loadingscreen`, `manualmenu`, `openinglogo`, `startmenu`,
`tallyscreen`, `trialcompletescreen`.

Sizes in English: `global` has 1,841 strings, `levelcommon` 883, `startmenu`
251 (in two tables), `briefingscreen` 38. The menu words are in `startmenu`:
"Bear Wares", "Story", "Leaderboards", the button prompts, and the credits.

## How to edit it

Extract a unit to a text file, edit it, and apply it back:

```
SeamRipper.exe --tool lu_strings.py extract startmenu.en_us.lu -o startmenu.txt
SeamRipper.exe --tool lu_strings.py apply startmenu.en_us.lu startmenu_edited.txt -o startmenu_new.lu --verify
```

Each line is a hash, a tab, and the text, grouped under a `# record` line:

```
81c900eb	Bear Wares
```

Edit only the text after the tab. The hash is the string's name, so leave it
alone. A `\n` in the text is a line break. Longer or shorter text is fine.

We checked this round trip on `startmenu.en_us.lu`: one string changed,
`VERIFY OK: container re-parses, all edits present`. The rebuilt file is
bigger (7,330 bytes became 37,512) because it is written uncompressed, which
the game accepts. We did not run the edited file in the game.

## Things you can see in the text

Some strings tell you about the game's design:

* The button prompts list **Shoot** and **Reload** next to Walk, Sprint, Dodge
  and Ultra-Kill, even though Naughty can't pick up guns in retail. See
  [Hero firearms](../examples/hero-firearms.md) for a patch that lets him.
* There are placeholder lines such as `Not found : level2` to `level7`
  and `Not found : levelzoo`. *Interpretation:* leftovers from an earlier
  level menu.
* A start-menu string names the first level "Paradise Resort Lobby – Level 1".

## The menus

The screens are Scaleform movies stored in chunks of type `04d00001`.
`pip_gfx.py` pulls them out as `.gfx` files, with every texture they use as PNG:

```
SeamRipper.exe --tool pip_gfx.py startmenu.lu -o menus
```

From `startmenu.lu` that gave 45 movies and 111 textures, including
`mainmenu`, `levelselectmenu`, `leaderboardmenu`, `credits` and one `polaroid_`
movie per target bear. Open the `.gfx` files in JPEXS Free Flash Decompiler to
look at the layout and ActionScript. The art is in the PNGs; the movies are mostly
layout and ActionScript.

## What isn't possible yet

Seam Ripper reads the movies but has no step to write an edited one back into
the `.lu`. `lu_chunk_replace.py` replaces a chunk in a container, but we have
not tried it on a menu movie. So for now, change the words (above) and treat the
menu art as read-only.

## Confirmed and not

* Confirmed: the unit and language list, the string counts, the extract and
  apply round trip, and the movie extraction numbers.
* Not tested in the game: an edited text unit, and anything about replacing a
  menu movie.
