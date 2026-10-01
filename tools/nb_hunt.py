#!/usr/bin/env python3
"""Budgeted searches for NB1 hash names."""
import argparse
import itertools
import math
import os
import re
import sqlite3
import string
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nb_names  # noqa: E402

MASK = 0xFFFFFFFF

# ---------------------------------------------------------------- CRC engine
_T = np.zeros(256, dtype=np.uint32)
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xEDB88320 if _c & 1 else _c >> 1
    _T[_i] = _c
_TOP = np.zeros(256, dtype=np.uint32)          # top byte of a table entry -> its index
for _i in range(256):
    _TOP[int(_T[_i]) >> 24] = _i


def reg(s):
    """Internal CRC register after hashing s (lower-cased, as the game does)."""
    return ~zlib.crc32(s.lower().encode("latin-1", "replace")) & MASK


def feed(regs, data):
    """Append the same bytes to every register in `regs`."""
    r = np.asarray(regs, dtype=np.uint32).copy()
    for b in data.lower().encode("latin-1", "replace"):
        r = _T[(r ^ b) & 0xFF] ^ (r >> 8)
    return r


def feed_each(start, words):
    """register after start + w, for every w in words (vectorised by length)."""
    out = np.empty(len(words), dtype=np.uint32)
    by_len = {}
    for i, w in enumerate(words):
        by_len.setdefault(len(w), []).append(i)
    for n, idx in by_len.items():
        mat = np.frombuffer("".join(words[i] for i in idx).lower().encode("latin-1", "replace"),
                            dtype=np.uint8).reshape(len(idx), n) if n else np.zeros((len(idx), 0), np.uint8)
        r = np.full(len(idx), start, dtype=np.uint32)
        for j in range(n):
            r = _T[(r ^ mat[:, j]) & 0xFF] ^ (r >> 8)
        out[idx] = r
    return out


def unappend_many(hashes, ending):
    """crc(prefix + ending) -> crc(prefix), for many hashes at once."""
    r = np.asarray(hashes, dtype=np.uint32) ^ np.uint32(MASK)
    for b in reversed(ending.lower().encode("latin-1", "replace")):
        i = _TOP[r >> 24]
        r = ((r ^ _T[i]) << np.uint32(8)) | (i ^ np.uint32(b))
    return r ^ np.uint32(MASK)


def unappend_each(h, words):
    """crc(prefix) for prefix + w == h, for every w in words (vectorised by length)."""
    out = np.empty(len(words), dtype=np.uint32)
    by_len = {}
    for i, w in enumerate(words):
        by_len.setdefault(len(w), []).append(i)
    for n, idx in by_len.items():
        r = np.full(len(idx), h ^ MASK, dtype=np.uint32)
        if n:
            mat = np.frombuffer("".join(words[i] for i in idx).lower().encode("latin-1", "replace"),
                                dtype=np.uint8).reshape(len(idx), n)
            for j in range(n - 1, -1, -1):
                t = _TOP[r >> 24]
                r = ((r ^ _T[t]) << np.uint32(8)) | (t ^ mat[:, j].astype(np.uint32))
        out[idx] = r ^ np.uint32(MASK)
    return out


def hashes_of(regs):
    return np.asarray(regs, dtype=np.uint32) ^ np.uint32(MASK)


# ------------------------------------------------------------ budget, speed
def expected_false(candidates, targets):
    return candidates * targets / 2 ** 32


def check_budget(candidates, targets, args):
    e = expected_false(candidates, targets)
    print(f"# {candidates:,} candidates x {targets} targets -> {e:.4f} false matches expected", flush=True)
    if e > args.max_false and not args.force:
        sys.exit(f"refused: over the budget of {args.max_false} (narrow the search, or --force)")
    return e


def lower_priority():
    """Below-normal priority on Windows, nice +10 elsewhere. Best effort."""
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
        else:
            os.nice(10)
    except Exception:
        pass


def default_jobs():
    return max(1, (os.cpu_count() or 2) // 2)


# ------------------------------------------------------------- plausibility
SPLIT = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_SCORER = None


class Scorer:
    """Cost per character of explaining a name with known tokens (lower is better)."""
    TRUST = {"found", "confirmed", "rule"}

    def __init__(self, known=None, tiers=None, extra_words=()):
        known = nb_names.load() if known is None else known
        if tiers is None:
            tiers, _ = nb_names.load_sources()
        # trusted tiers teach at full weight; searched names at a quarter, so a developer
        # typo already accepted elsewhere (accomodating, finsihing) is not scored as junk
        weights = {t: 1.0 for t in self.TRUST}
        weights["searched"] = 0.25
        weights["review"] = 0.1
        self.count, self.pairs = {}, set()
        for h, v in known.items():
            w = weights.get(tiers.get(h), 0.0 if tiers else 1.0)
            if not w:
                continue
            ps = self.parts(v)
            for p in ps:
                self.count[p] = self.count.get(p, 0) + w
            if w == 1.0:
                self.pairs.update(zip(ps, ps[1:]))
        self.total = sum(self.count.values()) or 1
        self.words = set(extra_words)
        # an optional plain word list (one word per line), e.g. NB_HUNT_WORDS=vocab.txt:
        # real words the game's own text never uses (shake, cam) should not look like junk
        wl = os.environ.get("NB_HUNT_WORDS")
        if wl and Path(wl).exists():
            self.words.update(l.strip().lower() for l in open(wl, errors="ignore") if l.strip().isalpha())
        try:
            for t in nb_names.load_text().values():
                s = t[0] if isinstance(t, (list, tuple)) else (t or "")
                self.words.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", str(s)))
        except Exception:
            pass

    @staticmethod
    def parts(name):
        out = []
        for chunk in re.split(r"[_\W]+", name):
            out += [p.lower() for p in SPLIT.findall(chunk)]
        return [p for p in out if p]

    def tcost(self, t):
        if t.isdigit():
            return 0.5
        c = self.count.get(t)
        if c:
            return -math.log(c / self.total) / 4
        return 4.0 if t in self.words else None

    def segment(self, s):
        n = len(s)
        best = [0.0] + [math.inf] * n
        back = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(max(0, j - 24), j):
                c = self.tcost(s[i:j])
                if c is None:
                    if j - i != 1:
                        continue
                    c = 6.0
                if best[i] + c < best[j]:
                    best[j], back[j] = best[i] + c, i
        toks, j = [], n
        while j > 0:
            toks.append(s[back[j]:j])
            j = back[j]
        return best[n], toks[::-1]

    def score(self, name):
        cost, toks, chars = 0.0, [], 0
        for p in self.parts(name):
            if len(p) == 1:                      # CamelCase initial: F, L, R, C
                cost += 1.5; toks.append(p.upper()); chars += 1
                continue
            c, t = self.segment(p)
            cost += c; toks += t; chars += len(p)
        loose = sum(1 for t in toks if len(t) == 1 and t.islower())
        unseen = sum(1 for a, b in zip(toks, toks[1:])
                     if (a, b) not in self.pairs and not a.isdigit() and not b.isdigit())
        return round(cost / max(chars, 1) + 0.8 * loose + 0.15 * unseen, 3), toks


JUNK = 3.5


def scorer():
    global _SCORER
    if _SCORER is None:
        _SCORER = Scorer()
    return _SCORER


def report(name, h, label=""):
    s, _ = scorer().score(name)
    flag = "JUNK?" if s >= JUNK else "     "
    print(f"{flag} {s:6.2f} {h:08x} {name}  {label}".rstrip(), flush=True)


# ------------------------------------------------------------------ targets
def read_targets(spec):
    """Hex hashes from a file (one per line, optional label after) or a comma list."""
    out = {}
    p = Path(spec)
    lines = p.read_text().splitlines() if p.exists() else spec.split(",")
    bad = 0
    for line in lines:
        parts = line.split(None, 1)
        if parts and parts[0].strip():
            tok = parts[0].strip().removeprefix("0x")
            if not re.fullmatch(r"[0-9a-fA-F]{1,8}", tok):
                bad += 1                          # e.g. two hashes fused by a missing newline
                continue
            out[int(tok, 16)] = parts[1].strip() if len(parts) > 1 else ""
    if bad:
        print(f"# warning: skipped {bad} malformed target line(s)", file=sys.stderr)
    return out


def peel(targets, suffix):
    """Map crc(prefix) -> (original hash, label) once a known suffix is taken off."""
    hs = np.array(list(targets), dtype=np.uint32)
    base = unappend_many(hs, suffix) if suffix else hs
    return {int(b): (int(h), targets[int(h)]) for b, h in zip(base, hs)}


# -------------------------------------------------------------------- brute
def _brute_chunk(job):
    start, head, depth, alphabet, want = job
    codes = np.frombuffer(alphabet.encode(), dtype=np.uint8).astype(np.uint32)
    n = len(alphabet)
    r = np.array([start], dtype=np.uint32)
    for _ in range(depth):
        r = np.repeat(r, n)
        r = _T[(r ^ np.tile(codes, len(r) // n)) & 0xFF] ^ (r >> 8)
    hits = []
    for i in np.nonzero(np.isin(r ^ np.uint32(MASK), want))[0]:
        i, s = int(i), []
        for _ in range(depth):
            s.append(alphabet[i % n]); i //= n
        hits.append(head + "".join(reversed(s)))
    return hits


def cmd_brute(args):
    targets = read_targets(args.targets)
    table = peel(targets, args.suffix)
    A, L = args.alphabet, args.len
    cands = sum(len(A) ** k for k in range(1, L + 1))
    check_budget(cands, len(targets), args)
    lower_priority()
    want = np.array(sorted(table), dtype=np.uint32)
    base = reg(args.prefix)
    jobs = []
    # each chunk holds at most ~4M states (16 MB per array), whatever the alphabet size
    chunk = max(1, int(math.log(4_000_000) / math.log(len(A))))
    for k in range(1, L + 1):
        fixed = max(0, k - chunk)
        for head in itertools.product(A, repeat=fixed):
            head = "".join(head)
            jobs.append((int(feed([base], head)[0]), head, k - fixed, A, want))
    def emit(hits):
        for x in hits:
            h0, lab = table[zlib.crc32((args.prefix + x).lower().encode())]
            report(args.prefix + x + args.suffix, h0, lab)

    if args.jobs <= 1:
        for j in jobs:
            emit(_brute_chunk(j))
        return
    from multiprocessing import Pool
    with Pool(args.jobs) as pool:
        for hits in pool.imap_unordered(_brute_chunk, jobs, chunksize=4):
            emit(hits)


# -------------------------------------------------------------------- words
def load_tokens(args):
    toks = set()
    if args.vocab:
        for f in args.vocab:
            toks |= {l.strip().lower() for l in open(f, errors="ignore") if l.strip()}
    if args.known_tokens:
        for v in nb_names.load().values():
            toks |= {t for t in re.split(r"[_\W]+", v.lower()) if t.isalnum()}
            toks |= {t.lower() for t in SPLIT.findall(v)}
    if args.tokens:
        toks |= {t.lower() for t in args.tokens.split(",")}
    return sorted(t for t in toks if t and len(t) <= args.max_token)


def cmd_words(args):
    targets = read_targets(args.targets)
    table = peel(targets, args.suffix)
    toks = load_tokens(args)
    seps = args.seps.split(",") if args.seps else [""]
    k = args.depth
    cands = len(toks) ** k * len(seps) ** (k - 1)
    check_budget(cands, len(targets), args)
    lower_priority()
    # forward: prefix + t1 + sep + ... + t(k-1) + sep; the last token is peeled off the targets
    fw = [(int(reg(args.prefix)), args.prefix)]
    for _ in range(k - 1):
        nxt = []
        for st, s in fw:
            regs = feed_each(st, toks)
            for sep in seps:
                after = feed(regs, sep) if sep else regs
                nxt += [(int(r), s + t + sep) for r, t in zip(after, toks)]
        fw = nxt
    fwd_h = {}
    for st, s in fw:
        fwd_h.setdefault(st ^ MASK, s)
    # backward: peel the last token off every target
    keys = np.array(list(fwd_h), dtype=np.uint32)
    for base, (h0, lab) in table.items():
        back = unappend_each(base, toks)
        for i in np.nonzero(np.isin(back, keys))[0]:
            report(fwd_h[int(back[i])] + toks[i] + args.suffix, h0, lab)


# -------------------------------------------------------------------- typos
EDIT_ALPHA = string.ascii_lowercase + string.digits + "_"


def edits1(w):
    out = set()
    for i in range(len(w) + 1):
        for c in EDIT_ALPHA:
            out.add(w[:i] + c + w[i:])
        if i < len(w):
            out.add(w[:i] + w[i + 1:])
            for c in EDIT_ALPHA:
                out.add(w[:i] + c + w[i + 1:])
            if i + 1 < len(w):
                out.add(w[:i] + w[i + 1] + w[i] + w[i + 2:])
    out.discard(w)
    return out


def cmd_typos(args):
    targets = read_targets(args.targets)
    want = np.array(list(targets), dtype=np.uint32)
    names = [n.lower() for n in args.names]
    one = {n: sorted(edits1(n) | {n}) for n in names}
    cands = sum(len(v) for v in one.values())
    if args.distance == 2:
        cands = sum(len(v) ** 2 for v in one.values())
    check_budget(cands, len(targets), args)
    lower_priority()
    empty = reg("")
    seen = set()
    for n, e1 in one.items():
        pool = [e1]
        if args.distance == 2:
            pool = (sorted(edits1(e)) for e in e1)
        for group in pool:
            hs = hashes_of(feed_each(empty, group))
            for i in np.nonzero(np.isin(hs, want))[0]:
                if group[i] not in seen:          # several predicted names can reach the same hit
                    seen.add(group[i])
                    report(group[i], int(hs[i]), targets[int(hs[i])])


# ----------------------------------------------------------------- siblings
SWAPS = [("in", "out", "loop", "_in", "_out", "_loop", "idle"), ("lt", "rt"), ("l", "r"), ("left", "right"),
         ("_l", "_r"), ("_lt", "_rt"), ("name", "desc"), ("_name", "_desc", ""), ("first", "second", "third"),
         ("bronze", "silver", "gold", "platinum"), ("fwd", "bwd"), ("open", "close"), ("on", "off"),
         ("start", "end"), ("win", "lose"), ("attack", "attacked"), ("kill", "killed"), ("scare", "scared")]


TOKEN = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+|[^A-Za-z\d]+")
_SWAP_OF = {}
for _g in SWAPS:
    for _a in _g:
        if _a and not _a.startswith("_"):
            _SWAP_OF.setdefault(_a, set()).update(b for b in _g if b and not b.startswith("_"))


def sibling_candidates(name):
    """Names a sibling of `name` would have: any number changed (0-20, same or no padding),
    any CamelCase/underscore token swapped for its partners (In/Out/Loop, Lt/Rt, name/desc...),
    and the suffix swaps that add or drop a separator (_name <-> '')."""
    low = name.lower()
    toks = [t.lower() for t in TOKEN.findall(name)]
    out = set()
    for i, t in enumerate(toks):
        alts = set()
        if t.isdigit():
            alts = {str(n).zfill(len(t)) for n in range(21)} | {str(n) for n in range(21)}
        elif t in _SWAP_OF:
            alts = _SWAP_OF[t]
        for a in alts:
            out.add("".join(toks[:i] + [a] + toks[i + 1:]))
    for group in SWAPS:
        if "" in group:                            # the bare name's siblings: X -> X_name, X_desc
            out.update(low + b for b in group if b)
        for a in group:
            if a and low.endswith(a):
                for b in group:
                    out.add(low[: len(low) - len(a)] + b)
    out.discard(low)
    return out


def affix_candidates(known, top=300):
    """Every ending that some known name uses (its last token, with separator), put on
    every other known name: ST_OpenFridge + _Panic, ST_DoorKick + Failed, ..."""
    ends = {}
    for v in known.values():
        m = re.search(r"(_?[A-Z]?[a-z]+|_?\d+|_[A-Za-z]+)$", v)
        if m and len(m.group(1)) < len(v):
            e = m.group(1).lower()
            ends[e] = ends.get(e, 0) + 1
    common = [e for e, _ in sorted(ends.items(), key=lambda kv: -kv[1])[:top]]
    out = set()
    for v in known.values():
        low = v.lower()
        if len(low) <= 80 and " " not in low:     # sentences and paths are not name stems
            out.update(low + e for e in common)
    return out


def learned_swap_candidates(known, least=2, per_name=400):
    """Token swaps the names themselves teach: when two known names differ in exactly one
    token (ST_RunFootL / ST_SprintFootL), that swap (run <-> sprint) is learned; swaps seen
    in at least `least` different contexts are applied to every name holding the token."""
    split = [[t.lower() for t in TOKEN.findall(v)] for v in known.values()]
    groups = {}
    for toks in split:
        for i, t in enumerate(toks):
            if t.isalpha() and len(t) > 1:
                groups.setdefault((tuple(toks[:i]), tuple(toks[i + 1:])), set()).add(t)
    pairs = {}
    for g in groups.values():
        for a in g:
            for b in g:
                if a != b:
                    pairs[(a, b)] = pairs.get((a, b), 0) + 1
    swaps = {}
    for (a, b), n in pairs.items():
        if n >= least:
            swaps.setdefault(a, set()).add(b)
    out = set()
    for toks in split:
        made = 0
        for i, t in enumerate(toks):
            for b in swaps.get(t, ()):
                out.add("".join(toks[:i] + [b] + toks[i + 1:]))
                made += 1
                if made >= per_name:
                    break
    return out


def learned_insert_candidates(known, least=2):
    """Insertions/deletions the names teach: ST_RunFootL -> ST_NinjaRunFootL inserts 'ninja'
    after 'st_'; seen after the same left token in >= `least` pairs, it is applied to every
    name holding that left token (and the reverse, deleting it, to names that have it)."""
    split = [[t.lower() for t in TOKEN.findall(v)] for v in known.values()]
    have = {tuple(t) for t in split}
    ins = {}
    for toks in split:
        for i in range(1, len(toks)):
            base = tuple(toks[:i] + toks[i + 1:])
            if base in have and toks[i].isalpha():
                key = (toks[i - 1], toks[i])
                ins[key] = ins.get(key, 0) + 1
    rules = {}
    for (left, t), n in ins.items():
        if n >= least:
            rules.setdefault(left, set()).add(t)
    out = set()
    for toks in split:
        for i, t in enumerate(toks):
            for new in rules.get(t, ()):
                out.add("".join(toks[:i + 1] + [new] + toks[i + 1:]))
            if i and t in rules.get(toks[i - 1], ()):
                out.add("".join(toks[:i] + toks[i + 1:]))
    return out


def camel(name, known):
    """Restore a lower-cased hit's capitalisation from how its tokens are spelled in known
    names (st_sinkidleout -> ST_SinkIdleOut); the hash is case-blind, readers are not."""
    counts = {}
    for v in known.values():
        for t in TOKEN.findall(v):
            if t.isalpha():
                counts.setdefault(t.lower(), {}).setdefault(t, 0)
                counts[t.lower()][t] += 1
    # most common spelling of each token; CamelCase words beat ALLCAPS and lower-case
    spell = {low: max(forms, key=lambda f: (forms[f] + (1000 if f[:1].isupper() and f[1:].islower() else 0)))
             for low, forms in counts.items()}
    # the closest known name decides the style: copy its spelling of the shared prefix,
    # and CamelCase the rest only if that name is CamelCase there (ST_Sink.. vs costume_names_..)
    low = name.lower()
    ref, shared = "", 0
    for v in known.values():
        lv = v.lower()
        n = len(os.path.commonprefix([lv, low]))
        if n > shared:
            ref, shared = v, n
    head, rest = ref[:shared], name[shared:].lower()
    if not ref or not any(c.isupper() for c in ref[max(0, shared - 1):] + ref[:shared][-6:]):
        return (head + rest) if ref else low
    return head + _camel_tail(rest, spell)


def _camel_tail(name, spell):
    out = []
    for chunk in re.split(r"(_)", name):
        n = len(chunk)
        best = [(0, [])] + [None] * n            # fewest tokens covering chunk[:j]
        for j in range(1, n + 1):
            for i in range(max(0, j - 30), j):
                if best[i] is None:
                    continue
                piece = chunk[i:j]
                word, cost = spell.get(piece), 1
                if word is None:
                    if piece.isdigit():
                        word = piece
                    elif piece.isalpha():             # unknown word: one capitalised piece, costly
                        word, cost = piece.capitalize(), 5
                    else:
                        continue
                cand = (best[i][0] + cost, best[i][1] + [word])
                if best[j] is None or cand[0] < best[j][0]:
                    best[j] = cand
        out.append("".join(best[n][1]) if best[n] else chunk)
    return "".join(out)


def cmd_siblings(args):
    targets = read_targets(args.targets)
    known = nb_names.load()
    if args.extra_names:                          # e.g. NB2's names: they teach patterns only
        extra = [l.strip() for l in open(args.extra_names, encoding="utf-8") if l.strip()]
        known = dict(known)
        known.update({("extra", i): v for i, v in enumerate(extra)})
    # generators are hashed in batches: holding every candidate at once can exhaust memory
    gens = []
    if args.affixes:
        gens.append(lambda: affix_candidates(known, args.affixes))
    if args.learned:
        gens.append(lambda: learned_swap_candidates(known, args.learned))
        gens.append(lambda: learned_insert_candidates(known, args.learned))
    gens.append(lambda: set().union(*(sibling_candidates(v) for v in known.values())))
    have = {v.lower() for v in known.values()}
    sizes = []
    for g in gens:
        sizes.append(len(g()))
    check_budget(sum(sizes), len(targets), args)
    want = np.array(list(targets), dtype=np.uint32)
    emit, seen = {}, set()
    start = reg("")
    for g in gens:
        batch = sorted(g() - have)
        for s in range(0, len(batch), 200_000):
            part = batch[s:s + 200_000]
            hs = hashes_of(feed_each(start, part))
            for i in np.nonzero(np.isin(hs, want))[0]:
                name = part[i]
                if name in seen:
                    continue
                seen.add(name)
                report(name, int(hs[i]), targets[int(hs[i])])
                if scorer().score(name)[0] < JUNK:
                    emit[str(int(hs[i]))] = camel(name, known)
    if args.emit:
        import json
        Path(args.emit).write_text(json.dumps(emit, indent=0), encoding="utf-8")
        print(f"# {len(emit)} non-junk hits written to {args.emit}")


# -------------------------------------------------------------------- score
def cmd_score(args):
    for n in args.names:
        s, toks = scorer().score(n)
        print(f"{s:6.2f} {'JUNK?' if s >= JUNK else '     '} {n}  {' '.join(toks)}")


# -------------------------------------------------------------------- index
def cache_dir(args):
    d = Path(args.cache or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")),
                                        "SeamRipper", "nb_hunt"))
    repo = HERE.parent.resolve()
    if repo in d.resolve().parents or d.resolve() == repo:
        sys.exit(f"refused: cache {d} is inside the repo; game data must stay out of it")
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_index(args):
    d = cache_dir(args)
    db = sqlite3.connect(d / "index.sqlite")
    db.execute("create table if not exists occ(hash integer, file text, word integer)")
    db.execute("create index if not exists occ_h on occ(hash)")
    imgs = d / "images"
    if args.action == "build":
        lower_priority()
        from naughty_lu import LuFile
        imgs.mkdir(exist_ok=True)
        interest = set(nb_names.load())
        if args.hashes:
            interest |= set(read_targets(args.hashes))
        # sentinels and small integers are not names; 0xffffffff alone would be ~98% of the rows
        interest = {h for h in interest if 0x10000 <= h < 0xFFFFFFF0}
        want = np.array(sorted(interest), dtype=np.uint32)
        db.execute("delete from occ")
        for f in sorted(Path(args.assets).glob("*.lu")):
            img = imgs / (f.stem + ".bin")
            if not img.exists():
                try:
                    img.write_bytes(bytes(LuFile(str(f)).image))
                except Exception as e:
                    print("skip", f.name, e)
                    continue
            b = img.read_bytes()
            a = np.frombuffer(b[: len(b) // 4 * 4], dtype=">u4").astype(np.uint32)
            idx = np.nonzero(np.isin(a, want))[0]
            db.executemany("insert into occ values (?,?,?)", ((int(a[i]), f.stem, int(i)) for i in idx))
        db.commit()
        db.execute("vacuum")                      # a rebuild otherwise keeps the old rows' space
        print(db.execute("select count(*), count(distinct hash), count(distinct file) from occ").fetchone(),
              "(occurrences, hashes, files)")
    else:                                         # where
        known = nb_names.load()
        for h in read_targets(args.hashes):
            rows = db.execute("select file, word from occ where hash=? limit ?", (h, args.limit)).fetchall()
            n = db.execute("select count(*), count(distinct file) from occ where hash=?", (h,)).fetchone()
            print(f"{h:08x} {known.get(h, '?')}: {n[0]} occurrences in {n[1]} files")
            for file, w in rows:
                b = (imgs / (file + ".bin")).read_bytes()
                a = np.frombuffer(b[: len(b) // 4 * 4], dtype=">u4")
                ctx = [("*" if j == w else "") + known.get(int(a[j]), "?" if int(a[j]) > 0xFFFF else ".")
                       for j in range(max(0, w - 6), min(len(a), w + 7))]
                print("   ", file, " ".join(ctx))


# ---------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def budgeted(p):
        p.add_argument("--max-false", type=float, default=0.1, help="refuse above this many expected chance matches")
        p.add_argument("--force", action="store_true", help="run even over the budget")
        p.add_argument("--jobs", type=int, default=default_jobs())

    p = sub.add_parser("brute", help="PREFIX + X over an alphabet")
    p.add_argument("prefix"); p.add_argument("targets")
    p.add_argument("--suffix", default=""); p.add_argument("--len", type=int, default=5)
    p.add_argument("--alphabet", default=string.ascii_lowercase)
    budgeted(p)

    p = sub.add_parser("words", help="PREFIX + 1-3 tokens (+ SUFFIX), meet in the middle")
    p.add_argument("prefix"); p.add_argument("targets")
    p.add_argument("--suffix", default=""); p.add_argument("--depth", type=int, default=2)
    p.add_argument("--seps", default=",_", help="comma list of separators between tokens")
    p.add_argument("--vocab", nargs="*"); p.add_argument("--tokens")
    p.add_argument("--known-tokens", action="store_true", help="add tokens of every known name")
    p.add_argument("--max-token", type=int, default=16)
    budgeted(p)

    p = sub.add_parser("typos", help="names within 1-2 edits of predicted names")
    p.add_argument("targets"); p.add_argument("names", nargs="+")
    p.add_argument("--distance", type=int, choices=(1, 2), default=1)
    budgeted(p)

    p = sub.add_parser("siblings", help="test the numbered/paired siblings of every known name")
    p.add_argument("targets")
    p.add_argument("--affixes", type=int, default=0, metavar="N",
                   help="also put the N most common known endings on every known name")
    p.add_argument("--learned", type=int, default=0, metavar="K",
                   help="also apply token swaps learned from known name pairs seen in >= K contexts")
    p.add_argument("--emit", help="write non-junk hits as {hash: Name} JSON, capitalisation restored")
    p.add_argument("--extra-names", help="file of more names (one per line) that teach patterns, e.g. NB2's")
    budgeted(p)

    p = sub.add_parser("score", help="plausibility of names (lower is better)")
    p.add_argument("names", nargs="+")

    p = sub.add_parser("index", help="build or query the asset hash index")
    p.add_argument("action", choices=("build", "where"))
    p.add_argument("--assets", help="folder of .lu files (build)")
    p.add_argument("--hashes", help="extra hashes to index (build) / hashes to look up (where)")
    p.add_argument("--cache"); p.add_argument("--limit", type=int, default=3)

    args = ap.parse_args(argv)
    {"brute": cmd_brute, "words": cmd_words, "typos": cmd_typos, "siblings": cmd_siblings,
     "score": cmd_score, "index": cmd_index}[args.cmd](args)


if __name__ == "__main__":
    main()
