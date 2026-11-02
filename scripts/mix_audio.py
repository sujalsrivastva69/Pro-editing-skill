#!/usr/bin/env python3
"""cut_voice.wav + plan.json -> master.wav (voice + sound effects + optional ducked music, -14 LUFS).

  python mix_audio.py work/cut_voice.wav --plan work/plan.json --out work/master.wav

Sound-effect level is computed, not guessed: gain = 10^((voice_LUFS - under - sfx_LUFS)/20), capped at 1,
where `under` is how many dB below the voice the effect should sit (15-17 dB for hits and pops, ~21 for tails).
The library's catalog.json has each file's measured loudness.
Placement: the loud transient lands ~2 frames BEFORE the visual change; risers end exactly on it.
Music (optional) sits ~22 dB under the voice and ducks a further 10 dB while the voice speaks.
"""
import argparse, json, subprocess
from pathlib import Path
import numpy as np
from pe_common import SFX_DIR, measure_lufs, run

SR = 48000


def load(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("voice")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="work/master.wav")
    ap.add_argument("--lufs", type=float, default=-14.0)
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    voice = load(a.voice)
    n = len(voice)
    v_lufs, _ = measure_lufs(a.voice)
    cat = {s["id"]: s for s in json.load(open(SFX_DIR / "catalog.json"))["sounds"]}
    mix = voice.copy()
    placed = []
    for e in sorted(plan.get("sfx", []), key=lambda e: e["t"]):
        meta = cat.get(e["id"])
        if not meta:
            print(f"  skip unknown sound {e['id']}")
            continue
        s = load(SFX_DIR / meta["file"])
        if len(s) == 0:
            continue
        under = e.get("under", 15)
        gain = min(1.0, 10 ** ((v_lufs - under - meta["lufs"]) / 20))
        peak_i = int(np.argmax(np.abs(s)))
        if any(k in e["id"] for k in ("riser", "swell", "reverse")):
            start = int(e["t"] * SR) - len(s)  # builds up and ends on the change
        else:
            start = int((e["t"] - 0.07) * SR) - peak_i  # transient ~2 frames before the change
        a0, a1 = max(0, start), min(n, start + len(s))
        if a1 <= a0:
            continue
        mix[a0:a1] += s[a0 - start:a1 - start] * gain
        placed.append((e["t"], e["id"], round(20 * np.log10(gain), 1)))

    mus = plan.get("music")
    if mus:
        m = load(SFX_DIR / "music" / (mus["id"] + ".mp3")) if not str(mus["id"]).endswith(".mp3") else load(mus["id"])
        if len(m):
            reps = int(np.ceil(n / len(m)))
            m = np.tile(m, reps)[:n]
            m_lufs = mus.get("lufs", -16)
            base = 10 ** ((v_lufs - mus.get("under", 22) - m_lufs) / 20)
            # ducking envelope from the voice: 1 while speaking, smoothed (attack ~40 ms, release ~450 ms)
            fr = int(0.02 * SR)
            rms = np.sqrt(np.convolve(voice ** 2, np.ones(fr) / fr, mode="same"))
            db = 20 * np.log10(rms + 1e-7)
            speaking = (db > (v_lufs - 24)).astype(np.float32)
            env = np.zeros_like(speaking)
            a_up, a_dn = 1 - np.exp(-1 / (0.04 * SR)), 1 - np.exp(-1 / (0.45 * SR))
            cur = 0.0
            for i in range(0, n, 48):  # 1 ms control rate
                tgt = speaking[i]
                cur += (a_up if tgt > cur else a_dn) * (tgt - cur) * 48 / 48
                env[i:i + 48] = cur
            duck = 10 ** (-mus.get("duck_db", 10) / 20)
            fade = np.minimum(1, np.minimum(np.arange(n), np.arange(n)[::-1]) / (0.8 * SR))
            mix += m * base * (1 - env * (1 - duck)) * fade

    stereo = np.stack([mix, mix], axis=1)
    pk = float(np.max(np.abs(stereo)))
    if pk > 0.98:
        stereo *= 0.98 / pk
    tmp = Path(a.out).with_suffix(".premaster.wav")
    import wave
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())
    # two-pass loudnorm to -14 LUFS / -1 dBTP
    p = run(["ffmpeg", "-hide_banner", "-i", tmp, "-af", f"loudnorm=I={a.lufs}:TP=-1:LRA=11:print_format=json", "-f", "null", "-"], check=False)
    j = json.loads(p.stderr[p.stderr.rindex("{"):])
    af = (f"loudnorm=I={a.lufs}:TP=-1:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-af", af, "-ar", str(SR), "-c:a", "pcm_s16le", a.out])
    tmp.unlink()
    i2, tp2 = measure_lufs(a.out)
    print(f"voice {v_lufs:.1f} LUFS | {len(placed)} sounds | master {i2} LUFS, true peak {tp2} dBFS -> {a.out}")
    for t, i, g in placed:
        print(f"  {t:6.2f}s {i:<22} {g:+.1f} dB")


if __name__ == "__main__":
    main()
