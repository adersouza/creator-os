import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";

function inside(root, candidate) {
  var relative = path.relative(root, candidate);
  return relative && relative !== ".."
    && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export async function verifyAnalyzerValidationManifest(root, manifestRef) {
  var resolvedRoot = path.resolve(root);
  var manifestPath = path.resolve(resolvedRoot, String(manifestRef || ""));
  if (!inside(resolvedRoot, manifestPath)) {
    throw new Error("analyzer validation dataset is outside the repository root");
  }
  var manifestStat = await lstat(manifestPath);
  if (!manifestStat.isFile() || manifestStat.isSymbolicLink()) {
    throw new Error("analyzer validation manifest is not a regular file");
  }
  var manifestBytes = await readFile(manifestPath);
  var manifest = JSON.parse(manifestBytes.toString("utf8"));
  if (
    manifest.schema !== "contentforge.analyzer_validation_manifest.v1"
    || !Array.isArray(manifest.fixtures)
    || manifest.fixtures.length === 0
    || !manifest.executableQualification
    || typeof manifest.executableQualification.command !== "string"
    || !["qualified", "blocked"].includes(
      manifest.executableQualification.status,
    )
  ) {
    throw new Error("analyzer validation manifest is invalid");
  }
  for (var fixture of manifest.fixtures) {
    if (
      !fixture
      || typeof fixture.ref !== "string"
      || !/^[a-f0-9]{64}$/.test(fixture.sha256 || "")
    ) {
      throw new Error("analyzer validation fixture identity is invalid");
    }
    var fixturePath = path.resolve(resolvedRoot, fixture.ref);
    if (!inside(resolvedRoot, fixturePath)) {
      throw new Error("analyzer validation fixture is outside the repository root");
    }
    var fixtureStat = await lstat(fixturePath);
    if (!fixtureStat.isFile() || fixtureStat.isSymbolicLink()) {
      throw new Error("analyzer validation fixture is not a regular file");
    }
    if (sha256(await readFile(fixturePath)) !== fixture.sha256) {
      throw new Error(`analyzer validation fixture drift:${fixture.ref}`);
    }
  }
  return {
    manifest,
    manifestFingerprint: sha256(manifestBytes),
  };
}
