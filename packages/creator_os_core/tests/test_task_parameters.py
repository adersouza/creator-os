from __future__ import annotations

from copy import deepcopy

import pytest
from creator_os_core.task_parameters import (
    benchmark_task_parameter_fingerprint,
    canonical_task_parameter_material,
    task_parameter_fingerprint,
)


def _material(**overrides):
    values = {
        "task_kind": "image_to_video",
        "prompt": "  A creator turns toward the camera naturally  ",
        "negative_prompt": " blurry,  text ",
        "negative_prompt_applied": True,
        "seed": 42,
        "duration_seconds": 6,
        "resolution": "720p",
        "geometry_source": "model",
        "geometry_probe": None,
        "width": 704,
        "height": 1280,
        "fps": "24/1",
        "frame_count": 145,
        "steps": 40,
        "requested_steps": None,
        "audio_mode": "none",
        "pipeline": "wan22_ti2v",
        "guide_scale": "5.0",
        "scheduler": "unipc",
        "tiling_mode": "auto",
        "trim_first_frames": 0,
        "retake_start_frame": None,
        "retake_end_frame": None,
        "extend_frames": None,
        "extend_direction": None,
        "low_ram": True,
        "tile_frames": 1,
        "tile_spatial": 2,
        "lora_sha256": None,
        "lora_scale": None,
        "commercial_use": True,
        "commercial_annual_revenue_usd": 1_000,
        "overlays_exist": False,
        "preserve_audio": False,
    }
    values.update(overrides)
    return canonical_task_parameter_material(**values)


def test_parameter_material_normalizes_and_separates_benchmark_from_execution() -> None:
    first = _material()
    second = _material(
        width=576,
        height=1024,
        fps="24/1",
        frame_count=145,
        steps=15,
        pipeline="ltx23_dev",
        guide_scale=None,
        scheduler=None,
        tiling_mode=None,
        negative_prompt=None,
        negative_prompt_applied=False,
    )

    assert first["benchmarkCell"]["prompt"] == (
        "A creator turns toward the camera naturally"
    )
    assert benchmark_task_parameter_fingerprint(first) == (
        benchmark_task_parameter_fingerprint(second)
    )
    assert task_parameter_fingerprint(first) != task_parameter_fingerprint(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "A creator smiles and walks toward the camera"),
        ("seed", 43),
        ("duration_seconds", 8),
        ("resolution", "1080p"),
        ("requested_steps", 30),
        ("audio_mode", "generated"),
    ],
)
def test_every_requested_inference_setting_changes_benchmark_identity(
    field: str, value
) -> None:
    baseline = _material()
    changed = _material(**{field: value})

    assert benchmark_task_parameter_fingerprint(changed) != (
        benchmark_task_parameter_fingerprint(baseline)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("low_ram", False),
        ("tile_frames", 2),
        ("tile_spatial", 3),
        ("lora_sha256", "a" * 64),
    ],
)
def test_model_specific_controls_change_execution_not_benchmark_identity(
    field: str, value
) -> None:
    overrides = {field: value}
    if field == "lora_sha256":
        overrides["lora_scale"] = 0.75
    baseline = _material()
    changed = _material(**overrides)

    assert benchmark_task_parameter_fingerprint(changed) == (
        benchmark_task_parameter_fingerprint(baseline)
    )
    assert task_parameter_fingerprint(changed) != task_parameter_fingerprint(baseline)


def test_policy_context_changes_full_identity_not_benchmark_cell() -> None:
    baseline = _material()
    changed = deepcopy(baseline)
    changed["policyContext"]["overlaysExist"] = True

    assert benchmark_task_parameter_fingerprint(changed) == (
        benchmark_task_parameter_fingerprint(baseline)
    )
    assert task_parameter_fingerprint(changed) != task_parameter_fingerprint(baseline)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        (
            {"pipeline": "wan22_i2v", "frame_count": 80},
            "task_parameter_wan_frame_geometry_invalid",
        ),
        (
            {"pipeline": "wan22_i2v", "trim_first_frames": 1},
            "task_parameter_wan_i2v_trim_unsupported",
        ),
    ],
)
def test_wan_i2v_rejects_shape_mismatched_execution_material(
    overrides: dict[str, object], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        _material(**overrides)
