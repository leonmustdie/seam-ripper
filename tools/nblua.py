#!/usr/bin/env python3
r"""nblua.py - one tool to edit Naughty Bear Lua: list, read, ship.

    python nblua.py list  game.lu
    python nblua.py read  game.lu <chunkname> -o chunk.lua
    # edit chunk.lua in any text editor (whole file is fine)
    python nblua.py ship  game.lu <chunkname> chunk.lua -o out.lu --stage <build>\assets\lu

read  -> pulls one script chunk out of the .lu and writes readable Lua, with
         each function tagged FAITHFUL / DIVERGENT (just hints).
ship  -> works out which functions you actually changed, injects ONLY those,
         keeps every other function's original game bytes, and refuses (naming
         the function) if you edited one the decompiler can't reproduce.

Backends: defaults to unluac.jar + luac51.exe sitting next to this script.
Add --luadec to use a luadec build instead (more functions decompile cleanly).

Depends on the existing pipeline files in the same folder: naughty_lu,
lua_decompile, lua_recompile, lua_chunk_swap, lu_chunk_replace, lua_clean,
and the helpers proto360, bccmp, rename_luadec, widen_sizet.
"""
import argparse, subprocess, sys, shutil, tempfile, struct, re
from pathlib import Path
import os as _os, tempfile as _tf
TMPDIR = _tf.gettempdir()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from naughty_lu import LuFile
import lua_decompile as L, lua_recompile, lua_chunk_swap, lua_clean
import proto360, bccmp, rename_luadec, widen_sizet

LUAC   = HERE / "luac51.exe"
UNLUAC = HERE / "unluac.jar"
LUADEC = HERE / ("luadec.exe" if _os.name == "nt" else "luadec")

NAME_RE = re.compile(rb"z:\\[\x20-\x7e]+?\.lua")

# ---------------------------------------------------------------- helpers

def find_luac(explicit):
    if explicit:
        return explicit
    for n in ("luac51", "luac5.1", "luac"):
        p = shutil.which(n)
        if p:
            return p
    if LUAC.exists():
        return str(LUAC)
    sys.exit("luac not found; pass --luac (e.g. --luac luac51.exe)")

def script_records(lu):
    """yield (record, name) for every script chunk in a loaded LuFile."""
    img = lu.image
    for r in lu.records:
        chunk = img[r.offset:r.offset + r.size]
        if b"\x1bLua" not in chunk:
            continue
        m = NAME_RE.search(chunk)
        name = m.group().decode().split("\\")[-1][:-4] if m else ""
        yield r, name, chunk

def locate(lu, name, hsh):
    img = lu.image
    for r in lu.records:
        chunk = img[r.offset:r.offset + r.size]
        if hsh and r.hash == int(hsh, 16):
            return r, chunk
        if name and b"\x1bLua" in chunk:
            m = NAME_RE.search(chunk)
            cn = m.group().decode().split("\\")[-1][:-4] if m else ""
            if cn == name or name.encode() in chunk:
                return r, chunk
    return None, None

def decompile(std_luac_path, luadec, jar, luac):
    """std .luac -> (source, ok). unluac by default, luadec if requested."""
    if luadec:
        if not Path(LUADEC).exists():
            sys.exit(f"--luadec requested but no luadec binary at {LUADEC}. "
                     f"Untick 'use luadec' to use unluac, or build luadec first.")
        raw = Path(std_luac_path).read_bytes()
        feed = widen_sizet.widen(raw) if raw[8] == 4 else raw
        Path(_os.path.join(TMPDIR, "_w.luac")).write_bytes(feed)
        r = subprocess.run([str(LUADEC), _os.path.join(TMPDIR, "_w.luac")],
                           capture_output=True, text=True)
        src = rename_luadec.apply(r.stdout) if r.stdout.strip() else ""
    else:
        r = subprocess.run(["java", "-jar", jar, str(std_luac_path)],
                           capture_output=True, text=True)
        src = lua_clean.clean_text(r.stdout) if r.stdout.strip() else ""
    return src

def compile_360(src_path, luac):
    r = subprocess.run([luac, "-s", "-o", _os.path.join(TMPDIR, "_n.luac"), str(src_path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return lua_recompile.convert(Path(_os.path.join(TMPDIR, "_n.luac")).read_bytes(), want_hash=True)

def line_of_each_function(src, luac):
    """compile UNSTRIPPED -> path -> source line where each function is defined."""
    Path(_os.path.join(TMPDIR, "_dbg.lua")).write_text(src, encoding="utf-8")
    subprocess.run([luac, "-o", _os.path.join(TMPDIR, "_dbg.luac"), _os.path.join(TMPDIR, "_dbg.lua")],
                   capture_output=True, check=True)
    d = Path(_os.path.join(TMPDIR, "_dbg.luac")).read_bytes()
    little = d[6] == 1; isz, stsz = d[7], d[8]; pos = [12]; out = {}
    def ru(n):
        v = int.from_bytes(d[pos[0]:pos[0]+n], "little" if little else "big"); pos[0]+=n; return v
    def walk(path):
        sl = ru(stsz); pos[0]+=sl
        ld = ru(isz); ru(isz); out[path] = ld
        pos[0]+=4
        nc = ru(isz); pos[0]+=4*nc
        nk = ru(isz)
        for _ in range(nk):
            t = d[pos[0]]; pos[0]+=1
            if t == 1: pos[0]+=1
            elif t == 3: pos[0]+=8
            elif t == 4: sl = ru(stsz); pos[0]+=sl
        npr = ru(isz)
        for i in range(npr): walk(f"{path}_{i}" if path else f"0_{i}")
        nl = ru(isz); pos[0]+=4*nl
        nloc = ru(isz)
        for _ in range(nloc): sl=ru(stsz); pos[0]+=sl; ru(isz); ru(isz)
        nup = ru(isz)
        for _ in range(nup): sl=ru(stsz); pos[0]+=sl
    walk("0")
    return out

# ---------------------------------------------------------------- commands

def cmd_list(a):
    lu = LuFile(a.lu)
    rows = [(r.hash, r.size, name) for r, name, _ in script_records(lu)]
    if not rows:
        print("no script chunks in this .lu"); return
    print(f"{len(rows)} script chunk(s) in {Path(a.lu).name}:\n")
    print(f"  {'name':<40} {'size':>7}  hash")
    for h, sz, name in sorted(rows, key=lambda x: x[2] or "zzz"):
        print(f"  {name or '(unnamed)':<40} {sz:>7}  {h:#010x}")

def _read_to_source(a, luac):
    lu = LuFile(a.lu)
    r, chunk = locate(lu, a.name, a.hash)
    if r is None:
        sys.exit("chunk not found; run `nblua.py list` to see available chunks")
    if b"\x1bLua" not in chunk:
        sys.exit("that record is not a Lua script chunk")
    std = L.transcode(chunk, {}, raw_hashes=True)
    tmp = Path(tempfile.mkdtemp(prefix="nblua_")) / "c.luac"
    tmp.write_bytes(std)
    src = decompile(tmp, a.luadec, a.jar, luac)
    if not src.strip() or len(src.splitlines()) < 3:
        sys.exit("decompiler produced no usable source for this chunk; try "
                 "--luadec (or the other backend).")
    return lu, r, chunk, std, src

def cmd_read(a):
    luac = find_luac(a.luac)
    lu, r, chunk, std, src = _read_to_source(a, luac)
    # faithfulness per function (best-effort: if luac is missing/misconfigured
    # we still write the source, just without FAITHFUL/DIVERGENT tags)
    grade_err = None
    try:
        emitted = compile_360(_write_tmp(src), luac)  # ensures it compiles
        bad = _divergent_set(std, src, luac)
    except FileNotFoundError:
        bad = None
        grade_err = (f"could not run luac at '{luac}'. The source is written, "
                     f"but functions are UNGRADED. Put luac51.exe next to "
                     f"nblua.py (or set its path in Settings) to enable grading "
                     f"and shipping.")
    except Exception as e:
        bad = None
        grade_err = f"could not grade functions ({e}); source written untagged."
    # tag each function on its def line
    tagged = src
    try:
        lines = src.split("\n")
        line_of = line_of_each_function(src, luac)
        by_line = {}
        for path, ld in line_of.items():
            if path == "0" or ld == 0:
                continue
            v = ("UNGRADED" if bad is None else
                 "DIVERGENT-do-not-edit" if path in bad else "FAITHFUL-safe-to-edit")
            by_line.setdefault(ld, []).append(f"{path}:{v}")
        for ln in sorted(by_line):
            if 1 <= ln <= len(lines) and "<<<" not in lines[ln-1]:
                lines[ln-1] += "  -- <<< " + "  ".join(by_line[ln])
        tagged = "\n".join(lines)
    except Exception:
        pass
    Path(a.out).write_text(tagged, encoding="utf-8")
    print(f"wrote {a.out}")
    if grade_err:
        print("  " + grade_err)
    elif bad:
        print(f"  heads-up: {', '.join(sorted(bad))} are DIVERGENT (ship will "
              f"refuse edits to them). Everything else is safe.")
    else:
        print("  all functions faithful — edit freely.")
    print("  edit chunk bodies, not signatures; then run `nblua.py ship`.")

def _write_tmp(src):
    p = Path(_os.path.join(TMPDIR, "_src.lua")); p.write_text(src, encoding="utf-8"); return p

def _divergent_set(std, src, luac):
    """functions the decompiler reconstructed wrong (recompile != original)."""
    img = compile_360(_write_tmp(src), luac)
    A = bccmp.parse(std); B = bccmp.parse(Path(_os.path.join(TMPDIR, "_n.luac")).read_bytes())
    bad = set()
    for d in bccmp.cmp_fn(A, B):
        bad.add(d.split("fn ")[1].split(":")[0].strip())
    return bad

def cmd_ship(a):
    luac = find_luac(a.luac)
    lu = LuFile(a.lu)
    r, chunk = locate(lu, a.name, a.hash)
    if r is None:
        sys.exit("chunk not found; run `nblua.py list`")
    i = chunk.find(b"\x1bLua")
    if i < 0:
        sys.exit("that record is not a Lua script chunk")
    bc = struct.unpack_from(">I", chunk, 0x1c)[0]
    orig_img = chunk[i:i+bc]

    # baseline: decompile the ORIGINAL chunk the same way read did
    std = L.transcode(chunk, {}, raw_hashes=True)
    tmp = Path(tempfile.mkdtemp(prefix="ship_")); tlc = tmp/"c.luac"; tlc.write_bytes(std)
    base_src = decompile(tlc, a.luadec, a.jar, luac)
    (tmp/"base.lua").write_text(base_src, encoding="utf-8")

    try:
        base_img = compile_360(tmp/"base.lua", luac)
        edit_img = compile_360(a.source, luac)
    except RuntimeError as e:
        sys.exit(f"source failed to compile:\n{e}")

    Lorig = proto360.decode_logic(orig_img)
    Lbase = proto360.decode_logic(base_img)
    Ledit = proto360.decode_logic(edit_img)
    if not (set(Lorig) == set(Lbase) == set(Ledit)):
        sys.exit("function structure changed (a function was added/removed, or "
                 "the decompile shape differs). Edit bodies only.")

    divergent = {p for p in Lorig if Lbase[p] != Lorig[p]}
    edited    = {p for p in Lorig if Ledit[p] != Lbase[p]}
    leaf = {p for p in edited if not any(q != p and q.startswith(p+"_") for q in edited)}

    unsafe = leaf & divergent
    if unsafe:
        sys.exit(f"REFUSED: you edited {', '.join(sorted(unsafe))}, which the "
                 f"decompiler could not reproduce faithfully — shipping it would "
                 f"inject wrong code. Leave those functions unchanged, or re-read "
                 f"this chunk with --luadec and retry.")
    if not leaf:
        print("no function-level changes detected; nothing to inject.")
        shutil.copy2(a.lu, a.out)
        return

    cur = orig_img
    for p in sorted(leaf):
        cur = proto360.splice(cur, edit_img, [int(x) for x in p.split("_")[1:]])
    new_chunk = lua_chunk_swap.swap(chunk, cur)

    # --- container-safety guard -------------------------------------------
    # Compressed (codec 2) containers now re-compress correctly via
    # lzx_encode.xmem_lzx_compress (lu_chunk_replace.py handles this,
    # verified round-trip against real retail NB1 pools). The remaining
    # known gap: some chunks are stored as paired (descriptor + body)
    # records sharing one hash; if the body's size changes, the descriptor
    # and every following record offset must be rebuilt, which isn't
    # handled yet. Refuse that specific case rather than emit a bad file.
    same_hash = [rr for rr in lu.records if rr.hash == r.hash and not rr.external]
    if len(same_hash) > 1 and len(new_chunk) != len(chunk):
        sys.exit(f"REFUSED: '{a.name or hex(r.hash)}' is stored as paired records "
                 f"sharing one hash, and your edit changed the chunk size "
                 f"({len(chunk)} -> {len(new_chunk)} bytes). Resizing these isn't "
                 f"handled yet and would corrupt the container. A same-size edit "
                 f"(e.g. changing a value, not adding code) would be accepted.")
    # ----------------------------------------------------------------------

    Path(_os.path.join(TMPDIR, "_ship_chunk.bin")).write_bytes(new_chunk)
    # Forward the ALREADY-RESOLVED record's hash, not the raw name string.
    # locate() above used precise embedded-path matching to find `r`; if we
    # instead pass a.name through, lu_chunk_replace.py has to re-resolve it
    # itself with a much cruder check (`name.encode() in chunk`, a bare
    # substring search over raw bytes) — which can and did match the WRONG
    # record (a short common name like "npc" coincidentally appearing
    # inside unrelated binary data), splicing the edit into the wrong
    # chunk entirely. Using r.hash makes this ambiguity impossible.
    sys.argv = ["lu_chunk_replace.py", a.lu,
                "--hash", f"{r.hash:#010x}",
                _os.path.join(TMPDIR, "_ship_chunk.bin"), "-o", a.out]
    import lu_chunk_replace
    lu_chunk_replace.main()
    print(f"shipped {len(leaf)} function(s): {', '.join(sorted(leaf))}")
    print("all other functions kept original game bytes.")

    # Mandatory container-integrity gate. The FAITHFUL/DIVERGENT check above
    # guards the bytecode; this guards the container layout the bytecode was
    # spliced into. Both legs (structural + independent decode) must pass, or
    # the just-written file is deleted and ship fails. Self-consistency is
    # not an accepted fallback: see verify_lzx.py's module docstring.
    import verify_lzx
    try:
        for msg in verify_lzx.verify_file(a.out):
            print(f"  verify: {msg}")
    except verify_lzx.VerifyError as e:
        try:
            _os.unlink(a.out)
        except OSError:
            pass
        sys.exit(f"REFUSED: container verification failed, output deleted.\n"
                 f"  {e}")

    if a.stage:
        stage = Path(a.stage)
        if not stage.is_dir():
            sys.exit(f"--stage dir missing: {stage}")
        dest = stage / Path(a.lu).name
        if dest.exists():
            shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
        shutil.copy2(a.out, dest)
        print(f"staged -> {dest}; run the game to test.")

def cmd_verify(a):
    import verify_lzx
    try:
        for msg in verify_lzx.verify_file(a.lu, verifier=a.verifier):
            print(msg)
    except verify_lzx.VerifyError as e:
        sys.exit(f"FAIL: {e}")
    print("PASS")

# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="Edit Naughty Bear Lua: list / read / ship.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list script chunks in a .lu")
    pl.add_argument("lu")
    pl.set_defaults(func=cmd_list)

    common = dict()
    pr = sub.add_parser("read", help="decompile one chunk to editable Lua")
    pr.add_argument("lu"); pr.add_argument("name", nargs="?")
    pr.add_argument("--hash"); pr.add_argument("-o", "--out", required=True)
    pr.add_argument("--luadec", action="store_true")
    pr.add_argument("--jar", default=str(UNLUAC))
    pr.add_argument("--luac", default=None)
    pr.set_defaults(func=cmd_read)

    ps = sub.add_parser("ship", help="inject your edits back into the .lu")
    ps.add_argument("lu"); ps.add_argument("name", nargs="?")
    ps.add_argument("source", help="your edited .lua")
    ps.add_argument("--hash"); ps.add_argument("-o", "--out", required=True)
    ps.add_argument("--luadec", action="store_true")
    ps.add_argument("--jar", default=str(UNLUAC))
    ps.add_argument("--luac", default=None)
    ps.add_argument("--stage", help="build assets\\lu folder to copy result into")
    ps.set_defaults(func=cmd_ship)

    pv = sub.add_parser("verify", help="check any .lu's container integrity")
    pv.add_argument("lu")
    pv.add_argument("--verifier", help="path to the independent decoder binary")
    pv.set_defaults(func=cmd_verify)

    a = ap.parse_args()
    if a.cmd in ("read", "ship") and not (a.name or a.hash):
        sys.exit("give a chunk name (or --hash). Run `nblua.py list` to see them.")
    a.func(a)

if __name__ == "__main__":
    main()
