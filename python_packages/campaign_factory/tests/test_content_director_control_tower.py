from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from campaign_factory.content_director import build_plan, load_plan, persist_plan
from campaign_factory.content_director_operations import list_plans, plan_status, replan
from campaign_factory.learning_consumption import (
    build_measured_recommendations,
    persist_measured_recommendations,
)
from campaign_factory.learning_governance import authorize_learning_policy
from campaign_factory.production_prompts import CREATOR_SOUL_IDS as _CREATOR_SOUL_IDS
from test_content_director import _conn, _request
from test_learning_consumption import _outcome, _pack


def _persisted(tmp_path: Path):
    conn = _conn(tmp_path)
    stored = persist_plan(conn, build_plan(conn, _request(output_count=5)))
    return conn, stored["planId"]


def test_status_is_read_only_bounded_and_answers_operator_questions(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path)
    before = conn.total_changes
    status = plan_status(conn, plan_id)
    assert conn.total_changes == before
    assert status["readOnly"] is True
    assert status["planId"] == plan_id
    assert status["whatShouldBeCreated"] == 0
    assert status["runtimeSha"]
    assert status["activeExperiments"] == []


def test_plan_list_is_scoped_and_limited(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path)
    listing = list_plans(conn, creator="stacey", limit=1)
    assert [row["id"] for row in listing["plans"]] == [plan_id]
    assert listing["limit"] == 1
    assert listing["readOnly"] is True


def test_replan_dry_run_writes_nothing_and_explains_retention(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path)
    item = conn.execute(
        """
        SELECT id FROM creative_plan_items
        WHERE plan_version_id = ? ORDER BY item_index LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE creative_plan_items
        SET execution_state = 'PUBLISHED',
            generation_identity_json = '{"finalMediaSha256":"fixture-sha"}',
            publication_identity_json = '{"instagramMediaId":"fixture-media"}'
        WHERE id = ?
        """,
        (item["id"],),
    )
    conn.commit()
    before = conn.total_changes
    result = replan(conn, plan_id=plan_id, apply=False)
    assert conn.total_changes == before
    assert result["dryRun"] is True
    assert result["providerCalls"] == 0
    assert result["retainedItems"][0]["state"] == "PUBLISHED"


def test_replan_apply_versions_and_preserves_completed_lineage(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path)
    old = conn.execute(
        """
        SELECT * FROM creative_plan_items
        WHERE plan_version_id = ? ORDER BY item_index LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE creative_plan_items
        SET execution_state = 'CREATIVE_APPROVED',
            generation_identity_json = '{"finalMediaSha256":"fixture-sha"}',
            review_identity_json = '{"action":"APPROVE"}'
        WHERE id = ?
        """,
        (old["id"],),
    )
    conn.commit()
    result = replan(conn, plan_id=plan_id, apply=True)
    successor = result["candidate"]
    assert successor["version"] == 2
    retained = successor["items"][0]
    assert retained["execution_state"] == "CREATIVE_APPROVED"
    assert (
        json.loads(retained["generation_identity_json"])["finalMediaSha256"]
        == "fixture-sha"
    )
    assert successor["previousPlanVersionId"] == plan_id


def test_fixture_master_proof_remains_supervised_and_non_mutating(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path)
    plan = load_plan(conn, plan_id)
    assert plan["creator"] == "stacey"
    assert len(plan["items"]) == 5
    assert plan["autonomyMode"] == "SUPERVISED"
    assert all(item["content_intent"] != "talking_selfie" for item in plan["items"])
    assert all(
        json.loads(item["audio_profile_json"])["resolveAt"] == "finishing"
        for item in plan["items"]
    )
    proof_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "fixtures"
        / "content_director_master_proof.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["truthLevel"] == "fixture_backed_implementation_proof"
    assert proof["notRealOperationalAutonomy"] is True
    assert set(proof["externalEffects"].values()) == {0}


def test_fixture_master_proof_consumes_one_supervised_active_recommendation(
    tmp_path: Path,
) -> None:
    conn = _conn(tmp_path)
    source = conn.execute(
        "SELECT id, content_hash FROM source_assets WHERE id = 'src_2'"
    ).fetchone()
    outcomes = [
        _outcome(
            index,
            sourceAssetId=source["id"],
            sourceSha256=source["content_hash"],
            creatorIdentityProfile=_CREATOR_SOUL_IDS["stacey"],
            campaignId="camp_1",
            publishedAt="2026-07-25T00:00:00Z",
            snapshotAt="2026-07-26T00:00:00Z",
        )
        for index in (1, 2, 3)
    ]
    pack = _pack(outcomes)
    conn.execute(
        """
        INSERT INTO reference_knowledge_packs
        (id, schema_version, source_fingerprint, generated_at, policy_json,
         summary_json, payload_json, imported_at, updated_at)
        VALUES (?, 'reference_factory.knowledge_pack.v1', ?, ?, '{}', '{}', ?, ?, ?)
        """,
        (
            pack["packId"],
            pack["sourceFingerprint"],
            pack["generatedAt"],
            json.dumps(pack),
            pack["generatedAt"],
            pack["generatedAt"],
        ),
    )
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, cluster_key, rank, label, prompt_template_json, raw_json,
          imported_at, updated_at
        ) VALUES (
          'refpat_10012097369458bf', 'measured_pattern', 0, 'Measured',
          '{"mainPrompt":"Approved measured casual motion prompt."}',
          '{"approvalStatus":"approved","patternFamily":"curiosity"}', ?, ?
        )
        """,
        (pack["generatedAt"], pack["generatedAt"]),
    )
    recommendations = build_measured_recommendations(
        pack, now=datetime(2026, 7, 27, tzinfo=UTC)
    )
    assert recommendations[0]["eligibleForOperatorApproval"], recommendations
    persisted = persist_measured_recommendations(conn, recommendations, pack=pack)
    assert persisted["itemsInserted"] == 1, persisted
    conn.execute(
        "UPDATE recommendation_items SET status = 'accepted' WHERE status = 'proposed'"
    )
    stored = conn.execute(
        "SELECT status, evidence_json FROM recommendation_items"
    ).fetchone()
    evidence = json.loads(stored["evidence_json"])
    assert stored["status"] == "accepted"
    assert evidence["creatorIdentityProfile"] == _CREATOR_SOUL_IDS["stacey"]
    assert evidence["accountId"] == "stacey-main"
    assert evidence["contentIntent"] == "passive_selfie"
    assert evidence["classification"] == "ADVISORY"
    recommendation_id = str(
        conn.execute("SELECT id FROM recommendation_items").fetchone()["id"]
    )
    authorize_learning_policy(
        conn,
        recommendation_item_id=recommendation_id,
        operator="fixture_operator",
        reason="fixture exact-scope production policy",
    )
    plan = build_plan(conn, _request())
    first = plan["items"][0]
    assert first["sourceAssetId"] == "src_2", json.dumps(
        first["learningDecision"], sort_keys=True
    )
    assert first["prompt"] == "Approved measured casual motion prompt."
    assert first["learningDecision"]["learningApplied"] is True
    assert first["learningDecision"]["finalChoiceChanged"] is True
