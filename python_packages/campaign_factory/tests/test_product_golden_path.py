from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from campaign_factory.audio_policy import build_motion_audio_intent
from campaign_factory.creative_approval import asset_requires_creative_approval
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.learning_score import learning_eligible
from campaign_factory.production_lane import plan_production_batch
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
