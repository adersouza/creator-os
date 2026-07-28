from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from campaign_factory.db import connect, init_db
from campaign_factory.reference_audio_intake import inspect_reference_audio


def _video(path: Path) -> None:
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=360x640:r=24:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:duration=1.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_reference_audio_exact_evidence_dedupe_and_occurrences(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    conn = connect(tmp_path / "campaign.sqlite")
    init_db(conn)
    metadata = {"platform": "instagram", "nativeMediaId": "reel123"}
    dry = inspect_reference_audio(
        conn,
        source_video=source,
        reference_id="ref_dry",
        metadata=metadata,
        artifact_root=tmp_path / "artifacts",
        apply=False,
    )
    assert dry["status"] == "proposed"
    assert (
        conn.execute("SELECT COUNT(*) FROM audio_reference_occurrences").fetchone()[0]
        == 0
    )
    first = inspect_reference_audio(
        conn,
        source_video=source,
        reference_id="ref_one",
        metadata=metadata,
        artifact_root=tmp_path / "artifacts",
        apply=True,
        dance_or_synchronized=True,
    )
    second = inspect_reference_audio(
        conn,
        source_video=source,
        reference_id="ref_two",
        metadata={**metadata, "nativeMediaId": "reel456"},
        artifact_root=tmp_path / "artifacts",
        apply=True,
    )
    assert first["classification"] == "REFERENCE_AUDIO_PREFERRED"
    assert first["encodedAudioSha256"]
    assert first["canonicalPcmSha256"]
    assert first["chromaprint"]["status"] in {"available", "unavailable"}
    assert second["canonicalAudioId"] == first["canonicalAudioId"]
    assert second["dedupe"]["matched"] is True
    assert conn.execute("SELECT COUNT(*) FROM audio_catalog").fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM audio_reference_occurrences").fetchone()[0]
        == 2
    )
    assert conn.execute("SELECT COUNT(*) FROM audio_segments").fetchone()[0] == 2
    conn.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_declared_talking_requires_creator_audio(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    conn = connect(tmp_path / "campaign.sqlite")
    init_db(conn)
    result = inspect_reference_audio(
        conn,
        source_video=source,
        reference_id="ref_talking",
        metadata={"platform": "private_reference", "nativeMediaId": "talking"},
        artifact_root=tmp_path / "artifacts",
        apply=False,
        declared_talking=True,
    )
    assert result["classification"] == "CREATOR_AUDIO_REQUIRED"
    conn.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_missing_audio_is_unavailable_without_rows(tmp_path: Path) -> None:
    source = tmp_path / "silent.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:r=24:d=1",
            "-an",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    conn = connect(tmp_path / "campaign.sqlite")
    init_db(conn)
    result = inspect_reference_audio(
        conn,
        source_video=source,
        reference_id="ref_silent",
        metadata={"platform": "private_reference"},
        artifact_root=tmp_path / "artifacts",
        apply=True,
    )
    assert result["status"] == "UNAVAILABLE"
    assert (
        conn.execute("SELECT COUNT(*) FROM audio_reference_occurrences").fetchone()[0]
        == 0
    )
    conn.close()
