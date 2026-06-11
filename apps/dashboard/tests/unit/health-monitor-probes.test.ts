/**
 * Health Monitor Canary Probe Tests
 *
 * Validates that health-monitor.ts contains all required
 * infrastructure connectivity probes and monitoring canaries.
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const MONITOR_PATH = join(__dirname, "../../api/cron/health-monitor.ts");
const monitorCode = readFileSync(MONITOR_PATH, "utf-8");

describe("Health Monitor Infrastructure Probes", () => {
	// Infrastructure connectivity
	it("must have DB connectivity probe", () => {
		expect(monitorCode).toContain("checkDbConnectivity");
	});

	it("must have Redis connectivity probe", () => {
		expect(monitorCode).toContain("checkRedisConnectivity");
		expect(monitorCode).toContain("ping()");
	});

	it("must have QStash connectivity probe", () => {
		expect(monitorCode).toContain("checkQStashConnectivity");
		expect(monitorCode).toContain("qstash.upstash.io");
	});

	// Sustained failure detection
	it("must have sync orchestrator health check", () => {
		expect(monitorCode).toContain("checkSyncOrchestratorHealth");
		expect(monitorCode).toContain("sync-orchestrator");
	});

	it("must have queue backlog check", () => {
		expect(monitorCode).toContain("checkQueueBacklog");
		expect(monitorCode).toContain("auto_post_queue");
	});

	// All probes wired into canary runner
	it("all probes must be wired into runCanaryCheck Promise.allSettled", () => {
		// Extract the Promise.allSettled block in runCanaryCheck
		const canaryFnStart = monitorCode.indexOf("async function runCanaryCheck");
		const allSettledStart = monitorCode.indexOf("Promise.allSettled([", canaryFnStart);
		const allSettledEnd = monitorCode.indexOf("]);", allSettledStart);
		const allSettledBlock = monitorCode.slice(allSettledStart, allSettledEnd);

		const requiredProbes = [
			"checkStaleAccounts",
			"checkDailyOrchestratorRate",
			"checkWebhookLag",
			"checkWebhookSubscriptions",
			"checkAccountSyncFreshness",
			"checkGeminiErrorRate",
			"checkCronFreshness",
			"checkDbConnectivity",
			"checkRedisConnectivity",
			"checkQStashConnectivity",
			"checkSyncOrchestratorHealth",
			"checkQueueBacklog",
		];

		for (const probe of requiredProbes) {
			expect(allSettledBlock).toContain(probe);
		}
	});

	// Each probe returns CanaryResult
	it("all probe functions must return CanaryResult with required fields", () => {
		const probes = [
			"checkDbConnectivity",
			"checkRedisConnectivity",
			"checkQStashConnectivity",
			"checkSyncOrchestratorHealth",
			"checkQueueBacklog",
		];

		for (const probe of probes) {
			const fnStart = monitorCode.indexOf(`async function ${probe}`);
			expect(fnStart).toBeGreaterThan(-1);
			// Find the return type annotation
			const fnSignature = monitorCode.slice(fnStart, fnStart + 200);
			expect(fnSignature).toContain("CanaryResult");
		}
	});
});

describe("Health Monitor Existing Canaries", () => {
	it("must check stale accounts", () => {
		expect(monitorCode).toContain("checkStaleAccounts");
		expect(monitorCode).toContain("last_synced_at");
		expect(monitorCode).toContain('.eq("is_active", true)');
		expect(monitorCode).toContain('.eq("is_retired", false)');
		expect(monitorCode).toContain('.eq("needs_reauth", false)');
		expect(monitorCode).toContain('.not("threads_access_token_encrypted", "is", null)');
	});

	it("must check daily orchestrator success rate", () => {
		expect(monitorCode).toContain("checkDailyOrchestratorRate");
	});

	it("must check webhook lag", () => {
		expect(monitorCode).toContain("checkWebhookLag");
	});

	it("must check per-account sync and webhook freshness", () => {
		expect(monitorCode).toContain("checkAccountSyncFreshness");
		expect(monitorCode).toContain("getAccountSyncHealth");
	});

	it("must check Gemini error rate", () => {
		expect(monitorCode).toContain("checkGeminiErrorRate");
	});

	it("must check cron freshness", () => {
		expect(monitorCode).toContain("checkCronFreshness");
	});
});
