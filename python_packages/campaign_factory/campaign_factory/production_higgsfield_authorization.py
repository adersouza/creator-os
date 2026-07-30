"""Higgsfield quote and spend binding for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import file_lock
from creator_os_core.provider_spend import verify_authorization
from creator_os_core.recreation_anchor_approval import (
    load_recreation_anchor_approval,
)

from .cost_tracker import ensure_cost_table
from .production_prompts import CREATOR_SOUL_IDS
from .provider_spend import (
    consume_provider_spend_authorization,
    ensure_authorization_table,
    issue_provider_spend_authorization,
)


class _BoundHiggsfieldQuote:
    def __init__(self, quote: Mapping[str, Any]) -> None:
        self._quote = dict(quote)

    def quote(self, _scope: dict[str, Any]) -> dict[str, Any]:
        return dict(self._quote)


class _BoundHiggsfieldBalance:
    def __init__(self, balance: float) -> None:
        self._balance = balance

    def balance(self) -> float:
        return self._balance


def higgsfield_request(
    job: Mapping[str, Any],
    *,
    max_credits: float,
    attempt_id: str | None = None,
) -> Any:
    from reel_factory.worker_api import HiggsfieldProductionRequest

    creator = str(job["creator"])
    try:
        soul_id = CREATOR_SOUL_IDS[creator]
    except KeyError as exc:
        raise ValueError(
            f"no pinned authenticated Higgsfield Soul identity for creator {creator}"
        ) from exc
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    authorization = job.get("_higgsfieldAuthorization")
    authorization_id = (
        str(authorization["authorizationId"])
        if isinstance(authorization, Mapping) and authorization.get("authorizationId")
        else None
    )
    provider_quote = (
        authorization.get("providerQuote")
        if isinstance(authorization, Mapping)
        and isinstance(authorization.get("providerQuote"), Mapping)
        else None
    )
    work_item_id = str(job["jobId"])
    if stage["recipeId"] == "higgsfield_recreate_reel":
        anchor = _validated_recreation_anchor(job, creator=creator, soul_id=soul_id)
        source_approval = str(anchor["approvalFingerprint"])
        source_image_path = Path(str(anchor["anchorFilePath"]))
    else:
        anchor = None
        source_approval_evidence = job.get("sourceApproval")
        if not isinstance(source_approval_evidence, Mapping) or not str(
            source_approval_evidence.get("approvalFingerprint") or ""
        ):
            raise PermissionError("exact_source_approval_fingerprint_required")
        source_approval = str(source_approval_evidence["approvalFingerprint"])
        source_image_path = Path(str(job["sourcePath"]))
    return HiggsfieldProductionRequest(
        recipe_id=(
            "higgsfield_recreate_reel"
            if stage["recipeId"] == "higgsfield_recreate_reel"
            else "higgsfield_passive_selfie"
        ),
        creator=creator,
        soul_id=soul_id,
        source_approval=source_approval,
        source_image_path=source_image_path,
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
        work_item_id=work_item_id,
        authorization_id=authorization_id,
        attempt_id=attempt_id,
        client_request_correlation_id=(
            f"creator-os:{work_item_id}:{attempt_id}" if attempt_id else None
        ),
        recreation_anchor_approval=anchor,
        public_mode=(
            "recreate_reel"
            if stage["recipeId"] == "higgsfield_recreate_reel"
            else "calm_animation"
        ),
        campaign=str(job["campaign"]),
        cohort_id=work_item_id,
        prompt_builder_fingerprint=_fingerprint(
            {
                "promptCardFingerprint": (
                    job.get("promptCard", {}).get("promptCardFingerprint")
                    if isinstance(job.get("promptCard"), Mapping)
                    else None
                ),
                "compiledPromptFingerprint": (
                    job.get("compiledPrompt", {}).get("compiledPromptFingerprint")
                    if isinstance(job.get("compiledPrompt"), Mapping)
                    else None
                ),
                "productionRecipeFingerprint": (
                    job.get("productionRecipe", {}).get("recipeFingerprint")
                    if isinstance(job.get("productionRecipe"), Mapping)
                    else None
                ),
                "promptExpansionFingerprint": (
                    job.get("promptExpansion", {}).get("inputFingerprint")
                    if isinstance(job.get("promptExpansion"), Mapping)
                    else None
                ),
            }
        ),
        authorized_request_fingerprint=(
            str(job["providerPlanFingerprint"])
            if job.get("providerPlanFingerprint")
            else None
        ),
        authorized_quote_fingerprint=(
            _fingerprint(dict(provider_quote)) if provider_quote is not None else None
        ),
        balance_delta_attribution_allowed=bool(
            job.get("_providerBalanceDeltaExclusive", True)
        ),
        batch_balance_snapshot_fingerprint=(
            str(job["_higgsfieldBalanceSnapshotFingerprint"])
            if job.get("_higgsfieldBalanceSnapshotFingerprint")
            else None
        ),
    )


def higgsfield_spend_scope(
    job: Mapping[str, Any],
    *,
    provider_plan: Mapping[str, Any],
) -> dict[str, Any]:
    scope = provider_plan.get("authorizationScope")
    if not isinstance(scope, Mapping):
        raise ValueError("higgsfield_provider_plan_authorization_scope_missing")
    if scope.get("requestFingerprint") != provider_plan.get(
        "providerRequestFingerprint"
    ):
        raise ValueError("higgsfield_provider_plan_fingerprint_mismatch")
    if scope.get("workItemId") != job.get("jobId"):
        raise ValueError("higgsfield_provider_plan_work_item_mismatch")
    return dict(scope)


def _validated_recreation_anchor(
    job: Mapping[str, Any],
    *,
    creator: str,
    soul_id: str,
) -> dict[str, Any]:
    approval_path = job.get("recreationAnchorApprovalPath")
    prompt_card = job.get("promptCard")
    prompt_fingerprint = (
        prompt_card.get("openaiPromptPackFingerprint")
        if isinstance(prompt_card, Mapping)
        else None
    )
    if not approval_path or not prompt_fingerprint:
        raise PermissionError("recreation_anchor_approval_required_before_quote")
    anchor = load_recreation_anchor_approval(
        Path(str(approval_path)),
        expected_creator=creator,
        expected_soul_id=soul_id,
        expected_creator_image_sha256=str(job["sourceSha256"]),
        expected_reference_video_sha256=str(job["referenceVideoSha256"]),
        expected_prompt_pack_fingerprint=str(prompt_fingerprint),
    )
    if (
        job.get("recreationAnchorApprovalFingerprint") != anchor["approvalFingerprint"]
        or job.get("recreationAnchorSha256") != anchor["anchorFileSha256"]
        or job.get("recreationAnchorPath") != anchor["anchorFilePath"]
    ):
        raise PermissionError("recreation_anchor_job_binding_mismatch")
    return anchor


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
    capabilities: dict[str, Any] | None = None
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
        recovery = _completed_higgsfield_recovery(candidate)
        if recovery is not None:
            prepared.append(
                {
                    **candidate,
                    "quotedProviderCredits": float(recovery["creditQuote"]["amount"]),
                    "providerPlanFingerprint": recovery["providerRequestFingerprint"],
                    "providerExecutionFingerprint": recovery.get(
                        "executionFingerprint"
                    ),
                    "providerSubmitContract": None,
                    "providerQuoteContract": None,
                    "_higgsfieldCapabilities": None,
                    "_higgsfieldQuote": dict(recovery["creditQuote"]),
                    "_campaignId": str(campaign["id"]),
                    "_higgsfieldRecovery": recovery,
                    "_providerAttemptId": recovery.get("attemptId"),
                }
            )
            continue
        if capabilities is None:
            capabilities = discover_higgsfield_production_capabilities()
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
                "providerPlanFingerprint": provider_plan["providerRequestFingerprint"],
                "providerExecutionFingerprint": provider_plan["executionFingerprint"],
                "providerSubmitContract": provider_plan["command"],
                "providerQuoteContract": provider_plan["quoteCommand"],
                "_higgsfieldCapabilities": capabilities,
                "_higgsfieldQuote": quote,
                "_campaignId": str(campaign["id"]),
                "_higgsfieldRecovery": None,
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
    with file_lock(_provider_account_lock_path(factory)):
        return _authorize_prepared_higgsfield_jobs(factory, prepared)


def _authorize_prepared_higgsfield_jobs(
    factory: Any,
    prepared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    fresh = [job for job in prepared if job.get("_higgsfieldRecovery") is None]
    balance_snapshot = _authorize_batch_balance(factory, fresh)
    authorized: list[dict[str, Any]] = []
    for job in prepared:
        if job.get("_higgsfieldRecovery") is not None:
            recovery = job["_higgsfieldRecovery"]
            scope = _recovered_authorization_scope(
                factory,
                authorization_id=str(recovery["authorizationId"]),
                provider_request_fingerprint=str(
                    recovery["providerRequestFingerprint"]
                ),
            )
            authorized.append(
                {
                    **job,
                    "_higgsfieldSpendScope": scope,
                    "_higgsfieldAuthorization": None,
                    "_providerPipelineJobId": str(recovery["attemptId"]).split(":", 1)[
                        0
                    ],
                }
            )
            continue
        pipeline_job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            str(job["_campaignId"]),
            {
                "workItemId": job["jobId"],
                "sourceAssetId": job["sourceAssetId"],
                "sourceSha256": job["sourceSha256"],
                "provider": "higgsfield",
                "providerModel": list(job["productionRecipe"].get("stages") or [{}])[
                    0
                ].get("providerModel"),
            },
        )
        pipeline_job = factory.domains.events.start_pipeline_job(pipeline_job["id"])
        attempt_id = str(pipeline_job["attempt_id"])
        exact_job = {
            **job,
            "_providerPipelineJobId": str(pipeline_job["id"]),
            "_providerAttemptId": attempt_id,
            "_higgsfieldBalanceSnapshotFingerprint": balance_snapshot["fingerprint"],
        }
        from reel_factory.worker_api import build_higgsfield_production_plan

        provider_plan = build_higgsfield_production_plan(
            higgsfield_request(
                exact_job,
                max_credits=float(job["quotedProviderCredits"]),
                attempt_id=attempt_id,
            ),
            capabilities=dict(job["_higgsfieldCapabilities"]),
        )
        scope = higgsfield_spend_scope(exact_job, provider_plan=provider_plan)
        try:
            authorization = issue_provider_spend_authorization(
                factory.conn,
                scope=scope,
                campaign_id=str(job["_campaignId"]),
                max_credits=float(job["quotedProviderCredits"]),
                secret=secret,
                quote_provider=_BoundHiggsfieldQuote(job["_higgsfieldQuote"]),
                balance_provider=_BoundHiggsfieldBalance(balance_snapshot["credits"]),
            )
        except Exception as exc:
            factory.domains.events.mark_pipeline_effect_state(
                str(pipeline_job["id"]),
                "NO_EFFECT_CONFIRMED",
                evidence={"authorizationFailure": type(exc).__name__},
            )
            raise
        factory.domains.events.mark_pipeline_effect_state(
            str(pipeline_job["id"]),
            "PRE_EFFECT",
            authorization_id=str(authorization["authorizationId"]),
            evidence={
                "providerRequestFingerprint": provider_plan[
                    "providerRequestFingerprint"
                ],
                "executionFingerprint": provider_plan["executionFingerprint"],
                "batchBalanceSnapshot": balance_snapshot,
            },
        )
        authorized.append(
            {
                **exact_job,
                "providerPlanFingerprint": provider_plan["providerRequestFingerprint"],
                "providerExecutionFingerprint": provider_plan["executionFingerprint"],
                "providerSubmitContract": provider_plan["command"],
                "providerQuoteContract": provider_plan["quoteCommand"],
                "_higgsfieldSpendScope": scope,
                "_higgsfieldAuthorization": authorization,
            }
        )
    return authorized


def _provider_account_lock_path(factory: Any) -> Path:
    settings = getattr(factory, "settings", None)
    db_path = getattr(settings, "db_path", None)
    if db_path:
        return (
            Path(str(db_path))
            .expanduser()
            .resolve()
            .with_name(".higgsfield-provider-account")
        )
    return Path.cwd() / ".higgsfield-provider-account"


def _authorize_batch_balance(
    factory: Any,
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    if not jobs:
        return {}
    capabilities = jobs[0].get("_higgsfieldCapabilities")
    authentication = (
        capabilities.get("authentication")
        if isinstance(capabilities, Mapping)
        and isinstance(capabilities.get("authentication"), Mapping)
        else {}
    )
    credits = authentication.get("credits")
    if isinstance(credits, bool) or not isinstance(credits, (int, float)):
        raise PermissionError("higgsfield_batch_balance_unavailable")
    ensure_authorization_table(factory.conn)
    ensure_cost_table(factory.conn)
    active_row = factory.conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM provider_spend_authorizations a
        WHERE a.provider = 'higgsfield'
          AND (
            a.status = 'authorized'
            OR (
              a.status = 'consumed'
              AND NOT EXISTS (
                SELECT 1 FROM ai_cost_events e
                WHERE e.reservation_id = a.reservation_id
              )
            )
          )
        """
    ).fetchone()
    active = float(active_row[0] or 0.0)
    required = round(
        sum(float(job["quotedProviderCredits"]) for job in jobs),
        4,
    )
    minimum = float(os.environ.get("HIGGSFIELD_MIN_BALANCE_CREDITS", "0") or 0)
    if float(credits) - minimum - active + 0.0001 < required:
        raise PermissionError("higgsfield_complete_batch_exceeds_available_balance")
    material = {
        "provider": "higgsfield",
        "observedAt": capabilities.get("observedAt"),
        "credits": float(credits),
        "minimumRetainedCredits": minimum,
        "existingActiveReservations": active,
        "preparedBatchQuote": required,
        "workItemIds": [str(job["jobId"]) for job in jobs],
    }
    return {**material, "fingerprint": _fingerprint(material)}


def _recovered_authorization_scope(
    factory: Any,
    *,
    authorization_id: str,
    provider_request_fingerprint: str,
) -> dict[str, Any]:
    row = factory.conn.execute(
        """
        SELECT scope_json, request_fingerprint
        FROM provider_spend_authorizations
        WHERE authorization_id = ? AND status = 'consumed'
        """,
        (authorization_id,),
    ).fetchone()
    if row is None or str(row["request_fingerprint"]) != provider_request_fingerprint:
        raise PermissionError("higgsfield_recovery_authorization_binding_missing")
    scope = json.loads(str(row["scope_json"]))
    if not isinstance(scope, dict):
        raise PermissionError("higgsfield_recovery_authorization_scope_invalid")
    return scope


def provider_control_reconciliation(factory: Any) -> dict[str, Any]:
    """Report provider-control contradictions without guessing a repair."""

    ensure_authorization_table(factory.conn)
    issues: list[dict[str, Any]] = []
    consumed_without_attempt = factory.conn.execute(
        """
        SELECT a.authorization_id, a.request_fingerprint, a.consumed_at
        FROM provider_spend_authorizations a
        LEFT JOIN pipeline_jobs p ON p.authorization_id = a.authorization_id
        WHERE a.provider = 'higgsfield' AND a.status = 'consumed'
        GROUP BY a.authorization_id
        HAVING COUNT(p.id) = 0
        """
    ).fetchall()
    for row in consumed_without_attempt:
        issues.append(
            _provider_issue(
                record=str(row["authorization_id"]),
                conflict="consumed_authorization_without_provider_attempt",
                manual_action="inspect local Reel receipts before authorizing a new attempt",
                evidence={
                    "requestFingerprint": row["request_fingerprint"],
                    "consumedAt": row["consumed_at"],
                },
            )
        )
    rows = factory.conn.execute(
        """
        SELECT id, status, effect_state, authorization_id, attempt_id,
               external_operation_id, reconciliation_json, result_json
        FROM pipeline_jobs
        WHERE job_type = 'higgsfield_motion_generation'
          AND effect_state <> 'FINALIZED'
        ORDER BY created_at, id
        """
    ).fetchall()
    conflicts = {
        "AUTHORIZATION_CONSUMED": (
            "consumed_authorization_without_submission_receipt",
            "confirm no provider effect, then use a fresh authorization and attempt ID",
        ),
        "SUBMISSION_STARTED": (
            "submission_started_without_generation_id",
            "reconcile provider history; do not resubmit blindly",
        ),
        "AMBIGUOUS": (
            "provider_effect_is_ambiguous",
            "reconcile provider history; do not resubmit blindly",
        ),
        "EXTERNAL_ID_KNOWN": (
            "generation_id_without_completed_output",
            "poll the known generation ID and retain the exact output",
        ),
        "PROVIDER_COMPLETED": (
            "provider_completed_without_retained_output",
            "recover the known result into the staged download path",
        ),
        "OUTPUT_RETAINED": (
            "completed_output_without_cost_binding",
            "reconcile actual or explicit unknown cost before asset registration",
        ),
        "COST_RECONCILED": (
            "cost_bound_without_registered_asset",
            "inspect QC and registration evidence; never regenerate automatically",
        ),
    }
    for row in rows:
        state = str(row["effect_state"])
        if state not in conflicts:
            continue
        conflict, action = conflicts[state]
        issues.append(
            _provider_issue(
                record=str(row["id"]),
                conflict=conflict,
                manual_action=action,
                evidence={
                    "effectState": state,
                    "status": row["status"],
                    "authorizationId": row["authorization_id"],
                    "attemptId": row["attempt_id"],
                    "externalOperationId": row["external_operation_id"],
                },
            )
        )
    return {
        "ok": not issues,
        "schema": "campaign_factory.provider_control_reconciliation.v1",
        "provider": "higgsfield",
        "issueCount": len(issues),
        "issues": issues,
        "automaticProviderCalls": 0,
    }


def _provider_issue(
    *,
    record: str,
    conflict: str,
    manual_action: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "owner": "campaign_factory",
        "record": record,
        "observedConflict": conflict,
        "safeAutomaticAction": "none",
        "manualAction": manual_action,
        "evidence": dict(evidence),
    }


def _completed_higgsfield_recovery(
    job: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return exact completed receipt evidence without authorizing another call."""

    receipt_dir = (
        Path(str(job["providerReviewRoot"])).expanduser().resolve() / "receipts"
    )
    if not receipt_dir.is_dir():
        return None
    expected_output = Path(str(job["providerOutputPath"])).expanduser().resolve()
    expected_source_sha = job.get("recreationAnchorSha256") or job.get("sourceSha256")
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    matches: list[tuple[Path, dict[str, Any]]] = []
    conflicting_completed_receipt = False
    for receipt_path in receipt_dir.glob("*.higgsfield_submission.json"):
        if receipt_path.is_symlink() or not receipt_path.is_file():
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        final = receipt.get("finalOutput") if isinstance(receipt, dict) else None
        source = receipt.get("source") if isinstance(receipt, dict) else None
        driving = receipt.get("drivingVideo") if isinstance(receipt, dict) else None
        if (
            isinstance(receipt, dict)
            and receipt.get("status") == "completed"
            and isinstance(final, dict)
            and (
                receipt.get("workItemId") == job.get("jobId")
                or Path(str(final.get("path") or "")).expanduser().resolve()
                == expected_output
            )
        ):
            conflicting_completed_receipt = True
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") != "completed"
            or receipt.get("workItemId") != job.get("jobId")
            or receipt.get("model") != stage.get("providerModel")
            or receipt.get("seed") != job.get("seed")
            or not receipt.get("generationId")
            or not receipt.get("authorizationId")
            or not receipt.get("attemptId")
            or not isinstance(final, dict)
            or not isinstance(source, dict)
            or source.get("sha256") != expected_source_sha
            or (
                job.get("referenceVideoSha256")
                and (
                    not isinstance(driving, dict)
                    or driving.get("sha256") != job.get("referenceVideoSha256")
                )
            )
            or Path(str(final.get("path") or "")).expanduser().resolve()
            != expected_output
            or not expected_output.is_file()
            or _sha256_file(expected_output) != final.get("sha256")
            or not isinstance(receipt.get("creditQuote"), dict)
            or not receipt.get("providerRequestFingerprint")
        ):
            continue
        matches.append((receipt_path, receipt))
    if len(matches) > 1:
        raise PermissionError("higgsfield_recovery_receipt_is_ambiguous")
    if not matches:
        if conflicting_completed_receipt:
            raise PermissionError("higgsfield_recovery_source_binding_mismatch")
        return None
    receipt_path, receipt = matches[0]
    final = receipt["finalOutput"]
    return {
        "receiptPath": str(receipt_path),
        "receiptSha256": _sha256_file(receipt_path),
        "generationId": str(receipt["generationId"]),
        "outputPath": str(expected_output),
        "outputSha256": str(final["sha256"]),
        "authorizationId": str(receipt["authorizationId"]),
        "attemptId": str(receipt["attemptId"]),
        "providerRequestFingerprint": str(receipt["providerRequestFingerprint"]),
        "executionFingerprint": receipt.get("executionFingerprint"),
        "creditQuote": dict(receipt["creditQuote"]),
    }


def recovered_higgsfield_cost_binding(
    factory: Any,
    *,
    job: Mapping[str, Any],
    receipt: Mapping[str, Any],
    spend_scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a completed receipt to its one consumed authorization and cost row."""

    generation_id = str(receipt.get("generationId") or "")
    credits = receipt.get("creditsConsumed")
    if not generation_id or isinstance(credits, bool):
        raise PermissionError("higgsfield_recovery_cost_evidence_missing")
    if credits is not None and (
        not isinstance(credits, (int, float)) or float(credits) <= 0
    ):
        raise PermissionError("higgsfield_recovery_cost_evidence_missing")
    rows = factory.conn.execute(
        """
        SELECT e.id AS cost_event_id, e.amount AS cost_amount, e.unit AS cost_unit,
               a.authorization_id, a.reservation_id,
               a.request_fingerprint, a.amount AS authorized_amount,
               a.unit AS authorized_unit, a.status AS authorization_status
        FROM ai_cost_events e
        JOIN provider_spend_authorizations a
          ON a.reservation_id = e.reservation_id
        WHERE e.provider = 'higgsfield'
          AND e.operation = 'video_generation'
          AND e.source_event_key =
              'campaign_factory:' || a.authorization_id || ':' || ?
        """,
        (generation_id,),
    ).fetchall()
    if len(rows) != 1:
        raise PermissionError("higgsfield_recovery_cost_binding_is_ambiguous")
    row = dict(rows[0])
    expected_scope_fingerprint = str(spend_scope.get("requestFingerprint") or "")
    if (
        row["authorization_status"] != "consumed"
        or row["request_fingerprint"] != expected_scope_fingerprint
        or row["authorized_unit"] != "higgsfield_credits"
    ):
        raise PermissionError("higgsfield_recovery_cost_binding_mismatch")
    if credits is None:
        if row["cost_amount"] is not None or row["cost_unit"] is not None:
            raise PermissionError("higgsfield_recovery_unknown_cost_binding_mismatch")
    elif (
        row["cost_unit"] != "higgsfield_credits"
        or row["cost_amount"] is None
        or abs(float(row["cost_amount"]) - float(credits)) > 0.0001
        or float(row["authorized_amount"]) + 0.0001 < float(credits)
    ):
        raise PermissionError("higgsfield_recovery_cost_binding_mismatch")
    return {
        "authorizationId": row["authorization_id"],
        "reservationId": row["reservation_id"],
        "costEventIds": [row["cost_event_id"]],
    }


def reconcile_recovered_higgsfield_attempt(
    factory: Any,
    *,
    pipeline_job_id: str,
    job: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_path: Path,
    spend_scope: Mapping[str, Any],
) -> dict[str, Any]:
    pipeline_job = factory.domains.events.pipeline_job(pipeline_job_id)
    external_id = str(
        receipt.get("externalOperationId") or receipt.get("generationId") or ""
    ).strip()
    effect_state = str(pipeline_job.get("effect_state") or "PRE_EFFECT")
    if effect_state == "FINALIZED":
        raise PermissionError("higgsfield_completed_provider_attempt_already_finalized")
    if external_id and effect_state in {
        "PRE_EFFECT",
        "AUTHORIZATION_CONSUMED",
        "SUBMISSION_STARTED",
        "AMBIGUOUS",
    }:
        pipeline_job = factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "EXTERNAL_ID_KNOWN",
            external_operation_id=external_id,
            evidence={"receiptPath": str(receipt_path)},
        )
        effect_state = str(pipeline_job["effect_state"])
    if effect_state == "EXTERNAL_ID_KNOWN":
        pipeline_job = factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "PROVIDER_COMPLETED",
            external_operation_id=external_id,
            evidence={"receiptPath": str(receipt_path)},
        )
        effect_state = str(pipeline_job["effect_state"])
    if effect_state == "PROVIDER_COMPLETED":
        factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "OUTPUT_RETAINED",
            external_operation_id=external_id,
            evidence={
                "receiptPath": str(receipt_path),
                "outputSha256": dict(receipt.get("finalOutput") or {}).get("sha256"),
            },
        )
    binding = recovered_higgsfield_cost_binding(
        factory,
        job=job,
        receipt=receipt,
        spend_scope=spend_scope,
    )
    factory.domains.events.mark_pipeline_effect_state(
        pipeline_job_id,
        "COST_RECONCILED",
        external_operation_id=external_id,
        evidence={
            "costEventIds": binding["costEventIds"],
            "actualCredits": receipt.get("creditsConsumed"),
            "actualCreditsStatus": (
                "known" if receipt.get("creditsConsumed") is not None else "unknown"
            ),
        },
    )
    return binding


def prepare_authorized_higgsfield_execution(
    factory: Any,
    *,
    pipeline_job_id: str,
    job: Mapping[str, Any],
    request: Any,
    authorization: Mapping[str, Any],
    spend_scope: Mapping[str, Any],
    capabilities: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    from reel_factory.worker_api import (
        build_higgsfield_production_plan,
        higgsfield_quote_fingerprint,
        quote_higgsfield_production_plan,
    )

    plan = build_higgsfield_production_plan(request, capabilities=capabilities)
    if (
        plan["providerRequestFingerprint"] != job["providerPlanFingerprint"]
        or plan["authorizationScope"] != spend_scope
    ):
        raise PermissionError("higgsfield_authorized_provider_plan_mismatch")
    live_quote = quote_higgsfield_production_plan(plan)
    if higgsfield_quote_fingerprint(live_quote) != higgsfield_quote_fingerprint(
        dict(authorization["providerQuote"])
    ):
        raise PermissionError("higgsfield_quote_changed_after_authorization")
    authorization_id = str(authorization["authorizationId"])
    verify_authorization(
        authorization,
        expected_scope=plan["authorizationScope"],
        secret=os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", ""),
        now=datetime.now(UTC),
    )
    consume_provider_spend_authorization(factory.conn, authorization_id)
    factory.domains.events.mark_pipeline_effect_state(
        pipeline_job_id,
        "AUTHORIZATION_CONSUMED",
        authorization_id=authorization_id,
        evidence={
            "providerRequestFingerprint": plan["providerRequestFingerprint"],
            "executionFingerprint": plan["executionFingerprint"],
        },
    )

    def record_effect(state: str, evidence: dict[str, Any]) -> None:
        factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            state,
            authorization_id=authorization_id,
            external_operation_id=(
                str(evidence["externalOperationId"])
                if evidence.get("externalOperationId")
                else None
            ),
            evidence=evidence,
        )

    return plan, live_quote, record_effect


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
