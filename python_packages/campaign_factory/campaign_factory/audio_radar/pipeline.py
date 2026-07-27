"""Bounded candidate fallback from ranked trend to verified MP4."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acquisition import AudioCache, probe_media
from .embedding import EmbeddingSettings, embed_selected_audio
from .ranking import RankedCandidate
from .segment import select_segment


class NeedsEmbeddedAudioError(RuntimeError):
    """All bounded compatible candidates failed acquisition or fulfillment."""

    code = "NEEDS_EMBEDDED_AUDIO"

    def __init__(self, attempts: list[dict[str, object]]) -> None:
        super().__init__(self.code)
        self.attempts = attempts


@dataclass(frozen=True)
class EmbeddedTrendingResult:
    """Successful candidate selection, embedding receipt, and failed attempts."""

    ranked_candidate: RankedCandidate
    embedding_receipt: dict[str, Any]
    attempts: tuple[dict[str, object], ...]


def fulfill_embedded_trending(
    *,
    video_path: Path,
    ranked_candidates: list[RankedCandidate],
    cache: AudioCache,
    output_path: Path,
    retrieved_at: str,
    settings: EmbeddingSettings = EmbeddingSettings(),
    speaking: bool = False,
    max_candidates: int = 5,
) -> EmbeddedTrendingResult:
    """Try a bounded candidate list and never downgrade to silence/native."""

    duration = _media_duration(video_path)
    attempts: list[dict[str, object]] = []
    for ranked in ranked_candidates[: max(1, max_candidates)]:
        candidate = ranked.candidate
        locator = candidate.locator
        canonical_id = str(candidate.canonical_track_id or candidate.candidate_id)
        if locator is None:
            attempts.append(
                {
                    "canonicalTrackId": canonical_id,
                    "status": "failed",
                    "reason": "audio_locator_missing",
                }
            )
            continue
        try:
            acquired = cache.acquire(locator, retrieved_at=retrieved_at)
            segment = select_segment(
                acquired,
                reel_duration_seconds=duration,
                preferred_offsets=_preferred_offsets(candidate.advisory_labels),
                excluded_offsets=_excluded_offsets(candidate.advisory_labels),
            )
            receipt = embed_selected_audio(
                video_path=video_path,
                acquired=acquired,
                segment=segment,
                output_path=output_path,
                settings=settings,
                speaking=speaking,
            )
            attempts.append(
                {
                    "canonicalTrackId": canonical_id,
                    "status": "fulfilled",
                    "candidateScore": ranked.score,
                    "segmentScore": segment.segment_score,
                }
            )
            receipt["selection"] = {
                "canonicalTrackId": canonical_id,
                "canonicalTitle": candidate.canonical_title,
                "canonicalArtists": list(candidate.canonical_artists),
                "platformSoundIds": [
                    {
                        "platform": value.platform,
                        "soundId": value.sound_id,
                        "region": value.region,
                    }
                    for value in candidate.platform_sound_ids
                ],
                "trendRank": candidate.current_rank,
                "trendVelocity": candidate.usage_velocity,
                "rankedScore": ranked.score,
                "bucket": ranked.bucket,
                "selectedReason": list(ranked.reasons),
                "advisoryLabels": candidate.advisory_labels,
            }
            receipt["candidateAttempts"] = attempts
            return EmbeddedTrendingResult(
                ranked_candidate=ranked,
                embedding_receipt=receipt,
                attempts=tuple(attempts),
            )
        except Exception as exc:
            attempts.append(
                {
                    "canonicalTrackId": canonical_id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "detail": str(exc)[:300],
                }
            )
    raise NeedsEmbeddedAudioError(attempts)


def _media_duration(path: Path) -> float:
    probe = probe_media(path)
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0)
    except (AttributeError, TypeError, ValueError) as exc:
        raise NeedsEmbeddedAudioError(
            [{"status": "failed", "reason": "video_duration_invalid"}]
        ) from exc
    if duration <= 0:
        raise NeedsEmbeddedAudioError(
            [{"status": "failed", "reason": "video_duration_invalid"}]
        )
    return duration


def _preferred_offsets(labels: dict[str, object]) -> tuple[float, ...]:
    value = labels.get("preferred_offsets_seconds")
    if not isinstance(value, list):
        return ()
    offsets: list[float] = []
    for raw in value:
        try:
            offset = float(raw)
        except (TypeError, ValueError):
            continue
        if offset >= 0:
            offsets.append(offset)
    return tuple(offsets)


def _excluded_offsets(labels: dict[str, object]) -> tuple[float, ...]:
    value = labels.get("excludedSegmentOffsetsSeconds")
    if not isinstance(value, list):
        return ()
    offsets: list[float] = []
    for raw in value:
        try:
            offset = float(raw)
        except (TypeError, ValueError):
            continue
        if offset >= 0:
            offsets.append(offset)
    return tuple(offsets)
