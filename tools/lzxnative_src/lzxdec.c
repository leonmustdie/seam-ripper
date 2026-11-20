/*
 * _lzxdec: native build of Seam Ripper's own LZX decoder.
 *
 * A line-for-line C port of naughty_lu.py's LZXDecoder.decompress (which is
 * itself a port of libmspack's lzxd.c, LGPL 2.1, see ../lzxverify_src/):
 * MSB bit order, 16-bit little-endian words, no LZX-DELTA, Xbox 360
 * uncompressed blocks without the CAB pad byte. naughty_lu.py uses it when
 * it imports and falls back to the Python decoder otherwise; the two are
 * checked against each other on every retail segment of both games
 * (tests/test_lzx_native.py). The independent check of written containers
 * stays lzxverify (libmspack), which shares no code with either.
 *
 * decompress(stream: bytes, out_len: int, window_bits: int) -> bytes
 * raises ValueError on a bad stream. The GIL is released while decoding, so
 * threads can decode several segments at once.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MIN_MATCH 2
#define NUM_CHARS 256
#define BLOCK_VERBATIM 1
#define BLOCK_ALIGNED 2
#define BLOCK_UNCOMPRESSED 3
#define PRETREE_NUM 20
#define NUM_PRIMARY 7
#define NUM_SECONDARY 249
#define FRAME_SIZE 32768
#define HUFF_MAXBITS 16

#define PRETREE_TB 6
#define PRETREE_MS 20
#define MAINTREE_TB 12
#define MAINTREE_MS (NUM_CHARS + 290 * 8)
#define LENGTH_TB 12
#define LENGTH_MS (NUM_SECONDARY + 1)
#define ALIGNED_TB 7
#define ALIGNED_MS 8

#define TBL(tb, ms) ((1 << (tb)) + ((ms) << 1))
#define MAINTREE_LEN_SIZE (MAINTREE_MS + 64)
#define LENGTH_LEN_SIZE (LENGTH_MS + 64)

static const int EXTRA_BITS[36] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7,
    8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16};
static uint32_t POSITION_BASE[290];

static int position_slots(int wbits)
{
    switch (wbits) {
    case 15: return 30; case 16: return 32; case 17: return 34;
    case 18: return 36; case 19: return 38; case 20: return 42;
    case 21: return 50; case 22: return 66; case 23: return 98;
    case 24: return 162; case 25: return 290;
    default: return 0;
    }
}

typedef struct {
    const uint8_t *d;
    Py_ssize_t n, pos;
    uint32_t buf;
    int left;
    jmp_buf fail;
    char err[128];
} Dec;

static void fail(Dec *s, const char *msg)
{
    snprintf(s->err, sizeof s->err, "%s", msg);
    longjmp(s->fail, 1);
}

static void ensure(Dec *s, int n)
{
    while (s->left < n) {
        uint32_t w;
        if (s->pos + 1 < s->n) {
            w = (uint32_t)s->d[s->pos] | ((uint32_t)s->d[s->pos + 1] << 8);
            s->pos += 2;
        } else if (s->pos < s->n) {
            w = s->d[s->pos];
            s->pos += 1;
        } else {
            w = 0;  /* zero-pad at EOF (stream is frame-exact) */
        }
        s->buf |= w << (16 - s->left);
        s->left += 16;
    }
}

static uint32_t readbits(Dec *s, int n)
{
    uint32_t v;
    if (n == 0)
        return 0;
    ensure(s, n);
    v = s->buf >> (32 - n);
    s->buf <<= n;
    s->left -= n;
    return v;
}

static uint32_t readhuff(Dec *s, const uint16_t *table, int tsize,
                         const uint8_t *lens, int tb, int ms)
{
    uint32_t sym;
    ensure(s, HUFF_MAXBITS);
    sym = table[s->buf >> (32 - tb)];
    if (sym >= (uint32_t)ms) {
        uint32_t mask = 1u << (32 - tb);
        for (;;) {
            uint32_t idx;
            mask >>= 1;
            if (mask == 0)
                fail(s, "huffman traverse overflow");
            idx = (sym << 1) | ((s->buf & mask) ? 1u : 0u);
            if (idx >= (uint32_t)tsize)
                fail(s, "huffman table index out of range");
            sym = table[idx];
            if (sym < (uint32_t)ms)
                break;
        }
    }
    s->buf <<= lens[sym];
    s->left -= lens[sym];
    return sym;
}

/* 0 on success, -1 on a bad code (the Python version returns None) */
static int make_table(int nsyms, int nbits, const uint8_t *length,
                      uint16_t *table, int tsize)
{
    uint32_t pos = 0, table_mask = 1u << nbits, bit_mask = table_mask >> 1;
    uint32_t next_symbol;
    int bit_num, sym;
    for (bit_num = 1; bit_num <= nbits; bit_num++) {
        for (sym = 0; sym < nsyms; sym++) {
            uint32_t leaf, k;
            if (length[sym] != bit_num)
                continue;
            leaf = pos;
            pos += bit_mask;
            if (pos > table_mask)
                return -1;
            for (k = 0; k < bit_mask; k++)
                table[leaf + k] = (uint16_t)sym;
        }
        bit_mask >>= 1;
    }
    if (pos == table_mask)
        return 0;
    for (sym = (int)pos; sym < (int)table_mask; sym++)
        table[sym] = 0xFFFF;
    next_symbol = ((table_mask >> 1) < (uint32_t)nsyms) ? (uint32_t)nsyms
                                                         : (table_mask >> 1);
    pos <<= 16;
    table_mask <<= 16;
    bit_mask = 1u << 15;
    for (bit_num = nbits + 1; bit_num <= HUFF_MAXBITS; bit_num++) {
        for (sym = 0; sym < nsyms; sym++) {
            uint32_t leaf;
            int fill;
            if (length[sym] != bit_num)
                continue;
            if (pos >= table_mask)
                return -1;
            leaf = pos >> 16;
            for (fill = 0; fill < bit_num - nbits; fill++) {
                if (leaf >= (uint32_t)tsize)
                    return -1;
                if (table[leaf] == 0xFFFF) {
                    if ((next_symbol << 1) + 1 >= (uint32_t)tsize)
                        return -1;
                    table[next_symbol << 1] = 0xFFFF;
                    table[(next_symbol << 1) + 1] = 0xFFFF;
                    table[leaf] = (uint16_t)next_symbol;
                    next_symbol++;
                }
                leaf = (uint32_t)table[leaf] << 1;
                if ((pos >> (15 - fill)) & 1)
                    leaf++;
            }
            if (leaf >= (uint32_t)tsize)
                return -1;
            table[leaf] = (uint16_t)sym;
            pos += bit_mask;
        }
        bit_mask >>= 1;
    }
    return pos == table_mask ? 0 : -1;
}

static void read_lens(Dec *s, uint8_t *lens, int size, int first, int last)
{
    uint8_t pre_len[PRETREE_NUM];
    uint16_t pre_tbl[TBL(PRETREE_TB, PRETREE_MS)];
    int i, x;
    for (i = 0; i < PRETREE_NUM; i++)
        pre_len[i] = (uint8_t)readbits(s, 4);
    if (make_table(PRETREE_MS, PRETREE_TB, pre_len, pre_tbl,
                   TBL(PRETREE_TB, PRETREE_MS)) < 0)
        fail(s, "bad pretree");
    x = first;
    while (x < last) {
        int z = (int)readhuff(s, pre_tbl, TBL(PRETREE_TB, PRETREE_MS), pre_len,
                              PRETREE_TB, PRETREE_MS);
        if (z == 17 || z == 18) {
            int cnt = z == 17 ? (int)readbits(s, 4) + 4 : (int)readbits(s, 5) + 20;
            while (cnt-- > 0) {
                if (x >= size)
                    fail(s, "length table overrun");
                lens[x++] = 0;
            }
        } else if (z == 19) {
            int y = (int)readbits(s, 1) + 4;
            z = (int)readhuff(s, pre_tbl, TBL(PRETREE_TB, PRETREE_MS), pre_len,
                              PRETREE_TB, PRETREE_MS);
            z = lens[x] - z;
            if (z < 0)
                z += 17;
            while (y-- > 0) {
                if (x >= size)
                    fail(s, "length table overrun");
                lens[x++] = (uint8_t)z;
            }
        } else {
            z = lens[x] - z;
            if (z < 0)
                z += 17;
            lens[x++] = (uint8_t)z;
        }
    }
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)
        | ((uint32_t)p[3] << 24);
}

/* the decode proper: heap buffers are owned by the caller, so a longjmp
   out of here leaks nothing */
static void decode(Dec *s, int wbits, uint8_t *window, uint8_t *out,
                   int64_t out_len, uint8_t *mt_len, uint8_t *lt_len,
                   uint16_t *mt_tbl, uint16_t *lt_tbl)
{
    const int64_t wsize = (int64_t)1 << wbits;
    const int num_offsets = position_slots(wbits) << 3;
    int64_t window_posn = 0, frame_posn = 0, offset = 0;
    int64_t frame = 0, end_frame = out_len / FRAME_SIZE + 1;
    uint32_t R0 = 1, R1 = 1, R2 = 1;
    int header_read = 0, intel_started = 0, length_empty = 0;
    uint32_t intel_filesize = 0;
    int block_type = 0;
    int64_t block_remaining = 0;
    uint8_t al_len[ALIGNED_MS];
    uint16_t al_tbl[TBL(ALIGNED_TB, ALIGNED_MS)];

    while (frame < end_frame) {
        int64_t frame_size, bytes_todo;
        if (!header_read) {
            if (readbits(s, 1)) {
                uint32_t i = readbits(s, 16), j = readbits(s, 16);
                intel_filesize = (i << 16) | j;
            }
            header_read = 1;
        }
        frame_size = FRAME_SIZE;
        if (out_len - offset < frame_size)
            frame_size = out_len - offset;

        bytes_todo = frame_posn + frame_size - window_posn;
        while (bytes_todo > 0) {
            int64_t this_run;
            if (block_remaining == 0) {
                uint32_t i, j;
                block_type = (int)readbits(s, 3);
                i = readbits(s, 16);
                j = readbits(s, 8);
                block_remaining = (int64_t)((i << 8) | j);

                if (block_type == BLOCK_ALIGNED) {
                    int k;
                    for (k = 0; k < ALIGNED_MS; k++)
                        al_len[k] = (uint8_t)readbits(s, 3);
                    if (make_table(ALIGNED_MS, ALIGNED_TB, al_len, al_tbl,
                                   TBL(ALIGNED_TB, ALIGNED_MS)) < 0)
                        fail(s, "bad aligned tree");
                }
                if (block_type == BLOCK_ALIGNED || block_type == BLOCK_VERBATIM) {
                    read_lens(s, mt_len, MAINTREE_LEN_SIZE, 0, 256);
                    read_lens(s, mt_len, MAINTREE_LEN_SIZE, 256,
                              NUM_CHARS + num_offsets);
                    if (make_table(MAINTREE_MS, MAINTREE_TB, mt_len, mt_tbl,
                                   TBL(MAINTREE_TB, MAINTREE_MS)) < 0)
                        fail(s, "bad maintree");
                    if (mt_len[0xE8] != 0)
                        intel_started = 1;
                    read_lens(s, lt_len, LENGTH_LEN_SIZE, 0, NUM_SECONDARY);
                    if (make_table(LENGTH_MS, LENGTH_TB, lt_len, lt_tbl,
                                   TBL(LENGTH_TB, LENGTH_MS)) < 0) {
                        int k;
                        for (k = 0; k < NUM_SECONDARY; k++)
                            if (lt_len[k])
                                fail(s, "bad length tree");
                        length_empty = 1;
                    } else {
                        length_empty = 0;
                    }
                } else if (block_type == BLOCK_UNCOMPRESSED) {
                    intel_started = 1;
                    if (s->left == 0)
                        ensure(s, 16);
                    s->left = 0;
                    s->buf = 0;
                    if (s->pos + 12 > s->n)
                        fail(s, "EOF in uncompressed block header");
                    R0 = le32(s->d + s->pos);
                    R1 = le32(s->d + s->pos + 4);
                    R2 = le32(s->d + s->pos + 8);
                    s->pos += 12;
                } else {
                    char m[40];
                    snprintf(m, sizeof m, "bad block type %d", block_type);
                    fail(s, m);
                }
            }

            this_run = block_remaining < bytes_todo ? block_remaining : bytes_todo;
            bytes_todo -= this_run;
            block_remaining -= this_run;

            if (block_type == BLOCK_ALIGNED || block_type == BLOCK_VERBATIM) {
                const int aligned = block_type == BLOCK_ALIGNED;
                while (this_run > 0) {
                    uint32_t sym = readhuff(s, mt_tbl, TBL(MAINTREE_TB, MAINTREE_MS),
                                            mt_len, MAINTREE_TB, MAINTREE_MS);
                    int64_t match_length, match_offset;
                    uint32_t slot;
                    if (sym < NUM_CHARS) {
                        if (window_posn >= wsize)
                            fail(s, "literal past window end");
                        window[window_posn++] = (uint8_t)sym;
                        this_run--;
                        continue;
                    }
                    sym -= NUM_CHARS;
                    match_length = sym & NUM_PRIMARY;
                    if (match_length == NUM_PRIMARY) {
                        if (length_empty)
                            fail(s, "LENGTH symbol needed but tree empty");
                        match_length += readhuff(s, lt_tbl, TBL(LENGTH_TB, LENGTH_MS),
                                                 lt_len, LENGTH_TB, LENGTH_MS);
                    }
                    match_length += MIN_MATCH;
                    slot = sym >> 3;
                    if (slot == 0) {
                        match_offset = R0;
                    } else if (slot == 1) {
                        match_offset = R1;
                        R1 = R0;
                        R0 = (uint32_t)match_offset;
                    } else if (slot == 2) {
                        match_offset = R2;
                        R2 = R0;
                        R0 = (uint32_t)match_offset;
                    } else {
                        int extra = slot >= 36 ? 17 : EXTRA_BITS[slot];
                        match_offset = (int64_t)POSITION_BASE[slot] - 2;
                        if (extra >= 3 && aligned) {
                            if (extra > 3)
                                match_offset += (int64_t)readbits(s, extra - 3) << 3;
                            match_offset += readhuff(s, al_tbl, TBL(ALIGNED_TB, ALIGNED_MS),
                                                     al_len, ALIGNED_TB, ALIGNED_MS);
                        } else if (extra) {
                            match_offset += readbits(s, extra);
                        }
                        R2 = R1;
                        R1 = R0;
                        R0 = (uint32_t)match_offset;
                    }
                    if (window_posn + match_length > wsize)
                        fail(s, "match ran over window wrap");
                    if (match_offset > window_posn) {
                        int64_t j = match_offset - window_posn, i = match_length, src;
                        if (j > wsize)
                            fail(s, "match offset beyond window");
                        src = wsize - j;
                        if (j < i) {
                            i -= j;
                            while (j > 0) {
                                window[window_posn++] = window[src++];
                                j--;
                            }
                            src = 0;
                        }
                        while (i > 0) {
                            window[window_posn++] = window[src++];
                            i--;
                        }
                    } else {
                        int64_t src = window_posn - match_offset, k;
                        if (match_offset >= match_length) {
                            memcpy(window + window_posn, window + src, (size_t)match_length);
                            window_posn += match_length;
                        } else {
                            for (k = 0; k < match_length; k++)
                                window[window_posn++] = window[src++];
                        }
                    }
                    this_run -= match_length;
                }
            } else {  /* uncompressed */
                if (s->pos + this_run > s->n)
                    fail(s, "EOF in uncompressed block");
                if (window_posn + this_run > wsize)
                    fail(s, "uncompressed run past window end");
                memcpy(window + window_posn, s->d + s->pos, (size_t)this_run);
                s->pos += this_run;
                window_posn += this_run;
                this_run = 0;
            }

            if (this_run < 0) {
                if (-this_run > block_remaining)
                    fail(s, "overrun past end of block");
                block_remaining -= -this_run;
            }
        }

        if (window_posn - frame_posn != frame_size)
            fail(s, "decode beyond output frame limits");

        /* re-align bitstream to a 16-bit boundary */
        if (s->left > 0)
            ensure(s, 16);
        if (s->left & 15) {
            int n = s->left & 15;
            s->buf <<= n;
            s->left -= n;
        }

        memcpy(out + offset, window + frame_posn, (size_t)frame_size);
        if (intel_started && intel_filesize && frame < 32768 && frame_size > 10) {
            uint8_t *fd = out + offset;
            int64_t curpos = offset, dpos = 0, dend = frame_size - 10;
            while (dpos < dend) {
                int32_t a;
                if (fd[dpos] != 0xE8) {
                    dpos++;
                    curpos++;
                    continue;
                }
                dpos++;
                a = (int32_t)le32(fd + dpos);
                if (-curpos <= (int64_t)a && (int64_t)a < (int64_t)intel_filesize) {
                    int64_t rel = a >= 0 ? (int64_t)a - curpos
                                         : (int64_t)a + (int64_t)intel_filesize;
                    uint32_t r = (uint32_t)rel;
                    fd[dpos] = (uint8_t)r;
                    fd[dpos + 1] = (uint8_t)(r >> 8);
                    fd[dpos + 2] = (uint8_t)(r >> 16);
                    fd[dpos + 3] = (uint8_t)(r >> 24);
                }
                dpos += 4;
                curpos += 5;
            }
        }
        offset += frame_size;
        frame_posn += frame_size;
        frame++;
        if (window_posn == wsize)
            window_posn = 0;
        if (frame_posn == wsize)
            frame_posn = 0;
    }
}

static PyObject *py_decompress(PyObject *self, PyObject *args)
{
    Py_buffer in;
    Py_ssize_t out_len;
    int wbits, failed = 0;
    uint8_t *window, *out, *mt_len, *lt_len;
    uint16_t *mt_tbl, *lt_tbl;
    Dec *s;
    PyObject *res = NULL;
    (void)self;

    if (!PyArg_ParseTuple(args, "y*ni", &in, &out_len, &wbits))
        return NULL;
    if (!position_slots(wbits) || out_len < 0) {
        PyBuffer_Release(&in);
        PyErr_Format(PyExc_ValueError, "unsupported LZX window bits %d", wbits);
        return NULL;
    }
    s = (Dec *)calloc(1, sizeof(Dec));
    window = (uint8_t *)calloc((size_t)1 << wbits, 1);
    out = (uint8_t *)malloc((size_t)out_len + 1);
    mt_len = (uint8_t *)calloc(MAINTREE_LEN_SIZE, 1);
    lt_len = (uint8_t *)calloc(LENGTH_LEN_SIZE, 1);
    mt_tbl = (uint16_t *)calloc(TBL(MAINTREE_TB, MAINTREE_MS), sizeof(uint16_t));
    lt_tbl = (uint16_t *)calloc(TBL(LENGTH_TB, LENGTH_MS), sizeof(uint16_t));
    if (!s || !window || !out || !mt_len || !lt_len || !mt_tbl || !lt_tbl) {
        PyErr_NoMemory();
        goto done;
    }
    s->d = (const uint8_t *)in.buf;
    s->n = in.len;

    Py_BEGIN_ALLOW_THREADS
    if (setjmp(s->fail) == 0)
        decode(s, wbits, window, out, (int64_t)out_len, mt_len, lt_len,
               mt_tbl, lt_tbl);
    else
        failed = 1;
    Py_END_ALLOW_THREADS

    if (failed)
        PyErr_SetString(PyExc_ValueError, s->err);
    else
        res = PyBytes_FromStringAndSize((const char *)out, out_len);
done:
    free(s);
    free(window);
    free(out);
    free(mt_len);
    free(lt_len);
    free(mt_tbl);
    free(lt_tbl);
    PyBuffer_Release(&in);
    return res;
}

static PyMethodDef methods[] = {
    {"decompress", py_decompress, METH_VARARGS,
     "decompress(stream, out_len, window_bits) -> bytes: one raw LZX "
     "bitstream (XMemCompress frame headers already removed)."},
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_lzxdec",
    "Native build of naughty_lu.LZXDecoder (see lzxnative_src/lzxdec.c).",
    -1, methods};

PyMODINIT_FUNC PyInit__lzxdec(void)
{
    uint32_t b = 0;
    int i;
    for (i = 0; i < 290; i++) {
        POSITION_BASE[i] = b;
        b += 1u << (i >= 36 ? 17 : EXTRA_BITS[i]);
    }
    return PyModule_Create(&module);
}
