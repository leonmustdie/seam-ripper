#!/usr/bin/env python3
"""
lu_convert.py — convert extracted Naughty Bear .lu resource chunks into
Blender-friendly formats.

Works on a raw .lu/.luh container directly, on the output of
naughty_lu.py extract, or on individual .bin chunks:

  textures (type 14200007)   ->  .dds (+ .png if Pillow is installed)
  meshes   (type 04000007)   ->  .obj + .mtl, UV-mapped, with materials
                                 bound to the converted textures

Usage:
  python3 lu_convert.py <extracted_dir> [-o out_dir]
  python3 lu_convert.py some_texture.bin some_mesh.bin [-o out_dir]

Texture pipeline (validated on X360 'Gold Edition' data):
  chunk header: +0x08 height, +0x0C width, +0x10 bpp, +0x24 mip count,
                +0x28 Xenos format dword (low 6 bits: 0x12=DXT1, 0x14=DXT5),
                +0x38 data offset, +0x3C data size
  pixel data is u16-byteswapped and 2D-tiled (Xenos XGAddress2DTiledOffset,
  surfaces padded to 32x32 blocks); base mip level is exported.

Mesh pipeline:
  chunk contains per-submesh descriptor blocks; each holds a buffer quad
  {vb_offset, vb_size, ib_offset, ib_size} (offsets 4KB-aligned, chunk-
  relative). Vertices are big-endian: float3 position at +0; UV is a pair
  of half-floats whose offset (and the vertex stride) vary per submesh and
  are auto-detected (stride via minimal-edge-length scoring, UV via range
  analysis). Index buffers are 16-bit big-endian triangle strips with
  0xFFFF primitive-restart. Descriptors also reference the submesh's
  textures as {crc32_hash, 0x04200007} pairs, used here to bind materials.

Only Pillow is needed (and only for PNG output); everything else is stdlib.
"""

import argparse
import math
import struct
import sys
from pathlib import Path

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

TEX_TYPE_TAG = b"\x34\x20\x00\x07"
MESH_TYPE_TAG = b"\x34\x20\x00"          # mesh chunks start 00000020 ... 34 20 00 04
XENOS_FORMATS = {0x12: ("DXT1", 8), 0x13: ("DXT3", 16), 0x14: ("DXT5", 16)}


# ---------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------

def byteswap16(b):
    a = bytearray(b)
    a[0::2], a[1::2] = b[1::2], b[0::2]
    return bytes(a)


def xenos_untile(data, wb, hb, bpb):
    """Untile an Xbox 360 2D tiled surface of wb x hb blocks (bpb bytes per
    block). The tiled surface is padded to 32x32 blocks; output is cropped
    linear data. Port of XGAddress2DTiledOffset."""
    aw = (wb + 31) & ~31
    ah = (hb + 31) & ~31
    need = aw * ah * bpb
    if len(data) < need:
        data = data + b"\0" * (need - len(data))
    out = bytearray(wb * hb * bpb)
    log_bpp = (bpb >> 2) + ((bpb >> 1) >> (bpb >> 2))
    for y in range(hb):
        for x in range(wb):
            macro = ((x >> 5) + (y >> 5) * (aw >> 5)) << (log_bpp + 7)
            micro = ((x & 7) + ((y & 6) << 2)) << log_bpp
            off = (macro + ((micro & ~15) << 1) + (micro & 15)
                   + ((y & 8) << (3 + log_bpp)) + ((y & 1) << 4))
            src = ((((off & ~511) << 3) + ((off & 448) << 2) + (off & 63)
                    + ((y & 16) << 7)
                    + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> log_bpp)
            so, do = src * bpb, (y * wb + x) * bpb
            out[do:do + bpb] = data[so:so + bpb]
    return bytes(out)


def dds_bytes(w, h, fourcc, payload):
    hdr = struct.pack("<4sII II I II 44x", b"DDS ", 124,
                      0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, h, w,
                      len(payload), 0, 1)
    pf = struct.pack("<II4sIIIII", 32, 0x4, fourcc.encode(), 0, 0, 0, 0, 0)
    caps = struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    return hdr + pf + caps + payload


def is_texture_chunk(data):
    return len(data) >= 0x40 and data[:4] == TEX_TYPE_TAG


def convert_texture(data, out_base):
    """Convert one texture chunk. Returns list of written paths."""
    h, w = struct.unpack_from(">2I", data, 8)
    mips = struct.unpack_from(">I", data, 0x24)[0]
    fmt = struct.unpack_from(">I", data, 0x28)[0]
    doff, dsz = struct.unpack_from(">2I", data, 0x38)
    code = fmt & 0x3F
    if code not in XENOS_FORMATS:
        print(f"  ! {out_base.name}: unsupported Xenos format {code:#04x} "
              f"(dword {fmt:#010x}); dumping raw data", file=sys.stderr)
        p = out_base.with_suffix(".texdata.bin")
        p.write_bytes(data[doff:doff + dsz])
        return [p]
    fourcc, bpb = XENOS_FORMATS[code]
    wb, hb = max(1, w // 4), max(1, h // 4)
    linear = xenos_untile(byteswap16(data[doff:doff + dsz]), wb, hb, bpb)
    written = []
    ddsp = out_base.with_suffix(".dds")
    ddsp.write_bytes(dds_bytes(w, h, fourcc, linear))
    written.append(ddsp)
    if HAVE_PIL:
        try:
            img = Image.open(ddsp).convert("RGBA")
            pngp = out_base.with_suffix(".png")
            img.save(pngp)
            written.append(pngp)
        except Exception as e:
            print(f"  ! PNG decode failed for {ddsp.name}: {e}", file=sys.stderr)
    return written


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------

def is_mesh_chunk(data):
    return (len(data) > 0x1000 and data[:4] == b"\x00\x00\x00\x20"
            and data[0xc:0xf] == MESH_TYPE_TAG)


def _decode_strips(raw, nverts):
    tris, strip = [], []

    def flush():
        for i in range(len(strip) - 2):
            a, b, c = strip[i], strip[i + 1], strip[i + 2]
            if len({a, b, c}) < 3 or max(a, b, c) >= nverts:
                continue
            tris.append((a, c, b) if i & 1 else (a, b, c))

    for t in raw:
        if t == 0xFFFF:
            flush()
            strip = []
        else:
            strip.append(t)
    flush()
    return tris


def _find_buffer_quads(d):
    out, seen = [], set()
    for o in range(0, len(d) - 16, 4):
        vo, vs, io_, isz = struct.unpack_from(">4I", d, o)
        if (vo and io_ and vo % 0x1000 == 0 and io_ % 0x1000 == 0 and vo < io_
                and 0 < vs <= io_ - vo and 0 < isz <= len(d) - io_
                and vs % 4 == 0 and isz % 2 == 0 and vo not in seen):
            seen.add(vo)
            out.append((o, vo, vs, io_, isz))
    return out


def _find_texture_refs(d, start, end):
    """Scan a descriptor window for {hash, 0x04200007} texture references."""
    refs = []
    for o in range(start, min(end, len(d) - 8), 4):
        h, t = struct.unpack_from(">2I", d, o)
        if t == 0x04200007 and h not in (0, 0xFFFFFFFF) and h not in refs:
            refs.append(h)
    return refs



def _layout_candidates(d, vo, vs, raw, decl, fixed_stride=None):
    """Enumerate plausible (stride, pos_off) pairs, scored by strip
    locality. When a vertex declaration is available, the stride must
    accommodate the declared UV offset and position candidates are the
    declared position offset plus a skinning-prefix shift."""
    max_idx = max((t for t in raw if t != 0xFFFF), default=0)
    out = []
    strides = [fixed_stride] if fixed_stride else list(range(16, 65, 4))
    for s in strides:
        if vs % s:
            continue
        n = vs // s
        if max_idx >= n or n < 3:
            continue
        if decl is not None:
            d_pos, d_uv = decl[0], decl[1]
            explicit = decl[2] if len(decl) > 2 else True
            if d_uv is not None and s < d_uv + 4:
                continue
            if s < d_pos + 12:
                continue
            if explicit:
                pos_range = [d_pos + 4 * k for k in range(0, 7)
                             if d_pos + 4 * k + 12 <= s]
            else:
                pos_range = [d_pos]   # implicit position: no skin prefix
        else:
            pos_range = list(range(0, s - 11, 4))
        tris = _decode_strips(raw, n)
        if not tris:
            continue
        sample_t = tris[:200]
        for po in pos_range:
            try:
                V = [struct.unpack_from(">3f", d, vo + i * s + po)
                     for i in range(n)]
            except struct.error:
                continue
            bad = unit = wlike = tiny = 0
            lo = [1e30] * 3
            hi = [-1e30] * 3
            step = max(1, n // 256)
            cnt = 0
            for i in range(0, n, step):
                x, y, z = V[i]
                cnt += 1
                if any(math.isnan(c) or abs(c) > 1e4 for c in (x, y, z)):
                    bad += 1
                    continue
                if any(0 < abs(c) < 1e-5 for c in (x, y, z)):
                    tiny += 1
                norm = x * x + y * y + z * z
                if 0.98 <= norm <= 1.02:
                    unit += 1
                if 0 <= x <= 1.01 and 0 <= y <= 1.01 and 0 <= z <= 1.01 \
                        and norm <= 1.01:
                    wlike += 1
                for k, c in enumerate((x, y, z)):
                    lo[k] = min(lo[k], c)
                    hi[k] = max(hi[k], c)
            if bad or cnt == 0:
                continue
            if decl is None and tiny > cnt * 0.3:
                continue       # int/byte field, not floats (blind scan only)
            if unit > cnt * 0.85:          # normal/tangent field
                continue
            diag = math.dist(lo, hi)
            if diag < 1e-3:                # constant / degenerate
                continue
            if wlike > cnt * 0.9 and diag < 2.0:  # blend weights
                continue
            edges = [math.dist(V[a], V[b]) for a, b, _ in sample_t]
            mean_edge = sum(edges) / len(edges)
            rng = 48271
            rand_d = []
            for _ in range(min(200, n)):
                rng = (rng * 48271) % 0x7FFFFFFF
                a = rng % n
                rng = (rng * 48271) % 0x7FFFFFFF
                b = rng % n
                if a != b:
                    rand_d.append(math.dist(V[a], V[b]))
            mean_rand = sum(rand_d) / len(rand_d) if rand_d else 0
            if mean_rand < 1e-6:
                continue
            out.append((mean_edge / mean_rand, s, po))
    out.sort()
    return out[:8]


def _read_trailer(d, io_, isz):
    """Read the submesh trailer that immediately follows each index buffer
    (4-aligned): {vertex_stride, count, primitive_type, 0, decl_ptr,
    n_decl_elements}. primitive_type 6 = triangle strip (count = index
    count), 4 = triangle list (count = triangle count). Returns dict or
    None when absent (false-positive buffer quads have no trailer)."""
    t = (io_ + isz + 3) & ~3
    if t + 24 > len(d):
        return None
    stride, count, prim, zero, declp, nel = struct.unpack_from(">6I", d, t)
    if not (12 <= stride <= 128) or stride % 4 or zero != 0:
        return None
    if prim not in (4, 5, 6) or count == 0 or not (8 <= declp <= len(d) - 4):
        return None
    need = count * 3 if prim == 4 else count
    if need * 2 > isz:
        return None
    decl = _parse_decl_at(d, declp)
    return {"stride": stride, "count": count, "prim": prim,
            "decl": decl}


def _parse_decl_at(d, o):
    """Parse a vertex declaration blob at offset o: optional leading zero
    dword, then 12-byte elements {gpu_format, usage<<16|idx, offset} until
    0xFFFFFFFF. Position is the element with format 0x001A2286
    (32_32_32_FLOAT); if absent the position is implicit at offset 0.
    Returns (pos_off, uv_off_or_None) or None if malformed."""
    if o + 4 > len(d):
        return None
    if struct.unpack_from(">I", d, o)[0] == 0:
        o += 4
    pos_off = None
    offsets = []
    for _ in range(16):
        if o + 4 > len(d):
            return None
        fmt = struct.unpack_from(">I", d, o)[0]
        if fmt == 0xFFFFFFFF:
            break
        if o + 12 > len(d):
            return None
        _, off = struct.unpack_from(">2I", d, o + 4)
        o += 12
        if off >= 0x10000:      # second stream / end marker
            continue
        if off >= 0x200 or off % 2:
            return None
        if (fmt & 0xFFFFFF) == FMT_POS_FLOAT3 and pos_off is None:
            pos_off = off
        offsets.append(off)
    else:
        return None
    explicit = pos_off is not None
    if pos_off is None:
        pos_off = 0             # implicit position before first element
    uv_cands = [off for off in offsets
                if not (pos_off <= off < pos_off + 12)]
    return pos_off, (max(uv_cands) if uv_cands else None), explicit


def _decode_list(raw, nverts):
    tris = []
    for i in range(0, len(raw) - 2, 3):
        a, b, c = raw[i], raw[i + 1], raw[i + 2]
        if a == b or b == c or a == c:
            continue
        if a < nverts and b < nverts and c < nverts:
            tris.append((a, b, c))
    return tris

def convert_mesh(data, out_base, texture_index=None, glb=True):
    """Convert one mesh chunk to OBJ+MTL (and GLB unless glb=False).
    texture_index maps crc32 hash -> absolute Path of the converted texture
    image; MTL references are made relative to the OBJ, GLB embeds the PNG."""
    quads = _find_buffer_quads(data)
    if not quads:
        print(f"  ! {out_base.name}: no vertex/index buffers found",
              file=sys.stderr)
        return []
    # ---- pass 1: gather layout candidates per submesh -------------------
    prepared = []
    prev_field = 0x20
    any_trailer = any(_read_trailer(data, q[3], q[4]) for q in quads)
    for field_off, vo, vs, io_, isz in quads:
        refs = _find_texture_refs(data, prev_field, field_off)
        prev_field = io_ + isz
        tr = _read_trailer(data, io_, isz)
        if tr is None and any_trailer:
            continue            # false-positive buffer quad: skip silently
        n_idx = isz // 2
        prim = 6
        if tr is not None:
            prim = tr["prim"]
            if prim == 4:       # list: count is the triangle count, exact
                n_idx = min(n_idx, tr["count"] * 3)
        raw = struct.unpack_from(f">{n_idx}H", data, io_)
        while raw and raw[-1] == 0xBFBF:    # trailing pad indices
            raw = raw[:-1]
        if tr is not None:
            decl = tr["decl"]
            stride = tr["stride"] if vs % tr["stride"] == 0 else None
        else:
            nxt = min((q[1] for q in quads if q[1] > vo), default=len(data))
            decl = _find_decl(data, io_ + isz, nxt)
            stride = None
        cands = _layout_candidates(data, vo, vs, raw, decl, stride)
        prepared.append((vo, vs, raw, decl, refs, cands, prim))

    # confident picks: unique candidate or clear locality winner
    g_lo = [1e30] * 3
    g_hi = [-1e30] * 3
    have_global = False
    for vo, vs, raw, decl, refs, cands, prim in prepared:
        if not cands:
            continue
        if len(cands) == 1 or cands[0][0] < 0.6 * cands[1][0]:
            sc, st, po = cands[0]
            n = vs // st
            for i in range(0, n, max(1, n // 128)):
                x, y, z = struct.unpack_from(">3f", data, vo + i * st + po)
                for k, c in enumerate((x, y, z)):
                    g_lo[k] = min(g_lo[k], c)
                    g_hi[k] = max(g_hi[k], c)
            have_global = True
    if have_global:
        m = [(hi - lo) * 0.15 + 0.05 for lo, hi in zip(g_lo, g_hi)]
        g_lo = [lo - mm for lo, mm in zip(g_lo, m)]
        g_hi = [hi + mm for hi, mm in zip(g_hi, m)]

    # ---- pass 2: final pick (containment in the model bbox breaks ties) --
    submeshes = []
    for vo, vs, raw, decl, refs, cands, prim in prepared:
        if not cands:
            print(f"  ! {out_base.name}: vb@{vo:#x}: layout detection failed;"
                  f" skipping submesh", file=sys.stderr)
            continue
        best = None
        for sc, st, po in cands:
            contain = 1.0
            if have_global:
                n = vs // st
                pts = [struct.unpack_from(">3f", data, vo + i * st + po)
                       for i in range(0, n, max(1, n // 128))]
                inside = sum(1 for x, y, z in pts
                             if g_lo[0] <= x <= g_hi[0]
                             and g_lo[1] <= y <= g_hi[1]
                             and g_lo[2] <= z <= g_hi[2])
                contain = inside / len(pts)
            final = sc / (0.05 + contain)
            if best is None or final < best[0]:
                best = (final, st, po)
        _, stride, pos_off = best
        n = vs // stride
        d_uv = decl[1] if decl else None
        uvo = d_uv if _uv_sane(data, vo, stride, n, d_uv) \
            else _detect_uv_offset(data, vo, stride, n, pos_off)
        V = [struct.unpack_from(">3f", data, vo + i * stride + pos_off)
             for i in range(n)]
        UV = ([struct.unpack_from(">2e", data, vo + i * stride + uvo)
               for i in range(n)] if uvo is not None else [(0.0, 0.0)] * n)
        tris = (_decode_list(raw, n) if prim == 4
                else _decode_strips(raw, n))
        submeshes.append((V, UV, tris, stride, pos_off, uvo, refs))

    import os as _os

    def _sm_image(sm):
        """Absolute Path of the first indexed texture a submesh references."""
        if not texture_index:
            return None
        return next((Path(texture_index[h]) for h in sm[6]
                     if h in texture_index), None)

    objp = out_base.with_suffix(".obj")
    mtlp = out_base.with_suffix(".mtl")
    with open(mtlp, "w") as f:
        for i, sm in enumerate(submeshes):
            f.write(f"newmtl mat{i}\nKd 0.8 0.8 0.8\n")
            img = _sm_image(sm)
            if img:
                f.write(f"map_Kd {_os.path.relpath(img, out_base.parent)}\n")
            f.write("\n")
    with open(objp, "w") as f:
        f.write("# converted from Naughty Bear .lu mesh chunk\n")
        f.write("# note: up-axis varies (characters are Y-up, some props Z-up); rotate in Blender as needed\n")
        f.write(f"mtllib {mtlp.name}\n")
        base = 1
        for i, (V, UV, tris, stride, pos_off, uvo, refs) in enumerate(submeshes):
            f.write(f"o submesh{i}\nusemtl mat{i}\n")
            for v in V:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for u, vv in UV:
                f.write(f"vt {u:.6f} {1.0 - vv:.6f}\n")
            for a, b, c in tris:
                f.write("f " + " ".join(f"{base + k}/{base + k}"
                                        for k in (a, b, c)) + "\n")
            base += len(V)
    written = [objp, mtlp]
    if glb:
        glbp = out_base.with_suffix(".glb")
        try:
            write_glb(glbp, submeshes,
                      images=[_sm_image(sm) for sm in submeshes])
            written.append(glbp)
        except Exception as e:
            print(f"  ! GLB export failed for {out_base.name}: {e}",
                  file=sys.stderr)
    nv = sum(len(s[0]) for s in submeshes)
    nt = sum(len(s[2]) for s in submeshes)
    layouts = [f"s{s[3]}p{s[4]}" + (f"uv{s[5]}" if s[5] is not None else "")
               for s in submeshes]
    print(f"  {objp.name}: {len(submeshes)} submeshes, {nv} verts, {nt} tris,"
          f" layouts {layouts}")
    return written


# ---------------------------------------------------------------------------
# GLB (binary glTF 2.0) export — stdlib only
# ---------------------------------------------------------------------------

_GLTF_UBYTE, _GLTF_USHORT, _GLTF_UINT, _GLTF_FLOAT = 5121, 5123, 5125, 5126
_TGT_ARRAY, _TGT_ELEMENT = 34962, 34963


def write_glb(out_path, submeshes, images=None):
    """Write submeshes as one binary glTF 2.0 file (single mesh, one
    primitive per submesh). submeshes entries are the tuples built by
    convert_mesh: (V, UV, tris, stride, pos_off, uvo, refs). images is an
    optional per-submesh list of image Paths; PNG/JPEG files get embedded
    into the GLB and bound as baseColorTexture (DDS can't be embedded —
    the glTF spec only allows PNG/JPEG).

    Note on UVs: the source data is D3D-style (origin top-left), which is
    also what glTF uses, so V is written unflipped — unlike the OBJ path,
    which flips to OBJ's bottom-left origin.
    """
    import json as _json

    jroot = {
        "asset": {"version": "2.0", "generator": "Seam Ripper lu_convert"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": Path(out_path).stem}],
        "meshes": [{"primitives": []}],
        "materials": [],
        "accessors": [],
        "bufferViews": [],
    }
    bin_parts = []
    offset = 0

    def _add_view(payload, target=None):
        nonlocal offset
        pad = (-len(payload)) % 4
        payload = payload + b"\0" * pad
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload) - pad}
        if target is not None:
            view["target"] = target
        jroot["bufferViews"].append(view)
        bin_parts.append(payload)
        offset += len(payload)
        return len(jroot["bufferViews"]) - 1

    def _add_accessor(view, ctype, count, atype, mn=None, mx=None):
        acc = {"bufferView": view, "componentType": ctype,
               "count": count, "type": atype}
        if mn is not None:
            acc["min"], acc["max"] = mn, mx
        jroot["accessors"].append(acc)
        return len(jroot["accessors"]) - 1

    img_cache = {}          # image Path -> texture index

    def _texture_for(img):
        if img in img_cache:
            return img_cache[img]
        img = Path(img)
        if not img.exists() or img.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            return None
        mime = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
        view = _add_view(img.read_bytes())
        jroot.setdefault("images", []).append(
            {"bufferView": view, "mimeType": mime, "name": img.stem})
        jroot.setdefault("samplers", [{}])
        jroot.setdefault("textures", []).append(
            {"source": len(jroot["images"]) - 1, "sampler": 0})
        idx = len(jroot["textures"]) - 1
        img_cache[img] = idx
        return idx

    for i, (V, UV, tris, _stride, _pos_off, uvo, _refs) in enumerate(submeshes):
        if not tris:
            continue
        flat_v = [c for v in V for c in v]
        pos_acc = _add_accessor(
            _add_view(struct.pack(f"<{len(flat_v)}f", *flat_v), _TGT_ARRAY),
            _GLTF_FLOAT, len(V), "VEC3",
            mn=[min(v[k] for v in V) for k in range(3)],
            mx=[max(v[k] for v in V) for k in range(3)])
        attrs = {"POSITION": pos_acc}
        if uvo is not None:
            flat_uv = [c for uv in UV for c in uv]
            attrs["TEXCOORD_0"] = _add_accessor(
                _add_view(struct.pack(f"<{len(flat_uv)}f", *flat_uv), _TGT_ARRAY),
                _GLTF_FLOAT, len(UV), "VEC2")
        idx = [k for t in tris for k in t]
        if len(V) <= 0xFFFF:
            ibytes, ctype = struct.pack(f"<{len(idx)}H", *idx), _GLTF_USHORT
        else:
            ibytes, ctype = struct.pack(f"<{len(idx)}I", *idx), _GLTF_UINT
        idx_acc = _add_accessor(_add_view(ibytes, _TGT_ELEMENT),
                                ctype, len(idx), "SCALAR")
        mat = {"name": f"mat{i}", "doubleSided": True,
               "pbrMetallicRoughness": {"metallicFactor": 0.0,
                                        "roughnessFactor": 1.0}}
        tex = _texture_for(images[i]) if images and images[i] else None
        if tex is not None:
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex}
        else:
            mat["pbrMetallicRoughness"]["baseColorFactor"] = [0.8, 0.8, 0.8, 1.0]
        jroot["materials"].append(mat)
        jroot["meshes"][0]["primitives"].append(
            {"attributes": attrs, "indices": idx_acc,
             "material": len(jroot["materials"]) - 1})

    if not jroot["meshes"][0]["primitives"]:
        raise ValueError("no exportable submeshes")
    blob = b"".join(bin_parts)
    jroot["buffers"] = [{"byteLength": len(blob)}]
    jbytes = _json.dumps(jroot, separators=(",", ":")).encode()
    jbytes += b" " * ((-len(jbytes)) % 4)
    blob += b"\0" * ((-len(blob)) % 4)
    total = 12 + 8 + len(jbytes) + 8 + len(blob)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(jbytes), b"JSON") + jbytes)
        f.write(struct.pack("<I4s", len(blob), b"BIN\0") + blob)


FMT_POS_FLOAT3 = 0x1A2286  # Xenos GPU fetch format: 32_32_32_FLOAT


def _find_decl(d, start, end):
    """Find an X360 vertex declaration in d[start:end]. Declarations are
    12-byte elements {gpu_format, usage<<16|usage_index, offset} ending in
    0xFFFFFFFF; the position element uses format 0x001A2286 (32_32_32_FLOAT).
    Returns (pos_off, uv_off_or_None) or None."""
    start = (start + 3) & ~3
    for o in range(start, min(end, len(d) - 12) , 4):
        if struct.unpack_from(">I", d, o)[0] != FMT_POS_FLOAT3:
            continue
        usage, pos_off = struct.unpack_from(">2I", d, o + 4)
        if pos_off >= 0x200 or pos_off % 4 or usage >= 0x100000:
            continue
        # walk subsequent elements for UV candidates
        offsets = []
        p = o + 12
        ok = True
        for _ in range(16):
            if p + 4 > len(d):
                ok = False
                break
            fmt = struct.unpack_from(">I", d, p)[0]
            if fmt == 0xFFFFFFFF:
                break
            if p + 12 > len(d):
                ok = False
                break
            _, off = struct.unpack_from(">2I", d, p + 4)
            p += 12
            if off >= 0x10000:   # stream-1 data / end marker
                continue
            if off >= 0x200 or off % 2:
                ok = False
                break
            offsets.append(off)
        if not ok:
            continue
        uv_cands = [off for off in offsets
                    if not (pos_off <= off < pos_off + 12)]
        return pos_off, (max(uv_cands) if uv_cands else None), True
    return None


def _uv_sane(d, vo, stride, n, off):
    if off is None or off + 4 > stride:
        return False
    for i in range(0, n, max(1, n // 128)):
        try:
            u, v = struct.unpack_from(">2e", d, vo + i * stride + off)
        except struct.error:
            return False
        if math.isnan(u) or math.isnan(v) or not (-8.1 <= u <= 8.1) \
                or not (-8.1 <= v <= 8.1):
            return False
    return True


def _find_spheres(d, start, end):
    """Collect bounding-sphere candidates {cx,cy,cz,r} from a descriptor
    window: 4 consecutive sane floats with a plausible positive radius."""
    out = []
    for o in range(start, min(end, len(d) - 16), 4):
        try:
            cx, cy, cz, r = struct.unpack_from(">4f", d, o)
        except struct.error:
            break
        if any(math.isnan(v) or abs(v) > 1e3 for v in (cx, cy, cz, r)):
            continue
        if 0.01 < r < 1e3 and (cx, cy, cz) != (0.0, 0.0, 0.0):
            out.append((cx, cy, cz, r))
    return out


def _detect_layout(d, vo, vs, raw, spheres=()):
    """Jointly detect (stride, position_offset) for one vertex buffer.
    Skinned vertices carry bone indices/weights before the position, so the
    position is not always at +0. Candidate float3 fields are filtered:
    - denormal-tiny components are reinterpreted int/byte data
    - mostly-unit-length triples are normals/tangents
    - triples in [0,1] summing to ~1 are blend weights
    Scoring combines strip-edge locality (positions are spatially local
    along triangle strips) with containment in the submesh's bounding
    sphere taken from its descriptor block."""
    max_idx = max((t for t in raw if t != 0xFFFF), default=0)
    best = None
    for s in (16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64):
        if vs % s:
            continue
        n = vs // s
        if max_idx >= n or n < 3:
            continue
        tris = _decode_strips(raw, n)
        if not tris:
            continue
        sample_t = tris[:200]
        for po in range(0, s - 11, 4):
            try:
                V = [struct.unpack_from(">3f", d, vo + i * s + po)
                     for i in range(n)]
            except struct.error:
                continue
            bad = unit = wlike = tiny = 0
            lo = [1e30] * 3
            hi = [-1e30] * 3
            step = max(1, n // 256)
            cnt = 0
            for i in range(0, n, step):
                x, y, z = V[i]
                cnt += 1
                if any(math.isnan(c) or abs(c) > 1e4 for c in (x, y, z)):
                    bad += 1
                    continue
                # reinterpreted ints/bytes decode as denormal-tiny floats;
                # real positions are either exactly 0 or normally scaled
                if any(0 < abs(c) < 1e-5 for c in (x, y, z)):
                    tiny += 1
                norm = x * x + y * y + z * z
                if 0.98 <= norm <= 1.02:
                    unit += 1
                if 0 <= x <= 1.01 and 0 <= y <= 1.01 and 0 <= z <= 1.01 \
                        and norm <= 1.01:
                    wlike += 1
                for k, c in enumerate((x, y, z)):
                    lo[k] = min(lo[k], c)
                    hi[k] = max(hi[k], c)
            if bad or cnt == 0:
                continue
            if decl is None and tiny > cnt * 0.3:
                continue       # int/byte field, not floats (blind scan only)
            if unit > cnt * 0.85:          # normal/tangent field
                continue
            diag = math.dist(lo, hi)
            if diag < 1e-3:                # constant / degenerate
                continue
            if wlike > cnt * 0.9 and diag < 2.0:  # blend weights
                continue
            edges = [math.dist(V[a], V[b]) for a, b, _ in sample_t]
            mean_edge = sum(edges) / len(edges)
            # positions are spatially local along triangle strips: strip
            # edges are much shorter than random vertex pairs. Junk fields
            # (weights, packed data) don't show this locality nearly as
            # strongly, and outliers can't fake it.
            rng = 48271
            rand_d = []
            for _ in range(min(200, n)):
                rng = (rng * 48271) % 0x7FFFFFFF
                a = rng % n
                rng = (rng * 48271) % 0x7FFFFFFF
                b = rng % n
                if a != b:
                    rand_d.append(math.dist(V[a], V[b]))
            mean_rand = sum(rand_d) / len(rand_d) if rand_d else 0
            if mean_rand < 1e-6:
                continue
            contain = 0.0
            if spheres:
                best_c = 0.0
                pts = [V[i] for i in range(0, n, step)]
                for cx, cy, cz, r in spheres:
                    rr = (r * 1.25) ** 2
                    inside = sum(1 for x, y, z in pts
                                 if (x-cx)**2 + (y-cy)**2 + (z-cz)**2 <= rr)
                    best_c = max(best_c, inside / len(pts))
                contain = best_c
            score = (mean_edge / mean_rand) / (0.05 + contain)
            if best is None or score < best[0]:
                best = (score, s, po)
    if best is None:
        return None, None
    return best[1], best[2]


def _detect_uv_offset(d, vo, stride, n, pos_off=0):
    """Find the half2 UV: the latest 2-aligned offset (outside the position
    field) where all sampled values are finite and in a sane texcoord range."""
    best = None
    for off in range(0, stride - 3, 2):
        if pos_off <= off < pos_off + 12 or pos_off <= off + 2 < pos_off + 12:
            continue
        ok = True
        lo = hi = None
        for i in range(0, n, max(1, n // 256)):
            try:
                u, v = struct.unpack_from(">2e", d, vo + i * stride + off)
            except struct.error:
                ok = False
                break
            if math.isnan(u) or math.isnan(v) or not (-1.1 <= u <= 8.1) \
                    or not (-1.1 <= v <= 8.1):
                ok = False
                break
            lo = u if lo is None else min(lo, u)
            hi = u if hi is None else max(hi, u)
        if ok and lo is not None and hi - lo > 1e-3:
            best = off  # later offsets win (UV sits at the tail)
    return best


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def gather_inputs(paths):
    """Returns list of (source, relative_output_stem) pairs, where source is
    either a Path (a .bin chunk on disk) or a (LuFile, LuRecord) tuple (a
    chunk read live from a raw .lu container).

    Accepts three input shapes so the tool "just works" regardless of where
    the user is in the pipeline: a directory of extracted chunks (the
    naughty_lu.py extract output, mirrored in the output), an individual
    .bin chunk, or a raw .lu / .luh container (exploded in memory — no need
    to run extract first).
    """
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*.bin")):
                files.append((f, Path(p.name) / f.relative_to(p).with_suffix("")))
        elif p.suffix.lower() in (".lu", ".luh") or _looks_like_container(p):
            from naughty_lu import LuFile, harvest_names
            lu = LuFile(str(p))
            names = harvest_names([lu])
            for r in lu.records:
                if getattr(r, "external", False):
                    continue
                nm = names.get(r.hash, f"{r.hash:08x}")
                files.append(((lu, r), Path(p.stem) / f"{r.index:04d}_{nm}"))
        else:
            files.append((p, Path(p.stem)))
    return files


def _looks_like_container(p):
    try:
        with open(p, "rb") as fh:
            head = fh.read(4)
        return head == b"\x05LUH" or head[:1] == b"\x03"
    except OSError:
        return False


def _read_source(src):
    """src is either a Path (.bin on disk) or (LuFile, LuRecord)."""
    if isinstance(src, tuple):
        lu, r = src
        return bytes(lu.chunk(r))
    return src.read_bytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("inputs", nargs="+",
                    help="extracted chunk .bin files or directories "
                         "(e.g. the naughty_lu.py extract output)")
    ap.add_argument("-o", "--out", help="output directory "
                                        "(default: alongside inputs)")
    ap.add_argument("--no-glb", action="store_true",
                    help="skip GLB export (write OBJ+MTL only)")
    args = ap.parse_args()

    files = gather_inputs(args.inputs)
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    textures, meshes, skipped, ui_chunks = [], [], 0, 0
    blobs = {}
    for p, rel in files:
        d = _read_source(p)
        key = rel                              # rel is unique per input
        blobs[key] = d
        if is_texture_chunk(d):
            textures.append((key, rel))
        elif is_mesh_chunk(d):
            meshes.append((key, rel))
        else:
            if len(d) >= 8 and d[4:8] == b"\x00\x00\x00\x00" and \
               int.from_bytes(d[:4], "big") == 0x04D00001:
                ui_chunks += 1
            elif b"CFX" in d[:64] or b"GFX" in d[:64] or \
                    (len(d) >= 4 and int.from_bytes(d[:4], "big") == 0x04D00001):
                ui_chunks += 1
            skipped += 1

    # textures first, building hash -> image path index for material binding
    tex_index = {}
    print(f"converting {len(textures)} textures...")
    for key, rel in textures:
        base = (out_dir / rel) if out_dir else Path(rel)
        base.parent.mkdir(parents=True, exist_ok=True)
        written = convert_texture(blobs[key], base)
        img = next((w for w in written if w.suffix == ".png"),
                   next((w for w in written if w.suffix == ".dds"), None))
        if img:
            # chunk stems are NNNN_<name-or-hex hash>; recover the hash
            tail = Path(str(rel)).name.split("_", 1)[-1]
            try:
                tex_index[int(tail, 16)] = img
            except ValueError:
                import zlib
                tex_index[zlib.crc32(tail.lower().encode()) & 0xFFFFFFFF] = img

    print(f"converting {len(meshes)} meshes...")
    for key, rel in meshes:
        base = (out_dir / rel) if out_dir else Path(rel)
        base.parent.mkdir(parents=True, exist_ok=True)
        convert_mesh(blobs[key], base, tex_index, glb=not args.no_glb)

    msg = (f"done ({skipped} non-convertible chunks skipped — animations, "
           f"sounds, scene data etc. are not yet supported)")
    if ui_chunks and not textures:
        msg += (f"\nnote: this container's images are inside {ui_chunks} "
                f"Scaleform UI chunks, not standalone textures. Use pip_gfx.py "
                f"(GUI: 'UI flash / textures') to extract them as PNG.")
    print(msg)


if __name__ == "__main__":
    main()
