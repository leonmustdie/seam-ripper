"""Sidebars and pages: Files, Search, History, Tools, Welcome."""
import os
import re
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView,
                               QLineEdit, QListWidget, QMenu, QPushButton,
                               QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import backend, style, toolspecs
from .paths import APPDIR
from .project import HIDDEN_DIRS
from .search import SearchRun
from .widgets import ToolForm, label


# ----------------------------------------------------------------- Files
class FilesSidebar(QWidget):
    opened = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.items = {}                     # path -> tree item
        self.modified = set()               # live files that differ from retail
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(label("FILES", "muted"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter…")
        self.filter.textChanged.connect(self._apply_filter)
        v.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setObjectName("tree")
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.tree, 1)
        self.count = label("", "muted")
        v.addWidget(self.count)
        ctx.changes_listeners.append(self.refresh_dots)
        style.notifier.changed.connect(self.refresh_dots)

    def load(self, project):
        self.tree.clear()
        self.items = {}
        nodes = {"": self.tree.invisibleRootItem()}
        files = project.files()
        for p in files:
            rel = p.relative_to(project.folder)
            parent = ""
            for part in rel.parts[:-1]:
                key = os.path.join(parent, part)
                if key not in nodes:
                    it = QTreeWidgetItem(nodes[parent], [part])
                    it.setExpanded(True)
                    nodes[key] = it
                parent = key
            it = QTreeWidgetItem(nodes[parent], [p.name])
            it.setData(0, Qt.UserRole, str(p))
            self.items[str(p)] = it
        self.count.setText(f"{len(files)} containers")
        self.refresh_dots()

    def set_modified(self, paths):
        self.modified = {os.path.normcase(str(p)) for p in paths}
        self.refresh_dots()

    def refresh_dots(self):
        """Blue dot: you have pending edits. Amber: already changed from retail."""
        from PySide6.QtGui import QIcon
        pend = {os.path.normcase(p) for p in
                (self.ctx.changes.containers() if self.ctx.changes else set())}
        edit, mod = style.dot_icon("edit"), style.dot_icon("warn")
        for path, it in self.items.items():
            n = os.path.normcase(path)
            it.setIcon(0, edit if n in pend else mod if n in self.modified else QIcon())
            it.setToolTip(0, "pending edits" if n in pend else
                          "changed from retail (see History)" if n in self.modified else "")

    def _apply_filter(self, text):
        q = text.lower()
        for path, it in self.items.items():
            hide = bool(q) and q not in it.text(0).lower()
            it.setHidden(hide)
            p = it.parent()
            while p is not None and not hide:
                p.setHidden(False)
                p = p.parent()

    def _clicked(self, item, _c=0):
        path = item.data(0, Qt.UserRole)
        if path:
            self.opened.emit(path)

    def select(self, path):
        it = self.items.get(str(path))
        if it:
            self.tree.setCurrentItem(it)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        path = it.data(0, Qt.UserRole) if it else None
        if not path:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: self.opened.emit(path))
        m.addAction("Show in folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(path).parent))))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(path))
        m.addSeparator()
        m.addAction("Revert to retail…", lambda: self._revert(path))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _revert(self, path):
        self.ctx.window.revert_file(path)


# ----------------------------------------------------------------- Search
class SearchSidebar(QWidget):
    """Text or regex search over every script of the open game folder. Results are listed
    container > script > line; clicking a line opens that script at that line."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.run_ = SearchRun(ctx.log)
        self.run_.progress.connect(self._progress)
        self.run_.hits.connect(self._add)
        self.run_.finished.connect(self._finished)
        self._reset()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(label("SEARCH", "muted"))
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search the scripts of every container…")
        self.query.returnPressed.connect(self.run)
        self.regex, self.case = QCheckBox("Regex"), QCheckBox("Match case")
        self.go = QPushButton("Search")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.run)
        opts = QHBoxLayout()
        opts.addWidget(self.regex)
        opts.addWidget(self.case)
        v.addWidget(self.query)
        v.addLayout(opts)
        v.addWidget(self.go)
        self.results = QTreeWidget()
        self.results.setObjectName("tree")
        self.results.setHeaderHidden(True)
        self.results.itemActivated.connect(self._open)
        self.results.itemClicked.connect(self._open)
        v.addWidget(self.results, 1)
        self.note = label("", "muted", True)
        v.addWidget(self.note)
        ctx.project_changed.connect(self._project_changed)

    def _reset(self):
        self._items = {}                    # container -> top item; (container, index) -> item
        self._counts = {}                   # container -> matching lines
        self._hits = 0
        self._scripts = 0
        self._folder = None

    def _project_changed(self):
        self.run_.cancel(quiet=True)
        self.results.clear()
        self._reset()
        self._busy(False)
        self.note.setText("")

    def _busy(self, on):
        self.go.setText("Cancel" if on else "Search")
        self.go.setObjectName("" if on else "primary")
        self.go.style().unpolish(self.go)
        self.go.style().polish(self.go)
        self.query.setEnabled(not on)

    def run(self):
        """Start the search, or stop the running one."""
        if self.run_.running():
            self.run_.cancel()
            return
        p = self.ctx.project
        text = self.query.text()
        if p is None:
            self.note.setText("Open a game folder first.")
            return
        if not text.strip():
            self.note.setText("Type what to look for.")
            return
        if self.regex.isChecked():
            try:
                re.compile(text)
            except re.error as e:
                self.note.setText(f"That is not a valid regular expression: {e}")
                return
        self.results.clear()
        self._reset()
        self._folder = p.folder
        self._busy(True)
        self.note.setText("Starting…")
        self.run_.start(backend.search_argv(self.ctx.settings, p.folder, text,
                                            self.regex.isChecked(), self.case.isChecked()),
                        cwd=APPDIR)

    def _progress(self, done, total, name):
        if done < total:
            self.note.setText(f"Reading scripts: {done} of {total} containers. Only the "
                              "first search takes this long.")
        else:
            self.note.setText(f"Searching… {self._hits} match(es) so far.")

    def _add(self, hits):
        tree = self.results
        tree.setUpdatesEnabled(False)
        for h in hits:
            cont = h["container"]
            top = self._items.get(cont)
            if top is None:
                top = self._items[cont] = QTreeWidgetItem(tree, [cont])
                top.setExpanded(True)
                self._counts[cont] = 0
            key = (cont, h["index"])
            sc = self._items.get(key)
            path = str(Path(self._folder) / cont)
            if sc is None:
                more = len(h.get("also") or [])
                sc = self._items[key] = QTreeWidgetItem(
                    top, [h["name"] + (f"   (+{more} identical cop{'y' if more == 1 else 'ies'})"
                                       if more else "")])
                sc.setData(0, Qt.UserRole, (path, h["index"], h["line"]))
                sc.setExpanded(True)
                self._scripts += 1
            it = QTreeWidgetItem(sc, [f"{h['line']:>5}   {h['text'].strip()[:160]}"])
            it.setData(0, Qt.UserRole, (path, h["index"], h["line"]))
            self._counts[cont] += 1
            self._hits += 1
        for cont, n in self._counts.items():
            self._items[cont].setText(0, f"{cont}   ({n})")
        tree.setUpdatesEnabled(True)

    def _finished(self, res):
        self._busy(False)
        n = self._hits
        found = f"{n} match(es) in {self._scripts} script(s)" if n else "No matches"
        if res.get("cancelled"):
            self.note.setText(f"Cancelled. {found} so far." if n else "Cancelled.")
        elif not res.get("ok"):
            self.note.setText(res.get("message") or "The search could not run.")
        elif n >= backend.SEARCH_LIMIT:
            self.note.setText(f"{found}. Stopped at {backend.SEARCH_LIMIT}: search for "
                              "something more specific.")
        else:
            self.note.setText(found + ".")

    def _open(self, item, _c=0):
        d = item.data(0, Qt.UserRole)
        if d:
            self.ctx.open_script(*d)


class SimplePage(QWidget):
    """A page with a heading and a short explanation (used for empty states)."""

    def __init__(self, title, text):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.addWidget(label(title, "heading"))
        v.addWidget(label(text, "muted", True))
        v.addStretch(1)


# ----------------------------------------------------------------- History
class HistoryPage(QWidget):
    """Files Seam Ripper has changed, and putting them back."""
    COLS = ["File", "State", "Last backup", "Earlier versions"]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.addWidget(label("History and backups", "heading"))
        v.addWidget(label("Every game file Seam Ripper has changed. Put one back, or "
                          "everything. Backups are kept in a .seamripper folder next to "
                          "the files.", "muted", True))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(self.COLS)):      # state and time in full, not "Retail ..."
            head.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._sel)
        v.addWidget(self.table, 1)
        self.note = label("", "muted", True)
        v.addWidget(self.note)
        row = QHBoxLayout()
        self.b_retail = QPushButton("Revert selected to retail")
        self.b_prev = QPushButton("Restore previous version")
        self.b_all = QPushButton("Revert everything to retail…")
        self.b_retail.clicked.connect(self.revert_one)
        self.b_prev.clicked.connect(self.previous)
        self.b_all.clicked.connect(self.revert_all)
        for b in (self.b_retail, self.b_prev, self.b_all):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.build_note = label("", "muted", True)
        self.b_build = QPushButton("Revert the game build's files…")
        self.b_build.setToolTip("Put back the game files in the restuff build that "
                                "Ship && launch replaced.")
        self.b_build.clicked.connect(lambda: self.ctx.window.revert_build())
        brow = QHBoxLayout()
        brow.addWidget(self.build_note, 1)
        brow.addWidget(self.b_build)
        v.addLayout(brow)
        self.rows = []
        self._sel()

    def refresh(self):
        self.table.setRowCount(0)
        self.rows = []
        p = self.ctx.project
        if p is None:
            self.note.setText("Open a game folder to see its history.")
            return
        try:
            self.rows = backend.backups_list(p)
        except Exception as e:
            self.note.setText(f"Could not read the backups: {e}")
            return
        self.note.setText("" if self.rows else
                          "No files have been changed yet. Once you Ship, the originals "
                          "show up here.")
        for r in self.rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            state = {"retail": "Retail (unchanged)", "modified": "Modified",
                     "missing": "Missing"}[r["state"]]
            for c, text in enumerate((p.relative(r["path"]), state, r["when"],
                                      str(r["previous"]))):
                it = QTableWidgetItem(text)
                if c == 1 and r["state"] == "modified":
                    it.setForeground(QColor(style.color("warn")))
                self.table.setItem(i, c, it)
        self._sel()
        self._build_row()

    def _build_row(self):
        """The restuff build's own files, which Ship && launch installs into."""
        s = self.ctx.settings
        d, _why = backend.build_check(backend.build_folder(s))
        self.b_build.setVisible(d is not None)
        self.build_note.setVisible(d is not None)
        if d is None:
            return
        try:
            n = len(backend.build_modified(s))
        except Exception:
            n = 0
        self.build_note.setText(
            f"Game build: {n} file(s) in {d['lu']} differ from the originals."
            if n else "Game build: its files are the originals.")
        self.b_build.setEnabled(n > 0)

    def _sel(self):
        r = self.current()
        self.b_retail.setEnabled(r is not None and r["state"] != "retail")
        self.b_prev.setEnabled(r is not None and r["state"] != "retail")
        self.b_all.setEnabled(any(x["state"] != "retail" for x in self.rows))

    def current(self):
        i = self.table.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def revert_one(self):
        r = self.current()
        if r:
            self.ctx.window.revert_file(r["path"])

    def previous(self):
        r = self.current()
        if r:
            self.ctx.window.restore_previous(r["path"])

    def revert_all(self):
        self.ctx.window.revert_everything()


# ----------------------------------------------------------------- Tools
class ToolsSidebar(QTreeWidget):
    chosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("tree")
        self.setHeaderHidden(True)
        self.items = {}
        for group, specs in toolspecs.by_group():
            top = QTreeWidgetItem([group])
            self.addTopLevelItem(top)
            for s in specs:
                it = QTreeWidgetItem(top, [s["title"]])
                it.setData(0, Qt.UserRole, s["title"])
                self.items[s["title"]] = it
            top.setExpanded(group != "Advanced")
        self.itemClicked.connect(self._clicked)

    def _clicked(self, item, _c):
        t = item.data(0, Qt.UserRole)
        if t:
            self.chosen.emit(t)

    def select(self, title):
        it = self.items.get(title)
        if it:
            it.parent().setExpanded(True)
            self.setCurrentItem(it)


class ToolsPage(QWidget):
    """One tool form at a time, prefilled from the project and selected file."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.forms = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        intro = SimplePage("Tools", "Pick a task on the left. The log shows the exact "
                           "command each one runs.")
        self.stack.addWidget(intro)
        v.addWidget(self.stack)

    def show_tool(self, title):
        spec = toolspecs.find(title)
        if spec is None:
            return
        if title not in self.forms:
            form = ToolForm(spec, self.ctx)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            inner = QWidget()
            iv = QVBoxLayout(inner)
            iv.setContentsMargins(16, 16, 16, 16)
            iv.addWidget(form)
            iv.addStretch(1)
            scroll.setWidget(inner)
            self.forms[title] = (form, scroll)
            self.stack.addWidget(scroll)
        form, scroll = self.forms[title]
        form.prefill()
        self.stack.setCurrentWidget(scroll)

    def refresh_prefill(self):
        for form, _s in self.forms.values():
            form.prefill()


# ----------------------------------------------------------------- Welcome
class WelcomePage(QWidget):
    open_folder = Signal()
    open_recent = Signal(str)

    def __init__(self, settings):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        box = QFrame()
        box.setObjectName("card")
        box.setMaximumWidth(560)
        v = QVBoxLayout(box)
        v.setContentsMargins(24, 24, 24, 24)
        v.addWidget(label("Seam Ripper", "heading"))
        v.addWidget(label("Open your Naughty Bear or Panic in Paradise folder to start."
                          "\n\nNothing is written to your game until you Ship.",
                          "muted", True))
        b = QPushButton("Open game folder…")
        b.setObjectName("primary")
        b.clicked.connect(self.open_folder)
        v.addWidget(b)
        self.recent_label = label("Recent projects", "muted")
        self.recent = QListWidget()
        self.recent.setObjectName("rowlist")
        self.recent.setMaximumHeight(150)
        self.recent.itemActivated.connect(lambda it: self.open_recent.emit(it.text()))
        self.recent.itemClicked.connect(lambda it: self.open_recent.emit(it.text()))
        v.addWidget(self.recent_label)
        v.addWidget(self.recent)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.set_recent(settings.get("recent", []))

    def set_recent(self, folders):
        self.recent.clear()
        for f in folders:
            if Path(f).exists():
                self.recent.addItem(f)
        self.recent.setMaximumHeight(min(150, 26 * self.recent.count() + 8))
        vis = self.recent.count() > 0
        self.recent.setVisible(vis)
        self.recent_label.setVisible(vis)
