#!/usr/bin/env python3
"""A rebuilt container must place every record where the engine expects it:
at the first multiple of its own alignment after the previous record."""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

from naughty_lu import LuFile
from lu_chunk_replace import rebuild, relayout, record_alignment

import game_paths

RETAIL = game_paths.NB1_DIR
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


def _blobs(lu):
    out, at = [], lu.data_base
    for size in lu.segment_sizes:
        out.append(bytes(lu.raw[at:at + size]))
        at += size
    return out


@unittest.skipUnless(NORMALBEAR.exists(), "retail NB1 files not available")
class SegmentReuse(unittest.TestCase):
    """rebuild rewrites only the segments whose bytes changed (raw, or
    compressed on request); the others keep retail's compressed bytes."""

    def setUp(self):
        self.lu = LuFile(NORMALBEAR)
        self.rec = self.lu.records[SCRIPT]
        self.old = bytes(self.lu.image[self.rec.offset:self.rec.offset + self.rec.size])
        self.assertTrue(self.lu.compressed and self.lu.segment_count > 1)

    def test_unchanged_record_gives_the_retail_file(self):
        out, how = rebuild(self.lu, {SCRIPT: self.old})
        self.assertEqual(out, bytes(self.lu.raw))
        self.assertIn(f"{self.lu.segment_count} kept", how)

    def test_one_changed_byte_recompresses_one_segment(self):
        import os
        import tempfile
        import verify_lzx
        new = bytearray(self.old)
        new[-1] ^= 0xFF
        out, _ = rebuild(self.lu, {SCRIPT: bytes(new)})
        fd, tmp = tempfile.mkstemp(suffix=".lu")
        os.close(fd)
        try:
            Path(tmp).write_bytes(out)
            back = LuFile(tmp)
            want = bytearray(self.lu.image)
            at = self.rec.offset + self.rec.size - 1
            want[at] ^= 0xFF
            self.assertEqual(bytes(back.image), bytes(want))
            window = self.lu.lzx_window or 0x100000
            changed = [i for i, (a, b) in enumerate(zip(_blobs(self.lu), _blobs(back)))
                       if a != b]
            self.assertEqual(changed, [at // window])
            # the rewritten segment is stored raw: stored size == slice size
            i = at // window
            self.assertEqual(back.segment_sizes[i],
                             min(window, len(want) - i * window))
            verify_lzx.check_structural(back)
            verifier = verify_lzx.find_verifier()
            if verifier:
                verify_lzx.check_independent(back, verifier)
        finally:
            os.unlink(tmp)

    def test_compress_option_compresses_the_rewritten_segment(self):
        new = bytearray(self.old)
        new[-1] ^= 0xFF
        out, how = rebuild(self.lu, {SCRIPT: bytes(new)}, compress=True)
        self.assertIn("0 stored uncompressed", how)
        self.assertLess(len(out), len(rebuild(self.lu, {SCRIPT: bytes(new)})[0]))


if __name__ == "__main__":
    unittest.main()
