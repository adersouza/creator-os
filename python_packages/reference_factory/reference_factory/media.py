from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .config import DEFAULT_DATA_ROOT
from .db import json_dump
from .identity import stable_id
from .timeutil import now_iso


def parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return None
            return round(float(num) / den_f, 3)
        except ValueError:
            return None
    try:
        return round(float(value), 3)
    except ValueError:
        return None


def ffprobe_video(path: Path, timeout: int = 20) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - persisted as probe failure.
        return {"valid": False, "error": str(exc)}
    if result.returncode != 0:
        return {
            "valid": False,
            "error": (result.stderr or result.stdout).strip()[:1000],
        }
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": f"ffprobe JSON parse failed: {exc}"}
    video = next(
        (s for s in raw.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if not video:
        return {"valid": False, "error": "no video stream", "probe_json": raw}
    duration = video.get("duration") or raw.get("format", {}).get("duration")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rotation = rotation_from_stream(video)
    if rotation in {90, 270} and width and height:
        display_width, display_height = height, width
    else:
        display_width, display_height = width, height
    return {
        "valid": width > 0 and height > 0,
        "duration_seconds": safe_float(duration),
        "width": display_width,
        "height": display_height,
        "fps": parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "codec": video.get("codec_name"),
        "aspect_ratio": round(display_width / display_height, 4)
        if display_width and display_height
        else None,
        "rotation": rotation,
        "probe_json": raw,
        "error": None,
    }


def rotation_from_stream(stream: dict[str, Any]) -> int:
    for side_data in stream.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                return abs(int(float(side_data["rotation"]))) % 360
            except (ValueError, TypeError):
                return 0
    tags = stream.get("tags") or {}
    try:
        return abs(int(float(tags.get("rotate", 0)))) % 360
    except (ValueError, TypeError):
        return 0


def safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def probe_videos(conn: Connection, limit: int | None = None) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT sf.reference_id, sf.path
        FROM source_files sf
        WHERE sf.kind = 'video'
        ORDER BY sf.account, sf.file_name
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    valid = 0
    invalid = 0
    for row in rows:
        path = Path(row["path"])
        probe = ffprobe_video(path)
        if probe.get("valid"):
            valid += 1
        else:
            invalid += 1
        conn.execute(
            """
            INSERT INTO video_probes (
              reference_id, valid, duration_seconds, width, height, fps,
              codec, aspect_ratio, rotation, probe_json, error, probed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
              valid = excluded.valid,
              duration_seconds = excluded.duration_seconds,
              width = excluded.width,
              height = excluded.height,
              fps = excluded.fps,
              codec = excluded.codec,
              aspect_ratio = excluded.aspect_ratio,
              rotation = excluded.rotation,
              probe_json = excluded.probe_json,
              error = excluded.error,
              probed_at = excluded.probed_at
            """,
            (
                row["reference_id"],
                1 if probe.get("valid") else 0,
                probe.get("duration_seconds"),
                probe.get("width"),
                probe.get("height"),
                probe.get("fps"),
                probe.get("codec"),
                probe.get("aspect_ratio"),
                probe.get("rotation"),
                json_dump(probe.get("probe_json") or {}),
                probe.get("error"),
                now_iso(),
            ),
        )
    conn.commit()
    return {
        "schema": "reference_factory.probe.v1",
        "requested": len(rows),
        "valid": valid,
        "invalid": invalid,
    }


def sample_times(duration: float | None) -> list[tuple[str, float]]:
    duration = duration or 3.0
    candidates = [
        ("opening", 0.1),
        ("hook_1s", min(1.0, max(0.1, duration * 0.2))),
        ("middle", max(0.1, duration * 0.5)),
        ("late", max(0.1, duration * 0.82)),
        ("cover", max(0.1, duration * 0.35)),
    ]
    seen: set[float] = set()
    result: list[tuple[str, float]] = []
    for role, time_sec in candidates:
        bounded = min(max(time_sec, 0.05), max(duration - 0.05, 0.05))
        rounded = round(bounded, 2)
        if rounded in seen:
            continue
        seen.add(rounded)
        result.append((role, rounded))
    return result


def extract_frame(video_path: Path, output_path: Path, time_sec: float) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(time_sec),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(540,iw)':-2",
        str(output_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=30
    )
    return (
        result.returncode == 0
        and output_path.exists()
        and output_path.stat().st_size > 0
    )


def sample_frames(
    conn: Connection,
    data_root: Path = DEFAULT_DATA_ROOT,
    limit: int | None = None,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT sf.reference_id, sf.path, vp.duration_seconds
        FROM source_files sf
        JOIN video_probes vp ON vp.reference_id = sf.reference_id
        WHERE sf.kind = 'video' AND vp.valid = 1
        ORDER BY sf.account, sf.file_name
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    videos = 0
    frames = 0
    failed = 0
    timestamp = now_iso()
    for row in rows:
        videos += 1
        video_path = Path(row["path"])
        ref_dir = data_root / "frame_samples" / row["reference_id"]
        for role, time_sec in sample_times(row["duration_seconds"]):
            frame_id = stable_id("frame", row["reference_id"], role)
            frame_path = ref_dir / f"{role}.jpg"
            ok = extract_frame(video_path, frame_path, time_sec)
            if ok:
                frames += 1
                thumb_path = data_root / "thumbnails" / f"{row['reference_id']}.jpg"
                if role in {"hook_1s", "middle"} and not thumb_path.exists():
                    thumb_path.parent.mkdir(parents=True, exist_ok=True)
                    thumb_path.write_bytes(frame_path.read_bytes())
                conn.execute(
                    """
                    INSERT INTO frame_samples (
                      id, reference_id, time_sec, role, frame_path, width, height, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
                    ON CONFLICT(reference_id, role) DO UPDATE SET
                      time_sec = excluded.time_sec,
                      frame_path = excluded.frame_path
                    """,
                    (
                        frame_id,
                        row["reference_id"],
                        time_sec,
                        role,
                        str(frame_path),
                        timestamp,
                    ),
                )
            else:
                failed += 1
    conn.commit()
    return {
        "schema": "reference_factory.sample_frames.v1",
        "videos": videos,
        "frames": frames,
        "failedFrames": failed,
    }


def thumbnail_batch(
    conn: Connection,
    data_root: Path = DEFAULT_DATA_ROOT,
    limit: int | None = None,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT sf.reference_id, sf.path, vp.duration_seconds
        FROM source_files sf
        JOIN video_probes vp ON vp.reference_id = sf.reference_id
        LEFT JOIN frame_samples fs
          ON fs.reference_id = sf.reference_id
         AND fs.role = 'contact'
        WHERE sf.kind = 'video'
          AND vp.valid = 1
          AND fs.id IS NULL
        ORDER BY sf.account, sf.file_name
        """
    ).fetchall()
    total_missing = len(rows)
    if limit is not None:
        rows = rows[:limit]
    created = 0
    failed = 0
    timestamp = now_iso()
    for row in rows:
        duration = row["duration_seconds"]
        time_sec = 1.0
        if isinstance(duration, (int, float)) and duration > 0:
            time_sec = min(1.0, max(0.1, duration * 0.2))
        frame_id = stable_id("frame", row["reference_id"], "contact")
        frame_path = data_root / "frame_samples" / row["reference_id"] / "contact.jpg"
        if extract_frame(Path(row["path"]), frame_path, time_sec):
            created += 1
            conn.execute(
                """
                INSERT INTO frame_samples (
                  id, reference_id, time_sec, role, frame_path, width, height, created_at
                )
                VALUES (?, ?, ?, 'contact', ?, NULL, NULL, ?)
                ON CONFLICT(reference_id, role) DO UPDATE SET
                  time_sec = excluded.time_sec,
                  frame_path = excluded.frame_path
                """,
                (frame_id, row["reference_id"], time_sec, str(frame_path), timestamp),
            )
        else:
            failed += 1
    conn.commit()
    return {
        "schema": "reference_factory.thumbnail_batch.v1",
        "missingBeforeRun": total_missing,
        "requested": len(rows),
        "created": created,
        "failed": failed,
        "remaining": max(0, total_missing - created),
    }
