#!/usr/bin/env python3
"""Mesh records of Naughty Bear (type 04000007) and Panic in Paradise
(34000007): read every sub-model by its own pointers and vertex declaration,
export them as an editable GLB, and write edited vertices back without
changing the record's size.

  lu_mesh.py roundtrip PATHS...     read, write back unchanged, compare;
                                    then through a GLB and back, compare

PATHS are .lu files, folders of them, or folders of decoded chunks (*.bin).

The record (LU_FORMAT.md 29.6, 33):
  +0x00 {ptr 0x20, count}: models, 16 bytes each {id, hash, list ptr, count}
        (id 1 drawn, id 2 shadow volume); a list entry is {34200001, sub-model}
  sub-model +0x20 bounding sphere (x, y, z, r) holding every vertex
            +0x40 ptr to the aabbccdd marker; the buffer quad follows it:
                  {vb offset, vb size, ib offset, ib size}
            +0x4c ptr to the trailer {stride, primitive count, primitive
                  (4 list, 6 strip), 0, declaration ptr, element count, 0,
                  vertex count, index count, ...} (LU_FORMAT 34.1)
            +0x70 rigid part: the bone it hangs on (skinned: -1)
  declaration: D3DVERTEXELEMENT9 {u16 stream, u16 offset, u32 type, u8
  method, u8 usage, u8 usage index, u8 pad}, closed by 00FF0000 FFFFFFFF.

What a replacement may change: vertex positions, normals and texture
coordinates. Vertex and index counts, the index buffer, the declaration,
skin weights, bone indices and palettes stay as shipped, so the record keeps
its size (Panic in Paradise hangs if a record changes size) and skinning
cannot break. A sphere grows when an edit moves vertices outside it.
"""
import argparse
import io
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

MESH_TYPES = (0x04000007, 0x34000007)
D3D_UBYTE4, D3D_F1, D3D_F2, D3D_F3 = 0x1A2286, 0x2C83A4, 0x2C23A5, 0x2A23B9
D3D_F4, D3D_H2, D3D_H4, D3D_COLOR = 0x1A23A6, 0x2C235F, 0x1A2360, 0x182886
U_POS, U_BW, U_BI, U_NRM, U_UV, U_TAN = 0, 1, 2, 3, 5, 6
MARKER = b"\xaa\xbb\xcc\xdd"
SUB_RE = re.compile(r"sub(\d+)")


class MeshError(Exception):
    pass


def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def is_mesh(d):
    return len(d) >= 0x30 and _u32(d, 0) == 0x20 and 0 < _u32(d, 4) < 16


def parse_decl(d, o):
    out = []
    for _ in range(32):
        if o + 12 > len(d):
            raise MeshError("vertex declaration runs past the record")
        so, typ, mu = struct.unpack_from(">3I", d, o)
        if typ == 0xFFFFFFFF:
            return out
        out.append({"stream": so >> 16, "offset": so & 0xFFFF, "type": typ,
                    "usage": (mu >> 16) & 0xFF, "index": (mu >> 8) & 0xFF})
        o += 12
    raise MeshError("vertex declaration has no end marker")


def submodels(d):
    """Every sub-model of a mesh record, in record order -> list of dicts."""
    if not is_mesh(d):
        raise MeshError("not a mesh record")
    mp, mn = struct.unpack_from(">2I", d, 0)
    out = []
    for i in range(mn):
        mid, _h, lp, ln = struct.unpack_from(">4I", d, mp + 16 * i)
        if ln > 4096 or lp + 8 * ln > len(d):
            raise MeshError("model list runs past the record")
        for k in range(ln):
            tag, sp = struct.unpack_from(">2I", d, lp + 8 * k)
            if tag != 0x34200001 or sp + 0x80 > len(d):
                raise MeshError(f"bad sub-model entry at {lp + 8 * k:#x}")
            qp, tp = _u32(d, sp + 0x40), _u32(d, sp + 0x4c)
            if d[qp:qp + 4] != MARKER:
                raise MeshError(f"sub-model {sp:#x}: no aabbccdd marker at {qp:#x}")
            vo, vs, io_, isz = struct.unpack_from(">4I", d, qp + 4)
            stride, count, prim, zero, declp, nel = struct.unpack_from(">6I", d, tp)
            if not stride or vs % stride or vo + vs > len(d) or io_ + isz > len(d):
                raise MeshError(f"sub-model {sp:#x}: buffers do not fit")
            if (io_ + isz + 3) & ~3 != tp:
                raise MeshError(f"sub-model {sp:#x}: trailer is not after its indices")
            el = parse_decl(d, declp)
            s0 = {(e["usage"], e["index"]): e for e in el if e["stream"] == 0}
            # model 2 is the shadow volume (30 of 30 such parts); a model 1
            # part with blend indices and no normal is drawn (2 in the corpora,
            # both with texture coordinates), so the model id decides
            kind = ("shadow" if mid == 2 else "skinned" if (U_BI, 0) in s0 else "rigid")
            out.append({"n": len(out), "model": mid, "sp": sp, "vo": vo, "vs": vs,
                        "io": io_, "isz": isz, "stride": stride, "count": count,
                        "prim": prim, "decl": el, "s0": s0, "kind": kind,
                        "verts": vs // stride,
                        "bone": struct.unpack_from(">i", d, sp + 0x70)[0]})
    return out


# ------------------------------------------------------------------ columns

_FMT = {D3D_F3: (">f4", 3), D3D_F2: (">f4", 2), D3D_F1: (">f4", 1), D3D_F4: (">f4", 4),
        D3D_H2: (">f2", 2), D3D_H4: (">f2", 4)}


def _column(d, sm, usage, index=0):
    """Raw column bytes view info -> (offset, numpy dtype, components) or None."""
    e = sm["s0"].get((usage, index))
    if e is None or e["type"] not in _FMT:
        return None
    fmt, k = _FMT[e["type"]]
    if e["offset"] + np.dtype(fmt).itemsize * k > sm["stride"]:
        return None
    return e["offset"], fmt, k


def read_column(d, sm, usage, index=0):
    c = _column(d, sm, usage, index)
    if c is None:
        return None
    off, fmt, k = c
    n, st = sm["verts"], sm["stride"]
    V = np.frombuffer(d, np.uint8, n * st, sm["vo"]).reshape(n, st)
    w = np.dtype(fmt).itemsize * k
    return np.frombuffer(V[:, off:off + w].tobytes(), fmt).reshape(n, k)


def write_column(buf, sm, usage, values, index=0):
    """Write values (n x k) into the vertex buffer of sm in buf (bytearray)."""
    c = _column(buf, sm, usage, index)
    if c is None:
        raise MeshError(f"sub-model {sm['n']} has no such column")
    off, fmt, k = c
    n, st = sm["verts"], sm["stride"]
    vals = np.asarray(values, np.float64).reshape(n, k).astype(fmt)
    V = np.frombuffer(buf, np.uint8, n * st, sm["vo"]).reshape(n, st).copy()
    w = np.dtype(fmt).itemsize * k
    V[:, off:off + w] = np.frombuffer(vals.tobytes(), np.uint8).reshape(n, w)
    buf[sm["vo"]:sm["vo"] + n * st] = V.tobytes()


def triangles(d, sm):
    """Triangles of a sub-model (index buffer decoded) -> int array (m, 3)."""
    n_idx = sm["isz"] // 2
    if sm["prim"] == 4:
        n_idx = min(n_idx, sm["count"] * 3)
    raw = list(struct.unpack_from(f">{n_idx}H", d, sm["io"]))
    while raw and raw[-1] == 0xBFBF:
        raw.pop()
    n = sm["verts"]
    tris = []
    if sm["prim"] == 4:
        for i in range(0, len(raw) - 2, 3):
            a, b, c = raw[i:i + 3]
            if len({a, b, c}) == 3 and max(a, b, c) < n:
                tris.append((a, b, c))
    else:
        strip = []
        for t in raw + [0xFFFF]:
            if t != 0xFFFF:
                strip.append(t)
                continue
            for i in range(len(strip) - 2):
                a, b, c = strip[i:i + 3]
                if len({a, b, c}) == 3 and max(a, b, c) < n:
                    tris.append((a, c, b) if i & 1 else (a, b, c))
            strip = []
    return np.array(tris, np.uint32).reshape(-1, 3)


def editable(sm):
    """Drawn sub-models with a float3 position (shadow volumes are left out)."""
    return sm["kind"] != "shadow" and _column(b"", sm, U_POS) is not None


def sphere(d, sm):
    return np.array(struct.unpack_from(">4f", d, sm["sp"] + 0x20), np.float64)


# ------------------------------------------------------------------ edit

def apply_edits(d, edits):
    """Record d with vertex columns replaced -> new bytes (same size).
    edits: {sub-model n: {"position": (v,3), "normal": (v,3), "uv": (v,2)}}.
    A sub-model's sphere radius grows to hold every new position."""
    buf = bytearray(d)
    subs = submodels(d)
    for n, cols in edits.items():
        sm = subs[n]
        for name, usage in (("position", U_POS), ("normal", U_NRM), ("uv", U_UV)):
            if cols.get(name) is None:
                continue
            if _column(buf, sm, usage) is None:
                raise MeshError(f"sub-model {n} stores no {name}")
            write_column(buf, sm, usage, cols[name])
        if cols.get("position") is not None:
            P = read_column(buf, sm, U_POS).astype(np.float64)
            c = sphere(buf, sm)
            r = float(np.linalg.norm(P - c[:3], axis=1).max())
            if r > c[3]:
                r32 = np.float32(r)
                while r32 < r:                       # never round below a vertex
                    r32 = np.nextafter(r32, np.float32(np.inf))
                struct.pack_into(">f", buf, sm["sp"] + 0x2c, float(r32))
    if len(buf) != len(d):
        raise MeshError("record size changed")
    return bytes(buf)


def smooth_normals(P, tris):
    """Area-weighted vertex normals, vertices at the same position welded
    (a game mesh splits vertices at texture seams)."""
    key = np.unique(np.round(P, 5), axis=0, return_inverse=True)[1].ravel()
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    acc = np.zeros((key.max() + 1 if len(key) else 0, 3))
    for k in range(3):
        np.add.at(acc, key[tris[:, k]], fn)
    S = acc[key]
    return S / np.maximum(np.linalg.norm(S, axis=1, keepdims=True), 1e-12)


def carry_normals(P0, P1, N0, tris):
    """New normals for an edit P0 -> P1: each shipped normal turned by the
    turn of the surface under it (old to new smooth normal), so smooth and
    hard edges stay as the artist made them. Where the surface did not turn
    the shipped normal is kept exactly."""
    tris = tris.astype(np.int64)
    S0, S1 = smooth_normals(P0, tris), smooth_normals(P1, tris)
    N = N0.astype(np.float64).copy()
    turn = np.linalg.norm(S1 - S0, axis=1) > 1e-6
    for i in np.flatnonzero(turn):
        a, b = S0[i], S1[i]
        v, c = np.cross(a, b), float(a @ b)
        if c < -0.999999:
            continue                                  # flipped face: leave it
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + K + K @ K / (1 + c)
        n = R @ N[i]
        N[i] = n / max(np.linalg.norm(n), 1e-12)
    return N


# ------------------------------------------------------------------ GLB

def to_glb(d, images=None, name="mesh"):
    """Editable GLB of a mesh record: one node and mesh per drawn sub-model,
    named subNN (its index in the record), every vertex of its buffer in
    buffer order, with a _SR_VID attribute (the vertex's index) so an edited
    file maps back even if Blender reorders or splits vertices.
    Positions are as stored: model space for skinned parts, the space of
    their bone for rigid parts. images: {sub-model n: PNG bytes}."""
    jroot = {"asset": {"version": "2.0", "generator": "Seam Ripper lu_mesh"},
             "scene": 0, "scenes": [{"nodes": [], "name": name}], "nodes": [],
             "meshes": [], "accessors": [], "bufferViews": [],
             "extras": {"seamripper_mesh": 1}}
    blob = bytearray()

    def view(payload, target=None):
        v = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(payload)}
        if target:
            v["target"] = target
        blob.extend(payload)
        blob.extend(b"\0" * ((-len(blob)) % 4))
        jroot["bufferViews"].append(v)
        return len(jroot["bufferViews"]) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype,
             "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        jroot["accessors"].append(a)
        return len(jroot["accessors"]) - 1

    images = images or {}
    img_index = {}
    for sm in submodels(d):
        if not editable(sm):
            continue
        n = sm["n"]
        P = read_column(d, sm, U_POS).astype("<f4")
        tris = triangles(d, sm)
        if not len(tris):
            continue
        attrs = {"POSITION": acc(P, "VEC3", minmax=True)}
        N = read_column(d, sm, U_NRM)
        if N is not None and N.shape[1] == 3:
            attrs["NORMAL"] = acc(N.astype("<f4"), "VEC3")
        UV = read_column(d, sm, U_UV)
        if UV is not None and UV.shape[1] == 2:
            attrs["TEXCOORD_0"] = acc(UV.astype("<f4"), "VEC2")
        attrs["_SR_VID"] = acc(np.arange(sm["verts"], dtype="<f4"), "SCALAR")
        prim = {"attributes": attrs,
                "indices": acc(tris.astype("<u4").reshape(-1), "SCALAR", 5125, 34963)}
        if n in images and "TEXCOORD_0" in attrs:
            png = images[n]
            if png not in img_index:
                jroot.setdefault("images", []).append(
                    {"bufferView": view(png), "mimeType": "image/png"})
                jroot.setdefault("textures", []).append({"source": len(jroot["images"]) - 1})
                jroot.setdefault("materials", []).append(
                    {"pbrMetallicRoughness": {"baseColorTexture":
                                              {"index": len(jroot["textures"]) - 1},
                                              "metallicFactor": 0.0}})
                img_index[png] = len(jroot["materials"]) - 1
            prim["material"] = img_index[png]
        label = f"sub{n:02d}"
        jroot["meshes"].append({"name": label, "primitives": [prim],
                                "extras": {"sr_submodel": n, "sr_kind": sm["kind"],
                                           "sr_vertices": sm["verts"]}})
        jroot["nodes"].append({"name": label, "mesh": len(jroot["meshes"]) - 1})
        jroot["scenes"][0]["nodes"].append(len(jroot["nodes"]) - 1)
    jroot["buffers"] = [{"byteLength": len(blob)}]
    j = json.dumps(jroot, separators=(",", ":")).encode()
    j += b" " * ((-len(j)) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(blob))
            + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def _read_glb(data):
    if data[:4] != b"glTF":
        raise MeshError("not a binary glTF (.glb) file")
    jl, jt = struct.unpack_from("<II", data, 12)
    g = json.loads(data[20:20 + jl].decode("utf-8"))
    blob = b""
    o = 20 + jl
    if o + 8 <= len(data):
        bl, bt = struct.unpack_from("<II", data, o)
        blob = data[o + 8:o + 8 + bl]
    return g, blob


_CT = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _accessor(g, blob, i):
    a = g["accessors"][i]
    if "sparse" in a:
        raise MeshError("sparse accessors are not supported")
    v = g["bufferViews"][a["bufferView"]]
    dt = np.dtype(_CT[a["componentType"]])
    k = _NC[a["type"]]
    start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride") or dt.itemsize * k
    cnt = a["count"]
    raw = np.frombuffer(blob, np.uint8, (cnt - 1) * stride + dt.itemsize * k, start) \
        if cnt else np.zeros(0, np.uint8)
    out = np.lib.stride_tricks.as_strided(raw, (cnt, dt.itemsize * k), (stride, 1)) \
        if cnt else np.zeros((0, dt.itemsize * k), np.uint8)
    vals = np.frombuffer(np.ascontiguousarray(out).tobytes(), dt).reshape(cnt, k)
    if a.get("normalized"):
        vals = vals / float(np.iinfo(dt).max)
    return vals.astype(np.float64)


def _node_matrices(g):
    """World matrix of every node (column vectors)."""
    def local(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], np.float64).reshape(4, 4).T
        t = np.array(nd.get("translation", [0, 0, 0]), np.float64)
        x, y, z, w = nd.get("rotation", [0, 0, 0, 1])
        s = np.array(nd.get("scale", [1, 1, 1]), np.float64)
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        M = np.eye(4)
        M[:3, :3] = R * s
        M[:3, 3] = t
        return M
    nodes = g.get("nodes", [])
    parent = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}
    out = {}

    def world(i):
        if i not in out:
            out[i] = (world(parent[i]) if i in parent else np.eye(4)) @ local(nodes[i])
        return out[i]
    for i in range(len(nodes)):
        world(i)
    return out


def edits_from_glb(d, data, normals="carry"):
    """Read an edited GLB (from to_glb, through Blender or any editor) against
    record d -> ({sub-model n: {"position", "normal", "uv"}}, notes).
    Primitives are matched to sub-models by mesh or node name (subNN) and
    vertices by the _SR_VID attribute; without it a primitive must have
    exactly the sub-model's vertex count, taken in order.
    normals: "carry" turns the shipped normals with the edited surface
    (carry_normals; Blender's own normals come back rougher than the shipped
    ones on edited areas), "glb" takes the GLB's normals where they differ."""
    g, blob = _read_glb(data)
    subs = submodels(d)
    mats = _node_matrices(g)
    notes = []
    got = {}
    for ni, nd in enumerate(g.get("nodes", [])):
        if "mesh" not in nd:
            continue
        mesh = g["meshes"][nd["mesh"]]
        m = SUB_RE.search(mesh.get("name", "")) or SUB_RE.search(nd.get("name", ""))
        n = mesh.get("extras", {}).get("sr_submodel")
        if n is None and m:
            n = int(m.group(1))
        if n is None:
            notes.append(f"'{nd.get('name') or mesh.get('name')}' is not one of the mesh's "
                         f"parts (no subNN name); ignored")
            continue
        if not 0 <= n < len(subs) or not editable(subs[n]):
            raise MeshError(f"'{nd.get('name')}': this mesh has no editable part {n}")
        M = mats[ni]
        Nm = np.linalg.inv(M[:3, :3]).T
        for prim in mesh["primitives"]:
            at = prim["attributes"]
            if "POSITION" not in at:
                continue
            P = _accessor(g, blob, at["POSITION"])
            P = (P @ M[:3, :3].T) + M[:3, 3]
            N = _accessor(g, blob, at["NORMAL"]) @ Nm.T if "NORMAL" in at else None
            if N is not None:
                N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            UV = _accessor(g, blob, at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
            vid = _accessor(g, blob, at["_SR_VID"])[:, 0] if "_SR_VID" in at else None
            got.setdefault(n, []).append((P, N, UV, vid))
    if not got:
        raise MeshError("the GLB holds none of this mesh's parts (names sub00, sub01, ...)")
    edits = {}
    for n, prims in got.items():
        sm = subs[n]
        nv = sm["verts"]
        P0 = read_column(d, sm, U_POS).astype(np.float64)
        N0 = read_column(d, sm, U_NRM)
        UV0 = read_column(d, sm, U_UV)
        P, N, UV = P0.copy(), None if N0 is None else N0.astype(np.float64).copy(), \
            None if UV0 is None else UV0.astype(np.float64).copy()
        seen = np.zeros(nv, bool)
        for Pp, Np, UVp, vid in prims:
            if vid is None:
                if len(prims) > 1 or len(Pp) != nv:
                    raise MeshError(
                        f"part sub{n:02d} has {len(Pp)} vertices and no _SR_VID ids; it "
                        f"needs {nv}. In Blender, export with Include > Data > "
                        f"Attributes ticked (keeps the ids), and edit vertices only: "
                        f"no new or deleted vertices")
                idx = np.arange(nv)
                notes.append(f"sub{n:02d}: no vertex ids; vertices taken in order")
            else:
                idx = np.rint(vid).astype(np.int64)
                if (idx < 0).any() or (idx >= nv).any():
                    raise MeshError(f"part sub{n:02d} has vertex ids outside 0..{nv - 1}; "
                                    f"vertices were added")
            # a vertex Blender split (seams, sharp edges) comes back several
            # times: every copy must agree on its position
            if len(idx) != len(np.unique(idx)):
                order = np.argsort(idx, kind="stable")
                si, sp_ = idx[order], Pp[order]
                same = si[1:] == si[:-1]
                gap = np.abs(sp_[1:] - sp_[:-1]).max(1)
                if (gap[same] > 1e-4).any():
                    bad = int(si[1:][same][np.argmax(gap[same])])
                    raise MeshError(f"part sub{n:02d}: copies of vertex {bad} were moved "
                                    f"apart (a split vertex must stay one vertex)")
            first = np.unique(idx, return_index=True)[1]
            idx, Pp = idx[first], Pp[first]
            P[idx] = Pp
            if N is not None and Np is not None:
                N[idx] = Np[first]
            if UV is not None and UVp is not None:
                UV[idx] = UVp[first]
            seen[idx] = True
        tris = triangles(d, sm)
        used = np.zeros(nv, bool)
        used[tris.reshape(-1)] = True
        missing = used & ~seen
        if missing.any():
            raise MeshError(f"part sub{n:02d}: {int(missing.sum())} vertices are missing "
                            f"(deleted, or exported without Include > Data > Attributes)")
        e = {}
        if not np.array_equal(P, P0):
            e["position"] = P
        if N is not None:
            N0f = N0.astype(np.float64)
            if normals == "carry":
                N = carry_normals(P0, P, N0f, tris) if "position" in e else N0f
            else:
                # Blender rounds normals on the way through: keep the shipped
                # value where the GLB's only differs by that rounding
                keep = np.linalg.norm(N - N0f, axis=1) <= 2e-3
                N[keep] = N0f[keep]
            if not np.array_equal(N, N0f):
                e["normal"] = N
        if UV is not None:
            uvh = UV.astype(">f2").astype(np.float64)
            if (uvh != UV0.astype(np.float64)).any():
                e["uv"] = UV
        if e:
            edits[n] = e
            what = ", ".join(e)
            moved = float(np.abs(P - P0).max()) if "position" in e else 0.0
            notes.append(f"sub{n:02d} ({sm['kind']}, {nv} vertices): {what} changed"
                         + (f", largest move {moved:.4g}" if moved else ""))
    return edits, notes


EDIT_FORMAT = "seamripper-mesh-edit"


def edits_to_obj(d, edits):
    """Neutral form of an edit: per part, only the vertices that changed
    (their ids and new values, float32 exact). No other game data."""
    subs = submodels(d)
    parts = {}
    for n, e in sorted(edits.items()):
        sm = subs[n]
        cols = {}
        for name, usage in (("position", U_POS), ("normal", U_NRM), ("uv", U_UV)):
            if e.get(name) is not None:
                old = read_column(d, sm, usage)
                new = np.asarray(e[name], np.float64).astype(old.dtype)
                cols[name] = (old, new)
        changed = np.zeros(sm["verts"], bool)
        for old, new in cols.values():
            changed |= (old != new).any(1)
        ids = np.flatnonzero(changed)
        if not len(ids):
            continue
        p = {"vertices": sm["verts"], "ids": ids.tolist()}
        for name, (old, new) in cols.items():
            p[name] = [[float(x) for x in row] for row in new[ids].astype(np.float32)]
        parts[str(n)] = p
    return {"format": EDIT_FORMAT, "version": 1, "parts": parts}


def obj_to_edits(d, obj):
    """The edits of a neutral mesh edit, as full columns of record d."""
    if obj.get("format") != EDIT_FORMAT:
        raise MeshError("not a Seam Ripper mesh edit")
    if obj.get("version", 0) > 1:
        raise MeshError("this mesh edit needs a newer Seam Ripper")
    subs = submodels(d)
    edits = {}
    for key, p in obj["parts"].items():
        n = int(key)
        if not 0 <= n < len(subs) or not editable(subs[n]):
            raise MeshError(f"this mesh has no editable part {n}")
        sm = subs[n]
        if p["vertices"] != sm["verts"]:
            raise MeshError(f"part {n} has {sm['verts']} vertices; the edit was made "
                            f"for {p['vertices']}")
        ids = np.asarray(p["ids"], np.int64)
        if len(ids) and (ids.min() < 0 or ids.max() >= sm["verts"]):
            raise MeshError(f"part {n}: vertex ids out of range")
        e = {}
        for name, usage in (("position", U_POS), ("normal", U_NRM), ("uv", U_UV)):
            if name in p:
                col = read_column(d, sm, usage)
                if col is None:
                    raise MeshError(f"part {n} stores no {name}")
                full = col.astype(np.float64)
                vals = np.asarray(p[name], np.float64)
                if vals.shape != (len(ids), col.shape[1]):
                    raise MeshError(f"part {n}: {name} has the wrong shape")
                full[ids] = vals
                e[name] = full
        edits[n] = e
    return edits


def encode_glb(d, data, normals="carry"):
    """Record d with the edits of GLB data applied -> (new record, notes)."""
    edits, notes = edits_from_glb(d, data, normals)
    return (apply_edits(d, edits) if edits else bytes(d)), notes


# ------------------------------------------------------------------ containers

def sha256(b):
    import hashlib
    return hashlib.sha256(bytes(b)).hexdigest()


def mesh_records(lu, h):
    import lu_records
    return lu_records.local_records(lu, h, MESH_TYPES)


def texture_pngs(lu, d):
    """{sub-model n: PNG bytes}: a picture to show on each sub-model in the
    editable GLB, for orientation only. A sub-model names its textures as
    {hash, 04200007} pairs between its header and its buffer marker (diffuse,
    normal, specular and others, in no fixed order); the largest one the
    container stores that does not look like a normal map is taken."""
    import lu_texture
    from naughty_lu import LuFile
    by_hash = {}
    sources = [lu]
    for dep in getattr(lu, "deps", None) or ():      # NB1: shared resource files
        p = Path(lu.path).parent / dep
        if p.is_file():
            try:
                sources.append(LuFile(p))
            except (OSError, ValueError):
                pass
    for src in sources:
        for r in src.records:
            if r.type in lu_texture.TEX_TYPES and not r.external:
                by_hash.setdefault(r.hash, (src, r))
    out, cache = {}, {}

    def load(h):
        if h not in cache:
            cache[h] = None
            try:
                src, r = by_hash[h]
                rec = bytes(src.chunk(r))
                t = lu_texture.info(rec)
                img = lu_texture.level_image(rec, 0, t)
                rgb = np.asarray(img.convert("RGB").resize((16, 16)), np.float64) / 255
                normal_map = rgb[:, :, 2].mean() > 0.7 and abs(rgb[:, :, 0].mean() - 0.5) < 0.15
                b = io.BytesIO()
                img.save(b, "PNG")
                cache[h] = (t["width"] * t["height"], normal_map, b.getvalue())
            except Exception:
                pass
        return cache[h]
    for sm in submodels(d):
        hi = min(_u32(d, sm["sp"] + 0x40), len(d) - 8)
        cands = []
        for o in range(sm["sp"], hi, 4):
            h, t = struct.unpack_from(">2I", d, o)
            if t in (0x04200007, 0x34200007) and h in by_hash and load(h):
                cands.append(load(h))
        cands = [c for c in cands if not c[1]] or cands
        if cands:
            out[sm["n"]] = max(cands, key=lambda c: c[0])[2]
    return out


def replace_in_container(lu_path, items, check_sha=True):
    """Build edited meshes into a container -> (file bytes, log lines).
    items: [(mesh name hash, neutral mesh edit dict (edits_to_obj), original
    record sha256 or None)]."""
    import lu_records
    from naughty_lu import LuFile
    lu = LuFile(lu_path)
    name = Path(lu_path).name
    reps, log = {}, []
    for h, obj, sha in items:
        recs = mesh_records(lu, h)
        if len(recs) != 1:
            raise MeshError(f"{name}: {len(recs)} meshes named {h:08x} with their own "
                            f"data (need exactly one)")
        old = bytes(lu.chunk(recs[0]))
        if check_sha and sha and sha256(old) != sha:
            raise MeshError(f"{name}: mesh {h:08x} is not the one the patch was made for")
        edits = obj_to_edits(old, obj)
        new = apply_edits(old, edits)
        reps[recs[0].index] = new
        nv = sum(len(p["ids"]) for p in obj["parts"].values())
        log.append(f"  mesh {h:08x}: {nv:,} vertices in {len(obj['parts'])} part(s) "
                   f"changed, {len(new):,} bytes (size kept)")

    def check(i, got):
        try:
            for sm in submodels(got):
                if editable(sm):
                    P = read_column(got, sm, U_POS).astype(np.float64)
                    if not np.isfinite(P).all():
                        return "has a vertex that is not a number"
                    c = sphere(got, sm)
                    if np.linalg.norm(P - c[:3], axis=1).max() > c[3] * (1 + 1e-6) + 1e-6:
                        return f"sub-model {sm['n']} has a vertex outside its sphere"
        except MeshError as e:
            return f"does not read back: {e}"
        return None
    try:
        out, how = lu_records.rebuild(lu, reps, check)
    except lu_records.RecordError as e:
        raise MeshError(str(e))
    log.append(f"  container rebuilt ({how})")
    return out, log


# ------------------------------------------------------------------ checks

def roundtrip(d):
    """-> list of problems. (1) every column written back unchanged gives the
    record byte for byte; (2) the editable GLB read back with no edit gives no
    edits; (3) moving one vertex changes exactly that vertex's position bytes
    (and maybe the sphere radius), nothing else."""
    probs = []
    subs = submodels(d)
    buf = bytearray(d)
    for sm in subs:
        if not editable(sm):
            continue
        for u in (U_POS, U_NRM, U_UV):
            col = read_column(d, sm, u)
            if col is not None:
                write_column(buf, sm, u, col.astype(np.float64))
    if bytes(buf) != d:
        probs.append("columns written back unchanged do not give the record back")
    edits, _ = edits_from_glb(d, to_glb(d))
    if edits:
        probs.append(f"the unedited GLB reads back as edits to {sorted(edits)}")
    ed = [sm for sm in subs if editable(sm)]
    if ed:
        sm = ed[0]
        P = read_column(d, sm, U_POS).astype(np.float64)
        k = sm["verts"] // 2
        P[k] += 0.25
        new = apply_edits(d, {sm["n"]: {"position": P}})
        obj = json.loads(json.dumps(edits_to_obj(d, {sm["n"]: {"position": P}})))
        if len(obj["parts"][str(sm["n"])]["ids"]) != 1 or \
                apply_edits(d, obj_to_edits(d, obj)) != new:
            probs.append("the neutral edit file does not rebuild the same record")
        diff =np.flatnonzero(np.frombuffer(new, np.uint8) != np.frombuffer(d, np.uint8))
        e = sm["s0"][(U_POS, 0)]
        lo = sm["vo"] + k * sm["stride"] + e["offset"]
        ok = set(range(lo, lo + 12)) | set(range(sm["sp"] + 0x2c, sm["sp"] + 0x30))
        if not len(diff) or any(int(x) not in ok for x in diff):
            probs.append("a one-vertex edit changed other bytes")
    return probs


def iter_meshes(paths):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from naughty_lu import LuFile
    globs = ("*/mesh_buffers/*.bin", "*/type_34000007/*.bin", "*/type_04000007/*.bin")
    for p in paths:
        p = Path(p)
        if p.is_dir() and not any(p.glob("*.lu")):
            files = [f for pat in globs for f in p.glob(pat)] or list(p.rglob("*.bin"))
            for f in sorted(files):
                d = f.read_bytes()
                if is_mesh(d):
                    yield str(f), d
            continue
        for f in (sorted(p.glob("*.lu")) if p.is_dir() else [p]):
            lu = LuFile(f)
            for r in lu.records:
                if r.type in MESH_TYPES and not r.external:
                    d = bytes(lu.chunk(r))
                    if is_mesh(d):
                        yield f"{f.name}:{r.hash:08x}", d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("roundtrip")
    pr.add_argument("paths", nargs="+")
    a = ap.parse_args()
    import hashlib
    seen, n, bad, parts = set(), 0, 0, 0
    for label, d in iter_meshes(a.paths):
        k = hashlib.sha1(d).digest()
        if k in seen:
            continue
        seen.add(k)
        n += 1
        try:
            probs = roundtrip(d)
            parts += sum(1 for sm in submodels(d) if editable(sm))
        except MeshError as e:
            probs = [str(e)]
        if probs:
            bad += 1
            if bad <= 20:
                print(f"FAIL {label}: {'; '.join(probs)}")
    print(f"{n} unique meshes ({parts} editable parts), {n - bad} passed, {bad} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
