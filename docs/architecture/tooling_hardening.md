# Creator OS Tooling Hardening

Creator OS uses free, local, and GitHub-native checks before adding hosted
services. Tooling must improve PR safety without changing scheduling,
publishing, QStash, metrics sync, account health, or production inventory.

## Current Tooling Gates

- `pnpm check:contracts` keeps pipeline contract compatibility copies
  synchronized.
- `pnpm security:secrets` runs a local current-tree secret scan when `gitleaks`
  or `trufflehog` is installed.
- GitHub Actions runs CodeQL for JavaScript/TypeScript and Python.
- GitHub Actions runs current-tree secret hygiene as a blocking check.
- GitHub Actions runs TruffleHog with verified-secret gating. The action
  supplies its own fail flag; workflow arguments keep only policy filters.
- GitHub Dependency Review is not an active gate because this private
  repository does not have the required Dependency Graph/GHAS support enabled.
- GitHub Actions runs Trivy filesystem scans, uploads SARIF findings, and gates
  HIGH/CRITICAL findings with explicit ignores required for accepted risk.
- GitHub Actions generates SBOM artifacts for npm/pnpm and Python dependency
  snapshots.
- GitHub Actions creates artifact attestations for SBOM artifacts. Dashboard
  build provenance belongs upstream in ThreadsDashboard.
- OpenSSF Scorecard runs in report mode. Pull requests upload the SARIF as a
  normal artifact; push/scheduled runs upload SARIF to code scanning after the
  first baseline exists. It is intentionally non-blocking until the baseline is
  reviewed.
- `pnpm check:arch` runs TypeScript and Python architecture-boundary checks.
- Dashboard Storybook and visual regression checks belong upstream in
  ThreadsDashboard; Creator OS no longer carries a dashboard mirror.
- `pnpm graphify:update` refreshes the local architecture graph. The
  `graphify-out/` directory remains a local artifact unless explicitly
  approved for commit.
- `pnpm check:artifacts` fails if runtime outputs, model weights, generated
  media, local databases, or `graphify-out/` are tracked by git.

## Dependency Update Policy

Dependabot remains the default dependency updater for now:

- npm/pnpm and GitHub Actions updates run weekly.
- minor and patch npm updates are grouped to reduce PR noise.
- Renovate is deferred until a clean trial branch proves that its grouping works
  across pnpm, uv workspaces, and GitHub Actions.
- A Renovate trial config exists at `.github/renovate.json`. Automerge is
  disabled. Enable Renovate only after reviewing its first dependency
  dashboard and PR grouping behavior.

Dependency PRs should be merged only after CI is green. If a dependency update
changes test runtime behavior, fix the compatibility issue directly instead of
bypassing tests.

## Secret Scanning Policy

Local secret scanning checks the current tree, not the full imported history.
The monorepo import already contains historical placeholders and test fixtures
that should not block adoption of the scanner. Historical cleanup can be handled
as a separate rotation/history-rewrite project if needed.

## Visual Regression Policy

Dashboard visual checks are Playwright-first:

- Storybook owns isolated component rendering.
- Playwright owns snapshot comparison.
- Chromatic is deferred because it requires hosted project/token setup.

When adding visual snapshots, keep them limited to reusable UI components and
do not commit creator media, generated reels, generated stills, uploads, local
campaign output, or model artifacts.

## Sentry And Observability Policy

Sentry is the current production error-reporting layer. Before adding
OpenTelemetry, verify:

- Dashboard production builds define a stable release identifier.
- source-map upload requirements are documented in deployment secrets.
- serverless Sentry setup remains lightweight and does not add unnecessary HTTP
  instrumentation overhead.

OpenTelemetry is deferred until monorepo runtime promotion is complete.
Use `docs/architecture/sentry_verification.md` as the promotion checklist.

## Supply-Chain Policy

Security workflows use audit/report mode before hard blocking new checks:

- StepSecurity Harden-Runner runs in `egress-policy: audit` on security and
  architecture jobs.
- Trivy uploads SARIF but does not currently fail PRs.
- Dependency Review is report-only until GitHub Dependency Graph is enabled;
  then it should block direct high/critical vulnerable dependency changes and
  denied licenses.
- SBOM artifacts are generated for review; they are not committed.
- Artifact attestations are generated for SBOMs and Dashboard build outputs;
  they are provenance evidence, not deployment approval.
- OpenSSF Scorecard findings are kept as PR artifacts and uploaded to code
  scanning on non-PR runs. Expected follow-up work includes reviewing pinned
  action versions, workflow token permissions, branch protections, and dangerous
  workflow patterns before making Scorecard required.

Move Harden-Runner or Trivy into blocking mode only after the baseline findings
and outbound hosts are reviewed.

## Architecture Drift Policy

Architecture checks are intentionally narrow:

- dependency-cruiser guards TypeScript app/runtime boundaries.
- import-linter guards Python package ownership boundaries.
- Graphify remains the exploratory architecture map.

Do not broaden these checks until the first narrow contracts are stable.

## Graphify Operating Rule

For architecture questions, use Graphify before broad source browsing when
`graphify-out/graph.json` exists:

```bash
graphify query "What owns schedule-safe inventory?"
graphify path "CampaignFactory" "ThreadsDashboard"
graphify explain "Campaign Factory"
```

After code changes, refresh the graph locally:

```bash
pnpm graphify:update
```

When no semantic Graphify backend is available, refresh the code architecture
graph only:

```bash
pnpm graphify:update -- --code-only
```

Do not commit `graphify-out/` unless a lightweight graph artifact is explicitly
approved.
