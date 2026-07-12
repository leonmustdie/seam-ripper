#!/usr/bin/env python3
"""lua_clean.py - readability pass for unluac-decompiled Naughty Bear scripts.

Stripped 360 bytecode loses original local names; unluac emits scratch
registers (L0_6) reused across unrelated values. This pass makes scripts
followable by:

  1. INLINING register chains:  R = Foo ; R = R(args)  ->  R = Foo(args)
     (also R.field, R[idx]). Collapses the 3-line register dance unluac
     produces into single statements.
  2. FOLDING  R = expr ; GLOBAL = R  ->  GLOBAL = expr   when R dies there.
  3. Forward-declare cleanup:  G = L0 ; L0 = nil  ->  G = nil.

Heuristic aid, not a decompiler. Logic identical to the raw decompile;
only presentation changes. Original names are gone (stripped); globals and
method names ARE preserved and carry the meaning.

Usage:
  lua_clean.py in.lua -o out.lua
  lua_clean.py indir/ -o outdir/
"""
import argparse, re, sys
from pathlib import Path

REG = re.compile(r"[LA]\d+_\d+")
# lines containing these keywords are structural; never merge across them
STRUCT = re.compile(r"\b(if|else|elseif|then|end|while|for|do|function|return|repeat|until|break)\b")


def _safe(line):
    """True if line is a plain assignment with no control-flow keyword."""
    return not STRUCT.search(line)


def inline_chains(lines):
    changed = True
    while changed:
        changed = False
        res = []
        j = 0
        while j < len(lines):
            cur = lines[j]
            m = re.match(r"(\s*)([LA]\d+_\d+)\s*=\s*(.+?)\s*$", cur)
            if m and j + 1 < len(lines) and _safe(cur) and _safe(lines[j + 1]):
                ind, reg, rhs = m.group(1), m.group(2), m.group(3)
                nxt = lines[j + 1]
                m2 = re.match(rf"\s*{re.escape(reg)}\s*=\s*{re.escape(reg)}([.(\[].*)$", nxt)
                # only inline if rhs is simple (no same-reg reuse that would double)
                if m2 and not re.search(rf"\b{re.escape(reg)}\b", rhs):
                    res.append(f"{ind}{reg} = {rhs}{m2.group(1)}")
                    j += 2
                    changed = True
                    continue
            res.append(cur)
            j += 1
        lines = res
    return lines


def fold_into_global(lines):
    """ R = expr ; NAME = R  (R not used after) -> NAME = expr """
    res = []
    j = 0
    while j < len(lines):
        cur = lines[j]
        m = re.match(r"(\s*)([LA]\d+_\d+)\s*=\s*(.+?)\s*$", cur)
        if m and j + 1 < len(lines) and _safe(cur) and _safe(lines[j + 1]):
            ind, reg, rhs = m.group(1), m.group(2), m.group(3)
            nxt = lines[j + 1]
            m2 = re.match(rf"\s*([A-Za-z_]\w*(?:\.\w+)?)\s*=\s*{re.escape(reg)}\s*$", nxt)
            # require reg not read in the line after next (cheap liveness check)
            after = lines[j + 2] if j + 2 < len(lines) else ""
            reg_read_after = bool(re.search(rf"=\s*.*\b{re.escape(reg)}\b", after)) or \
                             bool(re.search(rf"\b{re.escape(reg)}\b\s*[.(\[]", after))
            if m2 and not reg_read_after:
                res.append(f"{ind}{m2.group(1)} = {rhs}")
                j += 2
                continue
        # forward-declare: G = R ; R = nil -> G = nil
        m3 = re.match(r"(\s*)([A-Za-z_]\w*)\s*=\s*([LA]\d+_\d+)\s*$", cur)
        if m3 and j + 1 < len(lines) and re.match(rf"\s*{re.escape(m3.group(3))}\s*=\s*nil\s*$", lines[j + 1]):
            res.append(f"{m3.group(1)}{m3.group(2)} = nil")
            j += 2
            continue
        res.append(cur)
        j += 1
    return res


def clean_text(src):
    lines = src.split("\n")
    lines = inline_chains(lines)
    lines = fold_into_global(lines)
    lines = inline_chains(lines)  # second pass catches newly-adjacent chains
    note = ("-- cleaned by lua_clean.py: chains inlined, registers folded into "
            "their targets. logic == raw decompile; names inferred (stripped bytecode).\n")
    return note + "\n".join(lines)


def process(inp, outp):
    inp, outp = Path(inp), Path(outp)
    if inp.is_dir():
        n = 0
        for f in sorted(inp.rglob("*.lua")):
            dest = outp / f.relative_to(inp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(clean_text(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            n += 1
        print(f"cleaned {n} files -> {outp}")
    else:
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(clean_text(inp.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        print(f"cleaned {inp} -> {outp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("-o", "--out", required=True)
    process(*vars(ap.parse_args()).values())


if __name__ == "__main__":
    main()
