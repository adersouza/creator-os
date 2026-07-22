"""Fail-closed WaveSpeed REST adapter for the approved Wan model catalog."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    reference_video_paths: tuple[Path, ...] = ()
    reference_image_paths: tuple[Path, ...] = ()
    resolution: str = "1080p"
    duration_seconds: int | None = 5
    seed: int = 42
    enable_prompt_expansion: bool = False
    shot_type: str = "single"


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
    for index, path in enumerate(request.reference_video_paths, start=1):
        media[f"video_{index}"] = _file(path, f"reference video {index}")
    for index, path in enumerate(request.reference_image_paths, start=1):
        media[f"reference_image_{index}"] = _file(path, f"reference image {index}")
    parameters: dict[str, Any] = {
        "resolution": request.resolution,
        "durationSeconds": request.duration_seconds,
        "seed": request.seed,
        "enablePromptExpansion": request.enable_prompt_expansion,
        "shotType": request.shot_type if model.shot_type_supported else None,
    }
    if request.audio_path is not None:
        parameters["audioDurationSeconds"] = _media_duration(
            _file(request.audio_path, "audio")
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
    if intent_path.exists():
        previous = _read_json(intent_path)
        if previous.get("status") != "uploading" or previous.get("predictionId"):
            raise PermissionError("wavespeed_request_already_has_submission_evidence")
    intent: dict[str, Any] = {
        "schema": "reel_factory.wavespeed_submission.v1",
        "requestFingerprint": scope["requestFingerprint"],
        "authorizationId": verified["authorizationId"],
        "providerModel": model.provider_model,
        "status": "uploading",
        "predictionId": None,
        "outputPath": str(Path(request.output_path).expanduser().resolve()),
        "outputSha256": None,
    }
    _write_json(intent_path, intent)
    api = client or WaveSpeedClient()
    payload = _upload_and_build_payload(api, request, model)
    intent["status"] = "ready_to_submit"
    _write_json(intent_path, intent)
    try:
        task = api.submit_once(model, payload)
    except AmbiguousWaveSpeedSubmission:
        intent["status"] = "submission_ambiguous"
        _write_json(intent_path, intent)
        raise
    prediction_id = str(task["id"])
    intent["predictionId"] = prediction_id
    intent["status"] = str(task.get("status") or "created")
    _write_json(intent_path, intent)
    raw_urls = task.get("urls")
    urls: dict[str, Any] = raw_urls if isinstance(raw_urls, dict) else {}
    poll_timeout = 60 * 60 * 6 if model.task == "speech_to_video" else 60 * 30
    try:
        result = api.poll(
            prediction_id,
            result_url=urls.get("get"),
            timeout_seconds=poll_timeout,
        )
    except (TimeoutError, RuntimeError, ValueError, requests.RequestException) as exc:
        intent["status"] = (
            "poll_timeout" if isinstance(exc, TimeoutError) else "poll_failed"
        )
        intent["failure"] = type(exc).__name__
        _write_json(intent_path, intent)
        raise
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
    intent.update(
        {
            "status": "provider_completed_retention_pending",
            "providerStatus": result.get("status"),
            "providerCostUsd": _provider_cost(result),
            "outputUrlSha256": hashlib.sha256(outputs[0].encode("utf-8")).hexdigest(),
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
    intent.update(
        {
            "status": "completed",
            "outputSha256": digest,
            "failure": None,
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
    )
    if request.enable_prompt_expansion and not model.prompt_expansion_supported:
        raise ValueError(f"{model.id} does not support prompt expansion")
    if model.shot_type_supported and request.shot_type not in {"single", "multi"}:
        raise ValueError(f"{model.id} shot type must be single or multi")
    if not model.shot_type_supported and request.shot_type != "single":
        raise ValueError(f"{model.id} does not support shot type selection")
    if (
        model.task in {"image_to_video", "speech_to_video"}
        and request.image_path is None
    ):
        raise ValueError(f"{model.id} requires an image")
    reference_count = len(request.reference_video_paths) + len(
        request.reference_image_paths
    )
    if model.task != "reference_to_video" and reference_count:
        raise ValueError(f"{model.id} does not accept reference collections")
    if model.task == "reference_to_video" and not request.reference_video_paths:
        raise ValueError("WaveSpeed reference-to-video requires a reference video")
    if model.task == "reference_to_video" and not 1 <= reference_count <= 5:
        raise ValueError("WaveSpeed reference-to-video allows 1 to 5 references")
    paths = [
        path
        for path in (
            request.image_path,
            request.last_image_path,
            request.audio_path,
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
    return model


def _upload_and_build_payload(
    client: WaveSpeedClient, request: WaveSpeedRequest, model: VideoModel
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": " ".join(request.prompt.split()),
        "resolution": request.resolution,
        "seed": request.seed,
    }
    if request.duration_seconds:
        payload["duration"] = request.duration_seconds
    if model.prompt_expansion_supported:
        payload["enable_prompt_expansion"] = request.enable_prompt_expansion
    if model.shot_type_supported:
        payload["shot_type"] = request.shot_type
    if model.task != "speech_to_video":
        payload["negative_prompt"] = NEGATIVE_PROMPT
    if request.image_path is not None:
        payload["image"] = client.upload(request.image_path)
    if request.last_image_path is not None:
        payload["last_image"] = client.upload(request.last_image_path)
    if request.audio_path is not None:
        payload["audio"] = client.upload(request.audio_path)
    if request.reference_video_paths:
        payload["videos"] = [
            client.upload(path) for path in request.reference_video_paths
        ]
    if request.reference_image_paths:
        payload["reference_images"] = [
            client.upload(path) for path in request.reference_image_paths
        ]
    if model.task == "reference_to_video":
        payload["aspect_ratio"] = "9:16"
    return payload


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
