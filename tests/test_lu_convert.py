#!/usr/bin/env python3
"""tests/test_lu_convert.py - regression coverage for lu_convert.py.

test_is_texture_chunk_recognizes_both_games exists because of a real bug
found during live testing, not a hypothetical one: is_texture_chunk only
ever checked for PiP's texture type tag (0x34200007). NB1's texture type
(0x14200007) was never recognized at all, meaning every NB1 texture chunk
silently fell through as "not a texture" in main()'s categorization loop,
in lu_rig.py's texture-embedding scan, and in pip_dump.py's dump — despite
this toolkit's own docs and docstrings claiming NB1 texture conversion
worked. It went undetected because nobody had actually run NB1 texture
conversion against real game data until this session's rig-export work
surfaced it as "textures extracted fine, but the rig came out untextured
with no error at all."
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import lu_convert


class TestIsTextureChunk(unittest.TestCase):
    def test_recognizes_both_games(self):
        nb1 = b"\x14\x20\x00\x07" + b"\x00" * 60     # NB1 texture (14200007)
        pip = b"\x34\x20\x00\x07" + b"\x00" * 60     # PiP texture (34200007)
        self.assertTrue(lu_convert.is_texture_chunk(nb1),
                        "NB1 texture type tag not recognized")
        self.assertTrue(lu_convert.is_texture_chunk(pip),
                        "PiP texture type tag not recognized")

    def test_rejects_non_texture_types(self):
        mesh_like = b"\x04\x00\x00\x07" + b"\x00" * 60
        skeleton_like = b"\x04\x00\x00\x01" + b"\x00" * 60
        self.assertFalse(lu_convert.is_texture_chunk(mesh_like))
        self.assertFalse(lu_convert.is_texture_chunk(skeleton_like))

    def test_rejects_too_short(self):
        # a real texture header needs >= 0x40 bytes; a short buffer that
        # happens to start with the right tag must still be rejected
        short = b"\x14\x20\x00\x07" + b"\x00" * 10
        self.assertFalse(lu_convert.is_texture_chunk(short))


def _build_chunk_with_buffer(total=0x3000, quad_off=0x20,
                             vo=0x1000, vs=0x40, io_=0x2000, isz=0x30,
                             stride=0x20, count=8, prim=6, declp=0x100):
    """Synthesize a minimal chunk holding one valid vertex/index buffer pair
    plus the submesh trailer that _read_trailer/_find_buffer_quads expect.
    Everything else is zero — enough for detection, not for full conversion."""
    d = bytearray(total)
    struct.pack_into(">4I", d, quad_off, vo, vs, io_, isz)
    trailer = (io_ + isz + 3) & ~3
    # {stride, count, prim, zero, decl_ptr, n_decl_elements}
    struct.pack_into(">6I", d, trailer, stride, count, prim, 0, declp, 0)
    return bytes(d)


class TestIsMeshChunk(unittest.TestCase):
    def test_standalone_header_recognized(self):
        # 00000020 header + 34 20 00 xx model-class tag at +0x0c (fast path).
        body = (b"\x00\x00\x00\x20" + b"\x00" * 8
                + b"\x34\x20\x00\x04" + b"\x00" * (0x1000))
        self.assertTrue(lu_convert.is_mesh_chunk(body),
                        "standalone mesh header not recognized")

    def test_packed_area_header_recognized(self):
        # The real packed-area chunk (confirmed on area*vegetation.lu) is
        # resource type 0x04000009 and starts with that class tag, not the
        # standalone-model header. It must be recognized by the fast path.
        chunk = b"\x04\x00\x00\x09" + b"\x00" * 0x2000
        self.assertNotEqual(chunk[:4], b"\x00\x00\x00\x20")
        self.assertTrue(lu_convert.is_mesh_chunk(chunk),
                        "packed area chunk (04000009 header) not recognized")

    def test_headerless_geometry_recognized(self):
        # Even without a known class tag, a chunk carrying a valid vertex/
        # index buffer pair + trailer is geometry we can extract, so the
        # content-sniff fallback must catch it (detection == conversion).
        chunk = _build_chunk_with_buffer()
        self.assertNotEqual(chunk[:4], b"\x00\x00\x00\x20")
        self.assertNotEqual(chunk[:4], b"\x04\x00\x00\x09")
        self.assertTrue(lu_convert.is_mesh_chunk(chunk),
                        "headerless buffer+trailer geometry not recognized")

    def test_rejects_headerless_garbage(self):
        # Large, but no valid buffer quad / trailer anywhere: not a mesh.
        self.assertFalse(lu_convert.is_mesh_chunk(b"\x11" * 0x4000))

    def test_rejects_too_short(self):
        # Below the 0x1000 floor even a well-formed-looking quad is rejected.
        self.assertFalse(lu_convert.is_mesh_chunk(b"\x00" * 0x40))

    def test_texture_not_seen_as_mesh(self):
        # A texture chunk body must not trip the mesh sniffer.
        tex = b"\x14\x20\x00\x07" + b"\x00" * 0x2000
        self.assertFalse(lu_convert.is_mesh_chunk(tex))


if __name__ == "__main__":
    unittest.main()
