# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Seam Ripper.
#
# Build (from this folder, on Windows):
#     py -m PyInstaller seamripper.spec
# Output: dist/SeamRipper/SeamRipper.exe  (one-folder build)
#
# One-folder, NOT one-file, on purpose: the GUI runs every tool as a
# subprocess of its own EXE (SeamRipper.exe --tool <script> ...). A one-file
# build would re-extract the whole ~150 MB bundle on every single tool run;
# the folder build launches tools instantly.

from PyInstaller.utils.hooks import collect_submodules

# Tool scripts ship as DATA files (editable/inspectable in the shipped
# folder, byte-identical to the repo) AND are declared as hiddenimports so
# the --tool shim can import them by module name and call their main().
# PyInstaller can't runpy.run_path a bundled .py as __main__, so the shim
# uses import + main() instead; see SeamRipper.py.
# Tool scripts live in tools/ in the repo (kept out of the root listing) but
# still ship as DATA files FLAT into the bundle root (dest "."), same as
# before the move — the --tool shim's importlib.import_module(stem) and the
# frozen sys.path.insert(0, BUNDLE) in SeamRipper.py don't know or care
# about the repo's source layout, only about where PyInstaller put things.
TOOLS_DIR = "tools"

TOOL_SCRIPTS = [
    "naughty_lu.py", "lu_convert.py", "lu_strings.py", "lu_autofix.py",
    "lu_grep.py", "lu_repack.py", "lu_sound.py", "lu_chunk_replace.py",
    "lua_decompile.py", "lua_recompile.py", "lua_chunk_swap.py",
    "lua_clean.py", "lua_annotate.py", "lua_readable.py", "lua_readall.py",
    "lua_inject.py", "nblua.py", "nb_read.py", "nb_decompile.py",
    "nb_inject.py", "nb_ship.py", "nb_apply.py", "pip_dump.py",
    "pip_gfx.py",
    "proto360.py", "bccmp.py", "rename_luadec.py", "widen_sizet.py",
    "verify_lzx.py", "lua_callsplit.py", "lua_batchedit.py", "lzx_encode.py",
]
# PiP dumper companions — present in the full repo; harmless to list if
# missing at build time? No: PyInstaller errors on missing datas, so these
# are appended only if they exist.
OPTIONAL_SCRIPTS = ["lu_rig.py", "pip_scripts.py"]

import os
BINARIES = ["luac51.exe", "unluac.jar", "luadec.exe",
            # independent LZX verifier used by verify_lzx.py; the ship gate
            # REFUSES if this is missing, so it must be built and bundled.
            # Build for the target OS from tools/lzxverify_src/ (see build.sh).
            "lzxverify.exe" if os.name == "nt" else "lzxverify"]


def _in_tools(name):
    return os.path.join(TOOLS_DIR, name)


datas = [(_in_tools(s), ".") for s in TOOL_SCRIPTS if os.path.exists(_in_tools(s))]
datas += [(_in_tools(s), ".") for s in OPTIONAL_SCRIPTS if os.path.exists(_in_tools(s))]
datas += [(_in_tools(b), ".") for b in BINARIES if os.path.exists(_in_tools(b))]
datas += [(p, ".") for p in ("seamripper.ico", "seamripper_256.png",
                             "seamripper_64.png") if os.path.exists(p)]

# Stdlib the tool scripts need at runtime. PyInstaller only follows imports
# it can see in SeamRipper.py; the tools are data files, so their imports
# must be declared here. Pillow is optional (PNG texture output + GLB
# texture embedding) but included when installed.
hiddenimports = [
    "argparse", "glob", "zlib", "keyword", "collections", "tempfile",
    "subprocess", "shutil", "struct", "runpy", "math", "json", "shlex",
    "importlib", "io", "re", "base64", "hashlib", "binascii",
    "dataclasses", "enum",
    "numpy",  # lu_rig.py's bind-pose matrix math; third-party, PyInstaller's
              # Analysis never sees it since tool scripts bundle as data
              # files (see comment below), so it needs to be named explicitly.
]
# the tool scripts themselves, so import_module(name) resolves in the frozen
# app and PyInstaller follows their imports (naughty_lu, lu_convert, etc.)
_tool_mods = [os.path.splitext(s)[0] for s in TOOL_SCRIPTS + OPTIONAL_SCRIPTS
              + ["pip_gfx.py"] if os.path.exists(_in_tools(s))]
hiddenimports += sorted(set(_tool_mods))
try:
    import PIL  # noqa: F401
    hiddenimports += collect_submodules("PIL")
except ImportError:
    pass

a = Analysis(
    ["SeamRipper.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SeamRipper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # set True for a debug build with a console window
    icon="seamripper.ico",  # multi-res app icon (16..256 px)
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SeamRipper",
)
