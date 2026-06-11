#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

const root = process.cwd();
const scanRoots = ["src", "api"];
const extensions = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs"]);
const rootSourceDirs = ["services", "utils", "constants", "contexts"];

const allowedRootImports = new Set([
	"api/_lib/cron/scheduled-posts/crossPost.ts ../../../../services/aiService.js",
	"api/_lib/cron/webhook-processor/ig-processors.ts ../../../../services/aiService.js",
	"api/_lib/cron/webhook/instagram.ts ../../../../services/aiService.js",
]);

function walk(dir, files = []) {
	for (const entry of readdirSync(dir)) {
		if (entry === "node_modules" || entry === "dist" || entry === ".git") {
			continue;
		}
		const path = join(dir, entry);
		const stat = statSync(path);
		if (stat.isDirectory()) {
			walk(path, files);
			continue;
		}
		const ext = path.slice(path.lastIndexOf("."));
		if (extensions.has(ext)) files.push(path);
	}
	return files;
}

function normalizedRelative(path) {
	return relative(root, path).split(/[\\/]/).join("/");
}

function rootSourceTarget(file, specifier) {
	if (specifier.startsWith("@/")) return null;
	if (specifier.startsWith("./") || specifier.startsWith("../")) {
		const target = normalizedRelative(resolve(dirname(file), specifier));
		return rootSourceDirs.some((dir) => target === dir || target.startsWith(`${dir}/`))
			? target
			: null;
	}
	return rootSourceDirs.some((dir) => specifier === dir || specifier.startsWith(`${dir}/`))
		? specifier
		: null;
}

const importPattern =
	/(?:from\s+["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\))/g;
const violations = [];

for (const scanRoot of scanRoots) {
	for (const file of walk(join(root, scanRoot))) {
		const source = readFileSync(file, "utf8");
		for (const match of source.matchAll(importPattern)) {
			const specifier = match[1] || match[2] || "";
			const target = rootSourceTarget(file, specifier);
			if (!target) continue;

			const relFile = normalizedRelative(file);
			if (allowedRootImports.has(`${relFile} ${specifier}`)) continue;
			violations.push(`${relFile} imports ${specifier} (${target})`);
		}
	}
}

if (violations.length > 0) {
	console.error(
		"ERROR: Root source import detected. Frontend code must import from src via @/*; API code may only use the explicit legacy AI compatibility imports.",
	);
	for (const violation of violations) console.error(`- ${violation}`);
	process.exit(1);
}
