.PHONY: dev test verify sync format install

install:
	pnpm install
	uv sync --all-extras --all-packages
	git config core.hooksPath scripts/hooks

dev-web:
	pnpm run dev

dev-campaign:
	uv run --package campaign-factory uvicorn campaign_factory.app:app --reload --port 8000

dev-reference:
	uv run --package reference-factory uvicorn reference_factory.app:app --reload --port 8001

dev-reel:
	uv run --package reel-factory uvicorn reel_factory.app:app --reload --port 8002

dev:
	npx concurrently "make dev-web" "make dev-campaign" "make dev-reference" "make dev-reel"

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
