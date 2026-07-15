from __future__ import annotations

import copy
from pathlib import Path

import pytest
from reel_factory.reference_video_remix import (
    build_reference_video_remix_plan,
    gemini_motion_analysis_instruction,
)

from pipeline_contracts import load_example, validate_reference_video_remix_plan


def _inputs(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "video": tmp_path / "operator_selected_reference.mp4",
        "source_first": tmp_path / "source_first.png",
        "source_last": tmp_path / "source_last.png",
        "accepted_first": tmp_path / "accepted_first.png",
        "accepted_last": tmp_path / "accepted_last.png",
    }
    for index, path in enumerate(paths.values(), start=1):
        path.write_bytes((f"fixture-{index}-" * 32).encode())
    return paths


def _build(tmp_path: Path, **overrides):
    paths = _inputs(tmp_path)
    values = {
        "reference_video_path": paths["video"],
        "source_first_frame_path": paths["source_first"],
        "source_last_frame_path": paths["source_last"],
        "analysis": load_example("reference_video_motion_analysis"),
        "creator": "Stacey",
        "soul_id": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        "operator_selected": True,
        "rights_confirmed": True,
    }
    values.update(overrides)
    return build_reference_video_remix_plan(**values), paths


def test_builds_blocked_seedance_plan_without_provider_execution(tmp_path):
    plan, _ = _build(tmp_path)

    validate_reference_video_remix_plan(plan)
    assert plan["status"] == "awaiting_endpoint_frames"
    assert plan["animation"]["provider"] == "seedance"
    assert plan["animation"]["routingReason"] == "reference_video_conditioning"
    assert plan["animation"]["command"] is None
    assert plan["animation"]["paidGenerationAuthorized"] is False
    assert plan["approval"]["publishingAllowed"] is False
    frame_command = plan["framePair"]["first"]["generation"]["dryRunCommand"]
    assert frame_command[:4] == [
        "python3",
        "-m",
        "reel_factory.generate_assets",
        "reference-image-dry-run",
    ]
    assert frame_command[frame_command.index("--creator") + 1] == "Stacey"
    assert frame_command[frame_command.index("--creator") + 2] == "--soul-id"
    assert plan["framePair"]["last"]["generation"]["referenceConditioned"] is True


def test_gemini_instruction_requests_structural_json_without_source_copying():
    instruction = gemini_motion_analysis_instruction("ref_video_001")

    assert "reel_factory.reference_video_motion_analysis.v1" in instruction
    assert "referenceId ref_video_001" in instruction
    assert "one continuous 9:16 shot" in instruction
    assert "Do not return a transcript" in instruction
    assert "copy the source asset literally" in instruction


def test_ready_seedance_plan_routes_both_frames_and_reference_video(tmp_path):
    paths = _inputs(tmp_path)
    plan = build_reference_video_remix_plan(
        reference_video_path=paths["video"],
        source_first_frame_path=paths["source_first"],
        source_last_frame_path=paths["source_last"],
        analysis=load_example("reference_video_motion_analysis"),
        creator="Stacey",
        soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        operator_selected=True,
        rights_confirmed=True,
        accepted_first_frame_path=paths["accepted_first"],
        accepted_last_frame_path=paths["accepted_last"],
        first_frame_approval_id="approval_first",
        last_frame_approval_id="approval_last",
        budget_cap_credits=12,
    )

    command = plan["animation"]["command"]
    assert plan["status"] == "ready_for_paid_animation_approval"
    assert plan["animation"]["status"] == "ready_for_paid_approval"
    assert command[3] == "seedance_2_0"
    assert command[command.index("--start-image") + 1] == str(paths["accepted_first"])
    assert command[command.index("--end-image") + 1] == str(paths["accepted_last"])
    assert command[command.index("--video") + 1] == str(paths["video"])
    assert command[command.index("--duration") + 1] == "8"
    assert "7.5" not in command
    assert "--sound" not in command
    assert plan["scope"] == {
        "sourceDurationSeconds": 7.5,
        "outputDurationSeconds": 8,
        "durationRoundingPolicy": "nearest_integer_half_up",
        "shotCount": 1,
        "oneShotOnly": True,
        "outputAspectRatio": "9:16",
    }
    assert plan["animation"]["inputs"]["durationSeconds"] == 8
    assert plan["lineageSeed"]["sourceDurationSeconds"] == 7.5
    assert plan["lineageSeed"]["outputDurationSeconds"] == 8
    assert plan["animation"]["spendGuard"] == {
        "providerQuoteRequired": True,
        "atomicReservationRequired": True,
        "budgetCapCredits": 12.0,
    }
    assert plan["lineageSeed"]["firstAcceptedFrameSha256"]
    assert plan["lineageSeed"]["lastAcceptedFrameSha256"]
    assert plan["animation"]["paidGenerationAuthorized"] is False


def test_explicit_kling_plan_uses_frames_and_prompt_without_source_video(tmp_path):
    paths = _inputs(tmp_path)
    analysis = load_example("reference_video_motion_analysis")
    analysis["requiresReferenceVideoConditioning"] = False
    plan = build_reference_video_remix_plan(
        reference_video_path=paths["video"],
        source_first_frame_path=paths["source_first"],
        source_last_frame_path=paths["source_last"],
        analysis=analysis,
        creator="Stacey",
        soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        operator_selected=True,
        rights_confirmed=True,
        preferred_provider="kling",
        accepted_first_frame_path=paths["accepted_first"],
        accepted_last_frame_path=paths["accepted_last"],
        first_frame_approval_id="approval_first",
        last_frame_approval_id="approval_last",
    )

    command = plan["animation"]["command"]
    assert plan["animation"]["provider"] == "kling"
    assert plan["animation"]["model"] == "kling3_0"
    assert plan["animation"]["routingReason"] == "explicit_provider"
    assert "--start-image" in command
    assert "--end-image" in command
    assert "--video" not in command
    assert command[command.index("--mode") + 1] == "pro"
    assert command[command.index("--duration") + 1] == "8"


def test_auto_route_falls_back_to_kling_when_seedance_is_unavailable(tmp_path):
    plan, _ = _build(tmp_path, available_providers=("kling",))

    assert plan["animation"]["provider"] == "kling"
    assert plan["animation"]["routingReason"] == "deterministic_fallback"


def test_rejects_reference_without_operator_rights_confirmation(tmp_path):
    with pytest.raises(PermissionError, match="rights"):
        _build(tmp_path, rights_confirmed=False)


def test_rejects_gapped_gemini_timeline(tmp_path):
    analysis = copy.deepcopy(load_example("reference_video_motion_analysis"))
    analysis["structure"]["timeline"][1]["startSeconds"] = 4.0

    with pytest.raises(ValueError, match="continuously cover"):
        _build(tmp_path, analysis=analysis)


def test_rejects_incomplete_endpoint_approval_pair(tmp_path):
    paths = _inputs(tmp_path)

    with pytest.raises(ValueError, match="supplied together"):
        build_reference_video_remix_plan(
            reference_video_path=paths["video"],
            source_first_frame_path=paths["source_first"],
            source_last_frame_path=paths["source_last"],
            analysis=load_example("reference_video_motion_analysis"),
            creator="Stacey",
            soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            operator_selected=True,
            rights_confirmed=True,
            accepted_first_frame_path=paths["accepted_first"],
        )


def test_rejects_unchanged_source_as_accepted_endpoint(tmp_path):
    paths = _inputs(tmp_path)

    with pytest.raises(ValueError, match="unchanged source"):
        build_reference_video_remix_plan(
            reference_video_path=paths["video"],
            source_first_frame_path=paths["source_first"],
            source_last_frame_path=paths["source_last"],
            analysis=load_example("reference_video_motion_analysis"),
            creator="Stacey",
            soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            operator_selected=True,
            rights_confirmed=True,
            accepted_first_frame_path=paths["source_first"],
            accepted_last_frame_path=paths["accepted_last"],
            first_frame_approval_id="approval_first",
            last_frame_approval_id="approval_last",
        )
