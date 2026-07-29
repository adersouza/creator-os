from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.audio_policy import build_motion_audio_intent
from campaign_factory.audio_radar.models import (
    AudioLocator,
    PlatformSoundId,
    TrendCandidate,
)
from campaign_factory.creative_approval import asset_requires_creative_approval
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.learning_score import learning_eligible
from campaign_factory.production_audio_library import apply_audio_usage_policy
from campaign_factory.production_lane import (
    _audio_candidates_for_job,
    _block_duplicate_provider_outputs,
    _expand_production_job_prompt,
    _run_production_job,
    discover_production_audio_candidates,
    plan_production_batch,
    run_production_batch,
)
from campaign_factory.production_quality_policy import production_quality_policy
from PIL import Image


def _production_factory(
    tmp_path: Path, *, source_count: int = 2, creator: str = "stacey"
) -> SimpleNamespace:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaigns (id TEXT PRIMARY KEY, slug TEXT, updated_at TEXT);
        CREATE TABLE models (id TEXT PRIMARY KEY, slug TEXT);
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT,
          model_id TEXT,
          content_hash TEXT,
          stored_path TEXT,
          media_type TEXT,
          status TEXT,
          created_at TEXT
        );
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
        "INSERT INTO campaigns VALUES ('campaign-1', ?, '2026')",
        (f"{creator}-main",),
    )
    conn.execute("INSERT INTO models VALUES ('model-1', ?)", (creator,))
    for index in range(source_count):
        path = tmp_path / f"approved-{index}.png"
        Image.new("RGB", (360, 640), color=(index, 20, 40)).save(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        conn.execute(
            "INSERT INTO source_assets VALUES (?, 'campaign-1', 'model-1', ?, ?, "
            "'image', 'approved', ?)",
            (f"source-{index}", digest, str(path), f"2026-{index}"),
        )
    return SimpleNamespace(conn=conn)


def _fixture_media(tmp_path: Path) -> tuple[Path, Path]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for embedded-audio golden proof")
    video = tmp_path / "generated.mp4"
    audio = tmp_path / "candidate.m4a"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=128x224:r=24",
            "-t",
            "2",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "4",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    return video, audio


def _fake_generation(factory: SimpleNamespace, video: Path) -> dict[str, object]:
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    metadata = {
        "productionMotionRecipe": {"status": "active"},
        "humanReviewRequired": False,
        "creativeApprovalRequired": False,
        "publishability": {
            "blockingIssues": [
                "contentforge_audit_required",
                "motion_specific_qc_required",
                "NEEDS_EMBEDDED_AUDIO",
            ]
        },
    }
    factory.conn.execute(
        """
        INSERT INTO rendered_assets VALUES (
          'generated-asset', 'campaign-1', 'source-0', ?, ?, ?, ?, '{}', ?,
          'pending', 'review_ready', '2026-07-24T12:00:00Z'
        )
        """,
        (
            digest,
            str(video),
            str(video),
            video.name,
            json.dumps(metadata),
        ),
    )
    factory.conn.execute(
        "INSERT INTO generation_attempts VALUES "
        "('generation-attempt', 'generated-asset', '2026-07-24T12:00:00Z')"
    )
    row = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = 'generated-asset'"
    ).fetchone()
    return {"registeredAsset": dict(row)}


def _fixture_candidate(audio: Path) -> TrendCandidate:
    return TrendCandidate(
        candidate_id="fixture:instagram:audio-1",
        provider="fixture",
        title="Golden Trend",
        artist="Fixture Artist",
        platform_sound_ids=(
            PlatformSoundId(platform="instagram", sound_id="ig-audio-1"),
        ),
        observed_at="2026-07-24T12:00:00Z",
        current_rank=1,
        usage_velocity=10_000,
        locator=AudioLocator(
            provider="fixture",
            platform="instagram",
            track_id="audio-1",
            kind="local_file",
            value=str(audio),
        ),
    )


def test_production_audio_prefers_canonical_active_cache(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE audio_catalog (
          id TEXT PRIMARY KEY, canonical_track_id TEXT, canonical_title TEXT,
          canonical_artists_json TEXT, title TEXT, artist_name TEXT,
          platform TEXT, mood_tags_json TEXT, best_content_types_json TEXT,
          native_audio_id TEXT, velocity_score REAL,
          trend_score REAL, trend_sources_json TEXT, lifecycle_state TEXT,
          last_seen_at TEXT, refresh_metadata_json TEXT, active INTEGER
        );
        CREATE TABLE audio_cache_objects (
          audio_catalog_id TEXT, provider TEXT, platform TEXT,
          platform_sound_id TEXT, cache_path TEXT, byte_sha256 TEXT,
          acoustic_fingerprint TEXT, duration_seconds REAL, retrieved_at TEXT,
          source_metadata_json TEXT, cached INTEGER, pruned_at TEXT
        );
        """
    )
    cached = tmp_path / "cached-audio.bin"
    cached.write_bytes(b"active-audio-cache")
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    conn.execute(
        """
        INSERT INTO audio_catalog VALUES (
          'audio-1', 'canonical-1', 'Cached Trend', '["Artist"]',
          'Cached Trend', 'Artist', 'tiktok', '["playful"]', '["lifestyle"]',
          'music-1', 1234, 0.9,
          '["socialcrawl_tiktok"]', 'HOT', '2026-07-27T00:00:00Z',
          '{"score":42}', 1
        )
        """
    )
    conn.execute(
        """
        INSERT INTO audio_cache_objects VALUES (
          'audio-1', 'tikliveapi', 'tiktok', 'music-1', ?, ?, ?, 60,
          '2026-07-27T00:01:00Z', '{"soundOwner":"Owner","videoCount":99}',
          1, NULL
        )
        """,
        (str(cached), digest, "f" * 64),
    )

    candidates = discover_production_audio_candidates(conn)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.canonical_track_id == "canonical-1"
    assert candidate.locator is not None
    assert candidate.locator.kind == "local_file"
    assert candidate.locator.value == str(cached)
    assert candidate.artist == "Artist"
    assert candidate.mood_tags == ("playful", "lifestyle")
    assert candidate.advisory_labels["source"] == "canonical_active_audio_library"
    assert candidate.advisory_labels["soundOwner"] == "Owner"


def test_batch_audio_partitions_avoid_unnecessary_track_reuse(tmp_path: Path) -> None:
    candidates = [
        _fixture_candidate(tmp_path / f"audio-{index}.bin") for index in range(6)
    ]

    partitions = [
        _audio_candidates_for_job(
            candidates,
            job_index=index,
            job_count=3,
        )
        for index in range(3)
    ]

    assert [len(partition) for partition in partitions] == [2, 2, 2]
    assert not (
        {id(item) for item in partitions[0]} & {id(item) for item in partitions[1]}
    )
    assert not (
        {id(item) for item in partitions[1]} & {id(item) for item in partitions[2]}
    )


def test_batch_audio_excludes_acoustic_duplicates(tmp_path: Path) -> None:
    candidates = [
        replace(
            _fixture_candidate(tmp_path / f"audio-{index}.bin"),
            candidate_id=f"candidate-{index}",
            canonical_track_id=f"track-{index}",
            advisory_labels={"acousticFingerprint": "f" * 64},
        )
        for index in range(2)
    ]

    assert len(_audio_candidates_for_job(candidates, job_index=0, job_count=1)) == 1


def test_account_and_creator_audio_cooldowns_with_winner_override(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE rendered_assets (metadata_json TEXT, updated_at TEXT);
        CREATE TABLE audio_performance_rollups (
          audio_catalog_id TEXT, score REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO rendered_assets VALUES (?, ?)",
        (
            json.dumps(
                {
                    "audioEmbeddingReceipt": {
                        "creativeContext": {
                            "creator": "stacey",
                            "account": "stacey-main",
                        },
                        "selection": {
                            "canonicalTrackId": "legacy-normalized-track",
                            "advisoryLabels": {"audioCatalogId": "audio-1"},
                            "platformSoundIds": [
                                {"platform": "tiktok", "soundId": "sound-1"}
                            ],
                        },
                        "selectedSegment": {"start_offset_seconds": 12.5},
                    }
                }
            ),
            "2026-07-26T12:00:00Z",
        ),
    )
    candidates = [
        replace(
            _fixture_candidate(tmp_path / f"audio-{index}.bin"),
            candidate_id=f"candidate-{index}",
            canonical_track_id=f"track-{index}",
            advisory_labels={"audioCatalogId": f"audio-{index}"},
        )
        for index in range(1, 3)
    ]

    cooled = apply_audio_usage_policy(
        conn,
        candidates,
        creator="stacey",
        account="stacey-main",
        now="2026-07-27T12:00:00Z",
    )

    assert [candidate.canonical_track_id for candidate in cooled] == ["track-2"]

    conn.execute("INSERT INTO audio_performance_rollups VALUES ('audio-1', 2.0)")
    overridden = apply_audio_usage_policy(
        conn,
        candidates,
        creator="stacey",
        account="stacey-main",
        now="2026-07-27T12:00:00Z",
    )
    winner = next(
        candidate
        for candidate in overridden
        if candidate.canonical_track_id == "track-1"
    )
    assert winner.advisory_labels["measuredWinnerCooldownOverride"] is True
    assert "excludedSegmentOffsetsSeconds" not in winner.advisory_labels


def test_golden_approved_source_to_generated_image_capability() -> None:
    plan = build_generation_execution_plan("soul_static")
    assert plan.still_strategy == "soul_reference_pair"
    assert "generated_image_qc" in plan.qc_requirements


def test_golden_approved_source_to_static_mp4_capability() -> None:
    plan = build_generation_execution_plan("soul_static")
    assert plan.motion_strategy == "static_mp4_only"
    assert plan.static_fallback_required is True


def test_production_create_rejects_retired_local_wan_lane(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires Higgsfield cloud execution"):
        plan_production_batch(
            _production_factory(tmp_path),
            creator="stacey",
            intent="passive_selfie",
            count=1,
            execution="local",
            accounts="stacey-main",
            audio_preference="native_trending_required",
        )


def test_cloud_production_uses_pinned_higgsfield_kling_recipe(tmp_path: Path) -> None:
    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=3,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )
    assert {job["productionRecipe"]["modelId"] for job in batch["jobs"]} == {
        "higgsfield_kling3_turbo_i2v"
    }
    assert batch["provider"] == "higgsfield"
    assert batch["providerQuoteStatus"] == "required_before_apply"
    assert batch["quotedProviderCredits"] is None
    assert all(
        job["productionRecipe"]["stages"][0]["sound"] == "off" for job in batch["jobs"]
    )
    assert all(
        job["promptCard"]["source"]["sha256"] == job["sourceSha256"]
        for job in batch["jobs"]
    )
    assert all(job["compatibility"]["providerCalls"] == 0 for job in batch["jobs"])
    assert all(
        job["compiledPrompt"]["compiledPromptFingerprint"] for job in batch["jobs"]
    )


def test_normal_create_uses_one_openai_prompt_pack_per_source(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def prompts(**kwargs):
        calls.append(kwargs)
        return {
            "promptPackFingerprint": "f" * 64,
            "anchorPrompt": "Calm vertical portrait.",
            "seedancePrompt": "Seedance calm motion.",
            "klingPrompt": "Kling calm motion.",
            "promptPlanning": {
                "builderVersion": "creator_os_openai_prompt_builder.v2",
                "requestFingerprint": str(kwargs["creator_image"]),
                "cost": {"status": "not_exposed", "usd": None},
            },
            "cache": {"status": "miss", "providerCallMade": True},
        }

    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=3,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        prompt_pack_provider=prompts,
    )

    assert len(calls) == 2
    assert all(call["external_call_authorized"] is False for call in calls)
    assert {job["prompt"] for job in batch["jobs"]} == {"Kling calm motion."}
    assert all(
        job["promptCard"]["openaiPromptPackFingerprint"] == "f" * 64
        for job in batch["jobs"]
    )
    assert len(batch["promptPlanning"]) == 2
    assert all(
        item["currentRunCost"] == {"status": "not_exposed", "usd": None}
        for item in batch["promptPlanning"]
    )


@pytest.mark.parametrize("creator", ["stacey", "larissa", "lola"])
@pytest.mark.parametrize(
    "intent",
    ["passive_selfie", "flirty_portrait", "outfit", "lifestyle", "animate_existing"],
)
def test_supported_cloud_intents_bind_each_creator_soul(
    tmp_path: Path, creator: str, intent: str
) -> None:
    batch = plan_production_batch(
        _production_factory(tmp_path, creator=creator),
        creator=creator,
        intent=intent,
        count=1,
        execution="cloud",
        accounts=f"{creator}-main",
        audio_preference="embedded_trending_required",
    )

    job = batch["jobs"][0]
    assert job["creator"] == creator
    assert job["productionRecipe"]["creator"] == creator
    assert job["productionRecipe"]["provider"] == "higgsfield"
    assert job["productionRecipe"]["stages"][0]["sound"] == "off"


def test_unknown_creator_fails_before_provider_planning(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="no pinned authenticated Higgsfield Soul identity",
    ):
        plan_production_batch(
            _production_factory(tmp_path),
            creator="unknown",
            intent="passive_selfie",
            count=1,
            execution="cloud",
            accounts="unknown-main",
            audio_preference="embedded_trending_required",
        )


def test_non_talking_production_requires_embedded_trending(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="non-talking production intents require embedded_trending_required",
    ):
        plan_production_batch(
            _production_factory(tmp_path),
            creator="stacey",
            intent="passive_selfie",
            count=1,
            execution="cloud",
            accounts="stacey-main",
            audio_preference="creator_voice",
        )


def test_cloud_source_resolution_skips_non_reel_aspect_ratios(
    tmp_path: Path,
) -> None:
    factory = _production_factory(tmp_path)
    first = factory.conn.execute(
        "SELECT * FROM source_assets ORDER BY created_at LIMIT 1"
    ).fetchone()
    assert first is not None
    first_path = Path(first["stored_path"])
    Image.new("RGB", (120, 160), color=(10, 20, 40)).save(first_path)
    first_sha = hashlib.sha256(first_path.read_bytes()).hexdigest()
    factory.conn.execute(
        "UPDATE source_assets SET content_hash = ? WHERE id = ?",
        (first_sha, first["id"]),
    )

    batch = plan_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts=None,
        audio_preference="embedded_trending",
    )

    assert batch["jobs"][0]["sourceAssetId"] != first["id"]
    assert batch["jobs"][0]["sourceResolution"]["aspectRatio"] == 0.5625


def test_normal_create_ignores_imported_but_unapproved_sources(
    tmp_path: Path,
) -> None:
    factory = _production_factory(tmp_path)
    factory.conn.execute(
        "UPDATE source_assets SET status = 'imported' WHERE id = 'source-0'"
    )

    batch = plan_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=2,
        execution="cloud",
        accounts=None,
        audio_preference="embedded_trending",
    )

    assert {job["sourceAssetId"] for job in batch["jobs"]} == {"source-1"}


def test_normal_create_fails_closed_without_explicit_source_approval(
    tmp_path: Path,
) -> None:
    factory = _production_factory(tmp_path)
    factory.conn.execute("UPDATE source_assets SET status = 'imported'")

    with pytest.raises(ValueError, match="no explicitly approved image inventory"):
        plan_production_batch(
            factory,
            creator="stacey",
            intent="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending",
        )


def test_golden_reel_caption_hook_audio_to_postable_handoff() -> None:
    intent = build_motion_audio_intent(
        policy="native_trending_required",
        audio={"mode": "none"},
        output_sha256="a" * 64,
        selected_at="2026-07-24T00:00:00Z",
        track_id="native-track",
        track_name="trend",
        source="audio_radar",
        selected_reason="creator-fit",
    )
    assert intent["schema"] == "pipeline.audio_intent.v1"
    assert intent["required"] is True
    assert intent["policy"] == "native_trending_required"


def test_golden_production_embeds_ranked_audio_and_binds_exact_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "campaign_factory.production_lane._OPERATOR_VISUAL_SELECTION_COMPLETE",
        True,
    )
    factory = _production_factory(tmp_path)
    video, audio = _fixture_media(tmp_path)
    monkeypatch.setattr(
        "campaign_factory.production_lane._execute_higgsfield_provider_job",
        lambda *_args, **_kwargs: (
            _fake_generation(factory, video),
            {
                "requestId": "higgsfield-test",
                "outputSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "generationDurationSeconds": 1.0,
                "providerCostCredits": 8,
            },
        ),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._expand_production_job_prompt",
        lambda job: dict(job),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane.discover_production_audio_candidates",
        lambda *_args: [_fixture_candidate(audio)],
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._authorize_higgsfield_jobs",
        lambda _factory, jobs, max_total_credits: [
            {**job, "quotedProviderCredits": 8} for job in jobs
        ],
    )

    batch = run_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=True,
        max_total_credits=10,
    )

    assert batch["summary"]["completed"] == 1, json.dumps(batch, default=str)
    assert batch["results"][0]["hardQc"]["status"] == "passed"
    completed = batch["results"][0]["result"]["audioFulfillment"]
    receipt = completed["receipt"]
    intent = receipt["audioIntent"]
    row = factory.conn.execute(
        "SELECT content_hash, output_path, metadata_json FROM rendered_assets "
        "WHERE id = 'generated-asset'"
    ).fetchone()
    assert row is not None
    metadata = json.loads(row[2])
    assert receipt["selection"]["canonicalTrackId"]
    assert receipt["selectedTrack"]["acquisitionReceipt"]["byte_sha256"]
    assert receipt["selectedSegment"]["duration_seconds"] == pytest.approx(2, abs=0.12)
    assert receipt["verification"]["audioCodec"] == "aac"
    assert receipt["verification"]["audioPresent"] is True
    assert intent["policy"] == "embedded_trending_required"
    assert intent["fulfillment"]["output_sha256"] == row[0]
    assert completed["finalVideoSha256"] == row[0]
    assert completed["outputPath"] == row[1]
    assert metadata["output"]["sha256"] == row[0]
    assert metadata["publishability"]["blockingIssues"] == [
        "contentforge_audit_required",
        "motion_specific_qc_required",
    ]
    assert "native_audio_id" not in json.dumps(intent)


def test_golden_missing_audio_candidates_blocks_without_silence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "campaign_factory.production_lane._OPERATOR_VISUAL_SELECTION_COMPLETE",
        True,
    )
    factory = _production_factory(tmp_path)
    video, _audio = _fixture_media(tmp_path)
    monkeypatch.setattr(
        "campaign_factory.production_lane._execute_higgsfield_provider_job",
        lambda *_args, **_kwargs: (
            _fake_generation(factory, video),
            {
                "requestId": "higgsfield-test",
                "outputSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "generationDurationSeconds": 1.0,
                "providerCostCredits": 8,
            },
        ),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._expand_production_job_prompt",
        lambda job: dict(job),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane.discover_production_audio_candidates",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._authorize_higgsfield_jobs",
        lambda _factory, jobs, max_total_credits: [
            {**job, "quotedProviderCredits": 8} for job in jobs
        ],
    )

    batch = run_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=True,
        max_total_credits=10,
    )

    assert batch["summary"]["blocked"] == 1, json.dumps(batch, default=str)
    assert batch["results"][0]["error"] == "NEEDS_EMBEDDED_AUDIO"
    assert batch["summary"]["published"] == 0


def test_golden_batch_request_has_independent_outputs(tmp_path: Path) -> None:
    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="outfit",
        count=5,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending_required",
    )
    jobs = batch["jobs"]
    assert len(jobs) == 5
    assert len({job["jobId"] for job in jobs}) == 5
    assert len({job["seed"] for job in jobs}) == 5
    assert len({job["sourceAssetId"] for job in jobs}) == 2


def test_source_inventory_sha_substitution_is_rejected(tmp_path: Path) -> None:
    factory = _production_factory(tmp_path, source_count=1)
    source = Path(
        factory.conn.execute("SELECT stored_path FROM source_assets").fetchone()[0]
    )
    source.write_bytes(b"substituted-after-approval")
    with pytest.raises(ValueError, match="approved source SHA mismatch"):
        plan_production_batch(
            factory,
            creator="stacey",
            intent="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending",
        )


def test_cloud_batch_uses_bounded_concurrency_and_preserves_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "campaign_factory.production_lane._OPERATOR_VISUAL_SELECTION_COMPLETE",
        True,
    )
    factory = _production_factory(tmp_path, source_count=3)
    factory.settings = object()
    factory.close = lambda: None
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_expand(job):
        return dict(job)

    def fake_isolated(_factory, *, job, audio_candidates, max_credits_per_job):
        nonlocal active, peak
        assert max_credits_per_job == 8
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        if job["index"] == 1:
            return {
                "jobId": job["jobId"],
                "index": job["index"],
                "status": "failed",
                "error": "provider_failed",
            }
        digest = hashlib.sha256(str(job["index"]).encode()).hexdigest()
        return {
            "jobId": job["jobId"],
            "index": job["index"],
            "status": "completed",
            "provider": {
                "requestId": f"prediction-{job['index']}",
                "outputSha256": digest,
                "generationDurationSeconds": 1.0,
                "providerCostCredits": 8,
            },
            "result": {
                "audioFulfillment": {
                    "finalVideoSha256": digest,
                    "outputPath": f"/tmp/{digest}.mp4",
                }
            },
        }

    monkeypatch.setattr(
        "campaign_factory.production_lane._expand_production_job_prompt", fake_expand
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._run_production_job_isolated", fake_isolated
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._authorize_higgsfield_jobs",
        lambda _factory, jobs, max_total_credits: [
            {**job, "quotedProviderCredits": 8} for job in jobs
        ],
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane.discover_production_audio_candidates",
        lambda *_args: [],
    )
    batch = run_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=4,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=True,
        max_total_credits=40,
        max_concurrency=2,
    )
    assert peak == 2
    assert batch["summary"] == {
        "requested": 4,
        "created": 4,
        "submitted": 3,
        "jobsSubmitted": 3,
        "completed": 3,
        "blocked": 0,
        "failed": 1,
        "approved": 3,
        "scheduled": 0,
        "published": 0,
        "uniqueOutputs": 3,
        "uniqueFinalOutputs": 3,
        "totalProviderCredits": 24.0,
        "providerCreditsReported": True,
        "quotedProviderCredits": 32.0,
        "generationTimesSeconds": [1.0, 1.0, 1.0],
    }


def test_cloud_batch_spend_cap_blocks_before_provider_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "campaign_factory.production_lane._OPERATOR_VISUAL_SELECTION_COMPLETE",
        True,
    )
    provider_called = False

    def block_quote(_factory, jobs, *, max_total_credits):
        raise PermissionError(
            "production_batch_quote_exceeds_total_credit_cap: 48 > 20"
        )

    def unexpected_provider(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError

    monkeypatch.setattr(
        "campaign_factory.production_lane._expand_production_job_prompt",
        lambda job: dict(job),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._authorize_higgsfield_jobs",
        block_quote,
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane._execute_higgsfield_provider_job",
        unexpected_provider,
    )
    with pytest.raises(PermissionError, match="exceeds_total_credit_cap"):
        run_production_batch(
            _production_factory(tmp_path),
            creator="stacey",
            intent="passive_selfie",
            count=6,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending",
            apply=True,
            max_total_credits=20,
        )
    assert provider_called is False


def test_passive_recipe_cannot_be_overridden_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_PASSIVE_VIDEO_RECIPE", "wavespeed_anything")
    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )
    assert (
        batch["jobs"][0]["productionRecipe"]["modelId"] == "higgsfield_kling3_turbo_i2v"
    )


def test_higgsfield_create_does_not_require_wavespeed_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    batch = run_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=2,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=False,
    )
    assert batch["provider"] == "higgsfield"
    assert batch["summary"]["created"] == 2
    assert batch["summary"]["submitted"] == 0


def test_higgsfield_failure_never_falls_back_to_wavespeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fail_higgsfield(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("higgsfield_failed")

    monkeypatch.setattr(
        "campaign_factory.production_lane._execute_higgsfield_provider_job",
        fail_higgsfield,
    )
    job = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )["jobs"][0]
    result = _run_production_job(
        _production_factory(tmp_path),
        job=job,
        audio_candidates=[],
        max_credits_per_job=10,
    )
    assert calls == 1
    assert result["status"] == "failed"
    assert result["error"] == "higgsfield_failed"
    assert result["providers"] == []


def test_qwen_expansion_is_bound_to_cloud_job_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts=None,
        audio_preference="embedded_trending",
    )["jobs"][0]
    expanded = (
        "She shifts her gaze toward the camera, tilts her head slightly, "
        "and adjusts one strand of hair while the handheld framing stays restrained."
    )
    monkeypatch.setattr(
        "reel_factory.worker_api.expand_local_wan_i2v_prompt",
        lambda **_kwargs: {
            "schema": "reel_factory.wan_prompt_expansion.v1",
            "expandedPrompt": expanded,
            "receiptFingerprint": "a" * 64,
        },
    )
    prepared = _expand_production_job_prompt(job)
    assert prepared["prompt"] == expanded
    assert (
        prepared["productionRecipe"]["expandedPromptSha256"]
        == hashlib.sha256(expanded.encode()).hexdigest()
    )


def test_duplicate_provider_output_is_blocked_without_erasing_first_completion() -> (
    None
):
    results = [
        {
            "jobId": "one",
            "index": 0,
            "status": "completed",
            "provider": {"outputSha256": "a" * 64},
            "hardQc": {"blockers": [], "status": "passed"},
        },
        {
            "jobId": "two",
            "index": 1,
            "status": "completed",
            "provider": {"outputSha256": "a" * 64},
            "hardQc": {"blockers": [], "status": "passed"},
        },
    ]
    _block_duplicate_provider_outputs(results)
    assert results[0]["status"] == "completed"
    assert results[1]["status"] == "blocked"
    assert results[1]["hardQc"]["blockers"] == ["duplicate_output"]


def test_golden_approved_asset_has_single_creative_authority() -> None:
    calibration_asset = {
        "metadata": {"schema": "campaign_factory.motion_generation_asset.v1"}
    }
    production_asset = {
        "metadata": {
            "schema": "campaign_factory.motion_generation_asset.v1",
            "humanReviewRequired": False,
            "creativeApprovalRequired": False,
            "productionMotionRecipe": {"status": "active"},
        }
    }
    assert asset_requires_creative_approval(calibration_asset) is True
    assert production_asset["metadata"]["creativeApprovalRequired"] is False
    quality = production_quality_policy()
    assert quality["softScoresBlockPublication"] is False
    assert "wrong_creator" in quality["hardBlockers"]


def test_golden_real_metrics_feed_future_learning() -> None:
    cutover = datetime(2026, 7, 1, tzinfo=UTC)
    snapshot = {
        "metrics_eligible": 1,
        "history_source": "metric_history",
        "published_at": "2026-07-24T00:00:00Z",
        "lineage_v2_valid": 1,
    }
    missing_metrics = {**snapshot, "metrics_eligible": 0}
    assert learning_eligible(snapshot, cutover=cutover) is True
    assert learning_eligible(missing_metrics, cutover=cutover) is False
