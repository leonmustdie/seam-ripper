"""Every command-line tool as a form spec, grouped by what you want to do."""

LU = "Lu container (*.lu);;All (*.*)"
TXT = "Text (*.txt);;All (*.*)"
GLB = "glTF binary (*.glb);;All (*.*)"
ISO = "Xbox 360 disc image (*.iso);;All (*.*)"

F_FILE = {"label": ".lu file", "kind": "openfile", "patterns": LU, "required": True, "fill": "file"}
F_FILES = {"label": ".lu files or folder", "kind": "paths", "required": True, "fill": "paths"}
F_OUT = {"label": "Save into folder", "kind": "folder", "flag": "-o", "fill": "out"}

GROUPS = ["Text", "Scripts", "Extract and convert", "Sound", "Advanced"]

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
