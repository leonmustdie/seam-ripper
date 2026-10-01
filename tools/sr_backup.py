#!/usr/bin/env python3
"""Keep the untouched copy of every .lu Seam Ripper overwrites, and put it back."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

BACKUP_DIR = Path(".seamripper") / "backups"
MANIFEST = "manifest.json"
# earlier versions kept per file besides the retail copy, which is never
# pruned; enough to step back through a modding session
KEEP_PREVIOUS = 10


class BackupError(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def backup_dir(folder):
    """Where the backups for files in `folder` live."""
    return Path(folder) / BACKUP_DIR


def _load(folder):
    try:
        return json.loads((backup_dir(folder) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(folder, manifest):
    d = backup_dir(folder)
    tmp = d / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, d / MANIFEST)


def _copy_in(src, dest):
    """Copy without ever leaving a half-written file under dest's name."""
    tmp = dest.with_name(dest.name + ".partial")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def _record(saved, original):
    return {"backup": str(saved), "original": str(original),
            "size": saved.stat().st_size, "sha256": _sha256(saved),
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def _entry(folder, name, manifest):
    """The manifest entry for one file, rebuilt from disk if the manifest
    lost it (a retail copy on disk always wins over a missing record)."""
    d = backup_dir(folder)
    e = manifest.get(name) or {}
    retail = d / name
    if not e.get("retail") and retail.is_file():
        e["retail"] = {"backup": str(retail),
                       "original": str(Path(folder).resolve() / name),
                       "size": retail.stat().st_size,
                       "sha256": _sha256(retail), "time": ""}
    e["previous"] = [p for p in e.get("previous", [])
                     if Path(p["backup"]).is_file()]
    return e


def backup_before_overwrite(dest):
    """Save `dest` before something overwrites it.

    The first time a file is backed up that copy becomes its retail backup,
    kept forever and never overwritten. Later calls keep the version being
    replaced as a "previous" copy (the newest KEEP_PREVIOUS are kept), unless
    it is byte-identical to the newest backup already held.

    Returns None if dest does not exist, else
    {"file", "retail": record, "previous": [record, ...] oldest first,
     "created": "retail" | "previous" | None}
    where a record is {"backup", "original", "size", "sha256", "time"}.
    """
    dest = Path(dest)
    if not dest.is_file():
        return None
    folder, name = dest.parent, dest.name
    d = backup_dir(folder)
    d.mkdir(parents=True, exist_ok=True)
    manifest = _load(folder)
    e = _entry(folder, name, manifest)
    created = None
    if not e.get("retail"):
        saved = d / name
        _copy_in(dest, saved)
        e["retail"] = _record(saved, dest.resolve())
        created = "retail"
    else:
        digest = _sha256(dest)
        newest = (e["previous"] or [e["retail"]])[-1]
        if digest != newest["sha256"]:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            saved = d / f"{dest.stem}.{stamp}{dest.suffix}"
            n = 1
            while saved.exists():
                saved = d / f"{dest.stem}.{stamp}-{n}{dest.suffix}"
                n += 1
            _copy_in(dest, saved)
            e["previous"].append(_record(saved, dest.resolve()))
            created = "previous"
            for old in e["previous"][:-KEEP_PREVIOUS]:
                Path(old["backup"]).unlink(missing_ok=True)
            e["previous"] = e["previous"][-KEEP_PREVIOUS:]
    manifest[name] = e
    _save(folder, manifest)
    return {"file": name, **e, "created": created}


def list_backups(folder):
    """Every file in `folder` that has backups, sorted by name:
    [{"file", "path", "retail": record, "previous": [record, ...],
      "current": "retail" | "modified" | "missing"}]
    `current` compares the live file with its retail backup."""
    folder = Path(folder)
    d = backup_dir(folder)
    if not d.is_dir():
        return []
    manifest = _load(folder)
    names = set(manifest) | {p.name for p in d.iterdir()
                             if p.is_file() and p.suffix.lower() == ".lu"
                             and not _is_previous_name(p.name, manifest)}
    out = []
    for name in sorted(names):
        e = _entry(folder, name, manifest)
        if not e.get("retail"):
            continue
        live = folder / name
        if not live.is_file():
            current = "missing"
        elif (live.stat().st_size == e["retail"]["size"]
              and _sha256(live) == e["retail"]["sha256"]):
            current = "retail"
        else:
            current = "modified"
        out.append({"file": name, "path": str(live), "retail": e["retail"],
                    "previous": e["previous"], "current": current})
    return out


def _is_previous_name(fname, manifest):
    return any(Path(p["backup"]).name == fname
               for e in manifest.values() for p in e.get("previous", []))


def _check(record):
    saved = Path(record["backup"])
    if not saved.is_file():
        raise BackupError(f"backup {saved} is missing")
    if _sha256(saved) != record["sha256"]:
        raise BackupError(f"backup {saved.name} does not match the checksum "
                          f"recorded when it was made; it may be damaged, so "
                          f"nothing was restored")
    return saved


def revert_to_retail(path):
    """Put the retail backup of `path` back. The version being replaced is
    kept as a previous copy first, so restore_previous() can undo this.
    Returns {"file", "restored": record, "changed": bool}."""
    path = Path(path)
    e = _entry(path.parent, path.name, _load(path.parent))
    if not e.get("retail"):
        raise BackupError(f"no Seam Ripper backup of {path.name} in "
                          f"{backup_dir(path.parent)}")
    saved = _check(e["retail"])
    if path.is_file() and _sha256(path) == e["retail"]["sha256"]:
        return {"file": path.name, "restored": e["retail"], "changed": False}
    if path.is_file():
        backup_before_overwrite(path)
    _copy_in(saved, path)
    return {"file": path.name, "restored": e["retail"], "changed": True}


def restore_previous(path):
    """Step `path` back one version: the copy saved just before the latest
    overwrite, or the retail copy when no earlier version is held. The copy
    used is taken off the list, so calling this again steps back further.
    Returns {"file", "restored": record, "changed": bool}."""
    path = Path(path)
    manifest = _load(path.parent)
    e = _entry(path.parent, path.name, manifest)
    if not e.get("retail"):
        raise BackupError(f"no Seam Ripper backup of {path.name} in "
                          f"{backup_dir(path.parent)}")
    live = _sha256(path) if path.is_file() else None
    # an entry identical to what is there now is no step back; skip it
    while e["previous"] and e["previous"][-1]["sha256"] == live:
        Path(e["previous"].pop()["backup"]).unlink(missing_ok=True)
    rec = e["previous"][-1] if e["previous"] else e["retail"]
    saved = _check(rec)
    changed = live != rec["sha256"]
    if changed:
        _copy_in(saved, path)
    if e["previous"]:
        e["previous"].pop()
        saved.unlink(missing_ok=True)
    manifest[path.name] = e
    _save(path.parent, manifest)
    return {"file": path.name, "restored": rec, "changed": changed}


def revert_all(folder):
    """revert_to_retail() every file in `folder` that has a backup.
    Returns [{"file", "restored", "changed"} or {"file", "error"}]."""
    out = []
    for b in list_backups(folder):
        try:
            out.append(revert_to_retail(b["path"]))
        except BackupError as ex:
            out.append({"file": b["file"], "error": str(ex)})
    return out


# ----------------------------------------------------------------------- cli
def cmd_list(folder, as_json=False):
    rows = list_backups(folder)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print(f"no Seam Ripper backups in {Path(folder)}")
        return
    print(f"{len(rows)} file(s) backed up in {backup_dir(folder)}\n")
    print(f"  {'file':<36} {'size':>11}  {'backed up':<19}  earlier  live file")
    for r in rows:
        print(f"  {r['file']:<36} {r['retail']['size']:>11,}  "
              f"{r['retail'].get('time') or '?':<19}  {len(r['previous']):>7}  "
              f"{'retail' if r['current'] == 'retail' else r['current']}")


def cmd_revert(path, previous=False, as_json=False):
    """`path` is a file, or a folder meaning every backed-up file in it."""
    p = Path(path)
    try:
        if p.is_dir():
            res = revert_all(p)
        else:
            res = [(restore_previous if previous else revert_to_retail)(p)]
    except BackupError as e:
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(f"revert: {e}")
    if as_json:
        print(json.dumps({"ok": not any("error" in r for r in res),
                          "results": res}, indent=2))
    else:
        if not res:
            print(f"no Seam Ripper backups in {p}")
        what = "the previous version" if previous else "its retail backup"
        for r in res:
            if "error" in r:
                print(f"  {r['file']}: {r['error']}")
            elif r["changed"]:
                print(f"restored {r['file']} from {what} "
                      f"({Path(r['restored']['backup']).name})")
            else:
                print(f"{r['file']} already matches {what}; nothing to do")
    if any("error" in r for r in res):
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list the backups kept for a folder")
    pl.add_argument("folder")
    pl.add_argument("--json", action="store_true")
    pr = sub.add_parser("revert", help="restore a .lu (or every .lu in a "
                        "folder) from its retail backup")
    pr.add_argument("path")
    pr.add_argument("--previous", action="store_true",
                    help="step back one version instead of going to retail")
    pr.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a.folder, a.json)
    else:
        cmd_revert(a.path, a.previous, a.json)


if __name__ == "__main__":
    main()
