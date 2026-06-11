from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .caption_outcome import context_has_signal, load_context_json
from .core import CampaignFactory, json_load, utc_now


UNRESOLVED_NATIVE_AUDIO_STATUSES = {"recommended", "needs_operator_selection", "selected", "blocked", "missing"}


def build_mass_production_readiness_report(
    factory: CampaignFactory,
    *,
    campaign_id: str,
    days: int = 7,
    user_id: str | None = None,
    threadsdash_usage: dict[str, Any] | None = None,
    threadsdash_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    campaign = _campaign_by_id_or_slug(factory, campaign_id)
    days = max(1, int(days or 7))
    source_rows = _rows(factory, "SELECT * FROM source_assets WHERE campaign_id = ?", (campaign["id"],))
    sources_by_id = {row["id"]: row for row in source_rows}
    assets = _rows(
        factory,
        "SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at DESC",
        (campaign["id"],),
    )
    graph_ids = _graph_ids(factory, "rendered_assets", [asset["id"] for asset in assets])
    assignments = _rows(factory, "SELECT * FROM asset_account_assignments WHERE campaign_id = ?", (campaign["id"],))
    assignments_by_asset = _group_by(assignments, "rendered_asset_id")
    plans = _rows(factory, "SELECT * FROM distribution_plans WHERE campaign_id = ?", (campaign["id"],))
    plans_by_asset = _group_by(plans, "rendered_asset_id")
    snapshots = _rows(factory, "SELECT * FROM performance_snapshots WHERE campaign_id = ?", (campaign["id"],))
    snapshots_by_asset = _group_by(snapshots, "rendered_asset_id")
    snapshots_missing_caption_context = sum(
        1 for snapshot in snapshots
        if not context_has_signal(load_context_json(snapshot.get("caption_outcome_context_json")))
    )
    exports = _rows(factory, "SELECT * FROM threadsdash_exports WHERE campaign_id = ? ORDER BY created_at DESC", (campaign["id"],))

    asset_reports = []
    missing = Counter()
    audio_status_counts = Counter()
    content_fingerprint_groups: dict[str, list[str]] = defaultdict(list)
    source_family_groups: dict[str, list[str]] = defaultdict(list)
    rendered_asset_duplicate_risks = []
    unresolved_audio_assets = []
    approved_assets = []

    usage_by_asset = {
        item.get("renderedAssetId"): item
        for item in (threadsdash_usage or {}).get("assets", [])
        if item.get("renderedAssetId")
    }

    for asset in assets:
        source = sources_by_id.get(asset["source_asset_id"])
        source_prompt = json_load(source.get("source_prompt") if source else None, {}) or {}
        caption_generation = json_load(asset.get("caption_generation_json"), {}) or {}
        caption_outcome_context = load_context_json(asset.get("caption_outcome_context_json"))
        lineage = _extract_lineage(source_prompt, caption_generation)
        audio_status = _audio_status(source_prompt, caption_generation)
        audio_status_counts[audio_status] += 1
        content_fingerprint = _content_fingerprint(asset, source_prompt, lineage)
        source_family = _source_family(asset, source, source_prompt, lineage)
        content_fingerprint_groups[content_fingerprint].append(asset["id"])
        source_family_groups[source_family].append(asset["id"])

        asset_usage = (usage_by_asset.get(asset["id"]) or {}).get("usage") or {}
        usage_total = int(asset_usage.get("total") or 0)
        if usage_total:
            rendered_asset_duplicate_risks.append({
                "renderedAssetId": asset["id"],
                "filename": asset["filename"],
                "usage": asset_usage,
            })

        is_approved = asset.get("review_state") == "approved"
        if is_approved:
            approved_assets.append(asset)
        if not graph_ids.get(asset["id"]):
            missing["canonicalIds"] += 1
        if not lineage:
            missing["lineage"] += 1
        if not context_has_signal(caption_outcome_context):
            missing["captionOutcomeContext"] += 1
        if not asset.get("output_path") or not asset.get("campaign_path"):
            missing["renderedOutputPath"] += 1
        if not str(asset.get("caption") or "").strip():
            missing["caption"] += 1
        if audio_status == "missing":
            missing["audioStatus"] += 1
        if not assignments_by_asset.get(asset["id"]) and not plans_by_asset.get(asset["id"]):
            missing["accountAssignment"] += 1
        if audio_status in UNRESOLVED_NATIVE_AUDIO_STATUSES:
            unresolved_audio_assets.append(asset["id"])

        asset_reports.append({
            "renderedAssetId": asset["id"],
            "filename": asset["filename"],
            "reviewState": asset["review_state"],
            "canonicalGraphId": graph_ids.get(asset["id"]),
            "hasCanonicalId": bool(graph_ids.get(asset["id"])),
            "hasLineage": bool(lineage),
            "hasRenderedOutputPath": bool(asset.get("output_path") and asset.get("campaign_path")),
            "hasCaption": bool(str(asset.get("caption") or "").strip()),
            "hasCaptionOutcomeContext": context_has_signal(caption_outcome_context),
            "captionOutcomeContext": caption_outcome_context,
            "audioStatus": audio_status,
            "hasAccountAssignment": bool(assignments_by_asset.get(asset["id"]) or plans_by_asset.get(asset["id"])),
            "distributionPlanCount": len(plans_by_asset.get(asset["id"], [])),
            "performanceSnapshotCount": len(snapshots_by_asset.get(asset["id"], [])),
            "postedStatus": _posted_status(asset_usage),
            "contentFingerprint": content_fingerprint,
            "sourceFamily": source_family,
        })

    schedule = _schedule_summary(plans, days=days)
    duplicate_risk = {
        "byRenderedAsset": rendered_asset_duplicate_risks,
        "byContentFingerprint": _duplicate_groups(content_fingerprint_groups),
        "bySourceReferenceOrFamily": _duplicate_groups(source_family_groups),
    }
    metrics = _metrics_status(asset_reports, snapshots_by_asset)
    posting_ledger_audit = _external_posting_ledger_audit(factory, campaign, days=days)
    readiness_state = _readiness_score(
        approved_count=len(approved_assets),
        missing=missing,
        unresolved_audio_count=len(unresolved_audio_assets),
        schedule=schedule,
        duplicate_risk=duplicate_risk,
        threadsdash_readiness=threadsdash_readiness,
        posting_ledger_audit=posting_ledger_audit,
    )
    blockers = _blocker_ranking(
        approved_count=len(approved_assets),
        missing=missing,
        unresolved_audio_assets=unresolved_audio_assets,
        schedule=schedule,
        duplicate_risk=duplicate_risk,
        metrics=metrics,
        snapshots_missing_caption_context=snapshots_missing_caption_context,
        threadsdash_readiness=threadsdash_readiness,
        posting_ledger_audit=posting_ledger_audit,
    )
    scale_readiness = _scale_readiness(
        readiness_state=readiness_state,
        approved_count=len(approved_assets),
        missing=missing,
        unresolved_audio_count=len(unresolved_audio_assets),
        schedule=schedule,
        duplicate_risk=duplicate_risk,
        threadsdash_readiness=threadsdash_readiness,
        posting_ledger_audit=posting_ledger_audit,
    )
    summary = _markdown_summary(
        campaign=campaign,
        days=days,
        readiness_state=readiness_state,
        approved_count=len(approved_assets),
        total_assets=len(assets),
        missing=missing,
        schedule=schedule,
        blockers=blockers,
        scale_readiness=scale_readiness,
        posting_ledger_audit=posting_ledger_audit,
    )
    return {
        "schema": "campaign_factory.mass_production_readiness_report.v1",
        "generatedAt": utc_now(),
        "campaign": {"id": campaign["id"], "slug": campaign["slug"], "name": campaign["name"]},
        "userId": user_id,
        "days": days,
        "targetReadinessModel": {
            "pilot": {"accounts": 5, "reelsPerAccountPerDay": 3, "days": days, "targetSlots": 5 * 3 * days},
            "twentyAccountScale": {"accounts": 20, "reelsPerAccountPerDayRange": [2, 3], "dailySlotRange": [40, 60], "targetSlotRange": [40 * days, 60 * days]},
            "full": {"accounts": 80, "reelsPerAccountPerDayRange": [2, 3], "dailySlotRange": [160, 240], "targetSlotRange": [160 * days, 240 * days]},
        },
        "counts": {
            "sourceAssets": len(source_rows),
            "renderedAssets": len(assets),
            "approvedAssets": len(approved_assets),
            "missingCanonicalIds": missing["canonicalIds"],
            "missingLineage": missing["lineage"],
            "missingRenderedOutputPath": missing["renderedOutputPath"],
            "missingCaption": missing["caption"],
            "missingCaptionOutcomeContext": missing["captionOutcomeContext"],
            "missingAudioStatus": missing["audioStatus"],
            "missingAccountAssignment": missing["accountAssignment"],
            "performanceSnapshotsMissingCaptionOutcomeContext": snapshots_missing_caption_context,
            "blockedByUnresolvedNativeAudio": len(unresolved_audio_assets),
            "threadDashExportRuns": len(exports),
        },
        "audioStatusCounts": dict(audio_status_counts),
        "assets": asset_reports,
        "schedule": schedule,
        "scaleReadiness": scale_readiness,
        "duplicateRisk": duplicate_risk,
        "externalPostingLedgerAudit": posting_ledger_audit,
        "threadDashExportReadiness": threadsdash_readiness or {
            "checked": False,
            "liveExportAllowed": None,
            "blockingReasons": ["not_checked"],
            "warnings": [],
        },
        "postedStatusCoverage": _posted_coverage(asset_reports),
        "metricsSyncStatus": metrics,
        "blockerRanking": blockers,
        "readinessScore": readiness_state,
        "markdownSummary": summary,
    }


def _campaign_by_id_or_slug(factory: CampaignFactory, campaign_id: str) -> dict[str, Any]:
    row = factory.conn.execute("SELECT * FROM campaigns WHERE id = ? OR slug = ?", (campaign_id, campaign_id)).fetchone()
    if not row:
        raise ValueError(f"campaign not found: {campaign_id}")
    return dict(row)


def _rows(factory: CampaignFactory, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in factory.conn.execute(query, params).fetchall()]


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    return grouped


def _graph_ids(factory: CampaignFactory, local_table: str, local_ids: list[str]) -> dict[str, str | None]:
    if not local_ids:
        return {}
    placeholders = ",".join("?" for _ in local_ids)
    rows = factory.conn.execute(
        f"SELECT local_id, global_id FROM content_graph_nodes WHERE local_table = ? AND local_id IN ({placeholders})",
        (local_table, *local_ids),
    ).fetchall()
    found = {row["local_id"]: row["global_id"] for row in rows}
    return {local_id: found.get(local_id) for local_id in local_ids}


def _extract_lineage(source_prompt: dict[str, Any], caption_generation: dict[str, Any]) -> dict[str, Any]:
    for value in (
        source_prompt.get("generatedAssetLineage"),
        source_prompt.get("generated_asset_lineage"),
        caption_generation.get("generatedAssetLineage"),
        caption_generation.get("generated_asset_lineage"),
    ):
        if isinstance(value, dict) and value:
            return value
    return {}


def _audio_status(source_prompt: dict[str, Any], caption_generation: dict[str, Any]) -> str:
    candidates = [
        caption_generation.get("audioIntent"),
        caption_generation.get("audio_intent"),
        source_prompt.get("audioIntent"),
        source_prompt.get("audio_intent"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("status"):
            return str(candidate["status"])
    return "missing"


def _content_fingerprint(asset: dict[str, Any], source_prompt: dict[str, Any], lineage: dict[str, Any]) -> str:
    existing = (
        source_prompt.get("contentFingerprint")
        or source_prompt.get("content_fingerprint")
        or ((lineage.get("quality") or {}).get("contentFingerprint") if isinstance(lineage.get("quality"), dict) else None)
        or asset.get("content_hash")
    )
    return str(existing or asset["id"])


def _source_family(asset: dict[str, Any], source: dict[str, Any] | None, source_prompt: dict[str, Any], lineage: dict[str, Any]) -> str:
    lineage_source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    candidates = [
        lineage_source.get("referenceId"),
        lineage_source.get("referencePattern"),
        lineage_source.get("patternCardId"),
        source_prompt.get("referenceId"),
        source_prompt.get("referencePattern"),
        source_prompt.get("sourceFamily"),
        source.get("content_hash") if source else None,
        asset.get("source_asset_id"),
    ]
    return str(next((candidate for candidate in candidates if candidate), asset["id"]))


def _posted_status(usage: dict[str, Any]) -> str:
    if int(usage.get("published") or 0) > 0:
        return "posted"
    if int(usage.get("scheduled") or 0) > 0:
        return "scheduled"
    if int(usage.get("draft") or 0) > 0:
        return "drafted"
    return "not_tracked"


def _duplicate_groups(groups: dict[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"key": key, "count": len(values), "renderedAssetIds": sorted(values)}
        for key, values in sorted(groups.items())
        if key and len(values) > 1
    ]


def _schedule_summary(plans: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    by_account_day: dict[str, dict[str, Any]] = {}
    failed = 0
    skipped = 0
    considered = 0
    for plan in plans:
        start_raw = plan.get("planned_window_start")
        slot = _parse_dt(start_raw)
        in_window = slot is None or (now <= slot <= horizon)
        if not in_window:
            continue
        considered += 1
        account = plan.get("instagram_account_id") or plan.get("account_id") or "unassigned"
        day = slot.date().isoformat() if slot else "unscheduled"
        surface = str(plan.get("surface") or "regular_reel")
        key = f"{account}|{day}"
        item = by_account_day.setdefault(key, {
            "account": account,
            "day": day,
            "total": 0,
            "main": 0,
            "trial": 0,
            "story": 0,
            "other": 0,
        })
        item["total"] += 1
        if surface == "regular_reel":
            item["main"] += 1
        elif surface == "trial_reel":
            item["trial"] += 1
        elif surface == "story_cta":
            item["story"] += 1
        else:
            item["other"] += 1
        reason = str(plan.get("reason_code") or "").lower()
        if "fail" in reason:
            failed += 1
        if "skip" in reason:
            skipped += 1
    rows = sorted(by_account_day.values(), key=lambda row: (row["day"], row["account"]))
    scheduled_slots = sum(row["main"] + row["trial"] for row in rows)
    pilot_target = 5 * 3 * days
    twenty_min_target = 20 * 2 * days
    twenty_max_target = 20 * 3 * days
    full_min_target = 160 * days
    full_max_target = 240 * days
    return {
        "days": days,
        "plannedRowsInWindow": considered,
        "accountDayPlannedSlotCounts": rows,
        "mainTrialCountsPerAccountDay": rows,
        "failedSlotCount": failed,
        "skippedSlotCount": skipped,
        "scheduledMainTrialSlots": scheduled_slots,
        "scheduleGaps": {
            "pilot": {"targetSlots": pilot_target, "scheduledSlots": scheduled_slots, "gap": max(0, pilot_target - scheduled_slots)},
            "twentyAccountScale": {
                "accounts": 20,
                "targetMinSlots": twenty_min_target,
                "targetMaxSlots": twenty_max_target,
                "scheduledSlots": scheduled_slots,
                "minGap": max(0, twenty_min_target - scheduled_slots),
                "maxGap": max(0, twenty_max_target - scheduled_slots),
            },
            "full": {
                "targetMinSlots": full_min_target,
                "targetMaxSlots": full_max_target,
                "scheduledSlots": scheduled_slots,
                "minGap": max(0, full_min_target - scheduled_slots),
                "maxGap": max(0, full_max_target - scheduled_slots),
            },
        },
    }


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _posted_coverage(asset_reports: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(asset["postedStatus"] for asset in asset_reports)
    tracked = sum(counts[status] for status in ("drafted", "scheduled", "posted"))
    return {
        "counts": dict(counts),
        "trackedAssets": tracked,
        "untrackedAssets": counts.get("not_tracked", 0),
        "coverageRatio": round(tracked / len(asset_reports), 4) if asset_reports else 0.0,
    }


def _metrics_status(asset_reports: list[dict[str, Any]], snapshots_by_asset: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    approved = [asset for asset in asset_reports if asset["reviewState"] == "approved"]
    with_metrics = [asset for asset in approved if snapshots_by_asset.get(asset["renderedAssetId"])]
    return {
        "approvedAssets": len(approved),
        "approvedAssetsWithMetrics": len(with_metrics),
        "approvedAssetsMissingMetrics": max(0, len(approved) - len(with_metrics)),
        "coverageRatio": round(len(with_metrics) / len(approved), 4) if approved else 0.0,
    }


def _readiness_score(
    *,
    approved_count: int,
    missing: Counter,
    unresolved_audio_count: int,
    schedule: dict[str, Any],
    duplicate_risk: dict[str, Any],
    threadsdash_readiness: dict[str, Any] | None,
    posting_ledger_audit: dict[str, Any],
) -> str:
    if (
        approved_count <= 0
        or missing["canonicalIds"]
        or missing["renderedOutputPath"]
        or unresolved_audio_count
        or posting_ledger_audit.get("matchingSlotCount")
        or (threadsdash_readiness and threadsdash_readiness.get("blockingReasons"))
    ):
        return "NOT_READY"
    if schedule["scheduleGaps"]["pilot"]["gap"] == 0 and not any(duplicate_risk.values()):
        if schedule["scheduleGaps"]["full"]["minGap"] == 0:
            return "SCALE_READY"
        return "PILOT_READY"
    return "NOT_READY"


def _blocker_ranking(
    *,
    approved_count: int,
    missing: Counter,
    unresolved_audio_assets: list[str],
    schedule: dict[str, Any],
    duplicate_risk: dict[str, Any],
    metrics: dict[str, Any],
    snapshots_missing_caption_context: int,
    threadsdash_readiness: dict[str, Any] | None,
    posting_ledger_audit: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    blockers: dict[str, list[dict[str, Any]]] = {
        "preventsProduction": [],
        "risksLosingTracking": [],
        "risksDuplicatePosting": [],
        "risksWastingPaidGeneration": [],
        "niceToHave": [],
    }
    if approved_count == 0:
        blockers["preventsProduction"].append(_blocker("no_approved_assets", "No approved assets are available for scheduling."))
    if missing["renderedOutputPath"]:
        blockers["preventsProduction"].append(_blocker("missing_rendered_output_path", f"{missing['renderedOutputPath']} assets are missing output paths."))
    if missing["accountAssignment"]:
        blockers["preventsProduction"].append(_blocker("missing_account_assignment", f"{missing['accountAssignment']} assets have no account assignment or distribution plan."))
    if unresolved_audio_assets:
        blockers["preventsProduction"].append(_blocker("unresolved_native_audio", f"{len(unresolved_audio_assets)} assets have unresolved native audio.", {"renderedAssetIds": unresolved_audio_assets}))
    if schedule["scheduleGaps"]["pilot"]["gap"] > 0:
        blockers["preventsProduction"].append(_blocker("pilot_schedule_gap", f"Pilot target is short by {schedule['scheduleGaps']['pilot']['gap']} slots."))
    if threadsdash_readiness and threadsdash_readiness.get("blockingReasons"):
        blockers["preventsProduction"].append(_blocker("threadsdash_export_blocked", "ThreadDash export readiness has blocking reasons.", {"blockingReasons": threadsdash_readiness.get("blockingReasons")}))
    if posting_ledger_audit.get("matchingSlotCount"):
        blockers["preventsProduction"].append(_blocker(
            "external_schedule_state_not_canonical",
            "Matching schedule/account slots exist in Reel Factory posting_ledger; mirror or migrate them into Campaign Factory before production.",
            {"matchingSlotCount": posting_ledger_audit.get("matchingSlotCount"), "ledgerPath": posting_ledger_audit.get("ledgerDbPath")},
        ))
    if missing["canonicalIds"]:
        blockers["risksLosingTracking"].append(_blocker("missing_canonical_ids", f"{missing['canonicalIds']} rendered assets lack Campaign Factory graph IDs."))
    if missing["lineage"]:
        blockers["risksLosingTracking"].append(_blocker("missing_lineage", f"{missing['lineage']} assets are missing generated lineage."))
    if missing["caption"]:
        blockers["risksLosingTracking"].append(_blocker("missing_caption", f"{missing['caption']} assets are missing captions."))
    if missing["audioStatus"]:
        blockers["risksLosingTracking"].append(_blocker("missing_audio_status", f"{missing['audioStatus']} assets are missing audio status metadata."))
    if metrics["approvedAssetsMissingMetrics"]:
        blockers["risksLosingTracking"].append(_blocker("missing_metrics_sync", f"{metrics['approvedAssetsMissingMetrics']} approved assets have no performance snapshot."))
    if missing["captionOutcomeContext"]:
        blockers["risksLosingTracking"].append(_blocker("missing_caption_outcome_context", f"{missing['captionOutcomeContext']} rendered assets are missing caption outcome context."))
    if snapshots_missing_caption_context:
        blockers["risksLosingTracking"].append(_blocker("missing_snapshot_caption_outcome_context", f"{snapshots_missing_caption_context} performance snapshots are missing caption outcome context."))
    if posting_ledger_audit.get("matchingSlotCount"):
        blockers["risksLosingTracking"].append(_blocker(
            "external_posting_ledger_slots",
            f"{posting_ledger_audit['matchingSlotCount']} matching posting slots exist in Reel Factory's local ledger outside Campaign Factory.",
            {"canonicalOwner": posting_ledger_audit.get("canonicalOwner"), "ledgerPath": posting_ledger_audit.get("ledgerDbPath")},
        ))
    for key, label in (
        ("byRenderedAsset", "rendered_asset_reuse"),
        ("byContentFingerprint", "content_fingerprint_reuse"),
        ("bySourceReferenceOrFamily", "source_family_reuse"),
    ):
        if duplicate_risk.get(key):
            blockers["risksDuplicatePosting"].append(_blocker(label, f"{len(duplicate_risk[key])} duplicate-risk groups found.", {"groups": duplicate_risk[key]}))
    if schedule["failedSlotCount"] or schedule["skippedSlotCount"]:
        blockers["risksWastingPaidGeneration"].append(_blocker("failed_or_skipped_slots", "Some planned slots are marked failed/skipped.", {"failed": schedule["failedSlotCount"], "skipped": schedule["skippedSlotCount"]}))
    if schedule["scheduleGaps"]["full"]["minGap"] > 0:
        blockers["niceToHave"].append(_blocker("full_scale_schedule_gap", f"Full-scale minimum target is short by {schedule['scheduleGaps']['full']['minGap']} slots."))
    return blockers


def _scale_readiness(
    *,
    readiness_state: str,
    approved_count: int,
    missing: Counter,
    unresolved_audio_count: int,
    schedule: dict[str, Any],
    duplicate_risk: dict[str, Any],
    threadsdash_readiness: dict[str, Any] | None,
    posting_ledger_audit: dict[str, Any],
) -> dict[str, Any]:
    common_blockers = _common_scale_blockers(
        approved_count=approved_count,
        missing=missing,
        unresolved_audio_count=unresolved_audio_count,
        duplicate_risk=duplicate_risk,
        threadsdash_readiness=threadsdash_readiness,
        posting_ledger_audit=posting_ledger_audit,
    )
    pilot_blockers = list(common_blockers)
    if schedule["scheduleGaps"]["pilot"]["gap"] > 0:
        pilot_blockers.append(f"pilot schedule is short by {schedule['scheduleGaps']['pilot']['gap']} slots")
    twenty_blockers = list(common_blockers)
    if schedule["scheduleGaps"]["twentyAccountScale"]["minGap"] > 0:
        twenty_blockers.append(f"20-account schedule is short by {schedule['scheduleGaps']['twentyAccountScale']['minGap']} minimum slots")
    full_blockers = list(common_blockers)
    if schedule["scheduleGaps"]["full"]["minGap"] > 0:
        full_blockers.append(f"80-account schedule is short by {schedule['scheduleGaps']['full']['minGap']} minimum slots")
    return {
        "pilot5Accounts": {
            "target": "5 accounts x 3 reels/day x days",
            "ready": readiness_state in {"PILOT_READY", "SCALE_READY"},
            "blockingReasons": pilot_blockers,
        },
        "twentyAccounts": {
            "target": "20 accounts x 2-3 reels/day x days",
            "ready": not twenty_blockers,
            "blockingReasons": twenty_blockers,
        },
        "eightyAccounts": {
            "target": "80 accounts x 2-3 reels/day",
            "ready": readiness_state == "SCALE_READY" and not full_blockers,
            "blockingReasons": full_blockers,
        },
    }


def _common_scale_blockers(
    *,
    approved_count: int,
    missing: Counter,
    unresolved_audio_count: int,
    duplicate_risk: dict[str, Any],
    threadsdash_readiness: dict[str, Any] | None,
    posting_ledger_audit: dict[str, Any],
) -> list[str]:
    reasons = []
    if approved_count <= 0:
        reasons.append("no approved assets")
    if missing["canonicalIds"]:
        reasons.append(f"{missing['canonicalIds']} assets missing Campaign Factory canonical IDs")
    if missing["lineage"]:
        reasons.append(f"{missing['lineage']} assets missing lineage")
    if missing["renderedOutputPath"]:
        reasons.append(f"{missing['renderedOutputPath']} assets missing rendered output paths")
    if missing["caption"]:
        reasons.append(f"{missing['caption']} assets missing captions")
    if missing["audioStatus"]:
        reasons.append(f"{missing['audioStatus']} assets missing audio status")
    if missing["accountAssignment"]:
        reasons.append(f"{missing['accountAssignment']} assets missing account assignment or distribution plan")
    if unresolved_audio_count:
        reasons.append(f"{unresolved_audio_count} assets blocked by unresolved native audio")
    if any(duplicate_risk.values()):
        reasons.append("duplicate risk exists by rendered asset, fingerprint, or source family")
    if threadsdash_readiness and threadsdash_readiness.get("blockingReasons"):
        reasons.append("ThreadDash export readiness has blocking reasons")
    if posting_ledger_audit.get("matchingSlotCount"):
        reasons.append("Reel Factory posting_ledger has matching external slots; migrate or mirror schedule state into Campaign Factory")
    return reasons


def _external_posting_ledger_audit(factory: CampaignFactory, campaign: dict[str, Any], *, days: int) -> dict[str, Any]:
    reel_root = Path(factory.settings.reel_factory_root)
    ledger_db = reel_root / "manifest.sqlite"
    base = {
        "schema": "campaign_factory.external_posting_ledger_audit.v1",
        "ownership": "external_local_tooling_only",
        "canonicalOwner": "Campaign Factory distribution_plans, asset_account_assignments, ThreadDash exports, and performance_snapshots",
        "ledgerDbPath": str(ledger_db),
        "exists": ledger_db.exists(),
        "matchingSlotCount": 0,
        "statusCounts": {},
        "slotTypeCounts": {},
        "accountDayCounts": [],
        "requiresMigrationToCampaignFactory": False,
        "notes": [
            "Reel Factory posting_ledger.py is not canonical schedule/account state.",
            "If operators use it for planning, mirror or migrate those slots into Campaign Factory before pilot or scale reporting.",
        ],
    }
    if not ledger_db.exists():
        return base
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{ledger_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posting_slots'").fetchone()
        if not table:
            return {**base, "exists": True, "notes": [*base["notes"], "manifest.sqlite exists but has no posting_slots table."]}
        campaign_keys = (campaign["id"], campaign["slug"])
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT posting_slot_id, account_id, account_handle, campaign_id, date, slot_type, post_status, content_fingerprint, rendered_output_path
                FROM posting_slots
                WHERE campaign_id IN (?, ?)
                """,
                campaign_keys,
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        return {**base, "exists": True, "error": str(exc), "requiresMigrationToCampaignFactory": True}
    finally:
        if conn is not None:
            conn.close()
    promoted_slot_ids = _promoted_reel_slot_ids(factory, rows)
    unpromoted_rows = [row for row in rows if row.get("posting_slot_id") not in promoted_slot_ids]
    status_counts = Counter(row.get("post_status") or "unknown" for row in unpromoted_rows)
    slot_type_counts = Counter(row.get("slot_type") or "unknown" for row in unpromoted_rows)
    account_day: dict[str, dict[str, Any]] = {}
    for row in unpromoted_rows:
        key = f"{row.get('account_id') or row.get('account_handle')}|{row.get('date')}"
        item = account_day.setdefault(key, {
            "account": row.get("account_id") or row.get("account_handle") or "unknown",
            "day": row.get("date"),
            "total": 0,
        })
        item["total"] += 1
    return {
        **base,
        "matchingSlotCount": len(unpromoted_rows),
        "promotedSlotCount": len(promoted_slot_ids),
        "totalExternalSlotCount": len(rows),
        "statusCounts": dict(status_counts),
        "slotTypeCounts": dict(slot_type_counts),
        "accountDayCounts": sorted(account_day.values(), key=lambda row: (row["day"] or "", row["account"])),
        "requiresMigrationToCampaignFactory": bool(unpromoted_rows),
    }


def _promoted_reel_slot_ids(factory: CampaignFactory, rows: list[dict[str, Any]]) -> set[str]:
    slot_ids = [str(row.get("posting_slot_id") or "") for row in rows if row.get("posting_slot_id")]
    if not slot_ids:
        return set()
    placeholders = ",".join("?" for _ in slot_ids)
    graph_rows = factory.conn.execute(
        f"""
        SELECT external_id FROM content_graph_nodes
        WHERE external_system = 'reel_factory.posting_ledger'
          AND external_id IN ({placeholders})
        """,
        tuple(slot_ids),
    ).fetchall()
    graph_slot_ids = {row["external_id"] for row in graph_rows}
    reason_rows = factory.conn.execute(
        f"""
        SELECT reason_code FROM distribution_plans
        WHERE reason_code IN ({placeholders})
        """,
        tuple(f"reel_ledger:{slot_id}" for slot_id in slot_ids),
    ).fetchall()
    reason_slot_ids = {str(row["reason_code"]).split(":", 1)[1] for row in reason_rows if ":" in str(row["reason_code"])}
    return graph_slot_ids | reason_slot_ids


def _blocker(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def _markdown_summary(
    *,
    campaign: dict[str, Any],
    days: int,
    readiness_state: str,
    approved_count: int,
    total_assets: int,
    missing: Counter,
    schedule: dict[str, Any],
    blockers: dict[str, list[dict[str, Any]]],
    scale_readiness: dict[str, Any],
    posting_ledger_audit: dict[str, Any],
) -> str:
    lines = [
        f"# Mass Production Readiness: {campaign['slug']}",
        "",
        f"- Readiness score: **{readiness_state}**",
        f"- Window: {days} days",
        f"- Approved assets: {approved_count}/{total_assets}",
        f"- Pilot slots: {schedule['scheduleGaps']['pilot']['scheduledSlots']}/{schedule['scheduleGaps']['pilot']['targetSlots']} scheduled",
        f"- 20-account slots: {schedule['scheduleGaps']['twentyAccountScale']['scheduledSlots']}/{schedule['scheduleGaps']['twentyAccountScale']['targetMinSlots']}-{schedule['scheduleGaps']['twentyAccountScale']['targetMaxSlots']} scheduled",
        f"- Full-scale slots: {schedule['scheduleGaps']['full']['scheduledSlots']}/{schedule['scheduleGaps']['full']['targetMinSlots']}-{schedule['scheduleGaps']['full']['targetMaxSlots']} scheduled",
        f"- Missing canonical IDs: {missing['canonicalIds']}",
        f"- Missing lineage: {missing['lineage']}",
        f"- Missing account assignment: {missing['accountAssignment']}",
        f"- External Reel Factory posting ledger slots: {posting_ledger_audit.get('matchingSlotCount', 0)}",
        "",
        "## Scale Answers",
        f"- 5-account pilot: {'ready' if scale_readiness['pilot5Accounts']['ready'] else 'blocked'}",
        f"- 20-account scale: {'ready' if scale_readiness['twentyAccounts']['ready'] else 'blocked'}",
        f"- 80-account scale: {'ready' if scale_readiness['eightyAccounts']['ready'] else 'blocked'}",
        "",
        "## Blockers",
    ]
    for section, items in blockers.items():
        lines.append(f"### {section}")
        if not items:
            lines.append("- none")
        else:
            lines.extend(f"- `{item['code']}`: {item['message']}" for item in items)
    return "\n".join(lines)
