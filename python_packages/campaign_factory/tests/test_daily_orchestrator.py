from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.daily_orchestrator import orchestrate_daily
from campaign_factory.db import connect, init_db
from campaign_factory.derived_stills import TIER_POLICIES
from reel_factory.worker_api import DERIVED_STILL_SCHEMA


class _Reservations:
    def __init__(self) -> None:
        self.expired = 0

    def expire_inventory_reservations(self) -> int:
        self.expired += 1
        return 0


class _Governance:
    def resolve_operation(self, **kwargs):
        return {
            "governanceFingerprint": hashlib.sha256(
                repr(sorted(kwargs.items())).encode()
            ).hexdigest()
        }


def _approved_generated_still_receipt(
    *,
    source_id: str,
    creator_id: str,
    campaign_id: str,
    path: Path,
    sha256: str,
) -> str:
    policy = TIER_POLICIES["approved_generated_still"]
    return json.dumps(
        {
            "derivedStillSource": {
                "schema": DERIVED_STILL_SCHEMA,
                "sourceTier": "approved_generated_still",
                "derivationDepth": 1,
                "providerEditDepth": 0,
                "parentAssetId": None,
                "rootSourceAssetId": source_id,
                "canonicalIdentityEligible": policy["canonicalIdentityEligible"],
                "generationEligible": policy["generationEligible"],
                "allowedOperations": policy["allowedOperations"],
                "creator": creator_id,
                "campaignId": campaign_id,
                "provider": None,
                "model": None,
                "operation": "enroll",
                "source": {
                    "assetId": source_id,
                    "path": str(path),
                    "sha256": sha256,
                },
                "output": {"path": str(path), "sha256": sha256},
                "evidence": {},
                "createdAt": "2026-07-30T12:00:00Z",
                "approval": {
                    "decision": "approved",
                    "exactOutputSha256": sha256,
                },
            }
        },
        sort_keys=True,
    )


def _factory(tmp_path: Path) -> SimpleNamespace:
    conn = connect(tmp_path / "campaign.sqlite")
    init_db(conn)
    now = "2026-07-30T12:00:00Z"
    for index in (1, 2):
        creator = f"creator_{index}"
        campaign = f"campaign_{index}"
        source = f"source_{index}"
        path = tmp_path / f"{source}.jpg"
        path.write_bytes(f"source-{index}".encode())
        source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        conn.execute(
            """
            INSERT INTO models(id, slug, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (creator, creator, creator, now, now),
        )
        conn.execute(
            """
            INSERT INTO campaigns(id, slug, name, root_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign, campaign, campaign, str(tmp_path), now, now),
        )
        conn.execute(
            """
            INSERT INTO creator_lifecycle_state
            (model_id, status, status_reason, effective_at, changed_by, version,
             retention_state, updated_at)
            VALUES (?, 'active', 'fixture', ?, 'fixture', 1, 'retain_audit', ?)
            """,
            (creator, now, now),
        )
        conn.execute(
            """
            INSERT INTO campaign_governance
            (campaign_id, model_id, lifecycle_status, blocker_codes_json,
             status_reason, changed_by, effective_at, version, updated_at,
             production_priority)
            VALUES (?, ?, 'production_ready', '[]', 'fixture', 'fixture',
                    ?, 1, ?, ?)
            """,
            (campaign, creator, now, now, 3 - index),
        )
        conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, status, source_prompt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'approved', ?, ?, ?)
            """,
            (
                source,
                campaign,
                creator,
                source_sha,
                str(path),
                str(path),
                path.name,
                _approved_generated_still_receipt(
                    source_id=source,
                    creator_id=creator,
                    campaign_id=campaign,
                    path=path,
                    sha256=source_sha,
                ),
                now,
                now,
            ),
        )
    conn.commit()
    reservations = _Reservations()
    return SimpleNamespace(
        conn=conn,
        domains=SimpleNamespace(
            inventory_reservations=reservations,
            creator_governance=_Governance(),
        ),
        reservations=reservations,
    )


def _set_plan(
    factory: SimpleNamespace,
    *,
    campaign: str,
    target: int = 1,
    mode: str = "static_reel",
) -> None:
    now = "2026-07-30T12:00:00Z"
    factory.conn.execute(
        """
        INSERT INTO creative_plans
        (id, name, target_account, daily_base_video_target, style_lanes_json,
         status, linked_campaign_slug, created_at, updated_at)
        VALUES (?, ?, 'fixture', ?, ?, 'active', ?, ?, ?)
        """,
        (
            f"plan_{campaign}",
            f"plan_{campaign}",
            target,
            json.dumps([{"mode": mode}]),
            campaign,
            now,
            now,
        ),
    )
    factory.conn.commit()


def test_daily_orchestrator_is_fair_deterministic_and_idempotent(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    try:
        preview = orchestrate_daily(
            factory, run_key="2026-07-30", max_items=2, now="2026-07-30T12:00:00Z"
        )
        assert [item["creator_slug"] for item in preview["items"]] == [
            "creator_1",
            "creator_2",
        ]
        assert (
            factory.conn.execute(
                "SELECT COUNT(*) FROM daily_orchestrator_runs"
            ).fetchone()[0]
            == 0
        )

        applied = orchestrate_daily(
            factory,
            run_key="2026-07-30",
            max_items=2,
            apply=True,
            now="2026-07-30T12:00:00Z",
        )
        repeated = orchestrate_daily(
            factory,
            run_key="2026-07-30",
            max_items=2,
            apply=True,
            now="2026-07-30T12:05:00Z",
        )
        assert applied["policyFingerprint"] == repeated["policyFingerprint"]
        assert applied["runId"] == repeated["runId"]
        assert (
            factory.conn.execute(
                "SELECT COUNT(*) FROM daily_orchestrator_runs"
            ).fetchone()[0]
            == 1
        )
        assert factory.reservations.expired == 2
    finally:
        factory.conn.close()


def test_daily_orchestrator_enforces_provider_capacity(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    try:
        _set_plan(factory, campaign="campaign_1", mode="calm_animation")
        blocked = orchestrate_daily(
            factory,
            run_key="provider-blocked",
            max_items=2,
            provider_cap=0,
            now="2026-07-30T12:00:00Z",
        )
        assert [item["creator_slug"] for item in blocked["items"]] == ["creator_2"]
        assert blocked["stopReason"] == "provider_capacity_exhausted"

        allowed = orchestrate_daily(
            factory,
            run_key="provider-allowed",
            max_items=2,
            provider_cap=1,
            now="2026-07-30T12:00:00Z",
        )
        assert {item["mode"] for item in allowed["items"]} == {
            "calm_animation",
            "static_reel",
        }
    finally:
        factory.conn.close()


def test_daily_orchestrator_can_fill_one_campaign_from_distinct_sources(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    second = tmp_path / "source_1b.jpg"
    second.write_bytes(b"source-1b")
    second_sha = hashlib.sha256(second.read_bytes()).hexdigest()
    factory.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, media_type, status, source_prompt, created_at, updated_at)
        VALUES ('source_1b', 'campaign_1', 'creator_1', ?, ?, ?, ?,
                'image', 'approved', ?, ?, ?)
        """,
        (
            second_sha,
            str(second),
            str(second),
            second.name,
            _approved_generated_still_receipt(
                source_id="source_1b",
                creator_id="creator_1",
                campaign_id="campaign_1",
                path=second,
                sha256=second_sha,
            ),
            "2026-07-30T12:00:00Z",
            "2026-07-30T12:00:00Z",
        ),
    )
    factory.conn.commit()
    try:
        _set_plan(factory, campaign="campaign_1", target=2)
        result = orchestrate_daily(
            factory,
            run_key="multiple-sources",
            max_items=3,
            per_creator_cap=2,
            per_campaign_cap=2,
            now="2026-07-30T12:00:00Z",
        )
        assert len(result["items"]) == 3
        campaign_one = [
            item for item in result["items"] if item["campaign_id"] == "campaign_1"
        ]
        assert {item["source_asset_id"] for item in campaign_one} == {
            "source_1",
            "source_1b",
        }
    finally:
        factory.conn.close()


def test_daily_orchestrator_rechecks_governance_before_claim(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    orchestrate_daily(
        factory,
        run_key="governance-change",
        max_items=1,
        apply=True,
        now="2026-07-30T12:00:00Z",
    )

    class _BlockedGovernance:
        def resolve_operation(self, **_kwargs):
            raise PermissionError("creator suspended")

    factory.domains.creator_governance = _BlockedGovernance()
    try:
        result = orchestrate_daily(
            factory,
            run_key="governance-change",
            max_items=1,
            apply=True,
            execute=True,
            now="2026-07-30T12:05:00Z",
        )
        assert result["items"][0]["state"] == "exhausted"
        assert result["items"][0]["error_code"].startswith("governance_changed:")
    finally:
        factory.conn.close()


def test_daily_orchestrator_recovers_stale_running_claim(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    calls = 0

    def succeeded_runner(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "results": [{"status": "completed"}],
        }

    try:
        planned = orchestrate_daily(
            factory,
            run_key="stale-claim",
            max_items=1,
            max_attempts=2,
            apply=True,
            now="2026-07-30T12:00:00Z",
        )
        factory.conn.execute(
            """
            UPDATE daily_orchestrator_runs
            SET status = 'running', updated_at = '2026-07-30T12:00:00Z'
            WHERE id = ?
            """,
            (planned["runId"],),
        )
        factory.conn.execute(
            """
            UPDATE daily_orchestrator_items
            SET state = 'running', attempt_count = 1,
                updated_at = '2026-07-30T12:00:00Z'
            WHERE run_id = ?
            """,
            (planned["runId"],),
        )
        factory.conn.commit()
        recovered = orchestrate_daily(
            factory,
            run_key="stale-claim",
            max_items=1,
            max_attempts=2,
            apply=True,
            execute=True,
            runner=succeeded_runner,
            now="2026-07-30T13:00:00Z",
        )
        assert calls == 1
        assert recovered["items"][0]["state"] == "completed"
        assert recovered["items"][0]["attempt_count"] == 2
    finally:
        factory.conn.close()


def test_daily_orchestrator_retries_with_bounded_backoff(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    calls = 0

    def failed_runner(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    try:
        result = orchestrate_daily(
            factory,
            run_key="failure",
            max_items=1,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=failed_runner,
            now="2026-07-30T12:00:00Z",
        )
        assert result["items"][0]["state"] == "exhausted"
        assert "provider unavailable" in result["items"][0]["error_code"]
        assert result["publishingAuthority"] is False
        orchestrate_daily(
            factory,
            run_key="failure",
            max_items=1,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=failed_runner,
            now="2026-07-30T13:00:00Z",
        )
        assert calls == 1
    finally:
        factory.conn.close()


def test_daily_caps_apply_across_distinct_run_keys(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    try:
        first = orchestrate_daily(
            factory,
            run_key="capacity-first",
            max_items=2,
            per_creator_cap=1,
            per_campaign_cap=1,
            apply=True,
            now="2026-07-30T12:00:00Z",
        )
        second = orchestrate_daily(
            factory,
            run_key="capacity-second",
            max_items=2,
            per_creator_cap=1,
            per_campaign_cap=1,
            apply=True,
            now="2026-07-30T13:00:00Z",
        )
        assert len(first["items"]) == 2
        assert second["items"] == []
        assert second["stopReason"] == "eligible_inventory_exhausted"
    finally:
        factory.conn.close()


def test_exhausted_source_cannot_reenter_under_new_run_key(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    calls: list[str] = []

    def failed_runner(*_args, **kwargs):
        calls.append(str(kwargs["campaign"]))
        raise RuntimeError("terminal provider failure")

    try:
        exhausted = orchestrate_daily(
            factory,
            run_key="terminal-first",
            max_items=1,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=failed_runner,
            now="2026-07-30T12:00:00Z",
        )
        exhausted_source = exhausted["items"][0]["source_asset_id"]
        next_run = orchestrate_daily(
            factory,
            run_key="terminal-second",
            max_items=2,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=failed_runner,
            now="2026-07-31T13:00:00Z",
        )
        assert exhausted_source not in {
            item["source_asset_id"] for item in next_run["items"]
        }
        assert calls.count("campaign_1") == 1
    finally:
        factory.conn.close()


def test_daily_orchestrator_does_not_complete_failed_batch_result(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)

    def returned_failure(*_args, **_kwargs):
        return {
            "requested": 1,
            "summary": {"requested": 1, "completed": 0, "failed": 1},
            "results": [{"status": "failed"}],
        }

    try:
        result = orchestrate_daily(
            factory,
            run_key="returned-failure",
            max_items=1,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=returned_failure,
            now="2026-07-30T12:00:00Z",
        )
        assert result["items"][0]["state"] == "exhausted"
        assert result["items"][0]["error_code"].endswith(
            "production_batch_incomplete_or_failed"
        )
    finally:
        factory.conn.close()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"summary": {}, "results": []},
        {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "results": [],
        },
        {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "results": [{"status": "unknown"}],
        },
        {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "results": ["completed"],
        },
        {
            "summary": {"requested": "1", "completed": 1, "failed": 0},
            "results": [{"status": "completed"}],
        },
    ],
)
def test_daily_orchestrator_rejects_malformed_or_unknown_runner_payloads(
    tmp_path: Path,
    payload: object,
) -> None:
    factory = _factory(tmp_path)

    def malformed_runner(*_args, **_kwargs):
        return payload

    try:
        result = orchestrate_daily(
            factory,
            run_key="malformed-runner",
            max_items=1,
            max_attempts=1,
            apply=True,
            execute=True,
            runner=malformed_runner,
            now="2026-07-30T12:00:00Z",
        )
        assert result["items"][0]["state"] == "exhausted"
        assert result["items"][0]["error_code"].endswith(
            "production_batch_incomplete_or_failed"
        )
    finally:
        factory.conn.close()


def test_daily_orchestrator_requests_supported_embedded_trending_audio(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    observed: list[str] = []

    def succeeded_runner(*_args, **kwargs):
        observed.append(str(kwargs["audio_preference"]))
        return {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "results": [{"status": "completed"}],
        }

    try:
        result = orchestrate_daily(
            factory,
            run_key="supported-trending-audio",
            max_items=1,
            apply=True,
            execute=True,
            runner=succeeded_runner,
            now="2026-07-30T12:00:00Z",
        )
        assert observed == ["embedded_trending_required"]
        assert result["items"][0]["state"] == "completed"
    finally:
        factory.conn.close()
