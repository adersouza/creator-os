"""Canonical active Audio Radar candidates for production fulfillment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
              c.mood_tags_json, c.best_content_types_json,
              c.native_audio_id, c.velocity_score, c.trend_score,
              c.trend_sources_json, c.lifecycle_state, c.last_seen_at,
              c.refresh_metadata_json,
              o.provider AS cache_provider, o.platform AS cache_platform,
              o.platform_sound_id, o.cache_path, o.byte_sha256,
              o.acoustic_fingerprint, o.duration_seconds, o.retrieved_at,
              o.source_metadata_json
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
    seen_acoustic_fingerprints: set[str] = set()
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
        acoustic_fingerprint = str(row.get("acoustic_fingerprint") or "")
        if acoustic_fingerprint and acoustic_fingerprint in seen_acoustic_fingerprints:
            continue
        seen.add(catalog_id)
        if acoustic_fingerprint:
            seen_acoustic_fingerprints.add(acoustic_fingerprint)
        artists = _json_string_tuple(row.get("canonical_artists_json"))
        source_metadata = _json_object(row.get("source_metadata_json"))
        refresh_metadata = _json_object(row.get("refresh_metadata_json"))
        trend_sources = _json_string_tuple(row.get("trend_sources_json"))
        mood_tags = tuple(
            dict.fromkeys(
                (
                    *_json_string_tuple(row.get("mood_tags_json")),
                    *_json_string_tuple(row.get("best_content_types_json")),
                )
            )
        )
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
                mood_tags=mood_tags,
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
                    "acousticFingerprint": acoustic_fingerprint or None,
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

    unique: list[TrendCandidate] = []
    seen_audio: set[str] = set()
    for candidate in candidates:
        fingerprint = str(candidate.advisory_labels.get("acousticFingerprint") or "")
        if fingerprint and fingerprint in seen_audio:
            continue
        if fingerprint:
            seen_audio.add(fingerprint)
        unique.append(candidate)
    candidates = unique
    if job_count <= 1 or len(candidates) < job_count:
        return candidates
    return [
        candidate
        for index, candidate in enumerate(candidates)
        if index % job_count == job_index % job_count
    ]


def audio_fit_tags(intent: str) -> tuple[str, ...]:
    """Return the transparent deterministic fit labels for one visual intent."""

    return {
        "passive_selfie": ("playful", "flirty", "chill", "lifestyle", "neutral"),
        "flirty_portrait": ("flirty", "playful", "confident"),
        "outfit": ("fashion", "confident", "energetic"),
        "lifestyle": ("lifestyle", "chill", "neutral"),
        "animate_existing": ("lifestyle", "playful", "neutral"),
    }.get(intent, ("neutral",))


def apply_audio_usage_policy(
    connection: sqlite3.Connection | None,
    candidates: list[TrendCandidate],
    *,
    creator: str,
    account: str,
    now: str,
) -> list[TrendCandidate]:
    """Apply configured account-track and creator-segment cooldowns."""

    if connection is None:
        return candidates
    account_days = _env_days("CREATOR_OS_AUDIO_ACCOUNT_TRACK_COOLDOWN_DAYS", 7)
    creator_days = _env_days("CREATOR_OS_AUDIO_CREATOR_SEGMENT_COOLDOWN_DAYS", 14)
    winner_score = _env_float("CREATOR_OS_AUDIO_WINNER_SCORE", 1.0)
    current = _parse_time(now)
    account_cutoff = current - timedelta(days=account_days)
    creator_cutoff = current - timedelta(days=creator_days)
    recent_account_tracks: set[str] = set()
    creator_segments: dict[str, list[float]] = {}
    try:
        rows = connection.execute(
            """
            SELECT metadata_json, updated_at
            FROM rendered_assets
            WHERE metadata_json LIKE '%audioEmbeddingReceipt%'
              AND updated_at >= ?
            ORDER BY updated_at DESC
            """,
            (min(account_cutoff, creator_cutoff).isoformat(),),
        ).fetchall()
    except sqlite3.OperationalError:
        return candidates
    for raw in rows:
        row = dict(raw)
        updated = _parse_time(str(row.get("updated_at") or ""))
        metadata = _json_object(row.get("metadata_json"))
        receipt = metadata.get("audioEmbeddingReceipt")
        if not isinstance(receipt, dict):
            continue
        context = receipt.get("creativeContext")
        selection = receipt.get("selection")
        segment = receipt.get("selectedSegment")
        if not all(isinstance(value, dict) for value in (context, selection, segment)):
            continue
        receipt_identities = _selection_identities(selection)
        if not receipt_identities:
            continue
        if (
            updated >= account_cutoff
            and account
            and str(context.get("account") or "") == account
        ):
            recent_account_tracks.update(receipt_identities)
        if (
            updated >= creator_cutoff
            and creator
            and str(context.get("creator") or "") == creator
        ):
            try:
                offset = float(segment.get("start_offset_seconds"))
            except (TypeError, ValueError):
                continue
            for identity in receipt_identities:
                creator_segments.setdefault(identity, []).append(offset)

    selected: list[TrendCandidate] = []
    for candidate in candidates:
        identities = _candidate_identities(candidate)
        labels = dict(candidate.advisory_labels)
        winner_override = _measured_winner(
            connection,
            str(labels.get("audioCatalogId") or ""),
            winner_score=winner_score,
        )
        pinned_override = str(labels.get("lifecycleState") or "") == "PINNED"
        if identities & recent_account_tracks and not (
            winner_override or pinned_override
        ):
            continue
        excluded_offsets = (
            []
            if winner_override or pinned_override
            else [
                offset
                for identity in identities
                for offset in creator_segments.get(identity, [])
            ]
        )
        if excluded_offsets:
            labels["excludedSegmentOffsetsSeconds"] = sorted(set(excluded_offsets))
            labels["creatorSegmentCooldownDays"] = creator_days
        if winner_override:
            labels["measuredWinnerCooldownOverride"] = True
        if pinned_override:
            labels["pinnedCooldownOverride"] = True
        selected.append(replace(candidate, advisory_labels=labels))
    return selected


def _candidate_identities(candidate: TrendCandidate) -> set[str]:
    labels = candidate.advisory_labels
    return {
        value
        for value in (
            str(candidate.canonical_track_id or ""),
            str(labels.get("audioCatalogId") or ""),
            *(
                f"{sound.platform}:{sound.sound_id}"
                for sound in candidate.platform_sound_ids
            ),
        )
        if value
    }


def _selection_identities(selection: dict[str, Any]) -> set[str]:
    labels = _json_object(selection.get("advisoryLabels"))
    values = {
        str(selection.get("canonicalTrackId") or ""),
        str(labels.get("audioCatalogId") or ""),
    }
    sound_ids = selection.get("platformSoundIds")
    if isinstance(sound_ids, list):
        for sound in sound_ids:
            if not isinstance(sound, dict):
                continue
            platform = str(sound.get("platform") or "")
            sound_id = str(sound.get("soundId") or sound.get("sound_id") or "")
            if platform and sound_id:
                values.add(f"{platform}:{sound_id}")
    return {value for value in values if value}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
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


def _env_days(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0, min(365, value))


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _measured_winner(
    connection: sqlite3.Connection,
    audio_catalog_id: str,
    *,
    winner_score: float,
) -> bool:
    if not audio_catalog_id:
        return False
    try:
        row = connection.execute(
            """
            SELECT 1 FROM audio_performance_rollups
            WHERE audio_catalog_id = ? AND score >= ?
            LIMIT 1
            """,
            (audio_catalog_id, winner_score),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None
