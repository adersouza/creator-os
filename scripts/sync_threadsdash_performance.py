#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

REQUIRED_ENV = (
    "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS",
    "THREADSDASH_USER_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "LEARNING_LOOP_CUTOVER",
)

DEFAULT_SYNC_LIMIT = 10_000

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages/creator_os_core"))

from creator_os_core.runtime_paths import resolve_runtime_paths  # noqa: E402

_PATHS = resolve_runtime_paths(REPO_ROOT)
DEFAULT_CAMPAIGN_FACTORY_DB = _PATHS.campaign_factory_db
DEFAULT_REFERENCE_FACTORY_DB = _PATHS.reference_factory_db


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
    env: Mapping[str, str],
    campaign: str | None = None,
    *,
    run_id: str | None = None,
) -> list[str]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError(f"missing required performance sync env: {', '.join(missing)}")
    try:
        limit = int(env.get("CAMPAIGN_FACTORY_SYNC_LIMIT", str(DEFAULT_SYNC_LIMIT)))
    except ValueError as exc:
        raise ValueError(
            "CAMPAIGN_FACTORY_SYNC_LIMIT must be a positive integer"
        ) from exc
    if limit <= 0:
        raise ValueError("CAMPAIGN_FACTORY_SYNC_LIMIT must be a positive integer")
    selected_campaign = campaign or configured_campaigns(env)[0]
    selected_run_id = run_id or uuid.uuid4().hex
    return [
        "uv",
        "run",
        "campaign-factory",
        "--idempotency-key",
        f"performance-sync:{selected_campaign}:{selected_run_id}",
        "sync-performance",
        "--campaign",
        selected_campaign,
        "--user-id",
        env["THREADSDASH_USER_ID"],
        "--supabase-url",
        env["SUPABASE_URL"],
        "--supabase-service-role-key",
        env["SUPABASE_SERVICE_ROLE_KEY"],
        "--limit",
        str(limit),
    ]


def build_fanout_command(
    env: Mapping[str, str], campaign: str | None = None
) -> list[str]:
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
        "--reference-factory-db",
        str(reference_factory_db),
        "--campaign",
        campaign or configured_campaigns(env)[0],
    ]


def build_learning_refresh_command() -> list[str]:
    return [
        "uv",
        "run",
        "--package",
        "campaign-factory",
        "python",
        str(REPO_ROOT / "scripts" / "learning_refresh.py"),
        "refresh",
        "--apply",
    ]


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    args = list(argv or [])
    environment = dict(env or os.environ)
    try:
        campaigns = configured_campaigns(environment)
        run_id = uuid.uuid4().hex
        commands = [
            build_sync_command(environment, campaign, run_id=run_id)
            for campaign in campaigns
        ]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if "--dry-run" in args:
        for campaign, command in zip(campaigns, commands, strict=True):
            for cmd in (
                command,
                build_fanout_command(environment, campaign),
                build_learning_refresh_command(),
            ):
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
        eligible_snapshots = int(fanout_report.get("eligibleSnapshots") or 0)
        learning_refresh: dict[str, object]
        if eligible_snapshots:
            refreshed = subprocess.run(
                build_learning_refresh_command(),
                check=False,
                capture_output=True,
                text=True,
            )
            if refreshed.returncode != 0:
                _forward_phase_output(refreshed)
                return refreshed.returncode
            try:
                learning_refresh = _json_report(refreshed, phase="learning refresh")
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            learning_refresh = {
                "status": "skipped",
                "reason": "no_eligible_snapshots",
            }
        reports.append(
            {
                "campaign": campaign,
                "performanceSync": performance_report,
                "learningFanout": fanout_report,
                "learningRefresh": learning_refresh,
            }
        )
    print(
        json.dumps(
            {
                "schema": "creator_os.hourly_learning_sync.v1",
                "campaigns": reports,
                "performanceSync": reports[0]["performanceSync"],
                "learningFanout": reports[0]["learningFanout"],
                "learningRefresh": reports[0]["learningRefresh"],
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
