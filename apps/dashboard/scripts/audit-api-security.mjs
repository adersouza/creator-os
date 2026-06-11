#!/usr/bin/env node
// API security surface guard.
//
// This is intentionally conservative: API entrypoints must either show an
// auth/signature/secret marker, route into authenticated handlers, or be in the
// explicit public allowlist. It catches newly added public routes before they
// become accidental production exposure.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const API = join(ROOT, "api");

const PUBLIC_ROUTE_FILES = [
	"api/auth/apply-referral.ts",
	"api/auth/oauth-state.ts",
	"api/check-deletion-status.ts",
	"api/csp-report.ts",
	"api/favicon.ts",
	"api/health/ping.ts",
	"api/instagram/webhook.ts",
	"api/meta/data-deletion.ts",
	"api/meta/deauthorize.ts",
	"api/sentry-tunnel.ts",
	"api/shared-report.ts",
	"api/sitemap.ts",
	"api/threads/webhook.ts",
	"api/webhook.ts",
];

const PUBLIC_ROUTE_PATTERNS = [
	/^api\/go\/.+\.ts$/,
	/^api\/link-page\/.+\.ts$/,
];

const AUTH_MARKER =
	/(withAuth\s*\(|withAdminRole\s*\(|withCron\s*\(|withApiKey\s*\(|getAuthUserOrError|auth\.getUser|verifyCronAuth|verifyQStashSignature|createRefreshHandler\s*\(|STRIPE_WEBHOOK_SECRET|X-Hub-Signature|hub\.verify_token|META_WEBHOOK_VERIFY_TOKEN|signed_request|Authorization|authorization)/;

const DELEGATED_ROUTER_MARKER =
	/(Thin Router|Consolidated .* API Route|return\s+\(await import\(|return\s+handle[A-Z]|createRefreshHandler\s*\()/;
const SKIP_DIRS = new Set([
	"_lib",
	"types",
	"node_modules",
	".git",
	".next",
	"dist",
	"build",
	"coverage",
]);

function resolveReExportTarget(file, source) {
	const match = source.match(/export\s+\{\s*default\s*\}\s+from\s+["']([^"']+)["']/);
	if (!match) return null;
	const specifier = match[1];
	if (!specifier.startsWith(".")) return null;
	return resolve(join(file, ".."), specifier).replace(/\.js$/, ".ts");
}

function walk(dir) {
	const out = [];
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = join(dir, entry.name);
		if (entry.isDirectory()) {
			if (SKIP_DIRS.has(entry.name)) continue;
			out.push(...walk(full));
		} else if (entry.isFile() && extname(entry.name) === ".ts") {
			out.push(full);
		}
	}
	return out;
}

function isFile(path) {
	try {
		return statSync(path).isFile();
	} catch {
		return false;
	}
}

const problems = [];

for (const file of walk(API)) {
	const rel = relative(ROOT, file);
	const source = readFileSync(file, "utf8");
	const reExportTarget = resolveReExportTarget(file, source);
	const reExportHasAuth =
		reExportTarget && isFile(reExportTarget)
			? AUTH_MARKER.test(readFileSync(reExportTarget, "utf8"))
			: false;
	const allowedPublic =
		PUBLIC_ROUTE_FILES.includes(rel) ||
		PUBLIC_ROUTE_PATTERNS.some((pattern) => pattern.test(rel));
	const hasAuthMarker = AUTH_MARKER.test(source);
	const delegatedRouter = DELEGATED_ROUTER_MARKER.test(source);

	if (!allowedPublic && !hasAuthMarker && !delegatedRouter && !reExportHasAuth) {
		problems.push(`${rel} has no visible auth/signature marker`);
	}

	if (rel.startsWith("api/cron/") && !/verifyCronAuth|withCron\s*\(/.test(source)) {
		problems.push(`${rel} is a cron route without visible CRON_SECRET auth`);
	}

	if (
		rel.startsWith("api/auth/") &&
		!allowedPublic &&
		!hasAuthMarker &&
		!delegatedRouter &&
		!reExportHasAuth
	) {
		problems.push(`${rel} is an auth route without visible user validation`);
	}
}

for (const file of PUBLIC_ROUTE_FILES) {
	if (!isFile(join(ROOT, file))) {
		problems.push(`allowlisted public route does not exist: ${file}`);
	}
}

if (problems.length === 0) {
	console.log("ok: API security surface audit passed");
	process.exit(0);
}

console.error(
	`ERROR: ${problems.length} API security issue${problems.length === 1 ? "" : "s"} found:`,
);
for (const problem of problems) {
	console.error(`  ${problem}`);
}
process.exit(1);
