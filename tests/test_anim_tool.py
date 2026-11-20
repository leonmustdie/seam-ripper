"""The Extract animations tool: its form, the wrapper's exit codes, and (with
your own game files) a real extraction.

The form tests need PySide6 and run offscreen. The extraction tests need numpy
and read the game folders named in game_paths.py (SR_TEST_NB1_DIR,
SR_TEST_PIP_DIR); they skip when those are not set.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:                                     # pragma: no cover
    HAVE_QT = False
try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:                                     # pragma: no cover
    HAVE_NUMPY = False

import game_paths

NB1 = game_paths.NB1_DIR if (game_paths.NB1_DIR / "alienbear.lu").exists() else None
PIP = game_paths.PIP_DIR if (game_paths.PIP_DIR / "area06_npc.lu").exists() else None


def run_tool(*args, timeout=900):
    env = dict(os.environ, PYTHONHASHSEED="0")
    return subprocess.run([sys.executable, str(TOOLS / "anim_extract.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=timeout, env=env)


def glb_clips(path):
    """Animation names of a .glb."""
    b = Path(path).read_bytes()
    n = struct.unpack_from("<I", b, 12)[0]
    return [a.get("name") for a in json.loads(b[20:20 + n]).get("animations", [])]


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AnimationForm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        os.environ["SEAMRIPPER_HOME"] = cls.home.name
        cls.app = QApplication.instance() or QApplication([])
        from sr_gui import mainwindow, toolspecs
        cls.mw, cls.specs = mainwindow, toolspecs

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SEAMRIPPER_HOME", None)
        cls.home.cleanup()

    def form(self):
        from sr_gui.widgets import ToolForm
        w = self.mw.Main()
        self.addCleanup(w.close)
        f = ToolForm(self.specs.find("Extract animations"), w.ctx)
        f.show()
        self.addCleanup(f.close)
        f.widgets[".lu files or folder"][1].edit.setText("C:/in")
        f.widgets["Save into folder"][1].edit.setText("C:/out")
        return f

    def shown(self, f):
        return {n: f.form.isRowVisible(w) for n, (_s, w) in f.widgets.items()}

    def test_asks_for_what_is_missing(self):
        from sr_gui.widgets import ToolForm
        w = self.mw.Main()
        self.addCleanup(w.close)
        self.assertIsNone(ToolForm(self.specs.find("Extract animations"), w.ctx).argv())

    def test_game_choice_swaps_the_options(self):
        f = self.form()
        game = f.widgets["Game"][1]
        game.setCurrentText("Naughty Bear")
        s = self.shown(f)
        self.assertTrue(s["Don't retarget missing skeletons"])
        self.assertTrue(s["Skip skeletons with no clips"])
        self.assertFalse(s["Also export unused skeletons"])
        self.assertFalse(f.extra[0][1].isVisibleTo(f))              # no plan preview for NB1
        game.setCurrentText("Panic in Paradise")
        s = self.shown(f)
        self.assertFalse(s["Don't retarget missing skeletons"])
        self.assertFalse(s["Skip skeletons with no clips"])
        self.assertTrue(s["Also export unused skeletons"])
        self.assertTrue(f.extra[0][1].isVisibleTo(f))

    def test_command_line_per_game(self):
        f = self.form()
        game = f.widgets["Game"][1]
        game.setCurrentText("Naughty Bear")
        f.widgets["Don't retarget missing skeletons"][1].setChecked(True)
        f.widgets["Also export unused skeletons"][1].setChecked(True)    # hidden: must not leak
        a = f.argv()
        self.assertEqual(a[2:], ["C:/in", "--game", "nb1", "-o", "C:/out", "--rate", "30",
                                 "--no-retarget"])
        game.setCurrentText("Panic in Paradise")
        a = f.argv()
        self.assertIn("pip", a)
        self.assertIn("--all-rigs", a)
        self.assertNotIn("--no-retarget", a)                         # hidden for PiP
        self.assertEqual(f.argv(["--plan"])[-1], "--plan")

    def test_tab_beside_models_and_sound(self):
        w = self.mw.Main()
        self.addCleanup(w.close)
        names = [n.replace("&&", "&") for n, _ in w.container.pages] if hasattr(w, "container") else None
        if names is None:
            from sr_gui.views import ContainerView
            names = [n.replace("&&", "&") for n, _ in ContainerView(w.ctx).pages]
        self.assertEqual(names[names.index("Models & sound") + 1], "Animations")

    def test_windows_path_survives(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        f = self.form()
        f.widgets[".lu files or folder"][1].edit.setText(str(Path(d)))   # backslashes on Windows
        self.assertEqual(f.argv()[2], str(Path(d)))

    def test_wrapper_is_bundled(self):
        text = (ROOT / "seamripper.spec").read_text(encoding="utf-8")
        for name in ("anim_extract.py", "lu_anim2.py", "lu_corpus.py", "pip_corpus.py",
                     "pip_names.py", "nb1_anim_vocab.txt", "nb1_anim_sources.tsv"):
            self.assertIn(f'"{name}"', text, name)
            self.assertTrue((TOOLS / name).exists(), name)


class NeedsReport(unittest.TestCase):
    """Which other containers would add clips. Synthetic index: no game files."""

    def idx(self):
        return {
            # rig R has its own clips in a.lu; foreign F (no skeleton anywhere) retargets
            # onto R through a table in a.lu and has clips in b.lu (x2) and c.lu (x1, same as b's)
            "map": {("R", "F"): {"a"}},
            "skel": {"R": ("r", {"a"})},
            "clips": {"R": {"a": frozenset({"1", "2"})},
                      "F": {"b": frozenset({"x", "y"}), "c": frozenset({"x"})}},
        }

    def test_reachable_counts_only_what_loads(self):
        sys.path.insert(0, str(TOOLS))
        import anim_extract as A
        i = self.idx()
        self.assertEqual(len(A.reachable(i, "R", frozenset({"a"}))), 2)
        self.assertEqual(len(A.reachable(i, "R", frozenset({"a", "b"}))), 4)
        self.assertEqual(len(A.reachable(i, "R", frozenset({"a", "b", "c"}))), 4)   # c adds nothing new
        self.assertEqual(len(A.reachable(i, "R", frozenset({"b"}))), 0)             # no retarget table

    def test_present_skeleton_is_not_retargeted(self):
        sys.path.insert(0, str(TOOLS))
        import anim_extract as A
        i = self.idx()
        i["skel"]["F"] = ("f", {"b"})              # F's own skeleton is loaded with b
        self.assertEqual(len(A.reachable(i, "R", frozenset({"a", "b"}))), 2)

    def test_index_is_bundled_and_loads(self):
        sys.path.insert(0, str(TOOLS))
        import anim_extract as A
        idx = A.load_sources_index()
        self.assertIsNotNone(idx)
        self.assertTrue(idx["clips"] and idx["map"] and idx["skel"])


class Wrapper(unittest.TestCase):
    def test_missing_folder_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_tool(Path(d) / "nope", "--game", "nb1", "-o", Path(d) / "out", timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a folder", r.stdout)

    def test_folder_without_containers_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_tool(d, "--game", "pip", "-o", Path(d) / "out", timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no .lu files", r.stdout)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class RealExtraction(unittest.TestCase):
    @unittest.skipUnless(NB1, "SR_TEST_NB1_DIR not set")
    def test_naughty_bear_bakes_clips(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            for n in ("alienbear.lu", "admiralhat.lu"):
                if (NB1 / n).exists():
                    (Path(src) / n).write_bytes((NB1 / n).read_bytes())
            r = run_tool(src, "--game", "nb1", "-o", out)
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            glbs = list((Path(out) / "animations").glob("alienbear_rig_*.glb"))
            self.assertEqual(len(glbs), 1)
            self.assertGreater(len(glb_clips(glbs[0])), 50)
            r2 = run_tool(src, "--game", "nb1", "-o", out)              # re-run skips decoding
            self.assertIn("skipped=2", r2.stdout)
            self.assertTrue((Path(out) / "animations" / "needs.txt").exists())

    @unittest.skipUnless(NB1, "SR_TEST_NB1_DIR not set")
    def test_single_container(self):
        with tempfile.TemporaryDirectory() as out:
            r = run_tool(NB1 / "alienbear.lu", "--game", "nb1", "-o", out)
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            self.assertIn("decode 1 .lu", r.stdout)
            self.assertIn("characters_shared_resources.lu", r.stdout)     # the container it depends on
            glbs = list((Path(out) / "animations").glob("alienbear_rig_*.glb"))
            self.assertEqual(len(glbs), 1)

    @unittest.skipUnless(PIP, "SR_TEST_PIP_DIR not set")
    def test_panic_in_paradise_plan_names_clips(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            for n in ("area06_npc.lu", "area01_npc_3.lu", "alien01_mid.lu", "animesword.lu"):
                if (PIP / n).exists():
                    (Path(src) / n).write_bytes((PIP / n).read_bytes())
            r = run_tool(src, "--game", "pip", "--plan", "-o", out)
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            names = (Path(out) / "animations" / "clip_names.tsv").read_text(encoding="utf-8")
            self.assertIn("st_dance_01", names.lower())
            self.assertTrue(any((Path(out) / "scripts").rglob("*.lua")))


if __name__ == "__main__":
    unittest.main()
