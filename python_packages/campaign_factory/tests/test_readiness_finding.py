from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from campaign_factory.config import Settings
from campaign_factory.execution_readiness import ExecutionReadinessRepository
from campaign_factory.readiness_finding import (
    execution_blocker_detail,
    make_readiness_finding,
    readiness_finding_payloads,
    readiness_findings_from_codes,
)


def test_readiness_finding_contract_is_exact_and_immutable() -> None:
    finding = make_readiness_finding(
        "schedule_plan_not_ready:missing_inventory",
        severity="blocker",
        evidence={"source": "test"},
    )

    assert finding.to_payload() == {
        "code": "schedule_plan_not_ready:missing_inventory",
        "severity": "blocker",
        "owner": "schedule_plan",
        "operatorAction": "rerun_campaign_schedule_plan",
        "sourceCheck": "test",
        "affectedAssetId": None,
        "affectedAccountId": None,
        "affectedPostId": None,
        "evidence": {
            "source": "test",
            "explanation": "The schedule plan is not ready.",
            "sourceReason": "missing_inventory",
        },
        "retryable": True,
    }
    assert execution_blocker_detail(finding) == {
        "code": "schedule_plan_not_ready:missing_inventory",
        "category": "schedule_plan",
        "explanation": "The schedule plan is not ready.",
        "nextAction": "rerun_campaign_schedule_plan",
        "sourceReason": "missing_inventory",
    }
    with pytest.raises(AttributeError):
        finding.code = "changed"  # type: ignore[misc]


def test_readiness_finding_payloads_dedupe_exact_evidence() -> None:
    findings = readiness_findings_from_codes(
        ["missing_audio", "missing_audio"],
        severity="blocker",
        evidence={"renderedAssetId": "asset_1"},
    )

    assert readiness_finding_payloads([*findings, *findings]) == [
        {
            "code": "missing_audio",
            "severity": "blocker",
            "owner": "audio",
            "operatorAction": "select_or_verify_native_audio",
            "sourceCheck": "readiness_finding",
            "affectedAssetId": "asset_1",
            "affectedAccountId": None,
            "affectedPostId": None,
            "evidence": {"renderedAssetId": "asset_1"},
            "retryable": True,
        }
    ]


def test_readiness_finding_exposes_affected_entities_and_source_check() -> None:
    finding = make_readiness_finding(
        "trial_capability_unknown",
        severity="blocker",
        source_check="account_projection",
        affected_account_id="account_1",
        affected_post_id="post_1",
        evidence={"projectionCheckedAt": "2026-07-15T00:00:00Z"},
    )

    payload = finding.to_payload()
    assert payload["sourceCheck"] == "account_projection"
    assert payload["affectedAssetId"] is None
    assert payload["affectedAccountId"] == "account_1"
    assert payload["affectedPostId"] == "post_1"


@pytest.mark.parametrize(
    ("code", "owner", "action"),
    [
        (
            "ai_generated_media_disclosure_required",
            "creative_approval",
            "review_and_approve_ai_disclosure_caption",
        ),
        (
            "creative_approval_v1_not_operational",
            "creative_approval",
            "create_exact_creative_approval_v2",
        ),
    ],
)
def test_creative_approval_findings_have_exact_recovery_actions(
    code: str, owner: str, action: str
) -> None:
    finding = make_readiness_finding(code, severity="blocker").to_payload()
    assert finding["owner"] == owner
    assert finding["operatorAction"] == action
    assert finding["retryable"] is True


def test_execution_readiness_aggregates_canonical_findings(
    tmp_path: Path,
) -> None:
    repository = ExecutionReadinessRepository(
        sqlite3.connect(":memory:"),
        Settings(threadsdash_root=tmp_path / "missing-threadsdash"),
        creator_label=lambda value: str(value),
        creator_os_daily_plan=lambda **_kwargs: {"creators": [{"safeAccounts": 0}]},
        creator_os_draft_items=lambda _items: [],
        creator_os_schedule_safe_drafts=lambda _creator, _items: [],
        creator_os_account_health_report=lambda **_kwargs: {"summary": {}},
        creator_os_execution_draft_blockers=lambda _creator, _items: [],
        creator_os_execution_account_health_blockers=lambda _report: [],
        creator_os_execution_account_health_warnings=lambda _report: [],
        utc_now=lambda: "2026-07-15T00:00:00+00:00",
    )

    result = repository.creator_os_execution_readiness(
        creator="Stacey",
        requested_count=1,
        schedule_plan={"status": "blocked", "blockingReason": "no_inventory"},
        time_plan={"status": "blocked", "blockingReason": "no_slots"},
    )

    blocker_findings = [
        finding for finding in result["findings"] if finding["severity"] == "blocker"
    ]
    assert sorted(finding["code"] for finding in blocker_findings) == result["blockers"]
    assert all(
        set(finding)
        == {
            "code",
            "severity",
            "owner",
            "operatorAction",
            "sourceCheck",
            "affectedAssetId",
            "affectedAccountId",
            "affectedPostId",
            "evidence",
            "retryable",
        }
        for finding in result["findings"]
    )
    assert {
        detail["code"]: detail["nextAction"] for detail in result["blockerDetails"]
    }["insufficient_safe_accounts"] == "repair_or_wait_for_account_health"
