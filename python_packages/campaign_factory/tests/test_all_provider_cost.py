from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.all_provider_cost import (
    BudgetLimits,
    authorize_reference_paid_action,
    begin_paid_action_attempt,
    build_budget_override,
    issue_paid_action_authorization,
    reconcile_paid_action_cost,
    reconcile_reference_paid_action,
    unified_cost_report,
)
from campaign_factory.cost_tracker import ensure_cost_table, record_ai_cost
from campaign_factory.db import init_db
from campaign_factory.prompt_registry import PROMPT_REGISTRY, bind_campaign_prompt
from creator_os_core.provider_spend import (
    build_paid_action_quote,
    build_paid_action_spend_scope,
)
from reference_factory.prompt_registry import (
    PROMPT_REGISTRY as REFERENCE_PROMPT_REGISTRY,
)
from reference_factory.prompt_registry import bind_reference_prompt

SECRET = "test-only-unified-provider-cost-secret-32-bytes"


def _campaign_conn(database: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.row_factory = None
    return conn


def _scope(
    *,
    provider: str = "openai",
    creator: str = "creator_1",
    campaign: str = "campaign_1",
    run: str = "run_1",
    request: str = "a" * 64,
) -> dict:
    return build_paid_action_spend_scope(
        provider=provider,
        provider_model="gpt-5" if provider == "openai" else "gemini-3-pro-image",
        action_type="recreation_prompt_pack",
        creator_id=creator,
        campaign_id=campaign,
        run_id=run,
        input_fingerprints={"request": request},
        parameters={"maximumCalls": 1},
    )


def _quote(provider: str = "openai", amount: float = 1.25) -> dict:
    return build_paid_action_quote(
        provider=provider,
        model="gpt-5" if provider == "openai" else "gemini-3-pro-image",
        amount=amount,
        source="fixture_exact_quote",
        pricing_version="fixture.v1",
    )


def _limits(cap: float = 10) -> BudgetLimits:
    return BudgetLimits(cap, cap, cap, cap, cap, cap)


def _authorized_reference_action(conn: sqlite3.Connection) -> dict:
    compiled_prompt = "analyze this authorized reference"
    prompt_inputs = {"referenceId": "ref_1", "promptStyle": "minimal"}
    prompt_governance = bind_reference_prompt(
        prompt_id="reference.grok_analysis",
        version="1",
        provider="xai",
        model="grok-4",
        compiled_prompt=compiled_prompt,
        inputs=prompt_inputs,
    )
    return authorize_reference_paid_action(
        conn,
        provider="xai",
        model="grok-4",
        action_type="reference_analysis",
        request_fingerprint=prompt_governance["compiledPromptFingerprint"],
        creator_id="creator_1",
        campaign_id="campaign_1",
        run_id="run_reference_1",
        reference_id="ref_1",
        reference_source_sha256="d" * 64,
        secret=SECRET,
        quote=build_paid_action_quote(
            provider="xai",
            model="grok-4",
            amount=0.50,
            source="fixture_exact_quote",
            pricing_version="fixture.v1",
        ),
        limits=_limits(),
        prompt_governance=prompt_governance,
        current_prompt_registry=REFERENCE_PROMPT_REGISTRY,
        compiled_prompt=compiled_prompt,
        prompt_inputs=prompt_inputs,
        governance_context={
            "schema": "campaign_factory.creator_operation_context.v1",
            "creatorId": "creator_1",
            "campaignId": "campaign_1",
            "operation": "reference_analysis",
            "provider": "xai",
            "sourceAssetId": "source_reference_1",
            "governanceFingerprint": "e" * 64,
        },
    )


def test_paid_action_lifecycle_preserves_unknown_then_reconciles_refund() -> None:
    conn = _campaign_conn()
    authorization = issue_paid_action_authorization(
        conn,
        scope=_scope(),
        quote=_quote(),
        secret=SECRET,
        limits=_limits(),
    )
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=SECRET,
        attempt_id="attempt_1",
    )
    pending = conn.execute(
        """
        SELECT creator_id, campaign_id, action_type, quoted_usd,
               usd_cost_state, reconciliation_state
        FROM ai_cost_events WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    assert pending == (
        "creator_1",
        "campaign_1",
        "recreation_prompt_pack",
        1.25,
        "unknown",
        "pending",
    )

    receipt = reconcile_paid_action_cost(
        conn,
        event_id=event_id,
        actual_usd=1.10,
        refunded_usd=0.20,
        provider_reference="response_1",
    )
    assert receipt["actualUsd"] == 1.10
    assert receipt["refundedUsd"] == 0.20
    assert receipt["netUsd"] == pytest.approx(0.90)
    assert receipt["reconciliationState"] == "refunded"
    report = unified_cost_report(conn)
    assert report["groups"][0]["provider"] == "openai"
    assert report["groups"][0]["actualUsd"] == 1.10
    assert report["groups"][0]["refundedUsd"] == 0.20
    assert report["groups"][0]["unknownAttempts"] == 0


def test_unknown_provider_cost_never_becomes_zero() -> None:
    conn = _campaign_conn()
    authorization = issue_paid_action_authorization(
        conn,
        scope=_scope(),
        quote=_quote(),
        secret=SECRET,
        limits=_limits(),
    )
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=SECRET,
        attempt_id="attempt_unknown",
    )
    receipt = reconcile_paid_action_cost(
        conn,
        event_id=event_id,
        actual_usd=None,
        unknown_reason="provider_cost_not_exposed",
    )
    row = conn.execute(
        """
        SELECT estimated_cost_usd, cost_state, usd_cost_state,
               unknown_reason, reconciliation_state
        FROM ai_cost_events WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    assert receipt["netUsd"] is None
    assert row == (
        0.0,
        "unknown",
        "unknown",
        "provider_cost_not_exposed",
        "unknown",
    )
    report = unified_cost_report(conn)
    assert report["groups"][0]["actualUsd"] is None
    assert report["groups"][0]["unknownAttempts"] == 1


def test_unified_cost_report_is_schema_and_data_read_only() -> None:
    conn = _campaign_conn()
    schema_version = conn.execute("PRAGMA schema_version").fetchone()[0]
    total_changes = conn.total_changes
    objects = conn.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        ORDER BY type, name
        """
    ).fetchall()

    assert unified_cost_report(conn)["groups"] == []

    assert conn.execute("PRAGMA schema_version").fetchone()[0] == schema_version
    assert conn.total_changes == total_changes
    assert (
        conn.execute(
            """
            SELECT type, name, sql FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger')
            ORDER BY type, name
            """
        ).fetchall()
        == objects
    )


def test_unified_cost_report_requires_v5_without_creating_schema() -> None:
    conn = sqlite3.connect(":memory:")

    with pytest.raises(RuntimeError, match="campaign_schema_v5_required:tables"):
        unified_cost_report(conn)

    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone() == (0,)
    assert conn.total_changes == 0


def test_paid_prompt_requires_current_exact_registry_material_before_authorization() -> (
    None
):
    inputs = {
        "creator": "creator_1",
        "intent": "passive_selfie",
        "creatorImageSha256": "a" * 64,
        "referenceVideoSha256": None,
    }
    prompt = "The image is the approved creator identity for a calm short animation."
    governance = bind_campaign_prompt(
        prompt_id="campaign.openai_recreation_pack",
        version="3",
        provider="openai",
        model="gpt-5",
        compiled_prompt=prompt,
        inputs=inputs,
    )
    scope = build_paid_action_spend_scope(
        provider="openai",
        provider_model="gpt-5",
        action_type="recreation_prompt_pack",
        creator_id="creator_1",
        campaign_id="campaign_1",
        run_id="run_prompt",
        input_fingerprints={"request": "a" * 64},
        parameters={"maximumCalls": 1},
        prompt_governance=governance,
    )
    conn = _campaign_conn()
    with pytest.raises(PermissionError, match="current_prompt_verification_required"):
        issue_paid_action_authorization(
            conn,
            scope=scope,
            quote=_quote(),
            secret=SECRET,
            limits=_limits(),
        )

    changed_inputs = {**inputs, "intent": "substituted"}
    with pytest.raises(PermissionError, match="stale_or_material_mismatch"):
        issue_paid_action_authorization(
            conn,
            scope=scope,
            quote=_quote(),
            secret=SECRET,
            limits=_limits(),
            current_prompt_registry=PROMPT_REGISTRY,
            compiled_prompt=prompt,
            prompt_inputs=changed_inputs,
        )

    authorization = issue_paid_action_authorization(
        conn,
        scope=scope,
        quote=_quote(),
        secret=SECRET,
        limits=_limits(),
        current_prompt_registry=PROMPT_REGISTRY,
        compiled_prompt=prompt,
        prompt_inputs=inputs,
    )
    with pytest.raises(PermissionError, match="current_prompt_verification_required"):
        begin_paid_action_attempt(
            conn,
            authorization=authorization,
            secret=SECRET,
            attempt_id="attempt_without_current_prompt",
        )
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=SECRET,
        attempt_id="attempt_verified_prompt",
        current_prompt_registry=PROMPT_REGISTRY,
        compiled_prompt=prompt,
        prompt_inputs=inputs,
    )
    assert event_id


def test_caps_cover_global_creator_campaign_provider_and_run() -> None:
    conn = _campaign_conn()
    issue_paid_action_authorization(
        conn,
        scope=_scope(request="a" * 64),
        quote=_quote(amount=1.25),
        secret=SECRET,
        limits=_limits(cap=2),
    )
    with pytest.raises(PermissionError, match="provider_budget_exceeded"):
        issue_paid_action_authorization(
            conn,
            scope=_scope(request="b" * 64),
            quote=_quote(amount=1.25),
            secret=SECRET,
            limits=_limits(cap=2),
        )


def test_caps_count_reconciled_actual_overage_instead_of_only_quote() -> None:
    conn = _campaign_conn()
    authorization = issue_paid_action_authorization(
        conn,
        scope=_scope(request="a" * 64),
        quote=_quote(amount=1),
        secret=SECRET,
        limits=_limits(cap=3),
    )
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=SECRET,
        attempt_id="attempt_over_quote",
    )
    reconcile_paid_action_cost(conn, event_id=event_id, actual_usd=2.5)

    with pytest.raises(PermissionError, match="provider_budget_exceeded"):
        issue_paid_action_authorization(
            conn,
            scope=_scope(request="b" * 64),
            quote=_quote(amount=1),
            secret=SECRET,
            limits=_limits(cap=3),
        )


def test_caps_reserve_quote_while_actual_cost_is_unknown() -> None:
    conn = _campaign_conn()
    authorization = issue_paid_action_authorization(
        conn,
        scope=_scope(request="a" * 64),
        quote=_quote(amount=1.5),
        secret=SECRET,
        limits=_limits(cap=2),
    )
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=SECRET,
        attempt_id="attempt_unknown_cap",
    )
    reconcile_paid_action_cost(
        conn,
        event_id=event_id,
        actual_usd=None,
        unknown_reason="provider_cost_not_exposed",
    )

    with pytest.raises(PermissionError, match="provider_budget_exceeded"):
        issue_paid_action_authorization(
            conn,
            scope=_scope(request="b" * 64),
            quote=_quote(amount=0.75),
            secret=SECRET,
            limits=_limits(cap=2),
        )


def test_budget_checks_use_the_authorization_clock_consistently() -> None:
    conn = _campaign_conn()
    at = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    issue_paid_action_authorization(
        conn,
        scope=_scope(request="a" * 64),
        quote=_quote(amount=1.25),
        secret=SECRET,
        limits=_limits(cap=2),
        now=at,
    )
    with pytest.raises(PermissionError, match="provider_budget_exceeded"):
        issue_paid_action_authorization(
            conn,
            scope=_scope(request="b" * 64),
            quote=_quote(amount=1.25),
            secret=SECRET,
            limits=_limits(cap=2),
            now=at,
        )


def test_budget_override_is_scoped_signed_and_auditable() -> None:
    conn = _campaign_conn()
    scope = _scope()
    override = build_budget_override(
        scope=scope,
        allowed_breaches=[
            "global_daily",
            "global_monthly",
            "creator",
            "campaign",
            "provider",
            "run",
        ],
        operator="release-owner",
        reason="approved one-call qualification",
        secret=SECRET,
    )
    authorization = issue_paid_action_authorization(
        conn,
        scope=scope,
        quote=_quote(amount=1.25),
        secret=SECRET,
        limits=_limits(cap=1),
        override_receipt=override,
    )
    assert authorization["budgetOverride"]["operator"] == "release-owner"
    assert authorization["budgetOverride"]["reason"] == (
        "approved one-call qualification"
    )


def test_attempt_consume_and_ledger_insert_roll_back_together_after_crash(
    tmp_path: Path,
) -> None:
    database = tmp_path / "campaign.db"
    conn = _campaign_conn(database)
    authorization = issue_paid_action_authorization(
        conn,
        scope=_scope(),
        quote=_quote(),
        secret=SECRET,
        limits=_limits(),
    )

    def crash_after_consume() -> None:
        raise RuntimeError("simulated_process_crash")

    with pytest.raises(RuntimeError, match="simulated_process_crash"):
        begin_paid_action_attempt(
            conn,
            authorization=authorization,
            secret=SECRET,
            attempt_id="attempt_crash",
            after_consume=crash_after_consume,
        )
    conn.close()

    reopened = sqlite3.connect(database)
    status = reopened.execute(
        """
        SELECT status FROM provider_spend_authorizations
        WHERE authorization_id = ?
        """,
        (authorization["authorizationId"],),
    ).fetchone()
    attempts = reopened.execute("SELECT COUNT(*) FROM ai_cost_events").fetchone()
    assert status == ("authorized",)
    assert attempts == (0,)


def test_cost_helper_never_commits_caller_owned_transaction() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_cost_table(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    event_id = record_ai_cost(
        conn,
        provider="openai",
        operation="test",
        campaign_id="campaign_1",
        estimated_cost_usd=0.25,
    )
    assert conn.in_transaction is True
    conn.rollback()
    assert (
        conn.execute(
            "SELECT 1 FROM ai_cost_events WHERE id = ?", (event_id,)
        ).fetchone()
        is None
    )


def test_paid_action_entrypoint_rejects_caller_owned_transaction() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_cost_table(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        RuntimeError, match="paid_action_operation_requires_clean_transaction"
    ):
        issue_paid_action_authorization(
            conn,
            scope=_scope(),
            quote=_quote(),
            secret=SECRET,
            limits=_limits(),
        )
    assert conn.in_transaction is True
    conn.rollback()


def test_reference_paid_action_uses_campaign_ledger_and_reconciliation() -> None:
    conn = _campaign_conn()
    paid_action = _authorized_reference_action(conn)
    assert paid_action["attemptPersistedBeforeExternalEffect"] is True
    assert paid_action["creatorId"] == "creator_1"
    assert paid_action["campaignId"] == "campaign_1"
    event_id = paid_action["campaignLedgerEventId"]
    pending = conn.execute(
        """
        SELECT authorization_id, attempt_id, reconciliation_state
        FROM ai_cost_events WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    assert pending == (
        paid_action["authorizationId"],
        paid_action["attemptId"],
        "pending",
    )

    receipt = reconcile_reference_paid_action(
        conn,
        paid_action=paid_action,
        actual_usd=None,
        unknown_reason="provider_cost_not_exposed",
    )
    assert receipt["eventId"] == event_id
    assert receipt["reconciliationState"] == "unknown"
    assert conn.execute(
        "SELECT COUNT(*) FROM ai_cost_events WHERE id = ?", (event_id,)
    ).fetchone() == (1,)


@pytest.mark.parametrize(
    ("field", "replacement", "dimension"),
    [
        ("campaignLedgerEventId", "cost_missing", "event"),
        ("authorizationId", "spauth_wrong", "authorization"),
        ("attemptId", "refattempt_wrong", "attempt"),
        ("provider", "gemini", "provider"),
        ("creatorId", "creator_2", "creator"),
        ("campaignId", "campaign_2", "campaign"),
        ("actionType", "reference_prompt_compilation", "action"),
        ("runId", "run_reference_2", "run"),
        ("requestFingerprint", "b" * 64, "request_fingerprint"),
        ("spendRequestFingerprint", "c" * 64, "spend_request_fingerprint"),
        ("model", "grok-substituted", "model"),
        ("referenceId", "ref_2", "reference"),
        ("referenceSourceSha256", "f" * 64, "reference"),
        ("sourceAssetId", "source_reference_2", "reference"),
        ("governanceFingerprint", "f" * 64, "governance"),
    ],
)
def test_reference_cost_reconciliation_rejects_mismatched_context_dimension(
    field: str,
    replacement: str,
    dimension: str,
) -> None:
    conn = _campaign_conn()
    paid_action = _authorized_reference_action(conn)
    event_id = paid_action["campaignLedgerEventId"]
    substituted = {**paid_action, field: replacement}

    with pytest.raises(
        PermissionError,
        match=f"reference_paid_action_ledger_binding_mismatch:{dimension}",
    ):
        reconcile_reference_paid_action(
            conn,
            paid_action=substituted,
            actual_usd=0.42,
            provider_reference="provider_response_wrongly_attributed",
        )

    assert conn.execute(
        """
        SELECT reconciliation_state, actual_usd, provider_reference
        FROM ai_cost_events WHERE id = ?
        """,
        (event_id,),
    ).fetchone() == ("pending", None, None)


@pytest.mark.parametrize(
    ("column", "replacement", "dimension"),
    [
        ("authorization_id", "spauth_wrong", "authorization"),
        ("attempt_id", "refattempt_wrong", "attempt"),
        ("provider", "gemini", "provider"),
        ("creator_id", "creator_2", "creator"),
        ("campaign_id", "campaign_2", "campaign"),
        ("operation", "reference_prompt_compilation", "action"),
        ("action_type", "reference_prompt_compilation", "action"),
        ("run_id", "run_reference_2", "run"),
        ("source_event_key", "paid_action:wrong:wrong", "event"),
        ("reservation_id", "spres_wrong", "event"),
    ],
)
def test_reference_cost_reconciliation_rejects_mismatched_ledger_dimension(
    column: str,
    replacement: str,
    dimension: str,
) -> None:
    conn = _campaign_conn()
    paid_action = _authorized_reference_action(conn)
    event_id = paid_action["campaignLedgerEventId"]
    conn.execute(
        f"UPDATE ai_cost_events SET {column} = ? WHERE id = ?",
        (replacement, event_id),
    )
    conn.commit()

    with pytest.raises(
        PermissionError,
        match=f"reference_paid_action_ledger_binding_mismatch:{dimension}",
    ):
        reconcile_reference_paid_action(
            conn,
            paid_action=paid_action,
            actual_usd=0.42,
        )
