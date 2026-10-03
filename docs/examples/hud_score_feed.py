#!/usr/bin/env python3
"""
Usage:
  python hud_score_feed.py --lu "C:\\path\\to\\naughtybear\\lu\\levelcommon.lu" --out hud_out
  python hud_score_feed.py --lu ... --out hud_out --check-only      (checks only)
"""
import argparse
import hashlib
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

RETAIL_SHA256 = "4097ba39c1ea9036269646c1a6cda793d77acd8d716ce190a72dc639b33f2f51"
GFX_TYPE = 0x04D00001

# ---- the feed clip's ActionScript (written for this example; not the game's code) ----
FEED_AS = """this.ROWS = 6;
this.HOLD = @HOLD@;
this.FADE = @FADE@;
this.LIFE = @LIFE@;
this.texts = ["", "", "", "", "", ""];
this.times = [0, 0, 0, 0, 0, 0];
this.count = 0;
this.releasePending = false;
this.refresh = function()
{
   var now = getTimer();
   while(this.count > 0 && now - this.times[this.count - 1] >= this.LIFE)
   {
      this.count--;
   }
   var i = 0;
   while(i < this.ROWS)
   {
      var slot = this["s" + i];
      if(i < this.count)
      {
         var s = this.texts[i];
         if(typeof s != "string")
         {
            s = "";
         }
         var age = now - this.times[i];
         var al = 100;
         if(age > this.HOLD)
         {
            al = 100 * (1 - (age - this.HOLD) / this.FADE);
         }
         if(!(al > 0))
         {
            al = 0;
         }
         slot.t = s;
         slot._visible = true;
         slot._alpha = al;
      }
      else
      {
         slot.t = "";
         slot._visible = false;
      }
      i++;
   }
};
this.addLine = function(a, b)
{
   this.releasePending = true;
   var s = "";
   if(a != undefined)
   {
      s = String(a);
   }
   if(b != undefined && String(b) != "")
   {
      s = s + " " + String(b);
   }
   if(s == "")
   {
      return undefined;
   }
   var i = this.ROWS - 1;
   while(i > 0)
   {
      this.texts[i] = this.texts[i - 1];
      this.times[i] = this.times[i - 1];
      i--;
   }
   this.texts[0] = s;
   this.times[0] = getTimer();
   if(this.count < this.ROWS)
   {
      this.count++;
   }
   this.refresh();
};
this.onEnterFrame = function()
{
   if(this.releasePending)
   {
      this.releasePending = false;
      _root.CallEngineFunction("FearEventDisplayTextEnd");
   }
   this.refresh();
};
this.refresh();
stop();
"""


# =============================================================== narration
STEP = [0]
TOTAL = 8


def step(title, *why):
    STEP[0] += 1
    print()
    print("=" * 72)
    print(f"Step {STEP[0]} of {TOTAL}: {title}")
    print("=" * 72)
    for line in why:
        print("  " + line)


def say(msg):
    print("  - " + msg)


def die(msg):
    print()
    print("STOPPED: " + msg)
    sys.exit(1)


# =============================================================== finding tools
def find_seamripper(arg):
    cands = []
    if arg:
        cands.append(Path(arg))
    if os.environ.get("SEAMRIPPER"):
        cands.append(Path(os.environ["SEAMRIPPER"]))
    here = Path(__file__).resolve().parent
    for base in (here, here.parent, here.parent.parent, Path.cwd(), Path.cwd().parent):
        cands += [base, base / "tools", base / "seam-ripper" / "tools"]
    need = ["naughty_lu.py", "lu_chunk_replace.py", "verify_lzx.py", "lzx_encode.py", "sr_backup.py"]
    for c in cands:
        t = c / "tools" if (c / "tools" / "naughty_lu.py").exists() else c
        if all((t / n).exists() for n in need):
            return t.resolve()
    return None


def find_ffdec(arg):
    cands = []
    if arg:
        cands.append(arg)
    if os.environ.get("FFDEC"):
        cands.append(os.environ["FFDEC"])
    for d in (r"C:\Program Files (x86)\FFDec", r"C:\Program Files\FFDec"):
        cands += [os.path.join(d, "ffdec-cli.exe"), os.path.join(d, "ffdec.bat")]
    for n in ("ffdec-cli", "ffdec", "ffdec.sh"):
        w = shutil.which(n)
        if w:
            cands.append(w)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def find_7z(arg):
    cands = [arg] if arg else []
    cands += [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]
    for n in ("7z", "7za", "7zz"):
        w = shutil.which(n)
        if w:
            cands.append(w)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# =============================================================== SWF tag helpers
def parse_tags(buf, pos, end=None):
    end = len(buf) if end is None else end
    out = []
    while pos < end:
        start = pos
        h = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
        t, ln = h >> 6, h & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        data = bytes(buf[pos:pos + ln])
        pos += ln
        out.append({"t": t, "data": data, "raw": bytes(buf[start:pos])})
        if t == 0:
            break
    return out


def mk_tag(t, data, force_long=False):
    if len(data) < 0x3F and not force_long:
        return struct.pack("<H", (t << 6) | len(data)) + data
    return struct.pack("<H", (t << 6) | 0x3F) + struct.pack("<I", len(data)) + data


def bits_write(fields):
    acc = n = 0
    for v, nb in fields:
        if v < 0:
            v += 1 << nb
        acc = (acc << nb) | (v & ((1 << nb) - 1))
        n += nb
    pad = (-n) % 8
    return (acc << pad).to_bytes((n + pad) // 8, "big")


def nbits_signed(*vals):
    return max(max(abs(int(v)).bit_length() + 1 for v in vals), 1)


def matrix(tx_px, ty_px, sx=1.0, sy=1.0):
    tx, ty = round(tx_px * 20), round(ty_px * 20)
    f = []
    if sx != 1.0 or sy != 1.0:
        fx, fy = round(sx * 65536), round(sy * 65536)
        nb = nbits_signed(fx, fy)
        f += [(1, 1), (nb, 5), (fx, nb), (fy, nb)]
    else:
        f += [(0, 1)]
    f += [(0, 1)]
    nb = nbits_signed(tx, ty)
    f += [(nb, 5), (tx, nb), (ty, nb)]
    return bits_write(f)


def place2(depth, char=None, mx=None, name=None):
    fl = (2 if char is not None else 0) | (4 if mx is not None else 0) | (0x20 if name is not None else 0)
    d = bytes([fl]) + struct.pack("<H", depth)
    if char is not None:
        d += struct.pack("<H", char)
    if mx is not None:
        d += mx
    if name is not None:
        d += name.encode() + b"\0"
    return mk_tag(26, d)


def define_sprite(cid, inner_tags, frames=1):
    return mk_tag(39, struct.pack("<HH", cid, frames) + b"".join(inner_tags) + mk_tag(0, b""), force_long=True)


def edittext_clone(template, new_id, new_var):
    """copy a DefineEditText: new character id and variable name, everything else identical"""
    d = bytearray(template)
    n = d[2] >> 3
    q = 2 + (5 + 4 * n + 7) // 8
    fl1, fl2 = d[q], d[q + 1]
    q += 2
    if fl1 & 1:
        q += 2
    if fl2 & 0x80:
        q = d.index(b"\0", q) + 1
    if fl1 & 1:
        q += 2
    if fl1 & 4:
        q += 4
    if fl1 & 2:
        q += 2
    if fl2 & 0x20:
        q += 9
    e = d.index(b"\0", q)
    new = bytes(d[:q]) + new_var.encode() + b"\0" + bytes(d[e + 1:])
    return struct.pack("<H", new_id) + new[2:]


def edittext_var(d):
    n = d[2] >> 3
    q = 2 + (5 + 4 * n + 7) // 8
    fl1, fl2 = d[q], d[q + 1]
    q += 2
    if fl1 & 1:
        q += 2
    if fl2 & 0x80:
        q = d.index(b"\0", q) + 1
    if fl1 & 1:
        q += 2
    if fl1 & 4:
        q += 4
    if fl1 & 2:
        q += 2
    if fl2 & 0x20:
        q += 9
    return d[q:d.index(b"\0", q)].decode("latin-1")


# =============================================================== ActionScript bytecode helpers
def S(s):
    return b"\x00" + s.encode() + b"\0"


def push(*items):
    d = b"".join(items)
    return b"\x96" + struct.pack("<H", len(d)) + d


NEW_BODY = (push(bytes([4, 3]), bytes([4, 4]))                       # scoreString, fearString (arguments go last-to-first)
            + push(bytes([7, 2, 0, 0, 0]))                            # 2 arguments
            + push(bytes([4, 1]), S("HudHolder")) + bytes([0x4E])     # _root.HudHolder
            + push(S("FeedClip")) + bytes([0x4E])                     # .FeedClip
            + push(S("addLine")) + bytes([0x52, 0x17]))               # .addLine(fear, score); pop

DEAD = [(b"ShowTextBoxFearEvent", [b"value"]), (b"SetTextFearEvent", [b"textString", b"delayTime", b"scroll"]),
        (b"DelayFearEventText", []), (b"MoveFearEventText", []), (b"DelayFearEventCallBack", [b"callBack"])]


def _fn_header(op, d):
    """-> (name, params, code size, offset of the size field inside d)"""
    e = d.index(b"\0")
    name = bytes(d[:e])
    p = e + 1
    n = struct.unpack_from("<H", d, p)[0]
    p += 5 if op == 0x8E else 2
    params = []
    for _ in range(n):
        if op == 0x8E:
            p += 1
        e2 = d.index(b"\0", p)
        params.append(bytes(d[p:e2]))
        p = e2 + 1
    return name, params, struct.unpack_from("<H", d, p)[0], p


def _walk_outer(code):
    """yield (offset, opcode, header length, data) for outer-level actions; function bodies are skipped"""
    i = 0
    while i < len(code):
        op = code[i]
        if op < 0x80:
            i += 1
            continue
        ln = struct.unpack_from("<H", code, i + 1)[0]
        d = code[i + 3:i + 3 + ln]
        yield i, op, ln, d
        if op in (0x8E, 0x9B):
            i += 3 + ln + _fn_header(op, d)[2]
        elif op == 0x94:
            i += 3 + ln + struct.unpack_from("<H", d, 0)[0]
        else:
            i += 3 + ln


def rewrite_live_fn(code):
    for i, op, ln, d in _walk_outer(code):
        if op == 0x8E:
            name, params, sz, p = _fn_header(op, d)
            if name == b"SetTextFearEvent" and params == [b"fearString", b"scoreString", b"timeShow"]:
                bstart = i + 3 + ln
                new = bytearray(code[:bstart]) + NEW_BODY + code[bstart + sz:]
                struct.pack_into("<H", new, i + 3 + p, len(NEW_BODY))
                return bytes(new)
    raise ValueError("the live SetTextFearEvent function was not found")


def remove_dead(code):
    spans, removed = [], []
    for i, op, ln, d in _walk_outer(code):
        if op in (0x8E, 0x9B):
            name, params, sz, p = _fn_header(op, d)
            if (name, params) in DEAD:
                spans.append((i, i + 3 + ln + sz))
                removed.append(name.decode())
    if sorted(removed) != sorted(n.decode() for n, _ in DEAD):
        raise ValueError("expected five older functions, found " + str(removed))
    for i, op, ln, d in _walk_outer(code):
        if op in (0x99, 0x9D):
            tgt = i + 3 + ln + struct.unpack_from("<h", d, 0)[0]
            lo, hi = sorted((i, tgt))
            if any(lo < a < hi for a, b in spans):
                raise ValueError("a jump crosses code that would be removed")
    out = bytearray()
    last = 0
    for a, b in spans:
        out += code[last:a]
        last = b
    out += code[last:]
    return bytes(out), len(code) - len(out)


def trim_pool(code):
    """blank constant-pool strings that nothing references any more (indexes stay valid)"""
    i = 0
    pools, used = [], set()
    while i < len(code):        # linear scan: function bodies are ordinary inline actions
        op = code[i]
        if op < 0x80:
            i += 1
            continue
        ln = struct.unpack_from("<H", code, i + 1)[0]
        d = code[i + 3:i + 3 + ln]
        if op == 0x88:
            pools.append((i, ln))
        if op == 0x96:
            q = 0
            while q < len(d):
                t = d[q]
                q += 1
                if t == 0:
                    q = d.index(b"\0", q) + 1
                elif t in (1, 7):
                    q += 4
                elif t == 6:
                    q += 8
                elif t in (4, 5):
                    q += 1
                elif t == 8:
                    used.add(d[q])
                    q += 1
                elif t == 9:
                    used.add(struct.unpack_from("<H", d, q)[0])
                    q += 2
        i += 3 + ln
    if len(pools) != 1:
        raise ValueError("expected one constant pool")
    pi, pl = pools[0]
    pd = code[pi + 3:pi + 3 + pl]
    n = struct.unpack_from("<H", pd, 0)[0]
    q, strs = 2, []
    for _ in range(n):
        e = pd.index(b"\0", q)
        strs.append(bytes(pd[q:e]))
        q = e + 1
    nd = struct.pack("<H", n) + b"".join((x if k in used else b"") + b"\0" for k, x in enumerate(strs))
    return bytes(code[:pi + 1]) + struct.pack("<H", len(nd)) + nd + bytes(code[pi + 3 + pl:])


# =============================================================== movie handling
def find_movie(chunk):
    a = chunk.find(b"CFX", 0, 64)
    if a < 0:
        return None
    dec = zlib.decompressobj()
    try:
        dec.decompress(bytes(chunk[a + 8:]))
    except zlib.error:
        return None
    return a, len(chunk) - len(dec.unused_data)


def deflate7(z7, data):
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "o.gz")
        subprocess.run([z7, "a", "-tgzip", "-mx=9", "-mpass=15", "-mfb=258", "-bd", "-y", "-si", out],
                       input=data, capture_output=True, check=True)
        gz = open(out, "rb").read()
    if gz[:2] != b"\x1f\x8b" or gz[3] != 0:
        raise ValueError("unexpected 7-Zip output")
    return gz[10:-8]


def zwrap(deflate, data):
    return b"\x78\xda" + deflate + struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)


def pack_exact(z7, raw, target_total):
    """GFX raw -> CFX of exactly target_total bytes (7-Zip deflate, then seeded junk after the movie's end)"""
    hdr = b"CFX" + raw[3:4] + raw[4:8]
    body = raw[8:]
    base = len(zwrap(deflate7(z7, body), body))
    need = target_total - 8 - base
    if need < 0:
        return None, -need
    rnd = random.Random(1)
    pad = bytes(rnd.randrange(256) for _ in range(need + 200))
    guess = int(need / 1.06)
    for n in range(max(0, guess - 25), guess + 25):
        d = body + pad[:n]
        z = zwrap(deflate7(z7, d), d)
        if len(z) == target_total - 8:
            return hdr + z, base
    raise ValueError("could not hit the exact size")


# =============================================================== main
def main():
    ap = argparse.ArgumentParser(description="HUD score feed (preview) for Naughty Bear")
    ap.add_argument("--lu", required=True, help="your Naughty Bear levelcommon.lu")
    ap.add_argument("--out", default="hud_out", help="folder for the new file (default: hud_out)")
    ap.add_argument("--seamripper", help="Seam Ripper's tools folder (found automatically if nearby)")
    ap.add_argument("--ffdec", help="path to ffdec-cli.exe (JPEXS)")
    ap.add_argument("--sevenzip", help="path to 7z.exe")
    ap.add_argument("--scale", type=float, default=0.9, help="size of the feed lines, 0.5 to 1.0 (default 0.9)")
    ap.add_argument("--hold", type=int, default=1000, help="milliseconds a line stays (default 1000)")
    ap.add_argument("--fade", type=int, default=300, help="milliseconds to fade out (default 300)")
    ap.add_argument("--check-only", action="store_true", help="only check the setup, change nothing")
    ap.add_argument("--skip-hash-check", action="store_true",
                    help="build even if the file is not the retail one (it will probably fail)")
    a = ap.parse_args()
    if not (0.5 <= a.scale <= 1.0 and 100 <= a.hold <= 20000 and 50 <= a.fade <= 5000):
        die("--scale must be 0.5 to 1.0, --hold 100 to 20000, --fade 50 to 5000")

    print("HUD score feed (preview) for Naughty Bear")
    print("This builds a NEW levelcommon.lu. Your own files are only read, never changed.")

    # ---------------------------------------------------------- 1
    step("Check the setup",
         "Four things are needed: Seam Ripper's tools (they read and write the .lu",
         "container and check the result), JPEXS (compiles the feed's ActionScript),",
         "7-Zip (compresses the movie small enough to fit) and your own levelcommon.lu.")
    if sys.version_info < (3, 9):
        die("Python 3.9 or newer is needed.")
    say("Python " + sys.version.split()[0] + " ok")
    if a.seamripper and not Path(a.seamripper).exists():
        die("--seamripper points at a folder that does not exist: " + a.seamripper)
    tools = find_seamripper(a.seamripper)
    if not tools:
        die("Seam Ripper was not found. Download it from https://github.com/leonmustdie/seam-ripper "
            "and either put this script inside its folder or pass --seamripper \"<Seam Ripper>\\tools\".")
    say("Seam Ripper tools: " + str(tools))
    if a.ffdec and not os.path.exists(a.ffdec):
        die("--ffdec points at a file that does not exist: " + a.ffdec)
    ffdec = find_ffdec(a.ffdec)
    if not ffdec:
        die("JPEXS was not found. Install it from https://github.com/jindrapetrik/jpexs-decompiler/releases "
            "or pass --ffdec \"<path>\\ffdec-cli.exe\".")
    say("JPEXS: " + ffdec)
    if a.sevenzip and not os.path.exists(a.sevenzip):
        die("--sevenzip points at a file that does not exist: " + a.sevenzip)
    z7 = find_7z(a.sevenzip)
    if not z7:
        die("7-Zip was not found. Install it from https://www.7-zip.org or pass --sevenzip \"<path>\\7z.exe\".")
    say("7-Zip: " + z7)
    lu_path = Path(a.lu)
    if not lu_path.is_file() or lu_path.name.lower() != "levelcommon.lu":
        die("--lu must point at your Naughty Bear levelcommon.lu (the file with exactly that name).")
    sha = hashlib.sha256(lu_path.read_bytes()).hexdigest()
    if sha != RETAIL_SHA256 and not a.skip_hash_check:
        die("This levelcommon.lu is not the retail file this example was built for (checksum "
            + sha[:12] + "... instead of " + RETAIL_SHA256[:12] + "...). It may already be modified or "
            "from another version. Use an untouched copy, or --skip-hash-check to try anyway.")
    say("levelcommon.lu is the retail file" if sha == RETAIL_SHA256 else "levelcommon.lu checksum differs (skipped)")
    out_dir = Path(a.out)
    out_file = out_dir / "levelcommon.lu"
    if out_file.exists():
        die(str(out_file) + " already exists. Pick another --out folder (this script never overwrites).")
    if a.check_only:
        print("\nAll checks passed. Nothing was changed (--check-only).")
        return
    sys.path.insert(0, str(tools))
    from naughty_lu import LuFile

    # ---------------------------------------------------------- 2
    step("Find the HUD movie",
         "The HUD is a Flash (Scaleform) movie stored inside levelcommon.lu as one",
         "record. We read the container and look for the record that holds it, by",
         "checking for the score-line text fields the game uses.")
    lf = LuFile(str(lu_path))
    found = None
    for r in lf.records:
        if r.type != GFX_TYPE or r.external:
            continue
        chunk = bytes(lf.chunk(r))
        loc = find_movie(chunk)
        if loc:
            raw = b"GFX" + chunk[loc[0] + 3:loc[0] + 8] + zlib.decompress(chunk[loc[0] + 8:loc[1]])
            if b"naughtyEventText" in raw:
                found = (r, chunk, loc, raw)
                break
    if not found:
        die("The HUD movie was not found in this file.")
    rec, chunk, (m0, m1), raw = found
    movie_len = m1 - m0
    say(f"movie is record {rec.index}: {movie_len:,} bytes compressed, {len(raw):,} bytes when opened")
    say("the edited movie must come out at exactly this size: the data after it in the record is")
    print("    addressed by absolute offsets that we do not want to move")
    body = raw[8:]
    nb = body[0] >> 3
    p0 = (5 + 4 * nb + 7) // 8 + 4
    tags = parse_tags(body, p0)
    prefix = body[:p0]

    # ---------------------------------------------------------- 3
    step("Add the feed clip",
         "The old single line is one clip whose two text fields are tied to global",
         "variables, so it can only ever show one message. We add a new clip with six",
         "slots, each its own small clip (so each can fade on its own), copying the",
         "game's own font and text style. It goes next to the old clip in both HUD",
         "layouts. The old clip stays but stays empty.")
    ID_SH, ID_AM, ID_SLOT, ID_FEED = 500, 501, 502, 503
    PITCH = 27.0
    OX, OY = -128.5, -25.5
    by_id = {}
    for t in tags:
        if t["t"] in (37, 39):
            by_id[(t["t"], struct.unpack_from("<H", t["data"], 0)[0])] = t
    if any(k[1] in (ID_SH, ID_AM, ID_SLOT, ID_FEED) for k in by_id):
        die("The feed clip is already in this movie.")
    try:
        assert edittext_var(by_id[(37, 239)]["data"]) == "_root.naughtyEventText"
        assert edittext_var(by_id[(37, 241)]["data"]) == "_root.naughtyEventText"
        assert (39, 243) in by_id and (39, 391) in by_id and (39, 411) in by_id
    except (AssertionError, KeyError):
        die("The HUD movie does not have the layout this example expects.")

    def nowrap(d):
        d = bytearray(d)
        n = d[2] >> 3
        q = 2 + (5 + 4 * n + 7) // 8
        d[q] &= ~0x60 & 0xFF
        return bytes(d)

    sh = nowrap(edittext_clone(by_id[(37, 239)]["data"], ID_SH, "t"))
    am = nowrap(edittext_clone(by_id[(37, 241)]["data"], ID_AM, "t"))
    new_tags = [mk_tag(37, sh), mk_tag(37, am)]
    slot = define_sprite(ID_SLOT, [place2(1, ID_SH, matrix(1.0, 1.5)), place2(2, ID_AM, matrix(0, 0)), mk_tag(1, b"")])
    inner = [place2(1 + i, ID_SLOT, matrix(OX, OY + PITCH * i), "s%d" % i) for i in range(6)]
    inner += [mk_tag(12, b"\x07\x00"), mk_tag(1, b"")]     # placeholder script; the real one is added in step 4
    feed = define_sprite(ID_FEED, inner)
    new_tags += [slot, feed]
    say("added six slots (s0 to s5), the feed clip, and its placement in both HUD layouts")

    def add_place(sprite_data, depth, mx):
        inn = parse_tags(sprite_data, 4)
        k = [i for i, t in enumerate(inn) if t["t"] == 1][-1]
        parts = [t["raw"] for t in inn[:k]] + [place2(depth, ID_FEED, mx, "FeedClip")] + [t["raw"] for t in inn[k:]]
        return mk_tag(39, sprite_data[:4] + b"".join(parts), force_long=True)

    POS = {391: (-446.45, -188.8), 411: (-411.5, -182.3)}
    sc = a.scale
    out_tags = []
    for t in tags:
        sid = struct.unpack_from("<H", t["data"], 0)[0] if t["t"] == 39 else None
        r_ = t["raw"]
        if sid in POS:
            px, py = POS[sid]
            r_ = add_place(t["data"], 800, matrix(px + (1 - sc) * OX, py + (1 - sc) * OY, sc, sc))
        out_tags.append(r_)
        if sid == 243:
            out_tags += new_tags
    m1_body = prefix + b"".join(out_tags)
    m1_raw = raw[:4] + struct.pack("<I", 8 + len(m1_body)) + m1_body

    # ---------------------------------------------------------- 4
    step("Compile the feed's script with JPEXS",
         "The feed needs a script: it keeps the six lines, shows them newest first,",
         "fades them, and tells the engine when a line has been shown. It is written",
         "in plain ActionScript and compiled by JPEXS's command-line tool. (An early",
         "version used array functions and misbehaved in this game's engine; this one",
         "uses only fixed values.)")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "m1.raw").write_bytes(m1_raw)
        d = td / "imp" / "scripts" / "DefineSprite_503" / "frame_1"
        d.mkdir(parents=True)
        src = (FEED_AS.replace("@HOLD@", str(a.hold)).replace("@FADE@", str(a.fade))
               .replace("@LIFE@", str(a.hold + a.fade)))
        (d / "DoAction.as").write_text(src, encoding="ascii")
        say("compiling (this starts Java and can take a few seconds)")
        cp = subprocess.run([ffdec, "-importScript", str(td / "m1.raw"), str(td / "m2.gfx"), str(td / "imp")],
                            capture_output=True, text=True)
        if not (td / "m2.gfx").exists():
            die("JPEXS did not produce a file:\n" + (cp.stdout + cp.stderr)[-600:])
        m2 = (td / "m2.gfx").read_bytes()
    m2b = m2[8:]
    nb2 = m2b[0] >> 3
    feed_do = None
    for t in parse_tags(m2b, (5 + 4 * nb2 + 7) // 8 + 4):
        if t["t"] == 39 and struct.unpack_from("<H", t["data"], 0)[0] == ID_FEED:
            for it in parse_tags(t["data"], 4):
                if it["t"] == 12:
                    feed_do = it["data"]
    if not feed_do or len(feed_do) < 100:
        die("The compiled script was not found in JPEXS's output.")
    say(f"compiled script: {len(feed_do):,} bytes")

    # ---------------------------------------------------------- 5
    step("Rewrite the live function and make room",
         "The engine calls one function, SetTextFearEvent, for every score line. We",
         "change it to pass the text and the score on to the new clip (it used to",
         "write them into the old single line). The movie must stay the same size, so",
         "we also remove five older functions that the game defines twice (the later",
         "definitions replace them), and blank string-table entries nothing uses.")
    big = [t for t in parse_tags(m1_body, p0) if t["t"] == 12 and len(t["data"]) > 10000]
    if len(big) != 1:
        die("The main HUD script was not found.")
    final_tags = []
    for t in parse_tags(m1_body, p0):
        r_ = t["raw"]
        if t["t"] == 12 and len(t["data"]) > 10000:
            try:
                code = rewrite_live_fn(t["data"])
                code, saved = remove_dead(code)
                code = trim_pool(code)
            except ValueError as e:
                die(str(e))
            say(f"live function rewritten; {saved:,} bytes of unused code removed")
            r_ = mk_tag(12, code, force_long=True)
        if t["t"] == 39 and struct.unpack_from("<H", t["data"], 0)[0] == ID_FEED:
            parts = [mk_tag(12, feed_do) if it["t"] == 12 else it["raw"] for it in parse_tags(t["data"], 4)]
            r_ = mk_tag(39, t["data"][:4] + b"".join(parts), force_long=True)
        final_tags.append(r_)
    f_body = prefix + b"".join(final_tags)
    f_raw = raw[:4] + struct.pack("<I", 8 + len(f_body)) + f_body

    # ---------------------------------------------------------- 6
    step("Compress the movie to exactly the original size",
         "The record holds tables that point past the movie by absolute offsets, so if",
         "the movie changed size, everything after it would have to move. Instead we",
         "compress with 7-Zip (it beats the normal compressor) and fill any leftover",
         "space with padding after the end of the movie, which the game ignores.")
    cfx, base = pack_exact(z7, f_raw, movie_len)
    if cfx is None:
        die(f"The edited movie is {base} bytes too big to fit the original space. "
            "Try a smaller --hold/--fade or report this.")
    if zlib.decompress(cfx[8:])[:len(f_raw) - 8] != f_raw[8:]:
        die("Internal check failed: the compressed movie does not open back to the same data.")
    say(f"compressed to {base:,} bytes, padded to exactly {movie_len:,}; opens back identically")

    # ---------------------------------------------------------- 7
    step("Write the new levelcommon.lu",
         "We put the new movie into a copy of the record and let Seam Ripper rebuild",
         "the container (it keeps the layout the engine requires). Only this one",
         "record changes; every other record stays byte for byte the same.")
    new_chunk = chunk[:m0] + cfx + chunk[m1:]
    assert len(new_chunk) == len(chunk)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "chunk.bin"
        cpath.write_bytes(new_chunk)
        cp = subprocess.run([sys.executable, str(tools / "lu_chunk_replace.py"), str(lu_path), str(cpath),
                             "--index", str(rec.index), "-o", str(out_file)], capture_output=True, text=True)
    if not out_file.exists():
        die("Seam Ripper could not write the container:\n" + (cp.stdout + cp.stderr)[-600:])
    say(cp.stdout.strip())

    # ---------------------------------------------------------- 8
    step("Check the result",
         "Seam Ripper's integrity check decodes the new file independently and checks",
         "the layout rules. We also confirm that only the HUD record differs.")
    cp = subprocess.run([sys.executable, str(tools / "verify_lzx.py"), str(out_file)], capture_output=True, text=True)
    last = (cp.stdout.strip().splitlines() or ["(no output)"])[-1]
    say("integrity check: " + last)
    if last.strip() != "PASS":
        out_file.unlink()
        die("The integrity check failed, so the new file was deleted.\n" + cp.stdout[-600:])
    nf = LuFile(str(out_file))
    diff = [i for i, (x, y) in enumerate(zip(lf.records, nf.records))
            if (x.offset, x.size) != (y.offset, y.size) or bytes(lf.chunk(x)) != bytes(nf.chunk(y))]
    say(f"records that differ from yours: {diff}")
    if diff != [rec.index] or len(lf.records) != len(nf.records):
        out_file.unlink()
        die("Unexpected records changed, so the new file was deleted.")

    print()
    print("=" * 72)
    print("Done:  " + str(out_file.resolve()))
    print("=" * 72)
    print("To try it: make a COPY of your game folder, put this levelcommon.lu in the")
    print("copy's lu folder, and run that copy. To undo, put your original file back.")
    print("Tested in Xenia on the retail Naughty Bear files only.")


if __name__ == "__main__":
    main()
