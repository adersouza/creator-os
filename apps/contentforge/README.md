# ContentForge

Local content spoofer for images and short videos.

ContentForge runs on your machine with Next.js, FFmpeg, and Python helper scripts. It uploads a source file and generates run-scoped output variants engineered to:

- **Defeat perceptual-hash duplicate detection** (PDQ/SSCD — the same class of algorithms platforms use to flag re-used content).
- **Rewrite capture metadata** (`creation_time`, `handler_name`, device-matched x264 params/filenames) so a re-used file reads as an original device capture.

Two families of checks:

- **Spoof meters** — `sourceSimilarity`, `variantToVariantSimilarity`, `variationScore` measure how well a variant evades duplicate/forensic detection.
- **Quality guards** — `safeZoneScore` is blocking for Campaign Factory caption/UI
  overlap, while `creativeQualityScore` and `readabilityScore` remain review
  signals until model-backed quality gates land. Spoofing must never visibly
  degrade the delivered video; a variant that evades detection but looks worse
  is a failure.

> **Note:** This defeats platform duplicate-detection and capture-forensics — a Terms-of-Service-evasion capability. Two standing rules: (1) the quality floor is non-negotiable — no spoof change may worsen perceptible output quality; (2) extending or strengthening the evasion capability requires explicit owner instruction.

## Variation Lab

ContentForge has a first-class Variant Pack flow for the simple operator loop:
upload one source video, choose `subtle`, `balanced`, or `strong`, generate a
pack, and review ranked outputs with variation/readiness summaries.

```http
POST /api/variant-pack
GET  /api/variant-pack/<runId>
GET  /api/variant-pack/<runId>/manifest
```

Example request:

```json
{
  "source": "uploads/source.mp4",
  "variantCount": 8,
  "variationPreset": "balanced",
  "captionMode": "supplied_hooks",
  "suppliedHooks": ["caption to test"]
}
```

The response writes `output/runs/<runId>/final/variant_pack.json` and returns
per-variant fields such as `operatorState`, `variationScore`,
`sourceSimilarity`, `variantToVariantSimilarity`, `creativeQualityScore`,
`readabilityScore`, `safeZoneScore`, `recommendedFixes`, `scoreBreakdown`, and
`recommended`. Similarity is an operator meter; only technical failures make a
variant unusable.

## Requirements

- Node.js 20.9 or newer
- npm 10 or newer
- Python 3.10 or newer
- FFmpeg and FFprobe available on `PATH`
- macOS `zip`, `strings`, and `open` commands for zip download, binary string checks, and folder opening
- Optional for audio checks: Chromaprint `fpcalc`
- SSCD model at `models/sscd_disc_mixup.torchscript.pt`, or set
  `CONTENTFORGE_SSCD_MODEL_PATH` to an external model file. The model is
  optional for general advisory checks but required for Campaign Factory
  variation apply runs.

Install common system tools on macOS:

```bash
brew install ffmpeg chromaprint
```

Python helpers may require:

```bash
./scripts/setup-python.sh
```

General-profile checks degrade gracefully when optional tools or models are
missing. `campaign_factory_v1` fails closed when PDQ or SSCD cannot run.

## Setup

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scripts

```bash
npm run dev      # Start local dev server
npm run build    # Production build using webpack
npm run start    # Start production server after build
npm run lint     # ESLint
npm test         # Node test suite
npm run test:e2e # Local API smoke test; run with the dev server already up
npm run fixtures:campaign-factory # Generate synthetic Campaign Factory audit fixtures
npm run fixtures:campaign-factory:discover # Probe a local folder for real corpus candidates
npm run fixtures:campaign-factory:feedback # Update labels/feedback for a real corpus sample
npm run audit:campaign-factory:calibrate # JSON calibration report; fails on mismatches
npm run audit:campaign-factory:report # Markdown calibration report
npm run audit:campaign-factory:html # HTML calibration report
npm run audit:campaign-factory:record # Markdown report plus ignored local drift history
npm run audit:campaign-factory:ocr-benchmark # Compare Tesseract and Apple Vision on generated samples
npm audit        # Dependency vulnerability check
```

The e2e smoke test creates a tiny local fixture, uploads it, generates one Reel variant, runs Reels analysis, detector, cover extraction, editor export, GIF export, and selected ZIP download. Set `CONTENTFORGE_KEEP_E2E=1` if you want to inspect the generated run folders afterward.

## Output Model

Each generation uses a unique `runId` and writes files under:

```text
output/runs/<runId>/final
output/runs/<runId>/edits
```

API routes use the same `runId` for preview, download, scanning, and similarity checks. This prevents two browser sessions from deleting or mixing each other's output.

## Campaign Factory Similarity Audit

Campaign Factory V1 calls ContentForge directly after staging one source file in
`uploads/` and one rendered file in `output/final/`:

```bash
curl -sS -X POST http://127.0.0.1:3000/api/similarity \
  -H 'Content-Type: application/json' \
  -d '{
    "source": "<staged source filename>",
    "targetFile": "<staged rendered filename>",
    "auditProfile": "campaign_factory_v1",
    "layers": ["forensics", "compression", "provenance"]
  }'
```

Use `targetFile` so the audit is scoped to the rendered asset instead of every
older file in `output/final/`. The `campaign_factory_v1` profile keeps
FFmpeg/Lavf/Lavc, missing `creation_time`, generic `VideoHandler`, missing
audio, and missing faststart visible as warnings when the media is otherwise
platform-compatible. Real blockers are unsupported codec/container, invalid
short-form dimensions, unreadable/corrupt media, bad audio policy, and caption
safe-zone overlap for Campaign Factory outputs.

Responses include `verdicts`, `verdictCodes`, `overallVerdict`,
`filesAnalyzed`, and:

```json
{
  "readinessSummary": {
    "summaryText": "Upload-ready candidate with review warning(s).",
    "blockingReasons": [],
    "warnings": [],
    "blockingCodes": [],
    "warningCodes": [],
    "topWarnings": [],
    "uploadReady": true,
    "recommendedAction": "review"
  }
}
```

Campaign Factory OCR defaults to `CONTENTFORGE_OCR_ENGINE=auto`, which tries
Apple Vision on macOS, then Tesseract, then heuristic frame analysis. Override
with `CONTENTFORGE_OCR_ENGINE=apple_vision|tesseract|heuristic` when comparing
engines or reproducing calibration reports.

Campaign Factory responses also include `creativeQuality`, a review-only
heuristic signal for hook clarity, subject visibility, visual clarity, and
opening strength. It is intentionally labeled `semanticEngine: "heuristic_v1"`
until model-backed semantic vision is added.

Reference match review is opt-in and informational. The API layer is still
called `originality` for backward compatibility, but Campaign Factory uses it as
a reference/variation meter, not as an export blocker. Pass explicit references
when you want ContentForge to compare a target against prior account outputs:

```json
{
  "source": "<staged source filename>",
  "targetFile": "<staged rendered filename>",
  "auditProfile": "campaign_factory_v1",
  "layers": ["forensics", "originality"],
  "originalityReferenceFiles": ["prior_reel_a.mp4", "prior_reel_b.mp4"]
}
```

The response includes `referenceMatch` and the backward-compatible
`multiAccountOriginalityAudit` object with reference match level, variation
score, nearest matches, opening/hook/audio/cover/template match signals, and
operator notes. The matcher includes a local frame-signature similarity signal
for more stable clustering than raw pixel deltas alone. These signals do not add
blocking or warning readiness codes.
Use `originalityScope: "output_final"` only for deliberate local batch review
because it compares against other files in `output/final/`.

Real calibration media belongs in ignored
`test/fixtures/campaign-factory/real/`; tracked labels live in
`test/fixtures/campaign-factory/manifests/real_samples.json`. Use:

```bash
npm run fixtures:campaign-factory:real -- \
  --sourceType=campaign_factory \
  --expectedUploadReady=true \
  --acceptedByPlatform=unknown \
  /path/to/sample.mp4
```

`npm run audit:campaign-factory:record` writes ignored local history under
`test/fixtures/campaign-factory/reports/` so repeated runs can show drift in
warning/blocking code frequencies and audit latency.

Clean ignored local media with a dry run first:

```bash
npm run cleanup:local-media -- --older-than-days=14
npm run cleanup:local-media -- --older-than-days=14 --yes
```

Use `--max-bytes=5000000000` to keep local `uploads/`, `output/final/`,
`output/runs/`, and thumbnails under a target size.
The same dry-run/delete flow is available in the Runs tab under Local storage.

Uploads default to a 500MB per-file cap and preflight `Content-Length` when
available. Override locally with `CONTENTFORGE_MAX_UPLOAD_BYTES=...`.
Forge runs use a filesystem lock under `output/.locks/` so concurrent local
server processes do not start overlapping generation jobs.

Operator feedback submitted from the pre-publish audit is stored locally as
ignored JSONL under `test/fixtures/campaign-factory/feedback/`. Use it to find
warnings that operators mark useful, false positive, too strict, or missed.

Discover local candidates without importing them:

```bash
npm run fixtures:campaign-factory:discover -- --dir="$HOME/Downloads" --maxDepth=2 --limit=50
```

Record operator feedback on a labeled real sample:

```bash
npm run fixtures:campaign-factory:feedback -- \
  --file=real_sample_02.mp4 \
  --acceptedByPlatform=yes \
  --falsePositiveCodes=caption_too_close_to_edge
```

## Security Notes

This app is intended for trusted local workstation use. Before exposing it on a network, add authentication, request rate limits, storage quotas, and a cleanup job for old `uploads/`, `public/thumbnails/`, and `output/runs/` files.

The API routes constrain user-provided paths to project-owned directories, but generated media processing can still be CPU, memory, and disk intensive.
