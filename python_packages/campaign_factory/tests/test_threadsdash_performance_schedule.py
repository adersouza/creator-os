from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_threadsdash_performance.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "threadsdash-performance-sync.yml"


def load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_threadsdash_performance", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threadsdash_performance_sync_workflow_is_scheduled():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "cron: \"37 * * * *\"" in workflow
    assert "python3 scripts/sync_threadsdash_performance.py" in workflow
    assert "THREADSDASH_SUPABASE_URL" in workflow
    assert "THREADSDASH_SUPABASE_SERVICE_ROLE_KEY" in workflow


def test_sync_threadsdash_performance_requires_configured_env():
    module = load_sync_module()

    assert module.main(env={}) == 2


def test_sync_threadsdash_performance_calls_existing_cli(monkeypatch):
    module = load_sync_module()
    calls: list[list[str]] = []

    def fake_run(command, check):
        calls.append(list(command))
        assert check is False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(env={
        "CAMPAIGN_FACTORY_SYNC_CAMPAIGN": "may",
        "THREADSDASH_USER_ID": "user_1",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "CAMPAIGN_FACTORY_SYNC_LIMIT": "250",
    })

    assert result == 0
    assert calls == [[
        "uv",
        "run",
        "campaign-factory",
        "sync-performance",
        "--campaign",
        "may",
        "--user-id",
        "user_1",
        "--supabase-url",
        "https://example.supabase.co",
        "--supabase-service-role-key",
        "service-role",
        "--limit",
        "250",
    ]]
