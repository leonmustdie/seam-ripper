#!/usr/bin/env python3
"""Install shipped .lu files into a restuff build and start the game."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXE_NAME = "restuff.exe"
LOG_NAME = "restuff_log.txt"
CRASH_NAME = "restuff_crash.txt"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Backups are sr_backup's job, so every tool that overwrites a game file
# keeps its originals in the same place, in the same way.
import sr_backup  # noqa: E402


class LaunchError(Exception):
    """The build folder or a file could not be used; the message says why."""


def locate(build):
    """The parts of a restuff build -> {"build", "exe", "assets", "lu",
    "backups"} as strings. `build` is the folder holding restuff.exe (or the
    exe itself); the game's .lu files are in its assets/lu folder."""
    b = Path(build)
    if b.is_file():
        b = b.parent
    exe = b / EXE_NAME
    if not exe.is_file():
        raise LaunchError(f"no {EXE_NAME} in {b}; pick the folder the "
                          f"restuff build wrote it to")
    lu = b / "assets" / "lu"
    if not lu.is_dir():
        raise LaunchError(f"{b} has {EXE_NAME} but no assets\\lu folder "
                          f"with the game files")
    return {"build": str(b), "exe": str(exe), "assets": str(b / "assets"),
            "lu": str(lu), "backups": str(sr_backup.backup_dir(lu))}


def info(build):
    """locate() plus "lu_count" (the game's .lu files) and "backups_list"
    (sr_backup.list_backups of the game folder: one dict per saved original,
    with "file" and "current": "retail" | "modified" | "missing")."""
    d = locate(build)
    d["lu_count"] = sum(1 for _ in Path(d["lu"]).glob("*.lu"))
    d["backups_list"] = sr_backup.list_backups(d["lu"])
    return d


def _copy(src, dest):
    # through a temporary name, so a failed copy never leaves half a file
    tmp = dest.with_name(dest.name + ".srtmp")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _same(a, b):
    if a.stat().st_size != b.stat().st_size:
        return False
    return a.read_bytes() == b.read_bytes()


def install(build, files, log=print, allow_new=False):
    """Copy shipped .lu files into the build's assets/lu folder.

    Before a game file is replaced, sr_backup saves it: the first time as the
    retail copy, which is never overwritten, later as a previous version. A
    file the game does not have is refused unless allow_new=True (a misspelt
    name would otherwise do nothing in game). Nothing is copied unless every
    file passes the checks. Returns [{"file", "dest", "backup" (path or
    None), "created": "retail" | "previous" | None, "changed": False when
    the game already had these exact bytes and nothing was touched}]."""
    d = locate(build)
    lu = Path(d["lu"])
    srcs = [Path(f) for f in files]
    seen = {}
    for s in srcs:
        if not s.is_file():
            raise LaunchError(f"file not found: {s}")
        if s.resolve().parent == lu.resolve():
            raise LaunchError(f"{s.name} is already in the game folder")
        if not (lu / s.name).exists() and not allow_new:
            raise LaunchError(f"the game has no {s.name}; check the name "
                              f"(only files the game already has are "
                              f"installed)")
        other = seen.setdefault(s.name.lower(), s)
        if other is not s:
            raise LaunchError(f"{other} and {s} are both named {s.name}; "
                              f"the game folder can hold only one")
    out = []
    for s in srcs:
        dest = lu / s.name
        if dest.is_file() and _same(s, dest):
            log(f"{s.name} is already installed")
            out.append({"file": s.name, "dest": str(dest), "backup": None,
                        "created": None, "changed": False})
            continue
        b = sr_backup.backup_before_overwrite(dest)
        created = b["created"] if b else None
        if created == "retail":
            log(f"saved the original {s.name} to {Path(d['backups'])}")
        try:
            _copy(s, dest)
        except PermissionError:
            raise LaunchError(f"could not replace {dest}; is the game still "
                              f"running?")
        log(f"installed {s.name} -> {dest}")
        saved = None
        if created == "retail":
            saved = b["retail"]["backup"]
        elif created == "previous":
            saved = b["previous"][-1]["backup"]
        out.append({"file": s.name, "dest": str(dest), "backup": saved,
                    "created": created, "changed": True})
    return out


def restore(build, names=None, log=print):
    """Put the retail copies back (all of them, or just `names`). The backups
    are kept, and the version being replaced is saved as a previous one.
    Returns the file names that were looked at."""
    lu = Path(locate(build)["lu"])
    have = [r["file"] for r in sr_backup.list_backups(lu)]
    want = have if not names else [Path(n).name for n in names]
    missing = [n for n in want if n not in have]
    if missing:
        raise LaunchError("no saved original for " + ", ".join(missing))
    for n in want:
        try:
            r = sr_backup.revert_to_retail(lu / n)
        except sr_backup.BackupError as e:
            raise LaunchError(str(e))
        log(f"restored the original {n}" if r["changed"]
            else f"{n} was already the original")
    return want


def log_hint(build):
    """One line saying where the game's logs go."""
    return (f"The game's Lua errors are written to {LOG_NAME}; if it crashes, "
            f"{CRASH_NAME} appears next to {EXE_NAME} ({Path(build)}).")


def launch(build, popen=subprocess.Popen):
    """Start restuff.exe on its own, detached from Seam Ripper, with the
    build folder as its working folder. The game only writes its Lua error
    log when it is given --log_file on the command line. Returns {"pid",
    "argv", "log", "crash"}."""
    d = locate(build)
    b = Path(d["build"])
    log = b / LOG_NAME
    argv = [d["exe"], "--log_file", str(log)]
    kw = {"cwd": d["build"], "stdin": subprocess.DEVNULL,
          "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw["start_new_session"] = True
    try:
        proc = popen(argv, **kw)
    except OSError as e:
        raise LaunchError(f"could not start {d['exe']}: {e}")
    return {"pid": proc.pid, "argv": argv, "log": str(log),
            "crash": str(b / CRASH_NAME)}


# --------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name, help):
        p = sub.add_parser(name, help=help)
        p.add_argument("build", help="restuff build folder (holding "
                       "restuff.exe)")
        p.add_argument("--json", action="store_true",
                       help="print a JSON result as the last line")
        return p
    cmd("info", "show where the build's exe and game files are")
    pn = cmd("install", "copy shipped .lu files into the build (originals "
             "are backed up first)")
    pn.add_argument("files", nargs="+")
    pn.add_argument("--allow-new", action="store_true",
                    help="also copy files the game does not already have")
    pr = cmd("restore", "put the original files back")
    pr.add_argument("names", nargs="*", help="file names (default: all)")
    pl = cmd("run", "start the game, optionally installing files first")
    pl.add_argument("--install", nargs="+", default=[], metavar="FILE.lu")
    a = ap.parse_args()
    log = print
    try:
        if a.cmd == "info":
            d = info(a.build)
            if a.json:
                print(json.dumps(d))
                return
            print(f"game:       {d['exe']}\ngame files: {d['lu']} "
                  f"({d['lu_count']} .lu)\nbackups:    {d['backups']} "
                  f"({len(d['backups_list'])} saved)")
            for r in d["backups_list"]:
                print(f"  {r['file']:<40} game copy is {r['current']}")
        elif a.cmd == "install":
            r = install(a.build, a.files, log, a.allow_new)
            if a.json:
                print(json.dumps(r))
        elif a.cmd == "restore":
            r = restore(a.build, a.names, log)
            if not r:
                log("nothing to restore: no originals have been saved")
            if a.json:
                print(json.dumps(r))
        else:
            r = install(a.build, a.install, log) if a.install else []
            g = launch(a.build)
            log(f"started {EXE_NAME} (process {g['pid']})")
            log(log_hint(a.build))
            if a.json:
                print(json.dumps({"installed": r, **g}))
    except LaunchError as e:
        sys.exit(f"{a.cmd}: {e}")


if __name__ == "__main__":
    main()
