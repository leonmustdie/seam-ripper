#!/usr/bin/env python3
r"""lua_inject.py - one-shot: edited .lua source -> patched .lu, in place.

Runs the whole write chain:
  luac51 -s  ->  lua_recompile (360 fmt)  ->  lua_chunk_swap (wrap)  ->
  lu_chunk_replace (rebuild .lu raw, fix offsets)

You give it: the game .lu, which chunk (hash or name), and your edited .lua.
It finds the original chunk's wrapper inside the .lu automatically, so you
don't pass it separately.

Usage:
  lua_inject.py game.lu --name naughtybearsupportedcontrols edited.lua -o game_new.lu
  lua_inject.py game.lu --hash 0x88bdf6af edited.lua -o game_new.lu
  # if luac isn't on PATH as luac51/luac5.1/luac, point at it:
  lua_inject.py ... --luac C:\tools\luac51.exe
"""
import argparse, struct, subprocess, sys, shutil, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile
import lua_recompile, lua_chunk_swap

def find_luac(explicit):
    if explicit:
        return explicit
    for name in ("luac51", "luac5.1", "luac"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("luac not found on PATH; pass --luac luac51 path")

def u32(b, o): return struct.unpack_from(">I", b, o)[0]

def main():
    ap = argparse.ArgumentParser(description="Compile + inject edited lua into a lu.")
    ap.add_argument("lu")
    ap.add_argument("source", help="your edited .lua")
    ap.add_argument("--hash")
    ap.add_argument("--name")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luac", help="path to luac 5.1 (default: search PATH)")
    ap.add_argument("--keep", action="store_true", help="keep temp intermediates")
    a = ap.parse_args()
    if not (a.hash or a.name):
        sys.exit("specify --hash or --name to pick the chunk")

    luac = find_luac(a.luac)
    lu = LuFile(a.lu); img = lu.image

    # locate target record + pull its ORIGINAL chunk (for the wrapper/footer)
    target = None
    for r in lu.records:
        if a.hash and r.hash == int(a.hash, 16): target = r; break
        if a.name and a.name.encode() in img[r.offset:r.offset+r.size]: target = r; break
    if target is None:
        sys.exit("chunk not found in .lu")
    orig_chunk = bytes(img[target.offset:target.offset+target.size])
    if orig_chunk.find(b"\x1bLua") < 0:
        sys.exit("target record is not a Lua script chunk")

    tmp = Path(tempfile.mkdtemp(prefix="luainject_"))
    luac_out = tmp/"std.luac"
    bc360 = tmp/"chunk360.bin"
    origbin = tmp/"orig.bin"
    newchunk = tmp/"newchunk.bin"
    origbin.write_bytes(orig_chunk)

    # 1. compile (stripped)
    r = subprocess.run([luac, "-s", "-o", str(luac_out), a.source],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"luac failed:\n{r.stderr or r.stdout}")

    # 2. standard -> 360 bytecode
    bc360.write_bytes(lua_recompile.convert(luac_out.read_bytes(), want_hash=True))

    # 3. wrap new bytecode in the original chunk's wrapper/footer
    newchunk.write_bytes(lua_chunk_swap.swap(orig_chunk, bc360.read_bytes()))

    # 4. rebuild .lu raw with the swapped chunk (offsets fixed)
    sys.argv = ["lu_chunk_replace.py", a.lu,
                ("--hash" if a.hash else "--name"), (a.hash or a.name),
                str(newchunk), "-o", a.out]
    import lu_chunk_replace
    lu_chunk_replace.main()

    if not a.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"intermediates kept in {tmp}")
    print(f"DONE: {a.source} compiled + injected into {a.out}")
    print(f"  chunk {target.hash:#x}: {target.size}B -> {len(newchunk.read_bytes()) if a.keep else 'updated'}")

if __name__ == "__main__":
    main()
