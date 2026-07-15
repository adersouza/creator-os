from __future__ import annotations

from pathlib import Path

from creator_os_core.runtime_paths import resolve_component_roots, resolve_runtime_paths


def test_runtime_paths_derive_canonical_monorepo_layout(tmp_path: Path) -> None:
    source = tmp_path / "creator-os"
    paths = resolve_runtime_paths(source, env={})

    assert paths.source_root == source
    assert paths.runtime_root == tmp_path / "creator-os-runtime"
    assert paths.config_root == Path.home() / ".creator-os"
    assert paths.state_root == Path.home() / ".creator-os/state"
    assert paths.artifact_root == Path.home() / ".creator-os/artifacts"
    assert paths.model_root == Path.home() / ".creator-os/models"
    assert paths.log_root == Path.home() / ".creator-os/logs"
    assert paths.contentforge_root == source / "packages/contentforge"
    assert paths.threadsdash_root == tmp_path / "ThreadsDashboard"
    assert (
        paths.reference_data_root
        == Path.home() / ".creator-os/artifacts/reference_factory"
    )
    assert (
        paths.campaign_factory_db
        == Path.home() / ".creator-os/state/campaign_factory/campaign_factory.sqlite"
    )
    assert (
        paths.reference_factory_db
        == Path.home() / ".creator-os/state/reference_factory/reference_factory.sqlite"
    )
    assert (
        paths.reel_manifest_db
        == Path.home() / ".creator-os/state/reel_factory/manifest.sqlite"
    )
    assert (
        paths.reel_render_queue_db
        == Path.home() / ".creator-os/state/reel_factory/render_queue.sqlite"
    )


def test_runtime_paths_honor_explicit_overrides(tmp_path: Path) -> None:
    override = tmp_path / "runtime"
    paths = resolve_runtime_paths(
        tmp_path / "ignored",
        env={
            "HOME": str(tmp_path / "home"),
            "CREATOR_OS_ROOT": str(tmp_path / "source"),
            "CREATOR_OS_RUNTIME_ROOT": str(override),
            "CREATOR_OS_STATE_ROOT": str(tmp_path / "state"),
            "CREATOR_OS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "CREATOR_OS_MODEL_ROOT": str(tmp_path / "models"),
            "CREATOR_OS_LOG_ROOT": str(tmp_path / "logs"),
            "CONTENTFORGE_ROOT": str(tmp_path / "qc"),
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign.sqlite"),
            "REFERENCE_FACTORY_DB": str(tmp_path / "reference.sqlite"),
            "REEL_FACTORY_MANIFEST_DB": str(tmp_path / "manifest.sqlite"),
            "REEL_FACTORY_RENDER_QUEUE_DB": str(tmp_path / "queue.sqlite"),
        },
    )

    assert paths.source_root == tmp_path / "source"
    assert paths.runtime_root == override
    assert paths.config_root == tmp_path / "home/.creator-os"
    assert paths.state_root == tmp_path / "state"
    assert paths.artifact_root == tmp_path / "artifacts"
    assert paths.model_root == tmp_path / "models"
    assert paths.log_root == tmp_path / "logs"
    assert paths.contentforge_root == tmp_path / "qc"
    assert paths.campaign_factory_db == tmp_path / "campaign.sqlite"
    assert paths.reference_factory_db == tmp_path / "reference.sqlite"
    assert paths.reel_manifest_db == tmp_path / "manifest.sqlite"
    assert paths.reel_render_queue_db == tmp_path / "queue.sqlite"


def test_component_roots_support_flat_test_fixtures(tmp_path: Path) -> None:
    for name in ("reel_factory", "contentforge", "reference_factory"):
        (tmp_path / name).mkdir()

    roots = resolve_component_roots(tmp_path, env={})

    assert roots["reel_factory"] == tmp_path / "reel_factory"
    assert roots["contentforge"] == tmp_path / "contentforge"
    assert roots["reference_factory"] == tmp_path / "reference_factory"
    assert roots["ThreadsDashboard"] == tmp_path.parent / "ThreadsDashboard"
