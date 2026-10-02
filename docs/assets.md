---
title: Textures, models and sounds
parent: Seam Ripper reference
nav_order: 4
---

# Textures, models and sounds

Besides scripts and text, the game files hold the art and the sound. Seam
Ripper can pull these out into files you can open in normal tools. This page is
about getting them out; for what is inside the files see
[File formats and PiP internals](game-files.md).

All of the commands below run through the app's EXE as
`SeamRipper.exe --tool <script> ...`, or from the Tools page in the app.

## Naughty Bear (NB1)

Two steps: extract the container's chunks, then convert them.

```
SeamRipper.exe --tool naughty_lu.py extract admiralhat.lu -o extracted
SeamRipper.exe --tool lu_convert.py extracted -o converted
```

On `admiralhat.lu` this gave a mesh (290 vertices, 456 triangles) as `.obj` and
`.mtl` plus a `.glb` with the textures built in, and three textures as `.dds`
and `.png`. It also said it skipped three chunks, "animations, sounds, scene
data etc. are not yet supported". If you only ran the first step you only have
`.bin` files.

## Panic in Paradise (PiP)

One command does both steps:

```
SeamRipper.exe --tool pip_dump.py aluminumbat.lu -o dump
```

On `aluminumbat.lu` it wrote the mesh (134 vertices, 192 triangles) as `.obj`,
`.mtl` and `.glb`, three textures as `.dds` and `.png`, the script, and a report.
On a hat (`afrowig_top.lu`) it wrote four textures and a skeleton report.
Characters come out as rigged `.glb` files, props as `.obj`.

Menu screens are a different kind of chunk; see
[PiP: text and menus](scripts/pip-text-and-menus.md).

## Sounds

PiP's sound lives outside the `.lu` files, in FMOD sound banks (`.fsb`) in the
game's `FmodEventData` folder. Decode a bank to `.wav`:

```
SeamRipper.exe --tool lu_sound.py fsb HUD_Ingame.fsb -o sounds
```

We ran this on one bank and got one `.wav` (`FX_HUD_Stamina_Deny`) and a manifest.
`lu_sound.py` also has `bank` for sound chunks inside NB1 `.lu` files and
`streams` for loose `.xma` files; we did not test those two here.

## What you get

* **Textures:** `.dds` always, plus `.png` if Pillow is installed (the EXE has
  it). They are the base size only.
* **Models:** `.obj` and `.mtl`, and `.glb` with textures. Which way is up
  varies from model to model, so rotate in your 3D program.
* **Sounds:** `.wav`.

## What isn't here

Putting an edited texture, model or sound back into a container is not covered
on this page; we only tested getting them out.

If a texture format isn't supported yet, the tool saves the raw data as a
`.texdata.bin` and says so (see
[More troubleshooting](technical.md#more-troubleshooting)).
