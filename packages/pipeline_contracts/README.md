# Pipeline Contracts

Shared JSON schemas and lightweight validators for Campaign Factory, Reference Factory, and ThreadsDashboard.

In the `creator-os` monorepo, the canonical hand-edited JSON schemas live at:

```text
packages/pipeline_contracts/pipeline_contracts/schemas
```

The generated TypeScript bundle lives at:

```text
packages/pipeline_contracts/typescript/generated-schemas.ts
```

Python imports resolve directly to this uv workspace package. The generated
`contract-manifest.json` gives every canonical schema and TypeScript source file
a versioned SHA-256 receipt. A tagged release builds the compiled
`@creator-os/pipeline-contracts` tarball. ThreadsDashboard consumes that
immutable artifact through its package lock; it does not copy this tree.

```bash
pnpm check:contracts
```

## Python

```python
from pipeline_contracts import validate_audio_intent

validate_audio_intent(payload)
```

Named validators raise `ContractValidationError` on invalid payloads and return `None` when valid.

## TypeScript

```ts
import { validateCampaignFactoryDraftPayload } from "@creator-os/pipeline-contracts";

const errors = validateCampaignFactoryDraftPayload(payload);
```

TypeScript validators return an array of error strings. An empty array means the payload passed.

## Local Development

```bash
cd /Users/aderdesouza/Developer/creator-os
uv run python -m pytest packages/pipeline_contracts/tests
pnpm check:contracts
pnpm --filter @creator-os/pipeline-contracts build
pnpm pack:contracts
```

## Versioning Policy

- Patch versions may tighten examples, docs, and helper functions without changing schema IDs.
- Minor versions may add optional schema fields.
- Major versions require new schema IDs or explicit migration notes.
- CI builds and tests the installable package on every change.
- `pipeline-contracts-vX.Y.Z` tags publish immutable tarballs and SHA-256 files.
- Consumers pin the release URL plus package-lock integrity instead of trusting
  an unversioned sibling checkout or copying source files.

### 4.2.0 exact provider authorization compatibility

Package 4.2.0 keeps existing 4.1 exact-Higgsfield authorization receipts valid
while adding source, prompt-card, command, quote, and batch-balance bindings for
new provider attempts.

### 4.1.0 durable recovery and evidence contracts

Package 4.1.0 adds the state-ownership registry and durable recovery, exact
media/audio evidence, provider authorization, and handoff contract updates. It
preserves legacy `pipeline.audio_intent.v1` embedded-audio receipts while
requiring full lineage when `EXACT_BYTE_VERIFIED` is declared.

### 4.0.0 observed-profile experiment receipts

Package 4.0.0 adds `creator_os.visual_derivative_receipt.v1`,
`creator_os.renderer_equivalence_receipt.v1`, and
`creator_os.experiment_assignment_receipt.v1`. Existing schemas are unchanged;
consumers adopt the new receipt validators only when they participate in
observed-profile experiments.

### 3.0.0 audio-policy migration

Package 3.0.0 makes `policy` required on `pipeline.audio_intent.v1` and defines
the six supported policies: `embedded_trending_required`,
`native_trending_required`, `original_embedded`, `creator_voice`,
`royalty_free`, and `silent_allowed`. Normal Reels use
`embedded_trending_required`. Completed embedded-audio intents must include
fulfillment proof bound to the final output SHA; candidate exhaustion remains
blocked as `NEEDS_EMBEDDED_AUDIO`. Consumers must not infer silence or native
audio when `policy` is absent. Existing stored payloads must be migrated or
handled as legacy input before validation against package 3.0.0.

Package 3.0.1 aligns the shared publishability helper with those policies:
verified embedded proof is publishable without a native audio ID, while missing
candidates and legacy `licensed_music` metadata remain blocked.

### Campaign draft v3 rollout

`campaign_factory.threadsdash_drafts.v2` is a frozen compatibility contract. It
must continue to validate payloads created before overlay semantic and caption
timing proof became mandatory. Do not add new required fields to v2.

`campaign_factory.threadsdash_drafts.v3` is the current producer contract. It
requires an explicit passing `overlay_semantic_qc` result and an explicit
`caption_timing_qc.applicable` decision. Timed overlays require positive timing
proof; non-timed overlays carry an honest non-applicable result with zero
segments and no duration.

Live exports negotiate before any media or product write:

1. A v3 producer sends `campaign_factory.threadsdash_handshake.v2`, preferring
   v3 and advertising v2 as its rollback contract.
2. ThreadsDashboard selects v3 and returns its complete supported set.
3. Campaign Factory rejects a missing or mismatched selection before upload.
4. An operator may explicitly select `--draft-payload-schema v2`; that uses the
   legacy v1 handshake and never silently downgrades a v3 run.

Deploy the ThreadsDashboard consumer first, then promote the Creator OS
producer default. Roll back by explicitly selecting v2; never edit the v2
schema to emulate v3.
