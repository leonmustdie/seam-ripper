#!/usr/bin/env python3
"""Decode -> encode -> decode check for NB1 clip records (lu_anim_encode).

Per unique clip:
  raw     encode_clip(parse_clip(d), "raw") == d byte for byte (layout)
  f32     decode_clip(d) and decode_clip(encode_clip(.., "f32")) agree:
          same header fields, markers, bone/tag/channel set; statics
          equal exactly; keyed channels equal when sampled densely
  redund  the Euler (08-0a) / quaternion (23-25) redundancy (LU_FORMAT 28.5)
          still holds on the re-encoded clip as well as on the original
  json    the same through the neutral clip JSON a .srpatch stores
          (model_to_json -> text -> build_clip on the original record)
  sabot   a deliberately corrupted encode (one coefficient +0.01) is caught
          by the same comparison, so the comparison can fail
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lu_anim2 import decode_clip, sample_channel, euler_xyz_quat  # noqa: E402
from lu_anim_encode import (parse_clip, encode_clip, sha256, EncodeError,  # noqa: E402
                            model_to_json, build_clip)

TOL = 2e-5          # absolute, after scaling by max(1, |value|)
BAD_STATS = ("bad_", "size_mismatch", "unknown_enc", "keys_unsorted",
             "insane", "keyed_bad", "static_bad", "pieces_unsorted")


def _key(ch):
    return (ch["tag"], ch["family"])


def _grid(ch, duration):
    ts = [np.linspace(0.0, max(duration, 1e-3), 241)]
    if ch.get("kind") == "poly":
        T0, T1 = ch["seg_start"], ch["seg_end"]
        ts += [T0, T1, (T0 + T1) / 2, T0 + (T1 - T0) / 4]
    else:
        ts.append(ch["times"])
    return np.unique(np.concatenate(ts))


def compare(c0, c1):
    """-> (max scaled error, list of problems)."""
    probs = []
    for k in ("name_hash", "rig_hash", "track_count"):
        if c0[k] != c1[k]:
            probs.append(f"{k} {c0[k]} != {c1[k]}")
    if abs(c0["duration"] - c1["duration"]) > 1e-7:
        probs.append("duration")
    if c0["markers"] != c1["markers"]:
        probs.append("markers")
    worst = 0.0
    for b in sorted(set(c0["tracks"]) | set(c1["tracks"])):
        a0 = c0["tracks"].get(b, [])
        a1 = c1["tracks"].get(b, [])
        if [_key(x) for x in a0] != [_key(x) for x in a1]:
            probs.append(f"bone {b}: channel set differs")
            continue
        for x, y in zip(a0, a1):
            if x["family"] != "keyed":
                if x["values"][0] != y["values"][0]:
                    probs.append(f"bone {b} static {x['tag']:02x}: "
                                 f"{x['values'][0]} != {y['values'][0]}")
                continue
            ts = _grid(x, c0["duration"])
            v0, v1 = sample_channel(x, ts), sample_channel(y, ts)
            err = float(np.max(np.abs(v0 - v1) / np.maximum(1.0, np.abs(v0))))
            worst = max(worst, err)
            if not err <= TOL:
                probs.append(f"bone {b} tag {x['tag']:02x}: error {err:.3g}")
    return worst, probs


def redundancy(c, duration):
    """Median angle (rad) between quat(Euler 08-0a) and quaternion 23-25 on
    bones that key both completely, or [] if none."""
    out = []
    for b, chans in c["tracks"].items():
        by = {ch["tag"]: ch for ch in chans if ch["family"] == "keyed"}
        if not all(t in by for t in (0x08, 0x09, 0x0A, 0x23, 0x24, 0x25)):
            continue
        ts = np.linspace(0.0, duration, 31)
        e = np.stack([sample_channel(by[t], ts) for t in (0x08, 0x09, 0x0A)], 1)
        v = np.stack([sample_channel(by[t], ts) for t in (0x23, 0x24, 0x25)], 1)
        q = np.concatenate([v, np.sqrt(np.clip(1 - (v * v).sum(1), 0, None))[:, None]], 1)
        qe = euler_xyz_quat(e)
        dots = np.clip(np.abs((q * qe).sum(1)) / np.linalg.norm(q, axis=1), 0, 1)
        out.append(float(np.median(2 * np.arccos(dots))))
    return out


def _bad(stats):
    return {k: v for k, v in stats.items() if k.startswith(BAD_STATS)}


def _sabotage(model):
    """A copy of the model with one keyed value nudged by 0.01."""
    import copy
    m = copy.deepcopy(model)
    for bone in m["bones"]:
        for ch in bone["keyed"]:
            for pc in ch["pieces"]:
                if "times" in pc:
                    if pc["kind"] == "sample":
                        pc["values"][len(pc["values"]) // 2] += 0.01
                    else:
                        pc["coef"][len(pc["coef"]) // 2, -1] += 0.01
                    return m
    return None


def check_clip(d):
    r = {"size": len(d)}
    s0 = Counter()
    c0 = decode_clip(d, s0)
    if c0 is None:
        r["status"] = "retail_undecodable"
        return r
    try:
        m = parse_clip(d)
    except EncodeError as e:
        r["status"] = f"parse_error: {e}"
        return r
    r["raw_exact"] = encode_clip(m, "raw") == d
    d1 = encode_clip(m, "f32")
    r["f32_size"] = len(d1)
    s1 = Counter()
    c1 = decode_clip(d1, s1)
    if c1 is None:
        r["status"] = "f32_undecodable"
        return r
    new_bad = {k: v for k, v in _bad(s1).items() if _bad(s0).get(k, 0) < v}
    worst, probs = compare(c0, c1)
    r["max_err"] = worst
    if new_bad:
        probs.append(f"decoder complaints on re-encode: {new_bad}")
    r["problems"] = probs[:10]
    r["redund_retail"] = redundancy(c0, c0["duration"])
    r["redund_f32"] = redundancy(c1, c1["duration"])
    try:
        obj = json.loads(json.dumps(model_to_json(m)))
        cj = decode_clip(build_clip(obj, d), Counter())
        jp = compare(c0, cj)[1] if cj is not None else ["undecodable"]
    except EncodeError as e:
        jp = [str(e)]
    r["json_ok"] = not jp
    if jp:
        probs.append(f"json path: {jp[:3]}")
    sab = _sabotage(m)
    if sab is not None:
        cs = decode_clip(encode_clip(sab, "f32"), Counter())
        r["sabotage_caught"] = cs is None or bool(compare(c0, cs)[1])
    r["status"] = "ok" if not probs else "mismatch"
    return r


def run(clips, json_path=None, log=print):
    seen = {}
    dup = 0
    for label, d in clips:
        h = sha256(d)
        if h in seen:
            dup += 1
            continue
        seen[h] = (label, check_clip(d))
    rows = list(seen.values())
    st = Counter(r["status"] for _, r in rows)
    raw_ok = sum(1 for _, r in rows if r.get("raw_exact"))
    sab = [r.get("sabotage_caught") for _, r in rows if "sabotage_caught" in r]
    errs = [r["max_err"] for _, r in rows if "max_err" in r]
    red0 = [x for _, r in rows for x in r.get("redund_retail", [])]
    red1 = [x for _, r in rows for x in r.get("redund_f32", [])]
    size0 = sum(r["size"] for _, r in rows)
    size1 = sum(r.get("f32_size", r["size"]) for _, r in rows)
    log(f"unique clips: {len(rows)} (duplicates skipped: {dup})")
    log(f"status: {dict(st)}")
    log(f"raw re-emit byte-exact: {raw_ok} / {len(rows)}")
    log(f"neutral JSON path ok: {sum(1 for _, r in rows if r.get('json_ok'))} / {len(rows)}")
    if errs:
        log(f"f32 max scaled error: worst {max(errs):.3g}, "
            f"median {float(np.median(errs)):.3g} (tolerance {TOL})")
    log(f"sabotage caught: {sum(map(bool, sab))} / {len(sab)}")
    if red0:
        log(f"Euler/quat redundancy, median angle: retail {np.median(red0):.5f} rad "
            f"({len(red0)} bone-clips), re-encoded {np.median(red1):.5f} rad "
            f"({len(red1)}); worst retail {max(red0):.4f}, re-encoded {max(red1):.4f}")
    log(f"size: retail {size0:,} B, f32 re-encode {size1:,} B ({size1 / max(size0, 1):.2f}x)")
    bad = [(lbl, r) for lbl, r in rows if r["status"] != "ok" or not r.get("raw_exact")]
    for lbl, r in bad[:20]:
        log(f"  {lbl}: {r['status']} raw_exact={r.get('raw_exact')} {r.get('problems', '')}")
    if json_path:
        Path(json_path).write_text(json.dumps(
            {lbl: r for lbl, r in rows}, indent=1, default=float), encoding="utf-8")
    ok = (st.get("ok", 0) == len(rows) and raw_ok == len(rows) and all(sab)
          and (not red0 or np.median(red1) <= np.median(red0) + 1e-4))
    log("ROUNDTRIP OK" if ok else "ROUNDTRIP FAILED")
    return 0 if ok else 1
