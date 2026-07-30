import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, join, extname } from "node:path";

const root = resolve(import.meta.dirname, "..");
const registryPath = join(
  root,
  "packages/pipeline_contracts/pipeline_contracts/ownership_registry.v1.json",
);
const registry = JSON.parse(readFileSync(registryPath, "utf8"));
const contractPackage = JSON.parse(
  readFileSync(join(root, "packages/pipeline_contracts/package.json"), "utf8"),
);
const errors = [];

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
  `ownership registry valid: ${registry.domains.length} domains, ${tableOwners.size} canonical records`,
);
