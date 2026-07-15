from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from campaign_factory import front_generation_stage
from campaign_factory.provider_spend import (
    AUTHORIZATION_TABLE,
    consume_provider_spend_authorization,
    issue_provider_spend_authorization,
    record_provider_execution,
)
from creator_os_core.provider_spend import build_generate_assets_spend_scope

SECRET = "test-only-spend-authorization-secret-32-bytes"


class Quote:
    def __init__(self) -> None:
        self.calls = 0

    def quote(self, scope):
        self.calls += 1
        return {
            "provider": "higgsfield",
            "amount": 5,
            "unit": "higgsfield_credits",
            "items": [{"model": scope["providerModels"][0]}],
        }


class Balance:
    def balance(self):
        return 1000.0


@pytest.fixture(autouse=True)
def _budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_CREDITS", "100")
    monkeypatch.setenv("HIGGSFIELD_MONTHLY_BUDGET_CREDITS", "1000")
    monkeypatch.setenv("HIGGSFIELD_COHORT_MAX_CREDITS", "100")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "10")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "1")
    monkeypatch.setenv("HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS", "10")


def _scope(tmp_path: Path) -> dict:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    return build_generate_assets_spend_scope(
        [
            "image",
            "--prompt-json",
            str(prompt),
            "--stem",
            "clip_1",
            "--campaign",
            "campaign_1",
            "--cohort-id",
            "cohort_1",
            "--soul-id",
            "soul_1",
        ],
        root=tmp_path,
    )


def test_campaign_issues_consumes_and_records_authoritative_cost(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    quote = Quote()
    authorization = issue_provider_spend_authorization(
        conn,
        scope=_scope(tmp_path),
        campaign_id="campaign_db_id",
        max_credits=10,
        secret=SECRET,
        quote_provider=quote,
        balance_provider=Balance(),
        now=now,
    )
    assert quote.calls == 1
    consume_provider_spend_authorization(
        conn, authorization["authorizationId"], now=now
    )
    with pytest.raises(PermissionError, match="consumed"):
        consume_provider_spend_authorization(
            conn, authorization["authorizationId"], now=now
        )
    event_ids = record_provider_execution(
        conn,
        authorization=authorization,
        execution={
            "events": [
                {
                    "provider": "higgsfield",
                    "operation": "image_create",
                    "model": "text2image_soul_v2",
                    "jobId": "job_1",
                    "actualCredits": 4,
                }
            ]
        },
    )
    assert len(event_ids) == 1
    row = conn.execute(
        "SELECT campaign_id, reservation_id, amount, unit FROM ai_cost_events"
    ).fetchone()
    assert row == (
        "campaign_db_id",
        authorization["reservationId"],
        4.0,
        "higgsfield_credits",
    )
    assert (
        conn.execute(
            f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE authorization_id = ?",
            (authorization["authorizationId"],),
        ).fetchone()[0]
        == "consumed"
    )


def test_campaign_fails_before_quote_when_secret_is_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    quote = Quote()
    with pytest.raises(PermissionError, match="at least 32 bytes"):
        issue_provider_spend_authorization(
            conn,
            scope=_scope(tmp_path),
            campaign_id="campaign_1",
            max_credits=10,
            secret="short",
            quote_provider=quote,
            balance_provider=Balance(),
        )
    assert quote.calls == 0


def test_campaign_wrapper_authorizes_before_fake_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    scope = build_generate_assets_spend_scope(
        [
            "image",
            "--prompt-json",
            str(prompt),
            "--stem",
            "clip_1",
            "--campaign",
            "campaign_1",
            "--cohort-id",
            "campaign_1",
            "--soul-id",
            "soul_1",
            "--max-credits",
            "10",
        ],
        root=tmp_path,
    )
    authorization = {
        "authorizationId": "spauth_1",
        "reservationId": "spres_1",
        "scope": scope,
        "providerQuote": {
            "provider": "higgsfield",
            "amount": 5,
            "unit": "higgsfield_credits",
        },
    }
    issue = Mock(return_value=authorization)
    consume = Mock()
    record = Mock(return_value=["cost_1"])
    seen_authorization_path: Path | None = None

    def fake_subprocess(cmd, **_kwargs):
        nonlocal seen_authorization_path
        index = cmd.index("--spend-authorization-file")
        seen_authorization_path = Path(cmd[index + 1])
        assert seen_authorization_path.is_file()
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "lineage": {
                        "generation": {
                            "providerExecution": {"events": [{"jobId": "job_1"}]}
                        }
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("CREATOR_OS_SPEND_AUTH_SECRET", SECRET)
    monkeypatch.setattr(
        front_generation_stage, "issue_provider_spend_authorization", issue
    )
    monkeypatch.setattr(
        front_generation_stage, "consume_provider_spend_authorization", consume
    )
    monkeypatch.setattr(front_generation_stage, "record_provider_execution", record)
    monkeypatch.setattr(front_generation_stage.subprocess, "run", fake_subprocess)
    factory = SimpleNamespace(
        conn=sqlite3.connect(":memory:"),
        settings=SimpleNamespace(reel_factory_root=tmp_path),
        domains=SimpleNamespace(
            campaign_by_slug=lambda _slug: {"id": "campaign_db_id"}
        ),
    )

    result = front_generation_stage._invoke_generate_assets(
        factory,
        [
            "image",
            "--prompt-json",
            str(prompt),
            "--stem",
            "clip_1",
            "--campaign",
            "campaign_1",
            "--cohort-id",
            "campaign_1",
            "--soul-id",
            "soul_1",
            "--max-credits",
            "10",
        ],
    )

    assert result["campaignSpendReceipt"]["costEventIds"] == ["cost_1"]
    issue.assert_called_once()
    consume.assert_called_once_with(factory.conn, "spauth_1")
    record.assert_called_once()
    assert seen_authorization_path is not None
    assert not seen_authorization_path.exists()
