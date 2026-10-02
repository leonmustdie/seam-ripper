#!/usr/bin/env python3
"""Tests for the PiP slot budget and the Lua structure check's positions."""
import io
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import pip_scripts

import game_paths

PIP = game_paths.PIP_DIR
LOADERS = PIP / "levelloaders.lu"


def problems(text):
    return [(p["line"], p["col"], p["kind"])
            for p in pip_scripts.lua_structure_problems(text)]


class StructurePositions(unittest.TestCase):
    def test_valid_code_is_clean(self):
        src = ('t = { a = { 1, 2 }, b = "x(", c = [[ { ]], d = [==[ ]] ]==] }\n'
               "-- ( unbalanced in a comment\n"
               "--[=[ { also ]] still comment ]=]\n"
               "f(t['k'], \"esc \\\" quote\")\n")
        self.assertEqual(problems(src), [])

    def test_extra_closer_position(self):
        self.assertEqual(problems("x = 1\nf(a))\n"), [(2, 5, "extra")])

    def test_unclosed_string_position(self):
        self.assertEqual(problems('a = 1\n  b = "oops\nc = 2\n'),
                         [(2, 7, "string")])

    def test_unclosed_long_comment(self):
        self.assertEqual(problems("a = 1\n--[==[ note ]]\n"),
                         [(2, 1, "long_comment")])

    def test_mismatched_reports_inner_opener(self):
        self.assertEqual(problems("f({a = 1)\n"), [(1, 3, "mismatched")])

    def test_missing_closer_located_by_indentation(self):
        src = ("T = {\n"
               "  a = { x = 1,\n"          # the missing }
               "  b = { y = 2 },\n"
               "}\n")
        (p,) = pip_scripts.lua_structure_problems(src)
        self.assertEqual((p["line"], p["kind"]), (2, "unclosed"))
        self.assertEqual((p["bracket_line"], p["bracket_col"]), (1, 5))

    def test_line_endings_all_count(self):
        for eol in ("\n", "\r\n", "\r"):
            src = eol.join(["a = 1", "b = 2", "f(("]) + eol
            self.assertEqual(problems(src)[0][0], 3, repr(eol))

    def test_bytes_and_str_agree(self):
        src = "x = 'caf\xe9'\nf(\n"
        self.assertEqual(problems(src), problems(src.encode("latin-1")))

    def test_sanity_check_messages_carry_the_line(self):
        (msg,) = pip_scripts.lua_sanity_check("a = 1\nb = {\n")
        self.assertIn("line 2", msg)

    @unittest.skipUnless(PIP.exists(), "PiP retail units not present")
    def test_no_false_positives_on_retail(self):
        from naughty_lu import LuFile
        n = 0
        for name in ("global.lu", "levelcommon.lu", "levelloaders.lu"):
            lu = LuFile(str(PIP / name))
            for r, chunk in pip_scripts._iter_script_chunks(lu):
                src = pip_scripts.parse_script_chunk(chunk)["src"]
                self.assertEqual(pip_scripts.lua_structure_problems(src), [],
                                 f"{name} record {r.index}")
                n += 1
        self.assertGreater(n, 150)


class Squeeze(unittest.TestCase):
    def test_squeeze_matches_squeeze_lua(self):
        src = b"a = 1   \n\n\n\nb  =  2\t\t\n"
        for budget in range(0, len(src) + 2):
            with redirect_stderr(io.StringIO()):
                want = pip_scripts.squeeze_lua(src, budget)
            self.assertEqual(pip_scripts._squeeze(src, budget), want)

    def test_encode_error_names_line(self):
        with self.assertRaises(pip_scripts.SourceEncodingError) as cm:
            pip_scripts.encode_text("a = 1\r\nb = '\u2014'\r\n", b"x\r\n")
        self.assertEqual(cm.exception.line, 2)


@unittest.skipUnless(LOADERS.exists(), "PiP retail units not present")
class BudgetAgreesWithInject(unittest.TestCase):
    """The budget must say exactly what inject will accept or refuse."""

    @classmethod
    def setUpClass(cls):
        cls.slots = pip_scripts.container_slots(LOADERS)
        cls.tmp = Path(tempfile.mkdtemp(prefix="pipbudget_"))

    def inject(self, index, text):
        """-> (accepted, stored source bytes or None)."""
        name = self.slots[index]["path"].split("\\")[-1]
        d = self.tmp / f"r{index}"
        d.mkdir(exist_ok=True)
        ed = d / name
        pip_scripts.write_source(ed, text)
        out = d / "out.lu"
        args = Namespace(orig=str(LOADERS), scripts=[str(ed)], out=str(out),
                         force=False)
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                pip_scripts.cmd_inject(args)
        except SystemExit:
            return False, None
        from naughty_lu import LuFile
        lu = LuFile(str(out))
        return True, pip_scripts.parse_script_chunk(
            bytes(lu.chunk(lu.records[index])))["src"]

    def original(self, index):
        return self.slots[index]["src"].decode("latin-1")

    def check_boundaries(self, index):
        limit = self.slots[index]["limit"]
        # a real edit: the script's last line comment rewritten to a padding
        # comment whose length moves the size one byte at a time
        lines = self.original(index).replace("\r\n", "\n").split("\n")
        j = max(i for i, s in enumerate(lines)
                if s.startswith("--") and not s.startswith("--["))
        head = "\n".join(lines[:j]) + "\n--"
        rest = "\n" + "\n".join(lines[j + 1:])

        def edit(k, tail=""):
            return head + "x" * k + tail + rest

        def measure(text):
            return pip_scripts.budget(LOADERS, index, text)

        # raw boundary: exactly at the limit needs no squeezing
        k = measure(edit(0))["bytes_left"]
        self.assertGreater(k, 0)
        at = measure(edit(k))
        self.assertEqual((at["bytes_left"], at["fits"], at["needs_squeeze"]),
                         (0, True, False))
        ok, stored = self.inject(index, edit(k))
        self.assertTrue(ok)
        self.assertEqual(len(stored), limit)
        # one over: fits only because whitespace is squeezed
        over = measure(edit(k + 1))
        self.assertEqual((over["bytes_left"], over["fits"],
                          over["needs_squeeze"]), (-1, True, True))
        ok, stored = self.inject(index, edit(k + 1))
        self.assertTrue(ok)
        # a script is never written shorter than the original (padded with
        # spaces), so the record keeps its size
        self.assertEqual(len(stored), max(len(self.slots[index]["src"]),
                                          limit - over["bytes_left_squeezed"]))
        # squeezed boundary: exactly at the limit after squeezing everything
        # the injector may reclaim, then one byte more
        tail = "   "                            # trailing spaces to reclaim
        b0 = measure(edit(0, tail))
        k2 = b0["bytes_left"] + b0["reclaimable"]
        edge = measure(edit(k2, tail))
        self.assertEqual((edge["fits"], edge["needs_squeeze"],
                          edge["bytes_left_squeezed"]), (True, True, 0))
        ok, stored = self.inject(index, edit(k2, tail))
        self.assertTrue(ok)
        self.assertEqual(len(stored), limit)
        past = measure(edit(k2 + 1, tail))
        self.assertEqual((past["fits"], past["bytes_left_squeezed"]),
                         (False, -1))
        self.assertEqual(self.inject(index, edit(k2 + 1, tail)),
                         (False, None))

    def test_lf_script(self):
        self.check_boundaries(2)            # area12_loaderscript: no slack

    def test_crlf_script(self):
        self.check_boundaries(12)           # combatzooloaderscript: CRLF

    def test_unchanged_script(self):
        b = pip_scripts.budget(LOADERS, 0, self.original(0))
        self.assertEqual(b["edited_size"], b["original_size"])
        self.assertEqual(b["bytes_left"], b["limit"] - b["original_size"])
        self.assertLessEqual(b["limit"] + 0x28, b["slot_size"])

    def test_hash_expansion_counts(self):
        b = pip_scripts.budget(LOADERS, 12, 'a = HASH("foo")\n')
        self.assertEqual(b["hashes"], [["foo", 2356372769]])
        self.assertEqual(b["edited_size"], len(b"a = 2356372769\r\n"))
        ok, stored = self.inject(12, 'a = HASH("foo")\n')
        self.assertEqual(stored.rstrip(b" "), b"a = 2356372769\r\n")
        self.assertEqual(len(stored), len(self.slots[12]["src"]))   # padded to the original size

    def test_resolve_by_name(self):
        b = pip_scripts.budget(LOADERS, "combatzooloaderscript", "x = 1\n")
        self.assertEqual(b["record"], 12)

    def test_encoding_error_reported(self):
        b = pip_scripts.budget(LOADERS, 0, "a = 1\nb = '\u2014'\n")
        self.assertFalse(b["fits"])
        self.assertEqual(b["encoding_error"]["line"], 2)

    def test_structure_problems_in_edited_numbering(self):
        b = pip_scripts.budget(LOADERS, 12, 'x = HASH("a")\ny = {\n',
                               check=True)
        self.assertEqual([(p["line"], p["col"]) for p in b["problems"]],
                         [(2, 5)])

    def test_parse_is_cached(self):
        self.assertIs(pip_scripts.container_slots(LOADERS), self.slots)


if __name__ == "__main__":
    unittest.main()
