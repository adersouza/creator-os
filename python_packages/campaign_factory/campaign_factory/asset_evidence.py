from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.fileops import sha256_file


def verify_registered_asset_bytes(asset: dict[str, Any]) -> dict[str, Any]:
    path = (
        Path(str(asset.get("campaign_path") or asset.get("output_path") or ""))
        .expanduser()
        .resolve()
    )
    registered = str(asset.get("content_hash") or "")
    try:
        actual = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    except OSError:
        actual = None
    return {
        "path": str(path),
        "registeredSha256": registered or None,
        "actualSha256": actual,
        "passed": bool(registered and actual == registered),
    }


def final_artifact_integrity_for_publishability(
    asset: dict[str, Any], audit: dict[str, Any] | None
) -> dict[str, Any]:
    registered = str(asset.get("content_hash") or asset.get("contentHash") or "")
    audited = (audit or {}).get("finalArtifactIntegrity")
    if isinstance(audited, dict) and audited.get("subjectSha256") == registered:
        return audited
    return verify_registered_asset_bytes(asset)


def verify_final_artifact_integrity(asset: dict[str, Any]) -> dict[str, Any]:
    """Verify the exact final video after every byte-changing operation."""

    byte_check = verify_registered_asset_bytes(asset)
    subject_sha = str(byte_check.get("registeredSha256") or "")
    failures: list[str] = []
    if byte_check["passed"] is not True:
        failures.append("exact_media_sha_mismatch")

    path = Path(str(byte_check["path"]))
    is_video = path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    probe: dict[str, Any] = {}
    probe_error: str | None = None
    if not ffprobe:
        failures.append("ffprobe_unavailable")
    elif byte_check["passed"] is True:
        try:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode == 0:
                decoded = json.loads(completed.stdout or "{}")
                if isinstance(decoded, dict):
                    probe = decoded
            if not probe:
                probe_error = (completed.stderr or "ffprobe_failed").strip()
                failures.append("final_video_probe_failed")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            probe_error = type(exc).__name__
            failures.append("final_video_probe_failed")

    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        {},
    )
    audio_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        {},
    )
    width = _positive_number(video_stream.get("width"))
    height = _positive_number(video_stream.get("height"))
    duration = _positive_number(
        (probe.get("format") or {}).get("duration")
        if isinstance(probe.get("format"), dict)
        else None
    ) or _positive_number(video_stream.get("duration"))
    if probe:
        if not video_stream:
            failures.append("final_video_stream_missing")
        if width is None or height is None:
            failures.append("final_video_geometry_invalid")
        if is_video and duration is None:
            failures.append("final_video_duration_invalid")

    target_ratio = str(asset.get("target_ratio") or "").strip()
    ratio_matches = _ratio_matches(width, height, target_ratio)
    if ratio_matches is False:
        failures.append("final_video_geometry_mismatch")
    expected_duration = _expected_duration(asset)
    duration_matches = (
        None
        if not is_video or expected_duration is None or duration is None
        else abs(duration - expected_duration) <= max(0.25, expected_duration * 0.02)
    )
    if duration_matches is False:
        failures.append("final_video_duration_mismatch")

    decode_error: str | None = None
    decoded_ok = False
    if not ffmpeg:
        failures.append("ffmpeg_unavailable")
    elif byte_check["passed"] is True:
        try:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-f",
                    "null",
                    "-",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            decoded_ok = completed.returncode == 0
            if not decoded_ok:
                decode_error = (completed.stderr or "ffmpeg_decode_failed").strip()
                failures.append("final_video_decode_failed")
        except (OSError, subprocess.TimeoutExpired) as exc:
            decode_error = type(exc).__name__
            failures.append("final_video_decode_failed")

    caption_context = _json_object(asset.get("caption_outcome_context_json"))
    placement = caption_context.get("captionPlacementDecision")
    if not isinstance(placement, dict):
        placement = caption_context.get("caption_placement_decision")
    if not isinstance(placement, dict):
        placement = {}
    burned_caption = caption_context.get("captionBurnedIn") is True
    caption_binding_passed = not burned_caption or placement.get("status") == "passed"
    if not caption_binding_passed:
        failures.append("caption_receipt_final_sha_mismatch")

    generation = _json_object(asset.get("caption_generation_json"))
    audio_intent = generation.get("audioIntent")
    if not isinstance(audio_intent, dict):
        audio_intent = {}
    fulfillment = audio_intent.get("fulfillment")
    fulfillment = fulfillment if isinstance(fulfillment, dict) else {}
    lineage = audio_intent.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    embedded_audio_required = (
        str(audio_intent.get("mode") or "").startswith("embedded_")
        or fulfillment.get("proof_type") == "embedded_output_audio_stream"
    )
    audio_binding_passed = not embedded_audio_required or (
        bool(audio_stream)
        and str(audio_stream.get("codec_name") or "") == "aac"
        and fulfillment.get("audio_present") is True
        and fulfillment.get("output_sha256") == subject_sha
        and lineage.get("finalMediaSha256") == subject_sha
        and _is_sha256(lineage.get("embeddingReceiptSha256"))
    )
    if not audio_binding_passed:
        failures.append("audio_receipt_final_sha_mismatch")

    failures = sorted(set(failures))
    return {
        "schema": "campaign_factory.final_artifact_integrity.v1",
        "subjectSha256": subject_sha or None,
        "mediaKind": "video" if is_video else "image",
        "byteVerification": byte_check,
        "decode": {"passed": decoded_ok, "error": decode_error},
        "probe": {
            "passed": bool(probe),
            "error": probe_error,
            "durationSeconds": duration,
            "expectedDurationSeconds": expected_duration,
            "durationMatches": duration_matches,
            "width": int(width) if width is not None else None,
            "height": int(height) if height is not None else None,
            "targetRatio": target_ratio or None,
            "targetRatioMatches": ratio_matches,
            "videoCodec": video_stream.get("codec_name"),
            "audioCodec": audio_stream.get("codec_name"),
            "audioPresent": bool(audio_stream),
        },
        "captionBinding": {
            "required": burned_caption,
            "subjectSha256": subject_sha or None,
            "placementDecisionFingerprint": _json_fingerprint(placement)
            if placement
            else None,
            "passed": caption_binding_passed,
        },
        "audioBinding": {
            "required": embedded_audio_required,
            "subjectSha256": subject_sha or None,
            "audioIntentFingerprint": _json_fingerprint(audio_intent)
            if audio_intent
            else None,
            "passed": audio_binding_passed,
        },
        "failures": failures,
        "passed": not failures,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _json_fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _ratio_matches(
    width: float | None, height: float | None, target_ratio: str
) -> bool | None:
    if width is None or height is None or not target_ratio:
        return None
    try:
        target_width, target_height = (
            float(value) for value in target_ratio.split(":", 1)
        )
    except (TypeError, ValueError):
        return False
    if target_width <= 0 or target_height <= 0:
        return False
    return abs((width / height) - (target_width / target_height)) <= 0.03


def _expected_duration(asset: dict[str, Any]) -> float | None:
    metadata = _json_object(asset.get("metadata_json"))
    for record in (
        metadata.get("staticMp4Render"),
        metadata.get("productionMotionRecipe"),
        metadata.get("generation"),
        metadata,
    ):
        if not isinstance(record, dict):
            continue
        for key in ("durationSeconds", "duration_seconds", "duration"):
            if (duration := _positive_number(record.get(key))) is not None:
                return duration
    return None


def require_current_asset_audit(
    conn: sqlite3.Connection, asset: dict[str, Any]
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM audit_reports
        WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (asset["id"],),
    ).fetchone()
    if not row:
        raise ValueError("approval blocked: current_sha_audit_missing")
    audit = dict(row)
    if audit.get("subject_sha256") != asset.get("content_hash"):
        raise ValueError("approval blocked: current_sha_audit_mismatch")
    return audit


def invalidate_asset_evidence_after_byte_change(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    previous_sha: str,
    new_sha: str,
    mutation_type: str,
    mutation_receipt: dict[str, Any],
    changed_at: str,
) -> None:
    row = conn.execute(
        "SELECT content_hash, metadata_json FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"rendered asset not found: {rendered_asset_id}")
    if row["content_hash"] not in {previous_sha, new_sha}:
        raise ValueError("asset byte-change previous SHA mismatch")
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    invalidations = metadata.get("evidenceInvalidations")
    if not isinstance(invalidations, list):
        invalidations = []
    record = {
        "previousSha256": previous_sha,
        "newSha256": new_sha,
        "mutationType": mutation_type,
        "mutationReceipt": mutation_receipt,
        "changedAt": changed_at,
    }
    if record not in invalidations:
        invalidations.append(record)
    metadata["evidenceInvalidations"] = invalidations
    conn.execute(
        """
        UPDATE rendered_assets
        SET content_hash = ?, audit_status = 'pending',
            review_state = 'review_ready', metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            new_sha,
            json.dumps(metadata, sort_keys=True),
            changed_at,
            rendered_asset_id,
        ),
    )
