"""Campaign <-> ContentForge handoff against REAL ContentForge output.

Campaign Factory's unit tests feed the ContentForge adapter hand-written mock
responses. Nothing checked those mocks against real CF output, and the CF audit
response is NOT governed by a pipeline_contracts schema -- so a shape change in
CF's `/api/similarity` route (a renamed field, a new verdict value) would leave
the Python mocks green while production breaks.

This test closes that seam: it feeds *captured real* ContentForge audit output
through campaign_factory's actual contract-assertion and decision functions.

Scope (bounded honestly): this proves the campaign<->CF response contract and the
block-path decision on genuine CF data. It is NOT a full reference->reel->campaign
end-to-end run (the generation stages need external paid APIs), and CF's quality
gate itself is already live-tested in apps/contentforge
(campaign-factory-report.test.js).

Refresh the goldens when CF's response shape changes:
    node apps/contentforge/scripts/capture-cf-golden.mjs
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_factory.adapters.contentforge import _extract_checks, _score_from_verdict
from campaign_factory.audio_smoke import assert_contentforge_contract_response

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "contentforge_audit"
GOLDENS = ["iphone_reel", "corrupt_video"]


def _load(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", GOLDENS)
def test_real_cf_output_satisfies_campaign_contract(name: str) -> None:
    """The drift guard: real CF output must satisfy campaign's response contract.

    Fails if apps/contentforge/app/api/similarity/route.js changes the response
    shape (overallVerdict, readinessSummary.uploadReady, auditProfile, ...) in a
    way campaign_factory does not expect.
    """
    response = _load(name)
    # Raises AssertionError on any shape drift.
    assert_contentforge_contract_response(response)


def test_block_decision_matches_real_cf_verdicts() -> None:
    """Campaign derives the correct (block) decision from real CF responses."""
    for name in GOLDENS:
        response = _load(name)
        failed, _warnings = _extract_checks(response)
        score = _score_from_verdict(response.get("overallVerdict"), min_score=70)
        # Mirrors the approve condition in adapters.contentforge._audit_asset.
        approved = (
            response.get("overallVerdict") == "pass" and score >= 70 and not failed
        )
        assert not approved, f"{name} should not be auto-approved (verdict=fail)"
        assert failed, f"{name} should surface failed checks from real CF output"


def test_distinct_real_failure_codes_are_read() -> None:
    """Campaign reads real per-asset block codes, not a flattened mock.

    The corrupt fixture is rejected for an invalid container; the structurally
    valid iphone reel is not -- it fails on creative-quality instead. If campaign
    flattened the response it could not tell these apart.
    """
    corrupt = _load("corrupt_video")["readinessSummary"].get("blockingCodes") or []
    iphone = _load("iphone_reel")["readinessSummary"].get("blockingCodes") or []
    assert "invalid_video" in corrupt
    assert "invalid_video" not in iphone
