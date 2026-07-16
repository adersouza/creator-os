"""Generated image and video QC helpers for provider output."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def generated_image_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    creator: str | None = None,
    identity_provider: Any | None = None,
    vision_call=None,
    assess_image_call: Callable[..., dict[str, Any]],
    identity_call: Callable[..., dict[str, Any]],
    is_postable_call: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    image_items = [
        (key, Path(value))
        for key, value in sorted(local_paths.items())
        if key == "image" or key.startswith("variation_")
    ]
    if not image_items:
        return {
            "schema": "reel_factory.generated_image_qc.v1",
            "status": "failed" if required else "skipped",
            "reason": "no_downloaded_images",
            "results": [],
        }
    results = []
    for key, path in image_items:
        assessment = assess_image_call(path, root=root, vision_call=vision_call)
        identity = (
            identity_call(path, creator=creator, root=root, provider=identity_provider)
            if creator
            else {
                "schema": "reel_factory.identity_verification.v1",
                "creator": "",
                "status": "unavailable",
                "score": 0.0,
                "threshold": 0.42,
                "provider": "unavailable",
                "referenceSetId": "",
                "failureReason": "creator_missing",
            }
        )
        identity_postable = identity.get("status") == "passed"
        results.append(
            {
                "key": key,
                "path": str(path),
                "postable": is_postable_call(assessment) and identity_postable,
                "identityVerification": identity,
                **assessment,
            }
        )
    return {
        "schema": "reel_factory.generated_image_qc.v1",
        "status": "passed" if all(row["postable"] for row in results) else "failed",
        "results": results,
    }


def generated_image_qc_failure_reason(qc: dict[str, Any]) -> str:
    for row in qc.get("results") or []:
        if not isinstance(row, dict) or row.get("postable"):
            continue
        identity = row.get("identityVerification")
        if isinstance(identity, dict) and identity.get("status") != "passed":
            reason = identity.get("failureReason") or "identity verification failed"
            return f"generated image failed identity QC: {reason}"
        exposure = row.get("exposure")
        if isinstance(exposure, dict) and not exposure.get("safe", True):
            issues = exposure.get("issues") or []
            return "generated image failed exposure QC" + (
                f": {', '.join(str(item) for item in issues)}" if issues else ""
            )
        anatomy = row.get("anatomy")
        if isinstance(anatomy, dict) and not anatomy.get("plausible", True):
            defects = anatomy.get("defects") or []
            return "generated image failed anatomy QC" + (
                f": {', '.join(str(item) for item in defects)}" if defects else ""
            )
    return "generated image failed anatomy/exposure/identity QC"


def generated_video_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    vision_call=None,
    frame_sampler=None,
    assess_image_call: Callable[..., dict[str, Any]],
    is_postable_call: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    video_items = [
        (key, Path(value))
        for key, value in sorted(local_paths.items())
        if key == "video"
    ]
    if not video_items:
        return {
            "schema": "reel_factory.generated_video_qc.v1",
            "status": "failed" if required else "skipped",
            "reason": "no_downloaded_video",
            "results": [],
        }
    results = []
    for key, path in video_items:
        try:
            frames = (
                [Path(frame) for frame in frame_sampler(path)]
                if frame_sampler
                else sample_video_frames(path)
            )
        except Exception as exc:
            results.append(
                {
                    "key": key,
                    "path": str(path),
                    "postable": False,
                    "frames": [],
                    "error": f"video frame sampling failed: {exc}",
                }
            )
            continue
        frame_results = []
        for frame in frames:
            assessment = assess_image_call(frame, root=root, vision_call=vision_call)
            frame_results.append(
                {
                    "path": str(frame),
                    "postable": is_postable_call(assessment),
                    **assessment,
                }
            )
        results.append(
            {
                "key": key,
                "path": str(path),
                "postable": bool(frame_results)
                and all(row["postable"] for row in frame_results),
                "frames": frame_results,
            }
        )
    return {
        "schema": "reel_factory.generated_video_qc.v1",
        "status": "passed" if all(row["postable"] for row in results) else "failed",
        "results": results,
    }


def sample_video_frames(path: Path) -> list[Path]:
    from .sscd_video import extract_frames

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        frames = extract_frames(path, temp_dir)
        copied: list[Path] = []
        for idx, frame in enumerate(frames):
            target = path.with_suffix(path.suffix + f".qc_frame_{idx}.jpg")
            target.write_bytes(frame.read_bytes())
            copied.append(target)
        return copied


def generated_video_qc_failure_reason(qc: dict[str, Any]) -> str:
    for row in qc.get("results") or []:
        if not isinstance(row, dict) or row.get("postable"):
            continue
        if row.get("error"):
            return f"generated video failed frame QC: {row['error']}"
        for frame in row.get("frames") or []:
            if not isinstance(frame, dict) or frame.get("postable"):
                continue
            exposure = frame.get("exposure")
            if isinstance(exposure, dict) and not exposure.get("safe", True):
                issues = exposure.get("issues") or []
                return "generated video failed exposure QC" + (
                    f": {', '.join(str(item) for item in issues)}" if issues else ""
                )
            anatomy = frame.get("anatomy")
            if isinstance(anatomy, dict) and not anatomy.get("plausible", True):
                defects = anatomy.get("defects") or []
                return "generated video failed anatomy QC" + (
                    f": {', '.join(str(item) for item in defects)}" if defects else ""
                )
    return "generated video failed anatomy/exposure QC"
