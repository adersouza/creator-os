"""Bind a verified audio derivative to the exact Campaign Factory asset."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_audio_intent

from ..asset_evidence import invalidate_asset_evidence_after_byte_change

class AudioBindingError(RuntimeError):
    """An embedding receipt cannot safely replace the current asset bytes."""


def bind_embedding_receipt(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    embedding_receipt: dict[str, Any],
    bound_at: str,
) -> dict[str, Any]:
    """Atomically bind an Audio Radar derivative and append its lineage edge."""

    policy = str(embedding_receipt.get("policy") or "")
    if embedding_receipt.get(
        "schema"
    ) != "creator_os.audio_embedding_receipt.v1" or policy not in {
        "embedded_trending_required",
        "original_embedded",
    }:
        raise AudioBindingError("receipt has an unsupported embedded-audio policy")
    verification = _record(embedding_receipt.get("verification"), "verification")
    original_video = _record(embedding_receipt.get("originalVideo"), "original video")
    final_video = _record(embedding_receipt.get("finalVideo"), "final video")
    audio_intent = _record(embedding_receipt.get("audioIntent"), "audio intent")
    if (
        verification.get("status") != "verified"
        or verification.get("audioPresent") is not True
        or verification.get("audioCodec") != "aac"
    ):
        raise AudioBindingError("receipt does not prove a verified AAC audio stream")
    validate_audio_intent(audio_intent)
    original_sha = _sha_value(original_video.get("sha256"), "original video")
    final_sha = _sha_value(final_video.get("sha256"), "final video")
    fulfillment = _record(audio_intent.get("fulfillment"), "audio fulfillment")
    if _sha_value(fulfillment.get("output_sha256"), "fulfilled media") != final_sha:
        raise AudioBindingError("audio intent is not bound to the final video")
    final_path = _safe_file(final_video.get("path"))
    if _sha256_file(final_path) != final_sha:
        raise AudioBindingError("final video bytes do not match the receipt")

    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, campaign_id, source_asset_id, content_hash, output_path,
                   caption_generation_json, metadata_json
            FROM rendered_assets
            WHERE id = ?
            """,
            (rendered_asset_id,),
        ).fetchone()
        if row is None:
            raise AudioBindingError(f"rendered asset not found: {rendered_asset_id}")
        current_sha = str(row["content_hash"] or "").strip().lower()
        if current_sha not in {original_sha, final_sha}:
            raise AudioBindingError(
                "rendered asset no longer matches the receipt's original video"
            )
        attempt = conn.execute(
            """
            SELECT id
            FROM generation_attempts
            WHERE rendered_asset_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (rendered_asset_id,),
        ).fetchone()
        if attempt is None:
            raise AudioBindingError("rendered asset has no generation attempt lineage")

        caption_generation = _json_record(row["caption_generation_json"])
        metadata = _json_record(row["metadata_json"])
        caption_generation["audioIntent"] = audio_intent
        metadata = _bound_metadata(
            metadata,
            embedding_receipt=embedding_receipt,
            audio_intent=audio_intent,
            final_path=final_path,
            final_sha=final_sha,
        )
        blob_id = f"blob_audio_{final_sha[:24]}"
        edge_id = f"edge_audio_{final_sha[:24]}"
        lineage = {
            "schema": "campaign_factory.audio_embedding_lineage.v1",
            "policy": policy,
            "originalVideo": original_video,
            "selectedTrack": embedding_receipt.get("selectedTrack"),
            "selectedSegment": embedding_receipt.get("selectedSegment"),
            "mixSettings": embedding_receipt.get("mixSettings"),
            "finalVideo": final_video,
            "verification": verification,
            "audioIntentFingerprint": _canonical_sha256(audio_intent),
            "boundAt": bound_at,
        }
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO generation_output_blobs
                (id, content_sha256, byte_size, media_type, created_at)
                VALUES (?, ?, ?, 'video', ?)
                """,
                (blob_id, final_sha, final_path.stat().st_size, bound_at),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO generation_lineage_edges
                (id, generation_attempt_id, source_asset_id, rendered_asset_id,
                 output_blob_id, relation, lineage_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'audio_embedding', ?, ?)
                """,
                (
                    edge_id,
                    str(attempt["id"]),
                    str(row["source_asset_id"]),
                    rendered_asset_id,
                    blob_id,
                    json.dumps(lineage, ensure_ascii=False, sort_keys=True),
                    bound_at,
                ),
            )
            conn.execute(
                """
                UPDATE rendered_assets
                SET output_path = ?, campaign_path = ?,
                    filename = ?, caption_generation_json = ?, metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(final_path),
                    str(final_path),
                    final_path.name,
                    json.dumps(
                        caption_generation,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    bound_at,
                    rendered_asset_id,
                ),
            )
            invalidate_asset_evidence_after_byte_change(
                conn,
                rendered_asset_id=rendered_asset_id,
                previous_sha=original_sha,
                new_sha=final_sha,
                mutation_type="audio_embedding",
                mutation_receipt={
                    "schema": embedding_receipt["schema"],
                    "sha256": _canonical_sha256(embedding_receipt),
                },
                changed_at=bound_at,
            )
            _record_audio_selection(
                conn,
                campaign_id=str(row["campaign_id"]),
                rendered_asset_id=rendered_asset_id,
                embedding_receipt=embedding_receipt,
                bound_at=bound_at,
            )
        return {
            "schema": "campaign_factory.audio_embedding_binding.v1",
            "renderedAssetId": rendered_asset_id,
            "originalVideoSha256": original_sha,
            "finalVideoSha256": final_sha,
            "audioIntentFingerprint": lineage["audioIntentFingerprint"],
            "outputPath": str(final_path),
            "lineageEdgeId": edge_id,
            "reviewState": "review_ready",
            "boundAt": bound_at,
        }
    finally:
        conn.row_factory = previous_row_factory


def _bound_metadata(
    metadata: dict[str, Any],
    *,
    embedding_receipt: dict[str, Any],
    audio_intent: dict[str, Any],
    final_path: Path,
    final_sha: str,
) -> dict[str, Any]:
    publishability = _json_record(metadata.get("publishability"))
    blocking = [
        str(value)
        for value in (publishability.get("blockingIssues") or [])
        if str(value) not in {"NEEDS_EMBEDDED_AUDIO", "native_audio_unresolved"}
    ]
    production_recipe = _json_record(metadata.get("productionMotionRecipe"))
    autonomous_production = (
        production_recipe.get("status") == "active"
        and metadata.get("humanReviewRequired") is False
        and metadata.get("creativeApprovalRequired") is False
    )
    if not autonomous_production and "audio_creative_approval_required" not in blocking:
        blocking.append("audio_creative_approval_required")
    publishability.update(
        {
            "status": "blocked",
            "asset_state": "approved_but_not_publishable",
            "blockingIssues": blocking,
        }
    )
    return {
        **metadata,
        "asset_state": "approved_but_not_publishable",
        "audioBurned": True,
        "embeddedAudioMode": (
            "embedded_trending"
            if embedding_receipt.get("policy") == "embedded_trending_required"
            else "embedded_original"
        ),
        "audioIntent": audio_intent,
        "audioEmbeddingReceipt": embedding_receipt,
        "output": {"path": str(final_path), "sha256": final_sha},
        "publishability": publishability,
    }


def _record_audio_selection(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    rendered_asset_id: str,
    embedding_receipt: dict[str, Any],
    bound_at: str,
) -> None:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audio_selections'"
    ).fetchone()
    if table is None:
        return
    selection = _json_record(embedding_receipt.get("selection"))
    labels = _json_record(selection.get("advisoryLabels"))
    audio_catalog_id = str(labels.get("audioCatalogId") or "").strip()
    if not audio_catalog_id:
        return
    exists = conn.execute(
        "SELECT 1 FROM audio_catalog WHERE id = ?",
        (audio_catalog_id,),
    ).fetchone()
    if exists is None:
        return
    selection_id = (
        "audsel_embed_"
        + hashlib.sha256(
            f"{rendered_asset_id}:{audio_catalog_id}".encode()
        ).hexdigest()[:20]
    )
    payload = {
        "schema": "campaign_factory.embedded_audio_selection.v1",
        "renderedAssetId": rendered_asset_id,
        "audioCatalogId": audio_catalog_id,
        "creativeContext": embedding_receipt.get("creativeContext"),
        "selection": selection,
        "selectedTrack": embedding_receipt.get("selectedTrack"),
        "selectedSegment": embedding_receipt.get("selectedSegment"),
        "finalVideo": embedding_receipt.get("finalVideo"),
        "selectedAt": bound_at,
    }
    conn.execute(
        """
        INSERT INTO audio_selections (
          id, campaign_id, rendered_asset_id, audio_catalog_id, status,
          selected_by, selected_at, verified_at, payload_json, created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, 'verified', 'creator_os_audio_radar', ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          status = 'verified',
          verified_at = excluded.verified_at,
          payload_json = excluded.payload_json,
          updated_at = excluded.updated_at
        """,
        (
            selection_id,
            campaign_id,
            rendered_asset_id,
            audio_catalog_id,
            bound_at,
            bound_at,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            bound_at,
            bound_at,
        ),
    )


def _safe_file(value: object) -> Path:
    path = Path(str(value or "")).expanduser()
    if path.is_symlink():
        raise AudioBindingError("final video must not be a symlink")
    path = path.resolve()
    if not path.is_file():
        raise AudioBindingError("final video is missing")
    return path


def _record(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AudioBindingError(f"{label} is missing")
    return dict(value)


def _json_record(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _sha_value(value: object, label: str) -> str:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) != 64 or any(
        character not in "0123456789abcdef" for character in cleaned
    ):
        raise AudioBindingError(f"{label} SHA-256 is invalid")
    return cleaned


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
