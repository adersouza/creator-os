from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "creator-os"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_operator_help_has_no_generic_package_or_publish_escape_hatch() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "component" not in result.stdout
    assert "campaign-prepare" in result.stdout
    assert "generation-modes" in result.stdout
    assert "draft-export" in result.stdout
    assert "paid-generation" in result.stdout


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_paid_generation_requires_a_positive_finite_credit_cap(
    value: str, tmp_path: Path
) -> None:
    result = _run(
        "paid-generation",
        "--confirm-paid",
        "--target",
        "stacey",
        "--workspace",
        str(ROOT),
        "--campaign",
        "campaign",
        "--reference-image",
        str(tmp_path / "reference.png"),
        f"--max-credits={value}",
    )

    assert result.returncode == 2
    assert "finite and greater than zero" in result.stderr


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_static_reel_requires_a_positive_finite_duration(
    value: str, tmp_path: Path
) -> None:
    result = _run(
        "static-reel",
        "--dry-run",
        "--campaign",
        "campaign",
        "--still",
        str(tmp_path / "accepted.png"),
        f"--duration={value}",
    )

    assert result.returncode == 2
    assert "finite and greater than zero" in result.stderr


def test_draft_export_forces_draft_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    result = namespace["main"](
        [
            "draft-export",
            "--apply",
            "--campaign",
            "campaign",
            "--user-id",
            "user",
            "--max-drafts",
            "2",
        ]
    )

    assert result == 0
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("--schedule-mode") + 1] == "draft"
    assert "live" not in command
    assert "publish" not in " ".join(command)


def test_generation_modes_uses_read_only_campaign_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["generation-modes"]) == 0
    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "campaign-factory",
            "campaign-factory",
            "generation",
            "modes",
        ]
    ]
