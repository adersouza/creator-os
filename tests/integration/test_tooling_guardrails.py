from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _workflow(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_security_workflow_contains_dependency_review_and_trivy() -> None:
    workflow = _workflow(".github/workflows/security.yml")
    jobs = workflow["jobs"]

    assert "dependency-review" in jobs
    dependency_steps = jobs["dependency-review"]["steps"]
    assert any(step.get("uses") == "actions/dependency-review-action@v4" for step in dependency_steps)

    assert "trivy" in jobs
    trivy_steps = jobs["trivy"]["steps"]
    trivy_step = next(step for step in trivy_steps if step.get("name") == "Trivy scan")
    assert trivy_step["uses"] == "docker://aquasec/trivy:0.65.0"
    assert "--format sarif" in trivy_step["with"]["args"]
    assert "--output trivy-results.sarif" in trivy_step["with"]["args"]
    assert "--exit-code 0" in trivy_step["with"]["args"]
    assert any(step.get("uses") == "github/codeql-action/upload-sarif@v4" for step in trivy_steps)


def test_monorepo_ci_contains_architecture_and_sbom_jobs() -> None:
    workflow = _workflow(".github/workflows/monorepo-ci.yml")
    jobs = workflow["jobs"]

    assert "architecture" in jobs
    arch_runs = [step.get("run", "") for step in jobs["architecture"]["steps"]]
    assert "pnpm check:arch" in arch_runs

    assert "sbom" in jobs
    sbom_runs = "\n".join(step.get("run", "") for step in jobs["sbom"]["steps"])
    assert "@cyclonedx/cdxgen" in sbom_runs
    assert "-t js" in sbom_runs
    assert "uv export" in sbom_runs
    assert "--all-extras" not in sbom_runs
    assert any(step.get("uses") == "actions/upload-artifact@v4" for step in jobs["sbom"]["steps"])


def test_architecture_guard_configs_are_narrow_and_present() -> None:
    depcruise = (ROOT / ".dependency-cruiser.cjs").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    python_checker = (ROOT / "scripts/check-python-architecture-boundaries.py").read_text(encoding="utf-8")

    assert "dashboard-ui-no-live-publish-runtime" in depcruise
    assert "tribe-research-not-operational-gate" in depcruise
    assert "pipeline_contracts remains foundational" in pyproject
    assert "campaign_factory core does not import reference_factory directly" in pyproject
    assert "BOUNDARIES" in python_checker


def test_media_qc_is_read_only_contract() -> None:
    media_qc = (ROOT / "python_packages/reel_factory/media_qc.py").read_text(encoding="utf-8")

    assert "wouldWrite" in media_qc
    assert "subprocess.run" in media_qc
    assert "ffprobe" in media_qc
    assert "ffmpeg" in media_qc
    assert ".write_bytes" not in media_qc
