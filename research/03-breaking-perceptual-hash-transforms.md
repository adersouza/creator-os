# Research 03 — Transform vs. Hash-Distance vs. Quality (2026)

> Owner-supplied research. The key engineering finding behind the INTELLIGENCE_AUDIT Track-S correction: **which edits actually move PDQ/SSCD, and at what quality cost.**

## The headline finding

Defeating Instagram's perceptual hashes with *imperceptible* change is **hard**. Small "natural" edits barely move PDQ while preserving high VMAF; only **geometric edits (crop/rotation)** or **heavy compression** produce large PDQ jumps — and **SSCD (the deployed descriptor) survives crop, color, text-overlay, and screenshotting by design.** So pixel-level tricks defeat the weak hash (PDQ) but not the strong deployed one (SSCD/SimSearchNet++).

## Transform effects table (illustrative; PDQ Δ is per-frame Hamming, video match allows ~≤30)

| Transform | Params | Quality (VMAF/SSIM) | PDQ Δ | SSCD | Visible? |
|-----------|--------|--------------------|-------|------|----------|
| **Re-encode** | CRF 23→35 | 98→75 / 0.99→0.85 | +0–5 → +10–20 | robust | artifacts at CRF≥30 |
| **Resolution** | 1080→720→480→240 | 95→85→70→40 | +0–5 → +10–20 → +30 | robust | blur at 480p, harsh at 240p |
| **Crop** | −5%→−10%→−20% | 0.98→0.95→0.80 SSIM | +~5 → +10 → **>30** | **trained to survive crop** | framing change by −20% |
| **Hue/Sat/Contrast** | ±10–20° / 80–120% | 99→97 / ~0.99 | **+0–2 (negligible)** | robust | hardly visible |
| **Frame drop** | 10/20/50% | 95→90→70 | **+0/frame**; match% drops only past overlap thresh | unaffected | jerk at 10–20% |
| **Frame shuffle** | reorder segments | ~100 (pixels same) | **+0 (vPDQ unordered)** | unaffected | disorientation, no hash effect |
| **Speed change** | 0.9×/1.1× | ~100 | **+0 (frames identical)** | **+0** | feel only |
| **Audio swap** | mute/replace | — | **+0** | +0 | none (separate audio layer) |

## The four facts that matter for our code

1. **`setpts` speed change = 0 hash effect.** Per-frame pixels are unchanged. (Our editorial engine's tempo deltas do nothing for collision.)
2. **`eq` color/contrast/saturation ≈ 0 PDQ effect** (PDQ is grayscale-DCT) and SSCD is color-robust. (Our saturation deltas do nothing.)
3. **Crop is the one cheap PDQ-breaker** (~5 bits/5%, breaks ~20%) — **but useless against SSCD**, which is the deployed detector.
4. **Frame drop/reorder + audio swap = ~0 visual-hash effect.**

→ **To be SSCD-distinct you need genuinely different content** (different footage/framing/subject), not parametric nudges. Rule of thumb from the research: any transform pushing PSNR <~30dB / VMAF <~80 accumulates ~20–30 PDQ bits (breaks PDQ) — but that's a *visible* quality hit, and still may not beat SSCD.

## FFmpeg reference (for measurement harness, not for evasion)
```
re-encode:  ffmpeg -i in.mp4 -c:v libx264 -crf 30 -c:a copy out.mp4
downscale:  ffmpeg -i in.mp4 -vf scale=1280:720 -crf 23 out.mp4
crop 10%:   ffmpeg -i in.mp4 -vf "crop=iw*0.9:ih*0.9" out.mp4
speed 0.9:  ffmpeg -i in.mp4 -filter:v "setpts=0.9*PTS" out.mp4
color:      ffmpeg -i in.mp4 -vf "hue=h=15:s=1.2" out.mp4
drop frames:ffmpeg -i in.mp4 -vf "select=not(mod(n\,2))" -vsync vfr out.mp4
```

## Implication for Creator OS (legit, detection-first)
Don't try to out-edit SSCD. Instead: (1) **measure** sibling collisions with real PDQ/SSCD/vPDQ + audio and **block** fan-out on match; (2) achieve distinctness through **different generated content per account** (Workstream E: different reference image / Soul-2 still) + different captions + different audio — the only thing that legitimately clears SSCD and also satisfies Meta's "material edit" policy. Quality floor stays: any quality-destroying transform (heavy crop/CRF) is rejected by the watchability gate anyway.
