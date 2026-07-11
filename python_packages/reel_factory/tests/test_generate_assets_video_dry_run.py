from __future__ import annotations

import json
from pathlib import Path

from asset_prompt_contract import AssetPromptSet
from generate_assets import (
    AssetGenerationPlan,
    build_source_lineage,
    dry_run_video_asset,
    reference_matched_video_duration,
)


def _prompt(tmp_path: Path) -> Path:
    prompt = tmp_path / "prompt.json"
    prompt.write_text(
        json.dumps(
            {
                "higgsfieldGridPrompt": "Create a realistic vertical social photo with natural lighting and coherent phone framing.",
                "klingMotionPrompt": "Use the accepted start image for a short realistic phone video with subtle motion and stable framing.",
                "notes": "test prompt",
            }
        ),
        encoding="utf-8",
    )
    return prompt


def test_video_dry_run_builds_single_kling_command(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    start_image = tmp_path / "accepted.png"
    start_image.write_bytes(b"still")

    result = dry_run_video_asset(
        AssetGenerationPlan(
            prompt_json=prompt,
            stem="clip",
            reference=None,
            soul_id="soul_1",
            soul_name=None,
            start_image=str(start_image),
            out_dir=tmp_path,
            source_dir=tmp_path / "sources",
            campaign="may",
            creator="Stacey",
            estimated_cost_usd=0.10,
        ),
        wait=False,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["workflow"] == "kling3_0_video_from_accepted_still"
    assert len(result["commands"]) == 1
    command = result["commands"][0]
    assert command[:4] == ["higgsfield", "generate", "create", "kling3_0"]
    assert "--start-image" in command
    assert str(start_image) in command
    assert command[command.index("--mode") + 1] == "pro"


def test_source_lineage_includes_aligned_winner_dna_features(tmp_path: Path) -> None:
    prompt = AssetPromptSet(
        higgsfieldGridPrompt="Stacey standing in a bathroom mirror selfie wearing a black bikini with curvy hourglass styling.",
        klingMotionPrompt="Slow hip sway, stable phone camera.",
        notes="",
    )

    lineage = build_source_lineage(
        AssetGenerationPlan(
            prompt_json=tmp_path / "prompt.json",
            stem="clip",
            reference=str(tmp_path / "ref.png"),
            soul_id="soul_1",
            soul_name="Stacey",
            start_image=None,
            out_dir=tmp_path,
            source_dir=tmp_path,
            campaign="Test Campaign",
            creator="Stacey",
            estimated_cost_usd=0.10,
        ),
        prompt=prompt,
        commands=[],
    )

    assert lineage["schema"] == "reel_factory.generated_asset_lineage.v2"
    assert lineage["features"]["creator"] == "stacey"
    assert lineage["features"]["scene"] == "bathroom_mirror"
    assert lineage["features"]["camera"] == "mirror_selfie"
    assert lineage["features"]["outfit"] == "bikini"
    assert lineage["features"]["motion"] == "hip_sway"


def test_video_dry_run_honors_kling_mode_override(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    start_image = tmp_path / "accepted.png"
    start_image.write_bytes(b"still")

    result = dry_run_video_asset(
        AssetGenerationPlan(
            prompt_json=prompt,
            stem="clip",
            reference=None,
            soul_id="soul_1",
            soul_name=None,
            start_image=str(start_image),
            out_dir=tmp_path,
            source_dir=tmp_path / "sources",
            video_mode="4k",
            estimated_cost_usd=0.10,
        ),
        wait=False,
    )

    command = result["commands"][0]
    assert command[command.index("--mode") + 1] == "4k"


def test_video_dry_run_threads_end_image(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    start_image = tmp_path / "accepted.png"
    end_image = tmp_path / "bookend.png"
    start_image.write_bytes(b"still")
    end_image.write_bytes(b"still")

    result = dry_run_video_asset(
        AssetGenerationPlan(
            prompt_json=prompt,
            stem="clip",
            reference=None,
            soul_id="soul_1",
            soul_name=None,
            start_image=str(start_image),
            end_image=str(end_image),
            out_dir=tmp_path,
            source_dir=tmp_path / "sources",
            estimated_cost_usd=0.10,
        ),
        wait=False,
    )

    command = result["commands"][0]
    assert command[command.index("--end-image") + 1] == str(end_image)


def test_video_dry_run_can_disable_kling_mode_for_compatibility(
    tmp_path: Path,
) -> None:
    prompt = _prompt(tmp_path)
    start_image = tmp_path / "accepted.png"
    start_image.write_bytes(b"still")

    result = dry_run_video_asset(
        AssetGenerationPlan(
            prompt_json=prompt,
            stem="clip",
            reference=None,
            soul_id="soul_1",
            soul_name=None,
            start_image=str(start_image),
            out_dir=tmp_path,
            source_dir=tmp_path / "sources",
            video_mode=None,
            estimated_cost_usd=0.10,
        ),
        wait=False,
    )

    assert "--mode" not in result["commands"][0]


def test_reference_matched_video_duration_caps_probe_result(
    monkeypatch, tmp_path: Path
) -> None:
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    monkeypatch.setattr(
        "generate_assets.subprocess.check_output",
        lambda *args, **kwargs: b"12.4",
    )

    assert reference_matched_video_duration(reference, default=5, cap=8) == 8


def test_reference_matched_video_duration_uses_default_for_non_video(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"image")

    assert reference_matched_video_duration(reference, default=5, cap=8) == 5
