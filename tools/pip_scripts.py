#!/usr/bin/env python3
"""Extract Panic in Paradise Lua scripts."""
import argparse
import re
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


_SQUEEZE_STEPS = [
    (re.compile(rb"[ \t]+\n"), b"\n"),          # trailing ws
    (re.compile(rb"\n\n\n+"), b"\n\n"),         # blank-run collapse
    (re.compile(rb"[ \t][ \t]+"), b" "),        # internal run -> 1
]


def _squeeze(src, budget):
    """squeeze_lua without the note; budget=-1 applies every step."""
    for rx, rep in _SQUEEZE_STEPS:
        if len(src) <= budget:
            break
        src = rx.sub(rep, src)
    return src


def pad_to_original(src, original_len):
    """Pad a script that came out SHORTER than the one it replaces back to the
    original length with trailing spaces. The engine lays the records of a
    container out by their sizes, so a script that shrinks moves every record
    after it and the game fails to load a level (verified on retail PiP: a
    squeezed script 59 to 1,760 bytes smaller hung Stage 1 at load; the same
    edits padded back to their exact original size loaded). Trailing
    whitespace is invisible to Lua. A script that grew into the padding after
    its slot is left as it is: its record still ends in the same slot."""
    if len(src) < original_len:
        src = src + b" " * (original_len - len(src))
    return src


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
    before = len(src)
    src = _squeeze(src, budget)
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


_SPECIAL = re.compile(r"[-\[\]\"'(){}\r\n]")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_NEWLINE = re.compile(r"\r\n|\r|\n")
_CLOSER_OF = {"(": ")", "[": "]", "{": "}"}
_OPENER_OF = {")": "(", "]": "[", "}": "{"}


def lua_structure_problems(src):
    """A dependency-free structure check for edited Lua 5.1 source. NOT a
    parser: it flags only high-confidence breakage (unbalanced brackets,
    unterminated strings and long strings/comments) while skipping strings,
    long brackets of any level and both comment forms, and has zero false
    positives across the retail PiP script corpus.

    Returns a list of dicts, one per problem, in file order:
        {"line": int, "col": int, "kind": str, "message": str}
    `line`/`col` are 1-based, counted in characters, with CRLF, CR and LF all
    ending a line, so they match what an editor shows for the same text. For
    a bracket that is never closed, or a closer with nothing to close, the
    bracket itself is reported, except for an unclosed bracket whose missing
    closer the indentation points at (a later `}` that lines up with an outer
    line instead of its own `{`): then that inner `{` is reported and the
    unclosed bracket's own position is kept in "bracket_line"/"bracket_col".
    kind is one of: unclosed, extra, mismatched, string, long_string,
    long_comment.

    It deliberately does NOT balance do/then/function/end blocks: keyword
    counting without a real parser false-positives on valid code, and a
    malformed block surfaces as a load-time Lua error the user can see rather
    than the silent hang unbalanced brackets and strings cause.
    """
    text = src.decode("latin-1") if isinstance(src, (bytes, bytearray)) else src
    n = len(text)
    line_starts = [0] + [m.end() for m in _NEWLINE.finditer(text)]

    def pos(i):
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:                      # last line start <= i
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= i:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, i - line_starts[lo] + 1

    def indent(i):
        ln, _ = pos(i)
        s = line_starts[ln - 1]
        j = s
        while j < n and text[j] in " \t":
            j += 1
        return text[s:j], j

    problems = []

    def report(i, kind, message, **extra):
        ln, col = pos(i)
        problems.append({"line": ln, "col": col, "kind": kind,
                         "message": f"line {ln}, col {col}: {message}", **extra})

    stack = []                  # (bracket, index)
    # Closers that start their line less indented than their opener's line.
    # Harmless on their own, but when a bracket is left unclosed the first
    # one of these after it is usually the closer meant for that bracket.
    outdented = []
    i = 0
    while True:
        m = _SPECIAL.search(text, i)
        if not m:
            break
        i = m.start()
        c = text[i]
        if c in "\r\n":
            i += 1
            continue
        if c == "-":
            if text.startswith("--", i):
                lm = _LONG_OPEN.match(text, i + 2)
                if lm:
                    close = "]" + lm.group(1) + "]"
                    j = text.find(close, lm.end())
                    if j < 0:
                        report(i, "long_comment",
                               f"--{lm.group()} comment is never closed "
                               f"(no matching {close})")
                        break
                    i = j + len(close)
                    continue
                m2 = _NEWLINE.search(text, i)
                i = n if not m2 else m2.start()
                continue
            i += 1
            continue
        if c == "[":
            lm = _LONG_OPEN.match(text, i)
            if lm:
                close = "]" + lm.group(1) + "]"
                j = text.find(close, lm.end())
                if j < 0:
                    report(i, "long_string",
                           f"{lm.group()} long string is never closed "
                           f"(no matching {close})")
                    break
                i = j + len(close)
                continue
        if c in "\"'":
            j = i + 1
            closed = False
            while j < n:
                d = text[j]
                if d == c:
                    closed = True
                    break
                if d == "\\":
                    # an escaped line break continues the string
                    j += 3 if text.startswith(("\r\n", "\n\r"), j + 1) else 2
                elif d in "\r\n":
                    break
                else:
                    j += 1
            if not closed:
                report(i, "string", f"string starting with {c} is never "
                       f"closed on its line")
            i = j + 1
            continue
        if c in "([{":
            stack.append((c, i))
        elif c in ")]}":
            want = _OPENER_OF[c]
            if stack and stack[-1][0] == want:
                o, oi = stack.pop()
                oind, _ = indent(oi)
                cind, first = indent(i)
                if (first == i and len(cind) < len(oind)
                        and pos(oi)[0] != pos(i)[0]):
                    outdented.append((oi, i))
            elif any(b == want for b, _ in stack):
                # closes an outer bracket: everything above it is unclosed
                while stack[-1][0] != want:
                    o, oi = stack.pop()
                    report(oi, "mismatched",
                           f"'{o}' is never closed (the '{c}' at line "
                           f"{pos(i)[0]}, col {pos(i)[1]} closes an outer "
                           f"'{want}' first)")
                stack.pop()
            else:
                report(i, "extra", f"'{c}' has no matching '{want}' before it")
        i += 1
    for o, oi in stack:
        hint = next((s for s in outdented
                     if s[0] > oi and text[s[0]] == o), None)
        ol, oc = pos(oi)
        if hint:
            report(hint[0], "unclosed",
                   f"'{o}' at line {ol}, col {oc} is never closed. The "
                   f"'{_CLOSER_OF[o]}' on line {pos(hint[1])[0]} does not line "
                   f"up with this line, so the missing "
                   f"'{_CLOSER_OF[o]}' probably belongs to the '{o}' here",
                   bracket_line=ol, bracket_col=oc)
        else:
            report(oi, "unclosed", f"'{o}' is never closed")
    problems.sort(key=lambda p: (p["line"], p["col"]))
    return problems


def lua_sanity_check(src):
    """lua_structure_problems as plain messages (empty list == looks OK)."""
    return [p["message"] for p in lua_structure_problems(src)]


def match_script(chunks, edited_path):
    """Record index whose embedded path shares the longest trailing run of
    path components with `edited_path`, or None. `chunks` maps record index
    to parse_script_chunk parts."""
    etoks = norm_path(edited_path).split("/")
    best, best_n = None, 0
    for idx, parts in chunks.items():
        ctoks = norm_path(parts["path"].decode("ascii", "replace")).split("/")
        n = 0
        while (n < len(etoks) and n < len(ctoks)
               and etoks[-1 - n] == ctoks[-1 - n]):
            n += 1
        if n > best_n:
            best, best_n = idx, n
    return best


def slot_limits(lu, index, parts):
    """(slot bytes, source bytes the slot allows) for one script record. The
    slot is the chunk's size plus the padding up to the next chunk."""
    rec = next(r for r in lu.records if r.index == index)
    ordered = sorted((r for r in lu.records if not r.external),
                     key=lambda r: r.offset)
    pos = [r.index for r in ordered].index(index)
    slot = ((ordered[pos + 1].offset if pos + 1 < len(ordered)
             else lu.image_size) - rec.offset)
    return slot, slot - len(build_script_chunk({**parts, "src": b""}))


def expand_hashes(text):
    """HASH("name") -> decimal hash, the way PiP's own scripts spell them.
    The game compiles this source itself and has no HASH function."""
    if "HASH" not in text:
        return text, []
    import nb_names
    return nb_names.expand_hash_calls(text, fmt="{:d}")


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
        best = match_script(chunks, ep)
        if best is None:
            sys.exit(f"inject: no chunk in {args.orig} matches {edited}")
        # HASH("name") -> decimal, then UTF-8 on disk -> the container's own
        # encoding, keeping this chunk's line-ending convention
        text, expanded = expand_hashes(read_edited(ep))
        for name, value in expanded:
            print(f'  HASH("{name}") -> {value}')
        try:
            src = encode_text(text, chunks[best]["src"])
        except SourceEncodingError as e:
            sys.exit(f"{ep.name}: {e}")
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
        _, budget = slot_limits(lu, best, parts)
        if len(src) > budget:
            src = squeeze_lua(src, budget)
        if len(src) > budget:
            sys.exit(f"inject: {ep.name} is {len(src) - budget} bytes too "
                     f"large for its slot even after squeezing "
                     f"(slot allows {budget} source bytes); trim the script")
        src = pad_to_original(src, old_len)
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


# PiP stores script source as single-byte text, which extract_lua decodes as
# latin-1. The .lua files written to disk are UTF-8, because that is what text
# editors expect. Those two must be converted back at the container boundary
# or the round trip is not byte-exact: an accented byte like 0xE8 becomes the
# two bytes 0xC3 0xA8 in UTF-8, which grows the script and writes mojibake
# into the container. Real retail scripts do carry these - levelcommon's
# libraryloading and naughtyisland_npcs both have French developer comments
# ("systeme", "SUPPRIME!") with accented characters.
SOURCE_ENCODING = "latin-1"


def write_source(dest, text):
    """Write extracted Lua source to disk for editing (UTF-8, LF endings)."""
    Path(dest).write_text(text, encoding="utf-8", errors="replace", newline="\n")


def line_ending_of(original):
    """The line-ending convention a chunk's existing source uses.

    PiP is not consistent about this, and uses all three within a single
    container. In levelcommon.lu alone:
        LF    most scripts
        CRLF  objecttypes, rendergroups, surfacetype, vibbadge
        CR    libraryinput, libraryphysic  (classic Mac, no LF at all)
    Flattening everything to LF - which is what this module used to do -
    rewrote every script that was not already LF, so an edit that changed
    nothing still changed the stored bytes. A file with mixed endings cannot
    be reproduced exactly by any single choice, so it normalises to LF.
    """
    if not original:
        return "\n"
    cr, lf = original.count(b"\r"), original.count(b"\n")
    crlf = original.count(b"\r\n")
    if crlf and cr == crlf and lf == crlf:
        return "\r\n"
    if cr and lf == 0:
        return "\r"
    return "\n"


class SourceEncodingError(ValueError):
    """Edited text holds a character the container's encoding cannot store."""

    def __init__(self, line, char):
        self.line, self.char = line, char
        super().__init__(
            f"line {line} contains {char!r}, which cannot be stored in this "
            f"container's {SOURCE_ENCODING} script encoding. Replace it with "
            f"a plain ASCII equivalent (a typographic dash or quote pasted "
            f"from a word processor is the usual cause).")


def read_edited(path):
    """Text of an edited .lua as the injector sees it (UTF-8, else latin-1)."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(SOURCE_ENCODING)      # already container-encoded


def encode_text(text, original=b""):
    """Edited source text -> the bytes to store in the chunk.

    `original` is the source currently in the chunk, used only to preserve
    its line-ending convention (see line_ending_of). Raises
    SourceEncodingError for characters latin-1 cannot hold.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):          # editors that add a BOM
        text = text[1:]
    eol = line_ending_of(original)
    if eol != "\n":
        text = text.replace("\n", eol)
    try:
        return text.encode(SOURCE_ENCODING)
    except UnicodeEncodeError as e:
        raise SourceEncodingError(text[:e.start].count(eol) + 1,
                                  text[e.start:e.end]) from None


def encode_source(path, original=b""):
    """Read an edited .lua back and return the bytes to store in the chunk
    (see encode_text); exits with a modder-facing message on bad characters.
    """
    try:
        return encode_text(read_edited(path), original)
    except SourceEncodingError as e:
        sys.exit(f"{Path(path).name}: {e}")


_SLOT_CACHE = {}        # resolved container path -> (stat key, slots)


def container_slots(container_path):
    """Every script record of a PiP container, parsed once and cached until
    the file changes: {record index: {"path": str, "src": bytes,
    "slot": int, "limit": int}}. The first call per container decodes it
    (a few seconds on the biggest units); later calls are dictionary hits."""
    from naughty_lu import LuFile
    p = Path(container_path).resolve()
    st = p.stat()
    key = (st.st_size, st.st_mtime_ns)
    hit = _SLOT_CACHE.get(p)
    if hit and hit[0] == key:
        return hit[1]
    lu = LuFile(str(p))
    slots = {}
    for r in lu.records:
        if r.type != SCRIPT_TYPE or r.external:
            continue
        parts = parse_script_chunk(bytes(lu.chunk(r)))
        slot, limit = slot_limits(lu, r.index, parts)
        slots[r.index] = {
            "path": parts["path"].split(b"\x00")[0].decode("ascii", "replace"),
            "src": parts["src"], "slot": slot, "limit": limit,
            "_parts": {"path": parts["path"]}}
    _SLOT_CACHE[p] = (key, slots)
    return slots


def resolve_script(slots, script_id):
    """Record index for script_id: a record index (int or digits), or a
    script name / path matched the way `inject` matches edited files."""
    if isinstance(script_id, int) or str(script_id).isdigit():
        idx = int(script_id)
        if idx not in slots:
            raise KeyError(f"record {idx} is not a script in this container")
        return idx
    name = str(script_id)
    if not name.lower().endswith(".lua"):
        name += ".lua"
    best = match_script({i: s["_parts"] for i, s in slots.items()}, name)
    if best is None:
        raise KeyError(f"no script in this container matches {script_id!r}")
    return best


def budget(container_path, script_id, edited_text, check=False):
    """How an edited script stands against its slot, exactly as `inject`
    (and lu_lua.py ship) will judge it. Cheap after the first call per
    container. Returns a dict:

      record, path        which script record the edit targets
      original_size       source bytes in the retail chunk
      slot_size           chunk bytes the slot spans (size + padding)
      limit               most source bytes the slot can hold
      edited_size         source bytes after HASH() expansion, line-ending
                          and latin-1 conversion (None on encoding_error)
      reclaimable         whitespace bytes the injector may squeeze out
      bytes_left          limit - edited_size (negative = over, before
                          squeezing)
      bytes_left_squeezed limit - squeezed size
      fits                inject accepts the size (squeezing if needed)
      needs_squeeze       fits only because whitespace will be squeezed
      hashes              [[name, value], ...] HASH() calls expanded
      encoding_error      None, or {"line", "char", "message"}
      problems            (check=True only) lua_structure_problems of the
                          edited text, positions in the edited file's own
                          numbering
    """
    slots = container_slots(container_path)
    idx = resolve_script(slots, script_id)
    s = slots[idx]
    if isinstance(edited_text, (bytes, bytearray)):
        try:
            edited_text = bytes(edited_text).decode("utf-8")
        except UnicodeDecodeError:
            edited_text = bytes(edited_text).decode(SOURCE_ENCODING)
    text, expanded = expand_hashes(edited_text)
    out = {"record": idx, "path": s["path"], "original_size": len(s["src"]),
           "slot_size": s["slot"], "limit": s["limit"], "edited_size": None,
           "reclaimable": 0, "bytes_left": None, "bytes_left_squeezed": None,
           "fits": False, "needs_squeeze": False,
           "hashes": [[n, v] for n, v in expanded], "encoding_error": None}
    try:
        src = encode_text(text, s["src"])
    except SourceEncodingError as e:
        out["encoding_error"] = {"line": e.line, "char": e.char,
                                 "message": str(e)}
    else:
        small = len(_squeeze(src, s["limit"]))     # what inject writes
        out.update(edited_size=len(src),
                   reclaimable=len(src) - len(_squeeze(src, -1)),
                   bytes_left=s["limit"] - len(src),
                   bytes_left_squeezed=s["limit"] - small,
                   fits=small <= s["limit"],
                   needs_squeeze=len(src) > s["limit"] >= small)
    if check:
        out["problems"] = lua_structure_problems(edited_text)
    return out


def cmd_budget(args):
    import json
    try:
        b = budget(args.orig, args.index if args.index is not None
                   else str(args.edited), read_edited(args.edited),
                   check=True)
    except KeyError as e:
        sys.exit(f"budget: {e.args[0]}; pass --index to name the record "
                 f"(see `lu_lua.py list`)")
    if args.json:
        print(json.dumps(b))
        return
    print(f"{b['path']} (record {b['record']})")
    print(f"  original {b['original_size']:,} bytes, slot holds up to "
          f"{b['limit']:,} source bytes ({b['slot_size']:,}-byte chunk slot)")
    for name, value in b["hashes"]:
        print(f'  HASH("{name}") -> {value}')
    if b["encoding_error"]:
        print(f"  cannot store: {b['encoding_error']['message']}")
    elif b["bytes_left"] >= 0:
        print(f"  edited {b['edited_size']:,} bytes: {b['bytes_left']:,} "
              f"bytes left")
    elif b["fits"]:
        print(f"  edited {b['edited_size']:,} bytes: {-b['bytes_left']:,} over, "
              f"but fits after squeezing whitespace "
              f"({b['bytes_left_squeezed']:,} bytes left then)")
    else:
        print(f"  edited {b['edited_size']:,} bytes: too large by "
              f"{-b['bytes_left_squeezed']:,} bytes even after squeezing "
              f"{b['reclaimable']:,} bytes of whitespace")
    for p in b["problems"]:
        print(f"  structure: {p['message']}")
    if not b["fits"] or b["problems"]:
        sys.exit(1)


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
            write_source(dest, src)
            n += 1
    print(f"extracted {n} Lua source files "
          f"({dupe} duplicate copies skipped, {empty} empty chunks)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
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

    pb = sub.add_parser("budget", help="how many bytes an edited script has "
                        "left in its slot, and whether inject will accept it")
    pb.add_argument("orig", help="original PiP .lu container")
    pb.add_argument("edited", help="edited .lua file")
    pb.add_argument("--index", type=int,
                    help="script record to measure against (default: match "
                         "the edited file's path, as inject does)")
    pb.add_argument("--json", action="store_true",
                    help="print the result as one JSON object")
    pb.set_defaults(func=cmd_budget)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
