from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.cli_dispatch_operations import dispatch_operations_commands
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.creator_governance import CreatorGovernanceRepository
from campaign_factory.db import connect, init_db
from campaign_factory.incident_privacy import (
    CreatorPrivacyRepository,
    IncidentRepository,
)
from campaign_factory.operational_observability import (
    OperationalObservabilityRepository,
)
from campaign_factory.operator_authority import MUTATE, READ, classify_cli_operation
from campaign_factory.provider_spend import (
    ProviderOverspendError,
    record_provider_execution,
)

NOW = "2026-07-30T12:00:00.000000Z"


def _new_id_factory():
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}_{counter:04d}"

    return new_id


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "campaign.db")
    init_db(conn)
    conn.execute(
        """
        INSERT INTO models(id, slug, name, created_at, updated_at)
        VALUES ('model_1', 'creator-one', 'Creator One', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO campaigns
        (id, slug, name, root_path, created_at, updated_at)
        VALUES ('campaign_1', 'campaign-one', 'Campaign One', '/tmp', ?, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state
        (model_id, status, status_reason, changed_by, effective_at, version,
         updated_at)
        VALUES ('model_1', 'active', 'fixture', 'test', ?, 1, ?)
        """,
        (NOW, NOW),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance
        (campaign_id, model_id, lifecycle_status, blocker_codes_json,
         status_reason, changed_by, effective_at, version, updated_at)
        VALUES ('campaign_1', 'model_1', 'production_ready', '[]', 'fixture',
                'test', ?, 1, ?)
        """,
        (NOW, NOW),
    )
    conn.commit()
    return conn


def test_incident_cannot_close_without_verification_and_is_append_only(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    repository = IncidentRepository(conn, new_id=_new_id_factory(), utc_now=lambda: NOW)
    try:
        incident = repository.create(
            category="provider_ambiguity",
            severity="high",
            domain_owner="campaign_factory",
            owner="release_owner",
            next_action="reconcile provider result",
            operator="operator",
            campaign_id="campaign_1",
            external_effect_state="ambiguous",
        )
        with pytest.raises(ValueError, match="invalid_incident_transition"):
            repository.transition(
                incident["id"],
                state="closed",
                actor="operator",
                action="invalid_close",
                evidence={},
                closure_receipt={"bad": True},
            )
        for state in ("triaged", "contained", "repairing", "reconciled"):
            incident = repository.transition(
                incident["id"],
                state=state,
                actor="operator",
                action=f"move_to_{state}",
                evidence={"ticket": "INC-1"},
                repair_actions=(
                    [{"action": "provider_reconciled"}]
                    if state == "reconciled"
                    else None
                ),
            )
        with pytest.raises(ValueError, match="verification_evidence_required"):
            repository.transition(
                incident["id"],
                state="verified",
                actor="operator",
                action="verify",
                evidence={"ticket": "INC-1"},
            )
        incident = repository.transition(
            incident["id"],
            state="verified",
            actor="operator",
            action="verify",
            evidence={"ticket": "INC-1"},
            verification_evidence=[{"kind": "provider_receipt", "id": "r_1"}],
        )
        incident = repository.transition(
            incident["id"],
            state="closed",
            actor="operator",
            action="close",
            evidence={"ticket": "INC-1"},
            closure_receipt={"decision": "reconciled", "operator": "operator"},
        )
        assert incident["state"] == "closed"
        assert len(incident["events"]) == 7
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE incident_events SET action = 'rewritten' WHERE incident_id = ?",
                (incident["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained evidence"):
            conn.execute("DELETE FROM incident_records WHERE id = ?", (incident["id"],))
    finally:
        conn.close()


def test_privacy_revocation_blocks_future_creator_operations(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    new_id = _new_id_factory()
    privacy = CreatorPrivacyRepository(conn, new_id=new_id, utc_now=lambda: NOW)
    governance = CreatorGovernanceRepository(
        conn,
        new_id=new_id,
        slugify=lambda value: value,
        utc_now=lambda: NOW,
        managed_root=tmp_path,
    )
    try:
        request = privacy.create_request(
            creator="creator-one",
            request_type="consent_revocation",
            operator="privacy_officer",
            legal_basis="creator withdrew consent",
            deletion_scope={"allCreatorMedia": True},
            retention_policy={"auditEvidence": "retain"},
        )
        assert request["future_use_required"] == 1
        assert privacy.privacy_report("model_1")["futureUseBlocked"] is True
        with pytest.raises(PermissionError, match="creator_future_use_blocked"):
            governance.resolve_operation(
                creator="creator-one",
                campaign="campaign-one",
                operation="generation",
                provider="higgsfield",
            )
    finally:
        conn.close()


def test_legal_hold_and_protected_evidence_block_deletion_truth(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    privacy = CreatorPrivacyRepository(
        conn, new_id=_new_id_factory(), utc_now=lambda: NOW
    )
    try:
        request = privacy.create_request(
            creator="model_1",
            request_type="deletion_request",
            operator="privacy_officer",
            legal_basis="verified creator request",
            deletion_scope={"sourceAssets": ["all"]},
        )
        missing = tmp_path / "already-absent.mp4"
        inventory = privacy.register_inventory(
            creator="model_1",
            request_id=request["id"],
            data_class="source_asset",
            locator=str(missing),
            operator="privacy_officer",
            policy={"locatorType": "path"},
        )
        protected = privacy.register_inventory(
            creator="model_1",
            request_id=request["id"],
            data_class="financial_evidence",
            locator="ledger:event_1",
            operator="privacy_officer",
            contains_bytes=False,
            retention_state="retain_financial",
        )
        hold = privacy.place_legal_hold(
            creator="model_1",
            request_id=request["id"],
            scope={"allCreatorData": True},
            legal_authority="counsel instruction",
            reason="active dispute",
            operator="legal",
        )
        plan = privacy.deletion_plan("model_1")
        assert plan["blockedByLegalHold"] is True
        assert plan["eligibleInventory"] == []
        with pytest.raises(PermissionError, match="under_legal_hold"):
            privacy.disposition(
                inventory["id"],
                state="deletion_verified",
                operator="privacy_officer",
                evidence={"pathAbsent": True},
            )
        privacy.release_legal_hold(
            hold["id"],
            operator="legal",
            receipt={"authority": "counsel", "decision": "release"},
        )
        disposition = privacy.disposition(
            inventory["id"],
            state="deletion_verified",
            operator="privacy_officer",
            evidence={"pathAbsent": True, "checkedAt": NOW},
        )
        assert disposition["retention_state"] == "deletion_verified"
        assert disposition["verification"]["pathAbsent"] is True
        tombstone = privacy.disposition(
            inventory["id"],
            state="tombstoned",
            operator="privacy_officer",
            evidence={
                "priorState": "deletion_verified",
                "pathAbsent": True,
                "retainedRecordOnly": True,
            },
        )
        assert tombstone["retention_state"] == "tombstoned"
        assert tombstone["verification"]["retainedRecordOnly"] is True
        assert len(tombstone["events"]) == 3
        with pytest.raises(PermissionError, match="retention_is_mandatory"):
            privacy.disposition(
                protected["id"],
                state="deletion_verified",
                operator="privacy_officer",
                evidence={"pathAbsent": True},
            )
        final_plan = privacy.deletion_plan("model_1")
        assert [item["id"] for item in final_plan["protectedEvidence"]] == [
            protected["id"]
        ]
    finally:
        conn.close()


def test_observability_never_equates_loaded_with_executing_and_marks_stale(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute(
            """
            INSERT INTO activity_events
            (id, event_type, status, message, metadata_json, created_at)
            VALUES ('loaded_1', 'launch_agent_loaded', 'info',
                    'launch agent configuration loaded', '{}',
                    '2026-07-30T11:59:00.000000Z')
            """
        )
        conn.execute(
            """
            INSERT INTO pipeline_jobs
            (id, job_type, campaign_id, status, effect_state, recovery_policy,
             input_json, result_json, attempt_count, created_at, updated_at)
            VALUES ('job_stale', 'fixture', 'campaign_1', 'queued',
                    'PRE_EFFECT', 'NEVER_AUTOMATIC', '{}', '{}', 0,
                    '2026-07-30T09:00:00.000000Z',
                    '2026-07-30T09:00:00.000000Z')
            """
        )
        conn.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'running', started_at = created_at, attempt_count = 1
            WHERE id = 'job_stale'
            """
        )
        conn.commit()
        report = OperationalObservabilityRepository(conn, utc_now=lambda: NOW).report(
            stale_after_minutes=30
        )
        assert report["runtime"]["loaded"] is True
        assert report["runtime"]["executing"] is False
        assert report["runtime"]["warning"]
        assert report["health"] == "degraded"
        stale_job = next(
            item for item in report["observations"] if item["sourceId"] == "job_stale"
        )
        assert stale_job["stale"] is True
        assert stale_job["fresh"] is False
    finally:
        conn.close()


def test_provider_overspend_creates_central_manual_hold_incident(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute(
            """
            INSERT INTO provider_spend_authorizations
            (authorization_id, reservation_id, provider, campaign_id, cohort_id,
             request_fingerprint, amount, unit, scope_json,
             provider_quote_json, creator_id, status, issued_at, expires_at)
            VALUES ('auth_overspend', 'reservation_overspend', 'higgsfield',
                    'campaign_1', 'cohort_1', 'request_overspend', 5,
                    'higgsfield_credits', '{}', '{}', 'model_1', 'consumed',
                    ?, '2026-07-30T13:00:00.000000Z')
            """,
            (NOW,),
        )
        conn.commit()
        authorization = {
            "authorizationId": "auth_overspend",
            "reservationId": "reservation_overspend",
            "providerQuote": {
                "provider": "higgsfield",
                "amount": 5,
                "unit": "higgsfield_credits",
            },
            "scope": {
                "requestFingerprint": "request_overspend",
                "cohortId": "cohort_1",
            },
        }
        with pytest.raises(ProviderOverspendError):
            record_provider_execution(
                conn,
                authorization=authorization,
                execution={
                    "events": [
                        {
                            "provider": "higgsfield",
                            "operation": "image_create",
                            "model": "text2image_soul_v2",
                            "jobId": "job_overspend",
                            "actualCredits": 7,
                        }
                    ]
                },
            )
        incident = conn.execute(
            """
            SELECT * FROM incident_records
            WHERE category = 'overspend' AND campaign_id = 'campaign_1'
            """
        ).fetchone()
        assert incident is not None
        assert incident["state"] == "manual_hold"
        assert incident["severity"] == "critical"
        assert (
            conn.execute(
                """
            SELECT COUNT(*) FROM incident_evidence_links
            WHERE incident_id = ? AND evidence_type = 'ai_cost_event'
            """,
                (incident["id"],),
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_operator_cli_previews_are_read_only_and_apply_is_authority_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _db(tmp_path)
    new_id = _new_id_factory()
    domains = SimpleNamespace(
        incidents=IncidentRepository(conn, new_id=new_id, utc_now=lambda: NOW),
        creator_privacy=CreatorPrivacyRepository(
            conn, new_id=new_id, utc_now=lambda: NOW
        ),
    )
    factory = SimpleNamespace(conn=conn, domains=domains)
    parser = build_cli_parser()
    try:
        preview = parser.parse_args(
            [
                "incident-create",
                "--category",
                "missing_files",
                "--severity",
                "high",
                "--domain-owner",
                "campaign_factory",
                "--owner",
                "operator",
                "--next-action",
                "reconcile",
                "--operator",
                "operator",
            ]
        )
        assert classify_cli_operation(preview) == (READ, True)
        assert dispatch_operations_commands(preview, factory, None) == 0
        capsys.readouterr()
        assert conn.execute("SELECT COUNT(*) FROM incident_records").fetchone()[0] == 0

        applied = parser.parse_args(
            [
                "creator-privacy-request",
                "--creator",
                "model_1",
                "--request-type",
                "consent_revocation",
                "--operator",
                "privacy",
                "--legal-basis",
                "withdrawn",
                "--apply",
            ]
        )
        assert classify_cli_operation(applied) == (MUTATE, False)
    finally:
        conn.close()
