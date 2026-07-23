"""Bounded, evidence-preserving process runner for motion workers."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .core import reel_factory_python, sha256_file

_WORKER_TIMEOUT_SECONDS = 60 * 60 * 6
_WORKER_TERMINATE_GRACE_SECONDS = 5
_WORKER_STREAM_CHUNK_BYTES = 64 * 1024
_WORKER_STDOUT_CAPTURE_BYTES = 8 * 1024 * 1024
_WORKER_TAIL_BYTES = 64 * 1024
_SENSITIVE_ENV_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "AUTHORIZATION")


class MotionWorkerError(RuntimeError):
    """Worker failure carrying immutable log evidence without embedding full output."""

    def __init__(self, message: str, *, log_evidence: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.log_evidence = dict(log_evidence)


def _materialize_worker_evidence(
    evidence_transport_dir: Path | None,
    *,
    label: str,
    payload: Mapping[str, Any],
) -> tuple[Path, str]:
    if evidence_transport_dir is None:
        raise ValueError("local motion evidence transport directory is required")
    raw_directory = Path(evidence_transport_dir).expanduser()
    if raw_directory.exists() and raw_directory.is_symlink():
        raise ValueError("local motion evidence directory must not be a symlink")
    directory = raw_directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    path = directory / f"{label}.{digest}.json"
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError(
                f"local motion evidence path is not a regular file: {path}"
            )
        if sha256_file(path) != digest:
            raise ValueError(f"local motion evidence hash mismatch: {path}")
        if info.st_mode & 0o222:
            raise ValueError(f"local motion evidence file is mutable: {path}")
    else:
        atomic_write_text(path, encoded, encoding="utf-8")
        path.chmod(0o444)
    return path, digest


def build_motion_worker_command(
    factory: Any,
    *,
    model_id: str,
    prompt: str,
    still: Path | None,
    output_path: Path,
    campaign_slug: str,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int | None,
    audio_path: Path | None,
    generate_audio: bool,
    last_image_path: Path | None,
    source_video_path: Path | None = None,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    reference_image_paths: tuple[Path, ...],
    reference_video_paths: tuple[Path, ...],
    enable_prompt_expansion: bool,
    shot_type: str,
    local_model_dir: Path | None,
    motion_task: str,
    motion_lora_path: Path | None,
    motion_lora_strength: float,
    benchmark_recipe: Mapping[str, Any] | None = None,
    analyzer_registry: Mapping[str, Any] | None = None,
    local_motion_admission: Mapping[str, Any] | None = None,
    evidence_transport_dir: Path | None = None,
    dry_run: bool,
) -> list[str]:
    """Build the exact subprocess command and immutable evidence-file bindings."""

    command = [
        reel_factory_python(factory.settings.reel_factory_root),
        "-m",
        "reel_factory.motion_generate",
        "--model",
        model_id,
        "--prompt",
        prompt,
        "--out",
        str(output_path),
        "--campaign",
        campaign_slug,
        "--cohort-id",
        "creator_os_motion",
        "--seed",
        str(seed),
        "--shot-type",
        shot_type,
        "--dry-run" if dry_run else "--apply",
    ]
    if model_id.startswith("local_"):
        command.extend(["--task", motion_task])
    if model_id == "wavespeed_wan27_reference":
        if still is None:
            raise ValueError("WaveSpeed reference motion requires an accepted still")
        command.extend(["--reference-image", str(still)])
    elif motion_task not in {"text_to_video", "video_retake", "video_extend"}:
        if still is None:
            raise ValueError(f"{motion_task} requires an accepted still")
        command.extend(["--image", str(still)])
    for flag, value in (
        ("--steps", steps),
        ("--duration", duration_seconds),
        ("--resolution", resolution),
        ("--audio", audio_path),
        ("--last-image", last_image_path),
        ("--source-video", source_video_path),
        ("--retake-start-frame", retake_start_frame),
        ("--retake-end-frame", retake_end_frame),
        ("--extend-frames", extend_frames),
        ("--extend-direction", extend_direction if extend_frames is not None else None),
        ("--model-dir", local_model_dir),
        ("--lora", motion_lora_path),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    if motion_lora_strength != 1.0:
        command.extend(["--lora-strength", str(motion_lora_strength)])
    for path in reference_image_paths:
        command.extend(["--reference-image", str(path)])
    for path in reference_video_paths:
        command.extend(["--reference-video", str(path)])
    if enable_prompt_expansion:
        command.append("--enable-prompt-expansion")
    if generate_audio:
        command.append("--generate-audio")
    if preserve_audio:
        command.append("--preserve-audio")
    if benchmark_recipe is not None and analyzer_registry is not None:
        recipe_path, recipe_sha256 = _materialize_worker_evidence(
            evidence_transport_dir,
            label="benchmark_recipe",
            payload=benchmark_recipe,
        )
        registry_path, registry_sha256 = _materialize_worker_evidence(
            evidence_transport_dir,
            label="analyzer_registry",
            payload=analyzer_registry,
        )
        command.extend(
            [
                "--benchmark-recipe",
                str(recipe_path),
                "--benchmark-recipe-sha256",
                recipe_sha256,
                "--analyzer-registry",
                str(registry_path),
                "--analyzer-registry-sha256",
                registry_sha256,
            ]
        )
    if local_motion_admission is not None:
        admission_path, admission_sha256 = _materialize_worker_evidence(
            evidence_transport_dir,
            label="local_motion_admission",
            payload=local_motion_admission,
        )
        command.extend(
            [
                "--local-motion-admission",
                str(admission_path),
                "--local-motion-admission-sha256",
                admission_sha256,
            ]
        )
    return command


def _sensitive_worker_values() -> tuple[bytes, ...]:
    values = {
        value.encode("utf-8")
        for key, value in os.environ.items()
        if value
        and len(value) >= 8
        and any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }
    return tuple(sorted(values, key=len, reverse=True))


def _open_worker_log(log_dir: Path, *, phase: str, stream: str) -> tuple[Path, Any]:
    raw_directory = log_dir.expanduser()
    if raw_directory.exists() and raw_directory.is_symlink():
        raise MotionWorkerError(
            "motion worker log directory is unsafe", log_evidence={}
        )
    directory = raw_directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{phase}.{stream}.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise MotionWorkerError(
            "motion worker log identity collision", log_evidence={}
        ) from exc
    return path, os.fdopen(descriptor, "wb", buffering=0)


def _bounded_tail(tail: bytearray, chunk: bytes) -> None:
    tail.extend(chunk)
    if len(tail) > _WORKER_TAIL_BYTES:
        del tail[: len(tail) - _WORKER_TAIL_BYTES]


def _stop_worker_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_WORKER_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def invoke_motion_worker(
    command: list[str],
    *,
    factory: Any,
    log_dir: Path,
    phase: str,
) -> dict[str, Any]:
    """Run one worker with bounded memory and immutable, redacted stream evidence."""

    if phase not in {"preflight", "apply"}:
        raise ValueError("motion worker phase must be preflight or apply")
    stdout_path, stdout_log = _open_worker_log(log_dir, phase=phase, stream="stdout")
    try:
        stderr_path, stderr_log = _open_worker_log(
            log_dir, phase=phase, stream="stderr"
        )
    except Exception:
        stdout_log.close()
        stdout_path.chmod(0o444)
        raise

    secrets = _sensitive_worker_values()
    max_secret_length = max((len(value) for value in secrets), default=1)
    states: dict[str, dict[str, Any]] = {
        "stdout": {
            "path": stdout_path,
            "handle": stdout_log,
            "hash": hashlib.sha256(),
            "bytes": 0,
            "tail": bytearray(),
            "capture": bytearray(),
            "captureOverflow": False,
            "redactions": 0,
        },
        "stderr": {
            "path": stderr_path,
            "handle": stderr_log,
            "hash": hashlib.sha256(),
            "bytes": 0,
            "tail": bytearray(),
            "capture": None,
            "captureOverflow": False,
            "redactions": 0,
        },
    }
    thread_errors: list[BaseException] = []
    thread_error_lock = threading.Lock()

    def write_chunk(state: dict[str, Any], chunk: bytes) -> None:
        state["handle"].write(chunk)
        state["hash"].update(chunk)
        state["bytes"] += len(chunk)
        _bounded_tail(state["tail"], chunk)
        capture = state["capture"]
        if isinstance(capture, bytearray):
            remaining = _WORKER_STDOUT_CAPTURE_BYTES - len(capture)
            if remaining > 0:
                capture.extend(chunk[:remaining])
            if len(chunk) > remaining:
                state["captureOverflow"] = True

    def redact_preserving_length(state: dict[str, Any], chunk: bytes) -> bytes:
        redacted = chunk
        for secret in secrets:
            count = redacted.count(secret)
            if count:
                state["redactions"] += count
                redacted = redacted.replace(secret, b"*" * len(secret))
        return redacted

    def drain(name: str, pipe: Any) -> None:
        state = states[name]
        pending = b""
        try:
            while True:
                chunk = pipe.read(_WORKER_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                pending += chunk
                emit_count = max(0, len(pending) - (max_secret_length - 1))
                if emit_count:
                    redacted = redact_preserving_length(state, pending)
                    write_chunk(state, redacted[:emit_count])
                    pending = redacted[emit_count:]
            if pending:
                write_chunk(state, redact_preserving_length(state, pending))
        except BaseException as exc:  # pragma: no cover - defensive I/O boundary
            with thread_error_lock:
                thread_errors.append(exc)
        finally:
            pipe.close()

    process: subprocess.Popen[bytes] | None = None
    threads: list[threading.Thread] = []
    timed_out = False
    interrupted: BaseException | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=factory.settings.reel_factory_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        threads = [
            threading.Thread(
                target=drain, args=("stdout", process.stdout), daemon=True
            ),
            threading.Thread(
                target=drain, args=("stderr", process.stderr), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=_WORKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_worker_process(process)
        except BaseException as exc:
            interrupted = exc
            _stop_worker_process(process)
    except BaseException as exc:
        interrupted = exc
        if process is not None:
            _stop_worker_process(process)
    finally:
        for thread in threads:
            thread.join()
        evidence: dict[str, Any] = {}
        for name, state in states.items():
            state["handle"].close()
            state["path"].chmod(0o444)
            evidence[name] = {
                "path": str(state["path"]),
                "sha256": state["hash"].hexdigest(),
                "byteLength": state["bytes"],
                "redactionCount": state["redactions"],
            }

    if interrupted is not None:
        if isinstance(interrupted, (KeyboardInterrupt, SystemExit)):
            raise interrupted
        message = (
            "motion worker failed to start"
            if process is None
            else "motion worker interrupted"
        )
        raise MotionWorkerError(message, log_evidence=evidence) from interrupted
    if process is None:
        raise MotionWorkerError("motion worker failed to start", log_evidence=evidence)
    if thread_errors:
        raise MotionWorkerError(
            "motion worker log streaming failed", log_evidence=evidence
        ) from thread_errors[0]
    stderr_tail = bytes(states["stderr"]["tail"]).decode("utf-8", errors="replace")
    stdout_tail = bytes(states["stdout"]["tail"]).decode("utf-8", errors="replace")
    bounded_error = (stderr_tail or stdout_tail or "motion worker failed")[-3000:]
    if timed_out:
        raise MotionWorkerError(
            f"motion worker timed out: {bounded_error}", log_evidence=evidence
        )
    if process.returncode != 0:
        raise MotionWorkerError(bounded_error, log_evidence=evidence)
    if states["stdout"]["captureOverflow"]:
        raise MotionWorkerError(
            "motion worker JSON exceeded bounded capture limit",
            log_evidence=evidence,
        )
    try:
        payload = json.loads(bytes(states["stdout"]["capture"]))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MotionWorkerError(
            "motion worker returned invalid JSON", log_evidence=evidence
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != (
        "reel_factory.motion_generation_result.v1"
    ):
        raise MotionWorkerError(
            "motion worker returned the wrong schema", log_evidence=evidence
        )
    return {**payload, "_campaignExecutionLogEvidence": evidence}
