from __future__ import annotations

from sqlite3 import Connection


def score_reference(row: dict[str, object]) -> tuple[int, list[str]]:
    score = 50
    reasons: list[str] = []
    if row.get("valid"):
        score += 12
        reasons.append("valid video")
    width = row.get("width") or 0
    height = row.get("height") or 0
    aspect = row.get("aspect_ratio") or 0
    duration = row.get("duration_seconds") or 0
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        if width >= 720 and height >= 1280:
            score += 10
            reasons.append("good vertical resolution")
        elif width < 360 or height < 640:
            score -= 12
            reasons.append("low resolution")
    if isinstance(aspect, (int, float)):
        if 0.50 <= aspect <= 0.62:
            score += 8
            reasons.append("vertical reels aspect")
        elif aspect > 1.0:
            score -= 12
            reasons.append("horizontal/weird aspect")
    if isinstance(duration, (int, float)):
        if 4 <= duration <= 30:
            score += 8
            reasons.append("useful short-form duration")
        elif duration < 1.5:
            score -= 18
            reasons.append("too short")
        elif duration > 90:
            score -= 8
            reasons.append("long video")
    if row.get("caption_count"):
        score += 12
        reasons.append("caption text detected")
    if row.get("frame_count"):
        score += 4
        reasons.append("sampled frames available")
    return max(0, min(100, score)), reasons


def shortlist(conn: Connection, target: int = 300) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT
          sf.reference_id, sf.account, sf.file_name,
          vp.valid, vp.duration_seconds, vp.width, vp.height, vp.aspect_ratio,
          COUNT(DISTINCT fs.id) AS frame_count,
          COUNT(DISTINCT cp.caption_hash) AS caption_count
        FROM source_files sf
        JOIN video_probes vp ON vp.reference_id = sf.reference_id
        LEFT JOIN frame_samples fs ON fs.reference_id = sf.reference_id
        LEFT JOIN caption_patterns cp ON cp.reference_id = sf.reference_id
        WHERE sf.kind = 'video'
        GROUP BY sf.reference_id
        """
    ).fetchall()
    scored = []
    for row in rows:
        item = dict(row)
        score, reasons = score_reference(item)
        item["score"] = score
        item["reasons"] = reasons
        scored.append(item)
    scored.sort(
        key=lambda item: (
            -item["score"],
            item.get("account") or "",
            item.get("file_name") or "",
        )
    )
    return {
        "schema": "reference_factory.shortlist.v1",
        "target": target,
        "available": len(scored),
        "items": scored[:target],
    }
