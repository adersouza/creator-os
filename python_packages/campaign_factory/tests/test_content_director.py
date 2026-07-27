from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from campaign_factory.content_director import (
    PlanningRequest,
    build_plan,
    load_plan,
    persist_plan,
    transition_plan,
)
from campaign_factory.db_schema import SCHEMA


def _conn(tmp_path: Path, *, approved_sources: int = 3) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
        "EXPLOIT": 3,
        "EXPLORE": 1,
    }
    assert all(
        item["audioPolicy"] == "embedded_trending_required" for item in plan["items"]
    )


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
