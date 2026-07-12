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


if __name__ == "__main__":
    unittest.main()
