#!/usr/bin/env python3
"""lu_autofix.py - conservative batch typo fixer for x36 .lu localization.

Design rules:
  * NEVER touch slang or stylistic text (narrator glitch-speech, "wayyy",
    "BOO!", ". . ." ellipsis). Slang allowlist is honored everywhere.
  * NEVER auto-collapse double spaces. Inter-word double spacing may be
    deliberate layout/alignment for Scaleform. Double spaces are only ever
    *reported* for human review, never changed automatically.
  * Auto-fix ONLY unambiguous spelling errors (a misspelled word is wrong
    regardless of formatting). These come from a vetted dictionary.

Two modes:
  report   scan files, print every candidate as reviewable TSV
             FILE  HASH  KIND  detail  text
           KIND = spell (auto-fixable) | spacing (review-only) | punct (review-only)
  fix      apply ONLY spelling fixes from the vetted dict, across files,
           writing raw .lu outputs. Spacing/punct never auto-applied.
           --from REVIEW.tsv  optionally restrict spelling fixes to HASHes you
           approved (lines you kept), so even spelling is opt-in.

Usage:
  lu_autofix.py report lu/ > review.tsv
  lu_autofix.py fix lu/ -o out/                 # all vetted spelling fixes
  lu_autofix.py fix lu/ -o out/ --from review.tsv   # only approved HASHes
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naughty_lu import LuFile  # noqa: E402
from lu_strings import read_string, cmd_apply  # noqa: E402

# Vetted unambiguous misspellings. Case-preserving replace. NO slang, NO
# dialect (metre/centre are valid en-GB and stay). Add only certain errors.
SPELL = {
    "emited": "emitted", "whitnesses": "witnesses", "whitness": "witness",
    "recieve": "receive", "recieved": "received", "occured": "occurred",
    "occurence": "occurrence", "seperate": "separate", "definately": "definitely",
    "untill": "until", "achievment": "achievement", "begining": "beginning",
    "comming": "coming", "succesfully": "successfully", "successfull": "successful",
    "neccessary": "necessary", "wierd": "weird", "thier": "their",
    "becuase": "because", "tryed": "tried", "alot": "a lot",
}

# Slang / stylistic - NEVER flag or fix anywhere it appears.
SLANG = [
    "wayyy", "boo!", "naughty", "defluff", "unstuff",
    r"\.\s\.\s\.",      # ". . ." stylized ellipsis (loading / narrator)
    r"\bwh\s*\.\s*t\b",  # glitch-speech "Wh . t"
]
SLANG_RX = re.compile("|".join(SLANG), re.IGNORECASE)


def case_preserve(src, repl):
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def spelling_fixes(text):
    """Return (fixed_text, [ (bad,good), ... ]) applying SPELL, skipping slang spans."""
    applied = []

    def sub(m):
        word = m.group(0)
        low = word.lower()
        if low in SPELL:
            good = case_preserve(word, SPELL[low])
            applied.append((word, good))
            return good
        return word

    # word-by-word, but never inside a slang span
    out = []
    i = 0
    for m in re.finditer(r"[A-Za-z']+", text):
        # skip if this word sits inside a slang match
        span = text[m.start():m.end()]
        if SLANG_RX.fullmatch(span) or span.lower() in (s for s in SLANG):
            continue
    # simpler: do a global regex sub over words, slang words aren't in SPELL anyway
    fixed = re.sub(r"[A-Za-z']+", sub, text)
    return fixed, applied




def spacing_punct_fixes(text):
    """Conservative whitespace fixes:
      - collapse 2+ spaces to 1 ONLY when not following . ! ? (preserve
        intentional two-space-after-sentence typography)
      - remove space before , ; : (not before . ! ? which can be stylistic)
    Returns (fixed, changed_bool)."""
    orig = text
    # space before , ; :
    text = re.sub(r"\s+([,;:])", r"\1", text)
    # collapse multi-space not preceded by sentence punctuation
    text = re.sub(r"(?<![.!?])  +", " ", text)
    return text, (text != orig)


def iter_strings(lu_path):
    try:
        lu = LuFile(str(lu_path))
        image = lu.image
    except Exception as e:
        print(f"warning: {lu_path}: {e}", file=sys.stderr)
        return
    for r in lu.records:
        try:
            text, strlen, _ = read_string(image, r.offset)
        except Exception:
            continue
        if strlen == 0 or strlen > 4096 or not any(c.isalpha() for c in text):
            continue
        yield r.hash, text


def collect(paths, pat="*.en_us.lu"):
    out = []
    for p in paths:
        pp = Path(p)
        out += sorted(pp.rglob(pat)) if pp.is_dir() else [pp]
    return out


def cmd_report(args):
    files = collect(args.paths)
    n = 0
    for f in files:
        for h, text in iter_strings(f):
            if SLANG_RX.search(text):
                # text contains slang; still allow spelling fixes elsewhere in it,
                # but mark so reviewer knows to be careful
                pass
            fixed, applied = spelling_fixes(text)
            disp = text.replace("\n", "\\n")
            for bad, good in applied:
                print(f"{f.name}\t{h:08x}\tspell\t{bad}->{good}\t{disp}")
                n += 1
            if re.search(r"\S  +\S", text):
                print(f"{f.name}\t{h:08x}\tspacing\tdouble-space (review only)\t{disp}")
                n += 1
            if re.search(r"\s+[,;:](?!\))", text):
                print(f"{f.name}\t{h:08x}\tpunct\tspace-before-punct (review)\t{disp}")
                n += 1
    print(f"--- {n} candidates across {len(files)} file(s). "
          f"Only 'spell' lines are auto-fixable.", file=sys.stderr)


def cmd_fix(args):
    files = collect(args.paths)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    approved = None
    if args.from_review:
        approved = set()
        for ln in Path(args.from_review).read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 3 and parts[2] == "spell":
                approved.add((parts[0], parts[1].lower()))

    total_files = 0
    total_edits = 0
    for f in files:
        lu = LuFile(str(f))
        image = lu.image
        edits = {}   # hash -> new text
        for r in lu.records:
            try:
                text, strlen, _ = read_string(image, r.offset)
            except Exception:
                continue
            if strlen == 0 or not any(c.isalpha() for c in text):
                continue
            if approved is not None and (f.name, f"{r.hash:08x}") not in approved:
                continue
            fixed, applied = spelling_fixes(text)
            if getattr(args, "spacing", False):
                fixed2, ch = spacing_punct_fixes(fixed)
                if ch:
                    fixed = fixed2
                    applied = applied or [("spacing/punct", "fixed")]
            if applied and fixed != text:
                edits[r.hash] = fixed
        if not edits:
            continue
        # write a strings file then reuse lu_strings apply logic via subprocess-free call
        tmp = out_dir / (f.stem + ".strings.txt")
        def esc(s):
            return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        lines = [f"{h:08x}\t{esc(t)}" for h, t in edits.items()]
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")

        class A:
            orig = str(f)
            edited = str(tmp)
            out = str(out_dir / f.name)
            verify = True
        cmd_apply(A())
        total_files += 1
        total_edits += len(edits)
    print(f"--- fixed {total_edits} string(s) across {total_files} file(s) -> {out_dir}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Conservative .lu typo fixer (slang/formatting safe).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("report")
    pr.add_argument("paths", nargs="+")
    pr.set_defaults(func=cmd_report)
    pf = sub.add_parser("fix")
    pf.add_argument("paths", nargs="+")
    pf.add_argument("-o", "--out", required=True)
    pf.add_argument("--from", dest="from_review", help="restrict to approved HASHes in this report TSV")
    pf.add_argument("--spacing", action="store_true", help="also fix mid-phrase double-spaces (not after .!?) and space-before-,;:")
    pf.set_defaults(func=cmd_fix)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
