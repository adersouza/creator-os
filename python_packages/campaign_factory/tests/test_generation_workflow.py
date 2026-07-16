from __future__ import annotations

from pathlib import Path

import pytest
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.generation_workflow import (
    _run_library_reuse_mode,
    _run_motion_edit_mode,
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
        "campaign_factory.generation_workflow.run_front_generation_stage", fake_front
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


def test_motion_mode_creates_static_fallback_before_motion_and_preserves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still = tmp_path / "accepted.png"
    still.write_bytes(b"still")
    fallback = tmp_path / "static.mp4"
    calls: list[str] = []

    def fake_static(*_args, **_kwargs):
        calls.append("static")
        fallback.write_bytes(b"static-fallback")
        return {"paidGeneration": False, "render": {"outputPath": str(fallback)}}

    def fail_motion(*_args, **_kwargs):
        calls.append("motion")
        raise RuntimeError("simulated local motion failure")

    monkeypatch.setattr(
        "campaign_factory.generation_workflow.run_static_mp4_stage", fake_static
    )
    monkeypatch.setattr(
        "campaign_factory.generation_workflow.run_motion_edit_stage", fail_motion
    )

    with pytest.raises(RuntimeError, match="simulated local motion failure"):
        run_generation_workflow(
            object(),
            mode="motion_edit",
            campaign_slug="campaign",
            accepted_still_path=still,
            caption="A caption",
            dry_run=False,
            apply=True,
        )

    assert calls == ["static", "motion"]
    assert fallback.read_bytes() == b"static-fallback"


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
        match="motion_edit execution plan does not authorize library_reuse handler",
    ):
        _run_library_reuse_mode(
            object(),
            execution_plan=build_generation_execution_plan("motion_edit"),
            campaign_slug="campaign",
            library_folder=Path("/definitely/missing"),
            model_slug="stacey",
            output_format="reel",
            variant_count=1,
            workers=1,
            dry_run=True,
        )


def test_motion_handler_rejects_cross_mode_plan_before_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "campaign_factory.generation_workflow.run_static_mp4_stage",
        lambda *_args, **_kwargs: pytest.fail("render must not be reached"),
    )

    with pytest.raises(
        PermissionError,
        match="library_reuse execution plan does not authorize motion_edit handler",
    ):
        _run_motion_edit_mode(
            object(),
            execution_plan=build_generation_execution_plan("library_reuse"),
            campaign_slug="campaign",
            accepted_still_path=Path("/definitely/missing.png"),
            caption="caption",
            duration_seconds=5.0,
            dry_run=True,
            apply=False,
            allow_upscale=False,
        )
