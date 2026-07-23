from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    canonical_json,
    evidence_key_id,
    evidence_secret_path,
    initialize_evidence_key,
    load_evidence_secret,
    main,
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


def _key_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    path = tmp_path / "credentials" / "evidence-auth-key.json"
    return {"CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE": str(path)}, path


def test_environment_secret_has_precedence_over_a_missing_file(tmp_path: Path) -> None:
    environment, _ = _key_environment(tmp_path)
    environment["CREATOR_OS_EVIDENCE_AUTH_SECRET"] = SECRET

    assert load_evidence_secret(environment) == SECRET
    assert evidence_key_id(SECRET, environ=environment).startswith("local-")


def test_initializer_is_private_atomic_and_idempotent(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)

    created = initialize_evidence_key(apply=True, environ=environment)
    again = initialize_evidence_key(apply=True, environ=environment)

    assert set(created) == {"keyId", "path", "created"}
    assert created["created"] is True
    assert again == {**created, "created": False}
    assert created["path"] == str(path)
    assert created["keyId"] == evidence_key_id(
        load_evidence_secret(environment), environ=environment
    )
    assert path.stat().st_mode & 0o777 == 0o600
    decoded = json.loads(path.read_text())
    assert decoded["schema"] == "creator_os.evidence_key.v1"
    assert decoded["keyId"] == created["keyId"]


def test_initializer_dry_run_is_zero_write(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)

    preview = initialize_evidence_key(apply=False, environ=environment)

    assert preview == {"keyId": None, "path": str(path), "created": False}
    assert not path.exists()
    assert not path.parent.exists()


def test_key_file_rejects_unsafe_permissions(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)
    initialize_evidence_key(apply=True, environ=environment)
    path.chmod(0o640)

    with pytest.raises(EvidenceAttestationError, match="permissions_unsafe"):
        load_evidence_secret(environment)


def test_key_file_rejects_symlink(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)
    real_environment = {
        "CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE": str(
            tmp_path / "real" / "evidence-auth-key.json"
        )
    }
    initialize_evidence_key(apply=True, environ=real_environment)
    path.parent.mkdir(mode=0o700)
    path.symlink_to(real_environment["CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE"])

    with pytest.raises(EvidenceAttestationError, match="key_file_symlink"):
        load_evidence_secret(environment)


def test_key_file_rejects_bound_key_id_drift(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)
    initialize_evidence_key(apply=True, environ=environment)
    decoded = json.loads(path.read_text())
    decoded["keyId"] = "local-0000000000000000"
    path.write_text(json.dumps(decoded))
    path.chmod(0o600)

    with pytest.raises(EvidenceAttestationError, match="key_drift"):
        load_evidence_secret(environment)


def test_key_file_rejects_short_secret_and_non_regular_input(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)
    path.parent.mkdir(mode=0o700)
    path.write_text(
        json.dumps(
            {
                "schema": "creator_os.evidence_key.v1",
                "keyId": "local-0000000000000000",
                "secret": "short",
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(EvidenceAttestationError, match="secret_too_short"):
        load_evidence_secret(environment)

    path.unlink()
    path.mkdir(mode=0o700)
    with pytest.raises(EvidenceAttestationError, match="not_regular"):
        load_evidence_secret(environment)


def test_configured_key_id_is_a_drift_pin(tmp_path: Path) -> None:
    environment, _ = _key_environment(tmp_path)
    created = initialize_evidence_key(apply=True, environ=environment)
    environment["CREATOR_OS_EVIDENCE_AUTH_KEY_ID"] = "local-0000000000000000"

    with pytest.raises(EvidenceAttestationError, match="key_drift"):
        evidence_key_id(load_evidence_secret(environment), environ=environment)
    assert created["keyId"] != environment["CREATOR_OS_EVIDENCE_AUTH_KEY_ID"]


def test_python_and_node_load_the_same_file_and_key_identity(tmp_path: Path) -> None:
    environment, path = _key_environment(tmp_path)
    created = initialize_evidence_key(apply=True, environ=environment)
    root = Path(__file__).resolve().parents[3]
    module_uri = (root / "packages/contentforge/lib/evidence-attestation.js").as_uri()
    script = (
        f'import {{loadEvidenceSecret,evidenceKeyId}} from "{module_uri}";'
        "const environ={CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE:process.argv[1]};"
        "const secret=loadEvidenceSecret(environ);"
        "process.stdout.write(evidenceKeyId(secret,environ));"
    )

    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(path)],
        capture_output=True,
        check=True,
        text=True,
        env={**os.environ, "CREATOR_OS_EVIDENCE_AUTH_SECRET": ""},
    )

    assert completed.stdout == created["keyId"]
    assert SECRET not in completed.stdout


def test_default_key_path_uses_canonical_creator_os_config_root(tmp_path: Path) -> None:
    assert evidence_secret_path({"HOME": str(tmp_path)}) == (
        tmp_path / ".creator-os/credentials/evidence-auth-key.json"
    )


def test_initializer_cli_never_prints_the_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment, path = _key_environment(tmp_path)
    monkeypatch.delenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", raising=False)
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE", str(path))

    assert main(["init", "--apply"]) == 0
    output = capsys.readouterr().out
    decoded = json.loads(output)
    stored = json.loads(path.read_text())

    assert set(decoded) == {"keyId", "path", "created"}
    assert decoded["keyId"] == stored["keyId"]
    assert stored["secret"] not in output
    assert "secret" not in decoded
