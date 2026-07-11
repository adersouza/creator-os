.PHONY: dev test verify sync format install reel-models backup-runtime

install:
	pnpm install
	uv sync --all-extras --all-packages
	git config core.hooksPath scripts/hooks

reel-models:
	uv sync --package reel-factory --extra vision --extra ai --extra identity --inexact
	uv run --package reel-factory --extra vision --extra ai --extra identity python python_packages/reel_factory/fetch_models.py

backup-runtime:
	uv run python scripts/backup_runtime_state.py

dev-campaign:
	uv run --package campaign-factory uvicorn campaign_factory.app:app --reload --port 8000

dev-reference:
	uv run --package reference-factory uvicorn --factory reference_factory.server:create_app --reload --port 8001

dev:
	npx concurrently "make dev-campaign" "make dev-reference"

test:
	pnpm run test
	uv run pytest packages/pipeline_contracts/tests/
	uv run pytest python_packages/campaign_factory/tests/
	uv run pytest python_packages/reference_factory/tests/
	uv run pytest python_packages/reel_factory/tests/
	uv run pytest tests/integration/

# One command to verify everything locally, mirroring CI: static gates then tests.
verify:
	pnpm run check:all
	$(MAKE) test
