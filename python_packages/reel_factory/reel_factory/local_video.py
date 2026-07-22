"""Offline, model-catalog-driven local MLX video execution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from .fileops import atomic_write_text
from .local_model_manager import (
    hf_home,
    model_status,
    runtime_model_dir,
    runtime_status,
)
from .local_video_models import (
    MODEL_MANIFEST,
    LocalVideoModelSpec,
    default_local_model_dir,
    local_video_model_spec,
    ltx_text_encoder_dir,
)
from .video_provider_models import validate_model_request, video_model

AudioMode = Literal["none", "source", "generated"]
Runner = Callable[..., subprocess.CompletedProcess[str]]

DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted face, deformed hands, extra fingers, "
    "duplicate person, text, subtitles, watermark, interface elements, abrupt cuts"
)


class LocalVideoUnavailable(RuntimeError):
    """Raised when local runtime, weights, or dependency proof is incomplete."""


@dataclass(frozen=True, slots=True)
class LocalVideoRequest:
    model_id: str
    image_path: Path
    prompt: str
    output_path: Path
    model_dir: Path | None = None
    duration_seconds: int = 6
    resolution: str | None = None
    seed: int = 42
    steps: int | None = None
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    audio_mode: AudioMode = "none"
    audio_path: Path | None = None
    last_image_path: Path | None = None


def probe_local_video(
    model_id: str,
    *,
    model_dir: str | Path | None = None,
    python_executable: str | None = None,
) -> dict[str, Any]:
    spec = local_video_model_spec(model_id)
    directory = (
        Path(model_dir).expanduser().resolve()
        if model_dir is not None
        else default_local_model_dir(model_id)
    )
    model_capability = (
        _custom_model_status(spec, directory)
        if model_dir is not None
        else model_status(model_id)
    )
    runtime = runtime_status()
    configured_python = python_executable or os.environ.get(
        "CREATOR_OS_LOCAL_MLX_PYTHON"
    )
    configured_python = configured_python or str(runtime.get("python") or "")
    issues = list(model_capability["issues"])
    if not runtime["ready"]:
        issues.extend(str(value) for value in runtime["issues"])
    if not configured_python or not Path(configured_python).is_file():
        issues.append("local_mlx_python_missing")
    return {
        "schema": "reel_factory.local_video_capability.v1",
        "modelId": model_id,
        "family": spec.family,
        "model": model_capability,
        "runtime": runtime,
        "python": configured_python or None,
        "ready": not issues,
        "issues": sorted(set(issues)),
        "providerCalls": 0,
        "paidGeneration": False,
        "generationDownloadsAllowed": False,
    }


def build_local_video_command(
    request: LocalVideoRequest, *, python_executable: str | None = None
) -> list[str]:
    spec = local_video_model_spec(request.model_id)
    model = video_model(request.model_id)
    resolution = request.resolution or model.default_resolution
    validate_model_request(
        model,
        resolution=resolution,
        duration=request.duration_seconds,
        has_audio=request.audio_path is not None,
        has_last_image=request.last_image_path is not None,
        generate_audio=request.audio_mode == "generated",
    )
    _validate_request_inputs(request, spec)
    directory = (
        Path(request.model_dir).expanduser().resolve()
        if request.model_dir is not None
        else default_local_model_dir(request.model_id)
    )
    python = python_executable or os.environ.get("CREATOR_OS_LOCAL_MLX_PYTHON")
    python = python or str(runtime_status().get("python") or "python3")
    prompt = " ".join(request.prompt.split())
    image = Path(request.image_path).expanduser().resolve()
    output = Path(request.output_path).expanduser().resolve()
    if spec.family == "wan_2":
        return _build_wan_command(
            request,
            spec=spec,
            python=python,
            model_dir=runtime_model_dir(spec, directory),
            image=image,
            output=output,
            prompt=prompt,
        )
    return _build_ltx_command(
        request,
        spec=spec,
        python=python,
        model_dir=directory,
        image=image,
        output=output,
        prompt=prompt,
    )


def run_local_video(
    request: LocalVideoRequest,
    *,
    dry_run: bool,
    python_executable: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    spec = local_video_model_spec(request.model_id)
    image = Path(request.image_path).expanduser().resolve()
    output = Path(request.output_path).expanduser().resolve()
    capability = probe_local_video(
        request.model_id,
        model_dir=request.model_dir,
        python_executable=python_executable,
    )
    command = build_local_video_command(request, python_executable=python_executable)
    lineage_path = output.with_suffix(output.suffix + ".local_video.json")
    audio_sidecar = output.with_suffix(output.suffix + ".audio.wav")
    manifest = capability.get("model", {}).get("manifest")
    lineage: dict[str, Any] = {
        "schema": "reel_factory.local_video_generation.v1",
        "backend": "mlx_video",
        "modelId": request.model_id,
        "modelFamily": spec.family,
        "modelRepository": spec.repository,
        "modelRevision": spec.revision,
        "modelManifestSha256": capability.get("model", {}).get("manifestSha256"),
        "modelManifest": manifest,
        "input": {"path": str(image), "sha256": _sha256_file(image)},
        "lastImage": _optional_input(request.last_image_path),
        "sourceAudio": _optional_input(request.audio_path),
        "audio": {
            "mode": request.audio_mode,
            "nativePlatformAudio": False,
            "sidecarPath": str(audio_sidecar) if request.audio_mode != "none" else None,
            "sidecarSha256": None,
            "humanAudioReviewRequired": request.audio_mode != "none",
        },
        "request": {
            "prompt": " ".join(request.prompt.split()),
            "negativePrompt": request.negative_prompt,
            "durationSeconds": request.duration_seconds,
            "resolution": f"{spec.width}x{spec.height}",
            "fps": spec.fps,
            "steps": request.steps or spec.default_steps,
            "seed": request.seed,
            "pipeline": spec.pipeline,
        },
        "capability": capability,
        "command": command,
        "paidGeneration": False,
        "providerCalls": 0,
        "outputPath": str(output),
        "outputSha256": None,
        "status": "planned" if dry_run else "pending",
        "humanReviewRequired": True,
        "schedulingAllowed": False,
        "publishingAllowed": False,
        "aiDisclosureRequired": spec.ai_disclosure_required,
    }
    if dry_run:
        return lineage
    if not capability["ready"]:
        raise LocalVideoUnavailable(
            "local_video_unavailable: " + ", ".join(capability["issues"])
        )
    for path, code in (
        (output, "local_video_output_collision"),
        (lineage_path, "local_video_lineage_collision"),
        (audio_sidecar, "local_video_audio_collision"),
    ):
        if path.exists() and not (
            path == audio_sidecar and request.audio_mode == "none"
        ):
            raise FileExistsError(f"{code}: {path}")
    partial = output.with_suffix(".partial" + output.suffix)
    partial_audio = audio_sidecar.with_suffix(".partial.wav")
    if partial.exists() or partial_audio.exists():
        raise FileExistsError(f"local_video_partial_collision: {partial}")
    output.parent.mkdir(parents=True, exist_ok=True)
    apply_request = replace(request, output_path=partial)
    command = build_local_video_command(
        apply_request, python_executable=python_executable
    )
    if spec.family == "ltx_2" and request.audio_mode != "none":
        command.extend(["--output-audio", str(partial_audio)])
    lineage["command"] = command
    lineage["status"] = "running"
    lineage["lineagePath"] = str(lineage_path)
    lineage["partialOutputPath"] = str(partial)
    lineage["partialAudioPath"] = (
        str(partial_audio) if request.audio_mode != "none" else None
    )
    _persist(lineage_path, lineage)
    offline_env = {
        **os.environ,
        "HF_HOME": str(hf_home()),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60 * 60 * 12,
            env=offline_env,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "local_video_generation_failed: "
                + (completed.stderr[-3000:] or completed.stdout[-3000:])
            )
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise RuntimeError("local_video_output_missing")
        probe = _validate_video(
            partial,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_duration_seconds=request.duration_seconds,
            expected_fps=spec.fps,
            expect_audio=request.audio_mode != "none",
        )
        if request.audio_mode != "none":
            if not partial_audio.is_file() or partial_audio.stat().st_size <= 0:
                raise RuntimeError("local_video_audio_sidecar_missing")
            os.replace(partial_audio, audio_sidecar)
            lineage["audio"]["sidecarSha256"] = _sha256_file(audio_sidecar)
        os.replace(partial, output)
        lineage["outputSha256"] = _sha256_file(output)
        lineage["outputProbe"] = probe
        lineage["status"] = "completed"
        lineage["partialOutputPath"] = None
        lineage["partialAudioPath"] = None
        _persist(lineage_path, lineage)
    except KeyboardInterrupt as exc:
        _persist_failure(lineage_path, lineage, exc, status="interrupted")
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        _persist_failure(lineage_path, lineage, exc, status="failed")
        raise
    return lineage


def _build_wan_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    python: str,
    model_dir: Path,
    image: Path,
    output: Path,
    prompt: str,
) -> list[str]:
    frames = 4 * round(request.duration_seconds * spec.fps / 4) + 1
    command = [
        python,
        "-m",
        "mlx_video.models.wan_2.generate",
        "--model-dir",
        str(model_dir),
        "--image",
        str(image),
        "--prompt",
        prompt,
        "--negative-prompt",
        request.negative_prompt,
        "--width",
        str(spec.width),
        "--height",
        str(spec.height),
        "--num-frames",
        str(frames),
        "--steps",
        str(request.steps or spec.default_steps),
        "--guide-scale",
        spec.guide_scale,
        "--seed",
        str(request.seed),
        "--scheduler",
        "unipc",
        "--tiling",
        "aggressive" if "a14b" in spec.model_id else "auto",
        "--output-path",
        str(output),
    ]
    if "a14b" in spec.model_id:
        command.extend(["--trim-first-frames", "1"])
    return command


def _build_ltx_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    python: str,
    model_dir: Path,
    image: Path,
    output: Path,
    prompt: str,
) -> list[str]:
    frames = 8 * round(request.duration_seconds * spec.fps / 8) + 1
    command = [
        python,
        "-m",
        "mlx_video.models.ltx_2.generate",
        "--model-repo",
        str(model_dir),
        "--text-encoder-repo",
        str(ltx_text_encoder_dir()),
        "--pipeline",
        spec.pipeline,
        "--image",
        str(image),
        "--prompt",
        prompt,
        "--negative-prompt",
        request.negative_prompt,
        "--width",
        str(spec.width),
        "--height",
        str(spec.height),
        "--num-frames",
        str(frames),
        "--fps",
        str(spec.fps),
        "--steps",
        str(request.steps or spec.default_steps),
        "--seed",
        str(request.seed),
        "--tiling",
        "aggressive",
        "--spatial-upscaler",
        "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        "--output-path",
        str(output),
    ]
    if spec.pipeline != "distilled":
        command.extend(["--cfg-scale", spec.guide_scale, "--apg"])
    if request.last_image_path is not None:
        command.extend(
            ["--end-image", str(Path(request.last_image_path).expanduser().resolve())]
        )
    if request.audio_mode == "source":
        assert request.audio_path is not None
        command.extend(
            ["--audio-file", str(Path(request.audio_path).expanduser().resolve())]
        )
    elif request.audio_mode == "generated":
        command.append("--audio")
    return command


def _validate_request_inputs(
    request: LocalVideoRequest, spec: LocalVideoModelSpec
) -> None:
    if request.seed < 0:
        raise ValueError("local video requires an explicit non-negative seed")
    steps = request.steps or spec.default_steps
    if steps < 4 or steps > 60:
        raise ValueError("local video steps must be between 4 and 60")
    prompt = " ".join(str(request.prompt or "").split())
    if len(prompt) < 20:
        raise ValueError(
            "local video motion prompt must contain at least 20 characters"
        )
    image = Path(request.image_path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(f"local video input image not found: {image}")
    if request.audio_mode == "source":
        if request.audio_path is None:
            raise ValueError("source audio mode requires --audio")
        if not Path(request.audio_path).expanduser().resolve().is_file():
            raise FileNotFoundError("local video source audio not found")
    elif request.audio_path is not None:
        raise ValueError("--audio requires source audio mode")
    if (
        request.last_image_path is not None
        and not Path(request.last_image_path).expanduser().resolve().is_file()
    ):
        raise FileNotFoundError("local video last image not found")
    if spec.family == "wan_2" and request.audio_mode != "none":
        raise ValueError("local Wan does not support audio; select a local LTX model")


def _custom_model_status(spec: LocalVideoModelSpec, directory: Path) -> dict[str, Any]:
    manifest_path = directory / MODEL_MANIFEST
    issues = []
    manifest: dict[str, Any] | None = None
    try:
        decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append("local_model_manifest_missing_or_invalid")
    else:
        if isinstance(decoded, dict):
            manifest = decoded
        else:
            issues.append("local_model_manifest_invalid")
    if manifest is not None and (
        manifest.get("modelId") != spec.model_id
        or manifest.get("revision") != spec.revision
    ):
        issues.append("local_model_manifest_identity_mismatch")
    for relative in spec.required_paths:
        if not (directory / relative).is_file():
            issues.append(f"local_model_required_file_missing:{relative}")
    return {
        "modelId": spec.model_id,
        "modelDir": str(directory),
        "runtimeModelDir": str(runtime_model_dir(spec, directory)),
        "manifest": manifest,
        "manifestSha256": (
            _sha256_file(manifest_path) if manifest_path.is_file() else None
        ),
        "ready": not issues,
        "issues": issues,
    }


def _validate_video(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_duration_seconds: int,
    expected_fps: int,
    expect_audio: bool,
) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,avg_frame_rate:format=duration",
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
        raise RuntimeError("local_video_output_unreadable")
    try:
        payload = json.loads(proc.stdout)
        streams = payload.get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("local_video_output_probe_invalid") from exc
    videos = [value for value in streams if value.get("codec_type") == "video"]
    audios = [value for value in streams if value.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise RuntimeError("local_video_output_video_stream_mismatch")
    video = videos[0]
    if (
        int(video.get("width") or 0) != expected_width
        or int(video.get("height") or 0) != expected_height
    ):
        raise RuntimeError("local_video_output_dimensions_mismatch")
    if str(video.get("codec_name") or "").lower() not in {"h264", "hevc"}:
        raise RuntimeError("local_video_output_codec_mismatch")
    if expect_audio != (len(audios) == 1):
        raise RuntimeError("local_video_output_audio_stream_mismatch")
    try:
        numerator, denominator = str(video.get("avg_frame_rate") or "").split("/", 1)
        fps = float(numerator) / float(denominator)
        duration = float(payload.get("format", {}).get("duration"))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("local_video_output_timing_invalid") from exc
    if abs(fps - float(expected_fps)) > 0.05:
        raise RuntimeError("local_video_output_fps_mismatch")
    if abs(duration - float(expected_duration_seconds)) > 0.35:
        raise RuntimeError("local_video_output_duration_mismatch")
    return payload


def _optional_input(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _persist(path: Path, lineage: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_failure(
    lineage_path: Path,
    lineage: dict[str, Any],
    exc: BaseException,
    *,
    status: str,
) -> None:
    lineage["status"] = status
    lineage["failure"] = type(exc).__name__
    _persist(lineage_path, lineage)
