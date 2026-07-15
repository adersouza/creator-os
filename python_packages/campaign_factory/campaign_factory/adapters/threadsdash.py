"""Supported Campaign Factory port to ThreadsDashboard.

Implementation stays in the owning handshake, account-projection, draft, and
metrics modules.  This module intentionally exposes only the five operations
that cross the Campaign Factory boundary; internal callers import the owning
module directly.
"""

from .threadsdash_account_projection import (
    sync_threadsdash_instagram_accounts as sync_accounts,
)
from .threadsdash_draft_delivery import export_threadsdash as export_drafts
from .threadsdash_draft_readiness import (
    verify_threadsdash_export as verify_export,
)
from .threadsdash_handshake import run_threadsdash_handshake as handshake
from .threadsdash_metrics_ingestion import (
    sync_performance_snapshots as sync_metrics,
)

__all__ = [
    "export_drafts",
    "handshake",
    "sync_accounts",
    "sync_metrics",
    "verify_export",
]
