#!/usr/bin/env python3
r"""nb_decompile.py - one .luac (transcoded, raw-hashes) -> readable, named,
modifiable Lua source, plus a per-function trust map.

Pipeline: widen size_t -> luadec --raw-hashes-equivalent -> rename locals ->
annotate hash names. Then recompile each function and compare to the original
bytecode, so every function is tagged FAITHFUL (safe to edit + splice) or
DIVERGENT (decompiler got it wrong; do not trust/edit, inject would be wrong).

The `-- function num : PATH` comments luadec emits are the splice paths used
by nb_inject.py.

usage:
  nb_decompile.py chunk.luac -o chunk.lua [--annotate-roots EXTRACT...]
"""
import argparse, subprocess, sys
from pathlib import Path
import os as _os, tempfile as _tf
TMPDIR = _tf.gettempdir()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import widen_sizet, rename_luadec, lua_recompile, bccmp, lua_clean
try:
    import lua_annotate, lua_decompile as L
    HAVE_ANNOTATE = True
except Exception:
    HAVE_ANNOTATE = False

LUADEC = HERE.parent / "luadec" / "luadec" / "luadec"
LUAC   = HERE.parent / "luadec" / "lua-5.1" / "src" / "luac"
UNLUAC = HERE / "unluac.jar"

def decompile(luac_path, luadec=str(LUADEC), no_widen=False):
    raw = Path(luac_path).read_bytes()
    feed = raw if no_widen else (widen_sizet.widen(raw) if raw[8] == 4 else raw)
    Path(_os.path.join(TMPDIR, "_w.luac")).write_bytes(feed)
    r = subprocess.run([luadec, _os.path.join(TMPDIR, "_w.luac")], capture_output=True, text=True)
    return r.stdout, raw

def decompile_unluac(luac_path, jar=str(UNLUAC)):
    """Windows-friendly backend: unluac.jar (size_t=4 native, no widen) + the
    existing lua_clean readability pass. No luadec, no luadec-luac needed."""
    raw = Path(luac_path).read_bytes()
    r = subprocess.run(["java", "-jar", jar, str(luac_path)],
                       capture_output=True, text=True)
    src = r.stdout
    if src.strip():
        src = lua_clean.clean_text(src)
    return src, raw

def faithful_map(orig_std, named_src, luac=str(LUAC)):
    """compile named_src, compare per-function to original. returns dict
    path->bool (True=faithful) and a compile error string or None."""
    Path(_os.path.join(TMPDIR, "_n.lua")).write_text(named_src)
    c = subprocess.run([luac, "-s", "-o", _os.path.join(TMPDIR, "_n.luac"), _os.path.join(TMPDIR, "_n.lua")],
                       capture_output=True, text=True)
    if c.returncode != 0:
        return None, c.stderr.strip().split("\n")[-1]
    A = bccmp.parse(orig_std); B = bccmp.parse(Path(_os.path.join(TMPDIR, "_n.luac")).read_bytes())
    diffs = bccmp.cmp_fn(A, B)
    bad = set()
    for d in diffs:
        # lines look like "  fn 0_3: ..."
        tok = d.split("fn ")[1].split(":")[0].strip()
        bad.add(tok)
    return bad, None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("luac")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--annotate-roots", nargs="*", default=[])
    ap.add_argument("--luadec", default=str(LUADEC))
    ap.add_argument("--no-widen", action="store_true",
                    help="feed the .luac to luadec untouched (use when your "
                         "luadec is size_t-matched to the .luac, e.g. a "
                         "size_t=4 native build)")
    ap.add_argument("--unluac", action="store_true",
                    help="Windows-friendly: decompile with unluac.jar instead "
                         "of luadec (no luadec/WSL build needed)")
    ap.add_argument("--jar", default=str(UNLUAC), help="path to unluac.jar")
    ap.add_argument("--luac", dest="luac_bin", default=str(LUAC),
                    help="path to a Lua 5.1 luac for the verify step "
                         "(e.g. luac51.exe)")
    a = ap.parse_args()

    if a.unluac:
        src, orig_std = decompile_unluac(a.luac, a.jar)
        backend = "unluac"
    else:
        src, orig_std = decompile(a.luac, a.luadec, no_widen=a.no_widen)
        backend = "luadec"
    if not src.strip() or len(src.splitlines()) < 4:
        sys.exit(f"{backend} produced no usable source (stub/abort); try the "
                 f"other backend, or disassemble.")
    named = src if a.unluac else rename_luadec.apply(src)
    if a.annotate_roots and HAVE_ANNOTATE:
        rev = {h: n for h, n in L.build_hash_dict(a.annotate_roots).items()}
        named = lua_annotate.annotate(named, rev)

    # completeness: does the decompile have as many functions as the original?
    def count(f): return 1 + sum(count(p) for p in f["protos"])
    n_orig = count(bccmp.parse(orig_std))

    bad, err = faithful_map(orig_std, named, a.luac_bin)

    # Tag each function in the source with its bytecode path + verdict, so the
    # editor view tells you what is safe. Works for ANY backend: compile the
    # source UNSTRIPPED so luac records each proto's linedefined, then map
    # path -> source line and stamp it.
    tagged = named
    try:
        subprocess.run([a.luac_bin, "-o", _os.path.join(TMPDIR, "_dbg.luac"), _os.path.join(TMPDIR, "_n.lua")],
                       capture_output=True, check=True)
        line_of = {}   # path str -> linedefined
        d = Path(_os.path.join(TMPDIR, "_dbg.luac")).read_bytes()
        import struct as _s
        little = d[6] == 1; isz, stsz = d[7], d[8]
        pos = [12]
        def ru(n):
            v = int.from_bytes(d[pos[0]:pos[0]+n], "little" if little else "big"); pos[0]+=n; return v
        def rint(): return ru(isz)
        def rsize(): return ru(stsz)
        def walk(path):
            sl = rsize(); pos[0]+=sl                      # source
            ld = rint(); rint()                           # linedefined, last
            line_of[path] = ld
            pos[0]+=4                                      # nups,nparams,vararg,maxstack
            nc = rint(); pos[0]+=4*nc
            nk = rint()
            for _ in range(nk):
                t = d[pos[0]]; pos[0]+=1
                if t == 0: pass
                elif t == 1: pos[0]+=1
                elif t == 3: pos[0]+=8
                elif t == 4: sl = rsize(); pos[0]+=sl
            npr = rint()
            for i in range(npr): walk(f"{path}_{i}" if path else f"0_{i}")
            nl = rint(); pos[0]+=4*nl
            nloc = rint()
            for _ in range(nloc): sl=rsize(); pos[0]+=sl; rint(); rint()
            nup = rint()
            for _ in range(nup): sl=rsize(); pos[0]+=sl
        walk("0")
        lines = named.split("\n")
        # group verdict by line; a function defined on line L gets stamped there
        by_line = {}
        for path, ld in line_of.items():
            if path == "0" or ld == 0: continue
            v = "DIVERGENT-do-not-edit" if (bad and path in bad) else \
                ("UNGRADED" if bad is None else "FAITHFUL-safe-to-edit")
            by_line.setdefault(ld, []).append(f"{path}:{v}")
        for ln in sorted(by_line):
            if 1 <= ln <= len(lines) and "<<<" not in lines[ln-1]:
                lines[ln-1] = lines[ln-1] + "  -- <<< " + "  ".join(by_line[ln])
        tagged = "\n".join(lines)
    except Exception:
        pass
    Path(a.out).write_text(tagged, encoding="utf-8")
    print(f"wrote {a.out}")
    try:
        subprocess.run([a.luac_bin, "-s", "-o", _os.path.join(TMPDIR, "_cnt.luac"), a.out],
                       capture_output=True, check=True)
        n_got = count(bccmp.parse(Path(_os.path.join(TMPDIR, "_cnt.luac")).read_bytes()))
        if n_got < n_orig:
            print(f"  INCOMPLETE: recovered {n_got} of {n_orig} functions "
                  f"(stub). Use unluac or `luadec -dis` for this chunk.")
    except Exception:
        pass
    if err:
        print(f"  NOTE: full-file recompile fails ({err}). Per-function splice "
              f"still works for any FAITHFUL function below.")
    if bad is None:
        print("  faithfulness: could not compile to grade; read disassembly to verify before editing.")
    elif not bad:
        print("  faithfulness: ALL functions faithful — safe to edit + splice.")
    else:
        print(f"  DIVERGENT functions (do NOT edit/splice these): {', '.join(sorted(bad))}")
        print("  all other functions are faithful and safe to edit + splice.")

if __name__ == "__main__":
    main()
