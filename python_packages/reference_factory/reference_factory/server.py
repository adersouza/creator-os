from __future__ import annotations

from pathlib import Path
from typing import Annotated

from creator_os_core.local_api_auth import (
    install_local_api_auth_middleware,
    require_local_api_auth,
)
from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .audio import (
    audio_catalog_health,
    audio_resolution_shortlist,
    list_audio_catalog,
    list_audio_trend_snapshots,
    recommend_audio,
    resolve_audio_record,
    review_audio_catalog,
    upsert_audio_record,
    upsert_audio_trend_snapshot,
)
from .config import DEFAULT_DB_PATH
from .db import connect
from .reference_intake import (
    export_analysis_queue,
    export_video_prompts,
    generate_video_prompts,
    import_reference_analysis,
    queue_reference_analysis,
)
from .review import (
    reference_detail,
    reference_query,
    review_batch,
    review_stats,
    set_reference_label,
)


class LabelPayload(BaseModel):
    label: str | None = None
    tags: list[str] = []
    notes: str | None = None


class AudioPayload(BaseModel):
    title: str
    artistName: str | None = None
    platform: str
    nativeAudioId: str | None = None
    nativeAudioUrl: str | None = None
    moodTags: str | None = None
    bestContentTypes: str | None = None
    accountFit: str | None = None
    trendStatus: str | None = None
    usageCount: int | None = None
    expiresAt: str | None = None
    safeUsageNotes: str | None = None


class AudioSnapshotPayload(BaseModel):
    audioCatalogId: str | None = None
    platform: str | None = None
    nativeAudioId: str | None = None
    observedAt: str | None = None
    trendStatus: str = "unknown"
    usageCount: int | None = None
    saturationScore: float | None = None
    velocityScore: float | None = None
    curator: str | None = None
    source: str | None = None
    notes: str | None = None


class ReferenceAnalysisQueuePayload(BaseModel):
    source: str
    platform: str = "instagram"
    providerTarget: str = "gemini"
    accountProfile: str | None = None
    intakeProfile: str = "ig_ofm"
    mediaKinds: list[str] = ["video"]
    limit: int | None = None


class ReferenceAnalysisImportPayload(BaseModel):
    input: str


class GenerateVideoPromptsPayload(BaseModel):
    tools: list[str] = ["higgsfield_soul_image", "kling_3_video"]
    modelProfile: str | None = None
    limit: int = 50
    includePending: bool = True


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(
        title="Reference Factory Review",
        version="0.1.0",
        dependencies=[Depends(require_local_api_auth)],
    )
    install_local_api_auth_middleware(app)

    def conn():
        return connect(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return REVIEW_HTML

    @app.get("/api/stats")
    def stats() -> dict[str, object]:
        with conn() as db:
            return review_stats(db)

    @app.get("/api/audio")
    def audio(
        platform: str | None = None,
        freshOnly: bool = False,
        needsReview: bool = False,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        with conn() as db:
            if needsReview:
                return review_audio_catalog(db, platform=platform, limit=limit)
            return list_audio_catalog(
                db, platform=platform, fresh_only=freshOnly, limit=limit
            )

    @app.get("/api/audio/review")
    def audio_review(
        platform: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        with conn() as db:
            return review_audio_catalog(db, platform=platform, limit=limit)

    @app.get("/api/audio/snapshots")
    def audio_snapshots(
        platform: str | None = None,
        audioCatalogId: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        with conn() as db:
            return list_audio_trend_snapshots(
                db, platform=platform, audio_catalog_id=audioCatalogId, limit=limit
            )

    @app.get("/api/audio/recommend")
    def audio_recommend(
        platform: str,
        contentTags: str = "",
        accountTags: str = "",
        limit: Annotated[int, Query(ge=1, le=20)] = 3,
    ) -> dict[str, object]:
        with conn() as db:
            return recommend_audio(
                db,
                platform=platform,
                content_tags=[
                    tag.strip() for tag in contentTags.split(",") if tag.strip()
                ],
                account_tags=[
                    tag.strip() for tag in accountTags.split(",") if tag.strip()
                ],
                limit=limit,
            )

    @app.get("/api/audio/health")
    def audio_health(
        platform: str | None = None,
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
    ) -> dict[str, object]:
        with conn() as db:
            return audio_catalog_health(db, platform=platform, limit=limit)

    @app.get("/api/audio/shortlist")
    def audio_shortlist(
        platform: str = "tiktok",
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> dict[str, object]:
        with conn() as db:
            return audio_resolution_shortlist(db, platform=platform, limit=limit)

    @app.get("/api/reference-analysis-queue")
    def reference_analysis_queue(
        providerTarget: str = "gemini",
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> dict[str, object]:
        with conn() as db:
            return export_analysis_queue(
                db,
                data_root=db_path.parent,
                provider_target=providerTarget,
                limit=limit,
            )

    @app.post("/api/reference-analysis/queue")
    def reference_analysis_queue_create(
        payload: Annotated[ReferenceAnalysisQueuePayload, Body()],
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return queue_reference_analysis(
                    db,
                    Path(payload.source),
                    data_root=db_path.parent,
                    platform=payload.platform,
                    provider_target=payload.providerTarget,
                    account_profile=payload.accountProfile,
                    intake_profile=payload.intakeProfile,
                    media_kinds=payload.mediaKinds,
                    limit=payload.limit,
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference-analysis/import")
    def reference_analysis_import(
        payload: Annotated[ReferenceAnalysisImportPayload, Body()],
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return import_reference_analysis(db, Path(payload.input))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/video-prompts")
    def video_prompts(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        with conn() as db:
            return export_video_prompts(db, data_root=db_path.parent, limit=limit)

    @app.post("/api/video-prompts/generate")
    def video_prompts_generate(
        payload: Annotated[GenerateVideoPromptsPayload, Body()],
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return generate_video_prompts(
                    db,
                    data_root=db_path.parent,
                    target_tools=payload.tools,
                    model_profile=payload.modelProfile,
                    limit=payload.limit,
                    include_pending=payload.includePending,
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/audio")
    def audio_upsert(payload: Annotated[AudioPayload, Body()]) -> dict[str, object]:
        try:
            with conn() as db:
                return upsert_audio_record(db, payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/audio/resolve")
    def audio_resolve(payload: Annotated[AudioPayload, Body()]) -> dict[str, object]:
        try:
            with conn() as db:
                return resolve_audio_record(db, payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/audio/snapshots")
    def audio_snapshot_upsert(
        payload: Annotated[AudioSnapshotPayload, Body()],
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return upsert_audio_trend_snapshot(
                    db, payload.model_dump(exclude_none=True)
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/references")
    def references(
        label: str | None = None,
        captioned: str | None = None,
        account: str | None = None,
        minScore: int | None = None,
        sort: str = "score",
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        captioned_bool = None
        if captioned in {"true", "1", "yes"}:
            captioned_bool = True
        elif captioned in {"false", "0", "no"}:
            captioned_bool = False
        with conn() as db:
            return reference_query(
                db,
                label=label,
                captioned=captioned_bool,
                account=account,
                min_score=minScore,
                sort=sort,
                limit=limit,
                offset=offset,
            )

    @app.get("/api/review-batch")
    def batch(
        mode: str = "balanced",
        target: Annotated[int, Query(ge=1, le=1000)] = 300,
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return review_batch(db, target=target, mode=mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/reference/{reference_id}")
    def detail(reference_id: str) -> dict[str, object]:
        with conn() as db:
            item = reference_detail(db, reference_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Unknown reference")
            return item

    @app.post("/api/reference/{reference_id}/label")
    def label(
        reference_id: str, payload: Annotated[LabelPayload, Body()]
    ) -> dict[str, object]:
        try:
            with conn() as db:
                return set_reference_label(
                    db, reference_id, payload.label, payload.tags, payload.notes
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/frame/{frame_id}")
    def frame(frame_id: str) -> FileResponse:
        with conn() as db:
            row = db.execute(
                "SELECT frame_path FROM frame_samples WHERE id = ?",
                (frame_id,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unknown frame")
        path = Path(row["frame_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Frame missing")
        return FileResponse(path)

    return app


def run_server(host: str, port: int, db_path: Path = DEFAULT_DB_PATH) -> None:
    import uvicorn

    uvicorn.run(create_app(db_path), host=host, port=port)


REVIEW_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reference Factory</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; background: #0f0f10; color: #f2f2f2; font: 13px system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }
    header { position: sticky; top: 0; z-index: 2; padding: 14px 18px; background: rgba(15,15,16,.94); border-bottom: 1px solid #2a2a2c; display: grid; gap: 10px; }
    h1 { margin: 0; font-size: 18px; }
    .stats { color: #a9a9ad; display: flex; flex-wrap: wrap; gap: 12px; }
    .progress { display: flex; flex-wrap: wrap; gap: 8px; }
    .pill { background: #1a1a1d; border: 1px solid #333338; border-radius: 999px; padding: 5px 9px; color: #d7d7da; }
    .guidance { color: #bdbdc2; display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; }
    .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    select, input, button { background: #1d1d20; color: #f4f4f5; border: 1px solid #39393d; border-radius: 6px; min-height: 32px; padding: 0 10px; }
    button { cursor: pointer; font-weight: 700; }
    button:hover { border-color: #777; }
    main { padding: 18px; }
    .audio-panel { margin: 0 0 16px; padding: 12px; border: 1px solid #2c2c30; border-radius: 8px; background: #151518; display: grid; gap: 10px; }
    .audio-panel form, .audio-filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .audio-list { display: grid; gap: 6px; }
    .audio-row { display: grid; grid-template-columns: minmax(170px, 1.2fr) minmax(110px, .6fr) minmax(160px, .8fr) minmax(190px, 1fr) minmax(130px, .7fr); gap: 8px; padding: 8px; border: 1px solid #28282c; border-radius: 6px; background: #1a1a1d; }
    .audio-row a { color: #94d9ff; overflow-wrap: anywhere; }
    .audio-actions { display: flex; flex-wrap: wrap; gap: 4px; }
    .audio-actions button { min-height: 26px; padding: 0 7px; font-size: 11px; }
    .intake-panel { margin: 0 0 16px; padding: 12px; border: 1px solid #2c2c30; border-radius: 8px; background: #151518; display: grid; gap: 10px; }
    .intake-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
    .intake-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .intake-output { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
    .intake-card { border: 1px solid #28282c; border-radius: 6px; padding: 8px; background: #1a1a1d; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
    .card { background: #18181b; border: 1px solid #2c2c30; border-radius: 8px; overflow: hidden; display: grid; }
    .card img { width: 100%; aspect-ratio: 9/16; object-fit: cover; background: #050505; }
    .meta { padding: 10px; display: grid; gap: 6px; }
    .muted { color: #a9a9ad; }
    .caption { color: #d7d7da; min-height: 34px; }
    .actions { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; }
    .tags { display: flex; flex-wrap: wrap; gap: 4px; }
    .tag { font-size: 11px; padding: 3px 6px; border: 1px solid #34343a; border-radius: 999px; color: #bdbdc2; }
    .is-gold { outline: 2px solid #d4af37; }
    .is-maybe { outline: 2px solid #5da8ff; }
    .is-ignore { opacity: .55; }
    code { color: #94d9ff; font-size: 11px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <header>
    <h1>Reference Factory</h1>
    <div class="stats" id="stats">Loading stats...</div>
    <div class="progress" id="progress"></div>
    <div class="guidance">
      <span><strong>Gold:</strong> strong style/caption/visual pattern worth learning from</span>
      <span><strong>Maybe:</strong> useful but not clearly top-tier</span>
      <span><strong>Ignore:</strong> broken, duplicate, weak, irrelevant, or low-value</span>
    </div>
    <div class="controls">
      <select id="label">
        <option value="unreviewed">Unreviewed</option>
        <option value="">All</option>
        <option value="gold">Gold</option>
        <option value="maybe">Maybe</option>
        <option value="ignore">Ignored</option>
      </select>
      <select id="captioned">
        <option value="">Any captions</option>
        <option value="true">Captioned</option>
        <option value="false">No caption</option>
      </select>
      <select id="sort">
        <option value="score">Score</option>
        <option value="account-balanced">Account balanced</option>
        <option value="random">Random</option>
        <option value="newest">Newest filename</option>
      </select>
      <input id="account" placeholder="account">
      <input id="minScore" type="number" placeholder="min score" min="0" max="100">
      <button id="load">Load</button>
      <button id="batch">Guided 300 Batch</button>
    </div>
  </header>
  <main>
    <section class="intake-panel">
      <div>
        <strong>IG-first Gemini -> Higgsfield/Kling intake</strong>
        <p class="muted">Queue downloaded references for manual Gemini Pro analysis, import JSON results, then export paired daily prompts.</p>
      </div>
      <div class="intake-grid">
        <input id="intakeSource" placeholder="/Users/.../Downloads/tiktok">
        <select id="intakePlatform">
          <option value="instagram">Instagram</option>
          <option value="tiktok">TikTok</option>
        </select>
        <input id="intakeProvider" value="gemini">
        <input id="intakeProfile" value="ig_ofm">
        <input id="intakeAccountProfile" placeholder="model/account profile">
        <input id="intakeKinds" value="video">
        <input id="intakeLimit" type="number" min="1" max="500" value="10">
      </div>
      <div class="intake-actions">
        <button id="queueReferenceAnalysis">Queue Gemini Analysis</button>
        <input id="analysisImportPath" placeholder="/path/to/gemini_analysis.json">
        <button id="importReferenceAnalysis">Import Gemini JSON</button>
        <button id="generateVideoPrompts">Generate Prompt Pairs</button>
        <button id="loadVideoPrompts">Load Prompt Exports</button>
      </div>
      <div class="intake-output" id="intakeOutput"></div>
    </section>
    <section class="audio-panel">
      <div class="audio-filters">
        <strong>Audio catalog</strong>
        <select id="audioPlatform">
          <option value="instagram">Instagram</option>
          <option value="tiktok">TikTok</option>
          <option value="youtube">YouTube</option>
        </select>
        <label><input id="audioFresh" type="checkbox" checked> fresh only</label>
        <label><input id="audioNeedsReview" type="checkbox"> needs review</label>
        <button id="audioLoad">Load audio</button>
        <span id="audioHealth" class="muted"></span>
      </div>
      <form id="audioForm">
        <input id="audioTitle" placeholder="title" required>
        <input id="audioArtist" placeholder="artist/source">
        <input id="audioNativeId" placeholder="native ID">
        <input id="audioUrl" placeholder="native URL">
        <input id="audioTags" placeholder="vibe tags">
        <input id="audioContentTags" placeholder="content tags">
        <input id="audioAccountTags" placeholder="account tags">
        <input id="audioUsage" type="number" placeholder="usage count">
        <input id="audioExpires" placeholder="expires at">
        <input id="audioSafeNotes" placeholder="safe usage notes">
        <select id="audioTrend">
          <option value="rising">Rising</option>
          <option value="trending">Trending</option>
          <option value="fresh">Fresh</option>
          <option value="current">Current</option>
          <option value="peaked">Peaked</option>
          <option value="fading">Fading</option>
          <option value="unknown">Unknown</option>
          <option value="stale">Stale</option>
          <option value="expired">Expired</option>
        </select>
        <button type="submit">Resolve/save audio</button>
      </form>
      <div class="audio-list" id="audioList"></div>
    </section>
    <section class="grid" id="grid"></section>
  </main>
  <script>
    const TAGS = ["caption_style","visual_style","mirror","fit_check","bedroom","walking","pose","hook_good","no_caption"];
    let AUDIO_ITEMS = {};
    function intakeCard(title, body) {
      return `<div class="intake-card"><b>${esc(title)}</b><div class="muted">${body}</div></div>`;
    }
    function showIntake(result) {
      const cards = [];
      if (result.queued != null) cards.push(intakeCard("Queued", `${result.queued} references · ${result.intakeProfile || ""}`));
      if (result.imported != null) cards.push(intakeCard("Imported", `${result.imported} analyses · ${(result.errors || []).length} errors`));
      if (result.count != null) cards.push(intakeCard("Prompts", `${result.count} prompt records`));
      const exportObj = result.export || result;
      for (const [label, key] of [
        ["Queue JSON", "jsonPath"],
        ["Queue Markdown", "markdownPath"],
        ["Higgsfield JSONL", "dailyHiggsfieldImageJsonlPath"],
        ["Kling JSONL", "dailyKlingVideoJsonlPath"],
        ["Prompt Review", "dailyPromptReviewPath"],
      ]) {
        if (exportObj[key]) cards.push(intakeCard(label, `<code>${esc(exportObj[key])}</code>`));
      }
      document.getElementById("intakeOutput").innerHTML = cards.join("") || intakeCard("Result", `<pre>${esc(JSON.stringify(result, null, 2))}</pre>`);
    }
    async function intakePost(url, payload) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "intake request failed");
      showIntake(data);
      return data;
    }
    function esc(value) {
      return String(value || "").replace(/[&<>"'`]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" }[ch]));
    }
    async function loadStats() {
      const s = await fetch("/api/stats").then(r => r.json());
      const c = s.counts;
      const p = s.goldProgress || {};
      document.getElementById("stats").textContent =
        `${c.validVideos} videos · ${c.contactThumbnails} thumbnails · ${c.missingContactThumbnails} missing · ${c.captionPatterns} captions · ${c.gold} gold · ${c.maybe} maybe · ${c.ignore} ignored`;
      document.getElementById("progress").innerHTML =
        `<span class="pill">Target ${p.target || 300} gold</span>` +
        `<span class="pill">${p.gold || 0}/${p.target || 300} done</span>` +
        `<span class="pill">${p.captionedGold || 0} captioned gold</span>` +
        `<span class="pill">${p.visualGold || 0} visual/no-caption gold</span>` +
        `<span class="pill">account cap ${p.accountCap || 30}</span>`;
    }
    function qs() {
      const p = new URLSearchParams({ limit: "120" });
      for (const id of ["label","captioned","sort","account","minScore"]) {
        const v = document.getElementById(id).value;
        if (v) p.set(id, v);
      }
      return p.toString();
    }
    async function setLabel(id, label, tags=[]) {
      await fetch(`/api/reference/${id}/label`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, tags })
      });
      await load();
    }
    function card(item) {
      const cls = item.label ? `card is-${item.label}` : "card";
      const tags = (item.tags || []).map(t => `<span class="tag">${t}</span>`).join("");
      const tagButtons = TAGS.map(t => `<button onclick="setLabel('${item.referenceId}', 'gold', ['${t}'])">${t}</button>`).join("");
      return `<article class="${cls}">
        ${item.thumbnailUrl ? `<img src="${item.thumbnailUrl}" loading="lazy">` : `<div class="noimg">No thumb</div>`}
        <div class="meta">
          <strong>${item.account || ""}</strong>
          <span class="muted">${(item.durationSeconds || 0).toFixed(1)}s · ${item.width || "?"}x${item.height || "?"} · score ${item.score}</span>
          <p class="caption">${item.bestCaption || ""}</p>
          <div class="tags">${tags}</div>
          <div class="actions">
            <button onclick="setLabel('${item.referenceId}', 'gold')">Gold</button>
            <button onclick="setLabel('${item.referenceId}', 'maybe')">Maybe</button>
            <button onclick="setLabel('${item.referenceId}', 'ignore')">Ignore</button>
            <button onclick="setLabel('${item.referenceId}', null)">Clear</button>
          </div>
          <details><summary>tags</summary>${tagButtons}</details>
          <code>${item.referenceId}</code>
        </div>
      </article>`;
    }
    async function load() {
      const data = await fetch(`/api/references?${qs()}`).then(r => r.json());
      document.getElementById("grid").innerHTML = data.items.map(card).join("");
      await loadStats();
    }
    async function loadBatch() {
      const data = await fetch("/api/review-batch?mode=balanced&target=300").then(r => r.json());
      document.getElementById("grid").innerHTML = data.items.map(card).join("");
      await loadStats();
    }
    function audioRow(item) {
      const tags = [...(item.moodTags || []), ...(item.bestContentTypes || [])].slice(0, 5).join(", ");
      const url = item.nativeAudioUrl ? `<a href="${item.nativeAudioUrl}" target="_blank" rel="noreferrer">${item.nativeAudioId || item.nativeAudioUrl}</a>` : (item.nativeAudioId || "");
      const reasons = item.reviewReasons ? `Review: ${item.reviewReasons.join(", ")}` : (item.safeUsageNotes || "");
      const expiry = item.expiresAt ? `expires ${item.expiresAt}` : "no expiry";
      return `<div class="audio-row">
        <div><strong>${esc(item.title)}</strong><div class="muted">${esc(item.artistName)}</div></div>
        <div>${esc(item.platform)}<div class="muted">${esc(item.trendStatus || "unknown")} · ${item.usageCount || 0} uses</div></div>
        <div>${url}</div>
        <div>${esc(tags)}<div class="muted">${esc(expiry)}</div><div class="muted">${esc(reasons)}</div></div>
        <div class="audio-actions">
          <button onclick="editAudio('${item.id}')">Edit</button>
          <button onclick="quickAudio('${item.id}', 'rising')">Rising</button>
          <button onclick="quickAudio('${item.id}', 'current')">Current</button>
          <button onclick="quickAudio('${item.id}', 'stale')">Stale</button>
          <button onclick="extendAudio('${item.id}', 7)">+7d</button>
          <button onclick="quickAudio('${item.id}', 'unknown')">Needs title</button>
        </div>
      </div>`;
    }
    function fillAudioForm(item) {
      document.getElementById("audioTitle").value = item.title || "";
      document.getElementById("audioArtist").value = item.artistName || "";
      document.getElementById("audioNativeId").value = item.nativeAudioId || "";
      document.getElementById("audioUrl").value = item.nativeAudioUrl || "";
      document.getElementById("audioTags").value = (item.moodTags || []).join(",");
      document.getElementById("audioContentTags").value = (item.bestContentTypes || []).join(",");
      document.getElementById("audioAccountTags").value = (item.accountFit || []).join(",");
      document.getElementById("audioUsage").value = item.usageCount || "";
      document.getElementById("audioExpires").value = item.expiresAt || "";
      document.getElementById("audioSafeNotes").value = item.safeUsageNotes || "";
      document.getElementById("audioTrend").value = item.trendStatus || "unknown";
      document.getElementById("audioForm").scrollIntoView({ behavior: "smooth", block: "center" });
    }
    function editAudio(id) {
      const item = AUDIO_ITEMS[id];
      if (item) fillAudioForm(item);
    }
    async function quickAudio(id, trendStatus) {
      const item = AUDIO_ITEMS[id];
      if (!item) return;
      await saveAudioPayload({ ...item, trendStatus });
      await loadAudio();
    }
    async function extendAudio(id, days) {
      const item = AUDIO_ITEMS[id];
      if (!item) return;
      const d = new Date();
      d.setDate(d.getDate() + days);
      await saveAudioPayload({ ...item, expiresAt: d.toISOString() });
      await loadAudio();
    }
    async function loadAudioHealth() {
      const platform = document.getElementById("audioPlatform").value;
      const h = await fetch(`/api/audio/health?platform=${encodeURIComponent(platform)}&limit=10`).then(r => r.json());
      document.getElementById("audioHealth").textContent = `${h.fresh || 0} fresh · ${h.unresolvedTitles || 0} need titles · ${h.stale || 0} stale · ${h.ready || 0} ready`;
    }
    async function loadAudio() {
      const p = new URLSearchParams({
        platform: document.getElementById("audioPlatform").value,
        freshOnly: document.getElementById("audioFresh").checked ? "true" : "false",
        needsReview: document.getElementById("audioNeedsReview").checked ? "true" : "false",
        limit: "25"
      });
      const data = await fetch(`/api/audio?${p.toString()}`).then(r => r.json());
      AUDIO_ITEMS = Object.fromEntries((data.items || []).map(item => [item.id, item]));
      document.getElementById("audioList").innerHTML = (data.items || []).map(audioRow).join("") || '<span class="muted">No audio records yet.</span>';
      await loadAudioHealth();
    }
    async function saveAudioPayload(item) {
      const payload = {
        title: item.title,
        artistName: item.artistName,
        platform: item.platform,
        nativeAudioId: item.nativeAudioId,
        nativeAudioUrl: item.nativeAudioUrl,
        moodTags: Array.isArray(item.moodTags) ? item.moodTags.join(",") : item.moodTags,
        bestContentTypes: Array.isArray(item.bestContentTypes) ? item.bestContentTypes.join(",") : item.bestContentTypes,
        accountFit: Array.isArray(item.accountFit) ? item.accountFit.join(",") : item.accountFit,
        trendStatus: item.trendStatus,
        usageCount: item.usageCount,
        expiresAt: item.expiresAt,
        safeUsageNotes: item.safeUsageNotes,
      };
      const existing = Object.values(AUDIO_ITEMS).find(item =>
        item.platform === payload.platform && item.nativeAudioId === payload.nativeAudioId
      );
      await fetch(existing ? "/api/audio/resolve" : "/api/audio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }
    async function saveAudio(event) {
      event.preventDefault();
      const payload = {
        title: document.getElementById("audioTitle").value,
        artistName: document.getElementById("audioArtist").value,
        platform: document.getElementById("audioPlatform").value,
        nativeAudioId: document.getElementById("audioNativeId").value,
        nativeAudioUrl: document.getElementById("audioUrl").value,
        moodTags: document.getElementById("audioTags").value,
        bestContentTypes: document.getElementById("audioContentTags").value,
        accountFit: document.getElementById("audioAccountTags").value,
        trendStatus: document.getElementById("audioTrend").value,
        usageCount: Number(document.getElementById("audioUsage").value || 0) || undefined,
        expiresAt: document.getElementById("audioExpires").value,
        safeUsageNotes: document.getElementById("audioSafeNotes").value,
      };
      await fetch("/api/audio/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      event.target.reset();
      await loadAudio();
    }
    document.getElementById("load").addEventListener("click", load);
    document.getElementById("batch").addEventListener("click", loadBatch);
    document.getElementById("queueReferenceAnalysis").addEventListener("click", () => intakePost("/api/reference-analysis/queue", {
      source: document.getElementById("intakeSource").value,
      platform: document.getElementById("intakePlatform").value,
      providerTarget: document.getElementById("intakeProvider").value || "gemini",
      accountProfile: document.getElementById("intakeAccountProfile").value || undefined,
      intakeProfile: document.getElementById("intakeProfile").value || "ig_ofm",
      mediaKinds: document.getElementById("intakeKinds").value.split(",").map(v => v.trim()).filter(Boolean),
      limit: Number(document.getElementById("intakeLimit").value || 10),
    }).catch(err => showIntake({ error: err.message })));
    document.getElementById("importReferenceAnalysis").addEventListener("click", () => intakePost("/api/reference-analysis/import", {
      input: document.getElementById("analysisImportPath").value,
    }).catch(err => showIntake({ error: err.message })));
    document.getElementById("generateVideoPrompts").addEventListener("click", () => intakePost("/api/video-prompts/generate", {
      tools: ["higgsfield_soul_image", "kling_3_video"],
      modelProfile: document.getElementById("intakeAccountProfile").value || undefined,
      limit: Number(document.getElementById("intakeLimit").value || 10),
      includePending: true,
    }).catch(err => showIntake({ error: err.message })));
    document.getElementById("loadVideoPrompts").addEventListener("click", async () => {
      const data = await fetch("/api/video-prompts?limit=100").then(r => r.json());
      showIntake(data);
    });
    document.getElementById("audioLoad").addEventListener("click", loadAudio);
    document.getElementById("audioForm").addEventListener("submit", saveAudio);
    loadAudio();
    load();
  </script>
</body>
</html>"""
