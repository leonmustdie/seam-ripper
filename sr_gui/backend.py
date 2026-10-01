"""The GUI's one door to the toolkit: command lines for the tools, in-process calls
for backups and PiP checks, and one function per feature still being built.

Functions marked NOT WIRED raise NotAvailable; the page that calls them shows the
message ("not available yet") instead of inventing data.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .paths import tool_argv
from .settings import project_options


class NotAvailable(Exception):
    """A feature that isn't connected yet."""

    def __init__(self, what):
        super().__init__(f"{what} is not available yet.")
        self.what = what


# ------------------------------------------------- command lines
def _decompiler(settings):
    return settings.get("decompiler", "auto") or "auto"


def list_argv(settings, lu):
    return tool_argv(settings, "lu_lua.py", "list", str(lu))


def read_argv(settings, lu, index, out):
    return tool_argv(settings, "lu_lua.py", "read", str(lu), "--index", str(index),
                     "-o", str(out), "--backend", _decompiler(settings),
                     "--luac", settings["luac"], "--jar", settings["jar"])


def ship_argv(settings, lu, edits, out, also=(), force=False, preview=False):
    """`lu_lua.py ship` for several edits in one container.

    edits: [(record index, .lua file)]. `out` is the output file, or a folder when
    `also` names more containers (each is written as <out>/<its name>). Always
    `--backend auto`: `read` stamps the decompiler into the file and ship reads it
    back, so the baseline matches what was edited. Output is one JSON object."""
    a = tool_argv(settings, "lu_lua.py", "ship", str(lu))
    for index, src in edits:
        a += ["--edit", f"{index}={src}"]
    a += ["-o", str(out), "--backend", "auto", "--luac", settings["luac"],
          "--jar", settings["jar"], "--json"]
    if also:
        a += ["--also", *map(str, also)]
    if force:
        a.append("--force")
    if preview:
        a.append("--preview")
    return a


def where_argv(settings, folder, lu, name, index):
    return tool_argv(settings, "lu_lua.py", "where", str(folder), str(lu), name,
                     "--index", str(index), "--json")


def info_argv(settings, lu):
    return tool_argv(settings, "naughty_lu.py", "info", str(lu))


def strings_extract_argv(settings, lu, out):
    return tool_argv(settings, "lu_strings.py", "extract", str(lu), "-o", str(out))


def strings_apply_argv(settings, lu, txt, out):
    return tool_argv(settings, "lu_strings.py", "apply", str(lu), str(txt),
                     "-o", str(out), "--verify")


def spelling_argv(settings, lu):
    return tool_argv(settings, "lu_autofix.py", "report", str(lu))


def extract_argv(settings, lu, out):
    return tool_argv(settings, "naughty_lu.py", "extract", str(lu), "-o", str(out))


def convert_argv(settings, src, out):
    return tool_argv(settings, "lu_convert.py", str(src), "-o", str(out), "--no-glb")


# ------------------------------------------------- results
SR_ERROR = re.compile(r'^SR-ERROR file="([^"]*)" line=(\d+) kind=(\w+): (.*)$', re.M)


def parse_json(stdout):
    """The JSON object a `--json` run printed (None if there isn't one)."""
    text = (stdout or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    i = text.find("{")
    while i >= 0:
        try:
            return json.loads(text[i:])
        except ValueError:
            i = text.find("{", i + 1)
    return None


def parse_errors(stdout, stderr=""):
    """[{'file','line','kind','message'}] from a ship/preview run: the JSON
    `errors` list, or the SR-ERROR line when there is no JSON."""
    data = parse_json(stdout)
    if data and data.get("errors"):
        return data["errors"]
    return [{"file": f, "line": int(n), "kind": k, "message": m}
            for f, n, k, m in SR_ERROR.findall((stderr or "") + "\n" + (stdout or ""))]


NOTE_LINE = re.compile(r"^\s*note: line (\d+): (.*)$", re.M)


def parse_notes(stdout, stderr=""):
    """[{'line','message'}]: the non-blocking `note: line N: ...` lines a compile
    printed (number spelling the game compiler will store differently)."""
    seen, out = set(), []
    for n, m in NOTE_LINE.findall((stderr or "") + "\n" + (stdout or "")):
        if (n, m) not in seen:
            seen.add((n, m))
            out.append({"line": int(n), "message": m})
    return out


FORCEABLE = {"stale", "refused", "syntax", "structure"}


def friendly(err, game=None):
    """(message for a modder, can_force) for one error dict."""
    kind, msg = err.get("kind", ""), err.get("message", "")
    if kind == "stale":
        return ("This file doesn't match the script as it is now. It was probably read "
                "from another script or an older version. Re-read it and redo your edit, "
                "or ship anyway if you're sure.", True)
    if kind == "baseline":
        return ("Couldn't rebuild this script's original to compare with (not your "
                "edit's fault). Revert the script and open it again. " + msg, False)
    if kind == "syntax":
        if game == "pip":
            return (msg + " The game reads this file itself and can hang on a script "
                    "that doesn't parse.", True)
        return (msg, False)
    if kind == "structure":
        if game == "pip":
            return (msg + " Unbalanced brackets or quotes can hang the game at boot.", True)
        return (msg + " Only function bodies can be changed: keep the function lines "
                "as they are.", False)
    if kind == "refused":
        return (msg, True)
    if kind == "slot":
        return (msg + " Scripts must fit the space of the original.", False)
    return (msg, False)


# ------------------------------------------------- where Ship writes
class Plan:
    def __init__(self, out, in_place, note):
        self.out, self.in_place, self.note = Path(out), in_place, note


def ship_to(project, settings):
    """The 'ship to' folder for a project ('' = the game folder itself)."""
    if project is None:
        return ""
    return project_options(settings, project.folder).get("ship_to", "").strip()


def plan_output(project, settings, lu):
    """Where a ship of container `lu` writes: over the container itself (the
    original is backed up first) or into the project's 'ship to' folder."""
    lu = Path(lu)
    dest = ship_to(project, settings)
    if dest:
        return Plan(Path(dest) / lu.name, False,
                    f"Rebuilt containers go to {dest}. Your game folder is not changed.")
    return Plan(lu, True, "Ship overwrites the game file after backing it up "
                          "(see History to put it back).")


# ------------------------------------------------- backups (sr_backup, in-process)
def _sr_backup():
    import sr_backup
    return sr_backup


def backup_folders(project):
    """Folders under the project that hold a .seamripper\\backups folder."""
    out = []
    for root, dirs, _files in os.walk(project.folder):
        if ".seamripper" in dirs and (Path(root) / ".seamripper" / "backups").is_dir():
            out.append(Path(root))
        dirs[:] = [d for d in dirs if d != ".seamripper"]
    return out


def backups_list(project):
    """[{'file','path','state','when','previous'}]: one row per backed-up file.
    state: 'retail' (unchanged), 'modified' (differs from retail) or 'missing'."""
    sb = _sr_backup()
    rows = []
    for folder in backup_folders(project):
        for r in sb.list_backups(folder):
            times = [r["retail"].get("time", "")] + [p.get("time", "") for p in r["previous"]]
            rows.append({"file": r["file"], "path": r["path"],
                         "state": {"retail": "retail", "modified": "modified"}.get(
                             r["current"], "missing"),
                         "when": max(t for t in times if t is not None) if times else "",
                         "previous": len(r["previous"])})
    return sorted(rows, key=lambda r: r["path"].lower())


def modified_files(project):
    """Set of live file paths (str) that differ from their retail backup."""
    try:
        return {str(Path(r["path"])) for r in backups_list(project) if r["state"] == "modified"}
    except Exception:
        return set()


def revert_to_retail(path):
    return _sr_backup().revert_to_retail(path)


def restore_previous(path):
    return _sr_backup().restore_previous(path)


def revert_all(project):
    """Revert everything backed up, folder by folder -> [result dicts]."""
    out = []
    for folder in backup_folders(project):
        out += _sr_backup().revert_all(folder)
    return out


def backup_before_overwrite(dest):
    """Back up `dest` (if it exists) before something not run through ship
    overwrites it."""
    return _sr_backup().backup_before_overwrite(dest)


# ------------------------------------------------- PiP checks (in-process)
def _pip():
    import pip_scripts
    return pip_scripts


def pip_warm(lu):
    """Parse a PiP container so later budget() calls are instant. Slow the first
    time (up to ~25 s on the biggest units): call from a worker thread."""
    _pip().container_slots(str(lu))
    return True


def pip_budget(lu, index, text):
    """Space left in a PiP script's slot plus the structure problems of the text,
    lines/columns as the editor numbers them. Instant once pip_warm has run."""
    return _pip().budget(str(lu), int(index), text, check=True)


def _schema():
    import pip_schema
    return pip_schema


def schema_cached():
    """The cached PiP data schema, or None (never builds)."""
    try:
        return _schema().load_schema()
    except Exception:
        return None


def schema_build(pip_folder, progress=None):
    """Build and cache the PiP data schema (about 4 minutes). Worker thread."""
    ps = _schema()
    schema = ps.build(pip_folder, progress=progress)
    ps.save(schema)
    return schema


def value_warnings(orig, text, schema=None):
    """[{'line','col','kind','message',...}] for out-of-range or unknown data
    values the edit added. Warnings only."""
    return _schema().check(orig, text, schema=schema)


# ------------------------------------------------- restuff build: install, launch, history
POPEN = subprocess.Popen                # tests swap in a fake so nothing really starts


class NoBuild(Exception):
    """Launching needs a restuff build folder that Settings has not got right yet."""


def _launcher():
    import sr_launch
    return sr_launch


def build_folder(settings):
    return (settings.get("restuff_build") or "").strip()


def build_check(folder):
    """(sr_launch.locate() dict, '') for a usable restuff build folder, else
    (None, the reason)."""
    if not (folder or "").strip():
        return None, ""
    sl = _launcher()
    try:
        return sl.locate(folder.strip()), ""
    except sl.LaunchError as e:
        return None, str(e)


def require_build(settings):
    folder = build_folder(settings)
    if not folder:
        raise NoBuild("Set the restuff build folder in Settings (Play) first: the folder "
                      "that holds restuff.exe.")
    d, why = build_check(folder)
    if d is None:
        raise NoBuild(why)
    return d


def launch(project, settings):
    """Start restuff.exe (detached, log file argument included) -> {'pid', 'argv', 'log',
    'crash', 'hint'}. Raises NoBuild or sr_launch.LaunchError."""
    d = require_build(settings)
    sl = _launcher()
    got = sl.launch(d["build"], popen=POPEN)
    got["hint"] = sl.log_hint(d["build"])
    return got


def install_shipped(settings, paths):
    """Copy exactly the shipped containers into the build's assets\\lu, backing up its
    originals first. Files that already live there (the project IS that folder) are not
    copied -> {'installed': [{'file','dest','backup','created','changed'}], 'in_place':
    [names], 'lu': the build's game folder}. Raises NoBuild or sr_launch.LaunchError."""
    d = require_build(settings)
    lu = os.path.normcase(str(Path(d["lu"]).resolve()))
    todo, in_place, seen = [], [], set()
    for p in paths:
        key = os.path.normcase(str(Path(p).resolve()))
        if key in seen:
            continue
        seen.add(key)
        if os.path.normcase(str(Path(p).resolve().parent)) == lu:
            in_place.append(Path(p).name)
        else:
            todo.append(p)
    rows = _launcher().install(d["build"], todo, log=lambda _m: None) if todo else []
    return {"installed": rows, "in_place": in_place, "lu": d["lu"]}


def build_modified(settings):
    """Names of game files in the build that differ from the originals Seam Ripper saved
    (empty when there is no usable build)."""
    d, _why = build_check(build_folder(settings))
    if d is None:
        return []
    return [r["file"] for r in _sr_backup().list_backups(d["lu"]) if r["current"] != "retail"]


def build_revert(settings):
    """Put every installed file in the build back to its saved original -> names."""
    d = require_build(settings)
    return _launcher().restore(d["build"], build_modified(settings), log=lambda _m: None)


# ------------------------------------------------- hash lookup (in-process; the names are small)
def hash_lookup(text):
    """A name or a hash -> {'kind': 'name'|'hash'|'empty'|'bad', 'text': what to show,
    'known': bool or None, 'copy': text for the Copy button, 'copy2': a second copy value
    ('' if none), 'copy2_label'}."""
    import sr_lookup
    r = sr_lookup.lookup(text)
    out = {"kind": r["kind"], "text": r["message"], "known": None, "copy": "", "copy2": "",
           "copy2_label": ""}
    if r["kind"] == "name":
        d = r["results"][0]
        out["known"] = d["known"]
        lines = [f"{d['name']}  =  {d['hex']}", f"as a number: {d['decimal']}"]
        if d["names"] and not d["known"]:
            lines.append(f"The dictionary knows this hash as {d['names'][0]}.")
        elif not d["known"]:
            lines.append("Not in the name dictionary (the hash is still right).")
        for alt in r["results"][1:]:
            lines.append(_hash_line(alt, f"Read as a hash ({alt['how']}): "))
        out.update(text="\n".join(lines), copy=d["hex"], copy2=str(d["decimal"]),
                   copy2_label="Copy number")
    elif r["kind"] == "hash":
        res = r["results"]
        out["known"] = any(d["names"] for d in res)
        out["text"] = "\n".join(_hash_line(d, f"({d['how']}) " if len(res) > 1 else "")
                                for d in res)
        first = next((d for d in res if d["names"]), None)
        out["copy"] = first["names"][0] if first else ""
    return out


def _hash_line(d, prefix=""):
    if d["names"]:
        tier = f" [{d['tier']}]" if d.get("tier") else ""
        s = f"{prefix}{d['hex']}  =  {', '.join(d['names'])}{tier}"
    else:
        s = f"{prefix}{d['hex']}: unknown hash. It is not in the name dictionary."
    if d.get("text"):
        s += f"\nGame text: {d['text']!r}"
    return s


# ------------------------------------------------- search all scripts (a subprocess)
SEARCH_LIMIT = 2000


def search_argv(settings, folder, query, regex=False, case=False, limit=SEARCH_LIMIT):
    """`sr_search.py find` for a game folder: JSON lines (progress, hit, done)."""
    a = tool_argv(settings, "sr_search.py", "find", str(folder), "--json",
                  "--limit", str(limit))
    if regex:
        a.append("--regex")
    if case:
        a.append("--case")
    return a + ["--", query]


def parse_search_line(line):
    """One line of `sr_search.py find --json` -> its dict, or None for anything else."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        got = json.loads(line)
    except ValueError:
        return None
    return got if isinstance(got, dict) and "type" in got else None


# ------------------------------------------------- NOT WIRED features
def texture_replace(project, lu, texture, image):
    """Replace `texture` in `lu` with a PNG/DDS of the same size and format;
    -> {'ok': bool, 'problems': [...]}.  NOT WIRED."""
    raise NotAvailable("Texture import")


# ------------------------------------------------- patches (tools\sr_patch.py, run as a subprocess)
def patch_make_argv(settings, out, meta, entries):
    """`sr_patch.py make`: entries are (original container, record index, edited .lua);
    meta holds name, author, version, description. Writes only the .srpatch file."""
    a = tool_argv(settings, "sr_patch.py", "make", "-o", str(out), "--name", meta["name"])
    for key in ("author", "version", "description"):
        if meta.get(key):
            a += [f"--{key}", meta[key]]
    for lu, index, src in entries:
        a += ["--script", str(lu), str(index), str(src)]
    return a


def patch_info_argv(settings, patch):
    return tool_argv(settings, "sr_patch.py", "info", str(patch), "--json")


def patch_apply_argv(settings, patch, folder, out=None, force=False, check=False):
    """`sr_patch.py apply`. Without `out` the game files in `folder` are replaced (each
    backed up first); with it the patched copies go there. `check` only reports."""
    a = tool_argv(settings, "sr_patch.py", "apply", str(patch), str(folder))
    if out:
        a += ["-o", str(out)]
    if force:
        a.append("--force")
    if check:
        a.append("--check")
    return a + ["--json"]


def patch_json(stdout):
    """The JSON value on the last line a `--json` patch run printed (None if none)."""
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def patch_error(stderr, stdout=""):
    """The message a failed patch run ended with (the tool exits with one line)."""
    lines = [l.strip() for l in (stderr or stdout or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else "The patch tool failed. See the log."


def patch_changes(entry):
    """How many changes a patch entry (one file) holds."""
    return sum(len(e["hunks"]) if e["kind"] == "script" else e.get("count", 0)
               for e in entry["edits"])


def patch_summary(manifest, size):
    """One line about a finished patch: '13 files, 2 changes each, 2 KB, contains no game files'."""
    counts = [patch_changes(t) for t in manifest["targets"]]
    n = len(counts)
    if n == 1:
        many = f"{counts[0]} change" + ("" if counts[0] == 1 else "s")
    elif len(set(counts)) == 1:
        many = f"{counts[0]} change" + ("" if counts[0] == 1 else "s") + " each"
    else:
        many = f"{sum(counts)} changes in total"
    kb = f"{max(1, round(size / 1024))} KB" if size >= 1024 else f"{size} bytes"
    return f"{n} file{'' if n == 1 else 's'}, {many}, {kb}, contains no game files"


READY = ("ok", "compatible", "applied")


def patch_status_text(check):
    """(words for a modder, tone) for one file of `apply --check --json`."""
    s, detail = check["status"], check.get("detail", "")
    if check.get("read_only") and s in ("ok", "compatible"):
        return "fits, but the file is read-only", "warn"
    if s == "ok":
        return "ready", "ok"
    if s == "compatible":
        return "ready (this file has other changes; the patched scripts are original)", "ok"
    if s == "applied":
        return "already has this patch", "ok"
    if s == "mismatch":
        return "different version: " + detail, "warn"
    if s == "ambiguous":
        return "found more than once: " + detail, "err"
    return "not found", "err"


def patch_result_text(row):
    """Plain words for one file of a finished `apply --json`."""
    return {"identical": "identical to the author's result",
            "applied": "already had it",
            "differs": "applied, but not byte-identical to the author's result "
                       "(another Seam Ripper version?)",
            "compatible": "applied (the file has other changes)",
            "mismatch": "applied (forced)"}.get(row["status"], "applied")


def patch_manifest(patch):
    """The manifest of a finished patch, read in-process (a zip; instant)."""
    import sr_patch
    return sr_patch.read_manifest(patch)
