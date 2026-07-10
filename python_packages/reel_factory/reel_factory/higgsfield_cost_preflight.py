#!/usr/bin/env python3
"""Budget preflight for paid Higgsfield generation calls."""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from project_config import load_config

from reel_factory.sqlite_utils import connect_sqlite

SCHEMA = "reel_factory.higgsfield_cost_preflight.v1"
RESERVATION_SCHEMA = "reel_factory.higgsfield_spend_reservation.v1"
RESERVATION_TABLE = "higgsfield_spend_reservations"
RESERVATION_TABLE_SQL = f"""\
CREATE TABLE IF NOT EXISTS {RESERVATION_TABLE} (
    id                  TEXT PRIMARY KEY,
    provider            TEXT NOT NULL,
    source              TEXT,
    estimated_cost_usd  REAL NOT NULL,
    amount              REAL,
    unit                TEXT,
    provider_quote_json TEXT,
    cohort_id           TEXT,
    asset_count         INTEGER NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('reserved', 'consumed', 'cancelled')),
    created_at          TEXT NOT NULL,
    consumed_at         TEXT,
    cancelled_at        TEXT
)
"""
HIGGSFIELD_CREDIT_UNIT = "higgsfield_credits"


class BalanceProvider(Protocol):
    name: str

    def balance(self) -> tuple[float | None, str | None]: ...


@dataclass
class CliBalanceProvider:
    name: str = "higgsfield_cli"

    def balance(self) -> tuple[float | None, str | None]:
        cli = shutil.which("higgsfield")
        if not cli:
            return None, "higgsfield_cli_unavailable"
        proc = subprocess.run(
            [cli, "account", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None, "higgsfield_balance_unavailable"
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return None, "higgsfield_balance_unavailable"
        parsed = _parse_balance(payload)
        if parsed is not None:
            return parsed, None
        return None, "higgsfield_balance_unavailable"


def _parse_float(value: Any) -> float | None:
    """Parse a finite, non-negative money/balance value."""
    if isinstance(value, bool):
        return None
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _parse_balance(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    candidates = [
        payload.get("balance"),
        payload.get("balanceUsd"),
        payload.get("balance_usd"),
        payload.get("creditsUsd"),
        payload.get("credits_usd"),
        payload.get("credits"),
        (payload.get("account") or {}).get("balance")
        if isinstance(payload.get("account"), dict)
        else None,
        (payload.get("account") or {}).get("credits")
        if isinstance(payload.get("account"), dict)
        else None,
        (payload.get("billing") or {}).get("balanceUsd")
        if isinstance(payload.get("billing"), dict)
        else None,
        (payload.get("billing") or {}).get("credits")
        if isinstance(payload.get("billing"), dict)
        else None,
    ]
    for candidate in candidates:
        parsed = _parse_float(candidate)
        if parsed is not None:
            return parsed
    return None


def _parse_int(value: Any) -> int | None:
    """Parse a strictly positive integer without truncating floats/bools."""
    if isinstance(value, bool):
        return None
    try:
        if value is None or value == "":
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and value != parsed:
        return None
    if isinstance(value, str) and str(parsed) != value.strip():
        return None
    return parsed if parsed > 0 else None


def nonnegative_float_arg(value: str) -> float:
    parsed = _parse_float(value)
    if parsed is None:
        raise argparse.ArgumentTypeError("must be a finite, non-negative number")
    return parsed


def positive_int_arg(value: str) -> int:
    parsed = _parse_int(value)
    if parsed is None:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _campaign_cost_db_path(root: Path) -> Path:
    env_path = os.environ.get("CAMPAIGN_FACTORY_DB")
    if env_path:
        return Path(env_path).expanduser()
    root = Path(root).expanduser().resolve()
    candidates = [
        root / "campaign_factory.sqlite",
        root.parent / "campaign_factory" / "campaign_factory.sqlite",
        Path(__file__).resolve().parents[2]
        / "campaign_factory"
        / "campaign_factory.sqlite",
    ]
    return candidates[0] if candidates[0].exists() else candidates[-1]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _ensure_reservation_table(conn: sqlite3.Connection) -> None:
    conn.execute(RESERVATION_TABLE_SQL)
    columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({RESERVATION_TABLE})").fetchall()
    }
    for column, column_type in (
        ("amount", "REAL"),
        ("unit", "TEXT"),
        ("provider_quote_json", "TEXT"),
        ("cohort_id", "TEXT"),
    ):
        if column not in columns:
            conn.execute(
                f"ALTER TABLE {RESERVATION_TABLE} ADD COLUMN {column} {column_type}"
            )


def quote_higgsfield_generation(
    model: str, *, params: dict[str, str] | None = None
) -> dict[str, Any]:
    """Ask Higgsfield for the current provider-native credit quote."""
    cli = shutil.which("higgsfield")
    if not cli:
        raise RuntimeError("higgsfield_cli_unavailable")
    command = [cli, "generate", "cost", model]
    for key, value in sorted((params or {}).items()):
        command.extend([f"--{key}", str(value)])
    command.append("--json")
    proc = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError("higgsfield_quote_unavailable")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("higgsfield_quote_invalid_json") from exc
    credits = _parse_quote_credits(payload)
    if credits is None or credits <= 0:
        raise RuntimeError("higgsfield_quote_missing_credits")
    return {
        "schema": "reel_factory.higgsfield_provider_quote.v1",
        "provider": "higgsfield",
        "model": model,
        "amount": credits,
        "unit": HIGGSFIELD_CREDIT_UNIT,
        "raw": payload,
    }


def _parse_quote_credits(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("credits", "creditCost", "costCredits", "cost"):
        parsed = _parse_float(payload.get(key))
        if parsed is not None:
            return parsed
    for key in ("quote", "usage", "data", "result"):
        parsed = _parse_quote_credits(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _validated_ledger_amount(value: Any, *, source: str) -> float:
    parsed = _parse_float(value)
    if parsed is None:
        raise sqlite3.DataError(f"invalid non-negative finite cost in {source}")
    return parsed


def _spent_today_from_connection(
    conn: sqlite3.Connection, *, day: str
) -> tuple[float, float, float]:
    event_spend = 0.0
    if _table_exists(conn, "ai_cost_events"):
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(ai_cost_events)").fetchall()
        }
        reservation_filter = ""
        params: tuple[str, ...] = (day,)
        if "reservation_id" in columns and _table_exists(conn, RESERVATION_TABLE):
            # A cost event is covered only by a real active reservation.  Treat
            # missing, cancelled, and fabricated reservation ids as ordinary
            # spend so callers cannot suppress ledger usage by attaching an
            # arbitrary string to an event.
            reservation_filter = f"""
              AND (
                COALESCE(ai_cost_events.reservation_id, '') = ''
                OR NOT EXISTS (
                  SELECT 1
                  FROM {RESERVATION_TABLE} AS reservation
                  WHERE reservation.id = ai_cost_events.reservation_id
                    AND reservation.status IN ('reserved', 'consumed')
                )
              )
            """
        rows = conn.execute(
            f"""
            SELECT estimated_cost_usd
            FROM ai_cost_events
            WHERE substr(created_at, 1, 10) = ?{reservation_filter}
            """,
            params,
        ).fetchall()
        event_spend = sum(
            _validated_ledger_amount(row[0], source="ai_cost_events") for row in rows
        )

    reservation_spend = 0.0
    if _table_exists(conn, RESERVATION_TABLE):
        rows = conn.execute(
            f"""
            SELECT estimated_cost_usd
            FROM {RESERVATION_TABLE}
            WHERE substr(created_at, 1, 10) = ?
              AND status IN ('reserved', 'consumed')
            """,
            (day,),
        ).fetchall()
        reservation_spend = sum(
            _validated_ledger_amount(row[0], source=RESERVATION_TABLE) for row in rows
        )
    total = event_spend + reservation_spend
    if not math.isfinite(total):
        raise sqlite3.DataError("cost ledger total is not finite")
    return total, event_spend, reservation_spend


def _spent_today_usd(
    root: Path,
    *,
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> tuple[float, float, float]:
    db_path = (
        Path(cost_db_path).expanduser()
        if cost_db_path is not None
        else _campaign_cost_db_path(root)
    )
    if not db_path.exists():
        return 0.0, 0.0, 0.0
    now = now or datetime.datetime.now(datetime.UTC)
    day = now.date().isoformat()
    with connect_sqlite(db_path, readonly=True, wal=False) as conn:
        return _spent_today_from_connection(conn, day=day)


@dataclass(frozen=True)
class _BudgetPolicy:
    daily_budget: float | None
    max_assets: int | None
    minimum_balance: float | None
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]


def _configured_value(
    *,
    env_name: str,
    config: dict[str, Any],
    config_name: str,
    parser,
) -> tuple[Any, str | None]:
    if env_name in os.environ:
        raw = os.environ.get(env_name)
        parsed = parser(raw)
        return parsed, None if parsed is not None else "invalid"
    raw = config.get(config_name)
    if raw is None or raw == "":
        return None, "missing"
    parsed = parser(raw)
    return parsed, None if parsed is not None else "invalid"


def _budget_policy(root_path: Path) -> _BudgetPolicy:
    config = load_config(root_path)
    values: dict[str, Any] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for env_name, config_name, parser, key in (
        (
            "HIGGSFIELD_DAILY_BUDGET_USD",
            "dailyBudgetUsd",
            _parse_float,
            "daily_budget",
        ),
        (
            "HIGGSFIELD_RUN_MAX_ASSETS",
            "perRunMaxAssets",
            _parse_int,
            "max_assets",
        ),
        (
            "HIGGSFIELD_MIN_BALANCE_USD",
            "minimumBalanceUsd",
            _parse_float,
            "minimum_balance",
        ),
    ):
        parsed, error = _configured_value(
            env_name=env_name,
            config=config,
            config_name=config_name,
            parser=parser,
        )
        values[key] = parsed
        if error == "missing":
            missing.append(env_name)
        elif error == "invalid":
            invalid.append(env_name)
    return _BudgetPolicy(
        daily_budget=values["daily_budget"],
        max_assets=values["max_assets"],
        minimum_balance=values["minimum_balance"],
        missing_fields=tuple(missing),
        invalid_fields=tuple(invalid),
    )


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def _build_preflight_result(
    *,
    asset_count: Any,
    estimated_cost_usd: Any,
    provider: BalanceProvider,
    policy: _BudgetPolicy,
    spent_today: float,
    event_spend: float,
    reservation_spend: float,
    ledger_error: str | None,
    allow_unbudgeted_local_test: bool,
    budget_override_ledger_error: bool,
    reservation_mode: bool,
    balance_result: tuple[float | None, str | None] | None = None,
) -> dict[str, Any]:
    normalized_asset_count = _parse_int(asset_count)
    normalized_estimate = _parse_float(estimated_cost_usd)
    estimate_missing = estimated_cost_usd is None or estimated_cost_usd == ""
    balance_raw, balance_error = balance_result or provider.balance()
    balance = _parse_float(balance_raw)

    reasons: list[str] = []
    if policy.invalid_fields:
        reasons.append("budget_policy_invalid")
    if policy.missing_fields:
        reasons.append("budget_policy_missing")
    if normalized_asset_count is None:
        reasons.append("invalid_asset_count")
    elif policy.max_assets is not None and normalized_asset_count > policy.max_assets:
        reasons.append("run_asset_limit_exceeded")
    if estimate_missing:
        reasons.append("cost_estimate_missing")
    elif normalized_estimate is None:
        reasons.append("invalid_cost_estimate")
    elif reservation_mode and normalized_estimate == 0:
        reasons.append("cost_estimate_must_be_positive_for_paid_generation")
    if balance_raw is None:
        reasons.append(balance_error or "balance_unavailable")
    elif balance is None:
        reasons.append("balance_invalid")
    elif policy.minimum_balance is not None and balance < policy.minimum_balance:
        reasons.append("minimum_balance_not_met")
    if ledger_error:
        reasons.append("cost_ledger_unreadable")

    projected_daily_spend = spent_today + (normalized_estimate or 0.0)
    if not math.isfinite(projected_daily_spend):
        reasons.append("invalid_projected_daily_spend")
        projected_daily_spend = spent_today
    if policy.daily_budget is not None and projected_daily_spend > policy.daily_budget:
        reasons.append("estimated_cost_exceeds_daily_budget")

    if reservation_mode and (
        allow_unbudgeted_local_test or budget_override_ledger_error
    ):
        reasons.append("unsafe_cost_override_not_allowed_for_paid_generation")
    elif allow_unbudgeted_local_test:
        overridable = {
            "budget_policy_missing",
            "cost_estimate_missing",
            "balance_unavailable",
            "higgsfield_balance_unavailable",
        }
        reasons = [reason for reason in reasons if reason not in overridable]
        if budget_override_ledger_error:
            reasons = [
                reason for reason in reasons if reason != "cost_ledger_unreadable"
            ]

    reasons = _dedupe_reasons(reasons)
    allowed = not reasons
    return {
        "schema": SCHEMA,
        "balanceChecked": balance is not None,
        "balanceUsd": balance,
        "balanceProvider": provider.name,
        "budgetPolicy": {
            "dailyBudgetUsd": policy.daily_budget,
            "perRunMaxAssets": policy.max_assets,
            "minimumBalanceUsd": policy.minimum_balance,
            "estimatedCostUsd": normalized_estimate,
            "spentTodayUsd": round(spent_today, 4),
            "legacyEventSpendTodayUsd": round(event_spend, 4),
            "reservedOrConsumedTodayUsd": round(reservation_spend, 4),
            "projectedDailySpendUsd": round(projected_daily_spend, 4),
            "assetCount": normalized_asset_count,
            "costLedgerReadable": ledger_error is None,
            "costLedgerError": ledger_error,
            "missingPolicyFields": list(policy.missing_fields),
            "invalidPolicyFields": list(policy.invalid_fields),
            "estimateInputInvalid": not estimate_missing
            and normalized_estimate is None,
            "assetCountInputInvalid": normalized_asset_count is None,
        },
        "allowed": allowed,
        "blockingReason": "" if allowed else reasons[0],
        "blockingReasons": reasons,
        "localTestOverride": bool(allow_unbudgeted_local_test),
        "budgetOverrideLedgerError": bool(budget_override_ledger_error),
        "reservationRequired": reservation_mode,
    }


def check_higgsfield_cost_preflight(
    *,
    asset_count: int,
    estimated_cost_usd: float | None = None,
    provider: BalanceProvider | None = None,
    allow_unbudgeted_local_test: bool = False,
    budget_override_ledger_error: bool = False,
    root: str | Path = ".",
    cost_db_path: str | Path | None = None,
) -> dict[str, Any]:
    provider = provider or CliBalanceProvider()
    root_path = Path(root)
    policy = _budget_policy(root_path)
    ledger_error: str | None = None
    try:
        spent_today, event_spend, reservation_spend = _spent_today_usd(
            root_path, cost_db_path=cost_db_path
        )
    except sqlite3.Error as exc:
        spent_today = event_spend = reservation_spend = 0.0
        ledger_error = str(exc)
    return _build_preflight_result(
        asset_count=asset_count,
        estimated_cost_usd=estimated_cost_usd,
        provider=provider,
        policy=policy,
        spent_today=spent_today,
        event_spend=event_spend,
        reservation_spend=reservation_spend,
        ledger_error=ledger_error,
        allow_unbudgeted_local_test=allow_unbudgeted_local_test,
        budget_override_ledger_error=budget_override_ledger_error,
        reservation_mode=False,
    )


def reserve_higgsfield_spend(
    *,
    asset_count: int,
    estimated_cost_usd: float | None,
    provider: BalanceProvider | None = None,
    source: str | None = None,
    allow_unbudgeted_local_test: bool = False,
    budget_override_ledger_error: bool = False,
    root: str | Path = ".",
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Atomically validate remaining budget and reserve it before a paid call."""
    provider = provider or CliBalanceProvider()
    root_path = Path(root)
    policy = _budget_policy(root_path)
    db_path = (
        Path(cost_db_path).expanduser()
        if cost_db_path is not None
        else _campaign_cost_db_path(root_path)
    )
    timestamp = now or datetime.datetime.now(datetime.UTC)
    created_at = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    reservation_id = f"hfr_{uuid.uuid4().hex}"
    balance_result = provider.balance()
    try:
        with connect_sqlite(db_path, wal=False) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(RESERVATION_TABLE_SQL)
            spent_today, event_spend, reservation_spend = _spent_today_from_connection(
                conn, day=timestamp.date().isoformat()
            )
            result = _build_preflight_result(
                asset_count=asset_count,
                estimated_cost_usd=estimated_cost_usd,
                provider=provider,
                policy=policy,
                spent_today=spent_today,
                event_spend=event_spend,
                reservation_spend=reservation_spend,
                ledger_error=None,
                allow_unbudgeted_local_test=allow_unbudgeted_local_test,
                budget_override_ledger_error=budget_override_ledger_error,
                reservation_mode=True,
                balance_result=balance_result,
            )
            if result["allowed"]:
                conn.execute(
                    f"""
                    INSERT INTO {RESERVATION_TABLE}
                        (id, provider, source, estimated_cost_usd, asset_count,
                         status, created_at)
                    VALUES (?, 'higgsfield', ?, ?, ?, 'reserved', ?)
                    """,
                    (
                        reservation_id,
                        source,
                        result["budgetPolicy"]["estimatedCostUsd"],
                        result["budgetPolicy"]["assetCount"],
                        created_at,
                    ),
                )
            conn.commit()
    except sqlite3.Error as exc:
        result = _build_preflight_result(
            asset_count=asset_count,
            estimated_cost_usd=estimated_cost_usd,
            provider=provider,
            policy=policy,
            spent_today=0.0,
            event_spend=0.0,
            reservation_spend=0.0,
            ledger_error=str(exc),
            allow_unbudgeted_local_test=allow_unbudgeted_local_test,
            budget_override_ledger_error=budget_override_ledger_error,
            reservation_mode=True,
            balance_result=balance_result,
        )
    result["reservation"] = {
        "schema": RESERVATION_SCHEMA,
        "id": reservation_id if result["allowed"] else None,
        "status": "reserved" if result["allowed"] else "not_created",
        "source": source,
    }
    return result


def reserve_higgsfield_credits(
    *,
    provider_quote: dict[str, Any],
    asset_count: int,
    cohort_id: str,
    source: str | None = None,
    provider: BalanceProvider | None = None,
    root: str | Path = ".",
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Atomically reserve a current Higgsfield credit quote.

    This is the authoritative paid path. Legacy USD reservations remain only
    for compatibility and must not be used by cohort or acceptance runs.
    """
    amount = _parse_float(provider_quote.get("amount"))
    unit = provider_quote.get("unit")
    normalized_assets = _parse_int(asset_count)
    if amount is None or amount <= 0 or unit != HIGGSFIELD_CREDIT_UNIT:
        raise ValueError("provider quote must contain positive Higgsfield credits")
    if normalized_assets is None:
        raise ValueError("asset_count must be a positive integer")
    if not isinstance(cohort_id, str) or not cohort_id.strip():
        raise ValueError("cohort_id is required")

    daily_budget = _required_positive_env("HIGGSFIELD_DAILY_BUDGET_CREDITS")
    run_max_assets = _required_positive_int_env("HIGGSFIELD_RUN_MAX_ASSETS")
    cohort_cap = _required_positive_env("HIGGSFIELD_COHORT_MAX_CREDITS")
    min_balance = _required_nonnegative_env("HIGGSFIELD_MIN_BALANCE_CREDITS")
    provider = provider or CliBalanceProvider()
    balance_raw, balance_error = provider.balance()
    balance = _parse_float(balance_raw)

    reasons: list[str] = []
    if normalized_assets > run_max_assets:
        reasons.append("run_asset_limit_exceeded")
    if balance is None:
        reasons.append(balance_error or "higgsfield_balance_unavailable")
    elif balance - amount < min_balance:
        reasons.append("projected_balance_below_minimum")

    root_path = Path(root)
    db_path = (
        Path(cost_db_path).expanduser()
        if cost_db_path is not None
        else _campaign_cost_db_path(root_path)
    )
    timestamp = now or datetime.datetime.now(datetime.UTC)
    created_at = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    reservation_id = f"hfr_{uuid.uuid4().hex}"
    daily_spend = cohort_spend = 0.0
    try:
        with connect_sqlite(db_path, wal=False) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_reservation_table(conn)
            daily_spend = _credit_reservation_total(
                conn, day=timestamp.date().isoformat()
            )
            cohort_spend = _credit_reservation_total(conn, cohort_id=cohort_id)
            if daily_spend + amount > daily_budget:
                reasons.append("projected_daily_credits_exceeded")
            if cohort_spend + amount > cohort_cap:
                reasons.append("projected_cohort_credits_exceeded")
            reasons = _dedupe_reasons(reasons)
            if not reasons:
                compatibility_usd = _credits_to_compatibility_usd(amount)
                conn.execute(
                    f"""
                    INSERT INTO {RESERVATION_TABLE}
                        (id, provider, source, estimated_cost_usd, amount, unit,
                         provider_quote_json, cohort_id, asset_count, status, created_at)
                    VALUES (?, 'higgsfield', ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)
                    """,
                    (
                        reservation_id,
                        source,
                        compatibility_usd,
                        amount,
                        HIGGSFIELD_CREDIT_UNIT,
                        json.dumps(provider_quote, sort_keys=True),
                        cohort_id,
                        normalized_assets,
                        created_at,
                    ),
                )
            conn.commit()
    except sqlite3.Error as exc:
        reasons.append("cost_ledger_unreadable")
        reasons.append(str(exc))

    allowed = not reasons
    return {
        "schema": SCHEMA,
        "allowed": allowed,
        "blockingReason": "" if allowed else reasons[0],
        "blockingReasons": reasons,
        "providerQuote": provider_quote,
        "balanceCredits": balance,
        "budgetPolicy": {
            "dailyBudgetCredits": daily_budget,
            "cohortMaxCredits": cohort_cap,
            "minimumBalanceCredits": min_balance,
            "perRunMaxAssets": run_max_assets,
            "spentTodayCredits": round(daily_spend, 4),
            "cohortSpentCredits": round(cohort_spend, 4),
            "projectedDailyCredits": round(daily_spend + amount, 4),
            "projectedCohortCredits": round(cohort_spend + amount, 4),
            "projectedBalanceCredits": None
            if balance is None
            else round(balance - amount, 4),
        },
        "reservation": {
            "schema": RESERVATION_SCHEMA,
            "id": reservation_id if allowed else None,
            "status": "reserved" if allowed else "not_created",
            "source": source,
            "cohortId": cohort_id,
            "amount": amount,
            "unit": HIGGSFIELD_CREDIT_UNIT,
        },
    }


def _credit_reservation_total(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
    cohort_id: str | None = None,
) -> float:
    clauses = ["unit = ?", "status IN ('reserved', 'consumed')"]
    params: list[Any] = [HIGGSFIELD_CREDIT_UNIT]
    if day is not None:
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(day)
    if cohort_id is not None:
        clauses.append("cohort_id = ?")
        params.append(cohort_id)
    rows = conn.execute(
        f"SELECT amount FROM {RESERVATION_TABLE} WHERE {' AND '.join(clauses)}",
        params,
    ).fetchall()
    return sum(
        _validated_ledger_amount(row[0], source=RESERVATION_TABLE) for row in rows
    )


def _required_positive_env(name: str) -> float:
    parsed = _parse_float(os.environ.get(name))
    if parsed is None or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


def _required_nonnegative_env(name: str) -> float:
    parsed = _parse_float(os.environ.get(name))
    if parsed is None:
        raise ValueError(f"{name} must be a finite non-negative number")
    return parsed


def _required_positive_int_env(name: str) -> int:
    parsed = _parse_int(os.environ.get(name))
    if parsed is None:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _credits_to_compatibility_usd(amount: float) -> float:
    raw = os.environ.get("HIGGSFIELD_USD_PER_CREDIT")
    if raw is None or raw == "":
        return 0.0
    conversion = _parse_float(raw)
    if conversion is None or conversion <= 0:
        raise ValueError(
            "HIGGSFIELD_USD_PER_CREDIT must be finite and positive when configured"
        )
    return round(amount * conversion, 8)


def _transition_reservation(
    reservation_id: str,
    *,
    status: str,
    timestamp_column: str,
    root: str | Path,
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> bool:
    if status not in {"consumed", "cancelled"}:
        raise ValueError("invalid reservation transition")
    db_path = (
        Path(cost_db_path).expanduser()
        if cost_db_path is not None
        else _campaign_cost_db_path(Path(root))
    )
    timestamp = (now or datetime.datetime.now(datetime.UTC)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    with connect_sqlite(db_path, wal=False) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(RESERVATION_TABLE_SQL)
        current = conn.execute(
            f"SELECT status FROM {RESERVATION_TABLE} WHERE id = ?",
            (reservation_id,),
        ).fetchone()
        if current is None:
            conn.rollback()
            return False
        current_status = str(current[0])
        if current_status == status:
            conn.commit()
            return True
        if current_status != "reserved":
            conn.rollback()
            return False
        conn.execute(
            f"""
            UPDATE {RESERVATION_TABLE}
            SET status = ?, {timestamp_column} = ?
            WHERE id = ? AND status = 'reserved'
            """,
            (status, timestamp, reservation_id),
        )
        conn.commit()
    return True


def consume_higgsfield_spend_reservation(
    reservation_id: str,
    *,
    root: str | Path = ".",
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> bool:
    """Make a reservation permanent immediately before the provider call."""
    return _transition_reservation(
        reservation_id,
        status="consumed",
        timestamp_column="consumed_at",
        root=root,
        cost_db_path=cost_db_path,
        now=now,
    )


def cancel_higgsfield_spend_reservation(
    reservation_id: str,
    *,
    root: str | Path = ".",
    cost_db_path: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> bool:
    """Cancel only an unconsumed reservation (for setup/no-op failures)."""
    return _transition_reservation(
        reservation_id,
        status="cancelled",
        timestamp_column="cancelled_at",
        root=root,
        cost_db_path=cost_db_path,
        now=now,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asset-count", type=positive_int_arg, required=True)
    ap.add_argument("--estimated-cost-usd", type=nonnegative_float_arg)
    ap.add_argument("--allow-unbudgeted-local-test", action="store_true")
    ap.add_argument("--budget-override-ledger-error", action="store_true")
    args = ap.parse_args()
    result = check_higgsfield_cost_preflight(
        asset_count=args.asset_count,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
        budget_override_ledger_error=args.budget_override_ledger_error,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
