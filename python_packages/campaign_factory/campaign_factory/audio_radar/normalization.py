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
    canonical_variant = _plain(candidate.variant or inferred_variant or "")
    if title and canonical_artists:
        identity = f"{title}|{'|'.join(canonical_artists)}|{canonical_variant}"
    else:
        sound_identity = "|".join(
            sorted(
                f"{value.platform}:{value.sound_id}:{value.region or ''}"
                for value in candidate.platform_sound_ids
            )
        )
        identity = f"provider-sound-id|{sound_identity}|{canonical_variant}"
    canonical_track_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    observation = {
        "provider": candidate.provider,
        "candidateId": candidate.candidate_id,
        "observedAt": candidate.observed_at,
        "region": candidate.region,
        "rank": candidate.current_rank,
        "previousRank": candidate.previous_rank,
        **candidate.advisory_labels,
    }
    return replace(
        candidate,
        canonical_track_id=canonical_track_id,
        canonical_title=title,
        canonical_artists=canonical_artists,
        featured_artists=featured,
        variant=canonical_variant or None,
        advisory_labels={
            **candidate.advisory_labels,
            "observations": [observation],
        },
    )


def normalize_candidates(
    candidates: list[TrendCandidate] | tuple[TrendCandidate, ...],
) -> list[TrendCandidate]:
    """Normalize and merge duplicate platform wrappers for the same song."""

    complete_metadata_by_sound = {
        (sound.platform, sound.sound_id): candidate
        for candidate in candidates
        if candidate.title.strip() and candidate.artist.strip()
        for sound in candidate.platform_sound_ids
    }
    grouped: dict[str, TrendCandidate] = {}
    for raw in candidates:
        metadata_match = next(
            (
                complete_metadata_by_sound[(sound.platform, sound.sound_id)]
                for sound in raw.platform_sound_ids
                if (sound.platform, sound.sound_id) in complete_metadata_by_sound
            ),
            None,
        )
        if metadata_match is not None and (
            not raw.title.strip() or not raw.artist.strip()
        ):
            raw = replace(
                raw,
                title=raw.title or metadata_match.title,
                artist=raw.artist or metadata_match.artist,
                advisory_labels={
                    **raw.advisory_labels,
                    "metadataEnrichedFromSharedSoundId": True,
                },
            )
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
            usage_velocity=_maximum(
                existing.usage_velocity,
                candidate.usage_velocity,
            ),
            freshness_hours=_minimum(
                existing.freshness_hours,
                candidate.freshness_hours,
            ),
            trend_score=_maximum(existing.trend_score, candidate.trend_score),
            saturation=_maximum(existing.saturation, candidate.saturation),
            mood_tags=tuple(dict.fromkeys((*existing.mood_tags, *candidate.mood_tags))),
            locator=existing.locator or candidate.locator,
            advisory_labels=_merge_advisory_labels(
                existing.advisory_labels,
                candidate.advisory_labels,
            ),
        )
    merged = sorted(
        grouped.values(),
        key=lambda item: (
            item.current_rank is None,
            item.current_rank or 10**9,
            str(item.canonical_track_id),
        ),
    )
    return [
        replace(
            item,
            advisory_labels={
                **item.advisory_labels,
                "crossPlatformMatch": (
                    len({sound.platform for sound in item.platform_sound_ids}) > 1
                ),
                "observedPlatforms": sorted(
                    {sound.platform for sound in item.platform_sound_ids}
                ),
            },
        )
        for item in merged
    ]


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


def _merge_advisory_labels(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    observations: list[object] = []
    for value in (left.get("observations"), right.get("observations")):
        if isinstance(value, list):
            observations.extend(value)
    return {
        **left,
        **right,
        "observations": observations,
    }
