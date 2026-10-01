#!/usr/bin/env python3
"""proto360.splice must replace a function's CODE, not its debug stamps.

linedefined / lastlinedefined come from whichever source file was compiled,
so splicing an edited function in used to overwrite the retail line numbers
with the edited file's - bytes the modder never changed.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import lua_recompile
import nbdec
import proto360

LUAC = TOOLS / "luac51.exe"
if not LUAC.exists():
    LUAC = TOOLS / "luac51"


def game_chunk(source, tmp):
    src = tmp / "s.lua"
    src.write_text(source, encoding="utf-8", newline="\n")
    out = tmp / "s.luac"
    subprocess.run([str(LUAC), "-s", "-o", str(out), str(src)], check=True)
    return lua_recompile.convert(out.read_bytes())


def lines_of(chunk):
    # the game format differs from standard 5.1 only in the header and the
    # top-level nups byte; parse the stamps straight out of the proto tree
    top, _ = proto360.parse(chunk)
    out = []

    def walk(node):
        at = node["span"][0] + 4 + proto360._u32(chunk, node["span"][0])
        out.append((proto360._u32(chunk, at), proto360._u32(chunk, at + 4)))
        for k in node["kids"]:
            walk(k)
    walk(top)
    return out


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class SpliceKeepsLineStamps(unittest.TestCase):
    def test_line_numbers_survive_an_edit(self):
        tmp = Path(tempfile.mkdtemp())
        orig = game_chunk("function F()\n  local g = function() return 1 end\n"
                          "  return 2\nend\n", tmp)
        # the same function further down the file, with a changed value
        edit = game_chunk("\n\n\n\n\nfunction F()\n  local g = function() "
                          "return 1 end\n  return 3\nend\n", tmp)
        self.assertNotEqual(lines_of(orig), lines_of(edit))
        out = proto360.splice(orig, edit, [0])
        self.assertEqual(lines_of(out), lines_of(orig))
        # and the edit itself did land
        self.assertEqual(proto360.decode_logic(out)["0_0"],
                         proto360.decode_logic(edit)["0_0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
