from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
import reference_factory.url_intake as intake
from reference_factory.url_intake import analyze_url_reference, select_anchor


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
            "color=c=blue:s=360x640:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def test_anchor_hard_block_and_earliest_tie_break() -> None:
    def candidate(stamp: float, blockers: list[str] | None = None):
        return {
            "timeSec": stamp,
            "hardBlockers": blockers or [],
            "measurements": {
                "sharpness": 1,
                "faceVisibility": 1,
                "bodyExtent": 1,
                "singlePersonLowOcclusion": 1,
                "overlayClear": 1,
                "poseRepresentativeness": 1,
            },
        }

    blocked = candidate(0.0, ["black_frame"])
    early = candidate(0.5)
    later = candidate(0.8)
    assert select_anchor([blocked, later, early])["timeSec"] == 0.5
    assert blocked["score"] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_dry_run_is_write_free_and_apply_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    data_root = tmp_path / "reference-data"
    db_path = tmp_path / "reference.sqlite"
    metadata = {
        "platform": "instagram",
        "nativeMediaId": "reel123",
        "originalUrl": "https://www.instagram.com/reel/reel123/?tracking=x",
        "canonicalUrl": "https://www.instagram.com/reel/reel123/",
        "extractor": "Instagram",
        "extractorVersion": "test",
    }
    monkeypatch.setattr(
        intake,
        "_apple_vision",
        lambda _path: {
            "available": True,
            "provider": "apple_vision",
            "requests": [],
            "frames": [
                {
                    "identifier": index,
                    "available": True,
                    "faces": [{"width": 0.2, "height": 0.2, "confidence": 1.0}],
                    "bodies": [],
                    "handCount": 0,
                    "text": [],
                }
                for index in range(7)
            ],
        },
    )
    monkeypatch.setattr(
        intake,
        "_mediapipe",
        lambda _path: {
            "available": False,
            "provenance": {"available": False, "reason": "test_missing"},
            "frames": [],
        },
    )
    monkeypatch.setattr(
        intake,
        "run_selected_ocr",
        lambda _path, requested_engine: {
            "available": True,
            "engine": requested_engine,
            "boxes": [],
        },
    )
    dry = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=False
    )
    assert dry["apply"] is False
    assert not data_root.exists()
    assert not db_path.exists()
    assert dry["frameDerivatives"]["literal_first"]["path"] is None
    first = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=True
    )
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    existing_dry = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=False
    )
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    second = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=True
    )
    assert first["duplicateResult"] == "created"
    assert existing_dry["duplicateResult"] == "reused_platform_media_id"
    assert existing_dry["apply"] is False
    assert before == after
    assert second["duplicateResult"] == "reused_platform_media_id"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM frame_samples").fetchone()[0] == 7
        assert (
            conn.execute("SELECT COUNT(*) FROM reference_anchor_receipts").fetchone()[0]
            == 1
        )
