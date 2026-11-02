#!/usr/bin/env python3
"""Draft (or refresh) plan.json: framing, zooms and sound effects, placed from the transcript.

  python suggest_plan.py work/words.edited.json --out work/plan.json [--emphasis "never,free"] [--grade natural]
  python suggest_plan.py work/words.edited.json --update work/plan.json     # re-place sound effects after you add b-roll/cards

What it decides (every number is a starting point; read the plan and change it):
  framing  every other shot is cropped in to 110%, so a jump cut never looks like a jump cut
  push     shots longer than 6 s get a slow push-in (100% -> 107%) instead
  snap     a quick punch-in to 118% on numbers and power words, never across a cut, >= 4 s apart
  sfx      soft impact on snaps, whoosh on b-roll entries, pop on cards. At most one sound per 2.5 s,
           never the same file more than twice in a row, always ~15-17 dB under the voice.
"""
import argparse, json, re
from pe_common import norm_word

POWER = {"never", "always", "only", "free", "secret", "mistake", "biggest", "every", "everyone", "nobody", "stop",
         "best", "worst", "first", "second", "third", "million", "billion", "thousand", "zero", "double", "instantly",
         "guaranteed", "proof", "truth", "hack", "easy", "simple", "fast", "fail", "win", "money", "danger", "warning"}
NUMBERS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty", "thirty", "forty",
           "fifty", "hundred", "percent"}
IMPACT = ["impact-soft-1", "impact-soft-2", "impact-soft-3"]
POPS = ["pop-1", "pop-2"]
WHOOSH_IN = ["whoosh-soft", "whoosh-short", "slide-1", "slide-2"]
WHOOSH_OUT = ["whoosh-short", "slide-2"]


def make_sfx(plan, duration):
    ev = []  # (priority, t, kind)
    for z in plan.get("zooms", []):
        if z["kind"] == "snap":
            ev.append((2, z["t"], "impact"))
    for b in plan.get("broll", []):
        ev.append((3, b["t0"], "whoosh_in"))
        ev.append((1, b["t1"], "whoosh_out"))
    for c in plan.get("cards", []):
        ev.append((2, c["t0"], "pop"))
    for e in plan.get("sfx_manual", []):
        ev.append((4, e["t"], ("manual", e)))
    ev.sort(key=lambda e: (-e[0], e[1]))
    kept = []
    for pr, t, kind in ev:
        if all(abs(t - k[1]) >= 2.5 for k in kept):
            kept.append((pr, t, kind))
    kept.sort(key=lambda e: e[1])
    counters = {"impact": 0, "pop": 0, "whoosh_in": 0, "whoosh_out": 0}
    out, last = [], []
    for pr, t, kind in kept:
        if isinstance(kind, tuple):
            out.append(dict(kind[1]))
            last.append(kind[1]["id"])
            continue
        pool = {"impact": IMPACT, "pop": POPS, "whoosh_in": WHOOSH_IN, "whoosh_out": WHOOSH_OUT}[kind]
        sid = pool[counters[kind] % len(pool)]
        counters[kind] += 1
        if len(last) >= 2 and last[-1] == sid and last[-2] == sid:
            sid = pool[counters[kind] % len(pool)]
            counters[kind] += 1
        under = {"impact": 15, "pop": 17, "whoosh_in": 17, "whoosh_out": 21}[kind]
        out.append({"t": round(t, 2), "id": sid, "under": under})
        last.append(sid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--out", default="work/plan.json")
    ap.add_argument("--update", help="existing plan.json: keep everything, re-place sfx")
    ap.add_argument("--emphasis", default="", help="extra words that deserve a snap zoom, comma separated")
    ap.add_argument("--grade", default="natural", choices=["natural", "warm", "cool", "punchy"])
    ap.add_argument("--lut", default="", help="colour LUT on top of the grade: clean|warm_film|teal_orange|moody|punchy or a .cube path (see make_luts.py)")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--face-y", type=float, default=0.38, help="where the face sits vertically (0 top .. 1 bottom); zooms centre here")
    a = ap.parse_args()

    j = json.load(open(a.words, encoding="utf-8"))
    dur, words, cuts = j["duration"], j["words"], j.get("cuts", [])

    if a.update:
        plan = json.load(open(a.update, encoding="utf-8"))
        plan["sfx"] = make_sfx(plan, dur)
        json.dump(plan, open(a.update, "w", encoding="utf-8"), indent=1)
        print(f"sfx re-placed: {len(plan['sfx'])} sounds in {dur:.1f}s -> {a.update}")
        return

    bounds = [0.0] + cuts + [dur]
    zooms = []
    for k in range(len(bounds) - 1):
        t0, t1 = bounds[k], bounds[k + 1]
        if t1 - t0 > 6.0:
            zooms.append({"kind": "push", "t0": round(t0, 2), "t1": round(t1, 2), "to": 1.07})
        elif k % 2 == 1:
            zooms.append({"kind": "frame", "t0": round(t0, 2), "t1": round(t1, 2), "to": 1.10})

    extra = {norm_word(x) for x in a.emphasis.split(",") if x.strip()}
    cand = []
    for w in words:
        n = norm_word(w["w"])
        if n in POWER or n in NUMBERS or n in extra or re.search(r"\d", n):
            cand.append(w)
    snaps, last = [], -99
    for w in cand:
        if w["s"] - last < 4.0 or w["s"] < 1.0 or w["s"] > dur - 1.0:
            continue
        if any(abs(w["s"] - c) < 0.45 for c in cuts):
            continue
        if len(snaps) >= max(1, int(dur / 5)):
            break
        snaps.append({"kind": "snap", "t": round(w["s"], 2), "to": 1.18, "hold": 0.9, "word": w["w"]})
        last = w["s"]
    plan = {
        "size": [int(v) for v in a.size.split("x")],
        "face_y": a.face_y,
        "grade": {"natural": dict(contrast=1.05, saturation=1.06, brightness=0.01, temp=6500, sharpen=0.5, grain=4),
                  "warm": dict(contrast=1.06, saturation=1.08, brightness=0.01, temp=5800, sharpen=0.5, grain=4),
                  "cool": dict(contrast=1.07, saturation=1.02, brightness=0.0, temp=7400, sharpen=0.5, grain=4),
                  "punchy": dict(contrast=1.12, saturation=1.15, brightness=0.0, temp=6500, sharpen=0.7, grain=3)}[a.grade],
        "zooms": zooms + snaps,
        "broll": [],
        "cards": [],
        "music": None,
    }
    if a.lut:
        plan["grade"]["lut"] = a.lut
    plan["sfx"] = make_sfx(plan, dur)
    json.dump(plan, open(a.out, "w", encoding="utf-8"), indent=1)
    print(f"{len(zooms)} framing/push zooms, {len(snaps)} snap zooms, {len(plan['sfx'])} sounds -> {a.out}")
    for s in snaps:
        print(f"  snap at {s['t']:5.2f}s on '{s['word']}'")


if __name__ == "__main__":
    main()
