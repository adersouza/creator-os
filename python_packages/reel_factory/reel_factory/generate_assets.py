#!/usr/bin/env python3
"""Generate and track Higgsfield/Kling source assets from clean prompt JSON.

This module intentionally remains the stable import and CLI surface. Provider
transport, QC, value objects, and lineage builders live in focused sibling
modules; orchestration stays here so existing test seams and callers keep the
same patch points and stdout/exit behavior.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from .anatomy_qc import assess_image_qc, is_image_postable
from .asset_prompt_contract import AssetPromptSet
from .deprecated_generators import guard_deprecated_generator
from .evidence_store import record_asset_generation, validate_generation_soul
from .generation_asset_models import (
    DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO,
    DEFAULT_GRID_IMAGE_ASPECT_RATIO,
    IMAGE_MODEL,
    POLICY_BOUND_WORKER_MODES,
    VIDEO_MODEL,
    AssetGenerationPlan,
    DirectReferenceImagePlan,
    direct_reference_lineage_path,
    direct_reference_prompt,
    lineage_path,
    load_prompt,
    nonnegative_float_arg,
)
from .generation_execution_plan import load_generation_execution_plan
from .generation_lineage import (
    append_failed_generation as _append_failed_generation,
)
from .generation_lineage import (
    authorization_evidence as _authorization_evidence,
)
from .generation_lineage import (
    build_source_lineage,
    failed_generations_path,
    list_failed_generations,
)
from .generation_lineage import (
    direct_reference_lineage as _direct_reference_lineage,
)
from .generation_lineage import (
    failure_raw as _failure_raw,
)
from .generation_lineage import (
    provider_execution_evidence as _provider_execution_evidence,
)
from .generation_lineage import (
    step as _step,
)
from .generation_provider import (
    HiggsfieldCliAdapter,
    HiggsfieldCommandError,
    build_get_cmd,
    build_image_cmd,
    build_model_list_cmd,
    build_soul_list_cmd,
    build_upload_cmd,
    build_video_cmd,
    build_wait_cmd,
    capabilities_path,
    download_result,
    extract_higgsfield_generated_prompt,
    extract_id,
    extract_status,
    extract_url,
    image_identity_flag,
    reference_matched_video_duration,
    resolve_generation_models,
    select_supported_model,
    validate_required_capabilities,
)
from .generation_provider import (
    ensure_required_capabilities as _ensure_required_capabilities,
)
from .generation_provider import (
    probe_higgsfield_capabilities as _probe_higgsfield_capabilities,
)
from .generation_provider import resolve_soul_id as _resolve_soul_id
from .generation_provider import run_json as _provider_run_json
from .generation_provider import run_text as _provider_run_text
from .generation_qc import (
    generated_image_qc as _generated_image_qc,
)
from .generation_qc import (
    generated_image_qc_failure_reason,
    generated_video_qc_failure_reason,
)
from .generation_qc import (
    generated_video_qc as _generated_video_qc,
)
from .generation_qc import (
    sample_video_frames as _sample_video_frames,
)
from .identity_verification import verify_identity
from .provider_spend_authorization import (
    require_campaign_spend_authorization,
    spend_scope_args_for_plan,
)

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

# Compatibility patch points used by focused tests and downstream callers.
# They deliberately remain module globals even though implementation moved.
_run_json = _provider_run_json
_run_text = _provider_run_text
_COMPAT_TRANSPORT_MODULES = (subprocess, urllib.request)
_COMPAT_REEXPORTED_HELPERS = (
    HiggsfieldCliAdapter,
    build_model_list_cmd,
    build_soul_list_cmd,
    build_upload_cmd,
    capabilities_path,
    failed_generations_path,
    image_identity_flag,
    select_supported_model,
    _sample_video_frames,
)


def probe_higgsfield_capabilities(root: Path, *, force: bool = False) -> dict[str, Any]:
    return _probe_higgsfield_capabilities(
        root, force=force, run_json_call=_run_json, run_text_call=_run_text
    )


def ensure_required_capabilities(
    root: Path, image_model: str = IMAGE_MODEL, video_model: str = VIDEO_MODEL
) -> dict[str, Any]:
    return _ensure_required_capabilities(
        root,
        image_model,
        video_model,
        probe_call=probe_higgsfield_capabilities,
    )


def resolve_soul_id(name: str) -> str:
    return _resolve_soul_id(name, run_json_call=_run_json)


def _looks_like_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{24,}", value))


def _soul_id_for_plan(plan: AssetGenerationPlan, *, dry: bool) -> str | None:
    if plan.soul_id:
        return plan.soul_id
    name = plan.soul_name or plan.creator
    if not name:
        return None
    if dry:
        return f"<soul_id:{name}>"
    return resolve_soul_id(name)


def _soul_id_for_direct_plan(
    plan: DirectReferenceImagePlan, *, dry: bool
) -> str | None:
    if plan.soul_id:
        return plan.soul_id
    name = plan.soul_name or plan.creator
    if not name:
        return None
    if dry:
        return f"<soul_id:{name}>"
    return resolve_soul_id(name)


def _six_pack_prompts(prompt: AssetPromptSet) -> list[AssetPromptSet]:
    guard_deprecated_generator("six_pack")
    return [
        AssetPromptSet(
            higgsfieldGridPrompt=(
                f"{prompt.higgsfieldGridPrompt}\n\nRender only outfit variation {idx} from the six listed variations. "
                "Same pose, camera angle, room, framing, vertical composition, outfit family, lighting, and body emphasis."
            ),
            klingMotionPrompt=prompt.klingMotionPrompt,
            notes=prompt.notes,
        )
        for idx in range(1, 7)
    ]


def detect_grid_status(image_path: str | Path | None) -> dict[str, Any]:
    guard_deprecated_generator("grid_status_detection")
    if not image_path:
        return {"status": "missing", "isGrid": False}
    path = Path(image_path)
    try:
        with Image.open(path) as im:
            width, height = im.size
    except Exception as exc:
        return {"status": "unreadable", "isGrid": False, "error": str(exc)}
    ratio = width / height if height else 0.0
    is_grid = 0.85 <= ratio <= 1.20 and width >= 900 and height >= 900
    return {
        "status": "native_2x3_grid" if is_grid else "single_image_or_invalid_grid",
        "isGrid": is_grid,
        "width": width,
        "height": height,
        "ratio": ratio,
    }


def single_image_layout_status(image_path: str | Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "single_image_layout", "isGrid": False}
    if not image_path:
        return payload
    try:
        with Image.open(Path(image_path)) as im:
            width, height = im.size
    except Exception:
        return payload
    payload.update(
        {"width": width, "height": height, "ratio": width / height if height else 0.0}
    )
    return payload


def dry_run(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    soul_id = _soul_id_for_plan(plan, dry=True)
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    image_cmds = [
        build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=plan.image_model,
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        for image_prompt in image_prompts
    ]
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image or "<image_job_id>",
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "commands": image_cmds + [video_cmd],
        "lineage_path": str(lineage_path(plan)),
    }


def dry_run_image_asset(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    soul_id = _soul_id_for_plan(plan, dry=True)
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    commands = [
        build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=plan.image_model,
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        for image_prompt in image_prompts
    ]
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "higgsfield_soul_v2_image_only",
        "commands": commands,
        "lineage_path": str(lineage_path(plan)),
    }


def dry_run_direct_reference_image(
    plan: DirectReferenceImagePlan, *, wait: bool
) -> dict[str, Any]:
    soul_id = _soul_id_for_direct_plan(plan, dry=True)
    prompt = AssetPromptSet(
        higgsfieldGridPrompt=direct_reference_prompt(plan.image_aspect_ratio),
        klingMotionPrompt="",
        notes="Direct Higgsfield reference-image still; no prompt rewriting, appending, or VLM prompt writing.",
    )
    image_cmd = build_image_cmd(
        prompt,
        reference=plan.reference_image,
        soul_id=soul_id,
        model=plan.image_model,
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "higgsfield_direct_reference_image",
        "commands": [image_cmd],
        "lineage_path": str(direct_reference_lineage_path(plan)),
    }


def dry_run_video_asset(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    if not plan.start_image:
        raise ValueError("start_image is required for Kling video dry-run")
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "kling3_0_video_from_accepted_still",
        "commands": [video_cmd],
        "lineage_path": str(lineage_path(plan)),
    }


def _authorize_plan(
    plan: AssetGenerationPlan | DirectReferenceImagePlan, *, mode: str
) -> dict[str, Any]:
    args = spend_scope_args_for_plan(plan, mode=mode)
    return require_campaign_spend_authorization(
        args,
        root=plan.source_dir.parent,
        authorization_file=plan.spend_authorization_file,
    )


def _record_generation_failure(
    plan: AssetGenerationPlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    steps: list[dict[str, Any]],
    raw: dict[str, Any],
    error: HiggsfieldCommandError,
    stage: str,
    capabilities: dict[str, Any] | None = None,
    soul_id: str | None = None,
    soul_name: str | None = None,
    spend_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure = _failure_raw(error)
    raw.setdefault("failure", failure)
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        soul_id=soul_id or plan.soul_id,
        soul_name=soul_name or plan.soul_name,
        local_paths={},
        raw=raw,
    )
    payload["generation"]["status"] = "generation_rejected_or_failed"
    if spend_authorization is not None:
        payload["generation"]["spendAuthorization"] = _authorization_evidence(
            spend_authorization
        )
    payload["generation"]["failure"] = {"stage": stage, "command": error.cmd, **failure}
    payload["generation"]["steps"] = steps + [_step(stage, error.cmd, failure)]
    if capabilities:
        payload["generation"]["capabilities"] = {
            "schema": capabilities.get("schema"),
            "createdAt": capabilities.get("createdAt"),
            "validation": validate_required_capabilities(
                capabilities, plan.image_model, plan.video_model
            ),
        }
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _append_failed_generation(plan, lineage_path=path, lineage=payload)
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or soul_name or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": False,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
        "error": failure,
    }


def generated_image_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    creator: str | None = None,
    identity_provider: Any | None = None,
    vision_call=None,
) -> dict[str, Any]:
    return _generated_image_qc(
        local_paths,
        root=root,
        required=required,
        creator=creator,
        identity_provider=identity_provider,
        vision_call=vision_call,
        assess_image_call=assess_image_qc,
        identity_call=verify_identity,
        is_postable_call=is_image_postable,
    )


def generated_video_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    vision_call=None,
    frame_sampler=None,
) -> dict[str, Any]:
    return _generated_video_qc(
        local_paths,
        root=root,
        required=required,
        vision_call=vision_call,
        frame_sampler=frame_sampler,
        assess_image_call=assess_image_qc,
        is_postable_call=is_image_postable,
    )


def create_assets(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = False
) -> dict[str, Any]:
    spend_authorization = _authorize_plan(plan, mode="create")
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    soul_id = _soul_id_for_plan(plan, dry=False)
    upload_id = None
    image_cmd = build_image_cmd(
        prompt,
        reference=None,
        soul_id=soul_id,
        model=resolved["imageModel"],
        identity_flag=resolved["imageIdentityFlag"],
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    commands.append(image_cmd)
    try:
        raw["image"] = _run_json(image_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="image_create",
            capabilities=capabilities,
            soul_id=soul_id,
            soul_name=plan.soul_name,
            spend_authorization=spend_authorization,
        )
    steps.append(_step("image_create", image_cmd, raw["image"]))
    identity_validation = validate_generation_soul(raw["image"], soul_id)
    image_job_id = extract_id(raw["image"])
    image_url = extract_url(raw["image"])
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image or image_job_id or image_url,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    commands.append(video_cmd)
    try:
        raw["video"] = _run_json(video_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="video_create",
            capabilities=capabilities,
            soul_id=soul_id,
            soul_name=plan.soul_name,
            spend_authorization=spend_authorization,
        )
    steps.append(_step("video_create", video_cmd, raw["video"]))
    video_job_id = extract_id(raw["video"])
    video_status = extract_status(raw["video"])
    video_url = extract_url(raw["video"])
    local_paths: dict[str, str] = {}
    if download and image_url:
        local_paths["image"] = str(
            download_result(image_url, plan.out_dir / f"{plan.stem}_soul_image")
        )
    if download and video_url:
        local_paths["video"] = str(
            download_result(video_url, plan.out_dir / f"{plan.stem}.mp4")
        )
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        upload_id=upload_id,
        soul_id=soul_id,
        soul_name=plan.soul_name,
        image_job_id=image_job_id,
        image_result_url=image_url,
        video_job_id=video_job_id,
        video_result_url=video_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["identityValidation"] = identity_validation
    payload["generation"]["spendAuthorization"] = _authorization_evidence(
        spend_authorization
    )
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    if identity_validation["status"] == "invalid":
        payload["generation"]["status"] = "invalid_identity"
    if video_status and video_status != "completed":
        payload["generation"]["status"] = "video_failed"
        payload["generation"]["error"] = (
            f"video job {video_job_id or ''} returned status {video_status}".strip()
        )
    video_qc = (
        {"status": "skipped", "reason": "video_job_not_completed", "results": []}
        if video_status and video_status != "completed"
        else generated_video_qc(
            local_paths, root=plan.source_dir.parent, required=download
        )
    )
    payload["review"]["generatedVideoQc"] = video_qc
    payload["generation"]["providerExecution"] = _provider_execution_evidence(
        spend_authorization,
        [
            {
                "provider": "higgsfield",
                "operation": "image_create",
                "model": resolved["imageModel"],
                "raw": raw.get("image"),
            },
            {
                "provider": "kling",
                "operation": "video_create",
                "model": resolved["videoModel"],
                "raw": raw.get("video"),
            },
        ],
    )
    if video_qc["status"] == "failed":
        payload["generation"]["status"] = "video_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_video_qc",
            "reason": generated_video_qc_failure_reason(video_qc),
        }
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
        }
    if video_qc["status"] == "failed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"]["reason"],
        }
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def create_image_asset(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = True
) -> dict[str, Any]:
    spend_authorization = _authorize_plan(plan, mode="image")
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    soul_id = _soul_id_for_plan(plan, dry=False)
    upload_id = None
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    image_job_ids: list[str] = []
    image_urls: list[str] = []
    local_paths: dict[str, str] = {}
    raw_images: list[dict[str, Any]] = []
    for idx, image_prompt in enumerate(image_prompts, start=1):
        image_cmd = build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=resolved["imageModel"],
            identity_flag=resolved["imageIdentityFlag"],
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        commands.append(image_cmd)
        try:
            image_raw = _run_json(image_cmd)
        except HiggsfieldCommandError as exc:
            return _record_generation_failure(
                plan,
                prompt=prompt,
                commands=commands,
                steps=steps,
                raw=raw,
                error=exc,
                stage=f"image_create_{idx:02d}"
                if plan.image_mode == "six-pack"
                else "image_create",
                capabilities=capabilities,
                soul_id=soul_id,
                soul_name=plan.soul_name,
                spend_authorization=spend_authorization,
            )
        raw_images.append(image_raw)
        step_name = (
            f"image_create_{idx:02d}"
            if plan.image_mode == "six-pack"
            else "image_create"
        )
        steps.append(_step(step_name, image_cmd, image_raw))
        image_job_id = extract_id(image_raw)
        image_url = extract_url(image_raw)
        if image_job_id:
            image_job_ids.append(image_job_id)
        if image_url:
            image_urls.append(image_url)
        if download and image_url:
            if plan.image_mode == "six-pack":
                image_path = (
                    plan.out_dir / f"{plan.stem}_six_pack" / f"variation_{idx:02d}.png"
                )
                key = f"variation_{idx:02d}"
            else:
                image_path = plan.out_dir / f"{plan.stem}_soul_image.png"
                key = "image"
            local_paths[key] = str(download_result(image_url, image_path))
    raw["image"] = (
        raw_images
        if plan.image_mode == "six-pack"
        else (raw_images[0] if raw_images else {})
    )
    image_job_id = image_job_ids[0] if image_job_ids else None
    image_url = image_urls[0] if image_urls else None
    if plan.image_mode == "six-pack" and local_paths.get("variation_01"):
        local_paths["image"] = local_paths["variation_01"]
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        upload_id=upload_id,
        soul_id=soul_id,
        soul_name=plan.soul_name,
        image_job_id=image_job_id,
        image_result_url=image_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["workflow"] = "higgsfield_soul_v2_image_only"
    payload["generation"]["identityValidation"] = validate_generation_soul(
        raw["image"], soul_id
    )
    payload["generation"]["spendAuthorization"] = _authorization_evidence(
        spend_authorization
    )
    payload["generation"]["imageJobIds"] = image_job_ids
    payload["generation"]["imageResultUrls"] = image_urls
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    payload["generation"]["grid"] = (
        single_image_layout_status(local_paths.get("image"))
        if plan.image_mode != "six-pack"
        else {
            "status": "six_pack_separate_images",
            "isGrid": False,
            "count": len([key for key in local_paths if key.startswith("variation_")]),
        }
    )
    qc = generated_image_qc(
        local_paths,
        root=plan.source_dir.parent,
        required=download,
        creator=plan.creator or plan.soul_name,
    )
    payload["review"]["generatedImageQc"] = qc
    payload["generation"]["providerExecution"] = _provider_execution_evidence(
        spend_authorization,
        [
            {
                "provider": "higgsfield",
                "operation": "image_create",
                "model": resolved["imageModel"],
                "raw": image_raw,
            }
            for image_raw in raw_images
        ],
    )
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": generated_image_qc_failure_reason(qc),
        }
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def create_direct_reference_image_asset(
    plan: DirectReferenceImagePlan,
    *,
    wait: bool = False,
    download: bool = True,
) -> dict[str, Any]:
    spend_authorization = _authorize_plan(plan, mode="reference-image")
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, VIDEO_MODEL
    )
    resolved = resolve_generation_models(capabilities, plan.image_model, VIDEO_MODEL)
    soul_id = _soul_id_for_direct_plan(plan, dry=False)
    prompt = AssetPromptSet(
        higgsfieldGridPrompt=direct_reference_prompt(plan.image_aspect_ratio),
        klingMotionPrompt="",
        notes="Direct Higgsfield reference-image still; no prompt rewriting, appending, or VLM prompt writing.",
    )
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    image_cmd = build_image_cmd(
        prompt,
        reference=plan.reference_image,
        soul_id=soul_id,
        model=resolved["imageModel"],
        identity_flag=resolved["imageIdentityFlag"],
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    commands.append(image_cmd)
    try:
        raw["image"] = _run_json(image_cmd)
    except HiggsfieldCommandError as exc:
        failure = _failure_raw(exc)
        payload = _direct_reference_lineage(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps + [_step("image_create", image_cmd, failure)],
            raw={"image": failure},
            soul_id=soul_id,
            actual_models=resolved,
            status="generation_rejected_or_failed",
            failure={"stage": "image_create", "command": exc.cmd, **failure},
        )
        payload["generation"]["spendAuthorization"] = _authorization_evidence(
            spend_authorization
        )
        path = direct_reference_lineage_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _append_failed_generation(plan, lineage_path=path, lineage=payload)
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": failure,
        }
    steps.append(_step("image_create", image_cmd, raw["image"]))
    image_job_id = extract_id(raw["image"])
    image_url = extract_url(raw["image"])
    captured_prompt = extract_higgsfield_generated_prompt(raw["image"])
    local_paths: dict[str, str] = {}
    if download and image_url:
        aspect_slug = plan.image_aspect_ratio.replace(":", "x").replace("/", "_")
        local_paths["image"] = str(
            download_result(
                image_url,
                plan.out_dir / f"{plan.stem}_direct_reference_{aspect_slug}.png",
            )
        )
    payload = _direct_reference_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        steps=steps,
        raw=raw,
        soul_id=soul_id,
        actual_models=resolved,
        image_job_id=image_job_id,
        image_result_url=image_url,
        local_paths=local_paths,
        captured_prompt=captured_prompt,
        status="image_completed",
    )
    payload["generation"]["spendAuthorization"] = _authorization_evidence(
        spend_authorization
    )
    qc = generated_image_qc(
        local_paths,
        root=plan.source_dir.parent,
        required=download,
        creator=plan.creator or plan.soul_name,
    )
    payload["review"]["generatedImageQc"] = qc
    payload["generation"]["providerExecution"] = _provider_execution_evidence(
        spend_authorization,
        [
            {
                "provider": "higgsfield",
                "operation": "direct_reference_image_create",
                "model": resolved["imageModel"],
                "raw": raw.get("image"),
            }
        ],
    )
    path = direct_reference_lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": generated_image_qc_failure_reason(qc),
        }
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _append_failed_generation(plan, lineage_path=path, lineage=payload)
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "path": str(path), "lineage": payload, "campaign_record": None}


def create_video_asset(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = True
) -> dict[str, Any]:
    spend_authorization = _authorize_plan(plan, mode="video")
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    if not plan.start_image:
        raise ValueError("start_image is required for Kling video creation")
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    commands.append(video_cmd)
    try:
        raw["video"] = _run_json(video_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="video_create",
            capabilities=capabilities,
            soul_id=plan.soul_id,
            soul_name=plan.soul_name,
            spend_authorization=spend_authorization,
        )
    steps.append(_step("video_create", video_cmd, raw["video"]))
    video_job_id = extract_id(raw["video"])
    video_status = extract_status(raw["video"])
    video_url = extract_url(raw["video"])
    local_paths: dict[str, str] = {}
    if download and video_url:
        local_paths["video"] = str(
            download_result(video_url, plan.out_dir / f"{plan.stem}.mp4")
        )
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        soul_id=plan.soul_id,
        soul_name=plan.soul_name,
        video_job_id=video_job_id,
        video_result_url=video_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["workflow"] = "kling3_0_video_from_selected_panel"
    payload["generation"]["spendAuthorization"] = _authorization_evidence(
        spend_authorization
    )
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    if video_status and video_status != "completed":
        payload["generation"]["status"] = "video_failed"
        payload["generation"]["error"] = (
            f"video job {video_job_id or ''} returned status {video_status}".strip()
        )
    video_qc = (
        {"status": "skipped", "reason": "video_job_not_completed", "results": []}
        if video_status and video_status != "completed"
        else generated_video_qc(
            local_paths, root=plan.source_dir.parent, required=download
        )
    )
    payload["review"]["generatedVideoQc"] = video_qc
    if video_qc["status"] == "failed":
        payload["generation"]["status"] = "video_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_video_qc",
            "reason": generated_video_qc_failure_reason(video_qc),
        }
    payload["generation"]["providerExecution"] = _provider_execution_evidence(
        spend_authorization,
        [
            {
                "provider": "kling",
                "operation": "video_create",
                "model": resolved["videoModel"],
                "raw": raw.get("video"),
            }
        ],
    )
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
        }
    if video_qc["status"] == "failed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"]["reason"],
        }
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def read_lineage(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def wait_or_status(lineage: Path, *, wait: bool) -> dict[str, Any]:
    data = read_lineage(lineage)
    generation = data.get("generation") or {}
    job_ids = [generation.get("imageJobId"), generation.get("videoJobId")]
    results = {}
    for job_id in [job_id for job_id in job_ids if job_id]:
        cmd = build_wait_cmd(job_id) if wait else build_get_cmd(job_id)
        results[job_id] = _run_json(cmd)
        data.setdefault("generation", {}).setdefault("steps", []).append(
            _step("generate_wait" if wait else "generate_get", cmd, results[job_id])
        )
    data.setdefault("generation", {})["statusResults"] = results
    atomic_write_text(
        lineage, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "path": str(lineage), "results": results}


def _plan_from_args(args) -> AssetGenerationPlan:
    root = Path(args.root).resolve()
    soul_id = args.soul_id
    soul_name = args.soul_name
    if args.creator and not soul_id and not soul_name:
        soul_name = args.creator
    return AssetGenerationPlan(
        prompt_json=Path(args.prompt_json).expanduser().resolve(),
        stem=args.stem,
        reference=args.reference,
        soul_id=soul_id,
        soul_name=soul_name,
        start_image=args.start_image,
        end_image=args.end_image,
        video_reference=args.video_reference,
        out_dir=(root / args.out_dir).resolve(),
        source_dir=(root / "00_source_videos").resolve(),
        campaign=args.campaign,
        creator=args.creator,
        selected_panel=args.selected_panel,
        image_mode=args.image_mode,
        image_aspect_ratio=args.image_aspect_ratio or DEFAULT_GRID_IMAGE_ASPECT_RATIO,
        image_quality=args.image_quality,
        video_aspect_ratio=args.video_aspect_ratio,
        video_duration=(
            args.video_duration
            if args.video_duration is not None
            else reference_matched_video_duration(
                args.video_reference or args.reference, cap=args.max_video_duration
            )
        ),
        video_mode=None if args.video_mode == "off" else args.video_mode,
        video_sound=args.video_sound,
        image_model=args.image_model,
        video_model=args.video_model,
        cohort_id=args.cohort_id,
        max_credits=args.max_credits,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
        budget_override_ledger_error=args.budget_override_ledger_error,
        spend_authorization_file=(
            Path(args.spend_authorization_file).expanduser().resolve()
            if args.spend_authorization_file
            else None
        ),
    )


def _direct_plan_from_args(args) -> DirectReferenceImagePlan:
    root = Path(args.root).resolve()
    soul_id = args.soul_id
    soul_name = args.soul_name
    if args.creator and not soul_id and not soul_name:
        soul_name = args.creator
    return DirectReferenceImagePlan(
        reference_image=str(Path(args.reference).expanduser().resolve())
        if args.reference
        else "",
        stem=args.stem,
        soul_id=soul_id,
        soul_name=soul_name,
        creator=args.creator,
        campaign=args.campaign,
        out_dir=(root / args.out_dir).resolve(),
        source_dir=(root / "00_source_videos").resolve(),
        image_aspect_ratio=args.image_aspect_ratio
        or DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO,
        image_quality=args.image_quality,
        image_model=args.image_model,
        cohort_id=args.cohort_id,
        max_credits=args.max_credits,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
        budget_override_ledger_error=args.budget_override_ledger_error,
        spend_authorization_file=(
            Path(args.spend_authorization_file).expanduser().resolve()
            if args.spend_authorization_file
            else None
        ),
    )


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "mode",
        choices=[
            "create",
            "dry-run",
            "image",
            "image-dry-run",
            "reference-image",
            "reference-image-dry-run",
            "video",
            "video-dry-run",
            "wait",
            "status",
            "capabilities",
            "failed-generations",
        ],
    )
    ap.add_argument("--root", default=".")
    ap.add_argument("--prompt-json")
    ap.add_argument("--stem")
    ap.add_argument("--reference")
    ap.add_argument("--campaign")
    ap.add_argument("--creator")
    ap.add_argument(
        "--soul-id",
        help="Higgsfield Soul ID custom_reference_id, e.g. Stacey's trained Soul ref",
    )
    ap.add_argument(
        "--soul-name",
        help="Resolve a completed Higgsfield Soul ID by name, e.g. Stacey",
    )
    ap.add_argument("--start-image")
    ap.add_argument("--end-image")
    ap.add_argument(
        "--video-reference",
        help="Reference reel/video for models that accept --video, e.g. Seedance 2.0",
    )
    ap.add_argument("--selected-panel")
    ap.add_argument("--image-mode", choices=["single", "six-pack"], default="single")
    ap.add_argument("--out-dir", default="00_source_videos")
    ap.add_argument("--image-aspect-ratio")
    ap.add_argument("--image-quality", default="2k")
    ap.add_argument("--video-aspect-ratio", default="9:16")
    ap.add_argument("--video-duration", type=int, default=None)
    ap.add_argument("--max-video-duration", type=int, default=8)
    ap.add_argument(
        "--video-mode",
        choices=["std", "pro", "4k", "off"],
        default="pro",
        help="Kling quality mode; use 'off' to omit --mode for compatibility",
    )
    ap.add_argument("--video-sound", default="off")
    ap.add_argument("--image-model", default=IMAGE_MODEL)
    ap.add_argument("--video-model", default=VIDEO_MODEL)
    ap.add_argument(
        "--cohort-id",
        default="creator_os_default",
        help="Credit-ledger cohort used for the hard provider cap.",
    )
    ap.add_argument(
        "--max-credits",
        type=nonnegative_float_arg,
        help="Required per-run native-credit ceiling for every paid call.",
    )
    ap.add_argument("--estimated-cost-usd", type=nonnegative_float_arg)
    ap.add_argument("--allow-unbudgeted-local-test", action="store_true")
    ap.add_argument("--budget-override-ledger-error", action="store_true")
    ap.add_argument(
        "--spend-authorization-file",
        help="Campaign-issued signed authorization required for every paid mode.",
    )
    ap.add_argument(
        "--execution-plan-file",
        help="Campaign-issued generation execution plan for policy-bound worker calls.",
    )
    ap.add_argument("--lineage")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument(
        "--download",
        action="store_true",
        help="download created assets now; generated-video QC runs only on local downloaded video",
    )
    ap.add_argument("--force", action="store_true")
    return ap


def main() -> int:
    ap = _parser()
    args = ap.parse_args()
    if args.mode in POLICY_BOUND_WORKER_MODES and not args.execution_plan_file:
        ap.error(
            f"--execution-plan-file is required for canonical {args.mode} worker actions"
        )
    execution_plan = None
    if args.execution_plan_file:
        execution_plan = load_generation_execution_plan(
            args.execution_plan_file, worker_action=args.mode
        )
    if args.mode == "capabilities":
        result = probe_higgsfield_capabilities(
            Path(args.root).resolve(), force=args.force
        )
    elif args.mode == "failed-generations":
        result = list_failed_generations(Path(args.root).resolve())
    elif args.mode in {"reference-image", "reference-image-dry-run"}:
        if not args.reference or not args.stem:
            raise SystemExit("--reference and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _direct_plan_from_args(args)
        result = (
            dry_run_direct_reference_image(plan, wait=args.wait)
            if args.mode == "reference-image-dry-run"
            else create_direct_reference_image_asset(
                plan, wait=args.wait, download=args.download
            )
        )
    elif args.mode in {"create", "dry-run"}:
        if not args.prompt_json or not args.stem:
            raise SystemExit("--prompt-json and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _plan_from_args(args)
        result = (
            dry_run(plan, wait=args.wait)
            if args.mode == "dry-run"
            else create_assets(plan, wait=args.wait, download=args.download)
        )
    elif args.mode in {"image", "image-dry-run"}:
        if not args.prompt_json or not args.stem:
            raise SystemExit("--prompt-json and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _plan_from_args(args)
        result = (
            dry_run_image_asset(plan, wait=args.wait)
            if args.mode == "image-dry-run"
            else create_image_asset(plan, wait=args.wait, download=args.download)
        )
    elif args.mode in {"video", "video-dry-run"}:
        if not args.prompt_json or not args.stem or not args.start_image:
            raise SystemExit("--prompt-json, --stem, and --start-image are required")
        plan = _plan_from_args(args)
        result = (
            dry_run_video_asset(plan, wait=args.wait)
            if args.mode == "video-dry-run"
            else create_video_asset(plan, wait=args.wait, download=args.download)
        )
    else:
        if not args.lineage:
            raise SystemExit("--lineage is required")
        result = wait_or_status(Path(args.lineage), wait=args.mode == "wait")
    if execution_plan is not None:
        result["executionPlan"] = execution_plan
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
