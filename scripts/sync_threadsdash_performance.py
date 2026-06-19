#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence


REQUIRED_ENV = (
    "CAMPAIGN_FACTORY_SYNC_CAMPAIGN",
    "THREADSDASH_USER_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)


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


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = list(argv or [])
    environment = dict(env or os.environ)
    try:
        command = build_sync_command(environment)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if "--dry-run" in args:
        safe = [
            "<redacted>" if value == environment["SUPABASE_SERVICE_ROLE_KEY"] else value
            for value in command
        ]
        print(" ".join(safe))
        return 0
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
