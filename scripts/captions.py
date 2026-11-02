#!/usr/bin/env python3
"""words.edited.json -> captions.ass (burned in) + captions.srt (for upload).

  python captions.py work/words.edited.json --out-dir work --style editorial [--size 1080x1920] [--y 0.685] [--lang en|hi]

Styles (modelled on what documentary / explainer creators actually use; sizes measured from reference reels)
  editorial  Inter Bold, white, sentence case as spoken, 1-3 words per page, no outline, soft blurred shadow.
             Small and calm (about 5.4% of the frame width). This is the default.
  pill       the same text on a rounded dark-grey translucent pill. Best over busy or bright screens and B-roll.
  serif      Instrument Serif Italic (a Didot-like high-contrast italic), larger, for aesthetic / luxury content.

Rules baked in: no all-caps, no thick outlines, no per-word colour flashing, no emoji. Pages follow the speech
(a page appears when its first word starts), break on punctuation and pauses, and are balanced 2+2 / 3+2
instead of leaving a lonely last word. Captions sit at ~68% of the height: above every app's bottom UI and clear
of the right-hand buttons. Optional --keywords tints chosen words (off by default).
"""
import argparse, json, re
from pathlib import Path
from pe_common import FONT_DIR, norm_word

PUNCT_BREAK = (",", ".", "?", "!", ";", ":", "…", "।")
SERIF_FAM = "Instrument Serif"
STOP = {"this", "that", "with", "have", "from", "they", "will", "your", "what", "when", "were", "been", "then",
        "than", "them", "into", "just", "like", "some", "very", "also", "more", "much", "about", "which", "there",
        "their", "would", "could", "should", "these", "those", "here", "where", "while", "every", "because"}
SYS_INTER = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FALLBACKS = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]

STYLES = {
    #            ASS family,       italic, PIL font file candidates,                       size % of width, max words, max chars
    "editorial": ("Inter", 0, [FONT_DIR / "Inter-Bold.otf", SYS_INTER, *FALLBACKS], 5.4, 3, 22),
    "pill": ("Inter", 0, [FONT_DIR / "Inter-Bold.otf", SYS_INTER, *FALLBACKS], 5.2, 3, 22),
    "serif": ("Instrument Serif", -1, [FONT_DIR / "InstrumentSerif-Italic.ttf", *FALLBACKS], 8.2, 3, 18),
}


def ass_color(hexc):
    h = hexc.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ts(t):
    t = max(0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def srt_ts(t):
    t = max(0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"


def find_font(cands):
    for c in cands:
        if Path(c).exists():
            return str(c)
    return None


class Measurer:
    """Text width as libass will draw it (libass sizes a font by ascent+descent, not by the em)."""

    def __init__(self, path, size):
        from PIL import ImageFont
        probe = ImageFont.truetype(path, 1000)
        asc, desc = probe.getmetrics()
        self.f = ImageFont.truetype(path, max(4, size / ((asc + desc) / 1000)))

    def width(self, text):
        return self.f.getlength(text)


def split_chunks(words, pause=0.30):
    """Group words into chunks that end at punctuation or a pause."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["w"].rstrip('"”').endswith(PUNCT_BREAK) or nxt["s"] - w["e"] > pause:
            chunks.append(cur)
            cur = []
    return chunks


def balanced_pages(chunk, max_words, max_chars):
    n = len(chunk)
    k = 1
    while True:  # fewest pages such that every page fits both limits when split evenly
        sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
        pos, ok = 0, True
        for sz in sizes:
            seg = chunk[pos:pos + sz]
            pos += sz
            if sz > max_words or sum(len(x["w"]) + 1 for x in seg) - 1 > max_chars:
                ok = False
        if ok or k >= n:
            break
        k += 1
    sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
    out, pos = [], 0
    for sz in sizes:
        out.append(chunk[pos:pos + sz])
        pos += sz
    return out


def clean(word):
    t = word.replace('"', "").replace("“", "").replace("”", "")
    t = re.sub(r"\.+$", "", t)
    t = re.sub(r"[;:]+$", "", t)
    return t


def rounded_rect(w, h, r):
    r = min(r, h / 2, w / 2)
    f = lambda v: f"{v:.1f}"
    return (f"m {f(r)} 0 l {f(w - r)} 0 b {f(w)} 0 {f(w)} 0 {f(w)} {f(r)} l {f(w)} {f(h - r)} "
            f"b {f(w)} {f(h)} {f(w)} {f(h)} {f(w - r)} {f(h)} l {f(r)} {f(h)} b 0 {f(h)} 0 {f(h)} 0 {f(h - r)} "
            f"l 0 {f(r)} b 0 0 0 0 {f(r)} 0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--out-dir", default="work")
    ap.add_argument("--style", default="editorial", choices=list(STYLES))
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--y", type=float, default=0.685, help="vertical centre of the caption, fraction of the height")
    ap.add_argument("--lang", default="en", help="hi => Devanagari-capable font (Hind)")
    ap.add_argument("--font-pct", type=float, default=0, help="override font size, %% of frame width")
    ap.add_argument("--keywords", default="", help="comma separated words to tint (off by default)")
    ap.add_argument("--accent", default="#FFD60A")
    ap.add_argument("--hide", default="", help="windows without captions, e.g. '9-12.5,13-15.5' (full-screen cards)")
    ap.add_argument("--emph", default="auto", choices=["none", "auto", "all"],
                    help="mix: the key word of some pages is set in italic serif inside the bold sans caption "
                         "(auto = about 45%% of pages, all = every page that has a key word)")
    a = ap.parse_args()
    hide = [tuple(float(v) for v in w.split("-")) for w in a.hide.split(",") if w.strip()]

    W, H = map(int, a.size.split("x"))
    j = json.load(open(a.words, encoding="utf-8"))
    words = j["words"]
    fam, italic, cands, pct, max_words, max_chars = STYLES[a.style]
    if a.lang.startswith("hi"):
        fam, italic, cands = "Hind", 0, [FONT_DIR / "Hind-Bold.ttf", *FALLBACKS]
    size = int(W * (a.font_pct or pct) / 100)
    fpath = find_font(cands)
    meas = Measurer(fpath, size) if fpath else None
    es = int(size * 1.30)  # the serif word is a little larger: serif letters look smaller at the same size
    sf = find_font([FONT_DIR / "InstrumentSerif-Italic.ttf"])
    serif_meas = Measurer(sf, es) if sf else None
    cx, cy = W // 2, int(H * a.y)
    kw = {tuple(norm_word(x) for x in k.split()) for k in a.keywords.split(",") if k.strip()}
    tint = set()
    if kw:
        nw = [norm_word(w["w"]) for w in words]
        for ph in kw:
            for i in range(len(words) - len(ph) + 1):
                if tuple(nw[i:i + len(ph)]) == ph:
                    tint.update(range(i, i + len(ph)))
    for i, w in enumerate(words):
        w["_i"] = i

    pages = []
    for ch in split_chunks(words):
        pages += balanced_pages(ch, max_words, max_chars)

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{fam},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{0 if italic else -1},{italic},0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for pi, pg in enumerate(pages):
        if any(pg[0]["s"] < h1 and pg[-1]["e"] > h0 for h0, h1 in hide):
            continue
        # the key word of the page = the last content word; it is set in italic serif (the "mix")
        emph_i = None
        if a.emph != "none" and serif_meas and a.style != "serif" and not a.lang.startswith("hi") \
                and (a.emph == "all" or (pi * 0.618) % 1 < 0.45):
            cands_i = [k for k, w in enumerate(pg) if len(norm_word(w["w"])) >= 4 and norm_word(w["w"]) not in STOP]
            emph_i = cands_i[-1] if cands_i else None
        parts, sparts, widths = [], [], []
        for k, w in enumerate(pg):
            t = clean(w["w"])
            if k == emph_i:
                # italic serif is thin next to bold sans: a hair-line outline in the text colour gives it weight
                tag_in = r"{\fn%s\i1\b0\fs%d\bord1.4\3c&HFFFFFF&}" % (SERIF_FAM, es)
                tag_out = r"{\fn%s\i0\b1\fs%d\bord0}" % (fam, size)
                parts.append(tag_in + t + tag_out)
                sparts.append((tag_in + t + tag_out).replace(r"\3c&HFFFFFF&", r"\3c&H000000&"))
                widths.append(serif_meas.width(t) + 2.8)
                continue
            sparts.append(t)
            widths.append(meas.width(t) if meas else 0)
            if w["_i"] in tint:
                t = r"{\1c%s}%s{\1c&HFFFFFF&}" % (ass_color(a.accent), t)
            parts.append(t)
        text = " ".join(parts)
        shadow_text = " ".join(sparts)
        plain = " ".join(clean(w["w"]) for w in pg)
        text_w = sum(widths) + (meas.width(" ") * (len(pg) - 1) if meas else 0)
        s = max(0, pg[0]["s"] - 0.02)
        nxt = pages[pi + 1][0]["s"] if pi + 1 < len(pages) else 1e9
        e = pg[-1]["e"] + 0.14
        if nxt - pg[-1]["e"] < 0.30:
            e = nxt - 0.005  # no flicker between neighbouring pages
        e = min(e, nxt - 0.005)
        e = max(e, s + 0.30)
        fade = r"\fad(70,50)"
        pop = r"\fscx94\fscy94\t(0,110,\fscx100\fscy100)"
        if a.style == "pill" and meas:
            tw = text_w
            padx, pady = size * 0.50, size * 0.30
            pw, ph = tw + 2 * padx, size * 1.16 + 2 * pady - size * 0.16
            x0, y0 = cx - pw / 2, cy - ph / 2
            ev.append(f"Dialogue: 0,{ts(s)},{ts(e)},Main,,0,0,0,,{{\\an7\\pos({x0:.0f},{y0:.0f}){fade}\\bord0\\shad0"
                      f"\\1c&H4D4A4A&\\1a&H38&\\p1}}{rounded_rect(pw, ph, size * 0.36)}{{\\p0}}")
            ev.append(f"Dialogue: 1,{ts(s)},{ts(e)},Main,,0,0,0,,{{\\an5\\pos({cx},{cy}){fade}{pop}\\bord0\\shad0}}{text}")
        else:
            # soft shadow = the same text, black, blurred, nudged down; then the crisp white text on top
            ev.append(f"Dialogue: 0,{ts(s)},{ts(e)},Main,,0,0,0,,{{\\an5\\pos({cx + 1},{cy + int(size * 0.07)}){fade}"
                      f"\\bord0\\shad0\\1c&H000000&\\1a&H78&\\blur{max(3, size // 9)}}}{shadow_text}")
            ev.append(f"Dialogue: 1,{ts(s)},{ts(e)},Main,,0,0,0,,{{\\an5\\pos({cx},{cy}){fade}{pop}\\bord0\\shad0}}{text}")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "captions.ass").write_text(head + "\n".join(ev) + "\n", encoding="utf-8")

    # sentence-level SRT for upload (<=42 chars per line, <=2 lines, >=0.83 s)
    sent, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"].endswith((".", "?", "!", "…", "।")) or sum(len(x["w"]) + 1 for x in cur) > 74:
            sent.append(cur)
            cur = []
    if cur:
        sent.append(cur)
    lines = []
    for i, sg in enumerate(sent, 1):
        text = " ".join(w["w"].replace('"', "") for w in sg)
        if len(text) > 42:
            mid = len(text) // 2
            cut = text.rfind(" ", 0, mid + 8)
            text = text[:cut] + "\n" + text[cut + 1:]
        s, e = sg[0]["s"], max(sg[-1]["e"] + 0.3, sg[0]["s"] + 0.83)
        lines.append(f"{i}\n{srt_ts(s)} --> {srt_ts(e)}\n{text}\n")
    (out / "captions.srt").write_text("\n".join(lines), encoding="utf-8")
    print(f"style={a.style} font={fam} {size}px | {len(pages)} pages -> {out/'captions.ass'}; {len(sent)} lines -> captions.srt")


if __name__ == "__main__":
    main()
