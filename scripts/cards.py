#!/usr/bin/env python3
"""Make the graphic cards that appear between talking shots. Output is always a PNG that render.py places.

  python cards.py serif  --text "1. Read aloud" --out work/title1.png            # transparent overlay, italic serif
  python cards.py info   --label "FOR EXAMPLE" --caption "Daily practice" --image pic.jpg --out work/c1.png
  python cards.py info   --theme dark --title "Custom" --image shot.png --out work/c2.png   # screen / AI-clip scene
  python cards.py quote  --text "Practice" --out work/q.png                        # big word with curly quotes

Looks (taken from documentary / explainer reels):
  serif  big white Instrument Serif Italic with a soft shadow, sits over the face footage or a dark scene
  info   light: soft grey studio background, small tracked-out CAPS label, image on a rounded card with a deep
         soft shadow, bold Inter caption under it.  dark: navy gradient, italic serif title, image in a thin
         white-bordered rounded frame (good for screen recordings and AI clips)
  quote  one big word in curly quotes over the footage
Fonts come from ~/.cache/pro-editor/fonts (setup_assets.py), falling back to Liberation Sans / DejaVu.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pe_common import FONT_DIR

SYS = "/usr/share/fonts/opentype/inter/"
LIB = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def font(names, size):
    for n in names:
        for base in (FONT_DIR, Path(SYS)):
            p = Path(base) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.truetype(LIB, size)


def tracked(draw, xy, text, f, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking


def tracked_width(draw, text, f, tracking):
    return sum(draw.textlength(c, font=f) + tracking for c in text) - tracking


def shadow_layer(size, box, radius, blur, offset=(0, 0), alpha=110):
    lay = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    x0, y0, x1, y1 = box
    d.rounded_rectangle((x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]), radius=radius, fill=(0, 0, 0, alpha))
    return lay.filter(ImageFilter.GaussianBlur(blur))


def cover(img, w, h):
    img = img.convert("RGB")
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=r, fill=255)
    out = img.convert("RGBA")
    out.putalpha(m)
    return out


def serif(a):
    W = int(a.size.split("x")[0])
    f = font(["InstrumentSerif-Italic.ttf"], int(W * a.size_pct / 100))
    d0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    bb = d0.textbbox((0, 0), a.text, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    pad = int(W * 0.06)
    img = Image.new("RGBA", (W, h + pad * 2 + 20), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text(((W - w) // 2 - bb[0], pad - bb[1] + 6), a.text, font=f, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(int(W * 0.008) + 3)))
    ImageDraw.Draw(img).text(((W - w) // 2 - bb[0], pad - bb[1]), a.text, font=f, fill=(255, 255, 255, 255))
    img.save(a.out)
    print("wrote", a.out, img.size)


def quote(a):
    a.text = "“" + a.text + "”"
    a.size_pct = a.size_pct or 17
    serif(a)


def info(a):
    W, H = map(int, a.size.split("x"))
    dark = a.theme == "dark"
    import numpy as np
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    if dark:
        k = (yy / H)[..., None]
        top, bot = np.array([7, 11, 34], np.float32), np.array([13, 19, 56], np.float32)
        base = top * (1 - k) + bot * k
        d2 = ((xx - W * 0.5) / (W * 0.62)) ** 2 + ((yy - H * 0.60) / (H * 0.30)) ** 2
        glow = np.exp(-d2 * 1.6)[..., None] * np.array([40, 30, 118], np.float32)
        arr = np.clip(base + glow, 0, 255)
        ink, sub = (255, 255, 255), (190, 196, 230)
    else:
        d = np.sqrt(((xx - W * 0.5) / (W * 0.78)) ** 2 + ((yy - H * 0.46) / (H * 0.62)) ** 2)
        t = np.clip(d, 0, 1)[..., None] ** 1.6
        arr = np.array([247, 247, 248], np.float32) * (1 - t) + np.array([201, 202, 207], np.float32) * t
        ink, sub = (14, 14, 16), (60, 60, 64)
    arr = arr + np.random.default_rng(3).normal(0, 0.9, (H, W, 1))  # dither: no banding after video compression
    bg = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    img = bg.convert("RGBA")
    d = ImageDraw.Draw(img)

    ch = int(H * a.image_h)
    cw = int(W * a.image_w)
    f_label = font(["Inter-Medium.otf", "Inter-Bold.otf"], int(W * 0.024))
    f_cap = font(["Inter-Bold.otf"], int(W * 0.066))
    f_title = font(["InstrumentSerif-Italic.ttf"], int(W * 0.15))
    label_h = int(W * 0.03) if a.label else 0
    cap_h = int(W * 0.08) if a.caption else 0
    title_h = int(W * 0.17) if (a.title and dark) else 0
    gap = int(W * 0.045)
    total = title_h + label_h + (gap if a.label else 0) + ch + (gap if a.caption else 0) + cap_h
    y = int(H * a.center - total / 2)

    if a.title and dark:
        bb = d.textbbox((0, 0), a.title, font=f_title)
        d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y - bb[1]), a.title, font=f_title, fill=ink)
        y += title_h
    if a.label:
        tw = tracked_width(d, a.label.upper(), f_label, W * 0.004)
        tracked(d, ((W - tw) / 2, y), a.label.upper(), f_label, ink if not dark else sub, W * 0.004)
        y += label_h + gap
    x = (W - cw) // 2
    box = (x, y, x + cw, y + ch)
    rad = int(W * 0.03)
    img.alpha_composite(shadow_layer((W, H), box, rad, int(W * (0.018 if dark else 0.03)), (0, int(W * 0.02)), 150 if not dark else 170))
    if a.image:
        pic = rounded(cover(Image.open(a.image), cw, ch), rad)
        img.alpha_composite(pic, (x, y))
    d = ImageDraw.Draw(img)
    if dark:
        d.rounded_rectangle(box, radius=rad, outline=(255, 255, 255), width=max(3, int(W * 0.004)))
    y += ch + gap
    if a.caption:
        bb = d.textbbox((0, 0), a.caption, font=f_cap)
        d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y - bb[1]), a.caption, font=f_cap, fill=ink)
    img.convert("RGB").save(a.out, quality=95)
    print("wrote", a.out, img.size)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serif", "quote", "info"):
        p = sp.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--size", default="1080x1920")
        p.add_argument("--text", default="")
        p.add_argument("--size-pct", type=float, default=13.5 if name == "serif" else 0)
        p.add_argument("--label", default="")
        p.add_argument("--caption", default="")
        p.add_argument("--title", default="")
        p.add_argument("--image", default="")
        p.add_argument("--theme", default="light", choices=["light", "dark"])
        p.add_argument("--image-w", type=float, default=0.90)
        p.add_argument("--image-h", type=float, default=0.32)
        p.add_argument("--center", type=float, default=0.44, help="vertical centre of the group (fraction of height)")
    a = ap.parse_args()
    {"serif": serif, "quote": quote, "info": info}[a.cmd](a)


if __name__ == "__main__":
    main()
