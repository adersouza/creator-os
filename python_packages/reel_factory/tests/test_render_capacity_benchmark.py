from __future__ import annotations

import shutil

import pytest

from render_capacity_benchmark import run_render_capacity_benchmark


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")


def test_render_capacity_benchmark_uses_temp_fixtures_and_reports_throughput() -> None:
    report = run_render_capacity_benchmark(concurrencies=[1], jobs_per_concurrency=1, duration=0.25, encoder="libx264")

    assert report["schema"] == "reel_factory.render_capacity_benchmark.v1"
    assert report["writesProductionState"] is False
    assert report["scheduled"] == 0
    assert report["published"] == 0
    assert report["results"][0]["concurrency"] == 1
    assert report["results"][0]["jobsAttempted"] == 1
    assert "successfulRendersPerHour" in report["results"][0]
