"""Failure-injection regressions for read-only ThreadsDashboard post lookup."""

from __future__ import annotations

import pytest
from campaign_factory.adapters.threadsdash_client import (
    _select_post_by_id,
)


class _FakeClient:
    """Minimal SupabaseRestClient stand-in scripted per table."""

    def __init__(self, behaviors: dict[str, object]):
        self.behaviors = behaviors
        self.calls: list[str] = []

    def select(self, table: str, params: dict) -> list[dict]:
        self.calls.append(table)
        behavior = self.behaviors.get(table)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior or []


def test_select_post_by_id_propagates_transient_failure():
    client = _FakeClient({"posts": RuntimeError("Supabase request failed: HTTP 500")})
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _select_post_by_id(client, "post_1")


def test_select_post_by_id_missing_column_reads_as_absent():
    client = _FakeClient(
        {"posts": RuntimeError("column posts.media_urls does not exist (42703)")}
    )
    assert _select_post_by_id(client, "post_1") is None
