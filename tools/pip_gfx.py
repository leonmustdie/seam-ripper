#!/usr/bin/env python3
"""
pip_gfx.py — extract Scaleform UI movies and their textures from
Panic in Paradise .lu files (or already-extracted 04d00001 chunks).

PiP's UI chunks (record type 04d00001) each contain:
  1. a GFx movie ('CFX' = zlib-compressed, 'GFX' = stored) — the vector
     shell, layout and actionscript,
  2. an image table of {name_offset, name_length, data_offset,
     data_size} big-endian quads,
  3. the referenced images as standard little-endian DDS files
     (DXT1/3/5, written by gfxexport at build time — no console tiling).

The movie references its images by filename via GFx tag 1009
(DefineExternalImage2); the engine resolves those names against the
embedded blob at load time.

output per movie:  <name>.gfx  +  <name>/<image>.png  (.dds if Pillow
is missing or the format is exotic)

usage:
  python3 pip_gfx.py <files.lu | chunks.bin | movies.gfx ...> -o out/
  python3 pip_gfx.py briefingscreen.lu -o ui/ --dds   # keep raw DDS too
"""
import argparse
import io
import struct
import sys
import zlib
from pathlib import Path

from naughty_lu import LuFile

try:
    from PIL import Image
except ImportError:
    Image = None

GFX_TYPE = 0x04D00001


def find_movie(chunk):
    """Locate the CFX/GFX movie inside a chunk. Returns (start, end) or None."""
    c = chunk.find(b"CFX")
    g = chunk.find(b"GFX")
    m = min((x for x in (c, g) if x >= 0), default=-1)
    if m < 0:
        return None
    if chunk[m:m + 3] == b"CFX":
        dec = zlib.decompressobj()
        try:
            dec.decompress(bytes(chunk[m + 8:]))
        except zlib.error:
            return None
        return m, len(chunk) - len(dec.unused_data)
    end = m + 8 + struct.unpack_from("<I", chunk, m + 4)[0]
    return m, min(end, len(chunk))


def image_table(chunk, search_from):
    """Yield (name, dds_bytes) for every image table entry.

    Entries are {u32 name_off, u32 name_len, u32 data_off, u32 data_size}
    big-endian, chunk-relative, with NUL-terminated names and 'DDS '
    payloads. The table is located by scanning for self-consistent quads,
    which sidesteps the (only partially understood) header around it.
    """
    pos = search_from
    n = len(chunk)
    while pos + 16 <= n:
        no, nl, do_, ds = struct.unpack_from(">4I", chunk, pos)
        if (0 < nl < 256 and search_from <= no < n and ds > 0x80
                and search_from <= do_ <= n - ds
                and chunk[do_:do_ + 4] == b"DDS "
                and chunk[no + nl - 1:no + nl] == b"\x00"):
            name = chunk[no:no + nl - 1].decode("ascii", "replace")
            yield name, chunk[do_:do_ + ds]
            pos += 16
        else:
            pos += 1


def save_image(dds, out_base, keep_dds=False):
    """Write PNG (via Pillow) and/or DDS. Returns list of written paths."""
    written = []
    if Image is not None:
        try:
            img = Image.open(io.BytesIO(bytes(dds)))
            p = out_base.with_suffix(".png")
            img.save(p)
            written.append(p)
        except Exception:
            keep_dds = True
    else:
        keep_dds = True
    if keep_dds:
        p = out_base.with_suffix(".dds")
        p.write_bytes(dds)
        written.append(p)
    return written


def process_chunk(chunk, name, outdir, keep_dds=False, quiet=False):
    """Extract one 04d00001 chunk. Returns (n_movies, n_images)."""
    loc = find_movie(chunk)
    if loc is None:
        return 0, 0
    m, end = loc
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{name}.gfx").write_bytes(chunk[m:end])
    n_img = 0
    imgdir = outdir / name
    for iname, dds in image_table(chunk, end):
        imgdir.mkdir(parents=True, exist_ok=True)
        base = imgdir / Path(iname).stem
        save_image(dds, base, keep_dds)
        n_img += 1
    if not quiet:
        print(f"  {name}: movie {end - m} bytes, {n_img} textures")
    return 1, n_img


def process_lu(path, outdir, keep_dds=False, quiet=False):
    lf = LuFile(path)
    unit = Path(path).stem
    from naughty_lu import harvest_names
    names = harvest_names([lf])
    n_mov = n_img = 0
    for r in lf.records:
        if r.type != GFX_TYPE or r.external:
            continue
        name = names.get(r.hash) or f"{r.index:04d}_{r.hash:08x}"
        a, b = process_chunk(lf.chunk(r), name, outdir / unit, keep_dds, quiet)
        n_mov += a
        n_img += b
    return n_mov, n_img


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("inputs", nargs="+", help=".lu files, chunk .bin files, or .gfx files")
    ap.add_argument("-o", "--out", default="ui_out", help="output directory")
    ap.add_argument("--dds", action="store_true", help="also keep raw .dds files")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    if Image is None:
        print("note: Pillow not installed; textures will be saved as .dds only",
              file=sys.stderr)
    tot_m = tot_i = 0
    for inp in args.inputs:
        p = Path(inp)
        data = p.read_bytes()
        if data[:4] in (b"\x05LUH",) or data[:1] == b"\x03":
            if not args.quiet:
                print(f"{p.name}:")
            m, i = process_lu(p, out, args.dds, args.quiet)
        else:
            # raw chunk or bare .gfx: both go through the same dissection
            if not args.quiet:
                print(f"{p.name}:")
            m, i = process_chunk(data, p.stem, out, args.dds, args.quiet)
        tot_m += m
        tot_i += i
    print(f"done: {tot_m} movies, {tot_i} textures -> {out}")


if __name__ == "__main__":
    main()
