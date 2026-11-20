#!/usr/bin/env python3
"""Replace textures (Naughty Bear and Panic in Paradise).

  tex_replace.py list characters_shared_resources.lu [--find 26ca]
      the textures stored in a container: hash, size, format, mip levels

  tex_replace.py export characters_shared_resources.lu --texture 26ca1642 -o OUT [--dds]
      save textures as PNG (or DDS with every mip level) to edit

  tex_replace.py replace characters_shared_resources.lu --texture 26ca1642 --image blue.png
                 [--texture HASH --image FILE ...] [--all-copies]
                 [--patch Mod.srpatch] [-o patched.lu | --out-dir FOLDER]
      put edited pictures back. Saves a .srpatch to share, patched .lu files,
      or both.

The picture must have the texture's width and height (`list` shows them), or
--resize scales it to them. Instead of a file, --image can name a plain fill:
flat-normal (a normal map with no relief, 128 128 255), black, white or clear
(transparent black); used when a new model replaces a character whose other
maps (normal map, masks) were painted for the old model's layout. A
PNG (or any picture Pillow reads) is compressed in the texture's own format
(DXT1, DXT5, ...) and its mip levels are made from it; a DDS of the same
format is taken as it is, mip levels included. The texture keeps its size,
format and level count, so the record keeps its size and nothing else in the
container moves (Panic in Paradise hangs if a record changes size).

A texture is often stored in several containers (Naughty's fur is in
characters_shared_resources, naughtyisland_shared_resources and
mp_naughtybear); --all-copies also replaces every copy in the other
containers of the same folder, otherwise the game may still show the
original where it loads another copy.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lu_texture as T                      # noqa: E402


class ReplaceError(Exception):
    pass


def _hash(s):
    try:
        return int(str(s).lower().removeprefix("0x"), 16)
    except ValueError:
        raise ReplaceError(f"'{s}' is not a texture hash (8 hex digits)")


def textures(lu):
    """[(record, info dict)] for every texture with its own data, in order."""
    out = []
    for r in lu.records:
        if r.type in T.TEX_TYPES and not r.external:
            d = bytes(lu.chunk(r))
            try:
                out.append((r, T.info(d)))
            except T.TextureError as e:
                out.append((r, {"error": str(e)}))
    return out


def other_copies(lu_path, h):
    """Other containers in the same folder that store texture h themselves."""
    from naughty_lu import LuFile
    lu_path = Path(lu_path)
    out = []
    for p in sorted(lu_path.parent.glob("*.lu")):
        if p.resolve() == lu_path.resolve():
            continue
        try:
            lu = LuFile(p)              # reads the record table only
        except (OSError, ValueError):
            continue
        if any(r.hash == h and r.type in T.TEX_TYPES and not r.external
               for r in lu.records):
            out.append(p)
    return out


def cmd_list(a):
    from naughty_lu import LuFile
    lu = LuFile(a.lu)
    rows = textures(lu)
    ext = sum(1 for r in lu.records if r.type in T.TEX_TYPES and r.external)
    find = (a.find or "").lower()
    print(f"{'hash':8}  {'size':>9}  {'format':6}  {'levels':>6}  {'bytes':>10}")
    shown = 0
    for r, t in rows:
        if find and find not in f"{r.hash:08x}":
            continue
        shown += 1
        if "error" in t:
            print(f"{r.hash:08x}  {t['error']}")
            continue
        print(f"{r.hash:08x}  {t['width']:>4}x{t['height']:<4}  {t['format']:6}  "
              f"{t['levels']:>6}  {r.size:>10,}")
    print(f"{shown} texture(s) stored here" + (f"; {ext} more are used from other "
                                              f"containers" if ext else ""))
    return 0


def cmd_export(a):
    from naughty_lu import LuFile
    lu = LuFile(a.lu)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    want = {_hash(x) for x in a.texture.split(",")} if a.texture else None
    n = 0
    for r, t in textures(lu):
        if want is not None and r.hash not in want:
            continue
        if "error" in t:
            print(f"{r.hash:08x}: {t['error']}; skipped")
            continue
        d = bytes(lu.chunk(r))
        if a.dds and t["format"] != "ARGB8":
            p = out / f"{r.hash:08x}.dds"
            p.write_bytes(T.to_dds(d))
        else:
            p = out / f"{r.hash:08x}.png"
            T.level_image(d, 0, t).save(p)
        n += 1
        print(f"{r.hash:08x}  {t['width']}x{t['height']} {t['format']}  -> {p}")
    if want is not None and n < len(want):
        raise ReplaceError(f"{len(want) - n} of the textures asked for are not "
                           f"stored in {Path(a.lu).name}")
    print(f"{n} texture(s) saved")
    return 0


FILLS = {"flat-normal": (128, 128, 255, 255), "black": (0, 0, 0, 255),
         "white": (255, 255, 255, 255), "clear": (0, 0, 0, 0)}


def _texture_size(lu_path, h):
    from naughty_lu import LuFile
    import sr_patch
    lu = LuFile(sr_patch.retail_copy(Path(lu_path)))
    recs = T.texture_records(lu, h)
    if len(recs) != 1:
        raise ReplaceError(f"{Path(lu_path).name} stores {len(recs)} textures named "
                           f"{h:08x} (need exactly one; `list` shows them)")
    t = T.info(bytes(lu.chunk(recs[0])))
    return t["width"], t["height"]


def prepare_pictures(lu_path, pairs, resize=False, work=None):
    """Plain fills (FILLS) made at each texture's size and, with resize,
    pictures scaled to it -> [(hash, picture path)] (made files in work)."""
    from PIL import Image
    import tempfile
    out = []
    for h, p in pairs:
        name = str(p).lower()
        if name in FILLS or resize:
            work = work or tempfile.mkdtemp(prefix="texfill_")
            w, ht = _texture_size(lu_path, h)
            if name in FILLS:
                img = Image.new("RGBA", (w, ht), FILLS[name])
                q = Path(work) / f"{name}_{w}x{ht}.png"
            else:
                if not Path(p).is_file():
                    raise ReplaceError(f"picture not found: {p}")
                img = Image.open(p)
                if img.size == (w, ht):
                    out.append((h, Path(p)))
                    continue
                img = img.convert("RGBA").resize((w, ht), Image.LANCZOS)
                q = Path(work) / f"{Path(p).stem}_{w}x{ht}.png"
            img.save(q)
            out.append((h, q))
        else:
            out.append((h, Path(p)))
    return out


def plan(a):
    """-> {container path: [(hash, picture path)]}, checked against each
    container's own record (size, format)."""
    from naughty_lu import LuFile
    if len(a.texture) != len(a.image):
        raise ReplaceError("give one --image for every --texture")
    pairs = prepare_pictures(a.lu, [(_hash(h), Path(p) if p.lower() not in FILLS else p)
                                    for h, p in zip(a.texture, a.image)],
                             getattr(a, "resize", False))
    for _, p in pairs:
        if not p.is_file():
            raise ReplaceError(f"picture not found: {p}")
    target = Path(a.lu)
    jobs = {target: list(pairs)}
    if a.all_copies:
        for h, p in pairs:
            for other in other_copies(target, h):
                jobs.setdefault(other, []).append((h, p))
    import sr_patch
    for path, items in jobs.items():
        lu = LuFile(sr_patch.retail_copy(path))     # the original, if path is modded
        for h, p in items:
            recs = T.texture_records(lu, h)
            if len(recs) != 1:
                raise ReplaceError(f"{path.name} stores {len(recs)} textures named "
                                   f"{h:08x} (need exactly one; `list` shows them)")
            try:
                T.encode_source(bytes(lu.chunk(recs[0])), str(p))
            except (T.TextureError, OSError, ValueError) as e:
                raise ReplaceError(f"{p.name} into {path.name} {h:08x}: {e}")
    return jobs


def cmd_replace(a):
    import lu_records
    import sr_patch
    if not a.patch and not a.out and not a.out_dir:
        raise ReplaceError("say where to save: --patch for a .srpatch, -o or "
                           "--out-dir for patched .lu files")
    jobs = plan(a)
    if a.out and len(jobs) > 1:
        raise ReplaceError(f"{len(jobs)} containers change; use --out-dir")
    for path, items in jobs.items():
        print(f"{path.name}: " + ", ".join(f"{h:08x} <- {p.name}" for h, p in items))
    if a.patch:
        sr_patch.make_patch(
            a.patch, [{"container": str(p),
                       "scripts": [], "strings": None,
                       "textures": [(f"{h:08x}", str(src)) for h, src in items]}
                      for p, items in jobs.items()],
            name=a.name or Path(a.patch).stem, author=a.author or "",
            description=a.description or
            "replaced texture(s) " + ", ".join(sorted({f"{h:08x}" for items in
                                                         jobs.values() for h, _ in items})),
            version=a.version or "1")
    if a.out or a.out_dir:
        for path, items in jobs.items():
            src = sr_patch.retail_copy(path)
            if src != path:
                print(f"{path.name} has been modded; building from its retail backup")
            try:
                data, lines = T.replace_in_container(
                    src, [(h, str(p), None) for h, p in items])
            except T.TextureError as e:
                raise ReplaceError(str(e))
            for ln in lines:
                print(ln)
            out = Path(a.out) if a.out else Path(a.out_dir) / path.name
            from naughty_lu import LuFile
            game = lu_records.game_of(LuFile(src))
            try:
                lu_records.save(out, data, game)
            except lu_records.RecordError as e:
                raise ReplaceError(str(e))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list the textures stored in a container")
    pl.add_argument("lu")
    pl.add_argument("--find", help="only hashes containing this")
    pe = sub.add_parser("export", help="save textures as PNG or DDS to edit")
    pe.add_argument("lu")
    pe.add_argument("--texture", help="hash(es), comma-separated (default: all)")
    pe.add_argument("-o", "--out", required=True, help="folder to save into")
    pe.add_argument("--dds", action="store_true",
                    help="save DDS with every mip level instead of PNG")
    pr = sub.add_parser("replace", help="put edited pictures back")
    pr.add_argument("lu", help="the container that holds the texture(s)")
    pr.add_argument("--texture", action="append", default=[], required=True,
                    help="texture hash; repeat with one --image each")
    pr.add_argument("--image", action="append", default=[], required=True,
                    help="the new picture (PNG, DDS, ...), same width and height (or "
                         "--resize); or a fill: flat-normal, black, white, clear")
    pr.add_argument("--resize", action="store_true",
                    help="scale each picture to its texture's width and height")
    pr.add_argument("--all-copies", action="store_true",
                    help="also replace the copies in the other containers of the folder")
    pr.add_argument("--patch", help="save a .srpatch here")
    pr.add_argument("-o", "--out", help="save the patched .lu here (one container)")
    pr.add_argument("--out-dir", help="save every patched .lu into this folder")
    pr.add_argument("--name", help="patch name")
    pr.add_argument("--author")
    pr.add_argument("--description")
    pr.add_argument("--version")
    a = ap.parse_args()
    try:
        rc = {"list": cmd_list, "export": cmd_export, "replace": cmd_replace}[a.cmd](a)
    except ReplaceError as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 1
    except Exception as e:                  # sr_patch.PatchError and the like
        if type(e).__name__ in ("PatchError", "TextureError", "RecordError"):
            print(f"error: {e}", file=sys.stderr)
            rc = 1
        else:
            raise
    sys.exit(rc)


if __name__ == "__main__":
    main()
