#!/usr/bin/env python3
"""Put a new model into a character mesh (Naughty Bear and Panic in Paradise):
any number of vertices and triangles, skinned to the character's skeleton.

  mesh_import.py roundtrip PATHS...   every retail part decoded, written back
                                      through the import path, compared

The library behind `mesh_replace.py export --rigged` and `mesh_replace.py
import`. A mesh record (LU_FORMAT.md 29.6, 33, 34) is a list of parts
(sub-models). An imported part takes the place of one part and keeps that
part's vertex declaration, skin palette, textures and material; its vertex
and triangle counts are free. What changes (LU_FORMAT 34.1):

  buffer quad {vb offset, vb size, ib offset, ib size}
  trailer: primitive count (+0x04), primitive type (+0x08, 4 list, 6 strip),
           vertex count (+0x1c), index count (+0x20)
  bounding sphere (sub-model +0x20)
  per palette bone radius (palette struct radii, and the {bone, radius}
           array at sub-model +0x74)

What stays: the inverse bind matrices (sub-model +0x60, one per skeleton
bone, the same in every part), the palette bones, the material block, every
other part.

Layout. Naughty Bear: the new vertex buffer, index buffer (both 4 KB
aligned), and copies of the trailer, declaration and palette struct are
appended at the end of the record, which grows (the container is laid out
again). Panic in Paradise hangs when a record changes size, so the new
buffers go where the old ones were: vertices at the old vertex buffer, indices
ending at the old trailer. A part that does not fit is refused with the
budget. A strip (0xFFFF restarts, as retail) takes about 40% of the bytes of
a list; `auto` writes a list and falls back to a strip when a list does not
fit.

A part can also be collapsed: its indices are zeroed, so every triangle is
degenerate and nothing is drawn. Counts and layout stay.
"""
import argparse
import base64
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lu_mesh as M                          # noqa: E402
from lu_mesh import (MeshError, U_POS, U_BW, U_BI, U_NRM, U_UV,   # noqa: E402
                     U_TAN, D3D_COLOR)

U_COL = 10
IMPORT_FORMAT = "seamripper-model-import"
TRAILER = 0x3C                   # trailer bytes; the declaration follows
PAL_STRUCT = 20                  # {bones ptr, n, inverse binds ptr, radii ptr, n}
MAX_VERTS = 0xFFFE               # 0xFFFF restarts a strip
BONE_RE = re.compile(r"^b(?:one)?[_ .]?(\d{1,3})(?![0-9])", re.I)
FILL = 0xBF
RADIUS_EPS = 1e-5            # implied last weights below this are float noise (34.2)


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def _al(v, a):
    return (v + a - 1) // a * a


# ------------------------------------------------------------------ record

def trailer_at(d, sm):
    return _u32(d, sm["sp"] + 0x4c)


def palette(d, sm):
    """Skin palette of a sub-model -> dict or None (rigid, shadow without one).
    bones: skeleton bone of each skin slot; radii: one float per slot."""
    tp = trailer_at(d, sm)
    ps = _u32(d, tp + 0x34)
    if ps == 0xFFFFFFFF or ps + PAL_STRUCT > len(d):
        return None
    bp, n, ibp, rp, n2 = struct.unpack_from(">5I", d, ps)
    if n != n2 or not 0 < n < 256 or bp + 4 * n > len(d) or rp + 4 * n > len(d):
        raise MeshError(f"sub-model {sm['n']}: unreadable palette at {ps:#x}")
    p8, n8 = struct.unpack_from(">2I", d, sm["sp"] + 0x74)
    return {"ps": ps, "bones": list(struct.unpack_from(f">{n}I", d, bp)), "bp": bp,
            "ibp": ibp, "rp": rp, "p8": p8 if n8 == n else None,
            "radii": np.array(struct.unpack_from(f">{n}f", d, rp), np.float64)}


def inverse_binds(d, sm=None):
    """Inverse bind matrices, one per skeleton bone (row-major, row vectors:
    v_bone = v_model @ IB) -> (n, 4, 4) or None. Every skinned sub-model of a
    mesh points at the same bytes; with sm None the first skinned one is read."""
    subs = [sm] if sm is not None else M.submodels(d)
    for s in subs:
        ibp, n = struct.unpack_from(">2I", d, s["sp"] + 0x60)
        if ibp != 0xFFFFFFFF and 0 < n < 1024 and ibp + 64 * n <= len(d):
            return np.array(struct.unpack_from(f">{16 * n}f", d, ibp),
                            np.float64).reshape(n, 4, 4)
    return None


def bind_world(IB):
    """Bind matrices (row vectors) of every bone from the inverse binds."""
    return np.linalg.inv(IB)


def rest_scale(IB):
    """Rest scale of every bone (the bind matrix's row lengths)."""
    BW = bind_world(IB)
    return np.linalg.norm(BW[:, :3, :3], axis=2).mean(1)


def scaled_part(d, sm, IB=None):
    """Does this part hang only on bones with a rest scale far from 1 (bear
    hand accessories, bone 78 at 0.015, LU_FORMAT 29.6.1)? Blender bones
    cannot hold a rest scale, so such a part does not survive Blender."""
    pal = palette(d, sm) if influences(sm) else None
    IB = inverse_binds(d) if IB is None else IB
    if pal is None or IB is None:
        return False
    rs = rest_scale(IB)
    return all(abs(rs[b] - 1) > 0.5 for b in pal["bones"] if b < len(rs))


def influences(sm):
    """Weights a vertex of this layout carries (0 = not skinned)."""
    if (U_BI, 0) not in sm["s0"]:
        return 0
    bw = sm["s0"].get((U_BW, 0))
    if bw is None:
        return 1
    return 1 + M._FMT[bw["type"]][1] if bw["type"] in M._FMT else 1


def _raw(d, sm, e, width):
    n, st = sm["verts"], sm["stride"]
    V = np.frombuffer(d, np.uint8, n * st, sm["vo"]).reshape(n, st)
    return np.ascontiguousarray(V[:, e["offset"]:e["offset"] + width])


def decode_part(d, sm):
    """A part as the neutral arrays the writer takes (see encode_part).
    Skin slots are kept in their order, as skeleton bones; slots past the
    layout's influence count keep whatever bone their byte names."""
    s0 = sm["s0"]
    part = {"kind": sm["kind"], "position": M.read_column(d, sm, U_POS).astype(np.float32)}
    N = M.read_column(d, sm, U_NRM)
    if N is not None and N.shape[1] == 3:
        part["normal"] = N.astype(np.float32)
    T = M.read_column(d, sm, U_TAN)
    if T is not None and T.shape[1] == 4:
        part["tangent"] = T.astype(np.float32)
    # sets by usage index; a set can be missing (a colour 1 with no colour 0)
    uvs, cols = [], []
    for k in range(8):
        e = s0.get((U_UV, k))
        ok = e is not None and e["type"] in M._FMT and M._FMT[e["type"]][1] == 2
        uvs.append(M.read_column(d, sm, U_UV, k).astype(np.float32) if ok else None)
    for k in range(4):
        e = s0.get((U_COL, k))
        ok = e is not None and e["type"] == D3D_COLOR
        cols.append(np.frombuffer(_raw(d, sm, e, 4).tobytes(), ">u4").astype(np.uint32)
                    if ok else None)
    while uvs and uvs[-1] is None:
        uvs.pop()
    while cols and cols[-1] is None:
        cols.pop()
    part["uv"], part["color"] = uvs, cols
    nI = influences(sm)
    if nI:
        pal = palette(d, sm)
        if pal is None:
            raise MeshError(f"sub-model {sm['n']}: skinned but no palette")
        slots = _raw(d, sm, s0[(U_BI, 0)], 4).astype(np.int64)
        lut = np.array(pal["bones"] + [-1] * (256 - len(pal["bones"])), np.int64)
        part["bones"] = lut[slots].astype(np.int16)
        n = sm["verts"]
        W = np.zeros((n, 4), np.float32)
        if nI > 1:
            k = nI - 1
            w = np.frombuffer(_raw(d, sm, s0[(U_BW, 0)], 4 * k).tobytes(), ">f4").reshape(n, k)
            W[:, :k] = w
            W[:, k] = np.float32(1) - w.sum(1, dtype=np.float32)
        else:
            W[:, 0] = 1
        part["weights"] = W
    part["triangles"] = M.triangles(d, sm).astype(np.int64)
    return part


# ------------------------------------------------------------------ encode

def _slot_table(bones):
    lut = np.full(1024, -1, np.int64)
    for i, b in enumerate(bones):
        lut[b] = i
    return lut


def skin_slots(sm, part, pal):
    """-> (slots (n,4) uint8, weights (n,4) float32) for this layout. A vertex
    whose weights all sit in the first nI slots keeps its slot order (so a
    retail part re-encodes byte for byte); any other is reduced to its nI
    heaviest bones, renormalised."""
    nI = influences(sm)
    J = np.asarray(part["bones"], np.int64)
    W = np.asarray(part["weights"], np.float32).copy()
    n = len(J)
    lut = _slot_table(pal["bones"])
    used = W > 0
    bad = used & ((J < 0) | (J >= len(lut)))
    if bad.any():
        raise MeshError(f"part {sm['n']}: weights on bones outside the skeleton")
    S = np.where((J >= 0) & (J < len(lut)), lut[np.clip(J, 0, len(lut) - 1)], -1)
    miss = used & (S < 0)
    if miss.any():
        bones = sorted(set(J[miss].tolist()))
        raise MeshError(f"part {sm['n']}: {int(miss.any(1).sum())} vertices are weighted to "
                        f"bones this part's palette does not hold ({bones[:12]}); "
                        f"its palette is {pal['bones']}")
    if (W.sum(1) <= 0).any():
        raise MeshError(f"part {sm['n']}: {int((W.sum(1) <= 0).sum())} vertices have no weights")
    redo = (W[:, nI:] > 0).any(1) if nI < 4 else np.zeros(n, bool)
    if redo.any():
        idx = np.flatnonzero(redo)
        order = np.argsort(-W[idx], axis=1, kind="stable")[:, :nI]
        Wr = np.take_along_axis(W[idx], order, 1)
        Sr = np.take_along_axis(S[idx], order, 1)
        Wr /= Wr.sum(1, keepdims=True)
        W[idx] = 0
        S[idx] = -1
        W[idx, :nI] = Wr
        S[idx, :nI] = Sr
    S = np.where(S < 0, 0, S)
    return S.astype(np.uint8), W


def encode_part(sm, part, pal=None):
    """Vertex buffer bytes for part in sub-model sm's own declaration."""
    P = np.asarray(part["position"], np.float32)
    n, st = len(P), sm["stride"]
    V = np.zeros((n, st), np.uint8)

    def put(e, arr, fmt):
        b = np.frombuffer(np.ascontiguousarray(arr.astype(fmt)).tobytes(), np.uint8)
        w = b.size // n if n else 0
        if e["offset"] + w > st:
            raise MeshError(f"part {sm['n']}: element at {e['offset']} runs past the stride")
        V[:, e["offset"]:e["offset"] + w] = b.reshape(n, w)
    nI = influences(sm)
    if nI:
        if "bones" not in part:
            raise MeshError(f"part {sm['n']} is skinned; the model has no skin weights")
        slots, W = skin_slots(sm, part, pal)
    for e in sm["decl"]:
        if e["stream"] != 0:
            continue
        u, k, t = e["usage"], e["index"], e["type"]
        if u == U_BI and k == 0:
            V[:, e["offset"]:e["offset"] + 4] = slots
        elif u == U_BW and k == 0 and t in M._FMT:
            c = M._FMT[t][1]
            put(e, W[:, :c], ">f4")
        elif u == U_POS and k == 0 and t in M._FMT:
            put(e, P[:, :M._FMT[t][1]], M._FMT[t][0])
        elif u == U_NRM and k == 0 and t in M._FMT:
            put(e, np.asarray(part["normal"], np.float32)[:, :M._FMT[t][1]], M._FMT[t][0])
        elif u == U_TAN and k == 0 and t in M._FMT:
            T = part.get("tangent")
            if T is None:
                uv0 = next((x for x in part.get("uv") or [] if x is not None), None)
                T = tangents(P, part["normal"], uv0, part["triangles"])
            put(e, np.asarray(T, np.float32)[:, :M._FMT[t][1]], M._FMT[t][0])
        elif u == U_UV and t in M._FMT:
            uvs = part.get("uv") or []
            have = [x for x in uvs if x is not None]
            uv = uvs[k] if k < len(uvs) and uvs[k] is not None else                 (have[0] if have else np.zeros((n, 2)))
            put(e, np.asarray(uv, np.float32)[:, :M._FMT[t][1]], M._FMT[t][0])
        elif u == U_COL and t == D3D_COLOR:
            cols = part.get("color") or []
            c = cols[k] if k < len(cols) and cols[k] is not None else                 np.full(n, 0xFFFFFFFF, np.uint32)
            put(e, np.asarray(c, np.uint32), ">u4")
        # anything else stays zero
    return V.tobytes()


def tangents(P, N, UV, tris):
    """Per-vertex tangent (x, y, z, w) from the texture coordinates, w = +-1
    (bitangent = w * cross(normal, tangent), the glTF convention)."""
    P = np.asarray(P, np.float64)
    N = np.asarray(N, np.float64)
    n = len(P)
    T = np.zeros((n, 3))
    B = np.zeros((n, 3))
    if UV is not None and len(tris):
        UV = np.asarray(UV, np.float64)
        t = np.asarray(tris, np.int64)
        e1, e2 = P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]]
        d1, d2 = UV[t[:, 1]] - UV[t[:, 0]], UV[t[:, 2]] - UV[t[:, 0]]
        r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        r = np.where(np.abs(r) < 1e-20, 0, 1 / np.where(np.abs(r) < 1e-20, 1, r))
        sd = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
        td = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r[:, None]
        for k in range(3):
            np.add.at(T, t[:, k], sd)
            np.add.at(B, t[:, k], td)
    T = T - N * (T * N).sum(1, keepdims=True)
    ln = np.linalg.norm(T, axis=1)
    fall = ln < 1e-12                      # no UV gradient: any perpendicular
    if fall.any():
        a = np.where(np.abs(N[fall, 0:1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
        T[fall] = np.cross(N[fall], a)
        ln = np.linalg.norm(T, axis=1)
    T /= np.maximum(ln, 1e-12)[:, None]
    w = np.where((np.cross(N, T) * B).sum(1) < 0, -1.0, 1.0)
    return np.c_[T, w].astype(np.float32)


def stripify(tris):
    """Triangle list -> strip indices with 0xFFFF restarts (the retail form).
    Two greedy passes, the shorter kept: SGI style (start from the free
    triangle with the fewest free neighbours) and in input order (a mesh
    that came from strips, as every retail part, gets its strips back)."""
    a = _stripify(tris, by_degree=True)
    b = _stripify(tris, by_degree=False)
    return a if len(a) <= len(b) else b


def _stripify(tris, by_degree=True):
    """One greedy pass: grow forward and backward while a triangle shares
    the end edge in the winding the strip's parity needs; a backward run of
    odd length takes one repeated vertex at the front to keep the parity."""
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    m = len(tris)
    T = tris.tolist()
    edge = {}
    for i, (a, b, c) in enumerate(T):
        for e in ((a, b), (b, c), (c, a)):
            edge.setdefault(e, []).append(i)
    used = [False] * m

    def free_nb(t):
        a, b, c = T[t]
        return sum(1 for e in ((b, a), (c, b), (a, c))
                   for k in edge.get(e, ()) if not used[k])

    def next_tri(a, b):
        best = None
        for t in edge.get((a, b), ()):
            if not used[t]:
                f = free_nb(t)
                if best is None or f < best[0]:
                    best = (f, t)
        return None if best is None else best[1]

    def third(t, a, b):
        x, y, z = T[t]
        for p, q, r in ((x, y, z), (y, z, x), (z, x, y)):
            if p == a and q == b:
                return r
        return None

    def grow(t, rot):
        a, b, c = T[t][rot:] + T[t][:rot]
        fwd, taken = [a, b, c], [t]
        used[t] = True
        while True:
            i = len(fwd) - 3                          # index of the last triangle
            p, q = (fwd[-2], fwd[-1]) if (i + 1) % 2 == 0 else (fwd[-1], fwd[-2])
            nt = next_tri(p, q)
            if nt is None:
                break
            used[nt] = True
            taken.append(nt)
            fwd.append(third(nt, p, q))
        back = []                                     # vertices before a, nearest first
        while True:
            p0, p1 = (back[-1], back[-2]) if len(back) >= 2 else \
                ((back[-1], a) if back else (a, b))
            r = -(len(back) + 1)                      # relative index of the new triangle
            e = (p1, p0) if r % 2 else (p0, p1)
            nt = next_tri(*e)
            if nt is None:
                break
            used[nt] = True
            taken.append(nt)
            back.append(third(nt, *e))
        s = back[::-1] + fwd
        if len(back) % 2:
            s = [s[0]] + s
        for k in taken:
            used[k] = False
        return s, taken

    out = []
    import heapq
    heap = [(free_nb(t) if by_degree else 0, t) for t in range(m)]
    heapq.heapify(heap)
    while heap:
        f, t = heapq.heappop(heap)
        if used[t]:
            continue
        cur = free_nb(t) if by_degree else 0
        if cur != f:                                  # stale priority: requeue
            heapq.heappush(heap, (cur, t))
            continue
        best = None
        for rot in range(3):
            s, taken = grow(t, rot)
            if best is None or len(taken) > len(best[1]) or \
                    (len(taken) == len(best[1]) and len(s) < len(best[0])):
                best = (s, taken)
        for k in best[1]:
            used[k] = True
        if out:
            out.append(0xFFFF)
        out.extend(best[0])
    return out


def strip_triangles(idx, n):
    """Decode strip indices as the game does (lu_mesh.triangles)."""
    tris, strip = [], []
    for t in list(idx) + [0xFFFF]:
        if t != 0xFFFF:
            strip.append(t)
            continue
        for i in range(len(strip) - 2):
            a, b, c = strip[i:i + 3]
            if len({a, b, c}) == 3 and max(a, b, c) < n:
                tris.append((a, c, b) if i & 1 else (a, b, c))
        strip = []
    return np.array(tris, np.int64).reshape(-1, 3)


# ------------------------------------------------------------------ write

def _round_up32(r):
    r32 = np.float32(r)
    while r32 < r:
        r32 = np.nextafter(r32, np.float32(np.inf))
    return float(r32)


def bounds(P):
    """Bounding sphere (centre of the box, radius to the farthest vertex)."""
    P = np.asarray(P, np.float64)
    c = (P.min(0) + P.max(0)) / 2
    return c, _round_up32(float(np.linalg.norm(P - c, axis=1).max()) if len(P) else 0.0)


def counted(W, nI):
    """Which weights reach a radius: every stored weight above 0; the implied
    last one (1 - the others) only above RADIUS_EPS, as it is float noise
    below that (LU_FORMAT 34.2)."""
    m = np.asarray(W) > 0
    if 1 < nI <= m.shape[1]:
        m[:, nI - 1] &= np.asarray(W)[:, nI - 1] > RADIUS_EPS
    return m


def bone_radii(P, slots, W, pal, IB, nI=4):
    """Radius of each palette slot: the farthest vertex it moves (counted
    weights) from its bone's bind position (LU_FORMAT 34.2). Slots no vertex
    uses keep their old value."""
    out = pal["radii"].copy()
    C = counted(W, nI)
    BW = bind_world(IB)
    P = np.asarray(P, np.float64)
    for j, b in enumerate(pal["bones"]):
        m = ((slots == j) & C).any(1)
        if m.any():
            out[j] = _round_up32(float(np.linalg.norm(P[m] - BW[b][3, :3], axis=1).max()))
    return out


def _pad(buf, a):
    buf.extend(bytes([FILL]) * ((-len(buf)) % a))


def collapse(buf, sm):
    """Zero a part's indices: every triangle degenerate, nothing drawn."""
    buf[sm["io"]:sm["io"] + sm["isz"]] = bytes(sm["isz"])


def check_part(part, sm):
    P = np.asarray(part["position"])
    n = len(P)
    if not n:
        raise MeshError(f"part {sm['n']}: no vertices")
    if n > MAX_VERTS:
        raise MeshError(f"part {sm['n']}: {n:,} vertices; a part holds at most {MAX_VERTS:,}")
    if not np.isfinite(P).all():
        raise MeshError(f"part {sm['n']}: a vertex position is not a number")
    t = np.asarray(part["triangles"])
    if not len(t):
        raise MeshError(f"part {sm['n']}: no triangles")
    if t.min() < 0 or t.max() >= n:
        raise MeshError(f"part {sm['n']}: a triangle names a vertex that does not exist")
    for key in ("normal", "tangent", "weights"):
        if part.get(key) is not None and len(part[key]) != n:
            raise MeshError(f"part {sm['n']}: {key} count differs from the vertex count")
    if (U_NRM, 0) in sm["s0"] and part.get("normal") is None:
        part["normal"] = M.smooth_normals(P.astype(np.float64), t).astype(np.float32)


def build_record(d, parts, game, primitive="auto", in_place=None, log=None):
    """Record d with parts replaced -> new record bytes.
    parts: {sub-model n: neutral part (decode_part form) or "collapse"}.
    game "nb1" appends (record grows) unless in_place; "pip" is always in
    place and refuses what does not fit."""
    log = log or (lambda s: None)
    if in_place is None:
        in_place = game == "pip"
    if game == "pip" and not in_place:
        raise MeshError("Panic in Paradise records keep their size: in place only")
    if primitive not in ("auto", "list", "strip"):
        raise MeshError(f"primitive '{primitive}'?")
    buf = bytearray(d)
    subs = M.submodels(d)
    IB = inverse_binds(d)
    for n in sorted(parts):
        if not 0 <= n < len(subs):
            raise MeshError(f"this mesh has no part {n} (parts 0 to {len(subs) - 1})")
        sm = subs[n]
        part = parts[n]
        if isinstance(part, str):
            if part != "collapse":
                raise MeshError(f"part {n}: '{part}'?")
            collapse(buf, sm)
            log(f"  sub{n:02d} ({sm['kind']}): collapsed (indices zeroed, nothing drawn)")
            continue
        if sm["kind"] == "shadow":
            raise MeshError(f"part {n} is the shadow volume; it can be kept or collapsed")
        check_part(part, sm)
        pal = palette(d, sm) if influences(sm) else None
        if influences(sm) and IB is None:
            raise MeshError(f"part {n}: no inverse bind matrices")
        vb = encode_part(sm, part, pal)
        nv = len(part["position"])
        tris = np.asarray(part["triangles"], np.int64)
        lst = tris.reshape(-1)
        cands = {"list": lst}
        if primitive in ("auto", "strip"):
            if primitive == "strip" or in_place:
                cands["strip"] = np.array(stripify(tris), np.int64)
        tp = trailer_at(buf, sm)
        if in_place:
            room = tp - sm["vo"]

            def fits(ix):
                return len(vb) + _al(2 * len(ix), 4) <= room
            order = ["strip"] if primitive == "strip" else \
                ["list"] if primitive == "list" else ["list", "strip"]
            pick = next((p for p in order if fits(cands[p])), None)
            if pick is None:
                need = len(vb) + _al(2 * len(cands[order[-1]]), 4)
                per_v = sm["stride"]
                raise MeshError(
                    f"part sub{n:02d} does not fit: {nv:,} vertices x {per_v} bytes + "
                    f"{len(cands[order[-1]]):,} indices ({order[-1]}) = {need:,} bytes; "
                    f"the record has {room:,} bytes for this part (Panic in Paradise "
                    f"keeps every record's size). Fewer vertices or triangles: at "
                    f"{len(tris):,} triangles about {(room - 3 * len(tris)) // per_v:,} "
                    f"vertices fit")
        else:
            pick = "strip" if primitive == "strip" else "list"
        idx = cands[pick]
        ib = np.asarray(idx, ">u2").tobytes()
        nidx = len(idx)
        prims = len(tris) if pick == "list" else nidx - 2
        if in_place:
            vo = sm["vo"]
            io = tp - _al(len(ib), 4)
            buf[vo:vo + len(vb)] = vb
            buf[vo + len(vb):io] = bytes([FILL]) * (io - vo - len(vb))
            buf[io:io + len(ib)] = ib
            buf[io + len(ib):tp] = bytes([FILL]) * (tp - io - len(ib))
            tr = tp
        else:
            old_tr = bytes(buf[tp:tp + TRAILER])
            declp, nel = struct.unpack_from(">2I", buf, tp + 0x10)
            psp = _u32(buf, tp + 0x34)
            _pad(buf, 0x1000)
            vo = len(buf)
            buf += vb
            _pad(buf, 0x1000)
            io = len(buf)
            buf += ib
            _pad(buf, 4)
            tr = len(buf)
            buf += old_tr
            if declp == tp + TRAILER:              # retail: decl right after
                dsz = 12 * nel
                buf += d[declp:declp + dsz]
                struct.pack_into(">I", buf, tr + 0x10, tr + TRAILER)
                if psp != 0xFFFFFFFF and psp == declp + dsz:
                    buf += d[psp:psp + PAL_STRUCT]
                    struct.pack_into(">I", buf, tr + 0x34, tr + TRAILER + dsz)
            struct.pack_into(">I", buf, sm["sp"] + 0x4c, tr)
        qp = _u32(buf, sm["sp"] + 0x40)
        struct.pack_into(">4I", buf, qp + 4, vo, len(vb), io, len(ib))
        struct.pack_into(">2I", buf, tr + 0x04, prims, 4 if pick == "list" else 6)
        struct.pack_into(">2I", buf, tr + 0x1c, nv, nidx)
        c, r = bounds(part["position"])
        struct.pack_into(">4f", buf, sm["sp"] + 0x20, *c.tolist(), r)
        extra = ""
        if pal is not None:
            slots, W = skin_slots(sm, part, pal)
            radii = bone_radii(part["position"], slots, W, pal, IB, influences(sm))
            struct.pack_into(f">{len(radii)}f", buf, pal["rp"], *radii.tolist())
            if pal["p8"] is not None:
                for j, (b, rr) in enumerate(zip(pal["bones"], radii.tolist())):
                    struct.pack_into(">If", buf, pal["p8"] + 8 * j, b, rr)
            extra = f", {len(set(np.unique(slots[W > 0]).tolist()))} of " \
                    f"{len(pal['bones'])} palette bones used"
        log(f"  sub{n:02d} ({sm['kind']}): {nv:,} vertices, {len(tris):,} triangles as a "
            f"{pick} ({nidx:,} indices){extra}; "
            + ("in place" if in_place else f"appended at {vo:#x}"))
    out = bytes(buf)
    if game == "pip" and len(out) != len(d):
        raise MeshError("record size changed")
    return out


# ------------------------------------------------------------------ neutral form

_ARR = {"position": ("<f4", 3), "normal": ("<f4", 3), "tangent": ("<f4", 4),
        "bones": ("<i2", 4), "weights": ("<f4", 4), "triangles": ("<u4", 3)}


def _b64(a, fmt):
    return base64.b64encode(np.ascontiguousarray(np.asarray(a).astype(fmt)).tobytes()).decode()


def _unb64(s, fmt, k, n=None):
    a = np.frombuffer(base64.b64decode(s), fmt)
    if k > 1:
        if a.size % k:
            raise MeshError("damaged model import (array size)")
        a = a.reshape(-1, k)
    if n is not None and len(a) != n:
        raise MeshError("damaged model import (array length)")
    return a


def parts_to_obj(parts, source=""):
    """Neutral, self-contained form of an import (the modder's geometry and
    weights by skeleton bone; no game bytes) for a .srpatch."""
    out = {}
    for n, p in sorted(parts.items()):
        if isinstance(p, str):
            out[str(n)] = {"collapse": True}
            continue
        q = {"vertices": int(len(p["position"])), "triangle_count": int(len(p["triangles"]))}
        for key, (fmt, k) in _ARR.items():
            if p.get(key) is not None:
                q[key] = _b64(p[key], fmt)
        q["uv"] = [None if u is None else _b64(u, "<f4") for u in p.get("uv") or []]
        q["color"] = [None if c is None else _b64(c, "<u4") for c in p.get("color") or []]
        out[str(n)] = q
    return {"format": IMPORT_FORMAT, "version": 1, "source": source, "parts": out}


def obj_to_parts(obj):
    if obj.get("format") != IMPORT_FORMAT:
        raise MeshError("not a Seam Ripper model import")
    if obj.get("version", 0) > 1:
        raise MeshError("this model import needs a newer Seam Ripper")
    parts = {}
    for key, q in obj["parts"].items():
        n = int(key)
        if q.get("collapse"):
            parts[n] = "collapse"
            continue
        nv = q["vertices"]
        if "position" not in q or "triangles" not in q:
            raise MeshError(f"model import part {n}: no vertices or triangles")
        p = {}
        for k2, (fmt, k) in _ARR.items():
            if k2 in q:
                p[k2] = _unb64(q[k2], fmt, k, q["triangle_count"] if k2 == "triangles" else nv)
        p["triangles"] = p["triangles"].astype(np.int64)
        p["uv"] = [None if x is None else _unb64(x, "<f4", 2, nv) for x in q.get("uv", [])]
        p["color"] = [None if x is None else _unb64(x, "<u4", 1, nv)
                      for x in q.get("color", [])]
        parts[n] = p
    return parts


# ------------------------------------------------------------------ skeleton

def skeleton_for(lu, mesh_hash):
    """Parents of the skeleton that names this mesh (skeleton +0x08 lists its
    meshes, LU_FORMAT 24) -> list of parent indices, or None."""
    for r in lu.records:
        if r.external or (r.type & 0x0FFFFFFF) != 0x04000001:
            continue
        s = bytes(lu.chunk(r))
        if len(s) < 0x60:
            continue
        ptr, cnt = struct.unpack_from(">2I", s, 8)
        if not 0 < cnt < 64 or ptr + 8 * cnt > len(s):
            continue
        if not any(struct.unpack_from(">I", s, ptr + 8 * i)[0] == mesh_hash
                   for i in range(cnt)):
            continue
        rec_ptr, n = struct.unpack_from(">2I", s, 0x10)
        if not 0 < n < 1024 or rec_ptr + 16 * n > len(s):
            continue
        return [struct.unpack_from(">i", s, rec_ptr + 16 * i + 4)[0] for i in range(n)]
    return None


def bone_names(BW, parents=None):
    """b000_root, b078_L_hand-ish labels: index first so a name maps back."""
    names = []
    for i, W in enumerate(BW):
        x, y = W[3, 0], W[3, 1]
        side = "L_" if x > 0.02 else "R_" if x < -0.02 else ""
        zone = "head" if y > 1.3 else "upper" if y > 0.9 else "mid" if y > 0.45 else "low"
        names.append(f"b{i:03d}_{side}{zone}")
    return names


# ------------------------------------------------------------------ GLB out

def to_rigged_glb(d, parents=None, images=None, name="mesh"):
    """GLB of a mesh with its skeleton: one joint per skeleton bone, named
    bNNN_... (the index maps back), at the bind pose; every drawn skinned or
    rigid part as subNN, skinned parts weighted to those joints. Fit a new
    model to this armature in its rest pose, weight it to these bones and
    export it again (mesh_replace.py import)."""
    IB = inverse_binds(d)
    if IB is None:
        raise MeshError("this mesh has no skeleton (no inverse bind matrices)")
    BW = bind_world(IB)                       # row vectors
    Wc = np.transpose(BW, (0, 2, 1))          # column vectors
    nb = len(IB)
    if parents is None or len(parents) != nb:
        parents = [-1] * nb
    names = bone_names(BW, parents)
    j = {"asset": {"version": "2.0", "generator": "Seam Ripper mesh_import"},
         "scene": 0, "scenes": [{"nodes": [0], "name": name}],
         "nodes": [{"name": "skeleton", "children": []}],
         "meshes": [], "accessors": [], "bufferViews": [], "skins": [],
         "extras": {"seamripper_rig": 1, "bones": nb}}
    blob = bytearray()

    def view(payload, target=None):
        v = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(payload)}
        if target:
            v["target"] = target
        blob.extend(payload)
        blob.extend(b"\0" * ((-len(blob)) % 4))
        j["bufferViews"].append(v)
        return len(j["bufferViews"]) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        a = {"bufferView": view(np.ascontiguousarray(arr).tobytes(), target),
             "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        j["accessors"].append(a)
        return len(j["accessors"]) - 1
    first = 1
    for i in range(nb):
        p = parents[i]
        L = Wc[i] if p < 0 or p >= nb else np.linalg.inv(Wc[p]) @ Wc[i]
        j["nodes"].append({"name": names[i], "matrix": L.T.reshape(-1).tolist(),
                           "extras": {"sr_bone": i}})
    for i in range(nb):
        p = parents[i]
        if 0 <= p < nb:
            j["nodes"][first + p].setdefault("children", []).append(first + i)
        else:
            j["nodes"][0]["children"].append(first + i)
    ibm = acc(IB.astype("<f4").reshape(nb, 16), "MAT4", target=None)
    j["skins"].append({"joints": list(range(first, first + nb)), "inverseBindMatrices": ibm,
                       "skeleton": 0, "name": "skeleton"})
    images = images or {}
    mat_of = {}
    skipped = []
    for sm in M.submodels(d):
        if not M.editable(sm):
            continue
        if scaled_part(d, sm, IB):
            skipped.append(sm["n"])
            continue
        part = decode_part(d, sm)
        if not len(part["triangles"]):
            continue
        attrs = {"POSITION": acc(part["position"].astype("<f4"), "VEC3", minmax=True)}
        if "normal" in part:
            attrs["NORMAL"] = acc(part["normal"].astype("<f4"), "VEC3")
        if "tangent" in part and "normal" in part:
            T = part["tangent"].astype(np.float64)
            T[:, :3] /= np.maximum(np.linalg.norm(T[:, :3], axis=1, keepdims=True), 1e-12)
            T[:, 3] = np.where(T[:, 3] < 0, -1.0, 1.0)
            attrs["TANGENT"] = acc(T.astype("<f4"), "VEC4")
        for k, uv in enumerate(x for x in part["uv"] if x is not None):
            attrs[f"TEXCOORD_{k}"] = acc(uv.astype("<f4"), "VEC2")
        node = {"name": f"sub{sm['n']:02d}", "extras": {"sr_submodel": sm["n"]}}
        if "bones" in part:
            J = np.clip(part["bones"].astype(np.int64), 0, nb - 1)
            W = part["weights"].astype(np.float64).copy()
            W[part["bones"] < 0] = 0
            W = np.clip(W, 0, None)
            W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
            attrs["JOINTS_0"] = acc(J.astype("<u2"), "VEC4", 5123)
            attrs["WEIGHTS_0"] = acc(W.astype("<f4"), "VEC4")
            node["skin"] = 0
        elif 0 <= sm["bone"] < nb:
            # rigid: stored in its bone's space; hang it on that joint
            node["extras"]["sr_rigid_bone"] = sm["bone"]
        prim = {"attributes": attrs,
                "indices": acc(part["triangles"].astype("<u4").reshape(-1), "SCALAR",
                               5125, 34963)}
        png = images.get(sm["n"])
        if png is not None and part["uv"]:
            if png not in mat_of:
                j.setdefault("images", []).append({"bufferView": view(png),
                                                   "mimeType": "image/png"})
                j.setdefault("textures", []).append({"source": len(j["images"]) - 1})
                j.setdefault("materials", []).append(
                    {"name": f"tex{len(mat_of)}", "pbrMetallicRoughness": {
                        "baseColorTexture": {"index": len(j["textures"]) - 1},
                        "metallicFactor": 0.0}})
                mat_of[png] = len(j["materials"]) - 1
            prim["material"] = mat_of[png]
        j["meshes"].append({"name": f"sub{sm['n']:02d}", "primitives": [prim],
                            "extras": {"sr_submodel": sm["n"], "sr_kind": sm["kind"]}})
        node["mesh"] = len(j["meshes"]) - 1
        j["nodes"].append(node)
        ni = len(j["nodes"]) - 1
        if "skin" in node:
            j["scenes"][0]["nodes"].append(ni)
        else:
            b = sm["bone"]
            if 0 <= b < nb:
                j["nodes"][first + b].setdefault("children", []).append(ni)
            else:
                j["scenes"][0]["nodes"].append(ni)
    if skipped:
        j["extras"]["sr_left_out"] = skipped
    j["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


# ------------------------------------------------------------------ GLB in

def _bone_of(nd):
    b = (nd.get("extras") or {}).get("sr_bone")
    if isinstance(b, int):
        return b
    m = BONE_RE.match(nd.get("name", ""))
    return int(m.group(1)) if m else None


def parts_from_glb(d, data, notes=None):
    """Read a rigged GLB against mesh record d -> {sub-model n: part}.
    Objects are matched to parts by name (subNN; sub00.001 and the like
    join sub00). A skinned part's object must be skinned to joints named
    bNNN (any suffix): NNN is the skeleton bone. Positions are taken at the
    file's rest pose (each vertex through its joints' rest matrix times
    inverse bind), so the model must sit where it should on the character
    in the armature's rest pose. Weights on bones the part's palette lacks
    move to the nearest parent joint that it holds."""
    notes = notes if notes is not None else []
    g, blob = M._read_glb(data)
    subs = M.submodels(d)
    IB = inverse_binds(d)
    nb = len(IB) if IB is not None else 0
    nodes = g.get("nodes", [])
    wm = M._node_matrices(g)
    parent = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}
    bone = {i: _bone_of(nd) for i, nd in enumerate(nodes)}
    joint_set = {jn for s in g.get("skins", []) for jn in s["joints"]}
    bone_node = {}
    for i, b in bone.items():
        if b is not None and i in joint_set:
            bone_node.setdefault(b, i)

    def node_bone(i):
        """A joint node's skeleton bone: its own, else its nearest parent's."""
        seen = 0
        while i is not None and seen < 4096:
            if bone.get(i) is not None:
                return bone[i]
            i = parent.get(i)
            seen += 1
        return None
    got = {}
    for ni, nd in enumerate(nodes):
        if "mesh" not in nd:
            continue
        mesh = g["meshes"][nd["mesh"]]
        n = (nd.get("extras") or {}).get("sr_submodel")
        if n is None:
            n = (mesh.get("extras") or {}).get("sr_submodel")
        if n is None:
            m = M.SUB_RE.search(nd.get("name", "")) or M.SUB_RE.search(mesh.get("name", ""))
            n = int(m.group(1)) if m else None
        label = nd.get("name") or mesh.get("name") or f"node {ni}"
        if n is None:
            notes.append(f"'{label}' is not named after a part (sub00, sub01, ...); ignored")
            continue
        if not 0 <= n < len(subs) or subs[n]["kind"] == "shadow" or not M.editable(subs[n]):
            raise MeshError(f"'{label}': this mesh has no part {n} that takes a model")
        sm = subs[n]
        if scaled_part(d, sm, IB):
            raise MeshError(f"'{label}': part sub{n:02d} hangs on a bone with a rest scale "
                            f"(bone {palette(d, sm)['bones'][0]}); Blender cannot keep "
                            f"that, so it is left out of the rigged export and cannot "
                            f"be imported. Delete the object (the part stays as shipped) "
                            f"or collapse the part")
        skinned = influences(sm) > 0
        pal = palette(d, sm) if skinned else None
        skin = g["skins"][nd["skin"]] if "skin" in nd else None
        if skinned and skin is None:
            raise MeshError(f"'{label}': part sub{n:02d} is skinned, so the object must "
                            f"be skinned too (an Armature modifier on the exported "
                            f"skeleton, weights on bones named b000 ... b{nb - 1:03d})")
        if skin is not None:
            joints = skin["joints"]
            if "inverseBindMatrices" in skin:
                IBg = M._accessor(g, blob, skin["inverseBindMatrices"]).reshape(-1, 4, 4)
                IBg = np.transpose(IBg, (0, 2, 1))          # column vectors
            else:
                IBg = np.tile(np.eye(4), (len(joints), 1, 1))
            Sk = np.array([wm[jn] @ IBg[k] for k, jn in enumerate(joints)])
            jb = np.array([node_bone(jn) if node_bone(jn) is not None else -1
                           for jn in joints], np.int64)
            if skinned:
                inpal = set(pal["bones"])
                remap = {}
                for k, jn in enumerate(joints):
                    b, i = jb[k], jn
                    while b >= 0 and b not in inpal and i is not None:
                        i = parent.get(i)
                        b = node_bone(i) if i is not None else -1
                        b = -1 if b is None else b
                    if b != jb[k]:
                        remap[k] = b
                jb0 = jb.copy()
                for k, b in remap.items():
                    jb[k] = b
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                raise MeshError(f"'{label}': only triangles can be imported "
                                f"(primitive mode {prim.get('mode')})")
            at = prim["attributes"]
            V = M._accessor(g, blob, at["POSITION"])
            nv = len(V)
            Nn = M._accessor(g, blob, at["NORMAL"]) if "NORMAL" in at else None
            Tn = M._accessor(g, blob, at["TANGENT"]) if "TANGENT" in at else None
            uvs = []
            for k in range(8):
                if f"TEXCOORD_{k}" not in at:
                    break
                uvs.append(M._accessor(g, blob, at[f"TEXCOORD_{k}"])[:, :2])
            cols = []
            for k in range(4):
                if f"COLOR_{k}" not in at:
                    break
                c = M._accessor(g, blob, at[f"COLOR_{k}"])
                if c.shape[1] == 3:
                    c = np.c_[c, np.ones(len(c))]
                c = np.clip(np.rint(c * 255), 0, 255).astype(np.uint32)
                cols.append((c[:, 3] << 24) | (c[:, 0] << 16) | (c[:, 1] << 8) | c[:, 2])
            if "indices" in prim:
                tris = M._accessor(g, blob, prim["indices"]).astype(np.int64).reshape(-1, 3)
            else:
                tris = np.arange(nv, dtype=np.int64).reshape(-1, 3)
            part = {"uv": uvs, "color": cols, "triangles": tris}
            if skin is not None:
                Js, Ws = [], []
                for s in range(2):
                    if f"JOINTS_{s}" in at and f"WEIGHTS_{s}" in at:
                        Js.append(M._accessor(g, blob, at[f"JOINTS_{s}"]).astype(np.int64))
                        Ws.append(M._accessor(g, blob, at[f"WEIGHTS_{s}"]))
                if not Js:
                    raise MeshError(f"'{label}' is skinned but has no weights")
                Jl, Wl = np.concatenate(Js, 1), np.concatenate(Ws, 1)
                Wl = np.where(Wl > 0, Wl, 0)
                sw = Wl.sum(1, keepdims=True)
                if (sw <= 0).any():
                    raise MeshError(f"'{label}': {int((sw <= 0).sum())} vertices have no "
                                    f"weights")
                Wl = Wl / sw
                M4 = np.einsum("vk,vkij->vij", Wl, Sk[Jl])
                P = np.einsum("vij,vj->vi", M4, np.c_[V, np.ones(nv)])[:, :3]
                L3 = M4[:, :3, :3]
                if Nn is not None:
                    Nn = np.einsum("vij,vj->vi", np.linalg.inv(L3).transpose(0, 2, 1), Nn)
                if Tn is not None:
                    Tn = np.c_[np.einsum("vij,vj->vi", L3, Tn[:, :3]), Tn[:, 3]]
                if skinned:
                    B = jb[Jl]
                    moved = sorted({(int(jb0[j]), int(jb[j])) for j in
                                    np.unique(Jl[Wl > 0]).tolist() if jb0[j] != jb[j]
                                    and jb0[j] >= 0 and jb[j] >= 0})
                    if moved:
                        notes.append(f"sub{n:02d}: weights on bones outside this part's "
                                     f"palette moved to a parent: " + ", ".join(
                                         f"{a}->{b}" for a, b in moved[:16])
                                     + (" ..." if len(moved) > 16 else ""))
                    if ((B < 0) & (Wl > 0)).any():
                        raise MeshError(f"'{label}': weights on joints that are not "
                                        f"skeleton bones (name them b000 ... b{nb - 1:03d})")
                    # one bone may come from several joints: merge
                    order = np.argsort(-Wl, axis=1, kind="stable")
                    B = np.take_along_axis(B, order, 1)
                    Wl = np.take_along_axis(Wl, order, 1)
                    J4 = np.full((nv, 4), -1, np.int64)
                    W4 = np.zeros((nv, 4))
                    for v in range(nv):
                        acc = {}
                        for b, w in zip(B[v].tolist(), Wl[v].tolist()):
                            if w > 0:
                                acc[b] = acc.get(b, 0.0) + w
                        top = sorted(acc.items(), key=lambda x: -x[1])[:4]
                        tot = sum(w for _, w in top)
                        for k, (b, w) in enumerate(top):
                            J4[v, k], W4[v, k] = b, w / tot
                    J4[J4 < 0] = pal["bones"][0] if pal else 0
                    part["bones"], part["weights"] = J4, W4.astype(np.float32)
            else:
                Mw = wm[ni]
                P = (V @ Mw[:3, :3].T) + Mw[:3, 3]
                Lm = Mw[:3, :3]
                if Nn is not None:
                    Nn = Nn @ np.linalg.inv(Lm)
                if Tn is not None:
                    Tn = np.c_[Tn[:, :3] @ Lm.T, Tn[:, 3]]
                if skinned:
                    raise MeshError(f"'{label}': part sub{n:02d} is skinned")
                b = sm["bone"]
                if b in bone_node:                 # rigid part hung on its joint
                    inv = np.linalg.inv(wm[bone_node[b]])
                    P = (P @ inv[:3, :3].T) + inv[:3, 3]
                    if Nn is not None:
                        Nn = Nn @ wm[bone_node[b]][:3, :3]
                    if Tn is not None:
                        Tn = np.c_[Tn[:, :3] @ inv[:3, :3].T, Tn[:, 3]]
            part["position"] = P.astype(np.float32)
            if Nn is not None:
                Nn = Nn / np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
                part["normal"] = Nn.astype(np.float32)
            if Tn is not None:
                Tn[:, :3] /= np.maximum(np.linalg.norm(Tn[:, :3], axis=1, keepdims=True), 1e-12)
                part["tangent"] = Tn.astype(np.float32)
            got.setdefault(n, []).append(part)
    if not got:
        raise MeshError("the GLB holds none of this mesh's parts (objects named sub00, "
                        "sub01, ...)")
    return {n: merge_parts(ps) for n, ps in got.items()}


def merge_parts(ps):
    """Join several primitives / objects of one part into one."""
    if len(ps) == 1:
        return ps[0]
    out, off, tris = {}, 0, []
    for key in ("position", "normal", "tangent", "bones", "weights"):
        have = [p.get(key) is not None for p in ps]
        if all(have):
            out[key] = np.concatenate([p[key] for p in ps])
        elif any(have) and key in ("bones", "weights"):
            raise MeshError("some objects of a part are skinned and some not")
    for p in ps:
        tris.append(p["triangles"] + off)
        off += len(p["position"])
    out["triangles"] = np.concatenate(tris)
    for key in ("uv", "color"):
        k = min(len(p[key]) for p in ps)
        out[key] = [None if any(p[key][i] is None for p in ps) else
                    np.concatenate([p[key][i] for p in ps]) for i in range(k)]
    if "normal" not in out:
        out.pop("tangent", None)
    return out


# ------------------------------------------------------------------ containers

def import_in_container(lu_path, items, check_sha=True):
    """Build imported models into a container -> (file bytes, log lines).
    items: [(mesh name hash, neutral import (parts_to_obj, with its
    "options": primitive, in_place), original record sha256 or None)]."""
    import lu_records
    from naughty_lu import LuFile
    lu = LuFile(lu_path)
    game = lu_records.game_of(lu)
    name = Path(lu_path).name
    reps, log, want = {}, [], {}
    for h, obj, sha in items:
        parts = obj_to_parts(obj)
        opts = obj.get("options") or {}
        primitive = opts.get("primitive", "auto")
        in_place = True if opts.get("in_place") else None
        recs = M.mesh_records(lu, h)
        if len(recs) != 1:
            raise MeshError(f"{name}: {len(recs)} meshes named {h:08x} with their own "
                            f"data (need exactly one)")
        old = bytes(lu.chunk(recs[0]))
        if check_sha and sha and M.sha256(old) != sha:
            raise MeshError(f"{name}: mesh {h:08x} is not the one the patch was made for")
        log.append(f"  mesh {h:08x}:")
        new = build_record(old, parts, game, primitive, in_place, log.append)
        reps[recs[0].index] = new
        want[recs[0].index] = parts
        log.append(f"  mesh {h:08x}: {len(old):,} -> {len(new):,} bytes")

    def check(i, got):
        try:
            subs = M.submodels(got)
            for n, p in want[i].items():
                sm = subs[n]
                if isinstance(p, str):
                    if len(M.triangles(got, sm)):
                        return f"part {n} still draws triangles"
                    continue
                if sm["verts"] != len(p["position"]):
                    return f"part {n} reads back {sm['verts']} vertices"
                if len(M.triangles(got, sm)) != len(p["triangles"]):
                    return f"part {n} reads back a different triangle count"
                P = M.read_column(got, sm, U_POS)
                if not np.array_equal(P, np.asarray(p["position"], np.float32)):
                    return f"part {n} reads back different positions"
        except MeshError as e:
            return f"does not read back: {e}"
        return None
    try:
        out, how = lu_records.rebuild(lu, reps, check, allow_resize=(game == "nb1"))
    except lu_records.RecordError as e:
        raise MeshError(str(e))
    log.append(f"  container rebuilt ({how})")
    return out, log


# ------------------------------------------------------------------ checks

def same_triangles(a, b):
    """Same oriented triangles (any rotation, any order)?"""
    def canon(t):
        t = np.asarray(t, np.int64).reshape(-1, 3)
        r = np.argmin(t, axis=1)
        idx = (np.arange(3)[None, :] + r[:, None]) % 3
        c = np.take_along_axis(t, idx, 1)
        return c[np.lexsort(c.T[::-1])]
    return len(a) == len(b) and np.array_equal(canon(a), canon(b))


def roundtrip(d, game, notes=None, kinds=("skinned", "rigid")):
    """-> list of problems. Every drawn part decoded and written back through
    the import path (as a list, appended or in place; and as a strip): the
    vertex buffer must come back byte for byte, the triangles the same set,
    radii never smaller than shipped bound, every other part untouched."""
    probs = []
    subs = M.submodels(d)
    for sm in subs:
        if sm["kind"] not in kinds or not M.editable(sm) or not len(M.triangles(d, sm)):
            continue
        part = decode_part(d, sm)
        pal = palette(d, sm) if influences(sm) else None
        vb = encode_part(sm, part, pal)
        if vb != d[sm["vo"]:sm["vo"] + sm["vs"]]:
            probs.append(f"sub{sm['n']:02d}: vertex buffer does not re-encode byte for byte")
            continue
        modes = [("list", False), ("strip", False)] if game == "nb1" else [("auto", True)]
        for prim, inplace in modes:
            g = game
            if game == "pip":
                # our strips run up to ~1% longer than retail's (no degenerate
                # joins), so an UNCHANGED retail part can miss its in-place
                # budget by a little: noted, and the writer checked appending
                room = trailer_at(d, sm) - sm["vo"]
                need = len(vb) + _al(2 * len(stripify(part["triangles"])), 4)
                if need > room:
                    if need > room * 1.01:
                        probs.append(f"sub{sm['n']:02d}: strip {need - room} bytes over "
                                     f"the in-place budget")
                    if notes is not None:
                        notes.append(f"sub{sm['n']:02d}: {need - room} bytes over")
                    g, prim, inplace = "nb1", "strip", False
            try:
                new = build_record(d, {sm["n"]: part}, g, prim, inplace)
            except MeshError as e:
                probs.append(f"sub{sm['n']:02d} {prim}: {e}")
                continue
            ns = M.submodels(new)
            s2 = ns[sm["n"]]
            if new[s2["vo"]:s2["vo"] + s2["vs"]] != vb:
                probs.append(f"sub{sm['n']:02d} {prim}: vertices moved wrong")
            if not same_triangles(M.triangles(new, s2), part["triangles"]):
                probs.append(f"sub{sm['n']:02d} {prim}: triangles differ")
            for o in subs:
                if o["n"] == sm["n"]:
                    continue
                if new[o["vo"]:o["vo"] + o["vs"]] != d[o["vo"]:o["vo"] + o["vs"]] or \
                        new[o["io"]:o["io"] + o["isz"]] != d[o["io"]:o["io"] + o["isz"]]:
                    probs.append(f"sub{sm['n']:02d} {prim}: part {o['n']} changed")
            if pal is not None:
                prob = radius_problem(new, s2)
                if prob:
                    probs.append(f"sub{sm['n']:02d} {prim}: {prob}")
    return probs


def radius_problem(d, sm, tol=1e-6):
    """A palette radius that does not reach every vertex weighted to its
    slot (computed here from the vertex buffer as written) -> text or None.
    Retail radii were computed in float32 from the tool's own matrices:
    check them with tol 1e-5."""
    pal = palette(d, sm)
    IB = inverse_binds(d)
    part = decode_part(d, sm)
    BW = bind_world(IB)
    slots = np.full(part["bones"].shape, -1)
    lut = _slot_table(pal["bones"])
    ok = part["bones"] >= 0
    slots[ok] = lut[part["bones"][ok]]
    P = part["position"].astype(np.float64)
    C = counted(part["weights"], influences(sm))
    for j, b in enumerate(pal["bones"]):
        m = ((slots == j) & C).any(1)
        if m.any():
            r = np.linalg.norm(P[m] - BW[b][3, :3], axis=1).max()
            if pal["radii"][j] < r * (1 - tol):
                return f"slot {j} radius {pal['radii'][j]:.6g} < vertex bound {r:.6g}"
    if pal["p8"] is not None:
        for j, b in enumerate(pal["bones"]):
            if struct.unpack_from(">If", d, pal["p8"] + 8 * j) !=                     (b, float(np.float32(pal["radii"][j]))):
                return f"{{bone, radius}} array differs from the palette at slot {j}"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("roundtrip")
    pr.add_argument("paths", nargs="+")
    pr.add_argument("--game", choices=("nb1", "pip"), required=True)
    a = ap.parse_args()
    import hashlib
    seen, n, bad, parts, over = set(), 0, 0, 0, []
    for label, d in M.iter_meshes(a.paths):
        k = hashlib.sha1(d).digest()
        if k in seen:
            continue
        seen.add(k)
        n += 1
        try:
            probs = roundtrip(d, a.game, over)
            parts += sum(1 for sm in M.submodels(d) if M.editable(sm))
        except MeshError as e:
            probs = [str(e)]
        if probs:
            bad += 1
            if bad <= 20:
                print(f"FAIL {label}: {'; '.join(probs[:4])}")
    print(f"{n} unique meshes ({parts} drawn parts), {n - bad} passed, {bad} failed")
    if over:
        print(f"{len(over)} unchanged part(s) re-imported as a strip run over their "
              f"in-place budget by under 1% (written appended to check them)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
