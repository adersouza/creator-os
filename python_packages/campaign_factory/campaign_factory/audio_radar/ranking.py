"""Deterministic trend, creative-fit, fatigue, and segment-quality ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

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
    components: dict[str, float]
    final_rank: int | None = None
    excluded: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_dict(),
            "score": self.score,
            "bucket": self.bucket,
            "reasons": list(self.reasons),
            "components": self.components,
            "finalRank": self.final_rank,
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
        score, reasons, components = _candidate_score(
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
                components=components,
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
    return [
        replace(value, final_rank=index)
        for index, value in enumerate(eligible[: max(1, limit)], start=1)
    ]


def _candidate_score(
    candidate: TrendCandidate,
    context: AudioMatchContext,
    segment_quality: float | None,
) -> tuple[float, list[str], dict[str, float]]:
    reasons: list[str] = []
    rank_component = (
        26.0 / math.sqrt(max(1, int(candidate.current_rank)))
        if candidate.current_rank is not None
        else 0.0
    )
    velocity = (
        max(0.0, float(candidate.usage_velocity))
        if candidate.usage_velocity is not None
        else None
    )
    velocity_component = (
        min(18.0, math.log1p(velocity) * 1.7) if velocity is not None else 0.0
    )
    usage_component = (
        min(
            10.0,
            math.log1p(max(0, int(candidate.usage_total))) * 0.55,
        )
        if candidate.usage_total is not None
        else 0.0
    )
    platform_count = len({value.platform for value in candidate.platform_sound_ids})
    cross_platform_component = min(12.0, max(0, platform_count - 1) * 6.0)
    freshness = (
        float(candidate.freshness_hours)
        if candidate.freshness_hours is not None
        else None
    )
    freshness_component = (
        max(0.0, 12.0 - freshness / (24 * 7)) if freshness is not None else 0.0
    )
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
    saturation_penalty = (
        max(0.0, min(1.0, float(candidate.saturation))) * 14
        if candidate.saturation is not None
        else 0.0
    )
    segment_component = max(0.0, min(1.0, float(segment_quality or 0))) * 10
    labels = candidate.advisory_labels
    sample_appearances = _optional_float(labels.get("sampleAppearanceCount"))
    total_engagement = _optional_float(labels.get("totalEngagement"))
    sample_component = (
        min(4.0, math.log1p(max(0.0, sample_appearances)) * 1.5)
        if sample_appearances is not None
        else 0.0
    )
    engagement_component = (
        min(8.0, math.log1p(max(0.0, total_engagement)) * 0.5)
        if total_engagement is not None
        else 0.0
    )
    chart_type = str(labels.get("chartType") or "").lower()
    rank_gain = (
        candidate.previous_rank - candidate.current_rank
        if candidate.previous_rank is not None and candidate.current_rank is not None
        else _optional_float(labels.get("rankMovement"))
    )
    chart_component = 7.0 if chart_type == "breakout" else 0.0
    new_component = 5.0 if labels.get("newToTop100") is True else 0.0
    movement_component = (
        min(8.0, max(-4.0, rank_gain * 0.25)) if rank_gain is not None else 0.0
    )
    quality_component = sum(
        max(0.0, min(1.0, value)) * weight
        for value, weight in (
            (_optional_float(labels.get("candidateAudioQuality")), 4.0),
            (_optional_float(labels.get("hookQuality")), 4.0),
            (_optional_float(labels.get("creatorFit")), 5.0),
            (_optional_float(labels.get("visualMotionFit")), 4.0),
        )
        if value is not None
    )
    overuse_penalty = (
        max(0.0, min(1.0, value)) * 8.0
        if (value := _optional_float(labels.get("fleetOveruse"))) is not None
        else 0.0
    )
    if context.speaking and "talking" not in mood_tags:
        fit_component -= 3
        reasons.append("speaking_fit_penalty")
    if platform_count > 1:
        reasons.append("cross_platform_presence")
    if sample_appearances is not None:
        reasons.append("trend_sample_appearances")
    if total_engagement is not None:
        reasons.append("available_engagement_evidence")
    if velocity is not None and velocity > 0:
        reasons.append("positive_usage_velocity")
    if freshness is not None and freshness <= 24 * 14:
        reasons.append("fresh")
    if chart_type == "breakout":
        reasons.append("breakout_chart")
    if labels.get("newToTop100") is True:
        reasons.append("new_to_top_100")
    if rank_gain is not None and rank_gain > 0:
        reasons.append("positive_rank_movement")
    if quality_component > 0:
        reasons.append("available_quality_evidence")
    if fit_component > 0:
        reasons.append("creative_tag_match")
    if segment_component > 0:
        reasons.append("segment_quality")
    trend_score = (
        rank_component
        + velocity_component
        + usage_component
        + cross_platform_component
        + sample_component
        + engagement_component
        + freshness_component
        + chart_component
        + new_component
        + movement_component
    )
    creative_fit_score = fit_component + segment_component + quality_component
    fatigue_penalty = saturation_penalty + overuse_penalty
    score = trend_score + prior_component + creative_fit_score - fatigue_penalty
    components = {
        "trendScore": round(trend_score, 6),
        "performanceAdjustment": round(prior_component, 6),
        "creativeFitScore": round(creative_fit_score, 6),
        "fatiguePenalty": round(fatigue_penalty, 6),
        "finalScore": round(score, 6),
    }
    return score, reasons, components


def _bucket(candidate: TrendCandidate) -> str:
    freshness = candidate.freshness_hours
    velocity = candidate.usage_velocity
    saturation = candidate.saturation
    usage = candidate.usage_total
    rank_gain = (
        candidate.previous_rank - candidate.current_rank
        if candidate.previous_rank is not None and candidate.current_rank is not None
        else _optional_float(candidate.advisory_labels.get("rankMovement"))
    )
    if (
        candidate.advisory_labels.get("newToTop100") is True
        or str(candidate.advisory_labels.get("chartType") or "").lower() == "breakout"
        or (rank_gain is not None and rank_gain >= 10)
        or (
            freshness is not None
            and freshness <= 24 * 14
            and velocity is not None
            and velocity >= 500
            and (saturation is None or saturation < 0.65)
        )
    ):
        return "BREAKOUT"
    if (velocity is not None and velocity >= 1000) or (
        candidate.current_rank is not None and candidate.current_rank <= 20
    ):
        return "HOT"
    if usage is not None and usage >= 100_000:
        return "PROVEN"
    return "EVERGREEN"


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
