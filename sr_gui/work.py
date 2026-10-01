"""Run a function in a background thread and hear back on the GUI thread."""
from PySide6.QtCore import QThread, Signal


class Cancelled(Exception):
    pass


class Worker(QThread):
    """`fn(progress)` runs off the GUI thread. `progress(*args)` may be called by
    fn to report (it raises Cancelled after cancel(), which stops fn)."""
    done = Signal(object, object)          # (result, exception or None)
    progressed = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False
        self.finished.connect(self.deleteLater)

    def cancel(self):
        self._cancel = True

    def _progress(self, *args):
        if self._cancel:
            raise Cancelled()
        self.progressed.emit(args)

    def run(self):
        try:
            self.done.emit(self.fn(self._progress), None)
        except BaseException as e:          # reported to the GUI thread, never lost
            self.done.emit(None, e)
