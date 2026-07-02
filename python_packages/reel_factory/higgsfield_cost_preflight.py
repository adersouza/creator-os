#!/usr/bin/env python3
"""Budget preflight for paid Higgsfield generation calls."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from project_config import load_config
from reel_factory.sqlite_utils import connect_sqlite

SCHEMA = "reel_factory.higgsfield_cost_preflight.v1"


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
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _env_float(name: str) -> float | None:
    return _parse_float(os.environ.get(name))


def _env_int(name: str) -> int | None:
    return _parse_int(os.environ.get(name))


def _parse_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _campaign_cost_db_path(root: Path) -> Path:
    env_path = os.environ.get("CAMPAIGN_FACTORY_DB")
    if env_path:
        return Path(env_path).expanduser()
    root = Path(root).expanduser().resolve()
    candidates = [
        root / "campaign_factory.sqlite",
        root.parent / "campaign_factory" / "campaign_factory.sqlite",
        Path(__file__).resolve().parent.parent
        / "campaign_factory"
        / "campaign_factory.sqlite",
    ]
    return candidates[0] if candidates[0].exists() else candidates[-1]


def _spent_today_usd(root: Path, *, now: datetime.datetime | None = None) -> float:
    db_path = _campaign_cost_db_path(root)
    if not db_path.exists():
        return 0.0
    now = now or datetime.datetime.now(datetime.UTC)
    day = now.date().isoformat()
    with connect_sqlite(db_path, readonly=True, wal=False) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(estimated_cost_usd), 0)
            FROM ai_cost_events
            WHERE substr(created_at, 1, 10) = ?
            """,
            (day,),
        ).fetchone()
    return float(row[0] or 0.0)


def check_higgsfield_cost_preflight(
    *,
    asset_count: int,
    estimated_cost_usd: float | None = None,
    provider: BalanceProvider | None = None,
    allow_unbudgeted_local_test: bool = False,
    budget_override_ledger_error: bool = False,
    root: str | Path = ".",
) -> dict[str, Any]:
    provider = provider or CliBalanceProvider()
    root_path = Path(root)
    config = load_config(root_path)
    daily_budget = _env_float("HIGGSFIELD_DAILY_BUDGET_USD")
    if daily_budget is None:
        daily_budget = _parse_float(config.get("dailyBudgetUsd"))
    max_assets = _env_int("HIGGSFIELD_RUN_MAX_ASSETS")
    if max_assets is None:
        max_assets = _parse_int(config.get("perRunMaxAssets"))
    minimum_balance = _env_float("HIGGSFIELD_MIN_BALANCE_USD")
    if minimum_balance is None:
        minimum_balance = _parse_float(config.get("minimumBalanceUsd"))
    missing = [
        name
        for name, value in (
            ("HIGGSFIELD_DAILY_BUDGET_USD", daily_budget),
            ("HIGGSFIELD_RUN_MAX_ASSETS", max_assets),
            ("HIGGSFIELD_MIN_BALANCE_USD", minimum_balance),
        )
        if value is None
    ]
    balance, balance_error = provider.balance()
    blocking_reasons: list[str] = []
    if missing:
        blocking_reasons.append("budget_policy_missing")
    if max_assets is not None and asset_count > max_assets:
        blocking_reasons.append("run_asset_limit_exceeded")
    if balance is None:
        blocking_reasons.append(balance_error or "balance_unavailable")
    elif minimum_balance is not None and balance < minimum_balance:
        blocking_reasons.append("minimum_balance_not_met")
    ledger_error: str | None = None
    try:
        spent_today = _spent_today_usd(root_path)
    except sqlite3.Error as exc:
        spent_today = 0.0
        ledger_error = str(exc)
        if not budget_override_ledger_error:
            blocking_reasons.append("cost_ledger_unreadable")
    projected_daily_spend = spent_today + (estimated_cost_usd or 0.0)
    if estimated_cost_usd is None:
        # A missing estimate would make the daily-budget check pass trivially;
        # block instead of silently spending unbudgeted.
        blocking_reasons.append("cost_estimate_missing")
    if daily_budget is not None and projected_daily_spend > daily_budget:
        blocking_reasons.append("estimated_cost_exceeds_daily_budget")
    if allow_unbudgeted_local_test:
        blocking_reasons = []
    allowed = not blocking_reasons
    return {
        "schema": SCHEMA,
        "balanceChecked": balance is not None,
        "balanceUsd": balance,
        "balanceProvider": provider.name,
        "budgetPolicy": {
            "dailyBudgetUsd": daily_budget,
            "perRunMaxAssets": max_assets,
            "minimumBalanceUsd": minimum_balance,
            "estimatedCostUsd": estimated_cost_usd,
            "spentTodayUsd": round(spent_today, 4),
            "projectedDailySpendUsd": round(projected_daily_spend, 4),
            "assetCount": asset_count,
            "costLedgerReadable": ledger_error is None,
            "costLedgerError": ledger_error,
        },
        "allowed": allowed,
        "blockingReason": "" if allowed else blocking_reasons[0],
        "blockingReasons": blocking_reasons,
        "localTestOverride": bool(allow_unbudgeted_local_test),
        "budgetOverrideLedgerError": bool(budget_override_ledger_error),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asset-count", type=int, required=True)
    ap.add_argument("--estimated-cost-usd", type=float)
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
