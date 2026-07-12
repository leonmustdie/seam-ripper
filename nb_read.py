#!/usr/bin/env python3
r"""nb_read.py - one call: a .lu + a chunk name -> readable, tagged Lua source.

Does the whole read half for you: pulls the chunk out of the .lu, transcodes
it to a standard .luac, runs nb_decompile, and leaves you a <chunk>.lua whose
functions are stamped FAITHFUL / DIVERGENT so you know what is safe to edit.

usage (Windows, no luadec):
  python nb_read.py game.lu naughtybearhatbonus -o hatbonus.lua
  # uses unluac.jar + luac51.exe sitting next to the scripts

  python nb_read.py game.lu --hash 0xd88bd830 -o out.lua --luadec   # luadec backend
"""
import argparse, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from naughty_lu import LuFile
import lua_decompile as L

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu")
    ap.add_argument("name", nargs="?", help="chunk name (substring of the script)")
    ap.add_argument("--hash", help="chunk hash instead of name, e.g. 0xd88bd830")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luadec", action="store_true",
                    help="use the luadec backend instead of unluac")
    ap.add_argument("--jar", default=str(HERE / "unluac.jar"))
    ap.add_argument("--luac", default=str(HERE / "luac51.exe"))
    ap.add_argument("--annotate-roots", nargs="*", default=[],
                    help="extract dir(s) to resolve hash names as comments")
    a = ap.parse_args()
    if not (a.name or a.hash):
        sys.exit("give a chunk name or --hash")

    lu = LuFile(a.lu); img = lu.image
    target = None
    for r in lu.records:
        if a.hash and r.hash == int(a.hash, 16): target = r; break
        if a.name and a.name.encode() in img[r.offset:r.offset+r.size]: target = r; break
    if target is None:
        sys.exit(f"chunk not found in {a.lu}")
    chunk = bytes(img[target.offset:target.offset+target.size])
    if b"\x1bLua" not in chunk:
        sys.exit("that record is not a Lua script chunk")

    # transcode the live chunk -> standard .luac (raw hashes, exact round-trip)
    hashes = L.build_hash_dict(a.annotate_roots) if a.annotate_roots else {}
    std = L.transcode(chunk, hashes, raw_hashes=True)
    tmp = Path(tempfile.mkdtemp(prefix="nbread_")) / "chunk.luac"
    tmp.write_bytes(std)

    cmd = [sys.executable, str(HERE / "nb_decompile.py"), str(tmp),
           "-o", a.out, "--luac", a.luac]
    if a.luadec:
        pass  # nb_decompile defaults to luadec
    else:
        cmd += ["--unluac", "--jar", a.jar]
    if a.annotate_roots:
        cmd += ["--annotate-roots", *a.annotate_roots]
    print(f"chunk {target.hash:#010x}  ({target.size} bytes) -> decompiling...")
    subprocess.run(cmd)
    print(f"\nopen {a.out}; edit only functions tagged FAITHFUL, body only.")
    print(f"note the `-- function num : PATH` of the function you edit; pass it "
          f"to nb_apply.py / nb_inject.py as --path PATH.")

if __name__ == "__main__":
    main()
