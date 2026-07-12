#!/usr/bin/env python3
"""
naughty_lu.py — extractor for Naughty Bear (Gold Edition, Xbox 360) .lu
resource containers ("A2M engine loadable units").

The .lu format is NOT Lua bytecode. It is a big-endian resource container:
a self-describing header, a resource record table, and a data image that is
either stored raw or compressed as an XMemCompress LZX stream (X360 XCompress).
Full format documentation in the accompanying LU_FORMAT.md.

Commands:
  info        print header / record table details
  decompress  write the raw (decompressed) data image to a file
  extract     extract every resource chunk to <out>/<file-stem>/<type>/...

Extraction extras:
  * Resource hashes are CRC32 of the lower-cased resource name. The tool
    harvests strings embedded in chunk data (FX names, object names, ...)
    and resolves hashes to names automatically. Extra candidate names can
    be supplied with --names wordlist.txt (one name per line).
  * Records with offset == 0xFFFFFFFF are external references resolved by
    hash from a dependency .lu. Pass the dependency files on the command
    line and the tool resolves them across files.

No third-party dependencies; the LZX decoder (ported from libmspack's
lzxd.c) is embedded below.
"""

import argparse
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

# ============================================================================
# LZX decompressor (port of libmspack lzxd.c, MSB bit order, no LZX-DELTA)
# ============================================================================

LZX_MIN_MATCH = 2
LZX_NUM_CHARS = 256
LZX_BLOCK_VERBATIM = 1
LZX_BLOCK_ALIGNED = 2
LZX_BLOCK_UNCOMPRESSED = 3
LZX_PRETREE_NUM_ELEMENTS = 20
LZX_ALIGNED_NUM_ELEMENTS = 8
LZX_NUM_PRIMARY_LENGTHS = 7
LZX_NUM_SECONDARY_LENGTHS = 249
LZX_FRAME_SIZE = 32768
HUFF_MAXBITS = 16

PRETREE_TABLEBITS, PRETREE_MAXSYMBOLS = 6, LZX_PRETREE_NUM_ELEMENTS
MAINTREE_TABLEBITS, MAINTREE_MAXSYMBOLS = 12, LZX_NUM_CHARS + 290 * 8
LENGTH_TABLEBITS, LENGTH_MAXSYMBOLS = 12, LZX_NUM_SECONDARY_LENGTHS + 1
ALIGNED_TABLEBITS, ALIGNED_MAXSYMBOLS = 7, LZX_ALIGNED_NUM_ELEMENTS

POSITION_SLOTS = {15: 30, 16: 32, 17: 34, 18: 36, 19: 38, 20: 42, 21: 50,
                  22: 66, 23: 98, 24: 162, 25: 290}
EXTRA_BITS = [0, 0, 0, 0] + [i // 2 - 1 for i in range(4, 36)]
POSITION_BASE = []
_b = 0
for _i in range(290):
    POSITION_BASE.append(_b)
    _b += 1 << (17 if _i >= 36 else EXTRA_BITS[_i])


class LZXError(Exception):
    pass


def _make_decode_table(nsyms, nbits, length):
    table = [0] * ((1 << nbits) + (nsyms << 1))
    pos = 0
    table_mask = 1 << nbits
    bit_mask = table_mask >> 1
    for bit_num in range(1, nbits + 1):
        for sym in range(nsyms):
            if length[sym] != bit_num:
                continue
            leaf = pos
            pos += bit_mask
            if pos > table_mask:
                return None
            table[leaf:leaf + bit_mask] = [sym] * bit_mask
        bit_mask >>= 1
    if pos == table_mask:
        return table
    for sym in range(pos, table_mask):
        table[sym] = 0xFFFF
    next_symbol = nsyms if (table_mask >> 1) < nsyms else (table_mask >> 1)
    pos <<= 16
    table_mask <<= 16
    bit_mask = 1 << 15
    for bit_num in range(nbits + 1, HUFF_MAXBITS + 1):
        for sym in range(nsyms):
            if length[sym] != bit_num:
                continue
            if pos >= table_mask:
                return None
            leaf = pos >> 16
            for fill in range(bit_num - nbits):
                if table[leaf] == 0xFFFF:
                    table[next_symbol << 1] = 0xFFFF
                    table[(next_symbol << 1) + 1] = 0xFFFF
                    table[leaf] = next_symbol
                    next_symbol += 1
                leaf = table[leaf] << 1
                if (pos >> (15 - fill)) & 1:
                    leaf += 1
            table[leaf] = sym
            pos += bit_mask
        bit_mask >>= 1
    return table if pos == table_mask else None


class LZXDecoder:
    """Decompresses one raw LZX bitstream of known output length."""

    def __init__(self, window_bits):
        if window_bits not in POSITION_SLOTS:
            raise LZXError(f"unsupported LZX window bits {window_bits}")
        self.window_bits = window_bits
        self.window_size = 1 << window_bits
        self.num_offsets = POSITION_SLOTS[window_bits] << 3

    # bitstream helpers (16-bit LE words injected MSB-first into 32-bit buffer)
    def _ensure(self, n):
        while self._bitsleft < n:
            d, p = self._data, self._pos
            if p + 1 < len(d):
                w = d[p] | (d[p + 1] << 8)
                self._pos = p + 2
            elif p < len(d):
                w = d[p]
                self._pos = p + 1
            else:
                w = 0  # zero-pad at EOF (stream is frame-exact)
            self._bitbuf |= w << (16 - self._bitsleft)
            self._bitsleft += 16

    def _readbits(self, n):
        self._ensure(n)
        v = self._bitbuf >> (32 - n)
        self._bitbuf = (self._bitbuf << n) & 0xFFFFFFFF
        self._bitsleft -= n
        return v

    def _readhuff(self, table, lens, tablebits, maxsyms):
        self._ensure(HUFF_MAXBITS)
        sym = table[self._bitbuf >> (32 - tablebits)]
        if sym >= maxsyms:
            mask = 1 << (32 - tablebits)
            while True:
                mask >>= 1
                if mask == 0:
                    raise LZXError("huffman traverse overflow")
                sym = table[(sym << 1) | (1 if self._bitbuf & mask else 0)]
                if sym < maxsyms:
                    break
        n = lens[sym]
        self._bitbuf = (self._bitbuf << n) & 0xFFFFFFFF
        self._bitsleft -= n
        return sym

    def _read_lens(self, lens, first, last):
        pre_len = [self._readbits(4) for _ in range(LZX_PRETREE_NUM_ELEMENTS)]
        pre_tbl = _make_decode_table(PRETREE_MAXSYMBOLS, PRETREE_TABLEBITS, pre_len)
        if pre_tbl is None:
            raise LZXError("bad pretree")
        x = first
        while x < last:
            z = self._readhuff(pre_tbl, pre_len, PRETREE_TABLEBITS, PRETREE_MAXSYMBOLS)
            if z == 17:
                for _ in range(self._readbits(4) + 4):
                    lens[x] = 0
                    x += 1
            elif z == 18:
                for _ in range(self._readbits(5) + 20):
                    lens[x] = 0
                    x += 1
            elif z == 19:
                y = self._readbits(1) + 4
                z = self._readhuff(pre_tbl, pre_len, PRETREE_TABLEBITS,
                                   PRETREE_MAXSYMBOLS)
                z = lens[x] - z
                if z < 0:
                    z += 17
                for _ in range(y):
                    lens[x] = z
                    x += 1
            else:
                z = lens[x] - z
                if z < 0:
                    z += 17
                lens[x] = z
                x += 1

    def decompress(self, data, out_len):
        self._data = data
        self._pos = 0
        self._bitbuf = 0
        self._bitsleft = 0
        window = bytearray(self.window_size)
        wsize = self.window_size
        window_posn = frame_posn = frame = offset = 0
        R0 = R1 = R2 = 1
        header_read = False
        intel_filesize = 0
        intel_started = False
        block_type = block_length = block_remaining = 0
        MAINTREE_len = [0] * (MAINTREE_MAXSYMBOLS + 64)
        LENGTH_len = [0] * (LENGTH_MAXSYMBOLS + 64)
        LENGTH_empty = False
        mt_tbl = lt_tbl = al_tbl = al_len = None
        out = bytearray()

        end_frame = out_len // LZX_FRAME_SIZE + 1
        while frame < end_frame:
            if not header_read:
                if self._readbits(1):
                    i = self._readbits(16)
                    j = self._readbits(16)
                    intel_filesize = (i << 16) | j
                header_read = True

            frame_size = LZX_FRAME_SIZE
            if out_len - offset < frame_size:
                frame_size = out_len - offset

            bytes_todo = frame_posn + frame_size - window_posn
            while bytes_todo > 0:
                if block_remaining == 0:
                    # CAB LZX pads odd-length uncompressed blocks with one
                    # byte; the Xbox 360 XMemCompress variant does NOT: bit
                    # reading resumes at the byte immediately after the raw
                    # data. Verified on PiP global.lu segment 7 (an embedded
                    # zlib/CFX stream spanning the block boundary inflates to
                    # eof with a valid adler32, and every record after the
                    # block verifies hash+type).
                    block_type = self._readbits(3)
                    i = self._readbits(16)
                    j = self._readbits(8)
                    block_remaining = block_length = (i << 8) | j

                    if block_type == LZX_BLOCK_ALIGNED:
                        al_len = [self._readbits(3) for _ in range(8)]
                        al_tbl = _make_decode_table(ALIGNED_MAXSYMBOLS,
                                                    ALIGNED_TABLEBITS, al_len)
                        if al_tbl is None:
                            raise LZXError("bad aligned tree")

                    if block_type in (LZX_BLOCK_ALIGNED, LZX_BLOCK_VERBATIM):
                        self._read_lens(MAINTREE_len, 0, 256)
                        self._read_lens(MAINTREE_len, 256,
                                        LZX_NUM_CHARS + self.num_offsets)
                        mt_tbl = _make_decode_table(MAINTREE_MAXSYMBOLS,
                                                    MAINTREE_TABLEBITS, MAINTREE_len)
                        if mt_tbl is None:
                            raise LZXError("bad maintree")
                        if MAINTREE_len[0xE8] != 0:
                            intel_started = True
                        self._read_lens(LENGTH_len, 0, LZX_NUM_SECONDARY_LENGTHS)
                        lt_tbl = _make_decode_table(LENGTH_MAXSYMBOLS,
                                                    LENGTH_TABLEBITS, LENGTH_len)
                        if lt_tbl is None:
                            if any(LENGTH_len[:LZX_NUM_SECONDARY_LENGTHS]):
                                raise LZXError("bad length tree")
                            LENGTH_empty = True
                        else:
                            LENGTH_empty = False
                    elif block_type == LZX_BLOCK_UNCOMPRESSED:
                        intel_started = True
                        if self._bitsleft == 0:
                            self._ensure(16)
                        self._bitsleft = 0
                        self._bitbuf = 0
                        d, p = self._data, self._pos
                        if p + 12 > len(d):
                            raise LZXError("EOF in uncompressed block header")
                        R0 = int.from_bytes(d[p:p + 4], "little")
                        R1 = int.from_bytes(d[p + 4:p + 8], "little")
                        R2 = int.from_bytes(d[p + 8:p + 12], "little")
                        self._pos = p + 12
                    else:
                        raise LZXError(f"bad block type {block_type}")

                this_run = min(block_remaining, bytes_todo)
                bytes_todo -= this_run
                block_remaining -= this_run

                if block_type in (LZX_BLOCK_ALIGNED, LZX_BLOCK_VERBATIM):
                    aligned = block_type == LZX_BLOCK_ALIGNED
                    while this_run > 0:
                        sym = self._readhuff(mt_tbl, MAINTREE_len,
                                             MAINTREE_TABLEBITS, MAINTREE_MAXSYMBOLS)
                        if sym < LZX_NUM_CHARS:
                            window[window_posn] = sym
                            window_posn += 1
                            this_run -= 1
                            continue
                        sym -= LZX_NUM_CHARS
                        match_length = sym & LZX_NUM_PRIMARY_LENGTHS
                        if match_length == LZX_NUM_PRIMARY_LENGTHS:
                            if LENGTH_empty:
                                raise LZXError("LENGTH symbol needed but tree empty")
                            match_length += self._readhuff(
                                lt_tbl, LENGTH_len, LENGTH_TABLEBITS, LENGTH_MAXSYMBOLS)
                        match_length += LZX_MIN_MATCH
                        slot = sym >> 3
                        if slot == 0:
                            match_offset = R0
                        elif slot == 1:
                            match_offset = R1
                            R1 = R0
                            R0 = match_offset
                        elif slot == 2:
                            match_offset = R2
                            R2 = R0
                            R0 = match_offset
                        else:
                            extra = 17 if slot >= 36 else EXTRA_BITS[slot]
                            match_offset = POSITION_BASE[slot] - 2
                            if extra >= 3 and aligned:
                                if extra > 3:
                                    match_offset += self._readbits(extra - 3) << 3
                                match_offset += self._readhuff(
                                    al_tbl, al_len, ALIGNED_TABLEBITS, ALIGNED_MAXSYMBOLS)
                            elif extra:
                                match_offset += self._readbits(extra)
                            R2 = R1
                            R1 = R0
                            R0 = match_offset
                        if window_posn + match_length > wsize:
                            raise LZXError("match ran over window wrap")
                        if match_offset > window_posn:
                            j = match_offset - window_posn
                            if j > wsize:
                                raise LZXError("match offset beyond window")
                            src = wsize - j
                            i = match_length
                            if j < i:
                                i -= j
                                while j > 0:
                                    window[window_posn] = window[src]
                                    window_posn += 1
                                    src += 1
                                    j -= 1
                                src = 0
                            while i > 0:
                                window[window_posn] = window[src]
                                window_posn += 1
                                src += 1
                                i -= 1
                        else:
                            src = window_posn - match_offset
                            if match_offset >= match_length:
                                window[window_posn:window_posn + match_length] = \
                                    window[src:src + match_length]
                                window_posn += match_length
                            else:
                                for _ in range(match_length):
                                    window[window_posn] = window[src]
                                    window_posn += 1
                                    src += 1
                        this_run -= match_length
                else:  # uncompressed
                    d, p = self._data, self._pos
                    if p + this_run > len(d):
                        raise LZXError("EOF in uncompressed block")
                    window[window_posn:window_posn + this_run] = d[p:p + this_run]
                    self._pos = p + this_run
                    window_posn += this_run
                    this_run = 0

                if this_run < 0:
                    if -this_run > block_remaining:
                        raise LZXError("overrun past end of block")
                    block_remaining -= -this_run

            if window_posn - frame_posn != frame_size:
                raise LZXError("decode beyond output frame limits")

            # re-align bitstream to a 16-bit boundary
            if self._bitsleft > 0:
                self._ensure(16)
            if self._bitsleft & 15:
                n = self._bitsleft & 15
                self._bitbuf = (self._bitbuf << n) & 0xFFFFFFFF
                self._bitsleft -= n

            frame_data = window[frame_posn:frame_posn + frame_size]
            if intel_started and intel_filesize and frame < 32768 and frame_size > 10:
                frame_data = bytearray(frame_data)
                curpos = offset
                dpos, dend = 0, frame_size - 10
                while dpos < dend:
                    if frame_data[dpos] != 0xE8:
                        dpos += 1
                        curpos += 1
                        continue
                    dpos += 1
                    a = int.from_bytes(frame_data[dpos:dpos + 4], "little", signed=True)
                    if -curpos <= a < intel_filesize:
                        rel = a - curpos if a >= 0 else a + intel_filesize
                        frame_data[dpos:dpos + 4] = (rel & 0xFFFFFFFF).to_bytes(4, "little")
                    dpos += 4
                    curpos += 5
            out += frame_data
            offset += frame_size
            frame_posn += frame_size
            frame += 1
            if window_posn == wsize:
                window_posn = 0
            if frame_posn == wsize:
                frame_posn = 0
        return bytes(out[:out_len])


# ============================================================================
# XMemCompress stream framing
# ============================================================================

def parse_xmem_frames(data, image_size):
    """Split an XMemCompress stream into (uncompressed_size, payload) frames.
    Frame header: u16 BE compressed size (uncompressed = 0x8000), or the
    escape 0xFF, u16 BE uncompressed size, u16 BE compressed size."""
    frames = []
    pos = 0
    total = 0
    while total < image_size:
        if pos >= len(data):
            raise ValueError("XMemCompress chain ran past end of data")
        if data[pos] == 0xFF:
            if pos + 5 > len(data):
                raise ValueError("truncated escape frame header")
            un = struct.unpack_from(">H", data, pos + 1)[0]
            cm = struct.unpack_from(">H", data, pos + 3)[0]
            pos += 5
        else:
            cm = struct.unpack_from(">H", data, pos)[0]
            un = min(LZX_FRAME_SIZE, image_size - total)
            pos += 2
        if cm == 0 or pos + cm > len(data):
            raise ValueError(f"bad frame at {pos:#x} (csize {cm:#x})")
        frames.append((un, data[pos:pos + cm]))
        pos += cm
        total += un
    if total != image_size:
        raise ValueError(f"frame chain total {total:#x} != image size {image_size:#x}")
    return frames, pos


def xmem_lzx_decompress(data, image_size, window_size):
    frames, _ = parse_xmem_frames(data, image_size)
    stream = b"".join(payload for _, payload in frames)
    wbits = window_size.bit_length() - 1
    candidates = [wbits] if (1 << wbits) == window_size and wbits in POSITION_SLOTS \
        else list(range(15, 22))
    last_err = None
    for wb in candidates + [w for w in range(15, 22) if w not in candidates]:
        try:
            return LZXDecoder(wb).decompress(stream, image_size)
        except LZXError as e:
            last_err = e
    raise LZXError(f"could not decompress with any window size: {last_err}")


def lzx_store_segment(data):
    """Encode a pool segment as a valid XMemCompress LZX stream that stores
    the data uncompressed: one LZX uncompressed block spanning the segment,
    framed in 32 KB frames. This is exactly the framing retail PiP ships for
    incompressible front-end segments (frame headers 0x8010 / 0x8000), so
    the game engine demonstrably loads it. ~20 bytes overhead per segment.
    """
    n = len(data)
    bits = "0" + "011" + f"{n:024b}"          # intel header bit, type 3, len
    bits += "0" * (-len(bits) % 16)
    hdr = b"".join(struct.pack("<H", int(bits[i:i + 16], 2))
                   for i in range(0, len(bits), 16))
    lead = hdr + struct.pack("<3I", 1, 1, 1)  # stored R0 R1 R2
    frames = []
    pos = 0
    while pos < n:
        take = min(0x8000, n - pos)
        payload = (lead if pos == 0 else b"") + data[pos:pos + take]
        frames.append(struct.pack(">H", len(payload)) + payload)
        pos += take
    return b"".join(frames)


def rebuild_luh(template, new_chunks, mode="raw"):
    """Rebuild an LUH container from a template LuFile, replacing the chunk
    data of the records given in new_chunks ({record index: bytes}).

    LAYOUT-PRESERVING: the original image is kept byte-for-byte; untouched
    records never move (retail chunks cross-reference each other by absolute
    image offset, and several chunk types require 0x1000-aligned offsets, so
    re-flowing the layout corrupts the file even when every chunk is intact).
    A replaced chunk stays at its original offset when it fits its slot
    (original extent plus trailing padding up to the next record); otherwise
    it is appended at the end of the image at 0x1000 alignment and only its
    own record offset changes.

    mode="raw" writes segments as raw passthrough (csize == usize, the
    engine's memcpy convention — verified in-game); mode="store" wraps them
    as LZX uncompressed-block streams (csize slightly > usize; the engine
    REJECTS these — kept for experiments only). Returns the file bytes.
    """
    if not getattr(template, "is_luh", False):
        raise ValueError("rebuild_luh needs an LUH-container template")

    img = bytearray(template.image)
    recs = sorted(template.records, key=lambda r: r.offset)
    next_off = {recs[i].index: (recs[i + 1].offset if i + 1 < len(recs)
                                else len(img))
                for i in range(len(recs))}

    entries = {}     # index -> (hash, type, size, offset, flags)
    for r in template.records:
        data = new_chunks.get(r.index)
        if data is None:
            entries[r.index] = (r.hash, r.type, r.size, r.offset, r.flags)
            continue
        slot = next_off[r.index] - r.offset
        if len(data) <= slot:
            img[r.offset:r.offset + len(data)] = data
            img[r.offset + len(data):r.offset + slot] = \
                b"\xDF" * (slot - len(data))
            entries[r.index] = (r.hash, r.type, len(data), r.offset, r.flags)
        else:
            if len(img) % 0x1000:
                img += b"\xDF" * (0x1000 - len(img) % 0x1000)
            off = len(img)
            img += data
            entries[r.index] = (r.hash, r.type, len(data), off, r.flags)
    img = bytes(img)

    window = template.lzx_window or 0x100000
    segs = []
    for pos in range(0, len(img), window):
        part = img[pos:pos + window]
        segs.append(part if mode == "raw" else lzx_store_segment(part))

    out = bytearray()
    out += LUH_MAGIC
    out += template.raw[4:0xC]
    out += struct.pack(">I", len(template.records))
    for r in template.records:
        h, t, sz, off, fl = entries[r.index]
        out += struct.pack(">6I", h, t, 0xFFFFFFFF, sz, off, fl)
        out += b"\x00" * 15
    out += struct.pack(">5I", len(img), 1, len(img), window, len(segs))
    for sg in segs:
        out += struct.pack(">I", len(sg))
    for sg in segs:
        out += sg
    return bytes(out)


def u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


class LuRecord:
    __slots__ = ("index", "hash", "type", "size", "offset", "flags")

    def __init__(self, index, h, t, size, offset, flags):
        self.index = index
        self.hash = h
        self.type = t
        self.size = size
        self.offset = offset
        self.flags = flags

    @property
    def external(self):
        return self.offset == 0xFFFFFFFF or (self.flags >> 8) & 0x01

    @property
    def pool(self):
        return POOL_NAMES.get(self.flags >> 24, f"pool_{self.flags >> 24:02x}")

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.type, f"type_{self.type:08x}")


# Human-readable directory names for known chunk types. Anything not listed
# falls back to type_<hex> (see LuRecord.type_name), which is a fine, stable
# name — the map is purely cosmetic for extraction output.
TYPE_NAMES = {
    0x04000001: "unk_04000001",     # skeleton
    0x04B00000: "animation",        # scripts (bytecode NB1 / source PiP)
    0x14200007: "texture",          # NB1 texture
    0x34200007: "type_34200007",    # PiP texture
    0x04000007: "mesh_buffers",     # NB1 mesh
    0x34000007: "type_34000007",    # PiP mesh
    0x04D00013: "type_04d00013",    # PiP string table
    0x04D00001: "type_04d00001",    # PiP Scaleform UI
}

# Pool names keyed by the high byte of the record flags field.
POOL_NAMES = {0x00: "pool_00"}

# x36 header bytes 1:4 identify the target platform the container was built
# for. Every real NB1 file seen so far is Xbox 360 ("x36" itself, matching
# the magic); this map exists so an unrecognised tag degrades to a labeled
# warning instead of a crash, in case a PC/PS3 build ever surfaces.
LU_PLATFORM_TAGS = {
    b"x36": "Xbox 360 (x36)",
}

LUH_MAGIC = b"\x05LUH"


class LuFile:
    """NB1 x36 or PiP LUH container. The format is auto-detected from the
    magic; both expose the same records/image/chunk interface."""

    def __init__(self, path):
        self.path = Path(path)
        d = self.path.read_bytes()
        self.raw = d
        if d[:4] == LUH_MAGIC:
            self._init_luh(d)
            return
        if d[0] != 0x03:
            raise ValueError(f"{path}: bad version byte {d[0]:#x} "
                             f"(not an x36 or LUH container)")
        self.platform = LU_PLATFORM_TAGS.get(d[1:4], f"unknown ({d[1:4]!r})")
        if d[1:4] not in LU_PLATFORM_TAGS:
            print(f"warning: {path}: unrecognised platform tag {d[1:4]!r}; "
                  f"this tool was validated on Xbox 360 files", file=sys.stderr)
        if d[0x17:0x20] != b"--\nITCRAP":
            print(f"warning: {path}: missing '--\\nITCRAP' marker", file=sys.stderr)
        self.version = u32(d, 4)
        self.build_hash = u32(d, 8)
        self.dep_count = d[0x14]

        # dependency names
        self.deps = []
        dep_rel = u32(d, 0x24)
        if self.dep_count and dep_rel != 0xFFFFFFFF:
            p = 0x20 + dep_rel
            for _ in range(self.dep_count):
                e = d.index(b"\0", p)
                self.deps.append(d[p:e].decode("ascii", "replace"))
                p = e + 1

        # pool info
        pi = 0x20 + u32(d, 0x34)
        self.codec = u32(d, pi)
        self.image_size = u32(d, pi + 4)
        self.lzx_window = u32(d, pi + 8)
        self.segment_count = u32(d, pi + 0xC)
        sizes_rel = u32(d, pi + 0x10)
        self.compressed = self.codec == 2 and sizes_rel != 0xFFFFFFFF
        if self.compressed:
            count2 = u32(d, pi + 0x14)
            if count2 != self.segment_count:
                print(f"warning: {path}: segment count fields disagree "
                      f"({self.segment_count} vs {count2})", file=sys.stderr)
            so = 0x20 + sizes_rel
            self.segment_sizes = [u32(d, so + 4 * i)
                                  for i in range(self.segment_count)]
            self.stored_size = sum(self.segment_sizes)
        else:
            self.segment_sizes = []
            self.stored_size = self.image_size

        # footer: record table offset + count
        fo = 0x20 + u32(d, 0x38)
        table = 0x20 + u32(d, fo)
        count = u32(d, fo + 4)

        # data region
        self.data_base = 0x20 + u32(d, 0x40)
        actual = len(d) - self.data_base
        if actual != self.stored_size:
            print(f"warning: {path}: stored data {actual:#x} != header stored size "
                  f"{self.stored_size:#x}", file=sys.stderr)

        self.records = []
        for i in range(count):
            o = table + i * 0x18
            h, t, marker, sz, off, flags = struct.unpack_from(">6I", d, o)
            if marker != 0xFFFFFFFF:
                print(f"warning: {path}: record {i} pointer placeholder is "
                      f"{marker:#010x}, expected 0xffffffff", file=sys.stderr)
            self.records.append(LuRecord(i, h, t, sz, off, flags))

        self.by_hash = {}
        for r in self.records:
            if not r.external:
                self.by_hash.setdefault(r.hash, r)

        self._image = None

    def _init_luh(self, d):
        """PiP LUH container (magic 05 'LUH'), big-endian throughout:
        0x0C u32 record count; 0x10 record table with 39-byte entries
        {hash, type, ffffffff, size, image_offset, flags, 15 zero bytes};
        then {u32 total_image_size, u32 pool_count, u32 pool_image_size,
        u32 segment_uncompressed_size, u32 segment_count,
        u32 compressed_sizes[n]} and the XMemCompress LZX segments
        (window = segment size, 1 MB observed -> wbits 20)."""
        self.is_luh = True
        self.platform = "LUH v5 (Panic in Paradise)"
        self.version = u32(d, 4)
        self.build_hash = 0
        self.dep_count = 0
        self.deps = []
        count = u32(d, 0x0C)
        table = 0x10
        self.records = []
        for i in range(count):
            o = table + i * 39
            h, t, marker, sz, off, flags = struct.unpack_from(">6I", d, o)
            if marker != 0xFFFFFFFF:
                print(f"warning: {self.path}: record {i} pointer placeholder "
                      f"is {marker:#010x}, expected 0xffffffff",
                      file=sys.stderr)
            self.records.append(LuRecord(i, h, t, sz, off, flags))
        pi = table + count * 39
        self.image_size = u32(d, pi)
        pool_count = u32(d, pi + 4)
        if pool_count != 1:
            print(f"warning: {self.path}: {pool_count} pools (only 1 pool "
                  f"has been observed; parsing may be wrong)", file=sys.stderr)
        self.pool_image_size = u32(d, pi + 8)
        self.lzx_window = u32(d, pi + 0xC)          # segment size = window
        self.segment_count = u32(d, pi + 0x10)
        so = pi + 0x14
        self.segment_sizes = [u32(d, so + 4 * i)
                              for i in range(self.segment_count)]
        self.stored_size = sum(self.segment_sizes)
        self.data_base = so + 4 * self.segment_count
        self.codec = 2
        self.compressed = True
        actual = len(d) - self.data_base
        if actual != self.stored_size:
            print(f"warning: {self.path}: stored data {actual:#x} != sum of "
                  f"segment sizes {self.stored_size:#x}", file=sys.stderr)
        self.by_hash = {}
        for r in self.records:
            if not r.external:
                self.by_hash.setdefault(r.hash, r)
        self.undecoded = []          # [(image_start, image_end)] zero-filled
        self._image = None

    def _decode_luh_image(self):
        data = self.raw[self.data_base:]
        window = self.lzx_window or 0x100000
        parts = []
        pos = 0
        remaining = self.image_size
        for i, sz in enumerate(self.segment_sizes):
            target = min(window, remaining)
            seg = data[pos:pos + sz]
            try:
                if sz == target:      # stored raw (incompressible)
                    parts.append(seg)
                else:
                    parts.append(xmem_lzx_decompress(seg, target, window))
            except (LZXError, ValueError) as e:
                start = self.image_size - remaining
                self.undecoded.append((start, start + target))
                print(f"warning: {self.path}: segment {i} failed to decode "
                      f"({e}); zero-filling {target:#x} bytes at image "
                      f"{start:#x}", file=sys.stderr)
                parts.append(b"\x00" * target)
            pos += sz
            remaining -= target
        img = b"".join(parts)
        if len(img) != self.image_size:
            raise ValueError(f"{self.path}: decompressed {len(img):#x} bytes, "
                             f"expected {self.image_size:#x}")
        return img

    @property
    def image(self):
        """The decompressed data image (lazy). Compressed images are split
        into window-size slices, each an independent XMemCompress stream."""
        if self._image is None:
            if getattr(self, "is_luh", False):
                self._image = self._decode_luh_image()
                return self._image
            data = self.raw[self.data_base:]
            if self.compressed:
                window = self.lzx_window or 0x100000
                parts = []
                pos = 0
                remaining = self.image_size
                for i, sz in enumerate(self.segment_sizes):
                    target = min(window, remaining)
                    if sz == target:  # segment stored raw (incompressible)
                        parts.append(data[pos:pos + sz])
                    else:
                        parts.append(xmem_lzx_decompress(data[pos:pos + sz],
                                                         target, window))
                    pos += sz
                    remaining -= target
                self._image = b"".join(parts)
                if len(self._image) != self.image_size:
                    raise ValueError(
                        f"{self.path}: decompressed {len(self._image):#x} "
                        f"bytes, expected {self.image_size:#x}")
            else:
                self._image = data[:self.image_size]
        return self._image

    def chunk(self, rec):
        if rec.external:
            return None
        return self.image[rec.offset:rec.offset + rec.size]


# ============================================================================
# name resolution: hash = CRC32(lowercase(name))
# ============================================================================

def crc32_name(name):
    return zlib.crc32(name.lower().encode("ascii", "ignore")) & 0xFFFFFFFF


def harvest_names(lu_files, extra_words=()):
    """Build {crc32: name} from strings inside the data images plus
    any extra candidate words."""
    cands = set(extra_words)
    for lu in lu_files:
        cands.add(lu.path.stem)
        try:
            img = lu.image
        except Exception:
            continue
        for m in re.finditer(rb"[\x20-\x7e]{3,64}", img):
            s = m.group().decode()
            cands.add(s)
            for part in re.split(r"[^\w\-.]+", s):
                if len(part) >= 3:
                    cands.add(part)
    table = {}
    for c in cands:
        table[crc32_name(c)] = c.lower()
    return table


# ============================================================================
# commands
# ============================================================================

def cmd_info(args):
    for path in args.files:
        lu = LuFile(path)
        print(f"== {lu.path.name} ==")
        print(f"  platform     : {lu.platform}")
        print(f"  version      : {lu.version:#010x}   build hash: {lu.build_hash:#010x}")
        print(f"  dependencies : {lu.deps if lu.deps else '(none)'}")
        print(f"  data region  : file offset {lu.data_base:#x}, "
              f"{lu.stored_size:#x} bytes stored")
        if lu.compressed:
            print(f"  compression  : XMemCompress LZX, window {lu.lzx_window:#x}, "
                  f"{lu.segment_count} segment(s), image {lu.image_size:#x} bytes "
                  f"({lu.stored_size * 100 // lu.image_size}% of original)")
        else:
            print(f"  compression  : none (raw image, {lu.image_size:#x} bytes)")
        print(f"  records      : {len(lu.records)}")
        tc = Counter(r.type_name for r in lu.records)
        for t, n in tc.most_common():
            print(f"      {n:4d} x {t}")
        if args.verbose:
            print(f"  {'idx':>4} {'hash':8} {'type':>20} {'size':>9} "
                  f"{'offset':>10} {'pool':>6} ext")
            for r in lu.records:
                off = "external" if r.external else f"{r.offset:#x}"
                print(f"  {r.index:>4} {r.hash:08x} {r.type_name:>20} "
                      f"{r.size:>9,} {off:>10} {r.pool:>6} "
                      f"{'*' if r.external else ''}")
        print()


def cmd_decompress(args):
    lu = LuFile(args.file)
    out = Path(args.out) if args.out else lu.path.with_suffix(".image.bin")
    out.write_bytes(lu.image)
    state = "decompressed" if lu.compressed else "copied raw"
    print(f"{state} {len(lu.image):#x} bytes -> {out}")


def cmd_extract(args):
    lus = [LuFile(p) for p in args.files]
    extra = []
    if args.names:
        extra = [w.strip() for w in Path(args.names).read_text().splitlines()
                 if w.strip()]
    names = harvest_names(lus, extra)

    out_root = Path(args.out) if args.out else Path("lu_extracted")
    grand = Counter()

    for lu in lus:
        out_dir = out_root / lu.path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        counts = Counter()
        manifest = []

        for r in lu.records:
            name = names.get(r.hash, "")
            base = f"{r.index:04d}_{name or r.hash.to_bytes(4, 'big').hex()}"
            source = "local"
            data = lu.chunk(r)
            if data is None:
                # external: resolve by hash in the other files
                src = next((o for o in lus if o is not lu and r.hash in o.by_hash),
                           None)
                if src is not None:
                    data = src.chunk(src.by_hash[r.hash])
                    source = f"external:{src.path.name}"
                else:
                    source = "external:unresolved"
            if data is not None:
                dest = out_dir / r.type_name
                dest.mkdir(exist_ok=True)
                (dest / (base + ".bin")).write_bytes(data)
                counts[source.split(":")[0]] += 1
            else:
                counts["unresolved"] += 1
            manifest.append((r, name, source))

        with open(out_dir / "manifest.tsv", "w") as f:
            f.write(f"# source: {lu.path.name}  platform: {lu.platform}  "
                    f"deps: {','.join(lu.deps) or '-'}\n")
            f.write("index\thash\tname\ttype\ttype_name\tsize\timage_offset\t"
                    "flags\tpool\tsource\n")
            for r, name, source in manifest:
                off = "" if r.external else f"{r.offset:#x}"
                f.write(f"{r.index}\t{r.hash:08x}\t{name}\t{r.type:08x}\t"
                        f"{r.type_name}\t{r.size}\t{off}\t{r.flags:08x}\t"
                        f"{r.pool}\t{source}\n")

        named = sum(1 for _, name, _ in manifest if name)
        print(f"{lu.path.name}: {len(lu.records)} records -> {out_dir}/ "
              f"(local {counts['local']}, external {counts['external']}, "
              f"unresolved {counts['unresolved']}; {named} names resolved)")
        grand.update(counts)

    print(f"total: {sum(grand.values())} records "
          f"({grand['local']} local, {grand['external']} external, "
          f"{grand['unresolved']} unresolved)")


def main():
    ap = argparse.ArgumentParser(
        description="Naughty Bear (X360) .lu resource container tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="show container details")
    p.add_argument("files", nargs="+")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="list every record")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("decompress", help="dump the raw decompressed data image")
    p.add_argument("file")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_decompress)

    p = sub.add_parser("extract", help="extract all resource chunks")
    p.add_argument("files", nargs="+",
                   help=".lu files (list dependencies too so external "
                        "references resolve)")
    p.add_argument("-o", "--out", help="output directory (default lu_extracted)")
    p.add_argument("--names", help="wordlist of candidate resource names "
                                   "for hash resolution")
    p.set_defaults(func=cmd_extract)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
