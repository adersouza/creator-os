"""CLI boundary for local Wan and authorized WaveSpeed motion generation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

from .local_wan import LocalWanRequest, run_local_wan
from .video_provider_models import video_model, video_model_ids
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
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--last-image", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--reference-image", action="append", type=Path, default=[])
    parser.add_argument("--reference-video", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--cohort-id", default="creator_os_default")
    parser.add_argument("--resolution")
    parser.add_argument("--duration", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--shot-type", choices=["single", "multi"], default="single")
    parser.add_argument("--enable-prompt-expansion", action="store_true")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--authorization-json", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def build_request(args: argparse.Namespace) -> LocalWanRequest | WaveSpeedRequest:
    model = video_model(args.model)
    resolution = args.resolution or model.default_resolution
    duration = args.duration if args.duration is not None else model.default_duration
    if model.backend == "local_mlx":
        if args.image is None:
            raise ValueError("local Wan requires --image")
        if (
            args.last_image
            or args.audio
            or args.reference_image
            or args.reference_video
        ):
            raise ValueError("local Wan accepts one image only")
        if resolution != "720p":
            raise ValueError("local Wan supports only --resolution 720p")
        if args.enable_prompt_expansion:
            raise ValueError("local Wan does not support --enable-prompt-expansion")
        if args.shot_type != "single":
            raise ValueError("local Wan does not support --shot-type")
        model_dir = args.model_dir or (
            Path.home() / ".creator-os/models/Wan2.2-TI2V-5B-MLX"
        )
        return LocalWanRequest(
            image_path=args.image,
            prompt=args.prompt,
            output_path=args.out,
            model_dir=model_dir,
            duration_seconds=duration,
            seed=args.seed,
            steps=args.steps,
        )
    if args.model_dir is not None:
        raise ValueError("--model-dir applies only to local Wan")
    if args.steps != 40:
        raise ValueError("--steps applies only to local Wan")
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    if isinstance(request, LocalWanRequest):
        result = run_local_wan(request, dry_run=args.dry_run)
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
