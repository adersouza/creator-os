import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const checker = join(root, "scripts/check-state-ownership.mjs");
const canonicalRegistry = JSON.parse(
  readFileSync(
    join(
      root,
      "packages/pipeline_contracts/pipeline_contracts/ownership_registry.v1.json",
    ),
    "utf8",
  ),
);

function runWithRegistry(mutate) {
  const directory = mkdtempSync(join(tmpdir(), "creator-os-ownership-"));
  const registryPath = join(directory, "ownership_registry.v1.json");
  const registry = structuredClone(canonicalRegistry);
  mutate?.(registry);
  writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`);
  try {
    return spawnSync(
      process.execPath,
      [checker, `--registry=${registryPath}`],
      {
        cwd: root,
        encoding: "utf8",
      },
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test("canonical authoritative-report registry passes", () => {
  const result = runWithRegistry();
  assert.equal(result.status, 0, result.stderr);
});

test("wildcard authoritative field rules fail closed", () => {
  const result = runWithRegistry((registry) => {
    registry.authoritativeReports[0].fieldRules[0].path = "/**";
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /explicit JSON path without wildcards/);
});

test("nonexistent authoritative emitters fail closed", () => {
  const result = runWithRegistry((registry) => {
    registry.authoritativeReports[0].emittedBy =
      "python_packages/campaign_factory/campaign_factory/missing_report.py";
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /emitter does not exist/);
});

test("known authoritative schema omissions fail closed", () => {
  const result = runWithRegistry((registry) => {
    registry.authoritativeReports = registry.authoritativeReports.filter(
      (report) =>
        report.schema !== "campaign_factory.creator_governance_status.v1",
    );
  });
  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    /missing from the registry: campaign_factory\.creator_governance_status\.v1/,
  );
});
