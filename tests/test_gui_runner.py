"""The GUI's process holders (Runner, SideProc, SearchRun) shut down without Python
errors: a cancelled run, or one whose window closed, must not call back into Python
objects Qt already deleted ("Internal C++ object already deleted")."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_support import HAVE_QT  # noqa: E402  (also sets the offscreen platform)

if HAVE_QT:
    import shiboken6
    from PySide6.QtCore import SIGNAL, QEvent, QEventLoop, QObject, QProcess, Signal
    from PySide6.QtWidgets import QApplication
    from sr_gui.runner import Runner, SideProc, alive, drop
    from sr_gui.search import SearchRun

    class Log(QObject):
        message = Signal(str, str)

        def command(self, *_a):
            pass

        def write(self, *_a):
            pass

        def stamp(self, *_a):
            pass

# a child that keeps writing to both pipes, so output is pending when it is stopped
CHATTY = [sys.executable, "-c",
          "import sys, time\n"
          "for i in range(200):\n"
          "    print(i, flush=True); print(i, file=sys.stderr, flush=True); time.sleep(0.01)"]
SIGNALS = ("readyReadStandardOutput()", "readyReadStandardError()",
           "finished(int,QProcess::ExitStatus)", "errorOccurred(QProcess::ProcessError)")


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class Teardown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.errors = []
        old = sys.excepthook
        sys.excepthook = lambda *a: self.errors.append(a[1])   # errors raised in slots
        self.addCleanup(setattr, sys, "excepthook", old)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents(QEventLoop.AllEvents, 20)

    def test_drop_cuts_every_signal_before_the_kill(self):
        p = QProcess()
        for name in SIGNALS:
            getattr(p, name.split("(")[0]).connect(lambda *_a: None)
        p.start(CHATTY[0], CHATTY[1:])
        self.assertTrue(p.waitForStarted(5000))
        drop(p)
        self.assertEqual([p.receivers(SIGNAL(s)) for s in SIGNALS], [0] * 4)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)   # run deleteLater
        self.assertFalse(alive(p))

    def test_stopping_mid_output_raises_nothing(self):
        for delay in (0.05, 0.15, 0.3):
            side = SideProc(Log())
            side.start(CHATTY, lambda *_a: None)
            search = SearchRun(Log())
            search.start(CHATTY)
            runner = Runner(Log())
            runner.run(CHATTY)
            self.pump(delay)
            side.abort()
            search.cancel(quiet=True)
            runner.cancel()
            self.pump(0.3)
            self.assertFalse(runner.busy())
        self.assertEqual(self.errors, [])

    def test_owner_deleted_while_running_raises_nothing(self):
        # a closing window deletes its runners; Qt then kills the child and emits
        # finished into Python on the way out
        for make, go in ((Runner, lambda o: o.run(CHATTY)),
                         (SideProc, lambda o: o.start(CHATTY, lambda *_a: None)),
                         (SearchRun, lambda o: o.start(CHATTY))):
            o = make(Log())
            go(o)
            self.pump(0.1)
            shiboken6.delete(o)
            self.pump(0.3)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
