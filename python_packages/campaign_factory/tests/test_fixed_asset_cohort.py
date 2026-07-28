from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.content_director import PlanningRequest, build_plan, persist_plan
from campaign_factory.content_director_operations import create_metric_cohorts
from campaign_factory.db import init_db
from campaign_factory.fixed_asset_cohort import (
    FixedAssetCohortRequest,
    apply_fixed_asset_cohort,
    build_fixed_asset_cohort,
)

SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
NOW = "2026-07-28T00:00:00Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(**overrides: Any) -> FixedAssetCohortRequest:
    values: dict[str, Any] = {
        "creator": "stacey",
        "account": "bennett_s33",
        "intent": "passive_selfie",
        "asset_ids": ("asset_1", "asset_2", "asset_3"),
        "observation_cohorts": ("1h", "24h", "72h"),
        "autonomy_mode": "SUPERVISED",
        "timezone": "America/New_York",
        "start_date": date(2026, 7, 29),
    }
    values.update(overrides)
    return FixedAssetCohortRequest(**values)


def _receipt(index: int) -> dict[str, Any]:
    return {
        "schema": "creator_os.existing_video_intake_receipt.v1",
        "contractVersion": "existing-video-intake.v1",
        "derivationKind": "embedded_audio_final",
        "creator": "stacey",
        "campaign": "real_stacey_cohort",
        "intendedAccount": "bennett_s33",
        "contentIntent": "passive_selfie",
        "identityProfile": SOUL_ID,
        "technicalQc": {
            "status": "passed",
            "receiptId": f"qc_{index}",
        },
        "generation": {
            "generationId": f"higgsfield_{index}",
            "provider": "higgsfield",
            "model": "seedance_2_0",
            "recipe": "higgsfield_seedance2_passive",
            "prompt": f"retained actual prompt {index}",
            "seed": 100 + index,
            "originalCost": {
                "creditsConsumed": 15 + index,
                "unit": "higgsfield_credits",
            },
        },
        "audio": {
            "musicId": f"music_{index}",
            "sourceTrackSha256": f"{index + 1:x}" * 64,
            "acousticFingerprint": f"{index + 4:x}" * 64,
            "processedSegmentSha256": f"{index + 7:x}" * 64,
            "segmentStartSeconds": float(index),
            "segmentDurationSeconds": 5.0,
            "fulfillmentStatus": "verified",
            "proofType": "embedded_output_audio_stream",
        },
        "caption": f"retained hook {index}",
    }


def _fixture(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        """
        INSERT INTO models (id, slug, name, created_at, updated_at)
        VALUES ('model_stacey', 'stacey', 'Stacey', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO accounts (
          id, handle, platform, model_id, threadsdash_is_active,
          threadsdash_status, threadsdash_needs_reauth,
          threadsdash_projection_observed_at, created_at, updated_at
        ) VALUES (
          'account_stacey', 'bennett_s33', 'instagram', 'model_stacey', 1,
          'active', 0, ?, ?, ?
        )
        """,
        (NOW, NOW, NOW),
    )
    for index in range(1, 4):
        campaign_id = f"campaign_{index}"
        source_id = f"source_{index}"
        asset_id = f"asset_{index}"
        source = tmp_path / f"source-{index}.png"
        final = tmp_path / f"final-{index}.mp4"
        source.write_bytes(f"approved-source-{index}".encode())
        final.write_bytes(f"final-video-{index}".encode())
        conn.execute(
            """
            INSERT INTO campaigns (
              id, slug, name, platform, root_path, created_at, updated_at
            ) VALUES (?, ?, ?, 'instagram', ?, ?, ?)
            """,
            (
                campaign_id,
                f"cohort-{index}",
                f"Cohort {index}",
                str(tmp_path),
                NOW,
                NOW,
            ),
        )
        conn.execute(
            """
            INSERT INTO source_assets (
              id, campaign_id, model_id, content_hash, original_path, stored_path,
              filename, media_type, notes, account_ids_json, status, created_at,
              updated_at
            ) VALUES (?, ?, 'model_stacey', ?, ?, ?, ?, 'image', ?, '[]',
                      'approved', ?, ?)
            """,
            (
                source_id,
                campaign_id,
                _sha(source),
                str(source),
                str(source),
                source.name,
                json.dumps(
                    {
                        "sourceClass": "portrait",
                        "intentCompatibility": [
                            "passive_selfie",
                            "flirty_portrait",
                            "lifestyle",
                        ],
                    }
                ),
                NOW,
                NOW,
            ),
        )
        receipt = _receipt(index)
        audio_receipt_path = tmp_path / f"audio-{index}.json"
        audio_receipt = {
            "schema": "creator_os.audio_embedding_receipt.v1",
            "finalVideo": {"path": str(final), "sha256": _sha(final)},
        }
        audio_receipt_path.write_text(json.dumps(audio_receipt), encoding="utf-8")
        receipt["audio"].update(
            {
                "receiptPath": str(audio_receipt_path),
                "receiptSha256": _sha(audio_receipt_path),
                "fulfillmentOutputSha256": _sha(final),
            }
        )
        conn.execute(
            """
            INSERT INTO rendered_assets (
              id, campaign_id, source_asset_id, content_hash, output_path,
              campaign_path, filename, recipe, metadata_json, audit_status,
              review_state, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'higgsfield_seedance2_passive', ?,
                      'passed', 'approved', ?, ?)
            """,
            (
                asset_id,
                campaign_id,
                source_id,
                _sha(final),
                str(final),
                str(tmp_path),
                final.name,
                json.dumps(receipt),
                NOW,
                NOW,
            ),
        )
        approval = {
            "sourceAssetId": source_id,
            "sha256": _sha(source),
            "decision": "approved",
            "operator": "operator",
            "reason": "fixed_cohort_test",
            "decidedAt": NOW,
        }
        conn.execute(
            """
            INSERT INTO activity_events (
              id, event_type, campaign_id, source_asset_id, status, message,
              metadata_json, created_at
            ) VALUES (?, 'source_approval_decided', ?, ?, 'success',
                      'source approved', ?, ?)
            """,
            (
                f"approval_{index}",
                campaign_id,
                source_id,
                json.dumps(approval),
                NOW,
            ),
        )
        conn.execute(
            """
            INSERT INTO existing_media_asset_reviews (
              id, rendered_asset_id, final_sha256, source_sha256, provider,
              model_tool, recipe_id, generation_id, seed, creator,
              content_intent, source_class, reviewer, verdict,
              rejection_reasons_json, results_json, notes, contract_version,
              created_at
            ) VALUES (?, ?, ?, ?, 'higgsfield', 'seedance_2_0',
                      'higgsfield_seedance2_passive', ?, ?, 'stacey',
                      'passive_selfie', 'portrait', 'operator', 'WOULD_POST',
                      '[]', ?, 'exact-sha approval', 'existing-video-review.v2', ?)
            """,
            (
                f"review_{index}",
                asset_id,
                _sha(final),
                _sha(source),
                f"higgsfield_{index}",
                100 + index,
                json.dumps(
                    {
                        "identity": "PASS",
                        "anatomy": "PASS",
                        "motion": "PASS",
                        "phoneNative": "PASS",
                        "audioFit": "PASS",
                    }
                ),
                NOW,
            ),
        )
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, cluster_key, rank, label, prompt_template_json, raw_json,
          imported_at, updated_at
        ) VALUES (
          'pattern_1', 'pattern_1', 1, 'Approved prompt',
          '{"mainPrompt":"Approved casual motion."}',
          '{"approvalStatus":"approved","patternFamily":"curiosity"}', ?, ?
        )
        """,
        (NOW, NOW),
    )
    conn.commit()
    return conn


def _replace_receipt(
    conn: sqlite3.Connection, asset_id: str, **changes: Any
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT metadata_json FROM rendered_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    receipt = json.loads(row["metadata_json"])
    receipt.update(changes)
    conn.execute(
        "UPDATE rendered_assets SET metadata_json = ? WHERE id = ?",
        (json.dumps(receipt), asset_id),
    )
    conn.commit()
    return receipt


def test_three_passive_assets_dry_run_apply_and_idempotency(tmp_path: Path) -> None:
    conn = _fixture(tmp_path)
    before = conn.total_changes
    preview = build_fixed_asset_cohort(conn, _request())

    assert conn.total_changes == before
    assert preview["persistentWrites"] == 0
    assert preview["status"] == "DRAFT"
    assert preview["contentIntent"] == "passive_selfie"
    assert [item["renderedAssetId"] for item in preview["items"]] == [
        "asset_1",
        "asset_2",
        "asset_3",
    ]
    assert {item["contentIntent"] for item in preview["items"]} == {"passive_selfie"}
    assert all(
        item["attachmentMethod"] == "existing_canonical_asset"
        and item["generatedDuringPlan"] is False
        and item["attachmentCost"] == {"credits": 0, "providerCalls": 0}
        for item in preview["items"]
    )

    first = apply_fixed_asset_cohort(conn, preview)
    second_preview = build_fixed_asset_cohort(conn, _request())
    second = apply_fixed_asset_cohort(conn, second_preview)

    assert first["written"] is True
    assert first["providerCalls"] == first["mediaWrites"] == 0
    assert first["exports"] == first["schedules"] == first["publications"] == 0
    assert all(not attachment["blockers"] for attachment in first["attachments"])
    assert second["written"] is False
    assert second["idempotent"] is True
    assert all(attachment["idempotent"] for attachment in second["attachments"])
    assert (
        conn.execute(
            "SELECT count(*) FROM creative_plan_versions WHERE objective='LEARNING_COHORT'"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            """
            SELECT count(*) FROM creative_plan_items
            WHERE plan_version_id = ? AND content_intent = 'passive_selfie'
              AND execution_state = 'CREATIVE_APPROVED'
            """,
            (first["planId"],),
        ).fetchone()[0]
        == 3
    )


def test_normal_planner_diversity_is_unchanged(tmp_path: Path) -> None:
    conn = _fixture(tmp_path)
    request = PlanningRequest(
        creator="stacey",
        horizon_days=7,
        accounts=("bennett_s33",),
        objective="GROWTH",
        output_count=5,
        timezone="America/New_York",
        autonomy_mode="SUPERVISED",
        max_credits=100,
        start_date=date(2026, 7, 29),
    )
    before = build_plan(conn, request)
    apply_fixed_asset_cohort(conn, build_fixed_asset_cohort(conn, _request()))
    after = build_plan(conn, request)

    assert before["contentMixPolicy"] == after["contentMixPolicy"]
    assert len(set(item["contentIntent"] for item in after["items"])) > 1
    assert (
        before["decisionReceipt"]["resultingAllocation"]
        == after["decisionReceipt"]["resultingAllocation"]
    )


def test_previous_rolling_plan_is_referenced_but_immutable(tmp_path: Path) -> None:
    conn = _fixture(tmp_path)
    normal_request = PlanningRequest(
        creator="stacey",
        horizon_days=7,
        accounts=("bennett_s33",),
        objective="GROWTH",
        output_count=3,
        timezone="America/New_York",
        autonomy_mode="SUPERVISED",
        max_credits=100,
        start_date=date(2026, 7, 29),
    )
    previous = persist_plan(conn, build_plan(conn, normal_request))
    version_before = dict(
        conn.execute(
            "SELECT * FROM creative_plan_versions WHERE id = ?",
            (previous["planId"],),
        ).fetchone()
    )
    items_before = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM creative_plan_items WHERE plan_version_id = ? ORDER BY item_index",
            (previous["planId"],),
        )
    ]

    preview = build_fixed_asset_cohort(conn, _request())
    applied = apply_fixed_asset_cohort(conn, preview)

    assert preview["previousPlanVersionId"] == previous["planId"]
    assert applied["planId"] != previous["planId"]
    assert (
        dict(
            conn.execute(
                "SELECT * FROM creative_plan_versions WHERE id = ?",
                (previous["planId"],),
            ).fetchone()
        )
        == version_before
    )
    assert [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM creative_plan_items WHERE plan_version_id = ? ORDER BY item_index",
            (previous["planId"],),
        )
    ] == items_before


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ("wrong_creator", "wrong_creator"),
        ("wrong_account", "wrong_account_scope"),
        ("wrong_intent", "mixed_or_wrong_content_intent"),
        ("unapproved_source", "missing_source_approval"),
        ("missing_qc", "missing_technical_qc"),
        ("missing_review", "missing_would_post_review"),
        ("mixed_audio", "mixed_audio_cohorts"),
        ("duplicate_sha", "duplicate_final_sha"),
        ("published", "previously_published_asset"),
        ("fixture", "fixture_evidence"),
        ("invalid_audio", "audio_lineage_invalid"),
    ],
)
def test_ineligible_assets_block_without_writes(
    tmp_path: Path, mutation: str, blocker: str
) -> None:
    conn = _fixture(tmp_path)
    if mutation == "wrong_creator":
        _replace_receipt(conn, "asset_2", creator="larissa")
    elif mutation == "wrong_account":
        _replace_receipt(conn, "asset_2", intendedAccount="other-account")
    elif mutation == "wrong_intent":
        _replace_receipt(conn, "asset_2", contentIntent="lifestyle")
    elif mutation == "unapproved_source":
        conn.execute("UPDATE source_assets SET status='imported' WHERE id='source_2'")
        conn.commit()
    elif mutation == "missing_qc":
        _replace_receipt(conn, "asset_2", technicalQc={"status": "failed"})
    elif mutation == "missing_review":
        conn.execute(
            "UPDATE rendered_assets SET review_state='draft' WHERE id='asset_2'"
        )
        conn.commit()
    elif mutation == "mixed_audio":
        _replace_receipt(conn, "asset_2", derivationKind="provider_original_audio")
    elif mutation == "duplicate_sha":
        first = conn.execute(
            "SELECT content_hash FROM rendered_assets WHERE id='asset_1'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE rendered_assets SET content_hash=? WHERE id='asset_2'", (first,)
        )
        conn.commit()
    elif mutation == "published":
        conn.execute(
            """
            INSERT INTO proof_runs (
              id, campaign_id, rendered_asset_id, threadsdash_post_id, status,
              current_state, started_at, created_at, updated_at
            ) VALUES ('proof_2','campaign_2','asset_2','instagram-media','complete',
                      'published',?,?,?)
            """,
            (NOW, NOW, NOW),
        )
        conn.commit()
    elif mutation == "fixture":
        _replace_receipt(conn, "asset_2", evidenceClass="fixture")
    else:
        receipt = _replace_receipt(conn, "asset_2")
        receipt["audio"].pop("processedSegmentSha256")
        _replace_receipt(conn, "asset_2", audio=receipt["audio"])

    before = conn.total_changes
    preview = build_fixed_asset_cohort(conn, _request())

    assert blocker in preview["blockers"]
    assert preview["status"] == "BLOCKED"
    assert conn.total_changes == before
    with pytest.raises(ValueError, match="fixed-asset cohort blocked"):
        apply_fixed_asset_cohort(conn, preview)


def test_duplicate_asset_ids_and_invalid_request_shape_are_rejected(
    tmp_path: Path,
) -> None:
    conn = _fixture(tmp_path)
    with pytest.raises(ValueError, match="asset IDs must be distinct"):
        build_fixed_asset_cohort(
            conn,
            _request(asset_ids=("asset_1", "asset_1", "asset_3")),
        )
    with pytest.raises(ValueError, match="supervised mode"):
        build_fixed_asset_cohort(conn, _request(autonomy_mode="SHADOW"))
    with pytest.raises(ValueError, match="exactly 1h,24h,72h"):
        build_fixed_asset_cohort(conn, _request(observation_cohorts=("24h", "72h")))


def test_observation_cost_and_learning_truth_are_retained(tmp_path: Path) -> None:
    conn = _fixture(tmp_path)
    preview = build_fixed_asset_cohort(conn, _request())
    learning = preview["decisionReceipt"]["learning"]

    assert learning == {
        "consulted": True,
        "packPresent": False,
        "eligible": False,
        "applied": False,
        "rankingChanged": False,
        "finalChoiceChanged": False,
        "primaryFallback": "no_persisted_pack",
        "secondaryDiagnostics": [
            "fewer_than_three_eligible_24h_or_72h_outcomes",
            "no_supervised_active_recommendation",
        ],
    }
    assert [
        item["originalGenerationCost"]["creditsConsumed"] for item in preview["items"]
    ] == [
        16,
        17,
        18,
    ]
    applied = apply_fixed_asset_cohort(conn, preview)
    cohorts = conn.execute(
        """
        SELECT count(*) FROM creative_plan_metric_cohorts
        WHERE plan_item_id IN (
          SELECT id FROM creative_plan_items WHERE plan_version_id = ?
        )
        """,
        (applied["planId"],),
    ).fetchone()[0]
    assert cohorts == 0
    expectations = [
        json.loads(row["metric_cohort_identity_json"])
        for row in conn.execute(
            "SELECT metric_cohort_identity_json FROM creative_plan_items WHERE plan_version_id=?",
            (applied["planId"],),
        )
    ]
    assert all(
        item["observationBuckets"] == ["1h", "24h", "72h"]
        and item["publicationRequiredBeforeMaterialization"] is True
        and item["materializedCohortIds"] == []
        for item in expectations
    )
    assert all(
        json.loads(row["estimated_cost_json"])
        == {
            "attachmentCredits": 0,
            "originalGenerationCost": {
                "creditsConsumed": 15 + int(row["item_index"]) + 1,
                "unit": "higgsfield_credits",
            },
            "providerCalls": 0,
        }
        for row in conn.execute(
            "SELECT item_index, estimated_cost_json FROM creative_plan_items WHERE plan_version_id=?",
            (applied["planId"],),
        )
    )
    assert all(
        json.loads(row["export_identity_json"]) == {}
        and json.loads(row["publication_identity_json"]) == {}
        for row in conn.execute(
            "SELECT export_identity_json, publication_identity_json FROM creative_plan_items WHERE plan_version_id=?",
            (applied["planId"],),
        )
    )


def test_apply_revalidates_and_rolls_back_all_rows_on_stale_preview(
    tmp_path: Path,
) -> None:
    conn = _fixture(tmp_path)
    preview = build_fixed_asset_cohort(conn, _request())
    conn.execute("UPDATE rendered_assets SET review_state='draft' WHERE id='asset_2'")
    conn.commit()

    with pytest.raises(ValueError, match="missing_would_post_review"):
        apply_fixed_asset_cohort(conn, preview)

    assert (
        conn.execute(
            "SELECT count(*) FROM creative_plan_versions WHERE objective='LEARNING_COHORT'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM creative_plan_items WHERE plan_version_id=?",
            (preview["planId"],),
        ).fetchone()[0]
        == 0
    )


def test_actual_publication_materializes_cohorts_from_published_at(
    tmp_path: Path,
) -> None:
    conn = _fixture(tmp_path)
    applied = apply_fixed_asset_cohort(conn, build_fixed_asset_cohort(conn, _request()))
    item_id = applied["persistedPlan"]["items"][0]["id"]
    published_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    create_metric_cohorts(
        conn,
        plan_item_id=item_id,
        published_at=published_at,
    )

    rows = conn.execute(
        """
        SELECT observation_bucket, expected_earliest_at, observation_state
        FROM creative_plan_metric_cohorts WHERE plan_item_id=?
        ORDER BY expected_earliest_at
        """,
        (item_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("1h", "2026-08-01T13:00:00Z", "MISSING"),
        ("24h", "2026-08-02T12:00:00Z", "MISSING"),
        ("72h", "2026-08-04T12:00:00Z", "MISSING"),
    ]


def test_audio_receipt_final_sha_mismatch_is_blocked(tmp_path: Path) -> None:
    conn = _fixture(tmp_path)
    receipt = _replace_receipt(conn, "asset_2")
    audio_path = Path(receipt["audio"]["receiptPath"])
    audio_payload = json.loads(audio_path.read_text(encoding="utf-8"))
    audio_payload["finalVideo"]["sha256"] = "f" * 64
    audio_path.write_text(json.dumps(audio_payload), encoding="utf-8")
    receipt["audio"]["receiptSha256"] = _sha(audio_path)
    _replace_receipt(conn, "asset_2", audio=receipt["audio"])

    preview = build_fixed_asset_cohort(conn, _request())

    assert "audio_lineage_invalid" in preview["blockers"]


def test_cohort_identity_is_stable_across_implicit_schedule_dates(
    tmp_path: Path,
) -> None:
    conn = _fixture(tmp_path)
    first = build_fixed_asset_cohort(conn, _request(start_date=date(2026, 7, 29)))
    apply_fixed_asset_cohort(conn, first)
    next_day = build_fixed_asset_cohort(conn, _request(start_date=date(2026, 7, 30)))

    assert next_day["inputFingerprint"] == first["inputFingerprint"]
    assert next_day["planId"] == first["planId"]
    assert next_day["idempotent"] is True
    assert next_day["blockers"] == []
