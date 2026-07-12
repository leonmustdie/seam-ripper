#!/usr/bin/env python3
"""lu_grep.py - search UTF-16 localization text across many .lu files.

Scans every .lu in a folder, decompresses, extracts strings, and prints
matches as:  FILE  HASH  text

Usage:
  lu_grep.py PATTERN  path/to/lu/            # search a folder (recursive)
  lu_grep.py PATTERN  a.lu b.lu              # search specific files
  lu_grep.py -i PATTERN folder/              # case-insensitive
  lu_grep.py -e PATTERN folder/              # PATTERN is a regex
  lu_grep.py --list-files folder/            # just show which .lu have text

Pairs with lu_strings.py: copy the printed HASH into the extracted
strings.txt for that FILE to edit it.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile  # noqa: E402
from lu_strings import read_string  # noqa: E402


def iter_strings(lu_path):
    """Yield (hash, text) for every readable localization string in a .lu."""
    try:
        lu = LuFile(str(lu_path))
        image = lu.image
    except Exception as e:
        print(f"warning: {lu_path}: {e}", file=sys.stderr)
        return
    for r in lu.records:
        try:
            text, strlen, _ = read_string(image, r.offset)
        except Exception:
            continue
        if strlen == 0 or strlen > 4096:
            continue
        yield r.hash, text


def collect_files(paths):
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(pp.rglob("*.lu"))
        elif pp.is_file():
            files.append(pp)
        else:
            print(f"warning: {p}: not found", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="Search text across .lu files.")
    ap.add_argument("pattern", nargs="?", help="text or regex to find")
    ap.add_argument("paths", nargs="+", help="folder(s) or .lu file(s)")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("-e", "--regex", action="store_true", help="treat pattern as regex")
    ap.add_argument("--list-files", action="store_true",
                    help="list .lu files that contain any text, with string counts")
    args = ap.parse_args()

    files = collect_files(args.paths)
    if not files:
        print("no .lu files found", file=sys.stderr)
        sys.exit(1)

    if args.list_files:
        for f in files:
            n = sum(1 for _ in iter_strings(f))
            if n:
                print(f"{n:6d}  {f}")
        return

    if not args.pattern:
        print("error: pattern required (unless --list-files)", file=sys.stderr)
        sys.exit(2)

    flags = re.IGNORECASE if args.ignore_case else 0
    if args.regex:
        rx = re.compile(args.pattern, flags)
        test = lambda t: rx.search(t) is not None
    else:
        needle = args.pattern.lower() if args.ignore_case else args.pattern
        test = (lambda t: needle in t.lower()) if args.ignore_case else (lambda t: args.pattern in t)

    total = 0
    for f in files:
        for h, text in iter_strings(f):
            if test(text):
                disp = text.replace("\n", "\\n")
                print(f"{f.name}\t{h:08x}\t{disp}")
                total += 1
    print(f"--- {total} match(es) across {len(files)} file(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
