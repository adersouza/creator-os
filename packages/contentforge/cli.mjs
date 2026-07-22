#!/usr/bin/env node
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { PROJECT_ROOT, resolveUploadPath } from "./lib/paths.js";

const REPOSITORY_ROOT = path.resolve(PROJECT_ROOT, "../..");

async function readPayload() {
  var raw = process.argv[3]
    ? await readFile(process.argv[3], "utf8")
    : await new Promise(function (resolve, reject) {
        var chunks = [];
        process.stdin.setEncoding("utf8");
        process.stdin.on("data", function (chunk) { chunks.push(chunk); });
        process.stdin.on("end", function () { resolve(chunks.join("")); });
        process.stdin.on("error", reject);
      });
  var value = JSON.parse(raw || "{}");
  if (!value || Array.isArray(value) || typeof value !== "object") {
    throw new Error("request must be a JSON object");
  }
  return value;
}

async function sha256File(filePath) {
  var digest = createHash("sha256");
  for await (var chunk of createReadStream(filePath)) digest.update(chunk);
  return digest.digest("hex");
}

async function main() {
  process.chdir(PROJECT_ROOT);
  var command = process.argv[2];
  var payload = await readPayload();
  var result;
  if (command === "similarity") {
    var { POST: similarityPost } = await import("./lib/similarity.js");
    var response = await similarityPost(
      new Request("http://contentforge.local/api/similarity", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );
    result = await response.json();
    if (!response.ok) throw new Error(result.error || `similarity failed (${response.status})`);
  } else if (command === "variant-pack") {
    var { runVariantPack } = await import("./lib/variant-pack.js");
    var source = payload.source || payload.inputFile;
    if (!resolveUploadPath(source)) throw new Error("invalid source upload");
    result = await runVariantPack(payload);
  } else if (command === "motion-qc") {
    var { evaluateMotionSpecificQc } = await import("./lib/motion-specific-qc.js");
    var evidence = payload.evidence;
    if (payload.analysis) {
      var { motionEvidenceFromTrustedAnalysis } = await import(
        "./lib/trusted-media-analysis.js"
      );
      evidence = motionEvidenceFromTrustedAnalysis(payload.analysis, {
        humanReview: payload.humanReview || null,
      });
    }
    if (typeof payload.mediaPath !== "string" || !payload.mediaPath.trim()) {
      throw new Error("motion-qc requires mediaPath");
    }
    var mediaPath = path.resolve(payload.mediaPath);
    var mediaStat = await stat(mediaPath);
    if (!mediaStat.isFile()) throw new Error("motion-qc mediaPath must be a file");
    var mediaSha256 = await sha256File(mediaPath);
    if (payload.mediaSha256 && payload.mediaSha256 !== mediaSha256) {
      throw new Error("motion-qc media SHA-256 mismatch");
    }
    result = evaluateMotionSpecificQc(evidence, {
      ...payload.options,
      mediaSha256,
    });
  } else if (command === "analyze-media") {
    var { snapshotTrustedMediaAnalyzerRegistry } = await import(
      "./lib/analyzer-registry.js"
    );
    var { analyzeTrustedMedia } = await import("./lib/trusted-media-analysis.js");
    var registry = payload.analyzerRegistry || await snapshotTrustedMediaAnalyzerRegistry({
      producedAt: payload.producedAt,
    });
    result = await analyzeTrustedMedia({
      mediaPath: payload.mediaPath,
      sourcePath: payload.sourcePath || null,
      expectedMediaSha256: payload.mediaSha256 || null,
      expectedSourceSha256: payload.sourceSha256 || null,
      producedAt: payload.producedAt,
      overlaysExist: payload.overlaysExist === true,
      overlayEvidence: payload.overlayEvidence || null,
      analyzerRegistry: registry,
      repositoryRoot: REPOSITORY_ROOT,
    });
  } else if (command === "analyzer-registry") {
    var { snapshotTrustedMediaAnalyzerRegistry } = await import(
      "./lib/analyzer-registry.js"
    );
    result = await snapshotTrustedMediaAnalyzerRegistry({
      producedAt: payload.producedAt,
    });
  } else {
    throw new Error(
      "usage: contentforge <similarity|variant-pack|analyze-media|motion-qc|analyzer-registry> [request.json]",
    );
  }
  process.stdout.write(JSON.stringify(result) + "\n");
}

main().catch(function (error) {
  process.stderr.write(JSON.stringify({ error: error.message }) + "\n");
  process.exitCode = 1;
});
