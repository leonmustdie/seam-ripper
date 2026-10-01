"""The Scripts view: script list, editor, outline and checks for one container."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QSplitter, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import backend, style
from .batch import BatchDialog
from .changes import Draft
from .editor import CodeEditor, FindBar
from .luahelp import functions, parse_list
from .paths import APPDIR
from .project import container_game
from .widgets import label


class ScriptsTab(QWidget):
    listed = Signal(int)                    # number of scripts found
    problems_changed = Signal(list, bool)   # ([(text, line, context)], from a check or ship)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.lu = ""
        self.scripts = []
        self.draft = None
        self.reads = {}                     # (lu, index) -> original text this session
        self._loading = False
        self.errors = {}
        self.notes = []                     # [(line, text)] a check printed; not blocking
        self._shown_warns = []
        self.pending = None                 # (index, line) to open once the list arrives
        self.stash = None                   # (key, errors) to show once that script opens
        self.live, self.budget = {}, None   # live problems (PiP) and the space meter data

        split = QSplitter(Qt.Horizontal)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(split)

        # -- script list
        left = QFrame()
        left.setObjectName("sidebar")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter scripts…")
        self.filter.textChanged.connect(self._apply_filter)
        self.list = QListWidget()
        self.list.setObjectName("rowlist")
        self.list.itemClicked.connect(self._picked)
        self.list.itemActivated.connect(self._picked)
        self.list_note = label("", "muted", True)
        lv.addWidget(self.filter)
        lv.addWidget(self.list, 1)
        lv.addWidget(self.list_note)
        split.addWidget(left)

        # -- editor column
        self.stack = QStackedWidget()
        hint = label("Pick a script on the left.\n\n"
                     "Edit inside functions and leave the function lines alone. Nothing is "
                     "written to the game until you Ship.", "muted", True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setMargin(30)
        self.stack.addWidget(hint)
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(10, 6, 10, 6)
        head.setSpacing(10)
        self.name_lb = label("", "heading")
        self.form_lb = label("", "badge")
        self.game_lb = label("", "muted")
        self.other_btn = QPushButton("Also in other containers…")
        self.other_btn.setFlat(True)
        self.other_btn.setObjectName("linklike")
        self.other_btn.clicked.connect(self._other_containers)
        for w in (self.name_lb, self.form_lb, self.game_lb):
            head.addWidget(w)
        head.addStretch(1)
        head.addWidget(self.other_btn)
        pv.addLayout(head)
        tb = QHBoxLayout()
        tb.setContentsMargins(10, 0, 10, 6)
        self.editor = CodeEditor()
        self.find_bar = FindBar(self.editor)
        for text, fn, tip in (
                ("Undo", lambda: self.editor.undo(), ""),
                ("Redo", lambda: self.editor.redo(), ""),
                ("Find…", self.find_bar.open, "Ctrl+F"),
                ("Batch edit calls…", self.open_batch,
                 "Highlight one call, like a whole AddFear(...) line, to change every "
                 "call like it at once."),
                ("HASH(\"…\")…", self.insert_hash,
                 "Insert HASH(\"name\") at the cursor. Ship replaces it with the name's hash."),
                ("Check", self.check, "Try the recompile without writing anything."),
                ("Show diff", self._show_diff, "See what changed (the Changes page)."),
                ("Revert script", self.revert_script, "Throw away your edits to this script.")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            if tip:
                b.setToolTip(tip)
            tb.addWidget(b)
        tb.addStretch(1)
        pv.addLayout(tb)
        pv.addWidget(self.editor, 1)
        pv.addWidget(self.find_bar)
        self.stack.addWidget(page)
        split.addWidget(self.stack)

        # -- inspector
        right = QFrame()
        right.setObjectName("sidebar")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.addWidget(label("OUTLINE", "muted"))
        self.outline = QTreeWidget()
        self.outline.setObjectName("tree")
        self.outline.setHeaderHidden(True)
        self.outline.itemClicked.connect(
            lambda it, _c: self.editor.goto_line(it.data(0, Qt.UserRole)))
        rv.addWidget(self.outline, 2)
        rv.addWidget(label("CHECKS", "muted"))
        self.checks = QVBoxLayout()
        self.checks_box = QWidget()
        self.checks_box.setLayout(self.checks)
        rv.addWidget(self.checks_box, 1)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([230, 600, 250])
        split.setStretchFactor(1, 1)

        self.editor.edited.connect(self._on_edit)
        self.editor.cursorPositionChanged.connect(self._cursor_error)
        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(300)
        self._outline_timer.timeout.connect(self.refresh_side)
        ctx.changes_listeners.append(self.refresh_dots)
        ctx.planner.changed.connect(self._refresh_other)
        ctx.planner.changed.connect(self._warns_changed)
        style.notifier.changed.connect(self.refresh_dots)

    # -- container ---------------------------------------------------------------
    def load(self, lu):
        """Show the scripts of container `lu`."""
        self.lu = str(lu)
        self.scripts = []
        self.list.clear()
        self.draft = None
        self.live, self.budget = {}, None
        self.stack.setCurrentIndex(0)
        self.list_note.setText("Reading the script list…")
        self.problems_changed.emit([], False)
        self.ctx.banner.clear("script-error")
        if container_game(lu) == "pip":
            self.ctx.planner.warm_pip(lu, on_ready=self._warmed)
        self.ctx.runner.run(backend.list_argv(self.ctx.settings, lu), cwd=APPDIR,
                            on_done=lambda c, o, e, lu=self.lu: self._listed(lu, c, o, e),
                            title="Listing scripts", quiet=True)

    def _warmed(self):
        """The PiP container has been parsed: the live meter can work now."""
        if self.draft is not None and self.draft.game == "pip":
            self.refresh_side()

    def _listed(self, lu, code, out, err):
        if lu != self.lu:
            return
        header, self.scripts = parse_list(out)
        if code != 0:
            self.ctx.log.write(out + err, "err")
        self.list_note.setText("" if self.scripts else
                               "No Lua scripts in this container.")
        for s in self.scripts:
            it = QListWidgetItem(s.name)
            it.setToolTip(f"{s.form}, {s.size} bytes")
            it.setData(Qt.UserRole, s.index)
            self.list.addItem(it)
        self.refresh_dots()
        self._apply_filter()
        self.listed.emit(len(self.scripts))
        if self.pending:
            (index, line), self.pending = self.pending, None
            self.select_index(index, line)

    def _apply_filter(self, *_):
        q = self.filter.text().lower()
        for i in range(self.list.count()):
            self.list.item(i).setHidden(q not in self.list.item(i).text().lower())

    def refresh_dots(self):
        edited = {d.index for d in self.ctx.changes.pending() if d.lu == self.lu} \
            if self.ctx.changes else set()
        icon = style.dot_icon("edit")
        from PySide6.QtGui import QIcon
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setIcon(icon if it.data(Qt.UserRole) in edited else QIcon())

    def select_index(self, index, line=None):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == index:
                self.list.setCurrentRow(i)
                break
        self.open_index(index, line)

    def _picked(self, item):
        self.open_index(item.data(Qt.UserRole))

    def _script(self, index):
        return next((s for s in self.scripts if s.index == index), None)

    def reload(self):
        """Forget what was read (the container changed on disk) and reopen the
        current script."""
        self.reads.clear()
        cur = self.draft
        self.draft = None
        if cur is not None and self.ctx.changes.get(cur.key) is None:
            self.open_index(cur.index)

    # -- open a script -----------------------------------------------------------
    def open_index(self, index, line=None):
        s = self._script(index)
        if s is None:
            return
        key = (self.lu, index)
        pending = self.ctx.changes.get(key)
        if pending is not None:
            self._show(pending, line)
        elif key in self.reads:
            self._show(Draft(self.lu, index, s.name, s.form, container_game(self.lu),
                             self.reads[key]), line)
        else:
            out = self.ctx.scratch_dir() / f"read_{abs(hash(self.lu))}_{index}.lua"
            self.ctx.runner.run(
                backend.read_argv(self.ctx.settings, self.lu, index, out), cwd=APPDIR,
                title=f"Reading {s.name}",
                on_done=lambda c, o, e, s=s, out=out, line=line:
                self._read_done(c, s, out, line))

    def _read_done(self, code, s, out, line):
        if code != 0 or not Path(out).exists():
            self.ctx.banner.show_message(f"Could not read {s.name}. See the log for why.", "err")
            return
        text = Path(out).read_text(encoding="utf-8", errors="replace")
        self.reads[(self.lu, s.index)] = text
        self._show(Draft(self.lu, s.index, s.name, s.form, container_game(self.lu), text), line)

    def _show(self, draft, line=None):
        if self.draft is None or self.draft.key != draft.key:
            self.ctx.banner.clear("script-error")
        self.draft = draft
        self._loading = True
        self.editor.set_script(draft.text, draft.orig)
        self._loading = False
        self.name_lb.setText(draft.name)
        self.form_lb.setText(draft.form)
        self.game_lb.setText({"nb1": "Naughty Bear", "pip": "Panic in Paradise"}
                             .get(draft.game, ""))
        self.errors, self.live, self.budget, self.notes = {}, {}, None, []
        self.stack.setCurrentIndex(1)
        if self.stash and self.stash[0] == draft.key:
            self.show_errors(*self.stash)
            self.stash = None
        else:
            self._push_errors(False)
        self.refresh_side()
        self._refresh_other()
        if line:
            self.editor.goto_line(line)

    # -- editing -------------------------------------------------------------------
    def _on_edit(self):
        if self._loading or self.draft is None:
            return
        self.draft.text = self.editor.toPlainText()
        self.ctx.changes.update(self.draft)
        if self.errors or self.notes:       # they described the text before this edit
            self.errors, self.notes = {}, []
            self.ctx.banner.clear("script-error")
            self.editor.set_errors(self.live)
            self._push_errors(False)
        if self.draft.edited:
            self.ctx.planner.request_where(self.draft)
        self._outline_timer.start()

    def revert_script(self):
        if self.draft is None:
            return
        self.editor.set_script(self.draft.orig, self.draft.orig)
        self.draft.text = self.draft.orig
        self.ctx.changes.update(self.draft)
        self.errors, self.notes = {}, []
        self.ctx.banner.clear("script-error")
        self.refresh_side()
        self._push_errors(False)

    def insert_hash(self):
        name, ok = QInputDialog.getText(
            self, "Insert a hashed name",
            "Type the name, like CSmoke02. Ship turns it into the hash.")
        if ok and name.strip():
            self.editor.textCursor().insertText(f'HASH("{name.strip()}")')

    def open_batch(self):
        sel = self.editor.textCursor().selectedText().replace(" ", "\n")
        if not sel.strip():
            QMessageBox.information(
                self, "Select an example call",
                "Highlight one call in the editor first, like a whole AddFear(...) "
                "line.")
            return
        dlg = BatchDialog(self.editor.toPlainText(), sel, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_text is not None:
            self.editor.setPlainText(dlg.result_text)
            self.ctx.log.stamp(f"batch edit: {dlg.summary}")

    def _other_containers(self):
        if self.draft is not None:
            if not self.draft.edited:
                self.ctx.banner.show_message(
                    "Other containers are looked up once you have changed this script.",
                    "warn")
                return
            self.ctx.show_changes(self.draft.key)

    def _refresh_other(self):
        d = self.draft
        w = self.ctx.planner.where.get(d.key) if d is not None else None
        if w is not None and w.status == "ok":
            n = len(w.copies)
            self.other_btn.setText("Only in this container" if not n else
                                   f"Also in {n} other container{'s' if n != 1 else ''}…")
        elif w is not None and w.status == "busy":
            self.other_btn.setText("Looking for other containers…")
        else:
            self.other_btn.setText("Also in other containers…")

    def _show_diff(self):
        if self.draft is not None:
            self.ctx.show_changes(self.draft.key)

    # -- outline and checks ----------------------------------------------------------
    def refresh_side(self):
        d = self.draft
        self.outline.clear()
        if d is None:
            return
        changed = set(d.functions()) if d.edited else set()
        funcs = functions(d.text)
        for name, line, _b in funcs:
            it = QTreeWidgetItem([("● " if name in changed else "   ") + name])
            it.setData(0, Qt.UserRole, line)
            self.outline.addTopLevelItem(it)
        if not funcs:
            self.outline.addTopLevelItem(QTreeWidgetItem(["   (data script, no functions)"]))
        self._live_pip()
        self._set_checks(changed)

    def _live_pip(self):
        """PiP: space left and structure problems, live (once the unit is parsed)."""
        d = self.draft
        self.budget = None
        live = {}
        if d is not None and d.game == "pip" and self.ctx.planner.is_warm(d.lu):
            try:
                self.budget = backend.pip_budget(d.lu, d.index, d.text)
            except Exception:
                self.budget = None
            for p in (self.budget or {}).get("problems", []) or []:
                live.setdefault(int(p.get("line") or 0), p.get("message", ""))
            enc = (self.budget or {}).get("encoding_error")
            if enc:
                live.setdefault(int(enc.get("line") or 0), enc.get("message", ""))
        live.pop(0, None)
        if live != self.live:
            self.live = live
            self._push_errors(False)

    def _clear_checks(self):
        while self.checks.count():
            w = self.checks.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _add_check(self, text, kind, line=None):
        lb = label(("✓ " if kind == "ok" else "! " if kind == "warn" else "✕ ") + text,
                   kind, True)
        if line:
            lb.setText(lb.text() + f'  <a href="#{line}">Go to line {line}</a>')
            lb.setTextFormat(Qt.RichText)
            lb.linkActivated.connect(lambda _h, n=line: self.editor.goto_line(n))
        self.checks.addWidget(lb)

    def _add_meter(self, b):
        limit = int(b.get("limit") or 0)
        used = b.get("edited_size")
        left = b.get("bytes_left")
        if used is None or not limit:
            return
        bar = QProgressBar()
        bar.setRange(0, limit)
        bar.setValue(max(0, min(limit, used)))
        bar.setTextVisible(False)
        if left is not None and left >= 0:
            kind, txt = ("warn" if left < limit * 0.05 else "ok"), \
                f"{left} bytes left of {limit}"
        elif b.get("fits"):
            kind, txt = "warn", f"{-left} bytes over, fits after squeezing whitespace"
        else:
            kind, txt = "err", f"too large by {-(b.get('bytes_left_squeezed') or left)} bytes"
        bar.setStyleSheet("QProgressBar::chunk { background: %s; }" % style.color(kind))
        bar.setObjectName("meter")
        self.checks.addWidget(label("SPACE IN THIS SCRIPT", "muted"))
        self.checks.addWidget(bar)
        self.checks.addWidget(label(txt, kind, True))
        self.checks.addWidget(label("Edits must fit the original space or the game hangs "
                                    "at boot.", "muted", True))

    def _set_checks(self, changed):
        self._clear_checks()
        d = self.draft
        if d.game == "pip":
            if self.budget is not None:
                self._add_meter(self.budget)
            elif self.ctx.planner.is_warm(d.lu):
                self.checks.addWidget(label("Space: this script's slot could not be "
                                            "measured.", "muted", True))
            else:
                self.checks.addWidget(label("Measuring space… (the first time for a big unit "
                                            "can take a while)", "muted", True))
        merged = {**self.live, **self.errors}
        for line, msg in sorted(merged.items()):
            self._add_check(msg, "err", line)
        for line, msg in self._warns():
            self._add_check(msg, "warn", line or None)
        if d.edited:
            if changed:
                self._add_check(f"You changed {len(changed)} function(s): " +
                                ", ".join(sorted(changed)[:6]) +
                                ". Ship recompiles only what you changed.", "ok")
            elif d.game == "nb1":
                self._add_check("Your edit is outside any named function. Ship will say "
                                "if it can't use it.", "warn")
        else:
            self.checks.addWidget(label("No edits yet.", "muted"))
        self.checks.addStretch(1)

    def _cursor_error(self):
        line = self.editor.textCursor().blockNumber() + 1
        msg = self.editor.error_at(line)
        if msg:
            self.ctx.log.message.emit(f"Line {line}: {msg}", "info")

    # -- errors ---------------------------------------------------------------------
    def _push_errors(self, explicit):
        """Show check/ship errors and live problems in the editor and Problems list."""
        merged = {**self.live, **self.errors}
        self.editor.set_errors(merged)
        warns = self._warns()
        self._shown_warns = warns
        self.problems_changed.emit(
            [(m, ln, self) for ln, m in sorted(merged.items())] +
            [("Warning: " + m, ln, self) for ln, m in warns], explicit)
        if self.draft is not None:
            self._set_checks(set(self.draft.functions()) if self.draft.edited else set())

    def _warns(self):
        """[(line, text)]: check notes and, for PiP, unusual data values. Never blocking."""
        d = self.draft
        out = list(self.notes)
        if d is not None and d.game == "pip" and d.edited:
            self.ctx.planner.request_warnings(d)
            out += [(int(w.get("line") or 0), w.get("message", ""))
                    for w in self.ctx.planner.warnings_for(d)]
        return sorted(out)

    def _warns_changed(self):
        if self.draft is not None and self._warns() != self._shown_warns:
            self._push_errors(False)

    def show_errors(self, key, errs, failed=True):
        """Mark error lines [(line, message)] for the script `key`."""
        if self.draft is None or self.draft.key != key:
            self.stash = (key, errs)
            return
        self.errors = {ln: msg for ln, msg in errs if ln}
        self._push_errors(bool(errs))

    def discard_current(self, key):
        """A pending edit was discarded elsewhere: reload the editor if it shows it."""
        if self.draft is not None and self.draft.key == key:
            self.editor.set_script(self.draft.orig, self.draft.orig)
            self.draft.text = self.draft.orig
            self.errors, self.notes = {}, []
            self.refresh_side()
            self._push_errors(False)

    def jump_to(self, line):
        self.editor.goto_line(line)

    # -- check: ask the ship tool what it would do, write nothing ------------------------
    def check(self, then=None):
        """Recompile the edit without writing anything. `then(ok)`."""
        d = self.draft
        if d is None:
            return
        src = self.ctx.scratch_dir() / "check_edit.lua"
        src.write_text(d.text, encoding="utf-8")
        plan = backend.plan_output(self.ctx.project, self.ctx.settings, d.lu)

        def done(code, out, err):
            data = backend.parse_json(out)
            errs = backend.parse_errors(out, err)
            self.notes = [(n["line"], n["message"]) for n in backend.parse_notes(out, err)]
            ok = code == 0 and bool(data) and data.get("ok", False)
            if ok:
                self.errors = {}
                self._push_errors(False)
                names = [(n, ln) for n, ln in self._names(d, data)]
                what = ("recompile " + ", ".join(n for n, _ in names[:4])
                        if names else "have nothing to recompile")
                self.ctx.banner.show_message(
                    f"{d.name}: the check passed. Ship would {what}. Nothing was written."
                    + (f" {len(self.notes)} note(s): see Checks." if self.notes else ""),
                    "warn" if self.notes else "ok", tag="script-error")
            else:
                pairs = [(e.get("line") or 0, e.get("message", "")) for e in errs]
                self.errors = {ln: m for ln, m in pairs if ln}
                self._push_errors(True)
                first = errs[0] if errs else {"kind": "error", "message": "See the log.",
                                              "line": 0}
                text, _f = backend.friendly(first, d.game)
                self.ctx.banner.show_message(
                    f"{d.name}: the check found a problem" +
                    (f" on line {first['line']}" if first.get("line") else "") + f". {text}",
                    "err", tag="script-error")
            if then:
                then(ok)
        self.ctx.runner.run(
            backend.ship_argv(self.ctx.settings, d.lu, [(d.index, src)], plan.out,
                              preview=True),
            cwd=APPDIR, title=f"Checking {d.name}", quiet=True, on_done=done)

    @staticmethod
    def _names(d, data):
        """[(function name, line)] from a preview result for script `d`."""
        funcs = functions(d.text)
        out = []
        for s in data.get("scripts", []):
            if s.get("index") != d.index:
                continue
            for f in s.get("functions", []):
                line, name = f.get("line", 0), "top-level code"
                for n, ln, _b in funcs:
                    if line and ln <= line:
                        name = n
                out.append((name, line))
        return out
