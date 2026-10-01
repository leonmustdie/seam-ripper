"""Offscreen smoke tests for the GUI: window, rail, themes, tools, runner, and a
real read/check/ship of one Naughty Bear script (skipped without the game files)."""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication, QLabel
    HAVE_QT = True
except ImportError:                                     # pragma: no cover
    HAVE_QT = False

CANDIDATES = [Path(r"D:\testingenvironment\initialnb1files\lu"), Path(r"C:\Users\slmw0\Fuck\uh")]
PIP = Path(r"C:\Users\slmw0\Fuck\pip_full")
GAME = next((p for p in CANDIDATES if (p / "global.lu").exists()), None)


def pump(cond, timeout=90):
    end = time.time() + timeout
    app = QApplication.instance()
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 30)
        if cond():
            return True
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        os.environ["SEAMRIPPER_HOME"] = cls.home.name
        cls.app = QApplication.instance() or QApplication([])
        from sr_gui import backend, mainwindow
        cls.backend, cls.mw = backend, mainwindow

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SEAMRIPPER_HOME", None)
        cls.home.cleanup()

    def window(self):
        w = self.mw.Main()
        self.addCleanup(w.close)
        w.show()
        return w

    def idle(self, w):
        self.assertTrue(pump(lambda: not w.runner.busy()))


class WindowTests(GuiCase):
    def test_opens_on_the_welcome_page_and_switches_everything(self):
        from sr_gui import style, themes
        w = self.window()
        self.assertEqual(w.root_stack.currentIndex(), 0)
        for i in range(6):
            w.select_rail(i)
            self.app.processEvents()
        for key in w.theme_actions:
            w.set_theme(key)
            self.app.processEvents()
            resolved = themes.resolve(key, style.system_is_dark())
            want = themes.THEMES[resolved]["window"].lower()
            self.assertEqual(self.app.palette().window().color().name().lower(), want)
        self.assertEqual(w.settings["theme"], list(w.theme_actions)[-1])
        self.assertGreaterEqual(len(themes.THEMES), 5)

    def test_a_folder_without_containers_is_refused(self):
        w = self.window()
        with tempfile.TemporaryDirectory() as d:
            w.open_project(d)
        self.assertEqual(w.root_stack.currentIndex(), 0)
        self.assertTrue(w.banner.isVisible())

    def test_project_with_stubbed_features_says_not_available(self):
        w = self.window()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.lu").write_bytes(b"\x03x36" + b"\0" * 64)
            (Path(d) / "sub").mkdir()
            (Path(d) / "sub" / "b.lu").write_bytes(b"\x03x36" + b"\0" * 64)
            w.open_project(d)
            self.assertEqual(w.root_stack.currentIndex(), 1)
            self.assertEqual(w.badge.text(), "NB1")
            self.assertEqual(len(w.files_sb.items), 2)
            w.files_sb.filter.setText("b.lu")
            self.assertTrue(w.files_sb.items[str(Path(d) / "a.lu")].isHidden())
            w.files_sb.filter.setText("")
            w.select_rail(4)
            self.assertIn("No files have been changed yet", w.history.note.text())
            w.hash_edit.setText("CSmoke02")
            self.assertIn("0x", w.hash_result.text())
            w.launch()
            self.assertIn("restuff build folder", w.banner.text.text())
            w.patches.make()
            self.assertIn("Tick at least one change", w.banner.text.text())
            self.assertEqual(w.ctx.changes.count(), 0)
            self.assertEqual(w.changes_btn.text(), "Changes (0)")

    def test_every_tool_is_reachable_and_builds_a_command(self):
        from sr_gui import toolspecs
        from sr_gui.widgets import ToolForm
        w = self.window()
        titles = [t["title"] for t in toolspecs.TOOLS]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertTrue(all(t["group"] in toolspecs.GROUPS for t in toolspecs.TOOLS))
        for spec in toolspecs.TOOLS:
            self.assertTrue((ROOT / "tools" / spec["script"]).exists(), spec["script"])
            w.open_tool(spec["title"])
            self.assertIn(spec["title"], w.tools_page.forms)
            form = ToolForm(spec, w.ctx)
            if any(f.get("required") for f in spec["fields"]):
                self.assertIsNone(form.argv(), spec["title"])   # asks for what is missing
        # the old tabs' features are all still there
        for old in ("Export strings", "Import strings", "Spelling report", "Spelling fix",
                    "Search text", "Find a script", "Extract chunks",
                    "Convert textures and models", "Character model (GLB)",
                    "Menu movies (Panic in Paradise)", "Dump a whole game (Panic in Paradise)",
                    "Extract Panic in Paradise source", "Inject Panic in Paradise script",
                    "Sound banks", "Sound streams", "Container info", "Decompress image",
                    "Repack raw image"):
            self.assertIn(old, titles)

    def test_tools_open_without_a_game_folder(self):
        w = self.window()
        self.assertIsNone(w.ctx.project)
        self.assertEqual(w.root_stack.currentIndex(), 0)       # welcome screen
        w.welcome.extract_disc.emit()
        self.assertEqual(w.root_stack.currentIndex(), 1)
        self.assertIn("Extract game disc (.iso)", w.tools_page.forms)

    def test_form_builds_the_same_command_line_as_before(self):
        from sr_gui import toolspecs
        from sr_gui.widgets import ToolForm
        w = self.window()
        form = ToolForm(toolspecs.find("Import strings"), w.ctx)
        rows = {f["label"]: wd for f, wd in form.widgets.values()}
        rows[".lu file"].set_value("a.lu")
        rows["Edited .txt"].set_value("e.txt")
        rows["Save as .lu"].set_value("o.lu")
        self.assertEqual(form.argv()[2:], ["apply", "a.lu", "e.txt", "-o", "o.lu", "--verify"])


class RunnerTests(GuiCase):
    def test_queue_runs_in_order_and_cancel_stops(self):
        w = self.window()
        done = []
        py = sys.executable
        w.runner.run([py, "-c", "print('one')"], on_done=lambda c, o, e: done.append(("1", c, o.strip())))
        w.runner.run([py, "-c", "print('two')"], on_done=lambda c, o, e: done.append(("2", c, o.strip())))
        self.assertTrue(w.runner.busy())
        self.idle(w)
        self.assertEqual(done, [("1", 0, "one"), ("2", 0, "two")])
        self.assertIn("run: ", w.log.box.toPlainText())          # exact command is logged
        done.clear()
        w.runner.run([py, "-c", "import time; time.sleep(60)"],
                     on_done=lambda c, o, e: done.append(c))
        w.runner.run([py, "-c", "print('never')"], on_done=lambda c, o, e: done.append("second"))
        pump(lambda: w.runner.job is not None and w.runner.proc is not None, 10)
        w.runner.cancel()
        self.idle(w)
        self.assertEqual(done, [-1])
        w.runner.run([py, "-c", "print('after')"], on_done=lambda c, o, e: done.append(o.strip()))
        self.idle(w)
        self.assertEqual(done[-1], "after")

    def test_a_missing_program_reports_and_moves_on(self):
        w = self.window()
        got = []
        w.runner.run(["definitely-not-a-program-xyz"], on_done=lambda c, o, e: got.append(c))
        self.idle(w)
        self.assertEqual(got, [-1])

    def test_side_run_clears_running_status(self):
        from sr_gui.runner import SideProc
        w = self.window()
        seen, done = [], []
        w.log.message.connect(lambda text, kind: seen.append(text))
        side = SideProc(w.log)
        for code in (0, 3):
            side.start([sys.executable, "-c", f"raise SystemExit({code})"],
                       lambda c, o, e: done.append(c))
            self.assertTrue(pump(lambda: len(done) == (1 if code == 0 else 2), 30))
            self.assertEqual(seen[-1], "done" if code == 0 else "failed (exit 3)")

    def test_show_commands_toggle(self):
        w = self.window()
        w.runner.run([sys.executable, "-c", "pass"])
        self.idle(w)
        self.assertIn("run: ", w.log.box.toPlainText())
        w.log.show_cmds.setChecked(False)
        self.assertNotIn("run: ", w.log.box.toPlainText())
        w.log.show_cmds.setChecked(True)
        self.assertIn("run: ", w.log.box.toPlainText())


class EditorTests(GuiCase):
    def test_editor_gutter_find_and_highlight(self):
        from sr_gui.editor import CodeEditor, FindBar
        ed = CodeEditor()
        ed.resize(600, 300)
        ed.show()
        src = '-- c\nlocal x = 20.0\nif x == HASH("Foo") then\n  y = 0x4342e44f\nend\n'
        ed.set_script(src)
        self.assertGreater(ed.gutter_width(), 20)
        ed.goto_line(3)
        self.assertEqual(ed.textCursor().blockNumber(), 2)
        ed.set_errors({2: "bad"})
        self.assertEqual(ed.error_at(2), "bad")
        fmts = ed.document().firstBlock().layout().formats()
        self.assertTrue(fmts)                                    # comment line is highlighted
        ed.setPlainText(src.replace("20.0", "30.0"))
        self.assertTrue(pump(lambda: 2 in ed.marked, 5))
        bar = FindBar(ed)
        bar.find.setText("x")
        bar.repl.setText("value")
        bar.replace_all()
        self.assertNotIn("local x", ed.toPlainText())
        self.assertIn("local value", ed.toPlainText())
        bar.regex.setChecked(True)
        bar.find.setText("(value) =")
        bar.repl.setText(r"\1 :=")
        bar.replace_all()
        self.assertIn("value :=", ed.toPlainText())


@unittest.skipUnless(GAME, "no Naughty Bear game files here")
class RealScriptTests(GuiCase):
    def open_script(self):
        w = self.window()
        w.open_project(str(GAME))
        self.assertEqual(w.ctx.project.game, "nb1")
        w.open_container(str(GAME / "global.lu"))
        sc = w.view.scripts
        self.assertTrue(pump(lambda: sc.list.count() > 0 and not w.runner.busy()))
        self.assertEqual(sc.list.count(), 58)
        target = next(s for s in sc.scripts if s.name == "characterclasses")
        sc.select_index(target.index)
        self.assertTrue(pump(lambda: sc.draft is not None and not w.runner.busy()))
        return w, sc

    def test_draft_survives_reopening_and_discard(self):
        w, sc = self.open_script()
        text = sc.editor.toPlainText()
        sc.editor.setPlainText(text.replace("VERY_HIGH = 5", "VERY_HIGH = 6"))
        self.assertEqual(w.ctx.changes.count(), 1)
        w.ctx.changes.save()
        from sr_gui.changes import ChangeSet
        self.assertEqual(ChangeSet(w.ctx.project.folder).count(), 1)
        sc.revert_script()
        self.assertEqual(w.ctx.changes.count(), 0)
        w.ctx.changes.save()
        self.assertEqual(ChangeSet(w.ctx.project.folder).count(), 0)

    def test_container_info_and_text_tabs(self):
        w = self.window()
        w.open_project(str(GAME))
        w.open_container(str(GAME / "global.lu"))
        self.idle(w)
        self.assertIn("Xbox 360", w.view.info.text.toPlainText())
        self.assertEqual(w.view.badge.text(), "Naughty Bear")
        self.assertIn("(58)", w.view.tabs.tabText(0))


@unittest.skipUnless((PIP / "global.lu").exists(), "no Panic in Paradise game files here")
class PipScriptTests(GuiCase):
    def test_pip_project_reads_a_plaintext_script(self):
        w = self.window()
        w.open_project(str(PIP))
        self.assertEqual((w.ctx.project.game, w.badge.text()), ("pip", "PiP"))
        self.assertFalse(w.launch_btn.isEnabled())              # launching is NB1 only
        w.open_container(str(PIP / "global.lu"))
        sc = w.view.scripts
        self.assertTrue(pump(lambda: sc.list.count() > 0 and not w.runner.busy()))
        target = next(s for s in sc.scripts if s.name == "aiglobal")
        sc.select_index(target.index)
        self.assertTrue(pump(lambda: sc.draft is not None and not w.runner.busy()))
        self.assertEqual(sc.draft.game, "pip")
        self.assertIn("function", sc.editor.toPlainText())
        sc.editor.setPlainText(sc.editor.toPlainText() + "\n-- note\n")
        shown = " ".join(lb.text() for lb in sc.checks_box.findChildren(QLabel))
        self.assertRegex(shown, r"-?\d+ bytes left of \d+")


if __name__ == "__main__":
    unittest.main()
