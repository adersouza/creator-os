# Creator OS Release Hygiene Checklist

Last updated: 2026-07-07.

Run this before claiming a Creator OS audit/release branch is ready:

1. `git status --short --branch`
2. `pnpm doctor`
3. `pnpm doctor --json`
4. `uv run pytest tests/audits/test_doctor.py`
5. `git diff --check`
6. Confirm unrelated untracked files are not staged.
7. Confirm local work branches are merged, intentionally retained, or deleted.
8. Confirm push, PR, and merge state from GitHub before saying "merged".

`repository-health` stays WARN-first. A dirty tree or local non-main branch is
not a runtime failure, but it blocks clean release confidence until reviewed.
