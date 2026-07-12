#!/usr/bin/env python3
"""proto360.py - parse a Naughty Bear 360 Lua chunk into a proto tree with
byte spans, and splice one proto by path. 360 stream is flat-recursive with
no absolute offsets, so replacing a proto's byte span and reconcatenating is
valid; parent nproto counts are unchanged.

Proto path = nested index list, e.g. [] is top, [3] is 4th nested fn of top,
[3,1] is 2nd nested fn of that.
"""
import struct

HDR_LEN = 13  # 360 header (doubled number-size byte)

def _u32(d, p): return struct.unpack_from("<I", d, p)[0]

def parse(d):
    """return (top_proto_dict, body_start). header is d[:body_start]."""
    assert d[:5] == b"\x1bLua\x51", "not a 360 Lua chunk"
    pos = [HDR_LEN]
    def u32():
        v = _u32(d, pos[0]); pos[0]+=4; return v
    def skip(n): pos[0]+=n
    def lstr():
        n = u32(); skip(n); return n
    def proto(top, idx):
        start = pos[0]
        lstr()                  # source
        skip(8)                 # line defined, last
        skip(3 if top else 4)   # [nups] nparams vararg maxstack
        nups_off = None
        # capture nups byte offset for non-top (for signature check)
        nc = u32(); skip(4*nc)
        nk = u32()
        for _ in range(nk):
            t = d[pos[0]]; pos[0]+=1
            if t == 0: pass
            elif t == 1: skip(1)
            elif t == 3: skip(8)
            elif t == 4: lstr()
            elif t == 0xFE: skip(8)
            else: raise ValueError(f"const {t} at {pos[0]}")
        npr = u32(); kids = []
        for i in range(npr):
            kids.append(proto(False, i))
        nl = u32(); skip(4*nl)
        nloc = u32()
        for _ in range(nloc):
            lstr(); skip(8)
        nup = u32()
        for _ in range(nup):
            lstr()
        end = pos[0]
        return {"idx": idx, "top": top, "span": (start, end),
                "nproto": npr, "kids": kids}
    top = proto(True, None)
    return top, HDR_LEN

def find(top, path):
    node = top
    for i in path:
        node = node["kids"][i]
    return node

def shape(node):
    return (node["nproto"], tuple(shape(k) for k in node["kids"]))

def splice(orig_chunk, new_chunk, path):
    """replace proto at `path` in orig_chunk with the same-path proto bytes
    from new_chunk. returns spliced chunk bytes."""
    ot, ob = parse(orig_chunk)
    nt, nb = parse(new_chunk)
    if shape(ot) != shape(nt):
        raise ValueError("proto-tree shape differs; source must keep the same "
                         "function structure (only edit bodies)")
    onode = find(ot, path)
    nnode = find(nt, path)
    os_, oe = onode["span"]
    ns_, ne = nnode["span"]
    return orig_chunk[:os_] + new_chunk[ns_:ne] + orig_chunk[oe:]

def proto_bytes(chunk, path):
    t, _ = parse(chunk)
    s, e = find(t, path)["span"]
    return chunk[s:e]

def decode_logic(chunk):
    """path-str -> (code_bytes, consts_tuple) for every proto, decoding the
    360 stream. Ignores source name, line info, locals, upvalue names — so two
    functions compare equal iff their instructions+constants match (the thing
    that actually runs), regardless of debug stamps."""
    d = chunk; pos = [HDR_LEN]; out = {}
    def u32():
        v = _u32(d, pos[0]); pos[0]+=4; return v
    def b1():
        v = d[pos[0]]; pos[0]+=1; return v
    def lstr():
        n = u32(); s = d[pos[0]:pos[0]+n]; pos[0]+=n; return s
    def proto(top, path):
        lstr()                                  # source
        pos[0]+=8                               # line defined, last
        pos[0]+=3 if top else 4                 # [nups]nparams,vararg,maxstack
        nc = u32(); code = d[pos[0]:pos[0]+4*nc]; pos[0]+=4*nc
        nk = u32(); consts = []
        for _ in range(nk):
            t = b1()
            if t == 0: consts.append(("nil",))
            elif t == 1: consts.append(("b", b1()))
            elif t == 3: consts.append(("n", d[pos[0]:pos[0]+8])); pos[0]+=8
            elif t == 4: consts.append(("s", lstr()))
            elif t == 0xFE: consts.append(("h", d[pos[0]:pos[0]+8])); pos[0]+=8
            else: raise ValueError(f"const {t}")
        out[path] = (code, tuple(consts))
        npr = u32()
        for i in range(npr):
            proto(False, f"{path}_{i}" if path else f"0_{i}")
        nl = u32(); pos[0]+=4*nl
        nloc = u32()
        for _ in range(nloc): lstr(); pos[0]+=8
        nup = u32()
        for _ in range(nup): lstr()
    proto(True, "0")
    return out
