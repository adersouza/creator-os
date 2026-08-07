"""Canonical active Audio Radar candidates for production fulfillment."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from creator_os_core.fileops import sha256_file as _sha256_file

from .audio_radar import (
    AudioLocator,
    PlatformSoundId,
    TrendCandidate,
    normalize_candidates,
)


def production_audio_candidates(
    connection: sqlite3.Connection | None,
) -> list[TrendCandidate]:
    fixture = _approved_audio_fixture_candidate()
    if fixture is not None:
        return normalize_candidates([fixture])
    return active_audio_library_candidates(connection)


def _approved_audio_fixture_candidate() -> TrendCandidate | None:
    raw = os.environ.get("CREATOR_OS_EMBEDDED_AUDIO_FIXTURE", "").strip()
    if not raw:
        return None
    expanded = Path(raw).expanduser()
    if expanded.is_symlink():
        raise ValueError("approved embedded-audio fixture must not be a symlink")
    path = expanded.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"approved embedded-audio fixture is missing: {path}")
    digest = _sha256_file(path)
    observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    return TrendCandidate(
        candidate_id=f"approved-local-fixture:{digest}",
        provider="operator_approved_fixture",
        title=os.environ.get("CREATOR_OS_EMBEDDED_AUDIO_FIXTURE_TITLE", path.stem),
        artist="approved local fixture",
        platform_sound_ids=(
            PlatformSoundId(platform="local_fixture", sound_id=digest[:24]),
        ),
        observed_at=observed_at,
        current_rank=1,
        usage_velocity=1_000_000,
        trend_score=1.0,
        canonical_track_id=f"local_fixture:{digest}",
        locator=AudioLocator(
            provider="operator_approved_fixture",
            platform="local_fixture",
            track_id=digest,
            kind="local_file",
            value=str(path),
        ),
        advisory_labels={"operatorApprovedFixture": True},
    )


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
                    "usageRightsRequired": source_metadata.get(
                        "usageRightsRequired", False
                    ),
                    "usageRightsStatus": source_metadata.get("usageRightsStatus"),
                    "rightsSource": source_metadata.get("rightsSource"),
                    "territory": source_metadata.get("territory"),
                    "accountScope": source_metadata.get("accountScope"),
                    "commercialUseAllowed": source_metadata.get("commercialUseAllowed"),
                    "expiresAt": source_metadata.get("expiresAt"),
                    "evidenceReceipt": source_metadata.get("evidenceReceipt"),
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
    """Apply publication, pending-selection, and creator-segment cooldowns."""

    if connection is None:
        return candidates
    account_days = _env_days("CREATOR_OS_AUDIO_ACCOUNT_TRACK_COOLDOWN_DAYS", 7)
    winner_days = _env_days("CREATOR_OS_AUDIO_WINNER_TRACK_COOLDOWN_DAYS", 3)
    pinned_days = _env_days("CREATOR_OS_AUDIO_PINNED_TRACK_COOLDOWN_DAYS", 2)
    minimum_hours = max(
        24,
        _env_int("CREATOR_OS_AUDIO_ABSOLUTE_MINIMUM_GAP_HOURS", 24, maximum=8760),
    )
    creator_days = _env_days("CREATOR_OS_AUDIO_CREATOR_SEGMENT_COOLDOWN_DAYS", 14)
    winner_score = _env_float("CREATOR_OS_AUDIO_WINNER_SCORE", 1.0)
    current = _parse_time(now)
    creator_cutoff = current - timedelta(days=creator_days)
    account_track_times: dict[str, list[datetime]] = {}
    pending_account_tracks: set[str] = set()
    creator_segments: dict[str, list[float]] = {}
    try:
        rows = connection.execute(
            """
            SELECT s.payload_json, s.selected_at, h.published_at
            FROM audio_selections AS s
            LEFT JOIN audio_publication_history AS h
              ON h.audio_selection_id = s.id
            WHERE s.status IN ('selected', 'verified')
            ORDER BY COALESCE(h.published_at, s.selected_at) DESC
            """,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    for raw in rows:
        row = dict(raw)
        selected_at = _parse_time(str(row.get("selected_at") or ""))
        published_at = _parse_time(str(row.get("published_at") or ""))
        payload = _json_object(row.get("payload_json"))
        legacy_receipt = payload.get("audioEmbeddingReceipt")
        if isinstance(legacy_receipt, dict):
            payload = legacy_receipt
        context = payload.get("creativeContext")
        selection = payload.get("selection")
        segment = payload.get("selectedSegment")
        if not all(isinstance(value, dict) for value in (context, selection, segment)):
            continue
        receipt_identities = _selection_identities(selection)
        if not receipt_identities:
            continue
        if account and str(context.get("account") or "") == account:
            if published_at == datetime.min.replace(tzinfo=UTC):
                pending_account_tracks.update(receipt_identities)
            else:
                for identity in receipt_identities:
                    account_track_times.setdefault(identity, []).append(published_at)
        if (
            selected_at >= creator_cutoff
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
        if identities & pending_account_tracks:
            continue
        winner_override = _measured_winner(
            connection,
            str(labels.get("audioCatalogId") or ""),
            winner_score=winner_score,
        )
        pinned_override = str(labels.get("lifecycleState") or "") == "PINNED"
        effective_days = (
            pinned_days
            if pinned_override
            else winner_days
            if winner_override
            else account_days
        )
        account_cutoff = current - max(
            timedelta(days=effective_days),
            timedelta(hours=minimum_hours),
        )
        if any(
            used_at > account_cutoff
            for identity in identities
            for used_at in account_track_times.get(identity, [])
        ):
            continue
        excluded_offsets = [
            offset
            for identity in identities
            for offset in creator_segments.get(identity, [])
        ]
        if excluded_offsets:
            labels["excludedSegmentOffsetsSeconds"] = sorted(set(excluded_offsets))
            labels["creatorSegmentCooldownDays"] = creator_days
        if winner_override:
            labels["cooldownOverrideApplied"] = "measured_winner_bounded"
        if pinned_override:
            labels["cooldownOverrideApplied"] = "pinned_bounded"
        labels["accountTrackCooldownDays"] = effective_days
        labels["absoluteMinimumGapHours"] = minimum_hours
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
    return _env_int(name, default, maximum=365)


def _env_int(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0, min(maximum, value))


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
