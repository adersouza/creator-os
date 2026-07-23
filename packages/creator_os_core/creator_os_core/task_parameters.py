"""Canonical, versioned local-video inference parameter material."""

from __future__ import annotations

import hashlib
import json
from typing import Any

DEFAULT_LOCAL_VIDEO_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted face, deformed hands, extra fingers, "
    "duplicate person, text, subtitles, watermark, interface elements, abrupt cuts"
)


def canonical_task_parameter_material(
    *,
    task_kind: str,
    prompt: str,
    negative_prompt: str | None,
    negative_prompt_applied: bool,
    seed: int,
    duration_seconds: int | None,
    resolution: str,
    geometry_source: str,
    geometry_probe: dict[str, str] | None,
    width: int,
    height: int,
    fps: str,
    frame_count: int | None,
    steps: int,
    requested_steps: int | None,
    audio_mode: str,
    pipeline: str,
    guide_scale: str | None,
    scheduler: str | None,
    tiling_mode: str | None,
    trim_first_frames: int,
    retake_start_frame: int | None,
    retake_end_frame: int | None,
    extend_frames: int | None,
    extend_direction: str | None,
    low_ram: bool,
    tile_frames: int,
    tile_spatial: int,
    lora_sha256: str | None,
    lora_scale: float | None,
    commercial_use: bool,
    commercial_annual_revenue_usd: int | None,
    overlays_exist: bool,
    preserve_audio: bool,
) -> dict[str, Any]:
    """Return the sole normalized material hashed by Arena and execution gates."""

    normalized_prompt = " ".join(str(prompt or "").split())
    if not normalized_prompt:
        raise ValueError("task_parameter_prompt_missing")
    if negative_prompt_applied:
        normalized_negative = " ".join(str(negative_prompt or "").split())
        if not normalized_negative:
            raise ValueError("task_parameter_negative_prompt_missing")
    else:
        normalized_negative = None
    if min(width, height, steps) <= 0:
        raise ValueError("task_parameter_positive_integer_required")
    try:
        fps_numerator, fps_denominator = str(fps).split("/", 1)
        if int(fps_numerator) <= 0 or int(fps_denominator) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("task_parameter_fps_invalid") from exc
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("task_parameter_positive_integer_required")
    if frame_count is not None and frame_count <= 0:
        raise ValueError("task_parameter_positive_integer_required")
    if trim_first_frames < 0:
        raise ValueError("task_parameter_trim_first_frames_invalid")
    if pipeline in {"wan22_i2v", "wan22_ti2v"} and (
        frame_count is None or (frame_count - 1) % 4 != 0
    ):
        raise ValueError("task_parameter_wan_frame_geometry_invalid")
    if pipeline == "wan22_i2v" and trim_first_frames != 0:
        raise ValueError("task_parameter_wan_i2v_trim_unsupported")
    if seed < 0:
        raise ValueError("task_parameter_seed_invalid")
    if not str(resolution or "").strip() or not str(pipeline or "").strip():
        raise ValueError("task_parameter_model_shape_missing")
    if audio_mode not in {"none", "source", "generated", "preserved"}:
        raise ValueError("task_parameter_audio_mode_invalid")
    if preserve_audio is not (audio_mode == "preserved"):
        raise ValueError("task_parameter_preserve_audio_mismatch")
    if not 1 <= tile_frames <= 8 or not 1 <= tile_spatial <= 4:
        raise ValueError("task_parameter_tile_setting_invalid")
    if lora_sha256 is None:
        if lora_scale is not None:
            raise ValueError("task_parameter_lora_scale_without_identity")
        lora = None
    else:
        if not _is_sha256(lora_sha256) or lora_scale is None:
            raise ValueError("task_parameter_lora_identity_invalid")
        if not 0.0 < float(lora_scale) <= 2.0:
            raise ValueError("task_parameter_lora_scale_invalid")
        lora = {"sha256": lora_sha256, "scale": float(lora_scale)}
    if commercial_annual_revenue_usd is not None and (
        commercial_annual_revenue_usd < 0
    ):
        raise ValueError("task_parameter_commercial_revenue_invalid")
    edit_task = task_kind in {"video_retake", "video_extend"}
    if edit_task:
        if (
            duration_seconds is not None
            or frame_count is not None
            or geometry_source != "source_video"
            or not isinstance(geometry_probe, dict)
            or set(geometry_probe) != {"executable", "sha256"}
            or not str(geometry_probe.get("executable") or "").strip()
            or not _is_sha256(str(geometry_probe.get("sha256") or ""))
        ):
            raise ValueError("task_parameter_edit_geometry_not_source_derived")
    elif (
        duration_seconds is None
        or frame_count is None
        or geometry_source != "model"
        or geometry_probe is not None
    ):
        raise ValueError("task_parameter_generation_geometry_missing")
    if task_kind == "video_retake":
        if (
            retake_start_frame is None
            or retake_end_frame is None
            or retake_start_frame < 0
            or retake_end_frame <= retake_start_frame
            or extend_frames is not None
        ):
            raise ValueError("task_parameter_retake_controls_invalid")
        normalized_direction = None
    elif task_kind == "video_extend":
        if (
            extend_frames is None
            or extend_frames <= 0
            or retake_start_frame is not None
            or retake_end_frame is not None
            or extend_direction not in {"before", "after"}
        ):
            raise ValueError("task_parameter_extend_controls_invalid")
        normalized_direction = extend_direction
    else:
        if (
            retake_start_frame is not None
            or retake_end_frame is not None
            or extend_frames is not None
        ):
            raise ValueError("task_parameter_edit_controls_forbidden")
        normalized_direction = None
    benchmark_cell = {
        "taskKind": task_kind,
        "prompt": normalized_prompt,
        "seed": seed,
        "durationSeconds": duration_seconds,
        "resolution": str(resolution).strip(),
        "requestedSteps": requested_steps,
        "audioMode": audio_mode,
        "retakeStartFrame": retake_start_frame,
        "retakeEndFrame": retake_end_frame,
        "extendFrames": extend_frames,
        "extendDirection": normalized_direction,
        "preserveAudio": preserve_audio,
    }
    effective_execution = {
        "negativePrompt": normalized_negative,
        "negativePromptApplied": negative_prompt_applied,
        "geometrySource": geometry_source,
        "geometryProbe": geometry_probe,
        "width": width,
        "height": height,
        "fps": f"{int(fps_numerator)}/{int(fps_denominator)}",
        "frameCount": frame_count,
        "steps": steps,
        "pipeline": str(pipeline).strip(),
        "guideScale": guide_scale,
        "scheduler": scheduler,
        "tilingMode": tiling_mode,
        "trimFirstFrames": trim_first_frames,
        "lowRam": low_ram,
        "tileFrames": tile_frames,
        "tileSpatial": tile_spatial,
        "lora": lora,
    }
    policy_context = {
        "commercialUse": commercial_use,
        "commercialAnnualRevenueUsd": commercial_annual_revenue_usd,
        "overlaysExist": overlays_exist,
    }
    return {
        "schema": "creator_os.local_video_task_parameters.v1",
        "benchmarkCell": benchmark_cell,
        "effectiveExecution": effective_execution,
        "policyContext": policy_context,
    }


def task_parameter_fingerprint(material: dict[str, Any]) -> str:
    encoded = json.dumps(
        material, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def benchmark_task_parameter_fingerprint(material: dict[str, Any]) -> str:
    cell = material.get("benchmarkCell")
    if not isinstance(cell, dict):
        raise ValueError("task_parameter_benchmark_cell_missing")
    return task_parameter_fingerprint(cell)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
