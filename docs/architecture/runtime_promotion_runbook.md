# Guarded Creator OS Runtime Promotion

`creator-os promote` replaces the former manual runtime checkout procedure. It
is deliberately local-only and cannot authorize generation or publishing.

## Approval evidence

The approval JSON uses `creator_os.runtime_promotion_approval.v1` and binds the
exact 40-character commit, reviewer, timestamp, and passed evidence
fingerprints for contracts, architecture, artifacts, Python, JavaScript,
security, full verification, CI, and PR review. A missing, failed, duplicated,
or fingerprint-mismatched check blocks promotion.

## Dry-run

```bash
scripts/creator-os promote \
  --runtime-root /Users/aderdesouza/Developer/creator-os-runtime \
  --approved-commit <exact-sha> \
  --approval <approval.json> \
  --operator <name> \
  --dry-run
```

Dry-run fetches and resolves the exact commit and checks source/runtime
cleanliness. It creates no backup, receipt, or checkout mutation.

## Apply and rollback

Without `--dry-run`, the command:

1. locks the runtime-promotion state root;
2. creates a fresh Git bundle of the pre-promotion runtime and verifies it;
3. writes and re-reads a fingerprinted backup manifest;
4. detaches only the configured runtime checkout at the approved commit;
5. runs `make verify` and `creator-os status --live-read-only --json` there;
6. records exact command-result hashes and a durable receipt;
7. restores the previous commit if either post-check fails.

The live-read-only command is validated semantically, not only by process exit
code. Its output must be a non-empty JSON array with unique check names and
every status equal to `PASS`. `WARN`, `NOT_RUN`, malformed JSON, duplicate
checks, or an empty report triggers rollback.

The receipt includes exact before/after commits, backup paths/fingerprints,
verification outcomes, failure/rollback state, and copyable rollback commands.
Repeated promotion to an already-receipted exact commit returns the same
verified receipt.

Operational databases, model files, media libraries, ThreadsDashboard,
providers, schedules, QStash, and social publishing are outside this command's
authority.
