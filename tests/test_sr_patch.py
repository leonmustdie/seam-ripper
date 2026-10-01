#!/usr/bin/env python3
"""sr_patch: patches hold only changed lines, and applying one rebuilds exactly what a direct ship would."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import sr_patch as P

NB1 = Path(r"D:\testingenvironment\initialnb1files\lu")
BONE = NB1 / "bone.lu"
have_nb1 = BONE.exists() and any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify"))

BASE = "\n".join([
    "-- seam ripper: decompiled by nbdec (keep this line)",
    "function A()",
    '  f(--[[HASH:"x" TEXT:"Some game text"]]0x1, 1.0)',
    "  g(2)",
    "end",
    "function B()",
    "  h(3)",
    "end",
    ""])


class Lines(unittest.TestCase):
    def test_fingerprints_ignore_comments_and_spacing(self):
        a = P.normal_lines('x = "--no" -- yes\n--[==[ a\nb ]==] y  =  [[s--]]')
        self.assertEqual(a, ['x = "--no"', "", "y = [[s--]]"])

    def test_only_changed_lines_are_stored(self):
        edited = BASE.replace("g(2)", "g(2, nil, 1.5)")
        hunks = P.diff_hunks(BASE, edited)
        self.assertEqual([h["new"] for h in hunks], [["  g(2, nil, 1.5)"]])
        self.assertEqual(P.apply_hunks(BASE, hunks), edited)

    def test_game_text_is_not_stored(self):
        edited = BASE.replace("1.0)", "2.0)")
        new = P.diff_hunks(BASE, edited)[0]["new"][0]
        self.assertNotIn("Some game text", new)
        self.assertIn('HASH:"x"', new)

    def test_placed_by_content_when_lines_moved(self):
        hunks = P.diff_hunks(BASE, BASE.replace("h(3)", "h(4)"))
        moved = BASE.replace("function A()", "local pad\nlocal pad2\nfunction A()")
        self.assertIn("h(4)", P.apply_hunks(moved, hunks))

    def test_annotations_do_not_matter(self):
        hunks = P.diff_hunks(BASE, BASE.replace("g(2)", "g(5)"))
        other_reader = BASE.replace(' TEXT:"Some game text"', "")
        self.assertIn("g(5)", P.apply_hunks(other_reader, hunks))

    def test_refuses_a_different_script(self):
        hunks = P.diff_hunks(BASE, BASE.replace("g(2)", "g(5)"))
        with self.assertRaises(P.PatchError):
            P.apply_hunks(BASE.replace("g(2)", "g(7)"), hunks)

    def test_refuses_an_unrelated_file(self):
        with self.assertRaises(P.PatchError):
            P.diff_hunks(BASE, "totally\ndifferent\nfile\n")


def tool(script, *args):
    return subprocess.run([sys.executable, str(TOOLS / script), *map(str, args)],
                          capture_output=True, text=True, errors="replace")


@unittest.skipUnless(have_nb1, "retail NB1 files or lzxverify not available")
class RetailPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="srpatch_test_"))
        base = cls.tmp / "wm.lua"
        r = tool("lu_lua.py", "read", BONE, "--index", 207, "-o", base)
        assert r.returncode == 0, r.stderr
        text = base.read_text(encoding="utf-8")
        assert '"strength", 2.0' in text
        cls.edit = cls.tmp / "wm_edit.lua"
        cls.edit.write_text(text.replace('"strength", 2.0', '"strength", 3.0', 1),
                            encoding="utf-8")
        cls.patch = cls.tmp / "strength.srpatch"
        r = tool("sr_patch.py", "make", "-o", cls.patch, "--name", "strength",
                 "--script", BONE, 207, cls.edit)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.direct = cls.tmp / "direct_bone.lu"
        r = tool("lu_lua.py", "ship", BONE, "--edit", f"207={cls.edit}", "-o", cls.direct)
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        for p in cls.tmp.rglob("*"):
            if p.is_file():
                p.chmod(stat.S_IREAD | stat.S_IWRITE)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def game(self, name, source=BONE):
        g = self.tmp / name
        (g / "lu").mkdir(parents=True)
        shutil.copyfile(source, g / "lu" / "bone.lu")
        return g

    def test_patch_holds_no_game_code(self):
        with zipfile.ZipFile(self.patch) as z:
            self.assertEqual(z.namelist(), ["manifest.json"])
            m = json.loads(z.read("manifest.json"))
        new = [ln for t in m["targets"] for e in t["edits"]
               for h in e["hunks"] for ln in h["new"]]
        self.assertEqual(len(new), 1)
        self.assertIn('"strength", 3.0', new[0])
        self.assertLess(self.patch.stat().st_size, 2000)

    def test_patch_records_the_seam_ripper_version(self):
        sys.path.insert(0, str(TOOLS.parent))
        from sr_gui import VERSION
        self.assertEqual(P.SEAMRIPPER_VERSION, VERSION)
        m = P.read_manifest(self.patch)
        self.assertEqual(m["made_with"], f"Seam Ripper {VERSION}")
        self.assertIn(f"made with: Seam Ripper {VERSION}", P.info_text(m, self.patch))

    def test_apply_in_place_matches_direct_ship_and_reverts(self):
        import sr_backup
        g = self.game("inplace")
        r = P.apply_patch(self.patch, g, log=lambda m: None)
        self.assertEqual([f["status"] for f in r["files"]], ["identical"])
        self.assertEqual((g / "lu" / "bone.lu").read_bytes(), self.direct.read_bytes())
        again = P.apply_patch(self.patch, g, log=lambda m: None)
        self.assertEqual([f["status"] for f in again["files"]], ["applied"])
        # a patch made from the shipped-into file is still made against retail
        m = P.make_patch(self.tmp / "from_modded.srpatch",
                         [{"container": g / "lu" / "bone.lu", "scripts": [(207, self.edit)]}],
                         "again", log=lambda m: None)
        self.assertEqual(m["targets"][0]["sha256"], P.sha256_file(BONE))
        self.assertEqual(m["targets"][0]["edits"][0]["hunks"],
                         P.read_manifest(self.patch)["targets"][0]["edits"][0]["hunks"])
        sr_backup.revert_to_retail(g / "lu" / "bone.lu")
        self.assertEqual((g / "lu" / "bone.lu").read_bytes(), BONE.read_bytes())

    def test_out_folder_leaves_the_game_alone(self):
        g = self.game("outdir")
        r = P.apply_patch(self.patch, g, self.tmp / "outdir_result", log=lambda m: None)
        self.assertEqual((g / "lu" / "bone.lu").read_bytes(), BONE.read_bytes())
        self.assertEqual(Path(r["files"][0]["out"]).read_bytes(), self.direct.read_bytes())
        # straight into the chosen folder, not <folder>\lu\
        self.assertEqual(Path(r["files"][0]["out"]), self.tmp / "outdir_result" / "bone.lu")
        self.assertFalse((g / "lu" / ".seamripper").exists())

    def test_other_script_modded_is_compatible(self):
        pick = self.tmp / "pick.lua"
        tool("lu_lua.py", "read", BONE, "--index", 208, "-o", pick)
        text = pick.read_text(encoding="utf-8")
        old = "0xeecb4bfd, 0.0, 1.0)"
        self.assertIn(old, text)
        pick.write_text(text.replace(old, "0xeecb4bfd, 0.0, 1.25)", 1), encoding="utf-8")
        modded = self.tmp / "modded_bone.lu"
        r = tool("lu_lua.py", "ship", BONE, "--edit", f"208={pick}", "-o", modded)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        g = self.game("compatible", modded)
        self.assertEqual(P.check_targets(P.read_manifest(self.patch), g)[0]["status"],
                         "compatible")
        r = P.apply_patch(self.patch, g, log=lambda m: None)
        self.assertEqual(r["files"][0]["status"], "compatible")
        lu = g / "lu" / "bone.lu"
        out = self.tmp / "compat_check.lua"
        tool("lu_lua.py", "read", lu, "--index", 207, "-o", out)
        self.assertIn('"strength", 3.0', out.read_text(encoding="utf-8"))
        tool("lu_lua.py", "read", lu, "--index", 208, "-o", out)
        self.assertIn("0.0, 1.25)", out.read_text(encoding="utf-8"))

    def test_mismatch_missing_and_read_only_are_refused(self):
        other = self.tmp / "other.lua"
        other.write_text(self.edit.read_text(encoding="utf-8")
                         .replace('"strength", 3.0', '"strength", 4.0'), encoding="utf-8")
        modded = self.tmp / "other_bone.lu"
        tool("lu_lua.py", "ship", BONE, "--edit", f"207={other}", "-o", modded)
        g = self.game("mismatch", modded)
        before = (g / "lu" / "bone.lu").read_bytes()
        with self.assertRaises(P.PatchError) as cm:
            P.apply_patch(self.patch, g, log=lambda m: None)
        self.assertIn("different version", str(cm.exception))
        with self.assertRaises(P.PatchError):
            P.apply_patch(self.patch, g, force=True, log=lambda m: None)
        self.assertEqual((g / "lu" / "bone.lu").read_bytes(), before)

        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaises(P.PatchError) as cm:
            P.apply_patch(self.patch, empty, log=lambda m: None)
        self.assertIn("missing", str(cm.exception))

        g = self.game("readonly")
        (g / "lu" / "bone.lu").chmod(stat.S_IREAD)
        with self.assertRaises(P.PatchError) as cm:
            P.apply_patch(self.patch, g, log=lambda m: None)
        self.assertIn("read-only", str(cm.exception))


    def test_strings_patch_holds_only_the_new_text(self):
        src = NB1 / "episode9.en_us.lu"
        base = self.tmp / "strings.txt"
        tool("lu_strings.py", "extract", src, "-o", base)
        lines = base.read_text(encoding="utf-8").split("\n")
        i = next(k for k, ln in enumerate(lines) if "\t" in ln and not ln.startswith("#"))
        h = lines[i].split("\t")[0]
        lines[i] = h + "\tA modder's own text"
        edited = self.tmp / "strings_edit.txt"
        edited.write_text("\n".join(lines), encoding="utf-8")
        patch = self.tmp / "text.srpatch"
        r = tool("sr_patch.py", "make", "-o", patch, "--name", "t", "--strings", src, edited)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with zipfile.ZipFile(patch) as z:
            data = [z.read(n) for n in z.namelist() if n != "manifest.json"]
        self.assertEqual(data, [f"{h}\tA modder's own text\n".encode()])
        g = self.tmp / "strings_game"
        (g / "lu").mkdir(parents=True)
        shutil.copyfile(src, g / "lu" / src.name)
        r = P.apply_patch(patch, g, log=lambda m: None)
        self.assertEqual(r["files"][0]["status"], "identical")


if __name__ == "__main__":
    unittest.main()
