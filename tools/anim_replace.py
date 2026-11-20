#!/usr/bin/env python3
"""Replace one animation clip with another (Naughty Bear and Panic in Paradise).

  anim_replace.py list naughtybear.lu [--find walk]
      the clips stored in a container: hash, length, skeleton, name, and how
      many other containers hold their own copy

  anim_replace.py swap naughtybear.lu --clip st_walk --from LU_FOLDER --donor st_dance_01
                  [--patch Mod.srpatch] [-o patched.lu] [--replace-movement]
      every clip named by --clip (a hash, a clip name or a state name) plays
      the --donor clip instead. --from is the .lu that holds the donor, or the
      game's lu folder to search. Saves a .srpatch to share, a patched .lu, or
      both.

What a swap does: the donor is decoded and written back at full precision
into the target clip's own record. The target keeps its own forward movement
on the root bone unless --replace-movement is given, so a walk replaced by a
dance still moves at walking speed.

Naughty Bear: tracks are bone indexes, so the donor is moved onto the
target's skeleton with the bone map the game itself ships in the target
container's animation set (when the skeletons differ). The donor's skeleton
must be the target's or one `list` says the container can borrow from.

Panic in Paradise: tracks name their bone by hash, so a clip plays on any
skeleton with those bones and no map is needed. `swap` reports how many of
the replaced clip's bones the donor drives, and refuses a donor that drives
none of them. An additive clip only replaces an additive one, and the other
way round. The game freezes if a record changes size, so a shorter clip is
padded back to the original size, and a longer one goes into the donor's own
record when the donor is stored in the same container: the two records trade
names, and the donor's name then plays the replaced clip (one clip per donor).

A clip is often copied into many containers (each costume or area can have
its own copy); a swap changes only the container you give it, and both
commands say how many others hold the clip.
"""
import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
NAMES_FILE = {"nb1": "nb1_clip_names.tsv", "pip": "pip_clip_names.tsv"}
SOURCES_FILE = "nb1_anim_sources.tsv"         # NB1; PiP keeps them in its names file
GAME_NAMES = {"nb1": "Naughty Bear", "pip": "Panic in Paradise"}
ANIMSET_TYPE = 0x04300012
ROOT_TRANSLATION = (0x04, 0x05, 0x06)


class SwapError(Exception):
    pass


def _data_file(name):
    for d in (HERE, Path(__file__).resolve().parent):
        if (d / name).is_file():
            return d / name
    return None


def game_of(lu):
    """'pip' for an LUH (Panic in Paradise) container, else 'nb1'."""
    return "pip" if getattr(lu, "is_luh", False) else "nb1"


def _rows(game):
    p = _data_file(NAMES_FILE[game])
    if p is None:
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("	")
        yield f + [""] * (4 - len(f))


def load_names(game="nb1"):
    """{clip hash: (name, [state names])} from the game's clip-name table."""
    return {int(f[0], 16): (f[1], [x for x in f[2].split(";") if x]) for f in _rows(game)}


def clip_sources(game="nb1"):
    """{clip hash: {container stem, ...}}: which containers hold each clip."""
    out = {}
    if game == "pip":
        for f in _rows(game):
            out[int(f[0], 16)] = {x for x in f[3].split(",") if x}
        return out
    p = _data_file(SOURCES_FILE)
    if p is None:
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        f = line.split("	")
        if len(f) < 4 or f[0] != "clips":
            continue
        for c in f[3].split(","):
            if c:
                out.setdefault(int(c, 16), set()).add(f[2])
    return out


def label(h, names):
    name, states = names.get(h, ("", []))
    if name and states and states != [name]:
        return f"{name} (plays as {', '.join(states)})"
    return name or ", ".join(states)


def desc(h, names):
    """'0a1b2c3d st_name' (or just the hash when the clip is unnamed)."""
    n = label(h, names)
    return f"{h:08x} {n}" if n else f"{h:08x}"


def local_clips(lu):
    """{hash: record} of the clips stored in a container."""
    import lu_anim_encode as lae
    out = {}
    for r in lu.records:
        if r.external or r.type != lae.CLIP_TYPE or r.size < 0x60:
            continue
        if lae._u32(lu.chunk(r), 0) == lae.CLIP_TYPE:      # same test as clip_records
            out[r.hash] = r
    return out


def animset_bones(lu):
    """PiP: the bone hashes of the skeleton that plays the container's
    animation set (anim-set w[17] pointer, w[18] count; PIP_FORMAT.md 11.4),
    or None when it has no animation set."""
    import struct
    for r in lu.records:
        if r.type == ANIMSET_TYPE and not r.external:
            d = bytes(lu.chunk(r))
            if len(d) < 0x60:
                continue
            ptr, n = struct.unpack_from(">2I", d, 17 * 4)
            if 0 < n < 4096 and ptr + 4 * n <= len(d):
                return set(struct.unpack_from(f">{n}I", d, ptr))
    return None


def animset_maps(lu):
    """(own skeleton hash, {foreign skeleton: map}) of the container's own
    animation set, or (None, {}) when it has none."""
    from lu_corpus import animset_retarget_maps
    for r in lu.records:
        if r.type == ANIMSET_TYPE and not r.external:
            return animset_retarget_maps(bytes(lu.chunk(r)))
    return None, {}


def resolve(term, have, names):
    """Clip hashes in `have` named by term: comma-separated hashes, clip
    names or state names. Raises SwapError when one names nothing here."""
    out = []
    for t in (x.strip() for x in str(term).split(",")):
        if not t:
            continue
        hit = []
        try:
            h = int(t[2:] if t.lower().startswith("0x") else t, 16)
            if len(t.lower().removeprefix("0x")) == 8:
                hit = [h] if h in have else []
                if not hit:
                    raise SwapError(f"no clip {h:08x} in this container")
        except ValueError:
            pass
        if not hit:
            tl = t.lower()
            hit = sorted(h for h, (n, st) in names.items()
                         if h in have and (n.lower() == tl or tl in (s.lower() for s in st)))
            if not hit:
                raise SwapError(f"no clip named '{t}' in this container "
                                f"(try 'list' to see its clips)")
        out += [h for h in hit if h not in out]
    if not out:
        raise SwapError("no clip given")
    return out


def find_donor(src, term, names, game="nb1"):
    """(LuFile, clip hash) for the donor: src is a .lu or a folder of them."""
    from naughty_lu import LuFile
    src = Path(src)
    if src.is_file():
        lu = LuFile(src)
        if game_of(lu) != game:
            raise SwapError(f"{src.name} is a {GAME_NAMES[game_of(lu)]} container; "
                            f"the target is {GAME_NAMES[game]}")
        hs = resolve(term, local_clips(lu), names)
        if len(hs) != 1:
            raise SwapError(f"'{term}' names {len(hs)} clips in {src.name}; give one hash")
        return lu, hs[0]
    if not src.is_dir():
        raise SwapError(f"not found: {src}")
    # the clip's hash, from the term alone (a hash, or a name in the table)
    t = str(term).strip().lower().removeprefix("0x")
    wanted = set()
    try:
        if len(t) == 8:
            wanted = {int(t, 16)}
    except ValueError:
        pass
    if not wanted:
        wanted = {h for h, (n, st) in names.items()
                  if n.lower() == t or t in (s.lower() for s in st)}
    if not wanted:
        raise SwapError(f"unknown donor clip '{term}'")
    if len(wanted) > 1:
        raise SwapError(f"'{term}' names {len(wanted)} clips "
                        f"({', '.join(f'{h:08x}' for h in sorted(wanted))}); give one hash")
    h = wanted.pop()
    # the game's lu folder, or a folder above it (a project or game folder);
    # Seam Ripper's own backups are not game files
    every = [p for p in sorted(src.rglob("*.lu"))
             if ".seamripper" not in p.parts]
    by_stem = {}
    for p in every:
        by_stem.setdefault(p.stem.lower(), p)
    where = sorted(clip_sources(game).get(h, ()))
    files = [by_stem[u.lower()] for u in where if u.lower() in by_stem]
    files += [p for p in every if p not in files]
    for p in files:
        try:
            lu = LuFile(p)
        except Exception:
            continue
        if game_of(lu) == game and h in local_clips(lu):
            return lu, h
    raise SwapError(f"clip {h:08x} is in none of the {GAME_NAMES[game]} containers in {src}")


FLAT_LIMIT = 0.005     # largest value range turned into a constant by fit_model


def fit_model(obj, target_record, limit, say=None):
    """Shrink a neutral clip until the record built from it is at most `limit`
    bytes: the flattest sampled channels (all but the root's) become constants
    at their mean, flattest first, while their whole range is under
    FLAT_LIMIT. Returns the built record; SwapError if it cannot fit."""
    import copy
    import numpy as np
    import lu_anim_encode as lae
    say = say or (lambda s: None)
    built = lae.build_clip(obj, target_record)
    if len(built) <= limit:
        return built
    flat = []
    for bi, b in enumerate(obj["bones"]):
        if bi == 0:
            continue
        for ci, c in enumerate(b.get("keyed", [])):
            if c["tag"] not in lae._KNOWN or any(p["kind"] != "sample" for p in c["pieces"]):
                continue
            v = np.concatenate([np.asarray(p["values"], float).ravel() for p in c["pieces"]])
            if np.ptp(v) < FLAT_LIMIT:
                flat.append((float(np.ptp(v)), bi, c["tag"], float(v.mean())))
    flat.sort()
    work = copy.deepcopy(obj)
    for n, (r, bi, tag, mean) in enumerate(flat, 1):
        b = work["bones"][bi]
        b["keyed"] = [c for c in b["keyed"] if c["tag"] != tag]
        b.setdefault("static", []).append({"tag": tag, "value": mean})
        built = lae.build_clip(work, target_record)
        if len(built) <= limit:
            obj.clear()
            obj.update(work)
            say(f"made {n} near-constant channel(s) constant to fit {limit:,} bytes "
                f"(largest range {r:.1e})")
            return built
    raise SwapError(f"the replacement is {len(lae.build_clip(obj, target_record)):,} bytes "
                    f"and must fit {limit:,}; even with its {len(flat)} near-constant "
                    f"channel(s) made constant it does not")


def _kept_root(tgt, dur, say):
    """The target clip's root track (track 0) with its forward movement
    stretched over `dur` at the same speed: its statics, its keyed channels
    other than translation, and a linear channel per moving translation."""
    import numpy as np
    import lu_anim_encode as lae
    from lu_anim2 import decode_clip, sample_channel
    tm = lae.parse_clip(tgt)
    tc = decode_clip(tgt, Counter())
    root = {ch["tag"]: ch for ch in tc["tracks"].get(0, [])}
    tdur = tc["duration"]
    bone = {"keyed": [], "static": list(tm["bones"][0]["static"])}
    for tag in ROOT_TRANSLATION:
        ch = root.get(tag)
        if ch is None or ch["family"] != "keyed":
            continue
        v0, v1 = sample_channel(ch, np.array([0.0, tdur]))
        speed = (v1 - v0) / tdur
        bone["keyed"].append(lae.linear_channel(tag, v0, v0 + speed * dur, dur))
        say(f"kept the target's root movement on channel {tag:02x}: {speed:.3f}/s")
    bone["keyed"] += [c for c in tm["bones"][0]["keyed"] if c["tag"] not in ROOT_TRANSLATION]
    return bone


def swap_model(target_lu, target_hash, donor_bytes, keep_movement=True, notes=None):
    """The neutral clip (lu_anim_encode JSON) that makes target_hash in
    target_lu play donor_bytes."""
    import lu_anim_encode as lae
    say = notes.append if notes is not None else (lambda s: None)
    recs = lae.clip_records(target_lu, target_hash)
    if len(recs) != 1:
        raise SwapError(f"{len(recs)} clip records named {target_hash:08x}")
    tgt = bytes(target_lu.chunk(recs[0]))
    th, dh = lae.header_fields(tgt), lae.header_fields(donor_bytes)
    if th["game"] != dh["game"]:
        raise SwapError(f"the donor is a {GAME_NAMES[dh['game']]} clip, the target "
                        f"a {GAME_NAMES[th['game']]} one")
    model = lae.parse_clip(donor_bytes)
    dur = dh["duration"]
    if th["game"] == "pip":
        if dh["additive"] != th["additive"]:
            raise SwapError("an additive clip (one that adds to another pose) can only "
                            "replace an additive clip, and a normal one a normal one; "
                            f"the donor is {'additive' if dh['additive'] else 'normal'}")
        # the bones the replaced clip drives are bones of whatever plays it
        # (a container's animation set can be a bear moveset while its own
        # clips move a prop, so the set's bone list is not the check)
        want = {x for x in lae.parse_clip(tgt)["bone_hashes"] if x != 0xFFFFFFFF}
        donor_bones = {x for x in model["bone_hashes"] if x != 0xFFFFFFFF}
        hit = len(want & donor_bones)
        say(f"bones bind by name: the donor drives {hit} of the {len(want)} bones the "
            f"replaced clip drives" + (f", plus {len(donor_bones - want)} it does not"
                                       if donor_bones - want else ""))
        # clips of one body share ~99% of their bones, clips of different
        # bodies ~1% (a shared root name); half is the line between them
        if 2 * hit < len(want):
            raise SwapError(f"the donor drives only {hit} of the {len(want)} bones the "
                            f"replaced clip drives; it is for another skeleton")
        if keep_movement:
            root_hash = lae.parse_clip(tgt)["bone_hashes"][0]
            if root_hash not in model["bone_hashes"]:
                say(f"the donor has no track for the root bone {root_hash:08x}; "
                    f"its own movement is used")
            else:
                j = model["bone_hashes"].index(root_hash)
                bones = list(model["bones"])
                bones[j] = _kept_root(tgt, dur, say)
                model = dict(model, bones=bones)
    else:
        if dh["rig_hash"] == th["rig_hash"]:
            if dh["bones"] != th["bones"]:
                raise SwapError("same skeleton but a different bone count")
            say(f"same skeleton ({th['rig_hash']:08x}), no bone map needed")
        else:
            own, maps = animset_maps(target_lu)
            imap = maps.get(dh["rig_hash"])
            if imap is None:
                can = ", ".join(f"{k:08x}" for k in sorted(maps)) or "none"
                raise SwapError(
                    f"the donor is on skeleton {dh['rig_hash']:08x}, the target on "
                    f"{th['rig_hash']:08x}, and this container ships no bone map "
                    f"between them (it has maps from: {can})")
            if own is not None and own != th["rig_hash"]:
                raise SwapError(f"the container's animation set is for skeleton {own:08x}, "
                                f"not the target clip's {th['rig_hash']:08x}")
            if len(imap) != dh["bones"]:
                raise SwapError("the bone map does not fit the donor's skeleton")
            animated = [i for i, b in enumerate(model["bones"]) if b["keyed"] or b["static"]]
            lost = [i for i in animated if imap[i] < 0 and i != 0]
            say(f"bone map {dh['rig_hash']:08x} -> {th['rig_hash']:08x}: "
                f"{sum(t >= 0 for t in imap)} of {dh['bones']} bones"
                + (f"; {len(lost)} animated bone(s) have no match and are dropped"
                   if lost else ""))
            model = lae.retarget(model, imap, th["bones"], th["rig_hash"])
        if keep_movement:
            model = dict(model, bones=[_kept_root(tgt, dur, say)] + model["bones"][1:])
    obj = lae.model_to_json(model)
    lae.build_clip(obj, tgt)                    # refuses anything that would not build
    return obj


# ---------------------------------------------------------------------- cli

def cmd_list(a):
    from naughty_lu import LuFile
    import lu_anim_encode as lae
    lu = LuFile(a.lu)
    game = game_of(lu)
    names, sources = load_names(game), clip_sources(game)
    have = local_clips(lu)
    stem = Path(a.lu).stem
    print(f"{Path(a.lu).name} ({GAME_NAMES[game]}): {len(have)} clip(s) stored here")
    if game == "pip":
        bones = animset_bones(lu)
        if bones is not None:
            print(f"animation set plays on a skeleton with {len(bones)} bones; clips bind "
                  f"to bones by name, so any clip with those bones fits")
    else:
        own, maps = animset_maps(lu)
        if own is not None:
            print(f"animation set for skeleton {own:08x}; borrows clips from skeletons: "
                  + (", ".join(f"{k:08x} ({sum(t >= 0 for t in m)} of {len(m)} bones)"
                               for k, m in sorted(maps.items())) or "none"))
    rows = []
    for h, r in sorted(have.items()):
        f = lae.header_fields(bytes(lu.chunk(r)))
        name = label(h, names)
        if a.find and a.find.lower() not in name.lower() and a.find.lower() not in f"{h:08x}":
            continue
        others = len(sources.get(h, set()) - {stem})
        rows.append((h, f, name, others, r.size))
    rig = "clip rig" if game == "pip" else "skeleton"
    print(f"{'clip':8}  {'secs':>5}  {'bytes':>7}  {rig:8}  {'bones':>5}  {'also in':>7}  name")
    for h, f, name, others, size in rows:
        extra = " (additive)" if f.get("additive") else ""
        print(f"{h:08x}  {f['duration']:5.2f}  {size:7d}  {f['rig_hash']:08x}  {f['bones']:5d}  "
              f"{others:7d}  {name}{extra}")
    if a.find:
        print(f"{len(rows)} match(es)")
    return 0


def pip_record(lu, h, dh, obj, targets, used, names, notes):
    """PiP: None when clip h's replacement fits h's own record. Otherwise the
    donor's own record takes it (the two records trade names, no record
    changes size; fit_model shrinks obj if a few bytes over) -> donor hash."""
    import lu_anim_encode as lae
    have = local_clips(lu)
    tr = have[h]
    told = bytes(lu.chunk(tr))
    size, room = len(lae.build_clip(obj, told)), lae.pip_slot(lu, tr.index)
    if size <= room:
        return None
    why = (f"the replacement is {size:,} bytes and {label(h, names) or f'{h:08x}'}'s "
           f"record holds {room:,}; Panic in Paradise freezes if a record changes size")
    drec = have.get(dh)
    if drec is None:
        raise SwapError(f"{why}. Pick a shorter donor, or one stored in "
                        f"{Path(lu.path).name} so its record can be used")
    if dh in used or dh in targets:
        raise SwapError(f"{why}, and the donor's record is already taken by another "
                        f"clip of this swap. Replace this clip with a different donor")
    fit_model(obj, told, lae.pip_slot(lu, drec.index), notes.append)
    used.add(dh)
    notes.append(f"too big for its own record ({size:,} of {room:,} bytes): stored in "
                 f"the donor's record instead, and the donor's name "
                 f"({label(dh, names) or f'{dh:08x}'}) now plays the original clip")
    return dh


def cmd_swap(a):
    from naughty_lu import LuFile
    import lu_anim_encode as lae
    import sr_patch
    if not a.patch and not a.out:
        raise SwapError("say where to save: --patch for a .srpatch, -o for a patched .lu")
    target = Path(a.lu)
    base = sr_patch.retail_copy(target)         # motion and maps from the retail clip
    if base != target:
        print(f"{target.name} has been modded; reading the original clips from its "
              f"retail backup")
    tlu = LuFile(base)
    game = game_of(tlu)
    names = load_names(game)
    targets = resolve(a.clip, local_clips(tlu), names)
    dlu, dh = find_donor(a.from_, a.donor, names, game)
    donor = bytes(dlu.chunk(lae.clip_records(dlu, dh)[0]))
    print(f"{GAME_NAMES[game]}: donor {desc(dh, names)} from {Path(dlu.path).name}, "
          f"{lae.header_fields(donor)['duration']:.2f} s")
    sources = clip_sources(game)
    used = set()
    with tempfile.TemporaryDirectory(prefix="animswap_") as work:
        anims, built = [], []
        for h in targets:
            notes = []
            obj = swap_model(tlu, h, donor, keep_movement=not a.replace_movement, notes=notes)
            slot = pip_record(tlu, h, dh, obj, targets, used, names, notes) \
                if game == "pip" else None
            print(f"clip {desc(h, names)}:")
            for n in notes:
                print(f"  {n}")
            others = sorted(sources.get(h, set()) - {target.stem})
            if others:
                print(f"  note: {len(others)} other container(s) hold their own copy "
                      f"of this clip and still play the original "
                      f"({', '.join(others[:6])}{', ...' if len(others) > 6 else ''})")
            p = Path(work) / f"clip_{h:08x}.json"
            p.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
            if a.json_dir:
                Path(a.json_dir).mkdir(parents=True, exist_ok=True)
                (Path(a.json_dir) / p.name).write_bytes(p.read_bytes())
            if slot is None:
                anims.append((f"{h:08x}", str(p)))
                built.append((h, obj, None))
            else:
                anims.append((f"{h:08x}", str(p), f"{slot:08x}"))
                built.append((h, obj, None, slot, None))
        if a.patch:
            sr_patch.make_patch(
                a.patch, [{"container": str(target), "scripts": [], "strings": None,
                           "anims": anims}],
                name=a.name or Path(a.patch).stem, author=a.author or "",
                description=a.description or
                f"{', '.join(f'{h:08x}' for h in targets)} play "
                f"{label(dh, names) or f'{dh:08x}'} instead",
                version=a.version or "1")
        if a.out:
            write_lu(target, a.out, built, game)
    return 0


def write_lu(target, out, built, game="nb1"):
    """Build the clips into target and save as out (backing up out first if
    it is an existing game file)."""
    import lu_anim_encode as lae
    out = Path(out)
    try:
        data, lines = lae.replace_in_container(str(target), built, check_sha=False)
    except lae.EncodeError as e:
        raise SwapError(str(e))
    for ln in lines:
        print(ln)
    if out.exists():
        import os
        import stat
        if not os.access(out, os.W_OK) or not (out.stat().st_mode & stat.S_IWRITE):
            raise SwapError(f"{out} is read-only; clear its read-only attribute "
                            f"or save somewhere else")
        import sr_backup
        sr_backup.backup_before_overwrite(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(data)
    if game == "nb1":                       # PiP writes raw segments: no LZX to check
        import verify_lzx
        try:
            verify_lzx.verify_file(str(tmp))
        except verify_lzx.VerifyError as e:
            tmp.unlink()
            raise SwapError(f"the rebuilt container failed the LZX check: {e}")
    tmp.replace(out)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list the clips stored in a container")
    pl.add_argument("lu")
    pl.add_argument("--find", help="only clips whose name or hash contains this")
    ps = sub.add_parser("swap", help="make clips play another clip")
    ps.add_argument("lu", help="the container that holds the clip(s) to replace")
    ps.add_argument("--clip", required=True,
                    help="clip(s) to replace: hash, clip name or state name; comma-separated")
    ps.add_argument("--from", dest="from_", required=True,
                    help="the .lu holding the donor clip, or the game's lu folder")
    ps.add_argument("--donor", required=True, help="the clip to play instead (hash or name)")
    ps.add_argument("--replace-movement", action="store_true",
                    help="use the donor's root movement too (default: keep the target's)")
    ps.add_argument("--patch", help="save a .srpatch here")
    ps.add_argument("-o", "--out", help="save the patched .lu here")
    ps.add_argument("--json-dir", help="also save the neutral clip files here")
    ps.add_argument("--name", help="patch name")
    ps.add_argument("--author")
    ps.add_argument("--description")
    ps.add_argument("--version")
    a = ap.parse_args()
    try:
        rc = cmd_list(a) if a.cmd == "list" else cmd_swap(a)
    except SwapError as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
