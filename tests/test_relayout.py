#!/usr/bin/env python3
"""A rebuilt container must place every record where the engine expects it:
at the first multiple of its own alignment after the previous record."""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

from naughty_lu import LuFile
from lu_chunk_replace import relayout, record_alignment

RETAIL = Path(r"D:\testingenvironment\initialnb1files\lu")
NORMALBEAR = RETAIL / "normalbear.lu"
SCRIPT = 2773   # basenpcbodystatemachine, followed by two in-image records


@unittest.skipUnless(NORMALBEAR.exists(), "retail NB1 files not available")
class Relayout(unittest.TestCase):
    def setUp(self):
        self.lu = LuFile(NORMALBEAR)
        self.rec = self.lu.records[SCRIPT]
        self.old = self.lu.image[self.rec.offset:self.rec.offset + self.rec.size]

    def test_unchanged_record_reproduces_retail(self):
        image, offsets = relayout(self.lu, {SCRIPT: self.old})
        self.assertEqual(bytes(image), bytes(self.lu.image))
        for i, off in offsets.items():
            self.assertEqual(off, self.lu.records[i].offset)

    def test_every_growth_keeps_next_record_at_first_boundary(self):
        # growth by 1..32 bytes covers every end position within 16-byte steps;
        # the old shift-by-rounded-delta left a 16-byte gap for some of them
        nxt = self.lu.records[SCRIPT + 1]
        for grow in range(1, 33):
            new = self.old + b"\0" * grow
            image, offsets = relayout(self.lu, {SCRIPT: new})
            end = self.rec.offset + len(new)
            al = record_alignment(nxt)
            self.assertEqual(offsets[nxt.index], (end + al - 1) // al * al, grow)
            self.assertEqual(image[offsets[nxt.index]:offsets[nxt.index] + nxt.size],
                             self.lu.image[nxt.offset:nxt.offset + nxt.size])


if __name__ == "__main__":
    unittest.main()
