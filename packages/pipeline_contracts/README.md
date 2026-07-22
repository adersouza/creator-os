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
