#!/usr/bin/env python3
"""Replace one record's bytes inside a .lu, keeping the image layout."""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile              # noqa: E402
from lzx_encode import xmem_lzx_compress   # noqa: E402


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def record_alignment(rec):
    """The top byte of a record's flags is log2 of its alignment in the image."""
    return 1 << (rec.flags >> 24)


def relayout(lu, replacements):
    """Image with records' bytes replaced -> (image, {index: offset}).

    The engine expects every record at the first multiple of its alignment
    after the previous record ends (0xBF fill between). Records before the
    first replaced one stay put; from there on each is placed by that rule.
    """
    image = lu.image
    recs = sorted((r for r in lu.records if not r.external and r.size > 0),
                  key=lambda r: (r.offset, r.index))
    first = min(lu.records[i].offset for i in replacements)
    out = bytearray(image[:first])
    offsets = {}
    placed = {}   # original offset -> new offset (records sharing an offset)
    end = first
    for r in recs:
        if r.offset < first:
            continue
        if r.offset in placed:
            offsets[r.index] = placed[r.offset]
            continue
        a = record_alignment(r)
        at = (end + a - 1) // a * a
        out += b"\xBF" * (at - len(out))
        data = replacements.get(r.index, image[r.offset:r.offset + r.size])
        out += data
        offsets[r.index] = placed[r.offset] = at
        end = at + len(data)
    last = max(r.offset + r.size for r in recs)
    out += image[last:]
    # empty records keep their place relative to the record before them
    moved = sorted(placed.items())
    for r in lu.records:
        if r.external or r.index in offsets or r.offset < first:
            continue
        prev = [o for o in moved if o[0] <= r.offset]
        offsets[r.index] = r.offset + (prev[-1][1] - prev[-1][0] if prev else 0)
    return out, offsets


def write_record_table(raw, offsets, sizes):
    """Write new offsets / sizes into the record table of a container's header
    (by index, so a partner record sharing a hash keeps its own entry)."""
    fo = 0x20 + u32(raw, 0x38)
    table = 0x20 + u32(raw, fo)
    for i, off in offsets.items():
        struct.pack_into(">I", raw, table + i * 0x18 + 0x10, off)
    for i, size in sizes.items():
        struct.pack_into(">I", raw, table + i * 0x18 + 0x0C, size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu")
    ap.add_argument("chunk")
    ap.add_argument("--hash")
    ap.add_argument("--index", type=int,
                    help="record table index: exact, even when several "
                         "records share one hash")
    ap.add_argument("--name")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    lu = LuFile(a.lu)
    raw = bytearray(lu.raw)
    image = bytearray(lu.image)
    new = Path(a.chunk).read_bytes()

    target = None
    if a.index is not None:
        if not 0 <= a.index < len(lu.records):
            sys.exit(f"no record {a.index}")
        target = lu.records[a.index]
        if a.hash and target.hash != int(a.hash, 16):
            sys.exit(f"REFUSED: record {a.index} has hash {target.hash:#010x}, "
                     f"not {a.hash}")
    elif a.hash:
        # A script can share its hash with a partner record (a module
        # descriptor, an object record). Taking the first match would
        # overwrite the partner, so a shared hash must be addressed by index.
        same = [r for r in lu.records if r.hash == int(a.hash, 16)
                and not r.external]
        if len(same) > 1:
            sys.exit(f"REFUSED: {len(same)} records share hash {a.hash} "
                     f"(indices {', '.join(str(r.index) for r in same)}); "
                     f"pass --index to say which one to replace")
        target = same[0] if same else None
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

    new_image, offsets = relayout(lu, {target.index: new})
    write_record_table(raw, offsets, {target.index: len(new)})

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
