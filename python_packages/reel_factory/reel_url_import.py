#!/usr/bin/env python3
"""Download a social reel URL into the local source-video folder."""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

SAFE_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")


def _validate_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("reel URL must be an http(s) URL")
    host = parsed.hostname
    if not host:
        raise ValueError("reel URL must include a public http(s) host")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError("reel URL host must resolve to a public http(s) host") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
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


def _yt_dlp_cmd(url: str, output_template: Path) -> list[str]:
    return [
        "yt-dlp",
        "--no-playlist",
        "--no-progress",
        "--restrict-filenames",
        "--write-info-json",
        "-f",
        "bv*+ba/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_template),
        "--",
        url,
    ]


def _runner_cmd(url: str, output_template: Path) -> list[str]:
    if yt_dlp := shutil.which("yt-dlp"):
        return [yt_dlp, *_yt_dlp_cmd(url, output_template)[1:]]
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        *_yt_dlp_cmd(url, output_template)[1:],
    ]


def download_reel_url(
    url: str, *, out_dir: Path, stem: str, timeout: int = 600
) -> dict[str, object]:
    """Download a reel/post URL to ``out_dir/<stem>.mp4`` using yt-dlp.

    The function stages into a temporary directory so partial downloads never
    masquerade as valid source clips.
    """
    url = _validate_url(url)
    stem = _validate_stem(stem)
    out_dir.mkdir(parents=True, exist_ok=True)
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
    dest = out_dir / f"{stem}.mp4"
    if dest.exists():
        raise FileExistsError(f"source clip already exists: {dest}")
    with tempfile.TemporaryDirectory(prefix=f"{stem}_", dir=str(out_dir)) as tmp:
        tmp_dir = Path(tmp)
        template = tmp_dir / f"{stem}.%(ext)s"
        cmd = _runner_cmd(url, template)
        result = _run_ytdlp_with_retry(cmd, timeout=timeout)
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
        source_metrics = _source_metrics_from_info_json(tmp_dir, stem)
        media = media.resolve()
        media.relative_to(tmp_dir.resolve())
        dest = dest.resolve()
        dest.relative_to(out_dir.resolve())
        shutil.move(str(media), dest)
    return {
        "ok": True,
        "url": url,
        "stem": stem,
        "path": str(dest.resolve()),
        "command": cmd,
        "sourceMetrics": source_metrics,
    }


def write_url_sidecar(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _existing_import_for_url(out_dir: Path, url: str) -> dict[str, object] | None:
    for sidecar in sorted(out_dir.glob("*.reel_url_import.json")):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("url") or "").strip() == url:
            return payload
    return None


def _run_ytdlp_with_retry(
    cmd: list[str], *, timeout: int, attempts: int = 3
) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(max(1, attempts)):
        # codeql[py/command-line-injection] cmd is built by _runner_cmd with a
        # fixed executable, shell=False, a validated public URL, and a "--" URL delimiter.
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 or attempt == attempts - 1:
            return result
        time.sleep(0.5 * (2**attempt))
    return result or subprocess.CompletedProcess(cmd, 1, "", "yt-dlp failed")


def _source_metrics_from_info_json(tmp_dir: Path, stem: str) -> dict[str, object]:
    candidates = sorted(tmp_dir.glob(f"{stem}*.info.json"))
    if not candidates:
        return {}
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        key: payload.get(key)
        for key in (
            "id",
            "webpage_url",
            "uploader",
            "uploader_id",
            "upload_date",
            "timestamp",
            "view_count",
            "like_count",
            "comment_count",
            "repost_count",
            "duration",
        )
        if payload.get(key) is not None
    }
