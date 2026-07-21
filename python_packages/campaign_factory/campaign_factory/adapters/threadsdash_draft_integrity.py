from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pipeline_contracts import (
    evaluate_overlay_semantic_completeness,
    evaluate_overlay_timing,
)


def verify_rendered_media_asset(asset: dict[str, Any], file_path: Path) -> str:
    """Return the approved hash only when the current bytes still match it."""
    rendered_asset_id = str(asset.get("renderedAssetId") or "unknown")
    expected = str(asset.get("contentHash") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"rendered_media_content_hash_missing:{rendered_asset_id}")
    actual = sha256_file(file_path)
    if actual != expected:
        raise ValueError(
            "rendered_media_content_hash_mismatch:"
            f"{rendered_asset_id}:expected={expected}:actual={actual}"
        )
    return actual


def exported_content_hash(
    file_path: Path, *, approved_hash: str, is_derivative: bool
) -> str:
    return sha256_file(file_path) if is_derivative else approved_hash


def with_content_fingerprint(
    publishability: dict[str, Any], content_hash: str
) -> dict[str, Any]:
    """Bind a destination-specific derivative to the bytes actually exported."""
    result = dict(publishability)
    result["content_fingerprint"] = content_hash
    result["contentFingerprint"] = content_hash
    manifest = result.get("handoff_manifest")
    if isinstance(manifest, dict):
        manifest = dict(manifest)
        manifest["content_fingerprint"] = content_hash
        manifest["content_hash"] = content_hash
        result["handoff_manifest"] = manifest
    return result


def caption_timing_qc(
    asset: dict[str, Any], caption_context: dict[str, Any]
) -> dict[str, Any] | None:
    for record in (
        caption_context,
        asset,
        asset.get("generatedAssetLineage"),
        asset.get("captionGeneration"),
    ):
        if not isinstance(record, dict):
            continue
        for key in ("captionTimingQc", "caption_timing_qc"):
            value = record.get(key)
            if isinstance(value, dict):
                segments = value.get("segments")
                duration = value.get("duration_seconds", value.get("durationSeconds"))
                if isinstance(segments, list):
                    recomputed = evaluate_overlay_timing(
                        [dict(item) for item in segments if isinstance(item, dict)],
                        duration_seconds=duration,
                    )
                    recomputed["recorded_passed"] = value.get("passed")
                    return recomputed
                return {
                    **dict(value),
                    "passed": False,
                    "failure_reasons": ["missing_resolved_overlay_timing_segments"],
                    "reason": "missing_resolved_overlay_timing_segments",
                }
    return None


def has_human_semantic_approval(*records: Any) -> bool:
    for record in records:
        if not isinstance(record, dict):
            continue
        approval = record.get("humanSemanticApproval") or record.get(
            "human_semantic_approval"
        )
        if (
            isinstance(approval, dict)
            and approval.get("approved") is True
            and str(approval.get("reviewer") or "").strip()
            and str(
                approval.get("reviewedAt") or approval.get("reviewed_at") or ""
            ).strip()
        ):
            return True
    return False


def validate_caption_overlay_integrity(
    asset: dict[str, Any], caption_context: dict[str, Any], caption: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    caption_is_burned = asset_caption_is_burned(asset)
    human_approval = has_human_semantic_approval(
        caption_context,
        asset,
        asset.get("generatedAssetLineage"),
        asset.get("captionGeneration"),
    )
    semantic_qc = evaluate_overlay_semantic_completeness(
        (caption_context.get("caption_text") or caption) if caption_is_burned else None,
        require_overlay=caption_is_burned,
        human_semantic_approval=human_approval,
    )
    timing_qc = caption_timing_qc(asset, caption_context)
    if caption_is_burned and semantic_qc.get("timed_sequence") is True:
        if not isinstance(timing_qc, dict) or timing_qc.get("passed") is not True:
            reasons = (
                timing_qc.get("failure_reasons")
                if isinstance(timing_qc, dict)
                else None
            ) or ["missing_resolved_overlay_timing_proof"]
            raise ValueError(
                "burned_overlay_timing_unverified:"
                + ",".join(str(reason) for reason in reasons)
                + f":{asset['renderedAssetId']}"
            )
        semantic_qc = evaluate_overlay_semantic_completeness(
            {"segments": timing_qc.get("segments") or []},
            require_overlay=True,
            human_semantic_approval=human_approval,
            duration_seconds=timing_qc.get("duration_seconds"),
        )
    if semantic_qc.get("passed") is not True:
        failure_reasons = semantic_qc.get("failure_reasons") or [
            "overlay_semantic_qc_failed"
        ]
        raise ValueError(
            "burned_overlay_semantic_incomplete:"
            + ",".join(str(reason) for reason in failure_reasons)
            + f":{asset['renderedAssetId']}"
        )
    if semantic_qc.get("timed_sequence") is True:
        assert isinstance(timing_qc, dict)
        timing_qc = {
            **timing_qc,
            "applicable": True,
            "passed": True,
            "failure_reasons": [],
            "segment_count": int(timing_qc.get("segment_count") or 0),
            "duration_seconds": timing_qc.get("duration_seconds"),
        }
    else:
        timing_qc = {
            "schema": "pipeline.overlay_timing_qc.v1",
            "applicable": False,
            "passed": True,
            "failure_reasons": [],
            "segment_count": 0,
            "duration_seconds": None,
        }
    return semantic_qc, timing_qc


def asset_caption_is_burned(asset: dict[str, Any]) -> bool:
    for record in (
        asset,
        asset.get("generatedAssetLineage"),
        asset.get("captionOutcomeContext"),
        asset.get("captionGeneration"),
    ):
        if not isinstance(record, dict):
            continue
        for key in ("captionBurnedIn", "caption_burned_in"):
            if isinstance(record.get(key), bool):
                return bool(record[key])
    # Legacy assets with caption text fail closed as burned overlays.
    return bool(str(asset.get("caption") or "").strip())


def learning_cohort_metadata(asset: dict[str, Any]) -> dict[str, Any] | None:
    candidates = (
        asset.get("learningCohort"),
        asset.get("learning_cohort"),
        (asset.get("sourcePrompt") or {}).get("learning_cohort")
        if isinstance(asset.get("sourcePrompt"), dict)
        else None,
        (asset.get("generatedAssetLineage") or {}).get("learning_cohort")
        if isinstance(asset.get("generatedAssetLineage"), dict)
        else None,
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("cohort_id"):
            return dict(candidate)
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
