"""Changes: the pending-edits list (sidebar) and the review-and-ship page."""
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import backend, shipping, style
from .luahelp import side_by_side, unified_diff
from .patches_page import PatchDialog
from .paths import APPDIR
from .widgets import label, mono_font
from .work import Worker


class ChangesSidebar(QWidget):
    """Checklist of pending edits. Untick one to leave it out of a Ship."""
    selected = Signal(object)               # (container, index)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(label("PENDING CHANGES", "muted"))
        self.tree = QTreeWidget()
        self.tree.setObjectName("tree")
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemChanged.connect(self._toggled)
        v.addWidget(self.tree, 1)
        self.note = label("", "muted", True)
        v.addWidget(self.note)
        self.discard_btn = QPushButton("Discard selected edit")
        self.discard_btn.clicked.connect(self.discard)
        v.addWidget(self.discard_btn)
        ctx.changes_listeners.append(self.refresh)
        self.refresh()

    def refresh(self):
        keep = self.current_key()
        self.tree.blockSignals(True)
        self.tree.clear()
        drafts = self.ctx.changes.pending() if self.ctx.changes else []
        if drafts:
            top = QTreeWidgetItem([f"Scripts ({len(drafts)})"])
            self.tree.addTopLevelItem(top)
            for d in drafts:
                it = QTreeWidgetItem([f"{d.name}   {Path(d.lu).name}"])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked if d.key in self.ctx.changes.unchecked
                                 else Qt.Checked)
                it.setData(0, Qt.UserRole, d.key)
                top.addChild(it)
                if d.key == keep:
                    self.tree.setCurrentItem(it)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.note.setText("" if drafts else
                          "No changes yet. Edit a script and it appears here.")
        self.discard_btn.setEnabled(bool(drafts))

    def current_key(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def checked_keys(self):
        ch = self.ctx.changes
        return {d.key for d in ch.pending() if d.key not in ch.unchecked}

    def _clicked(self, item, _c):
        key = item.data(0, Qt.UserRole)
        if key:
            self.selected.emit(key)

    def _toggled(self, item, _c):
        key = item.data(0, Qt.UserRole)
        if key and (item.checkState(0) == Qt.Checked) == (key in self.ctx.changes.unchecked):
            self.ctx.changes.set_checked(key, item.checkState(0) == Qt.Checked)

    def discard(self):
        key = self.current_key()
        if key:
            self.ctx.changes.discard(key)
            self.ctx.window.reload_current_script(key)


class DiffView(QWidget):
    """Unified or side-by-side diff of one script."""

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.uni = self._edit()
        self.left, self.right = self._edit(), self._edit()
        pair = QWidget()
        h = QHBoxLayout(pair)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(1)
        h.addWidget(self.left)
        h.addWidget(self.right)
        self.left.verticalScrollBar().valueChanged.connect(self.right.verticalScrollBar().setValue)
        self.right.verticalScrollBar().valueChanged.connect(self.left.verticalScrollBar().setValue)
        self.left.horizontalScrollBar().valueChanged.connect(self.right.horizontalScrollBar().setValue)
        self.right.horizontalScrollBar().valueChanged.connect(self.left.horizontalScrollBar().setValue)
        self.stack.addWidget(self.uni)
        self.stack.addWidget(pair)
        v.addWidget(self.stack)
        self.args = None
        self.side = False
        style.notifier.changed.connect(self.render)

    def _edit(self):
        e = QPlainTextEdit()
        e.setReadOnly(True)
        e.setFont(mono_font(10))
        e.setLineWrapMode(QPlainTextEdit.NoWrap)
        return e

    def set_side_by_side(self, on):
        self.side = on
        self.stack.setCurrentIndex(1 if on else 0)
        self.render()

    def show_diff(self, orig, new, name):
        self.args = (orig, new, name)
        self.render()

    @staticmethod
    def _paint(edit, kinds):
        c = style.colors()
        edit.setStyleSheet(f"QPlainTextEdit {{ background: {c['code_bg']}; color: {c['code_text']}; "
                           f"border: 1px solid {c['line']}; }}")
        sels = []
        for n, kind in enumerate(kinds):
            col = {"add": c["add"], "del": c["del"], "hunk": c["gutter"]}.get(kind)
            if col:
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(QColor(col))
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(edit.document().findBlockByNumber(n))
                sels.append(s)
        edit.setExtraSelections(sels)

    def render(self):
        if not self.args:
            return
        orig, new, name = self.args
        if not self.side:
            lines = unified_diff(orig, new, name)
            self.uni.setPlainText("".join(l if l.endswith("\n") else l + "\n" for l in lines)
                                  or "No differences.")
            kinds = ["hunk" if l.startswith(("@@", "---", "+++")) else
                     "add" if l.startswith("+") else "del" if l.startswith("-") else ""
                     for l in lines]
            self._paint(self.uni, kinds)
        else:
            rows = side_by_side(orig, new)
            fmt = lambda no, t: f"{no:>5}  {t}" if no else " " * 7
            self.left.setPlainText("\n".join(fmt(r[0], r[1]) for r in rows))
            self.right.setPlainText("\n".join(fmt(r[2], r[3]) for r in rows))
            self._paint(self.left, ["del" if r[4] in ("del", "chg") else "" for r in rows])
            self._paint(self.right, ["add" if r[4] in ("add", "chg") else "" for r in rows])


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w:
            w.deleteLater()
        elif it.layout():
            _clear(it.layout())


class ReviewPage(QWidget):
    """The diff, exactly what will be recompiled, other containers, checks, and Ship."""

    def __init__(self, ctx, sidebar):
        super().__init__()
        self.ctx, self.sidebar = ctx, sidebar
        self.planner = ctx.planner
        self.key = None
        self.stale = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(14, 10, 14, 8)
        head.setSpacing(10)
        self.title = label("Review your changes", "heading")
        self.sub = label("", "muted")
        self.uni_btn, self.side_btn = QPushButton("Unified"), QPushButton("Side by side")
        for b in (self.uni_btn, self.side_btn):
            b.setCheckable(True)
        self.uni_btn.setChecked(True)
        self.uni_btn.clicked.connect(lambda: self._mode(False))
        self.side_btn.clicked.connect(lambda: self._mode(True))
        head.addWidget(self.title)
        head.addWidget(self.sub, 1)
        head.addWidget(self.uni_btn)
        head.addWidget(self.side_btn)
        v.addLayout(head)
        self.empty = label("Nothing here yet.\n\nEdit a script on the Files page and "
                           "it shows up here.", "muted", True)
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty, 1)

        self.split = QSplitter(Qt.Vertical)
        self.diff = DiffView()
        self.split.addWidget(self.diff)
        cards = QWidget()
        low = QHBoxLayout(cards)
        low.setContentsMargins(14, 10, 14, 10)
        self.card_funcs = self._card(low)
        self.card_also = self._card(low)
        self.card_checks = self._card(low)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(cards)
        self.split.addWidget(scroll)
        self.split.setSizes([300, 260])
        self.split.setStretchFactor(0, 1)
        v.addWidget(self.split, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 14, 8)
        self.note = label("", "muted", True)
        self.patch_btn = QPushButton("Save as patch…")
        self.patch_btn.clicked.connect(self.make_patch)
        self.force_btn = QPushButton("Ship anyway…")
        self.force_btn.setToolTip("Ship although the checks objected. Asks first.")
        self.force_btn.clicked.connect(lambda: self.ship(False, force=True))
        self.ship_btn = QPushButton("Ship")
        self.ship_btn.clicked.connect(lambda: self.ship(False))
        self.launch_btn = QPushButton("Ship && launch")
        self.launch_btn.setObjectName("primary")
        self.launch_btn.clicked.connect(lambda: self.ship(True))
        bar.addWidget(self.note, 1)
        for b in (self.patch_btn, self.force_btn, self.ship_btn, self.launch_btn):
            bar.addWidget(b)
        self.bar = QFrame()
        self.bar.setLayout(bar)
        v.addWidget(self.bar)

        sidebar.selected.connect(self.show_key)
        ctx.changes_listeners.append(self.refresh)
        self.planner.changed.connect(self.render_cards)
        style.notifier.changed.connect(self.render_cards)
        self.refresh()

    def _card(self, layout):
        f = QFrame()
        f.setObjectName("card")
        f.setLayout(QVBoxLayout())
        layout.addWidget(f, 1)
        return f

    def _mode(self, side):
        self.side_btn.setChecked(side)
        self.uni_btn.setChecked(not side)
        self.diff.set_side_by_side(side)

    # ------------------------------------------------------------ state
    def refresh(self):
        ch = self.ctx.changes
        drafts = ch.pending() if ch else []
        have = bool(drafts)
        for w in (self.split, self.uni_btn, self.side_btn):
            w.setVisible(have)
        self.empty.setVisible(not have)
        if have:
            if self.key not in {d.key for d in drafts}:
                self.key = drafts[0].key
            self.stale = True
            if self.isVisible():
                self.showEvent(None)
        else:
            self.key = None
            self.sub.setText("")
        self.render_cards()

    def showEvent(self, ev):
        if ev is not None:
            super().showEvent(ev)
        self.planner.active = True
        if self.stale and self.key:
            self.stale = False
            self.show_key(self.key)
        self.planner.refresh()

    def hideEvent(self, ev):
        self.planner.active = False
        super().hideEvent(ev)

    def show_key(self, key):
        self.stale = False
        d = self.ctx.changes.get(key) if self.ctx.changes else None
        if d is None:
            return
        self.key = key
        self.title.setText(d.name)
        self.sub.setText(f"{Path(d.lu).name}  ·  {len(d.functions())} function(s) changed")
        self.diff.show_diff(d.orig, d.text, d.name)
        self.planner.request_where(d)
        self.render_cards()

    def _draft(self):
        return self.ctx.changes.get(self.key) if self.ctx.changes and self.key else None

    # ------------------------------------------------------------ cards
    def render_cards(self):
        d = self._draft()
        for card in (self.card_funcs, self.card_also, self.card_checks):
            _clear(card.layout())
        if d is None:
            self._update_bar()
            return
        self._funcs_card(d)
        self._also_card(d)
        self._checks_card(d)
        self._update_bar()

    def _funcs_card(self, d):
        lay, pl = self.card_funcs.layout(), self.planner
        lay.addWidget(label("WHAT SHIP WILL DO", "muted"))
        pv = pl.previews.get(d.lu)
        if pv is None or pv.status == "busy":
            lay.addWidget(label("Checking exactly what Ship will do…", "muted", True))
            lay.addStretch(1)
            return
        for key, err in pv.errors:
            if key in (None, d.key):
                text, _f = backend.friendly(err, d.game)
                lb = label(("Line %d: " % err["line"] if err.get("line") else "") + text,
                           "err", True)
                lay.addWidget(lb)
                if err.get("line"):
                    b = QPushButton(f"Go to line {err['line']}")
                    b.clicked.connect(lambda _=False, dd=d, ln=err["line"]:
                                      self.ctx.window.open_script(dd.lu, dd.index, ln))
                    lay.addWidget(b)
        names = pl.function_names(d)
        if names is not None:
            if names:
                lay.addWidget(label("Recompiled:\n" + "\n".join(
                    f"✓ {n}" + (f"  (line {ln})" if ln else "") for n, ln in names), "ok", True))
                lay.addWidget(label("Everything else keeps its original bytes.", "muted", True))
            elif d.game == "nb1":
                lay.addWidget(label("No function-level change: the tools found nothing to "
                                    "recompile in this edit.", "warn", True))
        b = pl.budget_for(d)
        if b:
            kind, txt = self._budget_text(b)
            lay.addWidget(label(txt, kind, True))
        info = pl.script_info(d)
        for w in (info or {}).get("warnings", []):
            lay.addWidget(label("! " + w, "warn", True))
        single = len(pv.keys) == 1
        for n in pv.notes:
            lay.addWidget(label(f"Note, line {n['line']}: {n['message']}", "warn", True))
            if single:
                b = QPushButton(f"Go to line {n['line']}")
                b.clicked.connect(lambda _=False, ln=n["line"]:
                                  self.ctx.window.open_script(d.lu, d.index, ln))
                lay.addWidget(b)
        for h in (info or {}).get("hash_calls", []):
            lay.addWidget(label(f'HASH("{h["name"]}") becomes {h["value"]}', "muted", True))
        lay.addStretch(1)

    @staticmethod
    def _budget_text(b):
        limit, edited = b.get("budget"), b.get("edited")
        squeezed = b.get("squeezed")
        if b.get("fits"):
            extra = (" It fits after squeezing whitespace."
                     if edited is not None and limit is not None and edited > limit else "")
            return "ok", (f"Space: your edit is {edited} of {limit} bytes; "
                          f"{b.get('spare', 0)} left.{extra}")
        over = (squeezed or edited or 0) - (limit or 0)
        return "err", (f"Space: too large by {over} bytes (your edit is {edited}; "
                       f"the slot holds {limit}).")

    def _also_card(self, d):
        lay, pl = self.card_also.layout(), self.planner
        lay.addWidget(label("ALSO IN OTHER CONTAINERS", "muted"))
        w = pl.where.get(d.key)
        if w is None or w.status == "busy":
            lay.addWidget(label("Looking for other containers that carry this script…\n"
                                + pl.where_note(), "muted", True))
        elif w.status == "error":
            lay.addWidget(label(w.message, "err", True))
        elif not w.copies:
            lay.addWidget(label("This script is only in this container.", "muted", True))
        else:
            lay.addWidget(label("An edit only takes effect in the containers you ship it to.",
                                "muted", True))
            tree = QTreeWidget()
            tree.setHeaderHidden(True)
            tree.setRootIsDecorated(False)
            for c in w.copies:
                it = QTreeWidgetItem([Path(c.path).name + ("" if not c.reason
                                                          else f"   ({c.reason})")])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if c.checked else Qt.Unchecked)
                if not c.identical:
                    it.setToolTip(0, "This container has a different version of the script.")
                it.setData(0, Qt.UserRole, c.path)
                tree.addTopLevelItem(it)
            tree.itemChanged.connect(lambda it, _c, w=w: self._also_toggled(w, it))
            tree.setMinimumHeight(90)
            lay.addWidget(tree, 1)
            n = sum(1 for c in w.copies if c.checked)
            lay.addWidget(label(f"{n} of {len(w.copies)} ticked.", "muted"))
        lay.addStretch(1)

    def _also_toggled(self, w, it):
        for c in w.copies:
            if c.path == it.data(0, Qt.UserRole):
                c.checked = it.checkState(0) == Qt.Checked
        self._update_bar()

    def _checks_card(self, d):
        lay, pl = self.card_checks.layout(), self.planner
        lay.addWidget(label("VALUE CHECKS" if d.game == "pip" else "CHECKS", "muted"))
        if d.game != "pip":
            lay.addWidget(label("Naughty Bear scripts are checked by recompiling them "
                                "(above). Value warnings are for Panic in Paradise only.",
                                "muted", True))
            lay.addStretch(1)
            return
        ws = pl.warnings_for(d)
        if ws:
            for w in ws:
                lay.addWidget(label(f"! Line {w.get('line')}: {w.get('message')}", "warn", True))
                b = QPushButton(f"Go to line {w.get('line')}")
                b.clicked.connect(lambda _=False, ln=w.get("line"):
                                  self.ctx.window.open_script(d.lu, d.index, ln))
                lay.addWidget(b)
        else:
            lay.addWidget(label("✓ No unusual values found.", "ok", True))
        st = pl.schema_state
        if st in ("missing", "unknown"):
            lay.addWidget(label("These checks only know this script's values. Build "
                                "them from every retail script (about 4 minutes) to "
                                "catch more.", "muted", True))
            b = QPushButton("Build the value checks now")
            b.clicked.connect(self.ctx.window.build_schema)
            lay.addWidget(b)
        elif st == "building":
            bar = QProgressBar()
            bar.setRange(0, 0)
            lay.addWidget(bar)
            lay.addWidget(label("Building value checks… " + pl.schema_msg, "muted", True))
            b = QPushButton("Cancel")
            b.clicked.connect(pl.cancel_schema)
            lay.addWidget(b)
        elif st == "error":
            lay.addWidget(label(pl.schema_msg, "err", True))
        lay.addStretch(1)

    # ------------------------------------------------------------ ship bar
    def blockers(self):
        """(reasons Ship is off, forceable) for the checked drafts."""
        pl = self.planner
        drafts = pl.checked()
        if not drafts:
            return ["Tick at least one change."], False
        reasons, forceable = [], True
        for lu in {d.lu for d in drafts}:
            pv = pl.previews.get(lu)
            if pv is None or pv.status == "busy":
                reasons.append("Checking what Ship will do…")
                forceable = False
                continue
            for _key, err in pv.errors:
                text, can = backend.friendly(err, "pip" if any(
                    d.game == "pip" for d in drafts if d.lu == lu) else "nb1")
                reasons.append(text if not err.get("line") else f"Line {err['line']}: {text}")
                forceable = forceable and can
            if pv.status == "error" and not pv.errors:
                reasons.append(pv.message)
                forceable = False
        for d in drafts:
            b = pl.budget_for(d)
            if b and not b.get("fits"):
                reasons.append(self._budget_text(b)[1])
                forceable = False
        return reasons, forceable and bool(reasons)

    def _update_bar(self):
        pl = self.planner
        drafts = pl.checked()
        reasons, forceable = self.blockers()
        sig = pl.warning_signature()
        need_ack = bool(sig) and not reasons and pl.acked != sig
        if not hasattr(self, "ack_box"):
            self.ack_box = QCheckBox("I have read the warnings")
            self.ack_box.toggled.connect(self._acked)
            self.bar.layout().insertWidget(1, self.ack_box)
        self.ack_box.setVisible(bool(sig))
        self.ack_box.blockSignals(True)
        self.ack_box.setChecked(pl.acked == sig and bool(sig))
        self.ack_box.blockSignals(False)
        can = not reasons and not need_ack and bool(drafts)
        for b in (self.ship_btn, self.launch_btn):
            b.setEnabled(can)
        self.patch_btn.setEnabled(bool(drafts))
        self.force_btn.setVisible(bool(reasons) and forceable)
        if drafts:
            plan = backend.plan_output(self.ctx.project, self.ctx.settings, drafts[0].lu)
            note = plan.note
        else:
            note = ""
        if reasons:
            note = "Ship is off: " + reasons[0]
        elif need_ack:
            note = "Tick 'I have read the warnings' to ship. " + note
        self.note.setText(note)

    def _acked(self, on):
        self.planner.acked = self.planner.warning_signature() if on else None
        self._update_bar()

    # ------------------------------------------------------------ patch
    def patch_entries(self):
        """([(container, record index, edited .lua)], scripts still looking for copies):
        every ticked draft, plus the containers ticked in its 'also in' list (identical
        copies, each with its own record index)."""
        pl, work = self.planner, self.ctx.scratch_dir()
        entries, waiting = [], 0
        for n, d in enumerate(pl.checked()):
            src = work / f"patch_{n}_{d.index}.lua"
            src.write_text(d.text, encoding="utf-8")
            entries.append((d.lu, d.index, src))
            w = pl.where.get(d.key)
            if w is None or w.status == "busy":
                waiting += 1
                continue
            entries += [(c.path, c.index, src) for c in w.copies
                        if c.checked and c.index is not None]
        return entries, waiting

    def make_patch(self):
        """Save the ticked changes as a .srpatch. Nothing is shipped."""
        entries, waiting = self.patch_entries()
        if not entries:
            self.ctx.banner.show_message("Tick at least one change to put in a patch.", "warn")
            return
        files = {shipping.norm(lu) for lu, _i, _s in entries}
        summary = f"This one has {len(entries)} script(s) in {len(files)} file(s)."
        note = (f"Still finding the other files that have {waiting} of these scripts. "
                "Cancel and try again in a moment to include them." if waiting else "")
        dlg = PatchDialog(self, self.ctx.settings, summary, note)
        if dlg.exec() == QDialog.Accepted:
            self.start_patch(entries, dlg.meta(), dlg.out())

    def start_patch(self, entries, meta, out):
        ctx = self.ctx
        ctx.settings["patch_dir"] = str(Path(out).parent)
        ctx.settings["patch_author"] = meta.get("author", "")
        ctx.save_settings()
        ctx.banner.hide()
        ctx.runner.run(backend.patch_make_argv(ctx.settings, out, meta, entries), cwd=APPDIR,
                       title=f"Making patch {meta['name']}",
                       on_done=lambda c, o, e: self._patch_made(out, c, o, e))

    def _patch_made(self, out, code, o, e):
        ctx = self.ctx
        if code == -1:
            ctx.banner.show_message("Cancelled. No patch was written.", "warn")
            return
        try:
            if code != 0:
                raise ValueError(backend.patch_error(e, o))
            summary = backend.patch_summary(backend.patch_manifest(out), Path(out).stat().st_size)
        except Exception as ex:
            ctx.banner.show_message(f"The patch was not saved: {ex}", "err")
            return
        ctx.banner.show_message(
            f"Saved {out}. {summary}. Nothing was shipped.", "ok",
            [("Show in Patches", lambda: (ctx.window.select_rail(3),
                                          ctx.window.patches.open_patch(str(out)))),
             ("Open folder", lambda: QDesktopServices.openUrl(
                 QUrl.fromLocalFile(str(Path(out).parent))))])

    # ------------------------------------------------------------ shipping
    def ship(self, launch, force=False):
        if force:
            reasons, _f = self.blockers()
            ok = QMessageBox.warning(
                self, "Ship anyway?",
                "The checks objected:\n\n- " + "\n- ".join(reasons[:4]) +
                "\n\nThis can break the script, and in Panic in Paradise it can hang the "
                "game at boot. Your original is backed up first.\n\nShip anyway?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if ok != QMessageBox.Yes:
                return
        if not self.planner.groups():
            self.ctx.banner.show_message("Tick at least one change to ship.", "warn")
            return
        if launch and not self.ctx.window.launch_ready():
            return
        self.ctx.banner.hide()
        self.ctx.window.set_busy_ship(True)
        self.planner.ship(force, lambda results: self._finished(results, launch, force))

    def _finished(self, results, launch, force):
        ctx = self.ctx
        ctx.window.set_busy_ship(False)
        if not results:
            return
        last = results[-1]
        if not last["ok"]:
            return self._failed(last, launch, force)
        shipped, skipped, backups = [], [], 0
        for r in results:
            for t in (r["data"] or {}).get("targets", []):
                if t.get("status") == "shipped":
                    shipped.append(t)
                    backups += len(t.get("backups", []))
                elif t.get("status") == "refused":
                    skipped.append(f"{Path(t['container']).name}: {t.get('reason', 'refused')}")
        n = sum(len(r["drafts"]) for r in results)
        in_place = last["plan"].in_place
        paths = [t.get("out") or t["container"] for t in shipped]
        if in_place:
            for r in results:
                for d in r["drafts"]:
                    ctx.changes.discard(d.key)
        ctx.window.after_ship(paths, in_place)
        text = f"Shipped {n} script(s) into {len(shipped)} container(s). "
        text += (f"Originals backed up ({backups} file(s))." if backups else
                 "No backup was needed." if in_place else "")
        if not in_place:
            text += f" Written to {last['plan'].out.parent}. Your game folder is not changed."
        notes = [n for r in results for n in r.get("notes", [])]
        if notes:
            text += f" Note, line {notes[0]['line']}: {notes[0]['message']}"
        if skipped:
            text += " Skipped: " + "; ".join(skipped[:3]) + ("…" if len(skipped) > 3 else "") + "."
        actions = [("Open History", lambda: ctx.window.select_rail(4))]
        if in_place and backups:
            actions.append(("Undo", lambda p=paths: self.undo(p)))
        else:
            actions.append(("Open folder", lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(last["plan"].out.parent)))))
        kind = "warn" if skipped or notes else "ok"
        if launch:
            return self._install_and_launch(paths, text, kind, actions)
        ctx.banner.show_message(text, kind, actions)

    def _install_and_launch(self, paths, text, kind, actions):
        """Copy exactly what was shipped into the build (originals backed up), then start
        the game. The copy runs off the GUI thread."""
        ctx = self.ctx
        ctx.window.set_busy_ship(True)
        ctx.banner.show_message(text + " Installing into the game build…", kind, actions)
        w = self._install_worker = Worker(
            lambda _p: backend.install_shipped(ctx.settings, paths), self)
        w.done.connect(lambda res, exc: self._installed(res, exc, text, kind, actions))
        w.start()

    def _installed(self, res, exc, text, kind, actions):
        ctx = self.ctx
        ctx.window.set_busy_ship(False)
        if exc is not None:
            ctx.banner.show_message(f"{text} The game was not started: could not install "
                                    f"into the build: {exc}", "err", actions)
            return
        rows, in_place = res["installed"], res["in_place"]
        copied = [r["file"] for r in rows if r["changed"]]
        if copied:
            text += " Installed in the build: " + ", ".join(copied) + "."
        if in_place:
            text += (" Already in the build's game folder, so not copied: "
                     + ", ".join(in_place) + ".")
        if not copied and not in_place:
            text += " The build already had these files."
        try:
            got = backend.launch(ctx.project, ctx.settings)
        except Exception as e:
            ctx.banner.show_message(f"{text} The game did not start: {e}", "err", actions)
            return
        ctx.log.stamp(f"started restuff.exe (process {got['pid']})")
        ctx.banner.show_message(f"{text} Started the game. {got['hint']}", kind, actions)

    def _failed(self, last, launch, force):
        ctx = self.ctx
        errs = last["errors"] or [{"file": "", "line": 0, "kind": "error",
                                   "message": "The ship failed. See the log for why."}]
        e = errs[0]
        d = self.planner.draft_for_file(e.get("file", ""), last["drafts"]) if e.get("file") \
            else None
        if d is None and len(last["drafts"]) == 1:
            d = last["drafts"][0]
        text, can_force = backend.friendly(e, d.game if d else None)
        line = e.get("line") or 0
        msg = f"Ship stopped" + (f" at {d.name}" if d else "") + \
              (f", line {line}" if line else "") + f": {text}"
        actions = []
        if can_force and not force:
            actions.append(("Ship anyway…", lambda: self.ship(launch, force=True)))
        ctx.banner.show_message(msg, "err", actions, tag="script-error")
        if d is not None and line:
            ctx.window.report_script_errors(d, [(line, e.get("message", ""))])

    def undo(self, paths):
        ctx = self.ctx
        done = 0
        for p in paths:
            try:
                backend.restore_previous(p)
                done += 1
            except Exception as ex:
                ctx.banner.show_message(f"Could not undo {Path(p).name}: {ex}", "err")
                return
        ctx.window.after_ship(paths, True)
        ctx.banner.show_message(f"Undone: {done} container(s) put back as they were before "
                                "that ship.", "ok")
