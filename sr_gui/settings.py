"""Settings file, recent projects and per-project options."""
import json
import os
import sys
from pathlib import Path

from .paths import APPDIR, FROZEN, bundled

RECENT_MAX = 8


def home():
    """Writable folder for settings and drafts (SEAMRIPPER_HOME overrides it)."""
    return Path(os.environ.get("SEAMRIPPER_HOME") or APPDIR)


def settings_path():
    return home() / "seamripper_settings.json"


def load_settings():
    d = {
        "python": sys.executable,
        "luac": str(bundled("luac51.exe")),
        "jar": str(bundled("unluac.jar")),
        "stage": "",
        "last_dir": str(home()),
        "theme": "system",
        "decompiler": "auto",
        "show_commands": True,
        "recent": [],
        "projects": {},
        "restuff_build": "",
    }
    p = settings_path()
    if p.exists():
        try:
            d.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    # saved paths from another machine/install: fall back to the bundle
    for key, name in (("luac", "luac51.exe"), ("jar", "unluac.jar")):
        if not Path(d[key]).exists() and bundled(name).exists():
            d[key] = str(bundled(name))
    if FROZEN or not Path(d["python"]).exists():
        d["python"] = sys.executable
    return d


def save_settings(d):
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def add_recent(settings, folder):
    folder = str(folder)
    rec = [r for r in settings.get("recent", []) if r != folder]
    settings["recent"] = ([folder] + rec)[:RECENT_MAX]


def project_options(settings, folder):
    """Per-project settings dict (created on first use)."""
    return settings.setdefault("projects", {}).setdefault(
        str(folder), {"ship_to": ""})
