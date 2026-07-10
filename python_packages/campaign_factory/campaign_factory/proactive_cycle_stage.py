from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core import sanitize_for_storage, slugify
from .cost_tracker import PROVIDER_PRICING
from .fileops import atomic_write_text
from .persistence import utc_now
from .variation_stage import run_variation_stage

SCHEMA = "campaign_factory.proactive_cycle_run.v1"
DEFAULT_FRONT_IMAGE_COST_USD = PROVIDER_PRICING["higgsfield"]["per_generation"]
DEFAULT_FRONT_VIDEO_COST_USD = PROVIDER_PRICING["kling"]["per_generation"]


def run_proactive_cycle_stage(
    factory: Any,
    *,
    campaign_slug: str,
    count: int = 3,
    account: str | None = None,
    reference_image_path: Path | None = None,
    generation_mode: str = "existing_asset",
    enable_variation: bool = False,
    enable_export: bool = False,
    enable_schedule: bool = False,
    schedule_mode: str = "draft",
    user_id: str | None = None,
    dry_run: bool = True,
    apply: bool = False,
    enable_live: bool = False,
    enable_paid_generation: bool = False,
    budget_cap_usd: float | None = None,
    idempotency_key: str | None = None,
    kill_switch: bool = False,
) -> dict[str, Any]:
    """Plan one draft-first campaign cycle with fail-closed live guards."""
    campaign = factory.campaign_by_slug(campaign_slug)
    live_mode = bool(apply and not dry_run)
    normalized_generation_mode = _normalize_generation_mode(
        generation_mode, reference_image_path
    )
    projected_cost = _projected_cost(normalized_generation_mode)
    live_guard = _live_guard(
        live_mode=live_mode,
        enable_live=enable_live,
        enable_paid_generation=enable_paid_generation,
        budget_cap_usd=budget_cap_usd,
        projected_cost_usd=projected_cost,
        idempotency_key=idempotency_key,
        kill_switch=kill_switch or _env_kill_switch_active(),
    )
    report_key = (
        f"{'live' if live_mode else 'dry'}_{idempotency_key}"
        if idempotency_key
        else _dry_run_report_key(
            campaign_slug=campaign_slug,
            count=count,
            account=account,
            generation_mode=normalized_generation_mode,
            enable_variation=enable_variation,
            enable_export=enable_export,
            enable_schedule=enable_schedule,
            schedule_mode=schedule_mode,
        )
    )
    report_path = _report_path(factory, campaign=campaign, report_key=report_key)
    if report_path.exists():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("schema") == SCHEMA:
            payload["idempotentReplay"] = True
            return payload

    pipeline_job = factory.create_pipeline_job(
        "proactive_cycle",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "count": count,
            "account": account,
            "generationMode": normalized_generation_mode,
            "enableVariation": enable_variation,
            "enableExport": enable_export,
            "enableSchedule": enable_schedule,
            "scheduleMode": schedule_mode,
            "dryRun": dry_run,
            "apply": apply,
            "enableLive": enable_live,
            "budgetCapUsd": budget_cap_usd,
            "idempotencyKey": idempotency_key,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        if live_mode and not live_guard["allowed"]:
            raise PermissionError("; ".join(live_guard["blockingReasons"]))
        recommendation = factory.recommend_next_batch(
            campaign_slug,
            count=max(1, int(count)),
            account=account,
            persist=False,
        )
        top_item = (recommendation.get("items") or [{}])[0]
        variation = _variation_plan(top_item, enable_variation=enable_variation)
        export = _export_plan(
            enable_export=enable_export,
            enable_schedule=enable_schedule,
            schedule_mode=schedule_mode,
            user_id=user_id,
        )
        executed_actions: list[dict[str, Any]] = []
        if live_mode and enable_variation and top_item.get("renderedAssetId"):
            variation["result"] = run_variation_stage(
                factory,
                campaign_slug=campaign_slug,
                preset_name=variation["presetName"],
                rendered_asset_ids=[top_item["renderedAssetId"]],
                dry_run=True,
            )
            executed_actions.append(
                {"action": "variation_dry_run", "status": "completed"}
            )
        if live_mode and enable_export:
            if not user_id:
                raise ValueError("proactive export preview requires --user-id")
            from .adapters.threadsdash import export_threadsdash

            export_result = export_threadsdash(
                factory,
                campaign_slug=campaign_slug,
                user_id=user_id,
                dry_run=True,
                schedule_mode="draft",
                enable_variation=enable_variation,
                variation_preset=variation["presetName"],
            )
            export["result"] = _compact_export_result(export_result)
            executed_actions.append(
                {"action": "export_draft_preview", "status": "completed"}
            )
        report = {
            "schema": SCHEMA,
            "campaign": campaign_slug,
            "generatedAt": utc_now(),
            "dryRun": not live_mode,
            "apply": live_mode,
            "idempotencyKey": report_key,
            "idempotentReplay": False,
            "publishingAllowed": False,
            "autonomousSchedulingAllowed": False,
            "liveGuard": live_guard,
            "cost": {
                "projectedCostUsd": round(projected_cost, 4),
                "budgetCapUsd": budget_cap_usd,
                "status": _budget_status(projected_cost, budget_cap_usd),
            },
            "recommendation": _compact_recommendation(recommendation),
            "referenceSelection": _reference_selection(top_item),
            "generation": _generation_plan(
                mode=normalized_generation_mode,
                reference_image_path=reference_image_path,
                projected_cost_usd=projected_cost,
                enable_paid_generation=enable_paid_generation,
            ),
            "variation": variation,
            "export": export,
            "scheduleIntent": _schedule_intent(
                enable_schedule=enable_schedule, schedule_mode=schedule_mode
            ),
            "executedActions": executed_actions,
            "reportPath": str(report_path),
            "pipelineJobId": pipeline_job["id"],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            report_path,
            json.dumps(sanitize_for_storage(report), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        factory.finish_pipeline_job(pipeline_job["id"], sanitize_for_storage(report))
        return report
    except Exception as exc:
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _normalize_generation_mode(
    generation_mode: str, reference_image_path: Path | None
) -> str:
    normalized = str(generation_mode or "").strip().lower().replace("-", "_")
    if (
        normalized in {"front_generation", "front_generation_kling", "kling"}
        or reference_image_path
    ):
        return "front_generation_kling"
    if normalized in {"motion_edit", "existing_asset"}:
        return normalized
    return "existing_asset"


def _projected_cost(generation_mode: str) -> float:
    if generation_mode == "front_generation_kling":
        return DEFAULT_FRONT_IMAGE_COST_USD + DEFAULT_FRONT_VIDEO_COST_USD
    return 0.0


def _budget_status(projected_cost_usd: float, budget_cap_usd: float | None) -> str:
    if projected_cost_usd <= 0:
        return "not_required"
    if budget_cap_usd is None:
        return "missing_cap"
    if projected_cost_usd > budget_cap_usd:
        return "exceeds_cap"
    return "within_cap"


def _env_kill_switch_active() -> bool:
    return os.environ.get(
        "CREATOR_OS_PROACTIVE_CYCLE_DISABLED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def _live_guard(
    *,
    live_mode: bool,
    enable_live: bool,
    enable_paid_generation: bool,
    budget_cap_usd: float | None,
    projected_cost_usd: float,
    idempotency_key: str | None,
    kill_switch: bool,
) -> dict[str, Any]:
    blocking = []
    if kill_switch:
        blocking.append("proactive_cycle_kill_switch_active")
    if live_mode and not enable_live:
        blocking.append("missing_enable_live")
    if live_mode and not idempotency_key:
        blocking.append("missing_idempotency_key")
    if live_mode and budget_cap_usd is None:
        blocking.append("missing_budget_cap_usd")
    if live_mode and projected_cost_usd > 0 and not enable_paid_generation:
        blocking.append("missing_enable_paid_generation")
    if budget_cap_usd is not None and projected_cost_usd > budget_cap_usd:
        blocking.append("projected_cost_exceeds_budget_cap")
    return {
        "liveMode": live_mode,
        "enableLive": enable_live,
        "enablePaidGeneration": enable_paid_generation,
        "budgetCapUsd": budget_cap_usd,
        "projectedCostUsd": round(projected_cost_usd, 4),
        "idempotencyKeyRequired": live_mode,
        "killSwitchActive": kill_switch,
        "allowed": not blocking,
        "blockingReasons": blocking,
    }


def _dry_run_report_key(**values: Any) -> str:
    payload = json.dumps(values, sort_keys=True, default=str)
    import hashlib

    return f"dry_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _report_path(factory: Any, *, campaign: dict[str, Any], report_key: str) -> Path:
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    return (
        dirs["exports"]
        / "proactive_cycles"
        / f"{slugify(report_key)}.proactive_cycle_run.v1.json"
    )


def _compact_recommendation(recommendation: dict[str, Any]) -> dict[str, Any]:
    items = recommendation.get("items") or []
    top = items[0] if items else {}
    return {
        "schema": recommendation.get("schema"),
        "inputHash": recommendation.get("inputHash"),
        "count": recommendation.get("count"),
        "requestedCount": recommendation.get("requestedCount"),
        "account": recommendation.get("account"),
        "topItem": {
            "recommendationId": top.get("recommendationId"),
            "renderedAssetId": top.get("renderedAssetId"),
            "score": top.get("score"),
            "referencePatternId": top.get("referencePatternId"),
            "recommendedVariationPreset": top.get("recommendedVariationPreset"),
        },
    }


def _reference_selection(top_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "referencePatternId": top_item.get("referencePatternId"),
        "referencePattern": top_item.get("referencePattern"),
        "evidence": top_item.get("referencePatternEvidence") or {},
    }


def _generation_plan(
    *,
    mode: str,
    reference_image_path: Path | None,
    projected_cost_usd: float,
    enable_paid_generation: bool,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "referenceImagePath": str(reference_image_path.expanduser().resolve())
        if reference_image_path
        else None,
        "paidGenerationRequired": projected_cost_usd > 0,
        "paidGenerationEnabled": enable_paid_generation,
        "projectedCostUsd": round(projected_cost_usd, 4),
        "humanReviewRequired": True,
        "willCallPaidProvider": False,
    }


def _variation_plan(
    top_item: dict[str, Any], *, enable_variation: bool
) -> dict[str, Any]:
    return {
        "enabled": enable_variation,
        "dryRunOnly": True,
        "masterRenderedAssetId": top_item.get("renderedAssetId"),
        "presetName": top_item.get("recommendedVariationPreset") or "ig_subtle",
        "evidence": top_item.get("variationPresetEvidence") or {},
    }


def _export_plan(
    *,
    enable_export: bool,
    enable_schedule: bool,
    schedule_mode: str,
    user_id: str | None,
) -> dict[str, Any]:
    return {
        "enabled": enable_export,
        "dryRunOnly": True,
        "userId": user_id,
        "scheduleMode": "draft",
        "requestedScheduleMode": schedule_mode,
        "scheduleRequested": enable_schedule,
        "publishingAllowed": False,
    }


def _schedule_intent(*, enable_schedule: bool, schedule_mode: str) -> dict[str, Any]:
    return {
        "enabled": enable_schedule,
        "requestedMode": schedule_mode,
        "effectiveMode": "draft",
        "autonomousSchedulingAllowed": False,
        "reason": "proactive cycle is draft-first; schedule/publish remains operator-owned",
    }


def _compact_export_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": result.get("schema"),
        "dryRun": result.get("dryRun"),
        "created": len(result.get("created") or []),
        "updated": len(result.get("updated") or []),
        "skipped": len(result.get("skipped") or []),
        "errors": result.get("errors") or [],
    }
