"""GUI wiring for backups, exact preview, other containers, multi-script ships, PiP
checks. Every ship, backup and revert here works on scratch copies of a container."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_support import (HAVE_QT, NB1, PIP, GuiCase, pump, scratch_project, sha)  # noqa: E402

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QMessageBox, QProgressBar, QTreeWidget

EDIT_FROM = "assert(p1 ~= nil,"
EDIT_TO = "assert(p1 ~= nil or true,"
NOTE_FROM, NOTE_TO = "if n < 0 then", "if n < 0.0 then"       # animationmgr in global.lu


def have(*names):
    return NB1 is not None and all((NB1 / n).exists() for n in names)


class NB1Case(GuiCase):
    def setUp(self):
        self.folder, tmp = scratch_project(NB1, ["global.lu"])
        self.addCleanup(tmp.cleanup)
        self.orig = sha(self.folder / "global.lu")
        self.w = self.window()
        self.sc = self.open_script(self.w, self.folder, "global.lu", "characterclasses")
        self.text = self.sc.editor.toPlainText()

    def edit_good(self):
        self.sc.editor.setPlainText(self.text.replace(EDIT_FROM, EDIT_TO, 1))

    def wait_preview(self, status="ok"):
        w = self.w
        w.select_rail(2)
        lu = str(self.folder / "global.lu")
        pl = w.planner
        self.assertTrue(pump(lambda: (lu in pl.previews and pl.previews[lu].status == status)
                             and not pl._side[lu].running(), 60))
        return pl.previews[lu]

    def wait_planner_idle(self, timeout=240):
        """Every preview and 'also in other containers' lookup for what is pending has
        finished, so nothing is competing with (or feeding) the ship that follows."""
        pl = self.w.planner
        drafts = pl.checked()

        def idle():
            return (not pl._timer.isActive() and not pl._where_proc.running()
                    and not pl._where_queue
                    and all(not p.running() for p in pl._side.values())
                    and all(d.lu in pl.previews and pl.previews[d.lu].status != "busy"
                            and d.key in pl.where and pl.where[d.key].status != "busy"
                            for d in drafts))
        self.assertTrue(pump(idle, timeout))


@unittest.skipUnless(have("global.lu"), "no Naughty Bear game files here")
class CheckAndBanner(NB1Case):
    def test_error_banner_clears_when_the_script_is_fixed(self):
        w, sc = self.w, self.sc
        lines = self.text.split("\n")
        lines[5] += " ="
        sc.editor.setPlainText("\n".join(lines))
        sc.check()
        self.idle(w)
        self.assertIn(6, sc.errors)
        self.assertTrue(w.banner.isVisibleTo(w))
        self.assertEqual(w.banner.property("kind"), "err")
        self.assertIn("line 6", w.banner.text.text())
        self.assertEqual(w.problems.count(), 1)
        # the error described the old text: editing takes it down
        sc.editor.setPlainText(self.text)
        self.assertEqual(sc.errors, {})
        self.assertFalse(w.banner.isVisibleTo(w))
        self.assertEqual(w.problems.count(), 0)
        # and a check that passes says so
        self.edit_good()
        sc.check()
        self.idle(w)
        self.assertEqual(w.banner.property("kind"), "ok")
        self.assertIn("passed", w.banner.text.text())
        self.assertIn("ClassBuilder:InitNPCClass", w.banner.text.text())
        self.assertEqual(sc.errors, {})

    def test_opening_another_script_clears_an_old_error_banner(self):
        w, sc = self.w, self.sc
        lines = self.text.split("\n")
        lines[5] += " ="
        sc.editor.setPlainText("\n".join(lines))
        sc.check()
        self.idle(w)
        self.assertTrue(w.banner.isVisibleTo(w))
        other = next(s for s in sc.scripts if s.name == "fearstates")
        sc.select_index(other.index)
        self.assertTrue(pump(lambda: sc.draft is not None and sc.draft.name == "fearstates"
                             and not w.runner.busy()))
        self.assertFalse(w.banner.isVisibleTo(w))


@unittest.skipUnless(have("global.lu"), "no Naughty Bear game files here")
class PreviewAndShip(NB1Case):
    def test_changes_page_shows_the_exact_preview(self):
        self.edit_good()
        pv = self.wait_preview()
        w = self.w
        d = w.ctx.changes.pending()[0]
        names = w.planner.function_names(d)
        self.assertEqual([n for n, _l in names], ["ClassBuilder:InitNPCClass"])
        shown = " ".join(lb.text() for lb in w.review.card_funcs.findChildren(QLabel))
        self.assertIn("ClassBuilder:InitNPCClass", shown)
        self.assertTrue(w.review.ship_btn.isEnabled())
        self.assertEqual(pv.errors, [])
        # the preview wrote nothing
        self.assertEqual(sha(self.folder / "global.lu"), self.orig)
        self.assertFalse((self.folder / ".seamripper").exists())

    def test_error_in_the_preview_blocks_ship(self):
        lines = self.text.split("\n")
        lines[5] += " ="
        self.sc.editor.setPlainText("\n".join(lines))
        pv = self.wait_preview("error")
        self.assertEqual(pv.errors[0][1]["line"], 6)
        w = self.w
        self.assertTrue(pump(lambda: not w.review.ship_btn.isEnabled(), 5))
        self.assertFalse(w.review.force_btn.isVisibleTo(w))     # a NB1 syntax error can't be forced
        self.assertIn("Line 6", w.review.note.text())

    def test_ship_in_place_backs_up_then_history_reverts(self):
        w = self.w
        self.edit_good()
        self.wait_preview()
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy()))
        live = self.folder / "global.lu"
        self.assertNotEqual(sha(live), self.orig)
        backup = self.folder / ".seamripper" / "backups" / "global.lu"
        self.assertEqual(sha(backup), self.orig)                # the untouched original
        self.assertEqual(w.ctx.changes.count(), 0)              # in the game now
        self.assertIn("backed up", w.banner.text.text())
        # the file shows as modified in the tree, and the script now reads with the edit
        self.assertIn(str(live).lower(), {p.lower() for p in w.files_sb.modified})
        w.open_script(str(live), self.sc.draft.index)
        self.assertTrue(pump(lambda: EDIT_TO in self.sc.editor.toPlainText()
                             and not w.runner.busy()))
        # History lists it; revert puts the retail bytes back
        w.select_rail(4)
        self.assertEqual([(r["file"], r["state"]) for r in w.history.rows],
                         [("global.lu", "modified")])
        self.assertEqual(w.history.table.rowCount(), 1)
        w.history.table.selectRow(0)
        with mock.patch.object(w, "_confirm", return_value=True):
            w.history.revert_one()
        self.assertEqual(sha(live), self.orig)
        self.assertEqual(w.history.rows[0]["state"], "retail")
        self.assertEqual(w.files_sb.modified, set())
        # restore previous brings the modded version back
        w.history.table.selectRow(0)
        with mock.patch.object(w, "_confirm", return_value=True):
            w.history.previous()
        self.assertNotEqual(sha(live), self.orig)

    def fake_build(self, root):
        """A restuff build folder (fake exe) with a game file to overwrite, and a fake popen."""
        lu = Path(root) / "build" / "assets" / "lu"
        lu.mkdir(parents=True)
        (lu.parent.parent / "restuff.exe").write_bytes(b"MZ fake")
        self.w.settings["restuff_build"] = str(lu.parent.parent)
        calls = []

        class Fake:
            def __init__(self, argv, **kw):
                calls.append(argv)
                self.pid = 1
        old = self.backend.POPEN
        self.backend.POPEN = Fake
        self.addCleanup(setattr, self.backend, "POPEN", old)
        return lu, calls

    def test_ship_and_launch_installs_the_shipped_container_then_starts(self):
        w = self.w
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lu, calls = self.fake_build(tmp.name)
        (lu / "global.lu").write_bytes(b"the build's own global")
        self.edit_good()
        self.wait_preview()
        w.review.ship(True)
        self.assertTrue(pump(lambda: "Started the game" in w.banner.text.text(), 120))
        live = self.folder / "global.lu"
        self.assertEqual(sha(lu / "global.lu"), sha(live))
        self.assertNotEqual(sha(live), self.orig)
        saved = lu / ".seamripper" / "backups" / "global.lu"
        self.assertEqual(saved.read_bytes(), b"the build's own global")
        self.assertIn("Installed in the build: global.lu", w.banner.text.text())
        self.assertEqual(sorted(p.name for p in lu.glob("*.lu")), ["global.lu"])
        self.assertEqual(calls[0][1], "--log_file")

    def test_ship_and_launch_without_a_build_ships_nothing(self):
        w = self.w
        w.settings["restuff_build"] = ""
        self.edit_good()
        self.wait_preview()
        w.review.ship(True)
        self.assertIn("restuff build folder", w.banner.text.text())
        self.assertEqual(sha(self.folder / "global.lu"), self.orig)
        self.assertEqual(w.ctx.changes.count(), 1)

    def test_ship_and_launch_when_the_project_is_the_build_skips_the_copy(self):
        w = self.w
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lu, calls = self.fake_build(tmp.name)
        shutil.copyfile(NB1 / "global.lu", lu / "global.lu")
        sc = self.open_script(w, lu, "global.lu", "characterclasses")
        sc.editor.setPlainText(sc.editor.toPlainText().replace(EDIT_FROM, EDIT_TO, 1))
        w.select_rail(2)
        pl = w.planner
        self.assertTrue(pump(lambda: str(lu / "global.lu") in pl.previews
                             and pl.previews[str(lu / "global.lu")].status == "ok"
                             and not pl._side[str(lu / "global.lu")].running(), 60))
        w.review.ship(True)
        self.assertTrue(pump(lambda: "Started the game" in w.banner.text.text(), 120))
        self.assertIn("not copied: global.lu", w.banner.text.text())
        self.assertEqual(len(calls), 1)

    def test_undo_button_restores_the_version_before_the_ship(self):
        w = self.w
        self.edit_good()
        self.wait_preview()
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy()))
        live = self.folder / "global.lu"
        self.assertNotEqual(sha(live), self.orig)
        w.review.undo([str(live)])
        self.assertEqual(sha(live), self.orig)
        self.assertIn("Undone", w.banner.text.text())

    def test_ship_to_folder_leaves_the_game_folder_alone(self):
        from sr_gui.settings import project_options
        w = self.w
        import tempfile
        dest = tempfile.TemporaryDirectory()
        self.addCleanup(dest.cleanup)
        project_options(w.settings, self.folder)["ship_to"] = dest.name
        self.edit_good()
        self.wait_preview()
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy()))
        self.assertEqual(sha(self.folder / "global.lu"), self.orig)
        self.assertTrue((Path(dest.name) / "global.lu").exists())
        self.assertNotEqual(sha(Path(dest.name) / "global.lu"), self.orig)
        self.assertEqual(w.ctx.changes.count(), 1)              # still not in the game folder
        self.assertIn(dest.name, w.banner.text.text())

    @staticmethod
    def forced_runs(w):
        """How many logged commands were run with --force."""
        return sum(1 for ln in w.log.box.toPlainText().splitlines()
                   if ln.startswith("run:") and " --force" in ln)

    def test_stale_edit_is_refused_and_can_be_forced_after_confirming(self):
        w = self.w
        lines = self.text.split("\n")
        keep = ("function", "end")                 # same functions, everything else different
        self.sc.editor.setPlainText("\n".join(
            [lines[0]] + [ln if ln.startswith(keep) else "--" for ln in lines[1:]]))
        pv = self.wait_preview("error")
        self.assertEqual(pv.errors[0][1]["kind"], "stale")
        self.assertTrue(pump(lambda: w.review.force_btn.isVisibleTo(w), 5))
        self.assertFalse(w.review.ship_btn.isEnabled())
        self.assertIn("Re-read", w.review.note.text())
        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Cancel):
            w.review.ship(False, force=True)                    # declined: nothing runs
        self.assertEqual(self.forced_runs(w), 0)
        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes):
            w.review.ship(False, force=True)
        self.assertTrue(pump(lambda: not w.runner.busy()))
        self.assertEqual(self.forced_runs(w), 1)

    def test_ship_error_from_the_tool_jumps_to_the_line(self):
        w = self.w
        self.edit_good()
        self.wait_preview()
        # a syntax error the preview did not see (edited after it ran): ship reports it
        lines = self.sc.editor.toPlainText().split("\n")
        lines[5] += " ="
        self.sc.editor.setPlainText("\n".join(lines))
        w.select_rail(2)
        w.review.planner.previews.clear()
        w.review.ship(False)
        self.assertTrue(pump(lambda: w.banner.property("kind") == "err" and not w.runner.busy()))
        self.assertIn("line 6", w.banner.text.text())
        self.assertIn(6, self.sc.errors)
        self.assertTrue(w.rail_btns[0].isChecked())
        self.assertEqual(sha(self.folder / "global.lu"), self.orig)

    def test_two_scripts_ship_in_one_call(self):
        w = self.w
        self.edit_good()
        other = next(s for s in self.sc.scripts if s.name == "animationwrapper")
        self.sc.select_index(other.index)
        self.assertTrue(pump(lambda: self.sc.draft.name == "animationwrapper"
                             and not w.runner.busy()))
        t2 = self.sc.editor.toPlainText()
        self.assertIn("AnimEndScriptListener:Create(script)", t2)
        self.sc.editor.setPlainText(t2.replace("AnimEndScriptListener:Create(script)",
                                               "AnimEndScriptListener:Create(script, nil)", 1))
        self.assertEqual(w.ctx.changes.count(), 2)
        w.select_rail(2)
        self.wait_planner_idle()
        self.assertTrue(pump(lambda: not w.runner.busy()))
        w.log.clear()
        w.review.ship(False)
        self.assertTrue(pump(lambda: not w.runner.busy() and w.banner.isVisibleTo(w), 240))
        ships = [l for l in w.log.box.toPlainText().splitlines() if l.startswith("run:") and " ship " in l
                 and "--preview" not in l]
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0].count("--edit"), 2)


@unittest.skipUnless(have("global.lu"), "no Naughty Bear game files here")
class CompileNotes(GuiCase):
    def setUp(self):
        self.folder, tmp = scratch_project(NB1, ["global.lu"])
        self.addCleanup(tmp.cleanup)
        self.w = self.window()
        self.sc = self.open_script(self.w, self.folder, "global.lu", "animationmgr")
        text = self.sc.editor.toPlainText()
        self.assertIn(NOTE_FROM, text)
        self.sc.editor.setPlainText(text.replace(NOTE_FROM, NOTE_TO, 1))

    def test_check_shows_the_note_as_a_warning_and_jumps_to_its_line(self):
        w, sc = self.w, self.sc
        sc.check()
        self.idle(w)
        self.assertEqual([ln for ln, _m in sc.notes], [98])
        self.assertEqual(w.banner.property("kind"), "warn")
        self.assertIn("passed", w.banner.text.text())
        self.assertEqual(sc.errors, {})                         # a note is not an error
        shown = " ".join(lb.text() for lb in sc.checks_box.findChildren(QLabel))
        self.assertIn("stored as an integer", shown)
        self.assertEqual(w.problems.count(), 1)
        self.assertTrue(w.problems.item(0).text().startswith("Line 98: Warning:"))
        sc.editor.goto_line(1)
        w.problems.itemClicked.emit(w.problems.item(0))
        self.assertEqual(sc.editor.textCursor().blockNumber() + 1, 98)
        sc.editor.setPlainText(sc.editor.toPlainText() + "\n")   # editing takes it down
        self.assertEqual(sc.notes, [])

    def test_preview_lists_the_note_and_ship_stays_enabled(self):
        w = self.w
        w.select_rail(2)
        lu = str(self.folder / "global.lu")
        pl = w.planner
        self.assertTrue(pump(lambda: lu in pl.previews and pl.previews[lu].status == "ok"
                             and not pl._side[lu].running(), 60))
        self.assertEqual([n["line"] for n in pl.previews[lu].notes], [98])
        shown = " ".join(lb.text() for lb in w.review.card_funcs.findChildren(QLabel))
        self.assertIn("Note, line 98", shown)
        self.assertTrue(pump(lambda: w.review.ship_btn.isEnabled(), 10))


class BannerLifetime(GuiCase):
    def test_error_banner_clears_when_the_next_run_starts(self):
        w = self.window()
        w.banner.show_message("Something failed.", "err")
        self.assertTrue(w.banner.isVisibleTo(w))
        w.runner.run([sys.executable, "-c", "pass"], title="A later run")
        self.assertFalse(w.banner.isVisibleTo(w))
        self.idle(w)

    def test_a_warning_or_ok_banner_is_kept_by_a_later_run(self):
        w = self.window()
        w.banner.show_message("Shipped.", "ok")
        w.runner.run([sys.executable, "-c", "pass"], title="A later run")
        self.idle(w)
        self.assertTrue(w.banner.isVisibleTo(w))


@unittest.skipUnless(have("beartrap.lu", "bone.lu", "global.lu"), "needs beartrap.lu and bone.lu")
class OtherContainers(GuiCase):
    def setUp(self):
        self.folder, tmp = scratch_project(NB1, ["beartrap.lu", "bone.lu", "global.lu"])
        self.addCleanup(tmp.cleanup)
        self.orig = {n: sha(self.folder / n) for n in ("beartrap.lu", "bone.lu", "global.lu")}
        self.w = self.window()
        self.sc = self.open_script(self.w, self.folder, "beartrap.lu", "weaponmethods")
        text = self.sc.editor.toPlainText()
        self.sc.editor.setPlainText(text.replace("isUnspawned = false", "isUnspawned = true", 1))
        self.assertTrue(self.sc.draft.edited)
        self.w.select_rail(2)

    def wait_where(self):
        pl = self.w.planner
        key = self.sc.draft.key
        self.assertTrue(pump(lambda: key in pl.where and pl.where[key].status == "ok", 120))
        return pl.where[key]

    def test_identical_copies_are_ticked_by_default(self):
        wh = self.wait_where()
        self.assertEqual([Path(c.path).name for c in wh.copies], ["bone.lu"])
        self.assertTrue(wh.copies[0].identical and wh.copies[0].checked)
        self.assertTrue(pump(lambda: "bone.lu" in " ".join(
            lb.text() for lb in self.w.review.card_also.findChildren(QLabel)) or
            self.w.review.card_also.findChild(QTreeWidget) is not None, 5))
        tree = self.w.review.card_also.findChild(QTreeWidget)
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertEqual(tree.topLevelItem(0).checkState(0), Qt.Checked)
        self.assertEqual(self.sc.other_btn.text(), "Also in 1 other container…")

    def test_ship_goes_to_every_ticked_container_with_backups(self):
        w = self.w
        self.wait_where()
        self.assertTrue(pump(lambda: w.review.ship_btn.isEnabled(), 30))
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy(), 120))
        for n in ("beartrap.lu", "bone.lu"):
            self.assertNotEqual(sha(self.folder / n), self.orig[n], n)
            self.assertEqual(sha(self.folder / ".seamripper" / "backups" / n), self.orig[n], n)
        self.assertEqual(sha(self.folder / "global.lu"), self.orig["global.lu"])
        self.assertIn("2 container", w.banner.text.text())

    def test_unticked_container_is_left_alone(self):
        w = self.w
        wh = self.wait_where()
        wh.copies[0].checked = False
        self.assertTrue(pump(lambda: w.review.ship_btn.isEnabled(), 30))
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy(), 120))
        self.assertNotEqual(sha(self.folder / "beartrap.lu"), self.orig["beartrap.lu"])
        self.assertEqual(sha(self.folder / "bone.lu"), self.orig["bone.lu"])


@unittest.skipUnless((PIP / "global.lu").exists(), "no Panic in Paradise game files here")
class PipChecks(GuiCase):
    def setUp(self):
        self.folder, tmp = scratch_project(PIP, ["global.lu"])
        self.addCleanup(tmp.cleanup)
        self.orig = sha(self.folder / "global.lu")
        self.w = self.window()
        self.sc = self.open_script(self.w, self.folder, "global.lu", "aiglobal")
        self.assertTrue(pump(lambda: self.w.planner.is_warm(str(self.folder / "global.lu")), 90))
        self.sc.refresh_side()
        self.text = self.sc.editor.toPlainText()

    def meter(self):
        return self.sc.checks_box.findChild(QProgressBar, "meter")

    def test_live_meter_and_structure_problems(self):
        sc = self.sc
        self.assertIsNotNone(self.meter())
        left = sc.budget["bytes_left"]
        self.assertGreaterEqual(sc.budget["limit"], sc.budget["original_size"])
        sc.editor.setPlainText(self.text + "\n-- more\n")
        self.assertTrue(pump(lambda: sc.budget and sc.budget["bytes_left"] == left - len("\n-- more\n")
                             or (sc.budget and sc.budget["bytes_left"] < left), 5))
        # a missing closing bracket is flagged live, on its line
        sc.editor.setPlainText(self.text + "\nlocal broken = {\n")
        self.assertTrue(pump(lambda: bool(sc.live), 5))
        self.assertIn(max(sc.live), sc.editor.errors)
        shown = " ".join(lb.text() for lb in sc.checks_box.findChildren(QLabel))
        self.assertIn("never closed", shown)
        sc.editor.setPlainText(self.text)
        self.assertTrue(pump(lambda: not sc.live, 5))

    def test_too_large_edit_turns_the_meter_red_and_blocks_ship(self):
        w, sc = self.w, self.sc
        sc.editor.setPlainText(self.text + "\n" + "-- padding padding padding\n" * 3000)
        self.assertTrue(pump(lambda: sc.budget and not sc.budget["fits"], 5))
        shown = " ".join(lb.text() for lb in sc.checks_box.findChildren(QLabel))
        self.assertIn("too large by", shown)
        w.select_rail(2)
        lu = str(self.folder / "global.lu")
        self.assertTrue(pump(lambda: lu in w.planner.previews and w.planner.previews[lu].status
                             != "busy" and not w.planner._side[lu].running(), 60))
        self.assertFalse(w.review.ship_btn.isEnabled())

    def test_ship_pip_edit_in_place_with_backup(self):
        w, sc = self.w, self.sc
        sc.editor.setPlainText(self.text + "\n")
        w.select_rail(2)
        lu = str(self.folder / "global.lu")
        self.assertTrue(pump(lambda: lu in w.planner.previews and w.planner.previews[lu].status
                             == "ok" and not w.planner._side[lu].running(), 60))
        b = w.planner.budget_for(w.ctx.changes.pending()[0])
        self.assertTrue(b and b["fits"])
        self.assertTrue(pump(lambda: w.review.ship_btn.isEnabled(), 10))
        w.review.ship(False)
        self.assertTrue(pump(lambda: "Shipped" in w.banner.text.text() and not w.runner.busy(), 120))
        self.assertNotEqual(sha(lu), self.orig)
        self.assertEqual(sha(self.folder / ".seamripper" / "backups" / "global.lu"), self.orig)

    def test_value_warnings_need_a_tick(self):
        w, sc = self.w, self.sc
        sc.editor.setPlainText(self.text + "\n")
        pl = w.planner
        d = w.ctx.changes.pending()[0]
        with mock.patch.object(self.backend, "value_warnings", return_value=[
                {"line": 3, "col": 1, "kind": "range", "message": "hp = 30000 is far above 400"}]):
            w.select_rail(2)
            lu = str(self.folder / "global.lu")
            self.assertTrue(pump(lambda: pl.warnings_for(d) and lu in pl.previews and
                                 pl.previews[lu].status == "ok" and not pl._side[lu].running(), 60))
            self.assertFalse(w.review.ship_btn.isEnabled())     # warnings need a tick
            self.assertIn("read the warnings", w.review.note.text())
            w.review.ack_box.setChecked(True)
            self.assertTrue(w.review.ship_btn.isEnabled())
            shown = " ".join(lb.text() for lb in w.review.card_checks.findChildren(QLabel))
            self.assertIn("30000", shown)


    def test_schema_warnings_show_in_checks_and_problems(self):
        sc, w = self.sc, self.w
        with mock.patch.object(self.backend, "value_warnings", return_value=[
                {"line": 3, "col": 1, "kind": "range", "message": "hp = 30000 is far above 400"}]):
            sc.editor.setPlainText(self.text + "\n")
            self.assertTrue(pump(lambda: any("30000" in lb.text() for lb in
                                             sc.checks_box.findChildren(QLabel)), 10))
            self.assertTrue(pump(lambda: w.problems.count() == 1, 5))
            self.assertIn("Warning: hp = 30000", w.problems.item(0).text())
            self.assertEqual(sc.errors, {})
            sc.editor.setPlainText(self.text)                   # back to the original: gone
            self.assertTrue(pump(lambda: w.problems.count() == 0, 5))


class ValueChecks(GuiCase):
    def test_schema_build_runs_in_the_background_and_caches(self):
        if not (PIP / "levelloaders.lu").exists():
            self.skipTest("no Panic in Paradise game files here")
        folder, tmp = scratch_project(PIP, ["levelloaders.lu"])
        self.addCleanup(tmp.cleanup)
        w = self.window()
        w.open_project(str(folder))
        pl = w.planner
        self.assertEqual(pl.schema_state, "unknown")
        w.build_schema()
        self.assertEqual(pl.schema_state, "building")
        self.assertTrue(pump(lambda: pl.schema_state in ("ready", "error"), 300))
        self.assertEqual(pl.schema_state, "ready", pl.schema_msg)
        import os
        self.assertTrue(Path(os.environ["SEAMRIPPER_CACHE"], "pip_schema.json").exists())
        self.assertTrue(pl.schema["scripts"] > 0)

    def test_build_can_be_cancelled(self):
        if not (PIP / "levelloaders.lu").exists():
            self.skipTest("no Panic in Paradise game files here")
        folder, tmp = scratch_project(PIP, ["levelloaders.lu"])
        self.addCleanup(tmp.cleanup)
        w = self.window()
        w.open_project(str(folder))
        w.build_schema()
        w.planner.cancel_schema()                  # stops at the first script it reports
        self.assertTrue(pump(lambda: w.planner.schema_state != "building", 120))
        self.assertEqual(w.planner.schema_state, "missing")


if __name__ == "__main__":
    unittest.main()
