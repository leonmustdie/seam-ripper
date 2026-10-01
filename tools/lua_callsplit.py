#!/usr/bin/env python3
"""Find Lua call sites and split their arguments into positional slots."""
import re
from dataclasses import dataclass, field


@dataclass
class Arg:
    text: str
    start: int   # absolute offset into src of first char of the argument
    end: int     # absolute offset one past the last char


@dataclass
class Call:
    func: str
    args: list = field(default_factory=list)
    call_start: int = 0    # offset of the function name
    args_start: int = 0    # offset just after the opening paren
    args_end: int = 0      # offset of the closing paren


_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = set(_OPEN.values())


def _skip_string(src, i):
    """i points at a quote or long-bracket opener. Return index past the
    string, or None if this isn't actually a string start."""
    c = src[i]
    if c in "\"'":
        j = i + 1
        while j < len(src):
            if src[j] == "\\":
                j += 2
                continue
            if src[j] == c:
                return j + 1
            j += 1
        return j
    if c == "[":
        m = re.match(r"\[(=*)\[", src[i:])
        if m:
            close = "]" + m.group(1) + "]"
            k = src.find(close, i + m.end())
            return len(src) if k < 0 else k + len(close)
    return None


def _match_call_args(src, open_paren):
    """open_paren points at '('. Walk to the matching ')', splitting the
    top-level comma-separated arguments. Returns (args, close_index)."""
    args = []
    depth = 0
    i = open_paren
    arg_start = open_paren + 1
    while i < len(src):
        c = src[i]
        if c in "\"'" or (c == "[" and re.match(r"\[=*\[", src[i:])):
            nxt = _skip_string(src, i)
            if nxt is not None:
                i = nxt
                continue
        if c in _OPEN:
            depth += 1
            i += 1
            continue
        if c in _CLOSE:
            depth -= 1
            if depth == 0:
                seg = src[arg_start:i]
                if seg.strip():
                    args.append(_mk_arg(src, arg_start, i))
                return args, i
            i += 1
            continue
        if c == "," and depth == 1:
            args.append(_mk_arg(src, arg_start, i))
            arg_start = i + 1
            i += 1
            continue
        i += 1
    raise ValueError(f"unbalanced call starting at {open_paren}")


def _mk_arg(src, lo, hi):
    text = src[lo:hi]
    stripped = text.strip()
    left = lo + (len(text) - len(text.lstrip()))
    right = hi - (len(text) - len(text.rstrip()))
    return Arg(stripped, left, right)


def find_calls(src, func):
    """Find every call to `func`, which may be a bare name (AddFear) or an
    object-method form matched by its trailing method name (:AddFear). The
    receiver, if any, is not part of args; only the parenthesized list is."""
    name = func.lstrip(":.")
    pat = re.compile(r"(?<![\w.:])([\w.]+[.:])?" + re.escape(name) + r"\s*\(")
    calls = []
    for m in pat.finditer(src):
        open_paren = src.index("(", m.end() - 1)
        args, close = _match_call_args(src, open_paren)
        calls.append(Call(func=name, args=args, call_start=m.start(),
                          args_start=open_paren + 1, args_end=close))
    return calls
