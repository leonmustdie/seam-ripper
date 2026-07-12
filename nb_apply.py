#!/usr/bin/env python3
r"""nb_apply.py - one call: inject your edited function AND re-stage the .lu
into your build's assets\lu so the game picks it up.

Wraps nb_inject.py, then copies the rebuilt .lu into --stage (your build's
lu folder). Keeps a .bak of whatever it overwrites there.

usage:
  python nb_apply.py game.lu --name naughtybearhatbonus hatbonus.lua --path 0_0 ^
      -o game_new.lu --stage .\out\build\win-amd64-release\assets\lu

If --stage is omitted it just injects (same as nb_inject.py).
"""
import argparse, subprocess, sys, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu"); ap.add_argument("source")
    ap.add_argument("--name"); ap.add_argument("--hash")
    ap.add_argument("--path", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luac", default=str(HERE / "luac51.exe"))
    ap.add_argument("--stage", help="build assets\\lu folder to copy the new .lu into")
    a = ap.parse_args()
    if not (a.name or a.hash):
        sys.exit("give --name or --hash")

    cmd = [sys.executable, str(HERE / "nb_inject.py"), a.lu, a.source,
           "--path", a.path, "-o", a.out, "--luac", a.luac]
    cmd += (["--hash", a.hash] if a.hash else ["--name", a.name])
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit("inject failed; not staging.")

    if a.stage:
        stage = Path(a.stage)
        if not stage.is_dir():
            sys.exit(f"--stage dir does not exist: {stage}")
        dest = stage / Path(a.lu).name      # stage under the ORIGINAL lu's name
        if dest.exists():
            shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
            print(f"backed up existing -> {dest.name}.bak")
        shutil.copy2(a.out, dest)
        print(f"staged {a.out} -> {dest}")
        print("run the game to test.")
    else:
        print("injected only (no --stage given).")

if __name__ == "__main__":
    main()
