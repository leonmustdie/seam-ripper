#!/usr/bin/env python3
"""Script chunks extract to script/ (2.0 and earlier used animation/, which
held scripts, not animation data). Readers must find both, so extractions
made with older versions keep working."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import game_paths  # noqa: E402
import naughty_lu  # noqa: E402

BEARTRAP = game_paths.NB1_DIR / "beartrap.lu"


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class ScriptDirs(unittest.TestCase):
    def test_script_type_is_labelled_script(self):
        self.assertEqual(naughty_lu.TYPE_NAMES[0x04B00000], "script")

    def test_finds_new_and_old_folders(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            touch(root / "global" / "script" / "0001_a.bin")
            touch(root / "beartrap" / "animation" / "0002_b.bin")
            touch(root / "beartrap" / "texture" / "0003_c.bin")
            got = [p.relative_to(root).as_posix() for p in naughty_lu.script_chunk_files(root)]
            self.assertEqual(got, ["beartrap/animation/0002_b.bin", "global/script/0001_a.bin"])

    def test_flat_unit_folder(self):
        with tempfile.TemporaryDirectory() as t:
            unit = Path(t)
            touch(unit / "script" / "0001_a.bin")
            touch(unit / "animation" / "0002_b.bin")
            got = [p.name for p in naughty_lu.script_chunk_files(unit, nested=False)]
            self.assertEqual(sorted(got), ["0001_a.bin", "0002_b.bin"])

    @unittest.skipUnless(BEARTRAP.exists(), "no retail beartrap.lu here")
    def test_extract_writes_script_folder(self):
        with tempfile.TemporaryDirectory() as t:
            subprocess.run([sys.executable, str(TOOLS / "naughty_lu.py"), "extract", str(BEARTRAP), "-o", t],
                           check=True, capture_output=True)
            unit = Path(t) / "beartrap"
            self.assertTrue((unit / "script").is_dir())
            self.assertFalse((unit / "animation").exists())
            found = naughty_lu.script_chunk_files(t)
            self.assertTrue(found)
            self.assertTrue(any(b"\x1bLua" in p.read_bytes() for p in found))


if __name__ == "__main__":
    unittest.main()
