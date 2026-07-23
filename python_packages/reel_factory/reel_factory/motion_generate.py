"""CLI boundary for local MLX and authorized WaveSpeed motion generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import requests

from .local_video import LocalVideoRequest, LocalVideoTask, run_local_video
from .video_provider_models import validate_model_request, video_model, video_model_ids
from .wavespeed import (
    WaveSpeedRequest,
    build_wavespeed_spend_scope,
    execute_wavespeed,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate one review-only motion asset; never schedules or publishes."
    )
    parser.add_argument("--model", choices=video_model_ids(), required=True)
    parser.add_argument(
        "--task",
        choices=[
            "text_to_video",
            "image_to_video",
            "audio_image_to_video",
            "keyframe_interpolation",
            "video_retake",
            "video_extend",
        ],
        default=None,
    )
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--last-image", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--generate-audio", action="store_true")
    parser.add_argument("--preserve-audio", action="store_true")
    parser.add_argument("--source-video", type=Path)
    parser.add_argument("--retake-start-frame", type=int)
    parser.add_argument("--retake-end-frame", type=int)
    parser.add_argument("--extend-frames", type=int)
    parser.add_argument("--extend-direction", choices=["before", "after"])
    parser.add_argument("--no-low-ram", action="store_true")
    parser.add_argument("--tile-frames", type=int)
    parser.add_argument("--tile-spatial", type=int)
    parser.add_argument("--reference-image", action="append", type=Path, default=[])
    parser.add_argument("--reference-video", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--cohort-id", default="creator_os_default")
    parser.add_argument("--resolution")
    parser.add_argument("--duration", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--shot-type", choices=["single", "multi"], default="single")
    parser.add_argument("--enable-prompt-expansion", action="store_true")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--lora", type=Path)
    parser.add_argument("--lora-strength", type=float, default=1.0)
    parser.add_argument("--authorization-json", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--benchmark-recipe", type=Path)
    parser.add_argument("--benchmark-recipe-sha256")
    parser.add_argument("--analyzer-registry", type=Path)
    parser.add_argument("--analyzer-registry-sha256")
    parser.add_argument("--local-motion-admission", type=Path)
    parser.add_argument("--local-motion-admission-sha256")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def build_request(args: argparse.Namespace) -> LocalVideoRequest | WaveSpeedRequest:
    model = video_model(args.model)
    resolution = args.resolution or model.default_resolution
    duration = args.duration if args.duration is not None else model.default_duration
    if model.backend == "local_mlx":
        recipe_path = getattr(args, "benchmark_recipe", None)
        registry_path = getattr(args, "analyzer_registry", None)
        recipe_sha = getattr(args, "benchmark_recipe_sha256", None)
        registry_sha = getattr(args, "analyzer_registry_sha256", None)
        admission_path = getattr(args, "local_motion_admission", None)
        admission_sha = getattr(args, "local_motion_admission_sha256", None)
        if any(
            value is None
            for value in (
                recipe_path,
                recipe_sha,
                registry_path,
                registry_sha,
                admission_path,
                admission_sha,
            )
        ):
            raise ValueError(
                "local MLX generation requires path+sha evidence for admission, "
                "benchmark recipe, and analyzer registry"
            )
        benchmark_recipe = _load_bound_json(
            recipe_path, recipe_sha, label="benchmark_recipe"
        )
        analyzer_registry = _load_bound_json(
            registry_path, registry_sha, label="analyzer_registry"
        )
        local_motion_admission = _load_bound_json(
            admission_path, admission_sha, label="local_motion_admission"
        )
        selected_task = cast(LocalVideoTask, args.task or "image_to_video")
        if args.reference_image or args.reference_video:
            raise ValueError("local MLX motion does not accept reference media lists")
        if args.enable_prompt_expansion:
            raise ValueError(
                "local MLX prompt expansion is disabled until expanded text is captured"
            )
        if args.shot_type != "single":
            raise ValueError("local MLX motion does not support --shot-type")
        if (
            sum(
                bool(value)
                for value in (args.audio, args.generate_audio, args.preserve_audio)
            )
            > 1
        ):
            raise ValueError(
                "--audio, --generate-audio, and --preserve-audio are mutually exclusive"
            )
        validate_model_request(
            model,
            resolution=resolution,
            duration=duration,
            has_audio=args.audio is not None,
            has_last_image=args.last_image is not None,
            generate_audio=args.generate_audio,
            task=selected_task,
            has_image=args.image is not None,
            has_lora=args.lora is not None,
        )
        return LocalVideoRequest(
            model_id=model.id,
            image_path=args.image,
            prompt=args.prompt,
            output_path=args.out,
            model_dir=args.model_dir,
            duration_seconds=duration,
            resolution=resolution,
            seed=args.seed,
            steps=args.steps,
            audio_mode=(
                "source"
                if args.audio
                else "generated"
                if args.generate_audio
                else "preserved"
                if args.preserve_audio
                else "none"
            ),
            audio_path=args.audio,
            last_image_path=args.last_image,
            task=selected_task,
            lora_path=args.lora,
            lora_strength=args.lora_strength,
            source_video_path=args.source_video,
            retake_start_frame=args.retake_start_frame,
            retake_end_frame=args.retake_end_frame,
            extend_frames=args.extend_frames,
            extend_direction=args.extend_direction or "after",
            low_ram=not args.no_low_ram,
            tile_frames=args.tile_frames if args.tile_frames is not None else 1,
            tile_spatial=args.tile_spatial if args.tile_spatial is not None else 2,
            benchmark_recipe=benchmark_recipe,
            analyzer_registry=analyzer_registry,
            execution_context="campaign_generation",
            local_motion_admission=local_motion_admission,
        )
    if args.model_dir is not None:
        raise ValueError("--model-dir applies only to local MLX models")
    if args.lora is not None or args.lora_strength != 1.0:
        raise ValueError("--lora applies only to local MLX models")
    if args.task is not None:
        raise ValueError("--task override applies only to local MLX models")
    if args.generate_audio:
        raise ValueError("--generate-audio applies only to local LTX models")
    if args.preserve_audio:
        raise ValueError("--preserve-audio applies only to local LTX retakes")
    if args.source_video is not None:
        raise ValueError("--source-video applies only to local LTX editing")
    if (
        any(
            value is not None
            for value in (
                args.retake_start_frame,
                args.retake_end_frame,
                args.extend_frames,
                args.extend_direction,
                args.tile_frames,
                args.tile_spatial,
            )
        )
        or args.no_low_ram
    ):
        raise ValueError("local MLX editing and memory controls require a local model")
    if args.steps is not None:
        raise ValueError("--steps applies only to local MLX models")
    if any(
        getattr(args, name, None) is not None
        for name in (
            "benchmark_recipe",
            "benchmark_recipe_sha256",
            "analyzer_registry",
            "analyzer_registry_sha256",
            "local_motion_admission",
            "local_motion_admission_sha256",
        )
    ):
        raise ValueError("benchmark evidence applies only to local MLX models")
    return WaveSpeedRequest(
        model_id=model.id,
        prompt=args.prompt,
        output_path=args.out,
        image_path=args.image,
        last_image_path=args.last_image,
        audio_path=args.audio,
        reference_image_paths=tuple(args.reference_image),
        reference_video_paths=tuple(args.reference_video),
        resolution=resolution,
        duration_seconds=duration or None,
        seed=args.seed,
        enable_prompt_expansion=args.enable_prompt_expansion,
        shot_type=args.shot_type,
    )


def _load_bound_json(path: Any, expected_sha256: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(path, Path):
        raise ValueError(f"{label}_path_missing")
    digest = str(expected_sha256 or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{label}_sha256_invalid")
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label}_file_missing_or_unsafe")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise ValueError(f"{label}_file_missing_or_unsafe")
    payload_bytes = resolved.read_bytes()
    if hashlib.sha256(payload_bytes).hexdigest() != digest:
        raise ValueError(f"{label}_sha256_mismatch")
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label}_json_object_required")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    if isinstance(request, LocalVideoRequest):
        result = run_local_video(request, dry_run=args.dry_run)
        return {
            "schema": "reel_factory.motion_generation_result.v1",
            "modelId": args.model,
            "backend": "local_mlx",
            "dryRun": args.dry_run,
            "paidGeneration": False,
            "providerCalls": 0,
            "result": result,
        }

    scope = build_wavespeed_spend_scope(
        request, campaign=args.campaign, cohort_id=args.cohort_id
    )
    if args.dry_run:
        return {
            "schema": "reel_factory.motion_generation_result.v1",
            "modelId": args.model,
            "backend": "wavespeed",
            "dryRun": True,
            "paidGeneration": True,
            "providerCalls": 0,
            "spendScope": scope,
            "result": None,
        }
    if args.authorization_json is None or args.evidence_dir is None:
        raise PermissionError(
            "WaveSpeed apply requires --authorization-json and --evidence-dir"
        )
    try:
        authorization = json.loads(
            args.authorization_json.expanduser().resolve().read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("WaveSpeed authorization JSON is unreadable") from exc
    if not isinstance(authorization, dict):
        raise ValueError("WaveSpeed authorization JSON must be an object")
    from os import environ

    secret = environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    result = execute_wavespeed(
        request,
        campaign=args.campaign,
        cohort_id=args.cohort_id,
        authorization=authorization,
        secret=secret,
        evidence_dir=args.evidence_dir,
    )
    return {
        "schema": "reel_factory.motion_generation_result.v1",
        "modelId": args.model,
        "backend": "wavespeed",
        "dryRun": False,
        "paidGeneration": True,
        "providerCalls": 1,
        "spendScope": scope,
        "result": result,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        payload = run(_parser().parse_args(argv))
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        requests.RequestException,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
