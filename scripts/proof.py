#!/usr/bin/env python3
"""Approval gate: show the user the exact frames the video will contain BEFORE the full render.

  python proof.py proof_spec.json

proof_spec.json
{
  "video": "work/cut.mp4", "words": "work/words.edited.json", "plan": "work/plan.json", "out": "proof",
  "size": "1080x1920",
  "frames": [
    {"id": "F1", "t": 1.2, "caption": "editorial", "note": "Caption on the talking shot"},
    {"id": "F2", "t": 4.2, "caption": "editorial", "note": "Serif title card over the face"},
    {"id": "F5", "t": 14.0, "caption": "pill", "hide_captions": false, "note": "Caption on a dark scene"}
  ]
}
Every frame is drawn by the same render graph as the final video (zoom, grade, b-roll, cards, captions, grain),
so what is approved is what is delivered. Outputs: proof/F1.png ... and proof/proof_sheet.png (numbered).
After the user answers, edit plan.json / the caption style for the rejected frames only, run this again with
just those ids, and re-send. Render the full video only when every frame is approved.
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent


def sh(cmd):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-1500:] + p.stderr[-2500:])
        raise SystemExit(f"failed: {' '.join(map(str, cmd))[:200]}")
    return p.stdout


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = Path(spec.get("out", "proof"))
    out.mkdir(parents=True, exist_ok=True)
    size = spec.get("size", "1080x1920")
    frames = spec["frames"]
    by_style = {}
    for f in frames:
        by_style.setdefault((f.get("caption", "editorial"), f.get("lang", "en"), f.get("emph", spec.get("emph", "auto"))), []).append(f)

    done = {}
    for (style, lang, emph), fs in by_style.items():
        cdir = out / f"_cap_{style}_{emph}"
        cmd = [sys.executable, HERE / "captions.py", spec["words"], "--out-dir", cdir, "--style", style, "--size", size, "--lang", lang, "--emph", emph]
        if spec.get("caption_y"):
            cmd += ["--y", spec["caption_y"]]
        if spec.get("hide"):
            cmd += ["--hide", spec["hide"]]
        sh(cmd)
        fs = sorted(fs, key=lambda f: f["t"])
        pdir = out / f"_p_{style}_{emph}"
        sh([sys.executable, HERE / "render.py", spec["video"], "--plan", spec["plan"], "--captions", cdir / "captions.ass",
            "--out", pdir, "--proof", ",".join(str(f["t"]) for f in fs)])
        for img, f in zip(sorted(pdir.glob("proof_*.png")), fs):
            dst = out / f"{f['id']}.png"
            dst.write_bytes(img.read_bytes())
            done[f["id"]] = (dst, f)

    from PIL import Image, ImageDraw, ImageFont
    fnt = lambda s: ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Bold.otf", s) if Path("/usr/share/fonts/opentype/inter/Inter-Bold.otf").exists() else ImageFont.load_default()
    cell_w, cols = 520, 3
    tiles = []
    for fid in [f["id"] for f in frames]:
        dst, f = done[fid]
        im = Image.open(dst).convert("RGB")
        im = im.resize((cell_w, int(im.height * cell_w / im.width)), Image.LANCZOS)
        tile = Image.new("RGB", (cell_w, im.height + 96), (20, 20, 22))
        tile.paste(im, (0, 0))
        d = ImageDraw.Draw(tile)
        d.rounded_rectangle((12, 12, 74, 52), radius=10, fill=(255, 255, 255))
        d.text((24, 16), fid, font=fnt(24), fill=(0, 0, 0))
        import textwrap
        for li, ln in enumerate(textwrap.wrap(f.get("note", ""), 40)[:2]):
            d.text((14, im.height + 12 + li * 28), ln, font=fnt(19), fill=(235, 235, 235))
        tiles.append(tile)
    rows = (len(tiles) + cols - 1) // cols
    th = max(t.height for t in tiles)
    sheet = Image.new("RGB", (cell_w * cols + 12 * (cols + 1), th * rows + 12 * (rows + 1)), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, (12 + (i % cols) * (cell_w + 12), 12 + (i // cols) * (th + 12)))
    sheet.save(out / "proof_sheet.png")
    print(f"{len(frames)} frames -> {out}/F*.png and {out}/proof_sheet.png")


if __name__ == "__main__":
    main()
