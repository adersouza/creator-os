# ContentForge

Headless quality, distinctness, and variant-pack engine for Creator OS.
ContentForge uses FFmpeg, Sharp, and Python helpers and communicates through a
bounded stdin/stdout JSON CLI. It has no browser or HTTP server.

ContentForge is detect-and-block infrastructure. PDQ/SSCD collision checks,
sibling distinctness, readability, safe-zone, watchability, and quality-floor
evidence protect the pipeline. Do not add platform-avoidance behavior.

## Commands

Requests are JSON objects read from stdin or from an optional file argument.
Results are one JSON object on stdout; errors are JSON on stderr with a nonzero
exit status.

```bash
node cli.mjs similarity < request.json
node cli.mjs variant-pack < request.json
node cli.mjs similarity request.json
```

Campaign Factory invokes these commands as a subprocess with a timeout and
fails closed on missing executables, nonzero exits, empty output, invalid JSON,
or a non-object response.

### Kling editorial timing derivatives

The `kling_editorial` variant-pack preset provides the deterministic batch
equivalent of conservative timeline edits in CapCut: trim the first four
frames, trim the final two frames, retime to `1.03x`, and retime to `0.97x`.
It produces two derivatives by default and at most four.

This preset accepts only a source explicitly verified as uncaptioned. It never
calls a generation provider, changes color or framing, spoofs metadata, or
renders captions. Every result records the exact FFmpeg arguments, source and
output SHA-256, measured media properties, and the recipe bound to that output
filename. Results remain `pending_reel_factory`; Reel Factory must make a
placement decision and render captions afterward.

Set `CONTENTFORGE_OUTPUT_DIR` to an absolute run-scoped directory when invoking
the renderer from Creator OS. This keeps resumable state and generated media
outside the source checkout.

```json
{
  "source": "uploads/kling_source.mp4",
  "variationPreset": "kling_editorial",
  "variantCount": 4,
  "captionMode": "none",
  "sourceCaptionState": "uncaptioned_verified",
  "sourceCaptionEvidence": "higgsfield_generation_manifest:<generation-id>"
}
```

## Local data

- `uploads/`: staged source media.
- `output/final/`: compatibility output for similarity checks.
- `output/runs/<runId>/`: run-scoped variant-pack output.
- `models/`: optional local detector models.

These paths are runtime data and remain gitignored.

## Requirements

- Node.js 22, 24, or 26+
- Python 3.10+
- FFmpeg and FFprobe on `PATH`
- Sharp dependencies installed through pnpm
- Optional: Chromaprint `fpcalc`, Tesseract, Apple Vision, SSCD model

The `campaign_factory_v1` profile fails closed when required perceptual
detectors are unavailable. General-profile optional layers remain advisory.

## Verification

```bash
pnpm --filter contentforge lint
pnpm --filter contentforge test
pnpm --filter contentforge build
```

Fixture and calibration commands remain in `package.json`.
