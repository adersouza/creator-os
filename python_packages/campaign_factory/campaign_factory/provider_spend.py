"""Campaign-owned provider spend policy, authorization, and cost ledger."""

from __future__ import annotations

import datetime
import json
import math
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA,
    HIGGSFIELD_CREDIT_UNIT,
    SpendAuthorizationError,
    sign_authorization,
)
from creator_os_core.runtime_guards import global_kill_switch_active

from pipeline_contracts import validate_provider_spend_authorization

from .cost_tracker import ensure_cost_table, record_ai_cost
from .creator_governance import resolve_campaign_operation

AUTHORIZATION_TABLE = "provider_spend_authorizations"
AUTHORIZATION_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {AUTHORIZATION_TABLE} (
    authorization_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    campaign_id TEXT,
    cohort_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE,
    amount REAL NOT NULL,
    unit TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    provider_quote_json TEXT NOT NULL,
    creator_id TEXT,
    identity_profile_id TEXT,
    governance_fingerprint TEXT,
    governance_context_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('authorized', 'consumed', 'cancelled')),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    cancelled_at TEXT
)
"""


class QuoteProvider(Protocol):
    def quote(self, scope: dict[str, Any]) -> dict[str, Any]: ...


class BalanceProvider(Protocol):
    def balance(self) -> float | None: ...


class ProviderOverspendError(PermissionError):
    def __init__(
        self,
        *,
        actual: float,
        authorized_maximum: float,
        cost_event_ids: list[str],
    ) -> None:
        super().__init__("provider_overspend_requires_operator_review")
        self.actual = actual
        self.authorized_maximum = authorized_maximum
        self.cost_event_ids = cost_event_ids


@dataclass
class HiggsfieldCliQuoteProvider:
    timeout_seconds: int = 60

    def quote(self, scope: dict[str, Any]) -> dict[str, Any]:
        cli = shutil.which("higgsfield")
        if not cli:
            raise RuntimeError("higgsfield_cli_unavailable")
        items = []
        models = list(scope.get("providerModels") or [])
        for model in models:
            cmd = [cli, "generate", "cost", str(model)]
            if "kling" in str(model).lower():
                cmd.extend(["--duration", str(scope.get("videoDuration") or 5)])
                if scope.get("videoMode"):
                    cmd.extend(["--mode", str(scope["videoMode"])])
                if scope.get("videoSound"):
                    cmd.extend(["--sound", str(scope["videoSound"])])
            else:
                if scope.get("imageAspectRatio"):
                    cmd.extend(["--aspect_ratio", str(scope["imageAspectRatio"])])
                if scope.get("imageQuality"):
                    cmd.extend(["--quality", str(scope["imageQuality"])])
            proc = subprocess.run(
                [*cmd, "--json"],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if proc.returncode != 0:
                raise RuntimeError("higgsfield_quote_unavailable")
            try:
                raw = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError("higgsfield_quote_invalid_json") from exc
            amount = _quote_credits(raw)
            if amount is None or amount <= 0:
                raise RuntimeError("higgsfield_quote_missing_credits")
            items.append(
                {
                    "provider": "higgsfield",
                    "model": str(model),
                    "amount": amount,
                    "unit": HIGGSFIELD_CREDIT_UNIT,
                    "raw": raw,
                }
            )
        if not items:
            raise RuntimeError("provider_quote_set_empty")
        return {
            "provider": "higgsfield",
            "amount": round(sum(float(item["amount"]) for item in items), 4),
            "unit": HIGGSFIELD_CREDIT_UNIT,
            "items": items,
        }


@dataclass
class HiggsfieldCliBalanceProvider:
    timeout_seconds: int = 30

    def balance(self) -> float | None:
        cli = shutil.which("higgsfield")
        if not cli:
            return None
        proc = subprocess.run(
            [cli, "account", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if proc.returncode != 0:
            return None
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return None
        return _find_balance(payload)


def ensure_authorization_table(conn: sqlite3.Connection) -> None:
    conn.execute(AUTHORIZATION_TABLE_SQL)
    columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({AUTHORIZATION_TABLE})").fetchall()
    }
    for column in (
        "creator_id",
        "identity_profile_id",
        "governance_fingerprint",
        "governance_context_json",
    ):
        if column not in columns:
            conn.execute(f"ALTER TABLE {AUTHORIZATION_TABLE} ADD COLUMN {column} TEXT")
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{AUTHORIZATION_TABLE}_status "
        f"ON {AUTHORIZATION_TABLE}(provider, status, issued_at)"
    )


def issue_provider_spend_authorization(
    conn: sqlite3.Connection,
    *,
    scope: dict[str, Any],
    campaign_id: str | None,
    max_credits: float,
    secret: str,
    quote_provider: QuoteProvider | None = None,
    balance_provider: BalanceProvider | None = None,
    now: datetime.datetime | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Quote, enforce policy, reserve, and sign one worker execution."""
    # Validate the secret before any provider/network call.
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise SpendAuthorizationError(
            "CREATOR_OS_SPEND_AUTH_SECRET must contain at least 32 bytes"
        )
    if global_kill_switch_active():
        raise PermissionError("creator_os_global_kill_switch_active")
    governance_context: dict[str, Any] | None = None
    has_governance = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'campaign_governance'
        """
    ).fetchone()
    if has_governance:
        if not campaign_id:
            raise PermissionError("campaign_governance_required_for_provider_spend")
        scope_source_asset_id = str(
            scope.get("campaignSourceAssetId") or scope.get("sourceAssetId") or ""
        ).strip()
        governance_context = resolve_campaign_operation(
            conn,
            campaign_id=campaign_id,
            operation="provider_spend",
            provider="higgsfield",
            source_asset_id=scope_source_asset_id or None,
            account_id=(str(scope["accountId"]) if scope.get("accountId") else None),
            territory=(str(scope["territory"]) if scope.get("territory") else None),
        )
        scoped_campaign = str(scope.get("campaign") or "").strip()
        if scoped_campaign not in {
            str(governance_context["campaignId"]),
            str(governance_context["campaignSlug"]),
        }:
            raise PermissionError("provider_campaign_scope_mismatch")
        scoped_creator = str(scope.get("creator") or "").strip().lower()
        if scoped_creator != str(governance_context["creatorSlug"]).lower():
            raise PermissionError("provider_creator_scope_mismatch")
        if (
            scope_source_asset_id
            and scope_source_asset_id != governance_context["sourceAssetId"]
        ):
            raise PermissionError("provider_source_scope_mismatch")
        scoped_soul_id = str(scope.get("soulId") or "")
        if (
            scoped_soul_id
            and scoped_soul_id != governance_context["providerIdentityId"]
        ):
            raise PermissionError("provider_identity_scope_mismatch")
    if (
        isinstance(max_credits, bool)
        or not isinstance(max_credits, (int, float))
        or not math.isfinite(float(max_credits))
        or float(max_credits) <= 0
    ):
        raise ValueError("paid generation requires a finite positive credit cap")
    request_fingerprint = str(scope.get("requestFingerprint") or "")
    if len(request_fingerprint) != 64:
        raise ValueError("provider spend scope fingerprint is invalid")
    quote = (quote_provider or HiggsfieldCliQuoteProvider()).quote(scope)
    amount = _positive_number(quote.get("amount"), "provider quote amount")
    if quote.get("unit") != HIGGSFIELD_CREDIT_UNIT:
        raise ValueError("provider quote unit is invalid")
    if amount > float(max_credits):
        raise PermissionError("provider_quote_exceeds_run_cap")

    daily_cap = _positive_env("HIGGSFIELD_DAILY_BUDGET_CREDITS")
    monthly_cap = _positive_env("HIGGSFIELD_MONTHLY_BUDGET_CREDITS")
    cohort_cap = _positive_env("HIGGSFIELD_COHORT_MAX_CREDITS")
    run_max_assets = _positive_int_env("HIGGSFIELD_RUN_MAX_ASSETS")
    min_balance = _nonnegative_env("HIGGSFIELD_MIN_BALANCE_CREDITS")
    kling_daily_max = _positive_int_env("HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS")
    call_count = int(scope.get("providerCallCount") or 0)
    if call_count <= 0 or call_count > run_max_assets:
        raise PermissionError("run_asset_limit_exceeded")
    balance = (balance_provider or HiggsfieldCliBalanceProvider()).balance()
    if balance is None:
        raise PermissionError("higgsfield_balance_unavailable")
    if balance - amount < min_balance:
        raise PermissionError("projected_balance_below_minimum")

    timestamp = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    issued_at = _iso(timestamp)
    expires_at = _iso(timestamp + datetime.timedelta(seconds=ttl_seconds))
    cohort_id = str(scope.get("cohortId") or "")
    authorization_id = f"spauth_{uuid.uuid4().hex}"
    reservation_id = f"spres_{uuid.uuid4().hex}"
    day = issued_at[:10]
    month = issued_at[:7]
    quoted_kling = sum(
        1
        for model in scope.get("providerModels") or []
        if "kling" in str(model).lower()
    )
    payload = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA,
            "authorizationId": authorization_id,
            "reservationId": reservation_id,
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": issued_at,
            "expiresAt": expires_at,
            "scope": scope,
            "providerQuote": quote,
            **(
                {"governanceContext": governance_context}
                if governance_context is not None
                else {"legacyCompatibility": True}
            ),
        },
        secret=secret,
    )
    # Validate the exact durable payload before reserving provider capacity.
    validate_provider_spend_authorization(payload)
    if conn.in_transaction:
        raise RuntimeError("provider_spend_issue_requires_clean_transaction")
    ensure_authorization_table(conn)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE request_fingerprint = ?",
            (request_fingerprint,),
        ).fetchone()
        if existing is not None:
            raise PermissionError("provider_spend_request_already_authorized")
        active_provider_reservations = _active_provider_reservations(conn)
        if balance - active_provider_reservations - amount < min_balance:
            raise PermissionError("provider_balance_capacity_already_reserved")
        daily_spend = _reserved_total(conn, "substr(issued_at, 1, 10) = ?", day)
        monthly_spend = _reserved_total(conn, "substr(issued_at, 1, 7) = ?", month)
        cohort_spend = _reserved_total(conn, "cohort_id = ?", cohort_id)
        if daily_spend + amount > daily_cap:
            raise PermissionError("projected_daily_credits_exceeded")
        if monthly_spend + amount > monthly_cap:
            raise PermissionError("projected_monthly_credits_exceeded")
        if cohort_spend + amount > cohort_cap:
            raise PermissionError("projected_cohort_credits_exceeded")
        kling_today = _kling_count(conn, day)
        if kling_today + quoted_kling > kling_daily_max:
            raise PermissionError("projected_daily_kling_generation_limit_exceeded")
        conn.execute(
            f"""
            INSERT INTO {AUTHORIZATION_TABLE}
                (authorization_id, reservation_id, provider, campaign_id, cohort_id,
                 request_fingerprint, amount, unit, scope_json, provider_quote_json,
                 creator_id, identity_profile_id, governance_fingerprint,
                 governance_context_json, status, issued_at, expires_at)
            VALUES (?, ?, 'higgsfield', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'authorized', ?, ?)
            """,
            (
                authorization_id,
                reservation_id,
                campaign_id,
                cohort_id,
                request_fingerprint,
                amount,
                HIGGSFIELD_CREDIT_UNIT,
                json.dumps(scope, sort_keys=True),
                json.dumps(quote, sort_keys=True),
                (
                    governance_context["creatorId"]
                    if governance_context is not None
                    else None
                ),
                (
                    governance_context["identityProfileId"]
                    if governance_context is not None
                    else None
                ),
                (
                    governance_context["governanceFingerprint"]
                    if governance_context is not None
                    else None
                ),
                (
                    json.dumps(governance_context, sort_keys=True)
                    if governance_context is not None
                    else None
                ),
                issued_at,
                expires_at,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return payload


def validate_provider_spend_batch_capacity(
    conn: sqlite3.Connection,
    requests: list[tuple[dict[str, Any], float]],
    *,
    now: datetime.datetime | None = None,
) -> None:
    """Prove all prepared reservations fit policy before issuing the first."""

    if not requests:
        return
    ensure_authorization_table(conn)
    timestamp = _iso(now or datetime.datetime.now(datetime.UTC))
    day = timestamp[:10]
    month = timestamp[:7]
    daily_cap = _positive_env("HIGGSFIELD_DAILY_BUDGET_CREDITS")
    monthly_cap = _positive_env("HIGGSFIELD_MONTHLY_BUDGET_CREDITS")
    cohort_cap = _positive_env("HIGGSFIELD_COHORT_MAX_CREDITS")
    run_max_assets = _positive_int_env("HIGGSFIELD_RUN_MAX_ASSETS")
    kling_daily_max = _positive_int_env("HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS")
    total = sum(
        _positive_number(amount, "prepared provider quote")
        for _scope, amount in requests
    )
    calls = sum(int(scope.get("providerCallCount") or 0) for scope, _ in requests)
    if calls <= 0 or calls > run_max_assets:
        raise PermissionError("run_asset_limit_exceeded")
    if _reserved_total(conn, "substr(issued_at, 1, 10) = ?", day) + total > daily_cap:
        raise PermissionError("projected_daily_credits_exceeded")
    if (
        _reserved_total(conn, "substr(issued_at, 1, 7) = ?", month) + total
        > monthly_cap
    ):
        raise PermissionError("projected_monthly_credits_exceeded")
    cohorts: dict[str, float] = {}
    for scope, amount in requests:
        cohort = str(scope.get("cohortId") or "")
        cohorts[cohort] = cohorts.get(cohort, 0.0) + float(amount)
    for cohort, amount in cohorts.items():
        if _reserved_total(conn, "cohort_id = ?", cohort) + amount > cohort_cap:
            raise PermissionError("projected_cohort_credits_exceeded")
    quoted_kling = sum(
        1
        for scope, _amount in requests
        for model in scope.get("providerModels") or []
        if "kling" in str(model).lower()
    )
    if _kling_count(conn, day) + quoted_kling > kling_daily_max:
        raise PermissionError("projected_daily_kling_generation_limit_exceeded")


def consume_provider_spend_authorization(
    conn: sqlite3.Connection,
    authorization_id: str,
    *,
    now: datetime.datetime | None = None,
) -> None:
    caller_owned_transaction = conn.in_transaction
    ensure_authorization_table(conn)
    authorization = conn.execute(
        f"""
        SELECT campaign_id, provider, governance_fingerprint,
               governance_context_json
        FROM {AUTHORIZATION_TABLE} WHERE authorization_id = ?
        """,
        (authorization_id,),
    ).fetchone()
    if authorization is None:
        raise PermissionError(
            "provider spend authorization is missing, expired, or consumed"
        )
    campaign_id = authorization[0]
    provider = authorization[1]
    governance_fingerprint = authorization[2]
    governance_context_json = authorization[3]
    governance_row = (
        conn.execute(
            "SELECT 1 FROM campaign_governance WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign_id
        and conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'campaign_governance'
            """
        ).fetchone()
        else None
    )
    if governance_row is not None:
        if not governance_context_json:
            raise PermissionError("provider_authorization_governance_missing")
        prior_context = json.loads(governance_context_json)
        current_context = resolve_campaign_operation(
            conn,
            campaign_id=str(campaign_id),
            operation=str(prior_context["operation"]),
            provider=str(provider),
            source_asset_id=(
                str(prior_context["sourceAssetId"])
                if prior_context.get("sourceAssetId")
                else None
            ),
            account_id=(
                str(prior_context["accountId"])
                if prior_context.get("accountId")
                else None
            ),
            territory=(
                str(prior_context["territory"])
                if prior_context.get("territory")
                else None
            ),
        )
        if current_context["governanceFingerprint"] != governance_fingerprint:
            raise PermissionError("provider_authorization_governance_stale")
    timestamp = _iso(now or datetime.datetime.now(datetime.UTC))
    cursor = conn.execute(
        f"""
        UPDATE {AUTHORIZATION_TABLE}
        SET status = 'consumed', consumed_at = ?
        WHERE authorization_id = ? AND status = 'authorized' AND expires_at > ?
        """,
        (timestamp, authorization_id, timestamp),
    )
    if cursor.rowcount != 1:
        raise PermissionError(
            "provider spend authorization is missing, expired, or consumed"
        )
    if not caller_owned_transaction:
        conn.commit()


def cancel_provider_spend_authorization(
    conn: sqlite3.Connection,
    authorization_id: str,
    *,
    now: datetime.datetime | None = None,
) -> bool:
    """Release one unconsumed reservation after an aborted batch."""

    caller_owned_transaction = conn.in_transaction
    ensure_authorization_table(conn)
    timestamp = _iso(now or datetime.datetime.now(datetime.UTC))
    cursor = conn.execute(
        f"""
        UPDATE {AUTHORIZATION_TABLE}
        SET status = 'cancelled', cancelled_at = ?
        WHERE authorization_id = ? AND status = 'authorized'
        """,
        (timestamp, authorization_id),
    )
    if not caller_owned_transaction:
        conn.commit()
    return cursor.rowcount == 1


def load_provider_spend_authorization(
    conn: sqlite3.Connection,
    authorization_id: str,
    *,
    secret: str,
) -> dict[str, Any]:
    """Reconstruct the original signed receipt for exact crash recovery."""

    ensure_authorization_table(conn)
    row = conn.execute(
        f"""
        SELECT authorization_id, reservation_id, issued_at, expires_at,
               scope_json, provider_quote_json, governance_context_json
        FROM {AUTHORIZATION_TABLE}
        WHERE authorization_id = ?
        """,
        (authorization_id,),
    ).fetchone()
    if row is None:
        raise PermissionError("provider_spend_authorization_missing")
    governance_context = json.loads(str(row[6])) if row[6] else None
    payload = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA,
            "authorizationId": str(row[0]),
            "reservationId": str(row[1]),
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": str(row[2]),
            "expiresAt": str(row[3]),
            "scope": json.loads(str(row[4])),
            "providerQuote": json.loads(str(row[5])),
            **(
                {"governanceContext": governance_context}
                if governance_context is not None
                else {}
            ),
        },
        secret=secret,
    )
    validate_provider_spend_authorization(payload)
    return payload


def record_provider_execution(
    conn: sqlite3.Connection,
    *,
    authorization: dict[str, Any],
    execution: dict[str, Any] | None,
) -> list[str]:
    """Persist worker evidence in Campaign's authoritative cost ledger."""
    if not isinstance(execution, dict):
        return []
    events = execution.get("events")
    if not isinstance(events, list):
        return []
    caller_owned_transaction = conn.in_transaction
    ensure_cost_table(conn)
    authorization_row = conn.execute(
        f"""
        SELECT campaign_id, creator_id
        FROM {AUTHORIZATION_TABLE}
        WHERE authorization_id = ?
        """,
        (authorization["authorizationId"],),
    ).fetchone()
    campaign_id = (
        str(authorization_row[0])
        if authorization_row and authorization_row[0]
        else None
    )
    creator_id = (
        str(authorization_row[1])
        if authorization_row and authorization_row[1]
        else None
    )
    event_ids = []
    quote = authorization["providerQuote"]
    scope = authorization["scope"]
    authorized_maximum = _positive_number(
        quote.get("amount"), "authorized provider maximum"
    )
    overspend_actual: float | None = None
    for event in events:
        if not isinstance(event, dict) or not event.get("jobId"):
            continue
        amount = _event_amount(event.get("actualCredits"))
        if amount is not None and amount > authorized_maximum + 0.0001:
            overspend_actual = amount
        event_ids.append(
            record_ai_cost(
                conn,
                provider=str(event.get("provider") or "higgsfield"),
                operation=str(event.get("operation") or "generation"),
                campaign_id=campaign_id,
                generations=1,
                metadata={
                    "schema": "campaign_factory.provider_execution_cost.v1",
                    "authorizationId": authorization["authorizationId"],
                    "model": event.get("model"),
                    "jobId": event.get("jobId"),
                    "requestFingerprint": scope.get("requestFingerprint"),
                    "authorizedMaximumCredits": authorized_maximum,
                    "overspend": (
                        amount is not None and amount > authorized_maximum + 0.0001
                    ),
                },
                source_event_key=(
                    f"campaign_factory:{authorization['authorizationId']}:"
                    f"{event['jobId']}"
                ),
                reservation_id=authorization["reservationId"],
                amount=amount,
                unit=HIGGSFIELD_CREDIT_UNIT if amount is not None else None,
                provider_quote=quote,
                cohort_id=str(scope.get("cohortId") or ""),
                ensure_schema=False,
                commit=False,
            )
        )
    if overspend_actual is not None:
        _record_overspend_incident(
            conn,
            authorization=authorization,
            campaign_id=campaign_id,
            creator_id=creator_id,
            actual=overspend_actual,
            authorized_maximum=authorized_maximum,
            cost_event_ids=event_ids,
        )
    if not caller_owned_transaction:
        conn.commit()
    if overspend_actual is not None:
        raise ProviderOverspendError(
            actual=overspend_actual,
            authorized_maximum=authorized_maximum,
            cost_event_ids=event_ids,
        )
    return event_ids


def _record_overspend_incident(
    conn: sqlite3.Connection,
    *,
    authorization: dict[str, Any],
    campaign_id: str | None,
    creator_id: str | None,
    actual: float,
    authorized_maximum: float,
    cost_event_ids: list[str],
) -> None:
    has_incident_registry = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'incident_records'
        """
    ).fetchone()
    if has_incident_registry is None:
        return
    from .incident_privacy import IncidentRepository

    now = (
        datetime.datetime.now(datetime.UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    repository = IncidentRepository(
        conn,
        new_id=lambda prefix: f"{prefix}_{uuid.uuid4().hex}",
        utc_now=lambda: now,
    )
    incident = repository.create(
        category="overspend",
        severity="critical",
        domain_owner="campaign_factory",
        owner="release_owner",
        next_action="place provider spend on manual hold and reconcile actual cost",
        operator="provider_spend_guard",
        model_id=creator_id,
        campaign_id=campaign_id,
        external_effect_state="finalized",
        financial_exposure={
            "authorizationId": authorization["authorizationId"],
            "actualCredits": actual,
            "authorizedMaximumCredits": authorized_maximum,
            "costEventIds": cost_event_ids,
        },
        evidence=[
            {"evidenceType": "ai_cost_event", "evidenceId": event_id}
            for event_id in cost_event_ids
        ],
        fingerprint_scope={
            "category": "overspend",
            "authorizationId": authorization["authorizationId"],
            "actualCredits": actual,
            "authorizedMaximumCredits": authorized_maximum,
        },
    )
    if incident["state"] == "detected":
        repository.transition(
            str(incident["id"]),
            state="manual_hold",
            actor="provider_spend_guard",
            action="automatic_overspend_hold",
            evidence={
                "authorizationId": authorization["authorizationId"],
                "costEventIds": cost_event_ids,
            },
        )


def _reserved_total(conn: sqlite3.Connection, clause: str, value: str) -> float:
    now = _iso(datetime.datetime.now(datetime.UTC))
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM {AUTHORIZATION_TABLE} "
        f"WHERE provider = 'higgsfield' AND unit = ? "
        f"AND (status = 'consumed' OR (status = 'authorized' AND expires_at > ?)) "
        f"AND {clause}",
        (HIGGSFIELD_CREDIT_UNIT, now, value),
    ).fetchone()
    return float(row[0] or 0.0)


def _active_provider_reservations(conn: sqlite3.Connection) -> float:
    has_cost_table = (
        conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'ai_cost_events'
            """
        ).fetchone()
        is not None
    )
    consumed_clause = (
        """
        OR (
          status = 'consumed'
          AND NOT EXISTS (
            SELECT 1 FROM ai_cost_events e
            WHERE e.reservation_id = provider_spend_authorizations.reservation_id
          )
        )
        """
        if has_cost_table
        else "OR status = 'consumed'"
    )
    now = _iso(datetime.datetime.now(datetime.UTC))
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0)
        FROM {AUTHORIZATION_TABLE}
        WHERE provider = 'higgsfield'
          AND unit = ?
          AND ((status = 'authorized' AND expires_at > ?) {consumed_clause})
        """,
        (HIGGSFIELD_CREDIT_UNIT, now),
    ).fetchone()
    return float(row[0] or 0.0)


def _kling_count(conn: sqlite3.Connection, day: str) -> int:
    now = _iso(datetime.datetime.now(datetime.UTC))
    rows = conn.execute(
        f"SELECT scope_json FROM {AUTHORIZATION_TABLE} "
        "WHERE provider = 'higgsfield' AND unit = ? "
        "AND (status = 'consumed' OR (status = 'authorized' AND expires_at > ?)) "
        "AND substr(issued_at, 1, 10) = ?",
        (HIGGSFIELD_CREDIT_UNIT, now, day),
    ).fetchall()
    return sum(
        1
        for row in rows
        for model in (json.loads(str(row[0])).get("providerModels") or [])
        if "kling" in str(model).lower()
    )


def _quote_credits(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("credits", "creditCost", "costCredits", "cost", "amount"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            if math.isfinite(parsed) and parsed >= 0:
                return parsed
    for key in ("quote", "usage", "data", "result"):
        nested = _quote_credits(payload.get(key))
        if nested is not None:
            return nested
    return None


def _find_balance(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("balance", "balanceUsd", "balance_usd", "credits", "creditsUsd"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            if math.isfinite(parsed) and parsed >= 0:
                return parsed
    for key in ("account", "billing", "data", "result"):
        nested = _find_balance(payload.get(key))
        if nested is not None:
            return nested
    return None


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return parsed


def _positive_env(name: str) -> float:
    try:
        return _positive_number(float(os.environ.get(name, "")), name)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc


def _positive_int_env(name: str) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if str(value) != raw.strip() or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _event_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("provider execution credits must be finite and non-negative")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("provider execution credits must be finite and non-negative")
    return parsed


def _nonnegative_env(name: str) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def _iso(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
