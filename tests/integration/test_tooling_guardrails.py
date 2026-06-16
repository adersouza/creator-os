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
    assert jobs["sbom"]["permissions"]["attestations"] == "write"
    assert jobs["sbom"]["permissions"]["id-token"] == "write"
    assert any(
        step.get("uses") == "actions/attest-build-provenance@v4.1.0"
        for step in jobs["sbom"]["steps"]
    )

    assert "dashboard-build-provenance" in jobs
    dashboard_runs = "\n".join(
        step.get("run", "") for step in jobs["dashboard-build-provenance"]["steps"]
    )
    assert "pnpm --filter juno33 build" in dashboard_runs
    assert jobs["dashboard-build-provenance"]["permissions"]["attestations"] == "write"
    assert jobs["dashboard-build-provenance"]["permissions"]["id-token"] == "write"
    assert any(
        step.get("uses") == "actions/attest-build-provenance@v4.1.0"
        for step in jobs["dashboard-build-provenance"]["steps"]
    )


def test_scorecard_workflow_is_report_mode() -> None:
    workflow = _workflow(".github/workflows/scorecard.yml")
    jobs = workflow["jobs"]
    scorecard_steps = jobs["scorecard"]["steps"]

    scorecard_step = next(
        step for step in scorecard_steps if step.get("uses") == "ossf/scorecard-action@v2.4.3"
    )
    assert scorecard_step["continue-on-error"] is True
    assert scorecard_step["with"]["results_format"] == "sarif"
    assert scorecard_step["with"]["publish_results"] is False
    assert any(
        step.get("uses") == "actions/upload-artifact@v4"
        and step.get("name") == "Upload Scorecard report artifact"
        for step in scorecard_steps
    )
    sarif_upload = next(
        step
        for step in scorecard_steps
        if step.get("uses") == "github/codeql-action/upload-sarif@v4"
    )
    assert "github.event_name != 'pull_request'" in sarif_upload["if"]
    assert any(
        step.get("uses") == "github/codeql-action/upload-sarif@v4"
        for step in scorecard_steps
    )


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
    active_qc = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "python_packages/reel_factory/ai_visual_qc.py",
            "python_packages/reel_factory/qc_check.py",
        )
    )

    assert "visualQcStatus" in active_qc
    assert "subprocess.run" in active_qc
    assert "ffprobe" in active_qc
    assert "ffmpeg" in active_qc
    assert ".write_bytes" not in active_qc


def test_governance_docs_cover_runtime_promotion_and_runbooks() -> None:
    promotion = (ROOT / "docs/architecture/monorepo_deployment_promotion.md").read_text(
        encoding="utf-8"
    )
    media_provenance = (ROOT / "docs/architecture/media_provenance_contract.md").read_text(
        encoding="utf-8"
    )
    runbooks = (ROOT / "docs/runbooks/operator_failure_runbooks.md").read_text(
        encoding="utf-8"
    )

    assert "Production Promotion Checklist" in promotion
    assert "split `ThreadsDashboard` remains rollback mirror" in promotion
    assert "schema\": \"creator_os.media_provenance.v1" in media_provenance
    assert "Do not use provenance alone as a publishability" in media_provenance
    for heading in [
        "Publish Preflight Failure",
        "QStash Dispatch Failure",
        "Account Restriction",
        "Inventory Buffer Shortfall",
        "Story/Reel Surface Mismatch",
        "Media QC Failure",
    ]:
        assert heading in runbooks
    assert "Do not touch:" in runbooks
    assert "Safe recovery boundary:" in runbooks
