from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


capacity = _load_script("capacity_envelope_test_module", "capacity_envelope.py")
doctor = _load_script("capacity_doctor_test_module", "doctor.py")


def _valid_claim_receipt(*, creators: int = 10, assets: int = 10_000) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": capacity.SCHEMA,
        "tier": {
            "name": "test-exact-tier",
            "creators": creators,
            "assets": assets,
            "assetFiles": assets,
            "claimEligible": True,
        },
        "fixture": {
            "exact": True,
            "actualCounts": {
                "creators": creators,
                "assets": assets,
                "assetFiles": assets,
            },
        },
        "lanes": {
            name: {"name": name, "status": "passed", "evidence": {}}
            for name in capacity.MANDATORY_LANES
        },
        "thresholdEvaluation": {"passed": True},
        "supportClaim": {
            "supported": True,
            "largestSupportedTier": "test-exact-tier",
            "inferred": False,
        },
    }
    receipt["receiptFingerprint"] = capacity._fingerprint(receipt)
    return receipt


def test_exact_capacity_tier_definitions_cannot_be_inferred_from_smoke() -> None:
    assert capacity.CAPACITY_TIERS["smoke"] == capacity.CapacityTier(
        name="smoke",
        creators=2,
        assets=128,
        asset_files=128,
        claim_eligible=False,
    )
    assert (
        capacity.CAPACITY_TIERS["10-creators-10k-assets"].creators,
        capacity.CAPACITY_TIERS["10-creators-10k-assets"].assets,
    ) == (10, 10_000)
    assert (
        capacity.CAPACITY_TIERS["100-creators-100k-assets"].creators,
        capacity.CAPACITY_TIERS["100-creators-100k-assets"].assets,
    ) == (100, 100_000)
    assert (
        capacity.CAPACITY_TIERS["1000-creators-1m-assets"].creators,
        capacity.CAPACITY_TIERS["1000-creators-1m-assets"].assets,
    ) == (1_000, 1_000_000)
    assert capacity.CAPACITY_TIERS["smoke"].claim_eligible is False


def test_smoke_capacity_run_uses_real_isolated_state_and_atomic_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "capacity-workspace"

    receipt = capacity.run_capacity_benchmark(
        tier_name="smoke",
        workspace=workspace,
    )

    assert receipt["schema"] == capacity.SCHEMA
    assert receipt["fixture"]["exact"] is True
    assert receipt["fixture"]["actualCounts"] == {
        "accounts": 2,
        "assetBytes": 128 * capacity.ASSET_BYTES,
        "assetFiles": 128,
        "assets": 128,
        "campaigns": 2,
        "creators": 2,
    }
    run_root = Path(receipt["fixture"]["runRoot"])
    assert run_root.is_relative_to(workspace)
    assert not run_root.is_relative_to(ROOT)
    assert (run_root / "state/campaign_factory.sqlite").is_file(), (
        "real Campaign Factory SQLite fixture is required"
    )
    assert sum(1 for path in (run_root / "assets").rglob("*") if path.is_file()) == 128
    assert (run_root / "media/source.mp4").is_file()
    assert (run_root / "restore/state/campaign_factory.sqlite").is_file()

    assert set(receipt["lanes"]) == set(capacity.MANDATORY_LANES)
    for required_pass in (
        "database_fixture",
        "query_latency_index_use",
        "sqlite_contention",
        "filesystem_traversal",
        "sha_probe",
        "ffmpeg_throughput",
        "render_queue_throughput",
        "provider_queue_admission",
        "report_latency",
        "backup_restore",
        "failure_recovery",
    ):
        assert receipt["lanes"][required_pass]["status"] == "passed"
    assert receipt["lanes"]["contentforge_throughput"]["status"] in {
        "passed",
        "skipped",
    }
    assert receipt["externalEffects"] == {
        "paidProviderCalls": 0,
        "productionPathsTouched": False,
        "publishingEffects": 0,
    }
    assert receipt["supportClaim"] == {
        "supported": False,
        "largestSupportedTier": None,
        "inferred": False,
        "reason": "smoke_profile_is_never_claim_eligible",
    }
    assert capacity.capacity_claim_is_valid(receipt) is False

    receipt_path = run_root / "capacity-receipt.json"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert receipt["receiptFingerprint"] == capacity._fingerprint(
        {key: value for key, value in receipt.items() if key != "receiptFingerprint"}
    )

    with pytest.raises(FileExistsError, match="capacity_run_already_exists"):
        capacity.run_capacity_benchmark(
            tier_name="smoke",
            workspace=workspace,
        )


def test_capacity_claim_fails_closed_on_partial_skipped_or_inferred_evidence() -> None:
    receipt = _valid_claim_receipt()
    assert capacity.capacity_claim_is_valid(receipt) is True

    skipped = json.loads(json.dumps(receipt))
    skipped["lanes"]["contentforge_throughput"]["status"] = "skipped"
    skipped["receiptFingerprint"] = capacity._fingerprint(
        {key: value for key, value in skipped.items() if key != "receiptFingerprint"}
    )
    assert capacity.capacity_claim_is_valid(skipped) is False

    partial = json.loads(json.dumps(receipt))
    partial["fixture"]["actualCounts"]["assets"] -= 1
    partial["receiptFingerprint"] = capacity._fingerprint(
        {key: value for key, value in partial.items() if key != "receiptFingerprint"}
    )
    assert capacity.capacity_claim_is_valid(partial) is False

    inferred = json.loads(json.dumps(receipt))
    inferred["supportClaim"]["inferred"] = True
    inferred["receiptFingerprint"] = capacity._fingerprint(
        {key: value for key, value in inferred.items() if key != "receiptFingerprint"}
    )
    assert capacity.capacity_claim_is_valid(inferred) is False

    tampered = json.loads(json.dumps(receipt))
    tampered["tier"]["assets"] = 100_000
    assert capacity.capacity_claim_is_valid(tampered) is False


def test_capacity_paths_fail_closed_before_creating_state(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="capacity_workspace_overlaps_repository_or_runtime"
    ):
        capacity.run_capacity_benchmark(
            tier_name="smoke",
            workspace=ROOT / "capacity-never-create",
        )
    with pytest.raises(
        ValueError, match="capacity_receipt_must_not_be_written_inside_repository"
    ):
        capacity.run_capacity_benchmark(
            tier_name="smoke",
            workspace=tmp_path / "safe",
            receipt_path=ROOT / "capacity-never-write.json",
        )
    assert not (ROOT / "capacity-never-create").exists()
    assert not (ROOT / "capacity-never-write.json").exists()


def test_doctor_rejects_bare_or_tampered_measured_input_claims() -> None:
    receipt = _valid_claim_receipt(creators=10)
    scenario = {
        "creators": 10,
        "measured_inputs": True,
        "capacity_receipt": receipt,
    }
    assert doctor._scenario_capacity_receipt_valid(scenario) is True
    assert (
        doctor._scenario_capacity_receipt_valid(
            {"creators": 10, "measured_inputs": True}
        )
        is False
    )

    tampered = json.loads(json.dumps(scenario))
    tampered["capacity_receipt"]["fixture"]["actualCounts"]["assets"] -= 1
    assert doctor._scenario_capacity_receipt_valid(tampered) is False


def test_creator_os_capacity_command_is_exposed() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/creator-os"),
            "capacity",
            "benchmark",
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--tier" in completed.stdout
    assert "--workspace" in completed.stdout
