import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { URL, fileURLToPath } from "node:url";

import { motionSpecificQcPolicy } from "./motion-specific-qc.js";
import { TRUSTED_ANALYZERS } from "./trusted-media-analysis.js";

const IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./motion-specific-qc.js", import.meta.url),
);
const TRUSTED_MEDIA_IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./trusted-media-analysis.js", import.meta.url),
);
const DEFAULT_REPOSITORY_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);

function validProducedAt(value) {
  return typeof value === "string" && value.trim() && !Number.isNaN(Date.parse(value));
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function registryFingerprint(analyzers) {
  return createHash("sha256").update(JSON.stringify(analyzers)).digest("hex");
}

async function registration(definition, implementationPath, root) {
  var implementationRef = path.relative(root, implementationPath).split(path.sep).join("/");
  if (
    !implementationRef ||
    implementationRef === ".." ||
    implementationRef.startsWith("../") ||
    path.isAbsolute(implementationRef)
  ) {
    throw new Error("analyzer implementation is outside the repository root");
  }
  return {
    analyzerId: definition.analyzerId,
    analyzerVersion: definition.analyzerVersion,
    evidenceKinds: [...definition.evidenceKinds],
    implementationRef,
    implementationFingerprint: await sha256File(implementationPath),
  };
}

export async function snapshotTrustedMediaAnalyzerRegistry({
  producedAt,
  repositoryRoot = DEFAULT_REPOSITORY_ROOT,
} = {}) {
  if (!validProducedAt(producedAt)) {
    throw new Error("analyzer registry snapshot requires an explicit producedAt");
  }
  var root = path.resolve(repositoryRoot);
  var policy = motionSpecificQcPolicy();
  var analyzers = await Promise.all([
    ...TRUSTED_ANALYZERS.map(function (definition) {
      return registration(definition, TRUSTED_MEDIA_IMPLEMENTATION_PATH, root);
    }),
    registration({
      analyzerId: policy.id,
      analyzerVersion: policy.version,
      evidenceKinds: ["motion_specific_qc_receipt"],
    }, IMPLEMENTATION_PATH, root),
  ]);
  analyzers.sort(function (first, second) {
    return first.analyzerId.localeCompare(second.analyzerId);
  });
  var exactRegistryFingerprint = registryFingerprint(analyzers);
  return {
    schema: "creator_os.analyzer_registry.v1",
    registryId: `contentforge.trusted_media.v1.${exactRegistryFingerprint.slice(0, 16)}`,
    analyzers,
    provenance: {
      producer: "contentforge.analyzer_registry_adapter",
      producedAt,
      sourceReferences: analyzers.map(function (item) {
        return {
          recordId: `${item.analyzerId}@${item.analyzerVersion}`,
          fingerprint: item.implementationFingerprint,
        };
      }),
    },
  };
}

// Compatibility alias for callers introduced with the evidence bridge.
export const snapshotMotionSpecificQcAnalyzerRegistry = snapshotTrustedMediaAnalyzerRegistry;
