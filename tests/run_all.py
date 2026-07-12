#!/usr/bin/env python3
"""tests/run_all.py - run every regression test in this folder.

Usage:  python3 tests/run_all.py          (from the repo root, or anywhere)

No third-party dependencies (stdlib unittest only), matching the rest of
this toolkit. The independent-decode tests in test_verify_lzx.py skip
themselves if lzxverify hasn't been built for this platform yet, rather
than failing the whole run.
"""
import sys
import unittest
from pathlib import Path

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here.parent / "tools"))
    loader = unittest.TestLoader()
    suite = loader.discover(str(here), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
