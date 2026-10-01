"""Small shared widgets: log, problems list, bottom dock, banner, path row, tool form."""
import datetime
import shlex
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .paths import APPDIR, tool_argv
from .settings import save_settings


def mono_font(size=10):
    f = QFont("Consolas", size)
    f.setStyleHint(QFont.Monospace)
    return f


def label(text, name=None, wrap=False):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


# ----------------------------------------------------------------- log
class LogPanel(QWidget):
    """Everything that ran, with the exact command line for each run."""
    message = Signal(str, str)              # (text, kind) for the status strip

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.entries = []                   # (kind, text)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.show_cmds = QCheckBox("Show commands")
        self.show_cmds.setChecked(bool(settings.get("show_commands", True)))
        self.show_cmds.toggled.connect(self._toggle)
        b_copy = QPushButton("Copy last command")
        b_copy.clicked.connect(self.copy_last)
        b_save = QPushButton("Save log…")
        b_save.clicked.connect(self.save)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.clear)
        bar.addWidget(self.show_cmds)
        bar.addStretch(1)
        for b in (b_copy, b_save, b_clear):
            bar.addWidget(b)
        v.addLayout(bar)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setFont(mono_font())
        self.box.setMaximumBlockCount(20000)
        v.addWidget(self.box)

    def _render(self, kind, text):
        return f"run: {text}" if kind == "cmd" else text

    def _append(self, kind, text):
        if kind == "cmd" and not self.show_cmds.isChecked():
            return
        cur = self.box.textCursor()
        cur.movePosition(QTextCursor.End)
        self.box.setTextCursor(cur)
        s = self._render(kind, text)
        self.box.insertPlainText(s if s.endswith("\n") else s + "\n")
        sb = self.box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _add(self, kind, text):
        self.entries.append((kind, text))
        del self.entries[:-5000]
        self._append(kind, text)

    def write(self, text, kind="out"):
        if text:
            self._add(kind, text)
            if kind == "err":
                self.message.emit(text.strip().splitlines()[-1], "err")

    def stamp(self, msg):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        self._add("stamp", f"\n[{t}] {msg}")
        self.message.emit(msg, "info")

    def command(self, cmdline):
        self.stamp("running a tool")
        self._add("cmd", cmdline)

    def _toggle(self, on):
        self.settings["show_commands"] = bool(on)
        save_settings(self.settings)
        self.box.clear()
        for kind, text in self.entries:
            self._append(kind, text)

    def last_command(self):
        for kind, text in reversed(self.entries):
            if kind == "cmd":
                return text
        return ""

    def copy_last(self):
        QGuiApplication.clipboard().setText(self.last_command())

    def clear(self):
        self.entries.clear()
        self.box.clear()

    def save(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save log", "seamripper.log",
                                            "Log (*.log *.txt)")
        if fn:
            Path(fn).write_text("\n".join(self._render(k, t) for k, t in self.entries),
                                encoding="utf-8")


class ProblemsList(QListWidget):
    """Clickable problems: each row can jump to a script line."""
    jump = Signal(object, int)              # (context, line)

    def __init__(self):
        super().__init__()
        self.setObjectName("rowlist")
        self.itemActivated.connect(self._go)
        self.itemClicked.connect(self._go)

    def set_problems(self, problems):
        """problems: [(text, line or None, context)]"""
        self.clear()
        for text, line, ctx in problems:
            it = QListWidgetItem(("Line %d: " % line if line else "") + text)
            it.setData(Qt.UserRole, (ctx, line))
            self.addItem(it)

    def _go(self, item):
        ctx, line = item.data(Qt.UserRole)
        if line:
            self.jump.emit(ctx, line)


class BottomDock(QWidget):
    """Collapsed to one status line; opens to Problems | Log."""
    opened_changed = Signal(bool)

    def __init__(self, log, problems):
        super().__init__()
        self.log, self.problems = log, problems
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        strip = QFrame()
        strip.setObjectName("dockstrip")
        h = QHBoxLayout(strip)
        h.setContentsMargins(8, 3, 8, 3)
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.clicked.connect(lambda: self.set_open(not self.is_open()))
        self.last = QLabel("Ready")
        self.last.setObjectName("muted")
        self.count = QLabel("")
        h.addWidget(self.toggle)
        h.addWidget(self.last, 1)
        h.addWidget(self.count)
        v.addWidget(strip)
        self.tabs = QTabWidget()
        self.tabs.addTab(problems, "Problems")
        self.tabs.addTab(log, "Log")
        self.tabs.setCurrentIndex(1)
        self.tabs.setMinimumHeight(120)
        v.addWidget(self.tabs)
        self.tabs.setVisible(False)
        self._sync()
        log.message.connect(self.on_message)

    def is_open(self):
        return self.tabs.isVisible()

    def set_open(self, on, tab=None):
        self.tabs.setVisible(on)
        if tab is not None:
            self.tabs.setCurrentIndex(tab)
        self._sync()
        self.opened_changed.emit(on)

    def _sync(self):
        self.toggle.setText("▾" if self.is_open() else "▸")
        self.toggle.setToolTip("Hide the log" if self.is_open() else "Show problems and the log")

    def on_message(self, text, kind):
        self.last.setText(text.strip().splitlines()[-1][:160] if text.strip() else "Ready")
        if kind == "err" and not self.is_open():
            self.set_open(True, 0 if self.problems.count() else 1)

    def set_problem_count(self, n, open_=False):
        self.count.setText(f"{n} problem" + ("" if n == 1 else "s") if n else "No problems")
        self.count.setObjectName("err" if n else "muted")
        self.count.style().unpolish(self.count)
        self.count.style().polish(self.count)
        self.tabs.setTabText(0, f"Problems ({n})" if n else "Problems")
        if n and open_ and not self.is_open():
            self.set_open(True, 0)


# ----------------------------------------------------------------- banner
class Banner(QFrame):
    """A message strip above the main area (used instead of pop-up boxes)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("banner")
        self.tag = ""
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 8, 6)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h.addWidget(self.text, 1)
        self.actions = QHBoxLayout()
        h.addLayout(self.actions)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.clicked.connect(self.hide)
        h.addWidget(close)
        self.hide()

    def clear(self, tag):
        """Hide the banner if it is showing a message with this tag."""
        if self.tag == tag and self.isVisible():
            self.hide()

    def show_message(self, text, kind="ok", actions=(), tag=""):
        """kind: ok | warn | err.  actions: [(label, callback)].  A `tag` lets the
        page that showed the message take it down when it stops being true."""
        self.tag = tag
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.text.setText(text)
        while self.actions.count():
            w = self.actions.takeAt(0).widget()
            if w:
                w.deleteLater()
        for lab, fn in actions:
            b = QPushButton(lab)
            b.clicked.connect(fn)
            self.actions.addWidget(b)
        self.show()


class NotAvailableNote(QFrame):
    """Shown where a feature isn't connected yet: says so plainly."""

    def __init__(self, what, hint=""):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        t = QLabel(f"<b>{what}</b> is not available yet.")
        t.setWordWrap(True)
        v.addWidget(t)
        if hint:
            h = label(hint, "muted", True)
            v.addWidget(h)


# ----------------------------------------------------------------- path row
class PathRow(QWidget):
    """A line edit + Browse button for a file or folder."""

    def __init__(self, kind, settings, patterns="All files (*.*)", multi=False):
        super().__init__()
        self.kind, self.settings, self.patterns, self.multi = kind, settings, patterns, multi
        self.dirty = False                  # the user typed or browsed here
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setMinimumHeight(26)
        self.edit.textEdited.connect(lambda *_: setattr(self, "dirty", True))
        h.addWidget(self.edit, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self.browse)
        h.addWidget(b)

    def browse(self):
        start = self.settings.get("last_dir", str(APPDIR))
        if not Path(start).exists():
            start = str(APPDIR)
        # Qt's own dialog: the native Windows one can crash on some setups.
        opts = QFileDialog.DontUseNativeDialog
        if self.kind == "paths":
            dlg = QFileDialog(self, "Select file(s), or use 'Choose folder instead'", start)
            dlg.setOptions(opts)
            dlg.setFileMode(QFileDialog.ExistingFiles)
            if self.patterns:
                dlg.setNameFilter(self.patterns)
            btn = QPushButton("Choose folder instead…")
            picked = {"dir": None}

            def pickdir():
                d = QFileDialog.getExistingDirectory(self, "Select folder", start, opts)
                if d:
                    picked["dir"] = d
                    dlg.reject()
            btn.clicked.connect(pickdir)
            lay = dlg.layout()
            if lay is not None:
                lay.addWidget(btn, lay.rowCount(), 0, 1, -1)
            paths = dlg.selectedFiles() if dlg.exec() else []
            if picked["dir"]:
                paths = [picked["dir"]]
        elif self.kind == "folder":
            fn = QFileDialog.getExistingDirectory(self, "Select folder", start, opts)
            paths = [fn] if fn else []
        elif self.kind == "savefile":
            fn, _ = QFileDialog.getSaveFileName(self, "Save as", start, self.patterns, options=opts)
            paths = [fn] if fn else []
        elif self.multi:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select file(s)", start, self.patterns, options=opts)
        else:
            fn, _ = QFileDialog.getOpenFileName(self, "Select file", start, self.patterns, options=opts)
            paths = [fn] if fn else []
        if not paths:
            return
        self.set_value(" ".join(shlex.quote(p) for p in paths) if len(paths) > 1 else paths[0])
        self.dirty = True
        ref = paths[0]
        self.settings["last_dir"] = str(ref if self.kind == "folder" else Path(ref).parent)
        save_settings(self.settings)

    def set_value(self, text):
        self.edit.setText(str(text))

    def value(self):
        return self.edit.text().strip()


# ----------------------------------------------------------------- tool form
class ToolForm(QGroupBox):
    """A form built from a spec, one per command-line tool.
    spec = {title, script, sub (optional), help, fields:[...]};
    field = {label, kind: openfile|savefile|folder|paths|text|flag|choice,
             flag (optional '--x'), patterns, choices, default, required, fill}.
    `fill` says what to prefill: 'file' (the selected container), 'paths'
    (the selected container, or the project folder), 'folder' (the project
    folder) or 'out' (a folder under
    the project's exports)."""

    def __init__(self, spec, ctx, plain_title=False):
        super().__init__("" if plain_title else spec["title"])
        self.spec, self.ctx = spec, ctx
        self.widgets = {}
        lay = QVBoxLayout(self)
        if spec.get("help"):
            lay.addWidget(label(spec["help"], "muted", True))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)
        for f in spec["fields"]:
            k = f["kind"]
            if k in ("openfile", "savefile", "folder", "paths"):
                w = PathRow(k, ctx.settings, f.get("patterns", "All files (*.*)"),
                            multi=f.get("multi", k == "paths"))
            elif k == "flag":
                w = QCheckBox()
                w.setChecked(bool(f.get("default", False)))
            elif k == "choice":
                w = QComboBox()
                w.addItems(f["choices"])
            else:
                w = QLineEdit()
                w.setMinimumHeight(26)
                w.setText(str(f.get("default", "")))
            form.addRow(f["label"], w)
            self.widgets[f["label"]] = (f, w)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.run_btn = QPushButton(spec.get("button", "Run"))
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def prefill(self):
        """Fill empty, untouched path fields from the current selection."""
        proj, cur = self.ctx.project, self.ctx.current_file
        for f, w in self.widgets.values():
            if not isinstance(w, PathRow) or w.dirty:
                continue
            fill = f.get("fill")
            if fill == "file" and cur:
                w.set_value(cur)
            elif fill == "folder" and proj:
                w.set_value(proj.folder)
            elif fill == "paths" and (cur or proj):
                w.set_value(cur or proj.folder)
            elif fill == "out" and proj:
                w.set_value(proj.exports_dir(self.spec["title"].lower().replace(" ", "_")))

    def _val(self, f, w):
        if isinstance(w, PathRow):
            return w.value()
        if f["kind"] == "flag":
            return w.isChecked()
        if f["kind"] == "choice":
            return w.currentText()
        return w.text().strip()

    def argv(self):
        """The command line for the current field values, or None if a
        required field is empty (the log says which)."""
        argv = tool_argv(self.ctx.settings, self.spec["script"])
        if self.spec.get("sub"):
            argv.append(self.spec["sub"])
        pos, opt = [], []
        for name, (f, w) in self.widgets.items():
            v = self._val(f, w)
            if f["kind"] == "flag":
                if v and f.get("flag"):
                    opt.append(f["flag"])
                continue
            if not v:
                if f.get("required"):
                    self.ctx.log.stamp(f"{self.spec['title']}: '{name}' is required.")
                    return None
                continue
            if f.get("flag"):
                opt += [f["flag"], v]
            elif f.get("multi") or f["kind"] == "paths":
                pos += shlex.split(v)
            else:
                pos.append(v)
        return argv + pos + opt

    def run(self):
        argv = self.argv()
        if argv:
            for f, w in self.widgets.values():      # make sure an output folder exists
                if f["kind"] == "folder" and f.get("flag") and self._val(f, w):
                    try:
                        Path(self._val(f, w)).mkdir(parents=True, exist_ok=True)
                    except OSError:
                        pass
            self.ctx.runner.run(argv, cwd=APPDIR, title=self.spec["title"])
