import crypto from "crypto";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { mkdir } from "fs/promises";
import path from "path";
import { OUTPUT_DIR } from "./paths.js";
import { runVariantPack } from "./variant-pack.js";

var JOB_DIR = path.join(OUTPUT_DIR, "variant-pack-jobs");
var TERMINAL_STATUSES = new Set(["succeeded", "failed", "timed_out", "aborted", "cancelled"]);
var activeJobs = new Map();
var variantPackRunner = runVariantPack;

function nowIso() {
  return new Date().toISOString();
}

function stableStringify(value) {
  if (Array.isArray(value)) return "[" + value.map(stableStringify).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + stableStringify(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

function jobPath(runId) {
  return path.join(JOB_DIR, runId + ".json");
}

function publicJob(job) {
  var pollUrl = "/api/variant-pack/jobs/" + encodeURIComponent(job.runId);
  return {
    schema: "contentforge.variant_pack_job.v1",
    runId: job.runId,
    status: job.status,
    pollUrl,
    startedAt: job.startedAt || job.createdAt,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    terminalAt: job.terminalAt || null,
    error: job.error || null,
    report: job.report || null,
    artifacts: job.artifacts || [],
    idempotencyKey: job.idempotencyKey,
  };
}

async function ensureJobDir() {
  await mkdir(JOB_DIR, { recursive: true });
}

function readJob(runId) {
  var file = jobPath(runId);
  if (!existsSync(file)) return null;
  return JSON.parse(readFileSync(file, "utf8"));
}

function writeJob(job) {
  writeFileSync(jobPath(job.runId), JSON.stringify(job, null, 2));
  return job;
}

function terminalJob(job, status, extra = {}) {
  return writeJob({
    ...job,
    ...extra,
    status,
    updatedAt: nowIso(),
    terminalAt: nowIso(),
  });
}

function timeoutExpired(job) {
  var timeoutMs = Number(job.timeoutMs || 0);
  if (!timeoutMs || !job.startedAt) return false;
  return Date.now() - Date.parse(job.startedAt) > timeoutMs;
}

export function buildVariantPackJobId(input = {}) {
  var idempotencyKey = input.idempotencyKey || stableStringify({
    source: input.source || input.inputFile,
    variantCount: input.variantCount || input.count || 8,
    variationPreset: input.variationPreset || "balanced",
    captionMode: input.captionMode || "none",
    preserveBurnedCaptions: !!input.preserveBurnedCaptions,
  });
  return crypto.createHash("sha256").update(String(idempotencyKey)).digest("hex").slice(0, 8);
}

export async function startVariantPackJob(input = {}) {
  await ensureJobDir();
  var idempotencyKey = input.idempotencyKey || stableStringify(input);
  var runId = buildVariantPackJobId({ ...input, idempotencyKey });
  var existing = readJob(runId);
  if (existing) {
    if (!TERMINAL_STATUSES.has(existing.status) && timeoutExpired(existing)) {
      existing = terminalJob(existing, "timed_out", { error: "Variant pack job exceeded timeout" });
    }
    if (!TERMINAL_STATUSES.has(existing.status) && !activeJobs.has(runId)) {
      existing = terminalJob(existing, "aborted", { error: "Variant pack job was not active after process restart" });
    }
    return publicJob(existing);
  }

  var createdAt = nowIso();
  var job = writeJob({
    schema: "contentforge.variant_pack_job_state.v1",
    runId,
    status: "queued",
    createdAt,
    updatedAt: createdAt,
    startedAt: null,
    terminalAt: null,
    idempotencyKey,
    request: input,
    timeoutMs: Math.max(1, Number(input.jobTimeoutMs || 30 * 60 * 1000)),
    report: null,
    artifacts: [],
    error: null,
  });

  var promise = runVariantPackJob(runId);
  activeJobs.set(runId, promise);
  promise.finally(() => activeJobs.delete(runId));
  return publicJob(job);
}

export async function loadVariantPackJob(runId) {
  await ensureJobDir();
  var job = readJob(runId);
  if (!job) return null;
  if (!TERMINAL_STATUSES.has(job.status) && timeoutExpired(job)) {
    job = terminalJob(job, "timed_out", { error: "Variant pack job exceeded timeout" });
  }
  return publicJob(job);
}

export async function runVariantPackJob(runId) {
  await ensureJobDir();
  var job = readJob(runId);
  if (!job || TERMINAL_STATUSES.has(job.status)) return job;
  job = writeJob({
    ...job,
    status: "running",
    startedAt: job.startedAt || nowIso(),
    updatedAt: nowIso(),
  });
  try {
    var report = await variantPackRunner(job.request);
    var latest = readJob(runId) || job;
    if (TERMINAL_STATUSES.has(latest.status)) return latest;
    var artifacts = (report.results || [])
      .filter((item) => item && item.filePath)
      .map((item) => ({
        filename: item.filename || item.file,
        filePath: item.filePath,
        recommended: item.recommended === true,
        uploadReady: item.uploadReady === true,
      }));
    return terminalJob(latest, "succeeded", { report, artifacts, error: null });
  } catch (error) {
    var latest = readJob(runId) || job;
    if (TERMINAL_STATUSES.has(latest.status)) return latest;
    return terminalJob(latest, "failed", { error: error?.message || String(error) });
  }
}

export function __setVariantPackJobRunnerForTests(runner) {
  variantPackRunner = runner || runVariantPack;
}
