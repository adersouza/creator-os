"""Provider-free local canary for benchmark recipe, QC, and promotion evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .local_generation_queue import (
    LocalGenerationJob,
    LocalGenerationQueue,
    fingerprint,
    sha256_file,
)
from .local_model_benchmark import (
    PROMOTION_MEMORY_MEASUREMENT_METHOD,
    LocalBenchmarkTimer,
    LocalModelBenchmarkStore,
    PromotionPolicy,
)


def _read_registry(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise RuntimeError("canary_analyzer_registry_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("canary_analyzer_registry_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("canary_analyzer_registry_invalid")
    if payload.get("schema") != "creator_os.analyzer_registry.v1":
        raise RuntimeError("canary_analyzer_registry_schema_mismatch")
    return payload


def _passing_motion_evidence(subject_sha256: str) -> dict[str, Any]:
    common = {
        "available": True,
        "analyzer": "creator_os.canary.measured_fixture",
        "analyzerVersion": "1.0.0",
        "subjectSha256": subject_sha256,
    }
    return {
        "motion": {**common, "score": 0.27, "evidenceId": "motion-canary"},
        "temporal": {**common, "discontinuityScore": 0.08},
        "freeze": {**common, "frozenFrameRatio": 0.04},
        "anatomy": {
            **common,
            "face": {"anomalyScore": 0.05},
            "hands": {"anomalyScore": 0.08},
            "body": {"anomalyScore": 0.04},
        },
        "identity": {**common, "similarityScore": 0.93, "matched": True},
    }


def _run_measured_copy(
    *, source: Path, destination: Path, minimum_allocation_bytes: int
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    timer = LocalBenchmarkTimer.start()
    allocation_bytes = max(
        minimum_allocation_bytes,
        timer.child_peak_before_bytes + 16 * 1024**2,
    )
    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import sys; "
            "data=bytearray(int(sys.argv[3])); "
            "data[::4096]=b'x'*len(data[::4096]); "
            "target=Path(sys.argv[2]); "
            "target.write_bytes(Path(sys.argv[1]).read_bytes()+target.name.encode())"
        ),
        str(source),
        str(destination),
        str(allocation_bytes),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    measurement = timer.finish()
    return (
        {
            "wallTimeSeconds": measurement.wall_time_seconds,
            "peakMemoryBytes": measurement.peak_memory_bytes,
            "memoryMeasurementMethod": measurement.memory_measurement_method,
        },
        completed,
    )


def run_canary(
    *, root: Path, analyzer_registry_path: Path, repository_root: Path
) -> dict[str, Any]:
    canary_root = root.expanduser().resolve()
    if canary_root.exists() and any(canary_root.iterdir()):
        raise RuntimeError("canary_root_must_be_empty")
    canary_root.mkdir(parents=True, exist_ok=True)
    registry = _read_registry(analyzer_registry_path)
    raw_registrations = registry.get("analyzers")
    if not isinstance(raw_registrations, list):
        raise RuntimeError("canary_analyzer_registry_invalid")
    registrations = {
        str(registration.get("analyzerId")): registration
        for registration in raw_registrations
        if isinstance(registration, dict)
    }
    motion_registration = registrations.get("contentforge.motion_specific_qc")
    if motion_registration is None:
        raise RuntimeError("canary_motion_qc_registration_missing")

    source = canary_root / "input.bin"
    source.write_bytes(b"creator-os-provider-free-benchmark-canary")
    input_fingerprint = sha256_file(source)
    params = {"operation": "provider_free_measured_copy", "version": 1}
    recipe = {
        "schema": "creator_os.benchmark_recipe.v1",
        "recipeId": f"benchmark-canary-{input_fingerprint[:16]}",
        "contentIntentId": f"benchmark-canary-intent-{input_fingerprint[:16]}",
        "executionPolicySchema": "creator_os.local_benchmark_canary.v1",
        "executionPolicyFingerprint": fingerprint(
            {"providerCalls": 0, "productionWritesAllowed": False}
        ),
        "taskKind": "provider_free_copy",
        "inputFingerprints": [input_fingerprint],
        "parameterFingerprint": fingerprint(params),
        "requiredAnalyzers": [
            {
                "analyzerId": motion_registration.get("analyzerId"),
                "analyzerVersion": motion_registration.get("analyzerVersion"),
            }
        ],
        "expectedProviderCalls": 0,
        "productionWritesAllowed": False,
        "provenance": {
            "producer": "reel_factory.benchmark_evidence_canary",
            "producedAt": "2026-07-22T12:00:00Z",
            "sourceReferences": [
                {
                    "recordId": "benchmark-canary-input",
                    "fingerprint": input_fingerprint,
                }
            ],
        },
    }
    queue = LocalGenerationQueue(
        canary_root / "queue", resource_limit_bytes=2 * 1024**3
    )
    store = LocalModelBenchmarkStore(
        canary_root / "benchmarks", implementation_root=repository_root
    )
    completed_jobs: list[tuple[LocalGenerationJob, Path]] = []
    for label in ("baseline", "candidate"):
        output = canary_root / f"{label}.mp4"
        partial = output.with_suffix(".partial.mp4")
        job = LocalGenerationJob.create(
            job_id=f"canary-{label}",
            model_id=f"canary-{label}-model",
            model_revision="local-canary-v1",
            model_manifest_sha256=hashlib.sha256(label.encode()).hexdigest(),
            task_kind=str(recipe["taskKind"]),
            input_sha256=input_fingerprint,
            requested_memory_bytes=64 * 1024**2,
            params=params,
            cohort={"recipeFingerprint": fingerprint(recipe)},
            owned_artifact_paths=(output, partial),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
        queue.submit(job)
        with queue.worker_session() as lease:
            decision = queue.start_next(lease)
            if decision.job_id != job.job_id:
                raise RuntimeError("canary_queue_admission_mismatch")
            measurement, completed = _run_measured_copy(
                source=source,
                destination=partial,
                minimum_allocation_bytes=32 * 1024**2,
            )
            if completed.returncode != 0 or not partial.is_file():
                raise RuntimeError("canary_measured_copy_failed")
            if (
                measurement["memoryMeasurementMethod"]
                != PROMOTION_MEMORY_MEASUREMENT_METHOD
            ):
                raise RuntimeError("canary_measurement_not_promotion_eligible")
            output_sha256 = sha256_file(partial)
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
                output_sha256=output_sha256,
                output_path=output,
                execution_measurement=measurement,
            )
        completed_jobs.append((job, output))

    receipts = []
    contentforge_cli = repository_root / "packages/contentforge/cli.mjs"
    for job, output in completed_jobs:
        output_sha256 = sha256_file(output)
        request_path = canary_root / f"{job.job_id}.motion-qc-request.json"
        receipt_path = canary_root / f"{job.job_id}.motion-qc.json"
        request_path.write_text(
            json.dumps(
                {
                    "mediaPath": str(output),
                    "mediaSha256": output_sha256,
                    "evidence": _passing_motion_evidence(output_sha256),
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["node", str(contentforge_cli), "motion-qc", str(request_path)],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError("canary_contentforge_motion_qc_failed")
        receipt_path.write_text(completed.stdout.strip(), encoding="utf-8")
        qc_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            qc_payload.get("passed") is not True
            or qc_payload.get("providerCalls") != 0
            or qc_payload.get("modelCalls") != 0
        ):
            raise RuntimeError("canary_contentforge_motion_qc_not_provider_free")
        reference = store.ingest_qc_reference(
            check_id="contentforge.motion_specific_qc",
            receipt_path=receipt_path,
            expected_subject_sha256=output_sha256,
        )
        receipts.append(
            store.record_completed_job(
                queue,
                job_id=job.job_id,
                qc_references=(reference,),
                benchmark_id=f"benchmark-{job.job_id}",
                benchmark_recipe=recipe,
                analyzer_registry=registry,
            )
        )

    baseline, candidate = receipts
    evaluation = store.evaluate_promotion(
        candidate_model_fingerprint=candidate.model_fingerprint,
        baseline_model_fingerprint=baseline.model_fingerprint,
        task_kind=str(recipe["taskKind"]),
        hardware_fingerprint=candidate.hardware_fingerprint,
        candidate_benchmark_ids=(candidate.benchmark_id,),
        baseline_benchmark_ids=(baseline.benchmark_id,),
        policy=PromotionPolicy(
            minimum_candidate_samples=1,
            minimum_baseline_samples=1,
            maximum_wall_time_ratio=100,
            maximum_peak_memory_ratio=100,
        ),
    )
    if not evaluation.eligible:
        raise RuntimeError(
            "canary_promotion_evaluation_ineligible:"
            + ",".join(evaluation.blocking_reasons)
        )
    return {
        "schema": "reel_factory.benchmark_evidence_canary.v1",
        "providerCalls": 0,
        "productionWrites": 0,
        "benchmarkRecipeId": recipe["recipeId"],
        "benchmarkRecipeFingerprint": fingerprint(recipe),
        "analyzerRegistryId": registry["registryId"],
        "analyzerRegistryFingerprint": fingerprint(registry),
        "queueJobIds": [job.job_id for job, _ in completed_jobs],
        "benchmarkReceipts": [receipt.as_dict() for receipt in receipts],
        "promotionEvaluation": {
            "evaluationId": evaluation.evaluation_id,
            "eligible": evaluation.eligible,
            "blockingReasons": list(evaluation.blocking_reasons),
            "evidenceFingerprint": evaluation.evidence_fingerprint,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--analyzer-registry", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = run_canary(
            root=args.root,
            analyzer_registry_path=args.analyzer_registry,
            repository_root=args.repository_root.expanduser().resolve(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
