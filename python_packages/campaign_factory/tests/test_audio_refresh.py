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
    ) -> None:
        self.candidates = candidates
        self.last_metadata = {"status": status, "requests": 1}
        self.calls = 0

    def discover(self, *, region: str | None, limit: int) -> list[TrendCandidate]:
        self.calls += 1
        return self.candidates[:limit]


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
    creative = StaticProvider(
        [
            _candidate(
                provider="tiktok_creative_center",
                platform="tiktok",
                sound_id="tt_sound_202",
            )
        ]
    )
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

    empty = StaticProvider([])
    cooling = refresh_audio_library(
        region="US",
        max_new=1,
        max_active=30,
        apply=True,
        paths=paths,
        thresholds=config,
        social_provider=empty,
        creative_provider=empty,
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
        creative_provider=empty,
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
