"""Canonical path resolution for Creator OS source, runtime, and sibling repos."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_MAX_GIT_POINTER_BYTES = 4096


@dataclass(frozen=True)
class RuntimePaths:
    source_root: Path
    workspace_root: Path
    runtime_root: Path
    config_root: Path
    state_root: Path
    artifact_root: Path
    model_root: Path
    log_root: Path
    campaign_factory_root: Path
    reel_factory_root: Path
    reference_factory_root: Path
    contentforge_root: Path
    threadsdash_root: Path
    reference_data_root: Path
    campaign_factory_db: Path
    reference_factory_db: Path
    reel_manifest_db: Path
    reel_render_queue_db: Path


def _read_small_regular_file(path: Path) -> str | None:
    """Read a bounded non-symlink file without following its final component."""

    try:
        path_stat = os.lstat(path)
    except OSError:
        return None
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or path_stat.st_size > _MAX_GIT_POINTER_BYTES
    ):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode) or (
            opened_stat.st_dev,
            opened_stat.st_ino,
        ) != (path_stat.st_dev, path_stat.st_ino):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(_MAX_GIT_POINTER_BYTES + 1)
    except OSError:
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if len(raw) > _MAX_GIT_POINTER_BYTES:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _single_pointer_value(text: str, *, prefix: str = "") -> str | None:
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].startswith(prefix):
        return None
    value = lines[0][len(prefix) :]
    if not value or value != value.strip() or "\x00" in value:
        return None
    return value


def _absolute_pointer_target(value: str, *, relative_to: Path) -> Path:
    selected = Path(value)
    if not selected.is_absolute():
        selected = relative_to / selected
    return Path(os.path.abspath(os.fspath(selected)))


def _is_plain_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except OSError:
            return True
    return False


def _linked_worktree_workspace(source: Path) -> Path | None:
    """Return the primary checkout's workspace for one safe linked worktree."""

    dot_git = source / ".git"
    pointer_text = _read_small_regular_file(dot_git)
    if pointer_text is None:
        return None
    pointer = _single_pointer_value(pointer_text, prefix="gitdir: ")
    if pointer is None:
        return None
    gitdir = _absolute_pointer_target(pointer, relative_to=source)
    common_git = gitdir.parent.parent
    primary_checkout = common_git.parent
    if (
        gitdir.parent.name != "worktrees"
        or common_git.name != ".git"
        or _has_symlink_component(gitdir)
        or not _is_plain_directory(gitdir)
        or not _is_plain_directory(common_git)
        or not _is_plain_directory(primary_checkout)
    ):
        return None

    commondir_text = _read_small_regular_file(gitdir / "commondir")
    if commondir_text is None:
        return None
    commondir = _single_pointer_value(commondir_text)
    if commondir is None:
        return None
    if _absolute_pointer_target(commondir, relative_to=gitdir) != common_git:
        return None

    # Git maintains a reciprocal pointer from the per-worktree gitdir back to
    # the worktree's .git file. Requiring it prevents an arbitrary lookalike
    # path from selecting a different workspace.
    backlink_text = _read_small_regular_file(gitdir / "gitdir")
    if backlink_text is None:
        return None
    backlink = _single_pointer_value(backlink_text)
    if backlink is None:
        return None
    backlink_target = _absolute_pointer_target(backlink, relative_to=gitdir)
    if backlink_target != Path(os.path.abspath(os.fspath(dot_git))):
        return None
    return primary_checkout.parent


def _workspace_root(source: Path) -> Path:
    return _linked_worktree_workspace(source) or source.parent


def resolve_runtime_paths(
    source_root: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> RuntimePaths:
    """Resolve the active monorepo layout without assuming a personal home path."""
    values = os.environ if env is None else env
    inferred_source = Path(__file__).resolve().parents[3]
    source = (
        Path(values.get("CREATOR_OS_ROOT") or source_root or inferred_source)
        .expanduser()
        .resolve()
    )
    workspace = _workspace_root(source)
    runtime = (
        Path(values.get("CREATOR_OS_RUNTIME_ROOT") or workspace / "creator-os-runtime")
        .expanduser()
        .resolve()
    )
    home = Path(values.get("HOME") or Path.home()).expanduser().resolve()
    config_root = home / ".creator-os"
    state_root = (
        Path(values.get("CREATOR_OS_STATE_ROOT") or config_root / "state")
        .expanduser()
        .resolve()
    )
    artifact_root = (
        Path(values.get("CREATOR_OS_ARTIFACT_ROOT") or config_root / "artifacts")
        .expanduser()
        .resolve()
    )
    model_root = (
        Path(values.get("CREATOR_OS_MODEL_ROOT") or config_root / "models")
        .expanduser()
        .resolve()
    )
    log_root = (
        Path(values.get("CREATOR_OS_LOG_ROOT") or config_root / "logs")
        .expanduser()
        .resolve()
    )
    reference_data = (
        Path(
            values.get("REFERENCE_FACTORY_DATA_ROOT")
            or artifact_root / "reference_factory"
        )
        .expanduser()
        .resolve()
    )
    return RuntimePaths(
        source_root=source,
        workspace_root=workspace,
        runtime_root=runtime,
        config_root=config_root,
        state_root=state_root,
        artifact_root=artifact_root,
        model_root=model_root,
        log_root=log_root,
        campaign_factory_root=Path(
            values.get("CAMPAIGN_FACTORY_ROOT")
            or source / "python_packages/campaign_factory"
        )
        .expanduser()
        .resolve(),
        reel_factory_root=Path(
            values.get("REEL_FACTORY_ROOT") or source / "python_packages/reel_factory"
        )
        .expanduser()
        .resolve(),
        reference_factory_root=Path(
            values.get("REFERENCE_FACTORY_ROOT")
            or source / "python_packages/reference_factory"
        )
        .expanduser()
        .resolve(),
        contentforge_root=Path(
            values.get("CONTENTFORGE_ROOT") or source / "packages/contentforge"
        )
        .expanduser()
        .resolve(),
        threadsdash_root=Path(
            values.get("THREADSDASH_ROOT") or workspace / "ThreadsDashboard"
        )
        .expanduser()
        .resolve(),
        reference_data_root=reference_data,
        campaign_factory_db=Path(
            values.get("CAMPAIGN_FACTORY_DB")
            or state_root / "campaign_factory" / "campaign_factory.sqlite"
        )
        .expanduser()
        .resolve(),
        reference_factory_db=Path(
            values.get("REFERENCE_FACTORY_DB")
            or state_root / "reference_factory" / "reference_factory.sqlite"
        )
        .expanduser()
        .resolve(),
        reel_manifest_db=Path(
            values.get("REEL_FACTORY_MANIFEST_DB")
            or state_root / "reel_factory" / "manifest.sqlite"
        )
        .expanduser()
        .resolve(),
        reel_render_queue_db=Path(
            values.get("REEL_FACTORY_RENDER_QUEUE_DB")
            or state_root / "reel_factory" / "render_queue.sqlite"
        )
        .expanduser()
        .resolve(),
    )


def resolve_component_roots(
    projects_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Resolve canonical or flat fixture layouts for cross-component smoke tests."""
    values = os.environ if env is None else env
    root = Path(projects_root).expanduser().resolve()
    if (root / "creator-os").is_dir():
        creator_os = root / "creator-os"
    elif root.name == "python_packages":
        creator_os = root.parent
    else:
        creator_os = root

    def pick(env_var: str, candidates: list[Path]) -> Path:
        if value := values.get(env_var):
            return Path(value).expanduser().resolve()
        return next((path for path in candidates if path.is_dir()), candidates[-1])

    return {
        "reel_factory": pick(
            "REEL_FACTORY_ROOT",
            [root / "reel_factory", creator_os / "python_packages/reel_factory"],
        ),
        "contentforge": pick(
            "CONTENTFORGE_ROOT",
            [root / "contentforge", creator_os / "packages/contentforge"],
        ),
        "reference_factory": pick(
            "REFERENCE_FACTORY_ROOT",
            [
                root / "reference_factory",
                creator_os / "python_packages/reference_factory",
            ],
        ),
        "ThreadsDashboard": pick(
            "THREADSDASH_ROOT",
            [root / "ThreadsDashboard", creator_os.parent / "ThreadsDashboard"],
        ),
    }
