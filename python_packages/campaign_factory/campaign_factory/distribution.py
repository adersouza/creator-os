from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from typing import Any
from zoneinfo import ZoneInfo

from .account_eligibility import (
    enforce_account_eligibility,
    evaluate_account_eligibility,
)
from .assignment_eligibility import (
    enforce_assignment_eligibility,
    persist_assignment_origin,
)
from .caption_outcome import column_values, load_context_json
from .persistence import json_load


def _normalize_distribution_surface(value: str | None) -> str:
    normalized = (value or "regular_reel").strip().lower().replace("-", "_")
    aliases = {
        "reel": "regular_reel",
        "regular": "regular_reel",
        "ig_reel": "regular_reel",
        "trial": "trial_reel",
        "trial_reels": "trial_reel",
        "stories": "story",
        "ig_story": "story",
        "cta_story": "story_cta",
        "single_image": "feed_single",
        "feed_image": "feed_single",
        "feed_single_image": "feed_single",
        "carousel": "feed_carousel",
        "carousel_album": "feed_carousel",
    }
    normalized = aliases.get(normalized, normalized)
    return (
        normalized
        if normalized
        in {
            "regular_reel",
            "trial_reel",
            "story",
            "story_cta",
            "feed_single",
            "feed_carousel",
        }
        else "regular_reel"
    )


def _normalize_schedule_mode(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "draft"
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized not in {"draft", "preview", "live"}:
        raise ValueError(
            f"unknown schedule mode {value!r}; expected draft, preview, or live"
        )
    return normalized


def _parse_distribution_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


TRIAL_GRADUATION_STRATEGIES = {"MANUAL", "SS_PERFORMANCE"}


class DistributionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        normalize_content_surface: Callable[[str | None], str],
        rendered_asset: Callable[[str], dict[str, Any]],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[..., dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        ig_media_type_for_surface: Callable[[str, str], str],
        variant_lineage_for_asset: Callable[[str], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        dashboard: Callable[[str], dict[str, Any]],
        model_account_profile: Callable[[str], dict[str, Any] | None],
        account_compatible_with_model: Callable[
            ..., tuple[bool, str | None, dict[str, Any] | None]
        ],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self._normalize_content_surface = normalize_content_surface
        self._rendered_asset = rendered_asset
        self._campaign_by_slug = campaign_by_slug
        self._record_event = record_event
        self._create_pipeline_job = create_pipeline_job
        self._start_pipeline_job = start_pipeline_job
        self._finish_pipeline_job = finish_pipeline_job
        self._fail_pipeline_job = fail_pipeline_job
        self._rendered_for_campaign = rendered_for_campaign
        self._dashboard_rendered_asset = dashboard_rendered_asset
        self._ig_media_type_for_surface = ig_media_type_for_surface
        self._variant_lineage_for_asset = variant_lineage_for_asset
        self._ranking = ranking
        self._dashboard = dashboard
        self._model_account_profile = model_account_profile
        self._account_compatible_with_model = account_compatible_with_model

    def create_distribution_plan(
        self,
        rendered_asset_id: str,
        *,
        surface: str = "regular_reel",
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        paired_rendered_asset_id: str | None = None,
        reason_code: str | None = None,
        smart_link: str | None = None,
        cta_text: str | None = None,
        instagram_trial_reels: bool = False,
        trial_graduation_strategy: str | None = None,
        trial_group_id: str | None = None,
        trial_capability_authorization: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        asset = self._rendered_asset(rendered_asset_id)
        now = self._utc_now()
        plan_id = self._new_id("dist")
        distribution_surface = _normalize_distribution_surface(surface)
        asset_content_surface = self._normalize_content_surface(
            asset.get("content_surface")
        )
        content_surface = self._normalize_content_surface(surface)
        if distribution_surface in {"regular_reel", "trial_reel"}:
            content_surface = "reel"
        if instagram_trial_reels and asset_content_surface != "reel":
            raise ValueError("Instagram Trial Reels require reel content")
        normalized_strategy = self.validate_instagram_trial_reel_intent(
            content_surface=content_surface,
            distribution_surface=distribution_surface,
            media_type=str(asset.get("media_type") or "video"),
            instagram_trial_reels=instagram_trial_reels,
            trial_graduation_strategy=trial_graduation_strategy,
        )
        self._ensure_default_reel_cadence(
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            now=now,
        )
        account_eligibility = enforce_account_eligibility(
            self.conn,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            surface=distribution_surface,
            requires_trial_capability=instagram_trial_reels,
            authorization=trial_capability_authorization,
            planned_at=planned_window_start,
        )
        capability_decision = None
        if instagram_trial_reels:
            capability_decision = self._trial_capability_payload(account_eligibility)
        elif trial_capability_authorization:
            raise ValueError(
                "trial_capability_authorization requires instagram_trial_reels=true"
            )
        existing = self.conn.execute(
            """
            SELECT id FROM distribution_plans
            WHERE rendered_asset_id = ? AND surface = ?
              AND COALESCE(account_id, '') = COALESCE(?, '')
              AND COALESCE(instagram_account_id, '') = COALESCE(?, '')
              AND COALESCE(planned_window_start, '') = COALESCE(?, '')
            """,
            (
                rendered_asset_id,
                distribution_surface,
                account_id,
                instagram_account_id,
                planned_window_start,
            ),
        ).fetchone()
        if existing:
            return self.distribution_plan(existing["id"]) or {}
        eligibility = enforce_assignment_eligibility(
            self.conn,
            rendered_asset_id=rendered_asset_id,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_at=planned_window_start,
            surface=distribution_surface,
        )
        identity = eligibility["inputs"]
        caption_columns = column_values(
            load_context_json(asset.get("caption_outcome_context_json"))
        )
        variant_lineage = self._variant_lineage_for_asset(rendered_asset_id)
        self.conn.execute(
            """
            INSERT INTO distribution_plans
            (id, campaign_id, rendered_asset_id, account_id, instagram_account_id,
             source_family_id, perceptual_fingerprint, perceptual_cluster_id, account_group_id,
             account_eligibility_json, assignment_eligibility_json, surface, content_surface,
             concept_id, parent_reel_id, variant_family_id, variant_id, variant_index,
             variant_operations_json,
             planned_window_start, planned_window_end, paired_rendered_asset_id, reason_code,
             smart_link, cta_text, instagram_trial_reels, trial_graduation_strategy, trial_group_id,
             trial_capability_status, trial_capability_checked_at,
             trial_capability_reason, trial_capability_authorization,
             caption_hash, caption_text, caption_bank, caption_banks_json,
             creator_mix, creator_model, frame_type, length_class, format_class, caption_fit_version,
             suitability_decision, suitability_reason, source_clip, caption_outcome_context_json,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                asset["campaign_id"],
                rendered_asset_id,
                account_id,
                instagram_account_id,
                identity["sourceFamilyId"],
                identity["perceptualFingerprint"],
                identity["perceptualClusterId"],
                identity["accountGroupId"],
                json.dumps(account_eligibility, ensure_ascii=False, sort_keys=True),
                json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                distribution_surface,
                content_surface,
                variant_lineage.get("concept_id"),
                variant_lineage.get("parent_reel_id"),
                variant_lineage.get("variant_family_id"),
                variant_lineage.get("variant_id"),
                variant_lineage.get("variant_index"),
                json.dumps(
                    self._sanitize_for_storage(
                        variant_lineage.get("variant_operations") or []
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                planned_window_start,
                planned_window_end,
                paired_rendered_asset_id,
                reason_code,
                smart_link,
                cta_text,
                1 if instagram_trial_reels else 0,
                normalized_strategy,
                trial_group_id,
                (capability_decision or {}).get("status"),
                (capability_decision or {}).get("checkedAt"),
                (capability_decision or {}).get("reason"),
                (capability_decision or {}).get("authorization"),
                caption_columns["caption_hash"],
                caption_columns["caption_text"],
                caption_columns["caption_bank"],
                caption_columns["caption_banks_json"],
                caption_columns["creator_mix"],
                caption_columns["creator_model"],
                caption_columns["frame_type"],
                caption_columns["length_class"],
                caption_columns["format_class"],
                caption_columns["caption_fit_version"],
                caption_columns["suitability_decision"],
                caption_columns["suitability_reason"],
                caption_columns["source_clip"],
                caption_columns["caption_outcome_context_json"],
                now,
                now,
            ),
        )
        persist_assignment_origin(self.conn, eligibility)
        self._record_event(
            "distribution_plan_created",
            campaign_id=asset["campaign_id"],
            source_asset_id=asset["source_asset_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message=f"Distribution plan created: {distribution_surface}",
            metadata={
                "distributionPlanId": plan_id,
                "surface": distribution_surface,
                "accountId": account_id,
                "instagramAccountId": instagram_account_id,
                "pairedRenderedAssetId": paired_rendered_asset_id,
                "reasonCode": reason_code,
                "instagramTrialReels": bool(instagram_trial_reels),
                "trialGraduationStrategy": normalized_strategy,
                "trialGroupId": trial_group_id,
                "trialCapability": capability_decision,
                "accountEligibility": account_eligibility,
            },
            commit=False,
        )
        if commit:
            self.conn.commit()
        return self.distribution_plan(plan_id) or {}

    def _ensure_default_reel_cadence(
        self,
        *,
        account_id: str | None,
        instagram_account_id: str | None,
        now: str,
    ) -> None:
        row = None
        if account_id:
            row = self.conn.execute(
                "SELECT id, handle FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        if not row and instagram_account_id:
            row = self.conn.execute(
                "SELECT id, handle FROM accounts WHERE external_id = ?",
                (instagram_account_id,),
            ).fetchone()
        if not row:
            return
        self.conn.execute(
            """
            INSERT OR IGNORE INTO account_content_requirements
            (id, account_id, creator, content_surface, cadence, max_per_day,
             min_gap_hours, main_reels_per_day, trial_reels_per_day,
             allowed_days, active, created_at, updated_at)
            VALUES (?, ?, ?, 'reel', 'daily', 3, 4, 1, 2, '[]', 1, ?, ?)
            """,
            (self._new_id("requirement"), row["id"], row["handle"], now, now),
        )

    def validate_instagram_trial_reel_intent(
        self,
        *,
        content_surface: str,
        distribution_surface: str,
        media_type: str,
        instagram_trial_reels: bool,
        trial_graduation_strategy: str | None,
    ) -> str | None:
        strategy = (trial_graduation_strategy or "").strip().upper() or None
        if not instagram_trial_reels:
            if strategy:
                raise ValueError(
                    "trial_graduation_strategy requires instagram_trial_reels=true"
                )
            return None
        if content_surface != "reel":
            raise ValueError("Instagram Trial Reels require reel content")
        ig_media_type = self._ig_media_type_for_surface(content_surface, media_type)
        if ig_media_type != "REELS":
            raise ValueError("Instagram Trial Reels require ig_media_type=REELS")
        if not strategy:
            raise ValueError(
                "trial_graduation_strategy is required for Instagram Trial Reels"
            )
        if strategy not in TRIAL_GRADUATION_STRATEGIES:
            allowed = ", ".join(sorted(TRIAL_GRADUATION_STRATEGIES))
            raise ValueError(f"trial_graduation_strategy must be one of: {allowed}")
        return strategy

    def trial_reel_account_eligibility(
        self,
        *,
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        decision = evaluate_account_eligibility(
            self.conn,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            surface="trial_reel",
            requires_trial_capability=True,
            authorization=authorization,
        )
        return self._trial_capability_payload(decision)

    @staticmethod
    def _trial_capability_payload(decision: dict[str, Any]) -> dict[str, Any]:
        account = decision["account"]
        trial = decision["trial"]
        oauth = decision["oauth"]
        return {
            "accountId": account["accountId"],
            "instagramAccountId": account["instagramAccountId"],
            "status": trial["capability"],
            "checkedAt": trial["checkedAt"],
            "reason": trial["reason"],
            "oauthGrantedScopes": oauth["grantedScopes"],
            "oauthScopesVerifiedAt": oauth["verifiedAt"],
            "authorization": trial["authorization"],
            "allowed": decision["allowed"],
            "decisionReason": decision["decisionReason"],
            "operatorAction": decision["operatorAction"],
        }

    def distribution_plan(self, plan_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM distribution_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return self.distribution_plan_payload(dict(row)) if row else None

    def distribution_plans_for_asset(
        self, rendered_asset_id: str
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM distribution_plans WHERE rendered_asset_id = ? ORDER BY created_at",
            (rendered_asset_id,),
        ).fetchall()
        return [self.distribution_plan_payload(dict(row)) for row in rows]

    def distribution_plans_for_campaign(
        self, campaign_slug: str
    ) -> list[dict[str, Any]]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            "SELECT * FROM distribution_plans WHERE campaign_id = ? ORDER BY created_at",
            (campaign["id"],),
        ).fetchall()
        return [self.distribution_plan_payload(dict(row)) for row in rows]

    def clear_distribution_plans_for_campaign(
        self, campaign_slug: str, *, commit: bool = True
    ) -> int:
        campaign = self._campaign_by_slug(campaign_slug)
        count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM distribution_plans WHERE campaign_id = ?",
            (campaign["id"],),
        ).fetchone()["count"]
        self.conn.execute(
            "DELETE FROM distribution_plans WHERE campaign_id = ?", (campaign["id"],)
        )
        self._record_event(
            "distribution_plans_cleared",
            campaign_id=campaign["id"],
            status="info",
            message=f"Cleared {count} distribution plan rows",
            metadata={"campaign": campaign_slug, "cleared": count},
            commit=False,
        )
        if commit:
            self.conn.commit()
        return int(count or 0)

    def distribution_plan_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaignId": row["campaign_id"],
            "renderedAssetId": row["rendered_asset_id"],
            "accountId": row["account_id"],
            "instagramAccountId": row["instagram_account_id"],
            "surface": row["surface"],
            "contentSurface": row.get("content_surface")
            or self._normalize_content_surface(row["surface"]),
            "plannedWindowStart": row["planned_window_start"],
            "plannedWindowEnd": row["planned_window_end"],
            "pairedRenderedAssetId": row["paired_rendered_asset_id"],
            "reasonCode": row["reason_code"],
            "smartLink": row["smart_link"],
            "ctaText": row["cta_text"],
            "instagramTrialReels": bool(row.get("instagram_trial_reels")),
            "instagram_trial_reels": bool(row.get("instagram_trial_reels")),
            "trialGraduationStrategy": row.get("trial_graduation_strategy"),
            "trial_graduation_strategy": row.get("trial_graduation_strategy"),
            "trialCapability": (
                {
                    "status": row.get("trial_capability_status"),
                    "checkedAt": row.get("trial_capability_checked_at"),
                    "reason": row.get("trial_capability_reason"),
                    "authorization": row.get("trial_capability_authorization"),
                }
                if row.get("instagram_trial_reels")
                else None
            ),
            "accountEligibility": json_load(row.get("account_eligibility_json"), {}),
            **(
                {
                    "trialGroupId": row.get("trial_group_id"),
                    "trial_group_id": row.get("trial_group_id"),
                }
                if row.get("trial_group_id")
                else {}
            ),
            "conceptId": row.get("concept_id"),
            "parentReelId": row.get("parent_reel_id"),
            "variantFamilyId": row.get("variant_family_id"),
            "variantId": row.get("variant_id"),
            "variantIndex": row.get("variant_index"),
            "variantOperations": json_load(row.get("variant_operations_json"), []),
            "captionOutcomeContext": load_context_json(
                row.get("caption_outcome_context_json")
            ),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def plan_distribution(
        self,
        campaign_slug: str,
        *,
        user_id: str,
        mode: str = "preview",
        strategy: str = "trial-heavy",
        replace: bool = True,
        fallback_hours: list[int] | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        schedule_mode = _normalize_schedule_mode(mode)
        normalized_strategy = (
            (strategy or "trial-heavy").strip().lower().replace("_", "-")
        )
        if normalized_strategy not in {"trial-heavy"}:
            raise ValueError("only trial-heavy distribution strategy is supported")
        pipeline_job = self._create_pipeline_job(
            "distribution_plan",
            campaign["id"],
            {
                "campaign": campaign_slug,
                "userId": user_id,
                "mode": schedule_mode,
                "strategy": normalized_strategy,
                "replace": replace,
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        try:
            cleared = (
                self.clear_distribution_plans_for_campaign(campaign_slug, commit=False)
                if replace
                else 0
            )
            ranking = self._ranking(campaign_slug)
            ranking_by_asset = ranking.get("byAsset") or {}
            dashboard = self._dashboard(campaign_slug)
            eligible_assets = [
                asset
                for asset in dashboard.get("rendered", [])
                if asset.get("review_state") in {"approved", "review_ready"}
                and not (asset.get("export_readiness") or {}).get("blockingReasons")
            ]
            eligible_assets.sort(
                key=lambda asset: (ranking_by_asset.get(asset["id"]) or {}).get(
                    "score", 0
                ),
                reverse=True,
            )
            total = len(eligible_assets)
            regular_count = math.ceil(total * 0.20) if total else 0
            trial_count = math.floor(total * 0.60)
            if total and regular_count + trial_count == 0:
                trial_count = 1
            primary_assets = eligible_assets[: regular_count + trial_count]
            profile_cache: dict[str, dict[str, Any] | None] = {}
            account_cursors: dict[str, int] = {}
            account_day_counts: dict[tuple[str, str], int] = {}
            account_slot_times: dict[str, list[datetime]] = {}
            caption_day_counts: dict[tuple[str, str], int] = {}
            source_week_counts: dict[tuple[str, str], int] = {}
            planned = []
            unplanned = []
            warnings: list[dict[str, Any]] = []
            slots = self.distribution_slots(
                fallback_hours or [10, 14, 18],
                len(primary_assets) + len(primary_assets),
            )
            self.hydrate_distribution_cadence(
                slots, account_day_counts, account_slot_times
            )
            slot_index = 0
            for index, asset in enumerate(primary_assets):
                model_slug = asset.get("model_slug") or asset.get("modelId") or ""
                profile = profile_cache.setdefault(
                    model_slug, self._model_account_profile(model_slug)
                )
                surface = "regular_reel" if index < regular_count else "trial_reel"
                account_id = self.next_distribution_account(
                    profile,
                    model_slug,
                    account_cursors,
                    require_trial_eligible=surface == "trial_reel",
                )
                if not account_id:
                    unplanned.append(
                        {
                            "renderedAssetId": asset["id"],
                            "reason": (
                                "no_trial_eligible_account"
                                if surface == "trial_reel"
                                else "no_compatible_account"
                            ),
                        }
                    )
                    continue
                reason_code = (
                    "high_confidence_reel"
                    if surface == "regular_reel"
                    else "test_uncertain_winner"
                )
                slot, slot_index = self.next_valid_distribution_slot(
                    slots,
                    slot_index,
                    account_id,
                    asset,
                    account_day_counts,
                    account_slot_times,
                    caption_day_counts,
                    source_week_counts,
                    warnings,
                    surface,
                )
                if not slot:
                    unplanned.append(
                        {
                            "renderedAssetId": asset["id"],
                            "reason": "no_available_time_slot",
                        }
                    )
                    continue
                plan = self.create_distribution_plan(
                    asset["id"],
                    surface=surface,
                    instagram_account_id=account_id,
                    planned_window_start=slot.isoformat(),
                    commit=False,
                    reason_code=reason_code,
                    instagram_trial_reels=surface == "trial_reel",
                    trial_graduation_strategy="MANUAL"
                    if surface == "trial_reel"
                    else None,
                    trial_group_id=f"trial_{campaign['id']}_{asset['id']}"
                    if surface == "trial_reel"
                    else None,
                    smart_link=(profile or {}).get("defaultSmartLink"),
                    cta_text=(profile or {}).get("storyCtaText")
                    if surface == "story_cta"
                    else None,
                )
                planned.append(plan)
                if (profile or {}).get("storyCtaText") or (profile or {}).get(
                    "defaultSmartLink"
                ):
                    story_slot = slot + timedelta(hours=2)
                    story_plan = self.create_distribution_plan(
                        asset["id"],
                        surface="story_cta",
                        instagram_account_id=account_id,
                        planned_window_start=story_slot.isoformat(),
                        commit=False,
                        paired_rendered_asset_id=asset["id"],
                        reason_code="cta_followup",
                        smart_link=(profile or {}).get("defaultSmartLink"),
                        cta_text=(profile or {}).get("storyCtaText")
                        or "new post is up",
                    )
                    planned.append(story_plan)
            surface_counts: dict[str, int] = {}
            for plan in planned:
                surface_counts[plan["surface"]] = (
                    surface_counts.get(plan["surface"], 0) + 1
                )
            result = {
                "schema": "campaign_factory.distribution_plan_run.v1",
                "campaign": campaign["slug"],
                "userId": user_id,
                "mode": schedule_mode,
                "strategy": normalized_strategy,
                "generatedAt": self._utc_now(),
                "pipelineJobId": pipeline_job["id"],
                "clearedPlans": cleared,
                "eligibleAssets": total,
                "plannedCount": len(planned),
                "unplannedCount": len(unplanned) + max(0, total - len(primary_assets)),
                "surfaceCounts": surface_counts,
                "planned": planned,
                "unplanned": unplanned
                + [
                    {
                        "renderedAssetId": asset["id"],
                        "reason": "bottom_twenty_unplanned",
                    }
                    for asset in eligible_assets[len(primary_assets) :]
                ],
                "warnings": warnings,
            }
            self._record_event(
                "distribution_planned",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success" if not warnings else "warning",
                message=f"Distribution planned: {len(planned)} plans across {len(surface_counts)} surfaces",
                metadata={
                    "mode": schedule_mode,
                    "strategy": normalized_strategy,
                    "surfaceCounts": surface_counts,
                    "plannedCount": len(planned),
                    "unplannedCount": result["unplannedCount"],
                    "warningCount": len(warnings),
                },
            )
            self._finish_pipeline_job(pipeline_job["id"], result)
            return result
        except Exception as exc:
            # Discard the partial delete/insert batch so a failed replace run
            # cannot commit a half-written plan set via the failure bookkeeping.
            self.conn.rollback()
            self._record_event(
                "distribution_planned",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Distribution planning failed: {exc}",
                metadata={
                    "error": str(exc),
                    "mode": schedule_mode,
                    "strategy": normalized_strategy,
                },
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise

    def next_distribution_account(
        self,
        profile: dict[str, Any] | None,
        model_slug: str,
        cursors: dict[str, int],
        *,
        require_trial_eligible: bool = False,
    ) -> str | None:
        allowed = [
            str(item)
            for item in (profile or {}).get("allowedInstagramAccountIds") or []
            if str(item).strip()
        ]
        if not allowed:
            return None
        cursor_key = (profile or {}).get("modelSlug") or model_slug or "default"
        for _ in allowed:
            index = cursors.get(cursor_key, 0)
            account_id = allowed[index % len(allowed)]
            cursors[cursor_key] = index + 1
            compatible, _, _ = self._account_compatible_with_model(
                model_slug, instagram_account_id=account_id
            )
            if not compatible:
                continue
            account_decision = evaluate_account_eligibility(
                self.conn,
                instagram_account_id=account_id,
                surface="trial_reel" if require_trial_eligible else "regular_reel",
                requires_trial_capability=require_trial_eligible,
            )
            if not account_decision["allowed"]:
                continue
            return account_id
        return None

    def distribution_slots(self, hours: list[int], count: int) -> list[datetime]:
        local_tz = ZoneInfo("America/New_York")
        now = datetime.now(UTC)
        local_start_date = (now.astimezone(local_tz) + timedelta(days=1)).date()
        slots = []
        safe_hours = [hour for hour in hours if 0 <= int(hour) <= 23] or [10, 14, 18]
        day = 0
        while len(slots) < max(1, count * 4):
            current_day = local_start_date + timedelta(days=day)
            for hour in safe_hours:
                local_slot = datetime.combine(
                    current_day, datetime_time(hour=int(hour)), tzinfo=local_tz
                )
                slot = local_slot.astimezone(UTC)
                if slot > now:
                    slots.append(slot)
                    if len(slots) >= max(1, count * 4):
                        break
            day += 1
        return slots

    def hydrate_distribution_cadence(
        self,
        slots: list[datetime],
        account_day_counts: dict[tuple[str, str], int],
        account_slot_times: dict[str, list[datetime]],
    ) -> None:
        if not slots:
            return
        hydration_hours = self.distribution_hydration_window_hours()
        window_start = min(slots) - timedelta(hours=hydration_hours)
        window_end = max(slots) + timedelta(hours=hydration_hours)
        rows = self.conn.execute(
            """
            SELECT COALESCE(NULLIF(instagram_account_id, ''), account_id) AS account_id,
                   planned_window_start AS planned_at
            FROM distribution_plans
            WHERE planned_window_start IS NOT NULL
            UNION ALL
            SELECT COALESCE(NULLIF(instagram_account_id, ''), account_id) AS account_id,
                   scheduled_for AS planned_at
            FROM variant_account_usage
            WHERE scheduled_for IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            account_id = str(row["account_id"] or "").strip()
            planned_at = _parse_distribution_time(row["planned_at"])
            if not account_id or not planned_at:
                continue
            if not (window_start <= planned_at <= window_end):
                continue
            day_key = planned_at.date().isoformat()
            account_day_counts[(account_id, day_key)] = (
                account_day_counts.get((account_id, day_key), 0) + 1
            )
            account_slot_times.setdefault(account_id, []).append(planned_at)

    def distribution_hydration_window_hours(self) -> int:
        row = self.conn.execute(
            """
            SELECT MAX(COALESCE(min_gap_hours, 0)) AS max_gap
            FROM account_content_requirements
            WHERE active = 1
            """
        ).fetchone()
        try:
            max_gap = int(row["max_gap"] or 0) if row else 0
        except (TypeError, ValueError):
            max_gap = 0
        return max(4, max_gap)

    def account_distribution_cadence(
        self, account_id: str, content_surface: str | None = "reel"
    ) -> tuple[int, int]:
        surface = self._normalize_content_surface(content_surface)
        if surface in {"regular_reel", "trial_reel"}:
            surface = "reel"
        row = self.conn.execute(
            """
            SELECT r.max_per_day, r.min_gap_hours
            FROM account_content_requirements r
            LEFT JOIN accounts a ON a.id = r.account_id
            WHERE r.active = 1
              AND r.content_surface = ?
              AND (r.account_id = ? OR a.external_id = ? OR a.handle = ?)
            ORDER BY CASE
                WHEN r.account_id = ? THEN 0
                WHEN a.external_id = ? THEN 1
                ELSE 2
            END
            LIMIT 1
            """,
            (surface, account_id, account_id, account_id, account_id, account_id),
        ).fetchone()
        if not row:
            return 1, 4
        return max(1, int(row["max_per_day"] or 1)), max(
            0, int(row["min_gap_hours"] or 0)
        )

    def next_valid_distribution_slot(
        self,
        slots: list[datetime],
        start_index: int,
        account_id: str,
        asset: dict[str, Any],
        account_day_counts: dict[tuple[str, str], int],
        account_slot_times: dict[str, list[datetime]],
        caption_day_counts: dict[tuple[str, str], int],
        source_week_counts: dict[tuple[str, str], int],
        warnings: list[dict[str, Any]],
        content_surface: str | None = "reel",
    ) -> tuple[datetime | None, int]:
        max_per_day, min_gap_hours = self.account_distribution_cadence(
            account_id, content_surface
        )
        caption_hash = (
            asset.get("caption_hash")
            or asset.get("captionHash")
            or asset.get("content_hash")
            or asset["id"]
        )
        source_id = (
            asset.get("source_asset_id") or asset.get("sourceAssetId") or asset["id"]
        )
        for offset in range(len(slots)):
            index = start_index + offset
            slot = slots[index % len(slots)]
            day_key = slot.date().isoformat()
            week_key = f"{slot.isocalendar().year}-W{slot.isocalendar().week:02d}"
            if account_day_counts.get((account_id, day_key), 0) >= max_per_day:
                continue
            if any(
                abs((slot - planned_at).total_seconds()) < min_gap_hours * 3600
                for planned_at in account_slot_times.get(account_id, [])
            ):
                continue
            if (
                caption_day_counts.get((account_id, f"{day_key}:{caption_hash}"), 0)
                >= 1
            ):
                warnings.append(
                    {
                        "type": "caption_reuse_avoided",
                        "renderedAssetId": asset["id"],
                        "instagramAccountId": account_id,
                    }
                )
                continue
            if source_week_counts.get((account_id, f"{week_key}:{source_id}"), 0) >= 1:
                warnings.append(
                    {
                        "type": "source_family_reuse_avoided",
                        "renderedAssetId": asset["id"],
                        "instagramAccountId": account_id,
                    }
                )
                continue
            account_day_counts[(account_id, day_key)] = (
                account_day_counts.get((account_id, day_key), 0) + 1
            )
            account_slot_times.setdefault(account_id, []).append(slot)
            caption_day_counts[(account_id, f"{day_key}:{caption_hash}")] = (
                caption_day_counts.get((account_id, f"{day_key}:{caption_hash}"), 0) + 1
            )
            source_week_counts[(account_id, f"{week_key}:{source_id}")] = (
                source_week_counts.get((account_id, f"{week_key}:{source_id}"), 0) + 1
            )
            return slot, index + 1
        return None, start_index

    def distribution_summary(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rendered = [
            self._dashboard_rendered_asset(asset)
            for asset in self._rendered_for_campaign(campaign["id"])
        ]
        plans = self.distribution_plans_for_campaign(campaign_slug)
        planned_assets = {
            plan["renderedAssetId"]
            for plan in plans
            if plan.get("surface") != "story_cta"
        }
        surface_counts: dict[str, int] = {}
        preview_count = 0
        live_count = 0
        for plan in plans:
            surface = plan.get("surface") or "regular_reel"
            surface_counts[surface] = surface_counts.get(surface, 0) + 1
            if plan.get("plannedWindowStart"):
                preview_count += 1
        return {
            "schema": "campaign_factory.distribution_summary.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "surfaceCounts": surface_counts,
            "plannedAssets": len(planned_assets),
            "unplannedApprovedAssets": len(
                [
                    asset
                    for asset in rendered
                    if asset.get("review_state") in {"approved", "review_ready"}
                    and asset["id"] not in planned_assets
                ]
            ),
            "previewScheduledPlans": preview_count,
            "liveScheduledPlans": live_count,
            "plans": plans,
        }

    def latest_distribution_plan_for_asset(
        self, rendered_asset_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM distribution_plans WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (rendered_asset_id,),
        ).fetchone()
        return self.distribution_plan_payload(dict(row)) if row else None
