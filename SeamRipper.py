#!/usr/bin/env python3
r"""Seam Ripper: GUI front-end for the Naughty Bear modding toolkit."""
import sys

from sr_gui.paths import BUNDLE, FROZEN

# --------------------------------------------------------------- frozen shim
# When packaged with PyInstaller there is no system python to shell out to.
# Instead the GUI relaunches its own EXE as  SeamRipper.exe --tool <script> ...
# and this shim (which must run BEFORE the Qt import, so tool subprocesses
# never pay the GUI's startup cost) executes the bundled script in-process.
if FROZEN and len(sys.argv) >= 3 and sys.argv[1] == "--tool":
    # PyInstaller can't runpy.run_path a bundled .py as __main__ (the archive
    # has no __main__ for it), so import the tool module and call its main().
    from pathlib import Path
    stem = Path(sys.argv[2]).stem                  # no path escapes
    sys.argv = [stem] + sys.argv[3:]
    sys.path.insert(0, str(BUNDLE))
    try:
        import importlib
        mod = importlib.import_module(stem)
        if hasattr(mod, "main"):
            mod.main()
        else:
            # fallback: exec the source with __name__ == "__main__"
            src = (BUNDLE / f"{stem}.py").read_text(encoding="utf-8")
            g = {"__name__": "__main__", "__file__": str(BUNDLE / f"{stem}.py")}
            exec(compile(src, str(BUNDLE / f"{stem}.py"), "exec"), g)
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)

from PySide6.QtWidgets import QApplication

from sr_gui.mainwindow import Main


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Seam Ripper")
    w = Main()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
