"""Typed Audio Radar domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AudioLocatorKind = Literal["playable_url", "authenticated_url", "local_file"]


@dataclass(frozen=True)
class PlatformSoundId:
    """One provider/platform-specific sound identity."""

    platform: str
    sound_id: str
    region: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class AudioLocator:
    """A provider-approved way to acquire bytes without exposing credentials."""

    provider: str
    platform: str
    track_id: str
    kind: AudioLocatorKind
    value: str
    allowed_hosts: tuple[str, ...] = ()
    request_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TrendCandidate:
    """Normalized provider trend observation used for ranking and acquisition."""

    candidate_id: str
    provider: str
    title: str
    artist: str
    platform_sound_ids: tuple[PlatformSoundId, ...]
    observed_at: str
    featured_artists: tuple[str, ...] = ()
    variant: str | None = None
    region: str | None = None
    current_rank: int | None = None
    previous_rank: int | None = None
    usage_total: int | None = None
    usage_velocity: float | None = None
    freshness_hours: float | None = None
    trend_score: float | None = None
    saturation: float | None = None
    mood_tags: tuple[str, ...] = ()
    canonical_track_id: str | None = None
    canonical_title: str | None = None
    canonical_artists: tuple[str, ...] = ()
    locator: AudioLocator | None = None
    provider_payload_fingerprint: str | None = None
    advisory_labels: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe record without acquisition credentials."""

        value = asdict(self)
        locator = value.get("locator")
        if isinstance(locator, dict):
            locator.pop("request_headers", None)
            locator.pop("value", None)
            locator["available"] = True
        return value
