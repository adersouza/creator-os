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
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_authorization_table(conn)
        existing = conn.execute(
            f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE request_fingerprint = ?",
            (request_fingerprint,),
        ).fetchone()
        if existing is not None:
            raise PermissionError("provider_spend_request_already_authorized")
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
                 status, issued_at, expires_at)
            VALUES (?, ?, 'higgsfield', ?, ?, ?, ?, ?, ?, ?, 'authorized', ?, ?)
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
                issued_at,
                expires_at,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
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
        },
        secret=secret,
    )
    validate_provider_spend_authorization(payload)
    return payload


def consume_provider_spend_authorization(
    conn: sqlite3.Connection,
    authorization_id: str,
    *,
    now: datetime.datetime | None = None,
) -> None:
    ensure_authorization_table(conn)
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
    conn.commit()


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
    ensure_cost_table(conn)
    authorization_row = conn.execute(
        f"SELECT campaign_id FROM {AUTHORIZATION_TABLE} WHERE authorization_id = ?",
        (authorization["authorizationId"],),
    ).fetchone()
    campaign_id = (
        str(authorization_row[0])
        if authorization_row and authorization_row[0]
        else None
    )
    event_ids = []
    quote = authorization["providerQuote"]
    scope = authorization["scope"]
    for event in events:
        if not isinstance(event, dict) or not event.get("jobId"):
            continue
        amount = _event_amount(event.get("actualCredits"))
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
            )
        )
    conn.commit()
    return event_ids


def _reserved_total(conn: sqlite3.Connection, clause: str, value: str) -> float:
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM {AUTHORIZATION_TABLE} "
        f"WHERE status IN ('authorized', 'consumed') AND {clause}",
        (value,),
    ).fetchone()
    return float(row[0] or 0.0)


def _kling_count(conn: sqlite3.Connection, day: str) -> int:
    rows = conn.execute(
        f"SELECT scope_json FROM {AUTHORIZATION_TABLE} "
        "WHERE status IN ('authorized', 'consumed') AND substr(issued_at, 1, 10) = ?",
        (day,),
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
        parsed = _quote_credits(payload.get(key))
        if parsed is not None:
            return parsed
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
        parsed = _find_balance(payload.get(key))
        if parsed is not None:
            return parsed
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
