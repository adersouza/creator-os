from __future__ import annotations

from pathlib import Path

import pytest
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.generation_workflow import (
    _run_library_reuse_mode,
    run_generation_workflow,
)
from campaign_test_support import make_factory


def test_workflow_builds_and_passes_one_canonical_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    captured = {}

    def fake_front(_factory, **kwargs):
        captured["plan"] = kwargs["execution_plan"]
        return {"schema": "campaign_factory.front_generation_stage_run.v1"}

    monkeypatch.setattr(
        "campaign_factory.front_generation_stage.run_front_generation_stage", fake_front
    )

    result = run_generation_workflow(
        object(),
        mode="soul_static",
        campaign_slug="campaign",
        reference_image_path=reference,
        creator="Stacey",
        dry_run=True,
        apply=False,
    )

    assert captured["plan"].creative_mode == "soul_static"
    assert result["executionPlan"] == captured["plan"].to_contract()
    assert (
        result["modeDefinition"]["requiredApprovals"]
        == result["executionPlan"]["requiredApprovals"]
    )


def test_local_wan_mode_routes_to_the_guarded_motion_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still = tmp_path / "accepted.png"
    still.write_bytes(b"still")
    captured = {}

    def fake_motion(*_args, **kwargs):
        captured.update(kwargs)
        return {"schema": "campaign_factory.motion_generation_stage_run.v1"}

    monkeypatch.setattr(
        "campaign_factory.motion_generation_stage.run_motion_generation_stage",
        fake_motion,
    )
    result = run_generation_workflow(
        object(),
        mode="local_wan",
        campaign_slug="campaign",
        accepted_still_path=still,
        motion_prompt="Natural breathing and a slow camera push toward the subject",
        dry_run=True,
        apply=False,
    )
    assert result["mode"] == "local_wan"
    assert captured["model_id"] == "local_wan22_ti2v_5b_mlx"
    assert captured["dry_run"] is True


@pytest.mark.parametrize("mode", ["motion_edit", "best_only_kling"])
def test_retired_modes_are_rejected_before_factory_or_render_access(mode: str) -> None:
    with pytest.raises(ValueError, match=f"retired creative workflow mode: {mode}"):
        run_generation_workflow(
            object(),
            mode=mode,
            campaign_slug="campaign",
            dry_run=True,
            apply=False,
        )


def test_local_mode_authorizes_ltx_audio_without_paid_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still = tmp_path / "accepted.png"
    still.write_bytes(b"still")
    captured = {}

    def fake_motion(*_args, **kwargs):
        captured.update(kwargs)
        return {"schema": "campaign_factory.motion_generation_stage_run.v1"}

    monkeypatch.setattr(
        "campaign_factory.motion_generation_stage.run_motion_generation_stage",
        fake_motion,
    )
    run_generation_workflow(
        object(),
        mode="local_wan",
        campaign_slug="campaign",
        accepted_still_path=still,
        motion_model_id="local_ltx23_distilled_mlx",
        motion_task="image_to_video",
        motion_prompt="Natural motion synchronized with softly generated ambient audio",
        generate_audio=True,
        dry_run=True,
        apply=False,
    )
    assert captured["model_id"] == "local_ltx23_distilled_mlx"
    assert captured["generate_audio"] is True
    assert captured["motion_task"] == "image_to_video"
    assert captured["paid_confirmation"] is False


def test_local_mode_routes_talking_task_and_source_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still = tmp_path / "accepted.png"
    still.write_bytes(b"still")
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"speech")
    captured = {}

    def fake_motion(*_args, **kwargs):
        captured.update(kwargs)
        return {"schema": "campaign_factory.motion_generation_stage_run.v1"}

    monkeypatch.setattr(
        "campaign_factory.motion_generation_stage.run_motion_generation_stage",
        fake_motion,
    )
    run_generation_workflow(
        object(),
        mode="local_wan",
        campaign_slug="campaign",
        accepted_still_path=still,
        motion_model_id="local_longcat_avatar15_q4_mlx",
        motion_prompt="She speaks naturally to camera with subtle head movement",
        motion_task="audio_image_to_video",
        audio_path=audio,
        dry_run=True,
        apply=False,
    )
    assert captured["model_id"] == "local_longcat_avatar15_q4_mlx"
    assert captured["motion_task"] == "audio_image_to_video"
    assert captured["audio_path"] == audio
    assert captured["paid_confirmation"] is False


def test_generation_workflow_rejects_unknown_or_missing_mode() -> None:
    with pytest.raises(ValueError, match="unknown creative workflow mode"):
        run_generation_workflow(
            object(),
            mode="",
            campaign_slug="campaign",
            dry_run=True,
            apply=False,
        )


def test_library_reuse_folder_preflight_is_free_and_review_only(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "library"
    folder.mkdir()
    source = folder / "selected.mp4"
    source.write_bytes(b"selected-library-mp4")
    cf = make_factory(tmp_path)
    try:
        result = run_generation_workflow(
            cf,
            mode="library_reuse",
            campaign_slug="campaign",
            library_folder=folder,
            model_slug="stacey",
            output_format="reel",
            variant_count=10,
            workers=2,
            dry_run=True,
            apply=False,
        )

        assert result["mode"] == "library_reuse"
        assert result["result"]["selectedCount"] == 1
        assert result["result"]["providerCalls"] == 0
        assert result["result"]["paidGenerationAllowed"] is False
        assert result["result"]["autoApprovalAllowed"] is False
        assert result["result"]["renderingPerformed"] is False
        assert result["schedulingAllowed"] is False
        assert result["publishingAllowed"] is False
    finally:
        cf.close()


def test_library_reuse_requires_explicit_folder_and_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="library_folder is required"):
        run_generation_workflow(
            object(),
            mode="library_reuse",
            campaign_slug="campaign",
            dry_run=True,
            apply=False,
        )

    folder = tmp_path / "library"
    folder.mkdir()
    with pytest.raises(ValueError, match="model_slug is required"):
        run_generation_workflow(
            object(),
            mode="library_reuse",
            campaign_slug="campaign",
            library_folder=folder,
            dry_run=True,
            apply=False,
        )


def test_library_handler_rejects_cross_mode_plan_before_folder_access() -> None:
    with pytest.raises(
        PermissionError,
        match="soul_static execution plan does not authorize library_reuse handler",
    ):
        _run_library_reuse_mode(
            object(),
            execution_plan=build_generation_execution_plan("soul_static"),
            campaign_slug="campaign",
            library_folder=Path("/definitely/missing"),
            model_slug="stacey",
            output_format="reel",
            variant_count=1,
            workers=1,
            dry_run=True,
        )
