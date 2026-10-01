#!/usr/bin/env python3
"""HASH("name") in edited source must become exactly the game's hash for that
name, and nothing else in the source may change."""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nb_names


class ExpandHashCalls(unittest.TestCase):
    def test_known_game_hash(self):
        # surfacetype registers the emitter CSmoke01 as 0x656d019f
        out, found = nb_names.expand_hash_calls('x:AddEmitterToList(HASH("CSmoke01"))')
        self.assertEqual(out, "x:AddEmitterToList(0x656d019f)")
        self.assertEqual(found, [("CSmoke01", 0x656D019F)])

    def test_case_insensitive_like_the_game(self):
        a, _ = nb_names.expand_hash_calls('HASH("CSmoke01")')
        b, _ = nb_names.expand_hash_calls('HASH("csmoke01")')
        self.assertEqual(a, b)

    def test_quotes_spacing_and_several(self):
        out, found = nb_names.expand_hash_calls("f(HASH( 'a' ), HASH(\"b\"))")
        self.assertEqual(out, f"f({nb_names.crc('a'):#010x}, {nb_names.crc('b'):#010x})")
        self.assertEqual([n for n, _ in found], ["a", "b"])

    def test_small_hash_keeps_eight_hex_digits(self):
        # NPCBloodBearTrapRobot hashes below 2^24; it must still be written as
        # a hex integer so it compiles to the hash's integer type
        out, _ = nb_names.expand_hash_calls('HASH("NPCBloodBearTrapRobot")')
        self.assertEqual(out, "0x001cb9cf")

    def test_decimal_format_for_pip(self):
        out, _ = nb_names.expand_hash_calls('HASH("Sting")', fmt="{:d}")
        self.assertEqual(out, str(nb_names.crc("Sting")))

    def test_annotations_and_other_code_untouched(self):
        src = ('e = engine.EffectDefinition_Create(--[[HASH:"camerabird_FX"]]0x6f3d030f)\n'
               'local HASHED = 1\nMyHASH("x")\n')
        out, found = nb_names.expand_hash_calls(src)
        self.assertEqual(out, src)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
