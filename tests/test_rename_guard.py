#!/usr/bin/env python3
"""Tests for the accidental-global-rename guard.

Renaming a local is free: `luac -s` strips local names, so the bytecode is
unchanged. Verified on real content - renaming every l_<a>_<b> token left 31
of 34 scripts in global.lu byte-identical.

The 3 that changed were not locals. luadec prints some globals as bare
l_<a>_<b> tokens too, and a global is resolved BY NAME at runtime, so its
name is a string constant in the chunk. Renaming one repoints it at a
different variable. The signature is exact: instructions byte-identical,
only a string constant moved.

NOTE on coverage: on the current corpus all three real cases sit in protos
that are already DIVERGENT, so ship's older gate refuses them first and this
guard never fires. It exists for when the decompiler improves and those
protos become faithful - at which point such an edit WOULD otherwise ship
silently. Because no real case can exercise it end to end today, the
detector is tested directly here rather than through ship.
"""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nblua


def proto(code, consts):
    """(code_bytes, consts_tuple) in proto360.decode_logic's shape."""
    return (code, tuple(consts))


def s(text):
    return ("s", text.encode("latin-1") + b"\x00")


CODE_A = b"\x01\x02\x03\x04" * 4
CODE_B = b"\x05\x06\x07\x08" * 4


class DetectsAccidentalRename(unittest.TestCase):
    def test_flags_a_renamed_luadec_token(self):
        base = {"0_6": proto(CODE_A, [s("l_7_3"), s("keep")])}
        edit = {"0_6": proto(CODE_A, [s("readableName25"), s("keep")])}
        got = nblua._renamed_globals(base, edit, {"0_6"})
        self.assertEqual(got, [("0_6", "l_7_3", "readableName25")])

    def test_flags_several(self):
        base = {"0_1": proto(CODE_A, [s("l_2_20"), s("l_2_25")])}
        edit = {"0_1": proto(CODE_A, [s("newA"), s("newB")])}
        got = nblua._renamed_globals(base, edit, {"0_1"})
        self.assertEqual([(p, o) for p, o, _ in got],
                         [("0_1", "l_2_20"), ("0_1", "l_2_25")])


class StaysQuiet(unittest.TestCase):
    def test_identical_protos(self):
        base = {"0_1": proto(CODE_A, [s("l_2_20")])}
        self.assertEqual(nblua._renamed_globals(base, dict(base), {"0_1"}), [])

    def test_real_code_change_is_not_a_rename(self):
        """A genuine logic edit changes the instructions; that is the user
        editing code, not renaming a global."""
        base = {"0_1": proto(CODE_A, [s("l_2_20")])}
        edit = {"0_1": proto(CODE_B, [s("whatever")])}
        self.assertEqual(nblua._renamed_globals(base, edit, {"0_1"}), [])

    def test_ordinary_string_edit_is_not_flagged(self):
        """Changing a message the game displays is a normal edit - the old
        value has to look like a luadec token for this to fire."""
        base = {"0_1": proto(CODE_A, [s("Press A to continue")])}
        edit = {"0_1": proto(CODE_A, [s("Press B to continue")])}
        self.assertEqual(nblua._renamed_globals(base, edit, {"0_1"}), [])

    def test_renaming_a_local_produces_no_constant_change(self):
        """The whole point: a local's name is not in the bytecode, so a local
        rename cannot present as a constant difference."""
        base = {"0_1": proto(CODE_A, [s("unrelated")])}
        edit = {"0_1": proto(CODE_A, [s("unrelated")])}
        self.assertEqual(nblua._renamed_globals(base, edit, {"0_1"}), [])

    def test_unedited_protos_ignored(self):
        base = {"0_1": proto(CODE_A, [s("l_2_20")])}
        edit = {"0_1": proto(CODE_A, [s("renamed")])}
        self.assertEqual(nblua._renamed_globals(base, edit, set()), [])

    def test_constant_count_change_ignored(self):
        """Adding or removing a constant is a structural edit, not a rename."""
        base = {"0_1": proto(CODE_A, [s("l_2_20")])}
        edit = {"0_1": proto(CODE_A, [s("l_2_20"), s("extra")])}
        self.assertEqual(nblua._renamed_globals(base, edit, {"0_1"}), [])

    def test_missing_proto_ignored(self):
        base = {"0_1": proto(CODE_A, [s("l_2_20")])}
        self.assertEqual(nblua._renamed_globals(base, {}, {"0_1"}), [])


class TokenPattern(unittest.TestCase):
    def test_matches_luadec_tokens_only(self):
        for good in ("l_0_0", "l_12_7", "l_123_456"):
            self.assertTrue(nblua.LUADEC_TOKEN.match(good), good)
        for bad in ("l_0", "local", "l_a_b", "myLocal", "l_0_0_extra",
                    "xl_1_2"):
            self.assertFalse(nblua.LUADEC_TOKEN.match(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
