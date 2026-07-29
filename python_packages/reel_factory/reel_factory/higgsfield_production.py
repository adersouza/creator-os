"""Narrow authenticated Higgsfield adapter for review-only video candidates.

This module deliberately models the live CLI contracts used by Creator OS.  It
does not route between providers or select production defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from creator_os_core.recreation_anchor_approval import (
    load_recreation_anchor_approval,
)

from .evidence_store import record_asset_generation
from .fileops import atomic_write_text
from .generation_provider import (
    HiggsfieldCliAdapter,
    download_result,
    extract_id,
    extract_status,
    extract_url,
    result_credits,
)

SCHEMA = "reel_factory.higgsfield_production_receipt.v1"
CAPABILITY_SCHEMA = "reel_factory.higgsfield_production_capabilities.v1"
REVIEW_SCHEMA = "reel_factory.intent_video_bakeoff_review.v1"
REVIEW_FIELDS = (
    "identityPreservation",
    "bodyConsistency",
    "faceStability",
    "handAnatomyQuality",
    "motionSimilarity",
    "casualPhoneAppearance",
    "lipSync",
    "expressiveness",
    "attractiveness",
    "generationTimeSeconds",
    "creditsConsumed",
    "dollarCost",
    "wouldPost",
    "facialConsistency",
    "clothingStability",
    "backgroundStability",
    "broadActionFidelity",
    "cameraFramingFidelity",
    "pacingFidelity",
    "choreographyFidelity",
    "obviousAiArtifacts",
    "audioSynchronization",
)
RecipeId = Literal[
    "higgsfield_passive_selfie",
    "higgsfield_recreate_reel",
    "higgsfield_motion_copy_animate",
    "higgsfield_motion_copy_replace",
    "higgsfield_talking_speak",
    "higgsfield_talking_veo",
    "higgsfield_talking_motion_copy",
]


class HiggsfieldFeatureUnavailable(RuntimeError):
    """Raised before quote/submission when the authenticated surface lacks a tool."""


class HiggsfieldSubmissionNeedsReconciliation(RuntimeError):
    """A create command may have submitted; never submit it again blindly."""


@dataclass(frozen=True, slots=True)
class HiggsfieldCandidate:
    recipe_id: RecipeId
    purpose: str
    actual_tool: str | None
    exposed_job_type: str | None
    status: Literal["supported", "experimental", "unresolved", "rejected_recipe"]
    unavailable_reason: str | None = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["limitations"] = list(self.limitations)
        return value


@dataclass(frozen=True, slots=True)
class HiggsfieldProductionRequest:
    recipe_id: RecipeId
    creator: str
    soul_id: str
    source_approval: str
    output_path: Path
    review_root: Path
    source_image_path: Path | None = None
    source_generation_id: str | None = None
    source_generation_approval: str | None = None
    driving_video_path: Path | None = None
    speech_audio_path: Path | None = None
    prompt: str | None = None
    script: str | None = None
    tone: str | None = None
    pacing: str | None = None
    emotion: str | None = None
    model: str | None = None
    duration_seconds: int = 5
    max_credits: float | None = None
    seed: int | None = None
    reference_elements_path: Path | None = None
    work_item_id: str | None = None
    authorization_id: str | None = None
    attempt_id: str | None = None
    client_request_correlation_id: str | None = None
    recreation_anchor_approval: dict[str, Any] | None = None


_EXACT_JOB_TYPES = (
    "kling3_0",
    "kling3_0_turbo",
    "seedance_2_0",
    "seedance_2_0_mini",
    "kling3_0_motion_control",
    "veo3_1",
)
# The v1.1.19 CLI exposes duration as a cost parameter but rejects it on the
# generic model-cost command. The authenticated 2026-07-24 account transaction
# for a completed five-second Pro job charged exactly 16 credits.
_KLING3_MOTION_CONTROL_PRO_CREDITS_PER_SECOND = 3.2


def discover_higgsfield_production_capabilities(
    *,
    adapter: HiggsfieldCliAdapter | None = None,
) -> dict[str, Any]:
    """Inspect the authenticated CLI and return the exact callable contracts."""

    cli = adapter or HiggsfieldCliAdapter()
    account = cli.run_json(["higgsfield", "account", "status", "--json"])
    souls = _items(
        cli.run_json(["higgsfield", "soul-id", "list", "--size", "100", "--json"])
    )
    models = _items(cli.run_json(["higgsfield", "model", "list", "--video", "--json"]))
    workflows = _items(cli.run_json(["higgsfield", "workflow", "list", "--json"]))
    identifiers = {
        str(row.get("job_type") or row.get("id") or "")
        for row in (*models, *workflows)
        if isinstance(row, dict)
    }
    contracts: dict[str, Any] = {}
    for job_type in _EXACT_JOB_TYPES:
        if job_type not in identifiers:
            continue
        command = (
            ["higgsfield", "workflow", "get", job_type, "--json"]
            if any(str(row.get("job_type") or "") == job_type for row in workflows)
            else ["higgsfield", "model", "get", job_type, "--json"]
        )
        contracts[job_type] = cli.run_json(command)
    candidates = _candidate_capabilities(identifiers)
    return {
        "schema": CAPABILITY_SCHEMA,
        "observedAt": _utc_now(),
        "authentication": {
            "authenticated": bool(account),
            "plan": (
                _account_value(account, "plan")
                or _account_value(account, "subscription_plan_type")
            ),
            "credits": _numeric_account_value(account, "credits"),
        },
        "souls": [
            {
                "id": row.get("id") or row.get("soul_id"),
                "name": row.get("name"),
                "status": row.get("status"),
                "type": row.get("type"),
            }
            for row in souls
            if isinstance(row, dict)
        ],
        "models": models,
        "workflows": workflows,
        "contracts": contracts,
        "candidates": {
            key: candidate.to_dict() for key, candidate in candidates.items()
        },
    }


def higgsfield_candidate_catalog(
    capabilities: dict[str, Any],
) -> dict[str, HiggsfieldCandidate]:
    rows = [
        *(capabilities.get("models") or []),
        *(capabilities.get("workflows") or []),
    ]
    identifiers = {
        str(row.get("job_type") or row.get("id") or "")
        for row in rows
        if isinstance(row, dict)
    }
    return _candidate_capabilities(identifiers)


def build_higgsfield_production_plan(
    request: HiggsfieldProductionRequest,
    *,
    capabilities: dict[str, Any],
    adapter: HiggsfieldCliAdapter | None = None,
) -> dict[str, Any]:
    candidate = higgsfield_candidate_catalog(capabilities)[request.recipe_id]
    if candidate.status != "supported" and not (
        request.recipe_id == "higgsfield_motion_copy_animate"
        and candidate.status == "experimental"
    ):
        raise HiggsfieldFeatureUnavailable(
            candidate.unavailable_reason or f"{request.recipe_id} is unavailable"
        )
    cli = adapter or HiggsfieldCliAdapter()
    soul = _selected_soul(capabilities, request.soul_id)
    source_token, source = _source_identity(request, cli=cli)
    driving = _optional_media_identity(request.driving_video_path, "driving video")
    speech = _optional_media_identity(request.speech_audio_path, "speech audio")
    reference_elements_path, reference_element = _reference_element(request)
    anchor_approval = _recreation_anchor_approval(
        request,
        source=source,
        driving=driving,
    )
    if anchor_approval is not None:
        source = {**source, "kind": "approved_recreation_anchor"}
    reference_element_binding = (
        {
            "id": str(reference_element["id"]),
            "creator": request.creator.strip().lower(),
            "filePath": str(reference_elements_path),
            "fileSha256": _sha256_file(reference_elements_path),
            "deliveryMethod": "prompt_token",
        }
        if reference_elements_path is not None and reference_element is not None
        else None
    )
    prompt = _candidate_prompt(request, reference_element=reference_element)
    command = _candidate_command(
        request,
        candidate=candidate,
        source_token=source_token,
        driving=driving,
        speech=speech,
        prompt=prompt,
        reference_elements_path=reference_elements_path,
    )
    selected_model = command[3]
    material = {
        "recipeId": request.recipe_id,
        "creator": request.creator.strip().lower(),
        "soulId": request.soul_id,
        "source": source,
        "recreationAnchorApproval": anchor_approval,
        "drivingVideo": driving,
        "speechAudio": speech,
        "referenceElement": reference_element_binding,
        "prompt": prompt,
        "model": selected_model,
        "seed": request.seed,
        "outputPath": str(_output_path(request.output_path)),
    }
    request_fingerprint = _fingerprint(material)
    return {
        "schema": "reel_factory.higgsfield_production_plan.v1",
        "requestFingerprint": request_fingerprint,
        "recipe": candidate.to_dict(),
        "creator": request.creator.strip().lower(),
        "soul": soul,
        "source": source,
        "recreationAnchorApproval": anchor_approval,
        "drivingVideo": driving,
        "speechAudio": speech,
        "referenceElement": reference_element_binding,
        "prompt": prompt,
        "script": request.script,
        "command": command,
        "selectedModel": selected_model,
        "seed": request.seed,
        "quoteCommand": _quote_command(command, driving=driving),
        "quoteParameters": _quote_parameters(command, driving=driving),
        "outputPath": str(_output_path(request.output_path)),
        "reviewRoot": str(_review_root(request.review_root)),
        "maxCredits": request.max_credits,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def quote_higgsfield_production_plan(
    plan: dict[str, Any],
    *,
    adapter: HiggsfieldCliAdapter | None = None,
) -> dict[str, Any]:
    recipe = plan.get("recipe")
    if (
        isinstance(recipe, dict)
        and recipe.get("exposed_job_type") == "kling3_0_motion_control"
    ):
        parameters = plan.get("quoteParameters")
        if not isinstance(parameters, dict):
            raise ValueError("Higgsfield Motion Control quote parameters are missing")
        duration = parameters.get("durationSeconds")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or float(duration) <= 0
        ):
            raise ValueError("Higgsfield Motion Control quote duration is invalid")
        billed_seconds = max(1, int(round(float(duration))))
        credits = round(
            billed_seconds * _KLING3_MOTION_CONTROL_PRO_CREDITS_PER_SECOND,
            4,
        )
        return {
            "provider": "higgsfield",
            "amount": credits,
            "unit": "higgsfield_credits",
            "source": "authenticated_higgsfield_transaction_duration_rate",
            "raw": {
                "jobType": "kling3_0_motion_control",
                "mode": parameters.get("mode"),
                "durationSeconds": float(duration),
                "billedSeconds": billed_seconds,
                "creditsPerSecond": (_KLING3_MOTION_CONTROL_PRO_CREDITS_PER_SECOND),
            },
        }
    command = plan.get("quoteCommand")
    if not isinstance(command, list) or not command:
        raise ValueError("Higgsfield quote command is missing")
    raw = (adapter or HiggsfieldCliAdapter()).run_json(
        [str(value) for value in command]
    )
    cli_credits = _find_number(raw, ("credits", "creditCost", "costCredits", "cost"))
    if cli_credits is None or cli_credits <= 0:
        raise RuntimeError("higgsfield_quote_missing_credits")
    return {
        "provider": "higgsfield",
        "amount": cli_credits,
        "unit": "higgsfield_credits",
        "source": "authenticated_higgsfield_cli_generate_cost",
        "raw": raw,
    }


def execute_higgsfield_production(
    request: HiggsfieldProductionRequest,
    *,
    capabilities: dict[str, Any] | None = None,
    adapter: HiggsfieldCliAdapter | None = None,
    confirm_paid: bool,
) -> dict[str, Any]:
    """Submit once, poll, retain, hash, register, and write review evidence."""

    cli = adapter or HiggsfieldCliAdapter()
    live = capabilities or discover_higgsfield_production_capabilities(adapter=cli)
    plan = build_higgsfield_production_plan(request, capabilities=live, adapter=cli)
    cap = _positive_credits(request.max_credits)
    if not confirm_paid:
        raise PermissionError("Higgsfield generation requires --confirm-paid")
    quote = quote_higgsfield_production_plan(plan, adapter=cli)
    if float(quote["amount"]) > cap:
        raise PermissionError(
            f"higgsfield_quote_exceeds_credit_cap:{quote['amount']} > {cap}"
        )
    account_status = cli.run_json(["higgsfield", "account", "status", "--json"])
    balance_before = _numeric_account_value(account_status, "credits")
    if balance_before is None or balance_before < float(quote["amount"]):
        raise PermissionError("higgsfield_credit_balance_insufficient_or_unavailable")
    review_root = Path(plan["reviewRoot"])
    receipt_dir = review_root / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / (
        f"{plan['requestFingerprint']}.higgsfield_submission.json"
    )
    existing = _read_receipt(receipt_path) if receipt_path.exists() else None
    if existing is not None:
        return _recover_higgsfield_generation(
            request,
            plan=plan,
            receipt=existing,
            receipt_path=receipt_path,
            adapter=cli,
        )
    receipt = {
        "schema": SCHEMA,
        "requestFingerprint": plan["requestFingerprint"],
        "workItemId": request.work_item_id,
        "authorizationId": request.authorization_id,
        "attemptId": request.attempt_id,
        "externalOperationId": None,
        "operationReceipt": {
            "schema": "pipeline.operation_receipt.v1",
            "workItemId": request.work_item_id,
            "authorizationId": request.authorization_id,
            "attemptId": request.attempt_id,
            "externalOperationId": None,
        },
        "clientRequestCorrelationId": request.client_request_correlation_id,
        "status": "ready_to_submit",
        "recipe": plan["recipe"],
        "provider": "higgsfield",
        "tool": "authenticated_higgsfield_cli",
        "model": plan["selectedModel"],
        "seed": request.seed,
        "soulId": request.soul_id,
        "source": plan["source"],
        "recreationAnchorApproval": plan["recreationAnchorApproval"],
        "drivingVideo": plan["drivingVideo"],
        "speechAudio": plan["speechAudio"],
        "referenceElement": plan["referenceElement"],
        "prompt": plan["prompt"],
        "script": plan["script"],
        "creditQuote": quote,
        "creditsConsumed": None,
        "creditsConsumedSource": None,
        "balanceBefore": balance_before,
        "providerAccountSnapshot": _scrub_provider_payload(account_status),
        "balanceAfter": None,
        "generationId": None,
        "submittedAt": None,
        "completedAt": None,
        "generationDurationSeconds": None,
        "resultUrl": None,
        "finalOutput": None,
        "registration": None,
        "review": _empty_review(),
        "evidencePath": str(receipt_path),
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
    _write_receipt(receipt_path, receipt)
    started = time.monotonic()
    receipt["status"] = "submission_started"
    receipt["submittedAt"] = _utc_now()
    _write_receipt(receipt_path, receipt)
    try:
        created = cli.run_json([str(value) for value in plan["command"]])
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        receipt["status"] = "submission_ambiguous"
        receipt["failure"] = type(exc).__name__
        _write_receipt(receipt_path, receipt)
        raise HiggsfieldSubmissionNeedsReconciliation(
            "Higgsfield submission outcome is ambiguous; do not retry blindly"
        ) from exc
    generation_id = extract_id(created)
    if not generation_id:
        receipt["status"] = "submission_ambiguous"
        receipt["submissionResponse"] = _scrub_provider_payload(created)
        _write_receipt(receipt_path, receipt)
        raise HiggsfieldSubmissionNeedsReconciliation(
            "Higgsfield submission returned no generation id; do not retry blindly"
        )
    _bind_external_operation(receipt, generation_id)
    receipt["status"] = str(extract_status(created) or "created")
    receipt["submissionResponse"] = _scrub_provider_payload(created)
    _write_receipt(receipt_path, receipt)
    return _complete_higgsfield_generation(
        request,
        plan=plan,
        receipt=receipt,
        receipt_path=receipt_path,
        adapter=cli,
        started=started,
    )


def _recover_higgsfield_generation(
    request: HiggsfieldProductionRequest,
    *,
    plan: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    adapter: HiggsfieldCliAdapter,
) -> dict[str, Any]:
    if receipt.get("requestFingerprint") != plan["requestFingerprint"]:
        raise PermissionError("higgsfield_recovery_scope_mismatch")
    if receipt.get("status") == "completed":
        final = receipt.get("finalOutput")
        if not isinstance(final, dict):
            raise PermissionError("higgsfield_completed_receipt_output_missing")
        output = _output_path(Path(str(final.get("path") or "")))
        if _sha256_file(output) != final.get("sha256"):
            raise PermissionError("higgsfield_completed_output_sha256_mismatch")
        _probe_video(output)
        generation_id = receipt.get("generationId")
        if isinstance(generation_id, str) and generation_id:
            _bind_external_operation(receipt, generation_id)
            _write_receipt(receipt_path, receipt)
        return receipt
    if receipt.get("status") == "submission_ambiguous" and not receipt.get(
        "generationId"
    ):
        generation = _reconcile_submission_history(
            request,
            plan=plan,
            receipt=receipt,
            adapter=adapter,
        )
        if generation is None:
            raise HiggsfieldSubmissionNeedsReconciliation(
                "Higgsfield submission history did not yield one exact match; "
                "do not resubmit"
            )
        _bind_external_operation(receipt, str(generation["id"]))
        receipt["status"] = str(generation.get("status") or "reconciled")
        receipt["submissionHistoryReconciliation"] = {
            "status": "matched",
            "matchedAt": _utc_now(),
            "providerCreatedAt": generation.get("created_at"),
            "historyItemFingerprint": hashlib.sha256(
                json.dumps(
                    _scrub_provider_payload(generation),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        }
        _write_receipt(receipt_path, receipt)
    if not receipt.get("generationId"):
        raise PermissionError("higgsfield_submission_not_recoverable")
    return _complete_higgsfield_generation(
        request,
        plan=plan,
        receipt=receipt,
        receipt_path=receipt_path,
        adapter=adapter,
        started=time.monotonic(),
    )


def _bind_external_operation(receipt: dict[str, Any], operation_id: str) -> None:
    receipt["generationId"] = operation_id
    receipt["externalOperationId"] = operation_id
    operation = receipt.get("operationReceipt")
    if not isinstance(operation, dict):
        operation = {
            "schema": "pipeline.operation_receipt.v1",
            "workItemId": receipt.get("workItemId"),
            "authorizationId": receipt.get("authorizationId"),
            "attemptId": receipt.get("attemptId"),
        }
        receipt["operationReceipt"] = operation
    operation["externalOperationId"] = operation_id


def _reconcile_submission_history(
    request: HiggsfieldProductionRequest,
    *,
    plan: dict[str, Any],
    receipt: dict[str, Any],
    adapter: HiggsfieldCliAdapter,
) -> dict[str, Any] | None:
    """Bind one ambiguous submission to one exact recent provider job."""

    submitted_at = _provider_timestamp(receipt.get("submittedAt"))
    if submitted_at is None:
        return None
    try:
        history = adapter.run_json(
            [
                "higgsfield",
                "generate",
                "list",
                "--video",
                "--size",
                "100",
                "--json",
            ]
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return None
    matches = [
        item
        for item in _items(history)
        if _history_item_matches(
            item,
            request=request,
            plan=plan,
            submitted_at=submitted_at,
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _history_item_matches(
    item: dict[str, Any],
    *,
    request: HiggsfieldProductionRequest,
    plan: dict[str, Any],
    submitted_at: datetime,
) -> bool:
    generation_id = str(item.get("id") or "").strip()
    created_at = _provider_timestamp(item.get("created_at"))
    if not generation_id or created_at is None:
        return False
    if (
        not submitted_at - timedelta(seconds=30)
        <= created_at
        <= submitted_at + timedelta(minutes=15)
    ):
        return False
    if str(item.get("job_type") or item.get("model") or "") != str(
        plan.get("selectedModel") or ""
    ):
        return False
    params = item.get("params")
    if not isinstance(params, dict):
        return False
    if str(params.get("prompt") or "") != str(plan.get("prompt") or ""):
        return False
    try:
        duration = int(params.get("duration"))
    except (TypeError, ValueError):
        return False
    if duration != int(request.duration_seconds):
        return False
    if params.get("aspect_ratio") not in {None, "9:16"}:
        return False
    if request.seed is not None and params.get("seed") is not None:
        try:
            if int(params["seed"]) != request.seed:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _provider_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _complete_higgsfield_generation(
    request: HiggsfieldProductionRequest,
    *,
    plan: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    adapter: HiggsfieldCliAdapter,
    started: float,
) -> dict[str, Any]:
    generation_id = str(receipt["generationId"])
    completed = adapter.run_json(
        [
            "higgsfield",
            "generate",
            "wait",
            generation_id,
            "--timeout",
            "30m",
            "--interval",
            "5s",
            "--json",
        ]
    )
    status = str(extract_status(completed) or "")
    if status != "completed":
        receipt["status"] = status or "poll_incomplete"
        receipt["pollResponse"] = completed
        _write_receipt(receipt_path, receipt)
        raise RuntimeError(f"higgsfield_generation_not_completed:{status}")
    result_url = extract_url(completed)
    if not result_url:
        inspected = adapter.run_json(
            ["higgsfield", "generate", "get", generation_id, "--json"]
        )
        result_url = extract_url(inspected)
        completed = inspected
    if not result_url:
        receipt["status"] = "completed_without_result_url"
        _write_receipt(receipt_path, receipt)
        raise RuntimeError("higgsfield_completed_result_url_missing")
    output = _output_path(request.output_path)
    if output.exists():
        raise FileExistsError(f"higgsfield_output_collision:{output}")
    download_result(result_url, output)
    probe = _probe_video(output)
    if (
        request.recipe_id
        in {
            "higgsfield_passive_selfie",
            "higgsfield_recreate_reel",
        }
        and probe["audioStreams"]
    ):
        output.unlink(missing_ok=True)
        raise RuntimeError("higgsfield_silent_candidate_returned_audio")
    digest = _sha256_file(output)
    balance_after = _numeric_account_value(
        adapter.run_json(["higgsfield", "account", "status", "--json"]), "credits"
    )
    exposed_credits = result_credits(completed)
    balance_delta = (
        round(float(receipt["balanceBefore"]) - float(balance_after), 4)
        if balance_after is not None and receipt.get("balanceBefore") is not None
        else None
    )
    consumed = (
        exposed_credits
        if exposed_credits is not None
        else balance_delta
        if balance_delta is not None and balance_delta >= 0
        else None
    )
    generation_duration = round(time.monotonic() - started, 3)
    review = dict(receipt.get("review") or _empty_review())
    review.update(
        {
            "generationTimeSeconds": generation_duration,
            "creditsConsumed": consumed,
            "dollarCost": None,
        }
    )
    receipt.update(
        {
            "status": "completed",
            "completedAt": _utc_now(),
            "generationDurationSeconds": generation_duration,
            "resultUrl": _redacted_result_url(result_url),
            "resultResponse": _scrub_provider_payload(completed),
            "creditsConsumed": consumed,
            "creditsConsumedSource": (
                "generation_response"
                if exposed_credits is not None
                else "account_balance_delta"
                if consumed is not None
                else None
            ),
            "balanceAfter": balance_after,
            "finalOutput": {
                "path": str(output),
                "sha256": digest,
                "bytes": output.stat().st_size,
                "probe": probe,
            },
            "review": review,
        }
    )
    _write_receipt(receipt_path, receipt)
    registration = _register_review_output(
        request, receipt=receipt, receipt_path=receipt_path
    )
    receipt["registration"] = registration
    _write_receipt(receipt_path, receipt)
    return receipt


def _register_review_output(
    request: HiggsfieldProductionRequest,
    *,
    receipt: dict[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    generation_id = str(receipt["generationId"])
    lineage = {
        "schema": "reel_factory.higgsfield_video_lineage.v1",
        "source": {
            "referenceId": request.source_approval,
            "startImage": (receipt.get("source") or {}).get("path"),
            "recreationAnchorApproval": receipt.get("recreationAnchorApproval"),
            "soulId": request.soul_id,
            "drivingVideo": receipt.get("drivingVideo"),
            "speechAudio": receipt.get("speechAudio"),
            "referenceElement": receipt.get("referenceElement"),
        },
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": request.recipe_id,
            "status": "completed",
            "models": {"video": receipt["model"]},
            "videoJobId": generation_id,
            "videoResultUrl": receipt.get("resultUrl"),
            "soulId": None,
            "params": {
                "recipeId": request.recipe_id,
                "seed": request.seed,
                "soulSourceId": request.soul_id,
                "creditQuote": receipt.get("creditQuote"),
                "creditsConsumed": receipt.get("creditsConsumed"),
                "sourceSha256": (receipt.get("source") or {}).get("sha256"),
                "drivingVideoSha256": (
                    (receipt.get("drivingVideo") or {}).get("sha256")
                ),
                "speechAudioSha256": ((receipt.get("speechAudio") or {}).get("sha256")),
                "outputSha256": (receipt.get("finalOutput") or {}).get("sha256"),
            },
            "raw": {"video": receipt.get("resultResponse") or {}},
        },
        "assets": {
            "localPaths": {
                "image": (receipt.get("source") or {}).get("path"),
                "video": (receipt.get("finalOutput") or {}).get("path"),
            }
        },
        "review": {"humanReviewRequired": True},
    }
    return record_asset_generation(
        request.review_root,
        campaign="intent_video_bakeoff",
        creator=request.creator,
        prompt_json_path=receipt_path,
        stem=f"{request.recipe_id}_{generation_id[:12]}",
        lineage_path=receipt_path,
        lineage=lineage,
    )


def _candidate_capabilities(
    identifiers: set[str],
) -> dict[str, HiggsfieldCandidate]:
    passive_models = [
        value
        for value in ("kling3_0_turbo", "kling3_0", "seedance_2_0")
        if value in identifiers
    ]
    motion_tool = (
        "kling3_0_motion_control" if "kling3_0_motion_control" in identifiers else None
    )
    veo_tool = "veo3_1" if "veo3_1" in identifiers else None
    return {
        "higgsfield_passive_selfie": HiggsfieldCandidate(
            recipe_id="higgsfield_passive_selfie",
            purpose="animate an approved Soul-derived still without soundtrack",
            actual_tool="higgsfield generate create" if passive_models else None,
            exposed_job_type=",".join(passive_models) if passive_models else None,
            status="supported" if passive_models else "unresolved",
            unavailable_reason=(
                None
                if passive_models
                else "authenticated CLI exposes neither Kling 3.0 nor Seedance 2.0"
            ),
        ),
        "higgsfield_recreate_reel": HiggsfieldCandidate(
            recipe_id="higgsfield_recreate_reel",
            purpose=(
                "recreate broad Reel structure, performance, and camera progression "
                "from one video reference with one approved creator image"
            ),
            actual_tool=(
                "higgsfield generate create seedance_2_0"
                if "seedance_2_0" in identifiers
                else None
            ),
            exposed_job_type=(
                "seedance_2_0" if "seedance_2_0" in identifiers else None
            ),
            status="supported" if "seedance_2_0" in identifiers else "unresolved",
            unavailable_reason=(
                None
                if "seedance_2_0" in identifiers
                else "Seedance Fast is not exposed by the authenticated CLI"
            ),
            limitations=(
                "Experimental until an exact output receives operator WOULD_POST review.",
                "Broad recreation is supported; identical choreography is not promised.",
            ),
        ),
        "higgsfield_motion_copy_animate": HiggsfieldCandidate(
            recipe_id="higgsfield_motion_copy_animate",
            purpose="transfer driving-video motion and expression to an approved still",
            actual_tool=(
                "higgsfield generate create kling3_0_motion_control"
                if motion_tool
                else None
            ),
            exposed_job_type=motion_tool,
            status="experimental" if motion_tool else "unresolved",
            unavailable_reason=(
                None
                if motion_tool
                else "no authenticated motion-transfer job type is exposed"
            ),
            limitations=(
                "The live CLI names this Kling 3.0 Motion Control, not Animate.",
                "A prior output was rejected; each new use remains qualification-only.",
            ),
        ),
        "higgsfield_motion_copy_replace": HiggsfieldCandidate(
            recipe_id="higgsfield_motion_copy_replace",
            purpose="replace a driving-video performer with a trained Soul identity",
            actual_tool=None,
            exposed_job_type=None,
            status="unresolved",
            unavailable_reason="Replace is not exposed by the authenticated CLI or MCP",
        ),
        "higgsfield_talking_speak": HiggsfieldCandidate(
            recipe_id="higgsfield_talking_speak",
            purpose="deliver an exact script with an approved creator voice",
            actual_tool=None,
            exposed_job_type=None,
            status="unresolved",
            unavailable_reason="Speak is not exposed by the authenticated CLI or MCP",
        ),
        "higgsfield_talking_veo": HiggsfieldCandidate(
            recipe_id="higgsfield_talking_veo",
            purpose="vertical Veo direct-to-camera dialogue candidate",
            actual_tool=("higgsfield generate create veo3_1" if veo_tool else None),
            exposed_job_type=veo_tool,
            status="experimental" if veo_tool else "unresolved",
            unavailable_reason=(
                (
                    "Veo 3.1 has no supplied-audio input and is not an exact-voice "
                    "talking recipe"
                )
                if veo_tool
                else "Veo 3.1 is not exposed by the authenticated CLI"
            ),
            limitations=(
                "The exposed Veo contract accepts dialogue text but no supplied voice.",
                "Exact wording and voice identity require operator review.",
            ),
        ),
        "higgsfield_talking_motion_copy": HiggsfieldCandidate(
            recipe_id="higgsfield_talking_motion_copy",
            purpose="retain transferred motion while applying exact supplied speech",
            actual_tool=None,
            exposed_job_type=None,
            status="unresolved",
            unavailable_reason=(
                "no standalone Higgsfield lip-sync tool is exposed by the "
                "authenticated CLI or MCP"
            ),
        ),
    }


def _candidate_command(
    request: HiggsfieldProductionRequest,
    *,
    candidate: HiggsfieldCandidate,
    source_token: str,
    driving: dict[str, Any] | None,
    speech: dict[str, Any] | None,
    prompt: str,
    reference_elements_path: Path | None,
) -> list[str]:
    if request.recipe_id == "higgsfield_passive_selfie":
        model = str(request.model or "").strip()
        available = set(str(candidate.exposed_job_type or "").split(","))
        if (
            model
            not in {
                "kling3_0_turbo",
                "kling3_0",
                "seedance_2_0",
            }
            or model not in available
        ):
            raise ValueError(
                "passive Higgsfield bakeoff requires an exposed --model "
                "kling3_0_turbo, kling3_0, or seedance_2_0"
            )
        if not 4 <= int(request.duration_seconds) <= 15:
            raise ValueError("passive Higgsfield duration must be 4 to 15 seconds")
        command = [
            "higgsfield",
            "generate",
            "create",
            model,
            "--prompt",
            prompt,
            "--start-image",
            source_token,
            "--aspect_ratio",
            "9:16",
            "--duration",
            str(request.duration_seconds),
        ]
        if model == "kling3_0":
            command += ["--mode", "pro", "--sound", "off"]
        elif model == "kling3_0_turbo":
            if len(prompt) > 2500:
                raise ValueError("Kling 3 Turbo prompt must not exceed 2500 characters")
            command += ["--resolution", "720p"]
        else:
            command += [
                "--resolution",
                "720p",
                "--mode",
                "std",
                "--generate_audio",
                "false",
            ]
        return [*command, "--json"]
    if request.recipe_id == "higgsfield_recreate_reel":
        model = str(request.model or "").strip() or "seedance_2_0"
        if model != "seedance_2_0" or candidate.exposed_job_type != model:
            raise HiggsfieldFeatureUnavailable(
                "recreate_reel requires authenticated Seedance Fast; Mini was "
                "rejected for creator identity preservation"
            )
        if driving is None:
            raise ValueError("recreate_reel requires one reference video")
        if reference_elements_path is None:
            raise ValueError("recreate_reel requires the creator reference element")
        if speech is not None:
            raise ValueError(
                "recreate_reel cannot accept creator speech until supplied-voice "
                "preservation is qualified"
            )
        if not 4 <= int(request.duration_seconds) <= 15:
            raise ValueError("recreate_reel duration must be 4 to 15 seconds")
        command = [
            "higgsfield",
            "generate",
            "create",
            model,
            "--prompt",
            prompt,
            "--image-references",
            source_token,
            "--video-references",
            str(driving["path"]),
            "--aspect_ratio",
            "9:16",
            "--duration",
            str(request.duration_seconds),
            "--resolution",
            "480p",
            "--bitrate_mode",
            "high",
            "--generate_audio",
            "false",
        ]
        command += ["--mode", "fast"]
        return [*command, "--json"]
    if request.recipe_id == "higgsfield_motion_copy_animate":
        if driving is None:
            raise ValueError("motion-copy candidate requires a driving video")
        if speech is not None:
            raise ValueError("motion-copy candidate does not accept speech audio")
        return [
            "higgsfield",
            "generate",
            "create",
            "kling3_0_motion_control",
            "--image-references",
            source_token,
            "--video-references",
            str(driving["path"]),
            "--mode",
            "pro",
            "--json",
        ]
    if request.recipe_id == "higgsfield_talking_veo":
        if not str(request.script or "").strip():
            raise ValueError("Veo talking candidate requires an exact script")
        if speech is not None:
            raise ValueError(
                "the exposed Veo contract cannot accept supplied creator audio"
            )
        return [
            "higgsfield",
            "generate",
            "create",
            "veo3_1",
            "--prompt",
            prompt,
            "--start-image",
            source_token,
            "--aspect_ratio",
            "9:16",
            "--duration",
            "8",
            "--quality",
            "high",
            "--variant",
            "veo-3-1-fast",
            "--json",
        ]
    raise HiggsfieldFeatureUnavailable(
        f"{request.recipe_id} is not executable on the authenticated surface"
    )


def _recreation_anchor_approval(
    request: HiggsfieldProductionRequest,
    *,
    source: dict[str, Any],
    driving: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if request.recipe_id != "higgsfield_recreate_reel":
        return None
    approval = request.recreation_anchor_approval
    if not isinstance(approval, dict) or not approval.get("receiptPath"):
        raise PermissionError("recreation_anchor_approval_required_before_quote")
    if driving is None:
        raise ValueError("recreate_reel requires one reference video")
    validated = load_recreation_anchor_approval(
        Path(str(approval["receiptPath"])),
        expected_creator=request.creator,
        expected_soul_id=request.soul_id,
        expected_creator_image_sha256=str(approval.get("creatorImageSha256") or ""),
        expected_reference_video_sha256=str(driving["sha256"]),
        expected_prompt_pack_fingerprint=str(
            approval.get("promptPackFingerprint") or ""
        ),
        expected_anchor_file=Path(str(source.get("path") or "")),
    )
    if (
        source.get("kind") != "local_approved_image"
        or source.get("sha256") != validated["anchorFileSha256"]
        or request.source_approval != validated["approvalFingerprint"]
        or approval.get("receiptSha256") != validated["receiptSha256"]
    ):
        raise PermissionError("recreation_anchor_provider_binding_mismatch")
    return {
        key: validated[key]
        for key in (
            "schema",
            "creator",
            "soulId",
            "anchorGenerationId",
            "anchorModel",
            "anchorPromptPackId",
            "promptPackFingerprint",
            "anchorPromptFingerprint",
            "creatorImageSha256",
            "referenceVideoSha256",
            "selectedCompositionFrameSha256",
            "anchorFilePath",
            "anchorFileSha256",
            "anchorApprovalDecision",
            "approvedBy",
            "approvedAt",
            "approvalFingerprint",
            "receiptPath",
            "receiptSha256",
        )
    }


def _candidate_prompt(
    request: HiggsfieldProductionRequest,
    *,
    reference_element: dict[str, Any] | None,
) -> str:
    if request.recipe_id == "higgsfield_recreate_reel":
        if reference_element is None:
            raise ValueError("recreate_reel requires the creator reference element")
        reference_id = str(reference_element.get("id") or "").strip()
        if not reference_id:
            raise ValueError("creator reference element is missing its id")
        identity_prompt = (
            f"<<<{reference_id}>>> place her in this video. "
            "same motion but my model instead"
        )
        structural_prompt = " ".join(str(request.prompt or "").split())
        placeholder = (
            "<<<approved_creator_reference_element>>> place her in this video. "
            "same motion but my model instead"
        )
        if structural_prompt.startswith(placeholder):
            structural_prompt = structural_prompt[len(placeholder) :].lstrip(". ")
        return (
            f"{identity_prompt}. {structural_prompt}"
            if structural_prompt
            else identity_prompt
        )
    base = " ".join(str(request.prompt or "").split())
    if request.recipe_id == "higgsfield_talking_veo":
        script = " ".join(str(request.script or "").split())
        delivery = ", ".join(
            value
            for value in (
                str(request.tone or "").strip(),
                str(request.pacing or "").strip(),
                str(request.emotion or "").strip(),
            )
            if value
        )
        return (
            "Ordinary vertical direct-to-camera creator vlog in the source setting. "
            "Keep the framing casual and visually continuous. The speaker says "
            f'exactly: "{script}". Delivery: {delivery or "natural and conversational"}.'
        )
    if len(base) < 20:
        raise ValueError("Higgsfield motion prompt must contain at least 20 characters")
    return base


def _quote_command(command: list[str], *, driving: dict[str, Any] | None) -> list[str]:
    if command[:3] != ["higgsfield", "generate", "create"]:
        raise ValueError("unsupported Higgsfield create command")
    if command[3] == "kling3_0_motion_control":
        return []
    return ["higgsfield", "generate", "cost", *command[3:]]


def _quote_parameters(
    command: list[str], *, driving: dict[str, Any] | None
) -> dict[str, Any] | None:
    if command[3] != "kling3_0_motion_control":
        return None
    if driving is None:
        raise ValueError("motion-control quote requires a driving video")
    duration = _probe_video(Path(str(driving["path"])))["durationSeconds"]
    return {
        "jobType": command[3],
        "durationSeconds": duration,
        "mode": command[command.index("--mode") + 1],
    }


def _source_identity(
    request: HiggsfieldProductionRequest,
    *,
    cli: HiggsfieldCliAdapter,
) -> tuple[str, dict[str, Any]]:
    if bool(request.source_image_path) == bool(request.source_generation_id):
        raise ValueError(
            "choose exactly one approved source image or Higgsfield generation"
        )
    if not str(request.source_approval or "").strip():
        raise ValueError("source approval reference is required")
    if request.source_image_path is not None:
        path = _safe_file(request.source_image_path, "source image")
        return str(path), {
            "kind": "local_approved_image",
            "path": str(path),
            "sha256": _sha256_file(path),
            "approval": request.source_approval,
            "generationId": None,
        }
    generation_id = str(request.source_generation_id or "").strip()
    if not str(request.source_generation_approval or "").strip():
        raise ValueError("approved Higgsfield generation requires approval evidence")
    raw = cli.run_json(["higgsfield", "generate", "get", generation_id, "--json"])
    if extract_status(raw) != "completed" or not extract_url(raw):
        raise ValueError("approved Higgsfield source generation is not completed")
    return generation_id, {
        "kind": "approved_higgsfield_generation",
        "path": None,
        "sha256": None,
        "approval": request.source_generation_approval,
        "generationId": generation_id,
        "jobType": _first_string(raw, ("job_type", "job_set_type", "model")),
        "resultUrl": _redacted_result_url(str(extract_url(raw))),
    }


def _selected_soul(capabilities: dict[str, Any], soul_id: str) -> dict[str, Any]:
    matches = [
        row
        for row in capabilities.get("souls") or []
        if isinstance(row, dict)
        and str(row.get("id") or "") == str(soul_id)
        and str(row.get("status") or "").lower() in {"completed", "ready"}
    ]
    if len(matches) != 1:
        raise ValueError("selected Soul ID is not uniquely ready in Higgsfield")
    return dict(matches[0])


def _optional_media_identity(path: Path | None, label: str) -> dict[str, Any] | None:
    if path is None:
        return None
    media = _safe_file(path, label)
    return {"path": str(media), "sha256": _sha256_file(media)}


def _reference_element(
    request: HiggsfieldProductionRequest,
) -> tuple[Path | None, dict[str, Any] | None]:
    if request.recipe_id != "higgsfield_recreate_reel":
        return None, None
    path = request.reference_elements_path or (
        Path.home()
        / ".creator-os"
        / "higgsfield"
        / "reference_elements"
        / f"{request.creator.strip().lower()}.json"
    )
    path = _safe_file(path, "creator reference element")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("creator reference element is invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("creator reference element must contain exactly one item")
    element = payload[0]
    if not isinstance(element, dict):
        raise ValueError("creator reference element must be an object")
    if (
        str(element.get("name") or "").strip().lower()
        != request.creator.strip().lower()
    ):
        raise ValueError(
            "creator reference element does not match the requested creator"
        )
    for key in ("id", "medias", "video_medias"):
        if key not in element:
            raise ValueError(f"creator reference element is missing {key}")
    return path, element


def _probe_video(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe_missing")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,sample_rate,channels:"
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("higgsfield_output_unreadable")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        video = next(row for row in streams if row.get("codec_type") == "video")
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
        raise RuntimeError("higgsfield_output_probe_invalid") from exc
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0 or duration <= 0:
        raise RuntimeError("higgsfield_output_media_metadata_missing")
    ratio = width / height
    if not 0.50 <= ratio <= 0.65:
        raise RuntimeError("higgsfield_output_not_portrait_reel")
    audio = [row for row in streams if row.get("codec_type") == "audio"]
    return {
        "codec": video.get("codec_name"),
        "width": width,
        "height": height,
        "durationSeconds": round(duration, 3),
        "videoStreams": 1,
        "audioStreams": len(audio),
        "audio": [
            {
                "codec": row.get("codec_name"),
                "sampleRate": row.get("sample_rate"),
                "channels": row.get("channels"),
            }
            for row in audio
        ],
    }


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        values = payload.get("items")
        if isinstance(values, list):
            return [row for row in values if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _account_value(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict):
        return None
    if key in payload:
        return payload[key]
    for value in payload.values():
        found = _account_value(value, key)
        if found is not None:
            return found
    return None


def _numeric_account_value(payload: Any, key: str) -> float | None:
    value = _account_value(payload, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _find_number(payload: Any, keys: tuple[str, ...]) -> float | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parsed = float(value)
                if math.isfinite(parsed):
                    return parsed
        for value in payload.values():
            found = _find_number(value, keys)
            if found is not None:
                return found
    return None


def _first_string(payload: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _first_string(value, keys)
            if found:
                return found
    return None


def _positive_credits(value: float | None) -> float:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError("Higgsfield apply requires a finite positive credit cap")
    return float(value)


def _safe_file(path: Path, label: str) -> Path:
    expanded = Path(path).expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is missing: {resolved}")
    return resolved


def _output_path(path: Path) -> Path:
    expanded = Path(path).expanduser()
    if expanded.is_symlink():
        raise ValueError("Higgsfield output must not be a symlink")
    resolved = expanded.resolve()
    if resolved.suffix.lower() != ".mp4":
        raise ValueError("Higgsfield production output must be an MP4")
    return resolved


def _review_root(path: Path) -> Path:
    expanded = Path(path).expanduser()
    if expanded.exists() and expanded.is_symlink():
        raise ValueError("Higgsfield review root must not be a symlink")
    return expanded.resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_review() -> dict[str, Any]:
    return {
        "schema": REVIEW_SCHEMA,
        **{field: None for field in REVIEW_FIELDS},
        "operatorReviewRequired": True,
    }


def _redacted_result_url(value: str) -> str:
    return value.split("?", 1)[0]


def _scrub_provider_payload(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            if any(
                marker in str(key).lower()
                for marker in ("token", "secret", "authorization", "api_key")
            ):
                scrubbed[str(key)] = "[redacted]"
            else:
                scrubbed[str(key)] = _scrub_provider_payload(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_provider_payload(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return _redacted_result_url(value)
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError("higgsfield_receipt_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise PermissionError("higgsfield_receipt_invalid")
    return payload


def _request_from_args(args: argparse.Namespace) -> HiggsfieldProductionRequest:
    return HiggsfieldProductionRequest(
        recipe_id=args.recipe,
        creator=args.creator,
        soul_id=args.soul_id,
        source_approval=args.source_approval,
        output_path=args.output,
        review_root=args.review_root,
        source_image_path=args.source_image,
        source_generation_id=args.source_generation_id,
        source_generation_approval=args.source_generation_approval,
        driving_video_path=args.driving_video,
        speech_audio_path=args.speech_audio,
        prompt=args.prompt,
        script=args.script,
        tone=args.tone,
        pacing=args.pacing,
        emotion=args.emotion,
        model=args.model,
        duration_seconds=args.duration,
        max_credits=args.max_credits,
        seed=args.seed,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or run one authenticated Higgsfield visual-bakeoff candidate; "
            "never schedules or publishes."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--out", type=Path)
    for name in ("plan", "run"):
        command = commands.add_parser(name)
        command.add_argument("--mode", choices=["best_motion"], required=True)
        command.add_argument(
            "--recipe",
            choices=[
                "higgsfield_passive_selfie",
                "higgsfield_motion_copy_animate",
                "higgsfield_motion_copy_replace",
                "higgsfield_talking_speak",
                "higgsfield_talking_veo",
                "higgsfield_talking_motion_copy",
            ],
            required=True,
        )
        command.add_argument("--creator", required=True)
        command.add_argument("--soul-id", required=True)
        command.add_argument("--source-approval", required=True)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--source-image", type=Path)
        source.add_argument("--source-generation-id")
        command.add_argument("--source-generation-approval")
        command.add_argument("--driving-video", type=Path)
        command.add_argument("--speech-audio", type=Path)
        command.add_argument("--prompt")
        command.add_argument("--script")
        command.add_argument("--tone")
        command.add_argument("--pacing")
        command.add_argument("--emotion")
        command.add_argument("--model")
        command.add_argument("--duration", type=int, default=5)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--review-root", type=Path, required=True)
        command.add_argument("--max-credits", type=float)
        command.add_argument("--seed", type=int)
        if name == "run":
            command.add_argument("--confirm-paid", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        capabilities = discover_higgsfield_production_capabilities()
        if args.command == "capabilities":
            if args.out:
                output = args.out.expanduser().resolve()
                atomic_write_text(
                    output,
                    json.dumps(
                        capabilities,
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            payload = capabilities
        else:
            request = _request_from_args(args)
            payload = (
                build_higgsfield_production_plan(request, capabilities=capabilities)
                if args.command == "plan"
                else execute_higgsfield_production(
                    request,
                    capabilities=capabilities,
                    confirm_paid=args.confirm_paid,
                )
            )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
