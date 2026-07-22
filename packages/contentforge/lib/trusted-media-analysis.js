import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const TRUSTED_ANALYZERS = Object.freeze([
  Object.freeze({
    analyzerId: "contentforge.media_integrity",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["media_integrity_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.temporal_motion",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["temporal_motion_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.audio_integrity",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["audio_integrity_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.overlay_delivery",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["overlay_delivery_observation"]),
  }),
]);

const ANALYSIS_SCHEMA = "contentforge.trusted_media_analysis.v1";
const SAMPLE_WIDTH = 90;
const SAMPLE_HEIGHT = 160;
const FRAME_BYTES = SAMPLE_WIDTH * SAMPLE_HEIGHT;
const FROZEN_DELTA_THRESHOLD = 0.002;
const DISCONTINUITY_ABSOLUTE_THRESHOLD = 0.18;

function fingerprint(value) {
  return createHash("sha256").update(canonicalJsonDeep(value)).digest("hex");
}

function canonicalJsonDeep(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJsonDeep).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(function (key) {
      return JSON.stringify(key) + ":" + canonicalJsonDeep(value[key]);
    }).join(",") + "}";
  }
  return JSON.stringify(value);
}

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 30000,
      maxBuffer: options.maxBuffer || 8 * 1024 * 1024,
      encoding: options.encoding || "utf8",
    }, function (error, stdout, stderr) {
      resolve({
        ok: !error,
        error: error ? String(error.message || error) : null,
        stdout: stdout || (options.encoding === "buffer" ? Buffer.alloc(0) : ""),
        stderr: stderr || "",
      });
    });
  });
}

async function sha256File(filePath) {
  var digest = createHash("sha256");
  for await (var chunk of createReadStream(filePath)) digest.update(chunk);
  return digest.digest("hex");
}

function parseRate(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  var parts = value.split("/");
  var numerator = Number(parts[0]);
  var denominator = parts.length === 2 ? Number(parts[1]) : 1;
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator === 0) return null;
  return numerator / denominator;
}

function finiteOrUnavailable(value, reason) {
  return Number.isFinite(value) ? value : { available: false, reason };
}

function percentile(values, fraction) {
  if (!values.length) return null;
  var sorted = [...values].sort(function (a, b) { return a - b; });
  var index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * fraction) - 1));
  return sorted[index];
}

function mean(values) {
  return values.length ? values.reduce(function (sum, value) { return sum + value; }, 0) / values.length : null;
}

function longestRun(values, predicate) {
  var longest = 0;
  var current = 0;
  for (var value of values) {
    current = predicate(value) ? current + 1 : 0;
    longest = Math.max(longest, current);
  }
  return longest;
}

function frameDelta(first, second) {
  var total = 0;
  for (var index = 0; index < FRAME_BYTES; index += 1) {
    total += Math.abs(first[index] - second[index]);
  }
  return total / (FRAME_BYTES * 255);
}

function splitFrames(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length < FRAME_BYTES) return [];
  var complete = Math.floor(buffer.length / FRAME_BYTES);
  var frames = [];
  for (var index = 0; index < complete; index += 1) {
    frames.push(buffer.subarray(index * FRAME_BYTES, (index + 1) * FRAME_BYTES));
  }
  return frames;
}

async function toolRevision(tool, runner) {
  var result = await runner(tool, ["-version"], { timeout: 5000, maxBuffer: 256 * 1024 });
  if (!result.ok) return { available: false, reason: `${tool}_unavailable` };
  var line = String(result.stdout || result.stderr || "").split(/\r?\n/, 1)[0].trim();
  return line ? { available: true, version: line } : { available: false, reason: `${tool}_version_unavailable` };
}

async function probeMedia(mediaPath, runner) {
  var result = await runner("ffprobe", [
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    mediaPath,
  ], { timeout: 15000, maxBuffer: 3 * 1024 * 1024 });
  if (!result.ok) throw new Error(`trusted_media_ffprobe_failed:${result.error || "unknown"}`);
  var payload;
  try {
    payload = JSON.parse(String(result.stdout || "{}"));
  } catch (error) {
    throw new Error("trusted_media_ffprobe_invalid_json", { cause: error });
  }
  var streams = Array.isArray(payload.streams) ? payload.streams : [];
  var video = streams.find(function (stream) { return stream.codec_type === "video"; });
  if (!video) throw new Error("trusted_media_video_stream_missing");
  var audio = streams.find(function (stream) { return stream.codec_type === "audio"; }) || null;
  var format = payload.format && typeof payload.format === "object" ? payload.format : {};
  var duration = Number(format.duration ?? video.duration);
  if (!Number.isFinite(duration) || duration <= 0) throw new Error("trusted_media_duration_invalid");
  return {
    raw: payload,
    video,
    audio,
    format,
    duration,
  };
}

async function temporalObservations(mediaPath, runner) {
  var result = await runner("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-i", mediaPath,
    "-vf", `fps=2,scale=${SAMPLE_WIDTH}:${SAMPLE_HEIGHT}:force_original_aspect_ratio=decrease,pad=${SAMPLE_WIDTH}:${SAMPLE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=gray`,
    "-an", "-f", "rawvideo", "pipe:1",
  ], { timeout: 45000, maxBuffer: 64 * 1024 * 1024, encoding: "buffer" });
  if (!result.ok) {
    return { available: false, reason: "frame_sampling_failed", error: result.error };
  }
  var frames = splitFrames(result.stdout);
  if (frames.length < 2) return { available: false, reason: "insufficient_sampled_frames", sampledFrames: frames.length };
  var deltas = [];
  for (var index = 1; index < frames.length; index += 1) deltas.push(frameDelta(frames[index - 1], frames[index]));
  var average = mean(deltas);
  var frozen = deltas.filter(function (value) { return value <= FROZEN_DELTA_THRESHOLD; }).length / deltas.length;
  var active = deltas.filter(function (value) { return value > FROZEN_DELTA_THRESHOLD; }).length / deltas.length;
  var discontinuities = deltas.map(function (value, index) {
    return { comparisonIndex: index, normalizedFrameDelta: value };
  }).filter(function (item) {
    return item.normalizedFrameDelta >= DISCONTINUITY_ABSOLUTE_THRESHOLD;
  });
  return {
    available: true,
    sampling: {
      framesPerSecond: 2,
      width: SAMPLE_WIDTH,
      height: SAMPLE_HEIGHT,
      pixelFormat: "gray8",
      sampledFrames: frames.length,
      comparisons: deltas.length,
    },
    adjacentNormalizedMeanAbsoluteDeltas: deltas,
    meanNormalizedFrameDelta: average,
    p95NormalizedFrameDelta: percentile(deltas, 0.95),
    maxNormalizedFrameDelta: Math.max(...deltas),
    frozenFrameRatio: frozen,
    activeFrameRatio: active,
    longestFrozenRunComparisons: longestRun(deltas, function (value) {
      return value <= FROZEN_DELTA_THRESHOLD;
    }),
    frozenDeltaThreshold: FROZEN_DELTA_THRESHOLD,
    discontinuityThreshold: DISCONTINUITY_ABSOLUTE_THRESHOLD,
    discontinuityCandidates: discontinuities,
    loopSeamScore: frameDelta(frames[0], frames[frames.length - 1]),
  };
}

function parseSilence(stderr, duration) {
  var starts = [...String(stderr || "").matchAll(/silence_start:\s*([\d.]+)/g)].map(function (match) { return Number(match[1]); });
  var ends = [...String(stderr || "").matchAll(/silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)/g)];
  var intervals = ends.map(function (match, index) {
    return { startSeconds: starts[index] ?? null, endSeconds: Number(match[1]), durationSeconds: Number(match[2]) };
  });
  var total = intervals.reduce(function (sum, interval) { return sum + (Number.isFinite(interval.durationSeconds) ? interval.durationSeconds : 0); }, 0);
  return { intervals, totalSilenceSeconds: total, silenceRatio: duration > 0 ? Math.min(1, total / duration) : null };
}

async function audioObservations(mediaPath, probe, runner) {
  if (!probe.audio) return { available: false, reason: "audio_stream_missing" };
  var [silenceResult, volumeResult, truePeakResult] = await Promise.all([
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "silencedetect=noise=-35dB:d=0.25",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "volumedetect",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "ebur128=peak=true",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
  ]);
  var silence = silenceResult.ok
    ? parseSilence(silenceResult.stderr, probe.duration)
    : { available: false, reason: "silence_analysis_failed" };
  var maxVolumeMatch = String(volumeResult.stderr || "").match(/max_volume:\s*(-?[\d.]+)\s*dB/i);
  var maxVolumeDb = maxVolumeMatch ? Number(maxVolumeMatch[1]) : null;
  var truePeakMatches = [...String(truePeakResult.stderr || "").matchAll(/Peak:\s*(-?[\d.]+)\s*dBFS/gi)];
  var truePeakDbfs = truePeakMatches.length
    ? Number(truePeakMatches[truePeakMatches.length - 1][1])
    : null;
  var videoStart = Number(probe.video.start_time ?? 0);
  var audioStart = Number(probe.audio.start_time ?? 0);
  var audioDuration = Number(probe.audio.duration ?? probe.format.duration);
  var startOffsetMs = Number.isFinite(videoStart) && Number.isFinite(audioStart)
    ? Math.round((audioStart - videoStart) * 1000)
    : null;
  var durationDeltaMs = Number.isFinite(audioDuration)
    ? Math.round((audioDuration - probe.duration) * 1000)
    : null;
  return {
    available: true,
    codec: probe.audio.codec_name || null,
    sampleRate: Number(probe.audio.sample_rate) || null,
    channels: Number(probe.audio.channels) || null,
    durationSeconds: Number.isFinite(audioDuration) ? audioDuration : null,
    silence,
    maxVolumeDb: finiteOrUnavailable(maxVolumeDb, "max_volume_unavailable"),
    truePeakDbfs: finiteOrUnavailable(truePeakDbfs, "true_peak_unavailable"),
    clippingObserved: Number.isFinite(truePeakDbfs)
      ? truePeakDbfs >= -0.1
      : { available: false, reason: "true_peak_unavailable" },
    avStreamStartOffsetMs: finiteOrUnavailable(startOffsetMs, "stream_start_offset_unavailable"),
    avDurationDeltaMs: finiteOrUnavailable(durationDeltaMs, "stream_duration_delta_unavailable"),
    alignmentScope: "container_stream_timing_only_not_lip_sync",
  };
}

function overlayObservations(overlayEvidence, mediaSha256, overlaysExist) {
  if (!overlaysExist) return { available: false, reason: "overlay_not_present", applicable: false };
  if (!overlayEvidence || typeof overlayEvidence !== "object" || Array.isArray(overlayEvidence)) {
    return { available: false, reason: "overlay_evidence_missing", applicable: true };
  }
  var subject = overlayEvidence.subjectSha256 || overlayEvidence.mediaSha256 || null;
  if (subject !== mediaSha256) return { available: false, reason: "overlay_subject_mismatch", applicable: true };
  return {
    available: true,
    applicable: true,
    subjectSha256: subject,
    evidenceFingerprint: fingerprint(overlayEvidence),
    evidence: overlayEvidence,
  };
}

function analyzerResult(definition, registration, registry, observations, toolRevisions) {
  var requiredTools = definition.analyzerId.endsWith("media_integrity")
    ? ["ffprobe"]
    : definition.analyzerId.endsWith("overlay_delivery")
      ? []
      : ["ffmpeg", "ffprobe"];
  var unavailableTool = requiredTools.find(function (tool) {
    return toolRevisions[tool]?.available !== true;
  });
  var effectiveObservations = unavailableTool
    ? { available: false, reason: `${unavailableTool}_revision_unavailable` }
    : observations;
  return {
    analyzerId: definition.analyzerId,
    analyzerVersion: definition.analyzerVersion,
    evidenceKinds: [...definition.evidenceKinds],
    analyzerRegistryId: registry.registryId,
    analyzerRegistryFingerprint: registry.registryFingerprint,
    implementationRef: registration.implementationRef,
    implementationFingerprint: registration.implementationFingerprint,
    toolRevisions,
    status: effectiveObservations.applicable === false
      ? "not_applicable"
      : effectiveObservations.available === false
        ? "unavailable"
        : "measured",
    observations: effectiveObservations,
  };
}

function analyzerVerdict(record, subjectSha256, analysisId) {
  var passed = record.status === "measured" || record.status === "not_applicable";
  return {
    schema: "contentforge.trusted_analyzer_receipt.v1",
    policy: { id: record.analyzerId, version: record.analyzerVersion },
    subjectSha256,
    analysisId,
    observationFingerprint: fingerprint(record),
    analyzerRegistryId: record.analyzerRegistryId,
    analyzerRegistryFingerprint: record.analyzerRegistryFingerprint,
    implementationRef: record.implementationRef,
    implementationFingerprint: record.implementationFingerprint,
    verdict: passed ? "pass" : "blocked",
    passed,
    evidenceOnly: true,
    providerCalls: 0,
    reasons: passed ? [] : [{
      code: record.observations.reason || "measurement_unavailable",
      severity: "block",
    }],
  };
}

async function verifiedRegistry(analyzerRegistry, repositoryRoot) {
  if (!analyzerRegistry || analyzerRegistry.schema !== "creator_os.analyzer_registry.v1") {
    throw new Error("trusted_media_analyzer_registry_invalid");
  }
  if (typeof analyzerRegistry.registryId !== "string" || !analyzerRegistry.registryId.trim()) {
    throw new Error("trusted_media_analyzer_registry_id_missing");
  }
  if (!Array.isArray(analyzerRegistry.analyzers)) {
    throw new Error("trusted_media_analyzer_registry_entries_missing");
  }
  var root = path.resolve(repositoryRoot || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.."));
  var registrations = new Map();
  for (var item of analyzerRegistry.analyzers) {
    if (!item || typeof item !== "object") throw new Error("trusted_media_analyzer_registration_invalid");
    var key = `${item.analyzerId}@${item.analyzerVersion}`;
    if (registrations.has(key)) throw new Error("trusted_media_duplicate_analyzer_registration");
    if (!/^[a-f0-9]{64}$/.test(item.implementationFingerprint || "")) {
      throw new Error(`trusted_media_analyzer_implementation_fingerprint_invalid:${key}`);
    }
    var implementationPath = path.resolve(root, String(item.implementationRef || ""));
    var relative = path.relative(root, implementationPath);
    if (!relative || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new Error(`trusted_media_analyzer_implementation_outside_root:${key}`);
    }
    var implementationStat = await stat(implementationPath);
    if (!implementationStat.isFile()) throw new Error(`trusted_media_analyzer_implementation_missing:${key}`);
    var actual = createHash("sha256").update(await readFile(implementationPath)).digest("hex");
    if (actual !== item.implementationFingerprint) {
      throw new Error(`trusted_media_analyzer_implementation_drift:${key}`);
    }
    registrations.set(key, item);
  }
  for (var definition of TRUSTED_ANALYZERS) {
    var key = `${definition.analyzerId}@${definition.analyzerVersion}`;
    var registration = registrations.get(key);
    if (!registration) throw new Error(`trusted_media_required_analyzer_missing:${key}`);
    if (canonicalJsonDeep(registration.evidenceKinds) !== canonicalJsonDeep([...definition.evidenceKinds])) {
      throw new Error(`trusted_media_analyzer_evidence_kinds_mismatch:${key}`);
    }
  }
  return {
    registryId: analyzerRegistry.registryId,
    registryFingerprint: fingerprint(analyzerRegistry),
    registrations,
  };
}

export async function analyzeTrustedMedia({
  mediaPath,
  sourcePath = null,
  expectedMediaSha256 = null,
  expectedSourceSha256 = null,
  producedAt,
  overlaysExist = false,
  overlayEvidence = null,
  analyzerRegistry,
  repositoryRoot = null,
  runner = runTool,
} = {}) {
  if (typeof producedAt !== "string" || !producedAt.trim() || Number.isNaN(Date.parse(producedAt))) {
    throw new Error("trusted media analysis requires an explicit producedAt");
  }
  var registry = await verifiedRegistry(analyzerRegistry, repositoryRoot);
  var resolvedMedia = path.resolve(String(mediaPath || ""));
  var mediaStat = await stat(resolvedMedia);
  if (!mediaStat.isFile()) throw new Error("trusted media analysis requires a regular media file");
  var mediaSha256 = await sha256File(resolvedMedia);
  if (expectedMediaSha256 && expectedMediaSha256 !== mediaSha256) throw new Error("trusted_media_output_sha256_mismatch");
  var sourceSha256 = null;
  var resolvedSource = null;
  if (sourcePath) {
    resolvedSource = path.resolve(sourcePath);
    var sourceStat = await stat(resolvedSource);
    if (!sourceStat.isFile()) throw new Error("trusted media source must be a regular file");
    sourceSha256 = await sha256File(resolvedSource);
    if (expectedSourceSha256 && expectedSourceSha256 !== sourceSha256) throw new Error("trusted_media_source_sha256_mismatch");
  } else if (expectedSourceSha256) {
    throw new Error("trusted_media_expected_source_missing");
  }

  var [probe, temporal, ffmpegRevision, ffprobeRevision] = await Promise.all([
    probeMedia(resolvedMedia, runner),
    temporalObservations(resolvedMedia, runner),
    toolRevision("ffmpeg", runner),
    toolRevision("ffprobe", runner),
  ]);
  var audio = await audioObservations(resolvedMedia, probe, runner);
  var media = {
    available: true,
    bytes: mediaStat.size,
    container: probe.format.format_name || null,
    durationSeconds: probe.duration,
    video: {
      codec: probe.video.codec_name || null,
      profile: probe.video.profile || null,
      pixelFormat: probe.video.pix_fmt || null,
      width: Number(probe.video.width) || null,
      height: Number(probe.video.height) || null,
      aspectRatio: Number(probe.video.width) > 0 && Number(probe.video.height) > 0
        ? Number(probe.video.width) / Number(probe.video.height)
        : null,
      framesPerSecond: parseRate(probe.video.avg_frame_rate || probe.video.r_frame_rate),
      frameCount: Number(probe.video.nb_frames) || null,
    },
  };
  var tools = { node: process.version, platform: `${os.platform()}-${os.arch()}-${os.release()}`, ffmpeg: ffmpegRevision, ffprobe: ffprobeRevision };
  var analyzerResults = TRUSTED_ANALYZERS.map(function (definition) {
    var observations = definition.analyzerId.endsWith("media_integrity")
      ? media
      : definition.analyzerId.endsWith("temporal_motion")
        ? temporal
        : definition.analyzerId.endsWith("audio_integrity")
          ? audio
          : overlayObservations(overlayEvidence, mediaSha256, overlaysExist);
    var registration = registry.registrations.get(`${definition.analyzerId}@${definition.analyzerVersion}`);
    return analyzerResult(definition, registration, registry, observations, tools);
  });
  var analysisId = "analysis_" + fingerprint({ mediaSha256, sourceSha256, registryFingerprint: registry.registryFingerprint, analyzers: analyzerResults }).slice(0, 24);
  var payload = {
    schema: ANALYSIS_SCHEMA,
    analysisId,
    subject: {
      mediaPath: resolvedMedia,
      mediaSha256,
      sourcePath: resolvedSource,
      sourceSha256,
    },
    producedAt,
    producer: "contentforge.trusted_media_analysis",
    analyzerRegistry: {
      registryId: registry.registryId,
      registryFingerprint: registry.registryFingerprint,
    },
    rawObservations: analyzerResults,
    analyzerVerdicts: analyzerResults.map(function (record) {
      return analyzerVerdict(record, mediaSha256, analysisId);
    }),
    unavailableMeasurements: {
      creatorIdentity: "requires_identity_analyzer_or_structured_human_review",
      faceStability: "requires_face_tracking_analyzer_or_structured_human_review",
      anatomyArtifacts: "requires_anatomy_analyzer_or_structured_human_review",
      lipSync: "requires_dedicated_lip_sync_analyzer",
    },
  };
  payload.analysisFingerprint = fingerprint(payload);
  return payload;
}

export function motionEvidenceFromTrustedAnalysis(analysis, { humanReview = null } = {}) {
  if (!analysis || analysis.schema !== ANALYSIS_SCHEMA || !Array.isArray(analysis.rawObservations)) {
    throw new Error("trusted_media_analysis_invalid");
  }
  var claimedFingerprint = analysis.analysisFingerprint;
  var fingerprintPayload = { ...analysis };
  delete fingerprintPayload.analysisFingerprint;
  if (claimedFingerprint !== fingerprint(fingerprintPayload)) {
    throw new Error("trusted_media_analysis_fingerprint_mismatch");
  }
  var subjectSha256 = analysis.subject && analysis.subject.mediaSha256;
  var identities = analysis.rawObservations.map(function (record) {
    return `${record.analyzerId}@${record.analyzerVersion}`;
  });
  if (new Set(identities).size !== identities.length) throw new Error("trusted_media_analysis_duplicate_analyzer");
  var registry = analysis.analyzerRegistry;
  if (!registry || !/^[a-f0-9]{64}$/.test(registry.registryFingerprint || "")) {
    throw new Error("trusted_media_analysis_registry_missing");
  }
  if (analysis.rawObservations.some(function (record) {
    return record.analyzerRegistryId !== registry.registryId
      || record.analyzerRegistryFingerprint !== registry.registryFingerprint;
  })) throw new Error("trusted_media_analysis_registry_mismatch");
  var byId = Object.fromEntries(analysis.rawObservations.map(function (record) { return [record.analyzerId, record]; }));
  var temporal = byId["contentforge.temporal_motion"];
  var audio = byId["contentforge.audio_integrity"];
  var reviewPayload = humanReview && typeof humanReview === "object" ? { ...humanReview } : null;
  var reviewFingerprint = reviewPayload?.reviewFingerprint;
  if (reviewPayload) delete reviewPayload.reviewFingerprint;
  var reviewValid = humanReview
    && humanReview.schema === "reel_factory.human_media_review.v1"
    && humanReview.subjectSha256 === subjectSha256
    && reviewFingerprint === fingerprint(reviewPayload);
  var review = reviewValid ? humanReview : null;
  function descriptor(record, values) {
    if (!record || record.status !== "measured") return { available: false, reason: record?.observations?.reason || "measurement_unavailable", subjectSha256 };
    return {
      available: true,
      analyzer: record.analyzerId,
      analyzerVersion: record.analyzerVersion,
      evidenceId: analysis.analysisId,
      subjectSha256,
      ...values,
    };
  }
  function human(values, reason) {
    return review
      ? { available: true, analyzer: "reel_factory.structured_human_media_review", analyzerVersion: review.rubricVersion, evidenceId: review.reviewId, subjectSha256, ...values }
      : { available: false, reason, subjectSha256 };
  }
  var temporalValues = temporal?.observations || {};
  var audioValues = audio?.observations || {};
  var offset = typeof audioValues.avStreamStartOffsetMs === "number" ? audioValues.avStreamStartOffsetMs : null;
  var durationDelta = typeof audioValues.avDurationDeltaMs === "number" ? audioValues.avDurationDeltaMs : null;
  var technicalConfidence = offset === null || durationDelta === null
    ? null
    : Math.max(0, 1 - Math.min(1, Math.max(Math.abs(offset), Math.abs(durationDelta)) / 1000));
  return {
    motion: descriptor(temporal, { score: temporalValues.meanNormalizedFrameDelta }),
    temporal: descriptor(temporal, { discontinuityScore: temporalValues.p95NormalizedFrameDelta }),
    freeze: descriptor(temporal, { frozenFrameRatio: temporalValues.frozenFrameRatio }),
    loop: descriptor(temporal, { seamScore: temporalValues.loopSeamScore, loopable: review ? review.ratings.loopAcceptable : false }),
    identity: human({ similarityScore: review?.ratings?.creatorIdentitySimilarity, matched: review?.decisions?.creatorIdentityPreserved }, "identity_review_unavailable"),
    anatomy: human({
      face: { applicable: true, anomalyScore: review?.ratings?.faceArtifactScore },
      hands: review?.ratings?.handsVisible === false ? { applicable: false, reason: "hands_not_visible_in_reviewed_media" } : { applicable: true, anomalyScore: review?.ratings?.handArtifactScore },
      body: { applicable: true, anomalyScore: review?.ratings?.bodyArtifactScore },
    }, "anatomy_review_unavailable"),
    lipSync: { available: false, reason: "dedicated_lip_sync_analyzer_unavailable", subjectSha256 },
    audioAlignment: technicalConfidence === null
      ? { available: false, reason: "audio_stream_timing_unavailable", subjectSha256 }
      : descriptor(audio, { confidence: technicalConfidence, offsetMs: offset, aligned: Math.abs(offset) <= 120 }),
  };
}

export function trustedMediaAnalysisSchema() {
  return ANALYSIS_SCHEMA;
}
