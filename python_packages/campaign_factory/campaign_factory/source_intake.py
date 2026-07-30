"""Probe-authoritative source classification and lifecycle receipts."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from subprocess import run as run_process
from typing import Any

from .artifact_storage import managed_roots, root_keyed_path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def classify_source(path: Path) -> dict[str, Any]:
    extension_type = _extension_type(path)
    detected_mime = _detect_mime(path)
    probe = _probe(path)
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    format_row = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    has_visual_stream = any(
        isinstance(stream, dict) and stream.get("codec_type") == "video"
        for stream in streams
    )
    format_name = str(format_row.get("format_name") or "")
    mime_type = _mime_media_type(detected_mime)
    probed_type = (
        "image"
        if has_visual_stream
        and (
            detected_mime.startswith("image/")
            or format_name in {"image2", "image2pipe"}
        )
        else ("video" if has_visual_stream else "other")
    )
    if probed_type in {"image", "video"}:
        mismatch = extension_type not in {"other", probed_type} or (
            mime_type not in {"other", probed_type}
        )
        return {
            "mediaType": probed_type,
            "detectedMime": detected_mime,
            "classificationAuthority": "probe_extension_agree"
            if not mismatch
            else "probe",
            "quarantineReason": "extension_or_mime_mismatch" if mismatch else None,
            "probe": probe,
        }
    if extension_type in {"image", "video"}:
        return {
            "mediaType": extension_type,
            "detectedMime": detected_mime,
            "classificationAuthority": "extension_fallback",
            "quarantineReason": "media_probe_failed",
            "probe": probe,
        }
    return {
        "mediaType": mime_type,
        "detectedMime": detected_mime,
        "classificationAuthority": "unknown",
        "quarantineReason": "unsupported_media_type",
        "probe": probe,
    }


def record_source_lifecycle(
    conn: sqlite3.Connection,
    *,
    source_asset_id: str,
    stored_path: Path,
    storage_mode: str,
    classification: dict[str, Any],
    settings: Any,
    now: str,
    duplicate_source_asset_ids: list[str],
) -> None:
    binding = root_keyed_path(stored_path, managed_roots(settings))
    quarantine_reason = classification.get("quarantineReason")
    lifecycle_state = "quarantined" if quarantine_reason else "cataloged"
    storage_policy = (
        "external_reference" if storage_mode == "reference" else "managed_copy"
    )
    backup_state = "managed" if binding else "external_unverified"
    metadata = {
        "duplicateSourceAssetIds": sorted(set(duplicate_source_asset_ids)),
        "pathBinding": binding,
    }
    conn.execute(
        """
        INSERT INTO source_asset_lifecycle
        (source_asset_id, lifecycle_state, storage_policy, root_key, relative_path,
         classification_authority, detected_mime, probe_json, quarantine_reason,
         backup_state, metadata_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_asset_id) DO UPDATE SET
          lifecycle_state = excluded.lifecycle_state,
          storage_policy = excluded.storage_policy,
          root_key = excluded.root_key,
          relative_path = excluded.relative_path,
          classification_authority = excluded.classification_authority,
          detected_mime = excluded.detected_mime,
          probe_json = excluded.probe_json,
          quarantine_reason = excluded.quarantine_reason,
          backup_state = excluded.backup_state,
          metadata_json = excluded.metadata_json,
          version = source_asset_lifecycle.version + 1,
          updated_at = excluded.updated_at
        """,
        (
            source_asset_id,
            lifecycle_state,
            storage_policy,
            binding["rootKey"] if binding else None,
            binding["relativePath"] if binding else None,
            classification["classificationAuthority"],
            classification["detectedMime"],
            json.dumps(classification["probe"], sort_keys=True),
            quarantine_reason,
            backup_state,
            json.dumps(metadata, sort_keys=True),
            now,
        ),
    )
    evidence = {
        "classification": classification,
        "storagePolicy": storage_policy,
        "pathBinding": binding,
        "backupState": backup_state,
        "duplicateSourceAssetIds": sorted(set(duplicate_source_asset_ids)),
    }
    event_id = (
        "source_lifecycle_"
        + hashlib.sha256(
            f"{source_asset_id}:{lifecycle_state}:{json.dumps(evidence, sort_keys=True)}".encode()
        ).hexdigest()[:20]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO source_asset_lifecycle_events
        (id, source_asset_id, previous_state, new_state, reason, actor,
         evidence_json, created_at)
        VALUES (?, ?, NULL, ?, 'source_intake_classified',
                'campaign_factory.asset_import', ?, ?)
        """,
        (
            event_id,
            source_asset_id,
            lifecycle_state,
            json.dumps(evidence, sort_keys=True),
            now,
        ),
    )


def _extension_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def _mime_media_type(value: str) -> str:
    if value.startswith("image/"):
        return "image"
    if value.startswith("video/"):
        return "video"
    return "other"


def _detect_mime(path: Path) -> str:
    executable = shutil.which("file")
    if not executable:
        return "application/octet-stream"
    result = run_process(
        [executable, "--brief", "--mime-type", "--", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return (
        result.stdout.strip().lower()
        if result.returncode == 0 and result.stdout.strip()
        else "application/octet-stream"
    )


def _probe(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable:
        return {"ok": False, "error": "ffprobe_unavailable"}
    result = run_process(
        [
            executable,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "error": "ffprobe_failed",
            "detail": (result.stderr or "")[-1000:].strip(),
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "ffprobe_invalid_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "ffprobe_non_object"}
    return {"ok": True, **payload}
