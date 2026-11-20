---
title: Panic in Paradise examples
parent: Examples
has_children: true
nav_order: 2
---

# Panic in Paradise examples

Each of these is a `.srpatch` you can apply. The script patches hold only the
lines that were changed; Blue big-head Naughty holds its recoloured fur
picture and the head's moved vertices. How patches work is on [Patches and
backups](../patches.md).

| Example | What it does | What it touches |
|---|---|---|
| [Hero firearms](hero-firearms.md) | Naughty picks up guns and fires them, with a six-round clip, a reload pause and knife-style swings | `levelcommon` (2 scripts), `skinnaughty` (2 scripts) |
| [Rage glow](rage-glow.md) | Every ultra-kill makes Naughty's fists glow and hit harder, with no unlock needed | `skinnaughty` (1 script) |
| [Blue big-head Naughty](blue-big-head-naughty.md) | Naughty with blue fur and a 1.6x head: a texture replacement and a model edit | Naughty's fur texture and body model in `skinnaughty`, `area07_npc_1`, `area11`, `area15` |

## Apply one

1. Get your Panic in Paradise files ([Getting your game files](../getting-game-files.md)).
2. In Seam Ripper, open the patch on the **Patches** page. It checks that it
   fits your files.
3. Apply it to a copy first, then to the game. Seam Ripper backs up what it
   replaces.

The patches change different things, so you can apply all three.
