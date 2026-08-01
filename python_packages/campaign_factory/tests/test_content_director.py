from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from campaign_factory.campaign_schema_v7 import (
    apply as apply_learning_governance_schema,
)
from campaign_factory.content_director import (
    PlanningRequest,
    build_plan,
    load_plan,
    persist_plan,
    transition_plan,
)
from campaign_factory.db_schema import SCHEMA
from campaign_factory.production_prompts import CREATOR_SOUL_IDS


def _conn(tmp_path: Path, *, approved_sources: int = 3) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    apply_learning_governance_schema(conn)
    now = "2026-07-27T00:00:00Z"
    conn.execute(
        "INSERT INTO models VALUES ('model_1', 'stacey', 'Stacey', NULL, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO campaigns VALUES "
        "('camp_1', 'stacey-plan', 'Stacey Plan', 'instagram', ?, ?, ?)",
        (str(tmp_path), now, now),
    )
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state
        (model_id, status, status_reason, effective_at, changed_by, version,
         offboarding_state, retention_state, updated_at)
        VALUES ('model_1', 'active', 'fixture', ?, 'test', 1, NULL,
                'retain_audit', ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance
        (campaign_id, model_id, lifecycle_status, blocker_codes_json,
         status_reason, changed_by, effective_at, version, updated_at)
        VALUES ('camp_1', 'model_1', 'production_ready', '[]', 'fixture',
                'test', ?, 1, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO accounts (
          id, handle, platform, model_id, threadsdash_is_active,
          threadsdash_status, threadsdash_needs_reauth,
          threadsdash_projection_observed_at, created_at, updated_at
        ) VALUES (
          'account_1', 'stacey-main', 'instagram', 'model_1', 1, 'active', 0,
          ?, ?, ?
        )
        """,
        (now, now, now),
    )
    identity_source = tmp_path / "stacey_identity.bin"
    identity_source.write_bytes(b"operator-approved-stacey-identity")
    identity_source_sha = hashlib.sha256(identity_source.read_bytes()).hexdigest()
    conn.execute(
        """
        INSERT INTO source_assets (
          id, campaign_id, model_id, content_hash, original_path, stored_path,
          filename, media_type, content_surface, platform, source_prompt,
          account_ids_json, status, created_at, updated_at
        ) VALUES (
          'src_identity', 'camp_1', 'model_1', ?, ?, ?, 'stacey_identity.bin',
          'identity_reference', 'identity', 'instagram', '{}', '[]', 'approved',
          ?, ?
        )
        """,
        (
            identity_source_sha,
            str(identity_source),
            str(identity_source),
            now,
            now,
        ),
    )
    identity_manifest = tmp_path / "stacey_identity_profile.json"
    identity_manifest.write_text('{"creatorKey":"stacey"}', encoding="utf-8")
    identity_manifest_sha = hashlib.sha256(identity_manifest.read_bytes()).hexdigest()
    conn.execute(
        """
        INSERT INTO creator_identity_profiles (
          id, model_id, provider, provider_identity_id, version, profile_json,
          profile_fingerprint, identity_manifest_path, identity_manifest_sha256,
          canonical_source_asset_id, canonical_evidence_type, status,
          activated_at, retired_at, operator, created_at
        ) VALUES (
          'identity_1', 'model_1', 'higgsfield', ?, 1, '{}', ?,
          ?, ?, 'src_identity', 'operator_approved_original', 'active',
          ?, NULL, 'test', ?
        )
        """,
        (
            CREATOR_SOUL_IDS["stacey"],
            "f" * 64,
            str(identity_manifest),
            identity_manifest_sha,
            now,
            now,
        ),
    )
    for index in range(approved_sources):
        path = tmp_path / f"source_{index}.png"
        path.write_bytes(f"source-{index}".encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        notes = {
            "sourceClass": "full_body" if index == 2 else "portrait",
            "intentCompatibility": [
                "passive_selfie",
                "flirty_portrait",
                "lifestyle",
                "animate_existing",
                *(["outfit"] if index == 2 else []),
            ],
        }
        conn.execute(
            """
            INSERT INTO source_assets (
              id, campaign_id, model_id, content_hash, original_path, stored_path,
              filename, media_type, content_surface, platform, notes,
              account_ids_json, status, created_at, updated_at
            ) VALUES (?, 'camp_1', 'model_1', ?, ?, ?, ?, 'image', 'reel',
                      'instagram', ?, '[]', 'approved', ?, ?)
            """,
            (
                f"src_{index}",
                digest,
                str(path),
                str(path),
                path.name,
                json.dumps(notes),
                now,
                now,
            ),
        )
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, cluster_key, rank, label, prompt_template_json, raw_json,
          imported_at, updated_at
        ) VALUES (
          'pattern_1', 'pattern_1', 1, 'Curiosity',
          '{"mainPrompt":"Approved casual curiosity motion."}',
          '{"approvalStatus":"approved","patternFamily":"curiosity"}', ?, ?
        )
        """,
        (now, now),
    )
    return conn


def _request(**overrides) -> PlanningRequest:
    values = {
        "creator": "stacey",
        "horizon_days": 7,
        "accounts": ("stacey-main",),
        "objective": "GROWTH",
        "output_count": 5,
        "timezone": "America/New_York",
        "autonomy_mode": "SUPERVISED",
        "max_credits": 100.0,
        "start_date": date(2026, 7, 28),
    }
    values.update(overrides)
    return PlanningRequest(**values)


def test_plan_dry_run_makes_no_writes_and_is_explainable(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    before = conn.total_changes
    plan = build_plan(conn, _request())
    assert conn.total_changes == before
    assert plan["requestedOutputCount"] == 5
    assert len(plan["items"]) == 5
    assert plan["decisionReceipt"]["resultingAllocation"] == {
        "CONTROLLED_VARIATION": 1,
        "DETERMINISTIC_DEFAULT": 3,
        "MEASURED_WINNER": 0,
        "EXPLORE": 1,
    }
    assert plan["decisionReceipt"]["observedProfileAllocation"] == {
        "normal": 4,
        "treatment": 1,
        "profiles": {"mirror_crop_tone@1": 1, "tilt_crop_dark@1": 0},
    }
    treatment = next(
        item
        for item in plan["items"]
        if item["explorationClass"] == "CONTROLLED_VARIATION"
    )
    assert (
        treatment["observedProfileDecision"]["selectedProfile"] == "mirror_crop_tone@1"
    )
    assert all(
        item["audioPolicy"] == "embedded_trending_required" for item in plan["items"]
    )
    assert all(
        item["audioProfile"]["batchTrackUniquenessRequired"] is True
        and item["audioProfile"]["batchSegmentUniquenessRequired"] is True
        for item in plan["items"]
    )
    assert len({item["sourceAssetId"] for item in plan["items"][:3]}) == 3


def test_plan_apply_is_idempotent_and_versions_changed_inputs(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    first_plan = build_plan(conn, _request())
    first = persist_plan(conn, first_plan)
    again = persist_plan(conn, first_plan)
    second = persist_plan(conn, build_plan(conn, _request(objective="CONTENT_TESTING")))
    assert first["written"] is True
    assert again["idempotent"] is True
    assert second["version"] == 2
    assert second["previousPlanVersionId"] == first["planId"]


def test_only_approved_creator_sources_are_planned(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    other = tmp_path / "larissa.png"
    other.write_bytes(b"larissa")
    digest = hashlib.sha256(other.read_bytes()).hexdigest()
    conn.execute(
        "INSERT INTO models VALUES ('model_2', 'larissa', 'Larissa', NULL, 'n', 'n')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="does not own campaign"):
        conn.execute(
            """
            INSERT INTO source_assets (
              id, campaign_id, model_id, content_hash, original_path, stored_path,
              filename, media_type, content_surface, platform, account_ids_json,
              status, created_at, updated_at
            ) VALUES ('wrong_creator', 'camp_1', 'model_2', ?, ?, ?, 'larissa.png',
                      'image', 'reel', 'instagram', '[]', 'approved', 'n', 'n')
            """,
            (digest, str(other), str(other)),
        )
    conn.execute("UPDATE source_assets SET status='imported' WHERE id='src_0'")
    plan = build_plan(conn, _request())
    candidates = {
        source for item in plan["items"] for source in item["sourceCandidateIds"]
    }
    assert "src_0" not in candidates
    assert "wrong_creator" not in candidates


def test_unsupported_capabilities_never_enter_plan(tmp_path: Path) -> None:
    plan = build_plan(_conn(tmp_path), _request())
    assert not {
        "talking_selfie",
        "talking_motion_copy",
        "motion_copy",
        "dance",
    } & {item["contentIntent"] for item in plan["items"]}


def test_missing_or_unhealthy_account_blocks_without_changing_creative_choice(
    tmp_path: Path,
) -> None:
    conn = _conn(tmp_path)
    conn.execute(
        "UPDATE accounts SET threadsdash_status='blocked' WHERE id='account_1'"
    )
    plan = build_plan(conn, _request())
    assert plan["status"] == "BLOCKED"
    assert all(
        "account_projection_unhealthy" in item["blockingReasons"]
        for item in plan["items"]
    )
    assert all(item["sourceAssetId"] for item in plan["items"])


def test_spend_estimate_cannot_exceed_signed_ceiling(tmp_path: Path) -> None:
    plan = build_plan(_conn(tmp_path), _request(max_credits=50.0))
    assert plan["estimatedSpend"]["credits"] == 75.0
    assert all(
        "estimated_plan_cost_exceeds_signed_ceiling" in item["blockingReasons"]
        for item in plan["items"]
    )


def test_blocked_plan_cannot_be_approved(tmp_path: Path) -> None:
    conn = _conn(tmp_path, approved_sources=0)
    stored = persist_plan(conn, build_plan(conn, _request()))
    with pytest.raises(ValueError, match="blocked plan items"):
        transition_plan(
            conn,
            plan_id=stored["planId"],
            to_state="APPROVED",
            operator="operator",
            reason="reviewed",
        )


def test_valid_state_transition_is_receipt_backed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    stored = persist_plan(conn, build_plan(conn, _request()))
    approved = transition_plan(
        conn,
        plan_id=stored["planId"],
        to_state="APPROVED",
        operator="operator",
        reason="five items reviewed",
    )
    assert approved["status"] == "APPROVED"
    assert approved["transitionReceipt"]["from"] == "DRAFT"
    assert load_plan(conn, stored["planId"])["status"] == "APPROVED"


@pytest.mark.parametrize("campaign_status", ["paused", "archived"])
def test_inactive_campaign_rejects_plan_before_any_write(
    tmp_path: Path, campaign_status: str
) -> None:
    conn = _conn(tmp_path)
    conn.execute(
        """
        INSERT INTO campaign_lifecycle_events
        (id, campaign_id, model_id, old_status, new_status, reason, actor,
         evidence_json, related_ids_json, version, created_at)
        VALUES ('campaign_state_test', 'camp_1', 'model_1', 'production_ready',
                ?, 'fixture', 'test', '{}', '[]', 2, '2026-07-27T00:00:01Z')
        """,
        (campaign_status,),
    )
    conn.execute(
        """
        UPDATE campaign_governance
        SET lifecycle_status = ?, version = 2
        WHERE campaign_id = 'camp_1'
        """,
        (campaign_status,),
    )
    before = conn.total_changes
    with pytest.raises(PermissionError, match="campaign_state_blocks_content_plan"):
        build_plan(conn, _request())
    assert conn.total_changes == before


def test_inactive_creator_rejects_plan_before_any_write(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    conn.execute(
        """
        INSERT INTO creator_lifecycle_events
        (id, model_id, old_status, new_status, reason, actor, effective_at,
         evidence_json, version, created_at)
        VALUES ('creator_state_test', 'model_1', 'active', 'suspended',
                'fixture', 'test', '2026-07-27T00:00:01Z', '{}', 2,
                '2026-07-27T00:00:01Z')
        """
    )
    conn.execute(
        """
        UPDATE creator_lifecycle_state
        SET status = 'suspended', version = 2
        WHERE model_id = 'model_1'
        """
    )
    before = conn.total_changes
    with pytest.raises(PermissionError, match="creator_inactive"):
        build_plan(conn, _request())
    assert conn.total_changes == before


def test_plan_uses_versioned_registry_identity_and_revalidates_before_persist(
    tmp_path: Path,
) -> None:
    conn = _conn(tmp_path)
    conn.execute(
        """
        UPDATE creator_identity_profiles
        SET status = 'retired', retired_at = '2026-07-30T01:00:00Z'
        WHERE id = 'identity_1'
        """
    )
    conn.execute(
        """
        INSERT INTO creator_identity_profiles (
          id, model_id, provider, provider_identity_id, version, profile_json,
          profile_fingerprint, identity_manifest_path, identity_manifest_sha256,
          canonical_source_asset_id, canonical_evidence_type, status,
          activated_at, retired_at, operator, created_at
        )
        SELECT
          'identity_2', model_id, provider, 'registry_soul_v2', 2, profile_json,
          ?, identity_manifest_path, identity_manifest_sha256,
          canonical_source_asset_id, canonical_evidence_type, 'active',
          '2026-07-30T01:00:00Z', NULL, 'test', '2026-07-30T01:00:00Z'
        FROM creator_identity_profiles WHERE id = 'identity_1'
        """,
        ("e" * 64,),
    )
    plan = build_plan(conn, _request())
    assert plan["identityProfile"] == "registry_soul_v2"
    assert all(item["identityProfile"] == "registry_soul_v2" for item in plan["items"])

    conn.execute(
        """
        INSERT INTO campaign_lifecycle_events
        (id, campaign_id, model_id, old_status, new_status, reason, actor,
         evidence_json, related_ids_json, version, created_at)
        VALUES ('campaign_state_revalidate', 'camp_1', 'model_1',
                'production_ready', 'paused', 'fixture', 'test', '{}', '[]', 2,
                '2026-07-30T01:00:01Z')
        """
    )
    conn.execute(
        """
        UPDATE campaign_governance
        SET lifecycle_status = 'paused', version = 2
        WHERE campaign_id = 'camp_1'
        """
    )
    with pytest.raises(PermissionError, match="campaign_state_blocks_content_plan"):
        persist_plan(conn, plan)
