#!/usr/bin/env python3
"""Fetch everything the editor needs from GitHub (the shell here can reach GitHub and PyPI, not HuggingFace).

  python setup_assets.py                 # python deps check + CC0 sound library + fonts + VAD model
  python setup_assets.py --model small   # also download a Whisper model (tiny|base|small|medium|turbo)

Everything lands in ~/.cache/pro-editor (override with PRO_EDITOR_CACHE).
"""
import argparse, shutil, subprocess, sys, tarfile, urllib.request
from pe_common import CACHE, FONT_DIR, MODEL_DIR, SFX_DIR, run

REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
FONTS = {  # static TTFs from the google/fonts repo on GitHub (OFL licensed)
    "Anton-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Poppins-ExtraBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-ExtraBold.ttf",
    "Poppins-Black.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Black.ttf",
    "Poppins-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "Hind-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/hind/Hind-Bold.ttf",  # Devanagari + Latin
    "InstrumentSerif-Italic.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf",
    "InstrumentSerif-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf",
}
SYSTEM_INTER = ["Inter-Bold.otf", "Inter-SemiBold.otf", "Inter-Medium.otf"]  # copied from the system if present


def dl(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:  # noqa
        print(f"  could not fetch {url}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="whisper model to download: tiny|base|small|medium|turbo")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        print(f"{tool}: {'ok' if shutil.which(tool) else 'MISSING - install ffmpeg'}")
    miss = []
    for mod in ("numpy", "PIL", "sherpa_onnx"):
        try:
            __import__(mod)
        except ImportError:
            miss.append({"PIL": "pillow", "sherpa_onnx": "sherpa-onnx"}.get(mod, mod))
    if miss:
        print("installing:", miss)
        run([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", *miss])

    # CC0 sound effects + music (128 files, no attribution needed, safe for monetised channels)
    repo = CACHE / "agent-video-editor"
    if not SFX_DIR.exists():
        print("cloning CC0 sound library (kmilo93sd/agent-video-editor, MIT + CC0)...")
        run(["git", "clone", "--depth", "1", "https://github.com/kmilo93sd/agent-video-editor.git", repo])
    print("sound library:", "ok" if SFX_DIR.exists() else "MISSING")

    for name, url in FONTS.items():
        ok = dl(url, FONT_DIR / name)
        print(f"font {name}: {'ok' if ok else 'missing (captions fall back to the system font)'}")

    import os
    for n in SYSTEM_INTER:
        src = f"/usr/share/fonts/opentype/inter/{n}"
        if os.path.exists(src) and not (FONT_DIR / n).exists():
            shutil.copy(src, FONT_DIR / n)
        print(f"font {n}: {'ok' if (FONT_DIR / n).exists() else 'missing (falls back to Liberation Sans Bold, also Helvetica-like)'}")

    vad = MODEL_DIR / "silero_vad.onnx"
    print("VAD model:", "ok" if dl(f"{REL}/silero_vad.onnx", vad) else "MISSING")

    if a.model:
        d = MODEL_DIR / f"sherpa-onnx-whisper-{a.model}"
        if not d.exists():
            print(f"downloading whisper {a.model} (size varies: tiny 116MB, base 208MB, small 640MB, medium 1.9GB)...")
            tgz = MODEL_DIR / f"{a.model}.tar.bz2"
            if dl(f"{REL}/sherpa-onnx-whisper-{a.model}.tar.bz2", tgz):
                with tarfile.open(tgz) as t:
                    t.extractall(MODEL_DIR)
                tgz.unlink()
        print(f"whisper {a.model}:", "ok" if d.exists() else "MISSING")


if __name__ == "__main__":
    main()
