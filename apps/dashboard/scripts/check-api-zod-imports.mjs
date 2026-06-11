#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd();
const baseline = new Set(
	JSON.parse(readFileSync(join(root, "scripts/zod-import-baseline.json"), "utf8")),
);
const directZodPattern = /from\s+["']zod["']/;
const files = [];

function walk(dir) {
	for (const entry of readdirSync(dir)) {
		if (entry === "node_modules" || entry === "dist" || entry === ".git") {
			continue;
		}
		const path = join(dir, entry);
		const stat = statSync(path);
		if (stat.isDirectory()) {
			walk(path);
			continue;
		}
		if (path.endsWith(".ts")) files.push(path);
	}
}

walk(join(root, "api"));

const current = files
	.map((file) => relative(root, file))
	.filter((file) => file !== "api/_lib/zodCompat.ts")
	.filter((file) => directZodPattern.test(readFileSync(join(root, file), "utf8")))
	.sort();

const newDirectImports = current.filter((file) => !baseline.has(file));
const staleBaseline = [...baseline].filter((file) => !current.includes(file));

if (newDirectImports.length > 0) {
	console.error("ERROR: New direct API zod imports detected. Import from api/_lib/zodCompat.js instead.");
	for (const file of newDirectImports) console.error(`- ${file}`);
	process.exit(1);
}

if (staleBaseline.length > 0) {
	console.error("ERROR: zod import baseline is stale. Remove migrated files from scripts/zod-import-baseline.json.");
	for (const file of staleBaseline) console.error(`- ${file}`);
	process.exit(1);
}
