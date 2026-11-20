"""Every command-line tool as a form spec, grouped by what you want to do."""

LU = "Lu container (*.lu);;All (*.*)"
TXT = "Text (*.txt);;All (*.*)"
GLB = "glTF binary (*.glb);;All (*.*)"
SRPATCH = "Seam Ripper patch (*.srpatch);;All (*.*)"
ISO = "Xbox 360 disc image (*.iso);;All (*.*)"
PIC = "Pictures (*.png *.dds *.tga *.bmp *.jpg);;All (*.*)"

F_FILE = {"label": ".lu file", "kind": "openfile", "patterns": LU, "required": True, "fill": "file"}
F_FILES = {"label": ".lu files or folder", "kind": "paths", "required": True, "fill": "paths"}
F_OUT = {"label": "Save into folder", "kind": "folder", "flag": "-o", "fill": "out"}

GROUPS = ["Text", "Scripts", "Extract and convert", "Animation", "Textures and models",
          "Sound", "Advanced"]

TOOLS = [
    # ---- Text
    {"group": "Text", "title": "Export strings", "script": "lu_strings.py", "sub": "extract",
     "help": "Save a container's subtitles and menu text to a .txt you can edit "
             "(language files like global.en_us.lu).",
     "fields": [dict(F_FILE),
                {"label": "Save as .txt", "kind": "savefile", "flag": "-o", "patterns": TXT}]},
    {"group": "Text", "title": "Import strings", "script": "lu_strings.py", "sub": "apply",
     "help": "Put your edited text back. It's saved as a new file; the original "
             "isn't touched.",
     "fields": [dict(F_FILE),
                {"label": "Edited .txt", "kind": "openfile", "patterns": TXT, "required": True},
                {"label": "Save as .lu", "kind": "savefile", "flag": "-o", "patterns": LU},
                {"label": "Check the result", "kind": "flag", "flag": "--verify", "default": True}]},
    {"group": "Text", "title": "Spelling report", "script": "lu_autofix.py", "sub": "report",
     "help": "List spelling and spacing problems in the text of some containers. "
             "Report only: nothing is changed.",
     "fields": [dict(F_FILES)]},
    {"group": "Text", "title": "Spelling fix", "script": "lu_autofix.py", "sub": "fix",
     "help": "Write corrected copies of containers into a folder.",
     "fields": [dict(F_FILES),
                {"label": "Save into folder", "kind": "folder", "flag": "-o", "required": True,
                 "fill": "out"},
                {"label": "Also fix spacing", "kind": "flag", "flag": "--spacing"}]},
    {"group": "Text", "title": "Search text", "script": "lu_grep.py",
     "help": "Search the subtitle and menu text of many containers.",
     "fields": [{"label": "Search for", "kind": "text", "required": True},
                dict(F_FILES, fill="folder"),
                {"label": "Ignore case", "kind": "flag", "flag": "-i"},
                {"label": "Regular expression", "kind": "flag", "flag": "-e"}]},
    # ---- Scripts
    {"group": "Scripts", "title": "Find a script", "script": "pip_scripts.py", "sub": "find",
     "help": "Find which containers have a script, like 'gamemodes'.",
     "fields": [{"label": "Script name", "kind": "text", "required": True},
                dict(F_FILES, label="Containers or folder", fill="folder")]},
    {"group": "Scripts", "title": "Export all scripts", "script": "lu_lua.py", "sub": "export",
     "help": "Save every script in the game as text files, plus an INDEX.txt of "
             "where each one is.",
     "fields": [{"label": "Game folder", "kind": "folder", "required": True, "fill": "paths"},
                {"label": "Save into folder", "kind": "folder", "flag": "-o", "required": True,
                 "fill": "out"}]},
    {"group": "Scripts", "title": "Extract Panic in Paradise source", "script": "pip_scripts.py",
     "sub": "extract",
     "help": "Rebuild PiP's original script folders from extracted chunks (run "
             "'Extract chunks' first).",
     "fields": [{"label": "Extracted folder(s)", "kind": "paths", "required": True},
                {"label": "Save into folder", "kind": "folder", "flag": "-o", "required": True,
                 "fill": "out"},
                {"label": "One flat folder", "kind": "flag", "flag": "--flat"}]},
    {"group": "Scripts", "title": "Inject Panic in Paradise script", "script": "pip_scripts.py",
     "sub": "inject",
     "help": "The old way to put edited .lua files into a PiP container. Editing in "
             "Files and using Ship is safer.",
     "fields": [{"label": "Original .lu", "kind": "openfile", "patterns": LU,
                 "required": True, "fill": "file"},
                {"label": "Edited .lua file(s)", "kind": "paths", "required": True},
                {"label": "Skip the Lua check", "kind": "flag", "flag": "--force"},
                {"label": "Save as .lu", "kind": "savefile", "flag": "-o", "patterns": LU,
                 "required": True}]},
    # ---- Extract and convert
    {"group": "Extract and convert", "title": "Extract game disc (.iso)",
     "script": "xiso_extract.py", "sub": "extract",
     "help": "Copy the game files off a Naughty Bear disc image so you can open and "
             "edit them.",
     "fields": [{"label": "Disc image", "kind": "openfile", "patterns": ISO,
                 "required": True},
                {"label": "Save into folder", "kind": "folder", "flag": "-o",
                 "required": True},
                {"label": "Only the lu folder", "kind": "flag", "flag": "--lu-only"}]},
    {"group": "Extract and convert", "title": "Extract chunks", "script": "naughty_lu.py",
     "sub": "extract",
     "help": "Pull everything out of containers, sorted by type. Then run 'Convert "
             "textures and models' on the result.",
     "fields": [dict(F_FILES, label=".lu files or folder"), dict(F_OUT, required=True)]},
    {"group": "Extract and convert", "title": "Convert textures and models",
     "script": "lu_convert.py",
     "help": "Turn extracted chunks into DDS and PNG textures and OBJ and GLB models "
             "(PNG needs Pillow).",
     "fields": [{"label": "Extracted chunks", "kind": "paths", "required": True},
                {"label": "Save into folder", "kind": "folder", "flag": "-o", "fill": "out"},
                {"label": "OBJ only (no GLB)", "kind": "flag", "flag": "--no-glb"}]},
    {"group": "Extract and convert", "title": "Character model (GLB)", "script": "lu_rig.py",
     "help": "Export a skinned character or costume piece with its skeleton from an "
             "extracted unit folder.",
     "fields": [{"label": "Extracted unit folder", "kind": "paths", "required": True},
                {"label": "Save as .glb", "kind": "savefile", "flag": "-o", "patterns": GLB,
                 "required": True},
                {"label": "Force texture hash (hex, optional)", "kind": "text",
                 "flag": "--texture"}]},
    {"group": "Extract and convert", "title": "Menu movies (Panic in Paradise)",
     "script": "pip_gfx.py",
     "help": "Extract the Scaleform menu movies (.gfx) and the pictures inside them as PNG.",
     "fields": [dict(F_FILES, label=".lu or chunk files"), dict(F_OUT),
                {"label": "Keep DDS files", "kind": "flag", "flag": "--dds"}]},
    {"group": "Extract and convert", "title": "Dump a whole game (Panic in Paradise)",
     "script": "pip_dump.py",
     "help": "One button: chunks, textures, models, Lua source, menu movies and audio "
             "lists for every container.",
     "fields": [{"label": "Game folder or files", "kind": "paths", "required": True,
                 "fill": "paths"},
                dict(F_OUT, required=True)]},
    {"group": "Extract and convert", "title": "Extract animations",
     "script": "anim_extract.py", "button": "Extract animations",
     "help": "Turn a game's containers into character models (GLB) with every "
             "animation baked in, one per skeleton. Decodes the containers first "
             "(and for Panic in Paradise rebuilds the scripts that name the "
             "clips); re-runs skip containers already decoded. Naughty Bear takes "
             "about 7 minutes, Panic in Paradise about 70. Needs numpy.",
     "extra_buttons": [{"label": "Preview plan", "args": ["--plan"],
                        "show_if": {"Game": "Panic in Paradise"}}],
     "fields": [{"label": "Game", "kind": "choice", "flag": "--game",
                 "choices": ["Naughty Bear", "Panic in Paradise"], "values": ["nb1", "pip"]},
                {"label": ".lu files or folder", "kind": "paths", "required": True,
                 "fill": "paths"},
                {"label": "Save into folder", "kind": "folder", "flag": "-o", "required": True,
                 "fill": "out"},
                {"label": "Only these skeletons (hex, optional)", "kind": "text",
                 "flag": "--rigs"},
                {"label": "Frames per second", "kind": "text", "flag": "--rate",
                 "default": "30"},
                {"label": "Leave out scale animation", "kind": "flag", "flag": "--no-scale"},
                {"label": "Decode every container again", "kind": "flag", "flag": "--redecode"},
                {"label": "Don't retarget missing skeletons", "kind": "flag",
                 "flag": "--no-retarget", "show_if": {"Game": "Naughty Bear"}},
                {"label": "Skip skeletons with no clips", "kind": "flag",
                 "flag": "--skip-empty-rigs", "show_if": {"Game": "Naughty Bear"}},
                {"label": "Also export unused skeletons", "kind": "flag", "flag": "--all-rigs",
                 "show_if": {"Game": "Panic in Paradise"}}]},
    # ---- Animation (writing clips back; both games)
    {"group": "Animation", "title": "List animation clips", "script": "anim_replace.py",
     "sub": "list",
     "help": "The animation clips stored in a container: hash, length, skeleton, "
             "name, and how many other containers hold their own copy. Also "
             "lists the skeletons it can borrow clips from (Naughty Bear).",
     "fields": [dict(F_FILE),
                {"label": "Only names containing", "kind": "text", "flag": "--find"}]},
    {"group": "Animation", "title": "Replace an animation", "script": "anim_replace.py",
     "sub": "swap", "button": "Replace",
     "help": "Make one or more clips play another clip instead (a hash, a clip "
             "name like st_dance_01, or a state name like st_walk, which picks "
             "every clip of that state). Naughty Bear: the donor is fitted to "
             "the target's skeleton with the bone map the game ships, so it must "
             "be on the same skeleton or one 'List animation clips' says it can "
             "borrow from. Panic in Paradise: clips name their bones, so any "
             "clip for the same body fits, and no record may change size: a "
             "donor bigger than the clip goes into its own record when it is "
             "stored in the same container (the two clips trade places), one "
             "clip per donor. The target keeps its own forward "
             "movement unless you tick the box. Only this container changes: "
             "other containers with their own copy of the clip (costumes, areas, "
             "multiplayer) still play the original. Save a .srpatch to share, a "
             "patched .lu, or both. Needs numpy.",
     "fields": [dict(F_FILE, label="Container with the clip"),
                {"label": "Clip(s) to replace", "kind": "text", "flag": "--clip",
                 "required": True},
                {"label": "Donor .lu or lu folder", "kind": "paths", "multi": False,
                 "flag": "--from", "required": True, "fill": "folder"},
                {"label": "Donor clip", "kind": "text", "flag": "--donor", "required": True},
                {"label": "Use the donor's movement too", "kind": "flag",
                 "flag": "--replace-movement"},
                {"label": "Save patch as", "kind": "savefile", "flag": "--patch",
                 "patterns": SRPATCH},
                {"label": "Patch name", "kind": "text", "flag": "--name"},
                {"label": "Save patched .lu as", "kind": "savefile", "flag": "-o",
                 "patterns": LU}]},
    # ---- Textures and models (writing them back; both games)
    {"group": "Textures and models", "title": "List textures", "script": "tex_replace.py",
     "sub": "list",
     "help": "The textures stored in a container: hash, width and height, format "
             "(DXT1, DXT5, ...) and mip levels.",
     "fields": [dict(F_FILE),
                {"label": "Only hashes containing", "kind": "text", "flag": "--find"}]},
    {"group": "Textures and models", "title": "Export textures for editing",
     "script": "tex_replace.py", "sub": "export",
     "help": "Save textures as PNG to edit (leave the hash empty for all of them). "
             "DDS keeps every mip level as stored.",
     "fields": [dict(F_FILE),
                {"label": "Texture hash(es), comma-separated", "kind": "text",
                 "flag": "--texture"},
                dict(F_OUT, required=True),
                {"label": "DDS instead of PNG", "kind": "flag", "flag": "--dds"}]},
    {"group": "Textures and models", "title": "Replace a texture", "script": "tex_replace.py",
     "sub": "replace", "button": "Replace",
     "help": "Put an edited picture back. It must have the texture's width and "
             "height; it is compressed in the texture's own format and its mip "
             "levels are made from it, so the record keeps its size (a DDS of the "
             "same format is taken as it is). A texture is often stored in "
             "several containers of the folder: keep 'Every copy' ticked or the "
             "game may still show the original where it loads another copy. "
             "Save a .srpatch to share, patched .lu files, or both. Instead of a "
             "file the picture can be a plain fill: type flat-normal, black, white "
             "or clear (for the normal map and masks of a character that gets a "
             "new model). Needs numpy and Pillow.",
     "fields": [dict(F_FILE, label="Container with the texture"),
                {"label": "Texture hash", "kind": "text", "flag": "--texture",
                 "required": True},
                {"label": "Picture (PNG or DDS)", "kind": "openfile", "flag": "--image",
                 "patterns": PIC, "required": True},
                {"label": "Scale the picture to the texture's size", "kind": "flag",
                 "flag": "--resize"},
                {"label": "Every copy in the folder", "kind": "flag",
                 "flag": "--all-copies", "default": True},
                {"label": "Save patch as", "kind": "savefile", "flag": "--patch",
                 "patterns": SRPATCH},
                {"label": "Patch name", "kind": "text", "flag": "--name"},
                {"label": "Save patched .lu files into", "kind": "folder",
                 "flag": "--out-dir"}]},
    {"group": "Textures and models", "title": "List models", "script": "mesh_replace.py",
     "sub": "list",
     "help": "The models (meshes) stored in a container: hash, parts, vertices "
             "and kind (skinned or rigid).",
     "fields": [dict(F_FILE),
                {"label": "Only hashes containing", "kind": "text", "flag": "--find"}]},
    {"group": "Textures and models", "title": "Export a model for editing",
     "script": "mesh_replace.py", "sub": "export",
     "help": "Save a model as a GLB to edit in Blender: one object per part "
             "(sub00, sub01, ...), textured where the picture is found.",
     "fields": [dict(F_FILE),
                {"label": "Model hash", "kind": "text", "flag": "--mesh", "required": True},
                {"label": "Save as .glb", "kind": "savefile", "flag": "-o", "patterns": GLB,
                 "required": True},
                {"label": "Leave the textures out", "kind": "flag", "flag": "--no-textures"},
                {"label": "With the skeleton (to make a new model on)", "kind": "flag",
                 "flag": "--rigged"}]},
    {"group": "Textures and models", "title": "Import a new model", "script": "mesh_replace.py",
     "sub": "import", "button": "Import",
     "help": "Put a new model in a character: any number of vertices and "
             "triangles. Start from 'Export a model for editing' with the skeleton "
             "ticked; in Blender fit the model to the armature in its rest pose, "
             "weight it to the b000 ... bones, name each object after the part it "
             "replaces (sub00, ...) and export glTF 2.0 (.glb) with skinning. The "
             "part keeps its textures and material (replace the textures "
             "separately). Parts to hide are collapsed (nothing drawn). Naughty "
             "Bear: the model's record grows. Panic in Paradise: the record keeps "
             "its size, so a part that does not fit is refused with the room it "
             "has. Save a .srpatch to share, patched .lu files, or both. Needs "
             "numpy.",
     "fields": [dict(F_FILE, label="Container with the model"),
                {"label": "Model hash", "kind": "text", "flag": "--mesh", "required": True},
                {"label": "New model .glb", "kind": "openfile", "flag": "--glb",
                 "patterns": GLB},
                {"label": "Parts to hide (e.g. 1,2)", "kind": "text", "flag": "--collapse"},
                {"label": "Index buffer", "kind": "choice", "flag": "--primitive",
                 "choices": ["Automatic", "Triangle list", "Triangle strip"],
                 "values": ["auto", "list", "strip"]},
                {"label": "Keep the record's size (Naughty Bear)", "kind": "flag",
                 "flag": "--in-place"},
                {"label": "Every identical copy in the folder", "kind": "flag",
                 "flag": "--all-copies", "default": True},
                {"label": "Save patch as", "kind": "savefile", "flag": "--patch",
                 "patterns": SRPATCH},
                {"label": "Patch name", "kind": "text", "flag": "--name"},
                {"label": "Save patched .lu files into", "kind": "folder",
                 "flag": "--out-dir"}]},
    {"group": "Textures and models", "title": "Replace a model", "script": "mesh_replace.py",
     "sub": "replace", "button": "Replace",
     "help": "Put an edited model back. Move, scale and sculpt freely, but do not "
             "add, delete, merge or split vertices: counts, skin weights and bones "
             "stay as shipped, so the model keeps its size. In Blender export "
             "glTF 2.0 (.glb) with Include > Data > Attributes ticked and keep "
             "the object names. The shipped normals turn with the surface "
             "unless you take the GLB's. Save a .srpatch to share, patched .lu "
             "files, or both. Needs numpy.",
     "fields": [dict(F_FILE, label="Container with the model"),
                {"label": "Model hash", "kind": "text", "flag": "--mesh", "required": True},
                {"label": "Edited .glb", "kind": "openfile", "flag": "--glb",
                 "patterns": GLB, "required": True},
                {"label": "Use the GLB's normals", "kind": "flag", "flag": "--glb-normals"},
                {"label": "Every identical copy in the folder", "kind": "flag",
                 "flag": "--all-copies", "default": True},
                {"label": "Save patch as", "kind": "savefile", "flag": "--patch",
                 "patterns": SRPATCH},
                {"label": "Patch name", "kind": "text", "flag": "--name"},
                {"label": "Save patched .lu files into", "kind": "folder",
                 "flag": "--out-dir"}]},
    # ---- Sound
    {"group": "Sound", "title": "Sound banks", "script": "lu_sound.py", "sub": "bank",
     "help": "Extract a container's sound effect bank. Anything unknown is saved "
             "raw.",
     "fields": [dict(F_FILES, label=".lu or extracted unit"), dict(F_OUT)]},
    {"group": "Sound", "title": "Sound streams", "script": "lu_sound.py", "sub": "streams",
     "help": "Convert loose .xma streams to WAV (needs ffmpeg).",
     "fields": [{"label": "Folder of .xma", "kind": "paths", "required": True}, dict(F_OUT)]},
    # ---- Advanced
    {"group": "Advanced", "title": "Container info", "script": "naughty_lu.py", "sub": "info",
     "help": "Header and record table of one or more containers.",
     "fields": [dict(F_FILES, label=".lu files")]},
    {"group": "Advanced", "title": "Decompress image", "script": "naughty_lu.py",
     "sub": "decompress",
     "help": "Write a container's decompressed data image to a .bin file.",
     "fields": [dict(F_FILE), {"label": "Save as .bin", "kind": "savefile", "flag": "-o"}]},
    {"group": "Advanced", "title": "Repack raw image", "script": "lu_repack.py",
     "help": "Rebuild a container from an edited raw image. Low level: for format work.",
     "fields": [dict(F_FILE),
                {"label": "Edited image", "kind": "openfile", "flag": "--image"},
                {"label": "Save as .lu", "kind": "savefile", "flag": "-o", "patterns": LU},
                {"label": "Check the result", "kind": "flag", "flag": "--verify"}]},
]


def by_group():
    """[(group, [spec])] in display order."""
    return [(g, [t for t in TOOLS if t["group"] == g]) for g in GROUPS]


def find(title):
    for t in TOOLS:
        if t["title"] == title:
            return t
    return None
