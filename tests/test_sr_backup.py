#!/usr/bin/env python3
"""Backups Seam Ripper keeps before overwriting a .lu: the first copy is the
retail one and is never replaced; later versions can be stepped back through."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import sr_backup


class Backups(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="srbk_"))
        self.f = self.dir / "game.lu"
        self.f.write_bytes(b"retail")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ship(self, data):
        sr_backup.backup_before_overwrite(self.f)
        self.f.write_bytes(data)

    def test_nothing_to_back_up(self):
        self.assertIsNone(sr_backup.backup_before_overwrite(self.dir / "new.lu"))
        self.assertFalse((self.dir / ".seamripper").exists())

    def test_first_copy_is_retail_and_never_replaced(self):
        b = sr_backup.backup_before_overwrite(self.f)
        self.assertEqual(b["created"], "retail")
        saved = self.dir / ".seamripper" / "backups" / "game.lu"
        self.assertEqual(Path(b["retail"]["backup"]), saved)
        self.assertEqual(saved.read_bytes(), b"retail")
        self.f.write_bytes(b"mod1")
        self.ship(b"mod2")
        self.ship(b"mod3")
        self.assertEqual(saved.read_bytes(), b"retail")

    def test_manifest_records_size_and_checksum(self):
        import hashlib
        b = sr_backup.backup_before_overwrite(self.f)
        self.assertEqual(b["retail"]["size"], 6)
        self.assertEqual(b["retail"]["sha256"], hashlib.sha256(b"retail").hexdigest())
        self.assertEqual(Path(b["retail"]["original"]), self.f.resolve())
        self.assertTrue(b["retail"]["time"])

    def test_same_bytes_are_not_kept_twice(self):
        sr_backup.backup_before_overwrite(self.f)
        b = sr_backup.backup_before_overwrite(self.f)
        self.assertIsNone(b["created"])
        self.assertEqual(b["previous"], [])

    def test_step_back_then_retail(self):
        self.ship(b"mod1")
        self.ship(b"mod2")
        self.ship(b"mod3")
        r = sr_backup.restore_previous(self.f)
        self.assertTrue(r["changed"])
        self.assertEqual(self.f.read_bytes(), b"mod2")
        sr_backup.restore_previous(self.f)
        self.assertEqual(self.f.read_bytes(), b"mod1")
        sr_backup.restore_previous(self.f)
        self.assertEqual(self.f.read_bytes(), b"retail")
        r = sr_backup.restore_previous(self.f)
        self.assertFalse(r["changed"])

    def test_revert_to_retail_can_be_undone(self):
        self.ship(b"mod1")
        r = sr_backup.revert_to_retail(self.f)
        self.assertTrue(r["changed"])
        self.assertEqual(self.f.read_bytes(), b"retail")
        sr_backup.restore_previous(self.f)
        self.assertEqual(self.f.read_bytes(), b"mod1")

    def test_list_reports_live_state(self):
        self.ship(b"mod1")
        (rows,) = sr_backup.list_backups(self.dir)
        self.assertEqual(rows["file"], "game.lu")
        self.assertEqual(rows["current"], "modified")
        sr_backup.revert_to_retail(self.f)
        self.assertEqual(sr_backup.list_backups(self.dir)[0]["current"], "retail")
        self.f.unlink()
        self.assertEqual(sr_backup.list_backups(self.dir)[0]["current"], "missing")

    def test_revert_all(self):
        other = self.dir / "other.lu"
        other.write_bytes(b"other retail")
        self.ship(b"mod1")
        sr_backup.backup_before_overwrite(other)
        other.write_bytes(b"other mod")
        res = sr_backup.revert_all(self.dir)
        self.assertEqual({r["file"] for r in res}, {"game.lu", "other.lu"})
        self.assertEqual(self.f.read_bytes(), b"retail")
        self.assertEqual(other.read_bytes(), b"other retail")

    def test_damaged_backup_is_not_restored(self):
        self.ship(b"mod1")
        (self.dir / ".seamripper" / "backups" / "game.lu").write_bytes(b"junk!!")
        with self.assertRaises(sr_backup.BackupError):
            sr_backup.revert_to_retail(self.f)
        self.assertEqual(self.f.read_bytes(), b"mod1")

    def test_no_backup(self):
        with self.assertRaises(sr_backup.BackupError):
            sr_backup.revert_to_retail(self.f)
        self.assertEqual(sr_backup.list_backups(self.dir), [])

    def test_older_versions_are_pruned_but_retail_stays(self):
        for i in range(sr_backup.KEEP_PREVIOUS + 4):
            self.ship(b"mod%d" % i)
        b = sr_backup.backup_before_overwrite(self.f)
        self.assertEqual(len(b["previous"]), sr_backup.KEEP_PREVIOUS)
        kept = [p for p in (self.dir / ".seamripper" / "backups").iterdir()
                if p.suffix == ".lu"]
        self.assertEqual(len(kept), sr_backup.KEEP_PREVIOUS + 1)
        self.assertEqual(Path(b["retail"]["backup"]).read_bytes(), b"retail")


if __name__ == "__main__":
    unittest.main()
