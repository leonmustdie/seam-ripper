#!/usr/bin/env python3
"""
lu_rig.py — export rigged glTF (.glb) characters from Naughty Bear .lu extractions.

Combines a skeleton chunk (type 04000001) with a skinned mesh chunk
(type 04000007) into a single .glb with full joint hierarchy, bind pose,
and vertex weights. Bone names are not stored in the shipped files (only
hashes), so joints are auto-named from the hash plus a positional guess
(left_/right_/center_ by bind X, rough body region by height).

usage:
  python3 lu_rig.py <extracted_unit_dir> -o out.glb
  python3 lu_rig.py /tmp/big_extract/naughtybear -o naughtybear_rigged.glb
"""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lu_convert import (_find_buffer_quads, _read_trailer, _decode_strips,
                        _decode_list, _layout_candidates, is_mesh_chunk,
                        is_texture_chunk, convert_texture, _find_texture_refs)


# ---------------------------------------------------------------- skeleton

def parse_skeleton(d):
    """Type 04000001: header -> records {transform_ptr, parent, child,
    sibling} (16B), per-bone 144B transform blocks (two row-major 4x4
    bind matrices + scratch), unit-quaternion array, sorted
    {name_hash -> index} table."""
    if len(d) < 0x60 or struct.unpack_from(">I", d, 4)[0] != 0x04000001:
        return None
    rec_ptr, n = struct.unpack_from(">2I", d, 0x10)
    if not (0 < n < 1024):
        return None
    hash_ptr = struct.unpack_from(">I", d, 0x48)[0]
    bones = []
    for i in range(n):
        tptr, parent, child, sib = struct.unpack_from(">i3i", d, rec_ptr + i * 16)
        world = [struct.unpack_from(">4f", d, tptr + r * 16) for r in range(4)]
        bones.append({"parent": parent, "world": world})
    hashes = [struct.unpack_from(">Ii", d, hash_ptr + i * 8) for i in range(n)]
    for h, idx in hashes:
        bones[idx]["hash"] = h
    return bones


import numpy as np


def decompose_trs(M_std):
    """Column-convention affine matrix -> (translation, quat xyzw, scale)."""
    t = M_std[:3, 3].tolist()
    A = M_std[:3, :3].copy()
    s = np.linalg.norm(A, axis=0)
    s[s < 1e-12] = 1e-12
    R = A / s
    if np.linalg.det(R) < 0:
        s[0] = -s[0]
        R[:, 0] = -R[:, 0]
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        S = math.sqrt(tr + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / S, (m[0, 2] - m[2, 0]) / S,
             (m[1, 0] - m[0, 1]) / S, 0.25 * S]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        S = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * S, (m[0, 1] + m[1, 0]) / S,
             (m[0, 2] + m[2, 0]) / S, (m[2, 1] - m[1, 2]) / S]
    elif m[1, 1] > m[2, 2]:
        S = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / S, 0.25 * S,
             (m[1, 2] + m[2, 1]) / S, (m[0, 2] - m[2, 0]) / S]
    else:
        S = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / S, (m[1, 2] + m[2, 1]) / S,
             0.25 * S, (m[1, 0] - m[0, 1]) / S]
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return t, [c / n for c in q], s.tolist()


def bone_label(i, bones):
    x, y = bones[i]["world"][3][0], bones[i]["world"][3][1]
    side = "left_" if x > 0.02 else "right_" if x < -0.02 else ""
    if y > 1.3:
        zone = "head"
    elif y > 0.9:
        zone = "upper"
    elif y > 0.45:
        zone = "mid"
    else:
        zone = "lower"
    return f"bone{i:03d}_{side}{zone}_{bones[i].get('hash', 0):08x}"


# -------------------------------------------------------------------- mesh

def extract_skinned_mesh(d):
    """Returns list of submeshes: (positions, uvs, raw_skin_indices u8x4,
    weights f4, triangles, is_rigid, texture_refs). Raw indices are in the
    mesh's local palette space; use solve_palette() to map them to
    skeleton bones. texture_refs is the list of CRC32 hashes found in the
    descriptor window between this buffer and the previous one (same
    scan lu_convert.convert_mesh uses for material binding)."""
    quads = _find_buffer_quads(d)
    out = []
    prev_field = 0x20
    for field_off, vo, vs, io_, isz in quads:
        refs = _find_texture_refs(d, prev_field, field_off)
        prev_field = io_ + isz
        tr = _read_trailer(d, io_, isz)
        if tr is None:
            continue
        stride, prim = tr["stride"], tr["prim"]
        if vs % stride:
            continue
        n = vs // stride
        n_idx = isz // 2
        if prim == 4:
            n_idx = min(n_idx, tr["count"] * 3)
        raw = struct.unpack_from(f">{n_idx}H", d, io_)
        while raw and raw[-1] == 0xBFBF:
            raw = raw[:-1]
        layout = {52: (16, 3), 48: (12, 2), 40: (4, 0), 32: (4, 0)}.get(stride)
        if layout is None:
            continue                                  # shadow mesh / unskinned
        pos_off, wn = layout
        decl = tr["decl"]
        d_uv = decl[1] if decl and decl[1] and decl[1] + 4 <= stride else None
        verts, uvs, joints, weights = [], [], [], []
        for i in range(n):
            b = vo + i * stride
            verts.append(struct.unpack_from(">3f", d, b + pos_off))
            uvs.append(struct.unpack_from(">2e", d, b + d_uv)
                       if d_uv is not None else (0.0, 0.0))
            joints.append(list(d[b:b + 4]))
            if wn == 0:
                weights.append([1.0, 0.0, 0.0, 0.0])
            else:
                ws = list(struct.unpack_from(f">{wn}f", d, b + 4))
                w = (ws + [0.0] * 4)[:4]
                w[wn] = max(0.0, 1.0 - sum(ws))
                t = sum(w) or 1.0
                weights.append([c / t for c in w])
        tris = _decode_list(raw, n) if prim == 4 else _decode_strips(raw, n)
        if tris:
            out.append((verts, uvs, joints, weights, tris, wn == 0, refs))
    return out


def solve_palette(submeshes, bones):
    """The shipped files contain no skin palette, so recover the
    skin-index -> skeleton-bone mapping geometrically. Evidence: weighted
    vertex centroids per skin index. The mapping is a monotone increasing
    subset of skeleton indices (verified on the retail bears), so a
    DP sequence alignment of centroids against bone bind positions
    recovers it. Rigid accessory submeshes use their own index space and
    are handled separately (nearest bone)."""
    import numpy as np
    bonepos = np.array([b["world"][3][:3] for b in bones])
    acc = {}
    for verts, _, joints, weights, _, rigid, _ in submeshes:
        if rigid:
            continue
        for v, j4, w4 in zip(verts, joints, weights):
            for j, w in zip(j4, w4):
                if w > 0.02:
                    if j not in acc:
                        acc[j] = [np.zeros(3), 0.0]
                    acc[j][0] += w * np.array(v)
                    acc[j][1] += w
    if not acc:
        return None
    K = max(acc) + 1
    cents = np.zeros((K, 3))
    have = np.zeros(K, bool)
    for j, (sm, wm) in acc.items():
        cents[j] = sm / wm
        have[j] = True
    Nb = len(bones)
    D = np.linalg.norm(cents[:, None, :] - bonepos[None, :, :], axis=2)
    D[~have] = 0.15
    INF = 1e18
    dp = np.full((K, Nb), INF)
    back = np.zeros((K, Nb), int)
    dp[0] = D[0]
    for k in range(1, K):
        run, ra = INF, -1
        for b in range(Nb):
            if b > 0 and dp[k - 1, b - 1] < run:
                run, ra = dp[k - 1, b - 1], b - 1
            dp[k, b] = run + D[k, b]
            back[k, b] = ra
    b = int(np.argmin(dp[K - 1]))
    mapping = [0] * K
    for k in range(K - 1, -1, -1):
        mapping[k] = b
        if k:
            b = back[k][b]
    return mapping


def nearest_bone(verts, bones):
    import numpy as np
    bonepos = np.array([b["world"][3][:3] for b in bones])
    c = np.array(verts).mean(0)
    return int(np.argmin(np.linalg.norm(bonepos - c, axis=1)))


def smooth_normals(verts, tris):
    """Per-vertex normals, area-weighted average of adjacent face normals
    — this is what Blender's own 'Shade Smooth' produces, computed here
    at export time instead of needing a manual click after import. Writing
    these as the GLB's NORMAL attribute matters because glTF has no
    separate smooth/flat toggle: omit NORMAL and every viewer, Blender
    included, falls back to flat per-face normals on import, which is
    exactly the faceted look 'Shade Smooth' was fixing by hand."""
    v = np.asarray(verts, dtype=np.float64)
    normals = np.zeros_like(v)
    if len(tris):
        idx = np.asarray(tris, dtype=np.int64)
        e1 = v[idx[:, 1]] - v[idx[:, 0]]
        e2 = v[idx[:, 2]] - v[idx[:, 0]]
        face_n = np.cross(e1, e2)          # magnitude ~ 2x triangle area,
                                            # so summing these area-weights
                                            # the average automatically
        for k in range(3):
            np.add.at(normals, idx[:, k], face_n)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    normals = normals / lengths
    return [tuple(n) for n in normals]


# -------------------------------------------------------------------- glb

def build_glb(bones, submeshes, mapping, out_path, texture_index=None,
             force_hash=None):
    bin_parts = []

    def push(data):
        off = sum(len(b) for b in bin_parts)
        pad = (-len(data)) % 4
        bin_parts.append(data + b"\x00" * pad)
        return off, len(data)

    accessors, buffer_views, mesh_prims = [], [], []
    images, textures, samplers, materials = [], [], [], []
    img_cache = {}   # hash -> texture index, so a reused texture embeds once

    if texture_index:
        avail = ", ".join(f"{h:08x}" for h in sorted(texture_index)[:12])
        more = "" if len(texture_index) <= 12 else f" (+{len(texture_index) - 12} more)"
        print(f"texture index: {len(texture_index)} available: {avail}{more}")

    def _colorfulness(png_path):
        """Rough check for whether an image looks like a genuine, opaque
        diffuse color texture, as opposed to a greyscale mask (lightmap/
        AO/shadow), a tangent-space normal map, or a mostly-transparent
        decal/pattern overlay meant to be alpha-blended over a separate
        base color by the game's own shader — not something that stands
        alone as baseColorTexture. Sampled sparsely — a heuristic to rank
        candidates, not a real decoder.

        Three disqualifying signatures, checked independently:
          - near-perfect R≈G≈B correlation: greyscale mask.
          - average blue channel far above red/green, both near neutral
            (128): normal map.
          - low average alpha: a decal/overlay, real color data but most
            of the image is meant to show whatever's underneath it,
            which a flat baseColorTexture has no way to represent. Used
            directly, this renders as black-with-scattered-color, easy
            to mistake for "it embedded something, just wrong" rather
            than "this was never meant to be used alone."
        """
        try:
            import zlib as _zlib
            d = png_path.read_bytes()
            pos, w = 8, None
            idat = b""
            colortype = None
            while pos < len(d):
                ln = struct.unpack_from(">I", d, pos)[0]
                tag = d[pos + 4:pos + 8]
                chunk = d[pos + 8:pos + 8 + ln]
                if tag == b"IHDR":
                    w, h = struct.unpack_from(">2I", chunk, 0)
                    colortype = chunk[9]
                elif tag == b"IDAT":
                    idat += chunk
                elif tag == b"IEND":
                    break
                pos += 12 + ln
            raw = _zlib.decompress(idat)
            has_alpha = colortype == 6
            ch = 4 if has_alpha else 3
            stride = w * ch
            prev = [0] * stride
            i = 0
            rs, gs, bs, als, diffs = [], [], [], [], []
            for _y in range(h):
                ftype = raw[i]; i += 1
                row = bytearray(raw[i:i + stride]); i += stride
                if ftype == 1:                          # Sub
                    for x in range(ch, stride):
                        row[x] = (row[x] + row[x - ch]) & 0xFF
                elif ftype == 2:                        # Up
                    for x in range(stride):
                        row[x] = (row[x] + prev[x]) & 0xFF
                elif ftype == 3:                        # Average
                    for x in range(stride):
                        a = row[x - ch] if x >= ch else 0
                        row[x] = (row[x] + (a + prev[x]) // 2) & 0xFF
                elif ftype == 4:                        # Paeth
                    for x in range(stride):
                        a = row[x - ch] if x >= ch else 0
                        b = prev[x]
                        c = prev[x - ch] if x >= ch else 0
                        p = a + b - c
                        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                        pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                        row[x] = (row[x] + pred) & 0xFF
                prev = list(row)
                for x in range(0, stride, ch * 7):        # sparse sample
                    r, g, b = row[x], row[x + 1], row[x + 2]
                    rs.append(r); gs.append(g); bs.append(b)
                    diffs.append(abs(r - g) + abs(g - b) + abs(r - b))
                    if has_alpha:
                        als.append(row[x + 3])
            n = max(1, len(rs))
            mr, mg, mb = sum(rs) / n, sum(gs) / n, sum(bs) / n
            looks_like_normal_map = (
                mb > 200 and abs(mr - 128) < 40 and abs(mg - 128) < 40
                and mb - max(mr, mg) > 60)
            if looks_like_normal_map:
                return -1000       # disqualified: real divergence, wrong kind
            if has_alpha and als:
                ma = sum(als) / len(als)
                if ma < 200:        # meaningfully non-opaque, not just AA edges
                    return -1000    # disqualified: decal/overlay, not a base color
            return sum(diffs) / n
        except Exception:
            return -1                                    # couldn't check; don't crash the export over it

    def texture_for(refs, submesh_idx):
        """Best texture_index hit among a submesh's ref hashes, embedded
        (PNG bytes pushed into the shared buffer) at most once per image.
        When more than one candidate ref resolves to a real PNG, prefers
        whichever one actually looks like a color image over a greyscale
        one (lightmaps/AO/shadow masks are real texture references too,
        but they're not what should go in baseColorTexture)."""
        if not refs:
            print(f"  submesh {submesh_idx}: no texture reference hashes "
                 f"found for it at all (untextured — not a matching problem, "
                 f"this submesh never named a texture in the first place)")
            return None
        if force_hash is not None:
            if force_hash not in texture_index:
                print(f"  submesh {submesh_idx}: --texture {force_hash:08x} "
                     f"was given but that hash isn't in this unit's texture "
                     f"index at all — check the hex value against the "
                     f"filenames actually sitting in the *_textures folder")
                return None
            h = force_hash
            chosen_reason = "forced via --texture"
            if h in img_cache:
                print(f"  submesh {submesh_idx}: matched {h:08x} ({chosen_reason}, already embedded, reused)")
                return img_cache[h]
            img = Path(texture_index[h])
            off, ln = push(img.read_bytes())
            images.append({"bufferView": len(buffer_views), "mimeType": "image/png",
                           "name": img.stem})
            buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": ln})
            if not samplers:
                samplers.append({})
            textures.append({"source": len(images) - 1, "sampler": 0})
            idx = len(textures) - 1
            img_cache[h] = idx
            print(f"  submesh {submesh_idx}: matched {h:08x} ({chosen_reason}) -> {img.name}, embedded")
            return idx
        if not texture_index:
            print(f"  submesh {submesh_idx}: wants {', '.join(f'{h:08x}' for h in refs)}, "
                 f"but no texture_index was built at all (no texture chunks "
                 f"found anywhere under the unit folder)")
            return None
        candidates = [h for h in refs if h in texture_index]
        if not candidates:
            print(f"  submesh {submesh_idx}: wants {', '.join(f'{h:08x}' for h in refs)}, "
                 f"none of those hashes are in the texture index — the actual "
                 f"texture chunk this submesh references isn't in the "
                 f"extracted unit folder at all (likely another external "
                 f"dependency; check this unit's manifest.tsv 'source' "
                 f"column for these specific hashes, or re-run Container "
                 f"info on whatever file it points to)")
            return None
        if len(candidates) == 1:
            h = candidates[0]
            chosen_reason = "only candidate"
        else:
            scored = []
            for h in candidates:
                img = Path(texture_index[h])
                score = _colorfulness(img) if img.suffix.lower() == ".png" else -1
                scored.append((score, h))
            print(f"  submesh {submesh_idx}: {len(candidates)} texture candidates "
                 f"{', '.join(f'{h:08x}(color-score {s:.1f})' for s, h in scored)}"
                 f" — picking the highest score (0 or near-0 usually means a "
                 f"lightmap/AO/shadow mask, not the diffuse)")
            scored.sort(reverse=True)
            h = scored[0][1]
            chosen_reason = f"highest color-score of {len(candidates)} candidates"
        if h in img_cache:
            print(f"  submesh {submesh_idx}: matched {h:08x} ({chosen_reason}, already embedded, reused)")
            return img_cache[h]
        img = Path(texture_index[h])
        if not img.exists() or img.suffix.lower() != ".png":
            print(f"  submesh {submesh_idx}: matched {h:08x} but it's not a "
                 f"usable PNG ({img}) — DDS can't be embedded in glTF, "
                 f"this usually means Pillow isn't available in this build")
            return None
        off, ln = push(img.read_bytes())
        images.append({"bufferView": len(buffer_views), "mimeType": "image/png",
                       "name": img.stem})
        buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": ln})
        if not samplers:
            samplers.append({})
        textures.append({"source": len(images) - 1, "sampler": 0})
        idx = len(textures) - 1
        img_cache[h] = idx
        print(f"  submesh {submesh_idx}: matched {h:08x} ({chosen_reason}) -> {img.name}, embedded")
        return idx

    def accessor(data, comp, type_, count, normalized=False,
                 minmax=None, target=None):
        off, ln = push(data)
        buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": ln,
                             **({"target": target} if target else {})})
        acc = {"bufferView": len(buffer_views) - 1, "componentType": comp,
               "count": count, "type": type_}
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"], acc["max"] = minmax
        accessors.append(acc)
        return len(accessors) - 1

    n_textured = 0
    for sm_idx, (verts, uvs, joints, weights, tris, rigid, refs) in enumerate(submeshes):
        n = len(verts)
        if rigid:
            nb = nearest_bone(verts, bones)
            joints = [[nb, 0, 0, 0]] * n
        else:
            joints = [[mapping[j] if j < len(mapping) else 0 for j in j4]
                      for j4 in joints]
        vmin = [min(v[k] for v in verts) for k in range(3)]
        vmax = [max(v[k] for v in verts) for k in range(3)]
        a_pos = accessor(b"".join(struct.pack("<3f", *v) for v in verts),
                         5126, "VEC3", n, minmax=(vmin, vmax), target=34962)
        normals = smooth_normals(verts, tris)
        a_nrm = accessor(b"".join(struct.pack("<3f", *nv) for nv in normals),
                         5126, "VEC3", n, target=34962)
        a_uv = accessor(b"".join(struct.pack("<2f", u, v) for u, v in uvs),
                        5126, "VEC2", n, target=34962)
        a_j = accessor(b"".join(struct.pack("<4B", *j) for j in joints),
                       5121, "VEC4", n, target=34962)
        a_w = accessor(b"".join(struct.pack("<4f", *w) for w in weights),
                       5126, "VEC4", n, target=34962)
        idx = b"".join(struct.pack("<3H", *t) for t in tris)
        a_i = accessor(idx, 5123, "SCALAR", len(tris) * 3, target=34963)
        prim = {"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv,
                               "JOINTS_0": a_j, "WEIGHTS_0": a_w},
               "indices": a_i}
        tex = texture_for(refs, sm_idx)
        mat = {"name": f"mat{len(materials)}", "doubleSided": True,
               "pbrMetallicRoughness": {"metallicFactor": 0.0,
                                        "roughnessFactor": 1.0}}
        if tex is not None:
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex}
            n_textured += 1
        else:
            mat["pbrMetallicRoughness"]["baseColorFactor"] = [0.8, 0.8, 0.8, 1.0]
        materials.append(mat)
        prim["material"] = len(materials) - 1
        mesh_prims.append(prim)
    print(f"materials: {n_textured}/{len(submeshes)} submesh(es) textured, "
         f"{len(submeshes) - n_textured} fell back to grey")

    # nodes: locals from world bind matrices (row-major, row-vector
    # convention: W_child = L * W_parent  ->  L = W_c * inv(W_p);
    # glTF column convention: M_std = M_row^T)
    Wr = [np.array(b["world"], dtype=np.float64) for b in bones]
    nodes = []
    for i, b in enumerate(bones):
        L_row = Wr[i] if b["parent"] < 0 else Wr[i] @ np.linalg.inv(Wr[b["parent"]])
        t, q, sc = decompose_trs(L_row.T)
        nodes.append({"name": bone_label(i, bones), "translation": t,
                      "rotation": q, "scale": sc, "children": []})
    roots = []
    for i, b in enumerate(bones):
        if b["parent"] >= 0:
            nodes[b["parent"]]["children"].append(i)
        else:
            roots.append(i)
    for nd in nodes:
        if not nd["children"]:
            nd.pop("children")

    # inverse bind matrices: column-major flattening of inv(W_row)^T
    ibm = b""
    for i in range(len(bones)):
        inv_std = np.linalg.inv(Wr[i]).T
        ibm += inv_std.astype("<f4").T.tobytes()   # column-major flatten
    a_ibm = accessor(ibm, 5126, "MAT4", len(bones))

    mesh_node = len(nodes)
    nodes.append({"name": "mesh", "mesh": 0, "skin": 0})
    gltf = {
        "asset": {"version": "2.0", "generator": "lu_rig.py"},
        "scene": 0,
        "scenes": [{"nodes": roots + [mesh_node]}],
        "nodes": nodes,
        "meshes": [{"primitives": mesh_prims}],
        "materials": materials,
        "skins": [{"inverseBindMatrices": a_ibm,
                   "joints": list(range(len(bones))),
                   "skeleton": roots[0]}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": sum(len(b) for b in bin_parts)}],
    }
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
        gltf["samplers"] = samplers
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    bb = b"".join(bin_parts)
    glb = (struct.pack("<3I", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bb))
           + struct.pack("<2I", len(js), 0x4E4F534A) + js
           + struct.pack("<2I", len(bb), 0x004E4942) + bb)
    Path(out_path).write_bytes(glb)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("unit", help="extracted unit directory (e.g. "
                                 "lu_extracted/naughtybear)")
    ap.add_argument("-o", "--out", required=True, help="output .glb path")
    ap.add_argument("--texture", metavar="HASH",
                    help="force this texture hash (hex, e.g. 26ca1642) as "
                         "the diffuse for every textured submesh, instead "
                         "of the auto-picked highest-scoring candidate. "
                         "Use this once you've confirmed by eye which of "
                         "the candidates printed by a normal run is "
                         "actually the right one — the auto-scoring rules "
                         "out lightmaps and normal maps but can't tell a "
                         "correct color texture from an incorrect but "
                         "highly saturated one, that needs a human look.")
    args = ap.parse_args()
    unit = Path(args.unit)

    skel = None
    for p in sorted(unit.rglob("*.bin")):
        d = p.read_bytes()
        if len(d) > 0x60 and struct.unpack_from(">I", d, 4)[0] == 0x04000001:
            s = parse_skeleton(d)
            if s and (skel is None or len(s) > len(skel)):
                skel = s
    if not skel:
        sys.exit("no skeleton (type 04000001) chunk found in unit")
    print(f"skeleton: {len(skel)} bones")

    best = None
    mesh_dirs = [unit / "mesh_buffers", unit / "type_34000007"]
    mesh_paths = []
    for md in mesh_dirs:
        if md.exists():
            mesh_paths += sorted(md.glob("*.bin"))
    for p in mesh_paths:
        d = p.read_bytes()
        if not is_mesh_chunk(d):
            continue
        subs = extract_skinned_mesh(d)
        nv = sum(len(s[0]) for s in subs)
        if subs and (best is None or nv > best[0]):
            best = (nv, subs, p.name)
    if not best:
        # Don't just fail — this exact failure usually means "unit" is one
        # level too shallow (pointed at a multi-file extract destination
        # instead of one file's own subfolder within it), not that the
        # data genuinely isn't there. Check recursively, purely to give a
        # specific hint; the real (non-recursive) search above is what
        # actually decides pass/fail, so pointing at a multi-unit folder
        # doesn't silently grab a mesh from the wrong sibling.
        deeper = sorted(set(p.parent for p in unit.rglob("*.bin")
                            if p.parent.name in ("mesh_buffers", "type_34000007")))
        if deeper:
            hint = "\n".join(f"    {d}" for d in deeper[:5])
            sys.exit(f"no skinned mesh found directly in {unit}, but a mesh "
                     f"folder exists deeper:\n{hint}\n"
                     f"  'unit' usually needs to point at one file's own "
                     f"extracted subfolder, not the folder you extracted "
                     f"multiple files into — try pointing at the folder "
                     f"printed above instead.")
        sys.exit(f"no skinned mesh found anywhere under {unit} "
                 f"(checked recursively) — this unit may genuinely not "
                 f"have a skinned character in it")
    nv, subs, name = best
    print(f"mesh {name}: {len(subs)} submeshes, {nv} verts")
    mapping = solve_palette(subs, skel)
    if mapping is None:
        sys.exit("could not solve skin palette")
    print(f"solved palette: {len(mapping)} skin slots -> skeleton bones")

    # textures: convert every texture chunk in the unit, index by the hash
    # recovered from its filename (naughty_lu.py extract names chunks
    # NNNN_<hash-or-name>), same convention lu_convert.py's main() uses.
    tex_dir = Path(args.out).parent / (Path(args.out).stem + "_textures")
    tex_index = {}
    tex_paths = sorted(unit.rglob("*.bin"))
    n_tex = 0
    for p in tex_paths:
        d = p.read_bytes()
        if not is_texture_chunk(d):
            continue
        tex_dir.mkdir(parents=True, exist_ok=True)
        written = convert_texture(d, tex_dir / p.stem)
        img = next((w for w in written if w.suffix == ".png"), None)
        if img:
            tail = p.stem.split("_", 1)[-1]
            try:
                tex_index[int(tail, 16)] = img
            except ValueError:
                import zlib
                tex_index[zlib.crc32(tail.lower().encode()) & 0xFFFFFFFF] = img
            n_tex += 1
    if n_tex:
        print(f"textures: {n_tex} converted to {tex_dir}")

    force_hash = None
    if args.texture:
        try:
            force_hash = int(args.texture, 16)
        except ValueError:
            sys.exit(f"--texture {args.texture!r} isn't a valid hex hash "
                     f"(expected something like 26ca1642)")
    out = build_glb(skel, subs, mapping, args.out, texture_index=tex_index,
                    force_hash=force_hash)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
