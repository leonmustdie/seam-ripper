#!/usr/bin/env python3
"""Animation write-back: the clip encoder (lu_anim_encode), the swap tool
(anim_replace), multi-record container rebuilds and .srpatch "anim" edits.

The first groups build clips from scratch (both games' layouts) and need only
numpy. The rest read your own game files (SR_TEST_NB1_DIR, SR_TEST_PIP_DIR,
see game_paths.py) and skip without them. NB1 uses rosette.lu (62 KB, six
clips on two 2-bone skeletons, one bone map) so container rebuilds stay fast,
and naughtybear.lu only where no rebuild is needed; PiP uses
area07_npc_twinkles.lu (48 KB, three clips), umbrella.lu and skinnaughty.lu.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:                                     # pragma: no cover
    HAVE_NUMPY = False

import game_paths

NB1 = game_paths.NB1_DIR
HAVE_NB1 = HAVE_NUMPY and (NB1 / "rosette.lu").exists() and (NB1 / "naughtybear.lu").exists()
PIP = game_paths.PIP_DIR
HAVE_PIP = (HAVE_NUMPY and (PIP / "area07_npc_twinkles.lu").exists()
            and (PIP / "skinnaughty.lu").exists())
HAVE_LZXV = any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify"))

if HAVE_NUMPY:
    import lu_anim_encode as lae
    import anim_replace as ar
    from lu_anim2 import decode_clip, sample_channel

# rosette.lu: two clips on skeleton 7e70f016, one on 7592bdcf (the unit's own),
# and a bone map 7e70f016 -> 7592bdcf in its animation set
R_SAME, R_OWN, R_DONOR = 0xAD4FD453, 0xDEAC46B5, 0xED3F2054
WALK = (0x09CD6AB7, 0xF3C257D4)
DANCE = 0xFA28BC20                                      # st_dance_01, rig d01a231e
# PiP: area07_npc_twinkles.lu's three clips share one 8-bone skeleton;
# skinnaughty.lu holds Naughty's ST_Walk and the shared bear dances
T_TARGET, T_DONOR = 0x9549D78B, 0x0D08E6EF
P_WALK, P_DANCE, P_SHRUG, P_RUN = 0x6B9ABE46, 0x1E4BC9DC, 0x0B9E0C5A, 0x0DC1F546


def synthetic_clip():
    """A 2-bone clip: bone 0 moves x from 0 to 2 over 1 s, bone 1 has a
    static value 0.5."""
    h = bytearray(b"\xef" * 0x60)
    struct.pack_into(">2I", h, 0, lae.CLIP_TYPE, 0)
    struct.pack_into(">I", h, 8, 0x12345678)
    struct.pack_into(">f", h, 0x10, 1.0)
    struct.pack_into(">I", h, 0x14, 0x00EFEFEF)
    struct.pack_into(">2I", h, 0x18, 0xFFFFFFFF, 0xEFEFEFEF)
    struct.pack_into(">2I", h, 0x28, 0xFFFFFFFF, 0)
    struct.pack_into(">4f", h, 0x30, 0, 0, 0, 1)
    struct.pack_into(">2I", h, 0x40, 0xFFFFFFFF, 0)
    struct.pack_into(">2I", h, 0x48, 0xFFFFFFFF, 0xABCDEF01)
    h[0x50] = 0
    model = {"header": bytes(h), "markers": b"",
             "bones": [{"keyed": [lae.linear_channel(0x04, 0.0, 2.0, 1.0)],
                        "static": [{"tag": 0x00, "value": 0.5,
                                    "payload": lae.f24_encode(0.5)}]},
                       {"keyed": [], "static": []}]}
    return lae.encode_clip(model, "f32")


def synthetic_pip_clip(hashes=(0x11111111, 0x22222222), additive=0):
    """The same motion in Panic in Paradise's layout: bone-hash table,
    24-byte track entries, one tail entry {track 1, track 0}."""
    h = bytearray(b"\xef" * 0x70)
    struct.pack_into(">2I", h, 0, lae.CLIP_TYPE, 0)
    struct.pack_into(">2I", h, 8, 0x12345678, lae.CLIP_TYPE)
    struct.pack_into(">f", h, 0x10, 1.0)
    struct.pack_into(">2I", h, 0x14, 0x00EFEFEF, 0xFFFFFFFF)
    struct.pack_into(">2I", h, 0x38, 0xFFFFFFFF, 0)
    struct.pack_into(">4f", h, 0x40, 0, 0, 0, 1)
    struct.pack_into(">2I", h, 0x58, 0xFFFFFFFF, 0xABCDEF01)
    h[0x60] = additive
    h[0x61] = 0
    tail = struct.pack(">2H", 1, 0) + b"\xef" * 12
    model = {"game": "pip", "header": bytes(h), "markers": tail,
             "bone_hashes": list(hashes),
             "bones": [{"keyed": [lae.linear_channel(0x04, 0.0, 2.0, 1.0)],
                        "static": [{"tag": 0x00, "value": 0.5,
                                    "payload": lae.f24_encode(0.5)}]},
                       {"keyed": [], "static": []}]}
    return lae.encode_clip(model, "f32")


def channel(clip, bone, tag):
    return next(c for c in clip["tracks"][bone] if c["tag"] == tag)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class Encoder(unittest.TestCase):
    def test_f24_round_trips(self):
        from lu_anim2 import f24
        for x in (0.0, 0.5, -0.5, 1.0, 3.14159, -123.456, 1e-6, 2.0 ** 20):
            got = f24(lae.f24_encode(x))
            self.assertAlmostEqual(got, x, delta=abs(x) * 2 ** -16 + 1e-12, msg=x)

    def test_f24_refuses_what_it_cannot_hold(self):
        for x in (float("nan"), float("inf"), 2.0 ** 40):
            with self.assertRaises(lae.EncodeError):
                lae.f24_encode(x)

    def test_built_clip_decodes_to_what_was_written(self):
        d = synthetic_clip()
        c = decode_clip(d, Counter())
        self.assertIsNotNone(c)
        self.assertEqual(lae.header_fields(d)["bones"], 2)
        v = sample_channel(channel(c, 0, 0x04), np.array([0.0, 0.25, 0.5, 1.0]))
        np.testing.assert_allclose(v, [0.0, 0.5, 1.0, 2.0], atol=1e-6)
        self.assertAlmostEqual(lae.parse_clip(d)["bones"][0]["static"][0]["value"], 0.5,
                               places=5)

    def test_parse_then_encode_is_byte_exact(self):
        d = synthetic_clip()
        m = lae.parse_clip(d)
        self.assertEqual(lae.encode_clip(m, "raw"), d)
        self.assertEqual(lae.encode_clip(m, "f32"), d)

    def test_neutral_json_rebuilds_the_same_record(self):
        d = synthetic_clip()
        obj = json.loads(json.dumps(lae.model_to_json(lae.parse_clip(d))))
        self.assertEqual(obj["format"], "seamripper-clip")
        self.assertEqual(lae.build_clip(obj, d), d)

    def test_json_for_another_skeleton_is_refused(self):
        d = synthetic_clip()
        obj = lae.model_to_json(lae.parse_clip(d))
        bad = dict(obj, rig="00000001")
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(bad, d)
        bad = dict(obj, bone_count=3)
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(bad, d)

    def test_bad_key_times_are_refused(self):
        d = synthetic_clip()
        obj = json.loads(json.dumps(lae.model_to_json(lae.parse_clip(d))))
        pc = obj["bones"][0]["keyed"][0]["pieces"][0]
        pc["times"] = pc["times"] + [0.5]               # one more time than keys
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(obj, d)

    def test_retarget_moves_bones_by_the_map(self):
        m = lae.parse_clip(synthetic_clip())
        r = lae.retarget(m, [1, -1], 3, 0x11111111)
        self.assertEqual(len(r["bones"]), 3)
        self.assertEqual(r["bones"][1]["keyed"], m["bones"][0]["keyed"])
        self.assertEqual(r["bones"][0], {"keyed": [], "static": []})
        self.assertEqual(lae.header_fields(lae.encode_clip(r, "f32"))["rig_hash"], 0x11111111)
        with self.assertRaises(lae.EncodeError):
            lae.retarget(m, [1, 1], 3, 0x11111111)       # two bones onto one


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class PipEncoder(unittest.TestCase):
    def test_pip_clip_decodes_and_re_emits(self):
        d = synthetic_pip_clip()
        self.assertTrue(lae.is_pip(d))
        c = decode_clip(d, Counter())
        self.assertEqual(c["bone_hashes"], [0x11111111, 0x22222222])
        v = sample_channel(channel(c, 0, 0x04), np.array([0.0, 0.5, 1.0]))
        np.testing.assert_allclose(v, [0.0, 1.0, 2.0], atol=1e-6)
        m = lae.parse_clip(d)
        self.assertEqual(m["game"], "pip")
        self.assertEqual(lae.encode_clip(m, "raw"), d)
        f = lae.header_fields(d)
        self.assertEqual((f["bones"], f["rig_hash"], f["game"]), (2, 0xABCDEF01, "pip"))

    def test_pip_json_carries_its_own_bones(self):
        """A PiP clip file brings its bone list, tail table and rig id; the
        target only gives its name, and any bone list fits."""
        donor = synthetic_pip_clip((0xAAAAAAAA, 0xBBBBBBBB))
        target = synthetic_pip_clip((0x11111111, 0x22222222))
        obj = json.loads(json.dumps(lae.model_to_json(lae.parse_clip(donor))))
        self.assertEqual(obj["game"], "pip")
        self.assertEqual(lae.build_clip(obj, target), donor)   # same name, so identical

    def test_pip_and_nb1_clips_do_not_mix(self):
        pip_obj = lae.model_to_json(lae.parse_clip(synthetic_pip_clip()))
        nb1_obj = lae.model_to_json(lae.parse_clip(synthetic_clip()))
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(pip_obj, synthetic_clip())
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(nb1_obj, synthetic_pip_clip())

    def test_tail_naming_a_missing_track_is_refused(self):
        obj = lae.model_to_json(lae.parse_clip(synthetic_pip_clip()))
        obj["tail"] = (struct.pack(">2H", 5, 0) + b"\xef" * 12).hex()
        with self.assertRaises(lae.EncodeError):
            lae.build_clip(obj, synthetic_pip_clip())


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class Names(unittest.TestCase):
    NAMES = {0xF3C257D4: ("", ["st_walk", "?aa4a8f50"]),
             0x09CD6AB7: ("", ["st_walk"]),
             0xFA28BC20: ("st_dance_01", ["st_dance_01"]),
             0x1426DD0C: ("st_dance_03", ["st_dance01", "st_dance_03"])}

    def test_names_hashes_and_lists_resolve(self):
        have = set(self.NAMES)
        self.assertEqual(ar.resolve("st_walk", have, self.NAMES), [0x09CD6AB7, 0xF3C257D4])
        self.assertEqual(ar.resolve("ST_Dance_01", have, self.NAMES), [0xFA28BC20])
        self.assertEqual(ar.resolve("st_dance01", have, self.NAMES), [0x1426DD0C])
        self.assertEqual(ar.resolve("0xfa28bc20, 1426dd0c", have, self.NAMES),
                         [0xFA28BC20, 0x1426DD0C])

    def test_unknown_or_absent_clips_are_refused(self):
        with self.assertRaises(ar.SwapError):
            ar.resolve("st_fly", set(self.NAMES), self.NAMES)
        with self.assertRaises(ar.SwapError):
            ar.resolve("deadbeef", set(self.NAMES), self.NAMES)
        with self.assertRaises(ar.SwapError):
            ar.resolve("st_walk", {0xFA28BC20}, self.NAMES)

    def test_shipped_pip_name_table_reads(self):
        names = ar.load_names("pip")
        self.assertGreater(len(names), 650)
        self.assertEqual(names[P_DANCE][0], "ST_Dance_01")
        self.assertIn("skinnaughty", ar.clip_sources("pip")[P_WALK])

    def test_shipped_name_table_reads(self):
        names = ar.load_names()
        self.assertGreater(len(names), 500)
        self.assertEqual(names[0xFA28BC20][0], "st_dance_01")
        self.assertIn("st_walk", names[0xF3C257D4][1])
        self.assertIn("naughtybear", ar.clip_sources()[0xF3C257D4])


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:                                     # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class Form(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS.parent))
        cls.home = tempfile.TemporaryDirectory()
        os.environ["SEAMRIPPER_HOME"] = cls.home.name
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SEAMRIPPER_HOME", None)
        cls.home.cleanup()

    def test_replace_form_builds_the_swap_command(self):
        from sr_gui import mainwindow, toolspecs
        from sr_gui.widgets import ToolForm
        w = mainwindow.Main()
        self.addCleanup(w.close)
        f = ToolForm(toolspecs.find("Replace an animation"), w.ctx)
        self.addCleanup(f.close)
        self.assertIsNone(f.argv())                     # nothing filled in yet
        f.widgets["Container with the clip"][1].edit.setText("C:/g/lu/naughtybear.lu")
        f.widgets["Clip(s) to replace"][1].setText("st_walk")
        f.widgets["Donor .lu or lu folder"][1].edit.setText("C:/g/lu")
        f.widgets["Donor clip"][1].setText("st_dance_01")
        f.widgets["Save patch as"][1].edit.setText("C:/m/Dance.srpatch")
        a = f.argv()
        i = a.index("swap")
        self.assertTrue(a[i - 1].endswith("anim_replace.py") or "anim_replace" in " ".join(a))
        tail = a[i + 1:]
        self.assertEqual(tail[0], "C:/g/lu/naughtybear.lu")
        for flag, v in (("--clip", "st_walk"), ("--from", "C:/g/lu"),
                        ("--donor", "st_dance_01"), ("--patch", "C:/m/Dance.srpatch")):
            self.assertEqual(tail[tail.index(flag) + 1], v)
        self.assertNotIn("--replace-movement", tail)
        self.assertNotIn("-o", tail)

    def test_animation_tab_has_the_new_forms(self):
        from sr_gui import mainwindow
        from sr_gui.views import ContainerView
        w = mainwindow.Main()
        self.addCleanup(w.close)
        v = ContainerView(w.ctx)
        titles = [f.spec["title"] for f in v.anim.forms]
        self.assertEqual(titles, ["Extract animations", "List animation clips",
                                  "Replace an animation"])


@unittest.skipUnless(HAVE_NB1, "needs numpy and your NB1 files (SR_TEST_NB1_DIR)")
class RetailClips(unittest.TestCase):
    """Decode, encode, decode on real clips (the whole-corpus run is
    `lu_anim_encode.py roundtrip <lu folder>`)."""

    def clips(self, *units):
        for u in units:
            for label, d in lae._iter_clips([NB1 / u]):
                yield label, d

    def test_round_trip(self):
        import anim_roundtrip
        n = 0
        for label, d in self.clips("rosette.lu", "locker.lu", "landmine.lu"):
            r = anim_roundtrip.check_clip(d)
            self.assertEqual(r["status"], "ok", f"{label}: {r}")
            self.assertTrue(r["raw_exact"], label)
            self.assertTrue(r["json_ok"], label)
            if "sabotage_caught" in r:
                self.assertTrue(r["sabotage_caught"], label)
            n += 1
        self.assertGreater(n, 40)

    def test_walk_clips_round_trip(self):
        import anim_roundtrip
        from naughty_lu import LuFile
        lu = LuFile(NB1 / "naughtybear.lu")
        for h in WALK:
            d = bytes(lu.chunk(lae.clip_records(lu, h)[0]))
            r = anim_roundtrip.check_clip(d)
            self.assertEqual(r["status"], "ok", f"{h:08x}: {r}")
            self.assertTrue(r["raw_exact"])


@unittest.skipUnless(HAVE_NB1, "needs numpy and your NB1 files (SR_TEST_NB1_DIR)")
class Swap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from naughty_lu import LuFile
        cls.LuFile = LuFile
        cls.names = ar.load_names()

    def test_naughty_walk_takes_the_dance(self):
        """EternalDancing's walk swap (verified in game 2026-11-17)."""
        nb = self.LuFile(NB1 / "naughtybear.lu")
        src, dh = ar.find_donor(NB1, "st_dance_01", self.names)
        self.assertEqual(dh, DANCE)
        donor = bytes(src.chunk(lae.clip_records(src, dh)[0]))
        for h in WALK:
            notes = []
            obj = ar.swap_model(nb, h, donor, notes=notes)
            walk = bytes(nb.chunk(lae.clip_records(nb, h)[0]))
            new = lae.build_clip(obj, walk)
            f = lae.header_fields(new)
            self.assertEqual((f["rig_hash"], f["bones"], f["name_hash"]),
                             (0x7CA05935, 117, h))
            self.assertAlmostEqual(f["duration"], 2.3333, places=3)
            self.assertTrue(any("111 of 116" in n for n in notes), notes)
            # same forward speed as the walk it replaces
            c0, c1 = decode_clip(walk, Counter()), decode_clip(new, Counter())
            sp = []
            for c in (c0, c1):
                ch = channel(c, 0, 0x06)
                v = sample_channel(ch, np.array([0.0, c["duration"]]))
                sp.append((v[1] - v[0]) / c["duration"])
            self.assertAlmostEqual(sp[0], sp[1], places=4)
            # bone 1 onward is the dance's motion, moved by the game's map
            self.assertNotEqual(lae.sha256(new), lae.sha256(walk))

    def test_replace_movement_drops_the_walk_speed(self):
        nb = self.LuFile(NB1 / "naughtybear.lu")
        src, dh = ar.find_donor(NB1, "st_dance_01", self.names)
        donor = bytes(src.chunk(lae.clip_records(src, dh)[0]))
        obj = ar.swap_model(nb, WALK[0], donor, keep_movement=False)
        tags = [c["tag"] for c in obj["bones"][0].get("keyed", [])]
        self.assertNotIn(0x06, tags)

    def test_a_skeleton_with_no_map_is_refused(self):
        nb = self.LuFile(NB1 / "naughtybear.lu")
        ro = self.LuFile(NB1 / "rosette.lu")
        donor = bytes(ro.chunk(lae.clip_records(ro, R_DONOR)[0]))
        with self.assertRaises(ar.SwapError) as cm:
            ar.swap_model(nb, WALK[0], donor)
        self.assertIn("no bone map", str(cm.exception))

    def test_list_names_naughtys_clips(self):
        r = subprocess.run([sys.executable, str(TOOLS / "anim_replace.py"), "list",
                            str(NB1 / "naughtybear.lu"), "--find", "st_walk"],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("f3c257d4", r.stdout)
        self.assertIn("09cd6ab7", r.stdout)
        self.assertIn("2 match(es)", r.stdout)


@unittest.skipUnless(HAVE_NB1 and HAVE_LZXV, "needs numpy, lzxverify and your NB1 files")
class Rebuild(unittest.TestCase):
    """Container and patch round trips on rosette.lu (small, so fast)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        game = self.dir / "game" / "lu"
        game.mkdir(parents=True)
        shutil.copyfile(NB1 / "rosette.lu", game / "rosette.lu")   # writable copy
        self.game = game

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "anim_replace.py"), *map(str, args)],
                              capture_output=True, text=True, timeout=300)

    def test_multi_record_rebuild_changes_only_those_records(self):
        from naughty_lu import LuFile
        from lu_chunk_replace import rebuild
        lu = LuFile(self.game / "rosette.lu")
        a = lae.clip_records(lu, R_SAME)[0]
        b = lae.clip_records(lu, R_OWN)[0]
        new_a = bytes(lu.chunk(a)) + b"\xbf" * 64        # grow both
        new_b = bytes(lu.chunk(b)) + b"\xbf" * 128
        data, _how = rebuild(lu, {a.index: new_a, b.index: new_b})
        out = self.dir / "r.lu"
        out.write_bytes(data)
        back = LuFile(out)
        self.assertEqual(bytes(back.chunk(back.records[a.index])), new_a)
        self.assertEqual(bytes(back.chunk(back.records[b.index])), new_b)
        for r in lu.records:
            if r.index not in (a.index, b.index) and not r.external:
                self.assertEqual(bytes(back.chunk(back.records[r.index])),
                                 bytes(lu.chunk(r)), r.index)

    def test_swap_patch_and_lu_agree(self):
        """Same skeleton and mapped skeleton in one swap; the .srpatch
        applied elsewhere gives the same file as the direct -o."""
        import sr_patch
        lu = self.game / "rosette.lu"
        patch, out = self.dir / "Rosette.srpatch", self.dir / "out" / "rosette.lu"
        r = self.run_tool("swap", lu, "--clip", f"{R_SAME:08x},{R_OWN:08x}",
                          "--from", lu, "--donor", f"{R_DONOR:08x}",
                          "--patch", patch, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("same skeleton", r.stdout)
        self.assertIn("bone map 7e70f016 -> 7592bdcf", r.stdout)
        with zipfile.ZipFile(patch) as z:
            m = json.loads(z.read("manifest.json"))
            self.assertEqual(m["format_version"], 3)
            kinds = [e["kind"] for t in m["targets"] for e in t["edits"]]
            self.assertEqual(kinds, ["anim", "anim"])
            self.assertFalse(any(n.endswith(".lu") for n in z.namelist()))
        applied = self.dir / "applied"
        res = sr_patch.apply_patch(str(patch), str(self.game.parent), out_dir=str(applied),
                                   log=lambda *_: None)
        self.assertEqual([f["status"] for f in res["files"]], ["identical"])
        self.assertEqual((applied / "rosette.lu").read_bytes(), out.read_bytes())
        # both replaced clips now play the donor's 0.9 s
        from naughty_lu import LuFile
        back = LuFile(out)
        for h in (R_SAME, R_OWN):
            d = bytes(back.chunk(lae.clip_records(back, h)[0]))
            self.assertAlmostEqual(lae.header_fields(d)["duration"], 0.9, places=4)
            self.assertIsNotNone(decode_clip(d, Counter()))

    def test_patch_refuses_a_changed_clip(self):
        import sr_patch
        lu = self.game / "rosette.lu"
        patch = self.dir / "R.srpatch"
        r = self.run_tool("swap", lu, "--clip", f"{R_SAME:08x}", "--from", lu,
                          "--donor", f"{R_DONOR:08x}", "--patch", patch)
        self.assertEqual(r.returncode, 0, r.stderr)
        # a different rosette.lu: the target clip already replaced
        r = self.run_tool("swap", lu, "--clip", f"{R_SAME:08x}", "--from", lu,
                          "--donor", "54a09d09", "-o", lu)
        self.assertEqual(r.returncode, 0, r.stderr)
        st = sr_patch.check_targets(sr_patch.read_manifest(str(patch)), str(self.game.parent))
        self.assertEqual([s["status"] for s in st], ["mismatch"])
        with self.assertRaises(sr_patch.PatchError):
            sr_patch.apply_patch(str(patch), str(self.game.parent),
                                 out_dir=str(self.dir / "x"), log=lambda *_: None)

    def test_overwriting_a_game_file_backs_it_up_and_read_only_is_refused(self):
        import stat
        import sr_backup
        lu = self.game / "rosette.lu"
        before = lu.read_bytes()
        r = self.run_tool("swap", lu, "--clip", f"{R_SAME:08x}", "--from", lu,
                          "--donor", f"{R_DONOR:08x}", "-o", lu)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(lu.read_bytes(), before)
        self.assertEqual((sr_backup.backup_dir(self.game) / "rosette.lu").read_bytes(), before)
        os.chmod(lu, stat.S_IREAD)
        try:
            r = self.run_tool("swap", lu, "--clip", f"{R_OWN:08x}", "--from", lu,
                              "--donor", f"{R_DONOR:08x}", "-o", lu)
            self.assertEqual(r.returncode, 1)
            self.assertIn("read-only", r.stderr)
        finally:
            os.chmod(lu, stat.S_IREAD | stat.S_IWRITE)

    def test_nothing_to_save_is_an_error(self):
        lu = self.game / "rosette.lu"
        r = self.run_tool("swap", lu, "--clip", f"{R_SAME:08x}", "--from", lu,
                          "--donor", f"{R_DONOR:08x}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("say where to save", r.stderr)


@unittest.skipUnless(HAVE_PIP, "needs numpy and your PiP files (SR_TEST_PIP_DIR)")
class Pip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.game = self.dir / "game" / "lu"
        self.game.mkdir(parents=True)
        shutil.copyfile(PIP / "area07_npc_twinkles.lu", self.game / "area07_npc_twinkles.lu")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "anim_replace.py"), *map(str, args)],
                              capture_output=True, text=True, timeout=300)

    def test_round_trip(self):
        import anim_roundtrip
        n = 0
        for label, d in lae._iter_clips([PIP / "area07_npc_twinkles.lu", PIP / "umbrella.lu"]):
            r = anim_roundtrip.check_clip(d)
            self.assertEqual(r["status"], "ok", f"{label}: {r}")
            self.assertTrue(r["raw_exact"], label)
            self.assertTrue(r["json_ok"], label)
            n += 1
        self.assertEqual(n, 5)

    def test_naughty_walk_takes_the_dance(self):
        from naughty_lu import LuFile
        lu = LuFile(PIP / "skinnaughty.lu")
        donor = bytes(lu.chunk(lae.clip_records(lu, P_DANCE)[0]))
        walk = bytes(lu.chunk(lae.clip_records(lu, P_WALK)[0]))
        notes = []
        obj = ar.swap_model(lu, P_WALK, donor, notes=notes)
        new = lae.build_clip(obj, walk)
        f = lae.header_fields(new)
        self.assertEqual((f["name_hash"], f["game"]), (P_WALK, "pip"))
        self.assertAlmostEqual(f["duration"], 2.3333, places=3)
        self.assertTrue(any("drives 121 of the 121" in n for n in notes), notes)
        c0, c1 = decode_clip(walk, Counter()), decode_clip(new, Counter())
        self.assertEqual(c1["bone_hashes"], lae.parse_clip(donor)["bone_hashes"])
        sp = []
        for c in (c0, c1):
            ch = channel(c, 0, 0x06)
            v = sample_channel(ch, np.array([0.0, c["duration"]]))
            sp.append((v[1] - v[0]) / c["duration"])
        self.assertAlmostEqual(sp[0], sp[1], places=4)

    def test_a_smaller_clip_is_padded_to_the_original_size(self):
        # PiP hangs at level load when a record shrinks or moves (verified in
        # game), so a shorter replacement keeps the original record size.
        from naughty_lu import LuFile
        path = PIP / "skinnaughty.lu"
        lu = LuFile(path)
        shrug = bytes(lu.chunk(lae.clip_records(lu, P_SHRUG)[0]))
        obj = ar.swap_model(lu, P_WALK, shrug)
        out, log = lae.replace_in_container(path, [(P_WALK, obj, None)])
        self.assertTrue(any("padded to 23,296" in s for s in log), log)
        f = self.dir / "skinnaughty.lu"
        f.write_bytes(out)
        back = LuFile(f)
        for x, y in zip(lu.records, back.records):
            self.assertEqual((x.hash, x.size, x.offset), (y.hash, y.size, y.offset))

    def test_a_bigger_clip_is_refused(self):
        from naughty_lu import LuFile
        lu = LuFile(PIP / "skinnaughty.lu")
        dance = bytes(lu.chunk(lae.clip_records(lu, P_DANCE)[0]))
        obj = ar.swap_model(lu, P_WALK, dance)
        with self.assertRaisesRegex(lae.EncodeError, "must fit"):
            lae.replace_in_container(PIP / "skinnaughty.lu", [(P_WALK, obj, None)])

    def test_fit_model_and_renames(self):
        # the dance with the walk's movement is 48 bytes over the dance's own
        # record; fit_model makes its flattest channel constant
        import struct
        from naughty_lu import LuFile, rebuild_luh
        lu = LuFile(PIP / "skinnaughty.lu")
        walk_r, dance_r = (lae.clip_records(lu, h)[0] for h in (P_WALK, P_DANCE))
        walk, dance = bytes(lu.chunk(walk_r)), bytes(lu.chunk(dance_r))
        obj = ar.swap_model(lu, P_WALK, dance)
        self.assertGreater(len(lae.build_clip(obj, walk)), len(dance))
        notes = []
        new = ar.fit_model(obj, walk, len(dance), notes.append)
        self.assertLessEqual(len(new), len(dance))
        new += b"\xEF" * (len(dance) - len(new))
        self.assertTrue(any("1 near-constant" in n for n in notes), notes)
        with self.assertRaises(ar.SwapError):
            ar.fit_model(ar.swap_model(lu, P_WALK, dance), walk, len(walk))
        old = bytearray(walk)
        struct.pack_into(">I", old, 8, P_DANCE)
        f = self.dir / "skinnaughty.lu"
        f.write_bytes(rebuild_luh(lu, {dance_r.index: new, walk_r.index: bytes(old)},
                                  renames={dance_r.index: P_WALK, walk_r.index: P_DANCE}))
        back = LuFile(f)
        self.assertEqual(bytes(back.chunk(lae.clip_records(back, P_WALK)[0])), new)
        self.assertEqual(lae.clip_records(back, P_WALK)[0].offset, dance_r.offset)

    def test_a_long_donor_takes_its_own_record(self):
        """Walk -> a dance three times its size: the dance's record takes it
        and the two records trade names (verified in game 2026-11-17). The
        .srpatch (format 4) gives the same file as -o."""
        import sr_patch
        from naughty_lu import LuFile
        shutil.copyfile(PIP / "skinnaughty.lu", self.game / "skinnaughty.lu")
        lu = self.game / "skinnaughty.lu"
        patch, out = self.dir / "D.srpatch", self.dir / "out" / "skinnaughty.lu"
        r = self.run_tool("swap", lu, "--clip", f"{P_WALK:08x}", "--from", lu,
                          "--donor", f"{P_DANCE:08x}", "--patch", patch, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("stored in the donor's record", r.stdout)
        with zipfile.ZipFile(patch) as z:
            m = json.loads(z.read("manifest.json"))
        self.assertEqual(m["format_version"], 4)
        self.assertEqual(m["targets"][0]["edits"][0]["record"], f"0x{P_DANCE:08x}")
        applied = self.dir / "applied"
        res = sr_patch.apply_patch(str(patch), str(self.game.parent), out_dir=str(applied),
                                   log=lambda *_: None)
        self.assertEqual([f["status"] for f in res["files"]], ["identical"])
        self.assertEqual((applied / "skinnaughty.lu").read_bytes(), out.read_bytes())
        a, b = LuFile(PIP / "skinnaughty.lu"), LuFile(out)
        for x, y in zip(a.records, b.records):
            self.assertEqual((x.size, x.offset), (y.size, y.offset))
        walk, dance = (lae.clip_records(b, h)[0] for h in (P_WALK, P_DANCE))
        self.assertEqual(walk.offset, lae.clip_records(a, P_DANCE)[0].offset)
        self.assertEqual(dance.offset, lae.clip_records(a, P_WALK)[0].offset)
        f = lae.header_fields(bytes(b.chunk(walk)))
        self.assertEqual(f["name_hash"], P_WALK)
        self.assertAlmostEqual(f["duration"], 2.3333, places=3)
        old = bytearray(a.chunk(lae.clip_records(a, P_WALK)[0]))
        old[8:12] = P_DANCE.to_bytes(4, "big")
        self.assertEqual(bytes(b.chunk(dance)), bytes(old))

    def test_one_record_cannot_take_two_clips(self):
        from naughty_lu import LuFile
        lu = LuFile(PIP / "skinnaughty.lu")
        dance = bytes(lu.chunk(lae.clip_records(lu, P_DANCE)[0]))
        names, used, targets = ar.load_names("pip"), set(), [P_WALK, P_RUN]
        got = [ar.pip_record(lu, h, P_DANCE, ar.swap_model(lu, h, dance), targets,
                             used, names, [])
               for h in (P_WALK,)]
        self.assertEqual(got, [P_DANCE])
        with self.assertRaisesRegex(ar.SwapError, "already taken"):
            ar.pip_record(lu, P_RUN, P_DANCE, ar.swap_model(lu, P_RUN, dance), targets,
                          used, names, [])
        # a clip that fits its own record keeps it
        shrug = bytes(lu.chunk(lae.clip_records(lu, P_SHRUG)[0]))
        self.assertIsNone(ar.pip_record(lu, P_WALK, P_SHRUG, ar.swap_model(lu, P_WALK, shrug),
                                        [P_WALK], set(), names, []))

    def test_a_clip_for_another_skeleton_is_refused(self):
        from naughty_lu import LuFile
        lu = LuFile(PIP / "skinnaughty.lu")
        tw = LuFile(PIP / "area07_npc_twinkles.lu")
        donor = bytes(tw.chunk(lae.clip_records(tw, T_DONOR)[0]))
        with self.assertRaises(ar.SwapError):
            ar.swap_model(lu, P_WALK, donor)

    def test_swap_patch_and_lu_agree(self):
        import sr_patch
        lu = self.game / "area07_npc_twinkles.lu"
        patch, out = self.dir / "Tw.srpatch", self.dir / "out" / "area07_npc_twinkles.lu"
        r = self.run_tool("swap", lu, "--clip", f"{T_TARGET:08x}", "--from", lu,
                          "--donor", f"{T_DONOR:08x}", "--patch", patch, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("Panic in Paradise", r.stdout)
        with zipfile.ZipFile(patch) as z:
            m = json.loads(z.read("manifest.json"))
        self.assertEqual((m["game"], m["format_version"]), ("pip", 3))
        res = sr_patch.apply_patch(str(patch), str(self.game.parent),
                                   out_dir=str(self.dir / "applied"), log=lambda *_: None)
        self.assertEqual([f["status"] for f in res["files"]], ["identical"])
        self.assertEqual((self.dir / "applied" / lu.name).read_bytes(), out.read_bytes())
        from naughty_lu import LuFile
        back, orig = LuFile(out), LuFile(lu)
        donor = bytes(orig.chunk(lae.clip_records(orig, T_DONOR)[0]))
        got = bytes(back.chunk(lae.clip_records(back, T_TARGET)[0]))
        # a same-skeleton PiP swap keeping no movement of its own differs from
        # the donor's record only in the name and the root track
        self.assertEqual(lae.header_fields(got)["name_hash"], T_TARGET)
        self.assertEqual(lae.parse_clip(got)["bone_hashes"], lae.parse_clip(donor)["bone_hashes"])
        for r in orig.records:
            if r.hash != T_TARGET and not r.external:
                self.assertEqual(bytes(back.chunk(back.records[r.index])),
                                 bytes(orig.chunk(r)), r.index)

    def test_replace_movement_gives_the_donor_record_back(self):
        """With the donor's own movement, a same-skeleton PiP swap is the
        donor's record under the target's name, byte for byte."""
        from naughty_lu import LuFile
        lu = LuFile(PIP / "area07_npc_twinkles.lu")
        donor = bytes(lu.chunk(lae.clip_records(lu, T_DONOR)[0]))
        tgt = bytes(lu.chunk(lae.clip_records(lu, T_TARGET)[0]))
        new = lae.build_clip(ar.swap_model(lu, T_TARGET, donor, keep_movement=False), tgt)
        self.assertEqual(new[:8] + new[0xC:], donor[:8] + donor[0xC:])


if __name__ == "__main__":
    unittest.main()
