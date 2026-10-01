#!/usr/bin/env python3
r"""Recover the string names behind Naughty Bear's hashed constants."""
import argparse
import json
import re
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CACHE = HERE / "nb_names.json"

NAME_RE = re.compile(rb"z:\\[\x20-\x7e]+?\.lua")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
QUOTED = re.compile(r"""["']([^"'\n]{2,64})["']""")
ASCII = re.compile(rb"[\x20-\x7e]{3,64}")

# Values below this are treated as integers, never as hashes. A 32-bit CRC is
# uniform over 0..4.29e9, so the chance of a real hash landing this low is
# about 0.2%, while gameplay integers (counts, priorities, score thresholds)
# cluster here. Getting this wrong in the other direction is what makes an
# empty string - crc32(b"") is 0 - look like the hash 0x00000000.
HASH_FLOOR = 10 ** 7


def crc(s):
    if isinstance(s, str):
        s = s.encode("latin-1", "replace")
    return zlib.crc32(s.lower()) & 0xFFFFFFFF


# HASH("name") in edited source: the modder writes the name, ship writes the
# number. Matches single or double quotes; the name may not contain its quote.
HASH_CALL = re.compile(r"""\bHASH\(\s*(["'])([^"'\n]*?)\1\s*\)""")


def expand_hash_calls(src, fmt="0x{:08x}"):
    """-> (src with every HASH("name") replaced by crc(name) spelled by fmt,
    [(name, value), ...] in order of appearance)."""
    found = []

    def sub(m):
        v = crc(m.group(2))
        found.append((m.group(2), v))
        return fmt.format(v)
    return HASH_CALL.sub(sub, src), found


def classify(value):
    """"hash" or "int" - the best guess for one 0xFE value, on value alone."""
    return "hash" if value >= HASH_FLOOR else "int"


# ------------------------------------------------------------------ sources
def _containers(paths):
    from naughty_lu import LuFile
    for p in paths:
        p = Path(p)
        files = sorted(p.rglob("*.lu")) if p.is_dir() else [p]
        for f in files:
            try:
                yield f, LuFile(str(f))
            except Exception:
                continue


def tokens_from_pip(paths):
    """Identifiers and string literals from PiP's plaintext scripts."""
    import pip_scripts
    out = set()
    for f, lu in _containers(paths):
        if "LUH" not in getattr(lu, "platform", ""):
            continue
        for r in lu.records:
            if r.type != 0x04B00000 or getattr(r, "external", False):
                continue
            try:
                got = pip_scripts.extract_lua(bytes(lu.chunk(r)))
            except Exception:
                continue
            if got:
                out.update(WORD.findall(got[1]))
                out.update(QUOTED.findall(got[1]))
    return out


def tokens_from_nb1_constants(paths):
    """Plain string constants inside NB1's own compiled chunks."""
    import lua_decompile as L
    out = set()
    for f, lu in _containers(paths):
        img = lu.image
        for r in lu.records:
            ch = img[r.offset:r.offset + r.size]
            if b"\x1bLua" not in ch:
                continue
            try:
                std = L.transcode(ch, {}, raw_hashes=True)
            except Exception:
                continue
            for s in ASCII.findall(std):
                t = s.decode("latin-1")
                if t.startswith("__hash_0x"):
                    continue
                out.add(t)
                out.update(WORD.findall(t))
    return out


def tokens_from_paths(paths):
    out = set()
    for f, lu in _containers(paths):
        for m in NAME_RE.finditer(bytes(lu.image)):
            p = m.group().decode("latin-1")
            out.add(p)
            for piece in re.split(r"[\\/]", p):
                out.add(piece)
                if piece.lower().endswith(".lua"):
                    out.add(piece[:-4])
    return out


def tokens_from_raw(paths):
    out = set()
    for f, lu in _containers(paths):
        for m in ASCII.finditer(bytes(lu.image)):
            s = m.group().decode("latin-1")
            out.add(s)
            for piece in re.split(r"[\\/.]", s):
                if 2 < len(piece) < 64:
                    out.add(piece)
    return out


def hashes_used(nb1_paths):
    """Every 0xFE value that actually appears in the given NB1 containers."""
    import lua_decompile as L
    used = set()
    for f, lu in _containers(nb1_paths):
        img = lu.image
        for r in lu.records:
            ch = img[r.offset:r.offset + r.size]
            if b"\x1bLua" not in ch:
                continue
            try:
                std = L.transcode(ch, {}, raw_hashes=True)
            except Exception:
                continue
            for h in re.findall(rb"__hash_0x([0-9a-fA-F]{8,16})", std):
                used.add(int(h, 16) & 0xFFFFFFFF)
    return used


def build(pip_paths=(), nb1_paths=(), prune=True):
    """-> {crc32: name}. Earlier sources win; later ones only fill gaps.

    prune keeps only entries that actually name a constant present in the
    given NB1 containers. The raw-text layer contributes half a million
    candidate strings to resolve about a hundred values, so an unpruned
    dictionary is ~12 MB of which almost none is ever consulted. Pruned it is
    a few tens of KB. Rebuild with more containers to cover more of the game.
    """
    d = {}
    layers = []
    if pip_paths:
        layers.append(("pip-source", tokens_from_pip(pip_paths)))
    if nb1_paths:
        layers.append(("nb1-constants", tokens_from_nb1_constants(nb1_paths)))
    layers.append(("paths", tokens_from_paths(list(pip_paths) + list(nb1_paths))))
    if nb1_paths:
        layers.append(("raw-text", tokens_from_raw(nb1_paths)))
    for label, toks in layers:
        added = 0
        for t in toks:
            if not t:
                continue
            h = crc(t)
            if h not in d:
                d[h] = t
                added += 1
        print(f"  {label:<16} {len(toks):>8,} tokens, {added:>8,} new entries",
              file=sys.stderr)
    if prune and nb1_paths:
        used = hashes_used(nb1_paths)
        before = len(d)
        d = {k: v for k, v in d.items() if k in used}
        print(f"  {'pruned':<16} {before:>8,} -> {len(d):>8,} entries "
              f"({len(used):,} constants in the containers given)",
              file=sys.stderr)
    return d


# ------------------------------------------------------------ display text
# Most hashes with no recoverable name are TEXT IDs: an objective, an NPC's
# display name, a HUD message. The ID's own name was never shipped, but the
# text it stands for is - NB1 stores every localized string as its own
# record, keyed by that same hash. Showing the text next to the hash tells a
# modder exactly what it is, which the name would only have hinted at.
TEXT_CACHE = HERE / "nb_text.json"


def build_text(paths, suffix=".en_us.lu"):
    """-> {hash: text} from NB1 localization containers (English by
    default). A hash whose text differs between containers keeps the first."""
    import lu_strings
    out = {}
    for f, lu in _containers(paths):
        if not f.name.lower().endswith(suffix):
            continue
        try:
            img = lu.image
        except Exception:
            continue
        for r in lu.records:
            try:
                text, n, _ = lu_strings.read_string(img, r.offset)
            except Exception:
                continue
            if 0 < n <= 4096 and text.strip():
                out.setdefault(r.hash, text)
    return out


def build_text_nb2(paths, suffix=".en_us.lu"):
    """-> {hash: text} from Panic in Paradise's localization containers.

    The two games share many text IDs, so NB2's text can label an NB1 hash
    NB1's own text does not cover. It is kept apart and marked as NB2's
    wherever it is shown: the ID is the same, but NB2's wording (a score
    threshold, an unlock condition) can differ from NB1's."""
    import lu_strings
    out = {}
    for f, lu in _containers(paths):
        if not f.name.lower().endswith(suffix):
            continue
        for r in lu.records:
            if r.type != lu_strings.PIP_TABLE_TYPE or r.external:
                continue
            try:
                for h, text in lu_strings.pip_parse_table(bytes(lu.chunk(r))):
                    if text.strip():
                        out.setdefault(h, text)
            except Exception:
                continue
    return out


def load_text(path=None):
    """The cached {hash: (display text, "NB1" | "NB2")}, NB1 first.

    NB1's own text wins wherever it exists; NB2's only fills gaps."""
    p = Path(path) if path else TEXT_CACHE
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {int(k): (v, "NB2") for k, v in raw.get("nb2", {}).items()}
    out.update({int(k): (v, "NB1") for k, v in raw.get("text", raw).items()
                if not isinstance(v, dict)})
    return out


def save_text(d, path=None, nb2=None):
    """d: NB1's {hash: text}; nb2: NB2's, kept as a separate layer."""
    p = Path(path) if path else TEXT_CACHE
    body = {"version": 2, "count": len(d),
            "text": {str(k): v for k, v in sorted(d.items())}}
    if nb2:
        body["nb2"] = {str(k): v for k, v in sorted(nb2.items())}
    p.write_text(json.dumps(body, indent=0, ensure_ascii=False),
                 encoding="utf-8")
    return p


# ------------------------------------------------------------------- cache
def load(path=None):
    """The cached dictionary as {crc32: name}, or {} if there is none."""
    p = Path(path) if path else CACHE
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {int(k): v for k, v in raw.get("names", raw).items()}


def save(d, path=None):
    p = Path(path) if path else CACHE
    p.write_text(json.dumps({"version": 1, "count": len(d),
                             "names": {str(k): v for k, v in sorted(d.items())}},
                            indent=0), encoding="utf-8")
    return p


# ----------------------------------------------------------------- sources
# Where each name came from, kept beside the dictionary so its format stays
# {hash: name}:
#   found     the name is text somewhere in the game's own data (build)
#   rule      nb_reconstruct.py rebuilds it from the found names alone
#             (checked by `nb_reconstruct.py --verify`)
#   searched  a one-off search over a stated pattern; odds noted per batch
#   review    a searched name whose search was broad enough that only its
#             fit to its context vouches for it; worth a human look
#   confirmed a searched or review name a person who knows the game checked
#             against what it does in play
SOURCES = HERE / "nb_names_sources.json"
TIERS = ("found", "rule", "confirmed", "searched", "review")


def load_sources(path=None):
    """-> ({hash: tier}, {hash: note}); both empty if there is no file."""
    p = Path(path) if path else SOURCES
    if not p.exists():
        return {}, {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    return ({int(k): v for k, v in raw.get("tiers", {}).items()},
            {int(k): v for k, v in raw.get("notes", {}).items()})


def save_sources(tiers, notes=None, path=None):
    p = Path(path) if path else SOURCES
    counts = {t: sum(1 for v in tiers.values() if v == t) for t in TIERS}
    p.write_text(json.dumps({
        "version": 1, "counts": counts,
        "tiers": {str(k): v for k, v in sorted(tiers.items())},
        "notes": {str(k): v for k, v in sorted((notes or {}).items())}},
        indent=0, ensure_ascii=False), encoding="utf-8")
    return p


# --------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the CRC32 name dictionary")
    b.add_argument("--pip", nargs="*", default=[],
                   help="Panic in Paradise .lu files or folders (best source)")
    b.add_argument("--nb1", nargs="*", default=[],
                   help="Naughty Bear .lu files or folders")
    b.add_argument("-o", "--out", default=None)
    b.add_argument("--no-prune", action="store_true",
                   help="keep every candidate, not just the ones that "
                        "name a constant actually present in --nb1")

    bt = sub.add_parser("build-text", help="build the hash -> display text "
                        "table from localization containers (*.en_us.lu)")
    bt.add_argument("inputs", nargs="+", help="NB1 .lu files or folders")
    bt.add_argument("--nb2", nargs="*", default=[],
                    help="Panic in Paradise .lu files or folders, used only "
                         "where NB1 has no text, and marked as NB2's")
    bt.add_argument("-o", "--out", default=None)

    lk = sub.add_parser("lookup", help="look up one hash")
    lk.add_argument("value")

    a = ap.parse_args()
    if a.cmd == "build-text":
        d = build_text(a.inputs)
        nb2 = build_text_nb2(a.nb2) if a.nb2 else None
        p = save_text(d, a.out, nb2)
        print(f"{len(d):,} NB1 text entries"
              + (f", {len(nb2):,} NB2" if nb2 else "") + f" -> {p}")
        return
    if a.cmd == "build":
        if not (a.pip or a.nb1):
            sys.exit("give --pip and/or --nb1 sources")
        d = build(a.pip, a.nb1, prune=not a.no_prune)
        p = save(d, a.out)
        print(f"{len(d):,} names -> {p}")
    else:
        d = load()
        v = int(a.value, 0)
        print(d.get(v, f"(not in dictionary; looks like a "
                       f"{classify(v)}, value {v})"))


if __name__ == "__main__":
    main()
