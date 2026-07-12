# NOTICE — lzxverify and libmspack (LGPL 2.1)

This folder documents the licensing of `lzxverify` / `lzxverify.exe`, the
independent LZX decoder that `verify_lzx.py` uses as the mandatory
independent-decode leg of Seam Ripper's ship-time container check (see
`README_SeamRipper.md` → **Verification**).

This document covers `lzxverify` only. It does not review the licensing of
Seam Ripper's other bundled third-party tools (`luac51.exe`, `luadec.exe`,
`unluac.jar`); that's a separate, still-open task.

## What's bundled and why

`lzxverify` exists to decode a compressed segment with an implementation
that isn't Seam Ripper's own (`naughty_lu.py`'s `LZXDecoder`). The point is
independence: a decoder written by the same author as the encoder can share
the encoder's bugs, and this project found that out directly, twice,
before this check existed. libmspack is a mature, independently-written
LZX decompressor, unrelated to this project's own code.

- **Source**: [kyz/libmspack](https://github.com/kyz/libmspack), the
  `cabextract/mspack/` decoder sources specifically (`lzxd.c`, `system.c`,
  and their headers).
- **License**: GNU Lesser General Public License, version 2.1. Full text in
  `COPYING.LIB` in this folder, copied unmodified from upstream.
- **Copyright**: the bundled `lzxd.c` / `system.c` / headers are Copyright
  (C) Stuart Caie and other libmspack contributors, per the notices at the
  top of each file. Nothing in this folder alters those notices.

## What's ours vs. what's upstream

- `lzxd.c`, `system.c`, `system.h`, `lzx.h`, `mspack.h`, `mszip.h`, `qtm.h`,
  `cab.h`, `macros.h`, `readbits.h`, `readhuff.h` — **unmodified libmspack
  source**, copied verbatim from upstream. Not written by this project, not
  changed by this project.
- `lzxverify.c` — **written for Seam Ripper**, not part of libmspack. It's a
  thin harness that calls libmspack's decoder through its public API
  (`lzxd_init` / `lzxd_decompress` / `lzxd_free`, `mspack_default_system`)
  the same way any program uses a library. This is the "work that uses the
  Library" the LGPL describes, as distinct from a modification of the
  Library itself.

## Why this satisfies LGPL 2.1 §6

`lzxverify` / `lzxverify.exe` are built by compiling `lzxverify.c` together
with libmspack's `lzxd.c` and `system.c` into one executable (statically,
on both platforms this project ships). The LGPL allows this kind of
combination (§5–§6), conditioned on giving downstream users the ability to
modify the Library and relink, which is satisfied here by:

1. **Complete corresponding source, unmodified and unobscured.** Every
   libmspack source file the binary was built from is in this folder,
   verbatim, not just the pieces that happen to be used.
2. **A working build script.** `build.sh` is the literal command used to
   produce the bundled binary. Anyone can edit `lzxd.c` (patch a bug, port
   to a different LZX variant, whatever) and rerun it to get a relinked
   binary, on Linux directly or cross-compiled for Windows with MinGW
   (`x86_64-w64-mingw32-gcc`, same flags, `-o lzxverify.exe`).
3. **The license text itself**, `COPYING.LIB`, travels with the source, not
   just referenced from elsewhere.
4. **No additional restriction.** `lzxverify.c`, the one file in this
   folder this project actually wrote, imposes nothing beyond what linking
   against LGPL-covered code already requires. Anyone is free to use,
   modify, or replace it.

Practically: if you're auditing this repo, or forking it, or you just don't
trust a binary you can't inspect, everything needed to verify or rebuild
`lzxverify` from source is already sitting in this folder. Nothing about it
requires contacting anyone or requesting anything separately.

## If you modify the decoder

Edit `lzxd.c` or `system.c` in this folder, then from inside it:

    sh build.sh                                              # Linux
    x86_64-w64-mingw32-gcc -DDEBUG=0 -I. -o ../lzxverify.exe \
      lzxverify.c lzxd.c system.c -static                    # Windows, cross-compiled

Replace the binary Seam Ripper already has at the repo root with the result.
`verify_lzx.py`'s `find_verifier()` picks whichever one matches the current
platform by filename, nothing else needs to change.
