from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .config import CONTENTFORGE_APPLE_VISION_SCRIPT, DEFAULT_DATA_ROOT
from .db import json_dump
from .identity import stable_id, text_hash
from .timeutil import now_iso


VALID_ENGINES = {"auto", "apple_vision", "tesseract", "heuristic"}


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text


def parse_tesseract_tsv(tsv_text: str, frame_path: Path) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    reader = csv.DictReader(tsv_text.splitlines(), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or 0)
        except ValueError:
            confidence = 0
        if confidence < 20:
            continue
        try:
            x = int(float(row.get("left") or 0))
            y = int(float(row.get("top") or 0))
            w = int(float(row.get("width") or 0))
            h = int(float(row.get("height") or 0))
        except ValueError:
            continue
        boxes.append(
            {
                "ocrText": text,
                "confidence": confidence,
                "box": {"x": x, "y": y, "w": w, "h": h},
                "framePath": str(frame_path),
            }
        )
    return boxes


def run_tesseract(frame_path: Path) -> dict[str, Any]:
    version = first_line(["tesseract", "--version"])
    variants = [("original", frame_path)]
    with tempfile.TemporaryDirectory(prefix="reference-factory-ocr-") as tmp:
        tmp_path = Path(tmp)
        enhanced = tmp_path / "enhanced.png"
        threshold = tmp_path / "threshold.png"
        make_variant(frame_path, enhanced, "scale=iw*2:ih*2,eq=contrast=1.2:brightness=0.03")
        make_variant(frame_path, threshold, "scale=iw*2:ih*2,format=gray,threshold")
        if enhanced.exists():
            variants.append(("enhanced_2x", enhanced))
        if threshold.exists():
            variants.append(("threshold_2x", threshold))
        all_boxes: list[dict[str, Any]] = []
        errors: list[str] = []
        preprocessing: list[str] = []
        for name, path in variants:
            result = subprocess.run(
                ["tesseract", str(path), "stdout", "--psm", "6", "tsv"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                errors.append(f"{name}: {(result.stderr or '').strip()[:300]}")
                continue
            preprocessing.append(name)
            all_boxes.extend(parse_tesseract_tsv(result.stdout, frame_path))
        if not preprocessing:
            return {
                "available": False,
                "engine": "tesseract",
                "engineVersion": version,
                "error": "; ".join(errors) or "tesseract failed",
                "boxes": [],
            }
        boxes = dedupe_boxes(all_boxes)
        return {
            "available": True,
            "engine": "tesseract",
            "engineVersion": version,
            "preprocessing": preprocessing,
            "boxesBeforeMerge": len(all_boxes),
            "boxes": boxes,
        }


def make_variant(input_path: Path, output_path: Path, vf: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(input_path), "-vf", vf, str(output_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def run_apple_vision(frame_path: Path, script_path: Path = CONTENTFORGE_APPLE_VISION_SCRIPT) -> dict[str, Any]:
    if not script_path.exists():
        return {
            "available": False,
            "engine": "apple_vision",
            "error": f"Apple Vision script not found: {script_path}",
            "boxes": [],
        }
    result = subprocess.run(
        ["swift", str(script_path), str(frame_path)],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    if result.returncode != 0:
        return {
            "available": False,
            "engine": "apple_vision",
            "error": (result.stderr or result.stdout).strip()[:500],
            "boxes": [],
        }
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "engine": "apple_vision",
            "error": f"Apple Vision JSON parse failed: {exc}",
            "boxes": [],
        }
    if parsed.get("available") is False:
        return parsed
    boxes = [
        {
            "ocrText": box.get("ocrText", ""),
            "confidence": float(box.get("confidence") or 0),
            "box": box.get("box") or {"x": 0, "y": 0, "w": 0, "h": 0},
            "framePath": str(frame_path),
        }
        for box in parsed.get("boxes") or []
        if box.get("ocrText")
    ]
    return {
        "available": True,
        "engine": "apple_vision",
        "engineVersion": parsed.get("engineVersion") or "Vision",
        "preprocessing": ["original"],
        "boxesBeforeMerge": len(boxes),
        "boxes": dedupe_boxes(boxes),
    }


def run_selected_ocr(frame_path: Path, requested_engine: str = "auto") -> dict[str, Any]:
    requested_engine = requested_engine.lower()
    if requested_engine not in VALID_ENGINES:
        return {
            "available": False,
            "requestedEngine": requested_engine,
            "engine": None,
            "error": f"Unsupported OCR engine: {requested_engine}",
            "boxes": [],
        }
    if requested_engine == "heuristic":
        return {
            "available": False,
            "requestedEngine": requested_engine,
            "engine": "heuristic",
            "fallbackUsed": True,
            "fallbackReason": "heuristic mode does not run OCR",
            "boxes": [],
        }
    order = ["apple_vision", "tesseract"] if requested_engine == "auto" else [requested_engine]
    errors: list[str] = []
    for idx, engine in enumerate(order):
        result = run_apple_vision(frame_path) if engine == "apple_vision" else run_tesseract(frame_path)
        if result.get("available") is not False:
            result["requestedEngine"] = requested_engine
            result["fallbackUsed"] = idx > 0
            result["fallbackReason"] = "; ".join(errors) if idx > 0 else None
            return result
        errors.append(f"{engine}: {result.get('error') or 'unavailable'}")
    return {
        "available": False,
        "requestedEngine": requested_engine,
        "engine": None,
        "fallbackUsed": len(order) > 1,
        "fallbackReason": "; ".join(errors),
        "error": "; ".join(errors),
        "boxes": [],
    }


def dedupe_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for box in boxes:
        text = normalize_text(str(box.get("ocrText") or ""))
        if not text:
            continue
        geom = box.get("box") or {}
        key = (text.lower(), int(geom.get("x") or 0) // 8, int(geom.get("y") or 0) // 8)
        if key in seen:
            continue
        seen.add(key)
        box = {**box, "ocrText": text}
        merged.append(box)
    return merged


def first_line(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except Exception:  # noqa: BLE001
        return None
    text = result.stdout or result.stderr
    return text.splitlines()[0] if text.splitlines() else None


def run_ocr(
    conn: Connection,
    engine: str = "auto",
    likely_captioned_only: bool = False,
    limit: int | None = None,
    commit_every: int = 25,
    progress_every: int = 25,
) -> dict[str, object]:
    query = """
      SELECT fs.id, fs.reference_id, fs.frame_path, fs.time_sec, fs.role
      FROM frame_samples fs
      JOIN source_files sf ON sf.reference_id = fs.reference_id
      LEFT JOIN ocr_results existing ON existing.frame_sample_id = fs.id AND existing.requested_engine = ?
      WHERE existing.id IS NULL
      ORDER BY sf.account, sf.file_name, fs.time_sec
    """
    rows = conn.execute(query, (engine,)).fetchall()
    if likely_captioned_only:
        rows = [
            row
            for row in rows
            if row["role"] in {"opening", "hook_1s", "middle", "cover", "contact"}
        ]
    if limit is not None:
        rows = rows[:limit]
    processed = 0
    detected = 0
    errors = 0
    total = len(rows)
    for row in rows:
        result = run_selected_ocr(Path(row["frame_path"]), engine)
        boxes = result.get("boxes") or []
        text = normalize_text(" ".join(str(box.get("ocrText") or "") for box in boxes))
        confidence_values = [
            float(box.get("confidence"))
            for box in boxes
            if isinstance(box.get("confidence"), (int, float))
        ]
        avg_confidence = (
            round(sum(confidence_values) / len(confidence_values), 2)
            if confidence_values
            else None
        )
        ocr_id = stable_id("ocr", row["id"], engine)
        conn.execute(
            """
            INSERT INTO ocr_results (
              id, reference_id, frame_sample_id, engine, engine_version, requested_engine,
              fallback_used, fallback_reason, ocr_text, confidence, boxes_json, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(frame_sample_id, requested_engine) DO UPDATE SET
              engine = excluded.engine,
              engine_version = excluded.engine_version,
              fallback_used = excluded.fallback_used,
              fallback_reason = excluded.fallback_reason,
              ocr_text = excluded.ocr_text,
              confidence = excluded.confidence,
              boxes_json = excluded.boxes_json,
              error = excluded.error
            """,
            (
                ocr_id,
                row["reference_id"],
                row["id"],
                result.get("engine") or "none",
                result.get("engineVersion"),
                engine,
                1 if result.get("fallbackUsed") else 0,
                result.get("fallbackReason"),
                text,
                avg_confidence,
                json_dump(boxes),
                result.get("error"),
                now_iso(),
            ),
        )
        if text:
            detected += 1
            upsert_caption_pattern(conn, row["reference_id"], ocr_id, text, boxes, avg_confidence)
        if result.get("available") is False:
            errors += 1
        processed += 1
        if commit_every > 0 and processed % commit_every == 0:
            conn.commit()
        if progress_every > 0 and processed % progress_every == 0:
            print(
                f"ocr progress: {processed}/{total} frames, text={detected}, failures={errors}",
                file=sys.stderr,
                flush=True,
            )
    conn.commit()
    return {
        "schema": "reference_factory.ocr.v1",
        "requestedEngine": engine,
        "processedFrames": processed,
        "framesWithText": detected,
        "ocrFailures": errors,
    }


def upsert_caption_pattern(
    conn: Connection,
    reference_id: str,
    ocr_id: str,
    text: str,
    boxes: list[dict[str, Any]],
    avg_confidence: float | None,
) -> None:
    normalized = normalize_text(text)
    if not normalized:
        return
    lines = [line.strip() for line in re.split(r"\s{2,}|\n", text) if line.strip()]
    if not lines:
        lines = [normalized]
    placement = summarize_placement(boxes)
    caption_hash = text_hash(normalized)
    conn.execute(
        """
        INSERT INTO caption_patterns (
          caption_hash, reference_id, normalized_text, raw_text, first_line,
          line_count, char_count, avg_confidence, placement_json,
          source_ocr_result_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(caption_hash) DO UPDATE SET
          avg_confidence = MAX(caption_patterns.avg_confidence, excluded.avg_confidence),
          placement_json = excluded.placement_json
        """,
        (
            caption_hash,
            reference_id,
            normalized,
            text,
            lines[0],
            len(lines),
            len(normalized),
            avg_confidence,
            json_dump(placement),
            ocr_id,
            now_iso(),
        ),
    )


def ocr_cleanup(conn: Connection, min_confidence: float = 35.0) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT cp.caption_hash, cp.normalized_text, cp.char_count, cp.avg_confidence,
               COUNT(orow.id) AS observed_count
        FROM caption_patterns cp
        LEFT JOIN ocr_results orow
          ON LOWER(TRIM(orow.ocr_text)) = LOWER(TRIM(cp.normalized_text))
        GROUP BY cp.caption_hash
        """
    ).fetchall()
    removed = 0
    kept = 0
    for row in rows:
        text = normalize_text(row["normalized_text"] or "")
        confidence = row["avg_confidence"]
        observed_count = int(row["observed_count"] or 0)
        is_junk = (
            len(text) < 2
            or text.lower() in {"be", "bee", "®", ".", "-", "_"}
            or ((confidence is None or confidence < min_confidence) and observed_count < 2)
        )
        if is_junk:
            conn.execute(
                "DELETE FROM caption_patterns WHERE caption_hash = ?",
                (row["caption_hash"],),
            )
            removed += 1
        else:
            kept += 1
    conn.commit()
    return {
        "schema": "reference_factory.ocr_cleanup.v1",
        "removed": removed,
        "kept": kept,
        "minConfidence": min_confidence,
    }


def summarize_placement(boxes: list[dict[str, Any]]) -> dict[str, Any]:
    if not boxes:
        return {}
    xs: list[float] = []
    ys: list[float] = []
    for box in boxes:
        geom = box.get("box") or {}
        x = float(geom.get("x") or 0)
        y = float(geom.get("y") or 0)
        w = float(geom.get("w") or 0)
        h = float(geom.get("h") or 0)
        xs.append(x + w / 2)
        ys.append(y + h / 2)
    avg_y = sum(ys) / len(ys)
    vertical_band = "top" if avg_y < 260 else "middle" if avg_y < 620 else "bottom"
    return {
        "avgCenterX": round(sum(xs) / len(xs), 2),
        "avgCenterY": round(avg_y, 2),
        "verticalBand": vertical_band,
        "boxCount": len(boxes),
    }
