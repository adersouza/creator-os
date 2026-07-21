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

The root `pipeline_contracts/__init__.py` is an import shim, not a schema mirror.
ThreadsDashboard keeps its own consumer snapshot; the cross-repo contract test
compares that snapshot with Creator OS `main`.

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
import { validateCampaignFactoryDraftPayload } from "./pipeline_contracts/typescript";

const errors = validateCampaignFactoryDraftPayload(payload);
```

TypeScript validators return an array of error strings. An empty array means the payload passed.

## Local Development

```bash
cd /Users/aderdesouza/Developer/creator-os
uv run pytest packages/pipeline_contracts/tests
THREADSDASH_ROOT=/Users/aderdesouza/Developer/ThreadsDashboard uv run pytest packages/pipeline_contracts/tests/test_threadsdash_consumer_contracts.py
pnpm check:contracts
```

## Versioning Policy

- Patch versions may tighten examples, docs, and helper functions without changing schema IDs.
- Minor versions may add optional schema fields.
- Major versions require new schema IDs or explicit migration notes.
- Publishing this package to a package registry is the next hygiene step once all repo consumers are wired.

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
