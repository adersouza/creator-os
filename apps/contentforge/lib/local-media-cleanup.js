import { readdir, rm, stat } from "fs/promises";
import { existsSync } from "fs";
import path from "path";
import { OUTPUT_DIR, PROJECT_ROOT, UPLOADS_DIR } from "./paths.js";

export var LOCAL_MEDIA_TARGETS = [
  UPLOADS_DIR,
  path.join(OUTPUT_DIR, "final"),
  path.join(OUTPUT_DIR, "runs"),
  path.join(PROJECT_ROOT, "public", "thumbnails"),
];

async function walk(dir) {
  if (!existsSync(dir)) return [];
  var entries = await readdir(dir, { withFileTypes: true });
  var files = [];
  for (var entry of entries) {
    var fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
      continue;
    }
    var stats;
    try {
      stats = await stat(fullPath);
    } catch (error) {
      if (error && error.code === "ENOENT") continue;
      throw error;
    }
    files.push({
      path: fullPath,
      rel: path.relative(PROJECT_ROOT, fullPath),
      size: stats.size,
      mtimeMs: stats.mtimeMs,
    });
  }
  return files;
}

function pickCleanupCandidates(files, { olderThanDays, maxBytes }) {
  var cutoff = Date.now() - olderThanDays * 24 * 60 * 60 * 1000;
  var old = files.filter(function (file) { return file.mtimeMs < cutoff; });
  if (maxBytes <= 0) return old;
  var deleteSet = new Set(old.map(function (file) { return file.path; }));
  var remaining = files.reduce(function (sum, file) { return sum + file.size; }, 0) -
    old.reduce(function (sum, file) { return sum + file.size; }, 0);
  var oldestFirst = [...files]
    .filter(function (file) { return !deleteSet.has(file.path); })
    .sort(function (a, b) { return a.mtimeMs - b.mtimeMs; });
  for (var file of oldestFirst) {
    if (remaining <= maxBytes) break;
    deleteSet.add(file.path);
    remaining -= file.size;
  }
  return files.filter(function (file) { return deleteSet.has(file.path); });
}

async function collectLocalMediaCandidates({ olderThanDays = 14, maxBytes = 0 } = {}) {
  var normalizedDays = Math.max(1, Math.min(Number.parseFloat(olderThanDays || 14) || 14, 3650));
  var normalizedMaxBytes = Math.max(0, Number.parseInt(maxBytes || 0, 10) || 0);
  var files = [];
  for (var target of LOCAL_MEDIA_TARGETS) {
    files.push(...await walk(target));
  }
  var candidates = pickCleanupCandidates(files, {
    olderThanDays,
    maxBytes,
  });
  return { files, candidates, olderThanDays: normalizedDays, maxBytes: normalizedMaxBytes };
}

export async function inspectLocalMediaCleanup(options = {}) {
  var { files, candidates, olderThanDays, maxBytes } = await collectLocalMediaCandidates(options);
  var totalBytes = files.reduce(function (sum, file) { return sum + file.size; }, 0);
  var candidateBytes = candidates.reduce(function (sum, file) { return sum + file.size; }, 0);
  return {
    schema: "contentforge.local_media_cleanup.v1",
    mode: "dry_run",
    olderThanDays,
    maxBytes,
    scannedFiles: files.length,
    scannedBytes: totalBytes,
    candidateFiles: candidates.length,
    candidateBytes,
    targets: LOCAL_MEDIA_TARGETS.map(function (target) { return path.relative(PROJECT_ROOT, target); }),
    candidates: candidates.slice(0, 250).map(function (file) {
      return {
        file: file.rel,
        size: file.size,
        modifiedAt: new Date(file.mtimeMs).toISOString(),
      };
    }),
  };
}

export async function applyLocalMediaCleanup(options = {}) {
  var { candidates } = await collectLocalMediaCandidates(options);
  for (var candidate of candidates) {
    await rm(candidate.path, { force: true });
  }
  var report = await inspectLocalMediaCleanup(options);
  return {
    ...report,
    mode: "deleted",
    deletedFiles: candidates.length,
    deletedBytes: candidates.reduce(function (sum, file) { return sum + file.size; }, 0),
  };
}
