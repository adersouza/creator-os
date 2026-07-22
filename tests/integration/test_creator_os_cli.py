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
    assert "campaign-prepare" not in result.stdout
    assert "generate" in result.stdout
    assert "draft-export" in result.stdout
    for ordinary in ("create", "review", "approve", "export", "promote", "advanced"):
        assert ordinary in result.stdout
    assert "paid-generation" not in result.stdout
    assert "static-reel" not in result.stdout


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_wavespeed_generation_requires_a_positive_finite_usd_cap(
    value: str, tmp_path: Path
) -> None:
    result = _run(
        "generate",
        "--mode",
        "best_motion",
        "--apply",
        "--confirm-paid",
        "--workspace",
        str(ROOT),
        "--campaign",
        "campaign",
        "--accepted-still",
        str(tmp_path / "accepted.png"),
        "--motion-prompt",
        "Natural breathing and a gentle camera push toward the subject",
        f"--max-usd={value}",
    )

    assert result.returncode == 2
    assert "finite and greater than zero" in result.stderr


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_static_reel_requires_a_positive_finite_duration(
    value: str, tmp_path: Path
) -> None:
    result = _run(
        "generate",
        "--mode",
        "soul_static",
        "--dry-run",
        "--campaign",
        "campaign",
        "--accepted-still",
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


def test_generate_list_modes_uses_read_only_campaign_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["generate", "--list-modes"]) == 0
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


def test_create_alias_routes_to_the_existing_campaign_control_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    assert namespace["main"](["create", "--list-modes"]) == 0
    assert commands[0][-2:] == ["generation", "modes"]


def test_advanced_queue_keeps_diagnostics_without_a_second_control_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    assert namespace["main"](["advanced", "queue", "status"]) == 0
    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "reel-factory",
            "python",
            "-m",
            "reel_factory.local_generation_queue",
            "status",
        ]
    ]


def test_approve_routes_one_exact_record_to_campaign_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    approval = tmp_path / "approval.json"
    root = tmp_path / "approvals"
    assert (
        namespace["main"](["approve", "--approval", str(approval), "--root", str(root)])
        == 0
    )
    assert commands[0][-4:] == [
        "--approval",
        str(approval.resolve()),
        "--root",
        str(root.resolve()),
    ]


def test_promote_routes_to_guarded_core_module_in_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    commit = "a" * 40
    approval = tmp_path / "approval.json"
    runtime_root = tmp_path / "creator-os-runtime"
    assert (
        namespace["main"](
            [
                "promote",
                "--runtime-root",
                str(runtime_root),
                "--approved-commit",
                commit,
                "--approval",
                str(approval),
                "--operator",
                "operator",
                "--dry-run",
            ]
        )
        == 0
    )
    command = commands[0]
    assert "creator_os_core.runtime_promotion" in command
    assert command[command.index("--runtime-root") + 1] == str(runtime_root.resolve())
    assert command[-1] == "--dry-run"


def test_promote_requires_an_explicit_runtime_checkout() -> None:
    namespace = runpy.run_path(str(CLI))

    with pytest.raises(SystemExit, match="2"):
        namespace["main"](
            [
                "promote",
                "--approved-commit",
                "a" * 40,
                "--approval",
                "/tmp/approval.json",
                "--operator",
                "operator",
                "--dry-run",
            ]
        )


@pytest.mark.parametrize(
    ("operator_command", "module", "forwarded"),
    [
        (
            "local-queue",
            "reel_factory.local_generation_queue",
            ["status"],
        ),
        (
            "local-benchmarks",
            "reel_factory.local_model_benchmark",
            ["status"],
        ),
    ],
)
def test_local_operator_surfaces_route_only_to_reel_factory_modules(
    monkeypatch: pytest.MonkeyPatch,
    operator_command: str,
    module: str,
    forwarded: list[str],
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"]([operator_command, *forwarded]) == 0
    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "reel-factory",
            "python",
            "-m",
            module,
            *forwarded,
        ]
    ]


def test_motion_qc_register_routes_exact_asset_and_receipt_to_campaign_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run
    receipt = tmp_path / "motion-qc.json"

    assert (
        namespace["main"](
            [
                "motion-qc-register",
                "--rendered-asset-id",
                "asset_motion_1",
                "--receipt",
                str(receipt),
                "--operator",
                "operator_1",
            ]
        )
        == 0
    )
    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "campaign-factory",
            "campaign-factory",
            "register-motion-qc-receipt",
            "--rendered-asset-id",
            "asset_motion_1",
            "--receipt",
            str(receipt.resolve()),
            "--operator",
            "operator_1",
        ]
    ]


def test_generate_requires_explicit_mode() -> None:
    result = _run("generate", "--dry-run", "--campaign", "campaign")

    assert result.returncode == 2
    assert "--mode MODE | --list-modes" in result.stderr


def test_generate_routes_explicit_mode_to_campaign_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    assert (
        namespace["main"](
            [
                "generate",
                "--mode",
                "reference_video_remix",
                "--dry-run",
                "--campaign",
                "campaign",
                "--reference-video",
                str(tmp_path / "reference.mp4"),
                "--target",
                "Stacey",
                "--soul-id",
                "soul_1",
                "--workspace",
                str(ROOT),
            ]
        )
        == 0
    )
    command = commands[0]
    assert command[:6] == [
        "uv",
        "run",
        "--package",
        "campaign-factory",
        "campaign-factory",
        "generation",
    ]
    assert command[6:10] == ["run", "--mode", "reference_video_remix", "--campaign"]


def test_generate_forwards_exact_wavespeed_model_and_spend_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run
    assert (
        namespace["main"](
            [
                "generate",
                "--mode",
                "best_motion",
                "--dry-run",
                "--campaign",
                "campaign",
                "--accepted-still",
                str(tmp_path / "accepted.jpg"),
                "--motion-model",
                "wavespeed_wan27_i2v_pro",
                "--motion-prompt",
                "Natural breathing and a gentle camera push toward the subject",
                "--resolution",
                "1080p",
                "--duration",
                "5",
                "--seed",
                "71",
                "--max-usd",
                "0.60",
            ]
        )
        == 0
    )
    command = commands[0]
    assert command[command.index("--motion-model") + 1] == ("wavespeed_wan27_i2v_pro")
    assert command[command.index("--max-usd") + 1] == "0.6"
    assert command[command.index("--seed") + 1] == "71"
    assert "--dry-run" in command
    assert "publish" not in " ".join(command)
