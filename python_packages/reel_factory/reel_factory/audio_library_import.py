#!/usr/bin/env python3
"""Import a licensed local audio track with durable proof metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from .fileops import atomic_write_json
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_json

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".wav"}
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def _slug(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (normalized or fallback)[:64].rstrip("_")


def _extension(*, file: Path | None, url: str | None) -> str:
    suffix = file.suffix if file is not None else Path(urlparse(url or "").path).suffix
    suffix = suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise ValueError(f"audio source must use one of: {allowed}")
    return suffix


def _read_local(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"audio file is empty: {path}")
    if size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"audio file exceeds {MAX_DOWNLOAD_BYTES} bytes")
    return path.read_bytes()


def _download(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an absolute HTTP(S) direct-download URL")
    request = Request(url, headers={"User-Agent": "CreatorOS-AudioImporter/1.0"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied URL
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"audio download exceeds {MAX_DOWNLOAD_BYTES} bytes")
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if not payload:
        raise ValueError("audio download returned an empty response")
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"audio download exceeds {MAX_DOWNLOAD_BYTES} bytes")
    return payload


def _validate_audio(path: Path) -> None:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "ffprobe rejected the audio file")
    try:
        streams = json.loads(result.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid audio metadata") from exc
    if not streams or not streams[0].get("codec_name"):
        raise ValueError("audio source does not contain a decodable audio stream")


def _install_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = hashlib.sha256(destination.read_bytes()).hexdigest()
        incoming = hashlib.sha256(payload).hexdigest()
        if existing != incoming:
            raise FileExistsError(f"refusing to replace different audio: {destination}")
        _validate_audio(destination)
        return

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_audio(temp_path)
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def import_audio_track(
    *,
    root: Path,
    title: str,
    artist: str,
    source: str,
    license_name: str,
    license_url: str,
    page_url: str,
    tags: list[str],
    file: Path | None = None,
    url: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    if (file is None) == (url is None):
        raise ValueError("provide exactly one of file or url")

    extension = _extension(file=file, url=url)
    payload = _read_local(file) if file is not None else _download(url or "")
    digest = hashlib.sha256(payload).hexdigest()
    source_slug = _slug(source, fallback="audio")
    artist_slug = _slug(artist, fallback="artist")
    title_slug = _slug(title, fallback="track")
    track_id = f"{source_slug}_{digest[:12]}"
    filename = f"{source_slug}_{artist_slug}_{title_slug}_{digest[:12]}{extension}"
    audio_path = root.resolve() / "03_audio_library" / filename
    sidecar_path = audio_path.with_suffix(".json")

    _install_atomic(audio_path, payload)
    metadata: dict[str, Any] = {
        "schema": "reel_factory.local_audio_track.v1",
        "track_id": track_id,
        "track_name": title,
        "title": title,
        "artist": artist,
        "source": source,
        "license": license_name,
        "license_url": license_url,
        "source_url": page_url,
        "page_url": page_url,
        "tags": sorted({tag.strip() for tag in tags if tag.strip()}),
        "sha256": digest,
        "mode": "licensed_music",
        "selection_source": "embedded_licensed_audio",
    }
    if url:
        metadata["download_url"] = url
    if file:
        metadata["imported_filename"] = file.name
    if attribution:
        metadata["attribution"] = attribution
    atomic_write_json(sidecar_path, metadata)
    return {
        "audio_path": str(audio_path),
        "sidecar_path": str(sidecar_path),
        "metadata": metadata,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--file", type=Path)
    source_group.add_argument("--url")
    parser.add_argument("--title", required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--license-url", required=True)
    parser.add_argument("--page-url", required=True)
    parser.add_argument("--attribution")
    parser.add_argument("--tag", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = import_audio_track(
        root=args.root,
        file=args.file,
        url=args.url,
        title=args.title,
        artist=args.artist,
        source=args.source,
        license_name=args.license_name,
        license_url=args.license_url,
        page_url=args.page_url,
        attribution=args.attribution,
        tags=args.tag,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
