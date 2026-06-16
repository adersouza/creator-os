import { classifyCompetitorPattern } from "../competitors/metricQuality.js";
import {
	classifyQuestionSubtype,
	classifyContentArchetype,
	detectIdentityShapeId,
} from "./contentArchetypes.js";
import { detectTaxonomyLabelLeak } from "./contentFilter.js";
import type {
	RankedPattern,
	StrategyRecommendation,
	StrategyInput,
} from "./strategyRecommendations.js";

export const VIEW_TARGET_24H = 100;
export const MIN_ACCOUNT_STRATEGY_POSTS = 10;
export const MIN_PATTERN_STRATEGY_POSTS = 5;
export const MIN_MICROCOPY_STRATEGY_POSTS = 20;
export const MIN_VALIDATION_WINDOW_POSTS = 10;
export const DEFAULT_PERFORMANCE_PATCH_APPLIED_AT = "2026-06-06T00:00:00-04:00";

export interface AutoposterPerformancePostInput {
	id: string;
	user_id?: string | null;
	workspace_id?: string | null;
	account_id: string | null;
	cross_post_group_id: string | null;
	content: string | null;
	platform?: string | null;
	status?: string | null;
	published_at: string | null;
	views_count: number | null;
	replies_count: number | null;
	likes_count: number | null;
	reposts_count?: number | null;
	quotes_count?: number | null;
	media_type: string | null;
	media_urls?: string[] | null;
	hook_type: string | null;
	topic_label: string | null;
	format_type: string | null;
	emotional_frame: string | null;
	reply_mechanism: string | null;
	content_length_bucket: string | null;
	media_style: string | null;
	posting_hour: number | null;
	prompt_version: string | null;
	template_id: string | null;
	model_provider: string | null;
	source_pattern_id: string | null;
	strategy_recommendation_id: string | null;
	strategy_bucket: string | null;
	auto_post_queue_id?: string | null;
	dna_fit_score?: number | null;
	creator_fit_score?: number | null;
	account_flavor_score?: number | null;
	genericness_score?: number | null;
	metadata?: Record<string, unknown> | null;
}

export interface AutoposterQueueProvenanceInput {
	id: string;
	source_type?: string | null;
	source_id?: string | null;
	source_competitor_id?: string | null;
	source_competitor_username?: string | null;
	strategy_recommendation_id?: string | null;
	strategy_bucket?: string | null;
	source_pattern_id?: string | null;
	content_archetype?: string | null;
	question_subtype?: string | null;
	media_style?: string | null;
	metadata?: Record<string, unknown> | null;
}

export interface AutoposterPerformanceFact {
	post_id: string;
	user_id: string | null;
	workspace_id: string | null;
	group_id: string | null;
	group_name: string | null;
	account_id: string | null;
	account_username: string | null;
	creator_key: string | null;
	content: string | null;
	published_at: string | null;
	posting_hour: number | null;
	platform: string;
	views_1h: number;
	views_24h: number;
	current_views: number;
	replies_1h: number;
	replies_24h: number;
	current_replies: number;
	likes_24h: number;
	current_likes: number;
	reposts_count: number;
	quotes_count: number;
	media_type: string | null;
	media_style: string | null;
	has_media: boolean;
	source_type: string;
	source_id: string | null;
	source_competitor_id: string | null;
	source_competitor_username: string | null;
	direct_copy_reason: string | null;
	microcopy_confidence: number | null;
	content_archetype: string;
	question_subtype?: string | null;
	shape_id: string | null;
	hook_type: string;
	topic_label: string;
	format_type: string;
	emotional_frame: string;
	reply_mechanism: string;
	content_length_bucket: string;
	strategy_recommendation_id: string | null;
	strategy_bucket: string;
	clone_family: string | null;
	prompt_version: string | null;
	template_id: string | null;
	model_provider: string | null;
	source_pattern_id: string | null;
	quality_gate_lane: string | null;
	quality_gate_reason: string | null;
	dna_fit_score: number | null;
	creator_fit_score: number | null;
	account_flavor_score: number | null;
	genericness_score: number | null;
	smart_link_clicks: number;
	smart_link_conversions: number;
	smart_link_revenue: number;
	profile_clicks_proxy: number | null;
	profile_clicks_proxy_scope: string | null;
	metrics_quality: PerformanceMetricQuality;
	metric_notes: Record<string, unknown>;
}

export type PerformanceMetricQuality =
	| "complete"
	| "views_only"
	| "conversion_unavailable"
	| "profile_click_proxy"
	| "insufficient_metrics";

export interface MetricHistoryInput {
	post_id: string;
	hours_since_publish: number | null;
	views_count: number | null;
	replies_count: number | null;
	likes_count?: number | null;
}

export interface SmartLinkAttributionInput {
	post_id: string;
	clicks: number;
	conversions: number;
	revenue: number;
}

export interface AccountLookupInput {
	username?: string | null;
	workspace_id?: string | null;
}

export interface GroupLookupInput {
	name?: string | null;
}

export interface BuildPerformanceFactsInput {
	posts: AutoposterPerformancePostInput[];
	historyRows?: MetricHistoryInput[] | undefined;
	queueRows?: AutoposterQueueProvenanceInput[] | undefined;
	smartLinkAttribution?: SmartLinkAttributionInput[] | undefined;
	accountLookup?: Map<string, AccountLookupInput> | undefined;
	groupLookup?: Map<string, GroupLookupInput> | undefined;
	now?: Date | undefined;
}

function num(value: unknown): number {
	const parsed = Number(value ?? 0);
	return Number.isFinite(parsed) ? parsed : 0;
}

function str(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function metadataObject(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function nestedMetadataString(
	metadata: Record<string, unknown> | null | undefined,
	path: string[],
): string | null {
	let cursor: unknown = metadata || {};
	for (const segment of path) {
		if (!cursor || typeof cursor !== "object" || Array.isArray(cursor))
			return null;
		cursor = (cursor as Record<string, unknown>)[segment];
	}
	return str(cursor);
}

function nestedMetadataNumber(
	metadata: Record<string, unknown> | null | undefined,
	path: string[],
): number | null {
	let cursor: unknown = metadata || {};
	for (const segment of path) {
		if (!cursor || typeof cursor !== "object" || Array.isArray(cursor))
			return null;
		cursor = (cursor as Record<string, unknown>)[segment];
	}
	const parsed = Number(cursor);
	return Number.isFinite(parsed) ? parsed : null;
}

function deriveQueueId(post: AutoposterPerformancePostInput): string | null {
	return (
		str(post.auto_post_queue_id) ||
		str(post.metadata?.autoPostQueueId) ||
		str(post.metadata?.auto_post_queue_id)
	);
}

function closestHistory(
	rows: MetricHistoryInput[],
	postId: string,
	predicate: (hour: number) => boolean,
): MetricHistoryInput | null {
	let best: MetricHistoryInput | null = null;
	for (const row of rows) {
		if (row.post_id !== postId) continue;
		const hour = num(row.hours_since_publish);
		if (!predicate(hour)) continue;
		if (!best) {
			best = row;
			continue;
		}
		const bestHour = num(best.hours_since_publish);
		if (Math.abs(hour - 24) < Math.abs(bestHour - 24)) best = row;
	}
	return best;
}

function median(values: number[]): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	const middle = sorted[mid] ?? 0;
	const previous = sorted[mid - 1] ?? middle;
	return sorted.length % 2
		? middle
		: Math.round(((previous + middle) / 2) * 100) / 100;
}

function average(values: number[]): number {
	if (values.length === 0) return 0;
	return (
		Math.round(
			(values.reduce((sum, value) => sum + value, 0) / values.length) * 100,
		) / 100
	);
}

function percentile(values: number[], pct: number): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const idx = Math.max(
		0,
		Math.min(sorted.length - 1, Math.ceil(sorted.length * pct) - 1),
	);
	return sorted[idx] ?? 0;
}

export function buildAutoposterPerformanceFacts(
	input: BuildPerformanceFactsInput,
): AutoposterPerformanceFact[] {
	const queueById = new Map(
		(input.queueRows || []).map((row) => [row.id, row]),
	);
	const smartByPost = new Map(
		(input.smartLinkAttribution || []).map((row) => [row.post_id, row]),
	);
	const historyRows = input.historyRows || [];

	return input.posts.map((post) => {
		const queue = deriveQueueId(post)
			? queueById.get(deriveQueueId(post) as string)
			: null;
		const queueMetadata = metadataObject(queue?.metadata);
		const postMetadata = metadataObject(post.metadata);
		const fallback = classifyCompetitorPattern({
			content: post.content,
			topicTag: post.topic_label,
			mediaType:
				post.media_type ||
				(post.media_urls && post.media_urls.length > 0 ? "IMAGE" : "TEXT"),
			publishedAt: post.published_at,
		});
		const archetypeDecision = classifyContentArchetype(post.content);
		const contentArchetype =
			nestedMetadataString(postMetadata, ["content_archetype", "value"]) ||
			str(postMetadata.content_archetype) ||
			str(postMetadata.pattern_type) ||
			archetypeDecision.archetype;
		const questionSubtype =
			nestedMetadataString(postMetadata, [
				"content_archetype",
				"question_subtype",
			]) ||
			str(postMetadata.question_subtype) ||
			archetypeDecision.questionSubtype ||
			classifyQuestionSubtype(post.content || "");
		const shapeId =
			str(postMetadata.identity_shape_id) ||
			str(postMetadata.shape_id) ||
			detectIdentityShapeId(post.content);
		const at1h = closestHistory(
			historyRows,
			post.id,
			(hour) => hour >= 0 && hour <= 2,
		);
		const at24h = closestHistory(
			historyRows,
			post.id,
			(hour) => hour >= 20 && hour <= 28,
		);
		const smart = smartByPost.get(post.id);
		const account = post.account_id
			? input.accountLookup?.get(post.account_id)
			: null;
		const group = post.cross_post_group_id
			? input.groupLookup?.get(post.cross_post_group_id)
			: null;
		const sourceType =
			str(queue?.source_type) ||
			str(postMetadata.source_type) ||
			str(queueMetadata.source_type) ||
			"unknown";
		const cloneFamily =
			nestedMetadataString(postMetadata, ["winner_clone", "clone_family"]) ||
			str(postMetadata.clone_family) ||
			nestedMetadataString(queueMetadata, ["winner_clone", "clone_family"]) ||
			str(queueMetadata.clone_family);
		const qualityGateLane =
			str(postMetadata.quality_gate_lane) ||
			nestedMetadataString(postMetadata, ["quality_gate", "lane"]) ||
			str(queueMetadata.quality_gate_lane) ||
			nestedMetadataString(queueMetadata, ["quality_gate", "lane"]);
		const qualityGateReason =
			str(postMetadata.quality_gate_reason) ||
			nestedMetadataString(postMetadata, ["quality_gate", "laneReason"]) ||
			nestedMetadataString(postMetadata, ["quality_gate", "reason"]) ||
			str(queueMetadata.quality_gate_reason) ||
			nestedMetadataString(queueMetadata, ["quality_gate", "laneReason"]) ||
			nestedMetadataString(queueMetadata, ["quality_gate", "reason"]);
		const hasConversionAttribution = !!smart;
		const metricsQuality: PerformanceMetricQuality = hasConversionAttribution
			? "complete"
			: post.views_count == null && !at24h
				? "insufficient_metrics"
				: "conversion_unavailable";
		const workspaceId =
			str(post.workspace_id) || str(account?.workspace_id) || null;
		return {
			post_id: post.id,
			user_id: post.user_id ?? null,
			workspace_id: workspaceId,
			group_id: post.cross_post_group_id,
			group_name: group?.name ?? null,
			account_id: post.account_id,
			account_username: account?.username ?? null,
			creator_key: group?.name ?? post.cross_post_group_id ?? null,
			content: post.content,
			published_at: post.published_at,
			posting_hour: post.posting_hour ?? fallback.posting_hour,
			platform: post.platform || "threads",
			views_1h: num(at1h?.views_count ?? post.views_count),
			views_24h: num(at24h?.views_count ?? post.views_count),
			current_views: num(post.views_count),
			replies_1h: num(at1h?.replies_count ?? post.replies_count),
			replies_24h: num(at24h?.replies_count ?? post.replies_count),
			current_replies: num(post.replies_count),
			likes_24h: num(at24h?.likes_count ?? post.likes_count),
			current_likes: num(post.likes_count),
			reposts_count: num(post.reposts_count),
			quotes_count: num(post.quotes_count),
			media_type: post.media_type,
			media_style:
				post.media_style || queue?.media_style || fallback.media_style,
			has_media:
				Boolean(
					post.media_type &&
						!["text", "none"].includes(post.media_type.toLowerCase()),
				) || Boolean(post.media_urls?.length),
			source_type: sourceType,
			source_id: str(queue?.source_id) || str(postMetadata.source_id),
			source_competitor_id:
				str(queue?.source_competitor_id) ||
				str(postMetadata.source_competitor_id),
			source_competitor_username:
				str(queue?.source_competitor_username) ||
				str(postMetadata.source_competitor_username),
			direct_copy_reason:
				nestedMetadataString(postMetadata, ["direct_copy_reason"]) ||
				nestedMetadataString(postMetadata, [
					"microcopy",
					"direct_copy_reason",
				]) ||
				nestedMetadataString(queueMetadata, ["direct_copy_reason"]) ||
				nestedMetadataString(queueMetadata, [
					"microcopy",
					"direct_copy_reason",
				]),
			microcopy_confidence:
				nestedMetadataNumber(postMetadata, ["microcopy_confidence"]) ||
				nestedMetadataNumber(postMetadata, ["microcopy", "confidence"]) ||
				nestedMetadataNumber(queueMetadata, ["microcopy_confidence"]) ||
				nestedMetadataNumber(queueMetadata, ["microcopy", "confidence"]),
			content_archetype: str(queue?.content_archetype) || contentArchetype,
			question_subtype: questionSubtype,
			shape_id: shapeId,
			hook_type: post.hook_type || fallback.hook_type,
			topic_label: post.topic_label || fallback.topic_label,
			format_type: post.format_type || fallback.format_type,
			emotional_frame: post.emotional_frame || fallback.emotional_frame,
			reply_mechanism: post.reply_mechanism || fallback.reply_mechanism,
			content_length_bucket:
				post.content_length_bucket || fallback.content_length_bucket,
			strategy_recommendation_id:
				post.strategy_recommendation_id ||
				str(queue?.strategy_recommendation_id),
			strategy_bucket:
				post.strategy_bucket && post.strategy_bucket !== "none"
					? post.strategy_bucket
					: queue?.strategy_bucket || "none",
			clone_family: cloneFamily,
			prompt_version: post.prompt_version,
			template_id: post.template_id,
			model_provider: post.model_provider,
			source_pattern_id:
				post.source_pattern_id || str(queue?.source_pattern_id),
			quality_gate_lane: qualityGateLane,
			quality_gate_reason: qualityGateReason,
			dna_fit_score:
				post.dna_fit_score ??
				nestedMetadataNumber(postMetadata, ["dna", "dna_fit_score"]),
			creator_fit_score:
				post.creator_fit_score ??
				nestedMetadataNumber(postMetadata, ["dna", "creator_fit_score"]),
			account_flavor_score:
				post.account_flavor_score ??
				nestedMetadataNumber(postMetadata, ["dna", "account_flavor_score"]),
			genericness_score:
				post.genericness_score ??
				nestedMetadataNumber(postMetadata, ["dna", "genericness_score"]),
			smart_link_clicks: smart?.clicks ?? 0,
			smart_link_conversions: smart?.conversions ?? 0,
			smart_link_revenue: smart?.revenue ?? 0,
			profile_clicks_proxy: null,
			profile_clicks_proxy_scope: null,
			metrics_quality: metricsQuality,
			metric_notes: {
				conversionAttribution: hasConversionAttribution
					? "post_smart_link"
					: "unavailable",
				queueId: deriveQueueId(post),
			},
		};
	});
}

export async function persistAutoposterPerformanceFacts(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert returns a thenable Postgrest builder, not a plain Promise.
	dbClient: any,
	facts: AutoposterPerformanceFact[],
) {
	const rows = facts
		.filter((fact) => fact.user_id)
		.map((fact) => ({
			...fact,
			computed_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		}));
	if (rows.length === 0) return false;
	const { error } = await dbClient
		.from("autoposter_post_performance_facts")
		.upsert(rows, { onConflict: "post_id" });
	return !error;
}

export function summarizePerformanceFacts(facts: AutoposterPerformanceFact[]) {
	const views = facts.map((fact) => fact.views_24h);
	return {
		postCount: facts.length,
		averageViewsPerPost: average(views),
		medianViewsPerPost: median(views),
		postsAbove100ViewsRate:
			Math.round(
				(facts.filter((fact) => fact.views_24h >= VIEW_TARGET_24H).length /
					Math.max(1, facts.length)) *
					1000,
			) / 10,
		totalLinkClicks: facts.reduce(
			(sum, fact) => sum + fact.smart_link_clicks,
			0,
		),
		totalConversions: facts.reduce(
			(sum, fact) => sum + fact.smart_link_conversions,
			0,
		),
		totalRevenue:
			Math.round(
				facts.reduce((sum, fact) => sum + fact.smart_link_revenue, 0) * 100,
			) / 100,
		metricsQuality: distribution(
			facts.map((fact) => fact.metrics_quality),
			10,
		),
	};
}

export function distribution(values: string[], limit: number) {
	const counts = new Map<string, number>();
	for (const value of values) {
		const key = value?.trim() ? value.trim() : "unknown";
		counts.set(key, (counts.get(key) || 0) + 1);
	}
	const total = values.length || 1;
	return [...counts.entries()]
		.sort((a, b) => b[1] - a[1])
		.slice(0, limit)
		.map(([key, count]) => ({
			key,
			count,
			pct: Math.round((count / total) * 1000) / 10,
		}));
}

export function aggregateFactMetric(
	facts: AutoposterPerformanceFact[],
	field: keyof Pick<
		AutoposterPerformanceFact,
		| "content_archetype"
		| "question_subtype"
		| "shape_id"
		| "source_type"
		| "media_style"
		| "media_type"
		| "topic_label"
		| "hook_type"
		| "reply_mechanism"
		| "strategy_bucket"
	>,
	limit: number,
	minCount = 1,
) {
	const buckets = new Map<
		string,
		{
			views: number[];
			replies: number[];
			clicks: number;
			revenue: number;
			examples: string[];
		}
	>();
	for (const fact of facts) {
		const key = String(fact[field] || "unknown");
		const bucket = buckets.get(key) || {
			views: [],
			replies: [],
			clicks: 0,
			revenue: 0,
			examples: [],
		};
		bucket.views.push(fact.views_24h);
		bucket.replies.push(fact.replies_1h);
		bucket.clicks += fact.smart_link_clicks;
		bucket.revenue += fact.smart_link_revenue;
		if (bucket.examples.length < 3 && fact.content) {
			bucket.examples.push(fact.content.slice(0, 160));
		}
		buckets.set(key, bucket);
	}
	return [...buckets.entries()]
		.map(([key, bucket]) => ({
			key,
			count: bucket.views.length,
			avg: average(bucket.views),
			median: median(bucket.views),
			above100Rate:
				Math.round(
					(bucket.views.filter((value) => value >= VIEW_TARGET_24H).length /
						Math.max(1, bucket.views.length)) *
						1000,
				) / 10,
			avg1hReplies: average(bucket.replies),
			linkClicks: bucket.clicks,
			revenue: Math.round(bucket.revenue * 100) / 100,
			examples: bucket.examples,
		}))
		.filter((row) => row.count >= minCount)
		.sort((a, b) => b.avg - a.avg)
		.slice(0, limit);
}

export function accountPerformanceStrategies(
	facts: AutoposterPerformanceFact[],
) {
	const byAccount = new Map<string, AutoposterPerformanceFact[]>();
	for (const fact of facts) {
		if (!fact.account_id) continue;
		const rows = byAccount.get(fact.account_id) || [];
		rows.push(fact);
		byAccount.set(fact.account_id, rows);
	}
	return [...byAccount.entries()]
		.map(([accountId, rows]) => {
			const views = rows.map((row) => row.views_24h);
			const avgViews = average(views);
			const above100Rate =
				Math.round(
					(rows.filter((row) => row.views_24h >= VIEW_TARGET_24H).length /
						Math.max(1, rows.length)) *
						1000,
				) / 10;
			const revenuePerPost =
				Math.round(
					(rows.reduce((sum, row) => sum + row.smart_link_revenue, 0) /
						Math.max(1, rows.length)) *
						100,
				) / 100;
			const recommendedStrategyMode =
				rows.length >= MIN_ACCOUNT_STRATEGY_POSTS * 2 &&
				avgViews < 5 &&
				above100Rate === 0
					? "suppress"
					: rows.length >= MIN_ACCOUNT_STRATEGY_POSTS && avgViews < 20
						? "reduce"
						: avgViews >= VIEW_TARGET_24H || above100Rate >= 20
							? "scale"
							: "clone_winners";
			const recommendedPostsPerDay =
				recommendedStrategyMode === "scale"
					? 3
					: recommendedStrategyMode === "clone_winners"
						? 2
						: recommendedStrategyMode === "reduce"
							? 1
							: 0;
			return {
				accountId,
				accountUsername: rows[0]?.account_username || null,
				groupId: rows[0]?.group_id || null,
				groupName: rows[0]?.group_name || null,
				postCount: rows.length,
				averageViews24h: avgViews,
				medianViews24h: median(views),
				postsAbove100ViewsRate: above100Rate,
				revenuePerPost,
				recommendedPostsPerDay,
				recommendedStrategyMode,
			};
		})
		.sort((a, b) => b.averageViews24h - a.averageViews24h);
}

export function aggregateCloneVsNonClonePerformance(
	facts: AutoposterPerformanceFact[],
) {
	const buckets = new Map<
		string,
		{
			views: number[];
			replies: number[];
			clicks: number;
			revenue: number;
			examples: string[];
		}
	>();
	for (const fact of facts) {
		const key =
			fact.strategy_bucket === "proven" || fact.strategy_recommendation_id
				? "winner_clone_or_strategy_backed"
				: "non_clone";
		const bucket = buckets.get(key) || {
			views: [],
			replies: [],
			clicks: 0,
			revenue: 0,
			examples: [],
		};
		bucket.views.push(fact.views_24h);
		bucket.replies.push(fact.replies_1h);
		bucket.clicks += fact.smart_link_clicks;
		bucket.revenue += fact.smart_link_revenue;
		if (bucket.examples.length < 3 && fact.content) {
			bucket.examples.push(fact.content.slice(0, 160));
		}
		buckets.set(key, bucket);
	}
	return [...buckets.entries()].map(([key, bucket]) => ({
		key,
		count: bucket.views.length,
		avg: average(bucket.views),
		median: median(bucket.views),
		above100Rate:
			Math.round(
				(bucket.views.filter((value) => value >= VIEW_TARGET_24H).length /
					Math.max(1, bucket.views.length)) *
					1000,
			) / 10,
		avg1hReplies: average(bucket.replies),
		linkClicks: bucket.clicks,
		revenue: Math.round(bucket.revenue * 100) / 100,
		examples: bucket.examples,
	}));
}

export function aggregateMediaPerformanceByAccount(
	facts: AutoposterPerformanceFact[],
	limit = 50,
) {
	const byKey = new Map<string, AutoposterPerformanceFact[]>();
	for (const fact of facts) {
		if (!fact.account_id) continue;
		const key = `${fact.account_id}:${fact.has_media ? "media" : "text"}`;
		const rows = byKey.get(key) || [];
		rows.push(fact);
		byKey.set(key, rows);
	}
	return [...byKey.entries()]
		.map(([key, rows]) => {
			const [accountId, mediaBucket] = key.split(":");
			const views = rows.map((row) => row.views_24h);
			return {
				accountId,
				accountUsername: rows[0]?.account_username || null,
				groupName: rows[0]?.group_name || null,
				mediaBucket,
				count: rows.length,
				avg: average(views),
				median: median(views),
				above100Rate:
					Math.round(
						(rows.filter((row) => row.views_24h >= VIEW_TARGET_24H).length /
							Math.max(1, rows.length)) *
							1000,
					) / 10,
			};
		})
		.sort((a, b) => b.avg - a.avg)
		.slice(0, limit);
}

export function aggregateHourPerformanceByScope(
	facts: AutoposterPerformanceFact[],
	scope: "account" | "creator",
	limit = 80,
) {
	const byKey = new Map<string, AutoposterPerformanceFact[]>();
	for (const fact of facts) {
		const owner =
			scope === "account"
				? fact.account_id
				: fact.creator_key || fact.group_name;
		if (!owner || fact.posting_hour == null) continue;
		const key = `${owner}:${fact.posting_hour}`;
		const rows = byKey.get(key) || [];
		rows.push(fact);
		byKey.set(key, rows);
	}
	return [...byKey.entries()]
		.map(([key, rows]) => {
			const lastColon = key.lastIndexOf(":");
			const owner = key.slice(0, lastColon);
			const hour = Number(key.slice(lastColon + 1));
			const views = rows.map((row) => row.views_24h);
			return {
				scope,
				owner,
				hour,
				count: rows.length,
				avg: average(views),
				median: median(views),
				above100Rate:
					Math.round(
						(rows.filter((row) => row.views_24h >= VIEW_TARGET_24H).length /
							Math.max(1, rows.length)) *
							1000,
					) / 10,
			};
		})
		.sort((a, b) => b.avg - a.avg)
		.slice(0, limit);
}

export function topAndBottomPosts(
	facts: AutoposterPerformanceFact[],
	limit = 20,
) {
	const sorted = [...facts].sort((a, b) => b.views_24h - a.views_24h);
	const shape = (fact: AutoposterPerformanceFact) => ({
		postId: fact.post_id,
		content: fact.content,
		accountId: fact.account_id,
		accountUsername: fact.account_username,
		groupId: fact.group_id,
		groupName: fact.group_name,
		publishedAt: fact.published_at,
		postingHour: fact.posting_hour,
		views24h: fact.views_24h,
		replies1h: fact.replies_1h,
		currentLikes: fact.current_likes,
		mediaType: fact.media_type,
		sourceType: fact.source_type,
		contentArchetype: fact.content_archetype,
		questionSubtype: fact.question_subtype,
		shapeId: fact.shape_id,
		topicLabel: fact.topic_label,
		emotionalFrame: fact.emotional_frame,
		replyMechanism: fact.reply_mechanism,
		strategyBucket: fact.strategy_bucket,
		creatorFitScore: fact.creator_fit_score,
		linkClicks: fact.smart_link_clicks,
		revenue: fact.smart_link_revenue,
	});
	return {
		top: sorted.slice(0, limit).map(shape),
		bottom: sorted.slice(-limit).reverse().map(shape),
	};
}

export function scoreCorrelation(
	facts: AutoposterPerformanceFact[],
	scoreField: "creator_fit_score" | "dna_fit_score" | "account_flavor_score",
	minSamples = 30,
) {
	const rows = facts
		.map((fact) => ({
			score: fact[scoreField],
			views: fact.views_24h,
		}))
		.filter(
			(row): row is { score: number; views: number } => row.score != null,
		);
	if (rows.length < minSamples) {
		return {
			status: "insufficient_data" as const,
			sampleCount: rows.length,
			minSamples,
			correlation: null,
		};
	}
	const avgScore = average(rows.map((row) => row.score));
	const avgViews = average(rows.map((row) => row.views));
	let numerator = 0;
	let scoreDenom = 0;
	let viewsDenom = 0;
	for (const row of rows) {
		const scoreDelta = row.score - avgScore;
		const viewsDelta = row.views - avgViews;
		numerator += scoreDelta * viewsDelta;
		scoreDenom += scoreDelta ** 2;
		viewsDenom += viewsDelta ** 2;
	}
	const correlation =
		scoreDenom === 0 || viewsDenom === 0
			? 0
			: numerator / Math.sqrt(scoreDenom * viewsDenom);
	return {
		status: "ready" as const,
		sampleCount: rows.length,
		minSamples,
		correlation: Math.round(correlation * 1000) / 1000,
	};
}

export function extractWinnerPatterns(
	facts: AutoposterPerformanceFact[],
	limit = 25,
) {
	const accountThresholds = new Map<string, number>();
	const byAccount = new Map<string, number[]>();
	for (const fact of facts) {
		if (!fact.account_id) continue;
		const views = byAccount.get(fact.account_id) || [];
		views.push(fact.views_24h);
		byAccount.set(fact.account_id, views);
	}
	for (const [accountId, views] of byAccount.entries()) {
		if (views.length >= MIN_ACCOUNT_STRATEGY_POSTS) {
			accountThresholds.set(accountId, percentile(views, 0.9));
		}
	}
	return facts
		.map((fact) => {
			const accountThreshold = fact.account_id
				? accountThresholds.get(fact.account_id)
				: undefined;
			const performanceBasis =
				fact.smart_link_revenue > 0 || fact.smart_link_clicks >= 5
					? "revenue_or_clicks"
					: fact.views_24h >= VIEW_TARGET_24H
						? "views_above_100"
						: accountThreshold != null && fact.views_24h >= accountThreshold
							? "account_top_decile"
							: fact.views_1h >= 50 || fact.replies_1h >= 3
								? "early_velocity"
								: null;
			return { fact, performanceBasis };
		})
		.filter(
			(
				row,
			): row is {
				fact: AutoposterPerformanceFact;
				performanceBasis:
					| "views_above_100"
					| "account_top_decile"
					| "revenue_or_clicks"
					| "early_velocity";
			} => !!row.performanceBasis && !!row.fact.content,
		)
		.sort((a, b) => b.fact.views_24h - a.fact.views_24h)
		.slice(0, limit)
		.map(({ fact, performanceBasis }) => ({
			workspace_id: fact.workspace_id,
			group_id: fact.group_id,
			account_id: fact.account_id,
			creator_key: fact.creator_key,
			source_post_id: fact.post_id,
			source_text: fact.content || "",
			content_archetype: fact.content_archetype,
			question_subtype: fact.question_subtype,
			shape_id: fact.shape_id,
			topic_label: fact.topic_label,
			emotional_frame: fact.emotional_frame,
			content_length_bucket: fact.content_length_bucket,
			reply_mechanism: fact.reply_mechanism,
			media_style: fact.media_style,
			source_type: fact.source_type,
			posting_hour: fact.posting_hour,
			clone_family: classifyWinnerCloneFamily(fact),
			views_24h: fact.views_24h,
			replies_1h: fact.replies_1h,
			link_clicks: fact.smart_link_clicks,
			revenue: fact.smart_link_revenue,
			performance_basis: performanceBasis,
			clone_prompt: buildWinnerClonePrompt(fact),
			confidence: Math.min(
				0.95,
				0.55 +
					Math.min(0.25, fact.views_24h / 1000) +
					(fact.smart_link_clicks > 0 ? 0.1 : 0) +
					(fact.smart_link_revenue > 0 ? 0.15 : 0),
			),
			expires_at: new Date(Date.now() + 14 * 86_400_000).toISOString(),
		}));
}

export interface WinnerPatternLookup {
	source_post_id?: string | null;
	clone_family?: string | null;
}

export interface StrategyRecommendationLookup {
	id: string;
	pattern_type?: string | null;
	metric_basis?: Record<string, unknown> | null;
}

export interface AccountPerformanceStateLookup {
	account_id: string;
	recommended_strategy_mode?: string | null;
	recommended_posts_per_day?: number | null;
	avg_views_24h_30d?: number | null;
	posts_above_100_views_rate?: number | null;
	last_performance_recomputed_at?: string | null;
}

export interface ValidationWindowInput {
	patchAppliedAt?: string | Date | undefined;
	preDays?: number | undefined;
	postDays?: number | undefined;
	now?: Date | undefined;
}

export interface PerformanceValidationWindows {
	patchAppliedAt: string;
	pre: { start: string; end: string };
	post: { start: string; end: string };
}

export interface PerformanceValidationSummary {
	postCount: number;
	averageViewsPerPost: number;
	medianViewsPerPost: number;
	postsAbove100ViewsRate: number;
}

export interface PerformanceValidationBoardPost {
	postId: string;
	content: string | null;
	cloneFamily: string;
	contentArchetype: string;
	questionSubtype: string | null;
	postingHour: number | null;
	accountId: string | null;
	accountUsername: string | null;
	groupName: string | null;
	views24h: number;
	hasMedia: boolean;
	publishedAt: string | null;
}

export function buildPerformanceValidationWindows(
	input: ValidationWindowInput = {},
): PerformanceValidationWindows {
	const now = input.now || new Date();
	const patchDate = new Date(
		input.patchAppliedAt || DEFAULT_PERFORMANCE_PATCH_APPLIED_AT,
	);
	const validPatchDate = Number.isFinite(patchDate.getTime())
		? patchDate
		: new Date(DEFAULT_PERFORMANCE_PATCH_APPLIED_AT);
	const preDays = Math.max(1, Math.min(180, Math.floor(input.preDays || 14)));
	const postDays = Math.max(1, Math.min(180, Math.floor(input.postDays || 14)));
	const preStart = new Date(validPatchDate.getTime() - preDays * 86_400_000);
	const postEnd = new Date(
		Math.min(now.getTime(), validPatchDate.getTime() + postDays * 86_400_000),
	);
	return {
		patchAppliedAt: validPatchDate.toISOString(),
		pre: {
			start: preStart.toISOString(),
			end: validPatchDate.toISOString(),
		},
		post: {
			start: validPatchDate.toISOString(),
			end: postEnd.toISOString(),
		},
	};
}

export function factsInWindow(
	facts: AutoposterPerformanceFact[],
	window: { start: string; end: string },
): AutoposterPerformanceFact[] {
	const start = new Date(window.start).getTime();
	const end = new Date(window.end).getTime();
	return facts.filter((fact) => {
		if (!fact.published_at) return false;
		const publishedAt = new Date(fact.published_at).getTime();
		return (
			Number.isFinite(publishedAt) && publishedAt >= start && publishedAt < end
		);
	});
}

export function summarizeValidationFacts(
	facts: AutoposterPerformanceFact[],
): PerformanceValidationSummary {
	const summary = summarizePerformanceFacts(facts);
	return {
		postCount: summary.postCount,
		averageViewsPerPost: summary.averageViewsPerPost,
		medianViewsPerPost: summary.medianViewsPerPost,
		postsAbove100ViewsRate: summary.postsAbove100ViewsRate,
	};
}

export function deltaNumber(post: number, pre: number): number {
	return Math.round((post - pre) * 100) / 100;
}

export function deltaPct(post: number, pre: number): number | null {
	if (pre === 0) return post === 0 ? 0 : null;
	return Math.round(((post - pre) / pre) * 1000) / 10;
}

export function validationStatus(
	preCount: number,
	postCount: number,
	minSamples = MIN_VALIDATION_WINDOW_POSTS,
) {
	return preCount >= minSamples && postCount >= minSamples
		? "ready"
		: "insufficient_data";
}

export function resolveCloneFamily(
	fact: AutoposterPerformanceFact,
	input: {
		recommendationsById?: Map<string, StrategyRecommendationLookup> | undefined;
		winnerPatternsByPostId?: Map<string, WinnerPatternLookup> | undefined;
	},
): string {
	const recommendation = fact.strategy_recommendation_id
		? input.recommendationsById?.get(fact.strategy_recommendation_id)
		: null;
	const fromRecommendation = recommendation?.metric_basis?.cloneFamily;
	if (typeof fromRecommendation === "string" && fromRecommendation.trim()) {
		return fromRecommendation.trim();
	}
	const pattern =
		input.winnerPatternsByPostId?.get(fact.source_pattern_id || "") ||
		input.winnerPatternsByPostId?.get(fact.post_id);
	if (pattern?.clone_family) return pattern.clone_family;
	return "unknown";
}

function isWinnerCloneFact(
	fact: AutoposterPerformanceFact,
	recommendationsById?: Map<string, StrategyRecommendationLookup>,
): boolean {
	if (fact.strategy_bucket === "proven") return true;
	const recommendation = fact.strategy_recommendation_id
		? recommendationsById?.get(fact.strategy_recommendation_id)
		: null;
	return recommendation?.pattern_type === "winner_clone";
}

export function aggregateValidationBucket(
	facts: AutoposterPerformanceFact[],
	bucketFor: (fact: AutoposterPerformanceFact) => string,
	limit = 20,
) {
	const buckets = new Map<string, AutoposterPerformanceFact[]>();
	for (const fact of facts) {
		const key = bucketFor(fact);
		const rows = buckets.get(key) || [];
		rows.push(fact);
		buckets.set(key, rows);
	}
	return [...buckets.entries()]
		.map(([key, rows]) => ({
			key,
			...summarizeValidationFacts(rows),
			examples: rows
				.filter((fact) => fact.content)
				.slice(0, 3)
				.map((fact) => fact.content?.slice(0, 160) ?? ""),
		}))
		.sort((a, b) => b.averageViewsPerPost - a.averageViewsPerPost)
		.slice(0, limit);
}

export function compareValidationBucket(
	preFacts: AutoposterPerformanceFact[],
	postFacts: AutoposterPerformanceFact[],
	bucketFor: (fact: AutoposterPerformanceFact) => string,
	limit = 20,
) {
	const pre = new Map(
		aggregateValidationBucket(preFacts, bucketFor, 100).map((row) => [
			row.key,
			row,
		]),
	);
	const post = new Map(
		aggregateValidationBucket(postFacts, bucketFor, 100).map((row) => [
			row.key,
			row,
		]),
	);
	const keys = new Set([...pre.keys(), ...post.keys()]);
	return [...keys]
		.map((key) => {
			const preRow = pre.get(key) || {
				key,
				postCount: 0,
				averageViewsPerPost: 0,
				medianViewsPerPost: 0,
				postsAbove100ViewsRate: 0,
				examples: [],
			};
			const postRow = post.get(key) || {
				key,
				postCount: 0,
				averageViewsPerPost: 0,
				medianViewsPerPost: 0,
				postsAbove100ViewsRate: 0,
				examples: [],
			};
			return {
				key,
				pre: preRow,
				post: postRow,
				delta: {
					averageViewsPerPost: deltaNumber(
						postRow.averageViewsPerPost,
						preRow.averageViewsPerPost,
					),
					medianViewsPerPost: deltaNumber(
						postRow.medianViewsPerPost,
						preRow.medianViewsPerPost,
					),
					postsAbove100ViewsRate: deltaNumber(
						postRow.postsAbove100ViewsRate,
						preRow.postsAbove100ViewsRate,
					),
				},
			};
		})
		.sort(
			(a, b) =>
				b.post.averageViewsPerPost - a.post.averageViewsPerPost ||
				b.delta.averageViewsPerPost - a.delta.averageViewsPerPost,
		)
		.slice(0, limit);
}

export function buildValidationBoards(
	facts: AutoposterPerformanceFact[],
	input: {
		limit?: number | undefined;
		recommendationsById?: Map<string, StrategyRecommendationLookup> | undefined;
		winnerPatternsByPostId?: Map<string, WinnerPatternLookup> | undefined;
	} = {},
) {
	const limit = Math.max(1, Math.min(50, input.limit || 20));
	const shape = (
		fact: AutoposterPerformanceFact,
	): PerformanceValidationBoardPost => ({
		postId: fact.post_id,
		content: fact.content,
		cloneFamily: resolveCloneFamily(fact, input),
		contentArchetype: fact.content_archetype,
		questionSubtype: fact.question_subtype || null,
		postingHour: fact.posting_hour,
		accountId: fact.account_id,
		accountUsername: fact.account_username,
		groupName: fact.group_name,
		views24h: fact.views_24h,
		hasMedia: fact.has_media,
		publishedAt: fact.published_at,
	});
	const sorted = [...facts].sort((a, b) => b.views_24h - a.views_24h);
	return {
		winnerBoard: sorted.slice(0, limit).map(shape),
		loserBoard: sorted.slice(-limit).reverse().map(shape),
	};
}

export function buildPerformanceValidationReport(input: {
	facts: AutoposterPerformanceFact[];
	windows: PerformanceValidationWindows;
	limit?: number | undefined;
	recommendationsById?: Map<string, StrategyRecommendationLookup> | undefined;
	winnerPatternsByPostId?: Map<string, WinnerPatternLookup> | undefined;
	accountStatesById?: Map<string, AccountPerformanceStateLookup> | undefined;
	minSamples?: number | undefined;
}) {
	const limit = Math.max(3, Math.min(50, input.limit || 20));
	const preFacts = factsInWindow(input.facts, input.windows.pre);
	const postFacts = factsInWindow(input.facts, input.windows.post);
	const preSummary = summarizeValidationFacts(preFacts);
	const postSummary = summarizeValidationFacts(postFacts);
	const status = validationStatus(
		preSummary.postCount,
		postSummary.postCount,
		input.minSamples || MIN_VALIDATION_WINDOW_POSTS,
	);
	const summary = {
		status,
		pre: preSummary,
		post: postSummary,
		delta: {
			averageViewsPerPost: deltaNumber(
				postSummary.averageViewsPerPost,
				preSummary.averageViewsPerPost,
			),
			averageViewsPerPostPct: deltaPct(
				postSummary.averageViewsPerPost,
				preSummary.averageViewsPerPost,
			),
			medianViewsPerPost: deltaNumber(
				postSummary.medianViewsPerPost,
				preSummary.medianViewsPerPost,
			),
			postsAbove100ViewsRate: deltaNumber(
				postSummary.postsAbove100ViewsRate,
				preSummary.postsAbove100ViewsRate,
			),
		},
	};
	const media = compareValidationBucket(
		preFacts,
		postFacts,
		(fact) => (fact.has_media ? "image" : "text"),
		limit,
	);
	const questionSubtype = compareValidationBucket(
		preFacts,
		postFacts,
		(fact) => fact.question_subtype || "not_question_or_unknown",
		limit,
	);
	const cloneVsNonClone = compareValidationBucket(
		preFacts,
		postFacts,
		(fact) =>
			isWinnerCloneFact(fact, input.recommendationsById)
				? "winner_clone"
				: "non_clone",
		limit,
	);
	const cloneFamilies = compareValidationBucket(
		preFacts,
		postFacts,
		(fact) => resolveCloneFamily(fact, input),
		limit,
	);
	const accounts = compareValidationBucket(
		preFacts,
		postFacts,
		(fact) => fact.account_username || fact.account_id || "unknown",
		limit * 2,
	);
	const postBoards = buildValidationBoards(postFacts, {
		limit,
		recommendationsById: input.recommendationsById,
		winnerPatternsByPostId: input.winnerPatternsByPostId,
	});
	const accountRecovery = accounts.map((row) => {
		const matchingPostFact = postFacts.find(
			(fact) =>
				fact.account_username === row.key || fact.account_id === row.key,
		);
		const matchingPreFact = preFacts.find(
			(fact) =>
				fact.account_username === row.key || fact.account_id === row.key,
		);
		const accountId =
			matchingPostFact?.account_id || matchingPreFact?.account_id || null;
		const state = accountId ? input.accountStatesById?.get(accountId) : null;
		return {
			...row,
			accountId,
			recommendedStrategyMode: state?.recommended_strategy_mode ?? null,
			recommendedPostsPerDay: state?.recommended_posts_per_day ?? null,
			stateAverageViews24h30d: state?.avg_views_24h_30d ?? null,
			statePostsAbove100ViewsRate: state?.posts_above_100_views_rate ?? null,
			lastPerformanceRecomputedAt:
				state?.last_performance_recomputed_at ?? null,
			recoveryResult:
				state?.recommended_strategy_mode === "reduce" ||
				state?.recommended_strategy_mode === "suppress"
					? row.post.averageViewsPerPost >= 5 &&
						row.delta.averageViewsPerPost > 0
						? "improving_while_reduced"
						: "not_recovering"
					: "not_in_recovery",
		};
	});
	const findBucket = (
		rows: ReturnType<typeof compareValidationBucket>,
		key: string,
	) => rows.find((row) => row.key === key);
	const text = findBucket(media, "text");
	const image = findBucket(media, "image");
	const topical = findBucket(questionSubtype, "specific_topical_question");
	const generic =
		findBucket(questionSubtype, "generic_question_bait") ||
		findBucket(questionSubtype, "generic_question");
	const clone = findBucket(cloneVsNonClone, "winner_clone");
	const nonClone = findBucket(cloneVsNonClone, "non_clone");
	const answerStatus = status === "ready" ? "ready" : "insufficient_data";
	const workingCloneFamilies = cloneFamilies.filter(
		(row) =>
			row.key !== "unknown" &&
			row.post.postCount >= 3 &&
			row.post.averageViewsPerPost >= VIEW_TARGET_24H,
	);
	const improvedAccounts = accounts.filter(
		(row) =>
			row.post.postCount >= 3 &&
			row.delta.averageViewsPerPost > 0 &&
			row.post.averageViewsPerPost >= row.pre.averageViewsPerPost,
	);
	const retireCandidates = accounts.filter(
		(row) =>
			row.post.postCount >= MIN_ACCOUNT_STRATEGY_POSTS &&
			row.post.averageViewsPerPost < 5 &&
			row.post.postsAbove100ViewsRate === 0,
	);
	const answers = {
		averageViewsImproved: {
			status: answerStatus,
			value: status === "ready" ? summary.delta.averageViewsPerPost > 0 : null,
			reason:
				status === "ready"
					? `Average views changed by ${summary.delta.averageViewsPerPost}.`
					: "Not enough pre/post posts to validate average view lift.",
		},
		above100RateImproved: {
			status: answerStatus,
			value:
				status === "ready" ? summary.delta.postsAbove100ViewsRate > 0 : null,
			reason:
				status === "ready"
					? `Above-100 rate changed by ${summary.delta.postsAbove100ViewsRate} points.`
					: "Not enough pre/post posts to validate above-100 lift.",
		},
		textFirstImproved: {
			status:
				text?.post.postCount && image?.post.postCount
					? "ready"
					: "insufficient_data",
			value:
				text?.post.postCount && image?.post.postCount
					? text.post.averageViewsPerPost >= image.post.averageViewsPerPost
					: null,
			reason:
				text?.post.postCount && image?.post.postCount
					? `Post-patch text avg ${text.post.averageViewsPerPost} vs image avg ${image.post.averageViewsPerPost}.`
					: "Not enough post-patch text/image volume to compare.",
		},
		specificTopicalQuestionsBeatGeneric: {
			status:
				topical?.post.postCount && generic?.post.postCount
					? "ready"
					: "insufficient_data",
			value:
				topical?.post.postCount && generic?.post.postCount
					? topical.post.averageViewsPerPost > generic.post.averageViewsPerPost
					: null,
			reason:
				topical?.post.postCount && generic?.post.postCount
					? `Specific topical question avg ${topical.post.averageViewsPerPost} vs generic question avg ${generic.post.averageViewsPerPost}.`
					: "Not enough question subtype volume to compare.",
		},
		winnerClonesBeatNormalGeneration: {
			status:
				clone?.post.postCount && nonClone?.post.postCount
					? "ready"
					: "insufficient_data",
			value:
				clone?.post.postCount && nonClone?.post.postCount
					? clone.post.averageViewsPerPost > nonClone.post.averageViewsPerPost
					: null,
			reason:
				clone?.post.postCount && nonClone?.post.postCount
					? `Winner clone avg ${clone.post.averageViewsPerPost} vs non-clone avg ${nonClone.post.averageViewsPerPost}.`
					: "Not enough winner clone and non-clone volume to compare.",
		},
		workingCloneFamilies,
		improvedAccounts,
		retireCandidates,
	};
	const recommendations = [
		status === "ready" && summary.delta.averageViewsPerPost > 0
			? "Keep the performance-first patch active; average views improved."
			: status === "ready"
				? "Do not scale yet; average views have not improved."
				: "Wait for more post volume before changing strategy.",
		text?.post.postCount && image?.post.postCount
			? text.post.averageViewsPerPost >= image.post.averageViewsPerPost
				? "Keep Threads text-first until image posts beat text with sufficient volume."
				: "Re-open image testing for accounts where image posts beat text."
			: "Collect more text/image volume before changing media mix.",
		workingCloneFamilies.length > 0
			? `Increase observed working clone families: ${workingCloneFamilies.map((row) => row.key).join(", ")}.`
			: "Do not increase clone-family caps until a family beats target with enough samples.",
		retireCandidates.length > 0
			? `Retire or keep suppressed: ${retireCandidates
					.map((row) => row.key)
					.slice(0, 10)
					.join(", ")}.`
			: "No accounts meet retire criteria yet.",
	];
	return {
		windows: {
			...input.windows,
			pre: { ...input.windows.pre, count: preFacts.length },
			post: { ...input.windows.post, count: postFacts.length },
		},
		summary,
		breakdowns: {
			media,
			questionSubtype,
			cloneVsNonClone,
			cloneFamilies,
			accounts,
			accountRecovery,
		},
		answers,
		...postBoards,
		recommendations,
		dataQuality: {
			status,
			missingQuestionSubtypeCount: input.facts.filter(
				(fact) =>
					fact.content_archetype === "question" && !fact.question_subtype,
			).length,
			missingCloneAttributionCount: input.facts.filter(
				(fact) =>
					isWinnerCloneFact(fact, input.recommendationsById) &&
					resolveCloneFamily(fact, input) === "unknown",
			).length,
			sampleWarnings:
				status === "ready"
					? []
					: [
							`Need at least ${input.minSamples || MIN_VALIDATION_WINDOW_POSTS} posts in both pre and post windows.`,
						],
		},
	};
}

export interface ProfileCuriosityFrame {
	profileCuriosityFrame: string;
	datingAngle: boolean;
	validationAngle: boolean;
	identityAngle: boolean;
	curiosityMechanism: string;
	flirtAttractionAngle?: boolean;
}

const HIGH_VALUE_PROFILE_CURIOSITY_FRAMES = new Set([
	"direct_profile_curiosity",
	"dating_curiosity",
	"dating_validation",
	"validation_attraction",
	"body_confidence_identity",
	"flirty_attraction",
	"identity_curiosity",
]);

const HIGH_VALUE_CURIOSITY_MECHANISMS = new Set([
	"direct_profile_invitation",
	"dateability_test",
	"judgment_trigger",
	"validation_prompt",
	"body_confidence_identity",
	"flirt_tension",
	"relationship_standards_identity",
	"identity_statement",
]);

function normalizedFrameText(content: string | null | undefined): string {
	return String(content || "")
		.toLowerCase()
		.replace(/[’']/g, "'")
		.trim();
}

export function classifyProfileCuriosityFrame(
	content: string | null | undefined,
): ProfileCuriosityFrame {
	const text = normalizedFrameText(content);
	const relationshipSingle =
		/\b(i'?m|i am)\s+single\b/.test(text) ||
		/\b(single\s+(girl|life|era|but)|being single|single\.)\b/.test(text);
	const datingAngle =
		/\b(would you date|date a girl|dating|boyfriend|girlfriend|standards?|red flag|toxic|lose interest)\b/.test(
			text,
		) || relationshipSingle;
	const validationAngle =
		/\b(am i|still cute|cute|pretty|rate me|do i look|new top|problem if)\b/.test(
			text,
		);
	const identityAngle =
		/\b(i'?m|i am|my |girls who|girl who|red flag|toxic|crop top|gym gains?|obsessed with|taste is|i don'?t|i can)\b/.test(
			text,
		) || relationshipSingle;
	const flirtAttractionAngle =
		/\b(hot|sexy|flirty|flirt|thirst|thirsty|attention|clingy|needy|jealous|kiss|cuddle|late night text|good morning text|turns me on|handle)\b/.test(
			text,
		) ||
		(/\b(girl|girls|me|my)\b/.test(text) &&
			/\b(cute|pretty|date|single|crop top|headset|gym)\b/.test(text));
	const bodyConfidence =
		/\b(crop top|gym shark|gymshark|gym gains?|leg day|lifting|workout)\b/.test(
			text,
		) &&
		/\b(girl|girls|basic|can'?t be friends|problem|pretty|cute|fit|crime|stop acting)\b/.test(
			text,
		);
	const nicheIdentity =
		/\b(anime|gaming|headset|music|playlist|gym|pre-?workout)\b/.test(text) &&
		/\b(girl|girls|i'?m|my|obsessed|taste|red flag|date|cute|single)\b/.test(
			text,
		);
	const gatekeeping =
		/\b(gatekeep|gatekeeping|top\s*3|drop your|underrated|prove me wrong)\b/.test(
			text,
		);
	const directProfileCuriosity =
		/\b(check (my|the) profile|look at my profile|go to my profile|profile if|talk to me|text me|dm me|message me|free rn|actually free|need someone to talk|wanna know (a )?secret)\b/.test(
			text,
		);

	let curiosityMechanism = "generic_topic";
	if (directProfileCuriosity) {
		curiosityMechanism = "direct_profile_invitation";
	} else if (/\b(would you date|date a girl)\b/.test(text)) {
		curiosityMechanism = "dateability_test";
	} else if (/\b(red flag|toxic|lose interest)\b/.test(text)) {
		curiosityMechanism = "judgment_trigger";
	} else if (validationAngle) {
		curiosityMechanism = "validation_prompt";
	} else if (bodyConfidence) {
		curiosityMechanism = "body_confidence_identity";
	} else if (flirtAttractionAngle) {
		curiosityMechanism = "flirt_tension";
	} else if (
		relationshipSingle &&
		/\b(cook|clean|money|smoke|bad person|standard)\b/.test(text)
	) {
		curiosityMechanism = "relationship_standards_identity";
	} else if (nicheIdentity) {
		curiosityMechanism = "niche_identity";
	} else if (gatekeeping) {
		curiosityMechanism = "specific_gatekeeping_request";
	} else if (identityAngle) {
		curiosityMechanism = "identity_statement";
	}

	let profileCuriosityFrame = "generic_topic";
	if (datingAngle && validationAngle) profileCuriosityFrame = "dating_validation";
	else if (datingAngle) profileCuriosityFrame = "dating_curiosity";
	else if (validationAngle) profileCuriosityFrame = "validation_attraction";
	else if (bodyConfidence) profileCuriosityFrame = "body_confidence_identity";
	else if (directProfileCuriosity)
		profileCuriosityFrame = "direct_profile_curiosity";
	else if (flirtAttractionAngle) profileCuriosityFrame = "flirty_attraction";
	else if (nicheIdentity) profileCuriosityFrame = "niche_identity";
	else if (identityAngle) profileCuriosityFrame = "identity_curiosity";
	else if (gatekeeping) profileCuriosityFrame = "specific_gatekeeping";

	return {
		profileCuriosityFrame,
		datingAngle,
		validationAngle,
		identityAngle:
			identityAngle || bodyConfidence || nicheIdentity || flirtAttractionAngle,
		curiosityMechanism,
		flirtAttractionAngle,
	};
}

export function isHighValueProfileCuriosityContent(
	content: string | null | undefined,
): boolean {
	const frame = classifyProfileCuriosityFrame(content);
	return (
		HIGH_VALUE_PROFILE_CURIOSITY_FRAMES.has(frame.profileCuriosityFrame) ||
		HIGH_VALUE_CURIOSITY_MECHANISMS.has(frame.curiosityMechanism)
	);
}

export function profileCuriosityPriorityScore(
	content: string | null | undefined,
): number {
	const frame = classifyProfileCuriosityFrame(content);
	let score = 0;
	if (frame.profileCuriosityFrame === "direct_profile_curiosity") score += 90;
	else if (frame.profileCuriosityFrame === "dating_validation") score += 85;
	else if (frame.profileCuriosityFrame === "validation_attraction") score += 80;
	else if (frame.profileCuriosityFrame === "dating_curiosity") score += 78;
	else if (frame.profileCuriosityFrame === "flirty_attraction") score += 76;
	else if (frame.profileCuriosityFrame === "body_confidence_identity")
		score += 72;
	else if (frame.profileCuriosityFrame === "identity_curiosity") score += 60;
	else if (frame.profileCuriosityFrame === "niche_identity") score += 38;
	else if (frame.profileCuriosityFrame === "specific_gatekeeping") score += 24;
	if (frame.datingAngle) score += 18;
	if (frame.validationAngle) score += 16;
	if (frame.flirtAttractionAngle) score += 16;
	if (frame.identityAngle) score += 8;
	if (isProfileCuriosityDeadEndContent(content)) score -= 70;
	return score;
}

export function isProfileCuriosityDeadEndContent(
	content: string | null | undefined,
): boolean {
	const text = normalizedFrameText(content);
	if (!text) return false;
	const lowEffortDirectProfileBait =
		/\bwanna know (a )?(secret|something wild)\??\s*check my profile\b/.test(
			text,
		) ||
		/\bwanna know (a )?(secret|something wild) about (me|my .+)\??\s*check my profile\b/.test(
			text,
		);
	if (lowEffortDirectProfileBait) return true;
	const aestheticComfortFiller =
		/\b(cozy blankets?|blankets?|hot tea|tea|coffee|cute mug|quiet mornings?|morning coffee|sad girl anthem|heartbreak playlist|night light|rainy day|comfort show|comfort movie|comfort book|podcast|study snack|lazy sunday|soft playlist)\b/.test(
			text,
		);
	const strongProfileIntent =
		/\b(would you date|date a girl|am i (still )?(pretty|cute|hot)|still cute|crop top|gym gains?|red flag|toxic|lose interest|single|sexy|flirty|thirsty?|kiss|late night text|good morning text|check my profile|talk to me)\b/.test(
			text,
		) ||
		(/\bgirls? who\b/.test(text) &&
			/\b(pretty|sexy|date|dating|red flag|toxic|single|clingy|needy|jealous|kiss|crop top|gym gains?)\b/.test(
				text,
			));
	if (aestheticComfortFiller && !strongProfileIntent) return true;
	if (isHighValueProfileCuriosityContent(text)) return false;
	const hasCreatorCuriosityCue =
		/\b(girl|girls|would you date|date a girl|am i|cute|pretty|single|red flag|toxic|lose interest|crop top|headset|hot|sexy|flirty|thirst|clingy|needy|jealous|kiss|cuddle|late night text|good morning text|check my profile|talk to me|handle)\b/.test(
			text,
		);
	if (hasCreatorCuriosityCue) return false;
	const genericTopic =
		/\b(anime|manga|movie|show|music|song|playlist|gym|cardio|workout|game|gaming|podcast|book|snack|drink|food|coffee|study)\b/.test(
			text,
		);
	const genericAsk =
		/\b(what'?s|what is|which|best|favorite|favourite|go-?to|comfort|overrated|underrated|recommend|recs?|drop your|top\s*\d+|one .+ everyone|must watch)\b/.test(
			text,
		);
	const deadEndScene =
		/\b(comfort|chill|cozy|rainy day|lazy sunday|solo walk|after a long day|when bored|good cry|feeling down|study|character customization|anime opening|cardio machine|gym bro behavior)\b/.test(
			text,
		);
	return (
		(genericTopic && genericAsk) ||
		deadEndScene ||
		/\bwhat'?s your (?:favorite|favourite|go-?to|comfort) (?:anime|song|playlist|movie|show|game|snack|drink|book|podcast)\b/.test(
			text,
		)
	);
}

const FORMULA_PREFIX_RE =
	/^\s*(?:hot\s+take|unpopular\s+opinion|opinion|confession|asking\s+for\s+(?:a\s+)?friend)\s*:/i;
const FORMULA_SLOGAN_RE =
	/\b(?:trust|on god|no cap|that'?s tuff|bruh|based|fr fr|lowkey|deadass|sheesh)\b/i;

export function isLowCuriosityAiFormulaContent(
	content: string | null | undefined,
	sourceType?: string | null | undefined,
): boolean {
	if (sourceType && sourceType !== "ai") return false;
	const text = normalizedFrameText(content);
	if (!text) return false;
	if (!FORMULA_PREFIX_RE.test(text) && !FORMULA_SLOGAN_RE.test(text)) {
		return false;
	}
	const frame = classifyProfileCuriosityFrame(text);
	const highValue =
		frame.profileCuriosityFrame === "direct_profile_curiosity" ||
		frame.profileCuriosityFrame === "dating_curiosity" ||
		frame.profileCuriosityFrame === "dating_validation" ||
		frame.profileCuriosityFrame === "validation_attraction" ||
		frame.curiosityMechanism === "dateability_test" ||
		frame.curiosityMechanism === "validation_prompt" ||
		frame.curiosityMechanism === "relationship_standards_identity";
	if (highValue) return false;
	const genericDebate =
		/\b(pre-?workout|protein|cardio|lifting|workout|gym|coffee|playlist|anime|game|gaming|movie|show|song)\b/.test(
			text,
		) &&
		/\b(best|better|overrated|underrated|superior|essential|should|must|hits different|therapy|valid)\b/.test(
			text,
		);
	return FORMULA_PREFIX_RE.test(text) || genericDebate;
}

export function winnerCloneFrameAlignmentScore(input: {
	sourceContent?: string | null | undefined;
	candidateContent: string;
}): number {
	const source = classifyProfileCuriosityFrame(input.sourceContent);
	const candidate = classifyProfileCuriosityFrame(input.candidateContent);
	if (
		source.profileCuriosityFrame === "generic_topic" &&
		source.curiosityMechanism === "generic_topic"
	) {
		return 0;
	}

	let score = 0;
	for (const key of [
		"datingAngle",
		"validationAngle",
		"identityAngle",
	] as const) {
		if (!source[key]) continue;
		score += candidate[key] ? 25 : -35;
	}
	if (source.curiosityMechanism !== "generic_topic") {
		const highValueMechanism = [
			"direct_profile_invitation",
			"dateability_test",
			"validation_prompt",
			"body_confidence_identity",
			"relationship_standards_identity",
			"judgment_trigger",
			"flirt_tension",
		].includes(source.curiosityMechanism);
		score += candidate.curiosityMechanism === source.curiosityMechanism
			? 30
			: highValueMechanism
				? -60
				: -20;
	}
	if (
		source.profileCuriosityFrame !== "generic_topic" &&
		candidate.profileCuriosityFrame !== source.profileCuriosityFrame &&
		[
			"direct_profile_curiosity",
			"dating_curiosity",
			"dating_validation",
			"validation_attraction",
			"body_confidence_identity",
			"flirty_attraction",
		].includes(source.profileCuriosityFrame)
	) {
		score -= 25;
	}
	if (candidate.profileCuriosityFrame === "generic_topic") score -= 25;
	return Math.max(-90, Math.min(90, score));
}

function buildWinnerClonePrompt(fact: AutoposterPerformanceFact): string {
	const cloneFamily = classifyWinnerCloneFamily(fact);
	const frame = classifyProfileCuriosityFrame(fact.content);
	return [
		`Clone the performance pattern, not the exact wording.`,
		`Clone family=${cloneFamily}.`,
		`Source winner: "${fact.content || ""}"`,
		`Profile curiosity frame=${frame.profileCuriosityFrame}; mechanism=${frame.curiosityMechanism}; datingAngle=${frame.datingAngle ? "yes" : "no"}; validationAngle=${frame.validationAngle ? "yes" : "no"}; identityAngle=${frame.identityAngle ? "yes" : "no"}.`,
		`Archetype=${fact.content_archetype}; questionSubtype=${fact.question_subtype || "none"}; shape=${fact.shape_id || "none"}; topic=${fact.topic_label}; emotion=${fact.emotional_frame}; reply=${fact.reply_mechanism}; length=${fact.content_length_bucket}.`,
		`Keep the post similarly specific and conversion-aware if the source had direct/profile CTA energy.`,
		`Do not preserve only the topic. Preserve the dating, attraction, validation, identity, or judgment mechanism if present.`,
	].join(" ");
}

export function classifyWinnerCloneFamily(
	fact: Pick<
		AutoposterPerformanceFact,
		| "content"
		| "topic_label"
		| "content_archetype"
		| "shape_id"
		| "question_subtype"
	>,
): string {
	const text = `${fact.content || ""} ${fact.topic_label || ""}`.toLowerCase();
	const content = normalizedFrameText(fact.content);
	const frame = classifyProfileCuriosityFrame(fact.content);
	if (
		/\b(crop top|gym shark|gymshark|gym gains?|leg day|lifting|workout)\b/.test(
			text,
		) &&
		/\b(girl|girls|basic|can'?t be friends|problem|pretty|cute|fit|hot|sexy)\b/.test(
			text,
		)
	) {
		return "gym_crop_top_identity";
	}
	if (
		frame.profileCuriosityFrame === "flirty_attraction" ||
		frame.curiosityMechanism === "flirt_tension"
	) {
		return "flirty_profile_curiosity";
	}
	if (
		/\b(headset|gaming headset)\b/.test(content) &&
		frame.validationAngle
	) {
		return "headset_cute_validation";
	}
	if (
		/\b(age|am i|pretty|cute|new top)\b/.test(content) &&
		/\b(problem|pretty|cute|like|still cute|am i)\b/.test(content)
	) {
		return "age_pretty_validation";
	}
	if (
		/\banime\b/.test(text) &&
		/\b(date|dating|dateability|would you date|date a girl)\b/.test(text)
	) {
		return "anime_dateability_question";
	}
	if (
		/\banime\b/.test(text) &&
		/\b(must|watch|needs to watch|one anime)\b/.test(text)
	) {
		return "anime_must_watch_question";
	}
	if (
		/\bsingle\b/.test(text) &&
		/\b(cook|clean|money|smoke|bad person)\b/.test(text)
	) {
		return "single_cook_clean_identity";
	}
	if (
		fact.shape_id === "IM_A_X_BUT_Y" ||
		(/\bi'?m a\s*(9|10)\b/.test(text) &&
			/\b(unhinged|niche|taste)\b/.test(text))
	) {
		return "rating_but_niche_unhinged";
	}
	if (
		/\b(pre-?workout|protein|gym|workout)\b/.test(text) &&
		/\b(_+|prove me wrong|best|underrated)\b/.test(text)
	) {
		return "gym_fill_blank";
	}
	if (
		/\b(music|song|playlist)\b/.test(text) &&
		/\b(gatekeep|gatekeeping|top|best)\b/.test(text)
	) {
		return "music_gatekeeping_question";
	}
	return fact.question_subtype === "specific_topical_question"
		? "specific_topical_question_winner"
		: `${fact.content_archetype || "unknown"}_winner`;
}

export function classifyWinnerCloneFamilyFromContent(input: {
	content?: string | null | undefined;
	topicLabel?: string | null | undefined;
	contentArchetype?: string | null | undefined;
	shapeId?: string | null | undefined;
	questionSubtype?: string | null | undefined;
}): string {
	return classifyWinnerCloneFamily({
		content: input.content || "",
		topic_label: input.topicLabel || "unknown",
		content_archetype: input.contentArchetype || "unknown",
		shape_id: input.shapeId || null,
		question_subtype: input.questionSubtype || null,
	});
}

export function buildPerformanceFirstRecommendations(
	input: StrategyInput & {
		winnerPatterns?: ReturnType<typeof extractWinnerPatterns> | undefined;
		sourceTypePerformance?: RankedPattern[] | undefined;
		shapePerformance?: RankedPattern[] | undefined;
		accountStrategies?:
			| ReturnType<typeof accountPerformanceStrategies>
			| undefined;
	},
): StrategyRecommendation[] {
	const now = input.now || new Date();
	const expiresAt = new Date(now.getTime() + 7 * 86_400_000).toISOString();
	const rows: StrategyRecommendation[] = [];

	for (const winner of (input.winnerPatterns || []).slice(0, 12)) {
		if (!winner.workspace_id) continue;
		if (detectTaxonomyLabelLeak(winner.source_text)) continue;
		if (
			isLowCuriosityAiFormulaContent(winner.source_text, winner.source_type)
		) {
			continue;
		}
		const frame = classifyProfileCuriosityFrame(winner.source_text);
		if (
			frame.profileCuriosityFrame === "generic_topic" &&
			frame.curiosityMechanism === "generic_topic"
		) {
			continue;
		}
		const cloneFamily = classifyWinnerCloneFamilyFromContent({
			content: winner.source_text,
			topicLabel: winner.topic_label,
			contentArchetype: winner.content_archetype,
			shapeId: winner.shape_id,
			questionSubtype: winner.question_subtype,
		});
		rows.push({
			workspace_id: winner.workspace_id,
			group_id: winner.group_id,
			account_id: null,
			pattern_type: "winner_clone",
			pattern_value: winner.source_post_id,
			recommendation: "increase",
			confidence: Math.round(winner.confidence * 100) / 100,
			reason: `winner_clone_${winner.performance_basis}`,
			metric_basis: {
				sourcePostId: winner.source_post_id,
				sourcePatternId: winner.source_post_id,
				performanceBasis: winner.performance_basis,
				views24h: winner.views_24h,
				replies1h: winner.replies_1h,
				linkClicks: winner.link_clicks,
				revenue: winner.revenue,
				sourceText: winner.source_text,
				clonePrompt: winner.clone_prompt,
				cloneFamily,
				profileCuriosityFrame: frame.profileCuriosityFrame,
				curiosityMechanism: frame.curiosityMechanism,
				datingAngle: frame.datingAngle,
				validationAngle: frame.validationAngle,
				identityAngle: frame.identityAngle,
				contentArchetype: winner.content_archetype,
				questionSubtype: winner.question_subtype,
				shapeId: winner.shape_id,
				topicLabel: winner.topic_label,
				sourceType: winner.source_type,
			},
			expires_at: expiresAt,
		});
	}

	for (const pattern of (input.shapePerformance || []).slice(0, 5)) {
		if (!pattern.key || pattern.key === "unknown") continue;
		rows.push({
			workspace_id: input.workspaceId,
			group_id: input.groupId || null,
			account_id: input.accountId || null,
			pattern_type: "shape_id",
			pattern_value: pattern.key,
			recommendation: "increase",
			confidence: Math.min(
				0.9,
				0.55 + Math.min(0.25, (pattern.avg || 0) / 500),
			),
			reason: "shape_outperforms_on_24h_views",
			metric_basis: {
				days: input.days,
				count: pattern.count ?? null,
				avgViews24h: pattern.avg ?? null,
				above100Rate:
					(pattern as unknown as Record<string, unknown>).above100Rate ?? null,
			},
			expires_at: expiresAt,
		});
	}

	for (const pattern of (input.sourceTypePerformance || []).slice(0, 4)) {
		if (!pattern.key || pattern.key === "unknown") continue;
		rows.push({
			workspace_id: input.workspaceId,
			group_id: input.groupId || null,
			account_id: input.accountId || null,
			pattern_type: "source_type",
			pattern_value: pattern.key,
			recommendation: "increase",
			confidence: Math.min(0.9, 0.5 + Math.min(0.3, (pattern.avg || 0) / 500)),
			reason: "source_type_outperforms_on_24h_views",
			metric_basis: {
				days: input.days,
				count: pattern.count ?? null,
				avgViews24h: pattern.avg ?? null,
			},
			expires_at: expiresAt,
		});
	}

	for (const account of (input.accountStrategies || []).filter(
		(row) =>
			row.recommendedStrategyMode === "suppress" ||
			row.recommendedStrategyMode === "reduce",
	)) {
		rows.push({
			workspace_id: input.workspaceId,
			group_id: account.groupId || input.groupId || null,
			account_id: account.accountId,
			pattern_type: "account_strategy",
			pattern_value: account.recommendedStrategyMode,
			recommendation:
				account.recommendedStrategyMode === "suppress" ? "avoid" : "decrease",
			confidence: 0.72,
			reason: "account_below_view_target",
			metric_basis: {
				postCount: account.postCount,
				averageViews24h: account.averageViews24h,
				postsAbove100ViewsRate: account.postsAbove100ViewsRate,
				recommendedPostsPerDay: account.recommendedPostsPerDay,
			},
			expires_at: expiresAt,
		});
	}

	return rows;
}
