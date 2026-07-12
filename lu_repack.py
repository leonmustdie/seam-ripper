#!/usr/bin/env python3
"""lu_repack.py - write an x36 .lu container in RAW (codec=0) mode.

Pairs with naughty_lu.py. Takes an original .lu plus an optional edited
decompressed image, and emits a raw (uncompressed) container the engine
can load without an LZX encoder.

Pipeline for text edits:
  1. naughty_lu.py decompress orig.lu -o image.bin
  2. edit image.bin (UTF-16 strings)
  3. lu_repack.py orig.lu --image image.bin -o edited.lu

With no --image it does an identity round-trip (decompress->repack raw),
which is the test that proves the engine accepts codec=0 containers.

Header layout (mirrors naughty_lu.py LuFile parse, all big-endian):
  pool info block at  pi = 0x20 + u32(raw, 0x34)
    pi+0x00 codec          (2=LZX, 0=raw)
    pi+0x04 image_size      (uncompressed size)
    pi+0x08 lzx_window      (0 if raw)
    pi+0x0C segment_count   (1 if raw)
    pi+0x10 sizes_ptr_rel   (0xFFFFFFFF if raw)
    pi+0x14 segment_count2  (0 if raw)
  data region starts at data_base = 0x20 + u32(raw, 0x40)

Everything in raw[0:data_base] (deps, pool, footer, record table) is kept
verbatim except the six pool fields above. Record offsets are relative to
the decompressed image, so length-neutral edits need no pointer fix-ups.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile  # noqa: E402


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def repack_raw(orig_path, image_path=None, out_path=None, verbose=False):
    lu = LuFile(str(orig_path))
    raw = bytearray(lu.raw)

    # the decompressed image, original or edited
    if image_path:
        image = Path(image_path).read_bytes()
    else:
        image = lu.image  # identity round-trip

    pi = 0x20 + u32(raw, 0x34)
    data_base = lu.data_base

    old_codec = u32(raw, pi)
    old_image_size = u32(raw, pi + 4)

    if image_path and len(image) != old_image_size and verbose:
        print(f"note: edited image size {len(image):#x} != original "
              f"{old_image_size:#x} (length-changed edit; record offsets past "
              f"the edit may need fix-up if a chunk's byte length changed)",
              file=sys.stderr)

    # patch pool-info block -> raw mode
    struct.pack_into(">I", raw, pi + 0x00, 0)            # codec = raw
    struct.pack_into(">I", raw, pi + 0x04, len(image))   # image size
    struct.pack_into(">I", raw, pi + 0x08, 0)            # lzx window = 0
    struct.pack_into(">I", raw, pi + 0x0C, 1)            # segment count = 1
    struct.pack_into(">I", raw, pi + 0x10, 0xFFFFFFFF)   # sizes ptr = none
    struct.pack_into(">I", raw, pi + 0x14, 0)            # segment count2 = 0

    header = bytes(raw[:data_base])
    out = header + image

    if out_path:
        op = Path(out_path)
    else:
        op = Path(orig_path).with_suffix(".raw.lu")
    op.write_bytes(out)

    if verbose:
        print(f"  codec        : {old_codec} -> 0 (raw)")
        print(f"  image size   : {old_image_size:#x} -> {len(image):#x}")
        print(f"  data_base    : {data_base:#x}")
        print(f"  out size     : {len(out):#x} bytes")
    print(f"wrote {op} ({len(out)} bytes, raw/codec=0)")
    return op


def verify_roundtrip(orig_path, repacked_path):
    """Confirm the repacked raw file decodes to the same image as the original."""
    a = LuFile(str(orig_path))
    b = LuFile(str(repacked_path))
    ia, ib = a.image, b.image
    if ia == ib:
        print(f"VERIFY OK: decompressed images identical ({len(ia):#x} bytes)")
        return True
    n = min(len(ia), len(ib))
    first = next((i for i in range(n) if ia[i] != ib[i]), n)
    print(f"VERIFY FAIL: images differ. lenA={len(ia):#x} lenB={len(ib):#x} "
          f"first diff at {first:#x}", file=sys.stderr)
    return False


def main():
    ap = argparse.ArgumentParser(description="Repack an x36 .lu in raw (codec=0) mode.")
    ap.add_argument("orig", help="original .lu file")
    ap.add_argument("--image", help="edited decompressed image (omit for identity round-trip)")
    ap.add_argument("-o", "--out", help="output .lu path")
    ap.add_argument("--verify", action="store_true",
                    help="after writing, re-parse output and confirm image matches original")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    op = repack_raw(args.orig, args.image, args.out, verbose=True)

    if args.verify and not args.image:
        verify_roundtrip(args.orig, op)


if __name__ == "__main__":
    main()
