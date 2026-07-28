"""Immutable publication-copy freeze for exact existing media."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from .db import init_db
from .existing_media import (
    _fingerprint,
    _json,
    _now,
    _resolved_file,
    _sha256,
    _table_exists,
)

CAPTION_FREEZE_SCHEMA = "creator_os.existing_video_caption_freeze.v1"
CAPTION_FREEZE_CONTRACT_VERSION = "existing-video-caption-freeze.v1"


def freeze_existing_caption(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    final_sha256: str,
    caption: str,
    hashtags: list[str] | tuple[str, ...],
    overlay_state: str,
    pattern_source: str,
    reviewer: str,
    apply: bool,
) -> dict[str, Any]:
    """Freeze publication copy without modifying the approved media bytes."""

    caption = caption.strip()
    reviewer = reviewer.strip()
    pattern_source = pattern_source.strip()
    normalized_hashtags = list(
        dict.fromkeys(tag.strip() for tag in hashtags if tag.strip())
    )
    if not caption:
        raise ValueError("caption is required")
    if not reviewer:
        raise ValueError("reviewer is required")
    if not pattern_source:
        raise ValueError("pattern source is required")
    if overlay_state != "NONE_FROZEN":
        raise ValueError("existing media supports only NONE_FROZEN overlay state")
    final_sha256 = final_sha256.lower()
    row = conn.execute(
        """
        SELECT ra.content_hash, ra.output_path,
               emi.eligibility_state,
               EXISTS (
                 SELECT 1 FROM existing_media_asset_reviews review
                 WHERE review.rendered_asset_id = ra.id
                   AND review.final_sha256 = ra.content_hash
                   AND review.verdict = 'WOULD_POST'
               ) AS would_post
        FROM rendered_assets ra
        JOIN existing_media_intakes emi
          ON emi.rendered_asset_id = ra.id
         AND emi.final_sha256 = ra.content_hash
        WHERE ra.id = ?
        ORDER BY emi.updated_at DESC LIMIT 1
        """,
        (rendered_asset_id,),
    ).fetchone()
    if row is None:
        raise ValueError("canonical existing media intake missing")
    path = _resolved_file(row["output_path"])
    if (
        row["content_hash"] != final_sha256
        or not path.is_file()
        or path.is_symlink()
        or _sha256(path) != final_sha256
    ):
        raise ValueError("caption freeze final SHA does not match exact asset bytes")
    if row["eligibility_state"] != "ELIGIBLE":
        raise ValueError("canonical final-media QC is not eligible")
    if not bool(row["would_post"]):
        raise ValueError("WOULD_POST review missing")
    caption_hash = hashlib.sha256(caption.encode("utf-8")).hexdigest()
    core = {
        "schema": CAPTION_FREEZE_SCHEMA,
        "contractVersion": CAPTION_FREEZE_CONTRACT_VERSION,
        "renderedAssetId": rendered_asset_id,
        "finalSha256": final_sha256,
        "caption": caption,
        "captionHash": caption_hash,
        "hashtags": normalized_hashtags,
        "overlayState": overlay_state,
        "patternSource": pattern_source,
        "reviewer": reviewer,
        "learningConsulted": False,
        "learningApplied": False,
    }
    fingerprint = _fingerprint(core)
    if apply:
        init_db(conn)
    existing = (
        conn.execute(
            """
            SELECT freeze_fingerprint FROM existing_media_caption_freezes
            WHERE rendered_asset_id = ? AND final_sha256 = ?
            """,
            (rendered_asset_id, final_sha256),
        ).fetchone()
        if _table_exists(conn, "existing_media_caption_freezes")
        else None
    )
    if existing is not None and existing["freeze_fingerprint"] != fingerprint:
        raise ValueError("caption freeze conflict for exact asset bytes")
    preview = {
        **core,
        "freezeId": f"freeze_{fingerprint[:20]}",
        "freezeFingerprint": fingerprint,
        "dryRun": not apply,
        "persistentWrites": 0,
        "mediaWrites": 0,
    }
    if not apply or existing is not None:
        return preview
    now = _now()
    conn.execute(
        """
        INSERT INTO existing_media_caption_freezes (
          id, rendered_asset_id, final_sha256, caption, caption_hash,
          hashtags_json, overlay_state, pattern_source, reviewer,
          contract_version, freeze_fingerprint, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            preview["freezeId"],
            rendered_asset_id,
            final_sha256,
            caption,
            caption_hash,
            _json(normalized_hashtags),
            overlay_state,
            pattern_source,
            reviewer,
            CAPTION_FREEZE_CONTRACT_VERSION,
            fingerprint,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE rendered_assets
        SET caption = ?, caption_hash = ?, updated_at = ?
        WHERE id = ? AND content_hash = ?
        """,
        (caption, caption_hash, now, rendered_asset_id, final_sha256),
    )
    conn.commit()
    return {**preview, "dryRun": False, "persistentWrites": 2, "frozenAt": now}
