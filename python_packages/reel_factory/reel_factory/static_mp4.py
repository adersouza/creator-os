#!/usr/bin/env python3
"""Render a QC-accepted still as a locked, zero-cost vertical MP4."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_intent import write_audio_intent
from PIL import Image

SCHEMA = "reel_factory.static_mp4_render.v1"
CANVAS_W = 1080
CANVAS_H = 1920
MIN_STILL_W = 720
MIN_STILL_H = 1280
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


@dataclass(frozen=True)
class StaticMp4Request:
    still_path: Path
    output_path: Path
    duration_seconds: float = 5.0
    fps: int = 30
    platform: str = "instagram_reels"
    audio_mode: str = "platform_auto_music"
    allow_upscale: bool = False


def render_static_mp4(
    request: StaticMp4Request, *, dry_run: bool = False
) -> dict[str, Any]:
    still = request.still_path.expanduser().resolve()
    output = request.output_path.expanduser().resolve()
    _validate_request(request, still=still)
    command = _build_ffmpeg_command(request, still=still, output=output)
    quality = _planned_quality(request)
    audio_intent_path = output.with_suffix(output.suffix + ".audio_intent.json")
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        _run(command, timeout=180)
        quality = _quality(output)
        if quality["status"] != "passed":
            raise RuntimeError(f"static MP4 quality failed: {quality}")
        audio_intent_path = write_audio_intent(
            output,
            mode=request.audio_mode,
            platform=request.platform,
            notes=(
                "Locked static MP4; native platform audio remains unresolved until "
                "ThreadsDashboard selection and verification."
            ),
        )
    return {
        "schema": SCHEMA,
        "animationMode": "static_image_mp4",
        "lockedStatic": True,
        "paidGeneration": False,
        "estimatedCostUsd": 0,
        "stillPath": str(still),
        "outputPath": str(output),
        "durationSeconds": request.duration_seconds,
        "audioBurned": False,
        "audioIntentPath": str(audio_intent_path),
        "quality": quality,
        "ffmpegCommand": command,
        "humanReviewRequired": True,
        "dryRun": dry_run,
    }


def _validate_request(request: StaticMp4Request, *, still: Path) -> None:
    if not still.exists() or not still.is_file():
        raise FileNotFoundError(f"still image not found: {still}")
    if request.duration_seconds <= 0 or request.duration_seconds > 60:
        raise ValueError("duration_seconds must be > 0 and <= 60")
    if request.fps <= 0:
        raise ValueError("fps must be positive")
    if request.audio_mode not in {
        "platform_auto_music",
        "native_trending_audio",
        "silent_by_design",
    }:
        raise ValueError("static MP4 audio mode must remain native or silent")
    with Image.open(still) as image:
        width, height = image.size
    if not request.allow_upscale and (width < MIN_STILL_W or height < MIN_STILL_H):
        raise ValueError(
            f"still image is too small for static MP4 ({width}x{height}); "
            "allow upscale only for an explicit low-resolution test"
        )


def _build_ffmpeg_command(
    request: StaticMp4Request, *, still: Path, output: Path
) -> list[str]:
    return [
        FFMPEG,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-loop",
        "1",
        "-framerate",
        str(request.fps),
        "-i",
        str(still),
        "-vf",
        (
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=1080:1920,format=yuv420p"
        ),
        "-t",
        f"{request.duration_seconds:.3f}",
        "-r",
        str(request.fps),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]


def _run(command: list[str], *, timeout: int) -> None:
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(detail[-2000:])


def _quality(output: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        return {
            "status": "failed",
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "durationSeconds": 0.0,
            "warnings": [probe.stderr.strip()],
        }
    data = json.loads(probe.stdout or "{}")
    video = next(
        (item for item in data.get("streams", []) if item.get("codec_type") == "video"),
        {},
    )
    audio = [
        item for item in data.get("streams", []) if item.get("codec_type") == "audio"
    ]
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    duration = _float((data.get("format") or {}).get("duration"))
    warnings: list[str] = []
    if width != CANVAS_W or height != CANVAS_H:
        warnings.append("unexpected_dimensions")
    if fps <= 0:
        warnings.append("missing_frame_rate")
    if duration <= 0:
        warnings.append("missing_duration")
    if audio:
        warnings.append("unexpected_burned_audio")
    if not output.exists() or output.stat().st_size <= 0:
        warnings.append("empty_output")
    return {
        "status": "passed" if not warnings else "failed",
        "width": width,
        "height": height,
        "fps": fps,
        "durationSeconds": round(duration, 3),
        "warnings": warnings,
    }


def _planned_quality(request: StaticMp4Request) -> dict[str, Any]:
    return {
        "status": "planned",
        "width": CANVAS_W,
        "height": CANVAS_H,
        "fps": float(request.fps),
        "durationSeconds": float(request.duration_seconds),
        "warnings": [],
    }


def _parse_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return _float(numerator) / max(_float(denominator), 1.0)
    return _float(value)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--still", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--platform", default="instagram_reels")
    parser.add_argument(
        "--audio-mode",
        choices=["platform_auto_music", "native_trending_audio", "silent_by_design"],
        default="platform_auto_music",
    )
    parser.add_argument("--allow-upscale", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = render_static_mp4(
        StaticMp4Request(
            still_path=Path(args.still),
            output_path=Path(args.out),
            duration_seconds=args.duration,
            fps=args.fps,
            platform=args.platform,
            audio_mode=args.audio_mode,
            allow_upscale=args.allow_upscale,
        ),
        dry_run=not args.apply or args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
