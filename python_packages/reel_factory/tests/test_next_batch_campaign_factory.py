from __future__ import annotations

import subprocess
import sys

from reel_factory.next_batch import (
    CAMPAIGN_FACTORY_REQUEST_ENV,
    _campaign_factory_command,
    campaign_factory_next_batch,
)
from reel_factory.next_batch import select_next_batch as packaged_select_next_batch


def test_next_batch_packaged_module_is_importable():
    assert callable(packaged_select_next_batch)


def test_campaign_factory_next_batch_prefers_canonical_recommendations(monkeypatch):
    calls = []

    def fake_run(cmd, *, check, capture_output, env, text, timeout):
        calls.append(
            {
                "cmd": cmd,
                "check": check,
                "capture_output": capture_output,
                "request": env[CAMPAIGN_FACTORY_REQUEST_ENV],
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
                "campaign_factory.recommendation_bridge",
            ],
            "check": True,
            "capture_output": True,
            "request": '{"campaign":"may","count":2}',
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


def test_campaign_factory_command_uses_fixed_module_entrypoint():
    assert _campaign_factory_command() == [
        sys.executable,
        "-m",
        "campaign_factory.recommendation_bridge",
    ]
