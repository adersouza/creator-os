from __future__ import annotations

import json
from pathlib import Path

from campaign_factory import state_ownership
from campaign_test_support import make_factory


def test_state_explain_uses_machine_registry() -> None:
    result = state_ownership.explain_state("threadsdash_exports")
    assert result["ok"] is True
    assert result["repository"] == "creator-os"
    assert result["classification"] == "canonical"


def test_bridge_reconcile_attaches_matching_acknowledgment(
    tmp_path: Path, monkeypatch
) -> None:
    factory = make_factory(tmp_path)
    campaign = factory.domains.models.upsert_campaign("may", "model")
    sha = "a" * 64
    factory.conn.execute(
        """
        INSERT INTO threadsdash_exports
        (id, campaign_id, manifest_path, user_id, dry_run, status,
         final_sha256s_json, created_at)
        VALUES ('tdexp_1', ?, 'manifest.json', 'user_1', 0,
                'acceptance_unknown', ?, '2026-07-29T00:00:00Z')
        """,
        (campaign["id"], json.dumps([sha])),
    )
    monkeypatch.setattr(
        state_ownership,
        "reconcile_draft_handoff",
        lambda **_kwargs: {
            "acknowledgment": {
                "status": "accepted",
                "items": [{"submittedContentSha256": sha}],
            }
        },
    )

    result = state_ownership.reconcile_bridge(factory)

    assert result["ok"] is True
    assert result["acknowledgmentsAttached"] == ["tdexp_1"]
    row = factory.conn.execute(
        "SELECT status, acknowledgment_json FROM threadsdash_exports"
    ).fetchone()
    assert row["status"] == "accepted"
    assert json.loads(row["acknowledgment_json"])["status"] == "accepted"
    factory.close()
