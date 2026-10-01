#!/usr/bin/env python3
"""Read and edit the Lua inside a .lu (NB1 or PiP)."""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from naughty_lu import LuFile

SCRIPT_TYPE = 0x04B00000
NAME_RE = re.compile(rb"z:\\[\x20-\x7e]+?\.lua")

NB1, PIP = "nb1", "pip"


# ------------------------------------------------------------------ container
def game_of(lu):
    """Which game's storage scheme this container uses."""
    return PIP if "LUH" in getattr(lu, "platform", "") else NB1


class Script:
    __slots__ = ("index", "name", "path", "size", "hash", "compiled")

    def __init__(self, index, name, path, size, hsh, compiled):
        self.index, self.name, self.path = index, name, path
        self.size, self.hash, self.compiled = size, hsh, compiled


def scripts(lu):
    """Every editable Lua script in the container, in record order.

    NB1 marks its script records with the same 0x04B00000 type PiP uses, but
    some NB1 scripts are stored as a descriptor record plus a body record
    sharing one hash, and only the body carries the `\x1bLua` image. Both are
    reported by type, so prefer the record that actually holds the code.
    """
    out = []
    seen_hash = {}
    for r in lu.records:
        if getattr(r, "external", False):
            continue
        try:
            chunk = bytes(lu.chunk(r))
        except Exception:
            continue
        is_script = (r.type == SCRIPT_TYPE) or (b"\x1bLua" in chunk)
        if not is_script:
            continue
        m = NAME_RE.search(chunk)
        path = m.group().decode("latin-1") if m else ""
        if not path:
            path = _pip_path(chunk) or ""
        name = path.replace("\\", "/").rstrip("\x00").split("/")[-1]
        if name.endswith(".lua"):
            name = name[:-4]
        compiled = b"\x1bLua" in chunk
        s = Script(r.index, name or f"{r.hash:08x}", path, r.size, r.hash,
                   compiled)
        # descriptor + body pairs: keep whichever record has the code
        prev = seen_hash.get(r.hash)
        if prev is not None and not prev.compiled and compiled:
            out[out.index(prev)] = s
            seen_hash[r.hash] = s
            continue
        if prev is not None and prev.compiled:
            continue
        seen_hash[r.hash] = s
        out.append(s)
    return out


# Reading and writing PiP script text is not a plain byte copy: the source is
# single-byte (latin-1) inside the container but UTF-8 on disk, and different
# scripts use different line endings. pip_scripts owns that conversion so the
# PiP tab's own extract/inject and this tool cannot drift apart.
def _encode_source(path, original=b""):
    import pip_scripts
    return pip_scripts.encode_source(path, original)


def _pip_path(c):
    if len(c) < 0x28:
        return None
    try:
        po, pl = struct.unpack_from(">2I", c, 0x10)
        if 0 < po < len(c) and 0 < pl <= len(c) - po:
            return c[po:po + pl].split(b"\x00")[0].decode("ascii", "replace")
    except Exception:
        pass
    return None


def resolve(lu, name, index):
    """Pick exactly one script, or exit explaining why it could not."""
    all_s = scripts(lu)
    if index is not None:
        for s in all_s:
            if s.index == index:
                return s
        sys.exit(f"no script record at index {index}; run `lu_lua.py list`")
    if not name:
        sys.exit("give a script name, or --index. Run `lu_lua.py list`.")
    exact = [s for s in all_s if s.name == name]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        sys.exit(f"'{name}' matches {len(exact)} records "
                 f"({', '.join(str(s.index) for s in exact)}); "
                 f"pass --index to say which one")
    near = [s for s in all_s if name.lower() in s.name.lower()]
    if len(near) == 1:
        return near[0]
    if near:
        sys.exit(f"'{name}' is ambiguous, it matches: "
                 + ", ".join(f"{s.name}(#{s.index})" for s in near)
                 + ". Use the exact name or --index.")
    sys.exit(f"no script named '{name}'; run `lu_lua.py list`")


# ---------------------------------------------------------------- subcommands
def cmd_list(a):
    lu = LuFile(a.lu)
    game = game_of(lu)
    ss = scripts(lu)
    label = "Naughty Bear (x36, compiled bytecode)" if game == NB1 \
        else "Panic in Paradise (LUH, plaintext source)"
    if not ss:
        print(f"{Path(a.lu).name}: {label}\nno Lua scripts in this container")
        return
    print(f"{Path(a.lu).name}: {label}")
    print(f"{len(ss)} script(s)\n")
    print(f"  {'index':>6}  {'name':<40} {'size':>8}  {'form':<9} hash")
    for s in sorted(ss, key=lambda x: x.name or "zzz"):
        form = "bytecode" if s.compiled else "source"
        print(f"  {s.index:>6}  {s.name or '(unnamed)':<40} {s.size:>8}  "
              f"{form:<9} {s.hash:#010x}")


def cmd_read(a):
    lu = LuFile(a.lu)
    game = game_of(lu)
    s = resolve(lu, a.name, a.index)

    if game == PIP or not s.compiled:
        import pip_scripts
        chunk = bytes(lu.chunk(lu.records[s.index]))
        got = pip_scripts.extract_lua(chunk)
        if not got:
            sys.exit(f"record {s.index} is not a readable plaintext script")
        rel, src = got
        # Written as UTF-8 with explicit \n, because that is what editors and
        # the GUI expect; `ship` converts back to the container's own
        # SOURCE_ENCODING. Writing with the platform default newline instead
        # would put CRLF in the file, which ship would then have to undo.
        Path(a.out).write_text(src, encoding="utf-8", newline="\n")
        print(f"wrote {a.out}  ({len(src):,} chars, plaintext source)")
        print(f"  source path: {rel}")
        print("  edit freely, then `lu_lua.py ship`. Edits must fit the "
              "original slot; whitespace and comments are squeezed "
              "automatically if needed.")
        return

    # NB1: hand off to the decompile pipeline, addressing by hash so the
    # name never has to be re-resolved against raw bytes.
    import nblua
    ns = argparse.Namespace(lu=a.lu, name=None, hash=f"{s.hash:#010x}",
                            out=a.out, luadec=False, backend=a.backend,
                            jar=a.jar, luac=a.luac)
    nblua.cmd_read(ns)


def script_payload(chunk, compiled):
    """The part of a script chunk an edit is made against: the Lua image for
    NB1 bytecode, the source text for PiP. Two copies of a script with equal
    payloads take the same edit, whatever their chunk headers say."""
    if compiled:
        i = chunk.find(b"\x1bLua")
        return chunk[i:i + struct.unpack_from(">I", chunk, 0x1c)[0]]
    import pip_scripts
    try:
        return pip_scripts.parse_script_chunk(chunk)["src"]
    except Exception:
        return chunk


def _digest(b):
    return hashlib.sha1(b).hexdigest()


# ---------------------------------------------------------------------- ship
class _Edit:
    """One script's edit, checked against the container it was read from."""

    def __init__(self, script, source, payload):
        self.script, self.source, self.payload = script, Path(source), payload
        self.info = {}          # report fields for this script
        self.new_image = None   # NB1: rebuilt Lua image, None if unchanged
        self.new_src = None     # PiP: container-encoded source before squeezing


def _ship_error(msg, **kw):
    import nblua
    return nblua.ShipError(msg, **kw)


def _collect_edits(a, lu):
    """[(Script, source path)] from `name/--index source` and --edit."""
    def pick(name, index):
        try:
            return resolve(lu, name, index)
        except SystemExit as e:
            raise _ship_error(str(e.code), file=a.lu, kind="usage")
    out = []
    if a.source:
        out.append((pick(a.name, a.index), Path(a.source)))
    for spec in a.edit or []:
        key, sep, f = spec.partition("=")
        if not sep or not key.strip() or not f.strip():
            raise _ship_error(f"--edit takes INDEX=file.lua (or NAME=file.lua), "
                              f"not {spec!r}", kind="usage")
        key = key.strip()
        s = pick(None, int(key)) if key.isdigit() else pick(key, None)
        out.append((s, Path(f.strip())))
    if not out:
        raise _ship_error("nothing to ship: give the edited .lua (with a name "
                          "or --index), or --edit INDEX=file.lua", kind="usage")
    seen = {}
    for s, f in out:
        if s.index in seen:
            raise _ship_error(f"record {s.index} ({s.name}) is edited twice "
                              f"({seen[s.index].name} and {f.name}); give each "
                              f"script once", kind="usage")
        seen[s.index] = f
        if not f.is_file():
            raise _ship_error(f"edited file not found: {f}", file=f,
                              kind="usage")
    return out


def _prepare_nb1(a, lu, s, source):
    import nblua
    if not s.compiled:
        raise _ship_error(f"record {s.index} is not a compiled script",
                          kind="usage")
    chunk = bytes(lu.chunk(lu.records[s.index]))
    e = _Edit(s, source, script_payload(chunk, True))
    luac = nblua.find_luac(a.luac)
    names = nblua.load_names(a)
    prefer = a.backend
    if getattr(a, "luadec", False) and prefer in (None, "auto"):
        prefer = "luadec"
    got = nblua.prepare_edit(chunk, source, luac, prefer=prefer,
                             luadec=bool(getattr(a, "luadec", False)),
                             jar=a.jar, names=names, force=a.force,
                             name=s.name)
    for w in got["warnings"]:
        print(f"  note: {w}")
    e.new_image = got.pop("new_image")
    got.pop("orig_image")
    e.info = {"index": s.index, **got}
    return e


def _pip_slot(lu, index):
    """Bytes the chunk at `index` may occupy without moving (its size plus the
    padding up to the next record)."""
    rec = lu.records[index]
    ordered = sorted((r for r in lu.records if not r.external),
                     key=lambda r: r.offset)
    pos = [r.index for r in ordered].index(index)
    return ((ordered[pos + 1].offset if pos + 1 < len(ordered)
             else lu.image_size) - rec.offset)


def _issue_line(issue):
    """(line, text) from one structure-check finding. Accepts plain strings
    ("... at line 12") and dicts/tuples carrying a line number."""
    if isinstance(issue, dict):
        return int(issue.get("line") or 0), str(issue.get("message") or issue)
    if isinstance(issue, tuple) and len(issue) == 2 and isinstance(issue[0], int):
        return issue[0], str(issue[1])
    m = re.search(r"\bline (\d+)", str(issue))
    return (int(m.group(1)) if m else 0), str(issue)


def _luac_parse(luac, src):
    """None if `src` (bytes) parses as Lua 5.1, else (line, message)."""
    import nblua
    import subprocess
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="srparse_"))
    p = d / "edit.lua"
    p.write_bytes(src)
    try:
        r = subprocess.run([luac, "-p", str(p)], capture_output=True,
                           text=True, errors="replace")
    except OSError:
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if r.returncode == 0:
        return None
    return nblua.luac_error_line(r.stderr or r.stdout)


def _lf(b):
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _prepare_pip(a, lu, s, source):
    """Check an edited PiP script. Line numbers in errors are lines of the
    modder's file: HASH() expansion keeps line breaks, and the checks run on
    LF text, whatever line endings the chunk itself uses."""
    import difflib
    import tempfile
    import nblua
    import pip_scripts
    chunk = bytes(lu.chunk(lu.records[s.index]))
    parts = pip_scripts.parse_script_chunk(chunk)
    e = _Edit(s, source, parts["src"])
    text = nblua.read_edit_text(source)
    unexpanded = text                       # the structure check reports lines/columns of this
    # HASH("name") -> the name's hash as a plain decimal number, the way PiP's
    # own scripts write hashes. The game compiles this source itself and has
    # no HASH function, so it must be gone before the script ships.
    text, expanded = nblua.expand_hash_keep_lines(text, fmt="{:d}")
    for name, value in expanded:
        print(f'  HASH("{name}") -> {value}')
    path = source
    if expanded:
        path = Path(tempfile.mkdtemp(prefix="pipship_")) / source.name
        path.write_bytes(text.encode("utf-8"))
    try:
        src = pip_scripts.encode_source(path, parts["src"])
    except SystemExit as ex:
        line, msg = _issue_line(str(ex.code))
        raise _ship_error(str(ex.code), file=source, line=line, kind="encoding")
    warnings = []

    try:
        luac = nblua.find_luac(a.luac)
    except SystemExit:
        luac = None
    # a real Lua parse, when the original script passes one: catches what the
    # bracket/string check cannot (a missing `end`, a stray symbol)
    if luac and _luac_parse(luac, _lf(parts["src"])) is None:
        bad = _luac_parse(luac, _lf(src))
        if bad:
            line, msg = bad
            full = f"{source.name} line {line}: {msg}"
            if not a.force:
                raise _ship_error(full + "\n  fix the script, or pass --force "
                                  "to ship it anyway.", file=source, line=line,
                                  kind="syntax")
            warnings.append(full + " (--force given: shipping anyway)")

    lf_text = _lf(unexpanded.encode("latin-1", "replace")).decode("latin-1")
    issues = pip_scripts.lua_structure_problems(lf_text)
    if issues:
        found = [_issue_line(i) for i in issues]
        line = next((ln for ln, _ in found if ln), 0)
        msg = (f"{source.name}: this script has Lua structure problems that "
               f"would likely hang the game:\n    - "
               + "\n    - ".join(t for _, t in found))
        if not a.force:
            raise _ship_error(msg + "\n  fix the script, or pass --force to "
                              "override.", file=source, line=line,
                              kind="structure")
        sys.stderr.write(msg + "\n  (--force given: shipping anyway)\n")
        warnings.append(msg)

    got = pip_scripts.extract_lua(chunk)
    before = (got[1] if got else "").splitlines()
    after = nblua.read_edit_text(source).splitlines()
    diff = "".join(ln + "\n" for ln in difflib.unified_diff(
        before, after, f"fresh read of {s.name}", source.name, lineterm="",
        n=2))
    e.new_src = src
    e.info = {"index": s.index, "name": s.name, "source": str(source),
              "hash_calls": [{"name": n, "value": str(v)} for n, v in expanded],
              "diff": diff, "warnings": warnings,
              "changed": src != parts["src"]}
    return e


def _pip_fit(lu, index, e):
    """(chunk bytes or None, budget dict) for one PiP edit in one container.
    Scripts must fit their original slot: chunks are referenced by absolute
    offset, so one that grows past its slot gets relocated and hangs the game
    at boot."""
    import io
    import pip_scripts
    parts = pip_scripts.parse_script_chunk(bytes(lu.chunk(lu.records[index])))
    slot = _pip_slot(lu, index)
    budget = slot - len(pip_scripts.build_script_chunk({**parts, "src": b""}))
    src = e.new_src
    info = {"record": index, "slot": slot, "budget": budget,
            "original": len(parts["src"]), "edited": len(src)}
    if len(src) > budget:
        note = io.StringIO()
        err, sys.stderr = sys.stderr, note
        try:
            src = pip_scripts.squeeze_lua(src, budget)
        finally:
            sys.stderr = err
        info["squeezed"] = len(src)
        if note.getvalue().strip():
            print(note.getvalue().rstrip())
    info["fits"] = len(src) <= budget
    info["spare"] = budget - len(src)
    if not info["fits"]:
        return None, info
    parts["src"] = src
    return pip_scripts.build_script_chunk(parts), info


def _budget_text(b):
    t = (f"slot allows {b['budget']:,} source bytes; original {b['original']:,}, "
         f"your edit {b['edited']:,}")
    if "squeezed" in b:
        t += f", {b['squeezed']:,} after squeezing whitespace"
    return t + (f" (fits, {b['spare']:,} to spare)" if b["fits"]
                else f" (TOO LARGE by {-b['spare']:,})")


def _matches_in(container, edits, primary, entries):
    """{edit: [record index]} for the edits this container can take, or
    raise _Refused when it carries a different version of one. `entries` are
    the container's scripts as container_index() lists them."""
    if primary:
        return {e: [e.script.index] for e in edits}
    have = {}
    for s in entries:
        have.setdefault(s["name"], []).append(s)
    plan, missing = {}, []
    for e in edits:
        cands = have.get(e.script.name, [])
        if not cands:
            missing.append(e.script.name)
            continue
        want = _digest(e.payload)
        same = [c["index"] for c in cands if c["compiled"] == e.script.compiled
                and c["digest"] == want]
        if len(same) != len(cands):
            other = next(c for c in cands if c["index"] not in same)
            raise _Refused(
                f"{container} carries a different version of {e.script.name} "
                f"(record {other['index']}); an edit made from the copy you "
                f"read would not match it. Read {e.script.name} from this "
                f"container and edit that copy to change it here.")
        plan[e] = same
    if not plan:
        raise _Refused(f"{container} does not carry " + ", ".join(missing))
    return plan


def _entries(lu):
    """container_index()-style script entries for an open container."""
    out = []
    for s in scripts(lu):
        chunk = bytes(lu.chunk(lu.records[s.index]))
        out.append({"index": s.index, "name": s.name, "compiled": s.compiled,
                    "digest": _digest(script_payload(chunk, s.compiled))})
    return out


class _Refused(Exception):
    pass


def _deliver(src_path, data, out, stage, verify, target):
    """Write one target: build next to `out`, verify, keep a backup of any
    .lu about to be overwritten, then move into place (and stage)."""
    import sr_backup
    out = Path(out)
    tmp = out.with_name(out.stem + ".partial" + out.suffix)
    if data is None:
        shutil.copyfile(src_path, tmp)
    else:
        tmp.write_bytes(data)
        try:
            verify(tmp)
        except Exception as ex:
            tmp.unlink(missing_ok=True)
            raise _ship_error(f"REFUSED: container verification failed for "
                              f"{Path(src_path).name}, nothing written.\n  {ex}",
                              kind="verify")
    same_file = out.exists() and out.resolve() == Path(src_path).resolve()
    for p in (out, Path(stage) / Path(src_path).name if stage else None):
        if p is not None and p.exists() and not os.access(p, os.W_OK):
            tmp.unlink(missing_ok=True)
            raise _ship_error(f"REFUSED: {p} is read-only, nothing written. "
                              f"Clear its read-only flag (Properties) to ship "
                              f"into it, or ship to another folder.",
                              kind="refused")
    for p, key in ((out, "out"), (Path(stage) / Path(src_path).name
                                  if stage else None, "staged")):
        if p is None:
            continue
        b = sr_backup.backup_before_overwrite(p)
        if b and b["created"]:
            rec = b["retail"] if b["created"] == "retail" else b["previous"][-1]
            target.setdefault("backups", []).append(rec["backup"])
            print(f"  kept a {'retail' if b['created'] == 'retail' else 'previous'}"
                  f" backup of {p.name} in {Path(rec['backup']).parent}")
        if key == "out":
            os.replace(tmp, out)
            target["out"] = str(out)
            if not same_file and data is not None:
                print(f"wrote {out} ({out.stat().st_size:,} bytes)")
        else:
            shutil.copyfile(out, p)
            target["staged"] = str(p)
            print(f"staged -> {p}; run the game to test.")


def _targets(a, edits):
    """[(path, index entries or None)] the ship goes to, primary first.
    Containers found through --all-in come with their cached index entries,
    so a preview never has to open them."""
    out = [(Path(a.lu), None)]
    seen = {Path(a.lu).resolve()}
    extra = [(Path(x), None) for x in (a.also or [])]
    if a.all_in:
        names = {e.script.name for e in edits}
        idx = container_index(a.all_in, exclude=a.exclude)
        for f, ss in idx.items():
            if any(x["name"] in names for x in ss):
                extra.append((Path(f), ss))
    for p, ss in extra:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append((p, ss))
    return out


def ship(a, report):
    """Everything `lu_lua.py ship` does; fills `report` (see cmd_ship)."""
    import nblua
    stage = Path(a.stage) if a.stage else None
    if stage and not stage.is_dir():
        raise _ship_error(f"--stage folder missing: {stage}", kind="usage")
    if not (a.preview or a.out or stage):
        raise _ship_error("say where to write: -o (a file, or a folder when "
                          "shipping to several containers) and/or --stage",
                          kind="usage")
    lu = LuFile(a.lu)
    game = game_of(lu)
    report["game"] = game
    edits = []
    for s, f in _collect_edits(a, lu):
        e = (_prepare_nb1 if game == NB1 else _prepare_pip)(a, lu, s, f)
        edits.append(e)
        report["scripts"].append(e.info)
    targets = _targets(a, edits)

    if a.preview:
        out_for = None
    elif a.out:
        o = Path(a.out)
        if len(targets) > 1 or o.is_dir():
            if o.exists() and not o.is_dir():
                raise _ship_error("with several target containers, -o must be "
                                  "a folder", kind="usage")
            o.mkdir(parents=True, exist_ok=True)
            out_for = lambda p: o / p.name
        else:
            out_for = lambda p: o
    else:
        tmpd = Path(tempfile.mkdtemp(prefix="srship_"))
        out_for = lambda p: tmpd / p.name

    import verify_lzx

    def verify_nb1(path):
        for msg in verify_lzx.verify_file(str(path)):
            print(f"  verify: {msg}")

    used_out = {}
    for n, (path, entries) in enumerate(targets):
        primary = n == 0
        t = {"container": str(path)}
        report["targets"].append(t)
        try:
            lu_t = None
            if primary:
                lu_t = lu
            elif entries is None or not (a.preview and game == NB1):
                lu_t = LuFile(str(path))
                if game_of(lu_t) != game:
                    raise _Refused(f"{path.name} is a container for the "
                                   f"other game")
                entries = _entries(lu_t)
            elif any(x.get("game") != game for x in entries):
                raise _Refused(f"{path.name} is a container for the other game")
            plan = _matches_in(path.name, edits, primary, entries)
            t["records"] = sorted(i for v in plan.values() for i in v)
            if lu_t is None:
                # NB1 preview straight from the index
                t["status"] = ("would-ship" if any(e.new_image is not None
                                                   for e in plan)
                               else "unchanged")
                continue
            if game == NB1 and a.preview:
                t["status"] = ("would-ship" if any(e.new_image is not None
                                                   for e in plan)
                               else "unchanged")
                continue
            if game == NB1:
                import lua_chunk_swap
                chunks = {}
                for e, idxs in plan.items():
                    if e.new_image is None:
                        continue
                    for i in idxs:
                        chunks[i] = lua_chunk_swap.swap(
                            bytes(lu_t.chunk(lu_t.records[i])), e.new_image)
                data = nblua.replace_records(lu_t, chunks) if chunks else None
                verify = verify_nb1
            else:
                from naughty_lu import rebuild_luh
                chunks, t["budget"] = {}, []
                for e, idxs in plan.items():
                    for i in idxs:
                        c, b = _pip_fit(lu_t, i, e)
                        t["budget"].append({"name": e.script.name, **b})
                        if c is None:
                            msg = (f"{e.script.name} in {path.name} is "
                                   f"{-b['spare']} bytes too large for its "
                                   f"slot even after squeezing "
                                   f"whitespace (slot allows {b['budget']} "
                                   f"source bytes); trim the script")
                            if primary and not a.preview:
                                raise _ship_error(msg, file=e.source,
                                                  kind="slot")
                            raise _Refused(msg)
                        chunks[i] = c
                data = rebuild_luh(lu_t, chunks)

                def verify(p, chunks=chunks):
                    import pip_scripts
                    lu2 = LuFile(str(p))
                    for i, c in chunks.items():
                        got = pip_scripts.parse_script_chunk(
                            bytes(lu2.chunk(lu2.records[i])))["src"]
                        if got != pip_scripts.parse_script_chunk(c)["src"]:
                            raise RuntimeError(
                                f"the source read back from record {i} does "
                                f"not match what was written")
                    print("VERIFY OK: container re-parses, injected source "
                          "reads back identical")
        except _Refused as r:
            if primary and not a.preview:
                raise _ship_error(str(r), kind="usage")
            t.update(status="refused", reason=str(r))
            print(f"  REFUSED: {r}")
            continue

        t["status"] = ("unchanged" if data is None and game == NB1 else
                       "would-ship" if a.preview else "shipped")
        if a.preview:
            continue
        out = out_for(path)
        if str(out).lower() in used_out:
            t.update(status="refused",
                     reason=f"{out} is already the output for "
                            f"{used_out[str(out).lower()]}")
            print(f"  REFUSED: {t['reason']}")
            continue
        used_out[str(out).lower()] = path.name
        if data is None:
            print(f"{path.name}: no function-level changes detected; nothing "
                  f"to inject.")
            _deliver(path, None, out, None, None, t)
            continue
        print(f"{path.name}:")
        _deliver(path, data, out, stage, verify, t)
        for e in plan:
            if game == NB1 and e.new_image is not None:
                fs = [f["path"] for f in e.info["functions"]]
                print(f"  shipped {e.script.name}: {len(fs)} function(s): "
                      f"{', '.join(fs)}")
            elif game == PIP:
                b = next(x for x in t["budget"] if x["name"] == e.script.name)
                print(f"  shipped {e.script.name} (record {b['record']}): "
                      f"{b['original']} -> {b.get('squeezed', b['edited'])} "
                      f"bytes")
        if game == NB1:
            print("  all other functions kept original game bytes.")


def _print_preview(report):
    print("PREVIEW: nothing was written.\n")
    for s in report["scripts"]:
        print(f"{s['name']} (record {s['index']}) from {Path(s['source']).name}:")
        if report["game"] == NB1:
            if s["functions"]:
                print(f"  would recompile {len(s['functions'])} function(s):")
                for f in s["functions"]:
                    what = ("top-level code, first change at line"
                            if f["path"] == "0" else "defined at line")
                    print(f"    {f['path']:<12} {what} {f['line']}")
            else:
                print("  no function changed; this script would ship as it is.")
        for w in s.get("warnings", []):
            print(f"  note: {w}")
        if s["diff"]:
            print("  your changes against a fresh read:")
            print("    " + s["diff"].rstrip("\n").replace("\n", "\n    "))
        else:
            print("  no text changes against a fresh read.")
        print()
    print("targets:")
    for t in report["targets"]:
        name = Path(t["container"]).name
        if t["status"] == "refused":
            print(f"  {name}: REFUSED: {t['reason']}")
        else:
            print(f"  {name}: {t['status']} (record "
                  f"{', '.join(map(str, t['records']))})")
        for b in t.get("budget", []):
            print(f"    {b['name']}: {_budget_text(b)}")


def cmd_ship(a):
    """Human log on stdout; with --json the log goes to stderr and stdout
    carries one JSON object:
      {"ok", "preview", "game", "container",
       "scripts": [{"index", "name", "source", "diff", "warnings",
                    "hash_calls", NB1: "backend", "functions": [{"path", "line"}],
                    PiP: "changed"}],
       "targets": [{"container", "status": shipped|unchanged|would-ship|refused,
                    "reason", "records", "out", "staged", "backups",
                    PiP: "budget": [{"name", "record", "slot", "budget",
                                     "original", "edited", "squeezed", "fits",
                                     "spare"}]}],
       "errors": [{"file", "line", "kind", "message"}]}
    Every error also prints  SR-ERROR file="<path>" line=<n> kind=<kind>: <msg>
    on stderr (line 0: not tied to one line)."""
    import contextlib
    import json
    report = {"ok": False, "preview": bool(a.preview), "game": None,
              "container": str(a.lu), "scripts": [], "targets": [],
              "errors": []}
    real_out = sys.stdout
    err = None
    with contextlib.redirect_stdout(sys.stderr if a.json else sys.stdout):
        try:
            ship(a, report)
        except SystemExit as e:
            if e.code in (None, 0):
                raise
            err = _ship_error(str(e.code), kind="usage")
            report["errors"].append(err.as_dict())
        except Exception as e:
            if not hasattr(e, "sr_line"):
                raise
            err = e
            report["errors"].append(e.as_dict())
        if not err and a.preview and not a.json:
            _print_preview(report)
    report["ok"] = err is None
    if a.json:
        print(json.dumps(report, indent=1), file=real_out)
    if err:
        sys.stderr.write(f"ship: {err}\n{err.sr_line()}\n")
        sys.exit(1)


def cmd_export(a):
    """Every script in every given container, as files you can search.

    NB1 scripts go through nbdec (the same reconstruction `read` uses, with
    the backend stamp, so an exported file can be shipped as it is); PiP
    scripts are already source. INDEX.txt lists each script with every
    container that carries it: the same script is often compiled into many
    containers, and an edit only takes effect in the ones you ship it to.
    """
    import hashlib
    import nblua
    import nb_names
    names = nb_names.load()
    texts = nb_names.load_text()
    paths = []
    skip = {x.lower() for x in (a.exclude or [])}
    for p in a.inputs:
        p = Path(p)
        found = sorted(p.glob("*.lu")) if p.is_dir() else [p]
        # an excluded name only filters folder contents, so a retail copy
        # given explicitly by path still goes in
        paths += [f for f in found if not (p.is_dir() and f.name.lower() in skip)]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = {}                  # chunk digest -> source; copies are common
    where = {}                  # script name -> [(container, index, digest)]
    written = declined = 0
    for f in paths:
        try:
            lu = LuFile(str(f))
        except Exception as e:
            print(f"  skipped {f.name}: {e}")
            continue
        game = game_of(lu)
        for s in scripts(lu):
            chunk = bytes(lu.chunk(lu.records[s.index]))
            digest = hashlib.sha1(chunk).hexdigest()[:12]
            if digest not in cache:
                if game == PIP or not s.compiled:
                    import pip_scripts
                    got = pip_scripts.extract_lua(chunk)
                    cache[digest] = got[1] if got else None
                else:
                    src = nblua.nbdec_source(chunk, names, texts)
                    cache[digest] = None if src is None else (
                        nblua.BACKEND_MARK.format("nbdec") + "\n" + src + "\n")
            src = cache[digest]
            where.setdefault(s.name, []).append((f.name, s.index, digest))
            if src is None:
                declined += 1
                continue
            dest = out / f.stem / f"{s.name}.lua"
            if dest.exists():
                dest = out / f.stem / f"{s.name}.{s.index}.lua"
            dest.parent.mkdir(exist_ok=True)
            dest.write_text(src, encoding="utf-8", newline="\n")
            written += 1
    lines = ["script  -> containers holding it (index); "
             "[n versions] when the copies are not all identical", ""]
    for name in sorted(where):
        locs = where[name]
        versions = len({d for _, _, d in locs})
        tag = f"  [{versions} versions]" if versions > 1 else ""
        lines.append(f"{name}{tag}")
        for cont, idx, dig in locs:
            lines.append(f"    {cont} ({idx})" +
                         (f"  version {dig}" if versions > 1 else ""))
    (out / "INDEX.txt").write_text("\n".join(lines) + "\n", encoding="utf-8",
                                   newline="\n")
    print(f"wrote {written} scripts ({len(cache)} distinct) from "
          f"{len(paths)} container(s) to {out}")
    if declined:
        print(f"  {declined} could not be reconstructed exactly and were "
              f"left out; `read` them one at a time to use a fallback")
    print(f"  INDEX.txt lists every script and where it lives")


# --------------------------------------------------------------------- where
INDEX_VERSION = 1


def cache_dir():
    """Per-user cache folder (never inside the repo). SEAMRIPPER_CACHE
    overrides it."""
    env = os.environ.get("SEAMRIPPER_CACHE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) / "SeamRipper" if base
            else Path.home() / ".cache" / "seamripper")


def _scan_container(path):
    """[{index, name, hash, size, compiled, digest, chunk_digest}] for one
    container, or None if it cannot be read. Containers without a script
    record are answered from the record table alone, without decompressing."""
    try:
        lu = LuFile(path)
        if not any(r.type == SCRIPT_TYPE and not r.external for r in lu.records):
            return []
        out = []
        for s in scripts(lu):
            chunk = bytes(lu.chunk(lu.records[s.index]))
            out.append({"index": s.index, "name": s.name, "hash": s.hash,
                        "size": s.size, "compiled": s.compiled,
                        "game": game_of(lu),
                        "digest": _digest(script_payload(chunk, s.compiled)),
                        "chunk_digest": _digest(chunk)})
        return out
    except Exception:
        return None


def container_index(folder, exclude=None, use_cache=True, log=print,
                    recursive=False):
    """{container path: [script entries]} for every .lu in `folder`, and in
    its subfolders when `recursive` (skipping hidden ones such as
    .seamripper, whose backups are .lu files too).

    Entries are cached per file, keyed by size and modification time, in
    cache_dir()/where_index.json, so only new or changed containers are
    read again."""
    folder = Path(folder)
    skip = {x.lower() for x in (exclude or [])}
    found = folder.rglob("*.lu") if recursive else folder.glob("*.lu")
    files = [f for f in sorted(found) if f.name.lower() not in skip
             and not any(d.startswith(".") for d in f.relative_to(folder).parts[:-1])]
    cache_file = cache_dir() / "where_index.json"
    cache = {}
    if use_cache:
        try:
            got = json.loads(cache_file.read_text(encoding="utf-8"))
            if got.get("version") == INDEX_VERSION:
                cache = got.get("files", {})
        except (OSError, ValueError):
            pass
    out, todo = {}, []
    for f in files:
        st = f.stat()
        key = str(f.resolve())
        c = cache.get(key)
        if c and c["size"] == st.st_size and c["mtime_ns"] == st.st_mtime_ns:
            out[str(f)] = c["scripts"]
        else:
            todo.append((f, key, st))
    if todo:
        log(f"indexing {len(todo)} container(s) in {folder} (only needed once; "
            f"later lookups use the cache)")
        results = _scan_many([str(f) for f, _, _ in todo])
        for (f, key, st), ss in zip(todo, results):
            if ss is None:
                continue
            out[str(f)] = ss
            cache[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                          "scripts": ss}
        if use_cache:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_file.with_name(cache_file.name + ".tmp")
                tmp.write_text(json.dumps({"version": INDEX_VERSION,
                                           "files": cache}), encoding="utf-8")
                os.replace(tmp, cache_file)
            except OSError:
                pass
    return out


def _scan_many(paths):
    # Reading a container means decompressing it in Python, so a full game
    # folder takes minutes on one core. Spread it over processes, except in
    # the frozen EXE, where a child process would start the GUI again.
    if len(paths) > 8 and not getattr(sys, "frozen", False):
        try:
            from concurrent.futures import ProcessPoolExecutor
            # each worker holds whole decompressed containers: one per core
            # (16 here) ran machines out of memory
            with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 1)) as ex:
                return list(ex.map(_scan_container, paths, chunksize=4))
        except Exception:
            pass
    return [_scan_container(p) for p in paths]


def find_copies(index, name, digest, game=None, skip=None):
    """Other containers carrying script `name`, as
    [{"container", "index", "identical", "size"}]: identical means the same
    Lua image (NB1) / source (PiP) as `digest`."""
    skip = Path(skip).resolve() if skip else None
    out = []
    for f, ss in sorted(index.items()):
        if skip and Path(f).resolve() == skip:
            continue
        for s in ss:
            if s["name"] == name and (game is None or s.get("game") == game):
                out.append({"container": f, "index": s["index"],
                            "identical": s["digest"] == digest,
                            "size": s["size"]})
    return out


def cmd_where(a):
    lu = LuFile(a.container)
    s = resolve(lu, a.name, a.index)
    chunk = bytes(lu.chunk(lu.records[s.index]))
    digest = _digest(script_payload(chunk, s.compiled))
    log = (lambda m: print(m, file=sys.stderr)) if a.json else print
    # a game keeps containers in subfolders (NB1: lu\, uh\); copies outside
    # the edited file's folder are reported, and the GUI leaves them unticked
    idx = container_index(a.folder, exclude=a.exclude,
                          use_cache=not a.no_cache, log=log, recursive=True)
    copies = find_copies(idx, s.name, digest, game_of(lu), skip=a.container)
    if a.json:
        print(json.dumps({"container": str(a.container), "index": s.index,
                          "name": s.name, "copies": copies}, indent=1))
        return
    same = [c for c in copies if c["identical"]]
    diff = [c for c in copies if not c["identical"]]
    src = f"{s.name} (record {s.index} of {Path(a.container).name})"
    if not copies:
        print(f"{src} is not in any other container in {a.folder}")
        return
    print(f"{src} is also in {len({c['container'] for c in copies})} other "
          f"container(s):")
    if same:
        print(f"\n  identical copy ({len(same)}): an edit ships to these as it is")
        for c in same:
            print(f"    {Path(c['container']).name:<40} record {c['index']}")
    if diff:
        print(f"\n  different version ({len(diff)}): read and edit the script "
              f"from these containers to change them")
        for c in diff:
            print(f"    {Path(c['container']).name:<40} record {c['index']}  "
                  f"({c['size']:,} bytes)")


# ------------------------------------------------------------------- backups
def cmd_backups(a):
    import sr_backup
    sr_backup.cmd_list(a.folder, a.json)


def cmd_revert(a):
    import sr_backup
    sr_backup.cmd_revert(a.path, a.previous, a.json)


# ----------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list the Lua scripts in a .lu")
    pl.add_argument("lu")
    pl.set_defaults(func=cmd_list)

    def common(p, out_required=True):
        p.add_argument("lu")
        p.add_argument("name", nargs="?", help="script name as shown by `list`")
        p.add_argument("--index", type=int,
                       help="address the record by index (unambiguous)")
        p.add_argument("-o", "--out", required=out_required)
        p.add_argument("--backend", choices=("auto", "nbdec", "unluac",
                                             "luadec"),
                       default="auto", help="NB1 only: which decompiler")
        p.add_argument("--jar", default=str(HERE / "unluac.jar"))
        p.add_argument("--luac", default=None)

    pr = sub.add_parser("read", help="pull one script out as editable Lua")
    common(pr)
    pr.set_defaults(func=cmd_read)

    ps = sub.add_parser("ship", help="write your edits back into the .lu")
    common(ps, out_required=False)
    ps.add_argument("source", nargs="?", help="your edited .lua")
    ps.add_argument("--edit", action="append", metavar="INDEX=FILE.lua",
                    help="another script of the same container and its edited "
                         "file (repeatable; NAME=FILE.lua works too)")
    ps.add_argument("--stage", help="build assets\\lu folder to copy into")
    ps.add_argument("--also", nargs="+", metavar="LU",
                    help="also ship to these containers, where they carry "
                         "an identical copy of the script")
    ps.add_argument("--all-in", metavar="FOLDER",
                    help="also ship to every container in FOLDER that "
                         "carries an identical copy of the script")
    ps.add_argument("--exclude", nargs="*", metavar="NAME.lu",
                    help="with --all-in: container names to leave out")
    ps.add_argument("--preview", action="store_true",
                    help="write nothing; show what would be recompiled, the "
                         "slot budget (PiP) and a diff of your edit")
    ps.add_argument("--json", action="store_true",
                    help="print the result as one JSON object on stdout")
    ps.add_argument("--force", action="store_true",
                    help="PiP: ship even if the Lua checks object. NB1: ship "
                         "even when the edit renames a global")
    ps.set_defaults(func=cmd_ship)

    pe = sub.add_parser("export", help="every script of many containers "
                        "into a folder tree you can search")
    pe.add_argument("inputs", nargs="+", help=".lu files and/or folders")
    pe.add_argument("-o", "--out", required=True)
    pe.add_argument("--exclude", nargs="*", metavar="NAME.lu",
                    help="container names to skip inside the given folders "
                         "(e.g. modded copies)")
    pe.set_defaults(func=cmd_export)

    pw = sub.add_parser("where", help="which other containers carry the "
                        "same script")
    pw.add_argument("folder", help="folder of .lu files to search (e.g. assets)")
    pw.add_argument("container", help="the .lu the script was read from")
    pw.add_argument("name", nargs="?", help="script name as shown by `list`")
    pw.add_argument("--index", type=int, help="the script's record index")
    pw.add_argument("--exclude", nargs="*", metavar="NAME.lu",
                    help="container names to leave out (e.g. modded copies)")
    pw.add_argument("--no-cache", action="store_true",
                    help="re-read every container instead of using the cache")
    pw.add_argument("--json", action="store_true")
    pw.set_defaults(func=cmd_where)

    pb = sub.add_parser("backups", help="list the backups Seam Ripper kept "
                        "in a folder")
    pb.add_argument("folder")
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(func=cmd_backups)

    pv = sub.add_parser("revert", help="put a .lu back from its retail "
                        "backup (a folder: every backed-up .lu in it)")
    pv.add_argument("path")
    pv.add_argument("--previous", action="store_true",
                    help="step back one version instead of going to retail")
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(func=cmd_revert)

    a = ap.parse_args()
    if (a.cmd == "ship" and a.name and not a.source
            and (a.index is not None or Path(a.name).is_file())):
        # `ship game.lu edit.lua --index N`: the one positional is the file
        a.source, a.name = a.name, None
    a.func(a)


if __name__ == "__main__":
    # so `import lu_lua` elsewhere gets this module, not a second copy
    sys.modules.setdefault("lu_lua", sys.modules[__name__])
    main()
