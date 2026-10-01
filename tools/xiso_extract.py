#!/usr/bin/env python3
"""List and extract the files on an Xbox 360 disc image (.iso)."""
import argparse
import struct
import sys
from pathlib import Path

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
# where the game's file system starts: rebuilt/trimmed images at 0, full
# 360 disc images after the video partition (XGD2, XGD3), original Xbox (XGD1)
PARTITIONS = (("rebuilt", 0), ("XGD2", 0xFD90000), ("XGD3", 0x2080000),
              ("XGD1", 0x18300000))
DIRECTORY = 0x10
CHUNK = 8 << 20


class DiscError(Exception):
    pass


def find_partition(f):
    """(layout name, byte offset) of the Xbox file system in an open image."""
    for name, off in PARTITIONS:
        f.seek(off + 32 * SECTOR)
        if f.read(len(MAGIC)) == MAGIC:
            return name, off
    raise DiscError("no Xbox file system found: this isn't an Xbox disc image")


def _entries(data):
    """Every (name, start sector, size, is_dir) in one directory's table.

    The table is a binary tree; each entry holds its left and right
    neighbours as offsets in 4-byte units, 0xFFFF meaning none."""
    out, seen, stack = [], set(), [0]
    while stack:
        pos = stack.pop()
        if pos in seen or pos + 14 > len(data):
            continue
        seen.add(pos)
        left, right, start, size, attr, nlen = struct.unpack_from("<HHIIBB", data, pos)
        if left == 0xFFFF and right == 0xFFFF:
            continue                        # sector padding, not an entry
        name = data[pos + 14:pos + 14 + nlen].decode("latin-1")
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise DiscError(f"bad file name on disc: {name!r}")
        out.append((name, start, size, bool(attr & DIRECTORY)))
        for nxt in (left, right):
            if nxt and nxt != 0xFFFF:
                stack.append(nxt * 4)
    return out


def files(f, base):
    """[(path inside the disc, start sector, size)] for every file."""
    f.seek(base + 32 * SECTOR + len(MAGIC))
    root, root_size = struct.unpack("<II", f.read(8))
    out, todo, done = [], [("", root, root_size)], set()
    while todo:
        path, sector, size = todo.pop()
        if sector in done:
            continue
        done.add(sector)
        f.seek(base + sector * SECTOR)
        for name, start, length, is_dir in _entries(f.read(size)):
            full = f"{path}/{name}" if path else name
            if is_dir:
                if length:
                    todo.append((full, start, length))
            else:
                out.append((full, start, length))
    return sorted(out, key=lambda e: e[0].lower())


def extract(image, out_dir, only=None, log=print):
    """Copy every file (or only those under the folder `only`) to out_dir."""
    out_dir = Path(out_dir)
    with open(image, "rb") as f:
        layout, base = find_partition(f)
        todo = files(f, base)
        if only:
            pre = only.strip("/\\").lower() + "/"
            todo = [e for e in todo if e[0].lower().startswith(pre)]
            if not todo:
                raise DiscError(f"no folder called {only!r} on this disc")
        total = sum(e[2] for e in todo)
        log(f"{layout} disc image: {len(todo)} files, {total / 2**20:.1f} MB")
        done = 0
        for i, (path, start, size) in enumerate(todo, 1):
            dest = out_dir.joinpath(*path.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.seek(base + start * SECTOR)
            left = size
            with open(dest, "wb") as w:
                while left:
                    block = f.read(min(CHUNK, left))
                    if not block:
                        raise DiscError(f"{path}: the image ends early (incomplete download?)")
                    w.write(block)
                    left -= len(block)
            done += size
            if i % 500 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} files, {done / 2**20:.0f} MB")
    log(f"done: {out_dir}")
    return len(todo)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list the files on the disc")
    pl.add_argument("image")
    pe = sub.add_parser("extract", help="copy the disc's files into a folder")
    pe.add_argument("image")
    pe.add_argument("-o", "--out", required=True, help="folder to extract into")
    pe.add_argument("--lu-only", action="store_true",
                    help="only the lu folder (the game files Seam Ripper edits)")
    a = ap.parse_args()
    try:
        if a.cmd == "list":
            with open(a.image, "rb") as f:
                layout, base = find_partition(f)
                entries = files(f, base)
            for path, _start, size in entries:
                print(f"{size:12}  {path}")
            print(f"{layout} disc image: {len(entries)} files")
        else:
            extract(a.image, a.out, "lu" if a.lu_only else None)
    except (DiscError, OSError) as e:
        sys.exit(f"{a.cmd}: {e}")


if __name__ == "__main__":
    main()
