# Campaign Factory Audit Contract

This document defines the stable ContentForge response contract for
`auditProfile: "campaign_factory_v1"`. The profile is QA/advisory audit logic
only. It does not publish, schedule, automate posting, or attempt platform
circumvention.

## Request

Campaign Factory stages one source asset into `uploads/` and one rendered
variant into `output/final/`, then calls:

```json
{
  "source": "<staged source filename>",
  "targetFile": "<first staged variant filename>",
  "comparisonFiles": ["<second staged variant filename>"],
  "auditProfile": "campaign_factory_v1",
  "layers": ["pdq", "sscd"]
}
```

`targetFile` is required for request-scoped Campaign Factory audits. When it is
present, ContentForge audits that file plus validated `comparisonFiles` and
ignores unrelated older files in `output/final/`. Comparison entries must be
plain existing filenames, cannot equal `targetFile`, and cannot traverse
outside the run output directory.

PDQ and SSCD are mandatory for `campaign_factory_v1`, even if omitted from
`layers`. The profile fails closed when either detector or the SSCD model is
unavailable.

## Response

ContentForge preserves the existing `/api/similarity` response and extends it
with Campaign Factory fields:

```json
{
  "contractVersion": "campaign_factory_audit.v1.6",
  "auditProfile": "campaign_factory_v1",
  "targetFile": "<staged rendered filename>",
  "comparisonFiles": ["<staged sibling filename>"],
  "layers": {},
  "verdicts": {},
  "verdictCodes": {
    "forensics": "forensics_warn",
    "safeZone": "safe_zone_warn",
    "readability": "caption_readable"
  },
  "overallVerdict": "pass|warn|fail",
  "readinessSummary": {
    "summaryText": "Upload-ready candidate with review warning(s).",
    "uploadReady": true,
    "blockingReasons": [],
    "warnings": [],
    "topWarnings": [
      {
        "code": "caption_too_close_to_edge",
        "label": "Caption is near edge",
        "severity": "warn",
        "message": "Caption-like text is close to an edge or platform UI safe zone"
      }
    ],
    "operatorLabels": {
      "blocking": [],
      "needsReview": [],
      "advisory": [],
      "informational": []
    },
    "blockingCodes": [],
    "warningCodes": [],
    "recommendedAction": "approve_candidate|review|reject"
  },
  "ocr": {
    "available": true,
    "engine": "tesseract",
    "engineVersion": "tesseract 5.5.2",
    "fallbackUsed": false,
    "fallbackReason": null,
    "error": null,
    "frameSamples": 3,
    "sampleCount": 3,
    "avgConfidence": 86,
    "results": [
      {
        "file": "<target>",
        "timeSec": 0.4,
        "ocrText": "BIG HOOK WATCH NOW",
        "confidence": 86,
        "captionBoxes": []
      }
    ]
  },
  "captionBoxes": [
    {
      "file": "<target>",
      "timeSec": 0.4,
      "ocrText": "HOOK",
      "confidence": 86,
      "box": { "x": 100, "y": 200, "w": 180, "h": 40 },
      "contrast": 120,
      "fontHeightRatio": 0.063,
      "fontSizeScore": 100,
      "readabilityScore": 96,
      "safeZoneOverlap": []
    }
  ],
  "safeZoneScore": 100,
  "readabilityScore": 92,
  "hookVisibilityScore": 100,
  "safeZone": {
    "verdict": "pass|warn|fail",
    "warnings": [],
    "metrics": {
      "frameSamples": 0,
      "textBoxesDetected": 0
    }
  },
  "readability": {
    "verdict": "pass|warn|fail",
    "warnings": [],
    "metrics": {
      "frameSamples": 0,
      "textBoxesDetected": 0
    }
  },
  "coverCandidates": [
    {
      "file": "<target>",
      "timeSec": 1.2,
      "score": 82,
      "warnings": []
    }
  ],
  "hookVisibility": {
    "verdict": "pass|warn|fail",
    "warnings": [],
    "metrics": {
      "frameSamples": 0,
      "earlyTextBoxes": 0,
      "avgFrameDelta": 0
    }
  },
  "creativeQuality": {
    "available": true,
    "semanticEngine": "heuristic_v1",
    "modelBacked": false,
    "verdict": "pass|warn",
    "score": 82,
    "hookClarity": {
      "level": "strong|medium|weak",
      "score": 80,
      "text": "3 mistakes killing your reach",
      "wordCount": 5,
      "confidence": 86
    },
    "subjectVisibility": {
      "level": "strong|medium|weak",
      "score": 72,
      "method": "heuristic_frame_clarity",
      "modelBacked": false
    },
    "visualClarity": {
      "level": "strong|medium|weak",
      "score": 88
    },
    "openingStrength": {
      "level": "strong|medium|weak",
      "score": 78
    },
    "warnings": []
  },
  "multiAccountOriginalityAudit": {
    "available": true,
    "mode": "reference_match_meter",
    "blocking": false,
    "verdict": "pass",
    "referenceMatchLevel": "low|medium|high",
    "referenceMatchScore": 26,
    "variationScore": 74,
    "duplicateRisk": "low|medium|high",
    "originalityScore": 74,
    "nearestMatches": [
      {
        "file": "prior_reel.mp4",
        "score": 26,
        "referenceMatchScore": 26,
        "variationScore": 74,
        "referenceMatchLevel": "low|medium|high",
        "duplicateRisk": "low|medium|high",
        "openingSimilarity": 44,
        "frameSignatureSimilarity": 61,
        "hookSimilarity": 0.35,
        "coverSimilarity": 38,
        "audioMatch": false,
        "reasons": []
      }
    ],
    "sameOpeningRisk": "low|medium|high|unknown",
    "sameHookRisk": "low|medium|high|unknown",
    "sameAudioRisk": "low|medium|high|unknown",
    "sameCoverRisk": "low|medium|high|unknown",
    "sameTemplateRisk": "low|medium|high|unknown",
    "variationNotes": [],
    "recommendedCreativeChanges": [],
    "referenceMatchSignals": []
  },
  "timings": {
    "totalMs": 950,
    "layersMs": {
      "forensics": 120,
      "advisory": 520
    },
    "advisory": {
      "totalMs": 520,
      "frameExtractionMs": 140,
      "ocrMs": 310,
      "coverFrameExtractionMs": 70,
      "frameSamples": 3,
      "ocrFrameSamples": 3,
      "ocrTextBoxesDetected": 2,
      "ocrFallbackUsed": false,
      "ocrFallbackReason": null,
      "advisoryLatencySoftLimitMs": 5000,
      "coverCandidates": 3
    }
  },
  "filesAnalyzed": 1
}
```

## Semantics

- `overallVerdict: "fail"` means at least one blocking reason exists.
- `overallVerdict: "warn"` means the target is upload-ready but needs human
  review.
- `overallVerdict: "pass"` means no blockers and no warnings were found.
- `readinessSummary.uploadReady` is true when no blocking reasons exist.
- `recommendedAction: "reject"` is used for blockers.
- `recommendedAction: "review"` is used for upload-ready candidates with
  nonblocking warnings.
- `recommendedAction: "approve_candidate"` is used only for clean candidates.
- `contractVersion` identifies the stable Campaign Factory audit contract.
- `campaign_factory_audit.v1.6` blocks caption safe-zone, caption readability,
  hook visibility, and creative-quality warnings for Campaign Factory upload
  readiness.
- `campaign_factory_audit.v1.4` evaluates worst-case detector evidence rather
  than averages. PDQ requires every source/sibling distance to be greater than
  `40`; SSCD requires every source/sibling similarity to be below `0.50`.
- Detector unavailability produces `pdq_unavailable` or `sscd_unavailable`.
  Sibling collisions produce `pdq_sibling_collision` or
  `sscd_sibling_collision`. All four codes are blocking for this profile.
- `timings` reports audit runtime in milliseconds so slow OCR/frame sampling can
  be monitored without changing verdict semantics.
- `ocr.fallbackUsed` means ContentForge could not use the first requested OCR
  engine and used the next available local engine or heuristic path.
- `creativeQuality` uses OCR, cover-frame statistics, readability scores, and
  first-3-second motion/text signals to estimate hook clarity, subject
  visibility, visual clarity, and opening strength. Its warnings are blocking
  for `campaign_factory_v1` fan-out. `semanticEngine: "heuristic_v1"` means it
  is not model-backed semantic vision.
- Safe-zone, caption readability, hook-visibility, and creative-quality warnings
  are blocking for `campaign_factory_v1` because assets with illegible captions,
  weak openings, or unclear creative signals are not draft-ready Campaign
  Factory outputs.
- `referenceMatch` and the backward-compatible `multiAccountOriginalityAudit`
  are informational only. The layer name remains `originality` for API
  compatibility, but Campaign Factory treats it as a reference/variation meter.
  It compares the target to caller-provided references or an explicitly
  requested `output_final` scope and reports match signals without adding
  readiness warning or blocking codes.

## Blocking Codes

Campaign Factory V1 should treat these as blockers:

- `invalid_video`
- `forensics_invalid_codec`
- `forensics_invalid_container`
- `forensics_bad_dimensions`
- `forensics_audio_policy`
- `provenance_ai_flagged`
- `caption_too_close_to_edge`
- `caption_overlaps_ui_safe_zone`
- `ocr_unavailable`
- `caption_not_detected`
- `caption_low_confidence`
- `caption_low_contrast`
- `caption_text_too_small`
- `caption_text_unreadable`
- `weak_first_3_seconds`
- `hook_text_missing_first_3_seconds`
- `static_opening`
- `creative_hook_missing`
- `creative_hook_generic`
- `creative_hook_too_short`
- `creative_hook_too_long`
- `creative_hook_low_confidence`
- `creative_visual_too_dark`
- `creative_visual_soft`
- `creative_visual_unclear`
- `creative_subject_uncertain`
- `creative_subject_unclear`
- `creative_opening_static`
- `creative_opening_no_early_hook`
- non-advisory layer failures such as `pdq_failed`

## Warning Codes

Campaign Factory V1 should treat these as review-only signals. The default
ContentForge profile may still surface caption, hook, and creative-quality codes
as warnings, but Campaign Factory fan-out treats them as blockers.

- `forensics_ffmpeg_signature`
- `forensics_binary_signature`
- `forensics_bitrate_review`
- `forensics_audio_missing`
- `forensics_missing_faststart`
- `forensics_missing_creation_time`
- `forensics_default_handler_name`
- `compression_gop_review`
- `provenance_c2pa_unavailable`
- `cover_candidates_similar`

## Advisory Checks

Safe-zone, caption readability, cover candidate, and hook visibility checks use
sampled frames plus local OCR when available. The default local OCR mode is
`CONTENTFORGE_OCR_ENGINE=auto`, which tries Apple Vision on macOS, then
Tesseract, then heuristic frame analysis. You can force a path with:

```bash
CONTENTFORGE_OCR_ENGINE=apple_vision npm test
CONTENTFORGE_OCR_ENGINE=tesseract npm test
CONTENTFORGE_OCR_ENGINE=heuristic npm test
```

## Informational Reference Match Signals

Reference match signals appear under `referenceMatch.referenceMatchSignals`.
They are not readiness warning codes and should not block approval or export:

- `reference_match_close`
- `reference_match_same_opening`
- `reference_match_same_hook`
- `reference_match_same_cover`
- `reference_match_same_audio`
- `reference_match_template_reuse`

The audit reports recognized text, OCR confidence, caption boxes, contrast,
font-height ratio, safe-zone overlap, opening hook visibility, and cover
candidate diversity. Safe-zone, caption readability, hook, and creative-quality
warnings block Campaign Factory upload readiness; cover and reference-match
signals remain review-only. Tesseract OCR runs on multiple preprocessed frame
variants, including enhanced/upscaled and thresholded variants, then merges
overlapping boxes before scoring.

If OCR or optional provenance tooling is unavailable, ContentForge must return a
warning or info result instead of crashing the HTTP response.

## Multi-Account Originality

Originality checks are opt-in so ContentForge does not accidentally audit
unrelated old files in `output/final/`. Callers can pass explicit reference
filenames:

```json
{
  "source": "source.mp4",
  "targetFile": "candidate.mp4",
  "auditProfile": "campaign_factory_v1",
  "layers": ["forensics", "originality"],
  "originalityReferenceFiles": ["prior_account_reel.mp4"]
}
```

For local review batches, callers may explicitly request:

```json
{
  "originalityScope": "output_final"
}
```

The audit samples early frames, cover-like frames, local frame signatures, OCR
hook text when available, and audio fingerprints when local tooling can provide
them. Medium/high similarity produces informational match signals only.
Campaign Factory can use
those signals to choose close-format variants, lighter variations, or account
reuse spacing, but the reference match layer itself never blocks approval/export.

## Provenance Checks

Campaign Factory V1 does not require provenance credentials. ContentForge checks
C2PA, IPTC/XMP, PNG generation chunks, and regular container metadata for AI
generator strings or contradictory metadata. Absence of provenance remains normal
and nonblocking. Optional analyzer gaps remain warnings. Explicit AI/provenance
signals are surfaced through provenance layer details and may contribute blocking
codes only when the provenance layer marks the asset as flagged.

## Fixture Corpus

Committed tests use generated fixtures from:

```bash
npm run fixtures:campaign-factory
```

Local real-world samples can be copied into the ignored fixture corpus with:

```bash
npm run fixtures:campaign-factory:real -- \
  --sourceType=iphone \
  --expectedUploadReady=true \
  --expectedWarningCodes=forensics_ffmpeg_signature \
  --acceptedByPlatform=unknown \
  --operatorNotes="Accepted local review sample" \
  /path/to/iphone.mp4
```

Files under `test/fixtures/campaign-factory/real/` are intentionally ignored and
are not required for CI. Labels are tracked in
`test/fixtures/campaign-factory/manifests/real_samples.json`.

Discover local candidates and record operator feedback with:

```bash
npm run fixtures:campaign-factory:discover -- --dir="$HOME/Downloads"
npm run fixtures:campaign-factory:feedback -- \
  --file=real_sample_02.mp4 \
  --acceptedByPlatform=yes \
  --falsePositiveCodes=caption_too_close_to_edge
```

Generate an evidence report with:

```bash
npm run audit:campaign-factory:calibrate
npm run audit:campaign-factory:report
npm run audit:campaign-factory:html
npm run audit:campaign-factory:record
npm run audit:campaign-factory:ocr-benchmark
```

The calibration report includes warning/blocking code frequencies, OCR fallback
rate, slow samples, skipped local real-media files, and expected-vs-actual
mismatches. The OCR benchmark compares Tesseract with Apple Vision over a small
generated sample set so engine changes can be evaluated before threshold changes.
The `record` command writes ignored local history under
`test/fixtures/campaign-factory/reports/` and reports deltas against the previous
run.

## Compatibility

The `campaign_factory_v1` profile is stable for Campaign Factory V1.1 consumers.
ContentForge may add new warning codes, but existing fields and meanings should
remain backward-compatible. Contract changes that remove fields, rename codes,
or change warning/blocking semantics require a new `contractVersion`.
