"""Script editor: line numbers, Lua highlighting, error and edit marks, find bar."""
import re

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QPainter, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTextEdit, QToolButton, QWidget)

from . import style
from .luahelp import changed_lines
from .widgets import mono_font

KEYWORDS = ("and break do else elseif end false for function if in local nil not "
            "or repeat return then true until while").split()


class LuaHighlighter(QSyntaxHighlighter):
    """Colours Lua source with the active theme (call `refresh()` on a theme change)."""

    def __init__(self, doc):
        super().__init__(doc)
        self.refresh(rehighlight=False)

    def refresh(self, rehighlight=True):
        c = style.colors()

        def fmt(key, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(c[key]))
            if bold:
                f.setFontWeight(700)
            f.setFontItalic(italic)
            return f
        self.f_kw, self.f_str, self.f_num = fmt("kw"), fmt("str"), fmt("num")
        self.f_com, self.f_hash = fmt("com", italic=True), fmt("hash", bold=True)
        self.rules = [
            (re.compile(r"\b(?:%s)\b" % "|".join(KEYWORDS)), self.f_kw),
            (re.compile(r"\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b"), self.f_num),
            (re.compile(r"\bHASH\s*\(\s*(?:\"[^\"]*\"|'[^']*')\s*\)"), self.f_hash),
            (re.compile(r"\b0x[0-9a-fA-F]{8}\b"), self.f_hash),
        ]
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text):
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        # strings, then comments on top (a `--` inside a string is not a comment)
        i, n = 0, len(text)
        state = self.previousBlockState()
        if state == 1:                                  # inside --[[ ... ]]
            j = text.find("]]")
            if j < 0:
                self.setFormat(0, n, self.f_com)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, j + 2, self.f_com)
            i = j + 2
        self.setCurrentBlockState(0)
        while i < n:
            ch = text[i]
            if ch in "\"'":
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self.f_str)
                i = j + 1
            elif text.startswith("--", i):
                if text.startswith("--[[", i):
                    j = text.find("]]", i + 4)
                    if j < 0:
                        self.setFormat(i, n - i, self.f_com)
                        self.setCurrentBlockState(1)
                        return
                    self.setFormat(i, j + 2 - i, self.f_com)
                    i = j + 2
                else:
                    self.setFormat(i, n - i, self.f_com)
                    # a `--[[HASH:"x"]]0x...` annotation keeps its number tinted
                    return
            else:
                i += 1


class _Gutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with a line-number gutter, error lines and edited-line marks."""
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.setFont(mono_font(10))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 2)
        self.gutter = _Gutter(self)
        self.errors = {}                    # line -> message
        self.marked = set()                 # lines that differ from the original
        self.baseline = ""
        self.highlighter = LuaHighlighter(self.document())
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._extra)
        self._mark_timer = QTimer(self)
        self._mark_timer.setSingleShot(True)
        self._mark_timer.setInterval(300)
        self._mark_timer.timeout.connect(self._recompute_marks)
        self.textChanged.connect(self._mark_timer.start)
        self.textChanged.connect(self.edited)
        style.notifier.changed.connect(self.restyle)
        self._update_gutter_width()
        self.restyle()

    def restyle(self):
        c = style.colors()
        self.setStyleSheet(f"QPlainTextEdit {{ background: {c['code_bg']}; "
                           f"color: {c['code_text']}; border: none; "
                           f"selection-background-color: {c['sel']}; "
                           f"selection-color: {c['sel_text']}; }}")
        self.highlighter.refresh()
        self.gutter.update()
        self._extra()

    # -- content ----------------------------------------------------------------
    def set_script(self, text, baseline=None):
        """Load a script; `baseline` is the original text edits are marked against."""
        self.baseline = text if baseline is None else baseline
        self.errors = {}
        self.setPlainText(text)
        self.document().clearUndoRedoStacks()
        self._recompute_marks()

    def _recompute_marks(self):
        self.marked = changed_lines(self.baseline, self.toPlainText())
        self.gutter.update()
        self._extra()

    def set_errors(self, errors):
        """errors: {line: message}"""
        self.errors = dict(errors)
        self.gutter.update()
        self._extra()

    def goto_line(self, line):
        block = self.document().findBlockByNumber(max(0, line - 1))
        cur = QTextCursor(block)
        self.setTextCursor(cur)
        self.centerCursor()
        self.setFocus()

    # -- gutter -------------------------------------------------------------------
    def gutter_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        c = style.colors()
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(c["gutter"]))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        w = self.gutter.width()
        p.setFont(self.font())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = num + 1
                h = self.fontMetrics().height()
                if line in self.errors:
                    p.fillRect(0, top, 3, h, QColor(c["err"]))
                    p.setPen(QColor(c["err"]))
                elif line in self.marked:
                    p.fillRect(0, top, 3, h, QColor(c["edit"]))
                    p.setPen(QColor(c["gutter_text"]))
                else:
                    p.setPen(QColor(c["gutter_text"]))
                p.drawText(0, top, w - 6, h, Qt.AlignRight, str(line))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    # -- current line / error background ---------------------------------------
    def _extra(self):
        sels = []
        c = style.colors()
        for line in self.errors:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(QColor(style.tint("err", "code_bg")))
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(block)
                sels.append(s)
        s = QTextEdit.ExtraSelection()
        s.format.setBackground(QColor(style.tint("edit", "code_bg")))
        s.format.setProperty(QTextFormat.FullWidthSelection, True)
        s.cursor = self.textCursor()
        s.cursor.clearSelection()
        sels.append(s)
        self.setExtraSelections(sels)

    def error_at(self, line):
        return self.errors.get(line)


class FindBar(QWidget):
    """Find / replace under an editor (Ctrl+F)."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find")
        self.repl = QLineEdit()
        self.repl.setPlaceholderText("Replace with")
        self.regex = QCheckBox("Regex")
        self.case = QCheckBox("Match case")
        self.status = QLabel("")
        self.status.setObjectName("muted")
        b_next, b_prev = QPushButton("Next"), QPushButton("Previous")
        b_rep, b_all = QPushButton("Replace"), QPushButton("Replace all")
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        for w in (self.find, self.repl, b_next, b_prev, b_rep, b_all,
                  self.regex, self.case, self.status):
            h.addWidget(w)
        h.addStretch(1)
        h.addWidget(close)
        b_next.clicked.connect(lambda: self.step(False))
        b_prev.clicked.connect(lambda: self.step(True))
        b_rep.clicked.connect(self.replace_one)
        b_all.clicked.connect(self.replace_all)
        close.clicked.connect(self.hide)
        self.find.returnPressed.connect(lambda: self.step(False))
        self.find.textChanged.connect(lambda *_: self.status.setText(""))
        self.hide()

    def open(self):
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find.setText(sel)
        self.show()
        self.find.setFocus()
        self.find.selectAll()

    def _pattern(self):
        text = self.find.text()
        if not self.regex.isChecked():
            text = QRegularExpression.escape(text)
        opts = (QRegularExpression.NoPatternOption if self.case.isChecked()
                else QRegularExpression.CaseInsensitiveOption)
        rx = QRegularExpression(text, opts)
        return rx if rx.isValid() and self.find.text() else None

    def step(self, backward):
        rx = self._pattern()
        if rx is None:
            self.status.setText("No pattern" if not self.find.text() else "Bad regex")
            return False
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlag(0)
        cur = self.editor.document().find(rx, self.editor.textCursor(), flags)
        if cur.isNull():                                   # wrap around
            start = QTextCursor(self.editor.document())
            if backward:
                start.movePosition(QTextCursor.End)
            cur = self.editor.document().find(rx, start, flags)
        if cur.isNull():
            self.status.setText("Not found")
            return False
        self.editor.setTextCursor(cur)
        self.status.setText("")
        return True

    def replace_one(self):
        rx = self._pattern()
        cur = self.editor.textCursor()
        if rx is not None and cur.hasSelection() and rx.match(cur.selectedText()).hasMatch():
            cur.insertText(self._expand(rx, cur.selectedText()))
        self.step(False)

    def _expand(self, rx, matched):
        if not self.regex.isChecked():
            return self.repl.text()
        m = rx.match(matched)
        out = self.repl.text()
        for i in range(m.lastCapturedIndex(), 0, -1):
            out = out.replace("\\%d" % i, m.captured(i))
        return out

    def replace_all(self):
        rx = self._pattern()
        if rx is None:
            self.status.setText("No pattern")
            return
        doc = self.editor.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        n, pos = 0, QTextCursor(doc)
        while True:
            found = doc.find(rx, pos)
            if found.isNull() or not found.hasSelection():
                break
            found.insertText(self._expand(rx, found.selectedText()))
            pos = found
            n += 1
        cur.endEditBlock()
        self.status.setText(f"{n} replaced")
