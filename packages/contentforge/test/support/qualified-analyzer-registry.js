import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { snapshotTrustedMediaAnalyzerRegistry } from "../../lib/analyzer-registry.js";
import { verifyAnalyzerValidationManifest } from "../../lib/analyzer-validation-manifest.js";

const TEST_MANIFEST_REF =
  "packages/contentforge/test/fixtures/analyzer-validation/unit-qualified.json";

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(function (key) {
      return `${JSON.stringify(key)}:${canonicalJson(value[key])}`;
    }).join(",")}}`;
  }
  return JSON.stringify(value);
}

function fingerprint(value) {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function reviewedMaterial(policy, registration, dataset) {
  return {
    analyzerId: registration.analyzerId,
    analyzerVersion: registration.analyzerVersion,
    evidenceKinds: registration.evidenceKinds,
    approvedImplementationFingerprint: registration.implementationFingerprint,
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
    operator: "contentforge_test_fixture",
  };
}

export async function isolatedQualifiedAnalyzerRegistry({
  producedAt,
  repositoryRoot,
}) {
  var root = path.resolve(repositoryRoot);
  var historical = await snapshotTrustedMediaAnalyzerRegistry({
    producedAt,
    repositoryRoot: root,
    authorityVersion: 1,
  });
  var authority = JSON.parse(
    await readFile(
      path.join(root, "packages/contentforge/analyzer-authority.v2.json"),
      "utf8",
    ),
  );
  var verifiedDataset = await verifyAnalyzerValidationManifest(
    root,
    TEST_MANIFEST_REF,
  );
  if (
    verifiedDataset.manifest.executableQualification.status !== "qualified"
    || verifiedDataset.manifest.datasetOwner !== "contentforge_test"
  ) {
    throw new Error("isolated analyzer test qualification is unavailable");
  }
  var policies = new Map(authority.analyzers.map(function (item) {
    return [`${item.analyzerId}@${item.analyzerVersion}`, item];
  }));
  var dataset = {
    datasetId: verifiedDataset.manifest.datasetId,
    datasetOwner: verifiedDataset.manifest.datasetOwner,
    manifestRef: TEST_MANIFEST_REF,
    manifestFingerprint: verifiedDataset.manifestFingerprint,
  };
  var analyzers = historical.analyzers.map(function (registration) {
    var key = `${registration.analyzerId}@${registration.analyzerVersion}`;
    var policy = policies.get(key);
    if (!policy) throw new Error(`isolated analyzer policy missing:${key}`);
    var material = reviewedMaterial(policy, registration, dataset);
    return {
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
      operator: material.operator,
      authorityReview: {
        reviewId: `unit_test_authority_${registration.analyzerId.replaceAll(".", "_")}`,
        decision: "approved",
        reviewedAt: policy.lastQualification,
        approvedChangeClasses: ["initial_authority"],
        reviewedMaterialFingerprint: fingerprint(material),
      },
    };
  });
  var exactFingerprint = fingerprint(analyzers);
  return {
    schema: "creator_os.analyzer_registry.v2",
    registryId: `contentforge.unit_test_authority.v2.${exactFingerprint.slice(0, 16)}`,
    authorityVersion: 2,
    analyzers,
    provenance: {
      producer: "contentforge.test.isolated_qualified_analyzer_registry",
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
