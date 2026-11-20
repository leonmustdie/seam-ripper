#!/usr/bin/env python3
"""Texture records of Naughty Bear (type 14200007) and Panic in Paradise
(34200007): decode every mip level, and encode a replacement image back into
the record without changing its size.

  lu_texture.py roundtrip PATHS...      decode, re-tile, compare every texture
  lu_texture.py mipcheck PATHS...       do the decoded mips look like the base?

PATHS are .lu files, folders of them, or folders of decoded chunks (*.bin).

The record (LU_FORMAT.md section 10, 32):
  +0x00 tag 34200007, +0x08 width, +0x0c height, +0x10 bits per texel,
  +0x14 class tag, +0x20 header size 0x40, +0x24 mip level count,
  +0x28 Xenos format dword (low 6 bits = format, bits 6-7 = endian swap),
  +0x38 pixel data offset (0x1000), +0x3c pixel data size.
The pixel data is Xenos tiled. Level 0 is one 4 KB-aligned surface whose
pitch and height are rounded up to 32 blocks. Levels 1 and up follow it, each
its own 32-block-aligned surface computed from the power-of-two size, until
the packed level: the first level whose shorter side is 16 texels or less.
From there every remaining level sits in one surface at a fixed block offset
(the "packed mip tail"). A texture whose shorter side is already 16 or less
keeps all its levels in the level 0 surface.

A replacement keeps the size, format and level count, so the record keeps its
size and every byte not covered by a level (tile padding) is kept as it was.
"""
import argparse
import functools
import io
import os
import struct
import sys
from pathlib import Path

import numpy as np

TEX_TAGS = (b"\x34\x20\x00\x07",)                # record body tag, both games
TEX_TYPES = (0x14200007, 0x34200007)             # record table type ids
# Xenos format code -> (name, texels per block side, bytes per block)
FORMATS = {0x12: ("DXT1", 4, 8), 0x13: ("DXT3", 4, 16), 0x14: ("DXT5", 4, 16),
           0x06: ("ARGB8", 1, 4)}
HEADER = 0x40
TEX_DIR_GLOBS = ("*/texture/*.bin", "*/type_34200007/*.bin", "*/type_14200007/*.bin",
                 "texture/*.bin", "type_34200007/*.bin")


class TextureError(Exception):
    pass


def _log2c(v):
    return (v - 1).bit_length()


def _np2(v):
    return 1 << _log2c(v)


def _al(v, a):
    return (v + a - 1) // a * a


# ------------------------------------------------------------------ header

def is_texture(d):
    return len(d) >= HEADER and d[:4] in TEX_TAGS


def info(d):
    """Header fields of a texture record -> dict; raises TextureError."""
    if not is_texture(d):
        raise TextureError("not a texture record")
    w, h = struct.unpack_from(">2I", d, 8)       # width first (section 32.1)
    levels, fmt = struct.unpack_from(">2I", d, 0x24)
    doff, dsz = struct.unpack_from(">2I", d, 0x38)
    code = fmt & 0x3F
    if code not in FORMATS:
        raise TextureError(f"unsupported Xenos format {code:#04x}")
    name, bw, bpb = FORMATS[code]
    return {"width": w, "height": h, "levels": levels, "fmt": fmt, "code": code,
            "format": name, "block": bw, "bpb": bpb, "endian": (fmt >> 6) & 3,
            "data_offset": doff, "data_size": dsz}


# ------------------------------------------------------------------ layout

def packed_level(w, h):
    s = _log2c(min(w, h))
    return s - 4 if s > 4 else 0


def packed_offset(w, h, level, bw):
    """Block offset (x, y) of a packed level inside the tail surface. Port of
    Xenia's GetPackedMipOffset (2D)."""
    lw, lh = _log2c(w), _log2c(h)
    base = max(min(lw, lh) - 4, 0)
    pm = level - base
    if pm < 3:
        x, y = (0, 16 >> pm) if lw > lh else (16 >> pm, 0)
    else:
        if lw > lh:
            x, y = (1 << (lw - base)) >> (pm - 2), 0
        else:
            x, y = 0, (1 << (lh - base)) >> (pm - 2)
    return x // bw, y // bw


def layout(t):
    """Where each level lives -> list of dicts {level, offset (bytes from the
    pixel data start), pitch (blocks), x, y (block origin), wb, hb (blocks)}
    plus the total size the levels need."""
    w, h, n, bw, bpb = t["width"], t["height"], t["levels"], t["block"], t["bpb"]
    pl = packed_level(w, h)

    def surface(pt, rt):
        pitch = _al(-(-pt // bw), 32)
        return pitch, _al(pitch * _al(-(-rt // bw), 32) * bpb, 4096)

    out = []
    pitch0, size0 = surface(w, h)
    total = size0
    off = size0                               # where the next surface starts
    tail = None                               # (offset, pitch) of the packed tail
    for lv in range(n):
        wb = -(-max(w >> lv, 1) // bw)
        hb = -(-max(h >> lv, 1) // bw)
        if pl == 0:                            # everything in the level 0 surface
            x, y = packed_offset(w, h, lv, bw)
            out.append({"level": lv, "offset": 0, "pitch": pitch0, "x": x, "y": y,
                        "wb": wb, "hb": hb})
            continue
        if lv == 0:
            out.append({"level": 0, "offset": 0, "pitch": pitch0, "x": 0, "y": 0,
                        "wb": wb, "hb": hb})
            continue
        if lv < pl:
            pitch, size = surface(max(_np2(w) >> lv, 1), max(_np2(h) >> lv, 1))
            out.append({"level": lv, "offset": off, "pitch": pitch, "x": 0, "y": 0,
                        "wb": wb, "hb": hb})
            off += size
            total += size
            continue
        if tail is None:
            pitch, size = surface(max(_np2(w) >> pl, 1), max(_np2(h) >> pl, 1))
            tail = (off, pitch)
            off += size
            total += size
        x, y = packed_offset(w, h, lv, bw)
        out.append({"level": lv, "offset": tail[0], "pitch": tail[1], "x": x, "y": y,
                    "wb": wb, "hb": hb})
    return out, total


def tiled_offsets(x, y, pitch, bpb):
    """Byte offsets of blocks (x, y) in a tiled surface (numpy arrays). Port
    of XGAddress2DTiledOffset / Xenia GetTiledOffset2D."""
    lb = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}[bpb]
    pitch = _al(pitch, 32)
    macro = ((x >> 5) + (y >> 5) * (pitch >> 5)) << (lb + 7)
    micro = ((x & 7) + ((y & 0xE) << 2)) << lb
    off = macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 1) << 4)
    return (((off & ~0x1FF) << 3) + ((y & 16) << 7) + ((off & 0x1C0) << 2)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (off & 0x3F))


def _block_addresses(t, lv):
    """Byte offsets (from the pixel data start) of level lv's blocks, row
    major, as a read-only int64 array of shape (hb, wb). They depend on the
    size, level count and block format only, so each is worked out once."""
    return _addresses(t["width"], t["height"], t["levels"], t["block"], t["bpb"], lv)


@functools.lru_cache(maxsize=256)
def _addresses(w, h, n, block, bpb, lv):
    t = {"width": w, "height": h, "levels": n, "block": block, "bpb": bpb}
    L = layout(t)[0][lv]
    ys, xs = np.mgrid[0:L["hb"], 0:L["wb"]]
    a = L["offset"] + tiled_offsets(xs + L["x"], ys + L["y"], L["pitch"], bpb)
    a.setflags(write=False)
    return a


def _swap(b, endian):
    """Xenos endian swap (1 = 8in16, 2 = 8in32, 3 = 16in32). Self-inverse."""
    a = np.frombuffer(bytes(b), np.uint8)
    if endian == 1:
        return a.reshape(-1, 2)[:, ::-1].tobytes()
    if endian == 2:
        return a.reshape(-1, 4)[:, ::-1].tobytes()
    if endian == 3:
        return a.reshape(-1, 2, 2)[:, ::-1, :].tobytes()
    return bytes(b)


# ------------------------------------------------------------------ decode

def level_blocks(d, lv, t=None):
    """Level lv as linear little-endian blocks (standard DDS order) -> bytes."""
    t = t or info(d)
    addr = _block_addresses(t, lv).ravel()
    pix = np.frombuffer(d, np.uint8, t["data_size"], t["data_offset"])
    if addr.max() + t["bpb"] > len(pix):
        raise TextureError(f"level {lv} runs past the pixel data")
    idx = addr[:, None] + np.arange(t["bpb"])
    return _swap(pix[idx].tobytes(), t["endian"])


def level_image(d, lv=0, t=None):
    """Level lv as a PIL RGBA image."""
    from PIL import Image
    t = t or info(d)
    blocks = level_blocks(d, lv, t)
    w, h = max(t["width"] >> lv, 1), max(t["height"] >> lv, 1)
    if t["format"] == "ARGB8":
        a = np.frombuffer(blocks, np.uint8).reshape(h, w, 4)   # B G R A after swap
        return Image.fromarray(a[:, :, [2, 1, 0, 3]].copy(), "RGBA")
    return Image.open(io.BytesIO(dds(w, h, t["format"], blocks))).convert("RGBA")


def dds(w, h, fourcc, payload, mips=1):
    hdr = struct.pack("<4sII II I II 44x", b"DDS ", 124,
                      0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if mips > 1 else 0),
                      h, w, len(payload), 0, mips)
    pf = struct.pack("<II4sIIIII", 32, 0x4, fourcc.encode(), 0, 0, 0, 0, 0)
    caps = struct.pack("<IIIII", 0x1000 | (0x400008 if mips > 1 else 0), 0, 0, 0, 0)
    return hdr + pf + caps + payload


def to_dds(d):
    """The whole texture (every level) as a standard DDS file -> bytes."""
    t = info(d)
    if t["format"] == "ARGB8":
        raise TextureError("ARGB8 textures export as PNG only")
    body = b"".join(level_blocks(d, lv, t) for lv in range(t["levels"]))
    return dds(t["width"], t["height"], t["format"], body, t["levels"])


# ------------------------------------------------------------------ encode

def put_levels(d, levels):
    """A copy of record d with the given levels replaced.
    levels: {level: linear little-endian blocks}. Every other byte (header,
    other levels, tile padding) is kept, so the size never changes."""
    t = info(d)
    out = bytearray(d)
    pix = np.frombuffer(out, np.uint8, t["data_size"], t["data_offset"])
    pix = pix.copy()
    for lv, blocks in levels.items():
        addr = _block_addresses(t, lv).ravel()
        if len(blocks) != len(addr) * t["bpb"]:
            raise TextureError(f"level {lv} needs {len(addr) * t['bpb']} bytes, "
                               f"got {len(blocks)}")
        src = np.frombuffer(_swap(blocks, t["endian"]), np.uint8).reshape(-1, t["bpb"])
        pix[addr[:, None] + np.arange(t["bpb"])] = src
    out[t["data_offset"]:t["data_offset"] + t["data_size"]] = pix.tobytes()
    return bytes(out)


def _compress(img, fmt):
    """PIL RGBA image -> linear little-endian blocks in fmt."""
    if fmt == "ARGB8":
        a = np.asarray(img.convert("RGBA"), np.uint8)
        return a[:, :, [2, 1, 0, 3]].tobytes()
    b = io.BytesIO()
    img.convert("RGBA").save(b, "DDS", pixel_format=fmt)
    return b.getvalue()[128:]


def encode_image(d, img, mips="generate"):
    """Record d with its picture replaced by PIL image img (any mode).
    The image must have the texture's width and height. Every mip level is
    made by box-filtering img down (the D3DX default) and compressed in the
    record's own format; mips='keep' leaves levels 1 and up as they were."""
    from PIL import Image
    t = info(d)
    img = img.convert("RGBA")
    if img.size != (t["width"], t["height"]):
        raise TextureError(f"the image is {img.size[0]}x{img.size[1]}; this texture "
                           f"is {t['width']}x{t['height']} (resize it to match)")
    levels = {}
    for lv in range(t["levels"] if mips == "generate" else 1):
        size = (max(t["width"] >> lv, 1), max(t["height"] >> lv, 1))
        im = img if lv == 0 else img.resize(size, Image.BOX)
        levels[lv] = _compress(im, t["format"])
    return put_levels(d, levels)


def encode_dds(d, data):
    """Record d with its levels taken from a DDS file (bytes) of the same
    size and format. Levels the DDS lacks are generated from its level 0."""
    from PIL import Image
    t = info(d)
    if data[:4] != b"DDS ":
        raise TextureError("not a DDS file")
    h, w = struct.unpack_from("<2I", data, 12)
    n = max(struct.unpack_from("<I", data, 28)[0], 1)
    four = data[84:88].decode("latin-1")
    if (w, h) != (t["width"], t["height"]):
        raise TextureError(f"the DDS is {w}x{h}; this texture is "
                           f"{t['width']}x{t['height']}")
    if four != t["format"]:
        img = Image.open(io.BytesIO(data))
        return encode_image(d, img)              # recompress in the record's format
    pos, levels = 128, {}
    for lv in range(min(n, t["levels"])):
        wb = -(-max(w >> lv, 1) // 4)
        hb = -(-max(h >> lv, 1) // 4)
        size = wb * hb * t["bpb"]
        if pos + size > len(data):
            break
        levels[lv] = data[pos:pos + size]
        pos += size
    if len(levels) < t["levels"]:
        img = Image.open(io.BytesIO(data))
        full = encode_image(d, img)
        missing = {lv: level_blocks(full, lv) for lv in range(len(levels), t["levels"])}
        levels.update(missing)
    return put_levels(d, levels)


def encode_file(d, path):
    """Record d with the picture from a PNG/TGA/... or DDS file."""
    from PIL import Image
    data = Path(path).read_bytes()
    if data[:4] == b"DDS ":
        return encode_dds(d, data)
    return encode_image(d, Image.open(io.BytesIO(data)))


# ------------------------------------------------------------------ containers

def sha256(b):
    import hashlib
    return hashlib.sha256(bytes(b)).hexdigest()


def texture_records(lu, h):
    import lu_records
    return lu_records.local_records(lu, h, TEX_TYPES)


def encode_source(d, src, cache=None):
    """Record d with the picture from src: a file path, or (name, bytes).
    cache: a folder shared by the containers of one patch apply. The same
    picture going into textures of the same size, format and level count
    (one texture kept in several containers) is encoded once; every other
    record gets the same levels (put_levels keeps its own header and padding)."""
    from PIL import Image
    if cache is not None:
        data = src[1] if isinstance(src, tuple) else Path(src).read_bytes()
        t = info(d)
        key = sha256(data + f"|{t['format']}|{t['width']}x{t['height']}"
                            f"|{t['levels']}".encode())
        levels = _cached_levels(Path(cache), key,
                                lambda: _all_levels(encode_source(d, src), t))
        return put_levels(d, levels)
    if isinstance(src, tuple):
        data = src[1]
        if data[:4] == b"DDS ":
            return encode_dds(d, data)
        return encode_image(d, Image.open(io.BytesIO(data)))
    return encode_file(d, src)


def _all_levels(d, t):
    return {lv: level_blocks(d, lv, t) for lv in range(t["levels"])}


def _cached_levels(folder, key, make, wait=1800):
    """Levels stored under key in folder, made by make() the first time.
    Several processes may ask at once: the first takes key.lock and encodes,
    the others wait for key.bin (or encode themselves if the lock goes away
    without one, or after `wait` seconds)."""
    import time
    folder.mkdir(parents=True, exist_ok=True)
    done, lock = folder / f"{key}.bin", folder / f"{key}.lock"
    start = time.monotonic()
    while not done.exists():
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            if time.monotonic() - start > wait:
                return make()
            time.sleep(0.2)
            continue
        try:
            levels = make()
            body = b"".join(struct.pack("<II", lv, len(b)) + b
                            for lv, b in sorted(levels.items()))
            tmp = folder / f"{key}.{os.getpid()}.tmp"
            tmp.write_bytes(struct.pack("<I", len(levels)) + body)
            os.replace(tmp, done)
            return levels
        finally:
            lock.unlink(missing_ok=True)
    raw = done.read_bytes()
    levels, pos = {}, 4
    for _ in range(struct.unpack_from("<I", raw, 0)[0]):
        lv, n = struct.unpack_from("<II", raw, pos)
        levels[lv] = raw[pos + 8:pos + 8 + n]
        pos += 8 + n
    return levels


def replace_in_container(lu_path, items, check_sha=True, cache=None):
    """Build replacement pictures into a container -> (file bytes, log lines).
    items: [(texture name hash, picture (path or (name, bytes)), original
    record sha256 or None)]. Each record is re-encoded from the container's
    own record (same size, format and level count), then the container is
    rebuilt and read back (lu_records.rebuild). cache: see encode_source."""
    import lu_records
    from naughty_lu import LuFile
    lu = LuFile(lu_path)
    name = Path(lu_path).name
    reps, log = {}, []
    for h, src, sha in items:
        recs = texture_records(lu, h)
        if len(recs) != 1:
            raise TextureError(f"{name}: {len(recs)} textures named {h:08x} with "
                               f"their own data (need exactly one)")
        old = bytes(lu.chunk(recs[0]))
        if check_sha and sha and sha256(old) != sha:
            raise TextureError(f"{name}: texture {h:08x} is not the one the patch "
                               f"was made for")
        new = encode_source(old, src, cache)
        t = info(old)
        reps[recs[0].index] = new
        log.append(f"  texture {h:08x}: {t['width']}x{t['height']} {t['format']}, "
                   f"{t['levels']} levels, {len(new):,} bytes (size kept)")

    def check(i, got):
        try:
            _, probs = roundtrip(got)
        except TextureError as e:
            return f"does not decode: {e}"
        return "; ".join(probs) or None
    try:
        out, how = lu_records.rebuild(lu, reps, check)
    except lu_records.RecordError as e:
        raise TextureError(str(e))
    log.append(f"  container rebuilt ({how})")
    return out, log


# ------------------------------------------------------------------ checks

def roundtrip(d):
    """Decode every level and write them back into a blank copy of the pixel
    data. -> (rebuilt record, problems). Retail must come back byte for byte:
    the levels cover every nonzero byte and no two levels share a block."""
    t = info(d)
    probs = []
    lay, total = layout(t)
    if total != t["data_size"]:
        probs.append(f"layout needs {total} bytes, record has {t['data_size']}")
        return None, probs
    if len(d) != t["data_offset"] + t["data_size"]:
        probs.append("record does not end at the pixel data end")
    blank = bytearray(d)
    blank[t["data_offset"]:] = bytes(t["data_size"])
    seen = np.zeros(t["data_size"], bool)
    levels = {}
    for lv in range(t["levels"]):
        a = _block_addresses(t, lv).ravel()
        cov = (a[:, None] + np.arange(t["bpb"])).ravel()
        if seen[cov].any():
            probs.append(f"level {lv} overlaps an earlier level")
        seen[cov] = True
        levels[lv] = level_blocks(d, lv, t)
    rebuilt = put_levels(bytes(blank), levels)
    if rebuilt != d:
        diff = np.flatnonzero(np.frombuffer(rebuilt, np.uint8) != np.frombuffer(d, np.uint8))
        probs.append(f"{len(diff)} bytes differ (first at {diff[0]:#x})")
    return rebuilt, probs


def iter_textures(paths):
    """(label, record bytes) for every texture in .lu files, folders of them,
    or folders of decoded chunks."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from naughty_lu import LuFile
    for p in paths:
        p = Path(p)
        if p.is_dir() and not any(p.glob("*.lu")):
            # naughty_lu extract layout: <unit>/texture/*.bin (NB1),
            # <unit>/type_34200007/*.bin (PiP); else every .bin below
            files = [f for pat in TEX_DIR_GLOBS for f in p.glob(pat)]
            for f in sorted(files or p.rglob("*.bin")):
                with open(f, "rb") as fh:
                    head = fh.read(4)
                if head in TEX_TAGS:
                    yield str(f), f.read_bytes()
            continue
        for f in (sorted(p.glob("*.lu")) if p.is_dir() else [p]):
            lu = LuFile(f)
            for r in lu.records:
                if r.external or r.type not in TEX_TYPES:
                    continue
                yield f"{f.name}:{r.hash:08x}", bytes(lu.chunk(r))


def mip_error(d, lv, t=None):
    """Mean absolute difference (0-255 per channel, RGB premultiplied by
    alpha, plus alpha) between level lv and level 0 scaled down to the same
    size. Premultiplied because the colour under a fully transparent texel is
    arbitrary and differs between levels."""
    from PIL import Image
    t = t or info(d)
    base = level_image(d, 0, t)
    m = level_image(d, lv, t)
    ref = base.resize(m.size, Image.BOX)

    def pm(im):
        a = np.asarray(im, np.float32)
        return np.concatenate([a[:, :, :3] * a[:, :, 3:] / 255, a[:, :, 3:]], 2)
    return float(np.abs(pm(m) - pm(ref)).mean())


def _cmd_roundtrip(a):
    import hashlib
    seen, n, bad = set(), 0, 0
    for label, d in iter_textures(a.paths):
        k = hashlib.sha1(d).digest()
        if k in seen:
            continue
        seen.add(k)
        n += 1
        try:
            _, probs = roundtrip(d)
        except TextureError as e:
            probs = [str(e)]
        if probs:
            bad += 1
            if bad <= 20:
                print(f"FAIL {label}: {'; '.join(probs)}")
    print(f"{n} unique textures, {n - bad} re-emitted byte for byte, {bad} failed")
    return 1 if bad else 0


def _cmd_mipcheck(a):
    import hashlib
    seen, rows = set(), []
    for label, d in iter_textures(a.paths):
        k = hashlib.sha1(d).digest()
        if k in seen:
            continue
        seen.add(k)
        t = info(d)
        for lv in range(1, t["levels"]):
            if min(t["width"] >> lv, t["height"] >> lv) < a.min_size:
                break
            rows.append((mip_error(d, lv, t), lv, label))
    errs = np.array([r[0] for r in rows])
    print(f"{len(seen)} textures, {len(rows)} mip levels of side >= {a.min_size}: "
          f"error median {np.median(errs):.2f}, p95 {np.percentile(errs, 95):.2f}, "
          f"max {errs.max():.2f} (0-255 per channel)")
    for e, lv, label in sorted(rows, reverse=True)[:a.worst]:
        print(f"  {e:6.2f}  level {lv}  {label}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("roundtrip")
    pr.add_argument("paths", nargs="+")
    pm = sub.add_parser("mipcheck")
    pm.add_argument("paths", nargs="+")
    pm.add_argument("--min-size", type=int, default=4)
    pm.add_argument("--worst", type=int, default=10)
    a = ap.parse_args()
    sys.exit(_cmd_roundtrip(a) if a.cmd == "roundtrip" else _cmd_mipcheck(a))


if __name__ == "__main__":
    main()
