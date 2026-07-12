#!/usr/bin/env python3
"""verify_lzx.py - independent integrity check for a rebuilt .lu container.

Two legs, both mandatory for a PASS:

  structural  - record table and XMemCompress frame layout match the retail
                conventions verified on real NB1/PiP files this project has
                seen: every record offset 16-byte aligned, alignment gaps
                0xBF-filled, each segment's final frame in 5-byte escape form,
                each segment terminated by a 5-byte all-zero marker, and the
                segment-size table agreeing with the actual compressed bytes.

  independent - each compressed segment is decoded by a SEPARATE LZX
                implementation (a bundled libmspack-based binary, invoked as
                a subprocess) and the result compared byte-for-byte against
                the image the container claims to hold. This exists because
                self-consistency (this project's own encoder round-tripping
                through its own decoder) produced false confidence twice;
                a decoder written by the same author as the encoder shares
                its blind spots. libmspack is an independent codebase.

The independent leg REQUIRES the verifier binary. If it is missing, that is
a FAIL, not a skip: "sometimes verified" is a worse guarantee than "always
verified," and a silent fallback to the self-decoder is exactly the failure
mode that shipped a crashing build earlier in this project.

Used two ways:
  * imported: cmd_ship calls verify_file() before accepting a rebuilt .lu.
  * standalone: `python verify_lzx.py <file.lu>` checks any .lu on disk,
    retail or already-shipped, without going through an edit.
"""
import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile, LZX_FRAME_SIZE  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD_ALIGN = 16
ALIGN_FILL = 0xBF
STREAM_TERMINATOR = b"\x00" * 5


class VerifyError(Exception):
    pass


def find_verifier(explicit=None):
    """Locate the bundled independent-decoder binary, mirroring nblua's
    find_luac pattern. Returns a path string or None."""
    if explicit:
        return explicit if Path(explicit).exists() else None
    names = ["lzxverify.exe", "lzxverify"] if os.name == "nt" else ["lzxverify"]
    for n in names:
        p = HERE / n
        if p.exists():
            return str(p)
    return None


# ---------------------------------------------------------------- segments

def _segment_blobs(lu):
    """Return the list of raw compressed segment byte-blobs, in order."""
    if not lu.compressed:
        return None
    d = lu.raw
    off = lu.data_base
    segs = []
    for size in lu.segment_sizes:
        segs.append(d[off:off + size])
        off += size
    return segs


def _walk_frames(seg):
    """Walk one segment's XMemCompress frames. Returns (frames, ok_terminator)
    where frames is a list of dicts describing each frame, and ok_terminator
    is True iff the segment ends with the 5-byte zero marker. Raises
    VerifyError on a structurally impossible frame chain."""
    frames = []
    i = 0
    n = len(seg)
    while i < n:
        if seg[i:i + 5] == STREAM_TERMINATOR and i + 5 == n:
            return frames, True
        if seg[i] == 0xFF:
            if i + 5 > n:
                raise VerifyError(f"truncated escape header at {i:#x}")
            usize = struct.unpack_from(">H", seg, i + 1)[0]
            csize = struct.unpack_from(">H", seg, i + 3)[0]
            body = i + 5
            frames.append({"escape": True, "usize": usize, "csize": csize,
                           "at": i, "payload": seg[body:body + csize]})
            i = body + csize
        else:
            csize = struct.unpack_from(">H", seg, i)[0]
            body = i + 2
            frames.append({"escape": False, "usize": LZX_FRAME_SIZE,
                           "csize": csize, "at": i,
                           "payload": seg[body:body + csize]})
            i = body + csize
        if csize == 0:
            raise VerifyError(f"zero-length frame at {frames[-1]['at']:#x}")
        if i > n:
            raise VerifyError(f"frame at {frames[-1]['at']:#x} runs past "
                              f"segment end ({i:#x} > {n:#x})")
    return frames, False


# ---------------------------------------------------------------- structural

def check_structural(lu):
    """Raise VerifyError on any deviation from retail layout convention.
    Returns a short summary string on success."""
    recs = sorted((r for r in lu.records if not r.external),
                  key=lambda r: r.offset)

    misaligned = [r for r in recs if r.offset % RECORD_ALIGN]
    if misaligned:
        idxs = ", ".join(str(r.index) for r in misaligned[:8])
        more = "" if len(misaligned) <= 8 else f" (+{len(misaligned) - 8} more)"
        raise VerifyError(
            f"{len(misaligned)} record(s) not {RECORD_ALIGN}-byte aligned: "
            f"{idxs}{more}. Retail aligns every record; a raw-delta shift "
            f"after a resized chunk breaks this.")

    img = lu.image
    for r1, r2 in zip(recs, recs[1:]):
        gap_start = r1.offset + r1.size
        gap = r2.offset - gap_start
        if gap < 0:
            raise VerifyError(f"records {r1.index}/{r2.index} overlap "
                              f"({gap_start:#x} > {r2.offset:#x})")
        if 0 < gap < RECORD_ALIGN:
            fill = img[gap_start:r2.offset]
            if fill != bytes([ALIGN_FILL]) * gap:
                raise VerifyError(
                    f"alignment gap after record {r1.index} is not "
                    f"{ALIGN_FILL:#04x}-filled: {fill.hex()}")

    if not lu.compressed:
        return f"structural OK ({len(recs)} records, raw/uncompressed image)"

    segs = _segment_blobs(lu)
    if len(segs) != lu.segment_count:
        raise VerifyError(f"segment count {lu.segment_count} != "
                          f"{len(segs)} actual blobs")

    total_usize = 0
    for si, seg in enumerate(segs):
        if len(seg) != lu.segment_sizes[si]:
            raise VerifyError(f"segment {si} size table says "
                              f"{lu.segment_sizes[si]}, blob is {len(seg)}")
        frames, term = _walk_frames(seg)
        if not frames:
            raise VerifyError(f"segment {si} has no frames")
        if not term:
            raise VerifyError(f"segment {si} missing 5-byte zero terminator")
        if not frames[-1]["escape"]:
            raise VerifyError(f"segment {si} final frame is not in escape "
                              f"form (retail always escapes the last frame)")
        total_usize += sum(f["usize"] for f in frames)

    if total_usize != lu.image_size:
        raise VerifyError(f"frame usize total {total_usize} != declared "
                          f"image size {lu.image_size}")

    return (f"structural OK ({len(recs)} records, {len(segs)} segment(s), "
            f"image {lu.image_size} bytes)")


# ---------------------------------------------------------------- independent

def _strip_frames(seg):
    """Concatenate a segment's raw LZX payload (headers removed) and return
    (payload_bytes, total_uncompressed_size)."""
    payload = bytearray()
    total = 0
    frames, _ = _walk_frames(seg)
    for f in frames:
        payload += f["payload"]
        total += f["usize"]
    return bytes(payload), total


def check_independent(lu, verifier):
    """Decode every segment with the bundled independent binary and compare
    against the container image. Raise VerifyError on any mismatch or on a
    missing binary. Returns a summary string on success."""
    if not lu.compressed:
        return "independent decode skipped (raw/uncompressed container)"

    if verifier is None:
        raise VerifyError(
            "independent decoder binary not found (looked for lzxverify next "
            "to this script). This leg is mandatory: build the verifier from "
            "libmspack and bundle it. Refusing rather than silently trusting "
            "the self-decoder.")

    window = lu.lzx_window or 0x100000
    wbits = window.bit_length() - 1

    segs = _segment_blobs(lu)
    image = lu.image
    pos = 0
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="lzxverify_"))
    try:
        for si, seg in enumerate(segs):
            payload, usize = _strip_frames(seg)
            fin = tmp / f"seg{si}.in"
            fout = tmp / f"seg{si}.out"
            fin.write_bytes(payload)
            r = subprocess.run(
                [verifier, str(fin), str(fout), str(wbits), str(usize)],
                capture_output=True, text=True)
            if r.returncode != 0:
                raise VerifyError(
                    f"segment {si}: independent decoder returned "
                    f"{r.returncode}: {r.stderr.strip()}")
            got = fout.read_bytes()
            want = image[pos:pos + usize]
            if got != want:
                first = next((k for k in range(min(len(got), len(want)))
                              if got[k] != want[k]), min(len(got), len(want)))
                raise VerifyError(
                    f"segment {si}: independent decode differs from container "
                    f"image at byte {first:#x} (got {len(got)} bytes, "
                    f"expected {usize})")
            pos += usize
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    return f"independent decode OK ({len(segs)} segment(s), byte-exact)"


# ---------------------------------------------------------------- top level

def verify_file(path, verifier=None, on_log=None):
    """Run both legs on a .lu path. Returns a list of summary strings.
    Raises VerifyError on the first failure. on_log, if given, is called with
    each summary string as it passes."""
    lu = LuFile(path)
    results = []
    for check in (check_structural, lambda l: check_independent(l, find_verifier(verifier))):
        msg = check(lu)
        results.append(msg)
        if on_log:
            on_log(msg)
    return results


def main():
    ap = argparse.ArgumentParser(description="Verify a rebuilt .lu container.")
    ap.add_argument("lu")
    ap.add_argument("--verifier", help="path to the independent decoder binary")
    ap.add_argument("--structural-only", action="store_true",
                    help="skip the independent-decode leg (diagnostic use "
                         "only; not a valid ship gate)")
    a = ap.parse_args()

    lu = LuFile(a.lu)
    try:
        print(check_structural(lu))
        if a.structural_only:
            print("independent decode SKIPPED (--structural-only)")
        else:
            print(check_independent(lu, find_verifier(a.verifier)))
    except VerifyError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
