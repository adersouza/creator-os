from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
from campaign_factory import app as app_module
from campaign_factory import operator_authority as authority_module
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.config import Settings
from campaign_factory.db import connect, init_db
from campaign_factory.operator_authority import (
    DESTRUCTIVE,
    PAID,
    READ,
    authorize_cli_operation,
    build_api_authority_registry,
    build_cli_authority_registry,
    claim_cli_authority_event,
    classify_cli_operation,
    complete_cli_authority_event,
)
from campaign_factory.operator_authority_http import (
    MAX_REPLAY_BODY_BYTES,
    _build_authority_outcome,
    _response_from_authority_outcome,
)
from fastapi.responses import Response
from fastapi.testclient import TestClient


def test_cli_preview_is_read_only_and_apply_uses_key_identity(monkeypatch) -> None:
    preview = Namespace(cmd="orchestrate-daily", apply=False, execute=False)
    assert classify_cli_operation(preview) == (READ, True)

    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "x" * 48)
    apply = Namespace(cmd="orchestrate-daily", apply=True, execute=True)
    decision = authorize_cli_operation(apply)
    assert decision.effect_class == PAID
    assert decision.role == "operator"
    assert "x" * 8 not in decision.actor_fingerprint
    assert decision.receipt_required is True
    assert (
        authorize_cli_operation(
            Namespace(
                cmd="create",
                apply=False,
                execute=False,
                creator_image=Path("/tmp/reference.jpg"),
            )
        ).preview
        is True
    )


def test_unknown_and_known_legacy_writers_fail_closed_as_mutations() -> None:
    for command in ("assign-account", "model-account-profile", "distribution-plan"):
        effect, preview = classify_cli_operation(Namespace(cmd=command))
        assert effect == "local_mutation"
        assert preview is False


def test_known_report_commands_are_read_only_without_signing_material(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CREATOR_OS_EVIDENCE_AUTH_SECRET")
    monkeypatch.setenv("HOME", str(tmp_path))
    for command in (
        "caption-quality-repair-plan",
        "daily-plan",
        "multi-surface-inventory-audit",
        "parent-factory-post-gate-fresh-batch-proof",
        "recommend-audio",
    ):
        decision = authorize_cli_operation(Namespace(cmd=command))
        assert decision.effect_class == READ
        assert decision.preview is True

    inventory = build_cli_parser().parse_args(
        ["asset", "inventory", "--campaign", "stacey_learning_cohort_v1"]
    )
    decision = authorize_cli_operation(inventory)
    assert decision.effect_class == READ
    assert decision.preview is True


def test_mutating_command_without_signing_material_fails_closed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CREATOR_OS_EVIDENCE_AUTH_SECRET")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="evidence_attestation_key_file_missing"):
        authorize_cli_operation(
            Namespace(cmd="capture-publishability-rejection-evidence")
        )


def test_insecure_loopback_cannot_mutate_but_token_operator_can(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=tmp_path / "reel",
            reference_reels_root=tmp_path / "reference",
        ),
    )
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    insecure = TestClient(app_module.app, client=("127.0.0.1", 50000))
    assert insecure.post("/api/model-account-profile", json={}).status_code == 403

    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "authority-test-token")
    operator = TestClient(app_module.app, client=("127.0.0.1", 50000))
    response = operator.post(
        "/api/model-account-profile",
        json={},
        headers={
            "Authorization": "Bearer authority-test-token",
            "Idempotency-Key": "authority-test-request",
        },
    )
    assert response.status_code != 403
    replay = operator.post(
        "/api/model-account-profile",
        json={},
        headers={
            "Authorization": "Bearer authority-test-token",
            "Idempotency-Key": "authority-test-request",
        },
    )
    assert replay.status_code == response.status_code
    assert replay.json() == response.json()
    conflict = operator.post(
        "/api/model-account-profile",
        json={"model": "different"},
        headers={
            "Authorization": "Bearer authority-test-token",
            "Idempotency-Key": "authority-test-request",
        },
    )
    assert conflict.status_code == 409


def test_failed_retryable_claim_can_retry_and_success_replays(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "x" * 48)
    decision = authorize_cli_operation(
        Namespace(
            cmd="orchestrate-daily",
            apply=True,
            execute=True,
            idempotency_key="retryable-authority",
        )
    )
    conn = connect(tmp_path / "authority.sqlite")
    init_db(conn)
    try:
        assert claim_cli_authority_event(conn, decision)["status"] == "claimed"
        complete_cli_authority_event(
            conn,
            decision,
            succeeded=False,
            retryable=True,
            error="transient",
        )
        retry = claim_cli_authority_event(conn, decision)
        assert retry["status"] == "claimed"
        assert retry["attemptCount"] == 2
        complete_cli_authority_event(
            conn,
            decision,
            succeeded=True,
            exit_code=7,
        )
        replay = claim_cli_authority_event(conn, decision)
        assert replay["status"] == "replay"
        assert replay["outcome"] == {"exitCode": 7}
        row = conn.execute(
            """
            SELECT execution_state, attempt_count, retryable
            FROM operator_authority_events
            WHERE operation_id = ? AND idempotency_key = ?
            """,
            (decision.operation_id, decision.idempotency_key),
        ).fetchone()
        assert tuple(row) == ("succeeded", 2, 0)
    finally:
        conn.close()


def test_stale_claim_requires_reconciliation_without_retrying(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "x" * 48)
    monkeypatch.setattr(
        authority_module,
        "utc_now",
        lambda: "2026-07-30T00:00:00Z",
    )
    decision = authorize_cli_operation(
        Namespace(
            cmd="orchestrate-daily",
            apply=True,
            execute=True,
            idempotency_key="stale-authority",
        )
    )
    conn = connect(tmp_path / "stale-authority.sqlite")
    init_db(conn)
    try:
        assert claim_cli_authority_event(conn, decision)["status"] == "claimed"
        monkeypatch.setattr(
            authority_module,
            "utc_now",
            lambda: "2026-07-30T00:31:00Z",
        )

        stale = claim_cli_authority_event(conn, decision)

        assert stale["status"] == "reconciliation_required"
        assert stale["executionState"] == "claimed"
        assert stale["attemptCount"] == 1
        row = conn.execute(
            """
            SELECT execution_state, attempt_count, claim_updated_at,
                   completed_at, outcome_json, error_json
            FROM operator_authority_events
            WHERE operation_id = ? AND idempotency_key = ?
            """,
            (decision.operation_id, decision.idempotency_key),
        ).fetchone()
        assert tuple(row) == (
            "claimed",
            1,
            "2026-07-30T00:00:00Z",
            None,
            None,
            None,
        )
    finally:
        conn.close()


def test_http_authority_replay_persists_only_allowlisted_headers() -> None:
    body = b'{"ok":true}'
    response = Response(
        body,
        status_code=201,
        media_type="application/json",
        headers={
            "Set-Cookie": "session=never-persist",
            "Authorization": "Bearer never-persist",
            "Content-Language": "en",
        },
    )

    outcome = _build_authority_outcome(response, body)
    serialized = json.dumps(outcome, sort_keys=True)

    assert outcome["replayable"] is True
    assert "set-cookie" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    assert "never-persist" not in serialized
    replay = _response_from_authority_outcome(outcome)
    assert replay.status_code == 201
    assert replay.body == body
    assert replay.headers["content-type"].startswith("application/json")
    assert replay.headers["content-language"] == "en"
    assert replay.headers.get("set-cookie") is None
    assert replay.headers.get("authorization") is None


@pytest.mark.parametrize(
    "payload",
    [
        {"accessToken": "top-secret-token"},
        {
            "downloadUrl": (
                "https://example.invalid/file?X-Amz-Signature=top-secret-signature"
            )
        },
        {"detail": "Bearer top-secret-credential"},
    ],
)
def test_http_authority_sensitive_bodies_require_reconciliation(
    payload: dict[str, str],
) -> None:
    body = json.dumps(payload).encode()
    response = Response(body, media_type="application/json")

    outcome = _build_authority_outcome(response, body)

    assert outcome["replayable"] is False
    assert outcome["reconciliationRequired"] is True
    assert outcome["nonReplayableReason"] == (
        "response_body_contains_sensitive_material"
    )
    assert "bodyBase64" not in outcome
    serialized = json.dumps(outcome, sort_keys=True)
    assert "top-secret" not in serialized
    replay = _response_from_authority_outcome(outcome)
    assert replay.status_code == 409
    assert json.loads(replay.body)["status"] == ("operation_reconciliation_required")


def test_http_authority_oversize_body_is_not_truncated_or_replayed() -> None:
    body = json.dumps({"data": "x" * MAX_REPLAY_BODY_BYTES}).encode()
    assert len(body) > MAX_REPLAY_BODY_BYTES
    response = Response(body, media_type="application/json")

    outcome = _build_authority_outcome(response, body)

    assert outcome["replayable"] is False
    assert outcome["nonReplayableReason"] == "response_body_exceeds_replay_limit"
    assert outcome["bodyBytes"] == len(body)
    assert "bodyBase64" not in outcome
    replay = _response_from_authority_outcome(outcome)
    assert replay.status_code == 409


def test_destructive_cancel_never_downgrades_to_preview(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "x" * 48)
    args = build_cli_parser().parse_args(
        [
            "--idempotency-key",
            "cancel-reservation",
            "asset",
            "reservations",
            "cancel",
            "--reservation",
            "reservation-1",
        ]
    )
    assert classify_cli_operation(args) == (DESTRUCTIVE, False)
    decision = authorize_cli_operation(args)
    assert decision.effect_class == DESTRUCTIVE
    assert decision.preview is False
    assert decision.role == "operator"
    assert decision.receipt_required is True
    conn = connect(tmp_path / "destructive-authority.sqlite")
    init_db(conn)
    try:
        assert claim_cli_authority_event(conn, decision)["status"] == "claimed"
        row = conn.execute(
            """
            SELECT effect_class, role, preview, apply_requested, execution_state
            FROM operator_authority_events
            WHERE operation_id = ? AND idempotency_key = ?
            """,
            (decision.operation_id, decision.idempotency_key),
        ).fetchone()
        assert tuple(row) == (DESTRUCTIVE, "operator", 0, 0, "claimed")
    finally:
        conn.close()


def test_runtime_default_idempotency_key_is_per_invocation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "x" * 48)
    first = authorize_cli_operation(Namespace(cmd="serve"))
    second = authorize_cli_operation(Namespace(cmd="serve"))
    assert first.idempotency_key != second.idempotency_key


def test_authority_registries_cover_every_cli_leaf_and_api_route() -> None:
    cli = build_cli_authority_registry(build_cli_parser())
    api = build_api_authority_registry(app_module.app)
    assert len(cli) > 100
    assert len(api) >= 70
    assert len({item["operationId"] for item in cli}) == len(cli)
    assert len({item["operationId"] for item in api}) == len(api)
    assert all(item["effectClass"] for item in [*cli, *api])
    assert (
        next(
            item
            for item in api
            if item["operationId"] == "api:POST:/api/export-threadsdash"
        )["effectClass"]
        == "external_handoff"
    )
