from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from repurposer.config import RepurposeConfig
from repurposer.engines.audio import AudioEngine
from repurposer.engines.editorial import EditorialEngine
from repurposer.engines.micro import MicroEngine
from repurposer.engines.polish import PolishEngine
from repurposer.engines.visual import VisualEngine
from repurposer.pipeline import RepurposeError, VariantPipeline
from repurposer.qa.quality import QualityGate
from repurposer.qa.similarity import SimilarityGate

from pipeline_contracts import validate_variant_assignment


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


def test_variant_pipeline_returns_real_existing_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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

    pipeline = VariantPipeline(
        master, target_count=2, platform="reels", output_dir=tmp_path / "variants"
    )

    variants = pipeline.generate_batch("ig_subtle")

    assert len(variants) == 2
    assert all(path.exists() for path in variants)
    assert all(path.parent == tmp_path / "variants" for path in variants)
    assert all(path.name != f"variant_{idx}.mp4" for idx, path in enumerate(variants))
    assert master.read_bytes() == (tmp_path / "master.mp4").read_bytes()


def test_repurpose_presets_keep_micro_off_by_default():
    assert RepurposeConfig.from_preset("ig_subtle").enable_micro is False
    assert RepurposeConfig.from_preset("tiktok_aggressive").enable_micro is False
    assert RepurposeConfig.from_preset("custom").enable_micro is False


def test_ig_subtle_preset_uses_audio_layer_for_account_distinctness():
    preset = RepurposeConfig.from_preset("ig_subtle")
    assert preset.enable_audio is True
    assert preset.require_audio_change is True


def test_editorial_engine_makes_real_quality_passing_transform(tmp_path: Path):
    master = _tiny_mp4(tmp_path / "master.mp4")

    output = EditorialEngine.apply(master, tmp_path / "editorial.mp4", index=2)

    assert output.exists()
    assert output.read_bytes() != master.read_bytes()
    assert QualityGate.is_quality_acceptable(output)


def test_quality_gate_rejects_short_wide_video(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        QualityGate,
        "get_video_info",
        staticmethod(
            lambda path: {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1080,
                        "height": 404,
                    }
                ]
            }
        ),
    )

    assert QualityGate.is_quality_acceptable(Path("short-wide.mp4")) is False


def test_quality_gate_accepts_minimum_dimension_floor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        QualityGate,
        "get_video_info",
        staticmethod(
            lambda path: {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 720,
                        "height": 720,
                    }
                ]
            }
        ),
    )

    assert QualityGate.is_quality_acceptable(Path("square-720.mp4")) is True


def test_variant_pipeline_fails_without_partial_fake_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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

    pipeline = VariantPipeline(
        master, target_count=1, platform="reels", output_dir=tmp_path / "variants"
    )

    with pytest.raises(RepurposeError, match="editorial failed"):
        pipeline.generate_batch("ig_subtle")

    assert not list((tmp_path / "variants").glob("*.mp4"))


def test_ffmpeg_engines_raise_when_command_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not real media")
    track = tmp_path / "track.mp3"
    track.write_bytes(b"not real audio")

    def failed_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="ffmpeg exploded"
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        PolishEngine.apply(source, tmp_path / "polish.mp4")
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        MicroEngine.apply(source, tmp_path / "micro.mp4")
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        AudioEngine.apply(source, tmp_path / "audio.mp4", music_track=track)


def test_audio_engine_selects_account_specific_catalog_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    first_track = tmp_path / "first.m4a"
    second_track = tmp_path / "second.m4a"
    first_track.write_bytes(b"first")
    second_track.write_bytes(b"second")
    selected: list[Path] = []

    def fake_helpers():
        def get_connection(root):
            return object()

        def recommend_audio(conn, *, platform, limit):
            assert platform == "reels"
            assert limit == 2
            return {
                "recommendations": [
                    {"title": "first", "localPreviewPath": str(first_track)},
                    {"title": "second", "localPreviewPath": str(second_track)},
                ]
            }

        return get_connection, recommend_audio

    def fake_run_ffmpeg(cmd, *, output_path):
        selected.append(Path(cmd[4]))
        output_path.write_bytes(b"muxed")
        return output_path

    monkeypatch.setattr(
        "repurposer.engines.audio._reference_audio_helpers", fake_helpers
    )
    monkeypatch.setattr("repurposer.engines.audio.run_ffmpeg", fake_run_ffmpeg)

    output = AudioEngine.apply(
        source, tmp_path / "audio.mp4", platform="reels", account_index=1
    )

    assert output == tmp_path / "audio.mp4"
    assert selected == [second_track]


def test_audio_engine_fails_closed_when_required_audio_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    monkeypatch.setattr(
        "repurposer.engines.audio._reference_audio_helpers", lambda: (None, None)
    )

    with pytest.raises(RuntimeError, match="audio change required"):
        AudioEngine.apply(
            source, tmp_path / "audio.mp4", platform="reels", require_audio_change=True
        )


def test_variant_pipeline_passes_account_index_to_audio_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    master = _tiny_mp4(tmp_path / "master.mp4")
    seen_indexes: list[int] = []

    monkeypatch.setattr(
        RepurposeConfig,
        "from_preset",
        classmethod(
            lambda cls, name: cls(
                target_platform="reels",
                aggressiveness=0.0,
                enable_editorial=False,
                enable_audio=True,
                enable_generative=False,
                enable_polish=False,
                enable_micro=False,
            )
        ),
    )

    def fake_audio(video_path, output_path, **kwargs):
        seen_indexes.append(kwargs["account_index"])
        output_path.write_bytes(
            video_path.read_bytes() + str(kwargs["account_index"]).encode("ascii")
        )
        return output_path

    monkeypatch.setattr("repurposer.pipeline.AudioEngine.apply", fake_audio)
    monkeypatch.setattr(
        "repurposer.pipeline.QualityGate.is_quality_acceptable", lambda path: True
    )
    monkeypatch.setattr(
        "repurposer.pipeline.SimilarityGate.calculate_ssim", lambda left, right: 0.7
    )

    VariantPipeline(
        master,
        accounts=[{"account_id": "acct_a"}, {"account_id": "acct_b"}],
        output_dir=tmp_path / "variants",
    ).generate_assignment_manifest(
        preset_name="ig_subtle",
        campaign_slug="may",
        master_asset_id="asset_master",
        write_manifest=False,
    )

    assert seen_indexes == [0, 1]


def test_visual_engine_skips_cleanly_when_video_to_video_is_unsupported(
    tmp_path: Path,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")

    assert (
        VisualEngine.apply(
            source, tmp_path / "visual.mp4", prompt="make a safe visual variant"
        )
        == source
    )


def test_similarity_gate_extracts_keyframes_and_compares_phash(tmp_path: Path):
    master = _tiny_mp4(tmp_path / "master.mp4")
    variant = _tiny_mp4(tmp_path / "variant.mp4")

    frames = SimilarityGate.extract_keyframes(master, count=2)
    assert len(frames) == 2

    assert SimilarityGate.calculate_phash_distance(master, variant) >= 0
    assert SimilarityGate.calculate_ssim(master, variant) <= 1.0


def test_similarity_gate_raises_on_unparseable_ssim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    master = _tiny_mp4(tmp_path / "master.mp4")
    variant = _tiny_mp4(tmp_path / "variant.mp4")

    def no_ssim(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 0, stdout="", stderr="no score here"
        )

    monkeypatch.setattr(subprocess, "run", no_ssim)

    with pytest.raises(RuntimeError, match="All score"):
        SimilarityGate.calculate_ssim(master, variant)


def test_variant_pipeline_generates_account_bound_assignment_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    master = _tiny_mp4(tmp_path / "master.mp4")
    accounts = [
        {
            "account_id": "acct_a",
            "instagram_account_id": "ig_a",
            "preset_name": "ig_subtle",
        },
        {
            "account_id": "acct_b",
            "instagram_account_id": "ig_b",
            "preset_name": "ig_subtle",
        },
        {
            "account_id": "acct_c",
            "instagram_account_id": "ig_c",
            "preset_name": "ig_subtle",
        },
    ]

    monkeypatch.setattr(
        RepurposeConfig,
        "from_preset",
        classmethod(
            lambda cls, name: cls(
                target_platform="reels",
                aggressiveness=0.1,
                enable_editorial=False,
                enable_audio=False,
                enable_generative=False,
                enable_polish=True,
                enable_micro=False,
            )
        ),
    )
    monkeypatch.setattr(
        "repurposer.pipeline.QualityGate.is_quality_acceptable", lambda path: True
    )
    ssim_values = iter([0.72, 0.7, 0.63, 0.69, 0.64, 0.65])
    monkeypatch.setattr(
        "repurposer.pipeline.SimilarityGate.calculate_ssim",
        lambda left, right: next(ssim_values),
    )

    pipeline = VariantPipeline(
        master, accounts=accounts, platform="reels", output_dir=tmp_path / "variants"
    )
    manifest = pipeline.generate_assignment_manifest(
        preset_name="ig_subtle",
        campaign_slug="may",
        master_asset_id="asset_master",
    )

    validate_variant_assignment(manifest)
    assert len(manifest["assignments"]) == 3
    assert {item["account_id"] for item in manifest["assignments"]} == {
        "acct_a",
        "acct_b",
        "acct_c",
    }
    assert all(
        "acct_" in Path(item["variant_path"]).name for item in manifest["assignments"]
    )
    assert (tmp_path / "variants" / "asset_master.variant_assignment.v1.json").exists()


def test_variant_pipeline_keeps_ssim_as_diagnostic_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    master = _tiny_mp4(tmp_path / "master.mp4")
    accounts = [
        {"account_id": "acct_a", "preset_name": "ig_subtle"},
        {"account_id": "acct_b", "preset_name": "ig_subtle"},
    ]
    monkeypatch.setattr(
        RepurposeConfig,
        "from_preset",
        classmethod(
            lambda cls, name: cls(
                target_platform="reels",
                aggressiveness=0.1,
                enable_editorial=False,
                enable_audio=False,
                enable_generative=False,
                enable_polish=True,
                enable_micro=False,
            )
        ),
    )
    monkeypatch.setattr(
        "repurposer.pipeline.QualityGate.is_quality_acceptable", lambda path: True
    )
    monkeypatch.setattr(
        "repurposer.pipeline.SimilarityGate.calculate_ssim", lambda left, right: 0.99
    )

    manifest = VariantPipeline(
        master,
        accounts=accounts,
        output_dir=tmp_path / "variants",
    ).generate_assignment_manifest(
        preset_name="ig_subtle",
        campaign_slug="may",
        master_asset_id="asset_master",
        write_manifest=False,
    )

    assert len(manifest["assignments"]) == 2
    assert all(
        item["distinctness_scores"]["master_ssim"] == 0.99
        for item in manifest["assignments"]
    )
    assert manifest["assignments"][1]["distinctness_scores"]["sibling_max_ssim"] == 0.99
