# Creator OS Tooling Hardening

Creator OS uses free, local, and GitHub-native checks before adding hosted
services. Tooling must improve PR safety without changing scheduling,
publishing, QStash, metrics sync, account health, or production inventory.

## Current Tooling Gates

- `pnpm check:contracts` keeps pipeline contract mirrors synchronized.
- `pnpm security:secrets` runs a local current-tree secret scan when `gitleaks`
  or `trufflehog` is installed.
- GitHub Actions runs CodeQL for JavaScript/TypeScript and Python.
- GitHub Actions runs TruffleHog secret scanning on pull requests.
- `pnpm test:visual` builds Dashboard Storybook, serves it locally, and runs
  Playwright visual regression checks.
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
  across pnpm, npm package-lock mirrors, uv workspaces, and GitHub Actions.

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

Do not commit `graphify-out/` unless a lightweight graph artifact is explicitly
approved.
