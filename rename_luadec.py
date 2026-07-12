#!/usr/bin/env python3
"""rename_luadec.py - give luadec's l_<f>_<i> locals usage-based names.

Local names are stripped by `luac -s`, so any collision-free renaming
compiles to identical bytecode. The caller verifies that externally; this
module only proposes names from how each register is first assigned/used.

A token l_A_B reused across sibling functions takes its dominant meaning;
for single-scope scripts the name is exact. Names never collide with Lua
keywords, the script's globals, or each other within the file.
"""
import re, sys, keyword as _kw
from pathlib import Path

TOKEN = re.compile(r"\bl_(\d+)_(\d+)\b")
LUA_KW = {"and","break","do","else","elseif","end","false","for","function",
          "goto","if","in","local","nil","not","or","repeat","return","then",
          "true","until","while","self"}

def _lc(s):
    return s[:1].lower() + s[1:] if s else s

def _name_from_rhs(rhs):
    rhs = rhs.strip()
    m = re.match(r'require\(["\']([\w./]+)["\']\)', rhs)
    if m: return _lc(re.split(r"[./]", m.group(1))[-1])
    m = re.match(r'\(?[\w.]*[):]\s*Get([A-Za-z]\w*)\s*\(', rhs) or \
        re.match(r'[\w.]*[:.]Get([A-Za-z]\w*)\s*\(', rhs)
    if m: return _lc(m.group(1))
    m = re.match(r'Get([A-Za-z]\w*)\s*\(', rhs)
    if m: return _lc(m.group(1))
    m = re.match(r'[\w.]*[:.]([A-Za-z]\w*)\s*\(', rhs)
    if m: return _lc(m.group(1))
    m = re.match(r'[A-Za-z_]\w*\.([A-Za-z]\w*)\s*$', rhs)
    if m: return _lc(m.group(1))
    m = re.match(r'([A-Za-z_]\w*)\s*$', rhs)
    if m and rhs not in ("nil","true","false"): return _lc(m.group(1))
    m = re.match(r'([A-Za-z_]\w*)\s*\(', rhs)
    if m: return _lc(re.sub(r'^get','',m.group(1),flags=re.I))
    return None

def propose(src):
    globals_used = set(re.findall(r"\b([A-Z]\w+|g[A-Z]\w+)\b", src))
    # method-syntax self: T.Method = function(l_x_y, ...)  -> first param = self
    self_tokens = set()
    for m in re.finditer(r"[\w.]+\.\w+\s*=\s*function\s*\(\s*(l_\d+_\d+)", src):
        self_tokens.add(m.group(1))
    cand = {}  # token -> chosen base name
    for tok in sorted(set(f"l_{a}_{b}" for a,b in TOKEN.findall(src))):
        if tok in self_tokens:
            cand[tok] = "self"; continue
        best = None
        for m in re.finditer(rf"\blocal\s+{re.escape(tok)}\s*=\s*([^\n]+)", src):
            best = _name_from_rhs(m.group(1));
            if best: break
        if not best:
            for m in re.finditer(rf"\b{re.escape(tok)}\s*=\s*([^\n]+)", src):
                best = _name_from_rhs(m.group(1))
                if best: break
        cand[tok] = best
    # assign unique, non-colliding final names
    used = set(LUA_KW) | globals_used
    final = {}
    for tok, base in cand.items():
        if not base or base in LUA_KW:
            base = "self" if base == "self" else None
        if not base:
            final[tok] = tok; continue
        name = base; n = 2
        while name in used or name in final.values():
            name = f"{base}{n}"; n += 1
        final[tok] = name; used.add(name)
    return final

def apply(src):
    final = propose(src)
    return TOKEN.sub(lambda m: final.get(f"l_{m.group(1)}_{m.group(2)}",
                                          m.group(0)), src)

if __name__ == "__main__":
    s = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    Path(sys.argv[2]).write_text(apply(s), encoding="utf-8")
