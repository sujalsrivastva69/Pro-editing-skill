"""Shared helpers for the real-video-pro-editor scripts."""
import json, os, re, subprocess, sys, shutil
from pathlib import Path

CACHE = Path(os.environ.get("PRO_EDITOR_CACHE", Path.home() / ".cache" / "pro-editor"))
SFX_DIR = CACHE / "agent-video-editor" / "skills" / "editing-videos" / "library"
FONT_DIR = CACHE / "fonts"
MODEL_DIR = CACHE / "models"


def run(cmd, check=True, quiet=True):
    """Run a command list; return CompletedProcess with text output."""
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.stderr.write(p.stderr[-3000:] + "\n")
        raise SystemExit(f"command failed ({p.returncode}): {' '.join(map(str, cmd))[:300]}")
    return p


def probe(path):
    """Return dict with width, height, fps, duration, has_audio for a media file."""
    p = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    j = json.loads(p.stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    out = {"duration": float(j["format"].get("duration", 0)), "has_audio": a is not None}
    if v:
        n, d = v["r_frame_rate"].split("/")
        out.update(width=int(v["width"]), height=int(v["height"]), fps=float(n) / float(d or 1))
        # phone videos are often rotated by metadata; ffmpeg autorotates, so swap if needed
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) in (90, 270):
            out["width"], out["height"] = out["height"], out["width"]
    return out


def load_words(path):
    j = json.load(open(path, encoding="utf-8"))
    return j["words"] if isinstance(j, dict) else j


def measure_lufs(path):
    """Integrated loudness (LUFS) and true peak of a media file's audio."""
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    txt = p.stderr
    i = re.findall(r"I:\s+(-?[\d.]+)\s+LUFS", txt)
    tp = re.findall(r"Peak:\s+(-?[\d.]+)\s+dBFS", txt)
    return (float(i[-1]) if i else None, float(tp[-1]) if tp else None)


def norm_word(w):
    return re.sub(r"[^\w']+", "", w.lower(), flags=re.UNICODE)


FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mmm", "aa", "aaa", "eh"}


def rms_db(x, sr=16000, frame=0.005):
    """Smoothed per-frame loudness in dB (numpy), and the frame length in seconds."""
    import numpy as np
    n = int(sr * frame)
    m = len(x) // n
    r = np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1))
    r = np.convolve(r, np.ones(3) / 3, mode="same")
    return 20 * np.log10(r + 1e-6), frame
