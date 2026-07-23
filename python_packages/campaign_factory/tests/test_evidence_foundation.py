from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from campaign_factory.evidence_foundation import (
    ThinEvidenceCompatibilityError,
    canonical_json_sha256,
    compile_thin_evidence_records,
    snapshot_content_intent,
    snapshot_creator_identity_profile,
    validate_library_reuse_evidence_binding,
)
from campaign_factory.generation_execution_plan import (
    build_generation_execution_plan,
)
from campaign_factory.generation_workflow import run_generation_workflow
from campaign_factory.library_reuse import LibraryReuseRepository
from campaign_test_support import make_factory

from pipeline_contracts import (
    AnalyzerRegistrationV1,
    AnalyzerRegistryV1,
    AnalyzerRequirementV1,
    BenchmarkRecipeV1,
    ContentIntentV1,
    CreatorIdentityProfileV1,
    IdentityReferenceV1,
    ProvenanceV1,
    SourceReferenceV1,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
PRODUCED_AT = "2026-07-22T12:00:00Z"


def _provenance(producer: str, source_id: str, fingerprint: str) -> ProvenanceV1:
    return ProvenanceV1(
        producer=producer,
        produced_at=PRODUCED_AT,
        source_references=(
            SourceReferenceV1(record_id=source_id, fingerprint=fingerprint),
        ),
    )


def _records(
    media_sha256: str,
) -> tuple[
    CreatorIdentityProfileV1,
    ContentIntentV1,
    BenchmarkRecipeV1,
    AnalyzerRegistryV1,
]:
    identity = snapshot_creator_identity_profile(
        {
            "id": "identity_stacey_v1",
            "modelSlug": "stacey",
            "label": "Stacey",
        },
        identity_references=(
            IdentityReferenceV1(
                namespace="higgsfield_soul",
                external_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            ),
        ),
        provenance=_provenance("campaign_factory", "model:stacey", SHA_A),
    )
    intent = snapshot_content_intent(
        {"goal": "views_reach", "style_lanes": ["amateur_native"]},
        intent_id="intent_library_reuse_stacey_001",
        creator_identity_profile_id=identity.profile_id,
        content_surface="reel",
        media_kind="video",
        concept_tags=("library_reuse",),
        source_asset_fingerprints=(media_sha256,),
        provenance=_provenance("campaign_factory", "creative_plan:reuse", SHA_B),
    )
    recipe = BenchmarkRecipeV1(
        recipe_id="benchmark_library_reuse_preflight_v1",
        content_intent_id=intent.intent_id,
        execution_policy_schema="campaign_factory.generation_execution_plan.v1",
        execution_policy_fingerprint=canonical_json_sha256(
            build_generation_execution_plan("library_reuse").to_contract()
        ),
        task_kind="library_reuse_preflight",
        input_fingerprints=(media_sha256,),
        parameter_fingerprint=canonical_json_sha256(
            {"format": "reel", "variantCount": 1, "workers": 1}
        ),
        required_analyzers=(
            AnalyzerRequirementV1(
                analyzer_id="contentforge.campaign_factory_audit",
                analyzer_version="1.10.0",
            ),
        ),
        expected_provider_calls=0,
        production_writes_allowed=False,
        provenance=_provenance("reel_factory", intent.intent_id, SHA_A),
    )
    registry = AnalyzerRegistryV1(
        registry_id="contentforge_analyzers_2026_07_22",
        analyzers=(
            AnalyzerRegistrationV1(
                analyzer_id="contentforge.campaign_factory_audit",
                analyzer_version="1.10.0",
                evidence_kinds=("campaign_audit",),
                implementation_ref="packages/contentforge/lib/pipeline.js",
                implementation_fingerprint=(
                    "bece1a766d4f14bf4b7b585875ebf8f26042912f9b40282d43197cc86072f340"
                ),
            ),
        ),
        provenance=_provenance(
            "contentforge", "contentforge:campaign_factory_audit.v1.10", SHA_B
        ),
    )
    return identity, intent, recipe, registry


def test_incompatible_thin_evidence_records_fail_closed() -> None:
    identity, intent, recipe, registry = _records(SHA_A)
    mismatched_intent = ContentIntentV1(
        intent_id=intent.intent_id,
        creator_identity_profile_id="identity_lola_v1",
        goal=intent.goal,
        content_surface=intent.content_surface,
        media_kind=intent.media_kind,
        style_lanes=intent.style_lanes,
        concept_tags=intent.concept_tags,
        source_asset_fingerprints=intent.source_asset_fingerprints,
        provenance=intent.provenance,
    )

    with pytest.raises(
        ThinEvidenceCompatibilityError,
        match="thin_evidence_creator_identity_profile_mismatch",
    ):
        compile_thin_evidence_records(
            creator_identity_profile=identity,
            content_intent=mismatched_intent,
            execution_policy=build_generation_execution_plan(
                "library_reuse"
            ).to_contract(),
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_benchmark_recipe_inputs_are_exact_subset_of_intent_authorization() -> None:
    identity, intent, recipe, registry = _records(SHA_A)
    shared_intent = ContentIntentV1(
        intent_id=intent.intent_id,
        creator_identity_profile_id=intent.creator_identity_profile_id,
        goal=intent.goal,
        content_surface=intent.content_surface,
        media_kind=intent.media_kind,
        style_lanes=intent.style_lanes,
        concept_tags=intent.concept_tags,
        source_asset_fingerprints=(SHA_A, SHA_B),
        provenance=intent.provenance,
    )
    records = compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=shared_intent,
        execution_policy=build_generation_execution_plan("library_reuse").to_contract(),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
    assert records["contentIntent"]["sourceAssetFingerprints"] == [SHA_A, SHA_B]
    assert records["benchmarkRecipe"]["inputFingerprints"] == [SHA_A]

    unlisted_recipe = BenchmarkRecipeV1(
        recipe_id=recipe.recipe_id,
        content_intent_id=recipe.content_intent_id,
        execution_policy_schema=recipe.execution_policy_schema,
        execution_policy_fingerprint=recipe.execution_policy_fingerprint,
        task_kind=recipe.task_kind,
        input_fingerprints=("c" * 64,),
        parameter_fingerprint=recipe.parameter_fingerprint,
        required_analyzers=recipe.required_analyzers,
        expected_provider_calls=recipe.expected_provider_calls,
        production_writes_allowed=recipe.production_writes_allowed,
        provenance=recipe.provenance,
    )
    with pytest.raises(
        ThinEvidenceCompatibilityError,
        match="thin_evidence_benchmark_input_mismatch",
    ):
        compile_thin_evidence_records(
            creator_identity_profile=identity,
            content_intent=shared_intent,
            execution_policy=build_generation_execution_plan(
                "library_reuse"
            ).to_contract(),
            benchmark_recipe=unlisted_recipe,
            analyzer_registry=registry,
        )


@pytest.mark.parametrize(
    ("model_slug", "source_fingerprints", "variant_count", "error_code"),
    [
        ("lola", (SHA_A,), 1, "thin_evidence_creator_run_mismatch"),
        ("stacey", (SHA_B,), 1, "thin_evidence_selected_input_mismatch"),
        ("stacey", (SHA_A,), 2, "thin_evidence_parameter_mismatch"),
    ],
)
def test_library_reuse_evidence_is_bound_to_the_exact_run(
    model_slug: str,
    source_fingerprints: tuple[str, ...],
    variant_count: int,
    error_code: str,
) -> None:
    identity, intent, recipe, registry = _records(SHA_A)
    records = compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=intent,
        execution_policy=build_generation_execution_plan("library_reuse").to_contract(),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )

    with pytest.raises(ThinEvidenceCompatibilityError, match=error_code):
        validate_library_reuse_evidence_binding(
            records,
            model_slug=model_slug,
            selected_source_fingerprints=source_fingerprints,
            output_format="reel",
            variant_count=variant_count,
            workers=1,
        )


def test_library_reuse_evidence_preserves_source_order() -> None:
    identity, intent, recipe, registry = _records(SHA_A)
    intent = ContentIntentV1(
        intent_id=intent.intent_id,
        creator_identity_profile_id=intent.creator_identity_profile_id,
        goal=intent.goal,
        content_surface=intent.content_surface,
        media_kind=intent.media_kind,
        style_lanes=intent.style_lanes,
        concept_tags=intent.concept_tags,
        source_asset_fingerprints=(SHA_A, SHA_B),
        provenance=intent.provenance,
    )
    recipe = BenchmarkRecipeV1(
        recipe_id=recipe.recipe_id,
        content_intent_id=recipe.content_intent_id,
        execution_policy_schema=recipe.execution_policy_schema,
        execution_policy_fingerprint=recipe.execution_policy_fingerprint,
        task_kind=recipe.task_kind,
        input_fingerprints=(SHA_A, SHA_B),
        parameter_fingerprint=recipe.parameter_fingerprint,
        required_analyzers=recipe.required_analyzers,
        expected_provider_calls=recipe.expected_provider_calls,
        production_writes_allowed=recipe.production_writes_allowed,
        provenance=recipe.provenance,
    )
    records = compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=intent,
        execution_policy=build_generation_execution_plan("library_reuse").to_contract(),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )

    with pytest.raises(
        ThinEvidenceCompatibilityError,
        match="thin_evidence_selected_input_mismatch",
    ):
        validate_library_reuse_evidence_binding(
            records,
            model_slug="stacey",
            selected_source_fingerprints=(SHA_B, SHA_A),
            output_format="reel",
            variant_count=1,
            workers=1,
        )


def test_library_reuse_dry_run_carries_records_without_side_effects(
    tmp_path: Path,
) -> None:
    library = tmp_path / "selected"
    library.mkdir()
    media = library / "safe.mp4"
    media.write_bytes(b"local-only-library-reuse-canary")
    media_sha256 = hashlib.sha256(media.read_bytes()).hexdigest()
    identity, intent, recipe, registry = _records(media_sha256)

    planner = object.__new__(LibraryReuseRepository)
    planner._sha256_file = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    planner._slugify = lambda value: str(value).strip().lower().replace(" ", "-")
    factory = SimpleNamespace(
        domains=SimpleNamespace(library_reuse=planner),
    )
    before = {
        path.relative_to(tmp_path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = run_generation_workflow(
        factory,
        mode="library_reuse",
        campaign_slug="local_thin_evidence_canary",
        dry_run=True,
        apply=False,
        library_folder=library,
        model_slug="stacey",
        output_format="reel",
        variant_count=1,
        workers=1,
        creator_identity_profile=identity,
        content_intent=intent,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )

    assert result["result"]["providerCalls"] == 0
    assert result["result"]["paidGenerationAllowed"] is False
    assert result["result"]["renderingPerformed"] is False
    assert result["dryRun"] is True
    assert result["apply"] is False
    assert result["schedulingAllowed"] is False
    assert result["publishingAllowed"] is False
    assert result["evidenceRecords"] == compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=intent,
        execution_policy=build_generation_execution_plan("library_reuse").to_contract(),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
    after = {
        path.relative_to(tmp_path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_library_reuse_apply_persists_only_the_exact_validated_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = tmp_path / "selected"
    library.mkdir()
    media = library / "safe.mp4"
    media.write_bytes(b"isolated-library-reuse-evidence-apply")
    media_sha256 = hashlib.sha256(media.read_bytes()).hexdigest()
    identity, intent, recipe, registry = _records(media_sha256)
    expected = compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=intent,
        execution_policy=build_generation_execution_plan("library_reuse").to_contract(),
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
    factory = make_factory(tmp_path)

    def forbidden_process(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("thin evidence canary must not call a provider subprocess")

    def audit(**kwargs: Any) -> dict[str, Any]:
        return {
            "reports": [
                {
                    "renderedAssetId": asset_id,
                    "failedChecks": [],
                    "warnings": [],
                    "overallVerdict": "pass",
                }
                for asset_id in kwargs["rendered_asset_ids"]
            ]
        }

    try:
        factory.domains.library_reuse._audit_campaign = audit
        monkeypatch.setattr(subprocess, "run", forbidden_process)
        monkeypatch.setattr(subprocess, "Popen", forbidden_process)
        result = run_generation_workflow(
            factory,
            mode="library_reuse",
            campaign_slug="local_thin_evidence_apply_canary",
            dry_run=False,
            apply=True,
            library_folder=library,
            model_slug="stacey",
            output_format="reel",
            variant_count=1,
            workers=1,
            creator_identity_profile=identity,
            content_intent=intent,
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )["result"]

        manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
        assert manifest["evidenceRecords"] == expected
        assert manifest["selected"][0]["sourceSha256"] == media_sha256
        assert result["providerCalls"] == 0
        assert result["paidGeneration"] is False
        assert result["renderingPerformed"] is False
    finally:
        factory.close()


def test_library_reuse_repository_rejects_unvalidated_evidence_before_writes(
    tmp_path: Path,
) -> None:
    library = tmp_path / "selected"
    library.mkdir()
    (library / "safe.mp4").write_bytes(b"invalid-evidence-boundary")
    factory = make_factory(tmp_path)
    try:
        with pytest.raises(
            ThinEvidenceCompatibilityError,
            match="thin_evidence_record_set_invalid",
        ):
            factory.domains.library_reuse.run(
                folder=library,
                campaign_slug="invalid_evidence_canary",
                model_slug="stacey",
                evidence_records={"unvalidated": True},
            )
        assert (
            factory.conn.execute("SELECT COUNT(*) AS c FROM pipeline_jobs").fetchone()[
                "c"
            ]
            == 0
        )
    finally:
        factory.close()
