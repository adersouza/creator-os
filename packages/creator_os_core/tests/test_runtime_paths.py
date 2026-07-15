from __future__ import annotations

from pathlib import Path

from creator_os_core.runtime_paths import resolve_component_roots, resolve_runtime_paths


def test_runtime_paths_derive_canonical_monorepo_layout(tmp_path: Path) -> None:
    source = tmp_path / "creator-os"
    paths = resolve_runtime_paths(source, env={})

    assert paths.source_root == source
    assert paths.runtime_root == tmp_path / "creator-os-runtime"
    assert paths.contentforge_root == source / "packages/contentforge"
    assert paths.threadsdash_root == tmp_path / "ThreadsDashboard"
    assert paths.reference_data_root == tmp_path / "reference_reels"


def test_runtime_paths_honor_explicit_overrides(tmp_path: Path) -> None:
    override = tmp_path / "runtime"
    paths = resolve_runtime_paths(
        tmp_path / "ignored",
        env={
            "CREATOR_OS_ROOT": str(tmp_path / "source"),
            "CREATOR_OS_RUNTIME_ROOT": str(override),
            "CONTENTFORGE_ROOT": str(tmp_path / "qc"),
        },
    )

    assert paths.source_root == tmp_path / "source"
    assert paths.runtime_root == override
    assert paths.contentforge_root == tmp_path / "qc"


def test_component_roots_support_flat_test_fixtures(tmp_path: Path) -> None:
    for name in ("reel_factory", "contentforge", "reference_factory"):
        (tmp_path / name).mkdir()

    roots = resolve_component_roots(tmp_path, env={})

    assert roots["reel_factory"] == tmp_path / "reel_factory"
    assert roots["contentforge"] == tmp_path / "contentforge"
    assert roots["reference_factory"] == tmp_path / "reference_factory"
    assert roots["ThreadsDashboard"] == tmp_path.parent / "ThreadsDashboard"
