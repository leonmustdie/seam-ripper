#!/usr/bin/env python3
"""
lu_anim2.py — Naughty Bear (X360) .lu animation extractor, second iteration.

Clean rebuild. The byte-level decode is unchanged from v1 (every stage is
traceable from the raw .lu to the output floats); the rebuild separates the
PROVEN decode from the composition semantics that are still under test, and
makes the latter switchable at runtime.

Proven (validated against file bytes and pose statistics):
  * clip <-> skeleton binding by rig identity hash (clip+0x4C == skel+0x44)
  * channel families and exact size laws, incl. flags>>24 = quantization
    bit width and the 0x74 family's 4 bit-fields per key
  * all families store deltas; statics are truncated-LE-f32 deltas + tag
  * translation deltas apply in the PARENT frame (bone-length preservation
    is exact on non-layer clips)
  * rotation deltas compose on the PARENT side (pre-multiply); treating the
    values as quaternion components is wrong (values reach 2.0 rad and the
    quat reading doubles every angle)
  * hermite1 keys ship unsorted; sorting is lossless
  * ~40% of clips are trajectory layers: bone 0 carries extracted root
    motion, bone 2 its counter (corr -0.98, slope -1.02); standalone
    playback tears the hips from the legs by design, not by mis-decode

Open (undecidable from these files; flags below, resolve via the XEX
animation evaluator):
  * rotation vector (exponential map) vs Euler angles, and if Euler, the
    axis order. All pre-multiply candidates agree within 0.2 deg on pose
    statistics; they diverge up to ~65 deg on the 1.2% of samples with
    large multi-axis rotations (spine root, facial controllers).
  * tags 0x08/09/0a: not geometric scale (values to ~10 on facial
    controller bones); excluded from GLB output, present in JSON.
  * tags 0x00/01/02: weight-like curves (~1.0), JSON only.

usage:
  python3 lu_anim2.py extract <unit_dir>... -o out/ [--json] [--rot MODEL]
          [--include-layered-in-main] [--scale] [--rate N] [--names FILE]
          [--clips H1,H2,...]
      writes <unit>_rig_<hash>.glb        (non-layer clips)
             <unit>_rig_<hash>_layers.glb (trajectory-layer clips)
  python3 lu_anim2.py eval <unit_dir>...
      pose-statistics table across all rotation models
  python3 lu_anim2.py sheet <unit_dir>... -o sheet.png --clips H1[,H2...]
          [--rot MODEL] [--frames N]
      skeleton contact sheet, no Blender needed

rotation models (--rot): rotvec (default), xyz, zyx, yxz, zxy, xzy, yzx
"""
import argparse
import json
import math
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from lu_rig import (parse_skeleton, decompose_trs, bone_label,
                    extract_skinned_mesh, solve_palette, nearest_bone)

TAG_T = {0x04: 0, 0x05: 1, 0x06: 2}
TAG_R = {0x23: 0, 0x24: 1, 0x25: 2}
# 0x00-02 are ABSOLUTE scale (1.0 at rest; face bones squash and stretch).
# 0x08-0a are a second 3-vector whose meaning is still open; decoded, kept
# in the clip, not applied.
TAG_S = {0x00: 0, 0x01: 1, 0x02: 2}
TAG_X = {0x08: 0, 0x09: 1, 0x0A: 2}
KNOWN_TAGS = set(TAG_T) | set(TAG_R) | set(TAG_S) | set(TAG_X)
HERMITE_TPS = 240.0
U16_TPS = 30.0
LAYER_THRESHOLD = 0.25


# ---------------------------------------------------------------- quaternions

def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw*bx + ax*bw + ay*bz - az*by,
                     aw*by - ax*bz + ay*bw + az*bx,
                     aw*bz + ax*by - ay*bx + az*bw,
                     aw*bw - ax*bx - ay*by - az*bz])


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def rotvec_quat(v):
    a = float(np.linalg.norm(v))
    if a < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    s = math.sin(a/2) / a
    return np.array([v[0]*s, v[1]*s, v[2]*s, math.cos(a/2)])


def axis_quat(axis, a):
    q = [0.0, 0.0, 0.0, math.cos(a/2)]
    q[axis] = math.sin(a/2)
    return np.array(q)


EULER_ORDERS = {"xyz": (0, 1, 2), "zyx": (2, 1, 0), "yxz": (1, 0, 2),
                "zxy": (2, 0, 1), "xzy": (0, 2, 1), "yzx": (1, 2, 0)}


QUATCOMP = object()


def make_delta_fn(model):
    if model == "quatcomp":
        return QUATCOMP
    if model == "rotvec":
        return rotvec_quat
    order = EULER_ORDERS[model]

    def euler(v):
        q = np.array([0.0, 0.0, 0.0, 1.0])
        for ax in order:
            if v[ax]:
                q = qmul(q, axis_quat(ax, v[ax]))
        return q
    return euler


def compose_rot(dq, rq, side="pre"):
    """Compose a rotation delta with the rest quat on the given side."""
    return qmul(dq, rq) if side == "pre" else qmul(rq, dq)


def quatcomp_quat(v, rq):
    """REFUTED model (kept only for the record). Read channel values as
    quaternion COMPONENT deltas: xyz = rest_xyz + v, w = sqrt(1-|xyz|^2),
    normalize. Disproven by the clip data itself: w=sqrt(1-|xyz|^2) needs
    |xyz|^2 <= 1, but 2.2% of real rotation keys have x^2+y^2+z^2 > 1 (up to
    5.38) and single channels reach 2.0 rad. At those keys w goes imaginary
    and the rotation is destroyed, so the engine cannot use this. The earlier
    xenia memory 'match' was a false positive (delta sat next to the
    ubiquitous normalized (1,1,1) vector). Values are ANGLES -> the model is
    rotvec or Euler (see EULER_ORDERS). Do NOT use quatcomp for extraction.
    """
    xyz = np.asarray(rq[:3], float) + np.asarray(v, float)
    n2 = float(xyz @ xyz)
    w = math.sqrt(max(0.0, 1.0 - n2))
    q = np.array([xyz[0], xyz[1], xyz[2], w])
    n = float(np.linalg.norm(q))
    return q / n if n > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])


# ------------------------------------------------------------------ skeleton

class Skeleton:
    def __init__(self, chunk):
        self.bones = parse_skeleton(chunk)
        self.rig_hash = struct.unpack_from(">I", chunk, 0x44)[0]
        self.n = len(self.bones)
        # +0x18 {ptr, count}: per-bone quaternion xyzw. This is the JOINT
        # ORIENT (Maya-style), not the rest rotation: local = orient * anim.
        # Body joints have orient == rest (their animated rotation is
        # identity at bind); face transforms have orient == identity;
        # mirrored face bones have a 180-degree orient, and conj(orient) *
        # rest reproduces their static clip rotations exactly.
        qptr, qn = struct.unpack_from(">2I", chunk, 0x18)
        self.jo = np.tile([0.0, 0.0, 0.0, 1.0], (self.n, 1))
        if qn == self.n and qptr + 16 * qn <= len(chunk):
            self.jo = np.array(struct.unpack_from(f">{4*qn}f", chunk, qptr),
                               float).reshape(qn, 4)
            self.jo /= np.maximum(np.linalg.norm(self.jo, axis=1, keepdims=True), 1e-12)
        self.parents = [b["parent"] for b in self.bones]
        self.rest = []
        for i, b in enumerate(self.bones):
            Wc = np.array(b["world"], float)
            p = self.parents[i]
            L = Wc if p < 0 else Wc @ np.linalg.inv(
                np.array(self.bones[p]["world"], float))
            self.rest.append(decompose_trs(L.T))
        pos = self.world_positions({})
        self.bind_pos = pos
        self.bind_len = np.array(
            [np.linalg.norm(pos[i] - pos[self.parents[i]])
             if self.parents[i] >= 0 else 0.0 for i in range(self.n)])
        self.len_mask = self.bind_len > 0.02

    def world_positions(self, pose):
        """pose: {bone: (t3, q4)} overrides of rest; -> world positions."""
        W = [None] * self.n
        out = np.zeros((self.n, 3))
        for i in range(self.n):
            rt, rq, rs = self.rest[i]
            t3, q = pose.get(i, (np.asarray(rt, float), np.asarray(rq, float)))
            M = np.eye(4)
            M[:3, :3] = quat_mat(q) @ np.diag(rs)
            M[:3, 3] = t3
            W[i] = M if self.parents[i] < 0 else W[self.parents[i]] @ M
            out[i] = W[i][:3, 3]
        return out


def f24(payload):
    """Static payload -> float. The word is b0 b1 b2 tag; V = b2<<16|b1<<8|b0
    is a 24-bit float: sign(1) | exponent(6, bias 31) | mantissa(17).
    NOT an IEEE f32 with the low byte dropped (the old reading): that has the
    exponent two bits too wide and squashes 0.17..0.85 into 1e-4..0.05.
    Fitted on 470 static words whose true value is known from the
    Euler/quaternion redundancy; a static scale of 1.0 is 0x3dffff."""
    v = ((payload & 0xFF) << 16) | (payload & 0xFF00) | (payload >> 16 & 0xFF)
    if v & 0x7FFFFF == 0:
        return 0.0
    mag = (1.0 + (v & 0x1FFFF) / 131072.0) * 2.0 ** (((v >> 17) & 0x3F) - 31)
    return -mag if v & 0x800000 else mag


def unpack_quant(buf, count, bits):
    if bits == 8:
        q = np.frombuffer(buf, "u1", count).astype(np.float64)
    elif bits == 16:
        q = np.frombuffer(buf, ">u2", count).astype(np.float64)
    elif bits == 32:
        q = np.frombuffer(buf, ">u4", count).astype(np.float64)
    else:
        b = np.unpackbits(np.frombuffer(buf, np.uint8))[:count * bits]
        w = (1 << np.arange(bits - 1, -1, -1)).astype(np.float64)
        q = b.reshape(count, bits).astype(np.float64) @ w
    return q / float((1 << bits) - 1)


# ---------------------------------------------------------------------- clip

def _decode_piece(d, hdr_off, stats):
    """One channel piece -> (seg_start, seg_end, coef[k,4]) or None.

    Piece header {f32 start, u16 kc, u16 enc, u32 dp, u32 dsz}. enc is three
    fields, and every keyed channel in the corpus fits the size law they
    imply:
      hi & 0x40      values are quantised: 12-byte {f32 offset, f32 range,
                     u32 bits<<24} then bit-packed, value = offset+range*q.
                     (NOT {min,max}: range is never negative.)
      (hi >> 4) & 3  key times: 0 = uniform, one key every 1/lo s from
                     `start`; 1 = f32 absolute seconds; 3 = u16 ticks at
                     lo/s RELATIVE to `start`
      hi & 0xF       floats per key: 8 -> one sample, linear to the next;
                     2,3,4 -> polynomial segment of degree 1,2,3;
                     0 -> one sample (near-constant channels, keys unsorted)
      lo             rate (0xF0 = 240, 0x1E = 30, 0x0F = 15, ...)
    Key k owns the segment [t[k-1], t[k]], t[-1] = start: key times are
    segment ENDS. A polynomial key is [c_n .. c1, c0] in normalised
    u = 0..1, so c0 is the value at the segment start and the sum of the
    coefficients the value at the key time (c0 of key k+1 equals the sum of
    key k on 17319 of 17322 unquantised channels). A one-sample key is the
    value at its segment START. All of this is pinned by the Euler /
    quaternion redundancy (tags 08-0a vs 23-25): under these rules the two
    agree to quantisation error in every encoding pairing, under any other
    origin they do not.
    """
    if hdr_off + 16 > len(d):
        stats["bad_ptr"] += 1
        return None
    start, kc, enc, dp, dsz = struct.unpack_from(">fHHII", d, hdr_off)
    if kc == 0 or dp + dsz > len(d) or not math.isfinite(start):
        stats["bad_hdr"] += 1
        return None
    hi, lo = enc >> 8, enc & 0xFF
    quant, tmode, nib = bool(hi & 0x40), (hi >> 4) & 3, hi & 0xF
    if hi & 0x80 or tmode == 2 or nib not in (0, 2, 3, 4, 8):
        stats[f"unknown_enc_{enc:04x}"] += 1
        return None
    nv = 1 if nib in (0, 8) else nib
    o, bits, off, rng = dp, 32, 0.0, 1.0
    if quant:
        if dsz < 12:
            stats["bad_hdr"] += 1
            return None
        off, rng, fl = struct.unpack_from(">ffI", d, dp)
        bits = fl >> 24
        o += 12
        if not (1 <= bits <= 32 and math.isfinite(off) and math.isfinite(rng)):
            stats["bad_quant_hdr"] += 1
            return None
    tb = (0, 4 * kc, 0, 2 * kc)[tmode]
    vb = (kc * nv * bits + 7) // 8
    if (o - dp) + tb + vb != dsz:
        stats[f"size_mismatch_{enc:04x}"] += 1
        return None
    rate = float(lo or 30)
    if tmode == 0:
        # samples sit at start + k/rate; the piece ends ON its last sample
        # (the next piece of a multi-piece channel starts exactly there)
        seg_end = start + np.minimum(np.arange(1, kc + 1), kc - 1) / rate
    elif tmode == 1:
        seg_end = np.frombuffer(d, ">f4", kc, o).astype(np.float64)
    else:
        seg_end = start + np.frombuffer(d, ">u2", kc, o).astype(np.float64) / rate
    if quant:
        vals = off + rng * unpack_quant(d[o + tb: o + tb + vb], kc * nv, bits)
    else:
        vals = np.frombuffer(d, ">f4", kc * nv, o + tb).astype(np.float64)
    vals = vals.reshape(kc, nv)
    if nib == 0 and not np.all(np.diff(seg_end) >= 0):
        order = np.argsort(seg_end, kind="stable")
        seg_end, vals = seg_end[order], vals[order]
        stats["nib0_resorted"] += 1
    if not np.all(np.diff(seg_end) >= 0):
        stats["keys_unsorted"] += 1
        return None
    seg_start = np.concatenate([[min(float(start), float(seg_end[0]))], seg_end[:-1]])
    coef = np.zeros((kc, 4))
    if nib in (0, 8):
        v = vals[:, 0]
        coef[:, 3] = v
        coef[:-1, 2] = np.diff(v)          # linear to the next sample
    else:
        coef[:, 4 - nv:] = vals
    stats[f"enc_{hi:02x}"] += 1
    return seg_start, seg_end, coef


def _decode_channel(d, rec_off, stats):
    """Channel record {u32 piece_ptr, u32 piece_count, f32 end, u32 tag<<24}
    -> channel dict or None. A channel is `piece_count` consecutive piece
    headers (almost always 1; 370 records in the corpus have 2-10), each
    with its own start, key count and encoding."""
    dptr, npieces, _end, _tagw = struct.unpack_from(">IIfI", d, rec_off)
    if not (1 <= npieces <= 64) or dptr + 16 * npieces > len(d):
        stats["keyed_bad_rec"] += 1
        return None
    parts = []
    for j in range(npieces):
        pc = _decode_piece(d, dptr + 16 * j, stats)
        if pc is None:
            return None
        parts.append(pc)
    if npieces > 1:
        stats["multi_piece_channel"] += 1
    seg_start = np.concatenate([x[0] for x in parts])
    seg_end = np.concatenate([x[1] for x in parts])
    coef = np.concatenate([x[2] for x in parts])
    ch = {"kind": "poly", "seg_start": seg_start, "seg_end": seg_end,
          "coef": coef, "start": float(seg_start[0])}
    if not np.all(np.diff(seg_end) >= -1e-6):
        # 196 channels: a piece starts up to a frame or two before the one
        # in front of it has run out. The later piece wins from its start.
        stats["pieces_overlap"] += 1
        ch["pieces"] = parts
        ch["piece_start"] = np.array([float(x[0][0]) for x in parts])
        if not np.all(np.diff(ch["piece_start"]) >= 0):
            stats["pieces_unsorted"] += 1
            return None
    # polyline through the segment ends, for callers that only np.interp
    ch["times"] = np.concatenate([seg_start[:1], np.maximum.accumulate(seg_end)])
    ch["values"] = np.concatenate([coef[:1, 3], coef.sum(axis=1)])
    return ch


def _eval_segments(T0, T1, C, ts):
    k = np.clip(np.searchsorted(T1, ts, side="left"), 0, len(T1) - 1)
    span = T1[k] - T0[k]
    ok = span > 1e-9
    u = np.where(ok, (ts - T0[k]) / np.where(ok, span, 1.0), 1.0)
    u = np.clip(u, 0.0, 1.0)
    out = np.zeros_like(ts)
    for j in range(C.shape[1]):            # Horner, highest power first
        out = out * u + C[k, j]
    return out


def sample_channel(ch, ts):
    """Evaluate a channel at times ts (array or scalar) -> array.
    Before the first key the first value holds, after the last the last."""
    ts = np.atleast_1d(np.asarray(ts, float))
    if ch.get("kind") != "poly":
        return np.interp(ts, ch["times"], ch["values"])
    if "pieces" not in ch:
        return _eval_segments(ch["seg_start"], ch["seg_end"], ch["coef"], ts)
    which = np.clip(np.searchsorted(ch["piece_start"], ts, side="right") - 1,
                    0, len(ch["pieces"]) - 1)
    out = np.zeros_like(ts)
    for j, (T0, T1, C) in enumerate(ch["pieces"]):
        m = which == j
        if m.any():
            out[m] = _eval_segments(T0, T1, C, ts[m])
    return out


def decode_clip(d, stats):
    """Clip record -> dict. The track table is `bone_count` x 16 bytes,
    {keyed_off, keyed_n, static_off, static_n} per BONE: a bone has a keyed
    slot (16-byte channel records) and a static slot (u32 words,
    f24 value << 8 | tag). Reading it as bone_count x 8 bytes, which every
    earlier version did, sees only the first half of the skeleton and puts
    bone k's channels on bone 2k (keyed) and 2k+1 (static)."""
    if len(d) < 0x70 or struct.unpack_from(">I", d, 0)[0] != 0x04300000:
        return None
    name_hash = struct.unpack_from(">I", d, 8)[0]
    duration = struct.unpack_from(">f", d, 0x10)[0]
    # Panic in Paradise (LUH containers) inserts a bone-name-hash table
    # {ptr, count} at +0x1c, which moves everything behind it down 0x10, and
    # widens a track entry to 24 bytes: {keyed_off, keyed_n, 0, 0,
    # static_off, static_n}. NB1 has efefefef at +0x1c. Channel records,
    # pieces and static words are the same in both games.
    pip = struct.unpack_from(">I", d, 0x1C)[0] != 0xEFEFEFEF
    bone_hashes = None
    if pip:
        if len(d) < 0x80:
            return None
        hptr, hn = struct.unpack_from(">2I", d, 0x1C)
        tptr, tc = struct.unpack_from(">2I", d, 0x30)
        rig_hash = struct.unpack_from(">I", d, 0x5C)[0]
        stride, mk_off = 24, 0x50
        if hn != tc or hptr + 4*hn > len(d):
            return None
        bone_hashes = list(struct.unpack_from(f">{hn}I", d, hptr)) if hn else []
    else:
        tptr, tc = struct.unpack_from(">2I", d, 0x20)
        rig_hash = struct.unpack_from(">I", d, 0x4C)[0]
        stride, mk_off = 16, 0x40
    if not (0 < tc < 2048) or tptr + stride*tc > len(d) or not math.isfinite(duration):
        return None

    tracks = {}
    statics_raw = {}
    for i in range(tc):
        if pip:
            ko, kn, xo, xn, so, sn = struct.unpack_from(">6I", d, tptr + i*24)
            if xo or xn:
                stats["pip_mid_slot_nonzero"] += 1
        else:
            ko, kn, so, sn = struct.unpack_from(">4I", d, tptr + i*16)
        if so != 0xFFFFFFFF and sn:
            if sn > 16 or so + 4*sn > len(d):
                stats["static_bad_slot"] += 1
            else:
                words = list(struct.unpack_from(f">{sn}I", d, so))
                statics_raw[i] = words
                for w in words:
                    if w & 0xFF not in KNOWN_TAGS:
                        stats[f"static_unknown_tag_{w & 0xFF:02x}"] += 1
                        continue
                    v = f24(w >> 8)
                    if math.isfinite(v) and abs(v) < 100.0:
                        tracks.setdefault(i, []).append(
                            {"tag": w & 0xFF, "times": np.array([0.0]),
                             "values": np.array([v]), "family": "static_f24",
                             "kind": "static", "start": 0.0})
                        stats["static_f24"] += 1
                    else:
                        stats["static_bad"] += 1
        if ko == 0xFFFFFFFF or kn == 0:
            continue
        if kn > 16 or ko + 16*kn > len(d):
            stats["keyed_bad_slot"] += 1
            continue
        for c in range(kn):
            tagw = struct.unpack_from(">I", d, ko + c*16 + 12)[0]
            if tagw >> 24 not in KNOWN_TAGS:
                stats[f"keyed_unknown_tag_{tagw >> 24:02x}"] += 1
                continue
            ch = _decode_channel(d, ko + c*16, stats)
            if ch is None:
                continue
            if not (np.all(np.isfinite(ch["coef"]))
                    and np.all(np.abs(ch["values"]) < 100)):
                stats["insane_values"] += 1
                continue
            ch["tag"] = tagw >> 24
            ch["family"] = "keyed"
            tracks.setdefault(i, []).append(ch)

    markers = []
    mptr, mcount = struct.unpack_from(">2I", d, mk_off)
    if mptr != 0xFFFFFFFF and 0 < mcount < 4096 and mptr + mcount*16 <= len(d):
        for k in range(mcount):
            a, b = struct.unpack_from(">2H", d, mptr + k*16)
            f = struct.unpack_from(">3f", d, mptr + k*16 + 4)
            if all(math.isfinite(x) for x in f):
                markers.append({"a": a, "b": b, "t": list(f)})

    out = {"name_hash": name_hash, "rig_hash": rig_hash,
           "duration": max(duration, 1e-3), "track_count": tc,
           "tracks": tracks, "statics": statics_raw, "markers": markers}
    if pip:
        out["bone_hashes"] = bone_hashes
        # header byte +0x60: 1 = ADDITIVE clip, channels are deltas (PIP_FORMAT.md 11.14)
        out["additive"] = bool(d[0x60])
    return out


# ------------------------------------------------------------------- posing

def euler_xyz_quat(e):
    """(n,3) Euler angles, R = Rz*Ry*Rx -> (n,4) xyzw. This is what tags
    0x08-0a hold; on bones that carry both, it equals the 0x23-25
    quaternion to quantisation error (median 0.001 over 2500 bone-clips)."""
    c, s_ = np.cos(e / 2), np.sin(e / 2)
    cx, cy, cz = c[:, 0], c[:, 1], c[:, 2]
    sx, sy, sz = s_[:, 0], s_[:, 1], s_[:, 2]
    return np.stack([sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz,
                     cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz], 1)


def quat_euler_xyz(q):
    x, y, z, w = q
    return np.array([math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)),
                     math.asin(max(-1.0, min(1.0, 2*(w*y - z*x)))),
                     math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))])


def bone_curves(chans, rest, ts, jo=None, additive=False):
    """Channels of one bone -> (T, Q, S) arrays over ts, each None when the
    clip does not drive that property.

    additive=True (PiP clip header byte +0x60): the channels are DELTAS, not
    absolute values. Translation deltas add (0 = none), scale deltas multiply
    (1 = none), the rotation delta is post-multiplied in animation space:
    local = orient * bind * delta. A component the clip leaves out is no
    change. The result is the delta shown on the bind pose.

    Every channel is an ABSOLUTE local value, not a delta from rest: 98.4%
    of static translations equal the bone's rest translation exactly, and a
    scale channel rests at 1.0. A component the clip leaves out keeps its
    rest value.
      0x04-06  translation xyz
      0x23-25  rotation, quaternion xyz with w = +sqrt(1 - |xyz|^2). The
               exporter keeps w >= 0 and writes a duplicate-time key pair
               where the quaternion crosses hemispheres.
      0x08-0a  the same rotation as Euler XYZ radians (used when the
               quaternion is absent or incomplete)
      0x00-02  scale xyz
    """
    rt, rq, rs = (np.asarray(x, float) for x in rest)
    n = len(ts)
    jo = np.array([0.0, 0.0, 0.0, 1.0]) if jo is None else np.asarray(jo, float)
    # the animated rotation at bind: rest = orient * bind  ->  bind = conj(orient) * rest
    rq = qmul(np.array([-jo[0], -jo[1], -jo[2], jo[3]]), rq)
    comp = {}
    for ch in chans:
        if ch["tag"] in comp and ch["family"] != "keyed":
            continue                      # a keyed channel wins over a static
        comp[ch["tag"]] = sample_channel(ch, ts)
    T = Q = S = None
    if any(t in comp for t in TAG_T):
        T = np.tile(rt, (n, 1))
        for t, ax in TAG_T.items():
            if t in comp:
                T[:, ax] = rt[ax] + comp[t] if additive else comp[t]
    if any(t in comp for t in TAG_S):
        S = np.tile(rs, (n, 1))
        for t, ax in TAG_S.items():
            if t in comp:
                S[:, ax] = rs[ax] * comp[t] if additive else comp[t]
    nr = sum(t in comp for t in TAG_R)
    nx = sum(t in comp for t in TAG_X)
    if nr and not (nx == 3 and nr < 3):
        v = np.zeros((n, 3)) if additive else np.tile((rq if rq[3] >= 0 else -rq)[:3], (n, 1))
        for t, ax in TAG_R.items():
            if t in comp:
                v[:, ax] = comp[t]
        w = np.sqrt(np.clip(1.0 - (v * v).sum(axis=1), 0.0, None))
        Q = np.concatenate([v, w[:, None]], axis=1)
        if additive:
            Q = np.array([qmul(rq, q) for q in Q])        # anim = bind * delta
    elif nx:
        e = np.tile(quat_euler_xyz(rq), (n, 1))
        for t, ax in TAG_X.items():
            if t in comp:
                e[:, ax] = comp[t]
        Q = euler_xyz_quat(e)
    if Q is not None:
        Q /= np.maximum(np.linalg.norm(Q, axis=1, keepdims=True), 1e-12)
        Q = np.array([qmul(jo, q) for q in Q])        # local = orient * anim
        for k in range(1, n):
            if Q[k] @ Q[k-1] < 0:
                Q[k] = -Q[k]
    return T, Q, S


def local_pose(clip, skel, t, delta_fn=None, include_scale=False, side="pre"):
    """-> {bone: (t3, q4)} at time t. delta_fn/side are accepted for old
    callers and ignored: there is no rotation-model choice any more."""
    pose = {}
    ts = np.array([float(t)])
    for i, chans in clip["tracks"].items():
        if i >= skel.n:
            continue
        T, Q, _S = bone_curves(chans, skel.rest[i], ts, skel.jo[i], clip.get("additive", False))
        if T is None and Q is None:
            continue
        rt, rq, _rs = skel.rest[i]
        pose[i] = (np.asarray(rt, float) if T is None else T[0],
                   np.asarray(rq, float) if Q is None else Q[0])
    return pose


def strip_orphan_root_counter(clip, stats):
    """Retired. The "orphan root counter" was never in the data: it was the
    pelvis's ABSOLUTE local translation (rest 0.998 up) being added to rest
    as if it were a delta, on the wrong bone because of the half-stride
    track table. Kept as a no-op so old call sites still run."""
    return False


def is_layered(clip, skel, delta_fn):
    worst = 0.0
    for t in (0.0, clip["duration"] * 0.5):
        pos = skel.world_positions(local_pose(clip, skel, t, delta_fn))
        L = np.array([np.linalg.norm(pos[i] - pos[skel.parents[i]])
                      if skel.parents[i] >= 0 else 0 for i in range(skel.n)])
        m = skel.len_mask
        if not m.any():          # 1-bone prop rigs: nothing measurable
            return False
        worst = max(worst, float(np.abs(L[m] / skel.bind_len[m] - 1).max()))
    return worst > LAYER_THRESHOLD


def bake_clip(clip, skel, rate, delta_fn=None, include_scale=True, side="pre"):
    dur = clip["duration"]
    n = max(2, int(round(dur * rate)) + 1)
    ts = np.linspace(0.0, dur, n)
    out = {}
    for bone, chans in clip["tracks"].items():
        if bone >= skel.n:
            continue
        T, Q, S = bone_curves(chans, skel.rest[bone], ts, skel.jo[bone], clip.get("additive", False))
        rec = {}
        if T is not None:
            rec["t"] = T
        if S is not None and include_scale:
            rec["s"] = np.clip(S, 1e-4, None)
        if Q is not None:
            rec["r"] = Q
        if rec:
            out[bone] = rec
    if include_scale:
        # A bone whose REST scale is not 1 (the bears' left-hand item bone
        # rests at 0.015) gets that scale keyed in every clip that does not
        # drive it. glTF keeps a node's rest scale by itself, but Blender
        # bones cannot hold one: without the key the importer plays the clip
        # at scale 1 and the 2 cm item shows up 66x too big.
        for bone in range(skel.n):
            rs = np.asarray(skel.rest[bone][2], float)
            if np.abs(rs - 1.0).max() > 1e-3 and "s" not in out.get(bone, {}):
                out.setdefault(bone, {})["s"] = np.tile(rs, (n, 1))
    return out, ts


# --------------------------------------------------------------- GLB writer

def build_glb(skel, submeshes, mapping, clip_map, out_path):
    bin_parts = []

    def push(data):
        off = sum(len(b) for b in bin_parts)
        bin_parts.append(data + b"\x00" * ((-len(data)) % 4))
        return off, len(data)

    accessors, buffer_views = [], []

    def accessor(data, comp, type_, count, minmax=None, target=None):
        off, ln = push(data)
        buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": ln,
                             **({"target": target} if target else {})})
        acc = {"bufferView": len(buffer_views) - 1, "componentType": comp,
               "count": count, "type": type_}
        if minmax:
            acc["min"], acc["max"] = minmax
        accessors.append(acc)
        return len(accessors) - 1

    mesh_prims = []
    for verts, uvs, joints, weights, tris, rigid, _refs, pal in submeshes:
        nv = len(verts)
        m = pal if pal else mapping          # shipped palette wins
        if rigid:
            nb = m[0] if pal else nearest_bone(verts, skel.bones)
            joints = [[nb, 0, 0, 0]] * nv
        else:
            joints = [[m[j] if j < len(m) else 0 for j in j4]
                      for j4 in joints]
        vmin = [min(v[k] for v in verts) for k in range(3)]
        vmax = [max(v[k] for v in verts) for k in range(3)]
        a_pos = accessor(b"".join(struct.pack("<3f", *v) for v in verts),
                         5126, "VEC3", nv, minmax=(vmin, vmax), target=34962)
        a_uv = accessor(b"".join(struct.pack("<2f", u, v) for u, v in uvs),
                        5126, "VEC2", nv, target=34962)
        joints = [[jj if 0 <= jj < skel.n else 0 for jj in j4] for j4 in joints]
        # One slot per joint. The shipped vertices repeat a joint in unused
        # slots, sometimes with a rounding-noise weight (1.0, 5e-8, 0, 5e-9
        # on joints 2, 3, 2, 2). glTF sums the slots, so that is harmless
        # there, but Blender's importer assigns slot by slot and the later
        # slot overwrites the earlier one: the vertex ends up unweighted and
        # stays at the origin while the character walks away. Repeats are
        # merged, noise is dropped, the rest is renormalised.
        cj, cw = [], []
        for j4, w4 in zip(joints, weights):
            acc_w = {}
            for jj, ww in zip(j4, w4):
                if ww > 1e-5:
                    acc_w[jj] = acc_w.get(jj, 0.0) + float(ww)
            if not acc_w:
                acc_w = {j4[0]: 1.0}
            items = sorted(acc_w.items(), key=lambda x: -x[1])[:4]
            tot = sum(w for _j, w in items)
            cj.append([j for j, _w in items] + [0] * (4 - len(items)))
            cw.append([w / tot for _j, w in items] + [0.0] * (4 - len(items)))
        joints, weights = cj, cw
        if skel.n <= 256:
            a_j = accessor(b"".join(struct.pack("<4B", *j) for j in joints),
                           5121, "VEC4", nv, target=34962)
        else:                       # glTF allows u16 joint indices
            a_j = accessor(b"".join(struct.pack("<4H", *j) for j in joints),
                           5123, "VEC4", nv, target=34962)
        a_w = accessor(b"".join(struct.pack("<4f", *w) for w in weights),
                       5126, "VEC4", nv, target=34962)
        a_i = accessor(b"".join(struct.pack("<3H", *t) for t in tris),
                       5123, "SCALAR", len(tris) * 3, target=34963)
        mesh_prims.append({"attributes": {"POSITION": a_pos, "TEXCOORD_0": a_uv,
                                          "JOINTS_0": a_j, "WEIGHTS_0": a_w},
                           "indices": a_i})

    Wr = [np.array(b["world"], float) for b in skel.bones]
    nodes = []
    for i in range(skel.n):
        t, q, sc = skel.rest[i]
        nodes.append({"name": bone_label(i, skel.bones), "translation": t,
                      "rotation": q, "scale": sc, "children": []})
    roots = []
    for i in range(skel.n):
        p = skel.parents[i]
        if p >= 0:
            nodes[p]["children"].append(i)
        else:
            roots.append(i)
    for nd in nodes:
        if not nd["children"]:
            nd.pop("children")

    animations = []
    for clip_name in sorted(clip_map):
        baked, ts = clip_map[clip_name]
        a_time = accessor(ts.astype("<f4").tobytes(), 5126, "SCALAR", len(ts),
                          minmax=([float(ts[0])], [float(ts[-1])]))
        samplers, channels = [], []
        for bone in sorted(baked):
            for g, path, type_ in (("t", "translation", "VEC3"),
                                   ("r", "rotation", "VEC4"),
                                   ("s", "scale", "VEC3")):
                if g not in baked[bone]:
                    continue
                a_out = accessor(baked[bone][g].astype("<f4").tobytes(),
                                 5126, type_, len(ts))
                samplers.append({"input": a_time, "output": a_out,
                                 "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1,
                                 "target": {"node": bone, "path": path}})
        if channels:
            animations.append({"name": clip_name, "samplers": samplers,
                               "channels": channels})

    gltf = {"asset": {"version": "2.0", "generator": "lu_anim2.py"},
            "scene": 0, "scenes": [{"nodes": list(roots)}], "nodes": nodes,
            "accessors": accessors, "bufferViews": buffer_views,
            "buffers": [{"byteLength": 0}]}
    if animations:
        gltf["animations"] = animations
    if mesh_prims:
        ibm = b"".join(np.linalg.inv(Wr[i]).T.astype("<f4").T.tobytes()
                       for i in range(skel.n))
        a_ibm = accessor(ibm, 5126, "MAT4", skel.n)
        mesh_node = len(nodes)
        nodes.append({"name": "mesh", "mesh": 0, "skin": 0})
        gltf["meshes"] = [{"primitives": mesh_prims}]
        gltf["skins"] = [{"inverseBindMatrices": a_ibm,
                          "joints": list(range(skel.n)),
                          "skeleton": roots[0]}]
        gltf["scenes"][0]["nodes"].append(mesh_node)

    gltf["buffers"][0]["byteLength"] = sum(len(b) for b in bin_parts)
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    bb = b"".join(bin_parts)
    Path(out_path).write_bytes(
        struct.pack("<3I", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bb))
        + struct.pack("<2I", len(js), 0x4E4F534A) + js
        + struct.pack("<2I", len(bb), 0x004E4942) + bb)


# --------------------------------------------------------------------- scan

def scan_units(unit_dirs):
    skeletons, clips, meshes = {}, [], {}
    for unit in unit_dirs:
        unit = Path(unit)
        for p in sorted(unit.rglob("*.bin")):
            d = p.read_bytes()
            if len(d) > 0x60 and struct.unpack_from(">I", d, 4)[0] == 0x04000001:
                try:
                    sk = Skeleton(d)
                except Exception:
                    continue
                if sk.n and (sk.rig_hash not in skeletons
                             or sk.n > skeletons[sk.rig_hash][0].n):
                    skeletons[sk.rig_hash] = (sk, unit.name)
        # naughty_lu names this dir from the resolved type name when it has
        # one and "type_<id>" when it does not, so accept both spellings.
        for cd in (unit / "anim_clip", unit / "type_04300000"):
            if cd.is_dir():
                clips += [(unit.name, p) for p in sorted(cd.glob("*.bin"))]
        md = unit / "mesh_buffers"
        if md.is_dir():
            best = max((p.read_bytes() for p in md.glob("*.bin")),
                       key=len, default=None)
            if best:
                meshes[unit.name] = best
    return skeletons, clips, meshes


def load_clips(clip_files, stats, names, only):
    seen = {}
    for unit, p in clip_files:
        d = p.read_bytes()
        clip = decode_clip(d, stats)
        if clip is None:
            stats["not_a_clip"] += 1
            continue
        if only and clip["name_hash"] not in only:
            continue
        key = (clip["name_hash"], clip["rig_hash"])
        if key in seen:
            stats["duplicate_clip_skipped"] += 1
            continue
        clip["name"] = names.get(clip["name_hash"], f"{clip['name_hash']:08x}")
        clip["source"] = f"{unit}/{p.name}"
        seen[key] = clip
    return list(seen.values())


# --------------------------------------------------------------------- eval

def cmd_eval(args):
    skeletons, clip_files, _ = scan_units(args.units)
    stats = Counter()
    clips = load_clips(clip_files, stats, {}, None)
    rig, (skel, unit) = max(skeletons.items(),
                            key=lambda kv: sum(1 for c in clips
                                               if c["rig_hash"] == kv[0]))
    base_fn = make_delta_fn("rotvec")
    pool = [c for c in clips if c["rig_hash"] == rig
            and c["track_count"] == skel.n and not is_layered(c, skel, base_fn)]
    print(f"rig {rig:08x} ({unit}): {len(pool)} non-layer clips")
    print(f"{'model':8s} {'tilt med':>8s} {'tilt p90':>8s} {'toe pen%':>8s} "
          f"{'knee dom%':>9s}")
    for model in ["quatcomp", "rotvec"] + list(EULER_ORDERS):
        fn = make_delta_fn(model)
        tilts, toes, knees = [], [], []
        for c in pool:
            for frac in (0.2, 0.5, 0.8):
                pos = skel.world_positions(
                    local_pose(c, skel, frac * c["duration"], fn,
                               side=args.rot_side))
                sp = pos[9] - pos[2]
                tilts.append(math.degrees(math.acos(
                    max(-1, min(1, sp[1] / (np.linalg.norm(sp) or 1))))))
                toes.append(min(pos[103][1], pos[111][1]))
                for knee in (101, 109):
                    cr = np.cross(pos[knee+1]-pos[knee], pos[knee+2]-pos[knee+1])
                    if np.linalg.norm(cr) > 1e-4:
                        knees.append(np.sign(cr[0]))
        t, ty, kn = map(np.array, (tilts, toes, knees))
        dom = 100*max((kn > 0).mean(), (kn < 0).mean()) if len(kn) else 0
        print(f"{model:8s} {np.median(t):8.1f} {np.percentile(t, 90):8.1f} "
              f"{100*(ty < -0.10).mean():8.1f} {dom:9.0f}")


# -------------------------------------------------------------------- sheet

def cmd_sheet(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    skeletons, clip_files, _ = scan_units(args.units)
    stats = Counter()
    clips = {c["name_hash"]: c for c in load_clips(clip_files, stats, {}, None)}
    want = [int(h, 16) for h in args.clips.split(",")]
    fn = make_delta_fn(args.rot)
    nf = args.frames
    fig, axes = plt.subplots(len(want), nf,
                             figsize=(3.2*nf, 4.2*len(want)), squeeze=False)
    for row, h in enumerate(want):
        c = clips[h]
        skel = skeletons[c["rig_hash"]][0]
        for col in range(nf):
            t = col / max(nf-1, 1) * c["duration"]
            pos = skel.world_positions(local_pose(c, skel, t, fn,
                                                  side=args.rot_side))
            ax = axes[row][col]
            for i in range(skel.n):
                p = skel.parents[i]
                if p < 0:
                    continue
                cl = "tab:red" if i >= 100 or p >= 100 else \
                     ("tab:blue" if i < 69 else "tab:green")
                ax.plot([pos[p][2], pos[i][2]], [pos[p][1], pos[i][1]],
                        color=cl, lw=1.1)
            ax.set_title(f"{h:08x} t={t:.2f}", fontsize=8)
            ax.set_aspect("equal")
            ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.out, dpi=75)
    print(f"wrote {args.out}")


# ------------------------------------------------------------------ extract

def cmd_extract(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = {}
    if args.names:
        for w in Path(args.names).read_text().splitlines():
            w = w.strip()
            if w:
                names[zlib.crc32(w.lower().encode()) & 0xFFFFFFFF] = w
    only = {int(h, 16) for h in args.clips.split(",")} if args.clips else None

    skeletons, clip_files, meshes = scan_units(args.units)
    print("skeletons: " + ", ".join(
        f"{h:08x} ({sk.n} bones, {u})" for h, (sk, u) in skeletons.items()))
    stats = Counter()
    clips = load_clips(clip_files, stats, names, only)
    fn = make_delta_fn(args.rot)

    jdir = out / "clips_json"
    if args.json:
        jdir.mkdir(exist_ok=True)
    per_rig = defaultdict(lambda: ({}, {}))
    unmatched = Counter()
    for clip in clips:
        if args.json:
            jd = {k: clip[k] for k in ("name", "name_hash", "rig_hash",
                                       "duration", "track_count", "markers",
                                       "source")}
            jd["statics_raw"] = {str(b): [f"{w:08x}" for w in ws]
                                 for b, ws in clip["statics"].items()}
            jd["tracks"] = {str(b): [
                {"tag": f"{c['tag']:02x}", "family": c["family"],
                 "times": [round(float(x), 6) for x in c["times"]],
                 "values": [round(float(x), 6) for x in c["values"]]}
                for c in chans] for b, chans in clip["tracks"].items()}
            (jdir / f"{clip['name']}.json").write_text(json.dumps(jd, indent=1))
        rig = clip["rig_hash"]
        if rig not in skeletons:
            unmatched[rig] += 1
            continue
        skel = skeletons[rig][0]
        if clip["track_count"] != skel.n:
            stats["track_bone_mismatch"] += 1
            continue
        strip_orphan_root_counter(clip, stats)
        layered = is_layered(clip, skel, fn)
        stats["layered_clips" if layered else "standalone_clips"] += 1
        baked, ts = bake_clip(clip, skel, args.rate, fn, args.scale,
                              side=args.rot_side)
        if not baked:
            continue
        main, layers = per_rig[rig]
        if layered and not args.include_layered_in_main:
            layers[clip["name"]] = (baked, ts)
        else:
            main[clip["name"] + ("__layer" if layered else "")] = (baked, ts)

    for rig, (main, layers) in per_rig.items():
        skel, unit = skeletons[rig]
        submeshes, mapping = [], []
        mesh = meshes.get(unit)
        if mesh:
            try:
                submeshes = extract_skinned_mesh(mesh)
                mapping = solve_palette(submeshes, skel.bones)
            except Exception as e:
                print(f"  ! mesh solve failed for {unit}: {e}")
                submeshes, mapping = [], []
        for label, cm in (("", main), ("_layers", layers)):
            if not cm:
                continue
            dest = out / f"{unit}_rig_{rig:08x}{label}.glb"
            build_glb(skel, submeshes, mapping, cm, dest)
            print(f"wrote {dest}  ({len(cm)} clips"
                  f"{', skinned' if submeshes else ', skeleton only'})")

    if unmatched:
        print("clips whose rig is absent (JSON only):")
        for rig, n in unmatched.most_common():
            print(f"  rig {rig:08x}: {n}")
    print("stats:")
    for k, v in stats.most_common():
        print(f"  {k:24s} {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("units", nargs="+")
        p.add_argument("--rot", default="rotvec",
                       choices=["quatcomp", "rotvec"] + list(EULER_ORDERS))
        p.add_argument("--rot-side", default="pre", choices=["pre", "post"],
                       help="compose rotation delta before (pre) or after "
                            "(post) the rest quaternion")

    px = sub.add_parser("extract")
    common(px)
    px.add_argument("-o", "--out", required=True)
    px.add_argument("--json", action="store_true")
    px.add_argument("--rate", type=float, default=30.0)
    px.add_argument("--names")
    px.add_argument("--clips")
    px.add_argument("--scale", action="store_true")
    px.add_argument("--include-layered-in-main", action="store_true")
    px.set_defaults(func=cmd_extract)

    pe = sub.add_parser("eval")
    common(pe)
    pe.set_defaults(func=cmd_eval)

    ps = sub.add_parser("sheet")
    common(ps)
    ps.add_argument("-o", "--out", required=True)
    ps.add_argument("--clips", required=True)
    ps.add_argument("--frames", type=int, default=5)
    ps.set_defaults(func=cmd_sheet)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
