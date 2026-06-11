#!/usr/bin/env node
// Read-only reliability wiring check. By default this is static and local; when
// JUNO33_PROD_HEALTH_URL is set it performs unauthenticated GET probes only.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const requiredFiles = [
	"api/reliability.ts",
	"api/_lib/reliability.ts",
	"src/pages/Reliability.tsx",
	"supabase/migrations/20260526090000_reliability_slo_meta_usage.sql",
];
const problems = [];

for (const file of requiredFiles) {
	if (!existsSync(join(ROOT, file))) {
		problems.push(`Missing reliability file: ${file}`);
	}
}

const appSource = readFileSync(join(ROOT, "src/App.tsx"), "utf8");
if (!appSource.includes('path="/reliability"')) problems.push("Reliability route is not registered");

const operatorSource = readFileSync(join(ROOT, "api/operator.ts"), "utf8");
for (const key of ["reliabilitySlo", "metaApiUsage", "webhookHealth", "tokenSlo"]) {
	if (!operatorSource.includes(key)) problems.push(`Operator snapshot does not expose ${key}`);
}

const vercel = JSON.parse(readFileSync(join(ROOT, "vercel.json"), "utf8"));
const cronPaths = new Set((vercel.crons || []).map((cron) => cron.path));
for (const path of ["/api/cron/publish-worker", "/api/cron/health-monitor"]) {
	if (!cronPaths.has(path)) problems.push(`Expected cron path missing from vercel.json: ${path}`);
}

const healthUrl = process.env.JUNO33_PROD_HEALTH_URL;
if (healthUrl) {
	const base = healthUrl.replace(/\/$/, "");
	for (const endpoint of ["/", "/api/reliability?action=slo-summary"]) {
		const response = await fetch(`${base}${endpoint}`, { method: "GET" });
		if (response.status >= 500) {
			problems.push(`Read-only production probe failed for ${endpoint}: HTTP ${response.status}`);
		}
	}
}

if (problems.length > 0) {
	console.error(`ERROR: ${problems.length} reliability readiness issue${problems.length === 1 ? "" : "s"} found:`);
	for (const problem of problems) console.error(`  - ${problem}`);
	process.exit(1);
}

console.log("ok: reliability readiness wiring is present");
