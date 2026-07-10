#!/usr/bin/env python3
"""Simple audio selection metadata provider for social posting workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text

SCHEMA = "reel_factory.audio_provider.v1"
AUDIO_PROVIDER_MODES = {"AUTO_TRENDING", "SAFE_LIBRARY", "CUSTOM"}
CML_PRIMARY_WEIGHT = 0.60
LOCAL_WINNER_WEIGHT = 0.30
WATCH_LIST_WEIGHT = 0.10
DEFAULT_ALLOWED_TAGS = {
    "upbeat",
    "pop",
    "electronic",
    "lifestyle",
    "fashion",
    "confidence",
    "luxury",
    "chill",
}


@dataclass(frozen=True)
class AudioTrack:
    track_id: str
    track_name: str
    source: str
    trend_rank: int | None = None
    tags: tuple[str, ...] = ()
    artist: str | None = None
    metadata: dict[str, Any] | None = None


def trending_cml_path(root: Path) -> Path:
    return (
        Path(root).resolve()
        / "project_data"
        / "audio_sources"
        / "tiktok_cml_trending.json"
    )


def curated_winners_path(root: Path) -> Path:
    return (
        Path(root).resolve() / "project_data" / "audio_sources" / "curated_winners.json"
    )


def local_winners_path(root: Path) -> Path:
    return (
        Path(root).resolve() / "project_data" / "audio_sources" / "local_winners.json"
    )


def watch_list_path(root: Path) -> Path:
    return Path(root).resolve() / "project_data" / "audio_sources" / "watch_list.json"


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in cleaned.split("_") if part) or "track"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("tracks") or data.get("items") or []
    return data


def _track_from_record(record: dict[str, Any], *, default_source: str) -> AudioTrack:
    name = str(
        record.get("track_name") or record.get("name") or record.get("title") or ""
    ).strip()
    if not name:
        raise ValueError("audio track is missing track_name/name/title")
    source = str(record.get("source") or default_source).strip() or default_source
    raw_tags = record.get("tags") or record.get("moods") or record.get("genres") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags = tuple(sorted({_slug(str(tag)) for tag in raw_tags if str(tag).strip()}))
    raw_rank = record.get("trend_rank") or record.get("rank")
    try:
        trend_rank = int(raw_rank) if raw_rank is not None else None
    except (TypeError, ValueError):
        trend_rank = None
    track_id = str(record.get("track_id") or record.get("id") or "").strip()
    if not track_id:
        digest = hashlib.sha256(
            f"{source}|{name}|{record.get('artist') or ''}".encode()
        ).hexdigest()[:10]
        track_id = f"{_slug(source)}_{_slug(name)}_{digest}"
    metadata = {
        k: v
        for k, v in record.items()
        if k
        not in {
            "track_id",
            "id",
            "track_name",
            "name",
            "title",
            "source",
            "trend_rank",
            "rank",
            "tags",
            "moods",
            "genres",
            "artist",
        }
    }
    return AudioTrack(
        track_id=track_id,
        track_name=name,
        source=source,
        trend_rank=trend_rank,
        tags=tags,
        artist=str(record.get("artist")).strip() if record.get("artist") else None,
        metadata=metadata or None,
    )


def load_track_list(path: Path, *, default_source: str) -> list[AudioTrack]:
    tracks: list[AudioTrack] = []
    for record in _load_json(path):
        if isinstance(record, dict):
            tracks.append(_track_from_record(record, default_source=default_source))
    return tracks


def _matches_allowed_tags(track: AudioTrack, allowed_tags: set[str]) -> bool:
    if not allowed_tags:
        return True
    tags = set(track.tags)
    if tags & allowed_tags:
        return True
    meta = track.metadata or {}
    searchable = " ".join(
        str(meta.get(key) or "") for key in ("genre", "mood", "category", "description")
    )
    return bool({_slug(part) for part in searchable.split()} & allowed_tags)


def eligible_trending_tracks(
    root: Path, *, allowed_tags: set[str] | None = None, limit: int = 100
) -> list[AudioTrack]:
    allowed = {_slug(tag) for tag in (allowed_tags or DEFAULT_ALLOWED_TAGS)}
    tracks = [
        track
        for track in load_track_list(
            trending_cml_path(root), default_source="tiktok_cml"
        )
        if _matches_allowed_tags(track, allowed)
    ]
    tracks.sort(
        key=lambda track: (
            track.trend_rank if track.trend_rank is not None else 999999,
            track.track_name,
        )
    )
    return tracks[:limit]


def curated_winner_tracks(root: Path) -> list[AudioTrack]:
    tracks = load_track_list(curated_winners_path(root), default_source="safe_library")
    tracks.extend(
        load_track_list(
            local_winners_path(root), default_source="local_archive_audio_id"
        )
    )
    return _dedupe_tracks(tracks)


def watch_list_tracks(root: Path) -> list[AudioTrack]:
    return load_track_list(watch_list_path(root), default_source="watch_list")


def _dedupe_tracks(tracks: list[AudioTrack]) -> list[AudioTrack]:
    seen: set[str] = set()
    unique: list[AudioTrack] = []
    for track in tracks:
        if track.track_id in seen:
            continue
        seen.add(track.track_id)
        unique.append(track)
    return unique


def _choice(
    rng: random.Random, tracks: list[AudioTrack], *, reason: str
) -> dict[str, Any]:
    if not tracks:
        raise ValueError("cannot choose from an empty track list")
    track = rng.choice(tracks)
    payload = asdict(track)
    payload["tags"] = list(track.tags)
    payload.update(
        {
            "schema": SCHEMA + ".selection",
            "selected_reason": reason,
            "selected_at": int(time.time()),
        }
    )
    return payload


def _trend_weight(track: AudioTrack) -> float:
    if track.trend_rank is None:
        return 0.01
    return 1.0 / max(float(track.trend_rank), 1.0)


def _weighted_trending_choice(
    rng: random.Random, tracks: list[AudioTrack], *, reason: str
) -> dict[str, Any]:
    if not tracks:
        raise ValueError("cannot choose from an empty track list")
    weights = [_trend_weight(track) for track in tracks]
    track = rng.choices(tracks, weights=weights, k=1)[0]
    payload = asdict(track)
    payload["tags"] = list(track.tags)
    payload.update(
        {
            "schema": SCHEMA + ".selection",
            "selected_reason": reason,
            "selection_weight": round(_trend_weight(track), 6),
            "selected_at": int(time.time()),
        }
    )
    return payload


def select_audio(
    root: Path,
    *,
    mode: str = "AUTO_TRENDING",
    seed: int | str | None = None,
    custom_track: dict[str, Any] | None = None,
    allowed_tags: set[str] | None = None,
) -> dict[str, Any]:
    """Return one reviewable audio selection record.

    This does not call TikTok or attach audio. It selects from local cache files
    that can be refreshed by a separate business-safe CML integration.
    """
    mode = mode.upper()
    if mode not in AUDIO_PROVIDER_MODES:
        raise ValueError(f"audio mode must be one of {sorted(AUDIO_PROVIDER_MODES)}")
    rng = random.Random(str(seed if seed is not None else time.strftime("%Y-%m-%d")))
    if mode == "CUSTOM":
        if not custom_track:
            raise ValueError("CUSTOM audio mode requires custom_track")
        return _choice(
            rng,
            [_track_from_record(custom_track, default_source="custom")],
            reason="custom_manual_override",
        )

    cml_primary = eligible_trending_tracks(root, allowed_tags=allowed_tags)
    winners = curated_winner_tracks(root)
    watch_list = watch_list_tracks(root)
    if mode == "SAFE_LIBRARY":
        return _choice(rng, winners, reason="safe_library_curated_winner")
    if not cml_primary and not winners and not watch_list:
        raise FileNotFoundError(
            "no audio tracks available; add project_data/audio_sources/tiktok_cml_trending.json "
            "or project_data/audio_sources/local_winners.json"
        )

    roll = rng.random()
    if roll < CML_PRIMARY_WEIGHT and cml_primary:
        return _weighted_trending_choice(
            rng, cml_primary, reason="auto_cml_primary_60pct_rank_weighted"
        )
    if roll < CML_PRIMARY_WEIGHT + LOCAL_WINNER_WEIGHT and winners:
        return _choice(rng, winners, reason="auto_local_winner_30pct")
    if watch_list:
        return _choice(rng, watch_list, reason="auto_watch_list_10pct")
    if cml_primary:
        return _weighted_trending_choice(
            rng, cml_primary, reason="auto_fallback_cml_primary_rank_weighted"
        )
    return _choice(rng, winners, reason="auto_fallback_local_winner")


def write_selection(
    root: Path, selection: dict[str, Any], *, stem: str | None = None
) -> Path:
    out_dir = Path(root).resolve() / "project_data" / "audio_selections"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = stem or f"{selection.get('track_id', 'track')}_{int(time.time())}"
    path = out_dir / f"{_slug(name)}.json"
    atomic_write_text(path, 
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument(
        "--mode", choices=sorted(AUDIO_PROVIDER_MODES), default="AUTO_TRENDING"
    )
    ap.add_argument("--seed", default=None)
    ap.add_argument("--custom-track-json", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--stem")
    args = ap.parse_args()
    custom_track = None
    if args.custom_track_json:
        custom_track = json.loads(args.custom_track_json.read_text(encoding="utf-8"))
    selection = select_audio(
        args.root, mode=args.mode, seed=args.seed, custom_track=custom_track
    )
    if args.write:
        selection["selection_path"] = str(
            write_selection(args.root, selection, stem=args.stem)
        )
    print(json.dumps(selection, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
