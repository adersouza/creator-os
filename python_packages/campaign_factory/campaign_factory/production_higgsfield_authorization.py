"""Higgsfield quote and spend binding for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
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
        recovery = _completed_higgsfield_recovery(
            candidate,
            provider_plan=provider_plan,
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
                "_higgsfieldRecovery": recovery,
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
        if job.get("_higgsfieldRecovery") is not None:
            authorized.append(
                {
                    **job,
                    "_higgsfieldSpendScope": scope,
                    "_higgsfieldAuthorization": None,
                }
            )
            continue
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


def _completed_higgsfield_recovery(
    job: Mapping[str, Any],
    *,
    provider_plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return exact completed receipt evidence without authorizing another call."""

    receipt_path = (
        Path(str(provider_plan["reviewRoot"])).expanduser().resolve()
        / "receipts"
        / f"{provider_plan['requestFingerprint']}.higgsfield_submission.json"
    )
    if not receipt_path.exists():
        return None
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise PermissionError("higgsfield_recovery_receipt_is_unsafe")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError("higgsfield_recovery_receipt_is_invalid") from exc
    final = receipt.get("finalOutput") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("status") != "completed"
        or receipt.get("requestFingerprint") != provider_plan["requestFingerprint"]
        or not receipt.get("generationId")
        or not isinstance(final, dict)
    ):
        raise PermissionError("higgsfield_recovery_receipt_is_incomplete")
    output = Path(str(final.get("path") or "")).expanduser()
    expected_output = Path(str(job["providerOutputPath"])).expanduser().resolve()
    if (
        output.is_symlink()
        or output.resolve() != expected_output
        or not expected_output.is_file()
        or _sha256_file(expected_output) != final.get("sha256")
    ):
        raise PermissionError("higgsfield_recovery_output_binding_mismatch")
    source = receipt.get("source")
    driving = receipt.get("drivingVideo")
    if (
        not isinstance(source, dict)
        or source.get("sha256") != job.get("sourceSha256")
        or (
            job.get("referenceVideoSha256")
            and (
                not isinstance(driving, dict)
                or driving.get("sha256") != job.get("referenceVideoSha256")
            )
        )
    ):
        raise PermissionError("higgsfield_recovery_source_binding_mismatch")
    return {
        "receiptPath": str(receipt_path),
        "receiptSha256": _sha256_file(receipt_path),
        "generationId": str(receipt["generationId"]),
        "outputPath": str(expected_output),
        "outputSha256": str(final["sha256"]),
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
    if (
        not generation_id
        or isinstance(credits, bool)
        or not isinstance(credits, (int, float))
        or float(credits) <= 0
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
        or row["cost_unit"] != "higgsfield_credits"
        or row["authorized_unit"] != "higgsfield_credits"
        or abs(float(row["cost_amount"]) - float(credits)) > 0.0001
        or abs(float(row["authorized_amount"]) - float(credits)) > 0.0001
        or float(job["quotedProviderCredits"]) + 0.0001 < float(credits)
    ):
        raise PermissionError("higgsfield_recovery_cost_binding_mismatch")
    return {
        "authorizationId": row["authorization_id"],
        "reservationId": row["reservation_id"],
        "costEventIds": [row["cost_event_id"]],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
