from __future__ import annotations

from pathlib import Path

import pytest
from reel_factory.local_wan import (
    LocalWanRequest,
    build_local_wan_command,
    run_local_wan,
)


def _request(tmp_path: Path, *, duration: int = 6) -> LocalWanRequest:
    image = tmp_path / "still.jpg"
    image.write_bytes(b"source-image")
    return LocalWanRequest(
        image_path=image,
        prompt="Subtle natural breathing and a gentle camera push forward",
        output_path=tmp_path / "out.mp4",
        model_dir=tmp_path / "Wan2.2-TI2V-5B-MLX-Q8",
        duration_seconds=duration,
        seed=17,
        steps=40,
    )


def test_local_wan_adapter_builds_catalog_driven_portrait_command(
    tmp_path: Path,
) -> None:
    command = build_local_wan_command(_request(tmp_path), python_executable="python3")
    assert command[:3] == ["python3", "-m", "mlx_video.models.wan_2.generate"]
    assert command[command.index("--width") + 1] == "704"
    assert command[command.index("--height") + 1] == "1280"
    frames = int(command[command.index("--num-frames") + 1])
    assert frames == 145
    assert (frames - 1) % 4 == 0
    assert command[command.index("--seed") + 1] == "17"


def test_local_wan_adapter_dry_run_never_calls_runner(tmp_path: Path) -> None:
    def fail_runner(*_args, **_kwargs):
        raise AssertionError("runner must not execute during dry-run")

    result = run_local_wan(_request(tmp_path), dry_run=True, runner=fail_runner)
    assert result["status"] == "planned"
    assert result["schema"] == "reel_factory.local_video_generation.v1"
    assert result["providerCalls"] == 0
    assert result["paidGeneration"] is False


def test_local_wan_adapter_rejects_invalid_duration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duration"):
        build_local_wan_command(_request(tmp_path, duration=9))
