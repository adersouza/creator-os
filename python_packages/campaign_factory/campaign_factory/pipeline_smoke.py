from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import MethodType
from typing import Any

from .audio_smoke import run_pipeline_audio_smoke
from .config import Settings
from .core import CampaignFactory


def run_pipeline_smoke(
    *,
    projects_root: Path,
    workspace: Path | None = None,
    run_threadsdash_validator: bool = True,
) -> dict[str, Any]:
    projects_root = Path(projects_root).expanduser().resolve()
    if workspace is None:
        with tempfile.TemporaryDirectory(prefix="campaign-full-smoke-") as tmp:
            return _run_pipeline_smoke(
                projects_root=projects_root,
                workspace=Path(tmp),
                run_threadsdash_validator=run_threadsdash_validator,
            )
    return _run_pipeline_smoke(
        projects_root=projects_root,
        workspace=Path(workspace).expanduser().resolve(),
        run_threadsdash_validator=run_threadsdash_validator,
    )


def _run_pipeline_smoke(
    *,
    projects_root: Path,
    workspace: Path,
    run_threadsdash_validator: bool,
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    audio = run_pipeline_audio_smoke(
        projects_root=projects_root,
        workspace=workspace / "audio_boundary",
        run_threadsdash_validator=run_threadsdash_validator,
    )
    generation = _run_mocked_generation_intake_smoke(
        projects_root=projects_root, workspace=workspace / "generation_boundary"
    )
    summary = {
        "schema": "campaign_factory.pipeline_smoke.v1",
        "ok": bool(audio.get("ok")) and bool(generation.get("ok")),
        "workspace": str(workspace),
        "projectsRoot": str(projects_root),
        "mode": "mocked_providers_no_credits",
        "boundaries": {
            "audioNativeGate": audio,
            "generatedLineageIntake": generation,
            "reelContentforgeThreadsdash": {
                "source": "pipeline_audio_smoke",
                "reelFactory": audio.get("reelFactory"),
                "contentforge": audio.get("contentforge"),
                "threadsdash": audio.get("threadsdash"),
            },
            "performanceFeedback": {
                "inserted": ((audio.get("campaign") or {}).get("performanceInserted")),
                "leaderboardAudioCount": (
                    (audio.get("campaign") or {}).get("leaderboardAudioCount")
                ),
            },
        },
        "skippedBoundaries": [],
    }
    (workspace / "pipeline_smoke_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def _run_mocked_generation_intake_smoke(
    *, projects_root: Path, workspace: Path
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    source_video = workspace / "mocked_kling_output.mp4"
    source_video.write_bytes(b"mocked generated video")
    lineage_path = workspace / "generated_asset_lineage.json"
    lineage = _mock_lineage(source_video)
    lineage_path.write_text(
        json.dumps(lineage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    settings = Settings(
        root=workspace / "campaign_factory",
        db_path=workspace / "campaign_factory" / "campaign_factory.sqlite",
        reel_factory_root=projects_root / "reel_factory",
        contentforge_root=projects_root / "contentforge",
        reference_factory_root=projects_root / "reference_factory",
        threadsdash_root=projects_root / "ThreadsDashboard",
        campaigns_dir=workspace / "campaign_factory" / "campaigns",
    )
    factory = CampaignFactory(settings)
    captured: dict[str, Any] = {}

    def fake_make_batch(_self: CampaignFactory, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "schema": "campaign_factory.make_batch.v1",
            "campaign": kwargs["campaign_slug"],
            "mocked": True,
            "dryRunExport": kwargs.get("dry_run_export"),
        }

    factory.make_batch = MethodType(fake_make_batch, factory)
    try:
        result = factory.intake_finished_video(
            input_path=source_video,
            model_slug="stacey",
            platform="instagram",
            goal="reach",
            reference_pattern="auto",
            campaign_slug="mocked_generation_smoke",
            source_lineage_path=lineage_path,
            dry_run_export=True,
            variant_count=1,
            workers=1,
            recipes=["v01_original"],
        )
    finally:
        factory.close()

    source_prompt = json.loads(captured.get("source_prompt") or "{}")
    generated_lineage = source_prompt.get("generatedAssetLineage") or {}
    checks = {
        "intakeCalled": bool(captured),
        "draftFirst": bool(result.get("finishedVideoIntake", {}).get("draftFirst")),
        "lineagePreserved": generated_lineage.get("generation", {}).get("tool")
        == "higgsfield_kling_cli",
        "promptScorePreserved": (
            generated_lineage.get("quality", {}).get("promptScore") or {}
        ).get("score")
        == 91,
        "fallbackPreserved": generated_lineage.get("generation", {})
        .get("fallback", {})
        .get("provider")
        == "grok_imagine",
        "variationGridPreserved": generated_lineage.get("generation", {})
        .get("variationGrid", {})
        .get("provider")
        == "higgsfield_grok_image",
    }
    return {
        "schema": "campaign_factory.mocked_generation_intake_smoke.v1",
        "ok": all(checks.values()),
        "workspace": str(workspace),
        "lineagePath": str(lineage_path),
        "checks": checks,
        "finishedVideoIntake": result.get("finishedVideoIntake"),
    }


def _mock_lineage(source_video: Path) -> dict[str, Any]:
    return {
        "schema": "campaign_factory.generated_asset_lineage.v1",
        "pipelineTraceId": "trace_mocked_generation_intake_smoke",
        "source": {
            "referenceId": "ref_mirror_selfie_smoke",
            "patternCardId": "pattern_mirror_selfie_smoke",
            "promptId": "prompt_mirror_selfie_smoke",
            "formatType": "mirror_selfie",
            "referencePattern": "auto",
        },
        "generation": {
            "tool": "higgsfield_kling_cli",
            "modelProfile": "Stacey",
            "soulId": "5828d958-91dd-4d6d-8909-934503f47644",
            "imageModel": "text2image_soul_v2",
            "videoModel": "kling3_0",
            "imageJobId": "mock_img_job",
            "videoJobId": "mock_vid_job",
            "imagePath": str(source_video.with_suffix(".png")),
            "assetPath": str(source_video),
            "status": "generated",
            "fallback": {
                "provider": "grok_imagine",
                "when": "Use if Kling 3.0 rejects the prompt or fails generation.",
                "audio": "off",
                "prompt": "Animate the selected image as a short vertical IG Reels style clip with no audio.",
            },
            "variationGrid": {
                "provider": "higgsfield_grok_image",
                "prompt": "Make a 3x3 variation of this exact pose/background with fitted outfit variations.",
                "status": "planned",
            },
        },
        "review": {"humanReviewRequired": True, "status": "draft"},
        "quality": {
            "copyRisk": "medium",
            "promptScore": {
                "schema": "reference_factory.prompt_quality_score.v1",
                "score": 91,
                "imageScore": 94,
                "videoScore": 85,
                "status": "pass",
                "reasons": ["structured JSON prompt present", "motion prompt present"],
                "warnings": [],
            },
            "operatorRating": None,
        },
    }
