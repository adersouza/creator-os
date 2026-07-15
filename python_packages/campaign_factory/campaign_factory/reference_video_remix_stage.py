from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_guards import require_global_write_allowed
from reel_factory.reference_video_remix import (
    build_reference_video_remix_plan,
    gemini_motion_analysis_instruction,
)
from scenedetect import ContentDetector, detect

from .core import new_id, sanitize_for_storage, sha256_file
from .generation_execution_plan import (
    GenerationExecutionPlan,
    authorize_paid_generation,
    require_generation_execution_mode,
)
from .persistence import utc_now
from .static_mp4_stage import run_static_mp4_stage

REQUIRED_CONTENTFORGE_CHECKS = (
    "source_master_distinctness",
    "sibling_distinctness",
    "identity_verification",
    "endpoint_continuity",
    "readability",
    "safe_zone",
    "watchability",
    "visual_qc",
)
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
_SCENE_DETECT_THRESHOLD = 27.0
_SCENE_DETECT_MIN_LENGTH_FRAMES = 15
_T = TypeVar("_T")


class ReferenceVideoRemixSeams(Protocol):
    """External paid/model seams used by the Campaign-owned workflow."""

    def analyze_motion(
        self, reference_video: Path, instruction: str
    ) -> dict[str, Any]: ...

    def quote(
        self,
        *,
        operation: str,
        provider: str,
        model: str,
        soul_id: str,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]: ...

    def reserve(
        self, quote: dict[str, Any], max_credits: float, idempotency_key: str
    ) -> dict[str, Any]: ...

    def consume(self, reservation_id: str) -> bool: ...

    def cancel(self, reservation_id: str) -> bool: ...

    def generate_soul_endpoint(
        self,
        *,
        role: str,
        source_frame: Path,
        description: str,
        creator: str,
        soul_id: str,
        workspace: Path,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]: ...

    def verify_endpoint_approval(
        self,
        *,
        approval_id: str,
        role: str,
        endpoint_path: Path,
        endpoint_sha256: str,
    ) -> dict[str, Any]: ...

    def animate(
        self,
        *,
        provider: str,
        model: str,
        command: list[str],
        workspace: Path,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]: ...

    def contentforge_qc(
        self,
        *,
        video_path: Path,
        reference_video: Path,
        first_endpoint: Path,
        last_endpoint: Path,
        required_checks: tuple[str, ...],
        workspace: Path,
    ) -> dict[str, Any]: ...


class JsonCommandReferenceVideoRemixSeams:
    """Environment-only adapter for the operator-configured phase driver."""

    def __init__(self, command: str | None = None) -> None:
        command = command or os.environ.get("CREATOR_OS_REFERENCE_REMIX_DRIVER")
        if not command:
            raise ValueError(
                "CREATOR_OS_REFERENCE_REMIX_DRIVER is required for a live reference-video remix"
            )
        self.command = shlex.split(command)

    def _call(self, phase: str, **payload: Any) -> dict[str, Any]:
        completed = subprocess.run(
            self.command,
            input=json.dumps({"phase": phase, **payload}, sort_keys=True),
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"reference-video remix driver phase failed: {phase}")
        try:
            value = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"reference-video remix driver returned invalid JSON: {phase}"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(
                f"reference-video remix driver returned non-object JSON: {phase}"
            )
        return value

    def analyze_motion(self, reference_video: Path, instruction: str) -> dict[str, Any]:
        return self._call(
            "gemini_motion_analysis",
            referenceVideo=str(reference_video),
            instruction=instruction,
        )

    def quote(
        self,
        *,
        operation: str,
        provider: str,
        model: str,
        soul_id: str,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            "quote",
            operation=operation,
            provider=provider,
            model=model,
            soulId=soul_id,
            executionPlan=execution_plan,
        )

    def reserve(
        self, quote: dict[str, Any], max_credits: float, idempotency_key: str
    ) -> dict[str, Any]:
        return self._call(
            "reserve",
            quote=_redacted_quote(quote),
            maxCredits=max_credits,
            idempotencyKey=idempotency_key,
        )

    def consume(self, reservation_id: str) -> bool:
        return bool(self._call("consume", reservationId=reservation_id).get("ok"))

    def cancel(self, reservation_id: str) -> bool:
        return bool(self._call("cancel", reservationId=reservation_id).get("ok"))

    def generate_soul_endpoint(
        self,
        *,
        role: str,
        source_frame: Path,
        description: str,
        creator: str,
        soul_id: str,
        workspace: Path,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            "generate_soul_endpoint",
            role=role,
            sourceFrame=str(source_frame),
            description=description,
            creator=creator,
            soulId=soul_id,
            workspace=str(workspace),
            executionPlan=execution_plan,
        )

    def verify_endpoint_approval(
        self,
        *,
        approval_id: str,
        role: str,
        endpoint_path: Path,
        endpoint_sha256: str,
    ) -> dict[str, Any]:
        return self._call(
            "verify_endpoint_approval",
            approvalId=approval_id,
            role=role,
            endpointPath=str(endpoint_path),
            endpointSha256=endpoint_sha256,
        )

    def animate(
        self,
        *,
        provider: str,
        model: str,
        command: list[str],
        workspace: Path,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            "animate",
            provider=provider,
            model=model,
            command=command,
            workspace=str(workspace),
            executionPlan=execution_plan,
        )

    def contentforge_qc(
        self,
        *,
        video_path: Path,
        reference_video: Path,
        first_endpoint: Path,
        last_endpoint: Path,
        required_checks: tuple[str, ...],
        workspace: Path,
    ) -> dict[str, Any]:
        return self._call(
            "contentforge_qc",
            videoPath=str(video_path),
            referenceVideo=str(reference_video),
            firstEndpoint=str(first_endpoint),
            lastEndpoint=str(last_endpoint),
            requiredChecks=list(required_checks),
            workspace=str(workspace),
        )


def run_reference_video_remix_stage(
    factory: Any,
    *,
    campaign_slug: str,
    reference_video_path: Path,
    creator: str,
    soul_id: str,
    workspace: Path,
    operator_selected: bool,
    rights_confirmed: bool,
    first_frame_approval_id: str,
    last_frame_approval_id: str,
    execution_plan: GenerationExecutionPlan,
    paid_confirmation: bool,
    max_credits: float,
    preferred_provider: str = "auto",
    available_providers: tuple[str, ...] | list[str] = ("seedance", "kling"),
    seams: ReferenceVideoRemixSeams | None = None,
) -> dict[str, Any]:
    """Execute the paid structural remix through fail-closed injected seams."""
    execution_plan_contract = require_generation_execution_mode(
        execution_plan, "reference_video_remix"
    )
    authorize_paid_generation(
        execution_plan,
        expected_mode="reference_video_remix",
        media_kind="image",
        required_approvals=("reference_rights", "paid_generation"),
    )
    authorize_paid_generation(
        execution_plan,
        expected_mode="reference_video_remix",
        media_kind="video",
        required_approvals=(
            "reference_rights",
            "both_endpoint_frames",
            "paid_generation",
            "contentforge_approval",
            "final_human_review",
        ),
    )
    if not paid_confirmation:
        raise ValueError("explicit paid confirmation is required")
    cap = _positive_finite(max_credits, "max_credits")
    creator = _required_text(creator, "creator")
    soul_id = _required_text(soul_id, "soul_id")
    first_frame_approval_id = _required_text(
        first_frame_approval_id, "first_frame_approval_id"
    )
    last_frame_approval_id = _required_text(
        last_frame_approval_id, "last_frame_approval_id"
    )
    if not operator_selected:
        raise PermissionError("reference video must be explicitly operator-selected")
    if not rights_confirmed:
        raise PermissionError("reference video usage rights must be confirmed")
    require_global_write_allowed("paid reference-video remix")
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace not found: {workspace}")
    reference_video = _reference_video(reference_video_path)
    # This preflight is deliberately before Campaign rows, directories, or any
    # paid/provider seam. A multi-shot source is not eligible for the one-shot
    # structural-remix contract and must fail without side effects.
    probe = probe_reference_video(reference_video)
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
    remix_dir = (
        dirs["reel_inputs"]
        / "reference_video_remix"
        / sha256_file(reference_video)[:16]
    )
    remix_dir.mkdir(parents=True, exist_ok=True)
    seams = seams or JsonCommandReferenceVideoRemixSeams()
    pipeline_job = factory.domains.events.create_pipeline_job(
        "reference_video_remix",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "referenceVideoPath": str(reference_video),
            "creator": creator,
            "soulId": soul_id,
            "workspace": str(workspace),
            "operatorSelected": True,
            "rightsConfirmed": True,
            "paidConfirmation": True,
            "maxCredits": cap,
            "preferredProvider": preferred_provider,
            "availableProviders": list(available_providers),
            "executionPlan": execution_plan_contract,
            "publishingAllowed": False,
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        source_first, source_last = extract_reference_endpoints(
            reference_video, remix_dir, probe=probe
        )
        reference_id = "reference_video_" + sha256_file(reference_video)[:16]
        analysis = seams.analyze_motion(
            reference_video, gemini_motion_analysis_instruction(reference_id)
        )
        _validate_analysis_matches_source(analysis, probe, reference_id)
        ledger = _SpendLedger(max_credits=cap)

        first_generation, first_spend = _paid_call(
            seams,
            ledger=ledger,
            operation="soul_endpoint_first",
            provider="higgsfield",
            model="soul_2",
            soul_id=soul_id,
            idempotency_key=f"{reference_id}:endpoint:first",
            execution_plan=execution_plan,
            media_kind="image",
            required_approvals=("reference_rights", "paid_generation"),
            call=lambda: seams.generate_soul_endpoint(
                role="first",
                source_frame=source_first,
                description=str(analysis["structure"]["firstFrameDescription"]),
                creator=creator,
                soul_id=soul_id,
                workspace=remix_dir,
                execution_plan=execution_plan_contract,
            ),
        )
        last_generation, last_spend = _paid_call(
            seams,
            ledger=ledger,
            operation="soul_endpoint_last",
            provider="higgsfield",
            model="soul_2",
            soul_id=soul_id,
            idempotency_key=f"{reference_id}:endpoint:last",
            execution_plan=execution_plan,
            media_kind="image",
            required_approvals=("reference_rights", "paid_generation"),
            call=lambda: seams.generate_soul_endpoint(
                role="last",
                source_frame=source_last,
                description=str(analysis["structure"]["lastFrameDescription"]),
                creator=creator,
                soul_id=soul_id,
                workspace=remix_dir,
                execution_plan=execution_plan_contract,
            ),
        )
        first_endpoint = _endpoint_path(first_generation, "first")
        last_endpoint = _endpoint_path(last_generation, "last")
        _validate_distinct_endpoints(
            source_first=source_first,
            source_last=source_last,
            first_endpoint=first_endpoint,
            last_endpoint=last_endpoint,
        )
        first_approval = _verified_approval(
            seams,
            approval_id=first_frame_approval_id,
            role="first",
            endpoint_path=first_endpoint,
        )
        last_approval = _verified_approval(
            seams,
            approval_id=last_frame_approval_id,
            role="last",
            endpoint_path=last_endpoint,
        )

        static_fallback = run_static_mp4_stage(
            factory,
            campaign_slug=campaign_slug,
            still_path=first_endpoint,
            dry_run=False,
            apply=True,
        )
        _validate_static_fallback(static_fallback)
        plan = build_reference_video_remix_plan(
            reference_video_path=reference_video,
            source_first_frame_path=source_first,
            source_last_frame_path=source_last,
            analysis=analysis,
            creator=creator,
            soul_id=soul_id,
            operator_selected=True,
            rights_confirmed=True,
            preferred_provider=preferred_provider,
            available_providers=available_providers,
            accepted_first_frame_path=first_endpoint,
            accepted_last_frame_path=last_endpoint,
            first_frame_approval_id=first_frame_approval_id,
            last_frame_approval_id=last_frame_approval_id,
            budget_cap_credits=cap,
        )
        animation = plan["animation"]
        command = animation.get("command")
        if not isinstance(command, list) or not command:
            raise RuntimeError(
                "approved structural remix did not produce a provider command"
            )
        provider = str(animation["provider"])
        model = str(animation["model"])
        animation_result, animation_spend = _paid_call(
            seams,
            ledger=ledger,
            operation="reference_video_animation",
            provider=provider,
            model=model,
            soul_id=soul_id,
            idempotency_key=f"{plan['planId']}:animation",
            execution_plan=execution_plan,
            media_kind="video",
            required_approvals=(
                "reference_rights",
                "both_endpoint_frames",
                "paid_generation",
                "contentforge_approval",
                "final_human_review",
            ),
            call=lambda: seams.animate(
                provider=provider,
                model=model,
                command=[str(value) for value in command],
                workspace=remix_dir,
                execution_plan=execution_plan_contract,
            ),
        )
        final_video = _final_video_path(
            animation_result, provider=provider, model=model
        )
        qc = seams.contentforge_qc(
            video_path=final_video,
            reference_video=reference_video,
            first_endpoint=first_endpoint,
            last_endpoint=last_endpoint,
            required_checks=REQUIRED_CONTENTFORGE_CHECKS,
            workspace=remix_dir,
        )
        _validate_contentforge_qc(qc)
        lineage = _build_lineage(
            plan=plan,
            analysis=analysis,
            probe=probe,
            reference_video=reference_video,
            source_first=source_first,
            source_last=source_last,
            first_endpoint=first_endpoint,
            last_endpoint=last_endpoint,
            first_generation=first_generation,
            last_generation=last_generation,
            first_approval=first_approval,
            last_approval=last_approval,
            static_fallback=static_fallback,
            final_video=final_video,
            animation_result=animation_result,
            qc=qc,
            spend=[first_spend, last_spend, animation_spend],
            max_credits=cap,
            credits_spent=ledger.spent,
            execution_plan=execution_plan_contract,
        )
        lineage_path = remix_dir / f"{plan['planId']}.generated_asset_lineage.json"
        atomic_write_text(
            lineage_path,
            json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        registered_asset = _register_remix_asset(
            factory,
            campaign=campaign,
            video_path=final_video,
            lineage=lineage,
            lineage_path=lineage_path,
        )
        result = {
            "schema": "campaign_factory.reference_video_remix_stage_run.v1",
            "campaign": campaign_slug,
            "plan": plan,
            "analysis": analysis,
            "staticFallback": static_fallback,
            "registeredAsset": registered_asset,
            "lineagePath": str(lineage_path),
            "creditsSpent": ledger.spent,
            "maxCredits": cap,
            "executionPlan": execution_plan_contract,
            "handoffStatus": "blocked_pending_final_human_review",
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.domains.events.finish_pipeline_job(
            pipeline_job["id"], sanitize_for_storage(result)
        )
        return result
    except Exception as exc:
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def plan_reference_video_remix_stage(
    *,
    reference_video_path: Path,
    creator: str,
    soul_id: str,
    workspace: Path,
    operator_selected: bool,
    rights_confirmed: bool,
    max_credits: float | None,
    execution_plan: GenerationExecutionPlan,
) -> dict[str, Any]:
    """Return a provider-free preflight plan without extracting or generating media."""
    execution_plan_contract = require_generation_execution_mode(
        execution_plan, "reference_video_remix"
    )
    reference_video = _reference_video(reference_video_path)
    probe = probe_reference_video(reference_video)
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace not found: {workspace}")
    return {
        "schema": "campaign_factory.reference_video_remix_preflight.v1",
        "status": "planned",
        "referenceVideoPath": str(reference_video),
        "referenceVideoSha256": sha256_file(reference_video),
        "source": probe,
        "creator": _required_text(creator, "creator"),
        "soulId": _required_text(soul_id, "soul_id"),
        "workspace": str(workspace),
        "operatorSelected": bool(operator_selected),
        "rightsConfirmed": bool(rights_confirmed),
        "maxCredits": (
            _positive_finite(max_credits, "max_credits")
            if max_credits is not None
            else None
        ),
        "executionPlan": execution_plan_contract,
        "providerCalls": 0,
        "paidGenerationAuthorized": False,
        "requiredBeforeApply": [
            "operator_selection",
            "rights_confirmation",
            "both_endpoint_approval_ids",
            "explicit_paid_confirmation",
            "finite_credit_cap",
            "configured_reference_remix_driver",
        ],
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def probe_reference_video(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-1000:] or "ffprobe failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid JSON") from exc
    streams = [
        stream
        for stream in payload.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    if len(streams) != 1:
        raise ValueError("reference video must contain exactly one video stream")
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration = float(
        stream.get("duration") or (payload.get("format") or {}).get("duration") or 0
    )
    if duration < 5 or duration > 12:
        raise ValueError("reference video duration must be between 5 and 12 seconds")
    if width <= 0 or height <= 0 or abs((width / height) - (9 / 16)) > 0.01:
        raise ValueError("reference video must be 9:16")
    scene_detection = detect_reference_video_scenes(path)
    if scene_detection["shotCount"] != 1:
        raise ValueError(
            "reference video must be one continuous shot; "
            f"PySceneDetect found {scene_detection['shotCount']} shots"
        )
    return {
        "durationSeconds": duration,
        "width": width,
        "height": height,
        "aspectRatio": "9:16",
        "videoStreamCount": 1,
        "shotCount": 1,
        "hasCuts": False,
        "sceneDetection": scene_detection,
    }


def detect_reference_video_scenes(path: Path) -> dict[str, Any]:
    """Return deterministic cut evidence for a short local reference video.

    No output files are written. Decoder or detector failures are fatal because
    proceeding would move a potentially multi-shot input into paid generation.
    """
    try:
        scenes = detect(
            str(path),
            ContentDetector(
                threshold=_SCENE_DETECT_THRESHOLD,
                min_scene_len=_SCENE_DETECT_MIN_LENGTH_FRAMES,
            ),
            show_progress=False,
            start_in_scene=True,
        )
    except Exception as exc:
        raise RuntimeError("reference video scene detection failed closed") from exc
    if not scenes:
        raise RuntimeError("reference video scene detection returned no scenes")
    boundaries = [
        {
            "startSeconds": round(float(start.seconds), 6),
            "endSeconds": round(float(end.seconds), 6),
        }
        for start, end in scenes
    ]
    return {
        "detector": "pyscenedetect_content_detector",
        "threshold": _SCENE_DETECT_THRESHOLD,
        "minSceneLengthFrames": _SCENE_DETECT_MIN_LENGTH_FRAMES,
        "shotCount": len(boundaries),
        "hasCuts": len(boundaries) > 1,
        "scenes": boundaries,
    }


def extract_reference_endpoints(
    reference_video: Path, output_dir: Path, *, probe: dict[str, Any]
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_hash = sha256_file(reference_video)[:16]
    first = output_dir / f"{video_hash}.source_first.png"
    last = output_dir / f"{video_hash}.source_last.png"
    commands = (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(reference_video),
            "-vf",
            "select=eq(n\\,0)",
            "-frames:v",
            "1",
            str(first),
        ],
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(reference_video),
            "-vf",
            "reverse",
            "-frames:v",
            "1",
            str(last),
        ],
    )
    for command in commands:
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False, timeout=120
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr[-1000:] or "ffmpeg frame extraction failed"
            )
    if not first.is_file() or not last.is_file():
        raise RuntimeError(
            "deterministic endpoint extraction did not produce both frames"
        )
    if sha256_file(first) == sha256_file(last):
        raise ValueError(
            "reference video endpoints are identical; motion is not usable"
        )
    if probe.get("aspectRatio") != "9:16":
        raise ValueError("reference probe changed during extraction")
    return first, last


class _SpendLedger:
    def __init__(self, *, max_credits: float) -> None:
        self.max_credits = max_credits
        self.spent = 0.0


def _paid_call(
    seams: ReferenceVideoRemixSeams,
    *,
    ledger: _SpendLedger,
    operation: str,
    provider: str,
    model: str,
    soul_id: str,
    idempotency_key: str,
    execution_plan: GenerationExecutionPlan,
    media_kind: Literal["image", "video"],
    required_approvals: tuple[str, ...],
    call: Callable[[], _T],
) -> tuple[_T, dict[str, Any]]:
    execution_plan_contract = authorize_paid_generation(
        execution_plan,
        expected_mode="reference_video_remix",
        media_kind=media_kind,
        required_approvals=required_approvals,
        provider=provider,
        model=model,
    )
    quote = seams.quote(
        operation=operation,
        provider=provider,
        model=model,
        soul_id=soul_id,
        execution_plan=execution_plan_contract,
    )
    amount = _quote_amount(quote, provider=provider, model=model)
    remaining = round(ledger.max_credits - ledger.spent, 6)
    if amount > remaining:
        raise RuntimeError("provider quote exceeds remaining credit cap")
    reservation = seams.reserve(quote, remaining, idempotency_key)
    reservation_id = _reservation_id(reservation)
    consumed = False
    try:
        if not reservation.get("allowed"):
            raise RuntimeError(
                str(reservation.get("blockingReason") or "credit reservation blocked")
            )
        if not seams.consume(reservation_id):
            raise RuntimeError("failed to atomically consume provider reservation")
        consumed = True
        ledger.spent = round(ledger.spent + amount, 6)
        result = call()
        return result, {
            "operation": operation,
            "quote": _redacted_quote(quote),
            "reservation": {
                "id": reservation_id,
                "status": "consumed",
                "idempotencyKey": idempotency_key,
            },
        }
    except Exception:
        if not consumed:
            seams.cancel(reservation_id)
        raise


def _validate_analysis_matches_source(
    analysis: dict[str, Any], probe: dict[str, Any], reference_id: str
) -> None:
    if analysis.get("referenceId") != reference_id:
        raise ValueError("Gemini analysis reference id does not match the source")
    if analysis.get("provider") != "gemini" or analysis.get("status") != "ready":
        raise ValueError("Gemini motion analysis is not ready")
    source = analysis.get("source")
    if not isinstance(source, dict):
        raise ValueError("Gemini motion analysis is missing source evidence")
    if source.get("aspectRatio") != "9:16":
        raise ValueError("Gemini analysis must confirm 9:16")
    if source.get("shotCount") != 1 or source.get("hasCuts") is not False:
        raise ValueError("reference video must be one continuous shot")
    if probe.get("shotCount") != 1 or probe.get("hasCuts") is not False:
        raise ValueError("local scene preflight did not prove a continuous shot")
    if abs(float(source.get("durationSeconds") or 0) - probe["durationSeconds"]) > 0.15:
        raise ValueError("Gemini analysis duration does not match ffprobe")


def _endpoint_path(result: dict[str, Any], role: str) -> Path:
    path = Path(str(result.get("imagePath") or "")).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"{role} Soul endpoint generation did not produce an image")
    if not str(result.get("jobId") or "").strip():
        raise RuntimeError(
            f"{role} Soul endpoint generation is missing a provider job id"
        )
    return path


def _validate_distinct_endpoints(
    *,
    source_first: Path,
    source_last: Path,
    first_endpoint: Path,
    last_endpoint: Path,
) -> None:
    hashes = {
        "source_first": sha256_file(source_first),
        "source_last": sha256_file(source_last),
        "first_endpoint": sha256_file(first_endpoint),
        "last_endpoint": sha256_file(last_endpoint),
    }
    if hashes["first_endpoint"] in {hashes["source_first"], hashes["source_last"]}:
        raise ValueError("generated first endpoint copied a source endpoint")
    if hashes["last_endpoint"] in {hashes["source_first"], hashes["source_last"]}:
        raise ValueError("generated last endpoint copied a source endpoint")
    if hashes["first_endpoint"] == hashes["last_endpoint"]:
        raise ValueError("generated Soul endpoints must be distinct")


def _verified_approval(
    seams: ReferenceVideoRemixSeams,
    *,
    approval_id: str,
    role: str,
    endpoint_path: Path,
) -> dict[str, Any]:
    digest = sha256_file(endpoint_path)
    approval = seams.verify_endpoint_approval(
        approval_id=approval_id,
        role=role,
        endpoint_path=endpoint_path,
        endpoint_sha256=digest,
    )
    if (
        approval.get("ok") is not True
        or approval.get("decision") != "approved"
        or approval.get("approvalId") != approval_id
        or approval.get("endpointSha256") != digest
    ):
        raise PermissionError(f"{role} endpoint lacks matching operator approval")
    return approval


def _validate_static_fallback(result: dict[str, Any]) -> None:
    render = result.get("render")
    quality = render.get("quality") if isinstance(render, dict) else None
    registered = result.get("registeredAsset")
    if (
        result.get("paidGeneration") is not False
        or not isinstance(render, dict)
        or not isinstance(quality, dict)
        or not isinstance(registered, dict)
        or not registered.get("id")
        or not registered.get("content_hash")
        or render.get("paidGeneration") is not False
        or render.get("lockedStatic") is not True
        or render.get("audioBurned") is not False
        or quality.get("status") != "passed"
        or quality.get("width") != 1080
        or quality.get("height") != 1920
    ):
        raise RuntimeError(
            "structural remix static fallback is not free, static, silent, and 9:16"
        )


def _final_video_path(result: dict[str, Any], *, provider: str, model: str) -> Path:
    if result.get("provider") != provider or result.get("model") != model:
        raise RuntimeError(
            "animation provider receipt does not match deterministic routing"
        )
    if not str(result.get("jobId") or "").strip():
        raise RuntimeError("animation provider receipt is missing a job id")
    path = Path(str(result.get("videoPath") or "")).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("animation provider did not produce a video")
    return path


def _validate_contentforge_qc(qc: dict[str, Any]) -> None:
    checks = qc.get("checks")
    if qc.get("ok") is not True or not isinstance(checks, dict):
        raise RuntimeError("ContentForge rejected the structural remix")
    failed = [
        name for name in REQUIRED_CONTENTFORGE_CHECKS if checks.get(name) is not True
    ]
    if failed:
        raise RuntimeError(
            "ContentForge structural checks failed: " + ", ".join(failed)
        )
    report_path = Path(str(qc.get("reportPath") or "")).expanduser().resolve()
    if not report_path.is_file():
        raise RuntimeError("ContentForge QC evidence file is missing")


def _build_lineage(**values: Any) -> dict[str, Any]:
    plan = values["plan"]
    static_fallback = values["static_fallback"]
    registered_static = static_fallback.get("registeredAsset") or {}
    return {
        "schema": "campaign_factory.reference_video_remix_lineage.v1",
        "planId": plan["planId"],
        "generationExecutionPlan": values["execution_plan"],
        "reference": {
            "path": str(values["reference_video"]),
            "sha256": sha256_file(values["reference_video"]),
            "probe": values["probe"],
            "operatorSelected": True,
            "rightsConfirmed": True,
        },
        "geminiMotionAnalysis": {
            "analysis": values["analysis"],
            "sha256": _json_sha256(values["analysis"]),
        },
        "sourceEndpoints": {
            "first": _path_evidence(values["source_first"]),
            "last": _path_evidence(values["source_last"]),
        },
        "generatedEndpoints": {
            "first": {
                **_path_evidence(values["first_endpoint"]),
                "providerJobId": values["first_generation"].get("jobId"),
                "approval": values["first_approval"],
            },
            "last": {
                **_path_evidence(values["last_endpoint"]),
                "providerJobId": values["last_generation"].get("jobId"),
                "approval": values["last_approval"],
            },
        },
        "staticFallback": {
            "renderedAssetId": registered_static.get("id"),
            "outputPath": (static_fallback.get("render") or {}).get("outputPath"),
            "contentHash": registered_static.get("content_hash"),
            "paidGeneration": False,
            "lockedStatic": True,
            "audioBurned": False,
        },
        "animation": {
            "provider": plan["animation"]["provider"],
            "model": plan["animation"]["model"],
            "providerJobId": values["animation_result"].get("jobId"),
            **_path_evidence(values["final_video"]),
        },
        "spend": {
            "maxCredits": values["max_credits"],
            "creditsSpent": values["credits_spent"],
            "receipts": values["spend"],
        },
        "contentForge": values["qc"],
        "review": {
            "endpointApprovalsVerified": True,
            "contentForgeApproved": True,
            "finalHumanReviewRequired": True,
            "status": "review_ready",
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
        "createdAt": utc_now(),
    }


def _register_remix_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    video_path: Path,
    lineage: dict[str, Any],
    lineage_path: Path,
) -> dict[str, Any]:
    digest = sha256_file(video_path)
    existing = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE campaign_id = ? AND recipe = ? AND content_hash = ?",
        (campaign["id"], "reference_video_remix", digest),
    ).fetchone()
    if existing:
        return dict(existing)
    source = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at, id LIMIT 1",
        (campaign["id"],),
    ).fetchone()
    if not source:
        raise ValueError("campaign must have a source asset before remix registration")
    asset_id = new_id("asset")
    now = utc_now()
    metadata = {
        "generatedAssetLineage": lineage,
        "generatedAssetLineagePath": str(lineage_path),
        "humanReviewRequired": True,
        "publishingAllowed": False,
    }
    caption_generation = {
        "schema": "campaign_factory.caption_generation.v1",
        "workflow": "reference_video_structural_remix",
        "animationMode": lineage["animation"]["provider"],
        "paidGeneration": True,
        "generatedAssetLineage": lineage,
        "generatedAssetLineagePath": str(lineage_path),
        "humanReviewRequired": True,
    }
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         media_type, content_surface, caption_generation_json, recipe, target_ratio, metadata_json,
         audit_status, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', ?, 'reference_video_remix', '9:16',
                ?, 'approved_candidate', 'review_ready', ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source["id"],
            digest,
            str(video_path),
            str(video_path),
            video_path.name,
            json.dumps(sanitize_for_storage(caption_generation), sort_keys=True),
            json.dumps(sanitize_for_storage(metadata), sort_keys=True),
            now,
            now,
        ),
    )
    factory.conn.commit()
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )


def _reference_video(value: Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"reference video not found: {path}")
    if path.suffix.lower() not in _VIDEO_SUFFIXES:
        raise ValueError(f"unsupported reference video type: {path.suffix}")
    return path


def _quote_amount(quote: dict[str, Any], *, provider: str, model: str) -> float:
    amount = quote.get("amount")
    if quote.get("provider") != provider or quote.get("model") != model:
        raise RuntimeError("provider quote identity does not match the requested call")
    if quote.get("unit") != "higgsfield_credits":
        raise RuntimeError("provider quote must use Higgsfield credits")
    return _positive_finite(amount, "provider quote amount")


def _reservation_id(reservation: dict[str, Any]) -> str:
    detail = reservation.get("reservation")
    value = detail.get("id") if isinstance(detail, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("credit reservation did not return an id")
    return value


def _redacted_quote(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        key: quote.get(key)
        for key in ("schema", "provider", "model", "operation", "amount", "unit")
        if quote.get(key) is not None
    }


def _positive_finite(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{label} must be finite and positive")
    return float(value)


def _required_text(value: str, label: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"{label} is required")
    return resolved


def _path_evidence(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path)}


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
