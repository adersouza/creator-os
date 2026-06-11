#!/usr/bin/env node
// Production readiness guard for deployment wiring that TypeScript cannot see.
//
// Checks:
//   1. Every Vercel cron path points at a real API file.
//   2. Every scheduled cron has an explicit function budget in vercel.json.
//   3. Critical production env names are documented in .env.example.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

function readJson(path) {
	return JSON.parse(readFileSync(path, "utf8"));
}

function relative(path) {
	return path.replace(`${ROOT}/`, "");
}

const vercelPath = join(ROOT, "vercel.json");
const envExamplePath = join(ROOT, ".env.example");
const vercel = readJson(vercelPath);
const functions = vercel.functions ?? {};
const crons = vercel.crons ?? [];
const problems = [];

for (const cron of crons) {
	const route = String(cron.path ?? "");
	const file = `${route.replace(/^\//, "")}.ts`;
	const fullPath = join(ROOT, file);

	if (!existsSync(fullPath)) {
		problems.push({
			kind: "cron_missing_file",
			message: `${route} is scheduled but ${file} does not exist`,
		});
		continue;
	}

	const source = readFileSync(fullPath, "utf8");
	if (!/verifyCronAuth|withCron\s*\(/.test(source)) {
		problems.push({
			kind: "cron_missing_auth",
			message: `${file} is scheduled but does not visibly enforce CRON_SECRET auth`,
		});
	}

	if (!functions[file]) {
		problems.push({
			kind: "cron_missing_function_budget",
			message: `${file} is scheduled but has no vercel.functions maxDuration`,
		});
	}
}

const envExample = readFileSync(envExamplePath, "utf8");
const documentedEnv = new Set(
	Array.from(envExample.matchAll(/^\s*#?\s*([A-Z][A-Z0-9_]+)=/gm), (m) => m[1]),
);

const criticalEnv = [
	"APP_URL",
	"CRON_SECRET",
	"ENCRYPTION_KEY",
	"FACEBOOK_APP_ID",
	"FACEBOOK_APP_SECRET",
	"INSTAGRAM_CLIENT_ID",
	"INSTAGRAM_CLIENT_SECRET",
	"META_APP_SECRET",
	"META_WEBHOOK_VERIFY_TOKEN",
	"QSTASH_CURRENT_SIGNING_KEY",
	"QSTASH_NEXT_SIGNING_KEY",
	"QSTASH_TOKEN",
	"RESEND_API_KEY",
	"STRIPE_SECRET_KEY",
	"STRIPE_WEBHOOK_SECRET",
	"SUPABASE_SERVICE_ROLE_KEY",
	"SUPABASE_URL",
	"THREADS_APP_SECRET",
	"THREADS_CLIENT_ID",
	"THREADS_CLIENT_SECRET",
	"UPSTASH_REDIS_REST_TOKEN",
	"UPSTASH_REDIS_REST_URL",
	"VITE_FACEBOOK_APP_ID",
	"VITE_SUPABASE_ANON_KEY",
	"VITE_SUPABASE_URL",
	"VITE_THREADS_CLIENT_ID",
];

for (const name of criticalEnv) {
	if (!documentedEnv.has(name)) {
		problems.push({
			kind: "env_missing_from_example",
			message: `${name} is part of production readiness but is missing from ${relative(envExamplePath)}`,
		});
	}
}

if (problems.length === 0) {
	console.log(
		`ok: production wiring audit passed (${crons.length} cron routes, ${criticalEnv.length} env docs)`,
	);
	process.exit(0);
}

console.error(
	`ERROR: ${problems.length} production readiness issue${problems.length === 1 ? "" : "s"} found:`,
);
for (const problem of problems) {
	console.error(`  [${problem.kind}] ${problem.message}`);
}
process.exit(1);
