#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REQUIRED_ENV = (
    "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS",
    "THREADSDASH_USER_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "LEARNING_LOOP_CUTOVER",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN_FACTORY_DB = (
    REPO_ROOT / "python_packages" / "campaign_factory" / "campaign_factory.sqlite"
)
DEFAULT_REEL_FACTORY_ROOT = REPO_ROOT / "python_packages" / "reel_factory"
DEFAULT_REFERENCE_FACTORY_DB = (
    Path.home() / "Developer" / "reference_reels" / "reference_factory.sqlite"
)


def configured_campaigns(env: Mapping[str, str]) -> list[str]:
    raw = env.get("CAMPAIGN_FACTORY_SYNC_CAMPAIGNS")
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise ValueError(
            "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS must be a JSON array"
        ) from exc
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(
            "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS must be a non-empty JSON string array"
        )
    campaigns = [item.strip() for item in value]
    if len(campaigns) != len(set(campaigns)):
        raise ValueError("CAMPAIGN_FACTORY_SYNC_CAMPAIGNS contains duplicates")
    return campaigns


def build_sync_command(
    env: Mapping[str, str], campaign: str | None = None
) -> list[str]:
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
        campaign or configured_campaigns(env)[0],
        "--user-id",
        env["THREADSDASH_USER_ID"],
        "--supabase-url",
        env["SUPABASE_URL"],
        "--supabase-service-role-key",
        env["SUPABASE_SERVICE_ROLE_KEY"],
        "--limit",
        limit,
    ]


def build_fanout_command(
    env: Mapping[str, str], campaign: str | None = None
) -> list[str]:
    reel_factory_root = Path(env.get("REEL_FACTORY_ROOT") or DEFAULT_REEL_FACTORY_ROOT)
    campaign_factory_db = Path(
        env.get("CAMPAIGN_FACTORY_DB") or DEFAULT_CAMPAIGN_FACTORY_DB
    )
    reference_factory_db = Path(
        env.get("REFERENCE_FACTORY_DB") or DEFAULT_REFERENCE_FACTORY_DB
    )
    return [
        "uv",
        "run",
        "python",
        str(REPO_ROOT / "scripts" / "learning_fanout.py"),
        "--campaign-factory-db",
        str(campaign_factory_db),
        "--reel-factory-root",
        str(reel_factory_root),
        "--reference-factory-db",
        str(reference_factory_db),
        "--campaign",
        campaign or configured_campaigns(env)[0],
    ]


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    args = list(argv or [])
    environment = dict(env or os.environ)
    try:
        campaigns = configured_campaigns(environment)
        commands = [build_sync_command(environment, campaign) for campaign in campaigns]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if "--dry-run" in args:
        for campaign, command in zip(campaigns, commands, strict=True):
            for cmd in (command, build_fanout_command(environment, campaign)):
                safe = [
                    "<redacted>"
                    if value == environment["SUPABASE_SERVICE_ROLE_KEY"]
                    else value
                    for value in cmd
                ]
                print(" ".join(safe))
        return 0
    reports: list[dict[str, object]] = []
    for campaign, command in zip(campaigns, commands, strict=True):
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            _forward_phase_output(completed)
            return completed.returncode
        try:
            performance_report = _json_report(completed, phase="performance sync")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        fanout = subprocess.run(
            build_fanout_command(environment, campaign),
            check=False,
            capture_output=True,
            text=True,
        )
        if fanout.returncode != 0:
            _forward_phase_output(fanout)
            return fanout.returncode
        try:
            fanout_report = _json_report(fanout, phase="learning fan-out")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        reports.append(
            {
                "campaign": campaign,
                "performanceSync": performance_report,
                "learningFanout": fanout_report,
            }
        )
    print(
        json.dumps(
            {
                "schema": "creator_os.hourly_learning_sync.v1",
                "campaigns": reports,
                "performanceSync": reports[0]["performanceSync"],
                "learningFanout": reports[0]["learningFanout"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _json_report(
    completed: subprocess.CompletedProcess[str], *, phase: str
) -> dict[str, object]:
    raw = (completed.stdout or "").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{phase} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{phase} returned non-object JSON")
    return value


def _forward_phase_output(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.stdout:
        print(completed.stdout.rstrip(), file=sys.stdout)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
