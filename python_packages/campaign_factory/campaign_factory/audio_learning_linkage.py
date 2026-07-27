"""Exact future publication linkage for verified embedded Audio Radar selections."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from .learning_consumption import observation_bucket
from .persistence import json_load


def exact_embedded_audio_selection(
    conn: sqlite3.Connection,
    *,
    snapshot: dict[str, Any],
    raw: dict[str, Any],
    utc_now: Callable[[], str],
) -> dict[str, Any] | None:
    rendered_asset_id = str(snapshot.get("rendered_asset_id") or "").strip()
    final_sha = str(snapshot.get("content_hash") or "").strip().lower()
    if not rendered_asset_id or not final_sha:
        return None
    row = conn.execute(
        """
        SELECT * FROM audio_selections
        WHERE rendered_asset_id = ? AND status = 'verified'
        ORDER BY verified_at DESC, id DESC LIMIT 1
        """,
        (rendered_asset_id,),
    ).fetchone()
    if row is None:
        return None
    payload = json_load(row["payload_json"], {})
    if payload.get("schema") != "campaign_factory.embedded_audio_selection.v1":
        return None
    final_video = payload.get("finalVideo")
    final_video = final_video if isinstance(final_video, dict) else {}
    if str(final_video.get("sha256") or "").strip().lower() != final_sha:
        return None
    media_id = str(
        raw.get("instagram_media_id")
        or raw.get("instagramMediaId")
        or raw.get("instagram_post_id")
        or raw.get("instagramPostId")
        or ""
    ).strip()
    if not media_id:
        return None
    chosen = payload.get("selection")
    chosen = chosen if isinstance(chosen, dict) else {}
    selected_track = payload.get("selectedTrack")
    selected_track = selected_track if isinstance(selected_track, dict) else {}
    selected_segment = payload.get("selectedSegment")
    selected_segment = selected_segment if isinstance(selected_segment, dict) else {}
    creative = payload.get("creativeContext")
    creative = creative if isinstance(creative, dict) else {}
    linkage = {
        "schema": "campaign_factory.audio_publication_linkage.v1",
        "audioSelectionId": row["id"],
        "tiktokMusicId": (
            chosen.get("platformMusicId")
            or chosen.get("platform_music_id")
            or selected_track.get("trackId")
        ),
        "trackSha256": selected_track.get("acquiredAudioSha256"),
        "acousticFingerprint": chosen.get("acousticFingerprint"),
        "segmentStartSeconds": (
            selected_segment.get("startSeconds")
            or selected_segment.get("start_seconds")
        ),
        "segmentEndSeconds": (
            selected_segment.get("endSeconds") or selected_segment.get("end_seconds")
        ),
        "processedSegmentSha256": (
            selected_segment.get("processedSha256")
            or selected_segment.get("processed_sha256")
        ),
        "finalMediaSha256": final_sha,
        "instagramMediaId": media_id,
        "metricSnapshotIds": [snapshot.get("id")],
        "creator": creative.get("creator"),
        "creatorIdentityProfile": creative.get("creatorIdentityProfile"),
        "account": creative.get("account") or snapshot.get("account_id"),
        "intent": creative.get("intent"),
        "publishedAt": snapshot.get("published_at"),
        "snapshotAt": snapshot.get("snapshot_at"),
        "observationBucket": observation_bucket(
            snapshot.get("published_at"), snapshot.get("snapshot_at")
        ),
        "selection": {**chosen, "catalog_audio_id": row["audio_catalog_id"]},
    }
    required = (
        "tiktokMusicId",
        "trackSha256",
        "acousticFingerprint",
        "segmentStartSeconds",
        "segmentEndSeconds",
        "processedSegmentSha256",
        "finalMediaSha256",
        "instagramMediaId",
        "creator",
        "creatorIdentityProfile",
        "account",
        "intent",
        "observationBucket",
    )
    if any(
        linkage.get(field) is None
        or (isinstance(linkage.get(field), str) and not str(linkage.get(field)).strip())
        for field in required
    ):
        return None
    existing_rollup_links: list[dict[str, Any]] = []
    for existing in conn.execute(
        "SELECT stats_json FROM audio_performance_rollups WHERE audio_catalog_id = ?",
        (row["audio_catalog_id"],),
    ).fetchall():
        stats = json_load(existing["stats_json"], {})
        prior = stats.get("exactPublicationLinkages")
        if isinstance(prior, list):
            existing_rollup_links.extend(
                dict(item) for item in prior if isinstance(item, dict)
            )
    updated_payload = {**payload, "publicationLinkage": linkage}
    conn.execute(
        """
        UPDATE audio_selections
        SET post_id = ?, proof_url = ?, payload_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot.get("post_id"),
            snapshot.get("permalink"),
            json.dumps(updated_payload, ensure_ascii=False, sort_keys=True),
            utc_now(),
            row["id"],
        ),
    )
    linkage["_priorExactPublicationLinkages"] = existing_rollup_links
    return linkage
