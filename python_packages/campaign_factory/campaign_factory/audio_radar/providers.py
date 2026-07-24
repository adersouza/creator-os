"""Real provider adapters plus fixture/public-snapshot support."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from .models import AudioLocator, PlatformSoundId, TrendCandidate


class ProviderError(RuntimeError):
    """A provider could not return a valid, bounded response."""


class ProviderCredentialError(ProviderError):
    """A required provider credential is absent."""


class TrendProvider(Protocol):
    """Provider-neutral trend discovery interface."""

    provider_name: str

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        """Return current trend observations without acquiring media bytes."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _payload_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if isinstance(data, Mapping):
        raw = data.get("items") or data.get("tracks") or data.get("audios")
    else:
        raw = data
    if raw is None:
        raw = payload.get("items")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ProviderError("provider response did not include an item list")
    return [value for value in raw if isinstance(value, Mapping)]


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string(value: object) -> str:
    return str(value or "").strip()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProviderCredentialError(f"{name} is required")
    return value


class SocialCrawlInstagramProvider:
    """Instagram trending-audio adapter for SocialCrawl."""

    provider_name = "socialcrawl"
    credential_env = "SOCIALCRAWL_API_KEY"
    endpoint = "https://www.socialcrawl.dev/v1/instagram/music/trending"

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        key = _required_env(self.credential_env)
        response = self.session.get(
            self.endpoint,
            headers={"x-api-key": key, "Accept": "application/json"},
            timeout=30,
        )
        if response.status_code != 200:
            raise ProviderError(
                f"socialcrawl trending request failed: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("success") is False:
            raise ProviderError("socialcrawl trending response was unsuccessful")
        return self.parse(payload, region=region, limit=limit)

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any],
        *,
        region: str | None,
        limit: int,
    ) -> list[TrendCandidate]:
        observed_at = _string(payload.get("observed_at")) or _utc_now()
        fingerprint = _payload_fingerprint(payload)
        candidates: list[TrendCandidate] = []
        for index, item in enumerate(_items(payload)[: max(1, limit)], start=1):
            sound_id = _string(
                item.get("audio_id") or item.get("audioId") or item.get("id")
            )
            title = _string(
                item.get("title") or item.get("track_title") or item.get("audio_title")
            )
            if not sound_id or not title:
                continue
            artist = _string(item.get("artist") or item.get("artist_name"))
            audio_url = _string(
                item.get("audio_url") or item.get("audioUrl") or item.get("play_url")
            )
            locator = (
                AudioLocator(
                    provider=cls.provider_name,
                    platform="instagram",
                    track_id=sound_id,
                    kind="playable_url",
                    value=audio_url,
                    allowed_hosts=_host_suffixes(audio_url),
                )
                if audio_url
                else None
            )
            candidates.append(
                TrendCandidate(
                    candidate_id=f"socialcrawl:instagram:{sound_id}",
                    provider=cls.provider_name,
                    title=title,
                    artist=artist,
                    platform_sound_ids=(
                        PlatformSoundId(
                            platform="instagram",
                            sound_id=sound_id,
                            region=region,
                            url=_string(item.get("audio_page_url")) or None,
                        ),
                    ),
                    observed_at=observed_at,
                    region=region,
                    current_rank=_integer(item.get("rank")) or index,
                    previous_rank=_integer(item.get("previous_rank")),
                    usage_total=_integer(
                        item.get("usage_count") or item.get("reels_count")
                    ),
                    usage_velocity=_number(
                        item.get("usage_velocity") or item.get("uses_per_day")
                    ),
                    freshness_hours=_number(item.get("freshness_hours")),
                    trend_score=_number(item.get("trend_score")),
                    saturation=_number(item.get("saturation")),
                    mood_tags=tuple(
                        str(value)
                        for value in (item.get("vibe_tags") or ())
                        if str(value).strip()
                    ),
                    locator=locator,
                    provider_payload_fingerprint=fingerprint,
                )
            )
        return candidates


class TokchartTrendProvider:
    """TikTok Music Trends and Audio UGC adapter for Tokchart."""

    provider_name = "tokchart"
    credential_env = "TOKCHART_API_TOKEN"
    music_endpoint = "https://tokchart.com/api/v1/trending/global"
    audio_endpoint = "https://tokchart.com/api/v1/tiktok/audio/trending/global"

    def __init__(
        self,
        *,
        audio_ugc: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        self.audio_ugc = audio_ugc
        self.session = session or requests.Session()

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        token = _required_env(self.credential_env)
        endpoint = self.audio_endpoint if self.audio_ugc else self.music_endpoint
        params: dict[str, str | int] = {"page_size": max(1, min(limit, 1000))}
        if region:
            params["country"] = region
        response = self.session.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            timeout=30,
        )
        if response.status_code != 200:
            raise ProviderError(
                f"tokchart trend request failed: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ProviderError("tokchart trend response was not an object")
        return self.parse(payload, region=region, limit=limit)

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any],
        *,
        region: str | None,
        limit: int,
    ) -> list[TrendCandidate]:
        observed_at = _string(payload.get("observed_at")) or _utc_now()
        fingerprint = _payload_fingerprint(payload)
        candidates: list[TrendCandidate] = []
        for index, item in enumerate(_items(payload)[: max(1, limit)], start=1):
            sound_id = _string(
                item.get("sound_id") or item.get("music_id") or item.get("id")
            )
            title = _string(item.get("title") or item.get("track_title"))
            if not sound_id or not title:
                continue
            artist_value = (
                item.get("artists") or item.get("artist") or item.get("author")
            )
            if isinstance(artist_value, Sequence) and not isinstance(
                artist_value,
                (str, bytes),
            ):
                artists = tuple(
                    str(value).strip() for value in artist_value if str(value).strip()
                )
                artist = artists[0] if artists else ""
                featured = artists[1:]
            else:
                artist = _string(artist_value)
                featured = ()
            sound_url = _string(item.get("audio_url") or item.get("sound_url"))
            locator = (
                AudioLocator(
                    provider=cls.provider_name,
                    platform="tiktok",
                    track_id=sound_id,
                    kind="playable_url",
                    value=sound_url,
                    allowed_hosts=_host_suffixes(sound_url),
                )
                if sound_url
                else None
            )
            candidates.append(
                TrendCandidate(
                    candidate_id=f"tokchart:tiktok:{sound_id}",
                    provider=cls.provider_name,
                    title=title,
                    artist=artist,
                    featured_artists=featured,
                    platform_sound_ids=(
                        PlatformSoundId(
                            platform="tiktok",
                            sound_id=sound_id,
                            region=region,
                            url=_string(item.get("url")) or None,
                        ),
                    ),
                    observed_at=observed_at,
                    region=region,
                    current_rank=_integer(item.get("chart_index")) or index,
                    previous_rank=_integer(item.get("previous_chart_index")),
                    usage_total=_integer(item.get("ugc_videos_total")),
                    usage_velocity=_number(item.get("ugc_videos_per_day")),
                    freshness_hours=_number(item.get("freshness_hours")),
                    trend_score=_number(item.get("tokchart_score")),
                    saturation=_number(item.get("saturation")),
                    mood_tags=tuple(
                        str(value)
                        for value in (item.get("hashtags") or ())
                        if str(value).strip()
                    ),
                    locator=locator,
                    provider_payload_fingerprint=fingerprint,
                )
            )
        return candidates


class TikLiveAudioResolver:
    """Resolve one TikTok music ID to a provider playback locator."""

    provider_name = "tikliveapi"
    credential_env = "TIKLIVE_API_KEY"
    endpoint = "https://api.tikliveapi.com/music-info/"

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def resolve(self, music_id: str) -> AudioLocator:
        key = _required_env(self.credential_env)
        response = self.session.get(
            self.endpoint,
            headers={"X-Api-Key": key, "Accept": "application/json"},
            params={"music_id": music_id},
            timeout=30,
        )
        if response.status_code != 200:
            raise ProviderError(
                f"tiklive music-info request failed: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ProviderError("tiklive music-info response was not an object")
        return self.parse(payload, music_id=music_id)

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any],
        *,
        music_id: str,
    ) -> AudioLocator:
        play_url = _string(payload.get("play") or payload.get("playUrl"))
        returned_id = _string(payload.get("id") or music_id)
        if returned_id != music_id or not play_url:
            raise ProviderError("tiklive music-info response did not match music ID")
        return AudioLocator(
            provider=cls.provider_name,
            platform="tiktok",
            track_id=music_id,
            kind="playable_url",
            value=play_url,
            allowed_hosts=_host_suffixes(play_url),
        )


class PublicChartSnapshotProvider:
    """Read a permitted, operator-captured public-chart snapshot."""

    provider_name = "public_chart_snapshot"

    def __init__(self, path: Path) -> None:
        self.path = path

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        raw_path = self.path.expanduser()
        if raw_path.is_symlink():
            raise ProviderError("public chart snapshot is missing or unsafe")
        resolved = raw_path.resolve()
        if not resolved.is_file():
            raise ProviderError("public chart snapshot is missing or unsafe")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ProviderError("public chart snapshot must be a JSON object")
        platform = _string(payload.get("platform")) or "unknown"
        provider = _string(payload.get("provider")) or self.provider_name
        observed_at = _string(payload.get("observed_at"))
        if not observed_at:
            raise ProviderError("public chart snapshot needs observed_at")
        candidates: list[TrendCandidate] = []
        for index, item in enumerate(_items(payload)[: max(1, limit)], start=1):
            sound_id = _string(item.get("sound_id") or item.get("id"))
            title = _string(item.get("title"))
            if not sound_id or not title:
                continue
            candidates.append(
                TrendCandidate(
                    candidate_id=f"{provider}:{platform}:{sound_id}",
                    provider=provider,
                    title=title,
                    artist=_string(item.get("artist") or item.get("author")),
                    platform_sound_ids=(
                        PlatformSoundId(
                            platform=platform,
                            sound_id=sound_id,
                            region=region,
                        ),
                    ),
                    observed_at=observed_at,
                    region=region,
                    current_rank=_integer(item.get("rank")) or index,
                    previous_rank=_integer(item.get("previous_rank")),
                    usage_total=_integer(item.get("usage_total")),
                    usage_velocity=_number(item.get("usage_velocity")),
                    freshness_hours=_number(item.get("freshness_hours")),
                    trend_score=_number(item.get("trend_score")),
                    saturation=_number(item.get("saturation")),
                    provider_payload_fingerprint=_payload_fingerprint(payload),
                )
            )
        return candidates


def _host_suffixes(url: str) -> tuple[str, ...]:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return (host,) if host else ()
