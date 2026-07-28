"""Higgsfield quote and spend binding for the intent-first production lane."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.provider_spend import build_generate_assets_spend_scope

from .production_prompts import CREATOR_SOUL_IDS
from .provider_spend import issue_provider_spend_authorization


class _BoundHiggsfieldQuote:
    def __init__(self, quote: Mapping[str, Any]) -> None:
        self._quote = dict(quote)

    def quote(self, _scope: dict[str, Any]) -> dict[str, Any]:
        return dict(self._quote)


def higgsfield_request(job: Mapping[str, Any], *, max_credits: float) -> Any:
    from reel_factory.worker_api import HiggsfieldProductionRequest

    creator = str(job["creator"])
    try:
        soul_id = CREATOR_SOUL_IDS[creator]
    except KeyError as exc:
        raise ValueError(
            f"no pinned authenticated Higgsfield Soul identity for creator {creator}"
        ) from exc
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    return HiggsfieldProductionRequest(
        recipe_id=(
            "higgsfield_recreate_reel"
            if stage["recipeId"] == "higgsfield_recreate_reel"
            else "higgsfield_passive_selfie"
        ),
        creator=creator,
        soul_id=soul_id,
        source_approval=str(job["sourceAssetId"]),
        source_image_path=Path(str(job["sourcePath"])),
        driving_video_path=(
            Path(str(job["referenceVideoPath"]))
            if job.get("referenceVideoPath")
            else None
        ),
        output_path=Path(str(job["providerOutputPath"])),
        review_root=Path(str(job["providerReviewRoot"])),
        prompt=str(job["prompt"]),
        model=str(stage["providerModel"]),
        duration_seconds=int(stage["durationSeconds"]),
        max_credits=max_credits,
        seed=int(job["seed"]),
    )


def higgsfield_spend_scope(job: Mapping[str, Any]) -> dict[str, Any]:
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    args = [
        "video",
        "--stem",
        str(job["jobId"]),
        "--soul-id",
        CREATOR_SOUL_IDS[str(job["creator"])],
        "--campaign",
        str(job["campaign"]),
        "--cohort-id",
        str(job["jobId"]),
        "--start-image",
        str(job["sourcePath"]),
        "--video-model",
        str(stage["providerModel"]),
        "--video-aspect-ratio",
        "9:16",
        "--video-duration",
        str(stage["durationSeconds"]),
        "--video-mode",
        str(stage["mode"]),
        "--video-sound",
        "off",
    ]
    if job.get("referenceVideoPath"):
        args.extend(["--video-reference", str(job["referenceVideoPath"])])
    return build_generate_assets_spend_scope(args, root=Path.cwd())


def prepare_higgsfield_job_quotes(
    factory: Any,
    jobs: list[dict[str, Any]],
    *,
    max_total_credits: float,
) -> list[dict[str, Any]]:
    """Perform authenticated read-only quoting without issuing spend authority."""

    from reel_factory.worker_api import (
        build_higgsfield_production_plan,
        discover_higgsfield_production_capabilities,
        quote_higgsfield_production_plan,
    )

    if not jobs:
        return []
    capabilities = discover_higgsfield_production_capabilities()
    prepared: list[dict[str, Any]] = []
    total = 0.0
    for job in jobs:
        campaign = factory.domains.campaign_by_slug(str(job["campaign"]))
        model_slug = factory.domains.reel_execution.model_slug_for_campaign(
            campaign["id"]
        )
        dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
        output = dirs["rendered"] / (
            f"{job['jobId']}_{job['productionRecipe']['modelId']}.mp4"
        )
        review_root = dirs["audits"] / "higgsfield_production"
        candidate = {
            **job,
            "providerOutputPath": str(output),
            "providerReviewRoot": str(review_root),
        }
        request = higgsfield_request(candidate, max_credits=max_total_credits)
        provider_plan = build_higgsfield_production_plan(
            request,
            capabilities=capabilities,
        )
        quote = quote_higgsfield_production_plan(provider_plan)
        amount = float(quote["amount"])
        total = round(total + amount, 4)
        prepared.append(
            {
                **candidate,
                "quotedProviderCredits": amount,
                "providerPlanFingerprint": provider_plan["requestFingerprint"],
                "providerSubmitContract": provider_plan["command"],
                "providerQuoteContract": provider_plan["quoteCommand"],
                "_higgsfieldCapabilities": capabilities,
                "_higgsfieldQuote": quote,
                "_campaignId": str(campaign["id"]),
            }
        )
    if total > max_total_credits:
        raise PermissionError(
            "production_batch_quote_exceeds_total_credit_cap: "
            f"{total:.4f} > {max_total_credits:.4f}"
        )
    return prepared


def authorize_higgsfield_jobs(
    factory: Any,
    jobs: list[dict[str, Any]],
    *,
    max_total_credits: float,
) -> list[dict[str, Any]]:
    """Quote and authorize the whole batch before the first paid submission."""

    prepared = prepare_higgsfield_job_quotes(
        factory, jobs, max_total_credits=max_total_credits
    )
    secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    authorized: list[dict[str, Any]] = []
    for job in prepared:
        scope = higgsfield_spend_scope(job)
        authorization = issue_provider_spend_authorization(
            factory.conn,
            scope=scope,
            campaign_id=str(job["_campaignId"]),
            max_credits=float(job["quotedProviderCredits"]),
            secret=secret,
            quote_provider=_BoundHiggsfieldQuote(job["_higgsfieldQuote"]),
        )
        authorized.append(
            {
                **job,
                "_higgsfieldSpendScope": scope,
                "_higgsfieldAuthorization": authorization,
            }
        )
    return authorized
