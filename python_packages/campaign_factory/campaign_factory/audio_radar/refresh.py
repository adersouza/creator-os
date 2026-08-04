"""Bounded, idempotent weekly Audio Radar library refresh."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_paths import resolve_runtime_paths

from ..cli_support import _load_env_file
from ..config import get_settings
from ..db import connect, init_db
from .acquisition import AudioAcquisitionError, AudioCache
from .models import TrendCandidate
from .normalization import normalize_candidates
from .providers import (
    ProviderCredentialError,
    ProviderError,
    SocialCrawlInstagramProvider,
    SocialCrawlTikTokProvider,
    TikLiveAudioDetails,
    TikLiveAudioResolver,
    TikTokCreativeCenterProvider,
)
from .ranking import AudioMatchContext, RankedCandidate, rank_candidates
from .segment import SegmentSelectionError, decoded_audio_fingerprint

_LIFECYCLE_STATES = {
    "BREAKOUT",
    "HOT",
    "PROVEN",
    "EVERGREEN",
    "COOLING",
    "STALE",
    "PINNED",
}
_SECRET_ENVS = ("SOCIALCRAWL_API_KEY", "TIKLIVE_API_KEY", "TOKCHART_API_TOKEN")


@dataclass(frozen=True)
class LifecycleThresholds:
    """One configurable home for lifecycle and retention thresholds."""

    stale_after_absences: int = 2
    retention_days: int = 30
    winner_lookback_days: int = 60
    winner_score: float = 1.0
    creative_center_request_cap: int = 4
    tiktok_sample_count: int = 2

    @classmethod
    def from_env(cls) -> LifecycleThresholds:
        return cls(
            stale_after_absences=_env_int(
                "CREATOR_OS_AUDIO_STALE_AFTER_REFRESHES", 2, minimum=2, maximum=12
            ),
            retention_days=_env_int(
                "CREATOR_OS_AUDIO_RETENTION_DAYS", 30, minimum=1, maximum=730
            ),
            winner_lookback_days=_env_int(
                "CREATOR_OS_AUDIO_WINNER_LOOKBACK_DAYS",
                60,
                minimum=1,
                maximum=730,
            ),
            winner_score=_env_float("CREATOR_OS_AUDIO_WINNER_SCORE", 1.0, minimum=0.0),
            creative_center_request_cap=_env_int(
                "CREATOR_OS_AUDIO_CREATIVE_REQUEST_CAP",
                4,
                minimum=1,
                maximum=4,
            ),
            tiktok_sample_count=_env_int(
                "CREATOR_OS_AUDIO_TIKTOK_SAMPLE_COUNT",
                2,
                minimum=2,
                maximum=4,
            ),
        )


@dataclass(frozen=True)
class RefreshPaths:
    database: Path
    cache: Path
    receipts: Path
    lock: Path

    @classmethod
    def defaults(cls) -> RefreshPaths:
        runtime = resolve_runtime_paths()
        return cls(
            database=get_settings().db_path,
            cache=Path(
                os.environ.get(
                    "CREATOR_OS_AUDIO_CACHE",
                    runtime.artifact_root / "audio_radar" / "cache",
                )
            ),
            receipts=Path(
                os.environ.get(
                    "CREATOR_OS_AUDIO_RECEIPTS",
                    runtime.config_root / "reports" / "audio-refresh",
                )
            ),
            lock=Path(
                os.environ.get(
                    "CREATOR_OS_AUDIO_REFRESH_LOCK",
                    runtime.state_root / "audio-refresh.lock",
                )
            ),
        )


def refresh_audio_library(
    *,
    region: str,
    max_new: int,
    max_active: int,
    apply: bool,
    paths: RefreshPaths | None = None,
    thresholds: LifecycleThresholds | None = None,
    social_provider: Any | None = None,
    tiktok_social_provider: Any | None = None,
    creative_provider: Any | None = None,
    tiklive_resolver: Any | None = None,
    cache: AudioCache | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Discover live candidates and optionally update the durable local library."""

    if max_new < 0 or max_new > 100:
        raise ValueError("--max-new must be between 0 and 100")
    if max_active <= 0 or max_active > 1000:
        raise ValueError("--max-active must be between 1 and 1000")
    region = region.strip().upper()
    if len(region) != 2 or not region.isalpha():
        raise ValueError("--region must be a two-letter country code")

    selected_paths = paths or RefreshPaths.defaults()
    config = thresholds or LifecycleThresholds.from_env()
    started_at = now or _utc_now()
    run_id = _run_id(started_at, region)
    _load_private_audio_secrets()
    social = social_provider or SocialCrawlInstagramProvider()
    tiktok_social = tiktok_social_provider or SocialCrawlTikTokProvider()
    creative = creative_provider or TikTokCreativeCenterProvider(
        max_requests=config.creative_center_request_cap
    )
    resolver = tiklive_resolver or TikLiveAudioResolver()

    with _single_instance_lock(selected_paths.lock):
        instagram, social_status = _discover_source(
            social,
            source="socialcrawl_instagram",
            platform="instagram",
            region=region,
            limit=100,
        )
        social_tiktok, tiktok_social_status = _discover_source(
            tiktok_social,
            source="socialcrawl_tiktok",
            platform="tiktok",
            region=region,
            limit=100,
            sample_count=config.tiktok_sample_count,
        )
        creative_tiktok, creative_status = _discover_source(
            creative,
            source="tiktok_creative_center",
            platform="tiktok",
            region=region,
            limit=100,
        )
        normalized = normalize_candidates(
            [*instagram, *social_tiktok, *creative_tiktok]
        )
        ranked = rank_candidates(
            normalized,
            AudioMatchContext(creator="fleet", account="fleet"),
            limit=max(1, len(normalized)),
        )
        sources = {
            "socialcrawlInstagram": social_status,
            "socialcrawlTikTok": tiktok_social_status,
            "tiktokCreativeCenter": creative_status,
            "tiklive": {
                "status": "not_called" if apply else "dry_run_not_called",
                "requests": 0,
                "resolved": 0,
                "unavailable": 0,
            },
        }
        discovery = {
            "schema": "creator_os.audio_refresh_candidates.v1",
            "runId": run_id,
            "region": region,
            "observedAt": started_at,
            "sourceStatus": sources,
            "instagramCandidateCount": len(instagram),
            "socialcrawlTikTokVideoCount": tiktok_social_status.get("rawVideoCount", 0),
            "socialcrawlTikTokMusicIdCount": len(social_tiktok),
            "creativeCenterCandidateCount": len(creative_tiktok),
            "tiktokCandidateCount": len(social_tiktok) + len(creative_tiktok),
            "tiktokMusicIds": _tiktok_music_ids(normalized),
            "normalizedUniqueTrackCount": len(normalized),
            "candidates": [value.as_dict() for value in normalized],
        }
        if not apply:
            return {
                "schema": "creator_os.audio_refresh_receipt.v1",
                "runId": run_id,
                "mode": "dry-run",
                "status": _overall_status(sources),
                "region": region,
                "startedAt": started_at,
                "completedAt": _utc_now(),
                "sourceStatus": sources,
                "counts": {
                    "instagramCandidates": len(instagram),
                    "socialcrawlTikTokVideos": tiktok_social_status.get(
                        "rawVideoCount", 0
                    ),
                    "socialcrawlTikTokMusicIds": len(social_tiktok),
                    "creativeCenterCandidates": len(creative_tiktok),
                    "tiktokCandidates": len(social_tiktok) + len(creative_tiktok),
                    "tiktokMusicIds": len(_tiktok_music_ids(normalized)),
                    "normalizedUniqueTracks": len(normalized),
                    "audioFilesDownloaded": 0,
                    "activeLibrarySize": None,
                    "tracksRetained": None,
                    "tracksMarkedCooling": None,
                    "tracksMarkedStale": None,
                    "cachedFilesPruned": 0,
                },
                "credits": _credits(sources),
                "requestCaps": {
                    "socialcrawl": 1 + config.tiktok_sample_count,
                    "creativeCenter": config.creative_center_request_cap,
                    "tiklive": 0,
                    "downloads": 0,
                },
                "historicalRecordsPreserved": True,
                "dryRunMutations": {
                    "downloads": 0,
                    "activations": 0,
                    "deletions": 0,
                    "databaseWrites": 0,
                },
                "discovery": discovery,
            }

        selected_paths.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        selected_cache = cache or AudioCache(selected_paths.cache)
        with connect(selected_paths.database) as conn:
            init_db(conn)
            _separate_legacy_tiklive_sound_owners(conn)
            ranked = _rank_with_history(conn, normalized, now=started_at)
            history_before = _history_counts(conn)
            conn.execute(
                """
                INSERT INTO audio_refresh_runs (
                  id, region, apply_mode, status, started_at, source_status_json,
                  counts_json, credits_json, created_at
                ) VALUES (?, ?, 1, 'running', ?, ?, '{}', '{}', ?)
                ON CONFLICT(id) DO UPDATE SET
                  status = 'running',
                  completed_at = NULL,
                  source_status_json = excluded.source_status_json,
                  counts_json = '{}',
                  credits_json = '{}',
                  receipt_path = NULL,
                  candidates_receipt_path = NULL,
                  error_summary = NULL
                """,
                (
                    run_id,
                    region,
                    started_at,
                    _json(sources),
                    started_at,
                ),
            )
            catalog_ids: dict[str, str] = {}
            for ranked_candidate in ranked:
                candidate = ranked_candidate.candidate
                catalog_id = _upsert_candidate(
                    conn,
                    candidate=candidate,
                    ranked=ranked_candidate,
                    run_id=run_id,
                    now=started_at,
                )
                catalog_ids[str(candidate.canonical_track_id)] = catalog_id
            conn.commit()

            acquisition = _acquire_ranked_candidates(
                conn,
                ranked=ranked,
                catalog_ids=catalog_ids,
                resolver=resolver,
                cache=selected_cache,
                max_new=max_new,
                max_active=max_active,
                retrieved_at=started_at,
            )
            sources["tiklive"] = acquisition["tiklive"]
            seen_ids = set(catalog_ids.values())
            successful_platforms = {
                platform
                for platform, source_status in (
                    ("instagram", social_status),
                    (
                        "tiktok",
                        _combined_tiktok_status(
                            tiktok_social_status,
                            creative_status,
                        ),
                    ),
                )
                if source_status["status"] == "available"
            }
            lifecycle = _recalculate_lifecycle(
                conn,
                seen_catalog_ids=seen_ids,
                ranked=ranked,
                catalog_ids=catalog_ids,
                successful_platforms=successful_platforms,
                run_id=run_id,
                now=started_at,
                max_active=max_active,
                config=config,
            )
            prunes = (
                _prune_cache(
                    conn,
                    cache=selected_cache,
                    run_id=run_id,
                    now=started_at,
                    config=config,
                )
                if successful_platforms
                else []
            )
            history_after = _history_counts(conn)
            history_preserved = all(
                history_after[key] >= value for key, value in history_before.items()
            )
            counts = {
                "instagramCandidates": len(instagram),
                "socialcrawlTikTokVideos": tiktok_social_status.get("rawVideoCount", 0),
                "socialcrawlTikTokMusicIds": len(social_tiktok),
                "creativeCenterCandidates": len(creative_tiktok),
                "tiktokCandidates": len(social_tiktok) + len(creative_tiktok),
                "tiktokMusicIds": len(_tiktok_music_ids(normalized)),
                "normalizedUniqueTracks": len(normalized),
                "audioFilesDownloaded": acquisition["downloaded"],
                "tracksActivated": acquisition["activated"],
                "activeLibrarySize": _scalar(
                    conn, "SELECT COUNT(*) FROM audio_catalog WHERE active = 1"
                ),
                "tracksRetained": _scalar(conn, "SELECT COUNT(*) FROM audio_catalog"),
                "tracksMarkedCooling": lifecycle["cooling"],
                "tracksMarkedStale": lifecycle["stale"],
                "cachedFilesPruned": len(prunes),
            }
            completed_at = _utc_now()
            status = _overall_status(sources)
            candidates_path, receipt_path = _receipt_paths(
                selected_paths.receipts,
                run_id,
            )
            raw_payload_path = (
                selected_paths.receipts.expanduser().resolve()
                / f"{run_id}-provider-payloads.json"
            )
            provider_payloads = {
                "schema": "creator_os.audio_refresh_provider_payloads.v1",
                "runId": run_id,
                "region": region,
                "capturedAt": completed_at,
                "sources": {
                    "socialcrawlInstagram": _provider_payloads(social),
                    "socialcrawlTikTok": _provider_payloads(tiktok_social),
                },
            }
            receipt = {
                "schema": "creator_os.audio_refresh_receipt.v1",
                "runId": run_id,
                "mode": "apply",
                "status": status,
                "region": region,
                "startedAt": started_at,
                "completedAt": completed_at,
                "sourceStatus": sources,
                "counts": counts,
                "credits": _credits(sources),
                "requestCaps": {
                    "socialcrawl": 1 + config.tiktok_sample_count,
                    "creativeCenter": config.creative_center_request_cap,
                    "tiklive": max_new,
                    "downloads": max_new,
                },
                "lifecycleThresholds": asdict(config),
                "historicalRecordsPreserved": history_preserved,
                "historyCountsBefore": history_before,
                "historyCountsAfter": history_after,
                "acquisitions": acquisition["receipts"],
                "prunes": prunes,
                "sampleVerification": acquisition["sampleVerification"][:3],
                "candidatesReceipt": str(candidates_path),
                "providerPayloadReceipt": str(raw_payload_path),
                "receiptPath": str(receipt_path),
                "publishingActions": 0,
                "schedulingActions": 0,
                "generationActions": 0,
            }
            safe_discovery = _redact(discovery)
            safe_receipt = _redact(receipt)
            _write_private_json(candidates_path, safe_discovery)
            _write_private_json(raw_payload_path, _redact(provider_payloads))
            _write_private_json(receipt_path, safe_receipt)
            conn.execute(
                """
                UPDATE audio_refresh_runs
                SET status = ?, completed_at = ?, source_status_json = ?,
                    counts_json = ?, credits_json = ?, receipt_path = ?,
                    candidates_receipt_path = ?
                WHERE id = ?
                """,
                (
                    status,
                    completed_at,
                    _json(sources),
                    _json(counts),
                    _json(_credits(sources)),
                    str(receipt_path),
                    str(candidates_path),
                    run_id,
                ),
            )
            conn.commit()
            return safe_receipt


def _discover_source(
    provider: Any,
    *,
    source: str,
    platform: str,
    region: str,
    limit: int,
    sample_count: int = 1,
) -> tuple[list[TrendCandidate], dict[str, Any]]:
    try:
        discover_samples = getattr(provider, "discover_samples", None)
        candidates = (
            discover_samples(
                region=region,
                limit=limit,
                sample_count=sample_count,
            )
            if callable(discover_samples) and sample_count > 1
            else provider.discover(region=region, limit=limit)
        )
    except ProviderCredentialError:
        return [], {
            "status": "unavailable",
            "reason": "required_credential_missing",
            "requests": 0,
            "candidateCount": 0,
        }
    except (ProviderError, requests.RequestException, OSError):
        metadata = _redact(getattr(provider, "last_metadata", {}))
        if not isinstance(metadata, dict):
            metadata = {}
        return [], {
            **metadata,
            "status": "unavailable",
            "reason": "provider_or_public_page_unavailable",
            "requests": metadata.get("requests", 1),
            "candidateCount": 0,
        }
    metadata = _redact(getattr(provider, "last_metadata", {}))
    request_count = metadata.get("requests", 1) if isinstance(metadata, dict) else 1
    observation_valid = bool(candidates) or (
        isinstance(metadata, dict) and metadata.get("observationValid") is True
    )
    if not observation_valid:
        return [], {
            **(metadata if isinstance(metadata, dict) else {}),
            "status": "unavailable",
            "reason": "invalid_empty_response",
            "source": source,
            "platform": platform,
            "requests": request_count,
            "candidateCount": 0,
        }
    provider_status = (
        str(metadata.get("status"))
        if isinstance(metadata, dict) and metadata.get("status") == "partial"
        else "available"
    )
    return candidates, {
        **(metadata if isinstance(metadata, dict) else {}),
        "status": provider_status,
        "source": source,
        "platform": platform,
        "requests": request_count,
        "candidateCount": len(candidates),
    }


def _provider_payloads(provider: Any) -> list[Any]:
    payloads = getattr(provider, "last_raw_payloads", [])
    if not isinstance(payloads, list):
        return []
    return payloads


def _combined_tiktok_status(
    socialcrawl: dict[str, Any],
    creative_center: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": (
            "available"
            if "available" in {socialcrawl.get("status"), creative_center.get("status")}
            else "unavailable"
        )
    }


def _tiktok_music_ids(candidates: list[TrendCandidate]) -> list[str]:
    return sorted(
        {
            sound.sound_id
            for candidate in candidates
            for sound in candidate.platform_sound_ids
            if sound.platform == "tiktok"
        }
    )


def _load_private_audio_secrets() -> None:
    runtime = resolve_runtime_paths()
    env_file = Path(
        os.environ.get(
            "CREATOR_OS_AUDIO_REFRESH_ENV",
            runtime.config_root / "generation.env",
        )
    ).expanduser()
    values = _load_env_file(env_file)
    for name in _SECRET_ENVS:
        value = values.get(name, "").strip()
        if value and not os.environ.get(name):
            os.environ[name] = value


def _rank_with_history(
    conn: sqlite3.Connection,
    candidates: list[TrendCandidate],
    *,
    now: str,
) -> list[RankedCandidate]:
    prior_performance: dict[str, float] = {}
    enriched: list[TrendCandidate] = []
    recent_cutoff = (_parse_time(now) - timedelta(days=30)).isoformat()
    for candidate in candidates:
        canonical_id = str(candidate.canonical_track_id)
        row = conn.execute(
            """
            SELECT id, creator_fit_score, account_fit_score, fatigue_score,
                   performance_lift
            FROM audio_catalog
            WHERE canonical_track_id = ?
            """,
            (canonical_id,),
        ).fetchone()
        if row is None and candidate.platform_sound_ids:
            predicates = " OR ".join(
                "(s.platform = ? AND s.sound_id = ?)"
                for _ in candidate.platform_sound_ids
            )
            parameters = [
                value
                for sound in candidate.platform_sound_ids
                for value in (sound.platform, sound.sound_id)
            ]
            row = conn.execute(
                f"""
                SELECT c.id, c.creator_fit_score, c.account_fit_score,
                       c.fatigue_score, c.performance_lift
                FROM audio_catalog c
                JOIN audio_platform_sound_ids s ON s.audio_catalog_id = c.id
                WHERE {predicates}
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        if row is None:
            enriched.append(candidate)
            continue
        performance = conn.execute(
            """
            SELECT MAX(score) AS score
            FROM audio_performance_rollups
            WHERE audio_catalog_id = ?
            """,
            (row["id"],),
        ).fetchone()
        values = [
            value
            for value in (
                performance["score"] if performance else None,
                row["performance_lift"],
            )
            if value is not None
        ]
        if values:
            prior_performance[canonical_id] = max(float(value) for value in values)
        recent_uses = conn.execute(
            """
            SELECT COUNT(*) FROM audio_selections
            WHERE audio_catalog_id = ? AND updated_at >= ?
            """,
            (row["id"], recent_cutoff),
        ).fetchone()[0]
        labels = dict(candidate.advisory_labels)
        labels["localCatalogId"] = str(row["id"])
        labels["localUsageLast30Days"] = int(recent_uses)
        if values:
            labels["localPerformanceScore"] = max(float(value) for value in values)
        for key, value in (
            ("creatorFit", row["creator_fit_score"]),
            ("visualMotionFit", row["account_fit_score"]),
            ("fleetOveruse", row["fatigue_score"]),
        ):
            normalized = _unit_score(value)
            if normalized is not None:
                labels[key] = normalized
        if recent_uses:
            labels["fleetOveruse"] = max(
                float(labels.get("fleetOveruse") or 0),
                min(1.0, float(recent_uses) / 10.0),
            )
            labels["recentFleetUses"] = int(recent_uses)
        enriched.append(replace(candidate, advisory_labels=labels))
    return rank_candidates(
        enriched,
        AudioMatchContext(
            creator="fleet",
            account="fleet",
            previous_performance=prior_performance,
        ),
        limit=max(1, len(enriched)),
    )


def _upsert_candidate(
    conn: sqlite3.Connection,
    *,
    candidate: TrendCandidate,
    ranked: RankedCandidate,
    run_id: str,
    now: str,
) -> str:
    canonical_id = str(candidate.canonical_track_id)
    row = conn.execute(
        "SELECT id, pinned, active, imported_at FROM audio_catalog "
        "WHERE canonical_track_id = ?",
        (canonical_id,),
    ).fetchone()
    catalog_id = str(row["id"]) if row else f"audradar_{canonical_id}"
    sound_ids = candidate.platform_sound_ids
    platforms = sorted({value.platform for value in sound_ids})
    platform = platforms[0] if len(platforms) == 1 else "cross_platform"
    primary = sound_ids[0] if sound_ids else None
    lifecycle = "PINNED" if row and int(row["pinned"]) else ranked.bucket
    if lifecycle not in _LIFECYCLE_STATES:
        lifecycle = "EVERGREEN"
    conn.execute(
        """
        INSERT INTO audio_catalog (
          id, source_audio_id, canonical_track_id, canonical_title,
          canonical_artists_json, variant, title, artist_name, platform,
          native_audio_id, native_audio_url, trend_status, usage_count,
          trend_score, velocity_score, trend_sources_json, resolved,
          lifecycle_state, pinned, active, last_seen_refresh_id,
          consecutive_absences, last_seen_at, refresh_metadata_json,
          raw_json, imported_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                  ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          canonical_title = COALESCE(
            NULLIF(excluded.canonical_title, ''),
            audio_catalog.canonical_title
          ),
          canonical_artists_json = CASE
            WHEN excluded.canonical_artists_json != '[]'
            THEN excluded.canonical_artists_json
            ELSE audio_catalog.canonical_artists_json
          END,
          variant = excluded.variant,
          title = COALESCE(NULLIF(excluded.title, ''), audio_catalog.title),
          artist_name = COALESCE(
            NULLIF(excluded.artist_name, ''),
            audio_catalog.artist_name
          ),
          platform = excluded.platform,
          native_audio_id = excluded.native_audio_id,
          native_audio_url = excluded.native_audio_url,
          trend_status = excluded.trend_status,
          usage_count = excluded.usage_count,
          trend_score = excluded.trend_score,
          velocity_score = excluded.velocity_score,
          trend_sources_json = excluded.trend_sources_json,
          lifecycle_state = CASE
            WHEN audio_catalog.pinned = 1 THEN 'PINNED'
            ELSE excluded.lifecycle_state
          END,
          last_seen_refresh_id = excluded.last_seen_refresh_id,
          consecutive_absences = 0,
          last_seen_at = excluded.last_seen_at,
          refresh_metadata_json = excluded.refresh_metadata_json,
          raw_json = excluded.raw_json,
          updated_at = excluded.updated_at
        """,
        (
            catalog_id,
            canonical_id,
            canonical_id,
            candidate.canonical_title or candidate.title,
            _json(candidate.canonical_artists),
            candidate.variant,
            candidate.title,
            candidate.artist,
            platform,
            primary.sound_id if primary else None,
            primary.url if primary else None,
            lifecycle,
            candidate.usage_total,
            candidate.trend_score,
            candidate.usage_velocity,
            _json(sorted({candidate.provider})),
            lifecycle,
            int(row["pinned"]) if row else 0,
            int(row["active"]) if row else 0,
            run_id,
            now,
            _json(
                {
                    "score": ranked.score,
                    "reasons": ranked.reasons,
                    "observations": candidate.advisory_labels.get("observations", []),
                }
            ),
            _json(candidate.as_dict()),
            str(row["imported_at"]) if row else now,
            now,
        ),
    )
    for sound in sound_ids:
        sound_row_id = (
            "audsid_"
            + hashlib.sha256(
                f"{sound.platform}:{sound.sound_id}:{sound.region or ''}".encode()
            ).hexdigest()[:20]
        )
        conn.execute(
            """
            INSERT INTO audio_platform_sound_ids (
              id, audio_catalog_id, platform, sound_id, region, detail_url,
              first_seen_at, last_seen_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, sound_id, region) DO UPDATE SET
              audio_catalog_id = excluded.audio_catalog_id,
              detail_url = COALESCE(excluded.detail_url, detail_url),
              last_seen_at = excluded.last_seen_at,
              raw_json = excluded.raw_json
            """,
            (
                sound_row_id,
                catalog_id,
                sound.platform,
                sound.sound_id,
                sound.region or "",
                sound.url,
                now,
                now,
                _json(asdict(sound)),
            ),
        )
    snapshot_id = (
        "audtrend_" + hashlib.sha256(f"{catalog_id}:{run_id}".encode()).hexdigest()[:20]
    )
    conn.execute(
        """
        INSERT INTO audio_trend_snapshots (
          id, audio_catalog_id, platform, native_audio_id, observed_at,
          trend_status, usage_count, saturation_score, velocity_score,
          source, notes, raw_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(audio_catalog_id, observed_at) DO UPDATE SET
          trend_status = excluded.trend_status,
          usage_count = excluded.usage_count,
          saturation_score = excluded.saturation_score,
          velocity_score = excluded.velocity_score,
          source = excluded.source,
          notes = excluded.notes,
          raw_json = excluded.raw_json
        """,
        (
            snapshot_id,
            catalog_id,
            platform,
            primary.sound_id if primary else None,
            now,
            lifecycle,
            candidate.usage_total,
            candidate.saturation,
            candidate.usage_velocity,
            candidate.provider,
            ",".join(ranked.reasons),
            _json(candidate.as_dict()),
            now,
        ),
    )
    return catalog_id


def _acquire_ranked_candidates(
    conn: sqlite3.Connection,
    *,
    ranked: list[RankedCandidate],
    catalog_ids: dict[str, str],
    resolver: Any,
    cache: AudioCache,
    max_new: int,
    max_active: int,
    retrieved_at: str,
) -> dict[str, Any]:
    downloaded = 0
    activated = 0
    receipts: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    tiklive: dict[str, Any] = {
        "status": "not_called",
        "requests": 0,
        "resolved": 0,
        "unavailable": 0,
        "creditsUsed": None,
        "creditsRemaining": None,
    }
    conn.execute(
        "UPDATE audio_catalog SET active = 0 WHERE active = 1 AND resolved = 0"
    )
    active_count = _scalar(
        conn, "SELECT COUNT(*) FROM audio_catalog WHERE active = 1 AND resolved = 1"
    )
    for ranked_candidate in ranked:
        if activated >= max_new or active_count >= max_active:
            break
        candidate = ranked_candidate.candidate
        catalog_id = catalog_ids[str(candidate.canonical_track_id)]
        row = conn.execute(
            "SELECT active, pinned FROM audio_catalog WHERE id = ?",
            (catalog_id,),
        ).fetchone()
        if row is None or int(row["active"]):
            continue
        cached = conn.execute(
            """
            SELECT * FROM audio_cache_objects
            WHERE audio_catalog_id = ? AND cached = 1
            ORDER BY retrieved_at DESC LIMIT 1
            """,
            (catalog_id,),
        ).fetchone()
        if cached and Path(str(cached["cache_path"])).is_file():
            conn.execute(
                """
                UPDATE audio_catalog
                SET active = 1, activated_at = COALESCE(activated_at, ?),
                    resolved = 1, updated_at = ?
                WHERE id = ?
                """,
                (retrieved_at, retrieved_at, catalog_id),
            )
            activated += 1
            active_count += 1
            continue

        locator = candidate.locator
        details: TikLiveAudioDetails | None = None
        tiktok_ids = [
            sound.sound_id
            for sound in candidate.platform_sound_ids
            if sound.platform == "tiktok"
        ]
        if tiktok_ids and tiklive["requests"] < max_new:
            tiklive["status"] = "available"
            tiklive["requests"] += 1
            try:
                details = resolver.resolve_details(tiktok_ids[0])
                locator = details.locator
                tiklive["resolved"] += 1
                tiklive["creditsUsed"] = _sum_optional(
                    tiklive["creditsUsed"], details.credits_used
                )
                if details.credits_remaining is not None:
                    tiklive["creditsRemaining"] = details.credits_remaining
            except (ProviderError, ProviderCredentialError, OSError):
                tiklive["unavailable"] += 1
                if tiklive["resolved"] == 0:
                    tiklive["status"] = "unavailable"
        if locator is None or downloaded >= max_new:
            continue
        try:
            acquired = cache.acquire(locator, retrieved_at=retrieved_at)
            acoustic = decoded_audio_fingerprint(acquired.cache_path)
        except (AudioAcquisitionError, SegmentSelectionError, OSError):
            continue
        object_id = (
            "audobj_"
            + hashlib.sha256(
                f"{catalog_id}:{acquired.byte_sha256}".encode()
            ).hexdigest()[:20]
        )
        source_metadata = (
            details.receipt()
            if details
            else {
                "trackId": locator.track_id,
                "provider": locator.provider,
            }
        )
        conn.execute(
            """
            INSERT INTO audio_cache_objects (
              id, audio_catalog_id, provider, platform, platform_sound_id,
              cache_path, byte_sha256, acoustic_fingerprint, duration_seconds,
              size_bytes, codec, sample_rate, channels, source_fingerprint,
              source_metadata_json, cached, retrieved_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(audio_catalog_id, byte_sha256) DO UPDATE SET
              cache_path = excluded.cache_path,
              acoustic_fingerprint = excluded.acoustic_fingerprint,
              source_metadata_json = excluded.source_metadata_json,
              cached = 1,
              pruned_at = NULL,
              prune_reason = NULL,
              updated_at = excluded.updated_at
            """,
            (
                object_id,
                catalog_id,
                acquired.provider,
                acquired.platform,
                acquired.track_id,
                str(acquired.cache_path),
                acquired.byte_sha256,
                acoustic,
                acquired.duration_seconds,
                acquired.size_bytes,
                acquired.codec,
                acquired.sample_rate,
                acquired.channels,
                acquired.source_fingerprint,
                _json(source_metadata),
                retrieved_at,
                retrieved_at,
                retrieved_at,
            ),
        )
        conn.execute(
            """
            UPDATE audio_catalog
            SET active = 1, activated_at = COALESCE(activated_at, ?),
                resolved = 1,
                title = COALESCE(NULLIF(?, ''), title),
                artist_name = COALESCE(NULLIF(?, ''), artist_name),
                canonical_title = CASE
                  WHEN canonical_title IS NULL OR canonical_title = ''
                  THEN COALESCE(NULLIF(?, ''), canonical_title)
                  ELSE canonical_title
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                retrieved_at,
                details.title if details else candidate.title,
                candidate.artist,
                details.title if details else candidate.title,
                retrieved_at,
                catalog_id,
            ),
        )
        downloaded += 1
        activated += 1
        active_count += 1
        receipt = acquired.receipt()
        receipt.update(
            {
                "audioCatalogId": catalog_id,
                "acousticFingerprint": acoustic,
                "sourceMetadata": source_metadata,
            }
        )
        receipts.append(receipt)
        sample.append(
            {
                "audioCatalogId": catalog_id,
                "expectedTitle": candidate.title,
                "expectedCanonicalArtist": candidate.artist,
                "resolvedTitle": details.title if details else candidate.title,
                "resolvedSoundOwner": details.sound_owner if details else None,
                "soundOwnerPresentedAsPerformer": False,
                "validAudioStream": True,
                "durationSeconds": acquired.duration_seconds,
                "sha256": acquired.byte_sha256,
                "acousticFingerprint": acoustic,
                "cachePath": str(acquired.cache_path),
                "playableLocalCacheObject": acquired.cache_path.is_file(),
            }
        )
    if tiklive["requests"] == 0:
        tiklive["status"] = "not_called"
    conn.commit()
    return {
        "downloaded": downloaded,
        "activated": activated,
        "receipts": receipts,
        "sampleVerification": sample,
        "tiklive": tiklive,
    }


def _separate_legacy_tiklive_sound_owners(conn: sqlite3.Connection) -> int:
    """Relabel legacy TikLive authors and clear only proven false artist mappings."""

    changed = 0
    rows = conn.execute(
        """
        SELECT o.id, o.audio_catalog_id, o.source_metadata_json,
               c.artist_name, c.raw_json
        FROM audio_cache_objects AS o
        JOIN audio_catalog AS c ON c.id = o.audio_catalog_id
        WHERE o.provider = 'tikliveapi'
        """
    ).fetchall()
    for row in rows:
        metadata = _json_object(row["source_metadata_json"])
        legacy_author = str(metadata.get("author") or "").strip()
        sound_owner = str(metadata.get("soundOwner") or legacy_author).strip()
        if not sound_owner:
            continue
        if "author" in metadata or not metadata.get("soundOwner"):
            metadata.pop("author", None)
            metadata["soundOwner"] = sound_owner
            conn.execute(
                """
                UPDATE audio_cache_objects
                SET source_metadata_json = ?
                WHERE id = ?
                """,
                (_json(metadata), row["id"]),
            )
            changed += 1

        raw_candidate = _json_object(row["raw_json"])
        canonical_artist = str(raw_candidate.get("artist") or "").strip()
        stored_artist = str(row["artist_name"] or "").strip()
        if not canonical_artist and stored_artist == sound_owner:
            conn.execute(
                """
                UPDATE audio_catalog
                SET artist_name = NULL, canonical_artists_json = '[]'
                WHERE id = ?
                """,
                (row["audio_catalog_id"],),
            )
    conn.commit()
    return changed


def _recalculate_lifecycle(
    conn: sqlite3.Connection,
    *,
    seen_catalog_ids: set[str],
    ranked: list[RankedCandidate],
    catalog_ids: dict[str, str],
    successful_platforms: set[str],
    run_id: str,
    now: str,
    max_active: int,
    config: LifecycleThresholds,
) -> dict[str, int]:
    if not successful_platforms:
        return {"cooling": 0, "stale": 0}
    ranked_states = {
        catalog_ids[str(value.candidate.canonical_track_id)]: value.bucket
        for value in ranked
    }
    rows = conn.execute("SELECT * FROM audio_catalog").fetchall()
    cooling = 0
    stale = 0
    for row in rows:
        catalog_id = str(row["id"])
        pinned = bool(row["pinned"])
        winner = _recent_performance_winner(conn, catalog_id, now=now, config=config)
        if not bool(row["resolved"]):
            state = "STALE"
            active = 0
            absences = int(row["consecutive_absences"] or 0)
        elif pinned:
            state = "PINNED"
            active = 1
            absences = int(row["consecutive_absences"] or 0)
        elif catalog_id in seen_catalog_ids:
            state = "PROVEN" if winner else ranked_states.get(catalog_id, "EVERGREEN")
            active = int(row["active"] or 0)
            absences = 0
        else:
            relevant_platforms = {
                str(value["platform"])
                for value in conn.execute(
                    "SELECT platform FROM audio_platform_sound_ids "
                    "WHERE audio_catalog_id = ?",
                    (catalog_id,),
                ).fetchall()
            }
            coverage_complete = bool(
                relevant_platforms
            ) and relevant_platforms.issubset(successful_platforms)
            absences = int(row["consecutive_absences"] or 0)
            if coverage_complete:
                absences += 1
            if winner:
                state = "PROVEN"
                active = int(row["active"] or 0)
            elif coverage_complete and absences >= config.stale_after_absences:
                state = "STALE"
                active = 0
            elif coverage_complete and absences > 0:
                state = "COOLING"
                active = int(row["active"] or 0)
            else:
                state = str(row["lifecycle_state"] or "EVERGREEN")
                active = int(row["active"] or 0)
        if state == "COOLING":
            cooling += 1
        elif state == "STALE":
            stale += 1
        conn.execute(
            """
            UPDATE audio_catalog
            SET lifecycle_state = ?, trend_status = ?, active = ?,
                consecutive_absences = ?, updated_at = ?,
                last_seen_refresh_id = CASE
                  WHEN id IN ({seen_placeholders}) THEN ?
                  ELSE last_seen_refresh_id
                END
            WHERE id = ?
            """.format(
                seen_placeholders=",".join("?" for _ in seen_catalog_ids) or "NULL"
            ),
            (
                state,
                state,
                active,
                absences,
                now,
                *seen_catalog_ids,
                run_id,
                catalog_id,
            ),
        )
    _enforce_active_cap(
        conn,
        ranked_ids=[
            catalog_ids[str(value.candidate.canonical_track_id)] for value in ranked
        ],
        max_active=max_active,
        now=now,
    )
    conn.commit()
    return {"cooling": cooling, "stale": stale}


def _enforce_active_cap(
    conn: sqlite3.Connection,
    *,
    ranked_ids: list[str],
    max_active: int,
    now: str,
) -> None:
    pinned = {
        str(row["id"])
        for row in conn.execute(
            "SELECT id FROM audio_catalog "
            "WHERE active = 1 AND pinned = 1 AND resolved = 1"
        ).fetchall()
    }
    keep = set(pinned)
    for catalog_id in ranked_ids:
        if len(keep) >= max_active:
            break
        cached = conn.execute(
            "SELECT 1 FROM audio_cache_objects "
            "WHERE audio_catalog_id = ? AND cached = 1",
            (catalog_id,),
        ).fetchone()
        if cached:
            keep.add(catalog_id)
    if len(keep) < max_active:
        for row in conn.execute(
            """
            SELECT id FROM audio_catalog
            WHERE active = 1 AND resolved = 1
              AND lifecycle_state IN ('PROVEN', 'EVERGREEN', 'COOLING')
            ORDER BY CASE lifecycle_state
              WHEN 'PROVEN' THEN 0 WHEN 'EVERGREEN' THEN 1 ELSE 2 END,
              updated_at DESC
            """
        ).fetchall():
            keep.add(str(row["id"]))
            if len(keep) >= max_active:
                break
    if keep:
        placeholders = ",".join("?" for _ in keep)
        conn.execute(
            f"UPDATE audio_catalog SET active = 0, updated_at = ? "
            f"WHERE active = 1 AND pinned = 0 AND id NOT IN ({placeholders})",
            (now, *keep),
        )
    else:
        conn.execute(
            "UPDATE audio_catalog SET active = 0, updated_at = ? "
            "WHERE active = 1 AND pinned = 0",
            (now,),
        )


def _prune_cache(
    conn: sqlite3.Connection,
    *,
    cache: AudioCache,
    run_id: str,
    now: str,
    config: LifecycleThresholds,
) -> list[dict[str, Any]]:
    cutoff = (_parse_time(now) - timedelta(days=config.retention_days)).isoformat()
    rows = conn.execute(
        """
        SELECT o.*, c.canonical_track_id, c.pinned, c.consecutive_absences,
               c.lifecycle_state
        FROM audio_cache_objects o
        JOIN audio_catalog c ON c.id = o.audio_catalog_id
        WHERE o.cached = 1
          AND c.consecutive_absences >= ?
          AND c.pinned = 0
          AND o.retrieved_at < ?
        ORDER BY o.retrieved_at, o.id
        """,
        (config.stale_after_absences, cutoff),
    ).fetchall()
    receipts: list[dict[str, Any]] = []
    for row in rows:
        reasons = _retention_reasons(
            conn,
            audio_catalog_id=str(row["audio_catalog_id"]),
            canonical_track_id=str(row["canonical_track_id"] or ""),
            now=now,
            config=config,
        )
        if reasons:
            continue
        try:
            deleted_bytes = cache.delete_verified(
                Path(str(row["cache_path"])),
                expected_sha256=str(row["byte_sha256"]),
            )
        except AudioAcquisitionError:
            continue
        prune_id = (
            "audprune_"
            + hashlib.sha256(f"{run_id}:{row['id']}".encode()).hexdigest()[:20]
        )
        reason = (
            f"absent_{row['consecutive_absences']}_refreshes_and_"
            f"older_than_{config.retention_days}_days"
        )
        conn.execute(
            """
            UPDATE audio_cache_objects
            SET cached = 0, pruned_at = ?, prune_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, reason, now, row["id"]),
        )
        conn.execute(
            """
            INSERT INTO audio_cache_prune_receipts (
              id, refresh_run_id, audio_cache_object_id, audio_catalog_id,
              cache_path, byte_sha256, acoustic_fingerprint, size_bytes,
              reason, pruned_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prune_id,
                run_id,
                row["id"],
                row["audio_catalog_id"],
                row["cache_path"],
                row["byte_sha256"],
                row["acoustic_fingerprint"],
                deleted_bytes,
                reason,
                now,
                now,
            ),
        )
        receipts.append(
            {
                "pruneReceiptId": prune_id,
                "audioCacheObjectId": row["id"],
                "audioCatalogId": row["audio_catalog_id"],
                "cachePath": row["cache_path"],
                "byteSha256": row["byte_sha256"],
                "acousticFingerprint": row["acoustic_fingerprint"],
                "sizeBytes": deleted_bytes,
                "reason": reason,
                "prunedAt": now,
                "metadataDeleted": False,
                "cachedBytesDeleted": True,
            }
        )
    conn.commit()
    return receipts


def _retention_reasons(
    conn: sqlite3.Connection,
    *,
    audio_catalog_id: str,
    canonical_track_id: str,
    now: str,
    config: LifecycleThresholds,
) -> list[str]:
    values = [audio_catalog_id, canonical_track_id]
    values.extend(
        str(row["sound_id"])
        for row in conn.execute(
            "SELECT sound_id FROM audio_platform_sound_ids WHERE audio_catalog_id = ?",
            (audio_catalog_id,),
        ).fetchall()
    )
    values = [value for value in dict.fromkeys(values) if value]
    if _recent_performance_winner(conn, audio_catalog_id, now=now, config=config):
        return ["recent_performance_winner"]
    selection = conn.execute(
        """
        SELECT 1 FROM audio_selections
        WHERE audio_catalog_id = ?
          AND lower(status) IN (
            'selected', 'pending', 'approved', 'scheduled', 'verified', 'draft'
          )
        LIMIT 1
        """,
        (audio_catalog_id,),
    ).fetchone()
    if selection:
        return ["approved_or_scheduled_selection"]
    for value in values:
        pattern = f"%{value}%"
        job = conn.execute(
            """
            SELECT 1 FROM pipeline_jobs
            WHERE status IN ('queued', 'running') AND input_json LIKE ?
            LIMIT 1
            """,
            (pattern,),
        ).fetchone()
        if job:
            return ["pending_generation_job"]
        asset = conn.execute(
            """
            SELECT id, review_state FROM rendered_assets
            WHERE (caption_generation_json LIKE ? OR metadata_json LIKE ?)
              AND lower(review_state) NOT IN ('rejected', 'published')
            LIMIT 1
            """,
            (pattern, pattern),
        ).fetchone()
        if asset:
            distribution = conn.execute(
                "SELECT 1 FROM distribution_plans WHERE rendered_asset_id = ? LIMIT 1",
                (asset["id"],),
            ).fetchone()
            if distribution:
                return ["approved_or_scheduled_draft"]
            proof = conn.execute(
                """
                SELECT 1 FROM proof_runs
                WHERE rendered_asset_id = ?
                  AND (completed_at IS NULL OR lower(status) NOT IN ('completed', 'done'))
                LIMIT 1
                """,
                (asset["id"],),
            ).fetchone()
            if proof:
                return ["unpublished_final_or_recovery"]
            return ["unpublished_final"]
    return []


def _recent_performance_winner(
    conn: sqlite3.Connection,
    audio_catalog_id: str,
    *,
    now: str,
    config: LifecycleThresholds,
) -> bool:
    cutoff = (
        _parse_time(now) - timedelta(days=config.winner_lookback_days)
    ).isoformat()
    return (
        conn.execute(
            """
            SELECT 1 FROM audio_performance_rollups
            WHERE audio_catalog_id = ? AND score >= ? AND updated_at >= ?
            LIMIT 1
            """,
            (audio_catalog_id, config.winner_score, cutoff),
        ).fetchone()
        is not None
    )


def _history_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: _scalar(conn, f"SELECT COUNT(*) FROM {table}")
        for table in (
            "audio_catalog",
            "audio_platform_sound_ids",
            "audio_trend_snapshots",
            "audio_selections",
            "audio_performance_rollups",
            "performance_snapshots",
            "generation_lineage_edges",
        )
    }


def _credits(sources: dict[str, Any]) -> dict[str, Any]:
    instagram = sources.get("socialcrawlInstagram") or {}
    tiktok = sources.get("socialcrawlTikTok") or {}
    tiklive = sources.get("tiklive") or {}
    used_values = [
        value
        for value in (
            instagram.get("creditsUsed"),
            tiktok.get("creditsUsed"),
            tiklive.get("creditsUsed"),
        )
        if isinstance(value, (int, float))
    ]
    social_used_values = [
        value
        for value in (instagram.get("creditsUsed"), tiktok.get("creditsUsed"))
        if isinstance(value, (int, float))
    ]
    return {
        "used": sum(used_values) if used_values else None,
        "socialcrawlUsed": (sum(social_used_values) if social_used_values else None),
        "socialcrawlInstagramUsed": instagram.get("creditsUsed"),
        "socialcrawlTikTokUsed": tiktok.get("creditsUsed"),
        "socialcrawlRemaining": (
            tiktok.get("creditsRemaining")
            if tiktok.get("creditsRemaining") is not None
            else instagram.get("creditsRemaining")
        ),
        "tikliveUsed": tiklive.get("creditsUsed"),
        "tikliveRemaining": tiklive.get("creditsRemaining"),
        "tokchartUsed": 0,
    }


def _overall_status(sources: dict[str, Any]) -> str:
    primary_discovery = [
        sources.get("socialcrawlInstagram", {}).get("status"),
        sources.get("socialcrawlTikTok", {}).get("status"),
    ]
    if all(value == "available" for value in primary_discovery):
        return "success"
    if any(value in {"available", "partial"} for value in primary_discovery) or (
        sources.get("tiktokCreativeCenter", {}).get("status") == "available"
    ):
        return "partial"
    return "unavailable"


@contextmanager
def _single_instance_lock(path: Path) -> Iterator[None]:
    selected = path.expanduser()
    selected.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    selected.parent.chmod(0o700)
    descriptor = os.open(selected, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("audio refresh is already running") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _receipt_paths(root: Path, run_id: str) -> tuple[Path, Path]:
    selected = root.expanduser().resolve()
    selected.mkdir(parents=True, exist_ok=True, mode=0o700)
    selected.chmod(0o700)
    return (
        selected / f"{run_id}-candidates.json",
        selected / f"{run_id}-receipt.json",
    )


def _write_private_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def _redact(value: Any) -> Any:
    secret_values = tuple(
        os.environ.get(name, "") for name in _SECRET_ENVS if os.environ.get(name)
    )
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if _sensitive_key(key) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


def _sensitive_key(key: object) -> bool:
    normalized = "".join(
        character for character in str(key).lower() if character.isalnum()
    )
    return any(
        token in normalized
        for token in ("apikey", "authorization", "secret", "token", "cookie")
    )


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _run_id(now: str, region: str) -> str:
    stamp = "".join(character for character in now if character.isdigit())[:14]
    digest = hashlib.sha256(f"{now}:{region}".encode()).hexdigest()[:8]
    return f"audio_refresh_{stamp}_{digest}"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_object(value: object) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0] if row else 0)


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return float(left or 0) + float(right or 0)


def _unit_score(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score /= 100
    return max(0.0, min(1.0, score))
