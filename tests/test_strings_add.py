#!/usr/bin/env python3
"""lu_strings: a +HASH line adds a string the file does not have yet (new text records)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import sr_patch as P
import game_paths
from naughty_lu import LuFile

SRC = game_paths.NB1_DIR / "episode9.en_us.lu"
NEW = {0x0BADF00D: "A brand new line", 0x0BADF00E: "Two\\nlines and a\\ttab"}


def tool(script, *args):
    return subprocess.run([sys.executable, str(TOOLS / script), *map(str, args)],
                          capture_output=True, text=True)


@unittest.skipUnless(SRC.exists(), "needs SR_TEST_NB1_DIR (a retail NB1 lu folder)")
class AddStrings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "base.txt"
        tool("lu_strings.py", "extract", SRC, "-o", self.base)
        self.edited = self.tmp / "edited.txt"
        self.edited.write_text(self.base.read_text(encoding="utf-8")
                               + "".join(f"+{h:08x}\t{t}\n" for h, t in NEW.items()),
                               encoding="utf-8")

    def apply(self, src, edited, out):
        r = tool("lu_strings.py", "apply", src, edited, "-o", out, "--verify")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("VERIFY OK", r.stdout)
        return r.stdout

    def test_new_strings_are_appended_and_read_back(self):
        out = self.tmp / "out.lu"
        said = self.apply(SRC, self.edited, out)
        self.assertIn("added 2 new", said)
        before, after = LuFile(SRC), LuFile(out)
        self.assertEqual(len(after.records), len(before.records) + 2)
        back = self.tmp / "back.txt"
        tool("lu_strings.py", "extract", out, "-o", back)
        old = set(self.base.read_text(encoding="utf-8").splitlines())
        new = set(back.read_text(encoding="utf-8").splitlines())
        self.assertEqual(old - new, set())              # nothing the game had was lost
        self.assertEqual(new - old, {f"{h:08x}\t{t}" for h, t in NEW.items()})
        r = tool("verify_lzx.py", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rec in after.records[-2:]:
            self.assertEqual(rec.offset % 16, 0)
            self.assertEqual(rec.flags, before.records[0].flags)

    def test_applying_the_same_additions_twice_changes_nothing_more(self):
        once, twice = self.tmp / "once.lu", self.tmp / "twice.lu"
        self.apply(SRC, self.edited, once)
        said = self.apply(once, self.edited, twice)
        self.assertNotIn("added", said)
        self.assertEqual(len(LuFile(twice).records), len(LuFile(once).records))

    def test_a_plain_unknown_id_is_still_ignored(self):
        typo = self.tmp / "typo.txt"
        typo.write_text(self.base.read_text(encoding="utf-8") + "0badf00d\tx\n",
                        encoding="utf-8")
        out = self.tmp / "typo.lu"
        self.apply(SRC, typo, out)
        self.assertEqual(len(LuFile(out).records), len(LuFile(SRC).records))

    def test_patch_carries_only_the_added_lines_and_applies(self):
        patch = self.tmp / "add.srpatch"
        r = tool("sr_patch.py", "make", "-o", patch, "--name", "t",
                 "--strings", SRC, self.edited)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with zipfile.ZipFile(patch) as z:
            data = [z.read(n) for n in z.namelist() if n != "manifest.json"]
        self.assertEqual(data, ["".join(f"+{h:08x}\t{t}\n" for h, t in NEW.items()).encode()])
        g = self.tmp / "game"
        (g / "lu").mkdir(parents=True)
        shutil.copyfile(SRC, g / "lu" / SRC.name)
        res = P.apply_patch(patch, g, log=lambda m: None)
        direct = self.tmp / "direct.lu"
        self.apply(SRC, self.edited, direct)
        self.assertEqual(Path(res["files"][0]["out"]).read_bytes(), direct.read_bytes())

    def test_a_patch_with_added_strings_is_refused_by_a_reader_that_cannot_add_them(self):
        # builds from before "+" lines skipped them without a word and reported
        # success, so such a patch is format 2 and a format-1 reader must
        # refuse it up front
        patch = self.tmp / "add.srpatch"
        r = tool("sr_patch.py", "make", "-o", patch, "--name", "t", "--strings", SRC, self.edited)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(P.read_manifest(patch)["format_version"], 2)
        old = mock.patch.object(P, "FORMAT_VERSION", 1)
        old.start()
        self.addCleanup(old.stop)
        with self.assertRaises(P.PatchError) as cm:
            P.read_manifest(patch)
        self.assertIn("newer Seam Ripper", str(cm.exception))

    def test_a_patch_that_only_edits_strings_stays_readable_by_older_builds(self):
        lines = self.base.read_text(encoding="utf-8").split("\n")
        i = next(k for k, ln in enumerate(lines) if "\t" in ln)
        lines[i] = lines[i].split("\t")[0] + "\tJust an edit"
        edited = self.tmp / "edit_only.txt"
        edited.write_text("\n".join(lines), encoding="utf-8")
        patch = self.tmp / "edit.srpatch"
        r = tool("sr_patch.py", "make", "-o", patch, "--name", "t", "--strings", SRC, edited)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(P.read_manifest(patch)["format_version"], 1)

    def test_patch_make_refuses_a_plain_unknown_id(self):
        typo = self.tmp / "typo.txt"
        typo.write_text(self.base.read_text(encoding="utf-8") + "0badf00d\tx\n",
                        encoding="utf-8")
        r = tool("sr_patch.py", "make", "-o", self.tmp / "t.srpatch", "--name", "t",
                 "--strings", SRC, typo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("+HASH", r.stdout + r.stderr)


LC = game_paths.NB1_DIR / "levelcommon.en_us.lu"


@unittest.skipUnless(LC.exists(), "needs SR_TEST_NB1_DIR (a retail NB1 lu folder)")
class PartnerRecords(unittest.TestCase):
    """levelcommon's text file also holds non-text records that share a hash with
    a partner; positions must be tracked per record, not per hash."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "base.txt"
        tool("lu_strings.py", "extract", LC, "-o", self.base)

    def test_an_unchanged_strings_file_keeps_every_record_where_it_was(self):
        out = self.tmp / "same.lu"
        r = tool("lu_strings.py", "apply", LC, self.base, "-o", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a, b = LuFile(LC), LuFile(out)
        self.assertEqual([(x.hash, x.type, x.size, x.offset) for x in a.records],
                         [(x.hash, x.type, x.size, x.offset) for x in b.records])
        self.assertEqual(a.image, b.image)

    def test_added_and_edited_strings_pass_the_layout_check(self):
        lines = self.base.read_text(encoding="utf-8").split("\n")
        i = next(k for k, ln in enumerate(lines) if "\t" in ln)
        lines[i] = lines[i].split("\t")[0] + "\tA longer line than the game had here"
        edited = self.tmp / "edited.txt"
        edited.write_text("\n".join(lines) + "+0badf00d\tNew popup text\n", encoding="utf-8")
        out = self.tmp / "out.lu"
        r = tool("lu_strings.py", "apply", LC, edited, "-o", out, "--verify")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("VERIFY OK", r.stdout)
        r = tool("verify_lzx.py", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a, b = LuFile(LC), LuFile(out)
        # the non-text records came through untouched, whatever moved around them
        old = {(x.hash, x.type, x.index): a.chunk(x) for x in a.records if x.type != 0x04D00002}
        new = {(x.hash, x.type, x.index): b.chunk(x) for x in b.records if x.type != 0x04D00002}
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main()
