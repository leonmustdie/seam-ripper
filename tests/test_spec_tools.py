#!/usr/bin/env python3
"""The EXE build bundles every toolkit module that the GUI and the bundled tools import."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def spec_list(name):
    text = (ROOT / "seamripper.spec").read_text(encoding="utf-8")
    m = re.search(rf"^{name} = \[(.*?)\]", text, re.S | re.M)
    return set(re.findall(r'"([\w.]+\.py)"', m.group(1))) if m else set()


def local_imports(path):
    """Toolkit modules a file imports, at any depth (lazy imports count)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return {n for n in names if (TOOLS / f"{n}.py").exists()}


class SpecTools(unittest.TestCase):
    def test_every_imported_tool_is_bundled(self):
        bundled = spec_list("TOOL_SCRIPTS") | spec_list("OPTIONAL_SCRIPTS")
        todo = [ROOT / "SeamRipper.py", *sorted((ROOT / "sr_gui").glob("*.py"))]
        todo += [TOOLS / s for s in sorted(bundled) if (TOOLS / s).exists()]
        missing = {}
        for f in todo:
            for mod in local_imports(f):
                if f"{mod}.py" not in bundled:
                    missing.setdefault(f"{mod}.py", f.name)
        self.assertEqual(missing, {}, "imported but not in seamripper.spec (module: first importer)")


if __name__ == "__main__":
    unittest.main()
