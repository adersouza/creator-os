import { describe, expect, it } from "vitest";
import {
	buildQualityGateEffectivenessReport,
	type QualityGateQueueContext,
} from "../../api/_lib/handlers/auto-post/qualityGateEffectiveness";
import type { AutoposterPerformanceFact } from "../../api/_lib/handlers/auto-post/performanceFirst";

function fact(
	postId: string,
	content: string,
	views24h: number,
	queueId: string,
	overrides: Partial<AutoposterPerformanceFact> = {},
): AutoposterPerformanceFact {
	return {
		post_id: postId,
		user_id: "user_1",
		workspace_id: "workspace_1",
		group_id: "group_1",
		group_name: "Lola — Mains",
		account_id: "account_1",
		account_username: "lola_test",
		creator_key: "Lola",
		content,
		published_at: "2026-06-01T12:00:00.000Z",
		posting_hour: 12,
		platform: "threads",
		views_1h: views24h,
		views_24h: views24h,
		current_views: views24h,
		replies_1h: 0,
		replies_24h: 0,
		current_replies: 0,
		likes_24h: 0,
		current_likes: 0,
		reposts_count: 0,
		quotes_count: 0,
		media_type: null,
		media_style: null,
		has_media: false,
		source_type: "ai",
		source_id: null,
		source_competitor_id: null,
		source_competitor_username: null,
		direct_copy_reason: null,
		microcopy_confidence: null,
		content_archetype: "identity_statement",
		question_subtype: null,
		shape_id: null,
		hook_type: "identity",
		topic_label: "dating",
		format_type: "one_liner",
		emotional_frame: "playful",
		reply_mechanism: "implied",
		content_length_bucket: "short",
		strategy_recommendation_id: null,
		strategy_bucket: "none",
		prompt_version: null,
		template_id: null,
		model_provider: null,
		source_pattern_id: null,
		dna_fit_score: null,
		creator_fit_score: null,
		account_flavor_score: null,
		genericness_score: null,
		smart_link_clicks: 0,
		smart_link_conversions: 0,
		smart_link_revenue: 0,
		profile_clicks_proxy: null,
		profile_clicks_proxy_scope: null,
		metrics_quality: "views_only",
		metric_notes: { queueId },
		...overrides,
	};
}

function queue(
	id: string,
	decision: "pass" | "needs_review" | "block",
	reason: string,
): QualityGateQueueContext {
	return {
		id,
		source_type: "ai",
		metadata: {
			quality_gate: {
				decision,
				reason,
				flags: [],
				score: {
					replyTrigger: decision === "pass" ? 3 : 1,
					emotionalWarmth: 3,
					overall: decision === "pass" ? 3.2 : 2.1,
					rejectReason: null,
				},
			},
		},
	};
}

describe("quality gate effectiveness report", () => {
	it("counts historical winners blocked as false positives and losers allowed as false negatives", () => {
		const facts = [
			fact("winner_blocked", "i'm single. i can cook", 150, "q1"),
			fact("winner_passed", "i'm a 9 but my anime taste is unhinged", 140, "q2"),
			fact("loser_blocked", "who's up rn", 1, "q3"),
			fact("loser_passed", "anyone else", 2, "q4"),
		];
		const queueById = new Map([
			["q1", queue("q1", "needs_review", "confidence:uncertain_content")],
			["q2", queue("q2", "pass", "quality_gate_passed")],
			["q3", queue("q3", "block", "filter:generic_bait")],
			["q4", queue("q4", "pass", "quality_gate_passed")],
		]);

		const report = buildQualityGateEffectivenessReport({
			facts,
			queueById,
			now: new Date("2026-06-06T00:00:00.000Z"),
			days: 30,
		});

		expect(report.confusion.falsePositiveWinnersBlocked).toBe(1);
		expect(report.confusion.falseNegativeLosersAllowed).toBe(1);
		expect(report.summary.winnerBlockedRate).toBe(50);
		expect(report.summary.loserBlockRate).toBe(50);
		expect(report.boards.historicalWinnersBlocked[0].postId).toBe(
			"winner_blocked",
		);
		expect(report.boards.historicalLosersAllowed[0].postId).toBe(
			"loser_passed",
		);
	});

	it("reports replayed gate data quality when queue metadata is missing", () => {
		const report = buildQualityGateEffectivenessReport({
			facts: [fact("old_post", "what anime should everyone watch?", 120, "missing")],
			queueById: new Map(),
			now: new Date("2026-06-06T00:00:00.000Z"),
			days: 30,
		});

		expect(report.dataQuality.replayedCurrentGateCount).toBe(1);
		expect(report.dataQuality.missingQueueContextCount).toBe(1);
		expect(report.dataQuality.missingGenerationViralScoreCount).toBe(1);
	});
});
