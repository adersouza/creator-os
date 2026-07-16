# ContentForge Export Hygiene Adjudication

Date: 2026-07-15

## Scope and safety boundary

This audit covers ContentForge JavaScript exports only. It preserves the two
headless stdin/stdout commands (`similarity` and `variant-pack`), Campaign
Factory's subprocess boundary, resumable variant-pack jobs, quality gates, and
all dynamic tool invocation. It does not change scheduling, publishing,
inventory, provider, or production state.

The baseline command was:

```bash
pnpm audit:js-dead
```

It reported 39 unused exports, 14 unlisted system binaries, and one duplicate
audio-fit export. Each export was checked against:

- repository-wide static imports and symbol references;
- JavaScript dynamic `import()` calls;
- `packages/contentforge/cli.mjs` command registration;
- stdin/stdout worker behavior and package `bin`/scripts;
- ContentForge tests and scripts;
- package-level exports;
- Python Campaign Factory subprocess/dynamic-module callers;
- repository documentation and saved-manifest compatibility.

The only production dynamic JavaScript module load is Campaign Factory's
`scoreAudioFit` import. The ContentForge CLI imports only `POST` from
`similarity.js`, `runVariantPack` from `variant-pack.js`, and path validation.
No audited removal was reachable through either mechanism.

## Baseline 39-export adjudication

`Active internal` means the implementation is still used, but its unnecessary
public `export` modifier was removed. `Compatibility` means the canonical
public surface remains elsewhere. `Deleted` means the symbol and any helpers
used exclusively by that symbol had zero callers in all checked surfaces.

| Symbol | File | Classification | Evidence and disposition |
| --- | --- | --- | --- |
| `frameHash` | `lib/detector.js` | Deleted | Definition only; active code uses `multiFrameHash`. |
| `analyzeRunSimilarity` | `lib/detector.js` | Deleted | Retired route-era run analyzer; absent from CLI, scripts, tests, and downstream callers. |
| `deleteRunFiles` | `lib/detector.js` | Deleted | Retired route-era mutation; no caller or command. |
| `LOCAL_MEDIA_TARGETS` | `lib/local-media-cleanup.js` | Active internal | Used by the explicit cleanup inspector/applicator only; no external import. Made private. |
| `convertMedia` | `lib/media-tools.js` | Deleted | No CLI command, package script, test, or downstream caller. |
| `exportGif` | `lib/media-tools.js` | Deleted | Called only the unused `convertMedia`; no registered surface. |
| `generateClips` | `lib/media-tools.js` | Deleted | No registered surface or caller. |
| `generateFrames` | `lib/media-tools.js` | Deleted | No registered surface or caller. |
| `editMedia` | `lib/media-tools.js` | Deleted | No registered surface or caller. Argument builders remain tested. |
| `REFERENCE_DIR` | `lib/paths.js` | Active internal | Used only by path containment validation. Made private. |
| `extractThumbnail` | `lib/pipeline.js` | Deleted | No pipeline call or external caller. |
| `extractImageThumbnail` | `lib/pipeline.js` | Deleted | No pipeline call or external caller. |
| `getVideoInfo` | `lib/pipeline.js` | Active internal | Used by the active video pipeline only. Made private. |
| `getImageInfo` | `lib/pipeline.js` | Active internal | Used by the active image pipeline only. Made private. |
| `PLATFORM_PRESETS` | `lib/presets.js` | Deleted | Retired GUI catalog; absent from the headless CLI and all callers. |
| `IMAGE_PRESETS` | `lib/presets.js` | Deleted | Retired GUI catalog; absent from the headless CLI and all callers. |
| `MANIPULATION_LEVELS` | `lib/presets.js` | Deleted | Retired GUI presentation data; no caller. |
| `EFFECTIVENESS` | `lib/presets.js` | Deleted | Retired GUI estimate data; no caller or persisted contract. |
| `IMAGE_EFFECTIVENESS` | `lib/presets.js` | Deleted | Retired GUI estimate data; no caller or persisted contract. |
| `HOOK_TEXTS` | `lib/presets.js` | Deleted | Retired freehand-hook list; no caller. Caption ownership remains outside this list. |
| `DAYS` | `lib/presets.js` | Deleted | Retired GUI calendar labels; no caller. |
| `coverScaleFilterForProfile` | `lib/reels-profiles.js` | Deleted | No FFmpeg or pipeline caller; active contain/scale filters remain. |
| `REELS_PROFILES` re-export | `lib/reels.js` | Compatibility | Removed duplicate re-export. Canonical export remains in `lib/reels-profiles.js`. |
| `analyzeReelsRun` | `lib/reels.js` | Deleted | Retired route-era manifest writer; active CLI uses `similarity` and `variant-pack`. |
| `saveRunCaptions` | `lib/reels.js` | Deleted | Retired route-era mutation; no caller or CLI command. |
| `extractCoverFrame` | `lib/reels.js` | Deleted | No caller except the also-unused cover-candidate helper. |
| `extractCoverCandidates` | `lib/reels.js` | Deleted | No caller, CLI command, script, or test. |
| `listRuns` | `lib/reels.js` | Deleted | Retired GUI listing surface; no caller. |
| `cleanupOldFiles` | `lib/reels.js` | Deleted | Retired cleanup surface; canonical explicit cleanup script uses `local-media-cleanup.js`. |
| `VARIANT_PRESETS` | `lib/variant-engine.js` | Active internal | Used by normalization and FFmpeg configuration. Made private. |
| `DEFAULT_QUALITY_GATE` | `lib/variant-engine.js` | Active internal | Used by normalization and evaluation. Made private. |
| `variantLevelForPreset` | `lib/variant-engine.js` | Deleted | Definition only; active callers use normalized preset objects. |
| `validateQualityGate` | `lib/variant-engine.js` | Deleted | Definition only; active boundary normalizes and evaluates the gate. |
| `scoreQuality` | `lib/variant-engine.js` | Active internal | Used by `variantScoreBundle`. Made private. |
| `scoreDifference` | `lib/variant-engine.js` | Active internal | Used by `variantScoreBundle`. Made private. |
| `recommendedAction` | `lib/variant-engine.js` | Active internal | Used by `variantScoreBundle`. Made private. |
| `runVariantPackJob` | `lib/variant-pack-jobs.js` | Active internal | Used by the resumable queue scheduler. Made private; public start/load/diagnostic APIs remain. |
| `loadVariantPack` | `lib/variant-pack.js` | Deleted | No CLI, job, script, test, or downstream caller. Manifest creation remains active. |
| `buildVariantPackReport` | `lib/variant-pack.js` | Active internal | Called by `runVariantPack`. Made private. |

## Cascading exports exposed by the first pass

After removing the route-era zero-callers, Knip exposed four exports whose only
external-looking consumers had been among those deleted paths:

| Symbol | File | Classification | Evidence and disposition |
| --- | --- | --- | --- |
| `RUNS_DIR` | `lib/paths.js` | Active internal | Used by canonical run-path functions. Made private. |
| `safeBasename` | `lib/paths.js` | Active internal | Used by canonical path validation. Made private. |
| `formatBytes` | `lib/reels.js` | Active internal | Used by active media validation. Made private. |
| `listRunFiles` | `lib/reels.js` | Deleted | Its sole consumer was the deleted route-era analyzer. |

No audited export was classified as `evidence-only`: saved manifests remain
plain data and do not dynamically call these functions. Evidence preservation
therefore does not require retaining dead executable surfaces.

## Explicitly retained findings

- `scoreAudioFit` and `buildAudioFitScore` intentionally remain a compatibility
  alias pair. Campaign Factory dynamically imports `scoreAudioFit`; existing
  ContentForge callers/tests also exercise `buildAudioFitScore`.
- Knip's 14 `unlisted binaries` are deliberate host-tool invocations (`ffmpeg`,
  `ffprobe`, `fpcalc`, `strings`, `tesseract`, `swift`, and `python3`), not npm
  package dependencies or unused exports. Their fail-closed/advisory behavior is
  covered by the existing diagnostics and tests.
- `buildConvertArgs`, `buildClipArgs`, `buildFramesArgs`, and `buildEditArgs`
  remain as tested FFmpeg argument builders. Removing unused route wrappers does
  not remove advanced FFmpeg construction used for compatibility and regression
  coverage.
- The public stdin/stdout surface remains exactly `similarity` and
  `variant-pack`. No browser, HTTP server, or publishing surface was added.

## Result

The follow-up Knip run reports zero unused exports. Remaining output is limited
to the deliberate host binaries and the documented audio-fit compatibility
alias. ContentForge's detect-and-block QC behavior and variant-pack execution
remain unchanged.
