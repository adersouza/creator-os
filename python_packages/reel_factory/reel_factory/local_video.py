"""Offline, model-catalog-driven local MLX video execution."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypedDict

from pipeline_contracts import validate_local_model_router_decision

from .fileops import atomic_write_text
from .local_generation_queue import (
    LocalGenerationJob,
    WorkerLeaseUnavailable,
    default_local_generation_queue,
    fingerprint,
    hardware_identity,
)
from .local_lora_registry import verify_local_lora
from .local_model_benchmark import LocalBenchmarkTimer
from .local_model_manager import (
    hf_home,
    model_status,
    runtime_model_dir,
    runtime_status,
)
from .local_video_models import (
    LocalVideoModelSpec,
    default_local_model_dir,
    local_video_model_spec,
    ltx_text_encoder_dir,
)
from .video_provider_models import validate_model_request, video_model

AudioMode = Literal["none", "source", "generated", "preserved"]
LocalVideoTask = Literal[
    "text_to_video",
    "image_to_video",
    "audio_image_to_video",
    "keyframe_interpolation",
    "video_retake",
    "video_extend",
]
LocalVideoExecutionContext = Literal["campaign_generation", "arena_benchmark"]
Runner = Callable[..., subprocess.CompletedProcess[str]]

_MAX_GENERATION_LOG_BYTES = 16 * 1024 * 1024
_GENERATION_LOG_TAIL_BYTES = 32 * 1024
_GENERATION_TIMEOUT_SECONDS = 60 * 60 * 12
_GENERATION_SIGNAL_GRACE_SECONDS = 10
_GENERATION_KILL_GRACE_SECONDS = 30
_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS = 5
_MEDIA_TOOL_DISCOVERY_TIMEOUT_SECONDS = 30

_SUBPROCESS_ENV_ALLOWLIST = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY",
        "OMP_NUM_THREADS",
        "PATH",
        "PYTHONHASHSEED",
        "PYTHONUNBUFFERED",
        "SYSTEM_VERSION_COMPAT",
        "TOKENIZERS_PARALLELISM",
        "VECLIB_MAXIMUM_THREADS",
    }
)
_ENVIRONMENT_PATH_POLICY = "allowlisted_uv_build_temp_bins_removed_v1"
_SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
_SANDBOX_DENIAL_PROBE = """import errno
import socket
import sys

mask = 0
try:
    with open(sys.argv[1], "xb") as handle:
        handle.write(b"x")
except PermissionError:
    pass
else:
    mask |= 1
try:
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("127.0.0.1", 0))
except PermissionError:
    pass
else:
    mask |= 2
finally:
    try:
        tcp.close()
    except NameError:
        pass
try:
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.connect(("127.0.0.1", 9))
except PermissionError:
    pass
else:
    mask |= 4
finally:
    try:
        udp.close()
    except NameError:
        pass
try:
    tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_client.connect(("127.0.0.1", 9))
except PermissionError:
    pass
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.EACCES}:
        mask |= 8
else:
    mask |= 8
finally:
    try:
        tcp_client.close()
    except NameError:
        pass
raise SystemExit(mask)
"""
_SANDBOX_ALLOWED_WRITE_PROBE = """import os
import sys

descriptor = os.open(
    sys.argv[1],
    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
    0o600,
)
try:
    os.write(descriptor, b"creator-os-sandbox-write-probe")
    os.fsync(descriptor)
finally:
    os.close(descriptor)
os.unlink(sys.argv[1])
"""
_IMAGEIO_FFMPEG_DISCOVERY_PROBE = """from imageio_ffmpeg import get_ffmpeg_exe

print(get_ffmpeg_exe())
"""

DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted face, deformed hands, extra fingers, "
    "duplicate person, text, subtitles, watermark, interface elements, abrupt cuts"
)


class LocalVideoUnavailable(RuntimeError):
    """Raised when local runtime, weights, or dependency proof is incomplete."""


class _GenerationProcessFailure(RuntimeError):
    def __init__(self, message: str, *, log_evidence: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.log_evidence = dict(log_evidence)


class _GenerationTerminationRequested(BaseException):
    """Convert a termination signal into a recoverable interruption."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(signum)


class _OutputExpectations(TypedDict):
    width: int
    height: int
    fps: int
    duration: float | None
    minimumDuration: float | None


@dataclass(frozen=True, slots=True)
class _GenerationProcessResult:
    returncode: int
    log_evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocalVideoRequest:
    model_id: str
    image_path: Path | None
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
    task: LocalVideoTask = "image_to_video"
    lora_path: Path | None = None
    lora_strength: float = 1.0
    source_video_path: Path | None = None
    retake_start_frame: int | None = None
    retake_end_frame: int | None = None
    extend_frames: int | None = None
    extend_direction: Literal["before", "after"] = "after"
    low_ram: bool = True
    tile_frames: int = 1
    tile_spatial: int = 2
    benchmark_recipe: Mapping[str, Any] | None = None
    analyzer_registry: Mapping[str, Any] | None = None
    creator_identity_profile: Mapping[str, Any] | None = None
    content_intent: Mapping[str, Any] | None = None
    execution_context: LocalVideoExecutionContext | None = None
    local_motion_admission: Mapping[str, Any] | None = None
    arena_benchmark_binding: Mapping[str, Any] | None = None


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
    runtime = runtime_status(family=spec.family)
    python_env = _python_environment_name(spec.family)
    configured_python = python_executable or os.environ.get(python_env)
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
        task=request.task,
        has_image=request.image_path is not None,
        has_lora=request.lora_path is not None,
    )
    _validate_request_inputs(request, spec)
    directory = (
        Path(request.model_dir).expanduser().resolve()
        if request.model_dir is not None
        else default_local_model_dir(request.model_id)
    )
    python_env = _python_environment_name(spec.family)
    python = python_executable or os.environ.get(python_env)
    runtime = runtime_status(family=spec.family)
    python = python or str(runtime.get("python") or "python3")
    prompt = " ".join(request.prompt.split())
    image = (
        Path(request.image_path).expanduser().resolve()
        if request.image_path is not None
        else None
    )
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
    if spec.family == "ltx_2":
        return _build_ltx_command(
            request,
            spec=spec,
            python=python,
            model_dir=directory,
            image=image,
            output=output,
            prompt=prompt,
        )
    return _build_longcat_command(
        request,
        spec=spec,
        python=python,
        model_dir=directory,
        runtime_root=Path(str(runtime["runtimeDir"])),
        output=output,
        prompt=prompt,
    )


def _process_log_evidence(
    log_path: Path,
    *,
    observed_bytes: int,
    tail: bytes,
    truncated: bool,
) -> dict[str, Any]:
    captured_bytes = log_path.stat().st_size if log_path.is_file() else 0
    return {
        "schema": "reel_factory.local_generation_process_log.v1",
        "path": str(log_path),
        "sha256": _sha256_file(log_path) if log_path.is_file() else None,
        "capturedBytes": captured_bytes,
        "observedBytes": observed_bytes,
        "maximumCapturedBytes": _MAX_GENERATION_LOG_BYTES,
        "truncated": truncated,
        "tail": tail.decode("utf-8", errors="replace"),
    }


def _wait_for_process_exit(process: subprocess.Popen[bytes], *, timeout: int) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _terminate_isolated_process_group(
    process: subprocess.Popen[bytes], *, initial_signal: int
) -> None:
    """Signal and reap only the exact child-created process group."""

    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.wait()
        return
    if process_group != process.pid:
        # start_new_session=True guarantees pid == pgid. Never signal a
        # potentially unrelated process group if that invariant drifts.
        process.kill()
        process.wait()
        raise RuntimeError("local_video_child_process_group_mismatch")

    signals = [initial_signal]
    if initial_signal not in {signal.SIGTERM, signal.SIGKILL}:
        signals.append(signal.SIGTERM)
    if signals[-1] != signal.SIGKILL:
        signals.append(signal.SIGKILL)
    for signum in signals:
        try:
            os.killpg(process_group, signum)
        except ProcessLookupError:
            process.wait()
            return
        timeout = (
            _GENERATION_KILL_GRACE_SECONDS
            if signum == signal.SIGKILL
            else _GENERATION_SIGNAL_GRACE_SECONDS
        )
        if _wait_for_process_exit(process, timeout=timeout):
            return
    raise RuntimeError("local_video_child_process_group_not_reaped")


def _install_termination_handlers() -> dict[int, Any]:
    if threading.current_thread() is not threading.main_thread():
        return {}

    previous: dict[int, Any] = {}

    def requested(signum: int, _frame: Any) -> None:
        raise _GenerationTerminationRequested(signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, requested)
    return previous


def _restore_termination_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _run_generation_process(
    command: list[str],
    *,
    environment: Mapping[str, str],
    log_path: Path,
    runner: Runner,
) -> _GenerationProcessResult:
    """Stream one process into a bounded append-only log without buffering stdout."""

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_APPEND
    descriptor = os.open(log_path, flags, 0o600)
    observed_bytes = 0
    tail = bytearray()
    truncated = False

    def retain(chunk: bytes, handle: Any) -> None:
        nonlocal observed_bytes, truncated
        observed_bytes += len(chunk)
        remaining = max(0, _MAX_GENERATION_LOG_BYTES - handle.tell())
        if remaining:
            handle.write(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
        tail.extend(chunk)
        if len(tail) > _GENERATION_LOG_TAIL_BYTES:
            del tail[: len(tail) - _GENERATION_LOG_TAIL_BYTES]

    with os.fdopen(descriptor, "wb", buffering=0) as handle:
        if runner is not subprocess.run:
            completed = runner(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=False,
                check=False,
                timeout=_GENERATION_TIMEOUT_SECONDS,
                env=dict(environment),
            )
            for value in (
                getattr(completed, "stdout", None),
                getattr(completed, "stderr", None),
            ):
                if value:
                    retain(
                        value.encode("utf-8", errors="replace")
                        if isinstance(value, str)
                        else bytes(value),
                        handle,
                    )
            return _GenerationProcessResult(
                returncode=int(completed.returncode),
                log_evidence=_process_log_evidence(
                    log_path,
                    observed_bytes=observed_bytes,
                    tail=bytes(tail),
                    truncated=truncated,
                ),
            )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(environment),
            start_new_session=True,
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("local_video_generation_log_pipe_missing")
        output_stream = process.stdout

        def drain() -> None:
            for chunk in iter(lambda: output_stream.read(64 * 1024), b""):
                retain(chunk, handle)

        drain_thread = threading.Thread(
            target=drain,
            name="creator-os-local-video-log-drain",
            daemon=True,
        )
        drain_thread.start()
        previous_handlers = _install_termination_handlers()
        try:
            returncode = process.wait(timeout=_GENERATION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _restore_termination_handlers(previous_handlers)
            previous_handlers = {}
            _terminate_isolated_process_group(process, initial_signal=signal.SIGKILL)
            drain_thread.join(timeout=30)
            evidence = _process_log_evidence(
                log_path,
                observed_bytes=observed_bytes,
                tail=bytes(tail),
                truncated=truncated,
            )
            raise _GenerationProcessFailure(
                "local_video_generation_timeout: " + evidence["tail"][-3000:],
                log_evidence=evidence,
            ) from None
        except _GenerationTerminationRequested as exc:
            _restore_termination_handlers(previous_handlers)
            previous_handlers = {}
            _terminate_isolated_process_group(process, initial_signal=exc.signum)
            drain_thread.join(timeout=30)
            interrupted = KeyboardInterrupt(
                f"local_video_generation_terminated:{exc.signum}"
            )
            interrupted.log_evidence = _process_log_evidence(  # type: ignore[attr-defined]
                log_path,
                observed_bytes=observed_bytes,
                tail=bytes(tail),
                truncated=truncated,
            )
            raise interrupted from None
        except KeyboardInterrupt as exc:
            _restore_termination_handlers(previous_handlers)
            previous_handlers = {}
            _terminate_isolated_process_group(process, initial_signal=signal.SIGINT)
            drain_thread.join(timeout=30)
            exc.log_evidence = _process_log_evidence(  # type: ignore[attr-defined]
                log_path,
                observed_bytes=observed_bytes,
                tail=bytes(tail),
                truncated=truncated,
            )
            raise
        finally:
            _restore_termination_handlers(previous_handlers)
        drain_thread.join(timeout=30)
        if drain_thread.is_alive():
            raise RuntimeError("local_video_generation_log_drain_failed")
        return _GenerationProcessResult(
            returncode=returncode,
            log_evidence=_process_log_evidence(
                log_path,
                observed_bytes=observed_bytes,
                tail=bytes(tail),
                truncated=truncated,
            ),
        )


def run_local_video(
    request: LocalVideoRequest,
    *,
    dry_run: bool,
    python_executable: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    spec = local_video_model_spec(request.model_id)
    image = (
        Path(request.image_path).expanduser().resolve()
        if request.image_path is not None
        else None
    )
    output = Path(request.output_path).expanduser().resolve()
    capability = probe_local_video(
        request.model_id,
        model_dir=request.model_dir,
        python_executable=python_executable,
    )
    execution_binding = _validate_execution_binding(request, capability=capability)
    capability_fingerprint = _execution_capability_fingerprint(capability)
    command = build_local_video_command(request, python_executable=python_executable)
    lineage_path = output.with_suffix(output.suffix + ".local_video.json")
    audio_sidecar = output.with_suffix(output.suffix + ".audio.wav")
    manifest = capability.get("model", {}).get("manifest")
    lineage: dict[str, Any] = {
        "schema": "reel_factory.local_video_generation.v1",
        "backend": {
            "wan_2": "mlx_video",
            "ltx_2": "ltx_2_mlx",
            "longcat_avatar": "longcat_avatar_mlx",
        }[spec.family],
        "modelId": request.model_id,
        "modelFamily": spec.family,
        "modelRepository": spec.repository,
        "modelRevision": spec.revision,
        "modelManifestSha256": capability.get("model", {}).get("manifestSha256"),
        "modelManifest": manifest,
        "executionContext": request.execution_context,
        "executionBinding": execution_binding,
        "localMotionAdmission": (
            dict(request.local_motion_admission)
            if request.local_motion_admission is not None
            else None
        ),
        "arenaBenchmarkBinding": (
            dict(request.arena_benchmark_binding)
            if request.arena_benchmark_binding is not None
            else None
        ),
        "input": (
            {"path": str(image), "sha256": _sha256_file(image)}
            if image is not None
            else None
        ),
        "lastImage": _optional_input(request.last_image_path),
        "sourceVideo": _optional_input(request.source_video_path),
        "sourceAudio": _optional_input(request.audio_path),
        "lora": _optional_lora(
            request.lora_path, request.lora_strength, model_id=request.model_id
        ),
        "audio": {
            "mode": request.audio_mode,
            "nativePlatformAudio": False,
            "sidecarPath": str(audio_sidecar) if request.audio_mode != "none" else None,
            "sidecarSha256": None,
            "humanAudioReviewRequired": request.audio_mode != "none",
        },
        "request": {
            "prompt": " ".join(request.prompt.split()),
            "negativePrompt": (
                request.negative_prompt if spec.family == "wan_2" else None
            ),
            "negativePromptApplied": spec.family == "wan_2",
            "durationSeconds": request.duration_seconds,
            "resolution": f"{spec.width}x{spec.height}",
            "fps": spec.fps,
            "steps": _effective_steps(request, spec),
            "seed": request.seed,
            "pipeline": spec.pipeline,
            "task": request.task,
            "retakeStartFrame": request.retake_start_frame,
            "retakeEndFrame": request.retake_end_frame,
            "extendFrames": request.extend_frames,
            "extendDirection": request.extend_direction,
            "lowRam": request.low_ram,
            "tileFrames": request.tile_frames,
            "tileSpatial": request.tile_spatial,
        },
        "capability": capability,
        "executionCapabilityFingerprint": capability_fingerprint,
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
        planned_base_command = _build_execution_command(
            request,
            spec=spec,
            output=output,
            python_executable=python_executable,
        )
        planned_command, _planned_environment, planned_isolation = _isolated_execution(
            request,
            output=output,
            base_command=planned_base_command,
        )
        lineage["command"] = planned_command
        lineage["executionIsolation"] = planned_isolation
        lineage["providerCalls"] = planned_isolation["providerActivity"][
            "callsObserved"
        ]
        return lineage
    lineage["inputPreflight"] = _preflight_local_inputs(request)
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
    base_command = _build_execution_command(
        request,
        spec=spec,
        output=output,
        python_executable=python_executable,
    )
    command, offline_env, isolation = _isolated_execution(
        request,
        output=output,
        base_command=base_command,
    )
    lineage["command"] = command
    lineage["executionIsolation"] = isolation
    execution_log_path = Path(str(isolation["sandboxRoot"])) / "logs" / "generation.log"
    lineage["executionLog"] = {
        "schema": "reel_factory.local_generation_process_log.v1",
        "path": str(execution_log_path),
        "sha256": None,
        "capturedBytes": 0,
        "observedBytes": 0,
        "maximumCapturedBytes": _MAX_GENERATION_LOG_BYTES,
        "truncated": False,
        "tail": "",
    }
    lineage["providerCalls"] = isolation["providerActivity"]["callsObserved"]
    lineage["status"] = "running"
    lineage["lineagePath"] = str(lineage_path)
    lineage["partialOutputPath"] = str(partial)
    lineage["partialAudioPath"] = (
        str(partial_audio) if request.audio_mode != "none" else None
    )
    queue = default_local_generation_queue()
    job = _generation_job(
        request,
        spec=spec,
        capability=capability,
        command=command,
        output=output,
        execution_isolation=isolation,
    )
    lineage["queue"] = {
        "jobId": job.job_id,
        "journalPath": str(queue.journal.path),
        "resourceLimitBytes": queue.resource_limit_bytes,
        "requestedMemoryBytes": job.requested_memory_bytes,
    }
    artifacts_completed = False
    execution_stage = "pre_queue_admission"
    try:
        with queue.worker_session(blocking=False) as lease:
            queue.submit_and_start_exact(lease, job)
            queue_terminal = False
            try:
                execution_stage = "pre_generation_validation"
                # Do not create the requested lineage/output namespace until
                # the exact job owns both the machine lease and resource
                # admission. Busy or memory-blocked attempts remain clean and
                # retryable while their queue journal evidence is preserved.
                _prepare_isolation_workspace(isolation)
                current_capability = probe_local_video(
                    request.model_id,
                    python_executable=python_executable,
                )
                current_fingerprint = _execution_capability_fingerprint(
                    current_capability
                )
                if (
                    current_capability.get("ready") is not True
                    or current_fingerprint != capability_fingerprint
                ):
                    raise LocalVideoUnavailable(
                        "local_video_execution_capability_drift"
                    )
                # Recompute the launcher target and complete media-tool
                # evidence after queue admission, immediately before spawn.
                # A same-path binary replacement must not inherit the earlier
                # plan's approval.
                _bind_isolated_toolchain(
                    request,
                    base_command=base_command,
                    environment=offline_env,
                )
                current_sandbox = _sandbox_executable()
                if (
                    current_sandbox is None
                    or str(current_sandbox) != command[0]
                    or len(command) < 5
                    or command[1] != "-p"
                    or command[3] != "--"
                ):
                    raise LocalVideoUnavailable(
                        "local_video_isolation_execution_binding_drift"
                    )
                execution_stage = "isolation_preflight"
                current_isolation_preflight = _preflight_sandbox_execution(
                    sandbox_exec=current_sandbox,
                    profile=command[2],
                    python_executable=Path(command[4]),
                    forbidden_write_path=_sandbox_forbidden_write_probe_path(),
                )
                if current_isolation_preflight != isolation["isolationPreflight"]:
                    raise LocalVideoUnavailable("local_video_isolation_preflight_drift")
                execution_stage = "media_tool_discovery_preflight"
                current_media_tool_discovery = _preflight_imageio_ffmpeg_discovery(
                    sandbox_exec=current_sandbox,
                    profile=command[2],
                    python_executable=Path(command[4]),
                    environment=offline_env,
                    expected_ffmpeg=Path(offline_env["IMAGEIO_FFMPEG_EXE"]),
                )
                if (
                    current_media_tool_discovery
                    != isolation["mediaToolDiscoveryPreflight"]
                ):
                    raise LocalVideoUnavailable(
                        "local_video_media_tool_discovery_preflight_drift"
                    )
                execution_stage = "allowed_write_preflight"
                allowed_write_preflight = _preflight_allowed_sandbox_write(
                    sandbox_exec=current_sandbox,
                    profile=command[2],
                    python_executable=Path(command[4]),
                    sandbox_root=Path(str(isolation["sandboxRoot"])),
                )
                lineage["executionRevalidation"] = {
                    "modelId": request.model_id,
                    "capabilityFingerprint": current_fingerprint,
                    "isolationPreflightFingerprint": fingerprint(
                        current_isolation_preflight
                    ),
                    "mediaToolDiscoveryPreflightFingerprint": fingerprint(
                        current_media_tool_discovery
                    ),
                    "allowedWritePreflight": allowed_write_preflight,
                    "deepVerified": current_capability.get("model", {}).get(
                        "deepVerified"
                    ),
                    "modelDeepVerificationFingerprint": current_capability.get(
                        "model", {}
                    )
                    .get("deepVerificationReceipt", {})
                    .get("verificationFingerprint"),
                    "ready": True,
                }
                _persist(lineage_path, lineage)
                execution_stage = "generation_process"
                benchmark_timer = LocalBenchmarkTimer.start()
                try:
                    completed = _run_generation_process(
                        command,
                        environment=offline_env,
                        log_path=execution_log_path,
                        runner=runner,
                    )
                except (
                    KeyboardInterrupt,
                    OSError,
                    RuntimeError,
                    subprocess.SubprocessError,
                ) as exc:
                    failed_measurement = benchmark_timer.finish()
                    failure_log = getattr(exc, "log_evidence", None)
                    if isinstance(failure_log, dict):
                        lineage["executionLog"] = failure_log
                    elif execution_log_path.is_file():
                        captured = execution_log_path.read_bytes()
                        lineage["executionLog"] = _process_log_evidence(
                            execution_log_path,
                            observed_bytes=len(captured),
                            tail=captured[-_GENERATION_LOG_TAIL_BYTES:],
                            truncated=(len(captured) >= _MAX_GENERATION_LOG_BYTES),
                        )
                    lineage["executionMeasurement"] = {
                        "wallTimeSeconds": failed_measurement.wall_time_seconds,
                        "peakMemoryBytes": failed_measurement.peak_memory_bytes,
                        "memoryMeasurementMethod": (
                            failed_measurement.memory_measurement_method
                        ),
                    }
                    raise
                execution_stage = "post_generation_validation"
                lineage["executionLog"] = completed.log_evidence
                measurement = benchmark_timer.finish()
                lineage["executionMeasurement"] = {
                    "wallTimeSeconds": measurement.wall_time_seconds,
                    "peakMemoryBytes": measurement.peak_memory_bytes,
                    "memoryMeasurementMethod": measurement.memory_measurement_method,
                }
                if completed.returncode != 0:
                    raise RuntimeError(
                        "local_video_generation_failed: "
                        + str(completed.log_evidence["tail"])[-3000:]
                    )
                if not partial.is_file() or partial.stat().st_size <= 0:
                    raise RuntimeError("local_video_output_missing")
                if spec.family == "ltx_2" and request.audio_mode != "none":
                    _extract_audio_sidecar(partial, partial_audio)
                expectations = _output_expectations(
                    request, spec=spec, preflight=lineage["inputPreflight"]
                )
                probe = _validate_video(
                    partial,
                    expected_width=expectations["width"],
                    expected_height=expectations["height"],
                    expected_duration_seconds=expectations["duration"],
                    minimum_duration_seconds=expectations["minimumDuration"],
                    expected_fps=expectations["fps"],
                    expect_audio=request.audio_mode != "none",
                )
                verified = queue.verify_generated_artifacts(
                    lease,
                    job.job_id,
                    partial_output_path=partial,
                    final_output_path=output,
                    output_probe=probe,
                    execution_measurement=lineage["executionMeasurement"],
                    partial_audio_path=(
                        partial_audio if request.audio_mode != "none" else None
                    ),
                    final_audio_path=(
                        audio_sidecar if request.audio_mode != "none" else None
                    ),
                )
                if request.audio_mode != "none":
                    if not partial_audio.is_file() or partial_audio.stat().st_size <= 0:
                        raise RuntimeError("local_video_audio_sidecar_missing")
                    os.replace(partial_audio, audio_sidecar)
                    lineage["audio"]["sidecarSha256"] = verified["audioSha256"]
                os.replace(partial, output)
                lineage["outputSha256"] = verified["outputSha256"]
                lineage["outputProbe"] = verified["outputProbe"]
                lineage["executionMeasurement"] = verified["executionMeasurement"]
                lineage["status"] = "completed"
                lineage["partialOutputPath"] = None
                lineage["partialAudioPath"] = None
                # Persist the complete, verified lineage before the terminal
                # queue event. If power is lost in the narrow gap, the
                # operator can reconcile the immutable completed artifacts
                # without rerunning inference.
                _persist(lineage_path, lineage)
                artifacts_completed = True
                queue.succeed(
                    lease,
                    job.job_id,
                    output_sha256=lineage["outputSha256"],
                    output_path=output,
                    execution_measurement=lineage["executionMeasurement"],
                )
                queue_terminal = True
            except KeyboardInterrupt:
                lineage["executionStage"] = execution_stage
                if not queue_terminal and not artifacts_completed:
                    queue.interrupt(
                        lease,
                        job.job_id,
                        reason=f"{execution_stage}_interrupted",
                    )
                raise
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                if not queue_terminal and not artifacts_completed:
                    queue.fail(
                        lease,
                        job.job_id,
                        error=exc,
                        execution_measurement=lineage.get("executionMeasurement"),
                    )
                raise
    except KeyboardInterrupt as exc:
        if not artifacts_completed:
            _persist_failure(lineage_path, lineage, exc, status="interrupted")
        raise
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        WorkerLeaseUnavailable,
    ) as exc:
        if lineage_path.exists() and not artifacts_completed:
            _persist_failure(lineage_path, lineage, exc, status="failed")
        raise
    return lineage


def plan_local_video_job(
    request: LocalVideoRequest,
    *,
    python_executable: str | None = None,
) -> LocalGenerationJob:
    """Return the exact queue job that ``run_local_video`` will submit.

    Arena planning needs to freeze the queue identity before inference starts.
    This helper deliberately performs only local, read-only capability and
    command construction; it does not acquire the worker lock, enqueue work,
    download a model, or invoke a provider.
    """

    spec = local_video_model_spec(request.model_id)
    output = Path(request.output_path).expanduser().resolve()
    capability = probe_local_video(
        request.model_id,
        model_dir=request.model_dir,
        python_executable=python_executable,
    )
    _validate_execution_binding(request, capability=capability)
    base_command = _build_execution_command(
        request,
        spec=spec,
        output=output,
        python_executable=python_executable,
    )
    command, _environment, isolation = _isolated_execution(
        request,
        output=output,
        base_command=base_command,
    )
    return _generation_job(
        request,
        spec=spec,
        capability=capability,
        command=command,
        output=output,
        execution_isolation=isolation,
    )


def _isolated_execution(
    request: LocalVideoRequest,
    *,
    output: Path,
    base_command: list[str],
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    environment_source = os.environ if environ is None else environ
    if platform.system() != "Darwin":
        raise LocalVideoUnavailable("local_video_isolation_unavailable:macos_required")
    sandbox_exec = _sandbox_executable()
    if sandbox_exec is None:
        raise LocalVideoUnavailable(
            "local_video_isolation_unavailable:sandbox_exec_missing"
        )
    partial = output.with_suffix(".partial" + output.suffix)
    partial_audio = output.with_suffix(output.suffix + ".audio.wav").with_suffix(
        ".partial.wav"
    )
    sandbox_id = fingerprint(
        {
            "modelId": request.model_id,
            "task": request.task,
            "outputPath": str(output),
            "inputSha256": _optional_input_sha256(
                request.image_path or request.source_video_path
            ),
        }
    )[:20]
    sandbox_root = output.parent / f".local_video_sandbox_{sandbox_id}"
    home = sandbox_root / "home"
    temporary = sandbox_root / "tmp"
    cache = sandbox_root / "cache"
    allowed_write_paths = [sandbox_root, partial]
    if request.audio_mode != "none":
        allowed_write_paths.append(partial_audio)
    profile = "\n".join(
        [
            "(version 1)",
            # `system.sb` is an Apple-private profile whose execution policy
            # changed on macOS 27. Keep this profile self-contained.
            "(allow default)",
            "(deny network*)",
            "(deny file-write*",
            "  (require-not",
            "    (require-any",
            *[
                f"      ({'subpath' if path == sandbox_root else 'literal'} {json.dumps(str(path))})"
                for path in allowed_write_paths
            ],
            "    )",
            "  )",
            ")",
        ]
    )
    environment = {
        key: str(environment_source[key])
        for key in sorted(_SUBPROCESS_ENV_ALLOWLIST)
        if environment_source.get(key) is not None
    }
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(cache),
            "HF_HOME": str(hf_home()),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    environment = _sanitize_subprocess_environment(
        environment,
        environment_source=environment_source,
    )
    runtime = _runtime_binding(request)
    expected_ffmpeg = str(runtime.get("ffmpegExecutable") or "")
    if not expected_ffmpeg:
        raise LocalVideoUnavailable("local_video_ffmpeg_runtime_binding_mismatch")
    # Bind imageio-ffmpeg's own selector to the same exact runtime binary that
    # the content-addressed toolchain check approves. PATH alone is not enough
    # for this consumer and allowed the canary to fail only after rendering.
    environment["IMAGEIO_FFMPEG_EXE"] = expected_ffmpeg
    command = _bind_isolated_toolchain(
        request,
        base_command=base_command,
        environment=environment,
    )
    isolation_preflight = _preflight_sandbox_execution(
        sandbox_exec=sandbox_exec,
        profile=profile,
        python_executable=Path(command[0]),
        forbidden_write_path=_sandbox_forbidden_write_probe_path(),
    )
    media_tool_discovery_preflight = _preflight_imageio_ffmpeg_discovery(
        sandbox_exec=sandbox_exec,
        profile=profile,
        python_executable=Path(command[0]),
        environment=environment,
        expected_ffmpeg=Path(expected_ffmpeg),
    )
    isolation_core = {
        "schema": "reel_factory.local_subprocess_isolation.v1",
        "platform": "macos",
        "hostOperatingSystem": {
            "macVersion": platform.mac_ver()[0],
            "kernelRelease": platform.release(),
            "kernelVersion": platform.version(),
            "machine": platform.machine(),
        },
        "enforcement": "sandbox-exec",
        "enforcementBinary": str(Path(sandbox_exec).resolve()),
        "enforced": True,
        "networkAccess": "denied",
        "writeAccess": "explicit_artifacts_only",
        "allowedWritePaths": [str(path) for path in allowed_write_paths],
        "sandboxRoot": str(sandbox_root),
        "profileFingerprint": fingerprint({"profile": profile}),
        "environmentPolicy": "allowlist",
        "environmentAllowedKeys": sorted(environment),
        "environmentPathPolicy": _ENVIRONMENT_PATH_POLICY,
        "environmentFingerprint": fingerprint(environment),
        "isolationPreflight": isolation_preflight,
        "mediaToolDiscoveryPreflight": media_tool_discovery_preflight,
        "providerActivity": {
            "callsObserved": 0,
            "attemptsObserved": None,
            "successfulDirectSocketCallsPossible": False,
            "measurementScope": "successful_direct_socket_provider_calls",
            "observationMethod": "macos_sandbox_active_socket_denial_preflight",
            "enforcementStatus": "enforced",
            "evidenceBasis": (
                "tcp_bind_tcp_connect_and_udp_connect_denied_by_macos_sandbox"
            ),
        },
    }
    isolation = {
        **isolation_core,
        "isolationFingerprint": fingerprint(isolation_core),
    }
    return (
        [str(sandbox_exec), "-p", profile, "--", *command],
        environment,
        isolation,
    )


def _sanitize_subprocess_environment(
    environment: Mapping[str, str],
    *,
    environment_source: Mapping[str, str],
) -> dict[str, str]:
    """Remove uv build-launcher bins from the actual child environment.

    ``uv run --with-editable`` prepends a random
    ``builds-v<digits>/.tmp<nonempty>/bin`` directory for each invocation.
    Passing it through would let a planner and worker resolve different
    executables. Remove only that exact lexical shape beneath uv's configured
    cache, preserve every other entry (including order and duplicates), and
    fingerprint the exact sanitized environment that is executed.
    """

    sanitized = dict(environment)
    raw_path = sanitized.get("PATH")
    if raw_path is None:
        return sanitized
    configured_cache = environment_source.get("UV_CACHE_DIR")
    uv_cache = (
        Path(configured_cache).expanduser()
        if configured_cache
        else (Path.home() / ".cache" / "uv")
    )
    uv_cache = Path(os.path.abspath(uv_cache))
    retained = [
        raw_entry
        for raw_entry in raw_path.split(os.pathsep)
        if not _is_uv_ephemeral_build_bin(raw_entry, uv_cache=uv_cache)
    ]
    sanitized["PATH"] = os.pathsep.join(retained)
    return sanitized


def _is_uv_ephemeral_build_bin(raw_entry: str, *, uv_cache: Path) -> bool:
    if not raw_entry:
        return False
    candidate = Path(os.path.abspath(Path(raw_entry).expanduser()))
    try:
        relative = candidate.relative_to(uv_cache)
    except ValueError:
        return False
    parts = relative.parts
    if len(parts) != 3 or parts[2] != "bin":
        return False
    cache_format, ephemeral_id, _bin = parts
    if cache_format.startswith("builds-v"):
        version = cache_format.removeprefix("builds-v")
        return (
            version.isdigit()
            and ephemeral_id.startswith(".tmp")
            and len(ephemeral_id) > len(".tmp")
        )
    return False


def _sandbox_executable() -> Path | None:
    if _SANDBOX_EXECUTABLE.is_file() and os.access(_SANDBOX_EXECUTABLE, os.X_OK):
        return _SANDBOX_EXECUTABLE
    return None


def _preflight_sandbox_execution(
    *,
    sandbox_exec: Path,
    profile: str,
    python_executable: Path,
    forbidden_write_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Prove execution plus network/write denial before queue admission.

    A permissive control must first show that the probe capabilities are
    available in the parent environment. Otherwise an outer sandbox could make
    an ineffective inner policy look enforced.
    """

    python = python_executable.expanduser()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise LocalVideoUnavailable("local_video_isolation_probe_python_unavailable")
    python_resolved = python.resolve(strict=True)
    forbidden = forbidden_write_path.expanduser()
    if forbidden.exists() or forbidden.is_symlink():
        raise LocalVideoUnavailable("local_video_isolation_probe_path_collision")
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    probe_arguments = [
        str(python),
        "-B",
        "-I",
        "-S",
        "-E",
        "-c",
        _SANDBOX_DENIAL_PROBE,
        str(forbidden),
    ]
    control_profile = "(version 1)\n(allow default)"
    control_command = [
        str(sandbox_exec),
        "-p",
        control_profile,
        "--",
        *probe_arguments,
    ]
    denial_command = [
        str(sandbox_exec),
        "-p",
        profile,
        "--",
        *probe_arguments,
    ]
    for label, command, expected_returncode in (
        ("control", control_command, 15),
        ("denial", denial_command, 0),
    ):
        error_prefix = (
            "local_video_isolation_control_preflight_failed"
            if label == "control"
            else "local_video_isolation_denial_preflight_failed"
        )
        created_regular = False
        residual_observed = False
        try:
            completed = runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalVideoUnavailable(f"{error_prefix}:timeout") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise LocalVideoUnavailable(f"{error_prefix}:unavailable") from exc
        finally:
            created_regular = forbidden.is_file() and not forbidden.is_symlink()
            residual_observed = forbidden.exists() or forbidden.is_symlink()
            if residual_observed:
                try:
                    forbidden.unlink()
                except OSError as exc:
                    raise LocalVideoUnavailable(
                        "local_video_isolation_probe_cleanup_failed"
                    ) from exc
            if forbidden.exists() or forbidden.is_symlink():
                raise LocalVideoUnavailable(
                    "local_video_isolation_probe_cleanup_failed"
                )
        if completed.returncode != expected_returncode:
            raise LocalVideoUnavailable(f"{error_prefix}:exit_{completed.returncode}")
        if label == "control" and not created_regular:
            raise LocalVideoUnavailable(
                "local_video_isolation_control_preflight_failed:"
                "regular_write_not_observed"
            )
        if label == "denial" and residual_observed:
            raise LocalVideoUnavailable(
                "local_video_isolation_denial_preflight_failed:artifact_write_allowed"
            )
    return {
        "schema": "reel_factory.local_sandbox_preflight.v1",
        "enforcementBinary": str(Path(sandbox_exec).resolve()),
        "capabilityProbeExecutable": str(python),
        "capabilityProbeExecutableResolved": str(python_resolved),
        "capabilityProbeFingerprint": fingerprint(
            {"implementation": _SANDBOX_DENIAL_PROBE}
        ),
        "timeoutSeconds": _SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
        "controlProfileFingerprint": fingerprint({"profile": control_profile}),
        "controlProbeReturnCode": 15,
        "denialProbeReturnCode": 0,
        "profileFingerprint": fingerprint({"profile": profile}),
        "executionSucceeded": True,
        "unscopedWriteDenied": True,
        "tcpBindDenied": True,
        "udpConnectDenied": True,
        "tcpConnectDenied": True,
        "temporaryControlWritesExpected": 1,
        "temporaryControlWritesCleaned": True,
        "residualArtifactWrites": 0,
    }


def _sandbox_forbidden_write_probe_path() -> Path:
    return Path(tempfile.gettempdir()) / (
        f"creator_os_sandbox_probe_{os.getpid()}_{uuid.uuid4().hex}.tmp"
    )


def _preflight_allowed_sandbox_write(
    *,
    sandbox_exec: Path,
    profile: str,
    python_executable: Path,
    sandbox_root: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Prove a job-owned scratch write works immediately before generation."""

    probe_path = sandbox_root / f".allowed_write_probe_{uuid.uuid4().hex}.tmp"
    if probe_path.exists() or probe_path.is_symlink():
        raise LocalVideoUnavailable(
            "local_video_isolation_allowed_write_probe_collision"
        )
    command = [
        str(sandbox_exec),
        "-p",
        profile,
        "--",
        str(python_executable),
        "-B",
        "-I",
        "-S",
        "-E",
        "-c",
        _SANDBOX_ALLOWED_WRITE_PROBE,
        str(probe_path),
    ]
    residual = False
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalVideoUnavailable(
            "local_video_isolation_allowed_write_preflight_failed:timeout"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalVideoUnavailable(
            "local_video_isolation_allowed_write_preflight_failed:unavailable"
        ) from exc
    finally:
        residual = probe_path.exists() or probe_path.is_symlink()
        if residual:
            try:
                probe_path.unlink()
            except OSError as exc:
                raise LocalVideoUnavailable(
                    "local_video_isolation_allowed_write_probe_cleanup_failed"
                ) from exc
        if probe_path.exists() or probe_path.is_symlink():
            raise LocalVideoUnavailable(
                "local_video_isolation_allowed_write_probe_cleanup_failed"
            )
    if completed.returncode != 0:
        raise LocalVideoUnavailable(
            "local_video_isolation_allowed_write_preflight_failed:"
            f"exit_{completed.returncode}"
        )
    if residual:
        raise LocalVideoUnavailable(
            "local_video_isolation_allowed_write_preflight_failed:residual_artifact"
        )
    return {
        "schema": "reel_factory.local_sandbox_allowed_write_preflight.v1",
        "capabilityProbeExecutable": str(python_executable),
        "capabilityProbeFingerprint": fingerprint(
            {"implementation": _SANDBOX_ALLOWED_WRITE_PROBE}
        ),
        "profileFingerprint": fingerprint({"profile": profile}),
        "createSucceeded": True,
        "fsyncSucceeded": True,
        "deleteSucceeded": True,
        "residualArtifacts": 0,
    }


def _preflight_imageio_ffmpeg_discovery(
    *,
    sandbox_exec: Path,
    profile: str,
    python_executable: Path,
    environment: Mapping[str, str],
    expected_ffmpeg: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Prove the model runtime's actual encoder consumer resolves exact FFmpeg."""

    expected = expected_ffmpeg.expanduser()
    if not expected.is_file() or not os.access(expected, os.X_OK):
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:"
            "expected_ffmpeg_unavailable"
        )
    expected_resolved = expected.resolve(strict=True)
    if environment.get("IMAGEIO_FFMPEG_EXE") != str(expected):
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:"
            "environment_binding_mismatch"
        )
    command = [
        str(sandbox_exec),
        "-p",
        profile,
        "--",
        str(python_executable),
        "-B",
        "-I",
        "-E",
        "-c",
        _IMAGEIO_FFMPEG_DISCOVERY_PROBE,
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=_MEDIA_TOOL_DISCOVERY_TIMEOUT_SECONDS,
            env=dict(environment),
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:timeout"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:unavailable"
        ) from exc
    if completed.returncode != 0:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:"
            f"exit_{completed.returncode}"
        )
    observed = completed.stdout.strip()
    if observed != str(expected):
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:resolved_path_mismatch"
        )
    try:
        observed_resolved = Path(observed).expanduser().resolve(strict=True)
    except OSError as exc:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:"
            "resolved_path_unavailable"
        ) from exc
    if observed_resolved != expected_resolved:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:resolved_target_mismatch"
        )
    return {
        "schema": "reel_factory.local_media_tool_discovery_preflight.v1",
        "consumer": "imageio_ffmpeg.get_ffmpeg_exe",
        "consumerProbeFingerprint": fingerprint(
            {"implementation": _IMAGEIO_FFMPEG_DISCOVERY_PROBE}
        ),
        "pythonExecutable": str(python_executable),
        "expectedFfmpegExecutable": str(expected),
        "expectedFfmpegExecutableResolved": str(expected_resolved),
        "observedFfmpegExecutable": observed,
        "observedFfmpegExecutableResolved": str(observed_resolved),
        "environmentFingerprint": fingerprint(environment),
        "profileFingerprint": fingerprint({"profile": profile}),
        "timeoutSeconds": _MEDIA_TOOL_DISCOVERY_TIMEOUT_SECONDS,
        "discoverySucceeded": True,
    }


def _runtime_binding(request: LocalVideoRequest) -> Mapping[str, Any]:
    binding = request.arena_benchmark_binding or request.local_motion_admission
    runtime = binding.get("runtimeBinding") if isinstance(binding, Mapping) else None
    if not isinstance(runtime, Mapping):
        raise LocalVideoUnavailable("local_video_runtime_binding_missing")
    return runtime


def _bind_isolated_toolchain(
    request: LocalVideoRequest,
    *,
    base_command: list[str],
    environment: Mapping[str, str],
) -> list[str]:
    runtime = _runtime_binding(request)
    expected_launcher = str(runtime.get("pythonExecutable") or "")
    expected_resolved = str(runtime.get("pythonExecutableResolved") or "")
    if not expected_launcher or not expected_resolved or not base_command:
        raise LocalVideoUnavailable("local_video_python_runtime_binding_missing")
    launcher = str(base_command[0])
    if launcher != expected_launcher:
        raise LocalVideoUnavailable("local_video_python_runtime_binding_mismatch")
    if str(Path(launcher).expanduser().resolve()) != expected_resolved:
        raise LocalVideoUnavailable("local_video_python_runtime_target_mismatch")
    command = list(base_command)
    path = environment.get("PATH", "")
    if environment.get("IMAGEIO_FFMPEG_EXE") != str(
        runtime.get("ffmpegExecutable") or ""
    ):
        raise LocalVideoUnavailable("local_video_ffmpeg_runtime_binding_mismatch")
    for tool, field in (
        ("ffmpeg", "ffmpegExecutable"),
        ("ffprobe", "ffprobeExecutable"),
    ):
        resolved = shutil.which(tool, path=path)
        if resolved is None:
            raise LocalVideoUnavailable(f"local_video_{tool}_runtime_binding_mismatch")
        expected = {
            "executable": str(runtime.get(field) or ""),
            "sha256": str(runtime.get(f"{tool}Sha256") or ""),
            "size": runtime.get(f"{tool}Size"),
            "version": str(runtime.get(f"{tool}Version") or ""),
        }
        try:
            evidence = _tool_evidence_for_path(
                Path(resolved),
                expected=expected,
                environment=environment,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise LocalVideoUnavailable(
                f"local_video_{tool}_runtime_binding_mismatch"
            ) from exc
        if evidence != expected:
            raise LocalVideoUnavailable(f"local_video_{tool}_runtime_binding_mismatch")
    return command


def _tool_evidence_for_path(
    path: Path,
    *,
    expected: Mapping[str, Any],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or not os.access(resolved, os.X_OK)
    ):
        raise RuntimeError(f"local_video_runtime_tool_unsafe:{resolved.name}")
    stat = resolved.stat()
    content_evidence = {
        "executable": str(resolved),
        "sha256": _sha256_file(resolved),
        "size": stat.st_size,
    }
    expected_content = {
        "executable": str(expected.get("executable") or ""),
        "sha256": str(expected.get("sha256") or ""),
        "size": expected.get("size"),
    }
    if content_evidence != expected_content:
        raise RuntimeError(f"local_video_runtime_tool_content_mismatch:{resolved.name}")
    completed = subprocess.run(
        [str(resolved), "-version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=dict(environment),
    )
    first_line = (completed.stdout or completed.stderr).splitlines()
    if completed.returncode != 0 or not first_line:
        raise RuntimeError(f"local_video_runtime_tool_unreadable:{resolved.name}")
    evidence = {**content_evidence, "version": first_line[0].strip()}
    if evidence["version"] != str(expected.get("version") or ""):
        raise RuntimeError(f"local_video_runtime_tool_version_mismatch:{resolved.name}")
    return evidence


def _prepare_isolation_workspace(isolation: Mapping[str, Any]) -> None:
    root = Path(str(isolation.get("sandboxRoot") or "")).resolve()
    if root.exists():
        raise FileExistsError(f"local_video_isolation_workspace_collision:{root}")
    for relative in ("home", "tmp", "cache", "logs"):
        (root / relative).mkdir(parents=True, exist_ok=False)


def _build_execution_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    output: Path,
    python_executable: str | None,
) -> list[str]:
    """Build the exact partial-artifact command owned by the queue job."""

    partial = output.with_suffix(".partial" + output.suffix)
    partial_audio = output.with_suffix(output.suffix + ".audio.wav").with_suffix(
        ".partial.wav"
    )
    apply_request = replace(request, output_path=partial)
    command = build_local_video_command(
        apply_request, python_executable=python_executable
    )
    if spec.family == "longcat_avatar" and request.audio_mode != "none":
        command.extend(["--output-audio", str(partial_audio)])
    return command


def _build_wan_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    python: str,
    model_dir: Path,
    image: Path | None,
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
    if image is not None:
        command.extend(["--image", str(image)])
    if request.lora_path is not None:
        command.extend(
            [
                "--lora",
                str(Path(request.lora_path).expanduser().resolve()),
                str(request.lora_strength),
            ]
        )
    if "a14b" in spec.model_id:
        command.extend(["--trim-first-frames", "1"])
    return command


def _build_ltx_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    python: str,
    model_dir: Path,
    image: Path | None,
    output: Path,
    prompt: str,
) -> list[str]:
    frames = 8 * round(request.duration_seconds * spec.fps / 8) + 1
    base = [
        python,
        "-m",
        "ltx_pipelines_mlx.cli",
    ]
    common = [
        "--prompt",
        prompt,
        "--output",
        str(output),
        "--model",
        str(model_dir),
        "--gemma",
        str(ltx_text_encoder_dir(model_dir.parent)),
        "--seed",
        str(request.seed),
        "--quiet",
    ]
    if request.task == "video_retake":
        assert request.source_video_path is not None
        assert request.retake_start_frame is not None
        assert request.retake_end_frame is not None
        command = [
            *base,
            "retake",
            *common,
            "--video",
            str(Path(request.source_video_path).expanduser().resolve()),
            "--start",
            str(request.retake_start_frame),
            "--end",
            str(request.retake_end_frame),
            "--steps",
            str(_effective_steps(request, spec)),
        ]
        if request.audio_mode == "preserved":
            command.append("--no-regen-audio")
        return command
    if request.task == "video_extend":
        assert request.source_video_path is not None
        assert request.extend_frames is not None
        return [
            *base,
            "extend",
            *common,
            "--video",
            str(Path(request.source_video_path).expanduser().resolve()),
            "--extend-frames",
            str(request.extend_frames),
            "--direction",
            request.extend_direction,
            "--steps",
            str(_effective_steps(request, spec)),
        ]
    if request.task == "keyframe_interpolation":
        assert image is not None
        assert request.last_image_path is not None
        command = [
            *base,
            "keyframe",
            *common,
            "--start",
            str(image),
            "--end",
            str(Path(request.last_image_path).expanduser().resolve()),
            "--width",
            str(spec.width),
            "--height",
            str(spec.height),
            "--frames",
            str(frames),
            "--frame-rate",
            str(spec.fps),
            "--stage1-steps",
            str(_effective_steps(request, spec)),
            "--dev-transformer",
            "transformer-dev.safetensors",
            "--distilled-lora",
            "ltx-2.3-22b-distilled-lora-384.safetensors",
        ]
        return _append_ltx_memory_flags(command, request, include_tiling=False)

    subcommand = "a2v" if request.audio_mode == "source" else "generate"
    command = [
        *base,
        subcommand,
        *common,
        "--width",
        str(spec.width),
        "--height",
        str(spec.height),
        "--frames",
        str(frames),
        "--frame-rate",
        str(spec.fps),
    ]
    if image is not None:
        command.extend(["--image", str(image)])
    if subcommand == "a2v":
        assert request.audio_path is not None
        command.extend(
            ["--audio", str(Path(request.audio_path).expanduser().resolve())]
        )
        command.extend(["--stage1-steps", str(_effective_steps(request, spec))])
    elif spec.pipeline == "distilled":
        command.extend(["--distilled"])
        if request.steps is not None:
            command.extend(["--stage1-steps", str(request.steps)])
    else:
        command.extend(
            [
                "--two-stages-hq",
                "--stage1-steps",
                str(request.steps or spec.default_steps),
                "--stage2-steps",
                "3",
            ]
        )
    if request.lora_path is not None:
        command.extend(
            [
                "--lora",
                str(Path(request.lora_path).expanduser().resolve()),
                str(request.lora_strength),
            ]
        )
    if request.last_image_path is not None:
        command.extend(
            [
                "--image",
                str(Path(request.last_image_path).expanduser().resolve()),
                str(frames - 1),
                "1.0",
            ]
        )
    return _append_ltx_memory_flags(
        command, request, include_tiling=subcommand == "generate"
    )


def _append_ltx_memory_flags(
    command: list[str],
    request: LocalVideoRequest,
    *,
    include_tiling: bool,
) -> list[str]:
    if request.low_ram:
        command.append("--low-ram")
    if include_tiling and request.tile_frames > 1:
        command.extend(["--tile-frames", str(request.tile_frames)])
    if include_tiling and request.tile_spatial > 1:
        command.extend(["--tile-spatial", str(request.tile_spatial)])
    return command


def _effective_steps(request: LocalVideoRequest, spec: LocalVideoModelSpec) -> int:
    if request.steps is not None:
        return request.steps
    if spec.family == "ltx_2" and (
        request.audio_mode == "source"
        or request.task
        in {
            "keyframe_interpolation",
            "video_retake",
            "video_extend",
        }
    ):
        return 30
    return spec.default_steps


def _build_longcat_command(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    python: str,
    model_dir: Path,
    runtime_root: Path,
    output: Path,
    prompt: str,
) -> list[str]:
    assert request.image_path is not None
    assert request.audio_path is not None
    frames = 4 * round(request.duration_seconds * spec.fps / 4) + 1
    return [
        python,
        str(Path(__file__).with_name("longcat_mlx_generate.py")),
        "--runtime-root",
        str(runtime_root),
        "--weights-root",
        str(model_dir.parent),
        "--image",
        str(Path(request.image_path).expanduser().resolve()),
        "--audio",
        str(Path(request.audio_path).expanduser().resolve()),
        "--prompt",
        prompt,
        "--width",
        str(spec.width),
        "--height",
        str(spec.height),
        "--num-frames",
        str(frames),
        "--fps",
        str(spec.fps),
        "--seed",
        str(request.seed),
        "--output-path",
        str(output),
    ]


def _validate_request_inputs(
    request: LocalVideoRequest, spec: LocalVideoModelSpec
) -> None:
    if request.seed < 0:
        raise ValueError("local video requires an explicit non-negative seed")
    steps = _effective_steps(request, spec)
    if steps < 4 or steps > 60:
        raise ValueError("local video steps must be between 4 and 60")
    if not 1 <= request.tile_frames <= 8:
        raise ValueError("local video temporal tiles must be between 1 and 8")
    if not 1 <= request.tile_spatial <= 4:
        raise ValueError("local video spatial tiles must be between 1 and 4")
    prompt = " ".join(str(request.prompt or "").split())
    if len(prompt) < 20:
        raise ValueError(
            "local video motion prompt must contain at least 20 characters"
        )
    if request.image_path is not None:
        image = Path(request.image_path).expanduser().resolve()
        if not image.is_file():
            raise FileNotFoundError(f"local video input image not found: {image}")
    if request.source_video_path is not None:
        source_video = Path(request.source_video_path).expanduser().resolve()
        if not source_video.is_file():
            raise FileNotFoundError(
                f"local video source video not found: {source_video}"
            )
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
    if request.lora_path is not None:
        lora = Path(request.lora_path).expanduser().resolve()
        if not lora.is_file() or lora.suffix != ".safetensors":
            raise FileNotFoundError("local video LoRA must be a .safetensors file")
        if not 0.0 < request.lora_strength <= 2.0:
            raise ValueError(
                "local video LoRA strength must be greater than 0 and at most 2"
            )
        verify_local_lora(lora, model_id=request.model_id)
    if spec.family == "wan_2" and request.audio_mode != "none":
        raise ValueError("local Wan does not support audio; select a local LTX model")
    if spec.family == "ltx_2":
        if request.audio_mode == "none":
            raise ValueError(
                "local LTX 2.3 produces joint audio/video; choose generated, source, "
                "or preserved audio explicitly"
            )
        if request.audio_mode == "preserved" and request.task != "video_retake":
            raise ValueError("preserved audio is supported only for video_retake")
        if request.task == "video_retake":
            if request.source_video_path is None:
                raise ValueError("video_retake requires --source-video")
            if request.retake_start_frame is None or request.retake_end_frame is None:
                raise ValueError("video_retake requires start and end latent frames")
            if not (0 <= request.retake_start_frame < request.retake_end_frame):
                raise ValueError("video_retake frame range is invalid")
            if request.audio_mode not in {"generated", "preserved"}:
                raise ValueError(
                    "video_retake audio must be regenerated or explicitly preserved"
                )
        elif request.task == "video_extend":
            if request.source_video_path is None:
                raise ValueError("video_extend requires --source-video")
            if request.extend_frames is None or not 1 <= request.extend_frames <= 24:
                raise ValueError("video_extend requires 1-24 latent --extend-frames")
            if request.audio_mode != "generated":
                raise ValueError("video_extend requires generated continuation audio")
        elif request.source_video_path is not None:
            raise ValueError("--source-video requires video_retake or video_extend")
        if request.task in {"video_retake", "video_extend", "keyframe_interpolation"}:
            if request.lora_path is not None:
                raise ValueError(f"{request.task} does not accept a Creator OS LoRA")
        if (
            request.task == "keyframe_interpolation"
            and request.audio_mode != "generated"
        ):
            raise ValueError("keyframe_interpolation requires generated joint audio")
    if spec.family == "longcat_avatar":
        if request.task != "audio_image_to_video":
            raise ValueError("LongCat Avatar requires audio_image_to_video task")
        if request.audio_mode != "source" or request.audio_path is None:
            raise ValueError("LongCat Avatar requires explicit source audio")
        if request.last_image_path is not None or request.lora_path is not None:
            raise ValueError("LongCat Avatar does not accept last-image or LoRA inputs")
        if request.steps is not None and request.steps != spec.default_steps:
            raise ValueError(
                f"LongCat Avatar uses exactly {spec.default_steps} DMD steps"
            )


def _preflight_local_inputs(request: LocalVideoRequest) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "images": [],
        "sourceAudio": None,
        "sourceVideo": None,
    }
    for role, raw_path in (
        ("image", request.image_path),
        ("lastImage", request.last_image_path),
    ):
        if raw_path is None:
            continue
        path = Path(raw_path).expanduser().resolve()
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        try:
            payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
            stream = (payload.get("streams") or [])[0]
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"local_video_{role}_unreadable") from exc
        if stream.get("codec_type") != "video" or width <= 0 or height <= 0:
            raise ValueError(f"local_video_{role}_unreadable")
        evidence["images"].append(
            {
                "role": role,
                "path": str(path),
                "sha256": _sha256_file(path),
                "codec": stream.get("codec_name"),
                "width": width,
                "height": height,
            }
        )
    if request.audio_mode == "source":
        assert request.audio_path is not None
        path = Path(request.audio_path).expanduser().resolve()
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type,codec_name,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        try:
            payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
            stream = (payload.get("streams") or [])[0]
            raw_duration = stream.get("duration") or (payload.get("format") or {}).get(
                "duration"
            )
            if raw_duration is None:
                raise ValueError("source audio duration missing")
            duration = float(str(raw_duration))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("local_video_source_audio_unreadable") from exc
        if stream.get("codec_type") != "audio" or duration <= 0:
            raise ValueError("local_video_source_audio_unreadable")
        if duration + 0.05 < request.duration_seconds:
            raise ValueError(
                "local_video_source_audio_too_short:"
                f"required={request.duration_seconds}:observed={duration:.3f}"
            )
        evidence["sourceAudio"] = {
            "path": str(path),
            "sha256": _sha256_file(path),
            "codec": stream.get("codec_name"),
            "durationSeconds": duration,
            "minimumRequiredSeconds": request.duration_seconds,
            "policy": "trim_only_no_padding",
        }
    if request.source_video_path is not None:
        path = Path(request.source_video_path).expanduser().resolve()
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        try:
            payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
            streams = payload.get("streams") or []
            video = next(
                value for value in streams if value.get("codec_type") == "video"
            )
            audio_streams = [
                value for value in streams if value.get("codec_type") == "audio"
            ]
            numerator, denominator = str(video.get("avg_frame_rate") or "").split(
                "/", 1
            )
            fps = float(numerator) / float(denominator)
            duration = float(str((payload.get("format") or {}).get("duration")))
            width = int(video.get("width") or 0)
            height = int(video.get("height") or 0)
        except (
            StopIteration,
            TypeError,
            ValueError,
            ZeroDivisionError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("local_video_source_video_unreadable") from exc
        if width <= 0 or height <= 0 or duration <= 0 or fps <= 0:
            raise ValueError("local_video_source_video_unreadable")
        if len(audio_streams) != 1:
            raise ValueError(
                "local_video_source_video_requires_exactly_one_audio_stream"
            )
        latent_frame_count = max(1, int((duration * fps + 7) // 8))
        if (
            request.task == "video_retake"
            and request.retake_end_frame is not None
            and request.retake_end_frame > latent_frame_count
        ):
            raise ValueError(
                "local_video_retake_range_exceeds_source:"
                f"end={request.retake_end_frame}:latentFrames={latent_frame_count}"
            )
        evidence["sourceVideo"] = {
            "path": str(path),
            "sha256": _sha256_file(path),
            "codec": video.get("codec_name"),
            "width": width,
            "height": height,
            "fps": fps,
            "durationSeconds": duration,
            "latentFrameCount": latent_frame_count,
            "audioCodec": audio_streams[0].get("codec_name"),
        }
    return evidence


def _custom_model_status(spec: LocalVideoModelSpec, directory: Path) -> dict[str, Any]:
    expected = spec.directory(directory.parent)
    if directory != expected:
        return {
            "modelId": spec.model_id,
            "modelDir": str(directory),
            "runtimeModelDir": str(runtime_model_dir(spec, directory)),
            "manifest": None,
            "manifestSha256": None,
            "ready": False,
            "issues": [
                "custom_model_directory_layout_mismatch:"
                f"expected_basename={expected.name}:actual_basename={directory.name}"
            ],
        }
    return model_status(spec.model_id, models_root=directory.parent, deep=True)


def _validate_video(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_duration_seconds: float | None,
    minimum_duration_seconds: float | None,
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
    if (
        expected_duration_seconds is not None
        and abs(duration - expected_duration_seconds) > 0.35
    ):
        raise RuntimeError("local_video_output_duration_mismatch")
    if minimum_duration_seconds is not None and duration <= minimum_duration_seconds:
        raise RuntimeError("local_video_output_extension_missing")
    return payload


def _output_expectations(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    preflight: dict[str, Any],
) -> _OutputExpectations:
    source = preflight.get("sourceVideo")
    if isinstance(source, dict):
        duration = float(source["durationSeconds"])
        return {
            "width": int(source["width"]),
            "height": int(source["height"]),
            "fps": int(round(float(source["fps"]))),
            "duration": duration if request.task == "video_retake" else None,
            "minimumDuration": duration if request.task == "video_extend" else None,
        }
    return {
        "width": spec.width,
        "height": spec.height,
        "fps": spec.fps,
        "duration": request.duration_seconds,
        "minimumDuration": None,
    }


def _extract_audio_sidecar(video: Path, output: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",
            "-acodec",
            "pcm_s16le",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10 * 60,
    )
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(
            "local_video_audio_sidecar_extract_failed: "
            + (completed.stderr[-2000:] or completed.stdout[-2000:])
        )


def _optional_input(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def _optional_lora(
    path: Path | None, strength: float, *, model_id: str
) -> dict[str, object] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    registration = verify_local_lora(resolved, model_id=model_id)
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "strength": strength,
        "registration": registration,
    }


def _python_environment_name(family: str) -> str:
    return {
        "wan_2": "CREATOR_OS_LOCAL_MLX_PYTHON",
        "ltx_2": "CREATOR_OS_LOCAL_LTX_PYTHON",
        "longcat_avatar": "CREATOR_OS_LOCAL_LONGCAT_PYTHON",
    }[family]


def _generation_job(
    request: LocalVideoRequest,
    *,
    spec: LocalVideoModelSpec,
    capability: dict[str, Any],
    command: list[str],
    output: Path,
    execution_isolation: Mapping[str, Any],
) -> LocalGenerationJob:
    execution_binding = _validate_execution_binding(request, capability=capability)
    current_model_status = model_status(request.model_id, deep=True)
    deep_receipt = current_model_status.get("deepVerificationReceipt")
    if (
        not isinstance(deep_receipt, Mapping)
        or execution_binding.get("modelDeepVerificationFingerprint")
        != deep_receipt.get("verificationFingerprint")
        or execution_binding.get("runtimeBinding") != deep_receipt.get("runtimeBinding")
        or execution_binding.get("runtimeBindingFingerprint")
        != deep_receipt.get("runtimeBindingFingerprint")
    ):
        raise LocalVideoUnavailable("local_video_execution_runtime_binding_drift")
    router_promotion_linkage = None
    if execution_binding.get("schema") == (
        "reel_factory.campaign_local_motion_binding.v1"
    ):
        router_promotion_linkage = {
            "routerDecisionId": execution_binding["routerDecisionId"],
            "routerDecisionFingerprint": execution_binding["routerDecisionFingerprint"],
            "capabilityCohort": execution_binding["capabilityCohort"],
            "cohortKeyFingerprint": execution_binding["cohortKeyFingerprint"],
            "arenaSummaryFingerprint": execution_binding["arenaSummaryFingerprint"],
            "arenaPlanFingerprint": execution_binding["arenaPlanFingerprint"],
            "admissionFingerprint": execution_binding["admissionFingerprint"],
            "selectedModelFingerprint": execution_binding["selectedModelFingerprint"],
            "modelDeepVerificationFingerprint": execution_binding[
                "modelDeepVerificationFingerprint"
            ],
            "promotionApprovalEventId": execution_binding["promotionApprovalEventId"],
            "promotionApprovalEventHash": execution_binding[
                "promotionApprovalEventHash"
            ],
            "promotionHardwareFingerprint": execution_binding[
                "promotionHardwareFingerprint"
            ],
            "promotionEvidenceFingerprint": execution_binding[
                "promotionEvidenceFingerprint"
            ],
            "promotionBenchmarkIdsFingerprint": execution_binding[
                "promotionBenchmarkIdsFingerprint"
            ],
        }
    manifest_sha = str(capability.get("model", {}).get("manifestSha256") or "")
    inputs = {
        "image": _optional_input(request.image_path),
        "audio": _optional_input(request.audio_path),
        "lastImage": _optional_input(request.last_image_path),
        "sourceVideo": _optional_input(request.source_video_path),
        "lora": _optional_lora(
            request.lora_path, request.lora_strength, model_id=request.model_id
        ),
        "executionBinding": execution_binding,
    }
    input_sha = fingerprint(inputs)
    cohort_input_sha = fingerprint(
        {
            "image": inputs["image"],
            "audio": inputs["audio"],
            "lastImage": inputs["lastImage"],
            "sourceVideo": inputs["sourceVideo"],
        }
    )
    params = {
        "command": command,
        "outputPath": str(output),
        "task": request.task,
        "durationSeconds": request.duration_seconds,
        "seed": request.seed,
        "executionContext": request.execution_context,
        "executionBindingFingerprint": execution_binding["bindingFingerprint"],
        "executionIsolationFingerprint": execution_isolation["isolationFingerprint"],
    }
    job_id = (
        "local_video_"
        + fingerprint({"modelId": spec.model_id, "input": input_sha, "params": params})[
            :24
        ]
    )
    requested_memory = max(24 * 1024**3, int(spec.estimated_bytes * 1.35))
    return LocalGenerationJob.create(
        job_id=job_id,
        model_id=spec.model_id,
        model_revision=spec.revision,
        model_manifest_sha256=manifest_sha,
        task_kind=request.task,
        input_sha256=input_sha,
        requested_memory_bytes=requested_memory,
        params=params,
        cohort={
            "sourceInputSha256": cohort_input_sha,
            "task": request.task,
            "prompt": " ".join(request.prompt.split()),
            "durationSeconds": request.duration_seconds,
            "seed": request.seed,
            "audioMode": request.audio_mode,
            "executionContext": request.execution_context,
            "executionBindingFingerprint": execution_binding["bindingFingerprint"],
            "executionIsolationFingerprint": execution_isolation[
                "isolationFingerprint"
            ],
        },
        owned_artifact_paths=(
            output,
            output.with_suffix(".partial" + output.suffix),
            output.with_suffix(output.suffix + ".local_video.json"),
            output.with_suffix(output.suffix + ".audio.wav"),
            output.with_suffix(output.suffix + ".audio.wav").with_suffix(
                ".partial.wav"
            ),
            Path(str(execution_isolation["sandboxRoot"])),
        ),
        benchmark_recipe=request.benchmark_recipe,
        analyzer_registry=request.analyzer_registry,
        creator_identity_profile=request.creator_identity_profile,
        content_intent=request.content_intent,
        runtime_binding=(
            execution_binding.get("runtimeBinding")
            if isinstance(execution_binding.get("runtimeBinding"), Mapping)
            else None
        ),
        license_policy=(
            execution_binding.get("licensePolicy")
            if isinstance(execution_binding.get("licensePolicy"), Mapping)
            else None
        ),
        router_promotion_linkage=router_promotion_linkage,
    )


def _validate_execution_binding(
    request: LocalVideoRequest,
    *,
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    if request.execution_context is None:
        raise LocalVideoUnavailable("local_video_execution_context_required")
    if request.model_dir is not None:
        raise LocalVideoUnavailable(
            "local_video_custom_model_dir_forbidden_for_bound_execution"
        )
    if request.execution_context == "campaign_generation":
        if request.arena_benchmark_binding is not None:
            raise LocalVideoUnavailable("local_video_mixed_execution_evidence")
        return _validate_campaign_admission(request, capability=capability)
    if request.execution_context == "arena_benchmark":
        if request.local_motion_admission is not None:
            raise LocalVideoUnavailable("local_video_mixed_execution_evidence")
        return _validate_arena_benchmark_binding(request)
    raise LocalVideoUnavailable("local_video_execution_context_invalid")


def _execution_capability_fingerprint(capability: Mapping[str, Any]) -> str:
    model = capability.get("model")
    runtime = capability.get("runtime")
    model_payload = model if isinstance(model, Mapping) else {}
    runtime_payload = runtime if isinstance(runtime, Mapping) else {}
    deep = model_payload.get("deepVerificationReceipt")
    deep_payload = deep if isinstance(deep, Mapping) else {}
    return fingerprint(
        {
            "modelId": capability.get("modelId"),
            "ready": capability.get("ready"),
            "manifestSha256": model_payload.get("manifestSha256"),
            "deepVerified": model_payload.get("deepVerified"),
            "deepVerificationFingerprint": deep_payload.get("verificationFingerprint"),
            "runtimeId": runtime_payload.get("runtimeId"),
            "runtimeRepository": runtime_payload.get("repository"),
            "runtimeRevision": runtime_payload.get("observedRevision"),
            "runtimeEnvironment": runtime_payload.get("resolvedEnvironment"),
        }
    )


def _validate_campaign_admission(
    request: LocalVideoRequest,
    *,
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    admission = request.local_motion_admission
    if not isinstance(admission, Mapping):
        raise LocalVideoUnavailable("local_motion_admission_required")
    payload = dict(admission)
    expected_keys = {
        "schema",
        "routerDecision",
        "arenaSummary",
        "evidenceRecords",
        "inputFingerprints",
        "resourceSnapshot",
        "admissionFingerprint",
    }
    if set(payload) != expected_keys or payload.get("schema") != (
        "campaign_factory.local_motion_admission.v1"
    ):
        raise LocalVideoUnavailable("local_motion_admission_schema_invalid")
    claimed = _required_sha256(
        payload.get("admissionFingerprint"), "local_motion_admission_fingerprint"
    )
    core = dict(payload)
    core.pop("admissionFingerprint")
    if fingerprint(core) != claimed:
        raise LocalVideoUnavailable("local_motion_admission_fingerprint_mismatch")

    raw_decision = payload.get("routerDecision")
    if not isinstance(raw_decision, Mapping):
        raise LocalVideoUnavailable("local_motion_router_decision_missing")
    decision = dict(raw_decision)
    try:
        validate_local_model_router_decision(decision)
    except ValueError as exc:
        raise LocalVideoUnavailable("local_motion_router_decision_invalid") from exc
    decision_core = dict(decision)
    decision_claimed = _required_sha256(
        decision_core.pop("decisionFingerprint", None),
        "local_motion_router_decision_fingerprint",
    )
    if fingerprint(decision_core) != decision_claimed:
        raise LocalVideoUnavailable("local_motion_router_decision_fingerprint_mismatch")
    if decision.get("selectedModelId") != request.model_id:
        raise LocalVideoUnavailable("local_motion_selected_model_mismatch")
    if (
        decision.get("paidProviderFallbackAllowed") is not False
        or decision.get("legacyLocalMotionFallbackAllowed") is not False
    ):
        raise LocalVideoUnavailable("local_motion_router_fallback_not_closed")
    decision_request = decision.get("request")
    if not isinstance(decision_request, Mapping):
        raise LocalVideoUnavailable("local_motion_router_request_missing")

    selected = [
        candidate
        for candidate in decision.get("consideredCandidates", [])
        if isinstance(candidate, Mapping)
        and candidate.get("modelId") == request.model_id
    ]
    if len(selected) != 1:
        raise LocalVideoUnavailable("local_motion_selected_candidate_not_exactly_once")
    candidate = selected[0]
    if (
        candidate.get("exclusions") != []
        or not isinstance(candidate.get("score"), (int, float))
        or isinstance(candidate.get("score"), bool)
        or candidate.get("modelFingerprint") != decision.get("selectedModelFingerprint")
    ):
        raise LocalVideoUnavailable("local_motion_selected_candidate_ineligible")

    winning = decision.get("winningEvidence")
    summary = payload.get("arenaSummary")
    if not isinstance(winning, Mapping) or not isinstance(summary, Mapping):
        raise LocalVideoUnavailable("local_motion_arena_evidence_missing")
    if set(summary) != {
        "summaryId",
        "summaryFingerprint",
        "planId",
        "planFingerprint",
        "purpose",
    }:
        raise LocalVideoUnavailable("local_motion_arena_summary_binding_invalid")
    summary_fingerprint = _required_sha256(
        summary.get("summaryFingerprint"), "local_motion_arena_summary_fingerprint"
    )
    plan_fingerprint = _required_sha256(
        summary.get("planFingerprint"), "local_motion_arena_plan_fingerprint"
    )
    if (
        summary.get("purpose") != "promotion_eligible"
        or winning.get("arenaSummaryFingerprint") != summary_fingerprint
        or candidate.get("arenaSummaryFingerprint") != summary_fingerprint
        or not str(summary.get("summaryId") or "").strip()
        or not str(summary.get("planId") or "").strip()
    ):
        raise LocalVideoUnavailable("local_motion_arena_summary_binding_mismatch")
    for field in ("benchmarkIds", "matchedArenaSampleIds", "validArenaSampleIds"):
        values = winning.get(field)
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(str(value) for value in values))
        ):
            raise LocalVideoUnavailable(f"local_motion_{field}_invalid")
    cohort_key = winning.get("cohortKey")
    expected_cohort_key = {
        field: decision_request.get(field)
        for field in (
            "creatorId",
            "identityProfileId",
            "identityProfileFingerprint",
            "contentIntentId",
            "contentIntentFingerprint",
            "taskKind",
            "capabilityCohort",
        )
    }
    approval = winning.get("promotionApproval")
    if (
        not isinstance(cohort_key, Mapping)
        or dict(cohort_key) != expected_cohort_key
        or candidate.get("capabilityCohort") != decision_request.get("capabilityCohort")
        or candidate.get("benchmarkIds") != winning.get("benchmarkIds")
        or candidate.get("promotionApproval") != approval
        or not isinstance(approval, Mapping)
        or approval.get("candidateModelFingerprint")
        != decision.get("selectedModelFingerprint")
        or approval.get("taskKind") != request.task
        or approval.get("candidateBenchmarkIds") != winning.get("benchmarkIds")
    ):
        raise LocalVideoUnavailable("local_motion_promotion_cohort_mismatch")
    promotion_approval_event_hash = _required_sha256(
        approval.get("approvalEventHash"),
        "local_motion_promotion_approval_event_hash",
    )
    promotion_hardware_fingerprint = _required_sha256(
        approval.get("hardwareFingerprint"),
        "local_motion_promotion_hardware_fingerprint",
    )
    promotion_evidence_fingerprint = _required_sha256(
        approval.get("evidenceFingerprint"),
        "local_motion_promotion_evidence_fingerprint",
    )
    promotion_event_id = str(approval.get("approvalEventId") or "").strip()
    decision_id = str(decision.get("decisionId") or "").strip()
    if not promotion_event_id or not decision_id:
        raise LocalVideoUnavailable("local_motion_routing_identity_missing")

    records = payload.get("evidenceRecords")
    if not isinstance(records, Mapping) or set(records) != {
        "creatorIdentityProfile",
        "contentIntent",
        "executionPolicy",
        "benchmarkRecipe",
        "analyzerRegistry",
    }:
        raise LocalVideoUnavailable("local_motion_evidence_record_set_invalid")
    identity = records.get("creatorIdentityProfile")
    intent = records.get("contentIntent")
    recipe = records.get("benchmarkRecipe")
    registry = records.get("analyzerRegistry")
    if not isinstance(identity, Mapping):
        raise LocalVideoUnavailable("local_motion_evidence_record_invalid")
    if not isinstance(intent, Mapping):
        raise LocalVideoUnavailable("local_motion_evidence_record_invalid")
    if not isinstance(recipe, Mapping):
        raise LocalVideoUnavailable("local_motion_evidence_record_invalid")
    if not isinstance(registry, Mapping):
        raise LocalVideoUnavailable("local_motion_evidence_record_invalid")
    if (
        identity.get("profileId") != decision_request.get("identityProfileId")
        or fingerprint(identity) != decision_request.get("identityProfileFingerprint")
        or intent.get("intentId") != decision_request.get("contentIntentId")
        or fingerprint(intent) != decision_request.get("contentIntentFingerprint")
        or decision_request.get("taskKind") != request.task
    ):
        raise LocalVideoUnavailable("local_motion_evidence_router_binding_mismatch")
    if request.benchmark_recipe is None or dict(request.benchmark_recipe) != dict(
        recipe
    ):
        raise LocalVideoUnavailable("local_motion_benchmark_recipe_mismatch")
    if request.analyzer_registry is None or dict(request.analyzer_registry) != dict(
        registry
    ):
        raise LocalVideoUnavailable("local_motion_analyzer_registry_mismatch")

    input_fingerprints = payload.get("inputFingerprints")
    exact_inputs: list[str] = []
    for value in (
        _optional_input_sha256(request.image_path),
        _optional_input_sha256(request.audio_path),
        _optional_input_sha256(request.last_image_path),
        _optional_input_sha256(request.source_video_path),
    ):
        if value is not None and value not in exact_inputs:
            exact_inputs.append(value)
    if (
        input_fingerprints != exact_inputs
        or list(intent.get("sourceAssetFingerprints") or []) != exact_inputs
        or list(recipe.get("inputFingerprints") or []) != exact_inputs
    ):
        raise LocalVideoUnavailable("local_motion_input_fingerprint_mismatch")

    resource = payload.get("resourceSnapshot")
    resource_hardware = (
        resource.get("hardware") if isinstance(resource, Mapping) else None
    )
    current_hardware = hardware_identity()
    if (
        not isinstance(resource, Mapping)
        or resource.get("schema")
        != "campaign_factory.local_motion_resource_snapshot.v1"
        or resource.get("routerAvailableMemoryBytes")
        != decision_request.get("availableMemoryBytes")
        or not isinstance(resource_hardware, Mapping)
        or dict(resource_hardware) != current_hardware
        or current_hardware.get("fingerprint") != promotion_hardware_fingerprint
    ):
        raise LocalVideoUnavailable("local_motion_resource_snapshot_mismatch")

    model = capability.get("model")
    if not isinstance(model, Mapping):
        raise LocalVideoUnavailable("local_motion_model_capability_missing")
    deep = model.get("deepVerificationReceipt")
    if (
        model.get("ready") is not True
        or model.get("deepVerified") is not True
        or not isinstance(deep, Mapping)
    ):
        raise LocalVideoUnavailable("local_motion_model_not_deep_verified")
    deep_claimed = _required_sha256(
        deep.get("verificationFingerprint"),
        "local_motion_model_deep_verification_fingerprint",
    )
    deep_core = dict(deep)
    deep_core.pop("verificationFingerprint", None)
    if (
        fingerprint(deep_core) != deep_claimed
        or deep.get("modelId") != request.model_id
        or deep.get("manifestSha256") != model.get("manifestSha256")
        or deep.get("providerCalls") != 0
        or deep.get("paidGeneration") is not False
    ):
        raise LocalVideoUnavailable("local_motion_model_deep_verification_invalid")
    runtime_binding = winning.get("runtimeBinding")
    runtime_binding_fingerprint = _required_sha256(
        winning.get("runtimeBindingFingerprint"),
        "local_motion_runtime_binding_fingerprint",
    )
    license_policy = winning.get("licensePolicy")
    license_policy_fingerprint = _required_sha256(
        winning.get("licensePolicyFingerprint"),
        "local_motion_license_policy_fingerprint",
    )
    if (
        not isinstance(runtime_binding, Mapping)
        or fingerprint(runtime_binding) != runtime_binding_fingerprint
        or candidate.get("runtimeBinding") != runtime_binding
        or candidate.get("runtimeBindingFingerprint") != runtime_binding_fingerprint
        or deep.get("runtimeBinding") != runtime_binding
        or deep.get("runtimeBindingFingerprint") != runtime_binding_fingerprint
        or not isinstance(license_policy, Mapping)
        or fingerprint(license_policy) != license_policy_fingerprint
        or candidate.get("licensePolicy") != license_policy
        or candidate.get("licensePolicyFingerprint") != license_policy_fingerprint
        or license_policy.get("commercialUseAllowed") is not True
    ):
        raise LocalVideoUnavailable("local_motion_runtime_license_binding_mismatch")
    manifest = model.get("manifest")
    if not isinstance(manifest, Mapping):
        raise LocalVideoUnavailable("local_motion_model_manifest_missing")
    if manifest.get("licenseId") != license_policy.get("licenseId") or manifest.get(
        "commercialRevenueLimitUsd"
    ) != license_policy.get("commercialRevenueLimitUsd"):
        raise LocalVideoUnavailable("local_motion_model_license_drift")
    current_model_fingerprint = fingerprint(
        {
            "modelId": request.model_id,
            "modelRevision": str(manifest.get("revision") or ""),
            "modelManifestSha256": str(model.get("manifestSha256") or ""),
        }
    )
    if current_model_fingerprint != decision.get(
        "selectedModelFingerprint"
    ) or current_model_fingerprint != candidate.get("modelFingerprint"):
        raise LocalVideoUnavailable("local_motion_model_fingerprint_drift")

    binding_core = {
        "schema": "reel_factory.campaign_local_motion_binding.v1",
        "admissionFingerprint": claimed,
        "routerDecisionId": decision_id,
        "routerDecisionFingerprint": decision_claimed,
        "capabilityCohort": decision_request.get("capabilityCohort"),
        "cohortKey": dict(cohort_key),
        "cohortKeyFingerprint": fingerprint(cohort_key),
        "arenaSummaryFingerprint": summary_fingerprint,
        "arenaPlanFingerprint": plan_fingerprint,
        "selectedModelFingerprint": current_model_fingerprint,
        "modelDeepVerificationFingerprint": deep_claimed,
        "runtimeBinding": dict(runtime_binding),
        "runtimeBindingFingerprint": runtime_binding_fingerprint,
        "licensePolicy": dict(license_policy),
        "licensePolicyFingerprint": license_policy_fingerprint,
        "benchmarkRecipeFingerprint": fingerprint(recipe),
        "analyzerRegistryFingerprint": fingerprint(registry),
        "promotionApprovalEventId": promotion_event_id,
        "promotionApprovalEventHash": promotion_approval_event_hash,
        "promotionHardwareFingerprint": promotion_hardware_fingerprint,
        "promotionEvidenceFingerprint": promotion_evidence_fingerprint,
        "promotionBenchmarkIdsFingerprint": fingerprint(
            {"candidateBenchmarkIds": approval["candidateBenchmarkIds"]}
        ),
        "inputFingerprints": exact_inputs,
        "providerCalls": 0,
        "paidGeneration": False,
    }
    return {**binding_core, "bindingFingerprint": fingerprint(binding_core)}


def _validate_arena_benchmark_binding(request: LocalVideoRequest) -> dict[str, Any]:
    raw = request.arena_benchmark_binding
    if not isinstance(raw, Mapping):
        raise LocalVideoUnavailable("arena_benchmark_binding_required")
    binding = dict(raw)
    expected_keys = {
        "schema",
        "sampleId",
        "blindedCandidateId",
        "sourceSha256",
        "identityProfileId",
        "identityProfileFingerprint",
        "contentIntentId",
        "contentIntentFingerprint",
        "benchmarkRecipeFingerprint",
        "analyzerRegistryFingerprint",
        "modelDeepVerificationFingerprint",
        "runtimeBinding",
        "runtimeBindingFingerprint",
        "licensePolicy",
        "licensePolicyFingerprint",
        "providerCalls",
        "productionWritesAllowed",
        "bindingFingerprint",
    }
    if set(binding) != expected_keys or binding.get("schema") != (
        "reel_factory.arena_benchmark_execution.v1"
    ):
        raise LocalVideoUnavailable("arena_benchmark_binding_schema_invalid")
    claimed = _required_sha256(
        binding.get("bindingFingerprint"), "arena_benchmark_binding_fingerprint"
    )
    core = dict(binding)
    core.pop("bindingFingerprint")
    if fingerprint(core) != claimed:
        raise LocalVideoUnavailable("arena_benchmark_binding_fingerprint_mismatch")
    if (
        binding.get("providerCalls") != 0
        or binding.get("productionWritesAllowed") is not False
    ):
        raise LocalVideoUnavailable("arena_benchmark_external_activity_not_closed")
    if (
        _optional_input_sha256(request.image_path or request.source_video_path)
        != binding.get("sourceSha256")
        or request.benchmark_recipe is None
        or fingerprint(request.benchmark_recipe)
        != binding.get("benchmarkRecipeFingerprint")
        or request.analyzer_registry is None
        or fingerprint(request.analyzer_registry)
        != binding.get("analyzerRegistryFingerprint")
    ):
        raise LocalVideoUnavailable("arena_benchmark_binding_mismatch")
    runtime_binding = binding.get("runtimeBinding")
    runtime_binding_fingerprint = binding.get("runtimeBindingFingerprint")
    license_policy = binding.get("licensePolicy")
    license_policy_fingerprint = binding.get("licensePolicyFingerprint")
    if (
        not isinstance(runtime_binding, Mapping)
        or fingerprint(runtime_binding) != runtime_binding_fingerprint
        or not isinstance(license_policy, Mapping)
        or fingerprint(license_policy) != license_policy_fingerprint
        or license_policy.get("commercialUseAllowed") is not True
    ):
        raise LocalVideoUnavailable("arena_runtime_license_binding_invalid")
    profile = request.creator_identity_profile
    intent = request.content_intent
    if not isinstance(profile, Mapping) or not isinstance(intent, Mapping):
        raise LocalVideoUnavailable("arena_identity_intent_records_required")
    if (
        profile.get("schema") != "creator_os.creator_identity_profile.v1"
        or intent.get("schema") != "creator_os.content_intent.v1"
        or profile.get("profileId") != binding.get("identityProfileId")
        or fingerprint(profile) != binding.get("identityProfileFingerprint")
        or intent.get("intentId") != binding.get("contentIntentId")
        or fingerprint(intent) != binding.get("contentIntentFingerprint")
        or intent.get("creatorIdentityProfileId") != profile.get("profileId")
        or binding.get("sourceSha256")
        not in list(intent.get("sourceAssetFingerprints") or [])
    ):
        raise LocalVideoUnavailable("arena_identity_intent_record_binding_mismatch")
    for field in (
        "sampleId",
        "blindedCandidateId",
        "identityProfileId",
        "contentIntentId",
    ):
        if not str(binding.get(field) or "").strip():
            raise LocalVideoUnavailable(f"arena_benchmark_{field}_missing")
    for field in (
        "identityProfileFingerprint",
        "contentIntentFingerprint",
        "modelDeepVerificationFingerprint",
    ):
        _required_sha256(binding.get(field), f"arena_benchmark_{field}")
    return binding


def _optional_input_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise LocalVideoUnavailable(f"local_video_input_missing_or_unsafe:{resolved}")
    return _sha256_file(resolved)


def _required_sha256(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise LocalVideoUnavailable(f"{field}_invalid")
    return text


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
