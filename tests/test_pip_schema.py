#!/usr/bin/env python3
"""Tests for the PiP data-table schema warnings."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import pip_schema

PIP = Path(r"C:\Users\slmw0\Fuck\pip_full")
LEVELCOMMON = PIP / "levelcommon.lu"

RETAIL = """
local Costumes =
{
    [0 --[[Default for table]]] = { MenuTxtGrp = "Customization" },
    [1001] =
    {
        [2001] = {Hidden = false, LUName = "Boots", Bonus = {hp=40, st=-25}, costNP=1250, Menu = "Main"},
        [2002] = {Hidden = true,  LUName = "Shorts", Bonus = {hp=400, mr=5}, costNP=2375, Menu = "Main"},
        [2003] = {Hidden = false, LUName = "Hat", Bonus = {hp=1, st=50}, costNP=0, Menu = "Main"},
        [2004] = {Hidden = false, LUName = "Cap", Bonus = {hp=90, st=5}, costNP=500, Menu = "Main"},
    },
}
local function Init()
    local t = { a = 1 }
    AddCostumes(Costumes)
end
"""


def edit(old, new, text=RETAIL):
    assert old in text, old
    return text.replace(old, new, 1)


def kinds(original, edited, schema=None):
    return [w["kind"] for w in pip_schema.check(original, edited, schema)]


class Parsing(unittest.TestCase):
    def test_paths_and_values(self):
        acc = pip_schema.observe(RETAIL)
        hp = acc["fields"]["Costumes/[]/[]/Bonus/hp"]
        self.assertEqual((hp["min"], hp["max"], hp["n"]), (1, 400, 4))
        self.assertEqual(set(acc["tables"]["Costumes/[]/[]/Bonus"]["keys"]),
                         {"hp", "st", "mr"})
        self.assertIn("t", acc["tables"])        # a table inside a function

    def test_value_kinds(self):
        (root, fields), = pip_schema.data_tables(
            'X = { a = -3, b = 2*(1+2), c = "s", d = true, e = nil, '
            'f = FACTION_X, g = function(a, b) local x, y = 1, 2 end, '
            'h = HASH("Foo"), i = f(1), j = [==[long]==], k = 0x10 }')
        got = {f.key: (f.type, f.value) for f in fields}
        import nb_names
        self.assertEqual(got, {
            "a": ("number", -3), "b": ("number", 6), "c": ("string", "s"),
            "d": ("boolean", True), "e": ("nil", None),
            "f": ("name", "FACTION_X"), "g": ("function", None),
            "h": ("number", nb_names.crc("Foo")), "i": ("expr", None),
            "j": ("string", "long"), "k": ("number", 16)})

    def test_roots(self):
        roots = [r for r, _ in pip_schema.data_tables(
            "a.b = {}\nlocal c = {}\ntable.insert(t, {x=1})\n"
            "function f() return {y=2} end\n")]
        self.assertEqual(roots, ["a.b", "c", "table.insert()", "return"])

    def test_comments_and_strings_do_not_confuse(self):
        (root, fields), = pip_schema.data_tables(
            'T = { --[[ { ]] a = "}", -- }\n b = 2 }')
        self.assertEqual([f.key for f in fields], ["a", "b"])


class Check(unittest.TestCase):
    def test_unchanged_is_silent(self):
        self.assertEqual(pip_schema.check(RETAIL, RETAIL), [])

    def test_small_tweaks_are_silent(self):
        for old, new in [("hp=400", "hp=450"), ("hp=40,", "hp=700,"),
                         ("costNP=1250", "costNP=3000"),
                         ("st=50", "st=-40"),
                         ('Menu = "Main"}', 'Menu = "Main" }')]:
            self.assertEqual(kinds(RETAIL, edit(old, new)), [], new)

    def test_known_key_added_elsewhere_is_silent(self):
        e = edit("Bonus = {hp=1, st=50}", "Bonus = {hp=1, st=50, mr=10}")
        self.assertEqual(kinds(RETAIL, e), [])

    def test_new_entry_copying_a_sibling_is_silent(self):
        line = ('        [2004] = {Hidden = false, LUName = "Cap", Bonus = '
                '{hp=90, st=5}, costNP=500, Menu = "Main"},\n')
        e = edit(line, line + line.replace("2004", "2005")
                 .replace('"Cap"', '"Visor"'))
        self.assertEqual(kinds(RETAIL, e), [])

    def test_far_out_of_range(self):
        ws = pip_schema.check(RETAIL, edit("hp=400", "hp=30000"))
        self.assertEqual([w["kind"] for w in ws], ["range"])
        self.assertEqual((ws[0]["key"], ws[0]["value"]), ("hp", 30000))
        self.assertEqual(ws[0]["line"], 8)         # RETAIL starts with a newline
        self.assertIn("1..400", ws[0]["message"])

    def test_threshold_is_twice_the_largest_magnitude(self):
        self.assertEqual(kinds(RETAIL, edit("hp=400", "hp=800")), [])
        self.assertEqual(kinds(RETAIL, edit("hp=400", "hp=801")), ["range"])

    def test_negative_where_retail_never_is(self):
        self.assertEqual(kinds(RETAIL, edit("hp=40,", "hp=-5,")), ["range"])

    def test_new_key(self):
        ws = pip_schema.check(RETAIL, edit("Bonus = {hp=1, st=50}",
                                           "Bonus = {hp=1, st=50, rr=10}"))
        self.assertEqual([(w["kind"], w["key"]) for w in ws],
                         [("new_key", "rr")])
        self.assertIn("hp, mr, st", ws[0]["message"])

    def test_typo_key(self):
        self.assertEqual(kinds(RETAIL, edit("costNP=0", "costNp=0")),
                         ["new_key"])

    def test_type_change(self):
        self.assertEqual(kinds(RETAIL, edit("costNP=500", 'costNP="500"')),
                         ["type"])

    def test_value_outside_small_set(self):
        self.assertEqual(kinds(RETAIL, edit('500, Menu = "Main"',
                                            '500, Menu = "Mian"')), ["value"])

    def test_hash_call_counts_as_a_number(self):
        e = edit('[0 --[[Default for table]]]', '[HASH("Default")]')
        self.assertEqual(kinds(RETAIL, e), [])

    def test_new_table_is_not_judged(self):
        e = RETAIL + "\nlocal Mine = { anything = 1e9 }\n"
        self.assertEqual(kinds(RETAIL, e), [])

    def test_schema_extends_the_original(self):
        schema = {"version": pip_schema.SCHEMA_VERSION,
                  **pip_schema.observe(RETAIL.replace("mr=5", "rr=5"))}
        e = edit("Bonus = {hp=1, st=50}", "Bonus = {hp=1, st=50, rr=10}")
        self.assertEqual(kinds(RETAIL, e, schema), [])


class Cache(unittest.TestCase):
    def test_save_load_roundtrip(self):
        d = Path(tempfile.mkdtemp())
        schema = {"version": pip_schema.SCHEMA_VERSION,
                  **pip_schema.observe(RETAIL)}
        p = pip_schema.save(schema, d / "s.json")
        self.assertEqual(pip_schema.load_schema(path=p)["tables"],
                         schema["tables"])

    def test_missing_cache_without_folder(self):
        d = Path(tempfile.mkdtemp())
        self.assertIsNone(pip_schema.load_schema(path=d / "none.json"))

    def test_stale_version_is_ignored(self):
        d = Path(tempfile.mkdtemp())
        p = pip_schema.save({"version": -1, "tables": {}, "fields": {}},
                            d / "old.json")
        self.assertIsNone(pip_schema.load_schema(path=p))

    def test_default_cache_is_outside_the_repo(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"SEAMRIPPER_CACHE": d}):
            self.assertEqual(pip_schema.default_cache(),
                             Path(d) / "pip_schema.json")
        repo = TOOLS.parent.resolve()
        self.assertNotIn(repo, pip_schema.default_cache().resolve().parents)


@unittest.skipUnless(LEVELCOMMON.exists(), "PiP retail units not present")
class Retail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = pip_schema.build([LEVELCOMMON])
        cls.texts = {}
        for unit, text in pip_schema.pip_sources([LEVELCOMMON]):
            m = re.search(r"^local (AccessoriesAttribute|WeaponsAttributes) =",
                          text, re.M)
            if m:
                cls.texts[m.group(1)] = text

    def test_unchanged_retail_is_silent(self):
        n = 0
        for unit, text in pip_schema.pip_sources([LEVELCOMMON]):
            self.assertEqual(pip_schema.check(text, text, self.schema), [])
            n += 1
        self.assertGreater(n, 50)

    def test_costume_hp(self):
        t = self.texts["AccessoriesAttribute"]
        self.assertIn("hp=400", t)
        self.assertEqual(kinds(t, t.replace("hp=400", "hp=30000", 1),
                               self.schema), ["range"])
        self.assertEqual(kinds(t, t.replace("hp=400", "hp=450", 1),
                               self.schema), [])

    def test_costume_invented_resistance_key(self):
        t = self.texts["AccessoriesAttribute"]
        e = t.replace("Bonus = {st=5,mr=5}", "Bonus = {st=5,mr=5,rr=5}", 1)
        self.assertNotEqual(e, t)
        self.assertEqual(kinds(t, e, self.schema), ["new_key"])

    def test_weapon_damage_tweak(self):
        t = self.texts["WeaponsAttributes"]
        e = t.replace("Bonus = {md=160}", "Bonus = {md=300}", 1)
        self.assertNotEqual(e, t)
        self.assertEqual(kinds(t, e, self.schema), [])


if __name__ == "__main__":
    unittest.main()
