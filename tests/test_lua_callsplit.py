#!/usr/bin/env python3
"""tests/test_lua_callsplit.py - regression coverage for the call-site
splitter. All Lua fixtures here are hand-written and synthetic; none of it
is decompiled game script, so it's safe to ship with the toolkit.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import lua_callsplit as cs


class TestFindCalls(unittest.TestCase):
    def test_simple_call(self):
        src = "Foo(1, 2, 3)"
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls), 1)
        self.assertEqual([a.text for a in calls[0].args], ["1", "2", "3"])

    def test_method_call_form(self):
        src = "obj:Foo(FEAR_A, 10, false)"
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls), 1)
        self.assertEqual([a.text for a in calls[0].args], ["FEAR_A", "10", "false"])

    def test_does_not_match_similar_suffix(self):
        # "Foo" must not match "MyFoo(...)" or "Foobar(...)"
        src = "MyFoo(1) Foobar(2) Foo(3)"
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0].text, "3")

    def test_nested_call_argument_stays_whole(self):
        src = "Foo(1, Bar(2, 3), 4)"
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls[0].args), 3)
        self.assertEqual(calls[0].args[1].text, "Bar(2, 3)")

    def test_string_with_comma_stays_whole(self):
        src = 'Foo(1, "a, b, c", 2)'
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls[0].args), 3)
        self.assertEqual(calls[0].args[1].text, '"a, b, c"')

    def test_table_argument_stays_whole(self):
        src = "Foo(1, {x, y, z}, 2)"
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls[0].args), 3)
        self.assertEqual(calls[0].args[1].text, "{x, y, z}")

    def test_adversarial_mixed_case(self):
        """The exact combination that motivated a structural splitter over
        blind regex: nested call + comma-bearing string + table, together."""
        src = 'X:Foo(FEAR_A, PLAYER, foo(1, 2), "a, b", {x, y}, 1.5)'
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls), 1)
        got = [a.text for a in calls[0].args]
        self.assertEqual(got, ["FEAR_A", "PLAYER", "foo(1, 2)",
                               '"a, b"', "{x, y}", "1.5"])

    def test_multiple_calls_in_one_chunk(self):
        src = "\n".join(f"Foo({i}, {i*2})" for i in range(5))
        calls = cs.find_calls(src, "Foo")
        self.assertEqual(len(calls), 5)
        self.assertEqual([a.text for a in calls[2].args], ["2", "4"])

    def test_arg_spans_are_correct_offsets(self):
        src = "Foo(10, 20)"
        call = cs.find_calls(src, "Foo")[0]
        a0, a1 = call.args
        self.assertEqual(src[a0.start:a0.end], "10")
        self.assertEqual(src[a1.start:a1.end], "20")


if __name__ == "__main__":
    unittest.main()
