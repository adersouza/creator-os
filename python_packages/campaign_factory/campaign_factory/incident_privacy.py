from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

INCIDENT_TRANSITIONS = {
    "detected": {"triaged", "manual_hold"},
    "triaged": {"contained", "manual_hold"},
    "contained": {"repairing", "manual_hold"},
    "manual_hold": {"triaged", "contained", "repairing"},
    "repairing": {"reconciled", "manual_hold"},
    "reconciled": {"verified", "manual_hold"},
    "verified": {"closed", "manual_hold"},
    "closed": set(),
}

PRIVACY_TRANSITIONS = {
    "requested": {"scoped", "manual_hold", "blocked"},
    "scoped": {"authorized", "manual_hold", "blocked"},
    "authorized": {"executing", "manual_hold", "blocked"},
    "executing": {"verification_pending", "manual_hold", "blocked"},
    "verification_pending": {"verified", "manual_hold", "blocked"},
    "manual_hold": {
        "scoped",
        "authorized",
        "executing",
        "verification_pending",
        "blocked",
    },
    "blocked": {"scoped", "manual_hold"},
    "verified": {"closed"},
    "closed": set(),
}

PROTECTED_DATA_CLASSES = {
    "financial_evidence": "retain_financial",
    "security_evidence": "retain_security",
    "legal_evidence": "retain_legal",
    "audit_evidence": "retain_audit",
}

INCIDENT_CATEGORIES = {
    "provider_ambiguity",
    "overspend",
    "missing_files",
    "stale_approvals",
    "migration_failure",
    "reconciliation_mismatch",
    "consent_revocation",
    "cross_creator_contamination",
    "failed_backup",
    "failed_restore",
    "runtime_promotion_failure",
    "handoff_ambiguity",
    "security_finding",
}
INCIDENT_SEVERITIES = {"info", "low", "medium", "high", "critical"}
PRIVACY_REQUEST_TYPES = {
    "consent_revocation",
    "creator_departure",
    "account_disassociation",
    "deletion_request",
    "legal_hold",
    "backup_purge",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _required(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


@contextmanager
def _atomic(conn: sqlite3.Connection, name: str) -> Iterator[None]:
    savepoint = f"{name}_{id(conn)}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    else:
        conn.execute(f"RELEASE {savepoint}")


class IncidentRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._utc_now = utc_now

    def create(
        self,
        *,
        category: str,
        severity: str,
        domain_owner: str,
        owner: str,
        next_action: str,
        operator: str,
        model_id: str | None = None,
        campaign_id: str | None = None,
        affected_assets: list[str] | None = None,
        external_effect_state: str = "unknown",
        financial_exposure: dict[str, Any] | None = None,
        privacy_exposure: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        detected_at: str | None = None,
        fingerprint_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = detected_at or self._utc_now()
        assets = sorted(set(affected_assets or []))
        scope = fingerprint_scope or {
            "category": category,
            "modelId": model_id,
            "campaignId": campaign_id,
            "affectedAssets": assets,
            "externalEffectState": external_effect_state,
            "financialExposure": financial_exposure or {},
            "privacyExposure": privacy_exposure or {},
        }
        fingerprint = _fingerprint(scope)
        prior = self.conn.execute(
            "SELECT * FROM incident_records WHERE incident_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if prior is not None:
            return self.get(str(prior["id"]))
        incident_id = self._new_id("incident")
        with _atomic(self.conn, "create_incident"):
            self.conn.execute(
                """
                INSERT INTO incident_records
                (id, incident_fingerprint, category, state, severity, domain_owner,
                 model_id, campaign_id, affected_assets_json,
                 external_effect_state, financial_exposure_json,
                 privacy_exposure_json, owner, next_action, operator,
                 detected_at, created_at, updated_at)
                VALUES (?, ?, ?, 'detected', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?)
                """,
                (
                    incident_id,
                    fingerprint,
                    category,
                    severity,
                    _required(domain_owner, "domain_owner"),
                    model_id,
                    campaign_id,
                    _canonical(assets),
                    external_effect_state,
                    _canonical(financial_exposure or {}),
                    _canonical(privacy_exposure or {}),
                    _required(owner, "owner"),
                    _required(next_action, "next_action"),
                    _required(operator, "operator"),
                    now,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO incident_events
                (id, incident_id, previous_state, new_state, actor, action,
                 evidence_json, version, created_at)
                VALUES (?, ?, NULL, 'detected', ?, 'incident_detected', ?, 1, ?)
                """,
                (
                    self._new_id("incident_event"),
                    incident_id,
                    operator,
                    _canonical({"fingerprintScope": scope}),
                    now,
                ),
            )
            for item in evidence or []:
                self._add_evidence(incident_id, item, now)
        return self.get(incident_id)

    def _add_evidence(
        self, incident_id: str, evidence: dict[str, Any], created_at: str
    ) -> None:
        evidence_id = _required(str(evidence.get("evidenceId") or ""), "evidence_id")
        self.conn.execute(
            """
            INSERT INTO incident_evidence_links
            (id, incident_id, evidence_type, evidence_id, evidence_sha256,
             evidence_path, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(incident_id, evidence_type, evidence_id) DO NOTHING
            """,
            (
                self._new_id("incident_evidence"),
                incident_id,
                _required(str(evidence.get("evidenceType") or ""), "evidence_type"),
                evidence_id,
                evidence.get("sha256"),
                evidence.get("path"),
                _canonical(evidence.get("metadata") or {}),
                created_at,
            ),
        )

    def transition(
        self,
        incident_id: str,
        *,
        state: str,
        actor: str,
        action: str,
        evidence: dict[str, Any],
        owner: str | None = None,
        next_action: str | None = None,
        repair_actions: list[dict[str, Any]] | None = None,
        verification_evidence: list[dict[str, Any]] | None = None,
        closure_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM incident_records WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown incident: {incident_id}")
        current = str(row["state"])
        if state not in INCIDENT_TRANSITIONS[current]:
            raise ValueError(f"invalid_incident_transition:{current}:{state}")
        if state == "verified" and not verification_evidence:
            raise ValueError("incident_verification_evidence_required")
        if state == "closed" and current != "verified":
            raise ValueError("incident_must_be_verified_before_close")
        if state == "closed" and not closure_receipt:
            raise ValueError("incident_closure_receipt_required")
        now = self._utc_now()
        version = int(row["version"]) + 1
        timestamp_column = {
            "triaged": "triaged_at",
            "contained": "contained_at",
            "manual_hold": "manual_hold_at",
            "repairing": "repairing_at",
            "reconciled": "reconciled_at",
            "verified": "verified_at",
            "closed": "closed_at",
        }[state]
        repairs = repair_actions or json.loads(str(row["repair_actions_json"]))
        verifications = verification_evidence or json.loads(
            str(row["verification_evidence_json"])
        )
        closure = closure_receipt or (
            json.loads(str(row["closure_receipt_json"]))
            if row["closure_receipt_json"]
            else None
        )
        with _atomic(self.conn, "transition_incident"):
            self.conn.execute(
                """
                INSERT INTO incident_events
                (id, incident_id, previous_state, new_state, actor, action,
                 evidence_json, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._new_id("incident_event"),
                    incident_id,
                    current,
                    state,
                    _required(actor, "actor"),
                    _required(action, "action"),
                    _canonical(evidence),
                    version,
                    now,
                ),
            )
            updated = self.conn.execute(
                f"""
                UPDATE incident_records
                SET state = ?, owner = ?, next_action = ?, repair_actions_json = ?,
                    verification_evidence_json = ?, closure_receipt_json = ?,
                    {timestamp_column} = ?, version = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    state,
                    owner or row["owner"],
                    next_action or row["next_action"],
                    _canonical(repairs),
                    _canonical(verifications),
                    _canonical(closure) if closure is not None else None,
                    now,
                    version,
                    now,
                    incident_id,
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("incident_transition_concurrent_update")
        return self.get(incident_id)

    def get(self, incident_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM incident_records WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown incident: {incident_id}")
        events = self.conn.execute(
            "SELECT * FROM incident_events WHERE incident_id = ? ORDER BY version",
            (incident_id,),
        ).fetchall()
        evidence = self.conn.execute(
            """
            SELECT * FROM incident_evidence_links
            WHERE incident_id = ? ORDER BY created_at, id
            """,
            (incident_id,),
        ).fetchall()
        payload = dict(row)
        for key in (
            "affected_assets_json",
            "financial_exposure_json",
            "privacy_exposure_json",
            "repair_actions_json",
            "verification_evidence_json",
            "closure_receipt_json",
        ):
            payload[key.removesuffix("_json")] = (
                json.loads(str(payload[key])) if payload[key] is not None else None
            )
        payload["events"] = [dict(item) for item in events]
        payload["evidenceLinks"] = [dict(item) for item in evidence]
        return payload

    def report(self, incident_id: str | None = None) -> dict[str, Any]:
        if incident_id:
            return {
                "schema": "campaign_factory.incident_report.v1",
                "incident": self.get(incident_id),
            }
        rows = self.conn.execute(
            """
            SELECT id FROM incident_records
            ORDER BY CASE severity
              WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2
              WHEN 'low' THEN 3 ELSE 4 END,
              updated_at DESC, id
            """
        ).fetchall()
        incidents = [self.get(str(row["id"])) for row in rows]
        return {
            "schema": "campaign_factory.incident_report.v1",
            "openCount": sum(item["state"] != "closed" for item in incidents),
            "incidents": incidents,
        }


class CreatorPrivacyRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._utc_now = utc_now

    def _model(self, creator: str) -> sqlite3.Row:
        key = _required(creator, "creator")
        row = self.conn.execute(
            """
            SELECT DISTINCT m.* FROM models m
            LEFT JOIN creator_slug_history h ON h.model_id = m.id
            WHERE m.id = ? OR lower(m.slug) = lower(?) OR lower(h.slug) = lower(?)
            ORDER BY CASE WHEN m.id = ? THEN 0 WHEN lower(m.slug) = lower(?)
                          THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (key, key, key, key, key),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown creator: {creator}")
        return row

    def create_request(
        self,
        *,
        creator: str,
        request_type: str,
        operator: str,
        legal_basis: str,
        deletion_scope: dict[str, Any] | None = None,
        retention_policy: dict[str, Any] | None = None,
        effective_at: str | None = None,
    ) -> dict[str, Any]:
        model = self._model(creator)
        now = self._utc_now()
        effective = effective_at or now
        future_use_required = request_type in {
            "consent_revocation",
            "creator_departure",
            "deletion_request",
        }
        account_required = request_type in {
            "consent_revocation",
            "creator_departure",
            "account_disassociation",
            "deletion_request",
        }
        provider_required = request_type in {
            "consent_revocation",
            "creator_departure",
            "deletion_request",
        }
        scope = deletion_scope or {}
        retention = retention_policy or {}
        fingerprint = _fingerprint(
            {
                "modelId": model["id"],
                "requestType": request_type,
                "effectiveAt": effective,
                "deletionScope": scope,
                "retentionPolicy": retention,
                "legalBasis": legal_basis,
            }
        )
        prior = self.conn.execute(
            "SELECT id FROM creator_privacy_requests WHERE request_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if prior is not None:
            return self.get_request(str(prior["id"]))
        request_id = self._new_id("privacy_request")
        with _atomic(self.conn, "create_privacy_request"):
            self.conn.execute(
                """
                INSERT INTO creator_privacy_requests
                (id, request_fingerprint, model_id, request_type, state,
                 future_use_required, account_disassociation_required,
                 provider_inventory_required, deletion_scope_json,
                 retention_policy_json, operator, legal_basis, requested_at,
                 effective_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    fingerprint,
                    model["id"],
                    request_type,
                    int(future_use_required),
                    int(account_required),
                    int(provider_required),
                    _canonical(scope),
                    _canonical(retention),
                    operator,
                    _required(legal_basis, "legal_basis"),
                    now,
                    effective,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO creator_privacy_request_events
                (id, request_id, previous_state, new_state, actor, action,
                 evidence_json, version, created_at)
                VALUES (?, ?, NULL, 'requested', ?, 'request_recorded', ?, 1, ?)
                """,
                (
                    self._new_id("privacy_event"),
                    request_id,
                    operator,
                    _canonical({"legalBasis": legal_basis}),
                    now,
                ),
            )
            if future_use_required:
                self.conn.execute(
                    """
                    INSERT INTO creator_future_use_blocks
                    (id, model_id, request_id, block_reason, effective_at,
                     operator, evidence_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_id("future_use_block"),
                        model["id"],
                        request_id,
                        request_type,
                        effective,
                        operator,
                        _canonical({"requestFingerprint": fingerprint}),
                        now,
                    ),
                )
        return self.get_request(request_id)

    def transition_request(
        self,
        request_id: str,
        *,
        state: str,
        actor: str,
        action: str,
        evidence: dict[str, Any],
        verification_receipt: dict[str, Any] | None = None,
        closure_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM creator_privacy_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown privacy request: {request_id}")
        current = str(row["state"])
        if state not in PRIVACY_TRANSITIONS[current]:
            raise ValueError(f"invalid_privacy_transition:{current}:{state}")
        if state == "verified" and not verification_receipt:
            raise ValueError("privacy_verification_receipt_required")
        if state == "closed" and not closure_receipt:
            raise ValueError("privacy_closure_receipt_required")
        now = self._utc_now()
        version = int(row["version"]) + 1
        verification = verification_receipt or (
            json.loads(str(row["verification_receipt_json"]))
            if row["verification_receipt_json"]
            else None
        )
        closure = closure_receipt or (
            json.loads(str(row["closure_receipt_json"]))
            if row["closure_receipt_json"]
            else None
        )
        with _atomic(self.conn, "transition_privacy"):
            self.conn.execute(
                """
                INSERT INTO creator_privacy_request_events
                (id, request_id, previous_state, new_state, actor, action,
                 evidence_json, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._new_id("privacy_event"),
                    request_id,
                    current,
                    state,
                    actor,
                    action,
                    _canonical(evidence),
                    version,
                    now,
                ),
            )
            updated = self.conn.execute(
                """
                UPDATE creator_privacy_requests
                SET state = ?, verification_receipt_json = ?,
                    closure_receipt_json = ?, closed_at = ?, version = ?,
                    updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    state,
                    _canonical(verification) if verification is not None else None,
                    _canonical(closure) if closure is not None else None,
                    now if state == "closed" else row["closed_at"],
                    version,
                    now,
                    request_id,
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("privacy_transition_concurrent_update")
        return self.get_request(request_id)

    def register_inventory(
        self,
        *,
        creator: str,
        data_class: str,
        locator: str,
        operator: str,
        request_id: str | None = None,
        content_sha256: str | None = None,
        contains_bytes: bool = True,
        provider: str | None = None,
        provider_retention_until: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        account_id: str | None = None,
        retention_state: str = "active",
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model = self._model(creator)
        if data_class in PROTECTED_DATA_CLASSES:
            required_state = PROTECTED_DATA_CLASSES[data_class]
            if retention_state != required_state:
                raise PermissionError(f"{data_class}_must_be_{required_state}")
        now = self._utc_now()
        inventory_id = self._new_id("privacy_inventory")
        with _atomic(self.conn, "register_privacy_inventory"):
            self.conn.execute(
                """
                INSERT INTO creator_data_inventory
                (id, model_id, request_id, data_class, locator, content_sha256,
                 contains_bytes, provider, provider_retention_until,
                 source_asset_id, rendered_asset_id, account_id, retention_state,
                 policy_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inventory_id,
                    model["id"],
                    request_id,
                    data_class,
                    _required(locator, "locator"),
                    content_sha256,
                    int(contains_bytes),
                    provider,
                    provider_retention_until,
                    source_asset_id,
                    rendered_asset_id,
                    account_id,
                    retention_state,
                    _canonical(policy or {}),
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO creator_data_inventory_events
                (id, inventory_id, previous_state, new_state, action, operator,
                 evidence_json, version, created_at)
                VALUES (?, ?, NULL, ?, 'inventory_registered', ?, '{}', 1, ?)
                """,
                (
                    self._new_id("privacy_inventory_event"),
                    inventory_id,
                    retention_state,
                    operator,
                    now,
                ),
            )
        return self.inventory_item(inventory_id)

    def place_legal_hold(
        self,
        *,
        creator: str,
        scope: dict[str, Any],
        legal_authority: str,
        reason: str,
        operator: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        model = self._model(creator)
        now = self._utc_now()
        hold_id = self._new_id("legal_hold")
        self.conn.execute(
            """
            INSERT INTO creator_legal_holds
            (id, model_id, request_id, status, scope_json, legal_authority,
             reason, operator, effective_at, created_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                hold_id,
                model["id"],
                request_id,
                _canonical(scope),
                _required(legal_authority, "legal_authority"),
                _required(reason, "reason"),
                operator,
                now,
                now,
            ),
        )
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_legal_holds WHERE id = ?", (hold_id,)
            ).fetchone()
        )

    def release_legal_hold(
        self,
        hold_id: str,
        *,
        operator: str,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not receipt:
            raise ValueError("legal_hold_release_receipt_required")
        now = self._utc_now()
        updated = self.conn.execute(
            """
            UPDATE creator_legal_holds
            SET status = 'released', released_at = ?, release_receipt_json = ?
            WHERE id = ? AND status = 'active'
            """,
            (now, _canonical({"operator": operator, **receipt}), hold_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"active legal hold not found: {hold_id}")
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_legal_holds WHERE id = ?", (hold_id,)
            ).fetchone()
        )

    def disassociate_accounts(
        self,
        request_id: str,
        *,
        operator: str,
        external_results: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        request = self._request_row(request_id)
        accounts = self.conn.execute(
            "SELECT * FROM accounts WHERE model_id = ? ORDER BY id",
            (request["model_id"],),
        ).fetchall()
        results: list[dict[str, Any]] = []
        now = self._utc_now()
        with _atomic(self.conn, "disassociate_creator_accounts"):
            for account in accounts:
                external = (external_results or {}).get(str(account["id"]), {})
                effect_state = str(external.get("state") or "not_required")
                receipt_id = self._new_id("account_disassociation")
                self.conn.execute(
                    """
                    INSERT INTO creator_account_disassociations
                    (id, request_id, model_id, account_id, prior_external_id,
                     external_effect_state, operator, evidence_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        request_id,
                        request["model_id"],
                        account["id"],
                        account["external_id"],
                        effect_state,
                        operator,
                        _canonical(external),
                        now,
                    ),
                )
                self.conn.execute(
                    "UPDATE accounts SET model_id = NULL, updated_at = ? WHERE id = ?",
                    (now, account["id"]),
                )
                results.append(
                    {
                        "receiptId": receipt_id,
                        "accountId": account["id"],
                        "externalEffectState": effect_state,
                    }
                )
        return results

    def retire_identities(
        self, request_id: str, *, operator: str
    ) -> list[dict[str, Any]]:
        request = self._request_row(request_id)
        now = self._utc_now()
        rows = self.conn.execute(
            """
            SELECT id FROM creator_identity_profiles
            WHERE model_id = ? AND status = 'active'
            """,
            (request["model_id"],),
        ).fetchall()
        with _atomic(self.conn, "retire_creator_identities"):
            for row in rows:
                self.conn.execute(
                    """
                    UPDATE creator_identity_profiles
                    SET status = 'revoked', retired_at = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (now, row["id"]),
                )
        return [
            {
                "identityProfileId": row["id"],
                "status": "revoked",
                "operator": operator,
                "requestId": request_id,
            }
            for row in rows
        ]

    def disposition(
        self,
        inventory_id: str,
        *,
        state: str,
        operator: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM creator_data_inventory WHERE id = ?", (inventory_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown privacy inventory item: {inventory_id}")
        data_class = str(row["data_class"])
        if data_class in PROTECTED_DATA_CLASSES:
            raise PermissionError(f"{data_class}_retention_is_mandatory")
        active_holds = self.conn.execute(
            """
            SELECT id FROM creator_legal_holds
            WHERE model_id = ? AND status = 'active'
            """,
            (row["model_id"],),
        ).fetchall()
        if active_holds:
            raise PermissionError("creator_data_is_under_legal_hold")
        verified_states = {
            "deletion_verified",
            "backup_purge_verified",
            "provider_deletion_verified",
            "tombstoned",
        }
        if state in verified_states and not evidence:
            raise ValueError("privacy_disposition_evidence_required")
        if state in {"deletion_verified", "backup_purge_verified"} or (
            state == "tombstoned" and row["contains_bytes"]
        ):
            locator_type = json.loads(str(row["policy_json"])).get("locatorType")
            if locator_type != "path":
                raise PermissionError("local_deletion_verification_requires_path")
            path = Path(str(row["locator"])).expanduser()
            if path.exists() or path.is_symlink():
                raise PermissionError("bytes_still_exist_no_deletion_performed")
        now = self._utc_now()
        version = int(row["version"]) + 1
        with _atomic(self.conn, "privacy_disposition"):
            self.conn.execute(
                """
                INSERT INTO creator_data_inventory_events
                (id, inventory_id, previous_state, new_state, action, operator,
                 evidence_json, version, created_at)
                VALUES (?, ?, ?, ?, 'retention_state_recorded', ?, ?, ?, ?)
                """,
                (
                    self._new_id("privacy_inventory_event"),
                    inventory_id,
                    row["retention_state"],
                    state,
                    operator,
                    _canonical(evidence),
                    version,
                    now,
                ),
            )
            updated = self.conn.execute(
                """
                UPDATE creator_data_inventory
                SET retention_state = ?, verification_json = ?, version = ?,
                    updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    state,
                    _canonical(evidence),
                    version,
                    now,
                    inventory_id,
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("privacy_inventory_concurrent_update")
        return self.inventory_item(inventory_id)

    def deletion_plan(self, creator: str) -> dict[str, Any]:
        model = self._model(creator)
        items = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM creator_data_inventory
                WHERE model_id = ? ORDER BY data_class, locator
                """,
                (model["id"],),
            ).fetchall()
        ]
        holds = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM creator_legal_holds
                WHERE model_id = ? AND status = 'active'
                ORDER BY effective_at, id
                """,
                (model["id"],),
            ).fetchall()
        ]
        protected = [
            item for item in items if item["data_class"] in PROTECTED_DATA_CLASSES
        ]
        provider = [item for item in items if item["data_class"] == "provider_copy"]
        backups = [item for item in items if item["data_class"] == "backup"]
        eligible = [
            item
            for item in items
            if item["data_class"] not in PROTECTED_DATA_CLASSES
            and item["retention_state"]
            not in {
                "deletion_verified",
                "backup_purge_verified",
                "provider_deletion_verified",
                "tombstoned",
            }
        ]
        return {
            "schema": "campaign_factory.creator_privacy_deletion_plan.v1",
            "creator": {"id": model["id"], "slug": model["slug"]},
            "legalHolds": holds,
            "protectedEvidence": protected,
            "eligibleInventory": [] if holds else eligible,
            "blockedByLegalHold": bool(holds),
            "providerCopies": provider,
            "backups": backups,
            "note": "This is an evidence-bound plan; it performs no deletion.",
        }

    def privacy_report(self, creator: str) -> dict[str, Any]:
        model = self._model(creator)
        requests = [
            self.get_request(str(row["id"]))
            for row in self.conn.execute(
                """
                SELECT id FROM creator_privacy_requests
                WHERE model_id = ? ORDER BY requested_at, id
                """,
                (model["id"],),
            ).fetchall()
        ]
        blocks = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM creator_future_use_blocks
                WHERE model_id = ? ORDER BY effective_at, id
                """,
                (model["id"],),
            ).fetchall()
        ]
        return {
            "schema": "campaign_factory.creator_privacy_report.v1",
            "creator": {"id": model["id"], "slug": model["slug"]},
            "futureUseBlocked": bool(blocks),
            "futureUseBlocks": blocks,
            "requests": requests,
            "deletionPlan": self.deletion_plan(str(model["id"])),
        }

    def verification_readiness(self, request_id: str) -> dict[str, Any]:
        request = self._request_row(request_id)
        blockers: list[str] = []
        if request["state"] != "verification_pending":
            blockers.append(f"request_state_is_{request['state']}")
        if request["future_use_required"]:
            block = self.conn.execute(
                """
                SELECT id FROM creator_future_use_blocks
                WHERE model_id = ? AND request_id = ?
                """,
                (request["model_id"], request_id),
            ).fetchone()
            if block is None:
                blockers.append("future_use_block_missing")
        if request["account_disassociation_required"]:
            attached = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE model_id = ?",
                    (request["model_id"],),
                ).fetchone()[0]
            )
            if attached:
                blockers.append(f"accounts_still_associated:{attached}")
        if request["request_type"] in {
            "consent_revocation",
            "creator_departure",
            "deletion_request",
        }:
            active_identities = int(
                self.conn.execute(
                    """
                    SELECT COUNT(*) FROM creator_identity_profiles
                    WHERE model_id = ? AND status = 'active'
                    """,
                    (request["model_id"],),
                ).fetchone()[0]
            )
            if active_identities:
                blockers.append(f"identity_profiles_still_active:{active_identities}")
        provider_rows = self.conn.execute(
            """
            SELECT id, retention_state FROM creator_data_inventory
            WHERE model_id = ? AND data_class = 'provider_copy'
            """,
            (request["model_id"],),
        ).fetchall()
        if request["provider_inventory_required"] and not provider_rows:
            blockers.append("provider_retention_inventory_missing")
        unresolved_provider = [
            str(row["id"])
            for row in provider_rows
            if row["retention_state"] == "provider_retention_unknown"
        ]
        if unresolved_provider:
            blockers.append(
                "provider_retention_unresolved:" + ",".join(unresolved_provider)
            )
        pending_inventory = [
            str(row["id"])
            for row in self.conn.execute(
                """
                SELECT id FROM creator_data_inventory
                WHERE model_id = ?
                  AND retention_state IN (
                    'deletion_authorized', 'backup_purge_authorized',
                    'provider_deletion_requested'
                  )
                ORDER BY id
                """,
                (request["model_id"],),
            ).fetchall()
        ]
        if pending_inventory:
            blockers.append(
                "inventory_disposition_pending:" + ",".join(pending_inventory)
            )
        evidence = {
            "futureUseBlockPresent": not any(
                item == "future_use_block_missing" for item in blockers
            ),
            "associatedAccountCount": int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE model_id = ?",
                    (request["model_id"],),
                ).fetchone()[0]
            ),
            "activeIdentityCount": int(
                self.conn.execute(
                    """
                    SELECT COUNT(*) FROM creator_identity_profiles
                    WHERE model_id = ? AND status = 'active'
                    """,
                    (request["model_id"],),
                ).fetchone()[0]
            ),
            "providerInventoryIds": [str(row["id"]) for row in provider_rows],
            "pendingInventoryIds": pending_inventory,
        }
        return {
            "schema": "campaign_factory.creator_privacy_verification_readiness.v1",
            "requestId": request_id,
            "ready": not blockers,
            "blockers": blockers,
            "evidence": evidence,
        }

    def verify_request(self, request_id: str, *, operator: str) -> dict[str, Any]:
        readiness = self.verification_readiness(request_id)
        if not readiness["ready"]:
            raise PermissionError(
                "privacy_verification_blocked:" + ",".join(readiness["blockers"])
            )
        return self.transition_request(
            request_id,
            state="verified",
            actor=operator,
            action="privacy_obligations_verified",
            evidence=readiness["evidence"],
            verification_receipt={
                "schema": "campaign_factory.creator_privacy_verification.v1",
                "operator": operator,
                "verifiedAt": self._utc_now(),
                **readiness["evidence"],
            },
        )

    def get_request(self, request_id: str) -> dict[str, Any]:
        row = self._request_row(request_id)
        events = self.conn.execute(
            """
            SELECT * FROM creator_privacy_request_events
            WHERE request_id = ? ORDER BY version
            """,
            (request_id,),
        ).fetchall()
        payload = dict(row)
        for key in (
            "deletion_scope_json",
            "retention_policy_json",
            "verification_receipt_json",
            "closure_receipt_json",
        ):
            payload[key.removesuffix("_json")] = (
                json.loads(str(payload[key])) if payload[key] is not None else None
            )
        payload["events"] = [dict(item) for item in events]
        return payload

    def _request_row(self, request_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM creator_privacy_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown privacy request: {request_id}")
        return row

    def inventory_item(self, inventory_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM creator_data_inventory WHERE id = ?", (inventory_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown privacy inventory item: {inventory_id}")
        events = self.conn.execute(
            """
            SELECT * FROM creator_data_inventory_events
            WHERE inventory_id = ? ORDER BY version
            """,
            (inventory_id,),
        ).fetchall()
        payload = dict(row)
        payload["policy"] = json.loads(str(row["policy_json"]))
        payload["verification"] = json.loads(str(row["verification_json"]))
        payload["events"] = [dict(item) for item in events]
        return payload
