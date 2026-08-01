import { readFileSync, readdirSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  resolve,
  join,
  extname,
  relative,
  isAbsolute,
  sep,
} from "node:path";

const root = resolve(import.meta.dirname, "..");
const registryArg = process.argv.find((value) => value.startsWith("--registry="));
const registryPath = registryArg
  ? resolve(registryArg.split("=", 2)[1])
  : join(
      root,
      "packages/pipeline_contracts/pipeline_contracts/ownership_registry.v1.json",
    );
const registry = JSON.parse(readFileSync(registryPath, "utf8"));
const contractPackage = JSON.parse(
  readFileSync(join(root, "packages/pipeline_contracts/package.json"), "utf8"),
);
const errors = [];

function isInsideRoot(path) {
  const relativePath = relative(root, path);
  return (
    relativePath !== ".." &&
    !relativePath.startsWith(`..${sep}`) &&
    !isAbsolute(relativePath)
  );
}

if (registry.schema !== "creator_os.state_ownership_registry.v1") {
  errors.push("ownership registry schema must be creator_os.state_ownership_registry.v1");
}
if (!Number.isInteger(registry.version) || registry.version < 1) {
  errors.push("ownership registry version must be a positive integer");
}
if (registry.contractPackage?.version !== contractPackage.version) {
  errors.push("ownership registry contract package version does not match package.json");
}

const requiredDomainFields = [
  "domain",
  "repository",
  "canonicalStore",
  "canonicalTables",
  "allowedWriters",
  "allowedReaders",
  "importDirection",
  "exportDirection",
  "externalSourceOfTruth",
];
const tableOwners = new Map();
for (const [index, domain] of (registry.domains || []).entries()) {
  for (const field of requiredDomainFields) {
    if (!(field in domain)) errors.push(`domains[${index}] is missing ${field}`);
  }
  for (const table of domain.canonicalTables || []) {
    const prior = tableOwners.get(table);
    if (prior && prior.repository !== domain.repository) {
      errors.push(
        `${table} has competing owners: ${prior.repository} and ${domain.repository}`,
      );
    } else {
      tableOwners.set(table, {
        repository: domain.repository,
        domain: domain.domain,
      });
    }
  }
}

const persistence = registry.persistenceOwnership;
const requiredPersistencePolicy = [
  "ownerDomain",
  "legalWriterRoots",
  "legalReaders",
  "mutability",
  "allowedValues",
  "stateTransitionOwner",
  "retention",
  "deletionBehavior",
  "receiptBinding",
  "repairPath",
];
const persistenceStores = new Map();
if (persistence?.schema !== "creator_os.persistence_ownership_registry.v1") {
  errors.push(
    "persistenceOwnership.schema must be creator_os.persistence_ownership_registry.v1",
  );
}
if (
  persistence?.inventoryCommand !==
  "uv run python scripts/inventory-persistence.py"
) {
  errors.push("persistenceOwnership.inventoryCommand is not the reviewed command");
}
for (const [index, store] of (persistence?.sqliteStores || []).entries()) {
  if (!store.store || persistenceStores.has(store.store)) {
    errors.push(
      `persistenceOwnership.sqliteStores[${index}] must have a unique store`,
    );
    continue;
  }
  persistenceStores.set(store.store, store);
  for (const field of requiredPersistencePolicy) {
    if (
      !(field in store) ||
      store[field] === null ||
      store[field] === "" ||
      (Array.isArray(store[field]) && !store[field].length)
    ) {
      errors.push(
        `persistenceOwnership.sqliteStores[${index}] is missing ${field}`,
      );
    }
  }
  for (const writer of store.legalWriterRoots || []) {
    const writerPath = resolve(root, writer);
    if (!isInsideRoot(writerPath) || !statSafe(writerPath)) {
      errors.push(
        `persistence store ${store.store} has nonexistent legal writer ${writer}`,
      );
    }
  }
}

const inventoryScript = join(root, "scripts/inventory-persistence.py");
let fieldInventory = null;
if (!statSafe(inventoryScript)?.isFile()) {
  errors.push("persistence inventory script is missing");
} else {
  const result = spawnSync("uv", ["run", "python", inventoryScript], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.status !== 0) {
    errors.push(
      `persistence inventory failed: ${(result.stderr || result.stdout || "unknown error").trim()}`,
    );
  } else {
    try {
      fieldInventory = JSON.parse(result.stdout);
    } catch {
      errors.push("persistence inventory did not emit valid JSON");
    }
  }
}

const inventoryRecordsByStore = new Map();
let persistentRecordCount = 0;
let persistentFieldCount = 0;
if (
  fieldInventory &&
  fieldInventory.schema !== "creator_os.persistence_field_inventory.v1"
) {
  errors.push(
    "persistence field inventory schema must be creator_os.persistence_field_inventory.v1",
  );
}
for (const [storeName, records] of Object.entries(
  fieldInventory?.stores || {},
)) {
  const store = persistenceStores.get(storeName);
  if (!store) {
    errors.push(`unregistered persistent SQLite store: ${storeName}`);
    continue;
  }
  inventoryRecordsByStore.set(storeName, records);
  for (const [recordName, record] of Object.entries(records || {})) {
    persistentRecordCount += 1;
    if (
      !Array.isArray(record.checks) ||
      !Array.isArray(record.triggers) ||
      !Array.isArray(record.uniqueConstraints)
    ) {
      errors.push(
        `${storeName}.${recordName} is missing CHECK, trigger, or uniqueness inventory`,
      );
    }
    const fields = Object.entries(record.fields || {});
    if (!fields.length) {
      errors.push(`${storeName}.${recordName} has no registered fields`);
    }
    for (const [fieldName, field] of fields) {
      persistentFieldCount += 1;
      for (const required of [
        "type",
        "required",
        "default",
        "primaryKey",
        "unique",
        "foreignKeys",
      ]) {
        if (!(required in field)) {
          errors.push(
            `${storeName}.${recordName}.${fieldName} is missing ${required}`,
          );
        }
      }
    }
  }
}
for (const storeName of persistenceStores.keys()) {
  if (!inventoryRecordsByStore.has(storeName)) {
    errors.push(`persistence field inventory is missing store ${storeName}`);
  }
  if (!(registry.domains || []).some((domain) => domain.canonicalStore === storeName)) {
    errors.push(`persistent SQLite store has no owning domain: ${storeName}`);
  }
}
function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalJson(value[key])]),
    );
  }
  return value;
}
const observedWriterFingerprint = createHash("sha256")
  .update(JSON.stringify(canonicalJson(fieldInventory?.directSqlWriters || {})))
  .digest("hex");
if (
  !/^[a-f0-9]{64}$/.test(
    String(persistence?.directSqlWriterInventorySha256 || ""),
  ) ||
  observedWriterFingerprint !== persistence.directSqlWriterInventorySha256
) {
  errors.push(
    `direct SQL writer inventory drift: observed ${observedWriterFingerprint}; review the exact record/table writer set before updating the registry`,
  );
}
const observedJsonWriterFingerprint = createHash("sha256")
  .update(
    JSON.stringify(canonicalJson(fieldInventory?.persistentJsonWriters || {})),
  )
  .digest("hex");
if (
  !/^[a-f0-9]{64}$/.test(
    String(persistence?.persistentJsonWriterInventorySha256 || ""),
  ) ||
  observedJsonWriterFingerprint !==
    persistence.persistentJsonWriterInventorySha256
) {
  errors.push(
    `persistent JSON writer inventory drift: observed ${observedJsonWriterFingerprint}; register the new sidecar/artifact family before updating the registry`,
  );
}

const registeredRecordNames = new Set(
  [...inventoryRecordsByStore.values()].flatMap((records) =>
    Object.keys(records || {}),
  ),
);
const compatibilityKeys = new Set();
for (const [index, store] of (
  persistence?.retainedCompatibilityStores || []
).entries()) {
  for (const field of [
    "store",
    "records",
    "classification",
    "legalReaders",
    "legalWriters",
    "retention",
    "deletionBehavior",
    "repairPath",
  ]) {
    if (
      !(field in store) ||
      store[field] === null ||
      store[field] === "" ||
      (Array.isArray(store[field]) && field !== "legalWriters" && !store[field].length)
    ) {
      errors.push(
        `persistenceOwnership.retainedCompatibilityStores[${index}] is missing ${field}`,
      );
    }
  }
  if (!inventoryRecordsByStore.has(store.store)) {
    errors.push(
      `retained compatibility store is unknown: ${store.store}`,
    );
  }
  for (const record of store.records || []) {
    const key = `${store.store}:${record}`;
    if (compatibilityKeys.has(key)) {
      errors.push(`duplicate retained compatibility record: ${key}`);
    }
    compatibilityKeys.add(key);
    if (inventoryRecordsByStore.get(store.store)?.[record]) {
      errors.push(
        `retained compatibility record is part of the active schema: ${key}`,
      );
    }
  }
}
for (const [index, rule] of (persistence?.recordRules || []).entries()) {
  if (!rule.records?.length) {
    errors.push(`persistenceOwnership.recordRules[${index}] has no records`);
    continue;
  }
  for (const record of rule.records) {
    if (!registeredRecordNames.has(record)) {
      errors.push(
        `persistenceOwnership.recordRules[${index}] references unknown record ${record}`,
      );
    }
  }
  for (const field of [
    "mutability",
    "stateTransitionOwner",
    "deletionBehavior",
  ]) {
    if (!rule[field]) {
      errors.push(
        `persistenceOwnership.recordRules[${index}] is missing ${field}`,
      );
    }
  }
}

const requiredArtifactPolicy = [
  "family",
  "patterns",
  "ownerDomain",
  "legalWriters",
  "legalReaders",
  "fields",
  "mutability",
  "allowedValues",
  "stateTransitionOwner",
  "retention",
  "deletionBehavior",
  "receiptBinding",
  "repairPath",
];
const artifactFamilies = new Set();
for (const [index, family] of (persistence?.artifactFamilies || []).entries()) {
  if (!family.family || artifactFamilies.has(family.family)) {
    errors.push(
      `persistenceOwnership.artifactFamilies[${index}] must have a unique family`,
    );
  }
  artifactFamilies.add(family.family);
  for (const field of requiredArtifactPolicy) {
    if (
      !(field in family) ||
      family[field] === null ||
      family[field] === "" ||
      (Array.isArray(family[field]) && !family[field].length)
    ) {
      errors.push(
        `persistenceOwnership.artifactFamilies[${index}] is missing ${field}`,
      );
    }
  }
  for (const writer of family.legalWriters || []) {
    const writerPath = resolve(root, writer);
    if (!isInsideRoot(writerPath) || !statSafe(writerPath)) {
      errors.push(
        `persistent artifact family ${family.family} has nonexistent legal writer ${writer}`,
      );
    }
  }
}
const artifactDomain = (registry.domains || []).find(
  (domain) => domain.canonicalStore === "persistent_json_artifacts",
);
if (!artifactDomain) {
  errors.push("persistent JSON artifacts have no owning domain");
} else {
  for (const family of artifactFamilies) {
    if (!artifactDomain.canonicalTables?.includes(family)) {
      errors.push(
        `persistent artifact family is missing from its owning domain: ${family}`,
      );
    }
  }
}

const requiredReportDefaults = [
  "owner",
  "source",
  "freshness",
  "staleBehavior",
  "unknownBehavior",
  "authorityLevel",
  "evidence",
  "repairAction",
];
const discoveryFiles = registry.authoritativeReportDiscovery?.sourceFiles;
const discoverySources = new Set();
const discoveredReportSchemas = new Map();
const authoritativeReportSchemaPattern =
  /(?:_status|_report|_dashboard|_summary|_readiness)\.v\d+$/;
if (!Array.isArray(discoveryFiles) || !discoveryFiles.length) {
  errors.push(
    "authoritativeReportDiscovery.sourceFiles must be a non-empty array",
  );
} else {
  for (const [index, sourceFile] of discoveryFiles.entries()) {
    if (typeof sourceFile !== "string" || !sourceFile.trim()) {
      errors.push(
        `authoritativeReportDiscovery.sourceFiles[${index}] must be a repo-relative file`,
      );
      continue;
    }
    const normalizedSource = sourceFile.trim();
    if (discoverySources.has(normalizedSource)) {
      errors.push(
        `authoritativeReportDiscovery.sourceFiles contains duplicate ${normalizedSource}`,
      );
      continue;
    }
    discoverySources.add(normalizedSource);
    const absoluteSource = resolve(root, normalizedSource);
    if (
      !isInsideRoot(absoluteSource) ||
      !statSafe(absoluteSource)?.isFile()
    ) {
      errors.push(
        `authoritative report discovery source does not exist inside the repository: ${normalizedSource}`,
      );
      continue;
    }
    const sourceText = readFileSync(absoluteSource, "utf8");
    const schemasInSource = new Set();
    const schemaPattern =
      /["']schema["']\s*:\s*["']([A-Za-z0-9_.-]+)["']/g;
    for (const match of sourceText.matchAll(schemaPattern)) {
      if (!authoritativeReportSchemaPattern.test(match[1])) continue;
      schemasInSource.add(match[1]);
      const prior = discoveredReportSchemas.get(match[1]);
      if (prior && prior !== normalizedSource) {
        errors.push(
          `authoritative report schema ${match[1]} is emitted by both ${prior} and ${normalizedSource}`,
        );
      } else {
        discoveredReportSchemas.set(match[1], normalizedSource);
      }
    }
    if (!schemasInSource.size) {
      errors.push(
        `authoritative report discovery source emits no literal schema: ${normalizedSource}`,
      );
    }
  }
}

const reportSchemas = new Set();
for (const [index, report] of (registry.authoritativeReports || []).entries()) {
  if (!report.schema || reportSchemas.has(report.schema)) {
    errors.push(
      `authoritativeReports[${index}] must have a unique non-empty schema`,
    );
  }
  reportSchemas.add(report.schema);
  if (typeof report.emittedBy !== "string" || !report.emittedBy.trim()) {
    errors.push(`authoritativeReports[${index}] is missing emittedBy`);
  } else {
    const [emitterPath, ...symbolParts] = report.emittedBy.split("::");
    const emitterSymbol = symbolParts.join("::");
    if (!discoverySources.has(emitterPath)) {
      errors.push(
        `authoritativeReports[${index}].emittedBy must use a registered discovery source: ${emitterPath}`,
      );
    }
    const absoluteEmitter = resolve(root, emitterPath);
    const emitterStat = statSafe(absoluteEmitter);
    if (
      !isInsideRoot(absoluteEmitter) ||
      !emitterStat?.isFile()
    ) {
      errors.push(
        `authoritativeReports[${index}] emitter does not exist: ${emitterPath}`,
      );
    } else {
      const emitterText = readFileSync(absoluteEmitter, "utf8");
      if (!emitterText.includes(report.schema)) {
        errors.push(
          `authoritativeReports[${index}] emitter does not emit ${report.schema}`,
        );
      }
      if (emitterSymbol) {
        const escapedSymbol = emitterSymbol.replace(
          /[.*+?^${}()|[\]\\]/g,
          "\\$&",
        );
        const symbolPattern = new RegExp(
          `\\b(?:async\\s+def|def|class|function)\\s+${escapedSymbol}\\b`,
        );
        if (!symbolPattern.test(emitterText)) {
          errors.push(
            `authoritativeReports[${index}] emitter symbol does not exist: ${report.emittedBy}`,
          );
        }
      }
    }
  }
  for (const field of requiredReportDefaults) {
    if (!report.fieldDefaults?.[field]) {
      errors.push(
        `authoritativeReports[${index}].fieldDefaults is missing ${field}`,
      );
    }
  }
  const paths = new Set();
  for (const [fieldIndex, fieldRule] of (report.fieldRules || []).entries()) {
    if (!fieldRule.path || paths.has(fieldRule.path)) {
      errors.push(
        `authoritativeReports[${index}].fieldRules[${fieldIndex}] must have a unique path`,
      );
    }
    paths.add(fieldRule.path);
    if (
      typeof fieldRule.path === "string" &&
      (!fieldRule.path.startsWith("/") || fieldRule.path.includes("*"))
    ) {
      errors.push(
        `authoritativeReports[${index}].fieldRules[${fieldIndex}] must use an explicit JSON path without wildcards`,
      );
    }
    if (!fieldRule.calculation) {
      errors.push(
        `authoritativeReports[${index}].fieldRules[${fieldIndex}] is missing calculation`,
      );
    }
  }
  if (!paths.size) {
    errors.push(`authoritativeReports[${index}] must register report fields`);
  }
  if (!paths.has("/schema")) {
    errors.push(
      `authoritativeReports[${index}] must register its explicit /schema field`,
    );
  }
}

for (const [schema, emitter] of discoveredReportSchemas.entries()) {
  if (!reportSchemas.has(schema)) {
    errors.push(
      `authoritative report schema emitted by ${emitter} is missing from the registry: ${schema}`,
    );
  }
}

for (const owner of ["creator_os", "threadsdashboard", "meta", "bridgeIdentity"]) {
  if (!Array.isArray(registry.accountFieldOwnership?.[owner])) {
    errors.push(`accountFieldOwnership.${owner} must be an array`);
  }
}

function filesUnder(directory, extensions, ignored = new Set()) {
  const files = [];
  if (!directory || !statSafe(directory)) return files;
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (ignored.has(name)) continue;
    const stat = statSafe(path);
    if (!stat) continue;
    if (stat.isDirectory()) files.push(...filesUnder(path, extensions, ignored));
    else if (extensions.has(extname(name))) files.push(path);
  }
  return files;
}

function statSafe(path) {
  try {
    return statSync(path);
  } catch {
    return null;
  }
}

function rejectMatches(files, patterns, label) {
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const pattern of patterns) {
      if (pattern.test(text)) errors.push(`${label}: ${file} matches ${pattern}`);
    }
  }
}

const creatorFiles = filesUnder(
  join(root, "python_packages"),
  new Set([".py"]),
  new Set(["tests", "__pycache__"]),
);

const productionPython = filesUnder(
  join(root, "python_packages"),
  new Set([".py"]),
  new Set(["tests", "__pycache__"]),
);
const mutationPattern =
  /\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+["`\[]?([A-Za-z_][A-Za-z0-9_]*)/gi;
const recordStores = new Map();
for (const [storeName, records] of inventoryRecordsByStore.entries()) {
  for (const recordName of Object.keys(records || {})) {
    const stores = recordStores.get(recordName) || [];
    stores.push(storeName);
    recordStores.set(recordName, stores);
  }
}
for (const file of productionPython) {
  const source = readFileSync(file, "utf8");
  const relativeFile = relative(root, file);
  for (const match of source.matchAll(mutationPattern)) {
    const candidateStores = recordStores.get(match[1]) || [];
    if (!candidateStores.length) continue;
    const registered = candidateStores.some((storeName) =>
      (persistenceStores.get(storeName)?.legalWriterRoots || []).some(
        (writer) => {
          const writerPath = resolve(root, writer);
          const writerStat = statSafe(writerPath);
          return writerStat?.isDirectory()
            ? file.startsWith(`${writerPath}${sep}`)
            : file === writerPath;
        },
      ),
    );
    if (!registered) {
      errors.push(
        `unauthorized direct write: ${relativeFile} mutates ${match[1]} owned by ${candidateStores.join(", ")}`,
      );
    }
  }
}

rejectMatches(
  creatorFiles,
  [
    /\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:posts|publish_attempts|post_metric_history|campaign_schedule_batches|campaign_schedule_batch_items|account_schedule|autoposter_[a-z_]+)/i,
  ],
  "Creator OS must mutate ThreadsDashboard state through its API",
);

const draftDelivery = readFileSync(
  join(
    root,
    "python_packages/campaign_factory/campaign_factory/adapters/threadsdash_draft_delivery.py",
  ),
  "utf8",
);
if (/supabase_service_role_key|SUPABASE_SERVICE_ROLE_KEY/.test(draftDelivery)) {
  errors.push(
    "Campaign Factory draft delivery must not possess a Supabase service-role credential",
  );
}
if (/\.upload_storage_object\(|\.insert_with_fallback\(|\.update\(/.test(draftDelivery)) {
  errors.push(
    "Campaign Factory draft delivery contains a direct Supabase mutation instead of the owning API",
  );
}

const dashboardArg = process.argv.find((value) =>
  value.startsWith("--threadsdashboard="),
);
if (dashboardArg) {
  const dashboardRoot = resolve(dashboardArg.split("=", 2)[1]);
  const dashboardFiles = filesUnder(
    join(dashboardRoot, "api"),
    new Set([".ts", ".tsx"]),
    new Set(["node_modules"]),
  );
  rejectMatches(
    dashboardFiles,
    [
      /\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:generation_attempts|generation_lineage_edges|approval_decisions|performance_snapshots|recommendation_items)\b/i,
    ],
    "ThreadsDashboard must not mutate Creator OS canonical state",
  );
}

if (errors.length) {
  for (const error of errors) console.error(`ownership error: ${error}`);
  process.exit(1);
}
console.log(
  `ownership registry valid: ${registry.domains.length} domains, ${persistentRecordCount} persistent records, ${persistentFieldCount} persistent fields, ${artifactFamilies.size} artifact families, ${reportSchemas.size} authoritative reports`,
);
