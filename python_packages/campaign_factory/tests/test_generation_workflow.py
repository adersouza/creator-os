from __future__ import annotations

from pathlib import Path

import pytest
from campaign_factory.generation_workflow import run_generation_workflow


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

    result = run_generation_workflow(
        object(),
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
    assert result["result"]["providerCalls"] == 0
    assert result["result"]["paidGenerationAllowed"] is False
    assert result["result"]["autoApprovalAllowed"] is False
    assert result["schedulingAllowed"] is False
    assert result["publishingAllowed"] is False
