#!/usr/bin/env python3
"""Feature extraction, experiments, cost analytics, and Winner DNA refresh."""
from __future__ import annotations

import argparse
import statistics
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from intelligence_store import (
    confidence_for_sample_size,
    data_quality_from_connection,
    ensure_intelligence_schema,
    json_dumps,
    low_data_warning,
    winner_score,
)


FEATURE_KEYS = ("scene", "camera", "pose", "motion", "outfit", "creator", "body_style", "caption_style", "hook_type")


def connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(root) / "manifest.sqlite")
    conn.row_factory = sqlite3.Row
    ensure_intelligence_schema(conn)
    return conn


def infer_features_from_text(text: str) -> dict[str, Any]:
    low = text.lower()
    scene = "unknown"
    if "bathroom" in low or "mirror" in low:
        scene = "bathroom_mirror"
    elif "beach" in low or "ocean" in low:
        scene = "beach"
    elif "living room" in low or "fireplace" in low:
        scene = "living_room"
    camera = "mirror_selfie" if "mirror" in low or "selfie" in low else "unknown"
    pose = "seated_side" if "seated" in low or "sitting" in low else ("standing" if "standing" in low else "unknown")
    motion = "hip_sway" if "hip" in low or "sway" in low else "unknown"
    outfit = "crop_top" if "crop top" in low else ("dress" if "dress" in low else ("bikini" if "bikini" in low else "unknown"))
    body_style = "thick_hourglass" if "hourglass" in low or "thick" in low or "curves" in low else "unknown"
    return {
        "scene": scene,
        "camera": camera,
        "pose": pose,
        "motion": motion,
        "outfit": outfit,
        "creator": "stacey" if "stacey" in low else "unknown",
        "grid_source": 1 if "grid" in low or "panel" in low else 0,
        "caption_style": "short_direct",
        "hook_type": "curiosity" if "?" in text or "wait" in low or "which" in low else "unknown",
        "body_style": body_style,
    }


def feature_text_for_output(root: Path, output_path: Path) -> str:
    parts = [output_path.stem.replace("_", " ")]
    lineage = output_path.with_suffix(output_path.suffix + ".generated_asset_lineage.json")
    if lineage.exists():
        try:
            parts.append(json.dumps(json.loads(lineage.read_text(encoding="utf-8")), ensure_ascii=False))
        except Exception:
            pass
    source_lineage = root / "00_source_videos" / f"{output_path.stem}.generated_asset_lineage.json"
    if source_lineage.exists():
        try:
            parts.append(json.dumps(json.loads(source_lineage.read_text(encoding="utf-8")), ensure_ascii=False))
        except Exception:
            pass
    return "\n".join(parts)


def upsert_reel_feature(root: Path, output_path: Path, *, asset_generation_id: str | None = None,
                        campaign_id: str | None = None,
                        source_reference_id: str | None = None,
                        features: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    output_path = Path(output_path).expanduser().resolve()
    conn = connect(root)
    features = features or infer_features_from_text(feature_text_for_output(root, output_path))
    now = int(time.time())
    feature_id = f"feat_{abs(hash(str(output_path))) & 0xffffffff:x}"
    conn.execute(
        """
        INSERT INTO reel_features (
            feature_id, output_path, asset_generation_id, campaign_id, source_reference_id,
            scene, camera, pose, motion, outfit, creator, grid_source, caption_style,
            hook_type, body_style, features_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(output_path) DO UPDATE SET
            asset_generation_id=COALESCE(excluded.asset_generation_id, reel_features.asset_generation_id),
            campaign_id=COALESCE(excluded.campaign_id, reel_features.campaign_id),
            source_reference_id=COALESCE(excluded.source_reference_id, reel_features.source_reference_id),
            scene=excluded.scene,
            camera=excluded.camera,
            pose=excluded.pose,
            motion=excluded.motion,
            outfit=excluded.outfit,
            creator=excluded.creator,
            grid_source=excluded.grid_source,
            caption_style=excluded.caption_style,
            hook_type=excluded.hook_type,
            body_style=excluded.body_style,
            features_json=excluded.features_json,
            updated_at=excluded.updated_at
        """,
        (
            feature_id, str(output_path), asset_generation_id, campaign_id, source_reference_id,
            features.get("scene"), features.get("camera"), features.get("pose"),
            features.get("motion"), features.get("outfit"), features.get("creator"),
            int(bool(features.get("grid_source"))), features.get("caption_style"),
            features.get("hook_type"), features.get("body_style"),
            json.dumps(features, ensure_ascii=False), now, now,
        ),
    )
    conn.commit()
    return {"ok": True, "feature_id": feature_id, "features": features}


def refresh_features(root: Path, *, limit: int | None = None) -> dict[str, Any]:
    conn = connect(root)
    rows = conn.execute(
        """
        SELECT co.output_path, co.asset_generation_id, co.campaign_id, ag.reference_id
        FROM campaign_outputs co
        LEFT JOIN asset_generations ag ON ag.asset_generation_id = co.asset_generation_id
        ORDER BY co.created_at DESC
        """
    ).fetchall()
    if limit:
        rows = rows[:limit]
    count = 0
    for row in rows:
        existing = conn.execute("SELECT 1 FROM reel_features WHERE output_path=?", (row["output_path"],)).fetchone()
        if existing:
            continue
        upsert_reel_feature(
            root,
            Path(row["output_path"]),
            asset_generation_id=row["asset_generation_id"],
            campaign_id=row["campaign_id"],
            source_reference_id=row["reference_id"],
        )
        count += 1
    return {"ok": True, "features_refreshed": count}


def assign_experiment(root: Path, *, name: str, group: str, output_path: str | None = None,
                      asset_generation_id: str | None = None, hypothesis: str = "",
                      notes: str = "") -> dict[str, Any]:
    conn = connect(root)
    now = int(time.time())
    exp_id = f"exp_{name.lower().replace(' ', '_')}"
    conn.execute(
        """
        INSERT INTO experiments (experiment_id, name, hypothesis, status, created_at)
        VALUES (?, ?, ?, 'active', ?)
        ON CONFLICT(name) DO UPDATE SET hypothesis=COALESCE(excluded.hypothesis, experiments.hypothesis)
        """,
        (exp_id, name, hypothesis, now),
    )
    assignment_id = f"assign_{time.time_ns()}"
    conn.execute(
        """
        INSERT INTO experiment_assignments (
            assignment_id, experiment_id, group_name, entity_type, entity_id,
            output_path, asset_generation_id, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (assignment_id, exp_id, group, "output" if output_path else "asset_generation",
         output_path or asset_generation_id, output_path, asset_generation_id, notes, now),
    )
    conn.commit()
    return {"ok": True, "experiment_id": exp_id, "assignment_id": assignment_id}


def record_cost(root: Path, *, entity_type: str, entity_id: str | None = None,
                output_path: str | None = None, asset_generation_id: str | None = None,
                soul_jobs: int = 0, kling_jobs: int = 0,
                estimated_generation_cost: float | None = None,
                render_time_sec: float | None = None,
                operator_seconds: float | None = None,
                notes: str = "") -> dict[str, Any]:
    conn = connect(root)
    cost_id = f"cost_{time.time_ns()}"
    conn.execute(
        """
        INSERT INTO cost_events (
            cost_id, entity_type, entity_id, output_path, asset_generation_id,
            soul_jobs, kling_jobs, estimated_generation_cost, render_time_sec,
            operator_seconds, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cost_id, entity_type, entity_id, output_path, asset_generation_id,
         soul_jobs, kling_jobs, estimated_generation_cost, render_time_sec,
         operator_seconds, notes, int(time.time())),
    )
    conn.commit()
    return {"ok": True, "cost_id": cost_id}


def _score_rows_for_costs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.*, o.views, o.likes, o.comments, o.shares, o.saves, o.manual_score
        FROM cost_events c
        LEFT JOIN reel_outcomes o
          ON (c.output_path IS NOT NULL AND (o.output_path = c.output_path OR o.filename = substr(c.output_path, length(c.output_path) - length(o.filename) + 1)))
          OR (c.asset_generation_id IS NOT NULL AND o.asset_generation_id = c.asset_generation_id)
        """
    ).fetchall()
    out = []
    for row in rows:
        score = winner_score(row)
        cost = float(row["estimated_generation_cost"] or 0)
        out.append(dict(row) | {
            "winner_score": round(score, 2),
            "winner_score_per_cost": round(score / cost, 4) if cost else None,
        })
    return out


def cost_analytics(root: Path) -> dict[str, Any]:
    conn = connect(root)
    assets = _score_rows_for_costs(conn)
    assets.sort(key=lambda row: (row["winner_score_per_cost"] is not None, row["winner_score_per_cost"] or 0, row["winner_score"]), reverse=True)
    grouped: dict[str, dict[str, Any]] = {}
    for row in assets:
        group = grouped.setdefault(row["entity_type"], {
            "entity_type": row["entity_type"],
            "count": 0,
            "total_cost": 0.0,
            "winner_score": 0.0,
            "soul_jobs": 0,
            "kling_jobs": 0,
            "render_time_sec": 0.0,
            "operator_seconds": 0.0,
        })
        group["count"] += 1
        group["total_cost"] += float(row["estimated_generation_cost"] or 0)
        group["winner_score"] += float(row["winner_score"] or 0)
        group["soul_jobs"] += int(row["soul_jobs"] or 0)
        group["kling_jobs"] += int(row["kling_jobs"] or 0)
        group["render_time_sec"] += float(row["render_time_sec"] or 0)
        group["operator_seconds"] += float(row["operator_seconds"] or 0)
    groups = []
    for group in grouped.values():
        total_cost = group["total_cost"]
        groups.append(group | {
            "total_cost": round(total_cost, 4),
            "winner_score": round(group["winner_score"], 2),
            "winner_score_per_cost": round(group["winner_score"] / total_cost, 4) if total_cost else None,
            "render_time_sec": round(group["render_time_sec"], 2),
            "operator_seconds": round(group["operator_seconds"], 2),
        })
    groups.sort(key=lambda row: (row["winner_score_per_cost"] is not None, row["winner_score_per_cost"] or 0), reverse=True)
    return {"assets": assets, "by_entity_type": groups}


def experiment_report(root: Path, name: str | None = None) -> dict[str, Any]:
    conn = connect(root)
    where = ""
    params: list[Any] = []
    if name:
        where = "WHERE e.name=?"
        params.append(name)
    rows = conn.execute(
        f"""
        SELECT e.name, a.group_name, a.output_path, a.asset_generation_id,
               o.views, o.likes, o.comments, o.shares, o.saves, o.manual_score,
               c.estimated_generation_cost
        FROM experiment_assignments a
        JOIN experiments e ON e.experiment_id = a.experiment_id
        LEFT JOIN reel_outcomes o
          ON (a.output_path IS NOT NULL AND (o.output_path = a.output_path OR o.filename = substr(a.output_path, length(a.output_path) - length(o.filename) + 1)))
          OR (a.asset_generation_id IS NOT NULL AND o.asset_generation_id = a.asset_generation_id)
        LEFT JOIN cost_events c
          ON (a.output_path IS NOT NULL AND c.output_path = a.output_path)
          OR (a.asset_generation_id IS NOT NULL AND c.asset_generation_id = a.asset_generation_id)
        {where}
        """,
        params,
    ).fetchall()
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["name"], row["group_name"])
        group = groups.setdefault(key, {
            "experiment": row["name"],
            "name": row["group_name"],
            "count": 0,
            "winner_score": 0.0,
            "cost": 0.0,
        })
        group["count"] += 1
        group["winner_score"] += winner_score(row)
        group["cost"] += float(row["estimated_generation_cost"] or 0)
    out = []
    for group in groups.values():
        count = group["count"] or 1
        cost = group["cost"]
        out.append(group | {
            "avg_winner_score": round(group["winner_score"] / count, 2),
            "cost": round(cost, 4),
            "winner_score_per_cost": round(group["winner_score"] / cost, 4) if cost else None,
        })
    out.sort(key=lambda row: (row["winner_score_per_cost"] is not None, row["winner_score_per_cost"] or 0, row["avg_winner_score"]), reverse=True)
    by_avg = sorted(out, key=lambda row: row["avg_winner_score"], reverse=True)
    by_roi = sorted(out, key=lambda row: (row["winner_score_per_cost"] is not None, row["winner_score_per_cost"] or 0), reverse=True)
    return {
        "groups": out,
        "winner_by_avg_score": by_avg[0] if by_avg else None,
        "winner_by_roi": by_roi[0] if by_roi else None,
    }


def _experiment_outcome_rows(conn: sqlite3.Connection, name: str | None = None) -> list[sqlite3.Row]:
    where = ""
    params: list[Any] = []
    if name:
        where = "WHERE e.name=?"
        params.append(name)
    return conn.execute(
        f"""
        SELECT e.name AS experiment, a.group_name, a.output_path, a.asset_generation_id,
               o.filename, o.platform, o.account, o.posted_at,
               o.views, o.likes, o.comments, o.shares, o.saves, o.manual_score
        FROM experiment_assignments a
        JOIN experiments e ON e.experiment_id = a.experiment_id
        LEFT JOIN reel_outcomes o
          ON (a.output_path IS NOT NULL AND (o.output_path = a.output_path OR o.filename = substr(a.output_path, length(a.output_path) - length(o.filename) + 1)))
          OR (a.asset_generation_id IS NOT NULL AND o.asset_generation_id = a.asset_generation_id)
        {where}
        """,
        params,
    ).fetchall()


def baseline_vs_recommended_report(root: Path, *, experiment: str = "baseline_vs_recommended") -> dict[str, Any]:
    conn = connect(root)
    rows = _experiment_outcome_rows(conn, experiment)
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row["group_name"], {
            "name": row["group_name"],
            "assigned_count": 0,
            "outcome_count": 0,
            "scores": [],
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "saves": 0,
        })
        group["assigned_count"] += 1
        if row["filename"]:
            group["outcome_count"] += 1
            group["scores"].append(winner_score(row))
            for key in ("views", "likes", "comments", "shares", "saves"):
                group[key] += int(row[key] or 0)

    group_counts = [int(group["outcome_count"]) for group in groups.values()]
    quality = data_quality_from_connection(
        conn,
        matched_sample_size=sum(group_counts),
        experiment_group_counts=group_counts,
    )
    out_groups = []
    for group in groups.values():
        scores = group.pop("scores")
        count = len(scores)
        out_groups.append(group | {
            "avg_winner_score": round(sum(scores) / count, 2) if count else 0.0,
            "median_winner_score": round(statistics.median(scores), 2) if count else 0.0,
            "confidence": confidence_for_sample_size(count, total_outcomes=sum(group_counts)),
        })
    out_groups.sort(key=lambda item: item["avg_winner_score"], reverse=True)
    by_name = {row["name"]: row for row in out_groups}
    manual = by_name.get("manual")
    recommended = by_name.get("recommended")
    lift = None
    if manual and recommended and manual["avg_winner_score"]:
        lift = round(((recommended["avg_winner_score"] - manual["avg_winner_score"]) / manual["avg_winner_score"]) * 100, 2)
    return {
        "schema": "reel_factory.baseline_vs_recommended.v1",
        "experiment": experiment,
        "groups": out_groups,
        "manual": manual,
        "recommended": recommended,
        "lift_percent": lift,
        "winner": out_groups[0] if out_groups else None,
        "confidence": confidence_for_sample_size(min(group_counts) if group_counts else 0, total_outcomes=sum(group_counts)),
        "data_quality": quality,
    }


def account_fatigue_report(root: Path, *, account: str, window: int = 30) -> dict[str, Any]:
    conn = connect(root)
    rows = conn.execute(
        """
        SELECT o.filename, o.output_path, o.posted_at, f.scene, f.pose, f.motion,
               f.outfit, f.hook_type, f.caption_style, f.creator
        FROM reel_outcomes o
        LEFT JOIN reel_features f
          ON f.output_path = o.output_path OR o.filename = substr(f.output_path, length(f.output_path) - length(o.filename) + 1)
        WHERE o.account=?
        ORDER BY COALESCE(o.posted_at, '') DESC, o.imported_at DESC
        LIMIT ?
        """,
        (account, window),
    ).fetchall()
    feature_keys = ("scene", "pose", "motion", "outfit", "hook_type", "caption_style")
    repeated: list[dict[str, Any]] = []
    for key in feature_keys:
        counts: dict[str, int] = {}
        for row in rows:
            value = row[key]
            if value and value != "unknown":
                counts[str(value)] = counts.get(str(value), 0) + 1
        for value, count in counts.items():
            if count >= 2:
                repeated.append({"feature_key": key, "feature_value": value, "count": count})
    combo_counts: dict[str, int] = {}
    for row in rows:
        if row["creator"] and row["scene"] and row["creator"] != "unknown" and row["scene"] != "unknown":
            combo = f"{row['creator']} / {row['scene']}"
            combo_counts[combo] = combo_counts.get(combo, 0) + 1
    for value, count in combo_counts.items():
        if count >= 2:
            repeated.append({"feature_key": "creator_scene", "feature_value": value, "count": count})
    repeated.sort(key=lambda row: row["count"], reverse=True)
    max_repeat = repeated[0]["count"] if repeated else 0
    total = len(rows)
    ratio = (max_repeat / total) if total else 0
    if total >= 5 and ratio >= 0.6:
        level = "high"
    elif total >= 3 and ratio >= 0.4:
        level = "medium"
    else:
        level = "low"
    targets = [
        f"vary {row['feature_key']} away from {row['feature_value']}"
        for row in repeated[:5]
    ]
    return {
        "schema": "reel_factory.account_fatigue.v1",
        "account": account,
        "window": window,
        "outcome_count": total,
        "level": level,
        "score": round(ratio * 100, 2),
        "repeated_pattern_count": len(repeated),
        "overused_patterns": repeated[:10],
        "suggested_variation_targets": targets,
    }


def persist_recommendation_decision(
    root: Path,
    *,
    campaign: str,
    plan: dict[str, Any],
    rejection_patterns: list[dict[str, Any]] | None = None,
) -> str | None:
    ideas = plan.get("ideas") or []
    if not ideas:
        return None
    first = ideas[0]
    rec = first.get("recommendation") or {}
    decision_id = f"decision_{time.time_ns()}"
    data_quality = rec.get("data_quality") or first.get("data_quality") or {}
    conn = connect(root)
    conn.execute(
        """
        INSERT INTO recommendation_decisions (
            decision_id, campaign, recommendation_pattern, prompt_focus,
            avoid_labels_json, confidence, confidence_reason, winner_dna_json,
            rejection_patterns_json, data_quality_json, plan_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            campaign,
            rec.get("pattern", ""),
            first.get("prompt_focus"),
            json_dumps(first.get("avoid_labels") or []),
            rec.get("confidence") or first.get("confidence"),
            rec.get("confidence_reason"),
            json_dumps(first.get("winner_dna_focus") or []),
            json_dumps(rejection_patterns or []),
            json_dumps(data_quality),
            json_dumps(plan),
            int(time.time()),
        ),
    )
    conn.commit()
    return decision_id


def decision_log(root: Path, *, campaign: str | None = None, limit: int = 50) -> dict[str, Any]:
    conn = connect(root)
    where = ""
    params: list[Any] = []
    if campaign:
        where = "WHERE campaign=?"
        params.append(campaign)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM recommendation_decisions
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    decisions = []
    for row in rows:
        item = dict(row)
        for key in ("avoid_labels_json", "winner_dna_json", "rejection_patterns_json", "data_quality_json", "plan_json"):
            try:
                item[key.replace("_json", "")] = json.loads(item[key] or "{}")
            except json.JSONDecodeError:
                item[key.replace("_json", "")] = None
        decisions.append(item)
    return {"schema": "reel_factory.recommendation_decisions.v1", "decisions": decisions}


def refresh_winner_dna(root: Path) -> dict[str, Any]:
    refresh_features(root)
    conn = connect(root)
    rows = conn.execute(
        """
        SELECT f.*, o.views, o.likes, o.comments, o.shares, o.saves, o.manual_score
        FROM reel_features f
        JOIN reel_outcomes o ON o.output_path = f.output_path OR o.filename = substr(f.output_path, length(f.output_path) - length(o.filename) + 1)
        """
    ).fetchall()
    buckets: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for row in rows:
        score = winner_score(row)
        for key in FEATURE_KEYS:
            value = row[key]
            if value and value != "unknown":
                buckets.setdefault((key, str(value)), []).append((score, row["output_path"]))
    now = int(time.time())
    conn.execute("DELETE FROM winner_dna")
    for (key, value), samples in buckets.items():
        samples.sort(reverse=True)
        avg = sum(s for s, _ in samples) / len(samples)
        dna_id = f"dna_{key}_{value}".replace(" ", "_")
        conn.execute(
            """
            INSERT INTO winner_dna (
                dna_id, feature_key, feature_value, sample_size, avg_winner_score,
                top_output_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dna_id, key, value, len(samples), round(avg, 2), samples[0][1], now),
        )
    conn.commit()
    return {"ok": True, "rows": len(buckets)}


def winner_dna_leaderboard(root: Path, limit: int = 50) -> dict[str, Any]:
    conn = connect(root)
    total_outcomes = int(conn.execute("SELECT COUNT(*) AS n FROM reel_outcomes").fetchone()["n"] or 0)
    rows = conn.execute(
        "SELECT * FROM winner_dna ORDER BY avg_winner_score DESC, sample_size DESC LIMIT ?",
        (limit,),
    ).fetchall()
    rejection_rows = conn.execute(
        """
        SELECT primary_reason AS label, COUNT(*) AS count
        FROM operator_ratings
        WHERE primary_reason IS NOT NULL AND decision IN ('reject','maybe')
        GROUP BY primary_reason
        ORDER BY count DESC
        LIMIT 20
        """
    ).fetchall()
    def top_for(key: str) -> list[dict[str, Any]]:
        return [
            dict(row) | {"confidence": confidence_for_sample_size(row["sample_size"], total_outcomes=total_outcomes)}
            for row in conn.execute(
                """
                SELECT * FROM winner_dna
                WHERE feature_key=?
                ORDER BY avg_winner_score DESC, sample_size DESC
                LIMIT ?
                """,
                (key, limit),
            ).fetchall()
        ]
    combo_rows = conn.execute(
        """
        SELECT creator, scene, COUNT(*) AS sample_size, AVG(score) AS avg_winner_score
        FROM (
            SELECT f.creator, f.scene, o.views, o.likes, o.comments, o.shares, o.saves, o.manual_score,
                   CASE
                     WHEN o.manual_score IS NOT NULL THEN o.manual_score
                     ELSE (COALESCE(o.views,0) + COALESCE(o.likes,0) * 3 + COALESCE(o.comments,0) * 8 + COALESCE(o.shares,0) * 15 + COALESCE(o.saves,0) * 12)
                   END AS score
            FROM reel_features f
            JOIN reel_outcomes o ON o.output_path = f.output_path OR o.filename = substr(f.output_path, length(f.output_path) - length(o.filename) + 1)
            WHERE f.creator IS NOT NULL AND f.creator != 'unknown' AND f.scene IS NOT NULL AND f.scene != 'unknown'
        )
        GROUP BY creator, scene
        ORDER BY avg_winner_score DESC, sample_size DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    costs = cost_analytics(root)
    matched_sample_size = int(rows[0]["sample_size"] or 0) if rows else 0
    quality = data_quality_from_connection(conn, matched_sample_size=matched_sample_size)
    return {
        "total_outcomes": total_outcomes,
        "low_data_warning": low_data_warning(total_outcomes),
        "data_quality": quality,
        "winner_dna": [
            dict(row) | {"confidence": confidence_for_sample_size(row["sample_size"], total_outcomes=total_outcomes)}
            for row in rows
        ],
        "top_scenes": top_for("scene"),
        "top_poses": top_for("pose"),
        "top_motions": top_for("motion"),
        "top_outfits": top_for("outfit"),
        "best_creator_scene_combinations": [dict(row) for row in combo_rows],
        "worst_rejection_patterns": [dict(row) for row in rejection_rows],
        "costs": costs["by_entity_type"],
        "best_roi_assets": costs["assets"][:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    sub.add_parser("leaderboard")
    feat = sub.add_parser("features")
    feat.add_argument("--limit", type=int)
    assign = sub.add_parser("assign-experiment")
    assign.add_argument("--name", required=True)
    assign.add_argument("--group", required=True)
    assign.add_argument("--output-path")
    assign.add_argument("--asset-generation-id")
    assign.add_argument("--hypothesis", default="")
    record = sub.add_parser("record-cost")
    record.add_argument("--entity-type", default="final_reel")
    record.add_argument("--entity-id")
    record.add_argument("--output-path")
    record.add_argument("--asset-generation-id")
    record.add_argument("--soul-jobs", type=int, default=0)
    record.add_argument("--kling-jobs", type=int, default=0)
    record.add_argument("--estimated-generation-cost", type=float)
    record.add_argument("--render-time-sec", type=float)
    record.add_argument("--operator-seconds", type=float)
    record.add_argument("--notes", default="")
    cost = sub.add_parser("costs")
    cost.add_argument("--limit", type=int, default=20)
    exp = sub.add_parser("experiment-report")
    exp.add_argument("--name")
    baseline = sub.add_parser("baseline-report")
    baseline.add_argument("--experiment", default="baseline_vs_recommended")
    fatigue = sub.add_parser("account-fatigue")
    fatigue.add_argument("--account", required=True)
    fatigue.add_argument("--window", type=int, default=30)
    decisions = sub.add_parser("decision-log")
    decisions.add_argument("--campaign")
    decisions.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    root = Path(args.root)
    if args.cmd == "refresh":
        result = refresh_winner_dna(root)
    elif args.cmd == "leaderboard":
        result = winner_dna_leaderboard(root)
    elif args.cmd == "features":
        result = refresh_features(root, limit=args.limit)
    elif args.cmd == "costs":
        result = cost_analytics(root)
        result["assets"] = result["assets"][:args.limit]
    elif args.cmd == "experiment-report":
        result = experiment_report(root, args.name)
    elif args.cmd == "baseline-report":
        result = baseline_vs_recommended_report(root, experiment=args.experiment)
    elif args.cmd == "account-fatigue":
        result = account_fatigue_report(root, account=args.account, window=args.window)
    elif args.cmd == "decision-log":
        result = decision_log(root, campaign=args.campaign, limit=args.limit)
    elif args.cmd == "record-cost":
        result = record_cost(
            root,
            entity_type=args.entity_type,
            entity_id=args.entity_id,
            output_path=args.output_path,
            asset_generation_id=args.asset_generation_id,
            soul_jobs=args.soul_jobs,
            kling_jobs=args.kling_jobs,
            estimated_generation_cost=args.estimated_generation_cost,
            render_time_sec=args.render_time_sec,
            operator_seconds=args.operator_seconds,
            notes=args.notes,
        )
    else:
        result = assign_experiment(
            root,
            name=args.name,
            group=args.group,
            output_path=args.output_path,
            asset_generation_id=args.asset_generation_id,
            hypothesis=args.hypothesis,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
