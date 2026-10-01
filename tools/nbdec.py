#!/usr/bin/env python3
r"""Lua 5.1 decompiler built for Naughty Bear's scripts."""
import argparse
import re
import struct
import sys
from pathlib import Path

# --------------------------------------------------------------- opcodes
OPNAMES = [
    "MOVE", "LOADK", "LOADBOOL", "LOADNIL", "GETUPVAL", "GETGLOBAL",
    "GETTABLE", "SETGLOBAL", "SETUPVAL", "SETTABLE", "NEWTABLE", "SELF",
    "ADD", "SUB", "MUL", "DIV", "MOD", "POW", "UNM", "NOT", "LEN",
    "CONCAT", "JMP", "EQ", "LT", "LE", "TEST", "TESTSET", "CALL",
    "TAILCALL", "RETURN", "FORLOOP", "FORPREP", "TFORLOOP", "SETLIST",
    "CLOSE", "CLOSURE", "VARARG",
]
OP = {name: i for i, name in enumerate(OPNAMES)}

# instruction layouts (lopcodes.h): iABC, iABx, iAsBx
ABX = {"LOADK", "GETGLOBAL", "SETGLOBAL", "CLOSURE"}
ASBX = {"JMP", "FORLOOP", "FORPREP"}
BITRK = 1 << 8          # RK operands >= 256 index the constant table


class Instr:
    __slots__ = ("pc", "op", "A", "B", "C", "Bx", "sBx", "raw")

    def __init__(self, pc, raw):
        self.pc = pc
        self.raw = raw
        self.op = OPNAMES[raw & 0x3F]
        self.A = (raw >> 6) & 0xFF
        self.C = (raw >> 14) & 0x1FF
        self.B = (raw >> 23) & 0x1FF
        self.Bx = (raw >> 14) & 0x3FFFF
        self.sBx = self.Bx - 131071

    def __repr__(self):
        if self.op in ABX:
            return f"{self.pc:>4} {self.op:<10} A={self.A} Bx={self.Bx}"
        if self.op in ASBX:
            return f"{self.pc:>4} {self.op:<10} A={self.A} sBx={self.sBx}"
        return (f"{self.pc:>4} {self.op:<10} A={self.A} B={self.B} "
                f"C={self.C}")


# ----------------------------------------------------------------- values
class Const:
    """A Lua 5.1 constant. `kind` is nil / bool / number / string."""
    __slots__ = ("kind", "value")

    def __init__(self, kind, value=None):
        self.kind = kind
        self.value = value

    def source(self):
        if self.kind == "nil":
            return "nil"
        if self.kind == "bool":
            return "true" if self.value else "false"
        if self.kind == "number":
            return format_number(self.value)
        return quote(self.value)

    def __repr__(self):
        return f"<{self.kind} {self.value!r}>"


def format_number(x):
    """Render a Lua number the way luac will read back identically."""
    if x != x:
        return "(0/0)"
    if x == float("inf"):
        return "(1/0)"
    if x == float("-inf"):
        return "(-1/0)"
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    return repr(x)


_ESCAPES = {ord("\\"): "\\\\", ord('"'): '\\"', ord("\n"): "\\n",
            ord("\r"): "\\r", ord("\t"): "\\t", 0: "\\0"}


def quote(b):
    """A Lua string literal for these exact bytes."""
    if isinstance(b, str):
        b = b.encode("latin-1", "replace")
    out = ['"']
    for byte in b:
        if byte in _ESCAPES:
            out.append(_ESCAPES[byte])
        elif 32 <= byte < 127:
            out.append(chr(byte))
        else:
            out.append(f"\\{byte}")
    out.append('"')
    return "".join(out)


IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
IDENT_REST = IDENT_START | set("0123456789")
KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for",
            "function", "if", "in", "local", "nil", "not", "or", "repeat",
            "return", "then", "true", "until", "while"}


def is_identifier(s):
    if not s or s[0] not in IDENT_START or s in KEYWORDS:
        return False
    return all(c in IDENT_REST for c in s)


# ------------------------------------------------------------- local names
# Stripped bytecode keeps no local names at all, so every name here is
# invented - and free: a local's name is not in the compiled function, so
# nothing a name is chosen from can change the bytecode. The one thing a
# name must never do is shadow something the code refers to (a global, a
# captured upvalue, another local in scope); that WOULD change the bytecode,
# and the round-trip check would catch it.
#
# Names come from what the local is first given, the way a person would
# name it: `GetSpatialObject(x)` -> spatialObject,
# `GetComponent(x, "Fear Component")` -> fearComponent.
HASH_FLOOR = 10 ** 7          # 0xFE values below this are plain integers
VERBS = ("Get", "Create", "Find", "New", "Alloc", "Make", "Obtain",
         "Retrieve", "Acquire", "Build", "Load", "Compute", "Calc")
# callee names that say nothing about the value; an argument usually does
GENERIC = {"Instance", "InstanceMgr", "InstancePtr", "Ptr", "Value",
           "Result", "Data", "Component", "Script", "Interface", "Object",
           "Mgr", "Cast", "Int", "Bool", "Float", "String", "Uint32",
           "UInt32", "Vector", "Vector4", "require"}
_HASH_NOTE = re.compile(r'--\[\[HASH:"([^"]+)"\]\]')
_STRING_LIT = re.compile(r'^"([^"\\]*)"$')
_CONST_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
PATH_RE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")


def camel(text):
    """lowerCamelCase identifier from arbitrary text, or None."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if not words:
        return None
    first = words[0]
    run = re.match(r"[A-Z]+", first)
    if run:
        n = len(run.group())
        if n == len(first):
            first = first.lower()                 # GOD -> god
        elif n == 1:
            first = first[0].lower() + first[1:]  # Spatial -> spatial
        else:
            first = first[:n - 1].lower() + first[n - 1:]  # UIDArray -> uidArray
    out = first + "".join(
        w.capitalize() if w.isupper() else w[0].upper() + w[1:]
        for w in words[1:])
    if out[0].isdigit():
        out = "v" + out
    return out if is_identifier(out) else None


def strip_verb(name):
    for v in VERBS:
        if name.startswith(v) and len(name) > len(v) and \
                (name[len(v)].isupper() or name[len(v)] == "_"):
            return name[len(v):].lstrip("_")
    return name


def call_hint(callee, args):
    """A name for the value a call returns."""
    last = re.split(r"[.:]", callee)[-1]
    if not is_identifier(last):
        return None
    parts = [p for p in last.split("_") if p]
    tail = strip_verb(parts[-1]) if parts else ""
    tail = re.split(r"(?:From|By|With)(?=[A-Z])", tail)[0]
    tail = re.split(r"To(?=[A-Z])", tail)[-1]     # StringToHash -> Hash
    if tail in VERBS:
        tail = ""                           # AIHazingSound_Create
    if not tail or tail in GENERIC or last in GENERIC:
        for a in args:
            m = _HASH_NOTE.search(a) or _STRING_LIT.match(a)
            if m:
                text = m.group(1)
                if last == "require":
                    text = text.split(".")[-1]
                named = camel(text)
                if named:
                    return named
            # a constant-style name: Bool(ATTRIBUTE_FEEL_SAFE_HASH, true)
            m = _CONST_NAME.search(a)
            if m:
                named = camel(re.sub(r"_HASH$", "", m.group()))
                if named:
                    return named
        if len(parts) > 1:
            tail = strip_verb(parts[-2])
    return camel(tail) if tail else None


def param_hints(p, first):
    """Names for parameters from how the function uses them. -> {reg: name}

    A parameter stored straight into a field is named after the field
    (`self.threatLevel = p1` -> threatLevel); one passed as the only
    argument of a setter after it (`x:SetImmuneTime(p1)` -> immuneTime)."""
    out = {}
    code = p.code
    for i in code:
        if i.op == "SETTABLE" and first <= i.C < p.numparams and \
                i.B >= BITRK and i.C not in out:
            key = p.consts[i.B - BITRK]
            if key.kind == "string":
                named = camel(key.value.decode("latin-1", "replace"))
                if named:
                    out[i.C] = named
    for k in range(len(code) - 2):
        a, b, c = code[k], code[k + 1], code[k + 2]
        name = None
        if a.op == "SELF" and b.op == "MOVE" and c.op == "CALL" and \
                b.A == a.A + 2 and c.A == a.A and c.B == 3 and a.C >= BITRK:
            name = p.consts[a.C - BITRK]
        elif a.op == "GETGLOBAL" and b.op == "MOVE" and c.op == "CALL" and \
                b.A == a.A + 1 and c.A == a.A and c.B == 2:
            name = p.consts[a.Bx]
        if name is None or name.kind != "string":
            continue
        name = name.value.decode("latin-1", "replace")
        if name.startswith("Set") and len(name) > 3 and \
                first <= b.B < p.numparams and b.B not in out:
            named = camel(name[3:])
            if named:
                out[b.B] = named
    return out


def metatable_hint(p, pc, reg):
    """`local t = {}; setmetatable(t, NPC)` -> "npc"."""
    code = p.code
    for k in range(pc + 1, min(pc + 8, len(code) - 3)):
        a, b, c, d = code[k:k + 4]
        if a.op == "GETGLOBAL" and b.op == "MOVE" and b.B == reg and \
                b.A == a.A + 1 and c.op == "GETGLOBAL" and c.A == a.A + 2 and \
                d.op == "CALL" and d.A == a.A and \
                p.consts[a.Bx].value == b"setmetatable":
            return camel(p.consts[c.Bx].value.decode("latin-1", "replace"))
    return None


def comment_text(text, limit=80):
    """Display text made safe to sit inside a --[[ ]] comment on one line."""
    t = " / ".join(part.strip() for part in text.splitlines() if part.strip())
    t = t.replace("]]", "] ]").replace('"', "'")
    return t if len(t) <= limit else t[:limit - 3].rstrip() + "..."


def uses_as_object(p, reg):
    """Does the function treat register reg as an object (`reg.x`,
    `reg:m()`, `reg.x = y`)? The test for writing it as a method."""
    for i in p.code:
        if i.op in ("GETTABLE", "SELF") and i.B == reg:
            return True
        if i.op == "SETTABLE" and i.A == reg:
            return True
    return False


def chunk_globals(p):
    """Every global name a chunk reads or writes, nested functions too."""
    out = set()
    for q in p.walk():
        for i in q.code:
            if i.op in ("GETGLOBAL", "SETGLOBAL") and i.Bx < len(q.consts):
                c = q.consts[i.Bx]
                if c.kind == "string":
                    out.add(c.value.decode("latin-1", "replace"))
    return out


# ------------------------------------------------------------------ proto
class Proto:
    __slots__ = ("source", "linedefined", "lastlinedefined", "nups",
                 "numparams", "is_vararg", "maxstack", "code", "consts",
                 "protos", "lineinfo", "locals", "upvalues", "path")

    def __init__(self):
        self.protos = []
        self.consts = []
        self.code = []
        self.lineinfo = []
        self.locals = []
        self.upvalues = []
        self.path = "0"

    def walk(self):
        yield self
        for p in self.protos:
            yield from p.walk()


class BytecodeError(Exception):
    pass


def parse(data):
    """Standard Lua 5.1 bytecode -> root Proto. Raises BytecodeError."""
    if data[:4] != b"\x1bLua":
        raise BytecodeError("not a Lua chunk")
    if data[4] != 0x51:
        raise BytecodeError(f"not Lua 5.1 (version byte {data[4]:#x})")
    fmt_ver, endian, isz, stsz, insz, numsz, integral = data[5:12]
    if fmt_ver != 0:
        raise BytecodeError(f"unsupported format {fmt_ver}")
    if insz != 4:
        raise BytecodeError(f"instruction size {insz}, expected 4")
    little = endian == 1
    end = "<" if little else ">"
    pos = [12]

    def take(n):
        b = data[pos[0]:pos[0] + n]
        if len(b) != n:
            raise BytecodeError("truncated chunk")
        pos[0] += n
        return b

    def integer():
        return int.from_bytes(take(isz), "little" if little else "big")

    def size_t():
        return int.from_bytes(take(stsz), "little" if little else "big")

    def string():
        n = size_t()
        if n == 0:
            return b""
        return take(n)[:-1]          # drop the trailing NUL

    def number():
        if integral:
            return float(int.from_bytes(take(numsz),
                                        "little" if little else "big"))
        if numsz == 8:
            return struct.unpack(end + "d", take(8))[0]
        if numsz == 4:
            return struct.unpack(end + "f", take(4))[0]
        raise BytecodeError(f"number size {numsz}")

    def proto(path):
        p = Proto()
        p.path = path
        p.source = string()
        p.linedefined = integer()
        p.lastlinedefined = integer()
        p.nups, p.numparams, p.is_vararg, p.maxstack = take(4)
        n = integer()
        p.code = [Instr(i, struct.unpack_from(end + "I", take(4))[0])
                  for i in range(n)]
        n = integer()
        for _ in range(n):
            t = take(1)[0]
            if t == 0:
                p.consts.append(Const("nil"))
            elif t == 1:
                p.consts.append(Const("bool", take(1)[0] != 0))
            elif t == 3:
                p.consts.append(Const("number", number()))
            elif t == 4:
                p.consts.append(Const("string", string()))
            else:
                raise BytecodeError(f"constant type {t}")
        n = integer()
        for i in range(n):
            p.protos.append(proto(f"{path}_{i}"))
        n = integer()
        p.lineinfo = [integer() for _ in range(n)]
        n = integer()
        for _ in range(n):
            nm = string()
            p.locals.append((nm, integer(), integer()))
        n = integer()
        p.upvalues = [string() for _ in range(n)]
        return p

    return proto("0")


# ----------------------------------------------------------- disassembly
def disassemble(p, out=None, depth=0):
    out = [] if out is None else out
    pad = "  " * depth
    out.append(f"{pad}proto {p.path}: {len(p.code)} instr, "
               f"{len(p.consts)} consts, {len(p.protos)} nested, "
               f"params={p.numparams} vararg={p.is_vararg} "
               f"maxstack={p.maxstack} nups={p.nups}")
    for ins in p.code:
        extra = ""
        if ins.op in ABX and ins.Bx < len(p.consts):
            extra = "  ; " + p.consts[ins.Bx].source()
        elif ins.op not in ASBX:
            bits = []
            for label, v in (("B", ins.B), ("C", ins.C)):
                if v >= BITRK and (v - BITRK) < len(p.consts):
                    bits.append(f"{label}=" + p.consts[v - BITRK].source())
            if bits:
                extra = "  ; " + "  ".join(bits)
        out.append(f"{pad}  {ins!r}{extra}")
    for kid in p.protos:
        disassemble(kid, out, depth + 1)
    return out


# ------------------------------------------------------------ expressions
# precedence, loosest first, matching the Lua 5.1 grammar
P_OR, P_AND, P_CMP, P_CONCAT, P_ADD, P_MUL, P_UNARY, P_POW, P_ATOM = range(9)


class Expr:
    __slots__ = ("text", "prec", "multi", "method", "newk", "hint", "fn")

    def __init__(self, text, prec=P_ATOM, multi=False, method=False):
        self.text = text
        self.prec = prec
        self.multi = multi          # call/vararg: can yield several values
        self.method = method        # `obj:name`, only valid as a callee
        # lowest constant index first introduced while computing this value,
        # used to tell which of two things the source wrote first
        self.newk = None
        self.hint = None            # what a local holding this is named after
        self.fn = None              # (params, rest) when this is a closure

    def paren(self, need):
        return f"({self.text})" if self.prec < need else self.text

    def copy(self):
        """A separate value with the same text. Registers must not share
        Expr objects: per-value facts (newk) are written onto them."""
        e = Expr(self.text, self.prec, self.multi, self.method)
        e.newk, e.hint, e.fn = self.newk, self.hint, self.fn
        return e

    def __repr__(self):
        return f"<Expr {self.text!r}>"


BINOPS = {"ADD": ("+", P_ADD), "SUB": ("-", P_ADD),
          "MUL": ("*", P_MUL), "DIV": ("/", P_MUL),
          "MOD": ("%", P_MUL), "POW": ("^", P_POW)}


class Term:
    """One test in a condition, or the final operand of a value expression.

    start: first operand instruction; test: the test (for a final operand,
    the end of its instructions); target: where the JMP after the test goes;
    sense: the jump is taken when the tested value's truth equals this;
    reg: for a final operand, the register it lands in."""
    __slots__ = ("start", "test", "target", "sense", "reg")

    def __init__(self, start, test, target, sense, reg=None):
        self.start, self.test, self.target = start, test, target
        self.sense, self.reg = sense, reg

    def __repr__(self):
        return (f"<Term {self.start}..{self.test} -> {self.target} "
                f"s={self.sense}>")


# stands in the registers after the first of a call's several results
MULTI_CONT = "\0more results"


class Unsupported(Exception):
    """A construct this decompiler does not handle yet.

    `where` is (proto path, pc) of the instruction it gave up on, filled in
    by the innermost function being decompiled."""
    where = None


# ------------------------------------------------------------ local vars
# luac keeps declared locals in the low registers and uses everything above
# them as scratch, so a register is a LOCAL exactly when its value has to
# survive a statement boundary. Without this every proto that declares one
# fails with "register read before it was written": the value was written,
# a statement flushed the scratch registers, and the later read found
# nothing. Names were stripped by `luac -s`, so they are invented - which is
# free, because a local's name is not present in the bytecode at all.
STATEMENT_OPS = {"SETGLOBAL", "SETTABLE", "SETUPVAL", "RETURN", "TAILCALL",
                 "SETLIST", "JMP", "CLOSE"}


def writes_of(i):
    """Registers this instruction assigns."""
    if i.op in ("MOVE", "LOADK", "LOADBOOL", "GETUPVAL", "GETGLOBAL",
                "GETTABLE", "NEWTABLE", "ADD", "SUB", "MUL", "DIV", "MOD",
                "POW", "UNM", "NOT", "LEN", "CONCAT", "TESTSET", "CLOSURE"):
        return [i.A]
    if i.op == "LOADNIL":
        return list(range(i.A, i.B + 1))
    if i.op == "SELF":
        return [i.A, i.A + 1]
    if i.op == "CALL":
        if i.C == 0:
            return [i.A]
        return list(range(i.A, i.A + i.C - 1))
    if i.op == "VARARG":
        if i.B == 0:
            return [i.A]
        return list(range(i.A, i.A + i.B - 1))
    if i.op == "FORPREP":
        return [i.A]                  # R(A) -= R(A+2), then jump
    if i.op == "FORLOOP":
        return [i.A, i.A + 3]         # step the counter, expose the variable
    if i.op == "TFORLOOP":
        return list(range(i.A + 3, i.A + 3 + i.C))
    return []


def reads_of(i):
    """Registers this instruction consumes."""
    out = []

    def rk(x):
        if x < BITRK:
            out.append(x)

    if i.op in ("MOVE", "UNM", "NOT", "LEN", "TESTSET"):
        out.append(i.B)
    elif i.op in ("GETTABLE",):
        out.append(i.B); rk(i.C)
    elif i.op in ("SETTABLE",):
        out.append(i.A); rk(i.B); rk(i.C)
    elif i.op in ("ADD", "SUB", "MUL", "DIV", "MOD", "POW", "EQ", "LT", "LE"):
        rk(i.B); rk(i.C)
    elif i.op == "CONCAT":
        out.extend(range(i.B, i.C + 1))
    elif i.op == "SELF":
        out.append(i.B); rk(i.C)
    elif i.op in ("SETGLOBAL", "SETUPVAL", "TEST"):
        out.append(i.A)
    elif i.op in ("CALL", "TAILCALL"):
        out.append(i.A)
        if i.B == 0:
            out.append(i.A + 1)
        else:
            out.extend(range(i.A + 1, i.A + i.B))
    elif i.op == "RETURN":
        if i.B >= 2:
            out.extend(range(i.A, i.A + i.B - 1))
    elif i.op == "SETLIST":
        out.append(i.A)
        out.extend(range(i.A + 1, i.A + 1 + (i.B or 0)))
    elif i.op == "FORPREP":
        out.extend((i.A, i.A + 2))
    elif i.op in ("FORLOOP", "TFORLOOP"):
        out.extend(range(i.A, i.A + 3))
    return out


def fb_floor(x):
    """The smallest count luac would encode as the "floating point byte" x.

    NEWTABLE sizes are stored as eeeeexxx = (1xxx) * 2^(eeeee-1), exact up
    to 7 and rounded UP above that (lobject.c, luaO_int2fb). The smallest
    count that rounds to x is therefore the fewest items the constructor can
    have had."""
    if x < 8:
        return x
    return fb_int(x - 1) + 1


def fb_int(x):
    """luaO_fb2int: decode a floating point byte."""
    if x < 8:
        return x
    return ((x & 7) + 8) << ((x >> 3) - 1)


def pseudo_pcs(p):
    """pcs of the upvalue-binding pseudo instructions after each CLOSURE.

    They look like MOVE / GETUPVAL but never execute; MOVE's A field is
    meaningless there, so treating them as real writes to R(A) invents
    values that were never computed."""
    out = set()
    for i in p.code:
        if i.op == "CLOSURE" and i.Bx < len(p.protos):
            for n in range(p.protos[i.Bx].nups):
                out.add(i.pc + 1 + n)
    return out


def successors(p, i, pseudo_after=0):
    """pcs control can reach directly after instruction i."""
    op, pc = i.op, i.pc
    if op == "JMP":
        return [pc + 1 + i.sBx]
    if op in ("EQ", "LT", "LE", "TEST", "TESTSET"):
        return [pc + 1, pc + 2]
    if op == "LOADBOOL" and i.C:
        return [pc + 2]
    if op == "FORPREP":
        return [pc + 1 + i.sBx]
    if op == "FORLOOP":
        return [pc + 1 + i.sBx, pc + 1]
    if op == "TFORLOOP":
        return [pc + 1, pc + 2]
    if op in ("RETURN", "TAILCALL"):
        return []
    return [pc + 1 + pseudo_after]


def open_top(p, pc):
    """The last register an open (B == 0) operand list at pc reaches.

    "Up to the top of the stack" means up to the multiple results of the
    call or `...` evaluated just before, which is always the most recent
    one: it is the final item of the list being built."""
    for q in range(pc - 1, -1, -1):
        i = p.code[q]
        if (i.op == "CALL" and i.C == 0) or (i.op == "VARARG" and i.B == 0):
            return i.A
    return p.code[pc].A


def liveness(p, pseudo):
    """-> live_out: for each pc, the registers whose value at that point is
    read later on some path before being overwritten.

    Ordinary backward dataflow over the instruction graph. A B == 0 operand
    ("up to the top of the stack") reads every register from A to the frame
    size, and a CLOSURE reads the registers its pseudo instructions capture.
    TESTSET only writes when it jumps, so it does not end a value's life."""
    n = len(p.code)
    uses, kills, succ = [set() for _ in range(n)], \
        [set() for _ in range(n)], [[] for _ in range(n)]
    for i in p.code:
        if i.pc in pseudo:
            continue
        rs = set(reads_of(i))
        if i.B == 0 and i.op in ("CALL", "TAILCALL", "RETURN", "SETLIST"):
            rs |= set(range(i.A, open_top(p, i.pc) + 1))
        extra = 0
        if i.op == "CLOSURE" and i.Bx < len(p.protos):
            extra = p.protos[i.Bx].nups
            for k in range(extra):
                b = p.code[i.pc + 1 + k] if i.pc + 1 + k < n else None
                if b is not None and b.op == "MOVE":
                    rs.add(b.B)
        uses[i.pc] = rs
        if i.op != "TESTSET":
            kills[i.pc] = set(writes_of(i))
        succ[i.pc] = [t for t in successors(p, i, extra) if 0 <= t < n]
    live_in = [set() for _ in range(n)]
    live_out = [set() for _ in range(n)]
    changed = True
    while changed:
        changed = False
        for pc in range(n - 1, -1, -1):
            if pc in pseudo:
                continue
            out = set()
            for t in succ[pc]:
                # TESTSET assigns R(A) only on its jump edge (the JMP after
                # it); falling through leaves R(A) alone
                if t == pc + 1 and p.code[pc].op == "TESTSET":
                    out |= live_in[t] - {p.code[pc].A}
                else:
                    out |= live_in[t]
            inn = uses[pc] | (out - kills[pc])
            if out != live_out[pc] or inn != live_in[pc]:
                live_out[pc], live_in[pc] = out, inn
                changed = True
    testset = {i.pc: i.A for i in p.code if i.op == "TESTSET"}
    return Flow(uses, kills, succ, live_in, live_out, testset)


class Flow:
    """Per-pc register uses, kills, successors and liveness."""
    __slots__ = ("uses", "kills", "succ", "live_in", "live_out", "testset")

    def __init__(self, uses, kills, succ, live_in, live_out, testset):
        self.uses, self.kills, self.succ = uses, kills, succ
        self.live_in, self.live_out = live_in, live_out
        self.testset = testset

    def uses_of(self, pc, reg):
        """Every pc that reads the value `reg` receives at pc."""
        found, seen = set(), set()
        stack = list(self.succ[pc])
        while stack:
            q = stack.pop()
            if q in seen:
                continue
            seen.add(q)
            if reg in self.uses[q]:
                found.add(q)
            if reg in self.kills[q]:
                continue
            for t in self.succ[q]:
                if t == q + 1 and self.testset.get(q) == reg:
                    continue            # assigned on the jump edge
                stack.append(t)
        return found


# reads that do not use a value up: tests look at it and pass it on, and a
# loop re-reads its control registers every iteration
NOT_CONSUMERS = ("TEST", "TESTSET", "FORLOOP", "TFORLOOP", "FORPREP")


def constants_used(i):
    """Constant indices an instruction refers to."""
    if i.op in ("LOADK", "GETGLOBAL", "SETGLOBAL"):
        return [i.Bx]
    if i.op in ABX or i.op in ASBX:
        return []
    out = []
    if i.op in ("GETTABLE", "SELF", "SETTABLE", "ADD", "SUB", "MUL", "DIV",
                "MOD", "POW", "EQ", "LT", "LE"):
        for v in ((i.B, i.C) if i.op != "GETTABLE" and i.op != "SELF"
                  else (i.C,)):
            if v >= BITRK:
                out.append(v - BITRK)
    return out


def constant_order(p):
    """-> (first_use, new_at): the pc where each constant first appears, and
    for each pc the constants that appear there for the first time.

    luac numbers constants in the order the PARSER meets them, and the
    parser reads source left to right. So first-use order is a record of
    source order, and it keeps what the instructions lose: `a = f("x")`
    meets the name `a` before "x", while `local v = f("x"); a = v` meets
    "x" first. Both compile to the same instructions otherwise."""
    first_use, new_at = {}, {}
    for i in p.code:
        for k in constants_used(i):
            if k not in first_use:
                first_use[k] = i.pc
                new_at.setdefault(i.pc, []).append(k)
    return first_use, new_at


def target_constant(p, i):
    """The constant naming a store's target, if the store introduces it."""
    if i.op == "SETGLOBAL":
        return i.Bx
    if i.op == "SETTABLE" and i.B >= BITRK:
        return i.B - BITRK
    return None


def extra_values_before(p, pc, first_use, new_at):
    """Is the dead value written at pc an extra value of the assignment
    that follows (`x = a, b` evaluates b and drops it)?

    Only if the assignment's target was parsed BEFORE the values: its name
    constant first appears at the store, yet is numbered below every
    constant the values introduced."""
    code = p.code
    reg = min(writes_of(code[pc])) if writes_of(code[pc]) else None
    if reg is None:
        return False
    q = pc + 1
    while q < len(code) and writes_of(code[q]) and \
            min(writes_of(code[q])) > reg and code[q].op not in (
                "CALL", "JMP") + tuple(Decompiler.TEST_OPS):
        q += 1
    if q >= len(code):
        return False
    st = code[q]
    v = store_value_reg(st)
    if v is None or v >= reg:
        return False
    k = target_constant(p, st)
    if k is None or first_use.get(k) != q:
        return False
    fresh = [c for x in range(pc, q) for c in new_at.get(x, ())]
    return bool(fresh) and k < min(fresh)


def fixed_locals(p):
    """Registers that are locals before the first instruction runs.

    The parameters, plus - in a `...` function - the implicit `arg` table
    Lua 5.1 declares right after them (LUA_COMPAT_VARARG, flagged by
    VARARG_HASARG). It occupies a register whether or not the body uses it,
    so emitting it as an ordinary local would shift every register above."""
    return p.numparams + (1 if p.is_vararg & 1 else 0)


def store_value_reg(ins):
    """The register a store instruction takes its value from, or None."""
    if ins.op in ("SETGLOBAL", "SETUPVAL"):
        return ins.A
    if ins.op == "SETTABLE":
        return ins.C if ins.C < BITRK else None
    if ins.op == "MOVE":
        return ins.B
    return None


def feeds_store_run(p, call):
    """Are a multi-result CALL's results stored straight away, last first?

    That is a multiple assignment, `s, e = str:find(x)`: the results are
    temporaries, not locals, however they look from the register traffic."""
    n = call.C - 1
    for k in range(n):
        pc = call.pc + 1 + k
        if pc >= len(p.code):
            return False
        if store_value_reg(p.code[pc]) != call.A + n - 1 - k:
            return False
    return True


def find_locals(p):
    """Writes that DECLARE a local -> {register: {pc, ...}}.

    pc -1 means declared before the first instruction: a parameter, or a
    `local x` at the top of a function, for which luac emits no LOADNIL at
    all because the frame starts out nil.

    The evidence is luac's register allocation, which is strict: locals
    occupy the lowest registers for as long as they are in scope, and
    every temporary is taken from the first free register above them and
    released as soon as it is consumed. Two consequences are decidable from
    the bytecode alone:

      * a value that is never read can only be a local. A temporary always
        has a consumer, or luac would not have computed it.

            local x = f()          CALL R0 ...
            y = 1                  LOADK R0 1   <- would reuse R0 if free

      * when an instruction writes register w, every register below w is
        occupied. If one of them holds a value nothing reads again, it is not
        a temporary still waiting for its consumer - it is a local.

            local v = f()          CALL R0 1 2
            if v ~= -1 then end    EQ 1 R0 K; JMP
            if w ~= -1 then end    GETGLOBAL R1 w  <- R0 still occupied

    Which of a register's writes are declarations and which are later
    assignments to the same local is decided while decompiling, from
    scope: a write to a register whose local is still in scope is an
    assignment. So this can afford to report every write that is evidently
    a local's value.

    Where the bytecode genuinely cannot tell (`local x = 1; y = x` compiles
    identically to `y = 1`) emitting the shorter form is still byte-exact,
    which is the bar that matters.
    """
    decl = {}

    def mark(reg, pc):
        decl.setdefault(reg, set()).add(pc)

    fixed = fixed_locals(p)
    first_use, new_at = constant_order(p)
    for reg in range(fixed):
        mark(reg, -1)                       # parameters are locals already

    pseudo = pseudo_pcs(p)
    code = [i for i in p.code if i.pc not in pseudo]

    flow = liveness(p, pseudo)

    def read_after(reg, pc):
        """Is the value reg holds after pc read on some path onward?"""
        return reg in flow.live_out[pc]

    # writes that fill a loop's hidden control registers are not locals
    # in the source, however long they stay live
    control = set()
    written = {}
    for i in code:
        if i.op == "FORPREP":
            for reg in range(i.A, i.A + 3):
                if reg in written:
                    control.add((reg, written[reg]))
            mark(i.A + 3, i.pc)
        elif i.op == "TFORLOOP":
            for n in range(i.C):
                mark(i.A + 3 + n, i.pc)
        elif i.op == "JMP":
            t = i.pc + 1 + i.sBx
            if 0 <= t < len(p.code) and p.code[t].op == "TFORLOOP":
                A = p.code[t].A
                for reg in range(A, A + 3):
                    if reg in written:
                        control.add((reg, written[reg]))
        for r in writes_of(i):
            written[r] = i.pc

    written = {}
    for i in code:
        ws = writes_of(i)
        base = None
        if i.op in ("CALL", "TAILCALL"):
            base = i.A          # results or not, the call frame starts here
        elif ws and i.op not in ("FORLOOP", "TFORLOOP"):
            base = min(ws)
        # `obj:m()` with the method name past constant 255: luac reserves
        # SELF's two registers first, then loads the name into the next
        # one, so those two are taken but not yet written
        reserved = set()
        nxt = p.code[i.pc + 1] if i.pc + 1 < len(p.code) else None
        if ws and nxt is not None and nxt.op == "SELF" and nxt.C in ws:
            reserved = {nxt.A, nxt.A + 1}
        if base is not None:
            for r in range(base):
                if r < fixed or r in reserved:
                    continue
                if r not in written:
                    mark(r, -1)             # `local x` at function start
                elif not read_after(r, i.pc):
                    mark(r, written[r])
        # a value nobody reads. TESTSET and a skipping LOADBOOL deliver
        # their value by jumping, so the next instruction in pc order is
        # not where it is used.
        #
        # And a value read by two different instructions: a temporary has
        # exactly one consumer. Tests are not counted, because an and/or
        # value is tested and then used by whatever takes the result.
        if i.op not in ("TESTSET", "FORLOOP", "TFORLOOP", "FORPREP") and \
                not (i.op == "LOADBOOL" and i.C):
            for r in ws:
                if not read_after(r, i.pc):
                    if not extra_values_before(p, i.pc, first_use, new_at):
                        mark(r, i.pc)
                    continue
                # a constructor filling in its own table does not use the
                # table up
                uses = flow.uses_of(i.pc, r)
                consumers = [q for q in uses
                             if p.code[q].op not in NOT_CONSUMERS
                             and not (i.op == "NEWTABLE" and
                                      p.code[q].op in ("SETTABLE", "SETLIST")
                                      and p.code[q].A == r)]
                if len(consumers) > 1:
                    mark(r, i.pc)
                # `return f(x)` compiles to a TAILCALL. A one-value CALL
                # whose result is the last thing returned was therefore
                # held in a local first (or written `return (f(x))`, which
                # compiles the same)
                elif i.op == "CALL" and i.C == 2 and consumers == [i.pc + 1]:
                    q = p.code[i.pc + 1]
                    if q.op == "RETURN" and q.B >= 2 and \
                            q.A + q.B - 2 == i.A:
                        mark(r, i.pc)
        if i.op == "SETTABLE" and i.A < BITRK:
            # `t[k] = v` loads t, then k, then v, each into the next free
            # register. A key or value in a register BELOW the table's was
            # therefore computed before the statement began: a local.
            for r in (i.B, i.C):
                if r < BITRK and r < i.A and r >= fixed and r in written:
                    mark(r, written[r])
            # and the key before the value
            if i.B < BITRK and i.C < BITRK and i.C < i.B and \
                    i.C >= fixed and i.C in written:
                mark(i.C, written[i.C])
        if i.op == "CALL" and i.C > 2 and not feeds_store_run(p, i):
            # several results at once is a multiple assignment; the targets
            # are locals when they are used later
            for reg in range(i.A, i.A + i.C - 1):
                if read_after(reg, i.pc):
                    mark(reg, i.pc)
        elif i.op == "CLOSURE" and i.Bx < len(p.protos):
            # a closure captures registers by reference, which only a real
            # local can be; the capture is in the pseudo instructions
            child = p.protos[i.Bx]
            for n in range(child.nups):
                pc = i.pc + 1 + n
                if pc < len(p.code) and p.code[pc].op == "MOVE":
                    reg = p.code[pc].B
                    if reg == i.A:
                        # captures itself: `local function f`, declared
                        # before its body so the body can call it
                        mark(reg, i.pc)
                    else:
                        mark(reg, written.get(reg, -1))
        for r in ws:
            written[r] = i.pc
        if i.op == "FORPREP":
            written[i.A + 3] = i.pc
        elif i.op == "JMP":
            t = i.pc + 1 + i.sBx
            if 0 <= t < len(p.code) and p.code[t].op == "TFORLOOP":
                for n in range(p.code[t].C):
                    written[p.code[t].A + 3 + n] = i.pc

    for reg, pc in control:
        if reg in decl:
            decl[reg].discard(pc)
            if not decl[reg]:
                del decl[reg]
    # `local a, b, c` at the top of a function emits nothing, and locals
    # are allocated in order, so one declared before the first instruction
    # means every register below it was too
    entry = [r for r, pcs in decl.items() if -1 in pcs and r >= fixed]
    for r in range(fixed, max(entry) if entry else fixed):
        mark(r, -1)
    return decl


class Decompiler:
    """Reconstructs source for one proto.

    Registers hold Expr values, built up as instructions are walked, and
    flushed into statements at the points luac would have had to commit them
    (SETGLOBAL, SETTABLE, a call used as a statement, RETURN).
    """

    def __init__(self, proto, upval_names=None, indent=1, taken=None,
                 depth=0, method=False, context=None):
        self.p = proto
        self.regs = {}
        self.lines = []
        self.indent = indent
        # Names the enclosing function gave this proto's upvalues. A child
        # refers to them by index only; the binding is in the pseudo
        # instructions that follow the parent's CLOSURE (see op_CLOSURE).
        self.upval_names = upval_names or []
        # names a local here must not take: the upvalues this function
        # refers to (shadowing one changes what the code means)
        self.taken = set(taken or ()) | set(upval_names or ())
        # chunk-wide facts: every global name (a local named like one would
        # shadow it) and what is known about hashed constants
        self.ctx = context or {"globals": set(), "hash_names": {},
                               "hash_values": None}
        self.depth = depth
        self.decl = find_locals(proto)
        self.first_use, self.new_at = constant_order(proto)
        self.flow = liveness(proto, pseudo_pcs(proto))
        # register -> index in self.lines where its pending value was
        # computed, so it can be declared there after the fact (promote)
        self.pending_at = {}
        # which constant index produced each register's value;
        # used to tell `1 < a` from `a > 1`, which compile to the
        # same instructions but a different constant order
        self.reg_kidx = {}
        # register holding a call or `...` left open, whose
        # results spill to the top of the stack
        self.multi_reg = None
        self.after_tailcall = False
        # set by op_CLOSURE: the pc past the upvalue-binding
        # pseudo instructions it already consumed
        self.skip_until = None
        # pc a `break` would jump to, when inside a loop
        self.loop_exit = None
        # head pc of the loop being decompiled, see block()
        self.loop_head = None
        # set while evaluating pieces of an expression, so writes to a
        # local's register do not turn into assignment statements
        self.in_expr = False
        # the register a value expression delivers into, which it may write
        # even when it is a local (`x = x or 1`)
        self.expr_target = None
        self.taking_multi = False
        # placeholder -> final name, for locals declared without a value
        self.deferred = {}
        self._senses = []
        # pc -> every JMP further on that jumps back to it
        self.back_jumps = {}
        for ins in proto.code:
            if ins.op == "JMP":
                t = ins.pc + 1 + ins.sBx
                if t < ins.pc:
                    self.back_jumps.setdefault(t, []).append(ins.pc)
        # base registers of every generic for, so the CALL that
        # produces the iterator triple is not mistaken for a
        # multiple assignment into three locals
        self.iter_bases = {i.A for i in proto.code
                           if i.op == "TFORLOOP"}
        # every pc that writes each register, so a read of one
        # not yet written can be recognised as the nil it is
        self.first_writes = {}
        for ins in proto.code:
            for r in writes_of(ins):
                self.first_writes.setdefault(r, ins.pc)
        self.cur_pc = 0
        # the CURRENT name of the local in each register; a register can
        # hold different locals over time (sibling scopes)
        self.names = {}
        # registers holding a local that is in scope right now. A write to
        # one of these is an assignment; any other write is a declaration
        # (if find_locals saw it is one) or a temporary.
        self.active = set()
        # parameters are live before the first instruction
        hints = param_hints(proto, 1 if method else 0)
        for reg in range(proto.numparams):
            if method and reg == 0:
                base = "self"
            else:
                base = hints.get(reg) or f"p{reg if method else reg + 1}"
            self.bind(reg, self.pick_name(base))
        if fixed_locals(proto) > proto.numparams:
            self.bind(proto.numparams, "arg")
        # `local x` at the top of a function compiles to nothing at all
        self.entry_locals = sorted(r for r, pcs in self.decl.items()
                                   if -1 in pcs
                                   and r >= fixed_locals(proto))

    def store(self, reg, expr, pc):
        """Put a value in a register, declaring a local if this write is one."""
        if self.in_expr:
            if reg in self.active and reg != self.expr_target:
                # an expression writing a local would be an assignment
                # swallowed into an expression: refuse rather than lose it
                raise Unsupported("assignment to a local inside an expression")
            self.regs[reg] = expr
            return
        if reg in self.active:
            # the local is in scope, so this is an assignment to it
            self.settle_name(reg, expr.hint)
            self.emit(f"{self.names[reg]} = {expr.text}")
            self.regs[reg] = Expr(self.names[reg], P_ATOM)
        elif self.is_decl(reg, pc):
            name = self.pick_name(expr.hint)
            self.emit(f"local {name} = {expr.text}")
            self.bind(reg, name)
        else:
            self.regs[reg] = expr
            self.pending_at[reg] = len(self.lines)

    def promote(self, pcs):
        """Declare, after the fact, temporaries that turn out to be locals.

        A temporary never outlives its statement: luac frees it the moment
        its consumer runs. So a value still waiting in a register when a
        statement or a control structure is reached, and read again past it,
        was a local all along - one find_locals had no direct evidence for,
        like `local n = 0` first read inside a later loop. It is declared at
        the point it was computed, which is where the source had it."""
        live = set()
        for q in pcs:
            if 0 <= q < len(self.p.code):
                live |= self.flow.live_in[q]
        for reg in sorted(self.regs):
            if reg in self.active or reg not in live:
                continue
            if self.pending_at.get(reg) is None:
                continue
            self.declare_pending(reg)

    def pick_name(self, hint, alternatives=()):
        """A name for a new local: from the hint when there is one, never
        shadowing a global, a captured upvalue or a local in scope."""
        base = hint if hint and is_identifier(hint) else "v"
        blocked = {self.names[r] for r in self.active} | self.taken | \
            self.ctx["globals"]
        for cand in (base,) + tuple(alternatives):
            if cand not in blocked and is_identifier(cand):
                return cand
        sep = "_" if base[-1].isdigit() else ""
        n = 2
        while f"{base}{sep}{n}" in blocked:
            n += 1
        return f"{base}{sep}{n}"

    def unnamed(self, reg):
        """Put a local declared WITHOUT a value (`local a, b`) in scope under
        a placeholder. Its first assignment names it (settle_name), since
        that is the first thing that says what it is for; run() swaps the
        placeholders for the final names."""
        token = f"\x01{len(self.deferred)}\x01"
        self.deferred[token] = None
        self.bind(reg, token)
        return token

    def settle_name(self, reg, hint):
        token = self.names.get(reg)
        if token not in self.deferred or self.deferred[token] is not None:
            return
        name = self.pick_name(hint) if hint else None
        if name is None:
            return
        self.deferred[token] = name
        self.names[reg] = name
        self.regs[reg] = Expr(name, P_ATOM)

    def bind(self, reg, name):
        """Put the local `name` in scope in reg."""
        self.names[reg] = name
        self.regs[reg] = Expr(name, P_ATOM)
        self.active.add(reg)
        self.pending_at.pop(reg, None)

    def const_text(self, c):
        """Source for a constant, naming hashed ones the way NB2's own
        plaintext scripts do: --[[HASH:"name"]]0x2e1e60d6."""
        if c.kind == "number" and c.value == int(c.value) and \
                abs(c.value) < 2 ** 53:
            v = int(c.value)
            fe = self.ctx.get("fe_values")
            if fe is not None and v not in fe.get(self.p.path, ()):
                # a double in the original: NB1 spelled it with a point
                text = format_number(c.value)
                return text if any(ch in text for ch in ".e") else text + ".0"
            values = self.ctx["hash_values"]
            if v >= HASH_FLOOR and (values is None or v in values):
                name = self.ctx["hash_names"].get(v)
                if name and ("]]" in name or '"' in name):
                    name = None
                text = self.ctx.get("hash_text", {}).get(v)
                label = []
                if name:
                    label.append(f'HASH:"{name}"')
                if text:
                    # (text, source) from nb_names.load_text; NB2's text is
                    # marked, since its wording can differ from NB1's. A text
                    # ID with a known name shows both: the name is what the
                    # code calls it, the text is what the player sees.
                    text, src = text if isinstance(text, tuple) else (text, "NB1")
                    tag = "TEXT" if src == "NB1" else f"TEXT({src})"
                    label.append(f'{tag}:"{comment_text(text)}"')
                if label:
                    return f'--[[{" ".join(label)}]]0x{v:08x}'
                # NB1 stores large plain integers in the same 64-bit type as
                # hashes: score thresholds like 250000000. A real CRC lands
                # on a multiple of 100,000 about once in 100,000 values, so a
                # round number with no name is a number, and reads as one.
                if v % 100000 == 0:
                    return str(v)
                if values is not None:
                    return f"0x{v:08x}"
        return c.source()

    def newk_between(self, lo, hi):
        ks = [k for pc in range(lo, hi) for k in self.new_at.get(pc, ())]
        return min(ks) if ks else None

    def declare_pending(self, reg):
        """Turn the temporary waiting in reg into a local, declared where
        its value was computed. -> its name, or None if it cannot be."""
        at = self.pending_at.get(reg)
        if at is None or reg in self.active or reg not in self.regs:
            return None
        # locals take the lowest registers, so anything still pending below
        # a new local was a local too - declared first, as it came first
        for lower in sorted(r for r in self.pending_at if r < reg):
            if lower not in self.active and lower in self.regs:
                self.declare_pending(lower)
        at = self.pending_at.get(reg)
        value = self.regs[reg]
        name = self.pick_name(value.hint)
        self.lines.insert(at, "  " * self.indent +
                          f"local {name} = {value.text}")
        for other, idx in self.pending_at.items():
            if other != reg and idx >= at:
                self.pending_at[other] = idx + 1
        self.bind(reg, name)
        return name

    def store_value(self, ins, reg):
        """The value text a store takes from reg, and any extra values.

        Two pieces of evidence live only in the constant table (see
        constant_order): a value whose constants were numbered BEFORE the
        target's name was computed by a separate statement first - a local;
        and temporaries left unconsumed above the value, computed after the
        target was named, are extra values the assignment drops
        (`x = a, b`)."""
        k = target_constant(self.p, ins)
        fresh_target = k is not None and self.first_use.get(k) == ins.pc
        if fresh_target and reg not in self.active and reg in self.regs:
            newk = self.regs[reg].newk
            if newk is not None and newk < k:
                self.declare_pending(reg)
        since = self.pending_at.get(reg) if reg not in self.active else None
        text = self.reg(reg).text
        extras = []
        r = reg + 1
        while since is not None and r not in self.active and \
                self.pending_at.get(r, -1) >= since:
            extras.append(self.reg(r).text)
            r += 1
        return ", ".join([text] + extras)

    def is_decl(self, reg, pc):
        return pc in self.decl.get(reg, ())

    def decl_pcs(self):
        return {pc for pcs in self.decl.values() for pc in pcs}

    # -- helpers ---------------------------------------------------------
    def k(self, i):
        if i >= len(self.p.consts):
            raise Unsupported(f"constant {i} out of range")
        return self.p.consts[i]

    def rk(self, x):
        if x >= BITRK:
            c = self.k(x - BITRK)
            return Expr(self.const_text(c), P_ATOM)
        return self.reg(x)

    def reg(self, i):
        if i not in self.regs:
            # A register is nil until something writes it, and luac knows it:
            # luaK_nil emits no LOADNIL at all when nothing has been generated
            # yet, because the whole frame starts clean. So `x = nil` as the
            # first statement compiles to a bare SETGLOBAL reading a register
            # that was never written.
            first = self.first_writes.get(i)
            if first is None or first > self.cur_pc:
                return Expr("nil", P_ATOM)
            raise Unsupported(f"register {i} read before it was written")
        if self.regs[i].text == MULTI_CONT and not self.taking_multi:
            raise Unsupported("one of several call results used alone")
        # a temporary has exactly one consumer: once read, it is spent
        self.pending_at.pop(i, None)
        return self.regs[i]

    def emit(self, text):
        self.lines.append("  " * self.indent + text)

    def field(self, obj, key):
        """obj.key when the key is a plain identifier, else obj[key]."""
        if key.kind == "string" and is_identifier(key.value.decode(
                "latin-1", "replace")):
            name = key.value.decode("latin-1")
            e = Expr(f"{obj.paren(P_ATOM)}.{name}", P_ATOM)
            e.hint = camel(name)
            return e
        return Expr(f"{obj.paren(P_ATOM)}[{self.const_text(key)}]", P_ATOM)

    # -- control flow ----------------------------------------------------
    # A comparison never stands alone: luac always follows EQ/LT/LE/TEST with
    # a JMP, and arranges the test so the jump is taken when the body should
    # be SKIPPED. So the source condition is the comparison as-written when
    # the A (or C) flag is 0, and its negation when the flag is 1.
    #
    #   if x == y then B end   ->  EQ 0 x y ; JMP past-B ; B
    #   if x ~= y then B end   ->  EQ 1 x y ; JMP past-B ; B
    #
    # `a > b` and `a >= b` do not exist in the instruction set - luac compiles
    # them as `b < a` and `b <= a` - so they come back with the operands
    # swapped. That is the same program, and it recompiles identically, which
    # is the bar here.
    COMPARISONS = {"EQ": "==", "LT": "<", "LE": "<="}
    FLIPPED = {"<": ">", "<=": ">="}

    def _operands_swapped(self, ins):
        """Did the source write `a > b` rather than `b < a`?

        There is no `>` or `>=` opcode: luac compiles `a > b` as `b < a`. It
        still EVALUATES a before b though, so a ends up in the lower register
        while appearing as the comparison's second operand. That inversion is
        the signature, and it matters because emitting `b < a` instead would
        load the two in the wrong order and change the bytecode.

        When one side is a constant there are no registers to compare, and
        `1 < a` and `a > 1` produce identical INSTRUCTIONS. They differ in the
        constant table: whichever operand luac read first got the lower index.
        """
        b_is_k, c_is_k = ins.B >= BITRK, ins.C >= BITRK
        if not b_is_k and not c_is_k:
            return ins.B > ins.C
        # A comparison allocates its left operand's constants first (unlike
        # arithmetic, luac does not hold back a numeral here). So when the
        # constant is new at this instruction, which side the source wrote
        # first is recorded in the constant order: `0.5 < GetRandomNumber()`
        # numbers 0.5 before GetRandomNumber, `GetRandomNumber() > 0.5` the
        # other way round. When the constant is not new, both spellings
        # compile identically and the natural one is kept.
        k = (ins.B if b_is_k else ins.C) - BITRK
        other = ins.C if b_is_k else ins.B
        theirs = self.reg_kidx.get(other)
        if theirs is None and other in self.regs and other not in self.active:
            theirs = self.regs[other].newk
        fresh = self.first_use.get(k) == ins.pc
        if b_is_k:
            if fresh and theirs is not None:
                return k > theirs     # constant added later -> swapped
            return True
        if fresh and theirs is not None:
            return k < theirs         # `1 > a`: constant added first
        return False

    def compare_text(self, ins):
        sym = self.COMPARISONS[ins.op]
        if ins.op != "EQ" and self._operands_swapped(ins):
            lhs, rhs = self.rk(ins.C), self.rk(ins.B)
            sym = self.FLIPPED[sym]
        else:
            lhs, rhs = self.rk(ins.B), self.rk(ins.C)
        return Expr(f"{lhs.paren(P_CMP)} {sym} {rhs.paren(P_CMP)}", P_CMP)

    def target_of(self, jmp):
        return jmp.pc + 1 + jmp.sBx

    STATEMENT_OPS = ("SETTABLE", "SETGLOBAL", "SETUPVAL", "SETLIST",
                     "RETURN", "TAILCALL")

    def execute(self, ins):
        """Run one instruction's handler, keeping cur_pc in step with it.

        reg() uses cur_pc to tell a register that is still nil from one read
        out of order, so every path that evaluates an instruction - the main
        walk, condition operands, table items - has to come through here."""
        fn = getattr(self, "op_" + ins.op, None)
        if fn is None:
            raise Unsupported(ins.op)
        self.cur_pc = ins.pc
        if not self.in_expr and ins.op in self.STATEMENT_OPS:
            # a statement consumes the temporaries it reads; one still live
            # past it (`t.b = 2` on a pending `{}`, then `return t`) was a
            # local
            live = self.flow.live_out[ins.pc]
            if any(r in live and r not in self.active and r in self.pending_at
                   for r in reads_of(ins)):
                self.promote([ins.pc + 1])
        for r in writes_of(ins):
            self.reg_kidx.pop(r, None)     # LOADK / GETGLOBAL set it again
        feeds = [self.regs[r].newk for r in reads_of(ins)
                 if r in self.regs and r not in self.active]
        fn(ins)
        newk = [k for k in feeds if k is not None] + \
            list(self.new_at.get(ins.pc, ()))
        if newk:
            for r in writes_of(ins):
                if r in self.regs and r not in self.active:
                    self.regs[r].newk = min(newk)
        for r in writes_of(ins):
            if r not in self.active and r in self.regs:
                self.pending_at[r] = len(self.lines)

    def run(self):
        if self.entry_locals:
            names = [self.unnamed(r) for r in self.entry_locals]
            self.emit("local " + ", ".join(names))
        try:
            self.block(0, len(self.p.code))
        except Unsupported as e:
            if e.where is None:
                e.where = (self.p.path, self.cur_pc)
            raise
        return self.resolve_names("\n".join(self.lines))

    def resolve_names(self, text):
        """Replace placeholders with final names. One never assigned a
        value with a hint gets a plain name no other identifier in this
        function's text uses, so it cannot shadow or be shadowed."""
        if not self.deferred:
            return text
        used = set(re.findall(r"[A-Za-z_]\w*", text)) | self.taken | \
            self.ctx["globals"] | {n for n in self.deferred.values() if n}
        for token, name in self.deferred.items():
            if name is None:
                n = 1
                name = "v"
                while name in used:
                    n += 1
                    name = f"v{n}"
                used.add(name)
            text = text.replace(token, name)
        return text

    def block(self, start, end):
        pc = start
        code = self.p.code
        while pc < end:
            ins = code[pc]
            self.cur_pc = pc
            # A backward jump is always a loop, and the last one aimed at pc
            # is that loop's own. The head of the loop already being
            # decompiled is excluded: jumps threaded to it from inside the
            # body (an `if` ending the body) aim there too.
            if pc != self.loop_head:
                backs = [q for q in self.back_jumps.get(pc, ()) if q < end]
                if backs:
                    pc = self.loop(pc, max(backs), end)
                    continue
            if ins.op == "NEWTABLE":
                pc = self.table(pc, end)
                continue
            if ins.op == "FORPREP":
                pc = self.numeric_for(pc, end)
                continue
            if ins.op in self.TEST_OPS:
                got = self.value_expr(pc, end)
                if got is not None:
                    pc = got
                    continue
                pc = self.branch(pc, end)
                continue
            if ins.op in ("SETGLOBAL", "SETUPVAL", "SETTABLE", "MOVE"):
                got = self.multi_store(pc, end)
                if got is not None:
                    pc = got
                    continue
            if ins.op == "JMP":
                t = self.target_of(ins)
                if t == pc:
                    self.emit("while true do end")
                    pc += 1
                    continue
                if start < t < end and code[t].op == "TFORLOOP":
                    pc = self.generic_for(pc, end)
                    continue
                # inside a loop, a bare forward jump to the loop's exit is a
                # `break`; luac emits nothing else for it
                if self.loop_exit is not None and \
                        self.final(t) == self.final(self.loop_exit):
                    self.emit("break")
                    pc += 1
                    continue
                raise Unsupported("JMP outside a recognised structure")
            before = len(self.lines)
            self.execute(ins)
            if self.skip_until is not None:
                pc, self.skip_until = self.skip_until, None
            else:
                pc += 1
            if len(self.lines) != before:
                self.promote([pc])
        return pc

    TEST_OPS = ("EQ", "LT", "LE", "TEST", "TESTSET")
    # instructions that can legitimately sit inside a condition, computing an
    # operand. Anything else means the condition has ended and the body began.
    OPERAND_OPS = ("MOVE", "LOADK", "LOADNIL", "LOADBOOL", "GETGLOBAL",
                   "GETTABLE", "GETUPVAL", "SELF", "ADD", "SUB", "MUL", "DIV",
                   "MOD", "POW", "UNM", "NOT", "LEN", "CONCAT", "CALL")

    # -- conditions --------------------------------------------------------
    # luac never emits a condition as one test. It builds two jump lists as
    # it parses - `t` (jumps taken when the expression is true) and `f` -
    # and each `and` / `or` moves one list forward and leaves the other
    # pending (lcode.c, luaK_goiftrue / luaK_goiffalse / luaK_posfix). What
    # reaches the bytecode is a flat run of TERMS, each an operand
    # computation, a test and a JMP, whose targets are all that is left of
    # the expression tree. Rebuilding the tree from the targets is the whole
    # job, and the same job whether the expression steers an `if` or produces
    # a value (`x = a or b`), so both go through cond_tree.
    #
    # A test jumps when truth(c) == s, where c is the comparison as written
    # (or the register for TEST/TESTSET) and s is its A flag (C for tests).
    def leaf_expr(self, ins, negate):
        """The condition one test stands for, optionally negated."""
        if ins.op in self.COMPARISONS:
            if not negate:
                return self.compare_text(ins)
            if ins.op == "EQ":
                lhs, rhs = self.rk(ins.B), self.rk(ins.C)
                return Expr(f"{lhs.paren(P_CMP)} ~= {rhs.paren(P_CMP)}", P_CMP)
            return Expr(f"not ({self.compare_text(ins).text})", P_UNARY)
        if ins.op == "TEST":
            val = self.reg(ins.A)
        elif ins.op == "TESTSET":
            # TESTSET copies its operand into the result, so it can only
            # carry the value itself - never its negation
            if negate:
                raise Unsupported("TESTSET standing for a negation")
            return self.reg(ins.B)
        else:
            raise Unsupported(f"condition from {ins.op}")
        if negate:
            return Expr(f"not {val.paren(P_UNARY)}", P_UNARY)
        return val

    def is_operand(self, ins):
        if ins.op == "VARARG":
            return True
        if ins.op not in self.OPERAND_OPS:
            return False
        # C=2 is a call used for one value; C=0 is one left open for an
        # enclosing call to take all its results (`f(g())`). C=1 discards
        # the results, which only a statement does.
        return ins.op != "CALL" or ins.C in (0, 2)

    def scan_terms(self, pc, end):
        """The run of tests starting at pc, operands included.

        A term is (start, test, target, sense): its operand instructions
        start at `start`, the test is at `test`, the JMP after it goes to
        `target`, and the jump is taken when truth == sense."""
        code = self.p.code
        terms = []
        j = pc
        while j < end:
            k = j
            while k < end and self.is_operand(code[k]):
                k += 1
            if k + 1 >= end or code[k].op not in self.TEST_OPS \
                    or code[k + 1].op != "JMP":
                break
            ins = code[k]
            sense = ins.A if ins.op in self.COMPARISONS else ins.C
            terms.append(Term(j, k, self.target_of(code[k + 1]),
                              1 if sense else 0))
            j = k + 2
        return terms

    def same_place(self, a, b, fuzzy):
        """Do two jump labels mean the same place?

        Exact comparison first. `fuzzy` also accepts jump THREADING: when luac
        emits a JMP while other jumps are still waiting to be patched to the
        current position, it merges them into it (luaK_jump concatenates
        fs->jpc), so they land on that JMP's destination instead. An `if` at
        the end of a loop body therefore jumps straight to the loop head, and
        a nested `if` at the end of a then-branch straight past the else."""
        if a == b:
            return True
        if not fuzzy or not isinstance(a, int) or not isinstance(b, int):
            return False
        return self.final(a) == self.final(b)

    def final(self, pc):
        """Where control actually ends up from pc, following JMPs."""
        code = self.p.code
        seen = set()
        while pc < len(code) and code[pc].op == "JMP" and pc not in seen:
            seen.add(pc)
            pc = self.target_of(code[pc])
        return pc

    def cond_tree(self, labels, starts, T, F, fuzzy=False, value_leaf=None):
        """Rebuild the and/or tree for a run of terms.

        labels[i] is where term i jumps; starts[i] where its operands begin
        (starts[n] is where the last term falls through to). T and F are
        where control goes when the whole expression is true / false.
        value_leaf, when set, is the index of a final term with no test at
        all - the last operand of a value expression.

        -> nested tuples ("leaf", i, negate) / ("value", i) /
           ("or" | "and", left, right), or None if no tree fits.

        The split rule is luac's own: `X or Y` compiles X so that every jump
        out of it goes to T (true, skip Y) or falls into Y's first term, and
        `X and Y` so that every jump goes to F or into Y. The rightmost split
        that works is the loosest operator, since both are left-associative.
        """
        memo = {}

        def parse(i, j, T, F):
            key = (i, j, T, F)
            if key in memo:
                return memo[key]
            memo[key] = None
            out = None
            if j - i == 1:
                if i == value_leaf:
                    out = ("value", i)
                else:
                    # When T and F are the same place (an empty body) both
                    # readings fit; luac sends a condition's final test to
                    # F, so that reading is tried first.
                    lab, fall = labels[i], starts[i + 1]
                    if self.same_place(lab, F, fuzzy) and \
                            self.same_place(fall, T, fuzzy):
                        out = ("leaf", i, sense[i] == 1)
                    elif self.same_place(lab, T, fuzzy) and \
                            self.same_place(fall, F, fuzzy):
                        out = ("leaf", i, sense[i] == 0)
            else:
                for k in range(j - 1, i, -1):
                    left = parse(i, k, T, starts[k])
                    if left is not None:
                        right = parse(k, j, T, F)
                        if right is not None:
                            out = ("or", left, right)
                            break
                    left = parse(i, k, starts[k], F)
                    if left is not None:
                        right = parse(k, j, T, F)
                        if right is not None:
                            out = ("and", left, right)
                            break
            memo[key] = out
            return out

        sense = self._senses
        n = len(labels) + (1 if value_leaf is not None else 0)
        return parse(0, n, T, F)

    def terms_share_values(self, run):
        """Does a later term read a value an earlier term's operands made?

        Each test's operands are computed right before it and consumed by
        it, so the terms of ONE condition never share values. If they do,
        the value was a local declared between two conditions that merely
        end at the same place (`if a then local x = f() if x.. then`),
        and merging them into `if a and ...` would lose the declaration."""
        code = self.p.code
        for t in run[1:]:
            made = set()
            for pc in range(t.start, t.test):
                made.update(writes_of(code[pc]))
            after = set()
            for q in (t.test + 2, t.target):     # both ways out of the test
                if 0 <= q < len(code):
                    after |= self.flow.live_in[q]
            if made & after:
                return True
        return False

    def assigns_local(self, ins):
        """Does this instruction write a local that is in scope?

        That is an assignment statement, so it can never be one of a
        condition's operands - an expression only writes temporaries."""
        return any(r in self.active for r in writes_of(ins))

    def prepare_cond(self, terms):
        """Declare temporaries the condition reads more than once.

        An and/or VALUE tests each operand once and hands it on, so tests
        are not counted as consumers when finding locals. But within one
        condition, a register tested by two leaves and computed before the
        condition began - `(a and not b) or (not a and b)` - can only be a
        local: a temporary would have been consumed by the first test."""
        code = self.p.code
        lo, hi = terms[0].start, terms[-1].test
        written = {r for pc in range(lo, hi) for r in writes_of(code[pc])}
        seen = {}
        for t in terms:
            ins = code[t.test]
            if ins.op == "TEST" and ins.A not in written:
                seen[ins.A] = seen.get(ins.A, 0) + 1
        for reg, n in seen.items():
            if n > 1:
                self.declare_pending(reg)
        # Each test's operands are computed right before it. A value waiting
        # from before a LATER test's operands began, and read there, was not
        # computed for that test at all: it was a local declared ahead of the
        # condition. (From NB1 ep10achievements: two values computed, then
        # `a ~= f(x) or b == K`.)
        if len(terms) > 1:
            done = set()
            for pc in range(terms[1].start, terms[-1].test + 1):
                ins = code[pc]
                for r in reads_of(ins):
                    if r not in done and r not in self.active and \
                            r in self.pending_at:
                        self.declare_pending(r)
                done.update(writes_of(ins))

    def render_cond(self, node, terms):
        """Evaluate a cond_tree into an expression, running each term's
        operand instructions in program order as its leaf is reached."""
        kind = node[0]
        if kind == "leaf":
            t = terms[node[1]]
            self.run_operands(t.start, t.test)
            self.cur_pc = t.test
            return self.leaf_expr(self.p.code[t.test], node[2])
        if kind == "value":
            t = terms[node[1]]
            self.run_operands(t.start, t.test)
            self.cur_pc = max(t.start, t.test - 1)
            return self.reg(t.reg)
        left = self.render_cond(node[1], terms)
        right = self.render_cond(node[2], terms)
        sym, prec = ("or", P_OR) if kind == "or" else ("and", P_AND)
        return Expr(f"{left.paren(prec)} {sym} {right.paren(prec + 1)}", prec)

    def run_operands(self, start, end):
        """Evaluate instructions that only build values - never statements.

        Used for condition operands and the pieces of a value expression.
        A nested value expression (`f(a or b)` inside a condition) is handled
        by recursion; anything that would emit a statement is an error,
        because it means the region was misidentified."""
        code = self.p.code
        before = len(self.lines)
        saved, self.in_expr = self.in_expr, True
        try:
            pc = start
            while pc < end:
                ins = code[pc]
                self.cur_pc = pc
                if ins.op == "NEWTABLE":
                    pc = self.table(pc, end)
                    continue
                if ins.op in self.TEST_OPS:
                    got = self.value_expr(pc, end)
                    if got is None:
                        raise Unsupported("test inside an expression")
                    pc = got
                    continue
                self.execute(ins)
                if self.skip_until is not None:
                    pc, self.skip_until = self.skip_until, None
                else:
                    pc += 1
        finally:
            self.in_expr = saved
        if len(self.lines) != before:
            raise Unsupported("statement inside an expression")

    # -- value expressions -------------------------------------------------
    # `x = a or b` and `x = a == b` compile to the same kind of jump run as a
    # condition, but ending in a register instead of a branch (lcode.c,
    # exp2reg). Jumps that must deliver a value either copy it with TESTSET
    # and land on the instruction after the expression, or land on a pair of
    # LOADBOOLs luac appends: `LOADBOOL R 0 1` (false, skip next) and
    # `LOADBOOL R 1 0` (true). A TESTSET whose destination is its own operand
    # is turned back into TEST (patchtestreg), which is why `x = a or b`
    # contains no TESTSET at all when a and x share a register.
    BLOCKING = ("SETGLOBAL", "SETUPVAL", "RETURN", "TAILCALL", "FORPREP",
                "FORLOOP", "TFORLOOP", "CLOSE")

    def _loadbools(self, q):
        code = self.p.code
        if q < 0 or q + 1 >= len(code):
            return False
        a, b = code[q], code[q + 1]
        return (a.op == "LOADBOOL" and b.op == "LOADBOOL" and a.A == b.A
                and a.B == 0 and a.C == 1 and b.B == 1 and b.C == 0)

    def _pure_region(self, lo, hi, reg):
        """Could [lo, hi) be the last operand of a value landing in reg?"""
        code = self.p.code
        wrote = False
        for pc in range(lo, hi):
            ins = code[pc]
            if ins.op in self.BLOCKING:
                return False
            if ins.op == "CALL" and ins.C == 1:
                return False
            if ins.op in ("SETTABLE", "SETLIST") and ins.A < reg:
                return False
            if ins.op == "JMP" and self.target_of(ins) <= pc:
                return False
            if reg in writes_of(ins):
                wrote = True
        return wrote

    def _consumed(self, pc, reg):
        """Is reg read at or after pc before anything overwrites it?"""
        code = self.p.code
        for ins in code[pc:]:
            if reg in reads_of(ins):
                return True
            if reg in writes_of(ins):
                return False
        return False

    def _value_shape(self, terms, end):
        """-> (reg, labels, value_term or None, fall, E) or None."""
        code = self.p.code
        if any(t.target <= t.test + 1 for t in terms):
            return None
        j = terms[-1].test + 2
        max_t = max(t.target for t in terms)
        q, vterm = None, None
        if self._loadbools(j):
            q = j
        else:
            # the furthest jump lands on the false load, the true load, or
            # past both (a TESTSET delivering its own value)
            for cand in (max_t, max_t - 1, max_t - 2):
                if cand - 1 >= j and self._loadbools(cand) and \
                        code[cand - 1].op == "JMP" and \
                        self.target_of(code[cand - 1]) == cand + 2:
                    q = cand
                    break
        if q is not None:
            reg, E = code[q].A, q + 2
            if max_t > E or E > end:
                return None
            if q > j:
                if not self._pure_region(j, q - 1, reg):
                    return None
                vterm = Term(j, q - 1, None, None, reg)
            fixed = {q: "F", q + 1: "T"}
        else:
            E = max_t
            if E > end or E <= j:
                return None
            regs = {code[t.test].A for t in terms
                    if t.target == E and code[t.test].op in ("TEST", "TESTSET")}
            if len(regs) != 1:
                return None
            reg = regs.pop()
            if not self._pure_region(j, E, reg):
                return None
            has_testset = any(code[t.test].op == "TESTSET" for t in terms)
            if not has_testset and not self._consumed(E, reg):
                return None
            vterm = Term(j, E, None, None, reg)
            fixed = {}
        starts = {t.start for t in terms}
        if vterm is not None:
            starts.add(vterm.start)
        labels = []
        for t in terms:
            op = code[t.test].op
            if t.target in fixed:
                labels.append(fixed[t.target])
            elif t.target == E and op in ("TEST", "TESTSET"):
                labels.append("T" if t.sense else "F")
            elif t.target in starts and op != "TESTSET":
                labels.append(t.target)
            else:
                return None
        fall = vterm.start if vterm is not None else "F"
        return reg, labels, vterm, fall, E

    def value_expr(self, pc, end):
        """A value built with and/or or a comparison, at pc. -> next pc or None.

        Tried from the longest run of tests down, because the tests of an
        expression nested in the last operand (`a or f(b and c)`) sit in the
        same run and belong to the inner expression, not this one."""
        terms = self.scan_terms(pc, end)
        for n in range(len(terms), 0, -1):
            run = terms[:n]
            got = self._value_shape(run, end)
            if got is None:
                continue
            reg, labels, vterm, fall, E = got
            self._senses = [t.sense for t in run]
            starts = [t.start for t in run] + [fall]
            leaf = None
            parts = list(run)
            if vterm is not None:
                leaf = len(run)
                parts.append(vterm)
                starts.append(None)
            tree = self.cond_tree(labels, starts, "T", "F", value_leaf=leaf)
            if tree is None:
                continue
            decl_pc = next((d for d in sorted(self.decl.get(reg, ()))
                            if pc <= d < E), None)
            saved = self.in_expr, self.expr_target
            self.in_expr, self.expr_target = True, reg
            try:
                expr = self.render_cond(tree, parts)
            finally:
                self.in_expr, self.expr_target = saved
            expr.newk = self.newk_between(pc, E)
            if expr.hint is None or vterm is None:
                expr.hint = "flag" if vterm is None else expr.hint
            if decl_pc is not None:
                self.store(reg, expr, decl_pc)
            else:
                self.store(reg, expr, E - 1)
            return E
        return None

    # -- statements with conditions ---------------------------------------
    def cond_shape(self, pc, end, want_false=None):
        """The condition steering an if/while at pc.

        -> (terms, tree, body_pc, false_target) or None. The run of tests is
        trimmed to the longest prefix that forms ONE condition: for
        `while a do if b then ... end end` the scan picks up both tests, but
        they have different failure targets and no tree fits both."""
        terms = self.scan_terms(pc, end)
        # operands are pure expressions; a local declared among them means
        # the scan ran into the next statement
        decls = self.decl_pcs()
        for fuzzy in (False, True):
            for n in range(len(terms), 0, -1):
                run = terms[:n]
                if any(d in decls or self.assigns_local(self.p.code[d])
                       for t in run[1:] for d in range(t.start, t.test)):
                    continue
                if self.terms_share_values(run):
                    continue
                body = run[-1].test + 2
                false = run[-1].target
                if want_false is not None and \
                        not self.same_place(false, want_false, True):
                    continue
                self._senses = [t.sense for t in run]
                starts = [t.start for t in run] + [body]
                tree = self.cond_tree([t.target for t in run], starts,
                                      body, false, fuzzy)
                if tree is not None:
                    return run, tree, body, false
        return None

    def store_target(self, ins):
        """The assignment target text for a store instruction."""
        if ins.op == "SETGLOBAL":
            return self.k(ins.Bx).value.decode("latin-1", "replace")
        if ins.op == "SETUPVAL":
            return self.upval(ins.B)
        if ins.op == "SETTABLE":
            obj = self.reg(ins.A)
            if ins.B >= BITRK:
                return self.field(obj, self.k(ins.B - BITRK)).text
            return f"{obj.paren(P_ATOM)}[{self.reg(ins.B).text}]"
        return self.names[ins.A]

    def multi_store(self, pc, end):
        """`a, b = x, y`, stored last target first. -> next pc or None.

        luac evaluates every value into consecutive temporaries, then stores
        them in REVERSE: the last target straight from its expression, each
        earlier one from the next temporary down (lparser.c, restassign).
        Two stores in a row that consume descending temporaries can only be
        that, since a single assignment consumes its value immediately."""
        code = self.p.code

        def value_reg(ins):
            r = store_value_reg(ins)
            if ins.op == "MOVE" and ins.A not in self.active:
                return None
            return r

        first = code[pc]
        if value_reg(first) is None and not (
                first.op == "SETTABLE" and first.C >= BITRK):
            return None
        run = [pc]
        k = pc + 1
        top = None
        while k < end:
            r = value_reg(code[k])
            if r is None or r in self.active or r not in self.regs:
                break
            if top is None:
                v = value_reg(first)
                if v is not None and v not in self.active and v != r + 1:
                    break
            elif r != top - 1:
                break
            top = r
            run.append(k)
            k += 1
        if len(run) < 2:
            return None
        # targets in source order are the stores reversed; so are values
        targets = [self.store_target(code[q]) for q in reversed(run)]
        vals = []
        self.taking_multi = True
        for q in reversed(run[1:]):
            vals.append(self.reg(value_reg(code[q])))
        if first.op == "SETTABLE" and first.C >= BITRK:
            vals.append(self.rk(first.C))
        else:
            vals.append(self.reg(value_reg(first)))
        # results of one multi-value call arrive as the call plus
        # continuation markers; the call stands for all of them
        self.taking_multi = False
        texts = [v.text for v in vals if v.text != MULTI_CONT]
        self.emit(f"{', '.join(targets)} = {', '.join(texts)}")
        for q in run:
            if code[q].op == "MOVE":
                self.regs[code[q].A] = Expr(self.names[code[q].A], P_ATOM)
        return k

    def region_end(self, start, target, end):
        """Where a region jumped past by `target` really ends.

        If target lies inside the enclosing range it is the natural end. If
        not, the jump was threaded (see same_place) and the region ends at
        the JMP it was merged into: the last one in range that leads to the
        same place. -> pc or None."""
        if start <= target <= end:
            return target
        code = self.p.code
        want = self.final(target)
        best = None
        for q in range(start, min(end, len(code) - 1) + 1):
            if code[q].op == "JMP" and self.final(q) == want:
                best = q
        return best

    def if_extent(self, pc, end):
        """-> (terms, tree, body_pc, then_end, else_end or None) or None."""
        shape = self.cond_shape(pc, end)
        if shape is None:
            return None
        terms, tree, body, false = shape
        then_end = self.region_end(body, false, end)
        if then_end is None or then_end < body:
            return None
        code = self.p.code
        else_end = None
        # A JMP straight after a test belongs to that test (an empty `if`
        # ending the body), never an escape over an else branch.
        if then_end - 1 >= body and code[then_end - 1].op == "JMP" and \
                not (then_end - 2 >= body and
                     code[then_end - 2].op in self.TEST_OPS):
            esc = self.target_of(code[then_end - 1])
            back_in_body = body <= esc < then_end
            is_break = (self.loop_exit is not None and
                        self.final(esc) == self.final(self.loop_exit))
            if not back_in_body and not is_break:
                else_end = self.region_end(then_end, esc, end)
        return terms, tree, body, then_end, else_end

    def branch(self, pc, end):
        """if / elseif / else at pc. -> next pc."""
        stop = self.if_chain(pc, end, "if")
        self.emit("end")
        self.forget_temps()
        return stop

    def if_chain(self, pc, end, keyword):
        got = self.if_extent(pc, end)
        if got is None:
            raise Unsupported("condition with no consistent structure")
        terms, tree, body, then_end, else_end = got
        self.prepare_cond(terms)
        cond = self.render_cond(tree, terms)
        self.promote([body, then_end])
        self.emit(f"{keyword} {cond.text} then")
        if else_end is None:
            self.nest(body, then_end)
            return then_end
        self.nest(body, then_end - 1)
        # luac compiles `elseif` exactly like an `if` filling the whole else
        # branch; re-emitting it as `else if ... end end` would add an `end`
        # and change nothing else, so collapse it back
        if self.is_single_if(then_end, else_end):
            self.forget_temps()
            self.if_chain(then_end, else_end, "elseif")
        else:
            self.emit("else")
            self.nest(then_end, else_end)
        return else_end

    def is_single_if(self, start, end):
        code = self.p.code
        if start >= end:
            return False
        k = start
        while k < end and self.is_operand(code[k]):
            if k in self.decl_pcs() or self.assigns_local(code[k]):
                return False
            k += 1
        if k >= end or code[k].op not in self.TEST_OPS:
            return False
        if self.value_shape_at(k, end):
            return False
        got = self.if_extent(start, end)
        if got is None:
            return False
        _, _, _, then_end, else_end = got
        return (else_end if else_end is not None else then_end) == end

    def value_shape_at(self, pc, end):
        terms = self.scan_terms(pc, end)
        return any(self._value_shape(terms[:n], end)
                   for n in range(len(terms), 0, -1))

    # -- loops ---------------------------------------------------------------
    def loop(self, head, back, end):
        """A loop whose last backward jump is at `back`. -> next pc.

        A backward JMP is only ever a loop in Lua 5.1. If the test right
        before it owns it, the loop tests at the bottom: repeat/until.
        Otherwise it is a while, whose condition (if any) is the run of tests
        at the head that exits to just past the back jump."""
        code = self.p.code
        exit_pc = back + 1
        self.promote([head])
        if back - 1 >= head and code[back - 1].op in self.TEST_OPS:
            return self.repeat_loop(head, back, end)
        shape = self.cond_shape(head, back, want_false=exit_pc)
        if shape is not None:
            terms, tree, body, _ = shape
            self.prepare_cond(terms)
            cond = self.render_cond(tree, terms)
            self.emit(f"while {cond.text} do")
        else:
            body = head
            self.emit("while true do")
        self.nest(body, back, loop_exit=exit_pc, head=head)
        self.emit("end")
        self.forget_temps()
        return exit_pc

    def repeat_loop(self, head, back, end):
        """`repeat body until cond`: the condition jumps back while false."""
        code = self.p.code
        exit_pc = back + 1
        decls = self.decl_pcs()
        chosen = None
        for c in range(head, back):
            terms = self.scan_terms(c, back + 1)
            if not terms or terms[-1].test + 1 != back:
                continue
            if any(d in decls for t in terms for d in range(t.start, t.test)):
                continue
            # nothing in the body may jump into the middle of the condition
            if any(code[p].op == "JMP" and c < self.target_of(code[p]) <= back
                   for p in range(head, c)):
                continue
            self._senses = [t.sense for t in terms]
            starts = [t.start for t in terms] + [exit_pc]
            for fuzzy in (False, True):
                tree = self.cond_tree([t.target for t in terms], starts,
                                      exit_pc, head, fuzzy)
                if tree is not None:
                    chosen = (c, terms, tree)
                    break
            if chosen:
                break
        if chosen is None:
            raise Unsupported("repeat/until with an unreadable condition")
        c, terms, tree = chosen
        self.emit("repeat")
        self.nest(head, c, loop_exit=exit_pc, head=head)
        cond = self.render_cond(tree, terms)
        self.emit(f"until {cond.text}")
        self.forget_temps()
        return exit_pc

    def nest(self, start, end, loop_exit=None, head=None):
        """Decompile a nested range one level further in."""
        self.indent += 1
        self.forget_temps()
        prev = self.loop_exit, self.loop_head
        scope = set(self.active)
        if loop_exit is not None:
            self.loop_exit = loop_exit
            self.loop_head = head
        try:
            self.block(start, end)
        finally:
            self.loop_exit, self.loop_head = prev
            self.indent -= 1
            # locals declared inside went out of scope with the block
            self.active = scope | (self.active &
                                   set(range(fixed_locals(self.p))))

    # LFIELDS_PER_FLUSH: luac flushes array items to the table every 50, and
    # SETLIST's C says which batch this is.
    FIELDS_PER_FLUSH = 50

    def table(self, pc, end):
        """Rebuild a table constructor starting at NEWTABLE. -> next pc.

        The constructor is not one instruction: luac creates the table, builds
        each array item in a register above it, flushes them with SETLIST, and
        writes keyed fields with SETTABLE as it meets them. All of that has to
        be gathered back into a single `{...}` expression, because emitting the
        pieces separately would compile to different instructions.

        Where it ends is recorded in the NEWTABLE itself: luac patches B and C
        with the number of array and keyed items once the constructor is
        closed (as "floating point bytes", exact below 8). Without that, the
        `self.x = ...` statements that usually follow `local self = {}` look
        exactly like more keyed items.
        """
        code = self.p.code
        head = code[pc]
        A = head.A
        want_array, want_hash = fb_floor(head.B), fb_floor(head.C)
        # items in the order they were evaluated: (seq, kind, key, value)
        items = []
        n_array = n_hash = 0
        seq = 0
        last_write = {}                 # register -> seq it was last written
        j = pc + 1
        top_array, top_hash = fb_int(head.B), fb_int(head.C)
        saved, self.in_expr = self.in_expr, True
        try:
            while j < end:
                if n_array >= want_array and n_hash >= want_hash:
                    # the counts are met, but a count of 8 or more is stored
                    # rounded up, and a final open item (`{f()}`) is not
                    # counted at all. Keep going only while another item
                    # really follows; any count in the same rounding bucket
                    # compiles identically.
                    ahead = self.item_ahead(j, A, end)
                    if ahead is None:
                        break
                    if ahead != "open" and n_array >= top_array and \
                            n_hash >= top_hash:
                        break
                n = code[j]
                seq += 1
                if n.op == "SETLIST" and n.A == A:
                    batch, step = n.C, 1
                    if batch == 0:
                        # the batch number did not fit in C: it is the next
                        # "instruction", stored raw
                        if j + 1 >= len(code):
                            raise Unsupported("SETLIST missing its batch word")
                        batch, step = code[j + 1].raw, 2
                    if n.B == 0:
                        if self.multi_reg is None or self.multi_reg <= A:
                            raise Unsupported("open SETLIST with no multi-value source")
                        count = self.multi_reg - A
                        self.multi_reg = None
                    else:
                        count = n.B
                    base = (batch - 1) * self.FIELDS_PER_FLUSH
                    for k in range(1, count + 1):
                        val = self.reg(A + k)
                        items.append((last_write.get(A + k, seq), "array",
                                      base + k, val))
                    n_array += count
                    j += step
                    continue
                if n.op == "SETTABLE" and n.A == A:
                    if n.B >= BITRK:
                        key = Expr(self.const_text(self.k(n.B - BITRK)),
                                   P_ATOM)
                        name = self.k(n.B - BITRK)
                        name = name.value.decode("latin-1", "replace") \
                            if name.kind == "string" else None
                    else:
                        key, name = self.reg(n.B), None
                    items.append((seq, "hash", (key, name), self.rk(n.C)))
                    n_hash += 1
                    j += 1
                    continue
                if n.op == "NEWTABLE" and n.A > A:
                    j = self.table(j, end)          # a table inside a table
                    last_write[n.A] = seq
                    continue
                if n.op in self.TEST_OPS:
                    got = self.value_expr(j, end)
                    if got is None:
                        raise Unsupported("test inside a table constructor")
                    for r in writes_of(code[got - 1]):
                        last_write[r] = seq
                    j = got
                    continue
                w = writes_of(n)
                if w and all(r > A for r in w) and n.op not in ("JMP",) and \
                        not (n.op == "CALL" and n.C == 1):
                    self.execute(n)
                    for r in w:
                        last_write[r] = seq
                    if self.skip_until is not None:
                        j, self.skip_until = self.skip_until, None
                    else:
                        j += 1
                    continue
                break
        finally:
            self.in_expr = saved
        if n_array < want_array or n_hash < want_hash:
            raise Unsupported("table constructor ended before its items")

        parts = []
        for _, kind, key, val in sorted(items, key=lambda it: it[0]):
            if kind == "array":
                parts.append(val.text)
                continue
            key, name = key
            if name is not None and is_identifier(name):
                parts.append(f"{name} = {val.text}")
            else:
                parts.append(f"[{key.text}] = {val.text}")
        text = "{" + ", ".join(parts) + "}" if parts else "{}"
        # Long or nested constructors one item per line. Line breaks cost
        # nothing: the shipped bytecode carries no line information. A
        # multi-line item (a nested table, a function) moves one level in.
        if len(text) > 100 or any("\n" in p for p in parts):
            pad = "  " * self.indent
            text = "{\n" + ",\n".join(
                pad + "  " + p.replace("\n", "\n  ") for p in parts) + \
                "\n" + pad + "}"
        at = pc if self.is_decl(A, pc) else max(pc, j - 1)
        value = Expr(text, P_ATOM)
        value.hint = "args" if text == "{...}" else \
            (metatable_hint(self.p, max(pc, j - 1), A) or "t")
        value.newk = self.newk_between(pc, j)
        self.store(A, value, at)
        return j

    def item_ahead(self, j, A, end):
        """Does another item of the table in R(A) start at j?

        -> "open" if it ends in a SETLIST with an open count, "item" if in
        any other SETLIST/SETTABLE on the table, None if the constructor is
        over: something reads the table, overwrites a register at or below
        it, or completes a statement."""
        code = self.p.code
        k = j
        while k < end:
            ins = code[k]
            if ins.op in ("SETTABLE", "SETLIST") and ins.A == A:
                return "open" if ins.op == "SETLIST" and ins.B == 0 else "item"
            if A in reads_of(ins):
                return None
            if ins.op in ("SETTABLE", "SETLIST") and ins.A > A:
                k += 1                  # filling a table nested in the item
                continue
            if ins.op in self.TEST_OPS or ins.op == "JMP":
                k += 1
                continue
            w = writes_of(ins)
            if not w or any(r <= A for r in w) or \
                    (ins.op == "CALL" and ins.C == 1):
                return None
            if ins.op == "CLOSURE" and ins.Bx < len(self.p.protos):
                k += self.p.protos[ins.Bx].nups
            k += 1
        return None

    def generic_for(self, pc, end):
        """`for k, v in f, s, var do ... end`. -> next pc.

        The setup leaves the iterator triple in A, A+1, A+2 and the loop
        variables live at A+3 onward. Control enters by jumping straight to
        the TFORLOOP at the bottom, which is what distinguishes this from an
        ordinary forward jump.
        """
        code = self.p.code
        test_pc = self.target_of(code[pc])
        ctrl = code[test_pc]
        A, nvars = ctrl.A, ctrl.C
        if nvars < 1:
            raise Unsupported("TFORLOOP with no loop variables")
        # the iterator is normally one call yielding all three values
        src = self.regs.get(A)
        if src is not None and src.multi:
            iter_text = src.text
        else:
            parts = []
            for reg in (A, A + 1, A + 2):
                if reg not in self.regs:
                    break
                parts.append(self.regs[reg].text)
            if not parts:
                raise Unsupported("generic for with an unreadable iterator")
            iter_text = ", ".join(parts)
        for r in (A, A + 1, A + 2):         # consumed by the loop header
            self.regs.pop(r, None)
            self.pending_at.pop(r, None)
        self.promote([pc + 1, test_pc + 2])
        if iter_text.startswith("ipairs("):
            bases = ["i", "v"]
        elif iter_text.startswith("pairs("):
            bases = ["k", "v"]
        else:
            bases = ["k", "v"] if nvars > 1 else ["v"]
        names = []
        loop_vars = set()
        for n in range(nvars):
            base = bases[n] if n < len(bases) else "v"
            self.bind(A + 3 + n, self.pick_name(base))
            names.append(self.names[A + 3 + n])
            loop_vars.add(A + 3 + n)
        self.emit(f"for {', '.join(names)} in {iter_text} do")
        self.nest(pc + 1, test_pc, loop_exit=test_pc + 2, head=pc + 1)
        self.active -= loop_vars
        self.emit("end")
        self.forget_temps()
        return test_pc + 2

    def numeric_for(self, pc, end):
        """`for v = init, limit, step do ... end`. -> next pc.

        luac keeps three hidden control registers at A, A+1 and A+2 (the
        counter, the limit and the step) and exposes the loop variable as a
        fourth at A+3. FORPREP jumps forward to the matching FORLOOP, which
        jumps back to the top of the body.

        The step is written out only when it is not 1: luac always emits a
        step, so re-emitting `, 1` would add a constant the original did not
        have.
        """
        code = self.p.code
        ins = code[pc]
        A = ins.A
        loop_pc = self.target_of(ins)
        if loop_pc >= end or code[loop_pc].op != "FORLOOP":
            raise Unsupported("FORPREP not matched by a FORLOOP")
        init, limit, step = self.reg(A), self.reg(A + 1), self.reg(A + 2)
        for r in (A, A + 1, A + 2):         # consumed by the loop header
            self.regs.pop(r, None)
            self.pending_at.pop(r, None)
        self.promote([pc + 1, loop_pc + 1])
        var = self.pick_name("i", ("j", "k", "n", "m"))
        header = f"for {var} = {init.text}, {limit.text}"
        if step.text != "1":
            header += f", {step.text}"
        self.emit(header + " do")
        self.bind(A + 3, var)
        self.nest(pc + 1, loop_pc, loop_exit=loop_pc + 1, head=pc + 1)
        self.active.discard(A + 3)
        self.emit("end")
        self.forget_temps()
        return loop_pc + 1

    def forget_temps(self):
        """Drop scratch registers at a control-flow edge.

        A temporary's value is only meaningful along one path, so carrying it
        across a branch would let an expression from the then-branch leak into
        the else-branch. Declared locals survive, because they do.
        """
        for reg in list(self.regs):
            if reg not in self.active:
                del self.regs[reg]
                self.pending_at.pop(reg, None)

    # -- loads -----------------------------------------------------------
    def op_LOADK(self, i):
        self.reg_kidx[i.A] = i.Bx
        c = self.k(i.Bx)
        value = Expr(self.const_text(c), P_ATOM)
        m = _HASH_NOTE.search(value.text)
        value.hint = camel(m.group(1)) if m else \
            {"number": "n", "string": "str"}.get(c.kind, "v")
        self.store(i.A, value, i.pc)

    def op_LOADNIL(self, i):
        """`local a, b` - or the nils filling a short assignment."""
        new = [r for r in range(i.A, i.B + 1)
               if not self.in_expr and r not in self.active
               and self.is_decl(r, i.pc)]
        if new and new == list(range(new[0], i.B + 1)):
            names = [self.unnamed(r) for r in new]
            self.emit("local " + ", ".join(names))
        for r in range(i.A, i.B + 1):
            if r in self.active and r in new:
                continue
            if r in self.active:
                self.emit(f"{self.names[r]} = nil")
            else:
                self.regs[r] = Expr("nil", P_ATOM)

    def op_CLOSE(self, i):
        """Close upvalues at a block end. Implicit in the source."""

    def op_LOADBOOL(self, i):
        if i.C:
            raise Unsupported("LOADBOOL with skip (needs branch handling)")
        value = Expr("true" if i.B else "false", P_ATOM)
        value.hint = "flag"
        self.store(i.A, value, i.pc)

    def op_MOVE(self, i):
        self.store(i.A, self.reg(i.B).copy(), i.pc)

    def op_VARARG(self, i):
        if i.B != 0:
            raise Unsupported("VARARG with a fixed result count")
        self.regs[i.A] = Expr("...", P_ATOM, multi=True)
        self.multi_reg = i.A

    # -- upvalues and closures -------------------------------------------
    def upval(self, index):
        if index >= len(self.upval_names):
            raise Unsupported(f"upvalue {index} with no binding from the parent")
        return self.upval_names[index]

    def op_GETUPVAL(self, i):
        value = Expr(self.upval(i.B), P_ATOM)
        value.hint = self.upval(i.B)
        self.store(i.A, value, i.pc)

    def op_SETUPVAL(self, i):
        self.emit(f"{self.upval(i.B)} = {self.store_value(i, i.A)}")

    def op_CLOSURE(self, i):
        """R(A) := closure(proto[Bx]), bound to the upvalues that follow.

        Lua 5.1 puts the binding in PSEUDO instructions directly after
        CLOSURE - one per upvalue, MOVE to capture one of this function's
        registers, GETUPVAL to pass one of its own upvalues through. They are
        never executed; `run` skips past them because op_CLOSURE consumes
        them here.
        """
        if i.Bx >= len(self.p.protos):
            raise Unsupported("CLOSURE referring to a missing proto")
        child = self.p.protos[i.Bx]
        code = self.p.code
        names = []
        # `local function f` is in scope inside its own body, which is
        # visible as the closure capturing the register it is stored in
        recursive = any(code[i.pc + 1 + n].op == "MOVE" and
                        code[i.pc + 1 + n].B == i.A
                        for n in range(child.nups)
                        if i.pc + 1 + n < len(code))
        local_fn = recursive and i.A not in self.active and \
            self.is_decl(i.A, i.pc)
        if local_fn:
            self.bind(i.A, self.pick_name("fn"))
        for n in range(child.nups):
            pc = i.pc + 1 + n
            if pc >= len(code):
                raise Unsupported("CLOSURE with truncated upvalue bindings")
            binding = code[pc]
            if binding.op == "MOVE":
                reg = binding.B
                if reg not in self.active:
                    raise Unsupported("closure capturing a temporary")
                # the child picks its own names against the ones it
                # captures, so a captured placeholder must be final now
                if self.names[reg] in self.deferred and \
                        self.deferred[self.names[reg]] is None:
                    self.settle_name(reg, "v")
                names.append(self.names[reg])
            elif binding.op == "GETUPVAL":
                names.append(self.upval(binding.B))
            else:
                raise Unsupported(f"CLOSURE bound by {binding.op}")
        self.skip_until = i.pc + 1 + child.nups
        # `function T:m(...)`: when the closure is stored straight into a
        # field of a plain table path and its first parameter is used as an
        # object, name that parameter `self`. Compiles identically to
        # `T.m = function(self, ...)`.
        after = code[self.skip_until] if self.skip_until < len(code) else None
        method = False
        if after is not None and after.op == "SETTABLE" and \
                after.C == i.A and after.B >= BITRK and \
                child.numparams >= 1 and uses_as_object(child, 0):
            key = self.k(after.B - BITRK)
            obj = self.regs.get(after.A)
            method = (key.kind == "string" and obj is not None and
                      is_identifier(key.value.decode("latin-1", "replace"))
                      and PATH_RE.match(obj.text) is not None)
        params, rest = function_text(child, names, self.indent,
                                     self.depth + 1, method, self.ctx)
        if local_fn:
            self.emit(f"local function {self.names[i.A]}({params}){rest}")
            return
        value = Expr(f"function({params}){rest}", P_ATOM)
        value.hint = "fn"
        value.fn = (params, rest, method)
        self.store(i.A, value, i.pc)

    # -- globals and tables ----------------------------------------------
    def op_GETGLOBAL(self, i):
        self.reg_kidx[i.A] = i.Bx
        name = self.k(i.Bx).value.decode("latin-1", "replace")
        value = Expr(name, P_ATOM)
        value.hint = camel(name)
        self.store(i.A, value, i.pc)

    def op_SETGLOBAL(self, i):
        name = self.k(i.Bx).value.decode("latin-1", "replace")
        fn = self.regs.get(i.A)
        fn = fn.fn if fn is not None and i.A not in self.active else None
        value = self.store_value(i, i.A)
        if fn is not None and value == f"function({fn[0]}){fn[1]}" and \
                is_identifier(name):
            self.emit(f"function {name}({fn[0]}){fn[1]}")
            return
        self.emit(f"{name} = {value}")

    def op_GETTABLE(self, i):
        obj = self.reg(i.B)
        if i.C >= BITRK:
            self.store(i.A, self.field(obj, self.k(i.C - BITRK)), i.pc)
        else:
            self.store(i.A, Expr(
                f"{obj.paren(P_ATOM)}[{self.reg(i.C).text}]", P_ATOM), i.pc)

    def op_SETTABLE(self, i):
        obj = self.reg(i.A)
        if i.B >= BITRK:
            target = self.field(obj, self.k(i.B - BITRK))
        else:
            target = Expr(f"{obj.paren(P_ATOM)}[{self.reg(i.B).text}]",
                          P_ATOM)
        fn = None
        if i.C < BITRK and i.C not in self.active and i.C in self.regs:
            fn = self.regs[i.C].fn
        if i.C >= BITRK:
            val = self.rk(i.C).text
        else:
            val = self.store_value(i, i.C)
        # `function a.b.c(...)` / `function a.b:c(...)` for a closure stored
        # into a field of a plain dotted path
        if fn is not None and val == f"function({fn[0]}){fn[1]}" and \
                PATH_RE.match(target.text):
            params, rest, method = fn
            if method:
                head, _, last = target.text.rpartition(".")
                rest_params = ", ".join(params.split(", ")[1:])
                self.emit(f"function {head}:{last}({rest_params}){rest}")
            else:
                self.emit(f"function {target.text}({params}){rest}")
            return
        self.emit(f"{target.text} = {val}")

    # -- arithmetic ------------------------------------------------------
    def _binop(self, i):
        sym, prec = BINOPS[i.op]
        lhs, rhs = self.rk(i.B), self.rk(i.C)
        # left-associative: the right operand needs parens at equal precedence
        value = Expr(f"{lhs.paren(prec)} {sym} {rhs.paren(prec + 1)}", prec)
        value.hint = "n"
        self.store(i.A, value, i.pc)

    op_ADD = op_SUB = op_MUL = op_DIV = op_MOD = op_POW = _binop

    def op_UNM(self, i):
        operand = self.reg(i.B).paren(P_UNARY)
        if operand.startswith("-"):
            operand = " " + operand         # `- -x`, and never `---[[`
        value = Expr(f"-{operand}", P_UNARY)
        value.hint = "n"
        self.store(i.A, value, i.pc)

    def op_NOT(self, i):
        value = Expr(f"not {self.reg(i.B).paren(P_UNARY)}", P_UNARY)
        value.hint = "flag"
        self.store(i.A, value, i.pc)

    def op_LEN(self, i):
        value = Expr(f"#{self.reg(i.B).paren(P_UNARY)}", P_UNARY)
        value.hint = "count"
        self.store(i.A, value, i.pc)

    def op_CONCAT(self, i):
        parts = [self.reg(r).paren(P_CONCAT + 1) for r in range(i.B, i.C + 1)]
        value = Expr(" .. ".join(parts), P_CONCAT)
        value.hint = "str"
        self.store(i.A, value, i.pc)

    # -- calls -----------------------------------------------------------
    def op_SELF(self, i):
        obj = self.reg(i.B)
        if i.C >= BITRK:
            key = self.k(i.C - BITRK)
        else:
            # past 256 constants the name cannot be an RK operand, so luac
            # loads it into a register first; it is still a constant
            kidx = self.reg_kidx.get(i.C)
            self.reg(i.C)
            key = self.k(kidx) if kidx is not None else None
        name = key.value.decode("latin-1", "replace") \
            if key is not None and key.kind == "string" else None
        if name is None or not is_identifier(name):
            raise Unsupported("SELF with a computed method name")
        self.regs[i.A + 1] = obj.copy()
        # consumed by CALL to re-form obj:method(...)
        self.regs[i.A] = Expr(f"{obj.paren(P_ATOM)}:{name}", P_ATOM,
                              method=True)

    def _args(self, i):
        """The argument list for a CALL / TAILCALL.

        B == 0 means "every value from A+1 to the top of the stack", which
        happens when the last argument is itself a call or `...` that was
        left open so all of its results spill through: f(g()) passes every
        result of g, not just the first. The open value sits in the register
        recorded by the instruction that produced it.
        """
        if i.B == 0:
            if self.multi_reg is None or self.multi_reg <= i.A:
                raise Unsupported("open CALL with no multi-value source")
            fixed = [self.reg(r).text for r in range(i.A + 1, self.multi_reg)]
            return fixed + [self.reg(self.multi_reg).text]
        return [self.reg(r).text for r in range(i.A + 1, i.A + i.B)]

    def op_CALL(self, i):
        fn = self.reg(i.A)
        args = self._args(i)
        if fn.method:
            args = args[1:]          # receiver is implicit in a:b(...) form
        call = Expr(f"{fn.paren(P_ATOM)}({', '.join(args)})", P_ATOM,
                    multi=True)
        call.hint = call_hint(fn.text, args)
        if i.C == 1:
            self.emit(call.text)     # results discarded: a statement
            for r in list(self.regs):
                if r >= i.A:
                    del self.regs[r]
            self.multi_reg = None
        elif i.C == 2:
            self.store(i.A, call, i.pc)
            self.multi_reg = None
        elif i.C == 0:
            # results left open, to be consumed by an enclosing call or return
            self.regs[i.A] = call
            self.multi_reg = i.A
        elif i.C == 4 and i.A in self.iter_bases:
            # the iterator triple for a generic for: one expression, not
            # three locals
            self.regs[i.A] = call
            self.multi_reg = i.A
        else:
            # several results at once: `local a, b = f()`
            n = i.C - 1
            targets = list(range(i.A, i.A + n))
            if all(self.is_decl(t, i.pc) for t in targets):
                names = []
                for n_, t in enumerate(targets):
                    self.bind(t, self.pick_name(call.hint if n_ == 0 else "v"))
                    names.append(self.names[t])
                self.emit(f"local {', '.join(names)} = {call.text}")
                self.multi_reg = None
            else:
                # a multiple assignment's values; multi_store takes them
                self.regs[i.A] = call
                for t in targets[1:]:
                    self.regs[t] = Expr(MULTI_CONT, P_ATOM)
                self.multi_reg = None

    def op_TAILCALL(self, i):
        fn = self.reg(i.A)
        args = self._args(i)
        if fn.method:
            args = args[1:]
        self.emit(f"return {fn.paren(P_ATOM)}({', '.join(args)})")
        # luac always emits a RETURN after a TAILCALL. It is unreachable
        # boilerplate, not a second return statement in the source.
        self.after_tailcall = True

    def op_RETURN(self, i):
        if self.after_tailcall:
            self.after_tailcall = False
            return                    # luac's boilerplate after TAILCALL
        if i.B == 1:
            # luac appends a bare RETURN to every proto; only an explicit one
            # in the middle of the body is real source
            if i.pc != len(self.p.code) - 1:
                self.emit("return")
            return
        if i.B == 0:
            # return everything from A to the top: `return f()`, passing all
            # of f's results through rather than just the first
            if self.multi_reg is None or self.multi_reg < i.A:
                raise Unsupported("open RETURN with no multi-value source")
            fixed = [self.reg(r).text for r in range(i.A, self.multi_reg)]
            vals = fixed + [self.reg(self.multi_reg).text]
            self.emit(f"return {', '.join(vals)}")
            return
        vals = [self.reg(r).text for r in range(i.A, i.A + i.B - 1)]
        self.emit(f"return {', '.join(vals)}")


def param_list(p, names=None):
    names = names or {}
    params = [names.get(i, f"p{i + 1}") for i in range(p.numparams)]
    if p.is_vararg:
        params.append("...")
    return ", ".join(params)


def function_text(p, upval_names, indent, depth=1, method=False,
                  context=None):
    """A nested proto as (parameter list, everything after it)."""
    d = Decompiler(p, upval_names, indent + 1, None, depth, method, context)
    body = d.run()
    pad = "  " * indent
    params = param_list(p, d.names)
    if not body.strip():
        return params, " end"
    return params, f"\n{body}\n{pad}end"


def decompile_proto(p, as_function=False, hash_names=None,
                    hash_values=None, fe_values=None, hash_text=None):
    """-> source text for one proto, or raise Unsupported.

    as_function wraps the body in a `function(...) ... end` declaration. A
    nested proto's parameters live in its lowest registers, and emitting its
    body on its own turns every parameter read into a GLOBAL read - which
    compiles to completely different instructions. Wrapping makes them
    parameters again so the round trip is comparable.
    """
    context = {"globals": chunk_globals(p),
               "hash_names": hash_names or {},
               "hash_values": hash_values,
               # {hash: display text} for text IDs with no known name
               "hash_text": hash_text or {},
               # {proto path: integral values that were 0xFE}, when known
               "fe_values": fe_values}
    d = Decompiler(p, indent=1 if as_function else 0, context=context)
    body = d.run()
    if not as_function:
        return body
    return (f"return function({param_list(p)})\n"
            f"{body}\n"
            f"end\n")


# -------------------------------------------------- NB1 number types
# NB1's compiler has two representations for a number: an ordinary double,
# and a 64-bit integer (constant type 0xFE). Which one a constant gets is
# decided by how the SOURCE spells it - checked against NB2's plaintext copy
# of the same code: `self.xtxtUID = 0` and `SetStuntFearDelta(100)` are 0xFE
# in NB1, `self.fightUntilXHitPointThreashold = 20.0` is a double. Hashes
# are integers too. luac51 knows only doubles, so after compiling edited
# source the types have to be put back, by the same spelling rule.
_NUM_TOKEN = re.compile(
    r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def number_tokens(src):
    """[(line, text)] for every numeric literal, skipping strings, comments
    and identifiers."""
    out = []
    i, n, line = 0, len(src), 1

    def long_bracket(at):
        m = re.match(r"\[(=*)\[", src[at:])
        return len(m.group(1)) if m else None

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif src.startswith("--", i):
            level = long_bracket(i + 2)
            if level is not None:
                close = "]" + "=" * level + "]"
                j = src.find(close, i)
                j = n if j < 0 else j + len(close)
            else:
                j = src.find("\n", i)
                j = n if j < 0 else j
            line += src.count("\n", i, j)
            i = j
        elif c == "[" and long_bracket(i) is not None:
            close = "]" + "=" * long_bracket(i) + "]"
            j = src.find(close, i)
            j = n if j < 0 else j + len(close)
            line += src.count("\n", i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    line += 1
                j += 1
            i = j + 1
        elif c.isalpha() or c == "_":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            i = j
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM_TOKEN.match(src, i)
            out.append((line, m.group()))
            i = m.end()
        else:
            i += 1
    return out


def literal_value(text):
    if text[:2] in ("0x", "0X"):
        return float(int(text, 16))
    return float(text)


def is_float_spelling(text):
    return text[:2] not in ("0x", "0X") and any(ch in text for ch in ".eE")


def integer_constants(src, root):
    """Which integral number constants the source spells as integers.

    root must be compiled WITH line info. -> {proto path: set of values}
    for constants written like `20` (NB1 type 0xFE); ones written like
    `20.0` are left out (they stay doubles). A constant no literal accounts
    for - folded from an expression - counts as an integer, the majority
    representation in the shipped scripts."""
    tokens = {}
    for line, text in number_tokens(src):
        tokens.setdefault(line, []).append(text)
    out = {}
    for p in root.walk():
        ints = set()
        lines_of = {}
        for ins in p.code:
            for k in constants_used(ins):
                if ins.pc < len(p.lineinfo):
                    lines_of.setdefault(k, set()).add(p.lineinfo[ins.pc])
        for k, c in enumerate(p.consts):
            if c.kind != "number" or c.value != int(c.value):
                continue
            want = abs(c.value)
            kinds = set()
            for back in range(0, 4):             # the literal may sit a line
                for ln in lines_of.get(k, ()):   # or two above its opcode
                    for t in tokens.get(ln - back, ()):
                        if literal_value(t) == want:
                            kinds.add(is_float_spelling(t))
                if kinds:
                    break
            if kinds != {True}:
                ints.add(int(c.value))
        out[p.path] = ints
    return out


def spelling_conflicts(src, root):
    """Whole numbers a function writes both as `20` and as `20.0`. A function
    stores each value once, so both spellings get one type.

    root must be compiled WITH line info. -> [(line, text, value, proto
    path), ...] for every literal of such a value, in source order."""
    tokens = {}
    for line, text in number_tokens(src):
        tokens.setdefault(line, []).append(text)
    out = set()
    for p in root.walk():
        lines_of = {}
        for ins in p.code:
            for k in constants_used(ins):
                if ins.pc < len(p.lineinfo):
                    lines_of.setdefault(k, set()).add(p.lineinfo[ins.pc])
        for k, c in enumerate(p.consts):
            if c.kind != "number" or c.value != int(c.value):
                continue
            want = abs(c.value)
            seen = [(ln, t) for ln in lines_of.get(k, ())
                    for t in tokens.get(ln, ()) if literal_value(t) == want]
            if len({is_float_spelling(t) for _, t in seen}) == 2:
                out.update((ln, t, int(c.value), p.path) for ln, t in seen)
    return sorted(out)


def original_number_types(std_raw):
    """Per proto, the integral values the ORIGINAL chunk held as 0xFE and
    as doubles, from its transcode with raw hash placeholders."""
    fe, dbl = {}, {}
    for p in parse(std_raw).walk():
        a, b = set(), set()
        for c in p.consts:
            if c.kind == "string" and c.value.startswith(b"__hash_0x"):
                v = int(c.value[7:], 16)
                a.add(v - (1 << 64) if v >> 63 else v)
            elif c.kind == "number" and c.value == int(c.value):
                b.add(int(c.value))
        fe[p.path], dbl[p.path] = a, b
    return fe, dbl


def fe_numbers(src, root_lines, original=None):
    """{proto path: values to emit as 0xFE}: the original function's own
    choice for every constant it already had, the spelling rule for new
    ones."""
    spelled = integer_constants(src, root_lines)
    fe, dbl = original or ({}, {})
    out = {}
    for p in root_lines.walk():
        mine = set()
        for c in p.consts:
            if c.kind != "number" or c.value != int(c.value):
                continue
            v = int(c.value)
            if v in fe.get(p.path, ()):
                mine.add(v)
            elif v in dbl.get(p.path, ()):
                continue
            elif v in spelled.get(p.path, ()):
                mine.add(v)
        out[p.path] = mine
    return out


# --------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("disasm", help="print the instruction listing")
    d.add_argument("file")

    c = sub.add_parser("decompile", help="reconstruct source (work in progress)")
    c.add_argument("file")
    c.add_argument("-o", "--out")

    a = ap.parse_args()
    data = Path(a.file).read_bytes()
    root = parse(data)
    if a.cmd == "disasm":
        print("\n".join(disassemble(root)))
        return 0
    try:
        src = decompile_proto(root)
    except Unsupported as e:
        sys.exit(f"not yet supported: {e}")
    if a.out:
        Path(a.out).write_text(src + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {a.out}")
    else:
        print(src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
