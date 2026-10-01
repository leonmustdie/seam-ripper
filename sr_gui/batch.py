"""Batch edit dialog: change every call that matches a highlighted example."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout)


class BatchDialog(QDialog):
    """Select-and-mark editor. Given the full chunk source and one highlighted
    example call, split the call into slots, let the user tag each slot
    anchor/target/ignore and attach a scale/set/offset transform to targets,
    preview the matches, and apply."""

    def __init__(self, src, example_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch edit matching calls")
        self.src = src
        self.result_text = None
        self.summary = ""
        import lua_callsplit as cs
        import lua_batchedit as be
        self.cs = cs; self.be = be

        calls = cs.find_calls(example_text, self._guess_func(example_text))
        if not calls:
            QMessageBox.warning(self, "No call found",
                                "Couldn't parse a call out of the selection.")
            self.reject(); return
        self.func = calls[0].func
        self.pattern = be.build_pattern(example_text, calls[0])

        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Function: <b>{self.func}</b> — "
                           f"{self.pattern.arity} argument slot(s)"))

        self.uniform = QCheckBox("uniform: one transform for all target slots")
        self.uniform.setChecked(True)
        self.uniform.stateChanged.connect(self._sync_uniform)
        v.addWidget(self.uniform)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>#</b>"), 0, 0)
        grid.addWidget(QLabel("<b>example</b>"), 0, 1)
        grid.addWidget(QLabel("<b>role</b>"), 0, 2)
        grid.addWidget(QLabel("<b>op</b>"), 0, 3)
        grid.addWidget(QLabel("<b>value</b>"), 0, 4)
        self.rows = []
        for i, slot in enumerate(self.pattern.slots):
            r = i + 1
            grid.addWidget(QLabel(str(i)), r, 0)
            grid.addWidget(QLabel(slot.anchor_value), r, 1)
            role = QComboBox(); role.addItems(["anchor", "target", "ignore"])
            op = QComboBox(); op.addItems(["scale", "set", "offset"])
            val = QLineEdit()
            role.currentTextChanged.connect(self._sync_uniform)
            grid.addWidget(role, r, 2); grid.addWidget(op, r, 3); grid.addWidget(val, r, 4)
            self.rows.append((role, op, val))
        v.addLayout(grid)

        self.preview = QLabel("")
        v.addWidget(self.preview)
        b_prev = QPushButton("Preview matches"); b_prev.clicked.connect(self._do_preview)
        v.addWidget(b_prev)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._apply); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._sync_uniform()

    def _guess_func(self, text):
        import re
        m = re.search(r"([\w.]+[.:])?(\w+)\s*\(", text)
        return m.group(2) if m else ""

    def _sync_uniform(self, *_):
        uni = self.uniform.isChecked()
        first_target_op = None
        for role, op, val in self.rows:
            is_target = role.currentText() == "target"
            op.setEnabled(is_target and not uni or (is_target and first_target_op is None))
            val.setEnabled(is_target)
            if is_target and uni:
                if first_target_op is None:
                    first_target_op = (op, val); op.setEnabled(True); val.setEnabled(True)
                else:
                    op.setEnabled(False); val.setEnabled(False)

    def _build_pattern(self):
        be = self.be
        uni = self.uniform.isChecked()
        uni_op = uni_val = None
        if uni:
            for role, op, val in self.rows:
                if role.currentText() == "target":
                    uni_op, uni_val = op.currentText(), val.text(); break
        for slot, (role, op, val) in zip(self.pattern.slots, self.rows):
            t = role.currentText()
            slot.tag = {"anchor": be.Tag.ANCHOR, "target": be.Tag.TARGET,
                        "ignore": be.Tag.IGNORE}[t]
            if slot.tag is be.Tag.TARGET:
                o = uni_op if uni else op.currentText()
                p = uni_val if uni else val.text()
                slot.op = {"scale": be.Op.SCALE, "set": be.Op.SET,
                           "offset": be.Op.OFFSET}[o]
                slot.param = p
        return self.pattern

    def _do_preview(self):
        pat = self._build_pattern()
        matches = self.be.find_matches(self.src, pat)
        self.preview.setText(f"{len(matches)} call(s) match.")
        return matches

    def _apply(self):
        pat = self._build_pattern()
        matches = self.be.find_matches(self.src, pat)
        if not matches:
            QMessageBox.information(self, "No matches", "No calls matched; nothing changed.")
            return
        try:
            new_src, changes = self.be.apply(self.src, pat, matches)
        except ValueError as e:
            QMessageBox.warning(self, "Transform error", str(e)); return
        self.result_text = new_src
        self.summary = f"{len(matches)} call(s), {len(changes)} value(s) changed"
        self.accept()
