# Creator OS Business/Product Audits

Last updated: 2026-07-07.

`pnpm doctor --business` runs the second-layer business/product audit suite.
These WARN-first, aspirational audits no longer run in a plain `pnpm doctor`
default run (which covers only the technical/platform audits); they are pulled
in automatically by `--business`, `--release`, `--td-snapshot`, and `--ui-proof`.
Use `--td-snapshot PATH` or `CREATOR_OS_TD_SNAPSHOT` for read-only
ThreadsDashboard draft proof, and `--ui-proof PATH` or `CREATOR_OS_UI_PROOF`
for browser proof.

Use `pnpm doctor --release` for release gating. Release mode keeps ordinary
inventory as WARN, but fails missing TD/UI proof, dirty release trees, missing
commercial-readiness owners, and over-threshold scale utilization.

The business suite uses safe sanitized fixtures in
`tests/fixtures/doctor/creator_os_business_audit_fixture.json`. It does not
mutate production scheduling, publishing, account health, metrics sync, QStash,
or ThreadsDashboard runtime posting paths.

| Audit | Current proof | Remaining real-data gap |
| --- | --- | --- |
| Business logic | Fixture decisions verify creator, campaign, account, window, cooldown, priority, manual approval, and blocked-asset rules. | Replace with sanitized decision traces from copied campaign DBs. |
| Cross-system consistency | Creator OS and ThreadsDashboard fixture draft pair agrees on status, caption, media hash, lineage, account, and schedule. A provided TD snapshot turns this into PASS/FAIL proof. | Feed a read-only TD export snapshot in CI or release review. |
| Analytics integrity | Fixture covers source posts, normalized metrics, dashboard output, attribution, timezone, revenue, missing/duplicate/impossible metric checks. | Run against copied analytics DB snapshots. |
| UI consistency | Static fixture verifies asset/draft/queue/validation/analytics labels agree. A provided browser proof turns this into PASS/FAIL proof. | Feed the ThreadsDashboard Playwright proof JSON in CI or release review. |
| State machine | Business workflow fixture checks Generated -> Audited -> Validated -> Draft -> Scheduled -> Published. | Back with copied workflow DBs. |
| Data drift | Fixture compares caption length, hook, pacing, OCR density, quality score, approval rate against thresholds. | Feed rolling real metrics after enough history exists. |
| Recommendation | Fixture tracks accepted/rejected/regenerated/manual overrides and quality separation. | Feed real recommendation outcomes. |
| Regression | Fixture compares replay score, approval rate, QC pass rate, generation time, export failures, campaign success against baseline. | Store release baseline snapshots. |
| Cost | Fixture checks API, GPU, storage, OCR, embedding/analysis, totals, and cost per publishable asset. | Feed provider invoices/tick reports. |
| Human override | Fixture tracks caption/account/QC/schedule/regenerate interventions and override rate. | Feed operator decision logs. |
| Account-level | Fixture reports posting frequency, diversity, duplicate risk, approval rate, engagement trend, inactivity, content mix. | Run against copied account performance snapshots. |
| Campaign health | Fixture reports variety, hook/format diversity, duplicate load, schedule balance, winning theme reuse. | Run against copied campaign snapshots. |
| Repository health | Local git state plus fixture CI/flaky/migration metadata. | Add GitHub API CI/flaky history when auth is available. |
| Operator experience | Fixture journey covers clicks, confusion, recovery, onboarding, discoverability. | Validate with a real operator walkthrough. |
| Chaos | Fixture checks provider outage, corrupt media, invalid OCR, contract mismatch, duplicate exports, partial publish, DB restart. | Add adapter-level mocks as provider seams stabilize. |
| Scaling | Fixture computes 1,000/5,000/10,000 creator utilization from posts/day, generation seconds, approval capacity, export throughput, analytics lag, and retry rate. | Replace high-scale estimates with load-test measurements. |
| Product quality | Fixture compares blinded reviewer scores to automated QC. | Add more blind-review samples. |
| CEO dashboard | Fixture emits one-page health metrics: pipeline, contracts, generation volume, QC, timing, determinism, freshness, duplicates, overrides, publish success, cost. | Render from live approved sources once owner allows. |

WARN means the audit is runnable and found a real limitation or manual action.
It is not a fake PASS.
