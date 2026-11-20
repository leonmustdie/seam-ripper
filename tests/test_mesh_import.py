#!/usr/bin/env python3
"""Importing a new model (any vertex and triangle count) into a mesh:
mesh_import (decode, encode, strips, layout, radii, rigged GLB out and in),
`mesh_replace.py export --rigged` and `import`, `tex_replace --image
flat-normal`, the .srpatch "model" edit and the GUI form.

Every test that reads game files skips without them (SR_TEST_NB1_DIR,
SR_TEST_PIP_DIR, see game_paths.py). Naughty's mesh 743299d0 is read from
naughtybear.lu (NB1) and skinnaughty.lu (PiP); container writes use small
containers with a skinned mesh: deadbook.lu (NB1, 708 vertices, three
weights) and beardtomstache_acc.lu (PiP, 121 vertices, four weights).

Format claims (LU_FORMAT.md 34) are tested so they could fail: each test
names what would disprove its claim.
"""
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
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
NAUGHTY = 0x743299D0
HAVE_NB1 = HAVE_LIBS and (NB1 / "naughtybear.lu").exists() and (NB1 / "deadbook.lu").exists()
HAVE_PIP = HAVE_LIBS and (PIP / "skinnaughty.lu").exists() and \
    (PIP / "beardtomstache_acc.lu").exists()
DEADBOOK, BEARD = 0x6BF9A718, 0x34C698A1

if HAVE_LIBS:
    import lu_mesh as M
    import mesh_import as MI


def run(script, *args):
    return subprocess.run([sys.executable, str(TOOLS / script), *map(str, args)],
                          capture_output=True, text=True)


def record(lu_path, h):
    from naughty_lu import LuFile
    lu = LuFile(lu_path)
    return lu, bytes(lu.chunk(M.mesh_records(lu, h)[0]))


def skeleton_world(lu):
    """Bind matrices (row vectors) of the skeleton that names Naughty's mesh."""
    from lu_rig import parse_skeleton
    for r in lu.records:
        if r.external or (r.type & 0x0FFFFFFF) != 0x04000001:
            continue
        s = bytes(lu.chunk(r))
        ptr, cnt = struct.unpack_from(">2I", s, 8)
        if 0 < cnt < 64 and any(struct.unpack_from(">I", s, ptr + 8 * i)[0] == NAUGHTY
                                for i in range(cnt)):
            s = s[:4] + struct.pack(">I", 0x04000001) + s[8:]
            return np.array([b["world"] for b in parse_skeleton(s)], np.float64)
    return None


def grid(n=12, z=0.0):
    """A flat n x n vertex sheet: positions, normals, uvs, triangles."""
    y, x = np.mgrid[0:n, 0:n]
    P = np.c_[x.ravel() / (n - 1), y.ravel() / (n - 1), np.full(n * n, z)]
    t = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            t += [(a, a + 1, a + n + 1), (a, a + n + 1, a + n)]
    return P, np.tile([0.0, 0.0, 1.0], (n * n, 1)), P[:, :2].copy(), np.array(t)


def new_part(d, sm, n=12, scale=1.0, centre=None):
    """A made-up skinned part: a sheet weighted to the part's first two
    palette bones (half and half)."""
    P, N, UV, T = grid(n)
    pal = MI.palette(d, sm)
    if centre is None:
        centre = MI.bind_world(MI.inverse_binds(d))[pal["bones"][0]][3, :3]
    P = (P - 0.5) * scale + centre
    nv = len(P)
    bones = np.full((nv, 4), pal["bones"][0])
    W = np.zeros((nv, 4), np.float32)
    W[:, 0] = 1
    if len(pal["bones"]) > 1 and MI.influences(sm) > 1:
        bones[:, 1] = pal["bones"][1]
        W[:, 0] = W[:, 1] = 0.5
    return {"position": P.astype(np.float32), "normal": N.astype(np.float32),
            "uv": [UV.astype(np.float32)], "color": [], "bones": bones,
            "weights": W, "triangles": T}


def compact(part):
    """Drop the vertices no triangle uses."""
    used = np.unique(part["triangles"])
    remap = np.full(len(part["position"]), -1)
    remap[used] = np.arange(len(used))
    out = {k: (v[used] if k in ("position", "normal", "tangent", "bones", "weights")
               and v is not None else v) for k, v in part.items()}
    out["uv"] = [None if u is None else u[used] for u in part["uv"]]
    out["color"] = [None if c is None else c[used] for c in part["color"]]
    out["triangles"] = remap[part["triangles"]]
    return out


@unittest.skipUnless(HAVE_LIBS, "needs numpy")
class Strips(unittest.TestCase):
    def test_strip_gives_the_same_triangles(self):
        _, _, _, T = grid(15)
        rng = np.random.default_rng(3)
        for tris in (T, T[rng.permutation(len(T))], T[:7], T[::3]):
            s = MI.stripify(tris)
            self.assertTrue(MI.same_triangles(MI.strip_triangles(s, 10 ** 6), tris))
            self.assertLess(len(s), 3 * len(tris))

    def test_lone_and_shared_edge_triangles(self):
        # non-manifold: three triangles on one edge; and a lone triangle
        tris = np.array([(0, 1, 2), (1, 0, 3), (1, 0, 4), (5, 6, 7)])
        s = MI.stripify(tris)
        self.assertTrue(MI.same_triangles(MI.strip_triangles(s, 100), tris))

    def test_corrupt_strip_detected(self):
        _, _, _, T = grid(6)
        s = MI.stripify(T)
        s[3] = s[4]                                  # a wrong vertex in the strip
        self.assertFalse(MI.same_triangles(MI.strip_triangles(s, 100), T))

    def test_neutral_form_round_trip(self):
        P, N, UV, T = grid(5)
        part = {"position": P.astype(np.float32), "normal": N.astype(np.float32),
                "uv": [UV.astype(np.float32), None], "color": [None, np.arange(25, dtype=np.uint32)],
                "bones": np.ones((25, 4), np.int16), "weights": np.ones((25, 4), np.float32) / 4,
                "triangles": T}
        obj = json.loads(json.dumps(MI.parts_to_obj({0: part, 3: "collapse"})))
        back = MI.obj_to_parts(obj)
        self.assertEqual(back[3], "collapse")
        for k in ("position", "normal", "weights", "triangles"):
            np.testing.assert_array_equal(back[0][k], part[k])
        self.assertIsNone(back[0]["uv"][1])
        self.assertIsNone(back[0]["color"][0])
        obj["parts"]["0"]["vertices"] = 24                 # damaged
        with self.assertRaises(M.MeshError):
            MI.obj_to_parts(obj)


@unittest.skipUnless(HAVE_NB1 and HAVE_PIP, "needs both games' files")
class FormatClaims(unittest.TestCase):
    """LU_FORMAT.md 34: what a vertex-count change touches."""

    @classmethod
    def setUpClass(cls):
        cls.recs = {"nb1": record(NB1 / "naughtybear.lu", NAUGHTY),
                    "pip": record(PIP / "skinnaughty.lu", NAUGHTY)}

    def test_trailer_holds_vertex_and_index_counts(self):
        # disproved by a sub-model whose trailer +0x1c / +0x20 differs from
        # vb size / stride and ib size / 2
        for game, (_, d) in self.recs.items():
            for sm in M.submodels(d):
                tp = MI.trailer_at(d, sm)
                self.assertEqual(struct.unpack_from(">2I", d, tp + 0x1c),
                                 (sm["verts"], sm["isz"] // 2), (game, sm["n"]))

    def test_palette_struct_points_at_the_inverse_binds(self):
        # disproved by inverse binds that do not invert the skeleton's bind
        # matrices, or a palette struct pointing elsewhere than sub-model +0x60
        for game, (lu, d) in self.recs.items():
            W = skeleton_world(lu)
            IB = MI.inverse_binds(d)
            self.assertEqual(len(W), len(IB))
            err = max(np.abs(IB[i] @ W[i] - np.eye(4)).max() for i in range(len(W)))
            self.assertLess(err, 1e-5, game)
            for sm in M.submodels(d):
                pal = MI.palette(d, sm)
                if pal is not None:
                    self.assertEqual(pal["ibp"], struct.unpack_from(">I", d, sm["sp"] + 0x60)[0])
                    self.assertEqual(d[pal["ibp"]:pal["ibp"] + 64 * len(IB)],
                                     d[MI.palette(d, M.submodels(d)[0])["ibp"]:][:64 * len(IB)])

    def test_bone_radius_array_mirrors_the_palette(self):
        # disproved by a {bone, radius} entry that differs from the palette
        # bone or the radii array at the same slot
        for game, (_, d) in self.recs.items():
            for sm in M.submodels(d):
                pal = MI.palette(d, sm)
                if pal is None:
                    continue
                for j, b in enumerate(pal["bones"]):
                    self.assertEqual(struct.unpack_from(">If", d, pal["p8"] + 8 * j),
                                     (b, float(np.float32(pal["radii"][j]))))

    def test_radii_bound_the_weighted_vertices(self):
        # disproved by a radius smaller than its slot's farthest vertex
        for game, (_, d) in self.recs.items():
            for sm in M.submodels(d):
                if MI.palette(d, sm) is not None:
                    self.assertIsNone(MI.radius_problem(d, sm, tol=1e-5), (game, sm["n"]))
        # control: shrink one radius below its vertices and it is caught
        _, d = self.recs["nb1"]
        sm = M.submodels(d)[0]
        pal = MI.palette(d, sm)
        bad = bytearray(d)
        struct.pack_into(">f", bad, pal["rp"] + 4 * 3, pal["radii"][3] * 0.5)
        self.assertIsNotNone(MI.radius_problem(bytes(bad), sm, tol=1e-5))


@unittest.skipUnless(HAVE_NB1 and HAVE_PIP, "needs both games' files")
class Naughty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = {"nb1": record(NB1 / "naughtybear.lu", NAUGHTY),
                    "pip": record(PIP / "skinnaughty.lu", NAUGHTY)}

    def test_reimport_every_part(self):
        for game, (_, d) in self.recs.items():
            self.assertEqual(MI.roundtrip(d, game), [], game)

    def test_nb1_appends_and_pip_keeps_size(self):
        for game, (_, d) in self.recs.items():
            sm = M.submodels(d)[0]
            part = MI.decode_part(d, sm)
            new = MI.build_record(d, {0: part}, game)
            s2 = M.submodels(new)[0]
            if game == "nb1":
                self.assertGreater(len(new), len(d))
                self.assertEqual(s2["vo"] % 0x1000, 0)
                self.assertEqual(s2["io"] % 0x1000, 0)
                self.assertGreaterEqual(s2["vo"], len(d))
                qp = struct.unpack_from(">I", d, sm["sp"] + 0x40)[0]
                self.assertEqual(new[sm["sp"] + 0x80:qp], d[sm["sp"] + 0x80:qp])  # material
                self.assertEqual(new[qp + 20:sm["vo"]], d[qp + 20:sm["vo"]])
            else:
                self.assertEqual(len(new), len(d))
                self.assertEqual(s2["vo"], sm["vo"])
            self.assertEqual(new[s2["vo"]:s2["vo"] + s2["vs"]], d[sm["vo"]:sm["vo"] + sm["vs"]])

    def test_decimated_and_denser(self):
        for game, (_, d) in self.recs.items():
            sm = M.submodels(d)[0]
            part = MI.decode_part(d, sm)
            small = compact(dict(part, triangles=part["triangles"][::2]))
            new = MI.build_record(d, {0: small, 1: "collapse", 2: "collapse"}, game)
            s = M.submodels(new)
            self.assertEqual(len(M.triangles(new, s[0])), len(small["triangles"]))
            self.assertEqual(len(M.triangles(new, s[1])), 0)
            self.assertEqual(len(M.triangles(new, s[2])), 0)
            # denser: every vertex twice (a second copy of the body)
            nv = len(part["position"])
            big = {k: (np.concatenate([v, v]) if k in ("position", "normal", "tangent",
                                                         "bones", "weights") else v)
                   for k, v in part.items()}
            big["uv"] = [np.concatenate([u, u]) for u in part["uv"]]
            big["triangles"] = np.concatenate([part["triangles"], part["triangles"] + nv])
            if game == "nb1":
                new = MI.build_record(d, {0: big}, game)
                self.assertEqual(M.submodels(new)[0]["verts"], 2 * nv)
            else:
                with self.assertRaises(M.MeshError) as cm:
                    MI.build_record(d, {0: big}, game)
                self.assertIn("does not fit", str(cm.exception))
                self.assertIn("bytes for this part", str(cm.exception))

    def test_bad_input_refused(self):
        _, d = self.recs["nb1"]
        sm = M.submodels(d)[0]
        part = MI.decode_part(d, sm)
        pal = MI.palette(d, sm)
        outside = next(b for b in range(117) if b not in pal["bones"])
        cases = {
            "bone outside the palette": dict(part, bones=np.where(
                part["weights"] > 0.3, outside, part["bones"])),
            "vertex out of range": dict(part, triangles=np.r_[part["triangles"],
                                                              [[0, 1, 99999]]]),
            "not a number": dict(part, position=np.where(
                np.arange(len(part["position"]))[:, None] == 5, np.nan, part["position"])),
            "no weights": dict(part, weights=np.zeros_like(part["weights"])),
        }
        for what, p in cases.items():
            with self.assertRaises(M.MeshError, msg=what):
                MI.build_record(d, {0: p}, "nb1")
        with self.assertRaises(M.MeshError):                       # shadow volume
            MI.build_record(d, {3: part}, "nb1")
        with self.assertRaises(M.MeshError):
            MI.build_record(d, {0: part}, "pip", in_place=False)

    def test_weights_reduced_to_the_layout(self):
        # five-bone weights on a four-weight layout: the four heaviest kept
        _, d = self.recs["pip"]
        sm = M.submodels(d)[0]
        pal = MI.palette(d, sm)
        p = new_part(d, sm, 4)
        n = len(p["position"])
        p["bones"] = np.tile(pal["bones"][:4], (n, 1))
        p["weights"] = np.tile(np.float32([0.4, 0.3, 0.2, 0.1]), (n, 1))
        new = MI.build_record(d, {0: p}, "pip")
        got = MI.decode_part(new, M.submodels(new)[0])
        np.testing.assert_allclose(got["weights"].sum(1), 1, atol=1e-6)
        np.testing.assert_allclose(np.sort(got["weights"], 1)[:, ::-1][0],
                                   [0.4, 0.3, 0.2, 0.1], atol=1e-6)

    def test_rigged_glb_round_trip(self):
        for game, (lu, d) in self.recs.items():
            glb = MI.to_rigged_glb(d, MI.skeleton_for(lu, NAUGHTY))
            g, _ = M._read_glb(glb)
            names = [nd["name"] for nd in g["nodes"] if "sr_bone" in nd.get("extras", {})]
            self.assertEqual(len(names), len(MI.inverse_binds(d)))
            self.assertTrue(all(MI.BONE_RE.match(x) and int(MI.BONE_RE.match(x).group(1)) == i
                                for i, x in enumerate(names)))
            self.assertEqual(g["extras"].get("sr_left_out"), [1, 2])   # bone 78 rest scale
            notes = []
            parts = MI.parts_from_glb(d, glb, notes)
            self.assertEqual(sorted(parts), [0])
            ref = MI.decode_part(d, M.submodels(d)[0])
            np.testing.assert_allclose(parts[0]["position"], ref["position"], atol=1e-6)
            self.assertTrue(MI.same_triangles(parts[0]["triangles"], ref["triangles"]))
            new = MI.build_record(d, parts, game)
            self.assertIsNone(MI.radius_problem(new, M.submodels(new)[0]))

    def test_glb_moved_model_and_wrong_names(self):
        _, d = self.recs["nb1"]
        glb = MI.to_rigged_glb(d)
        g, blob = M._read_glb(glb)
        # move every joint in the file 1 unit up: the model, skinned at the
        # file's rest pose, comes back 1 unit up
        g["nodes"][0]["matrix"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1]
        moved = _glb(g, blob)
        p = MI.parts_from_glb(d, moved)[0]
        ref = MI.decode_part(d, M.submodels(d)[0])
        np.testing.assert_allclose(p["position"] - ref["position"],
                                   np.tile([0, 1, 0], (len(ref["position"]), 1)), atol=1e-5)
        # joints renamed: weights no longer reach skeleton bones
        g2 = json.loads(json.dumps(g))
        for nd in g2["nodes"]:
            if "sr_bone" in nd.get("extras", {}):
                nd["name"] = "joint"
                del nd["extras"]["sr_bone"]
        with self.assertRaises(M.MeshError):
            MI.parts_from_glb(d, _glb(g2, blob))
        # a skinned part without a skin
        g3 = json.loads(json.dumps(g))
        for nd in g3["nodes"]:
            nd.pop("skin", None)
        with self.assertRaises(M.MeshError):
            MI.parts_from_glb(d, _glb(g3, blob))


def _glb(g, blob):
    js = json.dumps(g, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


@unittest.skipUnless(HAVE_NB1 and HAVE_PIP, "needs both games' files")
class Corpus(unittest.TestCase):
    """Every retail skinned part, both games, re-imported through the new
    path: the vertex buffer byte for byte, the same triangles, radii that
    reach their vertices, every other part untouched (a few minutes)."""

    def _all(self, folder, game):
        import hashlib
        seen, bad, over = set(), [], []
        for label, d in M.iter_meshes([folder]):
            k = hashlib.sha1(d).digest()
            if k in seen:
                continue
            seen.add(k)
            try:
                probs = MI.roundtrip(d, game, over, kinds=("skinned",))
            except M.MeshError as e:
                probs = [str(e)]
            if probs:
                bad.append(f"{label}: {probs[:2]}")
        self.assertEqual(bad, [])
        return len(seen)

    def test_nb1(self):
        self.assertGreater(self._all(NB1, "nb1"), 250)

    def test_pip(self):
        self.assertGreater(self._all(PIP, "pip"), 500)


@unittest.skipUnless(HAVE_NB1 and HAVE_PIP, "needs both games' files")
class Containers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sr_import_"))

    def _glb(self, lu_path, h, scale):
        lu, d = record(lu_path, h)
        sm = next(s for s in M.submodels(d) if s["kind"] == "skinned" and MI.influences(s) > 1)
        part = new_part(d, sm, 10, scale)
        return d, sm, part

    def test_nb1_import_grows_the_record_and_verifies(self):
        d, sm, part = self._glb(NB1 / "deadbook.lu", DEADBOOK, 0.3)
        obj = MI.parts_to_obj({sm["n"]: part})
        data, log = MI.import_in_container(NB1 / "deadbook.lu", [(DEADBOOK, obj, None)])
        out = self.tmp / "deadbook.lu"
        out.write_bytes(data)
        from naughty_lu import LuFile
        lu2 = LuFile(out)
        d2 = bytes(lu2.chunk(M.mesh_records(lu2, DEADBOOK)[0]))
        self.assertGreater(len(d2), len(d))
        s2 = M.submodels(d2)[sm["n"]]
        self.assertEqual(s2["verts"], 100)
        self.assertEqual(len(M.triangles(d2, s2)), 162)
        if any((TOOLS / n).exists() for n in ("lzxverify.exe", "lzxverify")):
            import verify_lzx
            verify_lzx.verify_file(str(out))

    def test_pip_import_keeps_every_offset(self):
        d, sm, part = self._glb(PIP / "beardtomstache_acc.lu", BEARD, 0.05)
        part["position"] = part["position"][:60]
        for k in ("normal", "bones", "weights"):
            part[k] = part[k][:60]
        part["uv"] = [u[:60] for u in part["uv"]]
        part["triangles"] = part["triangles"][(part["triangles"] < 60).all(1)]
        obj = MI.parts_to_obj({sm["n"]: part})
        from naughty_lu import LuFile
        lu = LuFile(PIP / "beardtomstache_acc.lu")
        data, _ = MI.import_in_container(PIP / "beardtomstache_acc.lu", [(BEARD, obj, None)])
        out = self.tmp / "beardtomstache_acc.lu"
        out.write_bytes(data)
        lu2 = LuFile(out)
        self.assertEqual([(r.offset, r.size) for r in lu2.records],
                         [(r.offset, r.size) for r in lu.records])
        d2 = bytes(lu2.chunk(M.mesh_records(lu2, BEARD)[0]))
        self.assertEqual(M.submodels(d2)[sm["n"]]["verts"], 60)

    def test_cli_patch_and_apply(self):
        lu, d = record(PIP / "beardtomstache_acc.lu", BEARD)
        glb = self.tmp / "beard_rig.glb"
        r = run("mesh_replace.py", "export", PIP / "beardtomstache_acc.lu", "--mesh",
                f"{BEARD:08x}", "--rigged", "-o", glb, "--no-textures")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("joints b000", r.stdout)
        patch = self.tmp / "Beard.srpatch"
        r = run("mesh_replace.py", "import", PIP / "beardtomstache_acc.lu", "--mesh",
                f"{BEARD:08x}", "--glb", glb, "--patch", patch, "--out-dir", self.tmp / "out")
        self.assertEqual(r.returncode, 0, r.stderr)
        import sr_patch
        m = sr_patch.read_manifest(patch)
        self.assertEqual(m["format_version"], 5)
        self.assertEqual([e["kind"] for t in m["targets"] for e in t["edits"]], ["model"])
        res = sr_patch.apply_patch(patch, PIP, out_dir=self.tmp / "applied", log=lambda s: None)
        got = (self.tmp / "applied" / "beardtomstache_acc.lu").read_bytes()
        self.assertEqual(got, (self.tmp / "out" / "beardtomstache_acc.lu").read_bytes())
        self.assertEqual(res["files"][0]["status"], "identical")
        info = sr_patch.info_text(m, patch)
        self.assertIn("new model", info)
        # nothing to import
        r = run("mesh_replace.py", "import", PIP / "beardtomstache_acc.lu", "--mesh",
                f"{BEARD:08x}", "-o", self.tmp / "x.lu")
        self.assertNotEqual(r.returncode, 0)

    def test_collapse_only(self):
        r = run("mesh_replace.py", "import", NB1 / "naughtybear.lu", "--mesh",
                f"{NAUGHTY:08x}", "--collapse", "1,2", "--in-place", "-o",
                self.tmp / "naughtybear.lu")
        self.assertEqual(r.returncode, 0, r.stderr)
        lu, d = record(self.tmp / "naughtybear.lu", NAUGHTY)
        _, d0 = record(NB1 / "naughtybear.lu", NAUGHTY)
        self.assertEqual(len(d), len(d0))
        s = M.submodels(d)
        self.assertEqual([len(M.triangles(d, x)) for x in s[1:3]], [0, 0])

    def test_flat_normal_fill(self):
        r = run("tex_replace.py", "replace", PIP / "beardtomstache_acc.lu", "--texture",
                _a_texture(PIP / "beardtomstache_acc.lu"), "--image", "flat-normal",
                "-o", self.tmp / "flat.lu")
        self.assertEqual(r.returncode, 0, r.stderr)
        import lu_texture as T
        from naughty_lu import LuFile
        lu = LuFile(self.tmp / "flat.lu")
        h = int(_a_texture(PIP / "beardtomstache_acc.lu"), 16)
        img = T.level_image(bytes(lu.chunk(T.texture_records(lu, h)[0])))
        a = np.asarray(img.convert("RGB"), float)
        self.assertLess(np.abs(a - [128, 128, 255]).max(), 6)


def _a_texture(lu_path):
    import lu_texture as T
    from naughty_lu import LuFile
    lu = LuFile(lu_path)
    r = next(r for r in lu.records if r.type in T.TEX_TYPES and not r.external)
    return f"{r.hash:08x}"


@unittest.skipUnless(HAVE_QT and HAVE_LIBS, "needs PySide6")
class Form(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_import_form(self):
        from sr_gui import mainwindow, toolspecs
        from sr_gui.widgets import ToolForm
        w = mainwindow.Main()
        self.addCleanup(w.close)
        f = ToolForm(toolspecs.find("Import a new model"), w.ctx)
        self.addCleanup(f.close)
        f.set_values({"Container with the model": "C:/g/lu/naughtybear.lu",
                      "Model hash": "743299d0", "New model .glb": "C:/m/new.glb",
                      "Parts to hide (e.g. 1,2)": "1,2",
                      "Save patched .lu files into": "C:/m/out"})
        a = f.argv()
        tail = a[a.index("import") + 1:]
        self.assertTrue(any("mesh_replace" in x for x in a))
        for flag, v in (("--mesh", "743299d0"), ("--glb", "C:/m/new.glb"),
                        ("--collapse", "1,2"), ("--out-dir", "C:/m/out")):
            self.assertEqual(tail[tail.index(flag) + 1], v)
        from sr_gui.views import ContainerView
        titles = [x.spec["title"] for x in ContainerView(w.ctx).edit_models.forms]
        self.assertIn("Import a new model", titles)

    def test_spec_bundles_the_tool(self):
        spec = (TOOLS.parent / "seamripper.spec").read_text(encoding="utf-8")
        self.assertIn('"mesh_import.py"', spec)


if __name__ == "__main__":
    unittest.main()
