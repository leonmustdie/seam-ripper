"""Colour themes: one dict per theme, applied app-wide (Fusion style + palette)."""

# A theme is one dict. Add a theme by adding one entry here; everything else
# (status tints, diff text, disabled colours) is derived from these keys.
#   window/panel/alt    page, input/list and rail/sidebar backgrounds
#   text/muted/line     primary text, secondary text, borders
#   accent/accent_text  buttons and focus;  sel/sel_text  selection
#   edit/warn/err/ok    status colours (edited, warning, error, success)
#   code_*, gutter*, kw/str/num/com/hash   the script editor
#   add/del             diff backgrounds
THEMES = {
    "light": {
        "label": "Light", "dark": False,
        "window": "#f6f7f9", "panel": "#ffffff", "alt": "#eceff3",
        "text": "#1c2027", "muted": "#566070", "line": "#cdd2da",
        "accent": "#2458c4", "accent_text": "#ffffff",
        "sel": "#cfe0fb", "sel_text": "#10203a",
        "edit": "#2458c4", "warn": "#8a5200", "err": "#b3261e", "ok": "#17703c",
        "code_bg": "#fbfbfc", "code_text": "#22262d",
        "gutter": "#eef0f3", "gutter_text": "#66707f",
        "kw": "#9a2f8a", "str": "#8f4510", "num": "#0e6c78",
        "com": "#66707f", "hash": "#2458c4",
        "add": "#d9f2df", "del": "#f9dcda",
    },
    "dark": {
        "label": "Dark", "dark": True,
        "window": "#1d2025", "panel": "#23272e", "alt": "#181b20",
        "text": "#e4e7ec", "muted": "#9aa2af", "line": "#383e48",
        "accent": "#5b93f0", "accent_text": "#0b1626",
        "sel": "#2c4370", "sel_text": "#f2f5fb",
        "edit": "#6ea4ff", "warn": "#e5a640", "err": "#f0716b", "ok": "#52c281",
        "code_bg": "#1a1d22", "code_text": "#d8dce3",
        "gutter": "#22262c", "gutter_text": "#8a93a1",
        "kw": "#d68bc9", "str": "#e0a26a", "num": "#6cc6d1",
        "com": "#8a93a1", "hash": "#7fb0ff",
        "add": "#1d3626", "del": "#3d2120",
    },
    "naughty": {
        "label": "Naughty (honey)", "dark": True,
        "window": "#2a211a", "panel": "#33281f", "alt": "#211a14",
        "text": "#f1e6d4", "muted": "#b8a58c", "line": "#4d3d2f",
        "accent": "#f2a71b", "accent_text": "#241706",
        "sel": "#6b4a12", "sel_text": "#fff4dc",
        "edit": "#ffbf47", "warn": "#f0a04b", "err": "#ff7f6e", "ok": "#8fcf7a",
        "code_bg": "#1f1812", "code_text": "#efe3d0",
        "gutter": "#281f18", "gutter_text": "#a8957c",
        "kw": "#f28fa8", "str": "#e8c06a", "num": "#7fd0c4",
        "com": "#a8957c", "hash": "#ffbf47",
        "add": "#27401f", "del": "#4a2320",
    },
    "paradise": {
        "label": "Paradise (tropical)", "dark": False,
        "window": "#eef6f4", "panel": "#fbfefd", "alt": "#dcece8",
        "text": "#12302c", "muted": "#456460", "line": "#b6d0ca",
        "accent": "#007c73", "accent_text": "#ffffff",
        "sel": "#bfe8e1", "sel_text": "#08302b",
        "edit": "#006a8e", "warn": "#8a4b00", "err": "#b3261e", "ok": "#17703c",
        "code_bg": "#fdfffe", "code_text": "#173733",
        "gutter": "#e4f1ee", "gutter_text": "#55736f",
        "kw": "#a12d6f", "str": "#8a4200", "num": "#00687a",
        "com": "#55736f", "hash": "#006a8e",
        "add": "#cdeedd", "del": "#f8d9d3",
    },
    "midnight": {
        "label": "Midnight (neon)", "dark": True,
        "window": "#121424", "panel": "#181b2e", "alt": "#0d0f1c",
        "text": "#e7e9f7", "muted": "#9ea3c4", "line": "#2c3052",
        "accent": "#ff3d9a", "accent_text": "#1a0410",
        "sel": "#4a1c4b", "sel_text": "#ffeaf5",
        "edit": "#4dd0ff", "warn": "#ffc247", "err": "#ff6b7d", "ok": "#5be39a",
        "code_bg": "#0f1120", "code_text": "#e0e3f5",
        "gutter": "#151830", "gutter_text": "#8b90b8",
        "kw": "#ff79c6", "str": "#f1fa8c", "num": "#8be9fd",
        "com": "#8b90b8", "hash": "#4dd0ff",
        "add": "#123b2a", "del": "#4a1a2c",
    },
    "teddy": {
        "label": "Teddy (cream)", "dark": False,
        "window": "#f7f0e4", "panel": "#fffaf1", "alt": "#ede2d0",
        "text": "#33261a", "muted": "#6b5844", "line": "#d6c6ad",
        "accent": "#a8321f", "accent_text": "#ffffff",
        "sel": "#f0d2a4", "sel_text": "#3a2508",
        "edit": "#2458c4", "warn": "#8a5200", "err": "#a8261c", "ok": "#2a6b22",
        "code_bg": "#fffcf6", "code_text": "#33261a",
        "gutter": "#f1e7d6", "gutter_text": "#75634e",
        "kw": "#8f2b7a", "str": "#8a4a12", "num": "#0f6a6a",
        "com": "#75634e", "hash": "#2458c4",
        "add": "#dbeed0", "del": "#f6d8cf",
    },
}
SYSTEM = "system"
DEFAULT_LIGHT, DEFAULT_DARK = "light", "dark"


def theme_choices():
    """[(key, label)] in menu order, System first."""
    return [(SYSTEM, "System (follow Windows)")] + [
        (k, t["label"]) for k, t in THEMES.items()]


def resolve(name, system_is_dark):
    """Theme key to use for `name` ('system' follows the OS scheme)."""
    if name == SYSTEM or name not in THEMES:
        return DEFAULT_DARK if system_is_dark else DEFAULT_LIGHT
    return name


# ------------------------------------------------------------------ colour maths
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """Colour t of the way from a to b (hex in, hex out)."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def luminance(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio, 1..21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tint(t, key, over="window"):
    """Background tint for a status colour (message boxes, error lines)."""
    return mix(t[over], t[key], 0.16)


def check(t):
    """Contrast problems for a theme as [(what, ratio, needed)]; empty when fine."""
    rules = [
        ("text on window", t["text"], t["window"], 4.5),
        ("text on panel", t["text"], t["panel"], 4.5),
        ("text on rail", t["text"], t["alt"], 4.5),
        ("muted on window", t["muted"], t["window"], 4.5),
        ("muted on panel", t["muted"], t["panel"], 4.5),
        ("muted on rail", t["muted"], t["alt"], 4.5),
        ("button text on accent", t["accent_text"], t["accent"], 4.5),
        ("accent on window", t["accent"], t["window"], 3.0),
        ("selected text", t["sel_text"], t["sel"], 4.5),
        ("code text", t["code_text"], t["code_bg"], 7.0),
        ("line numbers", t["gutter_text"], t["gutter"], 3.5),
        ("comments", t["com"], t["code_bg"], 3.5),
        ("code text on selection", t["code_text"], t["sel"], 3.0),
    ]
    for k in ("kw", "str", "num", "hash"):
        rules.append((f"{k} colour", t[k], t["code_bg"], 4.5))
        for d in ("add", "del"):
            rules.append((f"{k} colour on diff {d}", t[k], t[d], 3.5))
    for d in ("add", "del"):
        rules.append((f"code text on diff {d}", t["code_text"], t[d], 4.5))
        rules.append((f"line numbers on diff {d}", t["gutter_text"], t[d], 3.0))
    for k in ("edit", "warn", "err", "ok"):
        rules.append((f"{k} colour on window", t[k], t["window"], 4.5))
        rules.append((f"{k} colour on its tint", t[k], tint(t, k), 3.0))
        rules.append((f"text on {k} tint", t["text"], tint(t, k), 4.5))
        rules.append((f"{k} colour on code", t[k], t["code_bg"], 3.0))
    rules.append(("code text on error line", t["code_text"],
                  tint(t, "err", "code_bg"), 4.5))
    rules.append(("code text on edited line", t["code_text"],
                  tint(t, "edit", "code_bg"), 4.5))
    return [(w, round(contrast(a, b), 2), need)
            for w, a, b, need in rules if contrast(a, b) < need]


# ------------------------------------------------------------------ applying (Qt)
def _stylesheet(t):
    a = t["accent"]
    return f"""
QToolTip {{ color: {t['text']}; background: {t['panel']}; border: 1px solid {t['line']}; }}
QPushButton#primary, QToolButton#primary {{
  background: {a}; color: {t['accent_text']}; border: 1px solid {a};
  border-radius: 4px; padding: 4px 12px; font-weight: 600; }}
QPushButton#primary:disabled, QToolButton#primary:disabled {{
  background: {mix(a, t['window'], .6)}; border-color: {mix(a, t['window'], .6)}; }}
QToolButton#rail {{ border: none; border-left: 3px solid transparent; border-radius: 0;
  padding: 8px 2px 6px 2px; color: {t['muted']}; background: transparent; }}
QToolButton#rail:checked {{ border-left-color: {a}; background: {t['sel']}; color: {t['sel_text']}; }}
QToolButton#rail:hover:!checked {{ background: {mix(t['alt'], t['text'], .08)}; }}
QFrame#banner {{ background: {tint(t, 'ok')}; border-bottom: 1px solid {t['line']}; }}
QFrame#banner[kind="err"] {{ background: {tint(t, 'err')}; }}
QFrame#banner[kind="warn"] {{ background: {tint(t, 'warn')}; }}
QFrame#card {{ background: {t['panel']}; border: 1px solid {t['line']}; border-radius: 6px; }}
QFrame#rail {{ background: {t['alt']}; border-right: 1px solid {t['line']}; }}
QFrame#sidebar {{ background: {t['panel']}; border-right: 1px solid {t['line']}; }}
QLabel#muted {{ color: {t['muted']}; }}
QLabel#heading {{ font-size: 15px; font-weight: 600; }}
QLabel#badge {{ background: {t['sel']}; color: {t['sel_text']}; border-radius: 8px; padding: 1px 8px; font-weight: 600; }}
QLabel#linklike {{ color: {t['edit']}; text-decoration: underline; }}
QLabel#ok {{ color: {t['ok']}; }}
QLabel#warn {{ color: {t['warn']}; }}
QLabel#err {{ color: {t['err']}; }}
QListWidget#rowlist, QTreeWidget#tree {{ border: none; background: {t['panel']}; }}
QTabBar::tab {{ padding: 5px 12px; border: 1px solid transparent; border-bottom: none; }}
QTabBar::tab:selected {{ background: {t['panel']}; border-color: {t['line']}; font-weight: 600; }}
QSplitter::handle {{ background: {t['line']}; }}
QMenu::item:selected {{ background: {t['sel']}; color: {t['sel_text']}; }}
"""


def make_palette(t):
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    for role, key in ((QPalette.Window, "window"), (QPalette.WindowText, "text"),
                      (QPalette.Base, "panel"), (QPalette.AlternateBase, "alt"),
                      (QPalette.Text, "text"), (QPalette.Button, "alt"),
                      (QPalette.ButtonText, "text"), (QPalette.ToolTipBase, "panel"),
                      (QPalette.ToolTipText, "text"), (QPalette.Highlight, "sel"),
                      (QPalette.HighlightedText, "sel_text"),
                      (QPalette.Link, "edit"), (QPalette.LinkVisited, "kw"),
                      (QPalette.PlaceholderText, "muted"), (QPalette.BrightText, "err"),
                      (QPalette.Light, "panel"), (QPalette.Mid, "line"),
                      (QPalette.Midlight, "alt"), (QPalette.Dark, "line"),
                      (QPalette.Shadow, "line")):
        p.setColor(role, QColor(t[key]))
    dim = QColor(mix(t["text"], t["window"], .55))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, dim)
    return p


def apply_theme(app, key):
    """Apply theme `key` (a THEMES key) to the whole application."""
    from PySide6.QtWidgets import QStyleFactory
    t = THEMES[key]
    if app.style().objectName().lower() != "fusion":
        app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(make_palette(t))
    app.setStyleSheet(_stylesheet(t))
