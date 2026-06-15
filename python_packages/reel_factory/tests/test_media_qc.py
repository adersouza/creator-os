from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from media_qc import inspect_media_qc, media_qc_tools_available


pytestmark = pytest.mark.skipif(not media_qc_tools_available(), reason="ffmpeg/ffprobe unavailable")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_video(path: Path, *, blank: bool = False) -> None:
    source = (
        "color=c=black:s=540x960:r=24:d=2"
        if blank
        else "testsrc2=size=540x960:rate=24:duration=2"
    )
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ]
    )


def test_media_qc_passes_readable_9_16_video(tmp_path: Path) -> None:
    video = tmp_path / "valid.mp4"
    _make_video(video)

    report = inspect_media_qc(video, expected_aspect_ratio="9:16", require_audio=False)

    assert report["schema"] == "reel_factory.media_qc.v1"
    assert report["wouldWrite"] is False
    assert report["passed"] is True
    assert report["checks"]["dimensions"]["aspectRatio"] == "9:16"
    assert report["checks"]["readable_keyframes"]["framesRead"] >= 2


def test_media_qc_flags_blank_near_duplicate_video(tmp_path: Path) -> None:
    video = tmp_path / "blank.mp4"
    _make_video(video, blank=True)

    report = inspect_media_qc(video, expected_aspect_ratio="9:16", require_audio=False)

    assert report["passed"] is False
    assert report["checks"]["blank_frames"]["passed"] is False
    assert report["checks"]["near_duplicate_frames"]["passed"] is False


def test_media_qc_reports_missing_media_without_writes(tmp_path: Path) -> None:
    report = inspect_media_qc(tmp_path / "missing.mp4")

    assert report["passed"] is False
    assert report["error"] == "media_missing"
    assert report["wouldWrite"] is False
