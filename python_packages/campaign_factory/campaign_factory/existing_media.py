"""Exact-lineage intake for already-finished Creator OS video.

This module deliberately does not import a provider adapter. It reconciles
existing bytes and retained receipts only; it never copies, re-encodes, uploads,
exports, schedules, or publishes media.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import connect_sqlite

from .config import get_settings
from .db import init_db

INTAKE_SCHEMA = "creator_os.existing_video_intake.v1"
INTAKE_RECEIPT_SCHEMA = "creator_os.existing_video_intake_receipt.v1"
REVIEW_SCHEMA = "creator_os.existing_video_review.v2"
REVIEW_SUMMARY_SCHEMA = "creator_os.existing_video_review_summary.v1"
ATTACHMENT_SCHEMA = "creator_os.existing_video_plan_attachment.v1"
CONTRACT_VERSION = "existing-video-intake.v1"
REVIEW_CONTRACT_VERSION = "existing-video-review.v2"
REVIEW_VERDICTS = frozenset({"WOULD_POST", "USABLE_AFTER_EDIT", "REJECT"})
REVIEW_RESULTS = frozenset({"identity", "anatomy", "motion", "phoneNative", "audioFit"})
REJECTION_REASONS = frozenset(
    {
        "IDENTITY_FAILURE",
        "BODY_PROPORTION_FAILURE",
        "ANATOMY_FAILURE",
        "MOTION_UNNATURAL",
        "EXPRESSION_MISMATCH",
        "LIGHTING_SYNTHETIC",
        "SETTING_DRIFT",
        "OUTFIT_DRIFT",
        "CAMERA_FAILURE",
        "AUDIO_MISMATCH",
        "PROMPT_MISMATCH",
        "DUPLICATE_OR_TOO_SIMILAR",
        "NOT_POSTABLE_GENERAL",
    }
)
STRUCTURAL_BLOCKERS = frozenset(
    {
        "manifest_schema_invalid",
        "creator_missing",
        "campaign_missing",
        "content_intent_missing",
        "intended_account_missing",
        "identity_profile_missing",
        "final_media_missing",
        "final_media_symlinked",
        "final_sha_mismatch",
        "final_media_corrupt",
        "final_geometry_invalid",
        "final_video_codec_invalid",
        "final_duration_invalid",
        "final_audio_invalid",
        "source_not_unique",
        "source_sha_mismatch",
        "source_bytes_missing",
        "source_creator_mismatch",
        "source_campaign_mismatch",
        "generation_attempt_missing",
        "generation_source_mismatch",
        "generation_visual_sha_mismatch",
        "generation_id_missing",
        "generation_id_mismatch",
        "generation_provider_invalid",
        "generation_model_missing",
        "generation_recipe_missing",
        "generation_prompt_missing",
        "generation_seed_missing",
        "generation_receipt_missing",
        "generation_receipt_sha_mismatch",
        "generation_receipt_id_mismatch",
        "generation_receipt_not_completed",
        "audio_receipt_missing",
        "audio_receipt_sha_mismatch",
        "audio_final_sha_mismatch",
        "audio_visual_sha_mismatch",
        "audio_music_id_missing",
        "audio_track_sha_missing",
        "audio_acoustic_fingerprint_missing",
        "audio_segment_missing",
        "audio_segment_sha_missing",
        "audio_fulfillment_invalid",
        "audio_duration_mismatch",
        "technical_qc_receipt_sha_mismatch",
        "technical_qc_subject_mismatch",
        "creator_hash_conflict",
        "generation_final_conflict",
        "published_identity_conflict",
        "canonical_asset_conflict",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _resolved_file(value: Any) -> Path:
    return Path(_text(value)).expanduser().resolve()


def _default_probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ValueError("ffprobe failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("ffprobe returned invalid output")
    return value


def _verified_binding(binding: Any, *, missing: str, mismatch: str) -> tuple[Path, str]:
    value = _record(binding)
    path = _resolved_file(value.get("path"))
    expected = _text(value.get("sha256")).lower()
    if not expected or not path.is_file() or path.is_symlink():
        raise ValueError(missing)
    if _sha256(path) != expected:
        raise ValueError(mismatch)
    return path, expected


def _worker_generation(worker: dict[str, Any]) -> dict[str, Any]:
    paid = _record(worker.get("paidGenerationEvidence"))
    if paid:
        return paid
    nested = _record(worker.get("worker"))
    return _record(nested.get("paidGenerationEvidence"))


def _audio_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    intent = _record(receipt.get("audioIntent"))
    fulfillment = _record(intent.get("fulfillment"))
    selection = _record(receipt.get("selection"))
    advisory = _record(selection.get("advisoryLabels"))
    selected_track = _record(receipt.get("selectedTrack"))
    acquisition = _record(selected_track.get("acquisitionReceipt"))
    segment = _record(receipt.get("selectedSegment"))
    platform_ids = selection.get("platformSoundIds")
    platform_ids = platform_ids if isinstance(platform_ids, list) else []
    tiktok_ids = [
        _text(_record(value).get("soundId"))
        for value in platform_ids
        if _text(_record(value).get("platform")).lower() == "tiktok"
    ]
    return {
        "musicId": next((value for value in tiktok_ids if value), ""),
        "sourceTrackSha256": _text(
            selected_track.get("acquiredAudioSha256")
            or acquisition.get("byte_sha256")
            or fulfillment.get("acquired_audio_sha256")
        ).lower(),
        "acousticFingerprint": _text(advisory.get("acousticFingerprint")).lower(),
        "processedSegmentSha256": _text(
            segment.get("processed_segment_sha256")
        ).lower(),
        "processedSegmentDecodedAudioFingerprint": _text(
            segment.get("decoded_audio_fingerprint")
        ).lower(),
        "segmentStartSeconds": segment.get("start_offset_seconds"),
        "segmentDurationSeconds": segment.get("duration_seconds"),
        "fulfillmentOutputSha256": _text(fulfillment.get("output_sha256")).lower(),
        "fulfillmentStatus": _text(fulfillment.get("status")).lower(),
        "audioPresent": fulfillment.get("audio_present"),
        "proofType": _text(fulfillment.get("proof_type")),
    }


def inspect_intake(
    conn: sqlite3.Connection,
    manifest_path: Path,
    *,
    probe: Callable[[Path], dict[str, Any]] = _default_probe,
) -> dict[str, Any]:
    """Resolve one exact intake without writing files or database rows."""

    before = conn.total_changes
    manifest_path = manifest_path.expanduser().resolve()
    manifest = _load_json(manifest_path)
    manifest_sha = _sha256(manifest_path)
    blockers: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema") != INTAKE_SCHEMA:
        blockers.append("manifest_schema_invalid")

    creator = _text(manifest.get("creator")).lower()
    campaign_slug = _text(manifest.get("campaign"))
    account = _text(manifest.get("intendedAccount"))
    intent = _text(manifest.get("contentIntent"))
    identity_profile = _text(manifest.get("identityProfile"))
    for value, reason in (
        (creator, "creator_missing"),
        (campaign_slug, "campaign_missing"),
        (account, "intended_account_missing"),
        (intent, "content_intent_missing"),
        (identity_profile, "identity_profile_missing"),
    ):
        if not value:
            blockers.append(reason)

    final_binding = _record(manifest.get("finalMedia"))
    final_path = _resolved_file(final_binding.get("path"))
    final_sha = _text(final_binding.get("sha256")).lower()
    if not final_path.is_file():
        blockers.append("final_media_missing")
    elif final_path.is_symlink():
        blockers.append("final_media_symlinked")
    elif not final_sha or _sha256(final_path) != final_sha:
        blockers.append("final_sha_mismatch")

    probe_result: dict[str, Any] = {}
    if final_path.is_file() and not final_path.is_symlink():
        try:
            probe_result = probe(final_path)
        except (OSError, ValueError, json.JSONDecodeError):
            blockers.append("final_media_corrupt")
    streams = probe_result.get("streams")
    streams = streams if isinstance(streams, list) else []
    videos = [
        _record(value)
        for value in streams
        if _text(_record(value).get("codec_type")) == "video"
    ]
    audios = [
        _record(value)
        for value in streams
        if _text(_record(value).get("codec_type")) == "audio"
    ]
    if probe_result and (
        len(videos) != 1
        or videos[0].get("width") != 1080
        or videos[0].get("height") != 1920
    ):
        blockers.append("final_geometry_invalid")
    if probe_result and (not videos or videos[0].get("codec_name") != "h264"):
        blockers.append("final_video_codec_invalid")
    try:
        final_duration = float(
            _text(_record(probe_result.get("format")).get("duration"))
        )
    except (TypeError, ValueError):
        final_duration = 0.0
    if probe_result and final_duration <= 0:
        blockers.append("final_duration_invalid")
    if probe_result and (
        len(audios) != 1
        or audios[0].get("codec_name") != "aac"
        or int(audios[0].get("channels") or 0) != 2
    ):
        blockers.append("final_audio_invalid")

    source_manifest = _record(manifest.get("source"))
    source_id = _text(source_manifest.get("id"))
    source_sha = _text(source_manifest.get("sha256")).lower()
    source_rows = conn.execute(
        """
        SELECT s.*, m.slug AS creator_slug, c.slug AS campaign_slug
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        JOIN campaigns c ON c.id = s.campaign_id
        WHERE s.id = ? AND s.content_hash = ?
        """,
        (source_id, source_sha),
    ).fetchall()
    source: dict[str, Any] = dict(source_rows[0]) if len(source_rows) == 1 else {}
    if len(source_rows) != 1:
        blockers.append("source_not_unique")
    else:
        source_path = _resolved_file(source.get("stored_path"))
        if not source_path.is_file() or source_path.is_symlink():
            blockers.append("source_bytes_missing")
        elif _sha256(source_path) != source_sha:
            blockers.append("source_sha_mismatch")
        if _text(source.get("creator_slug")).lower() != creator:
            blockers.append("source_creator_mismatch")
        if _text(source.get("campaign_slug")) != campaign_slug:
            blockers.append("source_campaign_mismatch")
        if _text(source.get("status")).lower() != "approved":
            blockers.append("blocked_unapproved_source")

    generation_manifest = _record(manifest.get("generation"))
    attempt_id = _text(generation_manifest.get("attemptId"))
    generation_row = conn.execute(
        """
        SELECT ga.*, gob.content_sha256 AS visual_sha256,
               ra.content_hash AS registered_generation_asset_sha
        FROM generation_attempts ga
        JOIN generation_output_blobs gob ON gob.id = ga.output_blob_id
        JOIN rendered_assets ra ON ra.id = ga.rendered_asset_id
        WHERE ga.id = ?
        """,
        (attempt_id,),
    ).fetchone()
    generation = dict(generation_row) if generation_row else {}
    if not generation:
        blockers.append("generation_attempt_missing")
    elif source and generation.get("source_asset_id") != source.get("id"):
        blockers.append("generation_source_mismatch")

    visual = _record(manifest.get("visualInput"))
    visual_sha = _text(visual.get("sha256")).lower()
    visual_path = _resolved_file(visual.get("path"))
    if (
        not visual_sha
        or not visual_path.is_file()
        or visual_path.is_symlink()
        or _sha256(visual_path) != visual_sha
        or (generation and generation.get("visual_sha256") != visual_sha)
    ):
        blockers.append("generation_visual_sha_mismatch")

    worker = _record(
        json.loads(generation.get("worker_result_json") or "{}") if generation else {}
    )
    paid = _worker_generation(worker)
    generation_id = _text(generation_manifest.get("generationId"))
    if not generation_id:
        blockers.append("generation_id_missing")
    elif _text(paid.get("generationId")) != generation_id:
        blockers.append("generation_id_mismatch")
    if _text(paid.get("provider")).lower() != "higgsfield":
        blockers.append("generation_provider_invalid")
    model = _text(generation_manifest.get("model") or paid.get("providerModel"))
    recipe = _text(generation_manifest.get("recipe"))
    prompt = _text(generation_manifest.get("prompt"))
    seed = generation_manifest.get("seed")
    for value, reason in (
        (model, "generation_model_missing"),
        (recipe, "generation_recipe_missing"),
        (prompt, "generation_prompt_missing"),
    ):
        if not value:
            blockers.append(reason)
    if seed is None:
        blockers.append("generation_seed_missing")
    try:
        generation_receipt_path, generation_receipt_sha = _verified_binding(
            generation_manifest.get("receipt"),
            missing="generation_receipt_missing",
            mismatch="generation_receipt_sha_mismatch",
        )
    except ValueError as exc:
        blockers.append(str(exc))
        generation_receipt_path, generation_receipt_sha = Path(), ""
    if generation_receipt_sha:
        generation_receipt = _load_json(generation_receipt_path)
        receipt_generation_id = _text(
            generation_receipt.get("generationId")
            or generation_receipt.get("predictionId")
            or generation_receipt.get("requestId")
        )
        if receipt_generation_id != generation_id:
            blockers.append("generation_receipt_id_mismatch")
        if _text(generation_receipt.get("status")).lower() not in {
            "completed",
            "succeeded",
            "success",
        }:
            blockers.append("generation_receipt_not_completed")

    try:
        audio_receipt_path, audio_receipt_sha = _verified_binding(
            manifest.get("audioReceipt"),
            missing="audio_receipt_missing",
            mismatch="audio_receipt_sha_mismatch",
        )
        audio_receipt = _load_json(audio_receipt_path)
    except ValueError as exc:
        blockers.append(str(exc))
        audio_receipt_path, audio_receipt_sha, audio_receipt = Path(), "", {}
    audio_final = _record(audio_receipt.get("finalVideo"))
    audio_original = _record(audio_receipt.get("originalVideo"))
    if audio_receipt and _text(audio_final.get("sha256")).lower() != final_sha:
        blockers.append("audio_final_sha_mismatch")
    if audio_receipt and _text(audio_original.get("sha256")).lower() != visual_sha:
        blockers.append("audio_visual_sha_mismatch")
    audio = _audio_identity(audio_receipt)
    for field, reason in (
        ("musicId", "audio_music_id_missing"),
        ("sourceTrackSha256", "audio_track_sha_missing"),
        ("acousticFingerprint", "audio_acoustic_fingerprint_missing"),
        ("processedSegmentSha256", "audio_segment_sha_missing"),
    ):
        if not audio.get(field):
            blockers.append(reason)
    if (
        audio.get("segmentStartSeconds") is None
        or audio.get("segmentDurationSeconds") is None
    ):
        blockers.append("audio_segment_missing")
    if (
        audio.get("fulfillmentOutputSha256") != final_sha
        or audio.get("fulfillmentStatus") != "verified"
        or audio.get("audioPresent") is not True
        or audio.get("proofType") != "embedded_output_audio_stream"
    ):
        blockers.append("audio_fulfillment_invalid")
    verification = _record(audio_receipt.get("verification"))
    try:
        verified_duration = float(_text(verification.get("durationSeconds")))
    except (TypeError, ValueError):
        verified_duration = 0.0
    if audio_receipt and (
        verified_duration <= 0 or abs(verified_duration - final_duration) > 0.05
    ):
        blockers.append("audio_duration_mismatch")

    qc_binding = _record(manifest.get("technicalQcReceipt"))
    qc_path = _resolved_file(qc_binding.get("path")) if qc_binding else Path()
    qc_sha = _text(qc_binding.get("sha256")).lower()
    qc_status = "missing"
    if not qc_binding:
        blockers.append("technical_qc_receipt_missing")
    elif not qc_path.is_file() or qc_path.is_symlink():
        blockers.append("technical_qc_receipt_missing")
    elif _sha256(qc_path) != qc_sha:
        blockers.append("technical_qc_receipt_sha_mismatch")
    else:
        qc = _load_json(qc_path)
        qc_subject = _text(
            qc.get("subjectSha256") or qc.get("mediaSha256") or qc.get("outputSha256")
        ).lower()
        qc_status = _text(qc.get("status")).lower()
        if qc_subject != final_sha:
            blockers.append("technical_qc_subject_mismatch")
        if qc.get("passed") is not True and qc_status != "passed":
            blockers.append("technical_qc_not_passed")
        else:
            qc_status = "passed"

    conflicting_creator = conn.execute(
        """
        SELECT ra.id
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        WHERE ra.content_hash = ? AND lower(m.slug) <> lower(?)
        LIMIT 1
        """,
        (final_sha, creator),
    ).fetchone()
    if conflicting_creator:
        blockers.append("creator_hash_conflict")
    existing_rows = (
        conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (source.get("campaign_id"), final_sha),
        ).fetchall()
        if source
        else []
    )
    existing = dict(existing_rows[0]) if len(existing_rows) == 1 else {}
    if len(existing_rows) > 1:
        blockers.append("canonical_asset_conflict")
    if existing and existing.get("source_asset_id") != source_id:
        blockers.append("canonical_asset_conflict")

    generation_conflict = (
        conn.execute(
            """
        SELECT emi.final_sha256
        FROM existing_media_intakes emi
        WHERE emi.generation_attempt_id = ? AND emi.final_sha256 <> ?
        LIMIT 1
        """,
            (attempt_id, final_sha),
        ).fetchone()
        if _table_exists(conn, "existing_media_intakes")
        else None
    )
    if (
        generation_conflict
        and _text(manifest.get("derivationKind")) != "embedded_audio_final"
    ):
        blockers.append("generation_final_conflict")

    if existing:
        published = conn.execute(
            """
            SELECT 1 FROM proof_runs
            WHERE rendered_asset_id = ? AND threadsdash_post_id IS NOT NULL
            UNION ALL
            SELECT 1 FROM variant_account_usage
            WHERE rendered_asset_id = ? AND published_at IS NOT NULL
            LIMIT 1
            """,
            (existing["id"], existing["id"]),
        ).fetchone()
        if published:
            blockers.append("published_identity_conflict")

    intake_identity = _fingerprint(
        {
            "contract": CONTRACT_VERSION,
            "creator": creator,
            "finalSha256": final_sha,
            "generationId": generation_id,
            "audioFulfillment": audio.get("fulfillmentOutputSha256"),
        }
    )
    review_exists = False
    if existing and _table_exists(conn, "existing_media_asset_reviews"):
        review_exists = bool(
            conn.execute(
                """
                SELECT 1 FROM existing_media_asset_reviews
                WHERE rendered_asset_id = ? AND final_sha256 = ?
                  AND verdict = 'WOULD_POST'
                """,
                (existing["id"], final_sha),
            ).fetchone()
        )
    if not review_exists:
        blockers.append("creative_review_missing")

    blockers = list(dict.fromkeys(blockers))
    structural = [value for value in blockers if value in STRUCTURAL_BLOCKERS]
    registration_allowed = not structural
    eligibility = "ELIGIBLE" if not blockers else "BLOCKED"
    mutations = {
        "registerRenderedAsset": not bool(existing),
        "recordIntakeReceipt": registration_allowed,
        "copyOrRewriteMedia": False,
        "approveSource": False,
        "createCreativeApproval": False,
        "attachPlanItem": False,
        "export": False,
        "schedule": False,
        "publish": False,
    }
    result = {
        "schema": "creator_os.existing_video_intake_preview.v1",
        "contractVersion": CONTRACT_VERSION,
        "dryRun": True,
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha},
        "intakeIdentity": intake_identity,
        "creator": creator,
        "campaign": campaign_slug,
        "intendedAccount": account,
        "contentIntent": intent,
        "identityProfile": identity_profile,
        "source": {
            "id": source_id,
            "sha256": source_sha,
            "status": source.get("status"),
            "bytesPresent": bool(source),
        },
        "generation": {
            "attemptId": attempt_id,
            "generationId": generation_id,
            "provider": _text(paid.get("provider")),
            "model": model,
            "recipe": recipe,
            "prompt": prompt,
            "seed": seed,
            "receiptPath": str(generation_receipt_path)
            if generation_receipt_sha
            else None,
            "receiptSha256": generation_receipt_sha or None,
            "originalCost": {
                "quote": paid.get("quote"),
                "creditsConsumed": paid.get("creditsConsumed"),
                "costEventIds": paid.get("costEventIds"),
            },
        },
        "visualInput": {"path": str(visual_path), "sha256": visual_sha},
        "finalMedia": {
            "path": str(final_path),
            "sha256": final_sha,
            "probe": probe_result,
        },
        "audio": {
            **audio,
            "receiptPath": str(audio_receipt_path) if audio_receipt_sha else None,
            "receiptSha256": audio_receipt_sha or None,
        },
        "technicalQc": {
            "status": qc_status,
            "receiptPath": str(qc_path) if qc_sha else None,
            "receiptSha256": qc_sha or None,
        },
        "creativeReview": {
            "exactWouldPostApprovalExists": review_exists,
            "operatorChatReview": _record(manifest.get("operatorReview")).get("status"),
            "chatReviewIsDurableApproval": False,
        },
        "canonicalAsset": {
            "exists": bool(existing),
            "id": existing.get("id"),
            "state": existing.get("review_state"),
        },
        "eligibility": eligibility,
        "registrationAllowed": registration_allowed,
        "blockers": blockers,
        "warnings": warnings,
        "wouldMutate": mutations,
        "providerCalls": 0,
        "mediaWrites": 0,
        "persistentWrites": conn.total_changes - before,
    }
    return result


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    )


def apply_intake(conn: sqlite3.Connection, preview: dict[str, Any]) -> dict[str, Any]:
    if not preview.get("registrationAllowed"):
        raise ValueError("intake blocked: " + ",".join(preview.get("blockers") or []))
    init_db(conn)
    existing = _record(preview.get("canonicalAsset"))
    now = _now()
    source = _record(preview.get("source"))
    final = _record(preview.get("finalMedia"))
    generation = _record(preview.get("generation"))
    audio = _record(preview.get("audio"))
    qc = _record(preview.get("technicalQc"))
    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE slug = ?", (preview["campaign"],)
    ).fetchone()
    if campaign is None:
        raise ValueError("campaign missing during apply")
    asset_id = _text(existing.get("id")) or f"asset_existing_{final['sha256'][:16]}"
    parent = conn.execute(
        "SELECT rendered_asset_id FROM generation_attempts WHERE id = ?",
        (generation["attemptId"],),
    ).fetchone()
    metadata = {
        "schema": INTAKE_RECEIPT_SCHEMA,
        "contractVersion": CONTRACT_VERSION,
        "intakeIdentity": preview["intakeIdentity"],
        "derivation": {
            "kind": "embedded_audio_final",
            "visualInput": preview["visualInput"],
            "generationAttemptId": generation["attemptId"],
            "generationId": generation["generationId"],
        },
        "creator": preview["creator"],
        "intendedAccount": preview["intendedAccount"],
        "contentIntent": preview["contentIntent"],
        "identityProfile": preview["identityProfile"],
        "generation": generation,
        "audio": audio,
        "technicalQc": qc,
        "blockers": preview["blockers"],
        "providerCalls": 0,
        "mediaMutated": False,
    }
    if not existing.get("exists"):
        conn.execute(
            """
            INSERT INTO rendered_assets (
              id, campaign_id, source_asset_id, parent_asset_id, content_hash,
              output_path, campaign_path, filename, media_type, content_surface,
              creator_model, frame_type, length_class, format_class, recipe,
              target_ratio, metadata_json, audit_status, review_state,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'video', 'reel', ?,
                      'generated_motion', 'short', 'vertical', ?, '9:16', ?, ?, ?,
                      ?, ?)
            """,
            (
                asset_id,
                campaign["id"],
                source["id"],
                parent["rendered_asset_id"] if parent else None,
                final["sha256"],
                final["path"],
                campaign["root_path"],
                Path(final["path"]).name,
                preview["creator"],
                generation["recipe"],
                _json(metadata),
                "approved_candidate"
                if qc.get("status") == "passed"
                else "needs_review",
                "review_ready",
                now,
                now,
            ),
        )
    else:
        row = conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if (
            row is None
            or row["content_hash"] != final["sha256"]
            or row["source_asset_id"] != source["id"]
            or Path(row["output_path"]).expanduser().resolve()
            != Path(final["path"]).expanduser().resolve()
        ):
            raise ValueError("canonical asset conflict during reconciliation")

    receipt = {
        **preview,
        "schema": INTAKE_RECEIPT_SCHEMA,
        "dryRun": False,
        "renderedAssetId": asset_id,
        "reconciled": bool(existing.get("exists")),
        "appliedAt": now,
        "providerCalls": 0,
        "mediaWrites": 0,
    }
    conn.execute(
        """
        INSERT INTO existing_media_intakes (
          id, intake_identity, campaign_id, source_asset_id, rendered_asset_id,
          generation_attempt_id, final_sha256, manifest_path, manifest_sha256,
          audio_receipt_path, audio_receipt_sha256, qc_receipt_path,
          qc_receipt_sha256, eligibility_state, receipt_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(intake_identity) DO UPDATE SET
          updated_at = excluded.updated_at
        """,
        (
            f"intake_{preview['intakeIdentity'][:20]}",
            preview["intakeIdentity"],
            campaign["id"],
            source["id"],
            asset_id,
            generation["attemptId"],
            final["sha256"],
            preview["manifest"]["path"],
            preview["manifest"]["sha256"],
            audio["receiptPath"],
            audio["receiptSha256"],
            qc.get("receiptPath"),
            qc.get("receiptSha256"),
            preview["eligibility"],
            _json(receipt),
            now,
            now,
        ),
    )
    conn.commit()
    return receipt


def review_existing_asset(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    final_sha256: str,
    reviewer: str,
    verdict: str,
    results: dict[str, str] | None,
    rejection_reasons: list[str] | tuple[str, ...] | None = None,
    notes: str | None,
    apply: bool,
) -> dict[str, Any]:
    verdict = verdict.upper()
    if verdict not in REVIEW_VERDICTS:
        raise ValueError("unsupported review verdict")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    row = conn.execute(
        """
        SELECT ra.*, m.slug AS creator, sa.content_hash AS source_sha256
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        WHERE ra.id = ?
        """,
        (rendered_asset_id,),
    ).fetchone()
    if row is None:
        raise ValueError("rendered asset not found")
    asset = dict(row)
    final_sha256 = final_sha256.lower()
    path = _resolved_file(asset["output_path"])
    if asset["content_hash"] != final_sha256 or _sha256(path) != final_sha256:
        raise ValueError("review final SHA does not match exact asset bytes")
    normalized_results = {
        key: _text(value).upper()
        for key, value in (results or {}).items()
        if key in REVIEW_RESULTS and _text(value)
    }
    normalized_reasons = sorted(
        {_text(value).upper() for value in (rejection_reasons or []) if _text(value)}
    )
    unsupported = set(normalized_reasons) - REJECTION_REASONS
    if unsupported:
        raise ValueError(
            "unsupported rejection reason: " + ", ".join(sorted(unsupported))
        )
    intake_row = conn.execute(
        """
        SELECT receipt_json FROM existing_media_intakes
        WHERE rendered_asset_id = ? AND final_sha256 = ?
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (rendered_asset_id, final_sha256),
    ).fetchone()
    intake = _record(json.loads(intake_row["receipt_json"])) if intake_row else {}
    generation = _record(intake.get("generation"))
    metadata = _record(json.loads(asset.get("metadata_json") or "{}"))
    paid_generation = _record(metadata.get("paidGenerationEvidence"))
    production_recipe = _record(metadata.get("productionMotionRecipe"))
    if not generation:
        generation = {
            "provider": paid_generation.get("provider"),
            "model": paid_generation.get("providerModel") or metadata.get("modelId"),
            "recipe": production_recipe.get("recipeId"),
            "generationId": paid_generation.get("generationId"),
            "seed": paid_generation.get("seed"),
        }
    prompt_card = _record(metadata.get("promptCard"))
    compiled_prompt = _record(metadata.get("compiledPrompt"))
    source_class = _text(metadata.get("sourceClass") or asset.get("frame_type")) or None
    evidence = {
        "sourceSha256": _text(asset.get("source_sha256")) or None,
        "promptCardFingerprint": _text(
            prompt_card.get("promptCardFingerprint")
            or metadata.get("promptCardFingerprint")
        )
        or None,
        "compiledPromptFingerprint": _text(
            compiled_prompt.get("compiledPromptFingerprint")
            or metadata.get("compiledPromptFingerprint")
        )
        or None,
        "provider": _text(generation.get("provider")) or None,
        "modelTool": _text(generation.get("model")) or None,
        "recipeId": _text(generation.get("recipe")) or None,
        "generationId": _text(generation.get("generationId")) or None,
        "seed": generation.get("seed")
        if isinstance(generation.get("seed"), int)
        else None,
        "contentIntent": _text(
            intake.get("contentIntent") or metadata.get("contentIntent")
        )
        or None,
        "sourceClass": source_class,
    }
    core = {
        "schema": REVIEW_SCHEMA,
        "contractVersion": REVIEW_CONTRACT_VERSION,
        "renderedAssetId": rendered_asset_id,
        "finalSha256": final_sha256,
        "creator": asset["creator"],
        "reviewer": reviewer,
        "verdict": verdict,
        "rejectionReasons": normalized_reasons,
        "results": normalized_results,
        "notes": notes,
        **evidence,
    }
    review_id = f"review_existing_{_fingerprint(core)[:20]}"
    preview = {
        **core,
        "reviewId": review_id,
        "dryRun": not apply,
        "wouldChangeReviewStateTo": (
            "approved"
            if verdict == "WOULD_POST"
            else "rejected"
            if verdict == "REJECT"
            else "needs_edit"
        ),
    }
    if not apply:
        return preview
    init_db(conn)
    now = _now()
    conn.execute(
        """
        INSERT OR IGNORE INTO existing_media_asset_reviews (
          id, rendered_asset_id, final_sha256, source_sha256,
          prompt_card_fingerprint, compiled_prompt_fingerprint, provider,
          model_tool, recipe_id, generation_id, seed, creator, content_intent, source_class,
          reviewer, verdict, rejection_reasons_json, results_json, notes,
          contract_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id,
            rendered_asset_id,
            final_sha256,
            evidence["sourceSha256"],
            evidence["promptCardFingerprint"],
            evidence["compiledPromptFingerprint"],
            evidence["provider"],
            evidence["modelTool"],
            evidence["recipeId"],
            evidence["generationId"],
            evidence["seed"],
            asset["creator"],
            evidence["contentIntent"],
            evidence["sourceClass"],
            reviewer,
            verdict,
            _json(normalized_reasons),
            _json(normalized_results),
            notes,
            REVIEW_CONTRACT_VERSION,
            now,
        ),
    )
    state = preview["wouldChangeReviewStateTo"]
    conn.execute(
        "UPDATE rendered_assets SET review_state = ?, updated_at = ? WHERE id = ?",
        (state, now, rendered_asset_id),
    )
    conn.commit()
    return {**preview, "dryRun": False, "reviewedAt": now}


def summarize_existing_reviews(conn: sqlite3.Connection) -> dict[str, Any]:
    """Summarize only explicitly recorded reasons; blanks remain unknown."""

    columns = (
        {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(existing_media_asset_reviews)"
            ).fetchall()
        }
        if _table_exists(conn, "existing_media_asset_reviews")
        else set()
    )

    def selected(column: str) -> str:
        return column if column in columns else f"NULL AS {column}"

    rows = (
        conn.execute(
            f"""
            SELECT creator, {selected("content_intent")}, {selected("provider")},
                   {selected("model_tool")}, {selected("recipe_id")},
                   {selected("source_class")}, {selected("rejection_reasons_json")}
            FROM existing_media_asset_reviews
            ORDER BY created_at, id
            """
        ).fetchall()
        if _table_exists(conn, "existing_media_asset_reviews")
        else []
    )
    counts: dict[tuple[str, str, str, str, str], int] = {}
    reviewed = 0
    explicit = 0
    for row in rows:
        reviewed += 1
        try:
            reasons = json.loads(row["rejection_reasons_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            reasons = []
        if not isinstance(reasons, list):
            reasons = []
        for reason in reasons:
            normalized = _text(reason).upper()
            if normalized not in REJECTION_REASONS:
                continue
            explicit += 1
            key = (
                _text(row["creator"]) or "unknown",
                _text(row["content_intent"]) or "unknown",
                "/".join(
                    value
                    for value in (
                        _text(row["provider"]),
                        _text(row["model_tool"]),
                        _text(row["recipe_id"]),
                    )
                    if value
                )
                or "unknown",
                _text(row["source_class"]) or "unknown",
                normalized,
            )
            counts[key] = counts.get(key, 0) + 1
    return {
        "schema": REVIEW_SUMMARY_SCHEMA,
        "predictiveClaim": False,
        "reviewCount": reviewed,
        "explicitReasonCount": explicit,
        "groups": [
            {
                "creator": key[0],
                "intent": key[1],
                "modelRecipe": key[2],
                "sourceClass": key[3],
                "rejectionReason": key[4],
                "count": count,
            }
            for key, count in sorted(counts.items())
        ],
    }


def attach_existing_to_plan(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    plan_item_id: str,
    rendered_asset_id: str,
    apply: bool,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT pi.*, pv.status AS plan_status, pv.creator AS plan_creator,
               pv.identity_profile AS plan_identity_profile,
               ra.content_hash AS final_sha256, ra.output_path, ra.source_asset_id,
               ra.metadata_json, ra.review_state, ra.audit_status,
               sa.status AS source_status, m.slug AS asset_creator
        FROM creative_plan_items pi
        JOIN creative_plan_versions pv ON pv.id = pi.plan_version_id
        JOIN rendered_assets ra ON ra.id = ?
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        WHERE (pv.id = ? OR pv.creative_plan_id = ?) AND pi.id = ?
        """,
        (rendered_asset_id, plan_id, plan_id, plan_item_id),
    ).fetchone()
    if row is None:
        raise ValueError("plan, item, or rendered asset not found")
    value = dict(row)
    intake = conn.execute(
        """
        SELECT receipt_json FROM existing_media_intakes
        WHERE rendered_asset_id = ? AND final_sha256 = ?
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (rendered_asset_id, value["final_sha256"]),
    ).fetchone()
    metadata = _record(
        json.loads(intake["receipt_json"])
        if intake is not None
        else json.loads(value["metadata_json"] or "{}")
    )
    blockers: list[str] = []
    if value["asset_creator"].lower() != value["creator"].lower():
        blockers.append("creator_mismatch")
    if value["asset_creator"].lower() != value["plan_creator"].lower():
        blockers.append("plan_creator_mismatch")
    if _text(metadata.get("contentIntent")) != value["content_intent"]:
        blockers.append("content_intent_mismatch")
    if _text(metadata.get("intendedAccount")) != value["target_account"]:
        blockers.append("account_mismatch")
    if _text(metadata.get("identityProfile")) != value["identity_profile"]:
        blockers.append("identity_profile_mismatch")
    if value["source_status"].lower() != "approved":
        blockers.append("blocked_unapproved_source")
    if _record(metadata.get("technicalQc")).get("status") != "passed":
        blockers.append("technical_qc_missing")
    if value["review_state"] != "approved":
        blockers.append("would_post_review_missing")
    review = (
        conn.execute(
            """
            SELECT * FROM existing_media_asset_reviews
            WHERE rendered_asset_id = ? AND final_sha256 = ?
              AND verdict = 'WOULD_POST'
            ORDER BY created_at DESC LIMIT 1
            """,
            (rendered_asset_id, value["final_sha256"]),
        ).fetchone()
        if _table_exists(conn, "existing_media_asset_reviews")
        else None
    )
    if review is None:
        blockers.append("would_post_review_missing")
    if value["audio_policy"] not in {
        "embedded_trending",
        "embedded_trending_required",
        "embedded_trending_audio",
    }:
        blockers.append("audio_policy_mismatch")
    if value["plan_status"] != "APPROVED":
        blockers.append("plan_not_approved")
    prior_generation = _record(json.loads(value["generation_identity_json"] or "{}"))
    idempotent = bool(
        prior_generation
        and prior_generation.get("renderedAssetId") == rendered_asset_id
    )
    if value["execution_state"] not in {"GENERATION_READY", "REVIEW_READY"} and not (
        idempotent and value["execution_state"] == "CREATIVE_APPROVED"
    ):
        blockers.append("plan_item_state_invalid")
    if (
        prior_generation
        and prior_generation.get("renderedAssetId") != rendered_asset_id
    ):
        blockers.append("plan_item_asset_conflict")
    experiment_id = _text(value.get("experiment_id"))
    if experiment_id:
        experiment = conn.execute(
            """
            SELECT variants_json, status FROM creative_plan_experiments
            WHERE id = ? AND plan_version_id = ?
            """,
            (experiment_id, value["plan_version_id"]),
        ).fetchone()
        variants = json.loads(experiment["variants_json"] or "[]") if experiment else []
        variant = _text(value.get("experiment_variant"))
        valid_variants = {
            _text(
                item
                if isinstance(item, str)
                else _record(item).get("name") or _record(item).get("variant")
            )
            for item in variants
        }
        if (
            experiment is None
            or _text(experiment["status"]).upper() not in {"PROPOSED", "ACTIVE"}
            or not variant
            or variant not in valid_variants
        ):
            blockers.append("experiment_assignment_invalid")
    if _record(json.loads(value["export_identity_json"] or "{}")):
        blockers.append("plan_item_already_exported")
    if _record(json.loads(value["publication_identity_json"] or "{}")):
        blockers.append("plan_item_already_published")
    published = conn.execute(
        """
        SELECT 1 FROM proof_runs
        WHERE rendered_asset_id = ? AND threadsdash_post_id IS NOT NULL
        UNION ALL
        SELECT 1 FROM variant_account_usage
        WHERE rendered_asset_id = ? AND published_at IS NOT NULL
        LIMIT 1
        """,
        (rendered_asset_id, rendered_asset_id),
    ).fetchone()
    if published:
        blockers.append("asset_already_published")
    path = _resolved_file(value["output_path"])
    if (
        not path.is_file()
        or path.is_symlink()
        or _sha256(path) != value["final_sha256"]
    ):
        blockers.append("final_media_mismatch")
    blockers = list(dict.fromkeys(blockers))
    receipt = {
        "schema": ATTACHMENT_SCHEMA,
        "contractVersion": CONTRACT_VERSION,
        "planId": value["plan_version_id"],
        "planItemId": plan_item_id,
        "renderedAssetId": rendered_asset_id,
        "finalSha256": value["final_sha256"],
        "attachmentMethod": "existing_canonical_asset",
        "originalGeneration": _record(metadata.get("generation")),
        "attachmentCost": {"credits": 0, "providerCalls": 0},
        "learningDecision": {
            "consulted": True,
            "eligible": False,
            "applied": False,
            "finalChoiceChanged": False,
            "fallbackReason": "insufficient real eligible outcomes",
        },
        "blockers": blockers,
        "dryRun": not apply,
        "idempotent": idempotent,
    }
    if blockers:
        return receipt
    if not apply or receipt["idempotent"]:
        return receipt
    now = _now()
    generation_identity = {
        "schema": ATTACHMENT_SCHEMA,
        "renderedAssetId": rendered_asset_id,
        "finalSha256": value["final_sha256"],
        "method": "existing_canonical_asset",
        "generatedDuringPlan": False,
        "originalGeneration": receipt["originalGeneration"],
        "attachmentCost": receipt["attachmentCost"],
    }
    review_identity = dict(review) if review is not None else {}
    start_state = value["execution_state"]
    if start_state == "GENERATION_READY":
        reconciliation_receipt = {
            **receipt,
            "transition": {
                "from": "GENERATION_READY",
                "to": "REVIEW_READY",
                "reason": "existing media lineage reconciled without generation",
            },
        }
        conn.execute(
            """
            INSERT INTO creative_plan_item_events (
              id, plan_item_id, from_state, to_state, event_type, actor,
              reason, receipt_json, created_at
            ) VALUES (?, ?, 'GENERATION_READY', 'REVIEW_READY',
                      'existing_asset_reconciled', 'authenticated_local_operator',
                      'existing_canonical_asset', ?, ?)
            """,
            (
                f"pitevt_{_fingerprint(reconciliation_receipt)[:16]}",
                plan_item_id,
                _json(reconciliation_receipt),
                now,
            ),
        )
        start_state = "REVIEW_READY"
    conn.execute(
        """
        UPDATE creative_plan_items
        SET source_asset_id = ?, generation_identity_json = ?,
            review_identity_json = ?, execution_state = 'CREATIVE_APPROVED',
            decision_receipt_json = ?, updated_at = ?
        WHERE id = ? AND generation_identity_json = '{}'
        """,
        (
            value["source_asset_id"],
            _json(generation_identity),
            _json(review_identity),
            _json(receipt["learningDecision"]),
            now,
            plan_item_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO creative_plan_item_events (
          id, plan_item_id, from_state, to_state, event_type, actor,
          reason, receipt_json, created_at
        ) VALUES (?, ?, ?, 'CREATIVE_APPROVED', 'existing_asset_attached',
                  'authenticated_local_operator', 'existing_canonical_asset', ?, ?)
        """,
        (
            f"pitevt_{_fingerprint(receipt)[:16]}",
            plan_item_id,
            start_state,
            _json(receipt),
            now,
        ),
    )
    conn.commit()
    return {**receipt, "dryRun": False, "attachedAt": now}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    intake = sub.add_parser("intake")
    intake.add_argument("--manifest", type=Path, required=True)
    intake_mode = intake.add_mutually_exclusive_group(required=True)
    intake_mode.add_argument("--dry-run", action="store_true")
    intake_mode.add_argument("--apply", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("--asset", required=True)
    review.add_argument("--final-sha", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--verdict", choices=sorted(REVIEW_VERDICTS), required=True)
    review.add_argument("--identity")
    review.add_argument("--anatomy")
    review.add_argument("--motion")
    review.add_argument("--phone-native", dest="phoneNative")
    review.add_argument("--audio-fit", dest="audioFit")
    review.add_argument(
        "--rejection-reason",
        action="append",
        default=[],
        choices=sorted(REJECTION_REASONS),
    )
    review.add_argument("--notes")
    review_mode = review.add_mutually_exclusive_group(required=True)
    review_mode.add_argument("--dry-run", action="store_true")
    review_mode.add_argument("--apply", action="store_true")
    attach = sub.add_parser("attach")
    attach.add_argument("--plan", required=True)
    attach.add_argument("--item", required=True)
    attach.add_argument("--asset", required=True)
    attach_mode = attach.add_mutually_exclusive_group(required=True)
    attach_mode.add_argument("--dry-run", action="store_true")
    attach_mode.add_argument("--apply", action="store_true")
    sub.add_parser("review-summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db_path = args.db or get_settings().db_path
    readonly = not bool(getattr(args, "apply", False))
    conn = connect_sqlite(db_path, readonly=readonly)
    try:
        if args.command == "intake":
            preview = inspect_intake(conn, args.manifest)
            result = apply_intake(conn, preview) if args.apply else preview
        elif args.command == "review":
            results = {
                field: getattr(args, field)
                for field in REVIEW_RESULTS
                if getattr(args, field, None)
            }
            result = review_existing_asset(
                conn,
                rendered_asset_id=args.asset,
                final_sha256=args.final_sha,
                reviewer=args.reviewer,
                verdict=args.verdict,
                results=results,
                rejection_reasons=args.rejection_reason,
                notes=args.notes,
                apply=args.apply,
            )
        elif args.command == "attach":
            result = attach_existing_to_plan(
                conn,
                plan_id=args.plan,
                plan_item_id=args.item,
                rendered_asset_id=args.asset,
                apply=args.apply,
            )
        else:
            result = summarize_existing_reviews(conn)
    finally:
        conn.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
