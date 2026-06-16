from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from audio_intent import read_audio_intent
from audio_mux import audio_library_health, audio_stream_count
from media_qc import inspect_media_qc, media_qc_tools_available
from photo_reel import build_photo_reel_ffmpeg_cmd, create_photo_reel


pytestmark = pytest.mark.skipif(not media_qc_tools_available(), reason="ffmpeg/ffprobe unavailable")


def _make_image(path: Path) -> None:
    image = Image.new("RGB", (900, 1400), color=(214, 164, 136))
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 120, 820, 1280), fill=(232, 196, 172))
    draw.ellipse((330, 150, 570, 390), fill=(128, 78, 60))
    draw.rectangle((260, 450, 650, 1080), fill=(77, 142, 204))
    draw.rectangle((120, 1160, 780, 1300), fill=(245, 238, 226))
    image.save(path)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def test_build_photo_reel_command_is_vertical_silent_mp4(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    out = tmp_path / "out.mp4"

    cmd = build_photo_reel_ffmpeg_cmd(image=image, out=out, duration=5, motion="hold")

    joined = " ".join(cmd)
    assert "-loop 1" in joined
    assert str(image) in cmd
    assert str(out) in cmd
    assert "crop=1080:1920" in joined
    assert "-an" in cmd


def test_create_photo_reel_writes_native_trending_audio_intent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    audio_source = root / "project_data" / "audio_sources" / "tiktok_cml_trending.json"
    audio_source.parent.mkdir(parents=True)
    audio_source.write_text(json.dumps({
        "tracks": [
            {"track_id": "trend_1", "track_name": "Creator Spark", "trend_rank": 1, "tags": ["fashion", "pop"]},
        ]
    }), encoding="utf-8")
    image = tmp_path / "source.jpg"
    out = tmp_path / "photo_reel.mp4"
    _make_image(image)

    result = create_photo_reel(
        image=image,
        out=out,
        root=root,
        duration=2.0,
        motion="slow_zoom",
        audio_mode="native_trending",
        seed="photo-reel-test",
    )

    qc = inspect_media_qc(out, expected_aspect_ratio="9:16", require_audio=False)
    intent = read_audio_intent(out)
    assert out.exists()
    assert qc["passed"] is True
    assert result["audioMode"] == "native_trending"
    assert result["draftExported"] == 0
    assert result["scheduled"] == 0
    assert result["published"] == 0
    assert result["writesProductionState"] is False
    assert intent is not None
    assert intent["mode"] == "native_trending_audio"
    assert intent["audio_selection"]["track_id"] == "trend_1"
    assert Path(result["lineagePath"]).exists()


def test_create_photo_reel_can_mux_local_audio(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")
    image = tmp_path / "source.jpg"
    audio = tmp_path / "tone.wav"
    out = tmp_path / "photo_reel_audio.mp4"
    _make_image(image)
    _run([
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1.2",
        "-y",
        str(audio),
    ])

    result = create_photo_reel(
        image=image,
        out=out,
        duration=2.0,
        motion="slow_zoom",
        audio_mode="local_mux",
        audio_file=audio,
    )

    qc = inspect_media_qc(out, expected_aspect_ratio="9:16", require_audio=True)
    assert out.exists()
    assert audio_stream_count(out) == 1
    assert qc["passed"] is True
    assert result["audioMode"] == "local_mux"
    assert not out.with_suffix(out.suffix + ".audio_intent.json").exists()


def test_audio_library_health_reports_empty_local_mux(tmp_path: Path) -> None:
    result = audio_library_health(tmp_path)

    assert result["trackCount"] == 0
    assert result["nativeAudioIntentReady"] is True
    assert result["localMuxReady"] is False
    assert result["blockingReason"] == "audio_library_empty"
    assert result["wouldWriteProductionState"] is False
