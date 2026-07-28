from __future__ import annotations

from pathlib import Path

import pytest
from campaign_factory.audio_radar import development_evaluator
from campaign_factory.audio_radar.development_evaluator import (
    DevelopmentAudioEvaluatorError,
    evaluate_local_audio,
)


def _features() -> dict[str, object]:
    return {
        "rms": [0.05] * 20 + [0.9] * 40,
        "onset_strength": [0.02] * 20 + [0.8, 0.1] * 20,
        "beat_times": [2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
        "duration_seconds": 6.0,
        "librosa_version": "test",
    }


def test_evaluator_is_bounded_read_only_and_hashes_local_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"local test audio")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(
        development_evaluator,
        "_extract_features",
        lambda _path, *, max_source_seconds: _features(),
    )

    result = evaluate_local_audio(
        source,
        reel_duration_seconds=2.0,
        max_source_seconds=6.0,
    )

    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert after == before
    assert result["developmentOnly"] is True
    assert result["persistenceWrites"] is False
    assert result["input"]["path"] == str(source)
    assert len(result["input"]["sha256"]) == 64
    assert result["selection"]["startSeconds"] > 0
    assert result["selection"]["durationSeconds"] == 2.0
    assert result["selection"]["candidateCount"] <= 31


def test_evaluator_preserves_exclusions_and_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"local test audio")
    monkeypatch.setattr(
        development_evaluator,
        "_extract_features",
        lambda _path, *, max_source_seconds: _features(),
    )

    first = evaluate_local_audio(source, reel_duration_seconds=2.0)
    second = evaluate_local_audio(source, reel_duration_seconds=2.0)
    cooled = evaluate_local_audio(
        source,
        reel_duration_seconds=2.0,
        excluded_offsets=(first["selection"]["startSeconds"],),
    )

    assert first == second
    assert (
        abs(cooled["selection"]["startSeconds"] - first["selection"]["startSeconds"])
        > 0.25
    )


def test_evaluator_rejects_unbounded_or_unsafe_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"local test audio")
    symlink = tmp_path / "track-link.wav"
    symlink.symlink_to(source)
    monkeypatch.setattr(
        development_evaluator,
        "_extract_features",
        lambda _path, *, max_source_seconds: _features(),
    )

    with pytest.raises(DevelopmentAudioEvaluatorError, match="within"):
        evaluate_local_audio(
            source,
            reel_duration_seconds=2.0,
            max_source_seconds=90.1,
        )
    with pytest.raises(DevelopmentAudioEvaluatorError, match="symlink"):
        evaluate_local_audio(symlink, reel_duration_seconds=2.0)
