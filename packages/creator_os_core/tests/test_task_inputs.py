from __future__ import annotations

import pytest
from creator_os_core.task_inputs import (
    canonical_task_input_bindings,
    validate_task_input_binding_records,
)


def test_video_edit_inputs_are_source_first_and_role_preserving() -> None:
    bindings = canonical_task_input_bindings(
        "video_retake",
        source_video_sha256="a" * 64,
        audio_sha256="b" * 64,
        last_image_sha256="c" * 64,
    )

    assert bindings == (
        {"role": "source_video", "sha256": "a" * 64},
        {"role": "audio", "sha256": "b" * 64},
        {"role": "last_image", "sha256": "c" * 64},
    )


def test_transported_input_order_and_role_collisions_fail_closed() -> None:
    with pytest.raises(ValueError, match="binding_order_invalid"):
        validate_task_input_binding_records(
            "video_extend",
            [
                {"role": "audio", "sha256": "b" * 64},
                {"role": "source_video", "sha256": "a" * 64},
            ],
        )

    with pytest.raises(ValueError, match="role_fingerprint_collision"):
        canonical_task_input_bindings(
            "image_to_video",
            image_sha256="a" * 64,
            audio_sha256="a" * 64,
        )
