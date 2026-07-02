from __future__ import annotations

import importlib
from pathlib import Path

MIGRATED_SHIM_CRITICAL_EXPORTS = {
    "caption_bank": ("caption_hash", "refresh_caption_weights"),
    "export_approved": ("export_approved", "_load_generated_asset_lineage_sidecar"),
    "fetch_models": ("DEST", "fetch", "main"),
    "manifest": ("Manifest", "sha256_str"),
    "metrics_store": ("ensure_metrics_schema", "import_metrics_csv"),
    "review_batch_guard": ("validate_review_batch", "main"),
}


def test_migrated_shim_critical_modules_import_from_package_and_flat_paths() -> None:
    for module_name, required_exports in MIGRATED_SHIM_CRITICAL_EXPORTS.items():
        packaged = importlib.import_module(f"reel_factory.{module_name}")
        flat = importlib.import_module(module_name)

        assert flat.__doc__
        assert packaged.__name__ == f"reel_factory.{module_name}"
        for export_name in required_exports:
            assert getattr(flat, export_name) is getattr(packaged, export_name)


def test_packaged_fetch_models_keeps_root_models_directory() -> None:
    packaged = importlib.import_module("reel_factory.fetch_models")

    assert Path(packaged.DEST).name == "models"
    assert Path(packaged.DEST).parent.name == "reel_factory"
