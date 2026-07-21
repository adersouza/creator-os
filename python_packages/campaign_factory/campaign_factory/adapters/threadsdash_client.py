from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from ..contracts import (
    ContractValidationError,
    validate_post_metric_history_read,
)
from .threadsdash_hmac import sign_body

VALID_PUBLISH_MODES = {"auto", "notify"}
SAFE_NATIVE_AUDIO_STATUSES = {"attached", "verified", "skipped", "not_required"}
UNRESOLVED_NATIVE_AUDIO_STATUSES = {
    "recommended",
    "needs_operator_selection",
    "selected",
    "blocked",
}
DEFERRED_NOTIFY_AUDIO_FAILURES = {"missing_audio", "embedded_audio_missing"}
METRIC_CONTRACT_VERSION = "instagram_metrics_contract_v1"
DASHBOARD_INGEST_MAX_ATTEMPTS = 3
DASHBOARD_INGEST_BACKOFF_SECONDS = (1.0, 3.0)
THREADSDASH_INGEST_PATH = "/api/campaign-factory/drafts/ingest"
DEFAULT_THREADSDASH_INGEST_HOSTS = frozenset({"juno33.com", "www.juno33.com"})
POST_METRIC_HISTORY_POST_ID_BATCH_SIZE = 5
THREADSDASH_POSTS_PAGE_SIZE = 500
_STDLIB_URLOPEN = urlopen


class _RejectDashboardIngestRedirects(HTTPRedirectHandler):
    """Never forward authenticated ingest requests to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_threadsdash_ingest_request(request: Request, *, timeout: float):
    # Preserve the existing injected transport seam used by deterministic E2E
    # fakes. Runtime traffic keeps the no-redirect opener below.
    if urlopen is not _STDLIB_URLOPEN:
        return urlopen(request, timeout=timeout)
    return build_opener(_RejectDashboardIngestRedirects()).open(
        request, timeout=timeout
    )


def _threadsdash_allowed_ingest_hosts() -> set[str]:
    configured = {
        host.strip().lower().rstrip(".")
        for host in os.environ.get("THREADSDASH_ALLOWED_INGEST_HOSTS", "").split(",")
        if host.strip()
    }
    return set(DEFAULT_THREADSDASH_INGEST_HOSTS) | configured


def _is_local_dashboard_ingest_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback


def _is_blocked_dashboard_ingest_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_threadsdash_ingest_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if not parsed.scheme or not host:
        raise ValueError(
            "ThreadsDashboard ingest URL must include an https scheme and hostname"
        )
    allow_local = (
        os.environ.get("CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST") == "1"
    )
    if parsed.username or parsed.password:
        raise ValueError("ThreadsDashboard ingest URL must not include credentials")
    if parsed.fragment:
        raise ValueError("ThreadsDashboard ingest URL must not include a fragment")
    if parsed.query:
        raise ValueError(
            "ThreadsDashboard ingest URL must not include query parameters"
        )
    if parsed.path.rstrip("/") != THREADSDASH_INGEST_PATH:
        raise ValueError(
            f"ThreadsDashboard ingest URL path must be {THREADSDASH_INGEST_PATH}"
        )
    if parsed.scheme != "https":
        if not (
            allow_local
            and parsed.scheme == "http"
            and _is_local_dashboard_ingest_host(host)
        ):
            raise ValueError("ThreadsDashboard ingest URL must use https")
    if _is_local_dashboard_ingest_host(host):
        if not allow_local:
            raise ValueError(
                "ThreadsDashboard ingest URL cannot target localhost unless local ingest is explicitly enabled"
            )
    elif _is_blocked_dashboard_ingest_ip(host):
        raise ValueError(
            "ThreadsDashboard ingest URL cannot target private or reserved IP addresses"
        )
    elif host not in _threadsdash_allowed_ingest_hosts():
        raise ValueError("ThreadsDashboard ingest URL host is not allowed")
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, THREADSDASH_INGEST_PATH, "", "", ""))


def _threadsdash_ingest_signature(
    body: bytes, *, secret: str, timestamp: str, nonce: str
) -> str:
    return sign_body(
        body,
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
    )


def _select_post_by_id(
    client: SupabaseRestClient, post_id: Any
) -> dict[str, Any] | None:
    if not post_id:
        return None
    try:
        rows = client.select(
            "posts",
            {
                "select": "id,status,platform,media_urls,metadata",
                "id": f"eq.{post_id}",
                "limit": "1",
            },
        )
    except RuntimeError as exc:
        # Transient failure must not read as "post missing" — the caller
        # treats a miss as permission to create a new post (dedup safety).
        if not _is_missing_column_error(exc):
            raise
        rows = []
    return rows[0] if rows else None


def _select_paged(
    client: SupabaseRestClient,
    table: str,
    params: dict[str, str],
    *,
    limit: int,
    page_size: int,
    probe_select: str = "id",
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch up to ``limit`` rows in pages of ``page_size``.

    Returns ``(rows, truncated)`` where ``truncated`` is True when at least
    one additional row exists beyond ``limit``.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < limit:
        page_limit = min(page_size, limit - len(rows))
        page = client.select(
            table,
            {**params, "limit": str(page_limit), "offset": str(offset)},
        )
        rows.extend(page)
        if not page:
            # Empty page: definitive end of data.
            return rows, False
        # A short-but-non-empty page is NOT proof of end-of-data: PostgREST
        # `max-rows` (or any server-side cap) can silently clamp a page below
        # the requested limit. Keep paging from the real offset until an empty
        # page or `limit` is reached, so a server cap can never silently
        # truncate a sync (audit: partial-sync failure injection).
        offset += len(page)
    probe = client.select(
        table,
        {**params, "select": probe_select, "limit": "1", "offset": str(offset)},
    )
    return rows, bool(probe)


def _select_threadsdash_posts_paged(
    client: SupabaseRestClient,
    *,
    user_id: str,
    campaign_ids: list[str] | None = None,
    limit: int,
    page_size: int = THREADSDASH_POSTS_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], bool]:
    base_params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
    }
    normalized_campaign_ids = list(
        dict.fromkeys(value.strip() for value in campaign_ids or [] if value.strip())
    )
    if normalized_campaign_ids:
        values = ",".join(json.dumps(value) for value in normalized_campaign_ids)
        base_params["metadata->campaign_factory->>campaign_id"] = f"in.({values})"
    rich_select = (
        "id,status,platform,media_type,ig_media_type,content_surface,account_id,instagram_account_id,created_at,updated_at,scheduled_for,"
        "published_at,permalink,instagram_post_id,metrics_observed_at,publish_mode,handoff_status,manual_publish_confirmed_at,content,metadata,views_count,ig_views,"
        "likes_count,replies_count,ig_comment_count,"
        "shares_count,ig_shares,ig_saved,"
        "ig_reach,ig_impressions,"
        "ig_reels_avg_watch_time,ig_reels_video_view_total_time"
    )
    try:
        return _select_paged(
            client,
            "posts",
            {"select": rich_select, **base_params},
            limit=limit,
            page_size=page_size,
        )
    except RuntimeError as exc:
        # Only fall back to the narrow column set when the error is a
        # missing-column/schema mismatch. Transient failures (5xx, network)
        # must propagate: silently retrying them with a narrower select would
        # sync rows without published_at/metric columns and quietly make every
        # post learning-ineligible (audit: partial-sync failure injection).
        if not _is_missing_column_error(exc):
            raise
        return _select_paged(
            client,
            "posts",
            {
                "select": "id,status,platform,media_type,ig_media_type,content_surface,account_id,instagram_account_id,created_at,scheduled_for,published_at,permalink,instagram_post_id,publish_mode,handoff_status,manual_publish_confirmed_at,content,metadata",
                **base_params,
            },
            limit=limit,
            page_size=page_size,
        )


def _is_missing_column_error(exc: Exception) -> bool:
    """True when a Supabase/PostgREST error indicates a schema/column mismatch
    (safe to retry with a narrower select), as opposed to a transient failure."""
    message = str(exc)
    return (
        "does not exist" in message
        or "42703" in message
        or "Could not find" in message
        or "schema cache" in message
    )


def _select_threadsdash_posts(
    client: SupabaseRestClient, *, user_id: str, limit: int
) -> list[dict[str, Any]]:
    rows, truncated = _select_threadsdash_posts_paged(
        client, user_id=user_id, limit=limit
    )
    if truncated:
        raise RuntimeError(
            "threadsdash_posts_truncated: increase the explicit read limit; "
            "partial post history cannot prove deduplication or assignment safety"
        )
    return rows


def _select_threadsdash_post_metric_history(
    client: SupabaseRestClient,
    *,
    post_ids: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Returns ``(rows, truncated)``; ``truncated`` means at least one batch
    had more history rows than its per-batch limit allowed."""
    ids = sorted({post_id for post_id in post_ids if post_id})
    if not ids:
        return [], False
    select_columns = (
        "id,post_id,account_id,platform,snapshot_at,hours_since_publish,"
        "views_count,likes_count,replies_count,reposts_count,quotes_count,shares_count,"
        "saves_count,reach,engagement_rate"
    )
    rows: list[dict[str, Any]] = []
    truncated = False
    for offset in range(0, len(ids), POST_METRIC_HISTORY_POST_ID_BATCH_SIZE):
        batch = ids[offset : offset + POST_METRIC_HISTORY_POST_ID_BATCH_SIZE]
        batch_limit = max(limit, len(batch) * 24)
        batch_rows, batch_truncated = _select_paged(
            client,
            "post_metric_history",
            {
                "select": select_columns,
                "post_id": f"in.({','.join(batch)})",
                "order": "snapshot_at.asc",
            },
            limit=batch_limit,
            page_size=batch_limit,
        )
        truncated = truncated or batch_truncated
        rows.extend(batch_rows)
    return rows, truncated


def _validate_threadsdash_post_metric_history_read(rows: list[dict[str, Any]]) -> None:
    try:
        validate_post_metric_history_read(
            {
                "schema": "threadsdashboard.post_metric_history.read.v1",
                "rows": rows,
            }
        )
    except ContractValidationError as exc:
        raise RuntimeError(
            f"post_metric_history.read.v1 validation failed: {exc}"
        ) from exc


def _text_hash(value: str) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _empty_usage() -> dict[str, Any]:
    return {
        "total": 0,
        "draft": 0,
        "scheduled": 0,
        "published": 0,
        "other": 0,
        "surfaces": {},
        "posts": [],
    }


def _add_usage(usage: dict[str, Any], *, row: dict[str, Any], status: str) -> None:
    usage["total"] += 1
    if status in {"draft", "scheduled", "published"}:
        usage[status] += 1
    else:
        usage["other"] += 1
    meta = (row.get("metadata") or {}).get("campaign_factory") or {}
    surface = _post_surface(row, meta if isinstance(meta, dict) else {})
    surface_counts = usage.setdefault("surfaces", {}).setdefault(
        surface, {"total": 0, "draft": 0, "scheduled": 0, "published": 0, "other": 0}
    )
    surface_counts["total"] += 1
    if status in {"draft", "scheduled", "published"}:
        surface_counts[status] += 1
    else:
        surface_counts["other"] += 1
    usage["posts"].append(
        {
            "id": row.get("id"),
            "status": status,
            "platform": row.get("platform"),
            "surface": surface,
            "mediaType": row.get("media_type"),
            "igMediaType": row.get("ig_media_type"),
            "accountId": row.get("account_id"),
            "instagramAccountId": row.get("instagram_account_id"),
            "createdAt": row.get("created_at"),
            "scheduledFor": row.get("scheduled_for"),
            "previewScheduleOnly": bool(meta.get("preview_schedule_only"))
            if isinstance(meta, dict)
            else False,
        }
    )


def _post_surface(row: dict[str, Any], meta: dict[str, Any]) -> str:
    for key in ("distribution_surface", "content_surface", "surface"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    if meta.get("trial_reel") or meta.get("is_trial_reel"):
        return "trial_reel"
    media_type = str(row.get("media_type") or "").lower()
    ig_media_type = str(row.get("ig_media_type") or "").upper()
    if ig_media_type in {"STORY", "STORIES"} or media_type in {"story", "stories"}:
        return "story"
    if ig_media_type == "REELS" or media_type == "reel":
        return "reel"
    if media_type in {"carousel", "slideshow"}:
        return media_type
    return str(row.get("platform") or "unknown").lower()


def _sync_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


class SupabaseRestClient:
    def __init__(self, url: str, service_role_key: str):
        self.url = url
        self.service_role_key = service_role_key

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }
        if extra:
            headers.update(extra)
        return headers

    def upload_storage_object(
        self,
        bucket: str,
        storage_path: str,
        file_path: Path,
        content_type: str,
        *,
        upsert: bool = False,
    ) -> None:
        endpoint = f"{self.url}/storage/v1/object/{quote(bucket)}/{quote(storage_path)}"
        data = file_path.read_bytes()
        request = Request(
            endpoint,
            data=data,
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": content_type,
                    "x-upsert": "true" if upsert else "false",
                }
            ),
        )
        self._open_json_or_empty(request)

    def get_storage_bucket(self, bucket: str) -> dict[str, Any]:
        endpoint = f"{self.url}/storage/v1/bucket/{quote(bucket)}"
        request = Request(endpoint, method="GET", headers=self.headers())
        result = self._open_json_or_empty(request)
        return result if isinstance(result, dict) else {}

    def insert_with_fallback(
        self, table: str, row: dict[str, Any], fallback_remove: list[str]
    ) -> dict[str, Any]:
        current = dict(row)
        while True:
            try:
                inserted = self.insert(table, current)
                return (
                    inserted[0] if isinstance(inserted, list) and inserted else inserted
                )
            except RuntimeError as exc:
                message = str(exc)
                removed = False
                for key in list(fallback_remove):
                    if key in current and (
                        key in message
                        or "Could not find" in message
                        or "schema cache" in message
                    ):
                        current.pop(key, None)
                        fallback_remove.remove(key)
                        removed = True
                        break
                if not removed:
                    raise

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in params.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(endpoint, method="GET", headers=self.headers())
        result = self._open_json_or_empty(request)
        return result if isinstance(result, list) else []

    def insert(self, table: str, row: dict[str, Any]) -> Any:
        endpoint = f"{self.url}/rest/v1/{quote(table)}"
        request = Request(
            endpoint,
            data=json.dumps(row).encode("utf-8"),
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
            ),
        )
        # Plain POST inserts are not idempotent: a retry after an ambiguous
        # failure (timeout, or a 5xx sent after the row committed) can create
        # duplicate rows (audit A6). Only retry statuses that guarantee the
        # request was never processed; never retry network-level ambiguity.
        return self._open_json_or_empty(request, retry_ambiguous=False)

    def upsert(self, table: str, row: dict[str, Any], *, on_conflict: str) -> Any:
        endpoint = f"{self.url}/rest/v1/{quote(table)}?on_conflict={quote(on_conflict, safe=',')}"
        request = Request(
            endpoint,
            data=json.dumps(row).encode("utf-8"),
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=representation",
                }
            ),
        )
        return self._open_json_or_empty(request)

    def update(
        self, table: str, values: dict[str, Any], filters: dict[str, str]
    ) -> Any:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in filters.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(
            endpoint,
            data=json.dumps(values).encode("utf-8"),
            method="PATCH",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
            ),
        )
        return self._open_json_or_empty(request)

    def delete(self, table: str, filters: dict[str, str]) -> Any:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in filters.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(
            endpoint,
            method="DELETE",
            headers=self.headers({"Prefer": "return=representation"}),
        )
        return self._open_json_or_empty(request)

    def _open_json_or_empty(
        self, request: Request, *, retry_ambiguous: bool = True
    ) -> Any:
        # Statuses where the server definitely did not process the request,
        # so retrying is always safe (even for non-idempotent POST inserts).
        safe_statuses = {408, 425, 429}
        # Statuses where the request *may* have been processed before the
        # error/timeout surfaced; only retried for idempotent requests.
        ambiguous_statuses = {409, 500, 502, 503, 504}
        transient_statuses = (
            safe_statuses | ambiguous_statuses if retry_ambiguous else safe_statuses
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    raw = response.read()
                break
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"Supabase request failed {exc.code}: {body}")
                if exc.code not in transient_statuses or attempt == 2:
                    raise last_error from exc
            except URLError as exc:
                # Network-level failure (incl. timeouts): ambiguous whether
                # the request reached the server. Never retried for
                # non-idempotent requests.
                last_error = RuntimeError(f"Supabase request failed: {exc}")
                if not retry_ambiguous or attempt == 2:
                    raise last_error from exc
            time.sleep(0.25 * (2**attempt))
        else:  # pragma: no cover - loop either breaks or raises
            raise last_error or RuntimeError("Supabase request failed")
        if not raw:
            return {}
        text = raw.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
