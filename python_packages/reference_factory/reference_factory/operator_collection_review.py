from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from creator_os_core.fileops import atomic_write_text
from fastapi import HTTPException

from pipeline_contracts import (
    operator_preference_profile_fingerprint,
    validate_operator_preference_profile,
)

from .timeutil import now_iso


def require_collection_dir(data_root: Path, collection_id: str) -> Path:
    if (
        not collection_id
        or Path(collection_id).name != collection_id
        or collection_id in {".", ".."}
    ):
        raise HTTPException(status_code=404, detail="Operator collection not found")
    root = (data_root / "operator_collections").resolve()
    collection_dir = (root / collection_id).resolve()
    if collection_dir.parent != root or not collection_dir.is_dir():
        raise HTTPException(status_code=404, detail="Operator collection not found")
    return collection_dir


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid operator collection file: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=500, detail=f"Invalid operator collection file: {path.name}"
        )
    return value


def _item_id(kind: str, key: str) -> str:
    if kind in {"reel", "selfie"}:
        return f"{kind}:{key}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _profile_handle(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[0].lstrip("@") if parts else "profile"


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _local_reel_path(data_root: Path, shortcode: str) -> Path | None:
    if Path(shortcode).name != shortcode or shortcode in {".", ".."}:
        return None
    path = data_root / "url_intake" / "instagram" / shortcode / "reference.mp4"
    return path if path.is_file() else None


def operator_collection_payload(
    data_root: Path, collection_id: str
) -> dict[str, object]:
    collection_dir = require_collection_dir(data_root, collection_id)
    notes = _load_json_object(collection_dir / "operator_notes.json")
    manifest = _load_json_object(collection_dir / "manifest.json")
    ratings_path = collection_dir / "operator_ratings.json"
    ratings_document = (
        _load_json_object(ratings_path) if ratings_path.exists() else {"ratings": {}}
    )
    ratings = ratings_document.get("ratings")
    if not isinstance(ratings, dict):
        raise HTTPException(status_code=500, detail="Invalid operator ratings file")

    items: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for entry in _dict_list(notes.get("reelNotes")):
        shortcode = str(entry.get("shortcode") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not shortcode or not url:
            continue
        item_id = _item_id("reel", shortcode)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        local_reel = _local_reel_path(data_root, shortcode)
        items.append(
            {
                "itemId": item_id,
                "kind": "reel",
                "title": shortcode,
                "url": url,
                "recommendation": str(entry.get("recommendation") or ""),
                "mediaUrl": (
                    f"/api/operator-collections/{quote(collection_id)}/reels/"
                    f"{quote(shortcode)}/media"
                    if local_reel
                    else None
                ),
                "rating": ratings.get(item_id),
            }
        )

    profile_sources = {
        str(entry.get("url")): entry
        for entry in _dict_list(manifest.get("profileSources"))
        if entry.get("url")
    }
    for entry in _dict_list(notes.get("profileNotes")):
        url = str(entry.get("url") or "").strip()
        if not url:
            continue
        item_id = _item_id("profile", url)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        handle = _profile_handle(url)
        mosaic_relative = f"profile_samples/visual_review/{handle}__review_mosaic.jpg"
        source = profile_sources.get(url, {})
        focus = source.get("focus", []) if isinstance(source, dict) else []
        items.append(
            {
                "itemId": item_id,
                "kind": "profile",
                "title": f"@{handle}",
                "url": url,
                "recommendation": str(entry.get("recommendation") or ""),
                "focus": focus if isinstance(focus, list) else [],
                "mediaUrl": (
                    f"/api/operator-collections/{quote(collection_id)}/media/"
                    f"{quote(mosaic_relative)}"
                    if (collection_dir / mosaic_relative).is_file()
                    else None
                ),
                "rating": ratings.get(item_id),
            }
        )

    image_notes = notes.get("imageNotes")
    recipes = _dict_list(
        image_notes.get("shotRecipes") if isinstance(image_notes, dict) else None
    )
    recipe_by_asset = {
        str(recipe.get("asset")): recipe for recipe in recipes if recipe.get("asset")
    }
    for entry in _dict_list(manifest.get("items")):
        relative = str(entry.get("path") or "")
        relative_path = Path(relative)
        if relative_path.parent.as_posix() != "selfies":
            continue
        key = relative_path.stem
        item_id = _item_id("selfie", key)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        recipe = recipe_by_asset.get(relative, {})
        must_preserve = (
            recipe.get("mustPreserve", []) if isinstance(recipe, dict) else []
        )
        items.append(
            {
                "itemId": item_id,
                "kind": "selfie",
                "title": str(recipe.get("name") or key),
                "url": None,
                "recommendation": str(
                    recipe.get("pose") or "Pose and framing reference"
                ),
                "mustPreserve": must_preserve
                if isinstance(must_preserve, list)
                else [],
                "mediaUrl": (
                    f"/api/operator-collections/{quote(collection_id)}/media/"
                    f"{quote(relative)}"
                ),
                "sha256": entry.get("sha256"),
                "rating": ratings.get(item_id),
            }
        )

    rated_scores = [
        int(rating["score"])
        for rating in ratings.values()
        if isinstance(rating, dict) and isinstance(rating.get("score"), int)
    ]
    return {
        "schema": "reference_factory.operator_collection_review.v1",
        "collectionId": collection_id,
        "items": items,
        "summary": {
            "total": len(items),
            "rated": len(rated_scores),
            "remaining": len(items) - len(rated_scores),
            "average": round(sum(rated_scores) / len(rated_scores), 2)
            if rated_scores
            else None,
            "byKind": {
                kind: sum(1 for item in items if item["kind"] == kind)
                for kind in ("reel", "profile", "selfie")
            },
        },
    }


def operator_collection_reel_media_path(
    data_root: Path, collection_id: str, shortcode: str
) -> Path:
    collection = operator_collection_payload(data_root, collection_id)
    reel_ids = {
        str(item.get("itemId"))
        for item in _dict_list(collection.get("items"))
        if item.get("kind") == "reel"
    }
    path = _local_reel_path(data_root, shortcode)
    if f"reel:{shortcode}" not in reel_ids or path is None:
        raise HTTPException(status_code=404, detail="Collection Reel media not found")
    return path


def build_operator_preference_profile(
    data_root: Path, collection_id: str
) -> dict[str, object]:
    collection_dir = require_collection_dir(data_root, collection_id)
    collection = operator_collection_payload(data_root, collection_id)
    operator_notes = _load_json_object(collection_dir / "operator_notes.json")
    summary_value = collection.get("summary")
    if not isinstance(summary_value, dict):
        raise HTTPException(
            status_code=500, detail="Invalid operator collection summary"
        )
    summary: dict[str, object] = dict(summary_value)
    items: list[dict[str, Any]] = []
    by_score = {str(score): 0 for score in range(1, 6)}
    for item in _dict_list(collection.get("items")):
        rating = item.get("rating")
        if not isinstance(rating, dict) or not isinstance(rating.get("score"), int):
            continue
        score = int(rating["score"])
        by_score[str(score)] += 1
        items.append(
            {
                "itemId": str(item["itemId"]),
                "kind": str(item["kind"]),
                "title": str(item["title"]),
                "score": score,
                "operatorNotes": str(rating.get("notes") or ""),
                "recommendation": str(item.get("recommendation") or ""),
                "updatedAt": str(rating["updatedAt"]),
            }
        )
    house_direction_value = operator_notes.get("houseDirection")
    house_direction: dict[str, object] = (
        dict(house_direction_value) if isinstance(house_direction_value, dict) else {}
    )
    principles: list[str] = []
    principle_values: list[object] = [
        house_direction.get("audienceGoal"),
        house_direction.get("audioDirection"),
        house_direction.get("identityDirection"),
    ]
    for key in ("visualPriorities", "editingPriorities"):
        values = house_direction.get(key)
        if isinstance(values, list):
            principle_values.extend(values)
    for value in principle_values:
        text = str(value or "").strip()
        if text and text not in principles:
            principles.append(text)
    summary["byScore"] = by_score
    total = summary.get("total")
    remaining = summary.get("remaining")
    core: dict[str, object] = {
        "collectionId": collection_id,
        "status": (
            "active"
            if isinstance(total, int)
            and total > 0
            and isinstance(remaining, int)
            and remaining == 0
            else "incomplete"
        ),
        "summary": summary,
        "houseDirection": house_direction,
        "brief": {
            "principles": principles,
            "masterItemIds": [item["itemId"] for item in items if item["score"] == 5],
            "strongItemIds": [item["itemId"] for item in items if item["score"] == 4],
            "usefulItemIds": [item["itemId"] for item in items if item["score"] == 3],
            "avoidItemIds": [item["itemId"] for item in items if item["score"] <= 2],
        },
        "items": items,
    }
    profile: dict[str, object] = {
        "schema": "reference_factory.operator_preference_profile.v1",
        **core,
        "generatedAt": now_iso(),
        "sourceFingerprint": operator_preference_profile_fingerprint(core),
    }
    validate_operator_preference_profile(profile)
    return profile


def write_operator_preference_profile(
    data_root: Path, collection_id: str
) -> dict[str, object]:
    profile = build_operator_preference_profile(data_root, collection_id)
    text = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    collection_path = (
        require_collection_dir(data_root, collection_id)
        / "operator_preference_profile.json"
    )
    stable_path = data_root / "learning" / "operator_preference_profile.json"
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(collection_path, text)
    atomic_write_text(stable_path, text)
    return profile


def set_operator_collection_rating(
    data_root: Path,
    collection_id: str,
    item_id: str,
    score: int | None,
    notes: str | None,
) -> dict[str, object]:
    collection_dir = require_collection_dir(data_root, collection_id)
    collection = operator_collection_payload(data_root, collection_id)
    collection_items = _dict_list(collection.get("items"))
    if item_id not in {item["itemId"] for item in collection_items}:
        raise HTTPException(status_code=404, detail="Collection item not found")

    ratings_path = collection_dir / "operator_ratings.json"
    document = (
        _load_json_object(ratings_path)
        if ratings_path.exists()
        else {
            "schema": "reference_factory.operator_collection_ratings.v1",
            "collectionId": collection_id,
            "ratings": {},
        }
    )
    ratings = document.setdefault("ratings", {})
    if not isinstance(ratings, dict):
        raise HTTPException(status_code=500, detail="Invalid operator ratings file")
    clean_notes = (notes or "").strip()
    if score is None and not clean_notes:
        ratings.pop(item_id, None)
        rating = None
    else:
        rating = {"score": score, "notes": clean_notes, "updatedAt": now_iso()}
        ratings[item_id] = rating
    document["updatedAt"] = now_iso()
    atomic_write_text(
        ratings_path,
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    preference_profile = write_operator_preference_profile(data_root, collection_id)
    return {
        "schema": "reference_factory.operator_collection_rating.v1",
        "collectionId": collection_id,
        "itemId": item_id,
        "rating": rating,
        "summary": operator_collection_payload(data_root, collection_id)["summary"],
        "preferenceProfile": {
            "status": preference_profile["status"],
            "sourceFingerprint": preference_profile["sourceFingerprint"],
        },
    }
