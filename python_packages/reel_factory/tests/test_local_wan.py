from __future__ import annotations

import json
from pathlib import Path

import pytest
from reel_factory.local_wan import (
    LocalWanRequest,
    build_local_wan_command,
    probe_local_wan,
    run_local_wan,
)


def _request(tmp_path: Path, *, duration: int = 6) -> LocalWanRequest:
    image = tmp_path / "still.jpg"
    image.write_bytes(b"source-image")
    model = tmp_path / "Wan2.2-TI2V-5B-MLX"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps({"model": "Wan2.2-TI2V-5B"}), encoding="utf-8"
    )
    return LocalWanRequest(
        image_path=image,
        prompt="Subtle natural breathing and a gentle camera push forward",
        output_path=tmp_path / "out.mp4",
        model_dir=model,
        duration_seconds=duration,
        seed=17,
        steps=40,
    )


def test_local_wan_command_is_portrait_deterministic_and_vae_aligned(
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


def test_local_wan_dry_run_never_calls_provider_or_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "reel_factory.local_wan.probe_local_wan",
        lambda **_: {"ready": False, "issues": ["model_missing"]},
    )

    def fail_runner(*_args, **_kwargs):
        raise AssertionError("runner must not execute during dry-run")

    result = run_local_wan(_request(tmp_path), dry_run=True, runner=fail_runner)
    assert result["status"] == "planned"
    assert result["providerCalls"] == 0
    assert result["paidGeneration"] is False
    assert not (tmp_path / "out.mp4").exists()


def test_local_wan_rejects_invalid_duration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duration"):
        build_local_wan_command(_request(tmp_path, duration=9))


def test_capability_probe_requires_every_converted_weight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr("reel_factory.local_wan.shutil.which", lambda _name: None)
    result = probe_local_wan(
        model_dir=request.model_dir, python_executable="/missing/python"
    )
    assert result["ready"] is False
    assert "converted_model_file_missing:model.safetensors" in result["issues"]
    assert "converted_model_file_missing:t5_encoder.safetensors" in result["issues"]
    assert "converted_model_file_missing:vae.safetensors" in result["issues"]


def test_local_apply_is_offline_atomic_and_preserves_completed_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_wan.probe_local_wan",
        lambda **_: {"ready": True, "issues": []},
    )
    monkeypatch.setattr(
        "reel_factory.local_wan._validate_video", lambda *_a, **_k: None
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def runner(command, **kwargs):
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        partial = Path(command[command.index("--output-path") + 1])
        assert partial.name.endswith(".partial.mp4")
        partial.write_bytes(b"generated-video")
        return Completed()

    result = run_local_wan(request, dry_run=False, runner=runner)
    assert request.output_path.read_bytes() == b"generated-video"
    assert result["status"] == "completed"
    assert result["partialOutputPath"] is None
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_wan.json").read_text(
            encoding="utf-8"
        )
    )
    assert lineage["status"] == "completed"


def test_local_interruption_keeps_honest_recoverable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_wan.probe_local_wan",
        lambda **_: {"ready": True, "issues": []},
    )

    def interrupted(_command, **_kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_local_wan(request, dry_run=False, runner=interrupted)
    assert not request.output_path.exists()
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_wan.json").read_text(
            encoding="utf-8"
        )
    )
    assert lineage["status"] == "interrupted"
    assert lineage["failure"] == "KeyboardInterrupt"
