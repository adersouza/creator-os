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
