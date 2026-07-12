#!/usr/bin/env python3
"""widen size_t fields 4 -> 8 in standard Lua 5.1 bytecode.

transcode() emits headers with size_t=4. A 64-bit Lua rejects them.
Only String length fields are size_t; widen each, flip header byte 8.
"""
import struct, sys
from pathlib import Path

def widen(d):
    if d[:4] != b"\x1bLua" or d[4] != 0x51:
        raise ValueError("not Lua 5.1")
    if d[8] != 4:
        raise ValueError(f"size_t already {d[8]}")
    p = [12]
    out = bytearray(d[:12])
    out[8] = 8
    def rd(n):
        b = d[p[0]:p[0]+n]; p[0]+=n; return b
    def ru32():
        v = struct.unpack_from("<I", d, p[0])[0]; p[0]+=4; return v
    def rsizet4():
        v = struct.unpack_from("<I", d, p[0])[0]; p[0]+=4; return v
    def wstr():
        n = rsizet4()
        out.extend(struct.pack("<Q", n))
        out.extend(rd(n))
    def wu32():
        out.extend(struct.pack("<I", ru32()))
    def func():
        wstr()                 # source
        out.extend(rd(4))      # linedefined
        out.extend(rd(4))      # lastlinedefined
        out.extend(rd(4))      # nups, numparams, is_vararg, maxstack
        nc = ru32(); out.extend(struct.pack("<I", nc)); out.extend(rd(4*nc))
        nk = ru32(); out.extend(struct.pack("<I", nk))
        for _ in range(nk):
            t = rd(1)[0]; out.append(t)
            if t == 0: pass
            elif t == 1: out.extend(rd(1))
            elif t == 3: out.extend(rd(8))
            elif t == 4: wstr()
            else: raise ValueError(f"const {t}")
        npr = ru32(); out.extend(struct.pack("<I", npr))
        for _ in range(npr): func()
        nl = ru32(); out.extend(struct.pack("<I", nl)); out.extend(rd(4*nl))
        nloc = ru32(); out.extend(struct.pack("<I", nloc))
        for _ in range(nloc):
            wstr(); out.extend(rd(4)); out.extend(rd(4))
        nup = ru32(); out.extend(struct.pack("<I", nup))
        for _ in range(nup): wstr()
    func()
    if p[0] != len(d):
        raise ValueError(f"trailing bytes: parsed {p[0]} of {len(d)}")
    return bytes(out)

if __name__ == "__main__":
    src = Path(sys.argv[1]); dst = Path(sys.argv[2])
    dst.write_bytes(widen(src.read_bytes()))
