#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd();
const scannedRoots = ["api", "src", "tests", "scripts"];
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
		if (/\.(ts|tsx|js|mjs)$/.test(path)) files.push(path);
	}
}

for (const dir of scannedRoots) walk(join(root, dir));

const violations = [];

for (const file of files) {
	const rel = relative(root, file);
	if (rel === "scripts/check-schema-drift-boundaries.mjs") continue;
	const source = readFileSync(file, "utf8");
	if (source.includes("post_metrics_history")) {
		violations.push(`${rel} references legacy post_metrics_history; use post_metric_history`);
	}
	if (/from\(["']post_metric_history["']\)[\s\S]{0,220}recorded_at/.test(source)) {
		violations.push(`${rel} queries post_metric_history.recorded_at; use snapshot_at`);
	}
}

if (violations.length > 0) {
	console.error("ERROR: schema drift boundary violation.");
	for (const violation of violations) console.error(`- ${violation}`);
	process.exit(1);
}
