#!/usr/bin/env python3
"""One-shot animation extraction: .lu folder -> skinned GLBs with baked clips.

usage: anim_extract.py <lu folder and/or .lu files> --game nb1|pip -o <out> [options]

Runs the whole chain in one process so the GUI needs a single button:

  nb1:  decode every .lu  ->  lu_corpus      (about 7 min for the retail set)
  pip:  decode every .lu  ->  pip_scripts extract  ->  pip_corpus
        (about 70 min; --plan stops before the bake and prints which
        character gets which clips)

Output layout under <out>:
  decoded/      one directory per .lu (naughty_lu extract layout)
  scripts/      PiP only: Lua source rebuilt from the animation chunks
  animations/   GLBs, rigs.csv, clips.csv, clip_names.tsv, summary.txt

Each stage is the existing tool, called with the arguments documented in
HANDOFF.md, so results are identical to running the scripts by hand.
Decoding skips units that already have a manifest.tsv unless --redecode.
"""
import argparse
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

VOCAB_NAME = "nb1_anim_vocab.txt"
SOURCES_NAME = "nb1_anim_sources.tsv"
NL, TAB = chr(10), chr(9)


def say(msg=""):
    print(msg, flush=True)


def find_vocab():
    """The NB1 name list pip_names uses. Next to this script when run from
    source; flat in the bundle root when frozen."""
    cands = [HERE / VOCAB_NAME]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / VOCAB_NAME)
    for c in cands:
        if c.exists():
            return c
    return None


def collect(sources):
    """The .lu files named by a mix of files and folders."""
    files = []
    for s in sources:
        files += [s] if s.is_file() else sorted(s.glob("*.lu"))
    return files


def find_data(name):
    """A data file next to this script, or flat in the bundle root when frozen."""
    cands = [HERE / name]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / name)
    return next((c for c in cands if c.exists()), None)


def make_sources_index(decoded_root, out_path):
    """Scan every decoded unit and write which container holds what:
         clips  <rig> <unit> <n>      n clips for that skeleton hash
         map    <rig> <foreign> <unit> an anim-set that retargets <foreign> onto <rig>
         skel   <rig> <label> <unit>  the skeleton itself
    One-off, from a whole decoded game; the result ships as nb1_anim_sources.tsv."""
    import lu_corpus
    reg = lu_corpus.Registry()
    units = sorted(p for p in Path(decoded_root).iterdir() if p.is_dir())
    seen_maps = set()
    for i, u in enumerate(units):
        reg.scan_unit(u)
        for ad in lu_corpus.ANIMSET_DIRS:
            for p in sorted((u / ad).glob("*.bin")) if (u / ad).is_dir() else []:
                own, maps = lu_corpus.animset_retarget_maps(p.read_bytes())
                for f in maps if own is not None else ():
                    seen_maps.add((own, f, u.name))
        if (i + 1) % 100 == 0:
            say(f"scanned {i + 1}/{len(units)}")
    per = {}
    for (nh, rig), srcs in reg.clip_sources.items():
        for src in srcs:
            per.setdefault((rig, src.split("/", 1)[0]), set()).add(nh)
    rows = [("clips", f"{r:08x}", u, ",".join(f"{h:08x}" for h in sorted(hs)))
            for (r, u), hs in per.items()]
    rows += [("map", f"{o:08x}", f"{f:08x}", u) for o, f, u in seen_maps]
    for rig, r in reg.rigs.items():
        label = reg.label(rig)
        for u in sorted(set(r["units"])):
            rows.append(("skel", f"{rig:08x}", label, u))
    rows.sort()
    Path(out_path).write_text(NL.join(TAB.join(r) for r in rows) + NL, encoding="utf-8")
    say(f"wrote {len(rows)} rows from {len(units)} units -> {out_path}")


def load_sources_index():
    path = find_data(SOURCES_NAME)
    if path is None:
        return None
    idx = {"clips": {}, "map": {}, "skel": {}}
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split(TAB)
        if len(t) != 4:
            continue
        if t[0] == "clips":
            idx["clips"].setdefault(t[1], {})[t[2]] = frozenset(t[3].split(","))
        elif t[0] == "map":
            idx["map"].setdefault((t[1], t[2]), set()).add(t[3])
        elif t[0] == "skel":
            idx["skel"].setdefault(t[1], (t[2], set()))[1].add(t[3])
    return idx


def reachable(idx, rig, units):
    """(foreign_rig, clip) pairs that end up on `rig` when exactly `units` are loaded:
    its own clips, plus clips of any skeleton whose retarget table is in `units`."""
    # the baker retargets only skeletons that are absent from the run; one that is
    # present gets its own GLB instead
    srcs = {rig} | {f for (o, f), mu in idx["map"].items()
                    if o == rig and mu & units and not (idx["skel"].get(f, ("", set()))[1] & units)}
    out = set()
    for f in srcs:
        for u, names in idx["clips"].get(f, {}).items():
            if u in units:
                out |= {(f, n) for n in names}
    return out


def needs_report(anim_dir, decoded):
    """After an NB1 bake: which other containers would add clips to each exported
    skeleton, fewest files first. Written to <anim_dir>/needs.txt and printed."""
    import csv
    idx = load_sources_index()
    if idx is None:
        return
    have = frozenset(p.name for p in decoded.iterdir() if p.is_dir())
    try:
        rigs = list(csv.DictReader(open(anim_dir / "rigs.csv", encoding="utf-8")))
    except OSError:
        return
    every = {u for per in idx["clips"].values() for u in per} | \
        {u for mu in idx["map"].values() for u in mu}
    lines = []
    for r in rigs:
        rig = r["rig"]
        label = r["label"] or rig
        mine = {u for u in every if u not in have}
        # only containers that can matter for this skeleton
        relevant = {u for per in (idx["clips"].get(f, {}) for f in
                    {rig} | {f for (o, f) in idx["map"] if o == rig}) for u in per} | \
            {u for (o, _f), mu in idx["map"].items() if o == rig for u in mu}
        cands = mine & relevant
        now = reachable(idx, rig, have)
        steps, cur, loaded = [], now, set(have)
        while len(steps) < 40:
            best = None
            for u in sorted(cands - (loaded - have)):
                g = len(reachable(idx, rig, frozenset(loaded | {u})) - cur)
                if best is None or g > best[1]:
                    best = (u, g)
            if best is None or best[1] == 0:
                break
            loaded.add(best[0])
            cur = reachable(idx, rig, frozenset(loaded))
            steps.append((best[0], best[1], len(cur)))
        if not steps:
            continue
        lines.append(f"{label} ({rig}): {len(now)} clips from the files you chose, "
                     f"up to {len(cur)} with more files.")
        for u, g, running in steps[:6]:
            lines.append(f"    add {u}.lu: +{g} clips (then {running})")
        if len(steps) > 6:
            lines.append(f"    ...and {len(steps) - 6} more files for the last "
                         f"{len(cur) - steps[5][2]} clips")
    if lines:
        text = ("Files that would add clips to the skeletons below, biggest gain first:"
                + NL + NL.join(lines) + NL)
    else:
        text = ("Nothing missing: every container that holds clips for these skeletons "
                "was included." + NL)
    (anim_dir / "needs.txt").write_text(text, encoding="utf-8")
    say("[needs] " + text.rstrip())


def decode_all(sources, decoded, redecode):
    import naughty_lu
    files = collect(sources)
    if not files:
        say("no .lu files in " + ", ".join(map(str, sources)))
        return False
    decoded.mkdir(parents=True, exist_ok=True)
    say(f"[1] decode {len(files)} .lu -> {decoded}")
    t0 = time.time()
    ok = fail = skipped = 0
    for i, p in enumerate(files):
        if not redecode and (decoded / p.stem / "manifest.tsv").exists():
            skipped += 1
            continue
        try:
            naughty_lu.cmd_extract(Namespace(files=[str(p)], out=str(decoded),
                                             names=None))
            ok += 1
        except Exception as e:
            fail += 1
            say(f"FAIL {p.name}: {e!r}")
            traceback.print_exc()
        if (i + 1) % 50 == 0:
            say(f"--- {i + 1}/{len(files)} done, {time.time() - t0:.0f}s")
    say(f"decode done: ok={ok} fail={fail} skipped={skipped} "
        f"in {time.time() - t0:.0f}s")
    # a decode failure costs one unit, not the run; but zero usable units is fatal
    return (ok + skipped) > 0


def run_tool(modname, argv):
    """Call another tool's main() with a private sys.argv."""
    import importlib
    mod = importlib.import_module(modname)
    saved = sys.argv
    sys.argv = [modname] + [str(a) for a in argv]
    try:
        mod.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = saved


def main():
    # The frozen EXE's --tool shim calls main() and ignores its return value,
    # so a failure must surface as a SystemExit to give the GUI a real exit code.
    rc = _run()
    if rc:
        sys.exit(rc)


def _run():
    try:                                   # stream line by line into the GUI log
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    if len(sys.argv) == 4 and sys.argv[1] == "--make-sources":     # maintainers only
        make_sources_index(sys.argv[2], sys.argv[3])
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lu_dir", nargs="+",
                    help="folder holding the game's .lu files, and/or individual .lu files")
    ap.add_argument("--game", required=True, choices=["nb1", "pip"])
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--rigs", help="only these rig hashes (hex, comma-separated)")
    ap.add_argument("--rate", type=float, default=30.0, help="clip sample rate")
    ap.add_argument("--no-scale", action="store_true",
                    help="do not export scale channels")
    ap.add_argument("--redecode", action="store_true",
                    help="decode every .lu again even if already decoded")
    # NB1 only
    ap.add_argument("--no-retarget", action="store_true",
                    help="nb1: do not bake clips of absent rigs through the retarget maps")
    ap.add_argument("--skip-empty-rigs", action="store_true",
                    help="nb1: no GLB for rigs that end with zero baked clips")
    # PiP only
    ap.add_argument("--all-rigs", action="store_true",
                    help="pip: also write a static GLB for rigs no clip plays on")
    ap.add_argument("--plan", action="store_true",
                    help="pip: print the character/clip assignment and stop")
    a = ap.parse_args()

    sources, out = [Path(x) for x in a.lu_dir], Path(a.out)
    for s in sources:
        if not (s.is_dir() or (s.is_file() and s.suffix.lower() == ".lu")):
            say(f"not a folder or .lu file: {s}")
            return 2
    decoded, scripts, anim = out / "decoded", out / "scripts", out / "animations"

    if not decode_all(sources, decoded, a.redecode):
        return 1

    common = ["--rate", a.rate]
    if a.rigs:
        common += ["--rigs", a.rigs]
    if a.no_scale:
        common += ["--no-scale"]

    if a.game == "nb1":
        say(f"[2] bake clips -> {anim}")
        args = [decoded, "-o", anim] + common
        if a.no_retarget:
            args += ["--no-retarget"]
        if a.skip_empty_rigs:
            args += ["--skip-empty-rigs"]
        rc = run_tool("lu_corpus", args)
        if rc == 0:
            try:
                needs_report(anim, decoded)
            except Exception as e:               # advice only; never fail the bake for it
                say(f"(needs report skipped: {e!r})")
        return rc

    say(f"[2] rebuild Lua source -> {scripts}")
    rc = run_tool("pip_scripts", ["extract", decoded, "-o", scripts])
    if rc:
        say(f"pip_scripts failed (exit {rc})")
        return rc
    vocab = find_vocab()
    if vocab is None:
        say(f"warning: {VOCAB_NAME} not found, clip names will be fewer")
    say(f"[3] {'plan' if a.plan else 'bake clips'} -> {anim}")
    args = [decoded, "--scripts", scripts, "-o", anim] + common
    if vocab:
        args += ["--vocab", vocab]
    if a.all_rigs:
        args += ["--all-rigs"]
    if a.plan:
        args += ["--plan"]
    return run_tool("pip_corpus", args)


if __name__ == "__main__":
    main()
