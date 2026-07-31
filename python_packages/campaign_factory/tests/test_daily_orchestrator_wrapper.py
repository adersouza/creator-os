import os
import subprocess
from pathlib import Path


def test_daily_orchestrator_wrapper_is_fail_closed_and_non_publishing(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "run_daily_orchestrator.sh"
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    fake_runner = fake_scripts / "run_campaign_factory.sh"
    fake_runner.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_runner.chmod(0o755)

    env = {
        **os.environ,
        "CREATOR_OS_RUNTIME_ROOT": str(tmp_path),
        "CREATOR_OS_DAILY_ORCHESTRATOR_RUN_KEY": "2026-07-31",
    }
    result = subprocess.run(
        [str(script)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "orchestrate-daily",
        "--run-key",
        "2026-07-31",
        "--max-items",
        "3",
        "--per-creator-cap",
        "1",
        "--per-campaign-cap",
        "1",
        "--provider-cap",
        "0",
    ]


def test_daily_orchestrator_wrapper_rejects_unknown_mode(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [str(root / "scripts" / "run_daily_orchestrator.sh")],
        env={
            **os.environ,
            "CREATOR_OS_RUNTIME_ROOT": str(tmp_path),
            "CREATOR_OS_DAILY_ORCHESTRATOR_MODE": "publish",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "must be preview, plan, or execute" in result.stderr
