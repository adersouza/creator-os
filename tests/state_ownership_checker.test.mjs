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
  assert.match(result.stdout, /\b\d{4} persistent fields/);
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

test("persistent stores require complete inherited field policy", () => {
  const result = runWithRegistry((registry) => {
    delete registry.persistenceOwnership.sqliteStores[0].repairPath;
  });
  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    /persistenceOwnership\.sqliteStores\[0\] is missing repairPath/,
  );
});

test("unregistered direct SQL writers fail closed", () => {
  const result = runWithRegistry((registry) => {
    registry.persistenceOwnership.sqliteStores.find(
      (store) => store.store === "campaign_factory_sqlite",
    ).legalWriterRoots = ["docs"];
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /unauthorized direct write/);
});

test("a new direct SQL writer inside the owner package fails closed", () => {
  const probe = join(
    root,
    "python_packages/campaign_factory/campaign_factory",
    `__ownership_probe_${process.pid}.py`,
  );
  writeFileSync(
    probe,
    'conn.execute("UPDATE campaigns SET name = ? WHERE id = ?", ("x", "y"))\n',
  );
  try {
    const result = runWithRegistry();
    assert.equal(result.status, 1);
    assert.match(result.stderr, /direct SQL writer inventory drift/);
  } finally {
    rmSync(probe, { force: true });
  }
});

test("a new persistent JSON family inside an owner package fails closed", () => {
  const probe = join(
    root,
    "python_packages/reel_factory/reel_factory",
    `__json_family_probe_${process.pid}.py`,
  );
  writeFileSync(
    probe,
    'from pathlib import Path\nPath("new_unregistered_family.json").write_text("{}")\n',
  );
  try {
    const result = runWithRegistry();
    assert.equal(result.status, 1);
    assert.match(result.stderr, /persistent JSON writer inventory drift/);
  } finally {
    rmSync(probe, { force: true });
  }
});

test("unknown persistence record rules fail closed", () => {
  const result = runWithRegistry((registry) => {
    registry.persistenceOwnership.recordRules[0].records.push(
      "not_a_persistent_record",
    );
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /references unknown record not_a_persistent_record/);
});

test("persistent artifact families require legal writers and repair policy", () => {
  const result = runWithRegistry((registry) => {
    delete registry.persistenceOwnership.artifactFamilies[0].receiptBinding;
  });
  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    /persistenceOwnership\.artifactFamilies\[0\] is missing receiptBinding/,
  );
});
