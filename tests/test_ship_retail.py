#!/usr/bin/env python3
"""lu_lua.py ship end to end on retail containers: no-op stays byte-identical,
edits verify, errors point at the modder's file, preview writes nothing,
several scripts and several containers ship in one call. Skips without the
game files; nothing from them is written into the repo."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
sys.path.insert(0, str(TOOLS))

NB1 = Path(r"D:\testingenvironment\initialnb1files\lu")
GLOBAL = NB1 / "global.lu"
PIP = Path(r"C:\Users\slmw0\Fuck\pip_full\global.lu")
LUAC = TOOLS / "luac51.exe"
SR_ERROR = re.compile(r'^SR-ERROR file="([^"]*)" line=(\d+) kind=(\w+): ', re.M)

have_nb1 = GLOBAL.exists() and LUAC.exists()
have_verifier = any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify"))


def run(*args, env=None):
    return subprocess.run([sys.executable, str(TOOLS / "lu_lua.py"), *map(str, args)],
                          capture_output=True, text=True, errors="replace",
                          env=env)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="srship_"))
        self.env = {**os.environ, "SEAMRIPPER_CACHE": str(self.tmp / "cache")}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, lu, index, name):
        out = self.tmp / name
        r = run("read", lu, "--index", index, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def edited(self, src, old, new, name):
        text = src.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p = self.tmp / name
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return p


@unittest.skipUnless(have_nb1, "retail NB1 global.lu / luac not available")
class Nb1Ship(Scratch):
    def test_noop_is_byte_identical(self):
        src = self.read(GLOBAL, 285, "fearstates.lua")
        out = self.tmp / "out.lu"
        r = run("ship", GLOBAL, "--index", 285, src, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out.read_bytes(), GLOBAL.read_bytes())

    @unittest.skipUnless(have_verifier, "lzxverify not built")
    def test_edit_matches_lu_chunk_replace(self):
        # the one-pass multi-record rebuild must equal the old per-record tool
        import lu_chunk_replace
        import lua_chunk_swap
        import nblua
        from naughty_lu import LuFile
        src = self.read(GLOBAL, 302, "gamemodes.lua")
        ed = self.edited(src, "eBRONZE_GRADE, 350000)", "eBRONZE_GRADE, 360000)",
                         "gamemodes.edit.lua")
        out = self.tmp / "out.lu"
        r = run("ship", GLOBAL, "--index", 302, ed, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("independent decode OK", r.stdout)
        lu = LuFile(str(GLOBAL))
        chunk = bytes(lu.chunk(lu.records[302]))
        got = nblua.prepare_edit(chunk, ed, str(LUAC), log=lambda *_: None)
        new_chunk = lua_chunk_swap.swap(chunk, got["new_image"])
        (self.tmp / "c.bin").write_bytes(new_chunk)
        argv = sys.argv
        sys.argv = ["lu_chunk_replace.py", str(GLOBAL), "--index", "302",
                    str(self.tmp / "c.bin"), "-o", str(self.tmp / "ref.lu")]
        try:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                lu_chunk_replace.main()
        finally:
            sys.argv = argv
        self.assertEqual(out.read_bytes(), (self.tmp / "ref.lu").read_bytes())

    def test_syntax_error_names_users_file_and_line(self):
        src = self.read(GLOBAL, 302, "gamemodes.lua")
        lines = src.read_text(encoding="utf-8").split("\n")
        lines.insert(1, "# my change")
        bad = self.tmp / "my edit.lua"
        bad.write_text("\n".join(lines), encoding="utf-8")
        r = run("ship", GLOBAL, "--index", 302, bad, "-o", self.tmp / "o.lu")
        self.assertEqual(r.returncode, 1)
        self.assertIn("my edit.lua line 2: unexpected symbol near '#'", r.stderr)
        self.assertNotIn("base.lua", r.stderr)
        self.assertNotIn("edit.lua:", r.stderr)
        m = SR_ERROR.search(r.stderr)
        self.assertEqual((Path(m.group(1)), m.group(2), m.group(3)),
                         (bad, "2", "syntax"))
        self.assertFalse((self.tmp / "o.lu").exists())

    def test_file_from_another_decompiler_is_refused(self):
        # an old-style read: luadec text without the stamp line
        r = run("read", GLOBAL, "--index", 302, "--backend", "luadec",
                "-o", self.tmp / "old.lua")
        if r.returncode:
            self.skipTest("luadec backend unavailable")
        text = (self.tmp / "old.lua").read_text(encoding="utf-8").split("\n")
        old = self.tmp / "old_nostamp.lua"
        old.write_text("\n".join(text[2:]), encoding="utf-8")
        r = run("ship", GLOBAL, "--index", 302, old, "-o", self.tmp / "o.lu")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Re-read the script", r.stderr)
        self.assertEqual(SR_ERROR.search(r.stderr).group(3), "stale")
        self.assertFalse((self.tmp / "o.lu").exists())

    def test_baseline_failure_is_not_blamed_on_the_edit(self):
        import nblua
        from naughty_lu import LuFile
        lu = LuFile(str(GLOBAL))
        chunk = bytes(lu.chunk(lu.records[302]))
        src = self.read(GLOBAL, 302, "gm.lua")
        orig = nblua.decompile
        nblua.decompile = lambda *a, **k: ("x = = 1\n" * 3, "luadec")
        try:
            with self.assertRaises(nblua.ShipError) as cm:
                nblua.prepare_edit(chunk, src, str(LUAC), log=lambda *_: None)
        finally:
            nblua.decompile = orig
        e = cm.exception
        self.assertEqual((e.kind, e.line, Path(e.file)), ("baseline", 1, src))
        self.assertIn("not caused by your edit", str(e))
        self.assertIn("Re-read the script", str(e))

    def test_added_function_points_at_it(self):
        src = self.read(GLOBAL, 293, "npc.lua")
        lines = src.read_text(encoding="utf-8").split("\n")
        lines.insert(60, "local function extra() return 1 end")
        p = self.tmp / "npc.edit.lua"
        p.write_text("\n".join(lines), encoding="utf-8")
        r = run("ship", GLOBAL, "--index", 293, p, "-o", self.tmp / "o.lu")
        m = SR_ERROR.search(r.stderr)
        self.assertEqual((m.group(2), m.group(3)), ("61", "structure"))

    def test_preview_writes_nothing(self):
        src = self.read(GLOBAL, 302, "gamemodes.lua")
        ed = self.edited(src, "eBRONZE_GRADE, 350000)", "eBRONZE_GRADE, 360000)",
                         "gamemodes.edit.lua")
        out = self.tmp / "o.lu"
        r = run("ship", GLOBAL, "--index", 302, ed, "-o", out, "--preview",
                "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.exists())
        rep = json.loads(r.stdout)
        self.assertTrue(rep["ok"] and rep["preview"])
        (s,) = rep["scripts"]
        self.assertEqual(s["functions"], [{"path": "0", "line": 4}])
        self.assertIn("+gradeScore:AddGradeScore(engine.eBRONZE_GRADE, 360000)",
                      s["diff"])
        self.assertEqual(rep["targets"][0]["status"], "would-ship")

    @unittest.skipUnless(have_verifier, "lzxverify not built")
    def test_two_scripts_one_ship_equals_two_ships(self):
        a = self.edited(self.read(GLOBAL, 302, "gm.lua"), "eBRONZE_GRADE, 350000)",
                        "eBRONZE_GRADE, 360000)", "gm.edit.lua")
        b = self.edited(self.read(GLOBAL, 293, "npc.lua"),
                        "npc.unawareVisionRange = 7.5",
                        "npc.unawareVisionRange = 9.5", "npc.edit.lua")
        both = self.tmp / "both.lu"
        r = run("ship", GLOBAL, "-o", both, "--edit", f"302={a}", "--edit",
                f"293={b}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("independent decode OK"), 1)
        one = self.tmp / "one.lu"
        self.assertEqual(run("ship", GLOBAL, "--index", 302, a, "-o", one).returncode, 0)
        two = self.tmp / "two.lu"
        self.assertEqual(run("ship", one, "--index", 293, b, "-o", two).returncode, 0)
        self.assertEqual(both.read_bytes(), two.read_bytes())

    def test_stage_keeps_retail_backup_and_revert(self):
        stage = self.tmp / "stage"
        stage.mkdir()
        shutil.copyfile(GLOBAL, stage / "global.lu")
        a = self.edited(self.read(GLOBAL, 302, "gm.lua"), "eBRONZE_GRADE, 350000)",
                        "eBRONZE_GRADE, 360000)", "gm.edit.lua")
        r = run("ship", GLOBAL, "--index", 302, a, "--stage", stage)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual((stage / "global.lu").read_bytes(), GLOBAL.read_bytes())
        backup = stage / ".seamripper" / "backups" / "global.lu"
        self.assertEqual(backup.read_bytes(), GLOBAL.read_bytes())
        rows = json.loads(run("backups", stage, "--json").stdout)
        self.assertEqual(rows[0]["current"], "modified")
        self.assertEqual(run("revert", stage / "global.lu").returncode, 0)
        self.assertEqual((stage / "global.lu").read_bytes(), GLOBAL.read_bytes())


@unittest.skipUnless(have_nb1 and (NB1 / "bone.lu").exists()
                     and (NB1 / "beartrap.lu").exists(),
                     "retail NB1 weapon containers not available")
class Nb1Targets(Scratch):
    """weaponmethods ships in both bone.lu and beartrap.lu, identically."""

    def setUp(self):
        super().setUp()
        from naughty_lu import LuFile
        import lu_lua
        self.idx = {p: next(s.index for s in lu_lua.scripts(LuFile(str(p)))
                            if s.name == "weaponmethods")
                    for p in (NB1 / "bone.lu", NB1 / "beartrap.lu")}
        src = self.read(NB1 / "bone.lu", self.idx[NB1 / "bone.lu"], "wm.lua")
        self.edit = self.edited(src, '"strength", 2.0', '"strength", 3.0',
                                "wm.edit.lua")

    def test_where_finds_identical_copy_and_caches(self):
        folder = self.tmp / "assets"
        folder.mkdir()
        for p in self.idx:
            shutil.copyfile(p, folder / p.name)
        r = run("where", folder, folder / "bone.lu", "--index",
                self.idx[NB1 / "bone.lu"], "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        names = {Path(c["container"]).name: c["identical"] for c in rep["copies"]}
        self.assertEqual(names, {"beartrap.lu": True})
        self.assertTrue((self.tmp / "cache" / "where_index.json").exists())
        again = run("where", folder, folder / "bone.lu", "--index",
                    self.idx[NB1 / "bone.lu"], env=self.env)
        self.assertNotIn("indexing", again.stdout + again.stderr)

    def test_read_only_target_is_refused_cleanly(self):
        import stat
        game = self.tmp / "ro"
        game.mkdir()
        target = game / "bone.lu"
        shutil.copyfile(NB1 / "bone.lu", target)
        before = target.read_bytes()
        target.chmod(stat.S_IREAD)
        try:
            r = run("ship", target, "--index", self.idx[NB1 / "bone.lu"],
                    self.edit, "-o", target)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("read-only", r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stdout + r.stderr)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in game.iterdir()), ["bone.lu"])
        finally:
            target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_where_searches_subfolders_but_not_backups(self):
        # a game folder keeps its containers in lu\; Seam Ripper's own
        # backups under .seamripper are .lu files too and must not count
        game = self.tmp / "game"
        for sub in ("lu", ".seamripper/backups"):
            (game / sub).mkdir(parents=True)
        for p in self.idx:
            shutil.copyfile(p, game / "lu" / p.name)
        shutil.copyfile(NB1 / "beartrap.lu", game / ".seamripper/backups/beartrap.lu")
        r = run("where", game, game / "lu" / "bone.lu", "--index",
                self.idx[NB1 / "bone.lu"], "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        found = [Path(c["container"]) for c in json.loads(r.stdout)["copies"]]
        self.assertEqual(found, [game / "lu" / "beartrap.lu"])

    @unittest.skipUnless(have_verifier, "lzxverify not built")
    def test_also_ships_identical_and_refuses_different(self):
        out = self.tmp / "out"
        mod = self.tmp / "bone_mod.lu"
        r = run("ship", NB1 / "bone.lu", "--index", self.idx[NB1 / "bone.lu"],
                self.edit, "-o", mod)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("ship", NB1 / "bone.lu", "--index", self.idx[NB1 / "bone.lu"],
                self.edit, "-o", out, "--also", NB1 / "beartrap.lu", mod,
                GLOBAL, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        status = {Path(t["container"]).name: t["status"] for t in rep["targets"]}
        self.assertEqual(status, {"bone.lu": "shipped", "beartrap.lu": "shipped",
                                  "bone_mod.lu": "refused", "global.lu": "refused"})
        self.assertEqual((out / "bone.lu").read_bytes(), mod.read_bytes())
        self.assertIn("different version", next(
            t["reason"] for t in rep["targets"] if t["container"] == str(mod)))
        single = self.tmp / "beartrap_single.lu"
        run("ship", NB1 / "beartrap.lu", "--index", self.idx[NB1 / "beartrap.lu"],
            self.edit, "-o", single)
        self.assertEqual((out / "beartrap.lu").read_bytes(), single.read_bytes())


@unittest.skipUnless(PIP.exists(), "retail PiP global.lu not available")
class PipShip(Scratch):
    def test_noop_and_preview_budget(self):
        src = self.read(PIP, 123, "camera.lua")
        out = self.tmp / "o.lu"
        r = run("ship", PIP, "--index", 123, src, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        import pip_scripts
        from naughty_lu import LuFile
        a, b = LuFile(str(PIP)), LuFile(str(out))
        self.assertEqual(pip_scripts.parse_script_chunk(bytes(a.chunk(a.records[123]))),
                         pip_scripts.parse_script_chunk(bytes(b.chunk(b.records[123]))))
        r = run("ship", PIP, "--index", 123, src, "--preview", "--json")
        rep = json.loads(r.stdout)
        (bud,) = rep["targets"][0]["budget"]
        self.assertTrue(bud["fits"])
        self.assertEqual(bud["original"], bud["edited"])

    @unittest.skipUnless(LUAC.exists(), "luac not available")
    def test_missing_end_points_at_line(self):
        src = self.read(PIP, 123, "camera.lua")
        text = src.read_text(encoding="utf-8")
        bad = self.tmp / "cam.lua"
        bad.write_text(text.replace("end\n", "", 1), encoding="utf-8", newline="\n")
        r = run("ship", PIP, "--index", 123, bad, "-o", self.tmp / "o.lu")
        self.assertEqual(r.returncode, 1)
        m = SR_ERROR.search(r.stderr)
        self.assertEqual((Path(m.group(1)), m.group(3)), (bad, "syntax"))
        self.assertGreater(int(m.group(2)), 0)
        self.assertFalse((self.tmp / "o.lu").exists())


if __name__ == "__main__":
    unittest.main()
