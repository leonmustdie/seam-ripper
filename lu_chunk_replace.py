#!/usr/bin/env python3
"""lu_chunk_replace.py - replace one record's bytes inside a .lu, preserving the
original image layout (inter-record padding/gaps).

Uncompressed (codec 0) source containers: writes raw codec=0, same as
before.

Compressed (codec 2) source containers: re-compresses the edited image with
lzx_encode.xmem_lzx_compress, keeping the ORIGINAL container's codec=2 shape
(same window size, same per-segment framing the retail engine already
accepts) rather than flattening to raw — an earlier raw/codec=0 rewrite of a
compressed x36 file was found to corrupt at load (see nblua.py's ship-time
guard history). Only the common case (the edit doesn't change the segment
COUNT — true unless the image size crosses a whole window boundary) is
supported; anything else refuses rather than emit an unverified layout.

Same-size chunk replacement: in-place overwrite, no record offsets change.
Different-size: splice at the record, shift only records that start after
it, rewrite only their table offsets. All original padding before the edit
is kept.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile              # noqa: E402
from lzx_encode import xmem_lzx_compress   # noqa: E402


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu")
    ap.add_argument("chunk")
    ap.add_argument("--hash")
    ap.add_argument("--name")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    lu = LuFile(a.lu)
    raw = bytearray(lu.raw)
    image = bytearray(lu.image)
    new = Path(a.chunk).read_bytes()

    target = None
    if a.hash:
        for r in lu.records:
            if r.hash == int(a.hash, 16):
                target = r
                break
    elif a.name:
        # A bare substring match over raw chunk bytes is fragile — a short
        # common name can coincidentally appear inside unrelated binary
        # data (this corrupted a real file once: "npc" matched inside a
        # 224-byte sound descriptor before matching npc.lua's actual 37 KB
        # script chunk). Collect every match and refuse if there's more
        # than one, rather than silently taking the first.
        needle = a.name.encode()
        matches = [r for r in lu.records if needle in image[r.offset:r.offset + r.size]]
        if len(matches) > 1:
            sys.exit(f"REFUSED: '{a.name}' matches {len(matches)} records as a "
                     f"raw substring ({', '.join(f'{m.hash:#010x}' for m in matches)}) "
                     f"— ambiguous. Use --hash with the exact record hash instead "
                     f"(from `nblua.py list` or the caller's own resolved record).")
        target = matches[0] if matches else None
    if target is None:
        sys.exit("chunk not found")

    # Retail convention (verified on global.lu 347 records + levelcommon.lu
    # 965 records, zero exceptions): every record offset is 16-byte aligned,
    # inter-record alignment gaps are filled with 0xBF. A raw-delta shift
    # breaks alignment on every record after the splice point; pad the
    # replacement so the shift stays a multiple of 16.
    delta = len(new) - target.size
    pad = (-delta) % 16
    delta += pad
    new_image = (bytearray(image[:target.offset]) + bytearray(new)
                + bytearray(b"\xBF" * pad)
                + bytearray(image[target.offset + target.size:]))

    fo = 0x20 + u32(raw, 0x38)
    table = 0x20 + u32(raw, fo)
    count = u32(raw, fo + 4)

    if delta != 0:
        for i in range(count):
            e = table + i * 0x18
            h = u32(raw, e)
            off = u32(raw, e + 0x10)
            if h == target.hash:
                struct.pack_into(">I", raw, e + 0x0C, len(new))
            elif off != 0xFFFFFFFF and off > target.offset:
                struct.pack_into(">I", raw, e + 0x10, off + delta)

    pi = 0x20 + u32(raw, 0x34)

    if not lu.compressed:
        struct.pack_into(">I", raw, pi + 0x00, 0)
        struct.pack_into(">I", raw, pi + 0x04, len(new_image))
        struct.pack_into(">I", raw, pi + 0x08, 0)
        struct.pack_into(">I", raw, pi + 0x0C, 1)
        struct.pack_into(">I", raw, pi + 0x10, 0xFFFFFFFF)
        struct.pack_into(">I", raw, pi + 0x14, 0)
        out = bytes(raw[:lu.data_base]) + bytes(new_image)
        Path(a.out).write_bytes(out)
        print(f"wrote {a.out} ({len(out):,} bytes, raw/uncompressed)")
        return

    # --- compressed source: re-compress, keep the codec=2 container shape --
    window = lu.lzx_window or 0x100000
    wbits = window.bit_length() - 1
    old_segcount = lu.segment_count

    segments = []
    pos = 0
    n = len(new_image)
    while pos < n:
        seg = bytes(new_image[pos:pos + window])
        comp = xmem_lzx_compress(seg, wbits)
        # if compression didn't help (rare for tiny/high-entropy segments),
        # store it raw the same way retail does for incompressible segments
        # (naughty_lu.py's reader already treats csize==usize as "stored").
        if len(comp) >= len(seg):
            comp = seg
        segments.append(comp)
        pos += window

    if len(segments) != old_segcount:
        sys.exit(f"REFUSED: this edit changes the image from {old_segcount} to "
                 f"{len(segments)} pool segments (crossed a {window:#x}-byte "
                 f"window boundary). Relocating the segment-sizes table and "
                 f"record table for a different segment count isn't "
                 f"supported yet — trim the edit so the total image size "
                 f"stays within the same number of {window:#x}-byte windows.")

    sizes_rel = u32(raw, pi + 0x10)
    so = 0x20 + sizes_rel
    for i, seg in enumerate(segments):
        struct.pack_into(">I", raw, so + 4 * i, len(seg))

    struct.pack_into(">I", raw, pi + 0x00, 2)
    struct.pack_into(">I", raw, pi + 0x04, len(new_image))
    struct.pack_into(">I", raw, pi + 0x08, window)
    struct.pack_into(">I", raw, pi + 0x0C, len(segments))
    struct.pack_into(">I", raw, pi + 0x10, sizes_rel)
    struct.pack_into(">I", raw, pi + 0x14, len(segments))

    out = bytes(raw[:lu.data_base]) + b"".join(segments)
    Path(a.out).write_bytes(out)
    ratio = sum(len(s) for s in segments) / len(new_image) * 100
    print(f"wrote {a.out} ({len(out):,} bytes, {len(segments)} LZX segment(s), "
          f"{ratio:.0f}% of uncompressed size)")


if __name__ == "__main__":
    main()
