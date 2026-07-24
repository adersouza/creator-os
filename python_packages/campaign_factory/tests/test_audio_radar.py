from __future__ import annotations

import json
import math
import sqlite3
import wave
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from campaign_factory.adapters.threadsdash_draft_payload import (
    _audio_intent_allows_live,
)
from campaign_factory.audio_policy import build_embedded_trending_audio_intent
from campaign_factory.audio_radar.acquisition import AcquiredAudio, AudioCache
from campaign_factory.audio_radar.binding import bind_embedding_receipt
from campaign_factory.audio_radar.embedding import (
    AudioEmbeddingError,
    embed_selected_audio,
)
from campaign_factory.audio_radar.models import (
    AudioLocator,
    PlatformSoundId,
    TrendCandidate,
)
from campaign_factory.audio_radar.normalization import normalize_candidates
from campaign_factory.audio_radar.providers import (
    ProviderError,
    PublicChartSnapshotProvider,
    SocialCrawlInstagramProvider,
    TikLiveAudioResolver,
    TokchartTrendProvider,
)
from campaign_factory.audio_radar.ranking import AudioMatchContext, rank_candidates
from campaign_factory.audio_radar.segment import SegmentSelection, select_segment

from pipeline_contracts import validate_audio_intent

FIXTURES = Path(__file__).parent / "fixtures" / "audio_radar"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_provider_fixtures_normalize_and_preserve_platform_sound_ids() -> None:
    instagram = SocialCrawlInstagramProvider.parse(
        _fixture("socialcrawl_trending.redacted.json"),
        region="US",
        limit=10,
    )
    tiktok = TokchartTrendProvider.parse(
        _fixture("tokchart_trending.redacted.json"),
        region="US",
        limit=10,
    )

    normalized = normalize_candidates([*instagram, *tiktok])

    assert len(normalized) == 1
    candidate = normalized[0]
    assert candidate.canonical_title == "midnight glow"
    assert {
        (value.platform, value.sound_id) for value in candidate.platform_sound_ids
    } == {
        ("instagram", "ig_audio_101"),
        ("tiktok", "tt_sound_202"),
    }
    assert candidate.usage_velocity == 6_100
    assert candidate.locator is not None


def test_tiklive_fixture_returns_allowlisted_locator() -> None:
    locator = TikLiveAudioResolver.parse(
        _fixture("tiklive_music_info.redacted.json"),
        music_id="tt_sound_202",
    )

    assert locator.track_id == "tt_sound_202"
    assert locator.kind == "playable_url"
    assert locator.allowed_hosts == ("cdn.example.test",)


def test_ranking_blocks_recent_and_scheduled_track_reuse() -> None:
    candidates = normalize_candidates(
        [
            TrendCandidate(
                candidate_id="one",
                provider="fixture",
                title="One",
                artist="Artist",
                platform_sound_ids=(PlatformSoundId("instagram", "1"),),
                observed_at="2026-07-24T12:00:00Z",
                current_rank=1,
                usage_velocity=5000,
                freshness_hours=24,
            ),
            TrendCandidate(
                candidate_id="two",
                provider="fixture",
                title="Two",
                artist="Artist",
                platform_sound_ids=(PlatformSoundId("instagram", "2"),),
                observed_at="2026-07-24T12:00:00Z",
                current_rank=2,
                usage_velocity=4000,
                freshness_hours=48,
            ),
        ]
    )
    first_id = str(candidates[0].canonical_track_id)
    ranked = rank_candidates(
        candidates,
        AudioMatchContext(
            creator="stacey",
            account="stacey",
            recently_used_track_ids=(first_id,),
        ),
    )

    assert len(ranked) == 1
    assert ranked[0].candidate.canonical_track_id != first_id


def test_mainstream_platform_discovery_and_rights_labels_do_not_gate_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mainstream-song.mp4"
    source.write_bytes(b"provider-authenticated mainstream audio bytes")
    discovered = normalize_candidates(
        [
            TrendCandidate(
                candidate_id="socialcrawl:instagram:ig_mainstream_1",
                provider="socialcrawl",
                title="Mainstream Chart Song",
                artist="Major Artist",
                platform_sound_ids=(PlatformSoundId("instagram", "ig_mainstream_1"),),
                observed_at="2026-07-24T12:00:00Z",
                current_rank=1,
                usage_velocity=50_000,
                locator=AudioLocator(
                    provider="socialcrawl",
                    platform="instagram",
                    track_id="ig_mainstream_1",
                    kind="local_file",
                    value=str(source),
                ),
                advisory_labels={
                    "discovered_via": "instagram",
                    "copyright": "mainstream",
                    "commercial_music": True,
                    "royalty_free": False,
                },
            ),
            TrendCandidate(
                candidate_id="tokchart:tiktok:tt_mainstream_2",
                provider="tokchart",
                title="Another Mainstream Song",
                artist="Major Artist",
                platform_sound_ids=(PlatformSoundId("tiktok", "tt_mainstream_2"),),
                observed_at="2026-07-24T12:00:00Z",
                current_rank=2,
                usage_velocity=40_000,
                advisory_labels={
                    "discovered_via": "tiktok",
                    "licensed": True,
                    "royalty_free": False,
                },
            ),
        ]
    )

    ranked = rank_candidates(
        discovered,
        AudioMatchContext(creator="stacey", account="stacey"),
    )

    assert {value.candidate.provider for value in ranked} == {
        "socialcrawl",
        "tokchart",
    }
    assert {
        sound.platform
        for value in ranked
        for sound in value.candidate.platform_sound_ids
    } == {"instagram", "tiktok"}
    monkeypatch.setattr(
        "campaign_factory.audio_radar.acquisition.probe_media",
        lambda _path: {
            "format": {"duration": "12.0"},
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                }
            ],
        },
    )
    acquired = AudioCache(tmp_path / "private-cache").acquire(
        next(
            value.candidate.locator
            for value in ranked
            if value.candidate.locator is not None
        ),
        retrieved_at="2026-07-24T12:00:00Z",
    )

    assert acquired.track_id == "ig_mainstream_1"
    assert acquired.byte_sha256 == sha256(source.read_bytes()).hexdigest()


def test_private_local_acquisition_hashes_and_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "operator-audio.mp4"
    source.write_bytes(b"operator supplied audio bytes")
    monkeypatch.setattr(
        "campaign_factory.audio_radar.acquisition.probe_media",
        lambda _path: {
            "format": {"duration": "9.5"},
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                }
            ],
        },
    )
    cache = AudioCache(tmp_path / "private-cache")
    acquired = cache.acquire(
        AudioLocator(
            provider="operator",
            platform="local",
            track_id="track-1",
            kind="local_file",
            value=str(source),
        ),
        retrieved_at="2026-07-24T12:00:00Z",
    )

    assert acquired.cache_path.read_bytes() == source.read_bytes()
    assert acquired.cache_path.stat().st_mode & 0o777 == 0o600
    assert acquired.duration_seconds == 9.5
    assert acquired.receipt()["source_fingerprint"]


def test_private_cache_sanitizes_provider_platform_and_track_path_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "operator-audio.mp4"
    source.write_bytes(b"operator supplied audio bytes")
    monkeypatch.setattr(
        "campaign_factory.audio_radar.acquisition.probe_media",
        lambda _path: {
            "format": {"duration": "9.5"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        },
    )
    cache = AudioCache(tmp_path / "private-cache")

    acquired = cache.acquire(
        AudioLocator(
            provider="../../provider",
            platform="../platform",
            track_id="../../track",
            kind="local_file",
            value=str(source),
        ),
        retrieved_at="2026-07-24T12:00:00Z",
    )

    assert acquired.cache_path.parent == cache.root


def test_public_chart_snapshot_rejects_symlink(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"observed_at":"2026-07-24T12:00:00Z","items":[]}')
    link = tmp_path / "snapshot-link.json"
    link.symlink_to(snapshot)

    with pytest.raises(ProviderError, match="missing or unsafe"):
        PublicChartSnapshotProvider(link).discover(region="US", limit=10)


def test_embedding_refuses_to_replace_its_source_video(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source video")
    acquired = AcquiredAudio(
        cache_path=tmp_path / "audio.mp4",
        provider="provider",
        platform="instagram",
        track_id="track",
        retrieved_at="2026-07-24T12:00:00Z",
        source_kind="local_file",
        source_fingerprint="a" * 64,
        byte_sha256="b" * 64,
        size_bytes=1,
        duration_seconds=5,
        codec="aac",
        sample_rate=48_000,
        channels=2,
    )
    segment = SegmentSelection(
        start_offset_seconds=0,
        duration_seconds=5,
        segment_score=1,
        rms_energy=1,
        peak_energy=1,
        onset_count=1,
        energy_change=1,
        beat_evidence="test",
        hook_evidence="test",
        selection_reason="test",
        decoded_audio_fingerprint="c" * 64,
    )

    with pytest.raises(AudioEmbeddingError, match="must differ"):
        embed_selected_audio(
            video_path=video,
            acquired=acquired,
            segment=segment,
            output_path=video,
        )


def test_segment_selection_scores_full_track_and_avoids_zero_default(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "energy.wav"
    sample_rate = 16_000
    duration = 8
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate * duration):
            second = index / sample_rate
            amplitude = 2500 if second < 2 else 18_000
            sample = int(amplitude * math.sin(2 * math.pi * 4 * second))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        handle.writeframes(frames)
    acquired = AcquiredAudio(
        cache_path=audio,
        provider="operator",
        platform="local",
        track_id="track",
        retrieved_at="2026-07-24T12:00:00Z",
        source_kind="local_file",
        source_fingerprint="a" * 64,
        byte_sha256="b" * 64,
        size_bytes=audio.stat().st_size,
        duration_seconds=8,
        codec="pcm_s16le",
        sample_rate=sample_rate,
        channels=1,
    )

    selected = select_segment(acquired, reel_duration_seconds=3)

    assert selected.start_offset_seconds > 0
    assert selected.duration_seconds == 3
    assert selected.onset_count >= 0
    assert len(selected.decoded_audio_fingerprint) == 64


def test_embedding_receipt_builds_verified_embedded_trending_handoff() -> None:
    receipt = {
        "schema": "creator_os.audio_embedding_receipt.v1",
        "policy": "embedded_trending_required",
        "verification": {
            "status": "verified",
            "audioPresent": True,
            "audioCodec": "aac",
        },
        "finalVideo": {
            "sha256": "a" * 64,
            "audioFingerprint": "b" * 64,
        },
        "selectedTrack": {
            "trackId": "track-1",
            "provider": "operator",
            "acquiredAudioSha256": "c" * 64,
        },
        "selectedSegment": {
            "start_offset_seconds": 2.5,
            "duration_seconds": 5.0,
            "segment_score": 0.91,
            "beat_evidence": "pcm_energy_onset_proxy",
            "hook_evidence": "energy_and_onset_window",
            "selection_reason": "best segment",
        },
        "selection": {
            "canonicalTrackId": "canonical-1",
            "canonicalTitle": "midnight glow",
            "canonicalArtists": ["example artist"],
            "platformSoundIds": [{"platform": "instagram", "soundId": "ig-1"}],
            "trendRank": 4,
            "trendVelocity": 4200,
        },
        "mixSettings": {"volume": 0.82},
    }

    intent = build_embedded_trending_audio_intent(
        receipt,
        selected_at="2026-07-24T12:00:00Z",
    )

    assert intent["policy"] == "embedded_trending_required"
    assert intent["status"] == "verified"
    assert intent["fulfillment"]["output_sha256"] == "a" * 64
    assert intent["fulfillment"]["embedded_audio_fingerprint"] == "b" * 64
    assert intent["operator_selection"]["platform_sound_ids"] == [
        {"platform": "instagram", "sound_id": "ig-1"}
    ]
    assert intent["gates"]["allow_publish"] is True
    validate_audio_intent(intent)
    assert _audio_intent_allows_live(intent) is True
    intent["fulfillment"].pop("embedded_audio_fingerprint")
    assert _audio_intent_allows_live(intent) is False


def test_verified_receipt_rebinds_exact_asset_and_appends_lineage(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-with-audio.mp4"
    final_path.write_bytes(b"verified final MP4 bytes with AAC proof")
    final_sha = sha256(final_path.read_bytes()).hexdigest()
    original_sha = "d" * 64
    receipt = {
        "schema": "creator_os.audio_embedding_receipt.v1",
        "policy": "embedded_trending_required",
        "verification": {
            "status": "verified",
            "audioPresent": True,
            "audioCodec": "aac",
        },
        "originalVideo": {"path": "/private/original.mp4", "sha256": original_sha},
        "finalVideo": {
            "path": str(final_path),
            "sha256": final_sha,
            "audioFingerprint": "b" * 64,
        },
        "selectedTrack": {
            "trackId": "track-1",
            "provider": "operator",
            "acquiredAudioSha256": "c" * 64,
        },
        "selectedSegment": {
            "start_offset_seconds": 2.5,
            "duration_seconds": 5.0,
            "segment_score": 0.91,
            "beat_evidence": "pcm_energy_onset_proxy",
            "hook_evidence": "energy_and_onset_window",
            "selection_reason": "best segment",
        },
        "selection": {
            "canonicalTrackId": "canonical-1",
            "canonicalTitle": "midnight glow",
            "canonicalArtists": ["example artist"],
            "platformSoundIds": [{"platform": "instagram", "soundId": "ig-1"}],
            "trendRank": 4,
            "trendVelocity": 4200,
        },
        "mixSettings": {"volume": 0.82},
    }
    receipt["audioIntent"] = build_embedded_trending_audio_intent(
        receipt,
        selected_at="2026-07-24T12:00:00Z",
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE rendered_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          source_asset_id TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          output_path TEXT NOT NULL,
          campaign_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          caption_generation_json TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          audit_status TEXT NOT NULL,
          review_state TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE generation_output_blobs (
          id TEXT PRIMARY KEY,
          content_sha256 TEXT NOT NULL UNIQUE,
          byte_size INTEGER,
          media_type TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE generation_attempts (
          id TEXT PRIMARY KEY,
          rendered_asset_id TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE generation_lineage_edges (
          id TEXT PRIMARY KEY,
          generation_attempt_id TEXT NOT NULL,
          source_asset_id TEXT,
          rendered_asset_id TEXT NOT NULL,
          output_blob_id TEXT NOT NULL,
          relation TEXT NOT NULL,
          lineage_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(generation_attempt_id, relation)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO rendered_assets
        VALUES (
          'asset-1', 'campaign-1', 'source-1', ?, '/private/original.mp4',
          '/private/original.mp4', 'original.mp4', '{}',
          '{"publishability":{"blockingIssues":["NEEDS_EMBEDDED_AUDIO"]}}',
          'pending', 'review_ready', '2026-07-24T11:00:00Z'
        )
        """,
        (original_sha,),
    )
    conn.execute(
        "INSERT INTO generation_attempts VALUES ('attempt-1', 'asset-1', ?)",
        ("2026-07-24T11:00:00Z",),
    )

    result = bind_embedding_receipt(
        conn,
        rendered_asset_id="asset-1",
        embedding_receipt=receipt,
        bound_at="2026-07-24T12:05:00Z",
    )

    row = conn.execute(
        """
        SELECT content_hash, output_path, caption_generation_json, metadata_json
        FROM rendered_assets
        WHERE id = 'asset-1'
        """
    ).fetchone()
    assert row is not None
    caption_generation = json.loads(row[2])
    metadata = json.loads(row[3])
    assert row[0] == final_sha
    assert row[1] == str(final_path)
    assert caption_generation["audioIntent"]["policy"] == ("embedded_trending_required")
    assert metadata["audioBurned"] is True
    assert metadata["publishability"]["blockingIssues"] == [
        "audio_creative_approval_required"
    ]
    assert result["finalVideoSha256"] == final_sha
    assert (
        conn.execute("SELECT relation FROM generation_lineage_edges").fetchone()[0]
        == "audio_embedding"
    )


def test_normalized_candidate_serialization_redacts_locator_value() -> None:
    candidate = normalize_candidates(
        SocialCrawlInstagramProvider.parse(
            _fixture("socialcrawl_trending.redacted.json"),
            region="US",
            limit=10,
        )
    )[0]
    assert candidate.locator is not None
    serialized = candidate.as_dict()

    assert serialized["locator"]["available"] is True
    assert "value" not in serialized["locator"]
    assert "request_headers" not in serialized["locator"]


def test_distinct_explicit_versions_remain_separate_before_fingerprinting() -> None:
    base = TrendCandidate(
        candidate_id="base",
        provider="fixture",
        title="Song (Sped Up)",
        artist="Artist",
        platform_sound_ids=(PlatformSoundId("instagram", "ig"),),
        observed_at="2026-07-24T12:00:00Z",
    )
    alternate = replace(
        base,
        candidate_id="alt",
        title="Song - Slowed",
        platform_sound_ids=(PlatformSoundId("tiktok", "tt"),),
    )

    normalized = normalize_candidates([base, alternate])

    assert len(normalized) == 2
    assert {value.canonical_title for value in normalized} == {"song"}
    assert {value.variant for value in normalized} == {"sped up", "slowed"}
    assert len({value.canonical_track_id for value in normalized}) == 2
