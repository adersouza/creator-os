#!/usr/bin/env python3
"""Refresh AudioProviderV1 pool files from reviewed or official audio exports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from audio_provider import (
    DEFAULT_ALLOWED_TAGS,
    local_winners_path,
    trending_cml_path,
    watch_list_path,
)
from .fileops import atomic_write_text

SCHEMA = "reel_factory.audio_refresh.v1"
KEEP_CML_REVIEW_INDICES = {1, 3, 4, 7, 8, 10}
KEEP_LOCAL_REVIEW_INDICES = {24, 25, 26}
WATCH_REVIEW_INDICES = {2, 5, 6, 9, 11, 12, 18, 19, 23}


def audio_sources_dir(root: Path) -> Path:
    return Path(root).resolve() / "project_data" / "audio_sources"


def refresh_log_path(root: Path) -> Path:
    return audio_sources_dir(root) / "refresh_log.jsonl"


def default_cml_drop_dir(root: Path) -> Path:
    return audio_sources_dir(root) / "official_cml_inbox"


def refresh_state_path(root: Path) -> Path:
    return audio_sources_dir(root) / "refresh_state.json"


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in cleaned.split("_") if part) or "track"


def _load_json_or_csv(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("tracks") or data.get("items") or data.get("candidates") or []
    if not isinstance(data, list):
        raise ValueError(
            f"{path} must contain a list or an object with tracks/items/candidates"
        )
    return [row for row in data if isinstance(row, dict)]


def _coerce_tags(record: dict[str, Any]) -> list[str]:
    raw = record.get("tags") or record.get("moods") or record.get("genres") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace(";", ",").split(",")]
    return sorted({_slug(str(tag)) for tag in raw if str(tag).strip()})


def _normalize_track(
    record: dict[str, Any], *, default_source: str, pool: str | None = None
) -> dict[str, Any]:
    name = str(
        record.get("track_name") or record.get("name") or record.get("title") or ""
    ).strip()
    artist = str(record.get("artist") or record.get("author") or "").strip()
    if not name:
        raise ValueError("track record missing track_name/name/title")
    source = str(record.get("source") or default_source).strip() or default_source
    track_id = str(record.get("track_id") or record.get("id") or "").strip()
    if not track_id:
        track_id = f"{_slug(source)}_{_slug(name)}_{_slug(artist)}".strip("_")
    raw_rank = record.get("trend_rank") or record.get("rank")
    try:
        trend_rank = int(raw_rank) if raw_rank not in (None, "") else None
    except (TypeError, ValueError):
        trend_rank = None
    out: dict[str, Any] = {
        "track_id": track_id,
        "track_name": name,
        "source": source,
        "tags": _coerce_tags(record),
    }
    if artist:
        out["artist"] = artist
    if trend_rank is not None:
        out["trend_rank"] = trend_rank
    if pool:
        out["pool"] = pool
    for key in ("review_index", "metadata"):
        if record.get(key) is not None:
            out[key] = record[key]
    return out


def _write_pool(
    path: Path,
    *,
    pool: str,
    tracks: list[dict[str, Any]],
    source_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "reel_factory.audio_pool.v1",
        "refreshed_at": int(time.time()),
        "pool": pool,
        "source_path": str(source_path) if source_path else None,
        "tracks": tracks,
    }
    atomic_write_text(path, 
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _append_refresh_log(root: Path, payload: dict[str, Any]) -> None:
    path = refresh_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": SCHEMA + ".log", "created_at": int(time.time()), **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_refresh_state(root: Path) -> dict[str, Any]:
    path = refresh_state_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_refresh_state(root: Path, state: dict[str, Any]) -> None:
    path = refresh_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, 
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def refresh_from_review(root: Path, review_path: Path) -> dict[str, Any]:
    rows = _load_json_or_csv(review_path)
    by_index = {
        int(row.get("review_index") or idx): row
        for idx, row in enumerate(rows, start=1)
    }
    cml = [
        _normalize_track(by_index[idx], default_source="tiktok_cml", pool="cml_primary")
        for idx in sorted(KEEP_CML_REVIEW_INDICES)
        if idx in by_index
    ]
    local = [
        _normalize_track(
            by_index[idx], default_source="local_archive_audio_id", pool="local_winners"
        )
        for idx in sorted(KEEP_LOCAL_REVIEW_INDICES)
        if idx in by_index
    ]
    watch = [
        _normalize_track(by_index[idx], default_source="watch_list", pool="watch_list")
        for idx in sorted(WATCH_REVIEW_INDICES)
        if idx in by_index
    ]
    _write_pool(
        trending_cml_path(root), pool="cml_primary", tracks=cml, source_path=review_path
    )
    _write_pool(
        local_winners_path(root),
        pool="local_winners",
        tracks=local,
        source_path=review_path,
    )
    _write_pool(
        watch_list_path(root), pool="watch_list", tracks=watch, source_path=review_path
    )
    result = {
        "source": "review",
        "cml": len(cml),
        "local_winners": len(local),
        "watch_list": len(watch),
    }
    _append_refresh_log(root, result)
    return result


def refresh_cml_from_export(
    root: Path, export_path: Path, *, limit: int = 100
) -> dict[str, Any]:
    allowed = set(DEFAULT_ALLOWED_TAGS)
    tracks = []
    for record in _load_json_or_csv(export_path):
        track = _normalize_track(
            record, default_source="tiktok_cml", pool="cml_primary"
        )
        if allowed and not (set(track.get("tags") or []) & allowed):
            continue
        tracks.append(track)
    tracks.sort(key=lambda row: (row.get("trend_rank", 999999), row["track_name"]))
    tracks = tracks[:limit]
    _write_pool(
        trending_cml_path(root),
        pool="cml_primary",
        tracks=tracks,
        source_path=export_path,
    )
    result = {
        "source": "official_cml_export",
        "cml": len(tracks),
        "path": str(export_path),
    }
    _append_refresh_log(root, result)
    return result


def refresh_latest_cml_export(
    root: Path, *, drop_dir: Path | None = None, limit: int = 100
) -> dict[str, Any]:
    inbox = (drop_dir or default_cml_drop_dir(root)).expanduser().resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        [path for path in inbox.iterdir() if path.suffix.lower() in {".json", ".csv"}],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        result = {
            "source": "official_cml_drop_dir",
            "status": "no_export_found",
            "drop_dir": str(inbox),
        }
        _append_refresh_log(root, result)
        return result
    latest = candidates[0]
    latest_hash = _file_sha256(latest)
    state = _load_refresh_state(root)
    if state.get("last_cml_export_sha256") == latest_hash:
        result = {
            "source": "official_cml_drop_dir",
            "status": "already_imported",
            "path": str(latest),
            "sha256": latest_hash,
        }
        _append_refresh_log(root, result)
        return result
    result = refresh_cml_from_export(root, latest, limit=limit)
    state.update(
        {
            "last_cml_export_path": str(latest),
            "last_cml_export_sha256": latest_hash,
            "last_cml_refresh_at": int(time.time()),
        }
    )
    _write_refresh_state(root, state)
    result.update({"status": "imported", "sha256": latest_hash})
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--review-candidates", type=Path)
    ap.add_argument("--cml-export", type=Path)
    ap.add_argument(
        "--latest-cml-export",
        action="store_true",
        help="import the newest .json/.csv official CML export from the drop directory",
    )
    ap.add_argument(
        "--drop-dir",
        type=Path,
        help="directory for official TikTok CML exports; default project_data/audio_sources/official_cml_inbox",
    )
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    results = []
    if args.review_candidates:
        results.append(refresh_from_review(args.root, args.review_candidates))
    if args.cml_export:
        results.append(
            refresh_cml_from_export(args.root, args.cml_export, limit=args.limit)
        )
    if args.latest_cml_export:
        results.append(
            refresh_latest_cml_export(
                args.root, drop_dir=args.drop_dir, limit=args.limit
            )
        )
    if not results:
        raise SystemExit("provide --review-candidates or --cml-export")
    print(json.dumps({"ok": True, "results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
