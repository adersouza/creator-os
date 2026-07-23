"""Authenticated, local-only attestations for Creator OS evidence records."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import sys
import tempfile
from argparse import ArgumentParser
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "creator_os.evidence_attestation.v1"
ALGORITHM: Final = "hmac-sha256"
SECRET_ENV: Final = "CREATOR_OS_EVIDENCE_AUTH_SECRET"
SECRET_FILE_ENV: Final = "CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE"
KEY_ID_ENV: Final = "CREATOR_OS_EVIDENCE_AUTH_KEY_ID"
KEY_FILE_SCHEMA: Final = "creator_os.evidence_key.v1"
DEFAULT_KEY_RELATIVE_PATH: Final = Path(
    ".creator-os/credentials/evidence-auth-key.json"
)
MINIMUM_SECRET_BYTES: Final = 32
MAXIMUM_KEY_FILE_BYTES: Final = 4096


class EvidenceAttestationError(ValueError):
    """An evidence attestation is missing, malformed, stale, or unauthentic."""


def _normalize_json_number(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceAttestationError("evidence_attestation_payload_invalid")
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {str(key): _normalize_json_number(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_number(item) for item in value]
    return value


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _normalize_json_number(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceAttestationError("evidence_attestation_payload_invalid") from exc


def payload_fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(payload))).hexdigest()


def _validate_secret(secret: str) -> str:
    if len(secret.encode("utf-8")) < MINIMUM_SECRET_BYTES:
        raise EvidenceAttestationError("evidence_attestation_secret_too_short")
    return secret


def _derived_evidence_key_id(secret: str) -> str:
    return f"local-{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]}"


def evidence_secret_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the local credential path without following its final component."""
    environment = os.environ if environ is None else environ
    configured = str(environment.get(SECRET_FILE_ENV) or "").strip()
    home = Path(str(environment.get("HOME") or Path.home())).expanduser()
    if configured:
        if configured == "~" or configured.startswith("~/"):
            configured = str(home) + configured[1:]
        selected = Path(configured)
        if not selected.is_absolute():
            raise EvidenceAttestationError("evidence_attestation_key_path_not_absolute")
    else:
        selected = home / DEFAULT_KEY_RELATIVE_PATH
    return Path(os.path.abspath(os.fspath(selected)))


def _validate_key_file_stat(file_stat: os.stat_result) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise EvidenceAttestationError("evidence_attestation_key_file_not_regular")
    if file_stat.st_mode & 0o077:
        raise EvidenceAttestationError(
            "evidence_attestation_key_file_permissions_unsafe"
        )
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise EvidenceAttestationError("evidence_attestation_key_file_owner_mismatch")
    if file_stat.st_size > MAXIMUM_KEY_FILE_BYTES:
        raise EvidenceAttestationError("evidence_attestation_key_file_too_large")


def _decode_key_file(raw: bytes) -> tuple[str, str]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAttestationError("evidence_attestation_key_file_invalid") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"schema", "keyId", "secret"}:
        raise EvidenceAttestationError("evidence_attestation_key_file_invalid")
    if decoded.get("schema") != KEY_FILE_SCHEMA:
        raise EvidenceAttestationError("evidence_attestation_key_file_version_invalid")
    secret = _validate_secret(str(decoded.get("secret") or ""))
    derived = _derived_evidence_key_id(secret)
    if decoded.get("keyId") != derived:
        raise EvidenceAttestationError("evidence_attestation_key_drift")
    return secret, derived


def _load_evidence_key_file(path: Path) -> tuple[str, str]:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError as exc:
        raise EvidenceAttestationError("evidence_attestation_key_file_missing") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise EvidenceAttestationError("evidence_attestation_key_file_symlink")
    _validate_key_file_stat(path_stat)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise EvidenceAttestationError(
            "evidence_attestation_key_file_unreadable"
        ) from exc
    try:
        opened_stat = os.fstat(fd)
        _validate_key_file_stat(opened_stat)
        if (opened_stat.st_dev, opened_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise EvidenceAttestationError("evidence_attestation_key_file_changed")
        raw = os.read(fd, MAXIMUM_KEY_FILE_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAXIMUM_KEY_FILE_BYTES:
        raise EvidenceAttestationError("evidence_attestation_key_file_too_large")
    return _decode_key_file(raw)


def load_evidence_secret(environ: Mapping[str, str] | None = None) -> str:
    """Load the environment secret first, then the private machine-local key file."""
    environment = os.environ if environ is None else environ
    if SECRET_ENV in environment:
        return _validate_secret(str(environment.get(SECRET_ENV) or ""))
    secret, _ = _load_evidence_key_file(evidence_secret_path(environment))
    return secret


def evidence_key_id(secret: str, *, environ: Mapping[str, str] | None = None) -> str:
    _validate_secret(secret)
    environment = os.environ if environ is None else environ
    derived = _derived_evidence_key_id(secret)
    configured = str(environment.get(KEY_ID_ENV) or "").strip()
    if configured:
        if len(configured) > 128:
            raise EvidenceAttestationError("evidence_attestation_key_id_invalid")
        if configured != derived:
            raise EvidenceAttestationError("evidence_attestation_key_drift")
    return derived


def _key_file_payload(secret: str) -> bytes:
    payload = {
        "schema": KEY_FILE_SCHEMA,
        "keyId": _derived_evidence_key_id(secret),
        "secret": secret,
    }
    return canonical_json(payload) + b"\n"


def initialize_evidence_key(
    *,
    apply: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Idempotently create the local evidence key without ever returning its secret."""
    environment = os.environ if environ is None else environ
    path = evidence_secret_path(environment)
    try:
        secret, key_id = _load_evidence_key_file(path)
    except EvidenceAttestationError as exc:
        if str(exc) != "evidence_attestation_key_file_missing":
            raise
    else:
        evidence_key_id(secret, environ=environment)
        return {"keyId": key_id, "path": str(path), "created": False}

    if not apply:
        return {"keyId": None, "path": str(path), "created": False}

    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_stat = os.lstat(parent)
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise EvidenceAttestationError("evidence_attestation_key_directory_unsafe")
    if parent_stat.st_mode & 0o077:
        raise EvidenceAttestationError(
            "evidence_attestation_key_directory_permissions_unsafe"
        )
    if hasattr(os, "geteuid") and parent_stat.st_uid != os.geteuid():
        raise EvidenceAttestationError(
            "evidence_attestation_key_directory_owner_mismatch"
        )

    secret = secrets.token_urlsafe(48)
    payload = _key_file_payload(secret)
    fd, temporary_name = tempfile.mkstemp(prefix=".evidence-auth-key.", dir=parent)
    temporary = Path(temporary_name)
    created = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            created = True
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError:
            existing_secret, key_id = _load_evidence_key_file(path)
            evidence_key_id(existing_secret, environ=environment)
            return {"keyId": key_id, "path": str(path), "created": False}
    finally:
        temporary.unlink(missing_ok=True)
    if not created:
        raise EvidenceAttestationError("evidence_attestation_key_create_failed")
    return {
        "keyId": _derived_evidence_key_id(secret),
        "path": str(path),
        "created": True,
    }


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceAttestationError(f"evidence_attestation_{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise EvidenceAttestationError(f"evidence_attestation_{field}_invalid")
    return parsed


def sign_evidence_attestation(
    payload: Mapping[str, Any],
    *,
    issuer: str,
    issued_at: str,
    secret: str,
    key_id: str | None = None,
) -> dict[str, Any]:
    if len(secret.encode("utf-8")) < 32:
        raise EvidenceAttestationError("evidence_attestation_secret_too_short")
    normalized_issuer = str(issuer or "").strip()
    if not normalized_issuer:
        raise EvidenceAttestationError("evidence_attestation_issuer_missing")
    _parse_timestamp(issued_at, field="issued_at")
    normalized_key_id = str(key_id or evidence_key_id(secret)).strip()
    if not normalized_key_id or len(normalized_key_id) > 128:
        raise EvidenceAttestationError("evidence_attestation_key_id_invalid")
    core = {
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "issuer": normalized_issuer,
        "keyId": normalized_key_id,
        "issuedAt": issued_at,
        "payloadFingerprint": payload_fingerprint(payload),
    }
    signature = hmac.new(
        secret.encode("utf-8"), canonical_json(core), hashlib.sha256
    ).hexdigest()
    return {**core, "signature": signature}


def verify_evidence_attestation(
    attestation: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    secret: str,
    expected_issuer: str,
    expected_key_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if len(secret.encode("utf-8")) < 32:
        raise EvidenceAttestationError("evidence_attestation_secret_too_short")
    exact = dict(attestation)
    if set(exact) != {
        "schema",
        "algorithm",
        "issuer",
        "keyId",
        "issuedAt",
        "payloadFingerprint",
        "signature",
    }:
        raise EvidenceAttestationError("evidence_attestation_shape_invalid")
    if (
        exact.get("schema") != SCHEMA
        or exact.get("algorithm") != ALGORITHM
        or exact.get("issuer") != expected_issuer
    ):
        raise EvidenceAttestationError("evidence_attestation_identity_mismatch")
    key_id = str(exact.get("keyId") or "")
    required_key_id = expected_key_id or evidence_key_id(secret)
    if key_id != required_key_id:
        raise EvidenceAttestationError("evidence_attestation_key_mismatch")
    issued_at = _parse_timestamp(exact.get("issuedAt"), field="issued_at")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or issued_at > current:
        raise EvidenceAttestationError("evidence_attestation_issued_at_invalid")
    if exact.get("payloadFingerprint") != payload_fingerprint(payload):
        raise EvidenceAttestationError("evidence_attestation_payload_mismatch")
    signature = str(exact.get("signature") or "")
    unsigned = dict(exact)
    unsigned.pop("signature", None)
    expected = hmac.new(
        secret.encode("utf-8"), canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise EvidenceAttestationError("evidence_attestation_signature_invalid")
    return exact


def _cli_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="python -m creator_os_core.evidence_attestation",
        description="Manage the private machine-local evidence attestation key.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    mode = initialize.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    if args.command != "init":
        raise AssertionError(f"unhandled evidence key command: {args.command}")
    try:
        result = initialize_evidence_key(apply=args.apply)
    except EvidenceAttestationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
