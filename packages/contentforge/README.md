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
