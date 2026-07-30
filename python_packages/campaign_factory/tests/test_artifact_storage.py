from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory import artifact_storage


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_root_keyed_path_rebinds_to_a_new_managed_root(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    old_path = old_root / "creator" / "campaign" / "asset.mp4"
    binding = artifact_storage.root_keyed_path(old_path, {"campaigns": old_root})
    assert binding == {
        "rootKey": "campaigns",
        "relativePath": "creator/campaign/asset.mp4",
    }

    new_root = tmp_path / "new"
    assert (
        artifact_storage.resolve_root_keyed_path(binding, {"campaigns": new_root})
        == new_root / "creator" / "campaign" / "asset.mp4"
    )


def test_root_binding_rejects_traversal_symlinks_and_external_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked"
    link.symlink_to(outside, target_is_directory=True)

    assert artifact_storage.root_keyed_path(outside / "x.mp4", {"root": root}) is None
    assert artifact_storage.root_keyed_path(link / "x.mp4", {"root": root}) is None
    with pytest.raises(ValueError, match="invalid_root_keyed_path"):
        artifact_storage.resolve_root_keyed_path(
            {"rootKey": "root", "relativePath": "../outside/x.mp4"},
            {"root": root},
        )
    with pytest.raises(ValueError, match="symlink"):
        artifact_storage.resolve_root_keyed_path(
            {"rootKey": "root", "relativePath": "linked/x.mp4"}, {"root": root}
        )


def test_atomic_copy_is_idempotent_and_rejects_collisions(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "managed" / "artifact.bin"
    source.write_bytes(b"exact")
    artifact_storage.atomic_copy(
        source, destination, expected_sha256=_sha(b"exact"), min_free_bytes=0
    )
    artifact_storage.atomic_copy(
        source, destination, expected_sha256=_sha(b"exact"), min_free_bytes=0
    )
    destination.write_bytes(b"collision")
    with pytest.raises(FileExistsError, match="collision"):
        artifact_storage.atomic_copy(
            source, destination, expected_sha256=_sha(b"exact"), min_free_bytes=0
        )


def test_atomic_copy_cleans_partial_file_after_sha_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "managed" / "artifact.bin"
    source.write_bytes(b"actual")
    with pytest.raises(OSError, match="SHA mismatch"):
        artifact_storage.atomic_copy(
            source, destination, expected_sha256=_sha(b"expected"), min_free_bytes=0
        )
    assert not destination.exists()
    assert not list(destination.parent.glob(".*.tmp"))


def test_atomic_copy_rejects_symlinked_source(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    link = tmp_path / "source-link.bin"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="non_symlink"):
        artifact_storage.atomic_copy(
            link,
            tmp_path / "managed" / "artifact.bin",
            expected_sha256=_sha(b"source"),
            min_free_bytes=0,
        )


def test_storage_guard_enforces_free_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        artifact_storage.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=100),
    )
    with pytest.raises(
        artifact_storage.StorageCapacityError, match="minimum_free_space"
    ):
        artifact_storage.ensure_storage_capacity(
            tmp_path / "artifact.bin", 60, min_free_bytes=50
        )


def test_storage_guard_enforces_managed_root_quota(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    (root / "existing.bin").write_bytes(b"1234")
    with pytest.raises(artifact_storage.StorageCapacityError, match="quota_exceeded"):
        artifact_storage.ensure_storage_capacity(
            root / "artifact.bin",
            3,
            storage_root=root,
            quota_bytes=6,
            min_free_bytes=0,
        )


def test_storage_guard_uses_fail_closed_environment_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_ARTIFACT_QUOTA_BYTES", "0")
    with pytest.raises(artifact_storage.StorageCapacityError, match="quota_exceeded"):
        artifact_storage.ensure_storage_capacity(
            tmp_path / "artifact.bin", 1, min_free_bytes=0
        )
    monkeypatch.setenv("CREATOR_OS_ARTIFACT_QUOTA_BYTES", "invalid")
    with pytest.raises(ValueError, match="nonnegative integer"):
        artifact_storage.ensure_storage_capacity(
            tmp_path / "artifact.bin", 1, min_free_bytes=0
        )


def test_storage_guard_rejects_destination_outside_declared_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="outside_storage_root"):
        artifact_storage.ensure_storage_capacity(
            tmp_path / "outside" / "artifact.bin",
            1,
            storage_root=tmp_path / "managed",
            min_free_bytes=0,
        )
