---
name: pro-reel-editor
description: Edit Sujal's own phone-recorded talking videos into pro reels: clean voice, cuts, pro captions, zooms, SFX, visual cards. Storyboard and frame approval before render.
---

# pro-reel-editor
Use when Sujal sends a raw video of himself. Reply in simple Hinglish. Must NOT look AI-made; his face, voice and footage stay the base.

Rules: never overwrite originals (work in work/); Claude cannot hear audio (verify by re-transcription + loudness, give timestamps to check with headphones); paste-ready text in code blocks; two REQUIRED gates before render: (A) storyboard, (B) proof frames.

Pipeline (scripts in scripts/, run with --help):
1. Voice clean (video-cleanup skill audiofix.py --wav-only -o work/clean.wav)
2. transcribe.py in.mp4 --out work/words.json --model small --lang en ; Claude corrects Hinglish text
3. plan_cuts.py work/words.json --out work/cuts.json ; show cut list + transcript
4. apply_cuts.py work/cuts.json --words work/words.json --out-dir work [--audio work/clean.wav]
5. STORYBOARD GATE: numbered scenes S1..Sn with time, line spoken, visual, caption style, SFX, reason, plus a thumbnail sheet. He approves/rejects each; redo only rejected until ALL approved; save work/storyboard.md
6. suggest_plan.py work/words.edited.json --out work/plan.json ; edit to match storyboard
7. cards.py info|serif|quote ...
8. PROOF GATE: proof.py proof_spec.json ; send proof_sheet.png ; repeat until ALL approved
9. captions.py ... --style editorial|pill|serif --emph auto
10. mix_audio.py work/cut_voice.wav --plan work/plan.json --out work/master.wav --lufs -14
11. render.py work/cut.mp4 --plan work/plan.json --captions work/captions.ass --audio work/master.wav --out out/final.mp4
12. qc.py out/final.mp4 --words work/words.edited.json --plan work/plan.json --sheet out/qc_sheet.png

Look: Inter Bold white sentence-case captions (1-3 words), key word in Instrument Serif Italic, grey pill on dark scenes, light grey info cards. Never all-caps or flashing colours.
Editing: every cut has a reason; zoom never crosses a cut; punch-in 110-120%; SFX 15-17 dB under voice, max 1 per 2.5 s; master -14 LUFS, peak <= -1 dBTP; light grade and grain.
