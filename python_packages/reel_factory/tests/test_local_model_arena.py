from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from reel_factory.human_media_review import (
    HumanMediaReview,
    HumanMediaReviewStore,
    HumanReviewDecisions,
    HumanReviewProvenance,
    HumanReviewRatings,
    HumanReviewSamplingEvidence,
)
from reel_factory.local_generation_queue import (
    LocalGenerationJob,
    LocalGenerationQueue,
    LocalQueueError,
    fingerprint,
    sha256_file,
)
from reel_factory.local_model_arena import (
    ArenaSampleSpec,
    LocalModelArenaStore,
    _human_review_evidence,
    _motion_qc_options,
    _promotion_design_check,
    _validate_human_review_binding,
    arena_analyzer_registry,
    build_arena_plan,
    build_arena_review_packet,
    build_arena_unblinding_receipt,
    validate_arena_plan,
    validate_arena_review_packet,
    validate_arena_unblinding_receipt,
)
from reel_factory.local_model_benchmark import LocalModelBenchmarkStore

PRODUCED_AT = "2026-07-22T12:00:00Z"
SHA_A = "a" * 64
SHA_B = "b" * 64
EVIDENCE_SECRET = "arena-test-evidence-" + "fixture-material-" + ("x" * 32)


def _base_registry(repository_root: Path) -> dict:
    trusted = repository_root / "packages/contentforge/lib/trusted-media-analysis.js"
    motion = repository_root / "packages/contentforge/lib/motion-specific-qc.js"
    analyzers = []
    for analyzer_id, kinds in (
        ("contentforge.media_integrity", ["media_integrity"]),
        ("contentforge.temporal_motion", ["temporal_motion"]),
        ("contentforge.audio_integrity", ["audio_integrity"]),
        ("contentforge.overlay_delivery", ["overlay_delivery"]),
    ):
        analyzers.append(
            {
                "analyzerId": analyzer_id,
                "analyzerVersion": "1.0.0",
                "evidenceKinds": kinds,
                "implementationRef": str(trusted.relative_to(repository_root)),
                "implementationFingerprint": sha256_file(trusted),
            }
        )
    analyzers.append(
        {
            "analyzerId": "contentforge.motion_specific_qc",
            "analyzerVersion": "2.0.0",
            "evidenceKinds": ["motion_specific_qc_receipt"],
            "implementationRef": str(motion.relative_to(repository_root)),
            "implementationFingerprint": sha256_file(motion),
        }
    )
    return {
        "schema": "creator_os.analyzer_registry.v1",
        "registryId": "contentforge-test-registry",
        "analyzers": analyzers,
        "provenance": {
            "producer": "test",
            "producedAt": PRODUCED_AT,
            "sourceReferences": [{"recordId": "contentforge", "fingerprint": SHA_A}],
        },
    }


def _spec(
    source: Path,
    *,
    creator: str = "stacey",
    seed: int = 1,
    model_id: str = "local_wan22_ti2v_5b_mlx",
) -> ArenaSampleSpec:
    return ArenaSampleSpec(
        creator_id=creator,
        identity_profile_id=f"identity-{creator}",
        identity_profile_fingerprint=SHA_A,
        content_intent_id="intent-subtle-motion",
        content_intent_fingerprint=SHA_B,
        source_path=source,
        model_id=model_id,
        capability_cohort="silent_i2v",
        task_kind="image_to_video",
        prompt="Subtle natural movement, stable face, fixed camera.",
        seed=seed,
        duration_seconds=5,
        resolution="720p",
    )


def _policy() -> dict:
    return {
        "schema": "creator_os.execution_policy.v1",
        "policyId": "local-arena-test",
        "paidProvidersAllowed": False,
        "productionWritesAllowed": False,
    }


def _fake_job(request) -> LocalGenerationJob:
    recipe = dict(request.benchmark_recipe)
    registry = dict(request.analyzer_registry)
    return LocalGenerationJob.create(
        job_id=f"job-{request.model_id}-{request.seed}",
        model_id=request.model_id,
        model_revision="model-revision",
        model_manifest_sha256="c" * 64,
        task_kind=request.task,
        input_sha256="d" * 64,
        requested_memory_bytes=1024,
        params={"seed": request.seed, "output": str(request.output_path)},
        cohort={"seed": request.seed},
        owned_artifact_paths=(request.output_path,),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )


def _job_from_sample(sample: dict) -> LocalGenerationJob:
    raw = sample["queueJob"]
    return LocalGenerationJob(
        job_id=str(raw["jobId"]),
        model_id=str(raw["modelId"]),
        model_fingerprint=str(raw["modelFingerprint"]),
        task_kind=str(raw["taskKind"]),
        task_fingerprint=str(raw["taskFingerprint"]),
        input_fingerprint=str(raw["inputFingerprint"]),
        requested_memory_bytes=int(raw["requestedMemoryBytes"]),
        params_fingerprint=str(raw["paramsFingerprint"]),
        owned_artifact_paths=tuple(raw.get("ownedArtifactPaths", [])),
        benchmark_recipe_id=str(raw["benchmarkRecipeId"]),
        benchmark_recipe_fingerprint=str(raw["benchmarkRecipeFingerprint"]),
        analyzer_registry_id=str(raw["analyzerRegistryId"]),
        analyzer_registry_fingerprint=str(raw["analyzerRegistryFingerprint"]),
    )


def _build(monkeypatch, tmp_path: Path, specs: list[ArenaSampleSpec]) -> dict:
    repository_root = Path(__file__).resolve().parents[3]
    registry = arena_analyzer_registry(
        _base_registry(repository_root),
        produced_at=PRODUCED_AT,
        repository_root=repository_root,
    )
    deep_core = {
        "schema": "reel_factory.local_model_deep_verification.v1",
        "modelId": "placeholder",
        "repository": "fixture/model",
        "revision": "model-revision",
        "manifestSha256": "c" * 64,
        "fileBindings": [],
        "dependencyBindings": [],
        "providerCalls": 0,
        "paidGeneration": False,
    }

    def status(model_id: str, **_kwargs) -> dict:
        model_core = {**deep_core, "modelId": model_id}
        return {
            "ready": True,
            "issues": [],
            "manifestSha256": "c" * 64,
            "manifest": {"revision": "model-revision"},
            "deepVerified": True,
            "deepVerificationReceipt": {
                **model_core,
                "verificationFingerprint": fingerprint(model_core),
            },
        }

    monkeypatch.setattr(
        "reel_factory.local_model_arena.model_status",
        status,
    )
    monkeypatch.setattr(
        "reel_factory.local_model_arena.plan_local_video_job", _fake_job
    )
    return build_arena_plan(
        sample_specs=specs,
        purpose="exploratory",
        produced_at=PRODUCED_AT,
        output_root=tmp_path / "arena",
        execution_policy=_policy(),
        analyzer_registry=registry,
    )


def test_registry_adds_exact_reel_factory_producers() -> None:
    root = Path(__file__).resolve().parents[3]
    registry = arena_analyzer_registry(
        _base_registry(root), produced_at=PRODUCED_AT, repository_root=root
    )
    identities = {
        (registration["analyzerId"], registration["analyzerVersion"])
        for registration in registry["analyzers"]
    }
    assert ("reel_factory.identity_preservation", "2.0.0") in identities
    assert ("reel_factory.structured_human_media_review", "1.0.0") in identities
    for registration in registry["analyzers"]:
        implementation = root / registration["implementationRef"]
        assert sha256_file(implementation) == registration["implementationFingerprint"]


def test_arena_plan_freezes_exact_queue_and_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    validated = validate_arena_plan(plan)
    sample = validated["samples"][0]
    assert validated["expectedSampleCount"] == 1
    assert sample["sourceSha256"] == sha256_file(source)
    assert (
        sample["queueJob"]["benchmarkRecipeId"] == sample["benchmarkRecipe"]["recipeId"]
    )
    assert sample["queueJobFingerprint"] == fingerprint(sample["queueJob"])
    assert validated["providerCalls"] == 0
    assert validated["productionWritesAllowed"] is False


def test_matched_models_share_recipe_and_task_but_keep_distinct_identity(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(
        monkeypatch,
        tmp_path,
        [
            _spec(source, model_id="local_wan22_ti2v_5b_mlx"),
            _spec(source, model_id="local_wan22_i2v_a14b_q4_mlx"),
        ],
    )
    first, second = plan["samples"]
    assert first["sampleId"] != second["sampleId"]
    assert first["queueJob"]["jobId"] != second["queueJob"]["jobId"]
    assert first["modelFingerprint"] != second["modelFingerprint"]
    assert first["benchmarkRecipe"]["recipeId"] == second["benchmarkRecipe"]["recipeId"]
    assert first["benchmarkRecipeFingerprint"] == second["benchmarkRecipeFingerprint"]
    assert first["queueJob"]["taskFingerprint"] == second["queueJob"]["taskFingerprint"]
    assert "modelId" not in first["benchmarkRecipe"]


def test_review_packet_is_shuffled_model_free_and_unblinding_waits_for_reviews(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(
        monkeypatch,
        tmp_path,
        [
            _spec(source, model_id="local_wan22_ti2v_5b_mlx"),
            _spec(source, model_id="local_wan22_i2v_a14b_q4_mlx"),
        ],
    )
    states = {}
    for index, sample in enumerate(plan["samples"]):
        output = Path(sample["outputPath"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"generated-{index}".encode())
        job = _job_from_sample(sample)
        states[job.job_id] = SimpleNamespace(
            status="succeeded",
            job=job,
            last_event={"payload": {"outputSha256": sha256_file(output)}},
        )

    queue = SimpleNamespace(states=lambda: states)

    class ReverseOrder:
        @staticmethod
        def shuffle(items: list[dict]) -> None:
            items.reverse()

    monkeypatch.setattr(
        "reel_factory.local_model_arena.secrets.SystemRandom",
        lambda: ReverseOrder(),
    )
    packet = build_arena_review_packet(
        arena_plan=plan,
        queue=queue,
        created_at=PRODUCED_AT,
        evidence_secret=EVIDENCE_SECRET,
    )
    validate_arena_review_packet(
        packet, arena_plan=plan, evidence_secret=EVIDENCE_SECRET
    )
    assert [item["reviewOrdinal"] for item in packet["candidates"]] == [1, 2]
    assert [item["blindedCandidateId"] for item in packet["candidates"]] == [
        item["blindedCandidateId"] for item in reversed(plan["samples"])
    ]
    serialized = json.dumps(packet, sort_keys=True)
    for sample in plan["samples"]:
        assert sample["modelId"] not in serialized
        assert sample["sampleId"] not in serialized
        assert sample["queueJob"]["jobId"] not in serialized
    review_store = HumanMediaReviewStore(tmp_path / "reviews")
    with pytest.raises(
        LocalQueueError, match="unblinding_requires_exact_signed_review_set"
    ):
        build_arena_unblinding_receipt(
            arena_plan=plan,
            review_packet=packet,
            human_reviews=review_store,
            created_at=PRODUCED_AT,
            evidence_secret=EVIDENCE_SECRET,
        )

    planned_by_blind = {item["blindedCandidateId"]: item for item in plan["samples"]}
    for index, candidate in enumerate(packet["candidates"]):
        sample = planned_by_blind[candidate["blindedCandidateId"]]
        review = HumanMediaReview(
            review_id=f"review-{index}",
            arena_plan_id=plan["planId"],
            sample_id=sample["sampleId"],
            blinded_candidate_id=candidate["blindedCandidateId"],
            subject_sha256=candidate["subjectSha256"],
            source_sha256=sample["sourceSha256"],
            reviewer="reviewer@example.test",
            reviewed_at=PRODUCED_AT,
            rubric_version="1.0.0",
            sampling_evidence=HumanReviewSamplingEvidence(
                analysis_id=f"analysis-{index}",
                analysis_fingerprint="d" * 64,
                sample_fps=8.0,
                width=180,
                height=320,
                sampled_frames=48,
                total_frames=180,
                duration_seconds=6.0,
                duration_coverage_ratio=1,
                frame_set_fingerprint="e" * 64,
                brief_frame_outlier_count=0,
                brief_frame_outliers_reviewed=True,
            ),
            ratings=HumanReviewRatings(
                realism=0.9,
                attractiveness=0.9,
                creator_identity_similarity=0.9,
                face_stability=0.9,
                motion_naturalness=0.9,
                face_artifact_score=0.1,
                hands_visible=False,
                hand_artifact_score=None,
                body_artifact_score=0.1,
                conversion_usefulness=0.9,
                intent_adherence=0.9,
                loop_acceptable=True,
            ),
            decisions=HumanReviewDecisions(
                creator_identity_preserved=True,
                anatomy_acceptable=True,
                operator_useful=True,
                approved_for_benchmark=True,
            ),
            provenance=HumanReviewProvenance(
                review_mode="blinded",
                unblinding_reason=None,
                source_references=((packet["packetId"], packet["packetFingerprint"]),),
            ),
        ).attest(evidence_secret=EVIDENCE_SECRET)
        review_store.record(review, output_path=Path(candidate["subjectPath"]))

    receipt = build_arena_unblinding_receipt(
        arena_plan=plan,
        review_packet=packet,
        human_reviews=review_store,
        created_at=PRODUCED_AT,
        evidence_secret=EVIDENCE_SECRET,
    )
    validated_receipt = validate_arena_unblinding_receipt(
        receipt,
        arena_plan=plan,
        review_packet=packet,
        human_reviews=review_store,
        evidence_secret=EVIDENCE_SECRET,
    )
    assert validated_receipt["expectedReviewCount"] == len(plan["samples"])
    assert {item["modelId"] for item in validated_receipt["bindings"]} == {
        item["modelId"] for item in plan["samples"]
    }


def test_arena_plan_rejects_source_substitution(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    source.write_bytes(b"substituted")
    with pytest.raises(LocalQueueError, match="arena_source_missing_or_substituted"):
        validate_arena_plan(plan)


def test_arena_plan_rejects_analyzer_drift(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    sample = plan["samples"][0]
    sample["analyzerRegistry"]["analyzers"][0]["implementationFingerprint"] = "f" * 64
    core = {key: value for key, value in plan.items() if key != "planFingerprint"}
    plan["planFingerprint"] = fingerprint(core)
    with pytest.raises(
        LocalQueueError, match="arena_analyzer_registry_fingerprint_mismatch"
    ):
        validate_arena_plan(plan)


def test_interrupted_sample_is_projected_and_does_not_block_recovery(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    root = tmp_path / "evidence"
    store = LocalModelArenaStore(root)
    store.persist_plan(plan)
    sample = plan["samples"][0]
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=2048)
    job = _job_from_sample(sample)
    queue.submit(job)
    with queue.worker_session() as lease:
        assert queue.start_next(lease).job_id == job.job_id
    with queue.worker_session():
        assert queue.states()[job.job_id].status == "interrupted"
    summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )
    assert summary["expectedSampleCount"] == 1
    assert summary["sampleCounts"]["interrupted"] == 1
    assert summary["promotionEligibleYield"] == 0
    assert summary["samples"][0]["executionEvidence"]["status"] == "interrupted"

    recovered = queue.recover_empty_interruption(
        job.job_id,
        lineage_path=Path(sample["outputPath"]),
        reason="operator verified crash before artifact write",
    )
    assert recovered.status == "queued"
    recovered_summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )
    assert recovered_summary["sampleCounts"]["missing"] == 1
    assert recovered_summary["sampleCounts"]["interrupted"] == 0
    assert recovered_summary["samples"][0]["executionEvidence"]["status"] == "queued"


def test_failed_queue_job_projects_into_honest_arena_denominator(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    root = tmp_path / "evidence"
    store = LocalModelArenaStore(root)
    store.persist_plan(plan)
    sample = plan["samples"][0]
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=1024)
    job = _job_from_sample(sample)
    queue.submit(job)
    with queue.worker_session() as lease:
        assert queue.start_next(lease).job_id == job.job_id
        queue.fail(
            lease,
            job.job_id,
            error=RuntimeError("local_video_generation_failed: offline dependency"),
        )

    summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )

    assert summary["sampleCounts"]["failed"] == 1
    assert summary["samples"][0]["status"] == "failed"
    assert summary["samples"][0]["executionEvidence"]["failureClass"] == (
        "model_process_nonzero_exit"
    )
    assert summary["promotionEligibleYield"] == 0


def test_admission_block_projects_as_resource_blocked_until_retry(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    root = tmp_path / "evidence"
    store = LocalModelArenaStore(root)
    store.persist_plan(plan)
    sample = plan["samples"][0]
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=512)
    job = _job_from_sample(sample)
    queue.submit(job)
    with queue.worker_session() as lease:
        decision = queue.start_next(lease)
    assert decision.admitted is False

    summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )

    assert summary["sampleCounts"]["resource_blocked"] == 1
    assert summary["samples"][0]["status"] == "resource_blocked"
    assert summary["promotionEligibleYield"] == 0


def test_cancelled_queue_job_remains_in_honest_arena_denominator(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    root = tmp_path / "evidence"
    store = LocalModelArenaStore(root)
    store.persist_plan(plan)
    sample = plan["samples"][0]
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=512)
    job = _job_from_sample(sample)
    queue.submit(job)
    with queue.worker_session() as lease:
        assert queue.start_next(lease).admitted is False
    queue.cancel_queued(job.job_id, reason="operator retired blocked sample")

    summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )

    assert summary["sampleCounts"]["cancelled"] == 1
    assert summary["samples"][0]["status"] == "cancelled"
    assert summary["samples"][0]["reason"] == "operator retired blocked sample"
    assert summary["promotionEligibleYield"] == 0


@pytest.mark.parametrize("status", ("interrupted", "resource_blocked", "missing"))
def test_projected_arena_statuses_cannot_be_recorded_as_immutable_terminals(
    monkeypatch, tmp_path: Path, status: str
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    store = LocalModelArenaStore(tmp_path / "evidence")
    store.persist_plan(plan)

    with pytest.raises(ValueError, match="arena_terminal_status_invalid"):
        store.record_terminal(
            plan_id=plan["planId"],
            sample_id=plan["samples"][0]["sampleId"],
            status=status,
            reason="must remain projected",
        )


def test_human_review_rejections_block_promotion_evidence() -> None:
    review = SimpleNamespace(
        ratings=SimpleNamespace(
            realism=1.0,
            attractiveness=1.0,
            creator_identity_similarity=1.0,
            face_stability=1.0,
            motion_naturalness=1.0,
            conversion_usefulness=1.0,
            intent_adherence=1.0,
            face_artifact_score=0.0,
            body_artifact_score=0.0,
            hands_visible=False,
            hand_artifact_score=None,
        ),
        decisions=SimpleNamespace(
            creator_identity_preserved=False,
            anatomy_acceptable=False,
            operator_useful=False,
            approved_for_benchmark=False,
        ),
    )

    blockers, quality = _human_review_evidence(review)

    assert blockers == [
        "human_review_creator_identity_rejected",
        "human_review_anatomy_rejected",
        "human_review_operator_usefulness_rejected",
        "human_review_benchmark_rejected",
    ]
    assert quality == 1.0


def test_human_quality_includes_attractiveness_and_visible_hand_artifacts() -> None:
    review = SimpleNamespace(
        ratings=SimpleNamespace(
            realism=1.0,
            attractiveness=0.0,
            creator_identity_similarity=1.0,
            face_stability=1.0,
            motion_naturalness=1.0,
            conversion_usefulness=1.0,
            intent_adherence=1.0,
            face_artifact_score=0.0,
            body_artifact_score=0.0,
            hands_visible=True,
            hand_artifact_score=1.0,
        ),
        decisions=SimpleNamespace(
            creator_identity_preserved=True,
            anatomy_acceptable=True,
            operator_useful=True,
            approved_for_benchmark=True,
        ),
    )

    blockers, quality = _human_review_evidence(review)

    assert blockers == []
    assert quality == pytest.approx(0.8)


def test_promotion_review_rejects_future_and_unblinded_evidence() -> None:
    plan = {
        "planId": "plan-1",
        "planFingerprint": SHA_A,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    sample = {
        "sampleId": "sample-1",
        "blindedCandidateId": "candidate-1",
        "sourceSha256": SHA_B,
        "queueJobFingerprint": "c" * 64,
        "identityProfileId": "identity-1",
        "identityProfileFingerprint": "d" * 64,
        "contentIntentId": "intent-1",
        "contentIntentFingerprint": "e" * 64,
    }
    review = SimpleNamespace(
        reviewed_at="2999-01-01T00:00:00Z",
        arena_plan_id="plan-1",
        sample_id="sample-1",
        blinded_candidate_id="candidate-1",
        source_sha256=SHA_B,
        provenance=SimpleNamespace(
            review_mode="blinded", unblinding_reason=None, source_references=()
        ),
    )
    with pytest.raises(LocalQueueError, match="human_review_from_future"):
        _validate_human_review_binding(review, plan=plan, sample=sample)

    review.reviewed_at = "2026-07-01T00:00:00Z"
    review.provenance = SimpleNamespace(
        review_mode="unblinded",
        unblinding_reason="operator inspected model identity",
        source_references=(),
    )
    with pytest.raises(LocalQueueError, match="human_review_plan_binding_mismatch"):
        _validate_human_review_binding(review, plan=plan, sample=sample)


def test_human_review_binds_exact_trusted_full_duration_frame_set() -> None:
    plan = {
        "planId": "plan-1",
        "planFingerprint": SHA_A,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    sample = {
        "sampleId": "sample-1",
        "blindedCandidateId": "candidate-1",
        "sourceSha256": SHA_B,
        "queueJobFingerprint": "c" * 64,
        "identityProfileId": "identity-1",
        "identityProfileFingerprint": "d" * 64,
        "contentIntentId": "intent-1",
        "contentIntentFingerprint": "e" * 64,
    }
    analysis = {
        "analysisId": "analysis-1",
        "analysisFingerprint": "f" * 64,
        "producedAt": "2026-07-01T00:00:00Z",
        "humanReviewSampling": {
            "sampleFps": 8.0,
            "width": 180,
            "height": 320,
            "sampledFrames": 48,
            "totalFrames": 180,
            "durationSeconds": 6.0,
            "durationCoverageRatio": 1,
            "frameSetFingerprint": "1" * 64,
            "briefFrameOutlierCount": 2,
        },
    }
    references = (
        ("plan-1", SHA_A),
        ("sample-1", "c" * 64),
        ("identity-1", "d" * 64),
        ("intent-1", "e" * 64),
        ("analysis-1", "f" * 64),
    )
    review = SimpleNamespace(
        reviewed_at="2026-07-02T00:00:00Z",
        arena_plan_id="plan-1",
        sample_id="sample-1",
        blinded_candidate_id="candidate-1",
        source_sha256=SHA_B,
        provenance=SimpleNamespace(
            review_mode="blinded",
            unblinding_reason=None,
            source_references=references,
        ),
        sampling_evidence=HumanReviewSamplingEvidence.from_trusted_analysis(analysis),
    )

    _validate_human_review_binding(review, plan=plan, sample=sample, analysis=analysis)

    review.sampling_evidence = HumanReviewSamplingEvidence.from_dict(
        {
            **review.sampling_evidence.as_dict(),
            "frameSetFingerprint": "2" * 64,
        }
    )
    with pytest.raises(LocalQueueError, match="sampling_binding_mismatch"):
        _validate_human_review_binding(
            review, plan=plan, sample=sample, analysis=analysis
        )


@pytest.mark.parametrize(
    ("sample", "expected"),
    (
        (
            {"taskKind": "image_to_video", "audioMode": "none"},
            {"expectsAudio": False, "expectsSpeech": False},
        ),
        (
            {"taskKind": "image_to_video", "audioMode": "generated"},
            {"expectsAudio": True, "expectsSpeech": False},
        ),
        (
            {"taskKind": "audio_image_to_video", "audioMode": "source"},
            {"expectsAudio": True, "expectsSpeech": True},
        ),
    ),
)
def test_motion_qc_applicability_tracks_audio_and_speaking_modes(
    sample: dict[str, str], expected: dict[str, bool]
) -> None:
    assert _motion_qc_options(sample) == expected


def test_terminal_exact_replay_is_idempotent_but_changed_payload_collides(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    store = LocalModelArenaStore(tmp_path / "evidence")
    store.persist_plan(plan)
    kwargs = {
        "plan_id": plan["planId"],
        "sample_id": plan["samples"][0]["sampleId"],
        "status": "failed",
        "reason": "local_failure",
    }
    first = store.record_terminal(**kwargs)
    assert store.record_terminal(**kwargs) == first
    assert len(store.events.read().events) == 1
    with pytest.raises(LocalQueueError, match="arena_terminal_sample_collision"):
        store.record_terminal(**{**kwargs, "reason": "different_failure"})


def test_plan_persistence_rejects_collision(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    store = LocalModelArenaStore(tmp_path / "evidence")
    path = store.persist_plan(plan)
    decoded = json.loads(path.read_text())
    decoded["purpose"] = "promotion_eligible"
    path.write_text(json.dumps(decoded))
    with pytest.raises(LocalQueueError, match="arena_plan_identity_collision"):
        store.persist_plan(plan)


def test_promotion_plan_requires_two_sources_and_two_seeds(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    repository_root = Path(__file__).resolve().parents[3]
    registry = arena_analyzer_registry(
        _base_registry(repository_root),
        produced_at=PRODUCED_AT,
        repository_root=repository_root,
    )
    monkeypatch.setattr(
        "reel_factory.local_model_arena.model_status",
        lambda *_args, **_kwargs: {
            "ready": True,
            "issues": [],
            "manifestSha256": "c" * 64,
            "manifest": {"revision": "model-revision"},
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_model_arena.plan_local_video_job", _fake_job
    )
    with pytest.raises(LocalQueueError, match="arena_promotion_requires_two_sources"):
        build_arena_plan(
            sample_specs=[
                _spec(source, creator=creator, seed=1)
                for creator in ("stacey", "larissa", "lola")
            ],
            purpose="promotion_eligible",
            produced_at=PRODUCED_AT,
            output_root=tmp_path / "arena",
            execution_policy=_policy(),
            analyzer_registry=registry,
        )


def test_promotion_comparison_requires_exact_non_model_grid(tmp_path: Path) -> None:
    sources = [tmp_path / "source-a.jpg", tmp_path / "source-b.jpg"]
    for index, source in enumerate(sources):
        source.write_bytes(f"source-{index}".encode())
    models = (
        "local_wan22_ti2v_5b_mlx",
        "local_wan22_i2v_a14b_q4_mlx",
    )
    matched = [
        _spec(source, creator=creator, seed=seed, model_id=model_id)
        for creator in ("stacey", "larissa", "lola")
        for model_id in models
        for source in sources
        for seed in (1, 2)
    ]
    _promotion_design_check(matched)

    unmatched = list(matched)
    changed = unmatched[-1]
    unmatched[-1] = ArenaSampleSpec(
        creator_id=changed.creator_id,
        identity_profile_id=changed.identity_profile_id,
        identity_profile_fingerprint=changed.identity_profile_fingerprint,
        content_intent_id=changed.content_intent_id,
        content_intent_fingerprint=changed.content_intent_fingerprint,
        source_path=changed.source_path,
        model_id=changed.model_id,
        capability_cohort=changed.capability_cohort,
        task_kind=changed.task_kind,
        prompt="A different prompt that confounds the model comparison.",
        seed=changed.seed,
        duration_seconds=changed.duration_seconds,
        resolution=changed.resolution,
        audio_mode=changed.audio_mode,
        audio_path=changed.audio_path,
        overlays_exist=changed.overlays_exist,
    )
    with pytest.raises(LocalQueueError, match="arena_promotion_unmatched_model_grid"):
        _promotion_design_check(unmatched)
