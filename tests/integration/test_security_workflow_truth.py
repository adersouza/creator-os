from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
    workflow = (ROOT / ".github" / "workflows" / "monorepo-ci.yml").read_text(
        encoding="utf-8"
    )
    sbom_job = workflow.split("\n  sbom:\n", 1)[1]

    assert "raw.githubusercontent.com:443" in sbom_job
    assert "azure.archive.ubuntu.com:80" in sbom_job
    assert "security.ubuntu.com:80" in sbom_job
    assert (
        "sudo apt-get install -y --no-install-recommends ffmpeg tesseract-ocr"
        in sbom_job
    )


def test_secret_scan_allows_trufflehog_container_registry() -> None:
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8"
    )
    secret_scan_job = workflow.split("\n  secrets:\n", 1)[1].split(
        "\n  trivy:\n", 1
    )[0]

    assert "ghcr.io:443" in secret_scan_job
    assert "pkg-containers.githubusercontent.com:443" in secret_scan_job
