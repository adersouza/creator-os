#!/usr/bin/env python3
"""Build a dry-run-first structural remix plan for one short reference video."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pipeline_contracts import (
    validate_reference_video_motion_analysis,
    validate_reference_video_remix_plan,
)

from .asset_prompt_contract import AssetPromptSet
from .fileops import atomic_write_text
from .generate_assets import build_video_cmd

Provider = Literal["seedance", "kling"]

ANALYSIS_SCHEMA = "reel_factory.reference_video_motion_analysis.v1"
PLAN_SCHEMA = "reel_factory.reference_video_remix_plan.v1"
PROVIDER_MODELS: dict[Provider, str] = {
    "seedance": "seedance_2_0",
    "kling": "kling3_0",
}
DEFAULT_SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
_FRAME_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_REQUIRED_TRANSFORMS = {"identity", "surface_text"}
_VISUAL_TRANSFORMS = {"wardrobe", "setting", "styling", "props"}


def gemini_motion_analysis_instruction(reference_id: str) -> str:
    """Return the bounded instruction used to obtain contract-shaped JSON."""
    resolved_reference_id = _required_text(reference_id, "reference_id")
    return (
        "Analyze the attached operator-selected reference video as motion structure only. "
        "Return exactly one JSON object matching schema "
        f"{ANALYSIS_SCHEMA} with referenceId {resolved_reference_id}. "
        "The supported scope is one continuous 9:16 shot lasting 5 to 12 seconds. "
        "Describe the first frame, last frame, subject motion, camera motion, pacing, "
        "and a continuous timestamped timeline. Preserve only reusable pose, framing, "
        "camera, pacing, motion-rhythm, or endpoint-composition structure. Require changes "
        "to identity, surface text, and at least one of wardrobe, setting, styling, or props. "
        "Do not return a transcript, source wording, creator identity, or instructions to "
        "copy the source asset literally. Set sourceTextPolicy.reuseVerbatim to false."
    )


def build_reference_video_remix_plan(
    *,
    reference_video_path: str | Path,
    source_first_frame_path: str | Path,
    source_last_frame_path: str | Path,
    analysis: dict[str, Any],
    creator: str,
    soul_id: str,
    operator_selected: bool,
    rights_confirmed: bool,
    preferred_provider: str = "auto",
    available_providers: tuple[str, ...] | list[str] = ("seedance", "kling"),
    accepted_first_frame_path: str | Path | None = None,
    accepted_last_frame_path: str | Path | None = None,
    first_frame_approval_id: str | None = None,
    last_frame_approval_id: str | None = None,
    budget_cap_credits: float | None = None,
) -> dict[str, Any]:
    """Compile a non-executing plan from validated motion analysis and local files.

    The plan never authorizes a provider call or publishing. Supplying accepted
    endpoint frames only advances it to ``ready_for_paid_animation_approval``.
    The existing provider quote and atomic credit reservation must still run
    immediately before any paid generation.
    """
    validate_reference_video_motion_analysis(analysis)
    _validate_analysis_semantics(analysis)
    if not operator_selected:
        raise PermissionError("reference video must be explicitly operator-selected")
    if not rights_confirmed:
        raise PermissionError("reference video usage rights must be confirmed")
    creator_name = _required_text(creator, "creator")
    resolved_soul_id = _required_text(soul_id, "soul_id")
    reference_video = _existing_file(
        reference_video_path, "reference video", _VIDEO_SUFFIXES
    )
    source_first = _existing_file(
        source_first_frame_path, "source first frame", _FRAME_SUFFIXES
    )
    source_last = _existing_file(
        source_last_frame_path, "source last frame", _FRAME_SUFFIXES
    )
    if source_first == source_last:
        raise ValueError("source first and last frames must be different files")

    provider, routing_reason = select_animation_provider(
        preferred_provider=preferred_provider,
        available_providers=available_providers,
        requires_reference_video_conditioning=bool(
            analysis["requiresReferenceVideoConditioning"]
        ),
    )
    model = PROVIDER_MODELS[provider]
    accepted = _accepted_frame_pair(
        first_path=accepted_first_frame_path,
        last_path=accepted_last_frame_path,
        first_approval_id=first_frame_approval_id,
        last_approval_id=last_frame_approval_id,
        source_first_hash=_sha256_file(source_first),
        source_last_hash=_sha256_file(source_last),
    )
    analysis_hash = _canonical_json_sha256(analysis)
    reference_hash = _sha256_file(reference_video)
    source_first_hash = _sha256_file(source_first)
    source_last_hash = _sha256_file(source_last)
    source_duration = float(analysis["source"]["durationSeconds"])
    output_duration = _provider_duration_seconds(source_duration)
    motion_prompt = _compile_motion_prompt(str(analysis["motionPrompt"]))
    plan_id = (
        "remix_"
        + _canonical_json_sha256(
            {
                "referenceVideoSha256": reference_hash,
                "analysisSha256": analysis_hash,
                "soulId": resolved_soul_id,
                "provider": provider,
            }
        )[:16]
    )

    ready = accepted["ready"]
    first_accepted = accepted["first"]
    last_accepted = accepted["last"]
    command = None
    if ready:
        command = build_video_cmd(
            AssetPromptSet(
                higgsfieldGridPrompt="",
                klingMotionPrompt=motion_prompt,
                notes="Structural reference-video remix; provider execution remains approval-gated.",
            ),
            start_image=first_accepted["path"],
            end_image=last_accepted["path"],
            video_reference=str(reference_video) if provider == "seedance" else None,
            model=model,
            aspect_ratio="9:16",
            duration=output_duration,
            mode="pro" if provider == "kling" else None,
            sound="off",
            wait=True,
        )

    reference_id = str(analysis["referenceId"])
    plan = {
        "schema": PLAN_SCHEMA,
        "planId": plan_id,
        "status": (
            "ready_for_paid_animation_approval" if ready else "awaiting_endpoint_frames"
        ),
        "reference": {
            "referenceId": reference_id,
            "videoPath": str(reference_video),
            "videoSha256": reference_hash,
            "operatorSelected": True,
            "rightsConfirmed": True,
            "analysisId": str(analysis["analysisId"]),
            "analysisSha256": analysis_hash,
        },
        "scope": {
            "sourceDurationSeconds": source_duration,
            "outputDurationSeconds": output_duration,
            "durationRoundingPolicy": "nearest_integer_half_up",
            "shotCount": 1,
            "oneShotOnly": True,
            "outputAspectRatio": "9:16",
        },
        "identity": {"creator": creator_name, "soulId": resolved_soul_id},
        "framePair": {
            "first": _frame_plan(
                role="first",
                source_path=source_first,
                source_hash=source_first_hash,
                source_timestamp=0.0,
                description=str(analysis["structure"]["firstFrameDescription"]),
                reference_id=reference_id,
                creator=creator_name,
                soul_id=resolved_soul_id,
                accepted_frame=first_accepted,
            ),
            "last": _frame_plan(
                role="last",
                source_path=source_last,
                source_hash=source_last_hash,
                source_timestamp=source_duration,
                description=str(analysis["structure"]["lastFrameDescription"]),
                reference_id=reference_id,
                creator=creator_name,
                soul_id=resolved_soul_id,
                accepted_frame=last_accepted,
            ),
            "continuityReviewRequired": True,
        },
        "animation": {
            "provider": provider,
            "model": model,
            "routingReason": routing_reason,
            "status": (
                "ready_for_paid_approval"
                if ready
                else "blocked_pending_endpoint_approval"
            ),
            "motionPrompt": motion_prompt,
            "inputs": {
                "startFramePath": first_accepted["path"],
                "endFramePath": last_accepted["path"],
                "referenceVideoPath": (
                    str(reference_video) if provider == "seedance" else None
                ),
                "durationSeconds": output_duration,
                "aspectRatio": "9:16",
                "sound": "off",
            },
            "command": command,
            "spendGuard": {
                "providerQuoteRequired": True,
                "atomicReservationRequired": True,
                "budgetCapCredits": _positive_optional_credit_cap(budget_cap_credits),
            },
            "paidGenerationAuthorized": False,
        },
        "lineageSeed": {
            "referenceId": reference_id,
            "referenceVideoSha256": reference_hash,
            "analysisId": str(analysis["analysisId"]),
            "analysisSha256": analysis_hash,
            "firstSourceFrameSha256": source_first_hash,
            "lastSourceFrameSha256": source_last_hash,
            "firstAcceptedFrameSha256": first_accepted["sha256"],
            "lastAcceptedFrameSha256": last_accepted["sha256"],
            "generationTool": "higgsfield_endpoint_frames_then_video",
            "providerModel": model,
            "sourceDurationSeconds": source_duration,
            "outputDurationSeconds": output_duration,
        },
        "qualityGates": {
            "contentForgeRequired": True,
            "blockingChecks": [
                "source_master_distinctness",
                "sibling_distinctness",
                "identity_verification",
                "endpoint_continuity",
                "readability",
                "safe_zone",
                "watchability",
                "visual_qc",
            ],
            "onFailure": "block_and_return_to_review",
        },
        "approval": {
            "endpointFrameApprovalRequired": True,
            "paidAnimationApprovalRequired": True,
            "finalAssetApprovalRequired": True,
            "publishingAllowed": False,
        },
    }
    _validate_plan_semantics(plan)
    validate_reference_video_remix_plan(plan)
    return plan


def select_animation_provider(
    *,
    preferred_provider: str,
    available_providers: tuple[str, ...] | list[str],
    requires_reference_video_conditioning: bool,
) -> tuple[Provider, str]:
    """Route deterministically without probing or invoking a paid provider."""
    preferred = str(preferred_provider or "auto").strip().lower()
    if preferred not in {"auto", *PROVIDER_MODELS}:
        raise ValueError("preferred_provider must be auto, seedance, or kling")
    available = {str(value).strip().lower() for value in available_providers}
    unknown = available.difference(PROVIDER_MODELS)
    if unknown:
        raise ValueError(f"unknown available provider(s): {sorted(unknown)}")
    if not available:
        raise ValueError("at least one animation provider must be available")
    if preferred != "auto":
        if preferred not in available:
            raise ValueError(f"requested provider is unavailable: {preferred}")
        return preferred, "explicit_provider"  # type: ignore[return-value]
    if requires_reference_video_conditioning and "seedance" in available:
        return "seedance", "reference_video_conditioning"
    if "kling" in available:
        reason = (
            "prompt_and_endpoint_frames"
            if not requires_reference_video_conditioning
            else "deterministic_fallback"
        )
        return "kling", reason
    return "seedance", "deterministic_fallback"


def _validate_analysis_semantics(analysis: dict[str, Any]) -> None:
    if analysis.get("schema") != ANALYSIS_SCHEMA:
        raise ValueError("reference video motion analysis has the wrong schema")
    duration = float(analysis["source"]["durationSeconds"])
    timeline = analysis["structure"]["timeline"]
    previous_end = 0.0
    for index, beat in enumerate(timeline):
        start = float(beat["startSeconds"])
        end = float(beat["endSeconds"])
        if start >= end:
            raise ValueError(f"timeline beat {index} must end after it starts")
        if abs(start - previous_end) > 0.05:
            raise ValueError("timeline must continuously cover the source motion")
        previous_end = end
    if abs(previous_end - duration) > 0.05:
        raise ValueError("timeline must end at the analyzed source duration")
    transforms = set(analysis["distinctness"]["transformElements"])
    missing = _REQUIRED_TRANSFORMS.difference(transforms)
    if missing:
        raise ValueError(f"distinctness transform set missing: {sorted(missing)}")
    if not transforms.intersection(_VISUAL_TRANSFORMS):
        raise ValueError(
            "distinctness requires a wardrobe, setting, styling, or props change"
        )


def _validate_plan_semantics(plan: dict[str, Any]) -> None:
    ready = plan["status"] == "ready_for_paid_animation_approval"
    first = plan["framePair"]["first"]["acceptedFrame"]
    last = plan["framePair"]["last"]["acceptedFrame"]
    if ready and (
        first["status"] != "accepted"
        or last["status"] != "accepted"
        or not plan["animation"]["command"]
    ):
        raise ValueError("ready remix plan requires two accepted endpoint frames")
    if not ready and plan["animation"]["command"] is not None:
        raise ValueError("blocked remix plan cannot expose a provider command")
    if plan["animation"]["paidGenerationAuthorized"] is not False:
        raise ValueError("remix plan must not authorize paid generation")
    if plan["approval"]["publishingAllowed"] is not False:
        raise ValueError("remix plan must not authorize publishing")


def _accepted_frame_pair(
    *,
    first_path: str | Path | None,
    last_path: str | Path | None,
    first_approval_id: str | None,
    last_approval_id: str | None,
    source_first_hash: str,
    source_last_hash: str,
) -> dict[str, Any]:
    supplied = [first_path, last_path, first_approval_id, last_approval_id]
    if not any(value is not None for value in supplied):
        pending = {
            "status": "pending",
            "path": None,
            "sha256": None,
            "approvalDecisionId": None,
        }
        return {"ready": False, "first": dict(pending), "last": dict(pending)}
    if not all(value is not None and str(value).strip() for value in supplied):
        raise ValueError(
            "accepted endpoint paths and approval decision ids must be supplied together"
        )
    accepted_first = _existing_file(first_path, "accepted first frame", _FRAME_SUFFIXES)
    accepted_last = _existing_file(last_path, "accepted last frame", _FRAME_SUFFIXES)
    first_hash = _sha256_file(accepted_first)
    last_hash = _sha256_file(accepted_last)
    if first_hash == source_first_hash or last_hash == source_last_hash:
        raise ValueError("accepted endpoint frame cannot be the unchanged source frame")
    if first_hash == last_hash:
        raise ValueError("accepted first and last frames must be distinct")
    return {
        "ready": True,
        "first": {
            "status": "accepted",
            "path": str(accepted_first),
            "sha256": first_hash,
            "approvalDecisionId": str(first_approval_id),
        },
        "last": {
            "status": "accepted",
            "path": str(accepted_last),
            "sha256": last_hash,
            "approvalDecisionId": str(last_approval_id),
        },
    }


def _frame_plan(
    *,
    role: Literal["first", "last"],
    source_path: Path,
    source_hash: str,
    source_timestamp: float,
    description: str,
    reference_id: str,
    creator: str,
    soul_id: str,
    accepted_frame: dict[str, Any],
) -> dict[str, Any]:
    stem = f"{_slug(reference_id)}_remix_{role}"
    return {
        "role": role,
        "sourceFramePath": str(source_path),
        "sourceFrameSha256": source_hash,
        "sourceTimestampSeconds": source_timestamp,
        "description": " ".join(description.split()),
        "generation": {
            "provider": "higgsfield",
            "model": "text2image_soul_v2",
            "workflow": "reference_conditioned_endpoint_frame",
            "referenceConditioned": True,
            "soulId": soul_id,
            "aspectRatio": "9:16",
            "promptPolicy": {
                "capturedPromptReused": False,
                "promptAppendUsed": False,
                "appUiTermsForbidden": True,
                "distinctnessAcceptanceRequired": True,
            },
            "dryRunCommand": [
                "python3",
                "generate_assets.py",
                "reference-image-dry-run",
                "--reference",
                str(source_path),
                "--creator",
                creator,
                "--soul-id",
                soul_id,
                "--stem",
                stem,
                "--image-aspect-ratio",
                "9:16",
            ],
        },
        "acceptedFrame": accepted_frame,
    }


def _compile_motion_prompt(value: str) -> str:
    prompt = " ".join(value.split())
    if len(prompt) < 20:
        raise ValueError("motionPrompt is too short")
    guardrail = (
        " Use only the two approved endpoint frames for identity and visual continuity. "
        "Reproduce the analyzed motion structure and camera rhythm, not the source identity, "
        "wording, wardrobe, or exact scene dressing. Keep one continuous 9:16 shot with no "
        "cuts, added people, graphic elements, or abrupt endpoint drift."
    )
    return prompt.rstrip(". ") + "." + guardrail


def _positive_optional_credit_cap(value: float | None) -> float | None:
    if value is None:
        return None
    resolved = float(value)
    if resolved <= 0:
        raise ValueError("budget_cap_credits must be positive")
    return resolved


def _provider_duration_seconds(source_duration: float) -> int:
    """Map analyzed source timing to the provider's bounded integer duration."""
    rounded = math.floor(float(source_duration) + 0.5)
    return min(12, max(5, rounded))


def _existing_file(value: str | Path | None, label: str, suffixes: set[str]) -> Path:
    if value is None:
        raise ValueError(f"{label} is required")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"unsupported {label} type: {path.suffix}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _slug(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in normalized.split("_") if part) or "reference"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-video", required=True)
    parser.add_argument("--source-first-frame", required=True)
    parser.add_argument("--source-last-frame", required=True)
    parser.add_argument("--analysis-json", required=True)
    parser.add_argument("--creator", default="Stacey")
    parser.add_argument("--soul-id", default=DEFAULT_SOUL_ID)
    parser.add_argument(
        "--preferred-provider", choices=["auto", "seedance", "kling"], default="auto"
    )
    parser.add_argument(
        "--available-provider",
        action="append",
        choices=["seedance", "kling"],
        dest="available_providers",
    )
    parser.add_argument("--accepted-first-frame")
    parser.add_argument("--accepted-last-frame")
    parser.add_argument("--first-frame-approval-id")
    parser.add_argument("--last-frame-approval-id")
    parser.add_argument("--budget-cap-credits", type=float)
    parser.add_argument("--operator-selected", action="store_true", required=True)
    parser.add_argument("--rights-confirmed", action="store_true", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    analysis_path = Path(args.analysis_json).expanduser().resolve()
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    if not isinstance(analysis, dict):
        raise ValueError("analysis JSON must contain an object")
    plan = build_reference_video_remix_plan(
        reference_video_path=args.reference_video,
        source_first_frame_path=args.source_first_frame,
        source_last_frame_path=args.source_last_frame,
        analysis=analysis,
        creator=args.creator,
        soul_id=args.soul_id,
        operator_selected=args.operator_selected,
        rights_confirmed=args.rights_confirmed,
        preferred_provider=args.preferred_provider,
        available_providers=tuple(args.available_providers or ("seedance", "kling")),
        accepted_first_frame_path=args.accepted_first_frame,
        accepted_last_frame_path=args.accepted_last_frame,
        first_frame_approval_id=args.first_frame_approval_id,
        last_frame_approval_id=args.last_frame_approval_id,
        budget_cap_credits=args.budget_cap_credits,
    )
    payload = json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, payload, encoding="utf-8")
        print(str(out))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
