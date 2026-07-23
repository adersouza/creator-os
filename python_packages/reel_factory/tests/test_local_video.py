from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from reel_factory.local_generation_queue import (
    WorkerLeaseUnavailable,
    default_local_generation_queue,
    fingerprint,
)
from reel_factory.local_lora_registry import register_local_lora
from reel_factory.local_video import (
    LocalVideoRequest,
    LocalVideoUnavailable,
    _run_generation_process,
    build_local_video_command,
    plan_local_video_job,
    probe_local_video,
    run_local_video,
)


@pytest.fixture(autouse=True)
def _stable_available_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reel_factory.local_video.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "reel_factory.local_video.shutil.which",
        lambda executable: (
            "/usr/bin/sandbox-exec" if executable == "sandbox-exec" else None
        ),
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
        lambda model_id, **_kwargs: {
            "ready": True,
            "issues": [],
            "modelId": model_id,
            "manifest": {"modelId": model_id, "revision": "fixture-revision"},
            "manifestSha256": "c" * 64,
            "deepVerified": True,
            "deepVerificationReceipt": None,
        },
    )


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
    recipe = {
        "schema": "creator_os.benchmark_recipe.v1",
        "recipeId": "fixture-recipe",
        "taskKind": task,
        "inputFingerprints": [source_sha256],
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
    binding_core = {
        "schema": "reel_factory.arena_benchmark_execution.v1",
        "sampleId": "fixture-sample",
        "blindedCandidateId": "fixture-candidate",
        "sourceSha256": source_sha256,
        "identityProfileId": "fixture-identity",
        "identityProfileFingerprint": "a" * 64,
        "contentIntentId": "fixture-intent",
        "contentIntentFingerprint": "b" * 64,
        "benchmarkRecipeFingerprint": fingerprint(recipe),
        "analyzerRegistryFingerprint": fingerprint(registry),
        "modelDeepVerificationFingerprint": "d" * 64,
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
    recipe = {
        **dict(request.benchmark_recipe or {}),
        "inputFingerprints": [source_sha256],
        "taskKind": request.task,
    }
    core = dict(request.arena_benchmark_binding or {})
    core.pop("bindingFingerprint", None)
    core["sourceSha256"] = source_sha256
    core["benchmarkRecipeFingerprint"] = fingerprint(recipe)
    return replace(
        request,
        benchmark_recipe=recipe,
        arena_benchmark_binding={
            **core,
            "bindingFingerprint": fingerprint(core),
        },
    )


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
        "measurementScope": "isolated_generation_subprocess",
        "observationMethod": "macos_sandbox_network_policy",
        "enforcementStatus": "enforced",
        "evidenceBasis": "external_network_denied_by_macos_sandbox",
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
    monkeypatch.setattr("reel_factory.local_video.shutil.which", lambda _name: None)

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
