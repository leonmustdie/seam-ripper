"""Planning and running a ship: exact preview, other containers, value checks."""
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import backend
from .luahelp import functions
from .paths import APPDIR, FROZEN
from .runner import SideProc
from .work import Cancelled, Worker


def norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


class Copy:
    """Another container that carries the same script."""

    def __init__(self, path, index, identical, size, same_folder):
        self.path, self.index, self.size = str(path), index, size
        self.identical = identical
        self.checked = identical and same_folder
        if not identical:
            self.reason = "a different version of this script; it would not take your edit"
        elif not same_folder:
            self.reason = "in another folder"
        else:
            self.reason = ""


class Where:
    def __init__(self):
        self.status = "busy"                # busy | ok | error
        self.copies = []
        self.message = ""


class Preview:
    def __init__(self, keys):
        self.status = "busy"                # busy | ok | error
        self.keys = keys
        self.data = None
        self.errors = []                    # [(draft key or None, error dict)]
        self.notes = []                     # [{'line','message'}] non-blocking
        self.message = ""


class ShipPlanner(QObject):
    """Everything the Changes page shows about a ship that hasn't happened yet."""
    changed = Signal()
    schema_progress = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.where = {}                     # draft key -> Where
        self.previews = {}                  # container -> Preview
        self.value_warnings = {}            # draft key -> (text signature, [warning])
        self.acked = None                   # signature of the warnings the user accepted
        self.schema_state = "unknown"       # unknown | missing | ready | building | error
        self.schema_msg = ""
        self.schema = None
        self._side = {}                     # container -> SideProc (preview)
        self._where_proc = SideProc(ctx.log)
        self._where_queue = []
        self._workers = []
        self._warm = {}                     # PiP container -> 'busy' | 'ready' | 'error'
        self._warm_cbs = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.refresh)
        self.active = False                 # the Changes page is showing
        ctx.changes_listeners.append(self._changes)

    # ------------------------------------------------------------ helpers
    def checked(self, lu=None):
        ch = self.ctx.changes
        return [d for d in ch.pending()
                if d.key not in ch.unchecked and (lu is None or d.lu == lu)]

    def edit_file(self, d):
        p = self.ctx.scratch_dir() / f"edit_{abs(hash(d.lu)) % 10**8}_{d.index}.lua"
        p.write_text(d.text, encoding="utf-8")
        return p

    def draft_for_file(self, path, drafts):
        n = norm(path)
        for d in drafts:
            if norm(self.edit_file(d)) == n:
                return d
        return None

    def _changes(self):
        for k in [k for k in self.where if k not in self.ctx.changes.drafts]:
            del self.where[k]
        for lu in [lu for lu in self.previews if not self.checked(lu)]:
            self.previews.pop(lu)
        if self.active:
            self._timer.start()

    # ------------------------------------------------------------ refresh
    def refresh(self):
        """Re-run the preview and value checks for what is pending (debounced)."""
        for lu in {d.lu for d in self.checked()}:
            self.request_preview(lu)
        for d in self.checked():
            self.request_where(d)
            if d.game == "pip":
                self.request_warnings(d)

    # ------------------------------------------------------------ preview
    def request_preview(self, lu):
        drafts = self.checked(lu)
        if not drafts:
            self.previews.pop(lu, None)
            self.changed.emit()
            return
        ctx = self.ctx
        pv = self.previews[lu] = Preview([d.key for d in drafts])
        edits = [(d.index, self.edit_file(d)) for d in drafts]
        out = backend.plan_output(ctx.project, ctx.settings, lu).out
        proc = self._side.setdefault(lu, SideProc(ctx.log))
        proc.start(backend.ship_argv(ctx.settings, lu, edits, out, preview=True),
                   lambda c, o, e: self._preview_done(lu, pv, drafts, c, o, e), cwd=APPDIR)
        self.changed.emit()

    def _preview_done(self, lu, pv, drafts, code, out, err):
        if self.previews.get(lu) is not pv:
            return
        data = backend.parse_json(out)
        pv.data = data
        pv.notes = backend.parse_notes(out, err)
        if data is None:
            pv.status, pv.message = "error", "The preview could not run. See the log."
            pv.errors = [(None, e) for e in backend.parse_errors(out, err)]
        else:
            pv.status = "ok" if data.get("ok") else "error"
            for e in data.get("errors", []):
                d = self.draft_for_file(e.get("file", ""), drafts) if e.get("file") else None
                if d is None and len(drafts) == 1:
                    d = drafts[0]
                pv.errors.append((d.key if d else None, e))
        self.changed.emit()

    def script_info(self, d):
        """The preview's entry for one draft's script, or None."""
        pv = self.previews.get(d.lu)
        if not pv or not pv.data:
            return None
        for s in pv.data.get("scripts", []):
            if s.get("index") == d.index:
                return s
        return None

    def budget_for(self, d):
        """PiP budget dict for the draft from the preview, or None."""
        pv = self.previews.get(d.lu)
        if not pv or not pv.data or not pv.data.get("targets"):
            return None
        for b in pv.data["targets"][0].get("budget", []) or []:
            if b.get("record") == d.index:
                return b
        return None

    def function_names(self, d):
        """[(name, line)] for the functions the exact preview says will be recompiled
        (name from the outline; 'top-level code' for line 0)."""
        info = self.script_info(d)
        if info is None:
            return None
        funcs = functions(d.text)
        out = []
        for f in info.get("functions", []):
            line = f.get("line", 0)
            name = "top-level code"
            if line:
                for n, ln, _b in funcs:
                    if ln <= line:
                        name = n
            out.append((name, line))
        return out

    # ------------------------------------------------------------ where
    def request_where(self, d):
        if d.key in self.where and self.where[d.key].status != "error":
            return
        self.where[d.key] = Where()
        if d.key not in self._where_queue:
            self._where_queue.append(d.key)
        self._next_where()
        self.changed.emit()

    def _next_where(self):
        if self._where_proc.running() or not self._where_queue:
            return
        key = self._where_queue.pop(0)
        d = self.ctx.changes.get(key)
        if d is None or self.ctx.project is None:
            return self._next_where()
        argv = backend.where_argv(self.ctx.settings, self.ctx.project.folder, d.lu,
                                  d.name, d.index)
        self._where_proc.start(argv, lambda c, o, e: self._where_done(key, d, c, o, e),
                               cwd=APPDIR)

    def _where_done(self, key, d, code, out, err):
        w = self.where.get(key)
        data = backend.parse_json(out)
        if w is not None:
            if code != 0 or data is None:
                w.status, w.message = "error", "Could not look for other copies. See the log."
            else:
                w.status = "ok"
                here = norm(Path(d.lu).parent)
                w.copies = [Copy(c["container"], c.get("index"), bool(c.get("identical")),
                                 c.get("size", 0), norm(Path(c["container"]).parent) == here)
                            for c in data.get("copies", [])
                            if norm(c["container"]) != norm(d.lu)]
        self.changed.emit()
        self._next_where()

    def where_note(self):
        return ("Looking for other copies for the first time can take about "
                + ("2 to 3 minutes" if FROZEN else "half a minute")
                + " on a whole game folder; after that it takes a second.")

    # ------------------------------------------------------------ PiP value checks
    def request_warnings(self, d):
        sig = (d.key, d.text)
        cur = self.value_warnings.get(d.key)
        if cur and cur[0] == hash(sig):
            return
        self.value_warnings[d.key] = (hash(sig), [])
        if self.schema_state == "unknown":
            self.schema = backend.schema_cached()
            self.schema_state = "ready" if self.schema else "missing"

        def job(_p, orig=d.orig, text=d.text, schema=self.schema):
            return backend.value_warnings(orig, text, schema)
        self._run(job, lambda res, exc, key=d.key, h=hash(sig): self._warned(key, h, res, exc))

    def _warned(self, key, h, res, exc):
        cur = self.value_warnings.get(key)
        if cur is None or cur[0] != h:
            return
        self.value_warnings[key] = (h, res or [])
        self.changed.emit()

    def warnings_for(self, d):
        cur = self.value_warnings.get(d.key)
        return cur[1] if cur else []

    def warning_signature(self):
        """What the user is asked to accept: value warnings and preview notes of
        the drafts that would ship."""
        items = []
        for d in self.checked():
            items += [(d.key, w.get("message")) for w in self.warnings_for(d)]
            info = self.script_info(d)
            if info:
                items += [(d.key, w) for w in info.get("warnings", [])]
        return tuple(items)

    def build_schema(self, folder):
        """Build the PiP data schema in the background (about 4 minutes)."""
        if self.schema_state == "building":
            return

        def job(progress):
            return backend.schema_build(folder, progress=lambda unit, n: progress(unit, n))
        self.schema_state, self.schema_msg = "building", "Starting…"
        w = self._run(job, self._schema_done)
        w.progressed.connect(lambda a: self._schema_prog(a))
        self._schema_worker = w
        self.changed.emit()

    def _schema_prog(self, args):
        unit, n = args
        self.schema_msg = f"{n} scripts read (in {Path(str(unit)).name})"
        self.schema_progress.emit(self.schema_msg)
        self.changed.emit()

    def cancel_schema(self):
        w = getattr(self, "_schema_worker", None)
        if w is not None and self.schema_state == "building":
            w.cancel()

    def _schema_done(self, res, exc):
        if exc is not None:
            cancelled = isinstance(exc, Cancelled)
            self.schema_state = "missing" if cancelled else "error"
            self.schema_msg = "Cancelled." if cancelled else f"The build failed: {exc}"
        else:
            self.schema, self.schema_state, self.schema_msg = res, "ready", ""
            self.value_warnings.clear()
            for d in self.checked():
                if d.game == "pip":
                    self.request_warnings(d)
        self.changed.emit()

    def _run(self, fn, done):
        w = Worker(fn, self)
        self._workers.append(w)

        def fin(res, exc):
            if w in self._workers:
                self._workers.remove(w)
            done(res, exc)
        w.done.connect(fin)
        w.start()
        return w

    # ------------------------------------------------------------ PiP warm-up
    def warm_pip(self, lu, on_ready=None):
        """Parse a PiP container in the background so live checks are instant.
        `on_ready()` is called on the GUI thread once it is done."""
        k = norm(lu)
        state = self._warm.get(k)
        if state == "ready":
            if on_ready:
                on_ready()
            return
        if on_ready:
            self._warm_cbs.setdefault(k, []).append(on_ready)
        if state == "busy":
            return
        self._warm[k] = "busy"

        def done(res, exc):
            self._warm[k] = "ready" if exc is None else "error"
            for fn in self._warm_cbs.pop(k, []):
                fn()
        self._run(lambda _p: backend.pip_warm(lu), done)

    def is_warm(self, lu):
        return self._warm.get(norm(lu)) == "ready"

    def forget_warm(self, lu):
        self._warm.pop(norm(lu), None)

    # ------------------------------------------------------------ groups and ship
    def groups(self):
        """[(container, [drafts], [also container paths])] for the checked drafts.
        Scripts of one container that go to different sets of other containers ship
        separately; with a 'ship to' folder they go together to the common ones."""
        ship_to = bool(backend.ship_to(self.ctx.project, self.ctx.settings))
        per = {}
        for d in self.checked():
            w = self.where.get(d.key)
            also = frozenset(norm(c.path) for c in (w.copies if w else []) if c.checked)
            paths = {norm(c.path): c.path for c in (w.copies if w else [])}
            per.setdefault(d.lu, []).append((d, also, paths))
        out = []
        for lu, items in per.items():
            sets = {a for _d, a, _p in items}
            if ship_to and len(sets) > 1:
                common = frozenset.intersection(*sets)
                items = [(d, common, p) for d, _a, p in items]
                sets = {common}
            for s in sets:
                drafts = [d for d, a, _p in items if a == s]
                paths = {}
                for _d, _a, p in items:
                    paths.update(p)
                out.append((lu, drafts, sorted(paths[n] for n in s)))
        return out

    def ship(self, force, on_done):
        """Ship every checked draft: one `lu_lua.py ship` per container (and per
        set of other containers). on_done(results) with one dict per group:
        {'lu', 'drafts', 'ok', 'data', 'errors', 'stderr'}; stops at the first failure."""
        ctx = self.ctx
        groups = self.groups()
        results = []

        def step(i):
            if i == len(groups):
                return on_done(results)
            lu, drafts, also = groups[i]
            plan = backend.plan_output(ctx.project, ctx.settings, lu)
            edits = [(d.index, self.edit_file(d)) for d in drafts]
            if also:
                folder = plan.out.parent
                out = folder
            else:
                out = plan.out
            argv = backend.ship_argv(ctx.settings, lu, edits, out, also=also, force=force)

            def fin(code, o, e):
                data = backend.parse_json(o)
                errs = backend.parse_errors(o, e)
                ok = code == 0 and bool(data) and data.get("ok", False)
                results.append({"lu": lu, "drafts": drafts, "ok": ok, "data": data,
                                "errors": errs, "stderr": e, "plan": plan,
                                "notes": backend.parse_notes(o, e)})
                if ok:
                    step(i + 1)
                else:
                    on_done(results)
            ctx.runner.run(argv, cwd=APPDIR, title=f"Shipping {Path(lu).name}",
                           quiet=True, on_done=fin)
        step(0)
