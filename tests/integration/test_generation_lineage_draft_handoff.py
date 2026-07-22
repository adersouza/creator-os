from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.generation_workflow import run_generation_workflow
from reel_factory.asset_prompt_contract import AssetPromptSet
from reel_factory.generate_assets import AssetGenerationPlan, build_source_lineage

from pipeline_contracts import (
    validate_generated_asset_lineage_v2,
    validate_generation_worker_lineage,
    validate_threadsdash_draft_payload_strict,
)


def _make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True)
    (reel_root / "01_captions").mkdir(parents=True)
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=reel_root,
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def _worker_lineage(tmp_path: Path) -> dict[str, Any]:
    prompt_path = tmp_path / "worker-prompt.json"
    prompt_path.write_text("{}\n", encoding="utf-8")
    lineage = build_source_lineage(
        AssetGenerationPlan(
            prompt_json=prompt_path,
            stem="accepted-still",
            reference=None,
            soul_id="soul_test_stacey",
            soul_name="Stacey",
            start_image=None,
            out_dir=tmp_path / "worker-output",
            source_dir=tmp_path / "worker-lineage",
            campaign="may",
            creator="Stacey",
        ),
        prompt=AssetPromptSet(
            higgsfieldGridPrompt="A clean portrait composition.",
            klingMotionPrompt="Subtle natural movement with stable framing.",
            notes="provider-free integration fixture",
        ),
        commands=[],
    )
    validate_generation_worker_lineage(lineage)
    return lineage


def _patch_provider_free_static_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_invoke(
        _factory: CampaignFactory,
        *,
        still_path: Path,
        output_path: Path,
        duration_seconds: float,
        dry_run: bool,
        allow_upscale: bool,
    ) -> dict[str, Any]:
        assert dry_run is False
        assert allow_upscale is False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"provider-free-static-mp4")
        audio_intent_path = output_path.with_suffix(
            output_path.suffix + ".audio_intent.json"
        )
        audio_intent_path.write_text(
            json.dumps(
                {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "platform_auto_music",
                    "required": True,
                    "status": "recommended",
                    "platform": "instagram_reels",
                    "recommendations": [],
                    "gates": {
                        "allow_draft_export": True,
                        "allow_preview_schedule": False,
                        "allow_live_schedule": False,
                        "allow_publish": False,
                    },
                    "notes": "native audio unresolved",
                    "audio_selection": None,
                    "createdAt": 1,
                }
            ),
            encoding="utf-8",
        )
        return {
            "schema": "reel_factory.static_mp4_render.v1",
            "animationMode": "static_image_mp4",
            "lockedStatic": True,
            "paidGeneration": False,
            "estimatedCostUsd": 0,
            "stillPath": str(still_path),
            "outputPath": str(output_path),
            "durationSeconds": duration_seconds,
            "audioBurned": False,
            "audioIntentPath": str(audio_intent_path),
            "quality": {
                "status": "passed",
                "width": 1080,
                "height": 1920,
                "fps": 30.0,
                "durationSeconds": duration_seconds,
                "warnings": [],
            },
            "ffmpegCommand": [
                "ffmpeg",
                "-loop",
                "1",
                str(still_path),
                str(output_path),
            ],
            "humanReviewRequired": True,
            "dryRun": False,
        }

    monkeypatch.setattr(
        "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
        fake_invoke,
    )


def _add_passing_qc_fixture(
    factory: CampaignFactory, registered_asset: dict[str, Any]
) -> None:
    report_path = Path(registered_asset["campaign_path"]).with_suffix(".audit.json")
    report_path.write_text(
        json.dumps(
            {
                "readinessSummary": {
                    "uploadReady": True,
                    "blockingReasons": [],
                    "warnings": [],
                    "blockingCodes": [],
                    "warningCodes": [],
                    "visualQcStatus": "passed",
                    "identityVerificationStatus": "passed",
                },
                "visualQcStatus": "passed",
                "identityVerificationStatus": "passed",
                "visualQc": {"status": "passed"},
                "identityVerification": {"status": "passed"},
                "overallVerdict": "pass",
                "warnings": [],
                "failedChecks": [],
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    factory.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score,
         status, layers_json, verdicts_json, overall_verdict, files_analyzed,
         failed_checks_json, warnings_json, created_at)
        VALUES ('audit_lineage_integration', ?, ?, 'run_lineage_integration', ?, 100,
                'approved_candidate', '{}', '{}', 'pass', 1, '[]', '[]',
                '2026-01-01T00:00:00+00:00')
        """,
        (
            registered_asset["campaign_id"],
            registered_asset["id"],
            str(report_path),
        ),
    )
    factory.conn.execute(
        "UPDATE rendered_assets SET audit_status = 'approved_candidate' WHERE id = ?",
        (registered_asset["id"],),
    )
    factory.conn.commit()


def _validate_against_released_contract(payload: dict[str, Any]) -> None:
    """Validate the seam without reaching into a sibling repository checkout."""

    validate_threadsdash_draft_payload_strict(payload)


def _build_provider_free_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    worker_lineage = _worker_lineage(tmp_path)
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    still = source_folder / "accepted.png"
    still.write_bytes(b"accepted-still-fixture")
    source_prompt = {
        "promptId": "prompt_integration_001",
        "referenceId": "reference_integration_001",
        "generatedAssetLineage": worker_lineage,
    }

    factory = _make_factory(tmp_path / "campaign-state")
    try:
        factory.domains.asset_import.import_folder(
            source_folder,
            campaign_slug="may",
            model_slug="stacey",
            source_prompt=json.dumps(source_prompt, sort_keys=True),
        )
        _patch_provider_free_static_renderer(monkeypatch)

        run = run_generation_workflow(
            factory,
            mode="soul_static",
            campaign_slug="may",
            accepted_still_path=still,
            dry_run=False,
            apply=True,
        )
        registered = run["result"]["registeredAsset"]
        assert run["mode"] == "soul_static"
        assert run["result"]["paidGeneration"] is False
        assert registered["review_state"] == "review_ready"
        _add_passing_qc_fixture(factory, registered)

        payload = build_draft_payloads(
            factory,
            campaign_slug="may",
            user_id="user_integration",
            review_only=True,
        )
        return payload, registered, worker_lineage
    finally:
        factory.close()


def test_active_mode_worker_lineage_becomes_strict_campaign_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, registered, worker_lineage = _build_provider_free_draft(
        tmp_path, monkeypatch
    )

    validate_threadsdash_draft_payload_strict(payload)
    assert len(payload["drafts"]) == 1

    draft = payload["drafts"][0]
    final_lineage = draft["generatedAssetLineage"]
    validate_generated_asset_lineage_v2(final_lineage)
    assert final_lineage["schema"] == "reel_factory.generated_asset_lineage.v2"
    assert final_lineage["source"]["promptId"] == "prompt_integration_001"
    assert final_lineage["source"]["referenceId"] == "reference_integration_001"
    assert final_lineage["source"]["stem"] == worker_lineage["source"]["stem"]
    assert final_lineage["renderedAssetId"] == registered["id"]
    assert final_lineage["contentFingerprint"] == registered["content_hash"]
    assert final_lineage["captionHash"] == draft["captionHash"]
    assert final_lineage["schema"] != worker_lineage["schema"]


def test_current_threadsdash_consumer_accepts_provider_free_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _, _ = _build_provider_free_draft(tmp_path, monkeypatch)

    _validate_against_released_contract(payload)
