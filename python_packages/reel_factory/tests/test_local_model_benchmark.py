from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from creator_os_core.evidence_attestation import (
    load_evidence_secret,
    sign_evidence_attestation,
)
from reel_factory.local_generation_queue import LocalGenerationJob, LocalGenerationQueue
from reel_factory.local_generation_queue import fingerprint as queue_fingerprint
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

from pipeline_contracts import (
    AnalyzerRegistrationV1,
    AnalyzerRegistryV1,
    AnalyzerRequirementV1,
    BenchmarkRecipeV1,
    ProvenanceV1,
    SourceReferenceV1,
)

GIB = 1024**3
ROOT = Path(__file__).resolve().parents[3]
TRUSTED_ANALYSIS_IMPLEMENTATION = (
    ROOT / "packages/contentforge/lib/trusted-media-analysis.js"
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _deep_verified_test_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CREATOR_OS_EVIDENCE_AUTH_SECRET",
        "benchmark-test-secret-0123456789-abcdef",
    )

    def status(model_id: str, *, deep: bool = True) -> dict:
        core = {
            "schema": "reel_factory.local_model_deep_verification.v1",
            "modelId": model_id,
            "repository": f"fixture/{model_id}",
            "revision": "revision-1",
            "manifestSha256": _sha(model_id),
            "fileBindings": [],
            "dependencyBindings": [],
            "providerCalls": 0,
            "paidGeneration": False,
        }
        return {
            "ready": True,
            "deepVerified": deep,
            "manifestSha256": _sha(model_id),
            "deepVerificationReceipt": {
                **core,
                "verificationFingerprint": queue_fingerprint(core),
            }
            if deep
            else None,
        }

    monkeypatch.setattr("reel_factory.local_model_benchmark.model_status", status)


def _records(
    *, input_fingerprint: str, parameter_fingerprint: str, task_kind: str
) -> tuple[BenchmarkRecipeV1, AnalyzerRegistryV1]:
    implementation_fingerprint = hashlib.sha256(
        TRUSTED_ANALYSIS_IMPLEMENTATION.read_bytes()
    ).hexdigest()
    provenance = ProvenanceV1(
        producer="reel_factory.test",
        produced_at="2026-07-22T12:00:00Z",
        source_references=(
            SourceReferenceV1(
                record_id=f"benchmark-input:{input_fingerprint[:16]}",
                fingerprint=input_fingerprint,
            ),
        ),
    )
    recipe = BenchmarkRecipeV1(
        recipe_id=f"benchmark-recipe-{input_fingerprint[:16]}",
        content_intent_id=f"intent-{input_fingerprint[:16]}",
        execution_policy_schema="campaign_factory.generation_execution_plan.v1",
        execution_policy_fingerprint=_sha("local-provider-free-policy"),
        task_kind=task_kind,
        input_fingerprints=(input_fingerprint,),
        parameter_fingerprint=parameter_fingerprint,
        required_analyzers=(
            AnalyzerRequirementV1(
                analyzer_id="contentforge.media_integrity",
                analyzer_version="1.0.0",
            ),
        ),
        expected_provider_calls=0,
        production_writes_allowed=False,
        provenance=provenance,
    )
    registry = AnalyzerRegistryV1(
        registry_id=f"contentforge-media-integrity-{implementation_fingerprint[:16]}",
        analyzers=(
            AnalyzerRegistrationV1(
                analyzer_id="contentforge.media_integrity",
                analyzer_version="1.0.0",
                evidence_kinds=("trusted_media_analysis",),
                implementation_ref="packages/contentforge/lib/trusted-media-analysis.js",
                implementation_fingerprint=implementation_fingerprint,
            ),
        ),
        provenance=ProvenanceV1(
            producer="contentforge.analyzer_registry_adapter",
            produced_at="2026-07-22T12:00:00Z",
            source_references=(
                SourceReferenceV1(
                    record_id="contentforge.media_integrity@1.0.0",
                    fingerprint=implementation_fingerprint,
                ),
            ),
        ),
    )
    return recipe, registry


def _records_for_job(
    job: LocalGenerationJob,
) -> tuple[BenchmarkRecipeV1, AnalyzerRegistryV1]:
    return _records(
        input_fingerprint=job.input_fingerprint,
        parameter_fingerprint=job.params_fingerprint,
        task_kind=job.task_kind,
    )


def _job(job_id: str, model: str, task_input: str) -> LocalGenerationJob:
    input_fingerprint = _sha(task_input)
    params = {"frames": 81, "seed": 9}
    recipe, registry = _records(
        input_fingerprint=input_fingerprint,
        parameter_fingerprint=queue_fingerprint(params),
        task_kind="image_to_video",
    )
    return LocalGenerationJob.create(
        job_id=job_id,
        model_id=model,
        model_revision="revision-1",
        model_manifest_sha256=_sha(model),
        task_kind="image_to_video",
        input_sha256=input_fingerprint,
        requested_memory_bytes=GIB,
        params=params,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )


def _qc(
    name: str = "contentforge.media_integrity",
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
    job: LocalGenerationJob,
    analyzer_registry: dict,
    subject_sha256: str,
    passed: bool,
) -> tuple[QCReference, ...]:
    relative = Path("evidence") / f"{job.job_id}.json"
    receipt = store.root / relative
    receipt.parent.mkdir(parents=True, exist_ok=True)
    registry = analyzer_registry
    registry_fingerprint = queue_fingerprint(registry)
    registration = registry["analyzers"][0]
    observation = {
        **registration,
        "analyzerRegistryId": registry["registryId"],
        "analyzerRegistryFingerprint": registry_fingerprint,
        "toolRevisions": {
            "node": "fixture",
            "platform": "fixture",
            "ffmpeg": {"available": True, "version": "fixture"},
            "ffprobe": {"available": True, "version": "fixture"},
        },
        "status": "measured",
        "observations": {"available": True},
    }
    analysis_id = f"analysis-{job.job_id}"
    verdict = {
        "schema": "contentforge.trusted_analyzer_receipt.v1",
        "policy": {
            "id": registration["analyzerId"],
            "version": registration["analyzerVersion"],
        },
        "subjectSha256": subject_sha256,
        "analysisId": analysis_id,
        "observationFingerprint": queue_fingerprint(observation),
        "implementationRef": registration["implementationRef"],
        "implementationFingerprint": registration["implementationFingerprint"],
        "analyzerRegistryId": registry["registryId"],
        "analyzerRegistryFingerprint": registry_fingerprint,
        "verdict": "pass" if passed else "blocked",
        "passed": passed,
        "evidenceOnly": True,
        "providerCalls": 0,
        "reasons": [] if passed else [{"code": "fixture_block", "severity": "block"}],
    }
    analysis = {
        "schema": "contentforge.trusted_media_analysis.v1",
        "analysisId": analysis_id,
        "subject": {
            "mediaPath": f"/fixture/{job.job_id}.mp4",
            "mediaSha256": subject_sha256,
            "sourcePath": None,
            "sourceSha256": None,
        },
        "producedAt": "2026-07-22T00:00:00Z",
        "producer": "contentforge.trusted_media_analysis",
        "humanReviewSampling": {
            "sampleFps": 8.0,
            "width": 180,
            "height": 320,
            "sampledFrames": 48,
            "totalFrames": 180,
            "durationSeconds": 6.0,
            "durationCoverageRatio": 1,
            "frameSetFingerprint": _sha(f"frames-{job.job_id}"),
            "briefFrameOutlierCount": 0,
        },
        "analyzerRegistry": {
            "registryId": registry["registryId"],
            "registryFingerprint": registry_fingerprint,
        },
        "rawObservations": [observation],
        "analyzerVerdicts": [verdict],
        "unavailableMeasurements": {},
    }
    analysis["analysisFingerprint"] = queue_fingerprint(analysis)
    signed_payload = dict(analysis)
    analysis["producerAttestation"] = sign_evidence_attestation(
        signed_payload,
        issuer="contentforge.trusted_media_analysis",
        issued_at=analysis["producedAt"],
        secret=load_evidence_secret(),
    )
    receipt.write_text(
        json.dumps(analysis),
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
    benchmark_recipe, analyzer_registry = _records_for_job(job)
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
            job=job,
            analyzer_registry=analyzer_registry.to_dict(),
            subject_sha256=output_sha256,
            passed=qc_passed,
        ),
        benchmark_id=benchmark_id,
        benchmark_recipe=benchmark_recipe,
        analyzer_registry=analyzer_registry,
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
    assert receipt.benchmark_recipe_id == job.benchmark_recipe_id
    assert receipt.benchmark_recipe_fingerprint == job.benchmark_recipe_fingerprint
    assert receipt.analyzer_registry_id == job.analyzer_registry_id
    assert receipt.analyzer_registry_fingerprint == job.analyzer_registry_fingerprint
    assert receipt.execution_attempt_count == 1
    assert receipt.execution_retry_count == 0
    assert receipt.local_cost_usd is None
    assert receipt.local_cost_measurement_method == "unavailable:not_metered"


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
        recipe, registry = _records_for_job(job)
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_qc(subject_sha256=_sha("output-job")),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_synthetic_benchmark_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="must_be_measured"):
        BenchmarkReceipt(
            benchmark_id="fake",
            job_id="fake",
            model_id="wan",
            model_fingerprint="model",
            model_deep_verification_fingerprint=_sha("deep-model"),
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
            model_id="wan",
            model_fingerprint="model",
            model_deep_verification_fingerprint=_sha("deep-model"),
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
    recipe, registry = _records_for_job(job)
    with pytest.raises(RuntimeError, match="qc_receipt_missing"):
        store.record_completed_job(
            queue,
            job_id="job",
            qc_references=_qc(subject_sha256=_sha("output-job")),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
    receipt = store.root / "evidence" / "contentforge.media_integrity.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(b"substituted")
    with pytest.raises(RuntimeError, match="qc_receipt_sha256_mismatch"):
        store.record_completed_job(
            queue,
            job_id="job",
            qc_references=_qc(subject_sha256=_sha("output-job")),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_qc_caller_verdict_must_match_bound_receipt(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    _complete_queue_job(queue, job)
    recipe, registry = _records_for_job(job)
    (actual,) = _write_qc(
        store,
        job=job,
        analyzer_registry=registry.to_dict(),
        subject_sha256=_sha("output-job"),
        passed=False,
    )
    forged = QCReference(
        check_id=actual.check_id,
        receipt_uri=actual.receipt_uri,
        receipt_sha256=actual.receipt_sha256,
        subject_sha256=_sha("output-job"),
        passed=True,
    )
    with pytest.raises(RuntimeError, match="passed_mismatch"):
        store.record_completed_job(
            queue,
            job_id="job",
            qc_references=(forged,),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


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


def test_component_qc_ingest_rejects_standalone_self_authored_verdict(
    tmp_path: Path,
) -> None:
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    receipt = tmp_path / "plausible-forgery.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "contentforge.trusted_analyzer_receipt.v1",
                "policy": {
                    "id": "contentforge.media_integrity",
                    "version": "1.0.0",
                },
                "subjectSha256": _sha("output"),
                "analysisId": "invented-analysis",
                "observationFingerprint": _sha("invented-observation"),
                "implementationRef": "packages/contentforge/lib/trusted-media-analysis.js",
                "implementationFingerprint": _sha("invented-implementation"),
                "analyzerRegistryId": "invented-registry",
                "analyzerRegistryFingerprint": _sha("invented-registry"),
                "verdict": "pass",
                "passed": True,
                "evidenceOnly": True,
                "providerCalls": 0,
                "reasons": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="trusted_analysis_required"):
        store.ingest_qc_reference(
            check_id="contentforge.media_integrity",
            receipt_path=receipt,
            expected_subject_sha256=_sha("output"),
        )


def test_legacy_motion_qc_v1_is_never_promotion_evidence(tmp_path: Path) -> None:
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    receipt = tmp_path / "legacy-motion.json"
    receipt.write_text(
        json.dumps(
            {
                "policy": {
                    "id": "contentforge.motion_specific_qc",
                    "version": "1.0.0",
                },
                "subjectSha256": _sha("output"),
                "passed": True,
                "evidenceOnly": True,
                "providerCalls": 0,
                "modelCalls": 0,
                "requirements": {},
                "thresholds": {},
                "measurements": {},
                "evidenceSources": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="policy_mismatch"):
        store.ingest_qc_reference(
            check_id="contentforge.motion_specific_qc",
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
            maximum_wall_time_ratio=1.25,
            maximum_peak_memory_ratio=1.25,
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


def test_active_promotion_honors_scope_expiry_and_revocation(tmp_path: Path) -> None:
    store, candidate, baseline = _matched_evidence(tmp_path)
    evaluation = _evaluate(store, candidate, baseline)
    store.approve_promotion(
        evaluation,
        approved_by="operator@example.test",
        reason="reviewed local evidence",
        scope=("image_to_video",),
        expires_at="2026-08-22T12:00:00Z",
    )
    active = store.active_promotion(
        candidate_model_fingerprint=evaluation.candidate_model_fingerprint,
        task_kind="image_to_video",
        candidate_benchmark_ids=evaluation.candidate_benchmark_ids,
        hardware_fingerprint=evaluation.hardware_fingerprint,
        observed_at="2026-07-22T12:00:00Z",
    )
    assert active["scope"] == ["image_to_video"]
    assert active["candidateBenchmarkIds"] == list(evaluation.candidate_benchmark_ids)
    assert active["hardwareFingerprint"] == evaluation.hardware_fingerprint
    with pytest.raises(RuntimeError, match="not_found_exactly_once"):
        store.active_promotion(
            candidate_model_fingerprint=evaluation.candidate_model_fingerprint,
            task_kind="image_to_video",
            candidate_benchmark_ids=(evaluation.candidate_benchmark_ids[0],),
            hardware_fingerprint=evaluation.hardware_fingerprint,
            observed_at="2026-07-22T12:00:00Z",
        )
    with pytest.raises(RuntimeError, match="not_found_exactly_once"):
        store.active_promotion(
            candidate_model_fingerprint=evaluation.candidate_model_fingerprint,
            task_kind="image_to_video",
            candidate_benchmark_ids=evaluation.candidate_benchmark_ids,
            hardware_fingerprint="different-hardware",
            observed_at="2026-07-22T12:00:00Z",
        )
    with pytest.raises(RuntimeError, match="not_found_exactly_once"):
        store.active_promotion(
            candidate_model_fingerprint=evaluation.candidate_model_fingerprint,
            task_kind="image_to_video",
            candidate_benchmark_ids=evaluation.candidate_benchmark_ids,
            hardware_fingerprint=evaluation.hardware_fingerprint,
            observed_at="2026-09-22T12:00:00Z",
        )
    store.revoke_promotion(
        evaluation.evaluation_id,
        revoked_by="operator@example.test",
        reason="model drift",
    )
    with pytest.raises(RuntimeError, match="not_found_exactly_once"):
        store.active_promotion(
            candidate_model_fingerprint=evaluation.candidate_model_fingerprint,
            task_kind="image_to_video",
            candidate_benchmark_ids=evaluation.candidate_benchmark_ids,
            hardware_fingerprint=evaluation.hardware_fingerprint,
            observed_at="2026-07-22T12:00:00Z",
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
        "candidate_qc_evidence_unavailable:contentforge.media_integrity"
        in evaluation.blocking_reasons
    )
    assert (
        "baseline_qc_evidence_unavailable:contentforge.media_integrity"
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
            maximum_wall_time_ratio=1.25,
            maximum_peak_memory_ratio=1.25,
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
    recipe, registry = _records_for_job(job)
    store = LocalModelBenchmarkStore(evidence_root)
    (reference,) = _write_qc(
        store,
        job=job,
        analyzer_registry=registry.to_dict(),
        subject_sha256=output_sha,
        passed=True,
    )
    qc = evidence_root / reference.receipt_uri
    recipe_path = tmp_path / "benchmark-recipe.json"
    registry_path = tmp_path / "analyzer-registry.json"
    recipe_path.write_text(json.dumps(recipe.to_dict()), encoding="utf-8")
    registry_path.write_text(json.dumps(registry.to_dict()), encoding="utf-8")
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
                f"contentforge.media_integrity={qc}",
                "--benchmark-id",
                "operator-benchmark",
                "--benchmark-recipe",
                str(recipe_path),
                "--analyzer-registry",
                str(registry_path),
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
            "1.25",
            "--maximum-peak-memory-ratio",
            "1.25",
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


def test_historical_receipt_reads_without_invented_evidence_linkage() -> None:
    payload = {
        "schema": "reel_factory.local_model_benchmark.v1",
        "benchmarkId": "historical",
        "jobId": "historical-job",
        "modelFingerprint": "historical-model",
        "taskFingerprint": "historical-task",
        "taskKind": "image_to_video",
        "hardwareFingerprint": "historical-hardware",
        "outputSha256": _sha("historical-output"),
        "wallTimeSeconds": 1.0,
        "peakMemoryBytes": 1,
        "memoryMeasurementMethod": PROMOTION_MEMORY_MEASUREMENT_METHOD,
        "qcReferences": [
            {
                "checkId": "contentforge.motion_specific_qc",
                "receiptUri": "qc/historical.json",
                "receiptSha256": _sha("historical-qc"),
                "subjectSha256": _sha("historical-output"),
                "passed": True,
            }
        ],
        "source": "measured_local_execution",
    }

    with pytest.raises(
        ValueError, match="historical_benchmark_missing_deep_model_evidence"
    ):
        BenchmarkReceipt.from_dict(payload)


def test_record_rejects_recipe_that_did_not_create_queue_job(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _complete_queue_job(queue, _job("job", "wan", "shot-a"))
    recipe, registry = _records_for_job(job)
    wrong_recipe = replace(recipe, recipe_id="wrong-recipe")

    with pytest.raises(RuntimeError, match="job_recipe_linkage_mismatch"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_write_qc(
                store,
                job=job,
                analyzer_registry=registry.to_dict(),
                subject_sha256=_sha("output-job"),
                passed=True,
            ),
            benchmark_recipe=wrong_recipe,
            analyzer_registry=registry,
        )


def test_new_measurement_requires_evidence_linked_queue_job(tmp_path: Path) -> None:
    input_fingerprint = _sha("shot-a")
    params = {"frames": 81, "seed": 9}
    recipe, registry = _records(
        input_fingerprint=input_fingerprint,
        parameter_fingerprint=queue_fingerprint(params),
        task_kind="image_to_video",
    )
    job = LocalGenerationJob.create(
        job_id="unlinked",
        model_id="wan",
        model_revision="revision-1",
        model_manifest_sha256=_sha("wan"),
        task_kind="image_to_video",
        input_sha256=input_fingerprint,
        requested_memory_bytes=GIB,
        params=params,
    )
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job = _complete_queue_job(queue, job)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")

    with pytest.raises(RuntimeError, match="job_recipe_linkage_missing"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_write_qc(
                store,
                job=job,
                analyzer_registry=registry.to_dict(),
                subject_sha256=_sha("output-unlinked"),
                passed=True,
            ),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_queue_preserves_multi_input_recipe_identity_without_collapsing_it() -> None:
    params = {"frames": 81, "seed": 9}
    recipe, registry = _records(
        input_fingerprint=_sha("source-a"),
        parameter_fingerprint=_sha("semantic-parameters"),
        task_kind="image_to_video",
    )
    recipe = replace(
        recipe,
        input_fingerprints=(_sha("source-a"), _sha("source-b")),
    )

    job = LocalGenerationJob.create(
        job_id="multi-input",
        model_id="wan",
        model_revision="revision-1",
        model_manifest_sha256=_sha("wan"),
        task_kind="image_to_video",
        input_sha256=_sha("aggregate-input-manifest"),
        requested_memory_bytes=GIB,
        params=params,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )

    assert job.benchmark_recipe_id == recipe.recipe_id
    assert job.benchmark_recipe_fingerprint == queue_fingerprint(recipe.to_dict())
    assert job.input_fingerprint == _sha("aggregate-input-manifest")


def test_record_rejects_analyzer_registry_drift_from_queue_job(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _complete_queue_job(queue, _job("job", "wan", "shot-a"))
    recipe, registry = _records_for_job(job)
    drifted_registry = replace(registry, registry_id="drifted-registry")

    with pytest.raises(RuntimeError, match="job_analyzer_registry_drift"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_write_qc(
                store,
                job=job,
                analyzer_registry=registry.to_dict(),
                subject_sha256=_sha("output-job"),
                passed=True,
            ),
            benchmark_recipe=recipe,
            analyzer_registry=drifted_registry,
        )


def test_record_rejects_changed_analyzer_implementation(tmp_path: Path) -> None:
    implementation_root = tmp_path / "implementation-root"
    implementation = (
        implementation_root / "packages/contentforge/lib/trusted-media-analysis.js"
    )
    implementation.parent.mkdir(parents=True)
    implementation.write_bytes(TRUSTED_ANALYSIS_IMPLEMENTATION.read_bytes())
    input_fingerprint = _sha("shot-a")
    params = {"frames": 81, "seed": 9}
    recipe, registry = _records(
        input_fingerprint=input_fingerprint,
        parameter_fingerprint=queue_fingerprint(params),
        task_kind="image_to_video",
    )
    implementation_fingerprint = hashlib.sha256(implementation.read_bytes()).hexdigest()
    registration = replace(
        registry.analyzers[0],
        implementation_fingerprint=implementation_fingerprint,
    )
    registry = replace(
        registry,
        registry_id=f"test-registry-{implementation_fingerprint[:16]}",
        analyzers=(registration,),
        provenance=replace(
            registry.provenance,
            source_references=(
                SourceReferenceV1(
                    record_id="contentforge.media_integrity@1.0.0",
                    fingerprint=implementation_fingerprint,
                ),
            ),
        ),
    )
    job = LocalGenerationJob.create(
        job_id="job",
        model_id="wan",
        model_revision="revision-1",
        model_manifest_sha256=_sha("wan"),
        task_kind="image_to_video",
        input_sha256=input_fingerprint,
        requested_memory_bytes=GIB,
        params=params,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    job = _complete_queue_job(queue, job)
    store = LocalModelBenchmarkStore(
        tmp_path / "evidence", implementation_root=implementation_root
    )
    implementation.write_text("changed implementation", encoding="utf-8")

    with pytest.raises(RuntimeError, match="analyzer_implementation_drift"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=_write_qc(
                store,
                job=job,
                analyzer_registry=registry.to_dict(),
                subject_sha256=_sha("output-job"),
                passed=True,
            ),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_record_requires_exact_qc_for_every_recipe_analyzer(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _complete_queue_job(queue, _job("job", "wan", "shot-a"))
    recipe, registry = _records_for_job(job)

    with pytest.raises(RuntimeError, match="required_qc_missing"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=(),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_exact_benchmark_replay_is_idempotent(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    receipt = _complete_and_benchmark(
        queue, store, job, benchmark_id="duplicate-benchmark"
    )
    recipe, registry = _records_for_job(job)

    replay = store.record_completed_job(
        queue,
        job_id=job.job_id,
        qc_references=receipt.qc_references,
        benchmark_id=receipt.benchmark_id,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
    assert replay == receipt
    assert len(store.benchmarks.read().events) == 1


def test_same_queue_job_cannot_be_counted_as_a_second_receipt(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("job", "wan", "shot-a")
    receipt = _complete_and_benchmark(queue, store, job, benchmark_id="first")
    recipe, registry = _records_for_job(job)

    with pytest.raises(RuntimeError, match="benchmark_job_collision"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=receipt.qc_references,
            benchmark_id="second",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_interrupted_job_cannot_create_benchmark_receipt(tmp_path: Path) -> None:
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2 * GIB)
    store = LocalModelBenchmarkStore(tmp_path / "evidence")
    job = _job("interrupted", "wan", "shot-a")
    queue.submit(job)
    with queue.worker_session() as lease:
        queue.start_next(lease)
        queue.interrupt(lease, job.job_id, reason="operator_interrupt")
    recipe, registry = _records_for_job(job)

    with pytest.raises(RuntimeError, match="requires_succeeded_job:.*interrupted"):
        store.record_completed_job(
            queue,
            job_id=job.job_id,
            qc_references=(),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
    assert store.all_receipts() == {}


def test_provider_free_end_to_end_benchmark_evidence_canary(tmp_path: Path) -> None:
    registry_request = tmp_path / "registry-request.json"
    registry_path = tmp_path / "analyzer-registry.json"
    registry_request.write_text(
        json.dumps({"producedAt": "2026-07-22T12:00:00Z"}), encoding="utf-8"
    )
    adapter = subprocess.run(
        [
            "node",
            str(ROOT / "packages/contentforge/cli.mjs"),
            "analyzer-registry",
            str(registry_request),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert adapter.returncode == 0, adapter.stderr
    adapter_registry = AnalyzerRegistryV1.from_dict(json.loads(adapter.stdout))
    registry_path.write_text(json.dumps(adapter_registry.to_dict()), encoding="utf-8")
    canary_root = tmp_path / "canary"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "reel_factory.benchmark_evidence_canary",
            "--root",
            str(canary_root),
            "--analyzer-registry",
            str(registry_path),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["providerCalls"] == 0
    assert result["productionWrites"] == 0
    assert result["promotionEvaluation"]["eligible"] is True
    assert len(result["benchmarkReceipts"]) == 4
    assert len({item["outputSha256"] for item in result["benchmarkReceipts"]}) == 4
    for receipt in result["benchmarkReceipts"]:
        assert receipt["benchmarkRecipeId"] == result["benchmarkRecipeId"]
        assert (
            receipt["benchmarkRecipeFingerprint"]
            == result["benchmarkRecipeFingerprint"]
        )
        assert receipt["analyzerRegistryId"] == result["analyzerRegistryId"]
        assert receipt["qcReferences"][0]["subjectSha256"] == receipt["outputSha256"]
        assert receipt["wallTimeSeconds"] > 0
        assert receipt["peakMemoryBytes"] > 0
        assert receipt["memoryMeasurementMethod"] == PROMOTION_MEMORY_MEASUREMENT_METHOD
