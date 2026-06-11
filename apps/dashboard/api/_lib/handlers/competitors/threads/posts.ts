/**
 * Handlers: POST /api/competitors?action=fetch-top-posts
 *           GET  /api/competitors?action=top-posts
 *           GET  /api/competitors?action=aggregated-top-posts
 *
 * Fetch, retrieve, and aggregate competitor corpus posts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
} from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { cached } from "../../../redisCache.js";
import {
	CompetitorFetchTopPostsSchema,
	parseBodyOrError,
} from "../../../validation.js";
import { verifyCompetitorOwnership } from "../../helpers/verifyOwnership.js";
import { db, fetchAndStorePosts, getAccessToken } from "../shared.js";

interface CompetitorWithPlatform {
	id: string;
	platform?: string | null | undefined;
}

interface CompetitorWithMeta {
	id: string;
	username: string;
	avatar_url?: string | null | undefined;
	platform?: string | null | undefined;
}

interface TopPostRow {
	competitor_id: string;
	engagement_score?: number | null | undefined;
	metric_quality?: string | null | undefined;
	scraped_at?: string | null | undefined;
	published_at?: string | null | undefined;
	[key: string]: unknown;
}

function sortCompetitorCorpus(a: TopPostRow, b: TopPostRow): number {
	const aValid =
		a.metric_quality === "valid_engagement" ||
		a.metric_quality === "scraper_estimated";
	const bValid =
		b.metric_quality === "valid_engagement" ||
		b.metric_quality === "scraper_estimated";
	if (aValid && bValid) {
		return (b.engagement_score || 0) - (a.engagement_score || 0);
	}
	if (aValid !== bValid) return aValid ? -1 : 1;
	const aTime = new Date((a.scraped_at || a.published_at || 0) as string).getTime();
	const bTime = new Date((b.scraped_at || b.published_at || 0) as string).getTime();
	return (Number.isFinite(bTime) ? bTime : 0) - (Number.isFinite(aTime) ? aTime : 0);
}

export async function handleFetchTopPosts(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const parsed = parseBodyOrError(res, CompetitorFetchTopPostsSchema, req.body);
	if (!parsed) return;
	const { competitorId, username } = parsed;

	// Verify competitor ownership (IDOR prevention)
	const ownedCompetitor = await verifyCompetitorOwnership(
		res,
		competitorId,
		user.id,
		"id",
	);
	if (!ownedCompetitor) return;

	const accessToken = await getAccessToken(user.id);
	if (!accessToken) return apiError(res, 400, "No connected account");

	try {
		const count = await fetchAndStorePosts(
			competitorId,
			username,
			accessToken,
			user.id,
		);
		return apiSuccess(res, { count });
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Failed to fetch competitor corpus posts", {
			username,
			error: message,
		});
		return apiError(
			res,
			502,
			message || "Failed to fetch posts from Threads API",
		);
	}
}

export async function handleGetTopPosts(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const competitorId = req.query.competitorId as string;
	if (!competitorId) return apiError(res, 400, "competitorId required");

	// Verify competitor ownership (IDOR prevention) and fetch platform
	const { data: ownedCompetitor } = await db()
		.from("competitors")
		.select("id, platform")
		.eq("id", competitorId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (!ownedCompetitor) {
		return apiError(res, 403, "Competitor not found or not authorized");
	}

	const rawLimit = req.query.limit as string;
	const topPostsLimit = parseInt(rawLimit, 10) || 50;
	if (topPostsLimit < 1 || topPostsLimit > 100) {
		return apiError(res, 400, "limit must be between 1 and 100");
	}

	const competitorPlatform =
		(ownedCompetitor as CompetitorWithPlatform).platform || "threads";

	const result = await cached(
		`competitor-corpus-posts:${competitorId}:${topPostsLimit}`,
		120,
		async () => {
			const { data: posts } = await db()
				.from("competitor_top_posts")
				.select("*")
				.eq("competitor_id", competitorId)
				.order("scraped_at", { ascending: false, nullsFirst: false })
				.limit(Math.max(topPostsLimit * 3, topPostsLimit));

			const enrichedPosts = (((posts as TopPostRow[]) || [])
				.sort(sortCompetitorCorpus)
				.slice(0, topPostsLimit)).map(
				(p: TopPostRow) => ({
					...p,
					competitor_platform: competitorPlatform,
				}),
			);

			return { posts: enrichedPosts };
		},
	);

	return apiSuccess(res, result);
}

export async function handleAggregatedTopPosts(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const rawLimit = req.query.limit as string;
	const limit = parseInt(rawLimit, 10) || 50;
	if (limit < 1 || limit > 100) {
		return apiError(res, 400, "limit must be between 1 and 100");
	}

	const result = await cached(
		`competitor-aggregated-corpus-posts:${user.id}:${limit}`,
		120,
		async () => {
			// Get user's competitors with their avatar URLs and platform
			const { data: competitors } = await db()
				.from("competitors")
				.select("id, username, avatar_url, platform")
				.eq("user_id", user.id);

			if (!competitors?.length) {
				return { posts: [] };
			}

			// Create a map of competitor ID to meta (avatar + platform)
			const competitorMeta = new Map<
				string,
				{ avatarUrl: string; platform: string }
			>();
			(competitors as CompetitorWithMeta[]).forEach((c: CompetitorWithMeta) => {
				competitorMeta.set(c.id, {
					avatarUrl: c.avatar_url || "",
					platform: c.platform || "threads",
				});
			});

			// Fetch corpus posts per competitor to ensure every competitor is
			// represented, then prefer valid engagement when available.
			const postsPerCompetitor = Math.max(
				5,
				Math.ceil(limit / competitors.length),
			);

			// Single query with .in() instead of N+1 loop
			const competitorIds = (competitors as CompetitorWithMeta[]).map(
				(c: CompetitorWithMeta) => c.id,
			);
			const { data: allPostsRaw } = await db()
				.from("competitor_top_posts")
				.select("*")
				.in("competitor_id", competitorIds)
				.order("scraped_at", { ascending: false, nullsFirst: false })
				.limit(postsPerCompetitor * competitors.length);

			// Ensure every competitor is represented (cap per competitor)
			const perCompetitorCount = new Map<string, number>();
			const allPosts: TopPostRow[] = [];
			for (const post of allPostsRaw || []) {
				const count = perCompetitorCount.get(post.competitor_id) || 0;
				if (count < postsPerCompetitor) {
					allPosts.push(post);
					perCompetitorCount.set(post.competitor_id, count + 1);
				}
			}

			// Sort all collected posts by valid engagement when present; otherwise
			// use recency so stats_unavailable rows are not treated as top performers.
			allPosts.sort(sortCompetitorCorpus);
			const topPosts = allPosts.slice(0, limit);

			const enrichedPosts = topPosts.map((post) => ({
				...post,
				competitor_avatar_url:
					competitorMeta.get(post.competitor_id)?.avatarUrl || "",
				competitor_platform:
					competitorMeta.get(post.competitor_id)?.platform || "threads",
			}));

			return { posts: enrichedPosts };
		},
	);

	return apiSuccess(res, result);
}
