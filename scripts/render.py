#!/usr/bin/env python3
"""cut.mp4 + plan.json (+ captions.ass, master.wav) -> final video, in ONE encode.

  python render.py work/cut.mp4 --plan work/plan.json --captions work/captions.ass \
         --audio work/master.wav --out out/final.mp4 [--preview]   # --preview = quick low-res check

Order of work inside one ffmpeg graph:
  zoom/framing (per-frame scale+crop around the face) -> colour grade -> b-roll and cards on top
  -> resize to the delivery size -> film grain over everything (so AI clips and real footage share one texture)
  -> captions burned in last (always sharp).
"""
import argparse, json, subprocess, tempfile
from pathlib import Path
from pe_common import FONT_DIR, probe, run

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def zexpr(zooms):
    terms = []
    for z in zooms:
        k = z["kind"]
        if k == "frame":
            terms.append(f"{z['to'] - 1:.4f}*between(t,{z['t0']},{z['t1']})")
        elif k == "push":
            span = max(0.1, z["t1"] - z["t0"])
            terms.append(f"{z['to'] - 1:.4f}*between(t,{z['t0']},{z['t1']})*clip((t-{z['t0']})/{span:.3f},0,1)")
        elif k == "snap":
            t, h = z["t"], z.get("hold", 0.9)
            terms.append(f"{z['to'] - 1:.4f}*(1-pow(1-clip((t-{t})/0.18,0,1),3))*(1-clip((t-{t + h:.3f})/0.35,0,1))")
    return "min(1.35,1+" + "+".join(terms) + ")" if terms else "1"


def grade_chain(g, sharpen=True):
    parts = [f"eq=contrast={g.get('contrast', 1.0)}:saturation={g.get('saturation', 1.0)}:brightness={g.get('brightness', 0.0)}"]
    if g.get("temp", 6500) != 6500:
        parts.append(f"colortemperature=temperature={g['temp']}")
    if sharpen and g.get("sharpen", 0) > 0:
        parts.append(f"unsharp=5:5:{g['sharpen']}:5:5:0.0")
    return ",".join(parts)


def font(path_name, size):
    from PIL import ImageFont
    for p in (FONT_DIR / path_name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if Path(p).exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def make_card(c, W, tmp, idx):
    from PIL import Image, ImageDraw
    big = c.get("text", "")
    sub = c.get("sub", "")
    col = c.get("color", "#FFD400")
    fbig = font("Poppins-Black.ttf", int(W * 0.082))
    fsub = font("Poppins-SemiBold.ttf", int(W * 0.040))
    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = d0.textbbox((0, 0), big.upper(), font=fbig)
    bs = d0.textbbox((0, 0), sub, font=fsub) if sub else (0, 0, 0, 0)
    pad = int(W * 0.04)
    w = min(int(W * 0.88), max(bb[2] - bb[0], bs[2] - bs[0]) + pad * 2 + 18)
    h = (bb[3] - bb[1]) + ((bs[3] - bs[1]) + int(W * 0.018) if sub else 0) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(W * 0.03), fill=(12, 12, 14, 215))
    d.rounded_rectangle((0, 0, 14, h - 1), radius=7, fill=col)
    y = pad - bb[1]
    d.text((pad + 14, y), big.upper(), font=fbig, fill=(255, 255, 255, 255))
    if sub:
        d.text((pad + 14, pad + (bb[3] - bb[1]) + int(W * 0.018) - bs[1]), sub, font=fsub, fill=col)
    p = Path(tmp) / f"card{idx}.png"
    img.save(p)
    return p, w, h


def rounded_mask(w, h, r, tmp, idx):
    from PIL import Image, ImageDraw
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    p = Path(tmp) / f"mask{idx}.png"
    m.save(p)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--captions", default="")
    ap.add_argument("--audio", default="")
    ap.add_argument("--out", default="out/final.mp4")
    ap.add_argument("--fonts", default=str(FONT_DIR))
    ap.add_argument("--preview", action="store_true", help="540x960, fast preset")
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--proof", default="", help="comma separated times in seconds: write only those frames as PNG into the folder given by --out, then stop")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    info = probe(a.video)
    W0, H0, fps = info["width"], info["height"], round(info["fps"]) or 30
    OW, OH = plan.get("size", [1080, 1920])
    if a.preview:
        OW, OH = OW // 2, OH // 2
    g = plan.get("grade", {})
    fy = plan.get("face_y", 0.38)
    tmp = tempfile.mkdtemp(prefix="pe_render_")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)

    inputs = ["-i", a.video]
    chains = []
    z = zexpr(plan.get("zooms", []))
    base = "[0:v]"
    if z != "1":
        base += (f"scale=w='trunc(iw*({z})/2)*2':h='trunc(ih*({z})/2)*2':eval=frame:flags=bicubic,"
                 f"crop={W0}:{H0}:x='(iw-{W0})/2':y='(ih-{H0})*{fy}',")
    chains.append(f"{base}fps={fps},{grade_chain(g)},format=yuv420p[v0]")
    cur, n_in = "v0", 1

    for k, b in enumerate(plan.get("broll", []), 1):
        src = Path(b["src"])
        t0, t1 = b["t0"], b["t1"]
        D = round(t1 - t0, 3)
        isimg = src.suffix.lower() in IMG_EXT
        inputs += (["-loop", "1", "-framerate", str(fps), "-i", str(src)] if isimg
                   else ["-stream_loop", "-1", "-i", str(src)])
        ci = n_in
        n_in += 1
        mode = b.get("mode", "full")
        st = 0 if isimg else b.get("start", 0)
        push = b.get("push", 1.05)
        if mode == "card":
            cw, ch = int(W0 * 0.90), int(H0 * 0.34)
            fitw, fith = cw, ch
        else:
            cw, ch = W0, H0
            fitw, fith = W0, H0
        pz = f"1+{push - 1:.4f}*clip(t/{D},0,1)"
        pre = (f"[{ci}:v]trim=start={st}:duration={D},setpts=PTS-STARTPTS,fps={fps},"
               f"scale={fitw}:{fith}:force_original_aspect_ratio=increase:flags=lanczos,crop={fitw}:{fith},"
               f"scale=w='trunc(iw*({pz})/2)*2':h='trunc(ih*({pz})/2)*2':eval=frame,crop={fitw}:{fith},"
               f"{grade_chain(g, sharpen=False)},format=yuva420p")
        if mode == "card":
            mp = rounded_mask(cw, ch, int(W0 * 0.035), tmp, k)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", str(D + 1), "-i", str(mp)]
            mi = n_in
            n_in += 1
            chains.append(pre + f"[bc{k}];[{mi}:v]format=gray,fps={fps}[mm{k}];"
                          f"[bc{k}][mm{k}]alphamerge=shortest=1,setpts=PTS+{t0}/TB,"
                          f"fade=t=in:st={t0}:d=0.12:alpha=1,fade=t=out:st={t1 - 0.12:.3f}:d=0.12:alpha=1[b{k}]")
            ov = f"overlay=x=(W-w)/2:y={b.get('y', 0.07)}*H:eof_action=pass"
        else:
            chains.append(pre + f",setpts=PTS+{t0}/TB,"
                          f"fade=t=in:st={t0}:d=0.10:alpha=1,fade=t=out:st={t1 - 0.10:.3f}:d=0.10:alpha=1[b{k}]")
            ov = "overlay=0:0:eof_action=pass"
        chains.append(f"[{cur}][b{k}]{ov}:enable='between(t,{t0},{t1})'[o{k}]")
        cur = f"o{k}"

    for k, c in enumerate(plan.get("cards", []), 1):
        if c.get("png"):  # a finished overlay made by cards.py (serif title, quote...)
            png = Path(c["png"])
        else:
            png, cw, ch = make_card(c, W0, tmp, k)
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(png)]
        ci = n_in
        n_in += 1
        t0, t1 = c["t0"], c["t1"]
        y0 = c.get("y", 0.11)
        chains.append(f"[{ci}:v]format=rgba,fade=t=in:st={t0}:d=0.2:alpha=1,fade=t=out:st={t1 - 0.2:.3f}:d=0.2:alpha=1[c{k}]")
        chains.append(f"[{cur}][c{k}]overlay=x=(W-w)/2:y='{y0}*H+34*(1-clip((t-{t0})/0.28,0,1))':"
                      f"enable='between(t,{t0},{t1})'[oc{k}]")
        cur = f"oc{k}"

    tail = []
    if (OW, OH) != (W0, H0):
        tail.append(f"scale={OW}:{OH}:flags=lanczos")
    if g.get("grain", 0):
        tail.append(f"noise=alls={g['grain']}:allf=t")
    if a.captions:
        cap = Path(a.captions).resolve()
        tail.append(f"ass='{cap}':fontsdir='{a.fonts}'")
    times = sorted(float(x) for x in a.proof.split(",") if x.strip()) if a.proof else []
    if times:
        sel = "+".join(f"between(t,{t - 0.0166:.4f},{t + 0.0166:.4f})" for t in times)
        tail.append(f"select='{sel}'")
    else:
        tail.append("format=yuv420p")
    chains.append(f"[{cur}]{','.join(tail)}[vout]")

    script = Path(tmp) / "graph.txt"
    script.write_text(";\n".join(chains))
    if times:
        outdir = Path(a.out)
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("proof_*.png"):
            old.unlink()
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", script, "-map", "[vout]",
               "-fps_mode", "vfr", "-t", f"{times[-1] + 0.2:.2f}", "-frames:v", str(len(times)), str(outdir / "proof_%02d.png")]
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
        got = sorted(outdir.glob("proof_*.png"))
        if p.returncode != 0 or len(got) != len(times):
            print(p.stderr[-2000:])
            raise SystemExit(f"proof frames: wanted {len(times)}, got {len(got)}")
        print(f"wrote {len(got)} proof frames -> {outdir}")
        return
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats", *inputs]
    if a.audio:
        cmd += ["-i", a.audio]
    cmd += ["-filter_complex_script", script, "-map", "[vout]"]
    if a.audio:
        cmd += ["-map", f"{n_in}:a", "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast" if a.preview else "medium", "-crf", str(28 if a.preview else a.crf),
            "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", "-shortest", a.out]
    print("rendering...", len(plan.get("broll", [])), "b-roll,", len(plan.get("cards", [])), "cards")
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-2500:])
        print("graph kept at", script)
        raise SystemExit(1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
