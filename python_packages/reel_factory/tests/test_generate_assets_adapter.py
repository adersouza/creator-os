from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from generate_assets import HiggsfieldCliAdapter, HiggsfieldCommandError


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "higgsfield_adapter"


@dataclass
class FakeCompletedProcess:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_higgsfield_adapter_returns_completed_fixture_json() -> None:
    payload = _fixture("completed_image.json")

    def runner(cmd, capture_output, text, timeout):
        return FakeCompletedProcess(returncode=0, stdout=json.dumps(payload))

    result = HiggsfieldCliAdapter(runner=runner, timeout_seconds=7).run_json(
        ["higgsfield", "generate", "create", "text2image_soul_v2"]
    )

    assert result["id"] == "img_completed_001"
    assert "_adapter" not in result


def test_higgsfield_adapter_marks_partial_generation_fixture() -> None:
    payload = _fixture("partial_processing.json")

    def runner(cmd, capture_output, text, timeout):
        return FakeCompletedProcess(returncode=0, stdout=json.dumps(payload))

    result = HiggsfieldCliAdapter(runner=runner).run_json(
        ["higgsfield", "generate", "create", "kling3_0"]
    )

    assert result["_adapter"]["failureKind"] == "partial"
    assert result["_adapter"]["status"] == "processing"
    assert result["items"][0]["id"] == "job_processing_001"


def test_higgsfield_adapter_classifies_quota_rejection_fixture() -> None:
    payload = _fixture("quota_error.json")

    def runner(cmd, capture_output, text, timeout):
        return FakeCompletedProcess(returncode=1, stdout=payload["stdout"], stderr=payload["stderr"])

    with pytest.raises(HiggsfieldCommandError) as excinfo:
        HiggsfieldCliAdapter(runner=runner).run_json(
            ["higgsfield", "generate", "create", "kling3_0"]
        )

    assert excinfo.value.failure_kind == "quota"
    assert "insufficient credits" in excinfo.value.stderr


def test_higgsfield_adapter_classifies_timeout() -> None:
    def runner(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout=timeout, output="job queued")

    with pytest.raises(HiggsfieldCommandError) as excinfo:
        HiggsfieldCliAdapter(runner=runner, timeout_seconds=3).run_json(
            ["higgsfield", "generate", "create", "kling3_0"]
        )

    assert excinfo.value.failure_kind == "timeout"
    assert excinfo.value.returncode == -1
    assert "timed out" in excinfo.value.stderr
