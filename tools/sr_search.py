#!/usr/bin/env python3
"""Search the Lua scripts of a whole folder of .lu containers."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

INDEX_VERSION = 1

# Decompiled NB1 text depends on the decompiler and on the name dictionaries,
# so cached text is filed under a signature of those files: improve the names
# and the next index rebuilds the NB1 text with them. PiP text is copied out
# of the container as it is and only depends on the extractor.
NB1_DEPS = ("nbdec.py", "nblua.py", "lua_decompile.py", "lua_recompile.py",
            "nb_names.json", "nb_text.json")
PIP_DEPS = ("pip_scripts.py",)


def default_cache_dir():
    """%LOCALAPPDATA%\\SeamRipper\\cache on Windows, ~/.cache/SeamRipper
    elsewhere; SEAMRIPPER_CACHE/search when that variable is set (tests)."""
    env = os.environ.get("SEAMRIPPER_CACHE")
    if env:
        return Path(env) / "search"
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SeamRipper" / "cache"
    return Path.home() / ".cache" / "SeamRipper"


def _signature(files):
    h = hashlib.sha1()
    for n in files:
        p = HERE / n
        h.update(n.encode())
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def signatures():
    """{"nb1": sig, "pip": sig} for the tool files the cached text depends on."""
    return {"nb1": "nb1-" + _signature(NB1_DEPS),
            "pip": "pip-" + _signature(PIP_DEPS)}


def containers_in(folder, exclude=()):
    """The .lu files a search covers: every one under the folder, in its
    subfolders too (a game keeps them in lu and uh folders), except in hidden
    folders such as .seamripper, whose backups are .lu files as well. Sorted
    by relative path."""
    folder = Path(folder)
    skip = {x.lower() for x in exclude}
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for n in files:
            if n.lower().endswith(".lu"):
                f = Path(root) / n
                if n.lower() not in skip and _rel(folder, f).lower() not in skip:
                    found.append(f)
    return sorted(found, key=lambda f: _rel(folder, f).lower())


def _rel(folder, f):
    """A container's key in the index: its path under the folder, with /."""
    return Path(f).relative_to(folder).as_posix()


class Cache:
    """One cache folder: a manifest per searched folder, plus the script text
    itself, stored once per distinct script and shared by every folder."""

    def __init__(self, cache_dir=None):
        self.root = Path(cache_dir) if cache_dir else default_cache_dir()
        self.sigs = signatures()

    def manifest_path(self, folder):
        key = os.path.normcase(str(Path(folder).resolve()))
        return (self.root / "folders" /
                (hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json"))

    def load_manifest(self, folder):
        p = self.manifest_path(folder)
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            if m.get("version") == INDEX_VERSION:
                return m
        except (OSError, ValueError):
            pass
        return {"version": INDEX_VERSION, "folder": str(Path(folder).resolve()),
                "containers": {}}

    def save_manifest(self, folder, m):
        p = self.manifest_path(folder)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=0), encoding="utf-8")
        os.replace(tmp, p)

    def text_path(self, game, digest):
        return self.root / "scripts" / self.sigs[game] / digest[:2] / \
            (digest + ".lua")

    def declined_path(self, game, digest):
        return self.text_path(game, digest).with_suffix(".declined")

    def has(self, game, digest):
        return (self.text_path(game, digest).exists()
                or self.declined_path(game, digest).exists())

    def put(self, game, digest, text):
        p = self.text_path(game, digest) if text is not None \
            else self.declined_path(game, digest)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(text or "", encoding="utf-8", newline="\n")
        os.replace(tmp, p)

    def get(self, game, digest):
        """The script's text, or None if it was declined or is not cached."""
        try:
            return self.text_path(game, digest).read_text(encoding="utf-8")
        except OSError:
            return None


def _script_text(game, s, chunk, names, texts):
    """The same text `lu_lua.py export` writes for this script, or None."""
    import lu_lua
    if game == lu_lua.PIP or not s.compiled:
        import pip_scripts
        got = pip_scripts.extract_lua(chunk)
        return got[1] if got else None
    import nblua
    src = nblua.nbdec_source(chunk, names, texts)
    return None if src is None else (
        nblua.BACKEND_MARK.format("nbdec") + "\n" + src + "\n")


def _fresh(entry, f, st, cache):
    if entry is None or entry.get("size") != st.st_size or \
            entry.get("mtime_ns") != st.st_mtime_ns:
        return False
    game = entry.get("game")
    return all(cache.has(game, s["digest"]) for s in entry.get("scripts", ()))


def index_folder(folder, cache_dir=None, exclude=(), progress=None):
    """Bring the folder's cached script text up to date and return a summary.

    Only containers whose size or modification time changed since the last
    run (or whose text was made by other tool versions) are opened again.
    progress, if given, is called as progress(done, total, container_name,
    status) where status is "cached", "read", "no scripts" or "error: ...".

    Returns {"folder", "cache", "containers", "with_scripts", "scripts",
    "distinct", "reread", "declined", "errors", "seconds"}."""
    import lu_lua
    from naughty_lu import LuFile
    t0 = time.time()
    cache = Cache(cache_dir)
    m = cache.load_manifest(folder)
    old = m["containers"]
    new = {}
    base = Path(folder)
    files = containers_in(base, exclude)
    names = texts = None
    reread = errors = 0
    last_save = time.time()
    for i, f in enumerate(files, 1):
        st = f.stat()
        rel = _rel(base, f)
        entry = old.get(rel)
        if _fresh(entry, f, st, cache):
            new[rel] = entry
            if progress:
                progress(i, len(files), rel, "cached")
            continue
        reread += 1
        entry = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                 "game": None, "scripts": []}
        try:
            lu = LuFile(str(f))
            game = lu_lua.game_of(lu)
            entry["game"] = game
            for s in lu_lua.scripts(lu):
                chunk = bytes(lu.chunk(lu.records[s.index]))
                digest = hashlib.sha1(chunk).hexdigest()[:20]
                if not cache.has(game, digest):
                    if names is None and game == lu_lua.NB1:
                        import nb_names
                        names, texts = nb_names.load(), nb_names.load_text()
                    cache.put(game, digest,
                              _script_text(game, s, chunk, names, texts))
                entry["scripts"].append({"index": s.index, "name": s.name,
                                         "digest": digest})
            status = (f"read, {len(entry['scripts'])} script(s)"
                      if entry["scripts"] else "no scripts")
        except Exception as e:  # a damaged or foreign file: note it, go on
            entry["error"] = str(e) or type(e).__name__
            status = f"error: {entry['error']}"
            errors += 1
        new[rel] = entry
        if progress:
            progress(i, len(files), rel, status)
        if time.time() - last_save > 10:
            m["containers"] = {**old, **new}
            cache.save_manifest(folder, m)
            last_save = time.time()
    m["containers"] = new
    cache.save_manifest(folder, m)
    digests = {(e["game"], s["digest"]) for e in new.values()
               for s in e["scripts"]}
    declined = sum(1 for g, d in digests if cache.get(g, d) is None)
    return {"folder": str(Path(folder).resolve()), "cache": str(cache.root),
            "containers": len(new),
            "with_scripts": sum(1 for e in new.values() if e["scripts"]),
            "scripts": sum(len(e["scripts"]) for e in new.values()),
            "distinct": len(digests), "reread": reread, "declined": declined,
            "errors": errors, "seconds": round(time.time() - t0, 2)}


def _matcher(pattern, regex, case):
    if regex:
        flags = 0 if case else re.IGNORECASE
        rx = re.compile(pattern, flags)
        # the whole-text pre-test needs ^ and $ to work per line
        return (lambda line: rx.search(line) is not None,
                re.compile(pattern, flags | re.MULTILINE))
    if case:
        return (lambda line: pattern in line), None
    low = pattern.lower()
    return (lambda line: low in line.lower()), None


def find(folder, pattern, regex=False, case=False, cache_dir=None,
         exclude=(), group=True, limit=None, progress=None, update=True):
    """Yield every line of every script in the folder that matches.

    Each hit is a dict {"container" (path under the folder, with /),
    "container_path", "game", "index",
    "name", "line" (1-based, as the file `lu_lua.py read` writes), "text",
    "digest", "source" (the cached .lua file), "also"}. With group=True
    (default) a script that is identical in several containers is reported
    once, under the first container by name, and "also" lists the others as
    [{"container", "index"}]; with group=False every copy is its own hit and
    "also" is []. limit stops after that many hits. update=True brings the
    index up to date first (progress is passed to index_folder)."""
    if update:
        index_folder(folder, cache_dir, exclude, progress)
    cache = Cache(cache_dir)
    m = cache.load_manifest(folder)
    match, rx = _matcher(pattern, regex, case)
    base = Path(m["folder"])
    skip = {x.lower() for x in exclude}
    where = {}                # (game, digest) -> [(container, index, name)]
    order = []
    for cont in sorted(m["containers"]):
        if cont.lower() in skip or cont.rsplit("/", 1)[-1].lower() in skip:
            continue
        e = m["containers"][cont]
        for s in sorted(e["scripts"], key=lambda s: s["index"]):
            key = (e["game"], s["digest"])
            if key not in where:
                where[key] = []
                order.append(key)
            where[key].append((cont, s["index"], s["name"]))
    n = 0
    for key in order:
        game, digest = key
        text = cache.get(game, digest)
        if text is None:
            continue
        # some PiP scripts end lines with CRLF or a bare CR
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # cheap whole-text test first; almost every script has no hit
        if rx is not None:
            if not rx.search(text):
                continue
        elif (pattern not in text) if case else \
                (pattern.lower() not in text.lower()):
            continue
        locs = where[key] if not group else where[key][:1]
        for ln, line in enumerate(text.split("\n"), 1):
            if not match(line):
                continue
            for cont, idx, name in locs:
                also = ([{"container": c, "index": i}
                         for c, i, _ in where[key][1:]] if group else [])
                yield {"container": cont,
                       "container_path": str(base / cont), "game": game,
                       "index": idx, "name": name, "line": ln, "text": line,
                       "digest": digest,
                       "source": str(cache.text_path(game, digest)),
                       "also": also}
                n += 1
                if limit is not None and n >= limit:
                    return


# --------------------------------------------------------------------- cli
def _progress_printer(as_json):
    def show(done, total, name, status):
        if as_json:
            print(json.dumps({"type": "progress", "done": done, "total": total,
                              "container": name, "status": status}),
                  flush=True)
        elif status != "cached" or done == total or done % 100 == 0:
            print(f"  [{done}/{total}] {name}: {status}", flush=True)
    return show


def _summary_line(s):
    return (f"indexed {s['containers']} container(s) in {s['seconds']}s: "
            f"{s['scripts']} scripts in {s['with_scripts']} containers, "
            f"{s['distinct']} distinct; {s['reread']} container(s) read this "
            f"time, the rest came from the cache")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("folder", help="folder of .lu files; its subfolders are "
                       "searched too, except hidden ones")
        p.add_argument("--cache", default=None,
                       help=f"cache folder (default {default_cache_dir()})")
        p.add_argument("--exclude", nargs="*", default=[], metavar="NAME.lu",
                       help="container names to leave out (e.g. modded "
                            "copies)")
        p.add_argument("--json", action="store_true",
                       help="one JSON object per line: progress, hits, and a "
                            "final summary")

    pi = sub.add_parser("index", help="build or refresh the script cache")
    common(pi)
    pf = sub.add_parser("find", help="search every script for text")
    common(pf)
    pf.add_argument("pattern")
    pf.add_argument("--regex", action="store_true",
                    help="the pattern is a Python regular expression")
    pf.add_argument("--case", action="store_true", help="match case")
    pf.add_argument("--all", action="store_true",
                    help="list every container's copy of a script, not just "
                         "the first")
    pf.add_argument("--limit", type=int, default=None,
                    help="stop after this many hits")
    a = ap.parse_args()

    if not Path(a.folder).is_dir():
        sys.exit(f"not a folder: {a.folder}")
    show = _progress_printer(a.json)
    if a.cmd == "index":
        s = index_folder(a.folder, a.cache, a.exclude, show)
        if a.json:
            print(json.dumps({"type": "done", **s}))
        else:
            print(_summary_line(s))
            if s["declined"]:
                print(f"  {s['declined']} script(s) could not be decompiled "
                      f"and are not searchable")
            if s["errors"]:
                print(f"  {s['errors']} file(s) could not be read (listed "
                      f"above)")
            print(f"  cache: {s['cache']}")
        return

    if a.regex:
        try:
            re.compile(a.pattern)
        except re.error as e:
            sys.exit(f"bad regular expression: {e}")
    s = index_folder(a.folder, a.cache, a.exclude, show)
    if not a.json:
        print(_summary_line(s))
    hits = scripts = 0
    last = None
    for h in find(a.folder, a.pattern, a.regex, a.case, a.cache, a.exclude,
                  group=not a.all, limit=a.limit, update=False):
        hits += 1
        if a.json:
            print(json.dumps({"type": "hit", **h}, ensure_ascii=False),
                  flush=True)
            continue
        here = (h["container"], h["index"])
        if here != last:
            scripts += 1
            more = f"  (+{len(h['also'])} identical copies)" if h["also"] \
                else ""
            print(f"\n{h['container']}  #{h['index']}  {h['name']}{more}")
            last = here
        print(f"  {h['line']:>6}: {h['text'].strip()}")
    if a.json:
        print(json.dumps({"type": "done", "hits": hits, **s}))
    else:
        print(f"\n{hits} matching line(s)" +
              (f" in {scripts} script(s)" if hits else "") +
              (" (limit reached)" if a.limit and hits >= a.limit else ""))


if __name__ == "__main__":
    main()
