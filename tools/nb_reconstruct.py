#!/usr/bin/env python3
r"""Rebuild hashed names from the conventions they follow."""
import argparse
import collections
import re
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import nb_names

NAMED = re.compile(r'(--\[\[HASH:[^\]]*\]\])0x[0-9a-f]{8}')
TEXT_ONLY = re.compile(r'--\[\[TEXT[^\]]*\]\](0x[0-9a-f]{8})')
BARE = re.compile(r"0x([0-9a-f]{8})\b")


def crc(s):
    return zlib.crc32(s.lower().encode("latin-1", "replace")) & 0xFFFFFFFF


# CRC32 can be run backwards over bytes you already know. Given the hash of
# "ep1_cha1_objectives_obj3" and the ending "3", unappend() returns the hash
# of "ep1_cha1_objectives_obj" exactly. That turns a family of names that
# differ only in their ending (obj1, obj2, obj3...) into ONE hash to search
# for, and it shows the family exists before anything about it is guessed.
_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xEDB88320 if _c & 1 else _c >> 1
    _TABLE.append(_c)
_TOP_BYTE = {t >> 24: i for i, t in enumerate(_TABLE)}


def unappend(h, ending):
    """crc(prefix + ending), ending -> crc(prefix)."""
    reg = h ^ 0xFFFFFFFF
    for b in reversed(ending.lower().encode("latin-1", "replace")):
        i = _TOP_BYTE[reg >> 24]
        reg = (((reg ^ _TABLE[i]) << 8) & 0xFFFFFFFF) | (i ^ b)
    return reg ^ 0xFFFFFFFF


NUMBER_STYLES = ("{}", "{:02d}", "{:03d}")


def numbered_families(hashes, least=3, top=60):
    """Groups of hashes that are one unknown prefix plus a run of numbers.

    -> {(prefix hash, number style, first number): {number: hash}}, for
    runs of at least `least` consecutive numbers. The same group can show
    up under a few styles (an equal-length ending aliases), so it is the
    caller's context that picks one; a group matching by chance needs
    `least` independent 32-bit coincidences."""
    out = {}
    for style in NUMBER_STYLES:
        for start in (0, 1):
            by_prefix = collections.defaultdict(dict)
            for h in hashes:
                for n in range(start, start + top):
                    by_prefix[unappend(h, style.format(n))][n] = h
            for p, members in by_prefix.items():
                ns = sorted(members)
                if len(ns) >= least and ns == list(range(start, start + len(ns))):
                    out[(p, style, start)] = members
    return out


def unlabelled_text(text):
    """The script with every already NAMED hash taken out, so a rule only
    sees hashes that still need a name. A hash labelled only with its
    display text still does: the text says what the player sees, the name
    is what the code calls it. A named hash keeps its label, so rules can
    still learn from the names around them (owners, prefixes)."""
    return TEXT_ONLY.sub(r"\1", NAMED.sub(r"\1<known>", text))


# ------------------------------------------------------------------ rules
# A rule: (script text, file stem) -> iterable of (hash, [candidates]).

# engine variable proxies: the hash names the variable, after the Lua
# name it is stored in
VAR_CALL = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)(?:\[([^\]\n]*)\])?\s*=\s*"
    r"(?:Bool|Int|Float|String|Uint32|UInt32|Vector|Vector4|Hash|HashedString)"
    r"\(0x([0-9a-f]{8})\b", re.M)
CLASS_DEF = re.compile(r"^function ([A-Za-z_]\w*)[:.]", re.M)
# MonitoringUtilMP_iCollectedJelly_Variable -> owner MonitoringUtilMP
VARIABLE_OWNER = re.compile(r'HASH:"([A-Za-z]\w*?)_\w+_Variable"')


def rule_variable_names(text, stem, container):
    """`self.bGameFinishSuccessful = Bool(0x..)` ->
    MonitoringUtilMP_bGameFinishSuccessful_Variable. The owner is a class
    defined in the script or one that the script's named variables already
    use; the type letter (i, b) is sometimes dropped; an array slot
    `iDancingTime[2]` is numbered: MonitoringUtilMP_iDancingTime2_Variable."""
    classes = set(CLASS_DEF.findall(text)) | set(VARIABLE_OWNER.findall(text))
    for lhs, index, h in VAR_CALL.findall(text):
        parts = lhs.split(".")
        last = parts[-1]
        owners = [p for p in parts[:-1] if p != "self"]
        if parts[0] == "self":
            owners = sorted(classes) or owners
        lasts = {last}
        if re.match(r"[ib][A-Z]", last):
            lasts.add(last[1:])
        if index:
            m = re.search(r"(\d+)\s*$", index)
            if not m:
                continue
            lasts = {f"{v}{m.group(1)}" for v in lasts} | \
                    {f"{v}_{m.group(1)}" for v in lasts}
        cands = set()
        for v in lasts:
            cands |= {v, "_".join(parts[:-1] + [v]),
                      "_".join([p for p in parts[:-1] if p != "self"] + [v])}
            for owner in owners:
                cands |= {f"{owner}_{v}", f"{owner}.{v}"}
        cands |= {c + "_Variable" for c in list(cands)}
        yield int(h, 16), sorted(cands)


# any constructor-style call taking the hash first:
#     effect_bearBlockHit = engine.EffectDefinition_Create(<"bearBlockHit">)
CTOR_CALL = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*[\w.:]+\(\s*"
    r"(?:--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})\b", re.M)


def rule_constructed_names(text, stem, container):
    """`effect_bloodNPC = engine.EffectDefinition_Create(0x..)` ->
    bloodNPC: the thing a constructor makes is named after the variable
    that holds it, less a leading word or two (effect_, g, s...)."""
    for lhs, h in CTOR_CALL.findall(text):
        last = lhs.split(".")[-1]
        toks, seps = split_name(last)
        cands = {last}
        for drop in (1, 2):
            if len(toks) > drop:
                rest, rs = toks[drop:], seps[drop:]
                cands.add(join_name(rest, rs))
                cands.add("".join(rest))
                cands.add("_".join(rest))
        yield int(h, 16), sorted(cands)


NPCDEF = re.compile(r'NPCDef\("([^"]+)",\s*0x([0-9a-f]{8})')


def rule_npc_names(text, stem, container):
    """`NPCDef("Stardust", <"npc_names_Stardust">)`: the text ID of an NPC's
    display name is built from the name itself."""
    for disp, h in NPCDEF.findall(text):
        words = re.findall(r"[A-Za-z0-9]+", disp)
        cands = set()
        for sep in ("", "_"):
            cands.add("npc_names_" + sep.join(words))
        yield int(h, 16), sorted(cands)


OBJECTIVE_CALL = re.compile(
    r"(Objective|AddSubObjective|AddProgressiveSubObjective|"
    r"AddFailSubObjective|AddOptionalSubObjective)\(0x([0-9a-f]{8})\b")


def level_names(stem, container):
    """Ways a level may be spelled in an ID: ep10challenge1, ep10_cha1..."""
    out = {container, stem}
    for src in (container, stem):
        m = re.match(r"ep(\d+)_?(story|cha|challenge|tutorial)?_?(\d+)?", src)
        if not m:
            continue
        e, mode, n = m.group(1), m.group(2) or "", m.group(3) or ""
        modes = {mode} | ({"cha", "challenge", "chal", "c"} if mode.startswith("cha") else set())
        for md in modes:
            for sep in ("", "_"):
                out.add(f"ep{e}{sep}{md}{n}")
                out.add(f"ep{e}{sep}{md}{sep}{n}" if n else f"ep{e}{sep}{md}")
                out.add(f"episode{e}{sep}{md}{n}")
    out.discard("")
    return out


def rule_objectives(text, stem, container):
    """NB2 names objectives game_objectives_<level>_obj<n> (+ _description,
    _target<n>, _optional<n>). Tried per hash with that hash's own level."""
    levels = level_names(stem, container)
    for kind, h in OBJECTIVE_CALL.findall(text):
        cands = set()
        for lvl in levels:
            for pre in ("game_objectives_", "objectives_", ""):
                for n in range(1, 31):
                    for suf in (f"_obj{n}", f"_obj{n}_description", f"_target{n}",
                                f"_optional{n}", f"_optional{n}_description",
                                f"_obj{n:02d}", f"_subobj{n}", f"_fail{n}"):
                        cands.add(pre + lvl + suf)
        yield int(h, 16), sorted(cands)


UNLOCK_ROW = re.compile(
    r'\{\s*(?:--\[\[TEXT[^\]]*\]\])?\s*0x([0-9a-f]{8}),\s*"(\w+)",\s*'
    r'engine\.e(\w+)_GRADE', re.S)


def rule_unlock_conditions(text, stem, container):
    """{0x.., "Ep1Cha2", engine.eBRONZE_GRADE}: an unlock condition's text
    ID, named after NB2's unlockable_condition_<level>_<grade> but with
    NB1's level spelling (unlockable_condition_ep1_bronze,
    unlockable_condition_ep2cha4_gold)."""
    for h, lvl, grade in UNLOCK_ROW.findall(text):
        m = re.match(r"ep(\d+)(cha|story|challenge)?(\d+)?", lvl, re.I)
        if not m:
            continue
        e, mode, n = m.group(1), (m.group(2) or "").lower(), m.group(3) or ""
        levels = {lvl.lower(), f"ep{e}", f"ep{e}{mode}{n}", f"ep{e}_{mode}{n}",
                  f"ep{e}cha{n}", f"ep{e}_cha{n}", f"ep{e}challenge{n}",
                  f"ep{e}_challenge{n}", f"level{e}_{mode}{n}"}
        g = grade.lower()
        cands = {f"{pre}{lv}{sep}{g}" for pre in ("unlockable_condition_",
                                                  "unlock_condition_")
                 for lv in levels for sep in ("_", "")}
        yield int(h, 16), sorted(cands)


SELF_ASSIGN = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.\[\]]*)\s*=\s*"
    r"(?:--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})\s*$", re.M)
AFFIX = {"hash", "id", "name", "anim", "attribute", "attr", "the", "g", "k"}


def rule_self_names(text, stem, container):
    """`ATTRIBUTE_FIREARM_AIMING_ANIM_HASH = 0x..`, `animWalkCrouchedRightFoot
    = 0x..`: the assigned name, stripped of affixes like ATTRIBUTE_ / _HASH /
    anim, joined the few ways names are joined, optionally behind a prefix
    that names in the same script already use (ST_, demo_...)."""
    prefixes = {""}
    for name in NAME_IN_COMMENT.findall(text):
        toks, seps = split_name(name)
        if len(toks) > 1:
            prefixes.add(toks[0] + seps[0])
    for lhs, h in SELF_ASSIGN.findall(text):
        base = re.sub(r"\[.*?\]", "", lhs.split(".")[-1])
        toks = [t.lower() for t in TOKEN.findall(base) if not t.isdigit() or True]
        cores = set()
        for lo in range(0, 3):
            for hi in range(len(toks), max(lo, len(toks) - 3), -1):
                core = toks[lo:hi]
                if not core or all(t in AFFIX for t in core):
                    continue
                cores.add(tuple(core))
        cands = set()
        for core in cores:
            for sep in ("", "_"):
                word = sep.join(core)
                for pre in prefixes:
                    cands.add(pre + word)
        yield int(h, 16), sorted(cands)


# Per-script rules. rule_objectives is kept but not run: NB2 names its
# objectives game_objectives_<level>_obj<n>, and 17 million candidates in
# that style matched nothing in NB1 (0.004 expected by chance) - NB1 uses
# another convention, and without a single NB1 example of it there is
# nothing to learn it from. Those hashes carry their English text instead.
RULES = [
    ("variable names", rule_variable_names),
    ("constructed things", rule_constructed_names),
    ("NPC display names", rule_npc_names),
    ("unlock conditions", rule_unlock_conditions),
    ("self-named values", rule_self_names),
]


# ------------------------------------------------------ context templates
# A hash with no rule of its own still sits among names that DO have one:
# the named hashes in the same function, in NB1 and in NB2's copy of that
# function, show how names are built there (ST_Success, stateAttack01,
# attack01StateRunning), and the words around the hash say what this one
# is about. So each of those names is used as a template and varied by one
# word: replaced, inserted or dropped, with the words taken from that same
# context. Every candidate is checked against the one hash it was made for.
TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
NAME_IN_COMMENT = re.compile(r'HASH:"([^"]+)"')
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
STRING = re.compile(r'"([^"\n]{2,40})"')
FUNC_START = re.compile(r"^(?:local\s+)?function\s+([\w.:]+)", re.M)


def split_name(name):
    """ST_Success -> (['ST', 'Success'], ['_']); attack01StateRunning ->
    (['attack', '01', 'State', 'Running'], ['', '', '']). Case is kept:
    CRC32 ignores it, but the rebuilt name should read as it was written."""
    toks, seps = [], []
    pos = 0
    for m in TOKEN.finditer(name):
        if toks:
            seps.append("_" if "_" in name[pos:m.start()] else "")
        toks.append(m.group())
        pos = m.end()
    return toks, seps


def join_name(toks, seps):
    out = toks[0] if toks else ""
    for t, s in zip(toks[1:], seps):
        out += s + t
    return out


def styled(word, like):
    """word cased the way the token it stands in for is cased."""
    if like[:1].isupper():
        return word.upper() if like.isupper() and len(like) > 1 and \
            len(word) <= len(like) else word[:1].upper() + word[1:]
    return word.lower()


def words_of(text):
    """Lower-case word tokens from identifiers, strings and names."""
    out = set()
    for w in IDENT.findall(text) + STRING.findall(text):
        out.update(t.lower() for t in TOKEN.findall(w) if not t.isdigit())
    return out


def functions(text):
    """{function name: body text} for top-level functions, plus the code
    outside any function under "<top>"."""
    out = {}
    starts = [(m.start(), m.group(1).replace(":", ".")) for m in FUNC_START.finditer(text)]
    top_end = starts[0][0] if starts else len(text)
    out["<top>"] = text[:top_end]
    for n, (at, name) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(text)
        out[name] = text[at:end]
    return out


def template_variants(name, words):
    """Every one-word change of a known name: a token replaced, a word
    inserted (joined either way), a token dropped, a word appended, digits
    renumbered."""
    toks, seps = split_name(name)
    out = set()
    if not toks:
        return out
    for i in range(len(toks)):
        like = toks[i]
        for w in words:
            ww = styled(w, like)
            out.add(join_name(toks[:i] + [ww] + toks[i + 1:], seps))
            for sep in ("", "_"):
                out.add(join_name(toks[:i] + [ww] + toks[i:],
                                  seps[:i] + [sep] + seps[i:]))
        if len(toks) > 1:
            out.add(join_name(toks[:i] + toks[i + 1:],
                              seps[:max(i - 1, 0)] + seps[i:]))
        if toks[i].isdigit():
            width = len(toks[i])
            for n in range(0, 21):
                for d in {str(n), str(n).zfill(width)}:
                    out.add(join_name(toks[:i] + [d] + toks[i + 1:], seps))
    # a trailing word appended, the way ST_Idle becomes ST_IdleInjured
    for w in words:
        for sep in ("", "_"):
            out.add(join_name(toks + [styled(w, toks[-1])], seps + [sep]))
    return out


LOCAL_LINES = 6


def local_words(body, h):
    """Words from the lines around each place hash h appears in body."""
    lines = body.splitlines()
    pat = f"0x{h:08x}"
    out = set()
    for n, line in enumerate(lines):
        if pat in line:
            out |= words_of("\n".join(lines[max(0, n - LOCAL_LINES):n + LOCAL_LINES + 1]))
    return out


MAX_TEMPLATES = 40


def local_names(body, h):
    """Known names within a few lines of each place hash h appears."""
    lines = body.splitlines()
    pat = f"0x{h:08x}"
    out = set()
    for n, line in enumerate(lines):
        if pat in line:
            window = "\n".join(lines[max(0, n - 3 * LOCAL_LINES):n + 3 * LOCAL_LINES + 1])
            out |= set(NAME_IN_COMMENT.findall(window))
    return out


def rule_context_templates(folder, nb2_folder, unnamed, known=None):
    """-> ({hash: name}, pairs tried).

    Templates: the named hashes of the same function in NB1 and in NB2's
    copy of it. Vocabulary: the words within a few lines of the hash, plus
    the templates' own words - local on purpose, both because nearby words
    are the ones that describe the hash and because a function-wide
    vocabulary in a long setup function multiplies the candidates, and the
    chance of a coincidence, for nothing."""
    known = known or {}
    nb2 = {}
    if nb2_folder:
        for f in Path(nb2_folder).rglob("*.lua"):
            nb2.setdefault(f.stem.lower(), f)
    found, pairs = {}, 0
    done = set()
    for f in sorted(Path(folder).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        key = (f.stem, raw)
        if key in done:                 # the same script in many containers
            continue
        done.add(key)
        other = {}
        if f.stem.lower() in nb2:
            other = functions(nb2[f.stem.lower()].read_text(
                encoding="utf-8", errors="replace"))
        for name, body in functions(raw).items():
            plain = unlabelled_text(body)
            bare = {int(h, 16) for h in BARE.findall(plain)} & unnamed
            bare -= set(found)
            if not bare:
                continue
            templates = set(NAME_IN_COMMENT.findall(body))
            templates |= set(NAME_IN_COMMENT.findall(other.get(name, "")))
            templates |= {c for c in found.values() if f"0x{crc(c):08x}" in body}
            if not templates:
                continue
            for h in bare:
                # in a long block (a big table, a setup function) the names
                # nearest the hash are the relevant templates; taking all of
                # them multiplies candidates, and chance matches, for nothing
                near = templates
                if len(templates) > MAX_TEMPLATES:
                    near = local_names(body, h) | set(
                        NAME_IN_COMMENT.findall(other.get(name, "")))
                    if len(near) > MAX_TEMPLATES:
                        continue
                tpl_words = {w.lower() for t in near for w in TOKEN.findall(t)
                             if not w.isdigit()}
                words = local_words(plain, h) | tpl_words
                cands = set(near)
                for t in near:
                    cands |= template_variants(t, words)
                pairs += len(cands)
                for c in cands:
                    if crc(c) == h:
                        found[h] = c
                        break
    return found, pairs


# --------------------------------------------------------- constant names
# Constants often spell out the name they hold:
#     FEAR_SCARE_TOILET = <"demo_fearevent_scare_toilet">
#     FEAR_SCARE_STOVE  = 0xdef18c57          -> demo_fearevent_scare_stove
# The named assignments teach the mapping (FEAR_ -> demo_fearevent_), a
# mapping is only used once it has been seen at least twice, and the
# constant's own name supplies the rest.
ASSIGN = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*"
    r"(?:--\[\[(HASH|TEXT)(?:\([A-Z0-9]+\))?:\"([^\"]+)\"[^\]]*\]\])?0x([0-9a-f]{8})\s*$",
    re.M)


def lhs_tokens(lhs):
    return [t.lower() for t in TOKEN.findall(lhs.split(".")[-1])]


def learn_mappings(pairs):
    """[(lhs, name)] -> Counter of (lhs prefix tokens, name prefix, sep)."""
    maps = collections.Counter()
    for lhs, name in pairs:
        lt = lhs_tokens(lhs)
        nt, seps = split_name(name)
        nl = [t.lower() for t in nt]
        k = 0
        while k < min(len(lt), len(nl)) and lt[-1 - k] == nl[-1 - k]:
            k += 1
        if k == 0:
            continue
        cut = len(nl) - k
        prefix = join_name(nt[:cut], seps[:max(cut - 1, 0)])
        if cut:
            prefix += seps[cut - 1]
        tail_sep = seps[-1] if seps else "_"
        maps[(tuple(lt[:len(lt) - k]), prefix, tail_sep)] += 1
    return maps


def rule_constant_names(folder, unnamed, known):
    """-> ({hash: name}, pairs tried, mappings used)."""
    known_pairs, bare = [], []
    seen = set()
    for f in sorted(Path(folder).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        for lhs, kind, label, h in ASSIGN.findall(raw):
            h = int(h, 16)
            if kind == "HASH" and label:
                known_pairs.append((lhs, label))
            elif h in unnamed:
                bare.append((lhs, h))
    maps = {m: n for m, n in learn_mappings(known_pairs).items() if n >= 2}
    found, pairs = {}, 0
    for lhs, h in bare:
        lt = lhs_tokens(lhs)
        cands = set()
        for (pre, name_pre, sep), _ in maps.items():
            if tuple(lt[:len(pre)]) != pre or len(lt) <= len(pre):
                continue
            rest = lt[len(pre):]
            for s in {sep, "_", ""}:
                cands.add(name_pre + s.join(rest))
        pairs += len(cands)
        for c in cands:
            if crc(c) == h:
                found[h] = c
                break
    return found, pairs, len(maps)


# ---------------------------------------------------------- call families
# The hashes passed in the same place - the first argument of
# RegisterNaughtyEventHudType, the argument of PlayAnimState - are the same
# KIND of name everywhere in the game. The named ones in that slot are the
# templates, and their own words the vocabulary: a family's names are built
# from a small shared set of parts (demo_fearevent_disabled_fridge,
# demo_fearevent_scare_stove...), so this stays tight however many members
# the family has.
CALL_OPEN = re.compile(r"([A-Za-z_][\w.:]*)\s*\(")
LABELLED_HASH = re.compile(r'--\[\[HASH:"([^"]+)"[^\]]*\]\]0x([0-9a-f]{8})')
ANY_HASH = re.compile(r'(?:--\[\[[^\]]*\]\])?0x([0-9a-f]{8})')


def call_arguments(line):
    """[(callee, position, argument text)] for every call on a line."""
    out = []
    for m in CALL_OPEN.finditer(line):
        callee = m.group(1).split(".")[-1].split(":")[-1]
        depth, arg, pos, i = 0, "", 0, m.end()
        while i < len(line):
            ch = line[i]
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                if depth == 0:
                    out.append((callee, pos, arg.strip()))
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                out.append((callee, pos, arg.strip()))
                arg, pos = "", pos + 1
                i += 1
                continue
            arg += ch
            i += 1
    return out


def rule_call_families(folder, unnamed, known, max_pairs=40_000_000):
    """-> ({hash: name}, pairs tried, families used).

    Templates: the known names in the same call slot anywhere in the game.
    Words: the family's own name parts, plus - per hash - the words around
    that hash, including its function's name, which is often the only place
    the thing it names is spelled out (DefineCakeMachineStealthKillCameras
    -> ST_CKCakeMachine, next to ST_CKBoat)."""
    names_at = collections.defaultdict(set)     # (callee, pos) -> names
    bare_at = collections.defaultdict(set)      # (callee, pos) -> hashes
    near = collections.defaultdict(set)         # hash -> local words
    seen = set()
    for f in sorted(Path(folder).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        lines = raw.splitlines()
        func = ""
        for n, line in enumerate(lines):
            m = FUNC_START.match(line)
            if m:
                func = m.group(1)
            if "0x" not in line:
                continue
            for callee, pos, arg in call_arguments(line):
                m = LABELLED_HASH.fullmatch(arg)
                if m:
                    names_at[(callee, pos)].add(m.group(1))
                    continue
                m = re.fullmatch(r"(?:--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})", arg)
                if m and int(m.group(1), 16) in unnamed:
                    h = int(m.group(1), 16)
                    bare_at[(callee, pos)].add(h)
                    window = "\n".join(lines[max(0, n - LOCAL_LINES):n + LOCAL_LINES + 1])
                    near[h] |= words_of(window) | words_of(func)
    found, pairs, families = {}, 0, 0
    for slot, hashes in sorted(bare_at.items(), key=lambda kv: -len(kv[1])):
        templates = names_at.get(slot, set())
        if len(templates) < 2:
            continue
        family_words = {w.lower() for t in templates for w in TOKEN.findall(t)
                        if not w.isdigit()}
        base = set(templates)
        for t in templates:
            base |= template_variants(t, family_words)
        todo = hashes - set(found)
        if not todo:
            continue
        used = False
        for h in sorted(todo):
            extra = near[h] - family_words
            cands = set(base)
            if extra:
                for t in templates:
                    cands |= template_variants(t, extra)
            if pairs + len(cands) > max_pairs:
                continue
            pairs += len(cands)
            used = True
            for c in cands:
                if crc(c) == h:
                    found[h] = c
                    break
        families += used
    return found, pairs, families


# ------------------------------------------------------------ line words
# Many IDs are just the words of the line they sit on, behind the head that
# the other names in the same call slot start with:
#     AddAchievement(engine.eACHIEVEMENT_JELLYWARS, <"achievement_JELLYWARS">)
#     RegisterNaughtyEventHudType(<"naughty_mp_bluewin">, "BLUE TEAM WINS!", ...)
# Candidates: a head (none, or the first one or two parts of a known name in
# the slot) followed by one to three of the line's own words, in any order.
# Runs in rounds, so a head first rebuilt in one round (naughty_mp_) is
# tried on the rest of its slot in the next.
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six",
                "seven", "eight", "nine", "ten"]
MAX_LINE_WORDS = 14
MAX_HEADS = 8


def line_words(line):
    """The words on one line of script, in their written case, first
    spelling kept: identifier parts, the words of labels and strings, digits
    also as English words, plurals also singular."""
    out = {}

    def add(w):
        out.setdefault(w.lower(), w)

    for t in re.findall(r'"([^"]*)"', line):
        for w in re.findall(r"[A-Za-z]+|\d+", t):
            add(w.lower())
    for ident in IDENT.findall(line):
        for w in TOKEN.findall(ident):
            add(w)
    for w in list(out.values()):
        low = w.lower()
        if low.isdigit() and int(low) < len(NUMBER_WORDS):
            add(NUMBER_WORDS[int(low)])
        elif low.endswith("ies") and len(low) > 4:
            add(low[:-3] + "y")
        elif low.endswith("s") and len(low) > 3 and not low.endswith("ss"):
            add(low[:-1])
    for noise in ("0x", "hash", "text"):
        out.pop(noise, None)
    return [w for w in out.values() if not re.fullmatch(r"[0-9a-f]{8}", w)]


def heads_of(name):
    toks, seps = split_name(name)
    out = set()
    for n in (1, 2):
        if len(toks) > n and seps[n - 1] == "_":
            out.add(join_name(toks[:n], seps[:n - 1]) + "_")
    return out


def rule_line_words(folder, unnamed, known):
    """-> ({hash: name}, pairs tried)."""
    import itertools
    heads_at = collections.defaultdict(collections.Counter)  # slot -> heads
    bare = collections.defaultdict(dict)       # slot -> {hash: [word lists]}
    seen = set()
    for f in sorted(Path(folder).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        for line in raw.splitlines():
            if "0x" not in line:
                continue
            for callee, pos, arg in call_arguments(line):
                m = LABELLED_HASH.fullmatch(arg)
                if m:
                    heads_at[(callee, pos)].update(heads_of(m.group(1)))
                    continue
                m = re.fullmatch(r"(?:--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})", arg)
                if m and int(m.group(1), 16) in unnamed:
                    h = int(m.group(1), 16)
                    bare[(callee, pos)].setdefault(h, []).append(line_words(line))
    found, pairs = {}, 0
    for slot, rows in bare.items():
        # the slot's commonest heads, each shared by at least two names
        heads = [""] + [hd for hd, n in heads_at[slot].most_common(MAX_HEADS) if n >= 2]
        for h, lines in rows.items():
            if h in found:
                continue
            cands = set()
            for words in lines:
                words = words[:MAX_LINE_WORDS]
                for r in (1, 2, 3):
                    for combo in itertools.permutations(words, r):
                        for sep in ("_", ""):
                            body = sep.join(combo)
                            cands.update(head + body for head in heads)
            # one hash's candidates never overlap another's, so counting
            # them per hash counts distinct pairs
            pairs += len(cands)
            for c in cands:
                if crc(c) == h:
                    found[h] = c
                    break
    return found, pairs


# ----------------------------------------------------- object actions
# The animations of an interaction are named <action><object>:
#     ST_CScareCooler      the attacker's scare      (cooler_doscareattack)
#     ST_CScaredCooler     the victim's reaction     (cooler_receivescareattack)
#     ST_StealthKillFridge / ST_StealthKilledFridge, ST_SabotageCooler ...
# Objects that look alike share one set (a toy chest plays the Cooler
# ones). Both lists are learned from the names already known, so each new
# find widens the next round; candidates are only checked against the
# unnamed hashes of interaction scripts (<object>_<action>.lua).
ACTION_NAME = re.compile(
    r"^(ST_(?:CScared|CScare|CK|CS|StealthKilled|StealthKill|Sabotage|"
    r"Repair|Fumble))([A-Z][A-Za-z]*?\d*)(In|Out|Loop|_In|_Out|_Loop)?$")
OBJECT_SUFFIXES = ("", "In", "Out", "Loop", "01", "02")


def rule_object_actions(folder, unnamed, known):
    """-> ({hash: name}, pairs tried)."""
    actions, objects = set(), set()
    for name in known.values():
        m = ACTION_NAME.match(name)
        if m:
            actions.add(m.group(1))
            objects.add(m.group(2))
    found, pairs = {}, 0
    if not actions:
        return found, pairs
    seen = set()
    for f in sorted(Path(folder).rglob("*_*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        todo = {int(h, 16) for h in BARE.findall(unlabelled_text(raw))} & unnamed
        todo -= set(found)
        if not todo:
            continue
        own = f.stem.split("_")[0]
        objs = objects | {own[:1].upper() + own[1:]}
        cands = {a + o + s for a in actions for o in objs for s in OBJECT_SUFFIXES}
        pairs += len(cands) * len(todo)
        for c in cands:
            h = crc(c)
            if h in todo:
                found.setdefault(h, c)
    return found, pairs


# ------------------------------------------------- runtime-built names
# Some names are glued together while the game runs:
#     local name = "naughty_finishingmove_" .. weapon:GetGodName()
# so the hash of every weapon's finishing move is that prefix plus a weapon
# name, and the weapon names are in the game's data as plain strings. The
# prefix is taken from the concatenation itself; it is only tried in the
# call slots where a known name already starts with it, against that
# slot's unnamed hashes.
CONCAT_PREFIX = re.compile(r'"([A-Za-z0-9_]{3,40}_)"\s*\.\.')
# local str = "naughty_conkill_" ... str = str .. objectName
ASSIGNED_PREFIX = re.compile(r'\b(\w+)\s*=\s*"([A-Za-z0-9_]{3,40}_)"')
LITERAL = re.compile(r'"([A-Za-z0-9_ ]{2,40})"')


def concat_prefixes(raw):
    out = {p.lower() for p in CONCAT_PREFIX.findall(raw)}
    for var, p in ASSIGNED_PREFIX.findall(raw):
        if re.search(rf"\b{var}\s*\.\.", raw):
            out.add(p.lower())
    return out


def object_names(known):
    """Object (god) names from the dictionary, with the numbered variants
    the game's objects come in (fridge03, sink01, bbq2)."""
    out = set()
    for name in known.values():
        base = re.split(r"[\\/]", name)[-1].split(".")[0].lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", base):
            continue
        out.add(base)
        stem = re.sub(r"\d+[a-z]?$", "", base)
        out.add(stem)
        for n in range(0, 11):
            out |= {f"{stem}{n}", f"{stem}{n:02d}"}
        out |= {f"{stem}01{s}" for s in "abc"}
    return out


def vocabulary(*folders, known=None):
    """Every string literal and every part of every known name in the given
    script folders, plus the dictionary's object names: the pieces
    runtime-built names are made from."""
    words = object_names(known) if known else set()
    for folder in folders:
        if not folder:
            continue
        for f in Path(folder).rglob("*.lua"):
            text = f.read_text(encoding="utf-8", errors="replace")
            for lit in LITERAL.findall(text):
                low = lit.lower()
                words |= {low, low.replace(" ", "_"), low.replace(" ", "")}
            for name in NAME_IN_COMMENT.findall(text):
                low = name.lower()
                words.add(low)
                words.update(p for p in re.split(r"[_ ]", low) if p)
    return words


def rule_runtime_prefixes(folder, unnamed, known, words):
    """-> ({hash: name}, pairs tried)."""
    prefixes = set()
    names_at = collections.defaultdict(set)
    bare_at = collections.defaultdict(set)
    seen = set()
    for f in sorted(Path(folder).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        prefixes |= concat_prefixes(raw)
        for line in raw.splitlines():
            if "0x" not in line:
                continue
            for callee, pos, arg in call_arguments(line):
                m = LABELLED_HASH.fullmatch(arg)
                if m:
                    names_at[(callee, pos)].add(m.group(1).lower())
                    continue
                m = re.fullmatch(r"(?:--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})", arg)
                if m and int(m.group(1), 16) in unnamed:
                    bare_at[(callee, pos)].add(int(m.group(1), 16))
    found, pairs = {}, 0
    for slot, hashes in bare_at.items():
        # a prefix is tried where a known name starts with it, or with its
        # first word (naughty_conkill_ next to naughty_finishingmove_)
        heads = set()
        for n in names_at.get(slot, ()):
            heads |= heads_of(n)
        used = {p for p in prefixes
                if any(n.startswith(p) for n in names_at.get(slot, ()))
                or any(p.startswith(hd) for hd in heads if hd.count("_") == 1)}
        todo = hashes - set(found)
        if not used or not todo:
            continue
        pairs += len(used) * len(words) * len(todo)
        for p in used:
            for w in words:
                h = crc(p + w)
                if h in todo:
                    found.setdefault(h, p + w)
    return found, pairs


# --------------------------------------------------- text-ID siblings
DIGITS = re.compile(r"\d+")


def numbered_siblings(name, top=150):
    """loading_hint_hint07 -> loading_hint_hint01..150, keeping the zero
    padding style, one digit run at a time."""
    out = set()
    for m in DIGITS.finditer(name):
        width = len(m.group())
        for n in range(0, top + 1):
            for text in {str(n), str(n).zfill(width)}:
                out.add(name[:m.start()] + text + name[m.end():])
    out.discard(name)
    return out


def text_container_siblings(containers, known):
    """NB1 keeps each group of text IDs in its own localization container
    (loadingscreen.en_us holds loading_hint_hint01..NN), so a known ID's
    numbered siblings are tried only against the unnamed IDs of the SAME
    container: a few hundred targets, not thousands.
    containers: {container: set of text-ID hashes}.
    -> ({hash: name}, candidate pairs tried, expected chance hits)"""
    found, pairs = {}, 0
    expected = 0.0
    for cont, keys in containers.items():
        unnamed = keys - set(known)
        if not unnamed:
            continue
        cands = set()
        for h in keys & set(known):
            cands |= numbered_siblings(known[h])
        pairs += len(cands) * len(unnamed)
        expected += len(cands) * len(unnamed) / 2 ** 32
        for c in cands:
            h = crc(c)
            if h in unnamed:
                found.setdefault(h, c)
    return found, pairs, expected


TEXT_WORD = re.compile(r"[a-z0-9]+")
BUTTON_TAG = re.compile(r"//\w+|'")
MAX_TEXT_WORDS = 12
TEXT_RUN = 4
TEXT_ENDINGS = ("", "2", "_2")


def text_prefixes(keys, known, stem):
    """Every '_'-ended head of the container's known IDs, plus its stem:
    demo_fearevent_disabled_toilet gives demo_, demo_fearevent_ and
    demo_fearevent_disabled_."""
    out = {"", stem + "_"}
    for h in keys & set(known):
        parts = known[h].lower().split("_")
        for i in range(1, len(parts)):
            out.add("_".join(parts[:i]) + "_")
    return out


def rule_text_words(containers, texts, known):
    """A text ID is often named with the words of its own English text:
    "You sabotaged the toilet!" is demo_fearevent_disabled_toilet, "SET
    TRAP" is hudbutton_settrap. Runs of up to four of the text's words,
    joined with '_' or nothing, go after each head that the container's
    known IDs use (see text_prefixes), tried only against that container's
    unnamed IDs.
    containers: {container: set of hashes}; texts: {hash: English text}.
    -> ({hash: name}, candidate pairs tried)"""
    found, pairs = {}, 0
    for cont, keys in containers.items():
        unnamed = [h for h in keys - set(known) if texts.get(h)]
        if not unnamed:
            continue
        heads = text_prefixes(keys, known, cont.split(".")[0])
        for h in unnamed:
            words = TEXT_WORD.findall(
                BUTTON_TAG.sub("", texts[h].lower()))[:MAX_TEXT_WORDS]
            runs = {j.join(words[i:k])
                    for i in range(len(words))
                    for k in range(i + 1, min(len(words), i + TEXT_RUN) + 1)
                    for j in ("", "_")}
            cands = {p + r + e for p in heads for r in runs
                     for e in TEXT_ENDINGS}
            pairs += len(cands)
            for c in cands:
                if crc(c) == h:
                    found.setdefault(h, c)
                    break
    return found, pairs


def load_text_containers(paths, texts=None):
    """{container stem: set of text-ID hashes} from NB1 .en_us.lu files.
    Pass a dict as `texts` to have it filled with {hash: English text}."""
    import lu_strings
    from naughty_lu import LuFile
    out = {}
    for p in paths:
        lu = LuFile(str(p))
        img = lu.image
        keys = set()
        for r in lu.records:
            try:
                text, n, _ = lu_strings.read_string(img, r.offset)
            except Exception:
                continue
            if 0 < n <= 4096:
                keys.add(r.hash)
                if texts is not None:
                    texts.setdefault(r.hash, text)
        out[Path(p).stem] = keys
    return out


# ------------------------------------------------------------------ driver
def reconstruct(folder, known=None):
    """The per-script RULES over one folder. -> (found, report, n unnamed)"""
    known = known if known is not None else nb_names.load()
    files = sorted(Path(folder).rglob("*.lua"))
    texts = []
    unnamed = set()
    for f in files:
        t = unlabelled_text(f.read_text(encoding="utf-8", errors="replace"))
        texts.append((t, f.stem, f.parent.name))
        unnamed |= {int(h, 16) for h in BARE.findall(t)}
    unnamed -= set(known)
    found, report = {}, []
    for label, rule in RULES:
        tried = set()
        hits = {}
        for text, stem, container in texts:
            for h, cands in rule(text, stem, container):
                if h not in unnamed:
                    continue
                for c in cands:
                    k = crc(c)
                    # distinct (hash, candidate) pairs, kept as one int each
                    tried.add((h << 32) | k)
                    if k == h:
                        hits[h] = c
        # a candidate can only ever coincide with the hash it was made for
        report.append((label, len(tried), dict(hits)))
        for h, c in hits.items():
            found.setdefault(h, c)
    return found, report, len(unnamed)


def working_copy(scripts, dest):
    """One copy of each distinct script (the same script is exported once
    per container that carries it), kept under its container's folder."""
    import shutil
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    seen = set()
    for f in sorted(Path(scripts).rglob("*.lua")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if (f.stem, text) in seen:
            continue
        seen.add((f.stem, text))
        out = dest / f.parent.name / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    return dest


def relabel(folder, names):
    """Write newly rebuilt names into the working copy, as the exporter
    would, so the next round can use them as templates and examples."""
    def sub(m):
        h = int(m.group(2), 16)
        if h not in names:
            return m.group(0)
        text = m.group(1) or ""
        text = text[4:-2] if text.startswith("--[[") else ""
        extra = f" {text}" if text.startswith("TEXT") else ""
        return f'--[[HASH:"{names[h]}"{extra}]]0x{m.group(2)}'
    pat = re.compile(r'(--\[\[TEXT[^\]]*\]\])?0x([0-9a-f]{8})\b')
    for f in Path(folder).rglob("*.lua"):
        t = f.read_text(encoding="utf-8")
        new = pat.sub(sub, t)
        if new != t:
            f.write_text(new, encoding="utf-8", newline="\n")


def unnamed_in(folder, known):
    out = set()
    for f in Path(folder).rglob("*.lua"):
        out |= {int(h, 16) for h in BARE.findall(
            unlabelled_text(f.read_text(encoding="utf-8")))}
    return out - set(known)


def run_rounds(scripts, nb2_scripts=None, text_files=(), known=None,
               work=None, max_rounds=6, log=print):
    """Every rule, in rounds, until a round rebuilds nothing new.
    -> (found {hash: name}, {rule: [pairs tried, rebuilt]})"""
    import tempfile
    known = dict(known if known is not None else nb_names.load())
    work = working_copy(scripts, work or Path(tempfile.mkdtemp()) / "work")
    texts = {}
    conts = load_text_containers(text_files, texts) if text_files else {}
    found, totals = {}, collections.defaultdict(lambda: [0, 0])
    words = None
    for rnd in range(1, max_rounds + 1):
        everything = {**known, **found}
        unnamed = unnamed_in(work, everything)
        new = {}

        def take(label, hits, pairs):
            totals[label][0] += pairs
            fresh = {h: c for h, c in hits.items()
                     if h not in everything and h not in new}
            totals[label][1] += len(fresh)
            new.update(fresh)

        _, report, _ = reconstruct(work, everything)
        for label, pairs, hits in report:
            take(label, hits, pairs)
        hits, pairs, _ = rule_constant_names(work, unnamed, everything)
        take("constant names", hits, pairs)
        hits, pairs, _ = rule_call_families(work, unnamed, everything)
        take("call families", hits, pairs)
        hits, pairs = rule_line_words(work, unnamed, everything)
        take("line words", hits, pairs)
        hits, pairs = rule_object_actions(work, unnamed, everything)
        take("object actions", hits, pairs)
        if words is None:
            words = vocabulary(work, nb2_scripts, known=everything)
        hits, pairs = rule_runtime_prefixes(work, unnamed, everything, words)
        take("runtime-built names", hits, pairs)
        hits, pairs = rule_context_templates(work, nb2_scripts, unnamed, everything)
        take("context templates", hits, pairs)
        if conts:
            hits, pairs, _ = text_container_siblings(conts, everything)
            take("text-ID siblings", hits, pairs)
            hits, pairs = rule_text_words(conts, texts, everything)
            take("text words", hits, pairs)
        log(f"  round {rnd}: {len(new)} new names ({len(unnamed):,} were unnamed)")
        if not new:
            break
        found.update(new)
        relabel(work, new)
    return found, dict(totals)


def verify(scripts, nb2_scripts, text_files, known, tiers, log=print):
    """The check behind every rebuilt name: hide all of them, start from the
    names found as text in the game's data, and let the rules rebuild what
    they can. A rebuilt name that differs from the one on file for the same
    hash would mean one of the two is a chance match; none should.
    -> {"same": {hash}, "case": {hash}, "different": {hash: (rebuilt, on
        file)}, "new": {hash: name}, "totals": rule totals}"""
    base = {h: n for h, n in known.items() if tiers.get(h) == "found"}
    hidden = {h: n for h, n in known.items() if h not in base}
    got, totals = run_rounds(scripts, nb2_scripts, text_files, base,
                             max_rounds=12, log=log)
    same = {h for h in got if h in hidden
            and got[h].lower() == hidden[h].lower()}
    return {"same": same,
            "case": {h for h in same if got[h] != hidden[h]},
            "different": {h: (got[h], hidden[h]) for h in got
                          if h in hidden and h not in same},
            "new": {h: c for h, c in got.items() if h not in hidden},
            "totals": totals, "hidden": len(hidden)}


def print_families(scripts, text_files, known):
    """One line per family: where, size, prefix hash, and the style the
    numbers are written in. Search for the prefix hash (one target, so a
    wide search stays cheap), then name every member at once."""
    groups = []
    seen = set()
    for f in sorted(Path(scripts).rglob("*.lua")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        if raw in seen:
            continue
        seen.add(raw)
        groups.append((f.stem, {int(h, 16) for h in BARE.findall(
            unlabelled_text(raw))} - set(known)))
    for cont, keys in load_text_containers(text_files).items():
        groups.append((cont, keys - set(known)))
    for where, hashes in groups:
        fams = numbered_families(hashes)
        # one line per group of members, under its first-found style
        shown = set()
        for (p, style, start), members in sorted(
                fams.items(), key=lambda kv: -len(kv[1])):
            key = frozenset(members.values())
            if key in shown:
                continue
            shown.add(key)
            print(f"{where:32} {len(members):3} members  prefix 0x{p:08x}  "
                  f"numbers {style.format(start)}..")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scripts", help="folder written by `lu_lua.py export`")
    ap.add_argument("--nb2", help="NB2 (PiP) scripts exported the same way; "
                                  "their names serve as templates")
    ap.add_argument("--text", nargs="*", default=[],
                    help="NB1 .en_us.lu localization containers (files or "
                         "folders), for the text-ID sibling rule; pass the "
                         "retail ones")
    ap.add_argument("--apply", action="store_true",
                    help="add the rebuilt names to nb_names.json")
    ap.add_argument("--families", action="store_true",
                    help="only list the numbered families among each "
                         "script's (and text container's) unnamed hashes, "
                         "with the hash of their shared prefix")
    ap.add_argument("--verify", action="store_true",
                    help="hide every name not found as text in the game's "
                         "data, rebuild from the rest, and compare; with "
                         "--apply, mark the rebuilt ones as tier 'rule' in "
                         "nb_names_sources.json and add any new names")
    a = ap.parse_args()
    files = []
    for t in a.text:
        t = Path(t)
        files += sorted(t.glob("*.en_us.lu")) if t.is_dir() else [t]
    known = nb_names.load()
    if a.families:
        print_families(a.scripts, files, known)
        return
    if a.verify:
        tiers, notes = nb_names.load_sources()
        if not any(t == "found" for t in tiers.values()):
            sys.exit("nb_names_sources.json has no 'found' names to start from")
        r = verify(a.scripts, a.nb2, files, known, tiers)
        print(f"rebuilt {len(r['same'])} of {r['hidden']} names not found as "
              f"text ({len(r['case'])} differ only in letter case)")
        print(f"rebuilt differently: {len(r['different'])}")
        for h, (got, have) in sorted(r["different"].items()):
            print(f"  0x{h:08x} rebuilt {got!r}, on file {have!r}")
        print(f"new names: {len(r['new'])}")
        chance = sum(p for p, _ in r["totals"].values()) / 2 ** 32
        print(f"expected chance matches across the run: {chance:.4f}")
        if a.apply:
            for h in r["same"]:
                if tiers.get(h) != "found":
                    tiers[h] = "rule"
            for h, c in r["new"].items():
                known[h] = c
                tiers[h] = "rule"
            nb_names.save(known)
            print(f"-> {nb_names.save_sources(tiers, notes)}")
        return
    found, totals = run_rounds(a.scripts, a.nb2, files, known)
    print(f"  {'rule':<22} {'candidates':>12} {'expected chance hits':>21} {'rebuilt':>8}")
    all_pairs = 0
    for label, (pairs, hits) in totals.items():
        all_pairs += pairs
        print(f"  {label:<22} {pairs:>12,} {pairs / 2 ** 32:>21.6f} {hits:>8}")
    print(f"rebuilt {len(found)} names in all; expected chance matches "
          f"across every rule: {all_pairs / 2 ** 32:.4f}")
    if a.apply and found:
        known.update(found)
        print(f"-> {nb_names.save(known)} ({len(known):,} names)")


if __name__ == "__main__":
    main()
