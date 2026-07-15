from __future__ import annotations

import re
from typing import Any

from ..account_eligibility import evaluate_account_eligibility
from ..core import CampaignFactory, normalize_content_surface

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def draft_destinations_for_asset(
    factory: CampaignFactory,
    asset: dict[str, Any],
    *,
    plans: list[dict[str, Any]] | None = None,
    require_distribution_plan: bool = False,
) -> list[dict[str, Any]]:
    plans = (
        plans
        if plans is not None
        else factory.domains.distribution.distribution_plans_for_asset(
            asset["renderedAssetId"]
        )
    )
    asset_content_surface = normalize_content_surface(
        asset.get("contentSurface") or asset.get("content_surface")
    )
    default_surface = (
        "regular_reel" if asset_content_surface == "reel" else asset_content_surface
    )
    if plans:
        return [
            {
                "accountId": plan.get("accountId"),
                "instagramAccountId": plan.get("instagramAccountId"),
                "plannedWindowStart": plan.get("plannedWindowStart"),
                "plannedWindowEnd": plan.get("plannedWindowEnd"),
                "notes": plan.get("reasonCode"),
                "distributionPlanId": plan.get("id"),
                "distributionSurface": plan.get("surface"),
                "contentSurface": plan.get("contentSurface")
                or plan.get("content_surface"),
                "instagramTrialReels": plan.get("instagramTrialReels"),
                "trialGraduationStrategy": plan.get("trialGraduationStrategy"),
                "trialGroupId": plan.get("trialGroupId"),
                "pairedRenderedAssetId": plan.get("pairedRenderedAssetId"),
                "reasonCode": plan.get("reasonCode"),
                "smartLink": plan.get("smartLink"),
                "ctaText": plan.get("ctaText"),
                "accountEligibility": _current_account_eligibility(
                    factory,
                    account_id=plan.get("accountId"),
                    instagram_account_id=plan.get("instagramAccountId"),
                    surface=plan.get("surface") or default_surface,
                    planned_at=plan.get("plannedWindowStart"),
                    trial=bool(plan.get("instagramTrialReels")),
                    authorization=(plan.get("trialCapability") or {}).get(
                        "authorization"
                    ),
                ),
            }
            for plan in plans
        ]
    if require_distribution_plan:
        return []
    assignments = factory.domains.campaign_overview.assignments_for_asset(
        asset["renderedAssetId"]
    )
    if assignments:
        return [
            {
                "accountId": assignment.get("account_id"),
                "instagramAccountId": assignment.get("instagram_account_id"),
                "plannedWindowStart": assignment.get("planned_window_start"),
                "plannedWindowEnd": assignment.get("planned_window_end"),
                "notes": assignment.get("notes"),
                "distributionSurface": default_surface,
                "contentSurface": asset_content_surface,
                "accountEligibility": _current_account_eligibility(
                    factory,
                    account_id=assignment.get("account_id"),
                    instagram_account_id=assignment.get("instagram_account_id"),
                    surface=default_surface,
                    planned_at=assignment.get("planned_window_start"),
                ),
            }
            for assignment in assignments
        ]
    destinations = []
    for account_id in asset.get("accountIds") or ["unassigned"]:
        normalized_account_id = None if account_id == "unassigned" else account_id
        destinations.append(
            {
                "accountId": account_id,
                "instagramAccountId": _resolve_instagram_account_id(
                    factory, account_id
                ),
                "plannedWindowStart": None,
                "plannedWindowEnd": None,
                "notes": None,
                "distributionSurface": default_surface,
                "contentSurface": asset_content_surface,
                "accountEligibility": evaluate_account_eligibility(
                    factory.conn,
                    account_id=normalized_account_id,
                    surface=default_surface,
                ),
            }
        )
    return destinations


def _current_account_eligibility(
    factory: CampaignFactory,
    *,
    account_id: str | None,
    instagram_account_id: str | None,
    surface: str,
    planned_at: str | None,
    trial: bool = False,
    authorization: str | None = None,
) -> dict[str, Any]:
    return evaluate_account_eligibility(
        factory.conn,
        account_id=account_id,
        instagram_account_id=instagram_account_id,
        surface=surface,
        requires_trial_capability=trial,
        authorization=authorization,
        planned_at=planned_at,
    )


def _resolve_instagram_account_id(
    factory: CampaignFactory, account_id: str
) -> str | None:
    if not account_id or account_id == "unassigned":
        return None
    row = factory.conn.execute(
        "SELECT * FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row and row["external_id"]:
        return str(row["external_id"])
    if UUID_RE.match(account_id):
        return account_id
    return None
