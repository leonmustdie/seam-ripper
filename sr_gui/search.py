"""One folder-wide script search: a streaming subprocess that can be cancelled."""
import shlex

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from . import backend


class SearchRun(QObject):
    """Runs `sr_search.py find` beside the job queue, so a long first index never blocks
    editing. Lines are parsed as they arrive and handed on in batches (one per read)."""
    progress = Signal(int, int, str)        # containers read, total, current container
    hits = Signal(list)                     # a batch of hit dicts
    finished = Signal(dict)                 # {'ok', 'cancelled', 'hits', 'message'}

    def __init__(self, log):
        super().__init__()
        self.log = log
        self.proc = None
        self.token = 0

    def running(self):
        return self.proc is not None

    def start(self, argv, cwd=None):
        self.cancel(quiet=True)
        self.token += 1
        token = self.token
        state = {"buf": b"", "err": [], "count": 0, "done": None}
        proc = self.proc = QProcess(self)
        if cwd:
            proc.setWorkingDirectory(str(cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(lambda: self._read(token, proc, state))
        proc.readyReadStandardError.connect(lambda: state["err"].append(
            bytes(proc.readAllStandardError()).decode("utf-8", "replace")))
        proc.finished.connect(lambda code, _s: self._fin(token, proc, state, code))
        proc.errorOccurred.connect(lambda e: self._fin(token, proc, state, -1)
                                   if e == QProcess.FailedToStart else None)
        self.log.command(" ".join(shlex.quote(a) for a in argv))
        proc.start(argv[0], argv[1:])

    def cancel(self, quiet=False):
        """Stop the search. Its results so far stay; `finished` says it was cancelled."""
        if self.proc is None:
            return
        proc, self.proc = self.proc, None
        self.token += 1
        proc.kill()
        proc.deleteLater()
        if not quiet:
            self.finished.emit({"ok": False, "cancelled": True, "hits": 0, "message": ""})

    def _read(self, token, proc, state):
        if token != self.token:
            return
        state["buf"] += bytes(proc.readAllStandardOutput())
        lines = state["buf"].split(b"\n")
        state["buf"] = lines.pop()
        self._lines(lines, state)

    def _lines(self, lines, state):
        batch, last = [], None
        for raw in lines:
            row = backend.parse_search_line(raw.decode("utf-8", "replace"))
            if row is None:
                continue
            if row["type"] == "hit":
                batch.append(row)
            elif row["type"] == "progress":
                last = row
            elif row["type"] == "done":
                state["done"] = row
        if last:
            self.progress.emit(last["done"], last["total"], last["container"])
        if batch:
            state["count"] += len(batch)
            self.hits.emit(batch)

    def _fin(self, token, proc, state, code):
        if token != self.token or self.proc is not proc:
            return
        try:
            state["buf"] += bytes(proc.readAllStandardOutput())
            state["err"].append(bytes(proc.readAllStandardError()).decode("utf-8", "replace"))
        except RuntimeError:
            return
        self._lines(state["buf"].split(b"\n"), state)
        self.proc = None
        proc.deleteLater()
        done = state["done"]
        err = "".join(state["err"]).strip()
        ok = code == 0 and done is not None
        if not ok and err:
            self.log.write(err[-800:], "err")
        self.finished.emit({"ok": ok, "cancelled": False, "hits": state["count"],
                            "message": "" if ok else (err.splitlines()[-1] if err else
                                                      "The search could not run. See the log.")})
