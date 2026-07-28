"""Deterministic, fail-closed Higgsfield recreation planning.

This module plans only the already-observed Higgsfield contracts.  It never
submits a generation.  Paid execution remains behind the existing spend and
human-review gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from .production_prompts import CREATOR_SOUL_IDS

SCHEMA: Final = "campaign_factory.recreation_plan.v1"
MODES: Final = ("auto", "passive", "motion", "structural", "first_last", "talking")
_MOTION_CREDIT_RATE: Final = 3.2

QuoteProvider = Callable[[str, dict[str, Any]], dict[str, Any]]


def plan_recreation(
    *,
    creator: str,
    source_video: Path,
    intake: dict[str, Any],
    requested_mode: str,
    audio_policy: str,
    through: str | None,
    max_credits: float | None,
    quote_provider: QuoteProvider | None = None,
) -> dict[str, Any]:
    """Build one stable public plan without exposing private Soul identifiers."""

    creator_key = str(creator or "").strip().lower()
    if creator_key not in CREATOR_SOUL_IDS:
        raise ValueError("recreation_creator_has_no_configured_soul_identity")
    if requested_mode not in MODES:
        raise ValueError("unsupported_recreate_mode")
    reference = _mapping(intake.get("reference"))
    audio = _mapping(intake.get("audio"))
    media = _mapping(reference.get("media"))
    reference_id = _required(reference.get("referenceId"), "referenceId")
    duration = _positive(media.get("durationSeconds"), "reference duration")
    measurements = _classification_measurements(
        source_video=source_video,
        reference=reference,
        audio=audio,
    )
    classification = _classification(reference, measurements)
    routed_mode, alternatives, route_status = _route(
        requested_mode=requested_mode,
        classification=classification,
        measurements=measurements,
    )
    excerpt = _select_excerpt(
        duration=duration,
        anchor_time=float(
            _mapping(reference.get("selectedAnchor")).get("timeSec") or 0
        ),
        mode=routed_mode,
    )
    audio_decision = _audio_decision(
        requested=audio_policy,
        classification=classification,
        mode=routed_mode,
        audio=audio,
    )
    scene_prompt = _scene_prompt(reference, classification)
    identity_fingerprint = hashlib.sha256(
        CREATOR_SOUL_IDS[creator_key].encode()
    ).hexdigest()
    run_id = (
        "recreate_"
        + _fingerprint(
            {
                "creator": creator_key,
                "referenceId": reference_id,
                "requestedMode": requested_mode,
                "excerpt": excerpt,
            }
        )[:20]
    )
    anchor_count = 2 if routed_mode == "first_last" else 1
    anchor_requests = [
        _public_anchor_request(
            role=role,
            creator=creator_key,
            identity_fingerprint=identity_fingerprint,
            reference=reference,
            prompt=scene_prompt,
        )
        for role in (("opening", "ending") if anchor_count == 2 else ("scene",))
    ]
    video_request = _video_request(
        mode=routed_mode,
        prompt=scene_prompt,
        reference=reference,
        excerpt=excerpt,
        measurements=measurements,
        classification=classification,
    )
    quote = quote_provider or _live_quote
    quote_items: list[dict[str, Any]] = []
    quote_errors: list[dict[str, str]] = []
    quote_skipped: list[dict[str, str]] = []
    for _ in range(anchor_count):
        _append_quote(
            quote_items,
            quote_errors,
            quote,
            "text2image_soul_v2",
            {
                "prompt": scene_prompt,
                "aspect_ratio": "9:16",
                "quality": "2k",
            },
        )
    if video_request is not None and routed_mode != "talking":
        compatibility = _mapping(video_request.get("compatibility"))
        if compatibility.get("classification") == "UNSUPPORTED":
            quote_skipped.append(
                {
                    "model": str(video_request["model"]),
                    "reason": "motion_source_unsupported_before_quote",
                }
            )
        else:
            _append_quote(
                quote_items,
                quote_errors,
                quote,
                str(video_request["model"]),
                _mapping(video_request.get("quoteParameters")),
            )
    total_quote = (
        round(sum(float(item["credits"]) for item in quote_items), 4)
        if not quote_errors and not quote_skipped
        else None
    )
    cap = _optional_positive(max_credits)
    within_cap = total_quote is not None and cap is not None and total_quote <= cap
    experimental = routed_mode in {"motion", "structural", "first_last"}
    talking_blocked = routed_mode == "talking"
    motion_unsupported = (
        routed_mode == "motion"
        and isinstance(video_request, dict)
        and _mapping(video_request.get("compatibility")).get("classification")
        == "UNSUPPORTED"
    )
    readiness = (
        "BLOCKED_TALKING_ROUTE_NOT_ENTITLED"
        if talking_blocked
        else "BLOCKED_INCOMPATIBLE_MOTION_SOURCE"
        if motion_unsupported
        else "MANUAL_REVIEW_REQUIRED"
        if route_status == "manual_review"
        else "EXPERIMENTAL_AUTHORIZATION_REQUIRED"
        if experimental
        else "ANCHOR_GENERATION_READY"
    )
    public = {
        "schema": SCHEMA,
        "runId": run_id,
        "creator": creator_key,
        "referenceId": reference_id,
        "referenceVideoSha256": _mapping(reference.get("source")).get("sha256"),
        "requestedMode": requested_mode,
        "classification": {
            "label": classification,
            "measurements": measurements,
            "confidence": _classification_confidence(classification, measurements),
            "warnings": _warnings(classification, measurements),
        },
        "selectedMode": routed_mode,
        "alternatives": alternatives,
        "productionReadiness": readiness,
        "through": through or "plan",
        "excerpt": excerpt,
        "audioDecision": audio_decision,
        "anchorPlan": {
            "count": anchor_count,
            "model": "soul_2",
            "officialJobType": "text2image_soul_v2",
            "requests": anchor_requests,
            "identityReviewRequired": True,
            "wouldUseAsAnchorRequired": True,
            "videoSubmissionBlockedUntilApproved": True,
        },
        "videoPlan": video_request,
        "quote": {
            "items": quote_items,
            "errors": quote_errors,
            "skipped": quote_skipped,
            "totalCredits": total_quote,
            "maxCredits": cap,
            "withinAuthorizedCap": within_cap,
            "quoteCalls": len(quote_items) + len(quote_errors),
            "providerGenerationCalls": 0,
            "paidCalls": 0,
            "noAutomaticPaidRetries": True,
        },
        "reviewPackage": _review_package(reference, routed_mode),
        "status": _status_rows(readiness),
        "proposedMutations": [
            "recreation run status",
            "immutable Soul-anchor receipt(s)",
            "mode-specific provider receipt after explicit approval",
            "common review package",
        ],
        "paidCalls": 0,
        "generationIds": [],
        "publishingAllowed": False,
        "schedulingAllowed": False,
    }
    return {**public, "planFingerprint": _fingerprint(public)}


def _classification(reference: dict[str, Any], measurements: dict[str, Any]) -> str:
    if reference.get("sourceSpeakingClassification") == "DECLARED_TALKING":
        return "talking"
    if int(measurements["maxPrincipalPersonCount"] or 0) > 1:
        return "multi_person"
    if int(measurements["shotCount"]) > 1:
        return "multi_shot"
    if measurements["severeOcclusion"]:
        return "heavy_occlusion"
    motion = float(measurements["coarseMotionEnergy"])
    if motion < 0.025:
        return "passive_single_shot"
    if motion < 0.075:
        return "simple_pose_motion"
    return "structural_reference"


def _route(
    *, requested_mode: str, classification: str, measurements: dict[str, Any]
) -> tuple[str, list[str], str]:
    if requested_mode != "auto":
        if requested_mode == "talking":
            return "talking", [], "blocked"
        return requested_mode, [], "explicit_operator_mode"
    routes = {
        "passive_single_shot": ("passive", ["structural"], "ready"),
        "simple_pose_motion": (
            "motion",
            ["structural", "passive"],
            "experimental",
        ),
        "walking": ("motion", ["structural"], "experimental"),
        "dance": ("motion", ["structural"], "experimental"),
        "first_last_transition": (
            "first_last",
            ["structural"],
            "experimental",
        ),
        "structural_reference": (
            "structural",
            ["motion", "first_last"],
            "experimental",
        ),
        "talking": ("talking", [], "blocked"),
        "lip_sync": ("talking", [], "blocked"),
        "multi_shot": ("structural", [], "manual_review"),
        "multi_person": ("structural", [], "manual_review"),
        "heavy_occlusion": ("structural", [], "manual_review"),
        "unsupported": ("structural", [], "manual_review"),
    }
    return routes.get(classification, routes["unsupported"])


def _classification_measurements(
    *, source_video: Path, reference: dict[str, Any], audio: dict[str, Any]
) -> dict[str, Any]:
    candidates = [
        row
        for row in list(reference.get("anchorCandidates") or [])
        if isinstance(row, dict)
    ]
    clean = [row for row in candidates if not row.get("excluded")]
    measurements = [_mapping(row.get("measurements")) for row in (clean or candidates)]
    persons = [
        int(row["principalPersonCount"])
        for row in measurements
        if isinstance(row.get("principalPersonCount"), int)
    ]
    severe = any(
        "severe_occlusion" in list(row.get("exclusions") or []) for row in candidates
    )
    return {
        "shotCount": max(1, len(list(reference.get("sceneCutsSeconds") or []))),
        "maxPrincipalPersonCount": max(persons) if persons else None,
        "faceVisibility": _maximum(measurements, "faceVisibility"),
        "bodyVisibility": _maximum(measurements, "bodyExtent"),
        "coarseMotionEnergy": _coarse_motion_energy(source_video),
        "cameraStability": "unavailable",
        "blur": round(1.0 - _maximum(measurements, "sharpness"), 6),
        "durationSeconds": _mapping(reference.get("media")).get("durationSeconds"),
        "speechEvidence": reference.get("sourceSpeakingClassification", "UNKNOWN"),
        "audioPresent": bool(_mapping(reference.get("media")).get("hasAudio")),
        "audioReuseClassification": audio.get("classification"),
        "cutTimestampsSeconds": list(reference.get("sceneCutsSeconds") or []),
        "severeOcclusion": severe,
        "framingCompatibility": _framing_state(candidates),
        "endpointCompatibility": "requires_human_review",
        "anchorCompatibility": "pending_soul_anchor",
    }


def _video_request(
    *,
    mode: str,
    prompt: str,
    reference: dict[str, Any],
    excerpt: dict[str, Any],
    measurements: dict[str, Any],
    classification: str,
) -> dict[str, Any] | None:
    source = {
        "referenceId": reference.get("referenceId"),
        "sha256": _mapping(reference.get("source")).get("sha256"),
        "excerpt": excerpt,
    }
    if mode == "talking":
        return {
            "status": "talking_route_not_entitled",
            "missingEvidence": [
                "authenticated Speak entitlement",
                "supplied-WAV voice-fidelity qualification",
                "9:16 output qualification",
            ],
            "silentFallbackAllowed": False,
        }
    if mode == "motion":
        return {
            "model": "kling3_0_motion_control",
            "status": "experimental_qualification_required",
            "compatibility": _motion_compatibility(
                measurements=measurements,
                classification=classification,
                excerpt=excerpt,
            ),
            "request": {
                "image_references": ["<approved_soul_anchor>"],
                "video_references": [source],
                "background_source": "input_image",
                "mode": "pro",
            },
            "quoteParameters": {
                "duration": excerpt["durationSeconds"],
                "mode": "pro",
            },
            "providerAudio": "replace_in_creator_os",
            "unsupportedFieldsAdded": [],
        }
    if mode == "structural":
        return {
            "model": "seedance_2_0",
            "status": "experimental_structural_recreation",
            "identityReplacementClaimed": False,
            "request": {
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "duration": int(round(float(excerpt["durationSeconds"]))),
                "resolution": "720p",
                "mode": "std",
                "generate_audio": False,
                "start_image": "<approved_soul_anchor>",
                "video_references": [source],
            },
            "quoteParameters": {
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "duration": int(round(float(excerpt["durationSeconds"]))),
                "resolution": "720p",
                "mode": "std",
                "generate_audio": False,
            },
        }
    if mode == "first_last":
        return {
            "model": "kling3_0",
            "status": "experimental_transition_recreation",
            "exactMotionCopyClaimed": False,
            "request": {
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "duration": int(round(float(excerpt["durationSeconds"]))),
                "mode": "pro",
                "sound": "off",
                "start_image": "<approved_opening_soul_anchor>",
                "end_image": "<approved_ending_soul_anchor>",
                "source": source,
            },
            "quoteParameters": {
                "prompt": prompt,
                "aspect_ratio": "9:16",
                "duration": int(round(float(excerpt["durationSeconds"]))),
                "mode": "pro",
                "sound": "off",
            },
        }
    return {
        "model": "kling3_0",
        "status": "production_supported_after_anchor_review",
        "request": {
            "prompt": "Subtle natural casual motion. Preserve identity and framing.",
            "aspect_ratio": "9:16",
            "duration": 5,
            "mode": "pro",
            "sound": "off",
            "start_image": "<approved_soul_anchor>",
        },
        "quoteParameters": {
            "prompt": "Subtle natural casual motion. Preserve identity and framing.",
            "aspect_ratio": "9:16",
            "duration": 5,
            "mode": "pro",
            "sound": "off",
        },
    }


def _motion_compatibility(
    *,
    measurements: dict[str, Any],
    classification: str,
    excerpt: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    blockers: list[str] = []
    if int(measurements.get("shotCount") or 0) != 1:
        blockers.append("source_is_not_one_material_shot")
    people = measurements.get("maxPrincipalPersonCount")
    if people not in {None, 1}:
        blockers.append("source_does_not_have_one_principal_person")
    if classification == "heavy_occlusion":
        blockers.append("source_has_severe_occlusion")
    if measurements.get("framingCompatibility") != "compatible":
        reasons.append("framing_compatibility_not_proven")
    if float(measurements.get("faceVisibility") or 0) < 0.5:
        reasons.append("face_visibility_is_weak")
    if float(measurements.get("bodyVisibility") or 0) < 0.2:
        reasons.append("body_extent_is_weak")
    if measurements.get("speechEvidence") == "UNKNOWN":
        reasons.append("talking_or_lipsync_requirement_unresolved")
    if not excerpt.get("wholeSource"):
        reasons.append("bounded_excerpt_must_be_materialized_and_confirmed")
    state = "UNSUPPORTED" if blockers else "POSSIBLE_FIT" if reasons else "STRONG_FIT"
    return {
        "classification": state,
        "blockers": blockers,
        "warnings": reasons,
        "checkedBeforeQuoteOrSubmission": True,
        "exactChoreographyClaimed": False,
    }


def _public_anchor_request(
    *,
    role: str,
    creator: str,
    identity_fingerprint: str,
    reference: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    frame_role = (
        "first_clean"
        if role == "opening"
        else ("last_clean" if role == "ending" else "best_anchor")
    )
    frames = _mapping(reference.get("frameDerivatives"))
    frame = _mapping(frames.get(frame_role))
    return {
        "role": role,
        "creator": creator,
        "identityProfileFingerprint": identity_fingerprint,
        "model": "soul_2",
        "officialJobType": "text2image_soul_v2",
        "referenceFrame": {
            "role": frame_role,
            "sha256": frame.get("sha256"),
            "timeSec": frame.get("timeSec"),
        },
        "request": {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "quality": "2k",
            "image_references": ["<selected_reference_frame>"],
            "count": 1,
        },
        "soulIdExposed": False,
        "approvalState": "OPERATOR_REVIEW_REQUIRED",
    }


def _audio_decision(
    *, requested: str, classification: str, mode: str, audio: dict[str, Any]
) -> dict[str, Any]:
    if requested != "auto":
        return {"requested": requested, "selected": requested, "reason": "explicit"}
    if classification in {"talking", "lip_sync"}:
        selected = "creator_or_reference_audio_required"
    elif classification == "dance":
        selected = "reference_audio_required"
    elif mode == "passive":
        selected = "embedded_trending_required"
    elif audio.get("classification") in {
        "REFERENCE_AUDIO_PREFERRED",
        "REFERENCE_AUDIO_ELIGIBLE",
    }:
        selected = "reference_audio_or_audio_radar_operator_choice"
    else:
        selected = "embedded_trending_required"
    return {
        "requested": "auto",
        "selected": selected,
        "canonicalAudioId": audio.get("canonicalAudioId"),
        "referenceOccurrenceId": audio.get("referenceOccurrence"),
        "providerGeneratedAudio": False,
    }


def _select_excerpt(
    *, duration: float, anchor_time: float, mode: str
) -> dict[str, Any]:
    limit = 5.0 if mode == "passive" else 10.0 if mode == "motion" else 15.0
    length = min(duration, limit)
    start = min(max(0.0, anchor_time - length / 2), max(0.0, duration - length))
    end = start + length
    return {
        "startSeconds": round(start, 3),
        "endSeconds": round(end, 3),
        "durationSeconds": round(length, 3),
        "sourceDurationSeconds": round(duration, 3),
        "wholeSource": math.isclose(length, duration, abs_tol=0.001),
        "reason": "bounded_coherent_window_around_selected_anchor",
        "operatorConfirmationRequired": not math.isclose(
            length, duration, abs_tol=0.001
        ),
    }


def _live_quote(model: str, params: dict[str, Any]) -> dict[str, Any]:
    if model == "kling3_0_motion_control":
        seconds = _positive(params.get("duration"), "motion duration")
        return {
            "model": model,
            "credits": round(seconds * _MOTION_CREDIT_RATE, 4),
            "unit": "higgsfield_credits",
            "source": "authenticated_transaction_duration_rate",
            "basis": {"seconds": seconds, "creditsPerSecond": _MOTION_CREDIT_RATE},
        }
    cli = shutil.which("higgsfield")
    if not cli:
        raise RuntimeError("higgsfield_cli_unavailable")
    command = [cli, "generate", "cost", model]
    for key, value in params.items():
        command += [f"--{key}", _cli_value(value)]
    command.append("--json")
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError("higgsfield_quote_unavailable")
    try:
        payload = json.loads(result.stdout)
        credits = _positive(payload.get("credits"), "quote credits")
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("higgsfield_quote_invalid") from exc
    return {
        "model": model,
        "credits": credits,
        "unit": "higgsfield_credits",
        "source": "authenticated_cli_cost",
    }


def _append_quote(
    items: list[dict[str, Any]],
    errors: list[dict[str, str]],
    quote: QuoteProvider,
    model: str,
    params: dict[str, Any],
) -> None:
    try:
        items.append(quote(model, params))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        errors.append({"model": model, "reason": str(exc)})


def _coarse_motion_energy(path: Path) -> float:
    width, height, samples = 64, 112, 12
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps=0.5,scale={width}:{height},format=gray",
            "-frames:v",
            str(samples),
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
        timeout=90,
    )
    frame_bytes = width * height
    frames = [
        result.stdout[index : index + frame_bytes]
        for index in range(0, len(result.stdout) - frame_bytes + 1, frame_bytes)
    ][:samples]
    if result.returncode != 0 or len(frames) < 2:
        return 0.0
    values = [
        sum(abs(left - right) for left, right in zip(a, b, strict=True))
        / (frame_bytes * 255)
        for a, b in zip(frames, frames[1:], strict=False)
    ]
    return round(sum(values) / len(values), 6)


def _scene_prompt(reference: dict[str, Any], classification: str) -> str:
    media = _mapping(reference.get("media"))
    cuts = list(reference.get("sceneCutsSeconds") or [])
    return (
        "Recreate the supplied reference scene composition with the configured "
        "creator identity: preserve the observed pose category, framing, clothing "
        "category, environment, lighting, and camera angle. Do not copy the "
        "reference performer identity. Do not add titles, interface chrome, music, "
        f"ambient audio, or dialogue. Source classification {classification}; "
        f"portrait {media.get('width')}x{media.get('height')}; "
        f"{max(1, len(cuts))} observed material shot markers."
    )


def _review_package(reference: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "sourceVideo": {
            "referenceId": reference.get("referenceId"),
            "sha256": _mapping(reference.get("source")).get("sha256"),
        },
        "selectedSourceFrame": reference.get("selectedAnchor"),
        "sourceFrameContactSheet": reference.get("contactSheet"),
        "soulAnchor": None,
        "secondSoulAnchor": None if mode != "first_last" else "pending",
        "generatedOutput": None,
        "sideBySideVideo": None,
        "operatorFields": {
            key: None
            for key in (
                "intendedCreatorPresent",
                "faceStability",
                "bodyConsistency",
                "anatomy",
                "motionFidelity",
                "structureFidelity",
                "cameraSimilarity",
                "firstLastContinuity",
                "lipSync",
                "audioChoice",
                "wouldPost",
            )
        },
        "identityAndAnatomyHumanDecisive": True,
    }


def _status_rows(readiness: str) -> list[dict[str, str]]:
    return [
        {"stage": "intake", "status": "COMPLETE"},
        {"stage": "analysis", "status": "COMPLETE"},
        {"stage": "audio_library", "status": "COMPLETE"},
        {"stage": "anchor", "status": "PLANNED"},
        {"stage": "anchor_review", "status": "PENDING"},
        {"stage": "provider_request", "status": "NOT_SUBMITTED"},
        {"stage": "audio_finishing", "status": "NOT_STARTED"},
        {"stage": "qc", "status": "NOT_STARTED"},
        {"stage": "human_review", "status": "NOT_STARTED"},
        {"stage": "export_readiness", "status": readiness},
    ]


def _warnings(classification: str, measurements: dict[str, Any]) -> list[str]:
    warnings = []
    if classification == "multi_shot":
        warnings.append("AUTO cannot silently submit a multi-shot experimental route")
    if measurements.get("speechEvidence") == "UNKNOWN":
        warnings.append("speech evidence is unknown, never assumed absent")
    if measurements.get("maxPrincipalPersonCount") is None:
        warnings.append("principal-person count unavailable on some frames")
    return warnings


def _classification_confidence(
    classification: str, measurements: dict[str, Any]
) -> str:
    if classification in {"talking", "multi_person", "heavy_occlusion"}:
        return "high"
    if measurements.get("speechEvidence") == "UNKNOWN":
        return "bounded"
    return "moderate"


def _framing_state(candidates: list[dict[str, Any]]) -> str:
    states = {
        str(_mapping(row.get("measurements")).get("framingCompatibility") or "")
        for row in candidates
    }
    if "compatible" in states:
        return "compatible"
    if states - {"", "unknown"}:
        return sorted(states - {"", "unknown"})[0]
    return "unknown"


def _maximum(rows: list[dict[str, Any]], field: str) -> float:
    values = [
        float(row[field])
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row.get(field), bool)
    ]
    return round(max(values), 6) if values else 0.0


def _cli_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _required(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be positive")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be positive") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _optional_positive(value: Any) -> float | None:
    if value is None:
        return None
    return _positive(value, "max credits")


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
