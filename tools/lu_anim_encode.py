#!/usr/bin/env python3
"""Encode Naughty Bear (NB1, x36) animation clip records (chunk 04300000).

The inverse of lu_anim2.decode_clip (LU_FORMAT.md section 28). A clip goes
through a neutral model:

    parse_clip(record bytes)  -> model
    encode_clip(model, mode)  -> record bytes

The model holds, per bone, its keyed channels (tag, record `end`, pieces of
segment ends plus polynomial coefficients or samples) and its static values
(tag, float). Two encoders:

  mode "raw"  re-emits every piece with its retail encoding and bytes, laid
              out the way retail lays a clip out. On retail input this must
              give the retail record byte for byte: a layout check.
  mode "f32"  writes every piece unquantised from the decoded floats, with
              f32 key times (encodings 0x18 samples, 0x12 linear, 0x14
              cubic, all used by retail) and statics re-encoded from their
              values. This is what an edited or imported clip goes through.
              Larger than retail (no quantisation).

Record layout (retail, every clip in the corpus):
    0x00  header (0x60 bytes): +0x08 name hash, +0x10 f32 duration,
          +0x20 {track table ptr, bone count}, +0x40 {marker ptr, count},
          +0x4c rig hash; the rest is copied
    0x60  track table, 16 B per bone {keyed_off, keyed_n, static_off, static_n}
    then per bone, in bone order:
          channel records (16 B each, 4-aligned)
          per channel: piece headers (16 B each, 4-aligned), then each
          piece's data (4-aligned)
          static words (u32 b0 b1 b2 tag, NOT aligned)
    markers (16 B each, 16-aligned) end the record
    gaps are 0xBF
"""
import argparse
import hashlib
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lu_anim2 import _decode_piece, f24  # noqa: E402

CLIP_TYPE = 0x04300000
EMPTY = 0xFFFFFFFF
FILL = 0xBF
TAGW_LOW = 0x00EFEF           # low 24 bits of a channel record's tag word


class EncodeError(Exception):
    pass


# ------------------------------------------------------------------ statics

def _swap24(x):
    return ((x & 0xFF) << 16) | (x & 0xFF00) | ((x >> 16) & 0xFF)


def f24_encode(x):
    """float -> 24-bit static payload (the word's top three bytes), so that
    lu_anim2.f24(payload) == x to 17-bit mantissa precision.
    sign(1) | exponent(6, bias 31) | mantissa(17)."""
    x = float(x)
    if not math.isfinite(x):
        raise EncodeError(f"static value {x} is not finite")
    if x == 0.0:
        return 0
    sign = 0x800000 if x < 0 else 0
    m, e = math.frexp(abs(x))           # abs = m * 2^e, m in [0.5, 1)
    e -= 1                              # abs = (2m) * 2^e, 2m in [1, 2)
    mant = int(round((2.0 * m - 1.0) * 131072.0))
    if mant == 131072:
        mant, e = 0, e + 1
    ef = e + 31
    if ef < 0:                          # below 2^-31: rounds to zero
        return 0
    if ef > 63:
        raise EncodeError(f"static value {x} is too large for a static word")
    if ef == 0 and mant == 0:           # would read back as 0; nudge up
        mant = 1
    return _swap24(sign | (ef << 17) | mant)


# -------------------------------------------------------------------- parse

def _u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def parse_clip(d):
    """Clip record bytes (NB1 or Panic in Paradise) -> model dict. Raises
    EncodeError on anything that is not a clip."""
    d = bytes(d)
    if len(d) < 0x60 or _u32(d, 0) != CLIP_TYPE:
        raise EncodeError("not a clip record (type 04300000)")
    pip = _u32(d, 0x1C) != 0xEFEFEFEF
    bone_hashes = None
    if pip:
        # Panic in Paradise (PIP_FORMAT.md 11.2): header 0x70, bone-name-hash
        # table {ptr 0x70, n} at +0x1c, track table at +0x30 with 24-byte
        # entries {keyed_off, keyed_n, 0, 0, static_off, static_n}, tail
        # table at +0x50
        if len(d) < 0x70:
            raise EncodeError("Panic in Paradise clip shorter than its header")
        hptr, hn = struct.unpack_from(">2I", d, 0x1C)
        tptr, tc = struct.unpack_from(">2I", d, 0x30)
        if hptr != 0x70 or hn != tc or not 0 < tc < 2048 or tptr + 24 * tc > len(d):
            raise EncodeError(f"unexpected Panic in Paradise tables "
                              f"{{{hptr:#x}, {hn}}} {{{tptr:#x}, {tc}}}")
        bone_hashes = list(struct.unpack_from(f">{tc}I", d, hptr))
        hsize, mk_off = 0x70, 0x50
    else:
        tptr, tc = struct.unpack_from(">2I", d, 0x20)
        if tptr != 0x60 or not 0 < tc < 2048 or tptr + 16 * tc > len(d):
            raise EncodeError(f"unexpected track table {{{tptr:#x}, {tc}}}")
        hsize, mk_off = 0x60, 0x40
    stats = Counter()
    bones = []
    for i in range(tc):
        if pip:
            ko, kn, xo, xn, so, sn = struct.unpack_from(">6I", d, tptr + 24 * i)
            if (xo, xn) != (0, 0):
                raise EncodeError(f"track {i}: middle slot {{{xo:#x}, {xn}}} is not empty")
        else:
            ko, kn, so, sn = struct.unpack_from(">4I", d, tptr + 16 * i)
        bone = {"keyed": [], "static": []}
        if ko != EMPTY and kn:
            for c in range(kn):
                pp, npc, end, tagw = struct.unpack_from(">IIfI", d, ko + 16 * c)
                ch = {"tag": tagw >> 24, "tagw_low": tagw & 0xFFFFFF,
                      "end": end, "pieces": []}
                for j in range(npc):
                    h = pp + 16 * j
                    start, kc, enc, dp, dsz = struct.unpack_from(">fHHII", d, h)
                    pc = {"start": start, "raw": (kc, enc, d[dp:dp + dsz])}
                    got = _decode_piece(d, h, stats)
                    if got is not None:
                        _seg_start, seg_end, coef = got
                        hi = enc >> 8
                        nib = hi & 0xF
                        pc["times"] = seg_end
                        pc["tmode"] = (hi >> 4) & 3
                        pc["nib"] = nib
                        pc["rate"] = enc & 0xFF
                        if nib in (0, 8):
                            pc["kind"] = "sample"
                            pc["values"] = coef[:, 3].copy()
                        else:
                            pc["kind"] = "poly"
                            pc["coef"] = coef[:, 4 - nib:].copy()
                    ch["pieces"].append(pc)
                bone["keyed"].append(ch)
        elif (ko, kn) != (EMPTY, 0):
            bone["keyed_slot"] = (ko, kn)      # unusual empty form, kept
        if so != EMPTY and sn:
            for c in range(sn):
                w = _u32(d, so + 4 * c)
                bone["static"].append({"tag": w & 0xFF, "payload": w >> 8,
                                       "value": f24(w >> 8)})
        elif (so, sn) != (EMPTY, 0):
            bone["static_slot"] = (so, sn)
        bones.append(bone)
    mp, mc = struct.unpack_from(">2I", d, mk_off)
    markers = d[mp:mp + 16 * mc] if mp != EMPTY and mc else b""
    m = {"header": d[:hsize], "bones": bones, "markers": markers,
         "marker_slot": (mp, mc), "decode_stats": stats,
         "game": "pip" if pip else "nb1"}
    if pip:
        m["bone_hashes"] = bone_hashes
    return m


# ------------------------------------------------------------------- encode

class _Buf:
    def __init__(self, head):
        self.b = bytearray(head)

    def align(self, a):
        while len(self.b) % a:
            self.b.append(FILL)
        return len(self.b)

    def put(self, data, a=1):
        at = self.align(a)
        self.b += data
        return at


def _times_bytes(pc, t):
    """Key-time bytes and time mode for a piece. A piece that came from a
    retail clip keeps its own time encoding, so its key times come back
    bit-exact (curves can jump at a key, so a time moved by f32 rounding
    moves the jump); anything else gets f32 absolute seconds."""
    tmode, rate = pc.get("tmode", 1), pc.get("rate", 0x1E)
    start = float(np.float32(pc["start"]))
    if tmode == 0 and rate:
        kc = len(t)
        want = start + np.minimum(np.arange(1, kc + 1), kc - 1) / float(rate)
        if np.array_equal(want, t):
            return 0, rate, b""
    elif tmode == 3 and rate:
        ticks = np.round((t - start) * rate)
        if (np.all((ticks >= 0) & (ticks < 0x10000))
                and np.array_equal(start + ticks / float(rate), t)):
            return 3, rate, ticks.astype(">u2").tobytes()
    return 1, 0x1E, np.asarray(t, dtype=">f4").tobytes()


def _piece_f32(pc):
    """One decoded piece -> (kc, enc, data), values unquantised f32. The
    encodings produced (08 18 10 30 12 32 33 14 34 with any time mode kept)
    are all used by retail clips."""
    t = np.asarray(pc["times"], float)
    kc = len(t)
    if not 0 < kc < 0x10000:
        raise EncodeError(f"piece with {kc} keys")
    tmode, rate, tb = _times_bytes(pc, t)
    if pc["kind"] == "sample":
        vals = np.asarray(pc["values"], dtype=">f4")
        nib = 0 if pc.get("nib") == 0 and tmode != 0 else 8
    else:
        coef = np.asarray(pc["coef"], float)
        nv = coef.shape[1]
        nib = nv
        if nv == 3 and tmode != 3:          # 0x13 unseen in retail; pad to cubic
            nib = 4
            coef = np.concatenate([np.zeros((len(coef), 1)), coef], axis=1)
        if tmode == 0:                      # 0x02-0x04 unseen; use f32 times
            tmode, rate, tb = 1, 0x1E, t.astype(">f4").tobytes()
        vals = coef.astype(">f4").reshape(-1)
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(vals.astype(float)))):
        raise EncodeError("non-finite key time or value")
    enc = (((tmode << 4) | nib) << 8) | rate
    return kc, enc, tb + vals.tobytes()


def encode_clip(model, mode="f32"):
    """Model -> clip record bytes. mode "raw": retail encodings and bytes;
    "f32": unquantised re-encode of the decoded values (pieces that did not
    decode keep their raw bytes)."""
    if mode not in ("raw", "f32"):
        raise ValueError(mode)
    bones = model["bones"]
    tc = len(bones)
    pip = model.get("game") == "pip"
    head = bytearray(model["header"])
    if pip:
        hashes = model["bone_hashes"]
        if len(hashes) != tc or len(head) != 0x70:
            raise EncodeError("a Panic in Paradise clip needs a 0x70 header and "
                              "one bone hash per track")
        struct.pack_into(">2I", head, 0x1C, 0x70, tc)
        buf = _Buf(head)
        buf.put(struct.pack(f">{tc}I", *hashes))
        table_at = buf.put(b"\0" * (24 * tc), 4)
        struct.pack_into(">2I", buf.b, 0x30, table_at, tc)
    else:
        struct.pack_into(">2I", head, 0x20, 0x60, tc)
        buf = _Buf(head)
        table_at = buf.put(b"\0" * (16 * tc))
    table = []
    for bone in bones:
        keyed = bone["keyed"]
        ko, kn = bone.get("keyed_slot", (EMPTY, 0))
        if keyed:
            ko = buf.put(b"\0" * (16 * len(keyed)), 4)
            kn = len(keyed)
            for c, ch in enumerate(keyed):
                pp = buf.put(b"\0" * (16 * len(ch["pieces"])), 4)
                for j, pc in enumerate(ch["pieces"]):
                    if mode == "raw" or "times" not in pc:
                        kc, enc, data = pc["raw"]
                    else:
                        kc, enc, data = _piece_f32(pc)
                    dp = buf.put(data, 4)
                    struct.pack_into(">fHHII", buf.b, pp + 16 * j,
                                     pc["start"], kc, enc, dp, len(data))
                tagw = (ch["tag"] << 24) | ch.get("tagw_low", TAGW_LOW)
                struct.pack_into(">IIfI", buf.b, ko + 16 * c,
                                 pp, len(ch["pieces"]), ch["end"], tagw)
        so, sn = bone.get("static_slot", (EMPTY, 0))
        if bone["static"]:
            words = []
            for s in bone["static"]:
                if mode == "raw" or s["tag"] not in _KNOWN:
                    p = s["payload"]
                else:
                    p = f24_encode(s["value"])
                words.append((p << 8) | s["tag"])
            so = buf.put(struct.pack(f">{len(words)}I", *words))
            sn = len(words)
        table.append((ko, kn, so, sn))
    for i, (ko, kn, so, sn) in enumerate(table):
        if pip:
            struct.pack_into(">6I", buf.b, table_at + 24 * i, ko, kn, 0, 0, so, sn)
        else:
            struct.pack_into(">4I", buf.b, table_at + 16 * i, ko, kn, so, sn)
    mp, mc = model.get("marker_slot", (EMPTY, 0))
    if model["markers"]:
        mp = buf.put(model["markers"], 16)
        mc = len(model["markers"]) // 16
    struct.pack_into(">2I", buf.b, 0x50 if pip else 0x40, mp, mc)
    return bytes(buf.b)


_KNOWN = {0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x08, 0x09, 0x0A,
          0x23, 0x24, 0x25}


# ------------------------------------------------------------ model edits

CLIP_JSON = "seamripper-clip"
CLIP_JSON_VERSION = 1


def is_pip(d):
    """True for a Panic in Paradise clip record (bone-hash table at +0x1c)."""
    return _u32(d, 0x1C) != 0xEFEFEFEF


def header_fields(d):
    """name_hash, duration, bones (track count), rig_hash, game. On PiP the
    rig hash is the clip rig id at +0x5c, not a skeleton hash (11.2)."""
    if is_pip(d):
        return {"name_hash": _u32(d, 8), "duration": struct.unpack_from(">f", d, 0x10)[0],
                "bones": _u32(d, 0x34), "rig_hash": _u32(d, 0x5C), "game": "pip",
                "additive": bool(d[0x60])}
    return {"name_hash": _u32(d, 8), "duration": struct.unpack_from(">f", d, 0x10)[0],
            "bones": _u32(d, 0x24), "rig_hash": _u32(d, 0x4C), "game": "nb1"}


def sha256(b):
    return hashlib.sha256(bytes(b)).hexdigest()


def retarget(model, imap, local_n, rig_hash):
    """A foreign-rig model moved onto a local skeleton. imap[j] is the local
    bone driven by foreign bone j, -1 for none: the retarget map the game
    ships in the local unit's anim-set record (LU_FORMAT.md 25.1). Values are
    copied as they are (absolute local TRS), as the engine's map does.
    Unmapped local bones get no channels (they hold their bind pose)."""
    bones = [{"keyed": [], "static": []} for _ in range(local_n)]
    taken = {}
    for j, bone in enumerate(model["bones"]):
        t = imap[j] if j < len(imap) else -1
        if t < 0 or t >= local_n:
            continue
        if t in taken:
            raise EncodeError(f"foreign bones {taken[t]} and {j} both map to "
                              f"local bone {t}")
        taken[t] = j
        bones[t] = {"keyed": bone["keyed"], "static": bone["static"]}
    head = bytearray(model["header"])
    struct.pack_into(">I", head, 0x4C, rig_hash)
    struct.pack_into(">I", head, 0x24, local_n)
    return dict(model, header=bytes(head), bones=bones)


def linear_channel(tag, v0, v1, duration):
    """A keyed channel going linearly from v0 at 0 to v1 at `duration`."""
    return {"tag": tag, "end": float(duration), "pieces": [{
        "start": 0.0, "kind": "poly", "times": np.array([float(duration)]),
        "coef": np.array([[v1 - v0, v0]], float), "tmode": 1, "rate": 0x1E,
        "nib": 2}]}


def _arr(x):
    return [float(v) for v in np.asarray(x, float).reshape(-1)]


def model_to_json(model):
    """Model -> plain dict (the neutral form a .srpatch stores). Holds only
    the motion: per-bone channels, duration, bounds, the +0x50 flag. The
    header and marker table come from the target clip when it is built."""
    h = model["header"]
    if model.get("game") == "pip":
        # PiP binds tracks to bones by name hash, so a clip carries its own
        # bone list, and the tail table (pairs of track indexes) goes with it
        out = {"format": CLIP_JSON, "version": CLIP_JSON_VERSION, "game": "pip",
               "rig": f"{_u32(h, 0x5C):08x}", "bone_count": len(model["bones"]),
               "bone_hashes": [f"{x:08x}" for x in model["bone_hashes"]],
               "duration": struct.unpack_from(">f", h, 0x10)[0],
               "bounds": list(struct.unpack_from(">4f", h, 0x40)),
               "additive": h[0x60], "tail": bytes(model["markers"]).hex(), "bones": []}
    else:
        out = {"format": CLIP_JSON, "version": CLIP_JSON_VERSION, "game": "nb1",
               "rig": f"{_u32(h, 0x4C):08x}", "bone_count": len(model["bones"]),
               "duration": struct.unpack_from(">f", h, 0x10)[0],
               "bounds": list(struct.unpack_from(">4f", h, 0x30)),
               "flag50": h[0x50], "bones": []}
    for i, bone in enumerate(model["bones"]):
        jb = {}
        if bone["keyed"]:
            jb["keyed"] = []
            for ch in bone["keyed"]:
                pcs = []
                for pc in ch["pieces"]:
                    if "times" not in pc:
                        raise EncodeError(f"bone {i} tag {ch['tag']:02x}: a piece "
                                          f"did not decode; cannot store it")
                    jp = {"start": float(pc["start"]), "kind": pc["kind"],
                          "times": _arr(pc["times"]),
                          "tmode": pc.get("tmode", 1), "rate": pc.get("rate", 0x1E)}
                    if pc["kind"] == "sample":
                        jp["values"] = _arr(pc["values"])
                        jp["nib"] = pc.get("nib", 8)
                    else:
                        c = np.asarray(pc["coef"], float)
                        jp["coef"] = [_arr(r) for r in c]
                    pcs.append(jp)
                jb["keyed"].append({"tag": ch["tag"], "end": float(ch["end"]),
                                    "pieces": pcs})
        if bone["static"]:
            jb["static"] = [{"tag": s["tag"], "value": float(s["value"])}
                            for s in bone["static"] if s["tag"] in _KNOWN]
        out["bones"].append(jb)
    return out


def model_from_json(obj, target_record):
    """Neutral clip + the target clip record it replaces -> model.

    NB1: header and marker table are the target's (its name, rig and
    skeleton pairs); the motion, duration, bounds and +0x50 flag are the
    neutral clip's, and rig and bone count must match the target's.
    PiP: only the target's name (+0x08) is kept. Tracks bind to bones by name
    hash, so the clip brings its own bone list, tail table, clip rig id and
    additive flag; any bone count works."""
    if obj.get("format") != CLIP_JSON:
        raise EncodeError("not a Seam Ripper clip file")
    if obj.get("version", 0) > CLIP_JSON_VERSION:
        raise EncodeError(f"clip file version {obj['version']} needs a newer "
                          f"Seam Ripper")
    t = header_fields(target_record)
    game = obj.get("game", "nb1")
    if game != t["game"]:
        names = {"nb1": "Naughty Bear", "pip": "Panic in Paradise"}
        raise EncodeError(f"the clip is from {names.get(game, game)}, the clip it "
                          f"replaces from {names[t['game']]}")
    if len(obj["bones"]) != obj["bone_count"]:
        raise EncodeError("bone count does not match the bone list")
    if game == "nb1":
        if int(obj["rig"], 16) != t["rig_hash"]:
            raise EncodeError(f"the clip is for rig {obj['rig']}, the clip it "
                              f"replaces is rig {t['rig_hash']:08x}")
        if obj["bone_count"] != t["bones"]:
            raise EncodeError(f"the clip has {obj['bone_count']} bones, the clip it "
                              f"replaces {t['bones']}")
    dur = float(obj["duration"])
    if not (math.isfinite(dur) and 0 < dur < 3600):
        raise EncodeError(f"bad duration {dur}")
    m = parse_clip(target_record)
    head = bytearray(m["header"])
    struct.pack_into(">f", head, 0x10, dur)
    if game == "pip":
        n = obj["bone_count"]
        hashes = [int(x, 16) for x in obj["bone_hashes"]]
        tail = bytes.fromhex(obj.get("tail", ""))
        if len(hashes) != n or not 0 < n < 2048:
            raise EncodeError("the clip needs one bone hash per track")
        if len(tail) % 16:
            raise EncodeError("tail table is not whole 16-byte entries")
        for k in range(0, len(tail), 16):
            a, b = struct.unpack_from(">2H", tail, k)
            if a >= n or b >= n:
                raise EncodeError(f"tail entry {k // 16} names track {max(a, b)} "
                                  f"of {n}")
        struct.pack_into(">4f", head, 0x40, *obj["bounds"])
        struct.pack_into(">I", head, 0x5C, int(obj["rig"], 16))
        head[0x60] = int(obj.get("additive", 0)) & 0xFF
        m = dict(m, bone_hashes=hashes, markers=tail, marker_slot=(EMPTY, 0))
    else:
        struct.pack_into(">4f", head, 0x30, *obj["bounds"])
        head[0x50] = int(obj.get("flag50", 0)) & 0xFF
    bones = []
    for jb in obj["bones"]:
        keyed = []
        for ch in jb.get("keyed", []):
            if ch["tag"] not in _KNOWN:
                raise EncodeError(f"unknown channel tag {ch['tag']:#x}")
            pcs = []
            for p in ch["pieces"]:
                pc = {"start": float(p["start"]), "kind": p["kind"],
                      "times": np.array(p["times"], float),
                      "tmode": int(p.get("tmode", 1)), "rate": int(p.get("rate", 0x1E))}
                if p["kind"] == "sample":
                    pc["values"] = np.array(p["values"], float)
                    pc["nib"] = int(p.get("nib", 8))
                    n = len(pc["values"])
                else:
                    pc["coef"] = np.array(p["coef"], float)
                    if pc["coef"].ndim != 2 or not 2 <= pc["coef"].shape[1] <= 4:
                        raise EncodeError("polynomial keys need 2 to 4 coefficients")
                    n = len(pc["coef"])
                if n != len(pc["times"]) or n == 0:
                    raise EncodeError("key count does not match key times")
                if np.any(np.diff(pc["times"]) < 0):
                    raise EncodeError("key times must not decrease")
                pcs.append(pc)
            keyed.append({"tag": ch["tag"], "end": float(ch["end"]), "pieces": pcs})
        static = [{"tag": s["tag"], "value": float(s["value"]),
                   "payload": f24_encode(s["value"])} for s in jb.get("static", [])]
        bones.append({"keyed": keyed, "static": static})
    return dict(m, header=bytes(head), bones=bones)


def build_clip(obj, target_record):
    """Neutral clip -> the record that replaces `target_record`."""
    return encode_clip(model_from_json(obj, target_record), "f32")


def clip_records(lu, name_hash):
    """Every local clip record of `lu` with this name hash."""
    return [r for r in lu.records if r.hash == name_hash and not r.external
            and r.type == CLIP_TYPE and r.size >= 0x60
            and _u32(lu.chunk(r), 0) == CLIP_TYPE]


def pip_slot(lu, index):
    """Bytes a PiP record may take without moving: up to the next record
    (rebuild_luh writes a record that fits here in place; one that does not
    is moved, which hangs the game)."""
    r = lu.records[index]
    after = [x.offset for x in lu.records
             if not x.external and x.offset > r.offset]
    return (min(after) if after else len(lu.image)) - r.offset


def replace_in_container(lu_path, clips, check_sha=True):
    """Build the clips into a container -> (file bytes, log lines).
    clips: [(name_hash, neutral clip dict, original record sha256 or None)
            or the same plus (slot clip hash, its record sha256 or None)].
    Each clip record is rebuilt from the recipient's own target record, then
    the container is rebuilt (NB1: relaid out and recompressed,
    lu_chunk_replace.rebuild; PiP: naughty_lu.rebuild_luh, which keeps every
    other record where it is and writes raw segments, the form PiP loads) and
    read back: every replaced record must come back byte for byte and decode
    cleanly, and every other record must be unchanged.

    A slot clip (PiP only) is a bigger clip of the same container whose
    record takes the replacement instead: the two records trade names (the
    record table hash and the clip's own name at +0x08), so no record changes
    size or place. The replaced clip's original motion then plays under the
    slot clip's name."""
    import os
    import tempfile
    from naughty_lu import LuFile, rebuild_luh
    from lu_chunk_replace import rebuild
    from lu_anim2 import decode_clip
    lu = LuFile(lu_path)
    name = Path(lu_path).name
    luh = getattr(lu, "is_luh", False)
    reps, ren, log = {}, {}, []

    def record(h, sha, what):
        recs = clip_records(lu, h)
        if len(recs) != 1:
            raise EncodeError(f"{name}: {len(recs)} clip records named {h:08x} "
                              f"(need exactly one)")
        old = bytes(lu.chunk(recs[0]))
        if check_sha and sha and sha256(old) != sha:
            raise EncodeError(f"{name}: {what} {h:08x} is not the one the patch "
                              f"was made for")
        return recs[0], old

    hashes = [c[0] for c in clips]
    slots = [c[3] for c in clips if len(c) > 3 and c[3] is not None]
    for x in set(slots):
        if slots.count(x) > 1 or x in hashes:
            raise EncodeError(f"{name}: clip {x:08x} is used as the record of more "
                              f"than one replacement, or is replaced itself")
    for c in clips:
        h, obj, sha = c[:3]
        slot_h = c[3] if len(c) > 3 else None
        r, old = record(h, sha, "clip")
        new = build_clip(obj, old)
        line = (f"  clip {h:08x}: {len(old):,} -> {len(new):,} bytes, "
                f"{obj['duration']:.2f} s")
        dest, dest_old = r, old
        if slot_h is not None:
            if not luh:
                raise EncodeError(f"{name}: only Panic in Paradise clips can take "
                                  f"another clip's record")
            dest, dest_old = record(slot_h, c[4] if len(c) > 4 else None, "clip")
            renamed = bytearray(old)
            struct.pack_into(">I", renamed, 8, slot_h)
            reps[r.index], ren[r.index] = bytes(renamed), slot_h
            ren[dest.index] = h
            line += (f", in clip {slot_h:08x}'s record ({len(dest_old):,} bytes); "
                     f"{slot_h:08x} now names the original {h:08x}")
        if luh:
            # PiP lays a container's records out by their sizes: a record
            # that moves (grows past its slot) or shrinks hangs level load
            # (verified in game for scripts and clips, 2026-11-17). So a clip
            # must fit its slot, and a shorter one is padded back to the
            # original size.
            slot = pip_slot(lu, dest.index)
            if len(new) > slot:
                raise EncodeError(
                    f"{name}: the replacement for clip {h:08x} is {len(new):,} "
                    f"bytes and its record holds {slot:,}; on Panic in Paradise a "
                    f"clip must fit the record it goes into (a record that moves "
                    f"or changes size hangs the game)")
            if len(new) < len(dest_old):
                new += b"\xEF" * (len(dest_old) - len(new))
                line += f" (padded to {len(dest_old):,})"
        reps[dest.index] = new
        log.append(line)
    try:
        if luh:
            out = rebuild_luh(lu, reps, renames=ren)
            how = (f"LUH, raw segments; {len(reps)} record(s) rewritten in place, "
                   f"sizes kept" + (f", {len(ren)} renamed" if ren else ""))
        else:
            out, how = rebuild(lu, reps)
    except ValueError as e:
        raise EncodeError(str(e))
    log.append(f"  container rebuilt ({how})")
    fd, tmp = tempfile.mkstemp(suffix=".lu")
    os.close(fd)
    try:
        Path(tmp).write_bytes(out)
        back = LuFile(tmp)
        for i, data in reps.items():
            got = bytes(back.chunk(back.records[i]))
            if got != data:
                raise EncodeError(f"record {i} did not read back identically")
            if back.records[i].hash != ren.get(i, lu.records[i].hash):
                raise EncodeError(f"record {i} did not keep its new name")
            st = Counter()
            if decode_clip(got, st) is None or any(
                    k.startswith(("bad_", "size_mismatch", "unknown_enc")) for k in st):
                raise EncodeError(f"record {i} does not decode cleanly: {dict(st)}")
        others = [r for r in lu.records if r.index not in reps and not r.external]
        for r in others:
            if bytes(back.chunk(back.records[r.index])) != bytes(lu.chunk(r)):
                raise EncodeError(f"record {r.index} changed although it was "
                                  f"not edited")
    finally:
        os.unlink(tmp)
    log.append(f"  read back: {len(reps)} record(s) identical, "
               f"{len(others)} other record(s) unchanged")
    return out, log


# ---------------------------------------------------------------------- cli

def _looks_like_clip(d):
    """An NB1 clip (efefefef at +0x1c) or a PiP one (bone-hash table at 0x70)."""
    return (len(d) >= 0x70 and d[:4] == b"\x04\x30\x00\x00"
            and (d[0x1C:0x20] == b"\xEF" * 4 or _u32(d, 0x1C) == 0x70))


def _iter_clips(paths):
    """(label, record bytes) for every clip (NB1 or PiP) in the given .lu
    files or folders of decoded chunks (*.bin)."""
    from naughty_lu import LuFile
    for p in paths:
        p = Path(p)
        if p.is_dir() and not any(p.glob("*.lu")):
            for f in sorted(p.rglob("*.bin")):
                d = f.read_bytes()
                if _looks_like_clip(d):
                    yield str(f), d
            continue
        files = sorted(p.glob("*.lu")) if p.is_dir() else [p]
        for f in files:
            lu = LuFile(f)
            for r in lu.records:
                if r.external or r.size < 0x60:
                    continue
                d = lu.chunk(r)
                if _looks_like_clip(d):
                    yield f"{f.name}:{r.hash:08x}", bytes(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("roundtrip", help="decode, encode, decode every clip")
    pr.add_argument("paths", nargs="+", help=".lu files, folders of them, or "
                                             "folders of decoded chunks")
    pr.add_argument("--json", help="write the per-clip report here")
    a = ap.parse_args()
    if a.cmd == "roundtrip":
        import anim_roundtrip
        rc = anim_roundtrip.run(_iter_clips(a.paths), a.json)
        sys.exit(rc)


if __name__ == "__main__":
    main()
