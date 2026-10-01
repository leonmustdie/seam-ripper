#!/usr/bin/env python3
"""Tests for lua_repair.

The rewrites must fix the real defects luadec emits, must not touch anything
inside a string or a comment, and must leave already-valid code alone. The
end-to-end cases assert against luac5.1 itself rather than against an
expected string, including a control that checks the broken input really is
rejected first - otherwise a test that "passes" proves nothing.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import lua_repair

LUAC = TOOLS / "luac51.exe"
if not LUAC.exists():
    LUAC = TOOLS / "luac51"


class Lexer(unittest.TestCase):
    def test_spans_cover_input_exactly(self):
        src = 'a = "x" -- c\nb = [[long]] .. \'q\'\n'
        spans = list(lua_repair.lex(src))
        self.assertEqual("".join(src[a:b] for _, a, b in spans), src)

    def test_finds_all_three_kinds(self):
        src = 'a = "x" -- c\nb = [[long]]\n'
        kinds = {k for k, _, _ in lua_repair.lex(src)}
        self.assertEqual(kinds, {"code", "string", "comment"})


class MethodRefs(unittest.TestCase):
    """`obj:Method` used as a value is not Lua; `obj.Method` is the same
    lookup, and is correct here because luadec has already put the receiver
    in the sibling register."""

    def test_colon_as_value_becomes_dot(self):
        out, rep = lua_repair.repair("local A, B = obj:Method, obj\n")
        self.assertEqual(out, "local A, B = obj.Method, obj\n")
        self.assertEqual(rep.self_refs, 1)

    def test_genuine_calls_untouched(self):
        for src in ('obj:Method(1, 2)\n',
                    'obj:Method"str"\n',
                    "obj:Method{t=1}\n",
                    "obj:Method[[long]]\n",
                    "function T:Method(a)\nend\n"):
            with self.subTest(src=src.strip()):
                out, rep = lua_repair.repair(src)
                self.assertEqual(out, src)
                self.assertEqual(rep.self_refs, 0)

    def test_call_split_across_newline_is_still_a_call(self):
        _, rep = lua_repair.repair("local x = obj:Method\n  (arg)\n")
        self.assertEqual(rep.self_refs, 0)

    def test_colon_inside_string_untouched(self):
        out, rep = lua_repair.repair(
            'local s = "obj:Method, obj"\nlocal A, B = o:M, o\n')
        self.assertEqual(out,
                         'local s = "obj:Method, obj"\nlocal A, B = o.M, o\n')
        self.assertEqual(rep.self_refs, 1)

    def test_colon_inside_comment_untouched(self):
        out, rep = lua_repair.repair(
            "-- see obj:Method, obj\nlocal A, B = o:M, o\n")
        self.assertEqual(out, "-- see obj:Method, obj\nlocal A, B = o.M, o\n")
        self.assertEqual(rep.self_refs, 1)

    def test_colon_inside_long_comment_untouched(self):
        out, rep = lua_repair.repair("--[[ obj:Method, obj ]]\nlocal A, B = o:M, o\n")
        self.assertTrue(out.startswith("--[[ obj:Method, obj ]]"), out)
        self.assertEqual(rep.self_refs, 1)

    def test_goto_label_untouched(self):
        out, _ = lua_repair.repair("::continue::\n")
        self.assertEqual(out, "::continue::\n")


class ComputedMethodRefs(unittest.TestCase):
    """`obj:[expr]` - a SELF whose method name is not a constant. Lua has no
    such syntax at all; `obj[expr]` is the equivalent lookup."""

    def test_rewritten(self):
        out, rep = lua_repair.repair("a, b = a:[k], a\n")
        self.assertEqual(out, "a, b = a[k], a\n")
        self.assertEqual(rep.computed_refs, 1)
        self.assertEqual(rep.self_refs, 0)

    def test_real_init_unlockable_line(self):
        out, _ = lua_repair.repair(
            "  createUnlockable, acc = createUnlockable:[condition2], createUnlockable\n")
        self.assertEqual(
            out,
            "  createUnlockable, acc = createUnlockable[condition2], createUnlockable\n")

    def test_long_string_call_untouched(self):
        """`obj:m[[str]]` is a real call - a NAME sits between the : and the [."""
        out, rep = lua_repair.repair("obj:m[[str]]\n")
        self.assertEqual(out, "obj:m[[str]]\n")
        self.assertEqual(rep.computed_refs, 0)

    def test_inside_string_untouched(self):
        out, rep = lua_repair.repair('local s = "a:[k]"\nx, y = o:[k], o\n')
        self.assertEqual(out, 'local s = "a:[k]"\nx, y = o[k], o\n')
        self.assertEqual(rep.computed_refs, 1)


class EmptyStatements(unittest.TestCase):
    """Lua 5.2 added the empty statement; 5.1 did not, so a lone `;` is a
    parse error. It cannot simply be deleted either - luadec emits it to stop
    `a = b` and a following `(f)(x)` parsing as one call."""

    def test_at_block_start_is_dropped(self):
        out, rep = lua_repair.repair("do\n  ;\n  ((f)()):M(true)\nend\n")
        self.assertEqual(out, "do\n  ((f)()):M(true)\nend\n")
        self.assertEqual(rep.lone_semis, 1)

    def test_moves_onto_previous_statement(self):
        out, rep = lua_repair.repair("a = b\n;\n(f)(x)\n")
        self.assertEqual(out, "a = b;\n(f)(x)\n")
        self.assertEqual(rep.lone_semis, 1)

    def test_not_appended_after_a_block_opener(self):
        for opener, src in (
                ("then", "if x then\n  ;\n  (f)(x)\nend\n"),
                ("else", "if x then\n  y = 1\nelse\n  ;\n  (f)(x)\nend\n"),
                ("do", "do\n  ;\n  (f)(x)\nend\n"),
                ("repeat", "repeat\n  ;\n  (f)(x)\nuntil x\n")):
            with self.subTest(opener=opener):
                out, _ = lua_repair.repair(src)
                self.assertNotIn(f"{opener};", out)

    def test_trailing_semicolon_untouched(self):
        out, rep = lua_repair.repair("a = 1;\nb = 2\n")
        self.assertEqual(out, "a = 1;\nb = 2\n")
        self.assertEqual(rep.lone_semis, 0)

    def test_semicolon_in_string_untouched(self):
        out, _ = lua_repair.repair('local s = "\\n;\\n"\n')
        self.assertEqual(out, 'local s = "\\n;\\n"\n')


class Holes(unittest.TestCase):
    """Spots where luadec produced no value at all. Not repairable - the
    value was never decompiled - so they are detected, never patched."""

    def test_dot_end_comma_spelling(self):
        _, rep = lua_repair.repair("local a, b = f(x), .end\n")
        self.assertTrue(rep.unrecoverable)

    def test_dot_end_equals_spelling(self):
        _, rep = lua_repair.repair("local a, b = .end\n")
        self.assertTrue(rep.unrecoverable)

    def test_dot_end_left_unpatched(self):
        src = "local a, b = getmetatable(x), .end\n"
        out, _ = lua_repair.repair(src)
        self.assertEqual(out, src)

    def test_empty_slot_after_equals(self):
        _, rep = lua_repair.repair('local a, b, c = , "x", "y"\n')
        self.assertTrue(rep.unrecoverable)

    def test_empty_slot_between_commas(self):
        _, rep = lua_repair.repair('local a, b, c = f(), , "y"\n')
        self.assertTrue(rep.unrecoverable)

    def test_holes_in_strings_are_not_holes(self):
        _, rep = lua_repair.repair('local s = "a = , b"\nlocal t = "x, , y"\n')
        self.assertFalse(rep.unrecoverable)

    def test_ordinary_comma_lists_are_not_holes(self):
        _, rep = lua_repair.repair("local a, b, c = 1, 2, 3\nf(x, y)\nt = {1, 2, 3}\n")
        self.assertFalse(rep.unrecoverable)

    def test_field_named_ending_is_not_a_hole(self):
        _, rep = lua_repair.repair("local a = x.ending\n")
        self.assertFalse(rep.unrecoverable)


class Warnings(unittest.TestCase):
    def test_counted_but_not_fatal(self):
        """2 of the 20 chunks that recompile byte-identically still print
        one, so it must not gate anything."""
        src = "-- DECOMPILER ERROR at PC35: Confused\nlocal x = 1\n"
        out, rep = lua_repair.repair(src)
        self.assertEqual(rep.decompiler_errors, 1)
        self.assertFalse(rep.unrecoverable)
        self.assertEqual(out, src)

    def test_strippable_on_request(self):
        src = "-- DECOMPILER ERROR at PC35: Confused\nlocal x = 1\n"
        out, _ = lua_repair.repair(src, strip_warnings=True)
        self.assertNotIn("DECOMPILER ERROR", out)


class Invariants(unittest.TestCase):
    def test_idempotent(self):
        src = "local A, B = obj:Method, obj\nc = d\n;\n(f)()\n"
        once, _ = lua_repair.repair(src)
        twice, rep2 = lua_repair.repair(once)
        self.assertEqual(twice, once)
        self.assertEqual(rep2.changed, 0)

    def test_valid_source_untouched(self):
        src = ("local t = {}\nfunction t:go(a, b)\n  return self.x:sub(1, 2)\n"
               "end\nt:go(1, 2)\n")
        out, rep = lua_repair.repair(src)
        self.assertEqual(out, src)
        self.assertEqual(rep.changed, 0)


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class AgainstRealLuac(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _parses(self, src):
        p = self.tmp / "s.lua"
        p.write_text(src, encoding="utf-8")
        r = subprocess.run([str(LUAC), "-p", str(p)],
                           capture_output=True, text=True)
        return r.returncode == 0, (r.stderr or r.stdout)

    def test_repaired_output_parses(self):
        broken = ("local function f(o, x)\n"
                  "  local A, B = o:Method, o\n"
                  "  do\n"
                  "    ;\n"
                  "    ((x)()):Other(true)\n"
                  "  end\n"
                  "  return A(B)\n"
                  "end\n"
                  "return f\n")
        ok, err = self._parses(broken)
        self.assertFalse(ok, "control failed: broken source was accepted, so "
                             "this test would pass even if repair did nothing")
        fixed, rep = lua_repair.repair(broken)
        ok, err = self._parses(fixed)
        self.assertTrue(ok, err)
        self.assertEqual((rep.self_refs, rep.lone_semis), (1, 1))

    def test_disambiguation_survives_repair(self):
        """The `;` must still separate the two statements afterwards."""
        src = "local b = {}\nlocal f = print\na = b\n;\n(f)(1)\n"
        out, _ = lua_repair.repair(src)
        ok, err = self._parses(out)
        self.assertTrue(ok, err)
        self.assertIn(";", out)

    def test_computed_ref_repair_parses(self):
        broken = "local t, k = {}, 'x'\nlocal A, B = t:[k], t\nreturn A(B)\n"
        ok, _ = self._parses(broken)
        self.assertFalse(ok, "control failed: broken source was accepted")
        fixed, _ = lua_repair.repair(broken)
        ok, err = self._parses(fixed)
        self.assertTrue(ok, err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
