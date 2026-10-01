"""Background command runner: a queue of tool runs, one at a time, cancellable."""
import shlex
from collections import deque

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class Job:
    def __init__(self, argv, cwd, on_done, title, quiet):
        self.argv, self.cwd, self.on_done = argv, cwd, on_done
        self.title, self.quiet = title, quiet
        self.out, self.err = [], []


class Runner(QObject):
    """Runs commands without blocking the window. Every command is written to
    the log exactly as run. `on_done(code, stdout, stderr)` is called on the
    GUI thread when a job ends (code -1 if it was cancelled or didn't start)."""
    busy_changed = Signal(bool)
    title_changed = Signal(str)

    def __init__(self, log):
        super().__init__()
        self.log = log
        self.queue = deque()
        self.job = None
        self.proc = None
        self.cancelled = False

    def busy(self):
        return self.job is not None or bool(self.queue)

    def run(self, argv, cwd=None, on_done=None, title="", quiet=False):
        """Queue a command. `quiet` keeps its output out of the log (the command
        line itself is always logged)."""
        was_busy = self.busy()
        self.queue.append(Job(argv, cwd, on_done, title or argv[-1] if argv else "", quiet))
        if not was_busy:
            self.busy_changed.emit(True)
        if self.job is None:
            self._next()

    def cancel(self):
        """Stop the running command and drop everything queued behind it."""
        if not self.busy():
            return
        self.log.stamp("cancelled.")
        self.queue.clear()
        self.cancelled = True
        if self.proc is not None:
            self.proc.kill()
        else:
            self.cancelled = False

    def _next(self):
        if not self.queue:
            self.job = None
            self.busy_changed.emit(False)
            self.title_changed.emit("")
            return
        job = self.job = self.queue.popleft()
        self.cancelled = False
        proc = self.proc = QProcess(self)
        if job.cwd:
            proc.setWorkingDirectory(str(job.cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(lambda: self._read(job, proc, False))
        proc.readyReadStandardError.connect(lambda: self._read(job, proc, True))
        proc.finished.connect(lambda code, _s: self._fin(job, proc, code))
        proc.errorOccurred.connect(lambda e: self._failed(job, proc, e))
        self.log.command(" ".join(shlex.quote(a) for a in job.argv))
        self.title_changed.emit(job.title)
        proc.start(job.argv[0], job.argv[1:])

    def _read(self, job, proc, is_err):
        try:
            data = bytes(proc.readAllStandardError() if is_err
                         else proc.readAllStandardOutput()).decode("utf-8", "replace")
        except RuntimeError:                        # the window is closing under us
            return
        (job.err if is_err else job.out).append(data)
        if data and not job.quiet:
            self.log.write(data.rstrip("\n"))

    def _failed(self, job, proc, error):
        if error == QProcess.FailedToStart and job is self.job:
            self.log.write(f"could not start {job.argv[0]}", "err")
            self._fin(job, proc, -1)

    def _fin(self, job, proc, code):
        if job is not self.job:                     # already handled
            return
        self._read(job, proc, False)
        self._read(job, proc, True)
        if self.cancelled:
            code = -1
        self.log.stamp(f"done (exit {code})")
        if code != 0 and not self.cancelled:
            self.log.write(f"{job.title or 'The tool'} failed (exit {code}).", "err")
        self.job, self.proc = None, None
        try:
            proc.deleteLater()
        except RuntimeError:
            pass
        if job.on_done:
            try:
                job.on_done(code, "".join(job.out), "".join(job.err))
            except Exception as e:                  # a GUI callback must not wedge the queue
                self.log.write(f"internal error: {e}", "err")
        if self.job is None:
            self._next()


class SideProc(QObject):
    """One command that runs beside the queue (previews, lookups), so it never
    waits behind a long job. Starting another run drops the first one's result.
    The command line is logged; output only if the run fails."""

    def __init__(self, log):
        super().__init__()
        self.log = log
        self.proc = None
        self.token = 0

    def running(self):
        return self.proc is not None

    def start(self, argv, on_done, cwd=None):
        """on_done(code, stdout, stderr) is called if this run isn't superseded."""
        self.abort()
        self.token += 1
        token = self.token
        out, err = [], []
        proc = self.proc = QProcess(self)
        if cwd:
            proc.setWorkingDirectory(str(cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(
            lambda: out.append(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")))
        proc.readyReadStandardError.connect(
            lambda: err.append(bytes(proc.readAllStandardError()).decode("utf-8", "replace")))

        def fin(code=-1, _s=None):
            if token != self.token or self.proc is not proc:
                return
            try:
                out.append(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))
                err.append(bytes(proc.readAllStandardError()).decode("utf-8", "replace"))
            except RuntimeError:
                return
            self.proc = None
            proc.deleteLater()
            if code != 0:
                self.log.write("".join(err).strip()[-800:])
            # replaces "running a tool" in the status bar
            self.log.message.emit(*(("done", "info") if code == 0
                                    else (f"failed (exit {code})", "err")))
            on_done(code, "".join(out), "".join(err))
        proc.finished.connect(fin)
        proc.errorOccurred.connect(
            lambda e: fin(-1) if e == QProcess.FailedToStart else None)
        self.log.command(" ".join(shlex.quote(a) for a in argv))
        proc.start(argv[0], argv[1:])

    def abort(self):
        if self.proc is not None:
            self.token += 1
            proc, self.proc = self.proc, None
            proc.kill()
            proc.deleteLater()
