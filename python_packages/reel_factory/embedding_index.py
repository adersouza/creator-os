#!/usr/bin/env python3
"""Index and search Reel Factory media/text embeddings."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from embedding_provider import HASH_MODEL, cosine_similarity, get_embedding_provider
from intelligence_store import ensure_intelligence_schema


def connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(root) / "manifest.sqlite")
    conn.row_factory = sqlite3.Row
    ensure_intelligence_schema(conn)
    return conn


def text_for_path(path: Path, root: Path | None = None) -> str:
    parts = [path.stem.replace("_", " ")]
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            parts.append(json.dumps(data, ensure_ascii=False)[:4000])
        except Exception:
            pass
    sidecar = path.with_suffix(path.suffix + ".generated_asset_lineage.json")
    if sidecar.exists():
        try:
            parts.append(
                json.dumps(
                    json.loads(sidecar.read_text(encoding="utf-8")), ensure_ascii=False
                )[:4000]
            )
        except Exception:
            pass
    if root:
        db = Path(root) / "manifest.sqlite"
        if db.exists():
            try:
                conn = connect(Path(root))
                feature = conn.execute(
                    "SELECT * FROM reel_features WHERE output_path=? LIMIT 1",
                    (str(path.resolve()),),
                ).fetchone()
                if feature:
                    parts.append(
                        "reel_features "
                        + json.dumps(dict(feature), ensure_ascii=False)[:4000]
                    )
                outcome = conn.execute(
                    """
                    SELECT filename, views, likes, comments, shares, saves, manual_score, notes
                    FROM reel_outcomes
                    WHERE output_path=? OR filename=?
                    LIMIT 1
                    """,
                    (str(path.resolve()), path.name),
                ).fetchone()
                if outcome:
                    parts.append(
                        "reel_outcome "
                        + json.dumps(dict(outcome), ensure_ascii=False)[:1000]
                    )
            except Exception:
                pass
    return "\n".join(parts)


def entity_type_for(path: Path) -> str:
    s = str(path)
    if "/prompts/" in s or path.parent.name == "prompts":
        return "prompt"
    if "/00_source_videos/" in s:
        return "source_or_panel"
    if "/02_processed/" in s:
        return "final_reel"
    if "generated_assets" in s and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return "generated_image"
    if "generated_assets" in s and path.suffix.lower() in {".mp4", ".mov"}:
        return "animated_grid"
    return "media"


def upsert_embedding(
    root: Path,
    path: Path,
    *,
    model: str = HASH_MODEL,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    path = Path(path).expanduser().resolve()
    provider = get_embedding_provider(model)
    text = text_for_path(path, root)
    vec = provider.embed(text)
    conn = connect(root)
    entity_type = entity_type or entity_type_for(path)
    entity_id = entity_id or path.stem
    embedding_id = f"emb_{entity_type}_{entity_id}_{provider.name}".replace("/", "_")
    conn.execute(
        """
        INSERT OR REPLACE INTO media_embeddings (
            embedding_id, entity_type, entity_id, path, model, vector_json, text_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            embedding_id,
            entity_type,
            entity_id,
            str(path),
            provider.name,
            json.dumps(vec),
            json.dumps({"text": text[:4000]}, ensure_ascii=False),
            int(time.time()),
        ),
    )
    conn.commit()
    return {
        "embedding_id": embedding_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "path": str(path),
        "model": provider.name,
    }


def index_root(
    root: Path, *, model: str = HASH_MODEL, limit: int | None = None
) -> dict[str, Any]:
    root = Path(root).resolve()
    candidates: list[Path] = []
    for base, patterns in [
        (root / "prompts", ["*.json"]),
        (root / "00_source_videos", ["*.mp4"]),
        (root / "project_data" / "generated_assets", ["*.png", "*.jpg", "*.mp4"]),
        (root / "02_processed", ["*.mp4"]),
        (root / "02_processed_fit", ["*.mp4"]),
    ]:
        if not base.exists():
            continue
        for pattern in patterns:
            candidates.extend(base.rglob(pattern))
    if limit:
        candidates = candidates[:limit]
    rows = [upsert_embedding(root, p, model=model) for p in candidates if p.is_file()]
    return {
        "ok": True,
        "indexed": len(rows),
        "model": rows[0]["model"] if rows else model,
    }


def similar(
    root: Path, path: Path, *, model: str = HASH_MODEL, limit: int = 10
) -> dict[str, Any]:
    root = Path(root).resolve()
    path = Path(path).expanduser().resolve()
    target = upsert_embedding(root, path, model=model)
    conn = connect(root)
    row = conn.execute(
        "SELECT vector_json FROM media_embeddings WHERE embedding_id=?",
        (target["embedding_id"],),
    ).fetchone()
    target_vec = json.loads(row["vector_json"])
    results = []
    for candidate in conn.execute(
        "SELECT * FROM media_embeddings WHERE embedding_id != ?",
        (target["embedding_id"],),
    ):
        if candidate["path"] and Path(candidate["path"]).resolve() == path:
            continue
        score = cosine_similarity(target_vec, json.loads(candidate["vector_json"]))
        results.append(
            {
                "score": round(score, 4),
                "entity_type": candidate["entity_type"],
                "entity_id": candidate["entity_id"],
                "path": candidate["path"],
                "model": candidate["model"],
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"ok": True, "query": str(path), "results": results[:limit]}


def _strongest_sidecar_similarity(path: Path) -> dict[str, Any] | None:
    sim_path = path.parent / "_similarity.json"
    if not sim_path.exists():
        return None
    try:
        payload = json.loads(sim_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("records") or payload.get("results") or []
    else:
        rows = []
    best = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("filename") not in {path.name, str(path)} and row.get(
            "variant"
        ) not in {path.name, str(path)}:
            continue
        score = row.get("max_similarity") or row.get("similarity") or row.get("score")
        if score is None:
            continue
        candidate = {"score": float(score), "source": "similarity_sidecar", "raw": row}
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def duplicate_risk(
    root: Path,
    path: Path,
    *,
    account: str,
    platform: str | None = None,
    model: str = HASH_MODEL,
    limit: int = 20,
) -> dict[str, Any]:
    root = Path(root).resolve()
    path = Path(path).expanduser().resolve()
    target = upsert_embedding(root, path, model=model)
    conn = connect(root)
    row = conn.execute(
        "SELECT vector_json FROM media_embeddings WHERE embedding_id=?",
        (target["embedding_id"],),
    ).fetchone()
    target_vec = json.loads(row["vector_json"])
    params: list[Any] = [account]
    platform_filter = ""
    if platform:
        platform_filter = "AND platform=?"
        params.append(platform)
    outcomes = conn.execute(
        f"""
        SELECT filename, output_path, platform, account, posted_at
        FROM reel_outcomes
        WHERE account=? {platform_filter}
        ORDER BY COALESCE(posted_at, '') DESC, imported_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    candidates = []
    for outcome in outcomes:
        candidate_path = outcome["output_path"]
        if not candidate_path:
            matches = list((root / "02_processed").rglob(str(outcome["filename"])))
            candidate_path = str(matches[0]) if matches else ""
        if not candidate_path:
            continue
        try:
            resolved = Path(candidate_path).expanduser().resolve()
        except Exception:
            continue
        if resolved == path:
            continue
        emb = conn.execute(
            """
            SELECT * FROM media_embeddings
            WHERE path=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(resolved),),
        ).fetchone()
        if not emb and resolved.exists():
            upsert_embedding(root, resolved, model=model)
            emb = conn.execute(
                "SELECT * FROM media_embeddings WHERE path=? ORDER BY created_at DESC LIMIT 1",
                (str(resolved),),
            ).fetchone()
        if not emb:
            continue
        score = cosine_similarity(target_vec, json.loads(emb["vector_json"]))
        candidates.append(
            {
                "score": round(score, 4),
                "path": str(resolved),
                "filename": outcome["filename"],
                "platform": outcome["platform"],
                "account": outcome["account"],
                "posted_at": outcome["posted_at"],
                "model": emb["model"],
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    nearest = candidates[0] if candidates else None
    sidecar = _strongest_sidecar_similarity(path)
    score = float(nearest["score"]) if nearest else 0.0
    model_used = nearest["model"] if nearest else target["model"]
    if sidecar and sidecar["score"] > score:
        score = float(sidecar["score"])
        model_used = sidecar["source"]
    if score >= 0.92:
        action = "avoid"
        level = "high"
    elif score >= 0.78:
        action = "review"
        level = "medium"
    else:
        action = "safe"
        level = "low"
    reason = "no prior posted neighbors found"
    if nearest:
        reason = f"nearest prior post scored {nearest['score']} similarity"
    if sidecar and sidecar["score"] >= score:
        reason = f"sidecar similarity scored {sidecar['score']}"
    return {
        "schema": "reel_factory.duplicate_risk.v1",
        "query": str(path),
        "account": account,
        "platform": platform,
        "risk_score": round(score, 4),
        "risk_level": level,
        "recommended_action": action,
        "nearest_prior_output": nearest,
        "model": model_used,
        "reason": reason,
        "candidates": candidates[:limit],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    idx = sub.add_parser("index")
    idx.add_argument("--model", default=HASH_MODEL)
    idx.add_argument("--limit", type=int)
    sim = sub.add_parser("similar")
    sim.add_argument("--path", required=True)
    sim.add_argument("--model", default=HASH_MODEL)
    sim.add_argument("--limit", type=int, default=10)
    dup = sub.add_parser("duplicate-risk")
    dup.add_argument("--path", required=True)
    dup.add_argument("--account", required=True)
    dup.add_argument("--platform")
    dup.add_argument("--model", default=HASH_MODEL)
    dup.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    if args.cmd == "index":
        result = index_root(Path(args.root), model=args.model, limit=args.limit)
    elif args.cmd == "similar":
        result = similar(
            Path(args.root), Path(args.path), model=args.model, limit=args.limit
        )
    else:
        result = duplicate_risk(
            Path(args.root),
            Path(args.path),
            account=args.account,
            platform=args.platform,
            model=args.model,
            limit=args.limit,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
