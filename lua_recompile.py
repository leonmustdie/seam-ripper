#!/usr/bin/env python3
r"""lua_recompile.py - inverse of lua_decompile transcode.

Standard Lua 5.1 bytecode (stock luac, any host word size) -> Naughty Bear
360 chunk bytecode: 13-byte doubled-size header, 4-byte size_t, top-level
proto drops nups.

--hash re-encodes string constants back to 0xFE interned hashes:
  * a constant literally named  __hash_0xXXXXXXXX  -> 0xFE with value XXXXXXXX
  * a string whose crc32(lower) is in the original chunk's hash set -> 0xFE
  * every other string stays a type-4 string
The original chunk (which records exactly which constants were 0xFE) is the
reference. Pass it with --ref.
"""
import argparse, struct, sys, zlib, re
from pathlib import Path

HASH_PH = re.compile(rb"^__hash_0x([0-9a-fA-F]{1,8})\x00?$")

def ref_hash_set(ref_chunk):
    d = ref_chunk
    i = d.find(b"\x1bLua")
    if i < 0: return set()
    p = i + 13
    n = struct.unpack_from("<I", d, p)[0]; p += 4 + n
    p += 4 + 4 + 3
    nc = struct.unpack_from("<I", d, p)[0]; p += 4 + nc*4
    nk = struct.unpack_from("<I", d, p)[0]; p += 4
    hs = set()
    for _ in range(nk):
        t = d[p]; p += 1
        if t == 4:
            sl = struct.unpack_from("<I", d, p)[0]; p += 4 + sl
        elif t == 0xFE:
            h = struct.unpack_from("<Q", d, p)[0]; p += 8; hs.add(h & 0xFFFFFFFF)
        elif t == 3: p += 8
        elif t == 1: p += 1
        elif t == 0: pass
        else: break
    return hs

def convert(std, want_hash=False, orig_hashes=None):
    if std[:4]!=b"\x1bLua" or std[4]!=0x51:
        raise ValueError("not Lua 5.1 bytecode")
    int_sz,sizet_sz,inst_sz,num_sz = std[7],std[8],std[9],std[10]
    d=std; p=[12]; out=bytearray()
    out+=bytes([0x1b,0x4c,0x75,0x61,0x51,0x00,0x01,0x04,0x04,0x04,0x08,0x08,0x00])
    orig_hashes = orig_hashes or set()
    def rd(n):
        b=d[p[0]:p[0]+n]; p[0]+=n; return b
    def rd_sizet(): return int.from_bytes(rd(sizet_sz),"little")
    def rd_u32(): return struct.unpack("<I",rd(4))[0]
    def wstr():
        n=rd_sizet(); s=rd(n); out.extend(struct.pack("<I",n)); out.extend(s)
    def emit_const_str():
        n=rd_sizet(); s=rd(n)
        if want_hash:
            m=HASH_PH.match(s)
            if m:
                val=int(m.group(1),16)
                out.append(0xFE); out.extend(struct.pack("<Q", val & 0xFFFFFFFF))
                return
            body = s[:-1] if s.endswith(b"\x00") else s
            c = zlib.crc32(body.lower()) & 0xFFFFFFFF
            if c in orig_hashes:
                out.append(0xFE); out.extend(struct.pack("<Q", c))
                return
        out.append(4); out.extend(struct.pack("<I",n)); out.extend(s)
    def proto(top):
        wstr()
        out.extend(rd(int_sz)); out.extend(rd(int_sz))
        nups=rd(1)[0]
        if not top: out.append(nups)
        out.extend(rd(3))
        nc=rd_u32(); out.extend(struct.pack("<I",nc)); out.extend(rd(inst_sz*nc))
        nk=rd_u32(); out.extend(struct.pack("<I",nk))
        for _ in range(nk):
            t=rd(1)[0]
            if t==0: out.append(t)
            elif t==1: out.append(t); out.append(rd(1)[0])
            elif t==3: out.append(t); out.extend(rd(num_sz))
            elif t==4: emit_const_str()
            else: raise ValueError("const type %d"%t)
        npr=rd_u32(); out.extend(struct.pack("<I",npr))
        for _ in range(npr): proto(False)
        nl=rd_u32(); out.extend(struct.pack("<I",nl)); out.extend(rd(inst_sz*nl))
        nloc=rd_u32(); out.extend(struct.pack("<I",nloc))
        for _ in range(nloc):
            wstr(); out.extend(rd(int_sz)); out.extend(rd(int_sz))
        nup=rd_u32(); out.extend(struct.pack("<I",nup))
        for _ in range(nup): wstr()
    proto(True)
    return bytes(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("infile"); ap.add_argument("-o","--out",required=True)
    ap.add_argument("--hash",action="store_true",help="re-encode hashed constants as 0xFE")
    ap.add_argument("--ref",help="original chunk .bin, source of the 0xFE hash set")
    a=ap.parse_args()
    oh=set()
    if a.hash and a.ref:
        oh=ref_hash_set(Path(a.ref).read_bytes())
    out=convert(Path(a.infile).read_bytes(), want_hash=a.hash, orig_hashes=oh)
    Path(a.out).write_bytes(out)
    print(f"wrote {a.out} ({len(out)} bytes, 360 chunk bytecode){' +hash' if a.hash else ''}")

if __name__=="__main__": main()
