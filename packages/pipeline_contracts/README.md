# Pipeline Contracts

Shared JSON schemas and lightweight validators for Campaign Factory, Reference Factory, and ThreadsDashboard.

This package is the canonical shared contract source for the content pipeline.
The GitHub remote is:

```text
https://github.com/adersouza/pipeline_contracts
```

Consumers can import it from the local sibling checkout during development.
Repositories that vendor a snapshot, such as ThreadsDashboard, should keep that
snapshot synchronized with this repo and enforce drift checks in CI.

## Python

```python
from pipeline_contracts import validate_audio_intent

validate_audio_intent(payload)
```

Named validators raise `ContractValidationError` on invalid payloads and return `None` when valid.

## TypeScript

```ts
import { validateCampaignFactoryDraftPayload } from "../pipeline_contracts/typescript";

const errors = validateCampaignFactoryDraftPayload(payload);
```

TypeScript validators return an array of error strings. An empty array means the payload passed.

## Local Development

```bash
cd /Users/adercialonedesouza/Projects/pipeline_contracts
/Users/adercialonedesouza/Projects/campaign_factory/.venv/bin/python -m pytest -q
```

## Versioning Policy

- Patch versions may tighten examples, docs, and helper functions without changing schema IDs.
- Minor versions may add optional schema fields.
- Major versions require new schema IDs or explicit migration notes.
- Publishing this package to a package registry is the next hygiene step once all repo consumers are wired.
