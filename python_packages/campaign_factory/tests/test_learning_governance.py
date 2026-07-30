from __future__ import annotations

import json
import sqlite3

import pytest
from campaign_factory.db import init_db
from campaign_factory.learning_governance import (
    append_learning_governance_revision,
    canonical_learning_eligibility,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    now = "2026-07-30T00:00:00Z"
    conn.execute(
        """
        INSERT INTO models(id, slug, name, created_at, updated_at)
        VALUES ('model_1', 'creator-1', 'Creator 1', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state(
          model_id, status, status_reason, effective_at, changed_by, version,
          retention_state, updated_at
        ) VALUES (
          'model_1', 'active', 'fixture', ?, 'test', 1, 'retain_audit', ?
        )
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaigns(id, slug, name, root_path, created_at, updated_at)
        VALUES ('campaign_1', 'campaign-1', 'Campaign 1', '/tmp/campaign-1', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance(
          campaign_id, model_id, lifecycle_status, blocker_codes_json,
          status_reason, changed_by, effective_at, version, updated_at
        ) VALUES (
          'campaign_1', 'model_1', 'production_ready', '[]', 'fixture',
          'test', ?, 1, ?
        )
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO source_assets(
          id, campaign_id, model_id, content_hash, original_path, stored_path,
          filename, status, created_at, updated_at
        ) VALUES (
          'source_1', 'campaign_1', 'model_1', ?, '/tmp/source.mp4',
          '/tmp/source.mp4', 'source.mp4', 'approved', ?, ?
        )
        """,
        ("a" * 64, now, now),
    )
    conn.execute(
        """
        INSERT INTO rendered_assets(
          id, campaign_id, source_asset_id, content_hash, output_path,
          campaign_path, filename, review_state, metadata_json, created_at, updated_at
        ) VALUES (
          'rendered_1', 'campaign_1', 'source_1', ?, '/tmp/final.mp4',
          '/tmp/final.mp4', 'final.mp4', 'approved', '{}', ?, ?
        )
        """,
        ("b" * 64, now, now),
    )
    conn.commit()
    return conn


def test_registry_is_append_only_and_revision_chain_is_fingerprinted() -> None:
    conn = _conn()
    first = append_learning_governance_revision(
        conn,
        root_id="experiment:1",
        event_key="design:1",
        state="designed",
        evidence_class="experiment_result",
        creator="creator-1",
        content_intent="passive_selfie",
        hypothesis_json={"hypothesis": "treatment improves reach"},
    )
    second = append_learning_governance_revision(
        conn,
        root_id="experiment:1",
        event_key="assignment:1",
        state="assigned",
        evidence_class="experiment_result",
        creator="creator-1",
        content_intent="passive_selfie",
        assignment_refs_json=[{"pairId": "pair_1"}],
    )
    assert second["revision"] == 2
    assert second["previousRevisionId"] == first["id"]
    assert len(first["recordFingerprint"]) == 64
    replay = append_learning_governance_revision(
        conn,
        root_id="experiment:1",
        event_key="assignment:1",
        state="assigned",
        evidence_class="experiment_result",
        creator="creator-1",
        content_intent="passive_selfie",
    )
    assert replay["id"] == second["id"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE learning_governance_registry SET state = 'measured' WHERE id = ?",
            (second["id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="retained evidence"):
        conn.execute(
            "DELETE FROM learning_governance_registry WHERE id = ?", (second["id"],)
        )
    with pytest.raises(ValueError, match="event replay conflicts"):
        append_learning_governance_revision(
            conn,
            root_id="another-root",
            event_key="assignment:1",
            state="assigned",
            evidence_class="experiment_result",
            creator="creator-1",
            content_intent="passive_selfie",
        )


def test_measurement_revisions_can_be_reconciled_and_reinterpreted() -> None:
    conn = _conn()
    common = {
        "root_id": "experiment:reconciled",
        "evidence_class": "experiment_result",
        "creator": "creator-1",
        "content_intent": "passive_selfie",
    }
    append_learning_governance_revision(
        conn,
        event_key="design:reconciled",
        state="designed",
        **common,
    )
    first = append_learning_governance_revision(
        conn,
        event_key="measure:initial",
        state="measured",
        result_json={"metricRevision": 1},
        **common,
    )
    second = append_learning_governance_revision(
        conn,
        event_key="measure:reconciled",
        state="measured",
        result_json={"metricRevision": 2},
        **common,
    )
    interpreted = append_learning_governance_revision(
        conn,
        event_key="interpret:reconciled",
        state="interpreted",
        operator_interpretation_json={"decision": "inconclusive"},
        **common,
    )
    revised = append_learning_governance_revision(
        conn,
        event_key="measure:late-revision",
        state="measured",
        result_json={"metricRevision": 3},
        **common,
    )

    assert [
        first["revision"],
        second["revision"],
        interpreted["revision"],
        revised["revision"],
    ] == [
        2,
        3,
        4,
        5,
    ]


def test_canonical_exclusions_bind_operator_removal_duplicate_and_contamination() -> (
    None
):
    conn = _conn()
    now = "2026-07-01T00:00:00Z"
    for post_id, published_at in (
        ("post_1", now),
        ("post_2", "2026-07-02T00:00:00Z"),
    ):
        conn.execute(
            """
            INSERT INTO performance_snapshots(
              id, campaign_id, rendered_asset_id, source_asset_id, content_hash,
              source_content_hash, post_id, status, published_at, snapshot_at,
              metrics_eligible, history_source, lineage_v2_valid, raw_json, created_at
            ) VALUES (?, 'campaign_1', 'rendered_1', 'source_1', ?, ?, ?,
                      'published', ?, ?, 1, 'metric_history', 1, ?, ?)
            """,
            (
                f"snapshot_{post_id}",
                "b" * 64,
                "a" * 64,
                post_id,
                published_at,
                "2026-07-06T00:00:00Z",
                json.dumps({"experimentContaminated": post_id == "post_2"}),
                "2026-07-06T00:00:00Z",
            ),
        )
    conn.execute(
        """
        UPDATE rendered_assets
        SET review_state = 'rejected',
            metadata_json = ?
        WHERE id = 'rendered_1'
        """,
        (
            json.dumps(
                {
                    "lifecycleStatus": "operator_removed",
                    "creativeDecision": "rejected",
                    "generationStatus": "completed",
                    "learningEligible": False,
                    "technicalFailure": False,
                }
            ),
        ),
    )
    conn.commit()
    snapshot = dict(
        conn.execute(
            "SELECT * FROM performance_snapshots WHERE post_id = 'post_2'"
        ).fetchone()
    )
    result = canonical_learning_eligibility(
        conn,
        snapshot,
        include_base_learning=False,
        required_observation_bucket="approximately_72h",
    )
    assert result["eligible"] is False
    assert {
        "operator_rejected_asset",
        "operator_removed_asset",
        "asset_learning_disabled",
        "duplicate_exact_final_media_outcome",
        "experiment_contamination",
        "missing_or_late_observation_window",
    }.issubset(result["reasons"])
    assert len(result["fingerprint"]) == 64
