from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Any

from pipeline_contracts import schema_path

from .config import CREATOR_OS_ROOT, Settings


def operator_control_check(
    settings: Settings,
) -> dict[str, Any]:
    """Verify that Campaign Factory can control the local pipeline repos."""
    reference_bank = (
        settings.reference_reels_root / "learning" / "campaign_reference_bank.json"
    )
    checks: list[dict[str, Any]] = []

    checks.extend(
        [
            _path_check(
                "campaign_factory",
                settings.root / "campaign_factory" / "cli.py",
                required=True,
            ),
            _path_check("reel_factory", settings.reel_factory_root, required=True),
            _path_check(
                "reel_factory.reel_pipeline",
                settings.reel_factory_root / "reel_factory" / "reel_pipeline.py",
                required=True,
            ),
            _path_check(
                "reel_factory.slideshow_factory",
                settings.reel_factory_root / "reel_factory" / "slideshow_factory.py",
                required=True,
            ),
            _path_check("contentforge", settings.contentforge_root, required=True),
            _path_check(
                "contentforge.package",
                settings.contentforge_root / "package.json",
                required=True,
            ),
            _path_check(
                "contentforge.cli",
                settings.contentforge_root / "cli.mjs",
                required=True,
            ),
            _path_check(
                "contentforge.similarity",
                settings.contentforge_root / "lib" / "similarity.js",
                required=True,
            ),
            _path_check(
                "reference_factory", settings.reference_factory_root, required=True
            ),
            _path_check(
                "reference_factory.cli",
                settings.reference_factory_root / "reference_factory" / "cli.py",
                required=True,
            ),
            _path_check("reference_bank", reference_bank, required=False),
            _path_check("threadsdash", settings.threadsdash_root, required=False),
            _path_check(
                "threadsdash.package",
                settings.threadsdash_root / "package.json",
                required=False,
            ),
            _path_check(
                "threadsdash.audio_smoke_validator",
                settings.threadsdash_root
                / "tests"
                / "pipelineAudioSmokeFixture.test.ts",
                required=False,
            ),
            _path_check(
                "schema.audio_intent",
                schema_path("audio_intent"),
                required=True,
            ),
            _path_check(
                "schema.threadsdash_drafts",
                schema_path("campaign_draft_payload"),
                required=True,
            ),
            _path_check(
                "schema.audio_catalog_export",
                schema_path("audio_catalog_export"),
                required=True,
            ),
            _path_check(
                "schema.performance_sync",
                schema_path("performance_sync"),
                required=True,
            ),
            _command_check("ffmpeg", required=True),
            _command_check("ffprobe", required=True),
            _path_check(
                "campaign_factory.venv_python",
                settings.root / ".venv" / "bin" / "python",
                required=False,
            ),
            _path_check(
                "threadsdash.node_modules",
                settings.threadsdash_root / "node_modules",
                required=False,
            ),
        ]
    )
    blocking = [item for item in checks if item["required"] and item["status"] != "ok"]
    warnings = [
        item for item in checks if not item["required"] and item["status"] != "ok"
    ]
    return {
        "schema": "campaign_factory.operator_control_check.v1",
        "ok": not blocking,
        "contentforgeMode": "local_cli",
        "checks": checks,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "commands": {
            "checkContentForge": (f"pnpm --dir {settings.contentforge_root} build"),
            "startCampaignFactory": (
                "uv run --package campaign-factory campaign-factory "
                "serve --host 127.0.0.1 --port 8877"
            ),
            "exportReferencePatterns": (
                "uv run --package reference-factory python -m reference_factory.cli "
                "export-patterns --limit 300 --for-campaign-factory"
            ),
            "makeBatch": (
                f"{CREATOR_OS_ROOT / 'scripts' / 'creator-os'} campaign-prepare "
                "--confirm-write "
                "--folder <source_folder> --campaign <campaign_slug> --model <model_slug> "
                "--format auto --variant-count 20"
            ),
        },
    }


def _path_check(name: str, path: Path, *, required: bool) -> dict[str, Any]:
    exists = path.exists()
    return {
        "name": name,
        "status": "ok"
        if exists
        else ("missing_required" if required else "missing_optional"),
        "required": required,
        "path": str(path),
    }


def _command_check(name: str, *, required: bool) -> dict[str, Any]:
    path = which(name)
    return {
        "name": name,
        "status": "ok"
        if path
        else ("missing_required" if required else "missing_optional"),
        "required": required,
        "path": path,
    }
