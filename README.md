# pro-reel-editor scripts
Run order: setup_assets -> transcribe -> plan_cuts -> apply_cuts -> STORYBOARD approval -> suggest_plan -> cards -> proof (frame approval) -> captions -> mix_audio -> render -> qc
Nothing is rendered until every storyboard scene and every proof frame is approved.

## Approved style
Inter Bold white captions (sentence case, 1-3 words) with Instrument Serif Italic key word; grey pill on dark scenes; serif-italic captions/titles; light info card (preferred) and dark card.

## Colour grading
`python make_luts.py --image frame.png --sheet luts_sheet.png` previews 5 LUTs (clean, warm_film, teal_orange, moody, punchy) on one frame for approval.
Use one with `suggest_plan.py ... --lut warm_film`. Any .cube file path also works.

## Resolution
Keep 1080x1920 (reels platforms cap there). `render.py ... --uhd` exports 2160x3840 with Lanczos. This is NOT AI upscaling and adds no detail; it only gets a higher quality tier on YouTube.
No AI upscaler (Real-ESRGAN, Video2X) on real footage: it invents text and makes skin plastic. The Claude workspace also has no GPU.

## Voice
Clean with the video-cleanup skill (DeepFilterNet), then `apply_cuts.py --audio clean.wav`.
Hinglish: Whisper via sherpa-onnx; Hinglish-tuned models are on HuggingFace (blocked in the workspace). Claude corrects the transcript text before captions.

All scripts: `python <name>.py --help` (proof.py takes a spec json).
