#!/usr/bin/env python3
r"""Make decompiler output parse as Lua 5.1 again."""
import re
import sys

__all__ = ["repair", "Report", "lex", "strip_decompiler_errors"]

# --------------------------------------------------------------------- lexer
# Enough Lua 5.1 lexing to know whether a given offset is code, a string or a
# comment. Deliberately small: it never needs to build a tree, only to mask
# out the regions a textual rewrite must not touch.

_LONG_OPEN = re.compile(r"\[(=*)\[")


def lex(src):
    """Yield (kind, start, end) spans covering src exactly.

    kind is one of: "code", "string", "comment".
    """
    i, n = 0, len(src)
    start = 0
    while i < n:
        c = src[i]
        # -- comment (line or long)
        if c == "-" and src.startswith("--", i):
            if start < i:
                yield ("code", start, i)
            j = i + 2
            m = _LONG_OPEN.match(src, j)
            if m:
                close = "]" + "=" * len(m.group(1)) + "]"
                k = src.find(close, m.end())
                j = n if k < 0 else k + len(close)
            else:
                k = src.find("\n", j)
                j = n if k < 0 else k
            yield ("comment", i, j)
            i = start = j
            continue
        # -- long string
        if c == "[":
            m = _LONG_OPEN.match(src, i)
            if m:
                if start < i:
                    yield ("code", start, i)
                close = "]" + "=" * len(m.group(1)) + "]"
                k = src.find(close, m.end())
                j = n if k < 0 else k + len(close)
                yield ("string", i, j)
                i = start = j
                continue
        # -- quoted string
        if c in "\"'":
            if start < i:
                yield ("code", start, i)
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    j += 1
                    break
                if src[j] == "\n":          # unterminated; bail at the line
                    break
                j += 1
            yield ("string", i, j)
            i = start = j
            continue
        i += 1
    if start < n:
        yield ("code", start, n)


def _code_mask(src):
    """bytearray, 1 where src[i] is ordinary code (not string/comment)."""
    mask = bytearray(len(src))
    for kind, a, b in lex(src):
        if kind == "code":
            for i in range(a, b):
                mask[i] = 1
    return mask


# ------------------------------------------------------------------- report
class Report:
    """What repair() changed and what it could not change."""

    def __init__(self):
        self.self_refs = 0        # colon-as-value rewrites
        self.computed_refs = 0    # `obj:[expr]` rewrites
        self.lone_semis = 0       # lone `;` removals/moves
        self.decompiler_errors = 0
        self.gave_up = 0          # `.end` markers: luadec quit mid-expression
        self.notes = []

    @property
    def unrecoverable(self):
        """True if the source contains damage no rewrite can fix."""
        return self.gave_up > 0

    @property
    def changed(self):
        return self.self_refs + self.computed_refs + self.lone_semis

    def summary(self):
        bits = []
        if self.self_refs:
            bits.append(f"{self.self_refs} method-reference")
        if self.computed_refs:
            bits.append(f"{self.computed_refs} computed-method-reference")
        if self.lone_semis:
            bits.append(f"{self.lone_semis} empty-statement")
        s = "repaired " + ", ".join(bits) if bits else "no repairs needed"
        if self.decompiler_errors:
            s += f"; {self.decompiler_errors} decompiler warning(s)"
        if self.gave_up:
            s += (f"; {self.gave_up} UNRECOVERABLE spot(s) where the "
                  f"decompiler quit mid-expression")
        return s

    def __repr__(self):
        return f"<Report {self.summary()}>"


# ------------------------------------------------------------------- fix 1
# `obj:Method` used as a value -> `obj.Method`.
#
# A colon is a method CALL only when the name after it is immediately
# followed by the call's arguments: `(`, a string literal, or a table
# constructor. Anything else (`,` `)` `=` end-of-line ...) means luadec
# printed a bare method reference, which Lua 5.1 will not parse.
_COLON = re.compile(r":\s*([A-Za-z_]\w*)")
# what legally follows a method name in a real call
_CALL_START = re.compile(r"[\s\n]*[(\"'{]|[\s\n]*\[=*\[")

# The same defect with a COMPUTED method name. luadec flags these itself with
# "-- DECOMPILER ERROR at PC...: [name] should be a SELF Operator":
#
#     createUnlockable, acc = createUnlockable:[cond], createUnlockable
#
# Lua has no `obj:[expr]` syntax at all (the colon form only ever takes a
# literal name). `obj[expr]` is the equivalent lookup, and - exactly as with
# the named case above - the receiver is already sitting in the sibling
# register, so dropping the colon is the faithful rewrite.
_COLON_INDEX = re.compile(r"(?<!:):\s*(?=\[)")


def fix_method_refs(src, report, mask=None):
    if mask is None:
        mask = _code_mask(src)
    out = []
    last = 0
    for m in _COLON.finditer(src):
        if not mask[m.start()]:
            continue
        # `::label::` - not Lua 5.1, but never rewrite it
        if src.startswith("::", m.start()):
            continue
        if m.start() and src[m.start() - 1] == ":":
            continue
        if _CALL_START.match(src, m.end()):
            continue                       # genuine call, leave alone
        out.append(src[last:m.start()])
        out.append("." + m.group(1))
        last = m.end()
        report.self_refs += 1
    out.append(src[last:])
    return "".join(out)


def fix_computed_method_refs(src, report, mask=None):
    """`obj:[expr]` -> `obj[expr]` (SELF with a non-constant method name)."""
    if mask is None:
        mask = _code_mask(src)
    out = []
    last = 0
    for m in _COLON_INDEX.finditer(src):
        if not mask[m.start()]:
            continue
        out.append(src[last:m.start()])
        last = m.end()
        report.computed_refs += 1
    out.append(src[last:])
    return "".join(out)


# ------------------------------------------------------------------- fix 2
# A line whose only content is `;` is a Lua 5.2 empty statement and a Lua 5.1
# parse error.
#
# The `;` is not decoration: luadec emits it to break the classic Lua
# ambiguity where a statement ending in a value is followed by a
# parenthesised expression, and the parser joins them into a call:
#
#     a = b
#     (f)(x)          -->  parsed as  a = b(f)(x)
#
# In Lua 5.1 the separator is only legal as a terminator ON the preceding
# statement (`a = b;`), never standing alone. So the fix is to move it to the
# end of the previous statement, not to glue it to the next one - gluing it
# forward leaves it as the first token of a block, which 5.1 rejects just as
# hard (`do ; (f)(x) end` is still a parse error).
#
# When there is no preceding statement in the block - the `;` is the first
# thing after `do` / `then` / `else` / `repeat` - there is no ambiguity for it
# to resolve, and the correct repair is simply to drop it.
_LONE_SEMI = re.compile(r"(?m)^[ \t]*;[ \t]*\r?\n")

# a previous line ending in one of these opens a block or an incomplete
# expression: appending `;` there would itself be a syntax error.
_BLOCK_OPENER = re.compile(
    r"(?:\b(?:do|then|else|repeat)|[{(,=]|\b(?:and|or|not)\b)[ \t]*$")


def _last_code_pos_before(src, mask, pos):
    """Index of the last non-space CODE character strictly before pos."""
    i = pos - 1
    while i >= 0:
        if mask[i] and not src[i].isspace():
            return i
        i -= 1
    return -1


def fix_empty_statements(src, report, mask=None):
    if mask is None:
        mask = _code_mask(src)
    edits = []          # (start, end, replacement)
    for m in _LONE_SEMI.finditer(src):
        semi = src.find(";", m.start())
        if semi < 0 or not mask[semi]:
            continue
        p = _last_code_pos_before(src, mask, m.start())
        if p < 0 or _BLOCK_OPENER.search(src[:p + 1]):
            # nothing to terminate: the `;` guards nothing, drop the line
            edits.append((m.start(), m.end(), ""))
        else:
            # terminate the previous statement, drop the standalone line
            edits.append((p + 1, p + 1, ";"))
            edits.append((m.start(), m.end(), ""))
        report.lone_semis += 1
    if not edits:
        return src
    out = []
    last = 0
    for a, b, rep in sorted(edits):
        out.append(src[last:a])
        out.append(rep)
        last = b
    out.append(src[last:])
    return "".join(out)


# ------------------------------------------------------------------- survey
_DECOMP_ERR = re.compile(r"--\s*DECOMPILER ERROR[^\n]*")

# Places where luadec emitted no value at all. Two spellings, both seen on
# real retail content, both meaning the same thing: the decompiler lost a
# register and printed a hole.
#
#   `.end`        goapinterface, librarycutscene, librarytables,
#                 eventdrivenconditionalsystem (global.lu)
#                     local a, b = getmetatable(x), .end
#                     local a, b = .end
#
#   empty slot    dynamiccameradof, libraryloading, libraryweapon
#                 (levelcommon.lu) - luadec's "Confused about usage of
#                 register R_ in 'UnsetPending'"
#                     local a, b, c = , "x", "y"
#
# Neither is repairable: the missing value was never decompiled, so any
# substitution would be invented code. They are detected so the caller can
# fall back to the other backend instead of shipping a guess.
_GAVE_UP_PATTERNS = (
    re.compile(r"(?:[=,]|\breturn\b)\s*\.end\b"),
    re.compile(r"=\s*,"),
    re.compile(r",\s*,"),
)


def _count_in_code(pattern, src, mask):
    """Matches of pattern that start in real code, not a string or comment."""
    return sum(1 for m in pattern.finditer(src) if mask[m.start()])


def strip_decompiler_errors(src):
    """Remove luadec's inline `-- DECOMPILER ERROR ...` comment lines."""
    return _DECOMP_ERR.sub("", src)


# --------------------------------------------------------------------- main
def repair(src, strip_warnings=False):
    """Repair decompiler output. -> (fixed_source, Report)

    strip_warnings removes luadec's `-- DECOMPILER ERROR` comments from the
    result. They are noisy, but they mark the exact spots where the
    decompiler was unsure, so they are kept by default.
    """
    report = Report()
    if not src:
        return src, report

    # Survey before rewriting, and only over real code - a `, ,` inside a
    # string literal is not a decompiler hole.
    mask = _code_mask(src)
    report.decompiler_errors = len(_DECOMP_ERR.findall(src))
    report.gave_up = sum(_count_in_code(p, src, mask) for p in _GAVE_UP_PATTERNS)

    # Order matters: each rewrite shifts offsets, so every pass recomputes
    # the mask it needs rather than sharing the one above.
    src = fix_empty_statements(src, report)
    src = fix_method_refs(src, report)
    src = fix_computed_method_refs(src, report)

    if report.gave_up:
        report.notes.append(
            f"the decompiler left {report.gave_up} hole(s) where it could not "
            f"reconstruct a value (`.end`, or an empty slot before a comma). "
            f"This source is INCOMPLETE - it must not be shipped, and the "
            f"other backend should be used for this chunk.")
    if strip_warnings:
        src = strip_decompiler_errors(src)
    return src, report


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inp")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--strip-warnings", action="store_true",
                    help="also drop luadec's -- DECOMPILER ERROR comments")
    a = ap.parse_args()
    from pathlib import Path
    src = Path(a.inp).read_text(encoding="utf-8", errors="replace")
    fixed, rep = repair(src, strip_warnings=a.strip_warnings)
    Path(a.out).write_text(fixed, encoding="utf-8")
    print(f"{a.inp} -> {a.out}: {rep.summary()}")
    for n in rep.notes:
        print("  " + n)
    return 1 if rep.unrecoverable else 0


if __name__ == "__main__":
    sys.exit(main())
