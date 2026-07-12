#!/usr/bin/env python3
"""
pip_scripts.py — extract Panic in Paradise Lua scripts.

Unlike the original Naughty Bear (which ships *compiled* Lua bytecode in
its animation/ chunks — see lua_decompile.py), PiP ships **plaintext Lua
source** in its animation chunks (type 04b00000), comments and all.
No decompilation needed; this tool slices the source straight out and
rebuilds the original on-disk script tree from the embedded paths.

Chunk layout (big-endian):
  0x00  u32 name hash
  0x04  u32 type = 0x04b00000
  0x10  u32 path_offset
  0x14  u32 path_length      (the z:\\nb2_data\\...\\X.lua source path)
  0x18  u32 source_offset
  0x1c  u32 source_length    (the Lua source text)
  0x20  u32 source_end
  0x24  u32 trailer_length

usage:
  python3 pip_scripts.py extract <extract_root>... -o scripts_out/
  # mirrors the original tree, e.g.
  #   scripts_out/nb2_data/assets/scripts/global/factionutil.lua

  python3 pip_scripts.py inject <orig.lu> <edited .lua files...> -o out.lu
  # matches each edited file to its chunk by the embedded source path
  # (longest path-suffix match), rebuilds the chunk (offsets fixed up)
  # and writes a new container (raw segments — engine-verified).
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_script_chunk(c):
    """Split a 04b00000 chunk into its parts. Round-trips byte-identically
    with build_script_chunk (validated on all script chunks in global.lu)."""
    h = struct.unpack_from(">I", c, 0)[0]
    po, pl, so, sl, to, tl = struct.unpack_from(">6I", c, 0x10)
    return {"hash": h, "path": bytes(c[po:po + pl]),
            "src": bytes(c[so:so + sl]), "trailer": bytes(c[to:to + tl])}


def build_script_chunk(parts):
    path, src, trailer = parts["path"], parts["src"], parts["trailer"]
    po = 0x28
    so = po + len(path)
    pad = (-so) % 4
    so += pad
    to = so + len(src)
    hdr = struct.pack(">10I", parts["hash"], 0x04B00000, 0, 0,
                      po, len(path), so, len(src), to, len(trailer))
    return hdr + path + b"\xBF" * pad + src + trailer


def squeeze_lua(src, budget):
    """Reclaim space to fit an edited script back into its original slot,
    using ONLY safe, non-structural transforms and stopping the instant it
    fits. Trailing whitespace and blank-line runs first (invisible changes),
    then — only if still over — collapsed runs of internal spaces/tabs, which
    the game tolerates but which do alter the file more visibly.

    Deliberately does NOT strip comments or reindent: those touch nearly
    every line of a large table and, empirically, a heavily-reflowed data
    script hangs the game at load even when it re-parses fine. If the edit
    still doesn't fit after whitespace reclamation, the caller errors out
    rather than shipping a mangled chunk. Keeping edits small enough to fit
    their slot is the intended workflow.
    """
    import re
    before = len(src)
    steps = [
        lambda t: re.sub(rb"[ \t]+\n", b"\n", t),          # trailing ws
        lambda t: re.sub(rb"\n\n\n+", b"\n\n", t),         # blank-run collapse
        lambda t: re.sub(rb"[ \t][ \t]+", b" ", t),        # internal run -> 1
    ]
    for fn in steps:
        if len(src) <= budget:
            break
        src = fn(src)
    if len(src) <= budget and len(src) != before:
        sys.stderr.write(
            f"  note: reclaimed {before - len(src)} bytes of whitespace to fit "
            f"the edit in its slot\n")
    return src


def norm_path(p):
    p = str(p).replace("\\", "/").lower().rstrip("\x00")
    if ":" in p:
        p = p.split(":", 1)[1]
    return p.lstrip("/")


def lua_sanity_check(src):
    """A dependency-free sanity check for edited Lua 5.1 source. NOT a parser:
    it flags only high-confidence structural breakage — unbalanced brackets
    and unterminated strings/comments — while correctly skipping strings, long
    strings, and both comment forms. Returns a list of problem strings (empty
    == looks OK), with zero false positives across the retail script corpus.

    It deliberately does NOT try to balance do/then/function/end blocks:
    keyword-counting without a real parser false-positives on perfectly valid
    code (e.g. `end` in identifiers, `function` as a table value), and the
    bracket/string checks already catch the great majority of fat-finger edits
    that would hang the game. A malformed block still surfaces as a load-time
    Lua error the user can see, rather than the silent hang that unbalanced
    brackets/strings cause.
    """
    text = src.decode("latin-1") if isinstance(src, (bytes, bytearray)) else src
    problems = []
    i, n = 0, len(text)
    depth = {"()": 0, "[]": 0, "{}": 0}
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c == "-" and text[i:i+2] == "--":
            if text[i:i+4] == "--[[":
                j = text.find("]]", i+4)
                if j < 0:
                    problems.append("unterminated --[[ long comment"); break
                line += text.count("\n", i, j); i = j+2; continue
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text[i:i+2] == "[[":
            j = text.find("]]", i+2)
            if j < 0:
                problems.append("unterminated [[ long string"); break
            line += text.count("\n", i, j); i = j+2; continue
        if c in "\"'":
            q = c; j = i+1; closed = False
            while j < n and text[j] != q:
                if text[j] == "\\":
                    j += 2
                elif text[j] == "\n":
                    break
                else:
                    j += 1
            else:
                closed = j < n            # loop ended by finding the quote
            if j < n and text[j] == q:
                closed = True
            if not closed:
                problems.append(f"unterminated string at line {line}")
            i = j+1; continue
        if c in "([{":
            depth[{"(": "()", "[": "[]", "{": "{}"}[c]] += 1
        elif c in ")]}":
            depth[{")": "()", "]": "[]", "}": "{}"}[c]] -= 1
        i += 1
    for pair, d in depth.items():
        if d > 0:
            problems.append(f"{d} unclosed '{pair[0]}'")
        elif d < 0:
            problems.append(f"{-d} extra '{pair[1]}'")
    return problems


def cmd_inject(args):
    from naughty_lu import LuFile, rebuild_luh
    lu = LuFile(args.orig)
    chunks = {}          # record index -> parsed parts
    for r in lu.records:
        if r.type == 0x04B00000 and not r.external:
            chunks[r.index] = parse_script_chunk(bytes(lu.chunk(r)))

    new_chunks = {}
    for edited in args.scripts:
        ep = Path(edited)
        etoks = norm_path(ep).split("/")
        best, best_n = None, 0
        for idx, parts in chunks.items():
            ctoks = norm_path(parts["path"].decode("ascii", "replace")).split("/")
            n = 0
            while (n < len(etoks) and n < len(ctoks)
                   and etoks[-1 - n] == ctoks[-1 - n]):
                n += 1
            if n > best_n:
                best, best_n = idx, n
        if best is None or best_n == 0:
            sys.exit(f"inject: no chunk in {args.orig} matches {edited}")
        src = ep.read_bytes().replace(b"\r\n", b"\n")
        # pre-flight: catch the fat-fingered structural errors that hang the
        # game silently at load, before we build a container around them.
        issues = lua_sanity_check(src)
        if issues:
            msg = (f"inject: {ep.name} has Lua structure problems that would "
                   f"likely hang the game:\n    - " + "\n    - ".join(issues))
            if getattr(args, "force", False):
                sys.stderr.write(msg + "\n  (--force given: injecting anyway)\n")
            else:
                sys.exit(msg + "\n  fix the script, or pass --force to override.")
        parts = dict(chunks[best])
        old_len = len(parts["src"])
        # scripts must fit their original slot: several unit types (global.lu
        # among them) reference image regions by absolute offset, so a chunk
        # that grows past its slot gets relocated and hangs the game at boot
        # (verified empirically). Auto-squeeze whitespace/comments to fit.
        rec = next(r for r in lu.records if r.index == best)
        ordered = sorted((r for r in lu.records if not r.external),
                         key=lambda r: r.offset)
        pos = [r.index for r in ordered].index(best)
        slot = ((ordered[pos + 1].offset if pos + 1 < len(ordered)
                 else lu.image_size) - rec.offset)
        budget = slot - len(build_script_chunk({**parts, "src": b""}))
        if len(src) > budget:
            src = squeeze_lua(src, budget)
        if len(src) > budget:
            sys.exit(f"inject: {ep.name} is {len(src) - budget} bytes too "
                     f"large for its slot even after squeezing "
                     f"(slot allows {budget} source bytes); trim the script")
        parts["src"] = src
        new_chunks[best] = build_script_chunk(parts)
        print(f"  {ep.name} -> record {best} "
              f"({parts['path'].decode('ascii', 'replace').rstrip(chr(0))}), "
              f"{old_len} -> {len(src)} bytes")

    data = rebuild_luh(lu, new_chunks)
    Path(args.out).write_bytes(data)
    print(f"injected {len(new_chunks)} script(s) -> {args.out} ({len(data):,} bytes)")

    # verify: re-extract each injected source and compare
    lu2 = LuFile(args.out)
    ok = True
    for idx, chunk in new_chunks.items():
        got = parse_script_chunk(bytes(lu2.chunk(lu2.records[idx])))["src"]
        want = parse_script_chunk(chunk)["src"]
        if got != want:
            print(f"  VERIFY FAIL record {idx}", file=sys.stderr)
            ok = False
    print("VERIFY OK: container re-parses, injected sources read back identical"
          if ok else "VERIFY had failures")


def extract_lua(d):
    """(relative_path, source_text) or None."""
    if len(d) < 0x28 or struct.unpack_from(">I", d, 4)[0] != 0x04b00000:
        return None
    po, pl, so, sl = struct.unpack_from(">4I", d, 0x10)
    if not (0 < so < len(d) and 0 < sl <= len(d) - so):
        return None
    if not (0 < po < len(d) and 0 < pl <= len(d) - po):
        return None
    path = d[po:po + pl].split(b"\x00")[0].decode("ascii", "replace")
    src = d[so:so + sl].split(b"\x00")[0].decode("latin-1")
    # normalise the embedded path: drop drive, unify separators
    rel = path.replace("\\", "/").lstrip("/")
    if ":" in rel:
        rel = rel.split(":", 1)[1].lstrip("/")
    return rel, src


SCRIPT_TYPE = 0x04B00000


def _iter_script_chunks(lu):
    """Yield (record, raw_chunk_bytes) for every script chunk in a container,
    for both PiP (plaintext) and NB1 (\\x1bLua bytecode) — the record type is
    0x04b00000 in both games."""
    for r in lu.records:
        if r.type == SCRIPT_TYPE and not getattr(r, "external", False):
            yield r, bytes(lu.chunk(r))


def _script_path(chunk):
    """Recover the embedded z:\\...\\name.lua path from a script chunk, or None.
    Works for PiP (path in a header field) and NB1 (path embedded near the
    Lua image); we just scan for the z:\\ ... .lua pattern, which both use."""
    import re
    m = re.search(rb"z:\\[\x20-\x7e]+?\.lua", chunk)
    if m:
        return m.group().decode("latin-1")
    return None


def cmd_find(args):
    r"""Locate which container(s) hold a given script. Prints, per match:
        <file>  <record#>  <embedded path>  [game]
    so you can feed the file straight into extract/inject.

    Works on both PiP LUH and NB1 x36 containers (auto-detected): the script
    record type (0x04b00000) and the embedded z:\...\name.lua source path
    are the same convention in both games, so one command covers both.
    NB1 chunks hold Lua 5.1 bytecode rather than plaintext source, but the
    embedded path is a plain string either way, which is all `find` reads.
    """
    import re
    from naughty_lu import LuFile

    files = []
    for p in map(Path, args.inputs):
        if p.is_dir():
            files += sorted(x for x in p.rglob("*.lu"))
            files += sorted(x for x in p.rglob("*.luh"))
        else:
            files.append(p)

    needle = args.name.lower().replace("\\", "/")
    rx = re.compile(args.name, re.I) if args.regex else None
    n_hits = 0
    for f in files:
        try:
            lu = LuFile(str(f))
        except Exception:
            continue
        game = "PiP" if getattr(lu, "is_luh", False) else "NB1"
        for r, chunk in _iter_script_chunks(lu):
            path = _script_path(chunk) or ""
            stem = path.replace("\\", "/").rsplit("/", 1)[-1][:-4].lower() if path else ""
            hit = (rx.search(path) if rx
                   else (needle in path.replace("\\", "/").lower()
                         or needle == stem))
            if hit:
                shown = path or f"(record {r.index}, no embedded path)"
                print(f"{f.name}\t{r.index}\t{shown}\t[{game}]")
                n_hits += 1
    if not n_hits:
        print(f"no script matching {args.name!r} found in {len(files)} container(s)",
              file=sys.stderr)
        sys.exit(1)


def cmd_extract(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    n = empty = dupe = 0
    seen = {}
    for root in args.roots:
        for p in sorted(Path(root).glob("*/animation/*.bin")):
            d = p.read_bytes()
            if not d:
                empty += 1
                continue
            r = extract_lua(d)
            if r is None:
                continue
            rel, src = r
            if len(src.strip()) < 2:
                empty += 1
                continue
            if args.flat:
                dest = out / p.parent.parent.name / (Path(rel).name)
            else:
                dest = out / rel
            # de-dup identical sources shipped in multiple units
            if dest in seen:
                if seen[dest] == src:
                    dupe += 1
                    continue
                stem = dest.with_suffix("")
                dest = Path(f"{stem}__{p.parent.parent.name}.lua")
            seen[dest] = src
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src, encoding="utf-8", errors="replace")
            n += 1
    print(f"extracted {n} Lua source files "
          f"({dupe} duplicate copies skipped, {empty} empty chunks)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("find", help="locate which container(s) hold a script")
    pf.add_argument("name", help="script name (e.g. gamemodes) or path fragment")
    pf.add_argument("inputs", nargs="+", help=".lu files or folders to search")
    pf.add_argument("-e", "--regex", action="store_true",
                    help="treat name as a regex matched against the full path")
    pf.set_defaults(func=cmd_find)

    pe = sub.add_parser("extract", help="slice Lua source out of extracted chunks")
    pe.add_argument("roots", nargs="+")
    pe.add_argument("-o", "--out", required=True)
    pe.add_argument("--flat", action="store_true",
                    help="write <unit>/<name>.lua instead of mirroring "
                         "the original source tree")
    pe.set_defaults(func=cmd_extract)

    pi = sub.add_parser("inject", help="write edited Lua source back into a .lu")
    pi.add_argument("orig", help="original PiP .lu container")
    pi.add_argument("scripts", nargs="+", help="edited .lua file(s)")
    pi.add_argument("-o", "--out", required=True, help="output .lu")
    pi.add_argument("--force", action="store_true",
                    help="inject even if the Lua sanity check flags problems")
    pi.set_defaults(func=cmd_inject)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
