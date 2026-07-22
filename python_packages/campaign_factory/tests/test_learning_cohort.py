from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.learning_cohort import (
    COHORT_ID,
    assign_learning_cohort_references,
    audit_learning_cohort,
    learning_cohort_assignment_metadata,
    prepare_learning_cohort,
    record_learning_cohort_approval,
    record_learning_cohort_draft,
    record_learning_cohort_generation,
    record_learning_cohort_publish,
    run_learning_cohort_day,
    sync_learning_cohort_metrics,
    sync_learning_cohort_publish_state,
)
from campaign_factory.lineage_v2 import build_lineage_v2_core, finalize_lineage_v2

from pipeline_contracts.validator import validate_contract


def _factory(tmp_path: Path) -> CampaignFactory:
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=tmp_path / "reel_factory",
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def _reference_ready(cf: CampaignFactory) -> None:
    cf.conn.execute(
        """UPDATE learning_cohort_assignments
        SET reference_id = 'stacey_ref', source_family = 'pattern_1',
            perceptual_cluster = 'cluster_1',
            content_fingerprint = id || '_fingerprint'"""
    )
    cf.conn.commit()


def test_prepare_is_fixed_balanced_and_idempotent(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        first = prepare_learning_cohort(
            cf.conn, start_date="2026-08-01", seed="fixed-seed"
        )
        second = prepare_learning_cohort(
            cf.conn, start_date="2026-09-01", seed="different-seed"
        )
        assert first["assignmentCount"] == 50
        assert first["rankedCount"] == 40
        assert first["controlCount"] == 10
        assert first["controlSurfaceCounts"] == {
            "regular_reel": 5,
            "trial_reel": 5,
        }
        assert second["idempotent"] is True
        rows = cf.conn.execute(
            """SELECT day_index, surface, scheduled_for FROM learning_cohort_assignments
            WHERE cohort_id = ? ORDER BY day_index, scheduled_for""",
            (COHORT_ID,),
        ).fetchall()
        for offset in range(0, 50, 2):
            early, late = rows[offset : offset + 2]
            assert (early["surface"] == "regular_reel") == (early["day_index"] % 2 == 1)
            gap = datetime.fromisoformat(
                late["scheduled_for"]
            ) - datetime.fromisoformat(early["scheduled_for"])
            assert gap.total_seconds() >= 6 * 3600
        assignment_id = cf.conn.execute(
            "SELECT id FROM learning_cohort_assignments ORDER BY day_index, surface LIMIT 1"
        ).fetchone()["id"]
        metadata = learning_cohort_assignment_metadata(cf.conn, assignment_id)
        validate_contract(metadata, "learning_cohort.v1.schema.json")
    finally:
        cf.close()


def test_run_day_is_idempotent_and_pauses_for_old_approval_backlog(
    tmp_path: Path,
) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        _reference_ready(cf)
        first = run_learning_cohort_day(cf.conn, day_index=1)
        second = run_learning_cohort_day(cf.conn, day_index=1)
        assert first["status"] == second["status"] == "queued_for_generation"
        assert {row["generationState"] for row in second["assignments"]} == {"queued"}
        cf.conn.execute(
            """UPDATE learning_cohort_assignments SET draft_id = 'draft_old'
            WHERE cohort_id = ? AND day_index = 1 AND surface = 'regular_reel'""",
            (COHORT_ID,),
        )
        cf.conn.commit()
        blocked = run_learning_cohort_day(cf.conn, day_index=4)
        assert blocked["status"] == "paused"
        assert "approval_backlog_exceeds_two_days" in blocked["blockingReasons"]
    finally:
        cf.close()


def test_reference_assignment_is_previewable_idempotent_and_identity_bound(
    tmp_path: Path,
) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        now = "2026-07-11T00:00:00Z"
        cf.conn.execute(
            """INSERT INTO reference_patterns
            (id, cluster_key, rank, label, imported_at, updated_at)
            VALUES ('pattern_1', 'cluster_1', 1, 'Pattern 1', ?, ?)""",
            (now, now),
        )
        cf.conn.execute(
            """INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, created_at, updated_at)
            VALUES ('plan_1', ?, 'pattern_1', ?, ?)""",
            (campaign_id, now, now),
        )
        cf.conn.commit()
        source = tmp_path / "stacey.png"
        source.write_bytes(b"stacey")
        manifest = tmp_path / "stacey.json"
        manifest.write_text(
            __import__("json").dumps(
                {
                    "creator": "Stacey",
                    "status": "ready",
                    "referenceSetId": "stacey_set",
                    "sourceImages": [
                        {
                            "path": str(source),
                            "sha256": "a" * 64,
                            "status": "embedded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        preview = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest
        )
        assert preview["dryRun"] is True
        assert preview["changes"] == 50
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM learning_cohort_assignments WHERE reference_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        applied = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest, apply=True
        )
        repeat = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest
        )
        assert applied["changes"] == 50
        assert repeat["changes"] == 0
        assert (
            run_learning_cohort_day(cf.conn, day_index=1)["status"]
            == "queued_for_generation"
        )
    finally:
        cf.close()


def test_run_day_blocks_when_reference_assignment_is_missing(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        result = run_learning_cohort_day(cf.conn, day_index=1)
        assert result["status"] == "paused"
        assert "reference_assignment_missing" in result["blockingReasons"]
    finally:
        cf.close()


def test_real_artifact_draft_approval_and_publish_transitions(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        _reference_ready(cf)
        run_learning_cohort_day(cf.conn, day_index=1)
        assignment = dict(
            cf.conn.execute(
                """SELECT * FROM learning_cohort_assignments
                WHERE day_index = 1 AND surface = 'regular_reel'"""
            ).fetchone()
        )
        model = cf.domains.models.upsert_model("stacey")
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        artifact = tmp_path / "approved.mp4"
        artifact.write_bytes(b"real-rendered-artifact")
        now = "2026-07-11T00:00:00+00:00"
        cf.conn.execute(
            """INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, source_prompt, created_at, updated_at)
            VALUES ('source_1', ?, ?, 'source_hash', ?, ?, 'approved.mp4', '{}', ?, ?)""",
            (campaign_id, model["id"], str(artifact), str(artifact), now, now),
        )
        cf.conn.execute(
            """INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, caption, caption_hash, recipe,
             created_at, updated_at)
            VALUES ('asset_1', ?, 'source_1', 'render_hash', ?, ?, 'approved.mp4',
             'caption', 'caption_hash', 'finished_video_registered', ?, ?)""",
            (campaign_id, str(artifact), str(artifact), now, now),
        )
        cf.conn.commit()
        lineage = build_lineage_v2_core(
            {
                "source": {
                    "promptId": "prompt_1",
                    "referenceId": assignment["reference_id"],
                },
                "generation": {"tool": "reel_factory.reel_pipeline"},
                "review": {"humanReviewRequired": True},
            },
            campaign_id=campaign_id,
            recipe_id="finished_video_registered",
            caption_hash="caption_hash",
            rendered_asset_id="asset_1",
            content_fingerprint=assignment["content_fingerprint"],
        )
        lineage["sourceFamilyId"] = assignment["source_family"]
        lineage["perceptualClusterId"] = assignment["perceptual_cluster"]
        lineage = finalize_lineage_v2(
            lineage,
            audio_intent={
                "schema": "pipeline.audio_intent.v1",
                "mode": "native_trending_audio",
            },
            variant_assignment=None,
        )
        lineage_path = tmp_path / "lineage.json"
        lineage_path.write_text(__import__("json").dumps(lineage), encoding="utf-8")

        generation = record_learning_cohort_generation(
            cf.conn,
            assignment_id=assignment["id"],
            rendered_asset_id="asset_1",
            lineage_path=lineage_path,
            artifact_path=artifact,
            provider_reservation_id="reservation_1",
        )
        assert generation["generationState"] == "complete"
        source_prompt = __import__("json").loads(
            cf.conn.execute(
                "SELECT source_prompt FROM source_assets WHERE id = 'source_1'"
            ).fetchone()["source_prompt"]
        )
        assert source_prompt["generatedAssetLineage"]["renderedAssetId"] == "asset_1"
        assert artifact.with_suffix(".mp4.generated_asset_lineage.json").is_file()

        bad_lineage = dict(lineage)
        bad_lineage["source"] = {**lineage["source"], "referenceId": "wrong_ref"}
        bad_path = tmp_path / "bad-lineage.json"
        bad_path.write_text(__import__("json").dumps(bad_lineage), encoding="utf-8")
        with pytest.raises(ValueError, match="referenceId"):
            record_learning_cohort_generation(
                cf.conn,
                assignment_id=assignment["id"],
                rendered_asset_id="asset_1",
                lineage_path=bad_path,
                artifact_path=artifact,
            )

        draft = record_learning_cohort_draft(
            cf.conn, assignment_id=assignment["id"], draft_id="draft_1"
        )
        assert draft["generationState"] == "draft_ingested"
        approved = record_learning_cohort_approval(
            cf.conn, assignment_id=assignment["id"], decision="approved"
        )
        assert approved["scheduleState"] == "ready_for_manual_publish"
        published = record_learning_cohort_publish(
            cf.conn,
            assignment_id=assignment["id"],
            post_id="post_1",
            published_at="2026-07-11T12:00:00-04:00",
        )
        assert published["publishState"] == "published"
        assert published["publishedAt"] == "2026-07-11T12:00:00-04:00"
    finally:
        cf.close()


def test_audit_requires_complete_evidence_and_computes_lift(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assert audit_learning_cohort(cf.conn)["passed"] is False
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET metric_1h_state = 'complete', metric_24h_state = 'complete',
                metric_72h_state = CASE WHEN surface = 'trial_reel'
                  THEN 'complete' ELSE 'not_required' END,
                reward_24h = CASE WHEN arm = 'ranked' THEN 120.0 ELSE 100.0 END"""
        )
        cf.conn.commit()
        result = audit_learning_cohort(cf.conn)
        assert result["passed"] is True
        assert result["lift"]["overallLift"] == 0.2
        assert result["lift"]["bootstrapPositiveConfidence"] == 1.0
    finally:
        cf.close()


def test_review_ready_library_asset_can_record_review_draft(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assignment = cf.conn.execute(
            "SELECT id FROM learning_cohort_assignments ORDER BY day_index LIMIT 1"
        ).fetchone()
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET rendered_asset_id = 'asset_review_ready',
                generation_state = 'review_ready'
            WHERE id = ?""",
            (assignment["id"],),
        )
        cf.conn.commit()

        draft = record_learning_cohort_draft(
            cf.conn,
            assignment_id=assignment["id"],
            draft_id="draft_review_only",
        )

        assert draft["draftId"] == "draft_review_only"
        assert draft["generationState"] == "draft_ingested"
        assert draft["scheduleState"] == "blocked_pending_approval"
    finally:
        cf.close()


def test_metric_sync_writes_real_windows_reward_and_retracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2026-07-01T00:00:00Z")
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assignment = dict(
            cf.conn.execute(
                """SELECT * FROM learning_cohort_assignments
                WHERE surface = 'trial_reel' ORDER BY day_index LIMIT 1"""
            ).fetchone()
        )
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET post_id = 'post_metric_sync', published_at = ?,
                publish_state = 'published'
            WHERE id = ?""",
            ("2026-07-10T12:00:00Z", assignment["id"]),
        )
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        for hour, views, likes in ((1.0, 100, 5), (24.0, 1000, 100), (72.0, 1500, 120)):
            cf.conn.execute(
                """INSERT INTO performance_snapshots
                (id, campaign_id, post_id, published_at, snapshot_at, views,
                 likes, comments, shares, saves, reach, metrics_eligible,
                 history_source, lineage_v2_valid, raw_json, created_at)
                VALUES (?, ?, 'post_metric_sync', ?, ?, ?, ?, 10, 5, 2, ?,
                        1, 'metric_history', 1, ?, ?)""",
                (
                    f"snapshot_{int(hour)}",
                    campaign_id,
                    "2026-07-10T12:00:00Z",
                    f"2026-07-{10 + int(hour // 24):02d}T12:00:00Z",
                    views,
                    likes,
                    views,
                    __import__("json").dumps(
                        {
                            "metadata": {
                                "threadsdash_metric_history": {
                                    "hoursSincePublish": hour
                                }
                            }
                        }
                    ),
                    "2026-07-11T00:00:00Z",
                ),
            )
        cf.conn.commit()

        first = sync_learning_cohort_metrics(cf.conn)
        second = sync_learning_cohort_metrics(cf.conn)
        row = dict(
            cf.conn.execute(
                "SELECT * FROM learning_cohort_assignments WHERE id = ?",
                (assignment["id"],),
            ).fetchone()
        )
        assert first["assignmentsChanged"] == 1
        assert second["assignmentsChanged"] == 0
        assert row["metric_1h_state"] == "complete"
        assert row["metric_24h_state"] == "complete"
        assert row["metric_72h_state"] == "complete"
        assert row["reward_24h"] == pytest.approx(
            __import__("math").log1p(1000) * 0.117
        )

        cf.conn.execute("DELETE FROM performance_snapshots WHERE id = 'snapshot_24'")
        cf.conn.commit()
        retracted = sync_learning_cohort_metrics(cf.conn)
        row = dict(
            cf.conn.execute(
                "SELECT * FROM learning_cohort_assignments WHERE id = ?",
                (assignment["id"],),
            ).fetchone()
        )
        assert retracted["assignmentsChanged"] == 1
        assert row["metric_24h_state"] == "pending"
        assert row["reward_24h"] is None
    finally:
        cf.close()


def test_publish_sync_repairs_notify_handoff_before_metric_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2026-07-01T00:00:00Z")
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assignment = dict(
            cf.conn.execute(
                """SELECT * FROM learning_cohort_assignments
                WHERE surface = 'trial_reel' ORDER BY day_index LIMIT 1"""
            ).fetchone()
        )
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET draft_id = 'threadsdash_post_1', rendered_asset_id = 'asset_1',
                approval_state = 'approved', generation_state = 'draft_ingested'
            WHERE id = ?""",
            (assignment["id"],),
        )
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        cf.conn.execute(
            """INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, post_id, platform, status,
             published_at, snapshot_at, views, likes, comments, shares, saves,
             reach, metrics_eligible, history_source, lineage_v2_valid, raw_json,
             created_at)
            VALUES ('snapshot_1h', ?, 'asset_1', 'threadsdash_post_1',
             'instagram', 'published', '2026-07-11T18:54:35+00:00',
             '2026-07-11T19:59:56+00:00', 2, 0, 0, 0, 0, 1, 1,
             'metric_history', 1, ?, '2026-07-11T19:59:56+00:00')""",
            (
                campaign_id,
                __import__("json").dumps(
                    {
                        "metadata": {
                            "trialGroupId": assignment["id"],
                            "threadsdash_metric_history": {"hoursSincePublish": 1.09},
                        }
                    }
                ),
            ),
        )
        cf.conn.commit()

        publish_first = sync_learning_cohort_publish_state(cf.conn)
        metric_first = sync_learning_cohort_metrics(cf.conn)
        publish_second = sync_learning_cohort_publish_state(cf.conn)
        row = dict(
            cf.conn.execute(
                "SELECT * FROM learning_cohort_assignments WHERE id = ?",
                (assignment["id"],),
            ).fetchone()
        )

        assert publish_first["status"] == "synced"
        assert publish_first["assignmentsChanged"] == 1
        assert publish_second["assignmentsChanged"] == 0
        assert metric_first["assignmentsChanged"] == 1
        assert row["post_id"] == "threadsdash_post_1"
        assert row["publish_state"] == "published"
        assert row["schedule_state"] == "published"
        assert row["metric_1h_state"] == "complete"
    finally:
        cf.close()


def test_publish_sync_fails_closed_on_asset_or_assignment_conflict(
    tmp_path: Path,
) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assignment = dict(
            cf.conn.execute(
                """SELECT * FROM learning_cohort_assignments
                WHERE surface = 'trial_reel' ORDER BY day_index LIMIT 1"""
            ).fetchone()
        )
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET draft_id = 'threadsdash_post_1', rendered_asset_id = 'asset_1',
                approval_state = 'approved', generation_state = 'draft_ingested'
            WHERE id = ?""",
            (assignment["id"],),
        )
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        cf.conn.execute(
            """INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, post_id, platform, status,
             published_at, snapshot_at, metrics_eligible, history_source,
             lineage_v2_valid, raw_json, created_at)
            VALUES ('snapshot_conflict', ?, 'wrong_asset', 'threadsdash_post_1',
             'instagram', 'published', '2026-07-11T18:54:35+00:00',
             '2026-07-11T19:59:56+00:00', 1, 'metric_history', 1, ?,
             '2026-07-11T19:59:56+00:00')""",
            (
                campaign_id,
                __import__("json").dumps(
                    {"metadata": {"trialGroupId": "another_assignment"}}
                ),
            ),
        )
        cf.conn.commit()

        result = sync_learning_cohort_publish_state(cf.conn)
        row = dict(
            cf.conn.execute(
                "SELECT * FROM learning_cohort_assignments WHERE id = ?",
                (assignment["id"],),
            ).fetchone()
        )

        assert result["status"] == "conflict"
        assert result["assignmentsChanged"] == 0
        assert result["conflicts"][0]["blockingReasons"] == [
            "rendered_asset_mismatch",
            "cohort_assignment_metadata_mismatch",
        ]
        assert row["post_id"] is None
        assert row["publish_state"] == "not_published"
    finally:
        cf.close()


def test_metric_sync_fails_closed_without_learning_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEARNING_LOOP_CUTOVER", raising=False)
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        result = sync_learning_cohort_metrics(cf.conn)
        assert result["status"] == "blocked_cutover_unset"
        assert result["assignmentsChanged"] == 0
    finally:
        cf.close()
