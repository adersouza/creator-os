from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from reel_factory.static_mp4 import StaticMp4Request, render_static_mp4


def _still(path: Path) -> Path:
    Image.new("RGB", (1152, 2048), color=(110, 90, 80)).save(path)
    return path


def test_static_mp4_dry_run_is_locked_free_and_silent(tmp_path: Path) -> None:
    still = _still(tmp_path / "still.png")
    output = tmp_path / "static.mp4"

    result = render_static_mp4(
        StaticMp4Request(still_path=still, output_path=output), dry_run=True
    )

    assert result["animationMode"] == "static_image_mp4"
    assert result["lockedStatic"] is True
    assert result["paidGeneration"] is False
    assert result["estimatedCostUsd"] == 0
    assert result["audioBurned"] is False
    assert result["quality"]["status"] == "planned"
    command = result["ffmpegCommand"]
    assert "zoompan" not in " ".join(command)
    assert "-an" in command
    assert command[command.index("-t") + 1] == "5.000"
    assert not output.exists()


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)
def test_static_mp4_apply_renders_and_writes_native_audio_intent(
    tmp_path: Path,
) -> None:
    still = _still(tmp_path / "still.png")
    output = tmp_path / "static.mp4"

    result = render_static_mp4(
        StaticMp4Request(still_path=still, output_path=output), dry_run=False
    )

    assert result["quality"] == {
        "status": "passed",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "durationSeconds": 5.0,
        "warnings": [],
    }
    assert output.is_file() and output.stat().st_size > 0
    intent = json.loads(Path(result["audioIntentPath"]).read_text(encoding="utf-8"))
    assert intent["schema"] == "pipeline.audio_intent.v1"
    assert intent["mode"] == "platform_auto_music"
    assert intent["gates"]["allow_draft_export"] is True
    assert intent["gates"]["allow_publish"] is False
