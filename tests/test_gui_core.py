"""Tests for the GUI's Qt-free parts: themes, project detection, script text helpers."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sr_gui import backend, changes, luahelp, project, settings, themes  # noqa: E402

LIST_OUT = """global.lu: Naughty Bear (x36, compiled bytecode)
58 script(s)

   index  name                                         size  form      hash
     310  achievements                                11113  bytecode  0xd1227efe
       2  camera                                        576  bytecode  0x3b1cee05
"""

SRC = """-- seam ripper: decompiled by nbdec (keep this line)
HIGH = 4
function NPC:Init()
  self.threatLevel = 10.0
end
function NPC:Update(dt)
  self:CheckFear(dt)
end
"""


class ThemeTests(unittest.TestCase):
    def test_every_theme_is_readable(self):
        for key, t in themes.THEMES.items():
            with self.subTest(theme=key):
                self.assertEqual(themes.check(t), [])

    def test_themes_have_the_same_keys(self):
        keys = set(themes.THEMES["light"])
        for key, t in themes.THEMES.items():
            self.assertEqual(set(t), keys, key)

    def test_system_follows_the_os(self):
        self.assertEqual(themes.resolve("system", True), "dark")
        self.assertEqual(themes.resolve("system", False), "light")
        self.assertEqual(themes.resolve("naughty", False), "naughty")
        self.assertEqual(themes.resolve("no-such-theme", True), "dark")

    def test_choices_start_with_system(self):
        ch = themes.theme_choices()
        self.assertEqual(ch[0][0], "system")
        self.assertEqual([k for k, _ in ch[1:]], list(themes.THEMES))

    def test_contrast_math(self):
        self.assertAlmostEqual(themes.contrast("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(themes.contrast("#777777", "#777777"), 1.0)


class ProjectTests(unittest.TestCase):
    def test_detect_game_from_headers(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.lu").write_bytes(b"\x03x36" + b"\0" * 20)
            (d / "b.lu").write_bytes(b"\x03x36" + b"\0" * 20)
            (d / "c.lu").write_bytes(b"\x05LUH" + b"\0" * 20)
            (d / "notes.txt").write_text("x")
            self.assertEqual(project.detect_game(d), "nb1")
            self.assertEqual(project.container_game(d / "c.lu"), "pip")
            self.assertIsNone(project.container_game(d / "notes.txt"))
            p = project.Project(d)
            self.assertEqual((p.game_name, p.badge), ("Naughty Bear", "NB1"))
            self.assertEqual(len(p.files()), 3)

    def test_pip_folder_and_hidden_state_folder(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "g.lu").write_bytes(b"\x05LUH" + b"\0" * 20)
            (d / ".seamripper").mkdir()
            (d / ".seamripper" / "staged.lu").write_bytes(b"\x03x36")
            p = project.Project(d)
            self.assertEqual(p.game, "pip")
            self.assertEqual([f.name for f in p.files()], ["g.lu"])

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as d:
            p = project.Project(d)
            self.assertIsNone(p.game)
            self.assertEqual(p.badge, "?")


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_recent(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["SEAMRIPPER_HOME"] = d
            try:
                s = settings.load_settings()
                self.assertEqual(s["theme"], "system")
                for i in range(12):
                    settings.add_recent(s, f"C:/g{i}")
                settings.add_recent(s, "C:/g3")
                self.assertEqual(s["recent"][0], "C:/g3")
                self.assertEqual(len(s["recent"]), settings.RECENT_MAX)
                self.assertEqual(len(set(s["recent"])), len(s["recent"]))
                settings.project_options(s, "C:/g3")["ship_to"] = "X"
                s["theme"] = "naughty"
                settings.save_settings(s)
                again = settings.load_settings()
                self.assertEqual(again["theme"], "naughty")
                self.assertEqual(again["projects"]["C:/g3"]["ship_to"], "X")
            finally:
                del os.environ["SEAMRIPPER_HOME"]


class LuaHelpTests(unittest.TestCase):
    def test_parse_list(self):
        header, scripts = luahelp.parse_list(LIST_OUT)
        self.assertTrue(header.startswith("global.lu: Naughty Bear"))
        self.assertEqual([(s.index, s.name, s.form, s.hash) for s in scripts],
                         [(310, "achievements", "bytecode", "0xd1227efe"),
                          (2, "camera", "bytecode", "0x3b1cee05")])

    def test_outline_and_changed_functions(self):
        names = [n for n, _l, _b in luahelp.functions(SRC)]
        self.assertEqual(names, ["NPC:Init", "NPC:Update"])
        new = SRC.replace("10.0", "20.0")
        self.assertEqual(luahelp.changed_functions(SRC, new), ["NPC:Init"])
        self.assertEqual(luahelp.changed_functions(SRC, SRC), [])
        added = SRC + "function NPC:New()\nend\n"
        self.assertEqual(luahelp.changed_functions(SRC, added), ["NPC:New"])
        top = SRC.replace("HIGH = 4", "HIGH = 9")
        self.assertEqual(luahelp.changed_functions(SRC, top), [])

    def test_changed_lines(self):
        new = SRC.replace("10.0", "20.0")
        self.assertEqual(luahelp.changed_lines(SRC, new), {4})
        self.assertEqual(luahelp.changed_lines(SRC, SRC), set())

    def test_diffs(self):
        new = SRC.replace("10.0", "20.0")
        text = "".join(luahelp.unified_diff(SRC, new, "npc"))
        self.assertIn("-  self.threatLevel = 10.0", text)
        self.assertIn("+  self.threatLevel = 20.0", text)
        rows = luahelp.side_by_side(SRC, new)
        self.assertEqual([r[4] for r in rows].count("chg"), 1)
        self.assertEqual(rows[0][4], "same")

    def test_error_lines(self):
        out = ("baseline backend: nbdec\nsource failed to compile:\n"
               "C:\\x\\luac51.exe: C:\\tmp\\ship_ab\\edit.lua:9: unexpected symbol near '='\n")
        self.assertEqual(luahelp.parse_errors(out), [(9, "unexpected symbol near '='")])
        self.assertEqual(luahelp.parse_errors("all fine"), [])


class ChangeSetTests(unittest.TestCase):
    def test_drafts_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["SEAMRIPPER_HOME"] = d
            try:
                cs = changes.ChangeSet("C:/game")
                fired = []
                cs.listeners.append(lambda: fired.append(1))
                dr = changes.Draft("C:/game/a.lu", 5, "npc", "bytecode", "nb1", SRC)
                cs.update(dr)
                self.assertEqual(cs.count(), 0)              # unchanged: not pending
                dr.text = SRC.replace("10.0", "20.0")
                cs.update(dr)
                self.assertEqual(cs.count(), 1)
                self.assertEqual(cs.containers(), {"C:/game/a.lu"})
                self.assertEqual(list(cs.by_container()), ["C:/game/a.lu"])
                self.assertEqual(cs.by_container(only=set()), {})
                cs.save()
                again = changes.ChangeSet("C:/game")
                self.assertEqual(again.count(), 1)
                self.assertEqual(again.get(("C:/game/a.lu", 5)).text, dr.text)
                dr.text = SRC
                cs.update(dr)
                self.assertEqual(cs.count(), 0)
                cs.save()
                self.assertEqual(changes.ChangeSet("C:/game").count(), 0)
                self.assertTrue(len(fired) >= 3)
            finally:
                del os.environ["SEAMRIPPER_HOME"]


class FakeProject:
    def __init__(self, folder):
        self.folder = Path(folder)


class BackendTests(unittest.TestCase):
    S = {"python": "python", "luac": "l", "jar": "j", "decompiler": "luadec"}

    def test_unwired_features_say_so(self):
        for fn, args in ((backend.texture_replace, (None, "a", "b", "c")),):
            with self.assertRaises(backend.NotAvailable) as cm:
                fn(*args)
            self.assertIn("not available yet", str(cm.exception))

    def test_ship_writes_in_place_or_to_the_ship_to_folder(self):
        s = dict(self.S, projects={})
        p = FakeProject("C:/game")
        plan = backend.plan_output(p, s, "C:/game/global.lu")
        self.assertTrue(plan.in_place)
        self.assertEqual(plan.out, Path("C:/game/global.lu"))
        s["projects"][str(p.folder)] = {"ship_to": "D:/build/assets"}
        plan = backend.plan_output(p, s, "C:/game/global.lu")
        self.assertFalse(plan.in_place)
        self.assertEqual(plan.out, Path("D:/build/assets/global.lu"))

    def test_compile_notes_are_parsed_once_each(self):
        line = "  note: line 98: 0.0 is stored as an integer, not a decimal: same function"
        got = backend.parse_notes("", "baseline backend: nbdec\n" + line + "\n")
        self.assertEqual(got, [{"line": 98, "message": line.split(": ", 2)[2]}])
        self.assertEqual(backend.parse_notes(line, line), got)
        self.assertEqual(backend.parse_notes("no notes here", ""), [])

    def test_ship_argv(self):
        a = backend.ship_argv(self.S, "a.lu", [(3, "x.lua"), (9, "y.lua")], "a.lu")
        self.assertEqual(a[a.index("--backend") + 1], "auto")      # whatever the setting says
        self.assertEqual([a[i + 1] for i, v in enumerate(a) if v == "--edit"],
                         ["3=x.lua", "9=y.lua"])
        self.assertIn("--json", a)
        self.assertNotIn("--preview", a)
        b = backend.ship_argv(self.S, "a.lu", [(3, "x.lua")], "out", also=["b.lu", "c.lu"],
                              force=True, preview=True)
        self.assertEqual(b[b.index("--also") + 1:b.index("--also") + 3], ["b.lu", "c.lu"])
        self.assertIn("--force", b)
        self.assertIn("--preview", b)
        r = backend.read_argv(self.S, "a.lu", 3, "o.lua")
        self.assertEqual(r[r.index("--backend") + 1], "luadec")
        w = backend.where_argv(self.S, "folder", "a.lu", "npc", 3)
        self.assertEqual(w[2:], ["where", "folder", "a.lu", "npc", "--index", "3", "--json"])

    def test_parse_results(self):
        out = ('log line\n{"ok": false, "errors": [{"file": "e.lua", "line": 2, '
               '"kind": "syntax", "message": "bad"}]}')
        self.assertEqual(backend.parse_json(out)["ok"], False)
        self.assertEqual(backend.parse_errors(out)[0]["line"], 2)
        err = 'x\nSR-ERROR file="C:\\a b\\my edit.lua" line=7 kind=stale: too different\n'
        e = backend.parse_errors("", err)[0]
        self.assertEqual((e["file"], e["line"], e["kind"], e["message"]),
                         ("C:\\a b\\my edit.lua", 7, "stale", "too different"))
        self.assertIsNone(backend.parse_json("no json here"))

    def test_friendly_messages_and_force(self):
        text, can = backend.friendly({"kind": "stale", "message": "m"})
        self.assertTrue(can)
        self.assertIn("Re-read", text)
        self.assertTrue(backend.friendly({"kind": "syntax", "message": "m"}, "pip")[1])
        self.assertFalse(backend.friendly({"kind": "syntax", "message": "m"}, "nb1")[1])
        self.assertTrue(backend.friendly({"kind": "structure", "message": "m"}, "pip")[1])
        self.assertFalse(backend.friendly({"kind": "baseline", "message": "m"})[1])
        self.assertIn("not your edit's fault", backend.friendly({"kind": "baseline", "message": "m"})[0])

    def test_backups_list_and_revert_through_sr_backup(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            f = d / "a.lu"
            f.write_bytes(b"retail bytes")
            backend.backup_before_overwrite(f)
            f.write_bytes(b"modded bytes")
            rows = backend.backups_list(FakeProject(d))
            self.assertEqual([(r["file"], r["state"], r["previous"]) for r in rows],
                             [("a.lu", "modified", 0)])
            self.assertEqual(backend.modified_files(FakeProject(d)), {str(f)})
            backend.revert_to_retail(f)
            self.assertEqual(f.read_bytes(), b"retail bytes")
            self.assertEqual(backend.backups_list(FakeProject(d))[0]["state"], "retail")
            backend.restore_previous(f)                       # steps back to the modded copy
            self.assertEqual(f.read_bytes(), b"modded bytes")
            res = backend.revert_all(FakeProject(d))
            self.assertFalse(any(r.get("error") for r in res))
            self.assertEqual(f.read_bytes(), b"retail bytes")


class ChangeSetChecksTests(unittest.TestCase):
    def test_unchecked_items_are_left_out(self):
        cs = changes.ChangeSet()
        d = changes.Draft("a.lu", 1, "n", "bytecode", "nb1", "x", "y")
        cs.update(d)
        fired = []
        cs.listeners.append(lambda: fired.append(1))
        cs.set_checked(d.key, False)
        self.assertIn(d.key, cs.unchecked)
        cs.set_checked(d.key, True)
        self.assertEqual(cs.unchecked, set())
        cs.set_checked(d.key, False)
        cs.discard(d.key)
        self.assertEqual(cs.unchecked, set())
        self.assertEqual(len(fired), 4)


class FeatureBackend(unittest.TestCase):
    S = {"python": "python", "luac": "l", "jar": "j", "decompiler": "luadec"}

    def build(self, root):
        lu = Path(root) / "build" / "assets" / "lu"
        lu.mkdir(parents=True)
        (lu.parent.parent / "restuff.exe").write_bytes(b"MZ")
        return lu

    def test_search_argv_keeps_the_query_last_even_if_it_looks_like_an_option(self):
        a = backend.search_argv(self.S, "C:/game", "--foo", regex=True, case=True, limit=50)
        self.assertEqual(a[-2:], ["--", "--foo"])
        self.assertTrue(a[1].endswith("sr_search.py"))
        self.assertEqual(a[a.index("--limit") + 1], "50")
        self.assertIn("--regex", a)
        self.assertIn("--case", a)
        self.assertNotIn("--regex", backend.search_argv(self.S, "C:/game", "x"))

    def test_parse_search_line(self):
        self.assertEqual(backend.parse_search_line('{"type": "hit", "line": 3}\n')["line"], 3)
        for bad in ("", "  [1/4] a.lu: read", "{broken", "[1]", '{"no": "type"}'):
            self.assertIsNone(backend.parse_search_line(bad))

    def test_require_build(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(backend.NoBuild):
                backend.require_build({})
            with self.assertRaisesRegex(backend.NoBuild, "restuff.exe"):
                backend.require_build({"restuff_build": d})
            lu = self.build(d)
            got = backend.require_build({"restuff_build": str(lu.parent.parent)})
            self.assertEqual(Path(got["lu"]), lu)
            self.assertEqual(backend.build_check("")[0], None)
            self.assertEqual(backend.build_check(str(d))[1].startswith("no restuff.exe"), True)

    def test_install_shipped_copies_only_what_is_not_already_in_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            lu = self.build(d)
            (lu / "global.lu").write_bytes(b"retail")
            (lu / "area1.lu").write_bytes(b"retail area")
            ship = Path(d) / "ship"
            ship.mkdir()
            (ship / "global.lu").write_bytes(b"modded")
            s = {"restuff_build": str(lu.parent.parent)}
            got = backend.install_shipped(s, [ship / "global.lu", lu / "area1.lu",
                                              ship / "global.lu"])
            self.assertEqual([r["file"] for r in got["installed"]], ["global.lu"])
            self.assertEqual(got["in_place"], ["area1.lu"])
            self.assertEqual((lu / "global.lu").read_bytes(), b"modded")
            self.assertEqual((lu / "area1.lu").read_bytes(), b"retail area")
            self.assertEqual(backend.build_modified(s), ["global.lu"])
            self.assertEqual(backend.build_revert(s), ["global.lu"])
            self.assertEqual((lu / "global.lu").read_bytes(), b"retail")
            self.assertEqual(backend.build_modified(s), [])

    def test_hash_lookup_texts(self):
        r = backend.hash_lookup("DetectThreat")
        self.assertEqual((r["kind"], r["copy"], r["copy2"]), ("name", "0x4342e44f", "1128457295"))
        self.assertIn("0x4342e44f", r["text"])
        r = backend.hash_lookup("0x4342e44f")
        self.assertEqual((r["kind"], r["known"], r["copy"]), ("hash", True, "DetectThreat"))
        r = backend.hash_lookup("0x00000001")
        self.assertEqual((r["known"], r["copy"]), (False, ""))
        self.assertIn("unknown hash", r["text"])
        self.assertEqual(backend.hash_lookup("0xfffffffff")["kind"], "bad")
        self.assertEqual(backend.hash_lookup("")["text"], "")


if __name__ == "__main__":
    unittest.main()
