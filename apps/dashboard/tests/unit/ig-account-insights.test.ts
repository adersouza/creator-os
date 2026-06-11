import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	_resetAlertingForTests,
	flushPartialInsightsAlert,
	trackInsightsResponse,
} from "../../api/_lib/alerting";
import {
	getTimeSeriesMetrics,
	getTotalValueMetrics,
	isBatchSupported,
	ACCOUNT_INSIGHTS,
	POST_INSIGHT_METRICS,
	REEL_INSIGHT_METRICS,
	BATCH_API,
} from "../../api/_lib/metaApiConfig";

/**
 * Tests for Instagram Account Insights response parsing.
 *
 * Meta API returns two different response formats depending on metric_type:
 * - time_series: { values: [{ value: N }] }
 * - total_value: { total_value: { value: N } }
 *
 * Our parser must handle both formats when merging results from parallel calls.
 */

interface InsightsMetricItem {
	name: string;
	values?: Array<{ value: number }>;
	total_value?: { value: number };
	period?: string;
}

/** Mirrors the parsing logic in instagramApi.ts getInstagramAccountInsights */
function parseInsightsData(data: InsightsMetricItem[]) {
	const insights = {
		reach: 0,
		followerCount: 0,
		accountsEngaged: 0,
		totalInteractions: 0,
		profileLinksTaps: 0,
		websiteClicks: 0,
	};

	for (const item of data) {
		const name = item.name?.toLowerCase();
		// time_series returns values[0].value, total_value returns total_value.value
		const value = item.values?.[0]?.value ?? item.total_value?.value ?? 0;

		switch (name) {
			case "reach":
				insights.reach = value;
				break;
			case "follower_count":
				insights.followerCount = value;
				break;
			case "accounts_engaged":
				insights.accountsEngaged = value;
				break;
			case "total_interactions":
				insights.totalInteractions = value;
				break;
			case "profile_links_taps":
				insights.profileLinksTaps = value;
				insights.websiteClicks = value;
				break;
		}
	}

	return insights;
}

describe("IG Account Insights parsing", () => {
	it("parses time_series format (values[0].value)", () => {
		const data: InsightsMetricItem[] = [
			{ name: "reach", values: [{ value: 250 }], period: "day" },
			{ name: "follower_count", values: [{ value: 1200 }], period: "day" },
		];

		const result = parseInsightsData(data);
		expect(result.reach).toBe(250);
		expect(result.followerCount).toBe(1200);
	});

	it("parses total_value format (total_value.value)", () => {
		const data: InsightsMetricItem[] = [
			{ name: "accounts_engaged", total_value: { value: 85 } },
			{ name: "total_interactions", total_value: { value: 340 } },
			{ name: "profile_links_taps", total_value: { value: 12 } },
		];

		const result = parseInsightsData(data);
		expect(result.accountsEngaged).toBe(85);
		expect(result.totalInteractions).toBe(340);
		expect(result.profileLinksTaps).toBe(12);
		expect(result.websiteClicks).toBe(12); // backwards compat
	});

	it("parses merged time_series + total_value responses (production shape)", () => {
		const data: InsightsMetricItem[] = [
			// From time_series call
			{ name: "reach", values: [{ value: 500 }], period: "day" },
			{ name: "follower_count", values: [{ value: 3000 }], period: "day" },
			// From total_value call
			{ name: "accounts_engaged", total_value: { value: 120 } },
			{ name: "total_interactions", total_value: { value: 450 } },
			{ name: "profile_links_taps", total_value: { value: 25 } },
		];

		const result = parseInsightsData(data);
		expect(result.reach).toBe(500);
		expect(result.followerCount).toBe(3000);
		expect(result.accountsEngaged).toBe(120);
		expect(result.totalInteractions).toBe(450);
		expect(result.profileLinksTaps).toBe(25);
	});

	it("returns 0 for metrics with no values or total_value", () => {
		const data: InsightsMetricItem[] = [
			{ name: "reach" },
			{ name: "accounts_engaged", values: [] },
		];

		const result = parseInsightsData(data);
		expect(result.reach).toBe(0);
		expect(result.accountsEngaged).toBe(0);
	});

	it("prefers values[0] over total_value when both present", () => {
		const data: InsightsMetricItem[] = [
			{
				name: "reach",
				values: [{ value: 100 }],
				total_value: { value: 200 },
			},
		];

		const result = parseInsightsData(data);
		expect(result.reach).toBe(100);
	});

	it("handles zero values correctly (not falsy-skipped)", () => {
		const data: InsightsMetricItem[] = [
			{ name: "reach", values: [{ value: 0 }] },
			{ name: "accounts_engaged", total_value: { value: 0 } },
		];

		const result = parseInsightsData(data);
		expect(result.reach).toBe(0);
		expect(result.accountsEngaged).toBe(0);
	});
});

describe("IG Account Insights URL construction", () => {
	it("includes metric_type=time_series for reach/follower_count", () => {
		const period = "day";
		const igUserId = "12345";
		const timeSeriesMetrics = period === "day" ? "reach,follower_count" : "reach";
		const url = `https://graph.instagram.com/v25.0/${igUserId}/insights?metric=${timeSeriesMetrics}&period=${period}&metric_type=time_series`;

		expect(url).toContain("metric_type=time_series");
		expect(url).toContain("metric=reach,follower_count");
	});

	it("includes metric_type=total_value for engagement metrics", () => {
		const period = "day";
		const igUserId = "12345";
		const totalValueMetrics = "accounts_engaged,total_interactions,profile_links_taps";
		const url = `https://graph.instagram.com/v25.0/${igUserId}/insights?metric=${totalValueMetrics}&period=${period}&metric_type=total_value`;

		expect(url).toContain("metric_type=total_value");
		expect(url).toContain("accounts_engaged");
		expect(url).toContain("total_interactions");
		expect(url).toContain("profile_links_taps");
	});

	it("strips follower_count from time_series when period != day", () => {
		const period: string = "week";
		const timeSeriesMetrics = period === "day" ? "reach,follower_count" : "reach";

		expect(timeSeriesMetrics).toBe("reach");
		expect(timeSeriesMetrics).not.toContain("follower_count");
	});

	it("excludes profile_links_taps for facebook login type", () => {
		const loginType: string = "facebook";
		const totalValueMetrics =
			loginType === "facebook"
				? "accounts_engaged,total_interactions"
				: "accounts_engaged,total_interactions,profile_links_taps";

		expect(totalValueMetrics).not.toContain("profile_links_taps");
	});
});

// ============================================================================
// metaApiConfig.ts contract tests
// ============================================================================

describe("Meta API Config — single source of truth", () => {
	it("getTimeSeriesMetrics includes follower_count for day period", () => {
		const metrics = getTimeSeriesMetrics("day");
		expect(metrics).toContain("reach");
		expect(metrics).toContain("follower_count");
	});

	it("getTimeSeriesMetrics excludes follower_count for non-day periods", () => {
		expect(getTimeSeriesMetrics("week")).toBe("reach");
		expect(getTimeSeriesMetrics("days_28")).toBe("reach");
	});

	it("getTotalValueMetrics includes profile_links_taps for instagram login", () => {
		const metrics = getTotalValueMetrics("instagram");
		expect(metrics).toContain("accounts_engaged");
		expect(metrics).toContain("total_interactions");
		expect(metrics).toContain("profile_links_taps");
	});

	it("getTotalValueMetrics excludes profile_links_taps for facebook login", () => {
		const metrics = getTotalValueMetrics("facebook");
		expect(metrics).toContain("accounts_engaged");
		expect(metrics).not.toContain("profile_links_taps");
	});

	it("batch API is NOT supported for instagram login type", () => {
		expect(isBatchSupported("instagram")).toBe(false);
		expect(isBatchSupported(undefined)).toBe(false);
	});

	it("batch API IS supported for facebook login type", () => {
		expect(isBatchSupported("facebook")).toBe(true);
	});

	it("ACCOUNT_INSIGHTS metric types are correct", () => {
		expect(ACCOUNT_INSIGHTS.timeSeries.metricType).toBe("time_series");
		expect(ACCOUNT_INSIGHTS.totalValue.metricType).toBe("total_value");
	});

	it("POST_INSIGHT_METRICS contains all required metrics", () => {
		for (const m of ["views", "reach", "likes", "comments", "shares", "saved"]) {
			expect(POST_INSIGHT_METRICS).toContain(m);
		}
	});

	it("REEL_INSIGHT_METRICS avoids Instagram Login rejected metrics", () => {
		expect(REEL_INSIGHT_METRICS).toContain("views");
		expect(REEL_INSIGHT_METRICS).toContain("ig_reels_avg_watch_time");
		expect(REEL_INSIGHT_METRICS).not.toContain("reposts");
	});

	it("BATCH_API base URL is facebook (not instagram)", () => {
		expect(BATCH_API.baseUrl).toBe("https://graph.facebook.com");
	});
});

// ============================================================================
// Partial insights alert — trackInsightsResponse + flushPartialInsightsAlert
// ============================================================================

describe("Partial insights alert — threshold and accumulator logic", () => {
	let mockFetch: ReturnType<typeof vi.fn>;

	beforeEach(() => {
		// Provide a webhook URL so alert() doesn't early-return
		process.env.DISCORD_ALERT_WEBHOOK_URL = "https://discord.test/webhook";
		mockFetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
		vi.stubGlobal("fetch", mockFetch);
		_resetAlertingForTests();
	});

	afterEach(() => {
		delete process.env.DISCORD_ALERT_WEBHOOK_URL;
		vi.unstubAllGlobals();
		_resetAlertingForTests();
	});

	it("fires alert when >50% of accounts have missing metrics (80% case)", async () => {
		// 4 of 5 accounts partial = 80%
		trackInsightsResponse(false);
		trackInsightsResponse(true, ["reach", "accounts_engaged"]);
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(true, ["accounts_engaged"]);
		trackInsightsResponse(true, ["reach", "total_interactions"]);

		await flushPartialInsightsAlert();

		expect(mockFetch).toHaveBeenCalledOnce();
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		expect(body.embeds[0].title).toContain(
			"IG insights API contract change detected",
		);
	});

	it("includes all unique missing metric names (deduplicates across accounts)", async () => {
		// 3 of 3 partial = 100%
		trackInsightsResponse(true, ["reach", "accounts_engaged"]);
		trackInsightsResponse(true, ["total_interactions"]);
		trackInsightsResponse(true, ["reach"]); // reach is a duplicate — should appear once

		await flushPartialInsightsAlert();

		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		const fields = body.embeds[0].fields as Array<{
			name: string;
			value: string;
		}>;
		const missingField = fields.find((f) => f.name === "missingMetrics");
		expect(missingField?.value).toContain("reach");
		expect(missingField?.value).toContain("accounts_engaged");
		expect(missingField?.value).toContain("total_interactions");
		// Verify deduplication: "reach" appears once, not twice
		expect((missingField?.value ?? "").split("reach").length - 1).toBe(1);
	});

	it("does NOT fire when ≤50% of accounts have missing metrics (isolated failure, not API change)", async () => {
		// 1 of 3 = 33%
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(false);
		trackInsightsResponse(false);

		await flushPartialInsightsAlert();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("does NOT fire at exactly 50% — threshold is strictly >50%", async () => {
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(false);

		await flushPartialInsightsAlert();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("does NOT fire when no accounts were processed", async () => {
		await flushPartialInsightsAlert();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("does NOT fire when all accounts returned full data", async () => {
		trackInsightsResponse(false);
		trackInsightsResponse(false);
		trackInsightsResponse(false);

		await flushPartialInsightsAlert();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("accumulator resets after flush — second flush with empty state does not re-fire", async () => {
		for (let i = 0; i < 5; i++) trackInsightsResponse(true, ["reach"]);

		await flushPartialInsightsAlert();
		expect(mockFetch).toHaveBeenCalledOnce();

		// Reset mock, run second flush — accumulator is empty so alert must not fire
		mockFetch.mockClear();
		await flushPartialInsightsAlert();
		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("affected field shows correct count and percentage", async () => {
		// 3 of 4 = 75%
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(true, ["reach"]);
		trackInsightsResponse(false);

		await flushPartialInsightsAlert();

		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		const fields = body.embeds[0].fields as Array<{
			name: string;
			value: string;
		}>;
		const affectedField = fields.find((f) => f.name === "affected");
		expect(affectedField?.value).toBe("3/4 accounts (75%)");
	});

	it("does NOT fire when only expected-optional metrics are missing (e.g. follower_count)", async () => {
		// 3 of 3 = 100% partial, but ONLY follower_count missing — expected omission
		trackInsightsResponse(true, ["follower_count"]);
		trackInsightsResponse(true, ["follower_count"]);
		trackInsightsResponse(true, ["follower_count"]);

		await flushPartialInsightsAlert();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("still fires when unexpected metrics are missing alongside follower_count", async () => {
		// follower_count is optional but reach is not — should still alert
		trackInsightsResponse(true, ["follower_count", "reach"]);
		trackInsightsResponse(true, ["follower_count", "reach"]);
		trackInsightsResponse(true, ["follower_count"]);

		await flushPartialInsightsAlert();

		expect(mockFetch).toHaveBeenCalledOnce();
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		const fields = body.embeds[0].fields as Array<{
			name: string;
			value: string;
		}>;
		const missingField = fields.find((f) => f.name === "missingMetrics");
		expect(missingField?.value).toContain("reach");
		expect(missingField?.value).not.toContain("follower_count");
	});
});
