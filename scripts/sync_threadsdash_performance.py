#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


REQUIRED_ENV = (
    "CAMPAIGN_FACTORY_SYNC_CAMPAIGN",
    "THREADSDASH_USER_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN_FACTORY_DB = (
    REPO_ROOT / "python_packages" / "campaign_factory" / "campaign_factory.sqlite"
)
DEFAULT_REEL_FACTORY_ROOT = REPO_ROOT / "python_packages" / "reel_factory"


def build_sync_command(env: Mapping[str, str]) -> list[str]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError(f"missing required performance sync env: {', '.join(missing)}")
    limit = env.get("CAMPAIGN_FACTORY_SYNC_LIMIT", "1000")
    return [
        "uv",
        "run",
        "campaign-factory",
        "sync-performance",
        "--campaign",
        env["CAMPAIGN_FACTORY_SYNC_CAMPAIGN"],
        "--user-id",
        env["THREADSDASH_USER_ID"],
        "--supabase-url",
        env["SUPABASE_URL"],
        "--supabase-service-role-key",
        env["SUPABASE_SERVICE_ROLE_KEY"],
        "--limit",
        limit,
    ]


def build_refresh_command(env: Mapping[str, str]) -> list[str]:
    reel_factory_root = Path(env.get("REEL_FACTORY_ROOT") or DEFAULT_REEL_FACTORY_ROOT)
    campaign_factory_db = Path(
        env.get("CAMPAIGN_FACTORY_DB") or DEFAULT_CAMPAIGN_FACTORY_DB
    )
    return [
        "uv",
        "run",
        "--directory",
        str(reel_factory_root),
        "python",
        "metrics_store.py",
        "--root",
        str(reel_factory_root),
        "refresh-outcomes",
        "--campaign-factory-db",
        str(campaign_factory_db),
        "--campaign",
        env["CAMPAIGN_FACTORY_SYNC_CAMPAIGN"],
    ]


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = list(argv or [])
    environment = dict(env or os.environ)
    try:
        command = build_sync_command(environment)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if "--dry-run" in args:
        for cmd in (command, build_refresh_command(environment)):
            safe = [
                "<redacted>"
                if value == environment["SUPABASE_SERVICE_ROLE_KEY"]
                else value
                for value in cmd
            ]
            print(" ".join(safe))
        return 0
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return completed.returncode
    refreshed = subprocess.run(build_refresh_command(environment), check=False)
    return refreshed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
