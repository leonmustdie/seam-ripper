#!/usr/bin/env python3
r"""Turn a folder of .lu files into a readable source tree."""
import argparse, subprocess, sys, shutil, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import naughty_lu  # noqa: F401  (import validates it's present)
import lua_readable

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lu_dir", help="folder containing .lu files")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--luac")
    ap.add_argument("--jar", default=str(Path(__file__).parent / "unluac.jar"))
    ap.add_argument("--keep-extract", action="store_true",
                    help="keep the intermediate extract dir")
    a = ap.parse_args()

    lu_dir = Path(a.lu_dir)
    lus = sorted(lu_dir.glob("*.lu"))
    if not lus:
        sys.exit(f"no .lu files in {lu_dir}")

    extract = Path(a.out + "_extract") if a.keep_extract else \
        Path(tempfile.mkdtemp(prefix="readall_extract_"))
    extract.mkdir(parents=True, exist_ok=True)

    here = Path(__file__).resolve().parent
    print(f"extracting {len(lus)} .lu files...")
    n_ext = 0
    for lu in lus:
        r = subprocess.run(
            [sys.executable, str(here / "naughty_lu.py"), "extract",
             str(lu), "-o", str(extract)],
            capture_output=True, text=True)
        if r.returncode == 0:
            n_ext += 1
    print(f"  extracted {n_ext} ok")

    # hand the populated extract dir to the readable pipeline
    sys.argv = ["lua_readable.py", str(extract), "-o", a.out, "--jar", a.jar]
    if a.luac:
        sys.argv += ["--luac", a.luac]
    lua_readable.main()

    # manifest
    out = Path(a.out)
    ok = sorted(p.relative_to(out).as_posix()
                for p in out.rglob("*.lua") if "_FAILED" not in p.parts)
    failed = sorted(p.relative_to(out / "_FAILED").as_posix()
                    for p in (out / "_FAILED").rglob("*.lua")) \
        if (out / "_FAILED").exists() else []
    man = out / "manifest.txt"
    man.write_text(
        f"verified: {len(ok)}\nfailed: {len(failed)}\n\n"
        "== VERIFIED ==\n" + "\n".join(ok) +
        "\n\n== FAILED (do not inject) ==\n" + "\n".join(failed) + "\n",
        encoding="utf-8")
    print(f"manifest: {man}")

    if not a.keep_extract:
        shutil.rmtree(extract, ignore_errors=True)

if __name__ == "__main__":
    main()
