"""The current theme: apply it, look colours up, and tell widgets when it changes."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from . import themes


class _Notifier(QObject):
    changed = Signal()


notifier = _Notifier()
_state = {"choice": themes.SYSTEM, "key": themes.DEFAULT_LIGHT}


def system_is_dark():
    hints = QApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def colors():
    """The active theme's dict."""
    return themes.THEMES[_state["key"]]


def color(name):
    return colors()[name]


def tint(name, over="window"):
    return themes.tint(colors(), name, over)


def choice():
    return _state["choice"]


def set_theme(choice_name):
    """Apply a theme by menu choice ('system' or a THEMES key), live."""
    app = QApplication.instance()
    _state["choice"] = choice_name
    _state["key"] = themes.resolve(choice_name, system_is_dark())
    themes.apply_theme(app, _state["key"])
    notifier.changed.emit()


def follow_system():
    """Re-resolve 'System' when Windows switches between light and dark."""
    hints = QApplication.styleHints()
    try:
        hints.colorSchemeChanged.connect(lambda *_: (
            set_theme(_state["choice"]) if _state["choice"] == themes.SYSTEM else None))
    except AttributeError:
        pass


def dot_icon(name, size=10):
    """A small filled circle in a theme colour (edit/warn/err/ok), for lists."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color(name)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)
