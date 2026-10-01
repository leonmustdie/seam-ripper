#!/usr/bin/env python3
"""Tests for sr_search.py, the cached script search over many containers."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import pip_scripts
import sr_search

# a folder holding the retail NB1 global.lu; the test skips without it
RETAIL_GLOBAL = Path(os.environ.get("SR_TEST_NB1_GLOBAL_DIR",
                                    r"C:\Users\slmw0\Fuck\uh"))


def script_chunk(name, src):
    path = b"z:\\nb2_data\\assets\\scripts\\" + name.encode() + b".lua\0"
    return pip_scripts.build_script_chunk({
        "hash": zlib.crc32(name.encode()), "path": path,
        "src": src.encode("latin-1"), "trailer": b""})


def luh(records, slack=0x200):
    """A minimal PiP LUH container: [(hash, type, bytes)], stored raw."""
    img = bytearray()
    entries = []
    for h, t, data in records:
        off = len(img)
        img += data + b"\xDF" * slack
        img += b"\xDF" * (-len(img) % 0x100)
        entries.append((h, t, len(data), off))
    out = bytearray(b"\x05LUH" + struct.pack(">3I", 5, 0, len(records)))
    for h, t, sz, off in entries:
        out += struct.pack(">6I", h, t, 0xFFFFFFFF, sz, off, 0) + b"\0" * 15
    out += struct.pack(">6I", len(img), 1, len(img), 0x100000, 1, len(img))
    return bytes(out + img)


def scripts_lu(*pairs):
    return luh([(zlib.crc32(n.encode()), 0x04B00000, script_chunk(n, s))
                for n, s in pairs])


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="srsearch_"))
        self.folder = self.tmp / "game"
        self.folder.mkdir()
        self.cache = self.tmp / "cache"
        shared = ("shared", "function Shared()\n  return 1\nend\n")
        (self.folder / "a.lu").write_bytes(scripts_lu(
            ("alpha", "x = 1\nfunction Fear()\n  return x + 2\nend\n"),
            shared))
        (self.folder / "b.lu").write_bytes(scripts_lu(
            ("beta", "-- FEAR in caps\r\ny = 10\r\n"), shared))
        (self.folder / "c.lu").write_bytes(scripts_lu(
            ("gamma", "a = 1\rb = 2\rfear = 3\r")))
        (self.folder / "notes.lu").write_bytes(b"not a container")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def find(self, pattern, **kw):
        return list(sr_search.find(self.folder, pattern,
                                   cache_dir=self.cache, **kw))

    def test_index_counts_and_errors(self):
        seen = []
        s = sr_search.index_folder(self.folder, self.cache,
                                   progress=lambda *a: seen.append(a))
        self.assertEqual(s["containers"], 4)
        self.assertEqual(s["with_scripts"], 3)
        self.assertEqual(s["scripts"], 5)
        self.assertEqual(s["distinct"], 4)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["reread"], 4)
        self.assertEqual([a[:2] for a in seen],
                         [(1, 4), (2, 4), (3, 4), (4, 4)])
        self.assertTrue(seen[3][3].startswith("error"))

    def test_incremental(self):
        sr_search.index_folder(self.folder, self.cache)
        s = sr_search.index_folder(self.folder, self.cache)
        self.assertEqual(s["reread"], 0)
        # a changed file is read again, and only that one
        p = self.folder / "c.lu"
        p.write_bytes(scripts_lu(("gamma", "fear = 4\n")))
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        s = sr_search.index_folder(self.folder, self.cache)
        self.assertEqual(s["reread"], 1)
        self.assertEqual([h["text"] for h in self.find("fear =")],
                         ["fear = 4"])

    def test_removed_container_leaves_the_index(self):
        sr_search.index_folder(self.folder, self.cache)
        (self.folder / "c.lu").unlink()
        s = sr_search.index_folder(self.folder, self.cache)
        self.assertEqual(s["containers"], 3)
        self.assertFalse(any(h["container"] == "c.lu"
                             for h in self.find("fear")))

    def test_plain_ignores_case_by_default(self):
        got = {(h["container"], h["name"], h["line"]) for h in
               self.find("fear")}
        self.assertEqual(got, {("a.lu", "alpha", 2), ("b.lu", "beta", 1),
                               ("c.lu", "gamma", 3)})

    def test_case_sensitive(self):
        got = [(h["container"], h["line"]) for h in
               self.find("FEAR", case=True)]
        self.assertEqual(got, [("b.lu", 1)])

    def test_line_endings_counted_like_an_editor(self):
        h = self.find("b = 2")
        self.assertEqual((h[0]["line"], h[0]["text"]), (2, "b = 2"))
        h = self.find("y = 10")
        self.assertEqual((h[0]["line"], h[0]["text"]), (2, "y = 10"))

    def test_regex_anchors_work_per_line(self):
        got = [(h["name"], h["line"]) for h in
               self.find(r"^function \w+\(\)$", regex=True)]
        self.assertEqual(got, [("alpha", 2), ("shared", 1)])

    def test_identical_copies_grouped(self):
        got = self.find("Shared")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["container"], "a.lu")
        self.assertEqual(got[0]["also"], [{"container": "b.lu", "index": 1}])
        every = self.find("Shared", group=False)
        self.assertEqual([h["container"] for h in every], ["a.lu", "b.lu"])
        self.assertEqual(every[1]["also"], [])

    def test_hit_fields(self):
        h = self.find("x + 2")[0]
        self.assertEqual(h["index"], 0)
        self.assertEqual(h["game"], "pip")
        self.assertEqual(Path(h["container_path"]), self.folder / "a.lu")
        text = Path(h["source"]).read_text(encoding="utf-8")
        self.assertIn("return x + 2", text)
        self.assertTrue(str(self.cache) in h["source"])

    def test_limit_and_exclude(self):
        self.assertEqual(len(self.find("=", limit=2)), 2)
        got = {h["container"] for h in self.find("fear", exclude=["a.lu"])}
        self.assertEqual(got, {"b.lu", "c.lu"})

    def test_subfolders_searched_hidden_ones_skipped(self):
        game = self.tmp / "game2"
        (game / "lu").mkdir(parents=True)
        (game / "uh").mkdir()
        (game / ".seamripper" / "backups").mkdir(parents=True)
        shutil.copy(self.folder / "a.lu", game / "lu" / "a.lu")
        (game / "uh" / "a.lu").write_bytes(scripts_lu(
            ("other", "function Fear()\n  return 9\nend\n")))
        shutil.copy(self.folder / "a.lu", game / ".seamripper" / "backups" / "a.lu")
        got = list(sr_search.find(game, "Fear", cache_dir=self.cache))
        self.assertEqual([h["container"] for h in got], ["lu/a.lu", "uh/a.lu"])
        self.assertEqual(Path(got[0]["container_path"]).resolve(),
                         (game / "lu" / "a.lu").resolve())
        self.assertEqual(sr_search.index_folder(game, self.cache)["containers"], 2)

    def test_exclude_by_name_or_relative_path(self):
        game = self.tmp / "game3"
        (game / "lu").mkdir(parents=True)
        (game / "uh").mkdir()
        shutil.copy(self.folder / "a.lu", game / "lu" / "a.lu")
        shutil.copy(self.folder / "a.lu", game / "uh" / "a.lu")
        one = list(sr_search.find(game, "Fear", cache_dir=self.cache,
                                  exclude=["uh/a.lu"]))
        self.assertEqual([h["container"] for h in one], ["lu/a.lu"])
        none = list(sr_search.find(game, "Fear", cache_dir=self.cache,
                                   exclude=["a.lu"]))
        self.assertEqual(none, [])

    def test_cli_json_stream(self):
        r = subprocess.run([sys.executable, str(TOOLS / "sr_search.py"),
                            "find", str(self.folder), "fear", "--cache",
                            str(self.cache), "--json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [json.loads(ln) for ln in r.stdout.splitlines()]
        kinds = [x["type"] for x in rows]
        self.assertEqual(kinds.count("progress"), 4)
        self.assertEqual(kinds.count("hit"), 3)
        self.assertEqual(rows[-1]["type"], "done")
        self.assertEqual(rows[-1]["hits"], 3)

    def test_cli_bad_regex(self):
        r = subprocess.run([sys.executable, str(TOOLS / "sr_search.py"),
                            "find", str(self.folder), "(", "--regex",
                            "--cache", str(self.cache)],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bad regular expression", r.stderr)


@unittest.skipUnless((RETAIL_GLOBAL / "global.lu").exists(),
                     "retail NB1 global.lu not available")
class RetailNB1(unittest.TestCase):
    def test_decompiled_text_matches_export(self):
        tmp = Path(tempfile.mkdtemp(prefix="srsearch_"))
        try:
            s = sr_search.index_folder(RETAIL_GLOBAL, tmp / "cache")
            self.assertEqual(s["declined"], 0)
            hits = list(sr_search.find(RETAIL_GLOBAL, "function BackupDOFValues",
                                       cache_dir=tmp / "cache",
                                       update=False))
            self.assertEqual(len(hits), 1)
            self.assertEqual((hits[0]["name"], hits[0]["line"]),
                             ("camera", 2))
            out = tmp / "camera.lua"
            subprocess.run([sys.executable, str(TOOLS / "lu_lua.py"), "read",
                            str(RETAIL_GLOBAL / "global.lu"), "--index",
                            str(hits[0]["index"]), "-o", str(out)],
                           check=True, capture_output=True)
            read = out.read_text(encoding="utf-8").split("\n")
            self.assertEqual(read[hits[0]["line"] - 1], hits[0]["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
