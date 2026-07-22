from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.motion_generation_stage import (
    _register_review_asset,
    run_motion_generation_stage,
)
from campaign_test_support import add_source_asset, make_factory

PROMPT = "Natural breathing, a gentle head turn, and a slow cinematic camera push"


def test_local_wan_apply_preserves_static_fallback_then_registers_review_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        calls: list[str] = []

        def fake_static(*_args, **kwargs):
            calls.append("static")
            assert kwargs["apply"] is True
            return {"registeredAsset": {"source_asset_id": source["id"]}}

        def fake_worker(command, *, factory):
            del factory
            if "--dry-run" in command:
                calls.append("preflight")
                return {
                    "schema": "reel_factory.motion_generation_result.v1",
                    "providerCalls": 0,
                    "result": {"status": "planned"},
                }
            calls.append("local_apply")
            output = Path(command[command.index("--out") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"generated-motion-video")
            return {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "result": {
                    "status": "completed",
                    "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
            }

        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage", fake_static
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker", fake_worker
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("local_wan"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="local_wan22_ti2v_5b_mlx",
            duration_seconds=6,
            resolution=None,
            seed=42,
            steps=40,
            dry_run=False,
            apply=True,
        )
        assert calls == ["preflight", "static", "local_apply"]
        asset = result["registeredAsset"]
        assert asset["audit_status"] == "pending"
        assert asset["review_state"] == "review_ready"
        assert asset["caption"] == ""
        assert result["providerCalls"] == 0
    finally:
        cf.close()


def test_wavespeed_dry_run_has_zero_provider_calls_and_no_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        scope = {"requestFingerprint": "a" * 64}
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "spendScope": scope,
            },
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage",
            lambda *_args, **_kwargs: {"dryRun": True},
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.issue_wavespeed_spend_authorization",
            lambda *_args, **_kwargs: pytest.fail("dry-run must not authorize spend"),
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("best_motion"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="wavespeed_wan27_i2v_pro",
            duration_seconds=5,
            resolution="1080p",
            seed=42,
            steps=40,
            dry_run=True,
            apply=False,
        )
        assert result["paidGeneration"] is True
        assert result["providerCalls"] == 0
        assert result["registeredAsset"] is None
    finally:
        cf.close()


def test_best_motion_rejects_local_or_unknown_model_before_any_worker_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: pytest.fail("worker must not run"),
        )
        with pytest.raises(PermissionError, match="does not authorize model"):
            run_motion_generation_stage(
                cf,
                execution_plan=build_generation_execution_plan("best_motion"),
                campaign_slug="may",
                still_path=still,
                prompt=PROMPT,
                model_id="local_wan22_ti2v_5b_mlx",
                duration_seconds=6,
                resolution="720p",
                seed=42,
                steps=40,
                dry_run=True,
                apply=False,
            )
    finally:
        cf.close()


def test_ltx_embedded_audio_is_not_misclassified_as_native_platform_audio(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        output = tmp_path / "ltx.mp4"
        output.write_bytes(b"ltx-video-with-audio")
        campaign = cf.domains.campaign_by_slug("may")
        asset = _register_review_asset(
            cf,
            campaign=campaign,
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_ltx23_distilled_mlx",
            source_path=still,
            source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
            output_path=output,
            worker_result={
                "result": {
                    "audio": {
                        "mode": "generated",
                        "nativePlatformAudio": False,
                        "sidecarSha256": "a" * 64,
                    },
                    "aiDisclosureRequired": True,
                }
            },
            paid=False,
        )
        metadata = json.loads(asset["metadata_json"])
        assert metadata["audioBurned"] is True
        assert metadata["embeddedAudioMode"] == "generated"
        assert metadata["nativeAudioResolved"] is False
        assert (
            "local_audio_policy_review_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "ai_generated_media_disclosure_required"
            in metadata["publishability"]["blockingIssues"]
        )
    finally:
        cf.close()
