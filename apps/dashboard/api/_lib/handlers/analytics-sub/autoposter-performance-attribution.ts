/**
 * Autoposter performance attribution.
 *
 * GET /api/analytics?action=autoposter-performance-attribution&days=30&accountId=optional&groupId=optional
 *
 * Competitors are pattern/cadence corpus. Our own posts are performance truth.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";
import { classifyCompetitorPattern } from "../competitors/metricQuality.js";
import { classifyContentArchetype } from "../auto-post/contentArchetypes.js";
import {
	buildStrategyRecommendations,
	evaluateRecommendationOutcomes,
	expireUnderperformingRecommendations,
	replaceStrategyRecommendations,
	type StrategyRecommendation,
} from "../auto-post/strategyRecommendations.js";
import {
	accountPerformanceStrategies,
	aggregateCloneVsNonClonePerformance,
	aggregateFactMetric,
	aggregateHourPerformanceByScope,
	aggregateMediaPerformanceByAccount,
	buildAutoposterPerformanceFacts,
	buildPerformanceFirstRecommendations,
	extractWinnerPatterns,
	persistAutoposterPerformanceFacts,
	scoreCorrelation,
	summarizePerformanceFacts,
	topAndBottomPosts,
	type AutoposterPerformanceFact,
	type AutoposterQueueProvenanceInput,
	type SmartLinkAttributionInput,
} from "../auto-post/performanceFirst.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const QuerySchema = z.object({
	workspaceId: z.string().optional(),
	accountId: z.string().optional(),
	groupId: z.string().optional(),
	days: z.coerce.number().int().min(7).max(180).optional().default(30),
	limit: z.coerce.number().int().min(3).max(25).optional().default(10),
});

const db = () => getSupabaseAny();

type Distribution = Array<{ key: string; count: number; pct: number }>;

interface PostRow {
	id: string;
	user_id?: string | null;
	workspace_id?: string | null;
	account_id: string | null;
	cross_post_group_id: string | null;
	content: string | null;
	platform?: string | null;
	media_type: string | null;
	media_urls?: string[] | null;
	published_at: string | null;
	views_count: number | null;
	replies_count: number | null;
	likes_count: number | null;
	reposts_count?: number | null;
	quotes_count?: number | null;
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

interface HistoryRow {
	post_id: string;
	hours_since_publish: number | null;
	views_count: number | null;
	replies_count: number | null;
	likes_count?: number | null;
}

interface ScoredPost extends PostRow {
	hook_type: string;
	topic_label: string;
	format_type: string;
	emotional_frame: string;
	reply_mechanism: string;
	content_length_bucket: string;
	media_style: string;
	content_archetype: string;
	posting_hour: number | null;
	repliesAt1h: number;
	viewsAt24h: number;
}

function keyOrUnknown(value: string | number | null | undefined): string {
	if (typeof value === "number") return String(value).padStart(2, "0");
	return value?.trim() ? value.trim() : "unknown";
}

function distribution(values: string[], limit: number): Distribution {
	const counts = new Map<string, number>();
	for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
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

function aggregateBy(
	posts: ScoredPost[],
	field: keyof Pick<
		ScoredPost,
		| "hook_type"
		| "topic_label"
		| "format_type"
		| "emotional_frame"
		| "reply_mechanism"
		| "content_length_bucket"
		| "media_style"
		| "content_archetype"
	>,
	metric: "repliesAt1h" | "viewsAt24h",
	limit: number,
) {
	const buckets = new Map<
		string,
		{ count: number; total: number; examples: string[] }
	>();
	for (const post of posts) {
		const key = keyOrUnknown(post[field] as string | null);
		const bucket = buckets.get(key) || { count: 0, total: 0, examples: [] };
		bucket.count++;
		bucket.total += post[metric];
		if (bucket.examples.length < 3 && post.content) {
			bucket.examples.push(post.content.slice(0, 120));
		}
		buckets.set(key, bucket);
	}
	return [...buckets.entries()]
		.map(([key, bucket]) => ({
			key,
			count: bucket.count,
			avg: Math.round((bucket.total / Math.max(1, bucket.count)) * 100) / 100,
			total: bucket.total,
			examples: bucket.examples,
		}))
		.filter((item) => item.count >= 2 || posts.length < 10)
		.sort((a, b) => b.avg - a.avg)
		.slice(0, limit);
}

function aggregateHours(
	posts: ScoredPost[],
	metric: "repliesAt1h" | "viewsAt24h",
	limit: number,
) {
	const buckets = new Map<string, { count: number; total: number }>();
	for (const post of posts) {
		const key = keyOrUnknown(post.posting_hour);
		const bucket = buckets.get(key) || { count: 0, total: 0 };
		bucket.count++;
		bucket.total += post[metric];
		buckets.set(key, bucket);
	}
	return [...buckets.entries()]
		.map(([key, bucket]) => ({
			key,
			count: bucket.count,
			avg: Math.round((bucket.total / Math.max(1, bucket.count)) * 100) / 100,
			total: bucket.total,
		}))
		.filter((item) => item.key !== "unknown")
		.sort((a, b) => b.avg - a.avg)
		.slice(0, limit);
}

function recurringWorst(posts: ScoredPost[], limit: number) {
	return aggregateBy(posts, "content_archetype", "viewsAt24h", limit)
		.sort((a, b) => a.avg - b.avg)
		.slice(0, limit)
		.map((item) => ({
			...item,
			reason: "low_average_24h_views_for_recurring_archetype",
		}));
}

function average(values: number[]): number {
	if (values.length === 0) return 0;
	return (
		Math.round(
			(values.reduce((sum, value) => sum + value, 0) / values.length) * 100,
		) / 100
	);
}

function strategyBucketOutcomes(posts: ScoredPost[]) {
	const buckets = new Map<
		string,
		{ count: number; views: number[]; replies: number[] }
	>();
	for (const post of posts) {
		const key = post.strategy_bucket || "none";
		const bucket = buckets.get(key) || { count: 0, views: [], replies: [] };
		bucket.count++;
		bucket.views.push(post.viewsAt24h);
		bucket.replies.push(post.repliesAt1h);
		buckets.set(key, bucket);
	}
	return [...buckets.entries()]
		.map(([bucket, value]) => ({
			bucket,
			count: value.count,
			avg24hViews: average(value.views),
			avg1hReplies: average(value.replies),
		}))
		.sort((a, b) => b.avg24hViews - a.avg24hViews);
}

function strategyRecommendationOutcomes(posts: ScoredPost[], limit: number) {
	const buckets = new Map<
		string,
		{
			count: number;
			views: number[];
			replies: number[];
			bucket: string;
			examples: string[];
		}
	>();
	for (const post of posts) {
		if (!post.strategy_recommendation_id) continue;
		const current = buckets.get(post.strategy_recommendation_id) || {
			count: 0,
			views: [],
			replies: [],
			bucket: post.strategy_bucket || "none",
			examples: [],
		};
		current.count++;
		current.views.push(post.viewsAt24h);
		current.replies.push(post.repliesAt1h);
		if (current.examples.length < 3 && post.content) {
			current.examples.push(post.content.slice(0, 120));
		}
		buckets.set(post.strategy_recommendation_id, current);
	}
	return [...buckets.entries()]
		.map(([strategyRecommendationId, value]) => ({
			strategyRecommendationId,
			strategyBucket: value.bucket,
			count: value.count,
			avg24hViews: average(value.views),
			avg1hReplies: average(value.replies),
			examples: value.examples,
		}))
		.sort((a, b) => b.avg24hViews - a.avg24hViews)
		.slice(0, limit);
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
	return [...new Set(values.filter((value): value is string => !!value))];
}

function queueIdForPost(post: PostRow): string | null {
	const metadata = post.metadata || {};
	return (
		post.auto_post_queue_id ||
		(typeof metadata.autoPostQueueId === "string"
			? metadata.autoPostQueueId
			: null) ||
		(typeof metadata.auto_post_queue_id === "string"
			? metadata.auto_post_queue_id
			: null)
	);
}

async function loadSmartLinkAttribution(
	postIds: string[],
): Promise<SmartLinkAttributionInput[]> {
	if (postIds.length === 0) return [];
	const { data: links } = await db()
		.from("smart_links")
		.select("id, post_id")
		.in("post_id", postIds);
	const linkRows = (
		(links || []) as Array<{ id: string; post_id: string | null }>
	).filter((row) => row.id && row.post_id);
	if (linkRows.length === 0) return [];
	const linkToPost = new Map(
		linkRows.map((row) => [row.id, row.post_id as string]),
	);
	const linkIds = linkRows.map((row) => row.id);
	const [{ data: clickRows }, { data: conversionRows }] = await Promise.all([
		db()
			.from("smart_link_clicks")
			.select("smart_link_id")
			.in("smart_link_id", linkIds),
		db()
			.from("smart_link_conversions")
			.select("smart_link_id, conversion_value")
			.in("smart_link_id", linkIds),
	]);
	const byPost = new Map<string, SmartLinkAttributionInput>();
	for (const click of (clickRows || []) as Array<{ smart_link_id: string }>) {
		const postId = linkToPost.get(click.smart_link_id);
		if (!postId) continue;
		const current = byPost.get(postId) || {
			post_id: postId,
			clicks: 0,
			conversions: 0,
			revenue: 0,
		};
		current.clicks++;
		byPost.set(postId, current);
	}
	for (const conversion of (conversionRows || []) as Array<{
		smart_link_id: string;
		conversion_value: number | null;
	}>) {
		const postId = linkToPost.get(conversion.smart_link_id);
		if (!postId) continue;
		const current = byPost.get(postId) || {
			post_id: postId,
			clicks: 0,
			conversions: 0,
			revenue: 0,
		};
		current.conversions++;
		current.revenue += Number(conversion.conversion_value || 0);
		byPost.set(postId, current);
	}
	return [...byPost.values()];
}

async function persistPerformanceFacts(facts: AutoposterPerformanceFact[]) {
	type PerformanceFactDbClient = Parameters<
		typeof persistAutoposterPerformanceFacts
	>[0];
	return persistAutoposterPerformanceFacts(db() as PerformanceFactDbClient, facts);
}

async function persistWinnerPatterns(
	winners: ReturnType<typeof extractWinnerPatterns>,
) {
	const rows = winners.filter((winner) => winner.workspace_id);
	if (rows.length === 0) return false;
	const { error } = await db()
		.from("autoposter_winner_patterns")
		.upsert(rows, { onConflict: "source_post_id,performance_basis" });
	return !error;
}

async function persistAccountPerformanceState(
	accountStrategies: ReturnType<typeof accountPerformanceStrategies>,
) {
	const now = new Date().toISOString();
	let persisted = 0;
	for (const row of accountStrategies) {
		const { error } = await db()
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
		if (!error) persisted++;
	}
	return persisted;
}

function compareDistributions(
	competitorDist: Distribution,
	ownDist: Distribution,
	limit: number,
) {
	const own = new Map(ownDist.map((item) => [item.key, item.pct]));
	const competitor = new Map(
		competitorDist.map((item) => [item.key, item.pct]),
	);
	const keys = new Set([...own.keys(), ...competitor.keys()]);
	return [...keys]
		.map((key) => {
			const competitorPct = competitor.get(key) || 0;
			const ourPct = own.get(key) || 0;
			return {
				key,
				competitorPct,
				ourPct,
				gapPct: Math.round((competitorPct - ourPct) * 10) / 10,
			};
		})
		.filter((item) => item.key !== "unknown")
		.sort((a, b) => Math.abs(b.gapPct) - Math.abs(a.gapPct))
		.slice(0, limit);
}

function classifyPost(row: PostRow): ScoredPost {
	const fallback = classifyCompetitorPattern({
		content: row.content,
		topicTag: row.topic_label,
		mediaType:
			row.media_type ||
			(row.media_urls && row.media_urls.length > 0 ? "IMAGE" : "TEXT"),
		publishedAt: row.published_at,
	});
	const metadataArchetype =
		typeof row.metadata?.content_archetype === "object" &&
		row.metadata?.content_archetype !== null &&
		"value" in row.metadata.content_archetype
			? String(
					(row.metadata.content_archetype as { value?: unknown }).value || "",
				)
			: typeof row.metadata?.pattern_type === "string"
				? row.metadata.pattern_type
				: "";
	const archetype =
		metadataArchetype || classifyContentArchetype(row.content).archetype;
	return {
		...row,
		hook_type: row.hook_type || fallback.hook_type,
		topic_label: row.topic_label || fallback.topic_label,
		format_type: row.format_type || fallback.format_type,
		emotional_frame: row.emotional_frame || fallback.emotional_frame,
		reply_mechanism: row.reply_mechanism || fallback.reply_mechanism,
		content_length_bucket:
			row.content_length_bucket || fallback.content_length_bucket,
		media_style: row.media_style || fallback.media_style,
		content_archetype: archetype,
		posting_hour: row.posting_hour ?? fallback.posting_hour,
		repliesAt1h: row.replies_count || 0,
		viewsAt24h: row.views_count || 0,
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const {
			workspaceId: requestedWorkspaceId,
			accountId,
			groupId,
			days,
			limit,
		} = parsed;

		let accountIds: string[] | null = null;
		let workspaceId = requestedWorkspaceId || null;
		if (accountId) {
			const account = await verifyAccountOwnership(
				res,
				accountId,
				user.id,
				"id",
			);
			if (!account) return;
			accountIds = [accountId];
		} else if (groupId) {
			const { data: group, error } = await db()
				.from("account_groups")
				.select("id, account_ids")
				.eq("id", groupId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (error)
				return apiError(res, 500, "Failed to verify group", {
					details: error.message,
				});
			if (!group) return apiError(res, 404, "Group not found");
			accountIds = ((group.account_ids || []) as string[]).filter(Boolean);
		}
		if (requestedWorkspaceId) {
			const { data: member, error } = await db()
				.from("workspace_members")
				.select("workspace_id")
				.eq("workspace_id", requestedWorkspaceId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (error) {
				return apiError(res, 500, "Failed to verify workspace", {
					details: error.message,
				});
			}
			if (!member) return apiError(res, 404, "Workspace not found");
		}
		if (!workspaceId) {
			const { data: memberships } = await db()
				.from("workspace_members")
				.select("workspace_id")
				.eq("user_id", user.id)
				.limit(1);
			workspaceId = (memberships?.[0]?.workspace_id as string | null) || null;
		}

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();
		let postQuery = db()
			.from("posts")
			.select(
				"id, user_id, account_id, cross_post_group_id, content, platform, media_type, media_urls, published_at, views_count, replies_count, likes_count, reposts_count, quotes_count, hook_type, topic_label, format_type, emotional_frame, reply_mechanism, content_length_bucket, media_style, posting_hour, prompt_version, template_id, model_provider, source_pattern_id, strategy_recommendation_id, strategy_bucket, auto_post_queue_id, metadata",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.gte("published_at", cutoff)
			.not("content", "is", null);
		if (accountIds && accountIds.length > 0)
			postQuery = postQuery.in("account_id", accountIds);
		const { data: rows, error: postsError } = await postQuery.limit(1000);
		if (postsError) {
			return apiError(res, 500, "Failed to fetch own posts", {
				details: postsError.message,
			});
		}

		const posts = ((rows || []) as PostRow[]).map(classifyPost);
		const postIds = posts.map((post) => post.id);
		if (postIds.length > 0) {
			const { data: historyRows } = await db()
				.from("post_metric_history")
				.select(
					"post_id, hours_since_publish, views_count, replies_count, likes_count",
				)
				.in("post_id", postIds)
				.lte("hours_since_publish", 28)
				.order("hours_since_publish", { ascending: true });
			const at1h = new Map<string, HistoryRow>();
			const at24h = new Map<string, HistoryRow>();
			for (const row of (historyRows || []) as HistoryRow[]) {
				const hour = Number(row.hours_since_publish ?? 0);
				if (hour <= 2 && !at1h.has(row.post_id)) at1h.set(row.post_id, row);
				if (hour >= 20 && hour <= 28 && !at24h.has(row.post_id)) {
					at24h.set(row.post_id, row);
				}
			}
			for (const post of posts) {
				post.repliesAt1h =
					at1h.get(post.id)?.replies_count ?? post.replies_count ?? 0;
				post.viewsAt24h =
					at24h.get(post.id)?.views_count ?? post.views_count ?? 0;
			}
		}

		const queueIds = uniqueStrings(
			(rows || []).map((post) => queueIdForPost(post as PostRow)),
		);
		const accountLookup = new Map<
			string,
			{ username: string | null; workspace_id: string | null }
		>();
		const groupLookup = new Map<string, { name: string | null }>();
		const [queueResult, smartLinkAttribution] = await Promise.all([
			queueIds.length > 0
				? db()
						.from("auto_post_queue")
						.select(
							"id, source_type, source_id, source_competitor_id, source_competitor_username, strategy_recommendation_id, strategy_bucket, source_pattern_id, media_style, metadata",
						)
						.in("id", queueIds)
				: Promise.resolve({ data: [] }),
			loadSmartLinkAttribution(postIds),
		]);
		const accountLookupIds = uniqueStrings(
			posts.map((post) => post.account_id),
		);
		if (accountLookupIds.length > 0) {
			const { data: accountRows } = await db()
				.from("accounts")
				.select("id, username")
				.in("id", accountLookupIds);
			for (const account of (accountRows || []) as Array<{
				id: string;
				username: string | null;
			}>) {
				accountLookup.set(account.id, {
					username: account.username,
					workspace_id: workspaceId,
				});
			}
		}
		const groupLookupIds = uniqueStrings(
			posts.map((post) => post.cross_post_group_id),
		);
		if (groupLookupIds.length > 0) {
			const { data: groupRows } = await db()
				.from("account_groups")
				.select("id, name")
				.in("id", groupLookupIds);
			for (const group of (groupRows || []) as Array<{
				id: string;
				name: string | null;
			}>) {
				groupLookup.set(group.id, { name: group.name });
			}
		}
		const performanceFacts = buildAutoposterPerformanceFacts({
			posts: (rows || []) as PostRow[],
			historyRows: ((postIds.length > 0
				? (
						await db()
							.from("post_metric_history")
							.select(
								"post_id, hours_since_publish, views_count, replies_count, likes_count",
							)
							.in("post_id", postIds)
							.lte("hours_since_publish", 28)
					).data
				: []) || []) as HistoryRow[],
			queueRows: (queueResult.data || []) as AutoposterQueueProvenanceInput[],
			smartLinkAttribution,
			accountLookup,
			groupLookup,
		});
		let performanceFactsPersisted = false;
		try {
			performanceFactsPersisted =
				await persistPerformanceFacts(performanceFacts);
		} catch {
			performanceFactsPersisted = false;
		}

		const ownDistribution = {
			archetypes: distribution(
				posts.map((post) => keyOrUnknown(post.content_archetype)),
				limit,
			),
			hooks: distribution(
				posts.map((post) => keyOrUnknown(post.hook_type)),
				limit,
			),
			topics: distribution(
				posts.map((post) => keyOrUnknown(post.topic_label)),
				limit,
			),
			formats: distribution(
				posts.map((post) => keyOrUnknown(post.format_type)),
				limit,
			),
			mediaStyles: distribution(
				posts.map((post) => keyOrUnknown(post.media_style)),
				limit,
			),
			hours: distribution(
				posts.map((post) => keyOrUnknown(post.posting_hour)),
				limit,
			),
		};

		const { data: competitors } = await db()
			.from("competitors")
			.select("id")
			.eq("user_id", user.id)
			.or("sync_status.eq.active,sync_status.is.null");
		const competitorIds = (competitors || []).map((c: { id: string }) => c.id);
		let competitorCorpus: Array<{
			content: string | null;
			hook_type: string | null;
			topic_label: string | null;
			format_type: string | null;
			media_style: string | null;
			posting_hour: number | null;
			content_archetype?: string | null;
		}> = [];
		if (competitorIds.length > 0) {
			const { data: corpusRows } = await db()
				.from("competitor_top_posts")
				.select(
					"content, hook_type, topic_label, format_type, media_style, posting_hour",
				)
				.in("competitor_id", competitorIds)
				.gte("scraped_at", cutoff)
				.not("content", "is", null)
				.limit(1000);
			competitorCorpus = ((corpusRows || []) as typeof competitorCorpus).map(
				(row) => ({
					...row,
					content_archetype: classifyContentArchetype(row.content).archetype,
				}),
			);
		}

		const competitorDistribution = {
			archetypes: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.content_archetype)),
				limit,
			),
			hooks: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.hook_type)),
				limit,
			),
			topics: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.topic_label)),
				limit,
			),
			formats: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.format_type)),
				limit,
			),
			mediaStyles: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.media_style)),
				limit,
			),
			hours: distribution(
				competitorCorpus.map((row) => keyOrUnknown(row.posting_hour)),
				limit,
			),
		};

		const best = {
			archetypesBy1hReplies: aggregateBy(
				posts,
				"content_archetype",
				"repliesAt1h",
				limit,
			),
			archetypesBy24hViews: aggregateBy(
				posts,
				"content_archetype",
				"viewsAt24h",
				limit,
			),
			hookTypesBy1hReplies: aggregateBy(
				posts,
				"hook_type",
				"repliesAt1h",
				limit,
			),
			hookTypesBy24hViews: aggregateBy(posts, "hook_type", "viewsAt24h", limit),
			topicsBy24hViews: aggregateBy(posts, "topic_label", "viewsAt24h", limit),
			formatsBy24hViews: aggregateBy(posts, "format_type", "viewsAt24h", limit),
			postingHoursBy24hViews: aggregateHours(posts, "viewsAt24h", limit),
		};
		const worstRecurringPatterns = recurringWorst(posts, limit);
		const competitorPatternsWeUnderuse = {
			archetypes: compareDistributions(
				competitorDistribution.archetypes,
				ownDistribution.archetypes,
				limit,
			).filter((item) => item.gapPct > 0),
			hooks: compareDistributions(
				competitorDistribution.hooks,
				ownDistribution.hooks,
				limit,
			).filter((item) => item.gapPct > 0),
			topics: compareDistributions(
				competitorDistribution.topics,
				ownDistribution.topics,
				limit,
			).filter((item) => item.gapPct > 0),
			formats: compareDistributions(
				competitorDistribution.formats,
				ownDistribution.formats,
				limit,
			).filter((item) => item.gapPct > 0),
		};
		const competitorPatternsWeOveruse = {
			archetypes: compareDistributions(
				competitorDistribution.archetypes,
				ownDistribution.archetypes,
				limit,
			).filter((item) => item.gapPct < 0),
			hooks: compareDistributions(
				competitorDistribution.hooks,
				ownDistribution.hooks,
				limit,
			).filter((item) => item.gapPct < 0),
			topics: compareDistributions(
				competitorDistribution.topics,
				ownDistribution.topics,
				limit,
			).filter((item) => item.gapPct < 0),
			formats: compareDistributions(
				competitorDistribution.formats,
				ownDistribution.formats,
				limit,
			).filter((item) => item.gapPct < 0),
		};
		const baselineViewsAt24h = average(posts.map((post) => post.viewsAt24h));
		const performanceSummary = summarizePerformanceFacts(performanceFacts);
		const topBottomPosts = topAndBottomPosts(performanceFacts, 20);
		const accountStrategies = accountPerformanceStrategies(performanceFacts);
		const winningArchetypes = aggregateFactMetric(
			performanceFacts,
			"content_archetype",
			limit,
			2,
		);
		const questionSubtypePerformance = aggregateFactMetric(
			performanceFacts,
			"question_subtype",
			limit,
			1,
		);
		const winningShapes = aggregateFactMetric(
			performanceFacts,
			"shape_id",
			limit,
			1,
		);
		const winningSourceTypes = aggregateFactMetric(
			performanceFacts,
			"source_type",
			limit,
			1,
		);
		const mediaPerformance = {
			byMediaType: aggregateFactMetric(
				performanceFacts,
				"media_type",
				limit,
				1,
			),
			byMediaStyle: aggregateFactMetric(
				performanceFacts,
				"media_style",
				limit,
				1,
			),
			byAccountTextVsMedia: aggregateMediaPerformanceByAccount(
				performanceFacts,
				limit * 2,
			),
		};
		const timingPerformance = aggregateHours(posts, "viewsAt24h", limit);
		const scopedTimingPerformance = {
			byAccount: aggregateHourPerformanceByScope(
				performanceFacts,
				"account",
				limit * 3,
			),
			byCreator: aggregateHourPerformanceByScope(
				performanceFacts,
				"creator",
				limit * 3,
			),
		};
		const winnerPatterns = extractWinnerPatterns(performanceFacts, 25);
		let winnerPatternsPersisted = false;
		try {
			winnerPatternsPersisted = await persistWinnerPatterns(winnerPatterns);
		} catch {
			winnerPatternsPersisted = false;
		}
		let accountPerformanceStateRowsUpdated = 0;
		try {
			accountPerformanceStateRowsUpdated =
				await persistAccountPerformanceState(accountStrategies);
		} catch {
			accountPerformanceStateRowsUpdated = 0;
		}
		const recommendationOutcomeEvaluations = evaluateRecommendationOutcomes(
			posts.map((post) => ({
				strategy_recommendation_id: post.strategy_recommendation_id,
				viewsAt24h: post.viewsAt24h,
			})),
			baselineViewsAt24h,
		);
		let strategyRecommendations: StrategyRecommendation[] = [];
		let strategyPersisted = false;
		if (workspaceId && posts.length > 0) {
			strategyRecommendations = buildStrategyRecommendations({
				workspaceId,
				groupId: groupId || null,
				accountId: accountId || null,
				days,
				best,
				worstRecurringPatterns,
				competitorPatternsWeUnderuse,
				competitorPatternsWeOveruse,
			});
			strategyRecommendations = [
				...buildPerformanceFirstRecommendations({
					workspaceId,
					groupId: groupId || null,
					accountId: accountId || null,
					days,
					best,
					worstRecurringPatterns,
					competitorPatternsWeUnderuse,
					competitorPatternsWeOveruse,
					winnerPatterns,
					sourceTypePerformance: winningSourceTypes,
					shapePerformance: winningShapes,
					accountStrategies,
				}),
				...strategyRecommendations,
			];
			try {
				await replaceStrategyRecommendations(
					{
						workspaceId,
						groupId: groupId || null,
						accountId: accountId || null,
					},
					strategyRecommendations,
				);
				strategyPersisted = strategyRecommendations.length > 0;
			} catch {
				strategyPersisted = false;
			}
		}
		try {
			await expireUnderperformingRecommendations(
				recommendationOutcomeEvaluations,
			);
		} catch {
			// Outcome expiry should never block the report payload.
		}

		return apiSuccess(res, {
			periodDays: days,
			workspaceId,
			accountId: accountId || null,
			groupId: groupId || null,
			postCount: posts.length,
			competitorCorpusCount: competitorCorpus.length,
			principle:
				"Competitor rows are pattern/cadence corpus. Our own posts provide performance truth.",
			best,
			worstRecurringPatterns,
			performanceTruth: {
				...performanceSummary,
				primaryMetric: "views_24h",
				targetAverageViewsPerPost: 100,
				factsPersisted: performanceFactsPersisted,
				winnerPatternsPersisted,
				accountPerformanceStateRowsUpdated,
				conversionAttribution:
					performanceSummary.totalLinkClicks > 0 ||
					performanceSummary.totalConversions > 0
						? "post_smart_link"
						: "unavailable",
				profileClicks:
					"Threads post-level profile clicks are not reliably available; use smart-link clicks or account/day proxy data when present.",
			},
			postLeaders: topBottomPosts,
			performanceWinners: {
				archetypes: winningArchetypes,
				questionSubtypes: questionSubtypePerformance,
				shapes: winningShapes,
				sourceTypes: winningSourceTypes,
				media: mediaPerformance,
				postingHours: timingPerformance,
				scopedPostingHours: scopedTimingPerformance,
			},
			performanceLosers: {
				archetypes: [...winningArchetypes].reverse(),
				shapes: [...winningShapes].reverse(),
				sourceTypes: [...winningSourceTypes].reverse(),
			},
			accountsByPerformance: {
				aboveTarget: accountStrategies.filter(
					(row) => row.averageViews24h >= 100,
				),
				belowTarget: accountStrategies.filter(
					(row) => row.averageViews24h < 100,
				),
				deadWeight: accountStrategies.filter(
					(row) => row.recommendedStrategyMode === "suppress",
				),
				all: accountStrategies,
			},
			correlations: {
				creatorFitVs24hViews: scoreCorrelation(
					performanceFacts,
					"creator_fit_score",
				),
				dnaFitVs24hViews: scoreCorrelation(performanceFacts, "dna_fit_score"),
				accountFlavorFitVs24hViews: scoreCorrelation(
					performanceFacts,
					"account_flavor_score",
				),
			},
			winnerCloning: {
				count: winnerPatterns.length,
				patterns: winnerPatterns.slice(0, limit),
				cloneFamilies: distribution(
					winnerPatterns.map((pattern) => pattern.clone_family || "unknown"),
					limit,
				),
				cloneVsNonClonePerformance:
					aggregateCloneVsNonClonePerformance(performanceFacts),
				rule: "Clone the performance pattern of measured winners; do not copy exact text unless the source is an allowed direct microcopy lane.",
			},
			distributions: {
				ours: ownDistribution,
				competitors: competitorDistribution,
			},
			competitorPatternsWeUnderuse,
			competitorPatternsWeOveruse,
			strategyRecommendations,
			strategyPersisted,
			strategyOutcomeTracking: {
				baselineViewsAt24h,
				byBucket: strategyBucketOutcomes(posts),
				byRecommendation: strategyRecommendationOutcomes(posts, limit),
				autoExpired: recommendationOutcomeEvaluations.filter(
					(outcome) => outcome.shouldExpire,
				),
			},
			generatorGuidance: {
				increase:
					"Prioritize measured winner clones and patterns that lift 24h views, then test competitor/direct market patterns.",
				avoid:
					"Reduce accounts and patterns that repeatedly miss view target. Creator fit is a soft signal until it correlates with views/clicks/revenue.",
			},
		});
	},
);
