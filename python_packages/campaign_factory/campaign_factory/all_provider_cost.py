"""Unified authorization, reservation, attempt, and cost reconciliation.

This extends Campaign Factory's existing provider authorization and
``ai_cost_events`` stores.  It deliberately creates no second ledger.
"""

from __future__ import annotations

import datetime
import hmac
import json
import math
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from creator_os_core.prompt_governance import verify_prompt_receipt
from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA_V3,
    USD_UNIT,
    build_paid_action_quote,
    build_paid_action_spend_scope,
    sign_authorization,
    verify_authorization_v3,
)
from creator_os_core.runtime_guards import global_kill_switch_active

from .cost_tracker import record_ai_cost
from .provider_spend import AUTHORIZATION_TABLE

LEDGER_SCHEMA = "campaign_factory.unified_paid_action_ledger.v1"
OVERRIDE_SCHEMA = "campaign_factory.provider_budget_override.v1"
_PROMPT_MATERIAL_MISSING = object()
REFERENCE_CONTEXT_SCHEMA = "campaign_factory.reference_paid_action_context.v1"


@dataclass(frozen=True)
class BudgetLimits:
    global_daily_usd: float
    global_monthly_usd: float
    creator_daily_usd: float
    campaign_daily_usd: float
    provider_daily_usd: float
    run_usd: float

    def validated(self) -> BudgetLimits:
        for name, value in self.__dict__.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        return self


def budget_limits_from_env(*, provider: str, run_cap_usd: float) -> BudgetLimits:
    """Load fail-closed global/provider/creator/campaign budget ceilings."""

    provider_key = "".join(char if char.isalnum() else "_" for char in provider.upper())
    return BudgetLimits(
        global_daily_usd=_positive_env("CREATOR_OS_PAID_DAILY_CAP_USD"),
        global_monthly_usd=_positive_env("CREATOR_OS_PAID_MONTHLY_CAP_USD"),
        creator_daily_usd=_positive_env("CREATOR_OS_CREATOR_DAILY_CAP_USD"),
        campaign_daily_usd=_positive_env("CREATOR_OS_CAMPAIGN_DAILY_CAP_USD"),
        provider_daily_usd=_positive_env(f"CREATOR_OS_{provider_key}_DAILY_CAP_USD"),
        run_usd=_positive_number(run_cap_usd, "run cap"),
    ).validated()


def issue_paid_action_authorization(
    conn: sqlite3.Connection,
    *,
    scope: Mapping[str, Any],
    quote: Mapping[str, Any],
    secret: str,
    limits: BudgetLimits,
    governance_context: Mapping[str, Any] | None = None,
    override_receipt: Mapping[str, Any] | None = None,
    current_prompt_registry: Mapping[str, Any] | None = None,
    compiled_prompt: Any = _PROMPT_MATERIAL_MISSING,
    prompt_inputs: Any = _PROMPT_MATERIAL_MISSING,
    now: datetime.datetime | None = None,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    """Atomically reserve one generic USD action under every configured cap."""

    if global_kill_switch_active():
        raise PermissionError("creator_os_global_kill_switch_active")
    limits.validated()
    current = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    if not 60 <= ttl_seconds <= 3600:
        raise ValueError("paid action authorization TTL must be 60 to 3600 seconds")
    normalized_scope = dict(scope)
    _verify_current_prompt_governance(
        normalized_scope,
        current_prompt_registry=current_prompt_registry,
        compiled_prompt=compiled_prompt,
        prompt_inputs=prompt_inputs,
        at=current,
    )
    request_fingerprint = str(normalized_scope.get("requestFingerprint") or "")
    if len(request_fingerprint) != 64:
        raise ValueError("paid action request fingerprint is invalid")
    normalized_quote = build_paid_action_quote(
        provider=str(quote.get("provider") or ""),
        model=str(quote.get("model") or ""),
        amount=_positive_number(quote.get("amount"), "quote amount"),
        unit=str(quote.get("unit") or ""),
        source=str(quote.get("source") or ""),
        pricing_version=str(quote.get("pricingVersion") or ""),
    )
    if normalized_quote["unit"] != USD_UNIT:
        raise ValueError("unified paid actions require USD quotes")
    if normalized_quote["provider"] != normalized_scope.get("provider"):
        raise ValueError("paid action quote provider mismatch")
    if normalized_quote["model"] != normalized_scope.get("providerModel"):
        raise ValueError("paid action quote model mismatch")
    amount = float(normalized_quote["amount"])
    issued_at = current.isoformat()
    expires_at = (current + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    override = (
        verify_budget_override(
            override_receipt,
            secret=secret,
            scope=normalized_scope,
            now=current,
        )
        if override_receipt is not None
        else None
    )
    authorization_id = f"spauth_{uuid.uuid4().hex}"
    reservation_id = f"spres_{uuid.uuid4().hex}"
    payload = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA_V3,
            "authorizationId": authorization_id,
            "reservationId": reservation_id,
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": issued_at,
            "expiresAt": expires_at,
            "scope": normalized_scope,
            "providerQuote": normalized_quote,
            **({"budgetOverride": override} if override is not None else {}),
            **(
                {"governanceContext": dict(governance_context)}
                if governance_context is not None
                else {}
            ),
        },
        secret=secret,
    )
    verify_authorization_v3(
        payload,
        expected_scope=normalized_scope,
        secret=secret,
        now=current,
    )
    _prepare_owned_transaction(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute(
            f"SELECT 1 FROM {AUTHORIZATION_TABLE} WHERE request_fingerprint = ?",
            (request_fingerprint,),
        ).fetchone():
            raise PermissionError("provider_spend_request_already_authorized")
        breaches = _budget_breaches(
            conn,
            scope=normalized_scope,
            amount=amount,
            limits=limits,
            at=current,
        )
        allowed = set(override.get("allowedBreaches") or []) if override else set()
        unapproved = sorted(set(breaches) - allowed)
        if unapproved:
            raise PermissionError(f"provider_budget_exceeded:{','.join(unapproved)}")
        context = dict(governance_context) if governance_context is not None else {}
        conn.execute(
            f"""
            INSERT INTO {AUTHORIZATION_TABLE} (
              authorization_id, reservation_id, provider, campaign_id, cohort_id,
              request_fingerprint, amount, unit, scope_json, provider_quote_json,
              creator_id, identity_profile_id, governance_fingerprint,
              governance_context_json, status, issued_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?,
                      'authorized', ?, ?)
            """,
            (
                authorization_id,
                reservation_id,
                normalized_scope["provider"],
                normalized_scope["campaignId"],
                normalized_scope["runId"],
                request_fingerprint,
                amount,
                json.dumps(normalized_scope, sort_keys=True),
                json.dumps(normalized_quote, sort_keys=True),
                normalized_scope["creatorId"],
                context.get("identityProfileId"),
                context.get("governanceFingerprint"),
                json.dumps(context, sort_keys=True) if context else None,
                issued_at,
                expires_at,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return payload


def begin_paid_action_attempt(
    conn: sqlite3.Connection,
    *,
    authorization: Mapping[str, Any],
    secret: str,
    attempt_id: str,
    current_prompt_registry: Mapping[str, Any] | None = None,
    compiled_prompt: Any = _PROMPT_MATERIAL_MISSING,
    prompt_inputs: Any = _PROMPT_MATERIAL_MISSING,
    now: datetime.datetime | None = None,
    after_consume: Callable[[], None] | None = None,
) -> str:
    """Consume a reservation and persist an unknown-cost attempt before I/O."""

    current = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    scope = dict(authorization.get("scope") or {})
    _verify_current_prompt_governance(
        scope,
        current_prompt_registry=current_prompt_registry,
        compiled_prompt=compiled_prompt,
        prompt_inputs=prompt_inputs,
        at=current,
    )
    verify_authorization_v3(
        authorization,
        expected_scope=scope,
        secret=secret,
        now=current,
    )
    attempt_id = _required(attempt_id, "attempt id")
    authorization_id = str(authorization["authorizationId"])
    _prepare_owned_transaction(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            f"""
            UPDATE {AUTHORIZATION_TABLE}
            SET status = 'consumed', consumed_at = ?
            WHERE authorization_id = ? AND status = 'authorized' AND expires_at > ?
            """,
            (current.isoformat(), authorization_id, current.isoformat()),
        )
        if cursor.rowcount != 1:
            raise PermissionError("paid_action_authorization_not_consumable")
        if after_consume is not None:
            after_consume()
        event_id = record_ai_cost(
            conn,
            provider=str(scope["provider"]),
            operation=str(scope["actionType"]),
            campaign_id=str(scope["campaignId"]),
            source_event_key=f"paid_action:{authorization_id}:{attempt_id}",
            reservation_id=str(authorization["reservationId"]),
            provider_quote=dict(authorization["providerQuote"]),
            metadata={
                "schema": LEDGER_SCHEMA,
                "authorizationId": authorization_id,
                "attemptId": attempt_id,
                "requestFingerprint": scope["requestFingerprint"],
                "reconciliationState": "pending",
            },
            ensure_schema=False,
            commit=False,
        )
        updated = conn.execute(
            """
            UPDATE ai_cost_events
            SET creator_id = ?, authorization_id = ?, action_type = ?,
                attempt_id = ?, run_id = ?, quoted_usd = ?, authorized_usd = ?,
                reconciliation_state = 'pending'
            WHERE id = ?
            """,
            (
                scope["creatorId"],
                authorization_id,
                scope["actionType"],
                attempt_id,
                scope["runId"],
                float(authorization["providerQuote"]["amount"]),
                float(authorization["providerQuote"]["amount"]),
                event_id,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("paid_action_attempt_row_not_persisted")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return event_id


def _verify_current_prompt_governance(
    scope: Mapping[str, Any],
    *,
    current_prompt_registry: Mapping[str, Any] | None,
    compiled_prompt: Any,
    prompt_inputs: Any,
    at: datetime.datetime,
) -> None:
    receipt = scope.get("promptGovernance")
    if receipt is None:
        if (
            current_prompt_registry is not None
            or compiled_prompt is not _PROMPT_MATERIAL_MISSING
            or prompt_inputs is not _PROMPT_MATERIAL_MISSING
        ):
            raise PermissionError("paid_action_prompt_receipt_missing")
        return
    if not isinstance(receipt, Mapping):
        raise PermissionError("paid_action_prompt_receipt_invalid")
    if (
        current_prompt_registry is None
        or compiled_prompt is _PROMPT_MATERIAL_MISSING
        or prompt_inputs is _PROMPT_MATERIAL_MISSING
    ):
        raise PermissionError("paid_action_current_prompt_verification_required")
    verify_prompt_receipt(
        current_prompt_registry,
        receipt,
        provider=str(scope.get("provider") or ""),
        model=str(scope.get("providerModel") or ""),
        compiled_prompt=compiled_prompt,
        inputs=prompt_inputs,
        at=at,
    )


def authorize_reference_paid_action(
    conn: sqlite3.Connection,
    *,
    provider: str,
    model: str,
    action_type: str,
    request_fingerprint: str,
    creator_id: str,
    campaign_id: str,
    run_id: str,
    reference_id: str,
    reference_source_sha256: str,
    secret: str,
    quote: Mapping[str, Any],
    limits: BudgetLimits,
    prompt_governance: Mapping[str, Any],
    current_prompt_registry: Mapping[str, Any],
    compiled_prompt: Any,
    prompt_inputs: Any,
    governance_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Authorize and durably begin one Reference Factory external effect."""

    governance = dict(governance_context)
    if (
        governance.get("schema") != "campaign_factory.creator_operation_context.v1"
        or governance.get("creatorId") != creator_id
        or governance.get("campaignId") != campaign_id
        or governance.get("operation") != "reference_analysis"
        or governance.get("provider") != provider.lower()
        or not governance.get("sourceAssetId")
        or not governance.get("governanceFingerprint")
    ):
        raise PermissionError("reference_paid_action_creator_governance_mismatch")
    normalized_reference_id = _required(reference_id, "reference id")
    if (
        not isinstance(reference_source_sha256, str)
        or len(reference_source_sha256) != 64
    ):
        raise ValueError("reference source SHA-256 is invalid")
    scope = build_paid_action_spend_scope(
        provider=provider,
        provider_model=model,
        action_type=action_type,
        creator_id=creator_id,
        campaign_id=campaign_id,
        run_id=run_id,
        input_fingerprints={
            "reference_request": request_fingerprint,
            "reference_source": reference_source_sha256,
        },
        parameters={
            "factory": "reference_factory",
            "referenceId": normalized_reference_id,
            "sourceAssetId": governance["sourceAssetId"],
        },
        prompt_governance=prompt_governance,
    )
    authorization = issue_paid_action_authorization(
        conn,
        scope=scope,
        quote=quote,
        secret=secret,
        limits=limits,
        current_prompt_registry=current_prompt_registry,
        compiled_prompt=compiled_prompt,
        prompt_inputs=prompt_inputs,
        governance_context=governance,
    )
    attempt_id = f"refattempt_{uuid.uuid4().hex}"
    event_id = begin_paid_action_attempt(
        conn,
        authorization=authorization,
        secret=secret,
        attempt_id=attempt_id,
        current_prompt_registry=current_prompt_registry,
        compiled_prompt=compiled_prompt,
        prompt_inputs=prompt_inputs,
    )
    return {
        "schema": REFERENCE_CONTEXT_SCHEMA,
        "authorizationId": authorization["authorizationId"],
        "attemptId": attempt_id,
        "campaignLedgerEventId": event_id,
        "provider": provider,
        "model": model,
        "actionType": action_type,
        "creatorId": creator_id,
        "campaignId": campaign_id,
        "runId": run_id,
        "referenceId": normalized_reference_id,
        "referenceSourceSha256": reference_source_sha256,
        "sourceAssetId": governance["sourceAssetId"],
        "governanceFingerprint": governance["governanceFingerprint"],
        "requestFingerprint": request_fingerprint,
        "spendRequestFingerprint": scope["requestFingerprint"],
        "attemptPersistedBeforeExternalEffect": True,
    }


def reconcile_reference_paid_action(
    conn: sqlite3.Connection,
    *,
    paid_action: Mapping[str, Any],
    actual_usd: float | None,
    provider_reference: str | None = None,
    unknown_reason: str | None = None,
) -> dict[str, Any]:
    """Reconcile the Campaign ledger event named by a Reference context."""

    if paid_action.get("schema") != REFERENCE_CONTEXT_SCHEMA:
        raise PermissionError("reference_paid_action_context_invalid")
    event_id = _required(
        paid_action.get("campaignLedgerEventId"), "campaign ledger event id"
    )
    return reconcile_paid_action_cost(
        conn,
        event_id=event_id,
        actual_usd=actual_usd,
        provider_reference=provider_reference,
        unknown_reason=unknown_reason,
        reference_paid_action=paid_action,
    )


def reconcile_paid_action_cost(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    actual_usd: float | None,
    refunded_usd: float = 0,
    provider_reference: str | None = None,
    unknown_reason: str | None = None,
    reference_paid_action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile actual provider cost, including refunds or provider credits."""

    _prepare_owned_transaction(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if reference_paid_action is not None:
            _verify_reference_reconciliation_binding(
                conn,
                event_id=event_id,
                paid_action=reference_paid_action,
            )
        row = conn.execute(
            """
            SELECT quoted_usd, reconciliation_state
            FROM ai_cost_events WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise LookupError("paid_action_cost_event_missing")
        if row[1] not in {"pending", "unknown"}:
            raise PermissionError("paid_action_cost_already_reconciled")
        refund = _nonnegative_number(refunded_usd, "refunded USD")
        if actual_usd is None:
            if not unknown_reason:
                raise ValueError("unknown actual cost requires an exact reason")
            state = "unknown"
            actual = None
            known_cost = 0.0
            cost_state = "unknown"
            usd_state = "unknown"
        else:
            actual = _nonnegative_number(actual_usd, "actual USD")
            if refund > actual:
                raise ValueError("refund cannot exceed actual provider cost")
            state = "refunded" if refund else "reconciled"
            known_cost = actual - refund
            cost_state = "actual"
            usd_state = "known"
            unknown_reason = None
        updated = conn.execute(
            """
            UPDATE ai_cost_events
            SET actual_usd = ?, refunded_usd = ?, estimated_cost_usd = ?,
                amount = ?, unit = 'USD', cost_state = ?, usd_cost_state = ?,
                unknown_reason = ?, reconciliation_state = ?,
                provider_reference = ?
            WHERE id = ? AND reconciliation_state IN ('pending', 'unknown')
            """,
            (
                actual,
                refund,
                known_cost,
                actual,
                cost_state,
                usd_state,
                unknown_reason,
                state,
                provider_reference,
                event_id,
            ),
        )
        if updated.rowcount != 1:
            raise PermissionError("paid_action_cost_already_reconciled")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "schema": LEDGER_SCHEMA,
        "eventId": event_id,
        "quotedUsd": float(row[0]),
        "actualUsd": actual,
        "refundedUsd": refund,
        "netUsd": known_cost if actual is not None else None,
        "reconciliationState": state,
        "unknownReason": unknown_reason,
        "providerReference": provider_reference,
    }


def _verify_reference_reconciliation_binding(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    paid_action: Mapping[str, Any],
) -> None:
    """Bind a Reference callback to its exact authorization and ledger attempt."""

    row = conn.execute(
        f"""
        SELECT
          event.authorization_id,
          event.attempt_id,
          event.provider,
          event.creator_id,
          event.campaign_id,
          event.operation,
          event.action_type,
          event.run_id,
          event.source_event_key,
          event.reservation_id,
          event.metadata_json,
          authorization.provider,
          authorization.creator_id,
          authorization.campaign_id,
          authorization.cohort_id,
          authorization.request_fingerprint,
          authorization.reservation_id,
          authorization.scope_json,
          authorization.provider_quote_json,
          authorization.governance_context_json,
          authorization.status
        FROM ai_cost_events AS event
        LEFT JOIN {AUTHORIZATION_TABLE} AS authorization
          ON authorization.authorization_id = event.authorization_id
        WHERE event.id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise PermissionError("reference_paid_action_ledger_binding_mismatch:event")
    (
        event_authorization_id,
        event_attempt_id,
        event_provider,
        event_creator_id,
        event_campaign_id,
        event_operation,
        event_action_type,
        event_run_id,
        event_source_key,
        event_reservation_id,
        event_metadata_json,
        authorization_provider,
        authorization_creator_id,
        authorization_campaign_id,
        authorization_run_id,
        authorization_request_fingerprint,
        authorization_reservation_id,
        authorization_scope_json,
        authorization_quote_json,
        authorization_governance_json,
        authorization_status,
    ) = row

    authorization_id = str(paid_action.get("authorizationId") or "")
    attempt_id = str(paid_action.get("attemptId") or "")
    if (
        not authorization_id
        or event_authorization_id != authorization_id
        or authorization_request_fingerprint is None
    ):
        raise PermissionError(
            "reference_paid_action_ledger_binding_mismatch:authorization"
        )
    if not attempt_id or event_attempt_id != attempt_id:
        raise PermissionError("reference_paid_action_ledger_binding_mismatch:attempt")

    try:
        scope = json.loads(str(authorization_scope_json))
        quote = json.loads(str(authorization_quote_json))
        metadata = json.loads(str(event_metadata_json))
        governance = json.loads(str(authorization_governance_json))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionError(
            "reference_paid_action_ledger_binding_mismatch:evidence"
        ) from exc
    if not all(
        isinstance(value, dict) for value in (scope, quote, metadata, governance)
    ):
        raise PermissionError("reference_paid_action_ledger_binding_mismatch:evidence")

    provider = str(paid_action.get("provider") or "")
    creator_id = str(paid_action.get("creatorId") or "")
    campaign_id = str(paid_action.get("campaignId") or "")
    action_type = str(paid_action.get("actionType") or "")
    run_id = str(paid_action.get("runId") or "")
    request_fingerprint = str(paid_action.get("requestFingerprint") or "")
    spend_request_fingerprint = str(paid_action.get("spendRequestFingerprint") or "")
    model = str(paid_action.get("model") or "")
    reference_id = str(paid_action.get("referenceId") or "")
    reference_source_sha256 = str(paid_action.get("referenceSourceSha256") or "")
    source_asset_id = str(paid_action.get("sourceAssetId") or "")
    governance_fingerprint = str(paid_action.get("governanceFingerprint") or "")
    input_fingerprints = scope.get("inputFingerprints")
    parameters = scope.get("parameters")

    checks = {
        "provider": (
            bool(provider)
            and event_provider == provider
            and authorization_provider == provider
            and scope.get("provider") == provider
            and quote.get("provider") == provider
        ),
        "creator": (
            bool(creator_id)
            and event_creator_id == creator_id
            and authorization_creator_id == creator_id
            and scope.get("creatorId") == creator_id
        ),
        "campaign": (
            bool(campaign_id)
            and event_campaign_id == campaign_id
            and authorization_campaign_id == campaign_id
            and scope.get("campaignId") == campaign_id
        ),
        "action": (
            bool(action_type)
            and event_operation == action_type
            and event_action_type == action_type
            and scope.get("actionType") == action_type
        ),
        "run": (
            bool(run_id)
            and event_run_id == run_id
            and authorization_run_id == run_id
            and scope.get("runId") == run_id
        ),
        "request_fingerprint": (
            bool(request_fingerprint)
            and isinstance(input_fingerprints, dict)
            and input_fingerprints.get("reference_request") == request_fingerprint
        ),
        "spend_request_fingerprint": (
            bool(spend_request_fingerprint)
            and authorization_request_fingerprint == spend_request_fingerprint
            and scope.get("requestFingerprint") == spend_request_fingerprint
            and metadata.get("requestFingerprint") == spend_request_fingerprint
        ),
        "model": (
            bool(model)
            and scope.get("providerModel") == model
            and quote.get("model") == model
        ),
        "reference": (
            bool(reference_id)
            and isinstance(parameters, dict)
            and parameters.get("referenceId") == reference_id
            and bool(reference_source_sha256)
            and isinstance(input_fingerprints, dict)
            and input_fingerprints.get("reference_source") == reference_source_sha256
            and bool(source_asset_id)
            and parameters.get("sourceAssetId") == source_asset_id
        ),
        "governance": (
            bool(governance_fingerprint)
            and governance.get("governanceFingerprint") == governance_fingerprint
            and governance.get("creatorId") == creator_id
            and governance.get("campaignId") == campaign_id
            and governance.get("sourceAssetId") == source_asset_id
        ),
        "event": (
            authorization_status == "consumed"
            and event_source_key == f"paid_action:{authorization_id}:{attempt_id}"
            and event_reservation_id == authorization_reservation_id
            and metadata.get("schema") == LEDGER_SCHEMA
            and metadata.get("authorizationId") == authorization_id
            and metadata.get("attemptId") == attempt_id
            and isinstance(parameters, dict)
            and parameters.get("factory") == "reference_factory"
        ),
    }
    for dimension, valid in checks.items():
        if not valid:
            raise PermissionError(
                f"reference_paid_action_ledger_binding_mismatch:{dimension}"
            )


def unified_cost_report(
    conn: sqlite3.Connection,
    *,
    creator_id: str | None = None,
    campaign_id: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Report quoted, authorized, actual, unknown, and refunded cost."""

    ensure_unified_cost_columns(conn)
    clauses = ["authorization_id IS NOT NULL"]
    params: list[Any] = []
    if creator_id:
        clauses.append("creator_id = ?")
        params.append(creator_id)
    if campaign_id:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if date:
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(date)
    rows = conn.execute(
        f"""
        SELECT provider, creator_id, campaign_id, action_type,
               substr(created_at, 1, 10) AS event_date,
               COUNT(*), SUM(quoted_usd), SUM(authorized_usd),
               SUM(actual_usd), SUM(refunded_usd),
               SUM(CASE WHEN reconciliation_state IN ('pending', 'unknown')
                        THEN 1 ELSE 0 END)
        FROM ai_cost_events
        WHERE {" AND ".join(clauses)}
        GROUP BY provider, creator_id, campaign_id, action_type, event_date
        ORDER BY event_date, provider, creator_id, campaign_id, action_type
        """,
        params,
    ).fetchall()
    groups = [
        {
            "provider": row[0],
            "creatorId": row[1],
            "campaignId": row[2],
            "actionType": row[3],
            "date": row[4],
            "attempts": int(row[5]),
            "quotedUsd": float(row[6] or 0),
            "authorizedUsd": float(row[7] or 0),
            "actualUsd": float(row[8]) if row[8] is not None else None,
            "refundedUsd": float(row[9] or 0),
            "unknownAttempts": int(row[10] or 0),
        }
        for row in rows
    ]
    return {
        "schema": "campaign_factory.unified_cost_report.v1",
        "filters": {
            "creatorId": creator_id,
            "campaignId": campaign_id,
            "date": date,
        },
        "groups": groups,
    }


def build_budget_override(
    *,
    scope: Mapping[str, Any],
    allowed_breaches: list[str],
    operator: str,
    reason: str,
    secret: str,
    now: datetime.datetime | None = None,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    """Create a narrowly scoped, signed budget-override receipt."""

    current = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    core = {
        "schema": OVERRIDE_SCHEMA,
        "requestFingerprint": scope["requestFingerprint"],
        "allowedBreaches": sorted(
            {_required(value, "budget breach") for value in allowed_breaches}
        ),
        "operator": _required(operator, "operator"),
        "reason": _required(reason, "reason"),
        "issuedAt": current.isoformat(),
        "expiresAt": (current + datetime.timedelta(seconds=ttl_seconds)).isoformat(),
    }
    return sign_authorization(core, secret=secret)


def verify_budget_override(
    receipt: Mapping[str, Any],
    *,
    secret: str,
    scope: Mapping[str, Any],
    now: datetime.datetime,
) -> dict[str, Any]:
    if receipt.get("schema") != OVERRIDE_SCHEMA:
        raise PermissionError("budget_override_schema_invalid")
    signature = receipt.get("signature")
    if not isinstance(signature, str):
        raise PermissionError("budget_override_signature_missing")
    unsigned = {key: value for key, value in receipt.items() if key != "signature"}
    expected = sign_authorization(unsigned, secret=secret)["signature"]
    if not _constant_time_equal(signature, expected):
        raise PermissionError("budget_override_signature_invalid")
    if receipt.get("requestFingerprint") != scope.get("requestFingerprint"):
        raise PermissionError("budget_override_scope_mismatch")
    if now >= datetime.datetime.fromisoformat(str(receipt["expiresAt"])):
        raise PermissionError("budget_override_expired")
    _required(receipt.get("operator"), "operator")
    _required(receipt.get("reason"), "reason")
    allowed = receipt.get("allowedBreaches")
    if not isinstance(allowed, list) or not allowed:
        raise PermissionError("budget_override_breaches_missing")
    return dict(receipt)


def ensure_unified_cost_columns(conn: sqlite3.Connection) -> None:
    """Validate the v5 ledger schema without mutating a reporting connection."""

    required_tables = {AUTHORIZATION_TABLE, "ai_cost_events"}
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if missing := required_tables - tables:
        raise RuntimeError(
            "campaign_schema_v5_required:tables:" + ",".join(sorted(missing))
        )
    required_cost_columns = {
        "id",
        "source_event_key",
        "reservation_id",
        "campaign_id",
        "provider",
        "operation",
        "input_tokens",
        "output_tokens",
        "generations",
        "amount",
        "unit",
        "provider_quote_json",
        "cohort_id",
        "estimated_cost_usd",
        "cost_state",
        "usd_cost_state",
        "unknown_reason",
        "metadata_json",
        "created_at",
        "creator_id",
        "authorization_id",
        "action_type",
        "attempt_id",
        "run_id",
        "quoted_usd",
        "authorized_usd",
        "actual_usd",
        "refunded_usd",
        "reconciliation_state",
        "provider_reference",
    }
    cost_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(ai_cost_events)")
    }
    if missing := required_cost_columns - cost_columns:
        raise RuntimeError(
            "campaign_schema_v5_required:ai_cost_events_columns:"
            + ",".join(sorted(missing))
        )
    required_authorization_columns = {
        "authorization_id",
        "reservation_id",
        "provider",
        "campaign_id",
        "cohort_id",
        "request_fingerprint",
        "amount",
        "unit",
        "scope_json",
        "provider_quote_json",
        "creator_id",
        "identity_profile_id",
        "governance_fingerprint",
        "governance_context_json",
        "status",
        "issued_at",
        "expires_at",
        "consumed_at",
        "cancelled_at",
    }
    authorization_columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({AUTHORIZATION_TABLE})")
    }
    if missing := required_authorization_columns - authorization_columns:
        raise RuntimeError(
            "campaign_schema_v5_required:provider_authorization_columns:"
            + ",".join(sorted(missing))
        )
    required_indexes = {
        "idx_ai_cost_events_authorization_attempt",
        "idx_ai_cost_events_campaign",
        "idx_ai_cost_events_source_key",
        "idx_ai_cost_events_unified_report",
        "idx_provider_spend_authorizations_status",
    }
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    if missing := required_indexes - indexes:
        raise RuntimeError(
            "campaign_schema_v5_required:indexes:" + ",".join(sorted(missing))
        )


def _prepare_owned_transaction(conn: sqlite3.Connection) -> None:
    """Require migrated schema without changing transaction or schema state."""

    if conn.in_transaction:
        raise RuntimeError("paid_action_operation_requires_clean_transaction")
    ensure_unified_cost_columns(conn)


def _budget_breaches(
    conn: sqlite3.Connection,
    *,
    scope: Mapping[str, Any],
    amount: float,
    limits: BudgetLimits,
    at: datetime.datetime,
) -> list[str]:
    day = at.date().isoformat()
    month = day[:7]
    provider = str(scope["provider"])
    creator = str(scope["creatorId"])
    campaign = str(scope["campaignId"])
    run = str(scope["runId"])
    tests = {
        "global_daily": (
            _reserved_total(conn, "substr(issued_at, 1, 10) = ?", day, at=at),
            limits.global_daily_usd,
        ),
        "global_monthly": (
            _reserved_total(conn, "substr(issued_at, 1, 7) = ?", month, at=at),
            limits.global_monthly_usd,
        ),
        "creator": (
            _reserved_total(
                conn,
                "creator_id = ? AND substr(issued_at, 1, 10) = ?",
                creator,
                day,
                at=at,
            ),
            limits.creator_daily_usd,
        ),
        "campaign": (
            _reserved_total(
                conn,
                "campaign_id = ? AND substr(issued_at, 1, 10) = ?",
                campaign,
                day,
                at=at,
            ),
            limits.campaign_daily_usd,
        ),
        "provider": (
            _reserved_total(
                conn,
                "provider = ? AND substr(issued_at, 1, 10) = ?",
                provider,
                day,
                at=at,
            ),
            limits.provider_daily_usd,
        ),
        "run": (
            _reserved_total(conn, "cohort_id = ?", run, at=at),
            limits.run_usd,
        ),
    }
    return [name for name, (current, cap) in tests.items() if current + amount > cap]


def _reserved_total(
    conn: sqlite3.Connection,
    clause: str,
    *values: str,
    at: datetime.datetime,
) -> float:
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(
          CASE
            WHEN status = 'authorized' THEN amount
            ELSE COALESCE(
              (
                SELECT CASE
                  WHEN event.reconciliation_state IN ('reconciled', 'refunded')
                       AND event.actual_usd IS NOT NULL
                    THEN MAX(
                      event.actual_usd - COALESCE(event.refunded_usd, 0),
                      0
                    )
                  ELSE amount
                END
                FROM ai_cost_events AS event
                WHERE event.authorization_id =
                      provider_spend_authorizations.authorization_id
                ORDER BY event.created_at DESC, event.id DESC
                LIMIT 1
              ),
              amount
            )
          END
        ), 0)
        FROM {AUTHORIZATION_TABLE}
        WHERE unit = 'USD'
          AND (status = 'consumed' OR (status = 'authorized' AND expires_at > ?))
          AND {clause}
        """,
        (at.isoformat(), *values),
    ).fetchone()
    return float(row[0] or 0)


def _positive_env(name: str) -> float:
    raw = os.environ.get(name)
    try:
        return _positive_number(float(raw) if raw is not None else None, name)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name}_missing_or_invalid") from exc


def _positive_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{label} must be finite and positive")
    return float(value)


def _nonnegative_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ValueError(f"{label} must be finite and non-negative")
    return float(value)


def _required(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
