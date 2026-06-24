const $ = (id) => document.getElementById(id);
const SELECTED_CAMPAIGN_KEY = "campaignFactory.selectedCampaign";
let usageByAsset = {};
let readinessByAsset = {};

window.__campaignFactoryAppLoaded = true;
console.info("Campaign Factory frontend loaded.");

function bind(id, handler) {
  const element = $(id);
  if (!element) {
    console.warn(`Missing UI control: ${id}`);
    return;
  }
  element.onclick = handler;
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function log(value) {
  $("log").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function h(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function configureCreatorTabs(activeApp) {
  const host = window.location.hostname || "localhost";
  const protocol = window.location.protocol || "http:";
  const campaignTab = $("campaignFactoryTab");
  const reelTab = $("reelFactoryTab");
  if (campaignTab) {
    campaignTab.href = `${protocol}//${host}:8877/`;
    campaignTab.classList.toggle("active", activeApp === "campaign");
  }
  if (reelTab) {
    reelTab.href = `${protocol}//${host}:8765/`;
    reelTab.classList.toggle("active", activeApp === "reel");
  }
}

function basePayload() {
  return {
    campaign: $("campaign").value.trim(),
    model: $("model").value.trim(),
    accounts: $("accounts").value.split(",").map((s) => s.trim()).filter(Boolean),
  };
}

function seedInitialCampaign() {
  const campaignInput = $("campaign");
  if (!campaignInput) return;
  const params = new URLSearchParams(window.location.search);
  const queryCampaign = params.get("campaign");
  const storedCampaign = window.localStorage.getItem(SELECTED_CAMPAIGN_KEY);
  const usableStoredCampaign = storedCampaign && storedCampaign !== campaignInput.placeholder ? storedCampaign : "";
  const browserFilledPlaceholder = campaignInput.value.trim() === campaignInput.placeholder.trim();
  if (queryCampaign) {
    campaignInput.value = queryCampaign;
  } else if (usableStoredCampaign) {
    campaignInput.value = usableStoredCampaign;
  } else if (browserFilledPlaceholder) {
    campaignInput.value = "";
  }
}

async function fetchDashboard(campaign) {
  const request = async (slug) => {
    const url = slug ? `/api/dashboard?campaign=${encodeURIComponent(slug)}` : "/api/dashboard";
    const res = await fetch(url);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || `Dashboard load failed (${res.status})`);
    return data;
  };
  if (!campaign) return request("");
  try {
    return await request(campaign);
  } catch (error) {
    window.localStorage.removeItem(SELECTED_CAMPAIGN_KEY);
    $("campaign").value = "";
    return request("");
  }
}

function auditClass(status) {
  if (status === "approved_candidate") return "ok";
  if (status === "pending") return "muted";
  return "warn";
}

function stateClass(state) {
  if (state === "ready") return "ok";
  if (state === "warning") return "warn";
  return "bad";
}

function statusTone(value) {
  const normalized = String(value || "").toLowerCase();
  if (["ready", "good", "approved", "success", "upload ready"].some((word) => normalized.includes(word))) return "ok";
  if (["blocked", "failed", "rejected", "critical", "high"].some((word) => normalized.includes(word))) return "bad";
  if (["warning", "review", "needs", "pending"].some((word) => normalized.includes(word))) return "warn";
  return "muted";
}

function smallStatus(label, value, tone) {
  return `
    <div class="status-card ${tone || statusTone(label)}">
      <span>${h(label)}</span>
      <b>${h(value ?? 0)}</b>
    </div>
  `;
}

function usageLine(assetId) {
  const usage = usageByAsset[assetId]?.usage || readinessByAsset[assetId]?.usage;
  if (!usage) return "usage not checked";
  return `${usage.draft || 0} draft · ${usage.scheduled || 0} scheduled · ${usage.published || 0} published`;
}

function performanceLine(asset) {
  const latest = asset.latestPerformance?.metrics;
  const score = asset.performanceScore;
  if (!latest && score == null) return "performance not synced";
  const parts = [];
  if (score != null) parts.push(`perf score ${score}`);
  if (latest) {
    if (latest.impressions != null) parts.push(`${latest.impressions} impressions`);
    if (latest.reach != null) parts.push(`${latest.reach} reach`);
    parts.push(`${latest.views ?? 0} views`);
    parts.push(`${latest.shares ?? 0} shares`);
    parts.push(`${latest.saves ?? 0} saves`);
  }
  return parts.join(" · ");
}

function recentActivityLine(event) {
  return `
    <div class="event-row ${h(event.status)}">
      <span>${h((event.createdAt || "").replace("T", " ").slice(0, 19))}</span>
      <b>${h(event.eventType)}</b>
      <span>${h(event.status)}</span>
      <span>${h(event.message)}</span>
    </div>
  `;
}

function recentJobLine(job) {
  const timing = job.finishedAt || job.startedAt || job.createdAt || "";
  return `
    <div class="event-row ${h(job.status)}">
      <span>${h(timing.replace("T", " ").slice(0, 19))}</span>
      <b>${h(job.jobType)}</b>
      <span>${h(job.status)}</span>
      <span>${job.error ? h(job.error) : `attempts ${h(job.attemptCount ?? 0)}`}</span>
    </div>
  `;
}

function healthCards(health) {
  if (!health) return "";
  const counts = health.counts || {};
  const items = [
    ["Sources", counts.sourcesImported],
    ["Rendered", counts.renderedAssets],
    ["Audited", counts.auditedAssets],
    ["Approved", counts.approvedAssets],
    ["Rejected", counts.rejectedAssets],
    ["Ready", counts.exportReadyAssets],
    ["Warnings", counts.warningAssets],
    ["Blocked", counts.blockedAssets],
    ["Failed Jobs", counts.failedJobs],
  ];
  return `<div class="health-grid">${items.map(([label, value]) => `
    <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
  `).join("")}</div>`;
}

function topStatusStrip(data, rendered) {
  const counts = data.health?.counts || {};
  const trust = data.trust || {};
  const audioCounts = data.audioWorkflow?.counts || {};
  const ready = counts.exportReadyAssets ?? rendered.filter((asset) => readinessFor(asset).state === "ready").length;
  const review = counts.warningAssets ?? rendered.filter((asset) => readinessFor(asset).state === "warning" || asset.review_state === "review_ready").length;
  const blocked = counts.blockedAssets ?? rendered.filter((asset) => readinessFor(asset).state === "blocked").length;
  const health = blocked > 0 ? "Review" : "Good";
  return `
    ${smallStatus("Health", health, blocked > 0 ? "warn" : "ok")}
    ${smallStatus("Rendered", counts.renderedAssets ?? rendered.length, "muted")}
    ${smallStatus("Review Ready", review, review > 0 ? "warn" : "ok")}
    ${smallStatus("Upload Ready", ready, ready > 0 ? "ok" : "muted")}
    ${smallStatus("Exceptions", trust.exceptions?.openCount ?? 0, (trust.exceptions?.openCount ?? 0) > 0 ? "warn" : "ok")}
    ${smallStatus("Trust Score", trust.trustScore ?? "n/a", "ok")}
    ${smallStatus("Needs Audio", audioCounts.needs_audio ?? 0, (audioCounts.needs_audio ?? 0) > 0 ? "bad" : "ok")}
  `;
}

function audioGateMini(audioWorkflow) {
  const counts = audioWorkflow?.counts || {};
  return `
    ${smallStatus("Needs Audio", counts.needs_audio ?? 0, (counts.needs_audio ?? 0) > 0 ? "bad" : "ok")}
    ${smallStatus("Pending Review", counts.selected_not_attached ?? 0, (counts.selected_not_attached ?? 0) > 0 ? "warn" : "muted")}
    ${smallStatus("Ready", counts.ready ?? 0, "ok")}
    ${smallStatus("Blocked", counts.blocked ?? 0, (counts.blocked ?? 0) > 0 ? "bad" : "muted")}
  `;
}

function creativePlanMini(plan) {
  const counts = plan?.counts || {};
  return `
    ${smallStatus("Daily Goal", `${counts.reviewed_outputs ?? 0} / ${counts.rendered_outputs ?? 0}`, "warn")}
    ${smallStatus("Rendered", counts.rendered_outputs ?? 0, "muted")}
    ${smallStatus("Reviewed", counts.reviewed_outputs ?? 0, "ok")}
  `;
}

function newBatchMini(rendered, data) {
  const counts = data.health?.counts || {};
  return `
    ${smallStatus("Variants to Review", counts.warningAssets ?? rendered.filter((asset) => asset.review_state === "review_ready").length, "warn")}
    ${smallStatus("Approved", counts.approvedAssets ?? rendered.filter((asset) => asset.review_state === "approved").length, "ok")}
    ${smallStatus("Failed Jobs", counts.failedJobs ?? 0, (counts.failedJobs ?? 0) > 0 ? "bad" : "muted")}
  `;
}

function distributionMini(distribution) {
  const counts = distribution?.surfaceCounts || {};
  return `
    ${smallStatus("Preview Slots", distribution?.previewScheduledPlans ?? 0, "muted")}
    ${smallStatus("Unplanned", distribution?.unplannedApprovedAssets ?? 0, (distribution?.unplannedApprovedAssets ?? 0) > 0 ? "warn" : "ok")}
    ${smallStatus("Trial / Reel", `${counts.trial_reel || 0} / ${counts.regular_reel || 0}`, "muted")}
  `;
}

function distributionCards(distribution) {
  if (!distribution) return "";
  const counts = distribution.surfaceCounts || {};
  const items = [
    ["Trial", counts.trial_reel || 0],
    ["Reel", counts.regular_reel || 0],
    ["Story CTA", counts.story_cta || 0],
    ["Unplanned", distribution.unplannedApprovedAssets || 0],
    ["Preview slots", distribution.previewScheduledPlans || 0],
  ];
  return `
    <h3>Distribution</h3>
    <div class="health-grid">${items.map(([label, value]) => `
      <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
    `).join("")}</div>
  `;
}

function audioWorkflowCards(audioWorkflow) {
  if (!audioWorkflow) return "";
  const counts = audioWorkflow.counts || {};
  const top = audioWorkflow.topRecommendedAudio || [];
  const items = [
    ["Needs audio", counts.needs_audio],
    ["Selected", counts.selected_not_attached],
    ["Blocked", counts.blocked],
    ["Ready", counts.ready],
  ];
  return `
    <h3>Native Audio</h3>
    <div class="health-grid">${items.map(([label, value]) => `
      <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
    `).join("")}</div>
    ${top.length ? `
      <div class="asset-small">
        <b>Top recommendations</b><br>
        ${top.slice(0, 5).map((item) => {
          const title = item.audio_title || "Untitled audio";
          const artist = item.artist_name ? ` · ${item.artist_name}` : "";
          const freshness = item.freshness ? ` · ${item.freshness}` : "";
          return `${h(title)}${h(artist)} · ${h(item.count)} asset${item.count === 1 ? "" : "s"}${h(freshness)}`;
        }).join("<br>")}
      </div>
    ` : ""}
  `;
}

function dailyProductionCards(dailyProduction) {
  if (!dailyProduction) return "";
  const items = [
    ["Prompt ready", dailyProduction.promptReady],
    ["Generated", dailyProduction.generated],
    ["Sent to pipeline", dailyProduction.sentToPipeline],
    ["Reviewed", dailyProduction.reviewed],
    ["Posted/scheduled", dailyProduction.postedOrScheduled],
    ["Remaining", dailyProduction.remainingBaseVideos],
  ];
  return `
    <h3>Daily 10 Base Videos</h3>
    <div class="health-grid">${items.map(([label, value]) => `
      <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
    `).join("")}</div>
  `;
}

function trustSummaryCards(trust) {
  if (!trust) return "";
  const severity = trust.exceptions?.severityCounts || {};
  const memory = trust.accountMemory || {};
  const recommendations = trust.recommendations || {};
  const items = [
    ["Trust score", trust.trustScore],
    ["Autonomy", trust.autonomyLevel],
    ["Open exceptions", trust.exceptions?.openCount ?? 0],
    ["High/Critical", (severity.high || 0) + (severity.critical || 0)],
    ["Account memory", memory.accountCount ?? 0],
    ["Accepted waiting", recommendations.acceptedWaitingExecution ?? 0],
  ];
  return `
    <h3>Trust Layer · ${h(trust.recommendedAction || "ready")}</h3>
    <div class="health-grid trust-health">${items.map(([label, value]) => `
      <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
    `).join("")}</div>
  `;
}

function creativePlanCards(plan) {
  if (!plan) return "";
  const counts = plan.counts || {};
  const items = [
    ["References", counts.references],
    ["Analyses", counts.analyses],
    ["Image prompts", counts.image_prompts],
    ["Video prompts", counts.video_prompts],
    ["Generated", counts.generated_videos],
    ["Rendered", counts.rendered_outputs],
    ["Reviewed", counts.reviewed_outputs],
    ["Measured", counts.measured_items],
  ];
  const actions = Array.isArray(plan.next_actions) ? plan.next_actions : [];
  return `
    <h3>Creative Plan · ${h(plan.name)} · ${h(plan.status)}</h3>
    <div class="health-grid">${items.map(([label, value]) => `
      <div class="metric"><span>${h(label)}</span><b>${h(value ?? 0)}</b></div>
    `).join("")}</div>
    <div class="asset-small"><b>Next actions</b><br>${actions.map((action) => `• ${h(action)}`).join("<br>")}</div>
  `;
}

const RECOMMENDATION_STATUSES = ["proposed", "accepted", "executed", "posted", "measured", "proved/disproved"];

function recommendationStatusClass(status, step) {
  if (!status) return "";
  if (step === "proved/disproved" && (status === "proved" || status === "disproved")) return "active";
  const order = { proposed: 0, accepted: 1, executed: 2, posted: 3, measured: 4, proved: 5, disproved: 5 };
  const stepOrder = { proposed: 0, accepted: 1, executed: 2, posted: 3, measured: 4, "proved/disproved": 5 };
  if (step === status) return "active";
  return (order[status] ?? -1) > (stepOrder[step] ?? 99) ? "done" : "";
}

function compactJson(value) {
  if (!value || (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length)) return "None";
  return JSON.stringify(value, null, 2);
}

function recommendationRail(status) {
  return `
    <div class="recommendation-rail">
      ${RECOMMENDATION_STATUSES.map((step) => `
        <span class="${recommendationStatusClass(status, step)}">${h(step)}</span>
      `).join("")}
    </div>
  `;
}

function recommendationScoreLine(item) {
  const breakdown = item.scoreBreakdown || {};
  const parts = [
    ["perf", breakdown.performance],
    ["reference", breakdown.referencePattern],
    ["audit", breakdown.auditReadiness],
    ["account", breakdown.accountFitFatigue],
    ["novelty", breakdown.novelty],
    ["ops", breakdown.operationalReadiness],
  ].filter(([, value]) => value != null);
  return parts.map(([label, value]) => `${label} ${value}`).join(" · ");
}

function accountMemoryLine(memory) {
  if (!memory) return "account memory not rebuilt";
  const topPattern = (memory.patternStats || [])[0];
  const topWindow = (memory.postingWindows || [])[0];
  const pieces = [
    `${memory.confidence || "low"} confidence`,
    `${memory.sampleSize ?? 0} samples`,
    memory.performanceScore != null ? `score ${memory.performanceScore}` : null,
    topPattern ? `top ${topPattern.pattern || topPattern.key || "pattern"}` : null,
    topWindow ? `best ${topWindow.window || topWindow.hour || "window"}` : null,
  ].filter(Boolean);
  return pieces.join(" · ");
}

function exceptionsLine(exceptions) {
  const open = (exceptions || []).filter((item) => item.status !== "resolved");
  if (!open.length) return "no open exceptions";
  const high = open.filter((item) => ["critical", "high"].includes(item.severity)).length;
  return `${open.length} open · ${high} high`;
}

function recommendationCard(item) {
  const statusClass = item.status === "proved" ? "ok" : (item.status === "disproved" || item.status === "rejected" ? "bad" : "warn");
  const baseline = item.baseline || {};
  const outcome = item.outcome || {};
  const decision = item.decision || {};
  const dataQuality = item.dataQuality || {};
  const accountMemory = item.accountMemory || null;
  const accountFit = item.accountFitEvidence || {};
  const exceptions = item.exceptions || [];
  const reasons = (item.reasons || []).slice(0, 4).join(" · ");
  const risks = (item.risks || []).slice(0, 4).join(" · ");
  return `
    <div class="recommendation-card">
      <div class="recommendation-topline">
        <div>
          <b>#${h(item.rank)} · ${h(item.filename || item.referencePattern?.label || item.recommendationId)}</b>
          <div class="asset-small">
            score ${h(item.score)} · confidence ${h(item.confidence)} · ${h(item.targetAccount || "no account")}
          </div>
        </div>
        <span class="${statusClass}">${h(item.status || "proposed")}</span>
      </div>
      ${recommendationRail(item.status || "proposed")}
      <div class="recommendation-summary">
        <div>
          <h4>Why</h4>
          <p>${h(reasons || "No reasons recorded.")}</p>
          <p class="muted">${h(recommendationScoreLine(item) || "No score breakdown.")}</p>
          ${risks ? `<p class="warn">${h(risks)}</p>` : ""}
        </div>
        <div>
          <h4>Data</h4>
          <p>${h(dataQuality.level || "unknown")} · sample ${h(dataQuality.sampleSize ?? "-")}</p>
          <p class="muted">${h((dataQuality.missing || []).join(", ") || "complete enough")}</p>
        </div>
        <div>
          <h4>Outcome</h4>
          <p>${h(outcome.status || "not measured")} · ${h(item.measurementVersion || outcome.measurementVersion || "no measurement")}</p>
          <p class="muted">baseline ${h(baseline.avgScore ?? outcome.baselineScore ?? "-")} · outcome ${h(outcome.outcomeScore ?? "-")}</p>
        </div>
        <div>
          <h4>Trust</h4>
          <p>${h(item.autonomyLevel || "level_1")} · ${h(item.executionStatus || "not_started")}</p>
          <p class="muted">${h(accountMemoryLine(accountMemory))}</p>
          <p class="${exceptions.length ? "warn" : "muted"}">${h(exceptionsLine(exceptions))}</p>
        </div>
      </div>
      <details class="recommendation-details">
        <summary>Why blocked? Evidence, baseline, account memory</summary>
        <div class="recommendation-detail-grid">
          <pre>${h(compactJson(item.evidence))}</pre>
          <pre>${h(compactJson(baseline))}</pre>
          <pre>${h(compactJson(accountFit))}</pre>
          <pre>${h(compactJson(exceptions))}</pre>
          <pre>${h(compactJson(decision))}</pre>
          <pre>${h(compactJson(outcome))}</pre>
        </div>
      </details>
      <div class="recommendation-actions">
        <button onclick="acceptRecommendation('${h(item.recommendationId)}')" ${item.status !== "proposed" ? "disabled" : ""}>Accept</button>
        <button onclick="rejectRecommendation('${h(item.recommendationId)}')" ${["rejected", "proved", "disproved"].includes(item.status) ? "disabled" : ""}>Reject</button>
        <button onclick="executeRecommendation('${h(item.recommendationId)}')" ${!["accepted", "executed"].includes(item.status) ? "disabled" : ""}>Execute</button>
        <button onclick="linkRecommendation('${h(item.recommendationId)}')">Link</button>
        <button onclick="measureRecommendation('${h(item.recommendationId)}')" ${!["posted", "executed", "measured"].includes(item.status) ? "disabled" : ""}>Measure</button>
      </div>
    </div>
  `;
}

async function loadRecommendations() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    $("recommendations").innerHTML = `<p class="muted">Select a campaign to see recommendations.</p>`;
    return;
  }
  const res = await fetch(`/api/recommendations?campaign=${encodeURIComponent(campaign)}&limit=5`);
  const data = await res.json();
  if (!res.ok) {
    $("recommendations").innerHTML = `<p class="bad">${h(data.detail || "Recommendations unavailable.")}</p>`;
    return;
  }
  const runs = data.runs || [];
  const latest = runs[0];
  const items = latest?.items || [];
  setText("recommendationCount", items.length);
  $("recommendations").innerHTML = items.length ? `
    <div class="recommendation-run-meta">
      <span class="pill">${h(latest.scoringVersion || "recommendation_score.v1")}</span>
      <span class="pill">${h((latest.createdAt || "").replace("T", " ").slice(0, 19))}</span>
      <span class="pill">${h(items.length)} item${items.length === 1 ? "" : "s"}</span>
    </div>
    <div class="recommendation-grid">${items.map(recommendationCard).join("")}</div>
  ` : `<p class="muted">No persisted recommendations yet.</p>`;
}

async function loadAutonomyPolicy() {
  const res = await fetch("/api/autonomy-policy");
  const data = await res.json();
  if (!res.ok) {
    log(data.detail || "Autonomy policy unavailable.");
    return;
  }
  $("autonomyLevel").value = data.level || "level_2";
}

async function saveAutonomyPolicy() {
  await post("/api/autonomy-policy", { level: $("autonomyLevel").value });
}

async function loadAccountMemory() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    $("accountMemory").innerHTML = `<p class="muted">Select a campaign to see account memory.</p>`;
    return;
  }
  const account = $("accounts").value.split(",").map((s) => s.trim()).filter(Boolean)[0];
  const query = account ? `&account=${encodeURIComponent(account)}` : "";
  const res = await fetch(`/api/account-memory?campaign=${encodeURIComponent(campaign)}${query}`);
  const data = await res.json();
  if (!res.ok) {
    $("accountMemory").innerHTML = `<p class="bad">${h(data.detail || "Account memory unavailable.")}</p>`;
    return;
  }
  const accounts = data.accounts || [];
  $("accountMemory").innerHTML = `
    <div class="trust-title">Account Memory</div>
    ${accounts.length ? accounts.slice(0, 4).map((memory) => `
      <div class="trust-row">
        <b>${h(memory.accountId)}</b>
        <span>${h(accountMemoryLine(memory))}</span>
      </div>
    `).join("") : `<p class="muted">${h((data.warnings || ["No account memory yet."]).join(" · "))}</p>`}
  `;
}

async function rebuildAccountMemory() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    log({ error: "Enter a campaign before rebuilding account memory." });
    return;
  }
  await post("/api/account-memory/rebuild", { campaign });
}

function accuracyPercent(value) {
  return value === null || value === undefined ? "n/a" : `${Math.round(Number(value) * 100)}%`;
}

async function loadRecommendationProof() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    $("recommendationProof").innerHTML = `<p class="muted">Select a campaign to see recommendation proof.</p>`;
    return;
  }
  const account = $("accounts").value.split(",").map((s) => s.trim()).filter(Boolean)[0];
  const query = account ? `&account=${encodeURIComponent(account)}` : "";
  const res = await fetch(`/api/recommendations/accuracy?campaign=${encodeURIComponent(campaign)}${query}&windowDays=30`);
  const data = await res.json();
  if (!res.ok) {
    $("recommendationProof").innerHTML = `<p class="bad">${h(data.detail || "Recommendation proof unavailable.")}</p>`;
    return;
  }
  const overall = data.overall || {};
  const calibration = data.calibration || [];
  const audio = ((data.segments || {}).audioMatchStatus || []).slice(0, 3);
  $("recommendationProof").innerHTML = `
    <div class="trust-title">Recommendation Proof</div>
    <div class="trust-row"><b>Trust score</b><span>${h(data.recommendationTrustScore)} · ${h(data.trustConfidence)}</span></div>
    <div class="trust-row"><b>Measured</b><span>${h(overall.measuredCount || 0)} · ${h(overall.provedCount || 0)} proved · ${h(overall.disprovedCount || 0)} disproved · ${h(overall.inconclusiveCount || 0)} inconclusive</span></div>
    <div class="trust-row"><b>Accuracy</b><span>${h(accuracyPercent(overall.accuracyRate))}${overall.averageLift !== null && overall.averageLift !== undefined ? ` · lift ${h(overall.averageLift)}` : ""}</span></div>
    <div class="trust-row"><b>Calibration</b><span>${calibration.length ? calibration.map((item) => `${item.key}: ${accuracyPercent(item.accuracyRate)}`).join(" · ") : "n/a"}</span></div>
    <div class="trust-row"><b>Audio proof</b><span>${audio.length ? audio.map((item) => `${item.key}: ${accuracyPercent(item.accuracyRate)}`).join(" · ") : "n/a"}</span></div>
    ${(data.drift || []).length ? `<p class="warn">Drift: ${h(data.drift.slice(0, 2).map((item) => `${item.dimension} ${item.key} -${Math.round(item.drop * 100)}pt`).join(" · "))}</p>` : ""}
  `;
}

async function loadAudioTrust() {
  const account = $("accounts").value.split(",").map((s) => s.trim()).filter(Boolean)[0];
  const query = account ? `&account=${encodeURIComponent(account)}` : "";
  const res = await fetch(`/api/audio-memory?limit=6${query}`);
  const data = await res.json();
  if (!res.ok) {
    $("audioTrust").innerHTML = `<p class="bad">${h(data.detail || "Audio trust unavailable.")}</p>`;
    return;
  }
  const trust = data.audioTrust || {};
  const items = data.items || [];
  $("audioTrust").innerHTML = `
    <div class="trust-title">Audio Memory V2</div>
    <div class="trust-row"><b>Average score</b><span>${h(trust.averageScore ?? "n/a")} · ${h(trust.strong || 0)} strong · ${h(trust.usable || 0)} usable</span></div>
    ${items.slice(0, 4).map((item) => `
      <div class="trust-row">
        <b>${h(item.title)}</b>
        <span>${h(item.platform)} · ${h(Math.round(item.audioMemoryScore || 0))} · ${h(item.recommendationConfidence || "weak")} · fatigue ${h(item.fatigue?.level || "n/a")}</span>
      </div>
    `).join("") || `<p class="muted">Import IG/TikTok audio memory to see ranked tracks.</p>`}
  `;
}

async function loadExceptions() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    $("exceptions").innerHTML = `<p class="muted">Select a campaign to see exceptions.</p>`;
    return;
  }
  const res = await fetch(`/api/exceptions?campaign=${encodeURIComponent(campaign)}&status=open`);
  const data = await res.json();
  if (!res.ok) {
    $("exceptions").innerHTML = `<p class="bad">${h(data.detail || "Exceptions unavailable.")}</p>`;
    return;
  }
  const exceptions = data.exceptions || [];
  $("exceptions").innerHTML = `
    <div class="trust-title">Exception Queue</div>
    ${exceptions.length ? exceptions.slice(0, 6).map((exception) => `
      <div class="exception-row ${h(exception.severity)}">
        <div>
          <b>${h(exception.severity)} · ${h(exception.reasonCode)}</b>
          <span>${h(exception.accountId || exception.campaignId || "campaign")}</span>
        </div>
        <button onclick="resolveException('${h(exception.id)}')">Resolve</button>
      </div>
    `).join("") : `<p class="muted">No open exceptions.</p>`}
  `;
}

function readinessFor(asset) {
  return readinessByAsset[asset.id] || asset.export_readiness || { state: "blocked", blockingReasons: ["unknown"] };
}

function rankingFor(asset, data) {
  const row = (data.ranking || []).find((item) => item.renderedAssetId === asset.id);
  return row || null;
}

function exportMetadataPayload() {
  return {
    contentPillar: $("contentPillar").value.trim() || undefined,
    ctaType: $("ctaType").value.trim() || undefined,
    language: $("language").value.trim() || undefined,
  };
}

function findingLabels(items) {
  return (items || []).map((item) => {
    if (typeof item === "string") return item;
    const label = item.label || item.message || item.code;
    return item.operatorLabel ? `${item.operatorLabel}: ${label}` : label;
  }).filter(Boolean);
}

function auditSignalLine(audit) {
  if (!audit) return "";
  const signals = [];
  if (audit.readabilityScore != null) signals.push(`readability ${audit.readabilityScore}`);
  if (audit.safeZoneScore != null) signals.push(`safe zone ${audit.safeZoneScore}`);
  if (audit.hookVisibilityScore != null) signals.push(`hook ${audit.hookVisibilityScore}`);
  const creative = audit.creativeQuality || {};
  const creativeScore = creative.score ?? creative.overallScore;
  const hookClarityScore = creative.hookClarity?.score ?? creative.hookClarityScore;
  const visualClarityScore = creative.visualClarity?.score ?? creative.visualClarityScore;
  const openingStrengthScore = creative.openingStrength?.score ?? creative.openingStrengthScore;
  if (creativeScore != null) signals.push(`creative ${creativeScore}`);
  if (hookClarityScore != null) signals.push(`hook clarity ${hookClarityScore}`);
  if (visualClarityScore != null) signals.push(`visual clarity ${visualClarityScore}`);
  if (openingStrengthScore != null) signals.push(`opening ${openingStrengthScore}`);
  const text = (audit.ocr?.results || []).map((item) => item.ocrText).filter(Boolean).join(" · ");
  if (text) signals.push(`OCR "${text.slice(0, 80)}"`);
  const ms = audit.timings?.totalMs;
  if (ms != null) signals.push(`${ms}ms audit`);
  return signals.length ? `<div class="asset-small">Audit signals: ${h(signals.join(" · "))}</div>` : "";
}

function auditSummary(asset) {
  const audit = asset.latest_audit;
  if (!audit) return `<span class="muted">No audit yet</span>`;
  const readiness = audit.readinessSummary || {};
  const warnings = findingLabels(readiness.topWarnings).concat(readiness.warnings || audit.warnings || []).slice(0, 4);
  const failed = (readiness.blockingReasons || audit.failedChecks || []).slice(0, 4);
  const action = readiness.recommendedAction || audit.status;
  const summary = readiness.summaryText || audit.overallVerdict || audit.status;
  return `
    <button onclick="showAudit('${audit.id}')">Audit</button>
    <span class="${auditClass(audit.status)}">${h(summary)}</span>
    <span class="pill">${h(action)}</span>
    <span class="${readiness.uploadReady ? "ok" : "muted"}">${readiness.uploadReady ? "upload ready" : "readiness unknown"}</span>
    ${auditSignalLine(audit)}
    ${failed.length ? `<div class="bad">Blocked: ${h(failed.join(", "))}</div>` : ""}
    ${warnings.length ? `<div class="warn">Review: ${h(warnings.join(", "))}</div>` : ""}
  `;
}

function renderVariantPacks(data, rendered) {
  const bySource = new Map();
  for (const asset of rendered) {
    if (!bySource.has(asset.source_asset_id)) bySource.set(asset.source_asset_id, []);
    bySource.get(asset.source_asset_id).push(asset);
  }
  $("variantPacks").innerHTML = bySource.size ? `
    <div class="pack-grid">
      ${Array.from(bySource.entries()).slice(0, 12).map(([sourceId, assets]) => {
        const approved = assets.filter((asset) => asset.review_state === "approved").length;
        const bestRank = Math.max(...assets.map((asset) => rankingFor(asset, data)?.score ?? 0));
        return `
          <div class="pack-card">
            <div>
              <b>${h(sourceId)}</b>
              <p class="muted">${assets.length} variants · ${approved} approved · best rank ${h(bestRank || "-")}</p>
            </div>
            <div class="pack-strip">
              ${assets.slice(0, 6).map((asset) => `
                <figure>
                  <button class="pack-preview" type="button" title="Inspect ${h(asset.filename)}" onclick="showAssetDetail('${asset.id}')">
                    <img loading="lazy" decoding="async" alt="${h(asset.recipe || asset.filename || asset.id)}" src="/api/rendered/${encodeURIComponent(asset.id)}/poster.jpg" />
                  </button>
                  <figcaption>${h(asset.recipe || asset.filename || asset.id)}</figcaption>
                </figure>
              `).join("")}
            </div>
            <div class="asset-small">
              ${assets.slice(0, 4).map((asset) => `${h(asset.recipe || "-")} · ${h(asset.review_state)} · ${h((asset.latest_audit?.readinessSummary || {}).recommendedAction || asset.audit_status)}`).join("<br>")}
            </div>
          </div>
        `;
      }).join("")}
    </div>
    ${bySource.size > 12 ? `<p class="section-footnote">Showing 12 of ${h(bySource.size)} source packs.</p>` : ""}
  ` : "";
}

function renderedQueue(rendered, data) {
  if (!rendered.length) {
    return `<p class="muted">No rendered assets in this campaign. Enter <code>downloads_test</code> in Campaign and click Refresh.</p>`;
  }
  return `
    <div class="queue-table" role="table" aria-label="Rendered Review Queue">
      <div class="queue-head" role="row">
        <span>Asset</span>
        <span>Recipe</span>
        <span>Audit</span>
        <span>Readiness</span>
        <span>Rank / Score</span>
        <span>Actions</span>
      </div>
      ${rendered.slice(0, 40).map((asset) => {
        const readiness = readinessFor(asset);
        const ranking = rankingFor(asset, data);
        const audit = asset.latest_audit || {};
        const summary = audit.readinessSummary || {};
        return `
          <div class="queue-row" role="row">
            <div class="queue-asset">
              <video controls muted playsinline preload="none" poster="/api/rendered/${encodeURIComponent(asset.id)}/poster.jpg" src="/api/rendered/${encodeURIComponent(asset.id)}/media"></video>
              <div>
                <b>${h(asset.filename)}</b>
                <span>${h(asset.id)} · ${h((asset.content_hash || "").slice(0, 10))}${asset.content_hash ? "..." : ""}</span>
              </div>
            </div>
            <span>${h(asset.recipe || "-")}</span>
            <span class="${auditClass(asset.audit_status)}">${h(summary.summaryText || asset.audit_status || "no audit")}</span>
            <span class="${stateClass(readiness.state)}">${h(readiness.state || "blocked")}</span>
            <span>#${h(ranking?.rank ?? "-")} · ${h(ranking?.score ?? readiness.operatorScore ?? "-")}</span>
            <div class="row-actions">
              <button type="button" onclick="showAssetDetail('${asset.id}')">Details</button>
              <button type="button" onclick="assignAccount('${asset.id}')">Assign</button>
              <button type="button" ${asset.audit_status === "approved_candidate" ? "" : "disabled title=\"Run audit and fix warnings before approving\""} onclick="review('${asset.id}', 'approved')">Approve</button>
              <button type="button" onclick="review('${asset.id}', 'rejected')">Reject</button>
            </div>
          </div>
        `;
      }).join("")}
    </div>
    ${rendered.length > 40 ? `<p class="section-footnote">Showing top 40 of ${h(rendered.length)} rendered assets.</p>` : ""}
  `;
}

async function post(url, body, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 45000);
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("Request timed out. Check the local server and try again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { error: text }; }
  if (!res.ok) throw new Error(data.detail || data.error || text);
  log(data);
  await refresh();
  return data;
}

async function refresh() {
  const campaign = $("campaign").value.trim();
  const data = await fetchDashboard(campaign);
  await loadAutonomyPolicy();
  const c = data.campaign;
  if (c && !$("campaign").value.trim()) $("campaign").value = c.slug;
  if (c?.slug) window.localStorage.setItem(SELECTED_CAMPAIGN_KEY, c.slug);
  setText("railCampaign", c?.slug || "-");
  setText("lastUpdated", `Last updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`);
  const rendered = (data.rendered || []).slice().sort((a, b) => {
    const aScore = rankingFor(a, data)?.score ?? readinessFor(a).operatorScore ?? 0;
    const bScore = rankingFor(b, data)?.score ?? readinessFor(b).operatorScore ?? 0;
    return bScore - aScore;
  });
  $("summary").innerHTML = c
    ? topStatusStrip(data, rendered)
    : `<p>No campaigns yet.</p>`;
  $("creativePlanSummary").innerHTML = creativePlanMini(data.creativePlan);
  $("newBatchSummary").innerHTML = newBatchMini(rendered, data);
  $("distributionSummary").innerHTML = distributionMini(data.distribution);
  $("audioGateSummary").innerHTML = audioGateMini(data.audioWorkflow);
  $("activity").innerHTML = (data.activity || []).slice(0, 20).map(recentActivityLine).join("") || `<p class="muted">No activity yet.</p>`;
  const jobs = (data.jobs || []).slice().sort((a, b) => (a.status === "failed" ? -1 : 0) - (b.status === "failed" ? -1 : 0));
  $("jobs").innerHTML = jobs.slice(0, 20).map(recentJobLine).join("") || `<p class="muted">No jobs yet.</p>`;
  renderVariantPacks(data, rendered);
  $("rendered").innerHTML = renderedQueue(rendered, data);
  await loadAccountMemory();
  await loadRecommendationProof();
  await loadAudioTrust();
  await loadExceptions();
  await loadRecommendations();
}

async function review(id, decision) {
  const notes = prompt(`${decision} notes`, "") || undefined;
  await post("/api/review-decision", { renderedAssetId: id, decision, notes });
}

async function showAudit(id) {
  const res = await fetch(`/api/audit-report/${encodeURIComponent(id)}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "audit report failed");
  log(data);
}

async function showAssetDetail(id) {
  const res = await fetch(`/api/asset-detail/${encodeURIComponent(id)}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "asset detail failed");
  log(data);
}

async function assignAccount(id) {
  const instagramAccountId = prompt("Instagram account id", "") || undefined;
  const plannedWindowStart = prompt("Planned window start (optional ISO/local text)", "") || undefined;
  const plannedWindowEnd = prompt("Planned window end (optional ISO/local text)", "") || undefined;
  const notes = prompt("Assignment notes", "") || undefined;
  await post("/api/asset-account-assignment", {
    renderedAssetId: id,
    instagramAccountId,
    plannedWindowStart,
    plannedWindowEnd,
    notes,
  });
}

async function checkUsage() {
  const data = await post("/api/threadsdash-usage", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
  });
  usageByAsset = Object.fromEntries((data.assets || []).map((asset) => [asset.renderedAssetId, asset]));
  await refresh();
}

async function syncPerformance() {
  await post("/api/sync-performance", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
  });
}

async function supabasePreflight() {
  await post("/api/supabase-preflight", {
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
    supabaseStorageBucket: $("supabaseBucket").value.trim() || "media",
  });
}

async function safeLiveSmoke() {
  if (!confirm("This writes exactly one live Supabase draft row. Continue?")) return;
  await post("/api/safe-live-smoke", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
    supabaseStorageBucket: $("supabaseBucket").value.trim() || "media",
    allowWarnings: true,
  });
}

async function checkReadiness() {
  const data = await post("/api/export-readiness", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
    ...exportMetadataPayload(),
  });
  readinessByAsset = Object.fromEntries((data.assets || []).map((asset) => [asset.renderedAssetId, {
    state: asset.state,
    operatorScore: asset.operatorScore,
    usage: asset.usage,
    draftDestinations: asset.draftDestinations || [],
    blockingReasons: asset.blockingReasons || [],
    warnings: asset.warnings || [],
  }]));
  await refresh();
  return data;
}

async function checkCampaignReadiness() {
  await post("/api/campaign-readiness", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim() || undefined,
  });
}

async function showAccountPlan() {
  const campaign = encodeURIComponent($("campaign").value.trim());
  const userId = encodeURIComponent($("userId").value.trim());
  const res = await fetch(`/api/account-plan?campaign=${campaign}&userId=${userId}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "account plan failed");
  log(data);
}

async function showRanking() {
  const campaign = encodeURIComponent($("campaign").value.trim());
  const res = await fetch(`/api/ranking?campaign=${campaign}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "ranking failed");
  log(data);
}

async function runRecommendations() {
  const campaign = $("campaign").value.trim();
  if (!campaign) {
    $("recommendations").innerHTML = `<p class="bad">Enter a campaign before running recommendations.</p>`;
    log({ error: "Enter a campaign before running recommendations." });
    return;
  }
  $("recommendations").innerHTML = `<p class="muted">Running recommendations for ${h(campaign)}...</p>`;
  log({ status: "running_recommendations", campaign });
  try {
    await post("/api/recommendations/run", {
      campaign,
      count: 10,
      account: $("accounts").value.split(",").map((s) => s.trim()).filter(Boolean)[0] || undefined,
      persist: true,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    $("recommendations").innerHTML = `<p class="bad">${h(message || "Recommendations unavailable.")}</p>`;
    log({ error: message || "Recommendations unavailable." });
  }
}

async function acceptRecommendation(id) {
  const notes = prompt("Accept notes", "") || undefined;
  await post(`/api/recommendations/${encodeURIComponent(id)}/accept`, { notes });
}

async function rejectRecommendation(id) {
  const reason = prompt("Reject reason", "") || undefined;
  const notes = prompt("Reject notes", "") || undefined;
  await post(`/api/recommendations/${encodeURIComponent(id)}/reject`, { reason, notes });
}

async function linkRecommendation(id) {
  const renderedAssetId = prompt("Rendered asset id", "") || undefined;
  const postId = prompt("ThreadsDashboard post id", "") || undefined;
  const performanceSnapshotId = prompt("Performance snapshot id", "") || undefined;
  await post(`/api/recommendations/${encodeURIComponent(id)}/link`, {
    renderedAssetId,
    postId,
    performanceSnapshotId,
    evidence: { source: "campaign_factory_ui" },
  });
}

async function executeRecommendation(id) {
  await post(`/api/recommendations/${encodeURIComponent(id)}/execute`, {
    mode: $("autonomyLevel").value || "level_2",
    dryRunRender: false,
    runAudit: true,
    contentforgeBaseUrl: $("contentforgeUrl").value.trim() || undefined,
  }, { timeoutMs: 240000 });
}

async function measureRecommendation(id) {
  const performanceSnapshotId = prompt("Performance snapshot id (optional)", "") || undefined;
  await post(`/api/recommendations/${encodeURIComponent(id)}/measure`, { performanceSnapshotId });
}

async function resolveException(id) {
  const resolution = prompt("Resolution", "operator reviewed") || "operator reviewed";
  await post(`/api/exceptions/${encodeURIComponent(id)}/resolve`, { resolution });
}

async function planDistribution() {
  await post("/api/plan-distribution", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    mode: $("distributionMode").value,
    strategy: $("distributionStrategy").value,
    replace: true,
  });
}

async function exportPreviewSchedule() {
  log("Preview/live schedule export is temporarily disabled until native audio is selected or verified in ThreadsDashboard.");
  return;
  /*
  const scheduleMode = $("scheduleMode").value;
  if (scheduleMode === "live" && !confirm("This writes publishable scheduled rows. Continue?")) return;
  await post("/api/export-threadsdash", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    dryRun: false,
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
    supabaseStorageBucket: $("supabaseBucket").value.trim() || "media",
    allowWarnings: true,
    scheduleMode,
    ...exportMetadataPayload(),
  });
  */
}

async function promotePreviewSchedule() {
  log("Live promotion is temporarily disabled until the native audio gate is complete.");
  return;
  /*
  if (!confirm("Promote preview-only scheduled rows into publishable scheduled rows?")) return;
  await post("/api/promote-preview-schedule", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
  });
  */
}

bind("refresh", refresh);
bind("railRefresh", () => {
  $("campaign").focus();
  refresh().catch((err) => log(err.message));
});
bind("openThreadsDashboardBtn", () => {
  window.open("http://localhost:3002/", "_blank", "noopener,noreferrer");
});
bind("importBtn", () => post("/api/import-folder", {
  ...basePayload(),
  folder: $("folder").value.trim(),
  notes: $("notes").value.trim(),
  platform: "instagram",
}));
bind("prepareBtn", () => post("/api/prepare-reel", {
  campaign: $("campaign").value.trim(),
  hooks: $("hooks").value,
  recipes: $("recipes").value.split(",").map((s) => s.trim()).filter(Boolean),
  captionColor: "auto",
}));
bind("makeBatchBtn", () => post("/api/make-batch", {
  ...basePayload(),
  folder: $("folder").value.trim(),
  format: $("batchFormat").value,
  variantCount: Number($("batchVariantCount").value || 8),
  referencePattern: $("batchReferencePattern").value.trim() || "auto",
  contentforgeBaseUrl: $("contentforgeUrl").value.trim() || undefined,
  userId: $("userId").value.trim() || undefined,
  dryRunExport: true,
  workers: 3,
  recipes: $("recipes").value.split(",").map((s) => s.trim()).filter(Boolean),
  autoApproveWarningOnly: $("batchAutoApprove").checked,
}));
bind("finishedVideoBtn", () => post("/api/intake-finished-video", {
  campaign: $("campaign").value.trim() || undefined,
  model: $("model").value.trim(),
  input: $("finishedVideo").value.trim(),
  platform: "instagram",
  goal: "reach",
  referencePattern: $("batchReferencePattern").value.trim() || "auto",
  contentforgeBaseUrl: $("contentforgeUrl").value.trim() || undefined,
  userId: $("userId").value.trim() || undefined,
  dryRunExport: true,
  variantCount: Number($("batchVariantCount").value || 8),
  workers: 3,
  recipes: $("recipes").value.split(",").map((s) => s.trim()).filter(Boolean),
  creativePlan: $("creativePlanName").value.trim() || undefined,
  styleLane: $("creativePlanLanes").value.split(",").map((s) => s.trim()).filter(Boolean)[0] || undefined,
}));
bind("createCreativePlanBtn", () => post("/api/create-creative-plan", {
  name: $("creativePlanName").value.trim(),
  targetAccount: $("creativePlanAccount").value.trim(),
  dailyBaseVideoTarget: Number($("creativePlanTarget").value || 10),
  styleLanes: $("creativePlanLanes").value.split(",").map((s) => s.trim()).filter(Boolean),
  modelProfile: $("creativePlanModel").value.trim() || $("model").value.trim(),
  sourceAccounts: $("creativePlanSources").value.split(",").map((s) => s.trim()).filter(Boolean),
  platform: "instagram",
  goal: "views_reach",
  linkedCampaign: $("campaign").value.trim() || undefined,
}));
bind("syncCreativePlanBtn", () => post("/api/sync-creative-plan-progress", {
  name: $("creativePlanName").value.trim(),
  promptExport: $("creativePlanPromptExport").value.trim(),
}));
bind("runBtn", () => post("/api/run-reel", {
  campaign: $("campaign").value.trim(),
  workers: 3,
  captionBand: "center",
  captionColor: "light",
  captionStyle: "ig",
  captionFont: "Instagram Sans Condensed",
}));
bind("syncBtn", () => post("/api/sync-reel", { campaign: $("campaign").value.trim() }));
bind("auditBtn", () => post("/api/audit", {
  campaign: $("campaign").value.trim(),
  minScore: 85,
  contentforgeBaseUrl: $("contentforgeUrl").value.trim() || undefined,
}));
bind("usageBtn", checkUsage);
bind("preflightBtn", supabasePreflight);
bind("performanceBtn", syncPerformance);
bind("readinessBtn", checkReadiness);
bind("campaignReadinessBtn", checkCampaignReadiness);
bind("accountPlanBtn", showAccountPlan);
bind("rankingBtn", showRanking);
bind("runRecommendationsBtn", runRecommendations);
bind("saveAutonomyBtn", saveAutonomyPolicy);
bind("rebuildAccountMemoryBtn", rebuildAccountMemory);
bind("loadExceptionsBtn", loadExceptions);
bind("safeSmokeBtn", safeLiveSmoke);
bind("planDistributionBtn", planDistribution);
bind("exportPreviewScheduleBtn", exportPreviewSchedule);
bind("promotePreviewBtn", promotePreviewSchedule);
bind("exportBtn", async () => {
  const realExport = $("realExport").checked;
  if (realExport) {
    const readiness = await checkReadiness();
    if (!readiness.liveExportAllowed) {
      log(readiness);
      return;
    }
    if ((readiness.warnings || []).length && !confirm(`Proceed with ${readiness.warnings.length} export warnings?`)) {
      log("Live export cancelled.");
      return;
    }
  }
  await post("/api/export-threadsdash", {
    campaign: $("campaign").value.trim(),
    userId: $("userId").value.trim(),
    dryRun: !realExport,
    supabaseUrl: $("supabaseUrl").value.trim() || undefined,
    supabaseServiceRoleKey: $("supabaseKey").value.trim() || undefined,
    supabaseStorageBucket: $("supabaseBucket").value.trim() || "media",
    allowWarnings: realExport,
    scheduleMode: "draft",
    ...exportMetadataPayload(),
  });
});

configureCreatorTabs("campaign");
seedInitialCampaign();
refresh().catch((err) => log(err.message));
