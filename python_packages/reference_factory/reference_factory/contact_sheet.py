from __future__ import annotations

import html
import json
import random
import subprocess
from pathlib import Path
from sqlite3 import Connection

from .config import DEFAULT_DATA_ROOT
from .db import json_dump
from .identity import stable_id
from .media import extract_frame
from .scoring import score_reference
from .timeutil import now_iso


def select_references(
    conn: Connection,
    mode: str,
    count: int = 100,
    per_account: int = 25,
) -> list[dict[str, object]]:
    base_query = """
      SELECT
        sf.reference_id, sf.account, sf.file_name, sf.path,
        vp.valid, vp.duration_seconds, vp.width, vp.height, vp.aspect_ratio,
        thumb.frame_path AS thumbnail_path,
        COUNT(DISTINCT cp.caption_hash) AS caption_count,
        GROUP_CONCAT(DISTINCT cp.first_line) AS caption_preview
      FROM source_files sf
      JOIN video_probes vp ON vp.reference_id = sf.reference_id
      LEFT JOIN frame_samples thumb
        ON thumb.reference_id = sf.reference_id
       AND thumb.role IN ('hook_1s', 'middle', 'opening')
      LEFT JOIN caption_patterns cp ON cp.reference_id = sf.reference_id
      WHERE sf.kind = 'video' AND vp.valid = 1
      GROUP BY sf.reference_id
    """
    rows = [dict(row) for row in conn.execute(base_query).fetchall()]
    for row in rows:
        score, reasons = score_reference(row)
        row["score"] = score
        row["reasons"] = reasons
    if mode == "random":
        random.seed(1337)
        random.shuffle(rows)
        return rows[:count]
    if mode == "captioned":
        return sorted(
            [row for row in rows if int(row.get("caption_count") or 0) > 0],
            key=lambda row: (-int(row["score"]), row.get("account") or ""),
        )[:count]
    if mode == "visual":
        return sorted(
            [row for row in rows if int(row.get("caption_count") or 0) == 0],
            key=lambda row: (-int(row["score"]), row.get("account") or ""),
        )[:count]
    if mode == "unreviewed":
        labeled = {
            row["reference_id"]
            for row in conn.execute("SELECT reference_id FROM review_labels").fetchall()
        }
        return sorted(
            [row for row in rows if row["reference_id"] not in labeled],
            key=lambda row: (-int(row["score"]), row.get("account") or ""),
        )[:count]
    if mode == "top-accounts":
        selected: list[dict[str, object]] = []
        by_account: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_account.setdefault(str(row.get("account") or "_root"), []).append(row)
        for account in sorted(by_account, key=lambda key: -len(by_account[key])):
            group = sorted(by_account[account], key=lambda row: -int(row["score"]))
            selected.extend(group[:per_account])
            if len(selected) >= count:
                break
        return selected[:count]
    return sorted(rows, key=lambda row: -int(row["score"]))[:count]


def generate_contact_sheet(
    conn: Connection,
    mode: str,
    count: int = 100,
    per_account: int = 25,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> dict[str, object]:
    refs = select_references(conn, mode=mode, count=count, per_account=per_account)
    ensure_thumbnails(conn, refs, data_root)
    timestamp = now_iso().replace(":", "").replace("+", "Z")
    sheet_id = stable_id("sheet", mode, count, per_account, timestamp)
    sheet_dir = data_root / "contact_sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    html_path = sheet_dir / f"{sheet_id}.html"
    image_path = sheet_dir / f"{sheet_id}.jpg"
    write_html(html_path, refs, mode)
    write_montage(image_path, refs)
    conn.execute(
        """
        INSERT INTO contact_sheets (
          id, mode, sheet_path, html_path, reference_ids_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            sheet_id,
            mode,
            str(image_path),
            str(html_path),
            json_dump([row["reference_id"] for row in refs]),
            now_iso(),
        ),
    )
    conn.commit()
    return {
        "schema": "reference_factory.contact_sheet.v1",
        "id": sheet_id,
        "mode": mode,
        "count": len(refs),
        "htmlPath": str(html_path),
        "imagePath": str(image_path),
    }


def ensure_thumbnails(conn: Connection, refs: list[dict[str, object]], data_root: Path) -> None:
    timestamp = now_iso()
    for row in refs:
        thumb = row.get("thumbnail_path")
        if thumb and Path(str(thumb)).exists():
            continue
        reference_id = str(row["reference_id"])
        video_path = Path(str(row["path"]))
        duration = row.get("duration_seconds")
        time_sec = 1.0
        if isinstance(duration, (int, float)) and duration > 0:
            time_sec = min(1.0, max(0.1, duration * 0.2))
        frame_id = stable_id("frame", reference_id, "contact")
        frame_path = data_root / "frame_samples" / reference_id / "contact.jpg"
        if extract_frame(video_path, frame_path, time_sec):
            row["thumbnail_path"] = str(frame_path)
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
                (frame_id, reference_id, time_sec, str(frame_path), timestamp),
            )
    conn.commit()


def write_html(path: Path, refs: list[dict[str, object]], mode: str) -> None:
    cards = []
    for row in refs:
        thumb = row.get("thumbnail_path") or ""
        reference_id = str(row["reference_id"])
        caption_preview = str(row.get("caption_preview") or "").split(",")[0]
        label_cmd = (
            "python3 -m reference_factory.cli label "
            f"--reference-id {reference_id} --label gold --tags visual"
        )
        cards.append(
            f"""
            <article class="card">
              <img src="{html.escape(str(thumb))}" alt="{html.escape(reference_id)}">
              <div class="meta">
                <strong>{html.escape(str(row.get("account") or ""))}</strong>
                <span>{html.escape(str(row.get("file_name") or ""))}</span>
                <span>{html.escape(format_video_meta(row))}</span>
                <span>score {html.escape(str(row.get("score") or ""))}</span>
                <p>{html.escape(caption_preview[:140])}</p>
                <code>{html.escape(label_cmd)}</code>
              </div>
            </article>
            """
        )
    path.write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Reference Factory Contact Sheet - {html.escape(mode)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font: 14px system-ui, sans-serif; background: #111; color: #eee; }}
    h1 {{ margin: 0 0 18px; font-size: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
    .card {{ background: #1b1b1b; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
    img {{ width: 100%; aspect-ratio: 9/16; object-fit: cover; background: #050505; display: block; }}
    .meta {{ padding: 10px; display: grid; gap: 5px; }}
    span, p {{ color: #bbb; margin: 0; overflow-wrap: anywhere; }}
    code {{ display: block; color: #99e6ff; font-size: 11px; white-space: pre-wrap; background: #050505; padding: 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Reference Factory Contact Sheet - {html.escape(mode)} ({len(refs)})</h1>
  <section class="grid">{''.join(cards)}</section>
</body>
</html>
""",
        encoding="utf-8",
    )


def write_montage(path: Path, refs: list[dict[str, object]]) -> None:
    thumbs = [str(row.get("thumbnail_path")) for row in refs if row.get("thumbnail_path") and Path(str(row.get("thumbnail_path"))).exists()]
    if not thumbs:
        path.write_text("No thumbnails available yet.\n", encoding="utf-8")
        return
    with tempfile_list(thumbs) as list_path:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vf",
                "scale=180:-2,tile=5x10",
                "-frames:v",
                "1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


class tempfile_list:
    def __init__(self, paths: list[str]):
        self.paths = paths
        self.path: Path | None = None

    def __enter__(self) -> Path:
        import tempfile

        fd, name = tempfile.mkstemp(prefix="reference-factory-thumbs-", suffix=".txt")
        self.path = Path(name)
        with open(fd, "w", encoding="utf-8", closefd=True) as f:
            for path in self.paths[:50]:
                escaped = path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        return self.path

    def __exit__(self, *_exc: object) -> None:
        if self.path:
            self.path.unlink(missing_ok=True)


def format_video_meta(row: dict[str, object]) -> str:
    dur = row.get("duration_seconds")
    width = row.get("width") or "?"
    height = row.get("height") or "?"
    duration = f"{float(dur):.1f}s" if isinstance(dur, (int, float)) else "?s"
    return f"{duration} · {width}x{height}"
