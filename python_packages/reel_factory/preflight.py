"""Pre-render source and caption readiness checks."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreflightWarning:
    code: str
    message: str
    severity: str = "warning"


def check_clip_readiness(
    video: Path,
    cap_set: Any,
    *,
    ffprobe: str,
    min_height: int = 720,
    min_duration: float = 2.0,
    max_duration: float = 120.0,
) -> list[PreflightWarning]:
    warnings: list[PreflightWarning] = []
    hooks = getattr(cap_set, "hooks", []) if cap_set is not None else []
    if not hooks:
        warnings.append(PreflightWarning("no_hooks", f"{video.stem} has no hooks"))
    if not video.exists() or video.stat().st_size == 0:
        return warnings + [PreflightWarning("missing_source", f"{video.name} is missing or empty", "error")]

    try:
        meta = _probe_video(video, ffprobe)
    except Exception as e:
        return warnings + [PreflightWarning("probe_failed", f"{video.name} could not be probed: {e}", "error")]

    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    duration = float(meta.get("duration") or 0.0)
    codec = str(meta.get("codec_name") or "")
    if not codec:
        warnings.append(PreflightWarning("missing_codec", f"{video.name} has no readable video codec", "error"))
    if min(width, height) < min_height:
        warnings.append(PreflightWarning(
            "low_resolution",
            f"{video.name} is {width}x{height}; shortest side is below {min_height}px",
        ))
    if duration < min_duration:
        warnings.append(PreflightWarning("too_short", f"{video.name} is only {duration:.2f}s"))
    if duration > max_duration:
        warnings.append(PreflightWarning("too_long", f"{video.name} is {duration:.1f}s"))
    return warnings


def _probe_video(video: Path, ffprobe: str) -> dict[str, str]:
    out = subprocess.check_output([
        ffprobe, "-v", "0",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name:format=duration",
        "-of", "default=nw=1:nk=0",
        str(video),
    ], stderr=subprocess.STDOUT).decode("utf-8", errors="replace")
    data: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data
