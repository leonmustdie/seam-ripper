#!/usr/bin/env python3
r"""nb_inject.py - apply ONE edited function into a game .lu, keeping every
other function's original bytecode byte-for-byte.

You give: the .lu, the chunk (by --name or --hash), your edited full source,
and which function you changed (--path, e.g. 0_3 from luadec's
`-- function num :` comment). It recompiles your source, lifts only that
function's proto, splices it into the original chunk, and rewrites the .lu.

Because non-target functions come from the ORIGINAL chunk, the decompiler's
fidelity on the rest of the file is irrelevant. The target function must keep
its original upvalue count and parameter count (edit the body, not the
signature) and the source must compile to the same function-tree shape.

usage:
  nb_inject.py game.lu --name globalmenu edited.lua --path 0_7 -o game_new.lu
"""
import argparse, subprocess, sys, shutil
from pathlib import Path
import os as _os, tempfile as _tf
TMPDIR = _tf.gettempdir()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lua_recompile, lua_chunk_swap, proto360
from naughty_lu import LuFile

LUAC = HERE / "luac51.exe"

def find_luac(explicit):
    if explicit: return explicit
    for n in ("luac51", "luac5.1", "luac"):
        p = shutil.which(n)
        if p: return p
    if Path(LUAC).exists(): return str(LUAC)
    sys.exit("luac not found; pass --luac")

def parse_path(s):
    # "0_7" or "0" -> [7] (drop leading top index 0); "0_3_1" -> [3,1]
    parts = [int(x) for x in s.split("_")]
    return parts[1:] if parts and parts[0] == 0 else parts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu"); ap.add_argument("source")
    ap.add_argument("--name"); ap.add_argument("--hash")
    ap.add_argument("--path", required=True, help="luadec function num, e.g. 0_7")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luac")
    a = ap.parse_args()
    if not (a.name or a.hash): sys.exit("give --name or --hash")
    luac = find_luac(a.luac)

    lu = LuFile(a.lu); img = lu.image
    target = None
    for r in lu.records:
        if a.hash and r.hash == int(a.hash, 16): target = r; break
        if a.name and a.name.encode() in img[r.offset:r.offset+r.size]: target = r; break
    if target is None: sys.exit("chunk not found in .lu")
    orig_chunk = bytes(img[target.offset:target.offset+target.size])
    i = orig_chunk.find(b"\x1bLua")
    if i < 0: sys.exit("target record is not a Lua script chunk")
    # wrapper +0x1c = bytecode image size; the footer (script name) follows it.
    # splice on bytecode ONLY; lua_chunk_swap re-appends the footer itself.
    import struct as _st
    bc_size = _st.unpack_from(">I", orig_chunk, 0x1c)[0]
    orig_img = orig_chunk[i:i+bc_size]

    # recompile edited source -> 360 image
    c = subprocess.run([luac, "-s", "-o", _os.path.join(TMPDIR, "_inj.luac"), a.source],
                       capture_output=True, text=True)
    if c.returncode: sys.exit(f"luac failed:\n{c.stderr or c.stdout}")
    new_img = lua_recompile.convert(Path(_os.path.join(TMPDIR, "_inj.luac")).read_bytes(), want_hash=True)

    path = parse_path(a.path)
    # signature guard: nups + nparams of target must match
    ot, _ = proto360.parse(orig_img); nt, _ = proto360.parse(new_img)
    try:
        spliced_img = proto360.splice(orig_img, new_img, path)
    except ValueError as e:
        sys.exit(f"splice refused: {e}")

    # rewrap chunk (fix wrapper size fields), then rebuild .lu
    new_chunk = lua_chunk_swap.swap(orig_chunk, spliced_img)
    Path(_os.path.join(TMPDIR, "_newchunk.bin")).write_bytes(new_chunk)
    sys.argv = ["lu_chunk_replace.py", a.lu,
                ("--hash" if a.hash else "--name"), (a.hash or a.name),
                _os.path.join(TMPDIR, "_newchunk.bin"), "-o", a.out]
    import lu_chunk_replace
    lu_chunk_replace.main()
    print(f"injected function {a.path} only; all other functions byte-unchanged")

if __name__ == "__main__":
    main()
