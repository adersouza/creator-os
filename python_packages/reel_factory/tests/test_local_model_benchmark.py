from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from reel_factory.local_generation_queue import LocalGenerationJob, LocalGenerationQueue
from reel_factory.local_model_benchmark import (
    PROMOTION_MEMORY_MEASUREMENT_METHOD,
    BenchmarkReceipt,
    LocalExecutionMeasurement,
    LocalModelBenchmarkStore,
    PromotionPolicy,
    QCReference,
)
from reel_factory.local_model_benchmark import (
    main as benchmark_main,
)

GIB = 1024**3


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _job(job_id: str, model: str, task_input: str) -> LocalGenerationJob:
    return LocalGenerationJob.create(
        job_id=job_id,
        model_id=model,
        model_revision="revision-1",
        model_manifest_sha256=_sha(model),
        task_kind="image_to_video",
        input_sha256=_sha(task_input),
        requested_memory_bytes=GIB,
        params={"frames": 81, "seed": 9},
    )


def _qc(
    name: str = "contentforge.motion_specific_qc",
    *,
    passed: bool = True,
    subject_sha256: str | None = None,
    receipt_uri: str | None = None,
    receipt_sha256: str | None = None,
) -> tuple[QCReference, ...]:
    return (
        QCReference(
            check_id=name,
            receipt_uri=receipt_uri or f"evidence/{name}.json",
            receipt_sha256=receipt_sha256 or _sha(name),
            subject_sha256=subject_sha256 or _sha("output"),
            passed=passed,
        ),
    )


def _write_qc(
    store: LocalModelBenchmarkStore,
    *,
    job_id: str,
    subject_sha256: str,
    passed: bool,
) -> tuple[QCReference, ...]:
    relative = Path("evidence") / f"{job_id}.json"
    receipt = store.root / relative
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "policy": {
                    "id": "contentforge.motion_specific_qc",
                    "version": "1.0.0",
                },
                "passed": passed,
                "subjectSha256": subject_sha256,
            }
        ),
        encoding="utf-8",
    )
    return _qc(
        passed=passed,
        subject_sha256=subject_sha256,
        receipt_uri=str(relative),
        receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
    )


def _complete_and_benchmark(
    queue: LocalGenerationQueue,
    store: LocalModelBenchmarkStore,
    job: LocalGenerationJob,
    *,
    benchmark_id: str,
    qc_passed: bool = True,
) -> BenchmarkReceipt:
    measurement = LocalExecutionMeasurement(
        wall_time_seconds=0.01,
        peak_memory_bytes=GIB,
        memory_measurement_method=PROMOTION_MEMORY_MEASUREMENT_METHOD,
    )
    output = queue.root / f"{job.job_id}.mp4"
    partial = output.with_suffix(".partial.mp4")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(f"output-{job.job_id}".encode())
    job = replace(
        job,
        owned_artifact_paths=(str(output.resolve()), str(partial.resolve())),
    )
    queue.submit(job)
    output_sha256 = _sha(f"output-{job.job_id}")
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)
        assert decision.job_id == job.job_id
        queue.verify_generated_artifacts(
            lease,
            job.job_id,
            partial_output_path=partial,
            final_output_path=output,
            output_probe={"streams": [{"codec_type": "video"}]},
            execution_measurement={
                "wallTimeSeconds": measurement.wall_time_seconds,
                "peakMemoryBytes": measurement.peak_memory_bytes,
                "memoryMeasurementMethod": measurement.memory_measurement_method,
            },
        )
        partial.replace(output)
        queue.succeed(
            lease,
            job.job_id,
            output_sha256=output_sha256,
            output_path=output,
            execution_measurement={
                "wallTimeSeconds": measurement.wall_time_seconds,
                "peakMemoryBytes": measurement.peak_memory_bytes,
                "memoryMeasurementMethod": measurement.memory_measurement_method,
            },
        )
    return store.record_completed_job(
        queue,
        job_id=job.job_id,
        qc_references=_write_qc(
            store,
            job_id=job.job_id,
            subject_sha256=output_sha256,
            passed=qc_passed,
        ),
        benchmark_id=benchmark_id,
    )


def _complete_queue_job(
    queue: LocalGenerationQueue, job: LocalGenerationJob
) -> LocalGenerationJob:
    output = queue.root / f"{job.job_id}.mp4"
    partial = output.with_suffix(".partial.mp4")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(f"output-{job.job_id}".encode())
    job = replace(
        job,
        owned_artifact_paths=(str(output.resolve()), str(partial.resolve())),
    )
    measurement = {
        "wallTimeSeconds": 1.0,
        "peakMemoryBytes": 1,
        "memoryMeasurementMethod": PROMOTION_MEMORY_MEASUREMENT_METHOD,
    }
    queue.submit(job)
    with queue.worker_session() as lease:
        queue.start_next(lease)
        queue.verify_generated_artifacts(
            lease,
            job.job_id,
            partial_output_path=partial,
            final_output_path=output,
            output_probe={"streams": [{"codec_type": "video"}]},
            execution_measurement=measurement,
        )
        partial.replace(output)
        queue.succeed(
            lease,
            job.job_id,
            output_sha256=_sha(f"output-{job.job_id}"),
            output_path=output,
            execution_measurement=measurement,
        )
    return job


def test_benchmark_is_bound_to_succeeded_job_and_measured_hardware(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    receipt = _complete_and_benchmark(queue, store, job, benchmark_id="benchmark-1")
    assert receipt.source == "measured_local_execution"
    assert receipt.wall_time_seconds > 0
    assert receipt.peak_memory_bytes > 0
    assert receipt.hardware_fingerprint
    assert receipt.model_fingerprint == job.model_fingerprint
    assert receipt.task_fingerprint == job.task_fingerprint
    assert receipt.output_sha256 == _sha("output-job")
    assert receipt.qc_references[0].subject_sha256 == receipt.output_sha256


def test_benchmark_rejects_nonterminal_job(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    queue.submit(_job("queued", "wan", "shot-a"))
    with pytest.raises(RuntimeError, match="requires_succeeded_job"):
        store.record_completed_job(
            queue,
            job_id="queued",
            qc_references=_qc(subject_sha256=_sha("output-job")),
        )


def test_benchmark_rejects_success_without_measured_terminal_event(
    tmp_path: Path,
) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    queue.submit(job)
    output = queue.root / "job.mp4"
    output.write_bytes(b"output-job")
    with queue.worker_session() as lease:
        queue.start_next(lease)
        queue.succeed(
            lease,
            job.job_id,
            output_sha256=_sha("output-job"),
            output_path=output,
        )
    with pytest.raises(RuntimeError, match="missing_execution_measurement"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_qc(subject_sha256=_sha("output-job")),
        )


def test_synthetic_benchmark_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="must_be_measured"):
        BenchmarkReceipt(
            benchmark_id="fake",
            job_id="fake",
            model_fingerprint="model",
            task_fingerprint="task",
            task_kind="image_to_video",
            hardware_fingerprint="hardware",
            output_sha256=_sha("output"),
            wall_time_seconds=1,
            peak_memory_bytes=1,
            memory_measurement_method="made-up",
            qc_references=_qc(subject_sha256=_sha("output-job")),
            source="synthetic",
        )


def test_missing_qc_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="QC reference"):
        BenchmarkReceipt(
            benchmark_id="missing-qc",
            job_id="job",
            model_fingerprint="model",
            task_fingerprint="task",
            task_kind="image_to_video",
            hardware_fingerprint="hardware",
            output_sha256=_sha("output"),
            wall_time_seconds=1,
            peak_memory_bytes=1,
            memory_measurement_method="resource",
            qc_references=(),
        )


def test_missing_or_substituted_qc_receipt_is_rejected(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    _complete_queue_job(queue, job)
    with pytest.raises(RuntimeError, match="qc_receipt_missing"):
        store.record_completed_job(
            queue,
            job_id="job",
            qc_references=_qc(subject_sha256=_sha("output-job")),
        )
    receipt = store.root / "evidence" / "contentforge.motion_specific_qc.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(b"substituted")
    with pytest.raises(RuntimeError, match="qc_receipt_sha256_mismatch"):
        store.record_completed_job(
            queue,
            job_id="job",
            qc_references=_qc(subject_sha256=_sha("output-job")),
        )


def test_qc_caller_verdict_must_match_bound_receipt(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    _complete_queue_job(queue, job)
    relative = Path("evidence") / "false.json"
    receipt_path = store.root / relative
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "policy": {
                    "id": "contentforge.motion_specific_qc",
                    "version": "1.0.0",
                },
                "subjectSha256": _sha("output-job"),
                "passed": False,
            }
        ),
        encoding="utf-8",
    )
    forged = QCReference(
        check_id="contentforge.motion_specific_qc",
        receipt_uri=str(relative),
        receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        subject_sha256=_sha("output-job"),
        passed=True,
    )
    with pytest.raises(RuntimeError, match="passed_mismatch"):
        store.record_completed_job(queue, job_id="job", qc_references=(forged,))


def test_operator_qc_ingest_rejects_unsupported_policy(tmp_path: Path) -> None:
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    receipt = tmp_path / "unsupported.json"
    receipt.write_text(
        json.dumps(
            {
                "policy": {"id": "unknown.qc", "version": "9.9.9"},
                "subjectSha256": _sha("output"),
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="policy_mismatch"):
        store.ingest_qc_reference(
            check_id="unknown.qc",
            receipt_path=receipt,
            expected_subject_sha256=_sha("output"),
        )


def _matched_evidence(
    tmp_path: Path, *, candidate_qc: bool = True
) -> tuple[
    LocalModelBenchmarkStore,
    tuple[BenchmarkReceipt, ...],
    tuple[BenchmarkReceipt, ...],
]:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    candidate: list[BenchmarkReceipt] = []
    baseline: list[BenchmarkReceipt] = []
    for index in range(2):
        task_input = f"shot-{index}"
        baseline.append(
            _complete_and_benchmark(
                queue,
                store,
                _job(f"baseline-{index}", "baseline", task_input),
                benchmark_id=f"baseline-benchmark-{index}",
            )
        )
        candidate.append(
            _complete_and_benchmark(
                queue,
                store,
                _job(f"candidate-{index}", "candidate", task_input),
                benchmark_id=f"candidate-benchmark-{index}",
                qc_passed=candidate_qc,
            )
        )
    return store, tuple(candidate), tuple(baseline)


def _evaluate(
    store: LocalModelBenchmarkStore,
    candidate: tuple[BenchmarkReceipt, ...],
    baseline: tuple[BenchmarkReceipt, ...],
):
    return store.evaluate_promotion(
        candidate_model_fingerprint=candidate[0].model_fingerprint,
        baseline_model_fingerprint=baseline[0].model_fingerprint,
        task_kind="image_to_video",
        hardware_fingerprint=candidate[0].hardware_fingerprint,
        candidate_benchmark_ids=tuple(item.benchmark_id for item in candidate),
        baseline_benchmark_ids=tuple(item.benchmark_id for item in baseline),
        policy=PromotionPolicy(
            maximum_wall_time_ratio=100,
            maximum_peak_memory_ratio=100,
        ),
    )


def test_eligible_evaluation_never_auto_promotes(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = _evaluate(store, candidate, baseline)
    assert evaluation.eligible
    event_types = [event["eventType"] for event in store.promotions.read().events]
    assert event_types == ["promotion_evaluated"]


def test_promotion_requires_explicit_operator_approval(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = _evaluate(store, candidate, baseline)
    event = store.approve_promotion(
        evaluation,
        approved_by="operator@example.test",
        reason="reviewed local evidence",
    )
    assert event["payload"]["automatic"] is False
    assert event["payload"]["evidenceFingerprint"] == evaluation.evidence_fingerprint
    with pytest.raises(RuntimeError, match="already_approved"):
        store.approve_promotion(
            evaluation, approved_by="operator@example.test", reason="duplicate"
        )


def test_promotion_rejects_forged_caller_evaluation(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = _evaluate(store, candidate, baseline)
    forged = replace(
        evaluation,
        candidate_model_fingerprint="forged-model",
        eligible=True,
        blocking_reasons=(),
    )
    with pytest.raises(RuntimeError, match="caller_payload_mismatch"):
        store.approve_promotion(
            forged, approved_by="operator@example.test", reason="forged"
        )


def test_missing_benchmark_blocks_promotion(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = store.evaluate_promotion(
        candidate_model_fingerprint=candidate[0].model_fingerprint,
        baseline_model_fingerprint=baseline[0].model_fingerprint,
        task_kind="image_to_video",
        hardware_fingerprint=candidate[0].hardware_fingerprint,
        candidate_benchmark_ids=(candidate[0].benchmark_id, "missing"),
        baseline_benchmark_ids=tuple(item.benchmark_id for item in baseline),
    )
    assert not evaluation.eligible
    assert "missing_candidate_benchmark:missing" in evaluation.blocking_reasons
    with pytest.raises(RuntimeError, match="not_evidence_eligible"):
        store.approve_promotion(evaluation, approved_by="operator", reason="unsafe")


def test_failed_qc_blocks_promotion(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path, candidate_qc=False)
    evaluation = _evaluate(store, candidate, baseline)
    assert not evaluation.eligible
    assert "candidate_qc_failed" in evaluation.blocking_reasons


def test_missing_qc_file_at_evaluation_time_blocks_promotion(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    for receipt in (store.root / "evidence").glob("*.json"):
        receipt.unlink()
    evaluation = _evaluate(store, candidate, baseline)
    assert not evaluation.eligible
    assert (
        "candidate_qc_evidence_unavailable:contentforge.motion_specific_qc"
        in evaluation.blocking_reasons
    )
    assert (
        "baseline_qc_evidence_unavailable:contentforge.motion_specific_qc"
        in evaluation.blocking_reasons
    )


def test_unmatched_task_cohort_blocks_promotion(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = store.evaluate_promotion(
        candidate_model_fingerprint=candidate[0].model_fingerprint,
        baseline_model_fingerprint=baseline[0].model_fingerprint,
        task_kind="image_to_video",
        hardware_fingerprint=candidate[0].hardware_fingerprint,
        candidate_benchmark_ids=(candidate[0].benchmark_id, candidate[0].benchmark_id),
        baseline_benchmark_ids=tuple(item.benchmark_id for item in baseline),
        policy=PromotionPolicy(
            maximum_wall_time_ratio=100,
            maximum_peak_memory_ratio=100,
        ),
    )
    assert not evaluation.eligible
    assert "duplicate_candidate_benchmark_id" in evaluation.blocking_reasons
    assert "task_fingerprint_cohort_mismatch" in evaluation.blocking_reasons


def test_operator_cli_records_output_bound_qc_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    queue_root = tmp_path / "queue"
    evidence_root = tmp_path / "benchmarks"
    queue = LocalGenerationQueue(queue_root, resource_limit_bytes=2 * GIB)
    job = _job("operator-job", "wan", "shot-a")
    output = queue_root / "operator.mp4"
    partial = output.with_suffix(".partial.mp4")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"operator-output")
    job = replace(
        job,
        owned_artifact_paths=(str(output.resolve()), str(partial.resolve())),
    )
    queue.submit(job)
    measurement = {
        "wallTimeSeconds": 2.5,
        "peakMemoryBytes": 1234,
        "memoryMeasurementMethod": PROMOTION_MEMORY_MEASUREMENT_METHOD,
    }
    with queue.worker_session() as lease:
        queue.start_next(lease)
        queue.verify_generated_artifacts(
            lease,
            job.job_id,
            partial_output_path=partial,
            final_output_path=output,
            output_probe={"streams": [{"codec_type": "video"}]},
            execution_measurement=measurement,
        )
        partial.replace(output)
        queue.succeed(
            lease,
            job.job_id,
            output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            output_path=output,
            execution_measurement=measurement,
        )
    output_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    lineage = output.with_suffix(output.suffix + ".local_video.json")
    lineage.write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_video_generation.v1",
                "queue": {"jobId": job.job_id},
                "status": "completed",
                "outputPath": str(output.resolve()),
                "outputSha256": output_sha,
                "executionMeasurement": measurement,
            }
        ),
        encoding="utf-8",
    )
    qc = tmp_path / "motion-qc.json"
    qc.write_text(
        json.dumps(
            {
                "policy": {
                    "id": "contentforge.motion_specific_qc",
                    "version": "1.0.0",
                },
                "subjectSha256": output_sha,
                "verdict": "pass",
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    assert (
        benchmark_main(
            [
                "--root",
                str(evidence_root),
                "--queue-root",
                str(queue_root),
                "record",
                "--job-id",
                job.job_id,
                "--lineage",
                str(lineage),
                "--qc",
                f"contentforge.motion_specific_qc={qc}",
                "--benchmark-id",
                "operator-benchmark",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmarkId"] == "operator-benchmark"
    copied = evidence_root / payload["qcReferences"][0]["receiptUri"]
    assert copied.is_file()
    assert copied.read_bytes() == qc.read_bytes()


def test_operator_cli_evaluates_then_explicitly_approves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    arguments = ["--root", str(store.root), "evaluate"]
    for receipt in candidate:
        arguments.extend(["--candidate-benchmark-id", receipt.benchmark_id])
    for receipt in baseline:
        arguments.extend(["--baseline-benchmark-id", receipt.benchmark_id])
    arguments.extend(
        [
            "--maximum-wall-time-ratio",
            "100",
            "--maximum-peak-memory-ratio",
            "100",
        ]
    )
    assert benchmark_main(arguments) == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["eligible"] is True
    assert evaluation["automatic"] is False

    assert (
        benchmark_main(
            [
                "--root",
                str(store.root),
                "approve",
                "--evaluation-id",
                evaluation["evaluationId"],
                "--approved-by",
                "operator@example.test",
                "--reason",
                "reviewed exact local evidence",
            ]
        )
        == 0
    )
    approval = json.loads(capsys.readouterr().out)
    assert approval["automatic"] is False
    assert approval["evaluationId"] == evaluation["evaluationId"]


def test_benchmark_module_contains_no_provider_or_publish_integration() -> None:
    import reel_factory.local_model_benchmark as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "requests" not in source
    assert "qstash" not in source.lower()
    assert "threadsdashboard" not in source.lower()
    assert "supabase" not in source.lower()
