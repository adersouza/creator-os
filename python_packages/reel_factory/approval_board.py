from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANES = ("clean", "normal", "timed")
GRADES = ("S", "A", "B", "C")
RATING_FIELDS = (
    ("model_match", "Model match"),
    ("face_realism", "Face realism"),
    ("pose_framing", "Pose/framing"),
    ("caption_fit", "Caption fit"),
    ("post_potential", "Post potential"),
)

LANE_LABELS = {
    "clean": "Clean MP4",
    "normal": "Normal Overlay",
    "timed": "Timed Overlay",
}

LANE_POLICY = {
    "clean": "Manual lane: no burned text; operator can add native audio or edit in IG.",
    "normal": "Managed lane: single Reel Factory caption-bank overlay.",
    "timed": "Managed lane: timed caption-bank overlay fitted to the clip duration.",
}

HARD_REJECT_REASONS = (
    "wrong_model",
    "fake_face",
    "bad_hands_or_limbs",
    "ui_or_text_artifacts",
    "bad_crop",
    "caption_wrong_font",
    "caption_bad_placement",
    "caption_covers_focal_point",
    "audio_bad_or_missing",
    "contentforge_blocked",
    "not_postable",
)


def build_approval_board(manifest_path: Path, *, out_dir: Path | None = None, title: str | None = None) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = Path(out_dir).expanduser().resolve() if out_dir else manifest_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    title = title or "Reel Approval Board"
    decisions = _build_decisions(manifest, manifest_path, title)

    html_path = out_dir / "approval_board.html"
    json_path = out_dir / "approval_decisions.json"
    csv_path = out_dir / "approval_decisions.csv"

    json_path.write_text(json.dumps(decisions, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    _write_decision_csv(csv_path, decisions["items"])
    html_path.write_text(_render_html(manifest, decisions, title), encoding="utf-8")

    return {
        "schema": "reel_factory.approval_board_result.v1",
        "count": len(decisions["items"]),
        "boardPath": str(html_path),
        "decisionJsonPath": str(json_path),
        "decisionCsvPath": str(csv_path),
    }


def promote_approval_decisions(decisions_path: Path, *, selected_dir: Path | None = None) -> dict[str, Any]:
    decisions_path = Path(decisions_path).expanduser().resolve()
    decisions = _load_decisions(decisions_path)
    selected_dir = Path(selected_dir).expanduser().resolve() if selected_dir else decisions_path.parent / "selected_reels"
    approved = []
    errors = []

    for item in decisions.get("items", []):
        status = str(item.get("status") or "").strip().lower()
        if status not in {"approved", "approve", "yes"}:
            continue
        lanes = _selected_lanes(item)
        if not lanes:
            errors.append({"id": item.get("id"), "stem": item.get("stem"), "error": "approved item missing valid selected_lanes"})
            continue
        for lane in lanes:
            source = Path(str((item.get("lanes") or {}).get(lane, {}).get("path") or "")).expanduser()
            if not source.exists():
                errors.append({"id": item.get("id"), "stem": item.get("stem"), "lane": lane, "error": f"selected file missing: {source}"})
                continue
            approved.append((item, lane, source.resolve()))

    if errors:
        raise ValueError(json.dumps({"schema": "reel_factory.approval_promote_errors.v1", "errors": errors}, indent=2))

    selected_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item, lane, source in approved:
        out_name = f"{int(item.get('id') or 0):02d}_{_safe_stem(item.get('stem'))}_{lane}{source.suffix.lower()}"
        dest = selected_dir / out_name
        shutil.copy2(source, dest)
        lane_data = (item.get("lanes") or {}).get(lane) or {}
        contentforge = item.get("contentforge") if isinstance(item.get("contentforge"), dict) else {}
        rows.append(
            {
                "id": item.get("id"),
                "stem": item.get("stem"),
                "source_board_id": item.get("source_board_id"),
                "selectedLane": lane,
                "selectedLanes": _selected_lanes(item),
                "outputPath": str(dest),
                "sourcePath": str(source),
                "sourceSha256": _sha256(source),
                "outputSha256": _sha256(dest),
                "audioIntentPath": lane_data.get("audioIntentPath") or _sidecar_path(source, "audio_intent"),
                "generatedAssetLineagePath": lane_data.get("generatedAssetLineagePath") or _sidecar_path(source, "generated_asset_lineage"),
                "contentForgeStatus": item.get("review_status") or contentforge.get("status"),
                "image": item.get("image"),
                "grade": item.get("grade"),
                "ratings": item.get("ratings") or {},
                "notes": item.get("notes", ""),
            }
        )

    manifest = {
        "schema": "reel_factory.approval_selected_manifest.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "sourceDecisionPath": str(decisions_path),
        "count": len(rows),
        "items": rows,
    }
    manifest_path = selected_dir / "selected_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return {
        "schema": "reel_factory.approval_promote_result.v1",
        "count": len(rows),
        "selectedDir": str(selected_dir),
        "manifestPath": str(manifest_path),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_path(path: Path, suffix: str) -> str | None:
    candidate = path.with_suffix(path.suffix + f".{suffix}.json")
    return str(candidate) if candidate.exists() else None


def _build_decisions(manifest: dict[str, Any], manifest_path: Path, title: str) -> dict[str, Any]:
    items = []
    file_results, contentforge_loaded = _contentforge_file_results_by_path(manifest, manifest_path)
    records = manifest.get("items") if isinstance(manifest.get("items"), list) else manifest.get("rows", [])
    for index, raw in enumerate(records or [], 1):
        lanes = {
            lane: {
                "path": _lane_path(raw.get(lane)),
                "decision": "pending",
                "notes": "",
                "placement": _lane_placement(raw.get(lane)),
            }
            for lane in LANES
            if _lane_path(raw.get(lane))
        }
        contentforge = _contentforge_summary(raw, lanes, file_results, contentforge_loaded=contentforge_loaded)
        placement = _placement_summary(raw, lanes)
        items.append(
            {
                "id": raw.get("id") or index,
                "stem": raw.get("stem") or (raw.get("source") or {}).get("id") or f"reel_{index:03d}",
                "source_board_id": raw.get("source_board_id"),
                "review_status": contentforge["status"],
                "contentforge": contentforge,
                "placement": placement,
                "status": "pending",
                "selected_lane": None,
                "selected_lanes": [],
                "grade": None,
                "ratings": {key: None for key, _label in RATING_FIELDS},
                "reject_reasons": [],
                "notes": "",
                "image": raw.get("image") or (raw.get("source") or {}).get("path"),
                "lanes": lanes,
            }
        )

    return {
        "schema": "reel_factory.approval_decisions.v1",
        "title": title,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "manifestPath": str(manifest_path),
        "sourceSchema": manifest.get("schema"),
        "count": len(items),
        "lanePolicy": LANE_POLICY,
        "hardRejectReasons": list(HARD_REJECT_REASONS),
        "items": items,
    }


def _lane_path(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("path")
    if value:
        return str(value)
    return None


def _lane_placement(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    decision = value.get("captionPlacementDecision") if isinstance(value.get("captionPlacementDecision"), dict) else {}
    return {
        "scoredLane": value.get("scoredLane") or value.get("selectedLane") or decision.get("scoredLane"),
        "renderBand": value.get("renderBand") or value.get("finalBand") or decision.get("selectedLane"),
        "finalBand": value.get("finalBand") or value.get("renderBand") or decision.get("selectedLane"),
        "decisionStatus": decision.get("status"),
        "decisionReason": decision.get("reason"),
        "font": value.get("font") or value.get("captionFont") or "Instagram Sans Condensed",
    }


def _contentforge_file_results_by_path(manifest: dict[str, Any], manifest_path: Path) -> tuple[dict[str, dict[str, Any]], bool]:
    review = manifest.get("contentForgeReview") if isinstance(manifest.get("contentForgeReview"), dict) else {}
    loaded = bool(review)
    if not review and manifest.get("contentForgeAuditPath"):
        audit_path = Path(str(manifest["contentForgeAuditPath"]))
        if not audit_path.is_absolute():
            audit_path = manifest_path.parent / audit_path
        try:
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            review = payload
            loaded = True
    results = review.get("fileResults") if isinstance(review.get("fileResults"), list) else []
    mapped = {}
    for result in results:
        if not isinstance(result, dict) or not result.get("outputPath"):
            continue
        mapped[str(Path(str(result["outputPath"])).expanduser().resolve())] = result
    return mapped, loaded


def _contentforge_summary(
    raw: dict[str, Any],
    lanes: dict[str, dict[str, Any]],
    file_results: dict[str, dict[str, Any]],
    *,
    contentforge_loaded: bool,
) -> dict[str, Any]:
    matched = []
    for lane in lanes.values():
        path = lane.get("path")
        if not path:
            continue
        result = file_results.get(str(Path(str(path)).expanduser().resolve()))
        if result:
            matched.append(result)
    warning_codes: list[str] = []
    blocking_codes: list[str] = []
    top_warnings: list[dict[str, Any]] = []
    for result in matched:
        warning_codes.extend(str(code) for code in result.get("warningCodes") or [])
        blocking_codes.extend(str(code) for code in result.get("blockingCodes") or [])
        top_warnings.extend(item for item in result.get("topWarnings") or [] if isinstance(item, dict))
    warning_codes.extend(str(code) for code in raw.get("contentForgeWarnings") or [])
    blocking_codes.extend(str(code) for code in raw.get("contentForgeBlockingCodes") or [])
    missing_file_evidence = bool(contentforge_loaded and lanes and not matched)
    if missing_file_evidence:
        warning_codes.append("contentforge_file_evidence_missing")
    warning_codes = sorted(set(warning_codes))
    blocking_codes = sorted(set(blocking_codes))
    raw_status = str(raw.get("contentForgeStatus") or "").lower()
    status = "blocked" if blocking_codes or raw_status == "fail" else "review" if warning_codes or raw_status in {"warn", "warning", "review"} else "ready"
    return {
        "status": status,
        "warningCodes": warning_codes,
        "blockingCodes": blocking_codes,
        "topWarnings": top_warnings[:5],
        "evidenceMode": raw.get("contentForgeEvidenceMode"),
        "note": raw.get("contentForgeNote"),
    }


def _placement_summary(raw: dict[str, Any], lanes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lane_rows = {}
    for lane, lane_data in lanes.items():
        placement = lane_data.get("placement") or {}
        if placement:
            lane_rows[lane] = placement
    return {
        "status": "review" if any("caption" in code for code in raw.get("contentForgeWarnings") or []) else "ready",
        "lanes": lane_rows,
    }


def _write_decision_csv(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "stem",
                "source_board_id",
                "status",
                "selected_lane",
                "selected_lanes",
                "grade",
                "ratings",
                "reject_reasons",
                "notes",
                "clean",
                "normal",
                "timed",
            ],
        )
        writer.writeheader()
        for item in items:
            row = {
                "id": item.get("id"),
                "stem": item.get("stem"),
                "source_board_id": item.get("source_board_id"),
                "status": item.get("status"),
                "selected_lane": item.get("selected_lane") or "",
                "selected_lanes": "|".join(_selected_lanes(item)),
                "grade": item.get("grade") or "",
                "ratings": json.dumps(item.get("ratings") or {}, sort_keys=True),
                "reject_reasons": "|".join(item.get("reject_reasons", [])),
                "notes": item.get("notes", ""),
            }
            for lane in LANES:
                row[lane] = item.get("lanes", {}).get(lane, {}).get("path", "")
            writer.writerow(row)


def _load_decisions(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            items = []
            for row in csv.DictReader(handle):
                lanes = {lane: {"path": row.get(lane) or "", "decision": "pending", "notes": ""} for lane in LANES if row.get(lane)}
                selected_lanes = [part for part in str(row.get("selected_lanes") or "").split("|") if part]
                items.append(
                    {
                        "id": int(row["id"]) if str(row.get("id") or "").isdigit() else row.get("id"),
                        "stem": row.get("stem"),
                        "source_board_id": row.get("source_board_id"),
                        "status": row.get("status"),
                        "selected_lane": row.get("selected_lane"),
                        "selected_lanes": selected_lanes,
                        "grade": row.get("grade") or None,
                        "ratings": _parse_ratings(row.get("ratings")),
                        "reject_reasons": [part for part in str(row.get("reject_reasons") or "").split("|") if part],
                        "notes": row.get("notes") or "",
                        "lanes": lanes,
                    }
                )
        return {"schema": "reel_factory.approval_decisions.v1", "items": items}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("approval decisions must be a JSON object with an items list")
    return payload


def _selected_lanes(item: dict[str, Any]) -> list[str]:
    raw = item.get("selected_lanes")
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str) and raw:
        values = raw.replace(",", "|").split("|")
    else:
        values = [item.get("selected_lane")]
    selected = []
    for value in values:
        lane = str(value or "").strip()
        if lane in LANES and lane not in selected:
            selected.append(lane)
    return selected


def _parse_ratings(value: Any) -> dict[str, Any]:
    if not value:
        return {key: None for key, _label in RATING_FIELDS}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {key: parsed.get(key) for key, _label in RATING_FIELDS}


def _safe_stem(value: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "reel"))
    return text.strip("_") or "reel"


def _render_html(manifest: dict[str, Any], decisions: dict[str, Any], title: str) -> str:
    cards = "\n".join(_render_card(item, index) for index, item in enumerate(decisions["items"]))
    reject_list = "\n".join(f"<code>{html.escape(reason)}</code>" for reason in HARD_REJECT_REASONS)
    sheets = _render_sheet_links(manifest)
    decisions_json = json.dumps(decisions, ensure_ascii=True).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #09090b; color: #f4f4f5; }}
    header {{ position: sticky; top: 0; z-index: 3; padding: 18px 22px; background: rgba(9,9,11,.94); border-bottom: 1px solid #27272a; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; }}
    a {{ color: #93c5fd; }}
    .meta, .policy, .decision {{ color: #a1a1aa; font-size: 13px; }}
    .reviewbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 14px; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    button {{ cursor: pointer; border: 1px solid #3f3f46; border-radius: 999px; background: #18181b; color: #f4f4f5; padding: 9px 13px; font: inherit; }}
    button.primary {{ background: #16a34a; border-color: #22c55e; color: #052e16; font-weight: 700; }}
    button.danger {{ background: #991b1b; border-color: #ef4444; color: #fee2e2; font-weight: 700; }}
    button[aria-pressed="true"] {{ outline: 2px solid #93c5fd; background: #1d4ed8; border-color: #60a5fa; }}
    .rejects {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    code {{ padding: 3px 6px; border: 1px solid #3f3f46; border-radius: 6px; background: #18181b; color: #e4e4e7; }}
    .evidence {{ margin: 12px 0; padding: 10px; border: 1px solid #27272a; border-radius: 8px; background: #18181b; display: grid; gap: 8px; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .chip {{ padding: 3px 7px; border-radius: 999px; border: 1px solid #3f3f46; color: #e4e4e7; background: #09090b; font-size: 12px; }}
    .chip.block {{ border-color: #ef4444; color: #fecaca; }}
    .chip.warn {{ border-color: #f59e0b; color: #fde68a; }}
    .chip.ready {{ border-color: #22c55e; color: #bbf7d0; }}
    .metric {{ color: #d4d4d8; font-size: 12px; }}
    main {{ padding: 22px; display: grid; gap: 22px; }}
    article {{ border: 1px solid #27272a; border-radius: 8px; background: #111113; padding: 16px; touch-action: pan-y; }}
    article.hidden {{ display: none; }}
    article.approved {{ border-color: #22c55e; }}
    article.rejected {{ border-color: #ef4444; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .grid {{ display: grid; grid-template-columns: minmax(180px, 280px) repeat(3, minmax(180px, 1fr)); gap: 14px; align-items: start; }}
    img, video {{ width: 100%; max-height: 520px; object-fit: contain; background: #000; border-radius: 8px; border: 1px solid #27272a; }}
    h3 {{ margin: 0 0 8px; font-size: 14px; }}
    .lane p {{ min-height: 34px; margin: 0 0 8px; }}
    .lane.selected video {{ border-color: #60a5fa; box-shadow: 0 0 0 2px rgba(96,165,250,.45); }}
    .grading {{ margin-top: 14px; display: grid; gap: 10px; }}
    .grade-row, .rating-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .rating-row span {{ min-width: 110px; color: #d4d4d8; font-size: 13px; }}
    .rating-row button {{ min-width: 36px; padding: 7px 10px; }}
    @media (max-width: 1000px) {{ .grid {{ grid-template-columns: 1fr; }} img, video {{ max-height: none; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <div class="meta">Items: {len(decisions["items"])} · Source: {html.escape(str(decisions.get("manifestPath", "")))}</div>
    <div class="meta">Decision files: <code>approval_decisions.json</code> and <code>approval_decisions.csv</code></div>
    {sheets}
    <div class="rejects">{reject_list}</div>
    <div class="reviewbar">
      <button id="prevBtn">Prev</button>
      <button id="rejectBtn" class="danger">Reject ←</button>
      <button id="approveBtn" class="primary">Approve →</button>
      <button id="nextBtn">Next</button>
      <button id="downloadBtn">Download reviewed JSON</button>
      <span id="progress" class="meta"></span>
    </div>
    <div class="filters">
      <button data-filter="all" aria-pressed="true">All</button>
      <button data-filter="blocked">Blocked</button>
      <button data-filter="warnings">Warnings</button>
      <button data-filter="caption">Caption placement</button>
      <button data-filter="readability">Readability</button>
      <button data-filter="watchability">Watchability</button>
      <button data-filter="clean">Clean MP4</button>
    </div>
    <div class="meta">Tap or use keys to select any lanes: <code>1</code> clean, <code>2</code> normal, <code>3</code> timed. Swipe left/right or use <code>←</code>/<code>→</code> to reject/approve.</div>
  </header>
  <main>{cards}</main>
  <script type="application/json" id="decisions-data">{decisions_json}</script>
  <script>
    (() => {{
      const original = JSON.parse(document.getElementById("decisions-data").textContent);
      const storageKey = "approval-board:" + original.manifestPath + ":" + original.createdAt;
      let decisions = JSON.parse(localStorage.getItem(storageKey) || "null") || original;
      const items = decisions.items || [];
      const cards = Array.from(document.querySelectorAll("article[data-index]"));
      let index = Math.max(0, items.findIndex((item) => item.status === "pending"));
      if (index < 0) index = 0;
      let filter = "all";

      const currentItem = () => items[index] || null;
      const save = () => localStorage.setItem(storageKey, JSON.stringify(decisions));

      function defaultLanes(item) {{
        if (!item) return [];
        if (Array.isArray(item.selected_lanes) && item.selected_lanes.length) return item.selected_lanes;
        if (item.selected_lane) return [item.selected_lane];
        if (item.lanes.normal) return ["normal"];
        if (item.lanes.clean) return ["clean"];
        if (item.lanes.timed) return ["timed"];
        return [];
      }}

      function setSelectedLanes(item, lanes) {{
        item.selected_lanes = lanes.filter((lane, i) => item.lanes[lane] && lanes.indexOf(lane) === i);
        item.selected_lane = item.selected_lanes[0] || null;
      }}

      function render() {{
        cards.forEach((card, i) => {{
          const item = items[i] || {{}};
          card.classList.toggle("hidden", i !== index || !matchesFilter(card, filter));
          card.classList.toggle("approved", item.status === "approved");
          card.classList.toggle("rejected", item.status === "rejected");
          card.querySelectorAll("[data-lane]").forEach((node) => {{
            const selected = (item.selected_lanes || []).includes(node.dataset.lane);
            node.classList.toggle("selected", selected);
            const button = node.querySelector("button");
            if (button) button.setAttribute("aria-pressed", String(selected));
          }});
          card.querySelectorAll("[data-grade]").forEach((button) => {{
            button.setAttribute("aria-pressed", String(button.dataset.grade === item.grade));
          }});
          card.querySelectorAll("[data-rating-field][data-rating-value]").forEach((button) => {{
            const ratings = item.ratings || {{}};
            button.setAttribute("aria-pressed", String(Number(button.dataset.ratingValue) === Number(ratings[button.dataset.ratingField])));
          }});
        }});
        const done = items.filter((item) => item.status !== "pending").length;
        document.getElementById("progress").textContent = `${{index + 1}}/${{items.length}} · ${{done}} reviewed`;
      }}

      function matchesFilter(card, value) {{
        if (value === "all") return true;
        if (value === "blocked") return card.dataset.reviewStatus === "blocked";
        if (value === "warnings") return card.dataset.reviewStatus === "review";
        if (value === "caption") return (card.dataset.codes || "").includes("caption");
        if (value === "readability") return (card.dataset.codes || "").includes("readability") || (card.dataset.codes || "").includes("contrast");
        if (value === "watchability") return (card.dataset.codes || "").includes("watch") || (card.dataset.codes || "").includes("vmaf") || (card.dataset.codes || "").includes("cambi");
        if (value === "clean") return Boolean(card.querySelector('[data-lane="clean"]'));
        return true;
      }}

      function seekToVisible(direction) {{
        if (!cards.length) return;
        for (let step = 0; step < cards.length; step++) {{
          const next = Math.max(0, Math.min(cards.length - 1, index + (direction * step)));
          if (matchesFilter(cards[next], filter)) {{
            index = next;
            return;
          }}
        }}
      }}

      function toggleLane(lane) {{
        const item = currentItem();
        if (!item || !item.lanes[lane]) return;
        const lanes = item.selected_lanes || [];
        setSelectedLanes(item, lanes.includes(lane) ? lanes.filter((value) => value !== lane) : lanes.concat(lane));
        save();
        render();
      }}

      function decide(status) {{
        const item = currentItem();
        if (!item) return;
        item.status = status;
        setSelectedLanes(item, status === "approved" ? defaultLanes(item) : []);
        save();
        if (index < items.length - 1) index += 1;
        render();
      }}

      function setGrade(grade) {{
        const item = currentItem();
        if (!item) return;
        item.grade = grade;
        save();
        render();
      }}

      function setRating(field, value) {{
        const item = currentItem();
        if (!item) return;
        item.ratings = item.ratings || {{}};
        item.ratings[field] = Number(value);
        save();
        render();
      }}

      function download() {{
        const blob = new Blob([JSON.stringify(decisions, null, 2) + "\\n"], {{ type: "application/json" }});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "approval_decisions.reviewed.json";
        link.click();
        URL.revokeObjectURL(link.href);
      }}

      document.querySelectorAll("[data-lane] button").forEach((button) => {{
        button.addEventListener("click", () => toggleLane(button.closest("[data-lane]").dataset.lane));
      }});
      document.querySelectorAll("[data-grade]").forEach((button) => {{
        button.addEventListener("click", () => setGrade(button.dataset.grade));
      }});
      document.querySelectorAll("[data-rating-field][data-rating-value]").forEach((button) => {{
        button.addEventListener("click", () => setRating(button.dataset.ratingField, button.dataset.ratingValue));
      }});
      document.querySelectorAll("[data-filter]").forEach((button) => {{
        button.addEventListener("click", () => {{
          filter = button.dataset.filter || "all";
          document.querySelectorAll("[data-filter]").forEach((node) => node.setAttribute("aria-pressed", String(node === button)));
          seekToVisible(1);
          render();
        }});
      }});
      document.getElementById("approveBtn").addEventListener("click", () => decide("approved"));
      document.getElementById("rejectBtn").addEventListener("click", () => decide("rejected"));
      document.getElementById("nextBtn").addEventListener("click", () => {{ index = Math.min(items.length - 1, index + 1); seekToVisible(1); render(); }});
      document.getElementById("prevBtn").addEventListener("click", () => {{ index = Math.max(0, index - 1); seekToVisible(-1); render(); }});
      document.getElementById("downloadBtn").addEventListener("click", download);
      document.addEventListener("keydown", (event) => {{
        if (event.key === "1") toggleLane("clean");
        if (event.key === "2") toggleLane("normal");
        if (event.key === "3") toggleLane("timed");
        if (event.key === "ArrowRight") decide("approved");
        if (event.key === "ArrowLeft") decide("rejected");
      }});
      let startX = null;
      document.addEventListener("touchstart", (event) => {{ startX = event.changedTouches[0].clientX; }}, {{ passive: true }});
      document.addEventListener("touchend", (event) => {{
        if (startX === null) return;
        const dx = event.changedTouches[0].clientX - startX;
        startX = null;
        if (Math.abs(dx) < 80) return;
        decide(dx > 0 ? "approved" : "rejected");
      }}, {{ passive: true }});
      items.forEach((item) => setSelectedLanes(item, defaultLanes(item)));
      render();
    }})();
  </script>
</body>
</html>
"""


def _render_sheet_links(manifest: dict[str, Any]) -> str:
    links = []
    for label, key in (("Clean sheet", "cleanSheet"), ("Normal sheet", "normalSheet"), ("Timed sheet", "timedSheet")):
        path = manifest.get(key)
        if path:
            links.append(f'<a href="{_uri(path)}">{html.escape(label)}</a>')
    if not links:
        return ""
    return f'<div class="meta">Sheets: {" · ".join(links)}</div>'


def _render_card(item: dict[str, Any], index: int) -> str:
    lane_html = "\n".join(_render_lane(lane, item["lanes"][lane]) for lane in LANES if lane in item.get("lanes", {}))
    grading_html = _render_grading()
    evidence_html = _render_evidence(item)
    codes = " ".join((item.get("contentforge") or {}).get("warningCodes") or []) + " " + " ".join((item.get("contentforge") or {}).get("blockingCodes") or [])
    source_media = _render_source_media(item)
    return f"""<article data-index="{index}" data-review-status="{html.escape(str(item.get("review_status") or "ready"))}" data-codes="{html.escape(codes)}">
  <h2>#{html.escape(str(item.get("id", "")))} {html.escape(str(item.get("stem", "")))}</h2>
  {evidence_html}
  <div class="grid">
    <section>
      <h3>Source</h3>
      {source_media}
    </section>
    {lane_html}
  </div>
  {grading_html}
  <p class="decision">Use the buttons or keys to set <code>status</code>, <code>selected_lanes</code>, and <code>reject_reasons</code> for this row.</p>
</article>"""


def _render_source_media(item: dict[str, Any]) -> str:
    path = item.get("image")
    if not path:
        return ""
    suffix = Path(str(path)).suffix.lower()
    if suffix in {".mp4", ".mov", ".webm"}:
        return f'<video controls preload="metadata" src="{_uri(path)}"></video>'
    return f'<img src="{_uri(path)}" alt="{html.escape(str(item.get("stem", "")))} source">'


def _render_evidence(item: dict[str, Any]) -> str:
    contentforge = item.get("contentforge") or {}
    placement = item.get("placement") or {}
    status = str(contentforge.get("status") or item.get("review_status") or "ready")
    warning_codes = contentforge.get("warningCodes") or []
    blocking_codes = contentforge.get("blockingCodes") or []
    status_chip = f'<span class="chip {html.escape(status)}">status: {html.escape(status)}</span>'
    block_chips = "".join(f'<span class="chip block">{html.escape(str(code))}</span>' for code in blocking_codes)
    warn_chips = "".join(f'<span class="chip warn">{html.escape(str(code))}</span>' for code in warning_codes)
    if not block_chips and not warn_chips:
        warn_chips = '<span class="chip ready">no ContentForge codes</span>'
    top = []
    for warning in contentforge.get("topWarnings") or []:
        code = html.escape(str(warning.get("code") or "warning"))
        message = html.escape(str(warning.get("message") or warning.get("summary") or "review"))
        top.append(f"<div class=\"metric\"><code>{code}</code> {message}</div>")
    placement_rows = []
    for lane, data in (placement.get("lanes") or {}).items():
        scored = data.get("scoredLane") or "unknown"
        final = data.get("finalBand") or data.get("renderBand") or "unknown"
        font = data.get("font") or ""
        reason = data.get("decisionReason") or ""
        placement_rows.append(
            f'<div class="metric"><code>{html.escape(str(lane))}</code> '
            f'scored {html.escape(str(scored))} → rendered {html.escape(str(final))} · '
            f'{html.escape(str(font))} {html.escape(str(reason))}</div>'
        )
    note = contentforge.get("note")
    note_html = f'<div class="metric">{html.escape(str(note))}</div>' if note else ""
    return f"""<section class="evidence">
  <div class="chips">{status_chip}{block_chips}{warn_chips}</div>
  {''.join(top)}
  {''.join(placement_rows)}
  {note_html}
</section>"""


def _render_lane(lane: str, data: dict[str, Any]) -> str:
    return f"""<section class="lane" data-lane="{html.escape(lane)}">
  <h3>{html.escape(LANE_LABELS[lane])}</h3>
  <p class="policy">{html.escape(LANE_POLICY[lane])}</p>
  <video controls preload="metadata" src="{_uri(data.get("path"))}"></video>
  <button data-pick-lane="{html.escape(lane)}">Toggle {html.escape(LANE_LABELS[lane])}</button>
</section>"""


def _render_grading() -> str:
    grade_buttons = " ".join(f'<button data-grade="{grade}">{grade}</button>' for grade in GRADES)
    rows = []
    for key, label in RATING_FIELDS:
        buttons = " ".join(f'<button data-rating-field="{key}" data-rating-value="{value}">{value}</button>' for value in range(1, 6))
        rows.append(f'<div class="rating-row"><span>{html.escape(label)}</span>{buttons}</div>')
    return f"""<section class="grading">
  <div class="grade-row"><span class="policy">Keeper grade</span>{grade_buttons}</div>
  {"".join(rows)}
</section>"""


def _uri(path: Any) -> str:
    if not path:
        return ""
    return Path(str(path)).expanduser().resolve().as_uri()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local reel approval board from an approved batch manifest.")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--promote-decisions", type=Path)
    parser.add_argument("--selected-dir", type=Path)
    args = parser.parse_args(argv)
    if args.promote_decisions:
        print(json.dumps(promote_approval_decisions(args.promote_decisions, selected_dir=args.selected_dir), indent=2))
        return 0
    if not args.manifest:
        parser.error("--manifest is required unless --promote-decisions is used")
    print(json.dumps(build_approval_board(args.manifest, out_dir=args.out_dir, title=args.title), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
