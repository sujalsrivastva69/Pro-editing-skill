#!/usr/bin/env python3
"""Speech -> words.json with per-word times (Whisper via sherpa-onnx, runs offline once models are cached).

  python transcribe.py recording.mp4 --out work/words.json [--model small] [--lang en|hi|auto]

How word times are made
  1. silero VAD finds phrases (speech between pauses): these boundaries are measured.
  2. Whisper transcribes each phrase. Fillers (um, uh) are kept on purpose so the cutter can remove them.
  3. Words inside a phrase are spread over its measured speech span in proportion to their length
     (an estimate, usually within ~0.15 s).
  4. Each filler is then MEASURED: Whisper is run on growing prefixes and shrinking suffixes of the phrase
     to find where the filler really starts and ends, and the phrase's other words are re-spread around it.
"""
import argparse, json, re, wave
import numpy as np
from pe_common import MODEL_DIR, FILLERS, norm_word, rms_db, run

SR = 16000


def load_audio(path):
    tmp = "/tmp/_pe_16k.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), tmp])
    w = wave.open(tmp)
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def vad_segments(x, min_silence=0.22, max_speech=14.0):
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(MODEL_DIR / "silero_vad.onnx")
    cfg.silero_vad.threshold = 0.45
    cfg.silero_vad.min_silence_duration = min_silence
    cfg.silero_vad.min_speech_duration = 0.12
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
    win = cfg.silero_vad.window_size
    segs = []

    def drain():
        while not vad.empty():
            s = vad.front
            segs.append((s.start, s.start + len(s.samples)))
            vad.pop()

    for i in range(0, len(x) - win + 1, win):
        vad.accept_waveform(x[i:i + win])
        drain()
    vad.flush()
    drain()
    return segs


def make_rec(name, lang):
    import sherpa_onnx
    d = MODEL_DIR / f"sherpa-onnx-whisper-{name}"
    if not d.exists():
        raise SystemExit(f"model missing: run  python setup_assets.py --model {name}")
    return sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=str(d / f"{name}-encoder.int8.onnx"), decoder=str(d / f"{name}-decoder.int8.onnx"),
        tokens=str(d / f"{name}-tokens.txt"), language="" if lang == "auto" else lang,
        task="transcribe", num_threads=4)


def decode(rec, chunk):
    st = rec.create_stream()
    st.accept_waveform(SR, chunk)
    rec.decode_stream(st)
    return st.result


def weight(w):
    return len(re.sub(r"\W", "", w)) + 1.5 + (1.2 if re.search(r"[,.;:?!]$", w) else 0)


def spread(words, t0, t1):
    """Share [t0, t1] between words by length."""
    if not words:
        return []
    ws = [weight(w) for w in words]
    tot, t, span = sum(ws), t0, max(0.05, t1 - t0)
    out = []
    for w, wt in zip(words, ws):
        d = span * wt / tot
        out.append({"w": w, "s": round(t, 3), "e": round(t + d * 0.94, 3)})
        t += d
    return out


def group_tokens(tokens):
    """BPE tokens -> words (a token starting with a space begins a new word; punctuation sticks)."""
    words, cur = [], ""
    for tok in tokens:
        if tok.startswith(" ") and cur.strip():
            words.append(cur.strip())
            cur = tok
        else:
            cur += tok
    if cur.strip():
        words.append(cur.strip())
    merged = []
    for w in words:
        if merged and re.fullmatch(r"[^\w]+", w):
            merged[-1] += w
        else:
            merged.append(w)
    return merged


def count_fillers(text, fill):
    return sum(1 for w in text.split() if norm_word(w) in fill)


def locate_fillers(x, rec, S, E, words, fill, step=0.08):
    """Measure where each filler of one phrase really is.

    Whisper is run on growing prefixes of the phrase; a filler counts as heard when it shows up in three
    prefixes in a row (a single hit is often noise). A recogniser hears a filler slightly before it ends, so
    the end is the next quiet moment after that, and the start is the quiet gap just before the sound.
    Returns [(word_index, start, end)] for the fillers that could be measured.
    """
    idx = [i for i, w in enumerate(words) if norm_word(w) in fill]
    if not idx:
        return []
    db, fr = rms_db(x[int(S * SR): int(E * SR)])
    quiet = np.percentile(db, 90) - 20
    est = spread(words, S + 0.1, E - 0.1)
    res = []
    for k, i in enumerate(idx, start=1):
        e0 = est[i]
        t, hits, tp = max(S + 0.25, e0["s"] - 0.3), 0, None
        stop = min(E, e0["e"] + 1.0)
        while t <= stop:
            ok = count_fillers(decode(rec, x[int(S * SR): int(t * SR)]).text, fill) >= k
            hits = hits + 1 if ok else 0
            if hits == 1:
                first = t
            if hits >= 3:
                tp = first
                break
            t += step
        if tp is None:
            continue
        j0 = int((tp - S) / fr)
        end_j = None
        for j in range(j0, min(len(db) - 2, j0 + int(0.8 / fr))):
            if db[j] < quiet and db[j + 1] < quiet:
                end_j = j
                break
        if end_j is None:
            end_j = j0 + int(0.12 / fr)
        # start: walk back over the voiced stretch to the quiet gap before it
        j, start_j = end_j - int(0.04 / fr), None
        while j > max(1, end_j - int(0.8 / fr)):
            if db[j] < quiet and db[j - 1] < quiet:
                k2 = j
                while k2 < end_j and db[k2] < quiet:
                    k2 += 1
                start_j = k2
                break
            j -= 1
        if start_j is None:
            continue
        s_t, e_t = S + start_j * fr, S + end_j * fr
        if e_t - s_t < 0.1:
            continue
        res.append((i, round(s_t, 3), round(e_t, 3)))
    return res


def respread(words, t0, t1, located):
    """Re-time a phrase: measured fillers stay put, the other words share the time between them."""
    fixed = {i: (s, e) for i, s, e in located}
    out, buf, cur = [], [], t0
    for i, w in enumerate(words):
        if i in fixed:
            out += spread(buf, cur, fixed[i][0])
            out.append({"w": w, "s": fixed[i][0], "e": fixed[i][1]})
            buf, cur = [], fixed[i][1]
        else:
            buf.append(w)
    out += spread(buf, cur, t1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default="work/words.json")
    ap.add_argument("--model", default="small", help="tiny|base|small|medium|turbo (run setup_assets.py --model X first)")
    ap.add_argument("--lang", default="en", help="en, hi, ... or auto. For Hinglish try en first (Roman script); hi gives Devanagari")
    ap.add_argument("--min-silence", type=float, default=0.22)
    ap.add_argument("--scan-model", default="tiny", help="model used to measure filler positions (smaller = faster)")
    ap.add_argument("--no-refine", action="store_true", help="skip the filler measuring step")
    ap.add_argument("--max-refine", type=int, default=12, help="measure at most this many fillers")
    a = ap.parse_args()

    rec = make_rec(a.model, a.lang)
    scan = rec if a.scan_model == a.model else make_rec(a.scan_model, a.lang)
    budget = a.max_refine

    x = load_audio(a.input)
    segs = vad_segments(x, a.min_silence)
    words, seg_info = [], []
    for si, (s, e) in enumerate(segs):
        pad = int(0.1 * SR)
        r = decode(rec, x[max(0, s - pad): min(len(x), e + pad)])
        toks = group_tokens(r.tokens)
        t0, t1 = s / SR, e / SR
        ws = spread(toks, t0, t1)
        nf = sum(1 for w in toks if norm_word(w) in FILLERS)
        if nf and not a.no_refine and budget > 0:
            S, E = max(0, t0 - 0.1), min(len(x) / SR, t1 + 0.1)
            loc = locate_fillers(x, scan, S, E, toks, FILLERS)
            budget -= nf
            if loc:
                ws = respread(toks, t0, t1, loc)
        for w in ws:
            w["seg"] = si
        words += ws
        seg_info.append({"i": si, "s": round(t0, 3), "e": round(t1, 3), "text": r.text.strip()})
    json.dump({"source": a.input, "model": a.model, "lang": a.lang, "segments": seg_info, "words": words},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(seg_info)} phrases, {len(words)} words -> {a.out}")
    for sg in seg_info:
        print(f"  [{sg['s']:6.2f}-{sg['e']:6.2f}] {sg['text']}")


if __name__ == "__main__":
    main()
