import { describe, expect, it } from "vitest";
import { calculateSchedulingSlo, classifyReliabilityRetry, parseMetaApiUsageHeaders } from "../../api/_lib/reliability";

describe("reliability center helpers", () => {
	it("calculates scheduling SLO rates and drift percentiles", () => {
		const summary = calculateSchedulingSlo([
			{
				id: "post-1",
				status: "published",
				account_id: "account-1",
				scheduled_for: "2026-05-25T12:00:00.000Z",
				published_at: "2026-05-25T12:00:42.000Z",
			},
			{
				id: "post-2",
				status: "published",
				account_id: "account-2",
				scheduled_for: "2026-05-25T12:00:00.000Z",
				published_at: "2026-05-25T12:06:00.000Z",
			},
			{
				id: "post-3",
				status: "failed",
				account_id: "account-3",
				scheduled_for: "2026-05-25T12:00:00.000Z",
			},
		], [{ id: "queue-1", account_id: "account-4", status: "dead_letter" }]);

		expect(summary.scheduledTotal).toBe(3);
		expect(summary.publishedTotal).toBe(2);
		expect(summary.failedTotal).toBe(1);
		expect(summary.onTime60s).toBe(1);
		expect(summary.lateOver5m).toBe(1);
		expect(summary.successRate).toBe(66.67);
		expect(summary.onTimeRate).toBe(50);
		expect(summary.driftSeconds.p95).toBe(360);
		expect(summary.qstashFailures).toBe(1);
		expect(summary.tone).toBe("critical");
	});

	it("parses Meta usage and Retry-After headers into reliability tones", () => {
		const headers = new Headers({
			"X-App-Usage": JSON.stringify({ call_count: 84, total_time: 12 }),
			"Retry-After": "60",
		});
		const parsed = parseMetaApiUsageHeaders(headers);
		expect(parsed.usagePercent).toBe(84);
		expect(parsed.retryAfterSeconds).toBe(60);
		expect(parsed.tone).toBe("critical");
	});

	it("classifies retry outcomes consistently for operator recovery", () => {
		expect(classifyReliabilityRetry({ status: 429 }).classification).toBe("rate_limit_retry");
		expect(classifyReliabilityRetry({ status: 500 }).classification).toBe("transient_retry");
		expect(classifyReliabilityRetry({ error: new Error("Error validating access token: code 190") }).classification).toBe("definitive_auth_failure");
		expect(classifyReliabilityRetry({ error: new Error("Invalid JSON payload") }).classification).toBe("permanent_failure");
	});
});
