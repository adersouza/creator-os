#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const monorepoRoot = resolve(root, "..", "..");
const canonicalContractsRoot = join(monorepoRoot, "packages", "pipeline_contracts");
const vendoredRoot = join(root, "pipeline_contracts");

function listFiles(directory) {
	const files = [];
	const visit = (current, prefix = "") => {
		for (const entry of readdirSync(current).sort()) {
			const fullPath = join(current, entry);
			const relativePath = prefix ? `${prefix}/${entry}` : entry;
			if (statSync(fullPath).isDirectory()) {
				visit(fullPath, relativePath);
			} else {
				files.push(relativePath);
			}
		}
	};
	visit(directory);
	return files;
}

function read(path) {
	return readFileSync(path, "utf8");
}

const mismatches = [];
const canonicalSchemaRoot = join(canonicalContractsRoot, "schemas");
const vendoredSchemaRoot = join(vendoredRoot, "schemas");
const canonicalSchemaFiles = listFiles(canonicalSchemaRoot);
const vendoredSchemaFiles = listFiles(vendoredSchemaRoot);
const vendoredSchemaSet = new Set(vendoredSchemaFiles);
const canonicalSchemaSet = new Set(canonicalSchemaFiles);

for (const file of canonicalSchemaFiles) {
	if (!vendoredSchemaSet.has(file)) {
		mismatches.push(`schemas/${file} is missing from Dashboard snapshot`);
		continue;
	}
	if (read(join(canonicalSchemaRoot, file)) !== read(join(vendoredSchemaRoot, file))) {
		mismatches.push(`schemas/${file} differs from packages/pipeline_contracts/schemas/${file}`);
	}
}
for (const file of vendoredSchemaFiles) {
	if (!canonicalSchemaSet.has(file)) {
		mismatches.push(`schemas/${file} is not in packages/pipeline_contracts/schemas`);
	}
}

if (
	read(join(canonicalContractsRoot, "typescript", "index.ts")) !==
	read(join(vendoredRoot, "typescript.ts"))
) {
	mismatches.push("typescript.ts differs from packages/pipeline_contracts/typescript/index.ts");
}

if (mismatches.length > 0) {
	console.error("ERROR: ThreadsDashboard pipeline_contracts snapshot is stale.");
	console.error("Sync from packages/pipeline_contracts.");
	for (const mismatch of mismatches) console.error(`- ${mismatch}`);
	process.exit(1);
}

console.log("ThreadsDashboard pipeline_contracts snapshot is in sync with packages/pipeline_contracts.");
