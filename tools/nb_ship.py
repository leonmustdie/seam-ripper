#!/usr/bin/env python3
r"""nb_ship.py - edit the whole file like normal code; ship the change.

You do NOT pick functions or paths. You edit chunk.lua freely and run this.
It works out which functions you actually changed (by comparing instructions +
constants, so line-number noise is ignored), injects ONLY those, and keeps
every other function's original game bytes. It refuses only if you edited a
function the decompiler can't reproduce faithfully (where your edit would sit
on top of a wrong reconstruction) - and tells you which.

usage (Windows):
  python nb_ship.py game.lu naughtybearhatbonus chunk.lua -o out.lu --stage <build>\assets\lu
  python nb_ship.py game.lu --hash 0xd88bd830 chunk.lua -o out.lu

Add --luadec to use the luadec backend (needs luadec built).
"""
import argparse, subprocess, sys, shutil, tempfile
from pathlib import Path
import os as _os, tempfile as _tf
TMPDIR = _tf.gettempdir()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from naughty_lu import LuFile
import lua_decompile as L, lua_recompile, lua_chunk_swap, proto360
import nb_decompile

LUAC   = HERE / "luac51.exe"
UNLUAC = HERE / "unluac.jar"

def find_luac(explicit):
    if explicit: return explicit
    for n in ("luac51", "luac5.1", "luac"):
        p = shutil.which(n)
        if p: return p
    if LUAC.exists(): return str(LUAC)
    sys.exit("luac not found; pass --luac")

def compile_to_360(src_path, luac):
    r = subprocess.run([luac, "-s", "-o", _os.path.join(TMPDIR, "_ship.luac"), str(src_path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return lua_recompile.convert(Path(_os.path.join(TMPDIR, "_ship.luac")).read_bytes(), want_hash=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu"); ap.add_argument("name", nargs="?")
    ap.add_argument("source", help="your edited chunk .lua")
    ap.add_argument("--hash")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luac", default=None)
    ap.add_argument("--jar", default=str(UNLUAC))
    ap.add_argument("--luadec", action="store_true")
    ap.add_argument("--stage", help="build assets\\lu folder to copy result into")
    a = ap.parse_args()
    if not (a.name or a.hash): sys.exit("give a chunk name or --hash")
    luac = find_luac(a.luac)

    # locate + lift the original chunk
    lu = LuFile(a.lu); img = lu.image
    target = None
    for r in lu.records:
        if a.hash and r.hash == int(a.hash, 16): target = r; break
        if a.name and a.name.encode() in img[r.offset:r.offset+r.size]: target = r; break
    if target is None: sys.exit("chunk not found in .lu")
    chunk = bytes(img[target.offset:target.offset+target.size])
    i = chunk.find(b"\x1bLua")
    if i < 0: sys.exit("that record is not a Lua script chunk")
    import struct
    bc = struct.unpack_from(">I", chunk, 0x1c)[0]
    orig_img = chunk[i:i+bc]

    # baseline: re-decompile the ORIGINAL chunk the same way nb_read did
    std = L.transcode(chunk, {}, raw_hashes=True)
    tmp = Path(tempfile.mkdtemp(prefix="ship_")); tlc = tmp/"c.luac"; tlc.write_bytes(std)
    if a.luadec:
        base_src, _ = nb_decompile.decompile(str(tlc))
        import rename_luadec; base_src = rename_luadec.apply(base_src)
    else:
        base_src, _ = nb_decompile.decompile_unluac(str(tlc), a.jar)
    (tmp/"base.lua").write_text(base_src, encoding="utf-8")

    # three logic views: original game, baseline recompile, your edited recompile
    try:
        base_img = compile_to_360(tmp/"base.lua", luac)
        edit_img = compile_to_360(a.source, luac)
    except RuntimeError as e:
        sys.exit(f"a source failed to compile:\n{e}")

    Lorig = proto360.decode_logic(orig_img)
    Lbase = proto360.decode_logic(base_img)
    Ledit = proto360.decode_logic(edit_img)
    if not (set(Lorig)==set(Lbase)==set(Ledit)):
        sys.exit("function structure changed (added/removed a function, or the "
                 "decompile shape differs). Edit bodies only.")

    divergent = {p for p in Lorig if Lbase[p] != Lorig[p]}   # decompiler got p wrong
    edited    = {p for p in Lorig if Ledit[p] != Lbase[p]}   # you changed p
    # leaf-only (a parent's logic also 'changes' when a child does; we splice leaves)
    def is_leaf(p, s):
        return not any(q!=p and q.startswith(p+"_") for q in s)
    edited_leaf = {p for p in edited if is_leaf(p, edited)}

    unsafe = edited_leaf & divergent
    if unsafe:
        names = ", ".join(sorted(unsafe))
        sys.exit(f"REFUSED: you edited function(s) {names} that the decompiler "
                 f"could not reproduce faithfully. Your edit there would ship "
                 f"wrong code. Leave those functions unchanged, or decompile "
                 f"this chunk with the other backend (--luadec) and retry.")
    if not edited_leaf:
        print("no function-level changes detected; nothing to inject.")
        if a.out: shutil.copy2(a.lu, a.out)
        return

    # splice each edited function into the original chunk image
    cur = orig_img
    for p in sorted(edited_leaf):
        path = [int(x) for x in p.split("_")[1:]]
        cur = proto360.splice(cur, edit_img, path)
    new_chunk = lua_chunk_swap.swap(chunk, cur)
    Path(_os.path.join(TMPDIR, "_ship_chunk.bin")).write_bytes(new_chunk)

    sys.argv = ["lu_chunk_replace.py", a.lu,
                ("--hash" if a.hash else "--name"), (a.hash or a.name),
                _os.path.join(TMPDIR, "_ship_chunk.bin"), "-o", a.out]
    import lu_chunk_replace
    lu_chunk_replace.main()
    print(f"shipped {len(edited_leaf)} edited function(s): {', '.join(sorted(edited_leaf))}")
    print("all other functions kept original game bytes.")

    if a.stage:
        stage = Path(a.stage)
        if not stage.is_dir(): sys.exit(f"--stage dir missing: {stage}")
        dest = stage / Path(a.lu).name
        if dest.exists(): shutil.copy2(dest, dest.with_suffix(dest.suffix+".bak"))
        shutil.copy2(a.out, dest)
        print(f"staged -> {dest}; run the game to test.")

if __name__ == "__main__":
    main()
