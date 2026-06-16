#!/usr/bin/env python3
"""Budget preflight for paid Higgsfield generation calls."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol


SCHEMA = "reel_factory.higgsfield_cost_preflight.v1"


class BalanceProvider(Protocol):
    name: str

    def balance(self) -> tuple[float | None, str | None]:
        ...


@dataclass
class CliBalanceProvider:
    name: str = "higgsfield_cli"

    def balance(self) -> tuple[float | None, str | None]:
        cli = shutil.which("higgsfield")
        if not cli:
            return None, "higgsfield_cli_unavailable"
        for cmd in (
            [cli, "account", "status", "--json"],
            [cli, "balance", "--json"],
        ):
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                continue
            try:
                payload = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError:
                continue
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
        (payload.get("account") or {}).get("balance") if isinstance(payload.get("account"), dict) else None,
        (payload.get("billing") or {}).get("balanceUsd") if isinstance(payload.get("billing"), dict) else None,
    ]
    for candidate in candidates:
        parsed = _parse_float(candidate)
        if parsed is not None:
            return parsed
    return None


def _env_float(name: str) -> float | None:
    return _parse_float(os.environ.get(name))


def _env_int(name: str) -> int | None:
    try:
        value = os.environ.get(name)
        if value is None or value == "":
            return None
        return int(value)
    except ValueError:
        return None


def check_higgsfield_cost_preflight(
    *,
    asset_count: int,
    estimated_cost_usd: float | None = None,
    provider: BalanceProvider | None = None,
    allow_unbudgeted_local_test: bool = False,
) -> dict[str, Any]:
    provider = provider or CliBalanceProvider()
    daily_budget = _env_float("HIGGSFIELD_DAILY_BUDGET_USD")
    max_assets = _env_int("HIGGSFIELD_RUN_MAX_ASSETS")
    minimum_balance = _env_float("HIGGSFIELD_MIN_BALANCE_USD")
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
    if estimated_cost_usd is not None and daily_budget is not None and estimated_cost_usd > daily_budget:
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
            "assetCount": asset_count,
        },
        "allowed": allowed,
        "blockingReason": "" if allowed else blocking_reasons[0],
        "blockingReasons": blocking_reasons,
        "localTestOverride": bool(allow_unbudgeted_local_test),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asset-count", type=int, required=True)
    ap.add_argument("--estimated-cost-usd", type=float)
    ap.add_argument("--allow-unbudgeted-local-test", action="store_true")
    args = ap.parse_args()
    result = check_higgsfield_cost_preflight(
        asset_count=args.asset_count,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
