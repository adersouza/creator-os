from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow_job(path: str, job_name: str) -> dict:
    workflow = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    return workflow["jobs"][job_name]


def _allowed_endpoints(job: dict) -> set[str]:
    harden_runner = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("step-security/harden-runner@")
    )
    return set(harden_runner["with"]["allowed-endpoints"].split())


def test_local_trust_boundary_and_ci_security_guard_passes() -> None:
    completed = subprocess.run(
        ["python3", "scripts/check-local-trust-boundaries.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_secret_scan_can_be_required_by_ci_without_lying() -> None:
    script = (ROOT / "scripts" / "security" / "secret-scan.sh").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "scripts" / "security" / "install-gitleaks.sh").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8"
    )

    assert "REQUIRE_SECRET_SCANNER" in script
    assert 'REQUIRE_SECRET_SCANNER: "1"' in workflow
    assert "allowed-endpoints: |" not in workflow
    assert "allowed-endpoints: >" in workflow
    assert "expected_sha256=" in installer
    assert "sha256sum --check" in installer


def test_sbom_job_allows_setup_uv_download_endpoint() -> None:
    sbom_job = _workflow_job(".github/workflows/monorepo-ci.yml", "sbom")
    endpoints = _allowed_endpoints(sbom_job)
    assert {
        "raw.githubusercontent.com:443",
        "azure.archive.ubuntu.com:80",
        "security.ubuntu.com:80",
        "fulcio.sigstore.dev:443",
        "rekor.sigstore.dev:443",
        "timestamp.sigstore.dev:443",
        "tuf-repo-cdn.sigstore.dev:443",
    } <= endpoints
    media_install = next(
        step
        for step in sbom_job["steps"]
        if step.get("name") == "Install media tooling"
    )
    assert (
        media_install["run"]
        == "sudo apt-get install -y --no-install-recommends ffmpeg tesseract-ocr"
    )


def test_secret_scan_allows_trufflehog_container_registry() -> None:
    secret_scan_job = _workflow_job(".github/workflows/security.yml", "secrets")
    assert {
        "ghcr.io:443",
        "pkg-containers.githubusercontent.com:443",
    } <= _allowed_endpoints(secret_scan_job)


def test_trivy_allows_vulnerability_database_registry() -> None:
    trivy_job = _workflow_job(".github/workflows/security.yml", "trivy")
    assert {"mirror.gcr.io:443"} <= _allowed_endpoints(trivy_job)
