from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _workflow(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _action_major(uses: str, action: str) -> int | None:
    prefix = f"{action}@v"
    if not uses.startswith(prefix):
        return None
    version = uses.removeprefix(prefix).split(".", maxsplit=1)[0]
    return int(version) if version.isdigit() else None


def _assert_action_major_allowed(steps: list[dict], action: str, allowed: set[int]) -> None:
    majors = [
        major
        for step in steps
        if (major := _action_major(step.get("uses", ""), action)) is not None
    ]
    assert majors, f"{action} must be present"
    assert set(majors).issubset(allowed), f"{action} majors {majors} must be in {sorted(allowed)}"


def test_security_workflow_gates_trivy_and_verified_secret_scans() -> None:
    workflow = _workflow(".github/workflows/security.yml")
    jobs = workflow["jobs"]

    assert "dependency-review" not in jobs

    assert "trivy" in jobs
    trivy_steps = jobs["trivy"]["steps"]
    trivy_step = next(step for step in trivy_steps if step.get("name") == "Trivy scan")
    assert trivy_step["uses"] == "docker://aquasec/trivy:0.65.0"
    assert "--format sarif" in trivy_step["with"]["args"]
    assert "--output trivy-results.sarif" in trivy_step["with"]["args"]
    assert "--exit-code 1" in trivy_step["with"]["args"]
    assert "--skip-dirs apps/dashboard" not in trivy_step["with"]["args"]
    assert any(step.get("uses") == "github/codeql-action/upload-sarif@v4" for step in trivy_steps)
    assert any(
        step.get("name") == "Gate Trivy HIGH/CRITICAL findings"
        and "exit 1" in step.get("run", "")
        for step in trivy_steps
    )

    secret_steps = jobs["secrets"]["steps"]
    trufflehog_step = next(
        step
        for step in secret_steps
        if step.get("name") == "TruffleHog full-history secret scan"
    )
    assert trufflehog_step["uses"] == "trufflesecurity/trufflehog@main"
    assert trufflehog_step["with"]["extra_args"] == "--only-verified"
    assert "continue-on-error" not in trufflehog_step


def test_monorepo_ci_contains_architecture_and_sbom_jobs() -> None:
    workflow = _workflow(".github/workflows/monorepo-ci.yml")
    jobs = workflow["jobs"]

    for job_name in (
        "contracts",
        "architecture",
        "javascript",
        "sbom",
    ):
        _assert_action_major_allowed(jobs[job_name]["steps"], "pnpm/action-setup", {6})
    assert "visual-regression" not in jobs
    assert "dashboard-build-provenance" not in jobs

    assert "architecture" in jobs
    arch_runs = [step.get("run", "") for step in jobs["architecture"]["steps"]]
    assert "pnpm check:arch" in arch_runs

    assert "sbom" in jobs
    sbom_runs = "\n".join(step.get("run", "") for step in jobs["sbom"]["steps"])
    assert "@cyclonedx/cdxgen" in sbom_runs
    assert "-t js" in sbom_runs
    assert "uv export" in sbom_runs
    assert "--all-extras" not in sbom_runs
    _assert_action_major_allowed(jobs["sbom"]["steps"], "actions/upload-artifact", {4, 7})
    assert jobs["sbom"]["permissions"]["attestations"] == "write"
    assert jobs["sbom"]["permissions"]["id-token"] == "write"
    assert any(
        step.get("uses") == "actions/attest-build-provenance@v4.1.0"
        for step in jobs["sbom"]["steps"]
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
    scorecard_artifact_steps = [
        step
        for step in scorecard_steps
        if step.get("name") == "Upload Scorecard report artifact"
    ]
    _assert_action_major_allowed(scorecard_artifact_steps, "actions/upload-artifact", {4, 7})
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


def test_dependabot_no_longer_excludes_deleted_dashboard_mirror() -> None:
    config = _workflow(".github/dependabot.yml")
    npm_updates = [
        update
        for update in config["updates"]
        if update["package-ecosystem"] == "npm" and update["directory"] == "/"
    ]

    assert len(npm_updates) == 1
    assert "apps/dashboard/**" not in npm_updates[0].get("exclude-paths", [])


def test_dependabot_ignores_known_incompatible_eslint_major() -> None:
    config = _workflow(".github/dependabot.yml")
    npm_update = next(
        update
        for update in config["updates"]
        if update["package-ecosystem"] == "npm" and update["directory"] == "/"
    )
    eslint_ignores = [
        ignore
        for ignore in npm_update.get("ignore", [])
        if ignore["dependency-name"] == "eslint"
    ]

    assert len(eslint_ignores) == 1
    assert "version-update:semver-major" in eslint_ignores[0]["update-types"]


def test_secret_scan_and_ignore_defaults_cover_local_secret_files() -> None:
    gitleaks = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "[extend]" in gitleaks
    assert "useDefault = true" in gitleaks
    assert "\nsecrets.toml\n" in gitignore
    assert "\n*.secrets.toml\n" in gitignore


def test_architecture_guard_configs_are_narrow_and_present() -> None:
    depcruise = (ROOT / ".dependency-cruiser.cjs").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    python_checker = (ROOT / "scripts/check-python-architecture-boundaries.py").read_text(encoding="utf-8")

    assert "pipeline-contracts-remain-foundational" in depcruise
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
    assert "Dashboard production deployment must stay on the external ThreadsDashboard" in promotion
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
