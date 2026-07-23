from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path

import pytest
from reel_factory.local_generation_queue import (
    AppendOnlyJournal,
    JournalCorruptionError,
    LocalGenerationJob,
    LocalGenerationQueue,
    LocalQueueError,
    WorkerLeaseUnavailable,
    default_local_generation_queue,
)
from reel_factory.local_generation_queue import (
    fingerprint as queue_fingerprint,
)

GIB = 1024**3


def test_default_queue_never_claims_more_than_small_host_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "reel_factory.local_generation_queue._physical_memory_bytes",
        lambda: 4 * GIB,
    )
    queue = default_local_generation_queue(tmp_path / "queue")
    assert queue.resource_limit_bytes == 4 * GIB
    assert queue.memory_reserve_bytes == 6 * GIB


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _job(
    job_id: str,
    *,
    memory: int = GIB,
    model: str = "wan-test",
    input_value: str | None = None,
) -> LocalGenerationJob:
    return LocalGenerationJob.create(
        job_id=job_id,
        model_id=model,
        model_revision="revision-1",
        model_manifest_sha256=_sha(model),
        task_kind="image_to_video",
        input_sha256=_sha(input_value or job_id),
        requested_memory_bytes=memory,
        params={"frames": 81, "seed": 7},
    )


def test_queue_round_trips_exact_identity_and_intent_evidence(tmp_path: Path) -> None:
    profile = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": "profile-stacey",
    }
    intent = {
        "schema": "creator_os.content_intent.v1",
        "intentId": "intent-motion",
        "creatorIdentityProfileId": profile["profileId"],
    }
    job = LocalGenerationJob.create(
        job_id="record-bound",
        model_id="wan-test",
        model_revision="revision-1",
        model_manifest_sha256=_sha("wan-test"),
        task_kind="image_to_video",
        input_sha256=_sha("input"),
        requested_memory_bytes=GIB,
        params={"seed": 7},
        creator_identity_profile=profile,
        content_intent=intent,
    )
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    queue.submit(job)
    replayed = (
        LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
        .states()[job.job_id]
        .job
    )
    assert replayed == job
    assert replayed.creator_identity_profile_fingerprint == queue_fingerprint(profile)
    assert replayed.content_intent_fingerprint == queue_fingerprint(intent)

    with pytest.raises(
        ValueError, match="identity_intent_evidence_records_must_be_paired"
    ):
        LocalGenerationJob.create(
            job_id="partial-record-link",
            model_id="wan-test",
            model_revision="revision-1",
            model_manifest_sha256=_sha("wan-test"),
            task_kind="image_to_video",
            input_sha256=_sha("input"),
            requested_memory_bytes=GIB,
            params={"seed": 7},
            creator_identity_profile=profile,
        )


def _interrupted_recovery_fixture(
    queue: LocalGenerationQueue, root: Path, *, job_id: str = "retry"
) -> tuple[LocalGenerationJob, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    output = (root / "render.mp4").resolve()
    lineage_path = output.with_suffix(output.suffix + ".local_video.json")
    partial = output.with_suffix(".partial" + output.suffix)
    manifest_sha = _sha("wan-test")
    request = {
        "prompt": "subtle natural motion",
        "negativePrompt": "bad",
        "negativePromptApplied": True,
        "durationSeconds": 6,
        "resolution": "720x1280",
        "fps": 24,
        "steps": 8,
        "seed": 7,
        "pipeline": "wan",
        "task": "image_to_video",
    }
    inputs = {"image": None, "audio": None, "lastImage": None, "lora": None}
    command = ["python", "-m", "mlx_video", "--output-path", str(partial)]
    params = {
        "command": command,
        "outputPath": str(output),
        "task": "image_to_video",
        "durationSeconds": 6,
        "seed": 7,
    }
    cohort_input_sha = queue_fingerprint(
        {"image": None, "audio": None, "lastImage": None}
    )
    cohort = {
        "sourceInputSha256": cohort_input_sha,
        "task": "image_to_video",
        "prompt": "subtle natural motion",
        "durationSeconds": 6,
        "seed": 7,
        "audioMode": "none",
    }
    job = LocalGenerationJob.create(
        job_id=job_id,
        model_id="wan-test",
        model_revision="revision-1",
        model_manifest_sha256=manifest_sha,
        task_kind="image_to_video",
        input_sha256=queue_fingerprint(inputs),
        requested_memory_bytes=GIB,
        params=params,
        cohort=cohort,
        owned_artifact_paths=(
            output,
            partial,
            lineage_path,
            output.with_suffix(output.suffix + ".audio.wav"),
            output.with_suffix(output.suffix + ".audio.wav").with_suffix(
                ".partial.wav"
            ),
        ),
    )
    lineage = {
        "schema": "reel_factory.local_video_generation.v1",
        "modelId": "wan-test",
        "modelRevision": "revision-1",
        "modelManifestSha256": manifest_sha,
        "input": None,
        "sourceAudio": None,
        "lastImage": None,
        "lora": None,
        "audio": {"mode": "none"},
        "request": request,
        "command": command,
        "outputPath": str(output),
        "queue": {"jobId": job_id},
        "status": "interrupted",
    }
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    partial.write_bytes(b"partial evidence")
    queue.submit(job)
    with queue.worker_session() as lease:
        queue.start_next(lease)
        queue.verify_generated_artifacts(
            lease,
            job_id,
            partial_output_path=partial,
            final_output_path=output,
            output_probe={"streams": [{"codec_type": "video"}]},
            execution_measurement={
                "wallTimeSeconds": 1.0,
                "peakMemoryBytes": GIB,
                "memoryMeasurementMethod": "test-fresh-child-peak",
            },
        )
        queue.interrupt(lease, job_id, reason="operator stopped run")
    return job, lineage_path, partial


def _hold_worker(root: str, ready: multiprocessing.connection.Connection) -> None:
    queue = LocalGenerationQueue(Path(root), resource_limit_bytes=2 * GIB)
    with queue.worker_session():
        ready.send("locked")
        ready.recv()


def _submit_same_job(
    root: str,
    ready: multiprocessing.connection.Connection,
) -> None:
    queue = LocalGenerationQueue(Path(root), resource_limit_bytes=2 * GIB)
    ready.recv()
    queue.submit(_job("shared"))
    ready.send("submitted")


def test_submit_is_idempotent_but_rejects_job_id_fingerprint_conflict(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    original = _job("job-1")
    assert queue.submit(original).status == "queued"
    assert queue.submit(original).status == "queued"
    assert len(queue.journal.read().events) == 1

    with pytest.raises(LocalQueueError, match="job_id_fingerprint_conflict"):
        queue.submit(_job("job-1", model="other-model"))


def test_worker_lease_is_cross_process_and_nonblocking(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_worker, args=(str(tmp_path), child))
    process.start()
    assert parent.recv() == "locked"
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    with pytest.raises(WorkerLeaseUnavailable, match="worker_busy"):
        with queue.worker_session():
            pass
    parent.send("release")
    process.join(timeout=10)
    assert process.exitcode == 0


def test_concurrent_identical_submit_is_exactly_once(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    parent_a, child_a = context.Pipe()
    parent_b, child_b = context.Pipe()
    processes = [
        context.Process(target=_submit_same_job, args=(str(tmp_path), child_a)),
        context.Process(target=_submit_same_job, args=(str(tmp_path), child_b)),
    ]
    for process in processes:
        process.start()
    parent_a.send("go")
    parent_b.send("go")
    assert {parent_a.recv(), parent_b.recv()} == {"submitted"}
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    events = queue.journal.read().events
    assert len(events) == 1
    assert events[0]["eventType"] == "job_submitted"


def test_resource_admission_fails_closed_and_keeps_job_queued(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("too-large", memory=3 * GIB))
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)

    assert not decision.admitted
    assert decision.reason == "requested_memory_exceeds_resource_limit"
    assert queue.states()["too-large"].status == "queued"
    assert (
        queue.states()["too-large"].last_event["eventType"] == "job_admission_blocked"
    )


def test_oversized_job_does_not_starve_a_later_admissible_job(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("too-large", memory=3 * GIB))
    queue.submit(_job("fits", memory=GIB))
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)
        assert decision.admitted
        assert decision.job_id == "fits"
        queue.interrupt(lease, "fits", reason="test cleanup")
    assert queue.states()["too-large"].status == "queued"


def test_fifo_start_and_success_preserve_exact_output_fingerprint(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("first"))
    queue.submit(_job("second"))
    output_sha = _sha("output")
    output = tmp_path / "out.mp4"
    output.write_bytes(b"output")
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)
        assert decision.job_id == "first"
        completed = queue.succeed(
            lease, "first", output_sha256=output_sha, output_path=output
        )
    assert completed.status == "succeeded"
    assert completed.last_event["payload"]["outputSha256"] == output_sha
    evidence = queue.execution_evidence("first")
    assert evidence["attemptCount"] == 1
    assert evidence["retryCount"] == 0
    assert evidence["failureClass"] is None
    assert evidence["localCost"] == {
        "available": False,
        "currency": "USD",
        "reason": "local_compute_cost_not_metered",
        "value": None,
    }
    assert queue.states()["second"].status == "queued"


def test_exact_submission_never_starts_an_unowned_backlog_job(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("older"))
    with queue.worker_session() as lease:
        with pytest.raises(
            LocalQueueError, match="queue_backlog_requires_operator_recovery:older"
        ):
            queue.submit_and_start_exact(lease, _job("current"))
    states = queue.states()
    assert states["older"].status == "queued"
    assert "current" not in states


def test_success_rejects_missing_or_substituted_output(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("output-check"))
    with queue.worker_session() as lease:
        queue.start_next(lease)
        with pytest.raises(LocalQueueError, match="job_output_missing"):
            queue.succeed(
                lease,
                "output-check",
                output_sha256=_sha("expected"),
                output_path=tmp_path / "missing.mp4",
            )
        wrong = tmp_path / "wrong.mp4"
        wrong.write_bytes(b"wrong")
        with pytest.raises(LocalQueueError, match="job_output_sha256_mismatch"):
            queue.succeed(
                lease,
                "output-check",
                output_sha256=_sha("expected"),
                output_path=wrong,
            )
        queue.interrupt(lease, "output-check", reason="test cleanup")


def test_failed_job_records_honest_error_and_is_terminal(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("broken"))
    with queue.worker_session() as lease:
        queue.start_next(lease)
        failed = queue.fail(lease, "broken", error=RuntimeError("model exploded"))
    assert failed.status == "failed"
    assert failed.last_event["payload"]["errorType"] == "RuntimeError"
    assert failed.last_event["payload"]["errorMessage"] == "model exploded"
    evidence = queue.execution_evidence("broken")
    assert evidence["attemptCount"] == 1
    assert evidence["retryCount"] == 0
    assert evidence["failureClass"] == "local_generation_runtime_error"
    assert evidence["executionMeasurement"] == {
        "available": False,
        "reason": "execution_measurement_unavailable",
    }


def test_admission_block_is_counted_without_inventing_execution_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = LocalGenerationQueue(
        tmp_path, resource_limit_bytes=2 * GIB, memory_reserve_bytes=GIB
    )
    monkeypatch.setattr(
        "reel_factory.local_generation_queue._macos_available_memory_bytes",
        lambda: GIB,
    )
    queue.submit(_job("blocked"))
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)
    assert not decision.admitted
    evidence = queue.execution_evidence("blocked")
    assert evidence["attemptCount"] == 0
    assert evidence["retryCount"] == 0
    assert evidence["admissionBlockCount"] == 1
    assert evidence["failureClass"] == "resource_admission_blocked"


def test_abandoned_running_job_becomes_interrupted_on_next_lease(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("abandoned"))
    with queue.worker_session() as lease:
        queue.start_next(lease)
        assert queue.states()["abandoned"].status == "running"

    assert queue.states()["abandoned"].status == "running"
    with queue.worker_session():
        recovered = queue.states()["abandoned"]
        assert recovered.status == "interrupted"
        assert (
            recovered.last_event["payload"]["reason"]
            == "previous_worker_released_without_terminal_event"
        )


def test_interrupted_recovery_quarantines_artifacts_and_replays(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job, lineage, partial = _interrupted_recovery_fixture(queue, tmp_path / "outputs")
    recovery = queue.recover_interrupted(
        job.job_id, lineage_path=lineage, reason="operator verified exact inputs"
    )
    assert recovery.state.status == "queued"
    assert not lineage.exists()
    assert not partial.exists()
    assert recovery.manifest_path.is_file()
    assert (recovery.manifest_path.parent / "completed.json").is_file()
    for artifact in recovery.artifacts:
        quarantined = Path(str(artifact["quarantinePath"]))
        assert quarantined.is_file()
        assert (
            hashlib.sha256(quarantined.read_bytes()).hexdigest() == artifact["sha256"]
        )

    replayed = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    assert replayed.states()[job.job_id].status == "queued"
    with replayed.worker_session() as lease:
        decision = replayed.submit_and_start_exact(lease, job)
        assert decision.job_id == job.job_id
        replayed.interrupt(lease, job.job_id, reason="test cleanup")


def test_interrupted_recovery_rejects_forged_lineage_without_mutation(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job, lineage, partial = _interrupted_recovery_fixture(queue, tmp_path / "outputs")
    payload = json.loads(lineage.read_text(encoding="utf-8"))
    payload["request"]["prompt"] = "forged request"
    lineage.write_text(json.dumps(payload), encoding="utf-8")
    lineage_before = lineage.read_bytes()
    partial_before = partial.read_bytes()

    with pytest.raises(LocalQueueError, match="task_fingerprint_mismatch"):
        queue.recover_interrupted(
            job.job_id, lineage_path=lineage, reason="should not move"
        )
    assert lineage.read_bytes() == lineage_before
    assert partial.read_bytes() == partial_before
    assert not (queue.root / "recovery").exists()
    assert queue.states()[job.job_id].status == "interrupted"


def test_empty_interruption_requeues_only_when_all_owned_paths_are_absent(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    output = (tmp_path / "outputs/render.mp4").resolve()
    lineage = output.with_suffix(output.suffix + ".local_video.json")
    job = LocalGenerationJob.create(
        job_id="crash-before-lineage",
        model_id="wan-test",
        model_revision="revision-1",
        model_manifest_sha256=_sha("wan-test"),
        task_kind="image_to_video",
        input_sha256=_sha("input"),
        requested_memory_bytes=GIB,
        params={"outputPath": str(output)},
        owned_artifact_paths=(output, lineage, output.with_suffix(".partial.mp4")),
    )
    with queue.worker_session() as lease:
        queue.submit_and_start_exact(lease, job)
    with queue.worker_session():
        assert queue.states()[job.job_id].status == "interrupted"

    recovered = queue.recover_empty_interruption(
        job.job_id,
        lineage_path=lineage,
        reason="operator verified crash happened before any artifact write",
    )
    assert recovered.status == "queued"
    with queue.worker_session() as lease:
        decision = queue.submit_and_start_exact(lease, job)
        assert decision.admitted is True
        queue.interrupt(lease, job.job_id, reason="test cleanup")


def test_completed_interruption_is_finalized_without_rerunning(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job, lineage_path, partial = _interrupted_recovery_fixture(
        queue, tmp_path / "outputs", job_id="completed-before-terminal-event"
    )
    output = Path(json.loads(lineage_path.read_text())["outputPath"])
    partial.replace(output)
    lineage = json.loads(lineage_path.read_text())
    lineage.update(
        {
            "status": "completed",
            "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "outputProbe": {"streams": [{"codec_type": "video"}]},
            "executionMeasurement": {
                "wallTimeSeconds": 1.0,
                "peakMemoryBytes": GIB,
                "memoryMeasurementMethod": "test-fresh-child-peak",
            },
        }
    )
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    recovered = queue.recover_completed_interruption(
        job.job_id,
        lineage_path=lineage_path,
        reason="operator verified completed lineage and output after power loss",
    )
    assert recovered.status == "succeeded"
    assert recovered.last_event["payload"]["outputSha256"] == lineage["outputSha256"]
    assert output.read_bytes() == b"partial evidence"
    assert lineage_path.is_file()


def test_completed_interruption_rejects_lineage_measurement_tampering(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job, lineage_path, partial = _interrupted_recovery_fixture(
        queue, tmp_path / "outputs", job_id="tampered-completed"
    )
    output = Path(json.loads(lineage_path.read_text())["outputPath"])
    partial.replace(output)
    lineage = json.loads(lineage_path.read_text())
    lineage.update(
        {
            "status": "completed",
            "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "outputProbe": {"streams": [{"codec_type": "video"}]},
            "executionMeasurement": {
                "wallTimeSeconds": 1.0,
                "peakMemoryBytes": 999,
                "memoryMeasurementMethod": "forged",
            },
        }
    )
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    with pytest.raises(LocalQueueError, match="measurement_mismatch"):
        queue.recover_completed_interruption(
            job.job_id,
            lineage_path=lineage_path,
            reason="must reject mutated result evidence",
        )
    assert queue.states()[job.job_id].status == "interrupted"
    assert output.read_bytes() == b"partial evidence"


def test_completed_interruption_does_not_reuse_prior_attempt_verification(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job, lineage_path, _partial = _interrupted_recovery_fixture(
        queue, tmp_path / "outputs", job_id="second-attempt-no-verification"
    )
    original_lineage = json.loads(lineage_path.read_text())
    queue.recover_interrupted(
        job.job_id,
        lineage_path=lineage_path,
        reason="operator quarantined first attempt",
    )
    with queue.worker_session() as lease:
        queue.submit_and_start_exact(lease, job)
        queue.interrupt(lease, job.job_id, reason="second attempt crashed early")

    output = Path(original_lineage["outputPath"])
    output.write_bytes(b"partial evidence")
    original_lineage.update(
        {
            "status": "completed",
            "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "outputProbe": {"streams": [{"codec_type": "video"}]},
            "executionMeasurement": {
                "wallTimeSeconds": 1.0,
                "peakMemoryBytes": GIB,
                "memoryMeasurementMethod": "test-fresh-child-peak",
            },
        }
    )
    lineage_path.write_text(json.dumps(original_lineage), encoding="utf-8")

    with pytest.raises(LocalQueueError, match="exactly_one_artifact_verification"):
        queue.recover_completed_interruption(
            job.job_id,
            lineage_path=lineage_path,
            reason="must not reuse first attempt evidence",
        )
    assert queue.states()[job.job_id].status == "interrupted"


def test_resource_blocked_exact_request_can_retry_when_memory_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reel_factory.local_generation_queue as module

    available = 2 * GIB
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module, "_macos_available_memory_bytes", lambda: available)
    queue = LocalGenerationQueue(
        tmp_path,
        resource_limit_bytes=4 * GIB,
        memory_reserve_bytes=GIB,
    )
    job = _job("memory-retry", memory=2 * GIB)
    with queue.worker_session() as lease:
        with pytest.raises(
            LocalQueueError, match="insufficient_current_available_memory"
        ):
            queue.submit_and_start_exact(lease, job)
    assert queue.states()[job.job_id].status == "queued"

    available = 4 * GIB
    with queue.worker_session() as lease:
        decision = queue.submit_and_start_exact(lease, job)
        assert decision.admitted
        queue.interrupt(lease, job.job_id, reason="test cleanup")


def test_queued_admission_can_be_explicitly_retired_without_deletion(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    queue.submit(_job("retire"))
    state = queue.cancel_queued("retire", reason="operator selected another request")
    assert state.status == "cancelled"
    assert state.last_event["payload"]["automatic"] is False
    replayed = LocalGenerationQueue(tmp_path, resource_limit_bytes=2 * GIB)
    assert replayed.states()["retire"].status == "cancelled"


def test_malformed_journal_fails_closed_until_explicit_recovery(tmp_path: Path) -> None:
    journal = AppendOnlyJournal(tmp_path / "jobs.jsonl")
    journal.append("clean", {"value": 1})
    with journal.path.open("ab") as handle:
        handle.write(b'{"partial":')
    with pytest.raises(JournalCorruptionError, match="journal_corrupt"):
        journal.read()

    recovery = journal.acknowledge_corruption()
    assert recovery is not None
    replay = journal.read()
    assert [event["eventType"] for event in replay.events] == [
        "clean",
        "journal_recovery_recorded",
    ]


def test_hash_chain_tampering_is_detected(tmp_path: Path) -> None:
    journal = AppendOnlyJournal(tmp_path / "jobs.jsonl")
    journal.append("clean", {"value": 1})
    text = journal.path.read_text(encoding="utf-8").replace('"value":1', '"value":2')
    journal.path.write_text(text, encoding="utf-8")
    with pytest.raises(JournalCorruptionError, match="journal_corrupt"):
        journal.read()


def test_job_fingerprints_bind_model_task_input_and_parameters() -> None:
    first = _job("one", input_value="shared")
    second = _job("two", input_value="shared")
    other_model = _job("three", input_value="shared", model="other")
    assert first.task_fingerprint == second.task_fingerprint
    assert first.model_fingerprint == second.model_fingerprint
    assert other_model.model_fingerprint != first.model_fingerprint


def test_queue_module_contains_no_provider_or_publish_integration() -> None:
    import reel_factory.local_generation_queue as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "requests" not in source
    assert "qstash" not in source.lower()
    assert "threadsdashboard" not in source.lower()
    assert "supabase" not in source.lower()
