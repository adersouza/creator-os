"""Deterministic cross-platform track normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import replace

from .models import PlatformSoundId, TrendCandidate

_FEATURE_RE = re.compile(
    r"\b(?:feat(?:uring)?|ft)\.?\s+(.+?)(?=$|[-–—([])",
    flags=re.IGNORECASE,
)
_VARIANT_RE = re.compile(
    r"(?P<marker>"
    r"sped[\s-]*up|slowed(?:\s*(?:and|&|\+)\s*reverb)?|"
    r"nightcore|remix|edit|instrumental|acoustic|live"
    r")",
    flags=re.IGNORECASE,
)
_BRACKETED_RE = re.compile(r"[\[(]([^\])]+)[\])]")
_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("’", "'")
    return " ".join(_NON_WORD_RE.sub(" ", normalized).split())


def _title_parts(
    title: str,
    featured_artists: tuple[str, ...],
) -> tuple[str, tuple[str, ...], str | None]:
    feature_names = list(featured_artists)
    feature_match = _FEATURE_RE.search(title)
    if feature_match:
        feature_names.extend(
            part.strip()
            for part in re.split(r",|&|\band\b", feature_match.group(1))
            if part.strip()
        )
        title = title[: feature_match.start()].strip()

    variants: list[str] = []
    for bracketed in _BRACKETED_RE.findall(title):
        variants.extend(
            match.group("marker") for match in _VARIANT_RE.finditer(bracketed)
        )
    variants.extend(match.group("marker") for match in _VARIANT_RE.finditer(title))
    title = _BRACKETED_RE.sub(
        lambda match: "" if _VARIANT_RE.search(match.group(1)) else match.group(0),
        title,
    )
    title = _VARIANT_RE.sub("", title)
    canonical_features = tuple(
        sorted({_plain(value) for value in feature_names if _plain(value)})
    )
    canonical_variant = "+".join(sorted({_plain(value) for value in variants})) or None
    return _plain(title), canonical_features, canonical_variant


def normalize_candidate(candidate: TrendCandidate) -> TrendCandidate:
    """Normalize track identity while preserving every platform sound ID."""

    title, featured, inferred_variant = _title_parts(
        candidate.title,
        candidate.featured_artists,
    )
    artist_parts = re.split(
        r"\b(?:feat(?:uring)?|ft)\.?\s+",
        candidate.artist,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    primary_artist = _plain(artist_parts[0])
    if len(artist_parts) == 2:
        featured = tuple(
            sorted(
                {
                    *featured,
                    *(
                        _plain(value)
                        for value in re.split(r",|&|\band\b", artist_parts[1])
                        if _plain(value)
                    ),
                }
            )
        )
    artists = tuple(value for value in (primary_artist, *featured) if value)
    canonical_artists = tuple(dict.fromkeys(artists))
    identity = f"{title}|{'|'.join(canonical_artists)}"
    canonical_track_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return replace(
        candidate,
        canonical_track_id=canonical_track_id,
        canonical_title=title,
        canonical_artists=canonical_artists,
        featured_artists=featured,
        variant=candidate.variant or inferred_variant,
    )


def normalize_candidates(
    candidates: list[TrendCandidate] | tuple[TrendCandidate, ...],
) -> list[TrendCandidate]:
    """Normalize and merge duplicate platform wrappers for the same song."""

    grouped: dict[str, TrendCandidate] = {}
    for raw in candidates:
        candidate = normalize_candidate(raw)
        key = str(candidate.canonical_track_id)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = candidate
            continue
        sound_ids = _merge_sound_ids(
            existing.platform_sound_ids,
            candidate.platform_sound_ids,
        )
        grouped[key] = replace(
            existing,
            platform_sound_ids=sound_ids,
            current_rank=_minimum(existing.current_rank, candidate.current_rank),
            previous_rank=_minimum(existing.previous_rank, candidate.previous_rank),
            usage_total=_maximum(existing.usage_total, candidate.usage_total),
            usage_velocity=_sum(existing.usage_velocity, candidate.usage_velocity),
            freshness_hours=_minimum(
                existing.freshness_hours,
                candidate.freshness_hours,
            ),
            trend_score=_maximum(existing.trend_score, candidate.trend_score),
            saturation=_maximum(existing.saturation, candidate.saturation),
            mood_tags=tuple(dict.fromkeys((*existing.mood_tags, *candidate.mood_tags))),
            locator=existing.locator or candidate.locator,
        )
    return sorted(
        grouped.values(),
        key=lambda item: (
            item.current_rank is None,
            item.current_rank or 10**9,
            str(item.canonical_track_id),
        ),
    )


def _merge_sound_ids(
    left: tuple[PlatformSoundId, ...],
    right: tuple[PlatformSoundId, ...],
) -> tuple[PlatformSoundId, ...]:
    records = {
        (value.platform, value.sound_id, value.region): value
        for value in (*left, *right)
    }
    return tuple(records[key] for key in sorted(records))


def _minimum(left: int | float | None, right: int | float | None):
    values = [value for value in (left, right) if value is not None]
    return min(values) if values else None


def _maximum(left: int | float | None, right: int | float | None):
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def _sum(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return float(left or 0) + float(right or 0)
