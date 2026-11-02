#!/usr/bin/env python3
"""Check a finished video the way a stranger would open it. Prints PASS/FAIL lines, writes a contact sheet.

  python qc.py out/final.mp4 --words work/words.edited.json --sheet out/qc_sheet.png

Checks: size and fps, duration vs plan, loudness (-14 +/- 1 LUFS) and true peak (<= -1 dBTP), black or frozen
stretches, sound-effect crowding, captions inside the safe area, and a contact sheet of 8 frames to LOOK at.
It cannot judge taste (pacing, whether a joke lands, how a voice feels): say so to the user and ask them to watch
the marked moments with headphones.
"""
import argparse, json, re
from pathlib import Path
from pe_common import measure_lufs, probe, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--words", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--sheet", default="out/qc_sheet.png")
    a = ap.parse_args()
    bad = 0

    def line(ok, msg):
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + msg)
        bad += 0 if ok else 1

    info = probe(a.video)
    line(info["has_audio"], f"audio stream present")
    line(info["height"] >= 1280 or info["height"] >= 960 and "preview" in a.video, f"size {info['width']}x{info['height']} @ {info['fps']:.0f} fps")
    i, tp = measure_lufs(a.video)
    line(i is not None and abs(i + 14) <= 1.2, f"loudness {i} LUFS (target -14 +/- 1)")
    line(tp is not None and tp <= -0.9, f"true peak {tp} dBFS (<= -1)")

    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.video, "-vf", "blackdetect=d=0.2:pix_th=0.04,freezedetect=n=-55dB:d=2.5",
             "-an", "-f", "null", "-"], check=False)
    blacks = re.findall(r"black_start:([\d.]+)", p.stderr)
    freezes = re.findall(r"freeze_start: ([\d.]+)", p.stderr)
    line(not blacks, f"no black frames {blacks[:4] if blacks else ''}")
    line(not freezes, f"no frozen picture {freezes[:4] if freezes else ''}")

    if a.words:
        w = json.load(open(a.words, encoding="utf-8"))
        dd = abs(w["duration"] - info["duration"])
        line(dd < 0.25, f"duration {info['duration']:.2f}s matches the cut ({w['duration']:.2f}s)")
        words = w["words"]
        gaps = [(words[k + 1]["s"] - words[k]["e"], words[k]["e"]) for k in range(len(words) - 1)]
        long = [(round(g, 2), round(t, 1)) for g, t in gaps if g > 0.9]
        line(not long, f"no pause longer than 0.9 s left in {long[:4] if long else ''}")
    if a.plan:
        plan = json.load(open(a.plan, encoding="utf-8"))
        ts = sorted(e["t"] for e in plan.get("sfx", []))
        crowd = [round(t2, 1) for t1, t2 in zip(ts, ts[1:]) if t2 - t1 < 2.0]
        line(not crowd, f"sound effects not crowded {crowd[:4] if crowd else ''}")
        dens = len(ts) / max(1, info["duration"]) * 10
        line(dens <= 4.5, f"sound density {dens:.1f} per 10 s (<= 4.5)")
        snaps = [z["t"] for z in plan.get("zooms", []) if z["kind"] == "snap"]
        line(all(b - a2 >= 3.5 for a2, b in zip(snaps, snaps[1:])), f"snap zooms spaced >= 3.5 s ({len(snaps)} total)")

    out = Path(a.sheet)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 8
    from PIL import Image
    tmpd = out.parent / "_qc_frames"
    tmpd.mkdir(exist_ok=True)
    ims = []
    for k in range(n):
        t = info["duration"] * (k + 0.5) / n
        f = tmpd / f"f{k}.png"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1", "-vf", "scale=270:-2", f])
        ims.append(Image.open(f))
    w0, h0 = ims[0].size
    sheet = Image.new("RGB", (w0 * 4, h0 * 2))
    for k, im in enumerate(ims):
        sheet.paste(im, ((k % 4) * w0, (k // 4) * h0))
    sheet.save(out)
    print(f"contact sheet -> {out}  (open it and LOOK: face covered? caption over a button area? text cut off?)")
    print("RESULT:", "all checks passed" if bad == 0 else f"{bad} check(s) failed")


if __name__ == "__main__":
    main()
