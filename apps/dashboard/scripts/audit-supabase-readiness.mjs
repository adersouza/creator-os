#!/usr/bin/env node
// Static Supabase readiness audit.
//
// This checks the repo's migration/schema history for production prerequisites
// that otherwise only fail after deploy: critical RLS coverage, storage bucket
// provisioning, and policy hardening migrations.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const MIGRATIONS = join(ROOT, "supabase", "migrations");
const SCHEMA = join(ROOT, "supabase", "schema.sql");

const problems = [];

function readIfExists(path) {
	return existsSync(path) ? readFileSync(path, "utf8") : "";
}

const migrationFiles = existsSync(MIGRATIONS)
	? readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort()
	: [];
const migrations = migrationFiles
	.map((file) => readFileSync(join(MIGRATIONS, file), "utf8"))
	.join("\n\n");
const schema = readIfExists(SCHEMA);
const corpus = `${schema}\n\n${migrations}`.toLowerCase();

const criticalTables = [
	"accounts",
	"instagram_accounts",
	"posts",
	"account_groups",
	"auto_post_queue",
	"media",
	"media_folders",
	"inbox_items",
	"inbox_assignments",
	"listening_alerts",
	"listening_results",
	"competitors",
	"competitor_posts",
	"reports",
	"shared_reports",
	"api_keys",
	"webhook_subscriptions",
	"webhook_deliveries",
	"ai_action_log",
	"agent_actions",
	"agent_approvals",
];

for (const table of criticalTables) {
	const createTable = new RegExp(`create\\s+table(?:\\s+if\\s+not\\s+exists)?\\s+(?:public\\.)?${table}\\b`).test(corpus);
	const alterRls = new RegExp(`alter\\s+table\\s+(?:public\\.)?${table}\\s+enable\\s+row\\s+level\\s+security`).test(corpus);
	const mentionsPolicy =
		corpus.includes(` on ${table}`) ||
		corpus.includes(` on public.${table}`) ||
		corpus.includes(` on public.${table} `) ||
		corpus.includes(`tablename = '${table}'`) ||
		corpus.includes(`tablename='${table}'`);

	if (createTable && !alterRls) {
		problems.push(`${table}: table exists but no ENABLE ROW LEVEL SECURITY found`);
	}
	if (createTable && !mentionsPolicy) {
		problems.push(`${table}: table exists but no policy reference found`);
	}
}

const requiredHardeningSignals = [
	"rls_close_cross_tenant_reads",
	"views_invoker_and_bucket_listing",
	"db_security_perf_polish",
	"revoke_anon_security_definer",
	"canonicalize_service_role_rls",
	"storage_bucket_readiness",
];

for (const signal of requiredHardeningSignals) {
	if (!migrationFiles.some((file) => file.includes(signal))) {
		problems.push(`missing expected hardening migration containing "${signal}"`);
	}
}

const requiredBuckets = ["media", "post-media", "avatars", "whitelabel"];
for (const bucket of requiredBuckets) {
	if (!corpus.includes(`'${bucket}'`) && !corpus.includes(`"${bucket}"`)) {
		problems.push(`storage bucket "${bucket}" is used by code but not provisioned in migrations/schema`);
	}
}

for (const bucket of requiredBuckets) {
	const bucketPolicy =
		corpus.includes(`bucket_id in ('media', 'post-media', 'avatars', 'whitelabel')`) ||
		corpus.includes(`bucket_id = '${bucket}'`);
	if (!bucketPolicy) {
		problems.push(`storage bucket "${bucket}" has no storage.objects policy reference`);
	}
}

if (problems.length === 0) {
	console.log(
		`ok: Supabase readiness audit passed (${criticalTables.length} tables, ${requiredBuckets.length} buckets)`,
	);
	process.exit(0);
}

console.error(
	`ERROR: ${problems.length} Supabase readiness issue${problems.length === 1 ? "" : "s"} found:`,
);
for (const problem of problems) console.error(`  ${problem}`);
process.exit(1);
