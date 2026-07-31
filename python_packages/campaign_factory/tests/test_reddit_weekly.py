from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campaign_factory.reddit_weekly import (
    RESEARCH_SCHEMA,
    RedditResearchClient,
    _generation_requests,
    _register_reddit_still,
    build_weekly_briefs,
)
from campaign_test_support import make_factory
from creator_os_core.evidence_attestation import payload_fingerprint
from PIL import Image


def _research(name: str) -> dict:
    posts = [
        {
            "postId": f"post-{index}",
            "title": f"winner {index}?",
            "permalink": f"https://www.reddit.com/{name}/comments/post-{index}",
            "mediaUrl": f"https://preview.redd.it/post-{index}.jpg",
            "mediaType": "image",
            "flair": "selfie",
            "score": 100 - index,
            "commentCount": 10 - index,
            "listing": "top_week",
            "rank": index,
            "dimensions": {"width": 1080, "height": 1350},
        }
        for index in range(1, 4)
    ]
    core = {
        "schema": RESEARCH_SCHEMA,
        "subreddit": name,
        "fetchedAt": "2026-07-31T12:00:00Z",
        "ruleSourceUrl": f"https://www.reddit.com/{name}/about/rules",
        "officialRules": [
            {
                "shortName": "Original content",
                "description": "Post your own content.",
                "kind": "all",
                "violationReason": "",
            }
        ],
        "posts": posts,
    }
    return {**core, "researchFingerprint": payload_fingerprint(core)}


class _Response:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def test_reddit_client_uses_oauth_rules_and_weekly_listings() -> None:
    urls: list[str] = []

    def opener(request, timeout):
        assert timeout == 30
        urls.append(request.full_url)
        if request.full_url.endswith("/api/v1/access_token"):
            return _Response({"access_token": "token"})
        if request.full_url.endswith("/about/rules"):
            return _Response(
                {
                    "rules": [
                        {
                            "short_name": "Original",
                            "description": "Original work only.",
                            "kind": "all",
                        }
                    ]
                }
            )
        return _Response(
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "winner",
                                "title": "weekly winner",
                                "score": 50,
                                "num_comments": 4,
                                "created_utc": 1,
                                "permalink": "/r/example/comments/winner",
                                "preview": {
                                    "images": [
                                        {
                                            "source": {
                                                "url": "https://preview.redd.it/winner.jpg",
                                                "width": 1080,
                                                "height": 1350,
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    ]
                }
            }
        )

    client = RedditResearchClient(
        client_id="client",
        client_secret="secret",
        user_agent="creator-os:test by u/operator",
        opener=opener,
    )
    snapshot = client.subreddit_snapshot("r/example", limit=10)

    assert snapshot["officialRules"][0]["shortName"] == "Original"
    assert snapshot["posts"][0]["mediaUrl"] == ("https://preview.redd.it/winner.jpg")
    assert any("/r/example/top?" in url and "t=week" in url for url in urls)
    assert any("/r/example/rising?" in url for url in urls)


def test_weekly_brief_uses_live_winners_and_detects_unchanged_rules() -> None:
    research = _research("r/example")
    state = {
        "subreddits": [
            {
                "name": "r/example",
                "status": "active",
                "eligible_creators": ["larissa"],
                "eligible_accounts": [
                    "u/Serious_material571",
                    "u/Adventurous-bill-745",
                ],
                "required_content_tags": ["selfie"],
                "prohibited_content": ["watermark"],
                "rules_snapshot": {
                    "officialRules": research["officialRules"],
                },
            }
        ]
    }

    briefs, rows = build_weekly_briefs(
        state=state,
        creator_id="larissa",
        research_provider=lambda _name: research,
        created_at="2026-07-31T12:00:00Z",
    )

    assert rows == [research]
    assert len(briefs) == 1
    assert len(briefs[0]["concepts"]) == 3
    assert briefs[0]["referencePostIds"] == ["post-1", "post-2", "post-3"]
    assert briefs[0]["ruleChange"]["reviewRequired"] is False


def test_generation_requests_allocate_one_family_to_only_one_account() -> None:
    accounts = [
        {
            "username": username,
            "creator_id": "larissa",
            "creator_name": "Larissa",
            "is_active": True,
        }
        for username in (
            "u/Serious_material571",
            "u/Adventurous-bill-745",
        )
    ]
    briefs = []
    for subreddit in ("r/one", "r/two"):
        concepts = [
            {
                "conceptId": f"{subreddit}-{index}",
                "referencePostId": f"{subreddit}-post-{index}",
                "referenceMediaUrl": f"https://preview.redd.it/{index}.jpg",
                "referenceReviewRequired": True,
                "contentTags": ["selfie"],
            }
            for index in range(3)
        ]
        briefs.append(
            {
                "subreddit": subreddit,
                "briefFingerprint": payload_fingerprint({"subreddit": subreddit}),
                "eligibleAccounts": [row["username"] for row in accounts],
                "ruleChange": {"reviewRequired": False},
                "concepts": concepts,
            }
        )
    report = {"coverage": {row["username"]: {"uncoveredSlots": 2} for row in accounts}}

    requests = _generation_requests(
        state={"accounts": accounts},
        report=report,
        briefs=briefs,
        creator_id="larissa",
    )

    assert [request["accountUsername"] for request in requests] == [
        "u/Serious_material571",
        "u/Adventurous-bill-745",
        "u/Serious_material571",
        "u/Adventurous-bill-745",
    ]
    families = [request["contentFamilyId"] for request in requests]
    assert len(families) == len(set(families))


def test_uncovered_slot_still_creates_generation_request() -> None:
    account = {
        "username": "u/Serious_material571",
        "creator_id": "larissa",
        "creator_name": "Larissa",
        "is_active": True,
    }
    brief = {
        "subreddit": "r/one",
        "briefFingerprint": "b" * 64,
        "eligibleAccounts": [account["username"]],
        "ruleChange": {"reviewRequired": False},
        "concepts": [
            {
                "conceptId": "concept-1",
                "referencePostId": "post-1",
                "referenceMediaUrl": "https://preview.redd.it/one.jpg",
                "referenceReviewRequired": True,
                "contentTags": ["selfie"],
            }
        ],
    }

    requests = _generation_requests(
        state={"accounts": [account]},
        report={"coverage": {account["username"]: {"uncoveredSlots": 1}}},
        briefs=[brief],
        creator_id="larissa",
    )

    assert len(requests) == 1


def test_generated_still_registration_preserves_family_and_account(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        model = factory.domains.models.upsert_model("larissa")
        campaign = factory.domains.models.upsert_campaign("reddit-pilot", "larissa")
        still = tmp_path / "winner.png"
        Image.new("RGB", (64, 96), color=(80, 40, 30)).save(still)
        digest = hashlib.sha256(still.read_bytes()).hexdigest()
        factory.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, content_surface, platform, source_prompt,
             account_ids_json, status, created_at, updated_at)
            VALUES ('source-reddit', ?, ?, ?, ?, ?, ?, 'image', 'reddit',
                    'reddit', '{}', '[]', 'generated_qc_passed', ?, ?)
            """,
            (
                campaign["id"],
                model["id"],
                digest,
                str(still),
                str(still),
                still.name,
                "2026-07-31T12:00:00Z",
                "2026-07-31T12:00:00Z",
            ),
        )
        factory.conn.commit()
        request = {
            "requestId": "reddit-gen:test",
            "briefFingerprint": "b" * 64,
            "contentFamilyId": "reddit-family:test",
            "accountUsername": "u/Serious_material571",
            "concept": {
                "referencePostId": "winner",
                "referencePostUrl": "https://www.reddit.com/r/example/comments/winner",
                "contentTags": ["selfie"],
            },
        }

        asset = _register_reddit_still(
            factory,
            campaign_slug="reddit-pilot",
            candidate={"sourceAssetId": "source-reddit"},
            request=request,
        )

        metadata = json.loads(asset["metadata_json"])
        assert asset["media_type"] == "image"
        assert asset["content_surface"] == "reddit"
        assert metadata["sourceFamilyId"] == "reddit-family:test"
        assert metadata["redditProposedAssignment"]["newAccount"] == (
            "u/Serious_material571"
        )
        assert metadata["perceptualFingerprint"].startswith("phash64:")
    finally:
        factory.close()
