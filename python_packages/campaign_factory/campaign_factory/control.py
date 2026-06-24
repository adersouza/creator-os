from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import CREATOR_OS_ROOT, Settings


def operator_control_check(
    settings: Settings,
    *,
    contentforge_base_url: str | None = None,
    check_http: bool = False,
) -> dict[str, Any]:
    """Verify that Campaign Factory can control the local pipeline repos."""
    base_url = contentforge_base_url or settings.contentforge_base_url
    reference_bank = settings.reference_reels_root / "learning" / "campaign_reference_bank.json"
    checks: list[dict[str, Any]] = []

    checks.extend([
        _path_check("campaign_factory", settings.root / "campaign_factory" / "cli.py", required=True),
        _path_check("reel_factory", settings.reel_factory_root, required=True),
        _path_check("reel_factory.reel_pipeline", settings.reel_factory_root / "reel_pipeline.py", required=True),
        _path_check("reel_factory.slideshow_factory", settings.reel_factory_root / "slideshow_factory.py", required=True),
        _path_check("contentforge", settings.contentforge_root, required=True),
        _path_check("contentforge.package", settings.contentforge_root / "package.json", required=True),
        _path_check("contentforge.variant_pack_api", settings.contentforge_root / "app" / "api" / "variant-pack" / "route.js", required=True),
        _path_check("contentforge.similarity_api", settings.contentforge_root / "app" / "api" / "similarity" / "route.js", required=True),
        _path_check("reference_factory", settings.reference_factory_root, required=True),
        _path_check("reference_factory.cli", settings.reference_factory_root / "reference_factory" / "cli.py", required=True),
        _path_check("reference_bank", reference_bank, required=False),
        _path_check("threadsdash", settings.threadsdash_root, required=False),
        _path_check("threadsdash.package", settings.threadsdash_root / "package.json", required=False),
        _path_check("threadsdash.audio_smoke_validator", settings.threadsdash_root / "tests" / "pipelineAudioSmokeFixture.test.ts", required=False),
        _path_check("schema.audio_intent", settings.root / "schemas" / "audio_intent.v1.schema.json", required=True),
        _path_check("schema.threadsdash_drafts", settings.root / "schemas" / "campaign_draft_payload.v1.schema.json", required=True),
        _path_check("schema.audio_catalog_export", settings.root / "schemas" / "audio_catalog_export.v1.schema.json", required=True),
        _path_check("schema.performance_sync", settings.root / "schemas" / "performance_sync.v1.schema.json", required=True),
        _command_check("ffmpeg", required=True),
        _command_check("ffprobe", required=True),
        _path_check("campaign_factory.venv_python", settings.root / ".venv" / "bin" / "python", required=False),
        _path_check("threadsdash.node_modules", settings.threadsdash_root / "node_modules", required=False),
    ])
    if check_http:
        checks.append(_http_check("contentforge.http", base_url))

    blocking = [item for item in checks if item["required"] and item["status"] != "ok"]
    warnings = [item for item in checks if not item["required"] and item["status"] != "ok"]
    return {
        "schema": "campaign_factory.operator_control_check.v1",
        "ok": not blocking,
        "contentforgeBaseUrl": base_url,
        "checks": checks,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "commands": {
            "startContentForge": f"{_run_script('contentforge')} dev -- -p 3002",
            "startCampaignFactory": f"{_run_script('campaign-factory')} serve --host 127.0.0.1 --port 8877",
            "exportReferencePatterns": f"{_run_script('reference-factory')} export-patterns --limit 300 --for-campaign-factory",
            "makeBatch": (
                f"{_run_script('campaign-factory')} make-batch "
                "--folder <source_folder> --campaign <campaign_slug> --model <model_slug> "
                "--format auto --variant-count 20 --reference-pattern auto "
                "--contentforge-base-url http://127.0.0.1:3002 --dry-run-export --user-id <user_id>"
            ),
        },
    }


def _run_script(name: str) -> str:
    return str(CREATOR_OS_ROOT / "scripts" / "run" / name)


def _path_check(name: str, path: Path, *, required: bool) -> dict[str, Any]:
    exists = path.exists()
    return {
        "name": name,
        "status": "ok" if exists else ("missing_required" if required else "missing_optional"),
        "required": required,
        "path": str(path),
    }


def _command_check(name: str, *, required: bool) -> dict[str, Any]:
    path = which(name)
    return {
        "name": name,
        "status": "ok" if path else ("missing_required" if required else "missing_optional"),
        "required": required,
        "path": path,
    }


def _http_check(name: str, url: str) -> dict[str, Any]:
    try:
        request = Request(url, method="GET")
        with urlopen(request, timeout=2) as response:
            return {
                "name": name,
                "status": "ok" if 200 <= response.status < 500 else "unavailable",
                "required": False,
                "url": url,
                "httpStatus": response.status,
            }
    except (OSError, URLError) as exc:
        return {
            "name": name,
            "status": "unavailable",
            "required": False,
            "url": url,
            "error": str(exc),
        }
