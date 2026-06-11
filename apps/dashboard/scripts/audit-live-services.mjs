#!/usr/bin/env node
// Optional live production dependency probe.
//
// Runs only checks that have credentials in the current environment. It never
// prints secret values. Use this after `vercel env pull` or in CI with prod
// env vars to answer: "will the external services answer right now?"

const checks = [];
const problems = [];

function present(name) {
	return typeof process.env[name] === "string" && process.env[name].length > 0;
}

async function checkRedis() {
	if (!present("UPSTASH_REDIS_REST_URL") || !present("UPSTASH_REDIS_REST_TOKEN")) {
		checks.push("redis: skipped (missing env)");
		return;
	}
	const { Redis } = await import("@upstash/redis");
	const redis = new Redis({
		url: process.env.UPSTASH_REDIS_REST_URL,
		token: process.env.UPSTASH_REDIS_REST_TOKEN,
	});
	const result = await redis.ping();
	if (result !== "PONG") problems.push("redis: ping did not return PONG");
	else checks.push("redis: ok");
}

async function checkSupabaseBuckets() {
	if (!present("SUPABASE_URL") || !present("SUPABASE_SERVICE_ROLE_KEY")) {
		checks.push("supabase: skipped (missing env)");
		return;
	}
	const { createClient } = await import("@supabase/supabase-js");
	const supabase = createClient(
		process.env.SUPABASE_URL,
		process.env.SUPABASE_SERVICE_ROLE_KEY,
		{ auth: { autoRefreshToken: false, persistSession: false } },
	);
	const { data, error } = await supabase.storage.listBuckets();
	if (error) {
		problems.push(`supabase: bucket listing failed (${error.message})`);
		return;
	}
	const buckets = new Set((data ?? []).map((bucket) => bucket.name));
	for (const required of ["media", "post-media", "avatars", "whitelabel"]) {
		if (!buckets.has(required)) problems.push(`supabase: missing storage bucket ${required}`);
	}
	if (!problems.some((p) => p.startsWith("supabase:"))) {
		checks.push("supabase: ok");
	}
}

async function checkQStash() {
	if (!present("QSTASH_TOKEN")) {
		checks.push("qstash: skipped (missing env)");
		return;
	}
	const response = await fetch("https://qstash.upstash.io/v2/dlq", {
		headers: { Authorization: `Bearer ${process.env.QSTASH_TOKEN}` },
		signal: AbortSignal.timeout(10000),
	});
	if (!response.ok) {
		problems.push(`qstash: API returned HTTP ${response.status}`);
		return;
	}
	checks.push("qstash: ok");
}

for (const fn of [checkRedis, checkSupabaseBuckets, checkQStash]) {
	try {
		await fn();
	} catch (error) {
		problems.push(error instanceof Error ? error.message : String(error));
	}
}

for (const line of checks) console.log(line);

if (problems.length === 0) {
	console.log("ok: live service audit completed");
	process.exit(0);
}

console.error(`ERROR: ${problems.length} live service issue${problems.length === 1 ? "" : "s"} found:`);
for (const problem of problems) console.error(`  ${problem}`);
process.exit(1);
