from __future__ import annotations

import ast
from pathlib import Path

from reel_factory import generate_assets
from reel_factory.generation_asset_models import (
    CAPABILITY_SCHEMA,
    DIRECT_REFERENCE_SEED_PROMPT,
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_TIMEOUT_SECONDS,
    IMAGE_MODEL_CANDIDATES,
    MIN_IMAGE_RESULT_BYTES,
    MIN_VIDEO_RESULT_BYTES,
    VIDEO_MODEL_CANDIDATES,
    VIDEO_SOUND_MODELS,
    AssetGenerationPlan,
    DirectReferenceImagePlan,
)
from reel_factory.generation_lineage import build_source_lineage
from reel_factory.generation_provider import (
    HiggsfieldCliAdapter,
    HiggsfieldCommandError,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "reel_factory"
SPLIT_MODULES = {
    "generate_assets.py": {"create_assets", "create_image_asset", "main"},
    "generation_asset_models.py": {"AssetGenerationPlan", "DirectReferenceImagePlan"},
    "generation_provider.py": {"HiggsfieldCliAdapter", "probe_higgsfield_capabilities"},
    "generation_qc.py": {"generated_image_qc", "generated_video_qc"},
    "generation_lineage.py": {"build_source_lineage", "direct_reference_lineage"},
}


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_generate_assets_split_has_bounded_cohesive_modules() -> None:
    for name, required_owners in SPLIT_MODULES.items():
        path = PACKAGE_ROOT / name
        assert len(path.read_text(encoding="utf-8").splitlines()) < 1_500, name
        assert required_owners <= _top_level_definitions(path), name


def test_generate_assets_keeps_compatibility_imports() -> None:
    assert generate_assets.AssetGenerationPlan is AssetGenerationPlan
    assert generate_assets.DirectReferenceImagePlan is DirectReferenceImagePlan
    assert generate_assets.HiggsfieldCliAdapter is HiggsfieldCliAdapter
    assert generate_assets.HiggsfieldCommandError is HiggsfieldCommandError
    assert generate_assets.build_source_lineage is build_source_lineage
    assert generate_assets.CAPABILITY_SCHEMA == CAPABILITY_SCHEMA
    assert generate_assets.DIRECT_REFERENCE_SEED_PROMPT == DIRECT_REFERENCE_SEED_PROMPT
    assert generate_assets.DOWNLOAD_CHUNK_BYTES == DOWNLOAD_CHUNK_BYTES
    assert generate_assets.DOWNLOAD_TIMEOUT_SECONDS == DOWNLOAD_TIMEOUT_SECONDS
    assert generate_assets.IMAGE_MODEL_CANDIDATES == IMAGE_MODEL_CANDIDATES
    assert generate_assets.MIN_IMAGE_RESULT_BYTES == MIN_IMAGE_RESULT_BYTES
    assert generate_assets.MIN_VIDEO_RESULT_BYTES == MIN_VIDEO_RESULT_BYTES
    assert generate_assets.VIDEO_MODEL_CANDIDATES == VIDEO_MODEL_CANDIDATES
    assert generate_assets.VIDEO_SOUND_MODELS == VIDEO_SOUND_MODELS


def test_generate_assets_coordinator_does_not_reown_extracted_implementations() -> None:
    definitions = _top_level_definitions(PACKAGE_ROOT / "generate_assets.py")
    assert "HiggsfieldCliAdapter" not in definitions
    assert "AssetGenerationPlan" not in definitions
    assert "DirectReferenceImagePlan" not in definitions
    assert "build_source_lineage" not in definitions
    assert "direct_reference_lineage" not in definitions


def test_generate_assets_cli_preserves_the_complete_argument_surface() -> None:
    parser = generate_assets._parser()
    assert parser.description == (
        "Generate and track Higgsfield/Kling source assets from clean prompt JSON."
    )
    actions = {
        action.dest: action for action in parser._actions if action.dest != "help"
    }
    assert set(actions) == {
        "mode",
        "root",
        "prompt_json",
        "stem",
        "reference",
        "campaign",
        "creator",
        "soul_id",
        "soul_name",
        "start_image",
        "end_image",
        "video_reference",
        "selected_panel",
        "image_mode",
        "out_dir",
        "image_aspect_ratio",
        "image_quality",
        "video_aspect_ratio",
        "video_duration",
        "max_video_duration",
        "video_mode",
        "video_sound",
        "image_model",
        "video_model",
        "cohort_id",
        "max_credits",
        "estimated_cost_usd",
        "allow_unbudgeted_local_test",
        "budget_override_ledger_error",
        "spend_authorization_file",
        "execution_plan_file",
        "lineage",
        "wait",
        "download",
        "force",
    }
    assert tuple(actions["mode"].choices) == (
        "create",
        "dry-run",
        "image",
        "image-dry-run",
        "reference-image",
        "reference-image-dry-run",
        "video",
        "video-dry-run",
        "wait",
        "status",
        "capabilities",
        "failed-generations",
    )


def test_generated_video_qc_uses_the_historical_module_sampler_seam(
    monkeypatch, tmp_path: Path
) -> None:
    video = tmp_path / "clip.mp4"
    frame = tmp_path / "frame.jpg"
    calls: list[Path] = []

    def sample(path: Path) -> list[Path]:
        calls.append(path)
        return [frame]

    monkeypatch.setattr(generate_assets, "_sample_video_frames", sample)
    monkeypatch.setattr(generate_assets, "assess_image_qc", lambda *args, **kwargs: {})
    monkeypatch.setattr(generate_assets, "is_image_postable", lambda assessment: True)

    result = generate_assets.generated_video_qc(
        {"video": str(video)}, root=tmp_path, required=True
    )

    assert calls == [video]
    assert result["status"] == "passed"
