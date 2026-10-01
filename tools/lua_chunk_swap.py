#!/usr/bin/env python3
"""Splice new Lua bytecode into a Naughty Bear script chunk."""
import argparse, struct
from pathlib import Path

def swap(chunk, new_image):
    i = chunk.find(b"\x1bLua")
    if i < 0:
        raise ValueError("no Lua image in chunk")
    old_sz = struct.unpack_from(">I", chunk, 0x1c)[0]
    footer = chunk[i + old_sz:]
    out = bytearray(chunk[:i])              # wrapper
    out += new_image
    out += footer
    struct.pack_into(">I", out, 0x1c, len(new_image))
    struct.pack_into(">I", out, 0x20, i + len(new_image))
    return bytes(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chunk"); ap.add_argument("image")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    out = swap(Path(a.chunk).read_bytes(), Path(a.image).read_bytes())
    Path(a.out).write_bytes(out)
    print(f"wrote {a.out} ({len(out)} bytes)")

if __name__ == "__main__": main()
