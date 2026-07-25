"""Fail-closed WaveSpeed REST adapter for the approved Wan model catalog."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from creator_os_core.provider_spend import (
    build_video_provider_spend_scope,
    verify_authorization_v2,
)

from .fileops import atomic_write_text
from .video_provider_models import VideoModel, validate_model_request, video_model

API_ROOT = "https://api.wavespeed.ai/api/v3"
UPLOAD_URL = f"{API_ROOT}/media/upload/binary"
TERMINAL_FAILURES = {"failed", "cancelled", "timeout"}
IN_PROGRESS = {"created", "processing"}
NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, deformed anatomy, extra fingers, "
    "duplicate person, text, subtitles, watermark, interface elements, abrupt cuts"
)


class AmbiguousWaveSpeedSubmission(RuntimeError):
    """POST outcome is unknown; callers must reconcile instead of retrying."""


@dataclass(frozen=True, slots=True)
class WaveSpeedRequest:
    model_id: str
    prompt: str
    output_path: Path
    image_path: Path | None = None
    last_image_path: Path | None = None
    audio_path: Path | None = None
    source_video_path: Path | None = None
    reference_video_paths: tuple[Path, ...] = ()
    reference_image_paths: tuple[Path, ...] = ()
    resolution: str = "1080p"
    duration_seconds: int | None = 5
    seed: int = 42
    enable_prompt_expansion: bool = False
    shot_type: str = "single"
    production_context: dict[str, Any] | None = None


def build_wavespeed_spend_scope(
    request: WaveSpeedRequest, *, campaign: str, cohort_id: str
) -> dict[str, Any]:
    model = _validate_request(request)
    media: dict[str, Path] = {}
    if request.image_path is not None:
        media["image"] = _file(request.image_path, "image")
    if request.last_image_path is not None:
        media["last_image"] = _file(request.last_image_path, "last image")
    if request.audio_path is not None:
        media["audio"] = _file(request.audio_path, "audio")
    if request.source_video_path is not None:
        media["source_video"] = _file(request.source_video_path, "source video")
    for index, path in enumerate(request.reference_video_paths, start=1):
        media[f"video_{index}"] = _file(path, f"reference video {index}")
    for index, path in enumerate(request.reference_image_paths, start=1):
        media[f"reference_image_{index}"] = _file(path, f"reference image {index}")
    parameters: dict[str, Any] = {
        "resolution": request.resolution,
        "durationSeconds": request.duration_seconds,
        "seed": request.seed if model.provider_accepts_seed else None,
        "requestIdentitySeed": request.seed,
        "providerSeedAccepted": model.provider_accepts_seed,
        "enablePromptExpansion": request.enable_prompt_expansion,
        "shotType": request.shot_type if model.shot_type_supported else None,
    }
    if request.production_context is not None:
        parameters["productionContext"] = _production_scope_context(
            request.production_context
        )
    if request.audio_path is not None:
        parameters["audioDurationSeconds"] = _media_duration(
            _file(request.audio_path, "audio")
        )
    if model.task == "motion_control" and request.reference_video_paths:
        parameters["referenceVideoDurationSeconds"] = _media_duration(
            _file(request.reference_video_paths[0], "motion reference video")
        )
    return build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model=model.provider_model,
        operation=model.task,
        campaign=campaign,
        cohort_id=cohort_id,
        prompt=request.prompt,
        media_paths=media,
        parameters=parameters,
    )


class WaveSpeedClient:
    """One-submit client.  Only result GETs are retried."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.api_key = api_key or os.environ.get("WAVESPEED_API_KEY", "")
        if not self.api_key:
            raise ValueError("WAVESPEED_API_KEY is required")
        self.session = session or requests.Session()
        self.sleep = sleep

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def upload(self, path: Path) -> str:
        resolved = _file(path, "WaveSpeed upload")
        with resolved.open("rb") as handle:
            response = self.session.post(
                UPLOAD_URL,
                headers=self.headers,
                files={"file": (resolved.name, handle)},
                timeout=(10, 300),
            )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("wavespeed_upload_response_invalid") from exc
        if not isinstance(body, dict) or body.get("code") != 200:
            raise RuntimeError("wavespeed_upload_rejected")
        data = body.get("data") if isinstance(body, dict) else None
        url = None
        if isinstance(data, dict):
            url = data.get("download_url") or data.get("url")
        return _https_url(url, "WaveSpeed upload response")

    def submit_once(self, model: VideoModel, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(
                f"{API_ROOT}/{model.provider_model}",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
                timeout=(10, 120),
            )
        except requests.RequestException as exc:
            raise AmbiguousWaveSpeedSubmission(
                "wavespeed_submission_outcome_ambiguous; do not retry POST"
            ) from exc
        if response.status_code >= 500:
            raise AmbiguousWaveSpeedSubmission(
                "wavespeed_submission_server_error_ambiguous; do not retry POST"
            )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise AmbiguousWaveSpeedSubmission(
                "wavespeed_submission_invalid_response_ambiguous; do not retry POST"
            ) from exc
        if not isinstance(body, dict) or body.get("code") != 200:
            raise RuntimeError("wavespeed_submission_rejected")
        task = body.get("data", body) if isinstance(body, dict) else None
        if not isinstance(task, dict) or not str(task.get("id") or "").strip():
            raise AmbiguousWaveSpeedSubmission(
                "wavespeed_submission_missing_prediction_id; do not retry POST"
            )
        return task

    def poll(
        self,
        prediction_id: str,
        *,
        result_url: str | None = None,
        timeout_seconds: int = 60 * 30,
    ) -> dict[str, Any]:
        url = _https_url(
            result_url or f"{API_ROOT}/predictions/{prediction_id}/result",
            "WaveSpeed result URL",
        )
        deadline = time.monotonic() + timeout_seconds
        interval = 2.0
        transient_failures = 0
        while time.monotonic() < deadline:
            try:
                response = self.session.get(url, headers=self.headers, timeout=(10, 60))
                response.raise_for_status()
                transient_failures = 0
            except requests.RequestException:
                transient_failures += 1
                if transient_failures > 3:
                    raise RuntimeError("wavespeed_result_poll_failed")
                self.sleep(min(10.0, interval * 2))
                continue
            body = response.json()
            if not isinstance(body, dict) or body.get("code") != 200:
                raise RuntimeError("wavespeed_result_rejected")
            result = body.get("data", body) if isinstance(body, dict) else None
            if not isinstance(result, dict):
                raise RuntimeError("wavespeed_result_invalid")
            status = str(result.get("status") or "").strip().lower()
            if status == "completed":
                return result
            if status in TERMINAL_FAILURES:
                raise RuntimeError(f"wavespeed_prediction_{status}")
            if status not in IN_PROGRESS:
                raise RuntimeError(f"wavespeed_prediction_unexpected_status:{status}")
            self.sleep(interval)
            interval = min(10.0, interval + 1.0)
        raise TimeoutError("wavespeed_prediction_poll_timeout")

    def download(self, url: str, destination: Path) -> str:
        safe_url = _https_url(url, "WaveSpeed output URL")
        output = Path(destination).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".partial")
        digest = hashlib.sha256()
        size = 0
        if output.exists():
            raise FileExistsError(f"wavespeed_output_collision: {output}")
        if temporary.exists():
            raise FileExistsError(f"wavespeed_partial_output_collision: {temporary}")
        try:
            with self.session.get(safe_url, stream=True, timeout=(10, 300)) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if size < 1024:
                raise RuntimeError("wavespeed_output_too_small")
            _probe_video(temporary)
            os.replace(temporary, output)
        except (OSError, ValueError, RuntimeError, requests.RequestException):
            temporary.unlink(missing_ok=True)
            raise
        return digest.hexdigest()


def execute_wavespeed(
    request: WaveSpeedRequest,
    *,
    campaign: str,
    cohort_id: str,
    authorization: dict[str, Any],
    secret: str,
    evidence_dir: Path,
    client: WaveSpeedClient | None = None,
) -> dict[str, Any]:
    """Upload, submit once, poll, retain, and hash one authorized prediction."""
    started_monotonic = time.monotonic()
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe_missing_before_wavespeed_submission")
    model = _validate_request(request)
    output = Path(request.output_path).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"wavespeed_output_collision: {output}")
    scope = build_wavespeed_spend_scope(request, campaign=campaign, cohort_id=cohort_id)
    verified = verify_authorization_v2(
        authorization, expected_scope=scope, secret=secret
    )
    evidence = Path(evidence_dir).expanduser().resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    intent_path = evidence / f"{scope['requestFingerprint']}.wavespeed_submission.json"
    api = client or WaveSpeedClient()
    if intent_path.exists():
        recovered_intent = _validated_recovery_intent(
            _read_json(intent_path),
            request=request,
            model=model,
            scope=scope,
            authorization_id=str(verified["authorizationId"]),
        )
        if recovered_intent.get("status") == "completed":
            digest = _sha256_file(output)
            if digest != recovered_intent.get("outputSha256"):
                raise PermissionError("wavespeed_completed_output_sha256_mismatch")
            _probe_video(output)
            if model.audio_required:
                _probe_audio(output)
            return {
                **recovered_intent,
                "evidencePath": str(intent_path),
                "scope": scope,
            }
        prediction_id = str(recovered_intent.get("predictionId") or "")
        if not prediction_id:
            raise PermissionError(
                "wavespeed_submission_is_ambiguous_or_unsubmitted; do not resubmit"
            )
        if output.exists():
            raise PermissionError("wavespeed_recovery_output_collision")
        return _poll_retain_prediction(
            api,
            request=request,
            model=model,
            prediction_id=prediction_id,
            result_url=str(recovered_intent.get("resultUrl") or "") or None,
            intent=recovered_intent,
            intent_path=intent_path,
            scope=scope,
            started_monotonic=started_monotonic,
        )
    intent: dict[str, Any] = {
        "schema": "reel_factory.wavespeed_submission.v1",
        "requestFingerprint": scope["requestFingerprint"],
        "authorizationId": verified["authorizationId"],
        "providerModel": model.provider_model,
        "seed": request.seed if model.provider_accepts_seed else None,
        "requestIdentitySeed": request.seed,
        "providerSeedAccepted": model.provider_accepts_seed,
        "creator": (
            request.production_context.get("creator")
            if request.production_context is not None
            else None
        ),
        "intent": (
            request.production_context.get("intent")
            if request.production_context is not None
            else None
        ),
        "sourceSha256": (
            scope["mediaSha256"].get("image")
            or scope["mediaSha256"].get("source_video")
        ),
        "expandedPrompt": " ".join(request.prompt.split()),
        "expandedPromptSha256": scope["promptSha256"],
        "status": "uploading",
        "predictionId": None,
        "submissionStartedAt": None,
        "submittedAt": None,
        "completedAt": None,
        "resultUrl": None,
        "outputPath": str(Path(request.output_path).expanduser().resolve()),
        "outputSha256": None,
        "outputUrl": None,
        "outputUrlSha256": None,
        "outputRecords": [],
        "generationDurationSeconds": None,
        "providerInferenceMilliseconds": None,
        "providerCostUsd": None,
    }
    _write_json(intent_path, intent)
    payload = _upload_and_build_payload(api, request, model)
    intent["status"] = "ready_to_submit"
    intent["submissionStartedAt"] = _utc_now()
    _write_json(intent_path, intent)
    try:
        task = api.submit_once(model, payload)
    except AmbiguousWaveSpeedSubmission:
        intent["status"] = "submission_ambiguous"
        _write_json(intent_path, intent)
        raise
    prediction_id = str(task["id"])
    _validate_provider_identity(task, model=model, prediction_id=prediction_id)
    raw_urls = task.get("urls")
    urls: dict[str, Any] = raw_urls if isinstance(raw_urls, dict) else {}
    result_url = (
        _https_url(urls.get("get"), "WaveSpeed result URL")
        if urls.get("get")
        else f"{API_ROOT}/predictions/{prediction_id}/result"
    )
    intent["predictionId"] = prediction_id
    intent["status"] = str(task.get("status") or "created")
    intent["submittedAt"] = str(task.get("created_at") or "") or _utc_now()
    intent["resultUrl"] = result_url
    _write_json(intent_path, intent)
    return _poll_retain_prediction(
        api,
        request=request,
        model=model,
        prediction_id=prediction_id,
        result_url=result_url,
        intent=intent,
        intent_path=intent_path,
        scope=scope,
        started_monotonic=started_monotonic,
    )


def _poll_retain_prediction(
    api: WaveSpeedClient,
    *,
    request: WaveSpeedRequest,
    model: VideoModel,
    prediction_id: str,
    result_url: str | None,
    intent: dict[str, Any],
    intent_path: Path,
    scope: dict[str, Any],
    started_monotonic: float,
) -> dict[str, Any]:
    poll_timeout = (
        60 * 60 * 6
        if model.task in {"speech_to_video", "audio_image_to_video", "video_lipsync"}
        else 60 * 30
    )
    try:
        result = api.poll(
            prediction_id,
            result_url=result_url,
            timeout_seconds=poll_timeout,
        )
    except (TimeoutError, RuntimeError, ValueError, requests.RequestException) as exc:
        intent["status"] = (
            "poll_timeout" if isinstance(exc, TimeoutError) else "poll_failed"
        )
        intent["failure"] = type(exc).__name__
        _write_json(intent_path, intent)
        raise
    _validate_provider_identity(result, model=model, prediction_id=prediction_id)
    outputs = result.get("outputs")
    if (
        not isinstance(outputs, list)
        or len(outputs) != 1
        or not isinstance(outputs[0], str)
    ):
        intent["status"] = "provider_completed_output_mismatch"
        intent["providerStatus"] = result.get("status")
        _write_json(intent_path, intent)
        raise RuntimeError("wavespeed_completed_output_mismatch")
    output_url_sha256 = hashlib.sha256(outputs[0].encode("utf-8")).hexdigest()
    previous_url_sha256 = intent.get("outputUrlSha256")
    if previous_url_sha256 and previous_url_sha256 != output_url_sha256:
        intent["status"] = "provider_completed_output_substituted"
        _write_json(intent_path, intent)
        raise RuntimeError("wavespeed_provider_output_url_substituted")
    timings = result.get("timings")
    timings = timings if isinstance(timings, dict) else {}
    inference_ms = timings.get("inference")
    if isinstance(inference_ms, bool) or not isinstance(inference_ms, (int, float)):
        inference_ms = None
    intent.update(
        {
            "status": "provider_completed_retention_pending",
            "providerStatus": result.get("status"),
            "providerCostUsd": _provider_cost(result),
            "outputUrl": _redacted_url(outputs[0]),
            "outputUrlSha256": output_url_sha256,
            "providerInferenceMilliseconds": inference_ms,
            "generationDurationSeconds": _generation_duration_seconds(
                intent, fallback_seconds=time.monotonic() - started_monotonic
            ),
            "outputRecords": [
                {
                    "index": 0,
                    "url": _redacted_url(outputs[0]),
                    "urlSha256": output_url_sha256,
                    "sha256": None,
                    "path": str(Path(request.output_path).expanduser().resolve()),
                    "retained": False,
                }
            ],
        }
    )
    _write_json(intent_path, intent)
    try:
        digest = api.download(outputs[0], request.output_path)
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        intent["status"] = "output_retention_failed"
        intent["failure"] = type(exc).__name__
        _write_json(intent_path, intent)
        raise
    embedded_audio = None
    if model.audio_required:
        _probe_audio(Path(request.output_path).expanduser().resolve())
        embedded_audio = {
            "mode": "source",
            "sourceSha256": (
                _sha256_file(_file(request.audio_path, "source audio"))
                if request.audio_path is not None
                else None
            ),
            "streamVerified": True,
        }
    intent.update(
        {
            "status": "completed",
            "outputSha256": digest,
            "completedAt": _utc_now(),
            "generationDurationSeconds": _generation_duration_seconds(
                intent, fallback_seconds=time.monotonic() - started_monotonic
            ),
            "outputRecords": [
                {
                    "index": 0,
                    "url": intent["outputUrl"],
                    "urlSha256": output_url_sha256,
                    "sha256": digest,
                    "path": str(Path(request.output_path).expanduser().resolve()),
                    "retained": True,
                }
            ],
            "failure": None,
            "audio": embedded_audio or {"mode": "none"},
        }
    )
    _write_json(intent_path, intent)
    return {**intent, "evidencePath": str(intent_path), "scope": scope}


def _validate_request(request: WaveSpeedRequest) -> VideoModel:
    model = video_model(request.model_id)
    if model.backend != "wavespeed":
        raise ValueError(f"{model.id} is not a WaveSpeed model")
    prompt = " ".join(str(request.prompt or "").split())
    if len(prompt) < 20:
        raise ValueError("WaveSpeed motion prompt must contain at least 20 characters")
    if request.seed < 0:
        raise ValueError("WaveSpeed requires an explicit non-negative seed")
    validate_model_request(
        model,
        resolution=request.resolution,
        duration=request.duration_seconds,
        has_audio=request.audio_path is not None,
        has_last_image=request.last_image_path is not None,
        has_source_video=request.source_video_path is not None,
    )
    if request.enable_prompt_expansion and not model.prompt_expansion_supported:
        raise ValueError(f"{model.id} does not support prompt expansion")
    if model.shot_type_supported and request.shot_type not in {"single", "multi"}:
        raise ValueError(f"{model.id} shot type must be single or multi")
    if not model.shot_type_supported and request.shot_type != "single":
        raise ValueError(f"{model.id} does not support shot type selection")
    if (
        model.task
        in {
            "image_to_video",
            "audio_image_to_video",
            "motion_control",
            "speech_to_video",
        }
        and request.image_path is None
    ):
        raise ValueError(f"{model.id} requires an image")
    if model.task == "video_lipsync" and request.source_video_path is None:
        raise ValueError(f"{model.id} requires a source video")
    reference_count = len(request.reference_video_paths) + len(
        request.reference_image_paths
    )
    if model.task not in {"reference_to_video", "motion_control"} and reference_count:
        raise ValueError(f"{model.id} does not accept reference collections")
    if model.task == "reference_to_video" and not request.reference_video_paths:
        raise ValueError("WaveSpeed reference-to-video requires a reference video")
    if model.task == "reference_to_video" and not 1 <= reference_count <= 5:
        raise ValueError("WaveSpeed reference-to-video allows 1 to 5 references")
    if model.task == "motion_control" and (
        len(request.reference_video_paths) != 1 or request.reference_image_paths
    ):
        raise ValueError("WaveSpeed motion control requires exactly one driving video")
    paths = [
        path
        for path in (
            request.image_path,
            request.last_image_path,
            request.audio_path,
            request.source_video_path,
            *request.reference_video_paths,
            *request.reference_image_paths,
        )
        if path is not None
    ]
    resolved_paths = [str(Path(path).expanduser().resolve()) for path in paths]
    if len(resolved_paths) != len(set(resolved_paths)):
        raise ValueError("WaveSpeed request contains duplicate media inputs")
    output = str(Path(request.output_path).expanduser().resolve())
    if output in set(resolved_paths):
        raise ValueError("WaveSpeed output path collides with an input")
    if request.production_context is not None:
        context = request.production_context
        source_path = request.image_path or request.source_video_path
        if (
            context.get("schema") != "campaign_factory.production_motion_recipe.v1"
            or context.get("modelId") != model.id
            or context.get("sourceSha256")
            != (
                _sha256_file(_file(source_path, "production source"))
                if source_path is not None
                else None
            )
            or context.get("expandedPromptSha256")
            != hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        ):
            raise PermissionError("wavespeed_production_context_mismatch")
    return model


def _upload_and_build_payload(
    client: WaveSpeedClient, request: WaveSpeedRequest, model: VideoModel
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if model.provider_accepts_prompt:
        payload["prompt"] = " ".join(request.prompt.split())
    if model.provider_accepts_seed:
        payload["seed"] = request.seed
    if model.provider_accepts_resolution:
        payload["resolution"] = request.resolution
    if model.provider_accepts_duration and request.duration_seconds:
        payload["duration"] = request.duration_seconds
    if model.prompt_expansion_supported:
        payload["enable_prompt_expansion"] = request.enable_prompt_expansion
    if model.shot_type_supported:
        payload["shot_type"] = (
            ("customize" if request.shot_type == "single" else "intelligent")
            if model.id == "wavespeed_kling_o3_pro_i2v"
            else request.shot_type
        )
    if model.provider_accepts_negative_prompt:
        payload["negative_prompt"] = NEGATIVE_PROMPT
    if request.image_path is not None:
        payload["image"] = client.upload(request.image_path)
    if request.last_image_path is not None:
        payload[
            "end_image" if model.id == "wavespeed_kling_o3_pro_i2v" else "last_image"
        ] = client.upload(request.last_image_path)
    if request.audio_path is not None:
        payload["audio"] = client.upload(request.audio_path)
    if request.source_video_path is not None:
        payload["video"] = client.upload(request.source_video_path)
    if model.task == "reference_to_video" and request.reference_video_paths:
        payload["videos"] = [
            client.upload(path) for path in request.reference_video_paths
        ]
    if model.task == "reference_to_video" and request.reference_image_paths:
        payload["reference_images"] = [
            client.upload(path) for path in request.reference_image_paths
        ]
    if model.task == "reference_to_video":
        payload["aspect_ratio"] = "9:16"
    elif model.id == "wavespeed_vidu_q3_i2v_pro":
        payload.update(
            {
                "movement_amplitude": "auto",
                "generate_audio": False,
                "bgm": False,
            }
        )
    elif model.id == "wavespeed_kling_o3_pro_i2v":
        payload["sound"] = False
    elif model.id == "wavespeed_kling_v3_pro_motion_control":
        payload["video"] = client.upload(request.reference_video_paths[0])
        payload["character_orientation"] = "video"
        payload["keep_original_sound"] = False
    elif model.id == "wavespeed_sync_lipsync2_pro":
        payload["sync_mode"] = "cut_off"
    return payload


def _production_scope_context(context: dict[str, Any]) -> dict[str, Any]:
    required = ("creator", "intent", "sourceSha256", "expandedPromptSha256")
    if any(not str(context.get(key) or "") for key in required):
        raise ValueError("WaveSpeed production context is incomplete")
    return {key: context[key] for key in required}


def _validate_provider_identity(
    payload: dict[str, Any], *, model: VideoModel, prediction_id: str
) -> None:
    returned_id = str(payload.get("id") or "")
    if returned_id and returned_id != prediction_id:
        raise RuntimeError("wavespeed_prediction_id_substituted")
    returned_model = str(payload.get("model") or "")
    if returned_model and returned_model != model.provider_model:
        raise RuntimeError("wavespeed_provider_model_substituted")


def _validated_recovery_intent(
    intent: dict[str, Any],
    *,
    request: WaveSpeedRequest,
    model: VideoModel,
    scope: dict[str, Any],
    authorization_id: str,
) -> dict[str, Any]:
    if (
        intent.get("schema") != "reel_factory.wavespeed_submission.v1"
        or intent.get("requestFingerprint") != scope["requestFingerprint"]
        or intent.get("authorizationId") != authorization_id
        or intent.get("providerModel") != model.provider_model
        or intent.get("requestIdentitySeed") != request.seed
        or intent.get("seed") != (request.seed if model.provider_accepts_seed else None)
        or intent.get("sourceSha256")
        != (
            scope["mediaSha256"].get("image")
            or scope["mediaSha256"].get("source_video")
        )
        or intent.get("expandedPromptSha256") != scope["promptSha256"]
        or intent.get("outputPath")
        != str(Path(request.output_path).expanduser().resolve())
    ):
        raise PermissionError("wavespeed_recovery_evidence_scope_mismatch")
    allowed = {
        "created",
        "processing",
        "poll_timeout",
        "poll_failed",
        "provider_completed_retention_pending",
        "output_retention_failed",
        "completed",
    }
    if intent.get("status") not in allowed:
        raise PermissionError(
            "wavespeed_submission_is_ambiguous_or_unrecoverable; do not resubmit"
        )
    return intent


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _generation_duration_seconds(
    intent: dict[str, Any], *, fallback_seconds: float
) -> float:
    raw = str(intent.get("submissionStartedAt") or intent.get("submittedAt") or "")
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return round(max(0.0, fallback_seconds), 3)
    return round(max(0.0, (datetime.now(UTC) - started).total_seconds()), 3)


def _redacted_url(value: str) -> str:
    parsed = urlparse(_https_url(value, "WaveSpeed output URL"))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file(value: Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _media_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    try:
        value = float(proc.stdout.strip())
    except ValueError as exc:
        raise ValueError("audio duration could not be measured") from exc
    if proc.returncode != 0 or value <= 0:
        raise ValueError("audio duration could not be measured")
    return round(value, 3)


def _https_url(value: Any, label: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be HTTPS")
    return url


def _probe_video(path: Path) -> None:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError("wavespeed_output_unreadable")
    try:
        streams = json.loads(proc.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("wavespeed_output_probe_invalid") from exc
    if len(streams) != 1:
        raise RuntimeError("wavespeed_output_video_stream_mismatch")
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError("wavespeed_output_dimensions_missing")
    ratio = width / height
    if not 0.50 <= ratio <= 0.65:
        raise RuntimeError("wavespeed_output_not_portrait_reel")


def _probe_audio(path: Path) -> None:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError("wavespeed_output_audio_unreadable")
    try:
        streams = json.loads(proc.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("wavespeed_output_audio_probe_invalid") from exc
    if len(streams) != 1:
        raise RuntimeError("wavespeed_output_audio_stream_mismatch")
    stream = streams[0]
    if (
        not str(stream.get("codec_name") or "")
        or int(stream.get("sample_rate") or 0) <= 0
        or int(stream.get("channels") or 0) <= 0
    ):
        raise RuntimeError("wavespeed_output_audio_metadata_missing")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError("wavespeed_submission_evidence_unreadable") from exc
    if not isinstance(value, dict):
        raise PermissionError("wavespeed_submission_evidence_invalid")
    return value


def _provider_cost(result: dict[str, Any]) -> float | None:
    for key in ("cost", "cost_usd", "costUsd", "actual_cost"):
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            if parsed >= 0:
                return parsed
    return None
