# Creator OS Release Hygiene Checklist

Last updated: 2026-07-07.

Run this before claiming a Creator OS audit/release branch is ready:

1. `git status --short --branch`
2. `pnpm doctor`
3. `pnpm doctor --release`
4. `pnpm doctor --json`
5. `uv run pytest tests/audits/test_doctor.py`
6. `git diff --check`
7. Confirm unrelated untracked files are not staged.
8. Confirm local work branches are merged, intentionally retained, or deleted.
9. Confirm push, PR, and merge state from GitHub before saying "merged".

Default `repository-health` stays WARN-first. In `--release`, a dirty tree is a
hard failure; local non-main branches remain a review warning unless the owner
decides they block the tag.
