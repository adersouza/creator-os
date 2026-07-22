import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { URL, fileURLToPath } from "node:url";

import { motionSpecificQcPolicy } from "./motion-specific-qc.js";

const IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./motion-specific-qc.js", import.meta.url),
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

export async function snapshotMotionSpecificQcAnalyzerRegistry({
  producedAt,
  repositoryRoot = DEFAULT_REPOSITORY_ROOT,
} = {}) {
  if (!validProducedAt(producedAt)) {
    throw new Error("analyzer registry snapshot requires an explicit producedAt");
  }
  var root = path.resolve(repositoryRoot);
  var implementationRef = path.relative(root, IMPLEMENTATION_PATH).split(path.sep).join("/");
  if (
    !implementationRef ||
    implementationRef === ".." ||
    implementationRef.startsWith("../") ||
    path.isAbsolute(implementationRef)
  ) {
    throw new Error("motion QC implementation is outside the repository root");
  }
  var policy = motionSpecificQcPolicy();
  var implementationFingerprint = await sha256File(IMPLEMENTATION_PATH);
  return {
    schema: "creator_os.analyzer_registry.v1",
    registryId: [
      "contentforge.motion_specific_qc",
      policy.version,
      implementationFingerprint.slice(0, 16),
    ].join("."),
    analyzers: [
      {
        analyzerId: policy.id,
        analyzerVersion: policy.version,
        evidenceKinds: ["motion_specific_qc_receipt"],
        implementationRef,
        implementationFingerprint,
      },
    ],
    provenance: {
      producer: "contentforge.analyzer_registry_adapter",
      producedAt,
      sourceReferences: [
        {
          recordId: `${policy.id}@${policy.version}`,
          fingerprint: implementationFingerprint,
        },
      ],
    },
  };
}
