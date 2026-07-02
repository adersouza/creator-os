#!/usr/bin/env python3
"""Zero-cost still-to-reel motion-edit renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audio_intent import write_audio_intent
from audio_mux import mux_audio
from caption_render import render_caption_png
from PIL import Image

from pipeline_contracts import validate_generated_asset_lineage

SCHEMA = "reel_factory.motion_edit_render.v1"
CANVAS_W = 1080
CANVAS_H = 1920
MIN_STILL_W = 720
MIN_STILL_H = 1280
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


@dataclass(frozen=True)
class MotionEditRequest:
    still_path: Path
    output_path: Path
    caption: str
    duration_seconds: float = 5.0
    fps: int = 30
    seed: str = "motion_edit"
    platform: str = "instagram_reels"
    caption_style: str = "ig"
    caption_band: str = "center"
    caption_font: str = "Instagram Sans Condensed"
    audio_mode: str = "platform_auto_music"
    local_audio_path: Path | None = None
    allow_upscale: bool = False


def render_motion_edit(
    request: MotionEditRequest, *, dry_run: bool = False
) -> dict[str, Any]:
    still = request.still_path.expanduser().resolve()
    output = request.output_path.expanduser().resolve()
    _validate_request(request, still=still)
    command = _build_ffmpeg_command(
        request, still=still, output=output, caption_png=_caption_png_path(output)
    )
    result = _result_payload(
        request,
        still=still,
        output=output,
        command=command,
        quality=_planned_quality(request),
        dry_run=dry_run,
    )
    if dry_run:
        _validate_result(result)
        return result

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="motion_edit_") as tmp:
        tmp_dir = Path(tmp)
        caption_png = tmp_dir / f"{output.stem}.caption.png"
        silent_output = (
            output
            if request.local_audio_path is None
            else tmp_dir / f"{output.stem}.silent.mp4"
        )
        render_caption_png(
            request.caption,
            font_family=request.caption_font,
            fonts_dir=Path(__file__).resolve().parent / "fonts",
            color_scheme="light",
            band=request.caption_band,
            style=request.caption_style,
            out_path=caption_png,
            canvas_w=CANVAS_W,
            canvas_h=CANVAS_H,
            renderer="pillow",
        )
        command = _build_ffmpeg_command(
            request, still=still, output=silent_output, caption_png=caption_png
        )
        _run(command, timeout=180)
        if request.local_audio_path is not None:
            mux_audio(
                silent_output,
                request.local_audio_path.expanduser().resolve(),
                out=output,
                overwrite=True,
            )
        quality = _quality(output)
        if quality["status"] != "passed":
            raise RuntimeError(f"motion edit quality failed: {quality}")
    audio_intent_path = _write_audio_intent(request, output)
    lineage_path = _write_lineage(request, still=still, output=output, quality=quality)
    result = _result_payload(
        request,
        still=still,
        output=output,
        command=command,
        quality=quality,
        dry_run=False,
        audio_intent_path=audio_intent_path,
        lineage_path=lineage_path,
    )
    _validate_result(result)
    return result


def _validate_request(request: MotionEditRequest, *, still: Path) -> None:
    if not still.exists() or not still.is_file():
        raise FileNotFoundError(f"still image not found: {still}")
    if request.duration_seconds <= 0 or request.duration_seconds > 60:
        raise ValueError("duration_seconds must be > 0 and <= 60")
    if request.fps <= 0:
        raise ValueError("fps must be positive")
    if request.audio_mode not in {
        "platform_auto_music",
        "native_trending_audio",
        "licensed_music",
        "silent_by_design",
    }:
        raise ValueError(
            "audio_mode must be platform_auto_music, native_trending_audio, licensed_music, or silent_by_design"
        )
    if request.local_audio_path is not None:
        audio = request.local_audio_path.expanduser().resolve()
        if not audio.exists() or not audio.is_file():
            raise FileNotFoundError(f"local audio not found: {audio}")
    with Image.open(still) as image:
        width, height = image.size
    if not request.allow_upscale and (width < MIN_STILL_W or height < MIN_STILL_H):
        raise ValueError(
            f"still image is too small for motion_edit ({width}x{height}); "
            "pass allow_upscale=True only for explicit low-resolution tests"
        )


def _build_ffmpeg_command(
    request: MotionEditRequest, *, still: Path, output: Path, caption_png: Path
) -> list[str]:
    frames = max(1, int(round(request.duration_seconds * request.fps)))
    vf = (
        f"[0:v]{_motion_filter(request, frames)},format=yuv420p[base];"
        "[1:v]format=rgba[cap];"
        "[base][cap]overlay=0:0:format=auto[v]"
    )
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
        "-loop",
        "1",
        "-i",
        str(caption_png),
        "-filter_complex",
        vf,
        "-map",
        "[v]",
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


def _motion_filter(request: MotionEditRequest, frames: int) -> str:
    mode = (
        int(hashlib.sha256(str(request.seed).encode("utf-8")).hexdigest()[:2], 16) % 4
    )
    if mode == 0:
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        x_expr = "(iw-iw/zoom)*on/{frames}"
        y_expr = "ih/2-(ih/zoom/2)"
    elif mode == 2:
        x_expr = "(iw-iw/zoom)*(1-on/{frames})"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "(ih-ih/zoom)*on/{frames}"
    x_expr = x_expr.format(frames=max(1, frames - 1))
    y_expr = y_expr.format(frames=max(1, frames - 1))
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1920,"
        f"zoompan=z=min(zoom+0.0015\\,1.08):x={x_expr}:y={y_expr}:d={frames}:s=1080x1920:fps={request.fps}"
    )


def _caption_png_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".caption.png")


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
    fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    duration = _float((data.get("format") or {}).get("duration"))
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    warnings: list[str] = []
    if width != CANVAS_W or height != CANVAS_H:
        warnings.append("unexpected_dimensions")
    if duration <= 0:
        warnings.append("missing_duration")
    if output.stat().st_size <= 0:
        warnings.append("empty_output")
    return {
        "status": "passed" if not warnings else "failed",
        "width": width,
        "height": height,
        "fps": fps,
        "durationSeconds": round(duration, 3),
        "warnings": warnings,
    }


def _planned_quality(request: MotionEditRequest) -> dict[str, Any]:
    return {
        "status": "planned",
        "width": CANVAS_W,
        "height": CANVAS_H,
        "fps": float(request.fps),
        "durationSeconds": float(request.duration_seconds),
        "warnings": [],
    }


def _write_audio_intent(request: MotionEditRequest, output: Path) -> Path:
    if request.local_audio_path is not None:
        return write_audio_intent(
            output,
            mode="licensed_music",
            platform=request.platform,
            notes="Local operator-provided audio muxed into motion-edit render.",
            audio_selection={
                "source": "local_audio",
                "path": str(request.local_audio_path.expanduser().resolve()),
            },
        )
    return write_audio_intent(
        output,
        mode=request.audio_mode,
        platform=request.platform,
        notes="Motion-edit render stays silent unless an explicit local audio file is supplied.",
    )


def _write_lineage(
    request: MotionEditRequest, *, still: Path, output: Path, quality: dict[str, Any]
) -> Path:
    payload = {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "pipelineTraceId": f"trace_motion_edit_{_text_hash(str(still) + ':' + str(output) + ':' + str(request.seed))}",
        "createdAt": _utc_now(),
        "source": {
            "parentStillPath": str(still),
            "parentStillHash": _sha256_file(still),
        },
        "generation": {
            "tool": "reel_factory.still_to_reel",
            "workflow": "motion_edit_still_to_reel",
            "animationMode": "motion_edit",
            "paidGeneration": False,
            "estimatedCostUsd": 0,
            "models": {},
            "provider": None,
        },
        "render": {
            "outputPath": str(output),
            "durationSeconds": request.duration_seconds,
            "fps": request.fps,
            "captionHash": _text_hash(request.caption),
            "quality": quality,
        },
        "review": {
            "humanReviewRequired": True,
        },
        "assets": {
            "localPaths": {
                "still": str(still),
                "video": str(output),
            },
        },
    }
    validate_generated_asset_lineage(payload)
    path = output.with_suffix(output.suffix + ".generated_asset_lineage.json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _result_payload(
    request: MotionEditRequest,
    *,
    still: Path,
    output: Path,
    command: list[str],
    quality: dict[str, Any],
    dry_run: bool,
    audio_intent_path: Path | None = None,
    lineage_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "animationMode": "motion_edit",
        "paidGeneration": False,
        "estimatedCostUsd": 0,
        "stillPath": str(still),
        "outputPath": str(output),
        "durationSeconds": request.duration_seconds,
        "caption": request.caption,
        "audioIntentPath": str(
            audio_intent_path
            or output.with_suffix(output.suffix + ".audio_intent.json")
        ),
        "lineagePath": str(
            lineage_path
            or output.with_suffix(output.suffix + ".generated_asset_lineage.json")
        ),
        "quality": quality,
        "ffmpegCommand": command,
        "dryRun": dry_run,
    }


def _validate_result(payload: dict[str, Any]) -> None:
    from pipeline_contracts import validate_motion_edit_render

    validate_motion_edit_render(payload)


def _parse_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        return _float(num) / max(_float(den), 1.0)
    return _float(value)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--still", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--caption", required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seed", default="motion_edit")
    parser.add_argument("--platform", default="instagram_reels")
    parser.add_argument("--caption-style", default="ig")
    parser.add_argument("--caption-band", default="center")
    parser.add_argument("--caption-font", default="Instagram Sans Condensed")
    parser.add_argument("--audio-mode", default="platform_auto_music")
    parser.add_argument("--local-audio")
    parser.add_argument("--allow-upscale", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    request = MotionEditRequest(
        still_path=Path(args.still),
        output_path=Path(args.out),
        caption=args.caption,
        duration_seconds=args.duration,
        fps=args.fps,
        seed=args.seed,
        platform=args.platform,
        caption_style=args.caption_style,
        caption_band=args.caption_band,
        caption_font=args.caption_font,
        audio_mode=args.audio_mode,
        local_audio_path=Path(args.local_audio) if args.local_audio else None,
        allow_upscale=args.allow_upscale,
    )
    print(
        json.dumps(
            render_motion_edit(request, dry_run=not args.apply or args.dry_run),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
