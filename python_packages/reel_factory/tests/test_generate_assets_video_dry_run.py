from __future__ import annotations

import json
from pathlib import Path

from generate_assets import AssetGenerationPlan, dry_run_video_asset


def test_video_dry_run_builds_single_kling_command(tmp_path: Path) -> None:
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
