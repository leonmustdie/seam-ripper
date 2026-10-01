"""Text helpers for the script editor: list parsing, outline, diffs, errors."""
import difflib
import re


class Script:
    def __init__(self, index, name, size, form, hash_):
        self.index, self.name, self.size = index, name, size
        self.form, self.hash = form, hash_


def parse_list(text):
    """Parse `lu_lua.py list` output into (header line, [Script]).

    Rows look like `   310  achievements   11113  bytecode  0xd1227efe`;
    the header line is e.g. `global.lu: Naughty Bear (x36, compiled bytecode)`.
    """
    header, scripts = "", []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if (len(parts) >= 5 and parts[0].isdigit() and parts[-1].startswith("0x")):
            scripts.append(Script(int(parts[0]), parts[1], parts[2],
                                  parts[-2], parts[-1]))
        elif not header and s.endswith(")") and "(" in s and ":" in s:
            header = s
    return header, scripts


_FUNC = re.compile(r"^(?:local\s+)?function\s+([\w.:]+)\s*\(")


def functions(text):
    """Top-level functions as [(name, first line number, block text)].

    A block runs from its `function` line to the next line that starts a new
    top-level statement; good enough to tell which functions you changed.
    """
    lines = text.splitlines()
    starts = []
    for i, ln in enumerate(lines):
        m = _FUNC.match(ln)
        if m:
            starts.append((m.group(1), i))
    out = []
    for n, (name, i) in enumerate(starts):
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("end"):
                end = j + 1
                break
            if n + 1 < len(starts) and j >= starts[n + 1][1]:
                end = j
                break
        out.append((name, i + 1, "\n".join(lines[i:end])))
    return out


def changed_functions(orig, new):
    """Names of functions whose text differs from (or is missing in) `orig`."""
    old = {}
    for name, _line, block in functions(orig):
        old.setdefault(name, []).append(block)
    seen, changed = {}, []
    for name, _line, block in functions(new):
        k = seen.get(name, 0)
        seen[name] = k + 1
        blocks = old.get(name, [])
        if k >= len(blocks) or blocks[k] != block:
            changed.append(name)
    return changed


def changed_lines(orig, new):
    """1-based line numbers in `new` that differ from `orig`."""
    a, b = orig.splitlines(), new.splitlines()
    out = set()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            out.update(range(j1 + 1, j2 + 1))
        elif tag == "delete":
            out.add(min(j1 + 1, max(len(b), 1)))
    return out


def unified_diff(orig, new, name="script"):
    """Unified diff lines (with newlines) between two texts."""
    return list(difflib.unified_diff(
        orig.splitlines(True), new.splitlines(True),
        f"{name} (original)", f"{name} (your edit)", n=3))


def side_by_side(orig, new):
    """Aligned rows [(left_no, left_text, right_no, right_text, kind)]; kind is
    'same', 'del', 'add' or 'chg'."""
    a, b = orig.splitlines(), new.splitlines()
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [(i + 1, a[i], j + 1, b[j], "same")
                     for i, j in zip(range(i1, i2), range(j1, j2))]
            continue
        n = max(i2 - i1, j2 - j1)
        for k in range(n):
            li = i1 + k if i1 + k < i2 else None
            rj = j1 + k if j1 + k < j2 else None
            kind = "chg" if li is not None and rj is not None else (
                "del" if li is not None else "add")
            rows.append((li + 1 if li is not None else None,
                         a[li] if li is not None else "",
                         rj + 1 if rj is not None else None,
                         b[rj] if rj is not None else "", kind))
    return rows


_ERR_LINE = re.compile(r"\.lua:(\d+):\s*(.*)")
_ERR_ANY = re.compile(r"(?:line\s+|:)(\d+)[:\s]\s*(.*)")


def parse_errors(text):
    """[(line number, message)] for errors in ship/check output that name a
    line of the edited script (`...edit.lua:9: unexpected symbol near '='`)."""
    out = []
    for ln in text.splitlines():
        m = _ERR_LINE.search(ln)
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    if not out:
        for ln in text.splitlines():
            if "error" in ln.lower() or "failed" in ln.lower():
                m = _ERR_ANY.search(ln)
                if m:
                    out.append((int(m.group(1)), m.group(2).strip() or ln.strip()))
    return out
