#!/usr/bin/env python3
r"""Edit Naughty Bear Lua: list, read, ship."""
import argparse, subprocess, sys, shutil, tempfile, struct, re
from pathlib import Path
import atexit as _atexit, os as _os, shutil as _shutil, tempfile as _tf
# private per process, so two runs at once never share these files
TMPDIR = _tf.mkdtemp(prefix="seamripper_")
_atexit.register(_shutil.rmtree, TMPDIR, True)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from naughty_lu import LuFile
import lua_decompile as L, lua_recompile, lua_chunk_swap, lua_clean
import proto360, bccmp, rename_luadec, widen_sizet, lua_repair

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
    """Find the record holding a script chunk, by embedded name or by hash.

    Several scripts are stored as a PAIR of records sharing one hash: a small
    descriptor followed by the body that actually carries the `\x1bLua` image
    (camera, componentsaccessors, gamespecificcomponentsaccessors and
    manualdetails in global.lu are all like this). Returning the first record
    whose hash matches therefore handed back the descriptor, and `read`/`ship`
    rejected it with "that record is not a Lua script chunk" - the chunk was
    there all along, just one record further on. Collect every candidate and
    prefer one that actually contains a Lua image.
    """
    img = lu.image
    want = int(hsh, 16) if hsh else None
    cands = []
    for r in lu.records:
        chunk = img[r.offset:r.offset + r.size]
        if want is not None and r.hash == want:
            cands.append((r, chunk))
            continue
        if name and b"\x1bLua" in chunk:
            m = NAME_RE.search(chunk)
            cn = m.group().decode().split("\\")[-1][:-4] if m else ""
            if cn == name or name.encode() in chunk:
                cands.append((r, chunk))
    if not cands:
        return None, None
    for r, chunk in cands:
        if b"\x1bLua" in chunk:
            return r, chunk
    return cands[0]

# Which decompiler produced a given .lua, recorded in the file itself. `read`
# writes it; `ship` reads it back so that the baseline it decompiles to diff
# against your edit is produced by the SAME backend. Comparing an edit made
# from luadec output against an unluac baseline would mark every function as
# changed and inject the whole chunk.
BACKEND_MARK = "-- seam ripper: decompiled by {} (keep this line)"
BACKEND_RE = re.compile(r"^--\s*seam ripper: decompiled by ([\w+]+)", re.M)


def _run_unluac(std_luac_path, jar):
    r = subprocess.run(["java", "-jar", jar, str(std_luac_path)],
                       capture_output=True, text=True, errors="replace")
    return lua_clean.clean_text(r.stdout) if r.stdout.strip() else ""


def _run_luadec(std_luac_path):
    if not Path(LUADEC).exists():
        return ""
    raw = Path(std_luac_path).read_bytes()
    feed = widen_sizet.widen(raw) if raw[8] == 4 else raw
    Path(_os.path.join(TMPDIR, "_w.luac")).write_bytes(feed)
    r = subprocess.run([str(LUADEC), _os.path.join(TMPDIR, "_w.luac")],
                       capture_output=True, text=True, errors="replace")
    if not r.stdout.strip():
        return ""
    src, rep = lua_repair.repair(rename_luadec.apply(r.stdout))
    # A hole is luadec printing a value it never reconstructed. Across 113
    # real retail chunks this predicted unparseable output exactly, with no
    # false positives, so refuse the source outright rather than hand back
    # something incomplete that happens to look editable.
    if rep.unrecoverable:
        return ""
    return src


def _normalise(luac_out, orig_hashes):
    """Put a recompiled candidate back into the same shape as the baseline.

    A candidate decompiled with hashed names RESOLVED (see nb_names.py) holds
    real string constants where the baseline holds __hash_0x placeholders, so
    the two cannot be compared directly. Running the candidate back through
    the game's own encoding - which re-hashes those strings to 0xFE - and then
    out again with placeholders puts both on identical terms.
    """
    nb1 = lua_recompile.convert(luac_out, want_hash=True,
                                orig_hashes=orig_hashes)
    return L.transcode(nb1, {}, raw_hashes=True)


def _score(src, base_std, luac, orig_hashes=None, named=False, chunk=None):
    """Rank a candidate source. Higher is better.

    (2, -divergent, named)  compiles; this many functions differ from retail
    (1, 0, named)           compiles but could not be compared
    (0, 0, 0)               does not compile / nothing produced

    `named` only breaks ties: readable names are worth having, but never at
    the cost of a single extra divergent proto, because a divergent proto is
    one `ship` will refuse to let you edit.

    Divergence is counted the same way `ship` counts it (proto360, top-level
    body included). Scoring candidates by a different measure than the one
    that gates shipping would optimise for the wrong thing.
    """
    if not src.strip() or len(src.splitlines()) < 3:
        return (0, 0, 0)
    p = Path(_os.path.join(TMPDIR, "_score.lua"))
    p.write_text(src, encoding="utf-8")
    out = _os.path.join(TMPDIR, "_score.luac")
    r = subprocess.run([luac, "-s", "-o", out, str(p)],
                       capture_output=True, text=True, errors="replace")
    if r.returncode:
        return (0, 0, 0)
    if chunk is None:
        return (1, 0, int(named))
    try:
        img = lua_recompile.convert(Path(out).read_bytes(), want_hash=True,
                                    orig_hashes=orig_hashes)
        Lo = proto360.decode_logic(chunk_image(chunk))
        Lb = proto360.decode_logic(img)
        if set(Lo) != set(Lb):
            return (1, -len(Lo), int(named))
        nd = sum(1 for k in Lo if Lo[k] != Lb[k])
    except Exception:
        return (1, 0, int(named))
    return (2, -nd, int(named))


def _variant_std(chunk, names):
    """The chunk transcoded with hashed constants resolved to real names,
    or None when no dictionary is available / nothing resolves."""
    if not names or chunk is None:
        return None
    try:
        named = L.transcode(chunk, names, raw_hashes=False)
    except Exception:
        return None
    return named


def decompile(std_luac_path, luadec, jar, luac, std=None, prefer=None,
              chunk=None, names=None):
    """std .luac -> readable Lua source. Returns (source, label).

    prefer: "unluac" / "luadec" pins a backend. "auto" (the default, and what
    `luadec=None` means) tries every combination and keeps whichever
    recompiles closest to the original bytecode:

      * both decompilers, because they fail on different chunks - across
        global.lu's 58 scripts they disagreed on 31, so choosing per chunk is
        worth far more than choosing one globally; and
      * with and without hashed-constant names resolved (nb_names.py), because
        resolving them is usually free and sometimes a large win - gamemodes
        goes from 35 divergent functions to 2 - but not universally, so it is
        scored rather than assumed.

    The label records both choices ("luadec+names"), and `read` stamps it into
    the file so `ship` rebuilds an identical baseline.
    """
    if prefer is None:
        prefer = "auto" if luadec is None else ("luadec" if luadec else "unluac")
    want_names = prefer.endswith("+names")
    base_prefer = prefer.replace("+names", "")

    if std is None:
        std = Path(std_luac_path).read_bytes()
    orig_hashes = lua_recompile.ref_hash_set(chunk) if chunk is not None else set()

    if base_prefer in ("auto", "nbdec") and chunk is not None:
        src = nbdec_source(chunk, names)
        if src is not None:
            return src, "nbdec"
        if base_prefer == "nbdec":
            return "", "nbdec"

    def run(backend, use_names):
        src_std = _variant_std(chunk, names) if use_names else std
        if src_std is None:
            return None
        p = Path(_os.path.join(TMPDIR, "_cand.luac"))
        p.write_bytes(src_std)
        return _run_luadec(p) if backend == "luadec" else _run_unluac(p, jar)

    if base_prefer in ("unluac", "luadec"):
        if base_prefer == "luadec" and not Path(LUADEC).exists():
            sys.exit(f"--backend luadec requested but no luadec binary at "
                     f"{LUADEC}. Use --backend unluac or auto, or build "
                     f"luadec first.")
        src = run(base_prefer, want_names) or ""
        return src, base_prefer + ("+names" if want_names else "")

    best_label, best_src, best_score = None, "", (-1, 0, 0)
    for backend in ("luadec", "unluac"):
        for use_names in (True, False):
            src = run(backend, use_names)
            if src is None:
                continue
            s = _score(src, std, luac, orig_hashes, named=use_names,
                       chunk=chunk)
            if s > best_score:
                best_label = backend + ("+names" if use_names else "")
                best_src, best_score = src, s
    # ties go to luadec: it reproduced retail bytecode exactly on 20 of
    # global.lu's 58 chunks against unluac's 6.
    return best_src, (best_label or "unluac")

def nbdec_source(chunk, names=None, texts=None):
    """nbdec's reconstruction of a chunk, or None if it declines.

    nbdec is purpose-built for this game's scripts and reproduces all of the
    shipped NB1 functions byte-for-byte (nbdec_bench.py measures it), so it
    is tried before the general decompilers. The 0xFE constants go in as
    numbers - how the game's compiler treated them - with hashed ones named
    from the dictionary."""
    import nbdec
    try:
        std = L.transcode(chunk, {}, as_numbers=True)
        fe, _ = nbdec.original_number_types(
            L.transcode(chunk, {}, raw_hashes=True))
        if texts is None:
            import nb_names
            texts = nb_names.load_text()
        return nbdec.decompile_proto(
            nbdec.parse(std), hash_names=names or {},
            hash_values=lua_recompile.ref_hash_set(chunk), fe_values=fe,
            hash_text=texts)
    except nbdec.Unsupported:
        return None


def compile_nbdec(src_path, luac, chunk):
    """Compile nbdec-style source back to the game's chunk bytecode.

    Numbers get their NB1 type back: every constant a function already had
    keeps the original's type, and a new one follows the game compiler's
    own rule - spelled as an integer (`20`, `0x2e1e60d6`) it is the 64-bit
    0xFE type, spelled with a point (`20.0`) a double. Strings are never
    reinterpreted as hashes: nbdec writes hashes as numbers, so a string in
    its output is really a string."""
    import nbdec
    out = Path(_os.path.join(TMPDIR, "_n.luac"))
    lined = Path(_os.path.join(TMPDIR, "_nl.luac"))
    for args, dest in ((["-s"], out), ([], lined)):
        r = subprocess.run([luac] + args + ["-o", str(dest), str(src_path)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr or r.stdout)
    src = Path(src_path).read_text(encoding="utf-8", errors="replace")
    original = nbdec.original_number_types(
        L.transcode(chunk, {}, raw_hashes=True))
    root = nbdec.parse(lined.read_bytes())
    fe = nbdec.fe_numbers(src, root, original)
    for line, text, value, path in nbdec.spelling_conflicts(src, root):
        kind = "an integer" if value in fe.get(path, ()) else "a decimal"
        clash = "decimal" if nbdec.is_float_spelling(text) else "whole number"
        if kind == ("a decimal" if clash == "decimal" else "an integer"):
            continue
        print(f"  note: line {line}: {text} is stored as {kind}, not a {clash}: "
              f"this function also uses {value} the other way, and a function "
              f"can hold each number only once")
    return lua_recompile.convert(out.read_bytes(), fe_numbers=fe)


def compile_for(backend, src_path, luac, orig_hashes, chunk):
    """The compile that matches how the source was decompiled."""
    if backend == "nbdec":
        return compile_nbdec(src_path, luac, chunk)
    return compile_360(src_path, luac, orig_hashes)


def compile_360(src_path, luac, orig_hashes=None):
    """Compile edited source back to the game's chunk bytecode.

    orig_hashes is the set of 0xFE values the ORIGINAL chunk held. It lets a
    string constant that was a hashed name be re-encoded as 0xFE instead of
    shipping as a literal string, which is what makes resolved names (see
    nb_names.py) round-trip instead of changing the bytecode.
    """
    r = subprocess.run([luac, "-s", "-o", _os.path.join(TMPDIR, "_n.luac"), str(src_path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return lua_recompile.convert(Path(_os.path.join(TMPDIR, "_n.luac")).read_bytes(),
                                 want_hash=True, orig_hashes=orig_hashes)

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

def load_names(a):
    """The CRC32 -> name dictionary, unless --no-names was given.

    Absent dictionary is not an error: everything still works, hashed
    constants just stay as __hash_0x placeholders. Build one with
    `nb_names.py build --pip <PiP .lu files> --nb1 <NB1 .lu files>`.
    """
    if getattr(a, "no_names", False):
        return {}
    try:
        import nb_names
        return nb_names.load(getattr(a, "names", None))
    except Exception:
        return {}


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
    src, backend = decompile(tmp, a.luadec, a.jar, luac, std=std,
                             prefer=getattr(a, "backend", None),
                             chunk=chunk, names=load_names(a))
    if not src.strip() or len(src.splitlines()) < 3:
        sys.exit("neither decompiler produced usable source for this chunk. "
                 "Pin one explicitly with --backend unluac / --backend luadec "
                 "to see its raw output and error.")
    return lu, r, chunk, std, src, backend

def cmd_read(a):
    luac = find_luac(a.luac)
    lu, r, chunk, std, src, backend = _read_to_source(a, luac)
    # faithfulness per function (best-effort: if luac is missing/misconfigured
    # we still write the source, just without FAITHFUL/DIVERGENT tags)
    grade_err = None
    orig_hashes = lua_recompile.ref_hash_set(chunk)
    try:
        compile_for(backend, _write_tmp(src), luac, orig_hashes, chunk)
        bad = _divergent_set(chunk, src, luac, orig_hashes, backend)
    except FileNotFoundError:
        bad = None
        grade_err = (f"could not run luac at '{luac}'. The source is written, "
                     f"but functions are UNGRADED. Put luac51.exe next to "
                     f"nblua.py (or set its path in Settings) to enable grading "
                     f"and shipping.")
    except Exception as e:
        bad = None
        grade_err = f"could not grade functions ({e}); source written untagged."
    tagged = tag_source(src, backend, bad, luac)
    Path(a.out).write_text(tagged, encoding="utf-8")
    print(f"wrote {a.out}  (backend: {backend})")
    if grade_err:
        print("  " + grade_err)
    elif bad:
        n = len(bad)
        print(f"  heads-up: {n} proto(s) DIVERGENT, ship will refuse edits to "
              f"them: {', '.join(sorted(bad))}")
        print(f"  everything else is safe to edit.")
    print("  edit function bodies (not signatures), then Ship.")

def tag_source(src, backend, bad, luac):
    """The text `read` writes: backend stamp, then the source with each
    function tagged FAITHFUL/DIVERGENT (bad=None means ungraded)."""
    # tag each function on its def line - unless every one is faithful, when
    # a tag on every line says nothing the header does not
    tagged = src
    if bad is None or bad:
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
    # "0" is the chunk's top-level body - everything outside any function.
    # It is editable like any other proto and `ship` gates it like any other
    # proto, so say so instead of silently leaving it ungraded.
    head = [BACKEND_MARK.format(backend)]
    if bad is not None and "0" in bad:
        head.append("-- <<< 0:DIVERGENT-do-not-edit  (the top-level chunk "
                    "body, i.e. every statement outside a function)")
    return "\n".join(head) + "\n" + tagged


def _write_tmp(src):
    p = Path(_os.path.join(TMPDIR, "_src.lua")); p.write_text(src, encoding="utf-8"); return p

def chunk_image(chunk):
    """The bare Lua image inside a chunk, as `ship` slices it."""
    i = chunk.find(b"\x1bLua")
    bc = struct.unpack_from(">I", chunk, 0x1c)[0]
    return chunk[i:i + bc]


def _divergent_set(chunk, src, luac, orig_hashes=None, backend=None):
    """Protos the decompiler reconstructed wrong (recompile != original).

    Measured exactly the way `ship` measures it: proto360.decode_logic on the
    original image against the recompiled one, comparing instructions and
    constants per proto. It used to use bccmp instead, which reports only
    nested functions, so the top-level chunk body ("0") was never graded -
    `read` would print "all functions faithful" and then `ship` would refuse
    the edit, because ship DOES compare "0". pictureinpicture behaved exactly
    like that. Same measure on both sides now.
    """
    img = compile_for(backend, _write_tmp(src), luac, orig_hashes, chunk)
    try:
        Lo = proto360.decode_logic(chunk_image(chunk))
        Lb = proto360.decode_logic(img)
    except Exception:
        return set()
    if set(Lo) != set(Lb):
        # structure differs: every proto is suspect
        return set(Lo)
    return {p for p in Lo if Lo[p] != Lb[p]}

# luadec emits a global it cannot name as a bare l_<a>_<b> token - visually
# identical to the locals it invents. Renaming a local is free, because
# `luac -s` strips local names and the bytecode is unchanged; renaming a
# global is not, because a global is resolved BY NAME at runtime and its name
# is a string constant in the chunk. Measured over global.lu: renaming every
# l_<a>_<b> token left 31 of 34 scripts byte-identical, and in all 3 that
# changed, the code bytes were identical and only a string constant moved.
# That is the exact signature this looks for.
LUADEC_TOKEN = re.compile(r"^l_\d+_\d+$")


def _renamed_globals(Lbase, Ledit, edited):
    """[(proto, old_name, new_name)] for globals the edit renamed by accident.

    Only fires when a proto's instructions are byte-identical and the only
    change is a string constant whose old value looks like a luadec-generated
    token. A real logic edit changes the code bytes, and an intentional string
    change does not swap out an l_<a>_<b> identifier.
    """
    out = []
    for p in sorted(edited):
        if p not in Lbase or p not in Ledit:
            continue
        code_a, consts_a = Lbase[p]
        code_b, consts_b = Ledit[p]
        if code_a != code_b:
            continue                      # genuine code change, not a rename
        sa = [c[1] for c in consts_a if c[0] == "s"]
        sb = [c[1] for c in consts_b if c[0] == "s"]
        if len(sa) != len(sb):
            continue
        for x, y in zip(sa, sb):
            if x == y:
                continue
            old = x.decode("latin-1", "replace").rstrip("\x00")
            new = y.decode("latin-1", "replace").rstrip("\x00")
            if LUADEC_TOKEN.match(old):
                out.append((p, old, new))
    return out


class ShipError(Exception):
    """A ship that cannot go ahead, and where in the modder's own file it
    points: `line` is a line of `file` (0 when no single line is to blame).
    kind: syntax / structure / refused / baseline / slot / verify / usage."""

    def __init__(self, message, file=None, line=0, kind="error"):
        super().__init__(message)
        self.file, self.line, self.kind = file, line, kind

    def as_dict(self):
        return {"file": str(self.file) if self.file else "", "line": self.line,
                "kind": self.kind, "message": str(self)}

    def sr_line(self):
        """One line the GUI can parse:
        SR-ERROR file="<path>" line=<n> kind=<kind>: <message>"""
        first = " ".join(str(self).split())
        return (f'SR-ERROR file="{self.file or ""}" line={self.line} '
                f'kind={self.kind}: {first}')


def read_edit_text(path):
    """The modder's .lua as text. A BOM some editors add is dropped (it is not
    Lua and would fail on line 1); nothing else changes, so line N here is
    line N in their editor."""
    text = Path(path).read_bytes().decode("utf-8", errors="replace")
    return text[1:] if text.startswith("﻿") else text


def expand_hash_keep_lines(src, fmt="0x{:08x}"):
    """nb_names.expand_hash_calls, but a HASH( ... ) call written across
    several lines keeps its line breaks, so every later line keeps its number
    and compiler errors still point at the right line of the modder's file."""
    import nb_names
    found = []

    def sub(m):
        v = nb_names.crc(m.group(2))
        found.append((m.group(2), v))
        return fmt.format(v) + "\n" * m.group(0).count("\n")
    return nb_names.HASH_CALL.sub(sub, src), found


LUAC_ERR = re.compile(r"\.lua:(\d+):\s*(.*)")


def luac_error_line(msg):
    """(line, message) from luac's `luac: path/x.lua:12: message` output."""
    for ln in str(msg).splitlines():
        m = LUAC_ERR.search(ln)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return 0, " ".join(str(msg).split())


def _line_map(matcher):
    """old line (1-based) -> new line, from a SequenceMatcher over lines."""
    out = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for k in range(i2 - i1):
            out[i1 + k + 1] = (j1 + k + 1) if tag == "equal" else (j1 + 1)
    return out


def _first_changed_line(matcher):
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            return j1 + 1
    return 0


STALE_RATIO = 0.5


def _stale_hint(stamp, matcher):
    """Why the modder's file may not match this script, or ""."""
    if not stamp:
        return ("Your file does not start with the '-- seam ripper: decompiled "
                "by ...' line that `read` writes, so it was not made by this "
                "version's read (or that line was removed). Re-read the script "
                "and redo your edit on the new file.")
    if matcher.ratio() < STALE_RATIO:
        return ("Most of your file differs from a fresh read of this script: "
                "it was probably read from a different script or container, or "
                "by an older Seam Ripper. Re-read the script and redo your edit "
                "on the new file.")
    return ""


def prepare_edit(chunk, source, luac, prefer="auto", luadec=False, jar=UNLUAC,
                 names=None, force=False, name="", log=print):
    """Check one edited script against its original chunk and build the new
    Lua image. Nothing is written. Raises ShipError naming the modder's file.

    Returns {"name", "source", "backend", "functions": [{"path", "line"}],
    "hash_calls": [{"name", "value"}], "diff", "warnings", "orig_image",
    "new_image"}; new_image is None when no function changed.
    """
    import difflib
    source = Path(source)
    if b"\x1bLua" not in chunk:
        raise ShipError("that record is not a Lua script chunk", kind="usage")
    orig_img = chunk_image(chunk)
    text = read_edit_text(source)
    user_lines = text.splitlines()

    # baseline: decompile the ORIGINAL chunk the same way read did. Which
    # backend that was matters: the diff below is "your source vs the
    # baseline", so a baseline from the other decompiler would differ almost
    # everywhere and ship would inject functions you never touched. `read`
    # stamps its choice into the file; honour it unless the user overrode it.
    stamp = BACKEND_RE.search(text)
    stamp_line = text[:stamp.start()].count("\n") + 1 if stamp else 1
    if prefer in (None, "auto") and stamp:
        prefer = stamp.group(1)
    std = L.transcode(chunk, {}, raw_hashes=True)
    orig_hashes = lua_recompile.ref_hash_set(chunk)
    tmp = Path(tempfile.mkdtemp(prefix="ship_")); tlc = tmp/"c.luac"; tlc.write_bytes(std)
    base_src, backend = decompile(tlc, luadec, jar, luac, std=std,
                                  prefer=prefer, chunk=chunk, names=names)
    baseline_msg = (
        f"This is not caused by your edit: Seam Ripper could not rebuild the "
        f"original {name or 'script'} with the '{backend}' decompiler that "
        f"line {stamp_line} of {source.name} asks for (the file was probably "
        f"read by an older Seam Ripper or with a hand-picked decompiler). "
        f"Re-read the script with the default decompiler and redo your edit "
        f"on the new file.")
    if not base_src.strip():
        raise ShipError(baseline_msg, source, stamp_line, "baseline")
    log(f"  baseline backend: {backend}")
    (tmp/"base.lua").write_text(base_src, encoding="utf-8")

    # HASH("name") -> the name's hash, spelled the way nbdec writes hashes, so
    # it compiles to the same number type as every original hashed constant.
    edit_src, expanded = expand_hash_keep_lines(text)
    for hn, value in expanded:
        log(f'  HASH("{hn}") -> {value:#010x}')
    (tmp/"edit.lua").write_bytes(edit_src.encode("utf-8"))

    try:
        base_img = compile_for(backend, tmp/"base.lua", luac, orig_hashes,
                               chunk)
    except FileNotFoundError:
        raise ShipError(f"could not run luac at '{luac}'; put luac51.exe next "
                        f"to nblua.py or set its path in Settings",
                        kind="usage")
    except Exception as e:
        raise ShipError(baseline_msg + f" (compiler said: "
                        f"{luac_error_line(e)[1]})", source, stamp_line,
                        "baseline")
    Lorig = proto360.decode_logic(orig_img)
    Lbase = proto360.decode_logic(base_img)
    if set(Lorig) != set(Lbase):
        raise ShipError(baseline_msg, source, stamp_line, "baseline")
    divergent = {p for p in Lorig if Lbase[p] != Lorig[p]}

    # what `read` wrote for this script; the edit is diffed against it
    read_text = tag_source(base_src, backend, divergent, luac)
    read_lines = read_text.splitlines()
    sm = difflib.SequenceMatcher(None, read_lines, user_lines, autojunk=False)
    hint = _stale_hint(stamp, sm)
    diff = "".join(ln + "\n" for ln in difflib.unified_diff(
        read_lines, user_lines, f"fresh read of {name or 'script'}",
        source.name, lineterm="", n=2))

    try:
        edit_img = compile_for(backend, tmp/"edit.lua", luac, orig_hashes, chunk)
    except Exception as e:
        line, msg = luac_error_line(e)
        where = f"{source.name} line {line}" if line else source.name
        raise ShipError(f"{where}: {msg}" + (f"\n  {hint}" if hint else ""),
                        source, line, "syntax")
    Ledit = proto360.decode_logic(edit_img)

    base_offset = len(read_lines) - len(base_src.splitlines())
    lmap = _line_map(sm)
    if set(Ledit) != set(Lbase):
        # first function whose position no longer lines up with the original
        try:
            e_lines = sorted(v for p, v in line_of_each_function(edit_src, luac).items()
                             if p != "0")
            b_lines = sorted(lmap.get(v + base_offset, 0) for p, v in
                             line_of_each_function(base_src, luac).items()
                             if p != "0")
            line = next((min(x, y) for x, y in zip(e_lines, b_lines) if x != y),
                        (e_lines + b_lines)[min(len(e_lines), len(b_lines))]
                        if e_lines or b_lines else 0)
        except Exception:
            line = 0
        where = f"{source.name} line {line}: " if line else f"{source.name}: "
        raise ShipError(where + "a function was added or removed, or a "
                        "function's signature changed. Edit function bodies "
                        "only." + (f"\n  {hint}" if hint else ""),
                        source, line, "structure")

    edited = {p for p in Lorig if Ledit[p] != Lbase[p]}
    leaf = {p for p in edited if not any(q != p and q.startswith(p+"_") for q in edited)}
    try:
        def_line = line_of_each_function(edit_src, luac)
    except Exception:
        def_line = {}
    top_line = _first_changed_line(sm)

    def line_of(p):
        return top_line if p == "0" else def_line.get(p, 0)

    unsafe = leaf & divergent
    if unsafe:
        first = min(unsafe, key=line_of)
        raise ShipError(
            f"{source.name} line {line_of(first)}: REFUSED: you edited "
            f"{', '.join(sorted(unsafe))}, which the decompiler could not "
            f"reproduce faithfully; shipping it would inject wrong code. Leave "
            f"those functions unchanged, or re-read this chunk with "
            f"--backend luadec and retry.", source, line_of(first), "refused")
    accidental = _renamed_globals(Lbase, Ledit, leaf)
    if accidental and not force:
        lines = [f"    {p}:  {old} -> {new}" for p, old, new in accidental]
        first = accidental[0][0]
        raise ShipError(
            f"{source.name} line {line_of(first)}: "
            "REFUSED: this edit renames a GLOBAL, which changes behaviour.\n"
            + "\n".join(lines) + "\n"
            "  luadec prints some globals as bare l_<a>_<b> tokens, exactly "
            "like locals. Renaming a local is free (the name is stripped from "
            "the bytecode, so it compiles identically), but a global is looked "
            "up BY NAME at runtime, so renaming one repoints it at a different "
            "variable.\n"
            "  If the rename was accidental, put the original name back. If "
            "you really meant to change which global is used, pass --force.",
            source, line_of(first), "refused")

    # a file read from another script, container or decompiler differs almost
    # everywhere; shipping it would replace whole functions with a different
    # reconstruction, so that needs saying out loud
    if leaf and sm.ratio() < STALE_RATIO and not force:
        raise ShipError(
            f"{source.name}: REFUSED: {hint} (Only {sm.ratio():.0%} of it "
            f"matches; shipping it would replace {len(leaf)} function(s) with "
            f"whatever this file holds.) If you really rewrote that much, "
            f"pass --force.", source, stamp_line, "stale")

    new_img = None
    if leaf:
        new_img = orig_img
        for p in sorted(leaf):
            new_img = proto360.splice(new_img, edit_img,
                                      [int(x) for x in p.split("_")[1:]])
    warnings = [hint] if hint and leaf else []
    return {"name": name, "source": str(source), "backend": backend,
            "functions": [{"path": p, "line": line_of(p)} for p in sorted(leaf)],
            "hash_calls": [{"name": n, "value": f"{v:#010x}"} for n, v in expanded],
            "diff": diff, "warnings": warnings,
            "orig_image": orig_img, "new_image": new_img}


def replace_records(lu, new_chunks):
    """The container with several records' bytes replaced, rebuilt once.

    Same layout as lu_chunk_replace.py (whose output this reproduces
    byte-for-byte for a single record): each later record at the first
    multiple of its own alignment after the previous one, 0xBF fill, and a
    compressed image re-compressed into the same number of segments.
    """
    from lzx_encode import xmem_lzx_compress
    from lu_chunk_replace import relayout, write_record_table

    def u32(b, o):
        return struct.unpack_from(">I", b, o)[0]
    raw = bytearray(lu.raw)
    image, offsets = relayout(lu, new_chunks)
    write_record_table(raw, offsets, {i: len(b) for i, b in new_chunks.items()})

    pi = 0x20 + u32(raw, 0x34)
    if not lu.compressed:
        struct.pack_into(">6I", raw, pi, 0, len(image), 0, 1, 0xFFFFFFFF, 0)
        return bytes(raw[:lu.data_base]) + bytes(image)

    window = lu.lzx_window or 0x100000
    wbits = window.bit_length() - 1
    segments = []
    for pos in range(0, len(image), window):
        seg = bytes(image[pos:pos + window])
        comp = xmem_lzx_compress(seg, wbits)
        segments.append(seg if len(comp) >= len(seg) else comp)
    if len(segments) != lu.segment_count:
        raise ShipError(
            f"this edit changes the container from {lu.segment_count} to "
            f"{len(segments)} compressed segments (the data crossed a "
            f"{window:#x}-byte boundary), which is not supported yet; trim "
            f"the edit so the script grows less", kind="slot")
    sizes_rel = u32(raw, pi + 0x10)
    so = 0x20 + sizes_rel
    for i, seg in enumerate(segments):
        struct.pack_into(">I", raw, so + 4 * i, len(seg))
    struct.pack_into(">6I", raw, pi, 2, len(image), window, len(segments),
                     sizes_rel, len(segments))
    return bytes(raw[:lu.data_base]) + b"".join(segments)


def cmd_ship(a):
    # One script, addressed by name or hash; lu_lua.py does the work so both
    # front doors share backups, previews and error reporting.
    import lu_lua
    lu = LuFile(a.lu)
    r, chunk = locate(lu, a.name, a.hash)
    if r is None:
        sys.exit("chunk not found; run `nblua.py list`")
    if b"\x1bLua" not in chunk:
        sys.exit("that record is not a Lua script chunk")
    ns = argparse.Namespace(
        lu=a.lu, name=None, index=r.index, source=a.source, out=a.out,
        backend=a.backend, jar=a.jar, luac=a.luac, stage=a.stage,
        force=getattr(a, "force", False), luadec=getattr(a, "luadec", False),
        names=getattr(a, "names", None), no_names=getattr(a, "no_names", False),
        edit=None, also=None, all_in=None, exclude=None,
        preview=getattr(a, "preview", False), json=getattr(a, "json", False))
    lu_lua.cmd_ship(ns)

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
    pr.add_argument("--backend", default="auto",
                    help="auto (default) uses nbdec, the purpose-built "
                         "decompiler, and falls back to scoring luadec and "
                         "unluac only for a chunk nbdec declines. Pin one "
                         "with nbdec / unluac / luadec / unluac+names / "
                         "luadec+names")
    pr.add_argument("--names", default=None,
                    help="CRC32 name dictionary (default: nb_names.json next "
                         "to this script; build it with nb_names.py)")
    pr.add_argument("--no-names", action="store_true",
                    help="leave hashed constants as __hash_0x placeholders")
    pr.add_argument("--luadec", action="store_true",
                    help="shorthand for --backend luadec")
    pr.add_argument("--jar", default=str(UNLUAC))
    pr.add_argument("--luac", default=None)
    pr.set_defaults(func=cmd_read)

    ps = sub.add_parser("ship", help="inject your edits back into the .lu")
    ps.add_argument("lu"); ps.add_argument("name", nargs="?")
    ps.add_argument("source", help="your edited .lua")
    ps.add_argument("--hash"); ps.add_argument("-o", "--out")
    ps.add_argument("--backend", default="auto",
                    help="normally leave this alone: `read` stamps the "
                         "backend it used into the .lua and ship reuses it, "
                         "so the baseline matches what you edited")
    ps.add_argument("--names", default=None)
    ps.add_argument("--no-names", action="store_true")
    ps.add_argument("--force", action="store_true",
                    help="ship even when the edit renames a global "
                         "(see the REFUSED message for what that means)")
    ps.add_argument("--luadec", action="store_true",
                    help="shorthand for --backend luadec")
    ps.add_argument("--jar", default=str(UNLUAC))
    ps.add_argument("--luac", default=None)
    ps.add_argument("--stage", help="build assets\\lu folder to copy result into")
    ps.add_argument("--preview", action="store_true",
                    help="write nothing; show what would be recompiled and a "
                         "diff of your edit")
    ps.add_argument("--json", action="store_true",
                    help="print the result as one JSON object on stdout")
    ps.set_defaults(func=cmd_ship)

    pv = sub.add_parser("verify", help="check any .lu's container integrity")
    pv.add_argument("lu")
    pv.add_argument("--verifier", help="path to the independent decoder binary")
    pv.set_defaults(func=cmd_verify)

    a = ap.parse_args()
    if a.cmd in ("read", "ship") and not (a.name or a.hash):
        sys.exit("give a chunk name (or --hash). Run `nblua.py list` to see them.")
    # --luadec predates --backend and is still what older callers (and the
    # GUI checkbox) pass; treat it as a shorthand rather than breaking them.
    if getattr(a, "luadec", False) and getattr(a, "backend", "auto") == "auto":
        a.backend = "luadec"
    a.func(a)

if __name__ == "__main__":
    # so `import nblua` elsewhere gets this module, not a second copy
    sys.modules.setdefault("nblua", sys.modules[__name__])
    main()
