"""The domain registry must actually be built, with every repository attached.

This exists because of a specific near-miss: an automated edit deleted the whole
``self.domains = CampaignDomainServices(...)`` assignment in ``core.py``. Ruff
passed and pytest collected 2313 tests, because nothing imports ``domains`` at
module scope — every call goes through ``factory.domains.<repo>`` at runtime.
Only a mypy count going *up* revealed it.

A count plus an explicit name set is cheap and fails loudly the moment the
dependency-injection graph loses a limb.
"""

from __future__ import annotations

from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory

# Every repository the control plane reaches through ``factory.domains``.
# Add a name here when a domain is genuinely added; never trim this list to make
# a failing run pass.
EXPECTED_DOMAINS = frozenset(
    {
        "account_memory",
        "account_planning",
        "account_reward_baselines",
        "asset_import",
        "audio_operations",
        "audio_recommendations",
        "audit_report",
        "audit_report_payload",
        "autonomy",
        "campaign_by_slug",
        "campaign_dirs",
        "campaign_overview",
        "caption_family",
        "close",
        "conn",
        "context",
        "creative_planning",
        "creator_governance",
        "creator_label",
        "discoverability",
        "distribution",
        "ensure_graph_edge_strict",
        "events",
        "exceptions",
        "export_summary",
        "finished_video",
        "first_lineage_value",
        "graph",
        "inventory_perceptual",
        "inventory_planning",
        "inventory_reservations",
        "lifecycle_reporting",
        "list_campaigns",
        "live_scale",
        "make_batch_repo",
        "models",
        "operational_proofs",
        "performance_summary_repo",
        "publishability",
        "ratio",
        "recommendation_accuracy_repo",
        "recommendations",
        "reel_execution",
        "reel_factory_reports",
        "reference",
        "rendered_asset",
        "rendered_for_campaign",
        "road_to_accounts_payload",
        "score_fraction",
        "settings",
        "surface_from_pattern",
        "surface_handoff",
        "truthy",
        "variant_lineage",
        "wilson_lower_bound",
    }
)


def test_domain_registry_is_fully_constructed() -> None:
    """``factory.domains`` must exist and expose every registered repository."""

    factory = CampaignFactory(Settings())
    try:
        domains = factory.domains
        assert domains is not None, "factory.domains was never constructed"
        present = {name for name in dir(domains) if not name.startswith("_")}
        missing = EXPECTED_DOMAINS - present
        assert not missing, f"domain registry lost repositories: {sorted(missing)}"
    finally:
        factory.domains.close()
