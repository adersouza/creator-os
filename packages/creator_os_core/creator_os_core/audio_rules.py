"""Canonical audio rights, title, and URL rules shared by every factory.

Campaign Factory and Reference Factory both classify the same audio items, so
these rules must give the same answer in both. They previously existed as two
copies that had already drifted textually — one normalized platform names with
``" ".join`` and the other with ``"_".join``, which agree on ``instagram`` and
``tiktok`` but not on any multi-word platform. Keeping one implementation here
removes the chance of a licensing decision differing by which package asked.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "audio_preview_evidence",
    "audio_rights_status",
    "is_generic_audio_title",
    "is_native_audio_url",
    "is_reel_page_url",
    "normalize_audio_tag",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def normalize_audio_tag(value: Any) -> str:
    """Lowercase, collapse whitespace, and treat ``-`` as ``_``."""

    return " ".join(str(value or "").strip().lower().replace("-", "_").split())


def is_generic_audio_title(title: str, platform: str | None = None) -> bool:
    """True when the title is only a placeholder like ``tiktok audio 12345``."""

    normalized = str(title or "").strip().lower()
    platform_norm = normalize_audio_tag(platform or "")
    if not normalized:
        return True
    unresolved_suffix = r"(?:\s+\(title unresolved\))?"
    if platform_norm == "tiktok":
        return bool(
            re.fullmatch(rf"tiktok audio [0-9a-z_-]+{unresolved_suffix}", normalized)
        )
    if platform_norm == "instagram":
        return bool(
            re.fullmatch(rf"instagram audio [0-9a-z_-]+{unresolved_suffix}", normalized)
        )
    return bool(
        re.fullmatch(
            rf"(tiktok|instagram) audio [0-9a-z_-]+{unresolved_suffix}",
            normalized,
        )
    )


def audio_rights_status(item: dict[str, Any]) -> str:
    """Read the rights status from any of the accepted item shapes."""

    raw_value = item.get("raw")
    raw: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    rights_value = item.get("rights")
    rights: dict[str, Any] = rights_value if isinstance(rights_value, dict) else {}
    raw_rights_value = raw.get("rights")
    raw_rights: dict[str, Any] = (
        raw_rights_value if isinstance(raw_rights_value, dict) else {}
    )
    value = (
        item.get("rightsStatus")
        or item.get("rights_status")
        or rights.get("status")
        or rights.get("usageRightsStatus")
        or raw.get("rightsStatus")
        or raw.get("rights_status")
        or raw_rights.get("status")
        or raw_rights.get("usageRightsStatus")
    )
    return normalize_audio_tag(value)


def is_native_audio_url(url: str, platform: str) -> bool:
    """True when the URL points at the platform's own audio/sound page."""

    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.lower().rstrip("/")
    platform_norm = normalize_audio_tag(platform)
    if platform_norm == "instagram":
        return (host == "instagram.com" or host.endswith(".instagram.com")) and (
            "/reels/audio/" in f"{path}/" or path.startswith("/audio/")
        )
    if platform_norm == "tiktok":
        return (
            host == "tiktok.com" or host.endswith(".tiktok.com")
        ) and path.startswith("/music/")
    return bool(url)


def is_reel_page_url(url: str, platform: str) -> bool:
    """True when the URL points at a post/reel page rather than an audio page."""

    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.lower().rstrip("/")
    platform_norm = normalize_audio_tag(platform)
    if platform_norm == "instagram":
        return (host == "instagram.com" or host.endswith(".instagram.com")) and bool(
            re.match(r"^/(?:reel|reels|p|tv)/[^/]+$", path)
        )
    if platform_norm == "tiktok":
        return (
            host == "tiktok.com" or host.endswith(".tiktok.com")
        ) and "/video/" in path
    return False


def audio_preview_evidence(item: dict[str, Any]) -> dict[str, str]:
    """Collect the local preview path and sha256 from any accepted item shape."""

    raw_value = item.get("raw")
    raw: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    nested_value = item.get("previewEvidence")
    nested: dict[str, Any] = nested_value if isinstance(nested_value, dict) else {}
    raw_nested_value = raw.get("previewEvidence")
    raw_nested: dict[str, Any] = (
        raw_nested_value if isinstance(raw_nested_value, dict) else {}
    )
    path = str(
        item.get("localPreviewPath")
        or item.get("local_preview_path")
        or nested.get("path")
        or raw_nested.get("path")
        or ""
    ).strip()
    sha256 = (
        str(
            item.get("previewSha256")
            or item.get("preview_sha256")
            or nested.get("sha256")
            or raw.get("previewSha256")
            or raw.get("preview_sha256")
            or raw_nested.get("sha256")
            or ""
        )
        .strip()
        .lower()
    )
    evidence: dict[str, str] = {}
    if path:
        evidence["path"] = path
    if sha256:
        evidence["sha256"] = sha256
        evidence["sha256Format"] = (
            "valid" if _SHA256_RE.fullmatch(sha256) else "invalid"
        )
    return evidence
