"""The main window: rail, sidebars, pages, top bar, bottom dock."""
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QStatusBar, QToolButton,
                               QVBoxLayout, QWidget)

from . import VERSION, backend, style, themes
from .changes_page import ChangesSidebar, ReviewPage
from .context import Context
from .paths import BUNDLE
from .pages import (FilesSidebar, HistoryPage, SearchSidebar, SimplePage, ToolsPage,
                    ToolsSidebar, WelcomePage)
from .patches_page import PatchesPage
from .project import Project
from .runner import Runner
from .shipping import ShipPlanner
from .settings import add_recent, load_settings, project_options, save_settings
from .settings_dialog import SettingsDialog
from .views import ContainerView
from .widgets import Banner, BottomDock, LogPanel, ProblemsList, label

RAIL = [("Files", "▤"), ("Search", "⌕"), ("Changes", "✎"), ("Patches", "⇄"),
        ("History", "↺"), ("Tools", "⚙")]
FILES, SEARCH, CHANGES, PATCHES, HISTORY, TOOLS = range(6)

_ITCH = "https://lil-limpy-linky.itch.io/"
ABOUT = (
    f"<p><b>Seam Ripper</b><br>Version {VERSION}<br>Seam Ripper is a modding toolkit for "
    "Naughty Bear and Naughty Bear: Panic in Paradise, now featuring patches for sharing "
    "mods.</p>"
    "<p>By leonmustdie · Icon and artwork by Mallorie.<br>"
    'Thanks to <a href="https://github.com/LilLimpy">LilLimpyLinky</a> for the initial '
    "stuff that kickstarted this project. Please check out the Naughty Bear Remakes "
    "they're doing, on their itch.io pages:<br>"
    f'<a href="{_ITCH}naughty-bear-pc">Naughty Bear</a> · '
    f'<a href="{_ITCH}naughty-bear-mobile-pc">Naughty Bear Mobile</a> · '
    f'<a href="{_ITCH}naughty-bear-pip-pc">Naughty Bear: Panic in Paradise</a><br>'
    'Got issues? Send them to the Github (<a href="https://github.com/leonmustdie/'
    'seam-ripper">github.com/leonmustdie/seam-ripper</a>) .</p>'
    "<p>Seam Ripper is a fanmade modding project, and is not affiliated with 505 Games or "
    "Behaviour Interactive aka A2M/Artificial Mind and Movement, or any of the original "
    "creators of the games therein.</p>"
    "<p>Seam Ripper is only used for game modification and extraction, and does not "
    "distribute files from the original Naughty Bear games (Naughty Bear, Naughty Bear "
    "Panic in Paradise aka Naughty Bear 2.)</p>"
    "<p>Please do not send ninjas to my house for desecrating the sacred ground of the "
    ".lu file format.</p>")


class Main(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle("Seam Ripper")
        for name in ("seamripper_256.png", "seamripper.ico", "seamripper_64.png"):
            p = BUNDLE / name
            if p.exists():
                self.setWindowIcon(QIcon(str(p)))
                break
        self.resize(1240, 820)
        self.settings = settings if settings is not None else load_settings()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.log = LogPanel(self.settings)
        self.problems = ProblemsList()
        self.dock = BottomDock(self.log, self.problems)
        self.runner = Runner(self.log)
        self.banner = Banner()
        self.ctx = Context(self.settings, self.runner, self.log, self.banner)
        self.ctx.window = self
        self.ctx.changes = None
        self.ctx.set_project(None)
        self.planner = self.ctx.planner = ShipPlanner(self.ctx)
        self._build_status()
        self._build_ui()
        self._build_menus()
        self.runner.title_changed.connect(self._run_started)
        self.problems.jump.connect(lambda c, line: c.jump_to(line))
        self.ctx.changes_listeners.append(self._changes_fired)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(lambda: self.ctx.changes.save())
        style.follow_system()
        self.set_theme(self.settings.get("theme", "system"), save=False)
        self.setAcceptDrops(True)
        self.log.stamp("Seam Ripper ready. Open your game folder to begin.")

    # ---------------------------------------------------------------- build
    def _build_status(self):
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.setTextVisible(False)
        self.busy_label = label("", "muted")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.runner.cancel)
        for w in (self.busy_label, self.busy_bar, self.cancel_btn):
            self.status.addPermanentWidget(w)
            w.hide()
        self.runner.busy_changed.connect(self._busy)
        self.runner.title_changed.connect(self.busy_label.setText)

    def _busy(self, on):
        for w in (self.busy_label, self.busy_bar, self.cancel_btn):
            w.setVisible(on)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._topbar())
        v.addWidget(self.banner)
        self.root_stack = QStackedWidget()
        self.welcome = WelcomePage(self.settings)
        self.welcome.open_folder.connect(self.choose_folder)
        self.welcome.open_recent.connect(self.open_project)
        self.root_stack.addWidget(self.welcome)
        self.root_stack.addWidget(self._workspace())
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.root_stack)
        split.addWidget(self.dock)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setChildrenCollapsible(False)
        self.vsplit = split
        v.addWidget(split, 1)

    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        self.proj_btn = QToolButton()
        self.proj_btn.setPopupMode(QToolButton.InstantPopup)
        self.proj_btn.setText("No game folder  ▾")
        self.proj_menu = QMenu(self)
        self.proj_menu.aboutToShow.connect(self._fill_project_menu)
        self.proj_btn.setMenu(self.proj_menu)
        self.badge = label("", "badge")
        h.addWidget(self.badge)
        h.addWidget(self.proj_btn)
        h.addStretch(1)
        self.changes_btn = QPushButton("Changes (0)")
        self.changes_btn.clicked.connect(lambda: self.select_rail(CHANGES))
        h.addWidget(self.changes_btn)
        self.ship_btn = QToolButton()
        self.ship_btn.setObjectName("primary")
        self.ship_btn.setText("Review && ship")
        self.ship_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.ship_btn.clicked.connect(lambda: self.select_rail(CHANGES))
        m = QMenu(self.ship_btn)
        m.addAction("Review && ship…", lambda: self.select_rail(CHANGES))
        m.addAction("Ship && launch", lambda: self.ship_now(True))
        m.addAction("Launch only", self.launch)
        self.ship_btn.setMenu(m)
        h.addWidget(self.ship_btn)
        self.launch_btn = QPushButton("▶ Launch")
        self.launch_btn.clicked.connect(self.launch)
        h.addWidget(self.launch_btn)
        self.topbar = bar
        bar.hide()
        return bar

    def _workspace(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(76)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(0, 6, 0, 6)
        rv.setSpacing(0)
        self.rail_btns = []
        for i, (name, glyph) in enumerate(RAIL):
            b = QToolButton()
            b.setObjectName("rail")
            b.setText(f"{glyph}\n{name}")
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setMinimumHeight(54)
            b.setMinimumWidth(76)
            b.clicked.connect(lambda _=False, i=i: self.select_rail(i))
            rv.addWidget(b)
            self.rail_btns.append(b)
        rv.addStretch(1)
        h.addWidget(rail)

        ctx = self.ctx
        self.files_sb = FilesSidebar(ctx)
        self.search_sb = SearchSidebar(ctx)
        self.changes_sb = ChangesSidebar(ctx)
        self.tools_sb = ToolsSidebar()
        self.files_sb.opened.connect(self.open_container)
        self.tools_sb.chosen.connect(self.open_tool)
        info = lambda t: SimplePage("", t)
        self.side_stack = QStackedWidget()
        for page in (self.files_sb, self.search_sb, self.changes_sb,
                     info("Make and apply shareable mod patches."),
                     info("Backups of files Seam Ripper has changed, and reverting them."),
                     self.tools_sb):
            self.side_stack.addWidget(page)
        side = QFrame()
        side.setObjectName("sidebar")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 8, 8, 8)
        sv.addWidget(self.side_stack, 1)
        sv.addWidget(self._hash_box())
        side.setMinimumWidth(200)

        self.view = ContainerView(ctx)
        self.view.scripts.problems_changed.connect(self._problems)
        self.view_hint = SimplePage("Pick a file", "Choose a container on the left to see its "
                                    "scripts, text, textures and more.")
        self.files_stack = QStackedWidget()
        self.files_stack.addWidget(self.view_hint)
        self.files_stack.addWidget(self.view)
        self.review = ReviewPage(ctx, self.changes_sb)
        self.patches = PatchesPage(ctx)
        self.history = HistoryPage(ctx)
        self.tools_page = ToolsPage(ctx)
        self.central = QStackedWidget()
        for page in (self.files_stack,
                     SimplePage("Search", "Type in the box on the left. Results open in "
                                "the editor at the right line."),
                     self.review, self.patches, self.history, self.tools_page):
            self.central.addWidget(page)
        hs = QSplitter(Qt.Horizontal)
        hs.addWidget(side)
        hs.addWidget(self.central)
        hs.setSizes([260, 980])
        hs.setStretchFactor(1, 1)
        hs.setChildrenCollapsible(False)
        h.addWidget(hs, 1)
        self.select_rail(FILES)
        return w

    def _hash_box(self):
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(label("HASH LOOKUP", "muted"))
        self.hash_edit = QLineEdit()
        self.hash_edit.setPlaceholderText("name or 0x… hash")
        self.hash_edit.textChanged.connect(self.lookup_hash)
        self.hash_result = label("", "muted", True)
        self.hash_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hash_copy, self.hash_copy2 = QPushButton("Copy"), QPushButton("Copy number")
        self.hash_copy.clicked.connect(lambda: self._copy_hash("copy"))
        self.hash_copy2.clicked.connect(lambda: self._copy_hash("copy2"))
        row = QHBoxLayout()
        row.addWidget(self.hash_copy)
        row.addWidget(self.hash_copy2)
        v.addWidget(self.hash_edit)
        v.addWidget(self.hash_result)
        v.addLayout(row)
        self.hash_answer = None
        self.lookup_hash()
        return box

    def lookup_hash(self, _text=None):
        """Show the other side of what is typed: a name's hash, or a hash's name."""
        r = self.hash_answer = backend.hash_lookup(self.hash_edit.text())
        tone = ("muted" if r["kind"] == "empty" else "err" if r["kind"] == "bad"
                else "ok" if r["known"] else "warn")
        self.hash_result.setObjectName(tone)
        self.hash_result.style().unpolish(self.hash_result)
        self.hash_result.style().polish(self.hash_result)
        self.hash_result.setText(r["text"])
        self.hash_copy.setVisible(bool(r["copy"]))
        self.hash_copy.setText("Copy name" if r["kind"] == "hash" else "Copy hash")
        self.hash_copy2.setVisible(bool(r["copy2"]))
        self.hash_copy2.setText(r["copy2_label"] or "Copy")

    def _copy_hash(self, which):
        if self.hash_answer and self.hash_answer[which]:
            QGuiApplication.clipboard().setText(self.hash_answer[which])
            self.status.showMessage(f"Copied {self.hash_answer[which]}", 3000)

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        f.addAction("Open game folder…", self.choose_folder, QKeySequence("Ctrl+O"))
        self.recent_menu = f.addMenu("Recent projects")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        f.addSeparator()
        f.addAction("Make patch…", lambda: self.patches.make())
        f.addAction("Apply patch…", lambda: (self.select_rail(PATCHES), self.patches.open_patch()))
        f.addSeparator()
        f.addAction("Exit", self.close)
        e = mb.addMenu("&Edit")
        e.addAction("Undo", lambda: self.editor().undo(), QKeySequence("Ctrl+Z"))
        e.addAction("Redo", lambda: self.editor().redo(), QKeySequence("Ctrl+Y"))
        e.addSeparator()
        e.addAction("Find and replace…", self.find, QKeySequence("Ctrl+F"))
        e.addAction("Batch edit calls…", lambda: self.view.scripts.open_batch())
        e.addAction("Insert HASH(\"…\")…", lambda: self.view.scripts.insert_hash())
        g = mb.addMenu("&Game")
        g.addAction("Review && ship…", lambda: self.select_rail(CHANGES))
        g.addAction("Ship && launch", lambda: self.ship_now(True))
        g.addAction("Launch", self.launch)
        g.addSeparator()
        g.addAction("Revert to retail…", lambda: self.select_rail(HISTORY))
        t = mb.addMenu("&Tools")
        t.addAction("Search all files…", lambda: (self.select_rail(SEARCH),
                                                   self.search_sb.query.setFocus()),
                    QKeySequence("Ctrl+Shift+F"))
        t.addAction("Hash lookup", lambda: self.hash_edit.setFocus(), QKeySequence("Ctrl+H"))
        t.addSeparator()
        t.addAction("All tools…", lambda: self.select_rail(TOOLS))
        vw = mb.addMenu("&View")
        tm = vw.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        self.theme_actions = {}
        for key, name in themes.theme_choices():
            a = QAction(name, self, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_group.addAction(a)
            tm.addAction(a)
            self.theme_actions[key] = a
        vw.addAction("Show or hide the log", lambda: self.dock.set_open(not self.dock.is_open()),
                     QKeySequence("Ctrl+L"))
        s = mb.addMenu("&Settings")
        s.addAction("Settings…", self.open_settings, QKeySequence("Ctrl+,"))
        hp = mb.addMenu("&Help")
        hp.addAction("About Seam Ripper", lambda: QMessageBox.about(
            self, "About Seam Ripper", ABOUT))

    # ---------------------------------------------------------------- theme
    def set_theme(self, choice, save=True):
        style.set_theme(choice)
        self.settings["theme"] = choice
        if choice in self.theme_actions:
            self.theme_actions[choice].setChecked(True)
        if save:
            save_settings(self.settings)

    def open_settings(self, tab=None):
        SettingsDialog(self.ctx, self, tab).exec()

    # ---------------------------------------------------------------- project
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choose your game folder (the one with the .lu files)",
            self.settings.get("last_dir", ""), QFileDialog.DontUseNativeDialog)
        if d:
            self.open_project(d)

    def open_project(self, folder):
        folder = str(Path(folder))
        p = Project(folder)
        if not p.files():
            self.banner.show_message(
                f"No .lu files found in {folder}. Pick the folder that holds the game's "
                ".lu containers.", "warn")
            return
        self.ctx.set_project(p)
        self.settings["last_dir"] = folder
        add_recent(self.settings, folder)
        project_options(self.settings, folder)
        save_settings(self.settings)
        self.welcome.set_recent(self.settings["recent"])
        self.files_sb.load(p)
        self.files_sb.set_modified(backend.modified_files(p))
        self.files_stack.setCurrentIndex(0)
        self.ctx.set_current_file(None)
        self.tools_page.refresh_prefill()
        self.proj_btn.setText(f"{p.game_name}   {p.folder}  ▾")
        self.badge.setText(p.badge)
        self.topbar.show()
        self.launch_btn.setEnabled(p.game == "nb1")
        self.launch_btn.setToolTip("" if p.game == "nb1" else
                                   "Launching is set up for Naughty Bear only")
        self.root_stack.setCurrentIndex(1)
        self.setWindowTitle(f"Seam Ripper - {p.game_name}")
        self.select_rail(FILES)
        self.banner.hide()
        self.log.stamp(f"opened {p.folder} ({p.game_name}, {len(p.files())} containers)")

    def _fill_project_menu(self):
        m = self.proj_menu
        m.clear()
        for f in self.settings.get("recent", []):
            m.addAction(f, lambda f=f: self.open_project(f))
        m.addSeparator()
        m.addAction("Open game folder…", self.choose_folder)

    def _fill_recent(self):
        self.recent_menu.clear()
        for f in self.settings.get("recent", []):
            self.recent_menu.addAction(f, lambda f=f: self.open_project(f))

    # ---------------------------------------------------------------- navigation
    def select_rail(self, i):
        for k, b in enumerate(self.rail_btns):
            b.setChecked(k == i)
        self.side_stack.setCurrentIndex(i)
        self.central.setCurrentIndex(i)
        if i == HISTORY:
            self.history.refresh()
        if self.root_stack.currentIndex() == 0 and self.ctx.project:
            self.root_stack.setCurrentIndex(1)

    def _run_started(self, title):
        if title and self.banner.property("kind") == "err":
            self.banner.hide()

    def open_container(self, path):
        self.banner.hide()
        self.select_rail(FILES)
        self.ctx.set_current_file(path)
        self.files_stack.setCurrentIndex(1)
        self.files_sb.select(path)
        self.view.load(path)
        self.tools_page.refresh_prefill()

    def open_script(self, lu, index, line=None):
        self.select_rail(FILES)
        if str(lu) != self.view.lu:
            self.ctx.set_current_file(lu)
            self.files_stack.setCurrentIndex(1)
            self.files_sb.select(lu)
            self.view.scripts.pending = (index, line)
            self.view.load(lu)
            self.view.tabs.setCurrentIndex(0)
            self.tools_page.refresh_prefill()
        else:
            self.view.tabs.setCurrentIndex(0)
            self.view.scripts.select_index(index, line)

    def report_script_errors(self, draft, errs):
        self.open_script(draft.lu, draft.index, errs[0][0] if errs else None)
        self.view.scripts.show_errors(draft.key, errs)
        self.dock.set_open(True, 0)

    def reload_current_script(self, key):
        self.view.scripts.discard_current(key)

    def open_tool(self, title):
        self.select_rail(TOOLS)
        self.tools_sb.select(title)
        self.tools_page.show_tool(title)

    def show_changes(self, key=None):
        self.select_rail(CHANGES)
        if key:
            self.review.show_key(key)

    def editor(self):
        return self.view.scripts.editor

    def find(self):
        if self.rail_btns[FILES].isChecked() and self.view.scripts.stack.currentIndex() == 1:
            self.view.scripts.find_bar.open()

    def _problems(self, probs, explicit=False):
        self.problems.set_problems(probs)
        self.dock.set_problem_count(len(probs), explicit)

    def _changes_fired(self):
        n = self.ctx.changes.count() if self.ctx.changes else 0
        self.changes_btn.setText(f"Changes ({n})")
        self.rail_btns[CHANGES].setText(f"✎\nChanges ({n})" if n else "✎\nChanges")
        if self.ctx.changes and self.ctx.project:
            self._save_timer.start()

    def after_ship(self, paths, in_place):
        """Files changed on disk (a ship or an undo): refresh what shows them."""
        p = self.ctx.project
        if in_place:
            for f in paths:
                self.planner.forget_warm(f)
            self.view.scripts.reload()
            if self.view.lu and self.view.scripts.draft is None and p and p.game == "pip":
                self.planner.warm_pip(self.view.lu, self.view.scripts._warmed)
        self.planner.where.clear()
        if p:
            self.files_sb.set_modified(backend.modified_files(p))
        if self.rail_btns[HISTORY].isChecked():
            self.history.refresh()

    # ---------------------------------------------------------------- history
    def _confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.Cancel,
                                    QMessageBox.Cancel) == QMessageBox.Yes

    def _restored(self, paths, text):
        self.after_ship(paths, True)
        self.banner.show_message(text, "ok")

    def revert_file(self, path):
        name = Path(path).name
        if not self._confirm("Revert to retail",
                             f"Put {name} back to the original?\n\nYou can undo this "
                             "from History."):
            return
        try:
            backend.revert_to_retail(path)
        except Exception as e:
            self.banner.show_message(f"Could not revert {name}: {e}", "err")
            return
        self._restored([path], f"{name} is back to retail.")

    def restore_previous(self, path):
        name = Path(path).name
        if not self._confirm("Restore previous version",
                             f"Put back the version of {name} from before the last Ship?"):
            return
        try:
            backend.restore_previous(path)
        except Exception as e:
            self.banner.show_message(f"Could not restore {name}: {e}", "err")
            return
        self._restored([path], f"{name} is back to the version before the last Ship.")

    def revert_everything(self):
        p = self.ctx.project
        if p is None:
            return
        rows = [r for r in backend.backups_list(p) if r["state"] != "retail"]
        if not rows:
            self.banner.show_message("Everything is already retail.", "ok")
            return
        if not self._confirm("Revert everything to retail",
                             f"Put {len(rows)} file(s) back to their originals?\n\n"
                             "The current versions are kept as backups."):
            return
        results = backend.revert_all(p)
        bad = [r for r in results if r.get("error")]
        self._restored([r["path"] for r in rows], f"{len(results) - len(bad)} file(s) are back "
                       "to retail." + (f" {len(bad)} could not be reverted: "
                                       f"{bad[0]['file']}: {bad[0]['error']}" if bad else ""))
        if bad:
            self.banner.show_message(self.banner.text.text(), "warn")

    def build_schema(self):
        """Build the Panic in Paradise value checks in the background."""
        p = self.ctx.project
        if p is None or p.game != "pip":
            self.banner.show_message("Open your Panic in Paradise folder first: the value "
                                     "checks are built from its scripts.", "warn")
            return
        self.planner.build_schema(str(p.folder))

    def set_busy_ship(self, busy):
        for b in (self.review.ship_btn, self.review.launch_btn):
            b.setEnabled(not busy)

    def ship_now(self, launch):
        self.select_rail(CHANGES)
        self.review.ship(launch)

    def launch_ready(self):
        """True if the game can be started; otherwise says why in the banner."""
        p = self.ctx.project
        if p is not None and p.game != "nb1":
            self.banner.show_message("Launching is set up for Naughty Bear only.", "warn")
            return False
        try:
            backend.require_build(self.settings)
        except backend.NoBuild as e:
            self.banner.show_message(str(e), "warn",
                                     [("Open Settings", lambda: self.open_settings("Play"))])
            return False
        return True

    def launch(self):
        """Start restuff.exe from the build folder chosen in Settings."""
        if not self.launch_ready():
            return
        try:
            got = backend.launch(self.ctx.project, self.settings)
        except Exception as e:
            self.banner.show_message(f"Could not start the game: {e}", "err")
            return
        self.log.stamp(f"started restuff.exe (process {got['pid']})")
        folder = str(Path(got["log"]).parent)
        self.banner.show_message(
            "Started the game. " + got["hint"], "ok",
            [("Open build folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))])

    def revert_build(self):
        """History: put the game files Ship & launch installed in the build back."""
        try:
            names = backend.build_modified(self.settings)
            if not names:
                self.banner.show_message("The build's files are already the originals.", "ok")
                return
            shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
            if not self._confirm("Revert the build's files",
                                 f"Put {len(names)} file(s) in the restuff build back to "
                                 f"their originals?\n\n{shown}\n\nThe current versions "
                                 "are kept as backups."):
                return
            done = backend.build_revert(self.settings)
        except Exception as e:
            self.banner.show_message(f"Could not revert the build's files: {e}", "err")
            return
        self.banner.show_message(f"{len(done)} file(s) in the build are back to the originals.",
                                 "ok")
        self.history.refresh()

    # ---------------------------------------------------------------- drag and drop
    @staticmethod
    def _dropped_patch(ev):
        for u in ev.mimeData().urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".srpatch"):
                return str(Path(u.toLocalFile()))
        return None

    def dragEnterEvent(self, ev):
        if self._dropped_patch(ev):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        fn = self._dropped_patch(ev)
        if not fn:
            return
        if self.ctx.project is None:
            self.banner.show_message("Open your game folder first, then drop the patch here.",
                                     "warn")
            return
        ev.acceptProposedAction()
        self.select_rail(PATCHES)
        self.patches.open_patch(fn)

    # ---------------------------------------------------------------- close
    def closeEvent(self, ev):
        self.search_sb.run_.cancel(quiet=True)
        self.patches.stop()
        if self.runner.busy():
            self.runner.cancel()
        if self.ctx.changes:
            self.ctx.changes.save()
        save_settings(self.settings)
        super().closeEvent(ev)
