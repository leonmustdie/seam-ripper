"""Where Seam Ripper's files live, source-run or frozen."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# BUNDLE: tool scripts / luac51.exe / unluac.jar (read-only in a PyInstaller
# bundle). APPDIR: writable folder for settings, next to the EXE.
if hasattr(sys, "_MEIPASS"):
    BUNDLE = Path(sys._MEIPASS)
    APPDIR = Path(sys.executable).resolve().parent
else:
    BUNDLE = APPDIR = Path(__file__).resolve().parent.parent
TOOLS = BUNDLE if FROZEN else BUNDLE / "tools"
if not FROZEN and str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))          # the GUI imports a few tools directly


def bundled(name):
    """Path to a bundled binary (luac51.exe, unluac.jar)."""
    return TOOLS / name


def tool_argv(settings, script, *args):
    """argv to run one of the toolkit scripts, source-run or frozen. A frozen
    build relaunches its own EXE as `SeamRipper.exe --tool <script> ...`."""
    if FROZEN:
        return [sys.executable, "--tool", script, *args]
    return [settings["python"], str(TOOLS / script), *args]
