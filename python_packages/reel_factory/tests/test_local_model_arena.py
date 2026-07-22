from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
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
    arena_analyzer_registry,
    build_arena_plan,
    validate_arena_plan,
)
from reel_factory.local_model_benchmark import LocalModelBenchmarkStore

PRODUCED_AT = "2026-07-22T12:00:00Z"
SHA_A = "a" * 64
SHA_B = "b" * 64


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
            "analyzerVersion": "1.0.0",
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


def _build(monkeypatch, tmp_path: Path, specs: list[ArenaSampleSpec]) -> dict:
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


def test_interrupted_sample_remains_in_honest_denominator(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe source")
    plan = _build(monkeypatch, tmp_path, [_spec(source)])
    root = tmp_path / "evidence"
    store = LocalModelArenaStore(root)
    store.persist_plan(plan)
    sample_id = plan["samples"][0]["sampleId"]
    store.record_terminal(
        plan_id=plan["planId"],
        sample_id=sample_id,
        status="interrupted",
        reason="operator_interrupted",
    )
    queue = LocalGenerationQueue(tmp_path / "queue", resource_limit_bytes=1024)
    summary = store.summarize(
        plan["planId"],
        queue=queue,
        benchmarks=LocalModelBenchmarkStore(root),
    )
    assert summary["expectedSampleCount"] == 1
    assert summary["sampleCounts"]["interrupted"] == 1
    assert summary["promotionEligibleYield"] == 0
    assert summary["samples"][0]["blockingReasons"] == ["queue_job_missing"]


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


def test_duplicate_terminal_identity_is_rejected(monkeypatch, tmp_path: Path) -> None:
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
    store.record_terminal(**kwargs)
    with pytest.raises(LocalQueueError, match="arena_duplicate_terminal_sample"):
        store.record_terminal(**kwargs)


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
