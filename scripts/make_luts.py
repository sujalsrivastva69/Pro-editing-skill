#!/usr/bin/env python3
"""Write 5 colour-grading LUTs (.cube, 33^3) to ~/.cache/pro-editor/luts. No third-party pack, no licence issues.

  python make_luts.py              # writes clean, warm_film, teal_orange, moody, punchy
  python make_luts.py --sheet luts_sheet.png --image frame.png   # preview every LUT on one frame (for approval)

Use: suggest_plan.py ... --lut warm_film   (or put "lut": "warm_film" inside plan.json -> grade).
Any .cube file downloaded from elsewhere can be dropped into the luts folder or given as a full path.
All grades are mild on purpose: heavy LUTs on phone footage look fake.
"""
import argparse, subprocess, sys
import numpy as np
from pe_common import CACHE

LUT_DIR = CACHE / "luts"
N = 33
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def scurve(x, k):
    """k>0 adds contrast around mid grey, keeps 0 and 1 fixed."""
    return np.clip(x + k * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2, 0, 1)


def sat(rgb, s):
    y = (rgb * LUMA).sum(-1, keepdims=True)
    return np.clip(y + (rgb - y) * s, 0, 1)


def clean(c):
    return sat(scurve(c, 0.10), 1.05)


def warm_film(c):
    c = scurve(c, 0.14)
    y = (c * LUMA).sum(-1, keepdims=True)
    hi = np.clip((y - 0.5) * 2, 0, 1)
    c = c + hi * np.array([0.030, 0.012, -0.030], np.float32)           # warm highlights
    c = c + (1 - y) * np.array([0.004, 0.002, 0.012], np.float32) * 0.5  # slightly cool lifted shadows
    c = 0.025 + c * 0.965                                                # faded blacks (film)
    return np.clip(sat(c, 0.94), 0, 1)


def teal_orange(c):
    c = scurve(c, 0.16)
    y = (c * LUMA).sum(-1, keepdims=True)
    sh, hi = np.clip(1 - y * 2, 0, 1), np.clip((y - 0.45) * 2, 0, 1)
    c = c + sh * np.array([-0.020, 0.012, 0.028], np.float32) + hi * np.array([0.030, 0.008, -0.026], np.float32)
    return np.clip(sat(c, 1.04), 0, 1)


def moody(c):
    c = scurve(c, 0.22) * 0.94
    y = (c * LUMA).sum(-1, keepdims=True)
    c = c + np.clip(1 - y * 2.2, 0, 1) * np.array([-0.012, 0.002, 0.022], np.float32)
    return np.clip(sat(c, 0.86), 0, 1)


def punchy(c):
    return sat(scurve(c, 0.20), 1.18)


LUTS = {"clean": clean, "warm_film": warm_film, "teal_orange": teal_orange, "moody": moody, "punchy": punchy}


def write_cube(name, fn):
    g = np.linspace(0, 1, N, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube: red changes fastest
    grid = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = fn(grid)
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    p = LUT_DIR / f"{name}.cube"
    with open(p, "w") as f:
        f.write(f'TITLE "{name}"\nLUT_3D_SIZE {N}\n')
        for v in out:
            f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
    return p


def resolve(name):
    """name or path -> existing .cube path (used by render.py)"""
    from pathlib import Path
    p = Path(name)
    if p.exists():
        return p
    q = LUT_DIR / (name if name.endswith(".cube") else name + ".cube")
    if not q.exists() and name in LUTS:
        q = write_cube(name, LUTS[name])
    return q if q.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", help="write a before/after sheet of all LUTs on --image")
    ap.add_argument("--image", help="a frame (png/jpg) to preview on")
    a = ap.parse_args()
    paths = {n: write_cube(n, f) for n, f in LUTS.items()}
    print("LUTs:", ", ".join(paths), "->", LUT_DIR)
    if a.sheet and a.image:
        from PIL import Image, ImageDraw, ImageFont
        tiles = [("original", Image.open(a.image).convert("RGB"))]
        for n, p in paths.items():
            tmp = f"/tmp/_lut_{n}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.image, "-vf", f"lut3d=file='{p}':interp=tetrahedral", tmp], check=True)
            tiles.append((n, Image.open(tmp).convert("RGB")))
        w = 360
        tiles = [(n, im.resize((w, int(im.height * w / im.width)))) for n, im in tiles]
        h = max(im.height for _, im in tiles)
        cols = 3
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (w + 10) + 10, rows * (h + 44) + 10), (12, 12, 14))
        d = ImageDraw.Draw(sheet)
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Bold.otf", 24)
        except OSError:
            fnt = ImageFont.load_default()
        for i, (n, im) in enumerate(tiles):
            x, y = 10 + (i % cols) * (w + 10), 10 + (i // cols) * (h + 44)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + h + 8), f"L{i}  {n}" if i else "original", font=fnt, fill=(235, 235, 235))
        sheet.save(a.sheet)
        print("sheet ->", a.sheet)


if __name__ == "__main__":
    main()
