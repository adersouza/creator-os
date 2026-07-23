from __future__ import annotations

import pytest
from creator_os_core.task_inputs import (
    canonical_task_input_bindings,
    validate_task_input_binding_records,
)


@pytest.mark.parametrize(
    ("task_kind", "kwargs", "expected_roles"),
    [
        ("text_to_video", {}, ()),
        ("image_to_video", {"image_sha256": "a" * 64}, ("image",)),
        (
            "audio_image_to_video",
            {"image_sha256": "a" * 64, "audio_sha256": "b" * 64},
            ("image", "audio"),
        ),
        (
            "keyframe_interpolation",
            {"image_sha256": "a" * 64, "last_image_sha256": "c" * 64},
            ("image", "last_image"),
        ),
        ("video_retake", {"source_video_sha256": "d" * 64}, ("source_video",)),
        ("video_extend", {"source_video_sha256": "d" * 64}, ("source_video",)),
    ],
)
def test_task_input_role_matrix_is_exact(
    task_kind: str, kwargs: dict[str, str], expected_roles: tuple[str, ...]
) -> None:
    bindings = canonical_task_input_bindings(task_kind, **kwargs)

    assert tuple(binding["role"] for binding in bindings) == expected_roles


def test_transported_input_order_and_role_collisions_fail_closed() -> None:
    with pytest.raises(ValueError, match="binding_order_invalid"):
        validate_task_input_binding_records(
            "keyframe_interpolation",
            [
                {"role": "last_image", "sha256": "b" * 64},
                {"role": "image", "sha256": "a" * 64},
            ],
        )

    with pytest.raises(ValueError, match="role_fingerprint_collision"):
        canonical_task_input_bindings(
            "keyframe_interpolation",
            image_sha256="a" * 64,
            last_image_sha256="a" * 64,
        )


@pytest.mark.parametrize("task_kind", ["video_retake", "video_extend"])
@pytest.mark.parametrize(
    "forbidden",
    [
        {"image_sha256": "a" * 64},
        {"audio_sha256": "b" * 64},
        {"last_image_sha256": "c" * 64},
    ],
)
def test_video_edit_rejects_every_unconsumed_media_role(
    task_kind: str, forbidden: dict[str, str]
) -> None:
    with pytest.raises(ValueError, match="role_forbidden"):
        canonical_task_input_bindings(
            task_kind,
            source_video_sha256="d" * 64,
            **forbidden,
        )
