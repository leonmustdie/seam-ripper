#!/usr/bin/env python3
"""Look up hashed names both ways: name to hash, hash to name."""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import nb_names  # noqa: E402

_CACHE = {}


def load_names(refresh=False):
    """{hash: name} from nb_names.json, read once per process."""
    if refresh or "names" not in _CACHE:
        _CACHE["names"] = nb_names.load()
    return _CACHE["names"]


def load_text(refresh=False):
    """{hash: (display text, "NB1" | "NB2")} from nb_text.json, read once."""
    if refresh or "text" not in _CACHE:
        _CACHE["text"] = nb_names.load_text()
    return _CACHE["text"]


def load_tiers(refresh=False):
    """{hash: tier} from nb_names_sources.json, read once."""
    if refresh or "tiers" not in _CACHE:
        _CACHE["tiers"] = nb_names.load_sources()[0]
    return _CACHE["tiers"]


def name_hash(name):
    """CRC32 of the lowercased name, the way both games hash names."""
    return nb_names.crc(name)


def signed(value):
    """The same 32 bits read as a signed integer (how PiP sometimes stores it)."""
    return value - (1 << 32) if value >= 1 << 31 else value


def formats(value):
    """{"hex", "decimal", "signed", "nb1", "pip"} spellings of one hash."""
    return {"hex": f"0x{value:08x}", "decimal": value, "signed": signed(value),
            "nb1": f"0x{value:08x}", "pip": str(value)}


_HEX = re.compile(r"[0-9a-fA-F]+")


def parse_hash(text):
    """Every reading of `text` as a 32-bit hash -> [(value, how), ...].

    Accepts 0x-prefixed hex, bare hex, unsigned or negative decimal, and
    decimals written with a trailing .0. A bare string of digits is both
    valid hex and valid decimal, so both readings come back (decimal
    first); [] means it is not a number at all."""
    t = text.strip().strip("\"'").replace("_", "")
    out = []

    def add(v, how):
        if -(1 << 31) <= v < (1 << 32):
            v &= 0xFFFFFFFF
            if all(v != x for x, _ in out):
                out.append((v, how))
    if not t:
        return out
    if t[:2].lower() == "0x":
        if _HEX.fullmatch(t[2:]):
            add(int(t[2:], 16), "hex")
        return out
    m = re.fullmatch(r"(-?\d+)(?:\.0*)?", t)
    if m:
        add(int(m.group(1)), "signed decimal" if t.startswith("-")
            else "decimal")
    if _HEX.fullmatch(t) and len(t) <= 8:
        add(int(t, 16), "hex")
    return out


def describe(value, names=None, text=None, tiers=None):
    """Everything known about one hash value, as a dict:

    {"hash": int, "hex": "0x........", "decimal": int, "signed": int,
     "nb1": "0x........", "pip": "<decimal>", "names": [name, ...],
     "text": display text or None, "text_game": "NB1" | "NB2" | None,
     "tier": "found" | "rule" | "confirmed" | "searched" | "review" | None}
    """
    names = load_names() if names is None else names
    text = load_text() if text is None else text
    tiers = load_tiers() if tiers is None else tiers
    value &= 0xFFFFFFFF
    got = [names[value]] if value in names else []
    tx = text.get(value)
    return {"hash": value, **formats(value), "names": got,
            "text": tx[0] if tx else None, "text_game": tx[1] if tx else None,
            "tier": tiers.get(value) if got else None}


def lookup_hash(text, names=None, textdb=None, tiers=None):
    """describe() for every reading of `text` as a hash, each with "how"."""
    out = []
    for v, how in parse_hash(text):
        d = describe(v, names, textdb, tiers)
        d["how"] = how
        out.append(d)
    return out


def lookup_name(name, names=None, textdb=None, tiers=None):
    """describe() of the name's hash, plus "name" and "known" (the dictionary
    already holds this name, ignoring case)."""
    d = describe(name_hash(name), names, textdb, tiers)
    d["name"] = name
    d["known"] = any(n.lower() == name.lower() for n in d["names"])
    return d


_NUMBER = re.compile(r"0[xX][0-9a-fA-F_]*|-?[0-9_]+(\.0*)?")


def lookup(text, names=None, textdb=None, tiers=None):
    """Answer a box that takes either kind of text -> {"kind": "hash" | "name"
    | "empty" | "bad", "query", "results": [describe() dicts, hash readings
    with "how", a name with "name" and "known"], "message"}.

    0x... and plain or negative decimals are hashes; anything else is a name
    (a name that is also eight hex digits gets its hash reading too, last)."""
    t = text.strip()
    if not t:
        return {"kind": "empty", "query": text, "results": [], "message": ""}
    if _NUMBER.fullmatch(t.strip("\"'")):
        got = lookup_hash(t, names, textdb, tiers)
        if not got:
            return {"kind": "bad", "query": t, "results": [],
                    "message": f"{t} is not a 32-bit hash (0x00000000 to "
                               f"0xFFFFFFFF, or the same as a decimal)."}
        return {"kind": "hash", "query": t, "results": got, "message": ""}
    d = lookup_name(t, names, textdb, tiers)
    out = [d]
    if re.fullmatch(r"[0-9a-fA-F]{8}", t):
        out += lookup_hash(t, names, textdb, tiers)
    return {"kind": "name", "query": t, "results": out, "message": ""}


def search_names(query, prefix=False, limit=100, names=None):
    """Known names containing (or, with prefix=True, starting with) `query`,
    ignoring case -> [(name, hash), ...] sorted by name, at most `limit`
    (None for all)."""
    names = load_names() if names is None else names
    q = query.lower()
    hit = (lambda n: n.lower().startswith(q)) if prefix else \
        (lambda n: q in n.lower())
    out = sorted(((n, h) for h, n in names.items() if hit(n)),
                 key=lambda x: (x[0].lower(), x[0]))
    return out if limit is None else out[:limit]


# --------------------------------------------------------------------- cli
def _show(d):
    lines = [f"  hash     {d['hex']}  (decimal {d['decimal']}, "
             f"signed {d['signed']})"]
    if d["names"]:
        tier = f"  [{d['tier']}]" if d.get("tier") else ""
        lines.append(f"  name     {', '.join(d['names'])}{tier}")
    else:
        lines.append("  name     (not in the name dictionary)")
    if d["text"]:
        lines.append(f"  text     {d['text']!r}"
                     + ("  (Panic in Paradise's wording)"
                        if d["text_game"] == "NB2" else ""))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pn = sub.add_parser("name", help="hash a name")
    pn.add_argument("name")
    ph = sub.add_parser("hash", help="find the name behind a hash "
                        "(0x hex, bare hex, decimal or negative decimal)")
    ph.add_argument("value")
    pa = sub.add_parser("any", help="a name or a hash, whichever it is")
    pa.add_argument("text")
    ps = sub.add_parser("search", help="known names containing some text")
    ps.add_argument("text")
    ps.add_argument("--prefix", action="store_true",
                    help="only names that start with the text")
    ps.add_argument("--limit", type=int, default=100)
    for p in (pn, ph, pa, ps):
        p.add_argument("--json", action="store_true",
                       help="print machine-readable JSON")
    a = ap.parse_args()

    if a.cmd == "name":
        d = lookup_name(a.name)
        if a.json:
            print(json.dumps(d, ensure_ascii=False))
            return
        print(f'{a.name}\n{_show(d)}')
        print(f'  in NB1 source write 0x{d["hash"]:08x}, in PiP source '
              f'{d["hash"]}, or HASH("{a.name}") in either')
        if d["names"] and not d["known"]:
            print(f"  note: the dictionary knows this hash as another name")
    elif a.cmd == "any":
        got = lookup(a.text)
        if a.json:
            print(json.dumps(got, ensure_ascii=False))
            return
        if got["message"]:
            sys.exit(got["message"])
        for d in got["results"]:
            print(f"{d.get('name') or a.text}\n{_show(d)}")
    elif a.cmd == "hash":
        got = lookup_hash(a.value)
        if a.json:
            print(json.dumps(got, ensure_ascii=False))
            return
        if not got:
            sys.exit(f"'{a.value}' is not a number; to hash a name use "
                     f"`sr_lookup.py name {a.value}`")
        for d in got:
            print(f"{a.value} read as {d['how']}\n{_show(d)}")
    else:
        got = search_names(a.text, a.prefix, a.limit)
        if a.json:
            print(json.dumps([{"name": n, "hash": h, "hex": f"0x{h:08x}"}
                              for n, h in got], ensure_ascii=False))
            return
        for n, h in got:
            print(f"0x{h:08x}  {h:>10}  {n}")
        print(f"{len(got)} name(s)" + (" (limit reached; use --limit)"
                                       if len(got) == a.limit else ""))


if __name__ == "__main__":
    main()
