from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from audio_intent import read_audio_intent
from PIL import Image
from still_to_reel import MotionEditRequest, render_motion_edit


def _still(path: Path, *, size: tuple[int, int] = (1080, 1920)) -> Path:
    Image.new("RGB", size, (120, 92, 80)).save(path)
    return path


def _tone(path: Path) -> Path:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "aac",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg audio fixture unavailable: {result.stderr[-200:]}")
    return path


def _probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_read_frames:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"ffprobe video fixture unavailable: {result.stderr[-200:]}")
    return json.loads(result.stdout or "{}")


def test_motion_edit_dry_run_is_zero_cost_and_no_paid_command(tmp_path: Path) -> None:
    still = _still(tmp_path / "still.png")
    out = tmp_path / "out.mp4"

    result = render_motion_edit(
        MotionEditRequest(
            still_path=still, output_path=out, caption="same still, new motion"
        ),
        dry_run=True,
    )

    assert result["schema"] == "reel_factory.motion_edit_render.v1"
    assert result["animationMode"] == "motion_edit"
    assert result["estimatedCostUsd"] == 0
    assert result["paidGeneration"] is False
    assert result["quality"]["status"] == "planned"
    command_text = " ".join(result["ffmpegCommand"]).lower()
    assert "higgsfield" not in command_text
    assert "kling" not in command_text
    assert not out.exists()


def test_motion_edit_apply_renders_mp4_and_sidecars(tmp_path: Path) -> None:
    still = _still(tmp_path / "still.png")
    out = tmp_path / "out.mp4"

    result = render_motion_edit(
        MotionEditRequest(
            still_path=still,
            output_path=out,
            caption="caption overlay here",
            duration_seconds=1,
            fps=12,
            seed="acct_a",
            allow_upscale=False,
        ),
        dry_run=False,
    )

    assert out.exists()
    assert result["quality"]["status"] == "passed"
    assert result["quality"]["width"] == 1080
    assert result["quality"]["height"] == 1920
    probe = _probe_video(out)
    stream = probe["streams"][0]
    duration = float(probe["format"]["duration"])
    frame_count = int(stream.get("nb_read_frames") or 0)
    assert stream["width"] == 1080
    assert stream["height"] == 1920
    assert stream["width"] / stream["height"] == 9 / 16
    assert 0.9 <= duration <= 1.2
    assert frame_count >= 10
    audio_intent = read_audio_intent(out)
    assert audio_intent is not None
    assert audio_intent["mode"] == "platform_auto_music"
    lineage = json.loads(Path(result["lineagePath"]).read_text(encoding="utf-8"))
    assert lineage["generation"]["workflow"] == "motion_edit_still_to_reel"
    assert lineage["generation"]["paidGeneration"] is False
    assert lineage["generation"]["models"] == {}
    assert lineage["review"]["humanReviewRequired"] is True


def test_motion_edit_missing_still_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="still image not found"):
        render_motion_edit(
            MotionEditRequest(
                still_path=tmp_path / "missing.png",
                output_path=tmp_path / "out.mp4",
                caption="x",
            ),
            dry_run=True,
        )


def test_motion_edit_low_resolution_requires_explicit_upscale(tmp_path: Path) -> None:
    still = _still(tmp_path / "small.png", size=(320, 480))

    with pytest.raises(ValueError, match="too small"):
        render_motion_edit(
            MotionEditRequest(
                still_path=still, output_path=tmp_path / "out.mp4", caption="x"
            ),
            dry_run=True,
        )

    result = render_motion_edit(
        MotionEditRequest(
            still_path=still,
            output_path=tmp_path / "out.mp4",
            caption="x",
            allow_upscale=True,
        ),
        dry_run=True,
    )

    assert result["quality"]["status"] == "planned"


def test_motion_edit_optional_local_audio_is_explicit_licensed_music(
    tmp_path: Path,
) -> None:
    still = _still(tmp_path / "still.png")
    audio = _tone(tmp_path / "tone.m4a")
    out = tmp_path / "with_audio.mp4"

    result = render_motion_edit(
        MotionEditRequest(
            still_path=still,
            output_path=out,
            caption="local audio only when explicit",
            duration_seconds=1,
            fps=12,
            local_audio_path=audio,
            audio_mode="licensed_music",
        ),
        dry_run=False,
    )

    audio_intent = read_audio_intent(out)
    assert audio_intent is not None
    assert audio_intent["mode"] == "licensed_music"
    assert audio_intent["audio_selection"]["source"] == "local_audio"
    assert "native_trending_audio" not in json.dumps(audio_intent)
    assert result["quality"]["status"] == "passed"
