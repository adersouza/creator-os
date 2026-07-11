from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.learning_cohort import COHORT_ID, prepare_learning_cohort

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "run_learning_cohort_daily.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("run_learning_cohort_daily", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def factory(tmp_path: Path) -> CampaignFactory:
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=tmp_path / "reel_factory",
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def prepare(cf: CampaignFactory) -> None:
    prepare_learning_cohort(cf.conn, start_date="2026-07-11")
    cf.conn.execute(
        """UPDATE learning_cohort_assignments
        SET reference_id = 'reference_1', source_family = 'family_1',
            content_fingerprint = id || '_fingerprint'"""
    )
    cf.conn.commit()


def test_daily_cycle_previews_and_queues_due_day_idempotently(tmp_path: Path) -> None:
    module = load_module()
    cf = factory(tmp_path)
    try:
        prepare(cf)
        now = datetime.fromisoformat("2026-07-12T08:30:00-04:00")

        preview = module.run_daily_cycle(cf.conn, now=now, apply=False)
        applied = module.run_daily_cycle(cf.conn, now=now, apply=True)
        repeated = module.run_daily_cycle(cf.conn, now=now, apply=True)

        assert preview["status"] == "ready_to_queue"
        assert applied["status"] == "queued_for_generation"
        assert repeated["status"] == "queued_for_generation"
        assert {row["generationState"] for row in repeated["dueAssignments"]} == {
            "queued"
        }
        assert applied["providerCalls"] == 0
        assert applied["publishingActionsTaken"] == 0
    finally:
        cf.close()


def test_daily_cycle_fails_closed_on_unresolved_prior_handoff(
    tmp_path: Path,
) -> None:
    module = load_module()
    cf = factory(tmp_path)
    try:
        prepare(cf)
        prior = cf.conn.execute(
            """SELECT id FROM learning_cohort_assignments
            WHERE cohort_id = ? AND day_index = 1 AND surface = 'regular_reel'""",
            (COHORT_ID,),
        ).fetchone()["id"]
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET draft_id = 'draft_1', approval_state = 'approved',
                schedule_state = 'ready_for_manual_publish'
            WHERE id = ?""",
            (prior,),
        )
        cf.conn.commit()

        report = module.run_daily_cycle(
            cf.conn,
            now=datetime.fromisoformat("2026-07-12T08:30:00-04:00"),
            apply=True,
        )
        due_states = {
            row["generation_state"]
            for row in cf.conn.execute(
                """SELECT generation_state FROM learning_cohort_assignments
                WHERE cohort_id = ? AND day_index = 2""",
                (COHORT_ID,),
            ).fetchall()
        }

        assert report["status"] == "operator_action_required"
        assert report["blockingReasons"] == ["prior_approved_publish_not_confirmed"]
        assert report["unresolvedPriorHandoffs"][0]["id"] == prior
        assert due_states == {"planned"}
        assert report["creditsSpent"] == 0
        assert report["draftActionsTaken"] == 0
        assert report["scheduleActionsTaken"] == 0
        assert report["publishingActionsTaken"] == 0
    finally:
        cf.close()


def test_campaign_scope_is_exact() -> None:
    module = load_module()

    assert module.configured_campaigns(f'["{COHORT_ID}"]') == [COHORT_ID]
    try:
        module.configured_campaigns(f'["{COHORT_ID}", "other"]')
    except ValueError as exc:
        assert "exactly" in str(exc)
    else:
        raise AssertionError("broad cohort scope was accepted")
