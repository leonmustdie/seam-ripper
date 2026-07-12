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


if __name__ == "__main__":
    unittest.main()
