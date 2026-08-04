#!/usr/bin/env python3
"""Download a social reel URL into the local source-video folder."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import requests

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

SAFE_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
_INSTAGRAM_RE = re.compile(
    r"^/(?:[A-Za-z0-9._]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)"
)
_TIKTOK_RE = re.compile(r"^/@[^/]+/video/(\d+)")
_YOUTUBE_SHORTS_RE = re.compile(r"^/shorts/([A-Za-z0-9_-]+)")
_METADATA_KEYS = (
    "id",
    "extractor",
    "extractor_key",
    "webpage_url",
    "original_url",
    "uploader",
    "uploader_id",
    "description",
    "upload_date",
    "timestamp",
    "view_count",
    "like_count",
    "comment_count",
    "repost_count",
    "duration",
    "width",
    "height",
    "fps",
    "vcodec",
    "acodec",
    "track",
    "track_id",
    "artist",
    "music_id",
    "original_audio",
)


def _validate_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("reel URL must be an http(s) URL")
    host = parsed.hostname
    if not host:
        raise ValueError("reel URL must include a public http(s) host")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip and (
        literal_ip.is_private
        or literal_ip.is_loopback
        or literal_ip.is_link_local
        or literal_ip.is_reserved
    ):
        raise ValueError("reel URL must resolve to a public http(s) host")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError("reel URL host must resolve to a public http(s) host") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("reel URL must resolve to a public http(s) host")
    return url


def _validate_stem(stem: str) -> str:
    clean = str(stem or "").strip()
    if (
        not clean
        or clean != Path(clean).name
        or ".." in clean
        or not SAFE_STEM_RE.fullmatch(clean)
        or any(sep in clean for sep in {"/", "\\"})
    ):
        raise ValueError("download_reel_url requires a safe stem")
    return clean


def _safe_output_child(out_dir: Path, filename: str) -> Path:
    root = out_dir.resolve()
    if filename != Path(filename).name:
        raise ValueError("download target requires a plain filename")
    # lgtm[py/path-injection] filename is validated as a single path segment;
    # the resolved child is rejected unless it remains directly under out_dir.
    path = (root / filename).resolve()
    if path.parent != root:
        raise ValueError("download target escaped output directory")
    return path


def _yt_dlp_cmd(url: str, output_template: Path) -> list[str]:
    return [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--abort-on-error",
        "--no-progress",
        "--restrict-filenames",
        "--write-info-json",
        "--no-write-comments",
        "-f",
        "bv*+ba/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_template),
        "--",
        url,
    ]


def _runner_cmd(
    url: str, output_template: Path, *, browser_cookies: bool = False
) -> list[str]:
    if yt_dlp := shutil.which("yt-dlp"):
        cmd = [yt_dlp, *_yt_dlp_cmd(url, output_template)[1:]]
    else:
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            *_yt_dlp_cmd(url, output_template)[1:],
        ]
    if browser_cookies:
        separator = cmd.index("--")
        cmd[separator:separator] = ["--cookies-from-browser", "chrome:Default"]
    return cmd


def canonicalize_reel_url(url: str) -> dict[str, str | None]:
    """Return a stable public identity without dereferencing the URL."""
    validated = _validate_url(url)
    parsed = urlparse(validated)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    platform = "direct_http"
    media_id: str | None = None
    canonical = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    if host in {"instagram.com", "www.instagram.com"}:
        match = _INSTAGRAM_RE.match(path)
        if match:
            platform, media_id = "instagram", match.group(1)
            canonical = f"https://www.instagram.com/reel/{media_id}/"
    elif host.endswith("tiktok.com"):
        match = _TIKTOK_RE.match(path)
        if match:
            platform, media_id = "tiktok", match.group(1)
            canonical = f"https://www.tiktok.com{path}"
        else:
            platform = "tiktok"
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        match = _YOUTUBE_SHORTS_RE.match(path)
        if match:
            media_id = match.group(1)
        elif host == "youtu.be":
            media_id = path.strip("/").split("/", 1)[0] or None
        else:
            media_id = (parse_qs(parsed.query).get("v") or [None])[0]
        platform = "youtube"
        if media_id:
            canonical = f"https://www.youtube.com/shorts/{media_id}"
    return {
        "originalUrl": _sanitize_url_for_receipt(validated),
        "canonicalUrl": canonical,
        "platform": platform,
        "nativeMediaId": media_id,
    }


def download_reel_url(
    url: str,
    *,
    out_dir: Path,
    stem: str,
    timeout: int = 600,
    allow_browser_cookies: bool = True,
) -> dict[str, object]:
    """Download a reel/post URL to ``out_dir/<stem>.mp4`` using yt-dlp.

    The function stages into a temporary directory so partial downloads never
    masquerade as valid source clips.
    """
    requested_url = _validate_url(url)
    url_identity = canonicalize_reel_url(requested_url)
    redirect_summary = (
        _validate_direct_redirect_chain(requested_url)
        if url_identity["platform"] == "direct_http"
        else "trusted_platform_url"
    )
    url = requested_url
    stem = _validate_stem(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve()
    existing = _existing_import_for_url(out_dir, url)
    if existing:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_imported_url",
            "url": url,
            "stem": existing.get("stem")
            or Path(str(existing.get("sourceVideoPath"))).stem,
            "path": existing.get("sourceVideoPath"),
            "command": [],
            "sourceMetrics": existing.get("sourceMetrics") or {},
        }
    dest = _safe_output_child(out_dir, f"{stem}.mp4")
    if dest.exists():
        raise FileExistsError(f"source clip already exists: {dest}")
    with tempfile.TemporaryDirectory(prefix=f"{stem}_", dir=str(out_dir)) as tmp:
        tmp_dir = Path(tmp)
        template = tmp_dir / f"{stem}.%(ext)s"
        cmd = _runner_cmd(url, template)
        result = _run_ytdlp_with_retry(cmd, timeout=timeout)
        cookie_fallback_used = False
        if result.returncode != 0 and allow_browser_cookies and _needs_auth(result):
            cmd = _runner_cmd(url, template, browser_cookies=True)
            result = _run_ytdlp_with_retry(cmd, timeout=timeout)
            cookie_fallback_used = True
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "yt-dlp failed"
            if "No module named yt_dlp" in message or "not found" in message.lower():
                message = "yt-dlp is required to import reel URLs. Install with: .venv/bin/python -m pip install yt-dlp"
            raise RuntimeError(message[-2000:])
        candidates = sorted(
            tmp_dir.glob(f"{stem}.*"),
            key=lambda p: p.stat().st_size if p.exists() else 0,
            reverse=True,
        )
        media = next(
            (
                p
                for p in candidates
                if p.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
            ),
            None,
        )
        if not media:
            raise RuntimeError("yt-dlp finished but no downloaded media file was found")
        info_json = _info_json_candidates(tmp_dir, stem)
        source_metrics = _source_metrics_from_info_json(
            info_json[0] if info_json else None
        )
        resolved_identity = _resolved_identity(url_identity, source_metrics)
        _validate_redirect_identity(url_identity, resolved_identity)
        if resolved_identity.get("redirectSummary") == "none":
            resolved_identity["redirectSummary"] = redirect_summary
        media.replace(dest)
        dest.chmod(0o600)
        info_json_path = None
        if info_json:
            info_json_path = _safe_output_child(out_dir, f"{stem}.info.json")
            # lgtm[py/path-injection] yt-dlp info-json is selected from the
            # private temp dir and copied to a validated out_dir child path.
            shutil.copy2(info_json[0], info_json_path)
            info_json_path.chmod(0o600)
        info_json_return_path = (
            str(info_json_path.resolve()) if info_json_path else None
        )
    return {
        "ok": True,
        "url": url,
        **resolved_identity,
        "stem": stem,
        "path": str(dest.resolve()),
        "command": _sanitize_command(cmd),
        "cookieFallbackUsed": cookie_fallback_used,
        "downloadedSha256": _sha256_file(dest),
        "extractorVersion": _yt_dlp_version(cmd[0]),
        "sourceMetrics": source_metrics,
        "infoJsonPath": info_json_return_path,
    }


def write_url_sidecar(path: Path, payload: dict[str, object]) -> None:
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _existing_import_for_url(out_dir: Path, url: str) -> dict[str, object] | None:
    for sidecar in sorted(out_dir.glob("*.reel_url_import.json")):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("url") or "").strip() == url:
            return payload
    return None


def _run_ytdlp_once(
    cmd: list[str], *, timeout: int
) -> subprocess.CompletedProcess[str]:
    # Ambiguous downloads are never blindly retried. A second submission is
    # allowed only when the anonymous response explicitly requires auth.
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_ytdlp_with_retry(
    cmd: list[str], *, timeout: int, attempts: int = 3
) -> subprocess.CompletedProcess[str]:
    """Retry only explicit transient transport/rate-limit failures."""
    result = _run_ytdlp_once(cmd, timeout=timeout)
    for attempt in range(1, max(1, attempts)):
        text = f"{result.stderr}\n{result.stdout}".lower()
        if result.returncode == 0 or not any(
            marker in text
            for marker in ("429", "too many requests", "timed out", "temporary failure")
        ):
            return result
        time.sleep(0.5 * (2 ** (attempt - 1)))
        result = _run_ytdlp_once(cmd, timeout=timeout)
    return result


def _info_json_candidates(tmp_dir: Path, stem: str) -> list[Path]:
    return sorted(tmp_dir.glob(f"{stem}*.info.json"))


def _source_metrics_from_info_json(path: Path | None) -> dict[str, object]:
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        key: payload.get(key) for key in _METADATA_KEYS if payload.get(key) is not None
    }


def _resolved_identity(
    initial: dict[str, str | None], metadata: dict[str, object]
) -> dict[str, str | None]:
    resolved_url = str(metadata.get("webpage_url") or initial["canonicalUrl"] or "")
    try:
        resolved = canonicalize_reel_url(resolved_url)
    except ValueError:
        resolved = initial
    return {
        "originalUrl": initial["originalUrl"],
        "canonicalUrl": resolved.get("canonicalUrl") or initial["canonicalUrl"],
        "platform": resolved.get("platform") or initial["platform"],
        "nativeMediaId": str(metadata.get("id") or resolved.get("nativeMediaId") or "")
        or None,
        "extractor": str(
            metadata.get("extractor") or metadata.get("extractor_key") or ""
        )
        or None,
        "redirectSummary": (
            "canonical_changed"
            if resolved.get("canonicalUrl") != initial.get("canonicalUrl")
            else "none"
        ),
    }


def _validate_redirect_identity(
    initial: dict[str, str | None], resolved: dict[str, str | None]
) -> None:
    # yt-dlp reports the public page it resolved. Validate that URL again and
    # prohibit a platform identity from changing after resolution.
    canonical = str(resolved.get("canonicalUrl") or "")
    _validate_url(canonical)
    initial_platform = initial.get("platform")
    resolved_platform = resolved.get("platform")
    if initial_platform != "direct_http" and resolved_platform != initial_platform:
        raise ValueError("reel URL redirected to a different platform")


def _validate_direct_redirect_chain(url: str, *, max_redirects: int = 5) -> str:
    """Resolve direct-media redirects one hop at a time with public-host checks."""
    current = url
    redirects = 0
    for _ in range(max_redirects + 1):
        _validate_url(current)
        response = requests.get(
            current,
            stream=True,
            allow_redirects=False,
            timeout=(10, 20),
            headers={"Range": "bytes=0-0"},
        )
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("direct media redirect omitted its target")
                current = urljoin(current, location)
                redirects += 1
                continue
            if response.status_code >= 400:
                raise ValueError(
                    f"direct media preflight failed with HTTP {response.status_code}"
                )
            return f"validated_public_redirects:{redirects}"
        finally:
            response.close()
    raise ValueError("direct media URL exceeded the redirect limit")


def _needs_auth(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stderr}\n{result.stdout}".lower()
    markers = (
        "login required",
        "requires authentication",
        "sign in to confirm",
        "cookies",
        "private video",
        "not logged in",
    )
    return any(marker in text for marker in markers)


def _sanitize_command(cmd: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip = False
    after_delimiter = False
    for item in cmd:
        if skip:
            cleaned.append("<private-browser-profile>")
            skip = False
            continue
        if after_delimiter:
            cleaned.append(_sanitize_url_for_receipt(item))
            after_delimiter = False
        else:
            cleaned.append(item)
        if item == "--cookies-from-browser":
            skip = True
        if item == "--":
            after_delimiter = True
    return cleaned


def _sanitize_url_for_receipt(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _yt_dlp_version(executable: str) -> str | None:
    try:
        return version("yt-dlp")
    except PackageNotFoundError:
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return result.stdout.strip() or None
