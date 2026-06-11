import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	accountPerformanceStrategies,
	aggregateFactMetric,
	buildPerformanceFirstRecommendations,
	extractWinnerPatterns,
	type AutoposterPerformanceFact,
} from "./performanceFirst.js";
import {
	replaceStrategyRecommendations,
	type StrategyRecommendation,
} from "./strategyRecommendations.js";

type DbClient = ReturnType<typeof getSupabaseAny>;

export interface PerformanceAttributionArtifacts {
	winnerPatterns: ReturnType<typeof extractWinnerPatterns>;
	accountStrategies: ReturnType<typeof accountPerformanceStrategies>;
	strategyRecommendations: StrategyRecommendation[];
}

export interface PerformanceAttributionRefreshResult {
	workspaceId: string;
	days: number;
	factsLoaded: number;
	winnerPatternsBuilt: number;
	winnerPatternsPersisted: boolean;
	strategyRecommendationsBuilt: number;
	strategyRecommendationsPersisted: boolean;
	accountPerformanceStateRowsUpdated: number;
}

export function buildPerformanceAttributionArtifacts(input: {
	workspaceId: string;
	facts: AutoposterPerformanceFact[];
	days?: number | undefined;
	limit?: number | undefined;
	now?: Date | undefined;
}): PerformanceAttributionArtifacts {
	const days = input.days ?? 30;
	const limit = input.limit ?? 25;
	const winnerPatterns = extractWinnerPatterns(input.facts, limit);
	const accountStrategies = accountPerformanceStrategies(input.facts);
	const strategyRecommendations = buildPerformanceFirstRecommendations({
		workspaceId: input.workspaceId,
		groupId: null,
		accountId: null,
		days,
		now: input.now,
		best: {},
		winnerPatterns,
		sourceTypePerformance: aggregateFactMetric(
			input.facts,
			"source_type",
			limit,
			1,
		),
		shapePerformance: aggregateFactMetric(input.facts, "shape_id", limit, 1),
		accountStrategies,
	});

	return {
		winnerPatterns,
		accountStrategies,
		strategyRecommendations,
	};
}

async function persistWinnerPatterns(
	client: DbClient,
	winners: ReturnType<typeof extractWinnerPatterns>,
): Promise<boolean> {
	const rows = winners.filter((winner) => winner.workspace_id);
	if (rows.length === 0) return false;
	const { error } = await client
		.from("autoposter_winner_patterns")
		.upsert(rows, { onConflict: "source_post_id,performance_basis" });
	if (error) throw error;
	return true;
}

async function persistAccountPerformanceState(
	client: DbClient,
	accountStrategies: ReturnType<typeof accountPerformanceStrategies>,
): Promise<number> {
	const now = new Date().toISOString();
	let persisted = 0;
	for (const row of accountStrategies) {
		const { error } = await client
			.from("account_autoposter_state")
			.update({
				avg_views_24h_30d: row.averageViews24h,
				median_views_24h_30d: row.medianViews24h,
				posts_above_100_views_rate: row.postsAbove100ViewsRate,
				revenue_per_post_30d: row.revenuePerPost,
				recommended_posts_per_day: row.recommendedPostsPerDay,
				recommended_strategy_mode: row.recommendedStrategyMode,
				last_performance_recomputed_at: now,
			})
			.eq("account_id", row.accountId);
		if (error) throw error;
		persisted++;
	}
	return persisted;
}

export async function refreshAutoposterPerformanceAttributionFromFacts(input: {
	workspaceId: string;
	days?: number | undefined;
	limit?: number | undefined;
	client?: DbClient | undefined;
	now?: Date | undefined;
}): Promise<PerformanceAttributionRefreshResult> {
	const client = input.client ?? getSupabaseAny();
	const days = input.days ?? 30;
	const limit = input.limit ?? 25;
	const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

	const { data, error } = await client
		.from("autoposter_post_performance_facts")
		.select("*")
		.eq("workspace_id", input.workspaceId)
		.eq("platform", "threads")
		.gte("published_at", cutoff)
		.order("published_at", { ascending: false })
		.limit(1000);
	if (error) throw error;

	const facts = (data || []) as AutoposterPerformanceFact[];
	const artifacts = buildPerformanceAttributionArtifacts({
		workspaceId: input.workspaceId,
		facts,
		days,
		limit,
		now: input.now,
	});

	let winnerPatternsPersisted = false;
	if (artifacts.winnerPatterns.length > 0) {
		winnerPatternsPersisted = await persistWinnerPatterns(
			client,
			artifacts.winnerPatterns,
		);
	}

	let strategyRecommendationsPersisted = false;
	if (artifacts.strategyRecommendations.length > 0) {
		await replaceStrategyRecommendations(
			{ workspaceId: input.workspaceId },
			artifacts.strategyRecommendations,
		);
		strategyRecommendationsPersisted = true;
	}

	const accountPerformanceStateRowsUpdated =
		artifacts.accountStrategies.length > 0
			? await persistAccountPerformanceState(client, artifacts.accountStrategies)
			: 0;

	const result: PerformanceAttributionRefreshResult = {
		workspaceId: input.workspaceId,
		days,
		factsLoaded: facts.length,
		winnerPatternsBuilt: artifacts.winnerPatterns.length,
		winnerPatternsPersisted,
		strategyRecommendationsBuilt: artifacts.strategyRecommendations.length,
		strategyRecommendationsPersisted,
		accountPerformanceStateRowsUpdated,
	};
	logger.info("[autoposter-performance-attribution] Refreshed from facts", {
		...result,
	});
	return result;
}
