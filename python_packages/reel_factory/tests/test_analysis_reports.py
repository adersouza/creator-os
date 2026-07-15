from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reel_factory.analysis_reports import (
    request_analysis_reports,
    write_operator_reports,
)
from reel_factory.readiness_check import run_readiness
from reel_factory.winner_dna import upsert_reel_feature


def _output(root: Path) -> Path:
    output = (
        root
        / "02_processed"
        / "clip_001"
        / "clip_001_h00_v01_original_light_deadbeef.mp4"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"fake")
    return output


def test_analysis_report_request_manifest_is_zero_cost_when_no_provider_configured(
    tmp_path: Path,
) -> None:
    output = _output(tmp_path)

    result = request_analysis_reports(tmp_path, clip="clip_001")

    assert result["schema"] == "reel_factory.analysis_report_requests.v1"
    assert result["providerCalls"] == 0
    assert result["estimatedCostUsd"] == 0
    assert result["records"][0]["status"] == "operator_input_required"
    assert result["records"][0]["outputPath"] == str(output)
    assert set(result["records"][0]["requestedReports"]) == {
        "virality",
        "video_analysis",
    }
    manifest = json.loads(
        (output.parent / "_analysis_report_requests.json").read_text(encoding="utf-8")
    )
    assert manifest["records"][0]["sidecars"]["virality"].endswith(
        ".virality_report.json"
    )
    assert manifest["records"][0]["sidecars"]["video_analysis"].endswith(
        ".video_analysis.json"
    )


def test_operator_reports_write_sidecars_consumed_by_readiness_and_winner_dna(
    tmp_path: Path,
) -> None:
    output = _output(tmp_path)

    result = write_operator_reports(
        output,
        virality={"score": 92, "hookScore": 81, "retentionRisk": 18},
        video_analysis={
            "winnerDnaFeatures": {
                "scene": "rooftop",
                "camera": "handheld",
                "pose": "standing",
                "motion": "walk_in",
                "outfit": "white_dress",
                "creator": "stacey",
                "body_style": "hourglass",
                "caption_style": "top_hook",
                "hook_type": "curiosity",
            },
            "scores": {"overallScore": 88, "firstThreeSecondsScore": 84},
        },
        provider="operator_vlm",
    )

    assert result["writtenReports"] == ["virality", "video_analysis"]
    readiness = run_readiness(tmp_path, clip="clip_001", require_virality=True)
    assert readiness["records"][0]["viralityQc"]["status"] == "passed"
    features = upsert_reel_feature(tmp_path, output)["features"]
    assert features["feature_source"] == "video_analysis"
    assert features["scene"] == "rooftop"
    assert features["hook_type"] == "curiosity"


def test_provider_command_generates_requested_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = _output(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, check):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if "--output" not in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps({"streams": []}), stderr=""
            )
        assert str(output) in cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"score": 93, "hookScore": 82, "retentionRisk": 21}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = request_analysis_reports(
        tmp_path,
        clip="clip_001",
        reports=("virality",),
        provider_command="higgsfield-report --mode dry",
    )

    assert result["providerCalls"] == 1
    assert result["records"][0]["status"] == "generated"
    provider_calls = [cmd for cmd in calls if "--output" in cmd]
    assert provider_calls[0][:3] == ["higgsfield-report", "--mode", "dry"]
    readiness = run_readiness(tmp_path, clip="clip_001", require_virality=True)
    assert readiness["records"][0]["viralityQc"]["score"] == 93
