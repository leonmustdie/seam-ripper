"""Build _lzxdec, the native LZX decoder, next to the tool scripts.

    py tools/lzxnative_src/build.py

Needs a C compiler setuptools can find (on Windows: Visual Studio's "Desktop
development with C++"). Writes tools/_lzxdec.<python tag>.pyd (or .so). Build
it with the same Python that runs PyInstaller: seamripper.spec bundles it when
it exists. Without it everything still works, with the slower Python decoder.
"""
import shutil
import sys
import tempfile
from pathlib import Path

from setuptools import Extension
from setuptools.dist import Distribution

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent


def main():
    ext = Extension("_lzxdec", [str(HERE / "lzxdec.c")],
                    extra_compile_args=["/O2"] if sys.platform == "win32" else ["-O2"])
    with tempfile.TemporaryDirectory() as tmp:
        dist = Distribution({"name": "_lzxdec", "ext_modules": [ext]})
        cmd = dist.get_command_obj("build_ext")
        cmd.build_lib = tmp
        cmd.build_temp = str(Path(tmp) / "obj")
        cmd.ensure_finalized()
        cmd.run()
        built = cmd.get_outputs()[0]
        for old in TOOLS.glob("_lzxdec.*"):
            if old.suffix in (".pyd", ".so"):
                old.unlink()
        dest = TOOLS / Path(built).name
        shutil.copy2(built, dest)
    print(f"built {dest}")


if __name__ == "__main__":
    main()
