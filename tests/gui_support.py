"""Shared helpers for the offscreen GUI tests."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:                                     # pragma: no cover
    HAVE_QT = False

import game_paths

NB1_CANDIDATES = [game_paths.NB1_DIR]
NB1 = next((p for p in NB1_CANDIDATES if (p / "global.lu").exists()), None)
PIP = game_paths.PIP_DIR


def pump(cond, timeout=90):
    end = time.time() + timeout
    app = QApplication.instance()
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 30)
        if cond():
            return True
    return False


def scratch_project(source, names):
    """A temp folder holding copies of some game containers (never the originals).
    Returns (folder, cleanup)."""
    d = tempfile.TemporaryDirectory()
    for n in names:
        shutil.copyfile(Path(source) / n, Path(d.name) / n)
    return Path(d.name), d


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        cls.cache = tempfile.TemporaryDirectory()
        os.environ["SEAMRIPPER_HOME"] = cls.home.name
        os.environ["SEAMRIPPER_CACHE"] = cls.cache.name    # never the user's real caches
        cls.app = QApplication.instance() or QApplication([])
        from sr_gui import backend, mainwindow
        cls.backend, cls.mw = backend, mainwindow

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SEAMRIPPER_HOME", None)
        os.environ.pop("SEAMRIPPER_CACHE", None)
        cls.home.cleanup()
        cls.cache.cleanup()

    def window(self):
        w = self.mw.Main()
        self.addCleanup(w.close)
        w.show()
        return w

    def idle(self, w, timeout=90):
        self.assertTrue(pump(lambda: not w.runner.busy(), timeout))

    def open_script(self, w, folder, container, script):
        """Open `script` of `container` in project `folder` and wait for it."""
        w.open_project(str(folder))
        w.open_container(str(Path(folder) / container))
        sc = w.view.scripts
        self.assertTrue(pump(lambda: sc.list.count() > 0 and not w.runner.busy()))
        target = next(s for s in sc.scripts if s.name == script)
        sc.select_index(target.index)
        self.assertTrue(pump(lambda: sc.draft is not None and sc.draft.index == target.index
                             and not w.runner.busy()))
        return sc
