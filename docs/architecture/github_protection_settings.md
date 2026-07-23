# GitHub Protection Settings Checklist

These controls are not fully expressible in repository files. Configure them in
GitHub before treating the monorepo as production runtime source.

## Branch Rulesets

- Protect `main`.
- Require pull requests before merge.
- Require the latest successful CI run on the merge commit.
- Require at least one approving review from a code owner or trusted maintainer.
- Dismiss stale approvals when the head branch changes.
- Require approval of the most recent reviewable push by someone other than the
  pusher.
- Require conversation resolution before merge.
- Require signed commits if it does not block existing automation.
- Require linear history or squash merges.
- Block force pushes and branch deletion.
- Restrict who can bypass branch protections. Bypass should be empty by default
  and should never include normal automation tokens.

## Required Checks

Require these checks before merge:

- `Creator OS Monorepo CI / contracts`
- `Creator OS Monorepo CI / architecture`
- `Creator OS Monorepo CI / javascript`
- `Creator OS Monorepo CI / python`
- `Creator OS Monorepo CI / hygiene`
- `Security / CodeQL (javascript-typescript)`
- `Security / CodeQL (python)`
- `Security / Secret scan` after the current-tree hygiene step is confirmed
  blocking and the full-history incident scan is either clean or explicitly
  kept report-only during the documented secret incident.
- `Security / Trivy filesystem scan`
- `OpenSSF Scorecard / Scorecard report` after the first SARIF baseline is
  reviewed. Scorecard starts in report mode so baseline findings do not block
  unrelated migration work.

The Trivy baseline is blocking in the repository workflow and should be a
required branch check. SBOM provenance jobs can become required after their
runtime and CI cost are reviewed. Dashboard visual regression and build
provenance belong to the external ThreadsDashboard repository, not Creator OS.

## Merge Queue

Enable merge queue for `main` once PR volume makes stale-green checks likely.
The merge queue must run the same required checks as normal pull requests.

Verification:

```bash
gh api repos/adersouza/creator-os/rulesets --jq '.[] | {name,enforcement}'
gh api repos/adersouza/creator-os/branches/main/protection \
  --jq '{reviews: .required_pull_request_reviews.required_approving_review_count, stale: .required_pull_request_reviews.dismiss_stale_reviews, last_push: .required_pull_request_reviews.require_last_push_approval, conversations: .required_conversation_resolution.enabled, checks: [.required_status_checks.checks[].context]}'
```

The live payload, not this checklist, is the authority. Require `reviews >= 1`
and `stale`, `last_push`, and `conversations` all true while preserving the full
required-check inventory above. Changing these repository settings requires a
GitHub administrator; a checked-in documentation change is not proof that the
control is active.

## Protected Environments

Create protected environments for production-adjacent deploys:

- `preview`
- `staging`
- `production`

Production must require a human reviewer and environment-scoped secrets. Test
workflows should not receive production Supabase, QStash, Instagram, or publish
credentials.

Each environment should use the smallest credential set needed for that
environment. Preview and staging secrets must not be accepted as proof that
production deploy permissions are safe.

## Secret Protection

Enable GitHub Secret Protection with push protection. Add custom patterns for:

- Supabase service-role keys
- QStash tokens and signing keys
- Instagram/Meta access tokens
- internal publish/proof webhook secrets
- Vercel deployment tokens

Custom patterns should start in alert mode and move to blocking after false
positives are reviewed.

## Dependency Graph And Supply Chain Settings

Enable these repository settings before promoting the remaining report-only
security workflows:

- Dependency Graph
- Dependabot alerts
- Dependabot security updates
- Code scanning alerts
- Secret scanning
- Secret scanning push protection
- Artifact attestations

Verification:

```bash
gh api repos/adersouza/creator-os --jq '.security_and_analysis'
gh api repos/adersouza/creator-os/code-scanning/alerts --paginate --jq length
```
