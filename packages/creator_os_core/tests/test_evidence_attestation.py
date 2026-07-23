from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    canonical_json,
    sign_evidence_attestation,
    verify_evidence_attestation,
)

SECRET = "evidence-test-secret-that-is-longer-than-thirty-two-bytes"
ISSUED_AT = "2026-07-22T12:00:00Z"
NOW = datetime(2026, 7, 22, 13, 0, tzinfo=UTC)


def test_attestation_binds_exact_payload_and_issuer() -> None:
    payload = {"subjectSha256": "a" * 64, "passed": True}
    attestation = sign_evidence_attestation(
        payload,
        issuer="contentforge.motion_specific_qc",
        issued_at=ISSUED_AT,
        secret=SECRET,
    )

    assert (
        verify_evidence_attestation(
            attestation,
            payload,
            secret=SECRET,
            expected_issuer="contentforge.motion_specific_qc",
            now=NOW,
        )
        == attestation
    )


@pytest.mark.parametrize(
    ("payload", "issuer", "secret", "match"),
    [
        (
            {"subjectSha256": "b" * 64, "passed": True},
            "contentforge.motion_specific_qc",
            SECRET,
            "payload_mismatch",
        ),
        (
            {"subjectSha256": "a" * 64, "passed": True},
            "contentforge.other",
            SECRET,
            "identity_mismatch",
        ),
        (
            {"subjectSha256": "a" * 64, "passed": True},
            "contentforge.motion_specific_qc",
            "different-secret-that-is-also-more-than-thirty-two-bytes",
            "key_mismatch",
        ),
    ],
)
def test_attestation_rejects_substitution(
    payload: dict[str, object], issuer: str, secret: str, match: str
) -> None:
    original = {"subjectSha256": "a" * 64, "passed": True}
    attestation = sign_evidence_attestation(
        original,
        issuer="contentforge.motion_specific_qc",
        issued_at=ISSUED_AT,
        secret=SECRET,
    )
    with pytest.raises(EvidenceAttestationError, match=match):
        verify_evidence_attestation(
            attestation,
            payload,
            secret=secret,
            expected_issuer=issuer,
            now=NOW,
        )


def test_attestation_rejects_future_issuance() -> None:
    payload = {"subjectSha256": "a" * 64}
    attestation = sign_evidence_attestation(
        payload,
        issuer="campaign_factory.creative_approval",
        issued_at="2026-07-23T00:00:00Z",
        secret=SECRET,
    )
    with pytest.raises(EvidenceAttestationError, match="issued_at_invalid"):
        verify_evidence_attestation(
            attestation,
            payload,
            secret=SECRET,
            expected_issuer="campaign_factory.creative_approval",
            now=NOW,
        )


def test_canonical_json_matches_javascript_for_integral_floats() -> None:
    completed = subprocess.run(
        [
            "node",
            "-e",
            "process.stdout.write(JSON.stringify({nested:[1.0,0.5,-0.0]}))",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    assert canonical_json({"nested": [1.0, 0.5, -0.0]}).decode() == completed.stdout
