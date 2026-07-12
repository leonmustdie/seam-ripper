#!/usr/bin/env python3
r"""lua_annotate.py - add readable comments to __hash_0x placeholders.

Decompiling with raw hashes yields exact, recompilable placeholders like
"__hash_0x139ad1f4" but they are unreadable. This appends the resolved name
(from the CRC32 dictionary) as a line comment, so you read the name and the
placeholder still round-trips exactly. luac strips comments, so annotation
does not change the bytecode.

  R = "__hash_0x139ad1f4"            -->  R = "__hash_0x139ad1f4"  -- AnimMgr
"""
import argparse, re, sys, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lua_decompile as L

PH = re.compile(r'"(__hash_0x([0-9a-fA-F]{1,8}))"')

def annotate(src, rev):
    out = []
    for line in src.split("\n"):
        names = []
        for m in PH.finditer(line):
            val = int(m.group(2), 16)
            nm = rev.get(val)
            if nm:
                names.append(nm)
        if names and "--" not in line:
            line = line + "  -- " + ", ".join(names)
        out.append(line)
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--roots", nargs="+", default=["."], help="chunk roots to mine the hash dict from")
    a = ap.parse_args()
    hashes = L.build_hash_dict(a.roots)
    rev = {h: n for h, n in hashes.items()}
    Path(a.out).write_text(annotate(Path(a.src).read_text(encoding="utf-8", errors="replace"), rev),
                           encoding="utf-8")
    print(f"annotated {a.src} -> {a.out}")

if __name__ == "__main__":
    main()
