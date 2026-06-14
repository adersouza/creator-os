# Pipeline Contracts

Shared JSON schemas and lightweight validators for Campaign Factory, Reference Factory, and ThreadsDashboard.

In the `creator-os` monorepo, this package is the canonical shared contract
source for the content pipeline:

```text
packages/pipeline_contracts
```

Compatibility mirrors may exist for consumers that still import local snapshots:

```text
packages/pipeline_contracts/pipeline_contracts/schemas
pipeline_contracts/schemas
apps/dashboard/pipeline_contracts
python_packages/campaign_factory/schemas
```

Those mirrors are not authoritative. Keep them byte-for-byte synchronized with
`packages/pipeline_contracts` and run the root drift check before merging:

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
pnpm check:contracts
```

## Versioning Policy

- Patch versions may tighten examples, docs, and helper functions without changing schema IDs.
- Minor versions may add optional schema fields.
- Major versions require new schema IDs or explicit migration notes.
- Publishing this package to a package registry is the next hygiene step once all repo consumers are wired.
