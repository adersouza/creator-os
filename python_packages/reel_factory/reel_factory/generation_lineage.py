"""Lineage and audit-evidence builders for Reel Factory generation workers."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_generation_worker_lineage

from .asset_prompt_contract import AssetPromptSet
from .feature_extract import extract_features
from .generation_asset_models import (
    AssetGenerationPlan,
    DirectReferenceImagePlan,
)
from .generation_provider import (
    HiggsfieldCommandError,
    extract_id,
    generation_completed,
    result_credits,
)


def step(
    name: str, cmd: list[str], response: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"name": name, "command": cmd, "raw": response or {}}


def failure_raw(exc: HiggsfieldCommandError) -> dict[str, Any]:
    return {
        "error": "higgsfield_command_failed",
        "failureKind": exc.failure_kind,
        "message": str(exc),
        "returnCode": exc.returncode,
        "stdoutTail": exc.stdout[-4000:],
        "stderrTail": exc.stderr[-4000:],
    }


def provider_execution_evidence(
    authorization: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return derived worker evidence; Campaign owns the authoritative ledger."""
    events = []
    for record in records:
        raw = record.get("raw")
        if not isinstance(raw, dict) or not generation_completed(raw):
            continue
        job_id = extract_id(raw)
        if not job_id:
            continue
        events.append(
            {
                "provider": str(record["provider"]),
                "operation": str(record["operation"]),
                "model": str(record["model"]),
                "jobId": job_id,
                "actualCredits": result_credits(raw),
            }
        )
    return {
        "schema": "reel_factory.provider_execution_evidence.v1",
        "authorizationId": authorization["authorizationId"],
        "reservationId": authorization["reservationId"],
        "requestFingerprint": authorization["scope"]["requestFingerprint"],
        "events": events,
    }


def authorization_evidence(authorization: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": authorization["schema"],
        "authorizationId": authorization["authorizationId"],
        "reservationId": authorization["reservationId"],
        "issuer": authorization["issuer"],
        "scope": authorization["scope"],
        "providerQuote": authorization["providerQuote"],
    }


def direct_reference_lineage(
    plan: DirectReferenceImagePlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    steps: list[dict[str, Any]],
    raw: dict[str, Any],
    soul_id: str | None,
    actual_models: dict[str, str],
    status: str,
    image_job_id: str | None = None,
    image_result_url: str | None = None,
    local_paths: dict[str, str] | None = None,
    captured_prompt: str | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = extract_features(captured_prompt or prompt.higgsfieldGridPrompt)
    creator = (plan.creator or plan.soul_name or "").strip().lower()
    if creator:
        features["creator"] = creator
    return {
        "schema": "reel_factory.direct_reference_image_lineage.v1",
        "createdAt": int(time.time()),
        "source": {
            "stem": plan.stem,
            "referenceImage": plan.reference_image,
            "soulId": soul_id or plan.soul_id,
            "soulName": plan.soul_name,
            "creator": plan.creator,
        },
        "features": features,
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": "higgsfield_direct_reference_image",
            "status": status,
            "models": {"image": actual_models.get("imageModel", plan.image_model)},
            "requestedModels": {"image": plan.image_model},
            "imageIdentityFlag": actual_models.get("imageIdentityFlag"),
            "imageJobId": image_job_id,
            "imageResultUrl": image_result_url,
            "prompts": asdict(prompt),
            "capturedHiggsfieldPrompt": captured_prompt,
            "promptPolicy": {
                "grokUsed": False,
                "qwenUsed": False,
                "ollamaUsed": False,
                "florenceUsed": False,
                "visualSchemaUsed": False,
                "promptAppendUsed": False,
                "capturedPromptReused": False,
                "policy": "reference_image_only",
            },
            "params": {
                "imageAspectRatio": plan.image_aspect_ratio,
                "imageQuality": plan.image_quality,
            },
            "commands": commands,
            "steps": steps,
            "raw": raw,
            "failure": failure,
        },
        "assets": {"localPaths": local_paths or {}},
        "review": {"humanReviewRequired": True},
    }


def build_source_lineage(
    plan: AssetGenerationPlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    upload_id: str | None = None,
    soul_id: str | None = None,
    soul_name: str | None = None,
    image_job_id: str | None = None,
    image_result_url: str | None = None,
    video_job_id: str | None = None,
    video_result_url: str | None = None,
    local_paths: dict[str, str] | None = None,
    raw: dict[str, Any] | None = None,
    actual_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    actual_models = actual_models or {}
    prompt_text = "\n".join(
        value
        for value in (
            prompt.higgsfieldGridPrompt,
            prompt.klingMotionPrompt,
            prompt.notes,
        )
        if value
    )
    features = extract_features(prompt_text)
    creator = (plan.creator or plan.soul_name or "").strip().lower()
    if creator:
        features["creator"] = creator
    lineage = {
        "schema": "reel_factory.generation_worker_lineage.v1",
        "createdAt": int(time.time()),
        "source": {
            "stem": plan.stem,
            "promptSourcePath": str(plan.prompt_json),
            "reference": plan.reference,
            "soulId": soul_id or plan.soul_id,
            "soulName": soul_name or plan.soul_name,
            "selectedPanel": plan.selected_panel,
            "startImage": plan.start_image,
            "endImage": plan.end_image,
            "videoReference": plan.video_reference,
        },
        "features": features,
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": "higgsfield_soul_v2_to_kling3_0",
            "campaign": plan.campaign,
            "creator": plan.creator,
            "models": {
                "image": actual_models.get("imageModel", plan.image_model),
                "video": actual_models.get("videoModel", plan.video_model),
            },
            "requestedModels": {
                "image": plan.image_model,
                "video": plan.video_model,
            },
            "imageIdentityFlag": actual_models.get("imageIdentityFlag"),
            "uploadId": upload_id,
            "soulId": soul_id or plan.soul_id,
            "soulName": soul_name or plan.soul_name,
            "imageJobId": image_job_id,
            "imageResultUrl": image_result_url,
            "videoJobId": video_job_id,
            "videoResultUrl": video_result_url,
            "prompts": asdict(prompt),
            "params": {
                "imageAspectRatio": plan.image_aspect_ratio,
                "imageQuality": plan.image_quality,
                "videoAspectRatio": plan.video_aspect_ratio,
                "videoDuration": plan.video_duration,
                "videoMode": plan.video_mode,
                "videoSound": plan.video_sound,
            },
            "commands": commands,
            "raw": raw or {},
        },
        "assets": {
            "localPaths": local_paths or {},
        },
        "review": {
            "humanReviewRequired": True,
        },
    }
    validate_generation_worker_lineage(lineage)
    return lineage


def failed_generations_path(root: Path | str) -> Path:
    return Path(root).resolve() / "failed_generations.jsonl"


def append_failed_generation(
    plan: AssetGenerationPlan | DirectReferenceImagePlan,
    *,
    lineage_path: Path,
    lineage: dict[str, Any],
) -> None:
    generation = lineage.get("generation") if isinstance(lineage, dict) else {}
    failure = generation.get("failure") if isinstance(generation, dict) else {}
    record = {
        "schema": "reel_factory.failed_generation.v1",
        "createdAt": int(time.time()),
        "stem": plan.stem,
        "creator": getattr(plan, "creator", None),
        "campaign": getattr(plan, "campaign", None),
        "status": generation.get("status") if isinstance(generation, dict) else None,
        "failure": failure if isinstance(failure, dict) else {},
        "lineagePath": str(lineage_path),
    }
    path = failed_generations_path(plan.source_dir.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_failed_generations(root: Path | str, *, limit: int = 100) -> dict[str, Any]:
    path = failed_generations_path(root)
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows = rows[-max(1, limit) :]
    return {
        "schema": "reel_factory.failed_generations.v1",
        "path": str(path),
        "count": len(rows),
        "items": rows,
    }
