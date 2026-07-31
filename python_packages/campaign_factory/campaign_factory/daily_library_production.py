from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from creator_os_core.fileops import atomic_write_text

from .adapters.contentforge import audit_campaign
from .learning_cohort import COHORT_ID, ensure_learning_cohort_tables
from .persistence import json_load

if TYPE_CHECKING:
    from .core import CampaignFactory


IDENTITY_CACHE_VERSION = "arcface_v1_threshold_0.42"


def run_daily_library_production(
    factory: CampaignFactory,
    *,
    day_index: int,
    cohort_id: str = COHORT_ID,
    campaign_slug: str = COHORT_ID,
    workers: int = 2,
    contentforge_base_url: str | None = None,
    library_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Build one bounded regular/trial pair from the cataloged local library.

    This stage is deliberately local and zero-cost. It may select, render, sync,
    audit, and mark assets review-ready. It never approves, exports, schedules,
    publishes, or calls a paid generation provider.
    """
    if day_index < 1:
        raise ValueError("day_index must be positive")
    ensure_learning_cohort_tables(factory.conn)
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    library_root = (library_root or Path.home() / "Documents/content/stacey").resolve()
    if not library_root.is_dir():
        raise ValueError(f"library_root is not a directory: {library_root}")
    assignments = _assignments_for_day(
        factory.conn, cohort_id=cohort_id, day_index=day_index
    )
    if not assignments:
        raise ValueError(f"no cohort assignments found for day {day_index}")

    blockers = _assignment_blockers(assignments)
    selections = _select_sources(
        factory,
        campaign_id=campaign["id"],
        cohort_id=cohort_id,
        assignments=assignments,
        library_root=library_root,
    )
    report: dict[str, Any] = {
        "schema": "campaign_factory.daily_library_production.v1",
        "generatedAt": _utc_now(),
        "mode": "apply" if apply else "plan",
        "campaign": campaign_slug,
        "cohortId": cohort_id,
        "dayIndex": day_index,
        "libraryRoot": str(library_root),
        "status": "blocked" if blockers else ("planned" if not apply else "running"),
        "blockingReasons": blockers,
        "selections": selections,
        "prepare": None,
        "render": None,
        "sync": None,
        "audit": None,
        "reviewReady": [],
        "needsReview": [],
        "controls": {
            "providerCalls": 0,
            "creditsSpent": 0,
            "paidGenerationAllowed": False,
            "approvalActionsTaken": 0,
            "draftActionsTaken": 0,
            "scheduleActionsTaken": 0,
            "publishActionsTaken": 0,
            "humanApprovalRequired": True,
        },
    }
    if blockers or not apply:
        return report

    now = _utc_now()
    for selection in selections:
        factory.conn.execute(
            """UPDATE learning_cohort_assignments
            SET source_asset_id = ?, generation_state = 'selected', updated_at = ?
            WHERE id = ?""",
            (selection["sourceAssetId"], now, selection["assignmentId"]),
        )
    factory.conn.commit()

    source_ids = [selection["sourceAssetId"] for selection in selections]
    hooks = _daily_hooks(
        factory,
        count=len(source_ids),
        seed_key=f"{cohort_id}:{day_index}",
        selections=selections,
    )
    prepared = factory.domains.reel_execution.prepare_reel_inputs(
        campaign_slug=campaign_slug,
        hooks=hooks,
        recipes=["v01_original"],
        caption_color="auto",
        notes=f"daily library production day {day_index}",
        force_new=False,
        source_asset_ids=source_ids,
    )
    target_jobs = [
        *prepared.get("prepared", []),
        *prepared.get("reusedExisting", []),
    ]
    target_jobs = _latest_job_per_source(target_jobs, source_ids=source_ids)
    missing_jobs = [
        source_id
        for source_id in source_ids
        if not any(job["source_asset_id"] == source_id for job in target_jobs)
    ]
    if missing_jobs:
        raise RuntimeError(
            "render jobs missing for selected sources: " + ", ".join(missing_jobs)
        )
    report["prepare"] = {
        "preparedCount": len(prepared.get("prepared") or []),
        "reusedExistingCount": len(prepared.get("reusedExisting") or []),
        "renderJobIds": [job["id"] for job in target_jobs],
        "sourceOwnershipAttestations": _write_source_ownership_attestations(
            factory,
            target_jobs=target_jobs,
            selections=selections,
            library_root=library_root,
        ),
    }

    runnable_job_ids = [
        job["id"] for job in target_jobs if job["status"] in {"prepared", "failed"}
    ]
    if runnable_job_ids:
        render = factory.domains.reel_execution.run_reel_factory(
            campaign_slug=campaign_slug,
            workers=workers,
            caption_band="",
            caption_color="light",
            caption_style="ig",
            caption_font="Instagram Sans Condensed",
            caption_placement_qc=True,
            phone_finalize=True,
            max_outputs_per_clip=1,
            render_job_ids=runnable_job_ids,
            creator_style_preset="stacey_static_center",
        )
        if render.get("returncode") != 0:
            report["status"] = "render_failed"
            report["render"] = _render_summary(render)
            return report
        report["render"] = _render_summary(render)
    else:
        report["render"] = {"runCount": 0, "returncode": 0, "reused": True}

    target_job_ids = [job["id"] for job in target_jobs]
    synced = factory.domains.reel_execution.sync_reel_outputs(
        campaign_slug=campaign_slug, render_job_ids=target_job_ids
    )
    rendered = _rendered_assets_for_jobs(
        factory.conn,
        campaign_id=campaign["id"],
        render_job_ids=target_job_ids,
    )
    rendered_ids = [asset["id"] for asset in rendered]
    report["sync"] = {
        "syncedCount": len(synced.get("synced") or []),
        "renderedAssetIds": rendered_ids,
    }
    if len(rendered_ids) != len(target_job_ids):
        report["status"] = "sync_incomplete"
        report["blockingReasons"] = [
            f"expected {len(target_job_ids)} rendered assets, found {len(rendered_ids)}"
        ]
        return report

    audited = audit_campaign(
        factory,
        campaign_slug=campaign_slug,
        min_score=85,
        contentforge_base_url=contentforge_base_url,
        rendered_asset_ids=rendered_ids,
    )
    audit_reports = audited.get("reports") or []
    report["audit"] = {
        "reportCount": len(audit_reports),
        "reports": [
            {
                "renderedAssetId": item.get("renderedAssetId"),
                "status": item.get("status"),
                "overallVerdict": item.get("overallVerdict"),
                "failedChecks": item.get("failedChecks") or [],
                "warnings": item.get("warnings") or [],
                "uploadReady": (item.get("readinessSummary") or {}).get("uploadReady"),
            }
            for item in audit_reports
        ],
    }
    audit_by_asset = {str(item.get("renderedAssetId")): item for item in audit_reports}
    assignments_by_source = {
        selection["sourceAssetId"]: selection for selection in selections
    }
    for asset in rendered:
        audit = audit_by_asset.get(str(asset["id"])) or {}
        selection = assignments_by_source[str(asset["source_asset_id"])]
        safe = _audit_is_review_ready(audit)
        state = "review_ready" if safe else "needs_review"
        metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        identity = selection["identityVerification"]
        visual_qc = _contentforge_visual_qc_evidence(audit)
        metadata.update(
            {
                "identityVerificationStatus": identity["status"],
                "identityVerification": identity,
                "visualQcStatus": visual_qc["status"],
                "visualQc": visual_qc,
            }
        )
        factory.conn.execute(
            """UPDATE rendered_assets
            SET review_state = ?, metadata_json = ?, updated_at = ? WHERE id = ?""",
            (
                "review_ready" if safe else "draft",
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                _utc_now(),
                asset["id"],
            ),
        )
        factory.conn.execute(
            """UPDATE learning_cohort_assignments
            SET rendered_asset_id = ?, artifact_path = ?, generation_state = ?,
                approval_state = 'pending', schedule_state = 'blocked_pending_approval',
                updated_at = ?
            WHERE id = ?""",
            (
                asset["id"],
                asset["campaign_path"],
                state,
                _utc_now(),
                selection["assignmentId"],
            ),
        )
        item = {
            "assignmentId": selection["assignmentId"],
            "surface": selection["surface"],
            "sourceAssetId": asset["source_asset_id"],
            "renderedAssetId": asset["id"],
            "artifactPath": asset["campaign_path"],
            "reviewState": "review_ready" if safe else "draft",
            "learningEligible": _source_has_learning_lineage(
                factory.conn, str(asset["source_asset_id"])
            ),
        }
        report["reviewReady" if safe else "needsReview"].append(item)
    factory.conn.commit()

    report["status"] = (
        "review_ready"
        if len(report["reviewReady"]) == len(selections)
        else "needs_review"
    )
    report["controls"]["learningEligibilityNote"] = (
        "Catalog media remains learning-ineligible unless prompt and reference lineage "
        "are both traceable; publishing metrics may still be collected."
    )
    return report


def _assignments_for_day(
    conn: sqlite3.Connection, *, cohort_id: str, day_index: int
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM learning_cohort_assignments
            WHERE cohort_id = ? AND day_index = ?
            ORDER BY scheduled_for, surface""",
            (cohort_id, day_index),
        ).fetchall()
    ]


def _assignment_blockers(assignments: list[dict[str, Any]]) -> list[str]:
    blockers = []
    for assignment in assignments:
        if assignment.get("draft_id") or assignment.get("post_id"):
            blockers.append(f"assignment_already_handed_off:{assignment['id']}")
        elif assignment.get("publish_state") not in {None, "not_published"}:
            blockers.append(
                f"assignment_publish_state:{assignment['id']}:{assignment['publish_state']}"
            )
    return blockers


def _select_sources(
    factory: CampaignFactory,
    *,
    campaign_id: str,
    cohort_id: str,
    assignments: list[dict[str, Any]],
    library_root: Path,
) -> list[dict[str, Any]]:
    conn = factory.conn
    candidates = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM source_assets
            WHERE campaign_id = ? AND media_type = 'video' AND status != 'rejected'
            ORDER BY id""",
            (campaign_id,),
        ).fetchall()
        if _is_cataloged_library_path(Path(str(row["stored_path"])), library_root)
    ]
    if not candidates:
        raise ValueError("no existing cataloged video sources available")
    candidate_by_id = {str(item["id"]): item for item in candidates}
    usage = Counter(
        str(row["source_asset_id"])
        for row in conn.execute(
            """SELECT source_asset_id FROM learning_cohort_assignments
            WHERE cohort_id = ? AND source_asset_id IS NOT NULL""",
            (cohort_id,),
        ).fetchall()
    )
    identity_by_source: dict[str, dict[str, Any]] = {}

    def identity_for(source: dict[str, Any]) -> dict[str, Any]:
        source_id = str(source["id"])
        if source_id not in identity_by_source:
            identity_by_source[source_id] = _verify_library_identity(factory, source)
        return identity_by_source[source_id]

    selections = []
    selected_source_ids: set[str] = set()
    for assignment in assignments:
        assigned_id = str(assignment.get("source_asset_id") or "")
        if assigned_id:
            if assigned_id not in candidate_by_id:
                raise ValueError(
                    f"assigned source asset is unavailable: {assignment['id']}:{assigned_id}"
                )
            if assigned_id in selected_source_ids:
                raise ValueError(
                    f"daily pair reuses assigned source: {assignment['id']}:{assigned_id}"
                )
            source = candidate_by_id[assigned_id]
        else:
            ranked = sorted(
                [
                    item
                    for item in candidates
                    if str(item["id"]) not in selected_source_ids
                ],
                key=lambda item: (
                    usage[str(item["id"])],
                    hashlib.sha256(
                        f"{assignment['assignment_seed']}:{item['id']}".encode()
                    ).hexdigest(),
                ),
            )
            source = next(
                (
                    item
                    for item in ranked
                    if identity_for(item).get("status") == "passed"
                ),
                None,
            )
            if source is None:
                raise ValueError(
                    "no distinct identity-verified Stacey library source available "
                    f"for {assignment['id']}"
                )
            usage[str(source["id"])] += 1
        identity = identity_for(source)
        if identity.get("status") != "passed":
            raise ValueError(
                f"assigned source identity is not verified: {assignment['id']}:{source['id']}:{identity.get('status')}"
            )
        selected_source_ids.add(str(source["id"]))
        selections.append(
            {
                "assignmentId": assignment["id"],
                "surface": assignment["surface"],
                "scheduledFor": assignment["scheduled_for"],
                "sourceAssetId": source["id"],
                "sourcePath": source["stored_path"],
                "contentHash": source["content_hash"],
                "selectionKey": hashlib.sha256(
                    f"{assignment['assignment_seed']}:{source['id']}".encode()
                ).hexdigest(),
                "identityVerification": identity,
            }
        )
    return selections


def _verify_library_identity(
    factory: CampaignFactory, source: dict[str, Any]
) -> dict[str, Any]:
    content_hash = str(source.get("content_hash") or "").strip()
    cache_dir = factory.settings.root / ".cache" / "library_identity"
    reference_fingerprint = _identity_reference_fingerprint(factory)
    cache_key = hashlib.sha256(
        f"{IDENTITY_CACHE_VERSION}:{content_hash}:{reference_fingerprint}".encode()
    ).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    if content_hash and cache_path.exists():
        cached = json_load(cache_path.read_text(encoding="utf-8"), {})
        if isinstance(cached, dict) and cached.get("status") in {"passed", "failed"}:
            return cached
    command = [
        sys.executable,
        "-m",
        "reel_factory.identity_verification",
        "verify",
        str(source["stored_path"]),
        "--creator",
        "Stacey",
        "--root",
        str(factory.settings.reel_factory_root),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    record: dict[str, Any] = {
        "schema": "reel_factory.identity_verification.v1",
        "creator": "Stacey",
        "status": "unavailable",
        "failureReason": "identity_verifier_failed",
    }
    for offset, character in enumerate(completed.stdout):
        if character != "{":
            continue
        try:
            candidate, _ = json.JSONDecoder().raw_decode(completed.stdout[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("schema"):
            record = candidate
    if completed.returncode != 0 and record.get("status") == "passed":
        record = {
            **record,
            "status": "unavailable",
            "failureReason": "identity_verifier_failed",
        }
    if content_hash and record.get("status") in {"passed", "failed"}:
        cache_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache_path, json.dumps(record, indent=2, sort_keys=True))
    return record


def _identity_reference_fingerprint(factory: CampaignFactory) -> str:
    configured = os.environ.get("REEL_FACTORY_IDENTITY_REFERENCE_SET")
    reference_path = (
        Path(configured).expanduser()
        if configured
        else factory.settings.reel_factory_root / "identity_references" / "stacey.json"
    )
    if not reference_path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with reference_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _daily_hooks(
    factory: CampaignFactory,
    *,
    count: int,
    seed_key: str,
    selections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from reel_factory.worker_api import (
        caption_hook_payload,
        load_or_build_caption_bank_store,
    )

    store = load_or_build_caption_bank_store(factory.settings.reel_factory_root)
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:16], 16)
    candidates = store.resolve_mix(
        "Stacey",
        limit=200,
        seed=seed,
        variant_types={"static", "timed"},
    )
    used_keys = _recent_used_caption_keys(factory.conn)
    timed = [
        item
        for item in candidates
        if item.get("variant_type") == "timed"
        and item.get("approval_id")
        and item.get("approval_file_sha")
        and item.get("approval_reviewer")
        and item.get("approval_decided_at")
        if factory.domains.reference.reference_hook_is_schedule_safe(
            str(item.get("text") or "")
        )
        and 2 <= len(item.get("segments") or []) <= 4
        and all(
            isinstance(segment, dict) and bool(str(segment.get("text") or "").strip())
            for segment in item.get("segments") or []
        )
        and not {
            str(item.get("static_text_hash") or ""),
            str(item.get("caption_payload_hash") or ""),
        }.intersection(used_keys)
    ]
    static = [
        item
        for item in candidates
        if item.get("variant_type") == "static"
        and factory.domains.reference.reference_hook_is_schedule_safe(
            str(item.get("text") or "")
        )
        and int(item.get("line_count") or 1) <= 2
        and int(item.get("word_count") or 0) <= 5
        and int(item.get("char_count") or len(str(item.get("text") or ""))) <= 24
        and not {
            str(item.get("static_text_hash") or ""),
            str(item.get("caption_payload_hash") or ""),
        }.intersection(used_keys)
    ]
    if selections is not None and len(selections) != count:
        raise ValueError("caption source selections must match requested hook count")
    contexts = [
        _caption_source_context(factory.conn, selection)
        for selection in (selections or [{} for _ in range(count)])
    ]
    selected: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, Any], str | None]
    ] = []
    selected_keys: set[str] = set()
    for index, context in enumerate(contexts):
        available_timed = _unused_caption_items(timed, selected_keys)
        available_static = _unused_caption_items(static, selected_keys)
        item, fitted_lineage = _fit_daily_caption(
            store=store,
            items=available_timed,
            context=context,
            seed=seed
            ^ int(
                hashlib.sha256(f"{seed_key}:{index}:timed".encode()).hexdigest()[:16],
                16,
            ),
        )
        fallback_reason: str | None = None
        if item is None:
            fallback_reason = (
                "no_source_compatible_approved_timed_hook"
                if available_timed
                else "no_remaining_eligible_approved_timed_hook"
            )
            item, fitted_lineage = _fit_daily_caption(
                store=store,
                items=available_static,
                context=context,
                seed=seed
                ^ int(
                    hashlib.sha256(f"{seed_key}:{index}:static".encode()).hexdigest()[
                        :16
                    ],
                    16,
                ),
            )
        if item is None:
            continue
        keys = _caption_item_keys(item)
        selected_keys.update(keys)
        selected.append((item, fitted_lineage, context, fallback_reason))
    if len(selected) < count:
        raise RuntimeError(
            "Stacey caption bank has only "
            f"{len(selected)} unused source-compatible timed/static hooks; need {count}"
        )
    hooks = []
    for item, fitted_lineage, context, fallback_reason in selected:
        selected_banks = list(item.get("selected_banks") or [])
        render_hook = caption_hook_payload(item)
        lineage = dict(fitted_lineage)
        lineage.update(
            {
                "timedPreferred": True,
                "timedEligible": item.get("variant_type") == "timed",
                "selectedVariantType": item.get("variant_type"),
                "eligibilityDecision": (
                    "approved_timed_passive_library"
                    if item.get("variant_type") == "timed"
                    else "static_fallback"
                ),
                "fallbackReason": (
                    None if item.get("variant_type") == "timed" else fallback_reason
                ),
                "recentReuseDecision": "clear",
                "recentReuseWindowDays": 14,
                "captionSelectionContext": {
                    "sourceAssetId": context["sourceAssetId"],
                    "contextFingerprint": context["contextFingerprint"],
                    "frameType": context["frameType"],
                    "reelSceneTags": context["reelSceneTags"],
                    "captionTopic": context["captionTopic"],
                    "selectionMode": "existing_scene_and_topic_fit",
                },
            }
        )
        hooks.append(
            {
                **(render_hook if isinstance(render_hook, dict) else {}),
                "text": item["text"],
                "captionHash": item["caption_hash"],
                "staticTextHash": item["static_text_hash"],
                "captionPayloadHash": item["caption_payload_hash"],
                "variantType": item["variant_type"],
                "captionBank": selected_banks[0] if selected_banks else None,
                "captionBanks": item.get("banks") or [],
                "creatorMix": "Stacey",
                "source": "reel_factory_caption_bank",
                "captionLineage": lineage,
            }
        )
    return hooks


def _caption_item_keys(item: dict[str, Any]) -> set[str]:
    return {
        value
        for value in (
            str(item.get("static_text_hash") or ""),
            str(item.get("caption_payload_hash") or ""),
        )
        if value
    }


def _unused_caption_items(
    items: list[dict[str, Any]], selected_keys: set[str]
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if not _caption_item_keys(item).intersection(selected_keys)
    ]


def _caption_source_context(
    conn: sqlite3.Connection, selection: dict[str, Any]
) -> dict[str, Any]:
    source_asset_id = str(selection.get("sourceAssetId") or "") or None
    row = (
        conn.execute(
            "SELECT filename, stored_path, source_prompt, notes FROM source_assets WHERE id = ?",
            (source_asset_id,),
        ).fetchone()
        if source_asset_id
        else None
    )
    filename = str((row and row["filename"]) or selection.get("sourcePath") or "")
    prompt_text = " ".join(
        value
        for value in (
            str((row and row["source_prompt"]) or "").strip(),
            str((row and row["notes"]) or "").strip(),
        )
        if value
    )
    searchable = f"{Path(filename).stem} {prompt_text}".lower()
    if any(token in searchable for token in ("gym", "workout", "fitness")):
        frame_type = "gym_body"
    elif any(token in searchable for token in ("mirror", "full body", "fullbody")):
        frame_type = "mirror_fullbody"
    elif any(token in searchable for token in ("closeup", "close-up", "selfie")):
        frame_type = "closeup"
    else:
        frame_type = "unknown"
    context_payload = {
        "sourceAssetId": source_asset_id,
        "frameType": frame_type,
        "videoStem": Path(filename).stem,
        "promptText": prompt_text,
    }
    return {
        **context_payload,
        "contextFingerprint": hashlib.sha256(
            json.dumps(context_payload, sort_keys=True).encode()
        ).hexdigest(),
    }


def _fit_daily_caption(
    *,
    store: Any,
    items: list[dict[str, Any]],
    context: dict[str, Any],
    seed: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    from reel_factory.caption_scene_fit import (
        classify_reel_scene_tags,
        infer_caption_topic_for_reel,
    )
    from reel_factory.reel_pipeline_selection import apply_caption_fit_to_caption_set
    from reel_factory.reel_pipeline_support import CaptionSet
    from reel_factory.worker_api import caption_hook_payload

    if not items:
        return None, {}
    hooks = [caption_hook_payload(item) for item in items]
    lineage = {
        index: store.lineage_for(
            item,
            selected_mix="Stacey",
            selected_banks=list(item.get("selected_banks") or []),
        )
        for index, item in enumerate(items)
    }
    reel_scene_tags = classify_reel_scene_tags(
        frame_type=context["frameType"],
        video_stem=context["videoStem"],
        prompt_text=context["promptText"],
    )
    caption_topic = infer_caption_topic_for_reel(
        frame_type=context["frameType"],
        video_stem=context["videoStem"],
        prompt_text=context["promptText"],
    )
    context["reelSceneTags"] = reel_scene_tags
    context["captionTopic"] = caption_topic
    fitted, _diagnostics = apply_caption_fit_to_caption_set(
        CaptionSet(hooks=hooks, hook_lineage=lineage),
        frame_type=context["frameType"],
        reel_scene_tags=reel_scene_tags,
        caption_topic=caption_topic,
        max_hooks=1,
        seed=seed,
        fit_mode="auto",
        scene_fit_mode="auto",
    )
    if not fitted.hooks:
        return None, {}
    fitted_hook = fitted.hooks[0]
    fitted_lineage = dict(fitted.hook_lineage.get(0) or {})
    payload_hash = str(fitted_lineage.get("captionPayloadHash") or "")
    item = next(
        (
            candidate
            for candidate in items
            if (
                payload_hash
                and str(candidate.get("caption_payload_hash") or "") == payload_hash
            )
            or caption_hook_payload(candidate) == fitted_hook
        ),
        None,
    )
    return item, fitted_lineage


def _recent_used_caption_keys(
    conn: sqlite3.Connection, *, reuse_window_days: int = 14
) -> set[str]:
    cutoff = (datetime.now(UTC) - timedelta(days=max(0, reuse_window_days))).isoformat()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT r.caption_hash, r.caption_generation_json, r.metadata_json
            FROM rendered_assets r
            WHERE r.id IN (
              SELECT rendered_asset_id FROM asset_account_assignments
              WHERE created_at >= ?
              UNION
              SELECT rendered_asset_id FROM distribution_plans
              WHERE COALESCE(planned_window_start, created_at) >= ?
              UNION
              SELECT asset_id FROM asset_inventory_reservations
              WHERE status IN ('pending', 'committed') AND reserved_at >= ?
            )
            """,
            (cutoff, cutoff, cutoff),
        ).fetchall()
    except sqlite3.Error:
        return set()
    keys: set[str] = set()
    for row in rows:
        if row["caption_hash"]:
            keys.add(str(row["caption_hash"]))
        for column in ("caption_generation_json", "metadata_json"):
            payload = json_load(row[column], {})
            _collect_caption_hashes(payload, keys)
    return keys


def _collect_caption_hashes(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                key
                in {
                    "captionHash",
                    "caption_hash",
                    "staticTextHash",
                    "static_text_hash",
                    "captionPayloadHash",
                    "caption_payload_hash",
                }
                and child
            ):
                keys.add(str(child))
            else:
                _collect_caption_hashes(child, keys)
    elif isinstance(value, list):
        for child in value:
            _collect_caption_hashes(child, keys)


def _is_cataloged_library_path(path: Path, library_root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    return resolved.is_file() and resolved.is_relative_to(library_root)


def _latest_job_per_source(
    jobs: list[dict[str, Any]], *, source_ids: list[str]
) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for job in jobs:
        source_id = str(job["source_asset_id"])
        current = latest.get(source_id)
        if current is None or str(job.get("created_at") or "") > str(
            current.get("created_at") or ""
        ):
            latest[source_id] = job
    return [latest[source_id] for source_id in source_ids if source_id in latest]


def _write_source_ownership_attestations(
    factory: CampaignFactory,
    *,
    target_jobs: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    library_root: Path,
) -> list[str]:
    selection_by_source = {
        str(selection["sourceAssetId"]): selection for selection in selections
    }
    paths = []
    for job in target_jobs:
        selection = selection_by_source[str(job["source_asset_id"])]
        path = (
            factory.settings.reel_factory_root
            / "00_source_videos"
            / f"{job['reel_clip_stem']}.owned_source.json"
        )
        atomic_write_text(
            path,
            json.dumps(
                {
                    "schema": "reel_factory.operator_owned_source.v1",
                    "sourceAssetId": selection["sourceAssetId"],
                    "sourceContentHash": selection["contentHash"],
                    "originalPath": selection["sourcePath"],
                    "libraryRoot": str(library_root),
                    "ownershipBasis": "operator_owned_catalog_root",
                    "learningLineageEligible": False,
                    "createdAt": _utc_now(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        paths.append(str(path))
    return paths


def _rendered_assets_for_jobs(
    conn: sqlite3.Connection, *, campaign_id: str, render_job_ids: list[str]
) -> list[dict[str, Any]]:
    assets = []
    for render_job_id in render_job_ids:
        row = conn.execute(
            """SELECT * FROM rendered_assets
            WHERE campaign_id = ? AND render_job_id = ?
            ORDER BY created_at DESC LIMIT 1""",
            (campaign_id, render_job_id),
        ).fetchone()
        if row:
            assets.append(dict(row))
    return assets


def _audit_is_review_ready(report: dict[str, Any]) -> bool:
    readiness = report.get("readinessSummary") or {}
    return bool(
        report
        and report.get("error") is None
        and report.get("status") in {"approved_candidate", "needs_review"}
        and report.get("overallVerdict") in {"pass", "warn"}
        and not (report.get("failedChecks") or [])
        and readiness.get("uploadReady") is True
        and not (readiness.get("blockingReasons") or [])
        and not (readiness.get("blockingCodes") or [])
    )


def _contentforge_visual_qc_evidence(report: dict[str, Any]) -> dict[str, Any]:
    readiness = report.get("readinessSummary") or {}
    return {
        "status": "passed" if _audit_is_review_ready(report) else "failed",
        "source": "contentforge",
        "auditStatus": report.get("status"),
        "overallVerdict": report.get("overallVerdict"),
        "uploadReady": readiness.get("uploadReady") is True,
        "failedChecks": report.get("failedChecks") or [],
        "warnings": report.get("warnings") or [],
    }


def _source_has_learning_lineage(
    conn: sqlite3.Connection, source_asset_id: str
) -> bool:
    row = conn.execute(
        "SELECT source_prompt FROM source_assets WHERE id = ?", (source_asset_id,)
    ).fetchone()
    payload = (
        json_load(row["source_prompt"], {}) if row and row["source_prompt"] else {}
    )
    lineage = payload.get("generatedAssetLineage") or payload.get(
        "generated_asset_lineage"
    )
    source = lineage.get("source") if isinstance(lineage, dict) else {}
    return bool(
        isinstance(source, dict)
        and source.get("promptId")
        and source.get("referenceId")
    )


def _render_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": result.get("returncode"),
        "runCount": len(result.get("runs") or []),
        "renderJobIds": [item.get("renderJobId") for item in result.get("runs") or []],
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
