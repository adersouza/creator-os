#!/usr/bin/env python3
"""Download a social reel URL into the local source-video folder."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
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
    dest = out_dir / f"{stem}.mp4"
    if dest.exists():
        raise FileExistsError(f"source clip already exists: {dest}")
    with tempfile.TemporaryDirectory(prefix=f"{stem}_", dir=str(out_dir)) as tmp:
        tmp_dir = Path(tmp)
        template = tmp_dir / f"{stem}.%(ext)s"
        cmd = _runner_cmd(url, template)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
        if media.suffix.lower() == ".mp4":
            shutil.move(str(media), dest)
        else:
            # Keep this import path dependency-free; yt-dlp usually remuxes to
            # mp4 above, but if a site refuses that, preserve the bytes in mp4
            # naming so the existing source pipeline can still attempt probing.
            shutil.move(str(media), dest)
    return {
        "ok": True,
        "url": url,
        "stem": stem,
        "path": str(dest.resolve()),
        "command": cmd,
    }


def write_url_sidecar(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
