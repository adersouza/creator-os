#!/usr/bin/env node
// Live deployment smoke probe.
//
// This checks the deployed HTTP surface, not local wiring. It intentionally
// avoids printing secrets. Set DEPLOY_SMOKE_URL or APP_URL to the deployed app.

const baseUrl = (process.env.DEPLOY_SMOKE_URL || process.env.APP_URL || "")
	.trim()
	.replace(/\/+$/, "");
const cronSecret = process.env.CRON_SECRET;

const checks = [];
const problems = [];

function fail(message) {
	problems.push(message);
}

function ok(message) {
	checks.push(message);
}

function requireBaseUrl() {
	if (!baseUrl) {
		fail("missing DEPLOY_SMOKE_URL or APP_URL");
		return false;
	}
	if (!/^https?:\/\//.test(baseUrl)) {
		fail("DEPLOY_SMOKE_URL/APP_URL must start with http:// or https://");
		return false;
	}
	return true;
}

async function request(path, init = {}) {
	const response = await fetch(`${baseUrl}${path}`, {
		...init,
		signal: AbortSignal.timeout(15000),
	});
	const contentType = response.headers.get("content-type") || "";
	const body = contentType.includes("application/json")
		? await response.json().catch(() => null)
		: await response.text().catch(() => "");
	return { response, body };
}

async function checkAppShell() {
	const { response } = await request("/");
	if (!response.ok) {
		fail(`app shell: HTTP ${response.status}`);
		return;
	}
	ok("app shell: ok");
}

async function checkPublicHealth() {
	const { response, body } = await request("/api/health/ping");
	if (!response.ok) {
		fail(`public health: HTTP ${response.status}`);
		return;
	}
	const status = body && typeof body === "object" ? body.status : null;
	if (status !== "ok") {
		fail("public health: unexpected response");
		return;
	}
	ok("public health: ok");
}

async function checkJobsHealthAuth() {
	if (!cronSecret) {
		ok("jobs health: skipped (missing CRON_SECRET)");
		return;
	}
	const { response, body } = await request("/api/health?action=jobs", {
		headers: { Authorization: `Bearer ${cronSecret}` },
	});
	if (!response.ok) {
		const code =
			body && typeof body === "object" && "error" in body
				? ` (${body.error})`
				: "";
		fail(`jobs health: HTTP ${response.status}${code}`);
		return;
	}
	ok("jobs health: ok");
}

if (requireBaseUrl()) {
	for (const fn of [checkAppShell, checkPublicHealth, checkJobsHealthAuth]) {
		try {
			await fn();
		} catch (error) {
			fail(error instanceof Error ? error.message : String(error));
		}
	}
}

for (const line of checks) console.log(line);

if (problems.length === 0) {
	console.log("ok: deployment smoke audit completed");
	process.exit(0);
}

console.error(
	`ERROR: ${problems.length} deployment smoke issue${problems.length === 1 ? "" : "s"} found:`,
);
for (const problem of problems) console.error(`  ${problem}`);
process.exit(1);
