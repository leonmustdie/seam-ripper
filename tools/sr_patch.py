#!/usr/bin/env python3
"""Make, inspect and apply .srpatch mod patches, which hold only the lines a modder changed."""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FORMAT = "seamripper-patch"
FORMAT_VERSION = 1
SEAMRIPPER_VERSION = "2.0"   # keep in step with sr_gui.VERSION
GAMES = {"nb1": "Naughty Bear", "pip": "Naughty Bear: Panic in Paradise"}
CONTEXT = 3            # fingerprinted lines on each side of a change
MAX_CHANGED = 0.5      # more than this share of a script changed = wrong file


class PatchError(Exception):
    """A patch could not be made or applied; the message says why."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tool(script, *args):
    """argv for one toolkit script, run from source or from the frozen EXE."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tool", script, *map(str, args)]
    return [sys.executable, str(HERE / script), *map(str, args)]


def _run(argv, log, what):
    r = subprocess.run(argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    if r.returncode:
        for line in out.splitlines():
            log(f"    {line}")
        last = out.splitlines()[-1].strip() if out else f"exit code {r.returncode}"
        raise PatchError(f"{what} failed: {last}")
    return out


def _safe_name(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


# ------------------------------------------------------------ fingerprints
# A patch never stores the game's lines, only a fingerprint of them, taken
# with comments and spacing removed: the decompiler's --[[HASH/TEXT]]
# annotations depend on the reader's dictionaries, the code does not.
LONG_OPEN = re.compile(r"\[(=*)\[")
TEXT_NOTE = re.compile(r'\s*TEXT(?:\([^)\n]*\))?:"[^"\n]*"')


def _long_end(text, m):
    close = "]" + m.group(1) + "]"
    j = text.find(close, m.end())
    return len(text) if j < 0 else j + len(close)


def _strip_comments(text):
    """Lua text without comments; newlines inside comments are kept, so line
    numbers stay the same."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] not in (c, "\n"):
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "[" and LONG_OPEN.match(text, i):
            j = _long_end(text, LONG_OPEN.match(text, i))
            out.append(text[i:j])
            i = j
        elif text.startswith("--", i):
            m = LONG_OPEN.match(text, i + 2)
            if m:
                j = _long_end(text, m)
            else:
                j = text.find("\n", i)
                j = n if j < 0 else j
            out.append("\n" * text.count("\n", i, j))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def normal_lines(text):
    return [" ".join(ln.split()) for ln in _strip_comments(text).split("\n")]


def _fp(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def _scrub(line):
    """A changed line as stored: without the game text the decompiler put in
    its annotations (the recipient's own read puts it back)."""
    return TEXT_NOTE.sub("", line)


def diff_hunks(base, edited):
    """The changes from `base` to `edited` as hunks holding only the new
    lines, plus fingerprints of the lines they replace and of their
    surroundings."""
    a, b = base.split("\n"), edited.split("\n")
    na = normal_lines(base)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changed = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag != "equal")
    if changed > MAX_CHANGED * len(a):
        raise PatchError(f"{changed} of {len(a)} lines differ from a fresh read "
                         f"of the original; is this edit from another script?")
    return [{"at": i1 + 1, "old": i2 - i1, "old_fp": _fp(na[i1:i2]),
             "before_fp": _fp(na[max(0, i1 - CONTEXT):i1]),
             "after_fp": _fp(na[i2:i2 + CONTEXT]),
             "new": [_scrub(ln) for ln in b[j1:j2]]}
            for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _fits(h, na, i):
    return (_fp(na[i:i + h["old"]]) == h["old_fp"]
            and _fp(na[max(0, i - CONTEXT):i]) == h["before_fp"]
            and _fp(na[i + h["old"]:i + h["old"] + CONTEXT]) == h["after_fp"])


def apply_hunks(base, hunks):
    """`base` with the hunks spliced in. Each hunk goes where its
    fingerprints match: at its own line number, or, if the read there
    differs, at the one other place that matches. Raises PatchError naming
    the first hunk that fits nowhere or in several places."""
    a, na = base.split("\n"), normal_lines(base)
    placed = []
    for n, h in enumerate(hunks, 1):
        i = h["at"] - 1
        if not (0 <= i <= len(na) and _fits(h, na, i)):
            hits = [k for k in range(len(na) + 1) if _fits(h, na, k)]
            if len(hits) != 1:
                raise PatchError(
                    f"change {n} of {len(hunks)} (line {h['at']}) "
                    + ("matches nowhere" if not hits else
                       f"matches {len(hits)} places")
                    + " in your copy of the script, so it is not the "
                      "version the patch was made for")
            i = hits[0]
        placed.append((i, h))
    placed.sort(key=lambda p: p[0])
    for (i, h), (k, _) in zip(placed, placed[1:]):
        if i + h["old"] > k:
            raise PatchError("two changes in this patch overlap in your copy "
                             "of the script")
    for i, h in reversed(placed):
        a[i:i + h["old"]] = h["new"]
    return "\n".join(a)


# ------------------------------------------------------------ containers
def _game_and_scripts(path):
    import lu_lua
    from naughty_lu import LuFile
    lu = LuFile(str(path))
    return lu, lu_lua.game_of(lu), {s.index: s for s in lu_lua.scripts(lu)}


def _script_digest(lu, s):
    import lu_lua
    return lu_lua._digest(lu_lua.script_payload(
        bytes(lu.chunk(lu.records[s.index])), s.compiled))


def fresh_read(container, index, work):
    """The script as Seam Ripper reads it, exactly as the GUI and `read` do."""
    out = Path(work) / f"read_{_safe_name(Path(container).stem)}_{index}.lua"
    _run(_tool("lu_lua.py", "read", container, "--index", index, "-o", out),
         lambda m: None, f"reading script #{index} of {Path(container).name}")
    return out.read_text(encoding="utf-8").replace("\r\n", "\n")


def _parse_strings(text):
    """{hash: text} from a lu_strings extract file (escapes left as written)."""
    out = {}
    for ln in text.splitlines():
        if not ln.strip() or ln.startswith("#") or "\t" not in ln:
            continue
        h, t = ln.split("\t", 1)
        try:
            out[int(h, 16)] = t
        except ValueError:
            continue
    return out


def _changed_strings(orig, edited, work):
    """Only the lines of an edited strings file that differ from the original:
    the modder's own text, never the game's."""
    base = Path(work) / f"base_{_safe_name(orig.name)}.txt"
    _run(_tool("lu_strings.py", "extract", orig, "-o", base), lambda m: None,
         f"reading the strings of {orig.name}")
    old = _parse_strings(base.read_text(encoding="utf-8"))
    new = _parse_strings(Path(edited).read_text(encoding="utf-8"))
    unknown = [h for h in new if h not in old]
    if unknown:
        raise PatchError(f"{Path(edited).name} has {len(unknown)} string ID(s) "
                         f"that {orig.name} does not contain (first: "
                         f"{unknown[0]:08x}); was it extracted from another file?")
    return "".join(f"{h:08x}\t{t}\n" for h, t in new.items() if old[h] != t)


def _build(orig, scripts, strings, work, log):
    """Ship the script sources and then the strings into a copy of `orig`;
    -> the rebuilt file (in `work`)."""
    cur = Path(orig)
    if scripts:
        out = Path(work) / f"scripts_{cur.name}"
        edits = [a for i, src in scripts for a in ("--edit", f"{i}={src}")]
        _run(_tool("lu_lua.py", "ship", cur, *edits, "-o", out), log,
             f"shipping {len(scripts)} script(s) into {cur.name}")
        cur = out
    if strings:
        out = Path(work) / f"strings_{Path(orig).name}"
        got = _run(_tool("lu_strings.py", "apply", cur, strings, "-o", out,
                         "--verify"), log, "applying strings")
        if "VERIFY OK" not in got:
            raise PatchError("the edited strings did not read back correctly "
                             "from the rebuilt file")
        cur = out
    return cur


def _parallel(fn, items):
    """fn over items, a few at a time (each runs Seam Ripper's own tools as
    subprocesses), results in order; the first error is raised."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as ex:
        return list(ex.map(fn, items))


def retail_copy(container):
    """The retail original of a container: Seam Ripper's retail backup if
    something was shipped into the file, else the file itself. A patch is
    always the difference from retail, which is what recipients have."""
    import sr_backup
    p = Path(container)
    saved = sr_backup.backup_dir(p.parent) / p.name
    return saved if saved.is_file() else p


def _make_target(n, t, work):
    """One container's part of a patch -> (game, entry, {zip path: bytes},
    log lines). An entry with no edits changed nothing."""
    lines = []
    log = lines.append
    given = Path(t["container"])
    if not given.is_file():
        raise PatchError(f"original container not found: {given}")
    orig = retail_copy(given)
    if orig != given and sha256_file(orig) != sha256_file(given):
        log(f"{given.name} has been shipped into; the patch is made against "
            f"its retail backup")
    lu, game, scripts = _game_and_scripts(orig)
    log(f"{orig.name} ({GAMES[game]})")
    entry = {"file": orig.name, "size": orig.stat().st_size,
             "sha256": sha256_file(orig), "edits": []}
    work = Path(work) / f"t{n}"
    work.mkdir()
    rebuilt, add, strings = [], {}, None
    for index, src in t.get("scripts", ()):
        index = int(index)
        if index not in scripts:
            raise PatchError(f"{orig.name} has no script at index {index}")
        if any(e.get("index") == index for e in entry["edits"]):
            raise PatchError(f"script #{index} of {orig.name} is given twice")
        s = scripts[index]
        base = fresh_read(orig, index, work)
        edited = Path(src).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        hunks = diff_hunks(base, edited)
        if not hunks:
            log(f"  {s.name}: no changes; left out")
            continue
        entry["edits"].append({
            "kind": "script", "index": index, "name": s.name,
            "record_hash": f"0x{s.hash:08x}",
            "script_sha": _script_digest(lu, s),
            "reader": base.split("\n", 1)[0], "hunks": hunks})
        # ship what a recipient will get, not the modder's own file
        p = work / f"patched_{index}.lua"
        p.write_text(apply_hunks(base, hunks), encoding="utf-8", newline="\n")
        rebuilt.append((index, p))
        log(f"  {s.name}: {len(hunks)} change(s), "
            f"{sum(len(h['new']) for h in hunks)} line(s) of your code")
    if t.get("strings"):
        changed = _changed_strings(orig, t["strings"], work)
        if changed:
            zp = f"strings/{n}_{_safe_name(orig.name)}.txt"
            add[zp] = changed.encode("utf-8")
            strings = work / "strings_edit.txt"
            strings.write_text(changed, encoding="utf-8")
            entry["edits"].append({"kind": "strings", "source": zp,
                                   "count": changed.count("\n")})
            log(f"  {changed.count(chr(10))} string(s) changed")
    if not entry["edits"]:
        log("  nothing changed; file left out")
        return game, entry, add, lines
    log("  test-applying it the way a recipient will")
    final = _build(orig, rebuilt, strings, work, log)
    entry["result_size"] = final.stat().st_size
    entry["result_sha256"] = sha256_file(final)
    return game, entry, add, lines


# -------------------------------------------------------------------- make
def make_patch(out_path, targets, name, author="", description="",
               version="", log=print):
    """Write a .srpatch from edits to one or more original containers.

    targets: [{"container": path of the original .lu,
               "scripts": [(record index, edited .lua path), ...],
               "strings": edited lu_strings extract file or None}, ...]
    Each script is stored as its changed lines only. The patch is applied to
    the originals here, the same way a recipient applies it, so a patch that
    would not apply or ship is never written. Returns the manifest."""
    if not targets:
        raise PatchError("nothing to put in the patch")
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION,
                "game": None, "name": name, "author": author,
                "description": description, "version": version,
                "made_with": f"Seam Ripper {SEAMRIPPER_VERSION}", "targets": []}
    files = {}
    with tempfile.TemporaryDirectory(prefix="srpatch_") as work:
        done = _parallel(lambda nt: _make_target(nt[0], nt[1], work), enumerate(targets))
    for game, entry, add, lines in done:
        for ln in lines:
            log(ln)
        if manifest["game"] not in (None, game):
            raise PatchError("a patch holds edits for one game only; "
                             f"{entry['file']} is {GAMES[game]}")
        manifest["game"] = game
        if entry["edits"]:
            manifest["targets"].append(entry)
            files.update(add)
    if not manifest["targets"]:
        raise PatchError("none of the given edits change anything")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        for zp, data in files.items():
            z.writestr(zp, data)
    os.replace(tmp, out_path)
    log(f"wrote {out_path} ({out_path.stat().st_size:,} bytes): "
        f"{sum(len(t['edits']) for t in manifest['targets'])} edit(s) to "
        f"{len(manifest['targets'])} file(s)")
    return manifest


# -------------------------------------------------------------------- read
def read_manifest(patch):
    """The manifest of a patch; raises PatchError if it is not one."""
    try:
        with zipfile.ZipFile(patch) as z:
            m = json.loads(z.read("manifest.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise PatchError(f"{Path(patch).name} is not a Seam Ripper patch ({e})")
    if m.get("format") != FORMAT:
        raise PatchError(f"{Path(patch).name} is not a Seam Ripper patch")
    if m.get("format_version", 0) > FORMAT_VERSION:
        raise PatchError(f"this patch needs a newer Seam Ripper (patch format "
                         f"{m['format_version']}, this one reads up to "
                         f"{FORMAT_VERSION})")
    return m


def _game_files(folder, name):
    """Every file called `name` (any case) in `folder` and its subfolders,
    skipping hidden ones such as .seamripper, which holds backups."""
    folder = Path(folder)
    return sorted(p for p in folder.rglob("*")
                  if p.name.lower() == name.lower() and p.is_file()
                  and not any(d.startswith(".") for d in p.relative_to(folder).parts[:-1]))


def check_targets(manifest, folder):
    """Which of the recipient's files each target goes into ->
    [{"file", "path", "status", "detail"}]. status:
      "ok"         the exact file the patch was made from
      "compatible" the file differs, but every edited script is the same one
      "mismatch"   an edited script differs (a --force apply still needs
                   every change to find its lines)
      "applied"    the file already is this patch's result
      "missing" / "ambiguous"."""
    out = []
    for t in manifest["targets"]:
        found = _game_files(folder, t["file"])
        r = {"file": t["file"], "path": None, "status": "missing", "detail": ""}
        sums = {p: sha256_file(p) for p in found}
        exact = [p for p in found if sums[p] == t["sha256"]]
        done = [p for p in found if sums[p] == t.get("result_sha256")]
        if exact:
            r.update(path=str(exact[0]), status="ok")
        elif done:
            r.update(path=str(done[0]), status="applied",
                     detail="it already has this patch")
        elif len(found) > 1:
            r.update(status="ambiguous", detail="found in " + ", ".join(
                str(p.relative_to(folder)) for p in found))
        elif found:
            r["path"] = str(found[0])
            r["status"], r["detail"] = _script_match(found[0], t)
        r["read_only"] = bool(r["path"]) and not os.access(r["path"], os.W_OK)
        out.append(r)
    return out


def _script_match(path, t):
    lu, _, scripts = _game_and_scripts(path)
    for e in t["edits"]:
        if e["kind"] != "script":
            continue
        s = _find_script(scripts, e)
        if s is None:
            return "mismatch", f"script {e['name']} is not in this file"
        if _script_digest(lu, s) != e["script_sha"]:
            return "mismatch", f"script {e['name']} is a different version"
    return "compatible", "the file differs, but the edited scripts are the originals"


def _find_script(scripts, e):
    want = int(e["record_hash"], 16)
    s = scripts.get(e["index"])
    if s is not None and s.hash == want:
        return s
    alt = [s for s in scripts.values() if s.hash == want]
    return alt[0] if len(alt) == 1 else None


# ------------------------------------------------------------------- apply
def _apply_target(n, t, c, strings_data, game, work):
    """Build one patched file in `work` -> (log lines, path)."""
    lines = []
    log = lines.append
    log(f"{t['file']}: {c['status']}" + (f" ({c['detail']})" if c["detail"] else ""))
    work = Path(work) / f"t{n}"
    work.mkdir()
    _, _, scripts = _game_and_scripts(c["path"])
    rebuilt, strings = [], None
    for e in t["edits"]:
        if e["kind"] == "script":
            s = _find_script(scripts, e)
            if s is None:
                raise PatchError(f"script {e['name']} is not in {t['file']}")
            base = fresh_read(c["path"], s.index, work)
            if base.split("\n", 1)[0] != e.get("reader", base.split("\n", 1)[0]):
                log(f"  note: {e['name']} was read differently when the patch "
                    f"was made; the changes are placed by content")
            try:
                text = apply_hunks(base, e["hunks"])
            except PatchError as ex:
                raise PatchError(f"{t['file']}, {e['name']}: {ex}")
            p = work / f"patched_{s.index}.lua"
            p.write_text(text, encoding="utf-8", newline="\n")
            rebuilt.append((s.index, p))
        elif e["kind"] == "strings":
            strings = work / "strings.txt"
            strings.write_bytes(strings_data)
        else:
            raise PatchError(f"unknown edit kind '{e['kind']}'; this patch "
                             f"needs a newer Seam Ripper")
    final = _build(c["path"], rebuilt, strings, work, log)
    if game == "nb1":
        import verify_lzx
        try:
            verify_lzx.verify_file(str(final))
        except verify_lzx.VerifyError as ex:
            raise PatchError(f"{t['file']}: the rebuilt file failed "
                             f"verification, nothing written: {ex}")
    return lines, final


def apply_patch(patch, folder, out_dir=None, force=False, log=print):
    """Apply a patch to the game files in `folder`.

    With out_dir the patched files are written there; without it they
    replace the game's own, each backed up first (sr_backup, as Ship does).
    Refuses a missing or ambiguous file, and a mismatch unless force. Returns
    {"files": [{"file", "out", "status", "result_sha256"}], "ok"}; status
    "identical" means byte-for-byte the patch author's result."""
    import sr_backup
    m = read_manifest(patch)
    checks = check_targets(m, folder)
    bad = [c for c in checks if c["status"] in ("missing", "ambiguous")]
    if bad:
        raise PatchError("; ".join(
            f"{c['file']} is {c['status']}" + (f" ({c['detail']})" if c["detail"] else "")
            for c in bad) + f" in {folder}")
    wrong = [c for c in checks if c["status"] == "mismatch"]
    if wrong and not force:
        raise PatchError("these files are not the ones this patch was made for:\n"
                         + "\n".join(f"  {c['file']}: {c['detail']}" for c in wrong)
                         + "\nThey may already be modded, or be from another "
                           "version of the game. Restore the originals (History), "
                           "or force it: every change must still find its lines.")
    for c in checks:
        if c["status"] != "applied" and out_dir is None and not os.access(c["path"], os.W_OK):
            raise PatchError(f"{c['path']} is read-only, nothing written")
    result = {"files": [], "ok": True}
    for t, c in zip(m["targets"], checks):
        if c["status"] == "applied":
            log(f"{t['file']}: {c['detail']}; left as it is")
            result["files"].append({"file": t["file"], "out": c["path"],
                                    "status": "applied",
                                    "result_sha256": t["result_sha256"]})
    todo = [(n, t, c) for n, (t, c) in enumerate(zip(m["targets"], checks))
            if c["status"] != "applied"]
    with zipfile.ZipFile(patch) as z:
        strings = {}
        for n, t, _ in todo:
            for e in t["edits"]:
                if e["kind"] == "strings":
                    zp = PurePosixPath(e["source"])
                    if zp.is_absolute() or ".." in zp.parts:
                        raise PatchError(f"unsafe path in patch: {e['source']}")
                    strings[n] = z.read(e["source"])
    with tempfile.TemporaryDirectory(prefix="srpatch_") as work:
        built = _parallel(lambda item: _apply_target(*item, strings.get(item[0]),
                                                     m["game"], work), todo)
        for lines, _ in built:
            for ln in lines:
                log(ln)
        names = [Path(c["path"]).name.lower() for _, _, c in todo]
        clash = len(set(names)) < len(names)
        # everything built and verified before any game file is touched
        for (_, t, c), (_, final) in zip(todo, built):
            if not out_dir:
                dest = Path(c["path"])
            elif clash:     # e.g. lu\global.lu and uh\global.lu: keep the subfolders
                dest = Path(out_dir) / Path(c["path"]).relative_to(folder)
            else:
                dest = Path(out_dir) / Path(c["path"]).name
            if out_dir:
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                sr_backup.backup_before_overwrite(dest)
            tmp = dest.with_name(dest.name + ".srtmp")
            shutil.copyfile(final, tmp)
            os.replace(tmp, dest)
            got = sha256_file(dest)
            if c["status"] == "ok" and got == t.get("result_sha256"):
                status = "identical"
            elif c["status"] == "ok":
                status, result["ok"] = "differs", False
                made = m.get("made_with", "an older Seam Ripper")
                log(f"  {t['file']}: verified, but not byte-identical to the "
                    f"patch author's result (patch made with {made}, this is "
                    f"Seam Ripper {SEAMRIPPER_VERSION})")
            else:
                status = c["status"]
            log(f"  wrote {dest} ({status})")
            result["files"].append({"file": t["file"], "out": str(dest),
                                    "status": status, "result_sha256": got})
    return result


# --------------------------------------------------------------------- cli
def info_text(m, patch):
    lines = [f"{m.get('name') or Path(patch).stem}"
             + (f"  v{m['version']}" if m.get("version") else "")
             + (f"  by {m['author']}" if m.get("author") else ""),
             f"game: {GAMES.get(m['game'], m['game'])}"]
    if m.get("made_with"):
        lines.append(f"made with: {m['made_with']}")
    if m.get("description"):
        lines.append(m["description"])
    for t in m["targets"]:
        lines.append(f"\n{t['file']}")
        for e in t["edits"]:
            if e["kind"] == "script":
                lines.append(f"  script {e['name']}: {len(e['hunks'])} change(s)")
            else:
                lines.append(f"  {e.get('count', '?')} localization string(s)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("make", help="build a patch from your edits")
    pm.add_argument("-o", "--out", required=True, help=".srpatch file to write")
    pm.add_argument("--name", required=True)
    pm.add_argument("--author", default="")
    pm.add_argument("--description", default="")
    pm.add_argument("--version", default="")
    pm.add_argument("--script", nargs=3, action="append", default=[],
                    metavar=("ORIGINAL.lu", "INDEX", "EDITED.lua"),
                    help="one edited script: the original container, the "
                         "script's index (from `lu_lua.py list`), your .lua")
    pm.add_argument("--strings", nargs=2, action="append", default=[],
                    metavar=("ORIGINAL.lu", "EDITED.txt"),
                    help="edited localization strings (a `lu_strings.py "
                         "extract` file); only changed lines are kept")

    pi = sub.add_parser("info", help="show what a patch contains")
    pi.add_argument("patch")
    pi.add_argument("--json", action="store_true")

    pa = sub.add_parser("apply", help="apply a patch to your game files")
    pa.add_argument("patch")
    pa.add_argument("folder", help="your game folder")
    pa.add_argument("-o", "--out", help="write the patched files here instead "
                                         "of replacing the game's (which are "
                                         "backed up first)")
    pa.add_argument("--force", action="store_true",
                    help="apply even if a file is not the one the patch was "
                         "made for, as long as every change finds its lines")
    pa.add_argument("--check", action="store_true",
                    help="only check which of your files the patch fits")
    pa.add_argument("--json", action="store_true",
                    help="print a JSON result as the last line")
    a = ap.parse_args()

    try:
        if a.cmd == "make":
            targets = {}
            for orig, index, src in a.script:
                if not index.isdigit():
                    sys.exit(f"script index must be a number, got '{index}'")
                t = targets.setdefault(str(Path(orig).resolve()).lower(), {
                    "container": orig, "scripts": [], "strings": None})
                t["scripts"].append((int(index), src))
            for orig, src in a.strings:
                t = targets.setdefault(str(Path(orig).resolve()).lower(), {
                    "container": orig, "scripts": [], "strings": None})
                if t["strings"]:
                    sys.exit(f"--strings given twice for {orig}")
                t["strings"] = src
            make_patch(a.out, list(targets.values()), a.name, a.author,
                       a.description, a.version)
        elif a.cmd == "info":
            m = read_manifest(a.patch)
            print(json.dumps(m, ensure_ascii=False) if a.json else info_text(m, a.patch))
        elif a.check:
            checks = check_targets(read_manifest(a.patch), a.folder)
            if a.json:
                print(json.dumps(checks))
            else:
                for c in checks:
                    print(f"  {c['file']}: {c['status']}"
                          + (f" ({c['detail']})" if c["detail"] else ""))
            if any(c["status"] not in ("ok", "compatible", "applied") for c in checks):
                sys.exit(1)
        else:
            r = apply_patch(a.patch, a.folder, a.out, a.force)
            if a.json:
                print(json.dumps(r))
            if not r["ok"]:
                sys.exit(2)
    except PatchError as e:
        sys.exit(f"{a.cmd}: {e}")


if __name__ == "__main__":
    main()
