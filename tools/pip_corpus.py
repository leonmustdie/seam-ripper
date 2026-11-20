#!/usr/bin/env python3
"""
pip_corpus.py — corpus-wide Naughty Bear: Panic in Paradise animation
extraction. Decoded corpus in (corpus_decode.py over the LUH containers),
one GLB per animated rig out, every clip named and baked.

What differs from NB1 (lu_corpus.py), all read from the shipped bytes and
checked by diagnostics/format_checks/pip_checks.py:

  * A clip names its bones. clip+0x1c {ptr, n} is a table of bone-name
    hashes, one per track; the skeleton carries the same hashes at +0x48
    as {hash, bone index} sorted by hash. A clip is bound to a skeleton BY
    HASH, never by index and never through a retarget map (the NB1 anim-set
    maps are gone). One clip hash, ffffffff, means "no bone": that track is
    empty in every clip.
  * The track table entry is 24 bytes (lu_anim2.decode_clip). Channels,
    pieces, static words, tags and the joint orient are NB1's.
  * anim key == clip record hash. An anim-set (04300012) lists the clips
    its model plays and the model's bone hashes; that bone list equals the
    hash set of exactly one skeleton (173 of 174 anim-sets).
  * The mesh record type is 34000007; the skeleton still references it as
    {hash, 04000007}. The inner layout is NB1's, so lu_corpus's
    declaration-driven reader is used unchanged.

Characters. Several skeleton RECORDS share one skeleton (rig hash) and
differ only in the mesh they name: Naughty, the vampire, the alien and the
zombie bear are four records of rig 250b05b2. One GLB is written per
character = skeleton records of a rig that name the same mesh.

Which character a clip is baked on:
  1. NATIVE anim-set. The unit descriptor (0400000e) stores adjacent
     {skeleton record, 04000001}{anim-set, 04300012} pairs: the object and
     the anim-set it owns. When the pair's skeleton has exactly the
     anim-set's bone list, the anim-set is that character's own ("hero",
     "vampire", "common"). An anim-set no descriptor pairs is native to a
     character when every container holding it also holds that skeleton
     record.
  2. MOVESET. A weapon or prop owns an anim-set whose bone list is the
     bear's, not its own (aluminumbat: 3-bone skeleton, 122-bone list).
     Those are the moves a bear plays with the object. They go to every
     character whose skeleton has exactly that bone list, and to skeletons
     that are a near superset of it (the 123-bone hero rig carries all 122).
  In both cases the skeleton must carry at least half of the clip's named
  bones: bear anim-sets also list the prop's own clip of a kill move.
  3. A clip no character gets that way goes to the skeleton that carries
     most of its bones (at least half), else it is reported as rig_absent.
Bones of the clip the skeleton lacks are dropped (counted per clip); bones
of the skeleton the clip lacks keep their rest pose.

Output: <label>_rig_<hash>[_<skeleton record>][_pN].glb, rigs.csv,
clips.csv, clip_names.tsv, state_names.tsv, rig_names.tsv, summary.txt.

usage:
  python pip_corpus.py pip_decoded --scripts pip_scripts_out -o out_pip
         [--rate 30] [--rigs H1,H2] [--max-mb 200] [--all-rigs] [--json]
"""
import argparse
import csv
import json
import struct
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from lu_anim2 import Skeleton, decode_clip, bake_clip, build_glb, TAG_T
from lu_rig import solve_palette
import lu_corpus as LC
import pip_names as PN

T_SKEL, T_MESH_REC, T_ANIMSET = 0x04000001, 0x34000007, 0x04300012
FAMILY_MIN = 0.9          # moveset bone list vs a superset skeleton
FAMILY_MIN_BONES = 20
MIN_COVER = 0.5
NO_BONE = 0xFFFFFFFF


def skeleton_bone_hashes(d, n):
    """skeleton+0x48 {ptr, count}: {name hash, bone index} sorted by hash
    -> list of hashes in bone order (None where a bone has no entry)."""
    p, c = struct.unpack_from(">2I", d, 0x48)
    out = [None] * n
    if p == 0xFFFFFFFF or p + 8 * c > len(d):
        return out
    for i in range(c):
        h, ix = struct.unpack_from(">2I", d, p + 8 * i)
        if ix < n:
            out[ix] = h
    return out


class Registry:
    def __init__(self):
        self.rigs = {}
        self.meshes = {}
        self.mesh_unit = {}
        self.clips = {}                       # clip hash -> decoded clip
        self.clip_sources = defaultdict(list)
        self.desc_pairs = set()               # (skeleton record, anim-set)
        self.bake_cache = {}
        self.stats = Counter()
        self.unit_count = 0

    def scan_unit(self, unit):
        self.unit_count += 1
        man = LC.read_manifest(unit)
        sd = unit / "unk_04000001"
        for p in sorted(sd.glob("*.bin")) if sd.is_dir() else []:
            d = p.read_bytes()
            if len(d) < 0x60 or struct.unpack_from(">I", d, 4)[0] != T_SKEL:
                continue
            try:
                sk = Skeleton(d)
            except Exception:
                self.stats["skeleton_parse_fail"] += 1
                continue
            if not sk.n:
                continue
            rec = man.get(LC.rec_index(p))
            r = self.rigs.get(sk.rig_hash)
            if r is None:
                hs = skeleton_bone_hashes(d, sk.n)
                self.rigs[sk.rig_hash] = r = {
                    "skel": sk, "hashes": hs,
                    "h2i": {h: i for i, h in enumerate(hs) if h is not None},
                    "records": {}, "units": [], "mesh_refs": [], "path": p}
            elif r["skel"].n != sk.n:
                self.stats["rig_hash_bone_count_conflict"] += 1
            refs = LC.skeleton_mesh_refs(d)
            e = r["records"].setdefault(rec[0] if rec else 0, {"units": [], "mesh_refs": refs})
            e["units"].append(unit.name)
            r["units"].append(unit.name)
            for mh in refs:
                if mh not in r["mesh_refs"]:
                    r["mesh_refs"].append(mh)
        dd = unit / "type_0400000e"
        for p in sorted(dd.glob("*.bin")) if dd.is_dir() else []:
            d = p.read_bytes()
            w = np.frombuffer(d[:len(d) & ~3], ">u4")
            for i in np.nonzero(w == T_ANIMSET)[0]:
                if i >= 3 and w[i - 2] == T_SKEL:
                    self.desc_pairs.add((int(w[i - 3]), int(w[i - 1])))
        md = unit / "type_34000007"
        for p in sorted(md.glob("*.bin")) if md.is_dir() else []:
            rec = man.get(LC.rec_index(p))
            if rec and rec[2] == T_MESH_REC:
                self.meshes.setdefault(rec[0], p)
                self.mesh_unit.setdefault(rec[0], unit.name)
        cd = unit / "type_04300000"
        for p in sorted(cd.glob("*.bin")) if cd.is_dir() else []:
            d = p.read_bytes()
            if len(d) >= 12 and struct.unpack_from(">I", d, 8)[0] in self.clips:
                self.clip_sources[struct.unpack_from(">I", d, 8)[0]].append(
                    f"{unit.name}/{p.name}")
                self.stats["duplicate_clip_record"] += 1
                continue
            clip = decode_clip(d, self.stats)
            if clip is None or "bone_hashes" not in clip:
                self.stats["not_a_pip_clip"] += 1
                continue
            self.clip_sources[clip["name_hash"]].append(f"{unit.name}/{p.name}")
            self.clips[clip["name_hash"]] = clip


def cover(clip, rig):
    """(bones of the clip the skeleton carries, named bones of the clip)."""
    hs = [h for h in clip["bone_hashes"] if h != NO_BONE]
    return sum(h in rig["h2i"] for h in hs), len(hs)


def bind_clip(clip, rig, stats):
    """Clip -> copy whose track indices are the skeleton's bone indices."""
    new = dict(clip)
    new["tracks"], new["statics"] = {}, {}
    h2i, hs = rig["h2i"], clip["bone_hashes"]
    lost = 0
    for j, chans in clip["tracks"].items():
        h = hs[j]
        if h == NO_BONE:
            stats["channels_on_unnamed_track"] += 1
            continue
        tgt = h2i.get(h)
        if tgt is None:
            lost += 1
            continue
        if tgt in new["tracks"]:
            stats["two_tracks_one_bone"] += 1
        new["tracks"][tgt] = list(chans)
    for j, ws in clip["statics"].items():
        tgt = h2i.get(hs[j])
        if tgt is not None:
            new["statics"][tgt] = ws
    new["track_count"] = rig["skel"].n
    new["bones_lost"] = lost
    return new


def characters(reg):
    """One character per rig and group of skeleton records naming the same
    meshes. -> {(rig hash, first record hash): dict}, primary (most
    containers) first within a rig."""
    out = {}
    for rh in sorted(reg.rigs):
        r = reg.rigs[rh]
        groups = defaultdict(list)
        for rec, e in r["records"].items():
            groups[tuple(e["mesh_refs"])].append(rec)
        gl = []
        for refs, recs in groups.items():
            recs.sort()
            units = [u for rec in recs for u in r["records"][rec]["units"]]
            gl.append(dict(rig=rh, recs=recs, mesh_refs=list(refs), units=units,
                           split=len(groups) > 1, native=[], movesets=[]))
        gl.sort(key=lambda c: (-len(c["units"]), c["recs"][0]))
        for c in gl:
            out[(rh, c["recs"][0])] = c
    return out


class _MeshView:
    """What lu_corpus.choose_mesh reads, narrowed to one character."""

    def __init__(self, reg, ch):
        self.rigs = {ch["rig"]: {"mesh_refs": ch["mesh_refs"], "units": ch["units"],
                                 "skel": reg.rigs[ch["rig"]]["skel"]}}
        self.meshes, self.mesh_unit = reg.meshes, reg.mesh_unit


def char_label(reg, corpus, ch):
    names = sorted({corpus.animset_label(a) for a in ch["native"]})
    real = [n for n in names if not n.startswith("animset_")]
    for pref in ("hero", "common"):
        if pref in real:
            real = [pref] + [n for n in real if n != pref]
    pick = real or names
    if not pick:
        mv = sorted({corpus.animset_label(a) for a in ch["movesets"]})
        mv = [n for n in mv if not n.startswith("animset_")] or mv
        if len(mv) == 1:
            return mv[0]
        us = sorted(set(ch["units"]))
        return us[0] if len(us) == 1 else f"{us[0]}+{len(us) - 1}units"
    return "+".join(pick[:3]) + (f"+{len(pick) - 3}more" if len(pick) > 3 else "")


# Skin-weight errors in the SHIPPED meshes, corrected on export (PIP_FORMAT.md
# 11.16). {mesh record hash: skeleton bones whose partial weights are dropped}.
# Found by diagnostics/format_checks/weight_hops.py; --keep-asset-weights
# exports the file's own weights.
ASSET_WEIGHT_FIXES = {
    0x02cc8b69: [65],   # alien: 4 eye-corner vertices 12-14 % on the left-hand item bone
}


def fix_asset_weights(submeshes, bones):
    """Drop weights under 0.5 on the given skeleton bones, renormalise the
    rest. -> vertices changed."""
    n = 0
    for s in submeshes:
        pal = s[7]
        if not pal or s[5]:
            continue
        for j, w in zip(s[2], s[3]):
            for k in range(4):
                if 0.0 < w[k] < 0.5 and j[k] < len(pal) and pal[j[k]] in bones:
                    w[k], j[k] = 0.0, 0
                    t = sum(w)
                    w[:] = [x / t for x in w]
                    n += 1
    return n


RIG_FIELDS = ["rig", "skel_record", "label", "native_animsets", "movesets", "bones",
              "clips_baked", "clips_native", "clips_moveset", "clips_by_cover", "mesh",
              "mesh_how", "mesh_submeshes", "mesh_verts", "skinned", "skel_units",
              "skel_first_unit", "files"]
CLIP_FIELDS = ["clip", "name", "label_source", "rig", "skel_record", "rig_label", "status", "how",
               "clip_rig", "clip_bones", "bones_bound", "bones_lost", "duration",
               "bones_animated", "additive", "part", "sources"]


def extract_rig(args, reg, ch, items, label, set_names, rig_rows, clip_rows, t0):
    """items: [(clip, how)] for this character."""
    out = Path(args.out)
    rig_hash = ch["rig"]
    r = reg.rigs[rig_hash]
    skel = r["skel"]
    rec_s = f"{ch['recs'][0]:08x}"
    submeshes, mesh_hash, mesh_how = LC.choose_mesh(_MeshView(reg, ch), rig_hash)
    if mesh_hash and not args.keep_asset_weights:
        reg.stats["asset_weight_fix_vertices"] += fix_asset_weights(
            submeshes, ASSET_WEIGHT_FIXES.get(int(mesh_hash, 16), ()))
    mapping = []
    if submeshes and any(s[7] is None for s in submeshes):
        try:
            mapping = solve_palette(submeshes, skel.bones) or []
        except Exception:
            mapping = []
    parts, cur, cur_bytes = [], {}, 0
    budget = args.max_mb * 1024 * 1024
    n_ok = 0
    n_how = Counter()
    used = set()
    for clip, how in sorted(items, key=lambda x: (x[0]["glb_name"].lower(), x[0]["name_hash"])):
        ov, nb = cover(clip, r)
        row = dict(clip=f"{clip['name_hash']:08x}", name=clip["glb_name"],
                   label_source=clip.get("label_source", ""), rig=f"{rig_hash:08x}",
                   skel_record=rec_s, rig_label=label, how=how, clip_rig=f"{clip['rig_hash']:08x}",
                   clip_bones=nb, bones_bound=ov, bones_lost=0,
                   duration=round(clip["duration"], 3), bones_animated=0,
                   additive=int(clip.get("additive", False)), part="",
                   sources=";".join(reg.clip_sources.get(clip["name_hash"], [])[:6]))
        ck = (clip["name_hash"], rig_hash)
        if ck not in reg.bake_cache:
            b = bind_clip(clip, r, reg.stats)
            baked, ts = bake_clip(b, skel, args.rate, None, not args.no_scale)
            reg.bake_cache[ck] = (b, baked, ts)
        b, baked, ts = reg.bake_cache[ck]
        row["bones_lost"] = b["bones_lost"]
        row["bones_animated"] = len(b["tracks"])
        if not baked:
            reg.stats["no_channels"] += 1
            row["status"] = "no_channels"
            clip_rows.append(row)
            continue
        if args.json:
            jd = {"clip": row["clip"], "name": row["name"], "rig": row["rig"],
                  "duration": clip["duration"],
                  "tracks": {str(bn): [
                      {"tag": f"{ch['tag']:02x}", "family": ch["family"],
                       "times": [round(float(x), 6) for x in ch["times"]],
                       "values": [round(float(x), 6) for x in ch["values"]]}
                      for ch in chans] for bn, chans in b["tracks"].items()}}
            (out / "clips_json" / f"{rig_hash:08x}_{row['clip']}.json").write_text(json.dumps(jd))
        name = clip["glb_name"]
        if name.lower() in used:
            name = f"{name}_{clip['name_hash']:08x}"
        used.add(name.lower())
        row["name"] = name
        nbytes = LC.est_bytes(baked, len(ts))
        if cur and cur_bytes + nbytes > budget:
            parts.append(cur)
            cur, cur_bytes = {}, 0
        cur[name] = (baked, ts)
        cur_bytes += nbytes
        n_ok += 1
        n_how[how] += 1
        row["status"], row["part"] = "baked", len(parts) + 1
        clip_rows.append(row)
    if cur:
        parts.append(cur)
    files = []
    stem = f"{LC.safe_name(label)}_rig_{rig_hash:08x}" + (f"_{rec_s}" if ch["split"] else "")
    for pi, cm in enumerate(parts):
        dest = out / f"{stem}{f'_p{pi+1}' if len(parts) > 1 else ''}.glb"
        build_glb(skel, submeshes, mapping, cm, dest)
        files.append(dest.name)
    if not parts:
        dest = out / f"{stem}.glb"
        build_glb(skel, submeshes, mapping, {}, dest)
        files.append(dest.name)
    nv = sum(len(s[0]) for s in submeshes)
    rig_rows.append(dict(
        rig=f"{rig_hash:08x}", skel_record=rec_s, label=label,
        native_animsets=";".join(set_names[0]), movesets=len(set_names[1]), bones=skel.n,
        clips_baked=n_ok, clips_native=n_how["animset"], clips_moveset=n_how["moveset"],
        clips_by_cover=n_how["cover"],
        mesh=mesh_hash, mesh_how=mesh_how, mesh_submeshes=len(submeshes), mesh_verts=nv,
        skinned=int(any(not s[5] for s in submeshes)), skel_units=len(ch["units"]),
        skel_first_unit=ch["units"][0], files=";".join(files)))
    print(f"rig {rig_hash:08x} {rec_s} {label:28s} {skel.n:4d} bones {n_ok:4d} clips  "
          f"mesh={mesh_how.split('(')[0]} {nv} verts -> {len(files)} file(s) "
          f"{time.time()-t0:.0f}s", flush=True)


def cmd_extract(args):
    t0 = time.time()
    root, out = Path(args.corpus), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.json:
        (out / "clips_json").mkdir(exist_ok=True)
    reg = Registry()
    units = sorted(p for p in root.glob(args.units) if p.is_dir())
    for i, u in enumerate(units):
        reg.scan_unit(u)
        if (i + 1) % 100 == 0:
            print(f"scanned {i+1}/{len(units)} units, {len(reg.rigs)} rigs, "
                  f"{len(reg.clips)} clips, {time.time()-t0:.0f}s", flush=True)
    print(f"scan: {reg.unit_count} units, {len(reg.rigs)} rigs, {len(reg.meshes)} meshes, "
          f"{len(reg.clips)} unique clips ({sum(len(v) for v in reg.clip_sources.values())} "
          f"records), {time.time()-t0:.0f}s", flush=True)

    # names
    scripts = PN.Scripts(args.scripts)
    corpus = PN.Corpus(str(root))
    PN.name_animsets(corpus, scripts)
    name_rows, state_rows = PN.build(corpus, scripts, PN.load_vocab(args.vocab))
    PN.write(name_rows, state_rows, corpus, str(out))
    nsum = PN.summary(name_rows, state_rows, corpus, scripts)
    print(nsum, flush=True)
    by_clip = {r["clip"]: r for r in name_rows}
    for h, c in reg.clips.items():
        nr = by_clip.get(h)
        c["glb_name"] = (nr["label"] if nr and nr["label"] else f"{h:08x}")
        c["label_source"] = nr["label_source"] if nr else ""

    # anim-set -> characters
    chars = characters(reg)
    chars_of_rig = defaultdict(list)
    for ck, ch in chars.items():
        chars_of_rig[ck[0]].append(ck)
    hset = {rh: frozenset(r["h2i"]) for rh, r in reg.rigs.items()}
    by_set = defaultdict(list)
    for rh in sorted(reg.rigs):
        by_set[hset[rh]].append(rh)
    paired_sets = {a for _s, a in reg.desc_pairs}
    targets = defaultdict(dict)           # clip -> {character key: how}

    def give(a, cks, how):
        for ck in cks:
            chars[ck]["native" if how == "animset" else "movesets"].append(a)
            rig = reg.rigs[ck[0]]
            for k in a["anim_keys"]:
                c = reg.clips.get(k)
                if c is None:
                    reg.stats["animset_clip_missing"] += 1
                    continue
                ov, nb = cover(c, rig)
                if nb and ov / nb >= MIN_COVER:
                    if targets[k].get(ck) != "animset":
                        targets[k][ck] = how
                else:
                    reg.stats["animset_listing_other_rig_clip"] += 1

    # pass 1: anim-sets a unit descriptor pairs with a skeleton of their own
    # bone list. pass 2: unpaired anim-sets, native by containers, only for
    # characters pass 1 left without a set (the hero, the alien); a prop
    # anim-set that happens to ship only alongside the NPC skeleton stays a
    # moveset.
    native_of = {}
    for a in corpus.animsets.values():
        bones = frozenset(a["bones"])
        cks = [ck for rh in (by_set.get(bones, []) if bones else []) for ck in chars_of_rig[rh]
               if any((rec, a["hash"]) in reg.desc_pairs for rec in chars[ck]["recs"])]
        if cks:
            native_of[a["hash"]] = cks
            reg.stats["animset_native_by_descriptor"] += 1
    has_native = {ck for cks in native_of.values() for ck in cks}
    for a in corpus.animsets.values():
        bones = frozenset(a["bones"])
        if a["hash"] in native_of or a["hash"] in paired_sets or not a["units"] or not bones:
            continue
        cks = [ck for rh in by_set.get(bones, []) for ck in chars_of_rig[rh]
               if ck not in has_native and set(a["units"]) <= set(chars[ck]["units"])]
        if cks:
            native_of[a["hash"]] = cks
            reg.stats["animset_native_by_containers"] += 1
    for a in corpus.animsets.values():
        bones = frozenset(a["bones"])
        same = by_set.get(bones, []) if bones else []
        if a["hash"] in native_of:
            give(a, native_of[a["hash"]], "animset")
            continue
        hosts = [ck for rh in same for ck in chars_of_rig[rh]]
        if len(same) > 1:
            # several skeletons with one bone list: the one the anim-set
            # shares most containers with
            au = set(a["units"])
            best = max(same, key=lambda rh: (len(au & set(reg.rigs[rh]["units"])), -rh))
            hosts = list(chars_of_rig[best])
            reg.stats["animset_bone_list_on_several_skeletons"] += 1
        if len(bones) >= FAMILY_MIN_BONES:
            for rh, hs in hset.items():
                if rh not in same and bones < hs and len(bones) >= FAMILY_MIN * len(hs):
                    hosts += chars_of_rig[rh]
        if not hosts:
            reg.stats["animset_without_skeleton"] += 1
            continue
        reg.stats["animset_moveset"] += 1
        give(a, hosts, "moveset")

    clip_rows = []
    for k, c in reg.clips.items():
        if targets.get(k):
            continue
        best = None
        for rh, r in reg.rigs.items():
            ov, nb = cover(c, r)
            if nb and ov / nb >= MIN_COVER:
                cand = (ov, -r["skel"].n, rh)
                if best is None or cand > best:
                    best = cand
        if best is None:
            reg.stats["clips_rig_absent"] += 1
            clip_rows.append(dict(
                clip=f"{k:08x}", name=c["glb_name"], label_source=c["label_source"], rig="",
                rig_label="", status="rig_absent", how="", clip_rig=f"{c['rig_hash']:08x}",
                clip_bones=sum(h != NO_BONE for h in c["bone_hashes"]), bones_bound=0,
                bones_lost=0, duration=round(c["duration"], 3), bones_animated=len(c["tracks"]),
                part="", sources=";".join(reg.clip_sources.get(k, [])[:6])))
        else:
            targets[k][chars_of_rig[best[2]][0]] = "cover"
            reg.stats["clips_bound_by_cover"] += 1

    by_char = defaultdict(list)
    for k, tg in targets.items():
        for ck, how in tg.items():
            by_char[ck].append((reg.clips[k], how))
    only = {int(h, 16) for h in args.rigs.split(",")} if args.rigs else None
    rig_rows = []
    rig_load = Counter()
    for ck, items in by_char.items():
        rig_load[ck[0]] += len(items)
    order = sorted(chars, key=lambda ck: (-rig_load[ck[0]], ck[0], -len(by_char.get(ck, [])), ck[1]))
    if args.plan:
        for ck in order:
            if by_char.get(ck):
                ch = chars[ck]
                hc = Counter(h for _c, h in by_char[ck])
                print(f"rig {ck[0]:08x} rec {ck[1]:08x} {char_label(reg, corpus, ch):26s} "
                      f"bones {reg.rigs[ck[0]]['skel'].n:3d} mesh {[f'{m:08x}' for m in ch['mesh_refs']]} "
                      f"native {sorted(corpus.animset_label(x) for x in ch['native'])} "
                      f"movesets {len(ch['movesets'])} clips {dict(hc)}")
        for k, v in reg.stats.most_common():
            if k.startswith(("animset", "clips_")):
                print(f"  {k:40s} {v}")
        return
    last_rig = None
    for ck in order:
        rh, ch = ck[0], chars[ck]
        if only and rh not in only:
            continue
        if not by_char.get(ck) and not args.all_rigs:
            continue
        if rh != last_rig:
            reg.bake_cache.clear()
            last_rig = rh
        label = char_label(reg, corpus, ch)
        set_names = (sorted({corpus.animset_label(a) for a in ch["native"]}),
                     sorted({corpus.animset_label(a) for a in ch["movesets"]}))
        try:
            extract_rig(args, reg, ch, by_char.get(ck, []), label, set_names,
                        rig_rows, clip_rows, t0)
        except Exception as e:
            traceback.print_exc()
            reg.stats["rig_failed"] += 1
            rig_rows.append(dict(rig=f"{rh:08x}", skel_record=f"{ck[1]:08x}", label=label,
                                 bones=reg.rigs[rh]["skel"].n, mesh_how=f"FAILED:{e!r}"[:120]))
    reg.bake_cache.clear()

    with open(out / "rigs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RIG_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rig_rows)
    with open(out / "clips.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CLIP_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(clip_rows)
    status = Counter(r["status"] for r in clip_rows)
    baked_clips = {r["clip"] for r in clip_rows if r["status"] == "baked"}
    lines = [f"units scanned      {reg.unit_count}",
             f"rigs (skeletons)   {len(reg.rigs)}",
             f"characters exported {len(rig_rows)} "
             f"({len({r['rig'] for r in rig_rows})} skeletons)",
             f"unique clips       {len(reg.clips)}",
             f"clips baked        {len(baked_clips)} unique, "
             f"{status.get('baked', 0)} bakes (a clip is baked once per character that plays it)",
             "clip status:"] + \
            [f"  {k:22s} {v}" for k, v in status.most_common()] + \
            ["decoder and binding stats:"] + \
            [f"  {k:32s} {v}" for k, v in reg.stats.most_common()] + \
            ["names:"] + ["  " + ln for ln in nsum.splitlines()] + \
            [f"elapsed {time.time()-t0:.0f}s"]
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", help="root holding one decoded unit dir per .lu")
    ap.add_argument("--scripts", required=True, help="pip_scripts.py extract output")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--units", default="*")
    ap.add_argument("--vocab", action="append", default=[],
                    help="extra name list for pip_names (NB1's cracked names)")
    ap.add_argument("--rigs", help="only these skeleton rig hashes (hex, comma-separated)")
    ap.add_argument("--rate", type=float, default=30.0)
    ap.add_argument("--max-mb", type=float, default=200.0)
    ap.add_argument("--all-rigs", action="store_true",
                    help="also write a static GLB for rigs no clip plays on")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--plan", action="store_true",
                    help="print which character gets which clips and stop")
    ap.add_argument("--no-scale", action="store_true")
    ap.add_argument("--keep-asset-weights", action="store_true",
                    help="do not apply ASSET_WEIGHT_FIXES (shipped skin-weight errors)")
    cmd_extract(ap.parse_args())


if __name__ == "__main__":
    main()
