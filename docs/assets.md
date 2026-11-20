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

## Animations

**Extract animations** (the Animations tab beside Models & sound, or the Tools page under Extract and convert) turns a
game's `.lu` folder into one rigged `.glb` per skeleton with every clip baked in
as an animation. Pick the game, the `.lu` files (a whole folder, or just the container you
have open) and an output folder. It decodes the containers, then bakes. For PiP it also rebuilds the Lua
source first, because the scripts are what give the clips their names.

```
SeamRipper.exe --tool anim_extract.py <lu folder> --game nb1 -o animations
SeamRipper.exe --tool anim_extract.py <lu folder> --game pip -o animations
```

For PiP, add `--plan` (the **Preview plan** button) to stop before the bake and
print which character gets which clips. Decoding skips containers it already
decoded, so a second run goes straight to the bake.

For Naughty Bear, the log and `needs.txt` also say which other containers would
add clips to each skeleton, biggest gain first. A skeleton borrows clips from
skeletons the game doesn't ship, and those clips sit in other containers. For
`naughtybear.lu` alone you get 60 clips; `characters_shared_resources.lu` adds
251 more, and the whole game gives 358. (Not available for Panic in Paradise.)

Under the output folder: `decoded/` (the extracted chunks), `scripts/` (PiP
only) and `animations/` with the `.glb` files plus `clips.csv`, `rigs.csv`,
`summary.txt` and, where names could be worked out, `clip_names.tsv`.

We ran NB1 over all 998 containers: 998 decoded with no failures (7 minutes),
then 900 unique clips baked into 69 `.glb` files, 142 MB (9 minutes). On PiP we
ran four containers only, not the whole game. NB1 clips are named by hash inside
the `.glb` (for example `fa28bc20_rtd01a231e`); `clip_names.tsv` maps each hash
to its name. PiP clips carry their names. PiP clip names can differ in capital
letters from one run to the next (`ST_Dance_01` or `st_dance_01`); they are the
same clip.

The models are skinned meshes with no textures, and need numpy. Open them in
Blender or any glTF viewer.

## Replacing an animation

**Replace an animation** (Animations tab, or the Tools page under Animation)
makes a clip play another clip instead, in either game. **List animation
clips** shows what a container holds first: each clip's hash, length, size in bytes,
skeleton, name, and how many other containers keep their own copy.

```
SeamRipper.exe --tool anim_replace.py list naughtybear.lu --find walk
SeamRipper.exe --tool anim_replace.py swap naughtybear.lu --clip st_walk ^
    --from "<lu folder>" --donor st_dance_01 --patch Dancing.srpatch
```

`--clip` takes a hash, a clip name or a state name (`st_walk` picks every
clip that state plays), comma-separated. `--from` is the container that holds
the donor, or the whole `lu` folder to search. Save a `.srpatch` to share
(`--patch`), a patched `.lu` (`-o`), or both. Writing over a game file backs
it up first, and a read-only file is refused.

* **The clip keeps its movement.** A walk replaced by a dance still moves
  Naughty at walking speed, because the root bone keeps the walk's forward
  motion. Tick **Use the donor's movement too** to drop that.
* **Naughty Bear:** clips address bones by number, so the donor is fitted to
  the target's skeleton with the bone map the game itself ships. The donor
  must be on the same skeleton or one `list` says the container can borrow
  from.
* **Panic in Paradise:** clips name their bones, so any clip for the same
  body fits. A donor for another body (a prop, a bird) is refused, and so is
  an additive clip in place of a normal one.
* **Only the container you give changes.** Clips are copied into many
  containers (each Naughty costume has its own walk); `list` and `swap` say
  how many others hold the clip.
* **Panic in Paradise and clip size.** The game freezes at level load if any
  record in a container changes size. A shorter replacement is padded back to
  the original size for you. A longer one goes into the donor's own record
  when the donor is stored in the same container: the two clips trade places,
  so the donor's name then plays the clip you replaced (Naughty dancing
  instead of walking also walks where the game asks for the dance). Each
  donor's record can take one clip, so give each clip of one swap its own
  donor; otherwise pick a donor no bigger than the clip (`list` shows the
  sizes).

Tested in game: on Naughty Bear, Naughty's walk and run replaced by two
dances (the EternalDancing example); on Panic in Paradise, Naughty's walk,
run and sprint replaced by three dances (in the dances' own records) and, in
place, by a shrug and a chat gesture. The encoder reproduces every clip in
both games: all 900 unique NB1 clips and all 719 PiP clips decode, encode and
decode back to the same motion, and come out byte for byte when nothing is
changed.

## Replacing a texture

**Replace a texture** (Tools page under Textures and models, or **Replace
with PNG or DDS…** on a container's Textures tab) puts an edited picture back,
in either game. **List textures** shows each texture's hash, width and height,
format and mip levels; **Export textures for editing** saves them as PNG (or
DDS with every mip level as stored).

```
SeamRipper.exe --tool tex_replace.py list characters_shared_resources.lu --find 26ca
SeamRipper.exe --tool tex_replace.py export characters_shared_resources.lu ^
    --texture 26ca1642 -o textures
SeamRipper.exe --tool tex_replace.py replace characters_shared_resources.lu ^
    --texture 26ca1642 --image fur_blue.png --all-copies --patch BlueFur.srpatch
```

* **Same width and height.** The picture must be the size of the texture;
  it is compressed in the texture's own format (DXT1, DXT3, DXT5 or 32-bit)
  and its mip levels are made from it, so the record keeps its size and
  nothing else in the container moves. A DDS of the same format is taken as
  it is, mip levels included. `--texture` and `--image` can be repeated to
  replace several textures at once.
* **Every copy.** A texture is often stored in several containers (Naughty's
  fur is in `characters_shared_resources`, `naughtyisland_shared_resources`
  and `mp_naughtybear` on Naughty Bear; `skinnaughty`, `area07_npc_1`,
  `area11` and `area15` on Panic in Paradise). `--all-copies` (ticked by
  default in the app) replaces the copies in the other containers of the
  same folder; without it the game may show the original where it loads
  another copy.
* Save a `.srpatch` to share (`--patch`), patched `.lu` files (`-o` for one
  container, `--out-dir` for several), or both. Writing over a game file
  backs it up first.

Checked against the game files: all 952 unique Naughty Bear textures and all
1,951 Panic in Paradise textures decode and re-encode byte for byte, and every
mip level matches its base scaled down. Naughty's fur recoloured blue (part of
the [Blue big-head Naughty](examples/blue-big-head-naughty.md) example) is
built with this tool for both games and works in game on both.

## Editing a model

**Replace a model** (Tools page under Textures and models, or a container's
Model editing tab, beside Animations) puts a model you edited in Blender back, in either game.
**List models** shows each model's hash, parts, vertices and kind; **Export a
model for editing** saves it as a GLB with one object per part (`sub00`,
`sub01`, ...), textured where the picture is found.

```
SeamRipper.exe --tool mesh_replace.py list naughtybear.lu --find 7432
SeamRipper.exe --tool mesh_replace.py export naughtybear.lu --mesh 743299d0 -o naughty.glb
SeamRipper.exe --tool mesh_replace.py replace naughtybear.lu --mesh 743299d0 ^
    --glb naughty_edited.glb --all-copies --patch BigHead.srpatch
```

* **Move vertices, don't add or delete them.** Move, scale, sculpt and smooth
  freely. The number of vertices and triangles, the skin weights and the
  bones stay as the game ships them, so the model keeps its size in the file
  and skinning can't break. A GLB with vertices added or missing is refused. To
  put in a different model with its own vertex count, see [Importing a new
  model](#importing-a-new-model).
* **In Blender:** File > Import > glTF 2.0, edit, then File > Export > glTF
  2.0 (.glb) with **Include > Data > Attributes** ticked. That keeps each
  vertex's id (`_SR_VID`), so vertices map back even when Blender reorders
  or splits them. Keep the object names.
* **Normals.** Each shipped normal turns with the surface under it, so the
  game's smooth and hard edges stay as made. `--glb-normals` takes Blender's
  normals instead (they come back rougher on edited areas).
* Skinned parts are in the bind pose; rigid parts (props, hats) are in the
  space of the bone they hang from. The shadow-volume copy of a character is
  left as it is.
* `--all-copies` also edits the copies in the other containers of the folder
  that are identical to the one you exported; a copy that differs is named
  and left alone.

Checked against the game files: all 862 unique meshes (1,951 editable parts)
in both games re-emit byte for byte, an unedited GLB reads back as no change,
and a one-vertex move changes only that vertex. Naughty's head 1.6 times bigger
(the other half of [Blue big-head Naughty](examples/blue-big-head-naughty.md))
is built with this tool for both games and works in game on both, together
with the blue fur and an animation swap.

## Importing a new model

**Import a new model** (Tools page under Textures and models, or a
container's Model editing tab) puts a different model in a character, in
either game: any number of vertices and triangles, skinned to the
character's own skeleton.

```
SeamRipper.exe --tool mesh_replace.py export naughtybear.lu --mesh 743299d0 --rigged -o naughty_rig.glb
SeamRipper.exe --tool mesh_replace.py import naughtybear.lu --mesh 743299d0 ^
    --glb my_model.glb --collapse 1,2 --all-copies --patch MyModel.srpatch
```

1. **Export with the skeleton.** `export --rigged` (or tick *With the
   skeleton* on Export a model for editing) saves the model with an
   armature: one joint per skeleton bone, named `b000`, `b001`, ... The
   number is the bone; anything after it (`b078_L_upper`) is only a label.
   The armature is at the character's bind pose (Naughty: a T-pose). Parts
   that hang on a bone with a rest scale (Naughty's two hand accessories,
   bone 78 at 0.015) are left out: Blender bones cannot hold a rest scale.
2. **Fit your model in Blender.** File > Import > glTF 2.0. Put your model
   over the character in the armature's rest pose, at the character's size,
   and give it an Armature modifier on the imported armature with vertex
   groups named after the bones (`b009...`). Weight painting, or Data
   Transfer from the exported part (Vertex Data > Vertex Groups, nearest
   face), both work.
3. **Name each object after the part it replaces**: `sub00` for Naughty's
   body. Several objects for one part are fine (`sub00`, `sub00.001`):
   they are joined. Export glTF 2.0 (.glb) with **Data > Armature** and
   **Skinning** on; do not apply the Armature modifier.
4. **Import.** Each `subNN` replaces that part: it keeps the part's
   textures, material and skin palette, takes your vertices, triangles,
   normals, UVs and weights. `--collapse 1,2` hides parts you have no
   replacement for (nothing is drawn). The shadow-volume copy is kept.
5. **Textures.** The part keeps the character's texture slots, so paint
   your model's picture to the slot's size (`--resize` scales it) and put it
   in with **Replace a texture**. Maps painted for the old model (normal
   map, masks) show the old model's details on yours: replace the normal map
   with `--image flat-normal` and masks with `black` or `clear`.

What the import needs and checks:

* **Weights.** Up to four bones per vertex (more are cut to the four
  heaviest). Every weighted bone must be in the part's palette (`export
  --rigged` prints its size: Naughty's body holds 69 bones in Naughty Bear,
  96 in Panic in Paradise); weights on other bones move to the nearest
  parent joint the palette holds, and the import says so.
* **Proportions.** The game's animations set every bone's position, not
  only its rotation, so a model always moves with the character's own
  joint positions. Fit it to the character's skeleton; a human on Naughty
  gets Naughty's short legs and big head.
* **Naughty Bear** writes the new vertices at the end of the model's
  record, which grows, and lays the container out again. A record can grow
  until the container would need another 1 MB compression segment (Naughty's
  containers have at least 480 KB to spare); past that the import is
  refused with a message.
* **Panic in Paradise** cannot take a record that changes size (the game
  hangs on load), so the new part must fit where the old one was. The
  import says how many bytes it needs and how many there are; Naughty's body
  has about 138 KB, roughly 2,000 vertices with 3,500 triangles. Triangles
  are written as a list where that fits and as a strip (about 40% smaller)
  where it does not.
* Vertices are positions in the bind pose: the file's armature at rest,
  through each joint's inverse bind matrix, so a model moved with its
  armature in Blender comes out where the armature put it.

### Models from MMD (.pmx)

MMD models are PMX files, not GLB. Convert in Blender with the **MMD Tools**
add-on (Edit > Preferences > Get Extensions, search "MMD Tools"):

1. File > Import > MMD model (.pmx). MMD models face the other way and use
   their own bone names (センター, 上半身, 左腕, ...); MMD Tools imports
   them facing Blender's -Y like a glTF character, so no turn is needed.
2. Import the character's rigged GLB alongside it. Pose the MMD armature
   into the character's rest pose (arms up from the A-pose into Naughty's
   T-pose), scale and stretch it onto the bear (Naughty is about 2.2 units
   tall), then apply the pose as rest (Pose > Apply > Apply Pose as Rest
   Pose) and apply the Armature modifier on the MMD mesh.
3. Rename the MMD vertex groups to the character's bones (upper body to the
   spine bones, 左腕 to the left upper arm, and so on), or delete them and
   transfer weights from the exported `sub00` with a Data Transfer modifier.
   Join the meshes into one object named `sub00`, parent it to the
   character's armature with an Armature modifier, and export as in step 3
   above.

MMD models usually have several pictures (one per material); the
character's part has one picture slot for its colour, so lay the pictures
out in one image (an atlas) and move each material's UVs into its square.

Checked against the game files: every retail skinned part in both games
(Naughty Bear 293 meshes, Panic in Paradise 569) goes through the import
path with its vertex buffer coming back byte for byte, the same triangles,
and every other part untouched; GLB export and import through Blender 4.4
keeps Naughty's body to 2e-6. In game: a new model works in Naughty
Bear (tested in Xenia); Panic in Paradise is not yet tested in game.

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
  it). They are the base size only; **Export textures for editing** with DDS
  keeps every mip level. Earlier builds exported textures that are not
  square (240 of them across both games) with width and height swapped, so
  they came out scrambled or half black; export them again.
* **Models:** `.obj` and `.mtl`, and `.glb` with textures. Which way is up
  varies from model to model, so rotate in your 3D program.
* **Animations:** rigged `.glb` files with the clips baked in, and CSV tables.
* **Sounds:** `.wav`.

## Known limits

Each of these is explained in its section above; this is the short list.

* **Imported models get the character's proportions.** The animations set
  every bone's position, so a human on Naughty moves with Naughty's short
  legs and big head ([Importing a new model](#importing-a-new-model)).
* **Panic in Paradise keeps every record's size.** A new model has to fit in
  the space the old one had (about 2,000 vertices for Naughty's body), and a
  longer animation needs a donor record to trade with. Naughty Bear has no
  such limit short of a new 1 MB compression segment.
* **Naughty's two hand accessories** (bone 78) are left out of `export
  --rigged`, because Blender bones cannot hold their rest scale. They stay as
  shipped, or are hidden with `--collapse`.
* **Blender must export attributes** (**Include > Data > Attributes**) for
  Replace a model, or the vertices cannot be matched back.
* **Stacked patches and `--check`.** Two patches applied to the same file
  both work, but `--check` then reports that file as matching neither,
  because it compares the whole file. Put edits to one file in one patch
  (`make` takes any number of `--texture`, `--mesh` and other edits).
* **Patched Naughty Bear files are larger** than the originals: the parts an
  edit rewrites are stored uncompressed ([Patches and
  backups](patches.md#how-a-patch-is-stored)).
* **A new model in Panic in Paradise is not yet tested in game.** It passes
  every file-side check; Naughty Bear is tested in game.

## What isn't here

Putting an edited sound back into a container is not covered; we only tested
getting sounds out.

If a texture format isn't supported yet, the tool saves the raw data as a
`.texdata.bin` and says so (see
[More troubleshooting](technical.md#more-troubleshooting)).
