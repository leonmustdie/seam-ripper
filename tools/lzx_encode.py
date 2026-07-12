#!/usr/bin/env python3
"""
lzx_encode.py — an LZX/XMemCompress ENCODER matching naughty_lu.py's decoder
bit-for-bit, so real game engines (verified: the PiP retail engine, via
naughty_lu.LZXDecoder) can load what this writes.

This is the write-side counterpart needed to safely re-compress x36 (NB1)
pools after a script edit — naughty_lu.py could only decompress before this.

Design: correctness over compression ratio. Every block is LZX_BLOCK_VERBATIM
(no aligned-offset tree — one less thing to get wrong), matches come from a
simple greedy LZ77 search (hash-chained), and Huffman trees are standard
length-limited canonical codes. This will not match retail's compression
ratio, but the output is a byte-exact XMemCompress stream: round-tripping it
through naughty_lu.LZXDecoder reproduces the original input exactly (self-
tested against real retail pool data from NB1's global.lu/levelcommon.lu).

Frame/pool framing (u16 BE compressed-size headers, 0xFF escape frames, the
Xbox 360 no-pad-after-uncompressed-block quirk) is unaffected by this file —
that's naughty_lu.py's parse_xmem_frames/rebuild machinery, reused as-is.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import (                                    # noqa: E402
    LZX_MIN_MATCH, LZX_NUM_CHARS, LZX_BLOCK_VERBATIM,
    LZX_PRETREE_NUM_ELEMENTS, LZX_NUM_PRIMARY_LENGTHS,
    LZX_NUM_SECONDARY_LENGTHS, LZX_FRAME_SIZE, HUFF_MAXBITS,
    MAINTREE_MAXSYMBOLS, LENGTH_MAXSYMBOLS,
    POSITION_SLOTS, EXTRA_BITS, POSITION_BASE,
)


class BitWriter:
    """Exact mirror of LZXDecoder's bit reader. Reader buffers 16-bit LE
    words MSB-first into a 32-bit register and consumes from the top; net
    effect is a plain MSB-first integer per 16-bit unit, written little-
    endian. push(value, n) appends n bits (value's own bits, MSB-first)."""

    def __init__(self):
        self.acc = 0
        self.nbits = 0
        self.out = bytearray()

    def push(self, value, n):
        if n == 0:
            return
        self.acc = (self.acc << n) | (value & ((1 << n) - 1))
        self.nbits += n
        while self.nbits >= 16:
            self.nbits -= 16
            word = (self.acc >> self.nbits) & 0xFFFF
            self.acc &= (1 << self.nbits) - 1
            self.out += struct.pack("<H", word)

    def align_word(self):
        if self.nbits:
            self.push(0, 16 - self.nbits)

    def getvalue(self):
        self.align_word()
        return bytes(self.out)


def canonical_codes(lengths, maxbits=HUFF_MAXBITS):
    """Code assignment matching _make_decode_table's implicit assumption:
    process lengths 1..max, symbols in increasing index order per length."""
    codes = [0] * len(lengths)
    code = 0
    for bit_num in range(1, maxbits + 1):
        for sym, ln in enumerate(lengths):
            if ln == bit_num:
                codes[sym] = code
                code += 1
        code <<= 1
    return codes


def _huffman_lengths_clean(freqs, maxbits, allow_empty=False):
    """Standard Huffman lengths from frequencies, then length-limit repair.

    allow_empty: true ONLY for the LENGTH tree. Cross-checked against
    libmspack's lzxd.c (an independent, real-world LZX decoder — cabextract
    genuinely rejected our first attempt at this, which is what sent us to
    it): BUILD_TABLE_MAYBE_EMPTY is used *exclusively* for the LENGTH tree,
    explicitly tolerating a fully-empty (zero active symbols) table as
    normal — every other tree (PRETREE, MAINTREE, ALIGNED) always uses the
    strict BUILD_TABLE, which requires a complete (Kraft-sum-1) code. Since
    a simple encoder frequently has zero matches needing extra length, the
    LENGTH tree is often legitimately empty; forcing 2 dummy symbols into
    it every time (as this function previously did unconditionally) was
    itself a source of divergence from a real decoder. Note the leniency
    covers ONLY true emptiness (0 active) — exactly 1 active symbol is
    still a hard error even for LENGTH, so it still needs padding here.
    """
    freqs = list(freqs)
    n = len(freqs)
    active = [i for i, f in enumerate(freqs) if f > 0]
    if allow_empty and len(active) == 0:
        return [0] * n
    if len(active) < 2:
        unused = [i for i in range(n) if freqs[i] == 0]
        pad = [i for i in unused if i not in active][:2 - len(active)]
        # extremely small alphabets (n<2) can't be padded; only the
        # 20-symbol pretree, 256+ symbol main tree, and 249-symbol length
        # tree ever call this, so n>=20 always holds in practice.
        for k, i in enumerate(pad):
            freqs[i] = 1 + k  # differing weights -> differing lengths

    import heapq
    items = [(f, i) for i, f in enumerate(freqs) if f > 0]
    if not items:
        return [0] * n
    if len(items) == 1:
        # still possible if n==1 (shouldn't happen for our alphabets)
        lens = [0] * n
        lens[items[0][1]] = 1
        return lens
    heap = []
    counter = 0
    for f, i in items:
        heap.append((f, counter, ("leaf", i)))
        counter += 1
    heapq.heapify(heap)
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        counter += 1
        heapq.heappush(heap, (f1 + f2, counter, ("node", n1, n2)))
    root = heap[0][2]
    lens = [0] * n

    def walk(node, depth):
        if node[0] == "leaf":
            lens[node[1]] = max(depth, 1)
        else:
            walk(node[1], depth + 1)
            walk(node[2], depth + 1)
    walk(root, 0)

    while max(lens[s] for _, s in items) > maxbits:
        over = max(range(n), key=lambda s: lens[s] if freqs[s] > 0 else -1)
        lens[over] -= 1
        under = sorted((s for s in range(n) if freqs[s] > 0 and
                        lens[s] < maxbits and s != over),
                       key=lambda s: -lens[s])
        if not under:
            lens[over] += 1
            break
        lens[under[0]] += 1
    return _fix_kraft(lens, freqs, maxbits)


def _fix_kraft(lens, freqs, maxbits):
    active = [i for i in range(len(lens)) if freqs[i] > 0]
    if not active:
        return lens
    kraft = sum(2.0 ** -lens[i] for i in active)
    guard = 0
    while kraft > 1.0 and guard < 10000:
        guard += 1
        i = min(active, key=lambda s: lens[s])
        lens[i] = min(lens[i] + 1, maxbits)
        kraft = sum(2.0 ** -lens[i] for i in active)
    return lens


def write_lens_array(bw, lengths, first, last, running):
    """Emit one tree's code-length array via the pretree, with zero-run RLE
    (codes 17/18). `running` holds the reader's persistent `lens[x]` state
    (naughty_lu allocates MAINTREE_len/LENGTH_len once and never clears them
    between blocks; each new value is (running[x] - delta) mod 17)."""
    span = list(range(first, last))
    tokens = []
    i, n = 0, len(span)
    while i < n:
        idx = span[i]
        if lengths[idx] == 0:
            j = i
            while j < n and lengths[span[j]] == 0:
                j += 1
            run = j - i
            run_positions = span[i:j]
            while run >= 20:
                take = min(run, 51)
                tokens.append(("run18", take, run_positions[:take]))
                run_positions = run_positions[take:]
                run -= take
                i += take
            while run >= 4:
                take = min(run, 19)
                tokens.append(("run17", take, run_positions[:take]))
                run_positions = run_positions[take:]
                run -= take
                i += take
            while run > 0:
                tokens.append(("val", span[i], 0))
                run -= 1
                i += 1
        else:
            tokens.append(("val", idx, lengths[idx]))
            i += 1

    freqs = [0] * LZX_PRETREE_NUM_ELEMENTS
    for t in tokens:
        if t[0] == "val":
            _, idx, newv = t
            freqs[(running[idx] - newv) % 17] += 1
        elif t[0] == "run17":
            freqs[17] += 1
        else:
            freqs[18] += 1
    pre_lens = _huffman_lengths_clean(freqs, 16)
    for i in range(LZX_PRETREE_NUM_ELEMENTS):
        bw.push(pre_lens[i], 4)
    pre_codes = canonical_codes(pre_lens, 16)

    for t in tokens:
        if t[0] == "val":
            _, idx, newv = t
            d = (running[idx] - newv) % 17
            bw.push(pre_codes[d], pre_lens[d])
            running[idx] = newv
        elif t[0] == "run17":
            bw.push(pre_codes[17], pre_lens[17])
            bw.push(t[1] - 4, 4)
            # decoder zeroes lens[x] for EVERY position in a run — mirror
            # that here so later blocks' deltas are computed against the
            # same "previous value" the decoder actually holds.
            for p in t[2]:
                running[p] = 0
        else:
            bw.push(pre_codes[18], pre_lens[18])
            bw.push(t[1] - 20, 5)
            for p in t[2]:
                running[p] = 0


def _find_matches(data, window_base, pos_start, pos_end, chain_state):
    """Greedy longest-match search, 3-byte hash chain. Matches may reach
    back before pos_start (into earlier frames of the same LZX window).
    chain_state = [head, prev] persists across calls within one compress()
    so each byte is hashed exactly once instead of rebuilding per frame."""
    HASH_BITS = 15
    HASH_SIZE = 1 << HASH_BITS
    MIN_MATCH = LZX_MIN_MATCH
    MAX_MATCH = LZX_NUM_PRIMARY_LENGTHS + LZX_NUM_SECONDARY_LENGTHS - 1 + LZX_MIN_MATCH
    head, prev = chain_state

    def h3(p):
        if p + 3 > len(data):
            return None
        return ((data[p] << 16) | (data[p + 1] << 8) | data[p + 2]) & (HASH_SIZE - 1)

    tokens = []
    p = pos_start
    while p < pos_end:
        best_len, best_off = 0, 0
        hh = h3(p)
        if hh is not None:
            cand = head[hh]
            tries = 0
            while cand is not None and cand >= 0 and tries < 32:
                tries += 1
                if cand < window_base:
                    break
                maxlen = min(MAX_MATCH, pos_end - p)
                ln = 0
                while ln < maxlen and data[cand + ln] == data[p + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_off = ln, p - cand
                cand = prev.get(cand, -1)
        if best_len >= MIN_MATCH:
            tokens.append(("match", best_len, best_off))
            end = p + best_len
            while p < end:
                hh2 = h3(p)
                if hh2 is not None:
                    prev[p] = head[hh2]
                    head[hh2] = p
                p += 1
        else:
            tokens.append(("lit", data[p]))
            if hh is not None:
                prev[p] = head[hh]
                head[hh] = p
            p += 1
    return tokens


def _slot_for_offset(off):
    """Which position slot (>=3) encodes this absolute offset, plus extra
    bits/value. Inverse of decoder's match_offset = POSITION_BASE[slot]-2+extra."""
    target = off + 2
    lo, hi, slot = 0, len(POSITION_BASE) - 1, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if POSITION_BASE[mid] <= target:
            slot = mid
            lo = mid + 1
        else:
            hi = mid - 1
    extra_bits = 17 if slot >= 36 else EXTRA_BITS[slot]
    return slot, extra_bits, target - POSITION_BASE[slot]


def _encode_block(bw, tokens, num_offsets, maintree_running, length_running, rcache):
    R0, R1, R2 = rcache
    main_syms = []
    for tok in tokens:
        if tok[0] == "lit":
            main_syms.append(("lit", tok[1]))
            continue
        _, mlen, moff = tok
        ml = mlen - LZX_MIN_MATCH
        if moff == R0:
            slot = 0
        elif moff == R1:
            slot = 1
            R1, R0 = R0, R1
        elif moff == R2:
            slot = 2
            R2, R0 = R0, R2
        else:
            slot, extra_bits, extra_val = _slot_for_offset(moff)
            R2, R1, R0 = R1, R0, moff
            main_syms.append(("match", slot, ml, extra_bits, extra_val))
            continue
        main_syms.append(("match", slot, ml, None, None))
    rcache[0], rcache[1], rcache[2] = R0, R1, R2

    freqs = [0] * (LZX_NUM_CHARS + num_offsets)
    for e in main_syms:
        if e[0] == "lit":
            freqs[e[1]] += 1
        else:
            _, slot, ml = e[0], e[1], e[2]
            lenslot = min(ml, LZX_NUM_PRIMARY_LENGTHS)
            freqs[LZX_NUM_CHARS + slot * 8 + lenslot] += 1
    length_freqs = [0] * LZX_NUM_SECONDARY_LENGTHS
    for e in main_syms:
        if e[0] == "match" and e[2] >= LZX_NUM_PRIMARY_LENGTHS:
            length_freqs[e[2] - LZX_NUM_PRIMARY_LENGTHS] += 1

    main_lens = _huffman_lengths_clean(freqs, HUFF_MAXBITS)
    length_lens = _huffman_lengths_clean(length_freqs, HUFF_MAXBITS, allow_empty=True)

    write_lens_array(bw, main_lens, 0, 256, maintree_running)
    write_lens_array(bw, main_lens, 256, LZX_NUM_CHARS + num_offsets,
                     maintree_running)
    main_codes = canonical_codes(main_lens, HUFF_MAXBITS)
    write_lens_array(bw, length_lens, 0, LZX_NUM_SECONDARY_LENGTHS,
                     length_running)
    length_codes = canonical_codes(length_lens, HUFF_MAXBITS)

    for e in main_syms:
        if e[0] == "lit":
            sym = e[1]
            bw.push(main_codes[sym], main_lens[sym])
        else:
            _, slot, ml, extra_bits, extra_val = e
            lenslot = min(ml, LZX_NUM_PRIMARY_LENGTHS)
            sym = LZX_NUM_CHARS + slot * 8 + lenslot
            bw.push(main_codes[sym], main_lens[sym])
            if lenslot == LZX_NUM_PRIMARY_LENGTHS:
                extra = ml - LZX_NUM_PRIMARY_LENGTHS
                bw.push(length_codes[extra], length_lens[extra])
            if extra_bits:
                bw.push(extra_val, extra_bits)


def _wrap_frame_header(payload, uncompressed_size, is_final):
    """XMemCompress's outer per-frame framing, matched to RETAIL convention
    (verified against all 10 segments of two real NB1 files, which agree
    unanimously): every frame except the last gets a plain 2-byte BE
    compressed-size header; the FINAL frame of a segment always uses the
    5-byte escape form (0xFF + u16 BE uncompressed-size + u16 BE
    compressed-size) even when it's a full 32 KB frame. A non-final frame
    also escapes if its plain header would collide with the 0xFF sentinel.
    The 5-zero-byte stream terminator that follows the final frame is
    appended by the caller, not here."""
    csize = len(payload)
    if is_final or csize >= 0xFF00:
        return b"\xFF" + struct.pack(">HH", uncompressed_size, csize) + payload
    return struct.pack(">H", csize) + payload


# Retail streams end with 5 zero bytes after the final frame — a null
# frame header the real decompressor uses as its end-of-stream signal
# (present in 10/10 segments across two retail files). A decoder that
# loops "read header, stop on terminator" (rather than counting output
# bytes like ours does) NEEDS this, or it reads past the end into garbage.
XMEM_STREAM_TERMINATOR = b"\x00" * 5


def xmem_lzx_compress(plaintext, window_bits):
    """Compress `plaintext` into an XMemCompress-framed LZX stream that
    naughty_lu.LZXDecoder(window_bits) + parse_xmem_frames decode back to
    the exact input. One VERBATIM block per LZX_FRAME_SIZE (32 KB) LZX
    frame, each wrapped in its own XMemCompress frame-size header (a
    separate outer layer from the LZX bitstream's internal 32 KB frames —
    naughty_lu.py's parse_xmem_frames consumes this wrapper before handing
    the concatenated payload to LZXDecoder). Framing conventions (final-
    frame escape header, trailing terminator) match retail output
    byte-for-byte in structure."""
    if window_bits not in POSITION_SLOTS:
        raise ValueError(f"unsupported window_bits {window_bits}")
    num_offsets = POSITION_SLOTS[window_bits] << 3
    window_size = 1 << window_bits

    maintree_running = [0] * (MAINTREE_MAXSYMBOLS + 64)
    length_running = [0] * (LENGTH_MAXSYMBOLS + 64)
    rcache = [1, 1, 1]
    chain_state = [[-1] * (1 << 15), {}]

    out = bytearray()
    pos, n = 0, len(plaintext)
    first_frame = True
    while pos < n:
        frame_end = min(pos + LZX_FRAME_SIZE, n)
        window_base = max(0, frame_end - window_size)
        tokens = _find_matches(plaintext, window_base, pos, frame_end, chain_state)
        block_length = frame_end - pos

        fbw = BitWriter()
        if first_frame:
            fbw.push(0, 1)  # no Intel E8 translation — once, stream-wide
            first_frame = False
        fbw.push(LZX_BLOCK_VERBATIM, 3)
        fbw.push((block_length >> 8) & 0xFFFF, 16)
        fbw.push(block_length & 0xFF, 8)
        _encode_block(fbw, tokens, num_offsets, maintree_running, length_running,
                      rcache)
        payload = fbw.getvalue()
        out += _wrap_frame_header(payload, block_length, frame_end == n)
        pos = frame_end
    out += XMEM_STREAM_TERMINATOR
    return bytes(out)
