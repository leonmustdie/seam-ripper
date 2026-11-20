#!/usr/bin/env python3
"""Edit models (Naughty Bear and Panic in Paradise): move vertices in Blender
and put the mesh back.

  mesh_replace.py list naughtybear.lu [--find 7432]
      the meshes stored in a container: hash, parts, vertices, kind

  mesh_replace.py export naughtybear.lu --mesh 743299d0 -o naughty.glb
      an editable GLB: one object per part (sub00, sub01, ...), textured
      where the container (or its shared resource file) holds the picture

  mesh_replace.py export naughtybear.lu --mesh 743299d0 --rigged -o naughty_rig.glb
      the same with the skeleton: one joint per bone, named b000 ... b116 (the
      number is the skeleton bone), skinned parts weighted to them. Start a
      new model from this file.

  mesh_replace.py import naughtybear.lu --mesh 743299d0 --glb new_model.glb
                  [--collapse 1,2] [--primitive auto|list|strip] [--in-place]
                  [--all-copies] [--patch Mod.srpatch] [-o patched.lu | --out-dir FOLDER]
      put a NEW model in: any number of vertices and triangles. Each object
      named subNN replaces that part (its textures, palette and material
      stay); --collapse hides parts (nothing drawn). Naughty Bear: the mesh
      record grows. Panic in Paradise: the record keeps its size, so a part
      that does not fit is refused with the budget.

  mesh_replace.py replace naughtybear.lu --mesh 743299d0 --glb edited.glb
                  [--glb-normals] [--all-copies]
                  [--patch Mod.srpatch] [-o patched.lu | --out-dir FOLDER]
      put the edited vertices back. Saves a .srpatch to share, patched .lu
      files, or both.

What can change: where vertices are (and their texture coordinates). Not the
number of vertices or triangles, the skin weights or the bones: those stay as
the game ships them, so the model keeps its size in the file and skinning
cannot break. Move, scale, sculpt and smooth freely; do not add, delete,
merge or split vertices.

Blender: File > Import > glTF, edit, then File > Export > glTF 2.0 (.glb)
with Include > Data > Attributes ticked. That keeps each vertex's id
(_SR_VID), so vertices map back even when Blender reorders them. Leave the
object names (sub00 ...) as they are.

Normals: by default each shipped normal turns with the surface under it, so
the game's smooth and hard edges stay as made; --glb-normals takes the
normals from the GLB instead. Positions are as stored: skinned parts in
model space (the bind pose), rigid parts in the space of their bone. The
shadow-volume copy of a character is not edited.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lu_mesh as M                         # noqa: E402


class ReplaceError(Exception):
    pass


def _hash(s):
    try:
        return int(str(s).lower().removeprefix("0x"), 16)
    except ValueError:
        raise ReplaceError(f"'{s}' is not a mesh hash (8 hex digits)")


def other_copies(lu_path, h):
    from naughty_lu import LuFile
    lu_path = Path(lu_path)
    out = []
    for p in sorted(lu_path.parent.glob("*.lu")):
        if p.resolve() == lu_path.resolve():
            continue
        try:
            lu = LuFile(p)
        except (OSError, ValueError):
            continue
        if any(r.hash == h and r.type in M.MESH_TYPES and not r.external
               for r in lu.records):
            out.append(p)
    return out


def cmd_list(a):
    from naughty_lu import LuFile
    lu = LuFile(a.lu)
    find = (a.find or "").lower()
    print(f"{'hash':8}  {'parts':>5}  {'vertices':>8}  {'bytes':>10}  kinds")
    n = 0
    for r in lu.records:
        if r.type not in M.MESH_TYPES or r.external:
            continue
        if find and find not in f"{r.hash:08x}":
            continue
        d = bytes(lu.chunk(r))
        if not M.is_mesh(d):            # PiP: 52-byte stubs share the type id
            continue
        try:
            subs = [s for s in M.submodels(d) if M.editable(s)]
        except M.MeshError as e:
            print(f"{r.hash:08x}  ({e})")
            continue
        if not subs:
            continue
        kinds = sorted({s["kind"] for s in subs})
        print(f"{r.hash:08x}  {len(subs):>5}  {sum(s['verts'] for s in subs):>8,}  "
              f"{r.size:>10,}  {', '.join(kinds)}")
        n += 1
    print(f"{n} mesh(es) stored here")
    return 0


def _record(lu, h, what):
    recs = M.mesh_records(lu, h)
    if len(recs) != 1:
        raise ReplaceError(f"{Path(lu.path).name} stores {len(recs)} meshes named "
                           f"{h:08x} (need exactly one; `list` shows them)")
    return bytes(lu.chunk(recs[0]))


def cmd_export(a):
    from naughty_lu import LuFile
    import sr_patch
    src = sr_patch.retail_copy(Path(a.lu))
    lu = LuFile(src)
    h = _hash(a.mesh)
    d = _record(lu, h, "mesh")
    imgs = {} if a.no_textures else M.texture_pngs(lu, d)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if a.rigged:
        import mesh_import as MI
        try:
            out.write_bytes(MI.to_rigged_glb(d, MI.skeleton_for(lu, h), imgs,
                                             name=f"{h:08x}"))
        except M.MeshError as e:
            raise ReplaceError(str(e))
        IB = MI.inverse_binds(d)
        print(f"  skeleton: {len(IB)} bones, joints b000 ... b{len(IB) - 1:03d}")
    else:
        out.write_bytes(M.to_glb(d, imgs, name=f"{h:08x}"))
    subs = [s for s in M.submodels(d) if M.editable(s)]
    for s in subs:
        extra = ""
        if a.rigged:
            import mesh_import as MI
            if MI.scaled_part(d, s):
                extra = " (left out: it hangs on a bone with a rest scale Blender cannot hold)"
            elif MI.influences(s):
                extra = f", palette of {len(MI.palette(d, s)['bones'])} bones"
        print(f"  sub{s['n']:02d}: {s['kind']}, {s['verts']:,} vertices"
              + (", textured" if s["n"] in imgs else "") + extra)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


def plan(a):
    """-> ({container path: neutral edit}, mesh hash). The edit is read from
    the GLB against the given container's original record; other copies
    (--all-copies) take the same edit only if their record is identical."""
    from naughty_lu import LuFile
    import sr_patch
    h = _hash(a.mesh)
    glb = Path(a.glb)
    if not glb.is_file():
        raise ReplaceError(f"GLB not found: {glb}")
    target = Path(a.lu)
    lu = LuFile(sr_patch.retail_copy(target))
    d = _record(lu, h, "mesh")
    try:
        edits, notes = M.edits_from_glb(d, glb.read_bytes(),
                                        "glb" if a.glb_normals else "carry")
    except M.MeshError as e:
        raise ReplaceError(f"{glb.name}: {e}")
    for x in notes:
        print(f"  {x}")
    if not edits:
        raise ReplaceError(f"{glb.name} changes nothing in mesh {h:08x}")
    obj = M.edits_to_obj(d, edits)
    jobs = {target: obj}
    if a.all_copies:
        sha = M.sha256(d)
        for other in other_copies(target, h):
            od = _record(LuFile(sr_patch.retail_copy(other)), h, "mesh")
            if M.sha256(od) == sha:
                jobs[other] = obj
            else:
                print(f"  {other.name} holds a different version of mesh {h:08x}; "
                      f"left as it is")
    return jobs, h


def _parts_arg(s, subs):
    out = []
    for x in (s or "").replace(" ", "").split(","):
        if not x:
            continue
        x = x.lower().removeprefix("sub")
        try:
            n = int(x)
        except ValueError:
            raise ReplaceError(f"'{x}' is not a part number (0, 1, sub02, ...)")
        if not 0 <= n < len(subs):
            raise ReplaceError(f"this mesh has no part {n}")
        out.append(n)
    return out


def plan_import(a):
    """-> ({container path: neutral import}, mesh hash). The GLB is read
    against the given container's original record and built once, so a part
    that does not fit is refused before anything is saved."""
    from naughty_lu import LuFile
    import sr_patch
    import mesh_import as MI
    h = _hash(a.mesh)
    target = Path(a.lu)
    lu = LuFile(sr_patch.retail_copy(target))
    d = _record(lu, h, "mesh")
    subs = M.submodels(d)
    parts = {}
    if a.glb:
        glb = Path(a.glb)
        if not glb.is_file():
            raise ReplaceError(f"GLB not found: {glb}")
        notes = []
        try:
            parts = MI.parts_from_glb(d, glb.read_bytes(), notes)
        except M.MeshError as e:
            raise ReplaceError(f"{glb.name}: {e}")
        for x in notes:
            print(f"  {x}")
    for n in _parts_arg(a.collapse, subs):
        if n in parts:
            raise ReplaceError(f"part {n} is both in the GLB and collapsed")
        parts[n] = "collapse"
    if not parts:
        raise ReplaceError("nothing to import: give --glb and/or --collapse")
    obj = MI.parts_to_obj(parts, source=Path(a.glb).name if a.glb else "")
    obj["options"] = {"primitive": a.primitive, "in_place": bool(a.in_place)}
    game = "pip" if getattr(lu, "is_luh", False) else "nb1"
    try:
        MI.build_record(d, MI.obj_to_parts(obj), game, a.primitive,
                        True if a.in_place else None, print)
    except M.MeshError as e:
        raise ReplaceError(str(e))
    jobs = {target: obj}
    if a.all_copies:
        sha = M.sha256(d)
        for other in other_copies(target, h):
            od = _record(LuFile(sr_patch.retail_copy(other)), h, "mesh")
            if M.sha256(od) == sha:
                jobs[other] = obj
            else:
                print(f"  {other.name} holds a different version of mesh {h:08x}; "
                      f"left as it is")
    return jobs, h


def cmd_import(a):
    import lu_records
    import sr_patch
    import mesh_import as MI
    from naughty_lu import LuFile
    if not a.patch and not a.out and not a.out_dir:
        raise ReplaceError("say where to save: --patch for a .srpatch, -o or "
                           "--out-dir for patched .lu files")
    jobs, h = plan_import(a)
    if a.out and len(jobs) > 1:
        raise ReplaceError(f"{len(jobs)} containers change; use --out-dir")
    print(f"mesh {h:08x} in: " + ", ".join(p.name for p in jobs))
    if a.patch:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="modelimport_") as tmp:
            ep = Path(tmp) / f"model_{h:08x}.json"
            ep.write_text(json.dumps(next(iter(jobs.values())), separators=(",", ":")),
                          encoding="utf-8")
            sr_patch.make_patch(
                a.patch, [{"container": str(p), "scripts": [], "strings": None,
                           "models": [(f"{h:08x}", str(ep))]} for p in jobs],
                name=a.name or Path(a.patch).stem, author=a.author or "",
                description=a.description or f"new model in mesh {h:08x}",
                version=a.version or "1")
    if a.out or a.out_dir:
        for path, obj in jobs.items():
            src = sr_patch.retail_copy(path)
            if src != path:
                print(f"{path.name} has been modded; building from its retail backup")
            try:
                data, lines = MI.import_in_container(src, [(h, obj, None)])
            except M.MeshError as e:
                raise ReplaceError(str(e))
            for ln in lines:
                print(ln)
            out = Path(a.out) if a.out else Path(a.out_dir) / path.name
            try:
                lu_records.save(out, data, lu_records.game_of(LuFile(src)))
            except lu_records.RecordError as e:
                raise ReplaceError(str(e))
    return 0


def cmd_replace(a):
    import lu_records
    import sr_patch
    from naughty_lu import LuFile
    if not a.patch and not a.out and not a.out_dir:
        raise ReplaceError("say where to save: --patch for a .srpatch, -o or "
                           "--out-dir for patched .lu files")
    jobs, h = plan(a)
    if a.out and len(jobs) > 1:
        raise ReplaceError(f"{len(jobs)} containers change; use --out-dir")
    print(f"mesh {h:08x} in: " + ", ".join(p.name for p in jobs))
    if a.patch:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="meshedit_") as tmp:
            ep = Path(tmp) / f"mesh_{h:08x}.json"
            ep.write_text(json.dumps(next(iter(jobs.values())), separators=(",", ":")),
                          encoding="utf-8")
            sr_patch.make_patch(
                a.patch, [{"container": str(p), "scripts": [], "strings": None,
                           "meshes": [(f"{h:08x}", str(ep))]} for p in jobs],
                name=a.name or Path(a.patch).stem, author=a.author or "",
                description=a.description or f"edited mesh {h:08x}",
                version=a.version or "1")
    if a.out or a.out_dir:
        for path, obj in jobs.items():
            src = sr_patch.retail_copy(path)
            if src != path:
                print(f"{path.name} has been modded; building from its retail backup")
            try:
                data, lines = M.replace_in_container(src, [(h, obj, None)])
            except M.MeshError as e:
                raise ReplaceError(str(e))
            for ln in lines:
                print(ln)
            out = Path(a.out) if a.out else Path(a.out_dir) / path.name
            try:
                lu_records.save(out, data, lu_records.game_of(LuFile(src)))
            except lu_records.RecordError as e:
                raise ReplaceError(str(e))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list the meshes stored in a container")
    pl.add_argument("lu")
    pl.add_argument("--find", help="only hashes containing this")
    pe = sub.add_parser("export", help="save a mesh as an editable GLB")
    pe.add_argument("lu")
    pe.add_argument("--mesh", required=True, help="mesh hash")
    pe.add_argument("-o", "--out", required=True, help=".glb to write")
    pe.add_argument("--no-textures", action="store_true", help="leave the pictures out")
    pe.add_argument("--rigged", action="store_true",
                    help="with the skeleton (joints b000 ...), to make a new model on")
    pi = sub.add_parser("import", help="put a new model in (any vertex count)")
    pi.add_argument("lu", help="the container that holds the mesh")
    pi.add_argument("--mesh", required=True, help="mesh hash")
    pi.add_argument("--glb", help="the new model: a GLB skinned to the rigged export's "
                                  "joints, one object per part (sub00, ...)")
    pi.add_argument("--collapse", help="parts to hide, e.g. 1,2 (nothing drawn)")
    pi.add_argument("--primitive", choices=("auto", "list", "strip"), default="auto",
                    help="index buffer form (auto: a list, a strip where a list "
                         "does not fit)")
    pi.add_argument("--in-place", action="store_true",
                    help="Naughty Bear: keep the record's size like Panic in Paradise "
                         "(refused if it does not fit)")
    pi.add_argument("--all-copies", action="store_true",
                    help="also import into identical copies in the other containers")
    pi.add_argument("--patch", help="save a .srpatch here")
    pi.add_argument("-o", "--out", help="save the patched .lu here (one container)")
    pi.add_argument("--out-dir", help="save every patched .lu into this folder")
    pi.add_argument("--name", help="patch name")
    pi.add_argument("--author")
    pi.add_argument("--description")
    pi.add_argument("--version")
    pr = sub.add_parser("replace", help="put an edited mesh back")
    pr.add_argument("lu", help="the container that holds the mesh")
    pr.add_argument("--mesh", required=True, help="mesh hash")
    pr.add_argument("--glb", required=True, help="the edited GLB (from `export`)")
    pr.add_argument("--glb-normals", action="store_true",
                    help="take the normals from the GLB (default: turn the shipped ones)")
    pr.add_argument("--all-copies", action="store_true",
                    help="also edit identical copies in the other containers of the folder")
    pr.add_argument("--patch", help="save a .srpatch here")
    pr.add_argument("-o", "--out", help="save the patched .lu here (one container)")
    pr.add_argument("--out-dir", help="save every patched .lu into this folder")
    pr.add_argument("--name", help="patch name")
    pr.add_argument("--author")
    pr.add_argument("--description")
    pr.add_argument("--version")
    a = ap.parse_args()
    try:
        rc = {"list": cmd_list, "export": cmd_export, "replace": cmd_replace,
              "import": cmd_import}[a.cmd](a)
    except ReplaceError as e:
        print(f"error: {e}", file=sys.stderr)
        rc = 1
    except Exception as e:
        if type(e).__name__ in ("PatchError", "MeshError", "RecordError"):
            print(f"error: {e}", file=sys.stderr)
            rc = 1
        else:
            raise
    sys.exit(rc)


if __name__ == "__main__":
    main()
