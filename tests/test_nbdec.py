#!/usr/bin/env python3
"""Tests for nbdec, the purpose-built Lua 5.1 decompiler.

Every correctness test is a ROUND TRIP against the real compiler: take Lua
source, compile it with luac51, decompile, recompile, and require the
instructions and constants to match. That is the same bar `ship` applies, and
unlike "does the output look right" it cannot be fudged.

Constructs not yet implemented must raise Unsupported rather than emit
something plausible and wrong - a decompiler that quietly guesses is worse
than one that admits it cannot do it, because the guess ships.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nbdec

LUAC = TOOLS / "luac51.exe"
if not LUAC.exists():
    LUAC = TOOLS / "luac51"


def compile_lua(text, tmp):
    src = tmp / "t.lua"
    src.write_text(text, encoding="utf-8", newline="\n")
    out = tmp / "t.luac"
    r = subprocess.run([str(LUAC), "-s", "-o", str(out), str(src)],
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"luac rejected the source: "
                             f"{r.stderr or r.stdout}\n{text}")
    return out.read_bytes()


def key(p):
    return ([i.raw for i in p.code],
            [(c.kind, c.value) for c in p.consts])


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def roundtrip(self, source):
        """source -> bytecode -> source' -> bytecode'. Returns (a, b, src')."""
        bc = compile_lua(source, self.tmp)
        root = nbdec.parse(bc)
        out = nbdec.decompile_proto(root)
        bc2 = compile_lua(out, self.tmp)
        return nbdec.parse(bc), nbdec.parse(bc2), out

    def assertExact(self, source):
        a, b, out = self.roundtrip(source)
        self.assertEqual(key(a), key(b),
                         f"round trip differs\n--- in ---\n{source}\n"
                         f"--- out ---\n{out}")

    # -- the shapes real NB1 scripts are full of ------------------------
    def test_global_assignment(self):
        self.assertExact("FEARSTATE_UNAWARE = engine.eFEARSTATE_UNAWARE\n")

    def test_several_global_assignments(self):
        self.assertExact(
            "A = engine.eA\nB = engine.eB\nC = engine.eC\n")

    def test_statement_call(self):
        self.assertExact("print(1)\n")

    def test_call_with_several_arguments(self):
        self.assertExact('engine.Foo("a", 2, true)\n')

    def test_nested_field_access(self):
        self.assertExact("x = a.b.c.d\n")

    def test_bracket_index_with_string_key(self):
        self.assertExact('x = a["not an identifier"]\n')

    def test_bracket_index_with_global_key(self):
        self.assertExact("x = a[k]\n")

    def test_method_call_statement(self):
        self.assertExact("obj:Method(1, 2)\n")

    def test_arithmetic(self):
        self.assertExact("x = a + b * c\n")

    def test_arithmetic_precedence_needs_parens(self):
        self.assertExact("x = (a + b) * c\n")

    def test_subtraction_is_left_associative(self):
        self.assertExact("x = a - b - c\n")
        self.assertExact("x = a - (b - c)\n")

    def test_concat(self):
        self.assertExact('x = a .. "-" .. b\n')

    def test_unary(self):
        self.assertExact("x = not a\n")
        self.assertExact("x = #a\n")

    def test_local_declaration_and_use(self):
        self.assertExact("local x = 1\nprint(x)\n")

    def test_local_survives_several_statements(self):
        self.assertExact("local x = 1\nprint(x)\nprint(x)\n")

    def test_table_field_assignment(self):
        self.assertExact("a.b = 1\n")

    def test_string_escapes(self):
        self.assertExact('x = "tab\\there"\n')
        self.assertExact('x = "quote\\"here"\n')

    def test_numbers(self):
        self.assertExact("x = 0\ny = 1\nz = 1.5\nw = 1000000\n")

    def test_booleans_and_nil(self):
        self.assertExact("x = true\ny = false\nz = nil\n")

    # -- control flow ---------------------------------------------------
    def test_if_equal(self):
        self.assertExact("if a == b then print(1) end\n")

    def test_if_not_equal(self):
        self.assertExact("if a ~= b then print(1) end\n")

    def test_if_less(self):
        self.assertExact("if a < b then print(1) end\n")
        self.assertExact("if a <= b then print(1) end\n")

    def test_if_greater_is_a_swapped_less(self):
        """Lua has no `>` opcode; luac compiles `a > b` as `b < a` but still
        evaluates a first, so the operand order in the instruction is the
        only record of which way the source was written."""
        self.assertExact("if a > b then print(1) end\n")
        self.assertExact("if a >= b then print(1) end\n")

    def test_comparison_against_a_constant(self):
        self.assertExact("if a > 1 then print(1) end\n")
        self.assertExact("if a < 1 then print(1) end\n")

    def test_constant_on_the_left(self):
        """`1 < a` and `a > 1` produce identical instructions and differ only
        in constant-table order."""
        self.assertExact("if 1 < a then print(1) end\n")

    def test_truthiness_test(self):
        self.assertExact("if a then print(1) end\n")
        self.assertExact("if not a then print(1) end\n")

    def test_if_else(self):
        self.assertExact("if a == b then print(1) else print(2) end\n")

    def test_while(self):
        self.assertExact("while a do print(1) end\n")
        self.assertExact("while a == b do print(1) end\n")

    def test_nested_if(self):
        self.assertExact("if a == b then if c == d then print(1) end end\n")

    def test_statement_after_if(self):
        self.assertExact("if a == b then print(1) end\nprint(2)\n")

    def test_condition_on_a_field(self):
        self.assertExact("if a.b == 1 then x = 2 end\n")

    def test_local_used_in_condition(self):
        self.assertExact("local x = 1\nif x == 2 then print(x) end\n")

    # -- comparisons used as values -------------------------------------
    def test_comparison_as_a_value(self):
        """`x = a == b` is a four-instruction sequence, not a comparison:
        a comparison only controls a jump, so luac materialises the boolean
        with a paired LOADBOOL."""
        self.assertExact("x = a == b\n")
        self.assertExact("x = a ~= b\n")
        self.assertExact("x = a < b\n")

    # -- table constructors ---------------------------------------------
    def test_empty_table(self):
        self.assertExact("x = {}\n")

    def test_array_table(self):
        self.assertExact("x = {1, 2, 3}\n")

    def test_array_of_strings(self):
        self.assertExact('x = {"a", "b"}\n')

    def test_hash_table(self):
        self.assertExact("x = {a = 1, b = 2}\n")

    def test_table_with_quoted_key(self):
        self.assertExact('x = {["not an ident"] = 1}\n')

    def test_nested_table(self):
        self.assertExact("x = {{1, 2}, {3}}\n")

    def test_table_of_globals(self):
        self.assertExact("x = {a, b, c}\n")

    def test_table_with_a_call_inside(self):
        self.assertExact("x = {f(1), 2}\n")

    # -- closures and upvalues ------------------------------------------
    def test_anonymous_function(self):
        self.assertExact("f = function() return 1 end\n")

    def test_function_with_parameters(self):
        self.assertExact("f = function(a, b) return a + b end\n")

    def test_vararg_function(self):
        self.assertExact("f = function(...) return ... end\n")

    def test_method_style_function(self):
        self.assertExact("t.f = function(self, x) return self.y + x end\n")

    def test_closure_capturing_a_local(self):
        """The capture is not in the child at all - it is in the pseudo
        instructions luac emits after CLOSURE in the PARENT."""
        self.assertExact("local x = 1\nf = function() return x end\n")

    def test_closure_assigning_an_upvalue(self):
        self.assertExact("local x = 1\nf = function() x = 2 end\n")

    def test_two_closures_sharing_an_upvalue(self):
        self.assertExact("local x = 1\n"
                         "f = function() return x end\n"
                         "g = function() return x end\n")

    # -- numeric for -----------------------------------------------------
    def test_numeric_for(self):
        self.assertExact("for i = 1, 10 do print(i) end\n")

    def test_numeric_for_with_step(self):
        self.assertExact("for i = 1, 10, 2 do print(i) end\n")

    def test_numeric_for_with_expressions(self):
        self.assertExact("for i = a, b do print(i) end\n")

    def test_numeric_for_body_uses_the_variable(self):
        self.assertExact("for i = 1, 10 do x = i + 1 end\n")

    # -- compound conditions, elseif, break ------------------------------
    def test_and_condition(self):
        """Two tests jumping to the same failure target is one `and`."""
        self.assertExact("if a and b then print(1) end\n")

    def test_or_condition(self):
        """The first test jumps FORWARD into the body when it succeeds."""
        self.assertExact("if a or b then print(1) end\n")

    def test_three_way_and(self):
        self.assertExact("if a and b and c then print(1) end\n")

    def test_compound_comparisons(self):
        self.assertExact("if a == 1 and b == 2 then print(1) end\n")
        self.assertExact("if a == 1 or b == 2 then print(1) end\n")

    def test_elseif(self):
        self.assertExact("if a == 1 then print(1) elseif a == 2 then "
                         "print(2) end\n")

    def test_elseif_else(self):
        self.assertExact("if a == 1 then print(1) elseif a == 2 then "
                         "print(2) else print(3) end\n")

    def test_elseif_chain(self):
        self.assertExact("if a == 1 then x = 1 elseif a == 2 then x = 2 "
                         "elseif a == 3 then x = 3 else x = 4 end\n")

    def test_break_in_while(self):
        self.assertExact("while a do break end\n")

    def test_break_guarded(self):
        self.assertExact("while a do if b then break end print(1) end\n")

    def test_and_in_while(self):
        self.assertExact("while a and b do print(1) end\n")

    # -- repeat / until and generic for ----------------------------------
    def test_repeat_until(self):
        """The only structure whose condition is at the BOTTOM, jumping back
        to the top while it is still false."""
        self.assertExact("repeat print(1) until a\n")

    def test_repeat_until_comparison(self):
        self.assertExact("repeat x = x + 1 until x == 10\n")

    def test_generic_for(self):
        self.assertExact("for k, v in pairs(t) do print(k) end\n")

    def test_generic_for_one_variable(self):
        self.assertExact("for k in pairs(t) do print(k) end\n")

    def test_generic_for_body_uses_both(self):
        self.assertExact("for k, v in pairs(t) do x = k end\n")

    # -- table constructor boundaries ---------------------------------------
    def test_open_table_constructor(self):
        """`{f()}`: the open last item is not counted in NEWTABLE's size."""
        self.assertExact("x = {f()}\n")

    def test_open_after_fixed_items(self):
        self.assertExact("x = {1, 2, f()}\n")

    def test_nested_open_constructors(self):
        """From naughtyisland_npcs_combat."""
        self.assertExact("local t = {{Q()}, {H()}}\nR(1, t)\n")

    def test_statements_after_empty_table(self):
        """From characterclasses: `local self = {}` followed by field
        stores that look exactly like more constructor items."""
        self.assertExact("local s = {}\nsetmetatable(s, C)\n"
                         "s.a = {}\ns.a[J] = s.b\nreturn s\n")

    def test_statement_after_keyed_table(self):
        self.assertExact("local t = {a = 1}\nt.b = 2\nreturn t\n")

    def test_large_keyed_table(self):
        """Nine or more keyed items: the size is stored rounded."""
        fields = ", ".join(f"f{n} = {n}" for n in range(11))
        self.assertExact(f"local t = {{{fields}}}\nt.z = 1\nreturn t\n")

    def test_mixed_array_and_keyed_order(self):
        self.assertExact("x = {1, a = 2, 3, b = f(), g()}\n")

    def test_computed_keys(self):
        self.assertExact("x = {[k] = 1, [k .. 'x'] = 2}\n")

    def test_many_array_items(self):
        """Over 50 array items is more than one SETLIST batch."""
        items = ", ".join(str(n) for n in range(120))
        self.assertExact(f"x = {{{items}}}\n")

    def test_value_expression_in_constructor(self):
        self.assertExact("x = {a = b or c, d == e}\n")

    # -- locals the bytecode only implies -----------------------------------
    def test_local_read_only_by_a_condition(self):
        self.assertExact("local v = f()\nif v ~= -1 then end\n"
                         "if w ~= -1 then end\n")

    def test_local_first_read_inside_loop(self):
        """From librarytables: `local count = 0` is not read until a loop
        body several statements later."""
        self.assertExact("local c = 0\nif type(t) == 'table' then\n"
                         "  for i, j in pairs(t) do c = c + 1 end\nend\n"
                         "return c\n")

    def test_local_reassigned_in_branch(self):
        """From librarymath Round()."""
        self.assertExact("local a, b = math.modf(n)\nlocal r = a\n"
                         "if b >= 0.5 then r = a + 1 end\nreturn r\n")

    def test_local_nil(self):
        self.assertExact("print(1)\nlocal p = nil\n"
                         "if a then p = 1 else p = 2 end\nreturn p\n")

    def test_local_declared_without_value_at_start(self):
        self.assertExact("local p\nif a then p = 1 end\nreturn p\n")

    def test_sibling_scopes_reuse_a_register(self):
        self.assertExact("if a then local x = f() g(x) else "
                         "local y = h() g(y) end\n")

    def test_local_used_twice(self):
        self.assertExact("local x = f()\ny = x\nz = x\n")

    def test_method_call_with_nested_call_argument(self):
        self.assertExact("local c = f()\nc:S(c, engine.V(0.75, 0.25, 0))\n")

    # -- features found in real NB1 chunks -------------------------------------
    def test_vararg_implicit_arg(self):
        """From libraryerrors: Lua 5.1 gives a `...` function a hidden
        local `arg`; declaring it again shifts every register."""
        self.assertExact("function F(c, ...)\n"
                         "  if T[c] == nil then T[c] = true end\n"
                         "  for i, v in pairs({...}) do print(v) end\n"
                         "end\n")

    def test_vararg_arg_used_by_name(self):
        """From librarymath: the old-style `arg` table read directly."""
        self.assertExact("function R(...)\n  if arg.n == nil then return 1 end\n"
                         "  return arg[1]\nend\n")

    def test_local_function_recursive(self):
        """From librarytables deepcopy: `local function` captures itself."""
        self.assertExact("function C(o)\n  local seen = {}\n"
                         "  local function copy(x)\n"
                         "    if type(x) ~= 'table' then return x end\n"
                         "    local n = {}\n    seen[x] = n\n"
                         "    for k, v in pairs(x) do n[copy(k)] = copy(v) end\n"
                         "    return n\n  end\n  return copy(o)\nend\n")

    def test_multiple_assignment_from_call(self):
        """From aiglobal: `s, e = src:find(' ')` into globals."""
        self.assertExact("local src = f()\ns, e = src:find(' ')\n"
                         "print(s, e)\n")

    def test_multiple_assignment_values(self):
        self.assertExact("a, b = 1, f()\n")

    def test_multiple_assignment_swap_locals(self):
        self.assertExact("local a, b = f()\na, b = b, a\nprint(a, b)\n")

    def test_multiple_assignment_fields(self):
        self.assertExact("t.x, t.y = g(), 2\n")

    def test_local_returned_from_call(self):
        """From eventdrivenconditionalsystem: `local v = f(); return v`
        is not `return f(v)`, which luac compiles as a tail call."""
        self.assertExact("function U(x)\n  local v = engine.P(1, x)\n"
                         "  return v\nend\n")

    def test_nested_local_shadowing_upvalue(self):
        """From librarycustomization: a local in an inner function must not
        take the same name as a captured outer one."""
        self.assertExact("local S = 0\nfunction G()\n  local id = S\n"
                         "  S = S + 1\n  return id\nend\n")

    # -- evidence that lives only in the constant table / register order -----
    def test_local_then_global_assignment(self):
        """From NB1 basecharacterbodystatemachine: `local x = r:F("A");
        a = x` compiles to the same instructions as `a = r:F("A")`; only
        the constant order (value parsed before the target's name) differs."""
        self.assertExact('local r = G(T, "C"):R()\nif r ~= nil then\n'
                         '  local x = r:F("A")\n  a = x\nelse\n  a = 1.5\nend\n')

    def test_extra_value_dropped(self):
        """From NB1 barricade: `cur = "h", 1` evaluates 1 and drops it."""
        self.assertExact('if b == nil then cur = "h", 1 else cur = "g", 2 end\n'
                         'P(cur)\n')

    def test_value_computed_before_table(self):
        """From librarymonitoring: `local x = Bool(...); T[k] = x`."""
        self.assertExact("local T = {}\nfunction C(k)\n"
                         "  if T[k] == nil then\n"
                         "    local b = Bool(S('p' .. k), false)\n"
                         "    T[k] = b\n  end\n  return E(T[k], true)\nend\n")

    def test_key_computed_before_table(self):
        """From libraryweapon: `local i = n + 1; t[i] = {...}`."""
        self.assertExact("function A(a, b)\n  local i = (table.getn(_G.T)) + 1\n"
                         "  _G.T[i] = {a, b}\nend\n")

    def test_locals_declared_at_function_start(self):
        """From manageyields: `local a, b, c, d` then assignments."""
        self.assertExact("function W(s)\n  local u, st, ty, d\n  u = false\n"
                         "  st = true\n  if os.time() > s.d then\n    u = true\n"
                         "    st, ty, d = coroutine.resume(s.s)\n  end\n"
                         "  return u, st, ty, d\nend\n")

    def test_and_value_returned(self):
        """From naughtybearbodystatemachine: a call's value reaching RETURN
        through `and` is not a local."""
        self.assertExact("function I()\n  return E.M() and G(T):I()\nend\n")

    def test_assignment_before_elseif_chain(self):
        """From NB1 libraryweapon: an else branch that assigns and THEN
        starts an if/elseif chain must not become an `elseif` - that
        swallowed the assignment."""
        self.assertExact("local w, v\nif T[k] ~= nil then\n  v = T[k]\nelse\n"
                         "  v = 'demo_' .. k\n  if k == 'a' then v = 'x'\n"
                         "  elseif k == 'b' then v = 'y' end\nend\nreturn v\n")

    def test_value_tested_twice_in_one_condition(self):
        """From librarymath Bitxor: `(a and not b) or (not a and b)`."""
        self.assertExact("function X(x, y)\n  local a = H(x)\n  local b = H(y)\n"
                         "  if (a and not b) or (not a and b) then z = 1 end\nend\n")

    def test_and_value_then_tested(self):
        """From naughtybearbodystatemachine_combat: a value built with
        and/not, then tested by a later condition, is one local."""
        self.assertExact("function P(h, B, u)\n  local d = G(B)\n"
                         "  local inAir = h.a:V() and not h.b:V()\n"
                         "  if d <= u[1] and (not inAir) then m = true end\nend\n")

    def test_method_name_constant_past_255(self):
        """From NB1 init_unlockable: with over 256 constants the method
        name is loaded into a register after SELF's two are reserved."""
        lines = [f"x{n} = {n + 0.5}" for n in range(300)]
        lines.append("local o = f()\no:EnableHat(1, 2)\ng(1)")
        self.assertExact("\n".join(lines) + "\n")

    # -- found by the full-game bench ------------------------------------------
    def test_locals_between_nested_ifs_ending_together(self):
        """From NB1 ep10achievements: two ifs ending at the same place
        compile like `if a and b`, unless the inner one's body starts by
        declaring locals its condition then uses."""
        self.assertExact("function F(e)\n  if e ~= nil then\n"
                         "    local a = e:GetAttacker()\n    if a ~= nil then\n"
                         "      local n = G(a):GetName()\n"
                         "      local h = R:GetCostume():GetHashName()\n"
                         "      if n ~= H(S.name) or h == 92716849 then end\n"
                         "    end\n  end\nend\n")

    def test_constant_written_first_in_comparison(self):
        """From NB1 level loaders: `0.5 < GetRandomNumber()` allocates 0.5
        first; `GetRandomNumber() > 0.5` would compile the same
        instruction with the constants the other way round."""
        self.assertExact("if 0.5 < GetRandomNumber() then a() else b() end\n")
        self.assertExact("if GetRandomNumber() > 0.5 then a() else b() end\n")
        self.assertExact("if 1 > f() then a() end\n")
        self.assertExact("if f() < 1 then a() end\n")

    # -- and/or producing a VALUE -----------------------------------------
    def test_or_value(self):
        self.assertExact("x = a or b\n")

    def test_and_value(self):
        self.assertExact("x = a and b\n")

    def test_and_or_idiom(self):
        """The ternary idiom: `c and x or y`."""
        self.assertExact("x = c and 1 or 2\n")

    def test_or_of_and(self):
        self.assertExact("x = a or (b and c)\n")

    def test_and_of_or(self):
        self.assertExact("x = (a or b) and c\n")

    def test_value_into_local(self):
        self.assertExact("local x = a or b\nprint(x)\n")

    def test_value_as_argument(self):
        self.assertExact("f(a or b, c)\n")

    def test_value_with_testset(self):
        """TESTSET only appears when the result lands in a register other
        than the operand's own, here a field read into a fresh temporary."""
        self.assertExact("local t = {}\nlocal y = t.a or t.b\nprint(y)\n")

    def test_comparison_or_value(self):
        """From libraryunlockable: a comparison inside an `or` value needs
        the LOADBOOL pair as well as the value exit."""
        self.assertExact("f(d.x == nil or d.x)\n")

    def test_not_value(self):
        self.assertExact("x = not a or b\n")

    def test_comparison_and_comparison_value(self):
        self.assertExact("x = a < b and c ~= d\n")

    def test_or_value_inside_condition(self):
        self.assertExact("if f(a or b) then print(1) end\n")

    def test_or_value_in_return(self):
        self.assertExact("return a or b\n")

    # -- jump threading -----------------------------------------------------
    def test_if_else_at_end_of_while(self):
        """From naughtybearadditivestatemachine: the then-branch's escape
        jump is merged into the loop's back jump and goes straight to the
        head."""
        self.assertExact("while true do\n"
                         "  local a = f()\n"
                         "  if a ~= nil then g(a) else h() end\n"
                         "end\n")

    def test_nested_if_else_threaded(self):
        """From ambiencetrigger: an inner if/else at the end of an outer
        then-branch escapes straight past the outer else."""
        self.assertExact("if a then\n"
                         "  print(1)\n"
                         "  if b then f() else g() end\n"
                         "else\n"
                         "  print(2)\n"
                         "  if b then h() else k() end\n"
                         "end\n")

    def test_returns_in_both_branches(self):
        """From rumblemanager: returns inside nested if/else."""
        self.assertExact("function F(a, b)\n"
                         "  if b ~= nil then\n"
                         "    if a:IsLocal() == true then return m:S(a) else return 0 end\n"
                         "  else\n"
                         "    return m:S(a)\n"
                         "  end\n"
                         "end\n")

    def test_if_at_end_of_while(self):
        self.assertExact("while x do if a then f() end end\n")

    def test_while_true(self):
        self.assertExact("while true do f() end\n")

    def test_nested_while(self):
        self.assertExact("while a do while b do f() end end\n")

    def test_if_then_break_after_else(self):
        self.assertExact("while a do if b then f() else g() end break end\n")

    def test_break_in_numeric_for(self):
        self.assertExact("for i = 1, 10 do if t[i] then break end end\n")

    def test_elseif_after_statements(self):
        self.assertExact("if a then f() elseif b == 1 then g() "
                         "elseif c then h() else k() end\n")

    def test_compound_nested_condition(self):
        self.assertExact("if a and (b or c) then f() end\n")

    def test_not_condition(self):
        self.assertExact("if not a then f() end\n")

    def test_repeat_with_or(self):
        self.assertExact("repeat f() until a or b\n")

    def test_repeat_with_local(self):
        self.assertExact("repeat local x = g() until x\n")

    def test_function_with_a_body(self):
        self.assertExact("f = function(a)\n"
                         "  if a == 1 then return 2 end\n"
                         "  return 3\n"
                         "end\n")


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class RefusesWhatItCannotDo(unittest.TestCase):
    """Unimplemented constructs must raise, never guess."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def assertRefuses(self, source):
        bc = compile_lua(source, self.tmp)
        root = nbdec.parse(bc)
        with self.assertRaises(nbdec.Unsupported):
            nbdec.decompile_proto(root)

    def test_jump_no_compiler_would_emit(self):
        """A forward JMP that skips half a statement matches no Lua
        construct. The decompiler must say so rather than drop it."""
        bc = bytearray(compile_lua("x = 1\ny = 2\n", self.tmp))
        root = nbdec.parse(bytes(bc))
        first = root.code[0]
        self.assertEqual(first.op, "LOADK")
        # JMP +1 (sBx is stored excess-131071 in the Bx field)
        jmp = nbdec.OP["JMP"] | ((1 + 131071) << 14)
        at = bytes(bc).find(first.raw.to_bytes(4, "little"))
        bc[at:at + 4] = jmp.to_bytes(4, "little")
        with self.assertRaises(nbdec.Unsupported):
            nbdec.decompile_proto(nbdec.parse(bytes(bc)))



@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class Readability(unittest.TestCase):
    """The output is for people to edit, so names and shapes matter - but
    every one of these must still round-trip exactly."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def decompile(self, source, **kw):
        bc = compile_lua(source, self.tmp)
        out = nbdec.decompile_proto(nbdec.parse(bc), **kw)
        again = compile_lua(out, self.tmp)
        self.assertEqual([key(p) for p in nbdec.parse(bc).walk()],
                         [key(p) for p in nbdec.parse(again).walk()],
                         f"round trip differs\n{out}")
        return out

    def test_top_level_not_indented(self):
        self.assertTrue(self.decompile("x = 1\n").startswith("x = 1"))

    def test_function_statement(self):
        out = self.decompile("function F(a) return a end\n")
        self.assertIn("function F(", out)

    def test_method_statement_names_self(self):
        out = self.decompile("T = {}\nfunction T:Get() return self.v end\n")
        self.assertIn("function T:Get()", out)
        self.assertIn("self.v", out)

    def test_plain_field_function_stays_dotted(self):
        """A first parameter never used as an object is not `self`."""
        out = self.decompile("T = {}\nfunction T.Add(a, b) return a + b end\n")
        self.assertIn("function T.Add(", out)

    def test_local_named_after_call(self):
        out = self.decompile("local o = GetSpatialObject(e)\no:A()\no:B()\n")
        self.assertIn("local spatialObject = GetSpatialObject(e)", out)

    def test_local_named_after_component_string(self):
        out = self.decompile('local c = GetComponent(e, "Fear Component")\n'
                             'c:A()\nc:B()\n')
        self.assertIn("local fearComponent = ", out)

    def test_parameter_named_after_field(self):
        out = self.decompile("T = {}\nfunction T:Set(x) self.threatLevel = x end\n")
        self.assertIn("function T:Set(threatLevel)", out)

    def test_loop_variables(self):
        out = self.decompile("for k, v in pairs(t) do print(k, v) end\n"
                             "for i, v in ipairs(t) do print(i, v) end\n"
                             "for i = 1, 3 do print(i) end\n")
        self.assertIn("for k, v in pairs(t)", out)
        self.assertIn("for i, v in ipairs(t)", out)
        self.assertIn("for i = 1, 3", out)

    def test_valueless_local_named_by_first_assignment(self):
        out = self.decompile("print(1)\nlocal a, b\nif c then a = GetGSLoading() "
                             "else a = G() end\nb = a.X\nreturn a, b\n")
        self.assertIn("local gsLoading", out)
        self.assertNotIn("\x01", out)

    def test_captured_valueless_local_not_shadowed(self):
        """Regression: a closure captured a local still waiting for its
        name; the closure's own local then took the same final name and
        shadowed it."""
        self.decompile("print(1)\nlocal a\nf = function() local foo = GetFoo() "
                       "return foo, a end\na = GetFoo()\nprint(a)\n")

    def test_locals_never_shadow_globals(self):
        out = self.decompile("local t = GetT()\nt:A()\nt:B()\nprint(T, t)\n"
                             "tbl = 1\n")
        for line in out.splitlines():
            self.assertFalse(line.startswith("local tbl "), out)

    def test_hash_constants_named(self):
        out = self.decompile("x = 773742806\n",
                             hash_names={773742806: "Damage_Head"})
        self.assertIn('--[[HASH:"Damage_Head"]]0x2e1e60d6', out)

    def test_text_id_labelled_with_its_display_text(self):
        """A hash with localized text shows the text, made safe for a
        one-line comment, alongside its name when that is known too."""
        out = self.decompile(
            "a = Objective(2170742641)\nb = Objective(773742806)\n",
            hash_names={773742806: "Damage_Head"},
            hash_text={2170742641: 'Cross the "Bridge"\nnow]]',
                       773742806: "ignored"})
        self.assertIn("""--[[TEXT:"Cross the 'Bridge' / now] ]"]]0x8162e771""",
                      out)
        # both a name and text: show both
        self.assertIn('--[[HASH:"Damage_Head" TEXT:"ignored"]]0x2e1e60d6', out)

    def test_round_integer_is_a_number_not_a_hash(self):
        """NB1 keeps big integers (score thresholds) in the hash type; a
        round one with no name prints as the number it is."""
        out = self.decompile("if s >= 250000000 then f() end\n",
                             hash_values={250000000})
        self.assertIn("250000000", out)
        self.assertNotIn("0x0ee6b280", out)

    def test_nb2_text_is_marked_as_nb2(self):
        """NB2's text can label an NB1 hash (the games share text IDs), but
        its wording can differ, so it is marked as NB2's."""
        out = self.decompile("a = Objective(2170742641)\nb = Objective(1381353472)\n",
                             hash_text={2170742641: ("The Disco", "NB2"),
                                        1381353472: ("Own text", "NB1")})
        self.assertIn('--[[TEXT(NB2):"The Disco"]]0x8162e771', out)
        self.assertIn('--[[TEXT:"Own text"]]0x5255c800', out)

    def test_nb1_double_spelled_with_a_point(self):
        """NB1 keeps integer literals as 0xFE and `20.0` as a double; the
        output spells each the way the compiler decided."""
        out = self.decompile("x = 20\ny = 25\n",
                             fe_values={"0": {25}})
        self.assertIn("x = 20.0", out)
        self.assertIn("y = 25", out)


@unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
class NumberTypes(unittest.TestCase):
    """Putting NB1's 0xFE integer type back after compiling with luac51."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def lined(self, source):
        src = self.tmp / "l.lua"
        src.write_text(source, encoding="utf-8", newline="\n")
        out = self.tmp / "l.luac"
        subprocess.run([str(LUAC), "-o", str(out), str(src)], check=True)
        return nbdec.parse(out.read_bytes())

    def test_scanner_skips_strings_and_comments(self):
        src = ('x = 20.0 -- 5\ny = "7" .. 3\nz = [[9]] + 0x1F + .5 + 1e3\n'
               'local abc1 = 4 --[[ 6 ]] w = 8\n')
        self.assertEqual(nbdec.number_tokens(src),
                         [(1, "20.0"), (2, "3"), (3, "0x1F"), (3, ".5"),
                          (3, "1e3"), (4, "4"), (4, "8")])

    def test_spelling_decides_type(self):
        src = "a = 20\nb = 30.0\nc = -1\nd = 0x2e1e60d6\n"
        ints = nbdec.integer_constants(src, self.lined(src))["0"]
        self.assertEqual(ints, {20, -1, 773742806})

    def test_original_type_wins_for_existing_constants(self):
        src = "a = 20\nb = 7\n"
        root = self.lined(src)
        got = nbdec.fe_numbers(src, root, ({"0": set()}, {"0": {20}}))
        self.assertEqual(got["0"], {7})     # 20 was a double originally

    def test_convert_emits_0xfe(self):
        sys.path.insert(0, str(TOOLS))
        import struct
        import lua_recompile
        bc = compile_lua("a = 20\nb = 1.5\n", self.tmp)
        out = lua_recompile.convert(bc, fe_numbers={"0": {20}})
        self.assertIn(b"\xfe" + struct.pack("<q", 20), out)
        self.assertIn(b"\x03" + struct.pack("<d", 1.5), out)


class Reconstruction(unittest.TestCase):
    """nb_reconstruct keeps a name only when its CRC32 matches exactly."""

    def setUp(self):
        import nb_reconstruct
        self.R = nb_reconstruct

    def test_variable_name_rule(self):
        h = self.R.crc("LibraryLoading_bIsLoadingInProgress")
        text = f"LibraryLoading.bIsLoadingInProgress = Bool(0x{h:08x}, false)\n"
        got = dict(self.R.rule_variable_names(text, "x", "y"))
        self.assertIn("LibraryLoading_bIsLoadingInProgress", got[h])

    def test_npc_rule(self):
        h = self.R.crc("npc_names_Vampire_Bearcula")
        text = f'X = NPCDef("Vampire Bearcula", 0x{h:08x}, 1)\n'
        got = dict(self.R.rule_npc_names(text, "x", "y"))
        self.assertIn("npc_names_Vampire_Bearcula", got[h])

    def test_numbered_siblings_keep_padding(self):
        sib = self.R.numbered_siblings("loading_hint_hint07", top=12)
        self.assertIn("loading_hint_hint12", sib)
        self.assertIn("loading_hint_hint03", sib)
        self.assertNotIn("loading_hint_hint07", sib)

    def test_constructed_thing_named_after_its_variable(self):
        h = self.R.crc("bloodNPC")
        text = f"effect_bloodNPC = engine.EffectDefinition_Create(0x{h:08x})\n"
        got = dict(self.R.rule_constructed_names(text, "x", "y"))
        self.assertIn("bloodNPC", got[h])

    def test_self_named_constant(self):
        h = self.R.crc("FirearmAimingAnim")
        text = f"ATTRIBUTE_FIREARM_AIMING_ANIM_HASH = 0x{h:08x}\n"
        got = dict(self.R.rule_self_names(text, "x", "y"))
        self.assertTrue(any(self.R.crc(c) == h for c in got[h]))

    def test_unlock_condition(self):
        h = self.R.crc("unlockable_condition_ep2cha4_gold")
        text = f'c = {{0x{h:08x}, "Ep2Cha4", engine.eGOLD_GRADE}}\n'
        got = dict(self.R.rule_unlock_conditions(text, "x", "y"))
        self.assertIn("unlockable_condition_ep2cha4_gold", got[h])

    def test_template_variants_keep_the_developers_casing(self):
        v = self.R.template_variants("ST_SitIn", {"out"})
        self.assertIn("ST_SitOut", v)

    def test_constant_mapping_learned_from_named_neighbours(self):
        maps = self.R.learn_mappings([
            ("FEAR_SCARE_TOILET", "demo_fearevent_scare_toilet"),
            ("FEAR_SCARE_SINK", "demo_fearevent_scare_sink")])
        self.assertEqual(maps[(("fear",), "demo_fearevent_", "_")], 2)

    def test_siblings_only_against_their_own_container(self):
        known = {self.R.crc("loading_hint_hint01"): "loading_hint_hint01"}
        target = self.R.crc("loading_hint_hint02")
        conts = {"loadingscreen": {self.R.crc("loading_hint_hint01"), target},
                 "other": {self.R.crc("loading_hint_hint03")}}
        found, _, _ = self.R.text_container_siblings(conts, known)
        self.assertEqual(found, {target: "loading_hint_hint02"})

    def test_text_id_named_with_the_words_of_its_own_text(self):
        toilet = self.R.crc("demo_fearevent_disabled_toilet")
        sink = self.R.crc("demo_fearevent_disabled_sink")
        trap = self.R.crc("hudbutton_settrap")
        conts = {"levelcommon.en_us": {toilet, sink, trap}}
        texts = {sink: "You sabotaged the sink!", trap: "SET TRAP",
                 toilet: "You sabotaged the toilet!"}
        known = {toilet: "demo_fearevent_disabled_toilet"}
        found, _ = self.R.rule_text_words(conts, texts, known)
        self.assertEqual(found, {sink: "demo_fearevent_disabled_sink"})
        known[self.R.crc("hudbutton_flush")] = "hudbutton_flush"
        conts["levelcommon.en_us"].add(self.R.crc("hudbutton_flush"))
        found, _ = self.R.rule_text_words(conts, texts, known)
        self.assertEqual(found[trap], "hudbutton_settrap")

    def test_unappend_gives_the_prefix_hash(self):
        h = self.R.crc("ep1_cha1_objectives_obj3")
        self.assertEqual(self.R.unappend(h, "3"),
                         self.R.crc("ep1_cha1_objectives_obj"))
        self.assertEqual(self.R.unappend(h, "_obj3"),
                         self.R.crc("ep1_cha1_objectives"))

    def test_numbered_family_found_before_its_prefix_is_known(self):
        members = {self.R.crc(f"ST_N{n}") for n in range(10)}
        noise = {self.R.crc("ST_Idle"), self.R.crc("ST_Run")}
        fams = self.R.numbered_families(members | noise)
        self.assertIn((self.R.crc("ST_N"), "{}", 0), fams)
        self.assertEqual(set(fams[(self.R.crc("ST_N"), "{}", 0)].values()),
                         members)

    def _folder(self, files):
        import tempfile
        d = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (d / name).write_text(text, encoding="utf-8")
        return d

    def test_array_slot_variable_uses_the_owner_of_named_neighbours(self):
        known = "MonitoringUtilMP_iCollectedJelly_Variable"
        h = self.R.crc("MonitoringUtilMP_iDancingTime2_Variable")
        text = (f'self.iCollectedJelly = Int(--[[HASH:"{known}"]]0x{self.R.crc(known):08x}, 0)\n'
                f"self.iDancingTime[2] = Int(0x{h:08x}, 0)\n")
        got = dict(self.R.rule_variable_names(self.R.unlabelled_text(text), "x", "y"))
        self.assertIn("MonitoringUtilMP_iDancingTime2_Variable", got[h])

    def test_line_words_rebuild_an_id_from_its_own_line(self):
        h = self.R.crc("achievement_JELLYWARS")
        d = self._folder({"achievements.lua":
                          f"m:AddAchievement(engine.eACHIEVEMENT_JELLYWARS, 0x{h:08x})\n"})
        found, pairs = self.R.rule_line_words(d, {h}, {})
        self.assertEqual(self.R.crc(found[h]), h)
        self.assertGreater(pairs, 0)

    def test_object_actions_learned_from_known_names(self):
        known = {self.R.crc(n): n for n in ("ST_CScareCooler", "ST_StealthKilledFridge")}
        h = self.R.crc("ST_StealthKilledCooler")
        d = self._folder({"beercooler_receivestealthkill.lua": f"v4 = 0x{h:08x}\n"})
        found, _ = self.R.rule_object_actions(d, {h}, known)
        self.assertEqual(found, {h: "ST_StealthKilledCooler"})

    def test_verify_rebuilds_hidden_names_from_the_found_ones(self):
        found = ("ST_CScareCooler", "ST_StealthKilledFridge")
        hidden = "ST_StealthKilledCooler"
        known = {self.R.crc(n): n for n in found + (hidden,)}
        tiers = {self.R.crc(n): "found" for n in found}
        tiers[self.R.crc(hidden)] = "searched"
        d = self._folder({"beercooler_receivestealthkill.lua":
                          f"v4 = 0x{self.R.crc(hidden):08x}\n"})
        r = self.R.verify(d, None, (), known, tiers, log=lambda *a: None)
        self.assertEqual(r["same"], {self.R.crc(hidden)})
        self.assertEqual(r["different"], {})

    def test_sources_round_trip(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "sources.json"
        self.R.nb_names.save_sources({1: "found", 2: "review"}, {2: "why"}, path=p)
        self.assertEqual(self.R.nb_names.load_sources(p),
                         ({1: "found", 2: "review"}, {2: "why"}))

    def test_prefix_held_in_a_local_before_concatenation(self):
        raw = ('local str = "naughty_conkill_"\n'
               "str = str .. objectName\n")
        self.assertIn("naughty_conkill_", self.R.concat_prefixes(raw))


class Parser(unittest.TestCase):
    def test_rejects_non_lua(self):
        with self.assertRaises(nbdec.BytecodeError):
            nbdec.parse(b"not bytecode at all")

    def test_rejects_wrong_version(self):
        data = bytearray(b"\x1bLua\x52\x00\x01\x04\x04\x04\x08\x00")
        with self.assertRaises(nbdec.BytecodeError):
            nbdec.parse(bytes(data))

    @unittest.skipUnless(LUAC.exists(), "luac5.1 not available")
    def test_reads_every_field(self):
        tmp = Path(tempfile.mkdtemp())
        bc = compile_lua("local function f(a, b, ...) return a + b end\n"
                         "return f\n", tmp)
        root = nbdec.parse(bc)
        self.assertEqual(len(root.protos), 1)
        fn = root.protos[0]
        self.assertEqual(fn.numparams, 2)
        self.assertTrue(fn.is_vararg)
        self.assertGreater(len(fn.code), 0)
        self.assertEqual(fn.path, "0_0")


class NumberFormatting(unittest.TestCase):
    def test_integers_render_without_a_point(self):
        self.assertEqual(nbdec.format_number(1.0), "1")
        self.assertEqual(nbdec.format_number(-25.0), "-25")
        self.assertEqual(nbdec.format_number(1000000.0), "1000000")

    def test_fractions_survive(self):
        self.assertEqual(float(nbdec.format_number(1.5)), 1.5)
        self.assertEqual(float(nbdec.format_number(0.1)), 0.1)


class StringQuoting(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(nbdec.quote(b"abc"), '"abc"')

    def test_escapes(self):
        self.assertEqual(nbdec.quote(b'a"b'), '"a\\"b"')
        self.assertEqual(nbdec.quote(b"a\nb"), '"a\\nb"')
        self.assertEqual(nbdec.quote(b"a\\b"), '"a\\\\b"')

    def test_non_ascii_bytes_are_numeric_escapes(self):
        self.assertEqual(nbdec.quote(b"\xe8"), '"\\232"')

    def test_identifier_check(self):
        for good in ("abc", "_x", "a1", "InitFears"):
            self.assertTrue(nbdec.is_identifier(good), good)
        for bad in ("", "1a", "a-b", "end", "local", "a b"):
            self.assertFalse(nbdec.is_identifier(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
