"""Deterministic trend, creative-fit, fatigue, and segment-quality ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import TrendCandidate


@dataclass(frozen=True)
class AudioMatchContext:
    """Creative and account history used to rank normalized candidates."""

    creator: str
    account: str
    visual_tags: tuple[str, ...] = ()
    motion_tags: tuple[str, ...] = ()
    caption_tags: tuple[str, ...] = ()
    speaking: bool = False
    previous_performance: dict[str, float] | None = None
    recently_used_track_ids: tuple[str, ...] = ()
    scheduled_batch_track_ids: tuple[str, ...] = ()
    advisory_labels: dict[str, object] | None = None


@dataclass(frozen=True)
class RankedCandidate:
    candidate: TrendCandidate
    score: float
    bucket: str
    reasons: tuple[str, ...]
    excluded: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_dict(),
            "score": self.score,
            "bucket": self.bucket,
            "reasons": list(self.reasons),
            "excluded": self.excluded,
        }


def rank_candidates(
    candidates: list[TrendCandidate],
    context: AudioMatchContext,
    *,
    segment_quality: dict[str, float] | None = None,
    limit: int = 10,
) -> list[RankedCandidate]:
    """Rank compatible tracks and exclude recent/batch reuse completely."""

    segment_quality = segment_quality or {}
    disallowed = {
        *context.recently_used_track_ids,
        *context.scheduled_batch_track_ids,
    }
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        canonical_id = str(candidate.canonical_track_id or candidate.candidate_id)
        excluded = canonical_id in disallowed
        score, reasons = _candidate_score(
            candidate,
            context,
            segment_quality.get(canonical_id),
        )
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                score=round(score, 6),
                bucket=_bucket(candidate),
                reasons=tuple(reasons),
                excluded=excluded,
            )
        )
    eligible = [value for value in ranked if not value.excluded]
    eligible.sort(
        key=lambda value: (
            -value.score,
            value.candidate.current_rank or 10**9,
            str(value.candidate.canonical_track_id),
        )
    )
    return eligible[: max(1, limit)]


def _candidate_score(
    candidate: TrendCandidate,
    context: AudioMatchContext,
    segment_quality: float | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    rank = max(1, int(candidate.current_rank or 100))
    rank_component = 26.0 / math.sqrt(rank)
    velocity = max(0.0, float(candidate.usage_velocity or 0.0))
    velocity_component = min(18.0, math.log1p(velocity) * 1.7)
    usage_component = min(
        10.0,
        math.log1p(max(0, int(candidate.usage_total or 0))) * 0.55,
    )
    platform_count = len({value.platform for value in candidate.platform_sound_ids})
    cross_platform_component = min(12.0, max(0, platform_count - 1) * 6.0)
    freshness = float(candidate.freshness_hours or 24 * 365)
    freshness_component = max(0.0, 12.0 - freshness / (24 * 7))
    creative_tags = {
        *context.visual_tags,
        *context.motion_tags,
        *context.caption_tags,
    }
    mood_tags = set(candidate.mood_tags)
    fit_component = min(14.0, len(creative_tags & mood_tags) * 3.5)
    prior = (context.previous_performance or {}).get(
        str(candidate.canonical_track_id),
        0.0,
    )
    prior_component = max(-8.0, min(10.0, float(prior)))
    saturation_penalty = max(0.0, min(1.0, float(candidate.saturation or 0))) * 14
    segment_component = max(0.0, min(1.0, float(segment_quality or 0))) * 10
    if context.speaking and "talking" not in mood_tags:
        fit_component -= 3
        reasons.append("speaking_fit_penalty")
    if platform_count > 1:
        reasons.append("cross_platform_presence")
    if velocity > 0:
        reasons.append("positive_usage_velocity")
    if freshness <= 24 * 14:
        reasons.append("fresh")
    if fit_component > 0:
        reasons.append("creative_tag_match")
    if segment_component > 0:
        reasons.append("segment_quality")
    score = (
        rank_component
        + velocity_component
        + usage_component
        + cross_platform_component
        + freshness_component
        + fit_component
        + prior_component
        + segment_component
        - saturation_penalty
    )
    return score, reasons


def _bucket(candidate: TrendCandidate) -> str:
    freshness = float(candidate.freshness_hours or 24 * 365)
    velocity = float(candidate.usage_velocity or 0)
    saturation = float(candidate.saturation or 0)
    usage = int(candidate.usage_total or 0)
    if freshness <= 24 * 14 and velocity >= 500 and saturation < 0.65:
        return "BREAKOUT"
    if velocity >= 1000 or (candidate.current_rank or 10**9) <= 20:
        return "HOT"
    if usage >= 100_000:
        return "PROVEN"
    return "EVERGREEN"
