#!/usr/bin/env python3
"""The native LZX decoder (_lzxdec, built from tools/lzxnative_src) must give
exactly what the Python decoder gives: on retail segments of both games, on
the encoder's own output, and on damaged streams (an error, never a crash).
Skipped when the native module isn't built."""
import random
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import naughty_lu as N
import game_paths

try:
    import _lzxdec
except ImportError:
    _lzxdec = None


def _segments(lu):
    """(stream, out_len, window bits) of each LZX-compressed segment."""
    window = lu.lzx_window or 0x100000
    wb = window.bit_length() - 1
    pos, remaining = lu.data_base, lu.image_size
    for sz in lu.segment_sizes:
        target = min(window, remaining)
        seg = bytes(lu.raw[pos:pos + sz])
        pos += sz
        remaining -= target
        if sz != target:
            frames, _ = N.parse_xmem_frames(seg, target)
            yield b"".join(p for _, p in frames), target, wb


def _python(stream, n, wb):
    try:
        return N.LZXDecoder(wb).decompress(stream, n)
    except Exception:
        return None


def _native(stream, n, wb):
    try:
        return _lzxdec.decompress(stream, n, wb)
    except ValueError:
        return None


@unittest.skipUnless(_lzxdec, "native decoder not built (tools/lzxnative_src/build.py)")
class NativeDecoder(unittest.TestCase):
    def test_used_by_naughty_lu(self):
        self.assertIs(N._lzxdec, _lzxdec)

    def test_encoder_output_round_trips(self):
        import lzx_encode
        rng = random.Random(7)
        data = bytes(rng.choice(b"abcdefgh") for _ in range(150_000)) + bytes(range(256)) * 300
        blob = lzx_encode.xmem_lzx_compress(data, 17)
        self.assertEqual(N.xmem_lzx_decompress(blob, len(data), 1 << 17), data)
        frames, _ = N.parse_xmem_frames(blob, len(data))
        stream = b"".join(p for _, p in frames)
        self.assertEqual(_lzxdec.decompress(stream, len(data), 17), data)

    def _same_as_python(self, path):
        lu = N.LuFile(path)
        n = 0
        for stream, size, wb in _segments(lu):
            self.assertEqual(_lzxdec.decompress(stream, size, wb),
                             N.LZXDecoder(wb).decompress(stream, size), f"{path.name} segment {n}")
            n += 1
        return n

    @unittest.skipUnless((game_paths.NB1_DIR / "normalbear.lu").exists(), "retail NB1 files not available")
    def test_nb1_container_matches_python(self):
        self.assertGreater(self._same_as_python(game_paths.NB1_DIR / "normalbear.lu"), 1)

    @unittest.skipUnless((game_paths.PIP_DIR / "global.lu").exists(), "retail PiP files not available")
    def test_pip_container_matches_python(self):
        # global.lu holds an uncompressed LZX block (segment 7)
        self.assertGreater(self._same_as_python(game_paths.PIP_DIR / "global.lu"), 1)

    def test_damaged_streams_fail_cleanly(self):
        import lzx_encode
        rng = random.Random(11)
        data = bytes(rng.choice(b"naughty bear ") for _ in range(40_000))
        blob = lzx_encode.xmem_lzx_compress(data, 16)
        frames, _ = N.parse_xmem_frames(blob, len(data))
        stream = b"".join(p for _, p in frames)
        for trial in range(60):
            bad = bytearray(stream)
            for _ in range(rng.randint(1, 8)):
                bad[rng.randrange(len(bad))] = rng.randrange(256)
            if trial % 5 == 0:
                bad = bad[:rng.randrange(len(bad))]
            bad = bytes(bad)
            got = _native(bad, len(data), 16)
            if got is not None:
                self.assertEqual(len(got), len(data))
                want = _python(bad, len(data), 16)
                if want is not None:
                    self.assertEqual(got, want, f"trial {trial}")
        with self.assertRaises(ValueError):
            _lzxdec.decompress(stream, len(data), 14)

    def test_errors_reach_callers_as_lzx_errors(self):
        with self.assertRaises(N.LZXError):
            N._lzx_decode(b"\xff" * 64, 1000, 16)


if __name__ == "__main__":
    unittest.main()
