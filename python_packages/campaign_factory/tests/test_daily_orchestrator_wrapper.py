import os
import subprocess
from pathlib import Path


def test_campaign_factory_wrapper_loads_threadsdash_ingest_environment(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL\"\n"
        "printf '%s\\n' \"$CAMPAIGN_FACTORY_INGEST_SECRET\"\n"
        "printf '%s\\n' \"$@\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    generation_env = tmp_path / "generation.env"
    generation_env.write_text(
        "HIGGSFIELD_DAILY_BUDGET_CREDITS=0\n"
        "HIGGSFIELD_MONTHLY_BUDGET_CREDITS=0\n"
        "HIGGSFIELD_RUN_MAX_ASSETS=0\n"
        "HIGGSFIELD_RUN_MAX_CREDITS=0\n"
        "HIGGSFIELD_COHORT_MAX_CREDITS=0\n"
        "HIGGSFIELD_MIN_BALANCE_CREDITS=0\n"
        "HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS=0\n",
        encoding="utf-8",
    )
    ingest_env = tmp_path / "campaign-ingest.env"
    ingest_env.write_text(
        "THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL=https://juno33.com/api/campaign-factory/drafts/ingest\n"
        "CAMPAIGN_FACTORY_INGEST_SECRET=test-secret\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "CREATOR_OS_RUNTIME_ROOT": str(tmp_path),
        "CREATOR_OS_GENERATION_ENV": str(generation_env),
        "CREATOR_OS_CAMPAIGN_INGEST_ENV": str(ingest_env),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    env.pop("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL", None)
    env.pop("CAMPAIGN_FACTORY_INGEST_SECRET", None)

    result = subprocess.run(
        [str(root / "scripts" / "run_campaign_factory.sh"), "status"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "https://juno33.com/api/campaign-factory/drafts/ingest",
        "test-secret",
        "run",
        "campaign-factory",
        "status",
    ]


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
