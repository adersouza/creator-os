from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.blocked_experiment_assignment import (
    validate_audio_experiment_exception,
    validate_factor_values,
)
from campaign_factory.blocked_experiment_reporting import (
    MIN_CLUSTER_ESS,
    _cluster_summary,
    _hierarchical_cluster_interval,
    _promotion_status,
    record_blocked_experiment_decision,
    rollback_blocked_experiment_policy,
)
from campaign_factory.content_director import build_plan
from campaign_factory.content_director_operations import design_experiment
from campaign_factory.learning_consumption import (
    apply_learning_to_production_plan,
    persist_learning_decision_receipt,
)
from campaign_factory.learning_governance import register_experiment_measurement
from campaign_factory.observed_experiment_reporting import (
    BLOCKED_ASSIGNMENT_METHOD,
    BLOCKED_MEASUREMENT_PLAN,
    EXPERIMENT_FACTORS,
    _metric_revision_reconciliation_reasons,
)
from campaign_test_support import make_factory
from test_content_director import _conn, _request

from pipeline_contracts import (
    ContractValidationError,
    validate_experiment_assignment_receipt,
)


def _plan(
    cf, *, factor: str = "overlay_timing", account: str = "account_a"
) -> tuple[str, str]:
    now = "2026-08-03T12:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO creative_plans
        (id, name, target_account, status, created_at, updated_at)
        VALUES ('blocked_root', 'blocked', ?, 'approved', ?, ?)
        """,
        (account, now, now),
    )
    cf.conn.execute(
        """
        INSERT INTO creative_plan_versions
        (id, creative_plan_id, version, creator, identity_profile, horizon_start,
         horizon_end, account_scope_json, timezone, objective,
         requested_output_count, autonomy_mode, status, input_fingerprint,
         created_at, updated_at)
        VALUES ('blocked_plan', 'blocked_root', 1, 'stacey', 'stacey',
                '2026-08-03', '2026-08-10', ?,
                'America/New_York', 'GROWTH', 2, 'SUPERVISED', 'APPROVED',
                ?, ?, ?)
        """,
        (json.dumps([account]), f"blocked-{factor}", now, now),
    )
    for index in range(2):
        cf.conn.execute(
            """
            INSERT INTO creative_plan_items
            (id, plan_version_id, item_index, creator, identity_profile,
             target_account, content_intent, pattern_family, prompt_text,
             desired_duration_seconds, audio_policy, exploration_class,
             priority, execution_state, created_at, updated_at)
            VALUES (?, 'blocked_plan', ?, 'stacey', 'stacey', ?,
                    'passive_selfie', 'passive', 'approved prompt', 5,
                    'embedded_trending_required', 'EXPLORE', ?,
                    'CREATIVE_APPROVED', ?, ?)
            """,
            (f"blocked_item_{index}", index, account, index + 1, now, now),
        )
    cf.conn.commit()
    return "blocked_plan", now


def _factor_values(*, timing: str, overlay: str = "hook_a") -> dict[str, str]:
    return {
        "source_family": "family_a",
        "overlay_text": overlay,
        "overlay_timing": timing,
        "audio_track": "track_a",
        "observed_profile": "normal",
        "motion_mode": "static_reel",
        "posting_window": "weekday_1830",
    }


def test_blocked_assignment_contract_rejects_unknown_or_empty_factor_values() -> None:
    example_path = (
        Path(__file__).parents[3]
        / "packages"
        / "pipeline_contracts"
        / "pipeline_contracts"
        / "schemas"
        / "experiment_assignment_receipt.v1.example.json"
    )
    receipt = json.loads(example_path.read_text(encoding="utf-8"))
    receipt.update(
        {
            "assignmentAlgorithmVersion": BLOCKED_ASSIGNMENT_METHOD,
            "changedVariable": "overlay_timing",
            "sourceFamilyBlockId": "family_a",
            "factorValues": _factor_values(timing="static"),
            "controlledValuesFingerprint": "c" * 64,
            "metricRevisionPolicy": "immutable_final_reconciled_observation.v1",
        }
    )
    validate_experiment_assignment_receipt(receipt)

    unknown = json.loads(json.dumps(receipt))
    unknown["factorValues"]["unexpected_factor"] = "value"
    with pytest.raises(ContractValidationError):
        validate_experiment_assignment_receipt(unknown)

    empty = json.loads(json.dumps(receipt))
    empty["factorValues"]["motion_mode"] = ""
    with pytest.raises(ContractValidationError):
        validate_experiment_assignment_receipt(empty)


def test_design_predeclares_generalized_block_controls(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        plan_id, _ = _plan(cf)
        receipt = design_experiment(
            cf.conn,
            plan_id=plan_id,
            changed_variable="overlay_timing",
            variants=("static", "timed"),
            hypothesis="timing changes equal-age reach",
            apply=True,
            assignment_method=BLOCKED_ASSIGNMENT_METHOD,
        )
        assert receipt["measurementPlan"] == BLOCKED_MEASUREMENT_PLAN
        assert receipt["requiredObservationCohort"] == ("24h_primary_72h_confirmatory")
        assert set(receipt["controlledVariables"]) == {
            "creator",
            "account",
            "content_intent",
            "observation_cohort",
            "publication_window",
            *EXPERIMENT_FACTORS,
        } - {"overlay_timing"}
        assert {item["experimentClass"] for item in receipt["assignments"]} == {
            "PENDING_BLOCKED_ROTATION"
        }
    finally:
        cf.close()


def test_factor_validation_rejects_a_second_changed_variable() -> None:
    assets = {
        role: {
            "id": f"{role}_asset",
            "parent_asset_id": "family_a",
            "metadata_json": json.dumps({"sourceFamilyId": "family_a"}),
        }
        for role in ("control", "treatment")
    }
    control = _factor_values(timing="static")
    treatment = _factor_values(timing="timed")
    normalized, fingerprint = validate_factor_values(
        changed_variable="overlay_timing",
        variants=["static", "timed"],
        factor_values=(control, treatment),
        assets=assets,
        source_family_block_id="family_a",
    )
    assert normalized["treatment"]["overlay_timing"] == "timed"
    assert len(fingerprint) == 64

    with pytest.raises(ValueError, match="differ only"):
        validate_factor_values(
            changed_variable="overlay_timing",
            variants=["static", "timed"],
            factor_values=(
                control,
                _factor_values(timing="timed", overlay="hook_b"),
            ),
            assets=assets,
            source_family_block_id="family_a",
        )


def test_exact_track_assignment_requires_operator_exception() -> None:
    with pytest.raises(PermissionError, match="reuse-policy exception"):
        validate_audio_experiment_exception(None)
    validate_audio_experiment_exception(
        {
            "exceptionId": "operator_exception_1",
            "authorizedBy": "operator",
            "reason": "bounded exact-track experiment",
            "scope": "exact_track_controlled_experiment",
        }
    )


def test_cluster_floor_matches_balanced_ninety_six_pair_matrix() -> None:
    blocks = [
        {
            "accountId": f"account_{index % 48}",
            "sourceFamilyBlockId": f"family_{index}",
            "primaryLift": 0.20,
            "confirmatoryLift": 0.15,
        }
        for index in range(96)
    ]
    summary = _cluster_summary(blocks)
    interval = _hierarchical_cluster_interval(blocks, seed="a" * 64, iterations=200)
    assert summary["accountClusterCount"] == 48
    assert summary["sourceFamilyBlockCount"] == 96
    assert summary["clusterAdjustedEffectiveSampleSize"] >= MIN_CLUSTER_ESS
    assert interval[0] > 0
    assert (
        _promotion_status(
            pair_count=96,
            cluster_summary=summary,
            median_lift=0.20,
            positive_percentage=1.0,
            interval=interval,
            guardrails_pass=True,
            confirmatory_pass=True,
        )
        == "operator_review_eligible"
    )


def test_metric_revision_must_match_latest_immutable_observation(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.conn.execute(
            """
            INSERT INTO performance_snapshot_observations
            (id, post_id, snapshot_at, source_hash, raw_json, normalized_json,
             created_at)
            VALUES ('obs_final', 'post_1', '2026-08-04T12:00:00+00:00', ?, '{}',
                    '{}', '2026-08-04T12:01:00+00:00')
            """,
            ("b" * 64,),
        )
        snapshot = {
            "post_id": "post_1",
            "snapshot_at": "2026-08-04T12:00:00+00:00",
        }
        raw = {
            "metric_revision_receipt": {
                "status": "final",
                "observationId": "obs_final",
                "sourceHash": "b" * 64,
            }
        }
        assert _metric_revision_reconciliation_reasons(cf.conn, snapshot, raw) == []
        raw["metric_revision_receipt"]["sourceHash"] = "c" * 64
        assert "metric_revision_source_hash_mismatch" in (
            _metric_revision_reconciliation_reasons(cf.conn, snapshot, raw)
        )
    finally:
        cf.close()


def test_adopted_policy_changes_choice_and_rollback_removes_it(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        plan_id, now = _plan(cf, factor="source_family")
        design = design_experiment(
            cf.conn,
            plan_id=plan_id,
            changed_variable="source_family",
            variants=("family_a", "family_b"),
            hypothesis="source family changes reach",
            apply=True,
            assignment_method=BLOCKED_ASSIGNMENT_METHOD,
        )
        report = {
            "schema": "creator_os.blocked_experiment_report.v1",
            "fingerprint": "d" * 64,
            "interpretation": {"status": "operator_review_eligible"},
        }
        cf.conn.execute(
            """
            UPDATE creative_plan_experiments
            SET interpretation_json = ?, status = 'MEASURED', updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(report), now, design["experimentId"]),
        )
        register_experiment_measurement(
            cf.conn, experiment_id=design["experimentId"], report=report
        )
        cf.conn.commit()
        decision = record_blocked_experiment_decision(
            cf.conn,
            experiment_id=design["experimentId"],
            operator="operator",
            decision="adopt",
            reason="qualified blocked result",
        )
        assert decision["productionUsageChanged"] is True
        sources = [
            {
                "id": "source_a",
                "status": "approved",
                "notes": json.dumps({"sourceFamilyId": "family_a"}),
            },
            {
                "id": "source_b",
                "status": "approved",
                "notes": json.dumps({"sourceFamilyId": "family_b"}),
            },
        ]
        selected, prompt, receipt = apply_learning_to_production_plan(
            cf.conn,
            creator="stacey",
            creator_identity_profile="stacey",
            account="account_a",
            intent="passive_selfie",
            sources=sources,
            base_prompt="base prompt",
        )
        assert [source["id"] for source in selected] == ["source_b"]
        assert prompt == "base prompt"
        assert receipt["learningInfluenced"] is True
        assert receipt["finalChoiceChanged"] is True
        assert receipt["eligibleFactorValuesBeforeLearning"] == [
            "family_a",
            "family_b",
        ]
        assert receipt["baseFactorValue"] == "family_a"
        assert receipt["finalFactorValue"] == "family_b"
        receipt_id = persist_learning_decision_receipt(
            cf.conn,
            decision=receipt,
            results=[{"jobId": "job_1", "status": "succeeded", "result": {}}],
        )
        persisted = cf.conn.execute(
            "SELECT decision_payload_json FROM manager_decisions WHERE id = ?",
            (receipt_id,),
        ).fetchone()
        assert persisted is not None
        payload = json.loads(persisted["decision_payload_json"])
        assert payload["learningInfluenced"] is True
        assert payload["finalChoiceChanged"] is True
        assert payload["eligibleFactorValuesBeforeLearning"] == [
            "family_a",
            "family_b",
        ]
        assert payload["baseFactorValue"] == "family_a"
        assert payload["finalFactorValue"] == "family_b"

        rollback = rollback_blocked_experiment_policy(
            cf.conn,
            experiment_id=design["experimentId"],
            operator="operator",
            reason="72h guardrail regression",
        )
        assert rollback["productionUsageChanged"] is True
        selected, _, receipt = apply_learning_to_production_plan(
            cf.conn,
            creator="stacey",
            creator_identity_profile="stacey",
            account="account_a",
            intent="passive_selfie",
            sources=sources,
            base_prompt="base prompt",
        )
        assert [source["id"] for source in selected] == ["source_a", "source_b"]
        assert receipt["finalChoiceChanged"] is False
    finally:
        cf.close()


def test_adopted_family_constrains_content_director_batch_and_rollback_restores_it(
    tmp_path: Path,
) -> None:
    conn = _conn(tmp_path)
    for source_id, family in (
        ("src_0", "family_a"),
        ("src_1", "family_b"),
        ("src_2", "family_b"),
    ):
        row = conn.execute(
            "SELECT notes FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()
        notes = json.loads(row["notes"])
        notes["sourceFamilyId"] = family
        conn.execute(
            "UPDATE source_assets SET notes = ? WHERE id = ?",
            (json.dumps(notes), source_id),
        )
    plan_id, now = _plan(
        SimpleNamespace(conn=conn),
        factor="source_family",
        account="stacey-main",
    )
    design = design_experiment(
        conn,
        plan_id=plan_id,
        changed_variable="source_family",
        variants=("family_a", "family_b"),
        hypothesis="source family changes reach",
        apply=True,
        assignment_method=BLOCKED_ASSIGNMENT_METHOD,
    )
    report = {
        "schema": "creator_os.blocked_experiment_report.v1",
        "fingerprint": "f" * 64,
        "interpretation": {"status": "operator_review_eligible"},
    }
    conn.execute(
        """
        UPDATE creative_plan_experiments
        SET interpretation_json = ?, status = 'MEASURED', updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(report), now, design["experimentId"]),
    )
    register_experiment_measurement(
        conn, experiment_id=design["experimentId"], report=report
    )
    conn.commit()
    record_blocked_experiment_decision(
        conn,
        experiment_id=design["experimentId"],
        operator="operator",
        decision="adopt",
        reason="qualified source-family result",
    )

    adopted = build_plan(conn, _request(output_count=10))
    adopted_scoped_items = [
        item for item in adopted["items"] if item["contentIntent"] == "passive_selfie"
    ]
    assert len(adopted_scoped_items) == 2
    assert {item["sourceAssetId"] for item in adopted_scoped_items} <= {
        "src_1",
        "src_2",
    }, json.dumps(
        [item["learningDecision"] for item in adopted_scoped_items], sort_keys=True
    )
    assert all(
        item["learningDecision"]["learningInfluenced"] is True
        and item["learningDecision"]["finalChoiceChanged"] is True
        and item["learningDecision"]["eligibleFactorValuesBeforeLearning"]
        == ["family_a", "family_b"]
        and item["learningDecision"]["baseFactorValue"] == "family_a"
        and item["learningDecision"]["finalFactorValue"] == "family_b"
        for item in adopted_scoped_items
    )

    rollback_blocked_experiment_policy(
        conn,
        experiment_id=design["experimentId"],
        operator="operator",
        reason="rollback test",
    )
    restored = build_plan(conn, _request(output_count=10))
    restored_scoped_items = [
        item for item in restored["items"] if item["contentIntent"] == "passive_selfie"
    ]
    assert "src_0" in {item["sourceAssetId"] for item in restored_scoped_items}
    assert all(
        item["learningDecision"]["finalChoiceChanged"] is False
        for item in restored_scoped_items
    )


def test_factor_without_production_consumer_cannot_be_adopted(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        plan_id, now = _plan(cf)
        design = design_experiment(
            cf.conn,
            plan_id=plan_id,
            changed_variable="overlay_timing",
            variants=("static", "timed"),
            hypothesis="timing changes reach",
            apply=True,
            assignment_method=BLOCKED_ASSIGNMENT_METHOD,
        )
        report = {
            "schema": "creator_os.blocked_experiment_report.v1",
            "fingerprint": "e" * 64,
            "interpretation": {"status": "operator_review_eligible"},
        }
        cf.conn.execute(
            """
            UPDATE creative_plan_experiments
            SET interpretation_json = ?, status = 'MEASURED', updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(report), now, design["experimentId"]),
        )
        register_experiment_measurement(
            cf.conn, experiment_id=design["experimentId"], report=report
        )
        cf.conn.commit()

        with pytest.raises(ValueError, match="no active production consumer"):
            record_blocked_experiment_decision(
                cf.conn,
                experiment_id=design["experimentId"],
                operator="operator",
                decision="adopt",
                reason="not connected",
            )
    finally:
        cf.close()
