#!/usr/bin/env python3
"""lua_batchedit.py - apply a per-argument transform to every call in a chunk
that matches an example, in the select-and-mark model.

Workflow the GUI drives:
  1. User selects one example call. build_pattern() splits it and returns a
     Pattern whose slots are all ANCHOR by default; the GUI lets the user
     retag each slot ANCHOR / TARGET / IGNORE and attach a transform to the
     TARGET slots.
  2. find_matches() scans the whole chunk for calls whose arity matches and
     whose ANCHOR slots equal the example's, and returns them for review.
  3. apply() rewrites the TARGET slots of the reviewed matches, right-to-left
     so earlier edits don't shift later spans, and returns the new source.

Transforms per target slot: scale (multiply), set (replace with literal),
offset (add). Uniform mode applies one transform to every target; individual
mode gives each target its own. Numeric transforms operate on the argument
parsed as a Lua number; a non-numeric target under scale/offset is an error
surfaced at apply time, not silently skipped.
"""
from dataclasses import dataclass, field
from enum import Enum

import lua_callsplit as cs


class Tag(Enum):
    ANCHOR = "anchor"
    TARGET = "target"
    IGNORE = "ignore"


class Op(Enum):
    SCALE = "scale"
    SET = "set"
    OFFSET = "offset"


@dataclass
class SlotSpec:
    tag: Tag
    anchor_value: str = ""      # required value when tag is ANCHOR
    op: Op = None               # transform when tag is TARGET
    param: str = ""             # factor / literal / addend as text
    match_value: str = None     # TARGET only: if set, only calls whose this
                                # slot equals it are matched. Defaults to the
                                # example's value (mark implies "calls like
                                # this one"); set None to target regardless of
                                # current value.


@dataclass
class Pattern:
    func: str
    slots: list = field(default_factory=list)   # one SlotSpec per position

    @property
    def arity(self):
        return len(self.slots)


def build_pattern(src, example_call):
    """example_call is a Call from lua_callsplit. Returns a Pattern with every
    slot ANCHOR-tagged to the example's own values (the caller then retags)."""
    slots = [SlotSpec(tag=Tag.ANCHOR, anchor_value=a.text, match_value=a.text)
             for a in example_call.args]
    return Pattern(func=example_call.func, slots=slots)


def find_matches(src, pattern):
    """Return the list of Calls whose arity equals the pattern's and whose
    every ANCHOR slot equals the pattern's anchor value."""
    out = []
    for call in cs.find_calls(src, pattern.func):
        if len(call.args) != pattern.arity:
            continue
        ok = True
        for slot, arg in zip(pattern.slots, call.args):
            if slot.tag is Tag.ANCHOR and arg.text != slot.anchor_value:
                ok = False
                break
            if (slot.tag is Tag.TARGET and slot.match_value is not None
                    and arg.text != slot.match_value):
                ok = False
                break
        if ok:
            out.append(call)
    return out


def _as_number(text):
    t = text.strip()
    try:
        if t.lower().startswith("0x"):
            return int(t, 16)
        if any(c in t for c in ".eE") and not t.lower().startswith("0x"):
            return float(t)
        return int(t)
    except ValueError:
        raise ValueError(f"target argument {text!r} is not a number")


def _fmt_number(n):
    if isinstance(n, float):
        s = repr(n)
        return s
    return str(n)


def _transform(arg_text, slot):
    if slot.op is Op.SET:
        return slot.param
    n = _as_number(arg_text)
    p = _as_number(slot.param)
    if slot.op is Op.SCALE:
        r = n * p
    elif slot.op is Op.OFFSET:
        r = n + p
    else:
        raise ValueError(f"no transform on slot")
    if isinstance(n, int) and isinstance(p, int) and slot.op is not Op.SET:
        r = int(r)
    return _fmt_number(r)


def apply(src, pattern, matches):
    """Rewrite every TARGET slot of every match. Returns (new_src, changes)
    where changes is a list of (call_start, arg_index, old, new)."""
    edits = []    # (start, end, replacement)
    changes = []
    for call in matches:
        for idx, (slot, arg) in enumerate(zip(pattern.slots, call.args)):
            if slot.tag is not Tag.TARGET:
                continue
            new_text = _transform(arg.text, slot)
            if new_text != arg.text:
                edits.append((arg.start, arg.end, new_text))
                changes.append((call.call_start, idx, arg.text, new_text))
    for start, end, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        src = src[:start] + rep + src[end:]
    return src, changes
