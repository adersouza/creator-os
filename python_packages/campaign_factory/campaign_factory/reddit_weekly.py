"""Weekly Reddit research, library matching, and approved generation planning."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from creator_os_core.fileops import atomic_write_json, sha256_file
from reel_factory.worker_api import media_identity

from .core import new_id, sanitize_for_storage
from .front_generation_stage import run_front_generation_stage
from .generation_execution_plan import build_generation_execution_plan
from .persistence import utc_now
from .reddit_handoff import (
    build_reddit_trend_brief,
    set_reddit_proposed_assignment,
    write_reddit_trend_brief,
)
from .reddit_library import build_reddit_library_report

RESEARCH_SCHEMA = "campaign_factory.reddit_weekly_research.v1"
PLAN_SCHEMA = "campaign_factory.reddit_weekly_plan.v1"
GENERATION_REQUEST_SCHEMA = "campaign_factory.reddit_generation_request.v1"
_SUBREDDIT_RE = re.compile(r"^(?:r/)?([A-Za-z0-9_]{2,21})$")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _value(row: Mapping[str, Any], snake: str, camel: str | None = None) -> Any:
    return row.get(snake, row.get(camel or snake))


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name}_required")
    return text


def _subreddit(value: Any) -> str:
    match = _SUBREDDIT_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("reddit_subreddit_invalid")
    return f"r/{match.group(1)}"


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _canonical_rules(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in _list(value):
        rule = _object(item)
        rows.append(
            {
                "shortName": str(rule.get("short_name") or rule.get("shortName") or ""),
                "description": str(rule.get("description") or ""),
                "kind": str(rule.get("kind") or "all"),
                "violationReason": str(
                    rule.get("violation_reason") or rule.get("violationReason") or ""
                ),
            }
        )
    return rows


def _listing_children(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = _object(payload.get("data"))
    return [
        _object(_object(item).get("data"))
        for item in _list(data.get("children"))
        if _object(_object(item).get("data"))
    ]


def _media_url(post: Mapping[str, Any]) -> str | None:
    preview = _object(post.get("preview"))
    images = _list(preview.get("images"))
    source = _object(_object(images[0]).get("source")) if images else {}
    value = str(source.get("url") or "").replace("&amp;", "&")
    if value:
        return value
    if str(post.get("post_hint") or "") == "image":
        value = str(post.get("url_overridden_by_dest") or post.get("url") or "")
        host = (urlparse(value).hostname or "").lower()
        if host.endswith(".redd.it") and value.lower().split("?", 1)[0].endswith(
            _IMAGE_SUFFIXES
        ):
            return value
    return None


def _post_record(post: Mapping[str, Any], *, listing: str, rank: int) -> dict[str, Any]:
    preview = _object(post.get("preview"))
    images = _list(preview.get("images"))
    source = _object(_object(images[0]).get("source")) if images else {}
    width = int(source.get("width") or 0)
    height = int(source.get("height") or 0)
    return {
        "postId": str(post.get("id") or ""),
        "title": str(post.get("title") or "").strip(),
        "permalink": (
            "https://www.reddit.com" + str(post.get("permalink") or "")
            if post.get("permalink")
            else None
        ),
        "mediaUrl": _media_url(post),
        "mediaType": (
            "image"
            if _media_url(post)
            else "gallery"
            if post.get("is_gallery")
            else "video"
            if post.get("is_video")
            else "link"
        ),
        "flair": post.get("link_flair_text"),
        "score": int(post.get("score") or 0),
        "commentCount": int(post.get("num_comments") or 0),
        "createdUtc": float(post.get("created_utc") or 0),
        "over18": bool(post.get("over_18")),
        "listing": listing,
        "rank": rank,
        "dimensions": {"width": width, "height": height},
    }


class RedditResearchClient:
    """Small official OAuth client for rules and public subreddit listings."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        user_agent: str,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.client_id = _required_text(client_id, "reddit_client_id")
        self.client_secret = _required_text(client_secret, "reddit_client_secret")
        self.user_agent = _required_text(user_agent, "reddit_user_agent")
        self._opener = opener
        self._access_token: str | None = None

    @classmethod
    def from_env(cls) -> RedditResearchClient:
        return cls(
            client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.environ.get("REDDIT_USER_AGENT", ""),
        )

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode("ascii")
        request = Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urlencode({"grant_type": "client_credentials"}).encode("ascii"),
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
        )
        with self._opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = str(_object(payload).get("access_token") or "")
        if not token:
            raise RuntimeError("reddit_oauth_access_token_missing")
        self._access_token = token
        return token

    def _get(self, path: str, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = "https://oauth.reddit.com" + path
        if query:
            url += "?" + urlencode({key: value for key, value in query.items()})
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        with self._opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("reddit_api_response_invalid")
        return payload

    def subreddit_snapshot(self, name: str, *, limit: int = 25) -> dict[str, Any]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= 100:
            raise ValueError("reddit_research_limit_must_be_1_to_100")
        normalized = _subreddit(name)
        slug = quote(normalized.removeprefix("r/"), safe="")
        rules_payload = self._get(f"/r/{slug}/about/rules")
        posts: dict[str, dict[str, Any]] = {}
        for listing, query in (
            ("top_week", {"limit": limit, "t": "week", "raw_json": 1}),
            ("hot", {"limit": limit, "raw_json": 1}),
            ("rising", {"limit": limit, "raw_json": 1}),
        ):
            path = "top" if listing == "top_week" else listing
            payload = self._get(f"/r/{slug}/{path}", query)
            for rank, post in enumerate(_listing_children(payload), start=1):
                post_id = str(post.get("id") or "")
                if not post_id:
                    continue
                candidate = _post_record(post, listing=listing, rank=rank)
                current = posts.get(post_id)
                if current is None or candidate["score"] > current["score"]:
                    posts[post_id] = candidate
        ordered = sorted(
            posts.values(),
            key=lambda item: (
                item["listing"] != "top_week",
                -int(item["score"]),
                -int(item["commentCount"]),
                int(item["rank"]),
            ),
        )
        core = {
            "schema": RESEARCH_SCHEMA,
            "subreddit": normalized,
            "fetchedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "ruleSourceUrl": f"https://www.reddit.com/{normalized}/about/rules",
            "officialRules": _canonical_rules(rules_payload.get("rules")),
            "posts": ordered,
        }
        return {**core, "researchFingerprint": _fingerprint(core)}


def _concepts(
    research: Mapping[str, Any],
    *,
    required_tags: list[str],
) -> list[dict[str, Any]]:
    posts = [_object(item) for item in _list(research.get("posts"))]
    visual = [post for post in posts if post.get("mediaUrl")]
    selected = (visual or posts)[:3]
    concepts: list[dict[str, Any]] = []
    while len(selected) < 3:
        selected.append({})
    for index, post in enumerate(selected):
        post_id = str(post.get("postId") or f"no-reference-{index + 1}")
        dimensions = _object(post.get("dimensions"))
        core = {
            "conceptId": (
                "reddit-concept:"
                + _fingerprint(
                    {
                        "subreddit": research["subreddit"],
                        "postId": post_id,
                        "index": index,
                    }
                )[:20]
            ),
            "referencePostId": post.get("postId"),
            "referencePostUrl": post.get("permalink"),
            "referenceMediaUrl": post.get("mediaUrl"),
            "referenceMediaType": post.get("mediaType"),
            "referenceDimensions": dimensions,
            "referenceReviewRequired": bool(post.get("mediaUrl")),
            "titlePattern": (
                "question" if "?" in str(post.get("title") or "") else "short_statement"
            ),
            "sourceTitle": post.get("title"),
            "sourceFlair": post.get("flair"),
            "contentTags": sorted(
                {
                    *required_tags,
                    *(
                        [str(post.get("flair")).strip().lower()]
                        if post.get("flair")
                        else []
                    ),
                }
            ),
            "generationIntent": (
                "Use the approved weekly reference for composition and setting, "
                "replace the person with the selected creator Soul identity, and "
                "retain the low-effort handheld aesthetic."
            ),
        }
        concepts.append({**core, "conceptFingerprint": _fingerprint(core)})
    return concepts


def build_weekly_briefs(
    *,
    state: Mapping[str, Any],
    creator_id: str,
    research_provider: Callable[[str], dict[str, Any]],
    created_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    briefs: list[dict[str, Any]] = []
    research_rows: list[dict[str, Any]] = []
    for row_value in _list(state.get("subreddits")):
        row = _object(row_value)
        if _value(row, "status") != "active":
            continue
        eligible_creators = [
            str(value)
            for value in _list(_value(row, "eligible_creators", "eligibleCreators"))
        ]
        if creator_id not in eligible_creators:
            continue
        name = _subreddit(_value(row, "name"))
        research = research_provider(name)
        research_rows.append(research)
        required_tags = [
            str(value).strip().lower()
            for value in _list(
                _value(row, "required_content_tags", "requiredContentTags")
            )
            if str(value).strip()
        ]
        catalog_rules = _object(_value(row, "rules_snapshot", "rulesSnapshot"))
        previous_official = _canonical_rules(catalog_rules.get("officialRules"))
        current_official = _canonical_rules(research.get("officialRules"))
        rule_changed = previous_official != current_official
        concepts = _concepts(research, required_tags=required_tags)
        patterns = [
            {
                "postId": post.get("postId"),
                "listing": post.get("listing"),
                "rank": post.get("rank"),
                "score": post.get("score"),
                "commentCount": post.get("commentCount"),
                "mediaType": post.get("mediaType"),
                "dimensions": post.get("dimensions"),
                "flair": post.get("flair"),
            }
            for post in _list(research.get("posts"))[:10]
        ] or [{"status": "no_posts_returned"}]
        brief = build_reddit_trend_brief(
            {
                "subreddit": name,
                "snapshotDate": created_at[:10],
                "ruleSourceUrl": research["ruleSourceUrl"],
                "rules": catalog_rules,
                "eligibleCreators": eligible_creators,
                "eligibleAccounts": _list(
                    _value(row, "eligible_accounts", "eligibleAccounts")
                ),
                "requiredContentTags": required_tags,
                "disallowedElements": _list(
                    _value(row, "prohibited_content", "prohibitedContent")
                ),
                "patterns": patterns,
                "titlePattern": _object(_value(row, "title_rules", "titleRules")),
                "promotionPolicy": _object(
                    _value(row, "promotion_rules", "promotionRules")
                ),
                "firstCommentPolicy": {
                    "allowed": bool(
                        _value(row, "first_comment_allowed", "firstCommentAllowed")
                    )
                },
                "concepts": concepts,
                "referencePostIds": [
                    concept["referencePostId"]
                    for concept in concepts
                    if concept.get("referencePostId")
                ],
                "researchEvidence": {
                    "schema": research["schema"],
                    "researchFingerprint": research["researchFingerprint"],
                    "fetchedAt": research["fetchedAt"],
                },
                "ruleChange": {
                    "changed": rule_changed,
                    "reviewRequired": rule_changed,
                    "catalogOfficialRulesFingerprint": _fingerprint(previous_official),
                    "fetchedOfficialRulesFingerprint": _fingerprint(current_official),
                    "fetchedOfficialRules": current_official,
                },
            },
            created_at=created_at,
        )
        briefs.append(brief)
    return briefs, research_rows


def _cards(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    views = _object(report.get("views"))
    return [
        _object(card)
        for name in ("Ready", "Exhausted")
        for card in _list(views.get(name))
        if _object(card).get("approvalState") == "approved"
    ]


def _match_candidates(
    report: Mapping[str, Any],
    briefs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for card in _cards(report):
        tags = {
            str(value).strip().lower()
            for value in [
                *_list(card.get("contentTags")),
                *_list(card.get("compositionTags")),
            ]
            if str(value).strip()
        }
        for brief in briefs:
            required = {
                str(value).strip().lower()
                for value in _list(brief.get("requiredContentTags"))
                if str(value).strip()
            }
            if required and not required.issubset(tags):
                continue
            matches.append(
                {
                    "assetId": card["assetId"],
                    "accountUsername": card.get("accountUsername"),
                    "subreddit": brief["subreddit"],
                    "briefFingerprint": brief["briefFingerprint"],
                    "matchedTags": sorted(required),
                    "requiresExactTaskApproval": True,
                }
            )
    return matches


def _generation_requests(
    *,
    state: Mapping[str, Any],
    report: Mapping[str, Any],
    briefs: list[dict[str, Any]],
    creator_id: str,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    claimed_families = {
        str(_value(_object(owner), "identity_value", "identityValue"))
        for owner in _list(state.get("contentOwners"))
        if _value(_object(owner), "identity_type", "identityType") == "source_family"
    }
    accounts = {
        str(_value(_object(row), "username")): _object(row)
        for row in _list(state.get("accounts"))
        if str(_value(_object(row), "creator_id", "creatorId")) == creator_id
        and _value(_object(row), "is_active", "isActive") is True
    }
    coverage = _object(report.get("coverage"))
    remaining_by_account: dict[str, int] = {}
    candidates_by_account: dict[
        str, list[tuple[dict[str, Any], dict[str, Any], str]]
    ] = {}
    for username, account in accounts.items():
        uncovered = int(_object(coverage.get(username)).get("uncoveredSlots") or 0)
        remaining_by_account[username] = max(0, uncovered)
        eligible = [
            brief
            for brief in briefs
            if username in [str(value) for value in _list(brief["eligibleAccounts"])]
        ]
        candidates_by_account[username] = [
            (
                brief,
                _object(concept),
                "reddit-family:"
                + _fingerprint(
                    {
                        "creator": creator_id,
                        "reference": str(
                            _object(concept).get("referencePostId")
                            or _object(concept)["conceptId"]
                        ),
                    }
                )[:24],
            )
            for brief in eligible
            if not _object(brief.get("ruleChange")).get("reviewRequired")
            for concept in _list(brief.get("concepts"))
        ]

    cursors = {username: 0 for username in accounts}
    positions = {username: 0 for username in accounts}
    while any(remaining_by_account.values()):
        progressed = False
        for username, account in accounts.items():
            if remaining_by_account.get(username, 0) <= 0:
                continue
            candidates = candidates_by_account.get(username, [])
            while cursors[username] < len(candidates):
                brief, concept, family = candidates[cursors[username]]
                cursors[username] += 1
                if family in claimed_families:
                    continue
                break
            else:
                remaining_by_account[username] = 0
                continue
            claimed_families.add(family)
            remaining_by_account[username] -= 1
            positions[username] += 1
            progressed = True
            core = {
                "schema": GENERATION_REQUEST_SCHEMA,
                "creatorId": creator_id,
                "creatorName": str(
                    _value(account, "creator_name", "creatorName") or creator_id
                ),
                "accountUsername": username,
                "subreddit": brief["subreddit"],
                "briefFingerprint": brief["briefFingerprint"],
                "concept": concept,
                "contentFamilyId": family,
                "referenceReviewRequired": bool(concept.get("referenceReviewRequired")),
                "referenceMediaUrl": concept.get("referenceMediaUrl"),
                "referenceLocalPath": None,
                "referenceMediaSha256": None,
                "status": (
                    "awaiting_reference_review"
                    if concept.get("referenceMediaUrl")
                    else "blocked_no_visual_reference"
                ),
                "queuePosition": positions[username],
            }
            requests.append(
                {
                    **core,
                    "requestId": "reddit-gen:" + _fingerprint(core)[:24],
                    "requestFingerprint": _fingerprint(core),
                }
            )
        if not progressed:
            break
    return requests


def _download_reference(
    *,
    url: str,
    destination: Path,
    user_agent: str,
    opener: Callable[..., Any] = urlopen,
) -> tuple[Path, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(".redd.it"):
        raise ValueError("reddit_reference_media_host_not_allowed")
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "image/*"})
    with opener(request, timeout=30) as response:
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError("reddit_reference_media_not_image")
        data = response.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("reddit_reference_media_too_large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    os.replace(temporary, destination)
    return destination, sha256_file(destination)


def prepare_reddit_weekly_plan(
    factory: Any,
    *,
    campaign_slug: str,
    state: Mapping[str, Any],
    research_provider: Callable[[str], dict[str, Any]],
    as_of: str | None = None,
    download_references: bool = False,
    reference_user_agent: str | None = None,
    reference_opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    created_at = as_of or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    creator_id = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    briefs, research = build_weekly_briefs(
        state=state,
        creator_id=creator_id,
        research_provider=research_provider,
        created_at=created_at,
    )
    report = build_reddit_library_report(
        factory,
        campaign_slug=campaign_slug,
        state=dict(state),
        as_of=created_at,
    )
    matches = _match_candidates(report, briefs)
    requests = _generation_requests(
        state=state,
        report=report,
        briefs=briefs,
        creator_id=creator_id,
    )
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    directory = (
        factory.domains.campaign_dirs(model_slug, campaign_slug)["sources"]
        / "reddit_weekly"
        / created_at[:10]
    )
    if download_references:
        user_agent = _required_text(
            reference_user_agent or os.environ.get("REDDIT_USER_AGENT"),
            "reddit_user_agent",
        )
        for request in requests:
            media_url = str(request.get("referenceMediaUrl") or "")
            if not media_url:
                continue
            destination = (
                directory
                / request["subreddit"].removeprefix("r/")
                / f"{request['requestId'].split(':')[-1]}.jpg"
            )
            path, digest = _download_reference(
                url=media_url,
                destination=destination,
                user_agent=user_agent,
                opener=reference_opener,
            )
            request["referenceLocalPath"] = str(path)
            request["referenceMediaSha256"] = digest
            request["status"] = "awaiting_reference_review"
            request["requestFingerprint"] = _fingerprint(
                {
                    key: value
                    for key, value in request.items()
                    if key != "requestFingerprint"
                }
            )
    for brief in briefs:
        write_reddit_trend_brief(factory, campaign_slug=campaign_slug, brief=brief)
    core = {
        "schema": PLAN_SCHEMA,
        "campaignId": str(campaign["id"]),
        "campaignSlug": campaign_slug,
        "creatorId": creator_id,
        "createdAt": created_at,
        "stateAsOf": state.get("asOf"),
        "briefs": briefs,
        "research": research,
        "libraryReport": report,
        "matchCandidates": matches,
        "generationRequests": requests,
        "summary": {
            "briefCount": len(briefs),
            "matchCandidateCount": len(matches),
            "generationRequestCount": len(requests),
            "blockedRuleReviewCount": sum(
                bool(_object(brief.get("ruleChange")).get("reviewRequired"))
                for brief in briefs
            ),
        },
    }
    plan = {**core, "planFingerprint": _fingerprint(core)}
    output = directory / f"weekly-plan-{plan['planFingerprint'][:16]}.json"
    atomic_write_json(output, plan)
    return {**plan, "artifactPath": str(output)}


def _register_reddit_still(
    factory: Any,
    *,
    campaign_slug: str,
    candidate: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    source_asset = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = ? AND campaign_id = ?",
        (candidate["sourceAssetId"], campaign["id"]),
    ).fetchone()
    if not source_asset:
        raise ValueError("reddit_generated_source_asset_missing")
    source = dict(source_asset)
    path = Path(str(source["stored_path"])).expanduser().resolve()
    digest = sha256_file(path)
    if digest != str(source["content_hash"]):
        raise ValueError("reddit_generated_source_asset_sha_mismatch")
    existing = factory.conn.execute(
        """
        SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND recipe = 'reddit_trend_soul_still'
          AND content_hash = ?
        ORDER BY created_at, id LIMIT 1
        """,
        (campaign["id"], digest),
    ).fetchone()
    if existing:
        return dict(existing)
    identity = media_identity(path)
    metadata = {
        **identity,
        "sourceFamilyId": request["contentFamilyId"],
        "generationSource": "reddit_weekly_winner_reference",
        "redditGenerationRequestId": request["requestId"],
        "redditTrendBriefFingerprint": request["briefFingerprint"],
        "redditReferencePostId": _object(request.get("concept")).get("referencePostId"),
        "redditReferencePostUrl": _object(request.get("concept")).get(
            "referencePostUrl"
        ),
        "contentTags": _list(_object(request.get("concept")).get("contentTags")),
        "compositionTags": ["weekly_winner_reference", "organic_amateur"],
        "humanReviewRequired": True,
    }
    rendered_id = new_id("asset")
    caption_hash = factory.domains.publishability.text_hash("")
    now = utc_now()
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, media_type, content_surface, caption, caption_hash,
         caption_generation_json, recipe, target_ratio, metadata_json,
         audit_status, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'reddit', '', ?, ?,
                'reddit_trend_soul_still', '9:16', ?, 'pending', 'review_ready',
                ?, ?)
        """,
        (
            rendered_id,
            campaign["id"],
            source["id"],
            digest,
            str(path),
            str(path),
            path.name,
            caption_hash,
            json.dumps(
                sanitize_for_storage(
                    {
                        "schema": "campaign_factory.reddit_still_generation.v1",
                        "generationRequest": dict(request),
                    }
                ),
                ensure_ascii=False,
                sort_keys=True,
            ),
            json.dumps(
                sanitize_for_storage(metadata),
                ensure_ascii=False,
                sort_keys=True,
            ),
            now,
            now,
        ),
    )
    factory.conn.commit()
    set_reddit_proposed_assignment(
        factory,
        campaign_slug=campaign_slug,
        rendered_asset_id=rendered_id,
        account_username=str(request["accountUsername"]),
        operator="reddit_weekly_generation",
        reason="Generated for an account-bound weekly Reddit coverage gap.",
        apply=True,
    )
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )


def run_reddit_generation_request(
    factory: Any,
    *,
    plan: Mapping[str, Any],
    request_id: str,
    reviewed_by: str,
    apply: bool = False,
    enable_paid_generation: bool = False,
    budget_cap_credits: float | None = None,
    wait: bool = False,
    download: bool = False,
) -> dict[str, Any]:
    plan_core = {
        key: value
        for key, value in plan.items()
        if key not in {"planFingerprint", "artifactPath"}
    }
    if _fingerprint(plan_core) != plan.get("planFingerprint"):
        raise ValueError("reddit_weekly_plan_fingerprint_mismatch")
    request = next(
        (
            _object(value)
            for value in _list(plan.get("generationRequests"))
            if _object(value).get("requestId") == request_id
        ),
        None,
    )
    if not request:
        raise ValueError("reddit_generation_request_not_found")
    reference = (
        Path(_required_text(request.get("referenceLocalPath"), "reddit_reference_path"))
        .expanduser()
        .resolve()
    )
    if sha256_file(reference) != request.get("referenceMediaSha256"):
        raise ValueError("reddit_reference_sha_mismatch")
    reviewer = _required_text(reviewed_by, "reddit_reference_reviewer")
    result = run_front_generation_stage(
        factory,
        campaign_slug=str(plan["campaignSlug"]),
        reference_image_path=reference,
        creator=str(request["creatorId"]),
        execution_plan=build_generation_execution_plan("soul_static"),
        scene_type="reddit_weekly_winner",
        dry_run=not apply,
        apply=apply,
        enable_paid_generation=enable_paid_generation,
        budget_cap_credits=budget_cap_credits,
        wait=wait,
        download=download,
    )
    registered: list[dict[str, Any]] = []
    if apply:
        soul_stage = next(
            (
                _object(stage)
                for stage in _list(_object(result.get("plan")).get("stages"))
                if _object(stage).get("name") == "soul_reference_image"
            ),
            {},
        )
        batch = _object(_object(soul_stage.get("result")).get("registeredBatch"))
        candidate_rows = _list(batch.get("candidates"))
        if not candidate_rows:
            static_stage = next(
                (
                    _object(stage)
                    for stage in _list(_object(result.get("plan")).get("stages"))
                    if _object(stage).get("name") == "static_mp4"
                ),
                {},
            )
            candidate_rows = _list(
                _object(static_stage.get("result")).get("candidates")
            )
        for candidate in candidate_rows:
            registered.append(
                _register_reddit_still(
                    factory,
                    campaign_slug=str(plan["campaignSlug"]),
                    candidate=_object(candidate),
                    request=request,
                )
            )
    return {
        "schema": "campaign_factory.reddit_generation_run.v1",
        "requestId": request_id,
        "referenceReviewedBy": reviewer,
        "apply": apply,
        "frontGeneration": result,
        "registeredRedditAssets": registered,
        "humanReviewRequired": True,
        "handoffCreationAllowed": False,
    }
