"""Failure-injection regression: dedup lookups must not swallow transient errors.

Before the fix, _select_existing_campaign_factory_post and _select_post_by_id
caught every RuntimeError from SupabaseRestClient and treated it as "no
existing post". A provider 500 / timeout mid-export therefore made the caller
insert a *duplicate* post, silently defeating the post_key dedup that makes
export reruns safe. Only genuine schema mismatches (missing table/column on
older dashboards) may fall through to the fallback lookup.
"""

from __future__ import annotations

import pytest
from campaign_factory.adapters.threadsdash import (
    _select_existing_campaign_factory_post,
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


def test_transient_link_lookup_failure_propagates():
    client = _FakeClient(
        {
            "campaign_factory_post_links": RuntimeError(
                "Supabase request failed: HTTP 500 internal error"
            ),
        }
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _select_existing_campaign_factory_post(
            client, user_id="user_1", post_key="key_1"
        )
    # Must not have fallen through to the posts metadata lookup.
    assert client.calls == ["campaign_factory_post_links"]


def test_transient_posts_metadata_lookup_failure_propagates():
    client = _FakeClient(
        {
            "campaign_factory_post_links": [],
            "posts": RuntimeError("Supabase request failed: HTTP 503 timeout"),
        }
    )
    with pytest.raises(RuntimeError, match="HTTP 503"):
        _select_existing_campaign_factory_post(
            client, user_id="user_1", post_key="key_1"
        )


def test_missing_table_still_falls_back_to_metadata_lookup():
    """Older dashboards without campaign_factory_post_links keep working."""
    client = _FakeClient(
        {
            "campaign_factory_post_links": RuntimeError(
                'relation "campaign_factory_post_links" does not exist'
            ),
            "posts": [
                {
                    "id": "post_9",
                    "status": "draft",
                    "platform": "instagram",
                    "media_urls": [],
                    "metadata": {"campaign_factory": {"post_key": "key_1"}},
                }
            ],
        }
    )
    found = _select_existing_campaign_factory_post(
        client, user_id="user_1", post_key="key_1"
    )
    assert found is not None
    assert found["id"] == "post_9"
    assert client.calls == ["campaign_factory_post_links", "posts"]


def test_select_post_by_id_propagates_transient_failure():
    client = _FakeClient({"posts": RuntimeError("Supabase request failed: HTTP 500")})
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _select_post_by_id(client, "post_1")


def test_select_post_by_id_missing_column_reads_as_absent():
    client = _FakeClient(
        {"posts": RuntimeError("column posts.media_urls does not exist (42703)")}
    )
    assert _select_post_by_id(client, "post_1") is None
