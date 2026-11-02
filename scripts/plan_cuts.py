#!/usr/bin/env python3
"""words.json -> cuts.json: what to keep, what to remove, and why.

  python plan_cuts.py work/words.json --out work/cuts.json [--max-gap 0.45] [--fillers "matlab,basically"]

Removes: filler sounds (um, uh...), the earlier of two near-identical phrases (a retake), and
anything said before the marker word "retake" (say "retake" out loud, then repeat the sentence).
Shortens: pauses longer than --max-gap to a natural 0.16 s (mid-sentence) or 0.28 s (after a
sentence). Pauses shorter than --max-gap are left alone, because breathing room is what keeps a
voice sounding human. Every cut point is moved to the quietest instant nearby so no word is clipped.
"""
import argparse, difflib, json
import numpy as np
from pe_common import load_words, norm_word, run
import wave

FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mmm", "aa", "aaa", "eh"}
SENT_END = (".", "?", "!", "…", "।")


def rms_track(src, frame=0.005):
    tmp = "/tmp/_pe_cut16k.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", tmp])
    w = wave.open(tmp)
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(16000 * frame)
    m = len(x) // n
    r = np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1))
    k = np.ones(3) / 3
    return np.convolve(r, k, mode="same"), frame


def snap(t, rms, frame, win=0.10):
    a, b = max(0, int((t - win) / frame)), min(len(rms) - 1, int((t + win) / frame))
    if b <= a:
        return t
    return (a + int(np.argmin(rms[a:b + 1]))) * frame + frame / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--out", default="work/cuts.json")
    ap.add_argument("--max-gap", type=float, default=0.45)
    ap.add_argument("--fillers", default="", help="extra filler words, comma separated")
    ap.add_argument("--keep-retakes", action="store_true", help="do not drop repeated phrases")
    a = ap.parse_args()

    j = json.load(open(a.words, encoding="utf-8"))
    words, segs = j["words"], j["segments"]
    fill = FILLERS | {norm_word(x) for x in a.fillers.split(",") if x.strip()}
    removed = []  # dicts: s, e, why, text
    drop_seg = set()

    # 1) retake marker: drop the phrase containing "retake" and the one before it
    for i, sg in enumerate(segs):
        if any(norm_word(w["w"]) == "retake" for w in words if w["seg"] == sg["i"]):
            drop_seg.update({sg["i"], segs[i - 1]["i"] if i > 0 else sg["i"]})
    # 2) repeated phrase: a phrase whose opening words are repeated by a following phrase is a false start
    if not a.keep_retakes:
        toks = {sg["i"]: [norm_word(w["w"]) for w in words if w["seg"] == sg["i"] and norm_word(w["w"]) not in fill and norm_word(w["w"])] for sg in segs}
        for i, sg in enumerate(segs[:-1]):
            for nxt in segs[i + 1:i + 3]:
                if nxt["s"] - sg["e"] > 3.0:
                    break
                A, B = toks[sg["i"]][:6], toks[nxt["i"]][:6]
                if len(A) >= 3 and len(B) >= 3 and difflib.SequenceMatcher(None, A, B).ratio() >= 0.7 and len(toks[nxt["i"]]) >= 0.6 * len(toks[sg["i"]]):
                    drop_seg.add(sg["i"])
                    break
    for sg in segs:
        if sg["i"] in drop_seg:
            removed.append({"s": sg["s"], "e": sg["e"], "why": "retake/false start", "text": sg["text"]})

    rms, frame = rms_track(j["source"])
    kept = [w for w in words if w["seg"] not in drop_seg]
    final = []
    for w in kept:
        if norm_word(w["w"]) in fill:
            removed.append({"s": w["s"], "e": w["e"], "why": "filler", "text": w["w"]})
        else:
            final.append(w)

    # 3) build keep intervals. Start with each kept word, merge when nothing was removed between
    #    and the gap is natural (<= max_gap); otherwise cut and leave a short natural pause.
    ivs = []
    prev = None
    for w in final:
        if prev is None:
            ivs.append([max(0.0, w["s"] - 0.10), w["e"] + 0.15])
        else:
            gap = w["s"] - prev["e"]
            removed_between = any(r["s"] >= prev["e"] - 0.05 and r["e"] <= w["s"] + 0.05 for r in removed)
            if gap <= a.max_gap and not removed_between:
                ivs[-1][1] = w["e"] + 0.15
            else:
                sent = prev["w"].endswith(SENT_END)
                tail, lead = (0.18, 0.10) if sent else (0.10, 0.06)
                if w["seg"] == prev["seg"]:
                    # inside one phrase: boundaries are estimates, trust the quietest instant nearby
                    cut_a = snap(prev["e"] + tail * 0.5, rms, frame)
                    cut_b = snap(w["s"] - lead * 0.5, rms, frame)
                else:
                    cut_a = prev["e"] + tail
                    cut_b = w["s"] - lead
                if cut_b <= cut_a:
                    ivs[-1][1] = w["e"] + 0.15
                else:
                    ivs[-1][1] = cut_a
                    ivs.append([cut_b, w["e"] + 0.15])
        prev = w
    # the first keep must not start before 0 and the last must not pass the end
    keep, out_t = [], 0.0
    for s, e in ivs:
        if e - s < 0.08:
            continue
        keep.append({"s": round(s, 3), "e": round(e, 3), "out_s": round(out_t, 3), "out_e": round(out_t + e - s, 3)})
        out_t += e - s
    src_dur = float(segs[-1]["e"]) + 0.5 if segs else 0
    saved = (segs[-1]["e"] - segs[0]["s"]) - out_t if segs else 0
    json.dump({"source": j["source"], "keep": keep, "removed": sorted(removed, key=lambda r: r["s"]),
               "max_gap": a.max_gap, "out_duration": round(out_t, 3)}, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"keep {len(keep)} pieces -> {out_t:.1f}s (about {saved:.1f}s shorter)")
    for r in sorted(removed, key=lambda r: r["s"]):
        print(f"  removed [{r['s']:6.2f}-{r['e']:6.2f}] {r['why']}: {r['text'][:70]}")


if __name__ == "__main__":
    main()
