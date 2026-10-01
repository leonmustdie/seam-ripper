#!/usr/bin/env python3
"""Check that every container and script in a game folder survives Seam Ripper's rebuild unchanged."""
import argparse
import collections
import contextlib
import hashlib
import io
import json
import sys
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import nblua                                   # noqa: E402
import proto360                                # noqa: E402
from lu_chunk_replace import relayout          # noqa: E402
from naughty_lu import LuFile                  # noqa: E402

_names = _texts = _luac = None


def _init():
    global _names, _texts, _luac
    import nb_names
    _names, _texts = nb_names.load(), nb_names.load_text()
    _luac = nblua.find_luac(None)


def scan_file(path):
    """Rebuild the container with nothing changed; collect its scripts."""
    try:
        lu = LuFile(path)
        recs = [r for r in lu.records if not r.external and r.size > 0]
        problem = None
        if recs:
            first = min(recs, key=lambda r: (r.offset, r.index))
            image, offsets = relayout(lu, {first.index: lu.chunk(first)})
            moved = [i for i, o in offsets.items() if o != lu.records[i].offset]
            if bytes(image) != lu.image:
                problem = "rebuilt image differs"
            elif moved:
                problem = f"records moved: {moved[:5]}"
        scripts = {}
        for r, name, chunk in nblua.script_records(lu):
            scripts.setdefault(hashlib.sha1(chunk).hexdigest(),
                               (name, r.index, bytes(chunk)))
        return str(path), problem, scripts
    except Exception as e:
        return str(path), f"{type(e).__name__}: {e}", {}


def check_script(item):
    """Read the script the way Ship does, compile it back, compare."""
    key, chunk = item
    tmp = Path(nblua.TMPDIR) / "audit.lua"
    try:
        src = nblua.nbdec_source(chunk, _names, _texts)
        if src is None:
            return key, "declined", []
        tmp.write_text(src, encoding="utf-8", newline="\n")
        with contextlib.redirect_stdout(io.StringIO()) as notes:
            img = nblua.compile_nbdec(tmp, _luac, chunk)
        orig = nblua.chunk_image(chunk)
        if img == orig:
            return key, "exact", notes.getvalue().splitlines()
        a, b = proto360.decode_logic(orig), proto360.decode_logic(img)
        if a == b:
            return key, "same code", []
        if set(a) != set(b):
            return key, "function list differs", sorted(set(a) ^ set(b))
        return key, "code differs", sorted(p for p in a if a[p] != b[p])
    except Exception as e:
        return key, "error", [f"{type(e).__name__}: {e}"[:300]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="folder of retail .lu files")
    ap.add_argument("--skip", nargs="*", default=[], help="file names to leave out")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--report", help="write the full results here as JSON")
    a = ap.parse_args()

    files = [f for f in sorted(Path(a.folder).glob("*.lu")) if f.name not in a.skip]
    containers, scripts, where = {}, {}, collections.defaultdict(list)
    with Pool(a.jobs, initializer=_init) as pool:
        for path, problem, found in pool.imap_unordered(scan_file, files, chunksize=4):
            containers[path] = problem
            for key, (name, index, chunk) in found.items():
                scripts.setdefault(key, (name, chunk))
                where[key].append(f"{Path(path).name}#{index}")
        bad = {p: m for p, m in containers.items() if m}
        print(f"containers: {len(files)} rebuilt, {len(bad)} changed")
        for p, m in sorted(bad.items()):
            print(f"  {Path(p).name}: {m}")

        results = {}
        items = [(k, c) for k, (_, c) in scripts.items()]
        for key, status, detail in pool.imap_unordered(check_script, items, chunksize=8):
            results[key] = (status, detail)

    counts = collections.Counter(s for s, _ in results.values())
    print(f"scripts: {len(results)} distinct (from {sum(map(len, where.values()))} copies)")
    for status, n in counts.most_common():
        print(f"  {status:<22} {n}")
    for key, (status, detail) in sorted(results.items(), key=lambda kv: scripts[kv[0]][0]):
        if status not in ("exact", "same code"):
            print(f"  {scripts[key][0] or '?'} ({where[key][0]}): {status} {detail[:4]}")
    if a.report:
        Path(a.report).write_text(json.dumps({
            "containers": containers,
            "scripts": [{"name": scripts[k][0], "in": where[k], "status": s,
                         "detail": d} for k, (s, d) in results.items()],
        }, indent=1), encoding="utf-8")
    return 1 if bad or any(s not in ("exact", "same code") for s in counts) else 0


if __name__ == "__main__":
    sys.exit(main())
