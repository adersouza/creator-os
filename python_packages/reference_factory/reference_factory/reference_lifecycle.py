"""Signed, append-only governance for reference and promoted-pattern use."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from sqlite3 import Connection, Row
from typing import Any

from creator_os_core.evidence_attestation import (
    load_evidence_secret,
    payload_fingerprint,
    sign_evidence_attestation,
    verify_evidence_attestation,
)

from .timeutil import now_iso

REFERENCE_EVENT_TYPES = frozenset(
    {
        "rights_granted",
        "rights_renewed",
        "rights_revoked",
        "rights_expired",
        "reference_deleted",
        "contradiction_opened",
        "contradiction_resolved",
    }
)
PATTERN_EVENT_TYPES = frozenset({"promoted", "superseded", "invalidated"})
EVIDENCE_TYPES = frozenset({"evidence", "inference"})
RIGHTS_EVENT_TYPES = frozenset(
    {
        "rights_granted",
        "rights_renewed",
        "rights_revoked",
        "rights_expired",
        "reference_deleted",
    }
)
ISSUER = "reference_factory.lifecycle"
SCHEMA = "reference_factory.lifecycle_event.v1"
PATTERN_SCHEMA = "reference_factory.pattern_lifecycle_event.v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def record_reference_lifecycle_event(
    conn: Connection,
    *,
    reference_id: str,
    event_type: str,
    operator: str,
    reason: str,
    evidence: dict[str, Any],
    evidence_type: str = "evidence",
    effective_at: str | None = None,
    expires_at: str | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    """Append one signed event and update the queryable current-state projection."""

    normalized_event = _choice(event_type, REFERENCE_EVENT_TYPES, "event_type")
    normalized_evidence_type = _choice(evidence_type, EVIDENCE_TYPES, "evidence_type")
    normalized_operator = _required(operator, "operator")
    normalized_reason = _required(reason, "reason")
    if (
        normalized_event in RIGHTS_EVENT_TYPES
        and normalized_evidence_type != "evidence"
    ):
        raise ValueError("reference rights events require evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("reference lifecycle evidence must be a nonempty object")
    source = conn.execute(
        """
        SELECT reference_id, content_hash
        FROM source_files
        WHERE reference_id=?
        """,
        (reference_id,),
    ).fetchone()
    if source is None:
        raise ValueError(f"unknown reference_id: {reference_id}")
    subject_sha256 = str(source["content_hash"] or "").strip().lower()
    if not _SHA256.fullmatch(subject_sha256):
        raise ValueError("reference lifecycle requires an exact source SHA-256")

    issued_at = _timestamp(effective_at or now_iso(), "effective_at")
    normalized_expiry = (
        _timestamp(expires_at, "expires_at") if expires_at is not None else None
    )
    if normalized_event in {"rights_granted", "rights_renewed"}:
        if normalized_expiry is None:
            raise ValueError("rights grant requires expires_at")
        if _parse_time(normalized_expiry) <= _parse_time(issued_at):
            raise ValueError("rights grant expires_at must follow effective_at")
        evidence = _validate_rights_grant_evidence(
            evidence,
            effective_at=issued_at,
            expires_at=normalized_expiry,
        )
    elif expires_at is not None:
        raise ValueError(f"{normalized_event} does not accept expires_at")

    core = {
        "schema": SCHEMA,
        "referenceId": str(reference_id),
        "eventType": normalized_event,
        "evidenceType": normalized_evidence_type,
        "operator": normalized_operator,
        "reason": normalized_reason,
        "effectiveAt": issued_at,
        "expiresAt": normalized_expiry,
        "subjectSha256": subject_sha256,
        "evidence": evidence,
    }
    event_id = f"refevt_{payload_fingerprint(core)[:24]}"
    payload = {"eventId": event_id, **core}
    signing_secret = secret or load_evidence_secret()
    attestation = sign_evidence_attestation(
        payload,
        issuer=ISSUER,
        issued_at=issued_at,
        secret=signing_secret,
    )
    verify_evidence_attestation(
        attestation,
        payload,
        secret=signing_secret,
        expected_issuer=ISSUER,
        now=datetime.now(UTC),
    )

    existing = conn.execute(
        "SELECT event_payload_json, attestation_json FROM reference_lifecycle_events WHERE id=?",
        (event_id,),
    ).fetchone()
    if existing is not None:
        if (
            _json(existing["event_payload_json"]) != payload
            or _json(existing["attestation_json"]) != attestation
        ):
            raise RuntimeError("reference lifecycle event identity collision")
        return reference_lifecycle_snapshot(
            conn, reference_id, secret=signing_secret, as_of=issued_at
        )

    prior = conn.execute(
        "SELECT * FROM reference_lifecycle_state WHERE reference_id=?",
        (reference_id,),
    ).fetchone()
    if prior is not None and _parse_time(issued_at) < _parse_time(
        str(prior["updated_at"])
    ):
        raise ValueError("reference lifecycle events cannot be backdated")
    next_state = _reduce_reference_state(prior, normalized_event, normalized_expiry)
    with conn:
        conn.execute(
            """
            INSERT INTO reference_lifecycle_events (
              id, reference_id, event_type, evidence_type, operator, reason,
              effective_at, expires_at, subject_sha256, event_payload_json,
              attestation_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                reference_id,
                normalized_event,
                normalized_evidence_type,
                normalized_operator,
                normalized_reason,
                issued_at,
                normalized_expiry,
                subject_sha256,
                _dump(payload),
                _dump(attestation),
                issued_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO reference_lifecycle_state (
              reference_id, rights_status, reference_status,
              contradiction_status, rights_expires_at, latest_event_id,
              updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
              rights_status=excluded.rights_status,
              reference_status=excluded.reference_status,
              contradiction_status=excluded.contradiction_status,
              rights_expires_at=excluded.rights_expires_at,
              latest_event_id=excluded.latest_event_id,
              updated_at=excluded.updated_at
            """,
            (
                reference_id,
                next_state["rightsStatus"],
                next_state["referenceStatus"],
                next_state["contradictionStatus"],
                next_state["expiresAt"],
                event_id,
                issued_at,
            ),
        )
    return reference_lifecycle_snapshot(
        conn, reference_id, secret=signing_secret, as_of=issued_at
    )


def record_pattern_lifecycle_event(
    conn: Connection,
    *,
    pattern_id: str,
    event_type: str,
    operator: str,
    reason: str,
    evidence: dict[str, Any],
    evidence_type: str = "evidence",
    superseded_by_pattern_id: str | None = None,
    effective_at: str | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    """Append one signed promoted-pattern lifecycle event."""

    normalized_event = _choice(event_type, PATTERN_EVENT_TYPES, "event_type")
    normalized_evidence_type = _choice(evidence_type, EVIDENCE_TYPES, "evidence_type")
    normalized_operator = _required(operator, "operator")
    normalized_reason = _required(reason, "reason")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("pattern lifecycle evidence must be a nonempty object")
    row = conn.execute(
        "SELECT * FROM reference_patterns WHERE id=?", (pattern_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown pattern_id: {pattern_id}")
    replacement = str(superseded_by_pattern_id or "").strip() or None
    if normalized_event == "superseded":
        if replacement is None or replacement == pattern_id:
            raise ValueError("superseded pattern requires a different replacement")
        replacement_row = conn.execute(
            "SELECT reference_id FROM reference_patterns WHERE id=?", (replacement,)
        ).fetchone()
        if replacement_row is None:
            raise ValueError(f"unknown replacement pattern_id: {replacement}")
        if replacement_row["reference_id"] != row["reference_id"]:
            raise ValueError("replacement pattern must share the same reference")
    elif replacement is not None:
        raise ValueError(f"{normalized_event} does not accept a replacement pattern")

    issued_at = _timestamp(effective_at or now_iso(), "effective_at")
    subject_sha256 = _pattern_subject_sha256(row)
    core = {
        "schema": PATTERN_SCHEMA,
        "patternId": pattern_id,
        "eventType": normalized_event,
        "evidenceType": normalized_evidence_type,
        "operator": normalized_operator,
        "reason": normalized_reason,
        "effectiveAt": issued_at,
        "subjectSha256": subject_sha256,
        "supersededByPatternId": replacement,
        "evidence": evidence,
    }
    event_id = f"patevt_{payload_fingerprint(core)[:24]}"
    payload = {"eventId": event_id, **core}
    signing_secret = secret or load_evidence_secret()
    attestation = sign_evidence_attestation(
        payload,
        issuer=ISSUER,
        issued_at=issued_at,
        secret=signing_secret,
    )
    verify_evidence_attestation(
        attestation,
        payload,
        secret=signing_secret,
        expected_issuer=ISSUER,
        now=datetime.now(UTC),
    )

    existing = conn.execute(
        """
        SELECT event_payload_json, attestation_json
        FROM reference_pattern_lifecycle_events WHERE id=?
        """,
        (event_id,),
    ).fetchone()
    if existing is not None:
        if (
            _json(existing["event_payload_json"]) != payload
            or _json(existing["attestation_json"]) != attestation
        ):
            raise RuntimeError("pattern lifecycle event identity collision")
        return pattern_lifecycle_snapshot(conn, pattern_id, secret=signing_secret)

    prior_state = conn.execute(
        "SELECT updated_at FROM reference_pattern_lifecycle_state WHERE pattern_id=?",
        (pattern_id,),
    ).fetchone()
    if prior_state is not None and _parse_time(issued_at) < _parse_time(
        str(prior_state["updated_at"])
    ):
        raise ValueError("pattern lifecycle events cannot be backdated")

    with conn:
        conn.execute(
            """
            INSERT INTO reference_pattern_lifecycle_events (
              id, pattern_id, event_type, superseded_by_pattern_id,
              evidence_type, operator, reason, effective_at, subject_sha256,
              event_payload_json, attestation_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                pattern_id,
                normalized_event,
                replacement,
                normalized_evidence_type,
                normalized_operator,
                normalized_reason,
                issued_at,
                subject_sha256,
                _dump(payload),
                _dump(attestation),
                issued_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO reference_pattern_lifecycle_state (
              pattern_id, status, superseded_by_pattern_id, latest_event_id,
              updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(pattern_id) DO UPDATE SET
              status=excluded.status,
              superseded_by_pattern_id=excluded.superseded_by_pattern_id,
              latest_event_id=excluded.latest_event_id,
              updated_at=excluded.updated_at
            """,
            (
                pattern_id,
                {
                    "promoted": "active",
                    "superseded": "superseded",
                    "invalidated": "invalidated",
                }[normalized_event],
                replacement,
                event_id,
                issued_at,
            ),
        )
    return pattern_lifecycle_snapshot(conn, pattern_id, secret=signing_secret)


def reference_lifecycle_snapshot(
    conn: Connection,
    reference_id: str,
    *,
    secret: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    state = conn.execute(
        """
        SELECT rls.*, rle.evidence_type, rle.event_payload_json, rle.attestation_json
        FROM reference_lifecycle_state rls
        JOIN reference_lifecycle_events rle ON rle.id=rls.latest_event_id
        WHERE rls.reference_id=?
        """,
        (reference_id,),
    ).fetchone()
    if state is None:
        return {
            "referenceId": reference_id,
            "rightsStatus": "unverified",
            "referenceStatus": "active",
            "contradictionStatus": "clear",
            "expiresAt": None,
            "latestEventId": None,
            "latestEvidenceType": None,
            "latestEventFingerprint": None,
            "eligible": False,
            "blockers": ["rights_evidence_missing"],
        }
    payload = _json(state["event_payload_json"])
    attestation = _json(state["attestation_json"])
    blockers: list[str] = []
    try:
        verify_evidence_attestation(
            attestation,
            payload,
            secret=secret or load_evidence_secret(),
            expected_issuer=ISSUER,
            now=datetime.now(UTC),
        )
    except Exception:
        blockers.append("rights_attestation_invalid")
    rights_status = str(state["rights_status"])
    reference_status = str(state["reference_status"])
    contradiction_status = str(state["contradiction_status"])
    expiry = state["rights_expires_at"]
    effective_at = _timestamp(as_of or now_iso(), "as_of")
    if reference_status == "deleted":
        blockers.append("reference_deleted")
    if contradiction_status == "open":
        blockers.append("reference_contradictory")
    if rights_status != "granted":
        blockers.append(f"rights_{rights_status}")
    elif expiry is None or _parse_time(str(expiry)) <= _parse_time(effective_at):
        rights_status = "expired"
        blockers.append("rights_expired")
    grant = _latest_rights_grant(conn, reference_id)
    if rights_status == "granted":
        if grant is None:
            blockers.append("rights_evidence_missing")
        else:
            grant_payload = _json(grant["event_payload_json"])
            try:
                verify_evidence_attestation(
                    _json(grant["attestation_json"]),
                    grant_payload,
                    secret=secret or load_evidence_secret(),
                    expected_issuer=ISSUER,
                    now=datetime.now(UTC),
                )
                _validate_rights_grant_evidence(
                    _json(grant_payload.get("evidence")),
                    effective_at=str(grant_payload.get("effectiveAt") or ""),
                    expires_at=str(grant_payload.get("expiresAt") or ""),
                )
                source = conn.execute(
                    "SELECT content_hash FROM source_files WHERE reference_id=?",
                    (reference_id,),
                ).fetchone()
                if (
                    source is None
                    or str(source["content_hash"] or "").strip().lower()
                    != str(grant_payload.get("subjectSha256") or "").strip().lower()
                ):
                    blockers.append("rights_subject_sha256_mismatch")
            except Exception:
                blockers.append("rights_evidence_invalid")
    return {
        "referenceId": reference_id,
        "rightsStatus": rights_status,
        "referenceStatus": reference_status,
        "contradictionStatus": contradiction_status,
        "expiresAt": expiry,
        "latestEventId": state["latest_event_id"],
        "latestEvidenceType": state["evidence_type"],
        "latestEventFingerprint": payload_fingerprint(payload),
        "eligible": not blockers,
        "blockers": _unique(blockers),
    }


def require_reference_provider_rights(
    conn: Connection,
    *,
    reference_id: str,
    provider: str,
    operation: str,
    expected_source_sha256: str,
    secret: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Require current, signed, exact-byte rights for one external provider action."""

    snapshot = reference_lifecycle_snapshot(
        conn,
        reference_id,
        secret=secret,
        as_of=as_of,
    )
    blockers = list(snapshot.get("blockers") or [])
    grant = _latest_rights_grant(conn, reference_id)
    if grant is None:
        blockers.append("rights_evidence_missing")
        evidence: dict[str, Any] = {}
        grant_payload: dict[str, Any] = {}
    else:
        grant_payload = _json(grant["event_payload_json"])
        evidence = _json(grant_payload.get("evidence"))
    canonical_sha256 = str(grant_payload.get("subjectSha256") or "").strip().lower()
    if not _SHA256.fullmatch(expected_source_sha256) or (
        canonical_sha256 != expected_source_sha256
    ):
        blockers.append("rights_subject_sha256_mismatch")
    sharing = evidence.get("providerSharing")
    allowed_providers = (
        {
            str(value).strip().lower()
            for value in sharing.get("providers", [])
            if str(value).strip()
        }
        if isinstance(sharing, dict)
        else set()
    )
    if (
        not isinstance(sharing, dict)
        or sharing.get("allowed") is not True
        or provider.strip().lower() not in allowed_providers
        and "*" not in allowed_providers
    ):
        blockers.append("rights_provider_sharing_blocked")
    scopes = {
        str(value).strip() for value in evidence.get("scope", []) if str(value).strip()
    }
    if operation not in scopes and "all_reference_operations" not in scopes:
        blockers.append("rights_operation_scope_blocked")
    if blockers or grant is None:
        raise PermissionError(
            "reference_provider_rights_ineligible:" + ",".join(_unique(blockers))
        )
    return {
        "schema": "reference_factory.provider_rights_eligibility.v1",
        "referenceId": reference_id,
        "provider": provider.strip().lower(),
        "operation": operation,
        "sourceSha256": expected_source_sha256,
        "rightsEventId": grant["id"],
        "rightsEvidenceFingerprint": payload_fingerprint(grant_payload),
        "rightsExpiresAt": snapshot["expiresAt"],
        "eligible": True,
    }


def pattern_lifecycle_snapshot(
    conn: Connection,
    pattern_id: str,
    *,
    secret: str | None = None,
) -> dict[str, Any]:
    state = conn.execute(
        """
        SELECT rpls.*, rple.evidence_type, rple.event_payload_json,
               rple.attestation_json
        FROM reference_pattern_lifecycle_state rpls
        JOIN reference_pattern_lifecycle_events rple
          ON rple.id=rpls.latest_event_id
        WHERE rpls.pattern_id=?
        """,
        (pattern_id,),
    ).fetchone()
    if state is None:
        return {
            "patternId": pattern_id,
            "status": "legacy_active",
            "supersededByPatternId": None,
            "latestEventId": None,
            "latestEvidenceType": None,
            "latestEventFingerprint": None,
            "eligible": True,
            "blockers": [],
        }
    payload = _json(state["event_payload_json"])
    blockers: list[str] = []
    try:
        verify_evidence_attestation(
            _json(state["attestation_json"]),
            payload,
            secret=secret or load_evidence_secret(),
            expected_issuer=ISSUER,
            now=datetime.now(UTC),
        )
    except Exception:
        blockers.append("pattern_attestation_invalid")
    status = str(state["status"])
    if status != "active":
        blockers.append(f"pattern_{status}")
    return {
        "patternId": pattern_id,
        "status": status,
        "supersededByPatternId": state["superseded_by_pattern_id"],
        "latestEventId": state["latest_event_id"],
        "latestEvidenceType": state["evidence_type"],
        "latestEventFingerprint": payload_fingerprint(payload),
        "eligible": not blockers,
        "blockers": _unique(blockers),
    }


def reference_is_eligible(
    conn: Connection,
    reference_id: str,
    *,
    secret: str | None = None,
    as_of: str | None = None,
) -> bool:
    return bool(
        reference_lifecycle_snapshot(conn, reference_id, secret=secret, as_of=as_of)[
            "eligible"
        ]
    )


def invalidated_pattern_ids(conn: Connection) -> list[str]:
    return [
        str(row["pattern_id"])
        for row in conn.execute(
            """
            SELECT pattern_id
            FROM reference_pattern_lifecycle_state
            WHERE status IN ('invalidated', 'superseded')
            ORDER BY pattern_id
            """
        ).fetchall()
    ]


def _latest_rights_grant(conn: Connection, reference_id: str) -> Row | None:
    return conn.execute(
        """
        SELECT *
        FROM reference_lifecycle_events
        WHERE reference_id=?
          AND event_type IN ('rights_granted', 'rights_renewed')
        ORDER BY effective_at DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (reference_id,),
    ).fetchone()


def _validate_rights_grant_evidence(
    evidence: dict[str, Any],
    *,
    effective_at: str,
    expires_at: str,
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("rights grant evidence must be an object")
    agreement_id = _required(evidence.get("agreementId"), "evidence.agreementId")
    subject = _required(evidence.get("subject"), "evidence.subject")
    scopes = _string_list(evidence.get("scope"), "evidence.scope")
    territories = _string_list(evidence.get("territories"), "evidence.territories")
    sharing = evidence.get("providerSharing")
    if not isinstance(sharing, dict) or not isinstance(sharing.get("allowed"), bool):
        raise ValueError("evidence.providerSharing.allowed must be a boolean")
    providers = _string_list(
        sharing.get("providers"),
        "evidence.providerSharing.providers",
        allow_empty=sharing["allowed"] is False,
    )
    if evidence.get("commercialUse") is not True:
        raise ValueError("evidence.commercialUse must explicitly be true")
    validity = evidence.get("validity")
    if not isinstance(validity, dict):
        raise ValueError("evidence.validity must be an object")
    starts_at = _timestamp(
        _required(validity.get("startsAt"), "evidence.validity.startsAt"),
        "evidence.validity.startsAt",
    )
    ends_at = _timestamp(
        _required(validity.get("expiresAt"), "evidence.validity.expiresAt"),
        "evidence.validity.expiresAt",
    )
    if starts_at != _timestamp(effective_at, "effective_at"):
        raise ValueError("evidence validity start must match effective_at")
    if ends_at != _timestamp(expires_at, "expires_at"):
        raise ValueError("evidence validity expiry must match expires_at")
    return {
        **evidence,
        "agreementId": agreement_id,
        "subject": subject,
        "scope": scopes,
        "providerSharing": {
            "allowed": sharing["allowed"],
            "providers": providers,
        },
        "commercialUse": True,
        "territories": territories,
        "validity": {"startsAt": starts_at, "expiresAt": ends_at},
    }


def _string_list(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    normalized = _unique([str(item).strip() for item in value if str(item).strip()])
    if not normalized and not allow_empty:
        raise ValueError(f"{field} must contain at least one value")
    return normalized


def _reduce_reference_state(
    prior: Row | None,
    event_type: str,
    expires_at: str | None,
) -> dict[str, str | None]:
    state: dict[str, str | None] = {
        "rightsStatus": str(prior["rights_status"]) if prior else "unverified",
        "referenceStatus": str(prior["reference_status"]) if prior else "active",
        "contradictionStatus": (
            str(prior["contradiction_status"]) if prior else "clear"
        ),
        "expiresAt": prior["rights_expires_at"] if prior else None,
    }
    if event_type in {"rights_granted", "rights_renewed"}:
        if state["referenceStatus"] == "deleted":
            raise ValueError("deleted reference cannot receive new rights")
        state["rightsStatus"] = "granted"
        state["expiresAt"] = expires_at
    elif event_type == "rights_revoked":
        state["rightsStatus"] = "revoked"
        state["expiresAt"] = None
    elif event_type == "rights_expired":
        state["rightsStatus"] = "expired"
    elif event_type == "reference_deleted":
        state["referenceStatus"] = "deleted"
        state["rightsStatus"] = "revoked"
        state["expiresAt"] = None
    elif event_type == "contradiction_opened":
        state["contradictionStatus"] = "open"
    elif event_type == "contradiction_resolved":
        state["contradictionStatus"] = "clear"
    return state


def _pattern_subject_sha256(row: Row) -> str:
    payload = {
        key: row[key]
        for key in (
            "id",
            "reference_id",
            "public_post_id",
            "provider",
            "model",
            "analyzer_version",
            "pattern_json",
        )
    }
    return hashlib.sha256(_dump(payload).encode("utf-8")).hexdigest()


def _choice(value: str, allowed: frozenset[str], field: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"unsupported {field}: {value}")
    return normalized


def _required(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _timestamp(value: str, field: str) -> str:
    parsed = _parse_time(value)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(UTC)


def _dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("lifecycle evidence must be an object")
    return parsed


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
