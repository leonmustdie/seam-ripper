#!/usr/bin/env python3
"""tests/test_lua_batchedit.py - regression coverage for the select-and-mark
batch editor. Fixture is hand-written, synthetic Lua, not decompiled game
script.

test_target_slots_implicitly_anchor_to_example_value exists specifically
because of a real surprise found during this project's own use of the
engine: marking a slot TARGET does not by itself scope matching, an
anchor-only value (like FEARTYPE_PLAYER) can be shared by unrelated calls
that happen to differ in the values you actually want to change. The first
attempt at reproducing a hand-built mod through this engine matched 42 calls
instead of the intended 26, until target slots were made to implicitly gate
on their example value too. This test locks that behavior in.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lua_callsplit as cs
import lua_batchedit as be

FIXTURE = """
function Init(self)
  self:AddFear(FEAR_A, PLAYER, 200, 150, 100, 50, 25, false)
  self:AddFear(FEAR_B, PLAYER, 200, 150, 100, 50, 25, false)
  self:AddFear(FEAR_C, PLAYER, 400, 300, 200, 100, 50, false)
  self:AddFear(FEAR_D, ENEMY, 200, 150, 100, 50, 25, false)
  self:AddFear(FEAR_E, PLAYER, 999, 150, 100, 50, 25, false)
end
"""


def _example_call(src):
    calls = cs.find_calls(src, "AddFear")
    return next(c for c in calls if "FEAR_A" in src[c.call_start:c.args_end])


def _mark(pattern, ignore=(), anchor=(), target_scale=(), factor="10"):
    for i in ignore:
        pattern.slots[i].tag = be.Tag.IGNORE
    for i in target_scale:
        pattern.slots[i].tag = be.Tag.TARGET
        pattern.slots[i].op = be.Op.SCALE
        pattern.slots[i].param = factor
    return pattern


class TestMatching(unittest.TestCase):
    def test_target_slots_implicitly_anchor_to_example_value(self):
        """FEAR_A and FEAR_B share the exact tuple; FEAR_C shares the
        FEARTYPE_PLAYER anchor but has a different tuple; FEAR_D has a
        different anchor entirely; FEAR_E differs in one target slot only.
        Only A and B should match with default (implicit) target gating."""
        pat = be.build_pattern(FIXTURE, _example_call(FIXTURE))
        _mark(pat, ignore=(0, 7), target_scale=(2, 3, 4, 5, 6))
        matches = be.find_matches(FIXTURE, pat)
        names = [FIXTURE[m.call_start:m.args_end] for m in matches]
        self.assertEqual(len(matches), 2)
        self.assertTrue(all("FEAR_A" in n or "FEAR_B" in n for n in names))

    def test_anchor_slot_still_gates_normally(self):
        """Sanity: FEAR_D's different PLAYER/ENEMY anchor excludes it even
        if target-value gating were somehow disabled."""
        pat = be.build_pattern(FIXTURE, _example_call(FIXTURE))
        _mark(pat, ignore=(0, 7), target_scale=(2, 3, 4, 5, 6))
        matches = be.find_matches(FIXTURE, pat)
        names = [FIXTURE[m.call_start:m.args_end] for m in matches]
        self.assertFalse(any("FEAR_D" in n for n in names))

    def test_explicit_match_value_none_widens_match(self):
        """Overriding one target slot's match_value to None makes it match
        regardless of current value, picking up FEAR_E (which differs only
        in that one slot)."""
        pat = be.build_pattern(FIXTURE, _example_call(FIXTURE))
        _mark(pat, ignore=(0, 7), target_scale=(2, 3, 4, 5, 6))
        pat.slots[2].match_value = None   # stop gating on this slot's value
        matches = be.find_matches(FIXTURE, pat)
        names = [FIXTURE[m.call_start:m.args_end] for m in matches]
        self.assertEqual(len(matches), 3)   # A, B, E
        self.assertTrue(any("FEAR_E" in n for n in names))


class TestTransforms(unittest.TestCase):
    def setUp(self):
        self.pat = be.build_pattern(FIXTURE, _example_call(FIXTURE))
        self.pat.slots[0].tag = be.Tag.IGNORE
        self.pat.slots[7].tag = be.Tag.IGNORE

    def test_scale_transform(self):
        _mark(self.pat, target_scale=(2, 3, 4, 5, 6), factor="10")
        matches = be.find_matches(FIXTURE, self.pat)
        new_src, changes = be.apply(FIXTURE, self.pat, matches)
        self.assertEqual(len(changes), 10)   # 2 matches * 5 target slots
        self.assertIn("2000, 1500, 1000, 500, 250", new_src)
        # FEAR_C/D/E, unmatched, must be byte-for-byte untouched
        self.assertIn("400, 300, 200, 100, 50", new_src)
        self.assertIn("999, 150, 100, 50, 25", new_src)

    def test_set_transform(self):
        for i, v in zip((2, 3, 4, 5, 6), ["1", "2", "3", "4", "5"]):
            self.pat.slots[i].tag = be.Tag.TARGET
            self.pat.slots[i].op = be.Op.SET
            self.pat.slots[i].param = v
        matches = be.find_matches(FIXTURE, self.pat)
        new_src, changes = be.apply(FIXTURE, self.pat, matches)
        self.assertEqual(new_src.count("1, 2, 3, 4, 5"), 2)

    def test_offset_transform(self):
        _mark(self.pat, target_scale=(2,), factor="0")  # placeholder, overwritten below
        self.pat.slots[2].op = be.Op.OFFSET
        self.pat.slots[2].param = "-50"
        for i in (3, 4, 5, 6):
            self.pat.slots[i].tag = be.Tag.TARGET
            self.pat.slots[i].op = be.Op.OFFSET
            self.pat.slots[i].param = "-50"
        matches = be.find_matches(FIXTURE, self.pat)
        new_src, changes = be.apply(FIXTURE, self.pat, matches)
        self.assertIn("150, 100, 50, 0, -25", new_src)

    def test_ignored_and_anchor_slots_never_edited(self):
        _mark(self.pat, target_scale=(2, 3, 4, 5, 6), factor="10")
        matches = be.find_matches(FIXTURE, self.pat)
        new_src, changes = be.apply(FIXTURE, self.pat, matches)
        # FEAR_A / FEAR_B names (slot 0, ignored) and PLAYER (slot 1, anchor)
        # and the trailing bool (slot 7, ignored) must all survive verbatim
        self.assertIn("FEAR_A, PLAYER,", new_src)
        self.assertIn("FEAR_B, PLAYER,", new_src)
        self.assertEqual(new_src.count(", false)"), 5)  # all 5 calls keep it

    def test_no_matches_yields_no_changes(self):
        pat = be.build_pattern(FIXTURE, _example_call(FIXTURE))
        pat.slots[0].tag = be.Tag.ANCHOR
        pat.slots[0].anchor_value = "FEAR_NONEXISTENT"
        matches = be.find_matches(FIXTURE, pat)
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
