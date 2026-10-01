#!/usr/bin/env python3
"""Tests for sr_lookup.py, the name <-> hash lookup."""
import json
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import sr_lookup

NAMES = {zlib.crc32(b"detectthreat"): "DetectThreat",
         zlib.crc32(b"costume_hat_partyhat"): "costume_hat_partyhat",
         zlib.crc32(b"costume_hat_tophat"): "costume_hat_tophat",
         zlib.crc32(b"partyhat"): "PartyHat"}
TEXT = {zlib.crc32(b"costume_hat_partyhat"): ("Party hat", "NB1")}
TIERS = {zlib.crc32(b"detectthreat"): "found"}


class NameHash(unittest.TestCase):
    def test_crc32_of_lowercase(self):
        self.assertEqual(sr_lookup.name_hash("DetectThreat"), 0x4342E44F)
        self.assertEqual(sr_lookup.name_hash("detectthreat"), 0x4342E44F)

    def test_signed(self):
        self.assertEqual(sr_lookup.signed(0xFFFFFFFF), -1)
        self.assertEqual(sr_lookup.signed(0x7FFFFFFF), 0x7FFFFFFF)

    def test_formats(self):
        f = sr_lookup.formats(0x4342E44F)
        self.assertEqual(f["hex"], "0x4342e44f")
        self.assertEqual(f["pip"], "1128457295")


class ParseHash(unittest.TestCase):
    def values(self, text):
        return [v for v, _ in sr_lookup.parse_hash(text)]

    def test_0x_hex(self):
        self.assertEqual(sr_lookup.parse_hash("0x4342E44F"),
                         [(0x4342E44F, "hex")])

    def test_bare_hex_with_letters(self):
        self.assertEqual(self.values("4342e44f"), [0x4342E44F])

    def test_digits_only_gives_both_readings(self):
        self.assertEqual(sr_lookup.parse_hash("12345678"),
                         [(12345678, "decimal"), (0x12345678, "hex")])

    def test_long_decimal_is_decimal_only(self):
        self.assertEqual(self.values("1128457295"), [0x4342E44F])

    def test_negative_decimal(self):
        self.assertEqual(sr_lookup.parse_hash("-1"),
                         [(0xFFFFFFFF, "signed decimal")])
        self.assertEqual(self.values(str(sr_lookup.signed(0xC1682B69))),
                         [0xC1682B69])

    def test_trailing_point_zero_and_quotes(self):
        self.assertEqual(self.values("1128457295.0"), [0x4342E44F])
        self.assertEqual(self.values('"0x4342e44f"'), [0x4342E44F])

    def test_rejects(self):
        for t in ("", "zz", "0x", "0x1ffffffff", "99999999999", "-3000000000",
                  "12.5"):
            self.assertEqual(sr_lookup.parse_hash(t), [], t)


class Lookups(unittest.TestCase):
    def test_describe_known(self):
        h = zlib.crc32(b"costume_hat_partyhat")
        d = sr_lookup.describe(h, NAMES, TEXT, {})
        self.assertEqual(d["names"], ["costume_hat_partyhat"])
        self.assertEqual(d["text"], "Party hat")
        self.assertEqual(d["text_game"], "NB1")
        self.assertEqual(d["hex"], f"0x{h:08x}")

    def test_describe_unknown(self):
        d = sr_lookup.describe(5, NAMES, TEXT, TIERS)
        self.assertEqual(d["names"], [])
        self.assertIsNone(d["text"])
        self.assertIsNone(d["tier"])

    def test_lookup_hash_from_text(self):
        got = sr_lookup.lookup_hash("0x4342e44f", NAMES, TEXT, TIERS)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["names"], ["DetectThreat"])
        self.assertEqual(got[0]["tier"], "found")
        self.assertEqual(got[0]["how"], "hex")

    def test_lookup_name(self):
        d = sr_lookup.lookup_name("detectTHREAT", NAMES, TEXT, TIERS)
        self.assertEqual(d["hash"], 0x4342E44F)
        self.assertTrue(d["known"])
        self.assertFalse(sr_lookup.lookup_name("nope_x", NAMES, {}, {})
                         ["known"])

    def test_search_substring_and_prefix(self):
        sub = sr_lookup.search_names("PARTYHAT", names=NAMES)
        self.assertEqual([n for n, _ in sub],
                         ["costume_hat_partyhat", "PartyHat"])
        pre = sr_lookup.search_names("costume_", prefix=True, names=NAMES)
        self.assertEqual([n for n, _ in pre],
                         ["costume_hat_partyhat", "costume_hat_tophat"])
        self.assertEqual(len(sr_lookup.search_names("hat", limit=1,
                                                    names=NAMES)), 1)
        for n, h in sub:
            self.assertEqual(h, zlib.crc32(n.lower().encode()))


class Any(unittest.TestCase):
    def ask(self, text):
        return sr_lookup.lookup(text, NAMES, TEXT, TIERS)

    def test_name_gives_its_hash(self):
        r = self.ask(" DetectThreat ")
        self.assertEqual(r["kind"], "name")
        self.assertEqual(r["results"][0]["hex"], "0x4342e44f")
        self.assertTrue(r["results"][0]["known"])

    def test_hash_gives_its_name(self):
        for t in ("0x4342E44F", "1128457295", '"0x4342e44f"'):
            r = self.ask(t)
            self.assertEqual(r["kind"], "hash", t)
            self.assertEqual(r["results"][0]["names"], ["DetectThreat"], t)

    def test_negative_decimal(self):
        r = self.ask("-1")
        self.assertEqual(r["results"][0]["hash"], 0xFFFFFFFF)

    def test_unknown_hash_is_still_an_answer(self):
        r = self.ask("0x00000001")
        self.assertEqual(r["kind"], "hash")
        self.assertEqual(r["results"][0]["names"], [])

    def test_unknown_name_is_not_in_the_dictionary(self):
        r = self.ask("brand_new_name")
        self.assertEqual(r["kind"], "name")
        self.assertFalse(r["results"][0]["known"])
        self.assertEqual(r["results"][0]["hash"], sr_lookup.name_hash("brand_new_name"))

    def test_bad_numbers(self):
        for t in ("0xzz".replace("zz", "1ffffffff"), "99999999999", "0x"):
            r = self.ask(t)
            self.assertEqual((r["kind"], r["results"]), ("bad", []), t)
            self.assertTrue(r["message"])

    def test_empty(self):
        self.assertEqual(self.ask("  ")["kind"], "empty")

    def test_eight_hex_digits_is_a_name_with_a_hash_reading(self):
        r = self.ask("deadbeef")
        self.assertEqual(r["kind"], "name")
        self.assertEqual(r["results"][0]["name"], "deadbeef")
        self.assertEqual(r["results"][1]["hash"], 0xDEADBEEF)


class RealDictionary(unittest.TestCase):
    def test_every_entry_hashes_to_its_key(self):
        names = sr_lookup.load_names()
        if not names:
            self.skipTest("no nb_names.json")
        bad = [(h, n) for h, n in names.items()
               if sr_lookup.name_hash(n) != h]
        self.assertEqual(bad[:5], [])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        r = subprocess.run([sys.executable, str(TOOLS / "sr_lookup.py"),
                            *args], capture_output=True, text=True)
        return r

    def test_name_json(self):
        r = self.run_cli("name", "DetectThreat", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["hex"], "0x4342e44f")
        self.assertEqual(d["decimal"], 1128457295)

    def test_hash_json_both_readings(self):
        r = self.run_cli("hash", "12345678", "--json")
        self.assertEqual([d["how"] for d in json.loads(r.stdout)],
                         ["decimal", "hex"])

    def test_any_json(self):
        r = self.run_cli("any", "0x4342e44f", "--json")
        d = json.loads(r.stdout)
        self.assertEqual(d["kind"], "hash")
        self.assertEqual(d["results"][0]["hash"], 0x4342E44F)

    def test_hash_not_a_number(self):
        r = self.run_cli("hash", "zz")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a number", r.stderr)


if __name__ == "__main__":
    unittest.main()
