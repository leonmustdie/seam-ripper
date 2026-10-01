#!/usr/bin/env python3
"""Warn when a Panic in Paradise script edit leaves the shape of the game's own data tables."""
import argparse
import bisect
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCHEMA_VERSION = 1
MAX_VALUES = 12             # distinct values remembered per field
HASH_FLOOR = 10 ** 7        # nb_names.HASH_FLOOR: at or above this, an ID
MIN_SEEN = 3                # retail examples a field needs before its range
                            # or value set is used to judge an edit

# ------------------------------------------------------------------ lexer
_TOKEN = re.compile(r"""
    (?P<ws>[ \t\f\v]+|\r\n|\r|\n)
  | (?P<long>\[=*\[)
  | (?P<com>--)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<num>0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>["'])
  | (?P<op>\.\.\.|\.\.|==|~=|<=|>=|.)
""", re.X | re.S)
_NEWLINE = re.compile(r"\r\n|\r|\n")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_ESC = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
        "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for",
            "function", "if", "in", "local", "nil", "not", "or", "repeat",
            "return", "then", "true", "until", "while"}
_BLOCK_OPEN = {"function", "if", "do", "repeat"}
_BLOCK_CLOSE = {"end", "until"}


class Tok:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind, self.value, self.pos = kind, value, pos

    def is_op(self, v):
        return self.kind == "op" and self.value == v


def _unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            d = s[i + 1]
            m = re.match(r"\d{1,3}", s[i + 1:])
            if m:
                out.append(chr(int(m.group()) & 0xFF))
                i += 1 + len(m.group())
                continue
            out.append(_ESC.get(d, d))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def tokenize(text):
    """Lua 5.1 tokens (comments dropped). Tolerant: text that is not valid
    Lua still tokenizes, it just yields odd tokens."""
    toks, i, n = [], 0, len(text)
    while i < n:
        m = _TOKEN.match(text, i)
        kind = m.lastgroup
        if kind == "ws":
            i = m.end()
        elif kind == "com":
            lm = _LONG_OPEN.match(text, i + 2)
            if lm:
                j = text.find("]" + lm.group(1) + "]", lm.end())
                i = n if j < 0 else j + len(lm.group(1)) + 2
            else:
                nl = _NEWLINE.search(text, i)
                i = nl.start() if nl else n
        elif kind == "long":
            close = "]" + m.group()[1:-1] + "]"
            j = text.find(close, m.end())
            end = n if j < 0 else j
            body = text[m.end():end]
            if body.startswith(("\r\n", "\n\r")):
                body = body[2:]
            elif body.startswith(("\n", "\r")):
                body = body[1:]
            toks.append(Tok("str", body, i))
            i = n if j < 0 else j + len(close)
        elif kind == "str":
            q, j = m.group(), i + 1
            while j < n and text[j] != q and text[j] not in "\r\n":
                j += 2 if text[j] == "\\" else 1
            toks.append(Tok("str", _unescape(text[i + 1:j]), i))
            i = j + 1
        elif kind == "name":
            v = m.group()
            toks.append(Tok("kw" if v in KEYWORDS else "name", v, i))
            i = m.end()
        elif kind == "num":
            v = m.group()
            try:
                num = int(v, 16) if v[:2] in ("0x", "0X") else float(v)
            except ValueError:
                num = None
            if isinstance(num, float) and num.is_integer() and abs(num) < 2**53:
                num = int(num)
            toks.append(Tok("num", num, i))
            i = m.end()
        else:
            toks.append(Tok("op", m.group(), i))
            i = m.end()
    return toks


# ------------------------------------------------------------------ parser
class Field:
    __slots__ = ("key", "pos", "type", "value", "table")

    def __init__(self, key, pos, vtype, value, table=None):
        self.key, self.pos, self.type = key, pos, vtype
        self.value, self.table = value, table


def _fold(toks):
    """Value of a constant arithmetic expression, or None."""
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def atom():
        nonlocal pos
        t = peek()
        if t is None:
            raise ValueError
        if t.is_op("-"):
            pos += 1
            return -atom()
        if t.is_op("("):
            pos += 1
            v = expr()
            if not (peek() and peek().is_op(")")):
                raise ValueError
            pos += 1
            return v
        if t.kind == "num" and t.value is not None:
            pos += 1
            return t.value
        raise ValueError

    def power():
        nonlocal pos
        v = atom()
        if peek() and peek().is_op("^"):
            pos += 1
            v = v ** power()
        return v

    def term():
        nonlocal pos
        v = power()
        while peek() and peek().kind == "op" and peek().value in "*/%":
            op = peek().value
            pos += 1
            r = power()
            v = v * r if op == "*" else v / r if op == "/" else v % r
        return v

    def expr():
        nonlocal pos
        v = term()
        while peek() and peek().kind == "op" and peek().value in "+-":
            op = peek().value
            pos += 1
            r = term()
            v = v + r if op == "+" else v - r
        return v

    try:
        v = expr()
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if pos != len(toks):
        return None
    if isinstance(v, float) and v.is_integer() and abs(v) < 2**53:
        v = int(v)
    return v


def classify(toks):
    """(type, value) of a table field's value tokens."""
    if not toks:
        return "expr", None
    t0 = toks[0]
    if len(toks) == 1:
        if t0.kind == "num":
            return "number", t0.value
        if t0.kind == "str":
            return "string", t0.value
        if t0.kind == "kw" and t0.value in ("true", "false"):
            return "boolean", t0.value == "true"
        if t0.kind == "kw" and t0.value == "nil":
            return "nil", None
    if t0.kind == "kw" and t0.value == "function":
        return "function", None
    # HASH("name") is expanded to the name's hash before the game sees it
    if (len(toks) == 4 and t0.kind == "name" and t0.value == "HASH"
            and toks[1].is_op("(") and toks[2].kind == "str"
            and toks[3].is_op(")")):
        import nb_names
        return "number", nb_names.crc(toks[2].value)
    if all(t.kind == "name" if k % 2 == 0 else t.is_op(".")
           for k, t in enumerate(toks)) and len(toks) % 2:
        return "name", "".join(t.value for t in toks)
    if all(t.kind == "num" or (t.kind == "op" and t.value in "+-*/%^()")
           for t in toks):
        v = _fold(toks)
        if v is not None:
            return "number", v
    return "expr", None


def _skip_expr(toks, i, stops):
    """Index of the first depth-0 token at/after i whose op value is in
    `stops`, counting brackets and function/if/do/repeat blocks."""
    depth = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.kind == "op":
            if t.value in "([{":
                depth += 1
            elif t.value in ")]}":
                if depth == 0:
                    return i
                depth -= 1
            elif depth == 0 and t.value in stops:
                return i
        elif t.kind == "kw":
            if t.value in _BLOCK_OPEN:
                depth += 1
            elif t.value in _BLOCK_CLOSE:
                depth -= 1
        i += 1
    return n


def parse_table(toks, i):
    """Parse the constructor whose `{` is toks[i] -> (fields, index past `}`)."""
    fields = []
    i += 1
    n = len(toks)
    positional = 0
    while i < n and not toks[i].is_op("}"):
        t = toks[i]
        if t.is_op(";") or t.is_op(","):
            i += 1
            continue
        key_pos = t.pos
        if t.is_op("["):
            j = _skip_expr(toks, i + 1, "")
            ktoks = toks[i + 1:j]
            key = (ktoks[0].value if len(ktoks) == 1 and ktoks[0].kind == "str"
                   else "[]")
            i = j + 1
            if i < n and toks[i].is_op("="):
                i += 1
        elif (t.kind == "name" and i + 1 < n and toks[i + 1].is_op("=")):
            key = t.value
            i += 2
        else:
            positional += 1
            key = "#"
        if i < n and toks[i].is_op("{"):
            sub, j = parse_table(toks, i)
            if j >= n or (toks[j].kind == "op" and toks[j].value in (",", ";", "}")):
                fields.append(Field(key, key_pos, "table", None, sub))
                i = j
                continue
        j = _skip_expr(toks, i, ",;")
        vtype, value = classify(toks[i:j])
        fields.append(Field(key, key_pos, vtype, value))
        i = j
    return fields, i + 1


def _chain(toks, j):
    """Dotted name (a.b:c -> "a.b.c") ending at toks[j], or ""."""
    parts = []
    while j >= 0 and toks[j].kind == "name":
        parts.append(toks[j].value)
        if j >= 1 and (toks[j - 1].is_op(".") or toks[j - 1].is_op(":")):
            j -= 2
            continue
        break
    return ".".join(reversed(parts))


def _root_of(toks, i):
    """Name for the constructor at toks[i], from what it is assigned or
    passed to: `a.b = {` -> "a.b", `f(x, {` -> "f()", `return {` -> "return"."""
    if i == 0:
        return None
    p = toks[i - 1]
    if p.is_op("="):
        return _chain(toks, i - 2) or None
    if p.is_op("(") or p.is_op(","):
        depth, j = 0, i - 1
        while j >= 0:
            t = toks[j]
            if t.kind == "op" and t.value in ")]}":
                depth += 1
            elif t.kind == "op" and t.value in "([{":
                if depth == 0:
                    break
                depth -= 1
            j -= 1
        name = _chain(toks, j - 1) if j >= 1 and toks[j].is_op("(") else ""
        return name + "()" if name else None
    if p.kind == "kw" and p.value == "return":
        return "return"
    return None


def data_tables(text):
    """[(root name, fields)] for every table constructor in the source that
    is assigned to a name, passed to a call, or returned."""
    toks = tokenize(text)
    out, i, n = [], 0, len(toks)
    while i < n:
        if toks[i].is_op("{"):
            root = _root_of(toks, i)
            fields, j = parse_table(toks, i)
            if root:
                out.append((root, fields))
            i = j
        else:
            i += 1
    return out


# ------------------------------------------------------------------ schema
def _new_acc():
    return {"tables": {}, "fields": {}}


def _note_value(f, vtype, value):
    f["n"] += 1
    f["types"][vtype] = f["types"].get(vtype, 0) + 1
    if vtype == "number" and value is not None:
        f["min"] = value if f["min"] is None else min(f["min"], value)
        f["max"] = value if f["max"] is None else max(f["max"], value)
    if vtype in ("number", "string", "boolean", "name"):
        vals = f["values"]
        if vals is not None and value not in vals:
            vals.append(value)
            if len(vals) > MAX_VALUES:
                f["values"] = None


def observe(text, acc=None):
    """Accumulate the key/type/range observations of one script's tables."""
    acc = acc if acc is not None else _new_acc()

    def walk(path, fields):
        t = acc["tables"].setdefault(path, {"n": 0, "keys": {}})
        t["n"] += 1
        for fd in fields:
            t["keys"][fd.key] = t["keys"].get(fd.key, 0) + 1
            fp = path + "/" + fd.key
            f = acc["fields"].setdefault(
                fp, {"n": 0, "types": {}, "min": None, "max": None,
                     "values": []})
            _note_value(f, fd.type, fd.value)
            if fd.table is not None:
                walk(fp, fd.table)

    for root, fields in data_tables(text):
        walk(root, fields)
    return acc


def _units(pip):
    """.lu files in a folder, or the given list of .lu files."""
    if isinstance(pip, (str, Path)):
        p = Path(pip)
        return sorted(p.rglob("*.lu")) if p.is_dir() else [p]
    return [Path(x) for x in pip]


def pip_sources(pip, skipped=None):
    """Every distinct plaintext script source in a folder (or list) of PiP
    units, as (unit name, text). Units that cannot be read are skipped and
    their names appended to `skipped`."""
    import pip_scripts
    from naughty_lu import LuFile
    seen = set()
    for f in _units(pip):
        try:
            lu = LuFile(str(f))
            if "LUH" not in getattr(lu, "platform", ""):
                continue
            srcs = [pip_scripts.parse_script_chunk(c)["src"]
                    for _, c in pip_scripts._iter_script_chunks(lu)]
        except Exception:
            if skipped is not None:
                skipped.append(f.name)
            continue
        finally:
            lu = None
        for src in srcs:
            h = hashlib.sha1(src).digest()
            if h in seen:
                continue
            seen.add(h)
            yield f.name, src.decode("latin-1")


def build(pip, progress=None):
    """Schema dict built from every script in a folder (or list) of retail
    PiP units. A full retail folder takes a few minutes, almost all of it
    decompressing the units."""
    acc = _new_acc()
    n = 0
    skipped = []
    for unit, text in pip_sources(pip, skipped):
        observe(text, acc)
        n += 1
        if progress:
            progress(unit, n)
    source = str(Path(pip)) if isinstance(pip, (str, Path)) else "files"
    return {"version": SCHEMA_VERSION, "source": source,
            "built": time.strftime("%Y-%m-%d %H:%M:%S"), "scripts": n,
            "skipped": skipped, **acc}


def default_cache():
    """Where the built schema is kept: outside the repo, per user."""
    base = os.environ.get("SEAMRIPPER_CACHE")
    if not base:
        base = (Path(os.environ["LOCALAPPDATA"]) / "SeamRipper"
                if os.environ.get("LOCALAPPDATA")
                else Path.home() / ".cache" / "seamripper")
    return Path(base) / "pip_schema.json"


def save(schema, path=None):
    path = Path(path or default_cache())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(schema, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return path


def load_schema(pip_folder=None, path=None):
    """The cached schema; built from `pip_folder` and cached if there is no
    usable cache yet. None when there is neither a cache nor a folder."""
    path = Path(path or default_cache())
    if path.exists():
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            if schema.get("version") == SCHEMA_VERSION:
                return schema
        except (OSError, ValueError):
            pass
    if pip_folder:
        schema = build(pip_folder)
        save(schema, path)
        return schema
    return None


# ------------------------------------------------------------------ check
def _merged(schema, own, kind, path):
    a = (schema or {}).get(kind, {}).get(path)
    b = own[kind].get(path)
    return [x for x in (a, b) if x]


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _fields(text):
    """[(table path, Field)] for every field of every data table."""
    out = []

    def walk(path, fields):
        for fd in fields:
            out.append((path, fd))
            if fd.table is not None:
                walk(path + "/" + fd.key, fd.table)

    for root, fields in data_tables(text):
        walk(root, fields)
    return out


def _sig(path, fd):
    return (path, fd.key, fd.type,
            fd.value if not isinstance(fd.value, float) else repr(fd.value))


def check(original_text, edited_text, schema=None):
    """Warnings (never refusals) for data-table fields the edit added or
    changed that leave the shape retail uses: a key the table never has, a
    value of a different type, a number far outside the retail range, or a
    value outside a small fixed set. Each warning is a dict:
        {"line", "col", "kind", "path", "key", "value", "message"}
    kind is one of new_key, type, range, value. Positions are 1-based in the
    edited text. `schema` is a loaded schema (load_schema()); with None, the
    original script's own tables are the only reference.
    """
    own = observe(original_text)
    before = {}
    for path, fd in _fields(original_text):
        s = _sig(path, fd)
        before[s] = before.get(s, 0) + 1

    starts = [0] + [m.end() for m in _NEWLINE.finditer(edited_text)]
    warnings = []

    def warn(fd, kind, path, message):
        ln = bisect.bisect_right(starts, fd.pos)
        warnings.append({"line": ln, "col": fd.pos - starts[ln - 1] + 1,
                         "kind": kind, "path": path, "key": fd.key,
                         "value": fd.value if kind != "new_key" else None,
                         "message": f"line {ln}: {message}"})

    for path, fd in _fields(edited_text):
        s = _sig(path, fd)
        if before.get(s):
            before[s] -= 1          # unchanged from the original
            continue
        tables = _merged(schema, own, "tables", path)
        if not tables:
            continue                # a table retail does not have
        known = set().union(*(t["keys"] for t in tables))
        where = _where(path)
        if fd.key not in known:
            shown = sorted(k for k in known if k not in ("[]", "#"))
            what = {"[]": "a [bracketed] key", "#": "a list item"}.get(
                fd.key, f"the key '{fd.key}'")
            warn(fd, "new_key", path,
                 f"{what} is never used in {where} in the retail scripts"
                 + (f" (it uses: {', '.join(shown[:15])}"
                    f"{', ...' if len(shown) > 15 else ''})" if shown else "")
                 + ". Unknown keys in game data tables can hang the loader.")
            continue
        stats = _merged(schema, own, "fields", path + "/" + fd.key)
        types = set().union(*(f["types"] for f in stats))
        if fd.type not in types:
            warn(fd, "type", path,
                 f"'{fd.key}' in {where} is a {fd.type} here but always a "
                 f"{' or '.join(sorted(types))} in the retail scripts")
            continue
        if fd.type == "number" and fd.value is not None:
            nums = [f for f in stats if f["min"] is not None]
            if sum(f["n"] for f in nums) < MIN_SEEN:
                continue            # too few retail examples to judge by
            lo = min(f["min"] for f in nums)
            hi = max(f["max"] for f in nums)
            if max(abs(lo), abs(hi)) >= HASH_FLOOR:
                continue            # an ID/hash field: no meaningful range
            reach = max(abs(lo), abs(hi), 1)
            v = fd.value
            rng = f"{_fmt(lo)}..{_fmt(hi)}"
            if v > hi + reach or v < lo - reach:
                warn(fd, "range", path,
                     f"'{fd.key}' = {_fmt(v)} is far outside the retail range "
                     f"for {where} ({rng}). Values far past what the game "
                     f"ships with can hang it (costume hp 400 works, 30000 "
                     f"hangs).")
            elif v < 0 <= lo:
                warn(fd, "range", path,
                     f"'{fd.key}' = {_fmt(v)} is negative, but the retail "
                     f"scripts never use a negative value in {where} ({rng})")
            continue
        if fd.type in ("string", "name", "boolean"):
            sets = [f["values"] for f in stats]
            if any(v is None for v in sets):
                continue
            vals = [v for vs in sets for v in vs]
            n = sum(f["n"] for f in stats)
            distinct = set(map(_fmt, vals))
            if (_fmt(fd.value) not in distinct and n >= 2 * len(distinct)
                    and n >= MIN_SEEN):
                warn(fd, "value", path,
                     f"'{fd.key}' = {_fmt(fd.value)} is not one of the values "
                     f"the retail scripts use in {where}: "
                     f"{', '.join(sorted(distinct))}")
    return warnings


def _where(path):
    """A table path as a modder reads it: Outfits/[]/Bonus -> Outfits[..].Bonus"""
    out = ""
    for k, part in enumerate(path.split("/")):
        if k == 0:
            out = part
        elif part == "[]":
            out += "[..]"
        elif part == "#":
            out += "[n]"
        else:
            out += "." + part
    return out


# ------------------------------------------------------------------ CLI
def _read(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def cmd_build(a):
    out = Path(a.out) if a.out else default_cache()
    t = time.time()

    def progress(unit, n):
        if n % 25 == 0:
            print(f"  {n} scripts read (at {unit})", flush=True)

    schema = build(a.pip, progress)
    save(schema, out)
    if schema["skipped"]:
        print(f"  could not read {len(schema['skipped'])} unit(s): "
              f"{', '.join(schema['skipped'])}")
    print(f"schema: {schema['scripts']} scripts, {len(schema['tables'])} "
          f"table shapes, {len(schema['fields'])} fields "
          f"({time.time() - t:.0f}s) -> {out}")


def cmd_check(a):
    schema = load_schema(a.pip, a.schema)
    ws = check(_read(a.orig), _read(a.edited), schema)
    if a.json:
        print(json.dumps({"schema": str(Path(a.schema or default_cache()))
                          if schema else None, "warnings": ws}))
        return
    if schema is None:
        print("note: no retail schema cached yet (run `pip_schema.py build "
              "<pip folder>`); comparing against the original script only")
    for w in ws:
        print(f"warning: {w['message']}")
    print(f"{len(ws)} warning(s)" if ws else "no warnings")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("build", help="build the schema from retail PiP units")
    pb.add_argument("pip", help="folder of retail PiP .lu files")
    pb.add_argument("-o", "--out", help=f"where to write it (default: "
                    f"{default_cache()})")
    pb.set_defaults(func=cmd_build)
    pc = sub.add_parser("check", help="warn about data-table edits that "
                        "leave the retail shape")
    pc.add_argument("orig", help="the original .lua")
    pc.add_argument("edited", help="the edited .lua")
    pc.add_argument("--schema", help="schema file (default: the cache)")
    pc.add_argument("--pip", help="retail PiP folder, to build the schema if "
                    "it is not cached yet")
    pc.add_argument("--json", action="store_true",
                    help="print {\"schema\": path|null, \"warnings\": [...]}")
    pc.set_defaults(func=cmd_check)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
