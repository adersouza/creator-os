#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd();
const scanRoot = join(root, "src/services");
const extensions = new Set([".ts", ".tsx"]);

const allowedRawFetchFiles = new Set([
	// OAuth, uploads, streams, raw responses, and telemetry/fire-and-forget
	// clients are intentionally outside apiFetch for now. Keep this list narrow
	// and documented when adding a new exception.
	"src/services/clientTelemetry.ts",
	"src/services/api/accounts.ts",
	"src/services/api/composer.ts",
	"src/services/api/contentLibrary.ts",
	"src/services/api/instagram.ts",
	"src/services/api/media.ts",
	"src/services/api/posts.ts",
	"src/services/api/reportsPdf.ts",
	"src/services/api/shared.ts",
	"src/services/autoPost/apiClient.ts",
	"src/services/autoPost/config.ts",
	"src/services/subscriptionService.ts",
	"src/services/voiceProfileService.ts",
]);

function walk(dir, files = []) {
	for (const entry of readdirSync(dir)) {
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

const violations = [];

for (const file of walk(scanRoot)) {
	const relFile = relative(root, file).split(/[\\/]/).join("/");
	if (allowedRawFetchFiles.has(relFile)) continue;

	const source = readFileSync(file, "utf8");
	if (
		/\bfetch\s*\(\s*apiUrl\s*\(\s*["']\/api\//.test(source) ||
		/\bfetch\s*\(\s*["']\/api\//.test(source)
	) {
		violations.push(relFile);
	}
}

if (violations.length > 0) {
	console.error(
		"ERROR: Raw internal API fetch detected in src/services. Use apiFetch() with a response schema, or add a narrowly documented allowlist entry for streaming/upload/raw-response clients.",
	);
	for (const violation of violations) console.error(`- ${violation}`);
	process.exit(1);
}
