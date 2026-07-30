from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from campaign_factory import front_generation_stage
from campaign_factory.cost_tracker import ensure_cost_table
from campaign_factory.production_higgsfield_authorization import (
    recovered_higgsfield_cost_binding,
)
from campaign_factory.provider_spend import (
    AUTHORIZATION_TABLE,
    ProviderOverspendError,
    consume_provider_spend_authorization,
    issue_provider_spend_authorization,
    record_provider_execution,
    validate_provider_spend_batch_capacity,
)
from campaign_test_support import authorize_campaign_governance, make_factory
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


def _scope(
    tmp_path: Path,
    *,
    campaign: str = "campaign_1",
    creator: str | None = None,
) -> dict:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    args = [
        "image",
        "--prompt-json",
        str(prompt),
        "--stem",
        "clip_1",
        "--campaign",
        campaign,
        "--cohort-id",
        "cohort_1",
        "--soul-id",
        "soul_1",
    ]
    if creator:
        args += ["--creator", creator]
    return build_generate_assets_spend_scope(args, root=tmp_path)


def test_combined_create_alias_is_not_an_authorizable_runtime_mode(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="mode is not a paid generation mode: create"):
        build_generate_assets_spend_scope(
            ["create", "--stem", "clip_1", "--soul-id", "soul_1"],
            root=tmp_path,
        )


def test_canonical_image_scope_represents_exactly_one_provider_call(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)

    assert scope["mode"] == "image"
    assert scope["providerCallCount"] == 1
    assert scope["providerModels"] == ["text2image_soul_v2"]


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


def test_spend_helpers_do_not_commit_caller_owned_transaction(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    authorization = issue_provider_spend_authorization(
        conn,
        scope=_scope(tmp_path),
        campaign_id="campaign_db_id",
        max_credits=10,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=Balance(),
        now=now,
    )

    conn.execute("BEGIN IMMEDIATE")
    consume_provider_spend_authorization(
        conn, authorization["authorizationId"], now=now
    )
    assert conn.in_transaction is True
    conn.rollback()
    assert conn.execute(
        f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE authorization_id = ?",
        (authorization["authorizationId"],),
    ).fetchone() == ("authorized",)

    consume_provider_spend_authorization(
        conn, authorization["authorizationId"], now=now
    )
    ensure_cost_table(conn)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    event_ids = record_provider_execution(
        conn,
        authorization=authorization,
        execution={
            "events": [
                {
                    "provider": "higgsfield",
                    "operation": "image_create",
                    "model": "text2image_soul_v2",
                    "jobId": "job_transaction",
                    "actualCredits": 4,
                }
            ]
        },
    )
    assert conn.in_transaction is True
    conn.rollback()
    assert (
        conn.execute(
            "SELECT 1 FROM ai_cost_events WHERE id = ?", (event_ids[0],)
        ).fetchone()
        is None
    )


def test_provider_overspend_is_recorded_then_blocks_progression(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    authorization = issue_provider_spend_authorization(
        conn,
        scope=_scope(tmp_path),
        campaign_id="campaign_db_id",
        max_credits=10,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=Balance(),
    )
    consume_provider_spend_authorization(conn, authorization["authorizationId"])

    with pytest.raises(ProviderOverspendError) as raised:
        record_provider_execution(
            conn,
            authorization=authorization,
            execution={
                "events": [
                    {
                        "provider": "higgsfield",
                        "operation": "image_create",
                        "model": "text2image_soul_v2",
                        "jobId": "job_overspend",
                        "actualCredits": 7,
                    }
                ]
            },
        )

    assert raised.value.authorized_maximum == 5
    assert raised.value.actual == 7
    row = conn.execute("SELECT amount, metadata_json FROM ai_cost_events").fetchone()
    assert row[0] == 7
    assert json.loads(row[1])["overspend"] is True


def test_unknown_actual_cost_remains_unknown(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    authorization = issue_provider_spend_authorization(
        conn,
        scope=_scope(tmp_path),
        campaign_id="campaign_db_id",
        max_credits=10,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=Balance(),
    )
    consume_provider_spend_authorization(conn, authorization["authorizationId"])

    event_ids = record_provider_execution(
        conn,
        authorization=authorization,
        execution={
            "events": [
                {
                    "provider": "higgsfield",
                    "operation": "image_create",
                    "model": "text2image_soul_v2",
                    "jobId": "job_unknown",
                    "actualCredits": None,
                }
            ]
        },
    )

    assert len(event_ids) == 1
    assert conn.execute("SELECT amount, unit FROM ai_cost_events").fetchone() == (
        None,
        None,
    )


@pytest.mark.parametrize("actual", [4.0, None])
def test_completed_recovery_accepts_actual_below_quote_or_unknown(
    tmp_path: Path,
    actual: float | None,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    scope = _scope(tmp_path)
    authorization = issue_provider_spend_authorization(
        conn,
        scope=scope,
        campaign_id="campaign_db_id",
        max_credits=10,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=Balance(),
    )
    consume_provider_spend_authorization(conn, authorization["authorizationId"])
    event_ids = record_provider_execution(
        conn,
        authorization=authorization,
        execution={
            "events": [
                {
                    "provider": "higgsfield",
                    "operation": "video_generation",
                    "model": "kling3_0",
                    "jobId": "generation-1",
                    "actualCredits": actual,
                }
            ]
        },
    )

    binding = recovered_higgsfield_cost_binding(
        SimpleNamespace(conn=conn),
        job={"quotedProviderCredits": 5.0},
        receipt={
            "generationId": "generation-1",
            "creditsConsumed": actual,
        },
        spend_scope=scope,
    )

    assert binding["authorizationId"] == authorization["authorizationId"]
    assert binding["costEventIds"] == event_ids


def test_campaign_fails_before_quote_when_secret_is_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    quote = Quote()
    with pytest.raises(PermissionError, match="at least 32 bytes"):
        issue_provider_spend_authorization(
            conn,
            scope=_scope(tmp_path, campaign="may", creator="stacey"),
            campaign_id="campaign_1",
            max_credits=10,
            secret="short",
            quote_provider=quote,
            balance_provider=Balance(),
        )
    assert quote.calls == 0


def test_governed_authorization_is_revalidated_before_provider_effect(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(
            cf,
            tmp_path,
            provider="higgsfield",
            soul_id="soul_1",
        )
        authorization = issue_provider_spend_authorization(
            cf.conn,
            scope=_scope(tmp_path, campaign="may", creator="stacey"),
            campaign_id=authorized["campaign"]["id"],
            max_credits=10,
            secret=SECRET,
            quote_provider=Quote(),
            balance_provider=Balance(),
        )
        cf.domains.creator_governance.transition_creator(
            "stacey",
            new_status="suspended",
            actor="test",
            reason="fixture suspension",
        )

        with pytest.raises(PermissionError, match="creator_inactive"):
            consume_provider_spend_authorization(
                cf.conn, authorization["authorizationId"]
            )
    finally:
        cf.close()


def test_soul_version_change_invalidates_stale_provider_authorization(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(
            cf,
            tmp_path,
            provider="higgsfield",
            soul_id="soul_1",
        )
        authorization = issue_provider_spend_authorization(
            cf.conn,
            scope=_scope(tmp_path, campaign="may", creator="stacey"),
            campaign_id=authorized["campaign"]["id"],
            max_credits=10,
            secret=SECRET,
            quote_provider=Quote(),
            balance_provider=Balance(),
        )
        source = cf.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?",
            (authorized["identitySourceId"],),
        ).fetchone()
        profile = {
            "schema": "creator_os.creator_identity_profile.v1",
            "profileId": "stacey_higgsfield_soul_2",
            "creatorKey": "stacey",
            "displayName": "Stacey",
            "modelProfile": "higgsfield_soul_v2",
            "identityReferences": [
                {
                    "namespace": "higgsfield.identity",
                    "externalId": "soul_2",
                    "fingerprint": "b" * 64,
                }
            ],
            "provenance": {
                "producer": "operator",
                "producedAt": "2026-07-30T12:00:00Z",
                "sourceReferences": [
                    {
                        "recordId": source["id"],
                        "fingerprint": source["content_hash"],
                    }
                ],
            },
        }
        manifest = tmp_path / "stacey_higgsfield_identity_v2.json"
        manifest.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
        cf.domains.creator_governance.enroll_identity_profile(
            "stacey",
            provider="higgsfield",
            provider_identity_id="soul_2",
            profile=profile,
            canonical_source_asset_id=source["id"],
            identity_manifest_path=manifest,
            identity_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            operator="test",
        )

        with pytest.raises(
            PermissionError, match="provider_authorization_governance_stale"
        ):
            consume_provider_spend_authorization(
                cf.conn, authorization["authorizationId"]
            )
    finally:
        cf.close()


def test_active_reservations_reduce_provider_balance_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "1")
    conn = sqlite3.connect(":memory:")
    first = _scope(tmp_path)
    second = {**first, "requestFingerprint": "b" * 64}

    issue_provider_spend_authorization(
        conn,
        scope=first,
        campaign_id="campaign-1",
        max_credits=5,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=SimpleNamespace(balance=lambda: 10.0),
    )
    with pytest.raises(
        PermissionError,
        match="provider_balance_capacity_already_reserved",
    ):
        issue_provider_spend_authorization(
            conn,
            scope=second,
            campaign_id="campaign-1",
            max_credits=5,
            secret=SECRET,
            quote_provider=Quote(),
            balance_provider=SimpleNamespace(balance=lambda: 10.0),
        )


def test_expired_reservations_release_provider_balance_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "1")
    conn = sqlite3.connect(":memory:")
    first = _scope(tmp_path)
    second = {**first, "requestFingerprint": "b" * 64}
    issue_provider_spend_authorization(
        conn,
        scope=first,
        campaign_id="campaign-1",
        max_credits=5,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=SimpleNamespace(balance=lambda: 10.0),
    )
    conn.execute(
        "UPDATE provider_spend_authorizations SET expires_at = ?",
        ("2020-01-01T00:00:00Z",),
    )
    conn.commit()

    authorization = issue_provider_spend_authorization(
        conn,
        scope=second,
        campaign_id="campaign-1",
        max_credits=5,
        secret=SECRET,
        quote_provider=Quote(),
        balance_provider=SimpleNamespace(balance=lambda: 10.0),
    )

    assert authorization["scope"]["requestFingerprint"] == "b" * 64


def test_concurrent_authorizations_cannot_overreserve_provider_balance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "1")
    database = tmp_path / "provider-spend.sqlite"
    bootstrap = sqlite3.connect(database)
    first = _scope(tmp_path)
    bootstrap.close()
    barrier = threading.Barrier(2)

    def authorize(fingerprint: str) -> str:
        conn = sqlite3.connect(database, timeout=10)
        try:
            barrier.wait()
            issue_provider_spend_authorization(
                conn,
                scope={**first, "requestFingerprint": fingerprint},
                campaign_id="campaign-1",
                max_credits=5,
                secret=SECRET,
                quote_provider=Quote(),
                balance_provider=SimpleNamespace(balance=lambda: 10.0),
            )
            return "authorized"
        except PermissionError:
            return "blocked"
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(authorize, ("a" * 64, "b" * 64)))

    assert sorted(outcomes) == ["authorized", "blocked"]
    check = sqlite3.connect(database)
    assert (
        check.execute(
            "SELECT COUNT(*) FROM provider_spend_authorizations "
            "WHERE status = 'authorized'"
        ).fetchone()[0]
        == 1
    )
    check.close()


def test_batch_policy_failure_issues_zero_authorizations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_CREDITS", "9")
    conn = sqlite3.connect(":memory:")
    scope = _scope(tmp_path)

    with pytest.raises(PermissionError, match="projected_daily_credits_exceeded"):
        validate_provider_spend_batch_capacity(
            conn,
            [
                (scope, 5.0),
                ({**scope, "requestFingerprint": "b" * 64}, 5.0),
            ],
        )

    assert (
        conn.execute("SELECT COUNT(*) FROM provider_spend_authorizations").fetchone()[0]
        == 0
    )


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
