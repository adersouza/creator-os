#!/usr/bin/env node
// Single source of truth: packages/pipeline_contracts/schemas (+ typescript/index.ts).
// This writes every compatibility mirror from canonical so you never hand-copy.
// Workflow: edit ONLY canonical, then `pnpm sync:contracts`. CI's `pnpm check:contracts` verifies.

import {
	cpSync,
	existsSync,
	mkdirSync,
	readdirSync,
	rmSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

const repoRoot = resolve(new URL("..", import.meta.url).pathname);
const canonicalRoot = join(repoRoot, "packages", "pipeline_contracts");
const canonicalSchemas = join(canonicalRoot, "schemas");
const canonicalIndexTs = join(canonicalRoot, "typescript", "index.ts");

// Keep these in lockstep with scripts/check-pipeline-contracts-sync.mjs
const schemaMirrors = [
	join(canonicalRoot, "pipeline_contracts", "schemas"),
	join(repoRoot, "pipeline_contracts", "schemas"),
	join(repoRoot, "python_packages", "campaign_factory", "schemas"),
];
const indexTsMirrors = [join(repoRoot, "pipeline_contracts", "typescript", "index.ts")];

function syncDir(src, dest) {
	mkdirSync(dest, { recursive: true });
	const want = new Set(readdirSync(src));
	for (const name of readdirSync(dest)) {
		if (!want.has(name)) rmSync(join(dest, name), { recursive: true, force: true });
	}
	for (const name of want) {
		cpSync(join(src, name), join(dest, name));
	}
}

if (!existsSync(canonicalSchemas)) {
	console.error(`ERROR: canonical schema dir missing: ${canonicalSchemas}`);
	process.exit(1);
}

// 1. Regenerate the TypeScript schema constants into every typescript/generated-schemas.ts target.
execFileSync("node", [join(repoRoot, "scripts", "generate-pipeline-contract-schemas.mjs")], {
	stdio: "inherit",
});

// 2. Mirror schema JSON (+ examples) from canonical.
for (const dest of schemaMirrors) {
	syncDir(canonicalSchemas, dest);
	console.log(`synced schemas -> ${dest}`);
}

// 3. Mirror the hand-written TypeScript exports barrel.
for (const dest of indexTsMirrors) {
	cpSync(canonicalIndexTs, dest);
	console.log(`synced index.ts -> ${dest}`);
}

console.log("Pipeline contract mirrors synced from packages/pipeline_contracts.");
