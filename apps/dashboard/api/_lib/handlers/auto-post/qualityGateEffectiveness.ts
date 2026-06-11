import { evaluateAIQualityGate } from "./qualityGate.js";
import type { AutoposterPerformanceFact } from "./performanceFirst.js";

export const DEFAULT_GATE_EFFECTIVENESS_DAYS = 120;
export const DEFAULT_GATE_WINNER_VIEWS = 100;
export const DEFAULT_GATE_LOSER_VIEWS = 5;

export interface QualityGateQueueContext {
	id: string;
	source_type?: string | null;
	source_content?: string | null;
	source_competitor_id?: string | null;
	predicted_viral_score?: number | null;
	metadata?: Record<string, unknown> | null;
}

export interface QualityGateDecisionSnapshot {
	decision: "pass" | "needs_review" | "block";
	reason: string;
	flags: string[];
	score: {
		replyTrigger: number | null;
		emotionalWarmth: number | null;
		overall: number | null;
		rejectReason?: string | null;
	};
	lane?: string | null | undefined;
	laneReason?: string | null | undefined;
	baselineDecision?: "pass" | "needs_review" | "block" | undefined;
	baselineReason?: string | undefined;
	source: "stored_generation_gate" | "replayed_current_gate";
	dataQuality: string[];
}

export interface QualityGateEffectivenessPost {
	postId: string;
	content: string | null;
	accountId: string | null;
	accountUsername: string | null;
	groupName: string | null;
	creatorKey: string | null;
	publishedAt: string | null;
	views24h: number;
	contentArchetype: string;
	questionSubtype: string | null;
	shapeId: string | null;
	sourceType: string;
	gate: QualityGateDecisionSnapshot;
	businessClass: "winner" | "loser" | "middle";
	outcome:
		| "winner_preserved"
		| "winner_blocked"
		| "loser_blocked"
		| "loser_allowed"
		| "middle_passed"
		| "middle_blocked";
}

export interface QualityGateEffectivenessReportInput {
	facts: AutoposterPerformanceFact[];
	queueById?: Map<string, QualityGateQueueContext> | undefined;
	now?: Date | undefined;
	days?: number | undefined;
	winnerViews?: number | undefined;
	loserViews?: number | undefined;
	limit?: number | undefined;
}

function num(value: unknown): number | null {
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function str(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function record(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function nestedRecord(
	value: Record<string, unknown> | null | undefined,
	path: string[],
): Record<string, unknown> | null {
	let cursor: unknown = value || {};
	for (const segment of path) {
		const next = record(cursor);
		if (!next) return null;
		cursor = next[segment];
	}
	return record(cursor);
}

function queueIdFromFact(fact: AutoposterPerformanceFact): string | null {
	const notes = record(fact.metric_notes);
	return str(notes?.queueId) || str(notes?.autoPostQueueId);
}

function extractStoredGate(
	metadata: Record<string, unknown> | null | undefined,
): QualityGateDecisionSnapshot | null {
	const gate = nestedRecord(metadata, ["quality_gate"]);
	if (!gate) return null;
	const decision = str(gate.decision);
	const reason = str(gate.reason);
	if (
		decision !== "pass" &&
		decision !== "needs_review" &&
		decision !== "block"
	) {
		return null;
	}
	const score = record(gate.score);
	const flagsValue = Array.isArray(gate.flags) ? gate.flags : [];
	return {
		decision,
		reason: reason || "unknown",
		flags: flagsValue.filter((flag): flag is string => typeof flag === "string"),
		score: {
			replyTrigger: num(score?.replyTrigger),
			emotionalWarmth: num(score?.emotionalWarmth),
			overall: num(score?.overall),
			rejectReason: str(score?.rejectReason),
		},
		lane: str(gate.lane) || str(metadata?.quality_gate_lane) || null,
		laneReason: str(gate.laneReason) || str(metadata?.quality_gate_reason) || null,
		source: "stored_generation_gate",
		dataQuality: [],
	};
}

function replayCurrentGate(
	fact: AutoposterPerformanceFact,
	queue: QualityGateQueueContext | null,
): QualityGateDecisionSnapshot {
	const viralScore = num(queue?.predicted_viral_score);
	const dataQuality = ["replayed_from_current_gate"];
	if (viralScore == null) dataQuality.push("missing_generation_viral_score");
	if (!queue) dataQuality.push("missing_queue_context");
	const baseline = evaluateAIQualityGate({
		content: fact.content || "",
		sourceType: queue?.source_type || fact.source_type || "ai",
		sourceContent: queue?.source_content || null,
		sourceCompetitorId:
			queue?.source_competitor_id || fact.source_competitor_id || null,
		viralScore,
	});
	const result = evaluateAIQualityGate({
		content: fact.content || "",
		sourceType: queue?.source_type || fact.source_type || "ai",
		sourceContent: queue?.source_content || null,
		sourceCompetitorId:
			queue?.source_competitor_id || fact.source_competitor_id || null,
		viralScore,
		performanceEvidence: {
			sourcePatternId: fact.source_pattern_id,
			strategyRecommendationId: fact.strategy_recommendation_id,
			strategyBucket: fact.strategy_bucket,
			patternType:
				fact.strategy_bucket === "proven" ||
				fact.strategy_recommendation_id
					? "winner_clone"
					: null,
			isGenericBait:
				fact.question_subtype === "generic_question_bait" ||
				fact.content_archetype === "generic_question",
		},
	});
	return {
		decision: result.decision,
		reason: result.reason,
		flags: result.flags,
		score: {
			replyTrigger: result.score.replyTrigger,
			emotionalWarmth: result.score.emotionalWarmth,
			overall: result.score.overall,
			rejectReason: result.score.rejectReason,
		},
		lane: result.lane ?? null,
		laneReason: result.laneReason ?? null,
		baselineDecision: baseline.decision,
		baselineReason: baseline.reason,
		source: "replayed_current_gate",
		dataQuality,
	};
}

function gateForFact(
	fact: AutoposterPerformanceFact,
	queueById: Map<string, QualityGateQueueContext> | undefined,
): QualityGateDecisionSnapshot {
	const queueId = queueIdFromFact(fact);
	const queue = queueId ? queueById?.get(queueId) || null : null;
	const stored = extractStoredGate(queue?.metadata);
	return stored || replayCurrentGate(fact, queue);
}

function pct(numerator: number, denominator: number): number {
	if (denominator <= 0) return 0;
	return Math.round((numerator / denominator) * 1000) / 10;
}

function average(values: number[]): number {
	if (values.length === 0) return 0;
	return Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100;
}

function businessClassFor(
	views24h: number,
	winnerViews: number,
	loserViews: number,
): "winner" | "loser" | "middle" {
	if (views24h >= winnerViews) return "winner";
	if (views24h < loserViews) return "loser";
	return "middle";
}

function outcomeFor(
	businessClass: "winner" | "loser" | "middle",
	blocked: boolean,
): QualityGateEffectivenessPost["outcome"] {
	if (businessClass === "winner") {
		return blocked ? "winner_blocked" : "winner_preserved";
	}
	if (businessClass === "loser") {
		return blocked ? "loser_blocked" : "loser_allowed";
	}
	return blocked ? "middle_blocked" : "middle_passed";
}

function groupBy(
	posts: QualityGateEffectivenessPost[],
	keyFor: (post: QualityGateEffectivenessPost) => string,
) {
	const buckets = new Map<string, QualityGateEffectivenessPost[]>();
	for (const post of posts) {
		const key = keyFor(post) || "unknown";
		const rows = buckets.get(key) || [];
		rows.push(post);
		buckets.set(key, rows);
	}
	return [...buckets.entries()]
		.map(([key, rows]) => {
			const winners = rows.filter((row) => row.businessClass === "winner");
			const losers = rows.filter((row) => row.businessClass === "loser");
			const blocked = rows.filter((row) => row.gate.decision !== "pass");
			const winnersBlocked = winners.filter((row) => row.outcome === "winner_blocked");
			const losersBlocked = losers.filter((row) => row.outcome === "loser_blocked");
			return {
				key,
				postCount: rows.length,
				averageViews24h: average(rows.map((row) => row.views24h)),
				acceptanceRate: pct(rows.length - blocked.length, rows.length),
				blockRate: pct(blocked.length, rows.length),
				winnerCount: winners.length,
				loserCount: losers.length,
				winnerPreservationRate: pct(winners.length - winnersBlocked.length, winners.length),
				loserBlockRate: pct(losersBlocked.length, losers.length),
				topReasons: reasonCounts(blocked).slice(0, 5),
			};
		})
		.sort((a, b) => b.postCount - a.postCount || b.averageViews24h - a.averageViews24h);
}

function reasonCounts(posts: QualityGateEffectivenessPost[]) {
	const counts = new Map<string, number>();
	for (const post of posts) {
		const key = post.gate.reason || "unknown";
		counts.set(key, (counts.get(key) || 0) + 1);
	}
	return [...counts.entries()]
		.map(([reason, count]) => ({ reason, count }))
		.sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
}

function board(posts: QualityGateEffectivenessPost[], limit: number) {
	return posts.slice(0, limit).map((post) => ({
		postId: post.postId,
		content: post.content,
		account: post.accountUsername || post.accountId,
		groupName: post.groupName,
		views24h: post.views24h,
		archetype: post.contentArchetype,
		questionSubtype: post.questionSubtype,
		shapeId: post.shapeId,
		sourceType: post.sourceType,
		gateDecision: post.gate.decision,
		gateReason: post.gate.reason,
		qualityGateLane: post.gate.lane || "standard",
		qualityGateLaneReason: post.gate.laneReason || null,
		baselineGateDecision: post.gate.baselineDecision || null,
		baselineGateReason: post.gate.baselineReason || null,
		gateSource: post.gate.source,
		replyTrigger: post.gate.score.replyTrigger,
		overallScore: post.gate.score.overall,
		publishedAt: post.publishedAt,
	}));
}

export function buildQualityGateEffectivenessReport(
	input: QualityGateEffectivenessReportInput,
) {
	const now = input.now || new Date();
	const days = Math.max(
		1,
		Math.min(365, Math.floor(input.days || DEFAULT_GATE_EFFECTIVENESS_DAYS)),
	);
	const winnerViews = Math.max(1, input.winnerViews || DEFAULT_GATE_WINNER_VIEWS);
	const loserViews = Math.max(0, input.loserViews ?? DEFAULT_GATE_LOSER_VIEWS);
	const limit = Math.max(3, Math.min(50, input.limit || 20));
	const start = new Date(now.getTime() - days * 86_400_000);
	const facts = input.facts.filter((fact) => {
		if (!fact.published_at || fact.platform !== "threads") return false;
		const publishedAt = new Date(fact.published_at).getTime();
		return Number.isFinite(publishedAt) && publishedAt >= start.getTime() && publishedAt <= now.getTime();
	});
	const posts: QualityGateEffectivenessPost[] = facts.map((fact) => {
		const gate = gateForFact(fact, input.queueById);
		const businessClass = businessClassFor(fact.views_24h, winnerViews, loserViews);
		const blocked = gate.decision !== "pass";
		return {
			postId: fact.post_id,
			content: fact.content,
			accountId: fact.account_id,
			accountUsername: fact.account_username,
			groupName: fact.group_name,
			creatorKey: fact.creator_key,
			publishedAt: fact.published_at,
			views24h: fact.views_24h,
			contentArchetype: fact.content_archetype,
			questionSubtype: fact.question_subtype || null,
			shapeId: fact.shape_id,
			sourceType: fact.source_type,
			gate,
			businessClass,
			outcome: outcomeFor(businessClass, blocked),
		};
	});
	const winners = posts.filter((post) => post.businessClass === "winner");
	const losers = posts.filter((post) => post.businessClass === "loser");
	const blocked = posts.filter((post) => post.gate.decision !== "pass");
	const passed = posts.filter((post) => post.gate.decision === "pass");
	const winnersBlocked = posts.filter((post) => post.outcome === "winner_blocked");
	const losersAllowed = posts.filter((post) => post.outcome === "loser_allowed");
	const losersBlocked = posts.filter((post) => post.outcome === "loser_blocked");
	const winnersPreserved = posts.filter((post) => post.outcome === "winner_preserved");
	const performanceLanePosts = posts.filter(
		(post) => post.gate.lane === "performance_backed_clone",
	);
	const performanceLaneWinners = performanceLanePosts.filter(
		(post) => post.businessClass === "winner",
	);
	const performanceLaneLosers = performanceLanePosts.filter(
		(post) => post.businessClass === "loser",
	);
	const storedCount = posts.filter((post) => post.gate.source === "stored_generation_gate").length;
	const replayedCount = posts.length - storedCount;
	const passedWinnerCount = passed.filter((post) => post.businessClass === "winner").length;
	const passedLoserCount = passed.filter((post) => post.businessClass === "loser").length;
	return {
		window: {
			start: start.toISOString(),
			end: now.toISOString(),
			days,
			postCount: posts.length,
			winnerViews,
			loserViews,
		},
		summary: {
			acceptanceRate: pct(passed.length, posts.length),
			blockRate: pct(blocked.length, posts.length),
			winnerCount: winners.length,
			loserCount: losers.length,
			winnerPreservationRate: pct(winnersPreserved.length, winners.length),
			winnerBlockedRate: pct(winnersBlocked.length, winners.length),
			loserBlockRate: pct(losersBlocked.length, losers.length),
			loserAllowedRate: pct(losersAllowed.length, losers.length),
			passedPostPrecisionForWinners: pct(passedWinnerCount, passed.length),
			passedPostLoserShare: pct(passedLoserCount, passed.length),
			averageViewsPassed: average(passed.map((post) => post.views24h)),
			averageViewsBlocked: average(blocked.map((post) => post.views24h)),
			performanceBackedLaneAcceptedCount: performanceLanePosts.length,
			performanceBackedLaneWinnerCount: performanceLaneWinners.length,
			performanceBackedLaneLoserCount: performanceLaneLosers.length,
		},
		confusion: {
			truePositiveWinnersPreserved: winnersPreserved.length,
			falsePositiveWinnersBlocked: winnersBlocked.length,
			trueNegativeLosersBlocked: losersBlocked.length,
			falseNegativeLosersAllowed: losersAllowed.length,
			middlePassed: posts.filter((post) => post.outcome === "middle_passed").length,
			middleBlocked: posts.filter((post) => post.outcome === "middle_blocked").length,
		},
		breakdowns: {
			reasons: reasonCounts(blocked),
			creator: groupBy(posts, (post) => post.creatorKey || post.groupName || "unknown"),
			account: groupBy(posts, (post) => post.accountUsername || post.accountId || "unknown"),
			archetype: groupBy(posts, (post) => post.contentArchetype || "unknown"),
			questionSubtype: groupBy(posts, (post) => post.questionSubtype || "not_question_or_unknown"),
			sourceType: groupBy(posts, (post) => post.sourceType || "unknown"),
			acceptedByLane: groupBy(
				passed,
				(post) => post.gate.lane || "standard",
			),
		},
		boards: {
			historicalWinnersBlocked: board(
				winnersBlocked.sort((a, b) => b.views24h - a.views24h),
				limit,
			),
			historicalLosersAllowed: board(
				losersAllowed.sort((a, b) => a.views24h - b.views24h),
				limit,
			),
			topPassedPosts: board(
				passed.sort((a, b) => b.views24h - a.views24h),
				limit,
			),
			worstPassedPosts: board(
				passed.sort((a, b) => a.views24h - b.views24h),
				limit,
			),
		},
		answers: {
			isGateProtectingPerformance:
				losers.length >= 20 && winners.length >= 5
					? pct(losersBlocked.length, losers.length) >= pct(winnersBlocked.length, winners.length)
					: null,
			shouldChangeThresholdsNow:
				winners.length >= 5 && losers.length >= 20
					? pct(winnersBlocked.length, winners.length) > pct(losersBlocked.length, losers.length)
					: null,
			reason:
				winners.length >= 5 && losers.length >= 20
					? `Gate blocked ${pct(winnersBlocked.length, winners.length)}% of winners and ${pct(losersBlocked.length, losers.length)}% of losers.`
					: "Insufficient winner/loser volume for a confident threshold decision.",
		},
		dataQuality: {
			storedGenerationGateCount: storedCount,
			replayedCurrentGateCount: replayedCount,
			missingQueueContextCount: posts.filter((post) =>
				post.gate.dataQuality.includes("missing_queue_context"),
			).length,
			missingGenerationViralScoreCount: posts.filter((post) =>
				post.gate.dataQuality.includes("missing_generation_viral_score"),
			).length,
			note:
				replayedCount > 0
					? "Rows without stored generation-time quality_gate metadata are replayed with the current gate; viral score may be missing, so treat those rows as directional."
					: "All rows used stored generation-time quality gate metadata.",
		},
	};
}
