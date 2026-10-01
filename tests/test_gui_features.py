"""GUI wiring for Launch, Ship && launch, hash lookup and folder-wide script search.
Everything runs on temp folders with a fake restuff.exe and a fake popen: nothing starts."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_support import HAVE_QT, GuiCase, pump  # noqa: E402
from test_sr_search import scripts_lu  # noqa: E402

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

NB1_HEAD = b"\x03x36" + b"\0" * 64


class FakePopen:
    calls = []

    def __init__(self, argv, **kw):
        FakePopen.calls.append((argv, kw))
        self.pid = 777


class Feature(GuiCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.build = self.tmp / "build"
        self.lu = self.build / "assets" / "lu"
        self.lu.mkdir(parents=True)
        (self.build / "restuff.exe").write_bytes(b"MZ fake")
        (self.lu / "global.lu").write_bytes(b"retail global")
        self.ship = self.tmp / "ship"
        self.ship.mkdir()
        (self.ship / "global.lu").write_bytes(b"modded global")
        self.game = self.tmp / "game"
        self.game.mkdir()
        (self.game / "a.lu").write_bytes(NB1_HEAD)
        FakePopen.calls = []
        old = self.backend.POPEN
        self.backend.POPEN = FakePopen
        self.addCleanup(setattr, self.backend, "POPEN", old)
        self.w = self.window()
        self.w.settings["restuff_build"] = ""             # settings may carry over from a test
        self.w.open_project(str(self.game))

    def use_build(self, folder=None):
        self.w.settings["restuff_build"] = str(folder or self.build)

    def banner(self):
        return self.w.banner.text.text()


class Launch(Feature):
    def test_needs_a_build_folder(self):
        self.w.launch()
        self.assertIn("restuff build folder", self.banner())
        self.assertEqual(FakePopen.calls, [])

    def test_a_bad_folder_says_why(self):
        self.use_build(self.tmp / "nowhere")
        self.w.launch()
        self.assertIn("restuff.exe", self.banner())
        self.assertEqual(FakePopen.calls, [])

    def test_starts_restuff_with_the_log_argument(self):
        self.use_build()
        self.w.launch()
        argv, kw = FakePopen.calls[0]
        self.assertEqual(argv, [str(self.build / "restuff.exe"), "--log_file",
                                str(self.build / "restuff_log.txt")])
        self.assertEqual(kw["cwd"], str(self.build))
        self.assertIn("restuff_log.txt", self.banner())
        self.assertIn("restuff_crash.txt", self.banner())

    def test_panic_in_paradise_is_refused(self):
        self.use_build()
        (self.game / "a.lu").write_bytes(scripts_lu(("x", "a = 1\n")))
        self.w.open_project(str(self.game))
        self.w.launch()
        self.assertIn("Naughty Bear only", self.banner())
        self.assertEqual(FakePopen.calls, [])

    def test_ship_and_launch_stops_before_shipping_without_a_build(self):
        self.assertFalse(self.w.launch_ready())
        self.assertIn("restuff build folder", self.banner())


class ShipAndLaunch(Feature):
    def install(self, paths):
        self.w.review._install_and_launch([str(p) for p in paths], "Shipped 1 script.",
                                          "ok", [])
        self.assertTrue(pump(lambda: "Started the game" in self.banner()
                             or "not started" in self.banner()
                             or "did not start" in self.banner(), 30))

    def test_installs_exactly_the_shipped_files_then_starts(self):
        self.use_build()
        (self.lu / "area1.lu").write_bytes(b"retail area1")
        self.install([self.ship / "global.lu"])
        self.assertEqual((self.lu / "global.lu").read_bytes(), b"modded global")
        self.assertEqual((self.lu / "area1.lu").read_bytes(), b"retail area1")
        self.assertIn("Installed in the build: global.lu", self.banner())
        self.assertEqual(FakePopen.calls[0][0][1], "--log_file")
        self.assertEqual(self.backend.build_modified(self.w.settings), ["global.lu"])

    def test_project_folder_is_the_build_folder_skips_the_copy(self):
        self.use_build()
        self.install([self.lu / "global.lu"])
        self.assertEqual((self.lu / "global.lu").read_bytes(), b"retail global")
        self.assertIn("not copied: global.lu", self.banner())
        self.assertFalse((self.lu / ".seamripper").exists())
        self.assertEqual(len(FakePopen.calls), 1)

    def test_a_failed_install_does_not_start_the_game(self):
        self.use_build()
        (self.ship / "typo.lu").write_bytes(b"x")
        self.install([self.ship / "typo.lu"])
        self.assertIn("could not install", self.banner())
        self.assertEqual(FakePopen.calls, [])
        self.assertEqual([p.name for p in self.lu.glob("*.lu")], ["global.lu"])

    def test_history_reverts_the_build(self):
        self.use_build()
        self.install([self.ship / "global.lu"])
        h = self.w.history
        h.refresh()
        self.assertIn("1 file(s)", h.build_note.text())
        self.assertTrue(h.b_build.isEnabled())
        self.w._confirm = lambda *_a: True
        self.w.revert_build()
        self.assertEqual((self.lu / "global.lu").read_bytes(), b"retail global")
        self.assertIn("originals", h.build_note.text())
        self.assertFalse(h.b_build.isEnabled())

    def test_history_hides_the_build_row_without_a_build(self):
        self.w.history.refresh()
        self.assertTrue(self.w.history.b_build.isHidden())


class SettingsPlay(Feature):
    def test_validates_with_sr_launch_locate(self):
        from sr_gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.w.ctx, self.w, "Play")
        self.addCleanup(dlg.close)
        dlg.build.edit.setText(str(self.build))
        self.assertIn("Found restuff.exe", dlg.build_state.text())
        dlg.build.edit.setText(str(self.tmp))
        self.assertIn("no restuff.exe", dlg.build_state.text())
        dlg.build.edit.setText("")
        self.assertIn("Not set", dlg.build_state.text())
        dlg.build.edit.setText(str(self.build))
        dlg.accept()
        self.assertEqual(self.w.settings["restuff_build"], str(self.build))


class HashBox(Feature):
    def test_name_shows_its_hash_and_copies_it(self):
        self.w.hash_edit.setText("DetectThreat")
        self.assertIn("0x4342e44f", self.w.hash_result.text())
        self.w.hash_copy.click()
        self.assertEqual(QGuiApplication.clipboard().text(), "0x4342e44f")
        self.w.hash_copy2.click()
        self.assertEqual(QGuiApplication.clipboard().text(), "1128457295")

    def test_hash_shows_its_name(self):
        self.w.hash_edit.setText("0x4342E44F")
        self.assertIn("DetectThreat", self.w.hash_result.text())
        self.w.hash_copy.click()
        self.assertEqual(QGuiApplication.clipboard().text(), "DetectThreat")

    def test_unknown_hash_says_so(self):
        self.w.hash_edit.setText("0x00000001")
        self.assertIn("unknown hash", self.w.hash_result.text())
        self.assertTrue(self.w.hash_copy.isHidden())

    def test_not_a_hash_and_empty(self):
        self.w.hash_edit.setText("0x1ffffffff")
        self.assertIn("not a 32-bit hash", self.w.hash_result.text())
        self.w.hash_edit.setText("")
        self.assertEqual(self.w.hash_result.text(), "")


class Search(Feature):
    def setUp(self):
        super().setUp()
        (self.game / "a.lu").unlink()
        (self.game / "lu").mkdir()
        (self.game / "uh").mkdir()
        (self.game / ".seamripper" / "backups").mkdir(parents=True)
        (self.game / "lu" / "a.lu").write_bytes(scripts_lu(
            ("alpha", "x = 1\nfunction Fear()\n  return x + 2\nend\n"),
            ("shared", "function Shared()\n  return 1\nend\n")))
        (self.game / "uh" / "a.lu").write_bytes(scripts_lu(
            ("beta", "-- FEAR in caps\ny = 10\n"), ("shared", "function Shared()\n  return 1\nend\n")))
        (self.game / ".seamripper" / "backups" / "a.lu").write_bytes(scripts_lu(
            ("old", "fear = 0\n")))
        self.w.open_project(str(self.game))
        self.sb = self.w.search_sb
        self.opened = []
        self.w.open_script = lambda lu, index, line=None: self.opened.append((lu, index, line))

    def search(self, text, regex=False, case=False):
        self.sb.query.setText(text)
        self.sb.regex.setChecked(regex)
        self.sb.case.setChecked(case)
        self.sb.run()
        self.assertTrue(pump(lambda: not self.sb.run_.running(), 120))

    def tops(self):
        t = self.sb.results
        return [t.topLevelItem(i) for i in range(t.topLevelItemCount())]

    def test_lists_container_script_line_and_skips_hidden_folders(self):
        self.search("fear")
        tops = self.tops()
        self.assertEqual([t.text(0).split()[0] for t in tops], ["lu/a.lu", "uh/a.lu"])
        script = tops[0].child(0)
        self.assertEqual(script.text(0), "alpha")
        self.assertIn("function Fear()", script.child(0).text(0))
        self.assertEqual(script.child(0).text(0).split()[0], "2")
        self.assertIn("2 match(es) in 2 script(s)", self.sb.note.text())
        self.assertEqual(self.sb.go.text(), "Search")

    def test_click_opens_the_script_at_that_line(self):
        self.search("return x")
        line = self.tops()[0].child(0).child(0)
        self.sb._open(line)
        lu, index, ln = self.opened[0]
        self.assertEqual(Path(lu), self.game / "lu" / "a.lu")
        self.assertEqual((index, ln), (0, 3))

    def test_identical_copies_are_noted_once(self):
        self.search("Shared")
        self.assertEqual(len(self.tops()), 1)
        self.assertIn("identical copy", self.tops()[0].child(0).text(0))

    def test_regex_and_case(self):
        self.search(r"^function \w+\(\)$", regex=True)
        self.assertIn("2 match(es)", self.sb.note.text())
        self.search("FEAR", case=True)
        self.assertEqual([t.text(0).split()[0] for t in self.tops()], ["uh/a.lu"])

    def test_bad_regex_and_empty_query_never_start(self):
        self.sb.query.setText("(")
        self.sb.regex.setChecked(True)
        self.sb.run()
        self.assertFalse(self.sb.run_.running())
        self.assertIn("not a valid regular expression", self.sb.note.text())
        self.sb.query.setText("  ")
        self.sb.run()
        self.assertIn("Type what to look for", self.sb.note.text())

    def test_no_matches(self):
        self.search("zzzzqqq")
        self.assertEqual(self.sb.note.text(), "No matches.")

    def test_cancel_stops_it_and_keeps_the_window_usable(self):
        self.sb.query.setText("fear")
        self.sb.run()
        self.assertTrue(self.sb.run_.running())
        self.assertEqual(self.sb.go.text(), "Cancel")
        self.sb.run()
        self.assertFalse(self.sb.run_.running())
        self.assertIn("Cancelled", self.sb.note.text())
        self.assertEqual(self.sb.go.text(), "Search")
        self.assertTrue(self.sb.query.isEnabled())

    def test_a_new_project_clears_the_results(self):
        self.search("fear")
        self.w.open_project(str(self.game))
        self.assertEqual(self.tops(), [])
        self.assertEqual(self.sb.note.text(), "")


if __name__ == "__main__":
    unittest.main()
