#!/bin/sh
# Builds the independent LZX verifier used by verify_lzx.py.
# Sources are from libmspack (kyz/libmspack), LGPL 2.1 - see COPYING.LIB.
# Windows: build with MinGW: x86_64-w64-mingw32-gcc ... -o lzxverify.exe
gcc -DDEBUG=0 -I. -o ../lzxverify lzxverify.c lzxd.c system.c
