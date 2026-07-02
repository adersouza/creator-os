#!/usr/bin/env python3
"""Download a social reel URL into the local source-video folder."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


def _validate_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("reel URL must be an http(s) URL")
    return url


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
        url,
    ]


def _runner_cmd(url: str, output_template: Path) -> list[str]:
    if shutil.which("yt-dlp"):
        return _yt_dlp_cmd(url, output_template)
    return [
        "python3",
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
