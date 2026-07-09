from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .caption_outcome import build_caption_outcome_context, column_values
from .core import (
    CampaignFactory,
    media_type_for_path,
    new_id,
    sha256_file,
    slugify,
    utc_now,
)

SCHEMA = "campaign_factory.reel_ledger_promotion_preview.v1"
PROMOTED_EVENT = "reel_ledger_promoted"
REEL_SLOT_EXTERNAL_SYSTEM = "reel_factory.posting_ledger"
PROMOTED_REASON_PREFIX = "reel_ledger"
PROMOTABLE_STATUSES = {
    "ready_for_review",
    "approved",
    "scheduled",
    "posted",
    "metrics_imported",
}
NON_PROMOTABLE_STATUSES = {"planned", "skipped", "failed"}
BLOCK_AUDIO_STATUSES = {"approved", "scheduled", "posted", "metrics_imported"}
SAFE_AUDIO_STATUSES = {"selected", "attached", "verified", "skipped", "not_required"}
PLATFORM_PROOF_KEYS = {
    "post_url",
    "platform_post_id",
    "post_id",
    "permalink",
    "ig_media_id",
    "instagram_media_id",
}


def promote_reel_ledger(
    factory: CampaignFactory,
    *,
    campaign_id: str,
    reel_factory_root: Path,
    days: int = 7,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or apply promotion from Reel Factory local posting ledger."""
    campaign = _campaign_by_id_or_slug(factory, campaign_id)
    ledger_db = Path(reel_factory_root).expanduser().resolve() / "manifest.sqlite"
    rows = _read_reel_slots(ledger_db, campaign)
    preview = _build_preview(
        factory,
        campaign=campaign,
        ledger_db=ledger_db,
        rows=rows,
        days=days,
        apply=apply,
    )
    if not apply:
        return preview
    if preview["blocked"] or preview["conflicts"]:
        return {
            **preview,
            "applied": False,
            "applyBlocked": True,
            "blockingReasons": sorted(
                {item["reason"] for item in preview["blocked"]}
                | {item["reason"] for item in preview["conflicts"]}
            ),
        }
    _apply_preview(factory, campaign=campaign, preview=preview)
    return {**preview, "applied": True, "applyBlocked": False}


def _campaign_by_id_or_slug(factory: CampaignFactory, value: str) -> dict[str, Any]:
    row = factory.conn.execute(
        "SELECT * FROM campaigns WHERE id = ? OR slug = ?", (value, slugify(value))
    ).fetchone()
    if not row:
        raise ValueError(f"campaign not found: {value}")
    return dict(row)


def _read_reel_slots(ledger_db: Path, campaign: dict[str, Any]) -> list[dict[str, Any]]:
    if not ledger_db.exists():
        raise FileNotFoundError(f"Reel Factory manifest.sqlite not found: {ledger_db}")
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{ledger_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='posting_slots'"
        ).fetchone()
        if not table:
            raise ValueError(
                f"Reel Factory ledger has no posting_slots table: {ledger_db}"
            )
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM posting_slots WHERE campaign_id IN (?, ?) ORDER BY date, planned_slot_time, account_id, slot_type",
                (campaign["id"], campaign["slug"]),
            ).fetchall()
        ]
    finally:
        if conn is not None:
            conn.close()


def _build_preview(
    factory: CampaignFactory,
    *,
    campaign: dict[str, Any],
    ledger_db: Path,
    rows: list[dict[str, Any]],
    days: int,
    apply: bool,
    applied: bool = False,
) -> dict[str, Any]:
    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    promotable_rows = [
        row for row in rows if str(row.get("post_status") or "") in PROMOTABLE_STATUSES
    ]
    account_day_counts = Counter(
        (
            str(row.get("account_id") or row.get("account_handle") or "unassigned"),
            str(row.get("date") or ""),
        )
        for row in promotable_rows
        if _surface_for_slot(row) in {"regular_reel", "trial_reel"}
    )
    fingerprint_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in promotable_rows:
        fp = str(row.get("content_fingerprint") or "").strip()
        if fp:
            fingerprint_rows[fp].append(row)

    for row in rows:
        slot_id = str(row.get("posting_slot_id") or "")
        status = str(row.get("post_status") or "planned")
        if status in NON_PROMOTABLE_STATUSES:
            skipped.append(_row_note(row, "non_promotable_status"))
            continue
        if status not in PROMOTABLE_STATUSES:
            skipped.append(_row_note(row, "unknown_status"))
            continue
        existing = _existing_promotion(factory, slot_id)
        issues = _row_blockers(row)
        if (
            account_day_counts[
                (
                    str(
                        row.get("account_id")
                        or row.get("account_handle")
                        or "unassigned"
                    ),
                    str(row.get("date") or ""),
                )
            ]
            > 3
        ):
            conflicts.append(_row_note(row, "account_day_quota_exceeded"))
            continue
        fp = str(row.get("content_fingerprint") or "").strip()
        duplicate_rows = fingerprint_rows.get(fp, []) if fp else []
        if len(duplicate_rows) > 1 and not existing:
            conflicts.append(
                _row_note(
                    row,
                    "duplicate_content_fingerprint",
                    {
                        "contentFingerprint": fp,
                        "slotIds": [r.get("posting_slot_id") for r in duplicate_rows],
                    },
                )
            )
            continue
        if fp:
            existing_asset = factory.conn.execute(
                "SELECT id FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
                (campaign["id"], fp),
            ).fetchone()
            if existing_asset and not existing:
                conflicts.append(
                    _row_note(
                        row,
                        "duplicate_content_fingerprint",
                        {
                            "contentFingerprint": fp,
                            "renderedAssetId": existing_asset["id"],
                        },
                    )
                )
                continue
        if issues:
            blocked.extend(_row_note(row, reason) for reason in issues)
            continue
        action = _promotion_action(factory, campaign, row, existing)
        if existing:
            updates.append(action)
        else:
            creates.append(action)

    return {
        "schema": SCHEMA,
        "campaign": {
            "id": campaign["id"],
            "slug": campaign["slug"],
            "name": campaign["name"],
        },
        "apply": apply,
        "applied": applied,
        "days": days,
        "source": {
            "ledgerDbPath": str(ledger_db),
            "matchingSlotCount": len(rows),
            "promotableSlotCount": len(promotable_rows),
        },
        "summary": {
            "rowsToCreate": len(creates),
            "rowsToUpdate": len(updates),
            "blockedRows": len(blocked),
            "conflictCount": len(conflicts),
            "missingLineageCount": sum(
                1 for item in blocked if item["reason"] == "missing_lineage"
            ),
            "missingAudioCount": sum(
                1 for item in blocked if item["reason"] == "missing_audio"
            ),
            "duplicateFingerprintRiskCount": sum(
                1
                for item in conflicts
                if item["reason"] == "duplicate_content_fingerprint"
            ),
            "accountDayQuotaIssueCount": sum(
                1
                for item in conflicts
                if item["reason"] == "account_day_quota_exceeded"
            ),
            "skippedRows": len(skipped),
        },
        "creates": creates,
        "updates": updates,
        "conflicts": conflicts,
        "blocked": blocked,
        "skipped": skipped,
    }


def _row_blockers(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    output = Path(str(row.get("rendered_output_path") or "")).expanduser()
    if not row.get("rendered_output_path"):
        reasons.append("missing_rendered_output_path")
    elif not output.exists():
        reasons.append("missing_rendered_output_file")
    if not _lineage(row):
        reasons.append("missing_lineage")
    if not str(row.get("caption") or "").strip():
        reasons.append("missing_caption")
    if (
        str(row.get("post_status") or "") in BLOCK_AUDIO_STATUSES
        and _audio_intent(row)["status"] not in SAFE_AUDIO_STATUSES
    ):
        reasons.append("missing_audio")
    return reasons


def _promotion_action(
    factory: CampaignFactory,
    campaign: dict[str, Any],
    row: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    lineage = _lineage(row)
    output_path = Path(str(row["rendered_output_path"])).expanduser().resolve()
    fingerprint = str(row.get("content_fingerprint") or "").strip() or sha256_file(
        output_path
    )
    account_handle = str(
        row.get("account_handle") or row.get("account_id") or "unassigned"
    ).lstrip("@")
    account_id = str(row.get("account_id") or account_handle)
    platform_proof = _platform_proof(row)
    status = str(row.get("post_status") or "")
    posted_state = (
        status
        if status not in {"posted", "metrics_imported"} or platform_proof
        else "unverified_platform_post"
    )
    caption_context = build_caption_outcome_context(
        caption_text=str(row.get("caption") or ""),
        render_recipe=lineage.get("recipe") if isinstance(lineage, dict) else None,
        source_clip=row.get("reel_clip_stem"),
        rendered_output=str(output_path),
        creator_model=_model_slug_for_campaign(factory, campaign["id"]),
        lineage=lineage,
    )
    return {
        "postingSlotId": row["posting_slot_id"],
        "action": "update" if existing else "create",
        "existing": existing or {},
        "account": {
            "id": account_id,
            "handle": account_handle,
            "platform": _platform(row),
        },
        "renderedAsset": {
            "contentHash": fingerprint,
            "outputPath": str(output_path),
            "filename": output_path.name,
            "caption": str(row.get("caption") or ""),
        },
        "captionOutcomeContext": caption_context,
        "distributionPlan": {
            "surface": _surface_for_slot(row),
            "plannedWindowStart": _planned_window_start(row),
            "reasonCode": _reason_code(row),
        },
        "lineage": lineage,
        "audioIntent": _audio_intent(row),
        "status": {
            "reelLedgerStatus": status,
            "campaignFactoryReviewState": _review_state(row),
            "promotedPostState": posted_state,
            "platformProof": platform_proof,
        },
    }


def _apply_preview(
    factory: CampaignFactory, *, campaign: dict[str, Any], preview: dict[str, Any]
) -> None:
    for action in [*preview["creates"], *preview["updates"]]:
        _apply_action(factory, campaign, action)
    factory.record_event(
        PROMOTED_EVENT,
        campaign_id=campaign["id"],
        status="success",
        message=f"Promoted {len(preview['creates']) + len(preview['updates'])} Reel Factory ledger slots",
        metadata={
            "schema": SCHEMA,
            "source": preview["source"],
            "summary": preview["summary"],
            "postingSlotIds": [
                item["postingSlotId"]
                for item in [*preview["creates"], *preview["updates"]]
            ],
        },
    )


def _apply_action(
    factory: CampaignFactory, campaign: dict[str, Any], action: dict[str, Any]
) -> None:
    account = factory.upsert_account(
        action["account"]["handle"],
        platform=action["account"]["platform"],
        external_id=action["account"]["id"],
    )
    source = _upsert_source_asset(factory, campaign, action)
    rendered = _upsert_rendered_asset(factory, campaign, source, action)
    _upsert_assignment(factory, campaign, rendered["id"], account, action)
    _upsert_distribution_plan(factory, campaign, rendered["id"], account, action)
    slot_graph = factory.ensure_graph_node(
        "reel_ledger_slot",
        external_system=REEL_SLOT_EXTERNAL_SYSTEM,
        external_id=action["postingSlotId"],
        payload=action,
    )
    rendered_graph = factory.ensure_graph_node(
        "rendered_asset",
        local_table="rendered_assets",
        local_id=rendered["id"],
        payload={
            "promotedFromReelLedgerSlotId": action["postingSlotId"],
            "contentHash": rendered["content_hash"],
        },
    )
    factory.ensure_graph_edge(
        slot_graph, rendered_graph, "reel_ledger_slot_promoted_to_rendered_asset"
    )
    factory.conn.commit()


def _upsert_source_asset(
    factory: CampaignFactory, campaign: dict[str, Any], action: dict[str, Any]
) -> dict[str, Any]:
    model_id = _model_id_for_campaign(factory, campaign["id"])
    lineage = action["lineage"]
    lineage_source = (
        lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    )
    source_key = str(
        lineage_source.get("referenceId")
        or lineage_source.get("sourceReferenceId")
        or lineage_source.get("referencePath")
        or action["renderedAsset"]["contentHash"]
    )
    source_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], source_hash),
    ).fetchone()
    source_prompt = {
        "schema": "campaign_factory.reel_ledger_promoted_source.v1",
        "promotedFrom": REEL_SLOT_EXTERNAL_SYSTEM,
        "postingSlotId": action["postingSlotId"],
        "promptId": f"prompt_reel_ledger_{action['postingSlotId']}",
        "referenceId": source_key,
        "generationTool": "reel_factory_posting_ledger",
        "generatedAssetLineage": lineage,
        "contentFingerprint": action["renderedAsset"]["contentHash"],
    }
    now = utc_now()
    rendered_path = action["renderedAsset"]["outputPath"]
    if row:
        factory.conn.execute(
            "UPDATE source_assets SET source_prompt = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                now,
                row["id"],
            ),
        )
        return dict(
            factory.conn.execute(
                "SELECT * FROM source_assets WHERE id = ?", (row["id"],)
            ).fetchone()
        )
    source_id = new_id("src")
    filename = f"reel_ledger_{slugify(source_key)[:40] or action['postingSlotId']}"
    factory.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path, filename, media_type, platform,
         source_prompt, notes, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'promoted', ?, ?)
        """,
        (
            source_id,
            campaign["id"],
            model_id,
            source_hash,
            rendered_path,
            rendered_path,
            filename,
            media_type_for_path(rendered_path),
            campaign["platform"],
            json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
            f"Promoted from Reel Factory posting slot {action['postingSlotId']}",
            now,
            now,
        ),
    )
    factory.ensure_graph_node(
        "source_asset",
        local_table="source_assets",
        local_id=source_id,
        payload=source_prompt,
    )
    return dict(
        factory.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()
    )


def _upsert_rendered_asset(
    factory: CampaignFactory,
    campaign: dict[str, Any],
    source: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    content_hash = action["renderedAsset"]["contentHash"]
    caption_context = action.get("captionOutcomeContext") or {}
    caption_columns = column_values(caption_context)
    render_recipe = caption_context.get("render_recipe") or "reel_ledger_promotion"
    row = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], content_hash),
    ).fetchone()
    caption_generation = {
        "schema": "campaign_factory.reel_ledger_promoted_render.v1",
        "generatedAssetLineage": action["lineage"],
        "audioIntent": action["audioIntent"],
        "reelLedger": {
            "postingSlotId": action["postingSlotId"],
            "status": action["status"],
        },
    }
    now = utc_now()
    values = (
        source["id"],
        action["renderedAsset"]["outputPath"],
        action["renderedAsset"]["outputPath"],
        action["renderedAsset"]["filename"],
        action["renderedAsset"]["caption"],
        caption_columns["caption_hash"],
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
        json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
        render_recipe,
        _review_state_from_status(action["status"]["campaignFactoryReviewState"]),
        now,
    )
    if row:
        factory.conn.execute(
            """
            UPDATE rendered_assets
            SET source_asset_id = ?, output_path = ?, campaign_path = ?, filename = ?, caption = ?,
                caption_hash = ?, caption_bank = ?, caption_banks_json = ?, creator_mix = ?,
                creator_model = ?, frame_type = ?, length_class = ?, format_class = ?,
                caption_fit_version = ?, suitability_decision = ?, suitability_reason = ?,
                source_clip = ?, caption_outcome_context_json = ?, caption_generation_json = ?,
                recipe = ?, review_state = ?, updated_at = ?
            WHERE id = ?
            """,
            (*values, row["id"]),
        )
        return dict(
            factory.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = ?", (row["id"],)
            ).fetchone()
        )
    rendered_id = new_id("asset")
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption,
         caption_hash, caption_bank, caption_banks_json, creator_mix, creator_model, frame_type,
         length_class, format_class, caption_fit_version, suitability_decision, suitability_reason,
         source_clip, caption_outcome_context_json, caption_generation_json, recipe, audit_status,
         review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            rendered_id,
            campaign["id"],
            source["id"],
            content_hash,
            action["renderedAsset"]["outputPath"],
            action["renderedAsset"]["outputPath"],
            action["renderedAsset"]["filename"],
            action["renderedAsset"]["caption"],
            caption_columns["caption_hash"],
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
            json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
            render_recipe,
            _review_state_from_status(action["status"]["campaignFactoryReviewState"]),
            now,
            now,
        ),
    )
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )


def _upsert_assignment(
    factory: CampaignFactory,
    campaign: dict[str, Any],
    rendered_asset_id: str,
    account: dict[str, Any],
    action: dict[str, Any],
) -> None:
    existing = factory.conn.execute(
        """
        SELECT id FROM asset_account_assignments
        WHERE campaign_id = ? AND rendered_asset_id = ? AND account_id = ? AND COALESCE(instagram_account_id, '') = COALESCE(?, '')
        """,
        (campaign["id"], rendered_asset_id, account["id"], action["account"]["id"]),
    ).fetchone()
    now = utc_now()
    caption_columns = column_values(action.get("captionOutcomeContext") or {})
    if existing:
        factory.conn.execute(
            """
            UPDATE asset_account_assignments
            SET planned_window_start = ?, caption_hash = ?, caption_text = ?, caption_bank = ?,
                caption_banks_json = ?, creator_mix = ?, creator_model = ?, frame_type = ?,
                length_class = ?, format_class = ?, caption_fit_version = ?, suitability_decision = ?,
                suitability_reason = ?, source_clip = ?, caption_outcome_context_json = ?,
                notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                action["distributionPlan"]["plannedWindowStart"],
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
                f"Promoted from Reel slot {action['postingSlotId']}",
                now,
                existing["id"],
            ),
        )
        return
    factory.conn.execute(
        """
        INSERT INTO asset_account_assignments
        (id, campaign_id, rendered_asset_id, account_id, instagram_account_id, planned_window_start,
         caption_hash, caption_text, caption_bank, caption_banks_json, creator_mix, creator_model,
         frame_type, length_class, format_class, caption_fit_version, suitability_decision,
         suitability_reason, source_clip, caption_outcome_context_json, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id("assign"),
            campaign["id"],
            rendered_asset_id,
            account["id"],
            action["account"]["id"],
            action["distributionPlan"]["plannedWindowStart"],
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
            f"Promoted from Reel slot {action['postingSlotId']}",
            now,
            now,
        ),
    )


def _upsert_distribution_plan(
    factory: CampaignFactory,
    campaign: dict[str, Any],
    rendered_asset_id: str,
    account: dict[str, Any],
    action: dict[str, Any],
) -> None:
    reason_code = action["distributionPlan"]["reasonCode"]
    existing = factory.conn.execute(
        "SELECT id FROM distribution_plans WHERE campaign_id = ? AND reason_code = ?",
        (campaign["id"], reason_code),
    ).fetchone()
    now = utc_now()
    caption_columns = column_values(action.get("captionOutcomeContext") or {})
    payload = (
        rendered_asset_id,
        account["id"],
        action["account"]["id"],
        action["distributionPlan"]["surface"],
        action["distributionPlan"]["plannedWindowStart"],
        reason_code,
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
    )
    if existing:
        factory.conn.execute(
            """
            UPDATE distribution_plans
            SET rendered_asset_id = ?, account_id = ?, instagram_account_id = ?, surface = ?,
                planned_window_start = ?, reason_code = ?, caption_hash = ?, caption_text = ?,
                caption_bank = ?, caption_banks_json = ?, creator_mix = ?, creator_model = ?,
                frame_type = ?, length_class = ?, format_class = ?, caption_fit_version = ?,
                suitability_decision = ?, suitability_reason = ?, source_clip = ?,
                caption_outcome_context_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (*payload, existing["id"]),
        )
        return
    factory.conn.execute(
        """
        INSERT INTO distribution_plans
        (id, campaign_id, rendered_asset_id, account_id, instagram_account_id, surface,
         planned_window_start, reason_code, caption_hash, caption_text, caption_bank,
         caption_banks_json, creator_mix, creator_model, frame_type, length_class,
         format_class, caption_fit_version, suitability_decision, suitability_reason,
         source_clip, caption_outcome_context_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id("dist"),
            campaign["id"],
            rendered_asset_id,
            account["id"],
            action["account"]["id"],
            action["distributionPlan"]["surface"],
            action["distributionPlan"]["plannedWindowStart"],
            reason_code,
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


def _existing_promotion(
    factory: CampaignFactory, slot_id: str
) -> dict[str, Any] | None:
    dist = factory.conn.execute(
        "SELECT * FROM distribution_plans WHERE reason_code = ?",
        (_reason_code({"posting_slot_id": slot_id}),),
    ).fetchone()
    graph = factory.conn.execute(
        "SELECT global_id FROM content_graph_nodes WHERE external_system = ? AND external_id = ?",
        (REEL_SLOT_EXTERNAL_SYSTEM, slot_id),
    ).fetchone()
    if not dist and not graph:
        return None
    return {
        "distributionPlanId": dist["id"] if dist else None,
        "renderedAssetId": dist["rendered_asset_id"] if dist else None,
        "graphId": graph["global_id"] if graph else None,
    }


def _model_id_for_campaign(factory: CampaignFactory, campaign_id: str) -> str:
    row = factory.conn.execute(
        "SELECT model_id FROM source_assets WHERE campaign_id = ? ORDER BY created_at LIMIT 1",
        (campaign_id,),
    ).fetchone()
    if row and row["model_id"]:
        return row["model_id"]
    return factory.upsert_model("reel_factory_pilot", name="Reel Factory Pilot")["id"]


def _model_slug_for_campaign(factory: CampaignFactory, campaign_id: str) -> str | None:
    row = factory.conn.execute(
        """
        SELECT m.slug
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        WHERE s.campaign_id = ?
        ORDER BY s.created_at
        LIMIT 1
        """,
        (campaign_id,),
    ).fetchone()
    if row:
        return row["slug"]
    campaign = factory.conn.execute(
        "SELECT root_path FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign and campaign["root_path"]:
        return Path(str(campaign["root_path"])).parent.name or None
    return None


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    lineage = _json_dict(row.get("lineage_json"))
    if lineage:
        return _merge_caption_lineage_sidecar(lineage, row)
    path = row.get("lineage_path")
    if path:
        try:
            payload = json.loads(
                Path(str(path)).expanduser().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        return (
            _merge_caption_lineage_sidecar(payload, row)
            if isinstance(payload, dict)
            else {}
        )
    return {}


def _merge_caption_lineage_sidecar(
    lineage: dict[str, Any], row: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(lineage, dict):
        return {}
    if isinstance(lineage.get("captionBank"), dict) or isinstance(
        lineage.get("captionLineage"), dict
    ):
        return lineage
    caption_lineage = _caption_lineage_sidecar(row)
    if not caption_lineage:
        return lineage
    merged = dict(lineage)
    merged["captionBank"] = caption_lineage
    if caption_lineage.get("captionHash") and not merged.get("captionHash"):
        merged["captionHash"] = caption_lineage["captionHash"]
    if isinstance(caption_lineage.get("captionOutcomeContext"), dict):
        merged.setdefault(
            "captionOutcomeContext", caption_lineage["captionOutcomeContext"]
        )
    return merged


def _caption_lineage_sidecar(row: dict[str, Any]) -> dict[str, Any]:
    output = row.get("rendered_output_path")
    if not output:
        return {}
    output_path = Path(str(output)).expanduser()
    candidates = [
        output_path.with_suffix(output_path.suffix + ".caption_lineage.json"),
        output_path.with_suffix(".caption_lineage.json"),
        output_path.parent / f"{output_path.stem}.caption_lineage.json",
    ]
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _audio_intent(row: dict[str, Any]) -> dict[str, Any]:
    track_id = str(row.get("audio_track_id") or "").strip()
    manual_needed = bool(row.get("manual_audio_needed"))
    status = (
        "selected"
        if track_id
        else ("needs_operator_selection" if manual_needed else "missing")
    )
    selection = {
        key: value
        for key, value in {
            "platform_audio_id": track_id or None,
            "track_id": track_id or None,
            "source": row.get("audio_source"),
            "selected_reason": row.get("audio_selected_reason"),
        }.items()
        if value
    }
    return {
        "schema": "pipeline.audio_intent.v1",
        "mode": row.get("audio_source") or "native_platform_audio",
        "required": status != "not_required",
        "status": status,
        **(
            {"operator_selection": selection, "audio_selection": selection}
            if selection
            else {}
        ),
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _surface_for_slot(row: dict[str, Any]) -> str:
    slot_type = str(row.get("slot_type") or "main")
    return "regular_reel" if slot_type == "main" else "trial_reel"


def _planned_window_start(row: dict[str, Any]) -> str | None:
    date_raw = str(row.get("date") or "").strip()
    time_raw = str(row.get("planned_slot_time") or "10:00").strip()
    if not date_raw:
        return None
    hour, minute = 10, 0
    try:
        parts = time_raw.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        pass
    local_tz = ZoneInfo("America/New_York")
    local_slot = datetime.combine(
        datetime.fromisoformat(date_raw).date(),
        datetime_time(hour=hour, minute=minute),
        tzinfo=local_tz,
    )
    return local_slot.astimezone(UTC).isoformat()


def _reason_code(row: dict[str, Any]) -> str:
    return f"{PROMOTED_REASON_PREFIX}:{row.get('posting_slot_id')}"


def _review_state(row: dict[str, Any]) -> str:
    status = str(row.get("post_status") or "")
    return (
        "approved"
        if status in {"approved", "scheduled", "posted", "metrics_imported"}
        else "draft"
    )


def _review_state_from_status(value: str) -> str:
    return "approved" if value == "approved" else "draft"


def _platform(row: dict[str, Any]) -> str:
    platform = str(row.get("platform") or "instagram").lower()
    return "instagram" if platform in {"ig", "instagram"} else platform


def _platform_proof(row: dict[str, Any]) -> dict[str, Any]:
    proof = {key: row.get(key) for key in PLATFORM_PROOF_KEYS if row.get(key)}
    lineage = _lineage(row)
    platform = (
        lineage.get("platform") if isinstance(lineage.get("platform"), dict) else {}
    )
    for key in PLATFORM_PROOF_KEYS:
        if platform.get(key):
            proof[key] = platform[key]
    return proof


def _row_note(
    row: dict[str, Any], reason: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "postingSlotId": row.get("posting_slot_id"),
        "reason": reason,
        "postStatus": row.get("post_status"),
        "accountId": row.get("account_id"),
        "accountHandle": row.get("account_handle"),
        "date": row.get("date"),
        "slotType": row.get("slot_type"),
        "renderedOutputPath": row.get("rendered_output_path"),
        **({"details": details} if details else {}),
    }
