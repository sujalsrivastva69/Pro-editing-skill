#!/usr/bin/env python3
"""cuts.json + source video (+ optional cleaned voice) -> cut.mp4, cut_voice.wav, words.edited.json.

  python apply_cuts.py work/cuts.json --words work/words.json --out-dir work [--audio work/clean.wav] [--fps 30]

The picture is re-encoded once (x264 CRF 15), the voice is written as 48 kHz PCM for the mixer.
Every piece gets a 6 ms fade at each end so a cut never clicks.
"""
import argparse, json
from pathlib import Path
from pe_common import probe, run

FADE = 0.006


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cuts")
    ap.add_argument("--words", required=True)
    ap.add_argument("--out-dir", default="work")
    ap.add_argument("--audio", help="cleaned voice wav from the video-cleanup skill (same timeline as the video)")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--vf", default="", help="extra video filter applied before cutting, e.g. scale=1080:1920")
    a = ap.parse_args()

    c = json.load(open(a.cuts, encoding="utf-8"))
    src = c["source"]
    keep = c["keep"]
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    audio_in = a.audio or src

    vparts, aparts = [], []
    for i, k in enumerate(keep):
        d = k["e"] - k["s"]
        vparts.append(f"[0:v]trim=start={k['s']}:end={k['e']},setpts=PTS-STARTPTS[v{i}]")
        aparts.append(f"[1:a]atrim=start={k['s']}:end={k['e']},asetpts=PTS-STARTPTS,aresample=48000,"
                      f"afade=t=in:st=0:d={FADE},afade=t=out:st={max(0, d - FADE):.4f}:d={FADE}[a{i}]")
    n = len(keep)
    vin = "".join(f"[v{i}]" for i in range(n))
    ain = "".join(f"[a{i}]" for i in range(n))
    vf = f",{a.vf}" if a.vf else ""
    graph = ";".join(vparts + aparts + [f"{vin}concat=n={n}:v=1:a=0{vf},fps={a.fps},format=yuv420p[vout]",
                                         f"{ain}concat=n={n}:v=0:a=1[aout]"])
    gfile = out / "cut_graph.txt"
    gfile.write_text(graph)
    cut_mp4, voice = out / "cut.mp4", out / "cut_voice.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-i", audio_in, "-filter_complex_script", gfile,
         "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "15",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", cut_mp4])
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", cut_mp4, "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", voice])

    # remap the words onto the new timeline (only words that survived)
    wj = json.load(open(a.words, encoding="utf-8"))
    removed = c["removed"]
    new = []
    for w in wj["words"]:
        mid = (w["s"] + w["e"]) / 2
        if any(r["s"] - 0.01 <= mid <= r["e"] + 0.01 for r in removed):
            continue
        for k in keep:
            if k["s"] <= mid <= k["e"]:
                s = k["out_s"] + max(0, w["s"] - k["s"])
                e = k["out_s"] + min(k["e"] - k["s"], w["e"] - k["s"])
                new.append({"w": w["w"], "s": round(s, 3), "e": round(max(e, s + 0.05), 3), "seg": w.get("seg", 0)})
                break
    dur = probe(cut_mp4)["duration"]
    json.dump({"duration": dur, "fps": a.fps, "source_size": [info["width"], info["height"]],
               "cuts": [k["out_s"] for k in keep[1:]], "words": new}, open(out / "words.edited.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"cut.mp4 {dur:.2f}s, {len(new)} words, {n - 1} cuts -> {out}")


if __name__ == "__main__":
    main()
