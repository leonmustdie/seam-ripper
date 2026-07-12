#!/usr/bin/env python3
r"""lua_readable.py - produce readable AND injectable Lua source from a unit.

Pipeline per script chunk:
  transcode (raw hashes) -> unluac -> lua_clean (inline/fold) -> annotate
  -> VERIFY: luac + lua_recompile must produce valid 360 bytecode.

Output is readable source where every hash is a "__hash_0x..." placeholder
with its resolved name in a trailing comment. Files that fail verification
are reported and written to a _FAILED subdir so you know not to inject them.

Usage:
  lua_readable.py <extract-dir> -o readable --luac luac51.exe
  # <extract-dir> is the naughty_lu.py extract output (has <unit>/animation/*.bin)
"""
import argparse, re, subprocess, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lua_decompile as L
import lua_recompile
import lua_clean
import lua_annotate

def find_luac(explicit):
    if explicit: return explicit
    for n in ("luac51","luac5.1","luac"):
        p = shutil.which(n)
        if p: return p
    sys.exit("luac not found; pass --luac")

def verify(src_text, luac, tmp):
    lua = tmp/"v.lua"; bc = tmp/"v.luac"
    lua.write_text(src_text, encoding="utf-8")
    r = subprocess.run([luac,"-s","-o",str(bc),str(lua)], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "luac: "+(r.stderr or r.stdout).strip().split("\n")[-1]
    try:
        lua_recompile.convert(bc.read_bytes(), want_hash=True)
    except Exception as e:
        return False, "recompile: "+str(e)
    return True, ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("extract")
    ap.add_argument("-o","--out",required=True)
    ap.add_argument("--luac")
    ap.add_argument("--jar", default=str(Path(__file__).parent/"unluac.jar"))
    a = ap.parse_args()
    luac = find_luac(a.luac)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp = out/"_tmp"; tmp.mkdir(exist_ok=True)

    hashes = L.build_hash_dict([a.extract])
    rev = {h:n for h,n in hashes.items()}
    jar = Path(a.jar)

    ok=fail=0; failed=[]
    for binf in sorted(Path(a.extract).glob("*/animation/*.bin")):
        raw = binf.read_bytes()
        sig = raw.find(b"\x1bLua")
        if sig < 0 or raw[sig+4] != 0x51: continue
        m = re.search(rb"z:\\[\x20-\x7e]+?\.lua", raw)
        name = m.group().decode().split("\\")[-1][:-4] if m else binf.stem.split("_",1)[-1]
        unit = binf.parent.parent.name
        try:
            std = L.transcode(raw, hashes, raw_hashes=True)
            (tmp/"c.luac").write_bytes(std)
            r = subprocess.run(["java","-jar",str(jar),str(tmp/"c.luac")],
                               capture_output=True, text=True)
            if r.returncode != 0 or not r.stdout.strip():
                fail+=1; failed.append((unit,name,"unluac failed")); continue
            cleaned = lua_clean.clean_text(r.stdout)
            annotated = lua_annotate.annotate(cleaned, rev)
            good, why = verify(annotated, luac, tmp)
            dest_dir = (out/unit) if good else (out/"_FAILED"/unit)
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir/f"{name}.lua").write_text(annotated, encoding="utf-8")
            if good: ok+=1
            else: fail+=1; failed.append((unit,name,why))
        except Exception as e:
            fail+=1; failed.append((unit,name,str(e)))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"readable+verified: {ok}   failed verification: {fail}")
    for u,n,w in failed[:20]:
        print(f"  FAIL {u}/{n}: {w}")

if __name__ == "__main__":
    main()
