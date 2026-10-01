#!/usr/bin/env python3
"""roundtrip_audit: an unchanged retail container and its scripts rebuild unchanged."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

RETAIL = Path(r"D:\testingenvironment\initialnb1files\lu\normalbear.lu")


@unittest.skipUnless(RETAIL.exists(), "retail normalbear.lu not available")
class RoundTripAudit(unittest.TestCase):
    def test_normalbear_rebuilds_unchanged(self):
        import roundtrip_audit as A
        A._init()
        _, problem, scripts = A.scan_file(RETAIL)
        self.assertIsNone(problem)
        self.assertTrue(scripts)
        for key, (name, _, chunk) in scripts.items():
            _, status, detail = A.check_script((key, chunk))
            self.assertIn(status, ("exact", "same code"), f"{name}: {detail}")


if __name__ == "__main__":
    unittest.main()
