#!/usr/bin/env python3
r"""Seam Ripper - a tabbed GUI front-end for the Naughty Bear modding toolkit.

Tabs separate tools by category. Each tool is a small form: click to pick a
file or folder, set options, hit Run. A shared log panel at the bottom shows
every command and all of its output, and can be saved.

The GUI never reimplements a tool. It runs your existing .py scripts via the
same Python, so the tested CLI logic stays authoritative. Settings (paths to
luac51.exe, unluac.jar, your build's assets\lu) are remembered between runs.

Run:  python SeamRipper.py
Needs: PySide6  (pip install PySide6)
"""
import sys, json, datetime, shlex
from pathlib import Path

# --------------------------------------------------------------- frozen shim
# When packaged with PyInstaller there is no system python to shell out to.
# Instead the GUI relaunches its own EXE as  SeamRipper.exe --tool <script> ...
# and this shim (which must run BEFORE the Qt import, so tool subprocesses
# never pay the GUI's startup cost) executes the bundled script in-process.
FROZEN = getattr(sys, "frozen", False)
# BUNDLE: where the tool .py files / luac51.exe / unluac.jar live (read-only
# inside the PyInstaller bundle). APPDIR: writable dir next to the EXE for
# settings and temp files.
if hasattr(sys, "_MEIPASS"):
    BUNDLE = Path(sys._MEIPASS)
    APPDIR = Path(sys.executable).resolve().parent
else:
    BUNDLE = APPDIR = Path(__file__).resolve().parent

if FROZEN and len(sys.argv) >= 3 and sys.argv[1] == "--tool":
    # PyInstaller can't runpy.run_path a bundled .py as __main__ (the archive
    # has no __main__ for it), so import the tool module and call its main().
    stem = Path(sys.argv[2]).stem                  # no path escapes
    sys.argv = [stem] + sys.argv[3:]
    sys.path.insert(0, str(BUNDLE))
    try:
        import importlib
        mod = importlib.import_module(stem)
        if hasattr(mod, "main"):
            mod.main()
        else:
            # fallback: exec the source with __name__ == "__main__"
            src = (BUNDLE / f"{stem}.py").read_text(encoding="utf-8")
            g = {"__name__": "__main__", "__file__": str(BUNDLE / f"{stem}.py")}
            exec(compile(src, str(BUNDLE / f"{stem}.py"), "exec"), g)
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QFont, QAction, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QFileDialog,
    QCheckBox, QComboBox, QSplitter, QListWidget, QGroupBox, QMessageBox,
    QFormLayout, QStatusBar, QScrollArea, QSizePolicy, QDialog, QDialogButtonBox,
    QSpinBox
)

HERE = APPDIR                       # legacy name: writable app dir
SETTINGS_PATH = APPDIR / "seamripper_settings.json"


def tool_argv(settings, script, *args):
    """argv to run one of the toolkit scripts, source-run or frozen.
    Source-run: scripts live in tools/ (see seamripper.spec's TOOLS_DIR).
    Frozen: PyInstaller bundles everything flat regardless of source
    layout (spec datas dest is always "."), so the frozen branch is
    unaffected by where tools/ sits in the repo."""
    if FROZEN:
        return [sys.executable, "--tool", script, *args]
    return [settings["python"], str(BUNDLE / "tools" / script), *args]


# ----------------------------------------------------------------- settings
def _bundled(name):
    """Path to a bundled binary (luac51.exe, unluac.jar): flat in a frozen
    build (spec datas dest is always "."), inside tools/ when run from
    source (see tool_argv's docstring for why these differ)."""
    return BUNDLE / name if FROZEN else BUNDLE / "tools" / name


def load_settings():
    d = {
        "python": sys.executable,
        "luac": str(_bundled("luac51.exe")),
        "jar": str(_bundled("unluac.jar")),
        "stage": "",
        "last_dir": str(APPDIR),
    }
    if SETTINGS_PATH.exists():
        try:
            d.update(json.loads(SETTINGS_PATH.read_text()))
        except Exception:
            pass
    # saved paths from another machine/install: fall back to the bundle
    for key, name in (("luac", "luac51.exe"), ("jar", "unluac.jar")):
        if not Path(d[key]).exists() and _bundled(name).exists():
            d[key] = str(_bundled(name))
    if FROZEN or not Path(d["python"]).exists():
        d["python"] = sys.executable
    return d


def save_settings(d):
    try:
        SETTINGS_PATH.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


# ----------------------------------------------------------------- log panel
class LogPanel(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Log"))
        bar.addStretch(1)
        b_save = QPushButton("Save log…"); b_save.clicked.connect(self.save)
        b_clear = QPushButton("Clear"); b_clear.clicked.connect(lambda: self.box.clear())
        bar.addWidget(b_save); bar.addWidget(b_clear)
        v.addLayout(bar)
        self.box = QPlainTextEdit(); self.box.setReadOnly(True)
        self.box.setFont(QFont("Consolas", 10))
        self.box.setMaximumBlockCount(20000)
        v.addWidget(self.box)

    def write(self, text, kind="out"):
        if not text:
            return
        cur = self.box.textCursor(); cur.movePosition(QTextCursor.End)
        self.box.setTextCursor(cur)
        self.box.insertPlainText(text if text.endswith("\n") else text + "\n")
        self.box.verticalScrollBar().setValue(self.box.verticalScrollBar().maximum())

    def stamp(self, msg):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        self.write(f"\n[{t}] {msg}")

    def save(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save log", "seamripper.log",
                                            "Log (*.log *.txt)")
        if fn:
            Path(fn).write_text(self.box.toPlainText(), encoding="utf-8")


# ----------------------------------------------------------------- runner
class Runner:
    """Runs one command at a time via QProcess, streaming output to the log."""
    def __init__(self, log, status):
        self.log = log
        self.status = status
        self.proc = None
        self._on_done = None

    def busy(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def run(self, argv, cwd=None, on_done=None):
        if self.busy():
            self.log.stamp("A task is already running; wait for it to finish.")
            return
        self._on_done = on_done
        self.proc = QProcess()
        if cwd:
            self.proc.setWorkingDirectory(str(cwd))
        self.proc.readyReadStandardOutput.connect(self._out)
        self.proc.readyReadStandardError.connect(self._err)
        self.proc.finished.connect(self._fin)
        self.log.stamp("run: " + " ".join(shlex.quote(a) for a in argv))
        self.status.showMessage("Running…")
        try:
            self.proc.start(argv[0], argv[1:])
        except Exception as e:
            self.log.write(f"failed to start: {e}")
            self.status.showMessage("Error", 4000)

    def _out(self):
        self.log.write(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace").rstrip("\n"))

    def _err(self):
        self.log.write(bytes(self.proc.readAllStandardError()).decode("utf-8", "replace").rstrip("\n"))

    def _fin(self, code, _status):
        self.log.stamp(f"done (exit {code})")
        self.status.showMessage("Done" if code == 0 else f"Exit {code}", 4000)
        cb, self._on_done = self._on_done, None
        self.proc = None
        if cb:
            cb(code)


# ----------------------------------------------------------------- path row
class PathRow(QWidget):
    """A label + line edit + Browse button for a file or folder."""
    def __init__(self, label, kind, settings, patterns="All files (*.*)", multi=False):
        super().__init__()
        self.kind = kind; self.settings = settings; self.patterns = patterns
        self.multi = multi
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        if label:
            h.addWidget(QLabel(label), 0)
        self.edit = QLineEdit(); self.edit.setMinimumHeight(26)
        h.addWidget(self.edit, 1)
        b = QPushButton("Browse…"); b.clicked.connect(self.browse)
        h.addWidget(b, 0)

    def browse(self):
        start = self.settings.get("last_dir", str(HERE))
        if not Path(start).exists():
            start = str(HERE)
        # Qt's own dialog (not the native one) — the native Windows dialog can
        # hard-crash some setups; this avoids that path entirely.
        opts = QFileDialog.DontUseNativeDialog
        try:
            if self.kind == "paths":
                # accept one-or-more files OR a folder. Default to file
                # selection; a checkbox row in the dialog switches to folder.
                dlg = QFileDialog(self, "Select file(s) — or use 'Choose folder'", start)
                dlg.setOptions(opts)
                dlg.setFileMode(QFileDialog.ExistingFiles)
                if self.patterns:
                    dlg.setNameFilter(self.patterns)
                btn = QPushButton("Choose folder instead…")
                folder_choice = {"dir": None}
                def _pickdir():
                    d = QFileDialog.getExistingDirectory(self, "Select folder", start, opts)
                    if d:
                        folder_choice["dir"] = d
                        dlg.reject()
                btn.clicked.connect(_pickdir)
                lay = dlg.layout()
                if lay is not None:
                    lay.addWidget(btn, lay.rowCount(), 0, 1, -1)
                paths = dlg.selectedFiles() if dlg.exec() else []
                if folder_choice["dir"]:
                    paths = [folder_choice["dir"]]
            elif self.kind == "folder":
                fn = QFileDialog.getExistingDirectory(self, "Select folder", start, opts)
                paths = [fn] if fn else []
            elif self.kind == "savefile":
                fn, _ = QFileDialog.getSaveFileName(self, "Save as", start, self.patterns, options=opts)
                paths = [fn] if fn else []
            elif self.multi:
                files, _ = QFileDialog.getOpenFileNames(self, "Select file(s)", start, self.patterns, options=opts)
                paths = files
            else:
                fn, _ = QFileDialog.getOpenFileName(self, "Select file", start, self.patterns, options=opts)
                paths = [fn] if fn else []
        except Exception as e:
            self.edit.setToolTip(f"file dialog error: {e}")
            return
        if not paths:
            return
        if self.multi and len(paths) > 1:
            self.edit.setText(" ".join(shlex.quote(p) for p in paths))
        else:
            self.edit.setText(paths[0])
        ref = paths[0]
        self.settings["last_dir"] = str(ref if self.kind == "folder" else Path(ref).parent)
        save_settings(self.settings)

    def value(self):
        return self.edit.text().strip()


# ----------------------------------------------------------------- generic tool form
class ToolForm(QGroupBox):
    """Spec-driven form. spec = {title, script, sub(optional), fields:[...]}.
    field = {label, kind: openfile|savefile|folder|text|flag|choice,
             flag(optional '--x'), patterns, choices, default}."""
    def __init__(self, spec, runner, settings):
        super().__init__(spec["title"])
        self.spec = spec; self.runner = runner; self.settings = settings
        self.widgets = {}
        lay = QVBoxLayout(self)
        if spec.get("help"):
            h = QLabel(spec["help"]); h.setWordWrap(True)
            h.setStyleSheet("color:#888;")
            lay.addWidget(h)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)
        for f in spec["fields"]:
            k = f["kind"]
            if k in ("openfile", "savefile", "folder", "paths"):
                w = PathRow("", k, settings, f.get("patterns", "All files (*.*)"),
                            multi=f.get("multi", k == "paths"))
                form.addRow(f["label"], w)
            elif k == "flag":
                w = QCheckBox(); w.setChecked(bool(f.get("default", False)))
                form.addRow(f["label"], w)
            elif k == "choice":
                w = QComboBox(); w.addItems(f["choices"]); w.setMinimumHeight(26)
                form.addRow(f["label"], w)
            else:
                w = QLineEdit(); w.setMinimumHeight(26); w.setText(str(f.get("default", "")))
                form.addRow(f["label"], w)
            self.widgets[f["label"]] = (f, w)
        lay.addLayout(form)
        run = QPushButton("Run " + spec["title"])
        run.clicked.connect(self.run)
        lay.addWidget(run)
        # never let a form shrink below its natural height; the scroll area
        # scrolls instead of crushing the rows together.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _val(self, w, kind):
        if kind in ("openfile", "savefile", "folder", "paths"):
            return w.value()
        if kind == "flag":
            return w.isChecked()
        if kind == "choice":
            return w.currentText()
        return w.text().strip()

    def run(self):
        argv = tool_argv(self.settings, self.spec["script"])
        if self.spec.get("sub"):
            argv.append(self.spec["sub"])
        positionals, optionals = [], []
        for label, (f, w) in self.widgets.items():
            v = self._val(w, f["kind"])
            if f["kind"] == "flag":
                if v and f.get("flag"):
                    optionals += [f["flag"]]
                continue
            if not v:
                if f.get("required"):
                    self.runner.log.stamp(f"{self.spec['title']}: '{label}' is required.")
                    return
                continue
            if f.get("flag"):
                optionals += [f["flag"], v]
            else:
                positionals += (shlex.split(v)
                                if (f.get("multi") or f["kind"] == "paths")
                                else [v])
        argv += positionals + optionals
        self.runner.run(argv, cwd=APPDIR)


# ----------------------------------------------------------------- Lua tab (custom)
class LuaTab(QWidget):
    def __init__(self, runner, settings):
        super().__init__()
        self.runner = runner; self.settings = settings
        self.cur_lu = ""; self.tmp_lua = HERE / "_sr_edit.lua"
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.lu = PathRow(".lu file:", "openfile", settings, "Lu container (*.lu);;All (*.*)")
        top.addWidget(self.lu, 1)
        b_list = QPushButton("List chunks"); b_list.clicked.connect(self.list_chunks)
        top.addWidget(b_list)
        self.luadec = QCheckBox("use luadec (cleaner)"); self.luadec.setChecked(True)
        top.addWidget(self.luadec)
        root.addLayout(top)

        mid = QSplitter(Qt.Horizontal)
        left = QWidget(); lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Chunks (click, then Read):"))
        self.chunks = QListWidget(); self.chunks.itemDoubleClicked.connect(self.read_chunk)
        lv.addWidget(self.chunks)
        b_read = QPushButton("Read selected → editor"); b_read.clicked.connect(self.read_chunk)
        lv.addWidget(b_read)
        mid.addWidget(left)

        right = QWidget(); rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Editor (edit bodies, not signatures):"))
        self.editor = QPlainTextEdit(); self.editor.setFont(QFont("Consolas", 10))
        rv.addWidget(self.editor)

        fr = QHBoxLayout()
        self.find_box = QLineEdit(); self.find_box.setPlaceholderText("find")
        self.repl_box = QLineEdit(); self.repl_box.setPlaceholderText("replace with")
        self.find_regex = QCheckBox("regex")
        b_repl = QPushButton("Replace all"); b_repl.clicked.connect(self.replace_all)
        b_batch = QPushButton("Batch edit calls…"); b_batch.clicked.connect(self.open_batch)
        fr.addWidget(self.find_box); fr.addWidget(self.repl_box)
        fr.addWidget(self.find_regex); fr.addWidget(b_repl); fr.addWidget(b_batch)
        rv.addLayout(fr)

        sh = QHBoxLayout()
        self.stage_after = QCheckBox("stage into build after ship")
        sh.addWidget(self.stage_after); sh.addStretch(1)
        b_ship = QPushButton("Ship"); b_ship.clicked.connect(self.ship)
        b_ship.setStyleSheet("font-weight:bold;")
        sh.addWidget(b_ship)
        rv.addLayout(sh)
        mid.addWidget(right)
        mid.setSizes([260, 640])
        root.addWidget(mid, 1)

        self.sel_chunk = None

    def _nblua(self, *args):
        return tool_argv(self.settings, "nblua.py", *args)

    def list_chunks(self):
        self.cur_lu = self.lu.value()
        if not self.cur_lu:
            self.runner.log.stamp("pick a .lu file first."); return
        self.chunks.clear()
        out_file = HERE / "_sr_list.txt"
        # capture list output by running and parsing the log is awkward; run and
        # read names from a temp via python -c is overkill — parse stdout here.
        proc = QProcess()
        proc.setWorkingDirectory(str(APPDIR))
        argv = tool_argv(self.settings, "nblua.py", "list", self.cur_lu)
        proc.start(argv[0], argv[1:])
        proc.waitForFinished(15000)
        text = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.runner.log.stamp("list chunks"); self.runner.log.write(text)
        for line in text.splitlines():
            line = line.strip()
            # rows look like:  name   size  0xhash
            if line and "0x" in line and not line.startswith("name"):
                name = line.split()[0]
                self.chunks.addItem(name)

    def _selected_name(self):
        it = self.chunks.currentItem()
        return it.text() if it else None

    def read_chunk(self, *_):
        name = self._selected_name()
        if not (self.cur_lu and name):
            self.runner.log.stamp("pick a .lu and select a chunk first."); return
        self.sel_chunk = name
        args = ["read", self.cur_lu, name, "-o", str(self.tmp_lua),
                "--luac", self.settings["luac"], "--jar", self.settings["jar"]]
        if self.luadec.isChecked():
            args.append("--luadec")
        def done(code):
            if code == 0 and self.tmp_lua.exists():
                self.editor.setPlainText(self.tmp_lua.read_text(encoding="utf-8", errors="replace"))
        self.runner.run(self._nblua(*args), cwd=APPDIR, on_done=done)

    def replace_all(self):
        find = self.find_box.text()
        if not find:
            return
        text = self.editor.toPlainText()
        if self.find_regex.isChecked():
            import re
            try:
                new, n = re.subn(find, self.repl_box.text(), text)
            except re.error as e:
                QMessageBox.warning(self, "Bad regex", str(e)); return
        else:
            n = text.count(find)
            new = text.replace(find, self.repl_box.text())
        if n:
            self.editor.setPlainText(new)
        self.runner.log.stamp(f"replace all: {n} substitution(s)")

    def open_batch(self):
        cursor = self.editor.textCursor()
        sel = cursor.selectedText()
        if not sel.strip():
            QMessageBox.information(
                self, "Select an example call",
                "Highlight one example call in the editor first, e.g. a full "
                "AddFear(...) line. The batch editor derives the pattern from it.")
            return
        dlg = BatchDialog(self.editor.toPlainText(), sel.replace("\u2029", "\n"), self)
        if dlg.exec() == QDialog.Accepted and dlg.result_text is not None:
            self.editor.setPlainText(dlg.result_text)
            self.runner.log.stamp(f"batch edit: {dlg.summary}")

    def ship(self):
        name = self.sel_chunk or self._selected_name()
        if not (self.cur_lu and name):
            self.runner.log.stamp("read a chunk before shipping."); return
        self.tmp_lua.write_text(self.editor.toPlainText(), encoding="utf-8")
        out = str(Path(self.cur_lu).with_name(Path(self.cur_lu).stem + "_edited.lu"))
        args = ["ship", self.cur_lu, name, str(self.tmp_lua), "-o", out,
                "--luac", self.settings["luac"], "--jar", self.settings["jar"]]
        if self.luadec.isChecked():
            args.append("--luadec")
        if self.stage_after.isChecked() and self.settings.get("stage"):
            args += ["--stage", self.settings["stage"]]
        self.runner.run(self._nblua(*args), cwd=APPDIR)


# ----------------------------------------------------------------- batch dialog
class BatchDialog(QDialog):
    """Select-and-mark editor. Given the full chunk source and one highlighted
    example call, split the call into slots, let the user tag each slot
    anchor/target/ignore and attach a scale/set/offset transform to targets,
    preview the matches, and apply."""

    def __init__(self, src, example_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch edit matching calls")
        self.src = src
        self.result_text = None
        self.summary = ""
        import lua_callsplit as cs
        import lua_batchedit as be
        self.cs = cs; self.be = be

        calls = cs.find_calls(example_text, self._guess_func(example_text))
        if not calls:
            QMessageBox.warning(self, "No call found",
                                "Couldn't parse a call out of the selection.")
            self.reject(); return
        self.func = calls[0].func
        self.pattern = be.build_pattern(example_text, calls[0])

        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Function: <b>{self.func}</b> — "
                           f"{self.pattern.arity} argument slot(s)"))

        self.uniform = QCheckBox("uniform: one transform for all target slots")
        self.uniform.setChecked(True)
        self.uniform.stateChanged.connect(self._sync_uniform)
        v.addWidget(self.uniform)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>#</b>"), 0, 0)
        grid.addWidget(QLabel("<b>example</b>"), 0, 1)
        grid.addWidget(QLabel("<b>role</b>"), 0, 2)
        grid.addWidget(QLabel("<b>op</b>"), 0, 3)
        grid.addWidget(QLabel("<b>value</b>"), 0, 4)
        self.rows = []
        for i, slot in enumerate(self.pattern.slots):
            r = i + 1
            grid.addWidget(QLabel(str(i)), r, 0)
            grid.addWidget(QLabel(slot.anchor_value), r, 1)
            role = QComboBox(); role.addItems(["anchor", "target", "ignore"])
            op = QComboBox(); op.addItems(["scale", "set", "offset"])
            val = QLineEdit()
            role.currentTextChanged.connect(self._sync_uniform)
            grid.addWidget(role, r, 2); grid.addWidget(op, r, 3); grid.addWidget(val, r, 4)
            self.rows.append((role, op, val))
        v.addLayout(grid)

        self.preview = QLabel("")
        v.addWidget(self.preview)
        b_prev = QPushButton("Preview matches"); b_prev.clicked.connect(self._do_preview)
        v.addWidget(b_prev)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._apply); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._sync_uniform()

    def _guess_func(self, text):
        import re
        m = re.search(r"([\w.]+[.:])?(\w+)\s*\(", text)
        return m.group(2) if m else ""

    def _sync_uniform(self, *_):
        uni = self.uniform.isChecked()
        first_target_op = None
        for role, op, val in self.rows:
            is_target = role.currentText() == "target"
            op.setEnabled(is_target and not uni or (is_target and first_target_op is None))
            val.setEnabled(is_target)
            if is_target and uni:
                if first_target_op is None:
                    first_target_op = (op, val); op.setEnabled(True); val.setEnabled(True)
                else:
                    op.setEnabled(False); val.setEnabled(False)

    def _build_pattern(self):
        be = self.be
        uni = self.uniform.isChecked()
        uni_op = uni_val = None
        if uni:
            for role, op, val in self.rows:
                if role.currentText() == "target":
                    uni_op, uni_val = op.currentText(), val.text(); break
        for slot, (role, op, val) in zip(self.pattern.slots, self.rows):
            t = role.currentText()
            slot.tag = {"anchor": be.Tag.ANCHOR, "target": be.Tag.TARGET,
                        "ignore": be.Tag.IGNORE}[t]
            if slot.tag is be.Tag.TARGET:
                o = uni_op if uni else op.currentText()
                p = uni_val if uni else val.text()
                slot.op = {"scale": be.Op.SCALE, "set": be.Op.SET,
                           "offset": be.Op.OFFSET}[o]
                slot.param = p
        return self.pattern

    def _do_preview(self):
        pat = self._build_pattern()
        matches = self.be.find_matches(self.src, pat)
        self.preview.setText(f"{len(matches)} call(s) match.")
        return matches

    def _apply(self):
        pat = self._build_pattern()
        matches = self.be.find_matches(self.src, pat)
        if not matches:
            QMessageBox.information(self, "No matches", "No calls matched; nothing changed.")
            return
        try:
            new_src, changes = self.be.apply(self.src, pat, matches)
        except ValueError as e:
            QMessageBox.warning(self, "Transform error", str(e)); return
        self.result_text = new_src
        self.summary = f"{len(matches)} call(s), {len(changes)} value(s) changed"
        self.accept()


# ----------------------------------------------------------------- main window
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Seam Ripper")
        # window / taskbar icon: load whichever bundled asset is present
        # (BUNDLE is the PyInstaller data dir when frozen, the source dir when
        # running from a checkout).
        for _ico in ("seamripper_256.png", "seamripper.ico", "seamripper_64.png"):
            _p = BUNDLE / _ico
            if _p.exists():
                self.setWindowIcon(QIcon(str(_p)))
                break
        self.resize(1100, 760)
        self.settings = load_settings()
        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.log = LogPanel()
        self.runner = Runner(self.log, self.status)

        tabs = QTabWidget()
        tabs.addTab(LuaTab(self.runner, self.settings), "Lua Code")
        tabs.addTab(self._text_tab(), "Text / Localization")
        tabs.addTab(self._assets_tab(), "Assets")
        tabs.addTab(self._pip_tab(), "Panic in Paradise")

        split = QSplitter(Qt.Vertical)
        split.addWidget(tabs); split.addWidget(self.log)
        split.setSizes([520, 240])
        self.setCentralWidget(split)
        self._menu()
        self.log.stamp("Seam Ripper ready. Set tool paths under Settings if needed.")

    # -- generic-tab builders ------------------------------------------------
    def _stack(self, specs):
        inner = QWidget(); v = QVBoxLayout(inner)
        v.setSpacing(12)
        for spec in specs:
            v.addWidget(ToolForm(spec, self.runner, self.settings))
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)
        return scroll

    def _text_tab(self):
        LU = "Lu container (*.lu);;All (*.*)"
        TXT = "Text (*.txt);;All (*.*)"
        return self._stack([
            {"title": "Extract strings", "script": "lu_strings.py", "sub": "extract",
             "help": "Dump a .lu's subtitle/localization strings to an editable text file. NB1 x36 and PiP LUH (language units like global.en_us.lu) are auto-detected.",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "out .txt", "kind": "savefile", "flag": "-o", "patterns": TXT}]},
            {"title": "Apply strings", "script": "lu_strings.py", "sub": "apply",
             "help": "Write your edited strings back into the .lu (raw, codec=0).",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "edited .txt", "kind": "openfile", "patterns": TXT, "required": True},
                        {"label": "out .lu", "kind": "savefile", "flag": "-o", "patterns": LU},
                        {"label": "verify", "kind": "flag", "flag": "--verify", "default": True}]},
            {"title": "Spelling report", "script": "lu_autofix.py", "sub": "report",
             "help": "Scan .lu files and list spelling/spacing candidates (review only).",
             "fields": [{"label": "folder or .lu", "kind": "paths", "required": True}]},
            {"title": "Spelling fix", "script": "lu_autofix.py", "sub": "fix",
             "fields": [{"label": "folder or .lu", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o", "required": True},
                        {"label": "also spacing", "kind": "flag", "flag": "--spacing"}]},
            {"title": "Grep text", "script": "lu_grep.py",
             "help": "Search localization text across .lu files.",
             "fields": [{"label": "pattern", "kind": "text", "required": True},
                        {"label": "folder or files", "kind": "paths", "required": True},
                        {"label": "ignore case", "kind": "flag", "flag": "-i"},
                        {"label": "regex", "kind": "flag", "flag": "-e"}]},
            {"title": "Repack raw", "script": "lu_repack.py",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "edited image", "kind": "openfile", "flag": "--image"},
                        {"label": "out .lu", "kind": "savefile", "flag": "-o", "patterns": LU},
                        {"label": "verify", "kind": "flag", "flag": "--verify"}]},
        ])

    def _assets_tab(self):
        LU = "Lu container (*.lu);;All (*.*)"
        return self._stack([
            {"title": "Container info", "script": "naughty_lu.py", "sub": "info",
             "help": "Show header / record info for .lu files.",
             "fields": [{"label": ".lu files", "kind": "openfile", "patterns": LU, "multi": True, "required": True}]},
            {"title": "Decompress image", "script": "naughty_lu.py", "sub": "decompress",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "out .bin", "kind": "savefile", "flag": "-o"}]},
            {"title": "Find a script", "script": "pip_scripts.py", "sub": "find",
             "help": "Which .lu holds a given script? Search a folder of "
                     ".lu files by script name (e.g. 'gamemodes') and get "
                     "back the file + record + embedded path. Works on both "
                     "PiP and NB1 containers.",
             "fields": [{"label": "script name", "kind": "text", "required": True},
                        {"label": ".lu files / folder to search", "kind": "paths", "required": True}]},
            {"title": "Extract chunks", "script": "naughty_lu.py", "sub": "extract",
             "help": "Extract every record from .lu files into an output tree.",
             "fields": [{"label": ".lu files", "kind": "openfile", "patterns": LU, "multi": True, "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o", "required": True}]},
            {"title": "Convert textures/meshes", "script": "lu_convert.py",
             "help": "Textures -> DDS + PNG (PNG needs Pillow); "
                     "meshes -> OBJ+MTL and GLB with embedded textures.",
             "fields": [{"label": "inputs (files/folder)", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"},
                        {"label": "OBJ only (skip GLB)", "kind": "flag", "flag": "--no-glb"}]},
            {"title": "Rigged character GLB", "script": "lu_rig.py",
             "help": "Export a skinned character/costume piece (skeleton + "
                     "weights) from an extracted unit directory. Chunk-type "
                     "driven, not game-specific — works on NB1 or PiP units.",
             "fields": [{"label": "extracted unit folder", "kind": "paths", "required": True},
                        {"label": "out .glb", "kind": "savefile", "flag": "-o",
                         "patterns": "glTF binary (*.glb);;All (*.*)", "required": True}]},
            {"title": "Sound: bank", "script": "lu_sound.py", "sub": "bank",
             "fields": [{"label": "inputs", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"}]},
            {"title": "Sound: streams", "script": "lu_sound.py", "sub": "streams",
             "fields": [{"label": "xma dir", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"}]},
        ])

    def _pip_tab(self):
        LU = "Lu container (*.lu);;All (*.*)"
        TXT = "Text (*.txt);;All (*.*)"
        GLB = "glTF binary (*.glb);;All (*.*)"
        return self._stack([
            {"title": "Dump everything", "script": "pip_dump.py",
             "help": "One-button bulk dump: chunks, textures, rigs, meshes, "
                     "Lua source, UI flash + textures, audio manifests. The "
                     "forms below run each stage individually.",
             "fields": [{"label": "game folder or files", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o", "required": True}]},
            {"title": "Find a script", "script": "pip_scripts.py", "sub": "find",
             "help": "Which .lu holds a given script? Search a folder of "
                     ".lu files by script name (e.g. 'gamemodes') and get "
                     "back the file + record + embedded path. Works on both "
                     "PiP and NB1 containers.",
             "fields": [{"label": "script name", "kind": "text", "required": True},
                        {"label": ".lu files / folder to search", "kind": "paths", "required": True}]},
            {"title": "Extract chunks", "script": "naughty_lu.py", "sub": "extract",
             "help": "Extract a PiP LUH .lu into raw chunks by type, with a "
                     "manifest per unit (LUH and NB1 x36 auto-detected).",
             "fields": [{"label": ".lu files / folder", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"}]},
            {"title": "Convert textures / meshes", "script": "lu_convert.py",
             "help": "Convert textures to DDS/PNG and meshes to OBJ+MTL/GLB. "
                     "Accepts a raw .lu, an extract folder, or .bin chunks. "
                     "For menu/UI units whose art is Scaleform-embedded, use "
                     "UI flash / textures instead.",
             "fields": [{"label": "extracted chunks (files/folder)", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"},
                        {"label": "OBJ only (skip GLB)", "kind": "flag", "flag": "--no-glb"}]},
            {"title": "Rigged character GLB", "script": "lu_rig.py",
             "help": "Export a skinned character/costume piece (skeleton + "
                     "weights) from an extracted unit directory.",
             "fields": [{"label": "extracted unit folder", "kind": "paths", "required": True},
                        {"label": "out .glb", "kind": "savefile", "flag": "-o",
                         "patterns": GLB, "required": True}]},
            {"title": "UI flash / textures", "script": "pip_gfx.py",
             "help": "Extract Scaleform UI movies (.gfx) and their embedded "
                     "textures as PNG from PiP .lu files or 04d00001 chunks.",
             "fields": [{"label": ".lu / chunk files", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"},
                        {"label": "keep raw DDS", "kind": "flag", "flag": "--dds"}]},
            {"title": "Lua source scripts", "script": "pip_scripts.py", "sub": "extract",
             "help": "Slice the plaintext Lua source out of extracted "
                     "animation chunks and rebuild the original script tree.",
             "fields": [{"label": "extract root(s)", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o", "required": True},
                        {"label": "flat layout", "kind": "flag", "flag": "--flat"}]},
            {"title": "Inject Lua script", "script": "pip_scripts.py", "sub": "inject",
             "help": "Write edited Lua source back into a PiP .lu: checks each "
                     "file's Lua structure, matches it to its chunk by source "
                     "path, fits it in place (or errors), and rebuilds the "
                     "container. Edits must fit the original slot.",
             "fields": [{"label": "original .lu", "kind": "openfile",
                         "patterns": "Lu container (*.lu);;All (*.*)", "required": True},
                        {"label": "edited .lua file(s)", "kind": "paths", "required": True},
                        {"label": "force (skip Lua check)", "kind": "flag", "flag": "--force"},
                        {"label": "out .lu", "kind": "savefile", "flag": "-o",
                         "patterns": "Lu container (*.lu);;All (*.*)", "required": True}]},
            {"title": "Extract strings", "script": "lu_strings.py", "sub": "extract",
             "help": "Dump a PiP language unit (global.en_us.lu etc.) to an "
                     "editable HASH<TAB>text file. 1,841 strings per language.",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "out .txt", "kind": "savefile", "flag": "-o", "patterns": TXT}]},
            {"title": "Apply strings", "script": "lu_strings.py", "sub": "apply",
             "help": "Write edited strings back into a rebuilt .lu (stored "
                     "segments; the retail engine loads these natively).",
             "fields": [{"label": ".lu", "kind": "openfile", "patterns": LU, "required": True},
                        {"label": "edited .txt", "kind": "openfile", "patterns": TXT, "required": True},
                        {"label": "out .lu", "kind": "savefile", "flag": "-o", "patterns": LU},
                        {"label": "verify", "kind": "flag", "flag": "--verify", "default": True}]},
            {"title": "Sound: bank", "script": "lu_sound.py", "sub": "bank",
             "help": "Characterise + extract the embedded SFX bank from a "
                     ".lu (LUH auto-detected). Unknown header shapes are "
                     "dumped raw and reported, never guessed into WAVs.",
             "fields": [{"label": ".lu or extracted unit", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"}]},
            {"title": "Sound: streams", "script": "lu_sound.py", "sub": "streams",
             "help": "Convert loose streams/*.xma to WAV (needs ffmpeg).",
             "fields": [{"label": "xma dir", "kind": "paths", "required": True},
                        {"label": "out folder", "kind": "folder", "flag": "-o"}]},
        ])

    # -- menu / settings -----------------------------------------------------
    def _menu(self):
        m = self.menuBar().addMenu("Settings")
        a = QAction("Tool paths…", self); a.triggered.connect(self._edit_paths)
        m.addAction(a)

    def _edit_paths(self):
        dlg = QWidget(self, Qt.Window); dlg.setWindowTitle("Tool paths")
        dlg.resize(560, 0); f = QFormLayout(dlg)
        rows = {}
        row_specs = [("python", "Python exe", "openfile"),
                     ("luac", "luac51.exe", "openfile"),
                     ("jar", "unluac.jar", "openfile"),
                     ("stage", "Build assets\\lu", "folder")]
        if FROZEN:              # tools run inside the EXE; no external python
            row_specs = row_specs[1:]
        for key, label, kind in row_specs:
            pr = PathRow("", kind, self.settings); pr.edit.setText(self.settings.get(key, ""))
            f.addRow(label, pr); rows[key] = pr
        save = QPushButton("Save")
        def do():
            for k, pr in rows.items():
                self.settings[k] = pr.value()
            save_settings(self.settings)
            self.log.stamp("settings saved."); dlg.close()
        save.clicked.connect(do); f.addRow(save)
        dlg.show()


def main():
    app = QApplication(sys.argv)
    w = Main(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
