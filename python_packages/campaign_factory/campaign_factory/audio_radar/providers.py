"""Real provider adapters plus fixture/public-snapshot support."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Protocol

import requests

from .models import AudioLocator, PlatformSoundId, TrendCandidate


class ProviderError(RuntimeError):
    """A provider could not return a valid, bounded response."""


class ProviderCredentialError(ProviderError):
    """A required provider credential is absent."""


@dataclass(frozen=True)
class TikLiveAudioDetails:
    """TikLive metadata plus the allowlisted locator used by AudioCache."""

    locator: AudioLocator
    title: str | None
    author: str | None
    duration_seconds: float | None
    video_count: int | None
    classification: str | None
    cover_url: str | None
    provider_request_id: str | None = None
    credits_used: float | None = None
    credits_remaining: float | None = None

    def receipt(self) -> dict[str, Any]:
        return {
            "musicId": self.locator.track_id,
            "title": self.title,
            "author": self.author,
            "durationSeconds": self.duration_seconds,
            "videoCount": self.video_count,
            "classification": self.classification,
            "coverUrl": self.cover_url,
            "providerRequestId": self.provider_request_id,
            "creditsUsed": self.credits_used,
            "creditsRemaining": self.credits_remaining,
            "locatorAvailable": True,
        }


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
        raw = None
        for key in ("items", "tracks", "audios"):
            if key in data:
                raw = data.get(key)
                break
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
        self.last_metadata: dict[str, Any] = {}

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        key = _required_env(self.credential_env)
        response = self.session.get(
            self.endpoint,
            headers={"x-api-key": key, "Accept": "application/json"},
            timeout=30,
        )
        if response.status_code != 200:
            self.last_metadata = _provider_failure_metadata(response)
            raise ProviderError(
                f"socialcrawl trending request failed: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("success") is False:
            raise ProviderError("socialcrawl trending response was unsuccessful")
        self.last_metadata = _provider_metadata(payload, response.headers)
        candidates = self.parse(payload, region=region, limit=limit)
        raw_items = _items(payload)
        if raw_items and not candidates:
            raise ProviderError(
                "socialcrawl Instagram response contained no usable music IDs"
            )
        self.last_metadata.update(
            {
                "status": "available",
                "requests": 1,
                "observationValid": True,
                "rawItemCount": len(raw_items),
            }
        )
        return candidates

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
        provider_metadata = _provider_metadata(payload)
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
                    advisory_labels={
                        "coverUrl": _optional_string(
                            item.get("cover_url")
                            or item.get("coverUrl")
                            or item.get("cover")
                        ),
                        "durationSeconds": _number(
                            item.get("duration") or item.get("duration_seconds")
                        ),
                        "providerRequestId": provider_metadata.get("requestId"),
                        "creditsUsed": provider_metadata.get("creditsUsed"),
                        "creditsRemaining": provider_metadata.get("creditsRemaining"),
                        "retrievedAt": observed_at,
                    },
                )
            )
        return candidates


class SocialCrawlTikTokProvider:
    """Aggregate SocialCrawl's real trending-video feed by TikTok music ID."""

    provider_name = "socialcrawl_tiktok"
    credential_env = "SOCIALCRAWL_API_KEY"
    endpoint = "https://www.socialcrawl.dev/v1/tiktok/trending"

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.last_metadata: dict[str, Any] = {}

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        key = _required_env(self.credential_env)
        selected_region = region or "US"
        response = self.session.get(
            self.endpoint,
            headers={"x-api-key": key, "Accept": "application/json"},
            params={"region": selected_region},
            timeout=30,
        )
        if response.status_code != 200:
            self.last_metadata = _provider_failure_metadata(response)
            raise ProviderError(
                "socialcrawl TikTok trending request failed: "
                f"HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("success") is not True:
            raise ProviderError("socialcrawl TikTok trending response was unsuccessful")
        platform = _string(payload.get("platform")).lower()
        endpoint = _string(payload.get("endpoint"))
        if platform and platform != "tiktok":
            raise ProviderError("socialcrawl TikTok response named another platform")
        if endpoint and not endpoint.endswith("/v1/tiktok/trending"):
            raise ProviderError("socialcrawl TikTok response named another endpoint")
        raw_items = _items(payload)
        candidates = self.parse(payload, region=selected_region, limit=limit)
        if raw_items and not candidates:
            raise ProviderError(
                "socialcrawl TikTok response contained no usable music IDs"
            )
        self.last_metadata = {
            **_provider_metadata(payload, response.headers),
            "status": "available",
            "requests": 1,
            "observationValid": True,
            "rawVideoCount": len(raw_items),
            "aggregatedMusicIdCount": len(candidates),
        }
        return candidates

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any],
        *,
        region: str | None,
        limit: int,
    ) -> list[TrendCandidate]:
        """Parse the credentialed unified-envelope schema without inferred ranks."""

        observed_at = _string(payload.get("observed_at")) or _utc_now()
        observed_time = _parse_datetime(observed_at)
        fingerprint = _payload_fingerprint(payload)
        provider_metadata = _provider_metadata(payload)
        groups: dict[str, dict[str, Any]] = {}

        for item in _items(payload)[: max(1, limit)]:
            post: Mapping[str, Any] = _first_mapping(item.get("post"), item)
            content: Mapping[str, Any] = _first_mapping(post.get("content"))
            author: Mapping[str, Any] = _first_mapping(post.get("author"))
            engagement: Mapping[str, Any] = _first_mapping(post.get("engagement"))
            extension: Mapping[str, Any] = _first_mapping(post.get("ext"))
            music = _first_mapping(
                post.get("music"),
                extension.get("music"),
                item.get("music"),
            )
            music_id = _string(
                extension.get("music_id")
                or extension.get("musicId")
                or music.get("id")
                or music.get("music_id")
                or music.get("musicId")
            )
            if not music_id:
                continue

            published_at = _timestamp_string(
                post.get("published_at")
                or post.get("publishedAt")
                or extension.get("published_at")
                or extension.get("publishedAt"),
                extension.get("published_at_epoch")
                or extension.get("publishedAtEpoch"),
            )
            music_title = _optional_string(
                music.get("title")
                or music.get("name")
                or extension.get("music_title")
                or extension.get("musicTitle")
                or extension.get("music_name")
            )
            music_author = _optional_string(
                music.get("author")
                or music.get("artist")
                or music.get("author_name")
                or extension.get("music_author")
                or extension.get("musicAuthor")
                or extension.get("music_author_name")
            )
            item_region = _optional_string(
                item.get("region")
                or post.get("region")
                or extension.get("region")
                or region
            )
            counts: dict[str, int | None] = {
                "views": _integer(engagement.get("views")),
                "likes": _integer(engagement.get("likes")),
                "comments": _integer(engagement.get("comments")),
                "shares": _integer(engagement.get("shares")),
            }
            interaction_values: list[int] = []
            for key in ("likes", "comments", "shares"):
                value = counts[key]
                if value is not None:
                    interaction_values.append(value)
            interactions = sum(interaction_values) if interaction_values else None
            video = _without_none(
                {
                    "videoId": _optional_string(post.get("id")),
                    "creationTime": published_at,
                    **counts,
                    "engagement": interactions,
                    "author": _optional_string(
                        author.get("username")
                        or author.get("display_name")
                        or author.get("displayName")
                    ),
                    "caption": _optional_string(
                        content.get("text") or post.get("caption")
                    ),
                    "musicId": music_id,
                    "musicTitle": music_title,
                    "musicAuthor": music_author,
                    "region": item_region,
                    "providerObservationTime": observed_at,
                }
            )
            group = groups.setdefault(
                music_id,
                {
                    "videos": [],
                    "titles": [],
                    "authors": [],
                    "regions": [],
                },
            )
            group["videos"].append(video)
            if music_title and music_title not in group["titles"]:
                group["titles"].append(music_title)
            if music_author and music_author not in group["authors"]:
                group["authors"].append(music_author)
            if item_region and item_region not in group["regions"]:
                group["regions"].append(item_region)

        candidates: list[TrendCandidate] = []
        for music_id, group in groups.items():
            videos = group["videos"]
            engagement_values = [
                int(video["engagement"])
                for video in videos
                if isinstance(video.get("engagement"), int)
            ]
            creation_times = [
                parsed_creation
                for video in videos
                if (
                    parsed_creation := _parse_datetime(
                        str(video.get("creationTime") or "")
                    )
                )
                is not None
            ]
            total_views = _sum_video_metric(videos, "views")
            total_likes = _sum_video_metric(videos, "likes")
            total_comments = _sum_video_metric(videos, "comments")
            total_shares = _sum_video_metric(videos, "shares")
            newest = max(creation_times) if creation_times else None
            freshness_hours = (
                max(0.0, (observed_time - newest).total_seconds() / 3600)
                if observed_time is not None and newest is not None
                else None
            )
            velocity_values: list[float] = []
            if observed_time is not None:
                for video in videos:
                    created = _parse_datetime(str(video.get("creationTime") or ""))
                    engagement_value = video.get("engagement")
                    if created is None or not isinstance(engagement_value, int):
                        continue
                    age_hours = max(
                        1.0,
                        (observed_time - created).total_seconds() / 3600,
                    )
                    velocity_values.append(engagement_value / age_hours)
            engagement_velocity = sum(velocity_values) if velocity_values else None
            labels = _without_none(
                {
                    "sourcePriority": 1,
                    "sampleAppearanceCount": len(videos),
                    "totalEngagement": (
                        sum(engagement_values) if engagement_values else None
                    ),
                    "medianEngagement": (
                        float(median(engagement_values)) if engagement_values else None
                    ),
                    "engagementDefinition": "likes+comments+shares",
                    "totalViews": total_views,
                    "totalLikes": total_likes,
                    "totalComments": total_comments,
                    "totalShares": total_shares,
                    "newestCreationTime": (
                        newest.isoformat().replace("+00:00", "Z") if newest else None
                    ),
                    "engagementVelocityPerHour": engagement_velocity,
                    "velocityDefinition": (
                        "sum((likes+comments+shares)/age_hours)"
                        if engagement_velocity is not None
                        else None
                    ),
                    "musicTitles": group["titles"] or None,
                    "musicAuthors": group["authors"] or None,
                    "regions": group["regions"] or None,
                    "providerObservationTime": observed_at,
                    "providerRequestId": provider_metadata.get("requestId"),
                    "creditsUsed": provider_metadata.get("creditsUsed"),
                    "creditsRemaining": provider_metadata.get("creditsRemaining"),
                    "videos": videos,
                }
            )
            candidates.append(
                TrendCandidate(
                    candidate_id=f"{cls.provider_name}:tiktok:{music_id}",
                    provider=cls.provider_name,
                    title=group["titles"][0] if group["titles"] else "",
                    artist=group["authors"][0] if group["authors"] else "",
                    platform_sound_ids=(
                        PlatformSoundId(
                            platform="tiktok",
                            sound_id=music_id,
                            region=region,
                        ),
                    ),
                    observed_at=observed_at,
                    region=region,
                    current_rank=None,
                    previous_rank=None,
                    usage_total=None,
                    usage_velocity=engagement_velocity,
                    freshness_hours=freshness_hours,
                    trend_score=None,
                    saturation=None,
                    provider_payload_fingerprint=fingerprint,
                    advisory_labels=labels,
                )
            )
        return candidates


class TikTokCreativeCenterProvider:
    """Narrow public-page adapter for Creative Center song trend views."""

    provider_name = "tiktok_creative_center"
    endpoint = (
        "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en"
    )
    _chart_views = (("popular", 7), ("popular", 30), ("breakout", 7), ("breakout", 30))

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        max_requests: int = 4,
    ) -> None:
        self.session = session or requests.Session()
        self.max_requests = max(1, min(int(max_requests), len(self._chart_views)))
        self.last_metadata: dict[str, Any] = {
            "status": "unavailable",
            "requests": 0,
            "views": [],
        }

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        candidates: list[TrendCandidate] = []
        view_receipts: list[dict[str, Any]] = []
        for chart_type, period_days in self._chart_views[: self.max_requests]:
            params = {
                "countryCode": region or "US",
                "period": str(period_days),
                "chartType": chart_type,
            }
            try:
                response = self.session.get(
                    self.endpoint,
                    params=params,
                    headers={
                        "Accept": "text/html,application/json",
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                        ),
                    },
                    timeout=30,
                )
                if response.status_code != 200:
                    raise ProviderError(
                        "creative center public page failed: "
                        f"HTTP {response.status_code}"
                    )
                parsed = self.parse_page(
                    response.text,
                    region=region or "US",
                    chart_type=chart_type,
                    period_days=period_days,
                    limit=limit,
                )
                candidates.extend(parsed)
                view_receipts.append(
                    {
                        "chartType": chart_type,
                        "periodDays": period_days,
                        "status": "available" if parsed else "unavailable",
                        "candidateCount": len(parsed),
                    }
                )
            except (ProviderError, requests.RequestException, ValueError):
                view_receipts.append(
                    {
                        "chartType": chart_type,
                        "periodDays": period_days,
                        "status": "unavailable",
                        "candidateCount": 0,
                    }
                )
        self.last_metadata = {
            "status": "available" if candidates else "unavailable",
            "requests": len(view_receipts),
            "observationValid": bool(candidates),
            "views": view_receipts,
        }
        return candidates[: max(1, limit)]

    @classmethod
    def parse_page(
        cls,
        page: str,
        *,
        region: str,
        chart_type: str,
        period_days: int,
        limit: int,
    ) -> list[TrendCandidate]:
        """Parse only JSON state embedded in the public song-trends page."""

        payloads = _embedded_json_payloads(page)
        observed_at = _utc_now()
        candidates: list[TrendCandidate] = []
        seen: set[tuple[str, str, int]] = set()
        for payload in payloads:
            for item in _creative_center_items(payload):
                sound_id = _string(
                    item.get("music_id")
                    or item.get("musicId")
                    or item.get("sound_id")
                    or item.get("soundId")
                    or item.get("clipId")
                    or item.get("id")
                )
                title = _string(
                    item.get("title")
                    or item.get("musicName")
                    or item.get("song_name")
                    or item.get("songName")
                )
                if not sound_id or not title:
                    continue
                item_chart = (
                    _string(item.get("chart_type") or item.get("chartType"))
                    or chart_type
                ).lower()
                item_period = (
                    _integer(
                        item.get("period")
                        or item.get("period_days")
                        or item.get("periodDays")
                    )
                    or period_days
                )
                dedupe_key = (sound_id, item_chart, item_period)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                rank = _integer(
                    item.get("rank")
                    or item.get("chart_position")
                    or item.get("chartPosition")
                )
                previous_rank = _integer(
                    item.get("previous_rank")
                    or item.get("previousRank")
                    or item.get("last_rank")
                    or item.get("lastRank")
                )
                rank_movement = _number(
                    item.get("rank_movement") or item.get("rankMovement")
                )
                detail_url = _string(
                    item.get("detail_url") or item.get("detailUrl") or item.get("url")
                )
                if detail_url.startswith("/"):
                    detail_url = f"https://ads.tiktok.com{detail_url}"
                if not detail_url:
                    detail_url = (
                        "https://ads.tiktok.com/business/creativecenter/song/"
                        f"{sound_id}/pc/en?countryCode={region}&period={item_period}"
                    )
                is_new = bool(
                    item.get("new_to_top_100")
                    or item.get("newToTop100")
                    or item_chart in {"new", "new_to_top_100"}
                )
                candidates.append(
                    TrendCandidate(
                        candidate_id=(
                            f"{cls.provider_name}:tiktok:{sound_id}:"
                            f"{item_chart}:{item_period}"
                        ),
                        provider=cls.provider_name,
                        title=title,
                        artist=_string(
                            item.get("artist")
                            or item.get("author")
                            or item.get("artistName")
                        ),
                        platform_sound_ids=(
                            PlatformSoundId(
                                platform="tiktok",
                                sound_id=sound_id,
                                region=region,
                                url=detail_url,
                            ),
                        ),
                        observed_at=_string(
                            item.get("observed_at") or item.get("observedAt")
                        )
                        or observed_at,
                        region=region,
                        current_rank=rank,
                        previous_rank=previous_rank,
                        usage_total=_integer(
                            item.get("video_count")
                            or item.get("videoCount")
                            or item.get("usage_count")
                        ),
                        usage_velocity=_number(
                            item.get("usage_velocity") or item.get("usageVelocity")
                        ),
                        freshness_hours=_number(item.get("freshness_hours")),
                        provider_payload_fingerprint=_payload_fingerprint(item),
                        advisory_labels={
                            "chartType": item_chart,
                            "rankMovement": rank_movement,
                            "newToTop100": is_new,
                            "observationPeriodDays": item_period,
                            "detailUrl": detail_url,
                        },
                    )
                )
                if len(candidates) >= max(1, limit):
                    return candidates
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
        self.last_metadata: dict[str, Any] = {}

    def resolve(self, music_id: str) -> AudioLocator:
        return self.resolve_details(music_id).locator

    def resolve_details(self, music_id: str) -> TikLiveAudioDetails:
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
        details = self.parse_details(
            payload,
            music_id=music_id,
            response_headers=response.headers,
        )
        self.last_metadata = {
            "requestId": details.provider_request_id,
            "creditsUsed": details.credits_used,
            "creditsRemaining": details.credits_remaining,
        }
        return details

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, Any],
        *,
        music_id: str,
    ) -> AudioLocator:
        return cls.parse_details(payload, music_id=music_id).locator

    @classmethod
    def parse_details(
        cls,
        payload: Mapping[str, Any],
        *,
        music_id: str,
        response_headers: Mapping[str, Any] | None = None,
    ) -> TikLiveAudioDetails:
        play_url = _string(payload.get("play") or payload.get("playUrl"))
        returned_id = _string(payload.get("id") or music_id)
        if returned_id != music_id or not play_url:
            raise ProviderError("tiklive music-info response did not match music ID")
        metadata = _provider_metadata(payload, response_headers)
        is_original = payload.get("is_original")
        if is_original is None:
            is_original = payload.get("isOriginal")
        classification = _optional_string(
            payload.get("classification")
            or payload.get("music_type")
            or payload.get("musicType")
        )
        if classification is None and is_original is not None:
            classification = "original" if bool(is_original) else "catalog"
        return TikLiveAudioDetails(
            locator=AudioLocator(
                provider=cls.provider_name,
                platform="tiktok",
                track_id=music_id,
                kind="playable_url",
                value=play_url,
                allowed_hosts=_host_suffixes(play_url),
            ),
            title=_optional_string(payload.get("title")),
            author=_optional_string(payload.get("author") or payload.get("artist")),
            duration_seconds=_number(
                payload.get("duration") or payload.get("duration_seconds")
            ),
            video_count=_integer(
                payload.get("video_count")
                or payload.get("videoCount")
                or payload.get("user_count")
            ),
            classification=classification,
            cover_url=_optional_string(
                payload.get("cover")
                or payload.get("cover_url")
                or payload.get("coverUrl")
            ),
            provider_request_id=metadata.get("requestId"),
            credits_used=metadata.get("creditsUsed"),
            credits_remaining=metadata.get("creditsRemaining"),
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


def _optional_string(value: object) -> str | None:
    clean = _string(value)
    return clean or None


def _first_mapping(*values: object) -> Mapping[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return value
    return {}


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _parse_datetime(value: str) -> datetime | None:
    clean = value.strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _timestamp_string(value: object, epoch: object) -> str | None:
    direct = _optional_string(value)
    if direct:
        parsed = _parse_datetime(direct)
        return (
            parsed.isoformat().replace("+00:00", "Z") if parsed is not None else direct
        )
    seconds = _number(epoch)
    if seconds is None:
        return None
    try:
        return (
            datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _sum_video_metric(videos: Sequence[Mapping[str, Any]], key: str) -> int | None:
    values = [int(video[key]) for video in videos if isinstance(video.get(key), int)]
    return sum(values) if values else None


def _provider_metadata(
    payload: Mapping[str, Any],
    headers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    headers = headers or {}
    meta: Mapping[str, Any] = _first_mapping(payload.get("meta"))
    credits: Mapping[str, Any] = _first_mapping(payload.get("credits"))
    request_id = _optional_string(
        payload.get("request_id")
        or payload.get("requestId")
        or meta.get("request_id")
        or meta.get("requestId")
        or headers.get("x-request-id")
        or headers.get("request-id")
    )
    used = _number(
        _first_defined(
            payload.get("credits_used"),
            payload.get("creditsUsed"),
            meta.get("credits_used"),
            credits.get("used"),
            headers.get("x-credits-used"),
        )
    )
    remaining = _number(
        _first_defined(
            payload.get("credits_remaining"),
            payload.get("creditsRemaining"),
            meta.get("credits_remaining"),
            credits.get("remaining"),
            headers.get("x-credits-remaining"),
        )
    )
    return {
        "requestId": request_id,
        "creditsUsed": used,
        "creditsRemaining": remaining,
    }


def _provider_failure_metadata(response: Any) -> dict[str, Any]:
    try:
        decoded = response.json()
    except (TypeError, ValueError):
        decoded = {}
    payload = decoded if isinstance(decoded, Mapping) else {}
    error = _first_mapping(payload.get("error"))
    error_message = _string(error.get("message") or payload.get("message"))
    return _without_none(
        {
            **_provider_metadata(payload, getattr(response, "headers", {})),
            "status": "unavailable",
            "requests": 1,
            "httpStatus": _integer(getattr(response, "status_code", None)),
            "providerErrorType": _optional_string(error.get("type")),
            "providerErrorStatus": _integer(error.get("status")),
            "creditsRefunded": (
                "refund" in error_message.lower() if error_message else None
            ),
        }
    )


def _first_defined(*values: object) -> object | None:
    return next((value for value in values if value is not None), None)


_SCRIPT_JSON_RE = re.compile(
    r"<script[^>]*type=[\"']application/(?:ld\\+)?json[\"'][^>]*>(.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
_STATE_ASSIGNMENT_RE = re.compile(
    r"(?:window\\.)?__(?:NEXT_DATA|INITIAL_STATE|SSR_DATA|SIGI_STATE)__?\\s*=\\s*"
    r"(\{.*?\})\\s*;?\\s*</script>",
    flags=re.IGNORECASE | re.DOTALL,
)


def _embedded_json_payloads(page: str) -> list[Mapping[str, Any]]:
    stripped = page.strip()
    raw_values: list[str] = []
    if stripped.startswith(("{", "[")):
        raw_values.append(stripped)
    raw_values.extend(
        html.unescape(value).strip() for value in _SCRIPT_JSON_RE.findall(page)
    )
    raw_values.extend(
        html.unescape(value).strip() for value in _STATE_ASSIGNMENT_RE.findall(page)
    )
    payloads: list[Mapping[str, Any]] = []
    for raw in raw_values:
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(decoded, Mapping):
            payloads.append(decoded)
    if not payloads:
        raise ProviderError("creative center page contained no parseable public state")
    return payloads


_CREATIVE_ITEM_KEYS = {
    "music_list",
    "musicList",
    "songs",
    "items",
    "trendingSongs",
    "popularSongs",
    "breakoutSongs",
}


def _creative_center_items(value: object) -> list[Mapping[str, Any]]:
    results: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if (
                key in _CREATIVE_ITEM_KEYS
                and isinstance(nested, Sequence)
                and not isinstance(nested, (str, bytes))
            ):
                results.extend(item for item in nested if isinstance(item, Mapping))
            elif isinstance(nested, (Mapping, list, tuple)):
                results.extend(_creative_center_items(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            if isinstance(nested, (Mapping, list, tuple)):
                results.extend(_creative_center_items(nested))
    return results
