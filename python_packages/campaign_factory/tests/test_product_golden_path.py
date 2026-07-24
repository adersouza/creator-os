from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
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
from campaign_factory.production_lane import (
    plan_production_batch,
    run_production_batch,
)
from campaign_factory.production_quality_policy import production_quality_policy


def _production_factory(tmp_path: Path, *, source_count: int = 2) -> SimpleNamespace:
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
    conn.execute("INSERT INTO campaigns VALUES ('campaign-1', 'stacey-main', '2026')")
    conn.execute("INSERT INTO models VALUES ('model-1', 'stacey')")
    for index in range(source_count):
        path = tmp_path / f"approved-{index}.png"
        path.write_bytes(f"approved-source-{index}".encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        conn.execute(
            "INSERT INTO source_assets VALUES (?, 'campaign-1', 'model-1', ?, ?, "
            "'image', 'imported', ?)",
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


def test_golden_approved_source_to_generated_image_capability() -> None:
    plan = build_generation_execution_plan("soul_static")
    assert plan.still_strategy == "soul_reference_pair"
    assert "generated_image_qc" in plan.qc_requirements


def test_golden_approved_source_to_static_mp4_capability() -> None:
    plan = build_generation_execution_plan("soul_static")
    assert plan.motion_strategy == "static_mp4_only"
    assert plan.static_fallback_required is True


def test_golden_approved_source_to_animated_reel(tmp_path: Path) -> None:
    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="local",
        accounts="stacey-main",
        audio_preference="native_trending_required",
    )
    job = batch["jobs"][0]
    assert job["productionRecipe"]["modelId"] == "local_wan22_ti2v_5b_mlx"
    assert job["productionRecipe"]["researchSelectionRequired"] is False


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
    factory = _production_factory(tmp_path)
    video, audio = _fixture_media(tmp_path)
    monkeypatch.setattr(
        "campaign_factory.production_lane.run_generation_workflow",
        lambda *_args, **_kwargs: _fake_generation(factory, video),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane.discover_production_audio_candidates",
        lambda: [_fixture_candidate(audio)],
    )

    batch = run_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="local",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=True,
    )

    assert batch["summary"]["completed"] == 1
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
    factory = _production_factory(tmp_path)
    video, _audio = _fixture_media(tmp_path)
    monkeypatch.setattr(
        "campaign_factory.production_lane.run_generation_workflow",
        lambda *_args, **_kwargs: _fake_generation(factory, video),
    )
    monkeypatch.setattr(
        "campaign_factory.production_lane.discover_production_audio_candidates",
        lambda: [],
    )

    batch = run_production_batch(
        factory,
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="local",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=True,
    )

    assert batch["summary"]["blocked"] == 1
    assert batch["results"][0]["error"] == "NEEDS_EMBEDDED_AUDIO"
    assert batch["summary"]["published"] == 0


def test_golden_batch_request_has_independent_outputs(tmp_path: Path) -> None:
    batch = plan_production_batch(
        _production_factory(tmp_path),
        creator="stacey",
        intent="outfit",
        count=5,
        execution="local",
        accounts="stacey-main",
        audio_preference="native_trending_required",
    )
    jobs = batch["jobs"]
    assert len(jobs) == 5
    assert len({job["jobId"] for job in jobs}) == 5
    assert len({job["seed"] for job in jobs}) == 5
    assert len({job["sourceAssetId"] for job in jobs}) == 2


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
