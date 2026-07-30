from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

from campaign_factory.db import init_db
from campaign_factory.learning_consumption import (
    apply_learning_to_production_plan,
    approved_audio_performance,
    build_audio_recommendations,
    build_measured_recommendations,
    evidence_tier,
    observation_bucket,
    persist_learning_decision_receipt,
    persist_measured_recommendations,
    recommendation_fingerprint,
    recommendation_state,
)
from campaign_factory.production_lane import plan_production_batch
from PIL import Image


def _outcome(index: int, *, bucket: str = "approximately_24h", **changes):
    base = {
        "performanceSnapshotId": f"perf_{index}",
        "instagramMediaId": f"1800000000000000{index}",
        "campaignId": "campaign_1",
        "creatorId": "stacey",
        "creatorIdentityProfile": "soul_stacey",
        "accountId": "stacey-main",
        "accountGroupId": "stacey-group",
        "contentIntent": "passive_selfie",
        "publishedAt": "2026-07-01T00:00:00Z",
        "snapshotAt": (
            "2026-07-02T00:00:00Z"
            if bucket == "approximately_24h"
            else "2026-07-01T01:00:00Z"
        ),
        "observationBucket": bucket,
        "sourceAssetId": "source_2",
        "sourceSha256": "b" * 64,
        "finalMediaSha256": f"{index}" * 64,
        "publicationStatus": "published",
        "historySource": "metric_history",
        "metricsEligible": True,
        "lineageV2Valid": True,
        "fixture": False,
        "metrics": {"views": 100 + index, "likes": 10, "comments": 2, "shares": 1},
    }
    base.update(changes)
    return {
        "promptId": "prompt_1",
        "postId": f"post_{index}",
        "rewardScore": 1.0,
        "sourceSnapshotAt": base["snapshotAt"],
        "baselineProvenance": {"medianValue": 0.5},
        "outcome": base,
    }


def _pack(outcomes):
    core = {
        "policy": {},
        "summary": {},
        "goldReferences": [],
        "promptCards": [
            {
                "id": "prompt_1",
                "prompt": {"mainPrompt": "Approved measured casual motion prompt."},
            }
        ],
        "patternCards": [
            {
                "id": "pattern_1",
                "clusterKey": "pattern_1",
                "promptCardIds": ["prompt_1"],
                "measuredOutcomeProvenance": outcomes,
            }
        ],
        "captionPatterns": [],
        "audioPatterns": [],
        "provenance": {},
    }
    fingerprint = recommendation_fingerprint(core)
    return {
        "schema": "reference_factory.knowledge_pack.v1",
        "packId": f"kp_{fingerprint[:16]}",
        "sourceFingerprint": fingerprint,
        "generatedAt": "2026-07-03T00:00:00Z",
        **core,
    }


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    now = "2026-07-03T00:00:00Z"
    conn.execute(
        "INSERT INTO campaigns VALUES (?, ?, ?, 'instagram', ?, ?, ?)",
        ("campaign_1", "stacey-main", "Stacey", "/tmp/stacey", now, now),
    )
    return conn


def test_equal_age_minimum_and_one_hour_policy() -> None:
    now = datetime(2026, 7, 3, tzinfo=UTC)
    two = build_measured_recommendations(_pack([_outcome(1), _outcome(2)]), now=now)
    assert two[0]["sampleCount"] == 2
    assert two[0]["eligibleForOperatorApproval"] is False
    one_hour = build_measured_recommendations(
        _pack(
            [
                _outcome(1, bucket="approximately_1h"),
                _outcome(2, bucket="approximately_1h"),
                _outcome(3, bucket="approximately_1h"),
            ]
        ),
        now=now,
    )
    assert one_hour[0]["sampleCount"] == 3
    assert one_hour[0]["eligibleForOperatorApproval"] is False
    assert "one_hour_evidence_is_advisory_only" in one_hour[0]["risks"]


def test_evidence_tiers_never_call_three_outcomes_a_winner() -> None:
    assert evidence_tier(3) == "early_advisory"
    assert evidence_tier(5) == "preliminary_direction"
    assert evidence_tier(10) == "stronger_directional_evidence"
    assert (
        evidence_tier(3, controlled_matched_experiment=True)
        == "causal_evidence_candidate"
    )
    recommendation = build_measured_recommendations(
        _pack([_outcome(1), _outcome(2), _outcome(3)]),
        now=datetime(2026, 7, 3, tzinfo=UTC),
    )[0]
    assert recommendation["evidenceTier"] == "early_advisory"
    assert [row["scope"] for row in recommendation["hierarchicalEvidence"]] == [
        "account",
        "account_group",
        "creator",
        "global",
    ]
    assert all(
        row["activation"] == "advisory_only"
        for row in recommendation["hierarchicalEvidence"][1:]
    )
    assert "winner" not in json.dumps(recommendation).lower()


def test_explicit_learning_objective_selects_versioned_v2_score() -> None:
    recommendation = build_measured_recommendations(
        _pack([_outcome(index, learningObjective="engagement") for index in (1, 2, 3)]),
        now=datetime(2026, 7, 3, tzinfo=UTC),
    )[0]

    assert recommendation["learningObjective"] == "engagement"
    assert recommendation["scoringVersion"] == "objective_weighted_outcome.v2"


def test_missing_or_mixed_age_and_fixture_evidence_is_not_promoted() -> None:
    pack = _pack(
        [
            _outcome(1),
            _outcome(2, bucket="approximately_1h"),
            _outcome(3, fixture=True),
            _outcome(4, instagramMediaId=None),
        ]
    )
    recommendations = build_measured_recommendations(
        pack, now=datetime(2026, 7, 3, tzinfo=UTC)
    )
    assert all(not item["eligibleForOperatorApproval"] for item in recommendations)
    assert {item["observationBucket"] for item in recommendations} == {
        "approximately_1h",
        "approximately_24h",
    }


def test_three_equal_age_outcomes_require_operator_approval_and_stay_scoped() -> None:
    conn = _conn()
    pack = _pack([_outcome(1), _outcome(2), _outcome(3)])
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
        INSERT INTO reference_patterns
        (id, cluster_key, label, prompt_template_json, raw_json,
         imported_at, updated_at)
        VALUES ('refpat_10012097369458bf', 'pattern_1', 'Pattern', ?, '{}', ?, ?)
        """,
        (
            json.dumps({"mainPrompt": "Approved measured casual motion prompt."}),
            pack["generatedAt"],
            pack["generatedAt"],
        ),
    )
    recs = build_measured_recommendations(pack, now=datetime(2026, 7, 3, tzinfo=UTC))
    assert recs[0]["eligibleForOperatorApproval"] is True
    persisted = persist_measured_recommendations(conn, recs, pack=pack)
    assert persisted["itemsInserted"] == 1
    repeated = persist_measured_recommendations(conn, recs, pack=pack)
    assert repeated == {
        "runsInserted": 0,
        "itemsInserted": 0,
        "itemsUnchanged": 1,
        "itemsSuperseded": 0,
    }
    sources = [
        {"id": "source_1", "content_hash": "a" * 64, "status": "approved"},
        {"id": "source_2", "content_hash": "b" * 64, "status": "approved"},
    ]
    unchanged, prompt, advisory = apply_learning_to_production_plan(
        conn,
        creator="stacey",
        creator_identity_profile="soul_stacey",
        account="stacey-main",
        intent="passive_selfie",
        sources=sources,
        base_prompt="Base prompt.",
        now=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert [item["id"] for item in unchanged] == ["source_1", "source_2"]
    assert prompt == "Base prompt."
    assert advisory["fallbackReason"] == "advisory_only"
    assert advisory["learningEligible"] is False
    assert advisory["learningApplied"] is False
    assert advisory["finalChoiceChanged"] is False
    row = conn.execute(
        "SELECT id FROM recommendation_items WHERE status = 'proposed'"
    ).fetchone()
    conn.execute(
        "UPDATE recommendation_items SET status = 'accepted' WHERE id = ?",
        (row["id"],),
    )
    selected, prompt, decision = apply_learning_to_production_plan(
        conn,
        creator="stacey",
        creator_identity_profile="soul_stacey",
        account="stacey-main",
        intent="passive_selfie",
        sources=sources,
        base_prompt="Base prompt.",
        now=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert [item["id"] for item in selected] == ["source_2", "source_1"]
    assert prompt == "Approved measured casual motion prompt."
    assert decision["learningInfluenced"] is True
    assert decision["learningEligible"] is True
    assert decision["learningApplied"] is True
    assert decision["finalChoiceChanged"] is True
    for creator in ("larissa", "lola"):
        other, _, other_decision = apply_learning_to_production_plan(
            conn,
            creator=creator,
            creator_identity_profile=f"soul_{creator}",
            account="stacey-main",
            intent="passive_selfie",
            sources=sources,
            base_prompt="Base prompt.",
            now=datetime(2026, 7, 3, tzinfo=UTC),
        )
        assert [item["id"] for item in other] == ["source_1", "source_2"]
        assert other_decision["fallbackReason"] == "no_creator_match"


def test_wrong_account_intent_and_revocation_prevent_consumption() -> None:
    conn = _conn()
    pack = _pack([_outcome(1), _outcome(2), _outcome(3)])
    rec = build_measured_recommendations(pack, now=datetime(2026, 7, 3, tzinfo=UTC))[0]
    # State classification is fail-closed even before persistence.
    assert (
        recommendation_state(
            "accepted",
            rec,
            current_pack_id="another_pack",
            now=datetime(2026, 7, 3, tzinfo=UTC),
        )
        == "EXPIRED"
    )
    assert (
        recommendation_state(
            "rejected",
            rec,
            current_pack_id=pack["packId"],
            now=datetime(2026, 7, 3, tzinfo=UTC),
        )
        == "BLOCKED"
    )
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
        INSERT INTO reference_patterns
        (id, cluster_key, label, prompt_template_json, raw_json,
         imported_at, updated_at)
        VALUES ('refpat_10012097369458bf', 'pattern_1', 'Pattern', '{}', '{}', ?, ?)
        """,
        (pack["generatedAt"], pack["generatedAt"]),
    )
    persist_measured_recommendations(conn, [rec], pack=pack)
    conn.execute("UPDATE recommendation_items SET status = 'accepted'")
    sources = [
        {"id": "source_1", "content_hash": "a" * 64, "status": "approved"},
        {"id": "source_2", "content_hash": "b" * 64, "status": "approved"},
    ]
    for account, intent, reason in (
        ("stacey-secondary", "passive_selfie", "no_account_match"),
        ("stacey-main", "outfit", "no_intent_match"),
    ):
        unchanged, _, decision = apply_learning_to_production_plan(
            conn,
            creator="stacey",
            creator_identity_profile="soul_stacey",
            account=account,
            intent=intent,
            sources=sources,
            base_prompt="Base prompt.",
            now=datetime(2026, 7, 3, tzinfo=UTC),
        )
        assert [item["id"] for item in unchanged] == ["source_1", "source_2"]
        assert decision["fallbackReason"] == reason
        assert decision["learningApplied"] is False
    conn.execute("UPDATE recommendation_items SET status = 'rejected'")
    unchanged, _, revoked = apply_learning_to_production_plan(
        conn,
        creator="stacey",
        creator_identity_profile="soul_stacey",
        account="stacey-main",
        intent="passive_selfie",
        sources=sources,
        base_prompt="Base prompt.",
        now=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert [item["id"] for item in unchanged] == ["source_1", "source_2"]
    assert revoked["fallbackReason"] == "operator_not_approved"
    assert revoked["learningApplied"] is False


def test_decision_receipt_binds_output_lineage_idempotently() -> None:
    conn = _conn()
    decision = {
        "reason": "operator_approved_measured_recommendation",
        "learningInfluenced": True,
        "match": {"creator": "stacey", "account": "stacey-main"},
    }
    results = [
        {
            "jobId": "job_1",
            "status": "completed",
            "result": {
                "registeredAsset": {
                    "id": "rendered_1",
                    "content_hash": "f" * 64,
                }
            },
        }
    ]
    first = persist_learning_decision_receipt(conn, decision=decision, results=results)
    second = persist_learning_decision_receipt(conn, decision=decision, results=results)
    assert first == second
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM manager_decisions WHERE id = ?", (first,)
        ).fetchone()[0]
        == 1
    )


def test_observation_bucket_never_turns_missing_into_zero() -> None:
    assert observation_bucket(None, "2026-07-01T01:00:00Z") is None
    assert observation_bucket("2026-07-01T00:00:00Z", None) is None
    assert (
        observation_bucket("2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z")
        == "approximately_24h"
    )


def test_audio_learning_requires_exact_linkage_and_operator_approval() -> None:
    conn = _conn()
    pack = _pack([])
    now = "2026-07-28T12:00:00Z"
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
            now,
            json.dumps(pack),
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO audio_catalog (
          id, title, platform, active, lifecycle_state, imported_at, updated_at
        ) VALUES ('aud_exact', 'Exact', 'tiktok', 1, 'HOT', ?, ?)
        """,
        (now, now),
    )
    links = [
        {
            "tiktokMusicId": "music_1",
            "trackSha256": "a" * 64,
            "acousticFingerprint": "fp_exact",
            "segmentStartSeconds": 0.0,
            "segmentEndSeconds": 5.0,
            "processedSegmentSha256": "b" * 64,
            "instagramMediaId": f"1800{index}",
            "creator": "stacey",
            "creatorIdentityProfile": "soul_stacey",
            "account": "stacey-main",
            "intent": "passive_selfie",
            "observationBucket": "approximately_24h",
            "finalMediaSha256": str(index) * 64,
            "snapshotAt": f"2026-07-{24 + index:02d}T12:00:00Z",
        }
        for index in (1, 2, 3)
    ]
    conn.execute(
        """
        INSERT INTO audio_performance_rollups (
          id, campaign_id, account_id, audio_catalog_id, audio_key, post_count,
          score, stats_json, updated_at
        ) VALUES ('rollup_1', 'campaign_1', 'stacey-main', 'aud_exact',
                  'tiktok:music_1', 3, 9.5, ?, ?)
        """,
        (json.dumps({"exactPublicationLinkages": links}), now),
    )
    recs = build_audio_recommendations(
        conn, pack=pack, now=datetime(2026, 7, 28, tzinfo=UTC)
    )
    assert len(recs) == 1
    assert recs[0]["sampleCount"] == 3
    assert recs[0]["eligibleForOperatorApproval"] is True
    persist_measured_recommendations(conn, recs, pack=pack)
    scores, ids = approved_audio_performance(
        conn,
        creator="stacey",
        creator_identity_profile="soul_stacey",
        account="stacey-main",
        intent="passive_selfie",
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )
    assert scores == {}
    assert ids == []
    conn.execute("UPDATE recommendation_items SET status = 'accepted'")
    scores, ids = approved_audio_performance(
        conn,
        creator="stacey",
        creator_identity_profile="soul_stacey",
        account="stacey-main",
        intent="passive_selfie",
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )
    assert scores == {"aud_exact": 10.0}
    assert len(ids) == 1


def test_audio_learning_rejects_incomplete_exact_linkage() -> None:
    conn = _conn()
    pack = _pack([])
    conn.execute(
        """
        INSERT INTO audio_catalog (
          id, title, platform, active, lifecycle_state, imported_at, updated_at
        ) VALUES ('aud_missing', 'Incomplete', 'tiktok', 1, 'HOT', ?, ?)
        """,
        ("2026-07-28T12:00:00Z", "2026-07-28T12:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO audio_performance_rollups (
          id, campaign_id, account_id, audio_catalog_id, audio_key, post_count,
          score, stats_json, updated_at
        ) VALUES ('rollup_incomplete', 'campaign_1', 'stacey-main', 'aud_missing',
                  'tiktok:music_missing', 3, 9.5, ?, '2026-07-28T12:00:00Z')
        """,
        (
            json.dumps(
                {
                    "exactPublicationLinkages": [
                        {
                            "instagramMediaId": f"1800{index}",
                            "creator": "stacey",
                            "creatorIdentityProfile": "soul_stacey",
                            "account": "stacey-main",
                            "intent": "passive_selfie",
                            "observationBucket": "approximately_24h",
                            "finalMediaSha256": str(index) * 64,
                            "snapshotAt": f"2026-07-{24 + index:02d}T12:00:00Z",
                        }
                        for index in (1, 2, 3)
                    ]
                }
            ),
        ),
    )
    assert (
        build_audio_recommendations(
            conn, pack=pack, now=datetime(2026, 7, 28, tzinfo=UTC)
        )
        == []
    )


def test_fixture_normal_create_dry_run_changes_only_approved_choice(tmp_path) -> None:
    conn = _conn()
    soul_id = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
    now = "2026-07-03T00:00:00Z"
    conn.execute(
        "INSERT INTO models VALUES ('model_1', 'stacey', 'Stacey', NULL, ?, ?)",
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state
        (model_id,status,status_reason,effective_at,changed_by,version,
         retention_state,updated_at)
        VALUES ('model_1','active','fixture',?,'test',1,'retain_audit',?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance
        (campaign_id,model_id,lifecycle_status,blocker_codes_json,status_reason,
         changed_by,effective_at,version,updated_at)
        VALUES ('campaign_1','model_1','production_ready','[]','fixture',
                'test',?,1,?)
        """,
        (now, now),
    )
    for index, digest_seed in ((1, "a"), (2, "b")):
        path = tmp_path / f"approved_{index}.png"
        Image.new("RGB", (360, 640), color=(index, 20, 30)).save(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        conn.execute(
            """
            INSERT INTO source_assets (
              id, campaign_id, model_id, content_hash, original_path, stored_path,
              filename, media_type, status, created_at, updated_at
            ) VALUES (?, 'campaign_1', 'model_1', ?, ?, ?, ?, 'image',
                      'approved', ?, ?)
            """,
            (
                f"source_{index}",
                digest,
                str(path),
                str(path),
                path.name,
                now,
                now,
            ),
        )
        if digest_seed == "b":
            preferred_sha = digest
    outcomes = [
        _outcome(index, creatorIdentityProfile=soul_id, sourceSha256=preferred_sha)
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
            now,
            json.dumps(pack),
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO reference_patterns
        (id, cluster_key, label, prompt_template_json, raw_json,
         imported_at, updated_at)
        VALUES ('refpat_10012097369458bf', 'pattern_1', 'Pattern', ?, '{}', ?, ?)
        """,
        (
            json.dumps({"mainPrompt": "Approved measured casual motion prompt."}),
            now,
            now,
        ),
    )
    recommendations = build_measured_recommendations(
        pack, now=datetime(2026, 7, 3, tzinfo=UTC)
    )
    persist_measured_recommendations(conn, recommendations, pack=pack)
    conn.execute("UPDATE recommendation_items SET status = 'accepted'")
    governance = SimpleNamespace(
        active_identity_profile=lambda _creator, provider: {
            "creator_slug": "stacey",
            "provider": provider,
            "provider_identity_id": soul_id,
        },
        resolve_operation=lambda **_kwargs: {
            "providerIdentityId": soul_id,
            "governanceFingerprint": "g" * 64,
        },
    )
    batch = plan_production_batch(
        SimpleNamespace(
            conn=conn,
            domains=SimpleNamespace(creator_governance=governance),
        ),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )
    assert batch["jobs"][0]["sourceAssetId"] == "source_2"
    assert batch["jobs"][0]["prompt"] == "Approved measured casual motion prompt."
    assert batch["learningDecision"]["learningInfluenced"] is True
    assert batch["provider"] == "higgsfield"
    assert (
        batch["jobs"][0]["productionRecipe"]["modelId"] == "higgsfield_kling3_turbo_i2v"
    )
