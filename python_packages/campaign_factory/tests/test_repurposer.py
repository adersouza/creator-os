from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repurposer.config import RepurposeConfig
from repurposer.engines.audio import AudioEngine
from repurposer.engines.micro import MicroEngine
from repurposer.engines.polish import PolishEngine
from repurposer.engines.visual import VisualEngine
from repurposer.pipeline import RepurposeError, VariantPipeline
from repurposer.qa.similarity import SimilarityGate


def _tiny_mp4(path: Path) -> Path:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=720x1280:d=1",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-y",
        str(path),
    ]
    subprocess.run(cmd, check=True)
    return path


def test_variant_pipeline_rejects_missing_master(tmp_path: Path):
    pipeline = VariantPipeline(
        tmp_path / "missing.mp4",
        target_count=1,
        platform="reels",
        output_dir=tmp_path / "variants",
    )

    with pytest.raises(FileNotFoundError):
        pipeline.generate_batch("ig_subtle")


def test_variant_pipeline_returns_real_existing_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = _tiny_mp4(tmp_path / "master.mp4")

    monkeypatch.setattr(
        RepurposeConfig,
        "from_preset",
        classmethod(
            lambda cls, name: cls(
                target_platform="reels",
                aggressiveness=0.0,
                enable_editorial=False,
                enable_audio=False,
                enable_generative=False,
                enable_polish=False,
                enable_micro=False,
            )
        ),
    )

    pipeline = VariantPipeline(master, target_count=2, platform="reels", output_dir=tmp_path / "variants")

    variants = pipeline.generate_batch("ig_subtle")

    assert len(variants) == 2
    assert all(path.exists() for path in variants)
    assert all(path.parent == tmp_path / "variants" for path in variants)
    assert all(path.name != f"variant_{idx}.mp4" for idx, path in enumerate(variants))
    assert master.read_bytes() == (tmp_path / "master.mp4").read_bytes()


def test_variant_pipeline_fails_without_partial_fake_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = _tiny_mp4(tmp_path / "master.mp4")

    monkeypatch.setattr(
        RepurposeConfig,
        "from_preset",
        classmethod(
            lambda cls, name: cls(
                target_platform="reels",
                aggressiveness=0.0,
                enable_editorial=True,
                enable_audio=False,
                enable_generative=False,
                enable_polish=False,
                enable_micro=False,
            )
        ),
    )

    def fail_editorial(*args, **kwargs):
        raise RuntimeError("editorial failed")

    monkeypatch.setattr("repurposer.pipeline.EditorialEngine.apply", fail_editorial)

    pipeline = VariantPipeline(master, target_count=1, platform="reels", output_dir=tmp_path / "variants")

    with pytest.raises(RepurposeError, match="editorial failed"):
        pipeline.generate_batch("ig_subtle")

    assert not list((tmp_path / "variants").glob("*.mp4"))


def test_ffmpeg_engines_raise_when_command_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not real media")
    track = tmp_path / "track.mp3"
    track.write_bytes(b"not real audio")

    def failed_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="ffmpeg exploded")

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        PolishEngine.apply(source, tmp_path / "polish.mp4")
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        MicroEngine.apply(source, tmp_path / "micro.mp4")
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        AudioEngine.apply(source, tmp_path / "audio.mp4", music_track=track)


def test_visual_engine_fails_cleanly_when_video_to_video_is_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    monkeypatch.setattr("repurposer.engines.visual.AssetGenerationPlan", None)

    with pytest.raises(RuntimeError, match="video-to-video generation is unavailable"):
        VisualEngine.apply(source, tmp_path / "visual.mp4", prompt="make a safe visual variant")


def test_similarity_gate_extracts_keyframes_and_compares_phash(tmp_path: Path):
    master = _tiny_mp4(tmp_path / "master.mp4")
    variant = _tiny_mp4(tmp_path / "variant.mp4")

    frames = SimilarityGate.extract_keyframes(master, count=2)
    assert len(frames) == 2

    assert SimilarityGate.calculate_phash_distance(master, variant) >= 0
    assert SimilarityGate.calculate_ssim(master, variant) <= 1.0
