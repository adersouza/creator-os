# Guarded Creator OS Runtime Promotion

`creator-os promote` replaces the former manual runtime checkout procedure. It
is deliberately local-only and cannot authorize generation or publishing.

The ordinary operator command sequence is `status`, `create`, `review`,
`approve`, `export`, and `promote`. The historical `generate` and
`draft-export` spellings remain compatibility aliases and emit deprecation
notices. Model, queue, benchmark, Arena, Router, and analyzer diagnostics live
under `creator-os advanced ...`; the compatibility diagnostic commands remain
temporarily available so existing scripts fail loudly rather than disappearing.

## Approval evidence

The approval JSON uses `creator_os.runtime_promotion_approval.v1` and binds the
exact reviewed PR head, merged `origin/main` commit, GitHub repository and pull
request, approving review from a write-capable non-author, and concrete
successful check-run IDs, URLs, completion times, head SHAs, GitHub Actions app
identity, workflow-run IDs, workflow names, and canonical workflow paths.
Promotion re-reads the pull request, reviewer permission, review, Actions runs,
and checks through the GitHub API; self-asserted hashes, a stale or non-counting
review, a lookalike check run, an unmerged head, or a commit other than exact
remote `main` cannot authorize a runtime change.

## Dry-run

```bash
scripts/creator-os promote \
  --runtime-root /Users/aderdesouza/Developer/creator-os-runtime \
  --approved-commit <exact-sha> \
  --approval <approval.json> \
  --operator <name> \
  --dry-run
```

Dry-run resolves the exact local commit, reads remote `main` with
`git ls-remote`, verifies GitHub evidence, and checks source cleanliness plus an
exact clean detached runtime. It does not fetch or update Git refs, and creates
no backup, receipt, or checkout mutation.

## Apply and rollback

Without `--dry-run`, the command:

1. acquires a deterministic lock derived from the resolved runtime checkout, so
   alternate state roots cannot race the same runtime;
2. creates a fresh Git bundle of the pre-promotion runtime and verifies it;
3. writes and re-reads a fingerprinted backup manifest;
4. revalidates source HEAD, remote `main`, review permission, review, checks, and
   workflow runs under that lock, after the backup and immediately before the
   transaction journal;
5. writes an authenticated transaction journal before changing the checkout;
6. detaches only the configured runtime checkout at the approved commit;
7. runs `make verify` and `creator-os status --live-read-only --json` there under
   an allowlisted environment that excludes signing secrets and credentials;
8. validates, atomically writes, re-reads, and authenticates the canonical
   receipt before marking the transaction committed;
9. restores the previous commit if a post-check, receipt validation, receipt
   write, or journal-finalization step fails.

An interrupted nonterminal journal is reconciled under the same lock before a
new attempt. Recovery authenticates the journal, verifies the exact backup
manifest and bundle, and imports a missing prior commit from that bundle before
rollback. A valid, authenticated success receipt at the approved commit
completes the old transaction; otherwise the runtime is restored to the
journaled prior commit. Unknown or conflicting checkout state fails closed for
manual investigation.

The live-read-only command is validated semantically, not only by process exit
code. Policy `creator_os.runtime_live_read_only_health.v1` requires exactly nine
unique checks: `repository`, `venv-entrypoints`, `contracts`, `local-config`,
`canonical-roots`, `runtime`, `campaign-database`, `provider-readiness`, and
`threadsdashboard-handshake`. Every status must be `PASS`; a missing, extra,
duplicate, `WARN`, `NOT_RUN`, malformed, or empty result triggers rollback.

The receipt includes exact before/after commits, backup paths/fingerprints,
verification outcomes, failure/rollback state, and copyable rollback commands.
The commands verify the bundle and fetch its objects before checking out the
old commit, so recovery still works if the old object is no longer present in
the runtime object database. Paths are shell-quoted. The final command reruns
the exact nine-check live-read-only health policy. These commands are recovery
information, not permission to skip the promotion lock or receipt review; the
normal automatic rollback and authenticated interrupted-transaction recovery
remain the preferred paths.
Receipt and transaction records are HMAC-authenticated with
`CREATOR_OS_EVIDENCE_AUTH_SECRET`; a missing or short secret fails closed.
Repeated promotion to an already-receipted exact commit does not trust the old
receipt as a health cache: it runs fresh verification and writes a new uniquely
identified `already_current` receipt. Every file in the owned receipt directory
must be a filename-matched, globally unique, authenticated receipt; malformed,
renamed, symlinked, or unreadable evidence blocks the next attempt. The state
root and its `backups`, `transactions`, and `receipts` children must be real,
contained directories rather than symlink aliases.

Operational databases, model files, media libraries, ThreadsDashboard,
providers, schedules, QStash, and social publishing are outside this command's
authority.

## Repository-external approval prerequisite

Runtime promotion verifies an independent, write-capable approving review even
if GitHub branch protection does not yet require one. Repository governance
must also enforce that review before this workflow is considered complete. This
setting is external state and must not be inferred from the checked-in runbook.
Verify it live:

```bash
gh api repos/adersouza/creator-os/branches/main/protection \
  --jq '{reviews: .required_pull_request_reviews.required_approving_review_count, stale: .required_pull_request_reviews.dismiss_stale_reviews, last_push: .required_pull_request_reviews.require_last_push_approval, conversations: .required_conversation_resolution.enabled}'
```

The required result is at least one approving review, stale approvals dismissed,
last-push approval required, and conversation resolution enabled. A repository
administrator must change those settings in GitHub. Do not weaken or replace
the nine existing required checks while doing so, and re-read the complete
protection payload afterward to prove the check inventory is unchanged.
