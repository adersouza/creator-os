"""Canonical typed input ordering for local video tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

_EDIT_TASKS: Final = frozenset({"video_retake", "video_extend"})
_IMAGE_TASK_ORDER: Final = ("image", "audio", "last_image", "source_video")
_EDIT_TASK_ORDER: Final = ("source_video", "audio", "last_image")


def canonical_task_input_bindings(
    task_kind: str,
    *,
    image_sha256: str | None = None,
    audio_sha256: str | None = None,
    last_image_sha256: str | None = None,
    source_video_sha256: str | None = None,
) -> tuple[dict[str, str], ...]:
    """Return one role-preserving, deterministic input binding sequence.

    Hash equality alone cannot distinguish an image from audio, a final
    keyframe, or an edit source. Callers must therefore compare these typed
    records first and derive ordered fingerprint lists from this sequence.
    """

    values = {
        "image": image_sha256,
        "audio": audio_sha256,
        "last_image": last_image_sha256,
        "source_video": source_video_sha256,
    }
    if task_kind in _EDIT_TASKS:
        if image_sha256 is not None:
            raise ValueError("task_input_edit_image_forbidden")
        if source_video_sha256 is None:
            raise ValueError("task_input_edit_source_video_required")
        order = _EDIT_TASK_ORDER
    else:
        order = _IMAGE_TASK_ORDER

    bindings: list[dict[str, str]] = []
    seen_fingerprints: set[str] = set()
    for role in order:
        fingerprint = values[role]
        if fingerprint is None:
            continue
        if not _is_sha256(fingerprint):
            raise ValueError(f"task_input_{role}_fingerprint_invalid")
        if fingerprint in seen_fingerprints:
            raise ValueError("task_input_role_fingerprint_collision")
        seen_fingerprints.add(fingerprint)
        bindings.append({"role": role, "sha256": fingerprint})
    return tuple(bindings)


def validate_task_input_binding_records(
    task_kind: str, records: Sequence[Mapping[str, object]]
) -> tuple[dict[str, str], ...]:
    """Rebuild and require the canonical representation of transported records."""

    by_role: dict[str, str] = {}
    for record in records:
        if set(record) != {"role", "sha256"}:
            raise ValueError("task_input_binding_record_invalid")
        role = str(record.get("role") or "")
        value = str(record.get("sha256") or "")
        if role in by_role:
            raise ValueError("task_input_binding_role_duplicate")
        by_role[role] = value
    unexpected = set(by_role).difference(_IMAGE_TASK_ORDER)
    if unexpected:
        raise ValueError("task_input_binding_role_invalid")
    canonical = canonical_task_input_bindings(
        task_kind,
        image_sha256=by_role.get("image"),
        audio_sha256=by_role.get("audio"),
        last_image_sha256=by_role.get("last_image"),
        source_video_sha256=by_role.get("source_video"),
    )
    if [dict(item) for item in records] != list(canonical):
        raise ValueError("task_input_binding_order_invalid")
    return canonical


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
