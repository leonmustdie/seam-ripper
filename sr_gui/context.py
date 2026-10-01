"""What every page needs from the window: settings, runner, log, pending edits."""
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .settings import save_settings


class Context(QObject):
    project_changed = Signal()
    file_changed = Signal(str)

    def __init__(self, settings, runner, log, banner):
        super().__init__()
        self.settings, self.runner, self.log, self.banner = settings, runner, log, banner
        self.project = None
        self.changes = None
        self.changes_listeners = []         # called whenever pending edits change
        self.current_file = ""
        self.window = None                  # the main window (navigation callbacks)

    def set_project(self, project):
        """Open `project` (or None) and load its saved drafts."""
        from .changes import ChangeSet
        self.project = project
        self.changes = ChangeSet(project.folder if project else None)
        self.changes.listeners.append(self._changes_fired)
        self.project_changed.emit()
        self._changes_fired()

    def _changes_fired(self):
        for fn in list(self.changes_listeners):
            fn()

    def save_settings(self):
        save_settings(self.settings)

    def not_available(self, exc):
        """Tell the user a feature isn't connected yet (never fake a result)."""
        self.banner.show_message(str(exc) + " It is being built and will appear here.", "warn")

    def set_current_file(self, path):
        self.current_file = str(path) if path else ""
        self.file_changed.emit(self.current_file)

    def scratch_dir(self):
        """Per-session folder for temporary .lua and .lu files."""
        if not hasattr(self, "_scratch"):
            import atexit, shutil, tempfile
            self._scratch = Path(tempfile.mkdtemp(prefix="seamripper_"))
            atexit.register(shutil.rmtree, self._scratch, True)
        return self._scratch

    # navigation: the main window fills these in
    def open_tool(self, title):
        if self.window:
            self.window.open_tool(title)

    def show_changes(self, key=None):
        if self.window:
            self.window.show_changes(key)

    def open_script(self, lu, index, line=None):
        if self.window:
            self.window.open_script(lu, index, line)
