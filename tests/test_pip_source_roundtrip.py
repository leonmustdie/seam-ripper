#!/usr/bin/env python3
"""Tests for the PiP script text round trip.

PiP stores script source as single-byte (latin-1) text, but the .lua files
this toolkit writes for editing are UTF-8, and different scripts inside one
container use different line endings. Getting either wrong means an edit that
changed nothing still changes the bytes written back into the game.

Both defects were real and both were found on retail content:

  encoding     levelcommon.lu's libraryloading and naughtyisland_npcs carry
               French developer comments with accented characters. Writing
               UTF-8 and reading the bytes straight back turned one 0xE8 byte
               into two (0xC3 0xA8), growing the script and writing mojibake.

  line endings levelcommon.lu alone uses all three conventions: LF for most
               scripts, CRLF for objecttypes/rendergroups/surfacetype/
               vibbadge, and bare CR for libraryinput/libraryphysic.
               Flattening everything to LF rewrote every script that was not
               already LF.
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import pip_scripts


class LineEndingDetection(unittest.TestCase):
    def test_pure_lf(self):
        self.assertEqual(pip_scripts.line_ending_of(b"a\nb\nc\n"), "\n")

    def test_pure_crlf(self):
        self.assertEqual(pip_scripts.line_ending_of(b"a\r\nb\r\nc\r\n"), "\r\n")

    def test_pure_cr(self):
        self.assertEqual(pip_scripts.line_ending_of(b"a\rb\rc\r"), "\r")

    def test_mixed_falls_back_to_lf(self):
        """No single choice reproduces a mixed file, so pick the safe one."""
        self.assertEqual(pip_scripts.line_ending_of(b"a\r\nb\nc\n"), "\n")

    def test_no_line_endings_at_all(self):
        self.assertEqual(pip_scripts.line_ending_of(b"single line"), "\n")

    def test_empty(self):
        self.assertEqual(pip_scripts.line_ending_of(b""), "\n")


class SourceRoundTrip(unittest.TestCase):
    """write_source then encode_source must reproduce the original bytes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _roundtrip(self, original_bytes):
        text = original_bytes.decode(pip_scripts.SOURCE_ENCODING)
        p = self.tmp / "s.lua"
        pip_scripts.write_source(p, text)
        return pip_scripts.encode_source(p, original_bytes)

    def test_plain_ascii_lf(self):
        src = b"function f()\n  return 1\nend\n"
        self.assertEqual(self._roundtrip(src), src)

    def test_accented_latin1_preserved(self):
        """The real levelcommon case: a 0xE8 byte must stay one byte."""
        src = b"-- probablement un autre syst\xe8me qui va remplacer \xe7a\nx = 1\n"
        got = self._roundtrip(src)
        self.assertEqual(got, src)
        self.assertEqual(len(got), len(src))

    def test_accented_uppercase(self):
        src = b"--OFFICIELLEMENT SUPPRIM\xc9!\nx = 1\n"
        self.assertEqual(self._roundtrip(src), src)

    def test_crlf_preserved(self):
        src = b"function f()\r\n  return 1\r\nend\r\n"
        self.assertEqual(self._roundtrip(src), src)

    def test_bare_cr_preserved(self):
        src = b"-- vibrate only for the local player\rfunction V()\rend\r"
        self.assertEqual(self._roundtrip(src), src)

    def test_accented_plus_crlf(self):
        src = b"-- syst\xe8me\r\nx = 1\r\n"
        self.assertEqual(self._roundtrip(src), src)

    def test_every_latin1_byte_survives(self):
        src = bytes(range(1, 256)).replace(b"\r", b"x").replace(b"\n", b"y")
        self.assertEqual(self._roundtrip(src), src)


class EncodeSourceBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, data, name="s.lua"):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def test_bom_is_stripped(self):
        p = self._write("﻿x = 1\n".encode("utf-8"))
        self.assertEqual(pip_scripts.encode_source(p, b"x = 0\n"), b"x = 1\n")

    def test_editor_crlf_normalised_to_original_lf(self):
        """An editor that saved CRLF must not change an LF script."""
        p = self._write(b"a = 1\r\nb = 2\r\n")
        self.assertEqual(pip_scripts.encode_source(p, b"a = 0\nb = 0\n"),
                         b"a = 1\nb = 2\n")

    def test_editor_lf_becomes_crlf_for_a_crlf_script(self):
        p = self._write(b"a = 1\nb = 2\n")
        self.assertEqual(pip_scripts.encode_source(p, b"a = 0\r\nb = 0\r\n"),
                         b"a = 1\r\nb = 2\r\n")

    def test_non_utf8_file_treated_as_container_encoding(self):
        """A file already saved in latin-1 must not be mangled."""
        p = self._write(b"-- syst\xe8me\nx = 1\n")
        self.assertEqual(pip_scripts.encode_source(p, b"x = 0\n"),
                         b"-- syst\xe8me\nx = 1\n")

    def test_unencodable_character_is_refused(self):
        """A pasted em dash cannot be stored; say so instead of corrupting."""
        p = self._write("x = 1  -- — dash\n".encode("utf-8"))
        with self.assertRaises(SystemExit) as cm:
            pip_scripts.encode_source(p, b"x = 0\n")
        msg = str(cm.exception)
        self.assertIn("line 1", msg)
        self.assertIn("latin-1", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
