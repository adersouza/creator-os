"""Authenticated, local-only attestations for Creator OS evidence records."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

SCHEMA: Final = "creator_os.evidence_attestation.v1"
ALGORITHM: Final = "hmac-sha256"
SECRET_ENV: Final = "CREATOR_OS_EVIDENCE_AUTH_SECRET"
KEY_ID_ENV: Final = "CREATOR_OS_EVIDENCE_AUTH_KEY_ID"


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


def load_evidence_secret(environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    secret = str(environment.get(SECRET_ENV) or "")
    if len(secret.encode("utf-8")) < 32:
        raise EvidenceAttestationError(f"{SECRET_ENV} must contain at least 32 bytes")
    return secret


def evidence_key_id(secret: str, *, environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    configured = str(environment.get(KEY_ID_ENV) or "").strip()
    if configured:
        if len(configured) > 128:
            raise EvidenceAttestationError("evidence_attestation_key_id_invalid")
        return configured
    return f"local-{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]}"


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
