"""Bounded, read-only librosa challenger for local Audio Radar development.

This module is intentionally disconnected from normal creation and refresh. It
accepts local regular files, emits JSON to stdout, and performs no persistence,
provider, database, or network work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

_SAMPLE_RATE = 16_000
_FRAME_SECONDS = 0.10
_WINDOW_STEP_SECONDS = 0.25
_MAX_FILES = 10
_MAX_SOURCE_SECONDS = 90.0


class DevelopmentAudioEvaluatorError(RuntimeError):
    """The bounded local development evaluation could not run."""


def evaluate_local_audio(
    path: Path,
    *,
    reel_duration_seconds: float,
    max_source_seconds: float = _MAX_SOURCE_SECONDS,
    preferred_offsets: tuple[float, ...] = (),
    excluded_offsets: tuple[float, ...] = (),
) -> dict[str, Any]:
    """Evaluate one local file without writing state or changing production."""

    source = path.expanduser()
    if source.is_symlink():
        raise DevelopmentAudioEvaluatorError("input must not be a symlink")
    source = source.resolve()
    if not source.is_file():
        raise DevelopmentAudioEvaluatorError("input must be a local regular file")
    target = round(float(reel_duration_seconds), 6)
    bounded_seconds = float(max_source_seconds)
    if target <= 0:
        raise DevelopmentAudioEvaluatorError("reel duration must be positive")
    if bounded_seconds <= 0 or bounded_seconds > _MAX_SOURCE_SECONDS:
        raise DevelopmentAudioEvaluatorError(
            f"max source duration must be within (0, {_MAX_SOURCE_SECONDS:g}] seconds"
        )
    features = _extract_features(source, max_source_seconds=bounded_seconds)
    selected = _score_windows(
        rms=features["rms"],
        onset_strength=features["onset_strength"],
        beat_times=features["beat_times"],
        analyzed_duration_seconds=float(features["duration_seconds"]),
        reel_duration_seconds=target,
        preferred_offsets=preferred_offsets,
        excluded_offsets=excluded_offsets,
    )
    return {
        "schema": "creator_os.audio_segment_development_evaluation.v1",
        "developmentOnly": True,
        "persistenceWrites": False,
        "input": {
            "path": str(source),
            "sha256": _sha256_file(source),
        },
        "analyzer": {
            "name": "librosa",
            "version": features["librosa_version"],
            "sampleRate": _SAMPLE_RATE,
            "maxSourceSeconds": bounded_seconds,
        },
        "selection": selected,
    }


def _extract_features(path: Path, *, max_source_seconds: float) -> dict[str, Any]:
    try:
        import librosa
        import numpy as np
    except ImportError as exc:
        raise DevelopmentAudioEvaluatorError(
            "librosa evaluator is unavailable; install dependency group audio-eval"
        ) from exc
    samples, sample_rate = librosa.load(
        path,
        sr=_SAMPLE_RATE,
        mono=True,
        duration=max_source_seconds,
    )
    if samples.size == 0:
        raise DevelopmentAudioEvaluatorError("input decoded to no samples")
    frame_length = max(2, round(_SAMPLE_RATE * _FRAME_SECONDS))
    hop_length = frame_length
    rms = librosa.feature.rms(
        y=samples,
        frame_length=frame_length,
        hop_length=hop_length,
        center=False,
    )[0]
    onset = librosa.onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=hop_length,
        center=False,
    )
    _tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sample_rate,
        hop_length=hop_length,
    )
    beat_times = librosa.frames_to_time(
        beat_frames,
        sr=sample_rate,
        hop_length=hop_length,
    )
    duration = min(
        float(samples.size) / float(sample_rate),
        max_source_seconds,
    )
    return {
        "rms": np.asarray(rms, dtype=float).tolist(),
        "onset_strength": np.asarray(onset, dtype=float).tolist(),
        "beat_times": np.asarray(beat_times, dtype=float).tolist(),
        "duration_seconds": duration,
        "librosa_version": str(librosa.__version__),
    }


def _score_windows(
    *,
    rms: list[float],
    onset_strength: list[float],
    beat_times: list[float],
    analyzed_duration_seconds: float,
    reel_duration_seconds: float,
    preferred_offsets: tuple[float, ...] = (),
    excluded_offsets: tuple[float, ...] = (),
) -> dict[str, Any]:
    if analyzed_duration_seconds + 0.03 < reel_duration_seconds:
        raise DevelopmentAudioEvaluatorError("analyzed audio is shorter than the Reel")
    frame_count = min(len(rms), len(onset_strength))
    if frame_count == 0:
        raise DevelopmentAudioEvaluatorError("librosa produced no aligned features")
    rms = [max(0.0, float(value)) for value in rms[:frame_count]]
    onset_strength = [max(0.0, float(value)) for value in onset_strength[:frame_count]]
    frames_per_window = max(1, math.ceil(reel_duration_seconds / _FRAME_SECONDS))
    last_start = max(0, frame_count - frames_per_window)
    step_frames = max(1, round(_WINDOW_STEP_SECONDS / _FRAME_SECONDS))
    starts = set(range(0, last_start + 1, step_frames))
    starts.add(last_start)
    for offset in preferred_offsets:
        frame = round(max(0.0, offset) / _FRAME_SECONDS)
        if frame <= last_start:
            starts.add(frame)
    starts = {
        start
        for start in starts
        if not any(
            abs(start * _FRAME_SECONDS - excluded) <= _WINDOW_STEP_SECONDS
            for excluded in excluded_offsets
        )
    }
    if not starts:
        raise DevelopmentAudioEvaluatorError(
            "all duration-compatible segments are excluded"
        )
    global_rms = statistics.fmean(rms)
    max_rms = max(rms)
    global_onset = statistics.fmean(onset_strength)
    max_onset = max(onset_strength)
    scored: list[tuple[float, int, dict[str, float | int]]] = []
    for start in sorted(starts):
        end = min(frame_count, start + frames_per_window)
        window_rms = rms[start:end]
        window_onset = onset_strength[start:end]
        start_seconds = start * _FRAME_SECONDS
        end_seconds = start_seconds + reel_duration_seconds
        beat_count = sum(start_seconds <= beat < end_seconds for beat in beat_times)
        onset_threshold = max(global_onset, 0.000001)
        onset_count = sum(value >= onset_threshold for value in window_onset)
        preferred_bonus = (
            0.08
            if any(
                abs(start_seconds - offset) <= _WINDOW_STEP_SECONDS
                for offset in preferred_offsets
            )
            else 0.0
        )
        beginning_penalty = 0.06 if start == 0 and last_start > 0 else 0.0
        score = (
            _ratio(statistics.fmean(window_rms), global_rms) * 0.42
            + _ratio(max(window_rms), max_rms) * 0.16
            + _ratio(statistics.fmean(window_onset), global_onset) * 0.22
            + _ratio(max(window_onset), max_onset) * 0.10
            + min(1.0, beat_count / max(1.0, reel_duration_seconds)) * 0.10
            + preferred_bonus
            - beginning_penalty
        )
        scored.append(
            (
                score,
                start,
                {
                    "rmsMean": statistics.fmean(window_rms),
                    "onsetMean": statistics.fmean(window_onset),
                    "onsetCount": onset_count,
                    "beatCount": beat_count,
                },
            )
        )
    score, start, evidence = max(scored, key=lambda value: (value[0], value[1]))
    start_seconds = min(
        start * _FRAME_SECONDS,
        max(0.0, analyzed_duration_seconds - reel_duration_seconds),
    )
    return {
        "startSeconds": round(start_seconds, 6),
        "endSeconds": round(start_seconds + reel_duration_seconds, 6),
        "durationSeconds": reel_duration_seconds,
        "score": round(score, 6),
        "candidateCount": len(scored),
        "rmsMean": round(float(evidence["rmsMean"]), 8),
        "onsetMean": round(float(evidence["onsetMean"]), 8),
        "onsetCount": int(evidence["onsetCount"]),
        "beatCount": int(evidence["beatCount"]),
        "reason": "librosa RMS, onset-strength, and beat challenger",
    }


def _ratio(value: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return min(2.0, max(0.0, value / denominator)) / 2.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only local librosa challenger for Audio Radar segments"
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--max-source-seconds", type=float, default=_MAX_SOURCE_SECONDS)
    parser.add_argument("--preferred-offset", action="append", type=float, default=[])
    parser.add_argument("--excluded-offset", action="append", type=float, default=[])
    args = parser.parse_args(argv)
    if len(args.paths) > _MAX_FILES:
        parser.error(f"at most {_MAX_FILES} local files may be evaluated")
    results = [
        evaluate_local_audio(
            path,
            reel_duration_seconds=args.duration,
            max_source_seconds=args.max_source_seconds,
            preferred_offsets=tuple(args.preferred_offset),
            excluded_offsets=tuple(args.excluded_offset),
        )
        for path in args.paths
    ]
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
