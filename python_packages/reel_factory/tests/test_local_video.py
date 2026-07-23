from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from reel_factory.local_generation_queue import (
    WorkerLeaseUnavailable,
    default_local_generation_queue,
    fingerprint,
)
from reel_factory.local_lora_registry import register_local_lora
from reel_factory.local_model_manager import runtime_status as manager_runtime_status
from reel_factory.local_video import (
    _IMAGEIO_FFMPEG_DISCOVERY_PROBE,
    _SANDBOX_ALLOWED_WRITE_PROBE,
    _SANDBOX_DENIAL_PROBE,
    LocalVideoRequest,
    LocalVideoUnavailable,
    _bind_isolated_toolchain,
    _isolated_execution,
    _preflight_allowed_sandbox_write,
    _preflight_imageio_ffmpeg_discovery,
    _preflight_sandbox_execution,
    _run_generation_process,
    _tool_evidence_for_path,
    _validate_campaign_admission,
    build_local_video_command,
    plan_local_video_job,
    probe_local_video,
    run_local_video,
)

RUNTIME_BINDING = {
    "runtimeId": "fixture-runtime",
    "repository": "fixture/runtime",
    "revision": "runtime-revision",
    "pythonExecutable": sys.executable,
    "pythonExecutableResolved": str(Path(sys.executable).resolve()),
    "ffmpegExecutable": "/fixture/bin/ffmpeg",
    "ffmpegSha256": "3" * 64,
    "ffmpegSize": 123,
    "ffmpegVersion": "ffmpeg version fixture",
    "ffprobeExecutable": "/fixture/bin/ffprobe",
    "ffprobeSha256": "4" * 64,
    "ffprobeSize": 456,
    "ffprobeVersion": "ffprobe version fixture",
}
RUNTIME_FINGERPRINT = fingerprint(RUNTIME_BINDING)
LICENSE_POLICY = {
    "licenseId": "apache-2.0",
    "commercialUse": True,
    "declaredAnnualRevenueUsd": None,
    "commercialRevenueLimitUsd": None,
    "commercialUseAllowed": True,
    "aiDisclosureRequired": False,
}
LICENSE_FINGERPRINT = fingerprint(LICENSE_POLICY)


@pytest.fixture(autouse=True)
def _stable_available_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reel_factory.local_video.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "reel_factory.local_video._sandbox_executable",
        lambda: Path("/usr/bin/sandbox-exec"),
    )

    def stable_isolation_preflight(**kwargs: object) -> dict[str, object]:
        python = Path(str(kwargs["python_executable"]))
        control_profile = "(version 1)\n(allow default)"
        return {
            "schema": "reel_factory.local_sandbox_preflight.v1",
            "enforcementBinary": "/usr/bin/sandbox-exec",
            "capabilityProbeExecutable": str(python),
            "capabilityProbeExecutableResolved": str(python.resolve()),
            "capabilityProbeFingerprint": fingerprint(
                {"implementation": _SANDBOX_DENIAL_PROBE}
            ),
            "timeoutSeconds": 5,
            "controlProfileFingerprint": fingerprint({"profile": control_profile}),
            "controlProbeReturnCode": 15,
            "denialProbeReturnCode": 0,
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "executionSucceeded": True,
            "unscopedWriteDenied": True,
            "tcpBindDenied": True,
            "udpConnectDenied": True,
            "tcpConnectDenied": True,
            "temporaryControlWritesExpected": 1,
            "temporaryControlWritesCleaned": True,
            "residualArtifactWrites": 0,
        }

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_sandbox_execution",
        stable_isolation_preflight,
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_imageio_ffmpeg_discovery",
        lambda **kwargs: {
            "schema": "reel_factory.local_media_tool_discovery_preflight.v1",
            "consumer": "imageio_ffmpeg.get_ffmpeg_exe",
            "consumerProbeFingerprint": fingerprint(
                {"implementation": _IMAGEIO_FFMPEG_DISCOVERY_PROBE}
            ),
            "pythonExecutable": str(kwargs["python_executable"]),
            "expectedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "expectedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "environmentFingerprint": fingerprint(kwargs["environment"]),
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "timeoutSeconds": 30,
            "discoverySucceeded": True,
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_allowed_sandbox_write",
        lambda **kwargs: {
            "schema": "reel_factory.local_sandbox_allowed_write_preflight.v1",
            "capabilityProbeExecutable": str(kwargs["python_executable"]),
            "capabilityProbeFingerprint": fingerprint(
                {"implementation": _SANDBOX_ALLOWED_WRITE_PROBE}
            ),
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "createSucceeded": True,
            "fsyncSucceeded": True,
            "deleteSucceeded": True,
            "residualArtifacts": 0,
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video.shutil.which",
        lambda executable, **_kwargs: {
            "ffmpeg": "/fixture/bin/ffmpeg",
            "ffprobe": "/fixture/bin/ffprobe",
        }.get(executable),
    )
    monkeypatch.setattr(
        "reel_factory.local_video._tool_evidence_for_path",
        lambda path, **_kwargs: {
            "executable": str(path),
            "sha256": (
                RUNTIME_BINDING["ffmpegSha256"]
                if path.name == "ffmpeg"
                else RUNTIME_BINDING["ffprobeSha256"]
            ),
            "size": (
                RUNTIME_BINDING["ffmpegSize"]
                if path.name == "ffmpeg"
                else RUNTIME_BINDING["ffprobeSize"]
            ),
            "version": (
                RUNTIME_BINDING["ffmpegVersion"]
                if path.name == "ffmpeg"
                else RUNTIME_BINDING["ffprobeVersion"]
            ),
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_generation_queue._physical_memory_bytes",
        lambda: 64 * 1024**3,
    )
    monkeypatch.setattr(
        "reel_factory.local_generation_queue._macos_available_memory_bytes",
        lambda: 128 * 1024**3,
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_local_inputs",
        lambda _request: {"images": [], "sourceAudio": None},
    )
    monkeypatch.setattr(
        "reel_factory.local_video.model_status",
        lambda model_id, **_kwargs: _model_status(model_id),
    )
    monkeypatch.setattr(
        "reel_factory.local_video.runtime_status",
        lambda **_kwargs: {
            "ready": True,
            "issues": [],
            "python": sys.executable,
            "runtimeDir": "/fixture/runtime",
        },
    )


def _model_status(model_id: str) -> dict:
    deep_core = {
        "modelId": model_id,
        "manifestSha256": "c" * 64,
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
        "providerCalls": 0,
        "paidGeneration": False,
    }
    return {
        "ready": True,
        "issues": [],
        "modelId": model_id,
        "manifest": {
            "modelId": model_id,
            "revision": "fixture-revision",
            "licenseId": LICENSE_POLICY["licenseId"],
            "commercialRevenueLimitUsd": None,
        },
        "manifestSha256": "c" * 64,
        "deepVerified": True,
        "deepVerificationReceipt": {
            **deep_core,
            "verificationFingerprint": fingerprint(deep_core),
        },
    }


def _image(tmp_path: Path, name: str = "still.jpg") -> Path:
    path = tmp_path / name
    path.write_bytes(f"image:{name}".encode())
    return path


def test_generation_process_log_is_streamed_bounded_and_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("reel_factory.local_video._MAX_GENERATION_LOG_BYTES", 2048)
    log_path = tmp_path / "generation.log"
    result = _run_generation_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x'*4096); sys.stderr.write('TAIL_MARK')",
        ],
        environment={},
        log_path=log_path,
        runner=subprocess.run,
    )
    assert result.returncode == 0
    assert log_path.stat().st_size == 2048
    assert result.log_evidence["observedBytes"] == 4105
    assert result.log_evidence["truncated"] is True
    assert result.log_evidence["tail"].endswith("TAIL_MARK")
    assert (
        result.log_evidence["sha256"]
        == hashlib.sha256(log_path.read_bytes()).hexdigest()
    )
    with pytest.raises(FileExistsError):
        _run_generation_process(
            [sys.executable, "-c", "print('second')"],
            environment={},
            log_path=log_path,
            runner=subprocess.run,
        )


@pytest.mark.parametrize(
    ("parent_signal", "expected_message"),
    (
        (signal.SIGINT, None),
        (signal.SIGTERM, "local_video_generation_terminated"),
        (signal.SIGHUP, "local_video_generation_terminated"),
    ),
)
def test_generation_process_interrupt_reaps_isolated_child_group(
    tmp_path: Path, parent_signal: int, expected_message: str | None
) -> None:
    pid_path = tmp_path / "child.pid"
    log_path = tmp_path / "generation.log"
    original_handler = signal.getsignal(parent_signal)

    def interrupt_parent() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            handler_ready = (
                parent_signal == signal.SIGINT
                or signal.getsignal(parent_signal) != original_handler
            )
            if pid_path.is_file() and handler_ready:
                os.kill(os.getpid(), parent_signal)
                return
            time.sleep(0.01)
        raise AssertionError("generation child or signal handler did not become ready")

    interrupter = threading.Thread(target=interrupt_parent, daemon=True)
    interrupter.start()
    with pytest.raises(KeyboardInterrupt, match=expected_message) as raised:
        _run_generation_process(
            [
                sys.executable,
                "-c",
                (
                    "import os,time,pathlib;"
                    f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()));"
                    "time.sleep(60)"
                ),
            ],
            environment={},
            log_path=log_path,
            runner=subprocess.run,
        )
    interrupter.join(timeout=10)
    assert not interrupter.is_alive()
    child_pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert raised.value.__class__ is KeyboardInterrupt
    assert raised.value.log_evidence["path"] == str(log_path)  # type: ignore[attr-defined]
    assert signal.getsignal(parent_signal) == original_handler


def _request(
    tmp_path: Path,
    *,
    model_id: str = "local_wan22_ti2v_5b_mlx",
    audio_mode: str = "none",
    audio_path: Path | None = None,
    last_image_path: Path | None = None,
    task: str = "image_to_video",
    image_path: Path | None = None,
    lora_path: Path | None = None,
) -> LocalVideoRequest:
    selected_image = image_path if image_path is not None else _image(tmp_path)
    source_sha256 = hashlib.sha256(selected_image.read_bytes()).hexdigest()
    exact_input_fingerprints = [source_sha256]
    for path in (audio_path, last_image_path):
        if path is not None:
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            if value not in exact_input_fingerprints:
                exact_input_fingerprints.append(value)
    recipe = {
        "schema": "creator_os.benchmark_recipe.v1",
        "recipeId": "fixture-recipe",
        "taskKind": task,
        "inputFingerprints": exact_input_fingerprints,
        "requiredAnalyzers": [
            {"analyzerId": "fixture.motion", "analyzerVersion": "1.0.0"}
        ],
        "expectedProviderCalls": 0,
        "productionWritesAllowed": False,
    }
    registry = {
        "schema": "creator_os.analyzer_registry.v1",
        "registryId": "fixture-registry",
        "analyzers": [{"analyzerId": "fixture.motion", "analyzerVersion": "1.0.0"}],
    }
    profile = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": "fixture-identity",
    }
    intent = {
        "schema": "creator_os.content_intent.v1",
        "intentId": "fixture-intent",
        "creatorIdentityProfileId": profile["profileId"],
        "sourceAssetFingerprints": exact_input_fingerprints,
    }
    model_deep_fingerprint = _model_status(model_id)["deepVerificationReceipt"][
        "verificationFingerprint"
    ]
    binding_core = {
        "schema": "reel_factory.arena_benchmark_execution.v1",
        "sampleId": "fixture-sample",
        "blindedCandidateId": "fixture-candidate",
        "sourceSha256": source_sha256,
        "identityProfileId": "fixture-identity",
        "identityProfileFingerprint": fingerprint(profile),
        "contentIntentId": "fixture-intent",
        "contentIntentFingerprint": fingerprint(intent),
        "benchmarkRecipeFingerprint": fingerprint(recipe),
        "analyzerRegistryFingerprint": fingerprint(registry),
        "modelDeepVerificationFingerprint": model_deep_fingerprint,
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
        "licensePolicy": LICENSE_POLICY,
        "licensePolicyFingerprint": LICENSE_FINGERPRINT,
        "providerCalls": 0,
        "productionWritesAllowed": False,
    }
    return LocalVideoRequest(
        model_id=model_id,
        image_path=selected_image,
        prompt="Subtle natural movement with a steady portrait camera composition",
        output_path=tmp_path / "out.mp4",
        duration_seconds=6,
        seed=71,
        audio_mode=audio_mode,  # type: ignore[arg-type]
        audio_path=audio_path,
        last_image_path=last_image_path,
        task=task,  # type: ignore[arg-type]
        lora_path=lora_path,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
        creator_identity_profile=profile,
        content_intent=intent,
        execution_context="arena_benchmark",
        arena_benchmark_binding={
            **binding_core,
            "bindingFingerprint": fingerprint(binding_core),
        },
    )


def _rebind_arena_source(
    request: LocalVideoRequest, source_path: Path
) -> LocalVideoRequest:
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    exact_inputs = [source_sha256]
    for path in (request.audio_path, request.last_image_path):
        if path is not None:
            exact_inputs.append(hashlib.sha256(path.read_bytes()).hexdigest())
    recipe = {
        **dict(request.benchmark_recipe or {}),
        "inputFingerprints": exact_inputs,
        "taskKind": request.task,
    }
    intent = {
        **dict(request.content_intent or {}),
        "sourceAssetFingerprints": sorted(exact_inputs),
    }
    core = dict(request.arena_benchmark_binding or {})
    core.pop("bindingFingerprint", None)
    core["sourceSha256"] = source_sha256
    core["benchmarkRecipeFingerprint"] = fingerprint(recipe)
    core["contentIntentFingerprint"] = fingerprint(intent)
    return replace(
        request,
        benchmark_recipe=recipe,
        content_intent=intent,
        arena_benchmark_binding={
            **core,
            "bindingFingerprint": fingerprint(core),
        },
    )


def _uv_ephemeral_path(identifier: str) -> str:
    cache = Path.home() / ".cache" / "uv"
    return os.pathsep.join(
        (
            str(cache / "builds-v0" / f".tmp{identifier}" / "bin"),
            str(cache / "archive-v0" / "stable-environment" / "bin"),
            "/fixture/bin",
            "/usr/bin",
            "/bin",
        )
    )


def test_arena_plan_job_is_stable_across_uv_ephemeral_path_prefixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", str(Path.home() / ".cache/uv"))
    monkeypatch.setenv("PATH", _uv_ephemeral_path("planner"))
    planned = plan_local_video_job(request)

    monkeypatch.setenv("PATH", _uv_ephemeral_path("apply"))
    applied = plan_local_video_job(request)
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            (
                str(Path.home() / ".cache/uv/archive-v0/stable-environment/bin"),
                "/fixture/bin",
                "/usr/bin",
                "/bin",
            )
        ),
    )
    applied_without_uv_build = plan_local_video_job(request)

    assert applied == planned
    assert applied_without_uv_build == planned
    assert applied.job_id == planned.job_id
    assert applied.params_fingerprint == planned.params_fingerprint
    assert applied.task_fingerprint == planned.task_fingerprint


def test_meaningful_path_drift_changes_exact_job_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", str(Path.home() / ".cache/uv"))
    monkeypatch.setenv("PATH", _uv_ephemeral_path("planner"))
    planned = plan_local_video_job(request)

    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            (
                str(Path.home() / ".cache/uv/builds-v0/.tmpapply/bin"),
                str(Path.home() / ".cache/uv/archive-v0/stable-environment/bin"),
                "/tmp/unreviewed-toolchain/bin",
                "/fixture/bin",
                "/usr/bin",
                "/bin",
            )
        ),
    )
    drifted = plan_local_video_job(request)

    assert drifted.job_id != planned.job_id
    assert drifted.params_fingerprint != planned.params_fingerprint
    assert drifted.task_fingerprint != planned.task_fingerprint


def test_uv_path_normalization_preserves_executed_environment_and_policy_evidence(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    first_path = _uv_ephemeral_path("planner")
    second_path = _uv_ephemeral_path("apply")
    first_command, first_environment, first_isolation = _isolated_execution(
        request,
        output=request.output_path.resolve(),
        base_command=[sys.executable, "/fixture/generate.py"],
        environ={
            "PATH": first_path,
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "must-stay-stripped",
        },
    )
    second_command, second_environment, second_isolation = _isolated_execution(
        request,
        output=request.output_path.resolve(),
        base_command=[sys.executable, "/fixture/generate.py"],
        environ={
            "PATH": second_path,
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "must-stay-stripped",
        },
    )

    expected_path = os.pathsep.join(
        (
            str(Path.home() / ".cache/uv/archive-v0/stable-environment/bin"),
            "/fixture/bin",
            "/usr/bin",
            "/bin",
        )
    )
    assert first_environment["PATH"] == expected_path
    assert second_environment["PATH"] == expected_path
    assert (
        first_environment["IMAGEIO_FFMPEG_EXE"] == RUNTIME_BINDING["ffmpegExecutable"]
    )
    assert (
        second_environment["IMAGEIO_FFMPEG_EXE"] == RUNTIME_BINDING["ffmpegExecutable"]
    )
    assert "IMAGEIO_FFMPEG_EXE" in first_isolation["environmentAllowedKeys"]
    assert "OPENAI_API_KEY" not in first_environment
    assert "OPENAI_API_KEY" not in second_environment
    assert "environmentObservation" not in first_isolation
    assert "environmentObservation" not in second_isolation
    assert first_isolation["environmentPathPolicy"] == (
        "allowlisted_uv_build_temp_bins_removed_v1"
    )
    assert (
        first_isolation["environmentFingerprint"]
        == second_isolation["environmentFingerprint"]
    )
    assert (
        first_isolation["isolationFingerprint"]
        == second_isolation["isolationFingerprint"]
    )
    assert first_isolation["networkAccess"] == "denied"
    assert first_isolation["writeAccess"] == "explicit_artifacts_only"
    assert first_isolation["providerActivity"]["callsObserved"] == 0
    assert (
        first_isolation["providerActivity"]["successfulDirectSocketCallsPossible"]
        is False
    )
    assert first_isolation["providerActivity"]["measurementScope"] == (
        "successful_direct_socket_provider_calls"
    )
    assert "(allow default)" in first_command[2]
    assert "(deny network*)" in first_command[2]
    assert "(deny file-write*" in first_command[2]
    assert "system.sb" not in first_command[2]
    assert first_command[4] == RUNTIME_BINDING["pythonExecutable"]
    assert first_command == second_command


def test_uv_path_normalization_respects_configured_cache_root(tmp_path: Path) -> None:
    request = _request(tmp_path)
    uv_cache = tmp_path / "configured-uv-cache"
    stable_bin = uv_cache / "archive-v0" / "stable-environment" / "bin"
    _, environment, _ = _isolated_execution(
        request,
        output=request.output_path.resolve(),
        base_command=[sys.executable, "/fixture/generate.py"],
        environ={
            "PATH": os.pathsep.join(
                (
                    str(uv_cache / "builds-v0" / ".tmpplanner" / "bin"),
                    str(stable_bin),
                    "/fixture/bin",
                    "/usr/bin",
                    "/bin",
                )
            ),
            "UV_CACHE_DIR": str(uv_cache),
        },
    )

    assert environment["PATH"] == os.pathsep.join(
        (str(stable_bin), "/fixture/bin", "/usr/bin", "/bin")
    )


def test_sandbox_preflight_proves_control_and_restrictive_capabilities(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    control_profile = "(version 1)\n(allow default)"

    def successful_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, dict(kwargs)))
        if command[2] == control_profile:
            Path(command[-1]).write_bytes(b"control")
            return subprocess.CompletedProcess(command, 15, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    forbidden = tmp_path / "forbidden-write.tmp"
    evidence = _preflight_sandbox_execution(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile=("(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)"),
        python_executable=Path(sys.executable),
        forbidden_write_path=forbidden,
        runner=successful_runner,
    )

    assert len(calls) == 2
    control_command, control_kwargs = calls[0]
    assert control_command[2] == control_profile
    assert control_command[4:9] == [sys.executable, "-B", "-I", "-S", "-E"]
    assert control_command[-1] == str(forbidden)
    assert control_kwargs["timeout"] == 5
    assert control_kwargs["env"] == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    denial_command, denial_kwargs = calls[1]
    assert "(deny network*)" in denial_command[2]
    assert "(deny file-write*)" in denial_command[2]
    assert denial_command[4:9] == [sys.executable, "-B", "-I", "-S", "-E"]
    assert 'open(sys.argv[1], "xb")' in denial_command[-2]
    assert 'tcp.bind(("127.0.0.1", 0))' in denial_command[-2]
    assert 'udp.connect(("127.0.0.1", 9))' in denial_command[-2]
    assert 'tcp_client.connect(("127.0.0.1", 9))' in denial_command[-2]
    assert denial_kwargs == control_kwargs
    assert evidence["controlProbeReturnCode"] == 15
    assert evidence["denialProbeReturnCode"] == 0
    assert evidence["executionSucceeded"] is True
    assert evidence["unscopedWriteDenied"] is True
    assert evidence["tcpBindDenied"] is True
    assert evidence["udpConnectDenied"] is True
    assert evidence["tcpConnectDenied"] is True
    assert evidence["temporaryControlWritesCleaned"] is True
    assert evidence["residualArtifactWrites"] == 0
    assert evidence["capabilityProbeExecutable"] == sys.executable
    assert not forbidden.exists()
    assert "networkAccess" not in evidence
    assert "writeAccess" not in evidence


def test_imageio_ffmpeg_discovery_preflight_proves_exact_runtime_consumer(
    tmp_path: Path,
) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    environment = {
        "PATH": "/usr/bin:/bin",
        "IMAGEIO_FFMPEG_EXE": str(ffmpeg),
    }
    calls: list[tuple[list[str], dict[str, object]]] = []

    def successful_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, dict(kwargs)))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{ffmpeg}\n",
            stderr="",
        )

    evidence = _preflight_imageio_ffmpeg_discovery(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile="(version 1)\n(allow default)\n(deny network*)",
        python_executable=Path(sys.executable),
        environment=environment,
        expected_ffmpeg=ffmpeg,
        runner=successful_runner,
    )

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == [
        "/usr/bin/sandbox-exec",
        "-p",
        "(version 1)\n(allow default)\n(deny network*)",
        "--",
    ]
    assert command[4:9] == [sys.executable, "-B", "-I", "-E", "-c"]
    assert command[-1] == _IMAGEIO_FFMPEG_DISCOVERY_PROBE
    assert kwargs["env"] == environment
    assert kwargs["timeout"] == 30
    assert evidence["consumer"] == "imageio_ffmpeg.get_ffmpeg_exe"
    assert evidence["expectedFfmpegExecutable"] == str(ffmpeg)
    assert evidence["observedFfmpegExecutable"] == str(ffmpeg)
    assert evidence["discoverySucceeded"] is True


def test_imageio_ffmpeg_discovery_preflight_rejects_environment_substitution(
    tmp_path: Path,
) -> None:
    expected = tmp_path / "ffmpeg"
    expected.write_bytes(b"#!/bin/sh\n")
    expected.chmod(0o755)

    with pytest.raises(
        LocalVideoUnavailable,
        match="environment_binding_mismatch",
    ):
        _preflight_imageio_ffmpeg_discovery(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)",
            python_executable=Path(sys.executable),
            environment={"IMAGEIO_FFMPEG_EXE": str(tmp_path / "substitute")},
            expected_ffmpeg=expected,
            runner=lambda *_args, **_kwargs: pytest.fail(
                "substituted binding must fail before spawning the consumer"
            ),
        )


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (
            subprocess.CompletedProcess(
                ["imageio-probe"], 72, stdout="", stderr="import failed"
            ),
            "exit_72",
        ),
        (
            subprocess.CompletedProcess(
                ["imageio-probe"],
                0,
                stdout="/tmp/substituted-ffmpeg\n",
                stderr="",
            ),
            "resolved_path_mismatch",
        ),
    ],
)
def test_imageio_ffmpeg_discovery_preflight_fails_closed_on_consumer_failure(
    tmp_path: Path,
    completed: subprocess.CompletedProcess[str],
    expected: str,
) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    ffmpeg.chmod(0o755)

    with pytest.raises(LocalVideoUnavailable, match=expected):
        _preflight_imageio_ffmpeg_discovery(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)",
            python_executable=Path(sys.executable),
            environment={"IMAGEIO_FFMPEG_EXE": str(ffmpeg)},
            expected_ffmpeg=ffmpeg,
            runner=lambda *_args, **_kwargs: completed,
        )


def test_sandbox_preflight_fails_closed_on_nonzero_control_exit(
    tmp_path: Path,
) -> None:
    def rejected_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 71, stdout="", stderr="denied")

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_isolation_control_preflight_failed:exit_71",
    ):
        _preflight_sandbox_execution(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile=(
                "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)"
            ),
            python_executable=Path(sys.executable),
            forbidden_write_path=tmp_path / "forbidden-write.tmp",
            runner=rejected_runner,
        )


@pytest.mark.parametrize("unexpected_mask", [1, 2, 4, 8, 15])
def test_sandbox_preflight_fails_closed_when_any_denial_is_not_enforced(
    tmp_path: Path,
    unexpected_mask: int,
) -> None:
    calls = 0

    def permissive_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(command[-1]).write_bytes(b"control")
        return subprocess.CompletedProcess(
            command,
            15 if calls == 1 else unexpected_mask,
            stdout="",
            stderr="",
        )

    with pytest.raises(
        LocalVideoUnavailable,
        match=(f"local_video_isolation_denial_preflight_failed:exit_{unexpected_mask}"),
    ):
        _preflight_sandbox_execution(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)",
            python_executable=Path(sys.executable),
            forbidden_write_path=tmp_path / "forbidden-write.tmp",
            runner=permissive_runner,
        )


def test_sandbox_preflight_rejects_outer_confinement_false_positive(
    tmp_path: Path,
) -> None:
    def outer_confined_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_isolation_control_preflight_failed:exit_0",
    ):
        _preflight_sandbox_execution(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)",
            python_executable=Path(sys.executable),
            forbidden_write_path=tmp_path / "forbidden-write.tmp",
            runner=outer_confined_runner,
        )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            subprocess.TimeoutExpired(["sandbox-exec"], 5),
            "local_video_isolation_denial_preflight_failed:timeout",
        ),
        (
            OSError("denial probe unavailable"),
            "local_video_isolation_denial_preflight_failed:unavailable",
        ),
    ],
)
def test_sandbox_preflight_fails_closed_on_denial_probe_errors(
    tmp_path: Path,
    failure: BaseException,
    expected: str,
) -> None:
    calls = 0

    def failing_denial_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(command[-1]).write_bytes(b"control")
            return subprocess.CompletedProcess(command, 15, stdout="", stderr="")
        raise failure

    with pytest.raises(LocalVideoUnavailable, match=expected):
        _preflight_sandbox_execution(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)",
            python_executable=Path(sys.executable),
            forbidden_write_path=tmp_path / "forbidden-write.tmp",
            runner=failing_denial_runner,
        )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            subprocess.TimeoutExpired(["sandbox-exec"], 5),
            "local_video_isolation_control_preflight_failed:timeout",
        ),
        (
            OSError("control probe unavailable after write"),
            "local_video_isolation_control_preflight_failed:unavailable",
        ),
        (KeyboardInterrupt(), None),
    ],
)
def test_sandbox_preflight_cleans_probe_when_runner_raises_after_write(
    tmp_path: Path,
    failure: BaseException,
    expected: str | None,
) -> None:
    forbidden = tmp_path / "forbidden-write.tmp"

    def failing_runner(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        forbidden.write_bytes(b"probe residue")
        raise failure

    if expected is None:
        with pytest.raises(KeyboardInterrupt):
            _preflight_sandbox_execution(
                sandbox_exec=Path("/usr/bin/sandbox-exec"),
                profile=(
                    "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)"
                ),
                python_executable=Path(sys.executable),
                forbidden_write_path=forbidden,
                runner=failing_runner,
            )
    else:
        with pytest.raises(LocalVideoUnavailable, match=expected):
            _preflight_sandbox_execution(
                sandbox_exec=Path("/usr/bin/sandbox-exec"),
                profile=(
                    "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)"
                ),
                python_executable=Path(sys.executable),
                forbidden_write_path=forbidden,
                runner=failing_runner,
            )

    assert not forbidden.exists()
    assert not forbidden.is_symlink()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox policy smoke")
def test_real_macos_sandbox_preflight_proves_active_denials(tmp_path: Path) -> None:
    evidence = _preflight_sandbox_execution(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile="(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)",
        python_executable=Path(sys.executable),
        forbidden_write_path=tmp_path / "forbidden-write.tmp",
    )

    assert evidence["controlProbeReturnCode"] == 15
    assert evidence["denialProbeReturnCode"] == 0
    assert evidence["tcpConnectDenied"] is True
    assert not (tmp_path / "forbidden-write.tmp").exists()


@pytest.mark.skipif(
    sys.platform != "darwin"
    or os.environ.get("CREATOR_OS_RUN_REAL_LOCAL_PREFLIGHT") != "1",
    reason="explicit local-only pinned-runtime preflight",
)
def test_real_pinned_wan_runtime_discovers_exact_ffmpeg_in_sandbox(
    tmp_path: Path,
) -> None:
    status = manager_runtime_status()
    if status.get("ready") is not True:
        pytest.skip("pinned Wan runtime is not ready on this machine")
    python = Path(str(status["python"]))
    assert python.is_file()
    which = subprocess.run(
        ["/usr/bin/which", "ffmpeg"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env=os.environ.copy(),
    )
    if which.returncode != 0 or not which.stdout.strip():
        pytest.skip("system FFmpeg is not available")
    ffmpeg = Path(which.stdout.strip()).resolve(strict=True)
    home = tmp_path / "home"
    temporary = tmp_path / "tmp"
    cache = tmp_path / "cache"
    for directory in (home, temporary, cache):
        directory.mkdir()
    profile = "\n".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            "(deny file-write*)",
        )
    )
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "XDG_CACHE_HOME": str(cache),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "*",
        "no_proxy": "*",
        "PYTHONDONTWRITEBYTECODE": "1",
        "IMAGEIO_FFMPEG_EXE": str(ffmpeg),
    }

    evidence = _preflight_imageio_ffmpeg_discovery(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile=profile,
        python_executable=python,
        environment=environment,
        expected_ffmpeg=ffmpeg,
    )

    assert evidence["pythonExecutable"] == str(python)
    assert evidence["observedFfmpegExecutable"] == str(ffmpeg)
    assert evidence["observedFfmpegExecutableResolved"] == str(ffmpeg)
    assert evidence["discoverySucceeded"] is True
    assert not any(any(directory.iterdir()) for directory in (home, temporary, cache))


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox policy smoke")
def test_real_macos_allowed_write_preflight_accepts_only_sandbox_root(
    tmp_path: Path,
) -> None:
    sandbox_root = tmp_path / "sandbox-root"
    sandbox_root.mkdir()
    profile = "\n".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            "(deny file-write*",
            "  (require-not",
            f"    (subpath {json.dumps(str(sandbox_root))})",
            "  )",
            ")",
        )
    )

    evidence = _preflight_allowed_sandbox_write(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile=profile,
        python_executable=Path(sys.executable),
        sandbox_root=sandbox_root,
    )

    assert "system.sb" not in profile
    assert "(deny network*)" in profile
    assert "(deny file-write*" in profile
    assert evidence["createSucceeded"] is True
    assert evidence["fsyncSucceeded"] is True
    assert evidence["deleteSucceeded"] is True
    assert evidence["residualArtifacts"] == 0
    assert not list(sandbox_root.iterdir())


def test_allowed_sandbox_write_preflight_creates_fsyncs_and_deletes(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def successful_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        probe = Path(command[-1])
        probe.write_bytes(b"temporary")
        probe.unlink()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    evidence = _preflight_allowed_sandbox_write(
        sandbox_exec=Path("/usr/bin/sandbox-exec"),
        profile="(version 1)\n(allow default)",
        python_executable=Path(sys.executable),
        sandbox_root=tmp_path,
        runner=successful_runner,
    )

    assert len(calls) == 1
    assert evidence["createSucceeded"] is True
    assert evidence["fsyncSucceeded"] is True
    assert evidence["deleteSucceeded"] is True
    assert evidence["residualArtifacts"] == 0
    assert not list(tmp_path.glob(".allowed_write_probe_*"))


def test_allowed_sandbox_write_preflight_cleans_and_fails_on_residue(
    tmp_path: Path,
) -> None:
    def residue_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"residue")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_isolation_allowed_write_preflight_failed:residual_artifact",
    ):
        _preflight_allowed_sandbox_write(
            sandbox_exec=Path("/usr/bin/sandbox-exec"),
            profile="(version 1)\n(allow default)",
            python_executable=Path(sys.executable),
            sandbox_root=tmp_path,
            runner=residue_runner,
        )
    assert not list(tmp_path.glob(".allowed_write_probe_*"))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            subprocess.TimeoutExpired(["sandbox-exec"], 5),
            "local_video_isolation_allowed_write_preflight_failed:timeout",
        ),
        (
            OSError("allowed-write probe unavailable after write"),
            "local_video_isolation_allowed_write_preflight_failed:unavailable",
        ),
        (KeyboardInterrupt(), None),
    ],
)
def test_allowed_write_preflight_cleans_probe_when_runner_raises_after_write(
    tmp_path: Path,
    failure: BaseException,
    expected: str | None,
) -> None:
    def failing_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"probe residue")
        raise failure

    if expected is None:
        with pytest.raises(KeyboardInterrupt):
            _preflight_allowed_sandbox_write(
                sandbox_exec=Path("/usr/bin/sandbox-exec"),
                profile="(version 1)\n(allow default)",
                python_executable=Path(sys.executable),
                sandbox_root=tmp_path,
                runner=failing_runner,
            )
    else:
        with pytest.raises(LocalVideoUnavailable, match=expected):
            _preflight_allowed_sandbox_write(
                sandbox_exec=Path("/usr/bin/sandbox-exec"),
                profile="(version 1)\n(allow default)",
                python_executable=Path(sys.executable),
                sandbox_root=tmp_path,
                runner=failing_runner,
            )

    assert not list(tmp_path.glob(".allowed_write_probe_*"))


def test_dropped_uv_build_bin_cannot_supply_missing_media_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    uv_bin = str(Path.home() / ".cache/uv/builds-v0/.tmpfake-tools/bin")

    def only_dropped_prefix_has_tools(executable: str, *, path: str) -> str | None:
        if uv_bin in path:
            return f"{uv_bin}/{executable}"
        return None

    monkeypatch.setattr(
        "reel_factory.local_video.shutil.which", only_dropped_prefix_has_tools
    )
    with pytest.raises(
        LocalVideoUnavailable, match="local_video_ffmpeg_runtime_binding_mismatch"
    ):
        _isolated_execution(
            request,
            output=request.output_path.resolve(),
            base_command=[sys.executable, "/fixture/generate.py"],
            environ={"PATH": os.pathsep.join((uv_bin, "/usr/bin", "/bin"))},
        )


def test_toolchain_binding_rejects_substituted_imageio_ffmpeg_selector(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_ffmpeg_runtime_binding_mismatch",
    ):
        _bind_isolated_toolchain(
            request,
            base_command=[sys.executable, "/fixture/generate.py"],
            environment={
                "PATH": "/fixture/bin:/usr/bin:/bin",
                "IMAGEIO_FFMPEG_EXE": "/tmp/substituted-ffmpeg",
            },
        )


def test_campaign_execution_passes_validated_runtime_binding_into_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(
        _request(tmp_path),
        execution_context="campaign_generation",
        arena_benchmark_binding=None,
        local_motion_admission={"schema": "campaign-admission-fixture"},
    )
    binding_core = {
        "schema": "reel_factory.campaign_local_motion_binding.v1",
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
    }
    execution_binding = {
        **binding_core,
        "bindingFingerprint": fingerprint(binding_core),
    }
    monkeypatch.setattr(
        "reel_factory.local_video._validate_execution_binding",
        lambda *_args, **_kwargs: execution_binding,
    )

    lineage = run_local_video(request, dry_run=True)

    assert lineage["executionContext"] == "campaign_generation"
    assert lineage["executionBinding"] == execution_binding
    discovery = lineage["executionIsolation"]["mediaToolDiscoveryPreflight"]
    assert discovery["expectedFfmpegExecutable"] == RUNTIME_BINDING["ffmpegExecutable"]
    assert (
        discovery["environmentFingerprint"]
        == lineage["executionIsolation"]["environmentFingerprint"]
    )


def test_campaign_apply_runs_exact_ffmpeg_discovery_before_queue_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(
        _request(tmp_path),
        execution_context="campaign_generation",
        arena_benchmark_binding=None,
        local_motion_admission={"schema": "campaign-admission-fixture"},
    )
    binding_core = {
        "schema": "reel_factory.campaign_local_motion_binding.v1",
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
    }
    execution_binding = {
        **binding_core,
        "bindingFingerprint": fingerprint(binding_core),
    }
    monkeypatch.setattr(
        "reel_factory.local_video._validate_execution_binding",
        lambda *_args, **_kwargs: execution_binding,
    )
    discovery_calls: list[dict[str, object]] = []

    def observe_discovery(**kwargs: object) -> dict[str, object]:
        discovery_calls.append(dict(kwargs))
        return {
            "schema": "reel_factory.local_media_tool_discovery_preflight.v1",
            "consumer": "imageio_ffmpeg.get_ffmpeg_exe",
            "consumerProbeFingerprint": fingerprint(
                {"implementation": _IMAGEIO_FFMPEG_DISCOVERY_PROBE}
            ),
            "pythonExecutable": str(kwargs["python_executable"]),
            "expectedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "expectedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "environmentFingerprint": fingerprint(kwargs["environment"]),
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "timeoutSeconds": 30,
            "discoverySucceeded": True,
        }

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_imageio_ffmpeg_discovery",
        observe_discovery,
    )

    class QueueReached(RuntimeError):
        pass

    def queue_after_preflight() -> object:
        assert len(discovery_calls) == 1
        environment = discovery_calls[0]["environment"]
        assert isinstance(environment, dict)
        assert environment["IMAGEIO_FFMPEG_EXE"] == RUNTIME_BINDING["ffmpegExecutable"]
        raise QueueReached("queue reached after exact media-tool preflight")

    monkeypatch.setattr(
        "reel_factory.local_video.default_local_generation_queue",
        queue_after_preflight,
    )

    with pytest.raises(QueueReached, match="queue reached after exact"):
        run_local_video(request, dry_run=False)

    assert len(discovery_calls) == 1
    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()


def test_isolation_rejects_same_path_media_tool_content_substitution(
    tmp_path: Path,
) -> None:
    tool = tmp_path / "ffmpeg"
    marker = tmp_path / "substituted-tool-was-invoked"
    trusted_content = b"#!/bin/sh\nprintf 'ffmpeg version trusted\\n'\n"
    tool.write_bytes(trusted_content)
    tool.chmod(0o755)
    trusted_evidence = {
        "executable": str(tool.resolve()),
        "sha256": hashlib.sha256(trusted_content).hexdigest(),
        "size": len(trusted_content),
        "version": "ffmpeg version trusted",
    }
    substituted_content = (
        f"#!/bin/sh\ntouch {str(marker)!r}\nprintf 'ffmpeg version trusted\\n'\n"
    ).encode()
    tool.write_bytes(substituted_content)
    tool.chmod(0o755)

    with pytest.raises(RuntimeError, match="runtime_tool_content_mismatch"):
        _tool_evidence_for_path(
            tool,
            expected=trusted_evidence,
            environment={"PATH": "/usr/bin:/bin"},
        )
    assert not marker.exists()


def test_isolation_rejects_python_outside_runtime_binding(tmp_path: Path) -> None:
    request = _request(tmp_path)
    with pytest.raises(
        LocalVideoUnavailable, match="local_video_python_runtime_binding_mismatch"
    ):
        _isolated_execution(
            request,
            output=request.output_path.resolve(),
            base_command=["/tmp/unreviewed-python", "/fixture/generate.py"],
            environ={"PATH": os.pathsep.join(("/fixture/bin", "/usr/bin", "/bin"))},
        )


def test_isolation_rejects_substitute_launcher_with_same_resolved_target(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    substitute = tmp_path / "substitute-python"
    substitute.symlink_to(Path(sys.executable).resolve())

    with pytest.raises(
        LocalVideoUnavailable, match="local_video_python_runtime_binding_mismatch"
    ):
        _isolated_execution(
            request,
            output=request.output_path.resolve(),
            base_command=[str(substitute), "/fixture/generate.py"],
            environ={"PATH": os.pathsep.join(("/fixture/bin", "/usr/bin", "/bin"))},
        )


def test_sandbox_preflight_failure_creates_no_queue_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)

    def reject_preflight(**_kwargs: object) -> dict[str, object]:
        raise LocalVideoUnavailable("local_video_isolation_preflight_failed:exit_71")

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_sandbox_execution",
        reject_preflight,
    )
    monkeypatch.setattr(
        "reel_factory.local_video.default_local_generation_queue",
        lambda: pytest.fail("queue must not be opened before isolation preflight"),
    )

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_isolation_preflight_failed:exit_71",
    ):
        run_local_video(request, dry_run=False)

    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()
    assert not request.output_path.with_suffix(
        request.output_path.suffix + ".local_video.json"
    ).exists()
    assert not list(tmp_path.glob(".local_video_sandbox_*"))


def test_media_tool_discovery_failure_creates_no_queue_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)

    def reject_discovery(**_kwargs: object) -> dict[str, object]:
        raise LocalVideoUnavailable(
            "local_video_media_tool_discovery_preflight_failed:exit_72"
        )

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_imageio_ffmpeg_discovery",
        reject_discovery,
    )
    monkeypatch.setattr(
        "reel_factory.local_video.default_local_generation_queue",
        lambda: pytest.fail(
            "queue must not be opened before media-tool discovery succeeds"
        ),
    )

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_media_tool_discovery_preflight_failed:exit_72",
    ):
        run_local_video(request, dry_run=False)

    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()
    assert not request.output_path.with_suffix(
        request.output_path.suffix + ".local_video.json"
    ).exists()
    assert not list(tmp_path.glob(".local_video_sandbox_*"))


def test_unrelated_stripped_parent_variable_does_not_change_job_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", str(Path.home() / ".cache/uv"))
    monkeypatch.setenv("PATH", _uv_ephemeral_path("planner"))
    monkeypatch.delenv("UNRELATED_OPERATOR_SECRET", raising=False)
    without_secret = plan_local_video_job(request)

    monkeypatch.setenv("UNRELATED_OPERATOR_SECRET", "must-not-affect-child")
    with_secret = plan_local_video_job(request)

    assert with_secret == without_secret


def test_wan_t2v_omits_image_and_never_falls_back_to_one(tmp_path: Path) -> None:
    request = LocalVideoRequest(
        model_id="local_wan22_ti2v_5b_mlx",
        image_path=None,
        task="text_to_video",
        prompt="A woman walks through a bright city street with natural motion",
        output_path=tmp_path / "out.mp4",
        duration_seconds=6,
    )
    command = build_local_video_command(request, python_executable="python3")
    assert "--image" not in command
    assert command[command.index("--prompt") + 1] == request.prompt


def test_campaign_admission_rehashes_last_image_before_flf_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _image(tmp_path, "first.png")
    last = _image(tmp_path, "last.png")
    inputs = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, last)]
    model_id = "local_wan21_flf2v_14b_cuda"
    manifest_sha = "c" * 64
    revision = "fixture-revision"
    model_fingerprint = fingerprint(
        {
            "modelId": model_id,
            "modelRevision": revision,
            "modelManifestSha256": manifest_sha,
        }
    )
    identity = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": "profile-stacey",
    }
    intent = {
        "schema": "creator_os.content_intent.v1",
        "intentId": "intent-flf",
        "creatorIdentityProfileId": identity["profileId"],
        "sourceAssetFingerprints": [*inputs, "f" * 64],
    }
    recipe = {
        "schema": "creator_os.benchmark_recipe.v1",
        "recipeId": "recipe-flf",
        "inputFingerprints": inputs,
    }
    registry = {
        "schema": "creator_os.analyzer_registry.v1",
        "registryId": "registry-flf",
    }
    summary_fingerprint = "f" * 64
    decision_request = {
        "creatorId": "stacey",
        "identityProfileId": identity["profileId"],
        "identityProfileFingerprint": fingerprint(identity),
        "contentIntentId": intent["intentId"],
        "contentIntentFingerprint": fingerprint(intent),
        "taskKind": "first_last_frame_to_video",
        "capabilityCohort": "first_last_frame",
        "availableMemoryBytes": 48 * 1024**3,
    }
    approval = {
        "approvalEventId": "approval-flf",
        "approvalEventHash": "7" * 64,
        "candidateModelFingerprint": model_fingerprint,
        "candidateBenchmarkIds": ["benchmark-flf"],
        "taskKind": "first_last_frame_to_video",
        "hardwareFingerprint": "8" * 64,
        "evidenceFingerprint": "9" * 64,
    }
    cohort_key = {
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
    winning = {
        "arenaSummaryFingerprint": summary_fingerprint,
        "benchmarkIds": ["benchmark-flf"],
        "matchedArenaSampleIds": ["sample-flf"],
        "validArenaSampleIds": ["sample-flf"],
        "cohortKey": cohort_key,
        "promotionApproval": approval,
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
        "licensePolicy": LICENSE_POLICY,
        "licensePolicyFingerprint": LICENSE_FINGERPRINT,
    }
    decision_core = {
        "schema": "reel_factory.local_model_router_decision.v1",
        "request": decision_request,
        "consideredCandidates": [
            {
                "modelId": model_id,
                "modelFingerprint": model_fingerprint,
                "capabilityCohort": "first_last_frame",
                "benchmarkIds": ["benchmark-flf"],
                "arenaSummaryFingerprint": summary_fingerprint,
                "promotionApproval": approval,
                "runtimeBinding": RUNTIME_BINDING,
                "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
                "licensePolicy": LICENSE_POLICY,
                "licensePolicyFingerprint": LICENSE_FINGERPRINT,
                "score": 1.0,
                "exclusions": [],
            }
        ],
        "selectedModelId": model_id,
        "selectedModelFingerprint": model_fingerprint,
        "decisionId": "decision-flf",
        "winningEvidence": winning,
        "paidProviderFallbackAllowed": False,
        "legacyLocalMotionFallbackAllowed": False,
    }
    decision = {
        **decision_core,
        "decisionFingerprint": fingerprint(decision_core),
    }
    admission_core = {
        "schema": "campaign_factory.local_motion_admission.v1",
        "routerDecision": decision,
        "arenaSummary": {
            "summaryId": "summary-flf",
            "summaryFingerprint": summary_fingerprint,
            "planId": "plan-flf",
            "planFingerprint": "e" * 64,
            "purpose": "promotion_eligible",
        },
        "evidenceRecords": {
            "creatorIdentityProfile": identity,
            "contentIntent": intent,
            "executionPolicy": {
                "schema": "creator_os.execution_policy.v1",
                "policyId": "policy-flf",
            },
            "benchmarkRecipe": recipe,
            "analyzerRegistry": registry,
        },
        "inputFingerprints": inputs,
        "inputBindings": [
            {"role": "image", "sha256": inputs[0]},
            {"role": "last_image", "sha256": inputs[1]},
        ],
        "promotionInputCohort": [
            [
                {"role": "image", "sha256": inputs[0]},
                {"role": "last_image", "sha256": inputs[1]},
            ]
        ],
        "resourceSnapshot": {
            "schema": "campaign_factory.local_motion_resource_snapshot.v1",
            "routerAvailableMemoryBytes": decision_request["availableMemoryBytes"],
            "hardware": {"fingerprint": approval["hardwareFingerprint"]},
        },
    }
    admission = {
        **admission_core,
        "admissionFingerprint": fingerprint(admission_core),
    }
    request = LocalVideoRequest(
        model_id=model_id,
        image_path=first,
        last_image_path=last,
        prompt="Move naturally between the exact endpoint frames",
        output_path=tmp_path / "out.mp4",
        task="first_last_frame_to_video",
        benchmark_recipe=recipe,
        analyzer_registry=registry,
        execution_context="campaign_generation",
        local_motion_admission=admission,
    )
    deep_core = {
        "modelId": model_id,
        "manifestSha256": manifest_sha,
        "providerCalls": 0,
        "paidGeneration": False,
        "runtimeBinding": RUNTIME_BINDING,
        "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
    }
    capability = {
        "model": {
            "ready": True,
            "deepVerified": True,
            "manifest": {
                "revision": revision,
                "licenseId": LICENSE_POLICY["licenseId"],
                "commercialRevenueLimitUsd": None,
            },
            "manifestSha256": manifest_sha,
            "deepVerificationReceipt": {
                **deep_core,
                "verificationFingerprint": fingerprint(deep_core),
            },
        }
    }
    monkeypatch.setattr(
        "reel_factory.local_video.validate_local_model_router_decision",
        lambda _decision: None,
    )
    monkeypatch.setattr(
        "reel_factory.local_video.hardware_identity",
        lambda: {"fingerprint": approval["hardwareFingerprint"]},
    )
    binding = _validate_campaign_admission(request, capability=capability)
    assert binding["inputFingerprints"] == inputs
    assert intent["sourceAssetFingerprints"] != inputs

    last.write_bytes(b"substituted-last-frame")
    with pytest.raises(LocalVideoUnavailable, match="input_fingerprint_mismatch"):
        _validate_campaign_admission(request, capability=capability)


def test_explicit_lora_is_hashed_input_and_passed_to_supported_runtime(
    tmp_path: Path,
) -> None:
    lora = tmp_path / "creator.safetensors"
    lora.write_bytes(b"pinned-local-lora")
    register_local_lora(
        lora,
        lora_id="creator_test",
        compatible_model_ids=["local_wan22_ti2v_5b_mlx"],
        license_id="test-only",
        source_repository="local/test",
        source_revision="fixture-v1",
        apply=True,
    )
    request = _request(tmp_path, lora_path=lora)
    command = build_local_video_command(request, python_executable="python3")
    assert command[command.index("--lora") + 1] == str(lora.resolve())
    lineage = run_local_video(request, dry_run=True)
    assert lineage["lora"]["sha256"]


def test_longcat_requires_image_audio_and_uses_owned_offline_adapter(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    request = _request(
        tmp_path,
        model_id="local_longcat_avatar15_q4_mlx",
        audio_mode="source",
        audio_path=audio,
        task="audio_image_to_video",
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[1].endswith("/longcat_mlx_generate.py")
    assert command[command.index("--audio") + 1] == str(audio.resolve())
    assert command[command.index("--weights-root") + 1].endswith("/models")
    assert "--output-audio" not in command
    lineage = run_local_video(request, dry_run=True)
    assert lineage["request"]["steps"] == 8
    assert lineage["request"]["negativePrompt"] is None
    assert lineage["request"]["negativePromptApplied"] is False

    with pytest.raises(ValueError, match="exactly 8 DMD steps"):
        build_local_video_command(
            replace(request, steps=4),
            python_executable="python3",
        )


def test_wan_quality_command_uses_q4_dual_model_profile(tmp_path: Path) -> None:
    request = _request(tmp_path, model_id="local_wan22_i2v_a14b_q4_mlx")
    command = build_local_video_command(request, python_executable="python3")
    assert command[command.index("--model-dir") + 1].endswith("/q4")
    assert command[command.index("--guide-scale") + 1] == "3.5,3.5"
    assert command[command.index("--tiling") + 1] == "aggressive"
    assert command[command.index("--steps") + 1] == "20"
    assert command[command.index("--trim-first-frames") + 1] == "1"


def test_custom_model_directory_must_use_canonical_verified_layout(
    tmp_path: Path,
) -> None:
    custom = tmp_path / "substituted-model"
    custom.mkdir()
    request = replace(_request(tmp_path), model_dir=custom)
    capability = probe_local_video(request.model_id, model_dir=custom)
    assert capability["ready"] is False
    assert any(
        issue.startswith("custom_model_directory_layout_mismatch:")
        for issue in capability["issues"]
    )


def test_bound_execution_forbids_custom_model_directory_even_if_probe_passes(
    tmp_path: Path,
) -> None:
    request = replace(_request(tmp_path), model_dir=tmp_path / "custom-model")

    with pytest.raises(
        LocalVideoUnavailable,
        match="custom_model_dir_forbidden_for_bound_execution",
    ):
        plan_local_video_job(request)


def test_ltx_q8_supports_source_audio_and_first_last_frame(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    last = _image(tmp_path, "last.jpg")
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        audio_mode="source",
        audio_path=audio,
        last_image_path=last,
        task="audio_image_to_video",
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[:4] == ["python3", "-m", "ltx_pipelines_mlx.cli", "a2v"]
    assert command[command.index("--width") + 1] == "576"
    assert command[command.index("--height") + 1] == "1024"
    assert command[command.index("--stage1-steps") + 1] == "30"
    assert command[command.index("--audio") + 1] == str(audio.resolve())
    assert str(last.resolve()) in command
    assert "--low-ram" in command
    frames = int(command[command.index("--frames") + 1])
    assert frames == 145
    assert (frames - 1) % 8 == 0


def test_ltx_hq_generated_audio_is_explicit(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        audio_mode="generated",
        task="image_to_video",
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[:4] == ["python3", "-m", "ltx_pipelines_mlx.cli", "generate"]
    assert "--two-stages-hq" in command
    assert command[command.index("--stage1-steps") + 1] == "15"
    assert "--audio" not in command
    assert "--low-ram" in command


def test_ltx_q4_is_quantized_distilled_and_rejects_source_audio(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        model_id="local_ltx23_distilled_mlx",
        audio_mode="generated",
        task="image_to_video",
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[:4] == ["python3", "-m", "ltx_pipelines_mlx.cli", "generate"]
    assert "--distilled" in command
    assert "--low-ram" in command
    assert command[command.index("--tile-spatial") + 1] == "2"
    assert command[command.index("--model") + 1].endswith("LTX-2.3-MLX-Q4")

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    with pytest.raises(ValueError, match="does not support task"):
        build_local_video_command(
            replace(
                request,
                audio_mode="source",
                audio_path=audio,
                task="audio_image_to_video",
            ),
            python_executable="python3",
        )


def test_ltx_keyframe_retake_and_extend_are_explicit_q8_tasks(
    tmp_path: Path,
) -> None:
    start = _image(tmp_path, "start.jpg")
    end = _image(tmp_path, "end.jpg")
    keyframe = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        image_path=start,
        last_image_path=end,
        audio_mode="generated",
        task="keyframe_interpolation",
    )
    keyframe_command = build_local_video_command(keyframe, python_executable="python3")
    assert keyframe_command[3] == "keyframe"
    assert keyframe_command[keyframe_command.index("--start") + 1] == str(
        start.resolve()
    )
    assert keyframe_command[keyframe_command.index("--end") + 1] == str(end.resolve())

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    retake = _rebind_arena_source(
        replace(
            keyframe,
            image_path=None,
            last_image_path=None,
            source_video_path=source,
            task="video_retake",
            audio_mode="preserved",
            retake_start_frame=2,
            retake_end_frame=5,
        ),
        source,
    )
    retake_command = build_local_video_command(retake, python_executable="python3")
    assert retake_command[3] == "retake"
    assert "--no-regen-audio" in retake_command
    assert retake_command[retake_command.index("--video") + 1] == str(source.resolve())

    extend = replace(
        retake,
        task="video_extend",
        audio_mode="generated",
        retake_start_frame=None,
        retake_end_frame=None,
        extend_frames=3,
        extend_direction="after",
    )
    extend_command = build_local_video_command(extend, python_executable="python3")
    assert extend_command[3] == "extend"
    assert extend_command[extend_command.index("--extend-frames") + 1] == "3"
    assert extend_command[extend_command.index("--direction") + 1] == "after"

    lineage = run_local_video(retake, dry_run=True)
    assert lineage["sourceVideo"]["sha256"]
    assert lineage["request"]["task"] == "video_retake"
    assert lineage["request"]["retakeStartFrame"] == 2
    assert lineage["audio"]["mode"] == "preserved"
    assert lineage["providerCalls"] == 0
    assert lineage["paidGeneration"] is False


def test_arena_audio_binding_requires_canonical_exact_input_order(
    tmp_path: Path,
) -> None:
    source = _image(tmp_path, "source-with-audio.jpg")
    audio = tmp_path / "source-audio.wav"
    audio.write_bytes(b"source-audio")
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        image_path=source,
        audio_mode="source",
        audio_path=audio,
        task="audio_image_to_video",
    )
    expected = [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, audio)
    ]

    job = plan_local_video_job(request)
    assert request.benchmark_recipe is not None
    assert request.benchmark_recipe["inputFingerprints"] == expected
    assert job.benchmark_recipe_fingerprint == fingerprint(request.benchmark_recipe)

    wrong_recipe = {
        **dict(request.benchmark_recipe),
        "inputFingerprints": [expected[1], expected[0]],
    }
    binding_core = dict(request.arena_benchmark_binding)
    binding_core.pop("bindingFingerprint")
    binding_core["benchmarkRecipeFingerprint"] = fingerprint(wrong_recipe)
    wrong_request = replace(
        request,
        benchmark_recipe=wrong_recipe,
        arena_benchmark_binding={
            **binding_core,
            "bindingFingerprint": fingerprint(binding_core),
        },
    )
    with pytest.raises(
        LocalVideoUnavailable, match="arena_benchmark_recipe_input_mismatch"
    ):
        plan_local_video_job(wrong_request)


def test_wan_fails_closed_when_audio_is_requested(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    request = _request(
        tmp_path,
        audio_mode="source",
        audio_path=audio,
        task="audio_image_to_video",
    )
    with pytest.raises(
        ValueError,
        match="does not support task|does not accept audio|does not support audio",
    ):
        build_local_video_command(request, python_executable="python3")


def test_dry_run_records_exact_inputs_without_runner_or_provider_call(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        model_id="local_ltx23_distilled_mlx",
        audio_mode="generated",
        task="image_to_video",
    )

    def fail_runner(*_args, **_kwargs):
        raise AssertionError("dry-run must not execute")

    result = run_local_video(request, dry_run=True, runner=fail_runner)
    assert result["status"] == "planned"
    assert result["input"]["sha256"]
    assert result["providerCalls"] == 0
    assert result["paidGeneration"] is False
    assert result["audio"]["nativePlatformAudio"] is False
    assert result["schedulingAllowed"] is False
    assert result["publishingAllowed"] is False


def test_apply_is_offline_atomic_and_preserves_audio_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-local-model")
    monkeypatch.setenv("PYTHONPATH", "/tmp/untrusted-python-imports")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/tmp/untrusted-dylibs")
    monkeypatch.setenv(
        "CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(tmp_path / "queue")
    )
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"source-audio")
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        audio_mode="source",
        audio_path=audio,
        task="audio_image_to_video",
    )
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {
            "ready": True,
            "issues": [],
            "model": {
                "manifest": {"modelId": request.model_id},
                "manifestSha256": "a" * 64,
            },
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._validate_video",
        lambda *_a, **_k: {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._extract_audio_sidecar",
        lambda _video, wav: wav.write_bytes(b"preserved-audio"),
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def runner(command, **kwargs):
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        assert (
            kwargs["env"]["IMAGEIO_FFMPEG_EXE"] == RUNTIME_BINDING["ffmpegExecutable"]
        )
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        assert "DYLD_LIBRARY_PATH" not in kwargs["env"]
        assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert "(deny network*)" in command[2]
        assert "(deny file-write*" in command[2]
        assert command[command.index("--audio") + 1] == str(audio.resolve())
        video = Path(command[command.index("--output") + 1])
        assert video.name.endswith(".partial.mp4")
        video.write_bytes(b"generated-video")
        return Completed()

    planned_job = plan_local_video_job(request)
    result = run_local_video(request, dry_run=False, runner=runner)
    assert request.output_path.read_bytes() == b"generated-video"
    assert result["status"] == "completed"
    assert result["audio"]["mode"] == "source"
    assert result["audio"]["nativePlatformAudio"] is False
    assert result["audio"]["sidecarSha256"]
    isolation = result["executionIsolation"]
    assert isolation["enforced"] is True
    assert isolation["networkAccess"] == "denied"
    assert isolation["writeAccess"] == "explicit_artifacts_only"
    assert isolation["providerActivity"] == {
        "callsObserved": 0,
        "attemptsObserved": None,
        "successfulDirectSocketCallsPossible": False,
        "measurementScope": "successful_direct_socket_provider_calls",
        "observationMethod": "macos_sandbox_active_socket_denial_preflight",
        "enforcementStatus": "enforced",
        "evidenceBasis": (
            "tcp_bind_tcp_connect_and_udp_connect_denied_by_macos_sandbox"
        ),
    }
    assert result["providerCalls"] == 0
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_video.json").read_text()
    )
    assert lineage["status"] == "completed"
    queue = default_local_generation_queue(tmp_path / "queue")
    assert queue.states()[planned_job.job_id].job == planned_job


def test_promotion_execution_fails_closed_without_macos_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr("reel_factory.local_video._sandbox_executable", lambda: None)

    with pytest.raises(LocalVideoUnavailable, match="sandbox_exec_missing"):
        plan_local_video_job(request)


def test_apply_revalidates_selected_model_immediately_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(tmp_path / "queue")
    )
    request = _request(tmp_path)
    capabilities = iter(
        [
            {
                "ready": True,
                "issues": [],
                "modelId": request.model_id,
                "model": {"manifestSha256": "a" * 64},
            },
            {
                "ready": True,
                "issues": [],
                "modelId": request.model_id,
                "model": {"manifestSha256": "b" * 64},
            },
        ]
    )
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_args, **_kwargs: next(capabilities),
    )
    runner_called = False

    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("drifted model must not execute")

    with pytest.raises(LocalVideoUnavailable, match="execution_capability_drift"):
        run_local_video(request, dry_run=False, runner=runner)
    assert runner_called is False
    assert not request.output_path.exists()


def test_post_queue_isolation_preflight_drift_fails_terminally_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    monkeypatch.setenv("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(queue_root))
    request = _request(tmp_path)
    preflight_calls = 0

    def drifting_preflight(**kwargs: object) -> dict[str, object]:
        nonlocal preflight_calls
        preflight_calls += 1
        profile = str(kwargs["profile"])
        return {
            "schema": "reel_factory.local_sandbox_preflight.v1",
            "enforcementBinary": str(kwargs["sandbox_exec"]),
            "capabilityProbeExecutable": str(kwargs["python_executable"]),
            "capabilityProbeFingerprint": fingerprint(
                {"implementation": _SANDBOX_DENIAL_PROBE}
            ),
            "timeoutSeconds": 5,
            "controlProfileFingerprint": fingerprint(
                {"profile": "(version 1)\n(allow default)"}
            ),
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
            "probeGeneration": preflight_calls,
        }

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_sandbox_execution",
        drifting_preflight,
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_allowed_sandbox_write",
        lambda **_kwargs: pytest.fail(
            "allowed-write probe must not run after isolation evidence drifts"
        ),
    )
    runner_called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        raise AssertionError("drifted isolation must not execute generation")

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_isolation_preflight_drift",
    ):
        run_local_video(request, dry_run=False, runner=runner)

    assert preflight_calls == 2
    assert runner_called is False
    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()
    assert not request.output_path.with_suffix(".mp4.local_video.json").exists()

    states = default_local_generation_queue(queue_root).states()
    assert len(states) == 1
    state = next(iter(states.values()))
    assert state.status == "failed"
    assert state.last_event["eventType"] == "job_failed"
    assert state.last_event["payload"]["errorType"] == "LocalVideoUnavailable"
    assert state.last_event["payload"]["errorMessage"] == (
        "local_video_isolation_preflight_drift"
    )
    assert state.last_event["payload"]["failureClass"] == (
        "local_generation_runtime_error"
    )


def test_post_queue_media_tool_discovery_drift_fails_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    monkeypatch.setenv("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(queue_root))
    request = _request(tmp_path)
    discovery_calls = 0

    def drifting_discovery(**kwargs: object) -> dict[str, object]:
        nonlocal discovery_calls
        discovery_calls += 1
        return {
            "schema": "reel_factory.local_media_tool_discovery_preflight.v1",
            "consumer": "imageio_ffmpeg.get_ffmpeg_exe",
            "consumerProbeFingerprint": fingerprint(
                {"implementation": _IMAGEIO_FFMPEG_DISCOVERY_PROBE}
            ),
            "pythonExecutable": str(kwargs["python_executable"]),
            "expectedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "expectedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutable": str(kwargs["expected_ffmpeg"]),
            "observedFfmpegExecutableResolved": str(kwargs["expected_ffmpeg"]),
            "environmentFingerprint": fingerprint(kwargs["environment"]),
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "timeoutSeconds": 30,
            "discoverySucceeded": True,
            "probeGeneration": discovery_calls,
        }

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_imageio_ffmpeg_discovery",
        drifting_discovery,
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_allowed_sandbox_write",
        lambda **_kwargs: pytest.fail(
            "allowed-write probe must not run after media-tool discovery drifts"
        ),
    )
    runner_called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        raise AssertionError("drifted encoder discovery must not run generation")

    with pytest.raises(
        LocalVideoUnavailable,
        match="local_video_media_tool_discovery_preflight_drift",
    ):
        run_local_video(request, dry_run=False, runner=runner)

    assert discovery_calls == 2
    assert runner_called is False
    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()
    assert not request.output_path.with_suffix(".mp4.local_video.json").exists()

    states = default_local_generation_queue(queue_root).states()
    assert len(states) == 1
    state = next(iter(states.values()))
    assert state.status == "failed"
    assert state.last_event["eventType"] == "job_failed"
    assert state.last_event["payload"]["errorMessage"] == (
        "local_video_media_tool_discovery_preflight_drift"
    )


def test_post_queue_isolation_preflight_interrupts_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    monkeypatch.setenv("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(queue_root))
    request = _request(tmp_path)
    preflight_calls = 0

    def interrupted_preflight(**kwargs: object) -> dict[str, object]:
        nonlocal preflight_calls
        preflight_calls += 1
        if preflight_calls == 2:
            raise KeyboardInterrupt
        python = Path(str(kwargs["python_executable"]))
        return {
            "schema": "reel_factory.local_sandbox_preflight.v1",
            "enforcementBinary": str(kwargs["sandbox_exec"]),
            "capabilityProbeExecutable": str(python),
            "capabilityProbeExecutableResolved": str(python.resolve()),
            "capabilityProbeFingerprint": fingerprint(
                {"implementation": _SANDBOX_DENIAL_PROBE}
            ),
            "timeoutSeconds": 5,
            "controlProfileFingerprint": fingerprint(
                {"profile": "(version 1)\n(allow default)"}
            ),
            "controlProbeReturnCode": 15,
            "denialProbeReturnCode": 0,
            "profileFingerprint": fingerprint({"profile": kwargs["profile"]}),
            "executionSucceeded": True,
            "unscopedWriteDenied": True,
            "tcpBindDenied": True,
            "udpConnectDenied": True,
            "tcpConnectDenied": True,
            "temporaryControlWritesExpected": 1,
            "temporaryControlWritesCleaned": True,
            "residualArtifactWrites": 0,
        }

    monkeypatch.setattr(
        "reel_factory.local_video._preflight_sandbox_execution",
        interrupted_preflight,
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_allowed_sandbox_write",
        lambda **_kwargs: pytest.fail(
            "allowed-write probe must not run after isolation preflight interruption"
        ),
    )
    runner_called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        raise AssertionError("interrupted isolation must not execute generation")

    with pytest.raises(KeyboardInterrupt):
        run_local_video(request, dry_run=False, runner=runner)

    assert preflight_calls == 2
    assert runner_called is False
    assert not request.output_path.exists()
    assert not request.output_path.with_suffix(".partial.mp4").exists()

    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_video.json").read_text()
    )
    assert lineage["status"] == "interrupted"
    assert lineage["failure"] == "KeyboardInterrupt"
    assert lineage["executionStage"] == "isolation_preflight"

    states = default_local_generation_queue(queue_root).states()
    assert len(states) == 1
    state = next(iter(states.values()))
    assert state.status == "interrupted"
    assert state.last_event["eventType"] == "job_interrupted"
    assert state.last_event["payload"]["reason"] == "isolation_preflight_interrupted"
    assert state.last_event["payload"]["failureClass"] == "execution_interrupted"


def test_apply_rejects_short_source_audio_before_queue_or_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "short.wav"
    audio.write_bytes(b"short-source-audio")
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        audio_mode="source",
        audio_path=audio,
        task="audio_image_to_video",
    )
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {"ready": True, "issues": [], "model": {}},
    )
    monkeypatch.setattr(
        "reel_factory.local_video._preflight_local_inputs",
        lambda _request: (_ for _ in ()).throw(
            ValueError("local_video_source_audio_too_short:required=6:observed=2.000")
        ),
    )
    runner_called = False

    def runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("short audio must fail before inference")

    with pytest.raises(ValueError, match="source_audio_too_short"):
        run_local_video(request, dry_run=False, runner=runner)
    assert runner_called is False
    assert not request.output_path.exists()


def test_terminal_journal_failure_preserves_completed_artifacts_for_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    monkeypatch.setenv("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(queue_root))
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {
            "ready": True,
            "issues": [],
            "model": {"manifestSha256": "a" * 64},
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._validate_video",
        lambda *_a, **_k: {"streams": [{"codec_type": "video"}]},
    )
    runner_calls = 0

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def runner(command, **_kwargs):
        nonlocal runner_calls
        runner_calls += 1
        Path(command[command.index("--output-path") + 1]).write_bytes(
            b"completed-video"
        )
        return Completed()

    def fail_terminal_journal(*_args, **_kwargs):
        raise OSError("simulated terminal journal fsync failure")

    monkeypatch.setattr(
        "reel_factory.local_generation_queue.LocalGenerationQueue.succeed",
        fail_terminal_journal,
    )
    with pytest.raises(OSError, match="journal fsync failure"):
        run_local_video(request, dry_run=False, runner=runner)

    lineage_path = request.output_path.with_suffix(".mp4.local_video.json")
    lineage = json.loads(lineage_path.read_text())
    assert request.output_path.read_bytes() == b"completed-video"
    assert lineage["status"] == "completed"
    assert lineage["outputSha256"]
    assert runner_calls == 1

    queue = default_local_generation_queue(queue_root)
    with queue.worker_session():
        state = next(iter(queue.states().values()))
        assert state.status == "interrupted"
    recovered = queue.recover_completed_interruption(
        state.job.job_id,
        lineage_path=lineage_path,
        reason="operator verified completed artifacts after terminal fsync failure",
    )
    assert recovered.status == "succeeded"
    assert runner_calls == 1


def test_busy_machine_leaves_no_collision_and_same_request_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    monkeypatch.setenv("CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(queue_root))
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {
            "ready": True,
            "issues": [],
            "model": {"manifestSha256": "a" * 64},
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._validate_video",
        lambda *_a, **_k: {"streams": [{"codec_type": "video"}]},
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def runner(command, **_kwargs):
        Path(command[command.index("--output-path") + 1]).write_bytes(b"video")
        return Completed()

    held_queue = default_local_generation_queue(queue_root)
    with held_queue.worker_session():
        with pytest.raises(WorkerLeaseUnavailable, match="worker_busy"):
            run_local_video(request, dry_run=False, runner=runner)
    lineage_path = request.output_path.with_suffix(".mp4.local_video.json")
    assert not lineage_path.exists()
    assert not request.output_path.exists()

    result = run_local_video(request, dry_run=False, runner=runner)
    assert result["status"] == "completed"
    assert request.output_path.read_bytes() == b"video"


def test_interruption_keeps_honest_recoverable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "CREATOR_OS_LOCAL_GENERATION_QUEUE_ROOT", str(tmp_path / "queue")
    )
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {
            "ready": True,
            "issues": [],
            "model": {"manifestSha256": "a" * 64},
        },
    )

    def interrupted(_command, **_kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_local_video(request, dry_run=False, runner=interrupted)
    assert not request.output_path.exists()
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_video.json").read_text()
    )
    assert lineage["status"] == "interrupted"
    assert lineage["failure"] == "KeyboardInterrupt"
    assert lineage["executionStage"] == "generation_process"
    state = next(
        iter(default_local_generation_queue(tmp_path / "queue").states().values())
    )
    assert state.status == "interrupted"
    assert state.last_event["payload"]["reason"] == "generation_process_interrupted"
