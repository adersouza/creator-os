from __future__ import annotations

import json
import os
from pathlib import Path

from .config import get_settings


def print_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def load_json_object(path: str | None) -> dict | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def decision_ledger_kwargs(args) -> dict:
    return {
        "creator": args.creator,
        "date": args.date,
        "threadsdash_report": load_json_object(args.threadsdash_report_json),
        "schedule_plan": load_json_object(args.schedule_plan_json),
        "time_plan": load_json_object(args.time_plan_json),
        "winner_expansion_report": load_json_object(args.winner_expansion_report_json),
        "winner_expansion_plan": load_json_object(args.winner_expansion_plan_json),
        "variant_inventory_plan": load_json_object(args.variant_inventory_plan_json),
        "variant_metrics_rollup": load_json_object(args.variant_metrics_rollup_json),
        "account_tiers": load_json_object(args.account_tiers_json),
    }


def load_hooks(path: str | None, values: list[str] | None) -> list[str | dict]:
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("hooks") or []
        if isinstance(data, list):
            return data
    return values or []


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _threadsdash_supabase_args(args) -> tuple[str | None, str | None]:
    settings = get_settings()
    env_file = (
        Path(args.threadsdash_env_file)
        if getattr(args, "threadsdash_env_file", None)
        else settings.threadsdash_root / ".env.local"
    )
    env_values = _load_env_file(env_file)
    url = (
        getattr(args, "supabase_url", None)
        or os.environ.get("SUPABASE_URL")
        or os.environ.get("VITE_SUPABASE_URL")
        or env_values.get("SUPABASE_URL")
        or env_values.get("VITE_SUPABASE_URL")
        or env_values.get("NEXT_PUBLIC_SUPABASE_URL")
    )
    key = (
        getattr(args, "supabase_service_role_key", None)
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or env_values.get("SUPABASE_SERVICE_ROLE_KEY")
        or env_values.get("SUPABASE_SERVICE_KEY")
    )
    return (url, key)
