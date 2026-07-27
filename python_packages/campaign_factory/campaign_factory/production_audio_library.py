"""Canonical active Audio Radar candidates for production fulfillment."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from .audio_radar import AudioLocator, PlatformSoundId, TrendCandidate


def active_audio_library_candidates(
    connection: sqlite3.Connection | None,
) -> list[TrendCandidate]:
    """Load active, retained, hash-verified cached tracks."""

    if connection is None:
        return []
    try:
        rows = connection.execute(
            """
            SELECT
              c.id, c.canonical_track_id, c.canonical_title,
              c.canonical_artists_json, c.title, c.artist_name, c.platform,
              c.native_audio_id, c.velocity_score, c.trend_score,
              c.trend_sources_json, c.lifecycle_state, c.last_seen_at,
              c.refresh_metadata_json,
              o.provider AS cache_provider, o.platform AS cache_platform,
              o.platform_sound_id, o.cache_path, o.byte_sha256,
              o.duration_seconds, o.retrieved_at, o.source_metadata_json
            FROM audio_catalog AS c
            JOIN audio_cache_objects AS o ON o.audio_catalog_id = c.id
            WHERE c.active = 1 AND o.cached = 1 AND o.pruned_at IS NULL
            ORDER BY
              CASE c.lifecycle_state
                WHEN 'HOT' THEN 0
                WHEN 'BREAKOUT' THEN 1
                WHEN 'PINNED' THEN 2
                WHEN 'COOLING' THEN 3
                ELSE 4
              END,
              COALESCE(c.velocity_score, 0) DESC,
              c.id,
              o.retrieved_at DESC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    selected: list[TrendCandidate] = []
    seen: set[str] = set()
    for raw in rows:
        row = dict(raw)
        catalog_id = str(row["id"])
        if catalog_id in seen:
            continue
        cache_path = Path(str(row["cache_path"])).expanduser()
        if (
            cache_path.is_symlink()
            or not cache_path.is_file()
            or _sha256_file(cache_path.resolve()) != str(row["byte_sha256"])
        ):
            continue
        seen.add(catalog_id)
        artists = _json_string_tuple(row.get("canonical_artists_json"))
        source_metadata = _json_object(row.get("source_metadata_json"))
        refresh_metadata = _json_object(row.get("refresh_metadata_json"))
        trend_sources = _json_string_tuple(row.get("trend_sources_json"))
        observed_at = str(row.get("last_seen_at") or row.get("retrieved_at") or "")
        sound_id = str(
            row.get("platform_sound_id") or row.get("native_audio_id") or catalog_id
        )
        selected.append(
            TrendCandidate(
                candidate_id=f"active_audio_library:{catalog_id}",
                provider="audio_radar_active_library",
                title=str(row.get("canonical_title") or row.get("title") or sound_id),
                artist=str(artists[0] if artists else row.get("artist_name") or ""),
                platform_sound_ids=(
                    PlatformSoundId(
                        platform=str(
                            row.get("cache_platform")
                            or row.get("platform")
                            or "unknown"
                        ),
                        sound_id=sound_id,
                    ),
                ),
                observed_at=observed_at,
                usage_total=_optional_int(source_metadata.get("videoCount")),
                usage_velocity=_optional_float(row.get("velocity_score")),
                trend_score=_optional_float(
                    row.get("trend_score") or refresh_metadata.get("score")
                ),
                canonical_track_id=str(
                    row.get("canonical_track_id")
                    or catalog_id.removeprefix("audradar_")
                ),
                canonical_title=str(
                    row.get("canonical_title") or row.get("title") or sound_id
                ),
                canonical_artists=artists,
                locator=AudioLocator(
                    provider=str(row.get("cache_provider") or "audio_radar_cache"),
                    platform=str(
                        row.get("cache_platform") or row.get("platform") or "unknown"
                    ),
                    track_id=sound_id,
                    kind="local_file",
                    value=str(cache_path.resolve()),
                ),
                advisory_labels={
                    "source": "canonical_active_audio_library",
                    "audioCatalogId": catalog_id,
                    "lifecycleState": row.get("lifecycle_state"),
                    "trendSources": list(trend_sources),
                    "soundOwner": source_metadata.get("soundOwner"),
                    "cachedByteSha256": row.get("byte_sha256"),
                    "cachedDurationSeconds": row.get("duration_seconds"),
                },
            )
        )
    return selected


def audio_candidates_for_job(
    candidates: list[TrendCandidate],
    *,
    job_index: int,
    job_count: int,
) -> list[TrendCandidate]:
    """Partition a sufficiently large batch library to avoid track reuse."""

    if job_count <= 1 or len(candidates) < job_count:
        return candidates
    return [
        candidate
        for index, candidate in enumerate(candidates)
        if index % job_count == job_index % job_count
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_string_tuple(value: Any) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if str(item).strip())


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
