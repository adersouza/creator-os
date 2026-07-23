from __future__ import annotations

import os
from pathlib import Path

import pytest
from creator_os_core.runtime_paths import resolve_component_roots, resolve_runtime_paths


def _make_linked_worktree(
    tmp_path: Path,
    *,
    relative_pointer: bool = False,
) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "Developer"
    primary = workspace / "creator-os"
    common_git = primary / ".git"
    linked = tmp_path / "isolated" / "creator-os-feature"
    gitdir = common_git / "worktrees" / linked.name
    gitdir.mkdir(parents=True)
    linked.mkdir(parents=True)

    pointer = os.path.relpath(gitdir, linked) if relative_pointer else os.fspath(gitdir)
    (linked / ".git").write_text(f"gitdir: {pointer}\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    (gitdir / "gitdir").write_text(
        f"{linked / '.git'}\n",
        encoding="utf-8",
    )
    return primary, linked, gitdir


def test_runtime_paths_derive_canonical_monorepo_layout(tmp_path: Path) -> None:
    source = tmp_path / "creator-os"
    paths = resolve_runtime_paths(source, env={})

    assert paths.source_root == source
    assert paths.workspace_root == tmp_path
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
    threadsdash_override = tmp_path / "dashboard"
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
            "THREADSDASH_ROOT": str(threadsdash_override),
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
    assert paths.threadsdash_root == threadsdash_override
    assert paths.campaign_factory_db == tmp_path / "campaign.sqlite"
    assert paths.reference_factory_db == tmp_path / "reference.sqlite"
    assert paths.reel_manifest_db == tmp_path / "manifest.sqlite"
    assert paths.reel_render_queue_db == tmp_path / "queue.sqlite"


def test_runtime_paths_primary_checkout_uses_its_parent_workspace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Developer" / "creator-os"
    (source / ".git").mkdir(parents=True)

    paths = resolve_runtime_paths(source, env={"HOME": str(tmp_path / "home")})

    assert paths.source_root == source
    assert paths.workspace_root == source.parent
    assert paths.runtime_root == source.parent / "creator-os-runtime"
    assert paths.threadsdash_root == source.parent / "ThreadsDashboard"


@pytest.mark.parametrize("relative_pointer", [False, True])
def test_runtime_paths_linked_worktree_uses_primary_checkout_workspace(
    tmp_path: Path,
    relative_pointer: bool,
) -> None:
    primary, linked, _gitdir = _make_linked_worktree(
        tmp_path,
        relative_pointer=relative_pointer,
    )

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.source_root == linked
    assert paths.workspace_root == primary.parent
    assert paths.runtime_root == primary.parent / "creator-os-runtime"
    assert paths.threadsdash_root == primary.parent / "ThreadsDashboard"


def test_runtime_paths_linked_worktree_honors_explicit_sibling_overrides(
    tmp_path: Path,
) -> None:
    primary, linked, _gitdir = _make_linked_worktree(tmp_path)
    runtime_override = tmp_path / "explicit-runtime"
    threadsdash_override = tmp_path / "explicit-dashboard"

    paths = resolve_runtime_paths(
        linked,
        env={
            "HOME": str(tmp_path / "home"),
            "CREATOR_OS_RUNTIME_ROOT": str(runtime_override),
            "THREADSDASH_ROOT": str(threadsdash_override),
        },
    )

    assert paths.workspace_root == primary.parent
    assert paths.runtime_root == runtime_override
    assert paths.threadsdash_root == threadsdash_override


def test_runtime_paths_malformed_gitdir_pointer_falls_back(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "isolated" / "creator-os-feature"
    linked.mkdir(parents=True)
    (linked / ".git").write_text(
        "gitdir: ../../Developer/creator-os/.git/worktrees/feature\nextra\n",
        encoding="utf-8",
    )

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.workspace_root == linked.parent
    assert paths.runtime_root == linked.parent / "creator-os-runtime"
    assert paths.threadsdash_root == linked.parent / "ThreadsDashboard"


def test_runtime_paths_symlinked_git_pointer_falls_back(tmp_path: Path) -> None:
    linked = tmp_path / "isolated" / "creator-os-feature"
    linked.mkdir(parents=True)
    pointer_file = tmp_path / "git-pointer"
    pointer_file.write_text(
        "gitdir: /tmp/creator-os/.git/worktrees/feature\n",
        encoding="utf-8",
    )
    (linked / ".git").symlink_to(pointer_file)

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.workspace_root == linked.parent


def test_runtime_paths_symlinked_gitdir_component_falls_back(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "Developer"
    primary = workspace / "creator-os"
    worktrees = primary / ".git" / "worktrees"
    real_gitdir = tmp_path / "gitdirs" / "creator-os-feature"
    linked = tmp_path / "isolated" / "creator-os-feature"
    real_gitdir.mkdir(parents=True)
    worktrees.mkdir(parents=True)
    linked.mkdir(parents=True)
    gitdir = worktrees / linked.name
    gitdir.symlink_to(real_gitdir, target_is_directory=True)
    (linked / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (real_gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    (real_gitdir / "gitdir").write_text(f"{linked / '.git'}\n", encoding="utf-8")

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.workspace_root == linked.parent


def test_runtime_paths_mismatched_worktree_backlink_falls_back(
    tmp_path: Path,
) -> None:
    _primary, linked, gitdir = _make_linked_worktree(tmp_path)
    (gitdir / "gitdir").write_text(
        f"{tmp_path / 'different' / '.git'}\n",
        encoding="utf-8",
    )

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.workspace_root == linked.parent


def test_runtime_paths_mismatched_commondir_falls_back(tmp_path: Path) -> None:
    _primary, linked, gitdir = _make_linked_worktree(tmp_path)
    (gitdir / "commondir").write_text(
        f"{tmp_path / 'different' / '.git'}\n",
        encoding="utf-8",
    )

    paths = resolve_runtime_paths(linked, env={"HOME": str(tmp_path / "home")})

    assert paths.workspace_root == linked.parent


def test_component_roots_support_flat_test_fixtures(tmp_path: Path) -> None:
    for name in ("reel_factory", "contentforge", "reference_factory"):
        (tmp_path / name).mkdir()

    roots = resolve_component_roots(tmp_path, env={})

    assert roots["reel_factory"] == tmp_path / "reel_factory"
    assert roots["contentforge"] == tmp_path / "contentforge"
    assert roots["reference_factory"] == tmp_path / "reference_factory"
    assert roots["ThreadsDashboard"] == tmp_path.parent / "ThreadsDashboard"
