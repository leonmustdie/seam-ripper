"""Settings dialog: project, play, tools, appearance, advanced."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QListWidget, QListWidgetItem, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from . import backend, style, themes
from .paths import FROZEN
from .project import GAME_NAMES
from .settings import project_options
from .widgets import PathRow, label


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None, tab=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(620, 460)
        self.ctx = ctx
        s = ctx.settings
        self.original_theme = style.choice()
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)

        # -- project
        page = QWidget()
        f = QFormLayout(page)
        p = ctx.project
        self.ship_to = PathRow("folder", s)
        if p:
            f.addRow("Game folder", label(f"{p.folder}   ({GAME_NAMES.get(p.game, 'unknown game')})", wrap=True))
            self.ship_to.set_value(project_options(s, p.folder).get("ship_to", ""))
            f.addRow("Ship to", self.ship_to)
            f.addRow("", label("Where Ship saves your changes. Leave empty to change the "
                               "game folder itself (backed up first).", "muted", True))
            f.addRow("Backups", label(str(p.folder / ".seamripper" / "backups") +
                                      "\n(each file's backups live next to it; managed "
                                      "automatically)", "muted", True))
        else:
            f.addRow(label("Open a game folder first to change project settings.", "muted", True))
        tabs.addTab(page, "Project")

        # -- play
        page = QWidget()
        f = QFormLayout(page)
        self.build = PathRow("folder", s)
        self.build.set_value(backend.build_folder(s))
        self.build.edit.textChanged.connect(self._check_build)
        f.addRow("restuff build folder", self.build)
        self.build_state = label("", "muted", True)
        f.addRow("", self.build_state)
        f.addRow("", label("The folder with restuff.exe (the PC port of Naughty Bear). "
                           "Ship && launch copies your changes into it, backing up the "
                           "originals.", "muted", True))
        tabs.addTab(page, "Play")
        self._check_build()

        # -- tools
        page = QWidget()
        f = QFormLayout(page)
        self.tool_rows = {}
        specs = [("python", "Python", "openfile"), ("luac", "luac51.exe", "openfile"),
                 ("jar", "unluac.jar", "openfile")]
        if FROZEN:                                  # tools run inside the EXE
            specs = specs[1:]
        for key, lab, kind in specs:
            r = PathRow(kind, s)
            r.set_value(s.get(key, ""))
            f.addRow(lab, r)
            self.tool_rows[key] = r
        tabs.addTab(page, "Tools")

        # -- appearance
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.addWidget(label("Pick a theme. It applies straight away.", "muted"))
        self.theme_list = QListWidget()
        for key, name in themes.theme_choices():
            it = QListWidgetItem(name)
            it.setData(256, key)
            self.theme_list.addItem(it)
            if key == style.choice():
                self.theme_list.setCurrentItem(it)
        self.theme_list.currentItemChanged.connect(self._theme)
        pv.addWidget(self.theme_list)
        tabs.addTab(page, "Appearance")

        # -- advanced
        page = QWidget()
        f = QFormLayout(page)
        self.decompiler = QComboBox()
        self.decompiler.addItems(["auto", "nbdec", "unluac", "luadec"])
        self.decompiler.setCurrentText(s.get("decompiler", "auto"))
        f.addRow("Decompiler (Naughty Bear)", self.decompiler)
        f.addRow("", label("Leave this on auto. The others are only for comparing by "
                           "hand. Panic in Paradise doesn't use it.", "muted", True))
        self.schema_btn = QPushButton("Build Panic in Paradise value checks (about 4 minutes)")
        self.schema_btn.setToolTip("Reads every retail Panic in Paradise script once so "
                                   "unusual values get a warning.")
        self.schema_btn.clicked.connect(ctx.window.build_schema)
        f.addRow(self.schema_btn)
        self.show_cmds = QCheckBox("Show the exact command of every run in the log")
        self.show_cmds.setChecked(bool(s.get("show_commands", True)))
        f.addRow(self.show_cmds)
        tabs.addTab(page, "Advanced")

        if tab:
            for i in range(tabs.count()):
                if tabs.tabText(i) == tab:
                    tabs.setCurrentIndex(i)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _check_build(self, *_):
        """Say whether the folder is a usable restuff build (sr_launch.locate decides)."""
        folder = self.build.value().strip()
        d, why = backend.build_check(folder)
        text, tone = (("Not set. Launch stays off until you pick it.", "muted") if not folder
                      else (f"Found restuff.exe. Game files: {d['lu']}", "ok") if d
                      else (why, "err"))
        self.build_state.setText(text)
        self.build_state.setObjectName(tone)
        self.build_state.style().unpolish(self.build_state)
        self.build_state.style().polish(self.build_state)

    def _theme(self, item, _prev=None):
        if item is not None:
            self.ctx.window.set_theme(item.data(256))

    def accept(self):
        s = self.ctx.settings
        for k, r in self.tool_rows.items():
            s[k] = r.value()
        s["restuff_build"] = self.build.value().strip()
        s["decompiler"] = self.decompiler.currentText()
        s["show_commands"] = self.show_cmds.isChecked()
        self.ctx.log.show_cmds.setChecked(self.show_cmds.isChecked())
        if self.ctx.project:
            project_options(s, self.ctx.project.folder)["ship_to"] = self.ship_to.value()
            self.ctx.planner.refresh()
        self.ctx.save_settings()
        self.ctx.log.stamp("settings saved.")
        super().accept()

    def reject(self):
        if style.choice() != self.original_theme:
            self.ctx.window.set_theme(self.original_theme)
        super().reject()
