#!/usr/bin/env python3
"""Read-only Creator OS audit runner."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))
sys.path.insert(0, str(ROOT / "packages/pipeline_contracts"))
sys.path.insert(0, str(ROOT / "python_packages/campaign_factory"))

from campaign_factory.adapters.threadsdash_handshake import (
    configured_handshake_url,
    run_threadsdash_handshake,
)
from campaign_factory.provider_probe import run_provider_probe
from creator_os_core.runtime_paths import RuntimePaths, resolve_runtime_paths
from doctor_environment import (
    _campaign_database_status,
    _canonical_roots_status,
    _contracts_status,
    _local_config_status,
    _read_env_assignments,
    _repository_status,
    _runtime_status,
    _venv_entrypoint_status,
)
from doctor_types import Result

FIXTURE = ROOT / "tests/fixtures/doctor/creator_os_audit_fixture.json"
BUSINESS_FIXTURE = ROOT / "tests/fixtures/doctor/creator_os_business_audit_fixture.json"

CURRENT_DOC_ROOTS = (
    ROOT / "README.md",
    ROOT / "CREATOR_OS_SYSTEM_MAP.md",
    ROOT / "PIPELINE_STATE.md",
    ROOT / "AGENTS.md",
    ROOT / "docs",
)
IGNORED_PARTS = {
    ".git",
    ".venv",
    ".uv-cache",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".next",
    "dist",
    "build",
    "coverage",
    "graphify-out",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--quick", action="store_true", help="skip expensive command-backed checks"
    )
    parser.add_argument(
        "--business", action="store_true", help="run only business/product audits"
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="fail release-blocking maturity gates instead of reporting WARN-only gaps",
    )
    parser.add_argument(
        "--td-snapshot",
        default=os.environ.get("CREATOR_OS_TD_SNAPSHOT"),
        help="read-only ThreadsDashboard draft snapshot JSON",
    )
    parser.add_argument(
        "--ui-proof",
        default=os.environ.get("CREATOR_OS_UI_PROOF"),
        help="read-only ThreadsDashboard browser proof JSON",
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run script self-checks"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="report read-only live repository/runtime status instead of fixture audits",
    )
    parser.add_argument(
        "--live-read-only",
        action="store_true",
        help="run only explicitly configured zero-write external probes with status",
    )
    args = parser.parse_args()
    if args.self_check:
        return self_check()

    results = (
        run_live_status(live_read_only=args.live_read_only)
        if args.status
        else run_doctor(
            quick=args.quick,
            business_only=args.business,
            td_snapshot=args.td_snapshot,
            ui_proof=args.ui_proof,
            release=args.release,
        )
    )
    if args.json:
        print(
            json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)
        )
    else:
        print_text(results)
    return 1 if any(result.status == "FAIL" for result in results) else 0


def run_live_status(
    *,
    paths: RuntimePaths | None = None,
    home: Path | None = None,
    live_read_only: bool = False,
) -> list[Result]:
    """Return live, read-only status without treating unprobed systems as healthy."""
    resolved = paths or resolve_runtime_paths(ROOT)
    home_root = home or Path.home()
    config_root = home_root / ".creator-os"
    performance_env = config_root / "performance-sync.env"
    generation_env = config_root / "generation.env"
    campaign_ingest_env = config_root / "campaign-ingest.env"
    ops_log = config_root / "ops.log"
    performance_values = _read_env_assignments(performance_env)
    generation_values = _read_env_assignments(generation_env)
    campaign_ingest_values = _read_env_assignments(campaign_ingest_env)
    probe_env = {
        **os.environ,
        **performance_values,
        **generation_values,
        **campaign_ingest_values,
    }
    trace_id = f"trace_{uuid.uuid4().hex}"

    repository = _repository_status(resolved.source_root)
    venv_entrypoints = _venv_entrypoint_status(resolved.source_root)
    contracts = _contracts_status(resolved.source_root)
    local_config = _local_config_status(
        performance_env, generation_env, campaign_ingest_env
    )
    configured_campaigns_dir = (
        Path(
            probe_env.get("CAMPAIGN_FACTORY_CAMPAIGNS")
            or resolved.artifact_root / "campaign_factory" / "campaigns"
        )
        .expanduser()
        .resolve()
    )
    canonical_roots = _canonical_roots_status(
        resolved, campaign_artifacts=configured_campaigns_dir
    )
    runtime = _runtime_status(resolved, performance_values, ops_log)
    database = _campaign_database_status(performance_values)
    if live_read_only:
        provider = _provider_probe_status(resolved, trace_id=trace_id)
        handshake = _threadsdash_handshake_status(
            resolved, probe_env=probe_env, trace_id=trace_id
        )
    else:
        provider = Result(
            name="provider-readiness",
            category="Provider readiness",
            status="NOT_RUN",
            reason="zero-generation provider probe was not requested",
            command="creator-os status --live-read-only",
            evidence=f"requested=false; trace_id={trace_id}",
            next_action="Run the explicit live-read-only status command when needed.",
        )
        handshake = Result(
            name="threadsdashboard-handshake",
            category="ThreadsDashboard handshake",
            status="NOT_RUN",
            reason="zero-product-write network handshake was not requested",
            command="creator-os status --live-read-only",
            evidence=f"requested=false; trace_id={trace_id}",
            next_action="Run the explicit live-read-only status command when needed.",
        )
    return [
        repository,
        venv_entrypoints,
        contracts,
        local_config,
        canonical_roots,
        runtime,
        database,
        provider,
        handshake,
    ]


def _provider_probe_status(paths: RuntimePaths, *, trace_id: str) -> Result:
    started = time.monotonic()
    try:
        evidence = run_provider_probe(
            artifact_root=paths.artifact_root, trace_id=trace_id
        )
    except Exception as exc:  # noqa: BLE001 - read-only diagnostic boundary
        return Result(
            name="provider-readiness",
            category="Provider readiness",
            status="FAIL",
            reason="zero-generation provider probe failed closed",
            command="creator-os status --live-read-only",
            evidence=f"trace_id={trace_id}; error={type(exc).__name__}: {exc}",
            next_action="Repair provider auth/model/workspace access; do not run generation.",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return Result(
        name="provider-readiness",
        category="Provider readiness",
        status="PASS",
        reason="provider account, workspace, models, balance, and free quote passed",
        command="creator-os status --live-read-only",
        evidence=json.dumps(evidence, sort_keys=True),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _threadsdash_handshake_status(
    paths: RuntimePaths, *, probe_env: dict[str, str], trace_id: str
) -> Result:
    started = time.monotonic()
    url = configured_handshake_url(probe_env)
    secret = probe_env.get("CAMPAIGN_FACTORY_INGEST_SECRET", "").strip()
    if not url or not secret:
        return Result(
            name="threadsdashboard-handshake",
            category="ThreadsDashboard handshake",
            status="NOT_RUN",
            reason="handshake URL or local HMAC secret is not configured",
            command="creator-os status --live-read-only",
            evidence=(
                f"trace_id={trace_id}; url_configured={bool(url)}; "
                f"secret_configured={bool(secret)}; threadsdash_checkout={paths.threadsdash_root}"
            ),
            next_action="Configure the handshake URL and machine-local secret, then retry.",
        )
    try:
        evidence = run_threadsdash_handshake(
            url=url, secret=secret, trace_id=trace_id, env=probe_env
        )
    except Exception as exc:  # noqa: BLE001 - read-only diagnostic boundary
        return Result(
            name="threadsdashboard-handshake",
            category="ThreadsDashboard handshake",
            status="FAIL",
            reason="zero-product-write ThreadsDashboard handshake failed closed",
            command="creator-os status --live-read-only",
            evidence=f"trace_id={trace_id}; error={type(exc).__name__}: {exc}",
            next_action="Repair HMAC, contract, endpoint, or network state; do not hand off drafts.",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return Result(
        name="threadsdashboard-handshake",
        category="ThreadsDashboard handshake",
        status="PASS",
        reason="HMAC and contract handshake passed with zero product rows written",
        command="creator-os status --live-read-only",
        evidence=json.dumps(evidence, sort_keys=True),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def run_doctor(
    *,
    quick: bool = False,
    business_only: bool = False,
    td_snapshot: str | Path | None = None,
    ui_proof: str | Path | None = None,
    release: bool = False,
) -> list[Result]:
    fixture = load_fixture()
    business_fixture = load_business_fixture()
    fixture["_release"] = release
    business_fixture["_release"] = release
    business_fixture["_proofs"] = {
        "td_snapshot": load_optional_json(td_snapshot),
        "ui_proof": load_optional_json(ui_proof),
    }
    audits: list[tuple[Callable[[dict[str, Any], bool], Result], dict[str, Any]]] = []
    technical_audits: list[tuple[str, Callable[[dict[str, Any], bool], Result]]] = [
        ("pipeline-determinism", determinism_audit),
        ("lineage", lineage_audit),
        ("quality-gates", quality_gate_audit),
        ("promotion", promotion_audit),
        ("learning", learning_audit),
        ("data-provenance", provenance_audit),
        ("replay", replay_audit),
        ("duplicate-intelligence", duplicate_audit),
        ("performance", performance_audit),
        ("resource", resource_audit),
        ("failure-recovery", failure_recovery_audit),
        ("configuration", configuration_audit),
        ("documentation", documentation_audit),
        ("technical-debt", technical_debt_audit),
        ("observability", observability_audit),
    ]
    business_audits: list[Callable[[dict[str, Any], bool], Result]] = [
        business_logic_audit,
        cross_system_consistency_audit,
        analytics_integrity_audit,
        ui_consistency_audit,
        business_state_machine_audit,
        data_drift_audit,
        recommendation_audit,
        regression_audit,
        cost_audit,
        human_override_audit,
        account_level_audit,
        campaign_health_audit,
        repository_health_audit,
        operator_experience_audit,
        chaos_audit,
        scaling_audit,
        product_quality_audit,
        ceo_dashboard_audit,
        release_readiness_audit,
        deployment_audit,
        backup_disaster_recovery_audit,
        secret_rotation_audit,
        oauth_authentication_audit,
        incident_response_audit,
        release_hygiene_audit,
        operational_ownership_audit,
        production_proof_audit,
        live_snapshot_audit,
        browser_runtime_proof_audit,
        release_gate_audit,
    ]
    business_regs: list[
        tuple[Callable[[dict[str, Any], bool], Result], dict[str, Any]]
    ] = [(audit, business_fixture) for audit in business_audits]
    # commercial_readiness reads the technical fixture but is gated with the
    # aspirational business suite, so pair it with `fixture` here.
    business_regs.append((commercial_readiness_audit, fixture))
    if business_only:
        audits.extend(business_regs)
    else:
        audits.extend((audit, fixture) for _, audit in technical_audits)
        # Proof/release flags drive the second-layer audits (TD snapshot, UI
        # proof, release gates), so include them when those inputs are present.
        if release or td_snapshot or ui_proof:
            audits.extend(business_regs)
    results: list[Result] = []
    for audit, data in audits:
        started = time.perf_counter()
        result = audit(data, quick)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        results.append(result)
    return results


def determinism_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    failures: list[str] = []
    for campaign in fixture["replay_campaigns"]:
        first = campaign["first_run"]
        second = campaign["second_run"]
        for key in (
            "lineage_hash",
            "contracts_hash",
            "promotion_decision",
            "export_manifest_hash",
        ):
            if first.get(key) != second.get(key):
                failures.append(f"{campaign['campaign_id']}: nondeterministic {key}")
        if not campaign.get("randomness_explained"):
            failures.append(f"{campaign['campaign_id']}: randomness is not explained")
    return fixture_result(
        name="pipeline-determinism",
        category="Pipeline Determinism Audit",
        failures=failures,
        reason_ok="sanitized replay fixture is deterministic for lineage, contracts, promotion, and export metadata",
        affected=[campaign["campaign_id"] for campaign in fixture["replay_campaigns"]],
        evidence=f"{len(fixture['replay_campaigns'])} replay fixture(s)",
        next_action="Add more sanitized historical campaigns to `tests/fixtures/doctor`.",
    )


def lineage_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = (
        "reference",
        "winner_dna",
        "recipe",
        "generated_image",
        "video",
        "qc",
        "draft",
        "published_post",
        "metrics",
    )
    failures = []
    for asset in fixture["assets"]:
        lineage = asset["lineage"]
        missing = [key for key in required if not lineage.get(key)]
        if missing:
            failures.append(
                f"{asset['asset_id']}: missing lineage links {', '.join(missing)}"
            )
    if not has_ref(
        read_json(
            ROOT
            / "packages/pipeline_contracts/pipeline_contracts/schemas/campaign_draft_payload.v1.schema.json"
        ),
        "generated_asset_lineage.v1.schema.json",
    ):
        failures.append(
            "campaign draft contract does not reference generated_asset_lineage"
        )
    return fixture_result(
        name="lineage",
        category="Lineage Audit",
        failures=failures,
        reason_ok="fixture assets reconstruct reference -> winner DNA -> recipe -> generated media -> QC -> draft -> post -> metrics",
        affected=[asset["asset_id"] for asset in fixture["assets"]],
        evidence="generated_asset_lineage schema and fixture ancestry graph verified",
        next_action="Add sanitized production-derived fixture assets as they become available.",
    )


def quality_gate_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = (
        "ocr",
        "compression",
        "readability",
        "safe_zone",
        "watchability",
        "distinctness",
        "pdq",
        "sibling_uniqueness",
    )
    failures = []
    for asset in fixture["assets"]:
        gates = asset["quality_gates"]
        missing = [key for key in required if key not in gates]
        failed = [key for key in required if gates.get(key) != "PASS"]
        if missing:
            failures.append(
                f"{asset['asset_id']}: missing quality gates {', '.join(missing)}"
            )
        if failed:
            failures.append(
                f"{asset['asset_id']}: non-passing quality gates {', '.join(failed)}"
            )
    for failure in fixture["quality_failures"]:
        reason = str(failure.get("failure_reason", ""))
        if not reason or reason.upper() == "FAILED":
            failures.append(f"{failure['asset_id']}: failure reason is not explicit")
    adapter = (
        ROOT
        / "python_packages/campaign_factory/campaign_factory/adapters/contentforge.py"
    ).read_text(encoding="utf-8", errors="ignore")
    if 'response.get("overallVerdict") == "pass"' not in adapter:
        failures.append(
            "ContentForge adapter does not gate approved_candidate on pass verdict"
        )
    return fixture_result(
        name="quality-gates",
        category="Quality Gate Audit",
        failures=failures,
        reason_ok="fixture approved/review-ready assets have required quality evidence and explicit failure reasons",
        affected=[asset["asset_id"] for asset in fixture["assets"]],
        evidence="OCR/compression/readability/safe-zone/watchability/distinctness/PDQ/sibling uniqueness checked",
        next_action="Add a DB-backed approved-asset quality evidence check when a stable fixture DB exists.",
    )


def promotion_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    transitions = {
        "planned": {"prompted"},
        "prompted": {"generated"},
        "generated": {"qc_passed", "qc_failed"},
        "qc_passed": {"ranked"},
        "ranked": {"captioned"},
        "captioned": {"export_ready"},
        "export_ready": {"awaiting_approval"},
        "awaiting_approval": {"approved", "rejected", "regenerate"},
        "approved": {"exported"},
        "error": {"planned"},
    }
    terminal = {"exported", "rejected", "failed", "qc_failed"}
    failures = []
    for asset in fixture["promotion_histories"]:
        states = asset["states"]
        for left, right in zip(states, states[1:]):
            if right not in transitions.get(left, set()) and left not in terminal:
                failures.append(
                    f"{asset['asset_id']}: illegal transition {left} -> {right}"
                )
        if len(states) != len(
            dict.fromkeys((index, state) for index, state in enumerate(states))
        ):
            failures.append(f"{asset['asset_id']}: malformed state history")
        if states[-1] not in terminal:
            failures.append(
                f"{asset['asset_id']}: non-terminal final state {states[-1]}"
            )
    retired = ROOT / "python_packages/reel_factory/reel_factory/orchestrator.py"
    if retired.exists():
        failures.append("Reel Factory still owns campaign promotion state")
    return fixture_result(
        name="promotion",
        category="Promotion Audit",
        failures=failures,
        reason_ok="legacy fixture histories remain valid and Reel campaign promotion state is retired",
        affected=[asset["asset_id"] for asset in fixture["promotion_histories"]],
        evidence="legacy transition fixture + Campaign ownership boundary",
        next_action="Add more terminal-state fixtures if new states are introduced.",
    )


def learning_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    learning = fixture["learning"]
    failures = []
    if learning["after"]["winner_score"] <= learning["before"]["winner_score"]:
        failures.append("winner_score did not improve")
    for key in (
        "new_references",
        "winner_patterns",
        "new_caption_styles",
        "new_hooks",
        "new_audio",
    ):
        if learning.get(key, 0) <= 0:
            failures.append(f"{key} did not increase")
    if learning.get("silent_degradation_detected"):
        failures.append("fixture reports silent degradation")
    learning_test = (
        ROOT / "python_packages/campaign_factory/tests/test_learning_fanout.py"
    )
    tests = learning_test.read_text(encoding="utf-8")
    if (
        "performance_snapshots" not in tests
        or 'DESTINATIONS = ("campaign", "reference")'
        not in (ROOT / "scripts/learning_fanout.py").read_text(encoding="utf-8")
    ):
        failures.append(
            "Campaign learning fan-out does not keep measured facts out of Reel Factory"
        )
    return fixture_result(
        name="learning",
        category="Learning Audit",
        failures=failures,
        reason_ok="fixture learning signals improve and Campaign-owned learning fan-out tests are present",
        affected=["python_packages/campaign_factory/tests/test_learning_fanout.py"],
        evidence=json.dumps(learning, sort_keys=True),
        next_action="Point this audit at a copied campaign DB once more real outcomes exist.",
    )


def provenance_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = (
        "generated_by",
        "prompt",
        "reference_ids",
        "timestamp",
        "recipe_version",
        "model_profile",
        "trace_id",
    )
    failures = []
    for asset in fixture["assets"]:
        provenance = asset["provenance"]
        missing = [key for key in required if not provenance.get(key)]
        if missing:
            failures.append(
                f"{asset['asset_id']}: missing provenance {', '.join(missing)}"
            )
    return fixture_result(
        name="data-provenance",
        category="Data Provenance Audit",
        failures=failures,
        reason_ok="fixture important fields carry generator, prompt, references, timestamp, recipe, model, and trace metadata",
        affected=[asset["asset_id"] for asset in fixture["assets"]],
        evidence=", ".join(required),
        next_action="Require the same fields in future DB-backed lineage fixtures.",
    )


def replay_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    failures = []
    for campaign in fixture["replay_campaigns"]:
        for key, expected in campaign["expected"].items():
            actual = campaign["actual"].get(key)
            if actual != expected:
                failures.append(
                    f"{campaign['campaign_id']}: {key} expected {expected}, got {actual}"
                )
    return fixture_result(
        name="replay",
        category="Replay Audit",
        failures=failures,
        reason_ok="sanitized replay fixtures match expected contracts, QC, promotion, and export manifests",
        affected=[campaign["campaign_id"] for campaign in fixture["replay_campaigns"]],
        evidence="small sanitized fixture set; scale path documented in audit inventory",
        next_action="Expand fixture count toward 100 campaigns after sanitized historical data exists.",
    )


def duplicate_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    duplicate_fixture = fixture["duplicate_intelligence"]
    hooks = duplicate_fixture["hooks"]
    captions = duplicate_fixture["caption_hashes"]
    exact_hooks = sorted(repeated_keys(hooks))
    repeated_hashes = sorted(repeated_keys(captions))
    semantic = sorted(
        pair["pair_id"]
        for pair in duplicate_fixture["semantic_pairs"]
        if pair["visual_structure_match"]
        and pair["storyline_match"]
        and pair["pacing_match"]
    )
    failures = []
    if exact_hooks != sorted(duplicate_fixture["expected_exact_hook_duplicates"]):
        failures.append("exact hook duplicates did not match expected fixture")
    if repeated_hashes != sorted(duplicate_fixture["expected_repeated_caption_hashes"]):
        failures.append("caption hash duplicates did not match expected fixture")
    if semantic != sorted(duplicate_fixture["expected_semantic_duplicates"]):
        failures.append("semantic duplicate pairs did not match expected fixture")
    return fixture_result(
        name="duplicate-intelligence",
        category="Duplicate Intelligence Audit",
        failures=failures,
        reason_ok="fixture detects exact hook, repeated caption hash, and basic semantic/pacing/storyline duplicates",
        affected=exact_hooks + repeated_hashes + semantic,
        evidence="local fixture matcher; no model required",
        next_action="Add model-backed semantic depth only after an accepted taxonomy/model is chosen.",
    )


def performance_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    timings = fixture["performance"]["stage_timings_ms"]
    failures = [
        f"{name}: missing timing"
        for name, value in timings.items()
        if value is None or value < 0
    ]
    slow = [
        f"{name}={value}ms"
        for name, value in timings.items()
        if value > fixture["performance"]["warn_threshold_ms"]
    ]
    status = "WARN" if slow and not failures else ("FAIL" if failures else "PASS")
    return Result(
        "performance",
        "Performance Audit",
        status,
        "fixture timings are present"
        if status == "PASS"
        else (
            "some fixture stages exceed warning threshold"
            if status == "WARN"
            else "fixture timing data is incomplete"
        ),
        "pnpm doctor",
        evidence=json.dumps(timings, sort_keys=True),
        affected=slow,
        next_action="Investigate slow local fixture stages." if slow else "None.",
    )


def resource_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    resources = fixture["resources"]
    failures = []
    for asset in fixture["assets"]:
        if (
            asset.get("requires_paid_generation")
            and asset.get("estimated_cost_usd") is None
        ):
            failures.append(f"{asset['asset_id']}: missing estimated cost")
    if (
        resources["disk_bytes"] < 0
        or resources["api_calls"] < 0
        or resources["cost_usd"] < 0
    ):
        failures.append("resource fixture has negative values")
    return fixture_result(
        name="resource",
        category="Resource Audit",
        failures=failures,
        reason_ok="fixture resource/cost fields are present and paid-generation assets carry estimates",
        affected=[asset["asset_id"] for asset in fixture["assets"]],
        evidence=json.dumps(resources, sort_keys=True),
        next_action="Wire real tick-report timing/cost summaries when stable tick fixtures exist.",
    )


def failure_recovery_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = {"Higgsfield", "Kling", "OCR", "SQLite", "export", "contract_validation"}
    scenarios = fixture["failure_recovery"]
    seen = {scenario["component"] for scenario in scenarios}
    failures = [
        f"missing mocked failure scenario: {component}"
        for component in sorted(required - seen)
    ]
    for scenario in scenarios:
        if scenario.get("corrupts_state"):
            failures.append(f"{scenario['component']}: corrupts state")
        if not scenario.get("recovery_action"):
            failures.append(f"{scenario['component']}: missing recovery action")
    return fixture_result(
        name="failure-recovery",
        category="Failure Recovery Audit",
        failures=failures,
        reason_ok="mocked provider/storage/contract failures have explicit recovery actions",
        affected=sorted(seen),
        evidence="fixture recovery scenarios; Campaign owns long-running coordination",
        next_action="Replace fixture-only provider scenarios with adapter-level mock tests as providers change.",
    )


def configuration_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    path = ROOT / "python_packages/reel_factory/project_data/orchestrator.toml"
    stale_terms = grep_repo(
        ("DEPRECATED_FLAG", "OLD_CREATOR_OS_", "LEGACY_ONLY_CONFIG")
    )
    if not path.exists():
        status = "PASS"
        reason = "Reel Factory has no local campaign orchestrator configuration"
        evidence = "campaign orchestration is owned by Campaign Factory"
        next_action = "None."
    else:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        required = (
            "campaign",
            "creator",
            "reference_image",
            "estimated_cost_per_asset_usd",
        )
        missing = [
            key
            for key in required
            if bool(config.get("enabled", False)) and not config.get(key)
        ]
        status = "FAIL" if missing else ("WARN" if config.get("enabled") else "PASS")
        reason = (
            "enabled orchestrator config missing required fields"
            if missing
            else "local orchestrator config is valid"
        )
        evidence = "\n".join(missing) if missing else str(path.relative_to(ROOT))
        next_action = (
            "Fill required local config fields or disable orchestrator."
            if missing
            else "None."
        )
    if stale_terms and status == "PASS":
        status = "WARN"
        reason = "configuration scan found possible stale/deprecated terms"
        evidence = "\n".join([evidence, *stale_terms[:10]]).strip()
        next_action = "Review stale/deprecated config term matches."
    return Result(
        "configuration",
        "Configuration Audit",
        status,
        reason,
        "pnpm doctor",
        evidence=evidence,
        affected=stale_terms[:10],
        next_action=next_action,
    )


def documentation_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    risky = docs_risk_findings()
    linked_archive = []
    for path in current_doc_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if "docs/archive/" in line and "current" in line.lower():
                linked_archive.append(
                    f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}"
                )
    failures = risky + linked_archive
    return fixture_result(
        name="documentation",
        category="Documentation Audit",
        failures=failures,
        reason_ok="current docs match ContentForge safety wording and current pipeline state; archive docs excluded",
        affected=[str(path.relative_to(ROOT)) for path in current_doc_files()],
        evidence="README.md, CREATOR_OS_SYSTEM_MAP.md, PIPELINE_STATE.md, AGENTS.md, docs/ excluding archive",
        next_action="Fix stale current-doc wording; leave clearly archived docs alone.",
    )


def technical_debt_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    markers = ("TODO", "FIXME", "deprecated", "compatibility shim", "legacy", "shim")
    findings = grep_repo(markers, suffixes=(".py", ".js", ".ts", ".tsx", ".md", ".mjs"))
    severe = [line for line in findings if "P0" in line or "SECURITY" in line]
    ownership = load_debt_ownership()
    categories = categorize_debt_findings(findings)
    missing_owners = sorted(set(categories) - set(ownership))
    status = "FAIL" if severe or missing_owners else ("WARN" if findings else "PASS")
    evidence = (
        f"{len(findings)} markers; severe={len(severe)}; "
        f"categories={json.dumps(categories, sort_keys=True)}; "
        "ownership=tests/fixtures/doctor/technical_debt_burndown.json"
    )
    return Result(
        "technical-debt",
        "Technical Debt Audit",
        status,
        "technical debt markers scanned, categorized, and mapped to burn-down owners"
        if not missing_owners
        else f"technical debt categories missing ownership: {', '.join(missing_owners)}",
        "pnpm doctor",
        evidence=evidence,
        affected=severe[:20] or missing_owners or findings[:20],
        next_action="Review severe markers immediately."
        if severe
        else (
            "Add ownership for missing debt categories."
            if missing_owners
            else "Use the burn-down owner file and debt report for scheduled cleanup; warnings are not merge blockers."
        ),
    )


def observability_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = (
        "current_stage",
        "failure_reason",
        "approver",
        "contract_schema",
        "model_profile",
        "reference_ids",
        "metrics",
    )
    failures = []
    for asset in fixture["assets"]:
        obs = asset["observability"]
        missing = [key for key in required if key not in obs]
        if missing:
            failures.append(
                f"{asset['asset_id']}: missing observability {', '.join(missing)}"
            )
    return fixture_result(
        name="observability",
        category="Observability Audit",
        failures=failures,
        reason_ok="fixture assets expose stage, failure reason, approver, contract, model, references, and metrics",
        affected=[asset["asset_id"] for asset in fixture["assets"]],
        evidence=", ".join(required),
        next_action="Back this with a DB walker once a stable fixture DB is available.",
    )


def commercial_readiness_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    journey = fixture["commercial_readiness"]
    release = bool(fixture.get("_release"))
    failures = [step["name"] for step in journey["steps"] if step["status"] == "fail"]
    checklist = journey.get("operator_checklist", [])
    missing_owners = [
        str(item.get("id", "unknown"))
        for item in checklist
        if not str(item.get("owner", "")).strip()
    ]
    open_items = [
        f"{item['id']}:{item['owner']}"
        for item in checklist
        if item.get("status") != "closed"
    ]
    manual = journey.get("manual_actions", [])
    status = (
        "FAIL"
        if failures or (release and missing_owners)
        else ("WARN" if manual or open_items else "PASS")
    )
    reason = (
        "fixture customer journey has failing steps"
        if failures
        else f"commercial-readiness checklist items are missing owners: {', '.join(missing_owners)}"
        if missing_owners and release
        else (
            f"fixture journey passes, but checklist items remain open: {', '.join(open_items)}"
            if open_items
            else "fixture journey passes, but operator/founder actions remain"
            if manual
            else "fixture customer journey passes without manual actions"
        )
    )
    return Result(
        "commercial-readiness",
        "Commercial Readiness Audit",
        status,
        reason,
        "pnpm doctor",
        evidence=json.dumps(
            {"steps": journey["steps"], "operator_checklist": checklist},
            sort_keys=True,
        ),
        affected=failures + missing_owners + open_items + manual,
        next_action="Resolve listed manual actions before claiming customer self-serve readiness."
        if manual or failures or open_items or missing_owners
        else "None.",
    )


def business_logic_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    required = (
        "creator_match",
        "campaign_match",
        "account_match",
        "time_window_match",
        "cooldown_applied",
        "priority_applied",
        "manual_approval_honored",
        "blocked_asset_not_promoted",
    )
    failures = []
    for decision in fixture["business_logic"]["decisions"]:
        missing = [key for key in required if key not in decision]
        failed = [key for key in required if decision.get(key) is not True]
        if missing:
            failures.append(f"{decision['decision_id']}: missing {', '.join(missing)}")
        if failed:
            failures.append(f"{decision['decision_id']}: failed {', '.join(failed)}")
        if not decision.get("explanation"):
            failures.append(f"{decision['decision_id']}: missing explanation")
    return fixture_result(
        name="business-logic",
        category="Business Logic Audit",
        failures=failures,
        reason_ok="fixture decisions prove creator/campaign/account/window/cooldown/priority/approval/blocking rules",
        affected=[row["decision_id"] for row in fixture["business_logic"]["decisions"]],
        evidence=json.dumps(fixture["business_logic"]["summary"], sort_keys=True),
        next_action="Add DB-backed decision traces when live campaign fixtures are sanitized.",
    )


def cross_system_consistency_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    fields = ("status", "caption", "media_hash", "lineage_hash", "account", "schedule")
    failures = []
    release = bool(fixture.get("_release"))
    proof = fixture.get("_proofs", {}).get("td_snapshot", {})
    if proof.get("error"):
        return Result(
            "cross-system-consistency",
            "Cross-System Consistency Audit",
            "FAIL",
            f"ThreadsDashboard snapshot could not be read: {proof['error']}",
            "pnpm doctor --business --td-snapshot",
            evidence=str(proof.get("path") or ""),
            affected=[str(proof.get("path") or "")],
            next_action="Provide a readable read-only TD snapshot JSON file.",
        )
    proof_data = proof.get("data")
    linked_failures, linked_rows = validate_td_linked_snapshot(proof_data)
    exported_snapshot = isinstance(proof_data, dict) and "generated_at" in proof_data
    if linked_rows or exported_snapshot:
        return Result(
            "cross-system-consistency",
            "Cross-System Consistency Audit",
            "FAIL" if linked_failures else "PASS",
            "\n".join(linked_failures)
            if linked_failures
            else "provided ThreadsDashboard snapshot contains real Creator OS linked rows",
            "pnpm doctor --business --td-snapshot",
            evidence=str(proof.get("path") or ""),
            affected=linked_rows,
            next_action="Fix TD/Creator OS linked-row drift before relying on handoff proof."
            if linked_failures
            else "None.",
        )
    snapshot = normalize_td_snapshot(proof_data)
    if snapshot:
        for pair in fixture["cross_system_consistency"]["draft_pairs"]:
            actual = snapshot.get(pair["draft_id"])
            if not actual:
                failures.append(f"{pair['draft_id']}: missing from TD snapshot")
                continue
            mismatched = [
                field
                for field in fields
                if pair["creator_os"].get(field) != actual.get(field)
            ]
            if mismatched:
                failures.append(f"{pair['draft_id']}: mismatch {', '.join(mismatched)}")
        return Result(
            "cross-system-consistency",
            "Cross-System Consistency Audit",
            "FAIL" if failures else "PASS",
            "\n".join(failures)
            if failures
            else "provided ThreadsDashboard snapshot matches Creator OS draft expectations",
            "pnpm doctor --business --td-snapshot",
            evidence=str(proof.get("path") or ""),
            affected=[
                row["draft_id"]
                for row in fixture["cross_system_consistency"]["draft_pairs"]
            ],
            next_action="Fix TD/Creator OS draft drift before relying on handoff proof."
            if failures
            else "None.",
        )
    for pair in fixture["cross_system_consistency"]["draft_pairs"]:
        mismatched = [
            field
            for field in fields
            if pair["creator_os"].get(field) != pair["threadsdashboard"].get(field)
        ]
        if mismatched:
            failures.append(f"{pair['draft_id']}: mismatch {', '.join(mismatched)}")
    threadsdash_root = resolve_runtime_paths(ROOT).threadsdash_root
    status = (
        "FAIL"
        if failures or release
        else ("WARN" if threadsdash_root.exists() else "SKIP")
    )
    reason = (
        "\n".join(failures)
        if failures
        else "release mode requires a live read-only ThreadsDashboard snapshot"
        if release
        else "sanitized Creator OS and ThreadsDashboard draft fixtures agree; live TD runtime was not mutated"
    )
    return Result(
        "cross-system-consistency",
        "Cross-System Consistency Audit",
        status,
        reason,
        "pnpm doctor --business",
        evidence=f"{len(fixture['cross_system_consistency']['draft_pairs'])} draft pair fixture(s)",
        affected=[
            row["draft_id"]
            for row in fixture["cross_system_consistency"]["draft_pairs"]
        ],
        next_action="Provide `--td-snapshot PATH` from the read-only ThreadsDashboard exporter."
        if status != "PASS"
        else "None.",
    )


def analytics_integrity_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    analytics = fixture["analytics_integrity"]
    source_ids = [row["post_id"] for row in analytics["source_posts"]]
    normalized_ids = [row["post_id"] for row in analytics["normalized_metrics"]]
    failures = []
    missing = sorted(set(source_ids) - set(normalized_ids))
    duplicates = sorted(repeated_keys(normalized_ids))
    if missing:
        failures.append(f"missing normalized posts: {', '.join(missing)}")
    if duplicates:
        failures.append(f"duplicate normalized metrics: {', '.join(duplicates)}")
    for row in analytics["normalized_metrics"]:
        if row["engagements"] > row["views"]:
            failures.append(f"{row['post_id']}: impossible engagement")
        if row["account"] not in analytics["valid_accounts"]:
            failures.append(f"{row['post_id']}: incorrect attribution")
        if not row["timezone_checked"]:
            failures.append(f"{row['post_id']}: timezone not checked")
        expected_revenue = round(row["clicks"] * row["revenue_per_click"], 2)
        if round(row["revenue"], 2) != expected_revenue:
            failures.append(f"{row['post_id']}: revenue mismatch")
    return fixture_result(
        name="analytics-integrity",
        category="Analytics Integrity Audit",
        failures=failures,
        reason_ok="fixture analytics import/normalization/dashboard output has no missing posts, dupes, impossible metrics, attribution, timezone, or revenue issues",
        affected=source_ids,
        evidence=json.dumps(analytics["dashboard_output"], sort_keys=True),
        next_action="Run against copied analytics DB snapshots when available.",
    )


def ui_consistency_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    release = bool(fixture.get("_release"))
    fields = (
        "asset_status",
        "draft_state",
        "queue_state",
        "validation_state",
        "analytics_state",
    )
    failures = []
    for snapshot in fixture["ui_consistency"]["snapshots"]:
        values = {field: snapshot[field] for field in fields}
        if len(set(values.values())) != 1:
            failures.append(f"{snapshot['asset_id']}: inconsistent UI states {values}")
    proof = fixture.get("_proofs", {}).get("ui_proof", {})
    if proof.get("error"):
        failures.append(f"UI proof could not be read: {proof['error']}")
    proof_failures: list[str] = []
    proof_routes: list[str] = []
    if proof.get("data"):
        proof_failures, proof_routes = validate_ui_proof(proof["data"])
        failures.extend(proof_failures)
        status = "FAIL" if failures else "PASS"
        reason = (
            "\n".join(failures)
            if failures
            else "provided ThreadsDashboard browser proof covers required routes without runtime UI errors"
        )
        return Result(
            "ui-consistency",
            "UI Consistency Audit",
            status,
            reason,
            "pnpm doctor --business --ui-proof",
            evidence=str(proof.get("path") or ""),
            affected=proof_routes
            or [row["asset_id"] for row in fixture["ui_consistency"]["snapshots"]],
            next_action="Fix browser proof failures before relying on UI consistency."
            if failures
            else "None.",
        )
    return Result(
        "ui-consistency",
        "UI Consistency Audit",
        "FAIL" if failures or release else "WARN",
        "\n".join(failures)
        if failures
        else "release mode requires ThreadsDashboard browser proof"
        if release
        else "static fixture states agree; browser/runtime UI proof still requires a safe preview session",
        "pnpm doctor --business",
        evidence=json.dumps(fixture["ui_consistency"]["snapshots"], sort_keys=True),
        affected=[row["asset_id"] for row in fixture["ui_consistency"]["snapshots"]],
        next_action="Provide `--ui-proof PATH` from the ThreadsDashboard Playwright proof.",
    )


def business_state_machine_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    transitions = {
        "Generated": {"Audited"},
        "Audited": {"Validated"},
        "Validated": {"Draft"},
        "Draft": {"Scheduled"},
        "Scheduled": {"Published"},
        "Published": set(),
    }
    failures = []
    seen_promotions: set[str] = set()
    for flow in fixture["business_state_machine"]["flows"]:
        states = flow["states"]
        for left, right in zip(states, states[1:]):
            if right not in transitions.get(left, set()):
                failures.append(
                    f"{flow['asset_id']}: impossible transition {left}->{right}"
                )
        if len(states) != len(dict.fromkeys(states)):
            failures.append(f"{flow['asset_id']}: loop detected")
        if states[-1] not in {"Published"}:
            failures.append(f"{flow['asset_id']}: orphan final state {states[-1]}")
        promotion_key = f"{flow['asset_id']}:{states[-1]}"
        if promotion_key in seen_promotions:
            failures.append(f"{flow['asset_id']}: duplicate promotion")
        seen_promotions.add(promotion_key)
    return fixture_result(
        name="business-state-machine",
        category="State Machine Audit",
        failures=failures,
        reason_ok="business workflow fixture follows Generated->Audited->Validated->Draft->Scheduled->Published without loops/orphans/duplicates",
        affected=[
            row["asset_id"] for row in fixture["business_state_machine"]["flows"]
        ],
        evidence="business workflow fixture DB surrogate",
        next_action="Back this with a copied workflow DB when available.",
    )


def data_drift_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    drift = fixture["data_drift"]
    warnings = []
    failures = []
    for metric, values in drift["metrics"].items():
        delta = abs(values["current"] - values["baseline"])
        if delta > values["fail_threshold"]:
            failures.append(
                f"{metric}: delta {delta} > fail {values['fail_threshold']}"
            )
        elif delta > values["warn_threshold"]:
            warnings.append(
                f"{metric}: delta {delta} > warn {values['warn_threshold']}"
            )
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return Result(
        "data-drift",
        "Data Drift Audit",
        status,
        "\n".join(failures or warnings)
        or "fixture drift metrics are inside thresholds",
        "pnpm doctor --business",
        evidence=json.dumps(drift["metrics"], sort_keys=True),
        affected=list(drift["metrics"].keys()),
        next_action="Investigate drift threshold breaches."
        if status != "PASS"
        else "None.",
    )


def recommendation_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    recs = fixture["recommendations"]
    total = len(recs)
    overrides = [row for row in recs if row["outcome"] == "manually_overridden"]
    accepted_quality = average(
        row["quality_score"] for row in recs if row["outcome"] == "accepted"
    )
    rejected_quality = average(
        row["quality_score"] for row in recs if row["outcome"] == "rejected"
    )
    override_rate = len(overrides) / max(total, 1)
    failures = []
    warnings = []
    if override_rate > 0.8:
        failures.append(f"override rate {override_rate:.2f} > 0.80")
    elif override_rate > 0.4:
        warnings.append(f"override rate {override_rate:.2f} > 0.40")
    if accepted_quality < rejected_quality:
        failures.append("accepted recommendations score below rejected recommendations")
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return Result(
        "recommendation",
        "Recommendation Audit",
        status,
        "\n".join(failures or warnings)
        or "fixture recommendations have acceptable override rate and quality separation",
        "pnpm doctor --business",
        evidence=json.dumps(
            {
                "overrideRate": override_rate,
                "acceptedQuality": accepted_quality,
                "rejectedQuality": rejected_quality,
            },
            sort_keys=True,
        ),
        affected=[row["recommendation_id"] for row in recs],
        next_action="Review recommender if override rate stays high."
        if status != "PASS"
        else "None.",
    )


def regression_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    failures = []
    warnings = []
    for metric, values in fixture["regression"]["metrics"].items():
        current = values["current"]
        baseline = values["baseline"]
        direction = values["direction"]
        delta = (
            current - baseline
            if direction == "higher_is_better"
            else baseline - current
        )
        if delta < -values["fail_threshold"]:
            failures.append(f"{metric}: regressed by {abs(delta)}")
        elif delta < -values["warn_threshold"]:
            warnings.append(f"{metric}: regressed by {abs(delta)}")
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return Result(
        "regression",
        "Regression Audit",
        status,
        "\n".join(failures or warnings)
        or "fixture release metrics did not regress beyond thresholds",
        "pnpm doctor --business",
        evidence=json.dumps(fixture["regression"]["metrics"], sort_keys=True),
        affected=list(fixture["regression"]["metrics"].keys()),
        next_action="Block release on hard regressions; review threshold warnings."
        if status != "PASS"
        else "None.",
    )


def cost_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    failures = []
    high = []
    for asset in fixture["costs"]["assets"]:
        parts = ("api", "gpu", "storage", "ocr", "embedding_analysis")
        missing = [part for part in parts if part not in asset["costs"]]
        if missing:
            failures.append(f"{asset['asset_id']}: missing costs {', '.join(missing)}")
        computed = round(sum(asset["costs"].get(part, 0) for part in parts), 2)
        if computed != round(asset["total_cost"], 2):
            failures.append(
                f"{asset['asset_id']}: cost total mismatch {computed} != {asset['total_cost']}"
            )
        if (
            asset["cost_per_publishable"]
            > fixture["costs"]["warn_cost_per_publishable"]
        ):
            high.append(f"{asset['asset_id']}={asset['cost_per_publishable']}")
    status = "FAIL" if failures else ("WARN" if high else "PASS")
    return Result(
        "cost",
        "Cost Audit",
        status,
        "\n".join(failures)
        if failures
        else (
            "high cost per publishable asset"
            if high
            else "fixture asset costs are complete and totals match"
        ),
        "pnpm doctor --business",
        evidence=json.dumps(fixture["costs"], sort_keys=True),
        affected=high or [asset["asset_id"] for asset in fixture["costs"]["assets"]],
        next_action="Investigate high-cost assets." if high or failures else "None.",
    )


def human_override_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    overrides = fixture["human_overrides"]["events"]
    total_assets = fixture["human_overrides"]["total_assets"]
    override_rate = len(overrides) / max(total_assets, 1)
    top_reasons = sorted(repeated_keys([event["reason"] for event in overrides]))
    status = (
        "WARN" if override_rate > fixture["human_overrides"]["warn_rate"] else "PASS"
    )
    return Result(
        "human-override",
        "Human Override Audit",
        status,
        f"override rate {override_rate:.2f}"
        if status == "WARN"
        else "fixture override rate is within threshold",
        "pnpm doctor --business",
        evidence=json.dumps(
            {"overrideRate": override_rate, "topRepeatedReasons": top_reasons},
            sort_keys=True,
        ),
        affected=[event["event_id"] for event in overrides],
        next_action="Review top override reasons." if status == "WARN" else "None.",
    )


def account_level_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    warnings = []
    for account in fixture["accounts"]:
        if account["posting_frequency_7d"] < account["min_posting_frequency_7d"]:
            warnings.append(f"{account['account_id']}: low posting frequency")
        if account["campaign_diversity"] < account["min_campaign_diversity"]:
            warnings.append(f"{account['account_id']}: low campaign diversity")
        if account["duplicate_risk"] > account["max_duplicate_risk"]:
            warnings.append(f"{account['account_id']}: duplicate risk")
        if account["approval_rate"] < account["min_approval_rate"]:
            warnings.append(f"{account['account_id']}: low approval rate")
        if account["inactive_days"] > account["max_inactive_days"]:
            warnings.append(f"{account['account_id']}: inactive period")
    return Result(
        "account-level",
        "Account-Level Audit",
        "WARN" if warnings else "PASS",
        "\n".join(warnings)
        if warnings
        else "fixture account health is inside thresholds",
        "pnpm doctor --business",
        evidence=json.dumps(fixture["accounts"], sort_keys=True),
        affected=[account["account_id"] for account in fixture["accounts"]],
        next_action="Review unhealthy account warnings." if warnings else "None.",
    )


def campaign_health_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    warnings = []
    for campaign in fixture["campaign_health"]:
        for metric, threshold in (
            ("variety", "min_variety"),
            ("hook_diversity", "min_hook_diversity"),
            ("format_diversity", "min_format_diversity"),
            ("schedule_balance", "min_schedule_balance"),
        ):
            if campaign[metric] < campaign[threshold]:
                warnings.append(f"{campaign['campaign_id']}: low {metric}")
        if campaign["duplicate_load"] > campaign["max_duplicate_load"]:
            warnings.append(f"{campaign['campaign_id']}: duplicate load high")
        if campaign["winning_theme_reuse"] > campaign["max_winning_theme_reuse"]:
            warnings.append(f"{campaign['campaign_id']}: winning theme overused")
    return Result(
        "campaign-health",
        "Campaign Health Audit",
        "WARN" if warnings else "PASS",
        "\n".join(warnings)
        if warnings
        else "fixture campaigns are varied, balanced, and supplied",
        "pnpm doctor --business",
        evidence=json.dumps(fixture["campaign_health"], sort_keys=True),
        affected=[campaign["campaign_id"] for campaign in fixture["campaign_health"]],
        next_action="Review narrow/repetitive campaigns." if warnings else "None.",
    )


def repository_health_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    release = bool(fixture.get("_release"))
    status_output = command_check(
        ["git", "status", "--short", "--branch"], timeout=30
    ).output
    branch_output = command_check(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
        ],
        timeout=30,
    ).output
    repo = fixture["repository_health"]
    warnings = []
    if repo["ci_duration_minutes"] > repo["max_ci_duration_minutes"]:
        warnings.append("CI duration above threshold")
    if repo["flaky_tests"] > 0:
        warnings.append("flaky tests reported")
    if repo["migration_debt"] > repo["max_migration_debt"]:
        warnings.append("migration debt above threshold")
    dirty_lines = [
        line
        for line in status_output.splitlines()
        if line and not line.startswith("##")
    ]
    if dirty_lines:
        warnings.append(
            f"working tree has {len(dirty_lines)} uncommitted/untracked path(s)"
        )
    stale_branches = [
        branch.strip()
        for branch in branch_output.splitlines()
        if branch.strip() and branch.strip() not in {"main"}
    ]
    if stale_branches:
        warnings.append(
            f"local non-main branches need merge/delete review: {', '.join(stale_branches[:6])}"
        )
    status = "FAIL" if release and dirty_lines else ("WARN" if warnings else "PASS")
    return Result(
        "repository-health",
        "Repository Health Audit",
        status,
        "\n".join(warnings)
        if warnings
        else "repository health fixture and local git state are clean",
        "git status --short --branch && git for-each-ref --format=%(refname:short) refs/heads",
        evidence=json.dumps(repo, sort_keys=True),
        affected=warnings,
        next_action="Resolve repo health warnings before release."
        if warnings
        else "None.",
    )


def operator_experience_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    experience = fixture["operator_experience"]
    warnings = []
    if experience["clicks"] > experience["max_clicks"]:
        warnings.append("too many clicks")
    if experience["confusing_states"]:
        warnings.append(
            f"confusing states: {', '.join(experience['confusing_states'])}"
        )
    for key in (
        "recovery_path_present",
        "onboarding_complete",
        "discoverability_present",
    ):
        if not experience[key]:
            warnings.append(f"{key} is false")
    return Result(
        "operator-experience",
        "Operator Experience Audit",
        "WARN" if warnings else "PASS",
        "\n".join(warnings)
        if warnings
        else "fixture operator journey is within click/confusion/recovery/onboarding/discoverability thresholds",
        "pnpm doctor --business",
        evidence=json.dumps(experience, sort_keys=True),
        affected=warnings,
        next_action="Validate with a real operator walkthrough before declaring top-tier UX."
        if warnings
        else "None.",
    )


def chaos_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    failures = []
    for scenario in fixture["chaos"]:
        if scenario["corrupts_state"]:
            failures.append(f"{scenario['scenario']}: corrupts state")
        if not scenario["graceful_recovery"]:
            failures.append(f"{scenario['scenario']}: recovery not graceful")
    return fixture_result(
        name="chaos",
        category="Chaos Audit",
        failures=failures,
        reason_ok="fixture chaos scenarios recover gracefully without state corruption",
        affected=[scenario["scenario"] for scenario in fixture["chaos"]],
        evidence=json.dumps(fixture["chaos"], sort_keys=True),
        next_action="Back high-risk scenarios with integration mocks as adapter seams settle.",
    )


def scaling_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    release = bool(fixture.get("_release"))
    warnings = []
    blockers = []
    projections = []
    for scenario in fixture["scaling"]:
        projection = scale_projection(scenario)
        projections.append(projection)
        if projection["max_utilization"] > scenario["warn_utilization"]:
            message = f"{scenario['creators']} creators: utilization {projection['max_utilization']:.2f} above {scenario['warn_utilization']:.2f}"
            warnings.append(message)
            if release_scale_required(scenario):
                blockers.append(message)
        if scenario["analytics_lag_minutes"] > scenario["max_analytics_lag_minutes"]:
            warnings.append(
                f"{scenario['creators']} creators: analytics lag above threshold"
            )
        if scenario["assumption_confidence"] < 0.75 or not scenario.get(
            "measured_inputs"
        ):
            warnings.append(f"{scenario['creators']} creators: weak assumptions")
    status = "FAIL" if release and blockers else ("WARN" if warnings else "PASS")
    return Result(
        "scaling",
        "Scaling Audit",
        status,
        "\n".join(warnings)
        if warnings
        else "fixture scale model is within thresholds for 1000/5000/10000 creators",
        "pnpm doctor --business",
        evidence=json.dumps(projections, sort_keys=True),
        affected=[str(row["creators"]) for row in fixture["scaling"]],
        next_action="Replace model estimates with load-test measurements for high-scale warnings."
        if warnings
        else "None.",
    )


def product_quality_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    warnings = []
    for sample in fixture["product_quality"]:
        reviewer_avg = average(sample["reviewer_scores"].values())
        auto = sample["automated_qc_score"]
        if abs(reviewer_avg - auto) > sample["warn_delta"]:
            warnings.append(
                f"{sample['asset_id']}: reviewer/QC disagreement {abs(reviewer_avg - auto):.2f}"
            )
    return Result(
        "product-quality",
        "Product Quality Audit",
        "WARN" if warnings else "PASS",
        "\n".join(warnings)
        if warnings
        else "blinded reviewer fixture scores agree with automated QC inside threshold",
        "pnpm doctor --business",
        evidence=json.dumps(fixture["product_quality"], sort_keys=True),
        affected=[sample["asset_id"] for sample in fixture["product_quality"]],
        next_action="Collect more blinded reviewer samples if disagreements appear."
        if warnings
        else "None.",
    )


def ceo_dashboard_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    dashboard = fixture["ceo_dashboard"]
    required = (
        "pipeline_health",
        "contract_health",
        "assets_generated_today",
        "qc_pass_rate",
        "average_generation_time_seconds",
        "replay_determinism",
        "analytics_freshness_minutes",
        "duplicate_rate",
        "human_override_rate",
        "publish_success",
        "cost_per_published_asset",
    )
    missing = [key for key in required if key not in dashboard]
    return fixture_result(
        name="ceo-dashboard",
        category="CEO Dashboard Audit",
        failures=[f"missing CEO metric: {key}" for key in missing],
        reason_ok="fixture CEO dashboard includes all required system-health metrics",
        affected=list(required),
        evidence=json.dumps(dashboard, sort_keys=True),
        next_action="Render these metrics in an operator dashboard once live sources are approved.",
    )


def release_readiness_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    release = bool(fixture.get("_release"))
    blockers = release_blockers(fixture, include_missing_proofs=release)
    status = "FAIL" if release and blockers else ("WARN" if blockers else "PASS")
    return Result(
        "release-readiness",
        "Release Readiness Audit",
        status,
        "\n".join(blockers)
        if blockers
        else "release gates are available and no local release blockers were detected",
        "pnpm doctor --release",
        evidence="release mode checks TD snapshot, UI proof, dirty tree, scaling, and severe/unowned debt",
        affected=blockers,
        next_action="Clear listed blockers before tagging or merging a release branch."
        if blockers
        else "None.",
    )


def deployment_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    docs = [
        ROOT / "docs/architecture/monorepo_deployment_promotion.md",
        ROOT / "docs/architecture/build_provenance.md",
        ROOT / "docs/architecture/github_protection_settings.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in docs if not path.exists()]
    status = "FAIL" if missing else "WARN"
    reason = (
        f"missing deployment governance docs: {', '.join(missing)}"
        if missing
        else "deployment controls are documented; live deployment/package proof remains external"
    )
    return Result(
        "deployment",
        "Deployment Audit",
        status,
        reason,
        "pnpm doctor",
        evidence=", ".join(
            str(path.relative_to(ROOT)) for path in docs if path.exists()
        ),
        affected=missing,
        next_action="Attach production deployment, migration, env-parity, and rollback evidence before commercial release.",
    )


def backup_disaster_recovery_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    item = checklist_item("time-machine-backup")
    open_item = item and item.get("status") != "closed"
    return Result(
        "backup-disaster-recovery",
        "Backup & Disaster Recovery Audit",
        "WARN" if open_item else "PASS",
        "Time Machine/local runtime backup remains open"
        if open_item
        else "backup checklist item is closed",
        "pnpm doctor",
        evidence=json.dumps(item or {}, sort_keys=True),
        affected=[item["id"]] if open_item else [],
        next_action="Configure and test local backup/restore, then close the checklist item."
        if open_item
        else "None.",
    )


def secret_rotation_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    docs = [
        ROOT / "docs/runbooks/threadsdash_ingest_secret_rotation.md",
        ROOT / "docs/runbooks/security_incident_closure.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in docs if not path.exists()]
    return Result(
        "secret-rotation",
        "Secret Rotation Audit",
        "FAIL" if missing else "PASS",
        f"missing secret rotation docs: {', '.join(missing)}"
        if missing
        else "secret rotation and incident credential rotation runbooks are present",
        "pnpm doctor",
        evidence=", ".join(
            str(path.relative_to(ROOT)) for path in docs if path.exists()
        ),
        affected=missing,
        next_action="Add missing rotation runbook coverage." if missing else "None.",
    )


def oauth_authentication_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    item = checklist_item("provider-account-auth")
    open_item = item and item.get("status") != "closed"
    return Result(
        "oauth-authentication",
        "OAuth / Authentication Audit",
        "WARN" if open_item else "PASS",
        "provider/account auth remains owner-controlled and open"
        if open_item
        else "provider/account auth checklist item is closed",
        "pnpm doctor",
        evidence=json.dumps(item or {}, sort_keys=True),
        affected=[item["id"]] if open_item else [],
        next_action="Verify provider auth, token expiry, and account permissions outside Creator OS."
        if open_item
        else "None.",
    )


def incident_response_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    docs = [
        ROOT / "docs/runbooks/operator_failure_runbooks.md",
        ROOT / "docs/runbooks/security_incident_closure.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in docs if not path.exists()]
    return Result(
        "incident-response",
        "Incident Response Audit",
        "FAIL" if missing else "PASS",
        f"missing incident response docs: {', '.join(missing)}"
        if missing
        else "operator failure and security incident runbooks are present",
        "pnpm doctor",
        evidence=", ".join(
            str(path.relative_to(ROOT)) for path in docs if path.exists()
        ),
        affected=missing,
        next_action="Add missing runbooks before release." if missing else "None.",
    )


def release_hygiene_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    release = bool(fixture.get("_release"))
    warnings = repo_hygiene_warnings()
    status = (
        "FAIL"
        if release and any("working tree" in row for row in warnings)
        else ("WARN" if warnings else "PASS")
    )
    return Result(
        "release-hygiene",
        "Release Hygiene Audit",
        status,
        "\n".join(warnings)
        if warnings
        else "working tree and local release branch hygiene are clean",
        "git status --short --branch && git for-each-ref --format=%(refname:short) refs/heads",
        evidence="CREATOR_OS_SYSTEM_MAP.md and docs/architecture/tooling_hardening.md",
        affected=warnings,
        next_action="Resolve dirty tree and branch cleanup before tagging/merging."
        if warnings
        else "None.",
    )


def operational_ownership_audit(_fixture: dict[str, Any], _quick: bool) -> Result:
    fixture = load_fixture()
    checklist = fixture["commercial_readiness"].get("operator_checklist", [])
    missing = [
        item["id"] for item in checklist if not str(item.get("owner", "")).strip()
    ]
    open_items = [
        f"{item['id']}:{item['owner']}"
        for item in checklist
        if item.get("status") != "closed"
    ]
    status = "FAIL" if missing else ("WARN" if open_items else "PASS")
    return Result(
        "operational-ownership",
        "Operational Ownership Audit",
        status,
        f"checklist items missing owners: {', '.join(missing)}"
        if missing
        else f"all items have owners, but remain open: {', '.join(open_items)}"
        if open_items
        else "all operator checklist items are owned and closed",
        "pnpm doctor",
        evidence=json.dumps(checklist, sort_keys=True),
        affected=missing or open_items,
        next_action="Close or explicitly defer owned checklist items before commercial readiness."
        if missing or open_items
        else "None.",
    )


def production_proof_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    proofs = fixture.get("_proofs", {})
    missing = []
    if not normalize_td_snapshot(proofs.get("td_snapshot", {}).get("data")):
        missing.append("live TD snapshot")
    if not proofs.get("ui_proof", {}).get("data"):
        missing.append("browser UI proof")
    status = "WARN" if missing else "PASS"
    return Result(
        "production-proof",
        "Production Proof Audit",
        status,
        f"missing live production proof: {', '.join(missing)}"
        if missing
        else "live snapshot and browser proof artifacts were provided",
        "pnpm doctor --td-snapshot PATH --ui-proof PATH",
        evidence=json.dumps(
            {key: value.get("path") for key, value in proofs.items()}, sort_keys=True
        ),
        affected=missing,
        next_action="Provide current read-only TD snapshot and UI proof artifacts."
        if missing
        else "None.",
    )


def live_snapshot_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    result = cross_system_consistency_audit(fixture, _quick)
    result.name = "live-snapshot"
    result.category = "Live Snapshot Audit"
    result.command = "pnpm doctor --td-snapshot PATH"
    return result


def browser_runtime_proof_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    result = ui_consistency_audit(fixture, _quick)
    result.name = "browser-runtime-proof"
    result.category = "Browser Runtime Proof Audit"
    result.command = "pnpm doctor --ui-proof PATH"
    return result


def release_gate_audit(fixture: dict[str, Any], _quick: bool) -> Result:
    blockers = release_blockers(fixture, include_missing_proofs=True)
    status = "FAIL" if bool(fixture.get("_release")) and blockers else "PASS"
    return Result(
        "release-gate",
        "Release Gate Audit",
        status,
        "\n".join(blockers)
        if status == "FAIL"
        else "release gate is wired; run with --release to enforce blockers",
        "pnpm doctor --release",
        evidence="cross-system, UI proof, repository, debt, commercial ownership, and scaling gates",
        affected=blockers if status == "FAIL" else [],
        next_action="Run `pnpm doctor --release` before release and clear FAIL rows."
        if status == "FAIL"
        else "None.",
    )


@dataclass
class CommandResult:
    returncode: int
    output: str
    duration_ms: int


def command_check(command: list[str], timeout: int = 180) -> CommandResult:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        completed.returncode,
        completed.stdout,
        int((time.perf_counter() - started) * 1000),
    )


def fixture_result(
    *,
    name: str,
    category: str,
    failures: list[str],
    reason_ok: str,
    affected: list[str],
    evidence: str,
    next_action: str,
) -> Result:
    return Result(
        name,
        category,
        "FAIL" if failures else "PASS",
        "\n".join(failures) if failures else reason_ok,
        "pnpm doctor",
        evidence=evidence,
        affected=affected,
        next_action=next_action if failures else "None.",
    )


def load_fixture() -> dict[str, Any]:
    return read_json(FIXTURE)


def load_business_fixture() -> dict[str, Any]:
    return read_json(BUSINESS_FIXTURE)


def load_optional_json(path_value: str | Path | None) -> dict[str, Any]:
    if not path_value:
        return {"path": None, "data": None, "error": None}
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return {"path": str(path), "data": None, "error": "file does not exist"}
    try:
        return {"path": str(path), "data": read_json(path), "error": None}
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": str(path), "data": None, "error": str(exc)}


def checklist_item(item_id: str) -> dict[str, Any] | None:
    fixture = load_fixture()
    for item in fixture["commercial_readiness"].get("operator_checklist", []):
        if item.get("id") == item_id:
            return item
    return None


def repo_hygiene_warnings() -> list[str]:
    status_output = command_check(
        ["git", "status", "--short", "--branch"], timeout=30
    ).output
    branch_output = command_check(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
        ],
        timeout=30,
    ).output
    warnings = []
    dirty_lines = [
        line
        for line in status_output.splitlines()
        if line and not line.startswith("##")
    ]
    if dirty_lines:
        warnings.append(
            f"working tree has {len(dirty_lines)} uncommitted/untracked path(s)"
        )
    stale_branches = [
        branch.strip()
        for branch in branch_output.splitlines()
        if branch.strip() and branch.strip() not in {"main"}
    ]
    if stale_branches:
        warnings.append(
            f"local non-main branches need merge/delete review: {', '.join(stale_branches[:6])}"
        )
    return warnings


def release_blockers(
    fixture: dict[str, Any], *, include_missing_proofs: bool
) -> list[str]:
    blockers = []
    proofs = fixture.get("_proofs", {})
    if include_missing_proofs:
        if not normalize_td_snapshot(proofs.get("td_snapshot", {}).get("data")):
            blockers.append("missing live TD snapshot")
        if not proofs.get("ui_proof", {}).get("data"):
            blockers.append("missing browser UI proof")
    blockers.extend(row for row in repo_hygiene_warnings() if "working tree" in row)
    for scenario in fixture.get("scaling", []):
        projection = scale_projection(scenario)
        if (
            release_scale_required(scenario)
            and projection["max_utilization"] > scenario["warn_utilization"]
        ):
            blockers.append(
                f"{scenario['creators']} creators utilization {projection['max_utilization']:.2f}"
            )
    debt = grep_repo(
        ("TODO", "FIXME", "deprecated", "compatibility shim", "legacy", "shim"),
        suffixes=(".py", ".js", ".ts", ".tsx", ".md", ".mjs"),
    )
    severe = [line for line in debt if "P0" in line or "SECURITY" in line]
    missing_debt_owners = sorted(
        set(categorize_debt_findings(debt)) - set(load_debt_ownership())
    )
    if severe:
        blockers.append(f"severe technical debt markers: {len(severe)}")
    if missing_debt_owners:
        blockers.append(
            f"unowned technical debt categories: {', '.join(missing_debt_owners)}"
        )
    commercial = load_fixture()["commercial_readiness"].get("operator_checklist", [])
    missing_owners = [
        item["id"] for item in commercial if not str(item.get("owner", "")).strip()
    ]
    if missing_owners:
        blockers.append(
            f"commercial checklist missing owners: {', '.join(missing_owners)}"
        )
    return blockers


def normalize_td_snapshot(data: Any) -> dict[str, dict[str, Any]]:
    if not data:
        return {}
    rows = td_snapshot_rows(data)
    normalized = {}
    for row in rows:
        draft_id = row.get("draft_id") or row.get("id")
        if draft_id:
            normalized[str(draft_id)] = row
    return normalized


def td_snapshot_rows(data: Any) -> list[dict[str, Any]]:
    rows = data.get("drafts", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def validate_td_linked_snapshot(data: Any) -> tuple[list[str], list[str]]:
    failures = []
    linked_rows = [
        row
        for row in td_snapshot_rows(data)
        if row.get("creator_os_external_id")
        or row.get("lineage_key")
        or row.get("creator_os")
        or row.get("threadsdashboard")
    ]
    if not linked_rows:
        return ["provided TD snapshot has no Creator OS linked rows"], []
    affected = []
    for row in linked_rows:
        row_id = str(row.get("creator_os_external_id") or row.get("draft_id") or "")
        affected.append(row_id or "unknown")
        for required_field in ("status", "media_hash"):
            if not row.get(required_field):
                failures.append(f"{row_id}: missing {required_field}")
        creator = (
            row.get("creator_os") if isinstance(row.get("creator_os"), dict) else {}
        )
        td = (
            row.get("threadsdashboard")
            if isinstance(row.get("threadsdashboard"), dict)
            else {}
        )
        for compared_field in ("caption", "media_hash", "account", "schedule"):
            if (
                creator.get(compared_field)
                and td.get(compared_field)
                and str(creator[compared_field]) != str(td[compared_field])
            ):
                failures.append(f"{row_id}: {compared_field} mismatch")
    return failures, affected


def release_scale_required(scenario: dict[str, Any]) -> bool:
    return int(scenario.get("creators", 0)) <= 1000


def validate_ui_proof(data: Any) -> tuple[list[str], list[str]]:
    required_routes = {"/calendar", "/composer", "/links", "/analytics", "/reliability"}
    rows = data.get("routes", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return ["UI proof must be a list or contain a routes list"], []
    by_route = {row.get("route"): row for row in rows if isinstance(row, dict)}
    routes = sorted(route for route in by_route if route)
    failures = [
        f"missing route proof: {route}"
        for route in sorted(required_routes - set(routes))
    ]
    for route, row in by_route.items():
        if route not in required_routes:
            continue
        if int(row.get("console_error_count", 0)) > 0:
            failures.append(f"{route}: console errors={row['console_error_count']}")
        if not row.get("viewport"):
            failures.append(f"{route}: missing viewport")
        if not row.get("visible_state_labels"):
            failures.append(f"{route}: missing visible state labels")
        if not row.get("screenshot_path"):
            failures.append(f"{route}: missing screenshot path")
    return failures, routes


def load_debt_ownership() -> dict[str, Any]:
    path = ROOT / "tests/fixtures/doctor/technical_debt_burndown.json"
    if not path.exists():
        return {}
    data = read_json(path)
    return {
        item["category"]: item
        for item in data.get("categories", [])
        if isinstance(item, dict) and item.get("category")
    }


def categorize_debt_findings(findings: list[str]) -> dict[str, int]:
    categories: dict[str, int] = {}
    for finding in findings:
        lower = finding.lower()
        if "fixme" in lower or "todo" in lower:
            category = "todo_fixme"
        elif "compatibility shim" in lower or "shim" in lower:
            category = "compatibility_shims"
        elif "deprecated" in lower or "legacy" in lower:
            category = "legacy_deprecated"
        else:
            category = "other"
        categories[category] = categories.get(category, 0) + 1
    return categories


def scale_projection(scenario: dict[str, Any]) -> dict[str, Any]:
    daily_assets = scenario["creators"] * scenario["posts_per_creator_per_day"]
    retry_multiplier = 1 + scenario["failure_retry_rate"]
    generation_hours = (
        daily_assets
        * scenario["generation_seconds_per_asset"]
        * retry_multiplier
        / 3600
    )
    generation_capacity = (
        scenario["generation_workers"] * scenario["available_generation_hours_per_day"]
    )
    approval_capacity = scenario["approval_capacity_per_day"]
    export_capacity = (
        scenario["export_throughput_per_hour"] * scenario["export_hours_per_day"]
    )
    utilizations = {
        "generation": generation_hours / max(generation_capacity, 1),
        "approval": daily_assets / max(approval_capacity, 1),
        "export": daily_assets / max(export_capacity, 1),
    }
    return {
        "creators": scenario["creators"],
        "daily_assets": round(daily_assets, 2),
        "generation_hours": round(generation_hours, 2),
        "utilization": {key: round(value, 3) for key, value in utilizations.items()},
        "max_utilization": round(max(utilizations.values()), 3),
        "analytics_lag_minutes": scenario["analytics_lag_minutes"],
        "assumption_confidence": scenario["assumption_confidence"],
        "measured_inputs": scenario.get("measured_inputs", False),
    }


def docs_risk_findings() -> list[str]:
    risky: list[str] = []
    for path in current_doc_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        if "contentforge" in lower:
            for line_no, line in enumerate(text.splitlines(), start=1):
                line_lower = line.lower()
                if "contentforge" in line_lower and any(
                    token in line_lower
                    for token in (
                        "spoof",
                        "evasion",
                        "evade",
                        "bypass duplicate",
                        "defeat duplicate",
                        "re-used content reads",
                    )
                ):
                    risky.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")
        for term in (
            "Recipe bandit reads legacy `publish_metrics`",
            "Next build: orchestrator + approval inbox",
            "The only gap is a recurring trigger",
        ):
            if term in text:
                risky.append(f"{path.relative_to(ROOT)}: stale term: {term}")
    return risky


def current_doc_files() -> list[Path]:
    files: list[Path] = []
    for root in CURRENT_DOC_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file() and "archive" not in path.relative_to(root).parts:
                    files.append(path)
    return files


def repo_files(suffixes: tuple[str, ...] | None = None) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    files = []
    for raw in completed.stdout.splitlines():
        path = ROOT / raw
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        files.append(path)
    return files


def grep_repo(
    markers: tuple[str, ...], suffixes: tuple[str, ...] | None = None
) -> list[str]:
    hits: list[str] = []
    lowered = tuple(marker.lower() for marker in markers)
    for path in repo_files(suffixes):
        if path == Path(__file__).resolve():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] == "docs" and "archive" in rel.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            line_lower = line.lower()
            if any(marker in line_lower for marker in lowered):
                hits.append(f"{rel}:{line_no}: {line.strip()}")
    return hits


def repeated_keys(values: list[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if normalized in seen:
            repeated.add(normalized)
        seen.add(normalized)
    return repeated


def average(values: Any) -> float:
    numbers = [float(value) for value in values]
    return sum(numbers) / len(numbers) if numbers else 0.0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def has_ref(value: object, ref: str) -> bool:
    if isinstance(value, dict):
        return value.get("$ref") == ref or any(
            has_ref(child, ref) for child in value.values()
        )
    if isinstance(value, list):
        return any(has_ref(child, ref) for child in value)
    return False


def tail(text: str, limit: int = 8) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def print_text(results: list[Result]) -> None:
    width = max(len(result.name) for result in results)
    print("Creator OS Doctor")
    print("=" * 17)
    for result in results:
        print(
            f"{result.status:<4} {result.name:<{width}} "
            f"{result.category} ({result.duration_ms}ms)"
        )
        print(f"     reason: {result.reason}")
        if result.evidence:
            for line in result.evidence.splitlines()[:8]:
                print(f"     evidence: {line}")
        if result.affected:
            print(f"     affected: {', '.join(result.affected[:8])}")
        if result.next_action != "None.":
            print(f"     next: {result.next_action}")
    failed = sum(1 for result in results if result.status == "FAIL")
    warned = sum(1 for result in results if result.status == "WARN")
    skipped = sum(1 for result in results if result.status == "SKIP")
    not_run = sum(1 for result in results if result.status == "NOT_RUN")
    passed = len(results) - failed - warned - skipped - not_run
    print(
        f"\nSummary: {failed} fail, {warned} warn, {not_run} not run, "
        f"{skipped} skip, {passed} pass"
    )


def self_check() -> int:
    assert tail("a\nb\n", limit=1) == "b"
    assert has_ref({"items": [{"$ref": "x.schema.json"}]}, "x.schema.json")
    assert repeated_keys(["A", "a", "b"]) == {"a"}
    fixture = load_fixture()
    business_fixture = load_business_fixture()
    assert fixture["replay_campaigns"]
    assert business_fixture["business_logic"]["decisions"]
    results = run_doctor(quick=True)
    result_names = {result.name for result in results}
    assert len(results) == 15
    business_results = run_doctor(quick=True, business_only=True)
    business_names = {result.name for result in business_results}
    assert len(business_results) == 31
    assert result_names >= {
        "pipeline-determinism",
        "lineage",
        "configuration",
        "observability",
    }
    # Gate-duplicate audits are gone; aspirational audits run only with --business.
    assert "architecture" not in result_names
    assert "contracts" not in result_names
    assert {"business-logic", "ceo-dashboard", "commercial-readiness"} <= business_names
    assert "commercial-readiness" not in result_names
    print("doctor self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
