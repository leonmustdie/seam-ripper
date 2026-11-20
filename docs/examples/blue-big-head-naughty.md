---
title: Blue big-head Naughty
parent: Naughty Bear examples
grand_parent: Examples
nav_order: 3
---

# Blue big-head Naughty

Naughty with blue fur and a head 1.6 times its size, in either game. It is
one texture replacement and one model edit in one patch, made to show how
both work. Nothing about how Naughty plays changes.

[Download for Naughty Bear](blue-big-head-naughty.srpatch){: .btn .btn-primary }
[Download for Panic in Paradise](blue-big-head-naughty-pip.srpatch){: .btn }

## What it changes

| Game | File | Change |
|---|---|---|
| Naughty Bear | `characters_shared_resources`, `naughtyisland_shared_resources` | fur texture `26ca1642` |
| Naughty Bear | `mp_naughtybear` | fur texture and body model `743299d0` |
| Naughty Bear | `naughtybear`, `cutscene_tophat_endings`, `ep6endingcutscene` | body model |
| Panic in Paradise | `skinnaughty`, `area15` | fur texture and body model |
| Panic in Paradise | `area07_npc_1`, `area11` | fur texture |

The fur and the body are stored in several containers, and the game loads
whichever copy the level uses, so the patch changes every copy.

## The texture

Naughty's fur is texture `26ca1642`, 1024 x 1024, DXT1. It was exported as a
PNG (**Export textures for editing**), recoloured (hue turned half way round,
saturation doubled, shading kept) and put back with **Replace a texture**,
*Every copy* ticked. Seam Ripper compresses the picture in the texture's own
format and remakes its mip levels, so the record keeps its size. See
[Replacing a texture](../assets.md#replacing-a-texture).

The patch stores the recoloured picture, not the original, and rebuilds it
into your own copy of each container.

## The model

Naughty's body is model `743299d0`, part `sub00`. It was exported as a GLB
(**Export a model for editing**), and in Blender every vertex above the neck
was scaled 1.6 times about the middle of the head, blended in over the neck so
there is no seam. The arms are left out of the scale. It was exported again
with **Include > Data > Attributes** ticked and put back with **Replace a
model**. See [Editing a model](../assets.md#editing-a-model).

Only vertices moved: 1,054 in Naughty Bear, 1,101 in Panic in Paradise. The
number of vertices, the skin weights and the bones are as shipped, so
skinning and animation work unchanged and the record keeps its size. The
patch stores only the moved vertices.

## Make your own

* Paint the PNG any way you like; it only has to stay 1024 x 1024.
* Sculpt, scale or smooth the head, ears or belly the same way. Do not add
  or delete vertices: for a different model, see [Importing a new
  model](../assets.md#importing-a-new-model).
* Save both as one patch with `make`:

```
SeamRipper.exe --tool sr_patch.py make -o my-naughty.srpatch --name "My Naughty" ^
    --texture characters_shared_resources.lu 26ca1642 fur.png ^
    --mesh naughtybear.lu 743299d0 head_edit.json
```

  One patch for both edits matters when they touch the same file: two
  separate patches applied on top of each other work, but `--check` then
  reports the file as not matching either patch.

## Checked

* The fur and the head were tested in game in both games (played in Xenia),
  also together with the EternalDancing animation swap.
* Each patch was test-applied to retail files when it was made, and every
  record it rewrites reads back as written. The files it writes are the same,
  byte for byte, as applying the separate fur and head patches one after the
  other.
