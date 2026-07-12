/* lzxverify.c - independent LZX decode harness for verify_lzx.py.
 *
 * This file is written for the Seam Ripper project. It is NOT part of
 * libmspack: it is a small program that USES libmspack's decoder
 * (lzxd.c / system.c / mspack.h / lzx.h, all unmodified upstream files
 * bundled alongside this one) via its public API, the same way any
 * application uses a library it links against. See NOTICE.md in this
 * folder for what that means for redistribution.
 *
 * libmspack is Copyright (C) Stuart Caie, licensed under the GNU Lesser
 * General Public License v2.1 (see COPYING.LIB in this folder). This file
 * itself carries no additional restriction beyond what linking against
 * LGPL-covered code already requires; see NOTICE.md.
 */
#include <stdio.h>
#include <stdlib.h>
#include "mspack.h"
#include "lzx.h"
#include "system.h"

static void banner(void) {
    fprintf(stderr,
        "lzxverify - independent LZX decode check (uses libmspack, LGPL 2.1)\n"
        "No warranty. See NOTICE.md and COPYING.LIB next to this program.\n");
}

int main(int argc, char **argv) {
    if (argc != 5) {
        banner();
        fprintf(stderr, "usage: %s in.bin out.bin window_bits out_size\n", argv[0]);
        return 2;
    }
    struct mspack_system *sys = mspack_default_system;
    struct mspack_file *in = sys->open(sys, argv[1], MSPACK_SYS_OPEN_READ);
    struct mspack_file *out = sys->open(sys, argv[2], MSPACK_SYS_OPEN_WRITE);
    if (!in || !out) { fprintf(stderr, "open failed\n"); return 1; }
    int window_bits = atoi(argv[3]);
    off_t out_size = (off_t)atoll(argv[4]);
    struct lzxd_stream *lzx = lzxd_init(sys, in, out, window_bits, 0, 4096, out_size, 0);
    if (!lzx) { fprintf(stderr, "lzxd_init failed\n"); return 1; }
    int err = lzxd_decompress(lzx, out_size);
    fprintf(stderr, "lzxd_decompress: %d\n", err);
    lzxd_free(lzx);
    sys->close(in);
    sys->close(out);
    return err;
}
