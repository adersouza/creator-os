# Creator OS Doctor Audit Inventory

Last updated: 2026-07-07.

This file records the audit coverage behind `pnpm doctor`. The doctor protects
live invariants and reports findings; WARN means the audit ran and found
non-blocking work, not that the audit is missing.

| Audit category | Current coverage | Status | Gap / next safe command |
| --- | --- | --- | --- |
| Architecture | `pnpm check:arch`, dependency-cruiser, import-linter, repo-local Python boundary scan | Covered | Keep in doctor. |
| Pipeline determinism | Sanitized replay fixture compares lineage, contracts, promotion decision, export manifest, and randomness explanation | Covered | Add more historical fixtures as they are sanitized. |
| Contracts | `pnpm check:contracts`, mirror sync, generated TypeScript check, mirror ownership guard, static unused-schema detection, ThreadsDashboard mirror check when present | Covered | Review static unused-schema WARNs before deleting anything. |
| Lineage | Fixture reconstructs reference -> winner DNA -> recipe -> generated media -> QC -> draft -> post -> metrics; schema ref is checked | Covered | Add DB-backed walker when stable fixture DB exists. |
| Quality gates | Fixture approved/review-ready assets assert OCR/compression/readability/safe-zone/watchability/distinctness/PDQ/sibling uniqueness and explicit failure reasons | Covered | Add DB-backed approved-asset evidence check later. |
| Promotion/state transitions | Fixture histories plus Reel orchestrator transition table and illegal-transition tests | Covered | Add new states here when orchestrator changes. |
| Learning health | Fixture verifies improved winner score, references, winner patterns, captions, hooks, audio, duplicates, rejected references; bandit tests cover `reel_outcomes` | Covered | Point at copied campaign DB after real outcomes accumulate. |
| Data provenance | Fixture verifies generated-by, prompt, reference IDs, timestamp, recipe version, model/profile, trace ID | Covered | Promote same fields into future DB-backed checks. |
| Replay | Sanitized replay fixture compares expected contracts, QC, promotion, and export manifest | Covered | Scale to 100 campaigns after sanitized history exists. |
| Duplicate intelligence | Fixture detects exact hook duplicates, repeated caption hashes, and basic semantic/pacing/storyline duplicates | Covered | Add model-backed semantic depth only after taxonomy/model choice. |
| Performance | Fixture stage timings are checked and doctor reports per-audit duration | Covered | Add tick-report trend summaries later. |
| Resource/cost | Fixture disk/API/GPU/cost fields and paid-generation cost estimates are checked | Covered | Wire real tick reports when stable. |
| Failure recovery | Mocked Higgsfield/Kling/OCR/SQLite/export/contract-validation scenarios plus orchestrator recovery tests | Covered | Replace fixture-only provider scenarios with adapter mock tests as providers change. |
| Configuration | Local orchestrator config, required enabled fields, stale/deprecated config terms | Covered | Operator must still opt into `enabled = true`. |
| Dependencies | Local package manager, lockfile, floating JS deps, Python floor | Covered | Add freshness policy only when owner defines one. |
| Security | Secret scan, tracked sensitive/runtime file check, unsafe Python shell subprocess scan | Covered | Install gitleaks/trufflehog for deeper local scans if absent. |
| Documentation | Current docs risk grep, stale pipeline terms, archive exclusion check | Covered | Keep archive stale unless linked as current guidance. |
| Technical debt | Live marker scan plus `creator_os_technical_debt_report.md` and `tests/fixtures/doctor/technical_debt_burndown.json` ownership | Covered | WARN inventory is not automatically a merge blocker. |
| Observability | Fixture verifies stage, failure reason, approver, contract/schema, model/profile, references, metrics | Covered | Back with DB walker when fixture DB exists. |
| Commercial readiness | Fixture customer journey covers onboard -> upload refs -> generate -> approve -> handoff -> analytics; checklist-backed manual actions reported | Covered with WARN findings | Close listed owner checklist items before claiming self-serve readiness. |

## Proof inputs

`pnpm doctor --td-snapshot PATH` consumes a read-only ThreadsDashboard draft
snapshot. Each row needs `draft_id`, `status`, `caption`, `media_hash`,
`lineage_hash`, `account`, and `schedule`.

`pnpm doctor --ui-proof PATH` consumes a ThreadsDashboard browser proof JSON
with route, viewport, console error count, visible state labels, and screenshot
path for `/calendar`, `/composer`, `/links`, `/analytics`, and `/reliability`.

`docs/audits/creator_os_release_hygiene_checklist.md` is the release hygiene
source for the repository-health WARN.

## Deferred hard audits

### Replay audit scale-up

Needed fixture/data:
- Sanitized campaign inputs, expected generated contracts, QC decisions, and
  export manifests for 100 historical campaigns.

Safe command shape:

```bash
pnpm doctor:replay --fixtures tests/fixtures/replay
```

Risk protected:
- Hidden state, non-deterministic promotion decisions, contract drift.

Why not automated now:
- The doctor includes a small sanitized replay fixture. Scaling to 100 requires
  owner-approved sanitized historical fixture data.

### Failure recovery audit

Needed fixture/data:
- Mock provider adapters for Higgsfield, Kling, OCR, SQLite write failure, and
  export failure.

Safe command shape:

```bash
uv run pytest tests/audits/test_failure_recovery.py
```

Risk protected:
- Partial writes, corrupt state, unsafe retries, approval-inbox loss.

Why not fully adapter-backed now:
- The doctor includes mocked scenario fixtures and existing orchestrator
  recovery tests. Provider-specific adapter mocks should be added as provider
  interfaces settle.

### Resource and commercial readiness scale-up

Needed fixture/data:
- Tick reports with timing/cost fields, sanitized onboarding scenario, sandbox
  accounts, and expected dashboard states.

Safe command shape:

```bash
pnpm doctor:readiness --fixture tests/fixtures/commercial-readiness
```

Risk protected:
- Founder-only operation, cost blowups, slow stages at scale.

Why not fully production-like now:
- The doctor includes a safe fixture journey and reports manual actions. A
  real self-serve readiness proof still needs a non-production account sandbox.
