#!/usr/bin/env python3
"""Tests for sr_launch.py: installing shipped files into a restuff build and starting it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import sr_backup
import sr_launch


class FakePopen:
    """Records how it was started; never starts anything."""
    calls = []

    def __init__(self, argv, **kw):
        FakePopen.calls.append((argv, kw))
        self.pid = 4242


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="srlaunch_"))
        self.build = self.tmp / "out build"                # a space, as real paths have
        self.lu = self.build / "assets" / "lu"
        self.lu.mkdir(parents=True)
        (self.build / "restuff.exe").write_bytes(b"MZ fake")
        (self.lu / "global.lu").write_bytes(b"retail global")
        (self.lu / "area1.lu").write_bytes(b"retail area1")
        self.ship = self.tmp / "ship"
        self.ship.mkdir()
        (self.ship / "global.lu").write_bytes(b"modded global")
        (self.ship / "area1.lu").write_bytes(b"modded area1")
        FakePopen.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, name):
        return (self.lu / name).read_bytes()


class Locate(Base):
    def test_finds_the_parts(self):
        d = sr_launch.locate(self.build)
        self.assertEqual(Path(d["exe"]), self.build / "restuff.exe")
        self.assertEqual(Path(d["lu"]), self.lu)
        self.assertEqual(Path(d["backups"]), self.lu / ".seamripper" / "backups")

    def test_exe_path_is_accepted(self):
        self.assertEqual(Path(sr_launch.locate(self.build / "restuff.exe")["build"]),
                         self.build)

    def test_no_exe(self):
        (self.build / "restuff.exe").unlink()
        with self.assertRaisesRegex(sr_launch.LaunchError, "no restuff.exe"):
            sr_launch.locate(self.build)

    def test_no_game_files(self):
        shutil.rmtree(self.build / "assets")
        with self.assertRaisesRegex(sr_launch.LaunchError, "assets.lu"):
            sr_launch.locate(self.build)

    def test_missing_folder(self):
        with self.assertRaises(sr_launch.LaunchError):
            sr_launch.locate(self.tmp / "nowhere")

    def test_info_counts_and_backups(self):
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lambda m: None)
        d = sr_launch.info(self.build)
        self.assertEqual(d["lu_count"], 2)
        self.assertEqual([(r["file"], r["current"]) for r in d["backups_list"]],
                         [("global.lu", "modified")])


class Install(Base):
    def test_backs_up_then_copies(self):
        got = sr_launch.install(self.build, [self.ship / "global.lu"],
                                log=lambda m: None)
        self.assertEqual(self.read("global.lu"), b"modded global")
        self.assertEqual(self.read("area1.lu"), b"retail area1")     # untouched
        self.assertEqual(got[0]["created"], "retail")
        self.assertEqual(Path(got[0]["backup"]).read_bytes(), b"retail global")
        self.assertEqual(got[0]["dest"], str(self.lu / "global.lu"))

    def test_only_the_shipped_files_are_installed(self):
        sr_launch.install(self.build, [self.ship / "area1.lu"], log=lambda m: None)
        self.assertEqual(self.read("global.lu"), b"retail global")
        self.assertEqual(sorted(p.name for p in self.lu.glob("*.lu")),
                         ["area1.lu", "global.lu"])

    def test_retail_backup_survives_a_second_install(self):
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lambda m: None)
        (self.ship / "global.lu").write_bytes(b"modded again")
        got = sr_launch.install(self.build, [self.ship / "global.lu"],
                                log=lambda m: None)
        self.assertEqual(got[0]["created"], "previous")
        self.assertEqual(Path(got[0]["backup"]).read_bytes(), b"modded global")
        row = sr_backup.list_backups(self.lu)[0]
        self.assertEqual(Path(row["retail"]["backup"]).read_bytes(), b"retail global")

    def test_same_content_twice_makes_no_new_backup(self):
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lambda m: None)
        got = sr_launch.install(self.build, [self.ship / "global.lu"],
                                log=lambda m: None)
        self.assertIsNone(got[0]["created"])
        self.assertFalse(got[0]["changed"])
        self.assertEqual(len(sr_backup.list_backups(self.lu)[0]["previous"]), 0)

    def test_unknown_file_refused_and_nothing_copied(self):
        (self.ship / "typo.lu").write_bytes(b"x")
        with self.assertRaisesRegex(sr_launch.LaunchError, "typo.lu"):
            sr_launch.install(self.build, [self.ship / "global.lu", self.ship / "typo.lu"],
                              log=lambda m: None)
        self.assertEqual(self.read("global.lu"), b"retail global")
        self.assertFalse((self.lu / ".seamripper").exists())

    def test_allow_new(self):
        (self.ship / "extra.lu").write_bytes(b"new")
        got = sr_launch.install(self.build, [self.ship / "extra.lu"],
                                log=lambda m: None, allow_new=True)
        self.assertIsNone(got[0]["created"])
        self.assertEqual(self.read("extra.lu"), b"new")

    def test_missing_source(self):
        with self.assertRaisesRegex(sr_launch.LaunchError, "not found"):
            sr_launch.install(self.build, [self.ship / "nope.lu"], log=lambda m: None)

    def test_file_already_in_the_game_folder(self):
        with self.assertRaisesRegex(sr_launch.LaunchError, "already in the game"):
            sr_launch.install(self.build, [self.lu / "global.lu"], log=lambda m: None)

    def test_two_files_with_one_name(self):
        other = self.tmp / "other"
        other.mkdir()
        (other / "global.lu").write_bytes(b"second")
        with self.assertRaisesRegex(sr_launch.LaunchError, "both named"):
            sr_launch.install(self.build, [self.ship / "global.lu", other / "global.lu"],
                              log=lambda m: None)
        self.assertEqual(self.read("global.lu"), b"retail global")

    def test_no_temporary_file_left(self):
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lambda m: None)
        self.assertEqual([p.name for p in self.lu.iterdir() if "srtmp" in p.name], [])

    def test_the_log_lists_what_was_installed(self):
        lines = []
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lines.append)
        self.assertTrue(any("installed global.lu" in m for m in lines))


class Restore(Base):
    def test_puts_the_originals_back(self):
        sr_launch.install(self.build, [self.ship / "global.lu", self.ship / "area1.lu"],
                          log=lambda m: None)
        names = sr_launch.restore(self.build, log=lambda m: None)
        self.assertEqual(sorted(names), ["area1.lu", "global.lu"])
        self.assertEqual(self.read("global.lu"), b"retail global")
        self.assertEqual(self.read("area1.lu"), b"retail area1")

    def test_one_file(self):
        sr_launch.install(self.build, [self.ship / "global.lu", self.ship / "area1.lu"],
                          log=lambda m: None)
        sr_launch.restore(self.build, ["global.lu"], log=lambda m: None)
        self.assertEqual(self.read("global.lu"), b"retail global")
        self.assertEqual(self.read("area1.lu"), b"modded area1")

    def test_a_file_without_a_backup(self):
        with self.assertRaisesRegex(sr_launch.LaunchError, "no saved original"):
            sr_launch.restore(self.build, ["global.lu"], log=lambda m: None)

    def test_nothing_saved_means_nothing_to_do(self):
        self.assertEqual(sr_launch.restore(self.build, log=lambda m: None), [])

    def test_already_original_is_said_so(self):
        sr_launch.install(self.build, [self.ship / "global.lu"], log=lambda m: None)
        sr_launch.restore(self.build, log=lambda m: None)
        lines = []
        sr_launch.restore(self.build, log=lines.append)
        self.assertTrue(any("already the original" in m for m in lines))


class Launch(Base):
    def test_starts_the_exe_with_the_log_argument(self):
        got = sr_launch.launch(self.build, popen=FakePopen)
        argv, kw = FakePopen.calls[0]
        log = str(self.build / "restuff_log.txt")
        self.assertEqual(argv, [str(self.build / "restuff.exe"), "--log_file", log])
        self.assertEqual(kw["cwd"], str(self.build))
        self.assertEqual(got["pid"], 4242)
        self.assertEqual(got["log"], log)
        self.assertEqual(got["crash"], str(self.build / "restuff_crash.txt"))

    def test_detached_and_silent(self):
        sr_launch.launch(self.build, popen=FakePopen)
        _argv, kw = FakePopen.calls[0]
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["stdout"], subprocess.DEVNULL)
        if os.name == "nt":
            self.assertTrue(kw["creationflags"] & subprocess.DETACHED_PROCESS)
        else:
            self.assertTrue(kw["start_new_session"])

    def test_bad_build_starts_nothing(self):
        (self.build / "restuff.exe").unlink()
        with self.assertRaises(sr_launch.LaunchError):
            sr_launch.launch(self.build, popen=FakePopen)
        self.assertEqual(FakePopen.calls, [])

    def test_a_start_failure_is_a_launch_error(self):
        def boom(argv, **kw):
            raise OSError("not a valid program")
        with self.assertRaisesRegex(sr_launch.LaunchError, "could not start"):
            sr_launch.launch(self.build, popen=boom)

    def test_hint_names_both_files(self):
        h = sr_launch.log_hint(self.build)
        self.assertIn("restuff_log.txt", h)
        self.assertIn("restuff_crash.txt", h)


class Cli(Base):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "sr_launch.py"), *args],
                              capture_output=True, text=True)

    def test_install_then_info_then_restore(self):
        r = self.run_cli("install", str(self.build), str(self.ship / "global.lu"),
                         "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[-1])[0]["file"], "global.lu")
        r = self.run_cli("info", str(self.build), "--json")
        d = json.loads(r.stdout)
        self.assertEqual(d["backups_list"][0]["current"], "modified")
        r = self.run_cli("restore", str(self.build))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("global.lu"), b"retail global")

    def test_bad_build_exits_with_a_message(self):
        r = self.run_cli("info", str(self.tmp / "nowhere"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("restuff.exe", r.stderr)


if __name__ == "__main__":
    unittest.main()
