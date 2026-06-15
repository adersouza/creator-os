"""Read-only media QC helpers for deterministic proof fixtures.

This module does not approve, reject, mutate, register, schedule, or publish
assets. It only inspects local media files and returns machine-readable
evidence that tests and review tools can consume.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import imagehash
from PIL import Image, ImageStat


def inspect_media_qc(
    path: str | Path,
    *,
    expected_aspect_ratio: str | None = None,
    require_audio: bool | None = None,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    """Inspect a media file without changing it.

    The returned shape is intentionally plain JSON so it can be reused by CLI
    smoke tests, future proof bundles, or dashboard fixtures without importing
    Python objects.
    """

    media_path = Path(path)
    checks: dict[str, dict[str, Any]] = {}
    if not media_path.exists():
        return _report(media_path, checks, passed=False, error="media_missing")

    probe = _ffprobe(media_path, ffprobe=ffprobe)
    video_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]

    if not video_stream:
        checks["video_stream"] = {"passed": False, "reason": "video_stream_missing"}
        return _report(media_path, checks, probe=probe, passed=False)

    width = _int(video_stream.get("width"))
    height = _int(video_stream.get("height"))
    duration = _duration_seconds(probe, video_stream)
    has_audio = bool(audio_streams)

    checks["duration"] = {
        "passed": bool(duration and duration > 0),
        "seconds": duration,
    }
    checks["dimensions"] = {
        "passed": bool(width and height and width > 0 and height > 0),
        "width": width,
        "height": height,
        "aspectRatio": _aspect_ratio(width, height),
    }
    checks["codec"] = {
        "passed": bool(video_stream.get("codec_name")),
        "codec": video_stream.get("codec_name") or "",
    }
    if expected_aspect_ratio:
        checks["aspect_ratio"] = {
            "passed": _aspect_ratio(width, height) == expected_aspect_ratio,
            "expected": expected_aspect_ratio,
            "observed": _aspect_ratio(width, height),
        }
    if require_audio is not None:
        checks["audio_presence"] = {
            "passed": has_audio is require_audio,
            "expected": require_audio,
            "observed": has_audio,
        }

    frame_result = _sample_frames(media_path, duration=duration, ffmpeg=ffmpeg)
    checks["readable_keyframes"] = {
        "passed": frame_result["framesRead"] > 0,
        "framesRead": frame_result["framesRead"],
    }
    checks["blank_frames"] = {
        "passed": not frame_result["blankFrameDetected"],
        "blankFrameDetected": frame_result["blankFrameDetected"],
        "blankFrameIndexes": frame_result["blankFrameIndexes"],
    }
    checks["near_duplicate_frames"] = {
        "passed": not frame_result["nearDuplicateFrames"],
        "nearDuplicateFrames": frame_result["nearDuplicateFrames"],
        "maxHashDistance": frame_result["maxHashDistance"],
    }

    return _report(
        media_path,
        checks,
        probe=probe,
        passed=all(check.get("passed") is True for check in checks.values()),
    )


def _ffprobe(path: Path, *, ffprobe: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout or "{}")


def _sample_frames(path: Path, *, duration: float | None, ffmpeg: str) -> dict[str, Any]:
    timestamps = _sample_timestamps(duration)
    with tempfile.TemporaryDirectory(prefix="creator_os_media_qc_") as tmp_dir:
        tmp = Path(tmp_dir)
        frames: list[Path] = []
        for index, timestamp in enumerate(timestamps):
            out = tmp / f"frame_{index:02d}.png"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-y",
                    str(out),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                frames.append(out)

        hashes = []
        blank_indexes = []
        for index, frame in enumerate(frames):
            with Image.open(frame) as image:
                rgb = image.convert("RGB")
                hashes.append(imagehash.phash(rgb))
                if _is_blank(rgb):
                    blank_indexes.append(index)

        distances = [
            hashes[a] - hashes[b]
            for a in range(len(hashes))
            for b in range(a + 1, len(hashes))
        ]
        max_distance = max(distances) if distances else None
        return {
            "framesRead": len(frames),
            "blankFrameDetected": bool(blank_indexes),
            "blankFrameIndexes": blank_indexes,
            "nearDuplicateFrames": bool(distances) and (max_distance or 0) <= 2,
            "maxHashDistance": max_distance,
        }


def _sample_timestamps(duration: float | None) -> list[float]:
    if not duration or duration <= 0:
        return [0.0]
    end = max(duration - 0.1, 0.0)
    return sorted({0.0, round(duration / 2, 3), round(end, 3)})


def _is_blank(image: Image.Image) -> bool:
    stat = ImageStat.Stat(image)
    channel_stddev = stat.stddev or [0.0]
    channel_mean = stat.mean or [0.0]
    return max(channel_stddev) < 2.0 or max(channel_mean) < 4.0 or min(channel_mean) > 251.0


def _duration_seconds(probe: dict[str, Any], video_stream: dict[str, Any]) -> float | None:
    raw = video_stream.get("duration") or (probe.get("format") or {}).get("duration")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _report(
    path: Path,
    checks: dict[str, dict[str, Any]],
    *,
    passed: bool,
    probe: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "reel_factory.media_qc.v1",
        "path": str(path),
        "passed": passed,
        "checks": checks,
        "wouldWrite": False,
    }
    if probe is not None:
        report["probeSummary"] = _probe_summary(probe)
    if error:
        report["error"] = error
    return report


def _probe_summary(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams") or []
    return {
        "streamCount": len(streams),
        "videoStreamCount": sum(1 for stream in streams if stream.get("codec_type") == "video"),
        "audioStreamCount": sum(1 for stream in streams if stream.get("codec_type") == "audio"),
    }


def media_qc_tools_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
