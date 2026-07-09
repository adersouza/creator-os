# Creator OS Technical Debt Audit

Last updated: 2026-07-07.

`pnpm doctor` now performs the live technical debt scan. It searches current
non-archive source/docs for TODO, FIXME, deprecated, legacy, and shim markers,
then reports the count, first matches, and burn-down ownership in the
`technical-debt` audit result.

This report intentionally does not make every marker a build failure. Debt
markers fail only when they are marked as severe, for example `P0` or
`SECURITY`, or when a debt category has no owner in
`tests/fixtures/doctor/technical_debt_burndown.json`; otherwise they are
WARN-level cleanup inventory.

## Current Cleanup Buckets

| Bucket | Doctor behavior | Owner action |
| --- | --- | --- |
| Severe markers | FAIL when marker text includes `P0` or `SECURITY` | Fix before merge or explicitly reclassify. |
| Compatibility shims | WARN inventory | Remove after downstream consumers migrate. |
| Deprecated/legacy paths | WARN inventory | Keep only when protected by current tests/docs. |
| TODO/FIXME | WARN inventory | Convert to issue-backed work or delete stale comments. |

Run:

```bash
pnpm doctor
```

For machine-readable debt output:

```bash
pnpm doctor --json
```
