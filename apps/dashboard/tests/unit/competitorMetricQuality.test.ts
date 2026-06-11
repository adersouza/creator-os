import { describe, expect, it } from "vitest";
import {
	classifyCompetitorPattern,
	evaluateCompetitorMetricQuality,
	hasValidCompetitorEngagement,
} from "../../api/_lib/handlers/competitors/metricQuality";

describe("competitor metric quality", () => {
	it("marks official Threads competitor rows with empty stats as unavailable", () => {
		const decision = evaluateCompetitorMetricQuality({
			platform: "threads",
			viewCount: 0,
			likeCount: 0,
			replyCount: 0,
			repostCount: 0,
		});

		expect(decision).toMatchObject({
			metric_source: "official_profile_posts",
			metric_quality: "stats_unavailable",
			metric_quality_reason: "official_threads_competitor_stats_unavailable",
		});
		expect(hasValidCompetitorEngagement(decision.metric_quality)).toBe(false);
	});

	it("marks Threads rows with interactions but no views as partial engagement", () => {
		const decision = evaluateCompetitorMetricQuality({
			platform: "threads",
			likeCount: 12,
			replyCount: 2,
			repostCount: 0,
			viewCount: 0,
		});

		expect(decision.metric_quality).toBe("partial_engagement");
		expect(hasValidCompetitorEngagement(decision.metric_quality)).toBe(false);
	});

	it("only treats rows with views as valid Threads engagement", () => {
		const decision = evaluateCompetitorMetricQuality({
			platform: "threads",
			viewCount: 1000,
			likeCount: 12,
		});

		expect(decision.metric_quality).toBe("valid_engagement");
		expect(hasValidCompetitorEngagement(decision.metric_quality)).toBe(true);
	});

	it("marks old scraper-enriched Threads rows as estimated, not official impressions", () => {
		const decision = evaluateCompetitorMetricQuality({
			platform: "threads",
			metricSource: "apify_threads_post_scraper",
			viewCount: 0,
			likeCount: 8,
			replyCount: 1,
			enrichedAt: "2026-06-05T00:00:00.000Z",
		});

		expect(decision).toMatchObject({
			metric_source: "apify_threads_post_scraper",
			metric_quality: "scraper_estimated",
			metric_quality_reason: "scraper_estimated_engagement_without_views",
			last_metric_checked_at: "2026-06-05T00:00:00.000Z",
		});
		expect(hasValidCompetitorEngagement(decision.metric_quality)).toBe(true);
	});

	it("classifies observable pattern fields without performance data", () => {
		const pattern = classifyCompetitorPattern({
			content: "be honest would you date me?",
			followerCount: 58_000,
			mediaType: "IMAGE",
			publishedAt: "2026-06-05T18:30:00.000Z",
		});

		expect(pattern).toMatchObject({
			hook_type: "question",
			format_type: "media_post",
			emotional_frame: "inviting",
			cta_style: "implicit_question",
			media_style: "image",
			posting_hour: 18,
			reply_mechanism: "direct_prompt",
			account_size_bucket: "50k_100k",
		});
	});
});
