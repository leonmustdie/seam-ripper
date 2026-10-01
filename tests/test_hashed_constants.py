#!/usr/bin/env python3
"""Tests for NB1's 0xFE constant handling.

The type holds a full 64-bit value and is used for two different things:
interned string ids (CRC32 of the lowercase string) and plain integers
(counts, priorities, score thresholds). Both must survive a decompile ->
recompile round trip exactly, or `ship` refuses to let you edit the proto
that contains one.
"""
import struct
import sys
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import lua_recompile
import nb_names


def std_chunk(consts, nested=()):
    """Minimal standard Lua 5.1 bytecode with the given top-level constants.

    consts: list of (type_byte, payload_bytes)
    """
    def proto(cs, kids, top):
        b = bytearray()
        b += struct.pack("<I", 0)          # source name (empty)
        b += struct.pack("<II", 0, 0)      # linedefined, lastlinedefined
        b += bytes([0])                    # nups
        b += bytes([0, 0, 2])              # numparams, is_vararg, maxstack
        b += struct.pack("<I", 0)          # no code
        b += struct.pack("<I", len(cs))
        for t, payload in cs:
            b += bytes([t]) + payload
        b += struct.pack("<I", len(kids))
        for k in kids:
            b += proto(k, (), False)
        b += struct.pack("<I", 0)          # line info
        b += struct.pack("<I", 0)          # locals
        b += struct.pack("<I", 0)          # upvalues
        return bytes(b)

    hdr = bytes([0x1b, 0x4c, 0x75, 0x61, 0x51, 0x00, 0x01, 4, 4, 4, 8, 0])
    return hdr + proto(consts, nested, True)


def s_const(text):
    b = text.encode("latin-1") + b"\x00"
    return (4, struct.pack("<I", len(b)) + b)


def nb1_chunk(consts, nested=()):
    """A chunk in the GAME's form: 13-byte header, and the top-level proto
    omits the nups byte. This is what ref_hash_set reads."""
    def proto(cs, kids, top):
        b = bytearray()
        b += struct.pack("<I", 0)          # source name (empty)
        b += struct.pack("<II", 0, 0)      # linedefined, lastlinedefined
        if not top:
            b += bytes([0])                # nups - absent at top level
        b += bytes([0, 0, 2])              # numparams, is_vararg, maxstack
        b += struct.pack("<I", 0)          # no code
        b += struct.pack("<I", len(cs))
        for t, payload in cs:
            b += bytes([t]) + payload
        b += struct.pack("<I", len(kids))
        for k in kids:
            b += proto(k, (), False)
        b += struct.pack("<I", 0)          # line info
        b += struct.pack("<I", 0)          # locals
        b += struct.pack("<I", 0)          # upvalues
        return bytes(b)

    hdr = bytes([0x1b, 0x4c, 0x75, 0x61, 0x51, 0x00, 0x01, 4, 4, 4, 8, 8, 0])
    return hdr + proto(consts, nested, True)


class SixtyFourBitValues(unittest.TestCase):
    """Retail uses the high word: 0xFFFFFFFFFFFFFFFF is -1, and it appears in
    real scripts (pictureinpicture's SetCameraPosition). Masking the
    placeholder to 32 bits turned it into 0x00000000FFFFFFFF, which was
    enough to stop that chunk's top-level body round-tripping at all."""

    def _roundtrip(self, text):
        std = std_chunk([s_const(text)])
        out = lua_recompile.convert(std, want_hash=True)
        i = out.find(bytes([0xFE]))
        self.assertGreater(i, 0, "constant was not re-encoded as 0xFE")
        return struct.unpack_from("<Q", out, i + 1)[0]

    def test_full_64_bit_preserved(self):
        self.assertEqual(self._roundtrip("__hash_0xffffffffffffffff"),
                         0xFFFFFFFFFFFFFFFF)

    def test_high_word_preserved(self):
        self.assertEqual(self._roundtrip("__hash_0x00000001ffffffff"),
                         0x00000001FFFFFFFF)

    def test_short_form_still_works(self):
        """Every real string hash is 32-bit, so the 8-digit spelling has to
        keep working - existing .lua files are full of it."""
        self.assertEqual(self._roundtrip("__hash_0xb902022c"), 0xB902022C)

    def test_small_value(self):
        self.assertEqual(self._roundtrip("__hash_0x00000000"), 0)


class RefHashSetRecursion(unittest.TestCase):
    """It used to walk only the top-level proto, so a name hashed inside a
    function body was missing from the set and could not be re-encoded."""

    def test_finds_nested_hashes(self):
        top = [(0xFE, struct.pack("<Q", 0x11111111))]
        kid = [(0xFE, struct.pack("<Q", 0x22222222))]
        hs = lua_recompile.ref_hash_set(nb1_chunk(top, nested=(kid,)))
        self.assertIn(0x11111111, hs)
        self.assertIn(0x22222222, hs, "nested proto's hash was not collected")

    def test_keeps_the_full_64_bit_value_low_word(self):
        hs = lua_recompile.ref_hash_set(
            nb1_chunk([(0xFE, struct.pack("<Q", 0xFFFFFFFFFFFFFFFF))]))
        self.assertIn(0xFFFFFFFF, hs)

    def test_survives_a_malformed_chunk(self):
        self.assertEqual(lua_recompile.ref_hash_set(b"not a chunk"), set())


class HashFloorGuard(unittest.TestCase):
    """crc32(b"") is 0, and 0 is an extremely common 0xFE *integer*. Without
    a floor, every empty string constant in a chunk gets re-encoded as the
    'hash' 0x00000000. That measurably worsened npc.lua's round trip."""

    def _encodes_as_hash(self, text, orig_hashes):
        std = std_chunk([s_const(text)])
        out = lua_recompile.convert(std, want_hash=True,
                                    orig_hashes=orig_hashes)
        return bytes([0xFE]) in out

    def test_empty_string_not_treated_as_hash_zero(self):
        self.assertEqual(zlib.crc32(b""), 0)
        self.assertFalse(self._encodes_as_hash("", {0}))

    def test_value_below_the_floor_not_treated_as_hash(self):
        """Find a string whose CRC32 lands below the floor and confirm it is
        left alone even when that value is in the chunk's 0xFE set."""
        for n in range(200000):
            t = f"s{n}"
            c = zlib.crc32(t.encode()) & 0xFFFFFFFF
            if c < lua_recompile.HASH_FLOOR:
                self.assertFalse(self._encodes_as_hash(t, {c}),
                                 f"{t!r} (crc {c}) was wrongly re-encoded")
                return
        self.skipTest("no sub-floor CRC found in the sample")

    def test_real_hash_still_re_encoded(self):
        text = "pipevents_barricading"
        c = zlib.crc32(text.encode()) & 0xFFFFFFFF
        self.assertGreaterEqual(c, lua_recompile.HASH_FLOOR)
        self.assertTrue(self._encodes_as_hash(text, {c}))

    def test_string_not_in_the_set_stays_a_string(self):
        self.assertFalse(self._encodes_as_hash("pipevents_barricading", set()))


class NameDictionary(unittest.TestCase):
    def test_crc_matches_engine_convention(self):
        """Lowercased, then CRC32 - verified against real values."""
        self.assertEqual(nb_names.crc("pipevents_barricading"), 0xB902022C)
        self.assertEqual(nb_names.crc("CallCops"), 0xB958E78D)
        self.assertEqual(nb_names.crc("ReactionCam"), 0x1D485F29)

    def test_case_insensitive(self):
        self.assertEqual(nb_names.crc("CallCops"), nb_names.crc("callcops"))

    def test_classify_integers_and_hashes(self):
        for v in (0, 1, 25, 100, 10001, 24999, 1000000):
            self.assertEqual(nb_names.classify(v), "int", f"{v} misclassified")
        for v in (0xB902022C, 0xB958E78D, 0x1D485F29):
            self.assertEqual(nb_names.classify(v), "hash",
                             f"{v:#x} misclassified")

    def test_load_missing_dictionary_is_not_an_error(self):
        self.assertEqual(nb_names.load("does_not_exist.json"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
