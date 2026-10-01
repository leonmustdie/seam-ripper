#!/usr/bin/env python3
"""Ship errors must name the modder's own file and a line in it, and end with
one SR-ERROR line the GUI can parse."""
import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nblua
import lu_lua

SR_ERROR = re.compile(r'^SR-ERROR file="([^"]*)" line=(\d+) kind=(\w+): (.*)$')


class LuacMessages(unittest.TestCase):
    def test_windows_path(self):
        msg = (r"C:\tools\luac51.exe: C:\Temp\ship_x\edit.lua:2: "
               r"unexpected symbol near '#'")
        self.assertEqual(nblua.luac_error_line(msg),
                         (2, "unexpected symbol near '#'"))

    def test_relative_path_and_nested_line(self):
        msg = "luac: edit.lua:40: 'end' expected (to close 'function' at line 3) near '<eof>'"
        line, text = nblua.luac_error_line(msg)
        self.assertEqual(line, 40)
        self.assertIn("at line 3", text)

    def test_no_line(self):
        self.assertEqual(nblua.luac_error_line("something odd\nhappened"),
                         (0, "something odd happened"))


class HashKeepsLines(unittest.TestCase):
    def test_multiline_call_keeps_line_count(self):
        src = 'a = HASH(\n"x"\n)\nb = 1 +\n'
        out, found = nblua.expand_hash_keep_lines(src)
        self.assertEqual(out.count("\n"), src.count("\n"))
        self.assertEqual(found[0][0], "x")
        self.assertTrue(out.startswith("a = 0x"))

    def test_single_line_same_as_nb_names(self):
        import nb_names
        src = 'f(HASH("CSmoke01"), HASH(\'b\'))\n'
        self.assertEqual(nblua.expand_hash_keep_lines(src),
                         nb_names.expand_hash_calls(src))

    def test_pip_decimal(self):
        out, _ = nblua.expand_hash_keep_lines('x = HASH("Sting")', fmt="{:d}")
        import nb_names
        self.assertEqual(out, f"x = {nb_names.crc('Sting')}")


class ErrorLine(unittest.TestCase):
    def test_format_parses(self):
        e = nblua.ShipError("my file.lua line 7: bad\n  more", r"C:\a b\my file.lua",
                            7, "syntax")
        m = SR_ERROR.match(e.sr_line())
        self.assertEqual(m.groups(), (r"C:\a b\my file.lua", "7", "syntax",
                                      "my file.lua line 7: bad more"))
        self.assertEqual(e.as_dict()["line"], 7)

    def test_no_file(self):
        m = SR_ERROR.match(nblua.ShipError("x").sr_line())
        self.assertEqual(m.group(1), "")
        self.assertEqual(m.group(2), "0")


class StructureIssues(unittest.TestCase):
    def test_string_with_line(self):
        self.assertEqual(lu_lua._issue_line("unterminated string at line 12"),
                         (12, "unterminated string at line 12"))

    def test_string_without_line(self):
        self.assertEqual(lu_lua._issue_line("2 unclosed '('")[0], 0)

    def test_dict_and_tuple(self):
        self.assertEqual(lu_lua._issue_line({"line": 5, "message": "m"}), (5, "m"))
        self.assertEqual(lu_lua._issue_line((6, "m")), (6, "m"))


class StaleHint(unittest.TestCase):
    def _sm(self, a, b):
        import difflib
        return difflib.SequenceMatcher(None, a, b, autojunk=False)

    def test_missing_stamp(self):
        self.assertIn("seam ripper", nblua._stale_hint(None, self._sm(["a"], ["a"])))

    def test_mostly_different(self):
        stamp = nblua.BACKEND_RE.search(nblua.BACKEND_MARK.format("nbdec"))
        self.assertTrue(nblua._stale_hint(stamp, self._sm(list("abcdef"), list("uvwxyz"))))
        self.assertEqual(nblua._stale_hint(stamp, self._sm(list("abcdef"), list("abcdeX"))), "")


if __name__ == "__main__":
    unittest.main()
