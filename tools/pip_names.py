#!/usr/bin/env python3
"""
pip_names.py — names for Panic in Paradise animation clips, states and rigs.

Everything here is read from the shipped files (PIP_FORMAT.md section 11):

  * The scripts are plaintext Lua and carry every hashed literal with its
    source string: --[[HASH:"ST_Idle":0x977c680c]]2541512716. That is the
    vocabulary. All literals are CRC32(lowercase).
  * An anim-set (04300012, one per animated object, record hash =
    CRC32(model name): "hero", "common", "wardrobe01") lists its layers
    {layer name, 0430000d}{layer record, 0430000e}, its blend-tree states
    {state key, 04300008}{node, 04300009} and its animations
    {anim key, 04300002}{event track, 04300003}.
  * A layer record (0430000e) holds the state machine: one 0430000f record
    per state, named by the UNSEEDED CRC32 the scripts pass to
    PlayAnimState, pointing at either an anim key (04300002) or a state
    key (04300008 -> node 04300009 -> several anim keys).
  * anim key == clip record hash (719 of 719), so state -> clip is direct.
  * An anim key is CRC32(lowercase name) continued from a start value:
        key = zlib.crc32(name, SEED)
    SEED_A 0000111b is the anim-key seed (NB1: 0000191d). A second start
    value, SEED_B 06b9c673, covers the animations shared by every bear
    (same linear relation, so it is a fixed prefix or a second seed; which
    string it stands for is not solved). State keys keep NB1's seed
    1b0eca1d.

  * Names the scripts never spell out are DERIVED by the rules the Lua
    itself uses to build them at run time (derive_names):
        uk        "ST_UK" + move [+ "_Receive" | "_Camera"[zone]]
                  (libraryweapon.lua; the moves are the string tables the
                  weapon scripts pass to RegisterCharacterAnimationBank)
        suffix    known name + "_Receive" / "_Camera" / "_XNeg" / "_XPos" /
                  "_Top" (librarycamera.lua AddCameraZone)
        suicide   "ST_Suicide" + weapon type name
        object    "st_" + ["cs" | "ck" | "stealthkill"] + object name + tail
        swap      known name with its tail piece swapped (in/out/loop, l/r)
        vocab     a name from a --vocab file (NB1's cracked names)
    A derived name is accepted only when its hash is an existing state,
    anim key or state key. Expected chance hits over all rules: under 1
    (printed per rule); the rule is written next to every such name.

A clip therefore gets, in order of strength:
    anim_name   exact: key(name) == clip hash, under seed A or B
    states      every state that plays it, with the state's script name
    events      names of the script events on its event track
    animsets    the models whose anim-set lists it

usage:
  python pip_names.py <pip_decoded> <scripts_dir> -o <out_dir>
      writes clip_names.tsv, state_names.tsv, rig_names.tsv
"""
import argparse
import csv
import glob
import os
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict

SEED_A = 0x0000111B
SEED_B = 0x06B9C673
SEED_STATE_KEY = 0x1B0ECA1D
T_CLIP, T_ANIMKEY, T_EVENT = 0x04300000, 0x04300002, 0x04300003
T_STATEKEY, T_NODE, T_LAYERNAME, T_LAYER, T_STATE = (
    0x04300008, 0x04300009, 0x0430000D, 0x0430000E, 0x0430000F)
T_ANIMSET = 0x04300012

HASH_RE = re.compile(r'--\[\[HASH:"([^"]*)":0x([0-9a-fA-F]+)\]\]')
FUNC_RE = re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_.:]*)\s*\(")


def key(name, seed):
    return zlib.crc32(name.lower().encode("latin-1", "replace"), seed) & 0xFFFFFFFF


def crc(name):
    return zlib.crc32(name.lower().encode("latin-1", "replace")) & 0xFFFFFFFF


# ------------------------------------------------------------------ scripts

class Scripts:
    """lit: crc -> source spelling of every HASH literal; ctx: crc ->
    {file:function} that use it; words: every identifier and quoted string
    (lowercase), the wider vocabulary for exact anim names."""

    def __init__(self, root):
        self.lit, self.ctx, self.words = {}, defaultdict(set), set()
        self.quoted = set()
        self.files = 0
        for p in glob.glob(os.path.join(root, "**", "*.lua"), recursive=True):
            txt = open(p, encoding="utf-8", errors="replace").read()
            self.files += 1
            rel = os.path.splitext(os.path.basename(p))[0]
            funcs = [(m.start(), m.group(1)) for m in FUNC_RE.finditer(txt)]
            for m in HASH_RE.finditer(txt):
                name, h = m.group(1), int(m.group(2), 16)
                if crc(name) != h:
                    continue
                self.lit.setdefault(h, name)
                f = next((n for pos, n in reversed(funcs) if pos < m.start()), "")
                self.ctx[h].add(rel + (":" + f if f else ""))
            self.words.update(s.lower() for s in re.findall(r'"([^"\n]{2,80})"', txt))
            self.quoted.update(re.findall(r'"([A-Za-z0-9_]{2,40})"', txt))
            self.quoted.update(re.findall(r"'([A-Za-z0-9_]{2,40})'", txt))
            self.words.update(s.lower() for s in re.findall(r"'([^'\n]{2,80})'", txt))
            self.words.update(w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,60}", txt))
        self.words.update(n.lower() for n in self.lit.values())


# ------------------------------------------------------------------- corpus

def read_manifest(unit):
    out = {}
    try:
        with open(os.path.join(unit, "manifest.tsv"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                p = ln.rstrip("\n").split("\t")
                if p[0].isdigit() and len(p) > 3:
                    out[int(p[0])] = (int(p[1], 16), p[2], int(p[3], 16))
    except OSError:
        pass
    return out


def rec_of(man, path):
    try:
        return man.get(int(os.path.basename(path).split("_", 1)[0]))
    except ValueError:
        return None


def parse_animset(d):
    """-> dict(bones, layers, state_keys, anim_keys) or None."""
    if len(d) < 0x60 or struct.unpack_from(">I", d, 0)[0] != T_ANIMSET:
        return None
    w = struct.unpack_from(">24I", d, 0)
    pp, pn, end = w[5], w[6], w[13]
    bp, bn = w[17], w[18]
    if pp + 16 * pn > len(d) or bp + 4 * bn > len(d):
        return None
    out = {"bones": list(struct.unpack_from(f">{bn}I", d, bp)) if bn else [],
           "layers": [], "state_keys": {}, "anim_keys": {}}
    for i in range(pn):
        h, t, h2, t2 = struct.unpack_from(">4I", d, pp + 16 * i)
        if t == T_LAYERNAME and t2 == T_LAYER:
            out["layers"].append((h, h2))
        elif t == T_STATEKEY and t2 == T_NODE:
            out["state_keys"][h] = h2
        elif t == T_ANIMKEY and t2 == T_EVENT:
            out["anim_keys"][h] = h2
    return out


def parse_layer(d):
    """Layer record -> [(state name crc, ref hash, ref type)]. +0x30 is a
    list of {0430000f, state offset}; a state is {0430000f, 0, name crc,
    0430000f, ref hash, ref type, layer hash, 0430000e, ...}."""
    out, o = [], 0x30
    while o + 8 <= len(d) and struct.unpack_from(">I", d, o)[0] == T_STATE:
        so = struct.unpack_from(">I", d, o + 4)[0]
        if so + 0x18 <= len(d) and struct.unpack_from(">I", d, so)[0] == T_STATE:
            nm, _t, rh, rt = struct.unpack_from(">4I", d, so + 8)
            out.append((nm, rh, rt))
        o += 8
    return out


def parse_node(d):
    """Blend-tree node -> anim keys it references, in file order."""
    out = []
    for o in range(0, len(d) - 7, 4):
        h, t = struct.unpack_from(">2I", d, o)
        if t == T_ANIMKEY and h not in out:
            out.append(h)
    return out


def parse_event_track(d):
    """-> (clip hash, [event name hashes]) or None. +0x10 {clip, 04300000};
    events are 04800026 records {.., name hash at +0x0c}."""
    if len(d) < 0x18 or struct.unpack_from(">I", d, 0x14)[0] != T_CLIP:
        return None
    clip = struct.unpack_from(">I", d, 0x10)[0]
    ev = []
    if len(d) >= 0x54 and struct.unpack_from(">I", d, 0x40)[0] == 0xAABBCCDD:
        lp, ln = struct.unpack_from(">2I", d, 0x48)
        for i in range(ln):
            if lp + 8 * i + 8 > len(d):
                break
            t, off = struct.unpack_from(">2I", d, lp + 8 * i)
            if t == 0x04800026 and off + 0x10 <= len(d):
                h = struct.unpack_from(">I", d, off + 0x0C)[0]
                if h and h not in ev:
                    ev.append(h)
    return clip, ev


class Corpus:
    def __init__(self, root):
        self.clips = {}                       # clip hash -> clip rig id
        self.clip_units = defaultdict(set)
        self.clip_events = defaultdict(list)  # clip hash -> event name hashes
        self.animsets = {}                    # animset hash -> dict
        self.layers = {}                      # layer hash -> [(name, ref, type)]
        self.nodes = {}                       # node hash -> [anim keys]
        self.ev_clip = {}
        self.names = {}                       # record hash -> manifest name
        units = sorted(p for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p))
        self.units = [os.path.basename(u) for u in units]
        for u in units:
            un = os.path.basename(u)
            man = read_manifest(u)
            for h, name, _t in man.values():
                if name:
                    self.names.setdefault(h, name)
            for p in glob.glob(os.path.join(u, "type_04300000", "*.bin")):
                with open(p, "rb") as f:
                    d = f.read(0x60)
                if len(d) < 0x60:
                    continue
                h = struct.unpack_from(">I", d, 8)[0]
                self.clips.setdefault(h, struct.unpack_from(">I", d, 0x5C)[0])
                self.clip_units[h].add(un)
            for p in glob.glob(os.path.join(u, "type_04300003", "*.bin")):
                rec = rec_of(man, p)
                if rec is None or rec[0] in self.ev_clip:
                    continue
                r = parse_event_track(open(p, "rb").read())
                if r is None:
                    continue
                self.ev_clip[rec[0]] = r[0]
                for e in r[1]:
                    if e not in self.clip_events[r[0]]:
                        self.clip_events[r[0]].append(e)
            for p in glob.glob(os.path.join(u, "type_04300009", "*.bin")):
                rec = rec_of(man, p)
                if rec and rec[0] not in self.nodes:
                    self.nodes[rec[0]] = parse_node(open(p, "rb").read())
            for p in glob.glob(os.path.join(u, "type_0430000e", "*.bin")):
                rec = rec_of(man, p)
                if rec and rec[0] not in self.layers:
                    self.layers[rec[0]] = parse_layer(open(p, "rb").read())
            for p in glob.glob(os.path.join(u, "type_04300012", "*.bin")):
                rec = rec_of(man, p)
                if rec is None:
                    continue
                a = self.animsets.get(rec[0])
                if a is None:
                    a = parse_animset(open(p, "rb").read())
                    if a is None:
                        continue
                    a["hash"], a["name"], a["units"] = rec[0], rec[1], []
                    self.animsets[rec[0]] = a
                a["units"].append(un)

    def animset_label(self, a):
        return a["name"] or f"animset_{a['hash']:08x}"

    def state_clips(self, a, ref, rtype):
        """Clips a state of anim-set `a` plays: its anim key, or the anim
        keys of the blend-tree node its state key names."""
        if rtype == T_ANIMKEY:
            keys = [ref]
        elif rtype == T_STATEKEY:
            keys = self.nodes.get(a["state_keys"].get(ref), [])
        else:
            keys = []
        return [k for k in keys if k in self.clips]


def name_animsets(corpus, scripts):
    """An anim-set record hash is CRC32(model name). naughty_lu resolves it
    only from strings in the same container; try the whole script
    vocabulary and the unit names for the ones it left blank."""
    todo = {a["hash"]: a for a in corpus.animsets.values() if not a["name"]}
    if not todo:
        return 0
    n = 0
    for w in set(scripts.words) | {u.lower() for u in corpus.units}:
        a = todo.get(zlib.crc32(w.encode("latin-1", "replace")) & 0xFFFFFFFF)
        if a is not None and not a["name"]:
            a["name"] = w
            n += 1
    return n


def load_vocab(paths):
    """Text or TSV files, one name per line (first field)."""
    out = set()
    for path in paths or ():
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                n = ln.split("\t")[0].strip()
                if re.fullmatch(r"[A-Za-z0-9_]{2,60}", n):
                    out.add(n)
    return out


UK_SUFFIX = ["_Receive", "_Camera", "_XNeg", "_XPos", "_Top", "_Hurt"]
OBJ_TAIL = ["", "idle", "in", "out", "loop", "_in", "_out", "_loop", "_receive", "_camera",
            "_escape", "_help", "01", "02", "03", "_idle", "start", "end"]
SWAP_TAIL = ["in", "out", "loop", "idle", "start", "end", "l", "r", "_l", "_r", "fwd", "bwd",
             "_fwd", "_bwd", "left", "right", "_in", "_out", "_loop", "01", "02", "03", "04",
             "05", "2", "3", "_01", "_02", "_03"]
SWAP_FROM = ["in", "out", "loop", "idle", "start", "end", "_in", "_out", "_loop", "01", "02",
             "l", "r", "fwd", "bwd", "left", "right"]


def derive_names(corpus, scripts, vocab):
    """-> (state crc -> (name, rule), clip hash -> (name, seed tag, rule),
    report lines). See the module docstring for the rules."""
    states, statekeys = set(), set()
    for a in corpus.animsets.values():
        statekeys.update(a["state_keys"])
        for _ln, lh in a["layers"]:
            states.update(nm for nm, _r, _t in corpus.layers.get(lh, []))
    un_state = {x for x in states if x not in scripts.lit}
    clips = set(corpus.clips)
    known = set(scripts.lit.values()) | vocab
    chains = [""] + UK_SUFFIX + [x + y for x in UK_SUFFIX for y in UK_SUFFIX if x != y]
    objs = ({a["name"] for a in corpus.animsets.values() if a["name"]} | set(corpus.units)
            | scripts.quoted)
    objs = {o for o in objs if not o.lower().startswith("st_")}

    def swaps():
        for n in known:
            nl = n.lower()
            for t in SWAP_TAIL:
                yield nl + t
            for t in SWAP_FROM:
                if nl.endswith(t) and len(nl) > len(t) + 3:
                    base = nl[:-len(t)]
                    yield base
                    for u in SWAP_TAIL:
                        yield base + u

    rules = [
        ("vocab", lambda: iter(vocab)),
        ("uk", lambda: ("ST_UK" + m + c for m in scripts.quoted for c in chains)),
        ("suicide", lambda: ("ST_Suicide" + m for m in scripts.quoted)),
        ("suffix", lambda: (n + c for n in known for c in chains[1:])),
        ("object", lambda: ("st_" + pre + o + t for o in objs
                            for pre in ("", "cs", "ck", "stealthkill") for t in OBJ_TAIL)),
        ("swap", swaps),
    ]
    st, cl, sk, report = {}, {}, {}, []
    ntarget = len(un_state) + 2 * len(clips) + len(statekeys)
    for rule, gen in rules:
        seen, hits = set(), Counter()
        for name in gen():
            nl = name.lower().encode("latin-1", "replace")
            if nl in seen:
                continue
            seen.add(nl)
            c = zlib.crc32(nl) & 0xFFFFFFFF
            if c in un_state and c not in st:
                st[c] = (name, rule)
                hits["state"] += 1
            for seed, tag in ((SEED_A, "A"), (SEED_B, "B")):
                k = zlib.crc32(nl, seed) & 0xFFFFFFFF
                if k in clips and (k not in cl or tag == "A" and cl[k][1] == "B"):
                    cl[k] = (name, tag, rule)
                    hits["clip" + tag] += 1
            k = zlib.crc32(nl, SEED_STATE_KEY) & 0xFFFFFFFF
            if k in statekeys and k not in sk:
                sk[k] = (name, rule)
                hits["statekey"] += 1
        report.append(f"derived by {rule:8s} {len(seen):8d} candidates, new hits "
                      f"{dict(hits) or 0}, expected by chance {len(seen) * ntarget / 2**32:.3f}")
    return st, cl, sk, report


def build(corpus, scripts, vocab=()):
    """-> (clip rows, state rows). A clip row is a dict."""
    exact = {}
    for w in scripts.words:
        for seed, tag in ((SEED_A, "A"), (SEED_B, "B")):
            k = zlib.crc32(w.encode("latin-1", "replace"), seed) & 0xFFFFFFFF
            if k in corpus.clips and (k not in exact or tag == "A" and exact[k][1] == "B"):
                exact[k] = (w, tag, "script")
    d_state, d_clip, _d_sk, report = derive_names(corpus, scripts, set(vocab))
    for k, v in d_clip.items():
        exact.setdefault(k, (v[0], v[1], v[2]))
    lit = dict(scripts.lit)
    lit_rule = {}
    for c, (n, rule) in d_state.items():
        lit[c], lit_rule[c] = n, rule
    corpus.derive_report = report
    scripts = _Named(scripts, lit)
    clip_states = defaultdict(lambda: defaultdict(set))   # clip -> state crc -> {how}
    clip_sets = defaultdict(set)
    state_rows = {}
    for a in corpus.animsets.values():
        lab = corpus.animset_label(a)
        for k in a["anim_keys"]:
            if k in corpus.clips:
                clip_sets[k].add(lab)
        for _ln, lh in a["layers"]:
            for nm, ref, rt in corpus.layers.get(lh, []):
                cl = corpus.state_clips(a, ref, rt)
                how = "direct" if rt == T_ANIMKEY else "blend"
                for c in cl:
                    clip_states[c][nm].add(how)
                r = state_rows.setdefault(nm, {"state": nm, "name": scripts.lit.get(nm, ""),
                                               "rule": lit_rule.get(nm, "script" if nm in lit else ""),
                                               "animsets": set(), "clips": set(), "how": set()})
                r["animsets"].add(lab)
                r["clips"].update(cl)
                r["how"].add(how)
    spell = {n.lower(): n for n in scripts.lit.values()}
    rows = []
    for c in sorted(corpus.clips):
        sts = clip_states.get(c, {})
        named = sorted(((scripts.lit[s], sorted(h)) for s, h in sts.items() if s in scripts.lit),
                       key=lambda x: (x[1] != ["direct"], len(x[0]), x[0].lower()))
        unnamed = sorted(f"?{s:08x}" for s in sts if s not in scripts.lit)
        ex = exact.get(c)
        # label candidates, strongest first: the clip's own name, the states
        # that play it directly, the states that reach it through a blend tree
        cands = []
        if ex:
            cands.append((spell.get(ex[0], ex[0]), "anim" + ex[1], ex[2]))
        rule_of = {scripts.lit[s_]: lit_rule.get(s_, "script") for s_ in sts if s_ in scripts.lit}
        for n, h in named:
            cands.append((n, "state" if h == ["direct"] else "blend", rule_of[n]))
        ctx = sorted({x for s in sts for x in scripts.ctx.get(s, ())})
        rows.append({
            "clip": c, "label": "", "label_source": "", "cands": cands,
            "anim_name": ex[0] if ex else "", "seed": ex[1] if ex else "", "name_rule": "",
            "states": [n for n, _h in named] + unnamed,
            "scripts": ctx,
            "events": [scripts.lit.get(e, f"?{e:08x}") for e in corpus.clip_events.get(c, [])],
            "animsets": sorted(clip_sets.get(c, ())),
            "clip_rig": corpus.clips[c], "units": sorted(corpus.clip_units[c])})
    assign_labels(rows)
    return rows, list(state_rows.values())


class _Named:
    """Scripts view whose literal table also holds the derived names."""

    def __init__(self, scripts, lit):
        self.lit, self.ctx, self.words, self.files = lit, scripts.ctx, scripts.words, scripts.files


RANK = {"animA": 0, "animB": 1, "state": 2, "blend": 3}


def assign_labels(rows):
    """One unique label per clip. A name can fit several clips (the same
    name under seed A and seed B is two clips; one state plays different
    clips on different models; a blend tree has several clips). The
    strongest claim keeps the plain name, the others fall to their next
    candidate, then to name@model, then to name.N."""
    taken = {}
    pending = sorted((r for r in rows if r["cands"]),
                     key=lambda r: (RANK[r["cands"][0][1]], r["clip"]))
    for depth in range(8):
        nxt = []
        for r in pending:
            if depth < len(r["cands"]):
                n, src, rule = r["cands"][depth]
                if n.lower() not in taken:
                    taken[n.lower()] = r
                    r["label"], r["label_source"], r["name_rule"] = n, src, rule
                    continue
                nxt.append(r)
            else:
                nxt.append(r)
        pending = [r for r in nxt if depth + 1 < len(r["cands"])]
        done = [r for r in nxt if depth + 1 >= len(r["cands"])]
        for r in done:
            n, src, rule = r["cands"][0]
            r["name_rule"] = rule
            sets = [a for a in r["animsets"] if not a.startswith("animset_")] or r["animsets"]
            lab = f"{n}@{min(sets, key=len)}" if sets else n
            k = 1
            base = lab
            while lab.lower() in taken:
                k += 1
                lab = f"{base}.{k}"
            taken[lab.lower()] = r
            r["label"], r["label_source"] = lab, src
        if not pending:
            break


def short(lst, n):
    return ";".join(lst[:n]) + (f";+{len(lst) - n}" if len(lst) > n else "")


def write(rows, states, corpus, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "clip_names.tsv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["clip", "label", "label_source", "name_rule", "anim_name", "seed", "states", "scripts",
                    "events", "animsets", "clip_rig", "units"])
        for r in rows:
            w.writerow([f"{r['clip']:08x}", r["label"], r["label_source"], r["name_rule"], r["anim_name"],
                        r["seed"], short(r["states"], 12), short(r["scripts"], 8),
                        short(r["events"], 12), short(r["animsets"], 8),
                        f"{r['clip_rig']:08x}", short(r["units"], 4)])
    with open(os.path.join(out, "state_names.tsv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["state_crc", "name", "name_rule", "how", "clips", "animsets"])
        for r in sorted(states, key=lambda r: (r["name"] == "", r["name"].lower(), r["state"])):
            w.writerow([f"{r['state']:08x}", r["name"], r["rule"], "+".join(sorted(r["how"])),
                        short([f"{c:08x}" for c in sorted(r["clips"])], 16),
                        short(sorted(r["animsets"]), 8)])
    with open(os.path.join(out, "rig_names.tsv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["animset", "name", "bones", "states", "anims", "units"])
        for a in sorted(corpus.animsets.values(), key=lambda a: corpus.animset_label(a)):
            ns = sum(len(corpus.layers.get(lh, [])) for _n, lh in a["layers"])
            w.writerow([f"{a['hash']:08x}", a["name"], len(a["bones"]), ns,
                        len(a["anim_keys"]), short(sorted(set(a["units"])), 4)])


def summary(rows, states, corpus, scripts):
    src = Counter(r["label_source"] or "none" for r in rows)
    lines = [
        f"scripts {scripts.files}, HASH literals {len(scripts.lit)}, vocabulary {len(scripts.words)}",
        f"anim-sets {len(corpus.animsets)} ({sum(1 for a in corpus.animsets.values() if a['name'])} named), "
        f"layers {len(corpus.layers)}, nodes {len(corpus.nodes)}, event tracks {len(corpus.ev_clip)}",
        f"clips {len(rows)}: exact anim name {sum(1 for r in rows if r['anim_name'])} "
        f"(seed A {sum(1 for r in rows if r['seed'] == 'A')}, seed B {sum(1 for r in rows if r['seed'] == 'B')}), "
        f"with a named state {sum(1 for r in rows if any(not s.startswith('?') for s in r['states']))}, "
        f"played by any state {sum(1 for r in rows if r['states'])}, "
        f"labelled {sum(1 for r in rows if r['label'])}",
        "label source: " + ", ".join(f"{k} {v}" for k, v in src.most_common()),
        f"states {len(states)}: named {sum(1 for s in states if s['name'])} "
        f"(from script literals {sum(1 for s in states if s['rule'] == 'script')})",
        "clip name rule: " + ", ".join(f"{k} {v}" for k, v in Counter(
            r["name_rule"] or "none" for r in rows).most_common()),
    ] + list(getattr(corpus, "derive_report", []))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("corpus")
    ap.add_argument("scripts")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--vocab", action="append", default=[],
                    help="extra name list (one per line or TSV first field), e.g. NB1's names")
    args = ap.parse_args()
    scripts = Scripts(args.scripts)
    corpus = Corpus(args.corpus)
    name_animsets(corpus, scripts)
    rows, states = build(corpus, scripts, load_vocab(args.vocab))
    write(rows, states, corpus, args.out)
    s = summary(rows, states, corpus, scripts)
    with open(os.path.join(args.out, "names_summary.txt"), "w", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s)


if __name__ == "__main__":
    main()
