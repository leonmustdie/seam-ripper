#!/usr/bin/env python3
"""
lu_corpus.py — corpus-wide Naughty Bear (X360) animation extraction.

lu_anim2.py works on one unit at a time and only bakes clips whose rig
skeleton is in that unit. Across the 998-file corpus that is the wrong
scope: a unit's clip records are mostly external references into shared
files (naughtybear.lu lists 137 clips, 60 local), and clips for one rig are
scattered over dozens of units. This tool builds ONE global registry over a
fully decoded corpus (see corpus_decode.py) and bakes every clip against
its rig wherever either lives.

Registry rules, all derived from the shipped bytes:
  * rig identity is the u32 at skeleton+0x44 and clip+0x4C
  * skeleton+0x08 = {ptr, count} -> list of {mesh_hash, 04000007} pairs:
    the skeleton names its own mesh(es). No geometric guessing needed to
    pair a skeleton with a mesh in units that carry several of each.
  * the unit descriptor chunk (type 00000102) references the skeleton as
    {skel_record_hash, 04000001}; its resolved name labels the rig.
  * clips dedupe on (name_hash, rig_hash); every source unit is recorded.
  * the anim-set chunk (type 04300012, one per rigged unit) carries at
    +0x34 {ptr, count} a table of RETARGET MAPS, 20 bytes each:
    {i16_map_ptr, n, hash_ptr, n, foreign_rig}. i16_map[j] is the local
    bone that foreign bone j drives (-1 = none); hash_ptr lists the foreign
    rig's bone name hashes, and local_bone_hash[i16_map[j]] == hash[j] on
    every mapped entry (verified on naughtybear, 5 foreign rigs). Clips
    whose rig has no skeleton anywhere (310 of 900, incl. the 116-bone
    d01a231e rig with 230 clips) are baked onto every local rig that maps
    them, named <clip>_rt<foreign_rig>.

Composition is lu_anim2's (LU_FORMAT.md section 28): every channel is an
absolute local value, rotation is a quaternion composed on the skeleton's
joint orient, nothing is stripped. The old root-counter stripping and the
--rot / --rot-side / --strip-min-bones options are kept only so old command
lines still parse; they no longer change the output.

Output, per rig: <label>_rig_<hash>[_pN].glb, split when a part would
exceed --max-mb. Plus rigs.csv, clips.csv, summary.txt.

usage:
  python lu_corpus.py corpus_decoded -o out_corpus [--rot rotvec] [--rate 30]
         [--units GLOB] [--rigs H1,H2] [--max-mb 200] [--strip-min-bones 50]
         [--no-retarget] [--json]
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
from lu_anim2 import (Skeleton, decode_clip, make_delta_fn,
                      strip_orphan_root_counter, is_layered, bake_clip,
                      build_glb, TAG_T, TAG_R)
from lu_rig import extract_skinned_mesh, solve_palette, find_palettes
from lu_convert import (_find_buffer_quads, _read_trailer, _decode_list,
                        _decode_strips, _find_texture_refs)

T_SKEL, T_MESH, T_CLIP = 0x04000001, 0x04000007, 0x04300000
T_UNITDESC, T_ANIMSET = 0x00000102, 0x04300012
CLIP_DIRS = ("type_04300000", "anim_clip")
SKEL_DIRS = ("unk_04000001",)
MESH_DIRS = ("mesh_buffers",)
ANIMSET_DIRS = ("type_04300012",)


# ---------------------------------------------------------------- manifest

def read_manifest(unit):
    """index -> (hash, name, type). naughty_lu names files NNNN_<name-or-hash>,
    so the manifest is the only reliable way back to the record hash when a
    name was resolved."""
    m = unit / "manifest.tsv"
    if not m.exists():
        return {}
    out = {}
    with open(m, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#") or line.startswith("index\t"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            try:
                out[int(parts[0])] = (int(parts[1], 16), parts[2], int(parts[3], 16))
            except ValueError:
                continue
    return out


def rec_index(path):
    try:
        return int(path.stem.split("_", 1)[0])
    except ValueError:
        return -1


def skeleton_mesh_refs(d):
    """skeleton+0x08 {ptr, count} -> [mesh_hash] ; keeps only 04000007."""
    ptr, cnt = struct.unpack_from(">2I", d, 8)
    if not (0 < cnt < 64) or ptr + 8 * cnt > len(d):
        return []
    out = []
    for i in range(cnt):
        h, t = struct.unpack_from(">2I", d, ptr + 8 * i)
        if t == T_MESH:
            out.append(h)
    return out


def unitdesc_skeleton_refs(d):
    """{hash, 04000001} pairs anywhere in a unit-descriptor chunk."""
    out = set()
    tag = struct.pack(">I", T_SKEL)
    i = d.find(tag, 4)
    while i >= 0:
        out.add(struct.unpack_from(">I", d, i - 4)[0])
        i = d.find(tag, i + 4)
    return out


def animset_retarget_maps(d):
    """anim-set (04300012) -> (own_rig, {foreign_rig: [i16 local index]})."""
    if len(d) < 0x60 or struct.unpack_from(">I", d, 0)[0] != T_ANIMSET:
        return None, {}
    own = struct.unpack_from(">I", d, 0x44)[0]
    bptr, bcnt = struct.unpack_from(">2I", d, 0x34)
    maps = {}
    if bptr == 0xFFFFFFFF or bcnt > 256 or bptr + 20 * bcnt > len(d):
        return own, maps
    for i in range(bcnt):
        p1, c1, p2, c2, rig = struct.unpack_from(">5I", d, bptr + 20 * i)
        if c1 != c2 or not (0 < c1 < 2048) or p1 + 2 * c1 > len(d) or p2 + 4 * c2 > len(d):
            continue
        maps[rig] = list(struct.unpack_from(f">{c1}h", d, p1))
    return own, maps


# -------------------------------------------------------------------- scan

class Registry:
    def __init__(self):
        self.rigs = {}            # rig_hash -> dict
        self.meshes = {}          # mesh_record_hash -> Path
        self.mesh_unit = {}       # mesh_record_hash -> unit name
        self.clips = {}           # (name_hash, rig_hash) -> clip dict
        self.clip_sources = defaultdict(list)
        self.skel_labels = defaultdict(set)   # skel_record_hash -> names
        self.retarget = defaultdict(dict)     # local_rig -> {foreign_rig: map}
        self.stats = Counter()
        self.unit_count = 0

    def scan_unit(self, unit):
        self.unit_count += 1
        man = read_manifest(unit)
        for sd in SKEL_DIRS:
            for p in sorted((unit / sd).glob("*.bin")) if (unit / sd).is_dir() else []:
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
                rec = man.get(rec_index(p))
                rec_hash = rec[0] if rec else struct.unpack_from(">I", d, 0)[0]
                r = self.rigs.get(sk.rig_hash)
                if r is None:
                    self.rigs[sk.rig_hash] = r = {
                        "skel": sk, "rec_hashes": set(), "units": [],
                        "mesh_refs": skeleton_mesh_refs(d), "path": p}
                elif r["skel"].n != sk.n:
                    self.stats["rig_hash_bone_count_conflict"] += 1
                r["rec_hashes"].add(rec_hash)
                r["units"].append(unit.name)
        for md in MESH_DIRS:
            for p in sorted((unit / md).glob("*.bin")) if (unit / md).is_dir() else []:
                rec = man.get(rec_index(p))
                if rec and rec[2] == T_MESH:
                    self.meshes.setdefault(rec[0], p)
                    self.mesh_unit.setdefault(rec[0], unit.name)
        ud = unit / "type_00000102"
        if ud.is_dir():
            for p in ud.glob("*.bin"):
                rec = man.get(rec_index(p))
                name = rec[1] if rec and rec[1] else p.stem.split("_", 1)[-1]
                for h in unitdesc_skeleton_refs(p.read_bytes()):
                    self.skel_labels[h].add(name)
        for ad in ANIMSET_DIRS:
            for p in sorted((unit / ad).glob("*.bin")) if (unit / ad).is_dir() else []:
                own, maps = animset_retarget_maps(p.read_bytes())
                if own is None:
                    continue
                for rig, m in maps.items():
                    prev = self.retarget[own].get(rig)
                    if prev is None:
                        self.retarget[own][rig] = m
                    elif prev != m:
                        self.stats["retarget_map_conflict"] += 1
        for cd in CLIP_DIRS:
            if not (unit / cd).is_dir():
                continue
            for p in sorted((unit / cd).glob("*.bin")):
                d = p.read_bytes()
                clip = decode_clip(d, self.stats)
                if clip is None:
                    self.stats["not_a_clip"] += 1
                    continue
                key = (clip["name_hash"], clip["rig_hash"])
                self.clip_sources[key].append(f"{unit.name}/{p.name}")
                if key in self.clips:
                    self.stats["duplicate_clip_record"] += 1
                    continue
                clip["name"] = f"{clip['name_hash']:08x}"
                self.clips[key] = clip

    def label(self, rig_hash):
        r = self.rigs[rig_hash]
        names = set()
        for h in r["rec_hashes"]:
            names |= self.skel_labels.get(h, set())
        names = sorted(names)
        if len(names) > 2:
            return f"{names[0]}+{len(names) - 1}more"
        if names:
            return "+".join(names)
        # fall back to the unit with the most clips for this rig
        per_unit = Counter()
        for (nh, rh), srcs in self.clip_sources.items():
            if rh == rig_hash:
                for s in srcs:
                    per_unit[s.split("/", 1)[0]] += 1
        for u in r["units"]:
            per_unit[u] += 0
        best = sorted(per_unit.items(), key=lambda kv: (-kv[1], kv[0]))
        return best[0][0] if best else f"rig{rig_hash:08x}"


def safe_name(s):
    return "".join(c if c.isalnum() or c in "-_+." else "_" for c in s)[:80]


# --------------------------------------------------------------- retarget

def retarget_clip(clip, imap, local_n, map_root=True):
    """Foreign-rig clip -> copy whose track indices are local bone indices.

    imap[j] = local bone for foreign bone j, -1 = unmapped. The engine's
    maps leave the foreign root (bone 0) unmapped; map_root keeps the
    foreign root's tracks on the local root so root motion survives."""
    new = dict(clip)
    new["tracks"], new["statics"] = {}, {}
    for j, chans in clip["tracks"].items():
        tgt = imap[j] if j < len(imap) else -1
        if tgt < 0 and j == 0 and map_root:
            tgt = 0
        if 0 <= tgt < local_n:
            new["tracks"][tgt] = list(chans)
    for j, ws in clip["statics"].items():
        tgt = imap[j] if j < len(imap) else -1
        if 0 <= tgt < local_n:
            new["statics"][tgt] = ws
    new["track_count"] = local_n
    new["retarget_from"] = clip["rig_hash"]
    new["rig_hash_native"] = clip["rig_hash"]
    new["name"] = f"{clip['name']}_rt{clip['rig_hash']:08x}"
    return new


def strip_counter_slot(clip, skel, stats):
    """Prop rigs: drop translation on zero-length children of the root only.
    That slot is the root-motion counter (bears: bone 2 via bone 1; props:
    bone 1). Part bones keep their translation."""
    hit = False
    for b, chans in list(clip["tracks"].items()):
        if b == 0 or skel.parents[b] != 0 or skel.bind_len[b] > 1e-4:
            continue
        kept = [ch for ch in chans if ch["tag"] not in TAG_T]
        if len(kept) != len(chans):
            clip["tracks"][b] = kept
            hit = True
    if hit:
        stats["prop_counter_slot_stripped"] += 1
    return hit


# ----------------------------------------------------------------- extract

def choose_mesh(reg, rig_hash):
    """The skeleton's own mesh reference list, first entry that yields
    geometry. Only when the skeleton names NO mesh at all does it fall back
    to the largest skinned mesh in a unit carrying the skeleton."""
    r = reg.rigs[rig_hash]
    tried = []
    for mh in r["mesh_refs"]:
        p = reg.meshes.get(mh)
        if p is None:
            tried.append(f"{mh:08x}:absent")
            continue
        try:
            subs, how = extract_rig_mesh(p.read_bytes(), r["skel"])
        except Exception:
            tried.append(f"{mh:08x}:error")
            continue
        if subs:
            if set(how) <= {"skinned", "shadow_skipped"}:
                return subs, f"{mh:08x}", "skeleton_ref"
            return subs, f"{mh:08x}", "parts(" + ",".join(
                f"{k}:{v}" for k, v in sorted(how.items())) + ")"
        tried.append(f"{mh:08x}:no_geometry")
    if r["mesh_refs"]:
        return [], "", "none(" + ";".join(tried) + ")"
    cands = [(mh, p) for mh, p in reg.meshes.items()
             if reg.mesh_unit[mh] in r["units"]]
    best = None
    for mh, p in cands:
        try:
            subs = extract_skinned_mesh(p.read_bytes())
        except Exception:
            continue
        nv = sum(len(s[0]) for s in subs)
        if subs and (best is None or nv > best[0]):
            best = (nv, subs, mh)
    if best:
        return best[1], f"{best[2]:08x}", "unit_fallback"
    return [], "", "none(no_mesh_ref)"


D3D_UBYTE4, D3D_F1, D3D_F2, D3D_F3, D3D_H2 = 0x1A2286, 0x2C83A4, 0x2C23A5, 0x2A23B9, 0x2C235F
U_POS, U_BW, U_BI, U_NRM, U_UV = 0, 1, 2, 3, 5


def parse_vertex_decl(d, o):
    """The submesh trailer's declaration pointer -> [(stream, offset, type,
    usage, usage_index)]. It is a plain Xbox 360 D3DVERTEXELEMENT9 array:
    12-byte elements {u16 stream, u16 offset, u32 type, u8 method, u8 usage,
    u8 usage_index, u8 pad}, closed by {0x00FF0000, 0xFFFFFFFF, 0}.

    lu_convert._parse_decl_at frames the same bytes one dword late (it takes
    the first element's stream/offset word for an "optional leading zero"),
    so it pairs each type with the NEXT element's offset and calls UBYTE4
    (0x1A2286, the blend indices) the position. That is why skinned props
    were read as rigid, with a position that started on the blend weight."""
    out = []
    for _ in range(24):
        if o + 12 > len(d):
            return None
        so, typ, mu = struct.unpack_from(">3I", d, o)
        if typ == 0xFFFFFFFF:
            return out
        out.append((so >> 16, so & 0xFFFF, typ, (mu >> 16) & 0xFF, (mu >> 8) & 0xFF))
        o += 12
    return None


def mesh_submodels(d):
    """Mesh record -> {trailer offset: (model id, sub-model offset)}.

    Record +0x00 {ptr, count} is an array of models, 16 bytes each:
    {id, hash, sub-model list ptr, count}; a list entry is {0x34200001,
    sub-model offset}. Model id 1 is the drawn model, id 2 (bears, birds,
    frog, SUV) holds the shadow-volume copy. A sub-model is one draw: +0x20
    bounding sphere, +0x40 -> its buffer quad, +0x4c -> its trailer, and at
    +0x60 either {bind-matrix ptr, count} with the palette at +0x74 (skinned)
    or, for a rigid part, the BONE INDEX it hangs on at +0x70."""
    out = {}
    try:
        mp, mn = struct.unpack_from(">2I", d, 0)
        if mp != 0x20 or not 0 < mn < 16:
            return out
        for i in range(mn):
            mid, _h, lp, ln = struct.unpack_from(">4I", d, mp + 16 * i)
            if ln > 4096 or lp + 8 * ln > len(d):
                return {}
            for k in range(ln):
                tag, sp = struct.unpack_from(">2I", d, lp + 8 * k)
                if tag != 0x34200001 or sp + 0x7c > len(d):
                    return {}
                out[struct.unpack_from(">I", d, sp + 0x4c)[0]] = (mid, sp)
    except struct.error:
        return {}
    return out


def extract_rig_mesh(d, skel):
    """Every drawable submesh of a rig's mesh record, laid out by its own
    vertex declaration -> (submeshes for build_glb, {how: count}).

    skinned  the declaration has BLENDINDICES (UBYTE4) and a palette
             descriptor follows the index buffer. Positions are in MODEL
             space; vertex index bytes go through the palette to skeleton
             bones. BLENDWEIGHT is FLOAT1/2/3 (the last weight is implied)
             or absent, in which case each vertex rides its first index
             alone: a one-submesh cooler is body (palette 0) plus lid
             (palette 1) that way. Count-1 palettes are the same case with
             every index 0, and are model space too (the cakemachine part on
             bone 15 is centred on the bind position of bone 15).
    shadow   BLENDINDICES but no NORMAL: the shadow-volume copy of the
             body. Skipped.
    rigid    no BLENDINDICES, no palette: a rigid part stored in the space
             of ONE bone, named by index in its sub-model header (+0x70, see
             mesh_submodels). 151 of 151 such parts in the corpus carry a
             valid index. Only if the header cannot be read does the old
             bounding-box guess run (anchor/compact in rigs.csv)."""
    quads = _find_buffer_quads(d)
    pals = find_palettes(d)
    subm = mesh_submodels(d)
    out, loose, how = [], [], Counter()
    lo = hi = None
    prev_field = 0x20
    for qi, (field_off, vo, vs, io_, isz) in enumerate(quads):
        refs = _find_texture_refs(d, prev_field, field_off)
        prev_field = io_ + isz
        tr = _read_trailer(d, io_, isz)
        if tr is None:
            continue
        t = (io_ + isz + 3) & ~3
        el = parse_vertex_decl(d, struct.unpack_from(">I", d, t + 16)[0])
        if not el:
            continue
        s0 = {}
        for st, off, typ, usage, ui in el:
            if st == 0:
                s0.setdefault((usage, ui), (off, typ))
        pos, bi = s0.get((U_POS, 0)), s0.get((U_BI, 0))
        stride, prim = tr["stride"], tr["prim"]
        if pos is None or pos[1] != D3D_F3 or vs % stride or pos[0] + 12 > stride:
            continue
        mid, sp = subm.get(t, (1, None))
        if mid == 2 or (bi and (U_NRM, 0) not in s0):
            how["shadow_skipped"] += 1
            continue
        n = vs // stride
        n_idx = isz // 2
        if prim == 4:
            n_idx = min(n_idx, tr["count"] * 3)
        raw = struct.unpack_from(f">{n_idx}H", d, io_)
        while raw and raw[-1] == 0xBFBF:
            raw = raw[:-1]
        tris = _decode_list(raw, n) if prim == 4 else _decode_strips(raw, n)
        if not tris:
            continue
        V = np.frombuffer(d, np.uint8, n * stride, vo).reshape(n, stride)

        def col(off, fmt, k):
            w = np.dtype(fmt).itemsize * k
            return np.frombuffer(V[:, off:off + w].tobytes(), fmt).reshape(n, k).astype(float)

        P = col(pos[0], ">f4", 3)
        if not np.all(np.isfinite(P)):
            continue
        uv = s0.get((U_UV, 0))
        if uv and uv[1] == D3D_H2 and uv[0] + 4 <= stride:
            uvs = [tuple(x) for x in col(uv[0], ">f2", 2)]
        else:
            uvs = [(0.0, 0.0)] * n
        after = io_ + isz
        nxt = quads[qi + 1][1] if qi + 1 < len(quads) else len(d)
        pal = next((q["bones"] for q in pals if after <= q["off"] < nxt), None)
        if bi and bi[1] == D3D_UBYTE4 and pal:
            bw = s0.get((U_BW, 0))
            wn = {D3D_F1: 1, D3D_F2: 2, D3D_F3: 3}.get(bw[1], 0) if bw else 0
            W4 = np.zeros((n, 4))
            if wn:
                W4[:, :wn] = col(bw[0], ">f4", wn)
                W4[:, wn] = np.clip(1.0 - W4[:, :wn].sum(axis=1), 0.0, None)
                W4 = np.clip(W4, 0.0, None)
                W4 /= np.maximum(W4.sum(axis=1, keepdims=True), 1e-9)
            else:
                W4[:, 0] = 1.0
            J = V[:, bi[0]:bi[0] + 4].astype(int)
            J[W4 <= 0] = 0                       # unused slots hold junk
            out.append(([tuple(map(float, v)) for v in P], uvs, J.tolist(), W4.tolist(),
                        tris, False, refs, [b if b < skel.n else 0 for b in pal]))
            lo = P.min(0) if lo is None else np.minimum(lo, P.min(0))
            hi = P.max(0) if hi is None else np.maximum(hi, P.max(0))
            how["skinned"] += 1
        elif not bi:
            ext = P.max(0) - P.min(0)
            if ext.max() > 200 or (ext > 1e-3).sum() < 2:
                continue                              # degenerate / misread
            bone = struct.unpack_from(">i", d, sp + 0x70)[0] if sp is not None else -1
            loose.append({"P": P, "uvs": uvs, "tris": tris, "refs": refs,
                          "bone": bone if 0 <= bone < skel.n else None})

    W = [np.array(b["world"], float) for b in skel.bones]

    def place(P, bone):
        return (np.c_[P, np.ones(len(P))] @ W[bone])[:, :3]

    for s in sorted(loose, key=lambda s: (s["bone"] is None, -len(s["P"]))):
        if s["bone"] is not None:
            bone, tag = s["bone"], "rigid"
        elif lo is None:
            bone, tag = 0, "anchor"
        else:
            best = None
            for b in range(skel.n):
                Q = place(s["P"], b)
                vol = float(np.prod(np.maximum(hi, Q.max(0)) - np.minimum(lo, Q.min(0))))
                key = (round(vol, 6), 1 if b == 0 else 0)
                if best is None or key < best[0]:
                    best = (key, b)
            bone, tag = best[1], "compact"
        Q = place(s["P"], bone)
        lo = Q.min(0) if lo is None else np.minimum(lo, Q.min(0))
        hi = Q.max(0) if hi is None else np.maximum(hi, Q.max(0))
        n = len(Q)
        out.append(([tuple(map(float, v)) for v in Q], s["uvs"], [[0, 0, 0, 0]] * n,
                    [[1.0, 0.0, 0.0, 0.0]] * n, s["tris"], True, s["refs"], [bone]))
        how[tag] += 1
    return out, how


def extract_prop_mesh(d, skel):
    """Rigid prop geometry (doors, traps, machines): every submesh is bound
    whole to one bone, and its vertices are stored in THAT BONE'S space
    (wardrobe01: each door's raw bounds are mirrored about the origin and
    land on the hinge bones only after the bind transform; the per-part
    header at +0x20 is a bone-space bounding sphere). Positions sit at the
    vertex declaration's position offset (implicit 0 on the unskinned
    stride-28/36/40 layouts; lu_rig's stride-40/32 table assumes +4 and
    misreads these).

    The part-to-bone table has not been found in the mesh chunk (no bone
    hash or index in the part headers), so binding is: a count-1 shipped
    palette when present; otherwise the largest part anchors at the origin
    (root) and every other part takes the bone whose bind transform keeps
    the assembled bounding box most compact, ties preferring an animatable
    non-root bone. Verified by render on wardrobe01 (doors on hinges);
    flagged 'compact' in rigs.csv because it is a heuristic. Nearest-bone
    on raw centroids was tried first and put both doors on the root.

    Returns (submeshes in MODEL space, {how: count})."""
    quads = _find_buffer_quads(d)
    pals = find_palettes(d)
    subs, prev_field = [], 0x20
    for qi, (field_off, vo, vs, io_, isz) in enumerate(quads):
        refs = _find_texture_refs(d, prev_field, field_off)
        prev_field = io_ + isz
        tr = _read_trailer(d, io_, isz)
        if tr is None or tr["decl"] is None:
            continue
        stride, prim, decl = tr["stride"], tr["prim"], tr["decl"]
        if vs % stride or decl[0] + 12 > stride:
            continue
        n = vs // stride
        n_idx = isz // 2
        if prim == 4:
            n_idx = min(n_idx, tr["count"] * 3)
        raw = struct.unpack_from(f">{n_idx}H", d, io_)
        while raw and raw[-1] == 0xBFBF:
            raw = raw[:-1]
        P = np.array([struct.unpack_from(">3f", d, vo + i * stride + decl[0])
                      for i in range(n)], float)
        if not np.all(np.isfinite(P)):
            continue
        ext = P.max(0) - P.min(0)
        if ext.max() > 200 or (ext > 1e-3).sum() < 2:
            continue                                  # degenerate / misread
        uv_off = decl[1] if decl[1] is not None and decl[1] + 4 <= stride else None
        uvs = [struct.unpack_from(">2e", d, vo + i * stride + uv_off)
               if uv_off is not None else (0.0, 0.0) for i in range(n)]
        lo = io_ + isz
        hi = quads[qi + 1][1] if qi + 1 < len(quads) else len(d)
        pal = next((p["bones"] for p in pals if lo <= p["off"] < hi), None)
        tris = _decode_list(raw, n) if prim == 4 else _decode_strips(raw, n)
        if not tris:
            continue
        subs.append({"P": P, "uvs": uvs, "tris": tris, "refs": refs,
                     "pal": pal if (pal and len(pal) == 1 and pal[0] < skel.n) else None})
    if not subs:
        return [], Counter()
    W = [np.array(b["world"], float) for b in skel.bones]

    def place(P, bone):
        return (np.c_[P, np.ones(len(P))] @ W[bone])[:, :3]

    how = Counter()
    order = sorted(range(len(subs)), key=lambda i: -len(subs[i]["P"]))
    lo = hi = None
    for idx in order:
        s = subs[idx]
        if s["pal"]:
            bone, tag = s["pal"][0], "palette"
        elif lo is None:
            bone, tag = 0, "anchor"
        else:
            best = None
            for b in range(skel.n):
                Q = place(s["P"], b)
                vol = float(np.prod(np.maximum(hi, Q.max(0)) - np.minimum(lo, Q.min(0))))
                key = (round(vol, 6), 1 if b == 0 else 0)
                if best is None or key < best[0]:
                    best = (key, b)
            bone, tag = best[1], "compact"
        Q = place(s["P"], bone)
        lo = Q.min(0) if lo is None else np.minimum(lo, Q.min(0))
        hi = Q.max(0) if hi is None else np.maximum(hi, Q.max(0))
        s["bone"], s["Q"] = bone, Q
        how[tag] += 1
    out = []
    for s in subs:
        n = len(s["P"])
        out.append(([tuple(map(float, v)) for v in s["Q"]], s["uvs"], [[0, 0, 0, 0]] * n,
                    [[1.0, 0.0, 0.0, 0.0]] * n, s["tris"], True, s["refs"], [s["bone"]]))
    return out, how


def est_bytes(baked, nframes):
    per = 0
    for rec in baked.values():
        per += 16 if "r" in rec else 0
        per += 12 if "t" in rec else 0
        per += 12 if "s" in rec else 0
    return nframes * (per + 4)


def clip_row(reg, c, rig_hash, label, status, **kw):
    key = (c.get("name_hash"), c.get("rig_hash_native", c["rig_hash"]))
    row = dict(clip=c["name"], rig=f"{rig_hash:08x}", rig_label=label, status=status,
               retarget_from=f"{c['retarget_from']:08x}" if "retarget_from" in c else "",
               duration=round(c["duration"], 3), tracks=c["track_count"],
               bones_animated=len(c["tracks"]), stripped=0, layered="", part="",
               sources=";".join(reg.clip_sources.get(key, [])))
    row.update(kw)
    return row


def short_tracks_match(clip, skel, tol=1e-3, min_obs=3):
    """True when every bone of a short clip that holds a complete static
    translation holds exactly the rest translation of skeleton bone k."""
    obs = 0
    for b, chans in clip["tracks"].items():
        if b >= skel.n:
            return False
        keyed = {ch["tag"] for ch in chans if ch["family"] == "keyed"}
        t = {ch["tag"]: float(ch["values"][0]) for ch in chans
             if ch["family"] != "keyed" and ch["tag"] in TAG_T and ch["tag"] not in keyed}
        if len(t) != 3:
            continue
        rt = skel.rest[b][0]
        if any(abs(v - rt[TAG_T[tag]]) > tol for tag, v in t.items()):
            return False
        obs += 1
    return obs >= min_obs


def extract_rig(args, reg, rig_hash, clips, fn, rig_rows, clip_rows, jdir, t0):
    out = Path(args.out)
    r = reg.rigs[rig_hash]
    skel = r["skel"]
    label = safe_name(reg.label(rig_hash))
    full_strip = skel.n >= args.strip_min_bones
    submeshes, mesh_hash, mesh_how = choose_mesh(reg, rig_hash)
    mapping = []
    if submeshes and any(s[7] is None for s in submeshes):
        try:
            mapping = solve_palette(submeshes, skel.bones) or []
        except Exception:
            mapping = []
    parts, cur, cur_bytes = [], {}, 0
    budget = args.max_mb * 1024 * 1024
    n_ok = n_rt = 0
    for c in sorted(clips, key=lambda c: c["name"]):
        retargeted = "retarget_from" in c
        if args.json and not retargeted:
            jd = {k: c[k] for k in ("name", "name_hash", "rig_hash", "duration",
                                    "track_count", "markers")}
            jd["sources"] = reg.clip_sources[(c["name_hash"], rig_hash)]
            jd["tracks"] = {str(b): [
                {"tag": f"{ch['tag']:02x}", "family": ch["family"],
                 "times": [round(float(x), 6) for x in ch["times"]],
                 "values": [round(float(x), 6) for x in ch["values"]]}
                for ch in chans] for b, chans in c["tracks"].items()}
            (jdir / f"{rig_hash:08x}_{c['name']}.json").write_text(json.dumps(jd))
        short = False
        if c["track_count"] != skel.n:
            # camerabird (35 tracks, 37 bones) and frog (47, 49): the clip
            # table stops two leaf bones early and bone k is still skeleton
            # bone k. Accepted only when the clip proves it: every bone that
            # carries a full static translation must sit on the rest
            # translation of the same-index skeleton bone. (The old note
            # here, "identity mapping refuted, 13.7 slip", was measured with
            # the 8-byte track table and is void.)
            if not (c["track_count"] < skel.n and short_tracks_match(c, skel)):
                reg.stats["track_bone_mismatch"] += 1
                clip_rows.append(clip_row(reg, c, rig_hash, label, "track_bone_mismatch"))
                continue
            short = True
            reg.stats["short_track_table"] += 1
        stripped = 0
        # No stripping any more. Channels are absolute local TRS; the old
        # "root counter" was the pelvis's rest translation read as a delta
        # (see lu_anim2.strip_orphan_root_counter).
        layered = int(is_layered(c, skel, fn))
        baked, ts = bake_clip(c, skel, args.rate, fn, not args.no_scale)
        if not baked:
            reg.stats["no_channels"] += 1
            clip_rows.append(clip_row(reg, c, rig_hash, label, "no_channels",
                                      stripped=stripped, layered=layered))
            continue
        b = est_bytes(baked, len(ts))
        if cur and cur_bytes + b > budget:
            parts.append(cur)
            cur, cur_bytes = {}, 0
        cur[c["name"]] = (baked, ts)
        cur_bytes += b
        status = "baked_retargeted" if retargeted else ("baked_short_tracks" if short else "baked")
        n_ok += 1
        n_rt += retargeted
        clip_rows.append(clip_row(reg, c, rig_hash, label, status, stripped=stripped,
                                  layered=layered, part=len(parts) + 1))
    if cur:
        parts.append(cur)
    files = []
    for pi, cm in enumerate(parts):
        suffix = f"_p{pi+1}" if len(parts) > 1 else ""
        dest = out / f"{label}_rig_{rig_hash:08x}{suffix}.glb"
        build_glb(skel, submeshes, mapping, cm, dest)
        files.append(dest.name)
    if not parts and not args.skip_empty_rigs:
        dest = out / f"{label}_rig_{rig_hash:08x}.glb"
        build_glb(skel, submeshes, mapping, {}, dest)
        files.append(dest.name)
    nv = sum(len(s[0]) for s in submeshes)
    rig_rows.append(dict(
        rig=f"{rig_hash:08x}", label=label, bones=skel.n,
        clips_unique=len(clips), clips_baked=n_ok, clips_retargeted=n_rt,
        mesh=mesh_hash, mesh_how=mesh_how, mesh_submeshes=len(submeshes),
        mesh_verts=nv, skinned=int(any(not s[5] for s in submeshes)),
        strip_mode="all_nonroot" if full_strip else "counter_slot",
        skel_units=len(r["units"]), skel_first_unit=r["units"][0],
        retarget_sources=";".join(f"{h:08x}" for h in sorted(reg.retarget.get(rig_hash, {}))),
        files=";".join(files)))
    print(f"rig {rig_hash:08x} {label:32s} {skel.n:4d} bones  "
          f"{n_ok:4d}/{len(clips):4d} clips ({n_rt} retargeted)  "
          f"mesh={mesh_how.split('(')[0]} {nv} verts  -> {len(files)} file(s)  "
          f"{time.time()-t0:.0f}s", flush=True)


RIG_FIELDS = ["rig", "label", "bones", "clips_unique", "clips_baked", "clips_retargeted",
              "mesh", "mesh_how", "mesh_submeshes", "mesh_verts", "skinned", "strip_mode",
              "skel_units", "skel_first_unit", "retarget_sources", "files"]
CLIP_FIELDS = ["clip", "rig", "rig_label", "status", "retarget_from", "duration", "tracks",
               "bones_animated", "stripped", "layered", "part", "sources"]


def cmd_extract(args):
    t0 = time.time()
    root, out = Path(args.corpus), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    units = sorted(p for p in root.glob(args.units) if p.is_dir())
    reg = Registry()
    for i, u in enumerate(units):
        reg.scan_unit(u)
        if (i + 1) % 200 == 0:
            print(f"scanned {i+1}/{len(units)} units, {len(reg.rigs)} rigs, "
                  f"{len(reg.clips)} unique clips, {time.time()-t0:.0f}s", flush=True)
    print(f"scan: {reg.unit_count} units, {len(reg.rigs)} rigs, "
          f"{len(reg.meshes)} meshes, {len(reg.clips)} unique clips "
          f"({sum(len(v) for v in reg.clip_sources.values())} records), "
          f"{sum(len(m) for m in reg.retarget.values())} retarget maps, "
          f"{time.time()-t0:.0f}s", flush=True)

    fn = make_delta_fn(args.rot)
    only_rigs = {int(h, 16) for h in args.rigs.split(",")} if args.rigs else None
    by_rig = defaultdict(list)
    for key, clip in reg.clips.items():
        by_rig[key[1]].append(clip)

    rig_rows, clip_rows = [], []
    jdir = out / "clips_json"
    if args.json:
        jdir.mkdir(exist_ok=True)

    # clips whose rig has no skeleton: retarget onto every local rig that
    # carries a map for it, or report them as absent.
    absent_rigs = [h for h in by_rig if h not in reg.rigs]
    for fr in absent_rigs:
        targets = [] if args.no_retarget else \
            [(loc, m) for loc, maps in reg.retarget.items()
             for r2, m in maps.items() if r2 == fr and loc in reg.rigs]
        if not targets:
            for c in by_rig[fr]:
                reg.stats["clips_rig_absent"] += 1
                clip_rows.append(clip_row(reg, c, fr, "", "rig_absent"))
            continue
        for loc, m in targets:
            n = reg.rigs[loc]["skel"].n
            for c in by_rig[fr]:
                by_rig[loc].append(retarget_clip(c, m, n, map_root=not args.no_map_root))
                reg.stats["clips_retargeted"] += 1

    for rig_hash in sorted(by_rig, key=lambda h: -len(by_rig[h])):
        if rig_hash not in reg.rigs:
            continue
        clips = by_rig[rig_hash]
        if only_rigs and rig_hash not in only_rigs:
            continue
        try:
            extract_rig(args, reg, rig_hash, clips, fn, rig_rows, clip_rows, jdir, t0)
        except Exception as e:
            traceback.print_exc()
            reg.stats["rig_failed"] += 1
            r = reg.rigs[rig_hash]
            rig_rows.append(dict(rig=f"{rig_hash:08x}", label="", bones=r["skel"].n,
                                 clips_unique=len(clips), clips_baked=0, clips_retargeted=0,
                                 mesh="", mesh_how=f"FAILED:{e!r}"[:120], mesh_submeshes=0,
                                 mesh_verts=0, skinned=0, strip_mode="", skel_units=len(r["units"]),
                                 skel_first_unit=r["units"][0], retarget_sources="", files=""))
            for c in clips:
                clip_rows.append(clip_row(reg, c, rig_hash, "", "rig_failed"))

    with open(out / "rigs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RIG_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rig_rows)
    with open(out / "clips.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CLIP_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(clip_rows)
    status = Counter(r["status"] for r in clip_rows)
    lines = [f"units scanned      {reg.unit_count}",
             f"rigs (skeletons)   {len(reg.rigs)}",
             f"rigs with clips    {len(by_rig)}",
             f"rigs exported      {len(rig_rows)}",
             f"unique clips       {len(reg.clips)}",
             f"clip records       {sum(len(v) for v in reg.clip_sources.values())}",
             f"retarget maps      {sum(len(m) for m in reg.retarget.values())} "
             f"({len(reg.retarget)} local rigs)",
             "clip status (retargeted copies counted per target rig):"] + \
            [f"  {k:22s} {v}" for k, v in status.most_common()] + \
            ["decoder stats:"] + [f"  {k:28s} {v}" for k, v in reg.stats.most_common()] + \
            [f"elapsed {time.time()-t0:.0f}s"]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", help="root holding one decoded unit dir per .lu")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--units", default="*", help="glob over unit dir names")
    ap.add_argument("--rigs", help="only these rig hashes (hex, comma-separated)")
    ap.add_argument("--rot", default="rotvec")
    ap.add_argument("--rot-side", default="pre", choices=["pre", "post"])
    ap.add_argument("--rate", type=float, default=30.0)
    ap.add_argument("--max-mb", type=float, default=200.0,
                    help="split a rig's GLB into parts above this many MB of animation data")
    ap.add_argument("--strip-min-bones", type=int, default=50,
                    help="full orphan root-counter stripping only for rigs with at least this many bones")
    ap.add_argument("--no-retarget", action="store_true",
                    help="do not bake clips of absent rigs through the anim-set retarget maps")
    ap.add_argument("--no-map-root", action="store_true",
                    help="when retargeting, leave the foreign root unmapped like the engine table does")
    ap.add_argument("--skip-empty-rigs", action="store_true",
                    help="do not write a GLB for rigs that end up with zero baked clips")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-scale", action="store_true",
                    help="do not export scale channels (tags 0x00-02)")
    args = ap.parse_args()
    cmd_extract(args)


if __name__ == "__main__":
    main()
