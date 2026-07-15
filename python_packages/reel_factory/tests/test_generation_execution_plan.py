from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from reel_factory import generate_assets
from reel_factory.generation_execution_plan import load_generation_execution_plan


def _write_plan(tmp_path: Path, **updates) -> Path:
    payload = {
        "schema": "campaign_factory.generation_execution_plan.v1",
        "creativeMode": "best_only_kling",
        "stillStrategy": "accepted_rank_one_still",
        "motionStrategy": "kling_best_only",
        "costClassification": "paid_video",
        "providers": ["higgsfield", "kling"],
        "models": ["kling3_0", "static_mp4"],
        "requiredApprovals": [
            "human_still_approval",
            "contentforge_approval",
            "rank_one_selection_receipt",
            "paid_generation",
        ],
        "providerAuthorization": "required_per_paid_call",
        "requiredLineage": [
            "reel_factory.generation_worker_lineage.v1",
            "reel_factory.generated_asset_lineage.v2",
        ],
        "qcRequirements": [
            "contentforge_quality",
            "rank_one_selection",
            "human_final_review",
        ],
        "staticFallbackBehavior": "required_before_paid_motion",
        "allowedOutputSurface": "campaign_review",
        "paidImageGeneration": False,
        "paidVideoGeneration": True,
        "humanReviewRequired": True,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
    payload.update(updates)
    path = tmp_path / "execution-plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_reel_worker_accepts_matching_campaign_execution_plan(tmp_path: Path) -> None:
    payload = load_generation_execution_plan(
        _write_plan(tmp_path), worker_action="video-dry-run"
    )

    assert payload["creativeMode"] == "best_only_kling"
    assert payload["publishingAllowed"] is False


def test_reel_worker_rejects_cross_mode_execution_plan(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="does not authorize reference-image"):
        load_generation_execution_plan(
            _write_plan(tmp_path), worker_action="reference-image"
        )


def test_reel_worker_rejects_policy_drift_before_execution(tmp_path: Path) -> None:
    path = _write_plan(tmp_path, motionStrategy="local_motion_edit")

    with pytest.raises(ValueError, match="motionStrategy"):
        load_generation_execution_plan(path, worker_action="video")


def test_generate_assets_cli_consumes_and_returns_supplied_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    still = tmp_path / "accepted.png"
    still.write_bytes(b"still")
    execution_plan = _write_plan(tmp_path)
    monkeypatch.setattr(
        generate_assets,
        "dry_run_video_asset",
        lambda _plan, *, wait: {"ok": True, "dry_run": True, "wait": wait},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_assets",
            "video-dry-run",
            "--prompt-json",
            str(prompt),
            "--stem",
            "accepted",
            "--start-image",
            str(still),
            "--execution-plan-file",
            str(execution_plan),
            "--root",
            str(tmp_path),
        ],
    )

    assert generate_assets.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["executionPlan"]["creativeMode"] == "best_only_kling"


@pytest.mark.parametrize(
    "mode",
    [
        "reference-image",
        "reference-image-dry-run",
        "image",
        "image-dry-run",
        "video",
        "video-dry-run",
    ],
)
def test_canonical_worker_actions_require_execution_plan_before_plan_construction(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        generate_assets,
        "_plan_from_args",
        lambda _args: pytest.fail("asset plan construction must not be reached"),
    )
    monkeypatch.setattr(
        generate_assets,
        "_direct_plan_from_args",
        lambda _args: pytest.fail("direct plan construction must not be reached"),
    )
    monkeypatch.setattr(sys, "argv", ["generate_assets", mode])

    with pytest.raises(SystemExit) as exc_info:
        generate_assets.main()

    assert exc_info.value.code == 2
    assert "--execution-plan-file is required" in capsys.readouterr().err


def test_read_only_modes_do_not_require_execution_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        generate_assets,
        "probe_higgsfield_capabilities",
        lambda _root, *, force: {"mode": "capabilities", "force": force},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_assets", "capabilities", "--root", str(tmp_path)],
    )

    assert generate_assets.main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "capabilities"


def test_explicit_legacy_dry_run_remains_compatible_without_execution_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        generate_assets,
        "dry_run",
        lambda _plan, *, wait: {"mode": "legacy-dry-run", "wait": wait},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_assets",
            "dry-run",
            "--prompt-json",
            str(prompt),
            "--stem",
            "legacy",
            "--creator",
            "Stacey",
            "--root",
            str(tmp_path),
        ],
    )

    assert generate_assets.main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "legacy-dry-run"
