from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_temporal_pdq() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "contentforge"
        / "lib"
        / "temporal_pdq.py"
    )
    spec = importlib.util.spec_from_file_location(
        "contentforge_temporal_pdq", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_temporal_pdq_reports_every_frame_hash_failure(monkeypatch):
    temporal_pdq = _load_temporal_pdq()

    def fail_to_open(_path):
        raise OSError("corrupt frame")

    monkeypatch.setattr(temporal_pdq.Image, "open", fail_to_open)
    hashes, errors = temporal_pdq.compute_frame_hashes(["frame_001.jpg"])

    assert hashes == []
    assert errors == [
        {
            "path": "frame_001.jpg",
            "error": "OSError: corrupt frame",
        }
    ]


def test_temporal_pdq_does_not_swallow_process_interrupts(monkeypatch):
    temporal_pdq = _load_temporal_pdq()

    def interrupt(_path):
        raise KeyboardInterrupt

    monkeypatch.setattr(temporal_pdq.Image, "open", interrupt)
    with pytest.raises(KeyboardInterrupt):
        temporal_pdq.compute_frame_hashes(["frame_001.jpg"])
