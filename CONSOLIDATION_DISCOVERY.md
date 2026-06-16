# Supervised Consolidation Discovery

Scope: Step 1 discovery and Step 2 creator-os runnable only. No runners were repointed, no repos were archived, no deploy settings were changed, and no `apps/*` or `python_packages/*` mirror files were hand-edited.

## Discovery Commands

Commands run from `/Users/aderdesouza/Developer` unless noted:

- `crontab -l`
- `rg -n "/Users/aderdesouza/Developer/(reel_factory|campaign_factory|contentforge|reference_factory)|reel_factory|campaign_factory|contentforge|reference_factory" ~/Library/LaunchAgents /Library/LaunchAgents /Library/LaunchDaemons`
- `find /Users/aderdesouza/Developer/{reel_factory,campaign_factory,contentforge,reference_factory}/.github/workflows -maxdepth 1 -type f -print`
- `find /Users/aderdesouza/Developer/{reel_factory,campaign_factory,contentforge,reference_factory} -maxdepth 3 \( -name README.md -o -name RUNBOOK.md -o -name REPO_MAP.md -o -name Makefile -o -name '*.sh' \) -print`
- `rg -n "cd |/Users/aderdesouza/Developer/(reel_factory|campaign_factory|contentforge|reference_factory)|npm run dev|npx next dev|pytest|uv run|python3 -m|reference_factory|campaign_factory|contentforge|reel_factory" <repo docs and shell scripts>`
- `sed -n '1,260p' /Users/aderdesouza/Developer/campaign_factory/campaign_factory/control.py`

## Runner Inventory

| Tool | Runner or surface | Current standalone path or command | Frequency or trigger | creator-os equivalent | Status |
| --- | --- | --- | --- | --- | --- |
| All four | User crontab | `crontab -l` returned `crontab: no crontab for aderdesouza` | None found | None | No repoint needed |
| All four | LaunchAgents and LaunchDaemons | No matches for `/Users/aderdesouza/Developer/{reel_factory,campaign_factory,contentforge,reference_factory}` under `~/Library/LaunchAgents`, `/Library/LaunchAgents`, or `/Library/LaunchDaemons` | None found | None | No repoint needed |
| ContentForge | `/Users/aderdesouza/Developer/contentforge/start.sh` | `cd /Users/aderdesouza/Developer/contentforge && exec npx next dev -p 3002 -H 0.0.0.0` | Local dev runner candidate when invoked manually or by local tooling | `/Users/aderdesouza/Developer/creator-os/scripts/run/contentforge dev -- -p 3002 -H 0.0.0.0` | OWNER DECISION - do not repoint |
| reel_factory | Split CI: `.github/workflows/ci.yml` | `pip install -e '.[dev]'`, `python -m ruff check --select E9,F63,F7,F82 .`, `python -m compileall *.py tests`, `python -m pytest -q tests/` | GitHub Actions on push and pull request to split repo | `uv run pytest python_packages/reel_factory/tests` plus root compile/lint gates in creator-os CI | Later Steps 3-5 decision; no repoint this run |
| campaign_factory | Split CI: `.github/workflows/ci.yml` | Checks out `pipeline_contracts`, installs split package, runs ruff, compileall, and `python -m pytest -q tests/` | GitHub Actions on push and pull request to split repo | `uv run pytest python_packages/campaign_factory/tests` plus root compile/lint gates in creator-os CI | Later Steps 3-5 decision; no repoint this run |
| contentforge | Split CI: `.github/workflows/ci.yml` | `npm ci`, `npm run lint`, `npm test`, `npm run build`, `npm audit --audit-level=moderate` | GitHub Actions on push and pull request to split repo | `pnpm --filter contentforge test`; build/lint/audit promotion remains a later runner decision | Later Steps 3-5 decision; no repoint this run |
| reference_factory | Split CI: `.github/workflows/ci.yml` | Checks out `pipeline_contracts`, installs split package with test extras, runs ruff, compileall, and `python -m pytest -q` | GitHub Actions on push and pull request to split repo | `uv run pytest python_packages/reference_factory/tests` plus root compile/lint gates in creator-os CI | Later Steps 3-5 decision; no repoint this run |
| campaign_factory | Operator control command generator: `campaign_factory/control.py` | Emits `cd {settings.contentforge_root} && npm run dev -- -p 3100` | Operator action surfaced by `campaign-factory doctor` | `scripts/run/contentforge dev -- -p 3100` | OWNER DECISION - do not repoint |
| campaign_factory | Operator control command generator: `campaign_factory/control.py` | Emits `cd {settings.root} && python3 -m campaign_factory.cli serve --host 127.0.0.1 --port 8877` | Operator action surfaced by `campaign-factory doctor` | `scripts/run/campaign-factory serve --host 127.0.0.1 --port 8877` | OWNER DECISION - do not repoint |
| campaign_factory | Operator control command generator: `campaign_factory/control.py` | Emits `cd {settings.reference_factory_root} && python3 -m reference_factory.cli export-patterns --limit 300 --for-campaign-factory` | Operator action surfaced by `campaign-factory doctor` | `scripts/run/reference-factory export-patterns --limit 300 --for-campaign-factory` | OWNER DECISION - do not repoint |
| campaign_factory | Operator control command generator: `campaign_factory/control.py` | Emits `cd {settings.root} && python3 -m campaign_factory.cli make-batch ... --contentforge-base-url http://127.0.0.1:3100 --dry-run-export --user-id <user_id>` | Operator action surfaced by `campaign-factory doctor`; batch generation adjacent | `scripts/run/campaign-factory make-batch ... --contentforge-base-url http://127.0.0.1:3100 --dry-run-export --user-id <user_id>` | OWNER DECISION - do not repoint |
| creator-os docs | `/Users/aderdesouza/Developer/creator-os/README.md` | Human-run examples: `cd reference_factory`, `cd reel_factory`, `cd campaign_factory`, `cd contentforge` | Documentation only | Use `scripts/run/reference-factory`, `scripts/run/reel-factory`, `scripts/run/campaign-factory`, and `scripts/run/contentforge` | Documented here only; no doc rewrite outside this discovery file |
| campaign_factory docs | `/Users/aderdesouza/Developer/campaign_factory/RUNBOOK.md` | Human-run examples under `$CREATOR_OS_ROOT/contentforge`, `$CREATOR_OS_ROOT/campaign_factory`, `$CREATOR_OS_ROOT/reel_factory`, and `$CREATOR_OS_ROOT/reference_factory` | Documentation/runbook | Same `scripts/run/*` wrappers | Later docs correction; no repoint this run |
| reference_factory docs | `/Users/aderdesouza/Developer/reference_factory/README.md` and `RUNBOOK.md` | Human-run examples under `$CREATOR_OS_ROOT/reference_factory`, plus references to campaign factory roots | Documentation/runbook | `scripts/run/reference-factory ...` | Later docs correction; no repoint this run |
| contentforge docs | `/Users/aderdesouza/Developer/contentforge/README.md` | Human-run examples for `npm run dev` and API usage | Documentation/runbook | `scripts/run/contentforge dev` | Later docs correction; no repoint this run |
| reel_factory docs | `/Users/aderdesouza/Developer/reel_factory/README.md`, `REPO_MAP.md`, and `setup.sh` | Human-run or repository-map references; no active hardcoded runner found | Documentation/runbook | `scripts/run/reel-factory <command>` | Later docs correction; no repoint this run |

## OWNER DECISION - Do Not Repoint

- `/Users/aderdesouza/Developer/contentforge/start.sh`: active local runner candidate with a hardcoded standalone path.
- `/Users/aderdesouza/Developer/campaign_factory/campaign_factory/control.py`: operator command generator for ContentForge start, Campaign Factory serve, Reference Factory export, and batch creation commands. These are operator/deploy/generation adjacent and should be reviewed before repointing.

## Step 2 Entry Points

Monorepo-only wrappers added under `/Users/aderdesouza/Developer/creator-os/scripts/run/`:

- `campaign-factory`: runs `uv run --package campaign-factory campaign-factory` from creator-os with `REEL_FACTORY_ROOT`, `CONTENTFORGE_ROOT`, `REFERENCE_FACTORY_ROOT`, and `THREADSDASH_ROOT` defaulted to creator-os paths.
- `reference-factory`: runs `uv run --package reference-factory python -m reference_factory.cli`.
- `reel-factory`: dispatches `generate-assets`, `reel-pipeline`, `caption-bank`, and `next-batch` to mirrored Python files through the root uv workspace.
- `contentforge`: runs `pnpm --dir apps/contentforge`.

## Step 2 Verification

Commands run from `/Users/aderdesouza/Developer/creator-os`:

| Command | Result |
| --- | --- |
| `uv run which pytest` | Pass: `/Users/aderdesouza/Developer/creator-os/.venv/bin/pytest` |
| `uv run pytest python_packages/reel_factory/tests python_packages/campaign_factory/tests python_packages/reference_factory/tests tests/integration` | Pass: 795 passed, 48 warnings |
| `pnpm --filter contentforge test` | Pass: 81 passed |
| `pnpm check:mirror-parity` | Pass: all mirrors in parity |
| `git diff --check` | Pass |
| `scripts/run/campaign-factory doctor` | Pass: `ok: true`, `blockingCount: 0`, `warningCount: 2` |
| `scripts/run/reference-factory --db /tmp/creator-os-reference-smoke.sqlite --data-root /tmp/creator-os-reference-smoke scan --source python_packages/reference_factory/tests` | Pass: inserted 4 files into the temp database |
| `scripts/run/reel-factory generate-assets reference-image-dry-run --root /tmp/creator-os-reel-smoke --reference /tmp/creator-os-reel-smoke-reference.png --stem smoke --creator Stacey` | Pass: `ok: true`, dry-run direct-reference workflow |
| `scripts/run/contentforge test` | Pass: 81 passed |
