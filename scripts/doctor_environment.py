"""Read-only repository and runtime-environment checks for ``doctor.py``."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from creator_os_core.runtime_paths import RuntimePaths
from doctor_types import Result


def _canonical_roots_status(
    paths: RuntimePaths, *, campaign_artifacts: Path | None = None
) -> Result:
    roots = {
        "state": paths.state_root,
        "artifacts": paths.artifact_root,
        "models": paths.model_root,
        "logs": paths.log_root,
    }
    checkout_roots = (paths.source_root, paths.runtime_root)
    unsafe = [
        f"{name}={path}"
        for name, path in roots.items()
        if any(path == root or path.is_relative_to(root) for root in checkout_roots)
    ]
    missing = [f"{name}={path}" for name, path in roots.items() if not path.is_dir()]
    database_paths = {
        "campaign": paths.campaign_factory_db,
        "reference": paths.reference_factory_db,
        "reelManifest": paths.reel_manifest_db,
        "renderQueue": paths.reel_render_queue_db,
    }
    checkout_databases = [
        f"{name}={path}"
        for name, path in database_paths.items()
        if any(path == root or path.is_relative_to(root) for root in checkout_roots)
    ]
    configured_artifacts = campaign_artifacts or (
        paths.artifact_root / "campaign_factory" / "campaigns"
    )
    checkout_artifacts = [
        f"campaignArtifacts={configured_artifacts}"
        for root in checkout_roots
        if configured_artifacts == root or configured_artifacts.is_relative_to(root)
    ]
    if unsafe or checkout_databases or checkout_artifacts:
        status = "FAIL"
        reason = "one or more canonical runtime paths resolve inside a Git checkout"
    elif missing:
        status = "NOT_RUN"
        reason = "canonical roots are configured but have not all been created"
    else:
        status = "PASS"
        reason = "canonical runtime roots exist outside source and runtime checkouts"
    return Result(
        name="canonical-roots",
        category="Runtime state roots",
        status=status,
        reason=reason,
        command="creator-os status",
        evidence="\n".join(
            [
                *(f"{name}={path}" for name, path in roots.items()),
                *(f"{name}Db={path}" for name, path in database_paths.items()),
                f"campaignArtifacts={configured_artifacts}",
            ]
        ),
        affected=[*unsafe, *checkout_databases, *checkout_artifacts, *missing],
        next_action=(
            "Run the verified state migration before switching runtime configuration."
            if status != "PASS"
            else "None."
        ),
    )


def _repository_status(root: Path) -> Result:
    branch = _git_output(root, "branch", "--show-current")
    sha = _git_output(root, "rev-parse", "HEAD")
    dirty = _git_output(root, "status", "--short")
    if not sha:
        status = "FAIL"
        reason = "source checkout is not readable as a Git repository"
    elif dirty:
        status = "WARN"
        reason = "source checkout has uncommitted changes"
    else:
        status = "PASS"
        reason = "source checkout is clean and its exact revision is known"
    return Result(
        name="repository",
        category="Repository",
        status=status,
        reason=reason,
        command="git status --short --branch",
        evidence=f"root={root}\nbranch={branch or '(detached)'}\nsha={sha or 'unknown'}",
        affected=dirty.splitlines()[:8] if dirty else [],
        next_action="Commit or deliberately discard the listed changes."
        if dirty
        else "None.",
    )


def _venv_entrypoint_status(root: Path) -> Result:
    """Detect executable wrappers whose shebang points at another checkout."""
    bin_root = root / ".venv" / "bin"
    if not bin_root.is_dir():
        return Result(
            name="venv-entrypoints",
            category="Python environment",
            status="NOT_RUN",
            reason="the repository virtual environment is absent",
            command="creator-os status",
            evidence=f"venv={root / '.venv'}",
            next_action="Run `uv sync --all-packages --all-extras --group dev`.",
        )

    expected_venv = (root / ".venv").resolve()
    stale: list[str] = []
    inspected = 0
    for path in sorted(bin_root.iterdir()):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                first_line = (
                    stream.readline(4096).decode("utf-8", errors="replace").strip()
                )
        except OSError:
            continue
        if not first_line.startswith("#!"):
            continue
        inspected += 1
        interpreter = first_line[2:].split(maxsplit=1)[0]
        if not interpreter.startswith("/") or ".venv" not in interpreter:
            continue
        interpreter_path = Path(interpreter)
        in_current_venv = interpreter_path.is_relative_to(expected_venv)
        if not in_current_venv:
            stale.append(f"{path.name}: {interpreter}")

    return Result(
        name="venv-entrypoints",
        category="Python environment",
        status="FAIL" if stale else "PASS",
        reason=(
            "virtual-environment entry points reference another checkout"
            if stale
            else "virtual-environment entry points are bound to this checkout"
        ),
        command="creator-os status",
        evidence=f"venv={expected_venv}\nshebangs_inspected={inspected}",
        affected=stale[:20],
        next_action=(
            "Run `uv sync --all-packages --all-extras --group dev --reinstall`."
            if stale
            else "None."
        ),
    )


def _contracts_status(root: Path) -> Result:
    checked = subprocess.run(
        ["node", "scripts/generate-pipeline-contract-schemas.mjs", "--check"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    ok = checked.returncode == 0
    return Result(
        name="contracts",
        category="Contracts",
        status="PASS" if ok else "FAIL",
        reason="generated contracts match canonical schemas"
        if ok
        else "generated contracts drift from canonical schemas",
        command="pnpm check:contracts",
        evidence=_tail(checked.stdout, limit=4),
        next_action="Run `pnpm sync:contracts`, inspect the diff, and recheck."
        if not ok
        else "None.",
    )


def _local_config_status(*files: Path) -> Result:
    missing = [str(path) for path in files if not path.is_file()]
    unsafe = [
        str(path) for path in files if path.is_file() and path.stat().st_mode & 0o077
    ]
    if missing:
        status = "WARN"
        reason = "one or more machine-local configuration files are absent"
    elif unsafe:
        status = "FAIL"
        reason = "machine-local configuration permissions are broader than 0600"
    else:
        status = "PASS"
        reason = "required machine-local config files exist with private permissions"
    return Result(
        name="local-config",
        category="Local config",
        status=status,
        reason=reason,
        command="creator-os status",
        evidence="\n".join(
            f"{path}: present={path.is_file()} mode={oct(path.stat().st_mode & 0o777) if path.exists() else 'missing'}"
            for path in files
        ),
        affected=missing + unsafe,
        next_action="Create missing files locally or restrict them to mode 0600."
        if missing or unsafe
        else "None.",
    )


def _runtime_status(
    paths: RuntimePaths, performance_values: dict[str, str], ops_log: Path
) -> Result:
    root = paths.runtime_root
    sha = _git_output(root, "rev-parse", "HEAD") if root.is_dir() else ""
    branch = _git_output(root, "branch", "--show-current") if sha else ""
    dirty = _git_output(root, "status", "--short") if sha else ""
    source_sha = _git_output(paths.source_root, "rev-parse", "HEAD")
    last_line = _latest_matching_line(ops_log, "performance-sync")
    if not sha:
        status = "NOT_RUN"
        reason = "runtime checkout is absent or not a readable Git checkout"
    elif dirty:
        status = "FAIL"
        reason = "runtime checkout contains uncommitted or untracked files"
    elif not source_sha or sha != source_sha:
        status = "WARN"
        reason = "runtime checkout does not match the reviewed source revision"
    elif not last_line:
        status = "WARN"
        reason = "runtime revision is known, but no performance-sync run is recorded"
    elif "[info]" in last_line and "ok" in last_line:
        status = "PASS"
        reason = "runtime revision is known and the latest recorded sync succeeded"
    else:
        status = "WARN"
        reason = "runtime revision is known, but the latest recorded sync did not prove success"
    campaign = performance_values.get(
        "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS", "not configured"
    )
    db_path = performance_values.get("CAMPAIGN_FACTORY_DB", "not configured")
    last_run = last_line.split(" ", 1)[0] if last_line else "not recorded"
    exit_status = (
        "0"
        if last_line and "[info]" in last_line and "ok" in last_line
        else "unknown/not successful"
    )
    return Result(
        name="runtime",
        category="Runtime checkout",
        status=status,
        reason=reason,
        command="creator-os status",
        evidence=(
            f"checkout={root}\nbranch={branch or '(detached/not available)'}\n"
            f"source_sha={source_sha or 'unknown'}\nruntime_sha={sha or 'unknown'}\n"
            f"clean={not bool(dirty)}\ndatabase={db_path}\ncampaigns={campaign}\n"
            f"last_run={last_run}\nexit_status={exit_status}\nlog={ops_log}"
        ),
        affected=dirty.splitlines()[:8] if dirty else [],
        next_action="Repair or run the pinned runtime job before claiming operational health."
        if status != "PASS"
        else "None.",
    )


def _campaign_database_status(values: dict[str, str]) -> Result:
    raw_path = values.get("CAMPAIGN_FACTORY_DB") or os.environ.get(
        "CAMPAIGN_FACTORY_DB"
    )
    campaigns_raw = values.get("CAMPAIGN_FACTORY_SYNC_CAMPAIGNS") or os.environ.get(
        "CAMPAIGN_FACTORY_SYNC_CAMPAIGNS", ""
    )
    if not raw_path:
        return Result(
            name="campaign-database",
            category="Campaign database",
            status="NOT_RUN",
            reason="no runtime campaign database path is configured",
            command="creator-os status",
            evidence="CAMPAIGN_FACTORY_DB is absent",
            next_action="Configure the runtime database path before checking it.",
        )
    path = Path(raw_path).expanduser()
    campaigns = _json_string_list(campaigns_raw)
    if not path.is_file():
        return Result(
            name="campaign-database",
            category="Campaign database",
            status="FAIL",
            reason="configured campaign database does not exist",
            command="creator-os status",
            evidence=f"database={path}\ncampaigns={campaigns or 'not configured'}",
            affected=[str(path)],
            next_action="Correct CAMPAIGN_FACTORY_DB; do not create a replacement implicitly.",
        )
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            present = []
            if "campaigns" in tables:
                for campaign in campaigns:
                    row = conn.execute(
                        "SELECT 1 FROM campaigns WHERE slug = ? LIMIT 1", (campaign,)
                    ).fetchone()
                    if row:
                        present.append(campaign)
    except sqlite3.Error as exc:
        return Result(
            name="campaign-database",
            category="Campaign database",
            status="FAIL",
            reason="configured campaign database is not readable in read-only mode",
            command="creator-os status",
            evidence=f"database={path}\nerror={exc}",
            next_action="Repair or restore the configured database before using it.",
        )
    missing = [campaign for campaign in campaigns if campaign not in present]
    status = "PASS" if "campaigns" in tables and not missing else "WARN"
    return Result(
        name="campaign-database",
        category="Campaign database",
        status=status,
        reason="database is readable and configured campaigns exist"
        if status == "PASS"
        else "database is readable but configured campaign evidence is incomplete",
        command="creator-os status",
        evidence=(
            f"database={path}\ntables={len(tables)}\n"
            f"configured_campaigns={campaigns}\npresent_campaigns={present}"
        ),
        affected=missing,
        next_action="Add or correct the configured campaign scope."
        if status != "PASS"
        else "None.",
    )


def _read_env_assignments(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        values[key] = value.strip().strip('"').strip("'")
    return values


def _json_string_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _latest_matching_line(path: Path, needle: str) -> str:
    if not path.is_file():
        return ""
    lines = [
        line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if needle in line
    ]
    return lines[-1] if lines else ""


def _tail(value: str, *, limit: int) -> str:
    return "\n".join(value.strip().splitlines()[-limit:])
