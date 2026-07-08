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


def test_doctor_runs_all_fifty_audits_in_quick_mode() -> None:
    results = doctor.run_doctor(quick=True)

    assert len(results) == 50
    assert {result.name for result in results} == {
        "architecture",
        "pipeline-determinism",
        "contracts",
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
        "dependencies",
        "security",
        "documentation",
        "technical-debt",
        "observability",
        "commercial-readiness",
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
    }
    assert all(result.category for result in results)
    assert all(result.command for result in results)
    assert all(result.reason for result in results)
    assert all(result.next_action for result in results)


def test_business_only_runs_all_second_layer_audits() -> None:
    results = doctor.run_doctor(quick=True, business_only=True)

    assert len(results) == 30
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
    }
    assert all(result.category for result in results)


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
    assert by_name["scaling"].status == "FAIL"
    assert "utilization" in by_name["scaling"].reason.lower()


def test_release_mode_fails_missing_commercial_owner() -> None:
    fixture = deepcopy(doctor.load_fixture())
    fixture["_release"] = True
    fixture["commercial_readiness"]["operator_checklist"][0]["owner"] = ""

    result = doctor.commercial_readiness_audit(fixture, True)

    assert result.status == "FAIL"
    assert "missing owners" in result.reason
