#!/usr/bin/env python3
"""Import explicitly licensed local audio into Reel Factory's mux library."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac"}


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in cleaned.split("_") if part) or "track"


def _ext_from_url(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(f"audio URL must end with one of {sorted(AUDIO_EXTS)}")
    return ext


def import_audio(
    *,
    root: Path,
    url: str,
    title: str,
    artist: str,
    source: str,
    license_name: str,
    license_url: str,
    page_url: str,
    tags: list[str],
) -> dict[str, str]:
    out_dir = root.resolve() / "03_audio_library"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _slug(f"{source}_{artist}_{title}")
    audio_path = out_dir / f"{stem}{_ext_from_url(url)}"
    with urlopen(url, timeout=60) as response, audio_path.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    sha = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    track_id = f"{_slug(source)}_{sha[:12]}"
    meta = {
        "schema": "reel_factory.local_audio_track.v1",
        "track_id": track_id,
        "track_name": title,
        "title": title,
        "artist": artist,
        "source": source,
        "license": license_name,
        "license_url": license_url,
        "source_url": page_url,
        "download_url": url,
        "tags": sorted({_slug(tag) for tag in tags if tag.strip()}),
        "sha256": sha,
        "mode": "licensed_music",
        "selection_source": "embedded_licensed_audio",
    }
    meta_path = audio_path.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"audio_path": str(audio_path), "meta_path": str(meta_path), "track_id": track_id}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--url", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--license", required=True, dest="license_name")
    ap.add_argument("--license-url", required=True)
    ap.add_argument("--page-url", required=True)
    ap.add_argument("--tag", action="append", default=[])
    args = ap.parse_args()
    print(json.dumps(import_audio(
        root=args.root,
        url=args.url,
        title=args.title,
        artist=args.artist,
        source=args.source,
        license_name=args.license_name,
        license_url=args.license_url,
        page_url=args.page_url,
        tags=args.tag,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
