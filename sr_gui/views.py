"""The container view: Scripts, Text, Textures, Models & sound and Info for one .lu."""
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from . import backend, toolspecs
from .paths import APPDIR
from .project import GAME_NAMES, container_game
from .scripts_tab import ScriptsTab
from .widgets import NotAvailableNote, ToolForm, label, mono_font


class TextTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.lu = ctx, ""
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.addWidget(label("Subtitle and menu text", "heading"))
        v.addWidget(label(
            "Export the text to a .txt, edit it in any text editor, then import it back. "
            "The original is backed up first.", "muted", True))
        row = QHBoxLayout()
        for text, fn in (("Export to .txt…", self.export), ("Import .txt…", self.import_),
                         ("Check spelling", self.spelling)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(label("Only language files (like global.en_us.lu) have text.",
                          "muted", True))
        v.addStretch(1)

    def load(self, lu):
        self.lu = str(lu)

    def _dir(self):
        p = self.ctx.project
        d = p.exports_dir("text") if p else self.ctx.scratch_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def export(self):
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export text", str(self._dir() / (Path(self.lu).stem + ".txt")),
            "Text (*.txt)", options=QFileDialog.DontUseNativeDialog)
        if fn:
            self.ctx.runner.run(backend.strings_extract_argv(self.ctx.settings, self.lu, fn),
                                cwd=APPDIR, title="Exporting text")

    def import_(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Import edited text", str(self._dir()), "Text (*.txt)",
            options=QFileDialog.DontUseNativeDialog)
        if not fn:
            return
        ctx = self.ctx
        plan = backend.plan_output(ctx.project, ctx.settings, self.lu)
        scratch = ctx.scratch_dir() / ("text_" + Path(self.lu).name)
        if scratch.exists():
            scratch.unlink()

        def done(code, out, err):
            if code != 0 or not scratch.exists():
                ctx.banner.show_message("The import failed. See the log.", "err")
                return
            try:
                if plan.out.exists():
                    backend.backup_before_overwrite(plan.out)   # the original first
                plan.out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(scratch, plan.out)
            except OSError as e:
                ctx.banner.show_message(f"Could not write {plan.out.name}: {e}", "err")
                return
            ctx.window.after_ship([plan.out], plan.in_place)
            ctx.banner.show_message(f"Text imported into {plan.out}. " + plan.note, "ok")
        ctx.runner.run(backend.strings_apply_argv(ctx.settings, self.lu, fn, scratch),
                       cwd=APPDIR, title="Importing text", on_done=done)

    def spelling(self):
        self.ctx.runner.run(backend.spelling_argv(self.ctx.settings, self.lu),
                            cwd=APPDIR, title="Checking spelling")


class TexturesTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.lu, self.folder = ctx, "", None
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        top = QHBoxLayout()
        self.export_btn = QPushButton("Export textures")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export)
        self.open_btn = QPushButton("Open export folder")
        self.open_btn.clicked.connect(self.open_folder)
        self.state = label("", "muted")
        top.addWidget(self.export_btn)
        top.addWidget(self.open_btn)
        top.addWidget(self.state, 1)
        v.addLayout(top)
        body = QHBoxLayout()
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(120, 90))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setSpacing(8)
        self.grid.setWordWrap(True)
        self.grid.currentItemChanged.connect(self._picked)
        body.addWidget(self.grid, 1)
        side = QFrame()
        side.setObjectName("card")
        side.setFixedWidth(300)
        sv = QVBoxLayout(side)
        self.preview = QLabel("Select a texture")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.details = label("", "muted", True)
        self.replace_btn = QPushButton("Replace with PNG or DDS…")
        self.replace_btn.clicked.connect(self.replace)
        sv.addWidget(self.preview)
        sv.addWidget(self.details)
        sv.addWidget(self.replace_btn)
        sv.addStretch(1)
        body.addWidget(side)
        v.addLayout(body, 1)

    def load(self, lu):
        self.lu = str(lu)
        p = self.ctx.project
        base = p.exports_dir("textures", Path(lu).stem) if p else \
            self.ctx.scratch_dir() / "textures" / Path(lu).stem
        self.folder = base
        self.grid.clear()
        self.preview.setText("Select a texture")
        self.details.setText("")
        self._scan()

    def export(self):
        base = self.folder
        (base / "chunks").mkdir(parents=True, exist_ok=True)
        self.state.setText("Exporting…")
        run = self.ctx.runner.run
        run(backend.extract_argv(self.ctx.settings, self.lu, base / "chunks"), cwd=APPDIR,
            title="Extracting", on_done=lambda c, o, e: run(
                backend.convert_argv(self.ctx.settings, base / "chunks", base / "images"),
                cwd=APPDIR, title="Converting textures",
                on_done=lambda c2, o2, e2: self._scan()) if c == 0 else self._scan())

    def _scan(self):
        self.grid.clear()
        imgs = sorted((self.folder / "images").rglob("*.png")) if self.folder else []
        for p in imgs:
            pm = QPixmap(str(p))
            it = QListWidgetItem(QIcon(pm.scaled(120, 90, Qt.KeepAspectRatio,
                                                 Qt.SmoothTransformation)), p.stem)
            it.setData(Qt.UserRole, str(p))
            self.grid.addItem(it)
        self.state.setText(f"{len(imgs)} texture image(s) in the export." if imgs else
                           "Not exported yet: click Export textures to see them here.")

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if self.folder and self.folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    def _picked(self, item, _prev=None):
        if item is None:
            return
        pm = QPixmap(item.data(Qt.UserRole))
        self.preview.setPixmap(pm.scaled(270, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.details.setText(f"{item.text()}\n{pm.width()} x {pm.height()} pixels")

    def replace(self):
        it = self.grid.currentItem()
        if it is None:
            self.ctx.banner.show_message("Select a texture first.", "warn")
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Choose your image", "",
                                            "Images (*.png *.dds)",
                                            options=QFileDialog.DontUseNativeDialog)
        if not fn:
            return
        try:
            backend.texture_replace(self.ctx.project, self.lu, it.text(), fn)
        except backend.NotAvailable as e:
            self.ctx.not_available(e)


class ToolStack(QScrollArea):
    """A scrolling stack of tool forms (used for Models & sound)."""

    def __init__(self, ctx, titles):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        self.forms = []
        for t in titles:
            f = ToolForm(toolspecs.find(t), ctx)
            self.forms.append(f)
            v.addWidget(f)
        v.addStretch(1)
        self.setWidget(inner)

    def prefill(self):
        for f in self.forms:
            f.prefill()


class InfoTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(mono_font(10))
        v.addWidget(self.text, 1)
        v.addWidget(label("Advanced tools for this container:", "muted"))
        row = QHBoxLayout()
        for t in ("Extract chunks", "Decompress image", "Repack raw image"):
            b = QPushButton(t + "…")
            b.clicked.connect(lambda _=False, t=t: ctx.open_tool(t))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

    def set_text(self, text):
        self.text.setPlainText(text)


class ContainerView(QWidget):
    """Everything about one container, in tabs. Only the tabs with content show."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.lu = ctx, ""
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 12, 4)
        head.setSpacing(10)
        self.name = label("", "heading")
        self.badge = label("", "badge")
        self.meta = label("", "muted")
        for w in (self.name, self.badge, self.meta):
            head.addWidget(w)
        head.addStretch(1)
        v.addLayout(head)
        self.tabs = QTabWidget()
        self.scripts = ScriptsTab(ctx)
        self.text = TextTab(ctx)
        self.textures = TexturesTab(ctx)
        self.models = ToolStack(ctx, ["Convert textures and models", "Sound banks",
                                      "Sound streams", "Character model (GLB)",
                                      "Menu movies (Panic in Paradise)"])
        self.info = InfoTab(ctx)
        self.pages = [("Scripts", self.scripts), ("Text", self.text),
                      ("Textures", self.textures), ("Models && sound", self.models),
                      ("Info", self.info)]
        for name, w in self.pages:
            self.tabs.addTab(w, name)
        v.addWidget(self.tabs, 1)
        self.scripts.listed.connect(lambda n: self._count("Scripts", n))
        self.textures_count = None

    def _count(self, base, n):
        i = [nm for nm, _ in self.pages].index(base)
        self.tabs.setTabText(i, f"{base} ({n})")

    def show_tab(self, name):
        for i, (nm, _w) in enumerate(self.pages):
            if nm.replace("&&", "&") .startswith(name):
                self.tabs.setCurrentIndex(i)

    def load(self, lu):
        self.lu = str(lu)
        game = container_game(lu)
        self.name.setText(Path(lu).name)
        self.badge.setText(GAME_NAMES.get(game, "Unknown format"))
        self.meta.setText(self.ctx.project.relative(lu) if self.ctx.project else "")
        self.tabs.setTabText(0, "Scripts")
        self.scripts.load(lu)
        self.text.load(lu)
        self.textures.load(lu)
        self.models.prefill()
        self.info.set_text("Reading container info…")
        self.ctx.runner.run(backend.info_argv(self.ctx.settings, lu), cwd=APPDIR,
                            title="Reading info", quiet=True,
                            on_done=lambda c, o, e, lu=str(lu): self._info(lu, c, o, e))

    def _info(self, lu, code, out, err):
        if lu != self.lu:
            return
        self.info.set_text(out + err)
        m = re.search(r"^\s*(\d+) x texture\s*$", out, re.M)
        n = int(m.group(1)) if m else 0
        i = [nm for nm, _ in self.pages].index("Textures")
        self.tabs.setTabVisible(i, code != 0 or n > 0)
        self.tabs.setTabText(i, f"Textures ({n})" if n else "Textures")
