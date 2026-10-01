#!/usr/bin/env python3
r"""Inverse of the lua_decompile transcode."""
import argparse, struct, sys, zlib, re
from pathlib import Path

# Up to 16 hex digits: the 0xFE constant is a full 64-bit value, and retail
# uses the high word (0xFFFFFFFFFFFFFFFF is -1). Masking this to 32 bits threw
# the high word away and broke the round trip for any chunk that used one.
HASH_PH = re.compile(rb"^__hash_0x([0-9a-fA-F]{1,16})\x00?$")

# A 32-bit CRC is uniform over 0..4.29e9, so only ~0.2% of real hashes land
# below this. Gameplay integers stored in the same 0xFE type (counts,
# priorities, score bands) cluster far below it. The distinction matters
# because of one specific false positive: crc32(b"") is 0, and 0 is a very
# common 0xFE integer, so without this floor every empty string constant in a
# chunk gets re-encoded as the "hash" 0x00000000. That measurably worsened
# npc.lua's round trip (69 divergent functions became 73).
HASH_FLOOR = 10 ** 7


def ref_hash_set(ref_chunk):
    """Every 0xFE value in the chunk, including nested protos.

    This used to walk only the top-level proto, so a name hashed inside a
    function body was absent from the set and could not be re-encoded -
    which silently limited how much of a chunk could round-trip.
    """
    d = ref_chunk
    i = d.find(b"\x1bLua")
    if i < 0:
        return set()
    p = [i + 13]
    hs = set()

    def u32():
        v = struct.unpack_from("<I", d, p[0])[0]; p[0] += 4; return v

    def proto(top):
        n = u32(); p[0] += n                  # source name
        p[0] += 4 + 4                         # linedefined, lastlinedefined
        if not top:
            p[0] += 1                         # nups (absent at top level)
        p[0] += 3                             # numparams, is_vararg, maxstack
        nc = u32(); p[0] += 4 * nc            # code
        nk = u32()
        for _ in range(nk):
            t = d[p[0]]; p[0] += 1
            if t == 4:
                sl = u32(); p[0] += sl
            elif t == 0xFE:
                h = struct.unpack_from("<Q", d, p[0])[0]; p[0] += 8
                hs.add(h & 0xFFFFFFFF)
            elif t == 3:
                p[0] += 8
            elif t == 1:
                p[0] += 1
            elif t == 0:
                pass
            else:
                raise ValueError(f"unknown constant type {t}")
        npr = u32()
        for _ in range(npr):
            proto(False)
        nl = u32(); p[0] += 4 * nl            # line info
        nloc = u32()
        for _ in range(nloc):
            sl = u32(); p[0] += sl; p[0] += 8
        nup = u32()
        for _ in range(nup):
            sl = u32(); p[0] += sl

    try:
        proto(True)
    except Exception:
        # a malformed or unexpected chunk shape: better to return what was
        # collected than to fail the whole recompile
        pass
    return hs

def convert(std, want_hash=False, orig_hashes=None, fe_numbers=None):
    """standard Lua 5.1 bytecode -> the game's chunk format.

    fe_numbers, {proto path: set of ints}, turns those number constants into
    the game's 64-bit integer constants (0xFE) - how NB1 stores every number
    its source spells as an integer. Paths are "0", "0_0", "0_0_1", ... as
    nbdec names them."""
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
                out.append(0xFE); out.extend(struct.pack("<Q", val & 0xFFFFFFFFFFFFFFFF))
                return
            body = s[:-1] if s.endswith(b"\x00") else s
            c = zlib.crc32(body.lower()) & 0xFFFFFFFF
            # Only treat a string as a re-encodable hash when the value looks
            # like one. Without the floor, crc32(b"") == 0 turns every empty
            # string into the integer-valued "hash" 0, which is wrong and
            # measurably hurt round-trip fidelity.
            if body and c >= HASH_FLOOR and c in orig_hashes:
                out.append(0xFE); out.extend(struct.pack("<Q", c))
                return
        out.append(4); out.extend(struct.pack("<I",n)); out.extend(s)
    def proto(top, path="0"):
        fe = (fe_numbers or {}).get(path, ())
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
            elif t==3:
                raw = rd(num_sz)
                v = struct.unpack("<d", raw)[0] if num_sz == 8 else None
                if v is not None and v == v and abs(v) < 2**63 and \
                        v == int(v) and int(v) in fe:
                    out.append(0xFE); out.extend(struct.pack("<q", int(v)))
                else:
                    out.append(t); out.extend(raw)
            elif t==4: emit_const_str()
            else: raise ValueError("const type %d"%t)
        npr=rd_u32(); out.extend(struct.pack("<I",npr))
        for n in range(npr): proto(False, f"{path}_{n}")
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
