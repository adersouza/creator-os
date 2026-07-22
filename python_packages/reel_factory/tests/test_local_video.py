from __future__ import annotations

import json
from pathlib import Path

import pytest
from reel_factory.local_video import (
    LocalVideoRequest,
    build_local_video_command,
    run_local_video,
)


def _image(tmp_path: Path, name: str = "still.jpg") -> Path:
    path = tmp_path / name
    path.write_bytes(f"image:{name}".encode())
    return path


def _request(
    tmp_path: Path,
    *,
    model_id: str = "local_wan22_ti2v_5b_mlx",
    audio_mode: str = "none",
    audio_path: Path | None = None,
    last_image_path: Path | None = None,
) -> LocalVideoRequest:
    return LocalVideoRequest(
        model_id=model_id,
        image_path=_image(tmp_path),
        prompt="Subtle natural movement with a steady portrait camera composition",
        output_path=tmp_path / "out.mp4",
        duration_seconds=6,
        seed=71,
        audio_mode=audio_mode,  # type: ignore[arg-type]
        audio_path=audio_path,
        last_image_path=last_image_path,
    )


def test_wan_quality_command_uses_q4_dual_model_profile(tmp_path: Path) -> None:
    request = _request(tmp_path, model_id="local_wan22_i2v_a14b_q4_mlx")
    command = build_local_video_command(request, python_executable="python3")
    assert command[command.index("--model-dir") + 1].endswith("/q4")
    assert command[command.index("--guide-scale") + 1] == "3.5,3.5"
    assert command[command.index("--tiling") + 1] == "aggressive"
    assert command[command.index("--steps") + 1] == "20"
    assert command[command.index("--trim-first-frames") + 1] == "1"


def test_ltx_distilled_supports_source_audio_and_first_last_frame(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    last = _image(tmp_path, "last.jpg")
    request = _request(
        tmp_path,
        model_id="local_ltx23_distilled_mlx",
        audio_mode="source",
        audio_path=audio,
        last_image_path=last,
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[:3] == ["python3", "-m", "mlx_video.models.ltx_2.generate"]
    assert command[command.index("--pipeline") + 1] == "distilled"
    assert command[command.index("--width") + 1] == "576"
    assert command[command.index("--height") + 1] == "1024"
    assert command[command.index("--steps") + 1] == "8"
    assert command[command.index("--audio-file") + 1] == str(audio.resolve())
    assert command[command.index("--end-image") + 1] == str(last.resolve())
    frames = int(command[command.index("--num-frames") + 1])
    assert frames == 145
    assert (frames - 1) % 8 == 0


def test_ltx_hq_generated_audio_is_explicit(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        model_id="local_ltx23_dev_hq_mlx",
        audio_mode="generated",
    )
    command = build_local_video_command(request, python_executable="python3")
    assert command[command.index("--pipeline") + 1] == "dev-two-stage-hq"
    assert command[command.index("--steps") + 1] == "15"
    assert "--audio" in command
    assert "--audio-file" not in command
    assert "--apg" in command


def test_wan_fails_closed_when_audio_is_requested(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    request = _request(tmp_path, audio_mode="source", audio_path=audio)
    with pytest.raises(
        ValueError, match="does not accept audio|does not support audio"
    ):
        build_local_video_command(request, python_executable="python3")


def test_dry_run_records_exact_inputs_without_runner_or_provider_call(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, model_id="local_ltx23_distilled_mlx")

    def fail_runner(*_args, **_kwargs):
        raise AssertionError("dry-run must not execute")

    result = run_local_video(request, dry_run=True, runner=fail_runner)
    assert result["status"] == "planned"
    assert result["input"]["sha256"]
    assert result["providerCalls"] == 0
    assert result["paidGeneration"] is False
    assert result["audio"]["nativePlatformAudio"] is False
    assert result["schedulingAllowed"] is False
    assert result["publishingAllowed"] is False


def test_apply_is_offline_atomic_and_preserves_audio_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"source-audio")
    request = _request(
        tmp_path,
        model_id="local_ltx23_distilled_mlx",
        audio_mode="source",
        audio_path=audio,
    )
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {
            "ready": True,
            "issues": [],
            "model": {"manifest": {"modelId": request.model_id}},
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_video._validate_video",
        lambda *_a, **_k: {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]
        },
    )

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def runner(command, **kwargs):
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        video = Path(command[command.index("--output-path") + 1])
        wav = Path(command[command.index("--output-audio") + 1])
        assert video.name.endswith(".partial.mp4")
        video.write_bytes(b"generated-video")
        wav.write_bytes(b"preserved-audio")
        return Completed()

    result = run_local_video(request, dry_run=False, runner=runner)
    assert request.output_path.read_bytes() == b"generated-video"
    assert result["status"] == "completed"
    assert result["audio"]["mode"] == "source"
    assert result["audio"]["nativePlatformAudio"] is False
    assert result["audio"]["sidecarSha256"]
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_video.json").read_text()
    )
    assert lineage["status"] == "completed"


def test_interruption_keeps_honest_recoverable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_video.probe_local_video",
        lambda *_a, **_k: {"ready": True, "issues": [], "model": {}},
    )

    def interrupted(_command, **_kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_local_video(request, dry_run=False, runner=interrupted)
    assert not request.output_path.exists()
    lineage = json.loads(
        request.output_path.with_suffix(".mp4.local_video.json").read_text()
    )
    assert lineage["status"] == "interrupted"
    assert lineage["failure"] == "KeyboardInterrupt"
