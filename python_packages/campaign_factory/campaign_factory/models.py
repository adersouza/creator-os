from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .artifact_storage import campaign_dirs
from .config import Settings
from .persistence import json_load


class ModelRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        ensure_graph_node: Callable[..., str],
        record_event: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._slugify = slugify
        self._utc_now = utc_now
        self._ensure_graph_node = ensure_graph_node
        self._record_event = record_event

    def _ensure_model_governance(self, model_id: str, slug: str, now: str) -> None:
        existing = self.conn.execute(
            "SELECT 1 FROM creator_lifecycle_state WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        if existing is None:
            event_id = self._new_id("creator_state")
            self.conn.execute(
                """
                INSERT INTO creator_lifecycle_state
                (model_id, status, status_reason, effective_at, changed_by,
                 version, offboarding_state, retention_state, updated_at)
                VALUES (?, 'active', 'creator_onboarded', ?, 'campaign_factory',
                        1, NULL, 'retain_audit', ?)
                """,
                (model_id, now, now),
            )
            self.conn.execute(
                """
                INSERT INTO creator_lifecycle_events
                (id, model_id, old_status, new_status, reason, actor,
                 effective_at, evidence_json, version, created_at)
                VALUES (?, ?, NULL, 'active', 'creator_onboarded',
                        'campaign_factory', ?, '{}', 1, ?)
                """,
                (event_id, model_id, now, now),
            )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO creator_slug_history
            (id, model_id, slug, effective_at, retired_at, actor, reason, created_at)
            VALUES (?, ?, ?, ?, NULL, 'campaign_factory', 'creator_onboarded', ?)
            """,
            (self._new_id("creator_slug"), model_id, slug, now, now),
        )

    def _ensure_campaign_governance(
        self, campaign_id: str, model_id: str, now: str
    ) -> None:
        governance = self.conn.execute(
            "SELECT model_id FROM campaign_governance WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if governance is not None:
            if str(governance["model_id"]) != model_id:
                raise PermissionError("campaign_creator_owner_mismatch")
            return
        source_models = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT DISTINCT model_id FROM source_assets WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
            if row[0]
        }
        if len(source_models) > 1:
            raise PermissionError("legacy_campaign_mixed_creator_ownership")
        if source_models and model_id not in source_models:
            raise PermissionError("campaign_creator_owner_mismatch")
        event_id = self._new_id("campaign_state")
        self.conn.execute(
            """
            INSERT INTO campaign_governance
            (campaign_id, model_id, lifecycle_status, blocker_codes_json,
             status_reason, changed_by, effective_at, version, updated_at)
            VALUES (?, ?, 'created', '[]', 'campaign_created',
                    'campaign_factory', ?, 1, ?)
            """,
            (campaign_id, model_id, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO campaign_lifecycle_events
            (id, campaign_id, model_id, old_status, new_status, reason, actor,
             evidence_json, related_ids_json, version, created_at)
            VALUES (?, ?, ?, NULL, 'created', 'campaign_created',
                    'campaign_factory', '{}', '[]', 1, ?)
            """,
            (event_id, campaign_id, model_id, now),
        )

    def _campaign_dirs(self, model_slug: str, campaign_slug: str) -> dict[str, Path]:
        return campaign_dirs(self.settings.campaigns_dir, model_slug, campaign_slug)

    def upsert_model(
        self, slug: str, name: str | None = None, notes: str | None = None
    ) -> dict[str, Any]:
        slug = self._slugify(slug)
        now = self._utc_now()
        row = self.conn.execute(
            """
            SELECT m.*
            FROM models m
            LEFT JOIN creator_slug_history h ON h.model_id = m.id
            WHERE m.slug = ? OR h.slug = ?
            ORDER BY CASE WHEN m.slug = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (slug, slug, slug),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE models SET name = ?, notes = COALESCE(?, notes), updated_at = ? WHERE id = ?",
                (name or row["name"], notes, now, row["id"]),
            )
            self._ensure_graph_node(
                "model",
                local_table="models",
                local_id=row["id"],
                payload={"slug": row["slug"], "name": name or row["name"]},
            )
            self._ensure_model_governance(str(row["id"]), slug, now)
            self.conn.commit()
            return dict(
                self.conn.execute(
                    "SELECT * FROM models WHERE id = ?", (row["id"],)
                ).fetchone()
            )
        model_id = self._new_id("model")
        self.conn.execute(
            "INSERT INTO models (id, slug, name, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (model_id, slug, name or slug.replace("_", " ").title(), notes, now, now),
        )
        self._ensure_graph_node(
            "model",
            local_table="models",
            local_id=model_id,
            payload={"slug": slug, "name": name or slug.replace("_", " ").title()},
        )
        self._ensure_model_governance(model_id, slug, now)
        self.conn.commit()
        model = dict(
            self.conn.execute(
                "SELECT * FROM models WHERE id = ?", (model_id,)
            ).fetchone()
        )
        self._record_event(
            "model_created",
            status="success",
            message=f"Model created: {model['slug']}",
            metadata={
                "modelId": model["id"],
                "slug": model["slug"],
                "name": model["name"],
            },
        )
        return model

    def upsert_campaign(
        self,
        slug: str,
        model_slug: str,
        name: str | None = None,
        platform: str = "instagram",
    ) -> dict[str, Any]:
        slug = self._slugify(slug)
        model_slug = self._slugify(model_slug)
        now = self._utc_now()
        row = self.conn.execute(
            "SELECT * FROM campaigns WHERE slug = ?", (slug,)
        ).fetchone()
        if row:
            owner = self.conn.execute(
                """
                SELECT m.slug
                FROM campaign_governance cg
                JOIN models m ON m.id = cg.model_id
                WHERE cg.campaign_id = ?
                """,
                (row["id"],),
            ).fetchone()
            if owner is None:
                raise PermissionError("legacy_campaign_creator_owner_unresolved")
            if owner is not None and str(owner["slug"]) != model_slug:
                raise PermissionError("campaign_creator_owner_mismatch")
        model = self.upsert_model(model_slug)
        if row:
            self._ensure_campaign_governance(str(row["id"]), str(model["id"]), now)
        dirs = self._campaign_dirs(model_slug, slug)
        if row:
            self.conn.execute(
                "UPDATE campaigns SET name = ?, platform = ?, root_path = ?, updated_at = ? WHERE id = ?",
                (name or row["name"], platform, str(dirs["root"]), now, row["id"]),
            )
            self._ensure_graph_node(
                "campaign",
                local_table="campaigns",
                local_id=row["id"],
                payload={"slug": slug, "platform": platform},
            )
            self.conn.commit()
            return dict(
                self.conn.execute(
                    "SELECT * FROM campaigns WHERE id = ?", (row["id"],)
                ).fetchone()
            )
        campaign_id = self._new_id("camp")
        self.conn.execute(
            "INSERT INTO campaigns (id, slug, name, platform, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                slug,
                name or slug.replace("_", " ").title(),
                platform,
                str(dirs["root"]),
                now,
                now,
            ),
        )
        self._ensure_graph_node(
            "campaign",
            local_table="campaigns",
            local_id=campaign_id,
            payload={"slug": slug, "platform": platform},
        )
        self._ensure_campaign_governance(campaign_id, str(model["id"]), now)
        self.conn.commit()
        campaign = dict(
            self.conn.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        )
        self._record_event(
            "campaign_created",
            campaign_id=campaign["id"],
            status="success",
            message=f"Campaign created: {campaign['slug']}",
            metadata={
                "campaignId": campaign["id"],
                "slug": campaign["slug"],
                "platform": campaign["platform"],
            },
        )
        return campaign

    def upsert_account(
        self,
        handle: str,
        platform: str = "instagram",
        external_id: str | None = None,
        model_id: str | None = None,
        account_group_id: str | None = None,
    ) -> dict[str, Any]:
        handle = handle.strip().lstrip("@")
        now = self._utc_now()
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE handle = ? AND platform = ?",
            (handle, platform),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE accounts SET external_id = COALESCE(?, external_id), model_id = COALESCE(?, model_id), account_group_id = COALESCE(?, account_group_id), updated_at = ? WHERE id = ?",
                (external_id, model_id, account_group_id, now, row["id"]),
            )
            self._ensure_graph_node(
                "account",
                local_table="accounts",
                local_id=row["id"],
                payload={"handle": handle, "platform": platform},
            )
            self.conn.commit()
            return dict(
                self.conn.execute(
                    "SELECT * FROM accounts WHERE id = ?", (row["id"],)
                ).fetchone()
            )
        account_id = self._new_id("acct")
        self.conn.execute(
            "INSERT INTO accounts (id, handle, platform, external_id, model_id, account_group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account_id,
                handle,
                platform,
                external_id,
                model_id,
                account_group_id,
                now,
                now,
            ),
        )
        self._ensure_graph_node(
            "account",
            local_table="accounts",
            local_id=account_id,
            payload={"handle": handle, "platform": platform},
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        )

    def project_instagram_trial_capability(
        self,
        account_id: str,
        *,
        capability: str,
        oauth_granted_scopes: list[str] | None,
        oauth_scopes_verified_at: str | None,
        checked_at: str | None,
        reason: str | None,
        projection_observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper for callers projecting only Trial evidence."""
        return self.project_instagram_account_evidence(
            account_id,
            capability=capability,
            oauth_granted_scopes=oauth_granted_scopes,
            oauth_scopes_verified_at=oauth_scopes_verified_at,
            checked_at=checked_at,
            reason=reason,
            projection_observed_at=projection_observed_at,
        )

    def project_instagram_account_evidence(
        self,
        account_id: str,
        *,
        capability: str,
        oauth_granted_scopes: list[str] | None,
        oauth_scopes_verified_at: str | None,
        checked_at: str | None,
        reason: str | None,
        is_active: bool | None = None,
        status: str | None = None,
        needs_reauth: bool | None = None,
        sync_cohort: str | None = None,
        projection_observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist ThreadsDashboard account, OAuth, and Trial facts exactly."""
        normalized_capability = str(capability or "unknown").strip().lower()
        if normalized_capability not in {"unknown", "eligible", "denied"}:
            raise ValueError(
                "trial_reels_capability must be unknown, eligible, or denied"
            )
        scopes_json = None
        if oauth_granted_scopes is not None:
            normalized_scopes = sorted(
                {
                    str(scope).strip()
                    for scope in oauth_granted_scopes
                    if str(scope).strip()
                }
            )
            scopes_json = json.dumps(normalized_scopes, ensure_ascii=False)
        now = self._utc_now()
        cursor = self.conn.execute(
            """
            UPDATE accounts
            SET oauth_granted_scopes_json = ?, oauth_scopes_verified_at = ?,
                trial_reels_capability = ?,
                trial_reels_capability_checked_at = ?,
                trial_reels_capability_reason = ?,
                threadsdash_is_active = COALESCE(?, threadsdash_is_active),
                threadsdash_status = COALESCE(?, threadsdash_status),
                threadsdash_needs_reauth = COALESCE(?, threadsdash_needs_reauth),
                threadsdash_sync_cohort = COALESCE(?, threadsdash_sync_cohort),
                threadsdash_projection_observed_at = COALESCE(
                    ?, threadsdash_projection_observed_at
                ),
                updated_at = ?
            WHERE id = ?
            """,
            (
                scopes_json,
                oauth_scopes_verified_at,
                normalized_capability,
                checked_at,
                reason,
                None if is_active is None else int(is_active),
                str(status).strip().lower() if status is not None else None,
                None if needs_reauth is None else int(needs_reauth),
                sync_cohort,
                projection_observed_at,
                now,
                account_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"account not found: {account_id}")
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        )

    def upsert_model_account_profile(
        self,
        model_slug: str,
        *,
        label: str | None = None,
        allowed_instagram_account_ids: list[str] | None = None,
        allowed_account_group_names: list[str] | None = None,
        allowed_handle_patterns: list[str] | None = None,
        default_smart_link: str | None = None,
        story_cta_text: str | None = None,
    ) -> dict[str, Any]:
        model = self.upsert_model(model_slug)
        now = self._utc_now()
        payload = {
            "label": label or model["name"],
            "allowed_instagram_account_ids_json": json.dumps(
                sorted(set(allowed_instagram_account_ids or []))
            ),
            "allowed_account_group_names_json": json.dumps(
                sorted(set(allowed_account_group_names or []))
            ),
            "allowed_handle_patterns_json": json.dumps(
                sorted(set(allowed_handle_patterns or []))
            ),
            "default_smart_link": default_smart_link,
            "story_cta_text": story_cta_text,
        }
        row = self.conn.execute(
            "SELECT * FROM model_account_profiles WHERE model_slug = ?",
            (model["slug"],),
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE model_account_profiles
                SET model_id = ?, label = ?, allowed_instagram_account_ids_json = ?,
                    allowed_account_group_names_json = ?, allowed_handle_patterns_json = ?,
                    default_smart_link = ?, story_cta_text = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    model["id"],
                    payload["label"],
                    payload["allowed_instagram_account_ids_json"],
                    payload["allowed_account_group_names_json"],
                    payload["allowed_handle_patterns_json"],
                    payload["default_smart_link"],
                    payload["story_cta_text"],
                    now,
                    row["id"],
                ),
            )
            self.conn.commit()
            return self.model_account_profile(model["slug"]) or {}
        profile_id = self._new_id("profile")
        self.conn.execute(
            """
            INSERT INTO model_account_profiles
            (id, model_id, model_slug, label, allowed_instagram_account_ids_json,
             allowed_account_group_names_json, allowed_handle_patterns_json, default_smart_link,
             story_cta_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                model["id"],
                model["slug"],
                payload["label"],
                payload["allowed_instagram_account_ids_json"],
                payload["allowed_account_group_names_json"],
                payload["allowed_handle_patterns_json"],
                payload["default_smart_link"],
                payload["story_cta_text"],
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.model_account_profile(model["slug"]) or {}

    def model_account_profile(self, model_slug: str) -> dict[str, Any] | None:
        slug = self._slugify(model_slug)
        row = self.conn.execute(
            "SELECT * FROM model_account_profiles WHERE model_slug = ?", (slug,)
        ).fetchone()
        return self._model_account_profile_payload(dict(row)) if row else None

    def _model_account_profile_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "modelId": row["model_id"],
            "modelSlug": row["model_slug"],
            "label": row["label"],
            "allowedInstagramAccountIds": json_load(
                row["allowed_instagram_account_ids_json"], []
            ),
            "allowedAccountGroupNames": json_load(
                row["allowed_account_group_names_json"], []
            ),
            "allowedHandlePatterns": json_load(row["allowed_handle_patterns_json"], []),
            "defaultSmartLink": row["default_smart_link"],
            "storyCtaText": row["story_cta_text"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def account_compatible_with_model(
        self,
        model_slug: str,
        *,
        instagram_account_id: str | None = None,
        account_handle: str | None = None,
        account_group_name: str | None = None,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        profile = self.model_account_profile(model_slug)
        if not profile:
            return False, "model_account_profile_missing", None
        allowed_ids = set(profile.get("allowedInstagramAccountIds") or [])
        if instagram_account_id and allowed_ids:
            return (
                instagram_account_id in allowed_ids,
                None
                if instagram_account_id in allowed_ids
                else "model_account_mismatch",
                profile,
            )
        allowed_groups = {
            str(item).lower() for item in profile.get("allowedAccountGroupNames") or []
        }
        if account_group_name and allowed_groups:
            ok = account_group_name.lower() in allowed_groups
            return ok, None if ok else "model_account_group_mismatch", profile
        handle = (account_handle or "").lower()
        patterns = [
            str(item).lower() for item in profile.get("allowedHandlePatterns") or []
        ]
        if handle and patterns:
            ok = any(pattern in handle for pattern in patterns)
            return ok, None if ok else "model_account_handle_mismatch", profile
        return False, "model_account_identity_unproven", profile
