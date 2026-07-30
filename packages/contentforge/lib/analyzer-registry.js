import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { URL, fileURLToPath } from "node:url";

import { motionSpecificQcPolicy } from "./motion-specific-qc.js";
import { verifyAnalyzerValidationManifest } from "./analyzer-validation-manifest.js";
import { TRUSTED_ANALYZERS } from "./trusted-media-analysis.js";

const IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./motion-specific-qc.js", import.meta.url),
);
const TRUSTED_MEDIA_IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./trusted-media-analysis.js", import.meta.url),
);
const OVERLAY_IMPLEMENTATION_PATH = fileURLToPath(
  new URL("./similarity.js", import.meta.url),
);
const HUMAN_REVIEW_IMPLEMENTATION_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../python_packages/reel_factory/reel_factory/human_media_review.py",
);
const LIP_SYNC_IMPLEMENTATION_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../scripts/local-lip-sync-analyzer.py",
);
const POSE_CONTINUITY_IMPLEMENTATION_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../scripts/local-pose-continuity-analyzer.py",
);
const DEFAULT_REPOSITORY_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const AUTHORITY_POLICY_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../analyzer-authority.v2.json",
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

function canonicalJson(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(function (key) {
      return JSON.stringify(key) + ":" + canonicalJson(value[key]);
    }).join(",") + "}";
  }
  return JSON.stringify(value);
}

function fingerprint(value) {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

async function implementationRegistration(definition, implementationPath, root) {
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

function analyzerDefinitions() {
  var policy = motionSpecificQcPolicy();
  return [
    ...TRUSTED_ANALYZERS.map(function (definition) {
      return {
        definition,
        implementationPath:
          definition.analyzerId === "contentforge.overlay_delivery"
            ? OVERLAY_IMPLEMENTATION_PATH
            : definition.analyzerId === "contentforge.pose_continuity"
              ? POSE_CONTINUITY_IMPLEMENTATION_PATH
              : TRUSTED_MEDIA_IMPLEMENTATION_PATH,
      };
    }),
    {
      definition: {
        analyzerId: policy.id,
        analyzerVersion: policy.version,
        evidenceKinds: ["motion_specific_qc_receipt"],
      },
      implementationPath: IMPLEMENTATION_PATH,
    },
    {
      definition: {
        analyzerId: "reel_factory.structured_human_media_review",
        analyzerVersion: "1.0.0",
        evidenceKinds: ["human_media_review"],
      },
      implementationPath: HUMAN_REVIEW_IMPLEMENTATION_PATH,
    },
    {
      definition: {
        analyzerId: "contentforge.local_face_mouth_track",
        analyzerVersion: "1.0.0",
        evidenceKinds: ["face_mouth_track_observation"],
      },
      implementationPath: LIP_SYNC_IMPLEMENTATION_PATH,
    },
  ];
}

async function snapshotLegacyRegistry({ producedAt, root }) {
  var analyzers = await Promise.all(analyzerDefinitions().map(function (item) {
    return implementationRegistration(
      item.definition,
      item.implementationPath,
      root,
    );
  }));
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

function reviewedMaterial(policy, registration, dataset) {
  return {
    analyzerId: registration.analyzerId,
    analyzerVersion: registration.analyzerVersion,
    evidenceKinds: registration.evidenceKinds,
    approvedImplementationFingerprint: policy.approvedImplementationFingerprint,
    model: policy.model,
    validationDataset: dataset,
    thresholds: policy.thresholds,
    thresholdsFingerprint: policy.thresholdsFingerprint,
    falsePositiveBudget: policy.falsePositiveBudget,
    falseNegativeBudget: policy.falseNegativeBudget,
    lastQualification: policy.lastQualification,
    nextRenewal: policy.nextRenewal,
    approvedUseCases: policy.approvedUseCases,
    unsupportedUseCases: policy.unsupportedUseCases,
    rollbackVersion: policy.rollbackVersion,
    operator: policy.operator,
  };
}

async function snapshotProductionAuthorityRegistry({ producedAt, root }) {
  var authority = JSON.parse(await readFile(AUTHORITY_POLICY_PATH, "utf8"));
  if (
    authority.schema !== "contentforge.analyzer_authority_policy.v2"
    || authority.authorityVersion !== 2
    || !Array.isArray(authority.analyzers)
  ) {
    throw new Error("analyzer production authority policy is invalid");
  }
  var verifiedDataset = await verifyAnalyzerValidationManifest(
    root,
    authority.datasetManifestRef,
  );
  if (
    verifiedDataset.manifest.datasetId !== authority.datasetId
    || verifiedDataset.manifest.datasetOwner !== authority.datasetOwner
  ) {
    throw new Error("analyzer validation dataset identity mismatch");
  }
  if (verifiedDataset.manifest.executableQualification.status !== "qualified") {
    throw new Error(
      "analyzer executable qualification is blocked:"
      + verifiedDataset.manifest.executableQualification.blockingReasons.join(","),
    );
  }
  var datasetFingerprint = verifiedDataset.manifestFingerprint;
  var authorityById = new Map(authority.analyzers.map(function (item) {
    return [`${item.analyzerId}@${item.analyzerVersion}`, item];
  }));
  if (authorityById.size !== authority.analyzers.length) {
    throw new Error("analyzer production authority policy has duplicate analyzers");
  }
  var analyzers = [];
  for (var item of analyzerDefinitions()) {
    var registration = await implementationRegistration(
      item.definition,
      item.implementationPath,
      root,
    );
    var identity = `${registration.analyzerId}@${registration.analyzerVersion}`;
    var policy = authorityById.get(identity);
    if (!policy) {
      throw new Error(`analyzer production authority missing:${identity}`);
    }
    if (policy.approvedImplementationFingerprint !== registration.implementationFingerprint) {
      throw new Error(`analyzer implementation lacks current authority review:${identity}`);
    }
    if (fingerprint(policy.thresholds) !== policy.thresholdsFingerprint) {
      throw new Error(`analyzer threshold authority fingerprint mismatch:${identity}`);
    }
    var dataset = {
      datasetId: authority.datasetId,
      datasetOwner: authority.datasetOwner,
      manifestRef: authority.datasetManifestRef,
      manifestFingerprint: datasetFingerprint,
    };
    var material = reviewedMaterial(policy, registration, dataset);
    if (
      !policy.authorityReview
      || policy.authorityReview.decision !== "approved"
      || fingerprint(material)
        !== policy.authorityReview.reviewedMaterialFingerprint
    ) {
      throw new Error(`analyzer authority review mismatch:${identity}`);
    }
    var qualifiedAt = Date.parse(policy.lastQualification);
    var renewAt = Date.parse(policy.nextRenewal);
    var snapshotAt = Date.parse(producedAt);
    var verifiedAt = Date.now();
    if (
      !Number.isFinite(qualifiedAt)
      || !Number.isFinite(renewAt)
      || qualifiedAt > snapshotAt
      || snapshotAt > renewAt
      || verifiedAt < qualifiedAt
      || verifiedAt > renewAt
      || Date.parse(policy.authorityReview.reviewedAt) > qualifiedAt
    ) {
      throw new Error(`analyzer production authority expired or not yet valid:${identity}`);
    }
    analyzers.push({
      ...registration,
      model: policy.model,
      validationDataset: dataset,
      thresholds: policy.thresholds,
      thresholdsFingerprint: policy.thresholdsFingerprint,
      falsePositiveBudget: policy.falsePositiveBudget,
      falseNegativeBudget: policy.falseNegativeBudget,
      lastQualification: policy.lastQualification,
      nextRenewal: policy.nextRenewal,
      approvedUseCases: policy.approvedUseCases,
      unsupportedUseCases: policy.unsupportedUseCases,
      rollbackVersion: policy.rollbackVersion,
      operator: policy.operator,
      authorityReview: policy.authorityReview,
    });
    authorityById.delete(identity);
  }
  if (authorityById.size) {
    throw new Error("analyzer production authority contains removed detector");
  }
  analyzers.sort(function (first, second) {
    return first.analyzerId.localeCompare(second.analyzerId);
  });
  var exactRegistryFingerprint = fingerprint(analyzers);
  return {
    schema: "creator_os.analyzer_registry.v2",
    registryId:
      `contentforge.production_authority.v2.${exactRegistryFingerprint.slice(0, 16)}`,
    authorityVersion: 2,
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

export async function snapshotTrustedMediaAnalyzerRegistry({
  producedAt,
  repositoryRoot = DEFAULT_REPOSITORY_ROOT,
  authorityVersion = 2,
} = {}) {
  if (!validProducedAt(producedAt)) {
    throw new Error("analyzer registry snapshot requires an explicit producedAt");
  }
  var root = path.resolve(repositoryRoot);
  if (authorityVersion === 1) {
    return snapshotLegacyRegistry({ producedAt, root });
  }
  if (authorityVersion !== 2) {
    throw new Error("unsupported analyzer authority version");
  }
  return snapshotProductionAuthorityRegistry({ producedAt, root });
}
