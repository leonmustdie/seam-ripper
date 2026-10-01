"""Tests for xiso_extract.py on a small built image and, if present, the retail disc."""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import xiso_extract as X  # noqa: E402

RETAIL_ISO = Path(r"C:\Users\slmw0\Downloads\Naughty Bear - Gold Edition (USA) (En,Fr,De,Es,It)"
                  r"\Naughty Bear - Gold Edition (USA) (En,Fr,De,Es,It).iso")
RETAIL_LU = Path(r"D:\testingenvironment\initialnb1files\lu")


def table(entries):
    """One directory sector: entries chained through their right pointers."""
    out = bytearray()
    for i, (name, sector, size, is_dir) in enumerate(entries):
        raw = name.encode("latin-1")
        length = (14 + len(raw) + 3) & ~3
        right = (len(out) + length) // 4 if i + 1 < len(entries) else 0
        out += struct.pack("<HHIIBB", 0, right, sector, size, 0x10 if is_dir else 0x20, len(raw))
        out += raw + b"\xff" * (length - 14 - len(raw))
    return bytes(out) + b"\xff" * (X.SECTOR - len(out))


def build_image(path, names=("default.xex", "lu"), truncate=0):
    """A rebuilt-layout image: default.xex at the root, lu/ with two files."""
    files = {"default.xex": b"XEX2" + b"x" * 3000, "lu/a.lu": b"A" * 5000, "lu/b.lu": b"B" * 10}
    data_at = 35
    placed = {}
    for key, blob in files.items():
        placed[key] = data_at
        data_at += (len(blob) + X.SECTOR - 1) // X.SECTOR
    img = bytearray(data_at * X.SECTOR)
    img[32 * X.SECTOR:32 * X.SECTOR + 28] = X.MAGIC + struct.pack("<II", 33, X.SECTOR)
    root = table([(names[0], placed["default.xex"], len(files["default.xex"]), False),
                  (names[1], 34, X.SECTOR, True)])
    lu = table([("a.lu", placed["lu/a.lu"], 5000, False), ("b.lu", placed["lu/b.lu"], 10, False)])
    img[33 * X.SECTOR:34 * X.SECTOR] = root
    img[34 * X.SECTOR:35 * X.SECTOR] = lu
    for key, blob in files.items():
        at = placed[key] * X.SECTOR
        img[at:at + len(blob)] = blob
    Path(path).write_bytes(bytes(img[:len(img) - truncate] if truncate else img))
    return files


class BuiltImage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="xiso_test_"))
        self.iso = self.tmp / "game.iso"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lists_every_file_with_its_size(self):
        build_image(self.iso)
        with open(self.iso, "rb") as f:
            layout, base = X.find_partition(f)
            got = [(p, s) for p, _start, s in X.files(f, base)]
        self.assertEqual((layout, base), ("rebuilt", 0))
        self.assertEqual(got, [("default.xex", 3004), ("lu/a.lu", 5000), ("lu/b.lu", 10)])

    def test_extract_copies_the_exact_bytes(self):
        files = build_image(self.iso)
        out = self.tmp / "out"
        self.assertEqual(X.extract(self.iso, out, log=lambda m: None), 3)
        for key, blob in files.items():
            self.assertEqual((out / key).read_bytes(), blob)

    def test_lu_only_skips_everything_else(self):
        build_image(self.iso)
        out = self.tmp / "out"
        X.extract(self.iso, out, "lu", log=lambda m: None)
        self.assertEqual(sorted(p.name for p in out.rglob("*") if p.is_file()), ["a.lu", "b.lu"])

    def test_not_an_xbox_image_is_refused(self):
        self.iso.write_bytes(b"\0" * (40 * X.SECTOR))
        with self.assertRaises(X.DiscError):
            X.extract(self.iso, self.tmp / "out", log=lambda m: None)

    def test_names_that_climb_out_of_the_folder_are_refused(self):
        build_image(self.iso, names=("..", "lu"))
        with self.assertRaises(X.DiscError):
            X.extract(self.iso, self.tmp / "out", log=lambda m: None)
        self.assertFalse((self.tmp / "default.xex").exists())

    def test_cut_short_image_says_so(self):
        build_image(self.iso, truncate=X.SECTOR)
        with self.assertRaisesRegex(X.DiscError, "ends early"):
            X.extract(self.iso, self.tmp / "out", log=lambda m: None)

    def test_command_line(self):
        build_image(self.iso)
        r = subprocess.run([sys.executable, str(TOOLS / "xiso_extract.py"), "extract",
                            str(self.iso), "-o", str(self.tmp / "out"), "--lu-only"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "out" / "lu" / "a.lu").exists())
        r = subprocess.run([sys.executable, str(TOOLS / "xiso_extract.py"), "list",
                            str(self.tmp / "missing.iso")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


@unittest.skipUnless(RETAIL_ISO.exists() and RETAIL_LU.exists(), "retail NB1 disc image not here")
class RetailDisc(unittest.TestCase):
    def test_retail_disc_matches_the_retail_files(self):
        with open(RETAIL_ISO, "rb") as f:
            layout, base = X.find_partition(f)
            entries = {p.lower(): (start, size) for p, start, size in X.files(f, base)}
            self.assertEqual(layout, "XGD2")
            for name in ("bone.lu", "global.lu", "naughtyisland.lu"):
                start, size = entries[f"lu/{name}"]
                f.seek(base + start * X.SECTOR)
                disc = hashlib.sha256(f.read(size)).digest()
                retail = hashlib.sha256((RETAIL_LU / name).read_bytes()).digest()
                self.assertEqual(disc, retail, name)


if __name__ == "__main__":
    unittest.main()
