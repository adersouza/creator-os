from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANES = ("clean", "normal", "timed")

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


def _build_decisions(manifest: dict[str, Any], manifest_path: Path, title: str) -> dict[str, Any]:
    items = []
    for raw in manifest.get("items", []):
        lanes = {
            lane: {
                "path": raw.get(lane),
                "decision": "pending",
                "notes": "",
            }
            for lane in LANES
            if raw.get(lane)
        }
        items.append(
            {
                "id": raw.get("id"),
                "stem": raw.get("stem"),
                "source_board_id": raw.get("source_board_id"),
                "status": "pending",
                "selected_lane": None,
                "reject_reasons": [],
                "notes": "",
                "image": raw.get("image"),
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
                "reject_reasons": "|".join(item.get("reject_reasons", [])),
                "notes": item.get("notes", ""),
            }
            for lane in LANES:
                row[lane] = item.get("lanes", {}).get(lane, {}).get("path", "")
            writer.writerow(row)


def _render_html(manifest: dict[str, Any], decisions: dict[str, Any], title: str) -> str:
    cards = "\n".join(_render_card(item) for item in decisions["items"])
    reject_list = "\n".join(f"<code>{html.escape(reason)}</code>" for reason in HARD_REJECT_REASONS)
    sheets = _render_sheet_links(manifest)
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
    .rejects {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    code {{ padding: 3px 6px; border: 1px solid #3f3f46; border-radius: 6px; background: #18181b; color: #e4e4e7; }}
    main {{ padding: 22px; display: grid; gap: 22px; }}
    article {{ border: 1px solid #27272a; border-radius: 8px; background: #111113; padding: 16px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .grid {{ display: grid; grid-template-columns: minmax(180px, 280px) repeat(3, minmax(180px, 1fr)); gap: 14px; align-items: start; }}
    img, video {{ width: 100%; max-height: 520px; object-fit: contain; background: #000; border-radius: 8px; border: 1px solid #27272a; }}
    h3 {{ margin: 0 0 8px; font-size: 14px; }}
    .lane p {{ min-height: 34px; margin: 0 0 8px; }}
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
  </header>
  <main>{cards}</main>
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


def _render_card(item: dict[str, Any]) -> str:
    lane_html = "\n".join(_render_lane(lane, item["lanes"][lane]) for lane in LANES if lane in item.get("lanes", {}))
    return f"""<article>
  <h2>#{html.escape(str(item.get("id", "")))} {html.escape(str(item.get("stem", "")))}</h2>
  <div class="grid">
    <section>
      <h3>Source Still</h3>
      <img src="{_uri(item.get("image"))}" alt="{html.escape(str(item.get("stem", "")))} source still">
    </section>
    {lane_html}
  </div>
  <p class="decision">Set <code>status</code>, <code>selected_lane</code>, and <code>reject_reasons</code> in the decision JSON/CSV for this row.</p>
</article>"""


def _render_lane(lane: str, data: dict[str, Any]) -> str:
    return f"""<section class="lane">
  <h3>{html.escape(LANE_LABELS[lane])}</h3>
  <p class="policy">{html.escape(LANE_POLICY[lane])}</p>
  <video controls preload="metadata" src="{_uri(data.get("path"))}"></video>
</section>"""


def _uri(path: Any) -> str:
    if not path:
        return ""
    return Path(str(path)).expanduser().resolve().as_uri()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local reel approval board from an approved batch manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--title")
    args = parser.parse_args(argv)
    print(json.dumps(build_approval_board(args.manifest, out_dir=args.out_dir, title=args.title), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
