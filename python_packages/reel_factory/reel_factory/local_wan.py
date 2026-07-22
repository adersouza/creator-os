"""Compatibility adapter for the original local Wan worker API.

New code should use :mod:`reel_factory.local_video`.  This small adapter keeps
existing runbooks and imports working while all execution, lineage, and model
verification live in the catalog-driven local engine.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_video import (
    DEFAULT_NEGATIVE_PROMPT,
    LocalVideoRequest,
    LocalVideoUnavailable,
    build_local_video_command,
    probe_local_video,
    run_local_video,
)

MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B"
LOCAL_MODEL_ID = "local_wan22_ti2v_5b_mlx"
LocalWanUnavailable = LocalVideoUnavailable


@dataclass(frozen=True, slots=True)
class LocalWanRequest:
    image_path: Path
    prompt: str
    output_path: Path
    model_dir: Path
    duration_seconds: int = 6
    seed: int = 42
    steps: int = 40
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT


def probe_local_wan(
    *, model_dir: str | Path | None = None, python_executable: str | None = None
) -> dict[str, Any]:
    return probe_local_video(
        LOCAL_MODEL_ID,
        model_dir=model_dir,
        python_executable=python_executable,
    )


def build_local_wan_command(
    request: LocalWanRequest, *, python_executable: str | None = None
) -> list[str]:
    return build_local_video_command(
        _as_local_video_request(request), python_executable=python_executable
    )


def run_local_wan(
    request: LocalWanRequest,
    *,
    dry_run: bool,
    python_executable: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    return run_local_video(
        _as_local_video_request(request),
        dry_run=dry_run,
        python_executable=python_executable,
        runner=runner,
    )


def _as_local_video_request(request: LocalWanRequest) -> LocalVideoRequest:
    return LocalVideoRequest(
        model_id=LOCAL_MODEL_ID,
        image_path=request.image_path,
        prompt=request.prompt,
        output_path=request.output_path,
        model_dir=request.model_dir,
        duration_seconds=request.duration_seconds,
        resolution="720p",
        seed=request.seed,
        steps=request.steps,
        negative_prompt=request.negative_prompt,
    )
