#!/usr/bin/env python3
r"""Score a decompiler by byte-exact round trip."""
import argparse
import collections
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import nbdec

LUAC = HERE / "luac51.exe"
if not LUAC.exists():
    LUAC = HERE / "luac51"
NAME_RE = re.compile(rb"z:\\[\x20-\x7e]+?\.lua")


def compile_source(text, tmp):
    src = tmp / "in.lua"
    src.write_text(text, encoding="utf-8", newline="\n")
    out = tmp / "in.luac"
    r = subprocess.run([str(LUAC), "-s", "-o", str(out), str(src)],
                       capture_output=True, text=True)
    if r.returncode:
        return None, (r.stderr or r.stdout).strip().splitlines()[-1:]
    return out.read_bytes(), None


def proto_key(p):
    """The parts that actually run: instructions and constants."""
    return ([i.raw for i in p.code],
            [(c.kind, c.value) for c in p.consts])


def describe_diff(want, got):
    """A one-line label for HOW two protos differ, so failures can be
    grouped into classes instead of counted as one undifferentiated pile."""
    if len(want.code) != len(got.code):
        return (f"instruction count {len(want.code)} -> {len(got.code)}")
    for a, b in zip(want.code, got.code):
        if a.raw != b.raw:
            if a.op != b.op:
                return f"opcode {a.op} -> {b.op}"
            return f"{a.op} operands differ"
    kw = [(c.kind, c.value) for c in want.consts]
    kg = [(c.kind, c.value) for c in got.consts]
    if len(kw) != len(kg):
        return f"constant count {len(kw)} -> {len(kg)}"
    for i, (x, y) in enumerate(zip(kw, kg)):
        if x != y:
            return f"constant {i} order/value"
    return "identical?"


def show_diff(want, got, text):
    print("    source produced:")
    for line in text.splitlines()[:14]:
        print("      " + line)
    print(f"    {'want':<34} {'got':<34}")
    for n, (a, b) in enumerate(zip(want.code, got.code)):
        mark = " " if a.raw == b.raw else "*"
        print(f"    {mark} {a!r:<32} {b!r:<32}")
        if n > 18:
            break
    print()


def pip_chunks(paths, tmp):
    """(label, bytecode) for PiP scripts compiled with luac51."""
    import pip_scripts
    from naughty_lu import LuFile
    for base in paths:
        base = Path(base)
        files = sorted(base.rglob("*.lu")) if base.is_dir() else [base]
        for f in files:
            try:
                lu = LuFile(str(f))
            except Exception:
                continue
            if "LUH" not in getattr(lu, "platform", ""):
                continue
            for r in lu.records:
                if r.type != 0x04B00000 or getattr(r, "external", False):
                    continue
                try:
                    got = pip_scripts.extract_lua(bytes(lu.chunk(r)))
                except Exception:
                    continue
                if not got:
                    continue
                bc, err = compile_source(got[1], tmp)
                if bc is not None:
                    yield f"{f.stem}:{Path(got[0]).stem}", bc, None


def nb1_chunks(paths):
    """(label, standard-form bytecode) for real NB1 script chunks."""
    from naughty_lu import LuFile
    import lua_decompile as L
    import lua_recompile as R
    for base in paths:
        base = Path(base)
        files = sorted(base.rglob("*.lu")) if base.is_dir() else [base]
        for f in files:
            try:
                lu = LuFile(str(f))
            except Exception:
                continue
            img = lu.image
            for r in lu.records:
                ch = img[r.offset:r.offset + r.size]
                if b"\x1bLua" not in ch:
                    continue
                m = NAME_RE.search(ch)
                nm = m.group().decode().split("\\")[-1][:-4] if m else ""
                try:
                    std = L.transcode(ch, {}, as_numbers=True)
                except Exception:
                    continue
                yield f"{f.stem}:{nm}", std, R.ref_hash_set(ch)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pip", nargs="*", default=[],
                    help="PiP .lu files or folders (known-good corpus)")
    ap.add_argument("--nb1", nargs="*", default=[],
                    help="NB1 .lu files or folders")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many chunks")
    ap.add_argument("--diff", type=int, default=0,
                    help="show this many mismatching protos in full")
    a = ap.parse_args()
    if not (a.pip or a.nb1):
        sys.exit("give --pip and/or --nb1")

    tmp = Path(tempfile.mkdtemp(prefix="nbdec_bench_"))
    reasons = collections.Counter()
    exact = differ = 0
    chunks = 0
    shown = 0

    src = list(pip_chunks(a.pip, tmp)) if a.pip else []
    src += list(nb1_chunks(a.nb1)) if a.nb1 else []
    if a.limit:
        src = src[:a.limit]

    import nb_names
    names = nb_names.load()
    texts = nb_names.load_text()
    for label, bc, hvals in src:
        chunks += 1
        try:
            root = nbdec.parse(bc)
        except nbdec.BytecodeError as e:
            reasons[f"parse: {e}"] += 1
            continue
        # A chunk is decompiled whole: nested functions are emitted inline by
        # their parent, because a closure's upvalue bindings live in the
        # PARENT's instructions. Decompiling each proto standalone would tear
        # them away from the only place that says what they capture.
        n_protos = sum(1 for _ in root.walk())
        try:
            text = nbdec.decompile_proto(root, hash_names=names,
                                         hash_values=hvals, hash_text=texts)
        except nbdec.Unsupported as e:
            reasons[str(e)] += n_protos
            differ += n_protos
            continue
        except Exception as e:
            reasons[f"crash: {type(e).__name__}: {e}"] += n_protos
            differ += n_protos
            continue
        out, err = compile_source(text, tmp)
        if out is None:
            reasons[f"output did not compile: {err}"] += n_protos
            differ += n_protos
            continue
        try:
            got_root = nbdec.parse(out)
        except nbdec.BytecodeError:
            reasons["output unparseable"] += n_protos
            differ += n_protos
            continue
        want_list = list(root.walk())
        got_list = list(got_root.walk())
        if len(want_list) != len(got_list):
            reasons[f"function count {len(want_list)} -> {len(got_list)}"] += n_protos
            differ += n_protos
            continue
        for p, g in zip(want_list, got_list):
            if proto_key(g) == proto_key(p):
                exact += 1
            else:
                differ += 1
                reasons["recompiled but bytes differ"] += 1
                shape = describe_diff(p, g)
                reasons["  ^ " + shape] += 1
                if a.diff and shown < a.diff:
                    shown += 1
                    print(f"--- {label} proto {p.path}: {shape}")
                    show_diff(p, g, text)

    total = exact + differ
    print(f"{chunks} chunks, {total} protos attempted\n")
    print(f"  byte-exact : {exact:>6}  ({100*exact/max(1,total):.1f}%)")
    print(f"  not yet    : {differ:>6}\n")
    print(f"{'reason':<52} {'protos':>7}")
    for reason, n in reasons.most_common(18):
        print(f"  {reason[:50]:<50} {n:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
