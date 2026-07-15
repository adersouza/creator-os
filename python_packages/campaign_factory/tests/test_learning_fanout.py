from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from campaign_factory.db import connect, init_db
from reel_factory.metrics_store import connect_metrics_db, ensure_metrics_schema
from reference_factory.db import connect as connect_reference_db
from reference_factory.learning import learning_summary as reference_learning_summary

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_PATH = REPO_ROOT / "scripts" / "learning_fanout.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("learning_fanout", BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_learning_databases(
    tmp_path: Path, *, prompt_ids: tuple[str, ...] = ("prompt_1",)
):
    campaign_db = tmp_path / "campaign.sqlite"
    reel_root = tmp_path / "reel"
    reference_db = tmp_path / "references" / "reference_factory.sqlite"
    reel_root.mkdir()
    output_path = reel_root / "asset_1.mp4"
    output_path.write_bytes(b"video")
    now = "2026-01-01T00:00:00+00:00"

    campaign_conn = connect(campaign_db)
    init_db(campaign_conn)
    campaign_conn.execute(
        "INSERT INTO campaigns VALUES ('campaign_1', 'may', 'May', 'instagram', ?, ?, ?)",
        (str(tmp_path / "may"), now, now),
    )
    campaign_conn.execute(
        "INSERT INTO models (id, slug, name, created_at, updated_at) VALUES ('model_1', 'model', 'Model', ?, ?)",
        (now, now),
    )
    campaign_conn.execute(
        """
        INSERT INTO source_assets (
          id, campaign_id, model_id, content_hash, original_path, stored_path,
          filename, source_prompt, created_at, updated_at
        ) VALUES ('source_1', 'campaign_1', 'model_1', 'source_hash', ?, ?,
                  'source.mp4', '{}', ?, ?)
        """,
        (str(tmp_path / "source.mp4"), str(tmp_path / "source.mp4"), now, now),
    )
    campaign_conn.execute(
        """
        INSERT INTO rendered_assets (
          id, campaign_id, source_asset_id, content_hash, output_path,
          campaign_path, filename, caption, caption_hash, recipe,
          review_state, created_at, updated_at
        ) VALUES ('asset_1', 'campaign_1', 'source_1', 'render_hash', ?, ?,
                  'asset_1.mp4', 'caption', 'caption_hash', 'recipe_1',
                  'approved', ?, ?)
        """,
        (str(output_path), str(output_path), now, now),
    )
    campaign_conn.commit()
    campaign_conn.close()

    reference_conn = connect_reference_db(reference_db)
    reference_conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, file_name, extension, kind, size_bytes, mtime,
          path_hash, created_at, updated_at
        ) VALUES ('reference_1', ?, 'reference.mp4', '.mp4', 'video', 1, ?,
                  'path_hash', ?, ?)
        """,
        (str(tmp_path / "reference.mp4"), now, now, now),
    )
    for prompt_id in prompt_ids:
        reference_conn.execute(
            """
            INSERT INTO generated_video_prompts (
              id, reference_id, target_tool, model_profile, prompt_json,
              status, created_at, updated_at
            ) VALUES (?, 'reference_1', 'higgsfield', ?, '{}', 'approved', ?, ?)
            """,
            (prompt_id, prompt_id, now, now),
        )
    reference_conn.commit()
    reference_conn.close()

    reel_conn = connect_metrics_db(reel_root / "manifest.sqlite")
    ensure_metrics_schema(reel_conn)
    reel_conn.close()
    return campaign_db, reel_root, reference_db, output_path


def insert_snapshot(
    campaign_db: Path,
    *,
    snapshot_id: str,
    snapshot_at: str,
    hours: int,
    prompt_id: str = "prompt_1",
    post_id: str = "post_1",
    views: int = 100,
    lineage_v2_valid: int = 1,
    history_source: str = "metric_history",
    reference_id: str = "reference_1",
    source_lineage_path: Path | None = None,
    pattern_reference_ids: list[str] | None = None,
    lineage_features: dict[str, str] | None = None,
) -> None:
    raw = {
        "metadata": {
            "threadsdash_metric_history": {"hoursSincePublish": hours},
            "campaign_factory": {
                "campaign_id": "may",
                "rendered_asset_id": "asset_1",
                "caption_hash": "caption_hash",
                "recipe": "recipe_1",
                "generated_asset_lineage": {
                    "schema": "reel_factory.generated_asset_lineage.v2",
                    "campaignId": "may",
                    "recipeId": "recipe_1",
                    "captionHash": "caption_hash",
                    "renderedAssetId": "asset_1",
                    "variationApplied": False,
                    "variantId": None,
                    "audioIntentFingerprint": "a" * 64,
                    "pipelineTraceId": "trace_1",
                    "source": {
                        "promptId": prompt_id,
                        "referenceId": reference_id,
                        "sourceLineagePath": str(source_lineage_path)
                        if source_lineage_path
                        else None,
                    },
                    "generation": {"tool": "higgsfield"},
                    "review": {"status": "approved"},
                    "features": lineage_features or {},
                },
                "reference_pattern": {
                    "id": "pattern_cluster_1",
                    "referenceIds": pattern_reference_ids or [],
                },
            },
        }
    }
    conn = connect(campaign_db)
    conn.execute(
        """
        INSERT INTO performance_snapshots (
          id, campaign_id, rendered_asset_id, source_asset_id, caption_hash,
          recipe, post_id, platform, status, instagram_account_id, published_at,
          snapshot_at, views, likes, comments, shares, saves, reach,
          watch_time_seconds, metrics_eligible, history_source, lineage_v2_valid,
          raw_json, created_at
        ) VALUES (?, 'campaign_1', 'asset_1', 'source_1', 'caption_hash',
                  'recipe_1', ?, 'instagram', 'published', 'ig_1',
                  '2026-01-02T00:00:00+00:00', ?, ?, 10, 2, 3, 4, ?, 20.0,
                  1, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            post_id,
            snapshot_at,
            views,
            views,
            history_source,
            lineage_v2_valid,
            json.dumps(raw, sort_keys=True),
            snapshot_at,
        ),
    )
    conn.commit()
    conn.close()


def run_bridge(module, campaign_db, reel_root, reference_db, *, max_attempts=5):
    return module.fanout_learning_snapshots(
        campaign_factory_db=campaign_db,
        reel_factory_root=reel_root,
        reference_factory_db=reference_db,
        campaign="may",
        max_attempts=max_attempts,
    )


def test_fanout_accepts_canonical_reel_manifest_path(tmp_path: Path) -> None:
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)

    result = module.fanout_learning_snapshots(
        campaign_factory_db=campaign_db,
        reel_manifest_db=reel_root / "manifest.sqlite",
        reference_factory_db=reference_db,
        campaign="may",
    )

    assert result["schema"] == "creator_os.learning_fanout.v1"
    assert result["reelWinnerDnaRefresh"]["rows"] == 0


def test_fanout_double_run_is_noop_and_keeps_exact_snapshot_keys(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_1h",
        snapshot_at="2026-01-02T01:05:00+00:00",
        hours=1,
        views=100,
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_24h",
        snapshot_at="2026-01-03T00:45:00+00:00",
        hours=24,
        views=500,
    )

    first = run_bridge(module, campaign_db, reel_root, reference_db)
    second = run_bridge(module, campaign_db, reel_root, reference_db)

    assert first["fanout"]["campaign"]["done"] == 2
    assert first["fanout"]["reel"]["done"] == 1
    assert first["fanout"]["reference"]["done"] == 1
    assert second["fanout"]["campaign"]["done"] == 0
    assert second["fanout"]["reel"]["done"] == 0
    assert second["fanout"]["reference"]["done"] == 0
    assert second["ledgerStates"] == {
        "campaign": {"done": 2},
        "reel": {"done": 1, "superseded": 1},
        "reference": {"done": 1, "superseded": 1},
    }
    conn = connect(campaign_db)
    keys = conn.execute(
        "SELECT DISTINCT snapshot_at FROM learning_fanout_ledger ORDER BY snapshot_at"
    ).fetchall()
    assert [row["snapshot_at"] for row in keys] == [
        "2026-01-02T01:05:00+00:00",
        "2026-01-03T00:45:00+00:00",
    ]
    assert (
        conn.execute("SELECT COUNT(*) FROM learning_fanout_ledger").fetchone()[0] == 6
    )
    conn.close()
    reference_conn = connect_reference_db(reference_db)
    fact = reference_conn.execute("SELECT * FROM prompt_post_outcomes").fetchone()
    assert fact["post_id"] == "post_1"
    assert fact["source_snapshot_at"] == "2026-01-03T00:45:00+00:00"
    assert (
        reference_conn.execute(
            "SELECT outcome_sample_count FROM generated_video_prompts WHERE id = 'prompt_1'"
        ).fetchone()[0]
        == 1
    )
    reference_conn.close()


def test_two_snapshots_same_hour_get_distinct_destination_ledgers(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_same_hour_1",
        snapshot_at="2026-01-03T10:05:00+00:00",
        hours=24,
        views=400,
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_same_hour_2",
        snapshot_at="2026-01-03T10:45:00+00:00",
        hours=25,
        views=500,
    )

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    conn = connect(campaign_db)
    rows = conn.execute(
        """
        SELECT snapshot_at, destination, status
        FROM learning_fanout_ledger
        ORDER BY snapshot_at, destination
        """
    ).fetchall()
    assert len(rows) == 6
    assert {row["snapshot_at"] for row in rows} == {
        "2026-01-03T10:05:00+00:00",
        "2026-01-03T10:45:00+00:00",
    }
    assert result["ledgerStates"] == {
        "campaign": {"done": 2},
        "reel": {"done": 1, "superseded": 1},
        "reference": {"done": 1, "superseded": 1},
    }
    conn.close()


def test_reference_identity_change_replaces_old_prompt_without_orphan(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(
        tmp_path, prompt_ids=("prompt_1", "prompt_2")
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_latest",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
    )
    run_bridge(module, campaign_db, reel_root, reference_db)

    conn = connect(campaign_db)
    row = conn.execute(
        "SELECT raw_json FROM performance_snapshots WHERE id = 'snap_latest'"
    ).fetchone()
    raw = json.loads(row["raw_json"])
    raw["metadata"]["campaign_factory"]["generated_asset_lineage"]["source"][
        "promptId"
    ] = "prompt_2"
    conn.execute(
        "UPDATE performance_snapshots SET raw_json = ? WHERE id = 'snap_latest'",
        (json.dumps(raw, sort_keys=True),),
    )
    conn.commit()
    conn.close()

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    assert result["fanout"]["reference"]["reopenedByHash"] == 1
    assert result["fanout"]["reference"]["done"] == 1
    reference_conn = connect_reference_db(reference_db)
    facts = reference_conn.execute(
        "SELECT prompt_id, post_id FROM prompt_post_outcomes"
    ).fetchall()
    assert [tuple(row) for row in facts] == [("prompt_2", "post_1")]
    assert (
        reference_conn.execute(
            "SELECT outcome_sample_count FROM generated_video_prompts WHERE id = 'prompt_1'"
        ).fetchone()[0]
        == 0
    )
    reference_conn.close()


def test_eligible_to_ineligible_retracts_and_restores_previous_snapshot(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_old",
        snapshot_at="2026-01-02T01:00:00+00:00",
        hours=1,
        views=100,
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_new",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
        views=500,
    )
    run_bridge(module, campaign_db, reel_root, reference_db)
    conn = connect(campaign_db)
    conn.execute(
        "UPDATE performance_snapshots SET lineage_v2_valid = 0 WHERE id = 'snap_new'"
    )
    conn.commit()
    conn.close()

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    assert result["fanout"]["reference"]["retracted"] == 1
    assert result["fanout"]["reel"]["retracted"] == 1
    reference_conn = connect_reference_db(reference_db)
    fact = reference_conn.execute("SELECT * FROM prompt_post_outcomes").fetchone()
    assert fact["source_snapshot_at"] == "2026-01-02T01:00:00+00:00"
    reference_conn.close()
    reel_conn = connect_metrics_db(reel_root / "manifest.sqlite")
    outcome = reel_conn.execute("SELECT * FROM reel_outcomes").fetchone()
    metric = reel_conn.execute("SELECT * FROM publish_metrics").fetchone()
    assert outcome["source_snapshot_at"] == "2026-01-02T01:00:00+00:00"
    assert metric["source_snapshot_at"] == "2026-01-02T01:00:00+00:00"
    reel_conn.close()


def test_soft_skip_retries_caps_and_hash_change_reopens(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_missing_prompt",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
        prompt_id="missing_prompt",
    )

    first = run_bridge(module, campaign_db, reel_root, reference_db, max_attempts=2)
    second = run_bridge(module, campaign_db, reel_root, reference_db, max_attempts=2)
    assert first["fanout"]["reference"]["pending"] == 1
    assert second["fanout"]["reference"]["retryCapped"] == 1
    assert second["ledgerStates"]["reference"] == {"failed_capped": 1}
    conn = connect(campaign_db)
    ledger = conn.execute(
        "SELECT * FROM learning_fanout_ledger WHERE destination = 'reference'"
    ).fetchone()
    assert ledger["status"] == "failed_capped"
    assert ledger["attempt_count"] == 2
    raw = json.loads(
        conn.execute(
            "SELECT raw_json FROM performance_snapshots WHERE id = 'snap_missing_prompt'"
        ).fetchone()[0]
    )
    raw["metadata"]["campaign_factory"]["generated_asset_lineage"]["source"][
        "sourceLineagePath"
    ] = "/tmp/recovered.direct_reference_lineage.json"
    conn.execute(
        "UPDATE performance_snapshots SET raw_json = ? WHERE id = 'snap_missing_prompt'",
        (json.dumps(raw, sort_keys=True),),
    )
    conn.commit()
    conn.close()

    third = run_bridge(module, campaign_db, reel_root, reference_db, max_attempts=2)
    assert third["fanout"]["reference"]["reopenedByHash"] == 1
    conn = connect(campaign_db)
    ledger = conn.execute(
        "SELECT * FROM learning_fanout_ledger WHERE destination = 'reference'"
    ).fetchone()
    assert ledger["status"] == "pending"
    assert ledger["attempt_count"] == 1
    conn.close()


def test_missing_prompt_registers_from_real_lineage_before_reference_fanout(
    tmp_path: Path,
) -> None:
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(
        tmp_path, prompt_ids=()
    )
    output_path = tmp_path / "observed.png"
    output_path.write_bytes(b"observed-output")
    identity_path = tmp_path / "identity.png"
    identity_path.write_bytes(b"identity-reference")
    captured_prompt = "Captured provider prompt from the immutable lineage artifact."
    prompt_sha = hashlib.sha256(captured_prompt.encode()).hexdigest()
    prompt_id = f"prompt_higgsfield_{prompt_sha[:16]}"
    lineage_path = tmp_path / "observed.direct_reference_lineage.json"
    lineage_path.write_text(
        json.dumps(
            {
                "source": {"referenceImage": str(identity_path)},
                "generation": {
                    "imageJobId": "job_observed",
                    "capturedHiggsfieldPrompt": captured_prompt,
                    "models": {"image": "text2image_soul_v2"},
                    "params": {"imageAspectRatio": "9:16"},
                },
                "assets": {"localPaths": {"image": str(output_path)}},
            }
        ),
        encoding="utf-8",
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_observed",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
        prompt_id=prompt_id,
        reference_id="identity_set:file_1",
        source_lineage_path=lineage_path,
        pattern_reference_ids=["reference_1"],
        lineage_features={
            "scene": "bedroom",
            "camera": "mirror_selfie",
            "creator": "stacey",
            "motion": "slow_pan",
        },
    )

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    assert result["fanout"]["reference"]["done"] == 1
    assert result["reelWinnerDnaRefresh"]["rows"] == 4
    conn = connect_reference_db(reference_db)
    prompt = conn.execute(
        "SELECT status FROM generated_video_prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    outcome = conn.execute(
        "SELECT post_id FROM prompt_post_outcomes WHERE prompt_id = ?", (prompt_id,)
    ).fetchone()
    link = conn.execute(
        """
        SELECT reference_id FROM generated_prompt_reference_links
        WHERE prompt_id = ? AND role = 'pattern_member'
        """,
        (prompt_id,),
    ).fetchone()
    assert prompt["status"] == "outcome_observed"
    assert outcome["post_id"] == "post_1"
    assert link["reference_id"] == "reference_1"
    conn.close()
    reel_conn = connect_metrics_db(reel_root / "manifest.sqlite")
    feature = reel_conn.execute(
        "SELECT scene, camera, creator, motion FROM reel_features"
    ).fetchone()
    winner_rows = reel_conn.execute(
        "SELECT feature_key, feature_value FROM winner_dna ORDER BY feature_key"
    ).fetchall()
    assert tuple(feature) == ("bedroom", "mirror_selfie", "stacey", "slow_pan")
    assert [tuple(row) for row in winner_rows] == [
        ("camera", "mirror_selfie"),
        ("creator", "stacey"),
        ("motion", "slow_pan"),
        ("scene", "bedroom"),
    ]
    reel_conn.close()

    campaign_conn = connect(campaign_db)
    snapshot = campaign_conn.execute(
        "SELECT raw_json FROM performance_snapshots WHERE id = 'snap_observed'"
    ).fetchone()
    raw = json.loads(snapshot["raw_json"])
    raw["metadata"]["campaign_factory"]["generated_asset_lineage"]["features"][
        "hook_type"
    ] = "curiosity"
    campaign_conn.execute(
        "UPDATE performance_snapshots SET raw_json = ? WHERE id = 'snap_observed'",
        (json.dumps(raw, sort_keys=True),),
    )
    campaign_conn.commit()
    campaign_conn.close()

    rerun = run_bridge(module, campaign_db, reel_root, reference_db)

    assert rerun["fanout"]["reel"]["reopenedByHash"] == 1
    assert rerun["fanout"]["reel"]["done"] == 1
    assert rerun["fanout"]["campaign"]["reopenedByHash"] == 0
    assert rerun["fanout"]["reference"]["reopenedByHash"] == 0
    assert rerun["reelWinnerDnaRefresh"]["rows"] == 5
    reel_conn = connect_metrics_db(reel_root / "manifest.sqlite")
    assert (
        reel_conn.execute("SELECT hook_type FROM reel_features").fetchone()["hook_type"]
        == "curiosity"
    )
    reel_conn.close()


def test_fallback_and_pre_cutover_rows_never_receive_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_fallback",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
        history_source="post_row_fallback",
    )
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_pre_cutover",
        snapshot_at="2026-01-04T00:00:00+00:00",
        hours=48,
        post_id="post_2",
    )
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2026-02-01T00:00:00+00:00")

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    assert result["eligibleSnapshots"] == 0
    assert result["fallbackRows"] == 1
    conn = connect(campaign_db)
    assert (
        conn.execute("SELECT COUNT(*) FROM learning_fanout_ledger").fetchone()[0] == 0
    )
    conn.close()


def test_snapshot_fanout_refreshes_pattern_and_changes_cluster_order(tmp_path: Path):
    module = load_bridge_module()
    campaign_db, reel_root, reference_db, _ = setup_learning_databases(tmp_path)
    reference_conn = connect_reference_db(reference_db)
    now = "2026-01-01T00:00:00+00:00"
    reference_conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, file_name, extension, kind, size_bytes, mtime,
          path_hash, created_at, updated_at
        ) VALUES ('reference_2', ?, 'reference_2.mp4', '.mp4', 'video', 1, ?,
                  'hash_2', ?, ?)
        """,
        (str(tmp_path / "reference_2.mp4"), now, now, now),
    )
    for reference_id, quality, visual in (
        ("reference_1", 60, "mirror_selfie"),
        ("reference_2", 75, "bedroom_pose"),
    ):
        pattern = {
            "visualFormat": visual,
            "hookType": "viewer_insert",
            "performanceClass": "unproven",
            "metrics": {"measuredOutcome": None},
            "winnerDna": {"performanceClass": "unproven"},
        }
        reference_conn.execute(
            """
            INSERT INTO reference_patterns (
              id, reference_id, rank, provider, analyzer_version, suggested_label,
              visual_format, hook_type, caption_archetype, quality_score,
              pattern_json, created_at, updated_at
            ) VALUES (?, ?, 1, 'heuristic', 'test', 'maybe', ?, 'viewer_insert',
                      'question_hook', ?, ?, ?, ?)
            """,
            (
                f"pattern_{reference_id}",
                reference_id,
                visual,
                quality,
                json.dumps(pattern),
                now,
                now,
            ),
        )
    reference_conn.commit()
    before = reference_learning_summary(reference_conn, limit=10)
    assert before["topClusters"][0]["topReferenceId"] == "reference_2"
    reference_conn.close()
    insert_snapshot(
        campaign_db,
        snapshot_id="snap_pattern",
        snapshot_at="2026-01-03T00:00:00+00:00",
        hours=24,
        views=100,
    )

    result = run_bridge(module, campaign_db, reel_root, reference_db)

    assert result["referencePatternRefresh"]["patternsChanged"] == 1
    reference_conn = connect_reference_db(reference_db)
    refreshed = json.loads(
        reference_conn.execute(
            "SELECT pattern_json FROM reference_patterns WHERE reference_id = 'reference_1'"
        ).fetchone()[0]
    )
    after = reference_learning_summary(reference_conn, limit=10)
    assert refreshed["performanceClass"] == "performed_well"
    assert after["topClusters"][0]["topReferenceId"] == "reference_1"
    reference_conn.close()
