from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.audio_radar.acquisition import AudioCache
from campaign_factory.audio_radar.models import (
    AudioLocator,
    PlatformSoundId,
    TrendCandidate,
)
from campaign_factory.audio_radar.normalization import normalize_candidates
from campaign_factory.audio_radar.providers import (
    ProviderError,
    SocialCrawlInstagramProvider,
    SocialCrawlTikTokProvider,
    TikLiveAudioDetails,
    TikLiveAudioResolver,
    TikTokCreativeCenterProvider,
)
from campaign_factory.audio_radar.refresh import (
    LifecycleThresholds,
    RefreshPaths,
    _prune_cache,
    refresh_audio_library,
)
from campaign_factory.db import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "audio_radar"


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        text: str = "",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload or {}
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self.payload


class RecordingSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


class StaticProvider:
    def __init__(
        self,
        candidates: list[TrendCandidate],
        *,
        status: str = "available",
        observation_valid: bool = False,
    ) -> None:
        self.candidates = candidates
        self.last_metadata = {
            "status": status,
            "requests": 1,
            "observationValid": observation_valid,
        }
        self.calls = 0

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        self.calls += 1
        return self.candidates[:limit]


class FailingProvider:
    last_metadata = {"requests": 1}

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        raise ProviderError("fixture provider outage")


class StaticTikLive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[str] = []

    def resolve_details(self, music_id: str) -> TikLiveAudioDetails:
        self.calls.append(music_id)
        return TikLiveAudioDetails(
            locator=AudioLocator(
                provider="tikliveapi",
                platform="tiktok",
                track_id=music_id,
                kind="local_file",
                value=str(self.path),
            ),
            title="Midnight Glow (Sped Up)",
            author="Example Artist feat. Guest",
            duration_seconds=31,
            video_count=91_000,
            classification="catalog",
            cover_url="https://cdn.example.test/cover.jpg",
            provider_request_id="req_fixture",
            credits_used=1,
            credits_remaining=99,
        )


def _json_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _paths(tmp_path: Path) -> RefreshPaths:
    return RefreshPaths(
        database=tmp_path / "campaign.sqlite",
        cache=tmp_path / "cache",
        receipts=tmp_path / "receipts",
        lock=tmp_path / "state" / "audio.lock",
    )


def _candidate(
    *,
    provider: str,
    platform: str,
    sound_id: str,
    locator: AudioLocator | None = None,
) -> TrendCandidate:
    return TrendCandidate(
        candidate_id=f"{provider}:{platform}:{sound_id}",
        provider=provider,
        title="Midnight Glow (Sped Up)",
        artist="Example Artist feat. Guest",
        platform_sound_ids=(
            PlatformSoundId(
                platform=platform,
                sound_id=sound_id,
                region="US",
                url=f"https://example.test/{sound_id}",
            ),
        ),
        observed_at="2026-06-01T12:00:00Z",
        region="US",
        current_rank=4,
        previous_rank=15,
        usage_total=72_000,
        usage_velocity=4_200,
        freshness_hours=24,
        locator=locator,
        advisory_labels={
            "chartType": "breakout" if platform == "tiktok" else "popular",
            "rankMovement": 11,
        },
    )


def test_socialcrawl_authentication_and_metadata_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture-social-key"
    monkeypatch.setenv("SOCIALCRAWL_API_KEY", secret)
    session = RecordingSession(
        FakeResponse(
            _json_fixture("socialcrawl_trending.redacted.json"),
            headers={"x-request-id": "header-request"},
        )
    )
    provider = SocialCrawlInstagramProvider(session=session)

    candidates = provider.discover(region="US", limit=10)

    assert session.calls[0]["headers"]["x-api-key"] == secret
    assert candidates[0].advisory_labels["coverUrl"].endswith(".jpg")
    assert candidates[0].advisory_labels["durationSeconds"] == 31
    assert candidates[0].advisory_labels["providerRequestId"] == (
        "req_redacted_example"
    )
    assert provider.last_metadata["creditsUsed"] == 1


def test_socialcrawl_upstream_error_preserves_safe_billing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOCIALCRAWL_API_KEY", "fixture-social-key")
    provider = SocialCrawlInstagramProvider(
        session=RecordingSession(
            FakeResponse(
                {
                    "success": False,
                    "error": {
                        "type": "UPSTREAM_ERROR",
                        "message": (
                            "The upstream data provider returned an error. "
                            "Your credits have been refunded."
                        ),
                        "status": 502,
                    },
                    "credits_used": 0,
                    "credits_remaining": 95,
                    "request_id": "req_refunded_fixture",
                },
                status_code=502,
            )
        )
    )

    with pytest.raises(ProviderError, match="HTTP 502"):
        provider.discover(region="US", limit=10)

    assert provider.last_metadata == {
        "requestId": "req_refunded_fixture",
        "creditsUsed": 0.0,
        "creditsRemaining": 95.0,
        "status": "unavailable",
        "requests": 1,
        "httpStatus": 502,
        "providerErrorType": "UPSTREAM_ERROR",
        "providerErrorStatus": 502,
        "creditsRefunded": True,
    }


def test_socialcrawl_tiktok_uses_real_schema_and_aggregates_music_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture-social-key"
    monkeypatch.setenv("SOCIALCRAWL_API_KEY", secret)
    session = RecordingSession(
        FakeResponse(_json_fixture("socialcrawl_tiktok_trending.redacted.json"))
    )
    provider = SocialCrawlTikTokProvider(session=session)

    candidates = provider.discover(region="US", limit=100)

    assert session.calls == [
        {
            "url": "https://www.socialcrawl.dev/v1/tiktok/trending",
            "headers": {"x-api-key": secret, "Accept": "application/json"},
            "params": {"region": "US"},
            "timeout": 30,
        }
    ]
    assert provider.last_metadata["rawVideoCount"] == 3
    assert provider.last_metadata["aggregatedMusicIdCount"] == 2
    assert provider.last_metadata["observationValid"] is True
    aggregated = next(
        candidate
        for candidate in candidates
        if candidate.platform_sound_ids[0].sound_id == "tt_music_501"
    )
    assert aggregated.current_rank is None
    assert aggregated.previous_rank is None
    assert aggregated.advisory_labels["sampleAppearanceCount"] == 2
    assert aggregated.advisory_labels["totalEngagement"] == 3000
    assert aggregated.advisory_labels["medianEngagement"] == 1500
    assert aggregated.advisory_labels["totalViews"] == 30000
    assert aggregated.advisory_labels["engagementVelocityPerHour"] == pytest.approx(
        83.33333333333334
    )
    assert aggregated.advisory_labels["videos"][0] == {
        "videoId": "video_101",
        "creationTime": "2026-07-23T12:00:00Z",
        "views": 10000,
        "likes": 800,
        "comments": 100,
        "shares": 100,
        "engagement": 1000,
        "author": "creator_one",
        "caption": "first real schema example",
        "musicId": "tt_music_501",
        "musicTitle": "Midnight Glow (Sped Up)",
        "musicAuthor": "Example Artist",
        "region": "US",
        "providerObservationTime": "2026-07-24T12:00:00Z",
    }
    opaque = next(candidate for candidate in candidates if not candidate.title)
    normalized = normalize_candidates([opaque])[0]
    assert normalized.canonical_track_id
    assert normalized.canonical_title == ""
    assert normalized.advisory_labels["crossPlatformMatch"] is False
    chart_metadata = replace(
        opaque,
        candidate_id="tiktok_creative_center:tiktok:tt_music_opaque",
        provider="tiktok_creative_center",
        title="Resolved Chart Title",
        artist="Resolved Chart Artist",
    )
    merged = normalize_candidates([opaque, chart_metadata])
    assert len(merged) == 1
    assert merged[0].canonical_title == "resolved chart title"
    assert any(
        observation.get("metadataEnrichedFromSharedSoundId") is True
        for observation in merged[0].advisory_labels["observations"]
    )


def test_socialcrawl_tiktok_rejects_nonempty_feed_without_music_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOCIALCRAWL_API_KEY", "fixture-social-key")
    provider = SocialCrawlTikTokProvider(
        session=RecordingSession(
            FakeResponse(
                {
                    "success": True,
                    "platform": "tiktok",
                    "endpoint": "/v1/tiktok/trending",
                    "data": {"items": [{"post": {"id": "video-no-music"}}]},
                }
            )
        )
    )

    with pytest.raises(ProviderError, match="no usable music IDs"):
        provider.discover(region="US", limit=100)


def test_tiklive_authentication_and_full_metadata_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture-tiklive-key"
    monkeypatch.setenv("TIKLIVE_API_KEY", secret)
    session = RecordingSession(
        FakeResponse(
            _json_fixture("tiklive_music_info.redacted.json"),
            headers={"x-request-id": "tiklive-request"},
        )
    )
    resolver = TikLiveAudioResolver(session=session)

    details = resolver.resolve_details("tt_sound_202")

    assert session.calls[0]["headers"]["X-Api-Key"] == secret
    assert session.calls[0]["params"] == {"music_id": "tt_sound_202"}
    assert details.locator.allowed_hosts == ("cdn.example.test",)
    assert details.video_count == 91_000
    assert details.classification == "catalog"
    assert details.cover_url is not None
    assert details.provider_request_id == "tiklive-request"


def test_creative_center_public_page_parsing_and_request_cap() -> None:
    page = (FIXTURES / "creative_center_music.redacted.html").read_text(
        encoding="utf-8"
    )
    parsed = TikTokCreativeCenterProvider.parse_page(
        page,
        region="US",
        chart_type="popular",
        period_days=7,
        limit=100,
    )
    session = RecordingSession(FakeResponse(text=page))
    provider = TikTokCreativeCenterProvider(session=session, max_requests=2)

    discovered = provider.discover(region="US", limit=100)

    assert len(parsed) == 2
    assert parsed[0].platform_sound_ids[0].sound_id == "tt_sound_202"
    assert parsed[0].advisory_labels["chartType"] == "breakout"
    assert parsed[0].advisory_labels["newToTop100"] is True
    assert parsed[0].advisory_labels["observationPeriodDays"] == 7
    assert len(session.calls) == 2
    assert provider.last_metadata["requests"] == 2
    assert discovered


def test_creative_center_unavailability_is_nonfatal() -> None:
    session = RecordingSession(FakeResponse(status_code=403))
    provider = TikTokCreativeCenterProvider(session=session, max_requests=2)

    assert provider.discover(region="US", limit=100) == []
    assert provider.last_metadata["status"] == "unavailable"
    assert provider.last_metadata["requests"] == 2


def test_cross_platform_dedupe_preserves_ids_but_versions_remain_distinct() -> None:
    instagram = _candidate(
        provider="socialcrawl",
        platform="instagram",
        sound_id="ig_audio_101",
    )
    tiktok = _candidate(
        provider="tiktok_creative_center",
        platform="tiktok",
        sound_id="tt_sound_202",
    )
    slowed = replace(
        tiktok,
        candidate_id="tiktok:slowed",
        title="Midnight Glow (Slowed + Reverb)",
        platform_sound_ids=(PlatformSoundId("tiktok", "tt_sound_slow", "US"),),
    )

    normalized = normalize_candidates([instagram, tiktok, slowed])

    assert len(normalized) == 2
    sped = next(value for value in normalized if value.variant == "sped up")
    assert {(value.platform, value.sound_id) for value in sped.platform_sound_ids} == {
        ("instagram", "ig_audio_101"),
        ("tiktok", "tt_sound_202"),
    }
    assert next(
        value for value in normalized if value.variant != "sped up"
    ).variant == ("slowed reverb")


def test_refresh_is_idempotent_then_cools_stales_and_prunes_only_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tiklive-audio.mp3"
    source.write_bytes(b"fixture audio bytes")
    monkeypatch.setattr(
        "campaign_factory.audio_radar.acquisition.probe_media",
        lambda _path: {
            "format": {"duration": "31.0"},
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": 2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "campaign_factory.audio_radar.refresh.decoded_audio_fingerprint",
        lambda _path: "f" * 64,
    )
    social = StaticProvider(
        [
            _candidate(
                provider="socialcrawl",
                platform="instagram",
                sound_id="ig_audio_101",
            )
        ]
    )
    tiktok_social = StaticProvider(
        [
            _candidate(
                provider="socialcrawl_tiktok",
                platform="tiktok",
                sound_id="tt_sound_202",
            )
        ]
    )
    creative = StaticProvider([])
    resolver = StaticTikLive(source)
    paths = _paths(tmp_path)
    config = LifecycleThresholds(retention_days=1)

    first = refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=config,
        social_provider=social,
        tiktok_social_provider=tiktok_social,
        creative_provider=creative,
        tiklive_resolver=resolver,
        now="2026-06-01T12:00:00Z",
    )
    repeated = refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=config,
        social_provider=social,
        tiktok_social_provider=tiktok_social,
        creative_provider=creative,
        tiklive_resolver=resolver,
        now="2026-06-01T12:00:00Z",
    )

    assert first["counts"]["audioFilesDownloaded"] == 1
    assert first["counts"]["activeLibrarySize"] == 1
    assert first["sourceStatus"]["tiklive"]["requests"] == 1
    assert first["sampleVerification"][0]["playableLocalCacheObject"] is True
    assert repeated["counts"]["audioFilesDownloaded"] == 0
    with connect(paths.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audio_catalog").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM audio_cache_objects").fetchone()[0] == 1
        )
        cache_path = Path(
            conn.execute("SELECT cache_path FROM audio_cache_objects").fetchone()[0]
        )
    assert cache_path.is_file()

    empty = StaticProvider([], observation_valid=True)
    unavailable_creative = StaticProvider([])
    cooling = refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=config,
        social_provider=empty,
        tiktok_social_provider=empty,
        creative_provider=unavailable_creative,
        tiklive_resolver=resolver,
        now="2026-06-08T12:00:00Z",
    )
    stale = refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=config,
        social_provider=empty,
        tiktok_social_provider=empty,
        creative_provider=unavailable_creative,
        tiklive_resolver=resolver,
        now="2026-06-15T12:00:00Z",
    )

    assert cooling["counts"]["tracksMarkedCooling"] == 1
    assert cooling["counts"]["cachedFilesPruned"] == 0
    assert stale["counts"]["tracksMarkedStale"] == 1
    assert stale["counts"]["cachedFilesPruned"] == 1
    assert cache_path.exists() is False
    with connect(paths.database) as conn:
        row = conn.execute(
            "SELECT lifecycle_state, active FROM audio_catalog"
        ).fetchone()
        assert tuple(row) == ("STALE", 0)
        assert conn.execute("SELECT COUNT(*) FROM audio_catalog").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM audio_trend_snapshots").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM audio_cache_prune_receipts").fetchone()[
                0
            ]
            == 1
        )


def test_all_source_invalid_empty_outage_preserves_lifecycle_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tiklive-audio.mp3"
    source.write_bytes(b"fixture audio bytes")
    monkeypatch.setattr(
        "campaign_factory.audio_radar.acquisition.probe_media",
        lambda _path: {
            "format": {"duration": "31.0"},
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": 2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "campaign_factory.audio_radar.refresh.decoded_audio_fingerprint",
        lambda _path: "f" * 64,
    )
    paths = _paths(tmp_path)
    social = StaticProvider(
        [
            _candidate(
                provider="socialcrawl",
                platform="instagram",
                sound_id="ig_audio_101",
            )
        ]
    )
    tiktok = StaticProvider(
        [
            _candidate(
                provider="socialcrawl_tiktok",
                platform="tiktok",
                sound_id="tt_sound_202",
            )
        ]
    )
    refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=LifecycleThresholds(retention_days=1),
        social_provider=social,
        tiktok_social_provider=tiktok,
        creative_provider=StaticProvider([]),
        tiklive_resolver=StaticTikLive(source),
        now="2026-06-01T12:00:00Z",
    )
    with connect(paths.database) as conn:
        conn.execute(
            """
            UPDATE audio_catalog
            SET lifecycle_state = 'HOT', trend_status = 'HOT',
                active = 1, consecutive_absences = 2
            """
        )
        conn.execute(
            "UPDATE audio_cache_objects SET retrieved_at = '2026-05-01T12:00:00Z'"
        )
        conn.commit()
        before = tuple(
            conn.execute(
                """
                SELECT lifecycle_state, trend_status, active,
                       consecutive_absences, updated_at
                FROM audio_catalog
                """
            ).fetchone()
        )
        cache_path = Path(
            conn.execute("SELECT cache_path FROM audio_cache_objects").fetchone()[0]
        )

    invalid_empty = StaticProvider([])
    outage = refresh_audio_library(
        region="US",
        max_new=10,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=LifecycleThresholds(retention_days=1),
        social_provider=FailingProvider(),
        tiktok_social_provider=invalid_empty,
        creative_provider=invalid_empty,
        tiklive_resolver=StaticTikLive(source),
        now="2026-06-15T12:00:00Z",
    )

    assert outage["status"] == "unavailable"
    assert all(
        outage["sourceStatus"][source_name]["status"] == "unavailable"
        for source_name in (
            "socialcrawlInstagram",
            "socialcrawlTikTok",
            "tiktokCreativeCenter",
        )
    )
    assert outage["sourceStatus"]["socialcrawlInstagram"]["reason"] == (
        "provider_or_public_page_unavailable"
    )
    assert outage["sourceStatus"]["socialcrawlTikTok"]["reason"] == (
        "invalid_empty_response"
    )
    assert outage["sourceStatus"]["tiktokCreativeCenter"]["reason"] == (
        "invalid_empty_response"
    )
    assert outage["counts"]["tracksMarkedCooling"] == 0
    assert outage["counts"]["tracksMarkedStale"] == 0
    assert outage["counts"]["cachedFilesPruned"] == 0
    assert cache_path.is_file()
    with connect(paths.database) as conn:
        after = tuple(
            conn.execute(
                """
                SELECT lifecycle_state, trend_status, active,
                       consecutive_absences, updated_at
                FROM audio_catalog
                """
            ).fetchone()
        )
        assert after == before
        assert (
            conn.execute("SELECT COUNT(*) FROM audio_cache_prune_receipts").fetchone()[
                0
            ]
            == 0
        )


@pytest.mark.parametrize(
    ("protection", "expected_reason"),
    [
        ("pinned", None),
        ("scheduled", "approved_or_scheduled_selection"),
        ("pending_job", "pending_generation_job"),
        ("performance", "recent_performance_winner"),
    ],
)
def test_pruning_retains_protected_tracks(
    tmp_path: Path,
    protection: str,
    expected_reason: str | None,
) -> None:
    paths = _paths(tmp_path)
    audio_cache = AudioCache(paths.cache)
    cached = audio_cache.root / f"{protection}.mp3"
    cached.write_bytes(protection.encode())
    cached.chmod(0o600)
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    now = "2026-06-15T12:00:00Z"
    with connect(paths.database) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO audio_refresh_runs (
              id, region, apply_mode, status, started_at, created_at
            ) VALUES ('run', 'US', 1, 'running', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO audio_catalog (
              id, source_audio_id, canonical_track_id, title, platform,
              lifecycle_state, pinned, active, consecutive_absences,
              imported_at, updated_at
            ) VALUES ('track', 'canonical', 'canonical', 'Track', 'instagram',
                      'STALE', ?, 0, 2, ?, ?)
            """,
            (1 if protection == "pinned" else 0, now, now),
        )
        conn.execute(
            """
            INSERT INTO audio_platform_sound_ids (
              id, audio_catalog_id, platform, sound_id, region,
              first_seen_at, last_seen_at
            ) VALUES ('sound', 'track', 'instagram', 'sound-1', 'US', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO audio_cache_objects (
              id, audio_catalog_id, provider, platform, platform_sound_id,
              cache_path, byte_sha256, acoustic_fingerprint, duration_seconds,
              size_bytes, codec, source_fingerprint, cached, retrieved_at,
              created_at, updated_at
            ) VALUES ('object', 'track', 'fixture', 'instagram', 'sound-1',
                      ?, ?, ?, 10, ?, 'mp3', ?, 1, ?, ?, ?)
            """,
            (
                str(cached),
                digest,
                "f" * 64,
                cached.stat().st_size,
                "s" * 64,
                "2026-05-01T12:00:00Z",
                now,
                now,
            ),
        )
        if protection == "scheduled":
            conn.execute(
                """
                INSERT INTO audio_selections (
                  id, audio_catalog_id, status, payload_json, created_at, updated_at
                ) VALUES ('selection', 'track', 'scheduled', '{}', ?, ?)
                """,
                (now, now),
            )
        elif protection == "pending_job":
            conn.execute(
                """
                INSERT INTO pipeline_jobs (
                  id, job_type, status, input_json, created_at, updated_at
                ) VALUES ('job', 'generation', 'queued',
                          '{"audioCatalogId":"track"}', ?, ?)
                """,
                (now, now),
            )
        elif protection == "performance":
            conn.execute(
                """
                INSERT INTO campaigns (
                  id, slug, name, root_path, created_at, updated_at
                ) VALUES ('campaign', 'campaign', 'Campaign', '/tmp', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO audio_performance_rollups (
                  id, campaign_id, audio_catalog_id, audio_key, score, updated_at
                ) VALUES ('performance', 'campaign', 'track', 'track', 2.0, ?)
                """,
                (now,),
            )
        conn.commit()

        pruned = _prune_cache(
            conn,
            cache=audio_cache,
            run_id="run",
            now=now,
            config=LifecycleThresholds(retention_days=1),
        )

        assert pruned == []
        assert cached.is_file()
        assert (
            conn.execute("SELECT COUNT(*) FROM audio_cache_prune_receipts").fetchone()[
                0
            ]
            == 0
        )
        if expected_reason is not None:
            # The protected cache remains byte-for-byte intact.
            assert hashlib.sha256(cached.read_bytes()).hexdigest() == digest


def test_dry_run_and_provider_failures_do_not_leak_secrets_or_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    social_secret = "social-secret-never-print"
    tiklive_secret = "tiklive-secret-never-print"
    monkeypatch.setenv("SOCIALCRAWL_API_KEY", social_secret)
    monkeypatch.setenv("TIKLIVE_API_KEY", tiklive_secret)

    class LeakyProvider:
        last_metadata: dict[str, Any] = {}

        def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
            raise ProviderError(f"provider echoed {social_secret}")

    result = refresh_audio_library(
        region="US",
        max_new=10,
        max_active=30,
        apply=False,
        paths=_paths(tmp_path),
        social_provider=LeakyProvider(),
        tiktok_social_provider=StaticProvider([]),
        creative_provider=StaticProvider([]),
        now="2026-06-01T12:00:00Z",
    )
    serialized = json.dumps(result)

    assert social_secret not in serialized
    assert tiklive_secret not in serialized
    assert result["dryRunMutations"] == {
        "downloads": 0,
        "activations": 0,
        "deletions": 0,
        "databaseWrites": 0,
    }
    assert not (tmp_path / "campaign.sqlite").exists()
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "receipts").exists()


def test_refresh_preserves_refunded_provider_metadata_in_receipt(
    tmp_path: Path,
) -> None:
    social = FailingProvider()
    social.last_metadata = {
        "requests": 1,
        "httpStatus": 502,
        "providerErrorType": "UPSTREAM_ERROR",
        "creditsUsed": 0.0,
        "creditsRemaining": 95.0,
        "creditsRefunded": True,
    }

    receipt = refresh_audio_library(
        region="US",
        max_new=10,
        max_active=30,
        apply=False,
        paths=_paths(tmp_path),
        social_provider=social,
        tiktok_social_provider=StaticProvider(
            [
                _candidate(
                    provider="socialcrawl_tiktok",
                    platform="tiktok",
                    sound_id="tt_sound_202",
                )
            ]
        ),
        creative_provider=StaticProvider([]),
        tiklive_resolver=object(),
        now="2026-07-24T12:00:00Z",
    )

    instagram = receipt["sourceStatus"]["socialcrawlInstagram"]
    assert instagram["status"] == "unavailable"
    assert instagram["httpStatus"] == 502
    assert instagram["providerErrorType"] == "UPSTREAM_ERROR"
    assert instagram["creditsRefunded"] is True
    assert receipt["credits"]["socialcrawlInstagramUsed"] == 0.0
    assert receipt["credits"]["socialcrawlRemaining"] == 95.0


def test_machine_local_schedule_is_configurable_and_never_publishes() -> None:
    repo = Path(__file__).resolve().parents[3]
    doc = (repo / "docs" / "operations" / "audio_refresh.md").read_text(
        encoding="utf-8"
    )
    runner = (repo / "scripts" / "run_audio_refresh.sh").read_text(encoding="utf-8")

    assert "com.creator-os.audio-refresh" in doc
    assert "PRIVATE_WEEKDAY" in doc
    assert "PRIVATE_HOUR" in doc
    assert "PRIVATE_MINUTE" in doc
    assert "/Users/aderdesouza/.creator-os/run-job.sh" in doc
    assert "CREATOR_OS_AUDIO_REFRESH_ENV" in runner
    assert "--apply" in runner
    assert "creator-os publish" not in runner.lower()
    assert "creator-os schedule" not in runner.lower()
