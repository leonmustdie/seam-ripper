#!/usr/bin/env python3
"""tests/test_verify_lzx.py - permanent regression coverage for verify_lzx.py.

These promote the ad hoc scratch checks run by hand during the NB1 alignment
debugging session into something the repo can rerun on its own. All fixtures
are synthetic: no retail game data ships with the toolkit or this test.

Two things are being guarded specifically because they were real, found bugs
this session, not hypothetical ones:
  - test_structural_fails_on_misaligned_records reproduces the exact class of
    bug that shipped a crashing NB1 build: a resized chunk splice shifted
    every later record off the 16-byte grid, and nothing caught it before
    boot time.
  - test_independent_fails_on_corrupted_payload guards the reason the
    independent-decode leg exists at all: a decoder written by the same
    author as the encoder can share its blind spots, so this asserts the
    check actually notices a real bitstream corruption, not just a
    self-consistent round trip.

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lzx_encode
import verify_lzx
from naughty_lu import LuRecord

WBITS = 15  # smallest valid window (naughty_lu.POSITION_SLOTS); plenty for
            # a fixture this small, and fast to compress.


class FakeLu:
    """Just enough of naughty_lu.LuFile's surface for verify_lzx to operate
    on: real LuRecord objects plus the container-level fields it reads.
    Not a stub of the parsing logic, only of the object verify_lzx consumes,
    so the checks under test are the real ones, not reimplemented copies."""

    def __init__(self, records, image, compressed_blob=None):
        self.records = records
        self.image = image
        self.image_size = len(image)
        if compressed_blob is None:
            self.compressed = False
        else:
            self.compressed = True
            self.raw = compressed_blob
            self.data_base = 0
            self.segment_sizes = [len(compressed_blob)]
            self.segment_count = 1
            self.lzx_window = 1 << WBITS


def _well_formed_fixture():
    """Two records, second one 16-aligned with a 12-byte 0xBF-padded gap
    after the first, matching retail convention. Returns (records, image)."""
    rec0 = b"A" * 20
    pad = b"\xBF" * 12
    rec1 = b"B" * 32
    image = rec0 + pad + rec1
    records = [
        LuRecord(0, 0x1111, 0, len(rec0), 0, 0),
        LuRecord(1, 0x2222, 0, len(rec1), len(rec0) + len(pad), 0),
    ]
    assert records[1].offset == 32          # 16-aligned
    assert len(image) == 64
    return records, image


class TestStructural(unittest.TestCase):
    def test_pass_on_well_formed_uncompressed(self):
        records, image = _well_formed_fixture()
        lu = FakeLu(records, image)
        msg = verify_lzx.check_structural(lu)
        self.assertIn("structural OK", msg)

    def test_pass_on_well_formed_compressed(self):
        records, image = _well_formed_fixture()
        blob = lzx_encode.xmem_lzx_compress(image, WBITS)
        lu = FakeLu(records, image, blob)
        msg = verify_lzx.check_structural(lu)
        self.assertIn("structural OK", msg)
        self.assertIn("1 segment(s)", msg)

    def test_fails_on_misaligned_records(self):
        """Reproduces the actual v1 crash bug: a record shifted off the
        16-byte grid. This is what a raw-delta splice shift looks like."""
        records, image = _well_formed_fixture()
        records[1].offset = 25   # not a multiple of 16
        lu = FakeLu(records, image)
        with self.assertRaises(verify_lzx.VerifyError) as cm:
            verify_lzx.check_structural(lu)
        self.assertIn("not 16-byte aligned", str(cm.exception))
        self.assertIn(": 1", str(cm.exception))   # names record index 1

    def test_fails_on_bad_gap_padding(self):
        records, image = _well_formed_fixture()
        # zero-fill the gap instead of 0xBF
        bad_image = image[:20] + b"\x00" * 12 + image[32:]
        lu = FakeLu(records, bad_image)
        with self.assertRaises(verify_lzx.VerifyError) as cm:
            verify_lzx.check_structural(lu)
        self.assertIn("not", str(cm.exception))
        self.assertIn("filled", str(cm.exception))

    def test_fails_on_overlapping_records(self):
        records, image = _well_formed_fixture()
        # 16-aligned, but still inside record 0's 20-byte span: the
        # alignment check alone wouldn't catch this, the overlap check must.
        records[1].offset = 16
        lu = FakeLu(records, image)
        with self.assertRaises(verify_lzx.VerifyError) as cm:
            verify_lzx.check_structural(lu)
        self.assertIn("overlap", str(cm.exception))

    def test_fails_on_missing_terminator(self):
        records, image = _well_formed_fixture()
        blob = lzx_encode.xmem_lzx_compress(image, WBITS)
        truncated = blob[:-5]   # strip the 5-byte zero terminator
        lu = FakeLu(records, image, truncated)
        with self.assertRaises(verify_lzx.VerifyError) as cm:
            verify_lzx.check_structural(lu)
        self.assertIn("terminator", str(cm.exception))


class TestIndependentDecode(unittest.TestCase):
    def setUp(self):
        if verify_lzx.find_verifier() is None:
            self.skipTest("lzxverify binary not built for this platform; "
                          "run lzxverify_src/build.sh first")

    def test_pass_on_real_encoder_output(self):
        records, image = _well_formed_fixture()
        blob = lzx_encode.xmem_lzx_compress(image, WBITS)
        lu = FakeLu(records, image, blob)
        msg = verify_lzx.check_independent(lu, verify_lzx.find_verifier())
        self.assertIn("byte-exact", msg)

    def test_fails_on_corrupted_payload(self):
        """The whole reason this leg exists: catch a bitstream the toolkit's
        own encoder produced wrong, using a DIFFERENT implementation."""
        records, image = _well_formed_fixture()
        blob = bytearray(lzx_encode.xmem_lzx_compress(image, WBITS))
        # flip a byte inside the LZX payload (well past any frame header)
        flip_at = len(blob) - 8
        blob[flip_at] ^= 0xFF
        lu = FakeLu(records, image, bytes(blob))
        with self.assertRaises(verify_lzx.VerifyError):
            verify_lzx.check_independent(lu, verify_lzx.find_verifier())


if __name__ == "__main__":
    unittest.main()
