from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from reference_factory.cli import build_parser, main
from reference_factory.db import connect
from reference_factory.reference_lifecycle import (
    pattern_lifecycle_snapshot,
    record_pattern_lifecycle_event,
    record_reference_lifecycle_event,
    reference_lifecycle_snapshot,
    require_reference_provider_rights,
)

SECRET = "reference-lifecycle-test-secret-" + ("x" * 32)
SOURCE_SHA = "a" * 64


def _rights_evidence(
    *,
    starts_at: str = "2026-07-15T12:00:00Z",
    expires_at: str = "2027-07-15T12:00:00Z",
    scopes: list[str] | None = None,
    providers: list[str] | None = None,
) -> dict:
    return {
        "agreementId": "agreement_1",
        "subject": "rights-holder:creator-1",
        "scope": scopes
        or [
            "pattern_learning",
            "reference_analysis",
            "reference_prompt_compilation",
        ],
        "providerSharing": {
            "allowed": True,
            "providers": providers or ["gemini", "xai"],
        },
        "commercialUse": True,
        "territories": ["US"],
        "validity": {"startsAt": starts_at, "expiresAt": expires_at},
    }


def test_lifecycle_cli_requires_structured_evidence() -> None:
    args = build_parser().parse_args(
        [
            "reference-lifecycle",
            "--reference-id",
            "ref_1",
            "--event",
            "rights_granted",
            "--operator",
            "operator:alice",
            "--reason",
            "signed authorization",
            "--evidence",
            json.dumps(_rights_evidence(expires_at="2027-07-15T12:00:00Z")),
            "--expires-at",
            "2027-07-15T12:00:00Z",
        ]
    )
    assert args.evidence["agreementId"] == "agreement_1"
    assert args.event == "rights_granted"


def test_direct_paid_reference_cli_points_to_governed_root_composition(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "--db",
                str(tmp_path / "reference.sqlite"),
                "analyze-reference-with-gemini-api",
                "--source",
                str(tmp_path),
            ]
        )
    assert "creator-os reference-paid --help" in capsys.readouterr().err


def test_signed_reference_rights_fail_closed_and_preserve_history(tmp_path: Path):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        assert reference_lifecycle_snapshot(conn, "ref_1")["blockers"] == [
            "rights_evidence_missing"
        ]

        granted = record_reference_lifecycle_event(
            conn,
            reference_id="ref_1",
            event_type="rights_granted",
            operator="operator:alice",
            reason="signed commercial reference authorization",
            evidence=_rights_evidence(expires_at="2026-08-15T12:00:00Z"),
            effective_at="2026-07-15T12:00:00Z",
            expires_at="2026-08-15T12:00:00Z",
            secret=SECRET,
        )
        assert granted["eligible"] is True
        assert granted["rightsStatus"] == "granted"
        assert granted["latestEvidenceType"] == "evidence"

        expired = reference_lifecycle_snapshot(
            conn,
            "ref_1",
            secret=SECRET,
            as_of="2026-08-16T12:00:00Z",
        )
        assert expired["eligible"] is False
        assert expired["rightsStatus"] == "expired"
        assert expired["blockers"] == ["rights_expired"]

        contradictory = record_reference_lifecycle_event(
            conn,
            reference_id="ref_1",
            event_type="contradiction_opened",
            operator="operator:alice",
            reason="conflicting ownership record",
            evidence={"ticketId": "rights_review_1"},
            evidence_type="inference",
            effective_at="2026-07-16T12:00:00Z",
            secret=SECRET,
        )
        assert contradictory["eligible"] is False
        assert "reference_contradictory" in contradictory["blockers"]

        resolved = record_reference_lifecycle_event(
            conn,
            reference_id="ref_1",
            event_type="contradiction_resolved",
            operator="operator:bob",
            reason="signed owner record reconciled",
            evidence={"ticketId": "rights_review_1", "resolution": "confirmed"},
            effective_at="2026-07-17T12:00:00Z",
            secret=SECRET,
        )
        assert resolved["eligible"] is True

        revoked = record_reference_lifecycle_event(
            conn,
            reference_id="ref_1",
            event_type="rights_revoked",
            operator="operator:bob",
            reason="creator revoked reference use",
            evidence={"revocationId": "revoke_1"},
            effective_at="2026-07-18T12:00:00Z",
            secret=SECRET,
        )
        assert revoked["eligible"] is False
        assert revoked["rightsStatus"] == "revoked"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM reference_lifecycle_events WHERE reference_id='ref_1'"
            ).fetchone()[0]
            == 4
        )
        event_id = conn.execute(
            """
            SELECT id FROM reference_lifecycle_events
            WHERE reference_id='ref_1' ORDER BY created_at LIMIT 1
            """
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE reference_lifecycle_events SET reason='changed' WHERE id=?",
                (event_id,),
            )
    finally:
        conn.close()


def test_rights_events_require_evidence_and_exact_source_sha(tmp_path: Path):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        with pytest.raises(ValueError, match="require evidence"):
            record_reference_lifecycle_event(
                conn,
                reference_id="ref_1",
                event_type="rights_granted",
                operator="operator:alice",
                reason="not sufficient",
                evidence={"note": "inferred"},
                evidence_type="inference",
                effective_at="2026-07-15T12:00:00Z",
                expires_at="2026-08-15T12:00:00Z",
                secret=SECRET,
            )
        conn.execute(
            "UPDATE source_files SET content_hash='not-a-sha' WHERE reference_id='ref_1'"
        )
        with pytest.raises(ValueError, match="exact source SHA-256"):
            record_reference_lifecycle_event(
                conn,
                reference_id="ref_1",
                event_type="rights_granted",
                operator="operator:alice",
                reason="bad subject",
                evidence={"agreementId": "agreement_1"},
                effective_at="2026-07-15T12:00:00Z",
                expires_at="2026-08-15T12:00:00Z",
                secret=SECRET,
            )
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (("agreementId", None), "evidence.agreementId"),
        (("subject", None), "evidence.subject"),
        (("scope", []), "evidence.scope"),
        (("providerSharing", None), "providerSharing.allowed"),
        (("commercialUse", False), "commercialUse"),
        (("territories", []), "evidence.territories"),
        (("validity", None), "evidence.validity"),
    ],
)
def test_rights_grant_rejects_semantically_incomplete_evidence(
    tmp_path: Path,
    mutation: tuple[str, object],
    error: str,
) -> None:
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        evidence = _rights_evidence()
        field, replacement = mutation
        if replacement is None:
            evidence.pop(field)
        else:
            evidence[field] = replacement
        with pytest.raises(ValueError, match=error):
            record_reference_lifecycle_event(
                conn,
                reference_id="ref_1",
                event_type="rights_granted",
                operator="operator:alice",
                reason="incomplete grant",
                evidence=evidence,
                effective_at="2026-07-15T12:00:00Z",
                expires_at="2027-07-15T12:00:00Z",
                secret=SECRET,
            )
    finally:
        conn.close()


def test_deletion_is_retained_and_cannot_be_reauthorized(tmp_path: Path):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        _grant(conn, "ref_1")
        deleted = record_reference_lifecycle_event(
            conn,
            reference_id="ref_1",
            event_type="reference_deleted",
            operator="operator:alice",
            reason="creator deletion request",
            evidence={"deletionRequestId": "delete_1", "retention": "audit_only"},
            effective_at="2026-07-16T12:00:00Z",
            secret=SECRET,
        )
        assert deleted["referenceStatus"] == "deleted"
        assert deleted["eligible"] is False
        assert "reference_deleted" in deleted["blockers"]
        with pytest.raises(ValueError, match="deleted reference"):
            record_reference_lifecycle_event(
                conn,
                reference_id="ref_1",
                event_type="rights_renewed",
                operator="operator:alice",
                reason="invalid renewal",
                evidence=_rights_evidence(
                    starts_at="2026-07-17T12:00:00Z",
                    expires_at="2027-07-17T12:00:00Z",
                ),
                effective_at="2026-07-17T12:00:00Z",
                expires_at="2027-07-17T12:00:00Z",
                secret=SECRET,
            )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM source_files WHERE reference_id='ref_1'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_provider_rights_bind_provider_operation_and_current_source_sha(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        _grant(conn, "ref_1")
        eligible = require_reference_provider_rights(
            conn,
            reference_id="ref_1",
            provider="xai",
            operation="reference_analysis",
            expected_source_sha256=SOURCE_SHA,
            secret=SECRET,
            as_of="2026-07-16T12:00:00Z",
        )
        assert eligible["eligible"] is True
        assert eligible["sourceSha256"] == SOURCE_SHA

        with pytest.raises(PermissionError, match="rights_provider_sharing_blocked"):
            require_reference_provider_rights(
                conn,
                reference_id="ref_1",
                provider="unlisted-provider",
                operation="reference_analysis",
                expected_source_sha256=SOURCE_SHA,
                secret=SECRET,
                as_of="2026-07-16T12:00:00Z",
            )
        with pytest.raises(PermissionError, match="rights_operation_scope_blocked"):
            require_reference_provider_rights(
                conn,
                reference_id="ref_1",
                provider="xai",
                operation="ungranted_operation",
                expected_source_sha256=SOURCE_SHA,
                secret=SECRET,
                as_of="2026-07-16T12:00:00Z",
            )
        conn.execute(
            "UPDATE source_files SET content_hash=? WHERE reference_id='ref_1'",
            ("b" * 64,),
        )
        conn.commit()
        with pytest.raises(PermissionError, match="rights_subject_sha256_mismatch"):
            require_reference_provider_rights(
                conn,
                reference_id="ref_1",
                provider="xai",
                operation="reference_analysis",
                expected_source_sha256="b" * 64,
                secret=SECRET,
                as_of="2026-07-16T12:00:00Z",
            )
    finally:
        conn.close()


def test_pattern_supersession_and_invalidation_are_signed_and_fail_closed(
    tmp_path: Path,
):
    conn = connect(tmp_path / "reference.sqlite")
    try:
        _insert_reference(conn, "ref_1")
        _insert_pattern(conn, "pattern_old", "ref_1", "v1")
        _insert_pattern(conn, "pattern_new", "ref_1", "v2")
        promoted = record_pattern_lifecycle_event(
            conn,
            pattern_id="pattern_old",
            event_type="promoted",
            operator="operator:alice",
            reason="approved reusable pattern",
            evidence={"reviewId": "review_1"},
            effective_at="2026-07-15T12:00:00Z",
            secret=SECRET,
        )
        assert promoted["eligible"] is True
        superseded = record_pattern_lifecycle_event(
            conn,
            pattern_id="pattern_old",
            event_type="superseded",
            superseded_by_pattern_id="pattern_new",
            operator="operator:alice",
            reason="new measured pattern version",
            evidence={"reviewId": "review_2"},
            effective_at="2026-07-16T12:00:00Z",
            secret=SECRET,
        )
        assert superseded["eligible"] is False
        assert superseded["status"] == "superseded"
        assert superseded["supersededByPatternId"] == "pattern_new"

        invalidated = record_pattern_lifecycle_event(
            conn,
            pattern_id="pattern_new",
            event_type="invalidated",
            operator="operator:bob",
            reason="rights-dependent promotion invalidated",
            evidence={"incidentId": "incident_1"},
            effective_at="2026-07-17T12:00:00Z",
            secret=SECRET,
        )
        assert invalidated["eligible"] is False
        assert invalidated["status"] == "invalidated"
        assert (
            pattern_lifecycle_snapshot(conn, "pattern_old", secret=SECRET)["status"]
            == "superseded"
        )
    finally:
        conn.close()


def _insert_reference(conn, reference_id: str) -> None:
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, file_name, extension, kind, size_bytes, mtime,
          path_hash, content_hash, created_at, updated_at
        ) VALUES (?, ?, ?, '.mp4', 'video', 100, '2026-07-15T12:00:00Z',
                  ?, ?, '2026-07-15T12:00:00Z', '2026-07-15T12:00:00Z')
        """,
        (
            reference_id,
            f"/portable/{reference_id}.mp4",
            f"{reference_id}.mp4",
            f"path_{reference_id}",
            SOURCE_SHA,
        ),
    )
    conn.commit()


def _insert_pattern(
    conn, pattern_id: str, reference_id: str, analyzer_version: str
) -> None:
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, reference_id, rank, provider, analyzer_version, quality_score,
          pattern_json, created_at, updated_at
        ) VALUES (?, ?, 1, 'heuristic', ?, 1.0, '{}',
                  '2026-07-15T12:00:00Z', '2026-07-15T12:00:00Z')
        """,
        (pattern_id, reference_id, analyzer_version),
    )
    conn.commit()


def _grant(conn, reference_id: str) -> None:
    record_reference_lifecycle_event(
        conn,
        reference_id=reference_id,
        event_type="rights_granted",
        operator="operator:alice",
        reason="signed commercial reference authorization",
        evidence=_rights_evidence(),
        effective_at="2026-07-15T12:00:00Z",
        expires_at="2027-07-15T12:00:00Z",
        secret=SECRET,
    )
