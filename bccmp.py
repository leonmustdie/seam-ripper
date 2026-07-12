#!/usr/bin/env python3
"""Compare two Lua 5.1 chunks structurally: per-function nparams, vararg,
maxstack, instruction stream, constant pool. Ignores header width, source
name, line info, local/upvalue debug names (all stripped or cosmetic)."""
import struct, sys
from pathlib import Path

def parse(d):
    assert d[:4] == b"\x1bLua" and d[4] == 0x51, "not Lua 5.1"
    little = d[6] == 1
    isz, stsz, insz, numsz = d[7], d[8], d[9], d[10]
    end = "<" if little else ">"
    p = [12]
    def rd(n):
        b = d[p[0]:p[0]+n]; p[0]+=n; return b
    def ru(sz):
        return int.from_bytes(rd(sz), "little" if little else "big")
    def rint(): return ru(isz)
    def rstr():
        n = ru(stsz)
        return b"" if n == 0 else rd(n)
    def func():
        rstr()                       # source (ignore)
        rint(); rint()               # line defined (ignore)
        rd(1)                        # nups
        nparams = rd(1)[0]; vararg = rd(1)[0]; maxstack = rd(1)[0]
        nc = rint(); code = [rd(insz) for _ in range(nc)]
        nk = rint(); consts = []
        for _ in range(nk):
            t = rd(1)[0]
            if t == 0: consts.append(("nil",))
            elif t == 1: consts.append(("bool", rd(1)[0]))
            elif t == 3: consts.append(("num", struct.unpack(end+"d", rd(numsz))[0]))
            elif t == 4: consts.append(("str", rstr()))
            else: raise ValueError(f"const {t}")
        npr = rint(); protos = [func() for _ in range(npr)]
        nl = rint(); [rd(insz) for _ in range(nl)]          # lineinfo (ignore)
        nloc = rint()
        for _ in range(nloc): rstr(); rint(); rint()        # locals (ignore)
        nup = rint()
        for _ in range(nup): rstr()                         # upval names (ignore)
        return {"sig": (nparams, vararg, maxstack), "code": code,
                "consts": consts, "protos": protos}
    return func()

def cmp_fn(a, b, path="0", out=None):
    if out is None: out = []
    if a["sig"] != b["sig"]:
        out.append(f"  fn {path}: sig {a['sig']} != {b['sig']}")
    if len(a["code"]) != len(b["code"]):
        out.append(f"  fn {path}: code len {len(a['code'])} != {len(b['code'])}")
    else:
        diff = sum(1 for x,y in zip(a["code"], b["code"]) if x != y)
        if diff: out.append(f"  fn {path}: {diff}/{len(a['code'])} instructions differ")
    if a["consts"] != b["consts"]:
        ca, cb = a["consts"], b["consts"]
        if len(ca) != len(cb):
            out.append(f"  fn {path}: const count {len(ca)} != {len(cb)}")
        else:
            for i,(x,y) in enumerate(zip(ca,cb)):
                if x != y: out.append(f"  fn {path}: const[{i}] {x!r} != {y!r}")
    if len(a["protos"]) != len(b["protos"]):
        out.append(f"  fn {path}: nproto {len(a['protos'])} != {len(b['protos'])}")
    else:
        for i,(x,y) in enumerate(zip(a["protos"], b["protos"])):
            cmp_fn(x, y, f"{path}_{i}", out)
    return out

if __name__ == "__main__":
    A = parse(Path(sys.argv[1]).read_bytes())
    B = parse(Path(sys.argv[2]).read_bytes())
    diffs = cmp_fn(A, B)
    if not diffs:
        print("IDENTICAL")
    else:
        print(f"DIFFERENT ({len(diffs)} findings)")
        for d in diffs[:12]: print(d)
