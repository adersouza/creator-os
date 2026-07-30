from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_creator_identity_profile

CREATOR_TRANSITIONS = {
    "active": {"suspended", "departed", "revoked", "deletion_pending"},
    "suspended": {"active", "departed", "revoked", "deletion_pending"},
    "departed": {"active", "revoked", "deletion_pending"},
    "revoked": {"active", "deletion_pending"},
    "deletion_pending": {"active", "deleted"},
    "deleted": set(),
}

CAMPAIGN_TRANSITIONS = {
    "created": {"configured", "paused", "blocked", "cancelled"},
    "configured": {
        "reference_ready",
        "source_ready",
        "paused",
        "blocked",
        "cancelled",
    },
    "reference_ready": {"source_ready", "paused", "blocked", "cancelled"},
    "source_ready": {"production_ready", "paused", "blocked", "cancelled"},
    "production_ready": {
        "producing",
        "reviewing",
        "paused",
        "blocked",
        "cancelled",
    },
    "producing": {"reviewing", "paused", "blocked", "completed", "cancelled"},
    "reviewing": {
        "producing",
        "approved",
        "paused",
        "blocked",
        "cancelled",
    },
    "approved": {"exporting", "completed", "paused", "blocked", "cancelled"},
    "exporting": {"completed", "paused", "blocked", "cancelled"},
    "paused": {
        "configured",
        "reference_ready",
        "source_ready",
        "production_ready",
        "producing",
        "reviewing",
        "approved",
        "exporting",
        "completed",
        "cancelled",
    },
    "blocked": {
        "configured",
        "reference_ready",
        "source_ready",
        "production_ready",
        "paused",
        "cancelled",
    },
    "completed": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),
}

_OPERATION_CAMPAIGN_STATES = {
    "generation": {"production_ready", "producing"},
    "provider_spend": {"production_ready", "producing"},
    "still_edit": {"production_ready", "producing"},
    "prompt_generation": {"production_ready", "producing"},
    "voice": {"production_ready", "producing"},
    "reserve": {"production_ready", "producing", "reviewing", "approved"},
    "reuse": {"production_ready", "producing", "reviewing", "approved"},
    "export": {"approved", "exporting"},
    "reference_analysis": {
        "configured",
        "reference_ready",
        "source_ready",
        "production_ready",
    },
}

_OPERATION_SCOPES = {
    "generation": ("likeness_generation", "commercial_use"),
    "provider_spend": ("likeness_generation", "commercial_use"),
    "still_edit": ("likeness_generation", "commercial_use"),
    "prompt_generation": ("likeness_generation", "commercial_use"),
    "reference_analysis": ("reference_video_use",),
    "voice": ("voice_use", "commercial_use"),
    "reserve": ("likeness_generation", "commercial_use"),
    "reuse": ("likeness_generation", "commercial_use"),
    "export": ("likeness_generation", "commercial_use"),
}


def resolve_campaign_operation(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    operation: str,
    provider: str,
    source_asset_id: str | None = None,
    account_id: str | None = None,
    territory: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT m.id, m.slug
        FROM campaign_governance cg
        JOIN models m ON m.id = cg.model_id
        WHERE cg.campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise PermissionError("campaign_governance_missing")
    repository = CreatorGovernanceRepository(
        conn,
        new_id=lambda prefix: f"{prefix}_read_only",
        slugify=lambda value: str(value).strip().lower().replace(" ", "_"),
        utc_now=lambda: (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        ),
    )
    return repository.resolve_operation(
        creator=str(row["id"]),
        campaign=campaign_id,
        operation=operation,
        provider=provider,
        source_asset_id=source_asset_id,
        account_id=account_id,
        territory=territory,
        at=at,
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_time(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _required(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


class CreatorGovernanceRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        managed_root: Path | None = None,
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._slugify = slugify
        self._utc_now = utc_now
        self._managed_root = managed_root.resolve() if managed_root else None

    def _managed_evidence_file(self, value: Path, label: str) -> Path:
        path = Path(value).expanduser()
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"{label} must be a regular file")
        resolved = path.resolve()
        if self._managed_root is not None:
            try:
                resolved.relative_to(self._managed_root)
            except ValueError as exc:
                raise PermissionError(f"{label}_outside_managed_root") from exc
        return resolved

    def _model(self, creator: str) -> sqlite3.Row:
        key = _required(creator, "creator")
        row = self.conn.execute(
            """
            SELECT m.* FROM models m
            LEFT JOIN creator_slug_history h ON h.model_id = m.id
            WHERE m.id = ? OR lower(m.slug) = lower(?) OR lower(h.slug) = lower(?)
            ORDER BY CASE WHEN m.id = ? THEN 0 WHEN lower(m.slug) = lower(?) THEN 1
                          ELSE 2 END
            LIMIT 1
            """,
            (key, key, key, key, key),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown creator: {creator}")
        return row

    def _validate_identity_profile_bytes(self, identity: sqlite3.Row) -> None:
        manifest_path = Path(str(identity["identity_manifest_path"]))
        if (
            manifest_path.is_symlink()
            or not manifest_path.is_file()
            or _file_sha256(manifest_path) != identity["identity_manifest_sha256"]
        ):
            raise PermissionError("creator_identity_manifest_stale")
        source = self.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?",
            (identity["canonical_source_asset_id"],),
        ).fetchone()
        if source is None or source["status"] != "approved":
            raise PermissionError("canonical_identity_source_not_exactly_approved")
        source_path = Path(str(source["stored_path"]))
        if (
            source_path.is_symlink()
            or not source_path.is_file()
            or _file_sha256(source_path) != source["content_hash"]
        ):
            raise PermissionError("canonical_identity_source_not_exactly_approved")

    def creator_status(self, creator: str) -> dict[str, Any]:
        model = self._model(creator)
        state = self.conn.execute(
            "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
            (model["id"],),
        ).fetchone()
        identities = self.conn.execute(
            """
            SELECT id, provider, provider_identity_id, version, profile_fingerprint,
                   identity_manifest_path, identity_manifest_sha256, status,
                   canonical_source_asset_id, activated_at, retired_at
            FROM creator_identity_profiles
            WHERE model_id = ? ORDER BY provider, version
            """,
            (model["id"],),
        ).fetchall()
        slugs = self.conn.execute(
            """
            SELECT slug, effective_at, retired_at
            FROM creator_slug_history WHERE model_id = ? ORDER BY effective_at
            """,
            (model["id"],),
        ).fetchall()
        accounts = self.conn.execute(
            """
            SELECT id, handle, platform, external_id, account_group_id
            FROM accounts WHERE model_id = ? ORDER BY platform, handle
            """,
            (model["id"],),
        ).fetchall()
        authorizations = self.conn.execute(
            """
            SELECT id, authorization_id, event_type, scope, provider,
                   commercial_use, territory_json, account_scope_json,
                   provider_use, reference_video_use, training_reference_use,
                   voice_authorized, effective_at, expires_at, evidence_path,
                   evidence_sha256, actor, reason, legal_hold, prior_event_id,
                   created_at
            FROM creator_authorization_events
            WHERE model_id = ? ORDER BY created_at, id
            """,
            (model["id"],),
        ).fetchall()
        return {
            "schema": "campaign_factory.creator_governance_status.v1",
            "creator": {
                "id": model["id"],
                "slug": model["slug"],
                "name": model["name"],
            },
            "lifecycle": dict(state) if state else None,
            "slugHistory": [dict(row) for row in slugs],
            "identityProfiles": [dict(row) for row in identities],
            "platformAccounts": [dict(row) for row in accounts],
            "authorizationEvents": [dict(row) for row in authorizations],
        }

    def active_identity_profile(self, creator: str, *, provider: str) -> dict[str, Any]:
        model = self._model(creator)
        state = self.conn.execute(
            "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
            (model["id"],),
        ).fetchone()
        if state is None or state["status"] != "active":
            raise PermissionError("creator_inactive")
        if provider.lower() == "internal":
            identity = self.conn.execute(
                """
                SELECT * FROM creator_identity_profiles
                WHERE model_id = ? AND status = 'active' AND activated_at >= ?
                ORDER BY activated_at DESC, version DESC
                LIMIT 1
                """,
                (model["id"], state["effective_at"]),
            ).fetchone()
        else:
            identity = self.conn.execute(
                """
                SELECT * FROM creator_identity_profiles
                WHERE model_id = ? AND provider IN (?, '*') AND status = 'active'
                  AND activated_at >= ?
                ORDER BY CASE WHEN provider = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (
                    model["id"],
                    provider.lower(),
                    state["effective_at"],
                    provider.lower(),
                ),
            ).fetchone()
        if identity is None:
            raise PermissionError("creator_identity_profile_missing")
        self._validate_identity_profile_bytes(identity)
        return {
            **dict(identity),
            "creator_id": model["id"],
            "creator_slug": model["slug"],
        }

    def transition_creator(
        self,
        creator: str,
        *,
        new_status: str,
        actor: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        model = self._model(creator)
        target = _required(new_status, "new_status")
        actor = _required(actor, "actor")
        reason = _required(reason, "reason")
        row = self.conn.execute(
            "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
            (model["id"],),
        ).fetchone()
        if row is None:
            raise PermissionError("creator_lifecycle_missing")
        current = str(row["status"])
        if target == current:
            return dict(row)
        if target not in CREATOR_TRANSITIONS.get(current, set()):
            raise ValueError(f"illegal_creator_transition:{current}->{target}")
        evidence = evidence or {}
        if target == "deleted" and not (
            str(evidence.get("deletionAuthority") or "").strip()
            and str(evidence.get("retentionDisposition") or "").strip()
        ):
            raise ValueError(
                "deleted creator requires deletionAuthority and retentionDisposition"
            )
        if validate_only:
            return {
                "schema": "campaign_factory.creator_transition_plan.v1",
                "apply": False,
                "creator": model["slug"],
                "creatorId": model["id"],
                "oldStatus": current,
                "newStatus": target,
                "actor": actor,
                "reason": reason,
                "evidence": evidence,
                "wouldChange": True,
            }
        now = self._utc_now()
        version = int(row["version"]) + 1
        retention_state = (
            "deletion_authorized"
            if target == "deleted"
            else str(row["retention_state"])
        )
        event_id = self._new_id("creator_state")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO creator_lifecycle_events
                (id, model_id, old_status, new_status, reason, actor, effective_at,
                 evidence_json, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    model["id"],
                    current,
                    target,
                    reason,
                    actor,
                    now,
                    json.dumps(evidence, sort_keys=True),
                    version,
                    now,
                ),
            )
            updated = self.conn.execute(
                """
                UPDATE creator_lifecycle_state
                SET status = ?, status_reason = ?, effective_at = ?, changed_by = ?,
                    version = ?, offboarding_state = ?, retention_state = ?,
                    updated_at = ?
                WHERE model_id = ? AND version = ?
                """,
                (
                    target,
                    reason,
                    now,
                    actor,
                    version,
                    target if target != "active" else None,
                    retention_state,
                    now,
                    model["id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("creator_transition_concurrent_update")
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
                (model["id"],),
            ).fetchone()
        )

    def rename_creator(
        self,
        creator: str,
        *,
        new_slug: str,
        actor: str,
        reason: str,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        model = self._model(creator)
        slug = self._slugify(_required(new_slug, "new_slug"))
        actor = _required(actor, "actor")
        reason = _required(reason, "reason")
        collision = self.conn.execute(
            """
            SELECT m.id
            FROM models m
            LEFT JOIN creator_slug_history h ON h.model_id = m.id
            WHERE (lower(m.slug) = lower(?) OR lower(h.slug) = lower(?))
              AND m.id <> ?
            LIMIT 1
            """,
            (slug, slug, model["id"]),
        ).fetchone()
        if collision is not None:
            raise ValueError("creator_slug_already_owned")
        if validate_only:
            return {
                "schema": "campaign_factory.creator_rename_plan.v1",
                "apply": False,
                "creator": model["slug"],
                "creatorId": model["id"],
                "oldSlug": model["slug"],
                "newSlug": slug,
                "actor": actor,
                "reason": reason,
                "wouldChange": slug != model["slug"],
            }
        now = self._utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE creator_slug_history SET retired_at = ? "
                "WHERE model_id = ? AND retired_at IS NULL",
                (now, model["id"]),
            )
            self.conn.execute(
                "UPDATE models SET slug = ?, updated_at = ? WHERE id = ?",
                (slug, now, model["id"]),
            )
            self.conn.execute(
                """
                INSERT INTO creator_slug_history
                (id, model_id, slug, effective_at, retired_at, actor, reason, created_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    self._new_id("creator_slug"),
                    model["id"],
                    slug,
                    now,
                    actor,
                    reason,
                    now,
                ),
            )
        return self.creator_status(str(model["id"]))

    def enroll_identity_profile(
        self,
        creator: str,
        *,
        provider: str,
        provider_identity_id: str,
        profile: dict[str, Any],
        canonical_source_asset_id: str,
        identity_manifest_path: Path,
        identity_manifest_sha256: str,
        operator: str,
        canonical_evidence_type: str = "operator_approved_original",
        validate_only: bool = False,
    ) -> dict[str, Any]:
        model = self._model(creator)
        provider = _required(provider, "provider").lower()
        provider_identity_id = _required(provider_identity_id, "provider_identity_id")
        operator = _required(operator, "operator")
        if canonical_evidence_type != "operator_approved_original":
            raise PermissionError("ai_derived_media_cannot_be_canonical_identity")
        source = self.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?",
            (_required(canonical_source_asset_id, "canonical_source_asset_id"),),
        ).fetchone()
        if source is None or str(source["model_id"]) != str(model["id"]):
            raise PermissionError("canonical_identity_source_creator_mismatch")
        source_path = self._managed_evidence_file(
            Path(str(source["stored_path"])), "canonical_identity_source"
        )
        source_sha = _file_sha256(source_path)
        if source["status"] != "approved" or source_sha != source["content_hash"]:
            raise PermissionError("canonical_identity_source_not_exactly_approved")
        try:
            source_prompt = json.loads(source["source_prompt"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("canonical_identity_source_lineage_invalid") from exc
        if not isinstance(source_prompt, dict):
            raise PermissionError("canonical_identity_source_lineage_invalid")
        if (
            source_prompt.get("generatedAssetLineage")
            or source_prompt.get("derivedStillSource")
            or source_prompt.get("provider")
        ):
            raise PermissionError("ai_derived_media_cannot_be_canonical_identity")
        approval_rows = self.conn.execute(
            """
            SELECT metadata_json FROM activity_events
            WHERE source_asset_id = ? AND event_type = 'source_approval_decided'
            ORDER BY created_at DESC, id DESC
            """,
            (source["id"],),
        ).fetchall()
        exact_approval = False
        for approval_row in approval_rows:
            approval = json.loads(approval_row["metadata_json"] or "{}")
            if (
                approval.get("decision") == "approved"
                and approval.get("sha256") == source_sha
            ):
                exact_approval = True
                break
        if not exact_approval:
            raise PermissionError("canonical_identity_source_approval_missing")
        origin_attestation = self.conn.execute(
            """
            SELECT metadata_json FROM activity_events
            WHERE source_asset_id = ?
              AND event_type = 'canonical_identity_origin_attested'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (source["id"],),
        ).fetchone()
        origin = (
            json.loads(origin_attestation["metadata_json"] or "{}")
            if origin_attestation is not None
            else {}
        )
        if (
            origin.get("sourceAssetId") != source["id"]
            or origin.get("sha256") != source_sha
            or origin.get("originClassification") != "human_original"
            or origin.get("operatorApproved") is not True
        ):
            raise PermissionError("canonical_identity_origin_attestation_missing")
        manifest_path = self._managed_evidence_file(
            identity_manifest_path, "identity_manifest"
        )
        actual_sha = _file_sha256(manifest_path)
        if actual_sha != identity_manifest_sha256:
            raise ValueError("identity_manifest_sha256_mismatch")
        if profile.get("schema") != "creator_os.creator_identity_profile.v1":
            raise ValueError("creator_identity_profile_schema_invalid")
        if str(profile.get("creatorKey") or "") != str(model["slug"]):
            raise ValueError("creator_identity_profile_creator_mismatch")
        validate_creator_identity_profile(profile)
        provenance_sources = profile["provenance"]["sourceReferences"]
        if not any(
            str(item["recordId"]) == str(source["id"])
            and str(item["fingerprint"]) == source_sha
            for item in provenance_sources
        ):
            raise ValueError("creator_identity_profile_source_binding_mismatch")
        provider_references = [
            item
            for item in profile["identityReferences"]
            if provider in str(item["namespace"]).lower()
        ]
        if not provider_references or provider_identity_id not in {
            str(item["externalId"]) for item in provider_references
        }:
            raise ValueError("provider_identity_profile_binding_mismatch")
        fingerprint = _canonical_sha256(profile)
        row = self.conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) FROM creator_identity_profiles
            WHERE model_id = ? AND provider = ?
            """,
            (model["id"], provider),
        ).fetchone()
        version = int(row[0] or 0) + 1
        if validate_only:
            return {
                "schema": "campaign_factory.creator_identity_enrollment_plan.v1",
                "apply": False,
                "creator": model["slug"],
                "creatorId": model["id"],
                "provider": provider,
                "providerIdentityId": provider_identity_id,
                "profileSha256": actual_sha,
                "profileFingerprint": fingerprint,
                "canonicalSourceAssetId": source["id"],
                "canonicalSourceSha256": source_sha,
                "nextVersion": version,
                "operator": operator,
            }
        now = self._utc_now()
        profile_id = self._new_id("creator_identity")
        with self.conn:
            self.conn.execute(
                """
                UPDATE creator_identity_profiles
                SET status = 'retired', retired_at = ?
                WHERE model_id = ? AND provider = ? AND status = 'active'
                """,
                (now, model["id"], provider),
            )
            self.conn.execute(
                """
                INSERT INTO creator_identity_profiles
                (id, model_id, provider, provider_identity_id, version, profile_json,
                 profile_fingerprint, identity_manifest_path,
                 identity_manifest_sha256, canonical_source_asset_id,
                 canonical_evidence_type, status,
                 activated_at, retired_at, operator, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?, ?)
                """,
                (
                    profile_id,
                    model["id"],
                    provider,
                    provider_identity_id,
                    version,
                    json.dumps(profile, sort_keys=True),
                    fingerprint,
                    str(manifest_path),
                    actual_sha,
                    source["id"],
                    canonical_evidence_type,
                    now,
                    operator,
                    now,
                ),
            )
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_identity_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        )

    def grant_authorization(
        self,
        creator: str,
        *,
        scope: str,
        provider: str,
        evidence_path: Path,
        evidence_sha256: str,
        actor: str,
        reason: str,
        effective_at: str | None = None,
        expires_at: str | None = None,
        commercial_use: bool = True,
        territories: list[str] | None = None,
        account_scope: list[str] | None = None,
        provider_use: bool = True,
        reference_video_use: bool = False,
        training_reference_use: bool = False,
        voice_authorized: bool = False,
        legal_hold: bool = False,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        model = self._model(creator)
        path = self._managed_evidence_file(evidence_path, "authorization_evidence")
        actual_sha = _file_sha256(path)
        if actual_sha != evidence_sha256:
            raise ValueError("authorization_evidence_sha256_mismatch")
        now = self._utc_now()
        effective = _parse_time(effective_at or now)
        expiry = _parse_time(expires_at) if expires_at else None
        if expiry is not None and expiry <= effective:
            raise ValueError("authorization_expiry_must_follow_effective_at")
        scope = _required(scope, "scope")
        provider = _required(provider, "provider").lower()
        actor = _required(actor, "actor")
        reason = _required(reason, "reason")
        if validate_only:
            return {
                "schema": "campaign_factory.creator_authorization_plan.v1",
                "apply": False,
                "creator": model["slug"],
                "creatorId": model["id"],
                "scope": scope,
                "provider": provider,
                "evidencePath": str(path),
                "evidenceSha256": actual_sha,
                "actor": actor,
                "reason": reason,
                "effectiveAt": _iso_time(effective),
                "expiresAt": _iso_time(expiry) if expiry else None,
                "territories": sorted(set(territories or [])),
                "accountScope": sorted(set(account_scope or [])),
                "referenceVideoUse": reference_video_use,
                "trainingReferenceUse": training_reference_use,
                "voiceAuthorized": voice_authorized,
                "legalHold": legal_hold,
            }
        authorization_id = self._new_id("creator_auth")
        event_id = self._new_id("creator_auth_event")
        self.conn.execute(
            """
            INSERT INTO creator_authorization_events
            (id, model_id, authorization_id, event_type, scope, provider,
             commercial_use, territory_json, account_scope_json, provider_use,
             reference_video_use, training_reference_use, voice_authorized,
             effective_at, expires_at, evidence_path, evidence_sha256, actor,
             reason, legal_hold, prior_event_id, created_at)
            VALUES (?, ?, ?, 'grant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, NULL, ?)
            """,
            (
                event_id,
                model["id"],
                authorization_id,
                scope,
                provider,
                int(commercial_use),
                json.dumps(sorted(set(territories or []))),
                json.dumps(sorted(set(account_scope or []))),
                int(provider_use),
                int(reference_video_use),
                int(training_reference_use),
                int(voice_authorized),
                _iso_time(effective),
                _iso_time(expiry) if expiry else None,
                str(path),
                actual_sha,
                actor,
                reason,
                int(legal_hold),
                now,
            ),
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_authorization_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        )

    def revoke_authorization(
        self,
        authorization_id: str,
        *,
        actor: str,
        reason: str,
        evidence_path: Path,
        evidence_sha256: str,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        grant = self.conn.execute(
            """
            SELECT * FROM creator_authorization_events
            WHERE authorization_id = ? AND event_type = 'grant'
            """,
            (authorization_id,),
        ).fetchone()
        if grant is None:
            raise ValueError("creator_authorization_grant_not_found")
        existing = self.conn.execute(
            """
            SELECT * FROM creator_authorization_events
            WHERE authorization_id = ? AND event_type = 'revoke'
            """,
            (authorization_id,),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        path = self._managed_evidence_file(evidence_path, "revocation_evidence")
        actual_sha = _file_sha256(path)
        if actual_sha != evidence_sha256:
            raise ValueError("authorization_evidence_sha256_mismatch")
        actor = _required(actor, "actor")
        reason = _required(reason, "reason")
        if validate_only:
            return {
                "schema": "campaign_factory.creator_authorization_revocation_plan.v1",
                "apply": False,
                "authorizationId": authorization_id,
                "creatorId": grant["model_id"],
                "grantEventId": grant["id"],
                "evidencePath": str(path),
                "evidenceSha256": actual_sha,
                "actor": actor,
                "reason": reason,
                "alreadyRevoked": False,
            }
        now = self._utc_now()
        event_id = self._new_id("creator_auth_event")
        self.conn.execute(
            """
            INSERT INTO creator_authorization_events
            (id, model_id, authorization_id, event_type, scope, provider,
             commercial_use, territory_json, account_scope_json, provider_use,
             reference_video_use, training_reference_use, voice_authorized,
             effective_at, expires_at, evidence_path, evidence_sha256, actor,
             reason, legal_hold, prior_event_id, created_at)
            VALUES (?, ?, ?, 'revoke', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?,
                    ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                grant["model_id"],
                authorization_id,
                grant["scope"],
                grant["provider"],
                grant["commercial_use"],
                grant["territory_json"],
                grant["account_scope_json"],
                grant["provider_use"],
                grant["reference_video_use"],
                grant["training_reference_use"],
                grant["voice_authorized"],
                now,
                str(path),
                actual_sha,
                actor,
                reason,
                grant["legal_hold"],
                grant["id"],
                now,
            ),
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM creator_authorization_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        )

    def campaign_status(self, campaign: str) -> dict[str, Any]:
        row = self._campaign_governance(campaign)
        return dict(row)

    def _campaign_governance(self, campaign: str) -> sqlite3.Row:
        key = _required(campaign, "campaign")
        slug = self._slugify(key)
        row = self.conn.execute(
            """
            SELECT cg.*, c.slug, c.name
            FROM campaign_governance cg
            JOIN campaigns c ON c.id = cg.campaign_id
            WHERE cg.campaign_id = ? OR lower(c.slug) = lower(?)
            LIMIT 1
            """,
            (key, slug),
        ).fetchone()
        if row is None:
            raise PermissionError("campaign_governance_missing")
        return row

    def transition_campaign(
        self,
        campaign: str,
        *,
        new_status: str,
        actor: str,
        reason: str,
        blocker_codes: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
        related_ids: list[str] | None = None,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        row = self._campaign_governance(campaign)
        target = _required(new_status, "new_status")
        actor = _required(actor, "actor")
        reason = _required(reason, "reason")
        current = str(row["lifecycle_status"])
        if target == current:
            return dict(row)
        if target not in CAMPAIGN_TRANSITIONS.get(current, set()):
            raise ValueError(f"illegal_campaign_transition:{current}->{target}")
        evidence = evidence or {}
        if target == "blocked" and (
            not blocker_codes or not str(evidence.get("repairAction") or "").strip()
        ):
            raise ValueError(
                "blocked campaign requires blocker_codes and evidence.repairAction"
            )
        if target in {"production_ready", "producing"}:
            creator_state = self.conn.execute(
                "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
                (row["model_id"],),
            ).fetchone()
            if creator_state is None or creator_state["status"] != "active":
                raise PermissionError("creator_inactive")
            identity = self.conn.execute(
                """
                SELECT * FROM creator_identity_profiles
                WHERE model_id = ? AND status = 'active' AND activated_at >= ?
                ORDER BY activated_at DESC, version DESC
                LIMIT 1
                """,
                (row["model_id"], creator_state["effective_at"]),
            ).fetchone()
            if identity is None:
                raise PermissionError("creator_identity_profile_missing")
            self._validate_identity_profile_bytes(identity)
            authorization_ids: list[str] = []
            for scope in _OPERATION_SCOPES["generation"]:
                grant = self._active_authorization(
                    model_id=str(row["model_id"]),
                    scope=scope,
                    provider="internal",
                    at=_parse_time(self._utc_now()),
                    not_before=_parse_time(str(creator_state["effective_at"])),
                )
                if grant is None:
                    raise PermissionError(f"creator_authorization_missing:{scope}")
                authorization_ids.append(str(grant["authorization_id"]))
            evidence = {
                **evidence,
                "identityProfileId": identity["id"],
                "identityProfileVersion": identity["version"],
                "authorizationIds": authorization_ids,
            }
        if target == "approved" and not evidence.get("approvedAssetIds"):
            raise ValueError("approved campaign requires evidence.approvedAssetIds")
        if target == "exporting" and not (
            evidence.get("exportBatchId") or evidence.get("approvedAssetIds")
        ):
            raise ValueError(
                "exporting campaign requires evidence.exportBatchId or approvedAssetIds"
            )
        now = self._utc_now()
        version = int(row["version"]) + 1
        ambiguous_rows = self.conn.execute(
            """
            SELECT id, attempt_id, authorization_id, external_operation_id
            FROM pipeline_jobs
            WHERE campaign_id = ?
              AND effect_state IN (
                'AUTHORIZATION_CONSUMED', 'SUBMISSION_STARTED',
                'EXTERNAL_ID_KNOWN', 'AMBIGUOUS', 'PROVIDER_COMPLETED',
                'OUTPUT_DOWNLOADED', 'OUTPUT_RETAINED', 'COST_RECONCILED',
                'EFFECT_CONFIRMED'
              )
            ORDER BY created_at, id
            """,
            (row["campaign_id"],),
        ).fetchall()
        related = set(related_ids or [])
        for job in ambiguous_rows:
            related.add(str(job["id"]))
            related.update(
                str(value)
                for value in (
                    job["attempt_id"],
                    job["authorization_id"],
                    job["external_operation_id"],
                )
                if value
            )
        if validate_only:
            pending_reservation_ids = [
                str(item[0])
                for item in self.conn.execute(
                    """
                    SELECT reservation_id FROM asset_inventory_reservations
                    WHERE campaign_id = ? AND status = 'pending'
                    ORDER BY reservation_id
                    """,
                    (row["campaign_id"],),
                ).fetchall()
            ]
            committed_reservation_ids = [
                str(item[0])
                for item in self.conn.execute(
                    """
                    SELECT reservation_id FROM asset_inventory_reservations
                    WHERE campaign_id = ? AND status = 'committed'
                    ORDER BY reservation_id
                    """,
                    (row["campaign_id"],),
                ).fetchall()
            ]
            return {
                "schema": "campaign_factory.campaign_transition_plan.v1",
                "apply": False,
                "campaign": row["slug"],
                "campaignId": row["campaign_id"],
                "creatorId": row["model_id"],
                "oldStatus": current,
                "newStatus": target,
                "actor": actor,
                "reason": reason,
                "blockerCodes": sorted(set(blocker_codes or [])),
                "evidence": evidence,
                "relatedIds": sorted(related),
                "pendingReservationsToRelease": pending_reservation_ids
                if target in {"paused", "cancelled", "completed", "archived"}
                else [],
                "committedReservationObligations": committed_reservation_ids
                if target in {"paused", "cancelled", "completed", "archived"}
                else [],
            }
        released: list[str] = []
        obligations: list[str] = []
        with self.conn:
            if target in {"paused", "cancelled", "completed", "archived"}:
                pending = self.conn.execute(
                    """
                    SELECT * FROM asset_inventory_reservations
                    WHERE campaign_id = ? AND status = 'pending'
                    """,
                    (row["campaign_id"],),
                ).fetchall()
                for reservation in pending:
                    self.conn.execute(
                        """
                        UPDATE asset_inventory_reservations
                        SET status = 'released', updated_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (now, reservation["id"]),
                    )
                    event = {
                        "reservationId": reservation["reservation_id"],
                        "campaignId": row["campaign_id"],
                        "status": "released",
                        "campaignTransition": target,
                    }
                    event_json = json.dumps(
                        event, sort_keys=True, separators=(",", ":")
                    )
                    event_sha = hashlib.sha256(event_json.encode()).hexdigest()
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_inventory_reservation_events
                        (id, reservation_row_id, reservation_id, event_type,
                         occurred_at, evidence_json, evidence_sha256)
                        VALUES (?, ?, ?, 'campaign_lifecycle_release', ?, ?, ?)
                        """,
                        (
                            f"invresevt_{event_sha[:24]}",
                            reservation["id"],
                            reservation["reservation_id"],
                            now,
                            event_json,
                            event_sha,
                        ),
                    )
                    released.append(str(reservation["reservation_id"]))
                obligations = [
                    str(item[0])
                    for item in self.conn.execute(
                        """
                        SELECT reservation_id FROM asset_inventory_reservations
                        WHERE campaign_id = ? AND status = 'committed'
                        ORDER BY reservation_id
                        """,
                        (row["campaign_id"],),
                    ).fetchall()
                ]
            transition_evidence = {
                **evidence,
                "releasedPendingReservationIds": released,
                "committedReservationCancellationObligations": obligations,
                "ambiguousExternalEffectJobIds": [
                    str(job["id"]) for job in ambiguous_rows
                ],
            }
            self.conn.execute(
                """
                INSERT INTO campaign_lifecycle_events
                (id, campaign_id, model_id, old_status, new_status, reason, actor,
                 evidence_json, related_ids_json, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._new_id("campaign_state"),
                    row["campaign_id"],
                    row["model_id"],
                    current,
                    target,
                    reason,
                    actor,
                    json.dumps(transition_evidence, sort_keys=True),
                    json.dumps(sorted(related)),
                    version,
                    now,
                ),
            )
            updated = self.conn.execute(
                """
                UPDATE campaign_governance
                SET lifecycle_status = ?, blocker_codes_json = ?,
                    status_reason = ?, changed_by = ?, effective_at = ?,
                    version = ?, updated_at = ?
                WHERE campaign_id = ? AND version = ?
                """,
                (
                    target,
                    json.dumps(sorted(set(blocker_codes or []))),
                    reason,
                    actor,
                    now,
                    version,
                    now,
                    row["campaign_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("campaign_transition_concurrent_update")
        return dict(
            self.conn.execute(
                "SELECT * FROM campaign_governance WHERE campaign_id = ?",
                (row["campaign_id"],),
            ).fetchone()
        )

    def resolve_operation(
        self,
        *,
        creator: str,
        campaign: str,
        operation: str,
        provider: str,
        source_asset_id: str | None = None,
        account_id: str | None = None,
        territory: str | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        model = self._model(creator)
        governance = self._campaign_governance(campaign)
        if str(governance["model_id"]) != str(model["id"]):
            raise PermissionError("campaign_creator_owner_mismatch")
        creator_state = self.conn.execute(
            "SELECT * FROM creator_lifecycle_state WHERE model_id = ?",
            (model["id"],),
        ).fetchone()
        if creator_state is None or creator_state["status"] != "active":
            raise PermissionError("creator_inactive")
        allowed_states = _OPERATION_CAMPAIGN_STATES.get(operation)
        if allowed_states is None:
            raise PermissionError(f"unknown_creator_operation:{operation}")
        if governance["lifecycle_status"] not in allowed_states:
            raise PermissionError(
                f"campaign_state_blocks_{operation}:{governance['lifecycle_status']}"
            )
        provider_filter = (
            "" if provider.lower() == "internal" else "AND provider IN (?, '*')"
        )
        identity_args: tuple[Any, ...] = (
            (model["id"], creator_state["effective_at"])
            if provider.lower() == "internal"
            else (
                model["id"],
                provider.lower(),
                creator_state["effective_at"],
                provider.lower(),
            )
        )
        identity_order = (
            "ORDER BY activated_at DESC"
            if provider.lower() == "internal"
            else "ORDER BY CASE WHEN provider = ? THEN 0 ELSE 1 END"
        )
        identity = self.conn.execute(
            """
            SELECT * FROM creator_identity_profiles
            WHERE model_id = ? """
            + provider_filter
            + """ AND status = 'active'
              AND activated_at >= ?
            """
            + identity_order
            + """
            LIMIT 1
            """,
            identity_args,
        ).fetchone()
        if identity is None:
            raise PermissionError("creator_identity_profile_missing")
        self._validate_identity_profile_bytes(identity)
        if source_asset_id:
            source = self.conn.execute(
                "SELECT model_id, campaign_id FROM source_assets WHERE id = ?",
                (source_asset_id,),
            ).fetchone()
            if (
                source is None
                or source["model_id"] != model["id"]
                or source["campaign_id"] != governance["campaign_id"]
            ):
                raise PermissionError("cross_creator_source_blocked")
        account = None
        if account_id:
            account = self.conn.execute(
                """
                SELECT id, external_id, model_id
                FROM accounts
                WHERE id = ? OR external_id = ? OR handle = ?
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (account_id, account_id, account_id, account_id),
            ).fetchone()
            if account is None or account["model_id"] != model["id"]:
                raise PermissionError("cross_creator_account_blocked")
        timestamp = _parse_time(at or self._utc_now())
        grants = []
        for scope in _OPERATION_SCOPES.get(operation, ()):
            grant = self._active_authorization(
                model_id=str(model["id"]),
                scope=scope,
                provider=provider,
                at=timestamp,
                not_before=_parse_time(str(creator_state["effective_at"])),
            )
            if grant is None:
                raise PermissionError(f"creator_authorization_missing:{scope}")
            allowed_accounts = set(json.loads(grant["account_scope_json"] or "[]"))
            resolved_account_ids = {
                str(value)
                for value in (
                    account_id,
                    account["id"] if account is not None else None,
                    account["external_id"] if account is not None else None,
                )
                if value
            }
            if allowed_accounts and (
                not resolved_account_ids.intersection(allowed_accounts)
            ):
                raise PermissionError(f"creator_authorization_account_scope:{scope}")
            allowed_territories = {
                str(item).casefold()
                for item in json.loads(grant["territory_json"] or "[]")
            }
            if allowed_territories and (
                territory is None or territory.casefold() not in allowed_territories
            ):
                raise PermissionError(f"creator_authorization_territory:{scope}")
            grants.append(grant)
        context = {
            "schema": "campaign_factory.creator_operation_context.v1",
            "creatorId": model["id"],
            "creatorSlug": model["slug"],
            "creatorLifecycleVersion": creator_state["version"],
            "campaignId": governance["campaign_id"],
            "campaignSlug": governance["slug"],
            "campaignLifecycleVersion": governance["version"],
            "campaignStatus": governance["lifecycle_status"],
            "operation": operation,
            "provider": provider.lower(),
            "accountId": account["id"] if account is not None else None,
            "territory": territory,
            "sourceAssetId": source_asset_id,
            "identityProfileId": identity["id"],
            "identityProfileVersion": identity["version"],
            "identityProfileFingerprint": identity["profile_fingerprint"],
            "providerIdentityId": identity["provider_identity_id"],
            "authorizationEventIds": [grant["id"] for grant in grants],
            "authorizationIds": [grant["authorization_id"] for grant in grants],
            "resolvedAt": at or self._utc_now(),
        }
        context["governanceFingerprint"] = _canonical_sha256(
            {key: value for key, value in context.items() if key != "resolvedAt"}
        )
        return context

    def _active_authorization(
        self,
        *,
        model_id: str,
        scope: str,
        provider: str,
        at: datetime,
        not_before: datetime,
    ) -> sqlite3.Row | None:
        rows = self.conn.execute(
            """
            SELECT grant.*
            FROM creator_authorization_events grant
            LEFT JOIN creator_authorization_events revoke
              ON revoke.authorization_id = grant.authorization_id
             AND revoke.event_type = 'revoke'
            WHERE grant.model_id = ?
              AND grant.event_type = 'grant'
              AND grant.scope = ?
              AND grant.provider IN (?, '*')
              AND grant.provider_use = 1
              AND revoke.id IS NULL
            ORDER BY grant.created_at DESC
            """,
            (model_id, scope, provider.lower()),
        ).fetchall()
        for row in rows:
            if _parse_time(str(row["effective_at"])) > at:
                continue
            if _parse_time(str(row["created_at"])) < not_before:
                continue
            if row["expires_at"] and _parse_time(str(row["expires_at"])) <= at:
                continue
            if scope == "commercial_use" and not row["commercial_use"]:
                continue
            if scope == "reference_video_use" and not row["reference_video_use"]:
                continue
            if scope == "voice_use" and not row["voice_authorized"]:
                continue
            evidence_path = Path(str(row["evidence_path"]))
            if (
                evidence_path.is_symlink()
                or not evidence_path.is_file()
                or _file_sha256(evidence_path) != row["evidence_sha256"]
            ):
                raise PermissionError(f"creator_authorization_evidence_stale:{scope}")
            return row
        return None
