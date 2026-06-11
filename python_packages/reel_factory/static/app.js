let AUDIO_DISABLED = true;
let clips = []; let selectedStem = null; let pollInterval = null;
let campaigns = [];
let currentFilter = {hook: null, recipe: null, review: null};
let cockpitMode = "Create";
let cockpitModeTouched = false;
let dashboardSummary = null;
let currentHooks = []; let hookLibrary = []; let hookEmbedding = {model: "hash-v1", real_embeddings: false}; let previewSelection = [];
let visibleOutputs = [];
let outputDisplayLimit = 80;
let sourceClipQuery = "";
let lastAiGeneration = null;
let showSafeZones = false;
let hookEditorOpen = false;
let generationState = {status: "not started"};
let gridCropState = {open: false, frame_time: 0.25, boxes: [], grid_preset: {columns: 3, rows: 2}, render_captions: true};
let gridCropDrag = null;
let reviewModalState = null;
let creatorOsTabSwitching = false;
const REVIEW_REASONS = [
  "eyes_bad", "face_drift", "hands_bad", "pose_drift", "weak_body", "weak_cleavage",
  "bad_crop", "background_changed", "motion_bad", "caption_bad", "grid_bad",
  "kling_zoomed_panel", "identity_good", "pose_good", "caption_good", "hook_good"
];

async function loadConfig() {
  try {
    const cfg = await (await fetch("/api/config")).json();
    AUDIO_DISABLED = !cfg.audio_enabled;
    if (cfg.workers) document.getElementById("workers").value = String(cfg.workers);
    if (cfg.caption_renderer) document.getElementById("captionRenderer").value = cfg.caption_renderer;
    if (cfg.placement_mode) document.getElementById("placementMode").value = cfg.placement_mode;
    if (cfg.output_profile) document.getElementById("outputProfile").value = cfg.output_profile;
  } catch (_) {}
}

function toggleAdvancedControls() {
  document.getElementById("advancedControls")?.classList.toggle("hidden");
  document.activeElement?.blur?.();
}

async function loadDashboardSummary() {
  const campaign = document.getElementById("campaign")?.value || "";
  const account = document.getElementById("acct")?.value || "";
  const qs = new URLSearchParams();
  if (campaign) qs.set("campaign", campaign);
  if (account) qs.set("account", account);
  dashboardSummary = await fetch(`/api/dashboard/summary?${qs.toString()}`).then(r => r.json()).catch(() => null);
  const stamp = document.getElementById("lastUpdated");
  if (stamp) stamp.textContent = "Last updated: just now";
  renderCommandCenter();
}

function toneClass(tone) {
  return {
    green: "tone-green",
    amber: "tone-amber",
    red: "tone-red",
    blue: "tone-blue",
    gray: "tone-gray",
  }[tone || "gray"] || "tone-gray";
}

function qualityTone(level) {
  return {weak: "red", directional: "amber", usable: "blue", strong: "green"}[level || "weak"] || "gray";
}

function commandCard(label, value, sub, actionLabel, action) {
  return `
    <div class="command-card">
      <div class="text-[10px] uppercase tracking-wide text-gray-500">${label}</div>
      <div class="text-2xl font-semibold mt-1">${escHtml(value)}</div>
      <div class="text-xs text-gray-500 mt-1 min-h-[18px]">${escHtml(sub || "")}</div>
      <button class="tag mt-3" onclick="${action}">${escHtml(actionLabel)}</button>
    </div>
  `;
}

function pct(value, fallback = 0) {
  const n = Number(value);
  if (Number.isFinite(n)) return Math.max(0, Math.min(100, Math.round(n)));
  return fallback;
}

function renderStatusStrip() {
  const el = document.getElementById("statusStrip");
  if (!el) return;
  const cc = dashboardSummary?.command_center || {};
  const rec = cc.recommended_next_batch || {};
  const exceptions = Number(cc.needs_review || 0);
  const queue = clips.length;
  const renderHealth = queue ? pct(((queue - exceptions) / queue) * 100, 100) : 100;
  const fanout = generationState.fanout;
  const fanoutPanels = fanout?.panels || [];
  const fanoutFailures = fanoutPanels.filter(p => p.failed || String(p.status || "").includes("fail")).length;
  const fanoutSuccess = fanoutPanels.length ? pct(((fanoutPanels.length - fanoutFailures) / fanoutPanels.length) * 100, 100) : 94;
  el.innerHTML = `
    <div class="health-item" ${tooltipAttr("Overall operator status. Good means no urgent review blockers; Needs Review means outputs require human decisions.")}><b>Overall Health</b><span class="${exceptions ? 'warn' : 'good'}">${exceptions ? 'Needs Review' : 'Good'}</span></div>
    <div class="health-item" ${tooltipAttr("Rough rendering health based on how much of the current queue is blocked by review work.")}><b>Render Health</b><span class="${renderHealth < 80 ? 'warn' : 'good'}">${renderHealth}%</span></div>
    <div class="health-item" ${tooltipAttr("Whether the local Higgsfield CLI capability probe has confirmed authenticated image/video generation access.")}><b>Higgsfield Auth</b><span class="${generationState.capabilities?.validation?.ok ? 'good' : 'warn'}">${generationState.capabilities?.validation?.ok ? 'Connected' : 'Probe Required'}</span></div>
    <div class="health-item" ${tooltipAttr("Recent panel animation success signal. It updates when a fanout workflow has panel job results.")}><b>Fanout Success (7d)</b><span class="${fanoutSuccess < 80 ? 'warn' : 'good'}">${fanoutSuccess}%</span></div>
    <div class="health-item" ${tooltipAttr("Outputs or workflow states that need operator attention before they can safely move forward.")}><b>Exceptions</b><span class="${exceptions ? 'bad' : 'good'}">${exceptions}</span></div>
    <div class="health-item" ${tooltipAttr("Number of source clips currently available in the Reel Factory queue.")}><b>Queue</b><span class="${queue ? 'warn' : 'good'}">${queue}</span></div>
  `;
}

function renderProofRail() {
  const el = document.getElementById("proofRail");
  if (!el) return;
  const cc = dashboardSummary?.command_center || {};
  const exceptions = Number(cc.needs_review || 0);
  const ready = Number(cc.ready_to_post || 0);
  const metrics = Number(cc.needs_metrics || 0);
  const queue = clips.length;
  const renderHealth = queue ? pct(((queue - exceptions) / queue) * 100, 100) : 100;
  const fanout = generationState.fanout;
  const panels = fanout?.panels || [];
  const failed = panels.filter(p => p.failed || String(p.status || "").includes("fail")).length;
  const fanoutSuccess = panels.length ? pct(((panels.length - failed) / panels.length) * 100, 100) : 94;
  const account = currentAccount();
  el.innerHTML = `
    <div class="proof-card" ${tooltipAttr("Quick proof that rendering work is not silently piling up behind review or metrics blockers.", "left")}>
      <div class="proof-head"><h3>Render Health</h3><span class="proof-status">${renderHealth < 80 ? 'Watch' : 'Good'}</span></div>
      <div class="proof-metric-row">
        <div class="metric-ring" style="--pct:${renderHealth}"><div><b>${renderHealth}%</b><span>Healthy</span></div></div>
        <div class="proof-lines">
          <div class="proof-line"><span>Ready to post</span><b>${ready}</b></div>
          <div class="proof-line"><span>Needs review</span><b>${exceptions}</b></div>
          <div class="proof-line"><span>Needs metrics</span><b>${metrics}</b></div>
        </div>
      </div>
    </div>
    <div class="proof-card" ${tooltipAttr("Shows whether local Higgsfield generation access has been checked. Probe before spending on real jobs.", "left")}>
      <div class="proof-head"><h3>Higgsfield Auth</h3><span class="proof-status">${generationState.capabilities?.validation?.ok ? 'Connected' : 'Unknown'}</span></div>
      <div class="proof-lines">
        <div class="proof-line"><span>User</span><b>${escHtml(account || 'default')}</b></div>
        <div class="proof-line"><span>Status</span><b>${generationState.capabilities?.validation?.ok ? 'Authenticated' : 'Probe required'}</b></div>
        <div class="proof-line"><span>Video model</span><b>Kling 3.0</b></div>
      </div>
      <button class="btn btn-secondary w-full mt-3" onclick="probeHiggsfield()" ${tooltipAttr("Run the Higgsfield capability check. If auth is expired, the log will tell you to run hf auth login.", "left")}>Re-authenticate / probe</button>
    </div>
    <div class="proof-card" ${tooltipAttr("Tracks the grid-to-panel animation fanout path: crop panels, start video jobs, and record successes/failures.", "left")}>
      <div class="proof-head"><h3>Fanout Status (7d)</h3><span class="proof-status">${fanoutSuccess}%</span></div>
      <div class="proof-metric-row">
        <div class="metric-ring" style="--pct:${fanoutSuccess}"><div><b>${fanoutSuccess}%</b><span>Success</span></div></div>
        <div class="proof-lines">
          <div class="proof-line"><span>Success</span><b>${panels.length ? panels.length - failed : '-'}</b></div>
          <div class="proof-line"><span>Failed</span><b>${panels.length ? failed : '-'}</b></div>
          <div class="proof-line"><span>Total jobs</span><b>${panels.length || '-'}</b></div>
        </div>
      </div>
      <button class="btn btn-secondary w-full mt-3" onclick="fanoutPanels({dryRun:true})" ${tooltipAttr("Dry-run crop the current Soul grid and show planned panel jobs before spending on animations.", "left")}>View fanout history</button>
    </div>
    <div class="proof-card" ${tooltipAttr("Operator work queue. These are the things that should be resolved before scheduling or export.", "left")}>
      <div class="proof-head"><h3>Exceptions</h3><span class="status-pill ${exceptions ? 'tone-red' : 'tone-green'}">${exceptions}</span></div>
      ${exceptions ? `
        <div class="exception-row"><i></i><div><b>${exceptions} output${exceptions === 1 ? '' : 's'} need review</b><span>${selectedStem || 'source queue'} · operator action</span></div><span>›</span></div>
        <div class="exception-row warn"><i></i><div><b>${metrics} metric update${metrics === 1 ? '' : 's'} pending</b><span>import outcomes when posted</span></div><span>›</span></div>
      ` : `
        <div class="exception-row warn"><i></i><div><b>No active blocking exception</b><span>Keep proof gates before export</span></div><span>›</span></div>
      `}
      <button class="btn btn-secondary w-full mt-3" onclick="openCommandCenterAction('review')" ${tooltipAttr("Open Review mode and filter to outputs needing operator decisions.", "left")}>View all exceptions</button>
    </div>
  `;
}

function renderCommandCenter() {
  renderStatusStrip();
  renderProofRail();
  const el = document.getElementById("commandCenter");
  if (!el) return;
  const cc = dashboardSummary?.command_center || {};
  const rec = cc.recommended_next_batch || {};
  const quality = rec.data_quality || {};
  el.innerHTML = `
    <div class="card rounded-lg p-4">
      <div class="flex items-center justify-between mb-3">
        <div>
          <div class="text-xs uppercase tracking-wide text-gray-400">Today’s Command Center</div>
          <div class="text-xs text-gray-500 mt-1">what needs attention, what is ready, and what to do next</div>
        </div>
        <button class="tag" onclick="loadDashboardSummary()">refresh</button>
      </div>
      <div class="grid grid-cols-4 gap-3">
        ${commandCard("Needs Review", cc.needs_review ?? 0, "draft outputs need eyes", "open review", "openCommandCenterAction('review')")}
        ${commandCard("Ready to Post", cc.ready_to_post ?? 0, "approved or ready outputs", "show approved", "openCommandCenterAction('approved')")}
        ${commandCard("Needs Metrics", cc.needs_metrics ?? 0, "posted/approved without outcomes", "import metrics", "openCommandCenterAction('metrics')")}
        ${commandCard("Recommended Next Batch", rec.confidence || "low", quality.level ? `data ${quality.level}` : (rec.confidence_reason || "pick a campaign"), "next batch", "showNextBatch()")}
      </div>
    </div>
  `;
}

function openCommandCenterAction(kind) {
  if (kind === "review") { cockpitMode = "Review"; currentFilter.review = "draft"; renderDetail(); return; }
  if (kind === "approved") { cockpitMode = "Review"; currentFilter.review = "approved"; renderDetail(); return; }
  if (kind === "metrics") { cockpitMode = "Learn"; renderDetail().then(() => focusOutcomeImport()); return; }
}

function scrollToEl(id) {
  document.getElementById(id)?.scrollIntoView({behavior: "smooth", block: "center"});
}

function startVideoFlow() {
  scrollToEl("dz");
  document.getElementById("fileInput")?.click();
}

async function startFirstClip() {
  if (!clips.length) {
    startVideoFlow();
    return;
  }
  await selectClip(selectedStem || clips[0].stem);
}

async function autoGenerateHooks(stem = selectedStem, {force = false, silent = false} = {}) {
  if (!stem) return null;
  if (!silent) flash("creating captions...");
  const r = await fetch(`/api/clips/${encodeURIComponent(stem)}/auto-hooks`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({count: 8, force})
  });
  const j = await r.json();
  if (!j.ok) {
    flash(j.detail || "caption generation failed");
    return null;
  }
  if (!silent) flash(j.generated ? `created ${j.hook_count} captions` : `${j.hook_count} captions already ready`);
  await loadClips();
  return j;
}

async function autoCaptionSelected() {
  if (!clips.length && !selectedStem) {
    startVideoFlow();
    flash("add a video first, then I can create captions");
    return;
  }
  if (!selectedStem) {
    await selectClip(clips[0].stem);
  }
  await autoGenerateHooks(selectedStem, {force: true});
  cockpitMode = "Render";
  cockpitModeTouched = true;
  await renderDetail();
}

async function makeReelsNow() {
  if (!clips.length && !selectedStem) {
    startVideoFlow();
    flash("add a video first, then click Make reels now");
    return;
  }
  if (!selectedStem) await selectClip(clips[0].stem);
  await autoGenerateHooks(selectedStem, {silent: false});
  cockpitMode = "Render";
  cockpitModeTouched = true;
  await renderDetail();
  await startRun();
}

async function loadClips() {
  clips = await (await fetch("/api/clips?ensure_thumbs=true")).json();
  const el = document.getElementById("clips");
  const count = document.getElementById("clipCount");
  if (count) count.textContent = `${clips.length} clip${clips.length === 1 ? "" : "s"}`;
  const query = sourceClipQuery.trim().toLowerCase();
  const visibleClips = query
    ? clips.filter(c => `${c.stem} ${c.status?.status || ""} ${c.hook_preview || ""}`.toLowerCase().includes(query))
    : clips;
  renderCommandCenter();
  if (clips.length === 0) {
    el.innerHTML = '<p class="text-gray-600 text-sm italic">no clips yet</p>';
    return;
  }
  if (visibleClips.length === 0) {
    el.innerHTML = '<p class="text-gray-600 text-sm italic">no clips match this search</p>';
    return;
  }
  el.innerHTML = visibleClips.map(c => `
    <div class="clip-card ${selectedStem===c.stem?'selected':''}" onclick="selectClip('${c.stem}')" ${tooltipAttr("Open this source clip. The center workspace will show its video, captions, rendered outputs, and generation workflow.", "right")}>
      <div class="clip-thumb">
        ${c.thumb_url ? `<img src="${c.thumb_url}" class="w-full h-full object-cover">` : ''}
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between gap-2">
          <div class="font-medium text-sm truncate">${c.stem}</div>
        </div>
        <div class="text-xs text-gray-500 mt-0.5">${c.duration || "00:14"} · ${c.output_count} out</div>
        <span class="status-pill ${toneClass(c.status?.tone)} mt-1">${escHtml(c.status?.status || "Draft")}</span>
        ${c.preflight?.length ? `<div class="text-[10px] text-amber-300 mt-0.5">${c.preflight.length} warning${c.preflight.length===1?'':'s'}</div>` : ''}
        <div class="text-xs text-gray-400 mt-1 truncate">${escHtml(hookLabel(c.hook_preview || '(no hooks yet)').slice(0,40))}</div>
      </div>
    </div>
  `).join("");
}

function initSourceSearch() {
  const input = document.getElementById("clipSearch");
  if (!input) return;
  input.addEventListener("input", () => {
    sourceClipQuery = input.value || "";
    loadClips();
  });
}

async function loadAccounts() {
  const accts = await (await fetch("/api/accounts")).json();
  const sel = document.getElementById("acct");
  sel.innerHTML = '<option value="">no account</option>' +
    accts.map(a => `<option value="${a.id}">${a.id} · ${a.voice||'-'}</option>`).join("");
  sel.onchange = loadDashboardSummary;
}

async function loadCampaigns() {
  try {
    const data = await (await fetch("/api/campaigns")).json();
    campaigns = data.campaigns || [];
  } catch (_) {
    campaigns = [];
  }
  const sel = document.getElementById("campaign");
  if (!sel) return;
  sel.innerHTML = '<option value="">no campaign</option>' +
    campaigns.map(c => `<option value="${escHtml(c.name)}">${escHtml(c.name)} · ${escHtml(c.creator || c.creator_name || '')}</option>`).join("");
  sel.onchange = loadDashboardSummary;
}

async function createCampaignFromUi() {
  const name = prompt("Campaign name:");
  if (!name) return;
  const creator = prompt("Creator:", "Stacey") || "Stacey";
  const account = document.getElementById("acct")?.value || prompt("Account:", "default") || "default";
  const platform = prompt("Platform:", "instagram_reels") || "instagram_reels";
  const r = await fetch("/api/campaigns", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({name, creator, account, platform})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "campaign create failed");
  await loadCampaigns();
  document.getElementById("campaign").value = name;
  flash("campaign created");
}

async function showNextBatch() {
  const campaign = document.getElementById("campaign")?.value || "";
  if (!campaign) return flash("pick a campaign first");
  const r = await fetch(`/api/campaigns/${encodeURIComponent(campaign)}/next-batch?count=5&persist=true`);
  const j = await r.json();
  const lines = (j.ideas || []).map(i => {
    const rec = i.recommendation || {};
    const confidence = i.confidence || rec.confidence || "low";
    const reason = rec.confidence_reason ? ` (${rec.confidence_reason})` : "";
    const quality = rec.data_quality?.level || i.data_quality?.level;
    const qualityText = quality ? ` · data: ${quality}` : "";
    const pattern = rec.pattern ? ` · ${rec.pattern}` : "";
    return `#${i.index + 1}: ${i.prompt_focus} · ${i.recipe_hint}${pattern} · confidence: ${confidence}${qualityText}${reason}`;
  }).join("\\n");
  const warning = (j.ideas || []).find(i => i.low_data_warning)?.low_data_warning;
  const logged = j.decision_id ? `Decision logged: ${j.decision_id}\\n\\n` : "";
  alert(`${logged}${warning ? `${warning}\\n\\n` : ""}${lines || "No next-batch ideas yet"}`);
}

async function showCampaignLeaderboard() {
  const campaign = document.getElementById("campaign")?.value || "";
  if (!campaign) return flash("pick a campaign first");
  const r = await fetch(`/api/campaigns/${encodeURIComponent(campaign)}/leaderboard`);
  const j = await r.json();
  const recipes = (j.best_recipes || []).slice(0, 5).map(x => `${x.recipe}: ${x.score} (${x.count})`).join("\\n");
  const failures = (j.worst_failure_patterns || []).slice(0, 5).map(x => `${x.label}: ${x.count}`).join("\\n");
  alert(`Best recipes\\n${recipes || "-"}\\n\\nFailure patterns\\n${failures || "-"}`);
}

async function importOutcomesCsv() {
  const path = document.getElementById("outcomeCsvPath")?.value?.trim() || prompt("Outcome CSV path:");
  if (!path) return;
  const r = await fetch("/api/outcomes/import", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({path})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "outcome import failed");
  flash(`imported ${j.imported || 0} outcomes`);
  if (selectedStem) await renderDetail();
}

async function refreshWinnerDnaUi() {
  const j = await (await fetch("/api/winner-dna/refresh", {method: "POST"})).json();
  flash(`Winner DNA refreshed: ${j.rows || 0} rows`);
  if (selectedStem) await renderDetail();
}

async function analyzeSelectedReference() {
  if (!selectedStem) return flash("select a source clip first");
  const sourcePath = `00_source_videos/${selectedStem}.mp4`;
  const dryRun = !confirm("Call Grok vision for structured reference analysis? Cancel uses deterministic dry-run analysis.");
  const j = await (await fetch("/api/references/analyze", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({reference: sourcePath, dry_run: dryRun})
  })).json();
  if (!j.ok) return flash(j.detail || j.error || "reference analysis failed");
  setGenerationState({reference_analysis: j.analysis, reference_analysis_path: j.path});
  genLog(j);
  flash("reference analysis saved");
  await renderDetail();
}

function escHtml(s) { return String(s == null ? "" : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escJs(s) { return String(s || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\n/g, "\\n").replace(/\r/g, ""); }
function tooltipAttr(text, placement = "") {
  const safe = escHtml(text);
  const place = placement ? ` data-tooltip-placement="${escHtml(placement)}"` : "";
  return `data-tooltip="${safe}" title="${safe}" aria-label="${safe}"${place}`;
}
function configureCreatorTabs(activeApp) {
  const host = window.location.hostname || "localhost";
  const protocol = window.location.protocol || "http:";
  const campaignTab = document.getElementById("campaignFactoryTab");
  const reelTab = document.getElementById("reelFactoryTab");
  if (campaignTab) {
    campaignTab.href = `${protocol}//${host}:8877/`;
    campaignTab.classList.toggle("active", activeApp === "campaign");
    campaignTab.addEventListener("click", () => { creatorOsTabSwitching = true; });
  }
  if (reelTab) {
    reelTab.href = `${protocol}//${host}:8765/`;
    reelTab.classList.toggle("active", activeApp === "reel");
    reelTab.addEventListener("click", () => { creatorOsTabSwitching = true; });
  }
}
function safeZoneOverlayHtml(zones) {
  const top = zones?.top_pct ?? 14.6;
  const bottom = zones?.bottom_pct ?? 25.0;
  const left = zones?.left_pct ?? 5.0;
  const right = zones?.right_pct ?? 5.0;
  return `
    <div class="safe-zone-overlay" aria-hidden="true">
      <div class="safe-zone-band safe-zone-top" style="height:${top}%"><span>safe zone</span></div>
      <div class="safe-zone-band safe-zone-bottom" style="height:${bottom}%"><span>caption/action zone</span></div>
      <div class="safe-zone-side safe-zone-left" style="width:${left}%"></div>
      <div class="safe-zone-side safe-zone-right" style="width:${right}%"></div>
    </div>
  `;
}
function safeZoneWrap(inner, zones, extraClass = "") {
  if (!showSafeZones) return inner;
  return `<div class="safe-zone-frame ${extraClass}">${inner}${safeZoneOverlayHtml(zones)}</div>`;
}
function toggleSafeZones() {
  showSafeZones = !showSafeZones;
  renderDetail();
}
function aiQcTags(record) {
  const warnings = record?.warnings || [];
  if (!warnings.length) return "";
  return warnings.map(w => `<span class="tag bg-amber-950 text-amber-200" title="AI visual QC warning">${escHtml(w.replace(/_/g, " "))}</span>`).join("");
}
function readinessTag(record) {
  if (!record) return "";
  const cls = record.status === "ready" ? "bg-emerald-900 text-emerald-100" : (record.status === "not_ready" ? "bg-red-950 text-red-200" : "bg-amber-950 text-amber-200");
  const title = (record.warnings || []).join(", ");
  return `<span class="tag ${cls}" title="${escHtml(title)}">${escHtml(record.status)} ${record.score ?? ""}</span>`;
}
function riskLight(label, level, title = "") {
  const tone = {ready: "green", pass: "green", low: "green", usable: "blue", strong: "green", warn: "amber", medium: "amber", directional: "amber", weak: "red", high: "red", not_ready: "red", fail: "red"}[level || "low"] || "gray";
  return `<span class="risk-light ${toneClass(tone)}" title="${escHtml(title)}">${escHtml(label)}: ${escHtml(level || "low")}</span>`;
}
function trustLabel(quality) {
  const level = quality?.level || "weak";
  const text = {weak: "Weak Data", directional: "Directional", usable: "Usable", strong: "Strong"}[level] || "Weak Data";
  const reason = (quality?.reasons || [])[0] || "";
  return `<div class="trust-label ${toneClass(qualityTone(level))}"><b>${escHtml(text)}</b><span>${escHtml(reason)}</span></div>`;
}
function whyDetails(label, lines) {
  return `<details class="why-drawer"><summary>Why?</summary><div>${(lines || []).filter(Boolean).map(x => `<p>${escHtml(x)}</p>`).join("") || `<p>No explanation available yet.</p>`}</div></details>`;
}
function clipStatusForData(data) {
  const status = clips.find(c => c.stem === selectedStem)?.status;
  if (status) return status;
  const states = (data.outputs || []).map(o => o.review_state);
  const approved = states.filter(s => s === "approved").length;
  const draft = states.filter(s => s === "draft").length;
  if (approved) return {status: "Needs Metrics", tone: "amber"};
  if (draft) return {status: "Needs Review", tone: "amber"};
  return {status: data.outputs?.length ? "Approved" : ((data.sidecar?.hooks || []).length ? "Ready to Render" : "Needs Captions"), tone: data.outputs?.length ? "green" : "amber"};
}
function nextActionForClip(data) {
  const fromList = clips.find(c => c.stem === selectedStem)?.next_action;
  if (fromList) return fromList;
  const status = clipStatusForData(data).status;
  return {
    "Needs Captions": {label: "Auto-caption + render", action: "autoCaptionAndRender()", mode: "Render"},
    "Needs Grok": {label: "Build prompt preview", action: "generateGrokPrompt()", mode: "Create"},
    "Needs Soul": {label: "Create Soul image", action: "createSoulImage()", mode: "Create"},
    "Needs Kling": {label: "Create Kling video", action: "createKlingVideo()", mode: "Create"},
    "Ready to Render": {label: "Run pipeline", action: "startRun()", mode: "Render"},
    "Needs Review": {label: "Review outputs", action: "setCockpitMode('Review')", mode: "Review"},
    "Needs Metrics": {label: "Import metrics", action: "focusOutcomeImport()", mode: "Learn"},
  }[status] || {label: "Open create mode", action: "setCockpitMode('Create')", mode: "Create"};
}

function readinessRow(label, value, tone, tooltip) {
  return `
    <div class="readiness-row" ${tooltipAttr(tooltip || `${label}: ${value}`)}>
      <span><i class="${toneClass(tone)}"></i>${escHtml(label)}</span>
      <b class="${toneClass(tone)}">${escHtml(value)}</b>
    </div>
  `;
}

function fanoutPanelCount() {
  const fanout = generationState.fanout || {};
  const crops = generationState.panel_crops || fanout.cropManifest?.panelCrops || [];
  const panels = fanout.panels || [];
  return Number(fanout.detectedPanelCount || panels.length || crops.length || 0);
}

function operatorReadinessFor(data, clipStatus, fallbackNextAction, dataQuality) {
  const campaign = currentCampaign();
  const account = currentAccount();
  const validation = generationState.capabilities?.validation || {};
  const authReady = !!validation.ok;
  const promptReady = !!(generationState.prompt_path || generationState.prompt);
  const gridReady = !!generationState.local_image_path;
  const cropCount = fanoutPanelCount();
  const cropReady = cropCount > 0;
  const animationDone = generationState.fanout?.dry_run === false;
  const confidence = generationState.fanout?.gridDetection?.confidence || generationState.fanout?.cropManifest?.confidence || "";
  const confidenceNeedsReview = cropReady && confidence && confidence !== "high" && confidence !== "operator_override";
  const outputCount = data.outputs?.length || 0;
  const rows = [
    readinessRow("Campaign", campaign || "Pick campaign", campaign ? "green" : "amber", "Generation lineage should always be tied to a campaign before creating paid assets."),
    readinessRow("Source clip", selectedStem || "Select clip", selectedStem ? "green" : "amber", "The selected source clip provides reference context and keeps generated assets traceable."),
    readinessRow("Higgsfield auth", authReady ? "Connected" : "Probe required", authReady ? "green" : "amber", "Run the capability probe before spending. If auth is expired, the log will point to hf auth login."),
    readinessRow("Prompt", promptReady ? "Ready" : "Build", promptReady ? "green" : "amber", "The v1 prompt contract contains one Higgsfield grid prompt and one shared Kling motion prompt."),
    readinessRow("Grid image", gridReady ? "Ready" : "Needed", gridReady ? "green" : "amber", "One Soul grid image is the source for smart panel detection and cropping."),
    readinessRow("Panel crops", cropReady ? `${cropCount} detected` : "Not cropped", confidenceNeedsReview ? "amber" : (cropReady ? "green" : "amber"), "Cropped panels become the individual start images for Kling/Higgsfield animations."),
    readinessRow("Review outputs", outputCount ? `${outputCount} local` : "None yet", outputCount ? "green" : "gray", "Rendered local variants appear here before Campaign Factory review/export decisions."),
  ];
  let action = fallbackNextAction;
  let headline = fallbackNextAction.label;
  let sub = `${clipStatus.status} · ${fallbackNextAction.mode || cockpitMode}`;
  if (!campaign) {
    headline = "Pick a campaign before paid generation";
    sub = "Keeps every generated asset traceable to Campaign Factory.";
    action = {label: "Focus campaign", action: "document.getElementById('campaign')?.focus()", mode: "Setup"};
  } else if (!authReady) {
    headline = "Probe Higgsfield before spending";
    sub = "Confirms auth, Soul model, Kling model, and identity flag support.";
    action = {label: "Probe Higgsfield", action: "probeHiggsfield()", mode: "Setup"};
  } else if (!promptReady) {
    headline = "Build the prompt contract preview";
    sub = "Prepare the v1 prompt contract from campaign and source reference context.";
    action = {label: "Build prompt preview", action: "generateGrokPrompt()", mode: "Create"};
  } else if (!gridReady) {
    headline = "Create grid + animate panels";
    sub = "Starts with one paid Soul grid, then pauses before paid panel animations.";
    action = {label: "Start Full Workflow", action: "createGridFanoutWorkflow()", mode: "Create"};
  } else if (!cropReady) {
    headline = "Crop the Soul grid into panels";
    sub = "Dry-run only. Shows panel thumbnails before animation spend.";
    action = {label: "Crop existing grid", action: "fanoutPanels({dryRun:true})", mode: "Create"};
  } else if (generationState.fanout?.dry_run) {
    headline = confidenceNeedsReview ? "Review panel crops before spend" : `Confirm ${cropCount} panel animations`;
    sub = confidenceNeedsReview
      ? "Crop detection was not high-confidence, so inspect the thumbnails first."
      : "Existing confirmation dialog will show the paid animation count again.";
    action = {label: confidenceNeedsReview ? "Review crops" : `Animate ${cropCount} panels`, action: confidenceNeedsReview ? "setCockpitMode('Create')" : "confirmAndRunPanelAnimations()", mode: "Create"};
  } else if (animationDone) {
    headline = "Inspect generated panel videos";
    sub = "Successful jobs are recorded in lineage; review failures before moving on.";
    action = {label: "Open Review", action: "setCockpitMode('Review')", mode: "Review"};
  }
  const modelText = authReady
    ? `${validation.imageModel || "Soul"} → ${validation.videoModel || "Kling"}`
    : "run capability probe";
  const costText = gridReady
    ? (cropReady ? `${cropCount} paid video job${cropCount === 1 ? "" : "s"} after confirmation` : "video job count appears after crop")
    : `1 paid Soul image + detected panel videos after confirmation`;
  return `
    <div class="operator-readiness-card">
      <div class="readiness-main">
        <div class="next-kicker">What should I do next?</div>
        <div class="next-title">${escHtml(headline)}</div>
        <div class="next-sub">${escHtml(sub)}</div>
        <div class="readiness-meta">
          <span ${tooltipAttr("Resolved generation models from the latest Higgsfield capability probe.")}>${escHtml(modelText)}</span>
          <span ${tooltipAttr("Paid action summary. Existing dialogs still require confirmation before spend.")}>${escHtml(costText)}</span>
          <span ${tooltipAttr("Current account context used for dashboard summary and generation requests.")}>${escHtml(account || "default")}</span>
        </div>
      </div>
      <div class="readiness-side">
        ${trustLabel(dataQuality)}
        <button class="btn text-xs" onclick="${action.action}" ${tooltipAttr("Recommended next safe operator action based on current Reel Factory state.")}>${escHtml(action.label)}</button>
      </div>
      <div class="readiness-grid">${rows.join("")}</div>
    </div>
  `;
}

async function autoCaptionAndRender() {
  await makeReelsNow();
}

function defaultModeFor(data, status) {
  return "Create";
}
function modeTabs() {
  const tips = {
    Create: "Generate new assets: make a Soul grid, crop panels, and animate each panel through Higgsfield/Kling.",
    Render: "Render local caption/recipe variants from the selected source clip with ffmpeg.",
    Review: "Inspect rendered outputs, approve/reject them, rate quality, and queue safe candidates for later publishing workflows.",
    Learn: "Import outcomes and inspect what is actually working so recommendations improve from real results."
  };
  return `<div class="mode-tabs">${["Create","Render","Review","Learn"].map(m => `<button class="${cockpitMode===m?'active':''}" onclick="setCockpitMode('${m}')" ${tooltipAttr(tips[m])}>${m}</button>`).join("")}</div>`;
}
function setCockpitMode(mode) {
  cockpitMode = mode;
  cockpitModeTouched = true;
  renderDetail();
}
function focusOutcomeImport() {
  const el = document.getElementById("outcomeCsvPath");
  if (el) {
    el.focus();
    el.scrollIntoView({behavior: "smooth", block: "center"});
  } else {
    flash("open Learn mode to import metrics");
  }
}
function setGenerationState(patch) {
  generationState = {...generationState, ...patch};
  renderGenerationState();
}
function generationStatusTag() {
  const label = generationState.status || "not started";
  const cls = label.includes("ready") || label.includes("selected") || label === "downloaded" || label === "rendered"
    ? "tone-green"
    : (label.includes("failed") ? "tone-red" : "tone-amber");
  return `<span id="genStatus" class="tag ${cls}">${escHtml(label)}</span>`;
}

function panelAnimationStatusHtml(panels) {
  if (!panels.length) return "";
  return `
    <div class="panel-animation-table">
      <h3>Panel Animation Status</h3>
      <div class="panel-animation-row header">
        <span>Panel</span><span>Start Image</span><span>Model</span><span>Job ID</span><span>Status</span><span>Result</span>
      </div>
      ${panels.slice(0, 12).map(p => {
        const url = p.startImageUrl || "";
        const jobId = p.videoJobId || p.job_id || p.jobId || "-";
        const result = p.videoResultUrl || p.result_url || "";
        return `
          <div class="panel-animation-row">
            <span>${escHtml(p.panel || "-")}</span>
            <span>${url ? `<img src="${url}?t=${Date.now()}" alt="panel ${escHtml(p.panel || '')}">` : "-"}</span>
            <span>Kling 3.0</span>
            <span class="truncate">${escHtml(jobId)}</span>
            <span class="${String(p.status || "").includes("fail") ? "tone-red" : "tone-green"}">${escHtml(p.status || "planned")}</span>
            <span>${result ? `<a href="${result}" target="_blank">View</a>` : "-"}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function fanoutHtml() {
  const fanout = generationState.fanout;
  const crops = generationState.panel_crops || fanout?.cropManifest?.panelCrops || [];
  if (!fanout && !crops.length) return "";
  const grid = fanout?.gridDetection?.gridPreset || fanout?.cropManifest?.gridPreset || {};
  const confidence = fanout?.gridDetection?.confidence || fanout?.cropManifest?.confidence || "unknown";
  const seam = fanout?.gridDetection?.seamDetection || fanout?.cropManifest?.seamDetection || {};
  const seamConfidence = seam.confidence || "unknown";
  const seamLabel = seam.method ? ` · seams ${escHtml(seamConfidence)}${seam.snapped ? " snapped" : " fallback"}` : "";
  const panels = fanout?.panels || crops.map(p => ({
    panel: p.panel,
    label: p.label,
    status: "cropped",
    startImagePath: p.startImagePath || p.path,
    startImageUrl: p.startImageUrl || p.url
  }));
  return `
    <div class="fanout-box mt-3">
      <div class="flex items-center justify-between gap-3 mb-2">
        <div>
          <div class="text-xs font-semibold text-gray-900">Detected grid: ${grid.columns || "?"} columns × ${grid.rows || "?"} rows (${panels.length || crops.length} panels)</div>
          <div class="text-xs text-gray-400 mt-1"><span class="status-pill ${confidence === "high" ? "tone-green" : "tone-amber"}">${escHtml(confidence)} confidence${seamLabel}</span></div>
        </div>
        <div class="flex gap-2">
          <button class="tag" onclick="fanoutPanels({dryRun:true})" ${tooltipAttr("Run panel detection again and refresh the cropped start-image thumbnails.")}>recrop</button>
          ${fanout?.dry_run ? `<button class="btn" onclick="confirmAndRunPanelAnimations()" ${tooltipAttr("Create one paid animation job per detected panel after confirmation.")}>Animate ${fanout.detectedPanelCount || panels.length} panels</button>` : ""}
        </div>
      </div>
      <div class="fanout-grid">
        ${panels.map(p => {
          const url = p.startImageUrl || "";
          const status = p.status || "cropped";
          const result = p.videoResultUrl ? "result ready" : "";
          return `<button class="fanout-cell" onclick="useFanoutPanel(${Number(p.panel) || 0})" ${tooltipAttr(`Use panel ${Number(p.panel) || ""} as the selected start image. ${p.startImagePath || ""}`)}>
            ${url ? `<img src="${url}?t=${Date.now()}" alt="panel ${Number(p.panel) || ''}">` : `<span class="fanout-empty">panel ${Number(p.panel) || ''}</span>`}
            <b>${escHtml(p.label || `panel ${p.panel}`)}</b>
            <small>${escHtml(status)} ${result}</small>
          </button>`;
        }).join("")}
      </div>
      ${panelAnimationStatusHtml(panels)}
    </div>
  `;
}
function panelPickerHtml() {
  const six = generationState.six_pack_urls || {};
  const sixKeys = Object.keys(six).sort();
  const sixPack = sixKeys.length ? `
    <div class="mt-3">
      <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Six-pack fallback images</div>
      <div class="grid grid-cols-3 gap-2">
        ${sixKeys.map(k => `<button class="six-pack-cell" onclick="selectSixPackVariation('${k}')" title="Use ${escHtml(k)}"><img src="${six[k]}?t=${Date.now()}" alt="${escHtml(k)}"><span>${escHtml(k.replace('variation_', 'v'))}</span></button>`).join("")}
      </div>
    </div>
  ` : "";
  const fanout = fanoutHtml();
  if (!generationState.local_image_url) return `${fanout}${sixPack}`;
  const cells = [1,2,3,4,5,6].map(n => `<button class="panel-cell" style="grid-area:cell${n}" onclick="selectPanel('${n}')" title="Use panel ${n}">${n}</button>`).join("");
  return `
    <div class="mt-3 grid grid-cols-2 gap-3">
      <div>
        <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Soul image / panel picker</div>
        ${generationState.grid_status ? `<div class="text-[10px] text-amber-300 mb-1">grid: ${escHtml(generationState.grid_status)}</div>` : ""}
        <div class="panel-picker">
          <img src="${generationState.local_image_url}?t=${Date.now()}" alt="Soul image">
          <div class="panel-grid">${cells}</div>
        </div>
        <button class="tag mt-2" onclick="selectPanel('full_image')" ${tooltipAttr("Use the entire Soul image as the animation start image instead of cropping one panel.")}>use full image</button>
      </div>
      <div>
        <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Selected start image</div>
        ${generationState.start_image_url ? `<img class="start-preview" src="${generationState.start_image_url}?t=${Date.now()}" alt="Selected start image">` : `<div class="start-preview empty">needs panel</div>`}
      </div>
    </div>
    ${fanout}
    ${sixPack}
  `;
}
function intelligencePanel(outcomes, dna) {
  const top = outcomes?.top || [];
  const totals = outcomes?.totals || {};
  const dnaRows = dna?.winner_dna || [];
  const sceneRows = dna?.top_scenes || [];
  const poseRows = dna?.top_poses || [];
  const motionRows = dna?.top_motions || [];
  const outfitRows = dna?.top_outfits || [];
  const comboRows = dna?.best_creator_scene_combinations || [];
  const roiRows = dna?.best_roi_assets || [];
  const rejects = dna?.worst_rejection_patterns || [];
  const warning = dna?.low_data_warning || null;
  const quality = dna?.data_quality || {};
  const baseline = dna?.baseline_report || {};
  const fatigue = dna?.account_fatigue || {};
  const featureRows = (label, rows) => `
    <div>
      <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">${label}</div>
      ${(rows.slice(0,4).map(row => `<div class="intelligence-row"><span>${escHtml(row.feature_value || `${row.creator}/${row.scene}`)}</span><b>${Math.round(row.avg_winner_score || 0)}</b></div>`).join("")) || `<p class="text-gray-500">No data yet.</p>`}
    </div>
  `;
  return `
    <div class="card rounded-lg p-4 mb-4">
      <div class="flex items-center justify-between gap-3 mb-3">
        <div>
          <div class="text-xs uppercase tracking-wide text-gray-400">Intelligence Layer</div>
          <div class="text-xs text-gray-500 mt-1">${outcomes?.count || 0} outcomes · ${totals.views || 0} views · ${totals.shares || 0} shares · ${totals.saves || 0} saves</div>
        </div>
        <div class="flex flex-wrap gap-2 text-xs">
          <input id="outcomeCsvPath" class="rounded px-2 py-1 text-xs w-64" placeholder="metrics.csv or /full/path/outcomes.csv">
          <button class="tag" onclick="importOutcomesCsv()">import outcomes CSV</button>
          <button class="tag" onclick="analyzeSelectedReference()">analyze reference</button>
          <button class="tag" onclick="refreshWinnerDnaUi()">refresh Winner DNA</button>
        </div>
      </div>
      ${warning ? `<div class="mb-3 rounded border border-amber-700 bg-amber-950/40 px-3 py-2 text-xs text-amber-100">${escHtml(warning)}</div>` : ""}
      <div class="grid grid-cols-3 gap-3 text-xs mb-3">
        <div class="rounded border border-gray-800 p-3">
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">baseline vs recommended</div>
          <div class="text-gray-300">manual ${Math.round(baseline.manual?.avg_winner_score || 0)} · recommended ${Math.round(baseline.recommended?.avg_winner_score || 0)}</div>
          <div class="text-gray-500 mt-1">lift ${baseline.lift_percent ?? "-"}% · ${escHtml(baseline.confidence?.level || "low")}</div>
        </div>
        <div class="rounded border border-gray-800 p-3">
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">account fatigue</div>
          <div class="text-gray-300">${escHtml(fatigue.level || "low")} · ${fatigue.score ?? 0}</div>
          <div class="text-gray-500 mt-1 truncate">${escHtml((fatigue.overused_patterns || [])[0]?.feature_value || "no repeated pattern yet")}</div>
        </div>
        <div class="rounded border border-gray-800 p-3" title="${escHtml((quality.reasons || []).join("; "))}">
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">data quality</div>
          <div class="text-gray-300">${escHtml(quality.level || "weak")} · ${quality.score ?? 0}/100</div>
          <div class="text-gray-500 mt-1 truncate">${escHtml((quality.reasons || ["no data quality report yet"])[0])}</div>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-3 text-xs">
        <div>
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">top performers</div>
          ${(top.slice(0,5).map(row => `<button class="intelligence-row" onclick="showSimilar('${escJs(row.output_path || row.filename)}')"><span class="truncate">${escHtml(row.filename)}</span><b>${Math.round(row.winner_score || 0)}</b></button>`).join("")) || `<p class="text-gray-500">No outcomes yet.</p>`}
        </div>
        <div>
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Winner DNA</div>
          ${(dnaRows.slice(0,8).map(row => `<div class="intelligence-row" title="${escHtml(row.confidence?.reason || '')}"><span>${escHtml(row.feature_key)}: ${escHtml(row.feature_value)} · ${escHtml(row.confidence?.level || 'low')}</span><b>${Math.round(row.avg_winner_score)}</b></div>`).join("")) || `<p class="text-gray-500">Refresh after importing outcomes.</p>`}
        </div>
        <div>
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">rejection patterns</div>
          ${(rejects.slice(0,8).map(row => `<div class="intelligence-row"><span>${escHtml(row.label)}</span><b>${row.count}</b></div>`).join("")) || `<p class="text-gray-500">No reject/maybe reasons yet.</p>`}
        </div>
      </div>
      <div class="grid grid-cols-3 gap-3 text-xs mt-3">
        ${featureRows("top scenes", sceneRows)}
        ${featureRows("top poses", poseRows)}
        ${featureRows("top motions", motionRows)}
      </div>
      <div class="grid grid-cols-3 gap-3 text-xs mt-3">
        ${featureRows("top outfits", outfitRows)}
        <div>
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">creator/scene combos</div>
          ${(comboRows.slice(0,4).map(row => `<div class="intelligence-row"><span>${escHtml(row.creator)} / ${escHtml(row.scene)}</span><b>${Math.round(row.avg_winner_score || 0)}</b></div>`).join("")) || `<p class="text-gray-500">No data yet.</p>`}
        </div>
        <div>
          <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">best ROI assets</div>
          ${(roiRows.slice(0,4).map(row => `<div class="intelligence-row"><span class="truncate">${escHtml((row.output_path || row.entity_id || "").split("/").pop())}</span><b>${row.winner_score_per_cost ?? "-"}</b></div>`).join("")) || `<p class="text-gray-500">No cost data yet.</p>`}
        </div>
      </div>
      ${generationState.reference_analysis ? `<pre class="mt-3 p-2 rounded bg-black/30 text-[10px] text-gray-400 whitespace-pre-wrap">${escHtml(JSON.stringify(generationState.reference_analysis, null, 2))}</pre>` : ""}
    </div>
  `;
}
function reviewReasonModalHtml() {
  if (!reviewModalState) return "";
  const positive = REVIEW_REASONS.filter(r => r.endsWith("_good"));
  const negative = REVIEW_REASONS.filter(r => !r.endsWith("_good"));
  const reasons = reviewModalState.decision === "approve" ? positive : negative;
  const selected = new Set(reviewModalState.secondary || []);
  return `
    <div class="modal-backdrop" onclick="closeReviewReasonModal(event)">
      <div class="review-modal" onclick="event.stopPropagation()">
        <div class="flex items-center justify-between gap-3 mb-3">
          <div>
            <div class="text-xs uppercase tracking-wide text-gray-400">${escHtml(reviewModalState.decision)} review</div>
            <div class="text-xs text-gray-500 mt-1">${escHtml(reviewModalState.filename)}</div>
          </div>
          <button class="tag" onclick="reviewModalState=null; renderDetail()">close</button>
        </div>
        <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-2">primary reason</div>
        <div class="reason-grid mb-3">
          ${reasons.map(r => `<button class="reason-pill ${reviewModalState.primary === r ? 'selected' : ''}" onclick="setReviewPrimary('${r}')">${escHtml(r.replace(/_/g, " "))}</button>`).join("")}
        </div>
        <div class="text-[10px] uppercase tracking-wide text-gray-500 mb-2">secondary reasons</div>
        <div class="reason-grid mb-3">
          ${reasons.map(r => `<button class="reason-pill ${selected.has(r) ? 'selected' : ''}" onclick="toggleReviewSecondary('${r}')">${escHtml(r.replace(/_/g, " "))}</button>`).join("")}
        </div>
        <textarea id="reviewNotes" class="w-full rounded p-2 text-xs h-20" placeholder="optional notes">${escHtml(reviewModalState.notes || "")}</textarea>
        <div class="flex justify-end gap-2 mt-3">
          <button class="tag" onclick="reviewModalState=null; renderDetail()">cancel</button>
          <button class="tag bg-indigo-700 text-white" onclick="saveReviewReason()">save review</button>
        </div>
      </div>
    </div>
  `;
}
function audioIntentSelect(o) {
  const modes = ["", "native_trending_audio", "original_voiceover", "licensed_music", "silent_by_design", "platform_auto_music"];
  const current = o.audio_intent?.mode || "";
  return `<select class="rounded px-2 py-1 text-[11px] w-full" onchange="setAudioIntent('${o.name}', this.value)">
    ${modes.map(m => `<option value="${m}" ${m===current?'selected':''}>${m || 'audio intent...'}</option>`).join("")}
  </select>`;
}
function generationPanel(data) {
  const campaign = document.getElementById("campaign")?.value || "";
  const promptPath = generationState.prompt_path || "";
  const stem = generationState.stem || "";
  const imagePath = generationState.local_image_path || "";
  const startImage = generationState.start_image_path || "";
  const preview = generationState.prompt ? JSON.stringify(generationState.prompt, null, 2) : "";
  const gridLayout = generationState.grid_layout || "3x2";
  return `
    <div class="card workflow-card mb-4">
      <div class="workflow-head">
        <div>
          <div class="text-xs uppercase tracking-wide text-gray-400">Generate Workflow</div>
          <h3 class="mt-2">Create grid + animate panels</h3>
          <div class="workflow-subtitle">1 Soul grid image → smart crop panels → animate each panel.</div>
        </div>
        <div class="workflow-actions">
          <button class="btn btn-secondary" onclick="fanoutPanels({dryRun:true})" ${tooltipAttr("Dry-run only. Uses the current Soul grid image path, detects panels, and shows cropped thumbnails before any animation jobs are created.")}>Crop existing grid</button>
          <button class="btn" onclick="createGridFanoutWorkflow()" ${tooltipAttr("Main workflow. Creates one paid Soul grid if needed, crops panels, then asks for confirmation before paid panel animations.")}>Start Full Workflow</button>
        </div>
      </div>
      <div class="workflow-body">
      <div class="flex gap-2 mb-3">${generationStatusTag()}<span class="tag">${campaign ? escHtml(campaign) : 'pick campaign'}</span></div>
      <div class="workflow-form text-xs">
        <input id="genStem" class="rounded px-2 py-2" placeholder="new clip stem" value="${escHtml(stem)}">
        <input id="genPromptPath" class="rounded px-2 py-2" placeholder="prompts/...json" value="${escHtml(promptPath)}">
        <button class="tag" onclick="fillNextClipId()" ${tooltipAttr("Reserve the next generated clip stem and matching prompt JSON path.")}>next id</button>
        <input id="genImagePath" class="rounded px-2 py-2" placeholder="Soul image local path" value="${escHtml(imagePath)}">
        <select id="genGridLayout" class="rounded px-2 py-2" ${tooltipAttr("Controls what layout Grok asks Higgsfield for in the final prompt. This changes prompt wording only, not the reference image or Soul ID.")}>
          ${[
            ["single", "1 image · best detail"],
            ["2x2", "2x2 · 4 panels"],
            ["3x2", "3x2 · 6 panels max"],
            ["4x2", "4x2 · quality risk"],
            ["2x4", "2x4 · quality risk"],
            ["3x3", "3x3 · quality risk"]
          ].map(([value, label]) => `<option value="${value}" ${gridLayout === value ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        <div class="full-span text-[11px] text-amber-700">Use 1 image, 2x2, or 3x2 for quality. 8+ panel grids often reduce per-panel detail and can return 10-panel layouts.</div>
        <input id="genStartImage" class="rounded px-2 py-2 full-span" placeholder="selected panel/start image path" value="${escHtml(startImage)}">
      </div>
      <div class="workflow-steps">
        <div class="workflow-step" ${tooltipAttr("Step 1 creates or uses a Higgsfield Soul grid image. This is the source image for panel cropping.")}><i>1</i><div><b>Soul Grid Image</b><span>${generationState.local_image_path ? "Ready" : "Pending"}</span></div></div>
        <div class="workflow-step ${generationState.panel_crops?.length ? "" : "pending"}" ${tooltipAttr("Step 2 detects the grid shape, removes padding, and saves each panel as its own start image.")}><i>2</i><div><b>Crop Panels (${generationState.panel_crops?.length || "2x3"})</b><span>${generationState.panel_crops?.length ? "Ready" : "Pending"}</span></div></div>
        <div class="workflow-step ${generationState.fanout?.dry_run === false ? "" : "pending"}" ${tooltipAttr("Step 3 creates one animation job per cropped panel after operator confirmation.")}><i>3</i><div><b>Animate Panels</b><span>${generationState.fanout?.dry_run === false ? "Running / ready" : "Pending"}</span></div></div>
      </div>
      <textarea id="genPromptPreview" class="prompt-preview w-full rounded p-2 text-xs" placeholder="prompt JSON preview appears here">${escHtml(preview)}</textarea>
      <div id="genVisualState">${panelPickerHtml()}</div>
      <div class="advanced-button-row text-xs">
        <button class="tag" onclick="probeHiggsfield()" ${tooltipAttr("Check local Higgsfield CLI auth and supported model capabilities before spending on jobs.")}>probe Higgsfield</button>
        <button class="tag" onclick="generateGrokPrompt()" ${tooltipAttr("Prepare the v1 prompt contract preview from the selected reference clip and campaign context.")}>build prompt preview</button>
        <button class="tag" onclick="generateGrokPrompt('more_cleavage')" ${tooltipAttr("Rebuild the preview with stronger cleavage and body-emphasis direction.")}>more cleavage</button>
        <button class="tag" onclick="generateGrokPrompt('less_smile')" ${tooltipAttr("Rebuild the preview with a sultry expression direction.")}>sultry expression</button>
        <button class="tag" onclick="generateGrokPrompt('more_reference_fidelity')" ${tooltipAttr("Rebuild the preview to follow the reference clip more closely.")}>more reference fidelity</button>
        <button class="tag" onclick="generateGrokPrompt('more_body_emphasis')" ${tooltipAttr("Rebuild the preview with stronger pose and body composition emphasis.")}>more body emphasis</button>
        <button class="tag" onclick="dryRunAssets()" ${tooltipAttr("No spend. Print the planned Higgsfield/Kling commands and lineage inputs for inspection.")}>dry-run commands</button>
        <button class="tag" onclick="createGridFanoutWorkflow()" ${tooltipAttr("Run the normal grid plus panel animation workflow with confirmation before paid animation jobs.")}>create grid + animate panels</button>
        <button class="tag" onclick="fanoutPanels({dryRun:true})" ${tooltipAttr("Crop and preview panels from an existing grid image without creating animation jobs.")}>crop existing grid</button>
        <button class="tag" onclick="createSoulImage()" ${tooltipAttr("Advanced fallback. Create only the paid Soul image and stop before panel selection/animation.")}>manual: create Soul image</button>
        <button class="tag" onclick="createSixPackSoulImages()" ${tooltipAttr("Advanced fallback. Create six separate paid Soul images instead of one grid image.")}>manual: six separate Soul images</button>
        <button class="tag" onclick="createKlingVideo()" ${tooltipAttr("Advanced fallback. Animate only the currently selected start image as one paid Kling job.")}>manual: create Kling video</button>
        <button class="tag" onclick="downloadKlingVideo()" ${tooltipAttr("Download a completed Kling/Higgsfield result URL into the local source clip library.")}>download video</button>
        <button class="tag bg-emerald-900 text-emerald-100" onclick="saveGeneratedPhoto()" ${tooltipAttr("Save the selected image as a photo-post asset for review. This does not publish.")}>save as photo post</button>
        <button class="tag" onclick="openGridCropEditor()" ${tooltipAttr("Open the manual crop editor for animated grids when automatic panel detection needs operator correction.")}>open grid crop editor</button>
        <button class="tag" onclick="renderGeneratedPack()" ${tooltipAttr("Render local caption/recipe variants from the downloaded generated clip.")}>render pack</button>
      </div>
      <pre id="genLog" class="mt-3 max-h-48 overflow-auto text-[10px] text-gray-400 whitespace-pre-wrap"></pre>
      </div>
    </div>
  `;
}
function gridCropPanel(data) {
  if (!gridCropState.open && !data.grid_crop?.plan) return "";
  if (data.grid_crop?.plan && !gridCropState.loadedStem) {
    const p = data.grid_crop.plan;
    gridCropState = {
      ...gridCropState,
      loadedStem: selectedStem,
      boxes: p.boxes || [],
      grid_preset: p.gridPreset || p.grid_preset || {columns: 3, rows: 2},
      frame_time: p.frameTime || p.frame_time || 0.25,
      source_dimensions: p.sourceDimensions || p.source_dimensions || gridCropState.source_dimensions,
      render_captions: (p.renderMode || p.render_mode || "fit_nocrop") === "fit_nocrop",
      open: true
    };
  }
  const dims = gridCropState.source_dimensions || {};
  const boxes = gridCropState.boxes || [];
  const frame = gridCropState.frame_url;
  const preset = gridCropState.grid_preset || {columns: 3, rows: 2};
  const dimLabel = dims.width ? `${dims.width}×${dims.height}` : "load frame first";
  return `
    <div id="gridCropWorkspace" class="card rounded-lg p-4 mb-4">
      <div class="flex items-center justify-between gap-3 mb-3">
        <div>
          <div class="text-xs uppercase tracking-wide text-gray-400">Grid Crop</div>
          <div class="text-xs text-gray-500 mt-1">Crop after Kling. Save boxes first, then render panels with fit/no-crop.</div>
        </div>
        <div class="flex gap-2">
          <span class="tag">${escHtml(dimLabel)}</span>
          <span class="tag">${boxes.filter(b => b.enabled !== false).length} enabled</span>
        </div>
      </div>
      <div class="flex flex-wrap gap-2 text-xs mb-3">
        <button class="tag" onclick="loadGridCropFrame()" ${tooltipAttr("Load a still frame from the selected video so crop boxes can be drawn accurately.")}>load frame</button>
        <button class="tag ${preset.columns===3&&preset.rows===2?'bg-indigo-600 text-white':''}" onclick="applyGridPreset(3,2)" ${tooltipAttr("Apply a 3 columns by 2 rows panel layout.")}>3x2</button>
        <button class="tag ${preset.columns===2&&preset.rows===2?'bg-indigo-600 text-white':''}" onclick="applyGridPreset(2,2)" ${tooltipAttr("Apply a 2 columns by 2 rows panel layout for higher per-panel detail.")}>2x2</button>
        <button class="tag ${preset.columns===4&&preset.rows===2?'bg-indigo-600 text-white':''}" onclick="applyGridPreset(4,2)" ${tooltipAttr("High-panel-count fallback only. Use when the generated image actually returned 4 columns by 2 rows.")}>4x2</button>
        <button class="tag" onclick="suggestGridBoxes()" ${tooltipAttr("Use image analysis to propose crop boxes for each visible panel.")}>suggest boxes</button>
        <button class="tag" onclick="saveGridCropPlan()" ${tooltipAttr("Save the current crop boxes so the render step can reuse them.")}>save crop plan</button>
        <button class="tag" onclick="previewGridPanel()" ${tooltipAttr("Render a still preview of the currently selected crop box.")}>preview selected</button>
        <button class="tag bg-emerald-900 text-emerald-100" onclick="renderGridCropPanels()" ${tooltipAttr("Create individual panel clips from enabled crop boxes and optionally render captions.")}>crop + caption panels</button>
        <label class="tag" title="When enabled, cropped panels also get caption rendering instead of only raw crops."><input type="checkbox" ${gridCropState.render_captions !== false ? "checked" : ""} onchange="gridCropState.render_captions=this.checked"> render captions</label>
      </div>
      <div class="grid grid-cols-3 gap-3">
        <div class="col-span-2">
          <div id="gridCropCanvas" class="grid-crop-canvas">
            ${frame ? `<img src="${frame}?t=${Date.now()}" alt="grid crop frame">` : `<div class="grid-crop-empty">load a frame to start</div>`}
            ${frame ? boxes.map(b => gridCropBoxHtml(b, dims)).join("") : ""}
          </div>
        </div>
        <div class="space-y-2 max-h-[520px] overflow-auto pr-1">
          ${boxes.map(b => gridCropControlsHtml(b)).join("") || `<p class="text-xs text-gray-500">No boxes yet. Load frame, then choose 3x2 or 4x2.</p>`}
          ${gridCropState.preview_url ? `<div class="pt-2"><div class="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Panel preview</div><img class="rounded border border-gray-700" src="${gridCropState.preview_url}?t=${Date.now()}"></div>` : ""}
        </div>
      </div>
    </div>
  `;
}
function gridCropBoxHtml(b, dims) {
  const w = dims.width || 1, h = dims.height || 1;
  const left = (b.x / w) * 100, top = (b.y / h) * 100, width = (b.w / w) * 100, height = (b.h / h) * 100;
  const selected = gridCropState.selected_panel === b.id;
  const disabled = b.enabled === false;
  return `<div class="grid-crop-box ${selected ? 'selected' : ''} ${disabled ? 'disabled' : ''}" data-panel="${b.id}" style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"
    onpointerdown="startGridCropDrag(event, ${b.id}, 'move')" onclick="selectGridCropPanel(${b.id})">
    <span>${escHtml(b.label || `panel ${b.id}`)}</span>
    <button class="grid-crop-handle" onpointerdown="startGridCropDrag(event, ${b.id}, 'resize')" title="resize"></button>
  </div>`;
}
function gridCropControlsHtml(b) {
  const checked = b.enabled === false ? "" : "checked";
  return `
    <div class="grid-crop-row ${gridCropState.selected_panel === b.id ? 'selected' : ''}">
      <div class="flex items-center justify-between mb-1">
        <button class="tag" onclick="selectGridCropPanel(${b.id})">${escHtml(b.label || `panel ${b.id}`)}</button>
        <label class="text-[11px] text-gray-400"><input type="checkbox" ${checked} onchange="setGridCropEnabled(${b.id}, this.checked)"> enabled</label>
      </div>
      <div class="grid grid-cols-4 gap-1 text-[10px]">
        ${["x","y","w","h"].map(k => `<input class="rounded px-1 py-1" type="number" value="${Math.round(b[k])}" onchange="setGridCropValue(${b.id}, '${k}', this.value)">`).join("")}
      </div>
    </div>
  `;
}
function hookToEditor(h) { return typeof h === "string" ? h : JSON.stringify(h, null, 2); }
function openHookEditor() {
  hookEditorOpen = true;
  renderDetail();
}
function hookLabel(h) {
  if (typeof h === "string") return h;
  const segs = Array.isArray(h?.segments) ? h.segments : [];
  return segs.map(s => s.text || "").filter(Boolean).join(" / ") || "[timed hook]";
}
function normalizeHookTextForDedupe(block) {
  let s = block;
  if (block.trim().startsWith("{")) {
    try {
      const parsed = JSON.parse(block);
      if (Array.isArray(parsed?.segments)) {
        s = parsed.segments.map(seg => seg.text || "").join(" ");
      }
    } catch (_) {}
  }
  return s.toLowerCase().replace(/\s+/g, " ").trim();
}
function duplicateHookPairs(hooks) {
  const pairs = [];
  const norm = hooks.map(normalizeHookTextForDedupe);
  for (let i = 0; i < norm.length; i++) {
    for (let j = i + 1; j < norm.length; j++) {
      if (norm[i] && norm[j] && hookSimilarity(norm[i], norm[j]) >= 92) pairs.push([i, j]);
    }
  }
  return pairs;
}
function hookSimilarity(a, b) {
  if (a === b) return 100;
  const longer = a.length >= b.length ? a : b;
  const shorter = a.length >= b.length ? b : a;
  if (!longer.length) return 0;
  const dist = levenshtein(longer, shorter);
  return ((longer.length - dist) / longer.length) * 100;
}
function levenshtein(a, b) {
  const row = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return row[b.length];
}
async function loadHookLibrary() {
  try {
    const tag = document.getElementById("hookTagFilter")?.value || "";
    const group = document.getElementById("hookGroupFilter")?.value || "";
    const minUse = document.getElementById("hookUseFilter")?.value || "0";
    const qs = new URLSearchParams({tag, semantic_group: group, min_use_count: minUse});
    const data = await (await fetch(`/api/hook-library?${qs}`)).json();
    hookLibrary = data.hooks || [];
    hookEmbedding = data.embedding || hookEmbedding;
  }
  catch (_) { hookLibrary = []; }
}
function renderHookBlocks(hooks) {
  currentHooks = hooks.map(hookToEditor);
  return `
    <div id="hookBlocks" class="space-y-3">
      ${currentHooks.map((text, idx) => hookBlockHtml(text, idx)).join("") || '<p class="text-xs text-gray-500">no hooks yet</p>'}
    </div>
  `;
}
function hookBlockHtml(text, idx) {
  return `
    <div class="card rounded p-3" data-hook-idx="${idx}">
      <div class="flex items-center justify-between mb-2">
        <span class="tag">#${idx + 1}</span>
        <div class="flex gap-1">
          <button class="tag" onclick="moveHook(${idx}, -1)">↑</button>
          <button class="tag" onclick="moveHook(${idx}, 1)">↓</button>
          <button class="tag" onclick="saveHookToLibrary(${idx})">library</button>
          <button class="tag bg-red-950 text-red-200" onclick="deleteHook(${idx})">delete</button>
        </div>
      </div>
      <textarea id="hook_${idx}" oninput="updateHookWarnings()" class="w-full rounded px-3 py-2 text-sm font-mono h-24">${escHtml(text)}</textarea>
    </div>
  `;
}
function collectHooksFromEditor() {
  const blocks = [...document.querySelectorAll("[data-hook-idx]")];
  return blocks.map((_, idx) => document.getElementById(`hook_${idx}`).value.trim()).filter(Boolean);
}
function rerenderHookEditor() {
  const holder = document.getElementById("hookEditor");
  if (!holder) return;
  holder.innerHTML = renderHookBlocks(currentHooks);
  updateHookWarnings();
}
function moveHook(idx, delta) {
  currentHooks = collectHooksFromEditor();
  const next = idx + delta;
  if (next < 0 || next >= currentHooks.length) return;
  [currentHooks[idx], currentHooks[next]] = [currentHooks[next], currentHooks[idx]];
  rerenderHookEditor();
}
function deleteHook(idx) {
  currentHooks = collectHooksFromEditor();
  currentHooks.splice(idx, 1);
  rerenderHookEditor();
}
function addHookBlock(text = "") {
  currentHooks = collectHooksFromEditor();
  currentHooks.push(text);
  rerenderHookEditor();
}
async function saveHookToLibrary(idx) {
  const hooks = collectHooksFromEditor();
  const hook = hooks[idx];
  if (!hook) return;
  await fetch("/api/hook-library", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({hook})
  });
  await loadHookLibrary();
  flash("saved to hook library");
}
function insertLibraryHook() {
  const sel = document.getElementById("hookLibrarySelect");
  if (!sel || !sel.value) return;
  const item = hookLibrary.find(h => h.id === sel.value);
  if (item) addHookBlock(hookToEditor(item.hook ?? item.text));
}
function hookLibraryOptions() {
  const groups = [...new Set(hookLibrary.map(h => h.semantic_group).filter(Boolean))].sort();
  return hookLibrary.map(item => {
    const meta = `${item.use_count || 0}x${item.semantic_group ? ' · ' + item.semantic_group : ''}`;
    return `<option value="${item.id}">${escHtml((item.text || '').slice(0, 64))} (${escHtml(meta)})</option>`;
  }).join("");
}
function updateHookWarnings() {
  const warn = document.getElementById("hookWarnings");
  if (!warn) return;
  const pairs = duplicateHookPairs(collectHooksFromEditor());
  if (!pairs.length) {
    warn.classList.add("hidden");
    warn.textContent = "";
    return;
  }
  warn.classList.remove("hidden");
  warn.textContent = `Duplicate hooks: ${pairs.map(([a,b]) => `#${a + 1} repeats #${b + 1}`).join(", ")}`;
}

async function selectClip(stem) {
  selectedStem = stem;
  currentFilter = {hook: null, recipe: null, review: null};
  outputDisplayLimit = 80;
  hookEditorOpen = false;
  cockpitModeTouched = false;
  lastAiGeneration = null;
  const detail = document.getElementById("detail");
  if (detail) {
    detail.innerHTML = `
      <div class="flex items-center gap-3 text-sm text-gray-400">
        <span class="spin"></span>
        <span>loading ${escHtml(stem)} details…</span>
      </div>
    `;
  }
  if (gridCropState.loadedStem !== stem) {
    gridCropState = {open: false, frame_time: 0.25, boxes: [], grid_preset: {columns: 3, rows: 2}, render_captions: true};
  }
  try {
    await loadClips();
    await renderDetail();
  } catch (err) {
    console.error(err);
    if (detail) {
      detail.innerHTML = `
        <div class="card rounded-lg p-4 border-red-900 bg-red-950/20">
          <div class="text-sm font-semibold text-red-200">Could not load clip details</div>
          <p class="text-xs text-red-100/80 mt-2">${escHtml(err?.message || String(err))}</p>
          <button class="btn btn-secondary text-xs mt-3" onclick="selectClip('${escJs(stem)}')">retry</button>
        </div>
      `;
    }
  }
}

async function renderDetail() {
  if (!selectedStem) return;
  const data = await (await fetch(`/api/clips/${selectedStem}`)).json();
  const metrics = await (await fetch("/api/metrics/summary")).json();
  const outcomes = await fetch("/api/outcomes/summary?limit=8").then(r => r.json()).catch(() => ({count: 0, top: [], totals: {}}));
  const dna = await fetch("/api/winner-dna/leaderboard?limit=16").then(r => r.json()).catch(() => ({winner_dna: [], worst_rejection_patterns: []}));
  dna.baseline_report = await fetch("/api/reports/baseline-vs-recommended").then(r => r.json()).catch(() => ({}));
  const selectedAccount = document.getElementById("acct")?.value || "";
  dna.account_fatigue = selectedAccount
    ? await fetch(`/api/reports/account-fatigue?account=${encodeURIComponent(selectedAccount)}`).then(r => r.json()).catch(() => ({}))
    : {};
  await loadHookLibrary();
  const detail = document.getElementById("detail");
  const hooks = (data.sidecar.hooks || []);

  // Group outputs by hook_idx for display
  const hookGroups = {};
  data.outputs.forEach(o => {
    if (!hookGroups[o.hook_idx]) hookGroups[o.hook_idx] = [];
    hookGroups[o.hook_idx].push(o);
  });
  const hookKeys = Object.keys(hookGroups).map(k => parseInt(k)).filter(k => k >= 0).sort((a,b) => a-b);
  const recipes = [...new Set(data.outputs.map(o => o.recipe))];

  // Apply filter
  const filtered = data.outputs.filter(o => {
    if (currentFilter.hook !== null && o.hook_idx !== currentFilter.hook) return false;
    if (currentFilter.recipe !== null && o.recipe !== currentFilter.recipe) return false;
    if (currentFilter.review !== null && o.review_state !== currentFilter.review) return false;
    return true;
  });
  const displayedOutputs = filtered.slice(0, outputDisplayLimit);
  visibleOutputs = displayedOutputs;
  const clipStatus = clipStatusForData(data);
  const nextAction = nextActionForClip(data);
  if (!cockpitModeTouched) cockpitMode = defaultModeFor(data, clipStatus.status);
  const showCreate = cockpitMode === "Create";
  const showRender = cockpitMode === "Render";
  const showReview = cockpitMode === "Review";
  const showLearn = cockpitMode === "Learn";
  const dataQuality = dna?.data_quality || {};

  detail.innerHTML = `
    <div class="clip-workspace">
      <div class="clip-media-card">
        <div class="flex items-center gap-2 mb-3">
          <h2 class="text-lg font-semibold">${selectedStem}</h2>
          <span class="status-pill ${toneClass(clipStatus.tone)}">${escHtml(clipStatus.status)}</span>
        </div>
        <div class="clip-meta-tags mb-3">
          <span class="tag">${hooks.length} captions</span>
          <span class="tag">${data.outputs.length} outputs</span>
          <span class="tag">MP4</span>
        </div>
        <video src="${data.video_url}" controls class="primary-video"></video>
        <div class="clip-action-row">
          ${data.csv ? `<a href="${data.csv}" target="_blank" class="btn btn-secondary text-xs" ${tooltipAttr("Open the rendered output manifest CSV for this clip.")}>CSV</a>` : ''}
          ${data.contact_sheet ? `<a href="${data.contact_sheet}" target="_blank" class="btn btn-secondary text-xs" ${tooltipAttr("Open a contact sheet preview of rendered variants for quick scanning.")}>contact sheet</a>` : ''}
          <button onclick="previewCaption()" class="btn btn-secondary text-xs" ${tooltipAttr("Render a quick still preview to check caption placement before running a full batch.")}>Preview caption</button>
          <button onclick="addClipAsReference()" class="btn btn-secondary text-xs" ${tooltipAttr("Attach this source clip to the selected campaign as reference material for future recommendations/generation.")}>Add as reference</button>
          <button onclick="openGridCropEditor()" class="btn btn-secondary text-xs" ${tooltipAttr("Manually define crop boxes for animated grid videos and render each panel separately.")}>Grid Crop</button>
          <button onclick="whisperSync()" class="btn btn-secondary text-xs" ${tooltipAttr("Use speech timing to align captions with spoken audio when available.")}>Auto-time speech</button>
          <button onclick="deleteClip('${selectedStem}')" class="btn btn-danger text-xs" ${tooltipAttr("Delete this source clip and its local processed outputs. This is destructive.")}>Delete clip</button>
        </div>
      </div>

      <div class="workflow-column">
        ${operatorReadinessFor(data, clipStatus, nextAction, dataQuality)}

        ${modeTabs()}

        <div class="${showCreate ? '' : 'hidden'}">${generationPanel(data)}</div>
        <div class="${showRender ? '' : 'hidden'}">
          <div class="card rounded-lg p-4 mb-4">
            <div class="text-xs uppercase tracking-wide text-gray-400 mb-2">Render Setup</div>
            <div class="flex flex-wrap gap-2 text-xs">
              ${riskLight("Source", data.video_url ? "pass" : "fail", "source video")}
              ${riskLight("Outputs", data.outputs.length ? "pass" : "warn", `${data.outputs.length} rendered outputs`)}
              ${riskLight("Data", dataQuality.level || "weak", (dataQuality.reasons || []).join(", "))}
              <button class="tag" onclick="startRun()" ${tooltipAttr("Render caption and recipe variants locally for the selected clip. No publishing happens here.")}>run pipeline</button>
              <button class="tag" onclick="previewCaption()" ${tooltipAttr("Create a quick preview frame to inspect caption placement before a full render.")}>preview caption</button>
            </div>
            ${whyDetails("Render", ["Use this mode when the source is ready but still needs caption/recipe variations.", `${data.outputs.length} outputs currently exist for this clip.`])}
          </div>
          ${gridCropPanel(data)}
          ${data.latest_preview ? `<div class="card rounded-lg p-3 mb-4"><div class="flex items-center justify-between mb-2"><div class="text-xs uppercase tracking-wide text-gray-400">latest preview</div><button class="tag ${showSafeZones ? 'bg-indigo-600 text-white' : ''}" onclick="toggleSafeZones()" ${tooltipAttr("Overlay platform safe zones so captions and important visuals avoid UI-covered areas.")}>safe zones</button></div>${safeZoneWrap(`<img src="${data.latest_preview}?t=${Date.now()}" class="max-h-[420px] rounded bg-black">`, data.safe_zones)}</div>` : ''}
        </div>
        <div class="${showLearn ? '' : 'hidden'}">${intelligencePanel(outcomes, dna)}</div>
      </div>
    </div>

    ${reviewReasonModalHtml()}

    ${showLearn && (metrics.rows || []).length ? `
    <div class="card rounded-lg p-4 mb-4">
      <div class="text-xs uppercase tracking-wide text-gray-400 mb-2">metrics summary</div>
      <div class="grid grid-cols-6 gap-2 text-xs text-gray-300">
        <div>recipe</div><div>hook</div><div>uploads</div><div>avg views</div><div>avg likes</div><div>top output</div>
        ${metrics.rows.map(row => `
          <div class="truncate">${escHtml(row.recipe)}</div>
          <div>h${String(row.hook_idx).padStart(2,'0')}</div>
          <div>${row.upload_count}</div>
          <div>${row.avg_views ?? '-'}</div>
          <div>${row.avg_likes ?? '-'}</div>
          <div class="truncate" title="${escHtml(row.top_output || '')}">${escHtml(row.top_output || '-')}</div>
        `).join("")}
      </div>
    </div>
    ` : ''}

    <div class="card rounded-lg p-4 mb-4 ${showCreate || showRender ? '' : 'hidden'}">
      <div class="flex items-center justify-between mb-3">
        <label class="text-xs uppercase tracking-wide text-gray-400 block">captions · optional editor</label>
        <div class="flex gap-2">
          ${hookEditorOpen ? `
          <input id="hookTagFilter" class="rounded px-2 py-1 text-xs w-24" placeholder="tag" onchange="renderDetail()">
          <input id="hookGroupFilter" class="rounded px-2 py-1 text-xs w-32" placeholder="semantic group" onchange="renderDetail()">
          <select id="hookUseFilter" class="rounded px-2 py-1 text-xs" onchange="renderDetail()">
            <option value="0">any use</option>
            <option value="2">2+ uses</option>
            <option value="5">5+ uses</option>
          </select>
          <select id="hookLibrarySelect" class="rounded px-2 py-1 text-xs">
            <option value="">insert from library</option>
            ${hookLibraryOptions()}
          </select>
          <button onclick="insertLibraryHook()" class="btn btn-secondary text-xs">Insert</button>
          ` : `
          <button onclick="autoCaptionSelected()" class="btn btn-secondary text-xs">Auto-create captions</button>
          <button onclick="openHookEditor()" class="btn btn-secondary text-xs">Edit captions</button>
          `}
        </div>
      </div>
      ${hookEditorOpen ? `<div id="hookEditor">${renderHookBlocks(hooks)}</div>` : `<p class="text-xs text-gray-500">${hooks.length ? `${hooks.length} captions ready. You can render without editing.` : "No captions yet. Auto-create captions will fill this for you."}</p>`}
      <p id="hookWarnings" class="hidden text-xs text-amber-300 mt-2"></p>
      ${hookEditorOpen ? `<div class="flex gap-2 mt-3">
        <button onclick="saveHooks('${selectedStem}')" class="btn">Save hooks</button>
        <button onclick="addHookBlock()" class="btn btn-secondary">+ Add hook</button>
        <button onclick="spinHook()" class="btn btn-secondary">+ Spin from base hook</button>
        <button id="aiHookBtn" onclick="aiRewriteHook()" class="btn btn-secondary" title="Checking Ollama…">AI rewrite hooks</button>
      </div>` : ``}
    </div>

    ${showReview && data.outputs.length > 0 ? `
    <div class="border-t border-gray-800 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm uppercase tracking-wide text-gray-400">outputs (${displayedOutputs.length} shown · ${filtered.length}${currentFilter.hook!==null||currentFilter.recipe!==null ? ` of ${data.outputs.length}` : ''})</h3>
        <div class="flex gap-2 text-xs flex-wrap">
          <button class="tag" onclick="generateThumbs()" ${tooltipAttr("Generate poster thumbnails for rendered output videos.")}>make thumbnails</button>
          <button class="tag" onclick="runReadiness()" ${tooltipAttr("Check rendered outputs for platform/export readiness warnings.")}>run readiness</button>
          <button class="tag" onclick="exportApproved()" ${tooltipAttr("Export locally approved outputs for the selected account. This still does not auto-publish.")}>export approved</button>
          <button class="tag" onclick="batchReview('approved')" ${tooltipAttr("Mark every currently visible output as approved.")}>approve visible</button>
          <button class="tag" onclick="batchReview('rejected')" ${tooltipAttr("Mark every currently visible output as rejected.")}>reject visible</button>
          ${!AUDIO_DISABLED ? `<button class="tag" onclick="muxAudio()" ${tooltipAttr("Attach a local audio file from the audio library. Native Instagram audio remains manual.")}>mux audio</button>` : ``}
          <button class="tag" onclick="renderComparePanel()" ${tooltipAttr("Open the synced comparison panel for outputs you selected with Compare.")}>compare selected</button>
          <button class="tag ${showSafeZones ? 'bg-indigo-600 text-white' : ''}" onclick="toggleSafeZones()" ${tooltipAttr("Overlay platform safe zones on preview videos.")}>safe zones</button>
          ${filtered.length > displayedOutputs.length ? `<button class="tag" onclick="showMoreOutputs('more')">show 80 more</button><button class="tag" onclick="showMoreOutputs('all')">show all</button>` : ``}
          <button class="tag ${currentFilter.hook===null && currentFilter.recipe===null ? 'bg-indigo-600 text-white':''}" onclick="setFilter(null,null)">all</button>
          ${recipes.map(r => `<button class="tag ${currentFilter.recipe===r?'bg-indigo-600 text-white':''}" onclick="setFilter(null,'${r}')">${r}</button>`).join("")}
          <span class="text-gray-700">|</span>
          ${hookKeys.map(h => `<button class="tag ${currentFilter.hook===h?'bg-indigo-600 text-white':''}" onclick="setFilter(${h},null)" title="${escHtml(hookLabel(hooks[h]))}">h${String(h).padStart(2,'0')}</button>`).join("")}
          <span class="text-gray-700">|</span>
          ${["draft","approved","rejected"].map(s => `<button class="tag ${currentFilter.review===s?'bg-indigo-600 text-white':''}" onclick="setReviewFilter('${s}')">${s}</button>`).join("")}
        </div>
      </div>
      <div id="comparePanel" class="hidden card rounded-lg p-3 mb-3"></div>

      <div class="grid grid-cols-4 gap-3 max-h-[700px] overflow-y-auto pr-2">
        ${displayedOutputs.map(o => `
          <div class="card rounded overflow-hidden">
            <div class="video-tile aspect-[9/16]">
              ${safeZoneWrap(`<video src="${o.url}" controls preload="metadata" class="w-full h-full object-cover"></video>`, data.safe_zones, "w-full h-full")}
            </div>
            <div class="p-2 text-[11px]">
              <div class="flex items-center gap-1 mb-1 flex-wrap">
                <span class="tag">h${String(o.hook_idx).padStart(2,'0')}</span>
                <span class="tag">${o.recipe}</span>
                <span class="tag">${o.review_state}</span>
                <span class="tag">${o.target_ratio}</span>
                <span class="tag">${o.audio_present ? 'audio' : 'silent'}</span>
                ${riskLight("QC", (o.ai_qc?.warnings || []).length ? "warn" : "pass", (o.ai_qc?.warnings || []).join(", "))}
                ${riskLight("Readiness", o.readiness?.status === "ready" ? "pass" : (o.readiness?.status || "warn"), (o.readiness?.warnings || []).join(", "))}
                ${riskLight("Duplicate", o.similarity ? (Number(o.similarity.novelty || 100) < 20 ? "high" : "low") : "low", o.similarity?.verdict || "run duplicate risk for details")}
                ${riskLight("Data", dataQuality.level || "weak", (dataQuality.reasons || []).join(", "))}
                ${o.operator_rating ? `<span class="tag" title="${escHtml((o.operator_rating.labels || []).join(', '))}">rated ${o.operator_rating.taste || '-'}/5</span>` : ''}
              </div>
              ${whyDetails("Output", [
                `Readiness: ${o.readiness?.status || "not checked"}`,
                `QC warnings: ${(o.ai_qc?.warnings || []).join(", ") || "none"}`,
                `Duplicate signal: ${o.similarity?.verdict || "not checked"}`,
              ])}
              <div class="text-gray-400 truncate" title="${escHtml(hookLabel(hooks[o.hook_idx]))}">${escHtml(hookLabel(hooks[o.hook_idx]).replace(/\\n/g,' / ').slice(0,60))}</div>
              <div class="flex gap-1 mt-2">
                ${["draft","approved","rejected"].map(s => `<button class="tag ${o.review_state===s?'bg-indigo-700 text-white':''}" onclick="setOutputReview('${o.name}', '${s}')" ${tooltipAttr(`Set this output review state to ${s}.`)}>${s}</button>`).join("")}
              </div>
              <div class="flex gap-1 mt-2">
                <button class="tag" onclick="toggleCompare('${o.name}', '${o.url}')" ${tooltipAttr("Add or remove this output from the side-by-side comparison panel.")}>compare</button>
                ${o.thumbnail_url ? `<a class="tag" target="_blank" href="${o.thumbnail_url}" ${tooltipAttr("Open this output's generated poster thumbnail.")}>thumb</a>` : ''}
              </div>
              <div class="mt-2">${audioIntentSelect(o)}</div>
              <div class="flex gap-1 mt-2">
                <button class="tag" onclick="quickRate('${escJs(o.name)}', 'identity_good,pose_good', 5)" ${tooltipAttr("Record a positive operator rating for identity and pose quality.")}>good</button>
                <button class="tag" onclick="openReviewReason('${escJs(o.name)}', 'maybe')" ${tooltipAttr("Open reason capture for a borderline output.")}>maybe</button>
                <button class="tag" onclick="openReviewReason('${escJs(o.name)}', 'reject')" ${tooltipAttr("Open reason capture for a rejected output.")}>reject</button>
                <button class="tag" onclick="showSimilar('${escJs(o.name)}')" ${tooltipAttr("Search the local media index for visually similar assets.")}>similar</button>
                <button class="tag" onclick="showDuplicateRisk('${escJs(o.name)}')" ${tooltipAttr("Check whether this output is too similar to prior account content.")}>dup risk</button>
                <button class="tag bg-emerald-900 text-emerald-100" onclick="queueThreadsDashboard('${escJs(o.name)}', '${escJs(hookLabel(hooks[o.hook_idx]))}')" ${tooltipAttr("Queue this approved output for ThreadsDashboard scheduling. This does not auto-publish.")}>schedule</button>
                <button class="tag" onclick="assignExperimentForOutput('${escJs(o.name)}')" ${tooltipAttr("Assign this output to an experiment group for later outcome comparison.")}>experiment</button>
              </div>
            </div>
          </div>
        `).join("") || '<p class="text-gray-500 text-sm col-span-4">no outputs match the filter</p>'}
      </div>
    </div>
    ` : showReview ? `
    <div class="border-t border-gray-800 pt-6 text-center">
      <p class="text-gray-500 text-sm">no outputs yet — click Make reels now or Run pipeline; captions will be created automatically</p>
    </div>
    ` : ``}
  `;
  updateHookWarnings();
  refreshAiHookStatus();
  renderCommandCenter();
}

function setFilter(hook, recipe) {
  currentFilter = {hook, recipe, review: null};
  outputDisplayLimit = 80;
  renderDetail();
}
function setReviewFilter(review) {
  currentFilter.review = currentFilter.review === review ? null : review;
  outputDisplayLimit = 80;
  renderDetail();
}
function showMoreOutputs(mode = "more") {
  outputDisplayLimit = mode === "all" ? 9999 : outputDisplayLimit + 80;
  renderDetail();
}
async function setOutputReview(filename, review_state) {
  await fetch(`/api/outputs/${encodeURIComponent(filename)}/review`, {
    method: "PUT", headers: {"content-type": "application/json"},
    body: JSON.stringify({review_state})
  });
  await renderDetail();
}
async function setAudioIntent(filename, mode) {
  if (!mode) return;
  const r = await fetch(`/api/outputs/${encodeURIComponent(filename)}/audio-intent`, {
    method: "PUT", headers: {"content-type": "application/json"},
    body: JSON.stringify({mode, platform: "instagram_reels"})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "audio intent failed");
  flash("audio intent saved");
  await renderDetail();
}

async function quickRate(filename, labels, score) {
  const labelList = labels.split(",");
  let retryHelper = null;
  if (labelList.includes("hands_bad")) retryHelper = "fix_hands";
  else if (labelList.includes("pose_drift")) retryHelper = "fix_pose";
  else if (labelList.includes("too_smiley")) retryHelper = "less_smile";
  await fetch(`/api/outputs/${encodeURIComponent(filename)}/rating`, {
    method: "PUT",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      identity: score,
      pose: score,
      taste: score,
      artifacts: score,
      motion: score,
      labels: labelList,
      retry_helper: retryHelper,
      decision: "approve",
      primary_reason: "identity_good",
      secondary_reasons: ["pose_good"]
    })
  });
  flash("rating saved");
  await renderDetail();
}

async function openReviewReason(filename, decision) {
  reviewModalState = {
    filename,
    decision,
    primary: decision === "approve" ? "identity_good" : (decision === "maybe" ? "pose_drift" : "hands_bad"),
    secondary: [],
    notes: ""
  };
  await renderDetail();
}
function setReviewPrimary(reason) {
  reviewModalState.primary = reason;
  renderDetail();
}
function toggleReviewSecondary(reason) {
  const set = new Set(reviewModalState.secondary || []);
  if (set.has(reason)) set.delete(reason);
  else if (reason !== reviewModalState.primary) set.add(reason);
  reviewModalState.secondary = [...set];
  renderDetail();
}
function closeReviewReasonModal(event) {
  if (event.target.classList.contains("modal-backdrop")) {
    reviewModalState = null;
    renderDetail();
  }
}
async function saveReviewReason() {
  if (!reviewModalState?.primary) return flash("pick a primary reason");
  const notes = document.getElementById("reviewNotes")?.value || "";
  const score = reviewModalState.decision === "reject" ? 2 : (reviewModalState.decision === "maybe" ? 3 : 5);
  const primary = reviewModalState.primary;
  const secondary = reviewModalState.secondary || [];
  const filename = reviewModalState.filename;
  const decision = reviewModalState.decision;
  const r = await fetch(`/api/outputs/${encodeURIComponent(filename)}/rating`, {
    method: "PUT",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      identity: score,
      pose: score,
      taste: score,
      artifacts: score,
      motion: score,
      labels: [primary, ...secondary],
      retry_helper: primary === "hands_bad" ? "fix_hands" : (primary === "pose_drift" ? "fix_pose" : null),
      decision,
      primary_reason: primary,
      secondary_reasons: secondary,
      notes
    })
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "rating failed");
  reviewModalState = null;
  await setOutputReview(filename, decision === "reject" ? "rejected" : "draft");
}

async function showSimilar(pathOrFilename) {
  const j = await (await fetch(`/api/similar?path=${encodeURIComponent(pathOrFilename)}&limit=8`)).json();
  const lines = (j.results || []).map(r => `${Math.round(r.score * 100)}% · ${r.entity_type} · ${r.path}`).join("\n");
  alert(lines || "No similar media indexed yet. Run embedding_index.py index first.");
}

async function showDuplicateRisk(pathOrFilename) {
  const account = document.getElementById("acct")?.value || prompt("Account:");
  if (!account) return;
  const j = await (await fetch(`/api/reports/duplicate-risk?path=${encodeURIComponent(pathOrFilename)}&account=${encodeURIComponent(account)}&limit=8`)).json();
  const nearest = j.nearest_prior_output ? `\nnearest: ${j.nearest_prior_output.filename || j.nearest_prior_output.path}` : "";
  alert(`duplicate risk: ${j.risk_level} (${Math.round((j.risk_score || 0) * 100)}%)\naction: ${j.recommended_action}\n${j.reason || ""}${nearest}`);
}

async function assignExperimentForOutput(filename) {
  const name = prompt("Experiment name:", "grid_vs_individual");
  if (!name) return;
  const group = prompt("Group:", "grid") || "grid";
  const r = await fetch("/api/experiments/assign", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({name, group, output_path: filename})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "experiment assignment failed");
  flash("experiment assigned");
}

async function batchReview(review_state) {
  const filenames = visibleOutputs.map(o => o.name);
  if (!filenames.length) return flash("no visible outputs");
  const r = await fetch("/api/outputs/review/batch", {
    method: "PUT", headers: {"content-type": "application/json"},
    body: JSON.stringify({filenames, review_state})
  });
  const j = await r.json();
  flash(`updated ${j.changed || 0} outputs`);
  await renderDetail();
}

async function previewCaption() {
  if (!selectedStem) return;
  flash("rendering preview…");
  const r = await fetch(`/api/clips/${selectedStem}/preview`, {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({caption_renderer: document.getElementById("captionRenderer").value, placement_mode: document.getElementById("placementMode").value, target_ratio: document.getElementById("targetRatios").value.split(",")[0]})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || j.error || "preview failed");
  flash("preview ready");
  await renderDetail();
}

async function addClipAsReference() {
  if (!selectedStem) return;
  const campaign = document.getElementById("campaign")?.value || "";
  if (!campaign) return flash("pick a campaign first");
  const sourcePath = `00_source_videos/${selectedStem}.mp4`;
  const r = await fetch(`/api/campaigns/${encodeURIComponent(campaign)}/references`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({source_path: sourcePath, visual_tags: ["operator_reference"]})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "reference add failed");
  flash("reference added");
}

async function importReelUrl() {
  const input = document.getElementById("reelUrl");
  const url = input?.value?.trim();
  if (!url) return flash("paste a reel URL first");
  const campaign = currentCampaign();
  if (!campaign) return flash("pick or create a campaign first");
  flash("downloading reference reel...");
  setGenerationState({status: "running"});
  const r = await fetch("/api/reels/import", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      url,
      campaign,
      creator: "Stacey",
      generate_prompt: document.getElementById("reelAutoPrompt")?.checked !== false,
      grid_layout: generationGridLayout()
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    return flash(j.detail || j.error || "reel import failed");
  }
  input.value = "";
  selectedStem = j.stem;
  await loadClips();
  await renderDetail();
  const promptPath = j.prompt?.prompt_json_path || `prompts/${j.stem}_grok.json`;
  setGenerationState({
    status: j.prompt?.ok ? "prompt ready" : "downloaded",
    stem: j.stem,
    prompt_path: promptPath,
    prompt: j.prompt?.prompt || generationState.prompt,
    grid_layout: j.prompt?.grid_layout?.value || generationGridLayout(),
    source_path: j.path,
    source_url: j.video_url
  });
  genLog(j);
  flash(j.prompt?.ok ? `imported ${j.stem} + prompt preview ready` : `imported ${j.stem}`);
}

function genLog(obj) {
  const el = document.getElementById("genLog");
  if (el) el.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}
function renderGenerationState() {
  const status = document.getElementById("genStatus");
  if (status) status.outerHTML = generationStatusTag();
  const stem = document.getElementById("genStem");
  const promptPath = document.getElementById("genPromptPath");
  const imagePath = document.getElementById("genImagePath");
  const startImage = document.getElementById("genStartImage");
  const gridLayout = document.getElementById("genGridLayout");
  const promptPreview = document.getElementById("genPromptPreview");
  const visual = document.getElementById("genVisualState");
  if (stem && generationState.stem) stem.value = generationState.stem;
  if (promptPath && generationState.prompt_path) promptPath.value = generationState.prompt_path;
  if (imagePath && generationState.local_image_path) imagePath.value = generationState.local_image_path;
  if (startImage && generationState.start_image_path) startImage.value = generationState.start_image_path;
  if (gridLayout && generationState.grid_layout) gridLayout.value = generationState.grid_layout;
  if (promptPreview && generationState.prompt) promptPreview.value = JSON.stringify(generationState.prompt, null, 2);
  if (visual) visual.innerHTML = panelPickerHtml();
  renderCommandCenter();
}
function currentCampaign() { return document.getElementById("campaign")?.value || ""; }
function currentAccount() { return document.getElementById("acct")?.value || "default"; }
async function fillNextClipId() {
  const j = await (await fetch("/api/next-clip-id")).json();
  document.getElementById("genStem").value = j.stem;
  document.getElementById("genPromptPath").value = `prompts/${j.stem}_grok.json`;
  setGenerationState({stem: j.stem, prompt_path: `prompts/${j.stem}_grok.json`, status: "not started"});
}

async function saveGeneratedPhoto() {
  const sourceImage = document.getElementById("genStartImage")?.value || document.getElementById("genImagePath")?.value || generationState.start_image_path || generationState.local_image_path || "";
  if (!sourceImage) {
    flash("create or select an image first");
    return;
  }
  const r = await fetch("/api/photos/save", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({source_image: sourceImage, account: currentAccount(), notes: "Saved from Reel Factory create workflow"})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "photo save failed");
  genLog(j);
  flash("saved as photo post");
}

async function queueThreadsDashboard(filename, caption = "") {
  const scheduledAt = prompt("Schedule time for ThreadsDashboard (optional ISO/local text):", "") || "";
  const r = await fetch("/api/threadsdashboard/queue", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      filename,
      account: currentAccount(),
      caption,
      scheduled_at: scheduledAt || null,
      notes: "Queued from Reel Factory review"
    })
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "schedule queue failed");
  await setOutputReview(filename, "approved");
  flash("queued for ThreadsDashboard");
}
function generationStem() {
  return document.getElementById("genStem")?.value || generationState.stem || selectedStem;
}
function generationPromptPath() {
  return document.getElementById("genPromptPath")?.value || generationState.prompt_path || `prompts/${generationStem()}_grok.json`;
}
function generationGridLayout() {
  return document.getElementById("genGridLayout")?.value || generationState.grid_layout || "3x2";
}
function generationGridDimensions() {
  const layout = generationGridLayout();
  const match = String(layout || "").match(/^(\d+)x(\d+)$/);
  if (!match) return {};
  return {columns: Number(match[1]), rows: Number(match[2]), grid_layout: layout};
}
function soulReferencePath() {
  const promptPath = generationPromptPath();
  const name = promptPath.split("/").pop().replace(/\.json$/, "");
  return `prompts/_references/${name}/reference_00_first_visible.jpg`;
}
function promptReferenceFrameUrl() {
  const path = soulReferencePath();
  return `/file/${path}`;
}
async function probeHiggsfield() {
  setGenerationState({status: "running"});
  const j = await (await fetch("/api/higgsfield/capabilities")).json();
  setGenerationState({status: j.validation?.ok ? "Higgsfield ready" : "failed", capabilities: j});
  genLog(j);
}
async function generateGrokPrompt(retryHelper = null) {
  if (!selectedStem) return;
  if (!currentCampaign()) return flash("pick a campaign first");
  if (!document.getElementById("genStem").value) await fillNextClipId();
  setGenerationState({status: "running", stem: generationStem(), prompt_path: generationPromptPath()});
  genLog("building prompt contract preview...");
  const r = await fetch("/api/prompts/generate", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      campaign: currentCampaign(),
      creator: "Stacey",
      reference_reel: `00_source_videos/${selectedStem}.mp4`,
      out: generationPromptPath(),
      retry_helper: retryHelper,
      reference_frame_mode: "first-visible",
      grid_layout: generationGridLayout()
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    return genLog(j);
  }
  document.getElementById("genPromptPreview").value = JSON.stringify(j.prompt, null, 2);
  setGenerationState({
    status: "prompt ready",
    prompt: j.prompt,
    prompt_path: j.prompt_json_path || generationPromptPath(),
    grid_layout: j.grid_layout?.value || generationGridLayout(),
    prompt_run_id: j.campaign_record?.prompt_run_id || generationState.prompt_run_id,
    first_visible_url: promptReferenceFrameUrl()
  });
  genLog(j);
}
async function dryRunAssets() {
  if (!document.getElementById("genStem").value) await fillNextClipId();
  setGenerationState({status: "running"});
  const r = await fetch("/api/assets/dry-run", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      campaign: currentCampaign() || null,
      creator: "Stacey",
      prompt_json: generationPromptPath(),
      image_mode: "single"
    })
  });
  const j = await r.json();
  setGenerationState({status: "dry-run ready"});
  genLog(j);
}
async function createSoulImage(options = {}) {
  if (!options.skipConfirm && !confirm("Create paid Higgsfield Soul image for Stacey?")) return null;
  setGenerationState({status: "running"});
  const r = await fetch("/api/assets/create-image", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      campaign: currentCampaign() || null,
      creator: "Stacey",
      prompt_json: generationPromptPath(),
      image_mode: options.imageMode || "single",
      wait: true,
      download: true
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    genLog(j);
    return j;
  }
  const imagePath = j.local_image_path || j.lineage?.assets?.localPaths?.image;
  if (imagePath) document.getElementById("genImagePath").value = imagePath;
  setGenerationState({
    status: imagePath ? "needs panel" : "Soul image ready",
    local_image_path: imagePath || generationState.local_image_path,
    local_image_url: j.local_image_url || j.image_url || generationState.local_image_url,
    image_job_id: j.image_job_id,
    image_result_url: j.image_result_url,
    grid: j.grid,
    grid_status: j.grid_status,
    asset_generation_id: j.asset_generation_id || generationState.asset_generation_id,
    lineage_path: j.lineage_path || generationState.lineage_path
  });
  genLog(j);
  return j;
}
async function fanoutPanels(options = {}) {
  const sourceImage = document.getElementById("genImagePath")?.value || generationState.local_image_path;
  if (!sourceImage) return flash("create or select a Soul grid image first");
  setGenerationState({status: options.dryRun ? "cropping panels" : "animating panels"});
  const body = {
    stem: generationStem(),
    campaign: currentCampaign() || null,
    creator: "Stacey",
    prompt_json: generationPromptPath(),
    source_image: sourceImage,
    image_job_id: generationState.image_job_id || null,
    asset_generation_id: generationState.asset_generation_id || null,
    lineage_path: generationState.lineage_path || null,
    dry_run: !!options.dryRun,
    wait: true,
    download: false,
    ...generationGridDimensions()
  };
  if (options.maxJobs != null) body.max_jobs = options.maxJobs;
  const r = await fetch("/api/assets/fanout-panels", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(body)
  });
  const j = await r.json();
  const crops = j.cropManifest?.panelCrops || [];
  setGenerationState({
    status: j.failed ? "fanout partial failure" : (j.dry_run ? "fanout ready" : "panel animations ready"),
    fanout: j,
    panel_crops: crops,
    lineage_path: j.lineage_path || generationState.lineage_path
  });
  genLog(j);
  return j;
}
function useFanoutPanel(panelNo) {
  const crops = generationState.panel_crops || generationState.fanout?.cropManifest?.panelCrops || [];
  const panel = crops.find(p => Number(p.panel) === Number(panelNo));
  if (!panel) return flash("panel crop missing");
  const path = panel.startImagePath || panel.path;
  const url = panel.startImageUrl || panel.url;
  const start = document.getElementById("genStartImage");
  if (start) start.value = path;
  setGenerationState({
    status: "panel selected",
    selected_panel: String(panelNo),
    crop_box: panel.cropBox,
    start_image_path: path,
    start_image_url: url
  });
  genLog({ok: true, selected_panel: panelNo, start_image_path: path, crop_box: panel.cropBox});
}
async function confirmAndRunPanelAnimations() {
  const planned = generationState.fanout;
  const count = planned?.detectedPanelCount || planned?.panels?.length || 0;
  if (!count) return flash("crop the grid first");
  if (!confirm(`Create ${count} paid Kling animation job${count === 1 ? "" : "s"} from the cropped panels?`)) return null;
  return await fanoutPanels({dryRun: false, maxJobs: count});
}
async function createGridFanoutWorkflow() {
  if (!currentCampaign()) return flash("pick a campaign first");
  if (!document.getElementById("genStem").value) await fillNextClipId();
  let sourceImage = document.getElementById("genImagePath")?.value || generationState.local_image_path;
  if (!sourceImage) {
    if (!confirm("Create one paid Higgsfield Soul grid for Stacey? After it returns, Reel Factory will detect panels and ask before creating paid Kling jobs.")) return;
    const imageResult = await createSoulImage({skipConfirm: true, imageMode: "single"});
    if (!imageResult?.ok) return imageResult;
    sourceImage = imageResult.local_image_path || imageResult.lineage?.assets?.localPaths?.image;
  }
  const plan = await fanoutPanels({dryRun: true});
  if (!plan?.cropManifest) return plan;
  const confidence = plan.gridDetection?.confidence || "unknown";
  if (confidence !== "high" && confidence !== "operator_override") {
    flash("panel crop needs operator review before paid animations");
    return plan;
  }
  return await confirmAndRunPanelAnimations();
}
async function createSixPackSoulImages() {
  if (!confirm("Create six paid Higgsfield Soul image jobs for Stacey?")) return;
  setGenerationState({status: "running"});
  const r = await fetch("/api/assets/create-image", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      campaign: currentCampaign() || null,
      creator: "Stacey",
      prompt_json: generationPromptPath(),
      image_mode: "six-pack",
      wait: true,
      download: true
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    return genLog(j);
  }
  const imagePath = j.local_image_path || j.lineage?.assets?.localPaths?.image;
  if (imagePath) document.getElementById("genImagePath").value = imagePath;
  setGenerationState({
    status: "six-pack ready",
    local_image_path: imagePath || generationState.local_image_path,
    local_image_url: j.local_image_url || j.image_url || generationState.local_image_url,
    six_pack_paths: j.six_pack_paths || {},
    six_pack_urls: j.six_pack_urls || {},
    image_job_id: j.image_job_id,
    image_job_ids: j.image_job_ids || [],
    asset_generation_id: j.asset_generation_id || generationState.asset_generation_id,
    grid_status: j.grid_status,
    lineage_path: j.lineage_path || generationState.lineage_path
  });
  genLog(j);
}
function selectSixPackVariation(key) {
  const path = generationState.six_pack_paths?.[key];
  const url = generationState.six_pack_urls?.[key];
  if (!path) return flash("six-pack image missing");
  const start = document.getElementById("genStartImage");
  if (start) start.value = path;
  setGenerationState({
    status: "panel selected",
    selected_panel: key,
    start_image_path: path,
    start_image_url: url
  });
  genLog({ok: true, selected_panel: key, start_image_path: path, start_image_url: url});
}
async function selectPanel(panel) {
  const sourceImage = document.getElementById("genImagePath")?.value;
  if (!sourceImage) return flash("set Soul image path first");
  const r = await fetch("/api/assets/select-panel", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({stem: generationStem(), source_image: sourceImage, panel, asset_generation_id: generationState.asset_generation_id || null})
  });
  const j = await r.json();
  if (j.start_image_path || j.path) document.getElementById("genStartImage").value = j.start_image_path || j.path;
  setGenerationState({
    status: "panel selected",
    selected_panel: j.selected_panel,
    crop_box: j.crop_box,
    start_image_path: j.start_image_path || j.path,
    start_image_url: j.start_image_url || j.url
  });
  genLog(j);
}
async function createKlingVideo() {
  if (!confirm("Create paid Kling video from selected panel/start image?")) return;
  const startImage = document.getElementById("genStartImage")?.value;
  if (!startImage) return flash("select panel/start image first");
  setGenerationState({status: "running"});
  const r = await fetch("/api/assets/create-video", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      campaign: currentCampaign() || null,
      creator: "Stacey",
      prompt_json: generationPromptPath(),
      start_image: startImage,
      selected_panel: generationState.selected_panel || null,
      asset_generation_id: generationState.asset_generation_id || null,
      wait: true,
      download: false
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    return genLog(j);
  }
  setGenerationState({
    status: "Kling video ready",
    video_job_id: j.video_job_id,
    video_result_url: j.video_result_url,
    asset_generation_id: j.asset_generation_id || generationState.asset_generation_id,
    video_lineage_path: j.lineage_path || generationState.video_lineage_path
  });
  genLog(j);
}
async function downloadKlingVideo() {
  const videoUrl = generationState.video_result_url || prompt("Kling result URL:");
  if (!videoUrl) return;
  setGenerationState({status: "running"});
  const r = await fetch("/api/assets/download-video", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationStem(),
      creator: "Stacey",
      prompt_json: generationPromptPath(),
      video_url: videoUrl,
      video_job_id: generationState.video_job_id || null,
      asset_generation_id: generationState.asset_generation_id || null,
      selected_panel: generationState.selected_panel || null,
      start_image: document.getElementById("genStartImage")?.value || null
    })
  });
  const j = await r.json();
  if (!j.ok) {
    setGenerationState({status: "failed"});
    return genLog(j);
  }
  setGenerationState({status: "downloaded", downloaded_stem: j.downloaded_stem || j.stem, source_path: j.source_path, source_url: j.source_url});
  selectedStem = j.downloaded_stem || j.stem || selectedStem;
  gridCropState = {open: true, frame_time: 0.25, boxes: [], grid_preset: {columns: 3, rows: 2}, render_captions: true};
  genLog(j);
  await loadClips();
  await renderDetail();
}
async function renderGeneratedPack() {
  setGenerationState({status: "running"});
  const r = await fetch(`/api/campaigns/${encodeURIComponent(currentCampaign())}/render-pack`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      stem: generationState.downloaded_stem || generationStem(),
      asset_generation_id: generationState.asset_generation_id || null,
      asset_prompt_json: generationPromptPath(),
      recipes: ["v01_original", "v09_caption_bg"],
      max_hooks: 3,
      target_ratios: ["9:16"],
      workers: 2
    })
  });
  const j = await r.json();
  setGenerationState({status: j.ok ? "rendered" : "failed"});
  genLog(j);
  await loadClips();
}

async function openGridCropEditor() {
  if (!selectedStem) return flash("select a grid video first");
  gridCropState = {...gridCropState, open: true, loadedStem: selectedStem};
  await renderDetail();
  await loadGridCropFrame();
}
async function loadGridCropFrame() {
  if (!selectedStem) return;
  const time = gridCropState.frame_time || 0.25;
  const j = await (await fetch(`/api/grid-crop/${selectedStem}/frame?time_sec=${encodeURIComponent(time)}`)).json();
  if (!j.ok) return flash(j.detail || "frame load failed");
  gridCropState = {
    ...gridCropState,
    open: true,
    loadedStem: selectedStem,
    frame_url: j.frame_url,
    frame_path: j.frame_path,
    source_dimensions: j.source_dimensions,
    boxes: j.plan?.boxes?.length ? j.plan.boxes : gridCropState.boxes,
    grid_preset: j.plan?.gridPreset || j.plan?.grid_preset || gridCropState.grid_preset,
    frame_time: j.plan?.frameTime || j.plan?.frame_time || time
  };
  if (!gridCropState.boxes?.length) await suggestGridBoxes(false);
  renderGridCropWorkspace();
}
async function suggestGridBoxes(rerender = true) {
  if (!selectedStem) return;
  const preset = gridCropState.grid_preset || {columns: 3, rows: 2};
  const j = await (await fetch(`/api/grid-crop/${selectedStem}/suggest`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({columns: preset.columns, rows: preset.rows})
  })).json();
  if (!j.ok) return flash(j.detail || "suggest failed");
  gridCropState = {...gridCropState, boxes: j.boxes, grid_preset: j.grid_preset, source_dimensions: j.source_dimensions};
  if (rerender) renderGridCropWorkspace();
}
async function applyGridPreset(columns, rows) {
  gridCropState = {...gridCropState, grid_preset: {columns, rows}};
  await suggestGridBoxes();
}
function renderGridCropWorkspace() {
  const el = document.getElementById("gridCropWorkspace");
  if (!el) return renderDetail();
  const data = {grid_crop: {plan: null}};
  el.outerHTML = gridCropPanel(data);
}
function selectGridCropPanel(id) {
  gridCropState.selected_panel = id;
  renderGridCropWorkspace();
}
function setGridCropEnabled(id, enabled) {
  const b = (gridCropState.boxes || []).find(x => Number(x.id) === Number(id));
  if (b) b.enabled = enabled;
  renderGridCropWorkspace();
}
function setGridCropValue(id, key, value) {
  const b = (gridCropState.boxes || []).find(x => Number(x.id) === Number(id));
  if (!b) return;
  b[key] = Math.max(key === "w" || key === "h" ? 2 : 0, Math.round(Number(value) || 0));
  renderGridCropWorkspace();
}
function startGridCropDrag(ev, id, mode) {
  ev.preventDefault();
  ev.stopPropagation();
  const canvas = document.getElementById("gridCropCanvas");
  const box = (gridCropState.boxes || []).find(x => Number(x.id) === Number(id));
  const dims = gridCropState.source_dimensions || {};
  if (!canvas || !box || !dims.width || !dims.height) return;
  const rect = canvas.getBoundingClientRect();
  gridCropDrag = {
    id,
    mode,
    startX: ev.clientX,
    startY: ev.clientY,
    rect,
    original: {...box},
    dims
  };
  canvas.setPointerCapture?.(ev.pointerId);
  document.addEventListener("pointermove", onGridCropDragMove);
  document.addEventListener("pointerup", stopGridCropDrag, {once: true});
}
function onGridCropDragMove(ev) {
  if (!gridCropDrag) return;
  const b = (gridCropState.boxes || []).find(x => Number(x.id) === Number(gridCropDrag.id));
  if (!b) return;
  const dx = ((ev.clientX - gridCropDrag.startX) / gridCropDrag.rect.width) * gridCropDrag.dims.width;
  const dy = ((ev.clientY - gridCropDrag.startY) / gridCropDrag.rect.height) * gridCropDrag.dims.height;
  if (gridCropDrag.mode === "resize") {
    b.w = Math.max(20, Math.round(gridCropDrag.original.w + dx));
    b.h = Math.max(20, Math.round(gridCropDrag.original.h + dy));
  } else {
    b.x = Math.max(0, Math.round(gridCropDrag.original.x + dx));
    b.y = Math.max(0, Math.round(gridCropDrag.original.y + dy));
  }
  const dims = gridCropDrag.dims;
  b.w = Math.min(b.w, dims.width - b.x);
  b.h = Math.min(b.h, dims.height - b.y);
  updateGridCropBoxDom(b);
}
function stopGridCropDrag() {
  document.removeEventListener("pointermove", onGridCropDragMove);
  gridCropDrag = null;
  renderGridCropWorkspace();
}
function updateGridCropBoxDom(b) {
  const dims = gridCropState.source_dimensions || {};
  const el = document.querySelector(`.grid-crop-box[data-panel="${b.id}"]`);
  if (!el || !dims.width || !dims.height) return;
  el.style.left = `${(b.x / dims.width) * 100}%`;
  el.style.top = `${(b.y / dims.height) * 100}%`;
  el.style.width = `${(b.w / dims.width) * 100}%`;
  el.style.height = `${(b.h / dims.height) * 100}%`;
}
async function saveGridCropPlan() {
  if (!selectedStem) return;
  if (!gridCropState.source_dimensions) await loadGridCropFrame();
  const preset = gridCropState.grid_preset || {columns: 3, rows: 2};
  const j = await (await fetch(`/api/grid-crop/${selectedStem}/plan`, {
    method: "PUT",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      frame_time: gridCropState.frame_time || 0.25,
      columns: preset.columns,
      rows: preset.rows,
      boxes: gridCropState.boxes || [],
      render_mode: "fit_nocrop"
    })
  })).json();
  if (!j.ok) return flash(j.detail || "crop plan save failed");
  gridCropState = {...gridCropState, boxes: j.plan.boxes, plan_path: j.plan_path};
  genLog(j);
  flash("crop plan saved");
  renderGridCropWorkspace();
}
async function previewGridPanel() {
  await saveGridCropPlan();
  const panel = gridCropState.selected_panel || (gridCropState.boxes?.[0]?.id || 1);
  const j = await (await fetch(`/api/grid-crop/${selectedStem}/preview`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({panel_id: panel})
  })).json();
  if (!j.ok) return flash(j.detail || "preview failed");
  gridCropState = {...gridCropState, preview_url: j.preview_url};
  renderGridCropWorkspace();
}
async function renderGridCropPanels() {
  if (!confirm("Crop enabled panels from this animated grid and render captions with fit/no-crop?")) return;
  await saveGridCropPlan();
  flash("cropping grid panels...");
  const j = await (await fetch(`/api/grid-crop/${selectedStem}/render`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({render_captions: gridCropState.render_captions !== false})
  })).json();
  if (!j.ok) return flash(j.detail || "grid render failed");
  genLog(j);
  flash(`created ${j.installed?.length || 0} panel clips`);
  await loadClips();
  await renderDetail();
}

async function whisperSync() {
  if (!selectedStem) return;
  flash("running speech timing…");
  const r = await fetch(`/api/clips/${selectedStem}/whisper-sync`, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({})});
  const j = await r.json();
  if (!j.ok) return flash(j.error || "speech timing unavailable");
  flash(j.written ? "speech captions written" : "speech captions already exist");
}

async function exportApproved() {
  const acct = document.getElementById("acct").value || "default";
  const r = await fetch("/api/export-approved", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({account: acct, platform: "ig", date: new Date().toISOString().slice(0, 10)})
  });
  const j = await r.json();
  flash(`exported ${j.count || 0} approved outputs`);
}

async function saveHooks(stem) {
  const hooks = collectHooksFromEditor();
  const pairs = duplicateHookPairs(hooks);
  if (pairs.length && !confirm(`Found ${pairs.length} duplicate hook${pairs.length === 1 ? '' : 's'}. Save anyway?`)) {
    return;
  }
  const r = await fetch(`/api/clips/${stem}/hooks`, {
    method: "PUT", headers: {"content-type": "application/json"},
    body: JSON.stringify({hooks, generation: lastAiGeneration || undefined})
  });
  const j = await r.json();
  if (j.ok) {
    flash(`saved ${j.hook_count} hooks${j.duplicates?.length ? ` · ${j.duplicates.length} duplicate warning${j.duplicates.length === 1 ? '' : 's'}` : ''}${j.semantic_duplicates?.length ? ` · ${j.semantic_duplicates.length} semantic warning${j.semantic_duplicates.length === 1 ? '' : 's'}` : ''}`);
  } else {
    alert(`error: ${j.error || 'unknown'}`);
  }
  await loadClips();
}

async function spinHook() {
  const base = prompt("Enter a base hook to spin into 8 stylistic variations:");
  if (!base) return;
  const r = await fetch("/api/spin", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({base, n: 8})
  });
  const j = await r.json();
  currentHooks = collectHooksFromEditor().concat(j.variations);
  rerenderHookEditor();
  updateHookWarnings();
}

async function aiRewriteHook() {
  const base = prompt("Base hook for Ollama to rewrite:");
  if (!base) return;
  const model = prompt("Ollama model name:", "llama3.2:3b") || "llama3.2:3b";
  const r = await fetch("/api/ai-hooks", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({backend: "ollama", model, base, n: 8, strict: true, reject_identical: true})
  });
  const j = await r.json();
  if (!j.ok) {
    alert(j.error || "Ollama hook generation is unavailable");
    return;
  }
  if ((j.rejected || []).length) {
    flash(`${j.rejected.length} AI hook${j.rejected.length === 1 ? '' : 's'} rejected`);
    alert(`Rejected AI hooks:\n${j.rejected.map(r => `- ${r.reason}: ${r.hook}`).join("\n").slice(0, 1200)}`);
  }
  lastAiGeneration = {
    generation_id: j.generationId,
    backend: j.backend,
    model: j.model,
    created_at: new Date().toISOString(),
    caption_hashes: (j.quality || []).map(q => q.captionHash).filter(Boolean),
    quality: j.quality || []
  };
  currentHooks = collectHooksFromEditor().concat(j.hooks || []);
  rerenderHookEditor();
  updateHookWarnings();
}

async function refreshAiHookStatus() {
  const btn = document.getElementById("aiHookBtn");
  if (!btn) return;
  try {
    const j = await (await fetch("/api/ai-hooks/status?model=llama3.2%3A3b")).json();
    btn.disabled = !j.ok;
    btn.title = j.ok ? "Rewrite hooks with local Ollama" : j.message;
  } catch (e) {
    btn.disabled = true;
    btn.title = "Ollama status check failed";
  }
}

function toggleCompare(name, url) {
  const existing = previewSelection.findIndex(o => o.name === name);
  if (existing >= 0) previewSelection.splice(existing, 1);
  else if (previewSelection.length < 4) previewSelection.push({name, url});
  else flash("compare up to 4 outputs");
  renderComparePanel();
}
function renderComparePanel() {
  const panel = document.getElementById("comparePanel");
  if (!panel) return;
  if (!previewSelection.length) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="flex items-center justify-between mb-2">
      <div class="text-xs uppercase tracking-wide text-gray-400">synced preview</div>
      <div class="flex gap-2"><button class="tag" onclick="previewPlayAll()">play all</button><button class="tag" onclick="previewPauseAll()">pause all</button></div>
    </div>
    <div class="grid grid-cols-${Math.min(4, previewSelection.length)} gap-2">
      ${previewSelection.map(o => `<video class="compare-video bg-black rounded" src="${o.url}" controls muted preload="metadata"></video>`).join("")}
    </div>
  `;
}
function previewPlayAll() { document.querySelectorAll(".compare-video").forEach(v => v.play()); }
function previewPauseAll() { document.querySelectorAll(".compare-video").forEach(v => v.pause()); }

async function generateThumbs() {
  if (!selectedStem) return;
  await fetch("/api/thumbnails", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({clip: selectedStem})
  });
  flash("thumbnails generated");
  await renderDetail();
}

async function runReadiness() {
  if (!selectedStem) return;
  const r = await fetch("/api/readiness", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({clip: selectedStem, platform: "instagram_reels"})
  });
  const j = await r.json();
  if (!j.ok) return flash(j.detail || "readiness failed");
  flash(`readiness: ${j.summary?.warn || 0} warning${j.summary?.warn === 1 ? '' : 's'}`);
  await renderDetail();
}

async function muxAudio() {
  if (!selectedStem) return;
  const audioTag = prompt("Audio tag to use from 03_audio_library:", "trending") || "";
  const r = await fetch("/api/audio-mux", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({clip: selectedStem, audio_tag: audioTag || null})
  });
  const j = await r.json();
  if (!j.ok) alert(j.error || "audio mux failed");
  else flash(`audio muxed ${j.count || 0} output${j.count === 1 ? '' : 's'}`);
  await renderDetail();
}

async function deleteClip(stem) {
  if (!confirm(`Delete ${stem}? This removes the source video, captions, and ALL ${clips.find(c=>c.stem===stem)?.output_count||0} processed outputs.`)) return;
  await fetch(`/api/clips/${stem}`, {method: "DELETE"});
  selectedStem = null;
  document.getElementById("detail").innerHTML = '<p class="text-gray-500 text-sm">drop a video above, or select one on the left</p>';
  await loadClips();
}

async function startRun() {
  if (selectedStem) {
    const selected = clips.find(c => c.stem === selectedStem);
    if (!selected || Number(selected.hook_count || 0) === 0) {
      await autoGenerateHooks(selectedStem, {silent: true});
    }
  }
  const acct = document.getElementById("acct").value;
  const campaign = document.getElementById("campaign")?.value || "";
  const textVariation = document.getElementById("textVariation").value;
  const workers = parseInt(document.getElementById("workers").value, 10);
  const mezzanine = document.getElementById("mezzanine").checked;
  const captionRenderer = document.getElementById("captionRenderer").value;
  const placementMode = document.getElementById("placementMode").value;
  const outputProfile = document.getElementById("outputProfile").value;
  const targetRatios = document.getElementById("targetRatios").value.split(",");
  const aiQc = document.getElementById("aiQc").checked;
  const readiness = document.getElementById("readiness").checked;
  document.getElementById("run-bar").classList.remove("hidden");
  document.getElementById("run-state").textContent = "starting…";
  const body = {account: acct || null, campaign: campaign || null, text_variation: textVariation, workers, mezzanine, caption_renderer: captionRenderer, placement_mode: placementMode, output_profile: outputProfile, target_ratios: targetRatios, ai_qc: aiQc, readiness};
  if (selectedStem) body.only_clip = selectedStem;
  await fetch("/api/run", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify(body)
  });
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pollRun, 1000);
}

async function pollRun() {
  const s = await (await fetch("/api/run/status")).json();
  const progress = s.total ? ` ${s.completed || 0}/${s.total}` : "";
  document.getElementById("run-state").textContent = s.running ? `running…${progress}` : (s.summary ? `done${progress}` : "idle");
  document.getElementById("run-elapsed").textContent = `${Math.round(s.elapsed)}s`;
  document.getElementById("run-log").innerHTML = s.log_tail.map(l => `<div>${escHtml(l)}</div>`).join("");
  document.getElementById("run-log").scrollTop = 99999;
  if (!s.running && s.summary) {
    clearInterval(pollInterval); pollInterval = null;
    document.querySelector("#run-bar .spin").style.display = "none";
    await loadClips();
    if (selectedStem) await renderDetail();
  }
}

// DROPZONE
const dz = document.getElementById("dz");
const fi = document.getElementById("fileInput");
dz.addEventListener("click", () => fi.click());
fi.addEventListener("change", e => uploadFiles(e.target.files));
["dragenter","dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("dragover"); }));
["dragleave","drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("dragover"); }));
dz.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
window.addEventListener("keydown", e => {
  if (e.key === "Escape" && reviewModalState) {
    reviewModalState = null;
    renderDetail();
    return;
  }
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  if (e.key.toLowerCase() === "a") batchReview("approved");
  if (e.key.toLowerCase() === "r") batchReview("rejected");
  if (e.key.toLowerCase() === "d") batchReview("draft");
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    const idx = clips.findIndex(c => c.stem === selectedStem);
    const next = e.key === "ArrowRight" ? idx + 1 : idx - 1;
    if (clips[next]) selectClip(clips[next].stem);
  }
});

async function uploadFiles(files) {
  if (!files || files.length === 0) return;
  for (const f of files) {
    if (!f.name.toLowerCase().match(/\.(mp4|mov|m4v)$/)) {
      flash(`skipped ${f.name} (not a video)`);
      continue;
    }
    flash(`uploading ${f.name}…`);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch("/api/upload", { method: "POST", body: fd });
      const j = await r.json();
      if (j.ok) {
        flash(`saved as ${j.stem}`);
        await loadClips();
        await autoGenerateHooks(j.stem, {silent: true});
        await selectClip(j.stem);
        flash(`${j.stem} ready — click Make reels now`);
      } else {
        flash(`error uploading ${f.name}`);
      }
    } catch (e) {
      flash(`upload failed: ${e}`);
    }
  }
}

// FLASH MESSAGE
function flash(msg) {
  let el = document.getElementById("flash");
  if (!el) {
    el = document.createElement("div");
    el.id = "flash";
    el.style.cssText = "position:fixed;bottom:24px;right:24px;background:#ffffff;border:1px solid #ed6755;color:#101114;padding:12px 18px;border-radius:8px;font-size:13px;z-index:1000;transition:opacity .3s;box-shadow:0 12px 32px rgba(20,25,32,.12);";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.opacity = "1";
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.style.opacity = "0", 2500);
}

document.getElementById("run").addEventListener("click", startRun);
configureCreatorTabs("reel");
initSourceSearch();
loadConfig().then(async () => {
  await loadAccounts();
  await loadCampaigns();
  await loadClips();
  await loadDashboardSummary();
  if (!selectedStem && clips.length) await selectClip(clips[0].stem);
});

// ── Auto-shutdown plumbing ────────────────────────────────────────
// Heartbeat: every 5s, tell the server we're still here.
setInterval(() => {
  fetch("/api/heartbeat", { method: "POST" }).catch(() => {});
}, 5000);
// Send one immediately on load too
fetch("/api/heartbeat", { method: "POST" }).catch(() => {});

// On tab/window close: send an explicit shutdown beacon so the server
// exits within ~1s instead of waiting for the heartbeat to lapse.
window.addEventListener("pagehide", () => {
  if (creatorOsTabSwitching) return;
  navigator.sendBeacon("/api/shutdown", "");
});
window.addEventListener("beforeunload", () => {
  if (creatorOsTabSwitching) return;
  navigator.sendBeacon("/api/shutdown", "");
});
