from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_threadsdash_performance.py"
OPERATIONS_DOC_PATH = (
    REPO_ROOT / "docs" / "operations" / "threadsdash_performance_sync.md"
)


def load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_threadsdash_performance", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threadsdash_performance_sync_local_schedule_is_documented():
    operations_doc = OPERATIONS_DOC_PATH.read_text(encoding="utf-8")

    assert "Run performance sync locally, not from GitHub Actions" in operations_doc
    assert "python3 scripts/sync_threadsdash_performance.py" in operations_doc
    assert "com.creator-os.threadsdash-performance-sync" in operations_doc
    assert "StartInterval" in operations_doc
    assert "SUPABASE_URL" in operations_doc
    assert "SUPABASE_SERVICE_ROLE_KEY" in operations_doc
    assert "mode `0600`" in operations_doc


def test_sync_threadsdash_performance_requires_configured_env():
    module = load_sync_module()

    assert module.main(env={}) == 2


def test_sync_threadsdash_performance_defaults_to_ten_thousand_posts():
    module = load_sync_module()
    command = module.build_sync_command(
        {
            "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS": '["may"]',
            "THREADSDASH_USER_ID": "user_1",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "LEARNING_LOOP_CUTOVER": "2026-07-09T00:00:00+00:00",
        }
    )

    assert command[-2:] == ["--limit", "10000"]


def test_sync_threadsdash_performance_rejects_invalid_limits():
    module = load_sync_module()
    base = {
        "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS": '["may"]',
        "THREADSDASH_USER_ID": "user_1",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "LEARNING_LOOP_CUTOVER": "2026-07-09T00:00:00+00:00",
    }

    for value in ("0", "-1", "not-a-number"):
        with pytest.raises(ValueError, match="positive integer"):
            module.build_sync_command({**base, "CAMPAIGN_FACTORY_SYNC_LIMIT": value})


def test_sync_threadsdash_performance_calls_existing_cli(monkeypatch, capsys):
    module = load_sync_module()
    calls: list[list[str]] = []

    reports = iter(
        [
            {"schema": "campaign_factory.performance_sync.v1", "postsScanned": 2},
            {
                "schema": "creator_os.learning_fanout.v1",
                "fanout": {"reference": {"done": 1}},
            },
        ]
    )

    def fake_run(command, check, capture_output, text):
        calls.append(list(command))
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(next(reports)), stderr=""
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        env={
            "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS": '["may"]',
            "THREADSDASH_USER_ID": "user_1",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "CAMPAIGN_FACTORY_SYNC_LIMIT": "250",
            "LEARNING_LOOP_CUTOVER": "2026-07-09T00:00:00+00:00",
        }
    )

    assert result == 0
    combined = json.loads(capsys.readouterr().out)
    assert combined["schema"] == "creator_os.hourly_learning_sync.v1"
    assert combined["performanceSync"]["postsScanned"] == 2
    assert combined["learningFanout"]["fanout"]["reference"]["done"] == 1
    assert calls == [
        [
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
        ],
        [
            "uv",
            "run",
            "python",
            str(module.REPO_ROOT / "scripts" / "learning_fanout.py"),
            "--campaign-factory-db",
            str(module.DEFAULT_CAMPAIGN_FACTORY_DB),
            "--reel-manifest-db",
            str(module.DEFAULT_REEL_MANIFEST_DB),
            "--reference-factory-db",
            str(module.DEFAULT_REFERENCE_FACTORY_DB),
            "--campaign",
            "may",
        ],
    ]


def test_sync_threadsdash_performance_skips_bridge_when_sync_fails(monkeypatch):
    module = load_sync_module()
    calls: list[list[str]] = []

    def fake_run(command, check, capture_output, text):
        calls.append(list(command))
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        env={
            "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS": '["may"]',
            "THREADSDASH_USER_ID": "user_1",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "LEARNING_LOOP_CUTOVER": "2026-07-09T00:00:00+00:00",
        }
    )

    assert result == 1
    assert len(calls) == 1


def test_hourly_sync_never_invokes_standalone_reel_refresh():
    module = load_sync_module()
    command = module.build_fanout_command(
        {
            "CAMPAIGN_FACTORY_DB": "/tmp/campaign.sqlite",
            "REEL_FACTORY_MANIFEST_DB": "/tmp/reel/manifest.sqlite",
            "REFERENCE_FACTORY_DB": "/tmp/reference.sqlite",
        },
        "may",
    )

    joined = " ".join(command)
    assert "learning_fanout.py" in joined
    assert "metrics_store.py" not in joined
    assert "refresh-outcomes" not in joined
