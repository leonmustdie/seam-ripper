#!/usr/bin/env python3
"""A function that writes one whole number both as `0` and as `0.0` stores it
once, so Ship must be able to point at the clash."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nbdec

LUAC = TOOLS / "luac51.exe"
if not LUAC.exists():
    LUAC = TOOLS / "luac51"


def conflicts(text):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "t.lua"
        src.write_text(text, encoding="utf-8", newline="\n")
        out = Path(d) / "t.luac"
        subprocess.run([str(LUAC), "-o", str(out), str(src)], check=True)
        return nbdec.spelling_conflicts(text, nbdec.parse(out.read_bytes()))


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class SpellingConflicts(unittest.TestCase):
    def test_both_spellings_in_one_function(self):
        found = conflicts("function f()\n  n = 0\n  g(n, 0.0, 1.5)\nend\n")
        self.assertEqual([(ln, t) for ln, t, _, _ in found], [(2, "0"), (3, "0.0")])

    def test_one_spelling_is_fine(self):
        self.assertEqual(conflicts("function f()\n  n = 0\n  g(n, nil, 1.5)\nend\n"), [])

    def test_separate_functions_do_not_clash(self):
        self.assertEqual(conflicts("function f() n = 0 end\nfunction g() m = 0.0 end\n"), [])


if __name__ == "__main__":
    unittest.main()
