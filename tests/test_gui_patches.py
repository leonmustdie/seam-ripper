"""GUI wiring for patches: Save as patch, the Patches tab, apply, and one real round trip.
Everything works on temp copies; retail files are only read."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_support import HAVE_QT, GuiCase, pump, sha  # noqa: E402

if HAVE_QT:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from sr_gui import backend
    from sr_gui.changes import Draft
    from sr_gui.patches_page import PatchDialog
    from sr_gui.shipping import Copy, Where

BONE = Path(r"D:\testingenvironment\initialnb1files\lu\bone.lu")
TOOLS = Path(__file__).resolve().parent.parent / "tools"
have_bone = BONE.exists() and any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify"))

S = {"python": "python", "luac": "l", "jar": "j"}


def manifest(*files):
    """A manifest with one script edit (2 hunks) per file name."""
    return {"name": "Strong bears", "author": "Ann", "version": "1.2",
            "description": "Bears hit harder.", "game": "nb1",
            "targets": [{"file": f, "edits": [{"kind": "script", "name": "weaponmethods",
                                                "hunks": [{}, {}]}]} for f in files]}


class Backend(unittest.TestCase):
    def test_make_argv_has_meta_and_every_script(self):
        a = backend.patch_make_argv(S, "out.srpatch", {"name": "N", "author": "", "version": "2",
                                                       "description": "d"},
                                    [("a.lu", 7, "x.lua"), ("b.lu", 9, "x.lua")])
        self.assertTrue(a[1].endswith("sr_patch.py"))
        self.assertEqual(a[2:], ["make", "-o", "out.srpatch", "--name", "N", "--version", "2",
                                 "--description", "d", "--script", "a.lu", "7", "x.lua",
                                 "--script", "b.lu", "9", "x.lua"])

    def test_apply_argv(self):
        a = backend.patch_apply_argv(S, "p.srpatch", "game", out="copy", force=True)
        self.assertEqual(a[2:], ["apply", "p.srpatch", "game", "-o", "copy", "--force", "--json"])
        self.assertEqual(backend.patch_apply_argv(S, "p", "g", check=True)[-2:],
                         ["--check", "--json"])
        self.assertNotIn("--force", backend.patch_apply_argv(S, "p", "g"))

    def test_summary_and_json(self):
        m = manifest(*[f"f{i}.lu" for i in range(13)])
        self.assertEqual(backend.patch_summary(m, 2048),
                         "13 files, 2 changes each, 2 KB, contains no game files")
        self.assertEqual(backend.patch_summary(manifest("a.lu"), 300),
                         "1 file, 2 changes, 300 bytes, contains no game files")
        self.assertEqual(backend.patch_json('wrote x\n{"ok": true}\n'), {"ok": True})
        self.assertEqual(backend.patch_json("[1]"), [1])
        self.assertIsNone(backend.patch_json("nothing"))
        self.assertEqual(backend.patch_error("apply: bad thing\n"), "apply: bad thing")

    def test_status_words(self):
        f = lambda s, d="": backend.patch_status_text({"status": s, "detail": d})
        self.assertEqual(f("ok"), ("ready", "ok"))
        self.assertEqual(f("compatible")[0], "ready (this file has other changes; the patched "
                                             "scripts are original)")
        self.assertEqual(f("applied")[0], "already has this patch")
        self.assertEqual(f("mismatch", "script a is a different version"),
                         ("different version: script a is a different version", "warn"))
        self.assertEqual(f("missing")[0], "not found")
        self.assertEqual(f("ambiguous", "found in a, b")[0], "found more than once: found in a, b")
        self.assertEqual(backend.patch_result_text({"status": "identical"}),
                         "identical to the author's result")
        self.assertEqual(backend.patch_result_text({"status": "applied"}), "already had it")


class FakeGame(GuiCase):
    """A window on a folder of placeholder .lu files; no tool is ever run."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        for n in ("a.lu", "b.lu"):
            (self.folder / n).write_bytes(b"x")
        self.w = self.window()
        self.w.open_project(str(self.folder))
        self.page = self.w.patches
        self.page.patch = "strong.srpatch"


class SaveAsPatch(FakeGame):
    def draft(self, name, index, lu="a.lu"):
        d = Draft(self.folder / lu, index, name, "", "nb1", "old\n", "new\n")
        self.w.ctx.changes.update(d)
        return d

    def test_entries_are_the_ticked_drafts_plus_ticked_copies(self):
        d1, d2 = self.draft("one", 5), self.draft("two", 6)
        self.w.ctx.changes.set_checked(d2.key, False)
        w = self.w.planner.where[d1.key] = Where()
        w.status = "ok"
        w.copies = [Copy(self.folder / "b.lu", 40, True, 1, True),
                    Copy(self.folder / "c.lu", 41, True, 1, True),
                    Copy(self.folder / "d.lu", None, True, 1, True)]
        w.copies[1].checked = False
        entries, waiting = self.w.review.patch_entries()
        self.assertEqual(waiting, 0)
        self.assertEqual([(Path(lu).name, i) for lu, i, _s in entries],
                         [("a.lu", 5), ("b.lu", 40)])
        self.assertEqual({Path(s).read_text(encoding="utf-8").strip() for _l, _i, s in entries},
                         {"new"})

    def test_a_script_still_looking_for_copies_is_counted(self):
        self.draft("one", 5)
        self.assertEqual(self.w.review.patch_entries()[1], 1)

    def test_dialog_builds_the_command_and_saving_ships_nothing(self):
        self.draft("one", 5)
        out = self.folder / "mods" / "Strong bears.srpatch"

        def fill(dlg):
            dlg.name.setText("Strong bears")
            dlg.author.setText("Ann")
            dlg.description.setPlainText("Hit harder")
            dlg.path.setText(str(out))
            return QDialog.Accepted
        with mock.patch.object(PatchDialog, "exec", fill), \
                mock.patch.object(self.w.runner, "run") as run, \
                mock.patch.object(self.backend, "ship_argv") as ship:
            self.w.review.make_patch()
        ship.assert_not_called()
        argv = run.call_args.args[0]
        self.assertEqual(argv[2:9], ["make", "-o", str(out), "--name", "Strong bears",
                                     "--author", "Ann"])
        self.assertEqual(argv[9:11], ["--description", "Hit harder"])
        self.assertEqual(argv[11:14], ["--script", str(self.folder / "a.lu"), "5"])
        self.assertEqual(self.w.settings["patch_dir"], str(out.parent))

    def test_nothing_ticked_says_so(self):
        self.w.review.make_patch()
        self.assertIn("Tick at least one change", self.w.banner.text.text())
        self.assertFalse(self.w.review.patch_btn.isEnabled())

    def test_dialog_needs_a_name_and_adds_the_extension(self):
        dlg = PatchDialog(self.w, dict(self.w.settings, patch_dir=str(self.folder)), "sum")
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg.save_btn.isEnabled())
        dlg.name.setText("My: mod?")
        self.assertTrue(dlg.save_btn.isEnabled())
        self.assertEqual(dlg.out(), self.folder / "My_ mod_.srpatch")
        dlg.path.setText(str(self.folder / "plain"))
        self.assertEqual(dlg.out(), self.folder / "plain.srpatch")

    def test_failed_make_shows_the_message(self):
        self.w.review._patch_made(self.folder / "x.srpatch", 1, "", "make: nothing changed\n")
        self.assertEqual(self.w.banner.property("kind"), "err")
        self.assertIn("nothing changed", self.w.banner.text.text())


class PatchesTab(FakeGame):
    def show(self, *statuses, detail="", targets=None):
        files = targets or [f"f{i}.lu" for i in range(len(statuses))]
        self.page.manifest = manifest(*files)
        self.page.checks = [{"file": f, "path": f, "status": s, "detail": detail}
                            for f, s in zip(files, statuses)]
        self.page.state = "ready"
        self.page._render()

    def words(self):
        t = self.page.tree
        return [t.topLevelItem(i).text(2) for i in range(t.topLevelItemCount())]

    def test_header_files_and_scripts_are_listed(self):
        self.show("ok")
        self.assertEqual(self.page.title.text(), "Strong bears")
        self.assertIn("version 1.2", self.page.meta.text())
        self.assertIn("by Ann", self.page.meta.text())
        self.assertEqual(self.page.desc.text(), "Bears hit harder.")
        top = self.page.tree.topLevelItem(0)
        self.assertEqual((top.text(0), top.text(1)), ("f0.lu", "2 changes"))
        self.assertEqual(top.child(0).text(0), "script weaponmethods: 2 changes")

    def test_status_wording(self):
        self.show("ok", "compatible", "applied", "mismatch", "missing", "ambiguous",
                  detail="why")
        self.assertEqual(self.words(), [
            "ready",
            "ready (this file has other changes; the patched scripts are original)",
            "already has this patch", "different version: why", "not found",
            "found more than once: why"])

    def test_apply_is_enabled_only_when_every_file_is_ready(self):
        for statuses, apply_on, force_on in (
                (("ok", "compatible", "applied"), True, False),
                (("ok", "mismatch"), False, True),
                (("ok", "missing"), False, False),
                (("mismatch", "ambiguous"), False, False)):
            self.show(*statuses)
            self.assertEqual(self.page.apply_btn.isEnabled(), apply_on, statuses)
            self.assertEqual(not self.page.force_btn.isHidden(), force_on, statuses)
        self.assertIn("backed up", self.page.apply_btn.toolTip())

    def test_ready_apply_asks_nothing_and_writes_in_place(self):
        self.show("ok", "applied")
        with mock.patch.object(self.w.runner, "run") as run, \
                mock.patch.object(QMessageBox, "warning") as ask:
            self.page.apply_()
        ask.assert_not_called()
        argv = run.call_args.args[0]
        self.assertEqual(argv[2:5], ["apply", "strong.srpatch", str(self.folder)])
        self.assertNotIn("--force", argv)
        self.assertNotIn("-o", argv)

    def test_force_needs_a_yes_and_passes_force(self):
        self.show("ok", "mismatch", detail="script x is a different version")
        with mock.patch.object(self.w.runner, "run") as run, \
                mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Cancel) as ask:
            self.page.apply_()
        self.assertIn("nothing is written", ask.call_args.args[2])
        self.assertIn("find its lines", ask.call_args.args[2])
        run.assert_not_called()
        with mock.patch.object(self.w.runner, "run") as run, \
                mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes):
            self.page.apply_()
        self.assertIn("--force", run.call_args.args[0])

    def test_apply_to_a_copy_writes_to_the_chosen_folder(self):
        self.show("compatible")
        out = self.folder / "copy"
        with mock.patch.object(self.w.runner, "run") as run:
            self.page.apply_copy(str(out))
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("-o") + 1], str(out))

    def test_missing_is_refused_without_running_anything(self):
        self.show("missing")
        with mock.patch.object(self.w.runner, "run") as run:
            self.page._go(str(self.folder), None, self.page.checks)
        run.assert_not_called()
        self.assertEqual(self.w.banner.property("kind"), "err")
        self.assertIn("f0.lu is missing", self.w.banner.text.text())

    def test_result_banner_lists_each_file_and_error_shows_the_message(self):
        self.show("ok", "applied")
        files = [{"file": "f0.lu", "out": "x", "status": "identical"},
                 {"file": "f1.lu", "out": "y", "status": "applied"}]
        with mock.patch.object(self.w, "after_ship"):
            self.page._applied(str(self.folder), None, 0, '{"ok": true, "files": %s}'
                               % json.dumps(files), "")
        text = self.w.banner.text.text()
        self.assertIn("f0.lu: identical to the author's result", text)
        self.assertIn("f1.lu: already had it", text)
        self.assertEqual(self.w.banner.property("kind"), "ok")
        same = [{"file": f"f{i}.lu", "out": "x", "status": "identical"} for i in range(13)]
        with mock.patch.object(self.w, "after_ship"):
            self.page._applied(str(self.folder), None, 0, '{"ok": true, "files": %s}'
                               % json.dumps(same), "")
        text = self.w.banner.text.text()
        self.assertIn("13 files: identical to the author's result", text)
        self.assertNotIn("f5.lu", text)
        self.page._applied(str(self.folder), None, 1, "", "apply: bone.lu is missing in x\n")
        self.assertEqual(self.w.banner.property("kind"), "err")
        self.assertIn("bone.lu is missing", self.w.banner.text.text())

    def test_dropping_a_patch_opens_it_on_the_patches_tab(self):
        from PySide6.QtCore import QMimeData, QUrl
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(self.folder / "m.srpatch"))])
        ev = mock.Mock()
        ev.mimeData.return_value = md
        with mock.patch.object(self.page, "open_patch") as opened:
            self.w.dropEvent(ev)
        opened.assert_called_once_with(str(Path(self.folder / "m.srpatch")))
        self.assertEqual(self.w.central.currentIndex(), 3)

    def test_a_file_that_is_not_a_patch_gives_the_tools_message(self):
        bad = self.folder / "junk.srpatch"
        bad.write_bytes(b"not a zip")
        self.page.open_patch(str(bad))
        self.assertTrue(pump(lambda: self.w.banner.isVisibleTo(self.w), 30))
        self.assertEqual(self.w.banner.property("kind"), "err")
        self.assertIn("not a Seam Ripper patch", self.w.banner.text.text())
        self.assertIsNone(self.page.manifest)


@unittest.skipUnless(have_bone, "no retail bone.lu or lzxverify here")
class RoundTrip(GuiCase):
    """Edit weaponmethods in a copy of retail bone.lu, save a patch, and apply it every way."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / "game"
        self.folder.mkdir()
        self.live = self.folder / "bone.lu"
        shutil.copyfile(BONE, self.live)               # (copyfile: the retail copy is read-only)
        self.orig = sha(self.live)
        self.w = self.window()

    def banner(self, word, timeout=240):
        w = self.w
        self.assertTrue(pump(lambda: word in w.banner.text.text() and not w.runner.busy(),
                             timeout), w.banner.text.text())

    def test_read_only_game_folder_says_why(self):
        w, page = self.w, self.w.patches
        sc = self.open_script(w, self.folder, "bone.lu", "weaponmethods")
        lines = sc.editor.toPlainText().split("\n")
        n = next(i for i, l in enumerate(lines) if '"strength", 2.0' in l)
        lines[n] = lines[n].replace("2.0", "3.0", 1)
        sc.editor.setPlainText("\n".join(lines))
        out = self.root / "strong.srpatch"
        entries, _waiting = w.review.patch_entries()
        w.review.start_patch(entries, {"name": "Strong", "author": "", "version": "",
                                       "description": ""}, out)
        self.banner("Saved")
        w.select_rail(3)
        page.open_patch(str(out))
        self.assertTrue(pump(lambda: page.state == "ready", 120))
        os.chmod(self.live, stat.S_IREAD)
        self.addCleanup(os.chmod, self.live, stat.S_IREAD | stat.S_IWRITE)
        # the check says so before anyone clicks, and Apply is off
        page.recheck()
        self.assertTrue(pump(lambda: page.state == "ready", 120))
        self.assertEqual(self.words(page), ["fits, but the file is read-only"])
        self.assertIn("read-only", page.note.text())
        self.assertFalse(page.apply_btn.isEnabled())
        self.assertTrue(page.copy_btn.isEnabled())
        # and if Apply runs anyway, the refusal is shown
        page.apply_()
        self.banner("read-only")
        self.assertEqual(w.banner.property("kind"), "err")
        self.assertEqual(sha(self.live), self.orig)

    def test_make_open_copy_apply_revert_and_build(self):
        w, page = self.w, self.w.patches
        sc = self.open_script(w, self.folder, "bone.lu", "weaponmethods")
        self.assertEqual(sc.draft.index, 207)
        lines = sc.editor.toPlainText().split("\n")
        n = next(i for i, l in enumerate(lines) if '"strength", 2.0' in l)
        lines[n] = lines[n].replace("2.0", "3.0", 1)
        sc.editor.setPlainText("\n".join(lines))
        self.assertEqual(w.ctx.changes.count(), 1)

        # save as patch: ships nothing
        out = self.root / "strong.srpatch"
        entries, _waiting = w.review.patch_entries()
        w.review.start_patch(entries, {"name": "Strong", "author": "Ann", "version": "1",
                                       "description": ""}, out)
        self.banner("Saved")
        self.assertTrue(out.is_file())
        self.assertIn("contains no game files", w.banner.text.text())
        self.assertIn("1 file, 1 change", w.banner.text.text())
        self.assertEqual(sha(self.live), self.orig)
        self.assertFalse((self.folder / ".seamripper").exists())

        # open it: name, files and status
        w.select_rail(3)
        page.open_patch(str(out))
        self.assertTrue(pump(lambda: page.state == "ready", 120))
        self.assertEqual(page.title.text(), "Strong")
        self.assertEqual(self.words(page), ["ready"])
        self.assertTrue(page.apply_btn.isEnabled())

        # apply to a copy: the game folder is untouched
        copy = self.root / "copy"
        page.apply_copy(str(copy))
        self.banner("Applied")
        self.assertIn("identical to the author's result", w.banner.text.text())
        self.assertEqual(sha(self.live), self.orig)
        self.assertNotEqual(sha(copy / "bone.lu"), self.orig)

        # apply in place: same bytes, backed up, History lists it
        page.apply_()
        self.banner("Applied")
        self.assertEqual(sha(self.live), sha(copy / "bone.lu"))
        self.assertEqual(sha(self.folder / ".seamripper" / "backups" / "bone.lu"), self.orig)
        self.assertEqual([(r["file"], r["state"]) for r in w.history.rows],
                         [("bone.lu", "modified")])
        self.assertTrue(pump(lambda: self.words(page) == ["already has this patch"], 120))

        # ...and History puts retail back
        w.select_rail(4)
        w.history.table.selectRow(0)
        with mock.patch.object(w, "_confirm", return_value=True):
            w.history.revert_one()
        self.assertEqual(sha(self.live), self.orig)

        # the game build: a fake restuff folder holding retail bone.lu
        lu = self.root / "build" / "assets" / "lu"
        lu.mkdir(parents=True)
        (lu.parent.parent / "restuff.exe").write_bytes(b"MZ fake")
        shutil.copyfile(BONE, lu / "bone.lu")
        w.settings["restuff_build"] = str(lu.parent.parent)
        w.select_rail(3)
        self.assertTrue(pump(lambda: page.state == "ready", 120))
        self.assertFalse(page.build_btn.isHidden())
        page.apply_build()
        self.banner("Applied")
        self.assertEqual(sha(lu / "bone.lu"), sha(copy / "bone.lu"))
        self.assertEqual(sha(lu / ".seamripper" / "backups" / "bone.lu"), self.orig)

    @staticmethod
    def words(page):
        t = page.tree
        return [t.topLevelItem(i).text(2) for i in range(t.topLevelItemCount())]


if __name__ == "__main__":
    unittest.main()
