from __future__ import annotations

import json
from pathlib import Path

from campaign_test_support import add_rendered_asset, make_factory


def test_operator_removal_rejects_without_recording_a_failure(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _, rendered_path = add_rendered_asset(cf, tmp_path)
        relocated_path = tmp_path / "Trash" / rendered_path.name
        relocated_path.parent.mkdir()
        rendered_path.rename(relocated_path)

        result = cf.domains.events.mark_asset_operator_removed(
            "asset_1",
            operator="operator",
            reason="scheduled duplicate already used",
            relocated_output_path=str(relocated_path),
            post_ids=["post_1"],
            cancellation_evidence=[{"postId": "post_1", "result": "cancelled"}],
        )

        asset = dict(
            cf.conn.execute(
                "SELECT review_state, audit_status, metadata_json FROM rendered_assets "
                "WHERE id = 'asset_1'"
            ).fetchone()
        )
        metadata = json.loads(asset["metadata_json"])
        event = cf.domains.events.events_for_asset("asset_1")[0]

        assert result["reviewState"] == "rejected"
        assert asset["review_state"] == "rejected"
        assert asset["audit_status"] == "pending"
        assert metadata["generationStatus"] == "completed"
        assert metadata["lifecycleStatus"] == "operator_removed"
        assert metadata["scheduleStatus"] == "cancelled"
        assert metadata["learningEligible"] is False
        assert metadata["technicalFailure"] is False
        assert metadata["providerFailure"] is False
        assert metadata["qcFailure"] is False
        assert metadata["operatorRemoval"]["relocatedOutputPath"] == str(relocated_path)
        assert metadata["operatorRemoval"]["relocatedContentSha"]
        assert event["eventType"] == "operator_media_removed"
        assert event["metadata"]["postIds"] == ["post_1"]
        assert event["metadata"]["scheduleStatus"] == "cancelled"
    finally:
        cf.close()
