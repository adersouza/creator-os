"""Creator OS shared foundational core.

Helpers deduplicated out of the three factory packages (campaign_factory,
reference_factory, reel_factory). This package imports *inward* only: it must
never import from any factory package or from pipeline_contracts.
"""
