#!/usr/bin/env node

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const repoRoot = resolve(new URL("..", import.meta.url).pathname);
const canonicalRoot = join(repoRoot, "packages", "pipeline_contracts");
const canonicalSchemas = join(canonicalRoot, "schemas");
const canonicalTypescript = join(canonicalRoot, "typescript", "index.ts");
const canonicalGeneratedTypescript = join(canonicalRoot, "typescript", "generated-schemas.ts");

const schemaMirrors = [
	{
		name: "package runtime schemas",
		path: join(canonicalRoot, "pipeline_contracts", "schemas"),
	},
	{
		name: "root compatibility schemas",
		path: join(repoRoot, "pipeline_contracts", "schemas"),
	},
	{
		name: "campaign factory compatibility schemas",
		path: join(repoRoot, "python_packages", "campaign_factory", "schemas"),
	},
];

const fileMirrors = [
	{
		name: "root compatibility TypeScript exports",
		canonical: canonicalTypescript,
		path: join(repoRoot, "pipeline_contracts", "typescript", "index.ts"),
	},
	{
		name: "root compatibility generated TypeScript schemas",
		canonical: canonicalGeneratedTypescript,
		path: join(repoRoot, "pipeline_contracts", "typescript", "generated-schemas.ts"),
	},
];

function listFiles(root) {
	if (!existsSync(root)) return [];
	const entries = [];
	const visit = (directory) => {
		for (const entry of readdirSync(directory).sort()) {
			const fullPath = join(directory, entry);
			if (statSync(fullPath).isDirectory()) {
				visit(fullPath);
			} else {
				entries.push(relative(root, fullPath));
			}
		}
	};
	visit(root);
	return entries;
}

function read(path) {
	return readFileSync(path, "utf8");
}

const failures = [];

if (!existsSync(canonicalSchemas)) {
	failures.push(`missing canonical schema directory: ${canonicalSchemas}`);
}
if (!existsSync(canonicalTypescript)) {
	failures.push(`missing canonical TypeScript exports: ${canonicalTypescript}`);
}
if (!existsSync(canonicalGeneratedTypescript)) {
	failures.push(`missing canonical generated TypeScript schemas: ${canonicalGeneratedTypescript}`);
}

const canonicalSchemaFiles = listFiles(canonicalSchemas);
for (const mirror of schemaMirrors) {
	if (!existsSync(mirror.path)) {
		failures.push(`${mirror.name} missing: ${mirror.path}`);
		continue;
	}
	const mirrorFiles = listFiles(mirror.path);
	const canonicalSet = new Set(canonicalSchemaFiles);
	const mirrorSet = new Set(mirrorFiles);
	for (const file of canonicalSchemaFiles) {
		const mirrorPath = join(mirror.path, file);
		if (!mirrorSet.has(file)) {
			failures.push(`${mirror.name} missing ${file}`);
			continue;
		}
		const canonicalPath = join(canonicalSchemas, file);
		if (read(canonicalPath) !== read(mirrorPath)) {
			failures.push(`${mirror.name} drift: ${file}`);
		}
	}
	for (const file of mirrorFiles) {
		if (!canonicalSet.has(file)) {
			failures.push(`${mirror.name} has non-canonical file: ${file}`);
		}
	}
}

for (const mirror of fileMirrors) {
	if (!existsSync(mirror.path)) {
		failures.push(`${mirror.name} missing: ${mirror.path}`);
		continue;
	}
	if (read(mirror.canonical) !== read(mirror.path)) {
		failures.push(`${mirror.name} drift: ${relative(repoRoot, mirror.path)}`);
	}
}

if (failures.length > 0) {
	console.error("ERROR: pipeline contract mirrors are out of sync with packages/pipeline_contracts.");
	for (const failure of failures) console.error(`- ${failure}`);
	process.exit(1);
}

console.log("Pipeline contract mirrors are in sync with packages/pipeline_contracts.");
