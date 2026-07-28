"""Deterministic duration-aware energy/onset segment selection."""

from __future__ import annotations

import hashlib
import math
import shutil
import statistics
import subprocess
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .acquisition import AcquiredAudio

_SAMPLE_RATE = 16_000
_FRAME_SECONDS = 0.10
_WINDOW_STEP_SECONDS = 0.25


class SegmentSelectionError(RuntimeError):
    """A compatible, decodable audio segment could not be selected."""


@dataclass(frozen=True)
class SegmentSelection:
    """Exact segment and deterministic evidence used by FFmpeg embedding."""

    start_offset_seconds: float
    end_seconds: float
    duration_seconds: float
    segment_score: float
    rms_energy: float
    peak_energy: float
    onset_count: int
    energy_change: float
    beat_evidence: str
    hook_evidence: str
    selection_reason: str
    decoded_audio_fingerprint: str
    processed_segment_sha256: str
    processed_segment_format: str = "s16le_mono_16000hz"

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "creator_os.audio_segment_selection.v1",
            **asdict(self),
        }


def select_segment(
    acquired: AcquiredAudio,
    *,
    reel_duration_seconds: float,
    preferred_offsets: tuple[float, ...] = (),
    excluded_offsets: tuple[float, ...] = (),
) -> SegmentSelection:
    """Evaluate the whole track instead of defaulting to offset zero."""

    target = round(float(reel_duration_seconds), 6)
    if target <= 0:
        raise SegmentSelectionError("Reel duration must be positive")
    if acquired.duration_seconds + 0.03 < target:
        raise SegmentSelectionError("candidate audio is shorter than the Reel")
    pcm = _decode_pcm(acquired.cache_path)
    if not pcm:
        raise SegmentSelectionError("candidate audio decoded to no samples")
    frame_size = max(1, round(_SAMPLE_RATE * _FRAME_SECONDS))
    energies = [
        _rms(pcm[index : index + frame_size])
        for index in range(0, len(pcm), frame_size)
    ]
    frames_per_window = max(1, math.ceil(target / _FRAME_SECONDS))
    last_start_frame = max(0, len(energies) - frames_per_window)
    step_frames = max(1, round(_WINDOW_STEP_SECONDS / _FRAME_SECONDS))
    starts = set(range(0, last_start_frame + 1, step_frames))
    starts.add(last_start_frame)
    for offset in preferred_offsets:
        frame = round(max(0.0, offset) / _FRAME_SECONDS)
        if frame <= last_start_frame:
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
        raise SegmentSelectionError(
            "all duration-compatible segments are inside the creator cooldown"
        )
    global_mean = statistics.fmean(energies)
    global_std = statistics.pstdev(energies) if len(energies) > 1 else 0.0
    scored: list[tuple[float, int, dict[str, float | int]]] = []
    for start in sorted(starts):
        values = energies[start : start + frames_per_window]
        mean_energy = statistics.fmean(values)
        peak_energy = max(values)
        deltas = [
            max(0.0, values[index] - values[index - 1])
            for index in range(1, len(values))
        ]
        onset_threshold = max(global_std * 0.35, global_mean * 0.08, 0.001)
        onsets = sum(delta >= onset_threshold for delta in deltas)
        energy_change = statistics.fmean(deltas) if deltas else 0.0
        preferred_bonus = (
            0.08
            if any(
                abs(start * _FRAME_SECONDS - offset) <= _WINDOW_STEP_SECONDS
                for offset in preferred_offsets
            )
            else 0.0
        )
        beginning_penalty = 0.06 if start == 0 and last_start_frame > 0 else 0.0
        score = (
            _ratio(mean_energy, global_mean) * 0.46
            + _ratio(peak_energy, max(energies)) * 0.18
            + min(1.0, onsets / max(1.0, target * 2.0)) * 0.24
            + _ratio(energy_change, global_std + global_mean * 0.05) * 0.12
            + preferred_bonus
            - beginning_penalty
        )
        scored.append(
            (
                score,
                start,
                {
                    "rms": mean_energy,
                    "peak": peak_energy,
                    "onsets": onsets,
                    "change": energy_change,
                },
            )
        )
    score, start_frame, evidence = max(
        scored,
        key=lambda value: (value[0], value[1]),
    )
    start_seconds = min(
        max(0.0, start_frame * _FRAME_SECONDS),
        max(0.0, acquired.duration_seconds - target),
    )
    segment_pcm = _slice_pcm(pcm, start_seconds, target)
    expected_samples = max(1, round(target * _SAMPLE_RATE))
    if len(segment_pcm) != expected_samples:
        raise SegmentSelectionError(
            "decoded audio does not contain the full selected segment"
        )
    canonical_segment_bytes = segment_pcm.tobytes()
    fingerprint = hashlib.sha256(canonical_segment_bytes).hexdigest()
    return SegmentSelection(
        start_offset_seconds=round(start_seconds, 6),
        end_seconds=round(start_seconds + target, 6),
        duration_seconds=target,
        segment_score=round(score, 6),
        rms_energy=round(float(evidence["rms"]), 8),
        peak_energy=round(float(evidence["peak"]), 8),
        onset_count=int(evidence["onsets"]),
        energy_change=round(float(evidence["change"]), 8),
        beat_evidence="pcm_energy_onset_proxy",
        hook_evidence=(
            "provider_preferred_offset_plus_energy"
            if preferred_offsets
            else "energy_and_onset_window"
        ),
        selection_reason=(
            "Highest deterministic duration-compatible window by RMS energy, "
            "peak energy, onset density, and energy change"
        ),
        decoded_audio_fingerprint=fingerprint,
        processed_segment_sha256=fingerprint,
    )


def decoded_audio_fingerprint(path: Path) -> str:
    """Fingerprint decoded mono PCM rather than container metadata."""

    return hashlib.sha256(_decode_pcm(path).tobytes()).hexdigest()


def _decode_pcm(path: Path) -> array[int]:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(_SAMPLE_RATE),
            "-t",
            "600",
            "-f",
            "s16le",
            "pipe:1",
        ],
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise SegmentSelectionError(
            (result.stderr.decode("utf-8", errors="replace") or "ffmpeg decode failed")[
                -2000:
            ].strip()
        )
    pcm = array("h")
    pcm.frombytes(result.stdout)
    if pcm.itemsize != 2:
        raise SegmentSelectionError("unexpected PCM sample width")
    return pcm


def _rms(values: array[int]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(float(value) ** 2 for value in values) / len(values)) / 32768


def _ratio(value: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return min(1.5, max(0.0, value / denominator))


def _slice_pcm(pcm: array[int], start: float, duration: float) -> array[int]:
    first = max(0, round(start * _SAMPLE_RATE))
    count = max(1, round(duration * _SAMPLE_RATE))
    return pcm[first : first + count]
