"""Patches: the Save-as-patch dialog and the page that checks and applies a .srpatch."""
import os
import re
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import backend, style
from .paths import APPDIR
from .runner import SideProc
from .widgets import label

EXT = ".srpatch"


def default_dir(settings):
    saved = settings.get("patch_dir", "")
    if saved and Path(saved).is_dir():
        return Path(saved)
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


def file_name(name):
    return (re.sub(r'[^\w\-. ]+', "_", name).strip(" .") or "patch") + EXT


class PatchDialog(QDialog):
    """Name, author, version, description and where to save a patch."""

    def __init__(self, parent, settings, summary, note=""):
        super().__init__(parent)
        self.setWindowTitle("Save as patch")
        self.setMinimumWidth(480)
        self.folder = default_dir(settings)
        v = QVBoxLayout(self)
        v.addWidget(label("A patch holds only the lines you changed, so you can share a mod "
                          "without sharing the game. " + summary, "muted", True))
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("required")
        self.author = QLineEdit(settings.get("patch_author", ""))
        self.version = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(64)
        self.path = QLineEdit(str(self.folder / file_name("")))
        self.browse = QPushButton("Browse…")
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(self.browse)
        for text, w in (("Name", self.name), ("Author", self.author), ("Version", self.version),
                        ("Description", self.description)):
            form.addRow(text, w)
        form.addRow("Save to", row)
        v.addLayout(form)
        if note:
            v.addWidget(label(note, "warn", True))
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        self.save_btn = self.buttons.button(QDialogButtonBox.Save)
        self.save_btn.setText("Save patch")
        self.typed = False                  # the user chose the path; stop following the name
        self.name.textChanged.connect(self._name_changed)
        self.path.textEdited.connect(lambda _t: setattr(self, "typed", True))
        self.browse.clicked.connect(self._browse)
        self._name_changed()

    def _name_changed(self, _t=None):
        self.save_btn.setEnabled(bool(self.name.text().strip()))
        if not self.typed:
            self.path.setText(str(self.folder / file_name(self.name.text().strip())))

    def _browse(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save the patch as", self.path.text(),
                                            "Seam Ripper patch (*.srpatch)",
                                            options=QFileDialog.DontUseNativeDialog)
        if fn:
            self.path.setText(fn)
            self.typed = True

    def meta(self):
        return {"name": self.name.text().strip(), "author": self.author.text().strip(),
                "version": self.version.text().strip(),
                "description": self.description.toPlainText().strip()}

    def out(self):
        p = Path(self.path.text().strip() or file_name(self.name.text()))
        return p if p.suffix.lower() == EXT else p.with_name(p.name + EXT)

    def _accept(self):
        if not self.name.text().strip():
            return
        if self.out().exists() and QMessageBox.question(
                self, "Replace file", f"{self.out().name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self.accept()


class PatchesPage(QWidget):
    """Open a .srpatch, see which of your files it fits, and apply it."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.patch = None                   # path of the open patch
        self.manifest = None
        self.checks = []                    # `apply --check --json` for the open game folder
        self.state = ""                     # "" | checking | ready | error
        self._info, self._check, self._other = (SideProc(ctx.log) for _ in range(3))
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.addWidget(label("Patches", "heading"))
        v.addWidget(label("Open a patch to see if it fits your game, then apply it. To "
                          "make one from your own edits, use Save as patch on the "
                          "Changes page.", "muted", True))
        row = QHBoxLayout()
        b = self.open_btn = QPushButton("Open patch…")
        b.clicked.connect(lambda: self.open_patch())
        m = self.make_btn = QPushButton("Make a patch from my changes…")
        m.clicked.connect(self.make)
        row.addWidget(b)
        row.addWidget(m)
        row.addStretch(1)
        v.addLayout(row)
        self.title = label("", "heading")
        self.meta = label("", "muted", True)
        self.desc = label("", None, True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Changes", "Status"])
        self.tree.setRootIsDecorated(True)
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 120)
        self.note = label("", "muted", True)
        for w in (self.title, self.meta, self.desc):
            v.addWidget(w)
        v.addWidget(self.tree, 1)
        v.addWidget(self.note)
        row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setToolTip("Changes your game files. They're backed up first.")
        self.force_btn = QPushButton("Apply anyway…")
        self.force_btn.setToolTip("Some files are a different version. If any change "
                                  "can't find its lines, nothing is written.")
        self.copy_btn = QPushButton("Apply to a copy…")
        self.copy_btn.setToolTip("Saves the patched files to another folder. Your game "
                                 "isn't touched.")
        self.build_btn = QPushButton("Apply to the game build")
        self.build_btn.setToolTip("Applies it to your restuff build (Settings, Play). "
                                  "Files are backed up first.")
        self.apply_btn.clicked.connect(lambda: self.apply_())
        self.force_btn.clicked.connect(lambda: self.apply_())
        self.copy_btn.clicked.connect(lambda: self.apply_copy())
        self.build_btn.clicked.connect(lambda: self.apply_build())
        for w in (self.apply_btn, self.force_btn, self.copy_btn, self.build_btn):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)
        self.empty = label("No patch is open.", "muted")
        v.insertWidget(3, self.empty)
        ctx.runner.busy_changed.connect(lambda _b: self._update())
        ctx.project_changed.connect(self.recheck)
        self._render()

    # ------------------------------------------------------------ opening
    def make(self):
        w = self.ctx.window
        w.select_rail(2)
        w.review.make_patch()

    def open_patch(self, fn=None):
        if not fn:
            start = str(Path(self.patch).parent) if self.patch else str(default_dir(self.ctx.settings))
            fn, _ = QFileDialog.getOpenFileName(self, "Choose a patch", start,
                                                "Seam Ripper patch (*.srpatch)",
                                                options=QFileDialog.DontUseNativeDialog)
        if not fn:
            return
        self.ctx.banner.hide()
        self._info.start(backend.patch_info_argv(self.ctx.settings, fn),
                         lambda c, o, e: self._opened(fn, c, o, e), cwd=APPDIR)

    def _opened(self, fn, code, out, err):
        m = backend.patch_json(out)
        if code != 0 or not isinstance(m, dict):
            self.ctx.banner.show_message(backend.patch_error(err, out), "err")
            return
        self.patch, self.manifest, self.checks = str(fn), m, []
        self.recheck()

    def recheck(self):
        """Ask which of the open game folder's files the patch fits."""
        self._check.abort()
        self.checks = []
        p = self.ctx.project
        if self.manifest is None:
            return self._render()
        if p is None:
            self.state = ""
            return self._render()
        self.state = "checking"
        self._render()
        folder = str(p.folder)
        self._check.start(
            backend.patch_apply_argv(self.ctx.settings, self.patch, folder, check=True),
            lambda c, o, e: self._checked(folder, c, o, e), cwd=APPDIR)

    def _checked(self, folder, code, out, err):
        rows = backend.patch_json(out)
        if not isinstance(rows, list) or len(rows) != len(self.manifest["targets"]):
            self.state, self.checks = "error", []
            self.ctx.banner.show_message(backend.patch_error(err, out), "err")
        else:
            self.state, self.checks = "ready", rows
        self._render()

    def stop(self):
        for p in (self._info, self._check, self._other):
            p.abort()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.manifest is not None and self.state != "checking":
            self.recheck()                  # the game files may have changed since

    # ------------------------------------------------------------ state
    def ready(self):
        return bool(self.checks) and all(c["status"] in backend.READY for c in self.checks)

    def read_only(self):
        """Files Apply would have to write but cannot (a protected folder)."""
        return [c for c in self.checks if c.get("read_only") and c["status"] != "applied"]

    def mismatched(self):
        return [c for c in self.checks if c["status"] == "mismatch"]

    def forceable(self):
        return bool(self.mismatched()) and all(
            c["status"] in backend.READY or c["status"] == "mismatch" for c in self.checks)

    def build_dir(self):
        d, _why = backend.build_check(backend.build_folder(self.ctx.settings))
        return d

    def _render(self):
        m = self.manifest
        self.empty.setVisible(m is None)
        for w in (self.title, self.meta, self.desc, self.tree):
            w.setVisible(m is not None)
        self.tree.clear()
        if m is not None:
            self.title.setText(m.get("name") or Path(self.patch).stem)
            self.meta.setText("  ·  ".join(x for x in (
                f"version {m['version']}" if m.get("version") else "",
                f"by {m['author']}" if m.get("author") else "", Path(self.patch).name) if x))
            self.desc.setText(m.get("description", ""))
            self.desc.setVisible(bool(m.get("description")))
            for n, t in enumerate(m["targets"]):
                it = QTreeWidgetItem([t["file"], _plural(backend.patch_changes(t), "change")])
                self.tree.addTopLevelItem(it)
                for e in t["edits"]:
                    text = (f"script {e['name']}: {_plural(len(e['hunks']), 'change')}"
                            if e["kind"] == "script"
                            else f"{_plural(e.get('count', 0), 'localization string')}")
                    it.addChild(QTreeWidgetItem([text]))
                it.setExpanded(True)
                if self.checks:
                    words, tone = backend.patch_status_text(self.checks[n])
                    it.setToolTip(2, self.checks[n].get("path") or "")
                elif self.state == "checking":
                    words, tone = "checking…", "muted"
                else:
                    words, tone = "open a game folder to check it", "muted"
                it.setText(2, words)
                if tone != "muted":
                    it.setForeground(2, QColor(style.color(tone)))
        note = self._note()
        if note and self.ctx.project is not None:
            # the statuses are about the open game folder, not the game build
            note = f"Checked against your open game folder, {self.ctx.project.folder}. " + note
        self.note.setText(note)
        self._update()

    def _note(self):
        if self.manifest is None or self.state != "ready":
            return ""
        if self.read_only() and (self.ready() or self.forceable()):
            return ("This patch fits, but the game files are read-only. Use Apply to a "
                    "copy, or untick read-only in the files' Properties.")
        if self.ready():
            return "This patch fits your game files."
        if self.forceable():
            return ("Some files are a different version. You can still try: if any change "
                    "can't find its lines, nothing is written.")
        return "This patch cannot be applied here: a file is missing or found more than once."

    def _update(self):
        idle = not self.ctx.runner.busy()
        writable = not self.read_only()
        ok = self.ready() and idle and writable
        self.apply_btn.setEnabled(ok)
        self.force_btn.setVisible(self.forceable())
        self.force_btn.setEnabled(idle and writable)
        self.build_btn.setVisible(self.build_dir() is not None)
        self.build_btn.setEnabled(self.manifest is not None and idle)
        self.copy_btn.setEnabled(idle and (self.ready() or self.forceable()))

    # ------------------------------------------------------------ apply
    def apply_(self):
        """Apply into the open game folder (asks first when a file is a different version)."""
        p = self.ctx.project
        if p is not None and self.checks:
            self._go(str(p.folder), None, self.checks)

    def apply_copy(self, out=None):
        p = self.ctx.project
        if p is None or not self.checks:
            return
        out = out or QFileDialog.getExistingDirectory(
            self, "Write the patched files to a folder", str(default_dir(self.ctx.settings)),
            QFileDialog.DontUseNativeDialog)
        if out:
            self._go(str(p.folder), out, self.checks)

    def apply_build(self):
        d = self.build_dir()
        if d is None or self.manifest is None:
            return
        folder = d["assets"]
        self._other.start(
            backend.patch_apply_argv(self.ctx.settings, self.patch, folder, check=True),
            lambda c, o, e: self._build_checked(folder, o, e), cwd=APPDIR)

    def _build_checked(self, folder, out, err):
        rows = backend.patch_json(out)
        if not isinstance(rows, list):
            self.ctx.banner.show_message(backend.patch_error(err, out), "err")
            return
        self._go(folder, None, rows)

    def _go(self, folder, out, checks):
        bad = [c for c in checks if c["status"] in ("missing", "ambiguous")]
        if bad:
            self.ctx.banner.show_message(
                "Not applied: " + "; ".join(f"{c['file']} is {c['status']}"
                                            + (f" ({c['detail']})" if c["detail"] else "")
                                            for c in bad) + f" in {folder}.", "err")
            return
        wrong = [c for c in checks if c["status"] == "mismatch"]
        if wrong and not self.confirm_force(wrong):
            return
        self.ctx.banner.hide()
        self.ctx.runner.run(
            backend.patch_apply_argv(self.ctx.settings, self.patch, folder, out, bool(wrong)),
            cwd=APPDIR, title=f"Applying {Path(self.patch).name}",
            on_done=lambda c, o, e: self._applied(folder, out, c, o, e))
        self._update()

    def confirm_force(self, wrong):
        return QMessageBox.warning(
            self, "Apply anyway?",
            "These files are not the version this patch was made for:\n\n- "
            + "\n- ".join(f"{c['file']}: {c['detail']}" for c in wrong[:6])
            + "\n\nIf any change can't find its lines, nothing is written. Your files "
              "are backed up first.\n\nApply anyway?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) == QMessageBox.Yes

    def _applied(self, folder, out, code, o, e):
        ctx = self.ctx
        r = backend.patch_json(o)
        if code == -1:
            ctx.banner.show_message("Cancelled. Nothing more was written.", "warn")
        elif not isinstance(r, dict) or code not in (0, 2):
            ctx.banner.show_message("Not applied: " + backend.patch_error(e, o), "err")
        else:
            rows = r.get("files", [])
            groups = {}                     # one line per kind of result, not per file
            for x in rows:
                groups.setdefault(backend.patch_result_text(x), []).append(x["file"])
            text = f"Applied {self.manifest.get('name') or Path(self.patch).name}. " + "; ".join(
                f"{files[0]}: {res}" if len(files) == 1 else f"{len(files)} files: {res}"
                for res, files in groups.items()) + "."
            actions = []
            if out:
                text += f" Written to {out}. Your game folder is not changed."
                actions.append(("Open folder", lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(out)))))
            else:
                text += " Originals are backed up."
                actions.append(("Open History", lambda: ctx.window.select_rail(4)))
            ctx.banner.show_message(text, "ok" if code == 0 else "warn", actions)
            if not out:
                inside = ctx.project and _same(folder, ctx.project.folder)
                if inside:
                    ctx.window.after_ship([x["out"] for x in rows], True)
                ctx.window.history.refresh()
        if not out and code in (0, 2) and self.manifest is not None:
            self.recheck()
        self._update()


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _same(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))
