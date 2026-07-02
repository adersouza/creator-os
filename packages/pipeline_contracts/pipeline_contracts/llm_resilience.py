from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

RETRIABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def urlopen_json_with_retry(
    request: urllib.request.Request,
    *,
    timeout: int = 120,
    attempts: int = 3,
    backoff_seconds: float = 0.25,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    last_error: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read().decode("utf-8")
            return decode_json_object(data)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRIABLE_HTTP_STATUSES or attempt == attempts - 1:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise RuntimeError(
                    f"LLM request failed after {attempts} attempts: {exc}"
                ) from exc
        sleep(backoff_seconds * (2**attempt))
    raise RuntimeError(f"LLM request failed: {last_error}")


def decode_json_object(
    text: str, fallback: dict[str, Any] | None = None
) -> dict[str, Any]:
    stripped = _strip_json_fence(text)
    decoder = json.JSONDecoder(strict=False)
    for candidate in (stripped, _braced_json(stripped)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                data, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict):
            return data
    return dict(fallback or {})


def _strip_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _braced_json(text: str) -> str | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0) if match else None
