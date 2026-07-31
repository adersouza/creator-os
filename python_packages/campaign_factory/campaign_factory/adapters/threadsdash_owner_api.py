from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

from . import threadsdash_client
from .threadsdash_client import (
    _threadsdash_ingest_signature,
    _validate_threadsdash_ingest_url,
)
from .threadsdash_handoff_evidence import (
    handoff_idempotency_key,
    shared_handoff_payload,
)

INGEST_MAX_ATTEMPTS = 3
INGEST_BACKOFF_SECONDS = (1.0, 3.0)
UPLOAD_TICKET_PATH = "/api/campaign-factory/media/upload-ticket"
REDDIT_HANDOFF_PATH = "/api/campaign-factory/reddit/handoff"


def owner_api_secret(value: str | None) -> str:
    secret = value or os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET")
    if not secret:
        raise ValueError(
            "threadsdash_ingest_secret or CAMPAIGN_FACTORY_INGEST_SECRET is required"
        )
    return secret


def owner_api_ingest_url(value: str | None) -> str:
    url = (
        value
        or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
    )
    if not url:
        raise ValueError(
            "threadsdash_ingest_url or THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL is required"
        )
    return _validate_threadsdash_ingest_url(url)


def upload_ticket_url(ingest_url: str) -> str:
    parsed = urlparse(owner_api_ingest_url(ingest_url))
    return urlunparse((parsed.scheme, parsed.netloc, UPLOAD_TICKET_PATH, "", "", ""))


def reddit_handoff_url(ingest_url: str) -> str:
    parsed = urlparse(owner_api_ingest_url(ingest_url))
    return urlunparse((parsed.scheme, parsed.netloc, REDDIT_HANDOFF_PATH, "", "", ""))


def _signed_json_request(
    *,
    url: str,
    secret: str,
    body: dict[str, Any],
    idempotency_key: str,
    attempts: int = INGEST_MAX_ATTEMPTS,
) -> dict[str, Any]:
    body_bytes = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    last_error = "unknown"
    for attempt in range(1, attempts + 1):
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signature = _threadsdash_ingest_signature(
            body_bytes, secret=secret, timestamp=timestamp, nonce=nonce
        )
        request = Request(
            url,
            data=body_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Campaign-Factory-Signature": signature,
                "X-Campaign-Factory-Timestamp": timestamp,
                "X-Campaign-Factory-Nonce": nonce,
                "X-Idempotency-Key": idempotency_key,
            },
        )
        try:
            with threadsdash_client._open_threadsdash_ingest_request(
                request, timeout=30
            ) as response:
                parsed = json.loads(response.read().decode("utf-8") or "{}")
                if not isinstance(parsed, dict):
                    raise ValueError(
                        "ThreadsDashboard owner API returned non-object JSON"
                    )
                return parsed
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {408, 409, 425, 429} and exc.code < 500:
                raise ValueError(
                    f"ThreadsDashboard owner API rejected request ({exc.code}): {detail}"
                ) from exc
            last_error = f"HTTP {exc.code}: {detail}"
        except (TimeoutError, URLError) as exc:
            last_error = str(exc)
        if attempt < attempts:
            time.sleep(INGEST_BACKOFF_SECONDS[min(attempt - 1, 1)])
    raise TimeoutError(f"ThreadsDashboard owner API outcome is unknown: {last_error}")


def submit_draft_handoff(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    shared = shared_handoff_payload(payload)
    export_id = str(shared.get("exportId") or "")
    shared["dryRun"] = False
    key = handoff_idempotency_key(export_id)
    parsed = _signed_json_request(
        url=owner_api_ingest_url(ingest_url),
        secret=owner_api_secret(ingest_secret),
        body=shared,
        idempotency_key=key,
    )
    acknowledgment = parsed.get("acknowledgment")
    if not isinstance(acknowledgment, dict):
        raise ValueError("ThreadsDashboard ingest response is missing acknowledgment")
    return {
        "attempted": True,
        "dryRun": False,
        "postIds": list(acknowledgment.get("postIds") or parsed.get("postIds") or []),
        "response": parsed,
        "acknowledgment": acknowledgment,
        "idempotencyKey": key,
    }


def submit_reddit_handoff(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    return _signed_json_request(
        url=reddit_handoff_url(owner_api_ingest_url(ingest_url)),
        secret=owner_api_secret(ingest_secret),
        body=payload,
        idempotency_key=f"reddit-manual-handoff:{payload['idempotencyKey']}",
    )


def reconcile_draft_handoff(
    *,
    export_id: str,
    user_id: str,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    key = handoff_idempotency_key(export_id)
    return _signed_json_request(
        url=owner_api_ingest_url(ingest_url),
        secret=owner_api_secret(ingest_secret),
        body={
            "operation": "reconcile",
            "exportId": export_id,
            "userId": user_id,
            "idempotencyKey": key,
        },
        idempotency_key=f"{key}:reconcile",
    )


def upload_delivery_media(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
    bucket: str,
) -> list[dict[str, Any]]:
    url = upload_ticket_url(owner_api_ingest_url(ingest_url))
    secret = owner_api_secret(ingest_secret)
    results: list[dict[str, Any]] = []
    uploaded: dict[str, dict[str, Any]] = {}
    for draft in payload.get("drafts") or []:
        if not isinstance(draft, dict):
            continue
        local_value = draft.get("_localFilePath")
        if not isinstance(local_value, str) or not local_value:
            continue
        path = Path(local_value)
        expected_sha = str(draft.get("contentHash") or "").lower()
        if not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
            raise ValueError("delivery media requires an existing file and SHA-256")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError("delivery media changed after creative approval")
        media_key = str(draft.get("campaignFactoryMediaKey") or "")
        if media_key not in uploaded:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            ticket = _signed_json_request(
                url=url,
                secret=secret,
                body={
                    "userId": draft.get("userId"),
                    "exportId": draft.get("campaignFactoryExportId"),
                    "mediaKey": media_key,
                    "fileName": path.name,
                    "fileSize": path.stat().st_size,
                    "mimeType": mime,
                    "expectedSha256": expected_sha,
                    "bucket": bucket,
                },
                idempotency_key=f"campaign-factory-media:{media_key}",
            )
            signed_url = str(ticket.get("signedUrl") or "")
            if not signed_url.startswith("https://") and not signed_url.startswith(
                "http://127.0.0.1"
            ):
                raise ValueError(
                    "ThreadsDashboard returned an invalid signed upload URL"
                )
            request = Request(
                signed_url,
                data=path.read_bytes(),
                method="PUT",
                headers={
                    "Content-Type": mime,
                    "cache-control": "max-age=3600",
                    "x-upsert": "false",
                },
            )
            with threadsdash_client._open_threadsdash_ingest_request(
                request, timeout=120
            ) as response:
                if int(getattr(response, "status", 200)) >= 300:
                    raise ValueError("signed delivery-media upload failed")
                response.read()
            media_ref = {
                "publicUrl": ticket["publicUrl"],
                "storagePath": ticket["storagePath"],
                "bucket": ticket["bucket"],
                "fileName": path.name,
                "fileSize": path.stat().st_size,
                "mediaType": mime,
                "sha256": expected_sha,
                "uploadTicketId": ticket["uploadTicketId"],
                "sourceSystem": "creator_os",
                "owningSystem": "threadsdashboard",
            }
            uploaded[media_key] = media_ref
            results.append(media_ref)
        media_ref = uploaded[media_key]
        draft["deliveryMedia"] = media_ref
        media = draft.get("media")
        if isinstance(media, list) and media and isinstance(media[0], dict):
            media[0]["url"] = media_ref["publicUrl"]
            media[0]["deliveryMedia"] = media_ref
    return results
