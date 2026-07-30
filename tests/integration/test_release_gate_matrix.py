from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_classes_and_gates_are_inferred_from_changed_paths() -> None:
    module = _module()
    matrix = module.load_matrix()
    assert set(matrix["releaseClasses"]) == {
        "documentation_only",
        "local_logic",
        "schema_change",
        "migration",
        "provider_adapter",
        "paid_provider_route",
        "creator_identity_change",
        "consent_privacy_change",
        "runtime_promotion",
        "historical_data_repair",
    }
    assert {
        gate
        for definition in matrix["releaseClasses"].values()
        for gates in definition["mandatoryGates"].values()
        for gate in gates
    } == {
        "focused_tests",
        "make_affected",
        "pnpm_check_all",
        "make_verify",
        "make_release",
        "make_exhaustive",
        "migration_fixtures",
        "runtime_verification",
        "backup",
        "restore",
        "security_scans",
        "live_read_only_checks",
        "controlled_paid_pilot",
        "contract_sync",
        "contract_check",
    }

    classes = module.infer_release_classes(
        [
            ".github/workflows/monorepo-ci.yml",
            "python_packages/campaign_factory/campaign_factory/campaign_schema_v7.py",
        ],
        matrix,
    )

    assert classes == [
        "local_logic",
        "migration",
        "runtime_promotion",
        "schema_change",
    ]
    gates = module.required_gates(classes, matrix)
    assert {"make_affected", "migration_fixtures", "security_scans"} <= set(
        gates["pull_request"]
    )
    assert {"backup", "restore", "runtime_verification"} <= set(gates["promotion"])


def test_pull_request_cannot_claim_merge_promotion_or_operational_proof() -> None:
    module = _module()
    matrix = module.load_matrix()

    with pytest.raises(module.GateError, match="post-merge/runtime proof"):
        module.validate_declarations(
            inferred=["local_logic"],
            declared=["local_logic"],
            claims=["implemented", "runtime_promoted"],
            matrix=matrix,
        )


def test_release_receipt_is_deterministic_and_binds_exact_head() -> None:
    module = _module()
    matrix = module.load_matrix()
    values = {
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "paths": ["scripts/release_gate.py"],
        "declared": ["local_logic"],
        "inferred": ["local_logic"],
        "claims": ["focused_verified", "implemented"],
        "matrix": matrix,
    }

    first = module.build_receipt(**values)
    second = module.build_receipt(**values)

    assert first == second
    assert first["headSha"] == "b" * 40
    assert len(first["fingerprint"]) == 64
