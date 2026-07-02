from __future__ import annotations

import subprocess
import sys

from next_batch import _campaign_factory_command, campaign_factory_next_batch


def test_campaign_factory_next_batch_prefers_canonical_recommendations(monkeypatch):
    calls = []

    def fake_run(cmd, *, check, capture_output, text, timeout):
        calls.append(
            {
                "cmd": cmd,
                "check": check,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
            }
        )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                '{"schema": "campaign_factory.recommendations.next_batch.v1", '
                '"campaign": "may", "items": [{"recommendationId": "recitem_1"}]}'
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REEL_FACTORY_CAMPAIGN_FACTORY_TIMEOUT_SECONDS", "12")

    result = campaign_factory_next_batch("may", count=2)

    assert calls == [
        {
            "cmd": [
                sys.executable,
                "-m",
                "campaign_factory.cli",
                "recommend-next-batch",
                "--campaign",
                "may",
                "--count",
                "2",
            ],
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 12.0,
        }
    ]
    assert result == {
        "schema": "campaign_factory.recommendations.next_batch.v1",
        "campaign": "may",
        "items": [{"recommendationId": "recitem_1"}],
        "source": "campaign_factory",
        "fallbackAvailable": "reel_factory.local_next_batch",
    }


def test_campaign_factory_next_batch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY", "1")

    assert campaign_factory_next_batch("may", count=2) is None


def test_campaign_factory_next_batch_falls_back_on_cli_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["campaign-factory"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert campaign_factory_next_batch("may", count=2) is None


def test_campaign_factory_command_allows_cli_override(monkeypatch):
    monkeypatch.setenv("REEL_FACTORY_CAMPAIGN_FACTORY_CLI", "campaign-factory")

    assert _campaign_factory_command("may", count=2) == [
        "campaign-factory",
        "recommend-next-batch",
        "--campaign",
        "may",
        "--count",
        "2",
    ]
