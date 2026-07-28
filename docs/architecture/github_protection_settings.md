# GitHub Protection Settings Checklist

These controls are not fully expressible in repository files. Configure them in
GitHub before treating the monorepo as production runtime source.

## Branch Rulesets

- Protect `main`.
- Require pull requests before merge.
- Require the latest successful CI run on the merge commit.
- For this single-owner repository, require zero approving reviews. Do not
  manufacture a second-person approval or block the owner on an unavailable
  reviewer.
- Dismiss stale approvals when the head branch changes; this is harmless when
  the required count is zero.
- Do not require approval of the most recent push by someone other than the
  pusher.
- Require conversation resolution before merge.
- Require signed commits if it does not block existing automation.
- Require linear history or squash merges.
- Block force pushes and branch deletion.
- Restrict who can bypass branch protections. Bypass should be empty by default
  and should never include normal automation tokens.

## Required Checks

The intentionally consolidated permanent PR branch-protection contexts are:

- `affected`
- `hygiene`
- `Secret scan`

`affected` expands to every genuinely impacted package/test tier. `hygiene`
owns the repository-wide static and artifact boundary. `Secret scan` remains
the protected security context. Do not restore the older collection of
package-level workflow names as permanent required contexts merely so promotion
can inspect release evidence.

The exact merged `main` SHA must separately receive complete, successful
promotion-time evidence from:

- `release`;
- `Secret scan`;
- `CodeQL (javascript-typescript)`;
- `CodeQL (python)`;
- `Trivy filesystem scan`.

Those workflow/check identities are verified live by the promotion validator
and must belong to the exact target SHA and trusted repository workflows.
Missing, pending, failed, cancelled, skipped when required, stale, substituted,
or wrong-SHA evidence blocks promotion.

Scorecard and SBOM remain repository supply-chain evidence, but they are not
permanent protected PR contexts or substitutes for the exact-SHA release and
security set. Dashboard visual regression and build provenance belong to the
external ThreadsDashboard repository.

## Merge Queue

Enable merge queue for `main` once PR volume makes stale-green checks likely.
The merge queue must run the same required checks as normal pull requests.

Verification:

```bash
gh api repos/adersouza/creator-os/rulesets --jq '.[] | {name,enforcement}'
gh api repos/adersouza/creator-os/branches/main/protection \
  --jq '{strict: .required_status_checks.strict, reviews: .required_pull_request_reviews.required_approving_review_count, stale: .required_pull_request_reviews.dismiss_stale_reviews, last_push: .required_pull_request_reviews.require_last_push_approval, conversations: .required_conversation_resolution.enabled, admins: .enforce_admins.enabled, checks: [.required_status_checks.checks[].context]}'
```

The live payload, not this checklist, is the authority. For the current
single-owner policy require `reviews == 0`, `last_push == false`,
`conversations == true`, strict status checks, admin enforcement, and exactly
the three protected contexts `affected`, `hygiene`, and `Secret scan`.
Changing these repository settings requires a GitHub administrator; a
checked-in documentation change is not proof that the control is active.

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
