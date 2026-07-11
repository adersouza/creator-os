# Creator OS Release Hygiene Checklist

Last updated: 2026-07-07.

Run this before claiming a Creator OS audit/release branch is ready:

1. `git status --short --branch`
2. `pnpm check:arch` and `pnpm check:contracts` (first-class architecture and
   contract gates — doctor no longer wraps these; CI runs them, so run them here
   too before release)
3. `pnpm doctor` (technical audits only in a default run)
4. `pnpm doctor --release` (also runs the second-layer business/release gates)
5. `pnpm doctor --json`
6. `uv run pytest tests/audits/test_doctor.py`
7. `git diff --check`
8. Confirm unrelated untracked files are not staged.
9. Confirm local work branches are merged, intentionally retained, or deleted.
10. Confirm push, PR, and merge state from GitHub before saying "merged".

Default `repository-health` stays WARN-first. In `--release`, a dirty tree is a
hard failure; local non-main branches remain a review warning unless the owner
decides they block the tag.
