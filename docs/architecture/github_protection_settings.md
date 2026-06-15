# GitHub Protection Settings Checklist

These controls are not fully expressible in repository files. Configure them in
GitHub before treating the monorepo as production runtime source.

## Branch Rulesets

- Protect `main`.
- Require pull requests before merge.
- Require the latest successful CI run on the merge commit.
- Require signed commits if it does not block existing automation.
- Require linear history or squash merges.
- Block force pushes and branch deletion.

## Required Checks

Require these checks before merge:

- `Creator OS Monorepo CI / contracts`
- `Creator OS Monorepo CI / architecture`
- `Creator OS Monorepo CI / javascript`
- `Creator OS Monorepo CI / python`
- `Creator OS Monorepo CI / hygiene`
- `Security / Dependency review`
- `Security / CodeQL (javascript-typescript)`
- `Security / CodeQL (python)`
- `Security / Secret scan`

The visual-regression, Trivy, and SBOM jobs should be required after their
first baseline has been reviewed for runtime and CI cost.

## Merge Queue

Enable merge queue for `main` once PR volume makes stale-green checks likely.
The merge queue must run the same required checks as normal pull requests.

## Protected Environments

Create protected environments for production-adjacent deploys:

- `preview`
- `staging`
- `production`

Production must require a human reviewer and environment-scoped secrets. Test
workflows should not receive production Supabase, QStash, Instagram, or publish
credentials.

## Secret Protection

Enable GitHub Secret Protection with push protection. Add custom patterns for:

- Supabase service-role keys
- QStash tokens and signing keys
- Instagram/Meta access tokens
- internal publish/proof webhook secrets
- Vercel deployment tokens

Custom patterns should start in alert mode and move to blocking after false
positives are reviewed.
