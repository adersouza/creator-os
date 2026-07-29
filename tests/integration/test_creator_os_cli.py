from __future__ import annotations

import json
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
    assert "create" in result.stdout
    assert "generate" not in result.stdout
    assert "export (draft-export)" in result.stdout
    for ordinary in ("create", "review", "approve", "export", "promote", "advanced"):
        assert ordinary in result.stdout
    for compatibility_diagnostic in (
        "local-models",
        "local-queue",
        "local-benchmarks",
        "approve-import",
        "motion-qc-register",
    ):
        assert compatibility_diagnostic not in result.stdout
    assert "paid-generation" not in result.stdout
    assert "static-reel" not in result.stdout


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


def test_status_and_doctor_use_the_exact_project_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["status", "--json", "--live-read-only"]) == 0
    assert namespace["main"](["doctor", "--", "--json"]) == 0
    assert commands == [
        [
            str(ROOT / ".venv" / "bin" / "python"),
            str(ROOT / "scripts" / "doctor.py"),
            "--status",
            "--json",
            "--live-read-only",
        ],
        [
            str(ROOT / ".venv" / "bin" / "python"),
            str(ROOT / "scripts" / "doctor.py"),
            "--json",
        ],
    ]


def test_audio_refresh_routes_to_bounded_audio_radar_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run

    assert (
        namespace["main"](
            [
                "audio",
                "refresh",
                "--region",
                "US",
                "--max-new",
                "10",
                "--max-active",
                "30",
                "--apply",
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
            "python",
            "-m",
            "campaign_factory.audio_radar.cli",
            "refresh",
            "--region",
            "US",
            "--max-new",
            "10",
            "--max-active",
            "30",
            "--apply",
        ]
    ]


def test_create_routes_mode_to_production_batch_without_internal_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    assert (
        namespace["main"](
            [
                "create",
                "--creator",
                "stacey",
                "--mode",
                "calm_animation",
                "--style",
                "passive_selfie",
                "--count",
                "4",
                "--execution",
                "cloud",
                "--accounts",
                "stacey-main",
            ]
        )
        == 0
    )
    command = commands[0]
    assert command[-17:] == [
        "create",
        "--creator",
        "stacey",
        "--mode",
        "calm_animation",
        "--style",
        "passive_selfie",
        "--count",
        "4",
        "--execution",
        "cloud",
        "--audio",
        "embedded_trending_required",
        "--reuse-policy",
        "prefer_exact",
        "--accounts",
        "stacey-main",
    ]
    assert "arena" not in " ".join(command)
    assert "evidence" not in " ".join(command)
    assert "deprecated" not in capsys.readouterr().err


def test_create_routes_reference_url_analysis_without_provider_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    assert (
        namespace["main"](
            [
                "create",
                "--creator",
                "stacey",
                "--mode",
                "recreate_reel",
                "--reference-url",
                "https://www.instagram.com/reel/DbQdqWFIvKQ/",
                "--recreate-mode",
                "structural",
                "--through",
                "analyze",
                "--reference-non-talking",
                "--reference-classification",
                "simple_pose_motion",
                "--audio",
                "auto",
            ]
        )
        == 0
    )
    command = commands[0]
    assert "--reference-url" in command
    assert command[command.index("--recreate-mode") + 1] == "structural"
    assert command[command.index("--through") + 1] == "analyze"
    assert "--reference-non-talking" in command
    assert (
        command[command.index("--reference-classification") + 1] == "simple_pose_motion"
    )
    assert "--apply" not in command
    assert "--soul-id" not in command


def test_export_is_canonical_and_draft_export_remains_deprecated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    common = [
        "--dry-run",
        "--campaign",
        "campaign",
        "--user-id",
        "user",
        "--max-drafts",
        "1",
    ]
    assert namespace["main"](["export", *common]) == 0
    assert "deprecated" not in capsys.readouterr().err
    assert namespace["main"](["draft-export", *common]) == 0
    assert "deprecated: use `creator-os export`" in capsys.readouterr().err
    assert len(commands) == 2


def test_advanced_analyzers_without_args_emits_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI))
    calls: list[tuple[list[str], Path, str | None]] = []

    def fake_run(
        command: list[str], *, cwd: Path = ROOT, input_text: str | None = None
    ) -> int:
        calls.append((command, cwd, input_text))
        return 0

    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["advanced", "analyzers"]) == 0
    assert len(calls) == 1
    command, cwd, input_text = calls[0]
    assert command == [
        "node",
        str(ROOT / "packages/contentforge/cli.mjs"),
        "analyzer-registry",
    ]
    assert cwd == ROOT
    assert input_text is not None
    assert set(json.loads(input_text)) == {"producedAt"}


@pytest.mark.parametrize(
    ("argument", "returncode", "stream", "expected"),
    [
        ("--help", 0, "stdout", "usage: creator-os advanced analyzers"),
        ("--unknown", 2, "stderr", "unrecognized arguments: --unknown"),
    ],
)
def test_advanced_analyzers_parses_diagnostic_arguments(
    argument: str, returncode: int, stream: str, expected: str
) -> None:
    result = _run("advanced", "analyzers", argument)

    assert result.returncode == returncode
    assert expected in getattr(result, stream)
    assert "analyzerRegistry" not in result.stdout


@pytest.mark.parametrize("mode", ["--dry-run", "--apply"])
def test_advanced_evidence_key_routes_only_to_core_initializer(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["advanced", "evidence-key", "init", mode]) == 0
    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "creator-os-core",
            "python",
            "-m",
            "creator_os_core.evidence_attestation",
            "init",
            mode,
        ]
    ]


def test_approve_routes_exact_review_builder_to_campaign_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    root = tmp_path / "approvals"
    assert (
        namespace["main"](
            [
                "approve",
                "--campaign",
                "may",
                "--rendered-asset-id",
                "asset-1",
                "--user-id",
                "user-1",
                "--approved-by",
                "operator",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert "creative-approval-build" in commands[0]
    assert commands[0][-4:] == [
        "--surface",
        "regular_reel",
        "--root",
        str(root.resolve()),
    ]


def test_approve_import_is_explicitly_compatibility_labeled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    namespace["main"].__globals__["_run"] = fake_run
    approval = tmp_path / "approval.json"
    assert namespace["main"](["approve-import", "--approval", str(approval)]) == 0
    assert "deprecated: use `creator-os advanced approval-import`" in (
        capsys.readouterr().err
    )
    assert "campaign_factory.creative_approval" in commands[0]


def test_promote_routes_to_contract_validated_entrypoint_in_dry_run(
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
    assert "campaign_factory.runtime_promotion_entrypoint" in command
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
    ("surface", "module", "uv_options"),
    [
        (
            "identity",
            "reel_factory.identity_verification",
            [
                "--isolated",
                "--offline",
                "--locked",
                "--all-packages",
                "--extra",
                "identity",
            ],
        ),
    ],
)
def test_contract_aware_advanced_surfaces_use_the_full_workspace_environment(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    module: str,
    uv_options: list[str],
) -> None:
    namespace = runpy.run_path(str(CLI))
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path = ROOT) -> int:
        commands.append(command)
        return 0

    monkeypatch.setitem(namespace, "_run", fake_run)
    namespace["main"].__globals__["_run"] = fake_run

    assert namespace["main"](["advanced", surface, "--help"]) == 0
    assert commands == [
        [
            "uv",
            "run",
            *uv_options,
            "python",
            "-m",
            module,
            "--help",
        ]
    ]


def test_motion_qc_register_routes_exact_asset_and_receipt_to_campaign_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
    assert "deprecated: use `creator-os advanced motion-qc-register`" in (
        capsys.readouterr().err
    )
