"""Apple-silicon local Wan 2.2 execution through MLX-Video.

This module does not install or download anything at generation time.  Model
installation/conversion is an explicit operator step, and every run is bound to
the exact local model manifest and source-image hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text

MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B"
RUNNER_MODULE = "mlx_video.models.wan_2.generate"
MLX_VIDEO_REVISION = "87db56a51758fefb748a359b90a5283bb8ba4837"
REQUIRED_MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "t5_encoder.safetensors",
    "vae.safetensors",
)
DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted face, deformed hands, extra fingers, "
    "duplicate person, text, subtitles, watermark, interface elements, abrupt cuts"
)


class LocalWanUnavailable(RuntimeError):
    """Raised when the configured local runtime cannot prove readiness."""


@dataclass(frozen=True, slots=True)
class LocalWanRequest:
    image_path: Path
    prompt: str
    output_path: Path
    model_dir: Path
    duration_seconds: int = 6
    seed: int = 42
    steps: int = 40
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT


def probe_local_wan(
    *, model_dir: str | Path | None = None, python_executable: str | None = None
) -> dict[str, Any]:
    model = _model_dir(model_dir)
    python = python_executable or os.environ.get("CREATOR_OS_LOCAL_WAN_PYTHON")
    python = python or shutil.which("python3") or ""
    issues: list[str] = []
    manifest_sha256 = None
    model_file_sha256: dict[str, str] = {}
    runtime_provenance = None
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        issues.append("apple_silicon_required_for_mlx_backend")
    if not shutil.which("ffprobe"):
        issues.append("ffprobe_missing")
    if not python or not Path(python).expanduser().exists():
        issues.append("python_runtime_missing")
    manifest = model / "config.json"
    if not model.is_dir():
        issues.append("converted_model_directory_missing")
    else:
        missing_files = [
            name for name in REQUIRED_MODEL_FILES if not (model / name).is_file()
        ]
        issues.extend(f"converted_model_file_missing:{name}" for name in missing_files)
        if manifest.is_file():
            try:
                config = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                issues.append("converted_model_manifest_invalid")
                config = None
            if isinstance(config, dict):
                manifest_sha256 = _sha256_file(manifest)
                if not _is_ti2v_5b_config(config):
                    issues.append("converted_model_identity_mismatch")
        for name in REQUIRED_MODEL_FILES:
            path = model / name
            if path.is_file():
                model_file_sha256[name] = _sha256_file(path)
    if python and Path(python).expanduser().exists():
        probe_script = (
            "import importlib.metadata as m, json, mlx, mlx_video; "
            "from transformers import AutoTokenizer; "
            "AutoTokenizer.from_pretrained('google/umt5-xxl', local_files_only=True); "
            "d=m.distribution('mlx-video'); "
            "print(json.dumps({'version': d.version, "
            "'direct_url': json.loads(d.read_text('direct_url.json') or '{}')}))"
        )
        proc = subprocess.run(
            [python, "-c", probe_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            issues.append("mlx_video_runtime_or_tokenizer_missing")
        else:
            try:
                runtime_provenance = json.loads(proc.stdout)
            except json.JSONDecodeError:
                issues.append("mlx_video_provenance_unreadable")
            if isinstance(runtime_provenance, dict):
                direct = runtime_provenance.get("direct_url")
                vcs = direct.get("vcs_info") if isinstance(direct, dict) else None
                revision = vcs.get("commit_id") if isinstance(vcs, dict) else None
                if revision != MLX_VIDEO_REVISION:
                    issues.append("mlx_video_revision_mismatch")
    return {
        "schema": "reel_factory.local_wan_capability.v1",
        "backend": "mlx_video",
        "model": MODEL_ID,
        "modelDir": str(model),
        "modelManifestSha256": manifest_sha256,
        "modelFileSha256": model_file_sha256,
        "python": python or None,
        "mlxVideoRevision": MLX_VIDEO_REVISION,
        "runtimeProvenance": runtime_provenance,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "ready": not issues,
        "issues": issues,
        "paidProviderCalls": 0,
    }


def build_local_wan_command(
    request: LocalWanRequest, *, python_executable: str | None = None
) -> list[str]:
    duration = int(request.duration_seconds)
    if duration not in {5, 6, 7, 8}:
        raise ValueError("local Wan duration must be 5, 6, 7, or 8 seconds")
    if request.seed < 0:
        raise ValueError("local Wan requires an explicit non-negative seed")
    if request.steps < 10 or request.steps > 60:
        raise ValueError("local Wan steps must be between 10 and 60")
    prompt = " ".join(str(request.prompt or "").split())
    if len(prompt) < 20:
        raise ValueError("local Wan motion prompt must contain at least 20 characters")
    image = Path(request.image_path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(f"local Wan input image not found: {image}")
    model_dir = Path(request.model_dir).expanduser().resolve()
    output = Path(request.output_path).expanduser().resolve()
    python = python_executable or os.environ.get("CREATOR_OS_LOCAL_WAN_PYTHON")
    python = python or shutil.which("python3") or "python3"
    # 24 fps and 4n+1 are both model constraints.  The extra first frame keeps
    # the requested duration while satisfying the temporal VAE contract.
    frames = 4 * round(duration * 24 / 4) + 1
    return [
        python,
        "-m",
        RUNNER_MODULE,
        "--model-dir",
        str(model_dir),
        "--image",
        str(image),
        "--prompt",
        prompt,
        "--negative-prompt",
        request.negative_prompt,
        "--width",
        "704",
        "--height",
        "1280",
        "--num-frames",
        str(frames),
        "--steps",
        str(request.steps),
        "--guide-scale",
        "5.0",
        "--seed",
        str(request.seed),
        "--scheduler",
        "unipc",
        "--tiling",
        "auto",
        "--output-path",
        str(output),
    ]


def run_local_wan(
    request: LocalWanRequest,
    *,
    dry_run: bool,
    python_executable: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    image = Path(request.image_path).expanduser().resolve()
    output = Path(request.output_path).expanduser().resolve()
    capability = probe_local_wan(
        model_dir=request.model_dir, python_executable=python_executable
    )
    command = build_local_wan_command(request, python_executable=python_executable)
    lineage_path = output.with_suffix(output.suffix + ".local_wan.json")
    lineage = {
        "schema": "reel_factory.local_wan_generation.v1",
        "backend": "mlx_video",
        "model": MODEL_ID,
        "input": {"path": str(image), "sha256": _sha256_file(image)},
        "request": {
            "prompt": " ".join(request.prompt.split()),
            "negativePrompt": request.negative_prompt,
            "durationSeconds": request.duration_seconds,
            "resolution": "704x1280",
            "fps": 24,
            "steps": request.steps,
            "seed": request.seed,
            "scheduler": "unipc",
        },
        "capability": capability,
        "command": command,
        "paidGeneration": False,
        "providerCalls": 0,
        "outputPath": str(output),
        "outputSha256": None,
        "status": "planned" if dry_run else "pending",
    }
    if dry_run:
        return lineage
    if not capability["ready"]:
        raise LocalWanUnavailable(
            "local_wan_unavailable: " + ", ".join(capability["issues"])
        )
    if output.exists():
        raise FileExistsError(f"local_wan_output_collision: {output}")
    if lineage_path.exists():
        raise FileExistsError(f"local_wan_lineage_collision: {lineage_path}")
    partial = output.with_suffix(".partial" + output.suffix)
    if partial.exists():
        raise FileExistsError(f"local_wan_partial_collision: {partial}")
    output.parent.mkdir(parents=True, exist_ok=True)
    apply_request = LocalWanRequest(
        image_path=request.image_path,
        prompt=request.prompt,
        output_path=partial,
        model_dir=request.model_dir,
        duration_seconds=request.duration_seconds,
        seed=request.seed,
        steps=request.steps,
        negative_prompt=request.negative_prompt,
    )
    command = build_local_wan_command(
        apply_request, python_executable=python_executable
    )
    lineage["command"] = command
    lineage["status"] = "running"
    lineage["lineagePath"] = str(lineage_path)
    lineage["partialOutputPath"] = str(partial)
    atomic_write_text(
        lineage_path,
        json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    offline_env = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60 * 60 * 6,
            env=offline_env,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "local_wan_generation_failed: "
                + (completed.stderr[-2000:] or completed.stdout[-2000:])
            )
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise RuntimeError("local_wan_output_missing")
        _validate_video(partial, expected_duration_seconds=request.duration_seconds)
        os.replace(partial, output)
        lineage["outputSha256"] = _sha256_file(output)
        lineage["status"] = "completed"
        lineage["partialOutputPath"] = None
        atomic_write_text(
            lineage_path,
            json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except KeyboardInterrupt as exc:
        _persist_local_failure(lineage_path, lineage, exc, status="interrupted")
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        _persist_local_failure(lineage_path, lineage, exc, status="failed")
        raise
    return lineage


def _model_dir(value: str | Path | None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_WAN_MODEL_DIR")
    selected = selected or Path.home() / ".creator-os/models/Wan2.2-TI2V-5B-MLX"
    return Path(selected).expanduser().resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_video(path: Path, *, expected_duration_seconds: int) -> None:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name,avg_frame_rate,nb_frames:format=duration",
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
        raise RuntimeError("local_wan_output_unreadable")
    try:
        streams = json.loads(proc.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("local_wan_output_probe_invalid") from exc
    if len(streams) != 1:
        raise RuntimeError("local_wan_output_video_stream_mismatch")
    stream = streams[0]
    if int(stream.get("width") or 0) != 704 or int(stream.get("height") or 0) != 1280:
        raise RuntimeError("local_wan_output_dimensions_mismatch")
    if str(stream.get("codec_name") or "").lower() not in {"h264", "hevc"}:
        raise RuntimeError("local_wan_output_codec_mismatch")
    try:
        numerator, denominator = str(stream.get("avg_frame_rate") or "").split("/", 1)
        fps = float(numerator) / float(denominator)
        duration = float(json.loads(proc.stdout).get("format", {}).get("duration"))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("local_wan_output_timing_invalid") from exc
    if abs(fps - 24.0) > 0.05:
        raise RuntimeError("local_wan_output_fps_mismatch")
    if abs(duration - float(expected_duration_seconds)) > 0.25:
        raise RuntimeError("local_wan_output_duration_mismatch")


def _is_ti2v_5b_config(config: dict[str, Any]) -> bool:
    try:
        return (
            str(config.get("model_version")) == "2.2"
            and str(config.get("model_type")) == "ti2v"
            and int(config.get("dim") or 0) == 3072
            and int(config.get("num_layers") or 0) == 30
            and config.get("dual_model") is False
            and int(config.get("max_area") or 0) == 704 * 1280
        )
    except (TypeError, ValueError):
        return False


def _persist_local_failure(
    lineage_path: Path,
    lineage: dict[str, Any],
    exc: BaseException,
    *,
    status: str,
) -> None:
    lineage["status"] = status
    lineage["failure"] = type(exc).__name__
    atomic_write_text(
        lineage_path,
        json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
