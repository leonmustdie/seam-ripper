#!/usr/bin/env python3
"""tests/test_lu_rig.py - regression coverage for lu_rig.py's texture
embedding (added alongside the pre-existing rig/skin export). Fixtures
are synthetic: a hand-built 1x1 PNG and fabricated submesh tuples, not
real game mesh/texture data.
"""
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import numpy as np
import lu_rig

BONES = [{"parent": -1, "world": np.eye(4).tolist()}]
MAPPING = [0]
TRIS = [(0, 1, 2)]
VERTS = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
UVS = [(0, 0), (1, 0), (0, 1)]
JOINTS = [[0, 0, 0, 0]] * 3
WEIGHTS = [[1, 0, 0, 0]] * 3


def _tiny_png(rgb=(255, 0, 0)):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
    return sig + ihdr + idat + chunk(b"IEND", b"")


def _patterned_png(pixel_fn, w=8, h=8):
    """An 8x8 RGBA PNG with a real per-pixel pattern, for testing the
    colorfulness heuristic, which needs more than one pixel to say
    anything meaningful. Filter type 0 (none) throughout."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    raw = bytearray()
    for y in range(h):
        raw.append(0)   # no filter
        for x in range(w):
            raw += bytes(pixel_fn(x, y))
    ihdr = chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(bytes(raw)))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + chunk(b"IEND", b"")


def _patterned_png_paeth_filtered(pixel_fn, w=8, h=8):
    """Same as _patterned_png, but actually applies PNG filter type 4
    (Paeth) to every row after the first. This exists specifically to
    regression-test a real bug: the colorfulness heuristic originally
    only correctly unfiltered PNG filter type 2 (Up), silently treating
    Sub/Average/Paeth-filtered rows as if they were already raw pixel
    values. That bug meant a real normal map on real game data wasn't
    detected, because the actual PNG encoder chose a non-Up filter for
    some rows. A fixture using only filter 0 (as _patterned_png does)
    would pass even with that bug still present — it never exercises
    the broken code path at all."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    prev = [0] * (w * 4)
    raw = bytearray()
    for y in range(h):
        row = []
        for x in range(w):
            row.extend(pixel_fn(x, y))
        filtered = bytearray()
        for x in range(len(row)):
            a = row[x - 4] if x >= 4 else 0
            b = prev[x]
            c = prev[x - 4] if x >= 4 else 0
            filtered.append((row[x] - paeth(a, b, c)) & 0xFF)
        raw.append(4)                # filter type 4: Paeth
        raw.extend(filtered)
        prev = row
    ihdr = chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(bytes(raw)))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + chunk(b"IEND", b"")


def _submesh(refs):
    return (VERTS, UVS, JOINTS, WEIGHTS, TRIS, True, refs)


def _parse_glb(path):
    data = Path(path).read_bytes()
    magic, _, _ = struct.unpack_from("<3I", data, 0)
    assert magic == 0x46546C67, "bad glb magic"
    off = 12
    jlen, _ = struct.unpack_from("<2I", data, off)
    gltf = json.loads(data[off + 8:off + 8 + jlen])
    off += 8 + jlen
    blen, _ = struct.unpack_from("<2I", data, off)
    bin_bytes = data[off + 8:off + 8 + blen]
    return gltf, bin_bytes


class TestTextureEmbedding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_textured_and_untextured_submesh_coexist(self):
        png = self.tmp_path / "tex.png"
        png.write_bytes(_tiny_png())
        tex_hash = 0xDEADBEEF
        subs = [_submesh([tex_hash]), _submesh([])]   # one textured, one not
        out = self.tmp_path / "out.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out),
                         texture_index={tex_hash: str(png)})
        gltf, bin_bytes = _parse_glb(out)

        self.assertEqual(len(gltf["materials"]), 2)
        self.assertIn("baseColorTexture",
                      gltf["materials"][0]["pbrMetallicRoughness"])
        self.assertIn("baseColorFactor",
                      gltf["materials"][1]["pbrMetallicRoughness"])
        self.assertEqual(len(gltf.get("images", [])), 1)

        # embedded bytes must be byte-identical to the source PNG
        bv = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
        embedded = bin_bytes[bv["byteOffset"]:bv["byteOffset"] + bv["byteLength"]]
        self.assertEqual(embedded, png.read_bytes())

        # skinning attributes still present alongside the new texture data
        # — the whole point is these two features coexist, neither
        # displaced the other
        attrs = set(gltf["meshes"][0]["primitives"][0]["attributes"])
        self.assertEqual(attrs, {"POSITION", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"})
        self.assertIn("skins", gltf)
        self.assertEqual(len(gltf["skins"][0]["joints"]), len(BONES))

    def test_shared_texture_embeds_once(self):
        png = self.tmp_path / "shared.png"
        png.write_bytes(_tiny_png((0, 255, 0)))
        tex_hash = 0x12345678
        subs = [_submesh([tex_hash])] * 3   # three submeshes, one texture
        out = self.tmp_path / "dedup.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out),
                         texture_index={tex_hash: str(png)})
        gltf, _ = _parse_glb(out)

        self.assertEqual(len(gltf["images"]), 1)     # embedded once, not 3x
        self.assertEqual(len(gltf["materials"]), 3)  # one material per submesh
        self.assertTrue(all(
            m["pbrMetallicRoughness"]["baseColorTexture"]["index"] == 0
            for m in gltf["materials"]))

    def test_no_texture_index_falls_back_cleanly(self):
        """build_glb with no texture_index (the pre-texture-support call
        shape) must still produce a valid, untextured GLB — the
        backward-compatibility case."""
        subs = [_submesh([0xAAAA])]   # has a ref, but no index to resolve it
        out = self.tmp_path / "no_tex.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out))   # no texture_index
        gltf, _ = _parse_glb(out)
        self.assertIn("baseColorFactor",
                      gltf["materials"][0]["pbrMetallicRoughness"])
        self.assertNotIn("images", gltf)

    def test_prefers_color_texture_over_greyscale_candidate(self):
        """The actual incident this exists for: a submesh referencing more
        than one texture (a real diffuse plus a greyscale lightmap/AO
        mask), where blindly taking the first resolved candidate picked
        the lightmap and produced a GLB that looked completely untextured
        even though a real image was correctly bound. Order must not
        matter — greyscale-first should still resolve to the color one."""
        lightmap = self.tmp_path / "lightmap.png"
        lightmap.write_bytes(_patterned_png(
            lambda x, y: (100 + x * 5, 100 + x * 5, 100 + x * 5, 255)))
        diffuse = self.tmp_path / "diffuse.png"
        diffuse.write_bytes(_patterned_png(
            lambda x, y: (200, 60, 30, 255) if (x + y) % 2 else (40, 90, 180, 255)))

        lightmap_hash, diffuse_hash = 0xAAAA, 0xBBBB
        # greyscale ref listed FIRST — this is what actually broke before
        subs = [_submesh([lightmap_hash, diffuse_hash])]
        out = self.tmp_path / "picks_diffuse.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out), texture_index={
            lightmap_hash: str(lightmap), diffuse_hash: str(diffuse)})
        gltf, _ = _parse_glb(out)
        self.assertEqual(gltf["images"][0]["name"], "diffuse")

    def test_single_candidate_unaffected_by_scoring(self):
        """Only one resolvable candidate: no scoring needed, must still
        just use it, same as before this fix existed."""
        png = self.tmp_path / "only.png"
        png.write_bytes(_tiny_png())
        h = 0xCCCC
        subs = [_submesh([h])]
        out = self.tmp_path / "single.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out),
                         texture_index={h: str(png)})
        gltf, _ = _parse_glb(out)
        self.assertEqual(gltf["images"][0]["name"], "only")

    def test_normal_map_signature_disqualified(self):
        """A second real incident: a normal map (blue-dominant, R/G
        centered near neutral 128) has genuine per-channel divergence, so
        a naive 'is this greyscale' check alone picks it as if it were a
        real color texture. Uses the Paeth-filtered fixture so this
        exercises real multi-filter-type PNG decoding, not just filter 0.

        Note: this specific fixture's diffuse candidate happens to win
        the race on raw color-score alone even without the disqualify
        check firing, so it doesn't cleanly isolate that one check in
        isolation — it documents correct end-to-end behavior on the
        fixed code, not a minimal bug-vs-fix discriminator. The actual
        proof the disqualify check works is direct: real game data
        (d2174e82, a genuine normal map) scored -1000 and was excluded
        after this fix, verified by hand against the uploaded texture
        set before this test was written."""
        normal_map = self.tmp_path / "normal.png"
        normal_map.write_bytes(_patterned_png_paeth_filtered(
            lambda x, y: (120 + (x % 3), 130 - (x % 3), 250, 255)))
        diffuse = self.tmp_path / "diffuse.png"
        diffuse.write_bytes(_patterned_png_paeth_filtered(
            lambda x, y: (180, 70, 40, 255) if (x + y) % 2 else (60, 100, 150, 255)))

        normal_hash, diffuse_hash = 0x1111, 0x2222
        subs = [_submesh([normal_hash, diffuse_hash])]
        out = self.tmp_path / "skips_normal_map.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out), texture_index={
            normal_hash: str(normal_map), diffuse_hash: str(diffuse)})
        gltf, _ = _parse_glb(out)
        self.assertEqual(gltf["images"][0]["name"], "diffuse")

    def test_force_hash_overrides_auto_selection(self):
        """--texture / force_hash must win even over a candidate that
        would otherwise score higher — this is the deliberate escape
        hatch for cases the heuristic can't resolve on its own (a highly
        saturated but wrong texture can legitimately outscore the
        correct, more muted one; that's a job for a human, not a
        scorer)."""
        wrong_but_flashy = self.tmp_path / "flashy.png"
        wrong_but_flashy.write_bytes(_patterned_png(
            lambda x, y: (250, 10, 5, 255)))   # extremely saturated, would win on score
        correct = self.tmp_path / "correct.png"
        correct.write_bytes(_patterned_png(
            lambda x, y: (140, 100, 70, 255) if (x + y) % 2 else (120, 90, 65, 255)))

        flashy_hash, correct_hash = 0x3333, 0x4444
        subs = [_submesh([flashy_hash, correct_hash])]
        out = self.tmp_path / "forced.glb"
        lu_rig.build_glb(BONES, subs, MAPPING, str(out),
                         texture_index={flashy_hash: str(wrong_but_flashy),
                                       correct_hash: str(correct)},
                         force_hash=correct_hash)
        gltf, _ = _parse_glb(out)
        self.assertEqual(gltf["images"][0]["name"], "correct")


if __name__ == "__main__":
    unittest.main()
