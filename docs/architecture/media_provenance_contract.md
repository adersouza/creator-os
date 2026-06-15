# Generated Media Provenance Contract

This is a docs-only contract for future media lineage storage. It must not be
treated as a production database migration.

## Contract

```json
{
  "schema": "creator_os.media_provenance.v1",
  "assetId": "",
  "contentSurface": "reel|story|feed_single|feed_carousel",
  "referenceImageHash": "",
  "referenceImageSource": "",
  "soulId": "",
  "higgsfieldCapturedPrompt": "",
  "bodyEmphasis": "none|bust|bust_hips",
  "generatedStillHash": "",
  "generatedStillPath": "",
  "klingMotionPrompt": "",
  "renderedVideoHash": "",
  "renderedVideoPath": "",
  "mediaQcResult": {
    "status": "passed|failed|review_required",
    "checks": []
  },
  "handoffManifestId": "",
  "createdAt": "",
  "wouldWrite": false
}
```

## Rules

- Record hashes, prompts, model identifiers, and QC results before handoff.
- Preserve the captured Higgsfield prompt exactly; append-only body emphasis
  must be represented separately.
- Never overwrite lineage when a media file is repaired. Create a new lineage
  record or a linked revision.
- Do not use provenance alone as a publishability or schedule-safe gate.
- Do not store production credentials, signed URLs, private customer data, or
  social-platform tokens in provenance.

## Future Implementation Boundary

Implement storage only after monorepo runtime promotion is stable. The first
implementation should be append-only, read-mostly, and covered by media QC
fixtures. It must not mutate scheduling, publishing, QStash, metrics sync,
account health, or production inventory behavior.
