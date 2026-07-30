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
from .provider_spend import (
    HiggsfieldCliBalanceProvider,
    cancel_provider_spend_authorization,
    consume_provider_spend_authorization,
    ensure_authorization_table,
    issue_provider_spend_authorization,
    load_provider_spend_authorization,
    record_provider_execution,
    validate_provider_spend_batch_capacity,
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
    authorization = job.get("_higgsfieldAuthorization")
    governance_context = (
        authorization.get("governanceContext")
        if isinstance(authorization, Mapping)
        and isinstance(authorization.get("governanceContext"), Mapping)
        else (
            job.get("_creatorGovernance")
            if isinstance(job.get("_creatorGovernance"), Mapping)
            else None
        )
    )
    if governance_context is None:
        raise PermissionError("creator_governance_required_before_provider_request")
    if governance_context.get("creatorSlug") != creator:
        raise PermissionError("provider_authorization_creator_mismatch")
    soul_id = str(governance_context["providerIdentityId"])
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    recovery = job.get("_higgsfieldRecovery")
    authorization_id = (
        str(authorization["authorizationId"])
        if isinstance(authorization, Mapping) and authorization.get("authorizationId")
        else (
            str(recovery["authorizationId"])
            if isinstance(recovery, Mapping) and recovery.get("authorizationId")
            else None
        )
    )
    provider_quote = (
        authorization.get("providerQuote")
        if isinstance(authorization, Mapping)
        and isinstance(authorization.get("providerQuote"), Mapping)
        else (
            recovery.get("creditQuote")
            if isinstance(recovery, Mapping)
            and isinstance(recovery.get("creditQuote"), Mapping)
            else None
        )
    )
    work_item_id = str(job["jobId"])
    if stage["recipeId"] == "higgsfield_recreate_reel":
        anchor = _validated_recreation_anchor(job, creator=creator, soul_id=soul_id)
        source_approval = str(anchor["approvalFingerprint"])
        source_approval_id = (
            f"recreation_anchor_approval:{anchor['approvalFingerprint']}"
        )
        source_asset_id = f"sha256:{anchor['anchorFileSha256']}"
        source_image_path = Path(str(anchor["anchorFilePath"]))
    else:
        anchor = None
        source_approval_evidence = job.get("sourceApproval")
        if (
            not isinstance(source_approval_evidence, Mapping)
            or not str(source_approval_evidence.get("approvalEventId") or "")
            or not str(source_approval_evidence.get("approvalFingerprint") or "")
        ):
            raise PermissionError("exact_source_approval_fingerprint_required")
        source_approval = str(source_approval_evidence["approvalFingerprint"])
        source_approval_id = str(source_approval_evidence["approvalEventId"])
        source_asset_id = str(job["sourceAssetId"])
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
        source_asset_id=source_asset_id,
        campaign_source_asset_id=str(job["sourceAssetId"]),
        source_approval_id=source_approval_id,
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
        prompt_card_fingerprint=(
            str(job["promptCard"]["promptCardFingerprint"])
            if isinstance(job.get("promptCard"), Mapping)
            and job["promptCard"].get("promptCardFingerprint")
            else None
        ),
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
            job.get("_providerBalanceDeltaExclusive", False)
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
    provider_quote: Mapping[str, Any],
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
    batch_snapshot_fingerprint = job.get(
        "_higgsfieldBalanceSnapshotFingerprint"
    ) or scope.get("batchBalanceSnapshotFingerprint")
    if not batch_snapshot_fingerprint:
        raise ValueError("higgsfield_batch_balance_snapshot_fingerprint_missing")
    return {
        **dict(scope),
        "batchBalanceSnapshotFingerprint": str(batch_snapshot_fingerprint),
        "quoteFingerprint": _fingerprint(dict(provider_quote)),
    }


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
    persist_attempts: bool = False,
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
        governance_context = factory.domains.creator_governance.resolve_operation(
            creator=str(job["creator"]),
            campaign=str(campaign["id"]),
            operation="provider_spend",
            provider="higgsfield",
            source_asset_id=str(job["sourceAssetId"]),
        )
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
            "_creatorGovernance": governance_context,
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
        pipeline_job = None
        attempt_id = f"quote:{job['jobId']}"
        exact_candidate = candidate
        if persist_attempts:
            pipeline_job = factory.domains.events.create_pipeline_job(
                "higgsfield_motion_generation",
                str(campaign["id"]),
                {
                    "workItemId": job["jobId"],
                    "sourceAssetId": job["sourceAssetId"],
                    "sourceSha256": job["sourceSha256"],
                    "provider": "higgsfield",
                    "providerModel": list(
                        job["productionRecipe"].get("stages") or [{}]
                    )[0].get("providerModel"),
                },
            )
            pipeline_job = factory.domains.events.start_pipeline_job(pipeline_job["id"])
            attempt_id = str(pipeline_job["attempt_id"])
            exact_candidate = {
                **candidate,
                "_providerPipelineJobId": str(pipeline_job["id"]),
                "_providerAttemptId": attempt_id,
            }
        try:
            request = higgsfield_request(
                exact_candidate,
                max_credits=max_total_credits,
                attempt_id=attempt_id,
            )
            provider_plan = build_higgsfield_production_plan(
                request,
                capabilities=capabilities,
            )
            quote = quote_higgsfield_production_plan(provider_plan)
        except Exception as exc:
            _mark_unsubmitted_attempts_no_effect(
                factory,
                [*prepared, exact_candidate],
                failure=type(exc).__name__,
            )
            raise
        amount = float(quote["amount"])
        total = round(total + amount, 4)
        prepared.append(
            {
                **exact_candidate,
                "quotedProviderCredits": amount,
                "providerPlanFingerprint": provider_plan["providerRequestFingerprint"],
                "providerExecutionFingerprint": provider_plan["executionFingerprint"],
                "providerSubmitContract": provider_plan["command"],
                "providerQuoteContract": provider_plan["quoteCommand"],
                "_higgsfieldPlan": provider_plan,
                "_higgsfieldCapabilities": capabilities,
                "_higgsfieldQuote": quote,
                "_campaignId": str(campaign["id"]),
                "_higgsfieldRecovery": None,
            }
        )
    if total > max_total_credits:
        _mark_unsubmitted_attempts_no_effect(
            factory,
            prepared,
            failure="production_batch_quote_exceeds_total_credit_cap",
        )
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
        factory,
        jobs,
        max_total_credits=max_total_credits,
        persist_attempts=True,
    )
    try:
        with file_lock(_provider_account_lock_path(factory)):
            return _authorize_prepared_higgsfield_jobs(factory, prepared)
    except Exception as exc:
        _mark_unsubmitted_attempts_no_effect(
            factory,
            prepared,
            failure=type(exc).__name__,
        )
        raise


def _mark_unsubmitted_attempts_no_effect(
    factory: Any,
    jobs: list[Mapping[str, Any]],
    *,
    failure: str,
) -> None:
    for job in jobs:
        pipeline_job_id = str(job.get("_providerPipelineJobId") or "")
        if not pipeline_job_id:
            continue
        pipeline_job = factory.domains.events.pipeline_job(pipeline_job_id)
        if pipeline_job.get("effect_state") != "PRE_EFFECT":
            continue
        factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "NO_EFFECT_CONFIRMED",
            evidence={"authorizationFailure": failure},
        )


def _authorize_prepared_higgsfield_jobs(
    factory: Any,
    prepared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    fresh = [job for job in prepared if job.get("_higgsfieldRecovery") is None]
    balance_snapshot = _authorize_batch_balance(
        factory,
        fresh,
        provider_snapshot=_provider_balance_snapshot() if fresh else None,
    )
    batch_scopes = [
        (
            higgsfield_spend_scope(
                job,
                provider_plan=dict(job["_higgsfieldPlan"]),
                provider_quote=dict(job["_higgsfieldQuote"]),
            ),
            float(job["quotedProviderCredits"]),
        )
        for job in fresh
    ]
    validate_provider_spend_batch_capacity(factory.conn, batch_scopes)
    authorized: list[dict[str, Any]] = []
    issued_authorization_ids: list[str] = []
    try:
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
                if scope.get("providerCommandFingerprint") != recovery.get(
                    "providerCommandFingerprint"
                ) or scope.get("quoteFingerprint") != _fingerprint(
                    dict(recovery["creditQuote"])
                ):
                    raise PermissionError(
                        "higgsfield_recovery_execution_binding_mismatch"
                    )
                authorized.append(
                    {
                        **job,
                        "_higgsfieldSpendScope": scope,
                        "_higgsfieldAuthorization": None,
                        "_providerPipelineJobId": str(recovery["attemptId"]).split(
                            ":", 1
                        )[0],
                    }
                )
                continue
            pipeline_job = factory.domains.events.pipeline_job(
                str(job["_providerPipelineJobId"])
            )
            exact_job = {
                **job,
                "_higgsfieldBalanceSnapshotFingerprint": balance_snapshot[
                    "fingerprint"
                ],
            }
            provider_plan = dict(job["_higgsfieldPlan"])
            scope = higgsfield_spend_scope(
                exact_job,
                provider_plan=provider_plan,
                provider_quote=dict(job["_higgsfieldQuote"]),
            )
            authorization = issue_provider_spend_authorization(
                factory.conn,
                scope=scope,
                campaign_id=str(job["_campaignId"]),
                max_credits=float(job["quotedProviderCredits"]),
                secret=secret,
                quote_provider=_BoundHiggsfieldQuote(job["_higgsfieldQuote"]),
                balance_provider=_BoundHiggsfieldBalance(balance_snapshot["credits"]),
            )
            issued_authorization_ids.append(str(authorization["authorizationId"]))
            factory.domains.events.mark_pipeline_effect_state(
                str(pipeline_job["id"]),
                "PRE_EFFECT",
                authorization_id=str(authorization["authorizationId"]),
                evidence={
                    "providerRequestFingerprint": provider_plan[
                        "providerRequestFingerprint"
                    ],
                    "executionFingerprint": provider_plan["executionFingerprint"],
                    "providerCommandFingerprint": scope["providerCommandFingerprint"],
                    "quoteFingerprint": scope["quoteFingerprint"],
                    "provider": "higgsfield",
                    "model": provider_plan["selectedModel"],
                    "batchBalanceSnapshot": balance_snapshot,
                    "creatorGovernance": authorization.get("governanceContext"),
                },
            )
            authorized.append(
                {
                    **exact_job,
                    "providerPlanFingerprint": provider_plan[
                        "providerRequestFingerprint"
                    ],
                    "providerExecutionFingerprint": provider_plan[
                        "executionFingerprint"
                    ],
                    "providerSubmitContract": provider_plan["command"],
                    "providerQuoteContract": provider_plan["quoteCommand"],
                    "_higgsfieldSpendScope": scope,
                    "_higgsfieldAuthorization": authorization,
                    "_creatorGovernance": authorization.get("governanceContext"),
                }
            )
    except Exception:
        for authorization_id in issued_authorization_ids:
            cancel_provider_spend_authorization(factory.conn, authorization_id)
        raise
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


def _provider_balance_snapshot() -> dict[str, Any]:
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    credits = HiggsfieldCliBalanceProvider().balance()
    if credits is None:
        raise PermissionError("higgsfield_batch_balance_unavailable")
    material = {
        "provider": "higgsfield",
        "observedAt": observed_at,
        "credits": float(credits),
    }
    return {**material, "evidenceFingerprint": _fingerprint(material)}


def _authorize_batch_balance(
    factory: Any,
    jobs: list[dict[str, Any]],
    *,
    provider_snapshot: Mapping[str, Any] | None = None,
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
    snapshot = dict(provider_snapshot or {})
    credits = snapshot.get("credits", authentication.get("credits"))
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
            (a.status = 'authorized' AND a.expires_at > ?)
            OR (
              a.status = 'consumed'
              AND NOT EXISTS (
                SELECT 1 FROM ai_cost_events e
                WHERE e.reservation_id = a.reservation_id
              )
            )
          )
        """,
        (datetime.now(UTC).isoformat().replace("+00:00", "Z"),),
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
        "observedAt": snapshot.get("observedAt") or capabilities.get("observedAt"),
        "credits": float(credits),
        "balanceEvidenceFingerprint": (
            snapshot.get("evidenceFingerprint")
            or _fingerprint(
                {
                    "provider": "higgsfield",
                    "observedAt": capabilities.get("observedAt"),
                    "credits": float(credits),
                }
            )
        ),
        "minimumRetainedCredits": minimum,
        "existingActiveReservations": active,
        "preparedBatchQuote": required,
        "projectedRemainingBalance": round(
            float(credits) - minimum - active - required,
            4,
        ),
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
    ensure_cost_table(factory.conn)
    issues: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    expired = factory.conn.execute(
        """
        SELECT authorization_id, request_fingerprint, expires_at
        FROM provider_spend_authorizations
        WHERE provider = 'higgsfield'
          AND status = 'authorized'
          AND expires_at <= ?
        ORDER BY expires_at, authorization_id
        """,
        (now,),
    ).fetchall()
    for row in expired:
        issues.append(
            _provider_issue(
                record=str(row["authorization_id"]),
                conflict="authorized_provider_spend_expired",
                manual_action="cancel the expired reservation before authorizing again",
                evidence={
                    "requestFingerprint": row["request_fingerprint"],
                    "expiresAt": row["expires_at"],
                },
            )
        )
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
        "OUTPUT_DOWNLOADED": (
            "downloaded_output_not_atomically_retained",
            "resume the exact staged file without another provider submission",
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
    cost_rows = factory.conn.execute(
        """
        SELECT e.id, e.amount, e.metadata_json,
               a.authorization_id, a.amount AS authorized_amount
        FROM ai_cost_events e
        JOIN provider_spend_authorizations a
          ON a.reservation_id = e.reservation_id
        WHERE e.provider = 'higgsfield'
        ORDER BY e.created_at, e.id
        """
    ).fetchall()
    for row in cost_rows:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if row["amount"] is None:
            issues.append(
                _provider_issue(
                    record=str(row["id"]),
                    conflict="provider_actual_credits_unknown",
                    manual_action="retain unknown cost until exact provider evidence exists",
                    evidence={
                        "authorizationId": row["authorization_id"],
                        "actualCredits": None,
                    },
                )
            )
        elif float(row["amount"]) > float(row["authorized_amount"]) + 0.0001 or bool(
            metadata.get("overspend")
        ):
            issues.append(
                _provider_issue(
                    record=str(row["id"]),
                    conflict="provider_actual_exceeds_authorization",
                    manual_action="review the durable overspend incident before progression",
                    evidence={
                        "authorizationId": row["authorization_id"],
                        "actualCredits": float(row["amount"]),
                        "authorizedMaximumCredits": float(row["authorized_amount"]),
                    },
                )
            )
    finalized = factory.conn.execute(
        """
        SELECT id, result_json
        FROM pipeline_jobs
        WHERE job_type = 'higgsfield_motion_generation'
          AND effect_state = 'FINALIZED'
        ORDER BY updated_at, id
        """
    ).fetchall()
    for row in finalized:
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if _json_contains_true(result, "reconciledCompletedRequest"):
            observations.append(
                {
                    "record": str(row["id"]),
                    "observation": "completed_receipt_recovered_without_provider_call",
                }
            )
    return {
        "ok": not issues,
        "schema": "campaign_factory.provider_control_reconciliation.v1",
        "provider": "higgsfield",
        "issueCount": len(issues),
        "issues": issues,
        "observationCount": len(observations),
        "observations": observations,
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


def _json_contains_true(value: Any, key: str) -> bool:
    if isinstance(value, Mapping):
        return value.get(key) is True or any(
            _json_contains_true(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_json_contains_true(item, key) for item in value)
    return False


def _completed_higgsfield_recovery(
    job: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return exact completed receipt evidence without authorizing another call."""

    from reel_factory.worker_api import higgsfield_execution_fingerprint

    receipt_dir = (
        Path(str(job["providerReviewRoot"])).expanduser().resolve() / "receipts"
    )
    if not receipt_dir.is_dir():
        return None
    expected_output = Path(str(job["providerOutputPath"])).expanduser().resolve()
    expected_source_sha = job.get("recreationAnchorSha256") or job.get("sourceSha256")
    expected_source_asset_id = (
        f"sha256:{job['recreationAnchorSha256']}"
        if job.get("recreationAnchorSha256")
        else job.get("sourceAssetId")
    )
    source_approval = job.get("sourceApproval")
    expected_source_approval_id = (
        f"recreation_anchor_approval:{job['recreationAnchorApprovalFingerprint']}"
        if job.get("recreationAnchorApprovalFingerprint")
        else (
            source_approval.get("approvalEventId")
            if isinstance(source_approval, Mapping)
            else None
        )
    )
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
        receipt_status = (
            str(receipt.get("status") or "") if isinstance(receipt, dict) else ""
        )
        final = receipt.get("finalOutput") if isinstance(receipt, dict) else None
        retained = receipt.get("retainedOutput") if isinstance(receipt, dict) else None
        downloaded = (
            receipt.get("downloadedOutput") if isinstance(receipt, dict) else None
        )
        downloaded_temporary_raw = (
            Path(str(downloaded.get("temporaryPath") or "")).expanduser()
            if isinstance(downloaded, dict)
            else None
        )
        downloaded_temporary = (
            downloaded_temporary_raw.resolve()
            if downloaded_temporary_raw is not None
            else None
        )
        downloaded_final = (
            Path(str(downloaded.get("finalPath") or "")).expanduser().resolve()
            if isinstance(downloaded, dict)
            else None
        )
        recovery_output = (
            final
            if isinstance(final, dict)
            else retained
            if isinstance(retained, dict)
            else downloaded
            if isinstance(downloaded, dict)
            else None
        )
        recovery_path = (
            Path(
                str(
                    recovery_output.get("path")
                    or recovery_output.get("temporaryPath")
                    or ""
                )
            )
            .expanduser()
            .resolve()
            if isinstance(recovery_output, dict)
            else None
        )
        if (
            receipt_status == "downloaded_output"
            and downloaded_temporary is not None
            and not downloaded_temporary.is_file()
            and downloaded_final is not None
        ):
            recovery_path = downloaded_final
        recoverable_status = receipt_status in {
            "completed",
            "downloaded_output",
            "output_retained",
            "rejected_unexpected_provider_audio",
        }
        source = receipt.get("source") if isinstance(receipt, dict) else None
        driving = receipt.get("drivingVideo") if isinstance(receipt, dict) else None
        anchor = (
            receipt.get("recreationAnchorApproval")
            if isinstance(receipt, dict)
            else None
        )
        reference_element = (
            receipt.get("referenceElement") if isinstance(receipt, dict) else None
        )
        provider_request_fingerprint = str(
            receipt.get("providerRequestFingerprint") or ""
        )
        expected_execution_fingerprint = (
            higgsfield_execution_fingerprint(
                provider_request_fingerprint,
                output_path=expected_output,
                review_root=Path(str(job["providerReviewRoot"])),
            )
            if len(provider_request_fingerprint) == 64
            else ""
        )
        reference_element_file = (
            Path(str(reference_element.get("filePath") or "")).expanduser().resolve()
            if isinstance(reference_element, dict)
            else None
        )
        if (
            isinstance(receipt, dict)
            and recoverable_status
            and isinstance(recovery_output, dict)
            and (
                receipt.get("workItemId") == job.get("jobId")
                or (
                    recovery_path == expected_output
                    or Path(str(downloaded.get("finalPath") or ""))
                    .expanduser()
                    .resolve()
                    == expected_output
                    if isinstance(downloaded, dict)
                    else False
                )
            )
        ):
            conflicting_completed_receipt = True
        if (
            not isinstance(receipt, dict)
            or not recoverable_status
            or receipt.get("workItemId") != job.get("jobId")
            or receipt.get("model") != stage.get("providerModel")
            or receipt.get("seed") != job.get("seed")
            or not receipt.get("generationId")
            or not receipt.get("authorizationId")
            or not receipt.get("attemptId")
            or not isinstance(recovery_output, dict)
            or not isinstance(source, dict)
            or source.get("sha256") != expected_source_sha
            or source.get("assetId") != expected_source_asset_id
            or source.get("approvalId") != expected_source_approval_id
            or (
                job.get("referenceVideoSha256")
                and (
                    not isinstance(driving, dict)
                    or driving.get("sha256") != job.get("referenceVideoSha256")
                )
            )
            or (
                job.get("recreationAnchorApprovalFingerprint")
                and (
                    not isinstance(anchor, dict)
                    or anchor.get("approvalFingerprint")
                    != job.get("recreationAnchorApprovalFingerprint")
                    or anchor.get("receiptSha256")
                    != dict(job.get("recreationAnchorApproval") or {}).get(
                        "receiptSha256"
                    )
                )
            )
            or (
                job.get("intent") == "recreate_reel"
                and (
                    not isinstance(reference_element, dict)
                    or reference_element_file is None
                    or not reference_element_file.is_file()
                    or _sha256_file(reference_element_file)
                    != reference_element.get("fileSha256")
                )
            )
            or recovery_path is None
            or recovery_path.is_symlink()
            or (
                downloaded_temporary_raw is not None
                and downloaded_temporary_raw.is_symlink()
            )
            or (
                receipt_status == "downloaded_output"
                and (
                    not isinstance(downloaded, dict)
                    or downloaded_final != expected_output
                )
            )
            or (
                receipt_status != "downloaded_output"
                and receipt_status != "rejected_unexpected_provider_audio"
                and recovery_path != expected_output
            )
            or not recovery_path.is_file()
            or _sha256_file(recovery_path) != recovery_output.get("sha256")
            or not isinstance(receipt.get("creditQuote"), dict)
            or len(provider_request_fingerprint) != 64
            or receipt.get("executionFingerprint") != expected_execution_fingerprint
            or len(str(receipt.get("providerCommandFingerprint") or "")) != 64
        ):
            continue
        from .production_batch_results import probe_production_video

        probe_production_video(recovery_path)
        matches.append((receipt_path, receipt))
    if len(matches) > 1:
        raise PermissionError("higgsfield_recovery_receipt_is_ambiguous")
    if not matches:
        if conflicting_completed_receipt:
            raise PermissionError("higgsfield_recovery_source_binding_mismatch")
        return None
    receipt_path, receipt = matches[0]
    final = (
        receipt.get("finalOutput")
        or receipt.get("retainedOutput")
        or receipt.get("downloadedOutput")
    )
    return {
        "receiptPath": str(receipt_path),
        "receiptSha256": _sha256_file(receipt_path),
        "generationId": str(receipt["generationId"]),
        "outputPath": str(recovery_path),
        "outputSha256": str(final["sha256"]),
        "authorizationId": str(receipt["authorizationId"]),
        "attemptId": str(receipt["attemptId"]),
        "providerRequestFingerprint": str(receipt["providerRequestFingerprint"]),
        "executionFingerprint": receipt.get("executionFingerprint"),
        "providerCommandFingerprint": receipt.get("providerCommandFingerprint"),
        "creditQuote": dict(receipt["creditQuote"]),
        **(
            {"recoveryStatus": str(receipt["status"])}
            if receipt.get("status") != "completed"
            else {}
        ),
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
        pipeline_job = factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "OUTPUT_DOWNLOADED",
            external_operation_id=external_id,
            evidence={
                "receiptPath": str(receipt_path),
                "downloadedOutput": receipt.get("downloadedOutput"),
            },
        )
        effect_state = str(pipeline_job["effect_state"])
    if effect_state == "OUTPUT_DOWNLOADED":
        factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            "OUTPUT_RETAINED",
            external_operation_id=external_id,
            evidence={
                "receiptPath": str(receipt_path),
                "outputSha256": dict(receipt.get("finalOutput") or {}).get("sha256"),
            },
        )
    authorization = load_provider_spend_authorization(
        factory.conn,
        str(receipt["authorizationId"]),
        secret=os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", ""),
    )
    record_provider_execution(
        factory.conn,
        authorization=authorization,
        execution={
            "events": [
                {
                    "provider": "higgsfield",
                    "operation": "video_generation",
                    "model": receipt.get("model"),
                    "jobId": receipt.get("generationId"),
                    "actualCredits": receipt.get("creditsConsumed"),
                }
            ]
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


def resume_recovered_higgsfield_attempt(
    factory: Any,
    *,
    pipeline_job_id: str,
    request: Any,
    recovery: Mapping[str, Any],
) -> dict[str, Any]:
    """Resume one retained/downloaded receipt without another provider submit."""

    from reel_factory.worker_api import resume_higgsfield_local_output

    load_provider_spend_authorization(
        factory.conn,
        str(recovery["authorizationId"]),
        secret=os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", ""),
    )
    effect_rank = {
        "PRE_EFFECT": 0,
        "AUTHORIZATION_CONSUMED": 1,
        "SUBMISSION_STARTED": 2,
        "EXTERNAL_ID_KNOWN": 3,
        "PROVIDER_COMPLETED": 4,
        "OUTPUT_DOWNLOADED": 5,
        "OUTPUT_RETAINED": 6,
        "COST_RECONCILED": 7,
    }

    def record_effect(state: str, evidence: dict[str, Any]) -> None:
        current = factory.domains.events.pipeline_job(pipeline_job_id)
        if effect_rank.get(state, 100) <= effect_rank.get(
            str(current.get("effect_state") or "PRE_EFFECT"), -1
        ):
            return
        factory.domains.events.mark_pipeline_effect_state(
            pipeline_job_id,
            state,
            authorization_id=str(recovery["authorizationId"]),
            external_operation_id=(
                str(evidence["externalOperationId"])
                if evidence.get("externalOperationId")
                else None
            ),
            evidence=evidence,
        )

    return resume_higgsfield_local_output(
        request,
        receipt_path=Path(str(recovery["receiptPath"])).expanduser().resolve(),
        effect_recorder=record_effect,
    )


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
    live_quote = quote_higgsfield_production_plan(plan)
    live_quote_fingerprint = higgsfield_quote_fingerprint(live_quote)
    expected_scope = {
        **plan["authorizationScope"],
        "quoteFingerprint": live_quote_fingerprint,
    }
    if (
        plan["providerRequestFingerprint"] != job["providerPlanFingerprint"]
        or expected_scope != spend_scope
    ):
        raise PermissionError("higgsfield_authorized_provider_plan_mismatch")
    if live_quote_fingerprint != higgsfield_quote_fingerprint(
        dict(authorization["providerQuote"])
    ):
        raise PermissionError("higgsfield_quote_changed_after_authorization")
    authorization_id = str(authorization["authorizationId"])
    verify_authorization(
        authorization,
        expected_scope=expected_scope,
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
