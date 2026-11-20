#!/usr/bin/env python3
"""Texture and model write-back: the texture codec (lu_texture), the mesh
vertex editor (lu_mesh), the same-size record writer (lu_records), the two
tools (tex_replace, mesh_replace), .srpatch "texture" and "mesh" edits, and
their GUI forms.

The first groups build records from scratch and need only numpy and Pillow.
The rest read your own game files (SR_TEST_NB1_DIR, SR_TEST_PIP_DIR, see
game_paths.py) and skip without them. NB1 uses witchhat.lu and mp_witchhat.lu
(31 KB each, the same three textures and hat mesh in both, so --all-copies
has a second copy to find); PiP uses vibbadge_acc.lu (15 KB, three textures
and one mesh).
"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    from PIL import Image
    HAVE_LIBS = True
except ImportError:                                     # pragma: no cover
    HAVE_LIBS = False

try:
    import PySide6                                      # noqa: F401
    HAVE_QT = True
except ImportError:                                     # pragma: no cover
    HAVE_QT = False

import game_paths

NB1 = game_paths.NB1_DIR
PIP = game_paths.PIP_DIR
HAVE_NB1 = HAVE_LIBS and (NB1 / "witchhat.lu").exists() and (NB1 / "mp_witchhat.lu").exists()
HAVE_PIP = HAVE_LIBS and (PIP / "vibbadge_acc.lu").exists()
HAVE_LZXV = any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify"))

if HAVE_LIBS:
    import lu_texture as T
    import lu_mesh as M
    import lu_records

# witchhat.lu / mp_witchhat.lu: textures (all 128x128 or 64x64 DXT1) and the hat
W_TEX, W_TEX2, W_MESH = 0x8E93A45C, 0x0BEDF4C9, 0x192A15FC
# vibbadge_acc.lu
V_TEX, V_MESH = 0xAAD25F7F, 0x4E9CD7DF


def texture_record(w, h, levels, code=0x12, endian=1):
    """A blank texture record with the header the games use."""
    d = bytearray(T.HEADER)
    d[:4] = b"\x34\x20\x00\x07"
    struct.pack_into(">2I", d, 8, w, h)
    struct.pack_into(">2I", d, 0x24, levels, 0x1A200100 | (endian << 6) | code)
    struct.pack_into(">2I", d, 0x38, 0x1000, 0)
    _, total = T.layout(T.info(bytes(d)))
    struct.pack_into(">I", d, 0x3C, total)
    return bytes(d) + bytes(0x1000 - T.HEADER + total)


def picture(w, h, seed=1, checker=True):
    """Colour ramps, plus an 8-pixel checker in blue (seed shifts it).
    checker=False: one diagonal ramp whose colours lie on a line in RGB, which
    a DXT1 block (four colours on a line) holds at every mip level; the ramps
    above spread over two colour axes and lose a lot in 4x4 and 2x2 levels."""
    y, x = np.mgrid[0:h, 0:w]
    if not checker:
        t = (x + y) / max(w + h - 2, 1)
        r, g, b = t * 255, 20 + t * 200, 255 - t * 255
    else:
        r = (x * 255 // max(w - 1, 1))
        g = (y * 255 // max(h - 1, 1))
        b = (((x // 8 + y // 8) + seed) % 2) * 200
    a = np.full_like(r, 255)
    return Image.fromarray(np.dstack([r, g, b, a]).astype(np.uint8), "RGBA")


def uncovered(d):
    """Pixel-data offsets (absolute) that no mip level uses (tile padding)."""
    t = T.info(d)
    seen = np.zeros(t["data_size"], bool)
    for lv in range(t["levels"]):
        a = T._block_addresses(t, lv).ravel()
        seen[(a[:, None] + np.arange(t["bpb"])).ravel()] = True
    return np.flatnonzero(~seen) + t["data_offset"]


def write_glb(g, blob):
    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob = bytes(blob) + bytes(-len(blob) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob),
                                                                      0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def accessor_slot(g, i):
    """(byte offset in the binary chunk, numpy dtype, components, count)."""
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    assert "byteStride" not in bv
    dt = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[a["componentType"]]
    k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    return bv.get("byteOffset", 0) + a.get("byteOffset", 0), dt, k, a["count"]


def glb_edit(data, fn):
    """Apply fn(g, blob (bytearray)) to a GLB and return the new file."""
    g, blob = M._read_glb(data)
    blob = bytearray(blob)
    fn(g, blob)
    return write_glb(g, blob)


def scale_part(data, part, s, about=None):
    """Scale every vertex of mesh node subNN by s (in place in the GLB)."""
    def fn(g, blob):
        for mesh in g["meshes"]:
            if mesh["name"] != f"sub{part:02d}":
                continue
            for prim in mesh["primitives"]:
                o, dt, k, n = accessor_slot(g, prim["attributes"]["POSITION"])
                P = np.frombuffer(bytes(blob[o:o + 4 * k * n]), dt).reshape(n, k)
                c = P.mean(0) if about is None else about
                Q = (c + (P - c) * s).astype(dt)
                blob[o:o + Q.nbytes] = Q.tobytes()
                a = g["accessors"][prim["attributes"]["POSITION"]]
                a["min"], a["max"] = Q.min(0).tolist(), Q.max(0).tolist()
    return glb_edit(data, fn)


def reverse_part(data, part):
    """Store subNN's vertices in reverse order (indices remapped), the way an
    editor that reorders vertices would hand them back."""
    def fn(g, blob):
        for mesh in g["meshes"]:
            if mesh["name"] != f"sub{part:02d}":
                continue
            for prim in mesh["primitives"]:
                n = None
                for acc in prim["attributes"].values():
                    o, dt, k, n = accessor_slot(g, acc)
                    A = np.frombuffer(bytes(blob[o:o + 4 * k * n]), dt).reshape(n, k)
                    blob[o:o + A.nbytes] = A[::-1].tobytes()
                o, dt, k, c = accessor_slot(g, prim["indices"])
                I = np.frombuffer(bytes(blob[o:o + np.dtype(dt).itemsize * c]), dt)
                blob[o:o + I.nbytes] = (n - 1 - I.astype(np.int64)).astype(dt).tobytes()
    return glb_edit(data, fn)


def set_vid(data, part, at, value):
    def fn(g, blob):
        mesh = next(m for m in g["meshes"] if m["name"] == f"sub{part:02d}")
        o, dt, k, n = accessor_slot(g, mesh["primitives"][0]["attributes"]["_SR_VID"])
        struct.pack_into(dt[0] + dt[1], blob, o + 4 * at, value)
    return glb_edit(data, fn)


def run(script, *args):
    return subprocess.run([sys.executable, str(TOOLS / script), *map(str, args)],
                          capture_output=True, text=True)


# ======================================================================== codec
@unittest.skipUnless(HAVE_LIBS, "numpy and Pillow not installed")
class TextureCodec(unittest.TestCase):
    def test_header_reads_width_first(self):
        d = texture_record(128, 32, 6)
        t = T.info(d)
        self.assertEqual((t["width"], t["height"], t["format"]), (128, 32, "DXT1"))

    def test_encoded_picture_decodes_back(self):
        for w, h, lv, code in ((64, 64, 7, 0x12), (128, 32, 6, 0x12), (64, 64, 7, 0x14),
                               (16, 16, 5, 0x06)):
            with self.subTest(w=w, h=h, code=code):
                d = texture_record(w, h, lv, code)
                img = picture(w, h)
                new = T.encode_image(d, img)
                self.assertEqual(len(new), len(d))
                got = np.asarray(T.level_image(new, 0), np.int16)
                self.assertEqual(got.shape, (h, w, 4))
                err = np.abs(got - np.asarray(img, np.int16)).mean()
                self.assertLess(err, 6 if code != 0x06 else 0.01)
                rebuilt, probs = T.roundtrip(new)
                self.assertEqual(probs, [])
                self.assertEqual(rebuilt, new)

    def test_cached_encode_matches_a_fresh_one(self):
        # one patch putting a picture into the same texture in several
        # containers encodes it once (sr_patch apply); every copy must come
        # out as a fresh encode would, keeping its own padding bytes
        d = texture_record(64, 64, 7, 0x12)
        other = bytearray(d)
        other[T.info(d)["data_offset"]:] = b"Z" * T.info(d)["data_size"]
        src = ("p.png", _png(picture(64, 64)))
        tmp = Path(tempfile.mkdtemp(prefix="srtexcache_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for rec in (d, bytes(other)):
            self.assertEqual(T.encode_source(rec, src, cache=tmp), T.encode_source(rec, src))
        self.assertEqual(len(list(tmp.glob("*.bin"))), 1)
        self.assertEqual(list(tmp.glob("*.lock")), [])

    def test_mips_are_the_picture_scaled_down(self):
        # levels of 16 px and up (below that one DXT block spans the whole
        # ramp and four shades are all it holds); control: a mip chain made
        # from the mirrored picture must score far worse
        img = picture(128, 128, checker=False)
        d = T.encode_image(texture_record(128, 128, 8), img)
        for lv in range(1, 4):
            self.assertLess(T.mip_error(d, lv), 5, f"level {lv}")
        flip = T.encode_image(d, img.transpose(Image.FLIP_LEFT_RIGHT))
        bad = T.put_levels(d, {lv: T.level_blocks(flip, lv) for lv in range(1, 8)})
        for lv in range(1, 4):
            self.assertGreater(T.mip_error(bad, lv), 4 * T.mip_error(d, lv), f"level {lv}")

    def test_dds_export_imports_byte_for_byte(self):
        d = T.encode_image(texture_record(64, 32, 6, 0x14), picture(64, 32))
        self.assertEqual(T.encode_dds(d, T.to_dds(d)), d)

    def test_padding_byte_is_caught(self):
        d = T.encode_image(texture_record(64, 64, 7), picture(64, 64))
        pad = uncovered(d)
        self.assertTrue(len(pad), "a 64x64 DXT1 texture has tile padding")
        bad = bytearray(d)
        bad[int(pad[len(pad) // 2])] ^= 0x5A
        _, probs = T.roundtrip(bytes(bad))
        self.assertTrue(any("differ" in p for p in probs), probs)

    def test_wrong_header_is_caught(self):
        d = bytearray(T.encode_image(texture_record(64, 64, 7), picture(64, 64)))
        struct.pack_into(">I", d, 8, 128)                   # claim twice the width
        _, probs = T.roundtrip(bytes(d))
        self.assertTrue(probs)

    def test_wrong_size_picture_is_refused(self):
        d = texture_record(64, 64, 7)
        with self.assertRaises(T.TextureError):
            T.encode_image(d, picture(32, 64))

    def test_same_size_rule(self):
        class R:
            hash, size, external, index = 1, 10, False, 0

        class L:
            path, records, is_luh = "x.lu", [R()], True
        with self.assertRaises(lu_records.RecordError):
            lu_records.rebuild(L(), {0: bytes(11)})


# ======================================================================= NB1
@unittest.skipUnless(HAVE_NB1, "needs numpy, Pillow and your NB1 files (SR_TEST_NB1_DIR)")
class Nb1Textures(unittest.TestCase):
    def setUp(self):
        from naughty_lu import LuFile
        self.lu = LuFile(NB1 / "witchhat.lu")
        self.tmp = Path(tempfile.mkdtemp(prefix="srtex_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def rec(self, h):
        return bytes(self.lu.chunk(T.texture_records(self.lu, h)[0]))

    def test_retail_round_trip(self):
        for r in self.lu.records:
            if r.type in T.TEX_TYPES and not r.external:
                d = bytes(self.lu.chunk(r))
                rebuilt, probs = T.roundtrip(d)
                self.assertEqual(probs, [], f"{r.hash:08x}")
                self.assertEqual(rebuilt, d)
                self.assertLess(float(np.median([T.mip_error(d, lv)
                                                 for lv in range(1, T.info(d)["levels"])])),
                                12, f"{r.hash:08x} mips do not look like the base")

    def test_replace_in_container(self):
        d = self.rec(W_TEX)
        t = T.info(d)
        pic = picture(t["width"], t["height"])
        data, log = T.replace_in_container(NB1 / "witchhat.lu", [(W_TEX, ("p.png", _png(pic)),
                                                                  T.sha256(d))])
        p = self.tmp / "witchhat.lu"
        p.write_bytes(data)
        from naughty_lu import LuFile
        back = LuFile(p)
        new = bytes(back.chunk(T.texture_records(back, W_TEX)[0]))
        self.assertEqual(len(new), len(d))
        err = np.abs(np.asarray(T.level_image(new), np.int16) - np.asarray(pic, np.int16)).mean()
        self.assertLess(err, 6)
        self.assertEqual(bytes(back.chunk(T.texture_records(back, W_TEX2)[0])), self.rec(W_TEX2))

    def test_patch_refuses_another_version(self):
        with self.assertRaises(T.TextureError):
            T.replace_in_container(NB1 / "witchhat.lu",
                                   [(W_TEX, ("p.png", _png(picture(128, 128))), "0" * 64)])

    def test_list_and_export(self):
        r = run("tex_replace.py", "list", NB1 / "witchhat.lu")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("8e93a45c", r.stdout)
        self.assertIn("DXT1", r.stdout)
        r = run("tex_replace.py", "export", NB1 / "witchhat.lu", "--texture", "8e93a45c",
                "-o", self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        with Image.open(self.tmp / "8e93a45c.png") as im:
            self.assertEqual(im.size, (128, 128))

    @unittest.skipUnless(HAVE_LZXV, "needs lzxverify")
    def test_patch_and_lu_agree_on_every_copy(self):
        game = self.tmp / "game"
        game.mkdir()
        for n in ("witchhat.lu", "mp_witchhat.lu"):
            shutil.copy2(NB1 / n, game / n)
        pic = self.tmp / "hat.png"
        picture(128, 128, seed=3).save(pic)
        patch, out = self.tmp / "Hat.srpatch", self.tmp / "out"
        r = run("tex_replace.py", "replace", game / "witchhat.lu", "--texture", "8e93a45c",
                "--image", pic, "--all-copies", "--patch", patch, "--out-dir", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.glob("*.lu")),
                         ["mp_witchhat.lu", "witchhat.lu"])
        info = run("sr_patch.py", "info", patch)
        self.assertIn("texture 0x8e93a45c replaced (128x128 DXT1)", info.stdout)
        import zipfile
        with zipfile.ZipFile(patch) as z:
            man = json.loads(z.read("manifest.json"))
            self.assertEqual(man["format_version"], 5)
            self.assertFalse([n for n in z.namelist() if n.endswith(".lu")],
                             "a patch carries the picture, never game files")
        applied = self.tmp / "applied"
        r = run("sr_patch.py", "apply", patch, game, "-o", applied)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in ("witchhat.lu", "mp_witchhat.lu"):
            self.assertEqual((applied / n).read_bytes(), (out / n).read_bytes(), n)
            self.assertEqual((game / n).read_bytes(), (NB1 / n).read_bytes(), "game untouched")


@unittest.skipUnless(HAVE_NB1, "needs numpy, Pillow and your NB1 files (SR_TEST_NB1_DIR)")
class Nb1Meshes(unittest.TestCase):
    def setUp(self):
        from naughty_lu import LuFile
        self.lu = LuFile(NB1 / "witchhat.lu")
        self.d = bytes(self.lu.chunk(M.mesh_records(self.lu, W_MESH)[0]))
        self.tmp = Path(tempfile.mkdtemp(prefix="srmesh_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_round_trip(self):
        self.assertEqual(M.roundtrip(self.d), [])

    def test_sphere_holds_every_vertex(self):
        for sm in M.submodels(self.d):
            if M.editable(sm):
                P = M.read_column(self.d, sm, M.U_POS).astype(np.float64)
                c = M.sphere(self.d, sm)
                self.assertLessEqual(np.linalg.norm(P - c[:3], axis=1).max(), c[3] * 1.000001)

    def test_scaled_glb_writes_back_the_same_size(self):
        glb = scale_part(M.to_glb(self.d), 0, 1.5)
        new, _ = M.encode_glb(self.d, glb)
        self.assertEqual(len(new), len(self.d))
        sm0 = M.submodels(self.d)[0]
        sm1 = M.submodels(new)[0]
        P0 = M.read_column(self.d, sm0, M.U_POS).astype(np.float64)
        P1 = M.read_column(new, sm1, M.U_POS).astype(np.float64)
        c = P0.mean(0)
        self.assertLess(np.abs(P1 - (c + (P0 - c) * 1.5)).max(), 1e-5)
        self.assertGreater(M.sphere(new, sm1)[3], M.sphere(self.d, sm0)[3])
        self.assertEqual(M.triangles(new, sm1).tolist(), M.triangles(self.d, sm0).tolist())

    def test_reordered_vertices_map_back_by_id(self):
        glb = scale_part(M.to_glb(self.d), 0, 1.2)
        self.assertEqual(M.encode_glb(self.d, reverse_part(glb, 0))[0], M.encode_glb(self.d, glb)[0])

    def test_unedited_glb_changes_nothing(self):
        edits, _ = M.edits_from_glb(self.d, M.to_glb(self.d))
        self.assertEqual(edits, {})

    def test_missing_or_new_vertices_are_refused(self):
        glb = M.to_glb(self.d)
        with self.assertRaises(M.MeshError):
            M.edits_from_glb(self.d, set_vid(glb, 0, 0, 1.0))      # vertex 0 gone
        with self.assertRaises(M.MeshError):
            M.edits_from_glb(self.d, set_vid(glb, 0, 0, 99999.0))  # a new vertex

    def test_neutral_edit_file_rebuilds_the_record(self):
        edits, _ = M.edits_from_glb(self.d, scale_part(M.to_glb(self.d), 0, 1.3))
        obj = json.loads(json.dumps(M.edits_to_obj(self.d, edits)))
        self.assertEqual(obj["format"], M.EDIT_FORMAT)
        self.assertEqual(M.apply_edits(self.d, M.obj_to_edits(self.d, obj)),
                         M.apply_edits(self.d, edits))

    def test_list_and_export(self):
        r = run("mesh_replace.py", "list", NB1 / "witchhat.lu")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("192a15fc", r.stdout)
        out = self.tmp / "hat.glb"
        r = run("mesh_replace.py", "export", NB1 / "witchhat.lu", "--mesh", "192a15fc",
                "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(M.edits_from_glb(self.d, out.read_bytes())[0], {})

    def test_an_unchanged_glb_is_an_error(self):
        glb = self.tmp / "same.glb"
        glb.write_bytes(M.to_glb(self.d))
        r = run("mesh_replace.py", "replace", NB1 / "witchhat.lu", "--mesh", "192a15fc",
                "--glb", glb, "--patch", self.tmp / "x.srpatch")
        self.assertEqual(r.returncode, 1)
        self.assertIn("changes nothing", r.stderr)

    @unittest.skipUnless(HAVE_LZXV, "needs lzxverify")
    def test_patch_and_lu_agree_on_every_copy(self):
        game = self.tmp / "game"
        game.mkdir()
        for n in ("witchhat.lu", "mp_witchhat.lu"):
            shutil.copy2(NB1 / n, game / n)
        glb = self.tmp / "big.glb"
        glb.write_bytes(scale_part(M.to_glb(self.d), 0, 2.0))
        patch, out = self.tmp / "BigHat.srpatch", self.tmp / "out"
        r = run("mesh_replace.py", "replace", game / "witchhat.lu", "--mesh", "192a15fc",
                "--glb", glb, "--all-copies", "--patch", patch, "--out-dir", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        info = run("sr_patch.py", "info", patch)
        self.assertIn("mesh 0x192a15fc edited", info.stdout)
        applied = self.tmp / "applied"
        r = run("sr_patch.py", "apply", patch, game, "-o", applied)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in ("witchhat.lu", "mp_witchhat.lu"):
            self.assertEqual((applied / n).read_bytes(), (out / n).read_bytes(), n)
            self.assertEqual((out / n).stat().st_size > 0, True)


# ======================================================================= PiP
@unittest.skipUnless(HAVE_PIP, "needs numpy, Pillow and your PiP files (SR_TEST_PIP_DIR)")
class Pip(unittest.TestCase):
    def setUp(self):
        from naughty_lu import LuFile
        self.src = PIP / "vibbadge_acc.lu"
        self.lu = LuFile(self.src)
        self.tmp = Path(tempfile.mkdtemp(prefix="srpip_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_round_trips(self):
        for r in self.lu.records:
            if r.external:
                continue
            d = bytes(self.lu.chunk(r))
            if r.type in T.TEX_TYPES:
                self.assertEqual(T.roundtrip(d)[1], [], f"{r.hash:08x}")
            elif r.type in M.MESH_TYPES and M.is_mesh(d):
                self.assertEqual(M.roundtrip(d), [], f"{r.hash:08x}")

    def check_in_place(self, data):
        from naughty_lu import LuFile
        p = self.tmp / "out.lu"
        p.write_bytes(data)
        back = LuFile(p)
        # the source is LZX-compressed and PiP containers are written with raw
        # segments, so the file grows; what must not change is any record's
        # place and size in the image
        self.assertEqual([(r.offset, r.size) for r in back.records],
                         [(r.offset, r.size) for r in self.lu.records])
        return back

    def test_texture_and_mesh_keep_every_record_in_place(self):
        d = bytes(self.lu.chunk(T.texture_records(self.lu, V_TEX)[0]))
        t = T.info(d)
        data, _ = T.replace_in_container(self.src, [(V_TEX, ("p.png", _png(
            picture(t["width"], t["height"]))), None)])
        self.check_in_place(data)
        md = bytes(self.lu.chunk(M.mesh_records(self.lu, V_MESH)[0]))
        edits, _ = M.edits_from_glb(md, scale_part(M.to_glb(md), 0, 1.5))
        data, _ = M.replace_in_container(self.src, [(V_MESH, M.edits_to_obj(md, edits), None)])
        back = self.check_in_place(data)
        self.assertNotEqual(bytes(back.chunk(M.mesh_records(back, V_MESH)[0])), md)

    def test_patches_apply_identically(self):
        game = self.tmp / "game"
        game.mkdir()
        shutil.copy2(self.src, game / self.src.name)
        pic = self.tmp / "badge.png"
        picture(128, 128, seed=5).save(pic)
        out = self.tmp / "out"
        r = run("tex_replace.py", "replace", game / self.src.name, "--texture", f"{V_TEX:08x}",
                "--image", pic, "--patch", self.tmp / "Badge.srpatch", "-o", out / "tex.lu")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run("sr_patch.py", "apply", self.tmp / "Badge.srpatch", game, "-o",
                self.tmp / "applied")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.tmp / "applied" / self.src.name).read_bytes(),
                         (out / "tex.lu").read_bytes())


# ======================================================================= GUI
@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def form(self, title):
        from sr_gui import mainwindow, toolspecs
        from sr_gui.widgets import ToolForm
        w = mainwindow.Main()
        self.addCleanup(w.close)
        f = ToolForm(toolspecs.find(title), w.ctx)
        self.addCleanup(f.close)
        return f

    def test_replace_texture_form(self):
        f = self.form("Replace a texture")
        self.assertIsNone(f.argv())
        f.set_values({"Container with the texture": "C:/g/lu/witchhat.lu",
                      "Texture hash": "8e93a45c", "Picture (PNG or DDS)": "C:/m/hat.png",
                      "Save patch as": "C:/m/Hat.srpatch"})
        a = f.argv()
        tail = a[a.index("replace") + 1:]
        self.assertTrue(any("tex_replace" in x for x in a))
        self.assertEqual(tail[0], "C:/g/lu/witchhat.lu")
        for flag, v in (("--texture", "8e93a45c"), ("--image", "C:/m/hat.png"),
                        ("--patch", "C:/m/Hat.srpatch")):
            self.assertEqual(tail[tail.index(flag) + 1], v)
        self.assertIn("--all-copies", tail)

    def test_replace_model_form(self):
        f = self.form("Replace a model")
        f.set_values({"Container with the model": "C:/g/lu/naughtybear.lu",
                      "Model hash": "743299d0", "Edited .glb": "C:/m/big.glb",
                      "Save patched .lu files into": "C:/m/out"})
        a = f.argv()
        tail = a[a.index("replace") + 1:]
        self.assertTrue(any("mesh_replace" in x for x in a))
        for flag, v in (("--mesh", "743299d0"), ("--glb", "C:/m/big.glb"),
                        ("--out-dir", "C:/m/out")):
            self.assertEqual(tail[tail.index(flag) + 1], v)
        self.assertNotIn("--glb-normals", tail)

    def test_textures_tab_opens_the_filled_form(self):
        from sr_gui import mainwindow
        w = mainwindow.Main()
        self.addCleanup(w.close)
        w.open_tool("Replace a texture", {"Texture hash": "26ca1642"})
        form, _ = w.tools_page.forms["Replace a texture"]
        self.assertEqual(form.widgets["Texture hash"][1].text(), "26ca1642")

    def test_models_tab_has_the_forms(self):
        from sr_gui import mainwindow
        from sr_gui.views import ContainerView
        w = mainwindow.Main()
        self.addCleanup(w.close)
        v = ContainerView(w.ctx)
        titles = [f.spec["title"] for f in v.edit_models.forms]
        for t in ("List models", "Export a model for editing", "Replace a model"):
            self.assertIn(t, titles)


class Packaging(unittest.TestCase):
    def test_spec_bundles_the_tools(self):
        spec = (ROOT / "seamripper.spec").read_text(encoding="utf-8")
        for n in ("lu_texture.py", "lu_mesh.py", "lu_records.py", "tex_replace.py",
                  "mesh_replace.py"):
            self.assertIn(f'"{n}"', spec)
            self.assertTrue((TOOLS / n).is_file(), n)


def _png(img):
    import io
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


if __name__ == "__main__":
    unittest.main()
