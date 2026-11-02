# Pro-editing-skill

Edit your own phone-recorded talking videos into pro reels: clean voice, cuts, captions, zooms, SFX, visual cards.
Two approval gates before render: **storyboard** (scene by scene) and **proof frames**. Nothing is rendered until every item is approved.

## Setup
    cd scripts
    python setup_assets.py --model small

## Pipeline
transcribe -> plan_cuts -> apply_cuts -> storyboard (approve) -> suggest_plan -> cards -> proof (approve) -> captions -> mix_audio -> render -> qc
Run any script with `--help`. `proof.py` takes a spec JSON.

## Approved look
- Captions: Inter Bold white, sentence case, 1-3 words/page, soft shadow, no outline; key word in Instrument Serif Italic. Grey pill on dark scenes. Serif-italic captions and the light info card are favourites.
- SFX: CC0 library (kmilo93sd/agent-video-editor), 15-17 dB under voice, restrained. Master -14 LUFS.

## Notes
- Hinglish: Whisper (sherpa-onnx) is used; Hinglish-tuned models live on HuggingFace, which is blocked in the Claude workspace. Transcript is reviewed and corrected before captions.
- Voice cleaning: DeepFilterNet via the video-cleanup skill.
