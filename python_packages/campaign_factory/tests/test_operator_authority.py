from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest
from campaign_factory import operator_authority as authority_module
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.db import connect, init_db
from campaign_factory.operator_authority import (
    DESTRUCTIVE,
    PAID,
    READ,
    authorize_cli_operation,
    build_cli_authority_registry,
    claim_cli_authority_event,
    classify_cli_operation,
    complete_cli_authority_event,
)


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
    first = authorize_cli_operation(Namespace(cmd="runtime-promotion"))
    second = authorize_cli_operation(Namespace(cmd="runtime-promotion"))
    assert first.idempotency_key != second.idempotency_key


def test_authority_registry_covers_every_cli_leaf() -> None:
    cli = build_cli_authority_registry(build_cli_parser())
    assert len(cli) > 100
    assert len({item["operationId"] for item in cli}) == len(cli)
    assert all(item["effectClass"] for item in cli)
