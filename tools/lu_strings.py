#!/usr/bin/env python3
"""lu_strings.py - extract / apply UTF-16 localization strings in x36 .lu files.

Workflow:
  1. lu_strings.py extract orig.lu -o strings.txt
       -> writes one editable line per record: HASH<TAB>text
  2. edit strings.txt (fix spelling, change wording; keep the HASH<TAB> prefix)
  3. lu_strings.py apply orig.lu strings.txt -o edited.lu
       -> rebuilds the image with your edits, fixes every record offset/size,
          and writes a raw (codec=0) container the engine loads directly.

Handles length-changing edits: when a string's byte length changes, all
later record offsets shift and the affected record's size updates, both in
the record table and re-derived in the image.

Each localization record in the decompressed image is:
  hash(4) type(4) ... strlen_u32 UTF-16BE-text(strlen units, NUL-terminated)
then 0xBF / 0x00 padding to the next record. The string length field is the
last u32 before the text; we locate it from the record layout the engine uses
(strlen at record_offset + 0x20, text at +0x24), matching all observed files.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile, rebuild_luh  # noqa: E402

STRLEN_REL = 0x20   # u32 string length (in UTF-16 units, incl. trailing NUL)
TEXT_REL = 0x24     # UTF-16BE text starts here
TAB = "\t"


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def read_string(image, rec_off):
    """Return (text_without_nul, strlen_units, total_text_bytes)."""
    strlen = u32(image, rec_off + STRLEN_REL)
    raw = image[rec_off + TEXT_REL: rec_off + TEXT_REL + strlen * 2]
    text = raw.decode("utf-16-be", "replace")
    if text.endswith("\x00"):
        text = text[:-1]
    return text, strlen, strlen * 2


PIP_TABLE_TYPE = 0x04D00013


def pip_parse_table(c):
    """Parse a PiP 04d00013 string-table chunk -> [(hash, text)]."""
    n = u32(c, 0xC)
    out = []
    for i in range(n):
        h = u32(c, 0x10 + i * 16)
        off = u32(c, 0x10 + i * 16 + 8)
        ln = u32(c, off + 0x10)
        text = c[off + 0x14: off + 0x14 + 2 * ln].decode("utf-16-be")
        out.append((h, text.rstrip("\x00")))
    return out


def pip_build_table(strings):
    """Rebuild a 04d00013 chunk from [(hash, text)]. Byte-identical to
    retail for unmodified input (validated on all five language units)."""
    n = len(strings)
    table = bytearray()
    payload = bytearray()
    base = 0x10 + n * 16
    for h, text in strings:
        if len(payload) % 4:
            payload += b"\xBF" * (4 - len(payload) % 4)
        off = base + len(payload)
        table += struct.pack(">4I", h, 0x04D00002, off, 1)
        units = text.encode("utf-16-be") + b"\x00\x00"
        payload += struct.pack(">2I", 0x04D00003, off + 8)
        payload += struct.pack(">2I", 0x04D00003, off + 0x14)
        payload += struct.pack(">I", len(units) // 2) + units
    return bytes(struct.pack(">4I", 0, 0, 0x10, n) + table + payload)


def esc(t):
    return t.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def unesc(t):
    return (t.replace("\\n", "\n").replace("\\t", "\t")
             .replace("\\\\", "\\"))


def pip_extract(lu, out):
    lines = []
    n = 0
    for r in lu.records:
        if r.type != PIP_TABLE_TYPE or r.external:
            continue
        lines.append(f"# record {r.index} ({r.hash:08x})")
        for h, text in pip_parse_table(lu.chunk(r)):
            lines.append(f"{h:08x}{TAB}{esc(text)}")
            n += 1
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"extracted {n} strings from {sum(1 for r in lu.records if r.type == PIP_TABLE_TYPE)} tables -> {out}")


def pip_apply(lu, edited, out, verify=False):
    edits = {}
    for ln in Path(edited).read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        h, _, text = ln.partition(TAB)
        edits[int(h, 16)] = unesc(text)

    new_chunks = {}
    n_changed = 0
    for r in lu.records:
        if r.type != PIP_TABLE_TYPE or r.external:
            continue
        strings = pip_parse_table(lu.chunk(r))
        rebuilt = [(h, edits.get(h, t)) for h, t in strings]
        n_changed += sum(1 for (h, t), (_, t2) in zip(strings, rebuilt) if t != t2)
        new_chunks[r.index] = pip_build_table(rebuilt)

    data = rebuild_luh(lu, new_chunks)
    Path(out).write_bytes(data)
    print(f"applied ({n_changed} strings changed) -> {out} "
          f"({len(data):,} bytes, stored segments)")

    if verify:
        lu2 = LuFile(out)
        ok = True
        for r in lu2.records:
            if r.type != PIP_TABLE_TYPE:
                continue
            for h, t in pip_parse_table(lu2.chunk(r)):
                if h in edits and t != edits[h]:
                    print(f"  VERIFY FAIL {h:08x}: got {t!r}", file=sys.stderr)
                    ok = False
        print("VERIFY OK: container re-parses, all edits present"
              if ok else "VERIFY had failures")


def cmd_extract(args):
    lu = LuFile(args.orig)
    out = Path(args.out) if args.out else Path(args.orig).with_suffix(".strings.txt")
    if getattr(lu, "is_luh", False):
        pip_extract(lu, out)
        return
    image = lu.image
    lines = []
    n_text = 0
    for r in lu.records:
        try:
            text, strlen, _ = read_string(image, r.offset)
        except Exception:
            continue
        if strlen == 0 or strlen > 4096:
            continue
        n_text += 1
        # escape newlines/tabs so one record = one line
        safe = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        lines.append(f"{r.hash:08x}{TAB}{safe}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"extracted {n_text} strings -> {out}")


def cmd_apply(args):
    lu = LuFile(args.orig)
    if getattr(lu, "is_luh", False):
        out = args.out or str(Path(args.orig).with_suffix(".edited.lu"))
        pip_apply(lu, args.edited, out, verify=args.verify)
        return
    image = bytearray(lu.image)
    raw = bytearray(lu.raw)

    # parse edited strings file: HASH<TAB>text per line
    edits = {}
    for ln in Path(args.edited).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or TAB not in ln:
            continue
        h, text = ln.split(TAB, 1)
        text = text.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        edits[int(h, 16)] = text

    # locate record table in header
    fo = 0x20 + u32(raw, 0x38)
    table = 0x20 + u32(raw, fo)
    count = u32(raw, fo + 4)

    # build records in image order so we can recompute shifts
    recs = sorted(lu.records, key=lambda r: r.offset)
    new_image = bytearray()
    new_off = {}      # hash -> new offset
    new_size = {}     # hash -> new size
    changed = 0

    for idx, r in enumerate(recs):
        # original record byte span: from r.offset to next record's offset
        start = r.offset
        end = recs[idx + 1].offset if idx + 1 < len(recs) else len(image)
        chunk = bytearray(image[start:end])
        new_off[r.hash] = len(new_image)

        if r.hash in edits:
            try:
                old_text, old_strlen, old_textbytes = read_string(image, start)
            except Exception:
                old_text = None
            new_text = edits[r.hash]
            if old_text is not None and new_text != old_text:
                new_units = len(new_text) + 1  # + trailing NUL
                new_bytes = new_text.encode("utf-16-be") + b"\x00\x00"
                # rebuild chunk: [0:STRLEN] + new strlen + new text, then re-pad
                head = chunk[:STRLEN_REL]
                rebuilt = bytearray()
                rebuilt += head
                rebuilt += struct.pack(">I", new_units)
                rebuilt += new_bytes
                # records are 16-byte aligned; pad with 0xBF to the next 0x10
                # boundary so the following record stays aligned (matches the
                # engine layout: a trailing 0xBF run rounds each record up).
                while len(rebuilt) % 16 != 0:
                    rebuilt.append(0xBF)
                chunk = rebuilt
                changed += 1

        new_size[r.hash] = len(chunk)   # full record span (matches table size semantics)
        new_image += chunk
        # keep the next record 16-byte aligned regardless of edits
        while len(new_image) % 16 != 0:
            new_image.append(0xBF)

    # rewrite record table size(+0x0C)/offset(+0x10) for every record
    for i in range(count):
        e = table + i * 0x18
        h = u32(raw, e)
        if h in new_off:
            struct.pack_into(">I", raw, e + 0x0C, new_size[h])
            struct.pack_into(">I", raw, e + 0x10, new_off[h])

    # patch pool-info -> raw mode, append new image
    pi = 0x20 + u32(raw, 0x34)
    struct.pack_into(">I", raw, pi + 0x00, 0)
    struct.pack_into(">I", raw, pi + 0x04, len(new_image))
    struct.pack_into(">I", raw, pi + 0x08, 0)
    struct.pack_into(">I", raw, pi + 0x0C, 1)
    struct.pack_into(">I", raw, pi + 0x10, 0xFFFFFFFF)
    struct.pack_into(">I", raw, pi + 0x14, 0)

    header = bytes(raw[:lu.data_base])
    out = header + bytes(new_image)
    op = Path(args.out) if args.out else Path(args.orig).with_suffix(".edited.lu")
    op.write_bytes(out)
    print(f"applied {changed} edits, wrote {op} ({len(out)} bytes, raw/codec=0)")

    if args.verify:
        v = LuFile(str(op))
        vimg = v.image
        ok = True
        for r in v.records:
            if r.hash in edits:
                try:
                    t, _, _ = read_string(vimg, r.offset)
                except Exception:
                    continue
                if t != edits[r.hash]:
                    print(f"  VERIFY FAIL {r.hash:08x}: got {t!r}", file=sys.stderr)
                    ok = False
        print("VERIFY OK: all edits present and readable" if ok else "VERIFY had failures")


def main():
    ap = argparse.ArgumentParser(description="Extract/apply UTF-16 localization strings in NB1 x36 and PiP LUH .lu files (auto-detected).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="dump strings to an editable text file")
    pe.add_argument("orig")
    pe.add_argument("-o", "--out")
    pe.set_defaults(func=cmd_extract)

    pa = sub.add_parser("apply", help="apply edited strings, write raw .lu")
    pa.add_argument("orig")
    pa.add_argument("edited")
    pa.add_argument("-o", "--out")
    pa.add_argument("--verify", action="store_true")
    pa.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
