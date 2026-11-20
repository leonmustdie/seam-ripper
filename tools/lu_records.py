#!/usr/bin/env python3
"""Write replaced records back into a container, both games, and prove it.

Used by the texture and model replacement tools. A replacement record keeps
the size of the record it replaces (a texture of the same size and format, a
mesh with the same vertex and index counts), so nothing else in the
container moves:

  Naughty Bear: lu_chunk_replace.rebuild (relayout, which leaves every
  record in place when no size changes, and the retail LZX recompression for
  compressed containers). The result passes verify_lzx before it is saved.
  Panic in Paradise: naughty_lu.rebuild_luh, raw segments, every record kept
  at its offset. PiP hangs on level load when a record moves or changes
  size (verified in game for scripts and clips), so a size change is refused.

After the rebuild the file is read back: every replaced record must come
back byte for byte (and pass the caller's own decode check), every other
record must be unchanged.
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class RecordError(Exception):
    pass


def game_of(lu):
    return "pip" if getattr(lu, "is_luh", False) else "nb1"


def local_records(lu, h, types):
    """Records named h of one of the given types that hold their own data."""
    return [r for r in lu.records
            if r.hash == h and r.type in types and not r.external]


def rebuild(lu, reps, check=None, allow_resize=False):
    """Container bytes with records replaced -> (bytes, description).
    reps: {record index: new bytes}, each the size of the record it replaces.
    allow_resize (Naughty Bear only): a record may change size; the records
    after it move to their alignment (relayout), as for scripts and clips.
    check(index, bytes) -> problem string or None, run on every replaced
    record as read back from the rebuilt file."""
    from naughty_lu import LuFile, rebuild_luh
    from lu_chunk_replace import rebuild as nb1_rebuild
    name = Path(lu.path).name
    if allow_resize and game_of(lu) == "pip":
        raise RecordError(f"{name}: Panic in Paradise records keep their size")
    for i, data in reps.items():
        r = lu.records[i]
        if len(data) != r.size and not allow_resize:
            raise RecordError(f"{name}: record {r.hash:08x} would change size "
                              f"({r.size:,} -> {len(data):,} bytes); a replacement "
                              f"must keep the size")
    try:
        if game_of(lu) == "pip":
            out = rebuild_luh(lu, reps)
            how = (f"LUH, raw segments; {len(reps)} record(s) rewritten in place, "
                   f"sizes kept")
        else:
            out, how = nb1_rebuild(lu, reps)
    except ValueError as e:
        raise RecordError(f"{name}: {e}")
    fd, tmp = tempfile.mkstemp(suffix=".lu")
    os.close(fd)
    try:
        Path(tmp).write_bytes(out)
        back = LuFile(tmp)
        for i, data in reps.items():
            got = bytes(back.chunk(back.records[i]))
            if got != data:
                raise RecordError(f"{name}: record {i} did not read back identically")
            if back.records[i].offset != lu.records[i].offset and game_of(lu) == "pip":
                raise RecordError(f"{name}: record {i} moved")
            if check:
                prob = check(i, got)
                if prob:
                    raise RecordError(f"{name}: record {i} {prob}")
        others = [r for r in lu.records if r.index not in reps and not r.external]
        for r in others:
            if bytes(back.chunk(back.records[r.index])) != bytes(lu.chunk(r)):
                raise RecordError(f"{name}: record {r.index} changed although it "
                                  f"was not edited")
    finally:
        os.unlink(tmp)
    return out, (f"{how}; read back: {len(reps)} record(s) identical, "
                 f"{len(others)} other record(s) unchanged")


def save(out, data, game, log=print):
    """Save container bytes as out: back up out first when it is an existing
    file (sr_backup), write through a temporary file, and for Naughty Bear
    run the LZX verifier before anything replaces out."""
    out = Path(out)
    if out.exists():
        if not os.access(out, os.W_OK) or not (out.stat().st_mode & stat.S_IWRITE):
            raise RecordError(f"{out} is read-only; clear its read-only attribute "
                              f"or save somewhere else")
        import sr_backup
        sr_backup.backup_before_overwrite(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(data)
    if game == "nb1":                       # PiP writes raw segments: no LZX to check
        import verify_lzx
        try:
            verify_lzx.verify_file(str(tmp))
        except verify_lzx.VerifyError as e:
            tmp.unlink()
            raise RecordError(f"the rebuilt container failed the LZX check: {e}")
    tmp.replace(out)
    log(f"wrote {out} ({out.stat().st_size:,} bytes)")
