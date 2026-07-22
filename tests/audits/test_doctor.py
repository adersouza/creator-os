from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PATH = ROOT / "scripts" / "doctor.py"


spec = importlib.util.spec_from_file_location("creator_os_doctor", DOCTOR_PATH)
assert spec and spec.loader
doctor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = doctor
spec.loader.exec_module(doctor)


def test_default_run_covers_only_technical_audits() -> None:
    results = doctor.run_doctor(quick=True)

    assert len(results) == 15
    assert {result.name for result in results} == {
        "pipeline-determinism",
        "lineage",
        "quality-gates",
        "promotion",
        "learning",
        "data-provenance",
        "replay",
        "duplicate-intelligence",
        "performance",
        "resource",
        "failure-recovery",
        "configuration",
        "documentation",
        "technical-debt",
        "observability",
    }
    # Gate-duplicate audits were deleted; aspirational audits are gated behind
    # --business and must not appear in a plain default run.
    assert not {
        "architecture",
        "contracts",
        "dependencies",
        "security",
        "commercial-readiness",
        "ceo-dashboard",
        "chaos",
    } & {result.name for result in results}
    assert all(result.category for result in results)
    assert all(result.command for result in results)
    assert all(result.reason for result in results)
    assert all(result.next_action for result in results)


def test_live_status_keeps_unprobed_external_systems_not_run(tmp_path: Path) -> None:
    config = tmp_path / "performance-sync.env"
    config.write_text(
        'export CAMPAIGN_FACTORY_DB="/tmp/example.sqlite"\n'
        'export SUPABASE_SERVICE_ROLE_KEY="never-print-me"\n',
        encoding="utf-8",
    )

    values = doctor._read_env_assignments(config)

    assert values["CAMPAIGN_FACTORY_DB"] == "/tmp/example.sqlite"
    assert values["SUPABASE_SERVICE_ROLE_KEY"] == "never-print-me"
    results = doctor.run_live_status(home=tmp_path)
    provider = next(row for row in results if row.name == "provider-readiness")
    handshake = next(row for row in results if row.name == "threadsdashboard-handshake")
    assert provider.status == "NOT_RUN"
    assert handshake.status == "NOT_RUN"
    assert "never-print-me" not in provider.evidence


def test_canonical_roots_reject_campaign_artifacts_inside_checkout(
    tmp_path: Path,
) -> None:
    source = tmp_path / "creator-os"
    runtime = tmp_path / "creator-os-runtime"
    for path in (
        source,
        runtime,
        tmp_path / "state",
        tmp_path / "artifacts",
        tmp_path / "models",
        tmp_path / "logs",
    ):
        path.mkdir(parents=True)
    paths = doctor.resolve_runtime_paths(
        source,
        env={
            "HOME": str(tmp_path / "home"),
            "CREATOR_OS_RUNTIME_ROOT": str(runtime),
            "CREATOR_OS_STATE_ROOT": str(tmp_path / "state"),
            "CREATOR_OS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "CREATOR_OS_MODEL_ROOT": str(tmp_path / "models"),
            "CREATOR_OS_LOG_ROOT": str(tmp_path / "logs"),
        },
    )

    result = doctor._canonical_roots_status(
        paths, campaign_artifacts=source / "python_packages/campaign_factory/campaigns"
    )

    assert result.status == "FAIL"
    assert "campaignArtifacts=" in result.affected[0]


def test_venv_entrypoints_fail_when_bound_to_removed_worktree(tmp_path: Path) -> None:
    root = tmp_path / "creator-os"
    bin_root = root / ".venv" / "bin"
    bin_root.mkdir(parents=True)
    (bin_root / "pytest").write_text(
        "#!/tmp/deleted-worktree/.venv/bin/python\n",
        encoding="utf-8",
    )

    result = doctor._venv_entrypoint_status(root)

    assert result.status == "FAIL"
    assert result.affected == ["pytest: /tmp/deleted-worktree/.venv/bin/python"]
    assert "--reinstall" in result.next_action


def test_venv_entrypoints_pass_when_bound_to_current_checkout(tmp_path: Path) -> None:
    root = tmp_path / "creator-os"
    bin_root = root / ".venv" / "bin"
    bin_root.mkdir(parents=True)
    (bin_root / "pytest").write_text(
        f"#!{bin_root / 'python'}\n",
        encoding="utf-8",
    )

    result = doctor._venv_entrypoint_status(root)

    assert result.status == "PASS"
    assert result.affected == []


def test_live_status_records_shared_trace_and_zero_write_probe_results(
    tmp_path: Path, monkeypatch
) -> None:
    config_root = tmp_path / ".creator-os"
    config_root.mkdir()
    (config_root / "performance-sync.env").write_text("", encoding="utf-8")
    (config_root / "generation.env").write_text("", encoding="utf-8")
    campaign_ingest = config_root / "campaign-ingest.env"
    campaign_ingest.write_text(
        'export THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL="https://juno33.com/api/campaign-factory/drafts/ingest"\n'
        'export CAMPAIGN_FACTORY_INGEST_SECRET="never-print-me"\n',
        encoding="utf-8",
    )
    campaign_ingest.chmod(0o600)
    monkeypatch.setattr(
        doctor,
        "run_provider_probe",
        lambda **kwargs: {
            "status": "PASS",
            "traceId": kwargs["trace_id"],
            "providerCalls": 0,
            "costEventsCreated": 0,
        },
    )
    monkeypatch.setattr(
        doctor,
        "run_threadsdash_handshake",
        lambda **kwargs: {
            "status": "PASS",
            "traceId": kwargs["trace_id"],
            "productRowsWritten": 0,
        },
    )

    results = doctor.run_live_status(home=tmp_path, live_read_only=True)
    provider = next(row for row in results if row.name == "provider-readiness")
    handshake = next(row for row in results if row.name == "threadsdashboard-handshake")

    assert provider.status == "PASS"
    assert handshake.status == "PASS"
    assert (
        json.loads(provider.evidence)["traceId"]
        == json.loads(handshake.evidence)["traceId"]
    )
    assert "never-print-me" not in handshake.evidence


def test_business_only_runs_all_second_layer_audits() -> None:
    results = doctor.run_doctor(quick=True, business_only=True)

    assert len(results) == 31
    assert {result.name for result in results} == {
        "business-logic",
        "cross-system-consistency",
        "analytics-integrity",
        "ui-consistency",
        "business-state-machine",
        "data-drift",
        "recommendation",
        "regression",
        "cost",
        "human-override",
        "account-level",
        "campaign-health",
        "repository-health",
        "operator-experience",
        "chaos",
        "scaling",
        "product-quality",
        "ceo-dashboard",
        "release-readiness",
        "deployment",
        "backup-disaster-recovery",
        "secret-rotation",
        "oauth-authentication",
        "incident-response",
        "release-hygiene",
        "operational-ownership",
        "production-proof",
        "live-snapshot",
        "browser-runtime-proof",
        "release-gate",
        "commercial-readiness",
    }
    assert all(result.category for result in results)


def test_proof_inputs_pull_business_suite_into_default_run(tmp_path: Path) -> None:
    snapshot = tmp_path / "td-snapshot.json"
    snapshot.write_text(json.dumps({"drafts": []}), encoding="utf-8")

    # Without --business, a proof/release input must still run the second-layer
    # audits that read it, otherwise the flag would be a silent no-op.
    results = doctor.run_doctor(quick=True, td_snapshot=snapshot)
    names = {result.name for result in results}

    assert "cross-system-consistency" in names
    assert "pipeline-determinism" in names


def test_repo_hygiene_reads_only_real_local_branch_refs(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_command_check(command: list[str], timeout: int = 180):
        commands.append(command)
        if command[:2] == ["git", "status"]:
            return doctor.CommandResult(0, "## HEAD (no branch)\n", 0)
        if command[:2] == ["git", "for-each-ref"]:
            return doctor.CommandResult(0, "main\n", 0)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(doctor, "command_check", fake_command_check)

    assert doctor.repo_hygiene_warnings() == []
    assert [
        "git",
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
    ] in commands


def test_duplicate_fixture_detects_exact_hash_and_semantic_duplicates() -> None:
    fixture = doctor.load_fixture()
    result = doctor.duplicate_audit(fixture, True)

    assert result.status == "PASS"
    assert "hard launch energy" in result.affected
    assert "cap_a" in result.affected
    assert "asset_fixture_001::asset_fixture_002" in result.affected


def test_business_logic_fixture_checks_required_decision_rules() -> None:
    fixture = doctor.load_business_fixture()
    result = doctor.business_logic_audit(fixture, True)

    assert result.status == "PASS"
    assert "decision_001" in result.affected
    assert (
        "manual approval" in result.reason.lower()
        or "manual" in result.evidence.lower()
    )


def test_td_snapshot_can_turn_cross_system_consistency_pass(tmp_path: Path) -> None:
    snapshot = tmp_path / "td-snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "drafts": [
                    {
                        "draft_id": "draft_482",
                        "status": "validated",
                        "caption": "Hard launch energy.",
                        "media_hash": "sha256:media482",
                        "lineage_hash": "sha256:lineage482",
                        "account": "stacey_main",
                        "schedule": "2026-07-08T18:00:00-04:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    results = doctor.run_doctor(quick=True, business_only=True, td_snapshot=snapshot)
    result = next(row for row in results if row.name == "cross-system-consistency")

    assert result.status == "PASS"


def test_td_snapshot_mismatch_fails_cross_system_consistency(tmp_path: Path) -> None:
    snapshot = tmp_path / "td-snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "drafts": [
                    {
                        "draft_id": "draft_482",
                        "status": "draft",
                        "caption": "Hard launch energy.",
                        "media_hash": "sha256:media482",
                        "lineage_hash": "sha256:lineage482",
                        "account": "stacey_main",
                        "schedule": "2026-07-08T18:00:00-04:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    results = doctor.run_doctor(quick=True, business_only=True, td_snapshot=snapshot)
    result = next(row for row in results if row.name == "cross-system-consistency")

    assert result.status == "FAIL"
    assert "status" in result.reason


def test_linked_td_snapshot_can_turn_cross_system_consistency_pass(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "td-linked-snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-07T00:00:00Z",
                "drafts": [
                    {
                        "draft_id": "post_real_001",
                        "creator_os_external_id": "post_real_001",
                        "status": "scheduled",
                        "caption": "Real linked caption.",
                        "media_hash": "sha256:real-media",
                        "lineage_hash": "",
                        "lineage_key": "graph_real_001",
                        "account": "acct_001",
                        "schedule": "2026-07-08T18:00:00Z",
                        "creator_os": {
                            "caption": "Real linked caption.",
                            "media_hash": "sha256:real-media",
                        },
                        "threadsdashboard": {
                            "status": "scheduled",
                            "caption": "Real linked caption.",
                            "media_hash": "sha256:real-media",
                            "account": "acct_001",
                            "schedule": "2026-07-08T18:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    results = doctor.run_doctor(quick=True, business_only=True, td_snapshot=snapshot)
    result = next(row for row in results if row.name == "cross-system-consistency")

    assert result.status == "PASS"
    assert result.affected == ["post_real_001"]


def test_ui_proof_can_turn_ui_consistency_pass(tmp_path: Path) -> None:
    proof = tmp_path / "ui-proof.json"
    proof.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "route": route,
                        "viewport": {"width": 1440, "height": 1000},
                        "console_error_count": 0,
                        "visible_state_labels": ["Validated"],
                        "screenshot_path": f"/tmp/{route.strip('/')}.png",
                    }
                    for route in [
                        "/calendar",
                        "/composer",
                        "/links",
                        "/analytics",
                        "/reliability",
                    ]
                ]
            }
        ),
        encoding="utf-8",
    )

    results = doctor.run_doctor(quick=True, business_only=True, ui_proof=proof)
    result = next(row for row in results if row.name == "ui-consistency")

    assert result.status == "PASS"


def test_release_mode_fails_missing_proofs_and_scale_threshold() -> None:
    results = doctor.run_doctor(quick=True, business_only=True, release=True)
    by_name = {result.name: result for result in results}

    assert by_name["cross-system-consistency"].status == "FAIL"
    assert "snapshot" in by_name["cross-system-consistency"].reason.lower()
    assert by_name["ui-consistency"].status == "FAIL"
    assert "browser proof" in by_name["ui-consistency"].reason.lower()
    assert by_name["scaling"].status == "WARN"
    assert "utilization" in by_name["scaling"].reason.lower()


def test_release_mode_fails_missing_commercial_owner() -> None:
    fixture = deepcopy(doctor.load_fixture())
    fixture["_release"] = True
    fixture["commercial_readiness"]["operator_checklist"][0]["owner"] = ""

    result = doctor.commercial_readiness_audit(fixture, True)

    assert result.status == "FAIL"
    assert "missing owners" in result.reason
